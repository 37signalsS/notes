# PriorityClass — приоритеты подов

**Актуально для:** Kubernetes 1.30–1.35+

---

## Определения

*   **PriorityClass (класс приоритета)** — объект API Kubernetes (`scheduling.k8s.io/v1`), определяющий числовой вес (приоритет) пода и политику его вытеснения. Объект не привязан к пространствам имен (cluster-scoped).
*   **Приоритет пода (`spec.priority`)** — вычисленное 32-битное целое число со знаком, фиксируемое в манифесте пода admission-контроллером при создании на основе связанного `PriorityClass`.
*   **Вытеснение (Preemption)** — механизм планировщика (`kube-scheduler`), принудительно удаляющий поды с более низким приоритетом с узла для освобождения вычислительных ресурсов (CPU, Memory) под размещение пода с более высоким приоритетом.
*   **Поды-жертвы (Victim Pods)** — запущенные поды с меньшим приоритетом, выбранные планировщиком для завершения (eviction) ради освобождения емкости узла.
*   **Номинированный узел (`status.nominatedNodeName`)** — поле в статусе пода, указывающее на узел, зарезервированный планировщиком для пода-кандидата на время завершения работы подов-жертв.
*   **Очереди планировщика (Scheduling Queues)** — внутренние структуры `kube-scheduler` (`activeQ`, `backoffQ`, `unschedulableQ`), определяющие порядок обработки подов.
*   **Политика вытеснения (`preemptionPolicy`)** — параметр `PriorityClass`, определяющий, имеет ли право под вытеснять другие поды (`PreemptLowerPriority`) или только занимает приоритетное место в очереди без вытеснения (`Never`).
*   **Глобальный дефолт (`globalDefault`)** — флаг, указывающий на автоматическое назначение данного класса всем создаваемым подам, у которых не задан `priorityClassName`.
*   **Выселение узлом (Kubelet Eviction)** — процесс завершения подов агентом `kubelet` при достижении критических порогов локальных ресурсов узла (MemoryPressure, DiskPressure, PIDPressure). В отличие от Preemption, оперирует классами QoS и фактическим потреблением.
*   **Pod Disruption Budget (PDB)** — объект защиты доступности сервиса (`policy/v1`), ограничивающий количество одновременно недоступных реплик при добровольных прерываниях, включая вытеснение планировщиком.

---

## Архитектура и принцип работы

### Роль PriorityClass в планировании

`PriorityClass` оперирует на двух критических этапах жизненного цикла планирования:

1.  **Порядок в очереди планирования:** Определение положения пода во внутренних структурах `kube-scheduler`.
2.  **Вытеснение ресурсов (Preemption):** Освобождение ресурсов на узлах при отсутствии подходящей емкости в точке расширения `PostFilter`.

```
                    Создание Pod (spec.priorityClassName)
                                   │
                                   ▼
                 ┌───────────────────────────────────┐
                 │    Priority Admission Plugin      │
                 │  - резолвит PriorityClass         │
                 │  - заполняет spec.priority        │
                 └─────────────────┬─────────────────┘
                                   │
                                   ▼
                 ┌───────────────────────────────────┐
                 │       kube-scheduler activeQ      │
                 │  (сортировка по spec.priority)    │
                 └─────────────────┬─────────────────┘
                                   │
                                   ▼
                            Scheduling Cycle
                      (PreFilter ──► Filter ──► Score)
                                   │
                   ┌───────────────┴───────────────┐
             Узел найден?                     Узел НЕ найден
                   │                               │
                   ▼                               ▼
             Binding Cycle               PostFilter (Preemption)
        (Reserve ──► PreBind             - выбор жертв (PDB check)
         ──► Bind ──► PostBind)          - nomination (nominatedNodeName)
                                         - удаление подов-жертв
```

### Жизненный цикл приоритета и контроллер допуска

