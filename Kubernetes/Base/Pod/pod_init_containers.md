# Init-контейнеры в Kubernetes

**Актуально для:** Kubernetes 1.30–1.35

## Определения

* **Init-container (Инициализирующий контейнер)** — специализированный контейнер в спецификации Pod (`spec.initContainers`), который запускается и обязан успешно завершиться с кодом возврата `0` до момента старта основных рабочих контейнеров приложения. Предназначен для выполнения подготовительных процедур: проверки сетевой доступности зависимостей, генерации конфигураций, миграции схем баз данных и настройки прав на дисковых томах.
* **Native Sidecar (Нативный сайдкар)** — механизм Kubernetes (alpha в v1.28, beta в v1.29, стабилен с v1.33; KEP-3839), позволяющий определять долгоживущие вспомогательные контейнеры внутри блока `spec.initContainers` с директивой `restartPolicy: Always`. В отличие от обычных init-контейнеров, нативный сайдкар не завершает работу, а запускается перед основными контейнерами и продолжает функционировать параллельно с ними в течение всего жизненного цикла Pod.
* **Идемпотентность (Idempotency)** — фундаментальное свойство операции, гарантирующее, что многократное ее повторение приводит к точно такому же результату, как и однократное, без возникновения побочных эффектов или повреждения данных. Все сценарии init-контейнеров обязаны быть идемпотентными, так как Kubelet перезапускает контейнер при любых сбоях, эвикциях или рестартах Pod на узле.
* **activeDeadlineSeconds** — параметр спецификации Pod (`spec.activeDeadlineSeconds`), задающий жесткий лимит времени (в секундах) на нахождение Pod в активном состоянии с момента его фактического запуска на узле. Лимит распространяется на все фазы, включая суммарное время работы всех init-контейнеров. При превышении тайм-аута Kubelet принудительно завершает Pod с причиной `DeadlineExceeded`.
* **restartPolicy (для Init-контейнеров)** — параметр контейнера, управляющий реакцией Kubelet на его остановку. Для классических init-контейнеров допустимы значения `OnFailure` (перезапуск только при коде возврата отличным от `0`, поведение по умолчанию) и `Never` (любой сбой контейнера приводит к аварийному завершению всего Pod). Для нативных сайдкаров используется значение `Always`.
* **InitContainerStatuses** — массив объектов в статусе Pod (`status.initContainerStatuses`), отражающий текущее и историческое состояние каждого init-контейнера: дескрипторы состояния (`running`, `terminated`, `waiting`), причину завершения (`reason`), код возврата (`exitCode`), счетчик перезапусков (`restartCount`) и флаг готовности (`ready`).
* **Pod Sandbox** — инфраструктурный контейнер (традиционно `pause`), создаваемый контейнерным рантаймом (containerd, CRI-O) по запросу Kubelet. Sandbox резервирует и удерживает общие пространства имен ядра Linux (Network, IPC, UTS), внутри которых последовательно запускаются init-контейнеры и параллельно стартуют основные контейнеры.
* **Эффективные ресурсы (Effective Requests / Limits)** — расчетные значения вычислительных ресурсов (CPU, Memory), используемые планировщиком `kube-scheduler` для размещения Pod на узлах и демоном `kubelet` для настройки cgroups и определения класса качества обслуживания (QoS). Вычисляются как максимум между наивысшим требованием отдельного init-контейнера и суммой требований основных контейнеров (с учетом постоянно запущенных нативных сайдкаров).

---

## Базовые концепции и архитектура

### Назначение и сценарии использования в инфраструктуре

Разделение процесса инициализации и исполнения бизнес-логики — ключевой принцип архитектуры контейнеризации в DevOps и системном администрировании. Перенос задач подготовки среды в init-контейнеры изолирует утилиты обслуживания от runtime-окружения приложения, снижая вектор атак и объем образов.

| Сценарий | Назначение и специфика | Типовые инструменты / образы |
| :--- | :--- | :--- |
| **Ожидание зависимостей** | Блокировка запуска приложения до готовности СУБД, очередей сообщений или внутренних микросервисов (TCP/HTTP health checks). | `busybox:1.36`, `alpine:3.20`, `curlimages/curl:8.10.1` |
| **Управление правами на томах** | Рекурсивная смена владельца (`chown`) и прав доступа (`chmod`) на монтируемых томах (`emptyDir`, PVC) под UID не-root пользователя. | `busybox:1.36`, `alpine:3.20` |
| **Миграции баз данных** | Применение DDL/DML миграций до запуска экземпляров приложения, предотвращая race conditions при параллельном старте нескольких реплик. | Образ приложения с CLI мигратора (Flyway, Liquibase, Django) |
| **Шаблонизация конфигураций** | Сборка единого конфигурационного файла из нескольких Secret, ConfigMap и параметров ядра через утилиты `envsubst`, `sed` или `jinja`. | `alpine:3.20`, специализированные утилитарные образы |
| **Сетевая инициализация ядра** | Настройка правил сетевой фильтрации `iptables`/`nftables` или параметров `sysctl` в общем Network Namespace Pod без выдачи привилегий основному приложению. | Образы с `iptables`, `iproute2` и capability `NET_ADMIN` |
| **Предварительный прогрев кэша** | Скачивание статических бинарных артефактов, словарей, гео-баз или исходного кода в общий том до приема первого запроса. | `alpine:3.20`, `bitnami/git:2.47` |
| **Валидация окружения** | Проверка валидности сертификатов x509, наличия обязательных переменных окружения и доступности внешних хранилищ конфигураций. | `curlimages/curl:8.10.1`, `busybox:1.36` |

---

### Архитектура и взаимодействие с Kubelet и CRI

