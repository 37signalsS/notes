# Перезапуск Pod в Kubernetes

## Определения

**Перезапуск контейнера (Container Restart)** — процесс завершения и повторного запуска процесса внутри контейнера. При этом объект Pod в API Kubernetes сохраняется, его сетевые идентификаторы (IP-адрес) и UID не меняются. Счётчик перезапусков (`restartCount`) в статусе пода увеличивается.

**Пересоздание Pod (Pod Recreation)** — полное удаление старого объекта Pod и создание нового. Новый Pod получает новый UID и, как правило, новый IP-адрес. Все счётчики перезапусков сбрасываются.

**CrashLoopBackOff** — состояние пода, указывающее на то, что контейнер падает сразу после старта, и Kubernetes перезапускает его с экспоненциально увеличивающейся задержкой (Back-off). Подробное описание: [Диагностика CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md).

**Graceful Shutdown (Корректное завершение)** — процесс корректного завершения работы контейнера с обработкой сигнала `SIGTERM`, сохранением состояния и завершением активных соединений. Регулируется через `terminationGracePeriodSeconds` (дефолт: 30с).

**PID 1 в контейнере** — основной процесс контейнера, который обрабатывает сигналы ОС (`SIGTERM`, `SIGKILL`). Если PID 1 — это shell-скрипт или обёртка без обработки сигналов, контейнер не будет корректно завершаться при `SIGTERM`.

**In-place Vertical Scaling** — возможность изменения ресурсов (CPU/Memory) работающего контейнера без его перезапуска (при поддержке рантаймом) или с перезапуском только целевого контейнера (через `resizePolicy`). [Подробнее](../../Autoscaling/in_place_pod_resize.md).

---

## Базовые концепции

### Перезапуск против пересоздания

Различие между этими процессами критично для диагностики состояния приложения и сохранения данных в эфемерной памяти.

| Характеристика | Перезапуск контейнера | Пересоздание Pod |
| :--- | :--- | :--- |
| **Объект в API** | Сохраняется (тот же UID) | Новый (новый UID) |
| **IP-адрес** | Сохраняется | Меняется (обычно) |
| **restartCount** | Увеличивается | Сбрасывается в 0 |
| **ФС контейнера** | Сбрасывается (кроме Volume) | Сбрасывается полностью |
| **Инициатор** | `kubelet` (на узле) | Контроллер (Deployment, и др.) |
| **Persistent Volume** | Монтируется повторно | Монтируется повторно |

### Механизмы и политики

#### Политика перезапуска (Restart Policy)
Определяет поведение `kubelet` при завершении работы контейнера (`spec.restartPolicy`):

| Политика | Описание | Типичные контроллеры |
| :--- | :--- | :--- |
| **Always** (дефолт) | Перезапуск при любом коде выхода | Deployment, StatefulSet, DaemonSet |
| **OnFailure** | Перезапуск только при ненулевом коде выхода | Job |
| **Never** | Контейнер не перезапускается | Job, CronJob |

#### Экспоненциальная задержка (Back-off)
Если контейнер падает повторно, `kubelet` вводит задержку перед следующим запуском:

```text
10с → 20с → 40с → 80с → 160с → 300с (максимум)
```

- **Максимальная задержка:** 300 секунд (5 минут).
- **Сброс счетчика:** После 10 минут успешной работы контейнера (`Running`).
- **Без ограничений для Deployment:** Цикл перезапуска бесконечен (отличие от Job).

> **Справка:** Подробное описание состояний CrashLoopBackOff, кодов завершения и архитектуры цикла перезапуска — [Определения и концепции CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md).

### Что вызывает перезапуск или пересоздание?

