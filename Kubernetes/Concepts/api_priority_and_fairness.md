# API Priority and Fairness (APF)

**Актуально для:** Kubernetes 1.29 - 1.31 (API `flowcontrol.apiserver.k8s.io/v1`)

---

## 1. Определения

*   **API Priority and Fairness (APF)** — встроенный в `kube-apiserver` механизм контроля перегрузок и планирования запросов, разделяющий входящий трафик на логические потоки, приоритизирующий их и обеспечивающий защиту от взаимной блокировки (fairness). Перешел в статус General Availability (GA) в Kubernetes 1.29.
*   **FlowSchema (FS)** — ресурс Kubernetes (`flowcontrol.apiserver.k8s.io/v1`), определяющий правила классификации входящих HTTP/gRPC-запросов (по субъекту, ресурсу, глаголу действия) и направляющий их в определенный уровень приоритета.
*   **PriorityLevelConfiguration (PLC)** — ресурс Kubernetes, определяющий параметры выделения вычислительных ресурсов (concurrency shares), поведение очередей и лимиты для одной логической группы приоритета.
*   **Concurrency Seats (Посадочные места)** — дискретные единицы вычислительной емкости API-сервера. Запрос занимает одно или несколько мест на все время своей обработки.
*   **Work Estimating (Оценка трудоемкости)** — механизм динамического расчета количества мест (`seats`), которые требует запрос в зависимости от типа операции (например, точечный `GET` требует 1 место, а тяжелый `LIST` — несколько мест с учетом прогнозируемого объема выборки).
*   **Shuffled Sharding (Перемешанное шардирование)** — вероятностный алгоритм изоляции очередей, распределяющий запросы одного клиента по небольшому подмножеству очередей из общего пула, что минимизирует вероятность коллизии с запросами других клиентов.
*   **Distinguisher (Дискриминатор потока)** — атрибут запроса (`ByUser` или `ByNamespace`), используемый алгоритмом Shuffled Sharding для разделения запросов внутри одного уровня приоритета.
*   **Fair Queuing (Справедливая очередь)** — модифицированный алгоритм взвешенной справедливой очереди (Weighted Fair Queueing / Virtual Time), определяющий порядок извлечения запросов из очередей для передачи на выполнение.
*   **Borrowing & Lending (Заимствование и предоставление)** — механизм совместного использования неиспользуемой емкости: уровень с избытком свободных мест временно «одалживает» их перегруженному уровню в пределах заданных процентов.

---

## 2. Основные концепции и архитектура

### Место APF в конвейере kube-apiserver

APF располагается непосредственно между этапом авторизации (RBAC) и этапом Admission Control. Это означает, что неаутентифицированные или запрещенные политиками безопасности запросы отсекаются до попадания в очереди APF и не расходуют вычислительные лимиты:

```
Входящий HTTP-запрос
         │
         ▼
┌──────────────────┐
│  Authentication  │  → Проверка сертификата, токена (401 Unauthorized)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Authorization   │  → RBAC, NodeRestriction (403 Forbidden)
└────────┬─────────┘
         │
         ▼
┌────────────────────────────────────────────────────────┐
│             API Priority and Fairness (APF)            │
│                                                        │
│  1. Matching FlowSchema (сверху вниз по Precedence)    │
│  2. Назначение PriorityLevelConfiguration              │
│  3. Расчет Work Estimating (Seats)                     │
│  4. Shuffled Sharding (выбор очереди по хэшу)          │
│  5. Ожидание в очереди (Fair Queuing) или Reject       │
└────────┬───────────────────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│ Admission Control│  → Mutating & Validating Webhooks
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   etcd Storage   │  → Чтение / запись данных
└──────────────────┘
```

### Расчет суммарного пула конкурентности

Распространенное заблуждение состоит в том, что APF полностью отменяет флаги API-сервера `--max-requests-inflight` и `--max-mutating-requests-inflight`.