Init-контейнеры управляются демоном `kubelet` через интерфейс взаимодействия с контейнерными средами CRI (Container Runtime Interface, например `containerd` или `CRI-O`). Они исполняются внутри того же Pod Sandbox, что и основные контейнеры, разделяя сетевой стек и локальные дисковые тома.

```
+-------------------------------------------------------------------------------------------------------+
| Kubernetes Worker Node (Linux Kernel)                                                                 |
|                                                                                                       |
|  +-------------------------------------------------------------------------------------------------+  |
|  | Pod Sandbox (pause)                                                                             |  |
|  | Namespaces: netns (IP: 10.244.1.45, lo: 127.0.0.1), ipcns, utsns                                |  |
|  | Volumes: /shared-data (emptyDir: mode 0777 / fsGroup), /secrets (Secret: read-only)             |  |
|  |                                                                                                 |  |
|  |  [Фаза 1: Обычный Init]          [Фаза 2: Native Sidecar]           [Фаза 3: Основное приложение]|  |
|  |  +--------------------------+    +-----------------------------+    +--------------------------+ |  |
|  |  | init-setup (busybox)     |    | log-shipper (vector/fluent) |    | web-app (nginx/go)       | |  |
|  |  | 1. chown /shared-data    |    | restartPolicy: Always       |    | 1. Читает /shared-data   | |  |
|  |  | 2. wait-for TCP:5432     |    | startupProbe: HTTP /health  |    | 2. Слушает :8080         | |  |
|  |  | 3. EXIT CODE 0           |    | Работает весь цикл Pod      |    | Работает весь цикл Pod   | |  |
|  |  +--------------------------+    +-----------------------------+    +--------------------------+ |  |
|  |               |                                 ^                                ^              |  |
|  |               | (Успешное завершение)           | (Переход в Ready)              |              |  |
|  |               +---------------------------------+--------------------------------+              |  |
|  +-------------------------------------------------------------------------------------------------+  |
|                                                  ^                                                    |
|                                                  | gRPC (RunPodSandbox / CreateContainer / Start)     |
|  +-----------------------------------------------+-------------------------------------------------+  |
|  | Kubelet Sync Loop (Pod Worker)                                                                  |  |
|  | - Синхронизирует spec.initContainers строго последовательно (индекс [0] -> [1] -> ...)         |  |
|  | - Блокирует запуск spec.containers до завершения всех Init (и прохождения startupProbe Sidecar)|  |
|  | - Вычисляет эффективные cgroup-лимиты Pod: max(init_limits, sum(app_limits + sidecar_limits))   |  |
|  +-------------------------------------------------------------------------------------------------+  |
+-------------------------------------------------------------------------------------------------------+
```

---

### Порядок выполнения и жизненный цикл

1. **Создание сетевой и дисковой инфраструктуры:** Kubelet запрашивает у CRI создание Pod Sandbox, подключает CNI-плагин (выделение IP-адреса и сетевого интерфейса) и монтирует объявленные в спецификации Pod тома (`emptyDir`, `ConfigMap`, `Secret`, `PersistentVolumeClaim`).
2. **Последовательный запуск (Sequential Execution):** Kubelet обходит массив `spec.initContainers` строго по порядку индексов: от `0` до `N-1`. Следующий контейнер в очереди не начнет создание, пока предыдущий не завершится со статусом `Terminated` и кодом возврата `0`.
3. **Обработка сбоев и Exponential Backoff:**
   * Если init-контейнер завершился с ненулевым кодом выхода, Kubelet руководствуется политикой перезапуска Pod (`spec.restartPolicy`).
   * По умолчанию (`restartPolicy: Always` или `OnFailure`) Kubelet перезапускает упавший контейнер. Для предотвращения перегрузки ноды интервал между перезапусками удваивается по алгоритму экспоненциальной задержки: 10с → 20с → 40с → 80с → 160с → максимум 300с (5 минут).
   * Если для Pod задано `restartPolicy: Never`, то падение любого init-контейнера немедленно переводит весь Pod в терминальный статус `Failed`.
4. **Запуск основного приложения:** Только после успешного завершения абсолютно всех стандартных init-контейнеров Kubelet переходит к блоку `spec.containers`. Все контейнеры основного приложения запускаются **параллельно**.
5. **Влияние `activeDeadlineSeconds`:** Таймер дедлайна начинает отсчет в момент старта Pod Sandbox. Если init-контейнеры выполняют длительную миграцию данных или бесконечно ждут упавшую базу данных и суммарное время превышает `activeDeadlineSeconds`, Kubelet отправляет сигнал `SIGKILL` всем процессам и помечает Pod как `Failed`.

---

### Мутируемость полей спецификации

В Kubernetes спецификация запущенного Pod является практически неизменяемой (immutable). Однако поле `spec.initContainers[*].image` входит в строго ограниченный перечень исключений (наряду с `spec.containers[*].image`, `spec.activeDeadlineSeconds`, `spec.tolerations`):

* **Если init-контейнеры уже успешно завершились (код 0):** изменение образа `spec.initContainers[*].image` через `kubectl patch` или API будет успешно сохранено в etcd, но **не приведет к повторному запуску init-контейнера**. Kubelet не перезапускает завершенные контейнеры в уже работающем Pod.
* **Если init-контейнер находится в сбое (`CrashLoopBackOff`):** изменение образа применится Kubelet на следующей итерации перезапуска, что позволяет устранять ошибки опечатки в теге или битые образы "на лету" без удаления объекта Pod.
* **Продакшн-стандарт:** Для планового обновления логики инициализации всегда используется управляемый перезапуск контроллера (`kubectl rollout restart deployment/<name>`), гарантирующий создание нового Pod с полным циклом инициализации.

---

### Взаимодействие с Native Sidecars

