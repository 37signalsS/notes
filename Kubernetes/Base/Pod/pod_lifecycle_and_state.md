# Жизненный цикл и состояния Pod в Kubernetes

## Определения

**Pod Phase (Фаза пода)** — высокоуровневое состояние Pod в кластере, определяемое полем `status.phase`. Отражает общую стадию жизненного цикла объекта с точки зрения оркестрации.

**Pod Conditions (Условия пода)** — массив в `status.conditions`, предоставляющий детализированную информацию о готовности конкретных аспектов Pod (сеть, инициализация, готовность контейнеров).

**Container States (Состояния контейнеров)** — текущий статус каждого контейнера внутри Pod (`Waiting`, `Running`, `Terminated`).

**Graceful Shutdown (Корректное завершение)** — процедура штатной остановки Pod, при которой приложению отправляется сигнал `SIGTERM`, дающий время на сохранение данных и закрытие соединений до принудительного удаления.

**terminationGracePeriodSeconds** — интервал времени (по умолчанию 30с), в течение которого Kubernetes ожидает корректного завершения процессов после отправки `SIGTERM` перед отправкой `SIGKILL`.

**preStop hook** — команда или HTTP-запрос, выполняемый `kubelet` внутри контейнера перед отправкой `SIGTERM`. Используется как «фора» для сети (синхронизация EndpointSlice) и как средство финализации (выход из кворума, отправка дампов).

**postStart hook** — команда или HTTP-запрос, выполняемый `kubelet` сразу после создания контейнера (параллельно с основным процессом). Используется для инициализации среды, регистрации в Service Discovery, прогрева кэшей.

**Readiness Gate (Врата готовности)** — пользовательское условие (custom condition), добавляемое во внешний контроллер и влияющее на общий статус `Ready` Pod. Pod считается готовым только при выполнении **всех** условий: `readinessProbe` + все `readinessGates`.

**Pod Disruption Budget (PDB)** — объект Kubernetes, ограничивающий количество одновременных выселений (evictions) подов одного сервиса при добровольных прерываниях (обновление узлов, drain). Не защищает от принудительных выселений при нехватке ресурсов.

**Voluntary Disruption (Добровольное прерывание)** — операция, инициированная администратором или контроллером (обновление Deployment, drain узла, eviction API). Учитывает PDB.

**Involuntary Disruption (Недобровольное прерывание)** — вынужденное завершение пода из-за аппаратных проблем, нехватки ресурсов (`OOMKilled`, `eviction-hard`), действия `node-pressure`. PDB не учитывается.

---

## Базовые концепции

### Фазы Pod

Фаза является суммарным статусом всех контейнеров и условий пода.

| Фаза | Описание | Типовые причины |
| :--- | :--- | :--- |
| **`Pending`** | Pod принят системой, но инфраструктура не готова. | Планирование (Scheduling), скачивание образов, выполнение Init-контейнеров. |
| **`Running`** | Pod привязан к узлу, запущен основной процесс. | Хотя бы один основной контейнер находится в состоянии `Running` или в процессе старта/перезапуска. |
| **`Succeeded`** | Успешное завершение работы. | Все контейнеры завершились с кодом 0. Характерно для завершенных объектов `Job`. |
| **`Failed`** | Завершение с ошибкой. | По крайней мере один контейнер завершился с кодом != 0 или был убит системой (например, OOM). |
| **`Unknown`** | Состояние не может быть получено. | Потеря связи между API-сервером и `kubelet` на узле. |

### Условия Pod (Conditions)

Позволяют точно локализовать проблему, если Pod «застрял» в одной из фаз.

| Условие | Описание | Актуальность |
| :--- | :--- | :--- |
| `PodScheduled` | Pod назначен на конкретный узел. | Базовое |
| `PodReadyToStartContainers` | Сетевое окружение и sandbox созданы. | **v1.29+ (Beta)** |
| `Initialized` | Все Init-контейнеры успешно завершены. | Базовое |
| `ContainersReady` | Все контейнеры в Pod прошли проверки готовности. | Базовое |
| `Ready` | Pod готов принимать трафик и включен в эндпоинты Service. | Базовое |
| `DisruptionTarget` | Pod будет удален из-за внешнего вмешательства (выселение). | **v1.31 (GA)** |

