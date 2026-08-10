# Vault Agent Sidecar — динамическое обновление конфигурации

## Определения

**Vault Agent Sidecar** — это архитектурный паттерн использования `vault-agent` в качестве постоянно работающего вспомогательного контейнера в Kubernetes-поде. Он отвечает за аутентификацию, получение секретов и их динамическое обновление в конфигурационных файлах основного приложения без перезапуска пода.

**Динамическая ротация (Dynamic Rotation)** — процесс автоматического обновления секретов (например, паролей БД или сертификатов) в работающем приложении. Агент отслеживает изменения в Vault, перезаписывает файлы и отправляет сигнал приложению (обычно `SIGHUP`) для перечитывания конфигурации.

**Native Sidecar Containers (K8s 1.29+)** — механизм Kubernetes (beta с 1.28, стабилен с 1.29, см. KEP-3839), позволяющий определять вспомогательные контейнеры в блоке `initContainers` с параметром `restartPolicy: Always`. Это гарантирует, что Vault Agent запустится раньше основного приложения (основные контейнеры стартуют только после перехода агента в состояние `Ready`), останется доступным на протяжении всего жизненного цикла пода и завершится **после** остановки основных контейнеров, получая `SIGTERM`. Ключевое отличие от обычного sidecar (контейнер в `containers`) — гарантированный порядок запуска и завершения, что устраняет race conditions при первичном рендеринге секретов.

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

### Жизненный цикл с Native Sidecars

При использовании нативных сайдкаров (K8s 1.29+):
1.  Vault Agent запускается как `initContainer` с `restartPolicy: Always`.
2.  Агент проходит аутентификацию и рендерит секреты (первичный рендеринг до старта приложения).
3.  Kubernetes переходит к запуску основного контейнера только после того, как агент станет `Ready` (если настроена `startupProbe`/`readinessProbe`).
4.  На протяжении работы пода агент поддерживает секреты актуальными (sidecar-роль): отслеживает лизы, продлевает токен, перерисовывает шаблоны по `static_secret_render_interval` (KV v2) или при ротации динамических секретов.
5.  При завершении пода агент получает `SIGTERM` и выключается **последним** — после остановки основных контейнеров, обеспечивая доступность секретов до полной остановки приложения.

**Вариант «init-only» для ручного внедрения:** если приложение не требует динамического обновления (статические секреты), вместо sidecar можно использовать обычный init-контейнер без `restartPolicy: Always`, который один раз рендерит секреты и завершается. Это снижает потребление ресурсов. Для динамических секретов (БД, PKI) обязателен sidecar с пролонгацией лиз.

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

### Сценарий 3: Использование Native Sidecar (K8s 1.29+)

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

### Сценарий 4: Гибрид «init + sidecar»

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

### Сценарий 5: API Proxy mode (приложение обращается к агенту)

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

### Преимущества и недостатки

| Характеристика | Преимущество | Недостаток |
| :--- | :--- | :--- |
| **Ротация** | Обновление секретов без рестарта подов. | Требует поддержки `SIGHUP` приложением или перечитывания файла. |
| **Изоляция** | Секреты только в памяти (`tmpfs`), не в `etcd`. | `shareProcessNamespace` ослабляет изоляцию процессов. |
| **Универсальность** | Работает в любом K8s без инжектора. | Требует ручного описания YAML для каждого Deployment. |
| **Гарантии запуска** | Нативный сайдкар (K8s 1.29+) стартует до приложения и блокирует его до готовности. | Для классического sidecar (<1.29) нужны probes или init-контейнер для исключения race conditions. |
| **Завершение пода** | Нативный сайдкар получает `SIGTERM` после основных контейнеров. | Классический sidecar завершается недетерминированно относительно приложения. |
| **Совместимость** | Работает с любыми приложениями и legacy. | Требуется роль и политики в Vault (auth method `kubernetes`). |

### Рекомендации

1.  **Лимиты ресурсов:** Всегда указывайте `resources.limits` для сайдкара, чтобы он не влиял на стабильность основного приложения. Ресурсы сайдкара суммируются с ресурсами остальных контейнеров при расчёте лимита пода.
2.  **Persistent Cache:** Используйте BoltDB кэш в агенте (`cache { persist "kubernetes" { ... } }`) для мгновенного восстановления токена и аренды при перезапуске контейнера агента без повторной аутентификации.
3.  **Graceful Shutdown:** Настройте `terminationGracePeriodSeconds` (минимум 30 сек), чтобы агент успел корректно закрыть сессии и (при необходимости) отозвать токен.
4.  **Безопасность:** Для агента используйте `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`; capability `SYS_PTRACE` добавляйте только там, где реально отправляются сигналы. В Vault 2.x контейнерные образы упакованы без capability `CAP_IPC_LOCK` — при запуске агента в контейнере задавайте `disable_mlock = true` (или добавьте capability при собственной сборке).
5.  **Версия образа:** Фиксируйте точный тег (например, `hashicorp/vault:1.21.4`), не `latest`, для воспроизводимости и контроля обновлений. Ветка 2.0.x — актуальный стабильный релиз с 14.04.2026.
6.  **Явные probes:** Для нативного сайдкара настраивайте `startupProbe`/`readinessProbe` агента — основной контейнер стартует только после готовности. Для классического sidecar организуйте readiness-проверку готовности файла секретов в приложении.
7.  **Конфигурация через ConfigMap:** Храните `agent-config.hcl` в ConfigMap, а TLS-CA — в Secret; монтируйте их только на чтение (`readOnly: true`).

### Диагностика

| Проблема | Инструмент | Причина / Решение |
| :--- | :--- | :--- |
| Агент в `CrashLoopBackOff` | `kubectl logs <pod> -c vault-agent` | Ошибка аутентификации (роль/токен), недоступность Vault, неверный путь к конфигу. |
| Секрет не появляется в `/vault/secrets` | `kubectl exec <pod> -c vault-agent -- cat /vault/secrets/...` | Синтаксис шаблона, отсутствие политики `read` на пути, `error_on_missing_key`. |
| Приложение стартует раньше секретов | `kubectl describe pod` | Классический sidecar без probes/init — используйте нативный сайдкар или readiness. |
| Приложение не получает `SIGHUP` | Проверка `shareProcessNamespace` и `SYS_PTRACE` | Не совпадает имя процесса, нет общего PID-namespace или capability. |
| Токен/кэш теряется при перезапуске | Проверка `persist` в конфиге | Не настроен `persist "kubernetes"`, путь к тому агента не персистентный. |

### Связанные документы

*   **[Vault Agent: основы](./basics.md)** — параметры HCL и синтаксис шаблонов.
*   **[Vault Injector](./injector.md)** — автоматизация внедрения сайдкаров через аннотации.
*   **[Интеграция с Kubernetes](../vault_kubernetes_integration.md)** — основной раздел по всем стратегиям управления секретами.