В действительности сумма этих флагов формирует **Server Concurrency Limit** (общую емкость доступных мест):

$$\text{TotalSeats} = \text{max-requests-inflight} + \text{max-mutating-requests-inflight}$$

По умолчанию в стандартной конфигурации `kubeadm`:
* `--max-requests-inflight`: 400
* `--max-mutating-requests-inflight`: 200
* **Итоговый пул (TotalSeats)**: 600 мест на инстанс `kube-apiserver`.

Каждый уровень `PriorityLevelConfiguration` с типом `Limited` получает гарантированную номинальную долю мест (`Nominal Concurrency Limit`):

$$\text{NominalSeats}(P) = \left\lfloor \text{TotalSeats} \times \frac{\text{nominalConcurrencyShares}(P)}{\sum_{i} \text{nominalConcurrencyShares}(i)} \right\rfloor$$

### Механизм Borrowing и Lending (Заимствование мест)

Для исключения ситуаций, когда дорогостоящие вычислительные ресурсы API-сервера простаивают, в версии API `flowcontrol.apiserver.k8s.io/v1` реализован механизм перераспределения мест:

* `spec.limited.lendablePercent`: процент от номинальных мест уровня, который разрешено отдавать другим уровням, если они не востребованы в текущий момент.
* `spec.limited.borrowingLimitPercent`: процент мест сверх собственного номинала, который данный уровень имеет право занять из общего фонда свободных мест.

Если уровень `workload-low` простаивает и имеет `lendablePercent: 50`, а уровень `workload-high` перегружен и имеет `borrowingLimitPercent: 50`, `workload-high` временно увеличивает свой лимит за счет ресурсов соседа, не допуская деградации приоритетного трафика.

### Алгоритм Shuffled Sharding

Для защиты от проблемы «шумного соседа» (noisy neighbor) внутри одного `PriorityLevelConfiguration` создается массив независимых очередей (параметр `queues`, например, 64 или 128).

```
Distinguisher (User: "operator-foo")
              │
              ▼ Хэширование SHA256
      [ Хэш-значение ]
              │
              ▼ Выбор Hand Size (например, 4 очереди)
  Очереди: [Q3, Q17, Q42, Q61] из 128
              │
              ▼ Определение наименее загруженной
          Выбрана: Q17
```

Вероятность того, что два разных клиента с одинаковым `PriorityLevelConfiguration` разделят в точности один и тот же набор очередей:

$$P = \frac{1}{\binom{\text{queues}}{\text{handSize}}} = \frac{\text{handSize}! \cdot (\text{queues} - \text{handSize})!}{\text{queues}!}$$

При `queues: 128` и `handSize: 8` число комбинаций составляет более **1,4 триллиона**, что снижает вероятность взаимной блокировки независимых пользователей практически до нуля.

### Встроенные (Built-in) ресурсы APF

При инициализации кластера Kubernetes автоматически создает системные уровни и схемы. Изменение их состава контролируется контроллером API-сервера; удаление системных объектов приводит к их автоматическому пересозданию.

#### Системные PriorityLevelConfiguration (v1)

| Имя | Тип | Shares | Queues | HandSize | Назначение |
|:---|:---|:---:|:---:|:---:|:---|
| `exempt` | Exempt | — | — | — | Критические запросы без ограничений и очередей (`system:masters`). |
| `system-leader-election` | Limited | 10 | 16 | 4 | Запросы блокировок Lease/ConfigMap/Endpoint для controller-manager и scheduler. |
| `node-high` | Limited | 40 | 64 | 4 | Срочные запросы kubelet (обновление Node Lease, Heartbeat). |
| `system` | Limited | 30 | 64 | 4 | Внутренние запросы системных контроллеров Kubernetes. |
| `workload-high` | Limited | 40 | 128 | 6 | Высокоприоритетные запросы рабочих нагрузок и операторов. |
| `workload-low` | Limited | 100 | 128 | 6 | Фоновые, пакетные и вспомогательные задачи. |
| `global-default` | Limited | 20 | 128 | 6 | Пользовательский интерактивный трафик (`kubectl`). |
| `catch-all` | Limited | 5 | 32 | 4 | Запасной уровень для несовпавших запросов (низкий приоритет). |

