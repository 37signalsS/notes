# Управление размещением подов: Affinity, Anti-Affinity и TopologySpreadConstraints

## Определения

* **Affinity (Притяжение)**: Правило, которое «притягивает» под к узлам или другим подам, обладающими определёнными характеристиками.
* **Anti-Affinity (Отталкивание)**: Правило, которое «отталкивает» под от узлов или других подов.
* **Node Affinity (Привязка к узлам)**: Правила в манифесте пода, определяющие предпочтения или требования к меткам узлов при планировании. Является эволюцией `nodeSelector`, предоставляя более гибкую логику, поддержку операторов и уровней строгости.
* **Pod Affinity (Привязка к подам)**: Размещает под на том же узле или в той же топологии, где уже запущены другие поды. Используется для совместного размещения связанных компонентов (например, приложение и кэш).
* **Pod Anti-Affinity (Избегание подов)**: Размещает поды на разных узлах или в разных топологиях относительно других подов. Используется для обеспечения высокой доступности путём распределения реплик.
* **Topology Spread Constraints (Ограничения по распространению в топологии)**: Механизм для равномерного распределения подов по доменам отказа (узлам, зонам, регионам). Более продвинутая альтернатива `podAntiAffinity`.
* **nodeName**: Прямое указание имени узла для размещения пода. Наиболее простой, но ограниченный метод (не использует планировщик, не работает с Taints/Tolerations/Affinity).
* **Topology Key (Ключ топологии)**: Метка узла, определяющая область (домен), в которой планировщик ищет поды или проверяет условия размещения.
* **Failure Domain (Домен отказа)**: Логическая группа ресурсов (узел, стойка, зона), которая может выйти из строя целиком.

---

## Основные концепции

### Типы правил

* `requiredDuringSchedulingIgnoredDuringExecution` (**Жёсткое правило**): Аналог `nodeSelector`. Под будет размещён **только если** правило выполнено. Если подходящих узлов нет, под остаётся в состоянии `Pending`.
* `preferredDuringSchedulingIgnoredDuringExecution` (**Мягкое правило**): Планировщик *постарается* выполнить правило, но если это невозможно, под всё равно будет размещён на доступном узле. Правилам назначается вес (`weight` от 1 до 100), где более высокий вес означает более высокий приоритет для планировщика.

### Поведение после запуска

* **IgnoredDuringExecution**: В обоих режимах (required и preferred) этот суффикс означает, что если метки на узле изменятся после запуска пода так, что они перестанут соответствовать правилам аффинити, под **продолжит работать**. Пересчёт размещения и выселение не производятся.
* `...RequiredDuringExecution`: Теоретически предполагает, что правило **продолжает действовать** и после запуска. Если метки на узле изменятся так, что правило перестанет выполняться, Kubernetes должен **выселить (evict)** под с этого узла. 
    * *Примечание:* Для `nodeAffinity` это поле (`requiredDuringSchedulingRequiredDuringExecution`) зарезервировано, но полноценная поддержка автоматического выселения во всех сценариях зависит от версии и конфигурации контроллеров.

### Сравнение механизмов планирования

* **Node Affinity против Taints и Tolerations**
  * **Направление действия**:
    * **Taints & Tolerations работают «от ноды»**: Нода «отталкивает» все поды, которые не имеют соответствующего `toleration`.
    * **Node Affinity работает «от пода»**: Под сам «тянется» к нодам с определёнными метками.
  * **Применение**:
    * **Taints + Tolerations**: Используются для жёсткой изоляции узлов под специфические задачи (GPU, CI-воркеры, выделенные команды), чтобы на них не попадали «чужие» поды.
    * **Node Affinity**: Используется для направления подов на узлы с нужными характеристиками (тип диска, зона доступности, архитектура процессора).
  * **Совместное использование**: В связке Taints удерживают лишние поды подальше, а Node Affinity гарантирует, что нужные поды попадут именно туда, где они должны работать.

* **`podAntiAffinity` против `TopologySpreadConstraints`**
  * **`podAntiAffinity`** работает по бинарному принципу: «размещать вместе» или «не размещать вместе» в рамках одной топологии. Он не умеет балансировать нагрузку. Например, при `podAntiAffinity` для 10 подов на 3-х узлах возможно распределение `1-1-8`, что формально не нарушает правило, но является неравномерным.
  * **`topologySpreadConstraints`** решает проблему балансировки. Он следит, чтобы количество подов в каждом домене топологии не отличалось более чем на `maxSkew`, обеспечивая равномерное распределение.

### Ключевые поля и операторы

* **`topologyKey`**: Определяет «область» применения правила (узел, зона доступности, регион). Планировщик ищет поды с нужными метками в пределах этой топологии.
  * `kubernetes.io/hostname`: Область — один узел.
  * `topology.kubernetes.io/zone`: Область — одна зона доступности.
  * `topology.kubernetes.io/region`: Область — один регион.

* **Операторы `nodeAffinity`**:
  * `In` / `NotIn`: Значение метки входит или не входит в указанный список.
  * `Exists` / `DoesNotExist`: Ключ метки присутствует или отсутствует на узле.
  * `Gt` / `Lt`: Числовое сравнение значений меток (только для `nodeAffinity`).
  * `NotIn` и `DoesNotExist` позволяют реализовать поведение **anti-affinity** на уровне самого пода (отталкивание от нод с определёнными метками без использования taints).

