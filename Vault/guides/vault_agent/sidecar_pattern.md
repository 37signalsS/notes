# Vault Agent Sidecar — динамическое обновление конфигурации

## Определения

**Vault Agent Sidecar** — это архитектурный паттерн использования `vault-agent` в качестве постоянно работающего вспомогательного контейнера в Kubernetes-поде. Он отвечает за аутентификацию, получение секретов и их динамическое обновление в конфигурационных файлах основного приложения без перезапуска пода.

**Динамическая ротация (Dynamic Rotation)** — процесс автоматического обновления секретов (например, паролей БД или сертификатов) в работающем приложении. Агент отслеживает изменения в Vault, перезаписывает файлы и отправляет сигнал приложению (обычно `SIGHUP`) для перечитывания конфигурации.

**Native Sidecar Containers (K8s 1.29+)** — механизм Kubernetes (beta с 1.28, стабилен с 1.29, см. KEP-3839), позволяющий определять вспомогательные контейнеры в блоке `initContainers` с параметром `restartPolicy: Always`. Это гарантирует, что Vault Agent запустится раньше основного приложения (основные контейнеры стартуют только после перехода агента в состояние `Ready`), останется доступным на протяжении всего жизненного цикла пода и завершится **после** остановки основных контейнеров, получая `SIGTERM`. Ключевое отличие от обычного sidecar (контейнер в `containers`) — гарантированный порядок запуска и завершения, что устраняет race conditions при первичном рендеринге секретов.

**Persistent Cache (BoltDB)** — механизм сохранения токенов и аренд секретов во внутреннем хранилище агента (файл `cache.db`), активируемый блоком `cache { persist "kubernetes" { ... } }`. Позволяет агенту восстанавливать состояние после перезапуска контейнера без повторной аутентификации, что критично для сценариев с лимитированными `secret_id_ttl` или дорогой аутентификацией.

**Auto-Auth** — подсистема Vault Agent, которая автоматически выполняет вход в Vault, продлевает токен и перевыпускает его при истечении. Поддерживаемые методы: `kubernetes` (ServiceAccount JWT), `approle` (RoleID/SecretID), `token`, `jwt`/`oidc`.

## Основные концепции

### Механизмы взаимодействия контейнеров

В паттерне Sidecar агент и приложение должны обмениваться данными и сигналами.

1.  **Общий том (Shared Volume):** Используется `emptyDir` с типом `Memory` (tmpfs) для передачи секретов в виде файлов. Это исключает запись чувствительных данных на физический диск узла. Каталог монтируется в агент (запись) и в приложение (чтение).
2.  **Сигнализация (Signaling):** Для отправки сигналов (например, `pkill -HUP`) между контейнерами используются следующие настройки:
    *   **`shareProcessNamespace: true`**: Позволяет процессам в разных контейнерах одного пода видеть друг друга в общем PID-пространстве.
    *   **`SYS_PTRACE` Capability**: Разрешает агенту отправлять сигналы процессам других контейнеров (требуется, если приложение не поддерживает перечитывание файла вручную).
3.  **Идентификация пользователя (UID):** Для корректной работы сигналов и прав доступа к файлам рекомендуется запускать агента и приложение под одним `runAsUser`. Для секретов, монтируемых только на чтение, это не обязательно.
4.  **Probe готовности (Readiness Probe):** На Vault Agent рекомендуется настраивать `readinessProbe`/`startupProbe`. С нативными сайдкарами основные контейнеры не начнут работу, пока агент не перейдёт в состояние `Ready`, что гарантирует готовность файлов с секретами до старта приложения.
5.  **Лимиты ресурсов:** Ресурсы сайдкара суммируются с ресурсами основных контейнеров при расчёте лимитов пода, поэтому для агента всегда задаются явные `requests`/`limits` (CPU, память).

### TLS и связь с Vault

Агент должен устанавливать защищённое соединение с сервером Vault. В конфигурации `vault { ... }` используются параметры:

*   **`ca_cert`** — путь к CA-сертификату Vault (монтируется через Secret). Если сертификат самоподписанный, укажите его явно; для публичных CA проверка встроена.
*   **`client_cert` / `client_key`** — опциональная mTLS-аутентификация агента на уровне TLS (не путать с auth method внутри Vault). Используется, когда Vault требует сертификат клиента для принятия соединения.
*   **`tls_skip_verify = true`** — запрещён в production. Отключает проверку подлинности сертификата, что делает соединение уязвимым для MITM-атак.
*   **`retry { ... }`** — поведение при недоступности Vault. `num_retries` задаёт количество попыток; `backoff` — стратегию задержки между ними. По умолчанию Agent выполняет 12 попыток с экспоненциальным backoff.

Для настройки TLS в Deployment:

```yaml
volumes:
- name: agent-tls
  secret:
    secretName: vault-agent-tls
    items:
    - key: ca.crt
      path: tls-ca-cert.crt
    - key: tls.crt
      path: tls.crt
    - key: tls.key
      path: tls.key
```

### Поведение при недоступности Vault

При потере связи с Vault во время работы пода агент действует по следующему алгоритму:

1.  **Первичная аутентификация:** если агент не может аутентифицироваться при старте (Vault недоступен), он перезапускает попытки согласно `retry { num_retries = N }`. Если попытки исчерпаны и `exit_on_retry_failure = true` (рекомендуется для Deployment), агент завершается с ошибкой, и Pod перезапускается.
2.  **Динамическая ротация:** при падении Vault агент продолжает обслуживать последние известные секреты из кэша (BoltDB или файлы в памяти). Новые изменения не будут подхвачены до восстановления связи.
3.  **Продление токена:** если агент держит активный токен (TTL > 0), продление (`renew`) тоже зависит от доступности Vault. При истечении TTL без продления токен становится невалидным, но агент автоматически перелогинивается при восстановлении соединения.
4.  **Graceful degradation:** в отличие от Injector, ручной sidecar не блокирует перезапуск пода при недоступности Vault — это определяется readinessProbe и restartPolicy контейнера.

### Жизненный цикл с Native Sidecars

При использовании нативных сайдкаров (K8s 1.29+):
1.  Vault Agent запускается как `initContainer` с `restartPolicy: Always`.
2.  Агент проходит аутентификацию и рендерит секреты (первичный рендеринг до старта приложения).
3.  Kubernetes переходит к запуску основного контейнера только после того, как агент станет `Ready` (если настроена `startupProbe`/`readinessProbe`).
4.  На протяжении работы пода агент поддерживает секреты актуальными (sidecar-роль): отслеживает лизы, продлевает токен, перерисовывает шаблоны по `static_secret_render_interval` (KV v2) или при ротации динамических секретов.
5.  При завершении пода агент получает `SIGTERM` и выключается **последним** — после остановки основных контейнеров, обеспечивая доступность секретов до полной остановки приложения.

**Вариант «init-only» для ручного внедрения:** если приложение не требует динамического обновления (статические секреты), вместо sidecar можно использовать обычный init-контейнер без `restartPolicy: Always`, который один раз рендерит секреты и завершается. Это снижает потребление ресурсов. Для динамических секретов (БД, PKI) обязателен sidecar с пролонгацией лиз.

### Сравнение: ручной Sidecar vs Injector

| Характеристика | Ручной Sidecar | Injector |
| :--- | :--- | :--- |
| **Способ описания** | Явный манифест Pod/Deployment | Аннотации в Deployment |
| **Гибкость HCL** | Полная (любые блоки конфига) | Ограничена поддерживаемыми аннотациями |
| **Динамические секреты** | Полная поддержка | Поддержка (через `agent-inject-secret-*`) |
| **AppRole auth** | Полная конфигурация в HCL | Поддерживается через аннотации |
| **Кэширование** | Явное описание `cache { persist }` | Активируется аннотацией `agent-cache-enable` |
| **Мульти-Vault / Failover** | Можно описать несколько `vault { ... }` блоков | Ограничено одним `VAULT_ADDR` |
| **Обнаруживаемость** | Читаемость манифеста | Скрыто в аннотациях |
| **Версия образа** | Фиксируется явно в `image:` | Управляется чартом Vault |

