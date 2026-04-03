# Управление размещением подов: Affinity, Anti-Affinity и TopologySpreadConstraints

## Definitions

* **Affinity (Притяжение)**: Правило, которое «притягивает» под к узлам или другим подам, обладающими определёнными характеристиками.
* **Anti-Affinity (Отталкивание)**: Правило, которое «отталкивает» под от узлов или других подов.
* **Node Affinity (Привязка к узлам)**: Размещает поды на узлах с определёнными метками (например, узлы с GPU или быстрыми дисками). Является более гибкой альтернативой `nodeSelector`.
* **Pod Affinity (Привязка к подам)**: Размещает под на том же узле или в той же топологии, где уже запущены другие поды. Используется для совместного размещения связанных компонентов (например, приложение и кэш).
* **Pod Anti-Affinity (Избегание подов)**: Размещает поды на разных узлах или в разных топологиях относительно других подов. Используется для обеспечения высокой доступности путём распределения реплик.
* **Topology Spread Constraints (Ограничения по распространению в топологии)**: Механизм для равномерного распределения подов по доменам отказа (узлам, зонам, регионам). Более продвинутая альтернатива `podAntiAffinity`.
* **nodeName**: Прямое указание имени узла для размещения пода. Наиболее простой, но ограниченный метод (не использует планировщик, не работает с Taints/Tolerations/Affinity).

---

## Basic Concepts

### Типы правил

* `requiredDuringScheduling...` (**Жёсткое правило**): Под будет размещён, **только если** правило выполнено. Если подходящих узлов нет, под остаётся в состоянии `Pending`.
* `preferredDuringScheduling...` (**Мягкое правило**): Планировщик *постарается* выполнить правило, но если это невозможно, под всё равно будет размещён на доступном узле. Правилам можно назначать вес (`weight` от 1 до 100) для приоритизации.

### Поведение после запуска

* `...IgnoredDuringExecution`: Правило применяется **только один раз** в момент планирования. Изменения меток на узлах или подах после запуска **не влияют** на уже работающий под. Это стандартное поведение.
* `...RequiredDuringExecution`: Правило **продолжает действовать** и после запуска. Если метки на узле изменятся так, что правило перестанет выполняться, Kubernetes **выселит (evict)** под с этого узла. Используется реже и только для `nodeAffinity`.

### Сравнение механизмов планирования

* **`nodeAffinity` vs. `Taints/Tolerations`**
  * **`nodeAffinity` (Притяжение)**: Под «хочет» быть размещённым на узле с определёнными метками.
  * **`Taints/Tolerations` (Отталкивание)**: Узел с `taint` не позволяет подам размещаться на нём, если у них нет соответствующего `toleration`. Подробнее в [Taints and Tolerations](./taints_and_tolerations.md).
  * Эти механизмы часто используются вместе: `taint` для резервирования узлов под специальные задачи и `nodeAffinity` для целенаправленного размещения на них нужных подов.

* **`podAntiAffinity` vs. `TopologySpreadConstraints`**
  * **`podAntiAffinity`** работает по бинарному принципу: «размещать вместе» или «не размещать вместе» в рамках одной топологии. Он не умеет балансировать нагрузку. Например, при `podAntiAffinity` для 10 подов на 3-х узлах возможно распределение `1-1-8`, что формально не нарушает правило, но является неравномерным.
  * **`topologySpreadConstraints`** решает проблему балансировки. Он следит, чтобы количество подов в каждом домене топологии не отличалось более чем на `maxSkew`, обеспечивая равномерное распределение.

### Ключевые поля и операторы

* **`topologyKey`**: Определяет «область» применения правила (узел, зона доступности, регион). Планировщик ищет поды с нужными метками в пределах этой топологии.
  * `kubernetes.io/hostname`: Область — один узел.
  * `topology.kubernetes.io/zone`: Область — одна зона доступности.
  * `topology.kubernetes.io/region`: Область — один регион.

* **Операторы `nodeAffinity`**:
  * `In`, `NotIn`: Значение метки должно/не должно совпадать с одним из указанных.
  * `Exists`, `DoesNotExist`: Узел должен/не должен иметь метку с указанным ключом.
  * `Gt`, `Lt`: Значение метки (число) должно быть больше или меньше указанного.

* **Поля `topologySpreadConstraints`**:
  * `maxSkew`: Максимально допустимое отклонение в количестве подов между доменами.
  * `whenUnsatisfiable`: Поведение при невозможности выполнить правило:
    * `DoNotSchedule` (по умолчанию): Жёсткое правило, под не будет запланирован.
    * `ScheduleAnyway`: Мягкое правило, под будет размещён в наименее загруженном домене.
  * `labelSelector`: Определяет, на какую группу подов распространяется правило.
  * `nodeAffinityPolicy`: Политика учёта `nodeAffinity` и `nodeSelector` при расчёте топологии (Kubernetes 1.26+).
    * `Honor` (по умолчанию): В расчёт включаются только узлы, удовлетворяющие `nodeAffinity`/`nodeSelector`.
    * `Ignore`: В расчёт включаются все узлы.
  * `nodeTaintsPolicy`: Политика учёта Taints/Tolerations при расчёте топологии (Kubernetes 1.26+).
    * `Honor` (по умолчанию): В расчёт включаются только узлы без Taints или с соответствующими Tolerations.
    * `Ignore`: В расчёт включаются все узлы.
  * `matchLabelKeys`: Список ключей меток пода для динамического определения группы распределения (Kubernetes 1.27+).
  * `minDomains`: Минимальное количество доменов топологии, по которым следует распределять поды (Kubernetes 1.24+).

