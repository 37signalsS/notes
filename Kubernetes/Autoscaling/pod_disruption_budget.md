# Бюджет прерывания подов (Pod Disruption Budget, PDB)

**Актуально для:** Kubernetes 1.31+

## Определения

**Pod Disruption Budget (PDB)** — объект Kubernetes API (`policy/v1`), ограничивающий количество подов реплицированного приложения, которые могут быть одновременно недоступны в результате *добровольных прерываний*.

> **Архитектурное правило:** PDB защищает **доступность сервиса**, а не сохранность данных. Для сохранности данных используются персистентные тома (PV/PVC), механизмы резервного копирования и репликация на прикладном уровне. PDB предотвращает простой бизнес-логики при регламентных работах на узлах кластера.

**Добровольные прерывания (Voluntary Disruptions)** — преднамеренные регламентные операции, инициируемые системным администратором, SRE или системной автоматикой через Eviction API:
* Очистка узла (`kubectl drain`) для обновления ядра Linux, установки патчей безопасности, обслуживания оборудования или перезагрузки гипервизора.
* Удаление или сжатие узлов локальными автоскейлерами инфраструктуры (Cluster Autoscaler).
* Перераспределение подов для дефрагментации или балансировки нагрузки между физическими серверами (Descheduler).
* Вытеснение подов планировщиком по приоритету (Priority Preemption), когда для высокоприоритетной рабочей нагрузки требуется освободить ресурсы узла.

**Недобровольные прерывания (Involuntary Disruptions)** — внезапные аппаратные и системные аварии, от которых PDB **не защищает** (так как они происходят на уровне ядра ОС, железа или kubelet в обход Eviction API):
* Аппаратный сбой сервера (выход из строя блока питания, сбой планки оперативной памяти, отказ дискового RAID-контроллера).
* Kernel Panic или зависание операционной системы физического хоста.
* Сетевой сплит (Network Partition), потеря линка на коммутаторе стойки или изоляция узла от Control Plane.
* Принудительное завершение процессов ядром Linux из-за исчерпания памяти (OOMKilled).
* Node Pressure Eviction — экстренное локальное выселение подов демоном `kubelet` при достижении критических порогов нехватки памяти, дескрипторов файлов или места на диске (`DiskPressure`, `MemoryPressure`, `PIDPressure`).

**Eviction API** — специализированная конечная точка Kubernetes API (подресурс `/eviction` для Pod), через которую выполняются безопасные запросы на выселение. Eviction API проверяет соответствие запроса действующим бюджетам PDB. Если выселение нарушает бюджет, API-сервер возвращает код ошибки `429 Too Many Requests`. Прямое удаление пода администратором (`kubectl delete pod`) **игнорирует PDB** и вызывает немедленную терминацию.

**Политика выселения нездоровых подов (`unhealthyPodEvictionPolicy`)** — параметр спецификации PDB (GA с Kubernetes 1.30+), регламентирующий, как обрабатывать выселение подов, находящихся в неработоспособном состоянии (`CrashLoopBackOff`, `Pending` или не прошедших Readiness Probe).

**Условие прерывания пода (DisruptionTarget)** — стандартный статус пода (`status.conditions[type: DisruptionTarget]`, GA с Kubernetes 1.31+), устанавливаемый при начале процедуры выселения для информирования контроллеров и систем мониторинга о причине прекращения работы пода.

---

## Архитектура и основные концепции

### Архитектурная роль и разделение ответственности

В production-инфраструктуре PDB выступает формальным контрактом доступности (SLA) между системными администраторами (Cluster Administrators / SRE) и владельцами сервисов (Application Owners):

| Роль | Зона ответственности | Взаимодействие с PDB |
|---|---|---|
| **Cluster Administrator / SRE** | Эксплуатация инфраструктуры: обновление серверов, ядра, вывод узлов на техобслуживание | Запускает `kubectl drain`. Команда подчиняется PDB и блокируется, если доступность приложения находится под угрозой. |
| **Application Owner / DevOps** | Развертывание и жизненный цикл сервисов | Определяет PDB в манифестах приложения, задавая минимальное число реплик для обработки трафика или сохранения кворума. |

