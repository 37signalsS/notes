# Vault Injector (Auto-Injection) в Kubernetes

## Definitions

**Vault Agent Injector** — компонент Vault, реализованный как **Mutating Admission Webhook** в Kubernetes. Автоматически внедряет Vault Agent (init-контейнер и/или sidecar) в поды на основе аннотаций `vault.hashicorp.com/*`, без необходимости модифицировать манифесты приложений.

**Mutating Admission Webhook** — механизм Kubernetes, позволяющий внешнему сервису модифицировать ресурсы (Pod, Deployment и т.д.) до их создания в API-сервере. Injector перехватывает запросы на создание подов и добавляет контейнеры Vault Agent.

## Basic Concepts

### Принцип работы

1. **Аннотирование пода** — в `metadata.annotations` добавляются аннотации `vault.hashicorp.com/*`.
2. **Перехват** — Kubernetes API отправляет запрос на создание пода в Vault Injector (webhook).
3. **Модификация** — Injector добавляет:
   - **Init-контейнер** Vault Agent — аутентификация и первичное получение секретов.
   - **Sidecar-контейнер** Vault Agent (опционально) — непрерывная ротация секретов.
   - **Shared volumes** — для монтирования секретов в основной контейнер.
4. **Запуск** — под создаётся уже с инжектированными контейнерами.

### Режимы работы

| Режим | Поведение | Когда использовать |
| :--- | :--- | :--- |
| **Init-container** (по умолчанию) | Vault Agent запускается, получает секреты и завершается | Статические секреты, однократное получение |
| **Sidecar** | Vault Agent работает постоянно, обновляет секреты | Динамические секреты с ротацией (DB creds, PKI certs) |

### Ключевые аннотации

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `vault.hashicorp.com/agent-inject` | Включает инъекцию Vault Agent | `"true"` |
| `vault.hashicorp.com/role` | Роль Vault для K8s-аутентификации | `"my-app-role"` |
| `vault.hashicorp.com/agent-inject-secret-<name>` | Путь к секрету в Vault | `database/creds/readonly` |
| `vault.hashicorp.com/agent-inject-template-<name>` | Go-шаблон для рендеринга секрета | См. примеры ниже |
| `vault.hashicorp.com/agent-inject-command-<name>` | Команда после обновления секрета | `"pkill -HUP myapp"` |
| `vault.hashicorp.com/agent-pre-populate-only` | `"false"` — sidecar-режим; `"true"` — только init | `"false"` |
| `vault.hashicorp.com/agent-image` | Образ Vault Agent | `"hashicorp/vault:1.16"` |
| `vault.hashicorp.com/namespace` | Vault namespace (Enterprise) | `"team-a"` |
| `vault.hashicorp.com/tls-skip-verify` | Пропуск TLS-верификации | `"true"` |
| `vault.hashicorp.com/secret-volume-path-<name>` | Путь монтирования секрета | `"/etc/secrets/db"` |

> **Важно:** Аннотация `vault.hashicorp.com/agent-inject-secret-<name>` поддерживает формат `path:filename` для указания имени файла. Пример: `database/creds/readonly:db-creds.txt`.

## Practical Scenarios

### Сценарий 1: Базовая инъекция (init-container)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "my-app-role"
    vault.hashicorp.com/agent-inject-secret-db: "database/creds/readonly"
spec:
  containers:
  - name: app
    image: my-app:latest
    # Секрет доступен в /vault/secrets/db
```

По умолчанию Injector создаёт init-контейнер. После получения секрета он завершается, а файл остаётся в `/vault/secrets/db`.

### Сценарий 2: Sidecar с ротацией секретов

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app-rotating
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "my-app-role"
    vault.hashicorp.com/agent-inject-secret-db: "database/creds/readonly"
    vault.hashicorp.com/agent-pre-populate-only: "false"
    vault.hashicorp.com/agent-inject-template-db: |
      {{- with secret "database/creds/readonly" -}}
      DB_USERNAME={{ .Data.username }}
      DB_PASSWORD={{ .Data.password }}
      {{- end }}
    vault.hashicorp.com/agent-inject-command-db: "pkill -HUP myapp"
spec:
  containers:
  - name: app
    image: my-app:latest
    envFrom:
    - configMapRef:
        name: db-config
    # Перечитывает конфиг при обновлении секрета
```

Аннотация `agent-pre-populate-only: "false"` запускает Vault Agent как sidecar. При ротации учётных данных агент обновляет файл и выполняет указанную команду.

### Сценарий 3: Несколько секретов с разными путями

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-secret-app
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "backend-role"
    vault.hashicorp.com/agent-inject-secret-db: "database/creds/app"
    vault.hashicorp.com/agent-inject-template-db: |
      {{- with secret "database/creds/app" -}}
      export DB_CONN="postgresql://{{ .Data.username }}:{{ .Data.password }}@db:5432/app"
      {{- end }}
    vault.hashicorp.com/secret-volume-path-db: "/etc/secrets/db"
    vault.hashicorp.com/agent-inject-secret-api: "secret/data/api-keys"
    vault.hashicorp.com/secret-volume-path-api: "/etc/secrets/api"
spec:
  containers:
  - name: app
    image: backend:latest
```

Каждый секрет рендерится в отдельный файл и монтируется в свой каталог.

### Сравнение: Injector vs Ручной Sidecar vs CSI Driver

| Критерий | Ручной Sidecar | Vault Injector | CSI Driver |
| :--- | :--- | :--- | :--- |
| **Гибкость** | Полный контроль | Ограничена аннотациями | Средняя (через SecretProviderClass) |
| **Сложность** | Явный манифест | Автоматика по аннотациям | Отдельный ресурс K8s |
| **Ротация** | Ручная настройка | Автоматическая (sidecar) | Автоматическая |
| **Требования** | Любой K8s | Компонент Injector | CSI Driver + Kubelet 1.20+ |
| **Использование** | Кастомная логика | Быстрое внедрение | Статические + динамические секреты |

## Additional Information

### Ограничения

- **Зависимость от компонента:** Injector должен быть развёрнут в кластере (обычно через Helm-чарт Vault).
- **Ограниченная гибкость:** Сложные сценарии (условная логика в шаблонах, несколько источников с зависимостями) требуют ручного sidecar.
- **Версионность:** Аннотации могут меняться между мажорными версиями Vault.
- **TLS:** Webhook требует корректной настройки TLS между API-сервером и Injector.

### Когда использовать Injector

- **Быстрое внедрение** — без модификации манифестов приложений.
- **Стандартные сценарии** — инъекция секретов в файлы/env-переменные.
- **Централизованное управление** — политики управляются через Vault.

### Когда использовать ручной Sidecar

- **Сложная логика** — кастомные шаблоны, несколько источников с зависимостями.
- **Тонкая настройка** — контроль `securityContext`, `resources`, `command`.
- **Air-gapped среды** — без установки дополнительных компонентов в кластер.

### Связанные документы

- Основа: [Vault Agent: основы](./basics.md) — `auto_auth`, `template`, `sink`, `cache`.
- Ручной sidecar: [Vault Agent Sidecar](./sidecar_pattern.md) — `shareProcessNamespace`, `SIGHUP`, `exit_after_auth`.
- Альтернатива: [Интеграция Vault с Kubernetes](../vault_kubernetes_integration.md) — CSI Driver и обзор всех стратегий.
