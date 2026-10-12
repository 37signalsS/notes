# HPA + PriorityClass + Preemption: взаимодействие при масштабировании

**Актуально для:** Kubernetes 1.28–1.35 (API autoscaling/v2, scheduling.k8s.io/v1, policy/v1)

Взаимодействие Horizontal Pod Autoscaler (HPA), классов приоритета (PriorityClass) и механизма вытеснения (Preemption) определяет стабильность и отказоустойчивость сервисов в условиях исчерпания аппаратных ресурсов кластера. В bare-metal и on-premise инфраструктурах вычислительная емкость фиксирована, поэтому при внезапных всплесках нагрузки HPA не может рассчитывать на мгновенное добавление физических серверов. Единственным способом гарантировать SLA критических сервисов становится принудительное перераспределение локальных ресурсов узлов за счет вытеснения менее приоритетных задач.

---

## Определения

**PriorityClass** — глобальный (non-namespaced) объект Kubernetes (`scheduling.k8s.io/v1`), сопоставляющий текстовое имя класса с 32-битным целочисленным значением приоритета (от `-2147483648` до `1000000000`). Значения выше 1 миллиарда зарезервированы под системные компоненты (`system-cluster-critical`, `system-node-critical`).

**Preemption (Вытеснение)** — логика планировщика (`kube-scheduler`), запускаемая на этапе `PostFilter`, если под с более высоким приоритетом не может быть размещен на узлах из-за дефицита ресурсов. Планировщик принудительно удаляет (посылает `SIGTERM`) поды с более низким приоритетом на выбранном узле, освобождая ресурсы под высокоприоритетную нагрузку.

**Eviction (Выселение)** — процесс аварийного завершения подов агентом `kubelet` на конкретном узле при превышении жестких порогов давления ресурсов (Node Pressure: память, диск, дескрипторы файлов). В отличие от preemption, выселение выполняется демоном узла, руководствуется классами качества обслуживания (QoS: `BestEffort` → `Burstable` → `Guaranteed`) и не учитывает численный `PriorityClass` в качестве первичного фактора.

**PodDisruptionBudget (PDB)** — объект Kubernetes (`policy/v1`), задающий бюджет допустимых одновременных добровольных прерываний (`minAvailable` или `maxUnavailable`) для набора реплик.

**NominatedNodeName** — поле в статусе пода (`status.nominatedNodeName`), выставляемое планировщиком в момент инициации вытеснения жертв на конкретном узле. Резервирует вычислительную емкость узла за ожидающим подом, блокируя ее использование другими поступающими подами с более низким приоритетом.

**PreemptionPolicy** — параметр PriorityClass (`PreemptLowerPriority` по умолчанию или `Never`), определяющий, имеет ли право под с данным классом вытеснять поды с более низким приоритетом при дефиците емкости.

**Preemption Thrashing (Флаппинг вытеснения)** — циклическое состояние деградации кластера, при котором всплеск нагрузки вызывает масштабирование высокоприоритетного Deployment вверх через HPA, массовое уничтожение фоновых задач, быстрое падение нагрузки, масштабирование вниз и повторный запуск фоновых задач по кругу.

---

## Архитектура и принцип работы

### Жизненный цикл взаимодействия HPA, планировщика и вытеснения

В инфраструктуре с фиксированным пулом физических серверов (on-premise / bare-metal) связка HPA и Preemption работает по следующему каскадному циклу:

```
                  ┌──────────────────────────────────────────┐
                  │ Всплеск метрики (CPU / Memory / Custom)  │
                  └────────────────────┬─────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────┐
                  │ HPA рассчитывает desiredReplicas         │
                  │ и патчит /scale Deployment               │
                  └────────────────────┬─────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────┐
                  │ ReplicaSet создает новые поды            │
                  │ Поды попадают в очередь scheduler        │
                  └────────────────────┬─────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        [Емкость узлов свободна]              [Ресурсы кластера исчерпаны]
                    │                                     │
                    ▼                                     ▼
           Запуск на узле                   kube-scheduler PostFilter:
           Статус: Running                  Поиск узла для Preemption
                                                          │
                               ┌──────────────────────────┴──────────────────────────┐
                               ▼                                                     ▼
                  [Жертвы найдены]                                      [Жертвы недоступны]
                               │                                                     │
                               ▼                                                     ▼
                  status.nominatedNodeName                              Под остается в Pending
                  SIGTERM жертвам (Grace Period)                        Event: FailedScheduling
                               │
                               ▼
                  Жертвы завершились → Очистка ресурсов
                  Высокоприоритетный под запущен (Running)
```