| Событие | Результат | Технический контекст |
| :--- | :--- | :--- |
| **Сбой процесса (Exit 1)** | Перезапуск | `kubelet` видит завершение процесса и запускает новый контейнер. |
| **OOMKilled** | Перезапуск | Ядро (OOM Killer) убивает процесс, `kubelet` фиксирует причину в статусе. |
| **Провал Liveness Probe** | Перезапуск | `kubelet` принудительно убивает контейнер для восстановления его работы. |
| **Провал Startup Probe** | Перезапуск | Контейнер не успел запуститься за отведенное время. |
| **Смена образа (Image)** | Пересоздание | Контроллер (Deployment) создает новый ReplicaSet → новые Pod. |
| **Обновление ConfigMap (Volume)** | Пересоздание | Манифест Pod изменяется → контроллер создает новые Pod. |
| **Обновление ConfigMap (ENV)** | Ничего | ENV задаются при старте контейнера, требуется `rollout restart`. |
| **Обновление Secret** | Варьируется | Volume — пересоздание, ENV — ничего (требуется restart). |
| **In-place Resize** | Варьируется | Если `resizePolicy: RestartContainer`, контейнер перезапустится с новыми лимитами. |
| **Eviction (Выселение)** | Пересоздание | Kubelet удаляет Pod при нехватке ресурсов на узле (Memory/Disk/PIDs). |
| **Preemption (Прекращение)** | Пересоздание | Scheduler удаляет Pod низкого приоритета для высокоприоритетного. |

---

## Влияние изменений конфигурации на перезапуски

### ConfigMap и Secret

Тип конфигурации определяет, будет ли Pod перезапущен:

| Тип | Ресурс | Эффект | Решение |
| :--- | :--- | :--- | :--- |
| **Volume** | ConfigMap/Secret монтирован как файл | **Пересоздание Pod** | Манифест Pod меняется → контроллер создает новые Pod. |
| **ENV** | `valueFrom.configMapKeyRef` | **Ничего** | Требуется `kubectl rollout restart` или нативный sidecar для hot-reload. |

**Пример монтирования ConfigMap как Volume:**
```yaml
# При обновлении ConfigMap:
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: app
    volumeMounts:
    - name: config
      mountPath: /etc/config
  volumes:
  - name: config
    configMap:
      name: my-config
```

**Проверка:**
```bash
# Если ConfigMap монтирован как Volume — Pod пересоздаётся
kubectl get pods --watch

# Если ConfigMap как ENV — Pod НЕ пересоздаётся
# Нужен ручной restart:
kubectl rollout restart deployment/<name>
```

### Deployment, StatefulSet, DaemonSet

| Объект | Изменение шаблона Pod | Команда |
| :--- | :--- | :--- |
| **Deployment** | Новые Pod с новым конфигом | `kubectl rollout restart deployment/<name>` |
| **StatefulSet** | Новые Pod в порядке скачков (0, 1, 2...) | `kubectl rollout restart statefulset/<name>` |
| **DaemonSet** | Обновление по одному на узел | `kubectl rollout restart daemonset/<name>` |

---

## Graceful Shutdown и обработка сигналов

### Механизм завершения Kubernetes

```text
1. API → Pod помечен на удаление (deletionTimestamp)
     ↓
2. kubelet → SIGTERM контейнеру (основной процесс)
     ↓
3. Ожидание terminationGracePeriodSeconds (30с по умолчанию)
     ↓
4. Если процесс жив → SIGKILL (принудительное завершение)
     ↓
5. PreStop hooks (если определены) выполняются до SIGTERM
```

### Настройка terminationGracePeriodSeconds

```yaml
apiVersion: v1
kind: Pod
spec:
  terminationGracePeriodSeconds: 60  # Для баз данных, требующих времени на flush
  containers:
  - name: app
    image: my-app:latest
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "nginx -s quit && sleep 5"]
```

**Рекомендации по значению:**

| Тип приложения | Рекомендуемое значение | Обоснование |
| :--- | :--- | :--- |
| **Stateless API** | 15–30с | Достаточно для завершения активных запросов |
| **Stateful (БД)** | 60–120с | Время на flush WAL, replication |
| **Batch-задачи** | 300–600с | Завершение обработки текущего батча |
| **Sidecar (Envoy)** | 30–60с | Drain соединений перед остановкой |

### Проблема PID 1 и tini/dumb-init

В大多数 образов основной процесс — это не PID 1, а shell-скрипт (т.к. Docker использует `/bin/sh -c command`). Shell **не обрабатывает сигналы** и передаёт их дочерним процессам.

