# Паттерны Sidecar в Kubernetes

**Актуально для:** Kubernetes 1.29 - 1.33+ (Native Sidecars GA в v1.33)

## Определения

**Sidecar Pattern (Сайдкар)** — архитектурный паттерн многоконтейнерного Pod, при котором вспомогательный контейнер запускается рядом с основным приложением в едином пространстве имен для расширения его функциональности (сбор метрик, ротация логов, проксирование трафика, обновление конфигураций), не требуя модификации исходного кода самого приложения.

**Adapter Pattern (Адаптер)** — разновидность сайдкара, предназначенная для унификации гетерогенного вывода основного приложения. Адаптер принимает специфичные или устаревшие форматы данных (например, кастомные текстовые логи или бинарные метрики) и трансформирует их в стандартный протокол, ожидаемый инфраструктурой мониторинга (например, Prometheus exposition format или JSON-логи).

**Ambassador Pattern (Амбассадор)** — разновидность сайдкара, выступающая в роли локального прокси-шлюза для управления **исходящими** сетевыми соединениями приложения. Приложение подключается к амбассадору через `localhost`, а амбассадор берет на себя маршрутизацию, балансировку нагрузки, повтор запросов (retries), шифрование TLS/mTLS и управление подключением к внешним системам (базам данных, внешним API, очередям сообщений).

**Native Sidecar (Нативный сайдкар)** — встроенный в ядро Kubernetes механизм (beta с v1.29, стабилен и включен по умолчанию с v1.33; KEP-3839), позволяющий определять долгоживущие вспомогательные контейнеры в блоке `spec.initContainers[]` с параметром `restartPolicy: Always`. Kubelet гарантирует их запуск строго до основного приложения и работу на протяжении всего жизненного цикла Pod.

**Volume Sidecar (IPC через разделяемые тома)** — паттерн взаимодействия, при котором сайдкар и основной контейнер монтируют общий том (`emptyDir`, тома в памяти `tmpfs` или `Secret`/`ConfigMap`). Используется для передачи динамических файлов, UNIX-сокетов межпроцессного взаимодействия (IPC) и буферизации данных.

**Shared Process Namespace (Общее пространство PID)** — механизм изоляции Pod (`spec.shareProcessNamespace: true`), объединяющий пространство процессов всех контейнеров. Позволяет сайдкару анализировать процессы основного контейнера через `/proc` и отправлять сигналы POSIX (например, `SIGHUP` для перечитывания конфигураций без перезапуска контейнера).

---

## Базовые концепции и архитектура

### Классификация паттернов и типовые задачи

| Паттерн | Направление потока данных | Основное назначение | Практический пример |
| :--- | :--- | :--- | :--- |
| **Sidecar** | Параллельно / Двунаправленно | Расширение функциональности среды выполнения | Fluent Bit для ротации логов; git-sync для синхронизации репозитория |
| **Adapter** | Изнутри Pod наружу | Унификация интерфейсов и протоколов | StatsD Exporter, преобразующий UDP-метрики в эндпоинт `/metrics` |
| **Ambassador** | Из Pod наружу | Локальное проксирование и изоляция сетевой топологии | Локальный Envoy или HAProxy для подключения к внешнему кластеру PostgreSQL |

**Ключевые области применения в практике DevOps, SRE и системного администрирования:**

1. **Наблюдаемость (Observability):**
   * Сбор и потоковая передача файлов логов со сжатием и парсингом (Fluent Bit, Vector, Filebeat) без внедрения тяжелых библиотек в код микросервиса.
   * Экспорт метрик приложений через адаптеры (JMX Exporter, StatsD Exporter).
2. **Сетевое взаимодействие и Traffic Management:**
   * Проксирование mTLS, управление таймаутами и канареечным трафиком (Envoy Proxy, Linkerd).
   * Изоляция сетевых протоколов (приложение отправляет HTTP-запросы на `localhost`, сайдкар преобразует их в gRPC или шифрует mTLS).
3. **Безопасность и управление секретами:**
   * Получение токенов и ротация сертификатов (Vault Agent, cert-manager CSI/Sidecar) с записью во временные тома в оперативной памяти (`medium: Memory`).
4. **Конфигурация и оркестрация:**
   * Фоновое обновление файлов конфигураций и оповещение процессов приложения через сигналы POSIX.

---

### Сравнение: Классический Sidecar vs Native Sidecar

До версии Kubernetes 1.28 сайдкары объявлялись как обычные элементы массива `spec.containers[]`. Это создавало критические проблемы для SRE: состояние гонки (race condition) при старте (приложение могло стартовать раньше прокси) и преждевременное завершение сайдкара при остановке Pod (прокси умирал до того, как приложение отправляло финальные запросы).