#### Системные FlowSchema

FlowSchema упорядочены по значению `matchingPrecedence` (от 1 до 10000; чем меньше число, тем выше приоритет совпадения):

| Precedence | Имя FlowSchema | PriorityLevel | Критерий совпадения |
|:---:|:---|:---|:---|
| 1 | `exempt` | `exempt` | Группа `system:masters` |
| 200 | `probes` | `exempt` | URL `/healthz`, `/livez`, `/readyz` |
| 1000 | `system-leader-election` | `system-leader-election` | Лидерские выборы контроллеров |
| 2000 | `system-node-high` | `node-high` | Обновление `leases` узлами в `kube-node-lease` |
| 3000 | `system-nodes` | `system` | Группа `system:nodes` (kubelet) |
| 4000 | `kube-controller-manager` | `workload-high` | Пользователь `system:kube-controller-manager` |
| 4000 | `kube-scheduler` | `workload-high` | Пользователь `system:kube-scheduler` |
| 8000 | `service-accounts` | `workload-low` | Все `system:serviceaccounts` |
| 9000 | `global-default` | `global-default` | Все аутентифицированные пользователи |
| 10000 | `catch-all` | `catch-all` | Все оставшиеся запросы (`*`) |

---

## 3. Практические сценарии и конфигурация

### Настройка базовых параметров в kube-apiserver (On-Prem / Bare-Metal)

Параметры конкурентности задаются в статическом манифесте контрольной панели `/etc/kubernetes/manifests/kube-apiserver.yaml` на каждом control plane узле:

```yaml
spec:
  containers:
  - command:
    - kube-apiserver
    - --enable-priority-and-fairness=true
    - --max-requests-inflight=800
    - --max-mutating-requests-inflight=400
```

> [!NOTE]
> При увеличении лимитов inflight-запросов пропорционально возрастает потребление оперативной памяти процессом `kube-apiserver` и увеличивается нагрузка на `etcd`. Для узлов с 8 CPU / 32 GB RAM типовые стабильные значения составляют 800/400 (суммарно 1200 мест).

---

### Сценарий 1: Изоляция «шумного» CI/CD или скрипта автоматизации

**Проблема:** Внешний пайплайн CI/CD или сервисный аккаунт запускает массовые `GET` и `LIST` запросы по всем неймспейсам, исчерпывая места в `workload-low` и замедляя работу продуктивных операторов.

**Решение:** Выделение отдельного `PriorityLevelConfiguration` с жестким отклонением при превышении очереди (`type: Reject`) и связывающей `FlowSchema` с высоким приоритетом совпадения.

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: cicd-isolated-level
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 15
    lendablePercent: 0
    borrowingLimitPercent: 0
    limitResponse:
      type: Reject
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: cicd-isolated-schema
spec:
  matchingPrecedence: 2500
  priorityLevelConfiguration:
    name: cicd-isolated-level
  distinguisherMethod:
    type: ByUser
  rules:
  - subjects:
    - kind: ServiceAccount
      serviceAccount:
        name: gitlab-runner-deployer
        namespace: cicd
    resourceRules:
    - verbs: ["*"]
      apiGroups: ["*"]
      resources: ["*"]
      clusterScope: true