1. **HPA Control Loop:** Контроллер HPA каждые `--horizontal-pod-autoscaler-sync-period` (по умолчанию 15 секунд) сравнивает текущую утилизацию с таргетом и обновляет `spec.replicas` в объекте `Deployment`.
2. **Создание подов:** Контроллер `ReplicaSet` генерирует манифесты подов, наследующих `priorityClassName` из шаблона (`podTemplateSpec`).
3. **Очередь планировщика:** Поды поступают в очередь `activeQ` планировщика. Планировщик сортирует очередь строго по полю `spec.priority`: высокоприоритетные поды рассматриваются первыми независимо от времени их создания.
4. **Фильтрация (Filter Plugin):** Планировщик проверяет соответствие предикатам на всех узлах (Node Affinity, Taints/Tolerations, CPU/RAM requests, порты узла). Если ни один узел не обладает достаточными нераспределенными `requests`, стандартное назначение невозможно.
5. **Пост-фильтрация и вытеснение (PostFilter / DefaultPreemption):** Планировщик проверяет, включен ли у пода `preemptionPolicy: PreemptLowerPriority`. Если да, запускается алгоритм выбора жертв.
6. **Резервирование узла (`NominatedNodeName`):** Планировщик выбирает узел, устанавливает в статусе ожидающего пода `status.nominatedNodeName = "<node-name>"` и инициирует удаление жертв через Kubernetes API.
7. **Временной разрыв (Grace Period Gap):** Жертвы переходят в состояние `Terminating` и выполняют завершение в течение `terminationGracePeriodSeconds`. В этот период ресурсы узла физически еще заняты, а высокоприоритетный под ожидает в фазе `Pending`.

### Алгоритм выбора жертв (Victim Selection Algorithm)

Планировщик минимизирует разрушительное воздействие на кластер, следуя детерминированным правилам:

1. **Только более низкий приоритет:** Под никогда не вытесняет поды с равным или более высоким `spec.priority`.
2. **Минимизация числа жертв:** Планировщик ищет комбинацию подов минимального суммарного веса и количества, удаление которых освободит ровно необходимый объем CPU и памяти для размещения входящего пода.
3. **Локальность вытеснения:** Вытеснение происходит строго в пределах одного узла. Планировщик не выполняет межхостовое вытеснение (Cross-Node Preemption), даже если удаление пода на соседнем узле сняло бы ограничение `podAntiAffinity`.
4. **Учет ограничений планирования:** После гипотетического удаления жертв узел обязан полностью удовлетворять всем предикатам планирования входящего пода (включая taints, affinities и topology spread constraints).

### Взаимодействие Preemption и PodDisruptionBudget (PDB)

Критический нюанс архитектуры Kubernetes заключается в том, что планировщик учитывает PDB при вытеснении **по принципу наилучшего старания (Best Effort)**:

| Сценарий вытеснения | Поведение kube-scheduler | Статус PDB |
|---|---|---|
| На узле A есть жертвы, удаление которых не нарушает PDB | Планировщик выбирает узел A | PDB полностью соблюден (`disruptionsAllowed >= 1`) |
| На узле A удаление нарушает PDB, но на узле B жертвы имеют более высокий приоритет, однако не нарушают PDB | Планировщик выберет узел B, минимизируя ущерб доступности | PDB соблюден |
| В кластере **нет ни одного узла**, где можно разместить высокоприоритетный под без нарушения PDB | **Планировщик принудительно вытесняет поды, нарушая PDB!** | **PDB нарушается (Best-Effort Fallback)** |

> [!WARNING]
> PDB защищает от добровольного удаления при операциях обслуживания (например, `kubectl drain`), но **не гарантирует абсолютный иммунитет** при вытеснении высокоприоритетными подами. Если свободных ресурсов нет, планировщик пожертвует доступностью низкоприоритетного приложения ради запуска критического сервиса.

