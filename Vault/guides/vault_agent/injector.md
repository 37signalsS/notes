# Vault Agent Injector — автоматическое внедрение в Kubernetes

## Определения

**Vault Agent Injector** — это компонент экосистемы HashiCorp Vault, реализованный в виде **Mutating Admission Webhook** для Kubernetes. Он автоматизирует процесс доставки секретов в поды, внедряя в них контейнеры Vault Agent (init-контейнер или sidecar) на основе аннотаций в манифестах приложений.

**Mutating Admission Webhook** — контроллер Kubernetes, который перехватывает запросы на создание или изменение ресурсов (Pod, Deployment) и модифицирует их спецификацию перед сохранением в `etcd`.

**Persistent Caching** — механизм сохранения токенов и аренды секретов во внутреннем хранилище агента (BoltDB), доступный в Injector через аннотации, что ускоряет запуск подов и снижает нагрузку на сервер Vault.

## Основные концепции

### Принцип работы и жизненный цикл

1.  **Аннотирование:** Разработчик добавляет аннотации `vault.hashicorp.com/*` в `template.metadata` объекта Deployment или Pod.
2.  **Перехват:** Kubernetes API-сервер отправляет запрос на создание пода в Webhook Injector.
3.  **Модификация:** Injector динамически добавляет:
    *   **Init-контейнер:** Для аутентификации и первичного получения секретов до запуска приложения.
    *   **Sidecar-контейнер:** Для мониторинга изменений и ротации секретов в реальном времени.
    *   **Эфемерные тома (Shared Volumes):** Области памяти (`tmpfs`), через которые агент передает секреты приложению.
4.  **Рендеринг:** Агент использует шаблоны (Consul Template) для записи секретов в файлы внутри общего тома.

### Ключевые аннотации (2024–2025)

| Аннотация | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `vault.hashicorp.com/agent-inject` | Включает механизм инъекции для данного пода. | `"false"` |
| `vault.hashicorp.com/role` | Роль в Vault для аутентификации `kubernetes`. | Обязательно |
| `vault.hashicorp.com/agent-cache-enable` | Включает **Persistent Cache** (передача токена между init и sidecar). | `"false"` |
| `vault.hashicorp.com/agent-init-first` | Форсирует запуск Vault-init перед всеми другими init-контейнерами. | `"false"` |
| `vault.hashicorp.com/agent-limits-cpu` | Максимальный лимит CPU для контейнера агента. | `"500m"` |
| `vault.hashicorp.com/agent-limits-mem` | Максимальный лимит памяти для контейнера агента. | `"128Mi"` |
| `vault.hashicorp.com/agent-run-as-same-user` | Запуск агента с тем же UID, что и у приложения (для прав доступа). | `"false"` |
| `vault.hashicorp.com/auth-type` | Тип аутентификации (например, `jwt` для WIF/OIDC). | `"kubernetes"` |

### Сравнение режимов работы

*   **Init-only (`agent-pre-populate-only: "true"`)**: Идеально для статических паролей и конфигураций. Секреты записываются один раз, агент завершается. Снижает потребление ресурсов кластера.
*   **Sidecar-mode**: Необходим для динамических секретов (базы данных, PKI), требующих продления аренды (Lease) и ротации без перезапуска пода.

## Практические сценарии

### Сценарий 1: Sidecar с кэшированием и лимитами ресурсов

Оптимальная настройка для продуктивной среды с защитой от чрезмерного потребления ресурсов и быстрым перезапуском.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-app
spec:
  template:
    metadata:
      annotations:
        # Активация инжектора
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "app-role-prod"
        
        # Оптимизация производительности
        vault.hashicorp.com/agent-cache-enable: "true"
        vault.hashicorp.com/agent-run-as-same-user: "true"
        
        # Лимиты ресурсов (Hardening)
        vault.hashicorp.com/agent-limits-cpu: "200m"
        vault.hashicorp.com/agent-limits-mem: "64Mi"
        
        # Определение секретов и шаблонов
        vault.hashicorp.com/agent-inject-secret-config: "secret/data/production/webapp"
        vault.hashicorp.com/agent-inject-template-config: |
          {{- with secret "secret/data/production/webapp" -}}
          export DB_PASSWORD="{{ .Data.data.password }}"
          {{- end }}
    spec:
      serviceAccountName: app-sa
      containers:
      - name: webapp
        image: my-app:latest
```

### Сценарий 2: Использование Workload Identity Federation (WIF)

Настройка инжектора для использования облачной идентичности вместо стандартных токенов Kubernetes.

```yaml
metadata:
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/auth-type: "jwt"
    vault.hashicorp.com/auth-path: "auth/gcp-wif"
    vault.hashicorp.com/auth-config-role: "gcp-app-role"
    vault.hashicorp.com/agent-inject-secret-keys: "secret/data/cloud-keys"
```

### Сценарий 3: Кастомные пути и команды обновления

```yaml
metadata:
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "payment-api"
    # Запись в специфичный каталог
    vault.hashicorp.com/secret-volume-path-db: "/etc/secrets"
    vault.hashicorp.com/agent-inject-secret-db: "database/creds/readonly"
    # Сигнал приложению о смене пароля
    vault.hashicorp.com/agent-inject-command-db: "kill -HUP 1"
```

## Дополнительная информация

### Рекомендации по безопасности

1.  **TLS Webhook:** Убедитесь, что связь между Kubernetes API и Injector зашифрована (настраивается автоматически при установке через Helm-чарт Vault).
2.  **Изоляция пространств имен:** По умолчанию Injector обрабатывает все поды в кластере. Рекомендуется ограничить область действия с помощью `namespaceSelector` в конфигурации вебхука.
3.  **AppArmor/Seccomp:** Используйте аннотацию `vault.hashicorp.com/agent-json-patch` для добавления профилей безопасности в инжектируемые контейнеры.

### Диагностика

| Проблема | Инструмент | Причина |
| :--- | :--- | :--- |
| Контейнеры агента не появляются | `kubectl describe pod` | Проверьте метки `namespace` и наличие аннотации `agent-inject: "true"`. |
| Ошибка `CrashLoopBackOff` агента | `kubectl logs -c vault-agent` | Ошибка аутентификации (проверьте роль) или недоступность сервера Vault. |
| Секрет пуст или не обновляется | `kubectl exec ... -- cat /vault/secrets/...` | Ошибка в синтаксисе шаблона Go или правах политики. |

### Связанные документы

*   **[Интеграция Vault с Kubernetes](../vault_kubernetes_integration.md)** — основной раздел по всем методам (CSI, VSO).
*   **[Vault Agent: основы](./basics.md)** — архитектура и кэширование BoltDB.
*   **[Vault Agent Sidecar](./sidecar_pattern.md)** — детали ручного внедрения.
*   **[Официальный список аннотаций](https://developer.hashicorp.com/vault/docs/platform/k8s/injector/annotations)**