**Как проверить условия:**
```bash
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[*].type}'
# → PodScheduled Initialized ContainersReady Ready

# Проверка конкретного условия
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → True

# Детализация: почему Pod не Ready
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}'
# → ReadinessGatesNotReady
```

### Состояния контейнеров и диагностика

Каждый контейнер имеет три возможных состояния, содержащих детали в поле `reason`:

1.  **`Waiting`**: Ожидание ресурсов или образов. Частые причины: `ImagePullBackOff`, `CreateContainerConfigError`.
2.  **`Running`**: Процесс запущен. Включает время старта (`startedAt`).
3.  **`Terminated`**: Процесс завершен. Важные поля:
    *   `exitCode`: Код выхода (0 — успех, 137 — OOM/SIGKILL, 143 — SIGTERM).
    *   `terminationMessage`: Сообщение об ошибке. По политике `FallbackToLogsOnError` (v1.31) может автоматически подтягиваться из логов контейнера.

```bash
# Получение точной причины завершения последнего инстанса контейнера
kubectl get pod <pod_name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'

# Просмотр сообщения о завершении (Termination Message)
kubectl get pod <pod_name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.message}'

# Просмотр текущего состояния всех контейнеров
kubectl get pod <pod_name> -o jsonpath='{range .status.containerStatuses[*]}{.name}{"\t"}{.state}{"\n"}{end}'
```

### Политика перезапуска (Restart Policy)

Настраивается через `spec.restartPolicy` и применяется `kubelet` ко всем контейнерам в Pod:
*   **Always** (дефолт): Перезапуск всегда (для Long-running сервисов).
*   **OnFailure**: Перезапуск только при ошибках (для Batch задач).
*   **Never**: Без перезапусков (для отладки).

**Back-off тайминги (для Always и OnFailure):**

| Перезапуск # | Задержка перед стартом |
| :--- | :--- |
| 1 | 10 секунд |
| 2 | 20 секунд |
| 3 | 40 секунд |
| 4 | 80 секунд |
| 5 | 160 секунд |
| 6 | 300 секунд (максимум) |

> **Подробнее:** Цикл перезапусков, Exit Code и CrashLoopBackOff описаны в [Перезапуск Pod в Kubernetes](./pod_restarts.md).

### Жизненный цикл с Native Sidecars (v1.29+, стабилен с v1.33)

Нативные сайдкары (Init-контейнеры с `restartPolicy: Always`) меняют логику старта и остановки:
1.  **Старт**: Основные контейнеры не запустятся, пока все сайдкары не пройдут `startupProbe`.
2.  **Стоп**: Сайдкары останавливаются **после** завершения основных контейнеров (решает проблему «зависших» Job).

> **Подробнее:** [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md).

### Readiness механизм

Pod считается `Ready` и добавляется в эндпоинты Service только при выполнении **всех** условий:
1. Все контейнеры прошли `readinessProbe` (проверяется `kubelet`).
2. Все `readinessGates` установлены во `True` (проверяется внешним контроллером).

**Что происходит при `NotReady`:**
*   Pod **не удаляется** и **не перезапускается**.
*   Pod исключается из `EndpointSlice` — трафик перестает поступать.
*   Если Pod был в `Ready` и перешёл в `NotReady` — трафик перенаправляется на другие реплики.

**Что происходит при `Ready`:**
*   Pod добавляется в `EndpointSlice` — трафик начинает поступать.