1.  При создании пода (через Deployment, StatefulSet или напрямую) admission-контроллер `Priority` перехватывает запрос:
    *   Если поле `spec.priorityClassName` заполнено, контроллер находит соответствующий `PriorityClass` и копирует его `value` в поле `spec.priority`.
    *   Если указанный `priorityClassName` не существует в кластере, запрос на создание пода **немедленно отклоняется с ошибкой**.
    *   Если поле `spec.priorityClassName` не указано, проверяется наличие класса с `globalDefault: true`. При его наличии под получает параметры дефолтного класса.
    *   Если дефолтного класса нет, `spec.priorityClassName` остается пустым, а `spec.priority` выставляется в `0`.
2.  **Иммутабельность:**
    *   Поле `spec.priority` у работающего пода неизменяемо. Смена приоритета возможна только через удаление и повторное создание пода.
    *   Поля `value` и `preemptionPolicy` внутри созданного `PriorityClass` также **неизменяемы (immutable)**. Любое изменение шкалы требует создания нового класса либо пересоздания существующего.

### Внутренние очереди kube-scheduler

Внутри планировщика поды распределяются по трем очередям:

*   **`activeQ` (PriorityQueue):** Очередь подов, готовых к планированию. Упорядочена строго по убыванию `spec.priority`. Поды с равным приоритетом ранжируются по времени создания.
*   **`backoffQ`:** Очередь подов, попытка планирования которых завершилась неудачей. Поды удерживаются здесь в течение экспоненциально растущего интервала (`backoffDuration`), после чего возвращаются в `activeQ`.
*   **`unschedulableQ`:** Хранилище подов, которые не могут быть запланированы текущим состоянием кластера (например, нехватка ресурсов на всех узлах). Поды перемещаются обратно в `activeQ` только при возникновении событий кластера (добавление узла, освобождение ресурсов, удаление других подов).

### Алгоритм вытеснения (DefaultPreemption)

Когда планировщик выполняет цикл фильтрации (Filter) и не находит ни одного подходящего узла для пода-кандидата, управление передается в плагин `DefaultPreemption` на этапе **`PostFilter`**:

```
[Старт PostFilter]
       │
       ▼
1. Проверка политики: прерывание, если preemptionPolicy == Never
       │
       ▼
2. Поиск потенциальных узлов (Feasible Nodes):
   Может ли узел удовлетворить требования кандидата, если с него удалить ВСЕ поды с приоритетом < кандидата?
       │
       ▼
3. Выбор подов-жертв на каждом потенциальном узле:
   - Исключаются поды с приоритетом >= приоритета кандидата.
   - Минимизируется суммарный приоритет жертв.
   - Учитывается PDB (предпочтение отдается жертвам, удаление которых не нарушит PDB).
   - Минимизируется общее число удаляемых подов.
       │
       ▼
4. Выбор наилучшего узла:
   - Приоритет узлам, где PDB НЕ нарушается.
   - Приоритет узлам с наименьшим максимальным приоритетом жертвы.
       │
       ▼
5. Номинация узла:
   Кандидату выставляется status.nominatedNodeName = <NodeName>.
       │
       ▼
6. Удаление жертв:
   Подам-жертвам отправляется команда на удаление через API-сервер (graceful deletion).
```

### Асинхронное вытеснение (SchedulerAsyncPreemption)

В стабильных версиях Kubernetes (начиная с v1.33+ в статусе beta, v1.32 alpha) вызовы API на удаление выбранных подов-жертв выполняются асинхронно в отдельных горутинах. Планировщик не блокирует свой основной конвейер в ожидании подтверждения от `apiserver`, что устраняет просадки пропускной способности (scheduling throughput) при массовом дефиците ресурсов на On-Premise инфраструктуре.