* **Поля `topologySpreadConstraints`**:
  * `maxSkew`: Максимально допустимое отклонение в количестве подов между доменами.
  * `whenUnsatisfiable`: Поведение при невозможности выполнить правило:
    * `DoNotSchedule` (по умолчанию): Жёсткое правило, под не будет запланирован.
    * `ScheduleAnyway`: Мягкое правило, под будет размещён в наименее загруженном домене.
  * `labelSelector`: Определяет, на какую группу подов распространяется правило.
  * `nodeAffinityPolicy` (Beta, 1.26+): Политика учёта `nodeAffinity` и `nodeSelector` при расчёте топологии.
    * `Honor` (по умолчанию): В расчёт включаются только узлы, удовлетворяющие `nodeAffinity`/`nodeSelector`.
    * `Ignore`: В расчёт включаются все узлы.
  * `nodeTaintsPolicy` (Beta, 1.26+): Политика учёта Taints/Tolerations при расчёте топологии.
    * `Honor` (по умолчанию): В расчёт включаются только узлы без Taints или с соответствующими Tolerations.
    * `Ignore`: В расчёт включаются все узлы.
  * `matchLabelKeys` (Beta, 1.27+): Список ключей меток пода для динамического определения группы распределения. Это позволяет планировщику учитывать только поды с тем же значением метки (например, `pod-template-hash`), что критично для правильного распределения во время Rolling Update.
  * `minDomains` (**GA, 1.30+**): Минимальное количество доменов топологии, по которым следует распределять поды. Помогает избежать концентрации подов в малом количестве доступных зон.

---

## Практические сценарии

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

Используйте `podAffinity` для компонентов, которые интенсивно обмениваются данными (например, приложение и кэш или два микросервиса с частыми вызовами друг друга). Размещение их на одном узле (`topologyKey: kubernetes.io/hostname`) минимизирует сетевую задержку и нагрузку на сетевой стек кластера.

**Пример (совместное размещение Сервиса А и Сервиса Б):**

```yaml
# В манифесте Сервиса Б указываем аффинити к Сервису А
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app: service-a
      topologyKey: kubernetes.io/hostname
```

**Использование matchLabelKeys (Beta 1.31+) для Affinity:**
Позволяет более точно настраивать близость подов, например, во время обновления, чтобы новые поды тянулись только к новым подам своей версии.

```yaml
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app: service-a
      topologyKey: kubernetes.io/hostname
      matchLabelKeys:
      - pod-template-hash
```

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

### Сценарий 4: Обеспечение высокой доступности и предотвращение перегрузки узлов (HA)

**Задача:** Развернуть приложение с несколькими репликами так, чтобы при падении одного или нескольких узлов нагрузка не концентрировалась на оставшихся живых узлах.

**Проблема (кейс из практики):** Если не настроено распределение подов, при падении узла все его поды могут переехать на один-два оставшихся воркера. Это создает критическую нагрузку на CPU/Memory этих узлов, что может привести к их "зависанию" и падению всего кластера.

**Решение:** 
1. Использовать `podAntiAffinity` с `topologyKey: kubernetes.io/hostname` для обязательного или предпочтительного разнесения реплик по разным физическим серверам.
2. При восстановлении упавших узлов использовать **кордонирование** (`kubectl cordon`), чтобы новые поды не планировались на восстанавливающийся узел сразу в большом количестве.

```yaml
# Пример для Deployment'а FluentD с защитой от скучивания
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
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values:
                - fluentd-router
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: fluentd
        image: fluent/fluentd-kubernetes-daemonset:v1-debian-elasticsearch
```

**Как это работает:**
1. Планировщик размещает первую реплику на подходящем узле.
2. При размещении второй реплики планировщик видит, что на первом узле уже есть под с меткой `app: fluentd-router`.
3. Согласно правилу `podAntiAffinity`, планировщик исключает этот узел из списка кандидатов.
4. Все три реплики гарантированно окажутся на разных узлах (если их достаточно). Если узлов меньше 3, новые поды останутся в `Pending`.

---

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
* `0/10 nodes are available: 6 node(s) didn't match topology spread constraints` — нарушение ограничений Topology Spread (слишком большой перекос `maxSkew`).
* `0/1 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }` — попытка планирования на мастер-ноду без соответствующих tolerations.

---

## Дополнительная информация

### Интеграции

* **[HPA](../Autoscaling/HPA/index.md)**: Поды, создаваемые HPA, автоматически наследуют правила распределения.
* **[Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md)**: Совместное использование с Anti-Affinity гарантирует, что при обслуживании узлов (drain) приложение сохранит доступность, так как реплики разнесены по разным доменам.
* **Cluster Autoscaler**: При добавлении новых узлов CA учитывает требования `nodeAffinity` и `topologySpreadConstraints`.
* **[QoS классы](./qos_limit_and_requests.md)**: Влияют на приоритет при вытеснении (eviction), что важно учитывать при использовании `...RequiredDuringExecution`.

### Рекомендации

* **Гибкость важнее жёсткости:** Отдавайте предпочтение мягким правилам (`preferred...`). Жёсткие правила (`required...`) могут оставить поды в состоянии `Pending` при малейшем изменении состояния кластера.
* **Опасность жёсткого Anti-Affinity по зонам:** Использование `required` с `topologyKey: topology.kubernetes.io/zone` опасно: если одна зона выйдет из строя, поды не смогут переехать в другие зоны, так как нарушат правило "один под на зону".
* **Topology Spread — основной выбор для HA:** Для обеспечения равномерности и отказоустойчивости `topologySpreadConstraints` является более мощным инструментом, чем `podAntiAffinity`.
* **Производительность:** Избегайте `podAffinity` с очень широкими селекторами в кластерах более 500 узлов, так как это перегружает планировщик.
* **Обновление приложений:** При использовании Anti-Affinity в Deployment используйте `matchLabelKeys` (с версии 1.27 для Topology и 1.31 для Affinity), чтобы избежать ситуации, когда новые поды не могут встать на место старых во время Rolling Update.
* **Cross-Namespace:** Для аффинити к подам в других пространствах имен используйте поле `namespaces` или `namespaceSelector`.
