# Жизненный цикл и состояния Pod в Kubernetes

**Актуально для:** Kubernetes 1.30+

---

## Определения

**Pod Phase (Фаза пода)** — строковое высокоуровневое состояние Pod в кластере, возвращаемое в поле `status.phase`. Представляет собой агрегированную оценку состояния оркестрации: `Pending`, `Running`, `Succeeded`, `Failed`, `Unknown`.

**Pod Conditions (Условия пода)** — массив объектов в `status.conditions`, детально описывающий готовность конкретных подсистем Pod: планирования (`PodScheduled`), сетевого и файлового окружения (`PodReadyToStartContainers`), завершения инициализации (`Initialized`), готовности контейнеров (`ContainersReady`), готовности к обслуживанию трафика (`Ready`) и статуса выселения (`DisruptionTarget`).

**Container States (Состояния контейнеров)** — дискретный статус каждого отдельного контейнера внутри Pod, отслеживаемый в `status.containerStatuses[*].state`: `Waiting`, `Running` или `Terminated`.

**Graceful Shutdown (Корректное завершение)** — процедура управляемой остановки процессов Pod, при которой контейнерам передается сигнал мягкого завершения (`SIGTERM` или объявленный `STOPSIGNAL`), предоставляя приложению время закрыть сетевые сокеты, завершить транзакции и сбросить буферы до отправки принудительного сигнала `SIGKILL`.

**terminationGracePeriodSeconds** — параметр спецификации Pod (`spec.terminationGracePeriodSeconds`, по умолчанию 30 секунд), определяющий предельное время ожидания завершения процессов контейнера после отправки `SIGTERM` до момента отправки `SIGKILL`.

**preStop hook** — синхронный блокирующий вызов (команда `exec` или HTTP-запрос `httpGet`), выполняемый `kubelet` непосредственно внутри контейнера перед отправкой сигнала `SIGTERM`. Используется для сетевой конвергенции (задержка перед завершением) и финализации состояния приложения.

**postStart hook** — асинхронный вызов (`exec` или `httpGet`), инициируемый `kubelet` сразу после запроса на создание контейнера в рантайме. Выполняется параллельно с основным процессом контейнера; не гарантирует выполнение до `ENTRYPOINT`.

**Readiness Gate (Врата готовности)** — механизм расширения оценки готовности Pod (`spec.readinessGates`), позволяющий внешним контроллерам (Ingress-контроллеры, Service Mesh, операторы балансировки) внедрять пользовательские условия в `status.conditions`. Pod не получает статус `Ready`, пока все условия из `readinessGates` не перейдут в `True`.

**Pod Disruption Budget (PDB)** — ресурс Kubernetes (`policy/v1`), задающий минимально допустимое количество доступных реплик (`minAvailable`) или максимальное число недоступных реплик (`maxUnavailable`) при добровольных прерываниях (Voluntary Disruptions).

**Voluntary Disruption (Добровольное прерывание)** — плановое удаление или перезапуск Pod, инициированное оператором или автоматикой кластера (выполнение `kubectl drain`, обновление Deployment, изменение DaemonSet, вызов Eviction API). Подчиняется ограничениям PDB.

**Involuntary Disruption (Недобровольное прерывание)** — внезапная остановка или падение Pod, вызванное сбоями инфраструктуры: аппаратный отказ узла, kernel panic, нехватка памяти узла (`OOMKilled`), эвикция по исчерпанию ресурсов (`node-pressure eviction`). Не ограничивается PDB.

**Stop Signal (Сигнал остановки)** — POSIX-сигнал, отправляемый рантаймом контейнеров процессу с PID 1 при остановке. По умолчанию `SIGTERM` (15), переопределяется инструкцией `STOPSIGNAL` в образе или полем `lifecycle.stopSignal` в спецификации контейнера.

---

## Архитектура и базовые концепции

### Фазы Pod (Pod Phase)

Фаза дает общую сводку о текущем состоянии Pod в кластерной модели данных. Она не отражает полный граф состояний контейнеров, а служит агрегированным маркером для управляющих контроллеров.

```
                   ┌──────────────┐
                   │   Pending    │
                   └──────┬───────┘
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
     ┌──────────────┐            ┌──────────────┐
     │   Running    │            │    Failed    │
     └──────┬───────┘            └──────────────┘
            │                           ▲
     ┌──────┴───────┐                   │
     ▼              ▼                   │
┌──────────────┐ ┌──────────────────────┘
│  Succeeded   │ │ (Ошибки контейнеров / OOM /
└──────────────┘ │  RestartPolicy: Never)
```

| Фаза | Описание | Типовые технические причины |
| :--- | :--- | :--- |
| **`Pending`** | Pod принят API-сервером, но один или несколько контейнеров еще не созданы и не запущены. | Ожидание планирования планировщиком (Scheduling), блокировка Scheduling Gates, скачивание образов (ImagePull), создание sandbox-окружения CNI, монтирование томов CSI. |
| **`Running`** | Pod привязан к узлу, sandbox создан, все тома смонтированы, и хотя бы один контейнер запущен, стартует или перезапускается. | Приложение выполняет рабочий цикл, либо один из контейнеров находится в цикле перезапуска при живых остальных. |
| **`Succeeded`** | Все контейнеры в Pod успешно завершили работу с кодом `0` и больше не будут перезапущены. | Завершение пакетных задач `Job` или однократных скриптов с политикой `restartPolicy: OnFailure` или `Never`. |
| **`Failed`** | Все контейнеры в Pod завершили работу, при этом хотя бы один контейнер завершился с ненулевым кодом выхода либо был принудительно убит системой. | Падение процесса приложения, аварийное завершение `OOMKilled` (код 137), эвикция узла с политикой `restartPolicy: Never`. |
| **`Unknown`** | Статус Pod не может быть получен API-сервером. | Потеря сетевой связности между Control Plane и агентом `kubelet` на узле (Node NotReady). |

> **Важно:** Поле `STATUS` в выводе команды `kubectl get pods` не является эквивалентом `status.phase`. `kubectl` синтезирует значение `STATUS` на основе состояний контейнеров (`CrashLoopBackOff`, `ContainerCreating`, `ImagePullBackOff`, `Terminating`, `OOMKilled`), чтобы упростить восприятие оператором.