### Спецификация манифеста PriorityClass

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: production-critical
value: 10000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "Для критически важных сервисов production-контура."
```

#### Правила и ограничения полей:

1.  **`value` (обязательное):**
    *   32-битное целое число со знаком.
    *   Пользовательский диапазон: **от `-2147483648` до `1000000000` включительно**.
    *   Значения больше `1000000000` зарезервированы для встроенных системных классов. Попытка создать пользовательский класс со значением `> 1000000000` будет отклонена.
    *   Отрицательные значения допустимы и используются для фоновых, обслуживающих или низкоприоритетных задач, которые должны уступать место дефолтным подам (`value: 0`).
2.  **`preemptionPolicy` (опциональное):**
    *   `PreemptLowerPriority` (по умолчанию): под имеет право вытеснять поды с меньшим значением `spec.priority`.
    *   `Never`: под помещается в голову очереди `activeQ` в соответствии со своим весом, но **не вытесняет** работающие поды. Он ожидает естественного освобождения ресурсов узла.
3.  **`globalDefault` (опциональное):**
    *   Булево значение (`true`/`false`).
    *   В кластере может существовать **только один** `PriorityClass` с `globalDefault: true`. Попытка применить манифест со вторым классом завершится ошибкой валидации API-сервера.
    *   Изменение или удаление `globalDefault` не меняет приоритеты уже запущенных подов.
4.  **Именование:**
    *   Имя должно соответствовать требованиям RFC 1123 (DNS subdomain).
    *   Запрещено использовать префикс `system-` для пользовательских классов.

### Системные классы приоритета

Kubernetes поставляется с двумя встроенными системными классами, которые создаются автоматически при инициализации кластера (`kube-apiserver`):

| Имя класса | Значение | Назначение и примеры компонентов |
| :--- | :--- | :--- |
| **`system-node-critical`** | `2000001000` | Компоненты, критичные для жизнедеятельности конкретного узла: сетевой CNI-плагин (Cilium, Calico node daemonset), локальные демоны CSI-хранилищ. |
| **`system-cluster-critical`** | `2000000000` | Компоненты, критичные для функционирования всего кластера: CoreDNS, etcd, kube-apiserver, kube-scheduler, kube-controller-manager. |

> [!WARNING]
> Назначение пользовательским прикладным подам классов `system-*` крайне не рекомендуется. Если бизнес-приложение с классом `system-cluster-critical` начнет вытеснять сетевые демоны или DNS, это приведет к каскадной деградации всего кластера.

### Сравнение: Scheduler Preemption vs Kubelet Eviction

Одна из самых частых ошибок системных администраторов и инженеров эксплуатации — путать вытеснение планировщиком и выселение узловым агентом.

| Критерий | Preemption (kube-scheduler) | Eviction (kubelet) |
| :--- | :--- | :--- |
| **Инициатор** | `kube-scheduler` (планировщик) | `kubelet` (агент на конкретном узле) |
| **Причина (триггер)** | Новый под не может разместиться из-за нехватки лимитов/реквестов (`requests`) | Локальный узел физически исчерпал память, диск или PID (`thresholds`) |
| **Основной критерий отбора жертв** | **Числовой приоритет (`spec.priority`)** | **Класс QoS (`BestEffort` ──► `Burstable` ──► `Guaranteed`) + перерасход ресурсов** |
| **Роль QoS** | **Не учитывается.** `BestEffort` с высоким приоритетом вытеснит `Guaranteed` с низким приоритетом | Первичный критерий. Внутри одного QoS-класса учитывается приоритет и потребление сверх request |
| **Соблюдение PDB** | Учитывает PDB (минимизирует нарушения) | **Игнорирует PDB** (стабильность узла важнее доступности приложения) |
| **Статус и код завершения** | Под удаляется стандартно через API-сервер (сигнал `SIGTERM`, graceful period) | Под переводится в фазу `Failed` с причиной `Evicted` |
| **Точка принятия решений** | Уровень кластера (Control Plane) | Уровень конкретного физического/виртуального сервера |

---

## Практические сценарии и конфигурация

### Сценарий 1: Корпоративная иерархия приоритетов для On-Premise инфраструктуры

В изолированных bare-metal и виртуализированных кластерах рекомендуется поддерживать четкую, ограниченную шкалу из 5–6 классов.

```yaml
# 1. Инфраструктурные аддоны (Ingress-контроллеры, cert-manager, node-exporter)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: platform-high
value: 1000000000
preemptionPolicy: PreemptLowerPriority
description: "Платформенные контроллеры и критические аддоны кластера."
---
# 2. Высокоприоритетные продуктовые сервисы (БД, брокеры сообщений, шлюзы)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: prod-critical
value: 800000000
preemptionPolicy: PreemptLowerPriority
description: "Критичные компоненты production-контура."
---
# 3. Стандартные рабочие сервисы production
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: prod-general
value: 500000000
preemptionPolicy: PreemptLowerPriority
description: "Стандартные микросервисы и stateless нагрузки."
---
# 4. Класс по умолчанию для нагрузок без явного указания
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: default-workload
value: 100000
globalDefault: true
preemptionPolicy: PreemptLowerPriority
description: "Дефолтный класс для всех неразмеченных подов."
---
# 5. Низкоприоритетные задачи и среды разработки
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: non-prod-workload
value: 10000
preemptionPolicy: PreemptLowerPriority
description: "Тестовые стенды, Dev/QA окружения."
---
# 6. Утилизирующие фоновые задачи (Scavenger / Batch)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: scavenger-batch
value: -1000
preemptionPolicy: Never
description: "Фоновые аналитические задачи, вытесняемые любыми другими подами."
```

Применение манифеста:

```bash
kubectl apply -f priority-classes.yaml
# → priorityclass.scheduling.k8s.io/platform-high created
# → priorityclass.scheduling.k8s.io/prod-critical created
# → priorityclass.scheduling.k8s.io/prod-general created
# → priorityclass.scheduling.k8s.io/default-workload created
# → priorityclass.scheduling.k8s.io/non-prod-workload created
# → priorityclass.scheduling.k8s.io/scavenger-batch created
```

### Сценарий 2: Фоновая и Batch-обработка без агрессивного вытеснения

Когда в кластере запускаются тяжелые вычислительные скрипты или ночные резервные копирования, они не должны нарушать работу стандартных сервисов. Для таких задач используется `preemptionPolicy: Never`.

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: batch-queue-runner
value: 200000
preemptionPolicy: Never
description: "Высокая позиция в очереди планирования, но без вытеснения запущенных подов."
---
apiVersion: batch/v1
kind: Job
metadata:
  name: night-backup
  namespace: maintenance
spec:
  template:
    spec:
      priorityClassName: batch-queue-runner
      restartPolicy: OnFailure
      containers:
      - name: backup-worker
        image: backup-tool:2.4
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
```

