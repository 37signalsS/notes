# Управление размещением подов: Affinity, Anti-Affinity и TopologySpreadConstraints

Механизмы распределения подов определяют, как реплики приложения размещаются в топологии кластера. В контексте автоматического масштабирования и высокой доступности (HA) правильное распределение гарантирует выживание сервиса при отказе инфраструктурных компонентов.

## Предварительные требования

**Требования к кластеру:**
* Kubernetes версии 1.24+ (для полной поддержки `topologySpreadConstraints` GA)
* Kubernetes версии 1.31+ (для `nodeAffinityPolicy`, `nodeTaintsPolicy`, `matchLabelKeys` в GA)
* Работающий `kube-scheduler` (проверка: `kubectl get pods -n kube-system -l component=kube-scheduler`)
* Наличие меток топологии на узлах (`kubernetes.io/hostname`, `topology.kubernetes.io/zone`)

**Проверка меток топологии узлов:**
```bash
# Проверка наличия меток зон на узлах
kubectl get nodes --show-labels | grep topology.kubernetes.io/zone

# Если метки зон отсутствуют (on-premise кластер), добавьте их вручную:
kubectl label nodes <node-name> topology.kubernetes.io/zone=zone-a

# Проверка всех меток конкретного узла
kubectl describe node <node-name> | grep Labels -A 10
```

**Инструменты для работы:**
* `kubectl` настроен для целевого кластера
* Права на создание Deployment, Pod, ConfigMap в целевом namespace

---

## Определения

* **Affinity (Притяжение)**: Правило, которое «притягивает» под к узлам или другим подам, обладающими определёнными характеристиками.
* **Anti-Affinity (Отталкивание)**: Правило, которое «отталкивает» под от узлов или других подов.
* **Node Affinity (Привязка к узлам)**: Правила в манифесте пода, определяющие предпочтения или требования к меткам узлов при планировании. Является эволюцией `nodeSelector`, предоставляя более гибкую логику, поддержку операторов и уровней строгости.
* **Pod Affinity / Inter-Pod Affinity (Привязка к подам)**: Размещает под на том же узле или в той же топологии, где уже запущены другие поды. Используется для совместного размещения связанных компонентов (например, приложение и кэш).
* **Pod Anti-Affinity / Inter-Pod Anti-Affinity (Избегание подов)**: Размещает поды на разных узлах или в разных топологиях относительно других подов. Используется для обеспечения высокой доступности путём распределения реплик.
* **Topology Spread Constraints (Ограничения по распространению в топологии)**: Механизм для равномерного распределения подов по доменам отказа (узлам, зонам, регионам). Более продвинутая альтернатива `podAntiAffinity`.
* **nodeName**: Прямое указание имени узла для размещения пода. Наиболее простой, но ограниченный метод (не использует планировщик, не работает с Taints/Tolerations/Affinity).
* **Topology Key (Ключ топологии)**: Метка узла, определяющая область (домен), в которой планировщик ищет поды или проверяет условия размещения.
* **Failure Domain (Домен отказа)**: Логическая группа ресурсов (узел, стойка, зона), которая может выйти из строя целиком.
* **Консолидация (Consolidation)**: Процесс уплотнения подов на меньшем количестве узлов для экономии ресурсов (характерно для Karpenter).
* **Дескедулер (Descheduler)**: Вспомогательный компонент, который анализирует запущенные поды и инициирует их выселение, если их распределение стало субоптимальным.

---

## Основные концепции
### Зачем управлять размещением?

Контроль места размещения подов имеет решающее значение для производительности и надежности системы:
1. **Связь с малой задержкой (Low Latency)**: Размещение часто взаимодействующих сервисов (например, веб-приложение и Redis) на одном узле позволяет минимизировать сетевые задержки и нагрузку на сетевой стек кластера.
2. **Улучшенная отказоустойчивость**: Распределение реплик приложения по разным узлам (с помощью `anti-affinity`) гарантирует, что сбой одного узла не приведет к отключению всех экземпляров сервиса, повышая общую доступность.
3. **Улучшенное использование ресурсов**: Правила сходства и антисходства помогают балансировать рабочие нагрузки по всему кластеру, обеспечивая эффективное использование имеющихся ресурсов CPU и Memory.
4. **Специфические требования к оборудованию**: Некоторым задачам (например, машинному обучению) требуются GPU, другим — быстрые SSD-накопители или определенная архитектура процессора.

### Типы правил

* `requiredDuringSchedulingIgnoredDuringExecution` (**Жёсткое правило**): Аналог `nodeSelector`. Под будет размещён **только если** правило выполнено. Если подходящих узлов нет, под остаётся в состоянии `Pending`.
* `preferredDuringSchedulingIgnoredDuringExecution` (**Мягкое правило**): Планировщик *постарается* выполнить правило, но если это невозможно, под всё равно будет размещён на доступном узле. Правилам назначается вес (`weight` от 1 до 100), где более высокий вес означает более высокий приоритет для планировщика.