### Различия между Preemption и Kubelet Eviction

Смешение этих понятий на уровне эксплуатации приводит к неверной диагностике сбоев:

| Характеристика | Preemption (Планировщик) | Eviction (Kubelet Node Pressure) |
|---|---|---|
| **Исполнитель** | `kube-scheduler` на Control Plane | `kubelet` на Worker Node |
| **Триггер** | Невозможность запланировать новый под из-за нехватки `requests` | Реальное физическое исчерпание RAM/диска на узле (`usage` превысил порог) |
| **Критерий выбора жертв** | Исключительно `spec.priority` (PriorityClass) | Классы качества обслуживания QoS (`BestEffort` → `Burstable` → `Guaranteed`) |
| **Учет QoS** | Не учитывается (под `Guaranteed` с низким приоритетом будет вытеснен) | Основной фактор ранжирования |
| **Статус пода** | Завершается штатно с кодом 143 (`SIGTERM`) или переходит в `Evicted` | Статус `Failed`, причина `Evicted` |
| **PDB** | Учитывается по принципу Best Effort | Игнорируется (вынужденный аварийный сбой) |

### Невытесняющие приоритеты (`preemptionPolicy: Never`)

Начиная с Kubernetes 1.24 (стабильный статус), в объекте `PriorityClass` поддерживается директива `preemptionPolicy: Never`.

* **Механизм:** Под с таким классом получает высокий численный вес `value`, что позволяет ему переместиться в начало очереди `Pending` планировщика и опередить обычные поды. Однако он **никогда не инициирует удаление** уже запущенных подов на узлах.
* **Применение:** Идеально для фоновых обработчиков, аналитических задач и пакетных воркеров высокой важности, которые должны стартовать сразу же, как только на bare-metal узлах естественным образом освободится место, но не имеют права прерывать выполнение текущих рабочих процессов.

### Защита от монополизации емкости: ResourceQuota по PriorityClass

В on-premise среде неконтролируемое масштабирование высокоприоритетного сервиса через HPA может полностью очистить кластер от всех остальных полезных нагрузок. Для изоляции ресурсов применяется `ResourceQuota` с селектором областей (`scopeSelector`):

```
┌─────────────────────────────────────────────────────────────────┐
│                     Namespace: payment-prod                     │
│                                                                 │
│  ResourceQuota (Scope: PriorityClass = prod-critical)           │
│  Hard Limits: requests.cpu = 64 Cores, requests.memory = 128Gi  │
│                                                                 │
│  ┌─────────────────────────┐      ┌──────────────────────────┐  │
│  │ HPA: maxReplicas = 40   │      │ При попытке создать      │  │
│  │ Каждая реплика = 2 CPU  │ ───► │ реплику №33:             │  │
│  │ 32 реплики = 64 CPU     │      │ Quota Exceeded (403 API) │  │
│  └─────────────────────────┘      │ Батч-поды защищены!      │  │
│                                   └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии и конфигурация

### Сценарий 1: Проектирование иерархии PriorityClass для Bare-Metal кластера

Базовая конфигурация классов приоритета для production-инфраструктуры, исключающая пересечение диапазонов и фиксирующая политики вытеснения:

```yaml
# 1. Системные ингрессы и балансировщики уровня приложения
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: prod-critical
value: 100000000
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: "Критичные production сервисы с жестким SLA доступности (Ingress, Billing, Auth)"
---
# 2. Основные бизнес-микросервисы компании
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: prod-high
value: 10000000
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: "Стандартные пользовательские API и веб-сервисы"
---
# 3. Дефолтный приоритет кластера (для нагрузок без указания класса)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: default-workload
value: 1000
preemptionPolicy: PreemptLowerPriority
globalDefault: true
description: "Глобальный приоритет по умолчанию для всех обычных приложений"
---
# 4. Фоновые пакетные задачи (Batch, ETL, генерация отчетов)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: batch-low
value: 100
preemptionPolicy: Never
globalDefault: false
description: "Фоновые воркеры и пакетные задачи. Не вытесняют другие поды при масштабировании."
```

### Сценарий 2: Критичный API Deployment под управлением HPA с защитой от Preemption Churn

Конфигурация масштабируемого сервиса с высоким приоритетом. Для предотвращения флаппинга вытеснения в манифесте HPA настраивается окно стабилизации `stabilizationWindowSeconds` на уменьшение и ограничение скорости нарастания реплик:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-gateway
  namespace: finance
  labels:
    app.kubernetes.io/name: payment-gateway
spec:
  replicas: 4
  selector:
    matchLabels:
      app.kubernetes.io/name: payment-gateway
  template:
    metadata:
      labels:
        app.kubernetes.io/name: payment-gateway
    spec:
      priorityClassName: prod-critical
      terminationGracePeriodSeconds: 30
      containers:
        - name: gateway
          image: internal-registry.local/finance/gateway:v2.4.1
          resources:
            requests:
              cpu: 1000m
              memory: 2Gi
            limits:
              cpu: 2000m
              memory: 4Gi
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: payment-gateway-hpa
  namespace: finance
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: payment-gateway
  minReplicas: 4
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 75
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 50
          periodSeconds: 30
        - type: Pods
          value: 4
          periodSeconds: 30
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 20
          periodSeconds: 60
      selectPolicy: Min
```