```

---

### Сценарий 2: Многопользовательская изоляция тенантов с разделением по Namespace

**Проблема:** В одном кластере работают команды разработки `team-alpha` и `team-beta`. Некорректный оператор в пространстве имен одной команды не должен блокировать запросы другой команды.

**Решение:** Настройка FlowSchema с `distinguisherMethod: ByNamespace` и пулом очередей, позволяющим заимствовать незанятые места.

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: tenant-workload-level
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 50
    lendablePercent: 30
    borrowingLimitPercent: 20
    limitResponse:
      type: Queue
      queuing:
        queues: 64
        handSize: 4
        queueLengthLimit: 25
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: tenant-workload-schema
spec:
  matchingPrecedence: 5000
  priorityLevelConfiguration:
    name: tenant-workload-level
  distinguisherMethod:
    type: ByNamespace
  rules:
  - subjects:
    - kind: Group
      group:
        name: "developers-group"
    resourceRules:
    - verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
      apiGroups: ["", "apps", "batch"]
      resources: ["pods", "deployments", "jobs", "services", "configmaps"]
      namespaces: ["team-alpha", "team-beta"]
      clusterScope: false
```

---

### Сценарий 3: Защита кластера от неиндексированных тяжелых `LIST`-запросов

**Проблема:** Мониторинг или аудит-агенты вызывают периодический `LIST pods` без параметров во всем кластере, создавая сериализационную нагрузку в сотни мегабайт и блокируя etcd.

**Решение:** Перенаправление тяжелых операций чтения метаданных в строгий низкоприоритетный контур.

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: bulk-metadata-readers
spec:
  matchingPrecedence: 4500
  priorityLevelConfiguration:
    name: workload-low
  distinguisherMethod:
    type: ByUser
  rules:
  - subjects:
    - kind: ServiceAccount
      serviceAccount:
        name: cluster-audit-collector
        namespace: monitoring
    resourceRules:
    - verbs: ["list"]
      apiGroups: [""]
      resources: ["pods", "events", "nodes", "configmaps"]
      clusterScope: true
```

---

## 4. Операции и команды

### Инспекция состояния APF через kubectl

```bash
# Просмотр всех FlowSchema с их приоритетами и целевыми уровнями
kubectl get flowschemas -o custom-columns=NAME:.metadata.name,PRECEDENCE:.spec.matchingPrecedence,LEVEL:.spec.priorityLevelConfiguration.name,DISTINGUISHER:.spec.distinguisherMethod.type

# → NAME                     PRECEDENCE   LEVEL                    DISTINGUISHER
# → exempt                   1            exempt                   <none>
# → probes                   200          exempt                   <none>
# → system-leader-election   1000         system-leader-election   ByUser
# → cicd-isolated-schema     2500         cicd-isolated-level      ByUser
# → global-default           9000         global-default           ByUser
# → catch-all                10000        catch-all                <none>

# Просмотр уровней приоритета и выделенных shares
kubectl get prioritylevelconfigurations

# → NAME                     TYPE      NOMINAL-SHARES   QUEUES   HAND-SIZE   AGE
# → catch-all                Limited   5                32       4           120d
# → cicd-isolated-level      Limited   15               <none>   <none>      2d
# → exempt                   Exempt    <none>           <none>   <none>      120d
# → global-default           Limited   20               128      6           120d
# → system-leader-election   Limited   10               16       4           120d
# → workload-high            Limited   40               128      6           120d
# → workload-low             Limited   100              128      6           120d
```

### Диагностические эндпоинты API-сервера

`kube-apiserver` предоставляет административные debug-эндпоинты для анализа очередей в режиме реального времени:

```bash
# Дамп текущего состояния уровней приоритета (выполняемые запросы, используемые места)
kubectl get --raw /debug/api_priority_and_fairness/dump_priority_levels

# → PriorityLevelName, ActiveQueues, IsIdle, ExecutingRequests, WaitingRequests
# → exempt, 0, true, 0, 0
# → system-leader-election, 1, false, 2, 0
# → workload-high, 5, false, 18, 2
# → workload-low, 12, false, 40, 14