PDB критически необходим для двух категорий рабочих нагрузок:
1. **Stateless-сервисы с балансировкой трафика:** предотвращает просадку пропускной способности сервиса ниже допустимого SLA при массовом обновлении пула узлов.
2. **Stateful-кластеры с кворумом (etcd, ZooKeeper, Consul, Patroni, ClickHouse, RabbitMQ):** гарантирует, что число активных узлов кластера не упадет ниже строгого большинства, исключая распад кворума (Split-Brain) и переход СУБД в режим read-only.

### Поддерживаемые контроллеры и ограничения

PDB рассчитывает бюджет на основе меток селектора (`selector.matchLabels`), сопоставляя их с подами в пространстве имен:
* **Deployment, StatefulSet, ReplicaSet:** полностью поддерживаются «из коробки». PDB динамически опрашивает контроллер для определения желаемого числа реплик.
* **Кастомные контроллеры (Custom Operators):** поддерживаются, если в их Custom Resource Definition (CRD) реализован подресурс `scale` (`/scale`), возвращающий спецификацию реплик.
* **DaemonSet:** PDB **не применяется** к DaemonSet. Под DaemonSet привязан к конкретному узлу; при очистке узла под не может мигрировать на другой сервер, где такой под уже запущен. При выселении `kubectl drain` требует явного флага `--ignore-daemonsets`.
* **Jobs / CronJobs:** PDB **не используется**. Пакетная задача должна завершиться до конца, либо контроллер перезапустит упавший под согласно политике перезапуска.
* **Ad-hoc поды (поды без управляющего контроллера):** PDB может выбирать автономные поды, но имеет жесткие ограничения: поддерживается только целочисленный `minAvailable` (проценты недоступны, так как неизвестно общее целевое число реплик), а `maxUnavailable` запрещен. Для production использование автономных подов без контроллера не рекомендуется.

### Жизненный цикл выселения через Eviction API

Взаимодействие при регламентных работах строится по следующему алгоритму:

```
[ Администратор / Скрипт ]
           │
           ▼
    kubectl drain node-01
           │
           ▼
  1. Вызывает Cordon (node-01 -> SchedulingDisabled)
  2. Запрашивает список подов на node-01
  3. Для каждого пода отправляет запрос:
     POST /api/v1/namespaces/{ns}/pods/{name}/eviction
           │
           ▼
 [ Kubernetes API Server ]
           │
           ├──► Проверяет селекторы всех PDB в namespace пода
           │
   ┌───────┴───────────────────────────────┐
   ▼                                       ▼
Бюджет соблюдается                     Бюджет нарушен
(disruptionsAllowed > 0)               (disruptionsAllowed == 0)
   │                                       │
   ▼                                       ▼
API Server декрементирует              API Server возвращает
disruptionsAllowed,                    HTTP 429 Too Many Requests
подтверждает удаление пода             ("Cannot evict pod: violates PDB")
   │                                       │
   ▼                                       ▼
Kubelet инициирует Graceful Shutdown   kubectl drain ожидает паузу
(SIGTERM -> preStop -> SIGKILL)        и повторяет запрос в цикле
   │                                   до истечения --timeout
   ▼
Контроллер (Deployment/StatefulSet)
создает под-замену на другой ноде
   │
   ▼
Новый под переходит в Ready=True
   │
   ▼
PDB инкрементирует disruptionsAllowed
(следующий под разблокирован)
```

### Параметры спецификации: minAvailable vs maxUnavailable

В манифесте PDB задается строго **одно** из двух полей (`minAvailable` или `maxUnavailable`):

