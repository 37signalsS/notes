# Vault Injector — автоматическое внедрение агента в Kubernetes

## Определения

**Vault Agent Injector** — компонент Vault, реализованный как **Mutating Admission Webhook** в Kubernetes. Он автоматически внедряет контейнеры Vault Agent (init-контейнер или sidecar) в поды на основе аннотаций, избавляя от необходимости вручную модифицировать манифесты приложений.

**Mutating Admission Webhook** — механизм Kubernetes, позволяющий внешним сервисам модифицировать ресурсы (Pod, Deployment и др.) на этапе их создания в API-сервере. Injector перехватывает запросы и добавляет необходимые конфигурации Vault Agent.

## Основные концепции

### Принцип работы

1. **Аннотирование:** в `metadata.annotations` пода добавляются параметры `vault.hashicorp.com/*`.
2. **Перехват:** Kubernetes API отправляет запрос на создание пода в webhook Injector.
3. **Модификация:** Injector добавляет в спецификацию пода:
    * **Init-контейнер Vault Agent:** для аутентификации и первичного получения секретов.
    * **Sidecar-контейнер Vault Agent:** для непрерывного обновления (ротации) секретов (опционально).
    * **Shared volumes:** общие тома для передачи секретов между агентом и основным приложением.
4. **Запуск:** под создается в кластере уже с внедренными компонентами.

### Режимы работы

| Режим | Поведение | Сценарий использования |
| :--- | :--- | :--- |
| **Init-container** | Агент запускается, получает секреты и завершается | Статические секреты, не требующие обновления без перезапуска |
| **Sidecar** | Агент работает постоянно в фоне основного пода | Динамические секреты с ротацией (пароли БД, сертификаты) |

### Ключевые аннотации

| Аннотация | Описание | Пример значения |
| :--- | :--- | :--- |
| `vault.hashicorp.com/agent-inject` | Включает механизм инъекции | `"true"` |
| `vault.hashicorp.com/role` | Роль Vault для аутентификации | `"my-app-role"` |
| `vault.hashicorp.com/agent-inject-secret-<name>` | Путь к секрету в Vault | `database/creds/readonly` |
| `vault.hashicorp.com/agent-inject-template-<name>` | Go-шаблон для оформления секрета | см. примеры ниже |
| `vault.hashicorp.com/agent-inject-command-<name>` | Команда после обновления секрета | `"pkill -HUP myapp"` |
| `vault.hashicorp.com/agent-pre-populate-only` | Режим работы: `"false"` — sidecar; `"true"` — init | `"false"` |
| `vault.hashicorp.com/agent-image` | Используемый образ агента | `"hashicorp/vault:1.16"` |
| `vault.hashicorp.com/secret-volume-path-<name>` | Кастомный путь монтирования | `"/etc/secrets/db"` |

## Практические сценарии

### Сценарий 1: Базовая инъекция (init-container)

В этом сценарии секрет будет получен один раз при старте и доступен по пути `/vault/secrets/db`.

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
```

### Сценарий 2: Sidecar с динамической ротацией

Агент будет отслеживать изменения в Vault, обновлять файл и уведомлять приложение сигналом SIGHUP.

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
```

### Сценарий 3: Несколько секретов в разные каталоги

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-secret-app
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "backend-role"
    # Первый секрет
    vault.hashicorp.com/agent-inject-secret-db: "database/creds/app"
    vault.hashicorp.com/secret-volume-path-db: "/etc/secrets/db"
    # Второй секрет
    vault.hashicorp.com/agent-inject-secret-api: "secret/data/api-keys"
    vault.hashicorp.com/secret-volume-path-api: "/etc/secrets/api"
spec:
  containers:
  - name: app
    image: backend:latest
```

## Дополнительная информация

### Сравнение методов интеграции

| Критерий | Vault Injector | Ручной Sidecar | CSI Driver |
| :--- | :--- | :--- | :--- |
| **Сложность** | Низкая (аннотации) | Высокая (явный YAML) | Средняя (CRD) |
| **Гибкость** | Ограничена аннотациями | Полный контроль | Нативная для K8s |
| **Ротация** | Автоматическая | Настраиваемая | Автоматическая |
| **Требования** | Компонент Injector | Любой K8s | CSI Driver в кластере |

### Ограничения и рекомендации

* **Установка:** Injector должен быть предварительно развернут в кластере (обычно через официальный Helm-чарт Vault).
* **Сложные шаблоны:** при необходимости сложной логики (зависимости между несколькими секретами) рекомендуется использовать ручной Sidecar.
* **Безопасность:** Webhook требует корректной настройки TLS между Kubernetes API и сервисом Injector.

### Связанные документы

* [Vault Agent: основы](./basics.md) — базовые блоки `auto_auth` и `template`.
* [Vault Agent Sidecar](./sidecar_pattern.md) — паттерн ручного внедрения sidecar.
* [Интеграция Vault с Kubernetes](../vault_kubernetes_integration.md) — общий обзор стратегий, включая CSI Driver.