### Поведение после запуска

* **IgnoredDuringExecution**: В обоих режимах (required и preferred) этот суффикс означает, что если метки на узле изменятся после запуска пода так, что они перестанут соответствовать правилам аффинити, под **продолжит работать**. Пересчёт размещения и выселение не производятся.
* `...RequiredDuringExecution`: Теоретически предполагает, что правило **продолжает действовать** и после запуска. Если метки на узле изменятся так, что правило перестанет выполняться, Kubernetes должен **выселить (evict)** под с этого узла. 
    * *Примечание:* Для `nodeAffinity` это поле (`requiredDuringSchedulingRequiredDuringExecution`) зарезервировано, но полноценная поддержка автоматического выселения во всех сценариях зависит от версии и конфигурации контроллеров.

### Фазы планирования: как работает Affinity

Affinity правила обрабатываются планировщиком (`kube-scheduler`) в рамках **Scheduling Framework** на двух этапах:

#### Этап 1: Фильтрация (Filter)
На этапе фильтрации отсеиваются узлы, которые **не могут** запустить под:
* **NodeAffinity** с `requiredDuringSchedulingIgnoredDuringExecution` — плагин `NodeAffinity` исключает узлы без соответствующих меток.
* **PodTopologySpread** (для `topologySpreadConstraints` с `whenUnsatisfiable: DoNotSchedule`) — исключает узлы, размещение на которых нарушит `maxSkew`.

**Результат:** список «подходящих» узлов (feasible nodes). Если список пуст — под остаётся в `Pending`.

#### Этап 2: Оценка (Score)
На этапе оценки каждый подходящий узел получает балл от 0 до 100:
* **NodeAffinity** с `preferredDuringSchedulingIgnoredDuringExecution` — плагин `NodeAffinity` добавляет баллы узлам с совпадающими метками согласно параметру `weight`.
* **PodTopologySpread** (для `topologySpreadConstraints` с `ScheduleAnyway`) — плагин добавляет баллы узлам, которые улучшают равномерность распределения.

**Расчёт итоговой оценки:**
Итоговый балл узла = сумма баллов от всех плагинов × вес плагина. Плагин `NodeAffinity` имеет вес 1, `PodTopologySpread` — вес 2.

**Пример расчёта для preferred правила:**
```yaml
preferredDuringSchedulingIgnoredDuringExecution:
- weight: 100  # Узел с меткой zone=prod получит 100 баллов
  preference:
    matchLabels:
      zone: prod
- weight: 50   # Узел с меткой ssd=true получит 50 баллов
  preference:
    matchLabels:
      ssd: "true"
```
Узел с обеими метками получит 150 баллов, с одной — 50 или 100, без меток — 0.

**Важно:** `preferred` правила **никогда не блокируют** планирование — даже при 0 баллах под будет размещён на любом доступном узле.

### Сравнение механизмов планирования

* **Node Affinity против Taints и Tolerations**
  * **Направление действия**:
    * **Taints & Tolerations работают «от ноды»**: Нода «отталкивает» все поды, которые не имеют соответствующего `toleration`. Подробнее: [Taints и Tolerations](./taints_and_tolerations.md).
    * **Node Affinity работает «от пода»**: Под сам «тянется» к нодам с определёнными метками.
  * **Применение**:
    * **Taints + Tolerations**: Используются для жёсткой изоляции узлов под специфические задачи (GPU, CI-воркеры, выделенные команды), чтобы на них не попадали «чужие» поды.
    * **Node Affinity**: Используется для направления подов на узлы с нужными характеристиками (тип диска, зона доступности, архитектура процессора).
  * **Совместное использование**: В связке Taints удерживают лишние поды подальше, а Node Affinity гарантирует, что нужные поды попадут именно туда, где они должны работать.

* **`podAntiAffinity` против `TopologySpreadConstraints`**
  * **`podAntiAffinity`** работает по бинарному принципу: «размещать вместе» или «не размещать вместе» в рамках одной топологии. Это «грубый» инструмент, который лишь гарантирует, что определенные поды не окажутся на одном узле, но не обеспечивает балансировку. Например, при 10 подах на 3-х узлах возможно распределение `1-1-8`, что формально не нарушает правило, но является крайне неравномерным.
  * **`topologySpreadConstraints`** — более гибкий и сложный механизм, решающий проблему балансировки. Он позволяет добиться равномерного распределения подов по разным доменам сбоя (стойки, зоны доступности, узлы), предотвращая ситуацию, когда сбой одной структуры инфраструктуры (например, всей зоны) приводит к отключению всего приложения.

### Ключевые поля и операторы