| Параметр | Тип | Описание | Когда применять |
|---|---|---|---|
| `spec.minAvailable` | `int` или `string` (процент) | Минимальное число или процент реплик, которые **обязаны оставаться в статусе Ready** при выселении. | Stateful-нагрузки с кворумом (например, `minAvailable: 2` для 3 реплик etcd/Patroni), где критично абсолютное число живых узлов. |
| `spec.maxUnavailable` | `int` или `string` (процент) | Максимальное число или процент реплик, которые **разрешено одновременно остановить**. | Масштабируемые веб-приложения и микросервисы (например, `maxUnavailable: 20%` или `maxUnavailable: 1`). |

> **Критическое правило:** Установка `maxUnavailable: 0` или `minAvailable: 100%` (или `minAvailable: 1` при `replicas: 1`) **полностью блокирует** выселение подов. Команда `kubectl drain` никогда не сможет завершиться без принудительного вмешательства администратора.

### Логика округления процентов

При вычислении количества подов по процентам Kubernetes всегда выполняет округление **в большую сторону до ближайшего целого** (`ceil`):
* При `minAvailable: 50%` для 7 реплик: `7 * 0.5 = 3.5` → округляется до **4 подов**. Должно остаться 4 готовых пода, выселить можно максимум 3.
* При `maxUnavailable: 25%` для 7 реплик: `7 * 0.25 = 1.75` → округляется до **2 подов**. Разрешено выселить максимум 2 пода одновременно.

### Взаимодействие PDB и стратегии обновления Deployment (Rolling Update)

Параметры `maxUnavailable` в PDB и в Deployment решают принципиально разные задачи:

| Характеристика | PDB `spec.maxUnavailable` | Deployment `spec.strategy.rollingUpdate.maxUnavailable` |
|---|---|---|
| **API ресурс** | `policy/v1` (PodDisruptionBudget) | `apps/v1` (Deployment) |
| **Точка перехвата** | Eviction API (регламентное обслуживание нод, drain, дескейлер) | Deployment Controller (развертывание новой версии образа) |
| **Влияние на `kubectl drain`** | **Прямое блокирующее действие** | Не блокирует drain |
| **Создание замены** | Не создает поды, только защищает существующие | Контроллер сам управляет созданием новых и гашением старых подов |

Во время Rolling Update контроллер Deployment создает новые реплики параллельно с удалением старых. PDB учитывает общее количество доступных готовых подов (сумму старой и новой версии). Если администратор запускает `kubectl drain` прямо в момент выполнения Rolling Update, PDB защитит сервис от избыточной деградации.

### Различие поведения Deployment и StatefulSet при выселении

Механика пересоздания подов при `kubectl drain` существенно отличается для stateless и stateful архитектур:

1. **Deployment (ReplicaSet):**
   * При получении команды eviction под переходит в `Terminating`.
   * ReplicaSet Controller немедленно заказывает создание нового пода со случайным суффиксом имени и новым UID (`app-abc-111` → `app-abc-222`).
   * Планировщик может разместить новый под на другом свободном узле **параллельно** с тем, как старый под завершает работу.
   * Как только новый под проходит Readiness Probe, бюджет PDB восстанавливается.

2. **StatefulSet:**
   * Поды StatefulSet обладают стабильной сетевой идентичностью (`db-0`, `db-1`, `db-2`) и уникальными PV.
   * Контроллер StatefulSet **не может** создать новый под `db-0`, пока старый под `db-0` не будет полностью удален и дерегистрирован в Control Plane.
   * Новый под с тем же именем создается строго последовательно после полного освобождения ресурсов старым подом.
   * Для StatefulSet с репликацией рекомендуется устанавливать `spec.maxUnavailable: 1`, чтобы ноды кластера СУБД обновлялись строго поочередно.

### Политика выселения нездоровых подов (Unhealthy Pod Eviction Policy)

Начиная с Kubernetes 1.30 (GA), поле `spec.unhealthyPodEvictionPolicy` позволяет разрешить системный дедлок при выселении сбойных подов:

```yaml
spec:
  unhealthyPodEvictionPolicy: AlwaysAllow # или IfHealthyBudget (по умолчанию)
```