# Дамп очередей конкретного уровня с идентификаторами ожидающих запросов
kubectl get --raw /debug/api_priority_and_fairness/dump_queues | head -n 30
```

### Проверка метрик prometheus напрямую через raw API

```bash
# Проверка отклоненных запросов (HTTP 429) с разбивкой по схемам и причинам
kubectl get --raw /metrics | grep apiserver_flowcontrol_rejected_requests_total

# → apiserver_flowcontrol_rejected_requests_total{flow_schema="cicd-isolated-schema",priority_level="cicd-isolated-level",reason="concurrency-limit"} 142
# → apiserver_flowcontrol_rejected_requests_total{flow_schema="service-accounts",priority_level="workload-low",reason="queue-full"} 8

# Проверка текущего количества выполняющихся запросов по уровням
kubectl get --raw /metrics | grep apiserver_flowcontrol_current_executing_requests

# Проверка запросов, находящихся в очередях ожидания
kubectl get --raw /metrics | grep apiserver_flowcontrol_current_inqueue_requests
```

---

## 5. Диагностика и устранение неполадок

### Матрица типичных сбоев

| Симптом | Причина сбоя | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| Клиент получает `HTTP 429 Too Many Requests` с заголовком `Retry-After` | Исчерпан лимит мест или переполнена очередь APF | Проверить лейбл `reason` в метрике `apiserver_flowcontrol_rejected_requests_total` | Если `queue-full` — увеличить `queues`/`queueLengthLimit`. Если `concurrency-limit` — увеличить `nominalConcurrencyShares`. |
| Рост задержки (latency) API у системных подов при стабильном etcd | Системные запросы застряли в очередях `workload-low` или `catch-all` | Выполнить дамп `/debug/api_priority_and_fairness/dump_priority_levels` | Проверить `matchingPrecedence` FlowSchema: системный SA перехватывается кастомным правилом. |
| Срыв Leader Election (CrashLoopBackOff контроллеров из-за lease timeout) | Конкуренция за уровень `system-leader-election` | Проверить метрику `apiserver_flowcontrol_request_wait_duration_seconds{priority_level="system-leader-election"}` | Убедиться, что сторонние операторы не используют системный Lease-пул, или повысить shares уровня до 15–20. |
| Полная блокировка доступа `kubectl` для администраторов | Попытка ограничить группу `system:authenticated` правилом с низким `precedence` | `kubectl get flowschemas` от имени сертификата из `system:masters` | Удалить некорректную FlowSchema. Сертификат `cluster-admin` (группа `system:masters`) идет в `exempt` и не блокируется. |

### Анализ причин отклонения (Reason Codes)

В ответе HTTP 429 и метриках APF фиксируются три типа причин:

1. `queue-full`: глубина очереди для данного хэш-шарда достигла `queueLengthLimit`. Новые запросы отклоняются немедленно, предотвращая утечку памяти API-сервера.
2. `concurrency-limit`: уровень сконфигурирован с `limitResponse.type: Reject`, и в момент поступления запроса все номинальные места (и доступный лимит заимствования) были заняты.
3. `time-out`: запрос находился в очереди ожидания дольше допустимого времени ожидания клиента или максимального таймаута ожидания очереди (обычно 60 секунд).

---

### Мониторинг и алерты Prometheus

Готовый манифест `PrometheusRule` для продакшн-мониторинга APF:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: apf-slo-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
  - name: kubernetes-apf
    rules:
    - alert: KubeAPIRequestRejectionHigh
      expr: |
        sum by (priority_level, flow_schema, reason) (
          rate(apiserver_flowcontrol_rejected_requests_total[5m])
        ) > 0.5
      for: 2m
      labels:
        severity: warning
      annotations:
        summary: "Высокая частота отклонений APF (HTTP 429)"
        description: "FlowSchema '{{ $labels.flow_schema }}' (уровень '{{ $labels.priority_level }}') отклоняет запросы по причине '{{ $labels.reason }}'. Скорость: {{ $value | printf \"%.2f\" }} запр/сек."

    - alert: KubeAPIQueueWaitTimeHigh
      expr: |
        histogram_quantile(0.99, sum by (le, priority_level) (
          rate(apiserver_flowcontrol_request_wait_duration_seconds_bucket[5m])
        )) > 5
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Критическое время ожидания в очереди APF (P99 > 5с)"
        description: "Запросы в уровне приоритета '{{ $labels.priority_level }}' ожидают обработки в очереди более 5 секунд на 99-м перцентиле. Возможно истощение concurrency shares."

    - alert: KubeAPISystemLeaderElectionThrottling
      expr: |
        sum(rate(apiserver_flowcontrol_rejected_requests_total{priority_level="system-leader-election"}[5m])) > 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "Отклонение запросов Leader Election в APF"
        description: "Критические запросы выборов лидера контрольной панели отклоняются API-сервером. Риск сплит-брейна и деградации контроллеров."
```