### Сценарий 3: Фоновая пакетная обработка с быстрым освобождением ресурсов

Фоновые сервисы должны уступать место высокоприоритетным нагрузкам без длительной задержки. Для этого устанавливается минимальный `terminationGracePeriodSeconds`, корректный обработчик `SIGTERM` в коде и `preemptionPolicy: Never` в PriorityClass:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: report-generator
  namespace: analytics
spec:
  replicas: 8
  selector:
    matchLabels:
      app.kubernetes.io/name: report-generator
  template:
    metadata:
      labels:
        app.kubernetes.io/name: report-generator
    spec:
      priorityClassName: batch-low
      # Короткий grace period минимизирует время нахождения критичного пода в Pending
      terminationGracePeriodSeconds: 10
      containers:
        - name: worker
          image: internal-registry.local/analytics/worker:v1.12.0
          resources:
            requests:
              cpu: 1000m
              memory: 2Gi
            limits:
              cpu: 1500m
              memory: 3Gi
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: report-generator-pdb
  namespace: analytics
spec:
  # Разрешает вытеснение до 75% реплик при необходимости
  maxUnavailable: 75%
  selector:
    matchLabels:
      app.kubernetes.io/name: report-generator
```

### Сценарий 4: Ограничение емкости через ResourceQuota по PriorityClass

Предотвращает сценарий, когда разросшийся по HPA микросервис вытесняет все фоновые процессы в кластере:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: prod-critical-quota
  namespace: finance
spec:
  hard:
    requests.cpu: "24"
    requests.memory: 48Gi
    pods: "20"
  scopeSelector:
    matchExpressions:
      - operator: In
        scopeName: PriorityClass
        values:
          - prod-critical
```

---

## Операции и команды

Сводка команд администратора для проверки очередей планирования, статусов вытеснения и состояния HPA.

### Инспекция классов приоритета и распределения подов

```bash
# Просмотр всех PriorityClass в кластере с сортировкой по значению
kubectl get priorityclasses --sort-by=.value
# → NAME              VALUE        GLOBAL-DEFAULT   PREEMPTION-POLICY       AGE
# → batch-low         100          false            Never                   14d
# → default-workload  1000         true             PreemptLowerPriority    14d
# → prod-high         10000000     false            PreemptLowerPriority    14d
# → prod-critical     100000000    false            PreemptLowerPriority    14d

# Просмотр всех подов с их классами приоритета и численным весом
kubectl get pods -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,PRIORITY_CLASS:.spec.priorityClassName,PRIORITY:.spec.priority,NODE:.spec.nodeName,STATUS:.status.phase'
# → NAMESPACE   NAME                                PRIORITY_CLASS   PRIORITY    NODE      STATUS
# → finance     payment-gateway-6bb98499c-5x8q2     prod-critical    100000000   node-01   Running
# → analytics   report-generator-55c8b746d-9k12z    batch-low        100         node-01   Running
# → default     nginx-frontend-77649b6d8-lp90a      default-workload 1000        node-02   Running
```