Начиная с Kubernetes 1.29 (Beta) и 1.33 (GA), контейнеры, определенные в блоке `spec.initContainers` со свойством `restartPolicy: Always`, обрабатываются рантаймом по специальным правилам:

1. **Порядок запуска:** Native Sidecar стартует в порядке своей очереди среди init-контейнеров. Однако, в отличие от обычного init, он не завершает работу.
2. **Критерий перехода к следующим контейнерам:** Kubelet переходит к запуску следующего init-контейнера (или основных контейнеров) только после того, как Native Sidecar переходит в состояние **Ready**. Состояние Ready определяется успешным прохождением проверок `startupProbe` (или `readinessProbe`, если startup не задана). Если проба не настроена, готовность фиксируется сразу после успешного вызова `StartContainer`.
3. **Изоляция сбоев:** Падение нативного сайдкара в процессе работы Pod приводит к его индивидуальному перезапуску рантаймом без прерывания работы основных контейнеров приложения.
4. **Специфика Graceful Shutdown:** При удалении Pod Kubelet останавливает контейнеры в обратном порядке:
   * Сначала сигнал `SIGTERM` отправляется основным контейнерам (`spec.containers`).
   * Нативные сайдкары продолжают работать, пока все основные контейнеры полностью не завершатся.
   * Только после этого Kubelet посылает `SIGTERM` нативным сайдкарам. Это предотвращает распространенную проблему, когда прокси-сервер (Envoy) или лог-агент завершался раньше приложения, приводя к обрыву сессий и потере завершающих логов.

Подробный разбор архитектурных шаблонов: [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md).

---

### Взаимодействие с пространствами имен Linux и дисковой подсистемой

С точки зрения ядра Linux системный администратор должен учитывать следующие особенности выполнения init-процессов:

* **Сетевой стек (Network Namespace):** Init-контейнеры работают в общем сетевом пространстве Pod. Они имеют общий IP-адрес, общую таблицу маршрутизации и разделяют loopback-интерфейс `127.0.0.1`. Порт, открытый нативным сайдкаром на `127.0.0.1`, доступен последующим init-контейнерам и основному приложению.
* **Файловая система и монтирование томов:** Файловые системы образов контейнеров полностью изолированы (разные rootfs). Передача файлов и директорий между init-контейнерами и приложением возможна **только через смонтированные тома** (обычно `emptyDir` в памяти или на диске узла).
* **Права доступа и UID/GID (POSIX Permissions):** По умолчанию директория тома `emptyDir` создается на хосте с правами `0777` и владельцем `root:root` (UID/GID `0:0`). Если основное приложение работает под непривилегированным пользователем (например, `runAsUser: 10001`), попытка записи в созданные init-контейнером файлы завершится ошибкой `Permission Denied`, если init-контейнер запускался от root и не настроил права (`chmod`/`chown`), либо если на уровне Pod не задан параметр `spec.securityContext.fsGroup`.

---

### Сравнение типов контейнеров в спецификации Pod

| Характеристика | Обычный Init-container | Native Sidecar | Контейнер приложения | Ephemeral Container |
| :--- | :--- | :--- | :--- | :--- |
| **Расположение в API** | `spec.initContainers[]` | `spec.initContainers[]` | `spec.containers[]` | `spec.ephemeralContainers[]` |
| **Параметр `restartPolicy`** | `OnFailure` или `Never` | Строго `Always` | Наследует политику Pod | Не поддерживается |
| **Порядок запуска** | Строго последовательный | В очереди init-контейнеров | Параллельно после всех init | Динамически через `kubectl debug` |
| **Условие продолжения** | Завершение с Exit Code 0 | Прохождение `startupProbe` | Не блокирует другие app-контейнеры | Не влияет на жизненный цикл |
| **Время жизни** | До завершения задачи | Весь жизненный цикл Pod | Весь жизненный цикл Pod | До завершения команды/отладки |
| **Порядок остановки** | Завершен до старта app | **После** основных контейнеров | Первыми при получении SIGTERM | Остановка по завершению процесса |
| **Поддержка Probes** | Запрещены | `startupProbe`, `readinessProbe` | Все: startup, readiness, liveness | Запрещены |
| **Lifecycle hooks** | Запрещены | Запрещены | `postStart`, `preStop` | Запрещены |
| **Влияние на QoS** | Участвует в расчете | Участвует (суммируется) | Участвует (суммируется) | Не влияет на QoS и ресурсы |

---

### Алгоритм расчета ресурсов (Requests и Limits) и влияние на QoS

Планировщик `kube-scheduler` и агент `kubelet` используют специальный алгоритм вычисления эффективного потребления ресурсов Pod, учитывая, что классические init-контейнеры никогда не работают одновременно друг с другом, но нативные сайдкары работают параллельно с приложением.

#### Формула расчета эффективных запросов (Effective Requests)

1. Для каждого ресурса (CPU, Memory) вычисляется суммарный запрос постоянно работающих компонентов:
   $$\text{SumAppRequests} = \sum \text{spec.containers[*].requests} + \sum \text{spec.initContainers[sidecars].requests}$$

2. Для каждого обычного init-контейнера $I_k$ учитываются его собственные запросы плюс запросы всех нативных сайдкаров $S$, запущенных до него или одновременно с ним:
   $$\text{PhaseRequest}(I_k) = \text{requests}(I_k) + \sum_{j \le k, S_j \in \text{sidecars}} \text{requests}(S_j)$$

3. Итоговый эффективный запрос Pod (учитывается планировщиком при поиске ноды):
   $$\text{EffectiveRequest} = \max \left( \max_k(\text{PhaseRequest}(I_k)), \text{SumAppRequests} \right) + \text{PodOverhead}$$