**Когда использовать ручной sidecar:** нужна нестандартная конфигурация агента (несколько Vault-инстансов, AppRole с внешним SecretID, кастомный `listener` для API Proxy), требуется полный контроль над probes и lifecycle, или Injector не развёрнут в кластере.

## Практические сценарии

### Сценарий 1: Настройка Vault Agent для Sidecar

Файл конфигурации агента (`agent-config.hcl`) должен настраивать автоматическую аутентификацию (Auto-Auth) и команду перезагрузки. Конфиг монтируется в контейнер агента через ConfigMap.

```hcl
pid_file = "/tmp/agent.pid"

vault {
  address = "https://vault.example.com:8200"
  # Связь с Vault по mTLS (агент должен иметь ссылку на CA-сертификат)
  ca_cert = "/etc/vault/agent/tls-ca-cert.crt"
  # Поведение при недоступности сервера
  retry {
    num_retries = 5
  }
}

auto_auth {
  method "kubernetes" {
    mount_path = "auth/kubernetes"
    config = {
      role = "webapp-role"
      token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    }
  }

  # Публикация токена в файл (опционально, для API Proxy и диагностики)
  sink "file" {
    config = {
      path = "/tmp/.vault-token"
    }
  }
}

cache {
  use_auto_auth_token = true

  # Persistent Cache (BoltDB): восстановление состояния при перезапуске
  # контейнера без повторной аутентификации.
  persist "kubernetes" {
    path = "/tmp/vault-agent-cache"
    keep_after_import = true
  }
}

template_config {
  static_secret_render_interval = "10m" # KV v2: период перерисовки статики
  exit_on_retry_failure = true
  # Максимальное количество одновременных соединений с Vault
  max_connections_per_host = 20
}

template {
  source      = "/vault/templates/db.ctmpl"
  destination = "/vault/secrets/config.yaml"

  # Сигнал SIGHUP основному приложению. Устаревший синтаксис command заменён
  # на блок exec (с Vault 1.19+ предпочтительно; требует shared PID-namespace).
  exec {
    command = ["pkill", "-HUP", "myapp"]
    timeout = "30s"
  }

  # Ожидание стабилизации при массовых изменениях
  wait {
    min = "2s"
    max = "10s"
  }
}
```

> **Примечание (Vault 2.x):** версия сервера и образ агента указаны в примерах ниже. Актуальный стабильный релиз Vault на момент документирования — **2.0.x** (GA 14.04.2026); ветка 1.21.x остаётся поддерживаемой и совместимой.

### Сценарий 2: Манифест Deployment с ручным Sidecar

Пример реализации через классический Sidecar (для версий K8s ниже 1.29, специфичных требований или обратной совместимости).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-sidecar
spec:
  replicas: 1
  template:
    spec:
      # Общее PID-пространство для отправки SIGHUP агентом приложению
      shareProcessNamespace: true
      serviceAccountName: webapp-sa
      volumes:
      - name: secrets-volume
        emptyDir: { medium: Memory }
      - name: agent-config
        configMap:
          name: vault-agent-config
      - name: agent-tls
        secret:
          secretName: vault-agent-tls
      containers:
      - name: webapp
        image: my-app:latest
        volumeMounts:
        - name: secrets-volume
          mountPath: /etc/app
          readOnly: true
        readinessProbe:
          exec:
            command: ["test", "-f", "/etc/app/config.yaml"]
          initialDelaySeconds: 5
          periodSeconds: 5
      - name: vault-agent
        image: hashicorp/vault:1.21.4
        args: ["agent", "-config=/etc/vault/agent-config.hcl"]
        volumeMounts:
        - name: secrets-volume
          mountPath: /vault/secrets
        - name: agent-config
          mountPath: /etc/vault
          readOnly: true
        - name: agent-tls
          mountPath: /etc/vault/agent/tls
          readOnly: true
        securityContext:
          capabilities:
            add: ["SYS_PTRACE"] # Разрешение на отправку сигналов
          runAsNonRoot: true
          readOnlyRootFilesystem: true
          allowPrivilegeEscalation: false
        resources:
          requests:
            cpu: "100m"
            memory: "64Mi"
          limits:
            cpu: "500m"
            memory: "128Mi"