### Диагностика процесса вытеснения (Preemption in Progress)

```bash
# Поиск подов, находящихся в процессе вытеснения с назначенным кандидатом узла (nominatedNodeName)
kubectl get pods -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,PRIORITY:.spec.priority,NOMINATED_NODE:.status.nominatedNodeName,STATUS:.status.phase' | grep -v '<none>'
# → NAMESPACE   NAME                                PRIORITY    NOMINATED_NODE   STATUS
# → finance     payment-gateway-6bb98499c-d49kz     100000000   node-01          Pending

# Детальный просмотр событий планировщика для ожидающего пода
kubectl describe pod payment-gateway-6bb98499c-d49kz -n finance | grep -A 10 Events:
# → Events:
# →   Type     Reason             Age   From                Message
# →   ----     ------             ----  ----                -------
# →   Warning  FailedScheduling   45s   default-scheduler   0/6 nodes are available: 6 Insufficient cpu. preemption: 0/6 nodes are available: 1 Preemption is not helpful, 5 Preemption is helpful.
# →   Normal   Preempted          44s   default-scheduler   by finance/payment-gateway-6bb98499c-d49kz on node node-01: pod analytics/report-generator-55c8b746d-9k12z terminated

# Проверка подов-жертв в состоянии Terminating на целевом узле
kubectl get pods -n analytics --field-selector spec.nodeName=node-01
# → NAME                               READY   STATUS        RESTARTS   AGE
# → report-generator-55c8b746d-9k12z   1/1     Terminating   0          18m
```

### Мониторинг метрик kube-scheduler и Prometheus

```bash
# Получение счетчиков вытеснения напрямую из API планировщика
kubectl get --raw /metrics | grep -E "^scheduler_preemption_(attempts|victims)_total"
# → scheduler_preemption_attempts_total 42
# → scheduler_preemption_victims_total 89
```

Запросы PromQL для дашбордов и алертинга:

```promql
# 1. Частота попыток вытеснения в секунду по кластеру
rate(scheduler_preemption_attempts_total[5m])

# 2. Суммарное количество уничтоженных подов-жертв за последний час
increase(scheduler_preemption_victims_total[1h])

# 3. Количество подов в Pending с ненулевым приоритетом более 2 минут
sum by (namespace) (
  kube_pod_status_phase{phase="Pending"} 
  * on(pod, namespace) group_left(priority_class) 
  kube_pod_info{priority_class!=""}
) > 0
```

---

## Диагностика и устранение неполадок

| Проблема / Симптом | Первопричина | Метод диагностики | Способ устранения |
|---|---|---|---|
| Высокоприоритетный под висит в `Pending`, поле `nominatedNodeName` заполнено | Поды-жертвы долго выполняют graceful shutdown | `kubectl get pod <victim> -o yaml \| grep terminationGracePeriodSeconds` | Уменьшить `terminationGracePeriodSeconds` у низкоприоритетных приложений (до 10–15 сек); проверить обработку `SIGTERM` в коде жертвы |
| Под висит в `Pending`, вытеснение не запускается (`0/N nodes available, Preemption is not helpful`) | Нарушение других предикатов: `podAntiAffinity`, `nodeSelector`, `Tolerations` | `kubectl describe pod <name>` раздел `Events: FailedScheduling` | Проверить жесткие правила `podAntiAffinity`. Заменить `requiredDuringScheduling` на `preferredDuringScheduling` |
| HPA рассчитал увеличение реплик, но новые поды не создаются | Достигнут лимит `ResourceQuota` по данному PriorityClass в namespace | `kubectl describe resourcequota -n <ns>` | Увеличить квоту CPU/RAM для класса `prod-critical` в `ResourceQuota` или скорректировать `maxReplicas` в HPA |
| Preemption Churn (массовый флаппинг подов при автоскейлинге) | Слишком быстрое масштабирование вниз и резкие скачки вверх у HPA | Анализ графиков `rate(scheduler_preemption_victims_total[1m])` и `kube_deployment_status_replicas` | Настроить `behavior.scaleDown.stabilizationWindowSeconds: 300` и ограничить `scaleUp.policies` по шагам |
| Низкоприоритетный сервис потерял доступность вопреки PDB | Поведение Best-Effort: при отсутствии альтернатив планировщик нарушил PDB | `kubectl describe pdb <pdb-name>` и лог планировщика `journalctl -u kube-scheduler` | Изолировать критичные сервисы на выделенный пул физических узлов с помощью Taints/Tolerations |
| Под с `priorityClassName` имеет фактический приоритет `0` | Класс приоритета был создан после создания пода или имя класса написано с ошибкой | `kubectl get pod <name> -o jsonpath='{.spec.priority}'` | Пересоздать под (`kubectl rollout restart deployment/<name>`). Проверить имя класса через `kubectl get priorityclass` |