| Режим | Поведение | Риски и сценарии |
|---|---|---|
| **`IfHealthyBudget`** (по умолчанию) | Нездоровый под (`CrashLoopBackOff`, сбойная Readiness Probe) может быть выселен только в том случае, если число остальных здоровых подов удовлетворяет бюджету (`currentHealthy >= desiredHealthy`). | Если у сервиса из 3 реплик упали 2 пода (`currentHealthy = 1`), а PDB требует `minAvailable: 2`, drain ноды со сбойным подом **зависнет намертво**, ожидая, пока под станет здоровым. |
| **`AlwaysAllow`** | Поды, не прошедшие Readiness Probe или находящиеся в циклическом падении, выселяются **независимо от состояния бюджета**. | Исключает зависание `kubectl drain` из-за проблемных приложений на узле. Рекомендуется SRE для сервисов, чьи сбои не должны блокировать регламентные работы на хостах. |

### Условия прерывания пода (DisruptionTarget)

Начиная с Kubernetes 1.31 (GA), в объект Pod в массив `status.conditions` добавляется условие `DisruptionTarget`, если под подвергается принудительному завершению. Это позволяет SRE точно установить причину завершения пода:

```yaml
status:
  conditions:
    - type: DisruptionTarget
      status: "True"
      reason: EvictionByEvictionAPI
      message: "Eviction API request accepted"
```

Значения поля `reason`:
* `EvictionByEvictionAPI` — под выселен регламентной операцией (`kubectl drain`).
* `PreemptionByKubeScheduler` — под вытеснен планировщиком ради более приоритетной нагрузки.
* `DeletionByTaintManager` — узел получил Taint `NoExecute` (например, узел перешел в статус NotReady).
* `EvictionByKubelet` — локальное выселение из-за нехватки ресурсов узла (`NodePressure`).
* `TerminationByKubelet` — локальное выключение ноды демоном Kubelet (`Graceful Node Shutdown`).

### Сравнение механизмов завершения подов

| Механизм | Инициатор | Триггер | PDB учитывается? | Действие администратора |
|---|---|---|---|---|
| **Eviction API** | SRE / Descheduler | `kubectl drain`, балансировка подов | **ДА** | Дождаться Ready подов или скорректировать PDB |
| **Break-Glass Drain** | SRE | `kubectl drain --disable-eviction` | **НЕТ** | Принудительное освобождение хоста в обход PDB |
| **Прямое удаление** | Пользователь | `kubectl delete pod <name>` | **НЕТ** | Использовать для экстренного перезапуска |
| **Node Pressure Eviction** | Демон `kubelet` | Превышение лимитов диска, RAM, PID на хосте | **НЕТ** | Оптимизировать Requests/Limits, очистить диск узла |
| **Taint-based Eviction** | Node Controller | Узел перешел в `NotReady` / `unreachable` | **НЕТ** | Проверить физический сервер, сеть хоста, kubelet |
| **OOM Killer** | Ядро Linux | Превышение контейнером `limits.memory` | **НЕТ** | Настроить правильный сайзинг памяти, профилировать утечки |
| **Priority Preemption** | Kube-scheduler | Появление пода с высоким `PriorityClass` | По умолчанию **НЕТ** (настраивается) | Использовать `preemptionPolicy: Never` для защиты жертв |

---

## Практические сценарии и конфигурация

### Требования к окружению

Для работы с PDB кластер должен поддерживать стабильный API `policy/v1` (Kubernetes 1.21+):

```bash
# Проверка доступности API-ресурса PodDisruptionBudget
kubectl api-resources --api-group=policy
# → NAME                   SHORTNAMES   APIVERSION   NAMESPACED   KIND
# → poddisruptionbudgets   pdb          policy/v1    true         PodDisruptionBudget

# Проверка версии кластера
kubectl version --short
# → Client Version: v1.31.2
# → Server Version: v1.31.2
```

### Сценарий 1: Высокодоступный Stateless микросервис (Deployment)

Конфигурация для критического HTTP-бэкенда с 5 репликами. Допускается временное отсутствие не более 20% реплик:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway
  namespace: production
  labels:
    app.kubernetes.io/name: api-gateway