```

Типичная схема взаимодействия с классическим sidecar: агент и приложение стартуют параллельно, поэтому для гарантии того, что файл секретов готов до первого чтения приложением, используются `readinessProbe` (см. выше) или init-контейнер для первичного рендеринга.

### Сценарий 3: AppRole аутентификация

Использование AppRole для пода с известным `serviceAccount`, без зависимости от ServiceAccount токена Kubernetes. Подходит для сред, где требуется отдельный учётные данные для каждого приложения или группа приложений.

```hcl
auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    config = {
      role_id_file_path = "/etc/vault/agent/approle/role-id"
      secret_id_file_path = "/etc/vault/agent/approle/secret-id"
      # Удалять SecretID после прочтения для безопасности
      remove_secret_id_file_after_reading = true
    }
  }

  sink "file" {
    config = {
      path = "/tmp/.vault-token"
    }
  }
}
```

Манифест Pod (фрагмент):

```yaml
volumes:
- name: approle-credentials
  secret:
    secretName: webapp-approle
    defaultMode: 0400
containers:
- name: vault-agent
  image: hashicorp/vault:1.21.4
  volumeMounts:
  - name: approle-credentials
    mountPath: /etc/vault/agent/approle
    readOnly: true
```

**Ключевые особенности AppRole:**

*   `role-id` и `secret-id` передаются через файлы, чтобы не expose их в Deployment манифесте.
*   `secret-id` может быть ограничен по времени (`secret_id_ttl`) или числу использований в Vault.
*   Для ServiceAccount-подов роль AppRole должна иметь политики, достаточные для чтения секретов.

### Сценарий 4: Использование Native Sidecar (K8s 1.29+)

Механизм исключает race conditions при старте приложения: основной контейнер стартует только после готовности агента. Агент объявляется как init-контейнер с `restartPolicy: Always` и остаётся жить весь жизненный цикл пода.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: webapp-native-sidecar
  labels:
    app: webapp
spec:
  shareProcessNamespace: true
  serviceAccountName: webapp-sa
  volumes:
  - name: secrets-volume
    emptyDir: { medium: Memory }
  - name: agent-config
    configMap:
      name: vault-agent-config
  initContainers:
  - name: vault-agent
    image: hashicorp/vault:1.21.4
    restartPolicy: Always # Делает контейнер нативным сайдкаром
    args: ["agent", "-config=/etc/vault/agent-config.hcl"]
    startupProbe:
      exec:
        command: ["sh", "-c", "test -f /tmp/agent.pid"]
      failureThreshold: 30
      periodSeconds: 5
    readinessProbe:
      exec:
        command: ["test", "-f", "/vault/secrets/config.yaml"]
      periodSeconds: 5
    securityContext:
      capabilities:
        add: ["SYS_PTRACE"]
      runAsNonRoot: true
    volumeMounts:
    - name: secrets-volume
      mountPath: /vault/secrets
    - name: agent-config
      mountPath: /etc/vault
      readOnly: true
  containers:
  - name: webapp
    image: my-app:latest
    # Приложение запустится только после готовности агента (Ready)
    volumeMounts:
    - name: secrets-volume
      mountPath: /etc/app
      readOnly: true
```

