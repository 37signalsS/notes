# Vault Agent Injector — автоматическое внедрение в Kubernetes

**Актуально для:** Vault 1.17+ (Vault Agent Injector, аннотации, persistent cache)

> **Статус:** Встроенный API Proxy в Vault Agent **deprecated** и **планируется к удалению** (Q2 2026).
> Для новых развёртываний используйте [Vault Proxy](https://developer.hashicorp.com/vault/docs/agent-and-proxy/proxy).

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
| `vault.hashicorp.com/agent-inject-default-template` | Дефолтный шаблон рендеринга: `map` (KEY=value) или `json`. | `"map"` |
| `vault.hashicorp.com/agent-inject-keys` | Список ключей через запятую для рендеринга из KV-секрета (фильтр). | Все ключи |
| `vault.hashicorp.com/agent-inject-keys-file` | Путь к файлу внутри пода с перечислением ключей (один на строку). | — |
| `vault.hashicorp.com/agent-inject-exclude-pattern` | Regex-паттерн для исключения секретов из инъекции (по суффиксу `<имя>`). | — |
| `vault.hashicorp.com/preserve-secret-case` | Сохранять регистр ключей при дефолтном шаблоне `map`. | `"false"` |
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
| `vault.hashicorp.com/agent-set-security-context` | Автоматически применяет `securityContext` к контейнерам агента. | `"false"` |
| `vault.hashicorp.com/agent-json-patch` | JSON-патч для модификации injected-контейнеров (добавление capability, AppArmor, Seccomp). | — |
| `vault.hashicorp.com/auth-type` | Тип аутентификации (например, `approle`, `jwt`, `cert`). | `"kubernetes"` |
| `vault.hashicorp.com/auth-path` | Путь метода аутентификации. | `"auth/kubernetes"` |
| `vault.hashicorp.com/auth-config-<поле>` | Дополнительные параметры метода авто-аутентификации (например, `auth-config-role-id-file-path`). Повторяется многократно. | — |
| `vault.hashicorp.com/service` | Адрес Vault, переопределяющий заданный в Injector (внутренний сервис кластера или внешний URL). | Настроенный в инжекторе |
| `vault.hashicorp.com/tls-skip-verify` | Пропуск проверки TLS-сертификата сервера Vault (не рекомендуется в production). | `"false"` |
| `vault.hashicorp.com/client-max-retries` | Количество повторов запросов к Vault (всего попыток = значение + 1; повторы: 412, все 5xx кроме 501). | `2` |
| `vault.hashicorp.com/log-level` | Уровень логирования агента (`trace`, `debug`, `info` и т.д.). | `"info"` |
| `vault.hashicorp.com/agent-revoke-on-shutdown` | Отзывать токен при завершении пода (graceful shutdown). | `"false"` |
| `vault.hashicorp.com/agent-revoke-grace` | Длительность ожидания перед отзывом токена (например, `5s`). | `"1s"` |

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

### Конфигурация вебхука и область действия

Injector поставляется как Helm-чарт и создаёт `MutatingWebhookConfiguration`, которая определяет, как API-сервер взаимодействует с вебхуком. В продуктивных средах требуется явная настройка двух параметров:

**`failurePolicy`** — поведение API-сервера при недоступности Injector:

| Значение | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `Ignore` | Pod создаётся без инъекции, если вебхук недоступен. | Staging / среды с пониженными требованиями к секретам. |
| `Fail` | Создание пода блокируется, если вебхук недоступен. | Production / среду, где секреты обязательны. |

```yaml
# Часть helm/values.yaml
injector:
  webhook:
    failurePolicy: Fail
    namespaceSelector:
      matchLabels:
        vault-injection: enabled
```

**`namespaceSelector`** — ограничивает область действия вебхука только pods в namespaces с указанными метками. Это снижает нагрузку на Injector и исключает инъекцию в системные пространства имён (`kube-system`, monitoring и др.).

**TLS вебхука:** Certificates управляются cert-manager или Helm-чартом автоматически. Для on-prem и bare-metal кластеров cert-manager может использовать `selfsigned-issuer` или промежуточный CA. Убедитесь, что endpoint Injector доступен для API-сервера по mTLS.

### Механизм инъекции (JSON Patch)

Injector не пересоздаёт пода, а применяет `JSONPatch` к спецификации Pod при создании. В патч добавляются:

1.  **Init-контейнер `vault-agent-init`** (если `agent-pre-populate-only: "false"` или не установлен):
    *   Выполняет аутентификацию в Vault.
    *   Рендерит секреты в shared volume.
    *   Завершается после успешного рендеринга.
2.  **Sidecar-контейнер `vault-agent`** (если `agent-pre-populate-only: "false"`):
    *   Запускается параллельно с приложением.
    *   Поддерживает аренды (Lease), продлевает токен, перерисовывает секреты.
3.  **Shared volume `vault-secrets`**:
    *   Тип `emptyDir` с `medium: Memory` (tmpfs) по умолчанию.
    *   Монтируется в init-контейнер (запись) и приложение (чтение).
4.  **Волатильные тома** для TLS-сертификатов и CA (если `service` указывает на внешний Vault).

Пример патча (сокращённо):

```json
[
  { "op": "add", "path": "/spec/initContainers/-", "value": { "name": "vault-agent-init", ... } },
  { "op": "add", "path": "/spec/containers/-", "value": { "name": "vault-agent", ... } },
  { "op": "add", "path": "/spec/volumes/-", "value": { "name": "vault-secrets", "emptyDir": { "medium": "Memory" } } }
]
```

Просмотреть фактические патчи для пода можно через audit-логи Kubernetes API-сервера или перехватив AdmissionReview запросы (например, через `kubectl proxy` и `tcpdump` на Injector).

### Сравнение режимов работы

*   **Init-only (`agent-pre-populate-only: "true"`)**: Идеально для статических паролей и конфигураций, а также для рабочих нагрузок типа `Job`/`CronJob`. Секреты записываются один раз, агент завершается. Снижает потребление ресурсов кластера и гарантирует чистое завершение пода (без sidecar, который удерживал бы его жизненный цикл).
*   **Sidecar-mode**: Необходим для динамических секретов (базы данных, PKI), требующих продления аренды (Lease) и ротации без перезапуска пода.
*   **Init + Sidecar (по умолчанию)**: init-контейнер предзаполняет shared volume до старта приложения, sidecar продолжает обновлять секреты и команды (SIGHUP). Стандарт для большинства продуктовых сценариев.

### Жизненный цикл и завершение пода

При нормальном завершении пода (`kubectl delete`, rolling update, scale down) sidecar получает `SIGTERM` **последним** — после остановки основных контейнеров. Это верно как для legacy-сайдкаров (K8s < 1.29), так и для native sidecar (K8s 1.29+, `initContainer` с `restartPolicy: Always`), который Kubernetes гарантирует завершить **последним** (согласно [K8s docs](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/)). Агент должен успеть:

1.  Отозвать активные аренды (Lease) в Vault, если настроен `agent-revoke-on-shutdown: "true"`.
2.  Отозвать активные аренды (Lease) в Vault, если настроен `agent-revoke-on-shutdown: "true"`.
3.  Корректно закрыть BoltDB кэш (если используется `agent-cache-enable` с `persist "kubernetes"`), чтобы избежать повреждения файла при последующем запуске.

Если под завершается аварийно (`OOMKilled`, `node failure`), токен может остаться активным до истечения TTL. Vault автоматически отзывает истёкшие токены, но для критичных сред рекомендуется использовать shorter TTL и Monitor alerts на активные сессии.

Для init-only режима (`agent-pre-populate-only: "true"`) init-контейнер завершается после рендеринга, и его жизненный цикл не влияет на завершение пода — приложение работает как обычно.

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

### Сценарий 2: AppRole аутентификация

Использование AppRole для пода с известным `serviceAccount`, без зависимости от ServiceAccount токена Kubernetes. Подходит для сред, где требуется отдельный учётные данные для каждого приложения или группа приложений.

```yaml
metadata:
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/auth-type: "approle"
    vault.hashicorp.com/auth-path: "auth/approle"
    vault.hashicorp.com/role: "payment-api-approle"
    
    # Передача Role ID и Secret ID через файлы (рекомендуется)
    # Secret ID создаётся заранее и помещается в Kubernetes Secret
    vault.hashicorp.com/auth-config-role-id-file-path: "/vault/secrets/role-id"
    vault.hashicorp.com/auth-config-secret-id-file-path: "/vault/secrets/secret-id"
    
    vault.hashicorp.com/agent-inject-secret-config: "secret/data/payment/config"
    vault.hashicorp.com/agent-inject-template-config: |
      {{- with secret "secret/data/payment/config" -}}
      export PAYMENT_API_KEY="{{ .Data.data.api_key }}"
      {{- end }}
```

**Ключевые особенности AppRole:**
*   `role-id` и `secret-id` передаются через файлы, чтобы не expose их в Deployment манифесте.
*   `secret-id` может быть ограничен по времени (`secret_id_ttl`) или числу использований в Vault.
*   Injector сам выполняет логин AppRole и получает токен, после чего работает как обычно.

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

### Сценарий 4: CronJob с init-only режимом

Для задач, которые не требуют динамической ротации секретов (например, миграции базы данных, пакетные расчёты), используется `agent-pre-populate-only: "true"`. Init-контейнер получает секреты, записывает их в shared volume и завершается. Sidecar не создаётся, что снижает потребление ресурсов и гарантирует корректное завершение пода после выполнения Job.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: db-migrate
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        metadata:
          annotations:
            vault.hashicorp.com/agent-inject: "true"
            vault.hashicorp.com/agent-pre-populate-only: "true"
            vault.hashicorp.com/role: "migration-role"
            vault.hashicorp.com/agent-inject-secret-db-creds: "database/creds/migrate"
            vault.hashicorp.com/agent-inject-template-db-creds: |
              {{- with secret "database/creds/migrate" -}}
              export DB_USER="{{ .Data.data.username }}"
              export DB_PASS="{{ .Data.data.password }}"
              {{- end }}
        spec:
          serviceAccountName: migration-sa
          restartPolicy: OnFailure
          containers:
          - name: migrate
            image: my-app:migrate
            command: ["./run-migrations.sh"]
```

> **Важно:** в `restartPolicy: OnFailure` init-контейнер завершается успешно, и Job продолжает нормальное выполнение. При `Never` или если init-контейнер завершается с ошибкой — Pod остаётся в состоянии `Init:Error`.

## Операции и команды

### Поддерживаемые версии Kubernetes

[Официальная документация](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/injector) Vault поддерживает следующие minor releases Kubernetes (текущие):

- **K8s 1.36, 1.35, 1.34, 1.33, 1.32** — полностью протестированы.
- **K8s 1.29** — минимальная версия для **native sidecar containers** (`initContainer` с `restartPolicy: Always`). На старших версиях применяется классический init+sidecar паттерн.

### Мониторинг и метрики

Vault Agent Injector экспортирует Prometheus-метрики. Чтобы включить 수бор метрик, установите `injector.metrics.enabled: true` в Helm-чарте.

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `vault_agent_injector_request_queue_length` | Количество ожидающих webhook-запросов. | Рост >100 в течение 5 мин — возможен перегрев. |
| `vault_agent_injector_webhook_latency` | Время обработки AdmissionReview. | >5s — проверьте нагрузку и настройки `timeoutSeconds`. |
| `vault_agent_injector_errors` | Ошибки обработки запросов. | >0 за 10 мин — проверьте логи. |

```bash
# Проверка состояния Injector Pod
kubectl get pods -n vault -l app.kubernetes.io/name=vault-agent-injector -o wide

# Просмотр метрик (через prometheus или direct scrape)
kubectl port-forward -n vault svc/vault-agent-injector-svc 9102:9102 &
curl -s http://localhost:9102/metrics | grep vault_agent_injector
kill %1

# Проверка MutatingWebhookConfiguration
kubectl get mutatingwebhookconfiguration vault-agent-injector-cfg -o name
```

### Health check и readiness

```bash
# Проверка готовности вебхука (API-сервер должен получать 200)
kubectl get --raw /apis/admissionregistration.k8s.io/v1/mutatingwebhookconfigurations \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | grep vault

# Проверка, что Service endpoint существует
kubectl get endpoints -n vault vault-agent-injector-svc -o wide
```

### Журналирование и rotation

Injector запускается как Deployment и пишет логи в stdout. Для bare-metal или on-prem кластеров с локальным сбором логов (journald на нодах) рекомендуется настроить rotation:

```ini
# /etc/systemd/journald.conf.d/vault-agent-injector.conf  (на нодах K8s)
[Journal]
SystemMaxUse=1G
MaxFileSec=1week
MaxRetentionSec=4week
```

Для k8s-кластеров с `kubectl logs` агрегатором (Fluentd, Loki, etc.) настройте `logLevel: info` или `logLevel: debug` в Helm values для детального аудита:

```yaml
# helm/values.yaml
injector:
  logLevel: info
```

### Команды диагностики

```bash
# Проверка MutatingWebhookConfiguration
kubectl get mutatingwebhookconfigurations vault-agent-injector-cfg -o yaml

# Проверка отзыпа логов Injector
kubectl logs -n vault -l app.kubernetes.io/name=vault-agent-injector --tail=100

# Аудит патчей через audit-логи API-сервера
kubectl get --raw /apis/auditregistration.k8s.io/v1alpha1/auditsinks
```

## Устранение неполадок

### Типовые ошибки

| Проблема | Инструмент | Причина и решение |
| :--- | :--- | :--- |
| **Контейнеры агента не появляются** | `kubectl describe pod` | Проверьте метки `namespace` и наличие аннотации `agent-inject: "true"`. Убедитесь, что `failurePolicy` не `Ignore` при недоступном Injector. |
| **Ошибка `CrashLoopBackOff` агента** | `kubectl logs -c vault-agent` | Ошибка аутентификации (проверьте роль) или недоступность сервера Vault. Проверьте `service` аннотацию и DNS. |
| **Секрет пуст или не обновляется** | `kubectl exec ... -- cat /vault/secrets/...` | Ошибка в синтаксисе шаблона Go или правах политики. Проверьте `agent-inject-template-*` и наличие `read` на пути. |
| **Pod в `Init:CrashLoopBackOff`** | `kubectl logs -c vault-agent-init` | Init-контейнер не может аутентифицироваться (неверный `role`, `auth-path` или `auth-config-*`). Проверьте `auth-type`. |
| **Секрет не появляется в `/vault/secrets`** | `kubectl exec ... -- ls /vault/secrets/` | Агент не завершил рендеринг (проверьте логи), или `secret-volume-path-*` указывает в другой каталог. |
| **Приложение стартует раньше секретов** | `kubectl describe pod` / `kubectl logs` | Классический sidecar без `startupProbe`/`readinessProbe`, или `agent-init-first: "false"` с race condition. Используйте native sidecar или explicit probe. |
| **Приложение не получает `SIGHUP`** | Проверка `shareProcessNamespace` и `SYS_PTRACE` | Не совпадает имя процесса, нет общего PID-namespace или capability. Используйте `agent-inject-command-*` с явной командой или `shareProcessNamespace: true`. |
| **Токен/кэш теряется при перезапуске** | Проверка `persist` в конфиге | Не настроен `persist "kubernetes"`, или путь к тому агента не персистентный. Используйте `emptyDir` с размером или PV для кэша. |
| **Vault недоступен при старте пода** | `kubectl logs -c vault-agent-init` | Проверьте `service` аннотацию, `ca_cert` (если используется mTLS), и сетевое подключение. Агент повторит попытку (см. `client-max-retries`). |
| **Токены не отзываются при завершении** | `vault token lookup <token>` после удаления пода | Не установлена `agent-revoke-on-shutdown: "true"` или grace период слишком короткий (`agent-revoke-grace`). |
| **Webhook не применяет патчи** | `kubectl get mutatingwebhookconfigurations` | Проверьте `failurePolicy`, `namespaceSelector` и метки namespace пода. Webhook может быть отключён на уровне namespace. |
| **Ошибка `TLS handshake error`** | `kubectl logs -c vault-agent` | Несоответствие CA-сертификата на Injector и Vault. Проверьте `ca_cert` в конфиге Injector и `tls-skip-verify` аннотацию. |

### Валидация и отладка вебхука

Перед деплоем в production проверьте корректность Injector:

```bash
# 1. Проверьте MutatingWebhookConfiguration
kubectl get mutatingwebhookconfigurations vault-agent-injector-cfg -o yaml

# 2. Проверьте, что Injector отвечает на AdmissionReview
kubectl get pods -n vault -l app.kubernetes.io/name=vault-agent-injector

# 3. Проверьте логи Injector на предмет ошибок валидации
kubectl logs -n vault -l app.kubernetes.io/name=vault-agent-injector --tail=100

# 4. Создайте тестовый Pod и проверьте, что аннотации применились
kubectl run test-vault --image=busybox --restart=Never --dry-run=client -o yaml | grep agent-inject
kubectl get pod test-vault -o yaml | grep -A5 "initContainers"
```

Для аудита применённых патчей используйте audit-логи API-сервера или включите `logLevel: debug` в Injector (Helm values).

### Обновление конфигурации и rollout

Injector применяет патчи только при **создании** Pod. Изменение аннотаций в существующем Deployment не влияет на работающие поды. Для применения новых аннотаций:

```bash
# Стратегия 1: Rolling update (по умолчанию)
kubectl rollout restart deployment/secure-app -n prod

# Стратегия 2: Изменение реплик (для Job/CronJob)
kubectl patch cronjob db-migrate -p '{"spec":{"suspend":true}}'
kubectl delete jobs --all -n prod
kubectl patch cronjob db-migrate -p '{"spec":{"suspend":false}}'

# Стратегия 3: Прямое удаление подов (Deployment)
kubectl delete pod -l app=secure-app -n prod --grace-period=0 --force
# Deployment автоматически создаст новые поды с новыми аннотациями
```

> **Важно:** при `agent-pre-populate-only: "true"` (CronJob, Job) новый Pod получит свежие секреты при каждом запуске. Для `agent-pre-populate: "true"` (init + sidecar) требуется полный rollout Deployment.

## Лучшие практики

### Безопасность

1.  **TLS Webhook:** Связь между Kubernetes API и Injector должна быть зашифрована (mTLS); сертификат настраивается автоматически при установке через Helm-чарт и ротируется cert-manager.
2.  **`failurePolicy`:** Для критичных production-сред, где секреты обязательны, установите `Fail` (создание пода блокируется при недоступном Injector). Для staging-сред с пониженными требованиями к секретам — `Ignore` (pod создаётся без инъекции). В обоих случаях настраивайте алерты на метрики Injector (`vault_agent_injector_request_queue_length`).
3.  **Изоляция пространств имен:** По умолчанию Injector обрабатывает все поды в кластере. Рекомендуется ограничить область действия с помощью `namespaceSelector` в конфигурации вебхука.
4.  **Авто-отзыв токена:** При завершении пода sidecar может отозвать свой токен (`vault.hashicorp.com/agent-revoke-on-shutdown: "true"`, grace — `agent-revoke-grace`), снижая число активных токенов в Vault.
5.  **Безопасность контейнера:** Используйте аннотацию `vault.hashicorp.com/agent-json-patch` для добавления профилей AppArmor/Seccomp и задавайте `securityContext` (запуск не от root: `agent-run-as-user: "100"`, `agent-set-security-context: "true"`).
6.  **Не используйте** `vault.hashicorp.com/tls-skip-verify: "true"` в production.
7.  **Резервное копирование TLS-сертификатов:** сертификат вебхука (используемый API-сервером для mTLS к Injector) требует backup. При использовании cert-manager сертификаты ротируются автоматически, но `Secret` с сертификатом в неймспейсе `vault` должен быть включён в backup-процедуру.

### Управление версиями и rollout

8.  **Избегайте `latest` образа:** при установке через Helm явно фиксируйте `injector.image.tag` и `vault.image.tag` для воспроизводимости.
9.  **Регулярные rollout:** после обновления конфигурации Vault (policies, roles) перезапускайте зависимые Deployment через `kubectl rollout restart`, так как изменения политик не применяются к уже выписанным токенам в работающих подах.

## Дополнительная информация

### Связанные документы

*   **[Интеграция Vault с Kubernetes](../vault_kubernetes_integration.md)** — основной раздел по всем методам (CSI, VSO).
*   **[Vault Agent: основы](./basics.md)** — архитектура и кэширование BoltDB.
*   **[Vault Agent Sidecar](./sidecar_pattern.md)** — детали ручного внедрения.