* **`topologyKey`**: Определяет «область» применения правила (метка узла, идентифицирующая домен топологии). Планировщик ищет поды с нужными метками в пределах этой топологии.
  * `kubernetes.io/hostname`: Область — отдельные узлы.
  * `topology.kubernetes.io/zone`: Область — зоны доступности.
  * `topology.kubernetes.io/region`: Область — регионы.

* **Операторы `nodeAffinity`**:
  * `In` / `NotIn`: Значение метки входит или не входит в указанный список.
  * `Exists` / `DoesNotExist`: Ключ метки присутствует или отсутствует на узле.
  * `Gt` / `Lt`: Числовое сравнение значений меток (только для `nodeAffinity`).
  * `NotIn` и `DoesNotExist` позволяют реализовать поведение **anti-affinity** на уровне самого пода (отталкивание от нод с определёнными метками без использования taints).

* **Поля `topologySpreadConstraints`**:
  * `maxSkew`: Максимально допустимая разница (перекос) между количеством подов в любых двух доменах топологии. Значение `1` означает, что поды должны распределяться максимально равномерно.
  * `whenUnsatisfiable`: Поведение планировщика, если под невозможно разместить согласно ограничению:
    * `DoNotSchedule` (по умолчанию): Жёсткое правило, под останется в состоянии `Pending`.
    * `ScheduleAnyway`: Мягкое правило, под будет размещён в домене, который меньше всего нарушает баланс.
  * `labelSelector`: Определяет группу подов, количество которых будет подсчитываться для проверки баланса. Обычно соответствует меткам самого приложения.
  * `nodeAffinityPolicy` (**GA, 1.31+**): Политика учёта `nodeAffinity` и `nodeSelector` при расчёте топологии.
    * `Honor` (по умолчанию): В расчёт включаются только узлы, удовлетворяющие `nodeAffinity`/`nodeSelector`.
    * `Ignore`: В расчёт включаются все узлы.
  * `nodeTaintsPolicy` (**GA, 1.31+**): Политика учёта Taints/Tolerations при расчёте топологии.
    * `Honor` (по умолчанию): В расчёт включаются только узлы без Taints или с соответствующими Tolerations.
    * `Ignore`: В расчёт включаются все узлы.
* `matchLabelKeys` (**GA, 1.31+ для TSC**): Список ключей меток пода для динамического определения группы распределения. Это позволяет планировщику учитывать только поды с тем же значением метки (например, `pod-template-hash`), что критично для правильного распределения во время Rolling Update.
* `minDomains` (**GA, 1.30+**): Минимальное количество доменов топологии, по которым следует распределять поды. Помогает избежать концентрации подов в малом количестве доступных зон. **Важно:** Задает минимальное количество доменов, которое *должно существовать*. Если у вас всего 1 узел (или 1 зона), а `minDomains: 3`, планировщик будет считать, что есть еще 2 "виртуальных" пустых домена, и заблокирует запуск всех подов на одном узле, чтобы не нарушать `maxSkew`.

### Cross-Namespace Affinity

По умолчанию `podAffinity` и `podAntiAffinity` ищут целевые поды **только в том же namespace**, где размещается текущий под. Для работы с подами из других пространств имен используются дополнительные поля:

* **`namespaces`** (GA 1.29+): Явный список namespace, в которых планировщик ищет целевые поды. Пустое значение или отсутствие поля — поиск только в своём namespace.
* **`namespaceSelector`** (Beta 1.26+): Label selector для выбора namespace. `namespaceSelector: {}` (пустой) — поиск во всех namespace.

**Пример: Affinity к подам в других namespace**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
  namespace: frontend
spec:
  template:
    spec:
      affinity:
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: cache
            topologyKey: kubernetes.io/hostname
            namespaceSelector:
              matchLabels:
                environment: production
            # namespaces:  # Альтернатива: явный список
            # - backend
            # - cache
```

**Ограничения и нюансы:**
* `namespaces` и `namespaceSelector` — взаимоисключающие поля (используйте только одно).
* `topologySpreadConstraints` не поддерживают `namespaceSelector` — всегда работает в рамках своего namespace.
* Для использования `namespaceSelector: {}` (все namespace) убедитесь, что у планировщика есть RBAC-права на чтение namespace во всём кластере (ClusterRole `system:kube-scheduler`).

---

## Практические сценарии

### Сценарий 1: Высокая доступность (High Availability)

Для stateless-приложений используйте `topologySpreadConstraints` для обеспечения отказоустойчивости на уровне дата-центров и узлов. Это гарантирует, что даже при выходе из строя целой стойки или зоны доступности, большая часть реплик приложения продолжит работу.

**Пример: Равномерное распределение по зонам и узлам**

Этот манифест гарантирует, что 6 реплик будут равномерно распределены по зонам, а внутри каждой зоны — равномерно распределены по конкретным узлам. Использование `whenUnsatisfiable: ScheduleAnyway` для зон рекомендовано при использовании автоскейлера, чтобы поды не зависали при сбое зоны.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 6
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      topologySpreadConstraints:
        # 1. Распределение по зонам доступности
        - maxSkew: 1
          topologyKey: "topology.kubernetes.io/zone"
          whenUnsatisfiable: ScheduleAnyway # Важно для HPA
          labelSelector:
            matchLabels:
              app: my-app
        # 2. Распределение по узлам внутри каждой зоны
        - maxSkew: 1
          topologyKey: "kubernetes.io/hostname"
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: my-app
      containers:
      - name: my-app-container
        image: nginx
```

