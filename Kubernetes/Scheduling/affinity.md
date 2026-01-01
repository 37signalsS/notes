# Affinity и Anti-Affinity: Управление размещением подов в Kubernetes

## Определения

*   **Affinity** и **Anti-Affinity**: Правила, которые определяют, где должны (Affinity) или не должны (Anti-Affinity) размещаться поды. Являются более гибкой альтернативой `nodeSelector`.
*   **Node Affinity (Привязка к узлам)**: Позволяет размещать поды на узлах с определёнными метками (например, узлы с GPU или быстрыми дисками).
*   **Pod Affinity (Привязка к подам)**: Размещает поды на том же узле или в той же топологии, где уже запущены другие поды. Используется для совместного размещения связанных компонентов (например, приложение и кэш).
*   **Pod Anti-Affinity (Избегание подов)**: Размещает поды на разных узлах или в разных топологиях относительно других подов. Используется для обеспечения высокой доступности путем распределения реплик.
*   `requiredDuringScheduling...` (**Жесткое правило**): Под будет размещен, только если правило выполнено. Если подходящих узлов нет, под остается в состоянии `Pending`.
*   `preferredDuringScheduling...` (**Мягкое правило**): Планировщик *постарается* выполнить правило, но если это невозможно, под будет размещен на доступном узле. Правилам можно назначать вес (`weight` от 1 до 100) для приоритезации.
*   `...IgnoredDuringExecution`: Правило применяется **только один раз** в момент планирования. Изменения меток на узлах или подах после запуска **не влияют** на уже работающий под. Это стандартное поведение.
*   `...RequiredDuringExecution`: Правило **продолжает действовать** и после запуска. Если метки на узле изменятся так, что правило перестанет выполняться, Kubernetes **выселит (evict)** под с этого узла. Используется реже (только для `nodeAffinity`).

## Основные концепции

### Типы правил Affinity

Правила Affinity состоят из типа (`required` или `preferred`) и поведения после запуска.

*   `requiredDuringScheduling...`: Жесткое правило.
*   `preferredDuringScheduling...`: Мягкое правило.

### Поведение после запуска

*   `...IgnoredDuringExecution`: Правило применяется однократно при планировании.
*   `...RequiredDuringExecution`: Правило действует постоянно, приводя к выселению пода при изменении меток узла.

### Affinity vs. Taints and Tolerations

*   **`Taints and Tolerations`**: Механизм **отталкивания**. Нода с `taint` не позволяет подам размещаться на ней без соответствующего `toleration`.
*   **`nodeAffinity`**: Механизм **притяжения**. Под "хочет" быть размещен на ноде с определенными метками.

Эти механизмы часто используются вместе: `taint` для резервирования узлов и `nodeAffinity` для целенаправленного размещения подов.

### Операторы для Node Affinity

*   `In`: Значение метки должно совпадать с одним из указанных.
*   `NotIn`: Значение метки не должно совпадать ни с одним из указанных.
*   `Exists`: Узел должен иметь метку с указанным ключом.
*   `DoesNotExist`: Узел не должен иметь метку с указанным ключом.
*   `Gt`: Значение метки (число) должно быть больше указанного.
*   `Lt`: Значение метки (число) должно быть меньше указанного.

### `topologyKey`

`topologyKey` определяет "область" применения правила (узел, зона доступности, регион). Планировщик ищет поды с нужными метками в пределах этой топологии.

*   `kubernetes.io/hostname`: Область — один узел.
*   `topology.kubernetes.io/zone`: Область — одна зона доступности.
*   `topology.kubernetes.io/region`: Область — один регион.

## Практические сценарии

### Комплексный пример Deployment

Пример Deployment, использующего все три типа affinity:

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
        # 1. Node Affinity: привязка к узлам
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
                    values:
                      - eu-central-1a

        # 2. Pod Affinity: привязка к другим подам
        podAffinity:
          # Жесткое правило: запускать этот под на том же узле, где уже есть под с меткой app=database.
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

        # 3. Pod Anti-Affinity: избегание других подов
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
          ports:
            - containerPort: 80
```

### Рекомендации и лучшие практики

*   **Высокая доступность (High Availability)**: Для stateless-приложений используйте `podAntiAffinity` для распределения реплик по разным узлам (`topologyKey: kubernetes.io/hostname`) или зонам доступности (`topologyKey: topology.kubernetes.io/zone`) для предотвращения единой точки отказа.
    ```yaml
    spec:
      affinity:
        podAntiAffinity:
          # Мягкое правило: стараться не запускать поды этого Deployment'а на одном и том же узле.
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: api-server # метка подов, которые не должны располагаться рядом
                # Разделяем поды в пределах одного узла
                topologyKey: kubernetes.io/hostname
            - weight: 50
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: api-server
                # Разделяем поды по разным зонам доступности
                topologyKey: topology.kubernetes.io/zone
    ```

*   **Производительность:** Используйте `podAffinity` для компонентов, которые интенсивно обмениваются данными (например, приложение и кэш Redis). Размещение их на одном узле (`topologyKey: kubernetes.io/hostname`) минимизирует сетевую задержку и повышает скорость отклика.
*   **Работа со специализированным оборудованием:** Используйте `nodeAffinity` для подов, требующих специфических ресурсов, таких как GPU (`nvidia.com/gpu`), быстрые диски (`disk-type: ssd`) или определенные архитектуры CPU.
*   **Гибкость и надежность:** Отдавайте предпочтение мягким правилам (`preferred...`) перед жесткими (`required...`). Жесткие правила могут сделать систему хрупкой: если ни один узел не удовлетворяет условиям, поды не будут запланированы. Мягкие правила обеспечивают более гибкое и отказоустойчивое размещение.
*   **Избегайте межзонного anti-affinity с `required`:** Жесткое правило `podAntiAffinity` с `topologyKey: topology.kubernetes.io/zone` может быть опасным. Если количество реплик превысит количество доступных зон, лишние поды никогда не будут запущены.