#### Архитектурная ловушка емкости (Capacity Gotcha)
Если для вспомогательного init-контейнера распаковки архива задать `resources.requests.cpu: "4"` и `memory: "8Gi"`, планировщик будет искать рабочий узел, имеющий минимум 4 свободных ядра и 8 Гигабайт памяти, даже если основному сервису требуется всего `100m` CPU и `256Mi` RAM. Pod зависнет в статусе `Pending` при отсутствии крупных свободных нод.

#### Деградация класса качества обслуживания (QoS Class)
Класс качества обслуживания всего Pod (`Guaranteed`, `Burstable`, `BestEffort`) определяется с учетом **всех** контейнеров, включая `initContainers`:
* Чтобы Pod получил наивысший класс **Guaranteed**, для **каждого** основного контейнера И для **каждого** init-контейнера должны быть строго заданы `requests` и `limits`, причем `requests` обязаны быть в точности равны `limits`.
* Если хотя бы один init-контейнер не имеет лимитов или его лимиты превышают запросы, весь Pod получает класс **Burstable**, что делает его кандидатом на принудительную эвикцию (OOM eviction) операционной системой при дефиците памяти на узле!

Подробнее о механизмах резервирования: [Управление ресурсами (QoS)](../../Scheduling/qos_limit_and_requests.md).

---

## Практические сценарии и конфигурация

### Сценарий 1: Ожидание внешних сервисов с таймаутом и Backoff

Классическая антипаттерн-ошибка — использование бесконечного цикла `while true; do nc -z ...; sleep 1; done`. При сбое сетевой инфраструктуры Pod зависает навсегда, потребляя ресурсы и скрывая проблему от системы мониторинга.

Правильная реализация включает счетчик попыток, экспоненциальную задержку и явное логирование:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: resilient-service-waiter
  namespace: production
  labels:
    app.kubernetes.io/name: order-processor
spec:
  restartPolicy: OnFailure
  initContainers:
  - name: wait-for-postgres
    image: busybox:1.36.1
    command: ['sh', '-c']
    args:
    - |
      set -eu
      TARGET_HOST="postgres-cluster.database.svc.cluster.local"
      TARGET_PORT="5432"
      MAX_RETRIES=30
      RETRY_INTERVAL=2

      echo "[INIT] Checking TCP connectivity to ${TARGET_HOST}:${TARGET_PORT}..."
      COUNT=0
      until nc -z -w 3 "${TARGET_HOST}" "${TARGET_PORT}"; do
        COUNT=$((COUNT + 1))
        if [ "${COUNT}" -ge "${MAX_RETRIES}" ]; then
          echo "[ERROR] Timeout waiting for database after ${MAX_RETRIES} attempts. Terminating." >&2
          exit 1
        fi
        echo "[INIT] Database unavailable (attempt ${COUNT}/${MAX_RETRIES}). Retrying in ${RETRY_INTERVAL}s..."
        sleep "${RETRY_INTERVAL}"
      done
      echo "[INIT] Successfully connected to database."
    resources:
      requests:
        cpu: "10m"
        memory: "16Mi"
      limits:
        cpu: "50m"
        memory: "32Mi"
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      runAsUser: 65534
      capabilities:
        drop: ["ALL"]
  containers:
  - name: app
    image: nginx:1.27-alpine
    ports:
    - containerPort: 80
    resources:
      requests:
        cpu: "100m"
        memory: "128Mi"
      limits:
        cpu: "200m"
        memory: "256Mi"
```

**Верификация состояния запуска:**
```bash
kubectl get pod resilient-service-waiter -n production
# → NAME                       READY   STATUS     RESTARTS   AGE
#   resilient-service-waiter   0/1     Init:0/1   0          8s

# Просмотр логов процесса инициализации в реальном времени:
kubectl logs resilient-service-waiter -n production -c wait-for-postgres -f
# → [INIT] Checking TCP connectivity to postgres-cluster.database.svc.cluster.local:5432...
#   [INIT] Database unavailable (attempt 1/30). Retrying in 2s...
#   [INIT] Successfully connected to database.

# Итоговое состояние после успешного завершения init:
kubectl get pod resilient-service-waiter -n production
# → NAME                       READY   STATUS    RESTARTS   AGE
#   resilient-service-waiter   1/1     Running   0          25s
```

---

### Сценарий 2: Миграция схемы базы данных перед стартом

Выполнение миграций непосредственно в init-контейнере предотвращает работу старого кода приложения с новой схемой и гарантирует атомарный переход до открытия сетевых портов приложения.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: backend-migrator
  namespace: default
spec:
  restartPolicy: OnFailure
  initContainers:
  - name: run-db-migrations
    image: python:3.12-slim
    command: ["/bin/sh", "-c"]
    args:
    - |
      set -euo pipefail
      echo "[MIGRATE] Running Django migrations..."
      python manage.py migrate --no-input
      echo "[MIGRATE] Migrations applied successfully."
    env:
    - name: DB_HOST
      value: "pg-pooler.internal"
    - name: DB_PASSWORD
      valueFrom:
        secretKeyRef:
          name: app-db-credentials
          key: password
    resources:
      requests:
        cpu: "100m"
        memory: "256Mi"
      limits:
        cpu: "500m"
        memory: "512Mi"
    securityContext:
      allowPrivilegeEscalation: false
      runAsNonRoot: true
      runAsUser: 1000
  containers:
  - name: web-api
    image: my-registry.local/web-api:v2.4.0
    command: ["gunicorn", "-b", "0.0.0.0:8000", "core.wsgi"]
    resources:
      requests:
        cpu: "200m"
        memory: "256Mi"
      limits:
        cpu: "1000m"
        memory: "1Gi"
```

---