### Условия Pod (Pod Conditions)

Массив `status.conditions` фиксирует прохождение Pod через критические контрольные точки жизненного цикла.

| Условие (Type) | Семантика `status: "True"` | Значение при `status: "False"` |
| :--- | :--- | :--- |
| **`PodScheduled`** | Pod успешно назначен планировщиком `kube-scheduler` на конкретный рабочий узел. | Недостаточно ресурсов (CPU/RAM), несовместимость taints/tolerations, правила nodeSelector/affinity не удовлетворены. |
| **`PodReadyToStartContainers`** | Сетевой sandbox настроен (CNI выделил IP), тома смонтированы, Pod готов к скачиванию образов и запуску контейнеров. | Ошибка CNI-плагина, сбой создания сетевого пространства имен, таймаут монтирования PV через CSI-драйвер. |
| **`Initialized`** | Все Init-контейнеры из `spec.initContainers` успешно выполнились с кодом 0. | Init-контейнер аварийно упал (`Init:Error`), завис или находится в `Init:CrashLoopBackOff`. |
| **`ContainersReady`** | Все основные контейнеры Pod прошли проверки `readinessProbe` и находятся в состоянии готовности. | Хотя бы один контейнер не прошел `readinessProbe` либо находится в состоянии `CrashLoopBackOff`. |
| **`Ready`** | Pod полностью готов обрабатывать сетевой трафик и включен в балансировочные списки `EndpointSlice` сервисов. | `ContainersReady: False` ЛИБО хотя бы один из внешних шлюзов `spec.readinessGates` находится в состоянии `False`. |
| **`DisruptionTarget`** | Pod выбран для выселения или удаления в результате прерывания (eviction, preemption, taint-eviction). | Штатная работа без активных запросов на выселение. |

**Структура объекта Condition в API:**
```yaml
type: Ready
status: "False"
lastProbeTime: null
lastTransitionTime: "2026-10-17T14:20:10Z"
reason: "ContainersNotReady"
message: "containers with unready status: [web-backend]"
```

**Диагностика условий через `kubectl`:**
```bash
# Просмотр всех условий Pod
kubectl get pod web-backend-78d594b5f8-2k19b -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.reason}{"\n"}{end}'
# → PodScheduled	True	
# → PodReadyToStartContainers	True	
# → Initialized	True	
# → ContainersReady	False	ContainersNotReady
# → Ready	False	ContainersNotReady

# Точечная проверка готовности с извлечением причины
kubectl get pod web-backend-78d594b5f8-2k19b -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}'
# → ContainersNotReady
```

---

### Состояния контейнеров и коды завершения (Exit Codes)

Каждый контейнер внутри Pod последовательно проходит через состояния `Waiting` → `Running` → `Terminated`. Детализация фиксируется в `status.containerStatuses[*]`.

```bash
# Получение полного снимка состояний всех контейнеров в Pod
kubectl get pod web-app -o jsonpath='{range .status.containerStatuses[*]}{.name}{"\tState: "}{.state.*.reason}{"\tRestarts: "}{.restartCount}{"\n"}{end}'
# → nginx	State: Running	Restarts: 0
# → log-shipper	State: CrashLoopBackOff	Restarts: 4
```

#### Классификация состояний

1. **`Waiting`** — контейнер не запущен, выполняются подготовительные операции.
   - `ContainerCreating` — рантайм настраивает cgroups, монтирует ConfigMap/Secret/тома, конфигурирует сеть.
   - `ImagePullBackOff` / `ErrImagePull` — образ не найден, ошибка аутентификации в Registry, превышен сетевой таймаут.
   - `CrashLoopBackOff` — контейнер упал после старта, `kubelet` выдерживает штрафную паузу перед перезапуском.
   - `CreateContainerConfigError` — не найдены Secret или ConfigMap, объявленные в `envFrom` или `volumes`.

2. **`Running`** — процесс успешно передан операционной системе и выполняется. Поле `startedAt` фиксирует метку времени старта. Если настроен `postStart`, он запускается параллельно с основным процессом.

3. **`Terminated`** — процесс остановился. Секция содержит `exitCode`, метки `startedAt`/`finishedAt`, а также `reason` и `message`.

#### Анализ кодов завершения (Exit Codes)

Код выхода процесса является первичным маркером диагностики для SRE и системных администраторов:

| Exit Code | Исходный сигнал / Ошибка | Первопричина и контекст |
| :--- | :--- | :--- |
| **`0`** | `SUCCESS` | Штатное завершение работы процесса (типично для завершившихся Job). |
| **`1`** | `Application Error` | Неперехваченная ошибка приложения, сбой конфигурации, синтаксическая ошибка в коде. |
| **`126`** | `Command Invoked Cannot Execute` | Файл команды найден, но не имеет прав на исполнение (`chmod +x`), либо несовместима архитектура ELF (ARM64 vs AMD64). |
| **`127`** | `File / Command Not Found` | Исполняемый файл не найден по указанному пути или отсутствует в переменной окружения `$PATH`. |
| **`128`** | `Invalid Exit Argument` | Приложение вызвало `exit` с недопустимым кодом аргумента (за пределами диапазона 0-255). |
| **`137`** | `128 + 9 (SIGKILL)` | Процесс принудительно убит ядром или рантаймом. 1) **OOMKilled** (превышение `limits.memory`). 2) Принудительное завершение по истечении `terminationGracePeriodSeconds`. |
| **`139`** | `128 + 11 (SIGSEGV)` | Ошибка сегментации (Segmentation Fault): попытка обращения к недопустимой области памяти в бинарном коде. |
| **`143`** | `128 + 15 (SIGTERM)` | Приложение получило сигнал мягкого завершения и корректно остановило свой цикл выполнения. |

```bash
# Диагностика последнего завершения контейнера (lastState)
kubectl get pod web-backend -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}'
# → 137

kubectl get pod web-backend -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
# → OOMKilled
```