spec:
  replicas: 5
  selector:
    matchLabels:
      app: api-gateway
  template:
    metadata:
      labels:
        app: api-gateway
    spec:
      containers:
        - name: gateway
          image: nginx:1.27-alpine
          ports:
            - containerPort: 80
          readinessProbe:
            httpGet:
              path: /healthz
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api-gateway-pdb
  namespace: production
spec:
  maxUnavailable: 20%
  unhealthyPodEvictionPolicy: AlwaysAllow
  selector:
    matchLabels:
      app: api-gateway
```

Проверка применения:

```bash
kubectl apply -f api-gateway.yaml
# → deployment.apps/api-gateway created
# → poddisruptionbudget.policy/v1/api-gateway-pdb created

kubectl get pdb -n production
# → NAME              MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → api-gateway-pdb   N/A             20%               1                     15s
```

### Сценарий 2: StatefulSet с распределенным кворумом (Patroni / etcd)

Для кластера из 3 узлов etcd или Patroni падение двух узлов одновременно фатально. Необходим строгий кворум: минимум 2 узла обязаны функционировать непрерывно:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: etcd-quorum-pdb
  namespace: database
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: etcd-cluster
```

При 3 активных репликах `ALLOWED DISRUPTIONS = 1`. Как только один под начинает выселяться, бюджет падает до `0`. Второй узел невозможно выселить, пока первый не перейдет в `Ready` на новом узле.

### Сценарий 3: Брокер очередей сообщений (Kafka / RabbitMQ StatefulSet)

Для кластеров со сложной репликацией очередей выселение нескольких брокеров вызывает чрезмерную нагрузку на сеть хостов из-за синхронизации реплик. Настройка последовательного обновления:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: kafka-brokers-pdb
  namespace: messaging
spec:
  maxUnavailable: 1
  unhealthyPodEvictionPolicy: IfHealthyBudget
  selector:
    matchLabels:
      app.kubernetes.io/component: kafka-broker
```

### Сценарий 4: Регламентное обслуживание ноды (SRE Drain Workflow)

Пошаговая процедура безопасного вывода физического сервера на техобслуживание с контролем PDB:

```bash
# Шаг 1: Предварительная симуляция drain (Dry-Run)
kubectl drain worker-04.corp.local --ignore-daemonsets --delete-emptydir-data --dry-run=server
# → node/worker-04.corp.local cordoned (dry run)
# → evicting pod production/api-gateway-695c898c69-f8s2j (dry run)
# → node/worker-04.corp.local drained (dry run)

# Шаг 2: Мониторинг состояния PDB в отдельной сессии терминала
kubectl get pdb -A -w
# → NAMESPACE    NAME              MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → production   api-gateway-pdb   N/A             20%               1                     2d

# Шаг 3: Выполнение реального выселения с тайм-аутом
kubectl drain worker-04.corp.local --ignore-daemonsets --delete-emptydir-data --timeout=10m
# → node/worker-04.corp.local cordoned
# → evicting pod production/api-gateway-695c898c69-f8s2j
# → pod/api-gateway-695c898c69-f8s2j evicted
# → node/worker-04.corp.local drained

# Шаг 4: Возврат ноды в строй после завершения регламентных работ
kubectl uncordon worker-04.corp.local
# → node/worker-04.corp.local uncordoned
```

### Сценарий 5: Break-Glass — экстренное выселение при блокировке PDB

Если `kubectl drain` блокируется некорректным PDB, а сервер требует немедленной остановки (например, перегрев стойки, замена диска), SRE применяет аварийные механизмы:

```bash
# Вариант А: Использование флага --disable-eviction (обход Eviction API)
# Вызывает стандартный DELETE Pods напрямую через API, игнорируя PDB
kubectl drain worker-04.corp.local --ignore-daemonsets --delete-emptydir-data --disable-eviction --force