### Сценарий 3: Подготовка прав на томах (Volume Permissions / chown Fixer)

Когда приложение запускается в строгом соответствии с PSS Restricted (`runAsNonRoot: true`, UID `10001`), а том PVC смонтирован с правами root, приложение падает с ошибкой `Permission Denied`. Вспомогательный init-контейнер решает эту проблему без предоставления постоянных прав root основному сервису:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secured-storage-pod
  namespace: app-space
spec:
  volumes:
  - name: persistent-storage
    emptyDir: {}
  initContainers:
  - name: volume-permissions-fixer
    image: busybox:1.36.1
    command: ["sh", "-c"]
    args:
    - |
      set -eu
      echo "[PERM] Adjusting ownership of /mnt/data to UID 10001:10001..."
      chown -R 10001:10001 /mnt/data
      chmod 700 /mnt/data
      echo "[PERM] Storage permissions successfully set."
    volumeMounts:
    - name: persistent-storage
      mountPath: /mnt/data
    securityContext:
      runAsUser: 0
      capabilities:
        add: ["CHOWN", "FOWNER"]
        drop: ["ALL"]
    resources:
      requests:
        cpu: "10m"
        memory: "16Mi"
      limits:
        cpu: "50m"
        memory: "32Mi"
  containers:
  - name: secured-app
    image: alpine:3.20
    command: ["sh", "-c", "echo 'Storage operational' > /mnt/data/status.log && sleep 3600"]
    volumeMounts:
    - name: persistent-storage
      mountPath: /mnt/data
    securityContext:
      runAsNonRoot: true
      runAsUser: 10001
      runAsGroup: 10001
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
    resources:
      requests:
        cpu: "50m"
        memory: "64Mi"
```

**Проверка прав внутри тома после запуска:**
```bash
kubectl exec secured-storage-pod -n app-space -c secured-app -- ls -ld /mnt/data
# → drwx------    2 10001    10001         4096 Oct 17 14:30 /mnt/data

kubectl exec secured-storage-pod -n app-space -c secured-app -- cat /mnt/data/status.log
# → Storage operational
```

---

### Сценарий 4: Настройка сетевого стека и параметров ядра (CAP_NET_ADMIN / sysctl)

Инициализирующий контейнер может конфигурировать правила `iptables` в пространстве имен Pod (например, для прозрачного перенаправления исходящего трафика на локальный порт sidecar-прокси), не требуя повышенных привилегий у основного контейнера.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: net-init-pod
  namespace: networking-test
spec:
  initContainers:
  - name: init-iptables
    image: alpine:3.20
    command: ["sh", "-c"]
    args:
    - |
      set -eu
      apk add --no-cache iptables
      echo "[NET] Configuring port redirection via iptables in Pod netns..."
      # Перенаправляем исходящий TCP трафик на порт локального прокси 15001
      iptables -t nat -A OUTPUT -p tcp --dport 80 -j REDIRECT --to-ports 15001
      echo "[NET] Network rules applied."
    securityContext:
      capabilities:
        add: ["NET_ADMIN"]
        drop: ["ALL"]
      allowPrivilegeEscalation: false
    resources:
      requests:
        cpu: "20m"
        memory: "32Mi"
      limits:
        cpu: "100m"
        memory: "64Mi"
  containers:
  - name: unprivileged-app
    image: curlimages/curl:8.10.1
    command: ["sleep", "3600"]
    securityContext:
      runAsNonRoot: true
      runAsUser: 1000
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
```

---

### Сценарий 5: Динамическая шаблонизация конфигурации из Secret/ConfigMap

Часто конфигурационному файлу приложения (Nginx, HAProxy) требуются подстановки IP-адреса Pod, динамических параметров и секретов, недопустимых для сохранения в открытых ConfigMap. Init-контейнер генерирует файл на временный том `emptyDir`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: config-generator-pod
  namespace: default
spec:
  volumes:
  - name: config-template
    configMap:
      name: nginx-template-cm
  - name: generated-config
    emptyDir: {}
  initContainers:
  - name: template-renderer
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    args:
    - |
      set -eu
      echo "[RENDER] Generating production configuration..."
      # Подстановка переменных окружения в шаблон конфига
      sed -e "s|__POD_IP__|${POD_IP}|g" \
          -e "s|__BACKEND_TOKEN__|${API_SECRET}|g" \
          /etc/templates/nginx.conf.tmpl > /etc/nginx-rendered/nginx.conf
      echo "[RENDER] File /etc/nginx-rendered/nginx.conf successfully written."
    env:
    - name: POD_IP
      valueFrom:
        fieldRef:
          fieldPath: status.podIP
    - name: API_SECRET
      valueFrom:
        secretKeyRef:
          name: backend-auth
          key: token
    volumeMounts:
    - name: config-template
      mountPath: /etc/templates
      readOnly: true
    - name: generated-config
      mountPath: /etc/nginx-rendered
    resources:
      requests:
        cpu: "10m"
        memory: "16Mi"
      limits:
        cpu: "50m"
        memory: "32Mi"
  containers:
  - name: web-server
    image: nginx:1.27-alpine
    volumeMounts:
    - name: generated-config
      mountPath: /etc/nginx/conf.d
      readOnly: true
    ports:
    - containerPort: 80
