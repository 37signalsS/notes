# Паттерны Sidecar в Kubernetes

## Определения

**Sidecar Pattern (Сайдкар)** — архитектурный паттерн многоконтейнерного Pod, при котором вспомогательный контейнер запускается рядом с основным приложением для расширения его функциональности (логирование, мониторинг, безопасность), не изменяя код самого приложения.

**Adapter Pattern (Адаптер)** — специализированный вид сайдкара, который унифицирует вывод основного приложения (например, преобразует кастомные логи или метрики в стандартный формат) для внешних систем мониторинга.

**Ambassador Pattern (Амбассадор)** — вид сайдкара, выступающий в роли прокси-сервера для управления **исходящими** сетевыми соединениями приложения (например, для реализации логики ретраев, балансировки или защиты соединений с БД).

**Native Sidecar (Нативный сайдкар)** — механизм Kubernetes (beta с v1.29, стабилен с v1.33), позволяющий определять вспомогательные контейнеры как `initContainers` с параметром `restartPolicy: Always`. Это гарантирует их запуск до основного приложения и работу на протяжении всего жизненного цикла Pod. Подробности описаны в KEP-3839.

**Volume Sidecar** — паттерн, при котором сайдкар расшаривает (shared volumes) файлы с основным контейнером для передачи данных, конфигурации или логов. Реализуется через `emptyDir` или `configMap`/`secret` volumes с `volumeMounts`.

---

## Базовые концепции

### Виды паттернов и их применение

| Паттерн | Назначение | Пример реализации |
| :--- | :--- | :--- |
| **Sidecar** | Расширение возможностей приложения | Fluentd для сбора логов, синхронизация конфигов git-sync. |
| **Adapter** | Унификация интерфейса взаимодействия | Конвертер кастомных метрик в формат Prometheus. |
| **Ambassador** | Упрощение сетевого взаимодействия | Проксирование запросов к БД или внешним API (Envoy). |

**Типовые задачи sidecar-контейнеров:**

*   **Наблюдаемость:** сбор и отправка логов (Fluentbit, Filebeat) и экспорт метрик (metrics exporter) без внедрения агентов в код приложения.
*   **Сетевое взаимодействие:** реализация Service Mesh, mTLS и управления трафиком (Envoy в Istio, Linkerd proxy).
*   **Конфигурация:** динамическая подгрузка настроек и ротация секретов из внешних источников (Vault Agent Injector — запись в shared Volume).
*   **Безопасность:** автоматическое управление TLS сертификатами и аутентификацией.

### Сравнение: Классический Sidecar vs Native Sidecar

| Характеристика | Классический Sidecar | Native Sidecar |
| :--- | :--- | :--- |
| **Определение** | Обычный контейнер в `containers[]` | Init-контейнер с `restartPolicy: Always` |
| **Порядок запуска** | Параллельно с основным | **До** основного (init-секция) |
| **Готовность до старта приложения** | Не гарантирована | Гарантирована (через `startupProbe`) |
| **Завершение** | Параллельно с основным | **После** основного контейнера |
| **Перезапуск при падении** | Может повлиять на Pod | Независимый (только сам сайдкар) |
| **Probes** | Все типы | `startupProbe`, `readinessProbe` |
| **Lifecycle hooks** | `postStart`, `preStop` | Не поддерживаются |
| **Ресурсы в QoS** | Суммируются | Суммируются |
| **Совместимость** | Все версии K8s | K8s 1.28+ (beta), 1.33+ (GA) |

### Жизненный цикл Native Sidecar

**Запуск (порядок инициализации):**
1. Kubelet запускает все init-контейнеры строго последовательно.
2. Обычные init-контейнеры (`restartPolicy: Never` или `OnFailure`) завершаются до перехода к следующему.
3. **Native Sidecar** (`restartPolicy: Always`) не завершается — он переходит в фоновый режим и продолжает работать.
4. Только после successful completion (или ready-состояния через startupProbe) всех init-контейнеров запускаются основные контейнеры.

**Работа:**
*   Native Sidecar работает параллельно с основными контейнерами.
*   Если Native Sidecar падает, он перезапускается независимо (не влияет на основной контейнер).
*   Основной контейнер НЕ перезапускается при падении Native Sidecar.

**Завершение:**
1. При получении SIGTERM (или истечении `terminationGracePeriodSeconds`) — завершаются **основные контейнеры**.
2. Kubelet ожидает их полной остановки (или `preStop` хуков).
3. Только после этого начинается завершение Native Sidecar.
4. Гарантия: вспомогательный сервис (прокси, логирование) жив, пока приложение корректно завершает работу.