**Валидация:**
```bash
# Применение манифеста
kubectl apply -f my-app-deployment.yaml
# → deployment.apps/my-app created

# Проверка распределения по зонам и узлам
kubectl get pods -o wide -l app=my-app
# NAME                      READY   STATUS    RESTARTS   AGE   IP            NODE     
# my-app-5f6b7d8c9-xxxxx    1/1     Running   0          10s   10.244.1.5    node-1   
# my-app-5f6b7d8c9-yyyyy    1/1     Running   0          10s   10.244.2.3    node-2   
# my-app-5f6b7d8c9-zzzzz    1/1     Running   0          10s   10.244.3.2    node-3   

# Проверка зон узлов
kubectl get nodes -o custom-columns=NAME:.metadata.name,ZONE:.metadata.labels.topology\.kubernetes\.io/zone
# NAME    ZONE
# node-1  zone-a
# node-2  zone-b
# node-3  zone-c

# Проверка событий планирования (не должно быть FailedScheduling)
kubectl get events --field-selector reason=FailedScheduling -l app=my-app
# No resources found
```

**Cleanup:**
```bash
kubectl delete deployment my-app
# → deployment.apps "my-app" deleted
```

**Edge Cases:**
* Если зон меньше чем реплик — поды распределятся равномерно с перекосом не более 1.
* Если узлов в зоне недостаточно для `maxSkew: 1` — поды останутся в `Pending` (при `DoNotSchedule`).
* При использовании HPA с `ScheduleAnyway` — поды будут размещаться даже при нарушении баланса зон.

### Сценарий 2: Оптимизация производительности

Используйте `podAffinity` для компонентов, которые интенсивно обмениваются данными. Размещение их на одном узле (`topologyKey: kubernetes.io/hostname`) минимизирует сетевую задержку и нагрузку на сетевой стек кластера.

**Пример: Совместное размещение веб-приложения и кэша Redis**

```yaml
# В манифесте веб-приложения указываем аффинити к Redis
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      affinity:
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: redis-cache
            topologyKey: kubernetes.io/hostname
      containers:
      - name: web-server
        image: nginx:1.27
```

**Валидация:**
```bash
# Убедитесь, что Redis уже запущен и имеет метку app=redis-cache
kubectl get pods -l app=redis-cache -o wide
# NAME                           READY   STATUS    RESTARTS   AGE   IP           NODE
# redis-cache-7b9f4d6c8-abc12    1/1     Running   0          5m    10.244.1.10  node-1

# Применяем веб-приложение
kubectl apply -f web-app.yaml

# Проверяем, что поды веб-приложения попали на те же узлы, что и Redis
kubectl get pods -l app=web-app -o wide
# NAME                       READY   STATUS    RESTARTS   AGE   IP           NODE
# web-app-6d5f8b9c7-def34    1/1     Running   0          1m    10.244.1.15  node-1  # ← тот же узел
# web-app-6d5f8b9c7-ghi56    1/1     Running   0          1m    10.244.2.8   node-2
# web-app-6d5f8b9c7-jkl78    1/1     Running   0          1m    10.244.3.5   node-3

# Проверка событий (не должно быть FailedScheduling из-за affinity)
kubectl get events --field-selector reason=FailedScheduling -l app=web-app
# No resources found
```

**Cleanup:**
```bash
kubectl delete deployment web-app
# → deployment.apps "web-app" deleted
```

**Edge Cases:**
* Если Redis не запущен — поды веб-приложения останутся в `Pending` (при `required`).
* Если Redis мигрирует на другой узел — поды веб-приложения **не последуют** за ним (из-за `IgnoredDuringExecution`).
* Для мягкого аффинити используйте `preferredDuringSchedulingIgnoredDuringExecution` с `weight`.

**Использование matchLabelKeys (Beta 1.31+) для Affinity:**
Позволяет более точно настраивать близость подов, например, во время обновления, чтобы новые поды тянулись только к новым подам своей версии.

```yaml
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app: web-app
      topologyKey: kubernetes.io/hostname
      matchLabelKeys:
      - pod-template-hash
```

### Сценарий 3: Работа со специализированным оборудованием (GPU)