**Решение: tini**
```dockerfile
# В Dockerfile:
FROM alpine:3.19
RUN apk add --no-cache tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["my-app"]
```

**Решение: dumb-init**
```dockerfile
FROM alpine:3.19
RUN apk add --no-cache dumb-init
ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["my-app"]
```

**В манифесте Kubernetes:**
```yaml
containers:
- name: app
  image: my-app:latest
  command: ["/sbin/tini", "--"]
  args: ["my-app"]
```

**Проверка PID 1:**
```bash
# Проверить, кто является PID 1
kubectl exec <pod-name> -- ps -p 1 -o comm=

# Если PID 1 — sh/bash, значит обработка сигналов нарушена
# Если PID 1 — tini/dumb-init/my-app, всё корректно
```

---

## Взаимодействие с другими компонентами

### Native Sidecar и перезапуск

Native Sidecars (Init-контейнеры с `restartPolicy: Always`, K8s v1.29+ GA) имеют особую логику перезапуска:

- Запускаются **до** основных контейнеров и работают постоянно.
- Если Native Sidecar падает, он перезапускается **только сам** (не влияет на основной контейнер).
- Основной контейнер НЕ перезапускается при падении Native Sidecar.

```yaml
initContainers:
- name: envoy-proxy
  image: envoyproxy/envoy:v1.29
  restartPolicy: Always  # Native Sidecar
containers:
- name: app
  image: my-app:latest
```

> **Подробнее:** [Sidecar Patterns в Kubernetes](./pod_sidecar_patterns.md).

### StartupProbe и перезапуск

`startupProbe` защищает долго запускающиеся приложения от преждевременного перезапуска через `livenessProbe`:

```yaml
containers:
- name: app
  startupProbe:
    httpGet:
      path: /healthz
      port: 8080
    failureThreshold: 30    # 30 × 10s = 5 минут на запуск
    periodSeconds: 10
  livenessProbe:
    httpGet:
      path: /healthz
      port: 8080
    periodSeconds: 10       # Проверяется только после прохождения startupProbe
```

**Логика:**
1. Пока `startupProbe` не пройдена → `livenessProbe` НЕ проверяется → контейнер НЕ перезапускается.
2. После прохождения `startupProbe` → начинает работать `livenessProbe`.
3. Если `startupProbe` не пройдена за `failureThreshold × periodSeconds` → контейнер перезапускается.

> **Подробнее:** [Зонды (Probes) в Kubernetes](./probes.md).

### PodDisruptionBudget (PDB) при перезапусках

PDB **не защищает от перезапусков**, вызванных сбоем приложения. Он защищает от **плановых disruption** (обслуживание узлов, обновления).

| Тип disruption | PDB защищает? | Пример |
| :--- | :--- | :--- |
| Приложение упало → перезапуск | **Нет** | CrashLoopBackOff |
| Обслуживание узла (drain) | **Да** | `kubectl drain node` |
| Обновление Deployment | **Да** | Rolling update |
| OOMKilled (عدم хватка памяти) | **Нет** | Лимиты превышены |
| Eviction (нехватка ресурсов на узле) | **Частично** | Зависит от `unhealthyPodEvictionPolicy` |

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2       # Или maxUnavailable: 1
  selector:
    matchLabels:
      app: my-app
