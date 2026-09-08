# Init-container в Kubernetes

## Определения

**Init-container (Инициализирующий контейнер)** — специализированный контейнер, который запускается и должен успешно завершиться (Exit Code 0) до начала работы основных контейнеров в Pod. Предназначен для подготовки среды, ожидания зависимостей или выполнения задач, результаты которых необходимы приложению.

**Native Sidecar (Нативный сайдкар)** — механизм Kubernetes (beta с v1.29, стабилен с v1.33), позволяющий определять sidecar-контейнеры как Init-контейнеры с параметром `restartPolicy: Always`. Такие контейнеры работают на протяжении всего жизненного цикла Pod, обеспечивая вспомогательные функции (логирование, мониторинг, проксирование). Описан в [KEP-3839](https://github.com/kubernetes/enhancements/tree/master/keps/sig-node/3839-sidecar-containers).

**Идемпотентность (Idempotency)** — свойство операции, при котором повторное выполнение не приводит к дополнительным побочным эффектам. Init-контейнеры должны быть идемпотентными, так как могут перезапускаться (например, при сбое узла) или выполняться повторно в Job.

**activeDeadlineSeconds** — параметр Pod, ограничивающий общее время жизни Pod в секундах, включая этап выполнения всех Init-контейнеров. Если время истечет до завершения init-контейнеров, Pod будет принудительно завершен с кодом ошибки.

**restartPolicy (для Init-контейнеров)** — определяет поведение при завершении Init-контейнера. Для обычных init-контейнеров: `Never` (не перезапускать) или `OnFailure` (перезапуск только при ошибке). Для Native Sidecar: `Always` (перезапуск всегда, работает параллельно с основными контейнерами).

---

## Базовые концепции

### Назначение и сценарии использования

Init-контейнеры позволяют вынести вспомогательную логику из основного образа приложения, уменьшая его размер и поверхность атаки.

| Сценарий | Описание | Типичные образы |
| :--- | :--- | :--- |
| **Ожидание зависимостей** | Блокировка старта приложения до доступности внешних сервисов (БД, API, очередей): `nc -z db 5432`, `wget -q --spider http://api:8080/health`. | `busybox`, `alpine`, `curlimages/curl` |
| **Подготовка данных** | Скачивание артефактов, клонирование Git-репозитория или генерация конфигов в общий `emptyDir` том. | `alpine/git`, `bitnami/kubectl`, `curlimages/curl` |
| **Управление правами** | Изменение владельца (`chown`) или прав доступа (`chmod`) на монтируемых томах для работы от имени не-root пользователя. | `busybox`, `alpine` |
| **Миграции баз данных** | Выполнение скриптов обновления схемы БД перед запуском приложения. | Образ приложения с CLI миграций |
| **Безопасность** | Утилиты (curl, git, sed) используются только на этапе инициализации и не включаются в финальный образ приложения, что снижает поверхность атаки. | Любые утилитарные образы |
| **Валидация конфигурации** | Проверка доступности ресурсов, корректности TLS-сертификатов или наличия обязательных переменных окружения перед стартом приложения. | `busybox`, `alpine`, `curlimages/curl` |
| **Многоэтапная подготовка** | Последовательная обработка данных: скачивание → трансформация → проверка → копирование в общую директорию. | Разные образы для каждого этапа |

### Порядок выполнения и жизненный цикл

1.  **Последовательность:** Init-контейнеры выполняются строго по одному в порядке их объявления в массиве `spec.initContainers`.
2.  **Условие перехода:** Следующий контейнер запускается только после успешного завершения текущего (Exit Code 0).
3.  **Сбой и перезапуск:** Если Init-контейнер завершается с ошибкой (Exit Code != 0), Kubelet перезапускает его согласно `restartPolicy` Пода. По умолчанию — `OnFailure` (перезапуск при ошибке). С каждым перезапуском интервал удваивается (exponential backoff): 10с → 20с → 40с → ... до `activeDeadlineSeconds` Pod.
4.  **Запуск приложения:** Основные контейнеры (`spec.containers`) запускаются параллельно только после успешного завершения всех обычных Init-контейнеров.
5.  **Завершение Pod:** При завершении Pod (kill, drain, rolling update) Native Sidecar (`restartPolicy: Always`) завершаются **после** основных контейнеров. Обычные init-контейнеры уже завершились к этому моменту.

**Особенности жизненного цикла:**
*   **Идемпотентность:** Init-контейнеры могут перезапускаться (например, при сбое узла или в Job). Их логика должна быть идемпотентной: повторное выполнение не должно приводить к ошибкам или повреждению данных в общем томе.
*   **activeDeadlineSeconds:** Ограничивает общее время жизни Pod, включая этап выполнения всех Init-контейнеров. Если время истечет до завершения init-контейнеров, Pod будет принудительно завершен. Важно учитывать это при настройке долгих миграций.
*   **Изменение образа:** Изменение `image` у Init-контейнера в уже запущенном Pod невозможно без пересоздания объекта. Для обновления используйте Deployment/Rolling Update.
*   **restartPolicy для обычных init:** Допустимые значения — `Never` (не перезапускать, завершить Pod) или `OnFailure` (перезапуск при ошибке). `Always` **запрещен** для обычных init-контейнеров — это зарезервировано для Native Sidecar.

### Взаимодействие с Native Sidecars (v1.29+)

Если контейнер помечен как нативный сайдкар (`restartPolicy: Always` в блоке `initContainers`):
*   **Блокировка:** Он запускается в порядке очереди, но следующий контейнер (обычный init или основной) начнет запуск только после того, как сайдкар перейдет в состояние `Ready` (успешное прохождение `startupProbe` или `readinessProbe`).
*   **StartupProbe:** Если настроена `startupProbe`, основные контейнеры не начнут запуск, пока все нативные сайдкар-контейнеры не пройдут эту проверку.
*   **Параллелизм:** Работает на протяжении всего жизненного цикла Pod параллельно с основными контейнерами.
*   **Завершение:** При завершении Pod основные контейнеры получают `SIGTERM` первыми. Только после их полного завершения (или `terminationGracePeriodSeconds`) начинается завершение Native Sidecar. Это гарантирует, что вспомогательный сервис (прокси, логирование) жив, пока приложение корректно завершает работу.

Подробнее о паттернах: [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md).

### Сравнение типов контейнеров

| Характеристика | Init-container | Native Sidecar | Основной container |
| :--- | :--- | :--- | :--- |
| **Порядок запуска** | Строго последовательный | Последовательный (среди init) | Параллельный (после всех init) |
| **Время работы** | Кратковременный (до Exit Code 0) | Долгоживущий (весь цикл Pod) | Долгоживущий (до остановки) |
| **restartPolicy** | `Never` или `OnFailure` | `Always` | `Always` (по умолчанию) |
| **Probes** | **Не поддерживаются** (кроме Native Sidecar) | `startupProbe`, `readinessProbe` | Все типы: liveness, readiness, startup |
| **Lifecycle hooks** | Не поддерживаются | Не поддерживаются | `postStart`, `preStop` |
| **Статус Pod** | Pod не готов (Ready: false) | Pod не Ready до прохождения startupProbe | Зависит от readiness probe |
| **Завершение** | Завершился ДО запуска приложения | Завершается **после** основных контейнеров | Завершается первыми |
| **Ресурсы** | `max(max(init), sum(app))` | Суммируются с основными | Суммируются |
| **Перезапуск** | Exponential backoff (10с→20с→...) | Независимый (только сам) | Независимый или DependsOn |

### Расчет ресурсов (Requests и Limits)

При планировании Pod ресурсы рассчитываются с учетом последовательного характера работы init-контейнеров:

**Обычные Init-контейнеры:**
```
EffectiveRequest = max(max(init_containers_requests), sum(app_containers_requests))
EffectiveLimit   = max(max(init_containers_limits),   sum(app_containers_limits))
```

**Native Sidecar (restartPolicy: Always):**
```
EffectiveRequest = sum(app_containers_requests) + sum(sidecar_containers_requests)
EffectiveLimit   = sum(app_containers_limits)   + sum(sidecar_containers_limits)
```

**Важно:** Если установить большие `resources.requests` для init-контейнера (например, `cpu: "4"`), планировщик будет искать узел с 4 CPU свободными, даже если основному приложению нужно всего `100m`. Это **типичная ошибка**, которая приводит к тому, что Pod не может быть размещен (Pending).

Подробнее: [QoS, Requests и Limits](../../Scheduling/qos_limit_and_requests.md).

---

## Практические сценарии

### Сценарий 1: Ожидание базы данных и миграция

Классический паттерн: сначала ожидаем доступность БД, затем выполняем миграции:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-db-init
spec:
  initContainers:
  - name: wait-db
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z db-service 5432; do echo "Waiting for DB..."; sleep 2; done']
    resources:
      requests:
        cpu: "10m"
        memory: "16Mi"
  - name: db-migration
    image: my-app-migrations:latest
    command: ['python', 'manage.py', 'migrate', '--no-input']
    env:
    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: url
    resources:
      requests:
        cpu: "100m"
        memory: "256Mi"
  containers:
  - name: main-app
    image: my-app:v1
    resources:
      requests:
        cpu: "200m"
        memory: "256Mi"
```

**Проверка:**
```bash
kubectl get pod app-db-init
# → NAME           READY   STATUS     RESTARTS   AGE
#   app-db-init    0/1     Init:0/2   0          15s

# После завершения:
# → NAME           READY   STATUS    RESTARTS   AGE
#   app-db-init    1/1     Running   0          45s
```

### Сценарий 2: Подготовка данных в общем томе

Init-контейнер скачивает контент в `emptyDir`, который затем монтируется в основной контейнер:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-static-fetch
spec:
  volumes:
  - name: html-dir
    emptyDir: {}
  initContainers:
  - name: fetch-content
    image: alpine:3.18
    command: ['sh', '-c', 'wget -O /data/index.html https://example.com/']
    volumeMounts:
    - name: html-dir
      mountPath: /data
    resources:
      requests:
        cpu: "10m"
        memory: "32Mi"
  containers:
  - name: nginx
    image: nginx:1.27
    volumeMounts:
    - name: html-dir
      mountPath: /usr/share/nginx/html
      readOnly: true
    ports:
    - containerPort: 80
```

**Проверка:**
```bash
kubectl exec nginx-static-fetch -- cat /usr/share/nginx/html/index.html
# → <!doctype html><html><head>...
```

### Сценарий 3: Валидация конфигурации перед стартом

Init-контейнер проверяет наличие обязательных переменных окружения и корректность TLS-соединения:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: validated-app
spec:
  initContainers:
  - name: validate-env
    image: alpine:3.18
    command: ['sh', '-c', |
      set -e
      echo "Checking required env vars..."
      for var in DATABASE_URL REDIS_URL API_KEY; do
        if [ -z "$(eval echo \$$var)" ]; then
          echo "ERROR: $var is not set"
          exit 1
        fi
      done
      echo "All env vars present"
    env:
    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: app-secrets
          key: database-url
          optional: true
    - name: REDIS_URL
      valueFrom:
        configMapKeyRef:
          name: app-config
          key: redis-url
          optional: true
    - name: API_KEY
      valueFrom:
        secretKeyRef:
          name: app-secrets
          key: api-key
          optional: true
    resources:
      requests:
        cpu: "10m"
        memory: "16Mi"
  - name: validate-tls
    image: curlimages/curl:8.5.0
    command: ['sh', '-c', 'curl -sf --max-time 5 https://api.example.com/health || exit 1']
    resources:
      requests:
        cpu: "10m"
        memory: "16Mi"
  containers:
  - name: app
    image: my-app:1.0
```

### Сценарий 4: Многоэтапная подготовка данных

Несколько init-контейнеров выполняют последовательную обработку:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-stage-prep
spec:
  initContainers:
  - name: download
    image: alpine:3.18
    command: ['sh', '-c', 'wget -q -O /data/raw.tar.gz https://example.com/dataset.tar.gz']
    volumeMounts:
    - name: data
      mountPath: /data
    resources:
      requests:
        cpu: "100m"
        memory: "128Mi"
  - name: extract
    image: alpine:3.18
    command: ['sh', '-c', 'cd /data && tar xzf raw.tar.gz && rm raw.tar.gz']
    volumeMounts:
    - name: data
      mountPath: /data
    resources:
      requests:
        cpu: "50m"
        memory: "64Mi"
  - name: validate
    image: alpine:3.18
    command: ['sh', '-c', 'test -f /data/config.yaml && echo "Config valid" || exit 1']
    volumeMounts:
    - name: data
      mountPath: /data
    resources:
      requests:
        cpu: "10m"
        memory: "16Mi"
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: data
      mountPath: /app/data
      readOnly: true
  volumes:
  - name: data
    emptyDir: {}
```

### Сценарий 5: Diagnostics статусов в kubectl

| Статус | Значение | Диагностика |
| :--- | :--- | :--- |
| **Init:0/2** | Ни один из 2 Init-контейнеров еще не завершился. | Нормально в начале; если долго — проверяйте логи предыдущих init. |
| **Init:Error** | Контейнер завершился с кодом != 0. | `kubectl logs <pod> -c <init-name>` |
| **Init:CrashLoopBackOff** | Контейнер циклично падает (ошибки в команде, правах или зависимостях). | `kubectl logs <pod> -c <init-name> --previous` |
| **Init:Error/ImagePullBackOff** | Образ init-контейнера не может быть скачан. | Проверьте имя образа, тег, доступность registry, imagePullSecrets. |
| **PodInitializing** | Все Init-контейнеры завершены, запускаются основные контейнеры. | Нормально; если зависает — проверьте readinessProbe основных контейнеров. |
| **Pending** (без init) | Pod не может быть размещен (ресурсы, taints, PVC). | `kubectl describe pod <name> \| grep -A 5 Events` |

**Полезные команды диагностики:**
```bash
# Логи конкретного init-контейнера
kubectl logs <pod> -c <init-container-name>

# Логи предыдущего запуска (если контейнер упал и перезапустился)
kubectl logs <pod> -c <init-container-name> --previous

# События Pod (ошибки планирования, image pull, etc.)
kubectl describe pod <pod>

# Проверка текущего статуса init-контейнеров
kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].state}'

# Проверка количества перезапусков
kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].restartCount}'
```

---

## Troubleshooting: типичные ошибки init-контейнеров

### Ошибка 1: Init-контейнер зависает в ожидании (Wait forever)

**Причина:** Сервис недоступен, опечатка в имени сервиса, неправильный порт.

**Диагностика:**
```bash
# Проверка логов init-контейнера
kubectl logs <pod> -c wait-db

# Проверка DNS внутри Pod
kubectl exec <pod> -- nslookup db-service

# Проверка доступности порта
kubectl exec <pod> -- nc -zv db-service 5432
```

**Решение:**
1. Убедитесь, что имя сервиса и порт корректны.
2. Проверьте, что сервис существует: `kubectl get svc db-service`.
3. Добавьте таймаут и ограничение попыток:
```yaml
command: ['sh', '-c', 'for i in $(seq 1 30); do nc -z db-service 5432 && exit 0; sleep 2; done; echo "Timeout"; exit 1']
```

### Ошибка 2: CrashLoopBackOff init-контейнера

**Причина:** Ошибка в команде, недостаточно прав, отсутствующая зависимость.

**Диагностика:**
```bash
# Логи с предыдущего запуска
kubectl logs <pod> -c <init-name> --previous

# Проверка events
kubectl describe pod <pod> | grep -A 10 "Events"
```

**Решение:**
1. Проверьте логи — обычно содержат конкретную ошибку.
2. Убедитесь, что образ содержит нужные утилиты (busybox содержит `nc`, `wget`, `sh`).
3. Проверьте права доступа к томам (init-контейнер может запускаться от root).

### Ошибка 3: Init-контейнер не завершается из-за activeDeadlineSeconds

**Причина:** Время выполнения init-контейнера превышает лимит Pod.

**Диагностика:**
```bash
kubectl describe pod <pod> | grep -A 5 "Events"
# → Warning  DeadlineExceeded  Pod was active longer than specified deadline
```

**Решение:**
1. Увеличьте `activeDeadlineSeconds` Pod:
```yaml
spec:
  activeDeadlineSeconds: 3600  # 1 час
  initContainers:
  - name: long-task
    ...
```
2. Оптимизируйте init-контейнер (параллелизм, кэширование промежуточных результатов).

### Ошибка 4: OOMKilled init-контейнера

**Причина:** Недостаточно памяти для операций init-контейнера (скачивание больших файлов, распаковка архивов).

**Диагностика:**
```bash
kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].lastState.terminated.reason}'
# → OOMKilled

kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].resources}'
```

**Решение:**
1. Увеличьте `limits.memory` для init-контейнера:
```yaml
initContainers:
- name: download
  resources:
    requests:
      memory: "256Mi"
    limits:
      memory: "512Mi"  # Достаточно для распаковки архива
```
2. Используйте стриминг вместо полной загрузки в память.

### Ошибка 5: Init-контейнер блокирует запуск из-за неправильного restartPolicy

**Причина:** Использование `restartPolicy: Always` для обычного init-контейнера (запрещено) или `restartPolicy: Never` для Native Sidecar.

**Диагностика:**
```bash
kubectl describe pod <pod> | grep -A 3 "Warning"
# → Warning  FailedCreate  Error creating pod: restartPolicy: Always is not allowed for init containers
```

**Решение:**
- Обычные init-контейнеры: используйте `OnFailure` (по умолчанию) или `Never`.
- Native Sidecar: используйте `Always` (только для init-контейнеров).

### Ошибка 6: Init-контейнер не может записать в Volume

**Причина:** `readOnly: true` на volumeMount, неправильные права, или Volume не поддерживает запись.

**Диагностика:**
```bash
kubectl logs <pod> -c <init-name>
# → sh: can't create /data/file.txt: Read-only file system

kubectl get pod <pod> -o jsonpath='{.spec.initContainers[*].volumeMounts[*]}'
```

**Решение:**
1. Проверьте флаг `readOnly` в `volumeMounts`.
2. Убедитесь, что Volume поддерживает запись (`emptyDir`, `hostPath`, `PersistentVolumeClaim`).
3. `ConfigMap` и `Secret` доступны только для чтения — для записи используйте `emptyDir`.

---

## Best Practices для Production

1.  **Минимализм:** Используйте легковесные образы (`busybox`, `alpine`, `distroless`). Не устанавливайте ненужные пакеты.
2.  **Идемпотентность:** Каждый init-контейнер должен безопасно выполняться повторно. Используйте проверки существования перед записью.
3.  **Ресурсы:** Всегда указывайте `resources.requests` и `resources.limits` для init-контейнеров. Не используйте завышенные лимиты.
4.  **Таймауты:** Ограничивайте время выполнения через `activeDeadlineSeconds` или таймауты в командах.
5.  **Логирование:** Выводите информативные сообщения в stdout/stderr для диагностики.
6.  **Безопасность:** Не храните секреты в переменных окружения init-контейнеров — используйте `secretKeyRef`. Используйте `readOnlyRootFilesystem: true`.
7.  **Native Sidecar:** Для sidecar-функций (логирование, мониторинг, прокси) используйте Native Sidecar (`restartPolicy: Always`) вместо обычных init-контейнеров.
8.  **Паттерны:** Смотрите [Продвинутые паттерны init-контейнеров](./pod_advanced_topics.md#продвинутые-паттерны-init-контейнеров) для примеров (ожидание зависимости, миграция данных, клонирование конфигурации).

---

## Дополнительная информация

**Связанные темы:**

*   [Продвинутые темы Pod](./pod_advanced_topics.md) — продвинутые паттерны init-контейнеров, hostAliases, Scheduling Gates.
*   [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — детали фаз и условий.
*   [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md) — детальный разбор нативных сайдкаров.
*   [Управление ресурсами (QoS)](../../Scheduling/qos_limit_and_requests.md) — расчет лимитов и типичные ошибки.
*   [Перезапуск Pod в Kubernetes](./pod_restarts.md) — перезапуск Native Sidecar и exponential backoff.