#### Политика сохранения диагностических сообщений (terminationMessagePolicy)

По умолчанию `kubelet` считывает сообщение об ошибке остановки из файла `/dev/termination-log` (`terminationMessagePolicy: File`). Для сервисов, пишущих ошибки только в stdout/stderr, рекомендуется задавать:

```yaml
spec:
  containers:
  - name: backend
    image: registry.example.com/backend:v1.4.2
    terminationMessagePath: /dev/termination-log
    terminationMessagePolicy: FallbackToLogsOnError
```

При значении `FallbackToLogsOnError` в случае падения контейнера с ненулевым кодом и при пустом файле `/dev/termination-log`, `kubelet` автоматически скопирует последние строки консольного вывода (хвост лога) в `status.containerStatuses[*].state.terminated.message`.

---

### Политика перезапуска (Restart Policy) и Back-off логика

Политика перезапуска задается на уровне Pod через `spec.restartPolicy`:
- **`Always`** (дефолт для Pod и Deployment/StatefulSet/DaemonSet): контейнер перезапускается при любом коде завершения.
- **`OnFailure`** (режим для пакетных задач Job): перезапуск происходит только при ненулевом коде завершения или SIGKILL/OOM.
- **`Never`**: автоматический перезапуск `kubelet` отключен; упавший контейнер остается в фазе `Failed`.

#### Механизм экспоненциальной задержки (CrashLoopBackOff)

Когда контейнер падает неоднократно, `kubelet` применяет экспоненциальную задержку перед следующим перезапуском, чтобы не перегружать CPU узла, сокет контейнерного рантайма и подсистему логирования:

$$\text{Delay}_n = \min(10 \cdot 2^{n-1}, 300)\quad \text{секунд}$$

Последовательность интервалов ожидания:
1. 1-е падение: немедленный перезапуск (задержка 0с или 10с в зависимости от рантайма).
2. 2-е падение: 10 секунд.
3. 3-е падение: 20 секунд.
4. 4-е падение: 40 секунд.
5. 5-е падение: 80 секунд.
6. 6-е падение: 160 секунд.
7. 7-е и последующие падения: 300 секунд (максимальный потолок — 5 минут).

**Сброс счетчика Back-off:** Если контейнер после старта успешно проработал непрерывно **10 минут (600 секунд)**, внутренний таймер `kubelet` сбрасывается. При последующем падении задержка снова начнется с минимальных 10 секунд.

**Управление Back-off в конфигурации узла (KubeletConfiguration):**
В K8s 1.35+ (Beta, фича `KubeletCrashLoopBackOffMax`) системный администратор может скорректировать потолок задержки в конфигурационном файле `/var/lib/kubelet/config.yaml`:
```yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
crashLoopBackOff:
  maxContainerRestartPeriod: "60s"
```

---

### Взаимодействие жизненного цикла с пробами (Startup, Liveness, Readiness)

Пробы выполняются демоном `kubelet` на узле через сетевые сокеты или системные вызовы в namespaces контейнера:

```
[Старт контейнера]
       │
       ▼
[startupProbe активна?] ─── Да ───► [startupProbe выполняет проверки]
       │                                     │
      Нет                                    ├── Не прошла ──► [Рестарт контейнера]
       │                                     ▼
       │                              [Прошла успешно]
       ├─────────────────────────────────────┘
       ▼
Параллельный запуск постоянных проверок:
 ┌──────────────────────────────────────┬─────────────────────────────────────┐
 ▼                                      ▼                                     ▼
[livenessProbe]                        [readinessProbe]                 [Контейнерный процесс]
 │                                      │
 ├── Не прошла (failureThreshold)       ├── Не прошла
 │    │                                 │    │
 │    ▼                                 │    ▼
 │   [Убийство и перезапуск             │   [Удаление IP из EndpointSlice;]
 │    по restartPolicy]                 │   [ContainersReady: False;      ]
 │                                      │   [Ready: False;                ]
 │                                      │   [Контейнер НЕ перезапускается!]
 │                                      │
 └── Прошла успешно                     └── Прошла успешно
      │                                      │
      ▼                                      ▼
     [Контейнер продолжает работу]          [Добавление IP в EndpointSlice;]
                                            [Ready: True]
```

1. **`startupProbe` (Защита медленного старта):**
   - Отключает выполнение `livenessProbe` и `readinessProbe` до тех пор, пока сама не вернет `Success`.
   - Если исчерпан лимит `failureThreshold * periodSeconds`, контейнер принудительно убивается и перезапускается в соответствии с `restartPolicy`.
   - Защищает тяжелые сервисы (Java Virtual Machine, базы данных с долгой фазой восстановления WAL) от ложных срабатываний `livenessProbe`.

2. **`livenessProbe` (Детектор зависаний и Deadlock):**
   - Проверяет жизнеспособность процесса на протяжении всего жизненного цикла.
   - При превышении порога ошибок (`failureThreshold`) `kubelet` убивает контейнер и запускает процедуру его перезапуска.
   - **Не устраняет** внешние зависимости (сбой внешней БД не должен приводить к падению Liveness, иначе возникнет каскадный рестарт всех реплик).

3. **`readinessProbe` (Детектор готовности к нагрузке):**
   - Определяет, готов ли Pod принимать трафик от `Service`.
   - При сбое пробы `kubelet` выставляет условие `ContainersReady: False`, а контроллер `endpointslice-controller` исключает адрес Pod из всех `EndpointSlice`.
   - **Контейнер НЕ перезапускается.** Процесс продолжает функционировать, получая возможность восстановить соединения или разгрузить локальные очереди.

---

### Жизненный цикл с Native Sidecars (K8s 1.33 GA)

Начиная с Kubernetes 1.33 механизм нативных сайдкаров (SidecarContainers) переведен в статус GA. Сайдкар определяется как контейнер в секции `initContainers` с параметром `restartPolicy: Always`.

```yaml
spec:
  initContainers:
  - name: vault-agent
    image: hashicorp/vault:1.18.0
    restartPolicy: Always
    startupProbe:
      httpGet:
        path: /v1/sys/health
        port: 8200
      periodSeconds: 2
```