**Отличия от классического sidecar (Сценарий 2):**
*   При запуске: нативный сайдкар стартует до основных контейнеров и блокирует их до `Ready`.
*   При завершении: агент получает `SIGTERM` после остановки основных контейнеров (последним), поэтому секреты доступны до самого конца.
*   Для `Job`/`CronJob` нативный сайдкар корректно завершается вместе с задачей, не удерживая под в состоянии выполнения.

### Сценарий 5: Гибрид «init + sidecar»

Для старых кластеров (< K8s 1.29) применяется комбинированный паттерн: отдельный init-контейнер гарантирует первичный рендеринг секретов до старта приложения, а sidecar продолжает обновлять их в фоне. Здесь файл конфигурации агента (`/etc/vault/agent-config.hcl`) используется обоими контейнерами — для init-контейнера агент завершается сразу после первичного рендеринга (`exit_after_auth` не требуется, блок `template` с `exit_on_retry_failure` и завершением по отсутствию изменений агент обрабатывает сам).

```yaml
spec:
  volumes:
  - name: secrets-volume
    emptyDir: { medium: Memory }
  - name: agent-config
    configMap:
      name: vault-agent-config
  initContainers:
  - name: vault-agent-init
    image: hashicorp/vault:1.21.4
    args: ["agent", "-config=/etc/vault/agent-config.hcl"]
    volumeMounts:
    - name: secrets-volume
      mountPath: /vault/secrets
    - name: agent-config
      mountPath: /etc/vault
      readOnly: true
  containers:
  - name: webapp
    image: my-app:latest
    volumeMounts:
    - name: secrets-volume
      mountPath: /etc/app
      readOnly: true
  - name: vault-agent
    image: hashicorp/vault:1.21.4
    args: ["agent", "-config=/etc/vault/agent-config.hcl"]
    volumeMounts:
    - name: secrets-volume
      mountPath: /vault/secrets
    - name: agent-config
      mountPath: /etc/vault
      readOnly: true
```

### Сценарий 6: Динамические секреты (база данных)

Для баз данных Vault может выдавать динамические учётные данные (PostgreSQL, MySQL, MongoDB), которые автоматически истекают (TTL) и перевыпускаются. Агент рендерит такие секреты так же, как статические, но обновление происходит по истечении `lease_duration` или при явном обновлении лизы.

```hcl
template {
  source      = "/vault/templates/db.ctmpl"
  destination = "/vault/secrets/db-config.yaml"

  exec {
    command = ["pkill", "-HUP", "myapp"]
    timeout = "30s"
  }
}
```

Шаблон `db.ctmpl`:

```
{{- with secret "database/creds/myapp-role" -}}
DB_HOST={{ .Data.data.host }}
DB_PORT={{ .Data.data.port }}
DB_USER={{ .Data.data.username }}
DB_PASSWORD={{ .Data.data.password }}
LEASE_DURATION={{ .LeaseData.lease_duration }}
{{- end -}}
```

**Особенности динамических секретов:**

*   Агент автоматически обновляет секрет до истечения `lease_duration` (обычно 1h для БД). Если Vault недоступен, агент использует последнее значение из кэша.
*   Необходимо настроить `lease_duration` в Vault (`vault write database/config/myapp ...`) и убедиться, что приложение корректно переподключается к БД при смене пароля.
*   Для PostgreSQL рекомендуется использовать `reload` вместо `HUP`, если приложение поддерживает hot-reload без перезапуска.

### Сценарий 7: StatefulSet с Headless Service

Для stateful-приложений (базы данных, очереди) требуется стабильный сетевой идентификатор и порядок запуска. Native Sidecar совместим с StatefulSet, но需要注意几点:

*   Headless Service (`clusterIP: None`) обеспечивает DNS-записи вида `<pod-name>.<service-name>.<namespace>.svc.cluster.local`.
*   `podManagementPolicy: Parallel` ускоряет запуск, но нарушает порядок; для Vault Agent лучше использовать `OrderedReady` (по умолчанию), чтобы агент в каждом поде успел аутентифицироваться до старта основного контейнера.
*   Persistent Volume Claim монтируется как в основной контейнер, так и в агент (если требуется сохранение состояния между перезапусками).

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: "postgres-headless"
  replicas: 3
  podManagementPolicy: OrderedReady
  volumeClaimTemplates:
  - metadata:
      name: postgres-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
  template:
    spec:
      serviceAccountName: postgres-sa
      volumes:
      - name: secrets-volume
        emptyDir: { medium: Memory }
      - name: agent-config
        configMap:
          name: vault-agent-config
      initContainers:
      - name: vault-agent
        image: hashicorp/vault:1.21.4
        restartPolicy: Always
        args: ["agent", "-config=/etc/vault/agent-config.hcl"]
        startupProbe:
          exec:
            command: ["sh", "-c", "test -f /tmp/agent.pid"]
          failureThreshold: 30
          periodSeconds: 5
        volumeMounts:
        - name: secrets-volume
          mountPath: /vault/secrets
        - name: agent-config
          mountPath: /etc/vault
          readOnly: true
      containers:
      - name: postgres
        image: postgres:15
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
        - name: secrets-volume
          mountPath: /etc/postgresql/secrets
          readOnly: true
```

### Сценарий 8: API Proxy mode (приложение обращается к агенту)

Если приложение работает с Vault напрямую (SDK, `vault` CLI) и не может читать файлы в shared volume, агент может выступить локальным API-прокси: блок `listener` поднимает эндпоинт `127.0.0.1:8200` внутри контейнера агента, а приложение обращается к нему через `VAULT_ADDR=http://127.0.0.1:8200`, используя общий сетевой namespace пода.

```hcl
listener "tcp" {
  address     = "127.0.0.1:8200"
  tls_disable = true
  # Защита от SSRF: требует заголовок X-Vault-Request
  require_request_header = true
}

cache {
  use_auto_auth_token = true
  persist "kubernetes" {
    path = "/tmp/vault-agent-cache"
  }
}
```

Приложение выполняет `vault read secret/data/config` через прокси: запросы кэшируются, токен продлевается агентом, а доступ к серверу Vault скрыт из POD (не нужен Service Entry/endpoint). Подробнее о конфигурации — в [файле основ](./basics.md).

## Дополнительная информация

### Мониторинг и наблюдаемость

Vault Agent экспортирует метрики Prometheus на порту `9102` (по умолчанию), если настроен блок `telemetry` в конфигурации.

```hcl
telemetry {
  prometheus_retention_time = "30s"
  disable_hostname = true
}
```

Для сбора метрик добавьте в Pod:

```yaml
- name: vault-agent
  ports:
  - containerPort: 9102
    name: metrics
```

**Ключевые метрики:**

| Метрика | Описание |
| :--- | :--- |
| `vault.agent.token.last_rotation_time` | Время последнего обновления токена |
| `vault.agent.token.lease_duration` | TTL текущего токена |
| `vault.agent.template.render_success` | Успешный рендеринг шаблона |
| `vault.agent.template.render_failure` | Ошибка рендеринга (недоступность Vault, ошибка политики) |
| `vault.agent.cache.entry_count` | Количество секретов в кэше |
| `vault.agent.logical.database.total_lease_count` | Количество активных аренд (динамические секреты) |

Для проверки метрик внутри пода:

```bash
kubectl exec -n prod deploy/webapp -- curl -s http://127.0.0.1:9102/metrics | grep vault_agent
# → vault_agent_token_last_rotation_time 1700000000
# → vault_agent_template_render_success 42
```

### Преимущества и недостатки