# Вариант Б: Экстренный патч PDB в 100% допустимых потерь
kubectl patch pdb api-gateway-pdb -n production -p '{"spec":{"minAvailable":null,"maxUnavailable":"100%"}}'
# → poddisruptionbudget.policy/v1/api-gateway-pdb patched

# Вариант В: Временное удаление PDB с последующим восстановлением
kubectl get pdb api-gateway-pdb -n production -o yaml > /tmp/api-gateway-pdb.yaml
kubectl delete -f /tmp/api-gateway-pdb.yaml
# → Выполнение drain ...
kubectl apply -f /tmp/api-gateway-pdb.yaml
```

### Сценарий 6: Совместная работа PDB, HPA и Pod Anti-Affinity

При автомасштабировании (HPA) количество подов постоянно меняется. Использование жесткого числового `minAvailable` может привести к дедлокам при снижении нагрузки (Scale-Down). Решение — процентный `maxUnavailable` в сочетании с окном стабилизации HPA:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: billing-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: billing-service
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 75
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 20
          periodSeconds: 60
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: billing-pdb
  namespace: production
spec:
  maxUnavailable: 25%
  selector:
    matchLabels:
      app: billing-service
```

---

## Диагностика и устранение неполадок

### Пошаговый алгоритм расследования дедлоков при drain

Когда выполнение `kubectl drain` завершается ошибкой вида:
`error when evicting pod "app-xxx" (will retry after 5s): Cannot evict pod as it would violate the pod's disruption budget.`

Применяется следующая диагностическая матрица:

```
                  kubectl drain зависает
                            │
                            ▼
              kubectl get pdb -A | grep -E " 0 "
                            │
             ┌──────────────┴──────────────┐
             ▼                             ▼
   ALLOWED DISRUPTIONS = 0        ALLOWED DISRUPTIONS > 0
             │                             │
   kubectl describe pdb <name>             ▼
             │                    Drain ожидает завершения
             │                    graceful shutdown (preStop / finalizers)
             │                    Проверить: kubectl get pods
             ▼
┌──────────────────────────────────────────────┐
│ Проверка полей status:                       │
│ - currentHealthy < desiredHealthy?           │
│   ├─ Поды в CrashLoopBackOff / NotReady      │
│   │  └► Установить AlwaysAllow               │
│   └─ Поды в Pending (нет ресурсов/квот)      │
│      └► Добавить ресурсы или снизить лимиты  │
│                                              │
│ - replicas == minAvailable?                  │
│   └► Ошибка сайзинга: PDB слишком жесткий    │
│                                              │
│ - Дублирующиеся селекторы?                   │
│   └► Два разных PDB матчат одни и те же поды │
└──────────────────────────────────────────────┘
```

#### 1. Анализ условий статуса PDB (`status.conditions`)

Начиная с Kubernetes 1.30, PDB содержит структурированные условия:

```bash
kubectl get pdb api-gateway-pdb -n production -o yaml
```

Фрагмент статуса при блокировке:

```yaml
status:
  currentHealthy: 2
  desiredHealthy: 3
  disruptionsAllowed: 0
  expectedPods: 3
  conditions:
    - type: DisruptionAllowed
      status: "False"
      reason: InsufficientPods
      message: "There are not enough healthy pods to allow disruption."
      lastTransitionTime: "2026-10-13T12:00:00Z"
```

Значения `reason` в условиях:
* `SufficientPods` — выселение разрешено (`status: "True"`).
* `InsufficientPods` — число здоровых подов меньше целевого, выселение заблокировано.
* `SyncFailed` — контроллер PDB не может получить доступ к целевому объекту (ошибка в селекторе или сбой прав RBAC).

#### 2. Зависшие выселения (`status.disruptionTarget`)

Если под получил разрешение на выселение, но не удаляется, PDB сохраняет ссылку на него в поле `status.disruptionTarget`. Это блокирует последующие выселения:

```bash
# Проверка наличия зависших таргетов
kubectl get pdb api-gateway-pdb -n production -o jsonpath='{.status.disruptionTarget}'
# → [{"name":"api-gateway-7b94bfbc86-9m2k8","uid":"f3214b7e-908b-4c07-b3f7-41e97669d20c"}]
```