**Особенности жизненного цикла Native Sidecar:**
1. **Порядок старта:**
   - Init-контейнеры запускаются строго последовательно в порядке объявления.
   - Если в списке встречается Native Sidecar (`restartPolicy: Always`), `kubelet` ждет успешного запуска sidecar-контейнера. Если для него настроена `startupProbe`, переход к следующему init-контейнеру или основным контейнерам происходит **только после успешного прохождения startupProbe сайдкара**.
2. **Время работы:**
   - После старта Native Sidecar продолжает работать параллельно с основными контейнерами на протяжении всего жизненного цикла Pod.
3. **Порядок завершения при остановке Pod:**
   - При удалении Pod `kubelet` сначала останавливает **все основные контейнеры** приложения (`spec.containers`).
   - Native Sidecar контейнеры продолжают работать, позволяя приложению сбрасывать логи, передавать метрики или закрывать mTLS-сессии.
   - После полной остановки основных контейнеров `kubelet` останавливает sidecar-контейнеры в **обратном порядке** относительно их объявления в `spec.initContainers`.

---

### Архитектура создания Pod (От API к рантайму)

```
[Пользователь / CI] ── kubectl apply -f pod.yaml
        │
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 1. kube-apiserver                                                      │
│    - Аутентификация (x509 / Bearer Token)                              │
│    - Авторизация (RBAC / Node)                                         │
│    - Mutating Webhooks (внедрение sidecar, изменение ресурсов)         │
│    - Schema Validation (проверка схемы OpenAPI)                        │
│    - Validating Webhooks / ValidatingAdmissionPolicy                   │
│    - Запись спецификации в etcd (status.phase = Pending)               │
└────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. kube-scheduler                                                      │
│    - Filtering / Predicates (отсев неподходящих узлов по CPU/RAM/Toler)│
│    - Scoring / Priorities (ранжирование узлов, Spread constraints)     │
│    - Binding: запись spec.nodeName в API-сервер                        │
└────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. kubelet (на назначенном узле)                                       │
│    - PLEG (Pod Lifecycle Event Generator) видит событие                │
│    - Вызов CRI: RunPodSandbox (создание pause-контейнера, namespaces)  │
│    - Вызов CNI: плагин выделяет IP, настраивает veth-пару и шлюзы      │
│    - status.conditions: PodReadyToStartContainers = True               │
│    - Вызов CSI / VolumeManager: монтирование ConfigMap, Secret, PVC    │
│    - Запуск Init-контейнеров (строго последовательно, код 0)           │
│    - status.conditions: Initialized = True                             │
│    - Запуск Native Sidecars (ожидание прохождения startupProbe)        │
│    - Запуск основных контейнеров (вызов CRI CreateContainer/Start)     │
│    - Исполнение lifecycle.postStart (асинхронно с entrypoint)          │
│    - Мониторинг проб (startup -> liveness & readiness)                 │
└────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. Обновление статуса в API                                            │
│    - status.phase = Running                                            │
│    - status.conditions: ContainersReady = True, Ready = True           │
│    - endpointslice-controller добавляет IP Pod в EndpointSlice         │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Архитектура удаления Pod и Graceful Shutdown

Процесс удаления инициируется командой `kubectl delete pod` или контроллерами кластера (ReplicaSet при масштабировании, Node Drain, Eviction API).

```
[kubectl delete pod]
        │
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 1. API Server                                                          │
│    - Фиксирует metadata.deletionTimestamp (текущее время UTC)          │
│    - Задает metadata.deletionGracePeriodSeconds (дефолт 30с)           │
│    - Pod переходит в визуальный статус "Terminating"                   │
└────────────────────────────────────────────────────────────────────────┘
        │
        ├──────────────────────────────────────────────────┐
        ▼                                                  ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│ 2. Локальная ветка (kubelet на ноде) │  │ 3. Сетевая ветка (Control    │
│                                      │  │    Plane и Dataplane)        │
│ 2a. Исполнение preStop hook          │  │                              │
│     - kubelet блокирует отправку     │  │ 3a. endpointslice-controller │
│       сигналов на время хука         │  │     - Помечает endpoint как  │
│     - Лимит времени = gracePeriod    │  │       terminating (ready=    │
│     - Если хук затянулся, дается     │  │       false, serving=true)   │
│       однократная фора в 2 секунды   │  │ 3b. kube-proxy / CNI         │
│                                      │  │     - Обновляет iptables /   │
│ 2b. Отправка Stop Signal (SIGTERM)   │  │       IPVS на всех узлах     │
│     - Рантайм отправляет сигнал      │  │ 3c. Ingress / Gateway        │
│       процессу с PID 1               │  │     - Исключает Pod из пула  │
│                                      │  │       балансировки           │
└──────────────────────────────────────┘  └──────────────────────────────┘
        │                                                  │
        │◄───────────────── Задержка сети ─────────────────┘
        ▼                   (от 1 до 5+ секунд)
┌────────────────────────────────────────────────────────────────────────┐
│ 4. Приложение обрабатывает SIGTERM                                     │
│    - Прекращает прием новых клиентских соединений                      │
│    - Дорабатывает текущие активные HTTP-запросы / задачи из очереди    │
│    - Закрывает соединения с базами данных и брокерами сообщений        │
│    - Завершается с кодом 0 (или 143)                                   │
└────────────────────────────────────────────────────────────────────────┘
        │
        ├── Процесс завершился штатно до истечения gracePeriod
        │    │
        │    ▼
        │   [К шагу 6: остановка sidecars и очистка томов]
        │
        └── Процесс завис и не вышел за время gracePeriod
             │
             ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 5. Принудительное уничтожение (SIGKILL)                                │