| Характеристика | Классический Sidecar | Native Sidecar (KEP-3839) |
| :--- | :--- | :--- |
| **Секция в манифесте** | `spec.containers[]` | `spec.initContainers[]` с `restartPolicy: Always` |
| **Порядок запуска** | Одновременно с приложением | **Строго до** основных контейнеров (в порядке очереди `initContainers`) |
| **Критерий готовности к старту app** | Отсутствует (параллельный запуск) | **Гарантирован:** переход к следующему контейнеру только после прохождения `startupProbe` |
| **Порядок завершения (Shutdown)** | Параллельный (произвольный) | **Строго после** основных контейнеров |
| **Поведение в Job / CronJob** | Блокирует завершение Job (контейнер не завершается) | Автоматически завершается Kubelet после успешного выхода основного контейнера |
| **Поддерживаемые пробы (Probes)** | `startupProbe`, `readinessProbe`, `livenessProbe` | `startupProbe`, `readinessProbe`, `livenessProbe` |
| **Lifecycle Hooks (`postStart`, `preStop`)** | Поддерживаются | **Не поддерживаются** (ограничение схемы `initContainers`) |
| **Расчет ресурсов (Requests/Limits)** | Суммируются напрямую | Суммируются с учетом фаз инициализации Pod |
| **Поддержка версий K8s** | Все версии | v1.28 (Alpha), v1.29–v1.32 (Beta), v1.33+ (GA / включено по умолчанию) |

---

### Жизненный цикл Native Sidecar

#### 1. Фаза инициализации и запуска

```
[Порядок запуска Pod с Native Sidecar]
Kubelet
  │
  ├─► 1. Стандартный init-контейнер 1 ──► [Exit 0] (Завершен)
  │
  ├─► 2. Native Sidecar (restartPolicy: Always) ──► Старт процесса
  │        │
  │        └─► Ожидание startupProbe ──► [Ready] (Переход в фон)
  │
  ├─► 3. Стандартный init-контейнер 2 ──► [Exit 0] (Завершен)
  │
  └─► 4. Запуск spec.containers[*] ──► Приложение стартует при работающем сайдкаре
```

1. Kubelet выполняет контейнеры из массива `spec.initContainers` строго последовательно.
2. Стандартный init-контейнер обязан успешно завершиться (код возврата `0`), прежде чем начнется запуск следующего.
3. При обнаружении контейнера с `restartPolicy: Always` Kubelet запускает его и ожидает прохождения проверок:
   * Если для сайдкара настроена `startupProbe`, Kubelet ожидает успешного прохождения пробы.
   * Если `startupProbe` отсутствует, готовность фиксируется сразу после успешного создания и запуска контейнера средой выполнения (CRI).
4. После достижения статуса готовности нативный сайдкар **не останавливается**, а переходит в непрерывный режим работы в фоновом потоке Pod.
5. Kubelet переходит к следующим init-контейнерам, а затем к параллельному запуску всех контейнеров приложения из секции `spec.containers[]`.

#### 2. Поведение во время работы (Runtime)

* Нативный сайдкар функционирует параллельно с основными контейнерами.
* **Изолированный перезапуск:** если нативный сайдкар аварийно завершает работу (сбой процесса, OOMKilled), Kubelet перезапускает его независимо в соответствии с экспоненциальной задержкой (CrashLoopBackOff). Основные контейнеры приложения **не перезапускаются**.
* Если readinessProbe сайдкара возвращает ошибку, сайдкар помечается как `NotReady`. Влияние на общий статус Pod: Pod считается не готовым принимать трафик через Service, если хотя бы один рабочий контейнер не прошел readiness-проверку.

#### 3. Фаза завершения (Graceful Shutdown)

```
[Порядок завершения Pod с Native Sidecar]
Удаление Pod (SIGTERM от Kubelet)
  │
  ├─► 1. Отправка SIGTERM в spec.containers[*] (Контейнеры приложения)
  │        │
  │        └─► Приложение завершает обработку запросов, отправляет финальные логи
  │              │
  │              └─► [Exit 0] Контейнеры приложения завершены
  │
  └─► 2. Только теперь: отправка SIGTERM в Native Sidecars
           │
           └─► Сайдкары (Envoy, Fluent Bit) сбрасывают буферы и завершаются
```

1. При удалении Pod Kubelet отправляет сигнал `SIGTERM` **только** основным контейнерам (`spec.containers[]`).
2. Нативные сайдкары продолжают полноценно функционировать, обеспечивая сетевое проксирование, ротацию токенов и сбор последних порций логов приложения.
3. Kubelet ожидает полной остановки основных контейнеров (или истечения таймера `terminationGracePeriodSeconds`).
4. Только после полной остановки контейнеров приложения Kubelet отправляет сигнал `SIGTERM` нативным сайдкарам в обратном порядке их объявления в `initContainers`.