**Подробнее о readinessGates:** [Продвинутые темы Pod](./pod_advanced_topics.md#врата-готовности-readiness-gates).

### Жизненный цикл создания Pod

Полный путь от `kubectl apply` до запущенного контейнера:

```
kubectl apply -f pod.yaml
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 1. kube-apiserver                                   │
│    Authn → Authz → Mutating Admission → Validation │
│    Запись в etcd (status.phase = Pending)           │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 2. kube-scheduler                                   │
│    Filtering → Scoring → Назначение nodeName        │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 3. kubelet (на узле)                                │
│    Watch → Синхронизация состояния                  │
│    ↓                                                │
│    3a. CRI: Создание Pod Sandbox (pause container)  │
│    3b. CRI: Сетевая настройка (CNI)                 │
│    3c. CRI: Монтирование Volume'ов                  │
│    3d. Запуск Init-контейнеров (строго по очереди)  │
│    3e. Запуск Native Sidecar'ов (если есть)         │
│    3f. Запуск основных контейнеров                  │
│    3g. Запуск postStart hook                        │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 4. status.update → API → etcd                       │
│    status.phase = Running                           │
└─────────────────────────────────────────────────────┘
```

**Типовые задержки на каждом этапе:**
*   **Этап 1:** Адмиссионные контроллеры (Webhook могут добавить 1-3с).
*   **Этап 2:** Ожидание планирования (от секунд до бесконечности при нехватке ресурсов).
*   **Этап 3b:** CNI плагин выделяет IP (обычно <1с, но Flannel/Calico могут задерживаться).
*   **Этап 3c:** Монтирование PV (NFS/Ceph — от секунд до минут).
*   **Этап 3d:** Init-контейнеры (зависит от логики, может выполняться часы).
*   **Этап 3f:** `imagePull` (取决于 размера образа и сети, от секунд до минут).

**Подробнее:** Жизненный цикл создания и масштабирования описан в [Архитектура Control Plane](../../Concepts/control_plane_architecture.md#жизненный-цикл-создания-пода).

### Жизненный цикл удаления Pod

Полная последовательность при `kubectl delete pod <name>` или при завершении контроллером:

```
kubectl delete pod <name>
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 1. kube-apiserver                                   │
│    Установка deletionTimestamp                      │
│    Запуск admission hooks (pre-delete)              │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 2. Параллельно:                                     │
│    2a. kubelet видит deletionTimestamp              │
│    2b. Контроллер эндпоинтов убирает из EndpointSlice│
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 3. kubelet (быстрая цепочка):                       │
│    3a. Запуск preStop hook (если настроен)          │
│    3b. Отправка SIGTERM PID 1 (основным контейнерам)│
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 4. Контроллер эндпоинтов (медленная цепочка):      │
│    Обновление EndpointSlice → kube-proxy на нодах   │
│    → Ingress контроллеры → Service Mesh             │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 5. Приложение обрабатывает SIGTERM:                 │
│    Завершение текущих запросов                      │
│    Закрытие соединений (Connection: close)          │
│    Сохранение состояния                             │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 6. Ожидание terminationGracePeriodSeconds           │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 7. Если процессы ещё живы:                         │
│    Отправка SIGKILL (принудительное убийство)       │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 8. Завершение Native Sidecar (K8s 1.29+):          │
│    Только после остановки основных контейнеров      │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ 9. kubelet:                                         │
│    Размонтирование Volume'ов                        │
│    Удаление Pod из API                              │
└─────────────────────────────────────────────────────┘
```

**Важно:** PDB проверяется **только** при добровольных прерываниях (eviction API, drain). При `kubectl delete pod` напрямую PDB **не проверяется**.

**Проблема сетевой гонки (Race Condition):** Обновление `EndpointSlice` — глобальная операция (секунды). Отправка `SIGTERM` — локальная (миллисекунды). Если приложение закрывает сокет сразу при `SIGTERM`, трафик продолжает поступать до обновления сети → `502 Bad Gateway`.

**Решение:** `preStop` hook с `sleep 5-15` дает сети время на синхронизацию.

> **Подробнее:** [Graceful Shutdown: Глубокое погружение](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md).

### Завершение работы (Graceful Shutdown)

**Разница между SIGTERM и SIGKILL:**

| Характеристика | SIGTERM (15) | SIGKILL (9) |
|:---|:---|:---|
| **Номер сигнала** | 15 | 9 |
| **Назначение** | Мягкое завершение — приложение может перехватить сигнал и выполнить cleanup | Принудительное убийство — процесс завершается немедленно |
| **Перехватимость** | Да — можно установить обработчик (trap) | Нет — ядро завершает процесс без возможности обработки |
| **Код выхода** | 143 (128 + 15) | 137 (128 + 9) |
| **Когда отправляется K8s** | Первым — при удалении Pod | Только если SIGTERM не сработал за `terminationGracePeriodSeconds` |
| **Применение** | Корректное закершение: закрытие соединений, сохранение данных, освобождение ресурсов | Аварийная остановка: процесс завис, игнорирует SIGTERM, превышен таймаут |

**Последовательность событий при удалении Pod:**
1.  Установка `deletionTimestamp` (статус меняется на `Terminating`).
2.  Параллельное выполнение:
    *   Запуск `preStop` hook (если настроен).
    *   Исключение Pod из списка эндпоинтов Service (перестает получать новый трафик).
3.  Отправка **`SIGTERM`** процессу PID 1 — приложение должно начать корректное завершение.
4.  Ожидание `terminationGracePeriodSeconds` (по умолчанию 30с).
5.  Отправка **`SIGKILL`** принудительно, если процессы еще живы — процесс убивается немедленно.

**Важно:** Kubernetes отправляет только `SIGTERM`. `SIGKILL` отправляется только по истечении таймаута. Это дает приложению время на graceful shutdown.

**Проблемы с PID 1:**
- Если в контейнере PID 1 — это shell-скрипт (например, `bash script.sh`), сигнал SIGTERM может не достичь дочерних процессов.
- Решение: использовать `exec` в скриптах (`exec java -jar app.jar`) или `tini`/`dumb-init` как Entrypoint.

**Рекомендуемые значения `terminationGracePeriodSeconds`:**

| Тип приложения | Рекомендуемое время | Причина |
| :--- | :--- | :--- |
| Stateless API | 30-45с | Быстрое завершение соединений |
| Web-сервер (Nginx) | 30с | preStop hook для graceful shutdown |
| База данных (PostgreSQL) | 60-120с | Финализация транзакций, checkpoint |
| Очередь (Kafka consumer) | 60с | Завершение обработки текущего сообщения |
| Machine Learning inference | 120-300с | Завершение текущего предсказания |

> **Подробнее:** [Graceful Shutdown: Глубокое погружение](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md).

### Voluntary vs Involuntary Disruption

| Характеристика | Voluntary Disruption | Involuntary Disruption |
| :--- | :--- | :--- |
| **Причина** | Обновление Deployment, drain узла, API eviction | OOMKilled, eviction-hard, аппаратный сбой |
| **PDB учитывается** | Да (eviction API проверяет PDB) | Нет (kubelet убивает напрямую) |
| **Порядок выселения** | Приоритет (low → high) | QoS (BestEffort → Burstable → Guaranteed) |
| **Типичный сценарий** | `kubectl drain`, Rolling Update | Node pressure, нехватка памяти/диска |
| **Предсказуемость** | Высокая (администратор контролирует) | Низкая (зависит от состояния узла) |

**Когда PDB НЕ помогает:**
*   `kubectl delete pod <name>` (прямое удаление без eviction API).
*   Involuntary disruption (Hard Eviction, OOMKilled).
*   Node failure (аппаратный сбой узла).

> **Подробнее:** [Pod Disruption Budget](../../Autoscaling/pod_disruption_budget.md), [Выселение Pod](../../Troubleshooting/Common_Errors/PodEvicted/definitions.md).

---

## Практические сценарии

### Пример 1: Настройка корректного завершения

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: graceful-app
spec:
  containers:
  - name: web
    image: nginx:1.27
    lifecycle:
      preStop:
        exec:
          # Даем балансировщику время обновить конфигурацию (обычно 5-10с)
          command: ["/bin/sh", "-c", "sleep 10"]
  terminationGracePeriodSeconds: 60 # Достаточно для закрытия тяжелых соединений
```

### Пример 2: Диагностика причины падения контейнера

```bash
# Получение точной причины завершения последнего инстанса контейнера
kubectl get pod <pod_name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'

# Просмотр сообщения о завершении (Termination Message)
kubectl get pod <pod_name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.message}'
```

### Пример 3: Настройка postStart для инициализации

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-init
spec:
  containers:
  - name: app
    image: my-app:1.0
    lifecycle:
      postStart:
        exec:
          command:
          - /bin/sh
          - -c
          - |
            # Регистрация в Service Discovery (пример для Consul)
            curl -s -X PUT http://consul:8500/v1/agent/service/register \
              -d '{"name":"my-app","port":8080,"tags":["v1"]}'
            # Прогрев кэша или предварительная загрузка данных
            wget -q -O /tmp/cache.json http://cache-server:8080/warmup
      preStop:
        exec:
          command:
          - /bin/sh
          - -c
          - |
            # Отмена регистрации
            curl -s -X PUT http://consul:8500/v1/agent/service/deregister/my-app
            sleep 5
    terminationGracePeriodSeconds: 30
```

### Пример 4: Pod с readinessGate для Ingress Controller

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-app
  labels:
    app: web
spec:
  readinessGates:
  - conditionType: "networking.kubernetes.io/ingress-ready"
  containers:
  - name: app
    image: web-app:1.0
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
```

```bash
# Проверка readinessGates
kubectl get pod web-app -o jsonpath='{.spec.readinessGates}'
# → [{"conditionType":"networking.kubernetes.io/ingress-ready"}]

# Проверка состояния конкретного условия
kubectl get pod web-app -o jsonpath='{.status.conditions[?(@.type=="networking.kubernetes.io/ingress-ready")].status}'
# → False (ожидает внешнего контроллера)
```

---

## Troubleshooting: типичные ошибки жизненного цикла

### Ошибка 1: Pod застрял в Pending

**Причины:**
*   Нет узлов с достаточными ресурсами (CPU/Memory requests не удовлетворяются).
*   Affinity/Anti-Affinity правила не могут быть выполнены.
*   Taints на узлах без соответствующих Tolerations.
*   PVC не может быть provisioned (StorageClass не найден, quota).
*   Scheduling Gates блокируют планирование (внешний контроллер не снял ворота).

**Диагностика:**
```bash
# Быстрая проверка: почему Pod не назначен
kubectl describe pod <pod-name> | grep -A 10 "Events:"

# Проверка Conditions
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[*]}' | jq .