│    - По истечении gracePeriod рантайм отправляет сигнал SIGKILL (9)    │
│    - Ядро ОС принудительно снимает процесс с выполнения                │
│    - Контейнер завершается с кодом 137                                 │
└────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 6. Финализация kubelet                                                 │
│    - Остановка Native Sidecars (в обратном порядке их объявления)      │
│    - Демонтирование томов (CSI Unmount / TearDown)                     │
│    - Удаление сетевого пространства имен и вызов CNI DEL               │
│    - Удаление pause-контейнера                                         │
│    - Вызов API: удаление объекта Pod из etcd (gracePeriod = 0)         │
└────────────────────────────────────────────────────────────────────────┘
```

#### Проблема сетевой гонки (Race Condition) и решение через preStop

Операция обновления `EndpointSlice` на сотнях узлов кластера через `kube-proxy` и Ingress-контроллеры требует от **1 до 5 секунд** (а в масштабных кластерах при высокой утилизации Control Plane — до 10 секунд).

Если веб-сервер при получении `SIGTERM` мгновенно закрывает слушающий TCP-сокет, Ingress-контроллер или внешний балансировщик, еще не получившие обновленный `EndpointSlice`, продолжат перенаправлять на него клиентские запросы. Результат — клиенты получают ошибки **HTTP 502 Bad Gateway** или **Connection Refused**.

**Стандартное решение в SRE-практике:**
Добавление в конфигурацию контейнера хука `preStop` со `sleep`, превышающим время сетевой конвергенции кластера:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "sleep 10"]
```

В течение этих 10 секунд контейнер продолжает нормально обслуживать входящий трафик. За это время Ingress и kube-proxy гарантированно удаляют адрес пода из iptables/маршрутов, после чего приложению безопасно передается `SIGTERM`.

#### Проблема PID 1 и проброс сигналов

В Linux процесс с PID 1 обладает уникальными системными свойствами: ядро ОС по умолчанию игнорирует для него стандартные обработчики сигналов. Сигналы вроде `SIGTERM` или `SIGINT` доставляются процессу только в том случае, если в коде приложения **явно зарегистрирован обработчик (signal handler)**.

**Типичная ошибка контейнеризации:**
Запуск приложения через shell-форму в `Dockerfile`:
```dockerfile
# ОШИБКА: shell-форма запускает /bin/sh -c "node server.js"
ENTRYPOINT npm start
```
В этом случае PID 1 внутри контейнера получает `/bin/sh`. Стандартный Bourne Shell не пересылает поступающий сигнал `SIGTERM` дочерним процессам (`node server.js`). Приложение не знает об удалении, не выполняет graceful shutdown, зависает на все 30 секунд и убивается принудительным `SIGKILL` (код 137).

**Решения:**
1. Использование exec-формы в `Dockerfile`:
   ```dockerfile
   ENTRYPOINT ["node", "server.js"]
   ```
2. Подмена shell-процесса командой `exec` в entrypoint-скриптах:
   ```bash
   #!/bin/sh
   # Подготовка окружения
   export APP_ENV=production
   # exec замещает shell процессом приложения, передавая ему PID 1
   exec /app/binary --config /etc/app.yaml
   ```
3. Использование легковесных init-систем для контейнеров (`tini` или `dumb-init`):
   ```dockerfile
   RUN apk add --no-cache tini
   ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
   ```
4. Активация `shareProcessNamespace: true` в спецификации Pod: позволяет общему процессу-раздатчику в рамках Pod перехватывать и распределять сигналы между контейнерами.

---

### Сравнение Voluntary и Involuntary Disruption

| Параметр | Voluntary Disruption (Добровольное) | Involuntary Disruption (Вынужденное) |
| :--- | :--- | :--- |
| **Инициатор** | Системный администратор, CI/CD, Deployment Controller, HPA. | Аппаратный сбой, Kernel OOM Killer, kubelet eviction manager. |
| **Примеры событий** | `kubectl drain`, `kubectl rollout restart`, вызов Eviction API, плановый апгрейд нод. | Смерть железа сервера, MemoryPressure, DiskPressure, потеря линка с сетью. |
| **Учет PDB (`PodDisruptionBudget`)** | **Строго учитывается.** API-сервер отклоняет выселение с кодом `429 Too Many Requests`, если нарушается квота. | **Не учитывается.** `kubelet` или ОС завершают процесс немедленно ради спасения узла. |
| **Порядок выселения** | По приоритету `PriorityClass` и правилам контроллера. | По классам качества обслуживания: `BestEffort` → `Burstable` → `Guaranteed`. |
| **Диагностический маркер** | Condition `DisruptionTarget` с причиной `EvictionByEvictionAPI`. | Condition `DisruptionTarget` с причиной `EvictionByKubelet` или `TerminationByKubelet`. |

---

## Практические сценарии и конфигурации

### Сценарий 1: Production-конфигурация Zero-Downtime Graceful Shutdown

Комплексный манифест сервиса с компенсацией задержек сети, корректным `terminationGracePeriodSeconds` и нативным sidecar для сбора логов.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: production-api
  namespace: default
  labels:
    app.kubernetes.io/name: production-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: production-api
  template:
    metadata:
      labels:
        app.kubernetes.io/name: production-api
    spec:
      # Общее время = preStop sleep (15s) + время на завершение активных транзакций (30s) + буфер (15s)
      terminationGracePeriodSeconds: 60
      initContainers:
      - name: log-collector-sidecar
        image: registry.example.com/sysadmin/fluent-bit:3.0.4
        # Native Sidecar: продолжает работать при остановке основного приложения
        restartPolicy: Always
        resources:
          limits:
            cpu: "200m"
            memory: "128Mi"
          requests:
            cpu: "50m"
            memory: "64Mi"
        volumeMounts:
        - name: shared-logs
          mountPath: /var/log/app
      containers:
      - name: web-service
        image: registry.example.com/sysadmin/api-service:v2.12.0
        lifecycle:
          preStop:
            exec:
              # 1. Даем 12 секунд kube-proxy и Ingress на удаление Pod из iptables
              # 2. Вызываем встроенную команду мягкой остановки приложения (если поддерживается)
              command:
              - /bin/sh
              - -c
              - |
                sleep 12
                /usr/local/bin/app-cli graceful-stop || true
        ports:
        - containerPort: 8080
          name: http
        startupProbe:
          httpGet:
            path: /healthz/startup
            port: 8080
          failureThreshold: 30
          periodSeconds: 2
        readinessProbe:
          httpGet:
            path: /healthz/ready
            port: 8080
          initialDelaySeconds: 2
          periodSeconds: 5
          timeoutSeconds: 2
          failureThreshold: 2
        livenessProbe:
          httpGet:
            path: /healthz/live
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 3
        volumeMounts:
        - name: shared-logs
          mountPath: /var/log/app
      volumes:
      - name: shared-logs
        emptyDir: {}