**Подробнее:** Порядок завершения детально описан в [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md#порядок-завершения-native-sidecar-ks-129).

### Readiness Probes и Native Sidecar

Для Native Sidecar поддерживается `startupProbe` и `readinessProbe`. Если Native Sidecar определён как init-контейнер с `restartPolicy: Always` и имеет `startupProbe`:

*   Основные контейнеры **не начнут запуск**, пока Native Sidecar не пройдет startupProbe (не станет `Ready`).
*   После прохождения startupProbe — поддерживается `readinessProbe` для отслеживания здоровья сайдкара.
*   Если readinessProbe сайдкара падает — сайдкар помечается как `NotReady`, но **не влияет** на готовность Pod (основные контейнеры не перезапускаются).

Это критично для Service Mesh (Envoy/Istio): прокси должен быть полностью готов к обработке трафика до того, как приложение начнет отправлять запросы.

**Подробнее:** [Пробы (Probes) в Kubernetes](../../Base/probes.md#взаимодействие-с-native-sidecars-v129).

### Ресурсы и QoS

При расчёте QoS-класса Pod ресурсы Native Sidecar суммируются с основными контейнерами:

```
EffectiveRequest = sum(app_containers_requests) + sum(sidecar_containers_requests)
EffectiveLimit   = sum(app_containers_limits)   + sum(sidecar_containers_limits)
```

**Важно:** Если установить большие `resources.requests` для сайдкара (например, `cpu: "4"`), планировщик будет искать узел с 4 CPU свободными, даже если основному приложению нужно всего `100m`. Это **типичная ошибка**, которая приводит к Pending Pod.

**Подробнее:** [QoS, Requests и Limits](../../Scheduling/qos_limit_and_requests.md).

---

## Практические сценарии

### Сценарий 1: Sidecar для сбора логов (Классический)

Использование Fluentd для чтения логов из общего Volume и их отправки в хранилище:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-logging
spec:
  volumes:
  - name: log-storage
    emptyDir: {}
  containers:
  - name: main-app
    image: my-app:1.2.0
    volumeMounts:
    - name: log-storage
      mountPath: /var/log/app
  - name: log-shipper
    image: fluent/fluentd:v1.16
    volumeMounts:
    - name: log-storage
      mountPath: /var/log/app
      readOnly: true
```

### Сценарий 2: Native Sidecar с гарантированной готовностью

Использование прокси-сервера Envoy, который должен быть полностью готов до того, как приложение начнет отправлять запросы:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-envoy
spec:
  initContainers:
  - name: envoy-proxy
    image: envoyproxy/envoy:v1.39.0
    restartPolicy: Always  # Делает контейнер нативным сайдкаром
    startupProbe:
      httpGet:
        path: /ready
        port: 9901
      initialDelaySeconds: 5
      periodSeconds: 2
      failureThreshold: 10
  containers:
  - name: app
    image: my-app:1.2.0
```

### Сценарий 3: Ambassador для legacy-приложений

Проксирование трафика для приложения, которое умеет работать только с `localhost`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: legacy-app-proxy
spec:
  containers:
  - name: legacy-app
    image: old-service:1.0 # Слушает только 127.0.0.1:8080
  - name: ambassador-proxy
    image: nginx:alpine
    volumeMounts:
    - name: config
      mountPath: /etc/nginx/conf.d
  volumes:
  - name: config
    configMap:
      name: proxy-config
```

### Сценарий 4: Adapter для метрик (Prometheus)

Сайдкар, который конвертирует кастомный формат метрик приложения в Prometheus-совместимый формат. Используется, когда приложение экспортит метрики в собственном формате, а внешний стек мониторинга работает через Prometheus:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-metrics-adapter
  labels:
    app: my-service
spec:
  volumes:
  - name: metrics-socket
    emptyDir: {}
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: metrics-socket
      mountPath: /tmp/metrics
    env:
    - name: METRICS_SOCKET
      value: /tmp/metrics/app.sock
  - name: metrics-exporter
    image: prom/statsd-exporter:v0.27.0
    args:
    - "--statsd.listen-udp=:9125"
    - "--statsd.listen-unixgram=/tmp/metrics/app.sock"
    - "--web.telemetry-path=/metrics"
    ports:
    - containerPort: 9125
      name: statsd
    - containerPort: 9102
      name: metrics
    volumeMounts:
    - name: metrics-socket
      mountPath: /tmp/metrics
      readOnly: true
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 100m
        memory: 128Mi
```

### Сценарий 5: Vault Agent Injector для секретов

Динамическая подгрузка секретов из HashiCorp Vault через sidecar-агент. Vault Agent монтирует секреты в shared volume и автоматически обновляет их при ротации:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-vault-secrets
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/agent-inject-secret-db: "secret/data/db"
    vault.hashicorp.com/agent-inject-template-db: |
      {{- with secret "secret/data/db" -}}
      DB_HOST={{ .Data.data.host }}
      DB_PORT={{ .Data.data.port }}
      DB_PASSWORD={{ .Data.data.password }}
      {{- end -}}
spec:
  serviceAccountName: vault-auth
  containers:
  - name: app
    image: my-app:1.0
    env:
    - name: DB_HOST
      valueFrom:
        secretKeyRef:
          name: vault-db-secrets
          key: DB_HOST
```

### Сценарий 6: Git-sync для конфигурации

Сайдкар, который синхронизирует конфигурацию из Git-репозитория в shared volume. Полезно для hot-reload конфигурации без перезапуска Pod:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-git-sync
spec:
  initContainers:
  - name: git-sync
    image: registry.k8s.io/git-sync/git-sync:v4.4.0
    args:
    - "--repo=https://github.com/myorg/configs.git"
    - "--root=/config"
    - "--one-time"  # Только для init; для native sidecar уберите флаг
    env:
    - name: GITHUB_TOKEN
      valueFrom:
        secretKeyRef:
          name: git-credentials
          key: token
    volumeMounts:
    - name: config-volume
      mountPath: /config
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: config-volume
      mountPath: /etc/config
      readOnly: true
  volumes:
  - name: config-volume
    emptyDir: {}
```

### Сценарий 7: Rate-limiter через Native Sidecar

Сайдкар, который ограничивает исходящий трафик приложения (например, к внешнему API с rate limit). Работает как прокси с логикой rate-limiting:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-rate-limiter
spec:
  initContainers:
  - name: rate-limiter
    image: nginx:alpine
    restartPolicy: Always  # Native Sidecar
    ports:
    - containerPort: 8080
      name: proxy
    lifecycle:
      postStart:
        exec:
          command:
          - /bin/sh
          - -c
          - |
            # Конфигурация rate limiting через nginx
            cat > /etc/nginx/conf.d/rate-limit.conf << 'EOF'
            limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
            server {
              listen 8080;
              location / {
                limit_req zone=api burst=20 nodelay;
                proxy_pass http://127.0.0.1:9000;
              }
            }
            EOF
    startupProbe:
      tcpSocket:
        port: 8080
      initialDelaySeconds: 2
      periodSeconds: 1
    readinessProbe:
      tcpSocket:
        port: 8080
      periodSeconds: 5
    volumeMounts:
    - name: nginx-conf
      mountPath: /etc/nginx/conf.d
  containers:
  - name: app
    image: my-app:1.0
  volumes:
  - name: nginx-conf
    emptyDir: {}
```

### Сценарий 8: Sidecar для автоматической ротации TLS-сертификатов

Сайдкар, который обновляет TLS-сертификаты из внешнего источника (Vault, cert-manager) и записывает их в shared volume. Основное приложение подхватывает обновления без перезапуска:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-cert-rotation
spec:
  initContainers:
  - name: cert-rotator
    image: jetstack/cert-manager-csi:v0.5.0
    args:
    - "--cert-path=/certs"
    - "--csi-mode"
    restartPolicy: Always  # Native Sidecar
    volumeMounts:
    - name: certs
      mountPath: /certs
      readOnly: true
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: certs
      mountPath: /etc/tls
      readOnly: true
  volumes:
  - name: certs
    emptyDir: {}
```

---

## Troubleshooting: типичные ошибки sidecar-контейнеров

### Ошибка 1: Sidecar crash loop — Pod не становится Ready

**Причина:** Классический sidecar падает до того, как основной контейнер стартует, или readinessProbe не проходит.

**Диагностика:**
```bash
kubectl describe pod <pod> | grep -A 5 "Containers:"
kubectl logs <pod> -c <sidecar-name> --previous
```

**Решение:**
1. Добавьте `startupProbe` для sidecar (особенно для Native Sidecar):
```yaml
startupProbe:
  httpGet:
    path: /ready
    port: 9901
  initialDelaySeconds: 5
  periodSeconds: 2
  failureThreshold: 10
```
2. Увеличьте `failureThreshold` — некоторые прокси (Envoy) требуют время на инициализацию.
3. Проверьте, что образ не «тини»/«scratch» — убедитесь в наличии health-check эндпоинта.

### Ошибка 2: Зависание Pod при удалении (Terminating)

**Причина:** Native Sidecar не завершается вовремя или заблокировал `preStop` хук.

**Диагностика:**
```bash
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].state}'
# Если основной контейнер Terminated, но sidecar仍在 Running — проблема с завершением
```

**Решение:**
1. Проверьте, что sidecar обрабатывает `SIGTERM`:
```bash
kubectl describe pod <pod> | grep -A 3 "preStop"
```
2. Установите разумный `terminationGracePeriodSeconds` (30-60 сек).
3. Для Native Sidecar: убедитесь, что внутри сайдкара нет бесконечных процессов, игнорирующих SIGTERM.

**Подробнее:** [Диагностика завершения Pod](../../Troubleshooting/Common_Errors/PodTerminating/diagnostics.md#этап-2-диагностика-native-sidecars-ks-129).

### Ошибка 3: Sidecar потребляет слишком много ресурсов

**Причина:** Ресурсы sidecar суммируются с основными контейнерами. Большие `requests` sidecar приводят к Pending Pod.

**Диагностика:**
```bash
kubectl describe pod <pod> | grep -A 10 "Requests:"
# → cpu: 4200m (500m app + 3700m sidecar) — Pod не может быть размещен
```

**Решение:**
1. Установите реалистичные `requests`/`limits` для sidecar:
```yaml
resources:
  requests:
    cpu: 50m      # Минимум для прокси
    memory: 64Mi
  limits:
    cpu: 200m
    memory: 128Mi
```
2. Проверьте, не является ли sidecar «сервисным бездельником» — возможно, его функциональность может быть вынесена наружу (Ingress Controller, DaemonSet).

**Подробнее:** [QoS, Requests и Limits](../../Scheduling/qos_limit_and_requests.md).

### Ошибка 4: Ephemeral контейнер не видит процессы sidecar

**Причина:** По умолчанию `shareProcessNamespace: false` — каждый контейнер в Pod имеет свой PID namespace.

**Решение:**
```bash
# Добавление ephemeral контейнера с общим PID namespace
kubectl debug -it <pod> --image=alpine --share-processes --target=<sidecar-name>

# Или включить в манифесте Pod:
spec:
  shareProcessNamespace: true
```

**Подробнее:** [Ephemeral Containers](./ephemeral_containers.md).

### Ошибка 5: Sidecar блокирует завершение Job

**Причина:** Обычные sidecar-контейнеры (не Native Sidecar) не завершаются при завершении Job, «зависая» навсегда.

**Диагностика:**
```bash
kubectl get pods -l job-name=<job> -o jsonpath='{.items[*].status.conditions[*].reason}'
# → PodMarkedForDeletion — Job завершен, но Pod не удаляется из-за sidecar
```

**Решение:**
1. Используйте **Native Sidecar** (init-контейнер с `restartPolicy: Always`) — контроллер Job автоматически завершает Native Sidecar после успешного выполнения основных контейнеров.
2. Или добавьте `activeDeadlineSeconds` к Job для принудительного завершения.

**Подробнее:** [Job в Kubernetes](../job.md).

---

## Best Practices

1. **Используйте Native Sidecar (K8s 1.29+)** для sidecar-функций (логирование, мониторинг, прокси). Это решает проблемы жизненного цикла: гарантированный порядок запуска/завершения.
2. **Всегда указывайте `startupProbe`** для Native Sidecar — это гарантирует, что приложение не стартует до готовности прокси/агента.
3. **Ограничивайте ресурсы sidecar** — `requests.cpu` и `requests.memory` должны быть минимально достаточными. Не превращайте sidecar в «второе приложение».
4. **Не используйте `preStop` хуки** для sidecar — Native Sidecar не поддерживает lifecycle hooks. Используйте graceful shutdown через SIGTERM и приложение.
5. **Для Job/CronJob** — всегда используйте Native Sidecar вместо обычного sidecar-контейнера. Обычный sidecar блокирует завершение Job.
6. **shareProcessNamespace** — включайте при необходимости обмен сигналами между контейнерами (например, sidecar отправляет SIGTERM основному процессу).
7. **Логирование через shared volume** — если sidecar собирает логи, используйте `emptyDir` с `medium: Memory` (tmpfs) для минимизации задержки.
8. **Избегайте sidecar для критических функций** — если sidecar падает, Pod может потерять наблюдаемость или сетевую функциональность. Рассмотрите DaemonSet или DaemonSet-based alternatives для критических сервисов.

---

## Связанные темы

*   [Init-container в Kubernetes](./pod_init_containers.md) — базовые сведения об инициализации и Native Sidecar.
*   [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — детали фаз и Graceful Shutdown.
*   [Ephemeral Containers](./ephemeral_containers.md) — отладка sidecar-контейнеров через ephemeral containers.
*   [Перезапуск Pod в Kubernetes](./pod_restarts.md) — перезапуск Native Sidecar и exponential backoff.
*   [Пробы (Probes) в Kubernetes](../../Base/probes.md) — взаимодействие с Native Sidecars.
*   [QoS, Requests и Limits](../../Scheduling/qos_limit_and_requests.md) — расчёт ресурсов sidecar.
*   [Обзор Service в Kubernetes](../../Networking/Service/service_overview.md) — сетевое взаимодействие.
*   [Job в Kubernetes](../job.md) — завершение sidecar в задачах.
*   [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — порядок завершения Native Sidecar.
*   [Ephemeral Containers](./ephemeral_containers.md) — отладка «на лету».