# Проверка Scheduling Gates
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
```

**Подробнее:** [Диагностика Pending](../../Troubleshooting/Common_Errors/pod_pending/diagnostics.md).

### Ошибка 2: Pod застрял в ImagePullBackOff

**Причины:**
*   Образ не существует в реестре (опечатка в имени или теге).
*   Приватный реестр: отсутствует `imagePullSecret`.
*   Сетевые проблемы (DNS не резолвит реестр, firewall).
*   Rate limiting реестра ( Docker Hub).

**Диагностика:**
```bash
# Проверка Events
kubectl describe pod <pod-name> | grep -A 5 "Events:"

# Проверка последней ошибки
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
# → ImagePullBackOff

# Ручное скачивание образа (на узле)
crictl pull <image>:<tag>
```

**Подробнее:** [Ошибки скачивания образов](../../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md).

### Ошибка 3: Pod застрял в ContainerCreating

**Причины:**
*   Монтирование Volume'ов (PVC pending, NFS недоступен).
*   CNI плагин не может выделить IP.
*   Secret/ConfigMap не найдены.
*   SecurityContext конфликтует с политикой узла.

**Диагностика:**
```bash
# Проверка Events
kubectl describe pod <pod-name> | grep -A 10 "Events:"

# Проверка монтирований
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes[*]}'