```

---

### Сценарий 2: Комплексная SRE-диагностика фаз и причин падения Pod

Набор проверенных команд для сбора контекста при аварийных инцидентах:

```bash
# 1. Поиск подов, находящихся в нештатных состояниях (не Running и не Completed)
kubectl get pods -A --field-selector status.phase!=Running,status.phase!=Succeeded
# → NAMESPACE   NAME                     READY   STATUS             RESTARTS   AGE
# → default     auth-7448b4564c-x7zlm    0/1     CrashLoopBackOff   6          12m
# → default     worker-db-migration-99   0/1     Error              0          45m

# 2. Быстрое извлечение кода завершения и причины остановки упавшего контейнера
kubectl get pod auth-7448b4564c-x7zlm -o jsonpath='{"Container: "}{.status.containerStatuses[0].name}{"\nExitCode: "}{.status.containerStatuses[0].lastState.terminated.exitCode}{"\nReason: "}{.status.containerStatuses[0].lastState.terminated.reason}{"\nMessage: "}{.status.containerStatuses[0].lastState.terminated.message}{"\n"}'
# → Container: auth
# → ExitCode: 137
# → Reason: OOMKilled
# → Message: 

# 3. Чтение предыдущих логов контейнера (из инстанса перед последним падением)
kubectl logs auth-7448b4564c-x7zlm --previous --tail=50
# → [INFO] Starting auth service v2.4.1...
# → [FATAL] java.lang.OutOfMemoryError: Java heap space

# 4. Проверка условий выселения (DisruptionTarget)
kubectl get pod auth-7448b4564c-x7zlm -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
# → {"lastProbeTime":null,"lastTransitionTime":"2026-10-17T11:00:00Z","message":"Eviction by eviction API","reason":"EvictionByEvictionAPI","status":"True","type":"DisruptionTarget"}
```

---

### Сценарий 3: Регистрация и дерегистрация в Service Discovery через хуки

Практический пример использования `postStart` для прогрева кэша и `preStop` для снятия ноды с балансировщика Consul/Etcd:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: catalog-service
  namespace: production
spec:
  terminationGracePeriodSeconds: 40
  containers:
  - name: catalog
    image: registry.example.com/apps/catalog:1.4.0
    lifecycle:
      postStart:
        exec:
          # Прогрев локального кэша перед готовностью отдавать трафик
          command:
          - /bin/sh
          - -c
          - "curl -s -X POST http://127.0.0.1:8080/internal/warmup > /tmp/warmup.log"
      preStop:
        exec:
          command:
          - /bin/sh
          - -c
          - |
            # 1. Помечаем узел как Maintenance в Consul
            curl -s -X PUT http://consul.local:8500/v1/agent/service/maintenance/catalog-service?enable=true&reason=k8s_pre_stop
            # 2. Ждем оттока активных соединений
            sleep 15
    ports:
    - containerPort: 8080
```

---

### Сценарий 4: Pod с Readiness Gates для внешнего контроллера балансировки

В сценариях интеграции с внешними аппаратными балансировщиками (F5 BIG-IP, HAProxy) или Service Mesh статус `Ready` пода должен подтверждаться внешним управляющим оператором.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: payment-gateway
  namespace: finance
spec:
  # Объявление пользовательского условия готовности
  readinessGates:
  - conditionType: "infrastructure.company.org/lb-ready"
  containers:
  - name: app
    image: registry.example.com/apps/payment:v3.1.0
    ports:
    - containerPort: 9000
    readinessProbe:
      httpGet:
        path: /health
        port: 9000
      periodSeconds: 5
```

**Проверка и ручное подтверждение Readiness Gate через PATCH (эмуляция работы оператора):**

```bash
# 1. Проверка текущих условий пода
kubectl get pod payment-gateway -n finance -o jsonpath='{.status.conditions[*].type}'
# → PodScheduled PodReadyToStartContainers Initialized ContainersReady Ready

# 2. Проверка значения Readiness Gate
kubectl get pod payment-gateway -n finance -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → False

kubectl get pod payment-gateway -n finance -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}'
# → ReadinessGatesNotReady

# 3. Внешний оператор переводит условие в True через PATCH подресурса status
kubectl patch pod payment-gateway -n finance --subresource='status' --type='merge' -p '{
  "status": {
    "conditions": [
      {
        "type": "infrastructure.company.org/lb-ready",
        "status": "True",
        "lastTransitionTime": "2026-10-17T14:45:00Z",
        "reason": "HealthCheckPassed",
        "message": "Node successfully enrolled into upstream balancing pool"
      }
    ]
  }
}'
# → pod/payment-gateway patched

# 4. Проверка итоговой готовности Pod
kubectl get pod payment-gateway -n finance -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → True
```

---

## Диагностические операции и команды

Справочная таблица команд системного администратора для исследования жизненного цикла Pod:

| Операция | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Текущая фаза** | `kubectl get pod <pod> -o jsonpath='{.status.phase}'` | Получение сырой фазы объекта API (`# → Running`). |
| **Список условий** | `kubectl get pod <pod> -o jsonpath='{range .status.conditions[*]}{.type}={.status} {end}'` | Сводка всех условий (`# → PodScheduled=True Initialized=True ContainersReady=True Ready=True`). |
| **Статусы контейнеров** | `kubectl get pod <pod> -o jsonpath='{range .status.containerStatuses[*]}{.name}: waiting={.state.waiting.reason} running={.state.running.startedAt} term={.state.terminated.reason}{"\n"}{end}'` | Детальный аудит состояния каждого контейнера Pod. |
| **Причина падения** | `kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'` | Определение OOMKilled, Error, Completed (`# → OOMKilled`). |
| **Код завершения** | `kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.exitCode}'` | Получение Exit Code последнего запуска (`# → 137`). |
| **Аудит PDB** | `kubectl get pdb -A` | Контроль допустимого количества прерываний (`ALLOWED DISRUPTIONS`). |
| **Логи до падения** | `kubectl logs <pod> -c <container> --previous --tail=100` | Анализ стектрейса ошибки перед перезапуском контейнера. |
| **Проверка выселения** | `kubectl get pod <pod> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")].reason}'` | Точная причина эвикции (`# → EvictionByKubelet`). |