## Practical Scenarios

### Сценарий 1: Высокая доступность (High Availability)

Для stateless-приложений используйте `podAntiAffinity` или `topologySpreadConstraints` для распределения реплик по разным узлам (`topologyKey: kubernetes.io/hostname`) или зонам доступности (`topologyKey: topology.kubernetes.io/zone`).

**Пример с `podAntiAffinity`**:

```yaml
# Стараться не запускать поды этого Deployment'а на одном и том же узле.
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app: api-server
        topologyKey: kubernetes.io/hostname
```

**Пример с `topologySpreadConstraints` (предпочтительный способ)**:

```yaml
# Равномерно распределить поды по зонам (жёстко) и узлам (мягко).
spec:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          app: my-app
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          app: my-app
```

### Сценарий 2: Оптимизация производительности

Используйте `podAffinity` для компонентов, которые интенсивно обмениваются данными (например, приложение и кэш). Размещение их на одном узле (`topologyKey: kubernetes.io/hostname`) минимизирует сетевую задержку.

### Сценарий 3: Работа со специализированным оборудованием

Используйте `nodeAffinity` для подов, требующих специфических ресурсов, таких как GPU (`nvidia.com/gpu`) или быстрые диски (`disk-type: ssd`).

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
              # topologyKey определяет «область» применения правила.
              # kubernetes.io/hostname означает, что поды должны быть на одном и том же узле.
              topologyKey: kubernetes.io/hostname
        # 3. Pod Anti-Affinity: стараться не размещать реплики этого deployment на одном узле.
        podAntiAffinity:
          # Мягкое правило: стараться не запускать поды этого Deployment'а на одном и том же узле.
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values:
                        - web-app
                # Разделяем поды в пределах одного узла
                topologyKey: kubernetes.io/hostname
      containers:
        - name: web-server
          image: nginx:1.28.0
```

### Сценарий 4: Обеспечение высокой доступности для stateless-сервиса (HA)

**Задача:** Развернуть stateless-приложение (например, лог-роутер на базе FluentD) с несколькими репликами и гарантировать, что планировщик разместит их на разных узлах для предотвращения единой точки отказа.

**Решение:** Использовать `podAntiAffinity` с `topologyKey: kubernetes.io/hostname`. Это правило указывает планировщику избегать размещения пода на узле, где уже работает другой под с такой же меткой.

```yaml
# Пример для Deployment'а FluentD
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fluentd-router
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fluentd-router
  template:
    metadata:
      labels:
        app: fluentd-router
    spec:
      affinity:
        podAntiAffinity:
          # Используем жёсткое правило для production
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values:
                - fluentd-router
            # Область применения правила — один узел (hostname)
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: fluentd
        image: fluent/fluentd-kubernetes-daemonset:v1-debian-elasticsearch
        # ... остальная конфигурация ...
```

**Как это работает:**

1. Когда планировщик собирается разместить первую реплику, он выбирает подходящий узел.
2. При размещении второй реплики правило `podAntiAffinity` активируется. Планировщик видит, что на первом узле уже есть под с меткой `app: fluentd-router`, и исключает этот узел из списка кандидатов.
3. Таким образом, все три реплики будут гарантированно размещены на разных узлах (если в кластере достаточно узлов). Если попытаться увеличить количество реплик до числа, превышающего количество доступных узлов, новые поды останутся в состоянии `Pending`.

## Additional Information

### Рекомендации

* **Гибкость и надёжность:** Отдавайте предпочтение мягким правилам (`preferred...`). Жёсткие правила (`required...`) могут сделать систему хрупкой: если ни один узел не удовлетворяет условиям, поды не будут запланированы.
* **Опасность `required` anti-affinity:** Жёсткое правило `podAntiAffinity` с `topologyKey: topology.kubernetes.io/zone` опасно. Если количество реплик превысит количество доступных зон, лишние поды никогда не будут запущены.
* **Современный подход к HA:** Для высокой доступности и равномерного распределения `topologySpreadConstraints` является более мощным и гибким инструментом, чем `podAntiAffinity`.
* **Взаимосвязь с QoS:** При планировании размещения учитывайте [QoS классы](./qos_limit_and_requests.md). Поды с разными QoS имеют разный приоритет при вытеснении (eviction), что влияет на выбор узла и стратегию распределения.
* **Производительность планировщика:** Избегайте использования `podAffinity`/`podAntiAffinity` с широкими селекторами (`matchLabels: {}`) в больших кластерах (>500 узлов). Это может значительно замедлить работу планировщика из-за необходимости сканировать все поды в кластере.
* **Комбинирование правил:** При использовании нескольких правил одновременно (например, `nodeAffinity` + `podAntiAffinity` + `topologySpreadConstraints`) помните, что все они должны выполняться. Слишком сложные комбинации могут привести к тому, что поды останутся в состоянии `Pending`.
