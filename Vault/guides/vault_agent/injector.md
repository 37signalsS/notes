# Vault Injector (Auto-Injection) в Kubernetes

**Vault Injector** — это компонент, который автоматически внедряет Vault Agent в поды Kubernetes через механизм **Mutating Admission Webhook**. В отличие от ручного добавления sidecar-контейнера в манифест, Injector делает это автоматически на основе аннотаций.

## Как работает Injector

1. **Аннотирование пода:** В `metadata.annotations` пода добавляются специальные аннотации (например, `vault.hashicorp.com/agent-inject: "true"`).
2. **Перехват запроса:** При создании пода Kubernetes API отправляет запрос в Vault Injector (webhook).
3. **Модификация спецификации:** Injector модифицирует спецификацию пода, добавляя:
   * **Init-контейнер** Vault Agent — для первоначальной аутентификации и получения секретов.
   * **Sidecar-контейнер** Vault Agent — для постоянного мониторинга и ротации секретов (опционально).
   * **Аннотации и volumes** — для монтирования секретов в основной контейнер.
4. **Запуск пода:** Под запускается уже с инжектированными контейнерами Vault Agent.

## Ключевые аннотации

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `vault.hashicorp.com/agent-inject` | Включает инъекцию Vault Agent | `"true"` |
| `vault.hashicorp.com/agent-inject-secret-<name>` | Путь к секрету в Vault для инъекции | `database/creds/readonly:db-creds.txt` |
| `vault.hashicorp.com/role` | Роль Vault для аутентификации Kubernetes | `"my-app-role"` |
| `vault.hashicorp.com/agent-inject-template` | Шаблон для рендеринга секрета | См. ниже |
| `vault.hashicorp.com/agent-inject-command-<name>` | Команда для выполнения после обновления секрета | `"pkill -HUP nginx"` |

## Пример манифеста

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "my-app-role"
    vault.hashicorp.com/agent-inject-secret-db: "database/creds/readonly"
    vault.hashicorp.com/agent-inject-template-db: |
      {{- with secret "database/creds/readonly" -}}
      username={{ .Data.data.username }}
      password={{ .Data.data.password }}
      {{- end }}
    vault.hashicorp.com/agent-inject-command-db: "pkill -HUP myapp"
spec:
  containers:
  - name: app
    image: my-app:latest
    # Секреты будут доступны в /vault/secrets/db
```

## Injector vs Ручной Sidecar

| Критерий | Ручной Sidecar | Vault Injector |
| :--- | :--- | :--- |
| **Гибкость** | Полный контроль над конфигурацией | Ограничено возможностями аннотаций |
| **Сложность** | Требует явного описания в манифесте | Автоматическое внедрение |
| **Поддержка** | Работает в любом Kubernetes | Требует установленного Vault Injector |
| **Ротация секретов** | Настраивается вручную через `command` | Автоматическая через аннотации |
| **Использование** | Сложные сценарии, кастомная логика | Стандартные сценарии, быстрое внедрение |

## Ограничения Injector

* **Требует установленного компонента:** Vault Injector должен быть развёрнут в кластере (обычно через Helm-чарт Vault).
* **Ограниченная гибкость:** Сложные сценарии (например, несколько шаблонов с разной логикой) могут требовать ручного подхода.
* **Версионность:** Аннотации могут меняться между версиями Vault.

> **Примечание:** Injector по умолчанию использует **режим init-контейнера** (завершается после аутентификации). Для постоянной ротации секретов требуется включить sidecar-режим через аннотацию `vault.hashicorp.com/agent-inject-token: "true"` или явное указание в конфигурации Helm.

## Когда использовать Injector

* **Быстрое внедрение:** Не нужно модифицировать манифесты приложений.
* **Стандартные сценарии:** Простая инъекция секретов в файлы или переменные окружения.
* **Централизованное управление:** Политики инъекции управляются через Vault.

## Когда использовать ручной Sidecar

* **Сложная логика:** Кастомные шаблоны, несколько источников секретов.
* **Тонкая настройка:** Контроль над `securityContext`, `resources`, `command`.
* **Air-gapped среды:** Где установка дополнительных компонентов нежелательна.

**Подробное руководство:** [Интеграция Vault с Kubernetes через Secrets Store CSI Driver](./vault_kubernetes_integration.md) — альтернативный подход с использованием CSI-драйвера.

## Связанные темы

* [Vault Agent: основы](./basics.md)
* [Интеграция с Kubernetes](./vault_kubernetes_integration.md)