```

---

## Операции и команды

### Диагностика состояний жизненного цикла в kubectl

На различных этапах жизненного цикла Pod поле `STATUS` вывода утилиты `kubectl` принимает информативные значения, отражающие ход инициализации:

| Статус Pod | Физический смысл | Действия системного администратора |
| :--- | :--- | :--- |
| **`Init:0/N`** | Выполняется первый из `N` объявленных init-контейнеров. | Проверить логи: `kubectl logs <pod> -c <init-0>`. |
| **`Init:M/N`** | `M` контейнеров завершились успешно; в данный момент работает контейнер с индексом `M`. | Инспектировать текущий контейнер `M+1` по имени из `spec.initContainers`. |
| **`Init:Error`** | Init-контейнер завершился с кодом, отличным от `0`. | Смотреть вывод stderr: `kubectl logs <pod> -c <failed-init>`. |
| **`Init:CrashLoopBackOff`** | Неоднократный сбой init-контейнера; Kubelet ожидает экспоненциальный тайм-аут. | Проверить логи предыдущего падения: `kubectl logs <pod> -c <init> --previous`. |
| **`Init:ImagePullBackOff`** | Невозможно загрузить образ init-контейнера (опечатка, неверный secret, сбой registry). | Проверить секцию `Events` в `kubectl describe pod <pod>`. |
| **`PodInitializing`** | Все обычные init-контейнеры завершились; Kubelet создает основные контейнеры. | Штатное переходное состояние. Если зависает — проверить запуск основных образов и монтирование PVC. |

---

### Набор команд траблшутинга (CLI Cheatsheet)

```bash
# 1. Просмотр логов конкретного init-контейнера
kubectl logs <pod-name> -c <init-container-name> -n <namespace>

# 2. Просмотр логов упавшего init-контейнера из предыдущего запуска (при CrashLoopBackOff)
kubectl logs <pod-name> -c <init-container-name> --previous -n <namespace>

# 3. Инспекция событий жизненного цикла (ошибки планирования, вызовы CRI, pull образов)
kubectl describe pod <pod-name> -n <namespace> | grep -A 20 "Events:"

# 4. Получение точного кода возврата (Exit Code) и причины завершения каждого init-контейнера
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{range .status.initContainerStatuses[*]}{.name}{"\tState: "}{.state}{"\tExitCode: "}{.state.terminated.exitCode}{"\tReason: "}{.state.terminated.reason}{"\n"}{end}'
# → wait-db    State: {"terminated":{"exitCode":0,"reason":"Completed"}}    ExitCode: 0    Reason: Completed
#   migrator   State: {"terminated":{"exitCode":1,"reason":"Error"}}        ExitCode: 1    Reason: Error

# 5. Проверка количества перезапусков (restartCount) по каждому init-контейнеру
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{range .status.initContainerStatuses[*]}{.name}{": "}{.restartCount}{" restarts\n"}{end}'

# 6. Список образов, используемых во всех init-контейнерах пода
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.initContainers[*].image}'

# 7. Поиск всех подов в кластере, зависших на стадии выполнения init-контейнеров
kubectl get pods -A --field-selector=status.phase=Pending -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,INIT_STATUS:.status.initContainerStatuses[*].state.waiting.reason' | grep -E "CrashLoopBackOff|ErrImagePull|ImagePullBackOff"

# 8. Инспекция фактических cgroup-ресурсов init-контейнеров
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{range .spec.initContainers[*]}{.name}{"\tRequests: "}{.resources.requests}{"\tLimits: "}{.resources.limits}{"\n"}{end}'
```

---

## Troubleshooting: типичные ошибки и решения

### Ошибка 1: Init-контейнер зависает в бесконечном ожидании (Wait forever / DeadlineExceeded)

**Симптомы:** Pod часами находится в статусе `Init:0/1`, либо завершается с ошибкой `DeadlineExceeded`.
```
Warning  DeadlineExceeded  Pod was active longer than specified deadline
```
**Причина:** Недоступность целевого сервиса (опечатка в DNS-имени Kubernetes Service, закрытый сетевой порт, блокировка NetworkPolicy). В скрипте `until` или `curl` отсутствует верхний лимит повторов или сетевой таймаут.
**Диагностика:**
```bash
# Проверка сетевой связности через эфемерный отладочный контейнер в пространстве имен Pod:
kubectl debug -it <pod-name> --image=busybox:1.36.1 --target=<init-name> -- nc -zv <target-service> <port>
```
**Решение:**
1. Обязательно вводить счетчик максимального числа итераций (например, `MAX_RETRIES=30`) и завершать скрипт с кодом `exit 1` при превышении лимита.
2. Проверить правила `NetworkPolicy`, разрешающие egress-трафик из namespace Pod к целевой базе данных.

---

### Ошибка 2: CrashLoopBackOff init-контейнера из-за отсутствующих утилит

**Симптомы:** Статус `Init:CrashLoopBackOff`. В логах контейнера сообщение:
```
sh: nc: not found
```
или
```
/bin/sh: line 1: curl: command not found
```
**Причина:** Использование минималистичных образов (например, `alpine:3.20` без установленных пакетов или distroless) при вызове отсутствующих системных бинарников в командах `command`/`args`.
**Решение:**
Использовать образы, содержащие требуемые утилиты "из коробки" (`busybox:1.36.1` для `nc`/`wget`/`sh`, либо `curlimages/curl:8.10.1` для вызовов HTTP API), либо явно устанавливать пакеты первой командой скрипта (`apk add --no-cache curl`).

---

### Ошибка 3: OOMKilled init-контейнера при распаковке или миграции

**Симптомы:** Статус `Init:OOMKilled` или код возврата `137` в выводе статуса.
```bash
kubectl get pod <pod-name> -o jsonpath='{.status.initContainerStatuses[*].state.terminated.reason}'
# → OOMKilled
```
**Причина:** Потребление оперативной памяти процессом (например, распаковка zip/tar архива в память, тяжелый компилятор TypeScript или запуск JVM) превысило порог `resources.limits.memory`.
**Решение:**
1. Выделить достаточный объем памяти в `resources.limits.memory` для этапа инициализации. Поскольку обычные init-контейнеры завершают работу до старта приложения, их память освобождается и возвращается операционной системе узла (в cgroup приложения).
2. Заменять буферизацию в памяти потоковой обработкой данных: `curl -sL https://... | tar -xz -C /data` вместо предварительного скачивания всего файла на диск.

