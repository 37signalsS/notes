# Vault Agent Injector — автоматическое внедрение в Kubernetes

## Определения

**Vault Agent Injector** — это компонент экосистемы HashiCorp Vault, реализованный в виде **Mutating Admission Webhook** для Kubernetes. Он автоматизирует процесс доставки секретов в поды, внедряя в них контейнеры Vault Agent (init-контейнер или sidecar) на основе аннотаций в манифестах приложений.

**Mutating Admission Webhook** — контроллер Kubernetes, который перехватывает запросы на создание или изменение ресурсов (Pod, Deployment) и модифицирует их спецификацию перед сохранением в `etcd`.

**Persistent Caching** — механизм сохранения токенов и аренды секретов во внутреннем хранилище агента (BoltDB), активируемый в Injector аннотацией `vault.hashicorp.com/agent-cache-enable` (Vault 1.7+). Кэш объединяется между init- и sidecar-контейнерами, что позволяет init-контейнеру получить токен и аренды секретов, а sidecar-контейнеру переиспользовать их после старта пода без повторной аутентификации. Это ускоряет запуск подов и снижает нагрузку на сервер Vault.

## Основные концепции

### Принцип работы и жизненный цикл

1.  **Аннотирование:** Разработчик добавляет аннотации `vault.hashicorp.com/*` в `template.metadata` объекта Deployment или Pod.
2.  **Перехват:** Kubernetes API-сервер отправляет запрос на создание пода в Webhook Injector.
3.  **Модификация:** Injector динамически добавляет:
    *   **Init-контейнер:** Для аутентификации и первичного получения секретов до запуска приложения.
    *   **Sidecar-контейнер:** Для мониторинга изменений и ротации секретов в реальном времени.
    *   **Эфемерные тома (Shared Volumes):** Области памяти (`tmpfs`), через которые агент передает секреты приложению.
4.  **Рендеринг:** Агент использует шаблоны (Consul Template) для записи секретов в файлы внутри общего тома.

### Ключевые аннотации

| Аннотация | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `vault.hashicorp.com/agent-inject` | Включает механизм инъекции для данного пода. | `"false"` |
| `vault.hashicorp.com/role` | Роль в Vault для аутентификации `kubernetes`. | Обязательно |
| `vault.hashicorp.com/agent-inject-secret-<имя>` | Путь в Vault к секрету (KV v2, database, PKI и др.). Суффикс `<имя>` — уникальный идентификатор секрета в пределах пода. | — |
| `vault.hashicorp.com/agent-inject-template-<имя>` | Consul Template для рендеринга конкретного секрета. Без него действует дефолтный шаблон (`map`). | Дефолтный шаблон |
| `vault.hashicorp.com/agent-inject-token` | Шарит Vault-токен с другими контейнерами пода (файл `/vault/secrets/token`). | `"false"` |
| `vault.hashicorp.com/agent-cache-enable` | Включает кэширование и **Persistent Cache** (общий между init и sidecar). | `"false"` |
| `vault.hashicorp.com/agent-cache-use-auto-auth-token` | Кэш аутентифицирует от имени запрашивающей стороны (`force`). | Отключено |
| `vault.hashicorp.com/agent-pre-populate` | Внедряет init-контейнер для предзаполнения тома с секретами до старта приложения. | `"true"` |
| `vault.hashicorp.com/agent-pre-populate-only` | Только init-контейнер (без sidecar). Рекомендуется для `Job`/`CronJob`. | `"false"` |
| `vault.hashicorp.com/agent-init-first` | Форсирует запуск init-контейнера Vault первым (полезно, если другие init-контейнеры зависят от секретов). | `"false"` |
| `vault.hashicorp.com/agent-inject-command-<имя>` | Команда, выполняемая после рендеринга шаблона секрета (например, `SIGHUP` приложению). | — |
| `vault.hashicorp.com/secret-volume-path-<имя>` | Путь на диске, куда будет помещен секрет (по умолчанию весь volume — `/vault/secrets`). | `/vault/secrets` |
| `vault.hashicorp.com/agent-limits-cpu` | Максимальный лимит CPU агента (пустая строка — без лимита). | `"500m"` |
| `vault.hashicorp.com/agent-limits-mem` | Максимальный лимит памяти агента (пустая строка — без лимита). | `"128Mi"` |
| `vault.hashicorp.com/agent-requests-cpu` | Запрос CPU агента. | `"250m"` |
| `vault.hashicorp.com/agent-requests-mem` | Запрос памяти агента. | `"64Mi"` |
| `vault.hashicorp.com/agent-run-as-same-user` | Запуск агента с тем же UID, что и у приложения (требует `SecurityContext.RunAsUser` у первого контейнера). | `"false"` |
| `vault.hashicorp.com/agent-run-as-user` / `agent-run-as-group` | Явные UID/GID для запуска агента. | `100` / `1000` |
| `vault.hashicorp.com/auth-type` | Тип аутентификации (например, `jwt` для WIF/OIDC). | `"kubernetes"` |
| `vault.hashicorp.com/auth-path` | Путь метода аутентификации. | `"auth/kubernetes"` |
| `vault.hashicorp.com/auth-config-<поле>` | Дополнительные параметры метода авто-аутентификации (например, `auth-config-role-id-file-path`). Повторяется многократно. | — |
| `vault.hashicorp.com/service` | Адрес Vault, переопределяющий заданный в Injector (внутренний сервис кластера или внешний URL). | Настроенный в инжекторе |
| `vault.hashicorp.com/tls-skip-verify` | Пропуск проверки TLS-сертификата сервера Vault (не рекомендуется в production). | `"false"` |
| `vault.hashicorp.com/client-max-retries` | Количество повторов запросов к Vault (всего попыток = значение + 1; повторы: 412, все 5xx кроме 501). | `2` |
| `vault.hashicorp.com/log-level` | Уровень логирования агента (`trace`, `debug`, `info` и т.д.). | `"info"` |