---

## 6. Лучшие практики

1. **Не изменяйте системные FlowSchema с precedence < 1000.** Встроенные правила для `system:masters`, проб работоспособности (`/healthz`, `/livez`) и узловых lease-обновлений критически важны для стабильности кластера.
2. **Диапазон `matchingPrecedence` для пользовательских правил.** Назначайте кастомным схемам приоритет от `1500` до `8999`. Значения выше 9000 попадут под действие системных `global-default` и `service-accounts`.
3. **Осторожность с `clusterScope: true`.** При создании правил с широкими фильтрами (`verbs: ["*"]`, `resources: ["*"]`) обязательно ограничивайте субъект (`subjects`) конкретным ServiceAccount или пользователем. Не создавайте всеобъемлющих перехватывающих схем.
4. **Использование `limitResponse: Reject` для пакетных задач.** Фоновые воркеры, ETL-скрипты и сборщики метрик должны получать немедленный `Reject` при перегрузке, а не заполнять очереди ожидания, тратя память контроллера.
5. **Тюнинг соотношения `queues` и `handSize`.**
   * Для слабонагруженных уровней достаточно `queues: 16`, `handSize: 4`.
   * Для высоконагруженных уровней со множеством тенантов используйте `queues: 128`, `handSize: 6-8`.
   * Помните: `handSize` не должен превышать число очередей (`handSize <= queues`).
6. **Всегда оставляйте запасной буфер `exempt`.** Административные операции должны производиться с сертификатом группы `system:masters` (например, стандартный `/etc/kubernetes/admin.conf`), чтобы иметь возможность исправить поврежденную конфигурацию APF даже при полном коллапсе остальных очередей.
7. **Комплексная защита API.** APF регулирует параллелизм обработки запросов внутри `kube-apiserver`, но не защищает сетевой стек. Используйте APF в связке с аутентификацией mTLS, внешними балансировщиками с ограничением RPS (например, HAProxy/Nginx перед API-серверами) и лимитами `ResourceQuota`.

---

## 7. Дополнительная информация

*   **[Control Plane Architecture](control_plane_architecture.md)** — архитектура управляющих компонентов и конвейер прохождения запроса.
*   **[High Availability](../Base/high_availability.md)** — построение отказоустойчивой контрольной панели Kubernetes на Bare-Metal.
*   **[API Interaction](api_interaction.md)** — жизненный цикл и форматы ответов API-сервера (коды 429, 503, retry-логика).
*   **[Multi-tenancy](multi-tenancy.md)** — изоляция команд и ресурсов в многопользовательском кластере.
*   **[High Load Preparation](high_load_preparation.md)** — подготовка кластера к пиковым нагрузкам и предотвращение каскадных сбоев.
*   **[Kube API Server Monitoring](../MonitoringLogging/kube_apiserver_monitoring.md)** — детальный мониторинг метрик, SLI/SLO и производительности etcd.
*   **[ApiAccessForbidden Diagnostics](../Troubleshooting/Common_Errors/ApiAccessForbidden/diagnostics.md)** — трассировка и диагностика ошибок 403 и 429.