*Поведение:* Если свободных ресурсов на узлах нет, джоба ожидает в состоянии `Pending`. Как только ресурсы освобождаются, планировщик выбирает её раньше, чем поды с `value: 100000` (дефолтные), но ни один работающий под не завершается принудительно.

### Сценарий 3: Разграничение доступа через ResourceQuota и scopeSelector

В мультитенантном кластере разработчики не должны иметь возможность бесконтрольно указывать `priorityClassName: prod-critical` для тестовых приложений. Для жесткого контроля прав используются квоты пространств имен:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: dev-priority-restriction
  namespace: team-development
spec:
  hard:
    pods: "0"
  scopeSelector:
    matchExpressions:
    - scopeName: PriorityClass
      operator: In
      values: ["prod-critical", "platform-high"]
```

Проверка поведения:

```bash
# Попытка разработчика запустить под с защищенным классом
kubectl run test-attack --image=nginx --restart=Never -n team-development --overrides='{"spec":{"priorityClassName":"prod-critical"}}'
# → Error from server (Forbidden): pods "test-attack" is forbidden: exceeded quota: dev-priority-restriction, requested: pods=1, used: pods=0, limited: pods=0
```

Для ограничения любых подов с приоритетом выше стандартного можно использовать `scopeName: PriorityClassInUse` или применить политики `ValidatingAdmissionPolicy`:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: disallow-critical-priority
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["pods"]
  validations:
  - expression: "!has(object.spec.priorityClassName) || !['prod-critical', 'platform-high'].contains(object.spec.priorityClassName)"
    message: "Назначение критических классов приоритета запрещено регламентом платформы."
```