```

---

## Практические сценарии

### Ручной перезапуск без удаления пода

Иногда требуется перезапустить процесс внутри контейнера, сохранив IP и UID пода (например, для сброса кеша или отладки). Прямой команды `kubectl restart container` не существует, но есть обходные пути:

**1. Убийство PID 1 (рекомендуется):**
```bash
kubectl exec <pod_name> -c <container_name> -- /bin/sh -c "kill 1"
```
*Процесс завершится, и kubelet запустит контейнер заново согласно `restartPolicy`.*

**2. Использование сигналов (если приложение игнорирует SIGTERM):**
```bash
kubectl exec <pod_name> -c <container_name> -- /bin/sh -c "kill -9 -1"
```
*Сигнал `-1` отправляется всем процессам в пространстве имен контейнера.*

**3. Удаление Pod с контроллером (пересоздание):**
```bash
kubectl delete pod <pod-name>  # Контроллер создаст новый Pod
```

**4. Rollout restart (для контроллеров):**
```bash
kubectl rollout restart deployment/<name>
kubectl rollout restart statefulset/<name>
kubectl rollout restart daemonset/<name>
```

### kubectl rollout restart — сценарии использования

**Применение 1: Применение нового ConfigMap/Secret (ENV)**
```bash
# ConfigMap обновлён, но Pod использует ENV — нужно перезапустить
kubectl rollout restart deployment/my-app
```

**Применение 2: Обновление образа с фиксированным тегом (не latest)**
```bash
# Образ обновлён в реестре, но Pod использует старый кэш
kubectl set image deployment/my-app app=my-app:v1.31.1
kubectl rollout restart deployment/my-app
```

**Применение 3: Очистка кеша в памяти**
```bash
# Приложение зависло, но не падает — soft restart
kubectl rollout restart deployment/my-app
```

**Применение 4: Применение securityContext или resource limits**
```bash
# Обновлены лимиты ресурсов или security policy
kubectl apply -f updated-manifest.yaml
kubectl rollout restart deployment/my-app
```

### Диагностический workflow для DevOps/SRE

```text
Под перезагружается (restartCount растёт)
     ↓
[1] kubectl describe pod <name>
     ├─ Last State: OOMKilled → [A]
     ├─ Last State: Error (exit 1) → [B]
     ├─ Last State: Error (exit 127) → [C]
     ├─ Last State: Error (exit 137) → [D]
     ├─ Last State: Error (exit 143) → [E]
     ├─ Liveness probe failed → [F]
     └─ Startup probe failed → [G]

[A] OOMKilled:
     ├─ Увеличить limits.memory
     ├─ Проверить потребление: kubectl top pod
     └─ Настроить язык (GOMEMLIMIT, MaxRAMPercentage)

[B] Exit Code 1 (Ошибка приложения):
     ├─ kubectl logs <pod> --previous
     ├─ Проверить переменные окружения
     └─ Проверить ConfigMap/Secret

[C] Exit Code 127 (Команда не найдена):
     ├─ Проверить command/args в манифесте
     ├─ Проверить $PATH в образе
     └─ Убедиться, что бинарный файл существует

[D] Exit Code 137 (SIGKILL):
     ├─ Проверить: OOMKilled или kill -9?
     ├─ Если OOMKilled → [A]
     └─ Если manual kill → проверить PreStop hooks

[E] Exit Code 143 (SIGTERM):
     ├─ Приложение не обрабатывает SIGTERM
     ├─ Проверить PID 1: kubectl exec <pod> -- ps -p 1
     └─ Использовать tini/dumb-init

[F] Liveness probe failed:
     ├─ Проверить эндпоинт: kubectl exec <pod> -- curl localhost:<port>/healthz
     ├─ Увеличить periodSeconds / timeoutSeconds
     └─ Проверить, не блокирует ли приложение health-эндпоинт

[G] Startup probe failed:
     ├─ Увеличить failureThreshold (время на запуск)
     ├─ Увеличить periodSeconds
     └─ Проверить, не зависает ли приложение на этапе инициализации
```

### Диагностические команды

**Анализ причин перезапуска:**
```bash
# Код завершения и причина последнего падения
kubectl get pod <name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'

# Все статусы контейнеров (включая предыдущие)
kubectl get pod <name> -o jsonpath='{.status.containerStatuses[*].state}'