---

## Рекомендации и лучшие практики

1. **Изоляция критических контуров через Taints и Tolerations:**
   Вместо того чтобы разрешать HPA вытеснять любые нагрузки по всему bare-metal кластеру, выделите группу физических серверов под критические сервисы (например, узел с taint `workload=critical:NoSchedule`). Добавьте соответствующий toleration только высокоприоритетным подам.
2. **Всегда используйте `preemptionPolicy: Never` для фоновых очередей:**
   Пакетные задачи (ETL, обработка логов, бэкапы) должны быстро стартовать при появлении свободных ядер, но их вытеснение приводит к повторному прогону задач с нуля и бессмысленной трате CPU/дискового ввода-вывода.
3. **Разделяйте численные веса с запасом на будущее:**
   Задавайте шаг значений PriorityClass не менее `10 000` или `1 000 000` (например: 100, 10 000, 1 000 000, 100 000 000). Это позволяет добавлять промежуточные классы без необходимости миграции существующих сервисов.
4. **Контролируйте `terminationGracePeriodSeconds` у жертв:**
   Время, которое критический под проводит в ожидании освобождения узла, напрямую равно времени остановки жертвы. Для всех низкоприоритетных сервисов grace period не должен превышать 10–15 секунд.
5. **Обязательное окно стабилизации для HPA (`stabilizationWindowSeconds`):**
   При использовании агрессивного вытеснения запрещено использовать короткие окна scale-down. Задержка в 300–600 секунд предотвращает каскадный перезапуск фоновых подов при кратковременных просадках нагрузки.
6. **Ограничивайте `maxReplicas` реальной емкостью кластера:**
   Значение `maxReplicas` в HPA должно рассчитываться исходя из допустимой доли утилизации оборудования, чтобы один сбойный или зафлуженный сервис не смог вытеснить весь системный стек мониторинга и логирования.
7. **Алертинг на метрику вытеснений:**
   Любое срабатывание `scheduler_preemption_victims_total` в steady-state режиме bare-metal кластера — это сигнал для SRE о дефиците вычислительных мощностей или неоптимальном планировании сайзинга подов.

---

## Дополнительная информация

- **[PriorityClass — приоритеты подов](../Concepts/priorityclass.md)** — архитектура очередей планировщика, системные классы и алгоритмы PostFilter.
- **[HPA: Основы](HPA/index.md)** — базовая архитектура Horizontal Pod Autoscaler, Resource Metrics API и жизненный цикл петли управления.
- **[HPA: Продвинутые темы](HPA/hpa_advanced.md)** — детальная настройка блока behavior, формулы расчета реплик и стабилизация масштабирования.
- **[Pod Disruption Budget](pod_disruption_budget.md)** — контракты доступности сервисов, защита от добровольных прерываний и взаимодействие с Eviction API.
- **[Autoscaling в On-Premise / Bare-Metal](on_premise_autoscaling.md)** — специфика горизонтального и вертикального масштабирования на собственных физических серверах.
- **[Descheduler](descheduler.md)** — дефрагментация узлов, балансировка распределения подов и устранение перекосов после массовых вытеснений.
- **[Диагностика Pod Pending](../Troubleshooting/Common_Errors/pod_pending/diagnostics.md)** — пошаговое руководство по расследованию причин застревания подов в фазе планирования.