Причины зависания:
* Зависший `preStop` hook в контейнере (пока не истечет `terminationGracePeriodSeconds`).
* Блокирующие финализаторы (`metadata.finalizers`) на объекте Pod.
* Проблемы с отключением томов на узле (CSI / Kubelet volume unmount timeout).

Решение:

```bash
# Принудительная очистка finalizers зависшего пода
kubectl patch pod api-gateway-7b94bfbc86-9m2k8 -n production -p '{"metadata":{"finalizers":null}}'
```

### Типичные ошибки конфигурации и архитектурные антипаттерны

#### Антипаттерн 1: Однорепличное приложение со строгим PDB

```yaml
# НЕПРАВИЛЬНО:
apiVersion: apps/v1
kind: Deployment
metadata:
  name: legacy-app
spec:
  replicas: 1
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: legacy-app-pdb
spec:
  minAvailable: 1 # или maxUnavailable: 0
```

*Проблема:* Выселение единственного пода снизит число доступных реплик до 0, что нарушает `minAvailable: 1`. Вывод узла из строя заблокирован навсегда.
*Исправление:* Для приложений с 1 репликой PDB не настраивается, либо настраивается `maxUnavailable: 1` с осознанием допустимости кратковременного даунтайма.

#### Антипаттерн 2: Пересекающиеся селекторы (Overlapping PDBs)

Если администратор создал два PDB:
1. `pdb-global` с `matchLabels: env: prod`
2. `pdb-backend` с `matchLabels: app: backend, env: prod`

Для любого пода с метками `app=backend, env=prod` Eviction API потребует согласия **обоих** PDB одновременно. Если хотя бы один PDB имеет `disruptionsAllowed = 0`, под не будет выселен.

*Исправление:* Удалить дублирующий PDB. Селекторы PDB должны быть взаимно изолированными.

#### Антипаттерн 3: Пустой селектор `matchLabels: {}`

В API `policy/v1` пустой селектор захватывает **абсолютно все поды** в данном namespace. Если в этом namespace есть хотя бы один нездоровый под, блокируются операции выселения вообще для всех сервисов пространства имен.

### Мониторинг и алертинг в Prometheus

#### Системные метрики kube-controller-manager

| Метрика | Тип | Описание |
|---|---|---|
| `pod_disruption_budgets` | Gauge | Общее количество зарегистрированных PDB в кластере. |
| `pod_disruption_budgets_sync_total` | Counter | Количество циклов синхронизации контроллера PDB. |
| `pod_disruption_budgets_sync_errors_total` | Counter | Количество ошибок валидации и синхронизации PDB. |

#### Метрики kube-state-metrics

| Метрика | Тип | Описание |
|---|---|---|
| `kube_poddisruptionbudget_status_disruptions_allowed` | Gauge | Количество подов, выселение которых разрешено в данный момент. |
| `kube_poddisruptionbudget_status_current_healthy` | Gauge | Текущее количество здоровых подов, удовлетворяющих селектору. |
| `kube_poddisruptionbudget_status_desired_healthy` | Gauge | Желаемое минимальное количество здоровых подов. |
| `kube_poddisruptionbudget_status_expected_pods` | Gauge | Общее число обнаруженных подов контроллера. |

#### Правила алертинга (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: pdb-monitoring-rules
  namespace: monitoring
spec:
  groups:
    - name: kubernetes-pdb.rules
      rules:
        - alert: PDBEvictionBlocked
          expr: kube_poddisruptionbudget_status_disruptions_allowed == 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Выселение подов заблокировано через PDB"
            description: "PDB {{ $labels.namespace }}/{{ $labels.poddisruptionbudget }} не разрешает выселение подов более 15 минут. Это заблокирует kubectl drain."

        - alert: PDBHealthDeficit
          expr: kube_poddisruptionbudget_status_current_healthy < kube_poddisruptionbudget_status_desired_healthy
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Дефицит доступных реплик в PDB"
            description: "В PDB {{ $labels.namespace }}/{{ $labels.poddisruptionbudget }} число здоровых подов ({{ $value }}) ниже минимально допустимого порога."

        - alert: PDBSyncErrorsHigh
          expr: rate(pod_disruption_budgets_sync_errors_total[5m]) > 0.1
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Ошибки синхронизации контроллера PDB"
            description: "Kube-controller-manager фиксирует ошибки обработки PDB объектов."