| Характеристика | Преимущество | Недостаток |
| :--- | :--- | :--- |
| **Ротация** | Обновление секретов без рестарта подов. | Требует поддержки `SIGHUP` приложением или перечитывания файла. |
| **Изоляция** | Секреты только в памяти (`tmpfs`), не в `etcd`. | `shareProcessNamespace` ослабляет изоляцию процессов. |
| **Универсальность** | Работает в любом K8s без инжектора. | Требует ручного описания YAML для каждого Deployment. |
| **Гарантии запуска** | Нативный сайдкар (K8s 1.29+) стартует до приложения и блокирует его до готовности. | Для классического sidecar (<1.29) нужны probes или init-контейнер для исключения race conditions. |
| **Завершение пода** | Нативный сайдкар получает `SIGTERM` после основных контейнеров. | Классический sidecar завершается недетерминированно относительно приложения. |
| **Совместимость** | Работает с любыми приложениями и legacy. | Требуется роль и политики в Vault (auth method `kubernetes` или `approle`). |

### Рекомендации

1.  **Лимиты ресурсов:** Всегда указывайте `resources.limits` для сайдкара, чтобы он не влиял на стабильность основного приложения. Ресурсы сайдкара суммируются с ресурсами остальных контейнеров при расчёте лимита пода.
2.  **Persistent Cache:** Используйте BoltDB кэш в агенте (`cache { persist "kubernetes" { ... } }`) для мгновенного восстановления токена и аренды секретов при перезапуске контейнера агента без повторной аутентификации.
3.  **Graceful Shutdown:** Настройте `terminationGracePeriodSeconds` (минимум 30 сек), чтобы агент успел корректно закрыть сессии и (при необходимости) отозвать токен.
4.  **Безопасность:** Для агента используйте `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`; capability `SYS_PTRACE` добавляйте только там, где реально отправляются сигналы. В Vault 2.x контейнерные образы упакованы без capability `CAP_IPC_LOCK` — при запуске агента в контейнере задавайте `disable_mlock = true` (или добавьте capability при собственной сборке).
5.  **Версия образа:** Фиксируйте точный тег (например, `hashicorp/vault:1.21.4`), не `latest`, для воспроизводимости и контроля обновлений. Ветка 2.0.x — актуальный стабильный релиз с 14.04.2026.
6.  **Явные probes:** Для нативного сайдкара настраивайте `startupProbe`/`readinessProbe` агента — основной контейнер стартует только после готовности. Для классического sidecar организуйте readiness-проверку готовности файла секретов в приложении.
7.  **Конфигурация через ConfigMap:** Храните `agent-config.hcl` в ConfigMap, а TLS-CA — в Secret; монтируйте их только на чтение (`readOnly: true`).
8.  **Pod Disruption Budget:** если приложение чувствительно к прерываниям, настройте `PodDisruptionBudget` с `minAvailable: 1`, чтобы voluntary disruptions (например, `kubectl drain`) не удаляли под с работающим агентом.
9.  **Валидация перед deploy:** используйте `kubectl apply --dry-run=server` для проверки манифеста и `kubectl get pod -w` после развёртывания, чтобы убедиться, что агент перешёл в состояние `Ready` до старта основного контейнера.

### Диагностика