### Сценарий 4: Подключение PriorityClass к рабочим нагрузкам

Класс приоритета указывается в спецификации шаблона пода (`spec.template.spec.priorityClassName`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-gateway
  namespace: orders
spec:
  replicas: 3
  selector:
    matchLabels:
      app: order-gateway
  template:
    metadata:
      labels:
        app: order-gateway
    spec:
      priorityClassName: prod-critical
      containers:
      - name: gateway
        image: internal-registry.corp/apps/order-gw:1.14.0
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "1"
            memory: "1Gi"
```

Проверка применения приоритета:

```bash
kubectl apply -f order-gateway.yaml
# → deployment.apps/order-gateway created

kubectl get pods -n orders -l app=order-gateway -o custom-columns=NAME:.metadata.name,PRIORITY_CLASS:.spec.priorityClassName,NUMERIC_PRIORITY:.spec.priority
# → NAME                             PRIORITY_CLASS   NUMERIC_PRIORITY
# → order-gateway-6bb98495f8-45k2n   prod-critical    800000000
# → order-gateway-6bb98495f8-k8m9v   prod-critical    800000000
# → order-gateway-6bb98495f8-zpq1x   prod-critical    800000000
```

### Сценарий 5: Резервирование ресурсов через «поды-заглушки» (Balloon Pods)

В On-Premise средах без динамического автомасштабирования серверов критически важно иметь гарантию моментального размещения дополнительных реплик продакшн-сервисов при авариях или всплесках нагрузки. Для этого применяется паттерн **Balloon Pods (поды-баллоны)**.

Запускается под с низким отрицательным приоритетом, который занимает ресурсы узлов. При появлении боевого пода планировщик моментально вытесняет «баллон».

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-resource-balloon
  namespace: kube-system
spec:
  replicas: 4
  selector:
    matchLabels:
      app: resource-balloon
  template:
    metadata:
      labels:
        app: resource-balloon
    spec:
      priorityClassName: scavenger-batch # value: -1000
      terminationGracePeriodSeconds: 0   # Мгновенное освобождение ресурсов узла
      containers:
      - name: pause
        image: registry.k8s.io/pause:3.10
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
```

*Результат:* 8 ядер CPU и 16 GiB памяти гарантированно зарезервированы в кластере. Как только сервису с приоритетом `prod-critical` требуются ресурсы, `kube-scheduler` мгновенно вытесняет `pause`-контейнеры.

### Сценарий 6: Безопасная ротация и миграция PriorityClass

Поскольку значения `value` и `preemptionPolicy` неизменяемы, обновление иерархии приоритетов должно производиться по методу **Blue/Green переключения классов**:

```bash
# 1. Создать новую версию класса с желаемым числовым весом
cat <<EOF | kubectl apply -f -
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: prod-critical-v2
value: 900000000
preemptionPolicy: PreemptLowerPriority
description: "Актуализированный класс для critical workloads."
EOF
# → priorityclass.scheduling.k8s.io/prod-critical-v2 created

# 2. Обновить манифесты деплойментов в Git / Helm values:
# priorityClassName: prod-critical-v2

# 3. Выполнить rollout перезапуск приложений
kubectl rollout restart deployment/order-gateway -n orders
# → deployment.apps/order-gateway restarted

# 4. Проверить, что старый класс больше не используется подами
kubectl get pods -A -o jsonpath='{range .items[?(@.spec.priorityClassName=="prod-critical")]}{.metadata.namespace}{"/"}{.metadata.name}{"\n"}{end}'
# → (пустой вывод)

# 5. Только после освобождения удалить старый класс
kubectl delete priorityclass prod-critical
# → priorityclass.scheduling.k8s.io "prod-critical" deleted
```

---

## Операции и команды

Справочник команд администратора для мониторинга и отладки приоритетов:

| Задача | Команда | Ожидаемый результат / вывод |
| :--- | :--- | :--- |
| **Список всех классов** | `kubectl get priorityclass` | Список классов, их `value`, `globalDefault`, `preemptionPolicy` и возраст. |
| **Детальная информация о классе** | `kubectl describe priorityclass prod-critical` | Вывод полного манифеста, описания и настроек вытеснения. |
| **Проверка приоритета пода** | `kubectl get pod <name> -n <ns> -o jsonpath='{.spec.priorityClassName}{" (val="}{.spec.priority}{")\n"}'` | `prod-critical (val=800000000)` |
| **Вывод подов со всеми приоритетами** | `kubectl get pods -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,CLASS:.spec.priorityClassName,VAL:.spec.priority` | Табличный список всех подов с числовыми весами. |
| **Поиск номинированных подов** | `kubectl get pods -A -o jsonpath='{range .items[?(@.status.nominatedNodeName)]}{.metadata.namespace}{"/"}{.metadata.name}{" nominated for "}{.status.nominatedNodeName}{"\n"}{end}'` | `orders/order-gw-xxx nominated for node-03.corp` |
| **Поиск событий вытеснения** | `kubectl get events -A --field-selector reason=Preempted` | События завершения подов из-за преемпшна. |
| **Проверка очередей шедулера в логах** | `kubectl logs -n kube-system kube-scheduler-<control-plane> \| grep -i preemption` | Записи о запуске `DefaultPreemption` и выборе жертв. |

Пример проверки всех PriorityClass в терминале:

```bash
kubectl get priorityclass
# → NAME                      VALUE        GLOBAL-DEFAULT   PREEMPTION-POLICY     AGE
# → default-workload          100000       true             PreemptLowerPriority   5d
# → non-prod-workload         10000        false            PreemptLowerPriority   5d
# → platform-high             1000000000   false            PreemptLowerPriority   5d
# → prod-critical             800000000    false            PreemptLowerPriority   5d
# → prod-general              500000000    false            PreemptLowerPriority   5d
# → scavenger-batch          -1000         false            Never                  5d
# → system-cluster-critical   2000000000   false            PreemptLowerPriority   30d
# → system-node-critical      2000001000   false            PreemptLowerPriority   30d
```

---

## Диагностика и устранение неполадок

### Сводная таблица типовых сбоев

| Симптом | Причина | Способ диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **Ошибка при деплое:** `failed to find priority class` | В манифесте указан класс, который не существует или был удален из кластера | `kubectl describe pod <name>` или логи контроллера Deployment | Создать отсутствующий `PriorityClass` или исправить имя в манифесте приложения. |
| **Ошибка при редактировании:** `PriorityClass is immutable` | Попытка изменить поле `value` или `preemptionPolicy` через `kubectl edit` / `kubectl apply` | `kubectl apply` возвращает ошибку API-сервера | Использовать Blue/Green ротацию классов (создать новый, перевести поды, удалить старый). |
| **Высокоприоритетный под застрял в `Pending`** | Жертвы на узлах защищены `PodDisruptionBudget` (PDB) с `minAvailable: 100%` или `maxUnavailable: 0` | В выводе `kubectl describe pod` видно сообщение `0/N nodes are available: ... PDB violation` | Смягчить настройки PDB жертв или добавить вычислительные мощности на On-Premise хостах. |
| **Под в `Pending`, вытеснение не инициируется** | 1. У пода-кандидата выставлен `preemptionPolicy: Never`.<br>2. На узлах нет подов с приоритетом **строго ниже**, чем у кандидата. | `kubectl get pod <name> -o yaml \| grep -E 'priority\|nominated'` | Проверить значения весов классов в кластере. Убедиться, что целевой под имеет более высокий вес, чем кандидаты в жертвы. |
| **Вытеснение невозможно из-за ограничений размещения** | Узел свободен от подов, но не проходит по `NodeSelector`, `NodeAffinity`, `Tolerations` или `PVC node affinity` | `kubectl describe pod` фиксирует несовпадение taints или volume node affinity | Проверить taints узлов и топологические ограничения PVC. Преемпшн освобождает только CPU/RAM, но не отменяет жесткие правила фильтрации. |
| **Шторм вытеснений (Preemption Thrashing)** | Два контроллера с разными приоритетами циклически вытесняют друг друга при перезапуске и автомасштабировании | Анализ логов шедулера и скачков метрики `scheduler_preemption_attempts_total` | Выровнять приоритеты, настроить PDB или разнести рабочие нагрузки по разным пулам узлов через taints/affinity. |

### Пошаговый алгоритм трассировки вытеснения

Если высокоприоритетный под не может запуститься:

1.  **Шаг 1: Проверить фактический приоритет и фазу пода:**
    ```bash
    kubectl get pod <pod-name> -n <namespace> -o jsonpath='Phase: {.status.phase}, Class: {.spec.priorityClassName}, Priority: {.spec.priority}, NominatedNode: {.status.nominatedNodeName}{"\n"}'
    # → Phase: Pending, Class: prod-critical, Priority: 800000000, NominatedNode: worker-02
    ```
2.  **Шаг 2: Проверить события пода:**
    ```bash
    kubectl describe pod <pod-name> -n <namespace> | grep -A 10 Events:
    ```
    *Искать:*
    *   `Preempted by ...` — под сам стал жертвой вытеснения.
    *   `0/8 nodes are available: 8 Insufficient cpu. preemption: 0/8 nodes are available: 8 No preemption victims found for incoming pod.` — нет подов с меньшим приоритетом, удаление которых освободило бы требуемый объем ресурсов.
3.  **Шаг 3: Проверить блокировку со стороны PodDisruptionBudget:**
    ```bash
    kubectl get pdb -A
    # Проверить, у каких сервисов ALLOWED DISRUPTIONS равно 0
    ```
4.  **Шаг 4: Проверить задержку завершения работы жертв:**
    Если `status.nominatedNodeName` заполнено, но под все еще `Pending`, значит выбранные поды-жертвы еще находятся в стадии graceful shutdown (`Terminating`) из-за большого значения `terminationGracePeriodSeconds` или долгой отработки хуков `preStop`.

### Метрики kube-scheduler в Prometheus

Для мониторинга здоровья планировщика и детекции аномалий вытеснения используются встроенные метрики `kube-scheduler` (порт `10259/metrics`):

| Метрика | Тип | Описание для SRE |
| :--- | :--- | :--- |
| `scheduler_preemption_attempts_total` | Counter | Общее количество начатых циклов вытеснения в плагине `DefaultPreemption`. |
| `scheduler_preemption_victims_total` | Counter | Количество подов, фактически выбранных и отправленных на удаление в качестве жертв. |
| `scheduler_pending_pods{queue="activeQ\|backoffQ\|unschedulableQ"}` | Gauge | Количество подов, ожидающих в каждой из трех очередей планировщика. |
| `scheduler_schedule_attempts_total{result="unschedulable"}` | Counter | Частота неудачных попыток планирования. |
| `scheduler_framework_extension_point_duration_seconds{extension_point="PostFilter"}` | Histogram | Латентность фазы PostFilter, на которой выполняется алгоритм вытеснения. |

### Правила алертинга (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: kube-scheduler-preemption-alerts
  namespace: monitoring
spec:
  groups:
  - name: scheduler.rules
    rules:
    - alert: HighPodPreemptionRate
      expr: sum(rate(scheduler_preemption_victims_total[5m])) > 5
      for: 5m
      labels:
        severity: warning
        tier: platform
      annotations:
        summary: "Высокая частота вытеснения подов в кластере"
        description: "Планировщик вытесняет более 5 подов в секунду за последние 5 минут. В кластере острый дефицит ресурсов или возник шторм преемпшна."

    - alert: CriticalWorkloadPreempted
      expr: sum by (namespace, pod) (increase(kube_pod_status_reason{reason="Preempted"}[10m])) > 0
      for: 1m
      labels:
        severity: critical
        tier: application
      annotations:
        summary: "Вытеснен под в namespace {{ $labels.namespace }}"
        description: "Под {{ $labels.pod }} был принудительно вытеснен другим подом. Проверьте распределение приоритетов."

    - alert: SchedulerUnschedulableQueueGrowing
      expr: scheduler_pending_pods{queue="unschedulableQ"} > 50
      for: 10m
      labels:
        severity: warning
        tier: platform
      annotations:
        summary: "Большое количество подов в очереди unschedulableQ"
        description: "В очереди {{ $labels.queue }} находится более 50 подов на протяжении 10 минут. Требуется расширение пула узлов."
```

---

## Лучшие практики

1.  **Держите иерархию компактной (3–5 классов):**
    Не создавайте классы под каждую команду или микросервис (избегайте «гонки вооружений» приоритетов). Достаточно базового деления: Системные аддоны ──► Critical Prod ──► General Prod ──► Default ──► Batch/Dev.
2.  **Всегда задавайте `resources.requests`:**
    Вытеснение опирается **исключительно на `requests`**. Если у высокоприоритетного пода не указаны `requests` (или указаны нули), планировщик сочтет, что под помещается на любой узел, но фактическая нехватка памяти приведет к аварийному завершению процессов ядром через OOM Killer (`kubelet`), минуя graceful preemption.
3.  **Оптимизируйте `terminationGracePeriodSeconds` у вытесняемых сервисов:**
    Пока под-жертва корректно закрывает соединения, высокоприоритетный под ожидает в `Pending`. Для некритичных воркеров и очередей устанавливайте разумный таймаут (например, `10s`–`15s`), чтобы сократить задержку ввода в строй критичных сервисов.
4.  **Не блокируйте вытеснение монопольными PDB:**
    Конфигурации PDB вида `minAvailable: 100%` или `maxUnavailable: 0` для второстепенных сервисов парализуют алгоритм `DefaultPreemption`. Оставляйте как минимум 1 допустимую к прерыванию реплику.
5.  **Защищайте классы через RBAC и Admission Control:**
    Права на создание подов с `priorityClassName: platform-high` или `prod-critical` должны строго ограничиваться через `ResourceQuota` со `scopeSelector` или admission-контроллеры (Kyverno, Gatekeeper, ValidatingAdmissionPolicy).
6.  **Используйте `preemptionPolicy: Never` для пакетных очередей:**
    Если сервису важно быть первым при освобождении узлов, но он не имеет права прерывать живых пользователей, используйте политику `Never` вместо раздувания значения `value`.
7.  **На On-Premise серверах держите буфер через поды-баллоны (Balloon Pods):**
    В отличие от динамических платформ, физический сервер нельзя ввести в строй за 2 минуты. Заблаговременное резервирование емкости через низкоприоритетные pause-контейнеры защищает продакшн от нехватки мощностей при сбоях хостов.

---

## Дополнительная информация

*   [Планировщик kube-scheduler](./kube_scheduler.md) — детальный разбор фаз Scheduling Framework, фильтрации и очередей.
*   [Pod Disruption Budget (PDB)](../Autoscaling/pod_disruption_budget.md) — настройка допустимых прерываний доступности сервисов.
*   [Квоты ресурсов и QoS](../Scheduling/qos_limit_and_requests.md) — взаимосвязь `requests`/`limits`, формирование классов QoS и квотирование приоритетов через `ResourceQuota`.
*   [Диагностика ошибок Pod Pending](../Troubleshooting/Common_Errors/pod_pending/diagnostics.md) — трассировка причин задержки планирования подов.
*   [Различия QoS и Eviction](../Troubleshooting/Common_Errors/PodEvicted/qos_and_eviction.md) — узловое выселение по порогам ресурсов kubelet.
*   [Дескедулер (Descheduler)](../Autoscaling/descheduler.md) — вторичная ребалансировка и оптимизация распределения подов.
*   [Правила размещения Affinity и Anti-Affinity](../Scheduling/affinity.md) — влияние топологических ограничений на выбор узлов при вытеснении.