```

---

## Лучшие практики

1. **Создавайте PDB для всех критических мультирепличных нагрузок:** Каждое приложение в production с `replicas >= 2` должно иметь PDB. Это обязательный контракт между владельцем сервиса и платформенной командой.
2. **Используйте процентные значения для stateless:** Для масштабируемых сервисов задавайте `maxUnavailable: 20%` или `maxUnavailable: 25%`. Это гарантирует корректную работу PDB как при 4 репликах, так и при 40.
3. **Используйте абсолютные числа для StatefulSet и кворумов:** Для кластеров СУБД (etcd, Consul, Patroni) рассчитывайте формулу кворума:
   $$\text{minAvailable} = \lfloor N / 2 \rfloor + 1$$
   где $N$ — общее число членов кластера.
4. **Всегда включайте `unhealthyPodEvictionPolicy: AlwaysAllow` для фоновых микросервисов:** Это исключает ситуацию, когда единичный упавший под в `CrashLoopBackOff` блокирует обслуживание физического сервера всей команде инфраструктуры.
5. **Сочетайте PDB с PodAntiAffinity и TopologySpreadConstraints:** PDB гарантирует, что поды не будут выселены одновременно, но если планировщик разместил все реплики на одном физическом сервере, выключение этого сервера уничтожит сервис целиком в обход PDB (как недобровольный сбой). Разносите поды по разным хостам и стойкам:

```yaml
spec:
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchExpressions:
              - key: app
                operator: In
                values:
                  - api-gateway
          topologyKey: kubernetes.io/hostname
```

6. **Настраивайте корректный `readinessProbe`:** PDB считает под здоровым (`Ready`), как только проба готовности завершилась успехом. Если приложению требуется дополнительное время на прогрев кэша, закладывайте его в параметры пробы, иначе последующие поды начнут выселяться до реальной готовности замены к приему нагрузки.
7. **Координируйте `terminationGracePeriodSeconds`:** При длительном завершении соединений (например, 120 секунд) тайм-аут drain на хосте должен быть существенно больше суммы времени завершения всех подов на узле.

---

## Дополнительная информация

### Взаимодействие со смежными компонентами экосистемы

* **[Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md)** — регламентные процедуры и детальный разбор флагов `kubectl drain`.
* **[Диагностика зависаний при drain (pdb_blocking)](../Troubleshooting/Common_Errors/PodTerminating/pdb_blocking.md)** — разбор типовых инцидентов и алгоритмы восстановления.
* **[Cluster Autoscaler](./cluster_autoscaler_detailed.md)** — учет бюджетов доступности при сокращении пула серверов.
* **[Descheduler](./descheduler.md)** — учет PDB стратегиями балансировки и выселения подов.
* **[PriorityClass](../Concepts/priorityclass.md)** — взаимодействие вытеснения по приоритету с бюджетами доступности.
* **[Лимиты ресурсов и QoS](../Scheduling/qos_limit_and_requests.md)** — влияние исчерпания ресурсов узла на эвикцию.
* **[Taints и Tolerations](../Scheduling/taints_and_tolerations.md)** — различие мягкого выселения через PDB и жесткого через Taint NoExecute.
* **[Vertical Pod Autoscaler (VPA)](./vpa_detailed.md)** — влияние режимов обновления контейнеров на доступность подов.

### Внешние ссылки

* [Официальная документация Kubernetes: PodDisruptionBudget](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
* [Официальная концепция Kubernetes: Pod Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
* [Руководство по безопасному выводу узлов из обслуживания (Safely Drain a Node)](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