---

### Ошибка 4: Невозможность записи в том (Read-only file system или Permission Denied)

**Симптомы:** Init-контейнер завершается с ошибкой:
```
sh: can't create /mnt/data/config.json: Permission denied
```
или
```
touch: /data/test.tmp: Read-only file system
```
**Причина:**
1. В секции `volumeMounts` ошибочно указан флаг `readOnly: true`.
2. Попытка записи в смонтированный `ConfigMap` или `Secret` — данные типы томов всегда монтируются ядром Linux в режиме `read-only`.
3. Том смонтирован с правами пользователя root (`0:0`), а init-контейнер выполняется под непривилегированным пользователем без прав на директорию.
**Решение:**
1. Для формирования динамических конфигов использовать промежуточный том `emptyDir: {}`, скопировав туда данные из `ConfigMap` и модифицируя их там.
2. Проверить `volumeMounts[*].readOnly`.
3. Задать `pod.spec.securityContext.fsGroup: <gid>` — Kubelet автоматически назначит группу-владельца на смонтированные тома при инициализации Pod.

---

### Ошибка 5: Неправильное использование `restartPolicy`

**Симптомы:** Манифест Pod отклоняется API-сервером на стадии валидации:
```
Error from server (Invalid): Pod "test-pod" is invalid: spec.initContainers[0].restartPolicy: Unsupported value: "Always": supported values: "OnFailure", "Never"
```
или нативный сайдкар не перезапускается при аварийном завершении.
**Причина:** Директива `restartPolicy: Always` внутри блока `initContainers` допустима только тогда, когда включен механизм Native Sidecars (стандарт в Kubernetes 1.29+). В устаревших версиях K8s или для обычных init-контейнеров допустимы только `OnFailure` и `Never`.
**Решение:**
Для стандартных однократных задач инициализации использовать `restartPolicy: OnFailure` (или не указывать поле — значение применится по умолчанию). Значение `Always` указывать исключительно для долгоживущих фоновых процессов логирования или прокси.

---

### Ошибка 6: Зависание Pod в статусе `Pending` из-за завышенных запросов ресурсов

**Симптомы:** Pod не планируется ни на одну ноду кластера. Вывод команды `kubectl describe pod <name>` показывает:
```
Events:
  Type     Reason            Age   From               Message
  Warning  FailedScheduling  12s   default-scheduler  0/10 nodes are available: 10 Insufficient cpu, 10 Insufficient memory.
```
**Причина:** В одном из init-контейнеров указаны неоправданно высокие `resources.requests` (например, скопированные из манифеста тяжелой Job). Планировщик суммирует требования по формуле `max(initRequests, sum(appRequests))` и не может найти ноду с требуемым объемом аллоцируемых ресурсов.
**Решение:**
Скорректировать `resources.requests` у init-контейнеров, приведя их в соответствие с реальным потреблением утилит `sh`, `curl` или `nc` (обычно не более `10m`-`50m` CPU и `16Mi`-`64Mi` RAM).

---

### Ошибка 7: Неожиданная деградация QoS-класса Pod (Guaranteed → Burstable)

**Симптомы:** Высоконагруженный Pod, для основных контейнеров которого заданы строгие равные `requests` и `limits`, неожиданно получает статус:
```bash
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'
# → Burstable
```
В результате при возникновении нехватки памяти на ноде Linux OOM-killer завершает данный Pod вместо Pod'ов с классом `Burstable`.
**Причина:** В одном из вспомогательных init-контейнеров (например, `wait-db`) лимиты не были указаны вовсе, либо `limits.cpu != requests.cpu`.
**Решение:**
Для сохранения класса **Guaranteed** спецификация каждого `initContainers` обязана содержать явные и эквивалентные значения:
```yaml
resources:
  requests:
    cpu: "20m"
    memory: "32Mi"
  limits:
    cpu: "20m"
    memory: "32Mi"
```

---

### Ошибка 8: Взаимная блокировка (Deadlock) с Native Sidecar

**Симптомы:** Init-контейнер зависает, ожидая доступности локального порта (например, mTLS-прокси на `127.0.0.1:15001`), но сайдкар не запускается.
**Причина:** Неверный порядок объявления в массиве `spec.initContainers`. Если контейнер ожидания объявлен с индексом `0`, а Native Sidecar (прокси) объявлен с индексом `1`, Kubelet не запустит сайдкар до полного завершения контейнера с индексом `0`. Возникает циклическая блокировка.
**Решение:**
Native Sidecar, предоставляющий сетевые или инфраструктурные сервисы другим компонентам Pod, **обязан объявляться первым** в списке `spec.initContainers`:
```yaml
spec:
  initContainers:
  - name: network-proxy        # Native Sidecar: стартует первым
    image: envoy:v1.31
    restartPolicy: Always
    startupProbe:
      httpGet:
        port: 15021
        path: /healthz/ready
  - name: wait-for-upstream    # Init Container: стартует вторым, когда прокси уже Ready
    image: busybox:1.36.1
    command: ["sh", "-c", "until nc -z 127.0.0.1 15001; do sleep 1; done"]
```

---

### Ошибка 9: Блокировка контроллером Pod Security Standards (PSS Restricted)