Для рабочих нагрузок машинного обучения, требующих GPU, необходимо комбинировать `nodeAffinity` (чтобы под "тянулся" к узлам с GPU) и `tolerations` (чтобы под мог "пройти" через taints, которыми обычно защищены такие узлы).

**Пример: Размещение ML-модуля на узле с GPU**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ml-training
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: accelerator
            operator: In
            values:
            - nvidia-gpu
  tolerations:
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
  containers:
  - name: ml-model
    image: nvidia/cuda:12.0-base
    resources:
      limits:
        nvidia.com/gpu: 1
```

**Валидация:**
```bash
# Проверка наличия узлов с GPU
kubectl get nodes -l accelerator=nvidia-gpu
# NAME       STATUS   ROLES   AGE   VERSION
# gpu-node   Ready    <none>  10d   v1.31.0

# Применение манифеста
kubectl apply -f ml-pod.yaml

# Проверка размещения
kubectl get pod ml-training -o wide
# NAME          READY   STATUS    RESTARTS   AGE   IP           NODE
# ml-training   1/1     Running   0          30s   10.244.5.2   gpu-node

# Проверка использования GPU
kubectl exec ml-training -- nvidia-smi
# Вывод nvidia-smi с информацией о GPU
```

**Cleanup:**
```bash
kubectl delete pod ml-training
# → pod "ml-training" deleted
```

**Edge Cases:**
* Если узел с GPU имеет taint, но toleration не указан — под останется в `Pending` с ошибкой `node(s) had untolerated taint`.
* Если метка на узле отсутствует — под останется в `Pending` с ошибкой `NodeAffinity`.
* Без `tolerations` под не попадёт на узел с GPU, даже при наличии `nodeAffinity`.

### Сценарий 4: Обеспечение высокой доступности и предотвращение перегрузки узлов (HA)

**Задача:** Развернуть приложение с несколькими репликами так, чтобы при падении одного или нескольких узлов нагрузка не концентрировалась на оставшихся живых узлах. Типичный пример — фронтенд интернет-магазина (`web-store`), где каждая реплика должна работать на отдельном сервере для исключения единой точки отказа. Это также защищает сервис от агрессивной **консолидации Karpenter**, не позволяя собрать все поды на одном большом узле.

**Проблема (кейс из практики):** Если не настроено распределение подов, при падении узла все его поды могут переехать на один-два оставшихся воркера. Это создает критическую нагрузку на CPU/Memory этих узлов, что может привести к их "зависанию" и падению всего кластера.

**Решение:** 
1. Использовать `podAntiAffinity` с `topologyKey: kubernetes.io/hostname` для обязательного или предпочтительного разнесения реплик по разным физическим серверам.
2. При восстановлении упавших узлов использовать **кордонирование** (`kubectl cordon`), чтобы новые поды не планировались на восстанавливающийся узел сразу в большом количестве.

```yaml
# Пример для Deployment'а интернет-магазина с защитой от отказа узла
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-store
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-store
  template:
    metadata:
      labels:
        app: web-store
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values:
                - web-store
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: store-app
        image: my-store:v1.2.0
```

**Валидация:**
```bash
# Применение манифеста
kubectl apply -f web-store.yaml

# Проверка распределения по узлам
kubectl get pods -l app=web-store -o wide
# NAME                         READY   STATUS    RESTARTS   AGE   IP           NODE
# web-store-7c9b5d8f4-xxxxx    1/1     Running   0          30s   10.244.1.8   node-1
# web-store-7c9b5d8f4-yyyyy    1/1     Running   0          30s   10.244.2.4   node-2
# web-store-7c9b5d8f4-zzzzz    1/1     Running   0          30s   10.244.3.6   node-3

# Проверка событий (не должно быть FailedScheduling)
kubectl get events --field-selector reason=FailedScheduling -l app=web-store
# No resources found

# Симуляция отказа узла
kubectl cordon node-2
kubectl drain node-2 --ignore-daemonsets --delete-emptydir-data

# Проверка, что поды перераспределились на другие узлы
kubectl get pods -l app=web-store -o wide
```

**Cleanup:**
```bash
kubectl delete deployment web-store
# → deployment.apps "web-store" deleted