---

## Troubleshooting: типичные ошибки жизненного цикла

### Ошибка 1: Pod застрял в статусе `Pending`

**Симптомы:** Фаза Pod остается `Pending`, узел в `spec.nodeName` не назначен, либо контейнеры не создаются.

**Причины:**
1. Нехватка ресурсов узлов по `requests.cpu` или `requests.memory`.
2. Неудовлетворенные правила `nodeSelector`, `nodeAffinity`, `podAntiAffinity`.
3. На узлах установлены Taints, для которых у Pod отсутствуют Tolerations.
4. Тома `PersistentVolumeClaim` находятся в состоянии `Pending` (нет подходящего PV, сбой CSI-провижинера).
5. Активированы Scheduling Gates (`spec.schedulingGates`), удерживающие планирование.

**Диагностика и решение:**
```bash
# Шаг 1: Проверка секции Events планировщика
kubectl describe pod <pod-name> | grep -A 8 "Events:"
# → Warning  FailedScheduling  3m   default-scheduler  0/12 nodes are available: 3 Insufficient cpu, 9 node(s) had untolerated taint.

# Шаг 2: Проверка наличия активных Scheduling Gates
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
# → [{"name":"example.org/security-scan"}]

# Решение:
# 1. Если не хватает ресурсов: уменьшить requests или добавить рабочие узлы.
# 2. Если застрял PVC: проверить статус StorageClass и дисковых квот (`kubectl describe pvc <pvc-name>`).
# 3. Если блокируют Scheduling Gates: дождаться снятия внешним оператором.
```

---

### Ошибка 2: Pod застрял в `ImagePullBackOff` или `ErrImagePull`

**Симптомы:** Контейнер находится в состоянии `Waiting`, причина `ImagePullBackOff`.

**Причины:**
1. Опечатка в имени репозитория или теге образа (`nginx:latset` вместо `nginx:latest`).
2. Приватный реестр образов: не указан или просрочен `imagePullSecrets`.
3. Проблемы сетевой связности узла с Docker Hub/Registry (таймаут DNS, корпоративный firewall).
4. Превышение лимитов запросов (Rate Limiting) со стороны публичных реестров.

**Диагностика и решение:**
```bash
# Шаг 1: Получение точного сообщения об ошибке скачивания
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].state.waiting.message}'
# → Back-off pulling image "registry.example.com/app:v1.0": rpc error: code = Unknown desc = Error response from daemon: unauthorized: authentication required

# Шаг 2: Проверка секретов на узле (при наличии доступа к ноде)
crictl pull registry.example.com/app:v1.0

# Решение:
# Создать и подключить imagePullSecret:
kubectl create secret docker-registry regcred --docker-server=registry.example.com --docker-username=user --docker-password=pass
# Добавить в pod.spec: imagePullSecrets: [{name: regcred}]
```

---

### Ошибка 3: Pod застрял в `ContainerCreating`

**Симптомы:** Pod назначен на узел, но состояние контейнеров не переходит в `Running`.

**Причины:**
1. Таймаут монтирования томов CSI (диск не отмонтировался от старого упавшего узла — `Multi-Attach error`).
2. Ошибка CNI-плагина: исчерпан пул IP-адресов узла (IPAM pool exhaustion), завис veth-интерфейс.
3. Отсутствуют объекты `ConfigMap` или `Secret`, монтируемые как файлы в `spec.volumes`.

**Диагностика и решение:**
```bash
# Шаг 1: Анализ системных событий kubelet
kubectl describe pod <pod-name> | grep -A 10 "Events:"
# → Warning  FailedMount  45s  kubelet  MountVolume.MountDevice failed for volume "pvc-123" : rpc error: code = Internal desc = volume is already attached to node-02

# Шаг 2: Проверка условия PodReadyToStartContainers
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodReadyToStartContainers")]}'
# → status: False, reason: NetworkPluginNotReady

# Решение:
# 1. При Multi-Attach error: принудительно удалить старый Pod или выполнить `kubectl delete volumeattachment <va-id>`.
# 2. При нехватке IP: перезапустить pod CNI-агента (calico-node, flannel) или расширить подсеть PodCIDR.
```

---

### Ошибка 4: Pod застрял в статусе `Terminating`

**Симптомы:** Pod удаляется, но не исчезает из вывода `kubectl get pods` в течение десятков минут.

**Причины:**
1. На Pod висят неудаляемые финализаторы (`metadata.finalizers`).
2. Завис процесс `preStop hook` (например, бесконечный цикл `sleep` или ожидание ответа от недоступного API).
3. Процесс с PID 1 игнорирует `SIGTERM`, а `SIGKILL` блокируется зависшим в состоянии `D` (Uninterruptible Sleep) вводом-выводом NFS/Ceph/диска.
4. Процесс на узле удерживает точку монтирования тома Pod.

**Диагностика и решение:**
```bash
# Шаг 1: Проверка наличия Finalizers
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'
# → ["storage.example.com/backup-protection"]

# Шаг 2: Поиск блокирующих процессов на рабочем узле (через SSH)
lsof +D /var/lib/kubelet/pods/<pod-uid>/volumes/

# Решение:
# 1. Если финализатор оставлен некорректно работающим оператором:
kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":null}}' --type=merge

# 2. Принудительное удаление из etcd (ВНИМАНИЕ: может привести к split-brain для StatefulSet!):
kubectl delete pod <pod-name> --grace-period=0 --force
```

---

### Ошибка 5: Циклические перезапуски `CrashLoopBackOff`

**Симптомы:** Pod циклически перезапускается, счетчик `RESTARTS` растет.