Полный список аннотаций (включая JSON-патчи, эфемерные лимиты и телеметрию): [официальная документация](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/injector/annotations).

### Формат рендеринга и каталог секретов

Инжектированные агенты рендерят секреты в общий volume, смонтированный из эфемерного хранилища `emptyDir`/`tmpfs`. По умолчанию:

*   Каталог секретов — `/vault/secrets/`.
*   Для каждого `agent-inject-secret-<имя>` создаётся файл `<имя>` (например, секрет `config` → `/vault/secrets/config`).
*   Без явного шаблона применяется дефолтный шаблон (`agent-inject-default-template`): `map` (по умолчанию) — значения записываются построчно как `KEY=value` по всем ключам мапы KV; `json` — весь секрет сериализуется в один JSON-объект. Регистр ключей сохраняется при `preserve-secret-case`. Для KV v2 значения лежат во вложенной мапе `.Data.data`.

Пример с явным форматом JSON:

```yaml
annotations:
  vault.hashicorp.com/agent-inject-default-template: "json"
  vault.hashicorp.com/agent-inject-secret-config: "secret/data/webapp"
```

Приложение читает готовый файл. Sidecar постоянно перерисовывает файл при ротации секрета (для KV v2 — по `static_secret_render_interval`, для leased — по мере приближения истечения лизы), поэтому приложение должно быть готово перечитывать файл или реально реагировать на его обновление (перезапуск сервиса, перезагрузка конфигурации).

### Установка и архитектура

Injector устанавливается вместе с Helm-чартом Vault (`injector.enabled=true`) и запускается как отдельный Deployment в кластере. Ключевые компоненты:

| Компонент | Назначение |
| :--- | :--- |
| **Deployment `vault-agent-injector`** | Контроллер вебхука: слушает `:443` (mutating admission webhook). |
| **MutatingWebhookConfiguration** | Регистрирует вебхук в API-сервере, определяет область действия (все поды или `namespaceSelector`). |
| **Service `vault-agent-injector-svc`** | Внутренний эндпоинт, через который API-сервер обращается к вебхуку (mTLS). |
| **TLS-сертификат** | Пара «сертификат + ключ» для вебхука; управляется cert-manager или Helm, автоматически ротируется. |