# Восстановление узла после теста
kubectl uncordon node-2
```

**Edge Cases:**
* Если узлов меньше чем реплик — часть подов останется в `Pending`.
* При Rolling Update старые и новые поды конкурируют за узлы. Используйте `matchLabelKeys` для разделения версий.
* При одновременном падении двух узлов из трёх — поды будут перезапущены на оставшемся узле, нарушая анти-аффинити (но это лучше, чем полная недоступность).

### Сценарий 5: Динамическая балансировка с Descheduler

`kube-scheduler` принимает решения только в момент старта пода. Со временем кластер деградирует (узлы перезагружаются, HPA скейлит поды). Инструмент Descheduler развертывается как `CronJob` для дефрагментации.

**Конфигурация Descheduler:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: descheduler-policy
  namespace: kube-system
data:
  policy.yaml: |
    apiVersion: "descheduler/v1alpha2"
    kind: "DeschedulerPolicy"
    profiles:
      - name: AffinityRebalance
        pluginConfig:
          - name: "RemoveDuplicates"
          - name: "RemovePodsViolatingTopologySpreadConstraint"
            args:
              includeSoftConstraints: false
          - name: "LowNodeUtilization"
            args:
              thresholds:
                cpu: 50
                memory: 50
              targetThresholds:
                cpu: 80
                memory: 80
        plugins:
          balance:
            enabled:
              - "RemoveDuplicates"
              - "RemovePodsViolatingTopologySpreadConstraint"
              - "LowNodeUtilization"
```

**Валидация:**
```bash
# Проверка работы Descheduler (после применения конфигурации)
kubectl logs -n kube-system -l app=descheduler --tail=50
# → Логи с информацией о выселенных подах

# Проверка распределения подов до и после
kubectl get pods -l app=my-app -o wide

# Проверка событий выселения
kubectl get events --field-selector reason=Evicted
# NAME          REASON    MESSAGE
# my-app-xxxxx  Evicted   Descheduler evicted pod
```

**Cleanup:**
```bash
# Удаление Descheduler (если развернут как Helm chart)
helm uninstall descheduler -n kube-system

# Или удаление вручную
kubectl delete deployment descheduler -n kube-system
kubectl delete configmap descheduler-policy -n kube-system
```

**Edge Cases:**
* Descheduler учитывает PDB — не выселяет поды, если нарушит `minAvailable`.
* `RemovePodsViolatingTopologySpreadConstraints` с `includeSoftConstraints: false` работает только с `required` правилами.
* При использовании с `ScheduleAnyway` — Descheduler может перемещать поды для оптимизации баланса.

---

## Дополнительная информация

### Диагностика и мониторинг

#### Проверка распределения подов

```bash
# Распределение по узлам
kubectl get pods -o wide -l app=my-app

# Проверка событий планирования
kubectl get events --field-selector reason=FailedScheduling

# Описание пода с информацией о планировании
kubectl describe pod my-pod | grep -A 10 "Affinity\|Topology"
```

#### Проверка ожидающих (Pending) подов

```bash
# Поды в состоянии Pending
kubectl get pods --field-selector status.phase=Pending

# Причина ожидания
kubectl describe pod pending-pod | grep -A 5 "Events:"
```

**Типичные сообщения об ошибках:**
* `0/10 nodes are available: 10 node(s) didn't match Pod Anti-Affinity rules` — невозможно выполнить правила Anti-Affinity (например, реплик больше, чем узлов).
* `0/10 nodes are available: 6 node(s) didn't match topology spread constraints` — нарушение ограничений Topology Spread (слишком большой перекос `maxSkew`). Если вы используете `minDomains`, проверьте, достаточно ли физических зон в кластере для удовлетворения этого требования (`node(s) had topology spread constraint slack conflict`).
* `0/1 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }` — попытка планирования на мастер-ноду без соответствующих tolerations.
* `0/3 nodes are available: 2 node(s) had node(s) didn't match Pod's node affinity/selector` — несовпадение меток узлов с `nodeAffinity`.
* `0/5 nodes are available: 3 node(s) didn't match pod affinity rules` — нет подов с целевыми метками для `podAffinity`.
* `0/5 nodes are available: 2 node(s) didn't match pod affinity/anti-affinity, 3 node(s) didn't match pod anti-affinity rules` — конфликт правил affinity/anti-affinity.

#### Расширенная диагностика

```bash
# Проверка меток узлов (для nodeAffinity)
kubectl get nodes --show-labels | grep -E "topology|zone|hostname"

# Проверка наличия целевых подов (для podAffinity)
kubectl get pods -l <target-label> --all-namespaces

# Проверка распределения подов по зонам
kubectl get pods -l app=my-app -o custom-columns=\
NAME:.metadata.name,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone

# Проверка логов планировщика (для детальной диагностики)
kubectl logs -n kube-system -l component=kube-scheduler --tail=100 | grep -E "FailedScheduling|affinity|topology"
```

### Troubleshooting

#### Проблема: Поды зависли в Pending из-за Affinity

**Диагностика:**
```bash
# Шаг 1: Проверить события пода
kubectl describe pod <pod-name> | grep -A 10 "Events:"

# Шаг 2: Проверить наличие целевых подов (для podAffinity)
kubectl get pods -l <target-label> -n <namespace>

# Шаг 3: Проверить метки узлов (для nodeAffinity)
kubectl get nodes -l <required-label>
```

**Решения:**
1. Если целевые поды не существуют — создайте их или измените `podAffinity` на `preferred`.
2. Если метки узлов отсутствуют — добавьте их: `kubectl label nodes <node> <key>=<value>`.
3. Если узлов недостаточно — добавьте узлы или уменьшите количество реплик.