**Симптомы:** Создание Pod блокируется admission-вебхуком:
```
Error from server (Forbidden): pods "insecure-pod" is forbidden: violates PodSecurity "restricted:latest":
allowPrivilegeEscalation != false, unrestricted capabilities, runAsNonRoot != true
```
**Причина:** Init-контейнер использует базовый образ (например, чистый `busybox` или `ubuntu`), сконфигурированный на запуск от пользователя root (UID 0), без явного определения блока `securityContext`.
**Решение:**
Явно определить `securityContext` для каждого init-контейнера в строгом соответствии с профилем Restricted:
```yaml
securityContext:
  allowPrivilegeEscalation: false
  runAsNonRoot: true
  runAsUser: 65534
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
```

---

### Ошибка 10: Переполнение локального диска ноды (DiskPressure) через `emptyDir`

**Симптомы:** Нода переходит в состояние `DiskPressure`, а Pod завершается с причиной `Evicted`.
**Причина:** Init-контейнер скачивает тяжелые артефакты, логи или дистрибутивы в том `emptyDir` без ограничения размера, заполняя системный раздел диска хоста (`/var/lib/kubelet`).
**Решение:**
Всегда задавать лимиты на временное хранилище (`ephemeral-storage`) для Pod и использовать ограничение `sizeLimit` на томах `emptyDir`:
```yaml
volumes:
- name: cache-vol
  emptyDir:
    sizeLimit: 1Gi
initContainers:
- name: asset-downloader
  resources:
    limits:
      ephemeral-storage: "1Gi"
```

---

## Best Practices для Production (DevOps / SRE / Sysadmin)

### Стандарты безопасности (Security Hardening)
1. **Принцип наименьших привилегий (Least Privilege):** Не запускайте init-контейнеры от пользователя root, если задача не требует изменения системных дескрипторов. Используйте непривилегированные UID (`runAsNonRoot: true`, `runAsUser: 65534`).
2. **Сброс Capabilities ядра:** Всегда отключайте стандартный набор привилегий Linux через `securityContext.capabilities.drop: ["ALL"]`. Если контейнеру требуется смена прав на томе, точечно добавляйте только `CHOWN` и `FOWNER`. Для сетевых манипуляций — только `NET_ADMIN`.
3. **Защита корневой файловой системы:** Устанавливайте `readOnlyRootFilesystem: true`. Все промежуточные данные и скрипты должны размещаться на явно смонтированных временных томах `emptyDir`.
4. **Безопасное хранение секретов:** Никогда не передавайте учетные данные в строке аргументов `command` или открытых переменных `env`. Используйте ссылки на Secret через `secretKeyRef` или монтирование томов с проекцией (`projected volumes`).

### Управление ресурсами и планирование (Capacity Planning)
1. **Соблюдение баланса QoS:** Если для Pod критичен класс обслуживания `Guaranteed`, убедитесь, что все init-контейнеры имеют жестко заданные `requests == limits` по CPU и Memory.
2. **Ограничение Ephemeral Storage:** Задавайте `ephemeral-storage` requests и limits для init-контейнеров, оперирующих файлами и архивами, чтобы защитить рабочий узел от неконтролируемого исчерпания дискового пространства.
3. **Минималистичные Requests:** Не завышайте CPU/Memory requests init-контейнеров. Оценивайте пиковое потребление процесса и не резервируйте ядра, которые будут простаивать после завершения инициализации.

### Идемпотентность и надежность скриптов
1. **Строгий режим оболочки:** В любых inline-скриптах оболочки (`sh`, `bash`) первой строкой объявляйте `set -euo pipefail`. Это гарантирует немедленное прерывание выполнения при возникновении ошибки в любом звене конвейера и обращении к неинициализированным переменным.
2. **Атомарность файловых операций:** При генерации конфигураций сначала создавайте временный файл (например, `config.tmp`), а затем выполняйте атомарное перемещение `mv config.tmp config.conf`. Это исключит чтение неполных конфигураций основным приложением при внезапном рестарте.
3. **Ограничение циклов ожидания:** Запрещено использовать бесконечные циклы ожидания. Любая проверка связности должна иметь ограничение по числу попыток (`MAX_RETRIES`), явный таймаут на операцию (`nc -w 3`, `curl --max-time 5`) и информативное логирование в stderr при сбое.

### Эксплуатация, логирование и мониторинг
1. **Структурированный вывод логов:** Скрипты инициализации должны выводить понятные префиксы (`[INIT]`, `[ERROR]`, `[SUCCESS]`) с указанием хостов, портов и статуса операций. Это сокращает MTTR (Mean Time to Resolution) инцидентов дежурными инженерами.
2. **Минимизация сторонних зависимостей:** Избегайте команд `apt update` или `apk add` в рантайме внутри init-контейнера. Сбой внешнего репозитория пакетов или сетевой изоляции кластера приведет к отказу всего сервиса. Все утилиты должны быть впечены в базовый образ на этапе CI/CD сборки.

---

## Дополнительная информация

### Связанные темы в базе знаний

* [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md) — детальный разбор реализации и жизненного цикла Native Sidecars (KEP-3839).
* [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — последовательность переходов фаз Pod, условия контейнеров и сигналы завершения.
* [Продвинутые темы Pod](./pod_advanced_topics.md) — мутируемые поля спецификации, Scheduling Gates и Pod Overhead.
* [Эфемерные контейнеры](./ephemeral_containers.md) — интерактивная отладка и профилирование упавших контейнеров без перезапуска Pod.
* [Управление ресурсами (QoS)](../../Scheduling/qos_limit_and_requests.md) — формулы расчета лимитов, алгоритмы планировщика и классы обслуживания.
* [Перезапуск Pod в Kubernetes](./pod_restarts.md) — обработка сбоев, restartPolicy и логика Exponential Backoff в Kubelet.
* [Диагностика ошибок ImagePull](../../Troubleshooting/Common_Errors/PodImagePullErrors/init_container_image_pulls.md) — решение проблем с загрузкой образов init-контейнеров.