**Причины:**
1. `Exit Code 1`: ошибка логики приложения, невалидный конфигурационный файл.
2. `Exit Code 137`: превышение лимита памяти узла (`OOMKilled`).
3. `Exit Code 127`: бинарный файл не найден (неверный путь в `command`).
4. Не проходит `livenessProbe` (приложение отвечает с задержкой или возвращает 500).

**Диагностика и решение:**
```bash
# Шаг 1: Проверка кода и причины завершения
kubectl get pod <pod-name> -o jsonpath='{range .status.containerStatuses[*]}{.name}{": code="}{.lastState.terminated.exitCode}{" reason="}{.lastState.terminated.reason}{"\n"}{end}'
# → backend: code=137 reason=OOMKilled

# Шаг 2: Проверка логов упавшего инстанса
kubectl logs <pod-name> --previous --tail=30

# Решение:
# 1. При OOMKilled: увеличить `resources.limits.memory` в манифесте.
# 2. При Liveness Failure: увеличить `timeoutSeconds` и `failureThreshold`, либо использовать `startupProbe`.
```

---

### Ошибка 6: Ошибки `Init:Error` и `Init:CrashLoopBackOff`

**Симптомы:** Pod не доходит до фазы запуска основных контейнеров, застревая на этапе инициализации.

**Причины:**
1. Init-контейнер завершился с кодом != 0 (миграция базы данных упала, недоступен внешний хост).
2. Init-контейнер исчерпал лимиты памяти (OOMKilled).

**Диагностика и решение:**
```bash
# Просмотр логов конкретного init-контейнера
kubectl logs <pod-name> -c <init-container-name>
# → ERROR: Connection to PostgreSQL at db.internal:5432 failed: password authentication failed

# Решение:
# Исправить конфигурацию, секреты доступа или сетевые политики для зависимостей Init-контейнера.
```

---

### Ошибка 7: `CreateContainerConfigError`

**Симптомы:** Контейнер не может быть создан (`Waiting: CreateContainerConfigError`).

**Причины:** Отсутствует `ConfigMap` или `Secret`, на которые ссылается `envFrom` или `valueFrom`.

**Диагностика и решение:**
```bash
# Шаг 1: Извлечение детального сообщения об ошибке
kubectl describe pod <pod-name> | grep -A 5 "CreateContainerConfigError"
# → Error: configmap "app-config" not found

# Решение:
# Создать недостающий ConfigMap:
kubectl create configmap app-config --from-literal=APP_ENV=production
```

---

## Best Practices для DevOps, SRE и системных администраторов

1. **Всегда объявляйте `terminationGracePeriodSeconds` явно.** Рассчитывайте его по формуле: $\text{GracePeriod} = \text{preStop sleep} + \text{максимальное время доработки транзакции} + 10\text{с buffer}$. Для обычных Web API задавайте 45–60с, для БД — 90–180с.
2. **Внедряйте `preStop sleep` в каждый Production Deployment с Ingress/Service.** Задержка в 10–15 секунд перед передачей `SIGTERM` полностью исключает появление ошибок `502 Bad Gateway` при плановых обновлениях.
3. **Используйте `startupProbe` для медленно стартующих приложений.** Задавайте высокий порог `failureThreshold` (например, 30 проверок с периодом 2с = 60 секунд запаса). Это избавит от ложных перезапусков Liveness-пробами во время прогрева JVM или компиляции кэшей.
4. **Не настраивайте `livenessProbe` на внешние зависимости.** Liveness-проба должна оценивать только локальное здоровье процесса (например, внутренний deadlock потоков). Если упала внешняя БД, падение Liveness-пробы вызовет перезапуск всех реплик приложения, что создаст лавинообразную нагрузку на БД при ее старте.
5. **Всегда используйте exec-форму запуска в контейнерах.** Конструкции вида `ENTRYPOINT ["/binary"]` или запуск через утилиты инициализации (`tini`, `dumb-init`) гарантируют доставку сигналов `SIGTERM` целевому приложению без зависания в shell.
6. **Определяйте PDB (`PodDisruptionBudget`) для всех критических сервисов.** Конфигурации `minAvailable: 1` или `maxUnavailable: 25%` гарантируют защиту сервиса от деградации при выполнении `kubectl drain` администраторами платформы.
7. **Никогда не применяйте `kubectl delete pod --force --grace-period=0` для StatefulSet без физической проверки узла.** Принудительное удаление Pod из etcd на живом, но изолированном по сети узле приведет к параллельному запуску двух инстансов базы данных с одинаковым PV и разрушению файловой системы тома (Split-Brain).
8. **Используйте `terminationMessagePolicy: FallbackToLogsOnError`.** Это позволяет централизованно собирать в метрики Kubernetes причины падения контейнеров без необходимости парсинга сотен мегабайт внешних логов.

---

## Связанные темы

* [Обзор архитектуры Pod](./pod_overview.md) — базовые ресурсы, фазы и контейнерная изоляция.
* [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md) — детальная архитектура Native Sidecars.
* [Init-контейнеры в Kubernetes](./pod_init_containers.md) — последовательность инициализации и управление ресурсами.
* [Перезапуск Pod в Kubernetes](./pod_restarts.md) — глубокий разбор Restart Policy и расчета задержек.
* [Пробы в Kubernetes (Probes)](../probes.md) — конфигурация Startup, Liveness и Readiness механизмов.
* [Продвинутые темы Pod](./pod_advanced_topics.md) — глубокий разбор Readiness Gates и Scheduling Gates.
* [Практические команды и сценарии управления Pod](./pod_practical_scenarios_commands.md) — сборка комплексных скриптов управления.
* [Graceful Shutdown: Глубокое погружение](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — отладка блокировок при остановке.
* [Диагностика ошибок Pending](../../Troubleshooting/Common_Errors/pod_pending/diagnostics.md) — устранение причин сбоев планирования.
* [CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md) — разбор инцидентов падения контейнеров.
* [Pod Disruption Budget](../../Autoscaling/pod_disruption_budget.md) — обеспечение отказоустойчивости при плановом обслуживании.