#### Проблема: Rolling Update Deadlock

**Симптом:** При обновлении Deployment с `podAntiAffinity` новые поды не могут встать на узлы, где ещё работают старые.

**Решение:**
```yaml
# Используйте matchLabelKeys (v1.31+) для разделения версий
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app: my-app
      topologyKey: kubernetes.io/hostname
      matchLabelKeys:
      - pod-template-hash  # Учитывает только поды той же версии
```

#### Проблема: Неравномерное распределение после сбоя узла

**Симптом:** После падения узла все поды переехали на один оставшийся узел.

**Решение:**
1. Используйте `topologySpreadConstraints` с `maxSkew: 1` для принудительного распределения.
2. Настройте Descheduler для автоматической ребалансировки.
3. Используйте `podDisruptionBudget` для защиты при drain.

### Интеграции

* **[HPA](../Autoscaling/HPA/index.md) и Cluster Autoscaler (CA)**: Поды, создаваемые HPA, автоматически наследуют правила распределения. При добавлении новых узлов CA (и Karpenter) учитывает требования `nodeAffinity` и `topologySpreadConstraints`.
* **[Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md)**: Совместное использование с Anti-Affinity гарантирует, что при обслуживании узлов (drain) или работе Descheduler'а приложение сохранит доступность, так как реплики разнесены по разным доменам.
* **[QoS классы](./qos_limit_and_requests.md)**: Влияют на приоритет при вытеснении (eviction), что важно учитывать при использовании `...RequiredDuringExecution`.
* **[PriorityClass](../Concepts/priorityclass.md)**: Определяет порядок вытеснения. Поды с высоким PriorityClass могут вытеснять поды с низким, даже если те удовлетворяют affinity правилам. При вытеснении учитываются только `required` affinity правила — `preferred` правила игнорируются.
* **[Taints и Tolerations](./taints_and_tolerations.md)**: Работают совместно с Node Affinity — Taints отталкивают нежелательные поды, Node Affinity притягивает нужные.
* **[Topology Manager](./topology_manager.md)**: Для NUMA-изолированных нагрузок Topology Manager координирует CPU, Memory и Device Manager. Node Affinity и Pod Affinity работают на уровне планировщика, а Topology Manager — на уровне kubelet.

### Рекомендации (Best Practices)

* **Гибкость важнее жёсткости:** Отдавайте предпочтение мягким правилам (`preferred...`). Жёсткие правила (`required...`) могут оставить поды в состоянии `Pending` при малейшем изменении состояния кластера.
* **Используйте Pod Affinity для связанных сервисов:** Размещайте вместе компоненты, которые часто обмениваются данными (например, веб-сервер и кэш или БД), чтобы снизить задержку сети и повысить общую производительность.
* **Используйте Pod Anti-Affinity для реплик:** Распределяйте реплики критически важных сервисов по разным узлам, чтобы предотвратить одновременный простой всех экземпляров при отказе одного узла. Это особенно важно для приложений с состоянием (Stateful), которые полагаются на кворум или избыточность.
* **Комбинируйте Affinity и Anti-Affinity:** Используйте оба механизма одновременно, чтобы сбалансировать производительность (совместное размещение зависимых служб) и надежность (разнесение реплик одной службы).
* **Опасность жёсткого Anti-Affinity по зонам:** Использование `required` с `topologyKey: topology.kubernetes.io/zone` опасно: если одна зона выйдет из строя, поды не смогут переехать в другие зоны, так как нарушат правило "один под на зону".
* **Topology Spread — основной выбор для HA:** Для обеспечения равномерности и отказоустойчивости `topologySpreadConstraints` является более мощным инструментом, чем `podAntiAffinity`.
* **Производительность:** Избегайте `podAffinity` с очень широкими селекторами в кластерах более 500 узлов, так как это перегружает планировщик.
* **Обновление приложений:** При использовании Anti-Affinity в Deployment используйте `matchLabelKeys` (с версии 1.27 для Topology и 1.31 для Affinity), чтобы избежать ситуации, когда новые поды не могут встать на место старых во время Rolling Update.
* **Cross-Namespace:** Для аффинити к подам в других пространствах имен используйте поле `namespaces` (явный список) или `namespaceSelector` (выбор по меткам). Убедитесь в наличии RBAC-прав у планировщика.
* **Тестирование сбоев:** Регулярно проверяйте поведение при отказе узлов — используйте `kubectl cordon` и `kubectl drain` для симуляции сбоев в staging-кластере.
* **Мониторинг распределения:** Настройте алерты на неравномерное распределение подов (например, через kube-state-metrics и Prometheus).
* **Документирование меток:** Ведите реестр используемых меток узлов и их значений. Недокументированные метки — причина ошибок планирования.

