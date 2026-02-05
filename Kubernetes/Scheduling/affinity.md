# Управление размещением подов: Affinity, Anti-Affinity и TopologySpreadConstraints

## 1. Определения

*   **Affinity (Притяжение)**: Правило, которое "притягивает" под к узлам или другим подам, обладающим определёнными характеристиками.
*   **Anti-Affinity (Отталкивание)**: Правило, которое "отталкивает" под от узлов или других подов.
*   **Node Affinity (Привязка к узлам)**: Размещает поды на узлах с определёнными метками (например, узлы с GPU или быстрыми дисками). Является более гибкой альтернативой `nodeSelector`.
*   **Pod Affinity (Привязка к подам)**: Размещает под на том же узле или в той же топологии, где уже запущены другие поды. Используется для совместного размещения связанных компонентов (например, приложение и кэш).
*   **Pod Anti-Affinity (Избегание подов)**: Размещает поды на разных узлах или в разных топологиях относительно других подов. Используется для обеспечения высокой доступности путем распределения реплик.
*   **Topology Spread Constraints (Ограничения по распространению в топологии)**: Механизм для равномерного распределения подов по доменам отказа (узлам, зонам, регионам). Более продвинутая альтернатива `podAntiAffinity`.

---

#### Типы правил

*   `requiredDuringScheduling...` (**Жесткое правило**): Под будет размещен, **только если** правило выполнено. Если подходящих узлов нет, под остается в состоянии `Pending`.
*   `preferredDuringScheduling...` (**Мягкое правило**): Планировщик *постарается* выполнить правило, но если это невозможно, под все равно будет размещен на доступном узле. Правилам можно назначать вес (`weight` от 1 до 100) для приоритезации.

#### Поведение после запуска

*   `...IgnoredDuringExecution`: Правило применяется **только один раз** в момент планирования. Изменения меток на узлах или подах после запуска **не влияют** на уже работающий под. Это стандартное поведение.
*   `...RequiredDuringExecution`: Правило **продолжает действовать** и после запуска. Если метки на узле изменятся так, что правило перестанет выполняться, Kubernetes **выселит (evict)** под с этого узла. Используется реже и только для `nodeAffinity`.

## 2. Основные концепции

### Сравнение механизмов планирования

*   **`nodeAffinity` vs. `Taints/Tolerations`**
    *   **`nodeAffinity` (Притяжение)**: Под "хочет" быть размещенным на узле с определенными метками.
    *   **`Taints/Tolerations` (Отталкивание)**: Узел с `taint` не позволяет подам размещаться на нем, если у них нет соответствующего `toleration`.
    *   Эти механизмы часто используются вместе: `taint` для резервирования узлов под специальные задачи и `nodeAffinity` для целенаправленного размещения на них нужных подов.

*   **`podAntiAffinity` vs. `TopologySpreadConstraints`**
    *   **`podAntiAffinity`** работает по бинарному принципу: "размещать вместе" или "не размещать вместе" в рамках одной топологии. Он не умеет балансировать нагрузку. Например, при `podAntiAffinity` для 10 подов на 3-х узлах возможно распределение `1-1-8`, что формально не нарушает правило, но является неравномерным.
    *   **`topologySpreadConstraints`** решает проблему балансировки. Он следит, чтобы количество подов в каждом домене топологии не отличалось более чем на `maxSkew`, обеспечивая равномерное распределение.

### Ключевые поля и операторы

*   **`topologyKey`**: Определяет "область" применения правила (узел, зона доступности, регион). Планировщик ищет поды с нужными метками в пределах этой топологии.
    *   `kubernetes.io/hostname`: Область — один узел.
    *   `topology.kubernetes.io/zone`: Область — одна зона доступности.
    *   `topology.kubernetes.io/region`: Область — один регион.

*   **Операторы `nodeAffinity`**:
    *   `In`, `NotIn`: Значение метки должно/не должно совпадать с одним из указанных.
    *   `Exists`, `DoesNotExist`: Узел должен/не должен иметь метку с указанным ключом.
    *   `Gt`, `Lt`: Значение метки (число) должно быть больше или меньше указанного.

*   **Поля `topologySpreadConstraints`**:
    *   `maxSkew`: Максимально допустимое отклонение в количестве подов между доменами.
    *   `whenUnsatisfiable`: Поведение при невозможности выполнить правило:
        *   `DoNotSchedule` (по умолчанию): Жесткое правило, под не будет запланирован.
        *   `ScheduleAnyway`: Мягкое правило, под будет размещен в наименее загруженном домене.
    *   `labelSelector`: Определяет, на какую группу подов распространяется правило.

## 3. Практические сценарии и рекомендации

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
# Равномерно распределить поды по зонам (жестко) и узлам (мягко).
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
          # Жесткое правило: под будет запущен ТОЛЬКО на узле с меткой disktype=ssd.
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
              # topologyKey определяет "область" применения правила.
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

### Рекомендации

*   **Гибкость и надежность:** Отдавайте предпочтение мягким правилам (`preferred...`). Жесткие правила (`required...`) могут сделать систему хрупкой: если ни один узел не удовлетворяет условиям, поды не будут запланированы.
*   **Опасность `required` anti-affinity:** Жесткое правило `podAntiAffinity` с `topologyKey: topology.kubernetes.io/zone` опасно. Если количество реплик превысит количество доступных зон, лишние поды никогда не будут запущены.
*   **Современный подход к HA:** Для высокой доступности и равномерного распределения `topologySpreadConstraints` является более мощным и гибким инструментом, чем `podAntiAffinity`.