# Проверка PVC
kubectl get pvc
```

### Ошибка 4: Pod застрял в Terminating

**Причины:**
*   `preStop` hook завис (бесконечный процесс).
*   Приложение игнорирует SIGTERM.
*   Finalizers блокируют удаление.
*   PDB блокирует eviction (при удалении через контроллер).
*   Volume не может быть размонтирован (процесс на узле держит mount).

**Диагностика:**
```bash
# Проверка finalizers
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'

# Проверка, какой процесс держит volume (на узле)
lsof +D /var/lib/kubelet/pods/<pod-uid>/volumes/

# Принудительное удаление (если Pod действительно «мёртв»)
kubectl delete pod <pod-name> --grace-period=0 --force
```

**Подробнее:** [Диагностика PodTerminating](../../Troubleshooting/Common_Errors/PodTerminating/diagnostics.md).

### Ошибка 5: Pod застрял в Init:Error или CrashLoopBackOff на init-контейнере

**Причины:**
*   Init-контейнер завершается с кодом != 0 (некорректная команда, отсутствующий ресурс).
*   Init-контейнер завис (бесконечный процесс).
*   Ресурсы init-контейнера слишком велики (Pod не может получить Enough CPU/Memory).

**Диагностика:**
```bash
# Проверка статуса init-контейнеров
kubectl get pod <pod-name> -o jsonpath='{.status.initContainerStatuses[*].state}'