### Вопросы на собеседовании

#### Что такое Topology Spread Constraints и почему они важны для HA?
Это механизм планирования, который обеспечивает равномерное распределение подов по разным доменам сбоя (зоны доступности, стойки, узлы). Это критично для высокой доступности, так как предотвращает возникновение единой точки отказа. Если все реплики приложения окажутся в одной зоне, то сбой этой зоны приведет к полному отключению сервиса.

#### Можете ли вы объяснить параметр `maxSkew`? Что означает `maxSkew: 1`?
Параметр `maxSkew` определяет максимально допустимую разницу в количестве подов между любыми двумя доменами топологии. 
* **`maxSkew: 1`** — это самая строгая настройка, заставляющая поды распределяться максимально равномерно. 
* **Пример:** Если у вас 5 реплик пода и 2 зоны доступности, то при `maxSkew: 1` одна зона получит 3 пода, а другая — 2. Разница (перекос) составит 1, что допустимо. Если бы одна зона получила 4 пода, а другая 1, перекос составил бы 3, что было бы нарушением правила.

#### Когда следует использовать Topology Spread Constraints вместо Pod Anti-Affinity?
Topology Spread Constraints следует предпочитать для достижения именно *равномерного* распределения реплик. Pod Anti-Affinity — это бинарное правило: оно лишь гарантирует, что некоторые поды не работают на одном узле. Spread Constraints дают более детальный контроль через параметр `maxSkew`, обеспечивая баланс между многими узлами или зонами, что является стандартом для production-решений.

#### В чём разница между Node Affinity и Taints/Tolerations?
* **Node Affinity** работает «от пода» — под сам «тянется» к узлам с определёнными метками.
* **Taints/Tolerations** работают «от узла» — узел «отталкивает» поды без соответствующих tolerations.
* **Совместное использование:** Taints удерживают лишние поды, Node Affinity гарантирует попадание нужных.

#### Что произойдёт, если правило required Affinity не может быть выполнено?
Под останется в состоянии `Pending`. Планировщик будет периодически перепроверять условия, но не разместит под, пока не появится подходящий узел. Для диагностики используйте `kubectl describe pod <name>` и проверяйте секцию Events.

#### Как избежать Rolling Update Deadlock при использовании podAntiAffinity?
Используйте `matchLabelKeys` (Kubernetes 1.31+ для Affinity, 1.27+ для Topology Spread) — это позволяет планировщику учитывать только поды с тем же значением метки (например, `pod-template-hash`), разделяя старые и новые версии при расчёте ограничений.

#### Что означает суффикс IgnoredDuringExecution?
Если после запуска пода метки на узле изменятся и перестанут соответствовать правилу affinity, под **не будет выселен** и продолжит работу. Пересчёт размещения не производится. Это поведение по умолчанию для большинства сценариев.

#### Как работает preferredDuringSchedulingIgnoredDuringExecution?
Это «мягкое» правило — планировщик *старается* его выполнить, но если это невозможно, под всё равно будет размещён на доступном узле. Правилам назначается вес (`weight` от 1 до 100). Планировщик суммирует баллы от всех правил и выбирает узел с наивысшим баллом.

### Комплексный пример Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      affinity:
        # 1. Node Affinity: только узлы с SSD, желательно в зоне eu-central-1a.
        nodeAffinity:
          # Жёсткое правило: под будет запущен ТОЛЬКО на узле с меткой disktype=ssd.
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: disktype
                    operator: In
                    values:
                      - ssd
          # Мягкое правило: планировщик будет стараться запустить под в указанной зоне.
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100 # Правило с наивысшим приоритетом
              preference:
                matchExpressions:
                  - key: topology.kubernetes.io/zone
                    operator: In
                    values: ["eu-central-1a"]
        # 2. Pod Affinity: размещать на том же узле, что и под с меткой app=database.
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app
                    operator: In
                    values:
                      - database
              topologyKey: kubernetes.io/hostname
        # 3. Pod Anti-Affinity: стараться не размещать реплики этого deployment на одном узле.
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values:
                        - web-app
                topologyKey: kubernetes.io/hostname
      containers:
        - name: web-server
          image: nginx:1.27.0
```

### См. также

* **[Taints и Tolerations](./taints_and_tolerations.md)** — механизм отталкивания подов от узлов, работает в связке с Node Affinity.
* **[QoS, Requests и Limits](./qos_limit_and_requests.md)** — влияет на приоритет вытеснения при нехватке ресурсов.
* **[Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md)** — защита при плановых работах и drain узлов.
* **[Kube-scheduler](../Concepts/kube_scheduler.md)** — архитектура планировщика и механизмы вытеснения.
* **[Pod Pending — диагностика](../Troubleshooting/Common_Errors/pod_pending/common_cases_and_solutions.md)** — поиск и устранение проблем планирования.