| Проблема | Инструмент | Причина / Решение |
| :--- | :--- | :--- |
| Агент в `CrashLoopBackOff` | `kubectl logs <pod> -c vault-agent` | Ошибка аутентификации (роль/токен), недоступность Vault, неверный путь к конфигу. |
| Секрет не появляется в `/vault/secrets` | `kubectl exec <pod> -c vault-agent -- cat /vault/secrets/...` | Синтаксис шаблона, отсутствие политики `read` на пути, `error_on_missing_key`. |
| Приложение стартует раньше секретов | `kubectl describe pod` | Классический sidecar без probes/init — используйте нативный сайдкар или readiness. |
| Приложение не получает `SIGHUP` | Проверка `shareProcessNamespace` и `SYS_PTRACE` | Не совпадает имя процесса, нет общего PID-namespace или capability. |
| Токен/кэш теряется при перезапуске | Проверка `persist` в конфиге | Не настроен `persist "kubernetes"`, путь к тому агента не персистентный. |
| Агент не продлевает токен | `kubectl logs <pod> -c vault-agent` | Истёк TTL токена, Vault недоступен для renew, конфиг `auto_auth` неверен. |
| Динамический секрет (БД) не обновляется | Проверка `lease_duration` и логов | Истёк срок аренды, Vault недоступен, приложение не переподключается. |
| Sidecar потребляет всю CPU | `kubectl top pod` | `static_secret_render_interval` слишком мал, или Vault недоступен (retry loop). |
| Pod не удаляется (Terminating) | `kubectl get pod -o jsonpath='{.status.containerStatuses[*].state}'` | Native Sidecar не завершается — проверьте graceful shutdown, `terminationGracePeriodSeconds`. |
| Метрики Prometheus не доступны | `kubectl exec -c vault-agent -- curl 127.0.0.1:9102/metrics` | Блок `telemetry` отсутствует в конфиге, или порт не открыт. |
| `error_on_missing_key` блокирует рендеринг | Логи агента | В шаблоне используется ключ, которого нет в секрете. Используйте `default` или проверьте путь в Vault. |
| `tls_skip_verify = true` в конфиге | Поиск по конфигу | Уязвимость для MITM. Замените на `ca_cert`. |

### Валидация и отладка

Перед развёртыванием проверьте:

```bash
# 1. Проверка синтаксиса HCL (опционально, если есть vault CLI)
vault agent -config=/etc/vault/agent-config.hcl -exit-after-auth 2>&1 | head -20

# 2. Проверка доступности Vault из пода
kubectl exec -n prod deploy/webapp -c vault-agent -- \
  curl -s --cacert /etc/vault/agent/tls/tls-ca-cert.crt \
  https://vault.vault.svc.cluster.local:8200/v1/sys/health
# → {"initialized":true,"sealed":false,...}

# 3. Проверка аутентификации
kubectl exec -n prod deploy/webapp -c vault-agent -- \
  vault login -method=kubernetes role=webapp-ms-role \
  jwt=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
# → Success! You are now authenticated.

# 4. Проверка рендеринга секретов
kubectl exec -n prod deploy/webapp -c vault-agent -- \
  cat /vault/secrets/config.yaml
# → DB_HOST=postgres.example.com
# → DB_PORT=5432
```

### Обновление конфигурации и rollout

При изменении `agent-config.hcl` или ConfigMap:

1.  ConfigMap обновляется (`kubectl apply -f vault-agent-config.yaml`).
2.  Для Deployment: `kubectl rollout restart deployment/webapp-sidecar` — агент перезапускается с новым конфигом, Persistent Cache сохраняет токен.
3.  Для StatefulSet: `kubectl rollout restart statefulset/postgres` — перезапуск происходит поэтапно (по replica order).
4.  Для Pod: `kubectl delete pod <pod>` — контроллер (ReplicaSet/StatefulSet) создаст новый Pod с новым ConfigMap.

**Стратегия 1: Rolling update (по умолчанию)**

Deployment автоматически обновляет поды по одному. Для агента это означает кратковременную потерю динамической ротации на одном реплике во время перезапуска.

**Стратегия 2: Изменение реплик (для Job/CronJob)**

Для Job/CronJob с init-only режимом новый Pod получит свежие секреты при каждом запуске. Для `init + sidecar` требуется полный rollout Deployment.

**Стратегия 3: Прямое удаление подов (Deployment)**

Если ConfigMap обновлён, но Pod не перезапускается:

```bash
kubectl delete pod -l app=webapp -n prod
# Deployment создаст новый Pod с новым ConfigMap
```

### Связанные документы

*   **[Vault Agent: основы](./basics.md)** — параметры HCL и синтаксис шаблонов.
*   **[Vault Injector](./injector.md)** — автоматизация внедрения сайдкаров через аннотации.
*   **[Интеграция с Kubernetes](../vault_kubernetes_integration.md)** — основной раздел по всем стратегиям управления секретами.
*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — детали машинной аутентификации (RoleID/SecretID).