Webhook принимает `AdmissionReview` (POST) и возвращает патч `JSONPatch` со встроенными контейнерами, томами и аннотациями пода. По умолчанию обрабатываются **все** поды кластера. В продуктивных средах рекомендуется ограничить область действия через `namespaceSelector` или изолировать Injector в кластере только для «управляемых» приложений.

```yaml
# Фрагмент helm/values.yaml
injector:
  enabled: true
  replicas: 2                # HA: >1 реплики устойчиво к сбою
  logLevel: info
  extraLabels:
    env: production
```

**Проверка работы:** после деплоя пода с аннотациями вебхук модифицирует его, а в кластере появляются контейнеры `vault-agent-init` и `vault-agent`.

```bash
kubectl get pods -l app=secure-app -o jsonpath='{.items[0].spec.initContainers[0].name}'
# → vault-agent-init
```

> **Важно:** Injector работает на уровне Pod, а не Deployment/StatefulSet. Патчи применяются при создании или перезапуске пода — изменение аннотаций не пересоздаёт уже работающие поды автоматически (нужен rollout).

### Сравнение режимов работы

*   **Init-only (`agent-pre-populate-only: "true"`)**: Идеально для статических паролей и конфигураций, а также для рабочих нагрузок типа `Job`/`CronJob`. Секреты записываются один раз, агент завершается. Снижает потребление ресурсов кластера и гарантирует чистое завершение пода (без sidecar, который удерживал бы его жизненный цикл).
*   **Sidecar-mode**: Необходим для динамических секретов (базы данных, PKI), требующих продления аренды (Lease) и ротации без перезапуска пода.
*   **Init + Sidecar (по умолчанию)**: init-контейнер предзаполняет shared volume до старта приложения, sidecar продолжает обновлять секреты и команды (SIGHUP). Стандарт для большинства продуктовых сценариев.

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

Настройка инжектора для использования облачной или OIDC-идентичности вместо стандартных токенов Kubernetes.

```yaml
metadata:
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/auth-type: "jwt"
    vault.hashicorp.com/auth-path: "auth/gcp-wif"
    vault.hashicorp.com/auth-config-role: "gcp-app-role"
    vault.hashicorp.com/agent-inject-secret-keys: "secret/data/cloud-keys"
```

**Ключевые особенности WIF:**
*   Метод `jwt` использует JWT-токен из `projected` volume (с параметрами `audience`, `expirationSeconds`).
*   Роль Vault настраивается на парсинг облачных claims (например, `aud`).
*   `auth-config-*` параметры задают поля Auto-Auth (например, `role`, `token_path`).

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

1.  **TLS Webhook:** Связь между Kubernetes API и Injector должна быть зашифрована (mTLS); сертификат настраивается автоматически при установке через Helm-чарт и ротируется cert-manager.
2.  **`failurePolicy`:** Для критичных сред установите `Ignore` (чтобы сбой вебхука не блокировал создание подов) и мониторьте алертами. Для строгих требований (секреты обязательны) — `Fail`.
3.  **Изоляция пространств имен:** По умолчанию Injector обрабатывает все поды в кластере. Рекомендуется ограничить область действия с помощью `namespaceSelector` в конфигурации вебхука.
4.  **Авто-отзыв токена:** При завершении пода sidecar может отозвать свой токен (`vault.hashicorp.com/agent-revoke-on-shutdown: "true"`, grace — `agent-revoke-grace`), снижая число активных токенов в Vault.
5.  **Безопасность контейнера:** Используйте аннотацию `vault.hashicorp.com/agent-json-patch` для добавления профилей AppArmor/Seccomp и задавайте `securityContext` (запуск не от root: `agent-run-as-user: "100"`, `agent-set-security-context: "true"`).
6.  **Не используйте** `vault.hashicorp.com/tls-skip-verify: "true"` в production.

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