**Подробнее о процедуре остановки:** [Graceful Shutdown в Kubernetes](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md#порядок-завершения-native-sidecar-k8s-129).

---

### Сетевое взаимодействие и IPC внутри Pod

Контейнеры одного Pod совместно используют пространства имен ядра Linux (Namespaces):

1. **Network Namespace:**
   * Все контейнеры имеют общий сетевой интерфейс `eth0` и общий `lo` (loopback `127.0.0.1`).
   * Взаимодействие между приложением и сайдкаром происходит через `localhost:<PORT>`.
   * **Правило портов:** два контейнера в одном Pod не могут слушать один и тот же TCP- или UDP-порт. Попытка второго контейнера занять занятый порт приведет к ошибке `bind: address already in use`.

2. **IPC Namespace и UNIX Domain Sockets:**
   * Для обмена данными с высокой пропускной способностью и минимальной задержкой рекомендуется использовать UNIX Domain Sockets вместо сетевого стека TCP/IP.
   * Сокет размещается в общем томе `emptyDir` (желательно `medium: Memory`).

3. **PID Namespace (`shareProcessNamespace`):**
   * По умолчанию каждый контейнер имеет изолированное дерево процессов PID.
   * При установке `spec.shareProcessNamespace: true` дерево процессов становится общим. Сайдкар видит процессы приложения, может выполнять диагностику через `/proc/<PID>/` и отправлять сигналы (`kill -HUP <PID>` для перечитывания конфигурации Nginx/HAProxy).

---

### Расчет ресурсов (Requests/Limits) и влияние на QoS

Планировщик `kube-scheduler` вычисляет суммарные требования Pod к ресурсам с учетом того, что обычные init-контейнеры завершаются до старта приложения, а нативные сайдкары работают постоянно:

```text
SumAppRequests     = sum(spec.containers[*].resources.requests)
SumSidecarRequests = sum(spec.initContainers[sidecars].resources.requests)

EffectiveRequest = SumAppRequests + SumSidecarRequests
```

Для классических init-контейнеров ($Init_k$) учитывается сумма самого init-контейнера и всех нативных сайдкаров, работающих на момент его выполнения:

```text
PhaseRequest(Init_k) = requests(Init_k) + sum(requests(Sidecars_до_него))
EffectivePodRequest  = max(SumAppRequests + SumSidecarRequests, max(PhaseRequest(Init_k)))
```

**Влияние на класс QoS (Quality of Service):**
* Чтобы Pod получил класс **Guaranteed**, абсолютно **все** контейнеры (включая все сайдкары в `spec.containers` и `spec.initContainers`) обязаны иметь строго заданные `requests` и `limits`, причем `requests == limits` для CPU и памяти.
* Если хотя бы один сайдкар не имеет лимита или его `requests != limits`, весь Pod получает класс **Burstable** или **BestEffort**, что снижает его устойчивость при нехватке памяти на узле (OOM Score).

**Подробнее:** [QoS, Requests и Limits](../../Scheduling/qos_limit_and_requests.md).

---

## Практические сценарии и конфигурация

### Сценарий 1: Сбор логов через разделяемый том (Классический Sidecar)

Приложение пишет логи в локальные файлы внутри тома `emptyDir`. Сайдкар на базе Fluent Bit читает файлы, парсит их и передает во внешнюю систему хранения.

**Требования:**
* Том `emptyDir` с ограничением по размеру (`sizeLimit`), чтобы исключить переполнение диска ноды при всплеске логов.
* Монтирование тома в сайдкар в режиме `readOnly: true`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-logging-sidecar
  labels:
    app.kubernetes.io/name: payment-processor
spec:
  volumes:
  - name: shared-logs
    emptyDir:
      sizeLimit: 1Gi
  containers:
  - name: backend-app
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    args:
    - >
      while true; do
        echo "{\"timestamp\":\"$(date -u +%FT%TZ)\",\"level\":\"INFO\",\"message\":\"Transaction processed\"}" >> /var/log/app/app.log;
        sleep 1;
      done
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 200m
        memory: 256Mi
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
  - name: log-collector
    image: fluent/fluent-bit:3.1.4
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 100m
        memory: 128Mi
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
      readOnly: true
```

**Проверка работы:**
```bash
# Проверка наполнения общего тома из сайдкара
kubectl exec app-logging-sidecar -c log-collector -- head -n 5 /var/log/app/app.log
# → {"timestamp":"2026-10-17T17:35:00Z","level":"INFO","message":"Transaction processed"}
```

---

### Сценарий 2: Native Sidecar с Envoy и гарантированной готовностью

Сетевой прокси Envoy запускается как нативный сайдкар. Основное приложение начинает работу только после того, как Envoy полностью инициализировался и прошел проверку готовности `startupProbe`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-envoy-sidecar
spec:
  initContainers:
  - name: envoy-proxy
    image: envoyproxy/envoy:v1.31.0
    restartPolicy: Always
    ports:
    - containerPort: 9901
      name: admin
    - containerPort: 10000
      name: ingress
    startupProbe:
      httpGet:
        path: /ready
        port: 9901
      initialDelaySeconds: 2
      periodSeconds: 2
      failureThreshold: 15
    readinessProbe:
      httpGet:
        path: /ready
        port: 9901
      periodSeconds: 5
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 250m
        memory: 256Mi
  containers:
  - name: core-api
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    args:
    - >
      echo "Connecting to Envoy on localhost:10000...";
      nc -z -w 3 127.0.0.1 10000 && echo "Envoy is reachable, starting API" || exit 1;
      sleep 3600
    resources:
      requests:
        cpu: 100m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
```

**Проверка работы:**
```bash
# Проверка порядка инициализации (initContainerStatuses должен быть ready до старта core-api)
kubectl get pod app-with-envoy-sidecar -o jsonpath='{.status.initContainerStatuses[0].ready}'
# → true
```

---

### Сценарий 3: Ambassador Pattern — локальный прокси к внешнему кластеру БД

Приложение обращается по фиксированному порту `127.0.0.1:5432`. Амбассадор-контейнер на базе HAProxy инкапсулирует логику маршрутизации к активному мастер-узлу PostgreSQL, мониторит состояние реплик и изолирует приложение от сетевых изменений внешней топологии.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: haproxy-ambassador-config
data:
  haproxy.cfg: |
    global
        maxconn 1024
    defaults
        mode tcp
        timeout connect 5000ms
        timeout client 50000ms
        timeout server 50000ms
    frontend postgres_front
        bind 127.0.0.1:5432
        default_backend postgres_back
    backend postgres_back
        balance roundrobin
        server pg-master 192.168.10.50:5432 check
---
apiVersion: v1
kind: Pod
metadata:
  name: legacy-app-ambassador
spec:
  volumes:
  - name: haproxy-cfg
    configMap:
      name: haproxy-ambassador-config
  containers:
  - name: business-logic
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    args:
    - >
      echo "App points strictly to localhost:5432";
      sleep 3600
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
  - name: pg-ambassador
    image: haproxy:2.8-alpine
    volumeMounts:
    - name: haproxy-cfg
      mountPath: /usr/local/etc/haproxy/haproxy.cfg
      subPath: haproxy.cfg
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 100m
        memory: 128Mi
```

---

### Сценарий 4: Adapter Pattern — трансформация сокета метрик в Prometheus Exposition Format

Приложение генерирует легковесные метрики через UNIX-сокет (StatsD format). Адаптер читает сокет через общий том в памяти (`medium: Memory`) и открывает стандартный HTTP-эндпоинт `/metrics` для скрейпинга системой Prometheus.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-metrics-adapter
  labels:
    app: order-service
spec:
  volumes:
  - name: socket-storage
    emptyDir:
      medium: Memory
      sizeLimit: 32Mi
  containers:
  - name: backend-service
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    args:
    - >
      sleep 2;
      while true; do
        echo -n "orders.created:1|c" | nc -u -U /var/run/metrics/statsd.sock;
        sleep 5;
      done
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
    volumeMounts:
    - name: socket-storage
      mountPath: /var/run/metrics
  - name: statsd-adapter
    image: prom/statsd-exporter:v0.27.0
    args:
    - "--statsd.listen-unixgram=/var/run/metrics/statsd.sock"
    - "--web.listen-address=:9102"
    - "--web.telemetry-path=/metrics"
    ports:
    - containerPort: 9102
      name: metrics
    resources:
      requests:
        cpu: 25m
        memory: 32Mi
      limits:
        cpu: 50m
        memory: 64Mi
    volumeMounts:
    - name: socket-storage
      mountPath: /var/run/metrics
```

---

### Сценарий 5: Безопасность — Vault Agent Native Sidecar для динамических секретов

Vault Agent запускается как нативный сайдкар. Он аутентифицируется через Kubernetes ServiceAccount, получает временные учетные данные к БД, сохраняет их в защищенный том оперативной памяти (`medium: Memory`) и обновляет до истечения TTL токена.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app-vault
spec:
  serviceAccountName: vault-auth-sa
  volumes:
  - name: vault-secrets
    emptyDir:
      medium: Memory
      sizeLimit: 16Mi
  - name: vault-config-vol
    configMap:
      name: vault-agent-config
  initContainers:
  - name: vault-agent
    image: hashicorp/vault:1.17.2
    restartPolicy: Always
    args: ["agent", "-config=/etc/vault/vault-agent-config.hcl"]
    volumeMounts:
    - name: vault-secrets
      mountPath: /vault/secrets
    - name: vault-config-vol
      mountPath: /etc/vault
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 100m
        memory: 128Mi
  containers:
  - name: application
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    args:
    - >
      until [ -f /vault/secrets/database.env ]; do
        echo "Waiting for dynamic secrets...";
        sleep 1;
      done;
      echo "Secrets found. Application started.";
      cat /vault/secrets/database.env;
      sleep 3600
    volumeMounts:
    - name: vault-secrets
      mountPath: /vault/secrets
      readOnly: true
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
```

---

### Сценарий 6: Синхронизация конфигураций — Git-Sync Native Sidecar

Сайдкар `git-sync` запускается в фоновом режиме нативного сайдкара (`restartPolicy: Always`), выполняет периодический опрос (polling каждые 30 секунд) удаленного репозитория и зеркалирует конфигурации в общий том `emptyDir`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-dynamic-config
spec:
  volumes:
  - name: config-dir
    emptyDir: {}
  initContainers:
  - name: config-syncer
    image: registry.k8s.io/git-sync/git-sync:v4.2.4
    restartPolicy: Always
    args:
    - "--repo=https://github.com/example-org/app-configs.git"
    - "--ref=HEAD"
    - "--period=30s"
    - "--root=/etc/configs"
    volumeMounts:
    - name: config-dir
      mountPath: /etc/configs
    resources:
      requests:
        cpu: 20m
        memory: 32Mi
      limits:
        cpu: 50m
        memory: 64Mi
  containers:
  - name: config-consumer
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    args:
    - >
      while true; do
        if [ -d /app/config ]; then
          ls -la /app/config;
        fi;
        sleep 10;
      done
    volumeMounts:
    - name: config-dir
      mountPath: /app/config
      readOnly: true
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
```

---

### Сценарий 7: Rate-Limiting исходящих вызовов через Native Sidecar (Nginx)

Приложение отправляет запросы к внешнему шлюзу партнеров через локальный прокси `127.0.0.1:8080`. Сайдкар Nginx ограничивает частоту запросов (Leaky Bucket / Token Bucket), предотвращая превышение лимитов провайдера. Конфигурация монтируется через ConfigMap (без использования недопустимых в `initContainers` директив `lifecycle`).

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rate-limiter-config
data:
  nginx.conf: |
    events { worker_connections 1024; }
    http {
        limit_req_zone $binary_remote_addr zone=partner_api:10m rate=10r/s;
        server {
            listen 8080;
            location / {
                limit_req zone=partner_api burst=20 nodelay;
                proxy_pass http://external-api.internal:80;
                proxy_set_header Host external-api.internal;
            }
            location /healthz {
                return 200 "OK\n";
            }
        }
    }
---
apiVersion: v1
kind: Pod
metadata:
  name: app-with-rate-limiter
spec:
  volumes:
  - name: proxy-config-vol
    configMap:
      name: rate-limiter-config
  initContainers:
  - name: rate-limit-proxy
    image: nginx:1.27-alpine
    restartPolicy: Always
    volumeMounts:
    - name: proxy-config-vol
      mountPath: /etc/nginx/nginx.conf
      subPath: nginx.conf
      readOnly: true
    startupProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 1
      periodSeconds: 2
      failureThreshold: 5
    readinessProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 5
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 100m
        memory: 128Mi
  containers:
  - name: payment-client
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    args:
    - >
      echo "Sending requests through local rate limiter...";
      sleep 3600
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
```

---

### Сценарий 8: Автоматическая ротация TLS-сертификатов с `fsGroup`

Сайдкар-ротатор генерирует и обновляет клиентские mTLS-сертификаты в общем томе. Контейнер генератора монтирует том с правами на запись, а приложение — в режиме `readOnly: true`. Для разрешения проблем с правами доступа непривилегированного приложения используется параметр `spec.securityContext.fsGroup`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-tls-rotation
spec:
  securityContext:
    fsGroup: 2000
  volumes:
  - name: tls-certs
    emptyDir:
      medium: Memory
      sizeLimit: 16Mi
  initContainers:
  - name: cert-manager-rotator
    image: alpine:3.20
    restartPolicy: Always
    command: ["/bin/sh", "-c"]
    args:
    - >
      while true; do
        echo "Generating/refreshing certs: $(date -u)" > /certs/tls.crt;
        echo "Valid until: $(date -u -d '+1 day')" >> /certs/tls.crt;
        sleep 3600;
      done
    volumeMounts:
    - name: tls-certs
      mountPath: /certs
      readOnly: false
    resources:
      requests:
        cpu: 25m
        memory: 32Mi
      limits:
        cpu: 50m
        memory: 64Mi
  containers:
  - name: secure-client
    image: alpine:3.20
    securityContext:
      runAsUser: 10001
      runAsNonRoot: true
    command: ["/bin/sh", "-c"]
    args:
    - >
      while true; do
        if [ -f /etc/tls/tls.crt ]; then
          head -n 2 /etc/tls/tls.crt;
        fi;
        sleep 30;
      done
    volumeMounts:
    - name: tls-certs
      mountPath: /etc/tls
      readOnly: true
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
```

---

## Операции и команды

Практические команды для администрирования, мониторинга и отладки многоконтейнерных подов:

### 1. Проверка статуса запуска нативных сайдкаров

```bash
# Получение детального статуса всех init-контейнеров и сайдкаров в Pod
kubectl get pod app-with-envoy-sidecar -o jsonpath='{range .status.initContainerStatuses[*]}{.name}{"\tReady: "}{.ready}{"\tRestarts: "}{.restartCount}{"\tState: "}{.state}{"\n"}{end}'
# → envoy-proxy    Ready: true    Restarts: 0    State: {"running":{"startedAt":"2026-10-17T17:40:00Z"}}
```

```bash
# Сравнение времени старта сайдкара и основного приложения
kubectl get pod app-with-envoy-sidecar -o jsonpath='{"Sidecar started: "}{.status.initContainerStatuses[0].state.running.startedAt}{"\nApp started:     "}{.status.containerStatuses[0].state.running.startedAt}{"\n"}'
# → Sidecar started: 2026-10-17T17:40:00Z
# → App started:     2026-10-17T17:40:04Z
```

### 2. Мониторинг логов конкретного сайдкара

```bash
# Просмотр логов сайдкара в реальном времени с ограничением вывода
kubectl logs app-logging-sidecar -c log-collector --tail=50 -f
# → 2026-10-17T17:41:00.123456Z [info] [engine] started, version=3.1.4

# Просмотр логов предыдущего упавшего экземпляра сайдкара
kubectl logs app-with-envoy-sidecar -c envoy-proxy --previous
```

### 3. Выполнение команд и интерактивная отладка внутри сайдкара

```bash
# Проверка сетевых портов, открытых внутри Pod
kubectl exec -it app-with-envoy-sidecar -c envoy-proxy -- netstat -tlpn
# → Active Internet connections (only servers)
# → Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name
# → tcp        0      0 127.0.0.1:9901          0.0.0.0:*               LISTEN      1/envoy
# → tcp        0      0 0.0.0.0:10000           0.0.0.0:*               LISTEN      1/envoy
```

### 4. Отладка процессов сайдкара через Ephemeral Container

```bash
# Подключение эфемерного отладочного контейнера с разделением PID namespace
kubectl debug -it app-with-envoy-sidecar --image=alpine:3.20 --target=envoy-proxy --share-processes
# → Target container "envoy-proxy" selected.
# → If you don't see a command prompt, try pressing enter.
# / # ps aux
# PID   USER     TIME  COMMAND
#     1 101       0:02 envoy -c /etc/envoy/envoy.yaml
#    25 root      0:00 /bin/sh
```

### 5. Контроль потребления ресурсов по контейнерам

```bash
# Проверка реального потребления CPU и памяти раздельно по контейнерам Pod
kubectl top pod app-logging-sidecar --containers
# → POD                   NAME             CPU(cores)   MEMORY(bytes)
# → app-logging-sidecar   backend-app      12m          45Mi
# → app-logging-sidecar   log-collector    6m           28Mi
```

---

## Диагностика и устранение неполадок (Troubleshooting)

### Ошибка 1: Pod зависает в статусе `Init:0/1` или `CrashLoopBackOff` сайдкара

**Симптом:** Pod не переходит в состояние `PodInitializing` или `Running`. Контейнеры приложения не запускаются.

**Причина:**
1. Нативный сайдкар (`restartPolicy: Always`) не может пройти `startupProbe` из-за слишком короткого таймаута или ошибки конфигурации.
2. Сайдкар падает при старте (например, неверный конфиг-файл Nginx/Envoy или недоступность монтируемого секрета).

**Диагностика:**
```bash
# Проверка состояния init-контейнеров
kubectl describe pod <pod-name> | grep -A 10 "Init Containers:"

# Анализ последних событий
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'
# → Warning  Unhealthy  pod/app-xxx  Startup probe failed: HTTP probe failed with statuscode: 503
```

**Решение:**
1. Если прокси-сервер требует длительной инициализации для прогрева кэша или загрузки TLS-сертификатов, увеличьте `failureThreshold` и `periodSeconds`:
   ```yaml
   startupProbe:
     httpGet:
       path: /healthz
       port: 8080
     initialDelaySeconds: 5
     periodSeconds: 3
     failureThreshold: 20   # 5 + (3 * 20) = до 65 секунд на старт
   ```
2. Проверьте логи: `kubectl logs <pod-name> -c <sidecar-name>`.

---

### Ошибка 2: Зависание Pod в состоянии `Terminating` при удалении

**Симптом:** При удалении Pod зависает в статусе `Terminating` на 30–60 секунд до принудительного уничтожения по таймауту `SIGKILL`.

**Причина:**
1. Контейнер приложения завершился (`Terminated`), но сайдкар всё ещё находится в состоянии `Running`, игнорируя сигнал `SIGTERM`.
2. Процесс в сайдкаре запущен через оболочку `sh` без директивы `exec` (проблема PID 1: shell поглощает сигналы POSIX и не передает их дочернему демону).

**Диагностика:**
```bash
# Проверка состояния контейнеров в Terminating Pod
kubectl get pod <pod-name> -o jsonpath='{
  "App:     "}{.status.containerStatuses[*].state}{"\n"}
  {"Sidecar: "}{.status.initContainerStatuses[*].state}{"\n"}'
# → App:     {"terminated":{"exitCode":0,"reason":"Completed"}}
# → Sidecar: {"running":{"startedAt":"..."}}
```

**Решение:**
1. Убедитесь, что бинарный файл внутри сайдкара запускается напрямую в манифесте либо в скрипте через `exec`:
   ```sh
   # ОШИБКА: trap не сработает надежно
   /usr/sbin/my-agent &
   
   # ПРАВИЛЬНО: замена процесса shell на процесс агента
   exec /usr/sbin/my-agent --config=/etc/agent.conf
   ```
2. Скорректируйте `terminationGracePeriodSeconds` в соответствии с реальным временем сброса буферов приложения.

---

### Ошибка 3: Зависание Pod в статусе `Pending` (Resource Starvation)

**Симптом:** Планировщик выдает ошибку `0/10 nodes are available: insufficient cpu, insufficient memory`.

**Причина:** Запросы ресурсов (`resources.requests`) сайдкара завышены. Поскольку ресурсы нативных сайдкаров суммируются с запросами приложения, общий запрос Pod превышает доступную емкость рабочих узлов (Node Allocatable).

**Диагностика:**
```bash
# Проверка эффективных запросов Pod
kubectl describe pod <pod-name> | grep -A 10 "Requests:"
# → cpu: 4200m (200m app + 4000m sidecar) — узел не найден
```

**Решение:**
1. Установите минимально достаточные `requests` для сайдкаров, отражающие реальное фоновое потребление:
   ```yaml
   resources:
     requests:
       cpu: 25m
       memory: 64Mi
     limits:
       cpu: 200m
       memory: 256Mi
   ```
2. Рассмотрите перенос тяжелых операций сбора логов/метрик из уровня каждого Pod в архитектуру DaemonSet на уровне ноды.

---

### Ошибка 4: Конфликт сетевых портов (`bind: address already in use`)

**Симптом:** Сайдкар или основной контейнер падает сразу после запуска с ошибкой связывания порта.

**Причина:** Основной контейнер и сайдкар пытаются забиндить одинаковый порт на сетевом интерфейсе `0.0.0.0` или `127.0.0.1` в общем Network Namespace Pod.

**Диагностика:**
```bash
kubectl logs <pod-name> -c <crashing-container>
# → [emerg] bind() to 0.0.0.0:8080 failed (98: Address already in use)
```

**Решение:**
1. Проведите аудит портов всех контейнеров в манифесте Pod.
2. Переназначьте локальные порты амбассадоров/прокси на выделенные диапазоны (например, приложение слушает `8080`, прокси принимает внешний трафик на `8443` или перенаправляет на `9000`).

---

### Ошибка 5: Ошибка прав доступа `Permission Denied` в разделяемом томе

**Симптом:** Приложение не может прочитать файл, сгенерированный сайдкаром (или сайдкар не может прочитать логи приложения).

**Причина:** По умолчанию каталог тома `emptyDir` создается с владельцем `root:root` (`UID:GID 0:0`). Если приложение запускается под непривилегированным пользователем (`runAsUser: 10001`), а сайдкар создал файл с маской `0600` от root, приложение получает отказ в доступе.

**Решение:**
1. Настройте групповые права доступа через `spec.securityContext.fsGroup`:
   ```yaml
   spec:
     securityContext:
       fsGroup: 2000
       runAsNonRoot: true
   ```
   Kubelet автоматически сменит группу владельца монтируемого тома на GID `2000` и предоставит права на чтение/запись процессам этой группы.

---

### Ошибка 6: Зависание Kubernetes Job / CronJob из-за классического сайдкара

**Симптом:** Задача выполнила расчеты (`main container completed with exit code 0`), но объект Job остается в состоянии `Running`, не завершаясь.

**Причина:** Классический сайдкар в `spec.containers[]` продолжает работать в бесконечном цикле. Контроллер Job считает Pod завершенным только тогда, когда **все** контейнеры массива `spec.containers[]` завершили работу.

**Решение:**
1. Перенесите вспомогательный контейнер в `spec.initContainers[]` с директивой `restartPolicy: Always` (Native Sidecar). Kubelet автоматически завершит нативный сайдкар сразу после завершения основного контейнера Job.

---

## Рекомендации и лучшие практики

1. **Используйте Native Sidecars (K8s 1.29+):** Переведите вспомогательные сервисы (Envoy, Vault Agent, сборщики метрик) на нативные сайдкары. Это устраняет гонки инициализации и гарантирует доступность сетевого прокси до старта приложения.
2. **Всегда объявляйте `startupProbe` для Native Sidecar:** Без `startupProbe` Kubelet считает нативный сайдкар готовым сразу после вызова runtime start, что может привести к сбою приложения, если прокси еще не успел прогреть конфигурацию.
3. **Минимизируйте `resources.requests`:** Сайдкары тиражируются вместе с каждой репликой Pod. Избыточный оверхед в `requests` приводит к фрагментации ресурсов кластера и преждевременному отказу планировщика.
4. **Не используйте `lifecycle` hooks в нативных сайдкарах:** Спецификация Kubernetes отвергает директивы `preStop` и `postStart` внутри блока `initContainers`. Реализуйте graceful shutdown исключительно через перехват `SIGTERM`.
5. **Используйте `emptyDir` в памяти для чувствительных данных:** Секреты, токены и UNIX-сокеты монтируйте в `emptyDir` с параметром `medium: Memory` (tmpfs). Это защитит секреты от сброса на физический диск ноды и ускорит обмен данными.
6. **Ограничивайте размер разделяемых томов:** Обязательно указывайте `sizeLimit` для всех томов `emptyDir` (особенно при буферизации логов), чтобы исключить исчерпание пространства на корневом разделе ноды (`DiskPressure`).
7. **Соблюдайте безопасность (Least Privilege):** Запускайте сайдкары с `securityContext.runAsNonRoot: true` и `allowPrivilegeEscalation: false`. Блокируйте запись в корневую файловую систему (`readOnlyRootFilesystem: true`).
8. **Используйте `shareProcessNamespace` только при явной необходимости:** Включение общего дерева процессов снижает изоляцию между контейнерами Pod. Применяйте его только для сигнального взаимодействия (`SIGHUP`) или низкоуровневой отладки.
9. **Архитектурный выбор (Sidecar vs DaemonSet):** Не превращайте сайдкары в монолитные агенты. Для универсального сбора метрик и логов узла предпочтительнее использовать централизованные агенты DaemonSet, а паттерн Sidecar резервировать для задач, требующих изоляции контекста приложения.

---

## Связанные темы

* [Init-контейнеры в Kubernetes](./pod_init_containers.md) — базовые принципы инициализации и KEP-3839.
* [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — фазы Pod, обработка сигналов и очереди состояний.
* [Пробы (Probes) в Kubernetes](../probes.md) — настройка проверок готовности и живучести контейнеров.
* [Эфемерные контейнеры (Ephemeral Containers)](./ephemeral_containers.md) — интерактивная отладка sidecar-контейнеров на лету.
* [Перезапуск Pod и политика RestartPolicy](./pod_restarts.md) — поведение CrashLoopBackOff для нативных сайдкаров.
* [QoS, Requests и Limits](../../Scheduling/qos_limit_and_requests.md) — расчет эффективных ресурсов многоконтейнерных подов.
* [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md#порядок-завершения-native-sidecar-k8s-129) — детальный порядок завершения Native Sidecars.
* [Диагностика зависания Pod](../../Troubleshooting/Common_Errors/PodTerminating/diagnostics.md#22-native-sidecars-k8s-129) — пошаговый траблшутинг native sidecars при удалении.