# Подробный JSON статуса
kubectl get pod <name> -o json | jq '.status.containerStatuses[] | {name, restartCount, lastState, state}'
```

**Мониторинг перезапусков в реальном времени:**
```bash
kubectl get pods --watch -o custom-columns="NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount,REASON:.status.containerStatuses[*].lastState.terminated.reason"
```

**Проверка логов предыдущего запуска:**
```bash
kubectl logs <pod-name> --previous
kubectl logs <pod-name> -c <container-name> --previous
```

**Проверка событий:**
```bash
kubectl events --for pod/<pod-name> --watch
kubectl describe pod <pod-name> | grep -A 10 "Events:"
```

**Проверка PID 1:**
```bash
kubectl exec <pod-name> -- ps -p 1 -o pid,comm,args
```

**Проверка termination message:**
```bash
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.message}'
```

---

## Production мониторинг и алертинг

### Метрики для мониторинга

**Prometheus метрики:**
```promql
# Количество перезапусков за последний час
sum(increase(kube_pod_container_status_restarts_total[1h])) by (namespace, pod)

# Поды с перезапусками > 5 за час
kube_pod_container_status_restarts_total > 5

# Процент подов в CrashLoopBackOff
count(kube_pod_status_reason{reason="CrashLoopBackOff"}) / count(kube_pod_status_phase{phase="Running"}) * 100

# Ожидание на узле (Pending)
kube_pod_status_phase{phase="Pending"} > 0
```

**Алерт-правила (PrometheusRule):**
```yaml
groups:
- name: pod-restarts
  rules:
  - alert: PodCrashLooping
    expr: increase(kube_pod_container_status_restarts_total[15m]) > 5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Pod {{ $labels.pod }} перезагружается"
      description: "Pod перезагрузился более 5 раз за 15 минут"

  - alert: PodOOMKilling
    expr: kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Pod {{ $labels.pod }} завершён из-за OOMKilled"
```

### Настройка мониторинга

**Grafana Dashboard (key panels):**
- Рестарты по namespace/pod (table)
- Timeline перезапусков (time series)
- Top Pod'ов по restartCount (bar chart)
- OOMKilled vs Eviction (pie chart)

**ELK/Loki:**
```bash
# Логи перезапусков
kubectl logs <pod> --previous | grep -iE "error|panic|fatal|exception"

# Фильтрация по exit code
kubectl get pods -o json | jq '.items[] | select(.status.containerStatuses[].lastState.terminated.exitCode == 137)'
```

---

## Дополнительная информация

### Анализ уровней сбоя

При расследовании «мигающих» подов следуйте алгоритму:

1. **Проверьте `restartCount`**: Если он растет — проблема внутри контейнера (код, лимиты, пробы).
2. **Проверьте `UID`**: Если он изменился — под пересоздан извне. Ищите причины в событиях (`kubectl get events`): вытеснение (Eviction), проблемы с Node или действия контроллера.
3. **Изучите `terminationMessage`**: Kubernetes сохраняет последние сообщения об ошибках в `/dev/termination-log` (можно переопределить через `spec.containers[*].terminationMessagePath`).

### terminationMessagePath и FallbackToLogsOnError

```yaml
containers:
- name: app
  terminationMessagePolicy: FallbackToLogsOnError  # Если termination-message пуст, берёт из stderr
  terminationMessagePath: /dev/termination-log      # Путь по умолчанию
```

**Политики:**
- `File` (дефолт): Только из файла `terminationMessagePath`.
- `FallbackToLogsOnError`: Если exit code != 0 и termination-message пуст, берёт последние строки stderr.

> **Подробнее:** [Продвинутые темы CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/advanced_topics.md).

### Связанные темы

- [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — фазы, условия, shutdown.
- [Зонды (Probes) в Kubernetes](./probes.md) — Liveness, Readiness, StartupProbe.
- [Sidecar Patterns в Kubernetes](./pod_sidecar_patterns.md) — Ambassador, Adapter, Native Sidecars.
- [Изменение ресурсов без перезапуска (In-Place Resize)](../../Autoscaling/in_place_pod_resize.md) — подробный разбор механизма.
- [Обновление и Rollout ConfigMap](../ConfigMap/update_and_rollout.md) — когда нужен перезапуск при смене конфигов.
- [Диагностика CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md) — разбор цикличных падений.
- [Причины и решения CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/common_cases_and_solutions.md) — 13 типовых кейсов.
- [OOMKilled в контейнерах](../../Troubleshooting/Common_Errors/oomkilled_pods.md) — нехватка памяти и QoS.