# Логи init-контейнера
kubectl logs <pod-name> -c <init-container-name>

# Логи init-контейнера с предыдущего запуска
kubectl logs <pod-name> -c <init-container-name> --previous
```

**Подробнее:** [Init-container в Kubernetes](./pod_init_containers.md).

### Ошибка 6: Pod застрял в CrashLoopBackOff

**Причины:**
*   Приложение падает сразу после старта (ошибка конфигурации, отсутствующий файл).
*   LivenessProbe не проходит (приложение не отвечает).
*   OOMKill (не хватает памяти).
*   Приложение завершается с кодом != 0.

**Диагностика:**
```bash
# Проверка Exit Code
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}'
# → 137 (OOMKill/SIGKILL), 1 (ошибка приложения)

# Проверка reason
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
# → OOMKilled, Error, Completed

# Логи (последний успешный запуск)
kubectl logs <pod-name> --previous
```

**Подробнее:** [Диагностика CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md).

### Ошибка 7: Pod застрял в CreateContainerConfigError

**Причины:**
*   Secret или ConfigMap не найден (опечатка в имени).
*   SecurityContext ссылается на несуществующий SecurityContextConstraint.
*   ServiceAccount не найден.
*   Volume ссылается на несуществующий PV/PVC.

**Диагностика:**
```bash
# Проверка Events
kubectl describe pod <pod-name> | grep -A 5 "Events:"
# → Error: CreateContainerConfigError: secrets "my-secret" not found

# Проверка Secret'ов
kubectl get secrets

# Проверка ConfigMap'ов
kubectl get configmaps
```

**Подробнее:** [CreateContainerConfigError](../../Troubleshooting/Common_Errors/CreateContainerConfigError/definitions.md).

---

## Best Practices

1. **Указывайте `terminationGracePeriodSeconds`** явно для каждого Deployment. Не полагайтесь на дефолт (30с) — для БД может потребоваться 60-120с.
2. **Используйте `preStop` hook** для синхронизации сети: `sleep 5-15` перед `SIGTERM` предотвращает `502 Bad Gateway`.
3. **Настройте `readinessProbe`** для каждого сервисного контейнера — это единственное, что определяет, принимает ли Pod трафик.
4. **Используйте `startupProbe`** для медленно стартующих приложений (Java, ML inference) — это защищает от преждевременного `livenessProbe` перезапуска.
5. **Не используйте `postStart`** для тяжелых операций — хук выполняется параллельно с основным процессом и может увеличить время старта.
6. **Включайте `preStop` hook** в каждый Production Deployment — это критично для zero-downtime обновлений.
7. **Настройте PDB** для критических сервисов: `minAvailable: 1` или `maxUnavailable: 1` гарантирует доступность при обслуживании узлов.
8. **Используйте `tini` или `dumb-init`** как PID 1 в контейнерах — это решает проблему проброса сигналов.
9. **Избегайте `kubectl delete pod`** напрямую в Production — используйте `kubectl scale --replicas=0` или eviction API (через `kubectl drain`).
10. **Включайте `shareProcessNamespace: true`** при необходимости мониторинга или отладки процессов в sidecar-контейнерах.

---

## Связанные темы

* [Обзор Pod в Kubernetes](./pod_overview.md) — архитектура и ресурсы.
* [Перезапуск Pod в Kubernetes](./pod_restarts.md) — детальный разбор Restart Policy и Back-off.
* [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md) — работа нативных сайдкаров.
* [Init-container в Kubernetes](./pod_init_containers.md) — особенности фазы инициализации.
* [Пробы в Kubernetes (Probes)](../probes.md) — влияние проб на условие `Ready`.
* [Graceful Shutdown: Глубокое погружение](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — отладка проблем остановки.
* [Диагностика Pending](../../Troubleshooting/Common_Errors/pod_pending/diagnostics.md) — пошаговые алгоритмы поиска причин.
* [CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md) — разбор цикличных падений.
* [Ошибки скачивания образов](../../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md) — ErrImagePull и ImagePullBackOff.
* [Pod Disruption Budget](../../Autoscaling/pod_disruption_budget.md) — ограничение выселений.
