# Бюджет прерывания подов (Pod Disruption Budget, PDB)

## Определения

**Pod Disruption Budget (PDB)** — объект Kubernetes (API `policy/v1`), ограничивающий количество подов, которые могут быть одновременно недоступны в результате *добровольных прерываний*.

> **Архитектурное правило:** PDB защищает **доступность сервиса**, а не данные. Для защиты данных используются PV/PVC, бэкапы и репликация на уровне самого приложения. PDB не спасет от потери данных, только от простоя при обслуживании кластера.

**Добровольные прерывания (Voluntary Disruptions)** — преднамеренные операции, инициируемые администратором кластера или автоматикой:
* Drain узла (`kubectl drain`) для обновления ОС или ядра.
* Освобождение пустого узла автоскейлерами (Cluster Autoscaler, Karpenter).
* Удаление подов для дефрагментации или балансировки (Descheduler).
* Вытеснение по приоритету (Preemption), если планировщик пытается разместить более важный под.

**Недобровольные прерывания (Involuntary Disruptions)** — внезапные сбои, от которых PDB **не может защитить** (так как они не используют Eviction API):
* Аппаратный сбой узла (Kernel Panic, отказ диска, потеря питания).
* Удаление виртуальной машины на уровне облачного провайдера (например, изъятие Spot-инстанса).
* OOMKilled (Out Of Memory) на уровне контейнера.
* Node Pressure Eviction (выселение Kubelet'ом из-за острой нехватки памяти или диска на узле).

**Eviction API** — внутренний механизм Kubernetes, через который проходят запросы на безопасное выселение подов. PDB перехватывает запросы именно к этому API. Прямое удаление пода (`kubectl delete pod`) **игнорирует PDB**.

## Основные концепции

### Поддерживаемые контроллеры и ограничения

PDB работает с нативными контроллерами (Deployment, StatefulSet, ReplicaSet) и **кастомными контроллерами** (операторы на Go).
* **DaemonSet**: Применение PDB к DaemonSet не имеет смысла, так как на выселяемом узле может быть только один такой под, и он не может "переехать" на другие узлы.
* **Jobs**: Применение PDB к Jobs бессмысленно, так как задача должна просто завершиться. Контроллер Job сам создаст замену при сбое.

### Архитектурная роль PDB

Без PDB Kubernetes может одновременно выселить слишком много реплик приложения во время масштабных работ по техническому обслуживанию (например, обновление пула узлов через Cluster Autoscaler). PDB выступает **контрактом (SLA)** между владельцем приложения (Application Owner) и администратором кластера (Cluster Admin). Он заставляет инфраструктурные инструменты уважать требования доступности бизнес-логики.

PDB критически важен для:
* **Высокодоступных API**: Гарантирует наличие реплик для бесперебойной обработки трафика.
* **Stateful-сервисов (Quorum-based)**: Предотвращает развал кворума в etcd, Kafka, ZooKeeper при одновременном выселении нескольких участников.

### Ключевые преимущества PDB

1. **Обеспечение доступности приложений**: Гарантируют, что минимальное количество реплик остается в сети во время добровольных сбоев, предотвращая перебои в обслуживании.
2. **Управление вытеснением**: Процесс обслуживания кластера (обновление узлов, применение патчей) становится постепенным и предсказуемым, не перегружая оставшиеся реплики.
3. **Повышение устойчивости при масштабировании**: Бюджеты предотвращают слишком агрессивное масштабирование вниз (Scale-Down), сохраняя критические сервисы функциональными.
4. **Повышение стабильности при автомасштабировании**: PDB заставляет Autoscaler учитывать потребности приложения, предотвращая одновременное завершение слишком большого количества подов, что могло бы вызвать деградацию качества обслуживания.

### Принцип работы

1. Пользователь или система инициирует операцию, требующую удаления пода (например, `kubectl drain`).
2. Kubernetes отправляет запрос к **Eviction API** (подзапрос к Pod).
3. PDB проверяет, не нарушит ли выселение пода бюджет доступности.
4. Если бюджет соблюдается — под выселяется немедленно.
5. Если бюджет нарушается — операция приостанавливается до восстановления доступности.

### Параметры конфигурации

| Параметр | Описание | Примеры |
|----------|----------|---------|
| `selector` | Метки подов, подпадающих под защиту | `matchLabels: app: web` |
| `minAvailable` | Минимальное количество/процент доступных подов | `3` или `50%` |
| `maxUnavailable` | Максимальное количество/процент недоступных подов | `1` или `25%` |

**Важно:** Можно указать только `minAvailable` **или** `maxUnavailable`, не оба одновременно.

### Взаимодействие PDB с Rolling Update

**PDB не ограничивает Rolling Update.** Стратегия обновления управляется spec Deployment (`maxSurge`, `maxUnavailable`), а не PDB. Во время обновления:

* Deployment создаёт новые поды согласно своей стратегии
* PDB учитывает общее количество доступных подов (старых + новых)
* Если Rolling Update нарушает PDB — обновление продолжается, но другие eviction-операции будут заблокированы

### Сравнение: PDB maxUnavailable vs Deployment maxUnavailable

Параметр `maxUnavailable` существует и в PDB, и в стратегии Deployment — но управляет он разными процессами:

| Характеристика | PDB `maxUnavailable` | Deployment `maxUnavailable` |
|:---------------|:--------------------|:---------------------------|
| **Где задаётся** | В манифесте PDB (`policy/v1`) | В `spec.strategy.rollingUpdate` Deployment |
| **Что контролирует** | Добровольные выселения через Eviction API (drain, обновление нод, scale-down) | Rolling update Deployment (замена подов при деплое новой версии) |
| **Действие** | Блокирует eviction, если нарушен лимит | Определяет, сколько старых подов можно остановить одновременно |
| **Влияние на drain** | **Прямое** — PDB может заблокировать drain | **Косвенное** — Deployment сам создаёт замену подов при eviction |
| **По умолчанию** | Не задан (поведение не ограничено) | `25%` |

**Ключевое отличие:** PDB срабатывает на Eviction API (drain ноды, обслуживание), а Deployment `maxUnavailable` работает только в рамках rolling update. Если PDB не настроен — drain выселит любое количество подов без ограничений. Если не настроен `maxUnavailable` в Deployment — rolling update будет использовать значение по умолчанию 25%.

### Взаимодействие PDB с недобровольными сбоями

Хотя PDB не может отменить отключение питания сервера, он **учитывает** такие потери в своем бюджете. 

**Сценарий:** У вас есть Deployment (5 реплик) и PDB (`minAvailable: 4`).
1. Внезапно умирает узел, унося с собой 2 пода.
2. В кластере остается 3 здоровых пода (`currentHealthy: 3`).
3. Администратор запускает `kubectl drain` на другом узле, где работает еще один под этого Deployment.
4. **Eviction API блокирует drain**, так как `currentHealthy` (3) уже меньше `minAvailable` (4). 
5. Drain будет висеть в ожидании, пока Controller Manager не пересоздаст упавшие поды на здоровых узлах и они не перейдут в статус `Ready`.

Это важнейшая механика предотвращения каскадных отказов. Система защищает себя от намеренного ухудшения ситуации, когда часть инфраструктуры уже пострадала.

### Политика выселения нездоровых подов (Unhealthy Pod Eviction Policy)

> **Stable (GA) с Kubernetes 1.31**

PDB содержит поле `spec.unhealthyPodEvictionPolicy`, определяющее критерии выселения подов, которые не прошли пробы жизнеспособности (Readiness Probe) или находятся в аварийном состоянии. Эта функция позволяет избежать блокировки обслуживания узлов из-за подов, которые не могут стать здоровыми.

**Что считается «нездоровым» подом:**

* Под в статусе `Running`, но без `Ready=True` (не прошёл Readiness Probe)
* Под в `CrashLoopBackOff` (циклические перезапуски из-за ошибок или мисконфигурации)
* Под, завершающийся с ошибкой и перезапускаемый kubelet

| Значение | Поведение |
|----------|-----------|
| `IfHealthyBudget` (по умолчанию) | Нездоровые поды могут быть выселены **только если** `currentHealthy >= desiredHealthy`. Если здоровых подов достаточно для соблюдения PDB — проблемные поды выселяются (переезжают на другую ноду). Если здоровых подов **недостаточно** — выселение нездоровых подов **блокируется**, давая им шанс восстановиться |
| `AlwaysAllow` | Нездоровые поды могут быть выселены **независимо** от состояния PDB. Менеджеры кластера могут принудительно перенести проблемные поды без ожидания восстановления |

**Как это работает на практике:**

1. **`IfHealthyBudget`** — если Deployment имеет 3 реплики, PDB `minAvailable: 2`, и все 3 пода работают (`currentHealthy = 3`), но один из них в `CrashLoopBackOff` — этот под может быть выселен, так как оставшиеся 2 здоровых пода удовлетворяют PDB. Если же один под уже вышел из строя (`currentHealthy = 2`), выселение проблемного пода **блокируется** — kubelet даёт ему шанс перезапуститься и стать `Ready`.

2. **`AlwaysAllow`** — независимо от количества здоровых подов, проблемный под будет выселен при drain ноды. Это ускоряет обслуживание, но под может не получить шанса восстановиться.

**Влияние на drain нод:**

* При `IfHealthyBudget` drain может **заблокироваться**, если в кластере есть поды в `CrashLoopBackOff` и здоровых подов недостаточно для соблюдения PDB
* При `AlwaysAllow` drain продолжится, проблемные поды будут выселены принудительно

**Рекомендация:** Используйте `AlwaysAllow` для приложений, которые некорректно завершают работу при drain, или для сценариев, где проблемные поды нужно перенести немедленно. Используйте `IfHealthyBudget` по умолчанию для приложений, которым нужно время на восстановление после сбоя.

### Округление процентов

При указании процентов значения всегда округляются **в большую** сторону:

| Реплик | `minAvailable: 30%` | `minAvailable: 35%` | `maxUnavailable: 25%` |
|--------|---------------------|---------------------|----------------------|
| 10 | 3 пода | 4 пода | 2 пода |
| 7 | 3 пода | 3 пода | 2 пода |
| 3 | 1 под | 2 пода | 1 под |

### Диагностика состояния PDB

#### Проверка через kubectl

```bash
# Список всех PDB
kubectl get pdb -A
# → 
# NAMESPACE   NAME      MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# default     web-pdb   80%             N/A               1                     10m

# Детальная информация
kubectl describe pdb web-pdb -n default
```

#### Статус и условия (Status Conditions)

В новых версиях Kubernetes (1.30+) статус PDB содержит поле `conditions`, которое позволяет программно и визуально определить причину блокировки выселения.

| Тип условия | Статус | Причина (Reason) | Описание |
|-------------|--------|------------------|----------|
| **`DisruptionAllowed`** | `True` | `SufficientPods` | Выселение разрешено: достаточно здоровых подов |
| **`DisruptionAllowed`** | `False` | `InsufficientPods` | Выселение заблокировано: достигнут лимит доступности |
| **`DisruptionAllowed`** | `False` | `SyncFailed` | Ошибка контроллера (например, ошибка в селекторе) |

#### Пример вывода `kubectl get pdb`

```
NAME          MIN AVAILABLE   CURRENT   DESIRED   ALLOWED DISRUPTIONS   AGE
web-pdb       80%             5         5         1                     10m
kafka-pdb     N/A             3         3         1                     5m
```

| Поле вывода | API поле | Описание |
|------|----------|----------|
| `MIN AVAILABLE` | `spec.minAvailable` / `spec.maxUnavailable` | Настроенный бюджет |
| `CURRENT` | `status.currentHealthy` | Текущее количество здоровых подов (с `Ready=True`) |
| `DESIRED` | `status.desiredHealthy` | Ожидаемое минимальное количество здоровых подов |
| `ALLOWED DISRUPTIONS` | `status.disruptionsAllowed` | Сколько подов можно выселить без нарушения PDB |
| — | `status.expectedPods` | Общее количество подов, найденных по селектору |

**`currentHealthy`** считает только поды с `status.conditions[type: Ready].status: True`. Поды в `CrashLoopBackOff`, `Pending` или без пройденной Readiness Probe не учитываются (если не настроена политика `AlwaysAllow`).

### Ограничения для ad-hoc подов (без контроллера)

Если PDB используется с подами, которые **не управляются контроллером** (Deployment, StatefulSet, ReplicaSet и т.д.):

| Ограничение | Описание |
|-------------|----------|
| Только `minAvailable` | Параметр `maxUnavailable` **недоступен** |
| Только абсолютные числа | Проценты **не поддерживаются** — Kubernetes не знает желаемое количество подов |
| Координация вручную | Владелец приложения должен сам отслеживать количество подов |

**Рекомендация:** Всегда используйте контроллеры верхнего уровня для управления подами — это обеспечивает корректную работу PDB со всеми параметрами.

### Пересекающиеся PDB

Если под попадает под селекторы **нескольких PDB одновременно**, Eviction API требует разрешения **всех** PDB. Под не может быть выселен, если хотя бы один PDB блокирует операцию.

**Пример проблемы:** Два PDB с одинаковым `matchLabels: app: web` создают дублирующую защиту. Eviction будет заблокирован, если хотя бы один из PDB не позволяет выселить под.

**Рекомендация:** Избегайте дублирующих селекторов. Каждый набор подов должен управляться одним PDB. Исключение — сценарии миграции, когда поды временно покрываются двумя PDB при переходе из одного в другой.

### Пустой селектор

Поведение пустого `selector` зависит от версии API:

| API версия | Поведение пустого `selector` |
|------------|------------------------------|
| `policy/v1` (Kubernetes 1.21+) | Сопоставляет **все поды** в namespace |
| `policy/v1beta1` (до 1.21) | **Не сопоставляет** ничего |

**Рекомендация:** Всегда явно указывайте `matchLabels` в селекторе, чтобы избежать непреднамеренного сопоставления всех подов.

### Выбор между minAvailable и maxUnavailable

**`maxUnavailable` предпочтительнее** для большинства сценариев — он автоматически адаптируется к изменению количества реплик. При масштабировании вверх или вниз процент допустимых disruptions остаётся пропорциональным.

**`minAvailable` полезен** когда известен абсолютный минимум для работоспособности приложения (например, кворум из 3 для 5-нодового кластера).

### Ограничение: `maxUnavailable: 0` / `minAvailable: 100%`

Установка `maxUnavailable: 0` или `minAvailable: 100%` **полностью блокирует** все добровольные выселения для данного PDB. Команда `kubectl drain` на нодах с такими подами завершится ошибкой. Для Deployment с единственной репликой это означает невозможность обновления.

## Предварительные требования

### Версии Kubernetes и feature gates

| Версия Kubernetes | Статус API | Feature gates | Примечания |
|-------------------|-----------|---------------|------------|
| 1.4+ | `policy/v1beta1` | PDB включён по умолчанию | Начальная реализация |
| 1.21+ | `policy/v1` (stable) | PDB стабилизирован | Рекомендуемая версия для production |
| 1.25+ | только `policy/v1` | — | `policy/v1beta1` удалён |
| 1.27+ | — | `PDBUnhealthyPolicy=true` (beta) | `spec.unhealthyPodEvictionPolicy` |
| 1.30+ | — | `PDBUnhealthyPolicy` (GA) | Политика нездоровых подов стабилизирована |
| 1.31+ | — | `PodDisruptionConditions` (GA) | `DisruptionTarget` condition на подах |
| 1.32+ | — | — | `policy/v1` единственная версия |

### Требования к окружению

**Перед использованием PDB убедитесь:**

```bash
# Проверка версии API (должна быть policy/v1)
kubectl api-versions | grep policy/v1
# → policy/v1

# Проверка наличия CRD/Resource
kubectl api-resources | grep poddisruptionbudgets
# → poddisruptionbudgets   pdb   policy/v1   true   PodDisruptionBudget

# Проверка feature gates (на master-ноде)
kubectl get --raw '/metrics' | grep -i pdb
# → наличие метрик controller подтверждает работу PDB
```

### Влияние ResourceQuota на PDB

**Порядок проверок при выселении:**
1. ResourceQuota проверяет, есть ли квота на создание нового пода (при перезапуске на другой ноде)
2. PDB проверяет бюджет доступности
3. Если квота исчерпана — под не может быть пересоздан, PDB блокирует drain (ожидание)

**Рекомендация:** При использовании ResourceQuota убедитесь, что квота позволяет временное превышение реплик (для перемещения подов при drain). Иначе drain зависнет даже при корректном PDB.

## Практические сценарии

### Сценарий 1: Базовый PDB с minAvailable

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-pdb
  namespace: default
spec:
  minAvailable: 80%  # Всегда доступно не менее 80% подов
  selector:
    matchLabels:
      app: web
```

### Сценарий 2: PDB с фиксированным количеством

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: payment-service-pdb
spec:
  minAvailable: 3  # Всегда доступно не менее 3 подов
  selector:
    matchLabels:
      app: payment-service
```

### Сценарий 3: PDB с maxUnavailable (для StatefulSet)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: kafka-pdb
spec:
  maxUnavailable: 1  # Одновременно недоступен только 1 под
  selector:
    matchLabels:
      app: kafka-broker
```

### Сценарий 4: PDB для критического сервиса (5 реплик)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: critical-api-pdb
spec:
  minAvailable: 4  # Из 5 реплик минимум 4 должны быть доступны
  selector:
    matchLabels:
      app: critical-api
      tier: backend
```

### Сценарий 5: PDB с процентом для масштабируемого приложения

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: scalable-app-pdb
spec:
  minAvailable: 66%  # Две трети подов всегда доступны
  selector:
    matchLabels:
      app: scalable-app
```

### Сценарий 6: Мониторинг PDB при drain узла

**Контекст:** При обслуживании узла (`kubectl drain`) важно отслеживать изменения PDB в реальном времени, чтобы понимать, какие поды выселяются, а какие заблокированы.

**Подготовка окружения (терминал 1) — мониторинг PDB:**

```bash
# Отслеживание изменений PDB в реальном времени
kubectl get pdb -w
```

**Пример вывода при drain:**

```
NAME      MIN AVAILABLE   CURRENT   DESIRED   ALLOWED DISRUPTIONS   AGE
ngx-pdb   2               3         3         1                     5m
# → После начала drain первого пода:
ngx-pdb   2               3         3         0                     5m
# → После успешного переезда первого пода:
ngx-pdb   2               3         3         1                     5m
```

**Выполнение drain (терминал 2):**

```bash
# Drain узла с игнорированием DaemonSet
kubectl drain node-01 --ignore-daemonsets --delete-emptydir-data
# → node/node-01 cordoned
# → evicting pod default/ngx-6799fc88d8-7j589
# → pod/ngx-6799fc88d8-7j589 evicted
# → node/node-01 drained
```

**Что происходит:**

1. PDB с `minAvailable: 2` и 3 репликами имеет `ALLOWED DISRUCTIONS = 1`
2. При начале drain первый под переходит в `Terminating` — `ALLOWED DISRUPTIONS` становится `0`
3. Второй под **не может быть выселен** — eviction блокируется PDB
4. После полного переезда первого пода на другую ноду и перехода в `Running` — `ALLOWED DISRUCTIONS` возвращается к `1`
5. Drain продолжает выселение следующего пода (по одному за раз)

**Параллельная проверка подов (терминал 3):**

```bash
# Отслеживание статуса подов
kubectl get pods -o wide -w
# → ngx-6799fc88d8-7j589   1/1   Terminating   0   5m   10.244.1.5   node-01
# → ngx-6799fc88d8-pk2z9   0/1   Pending       0   0s   <none>       node-02
# → ngx-6799fc88d8-pk2z9   1/1   Running       0   5s   10.244.2.8   node-02

# Проверка распределения по нодам
kubectl get pods -o wide
# → NAME                     READY   STATUS    IP           NODE
# → ngx-6799fc88d8-pk2z9     1/1     Running   10.244.2.8   node-02
```

### Сценарий 7: Управление сбоями при drain узла (пример с 6 репликами)

**Задача:** Гарантировать, что при обновлении узлов сервиса с 6 репликами всегда будет доступно достаточное количество экземпляров для обработки трафика без потери производительности.

**Конфигурация:**
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 4 # Всегда должно работать минимум 4 пода
  selector:
    matchLabels:
      app: my-app
```

**Как это работает:**
1. Если вы инициируете `kubectl drain` для узла, на котором находятся 3 пода этого приложения, Kubernetes не удалит их все сразу.
2. Система будет вытеснять поды постепенно, только когда на других (новых или существующих) узлах будет запущено и станет `Ready` достаточное количество реплик, чтобы общее число живых подов не упало ниже 4.
3. Это гарантирует бесперебойную работу сервиса на протяжении всего процесса обслуживания инфраструктуры.

**Важные наблюдения:**

* Если на целевой ноде **недостаточно ресурсов** (CPU/memory) для пересоздания пода — eviction **замораживается** до появления ресурсов
* Поды выселяются **последовательно по одному** — пока `ALLOWED DISRUCTIONS = 0`, новые eviction-запросы блокируются
* После восстановления бюджета drain автоматически продолжает работу
* Ошибки eviction в выводе drain (`error: evicting pod ... violates PodDisruptionBudget`) — **нормальное поведение**, drain повторяет попытку после восстановления бюджета

### Взаимодействие PDB с PriorityClass (Preemption)

**Preemption (вытеснение по приоритету)** — механизм, при котором kube-scheduler удаляет поды с низким приоритетом для размещения подов с высоким приоритетом.

**Важно:** По умолчанию Preemption **игнорирует PDB**. Это может привести к неожиданной потере доступности.

**Настройка учёта PDB при Preemption (Kubernetes 1.21+):**

Feature gate `PreferNominatedNodeWithPDB` (alpha в 1.26) и настройка `preemptionPolicy` на уровне PriorityClass:

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000000
preemptionPolicy: PreemptLowerPriority  # По умолчанию
# preemptionPolicy: Never  # Запретить preemption для этого класса
globalDefault: false
description: "Высокий приоритет для критических сервисов"
```

**Рекомендации:**

| Ситуация | Рекомендация |
|----------|--------------|
| Критичный сервис с жёстким PDB | Установите `preemptionPolicy: Never` для его PriorityClass |
| Необходимость preemption с учётом PDB | Включите feature gate `PreferNominatedNodeWithPDB` (1.26+) |
| Множественные PriorityClass | Тестируйте сценарии preemption в staging-окружении |

### Взаимодействие PDB с HPA (Horizontal Pod Autoscaler)

HPA и PDB работают на разных уровнях:
- **HPA** управляет количеством реплик (scale up/down)
- **PDB** ограничивает выселение подов

**Конфликты и решения:**

| Сценарий | Проблема | Решение |
|----------|----------|---------|
| HPA scale-down + жёсткий PDB | HPA не может удалить поды, так как PDB блокирует | Настройте `behavior.scaleDown` в HPA с учётом PDB |
| HPA scale-up + недостаток ресурсов | Новые поды не создаются, PDB не освобождается | Увеличьте ресурсы узлов или снизьте `minAvailable` |
| Одновременный drain + HPA scale-down | Двойное давление на доступность | Координируйте окна обслуживания с HPA |

**Пример настройки HPA с учётом PDB:**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web
  minReplicas: 3
  maxReplicas: 20
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10          # Не более 10% реплик за раз (учитывает PDB)
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Проверка совместимости HPA и PDB:**

```bash
# Проверка текущего количества реплик и PDB
kubectl get hpa web-hpa
# → REFERENCE          TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# → Deployment/web     45%/70%   3         20        5          10m

kubectl get pdb web-pdb
# → NAME      MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → web-pdb   3               N/A               2                     10m

# Если ALLOWED DISRUPTIONS = 0 — HPA не сможет уменьшить количество реплик
```

### Обновление PDB в -runtime

**Атомарное обновление PDB через `kubectl replace`:**

```bash
# Получить текущий PDB
kubectl get pdb web-pdb -o yaml > pdb-backup.yaml

# Редактировать локально
vim pdb-backup.yaml

# Применить изменения
kubectl replace -f pdb-backup.yaml
```

**Быстрое изменение через `kubectl patch`:**

```bash
# Изменить minAvailable
kubectl patch pdb web-pdb -p '{"spec":{"minAvailable":2}}' --type=merge

# Переключить на maxUnavailable
kubectl patch pdb web-pdb -p '{"spec":{"minAvailable":null,"maxUnavailable":1}}' --type=merge

# Изменить unhealthyPodEvictionPolicy
kubectl patch pdb web-pdb -p '{"spec":{"unhealthyPodEvictionPolicy":"AlwaysAllow"}}' --type=merge
```

**Важно:** PDB не поддерживает `kubectl apply` с `last-applied-configuration` — используйте `replace` или `patch`.

### Мониторинг PDB через Prometheus

**Метрики PDB (встроенные в kube-controller-manager):**

| Метрика | Описание |
|---------|----------|
| `pod_disruption_budgets` | Общее количество PDB в кластере |
| `pod_disruption_budgets_sync_total` | Количество успешных синхронизаций PDB |
| `pod_disruption_budgets_sync_errors_total` | Ошибки синхронизации PDB |

**PromQL-запросы для мониторинга:**

```promql
# Все PDB с нулевыми разрешёнными disruptions (заблокированные)
kube_poddisruptionbudget_status_desired_healthy - kube_poddisruptionbudget_status_current_healthy > 0

# Процент доступных disruptions по PDB
(kube_poddisruptionbudget_status_desired_healthy - kube_poddisruptionbudget_status_current_healthy) / kube_poddisruptionbudget_status_desired_healthy * 100

# PDB с ошибками синхронизации
rate(pod_disruption_budgets_sync_errors_total[5m]) > 0
```

**Алерт для Prometheus (пример):**

```yaml
groups:
  - name: pdb-alerts
    rules:
      - alert: PDBBlocked
        expr: kube_poddisruptionbudget_status_desired_healthy - kube_poddisruptionbudget_status_current_healthy > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "PDB {{ $labels.poddisruptionbudget }} заблокирован"
          description: "PDB в namespace {{ $labels.namespace }} не позволяет выселения уже 5 минут. Проверьте состояние подов."

      - alert: PDBAtRisk
        expr: kube_poddisruptionbudget_status_current_healthy / kube_poddisruptionbudget_status_desired_healthy < 1.2
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "PDB {{ $labels.poddisruptionbudget }} близок к лимиту"
          description: "Запас здоровых подов менее 20% от желаемого."
```

### Расширенный статус PDB (DisruptionTarget)

**Kubernetes 1.29+** добавил поле `status.disruptionTarget` — список подов, выселение которых одобрено, но ещё не завершено.

**Диагностика зависших выселений:**

```bash
# Проверка disruptionTarget
kubectl get pdb web-pdb -o jsonpath='{.status.disruptionTarget}'
# → [{"name":"web-abc12","uid":"..."}]

# Если список непустой, но поды не удаляются — возможные причины:
# - Finalizers блокируют удаление
# - PreStop hook завис
# - Проблемы с сетью (API server не может подтвердить удаление)
```

**Очистка зависших выселений:**

```bash
# Принудительное удаление пода с finalizers
kubectl patch pod web-abc12 -p '{"metadata":{"finalizers":null}}' --type=merge

# Или прямое удаление (обход PDB)
kubectl delete pod web-abc12 --grace-period=0 --force
```

### Edge Cases и особые сценарии

#### PDB и Ephemeral Containers

Ephemeral Containers (временные контейнеры для отладки) **не учитываются** в PDB. Они не влияют на `currentHealthy` и не защищаются PDB.

#### PDB и Admission Webhooks

Если в кластере настроены **Validating/Mutating Webhooks**:
- PDB проверяется **после** admission webhooks
- Webhook может заблокировать создание нового пода, что косвенно влияет на PDB (под не создаётся, бюджет не освобождается)

#### PDB и Pod Priority and Preemption

При использовании **Priority Classes**:
- PDB не учитывает приоритет подов при выселении
- Preemption может удалить под независимо от PDB (по умолчанию)
- Для защиты критичных подов используйте `preemptionPolicy: Never`

#### PDB и Topology Spread Constraints

**Topology Spread Constraints** (распределение подов по зонам) работает совместно с PDB:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 6
  template:
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: web
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-pdb
spec:
  minAvailable: 4  # Гарантирует, что при drain зоны останется достаточно подов
  selector:
    matchLabels:
      app: web
```

**Рекомендация:** Используйте PDB + topologySpreadConstraints для максимальной отказоустойчивости при обслуживании зон доступности.

#### PDB и Leader Election

Для приложений с **leader election** (например, Kubernetes controllers, кастомные операторы):
- PDB защищает от одновременного выселения всех реплик
- При выселении leader-пода происходит перевыбор лидера
- Используйте `maxUnavailable: 1` для минимизации частоты перевыборов

#### PDB и Graceful Shutdown

**Graceful Shutdown** (корректное завершение работы) влияет на PDB:
- `terminationGracePeriodSeconds` определяет время на завершение
- Под остаётся в статусе `Terminating` и учитывается в PDB как доступный
- Долгий graceful shutdown может замедлить drain

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: web
---
# В Deployment:
# spec.template.spec.terminationGracePeriodSeconds: 60  # Достаточно для завершения запросов
```

### Рекомендации по типам приложений

| Тип приложения | Рекомендация | Обоснование |
|----------------|--------------|-------------|
| **Stateless frontend** (веб-приложения) | `minAvailable: 90%` | Допустима небольшая деградация при плановых операциях |
| **Single-replica stateful** (одна реплика БД) | Без PDB, координация с администратором | PDB не спасёт — приложение не может работать в двух местах одновременно |
| **Quorum-based** (etcd, Consul, MongoDB) | `minAvailable` = размер кворума | Ниже кворума приложение полностью неработоспособно |
| **Multi-replica stateful** (Kafka, Cassandra) | `maxUnavailable: 1` | Последовательное обновление, сохранение кворума |
| **Batch Job** | Без PDB | Job controller сам создаст замену при сбое |

> **Примечание для single-replica stateful:** Если администратору кластера нужно выполнить drain ноды, он должен заранее согласовать с владельцем приложения время простоя, временно удалить PDB, выполнить drain, затем восстановить PDB. При `replicas: 1` и `minAvailable: 1` drain будет заблокирован — используйте `minAvailable: 0` или удаляйте под вручную.

**Различие Deployment и StatefulSet при замене подов во время drain:**

* **Deployment** — при терминации пода немедленно создаёт замену (с новым UID (Unique Identifier — уникальный идентификатор) и именем, например `web-abc → web-def`). Replacement-под может быть запланирован на другой ноде параллельно с завершением старого.
* **StatefulSet** — дожидается полного завершения старого пода (освобождения имени, например `web-0`), и только затем создаёт новый под с тем же именем (`web-0`), но с новым UID. Это гарантирует стабильность имён, что критично для stateful-приложений (базы данных, где `web-0` — мастер, `web-1` — слейв). Для StatefulSet используйте `maxUnavailable: 1` для последовательного обновления.

## Дополнительная информация

### Лучшие практики

* **Создавайте PDB для всех критических нагрузок** — это касается баз данных, веб-серверов и любых сервисов со строгими требованиями к аптайму.
* **Баланс между minAvailable и maxUnavailable**:
    * **Stateless-сервисы**: Могут использовать более агрессивную политику через `maxUnavailable` (например, разрешить отсутствие 20-30% подов).
    * **Stateful-сервисы**: Требуют строгой политики через `minAvailable` (например, размер кворума + 1).
* **Интеграция с HPA**: При использовании горизонтального масштабирования настраивайте PDB так, чтобы он корректно отражал текущее количество реплик. Предпочтительнее использовать **процентные значения** (`minAvailable: 80%`), чтобы бюджет автоматически адаптировался при изменении количества реплик от 3 до 10 и более. Настраивайте `behavior.scaleDown` в HPA с учётом PDB.
* **Мониторинг во время обслуживания**: Всегда проверяйте состояние PDB (`ALLOWED DISRUPTIONS`) перед и во время проведения работ (обновление узлов, rolling update), чтобы убедиться, что бюджеты применяются корректно и не блокируют процесс надолго.
* **Учитывайте время запуска пода** — если под запускается долго, используйте `maxUnavailable: 1`.
* **Тестируйте перед production** — проверяйте поведение PDB при drain.
* **Используйте с Pod Anti-Affinity** — для максимальной отказоустойчивости.
* **Избегайте `minAvailable: 100%`** — это заблокирует любые плановые операции.
* **Для StatefulSet используйте `maxUnavailable: 1`** — обеспечивает последовательное обновление.
* **Настройте `unhealthyPodEvictionPolicy: AlwaysAllow`** для системных сервисов и приложений с нестабильным стартом, чтобы избежать блокировки drain из-за подов в `CrashLoopBackOff`.
* **Координируйте PDB с ResourceQuota** — убедитесь, что квота позволяет временное превышение реплик при перемещении подов.
* **Используйте PDB с Topology Spread Constraints** для защиты при обслуживании зон доступности.
* **Мониторьте PDB через Prometheus** — настройте алерты на заблокированные PDB и низкий запас здоровых подов.

### Интеграции

PDB взаимодействует с другими компонентами экосистемы Kubernetes:

* **[Cluster Autoscaler](cluster_autoscaler_detailed.md)** — проверяет PDB перед удалением узла
* **[Karpenter](Karpenter/overview.md)** — учитывает PDB при консолидации узлов
* **[Node Maintenance](../Operations/node_maintenance.md)** — drain использует Eviction API с учётом PDB
* **[HPA (Horizontal Pod Autoscaler)](HPA/hpa_advanced.md)** — координация при scale-down
* **[PriorityClass](../Concepts/priorityclass.md)** — влияние preemption на PDB
* **[ResourceQuota](../Scheduling/qos_limit_and_requests.md)** — порядок проверок при выселении
* **[Taints и Tolerations](../Scheduling/taints_and_tolerations.md)** — taint-based eviction игнорирует PDB

### Условия прерывания пода (Pod Disruption Conditions)

> **Stable (GA) с Kubernetes 1.31**

Kubernetes добавляет условие `DisruptionTarget` к подам, которые выселяются в результате добровольных прерываний. Это позволяет контроллерам (например, Job controller) и системам мониторинга точно определять причину завершения работы пода. Поле `status.conditions[].reason` указывает точную причину выселения:

| Значение `reason` | Описание |
|-------------------|----------|
| `PreemptionByKubeScheduler` | Под вытеснен для размещения пода с более высоким приоритетом |
| `DeletionByTaintManager` | Удалён из-за taint ноды (`NoExecute`) |
| `EvictionByEvictionAPI` | Выселен через Eviction API (`kubectl drain`) |
| `DeletedInPlaceOrPhantomNode` | Под привязан к несуществующей ноде (удаление Pod Garbage Collector) |
| `EvictionByKubelet` | Kubelet проактивно удаляет поды для освобождения ресурсов (NodePressure eviction) |
| `TerminationByKubelet` | Нода выключается, kubelet завершает поды (фича в бете с 1.21, feature gate `NodeShutdown`) |

**Пример условия на поде:**

```yaml
status:
  conditions:
    - type: DisruptionTarget
      status: "True"
      reason: EvictionByEvictionAPI
```

**Применение:**

* **Мониторинг и алертинг** — отслеживание причин выселений для анализа проблем
* **Pod Garbage Collector** — маркирует выселенные поды как `finalized`
* **Jobs** — можно использовать disruption conditions как часть критериев завершения Job

**Прерванный disruption:** Процесс выселения пода может быть прерван, а затем возобновлён. В таких ситуациях условие `DisruptionTarget` может быть добавлено к пода, но фактическое удаление пода не произойдёт (например, из-за временных сбоев или багов). Через некоторое время Kubernetes автоматически очистит это условие, если под не был удалён.

### Эволюция API

| Версия Kubernetes | Изменения |
|-------------------|-----------|
| 1.4 | Введён PDB (API `policy/v1beta1`) |
| 1.21 | Стабилизация API `policy/v1` |
| 1.25 | Удаление `policy/v1beta1` |

### Разделение ролей: Cluster Admin и Application Owner

PDB служит **интерфейсом** между ролями с разным контекстом и зоной ответственности:

| Роль | Зона ответственности | Доступ |
|------|---------------------|--------|
| **Cluster Admin** | Инфраструктура: ноды, обновления, обслуживание | `kubectl drain`, управление узлами, без доступа к приложениям |
| **Application Owner** | Приложение: деплой, конфигурация, PDB | Деплой в свой namespace, без доступа к узлам кластера |

**Как PDB обеспечивает взаимодействие:**

1. Application Owner создаёт PDB с требованиями к доступности своего приложения
2. Cluster Admin выполняет drain ноды для обслуживания
3. PDB автоматически блокирует drain, если нарушение бюджета доступности произойдёт
4. Cluster Admin видит блокировку (`ALLOWED DISRUPTIONS = 0`) и ждёт, пока приложение восстановит доступность
5. После восстановления — drain продолжается

**Практический пример:**

* Deployment: `nginx` с 3 репликами, PDB `minAvailable: 2`
* Node-01: 2 пода, Control-Plane: 1 под
* Cluster Admin выполняет `kubectl drain node-01 --ignore-daemonsets`
* Первый pod переходит в `Terminating` → `ALLOWED DISRUPTIONS = 0`
* Второй pod **заблокирован** PDB — eviction повторяет попытку
* После переезда первого пода на Control-Plane и перехода в `Running` → `ALLOWED DISRUPTIONS = 1`
* Drain продолжает выселение второго пода

Это разделение критично в мультикомандных кластерах (shared clusters), где:

* Cluster Admin не знает требований доступности каждого приложения
* Application Owner не управляет инфраструктурой
* PDB гарантирует, что обслуживание узлов не нарушит SLA (Service Level Agreement — соглашение об уровне обслуживания) приложения

> **Рекомендация:** Даже если роли совмещены (один инженер и администрирует, и деплоит), PDB полезен при сотнях приложений — он предотвращает ситуации, когда при массовом drain забыли про критичный сервис.

### Сравнение механизмов выселения (Eviction)

PDB защищает **только** от добровольных прерываний через Eviction API (чаще всего это `kubectl drain` или выселение автоскейлером). Важно понимать, в каких случаях PDB **игнорируется**:

| Механизм выселения | Инициатор | Триггер | PDB учитывается? | Решение проблемы |
| :--- | :--- | :--- | :--- | :--- |
| **API Eviction** | Пользователь / Автоскейлер | `kubectl drain`, Scale-down | **ДА** | Дождаться `Ready` подов или исправить PDB |
| **Node Pressure Eviction** | `kubelet` | Нехватка Memory/Disk/PID | **НЕТ** | Оптимизировать лимиты, добавить ресурсы узлу |
| **Taint-based Eviction** | Node Controller | Узел перешел в `NotReady` | **НЕТ** | Настроить Tolerations или чинить узел |
| **Preemption** | Kube-scheduler | Попытка втиснуть `HighPriority` под | **НЕТ** | (Настраивается с K8s 1.21+, но по умолчанию игнорирует PDB) |
| **OOMKilled** | OOM Killer (Linux Kernel) | Контейнер превысил RAM лимит | **НЕТ** | [Right-sizing через VPA](./vpa_detailed.md) |

### Стратегии обслуживания всех нод кластера

Когда требуется обслуживание **всех** нод кластера (обновление ОС (Operating System — операционная система), замена железа), есть три подхода:

| Стратегия | Описание | Downtime | Стоимость | Сложность |
|-----------|----------|----------|-----------|-----------|
| **Принять downtime** | Последовательный drain → обслуживание → uncordon каждой ноды | Да | Минимальная | Низкая |
| **Failover-кластер** | Создать полный дублирующий кластер, переключить трафик (switch over) | Нет | Высокая (дублирование всех ресурсов) | Высокая |
| **Временная нода** | Добавить временную ноду → drain старых по одной → обслуживание → возврат | Нет (при достаточных ресурсах) | Средняя (оплата временной ноды) | Средняя |

**Последовательный drain всех нод (базовый подход):**

1. Drain node-1 → обслуживание → uncordon node-1 (поды возвращаются)
2. Drain node-2 → обслуживание → uncordon node-2
3. Повторять для всех нод
4. Ключевое: каждая нода должна быть возвращена в кластер **перед** drain следующей, иначе поды не смогут переехать (PDB заблокирует)

**Важно:** Drain **всех** нод одновременно невозможен — приложениям некуда переезжать. PDB не спасёт, если в кластере не останется рабочих нод.

**Для zero-downtime обновлений на уровне кластера:**

* Написать fault-tolerant приложения (устойчивые к потере части реплик)
* Использовать PDB + Pod Anti-Affinity (реплики на разных нодах)
* Комбинировать с autoscaling (временное увеличение ресурсов)
* Подготовить приложения к преднамеренным сбоям (Chaos Engineering)

### Типичные ошибки и нюансы

*   **PDB для одной реплики:** Если у приложения `replicas: 1` и настроен PDB `minAvailable: 1` (или `maxUnavailable: 0`), это **полностью заблокирует** `kubectl drain`. Администратор не сможет обслужить узел без ручного вмешательства.
    *   *Решение:* Используйте `maxUnavailable: 1` (что позволит временно отключить единственную реплику) или временно масштабируйте приложение до 2 реплик перед drain.
*   **Игнорирование времени запуска:** PDB считает под здоровым (`Ready`), как только Readiness Probe вернула успех. Если приложению нужно время после этого для прогрева кеша или загрузки данных, это может привести к деградации производительности при последовательном выселении подов.
    *   *Решение:* Настройте `readinessProbe` с учетом реальной готовности к нагрузке.
*   **Конфликт селекторов:** Если несколько PDB выбирают одни и те же поды, Kubernetes будет требовать соблюдения **всех** бюджетов. Это часто приводит к дедлокам при drain.
*   **PDB и Dry-run:** Команда `kubectl drain --dry-run` учитывает PDB. Это позволяет безопасно проверить, заблокирует ли PDB обслуживание узла, не выполняя реальных действий.

### Диагностика PDB-блокировок (Troubleshooting)

Когда `kubectl drain` зависает с сообщением вида `error: cannot evict pod as it would violate the pod's disruption budget`, выполните следующие шаги:

1.  **Найти проблемный PDB:** 
    `kubectl get pdb -A | grep 0` (ищем PDB, где `ALLOWED DISRUPTIONS` равен нулю).
2.  **Проверить статус PDB:**
    `kubectl describe pdb <name> -n <namespace>`
    Особое внимание обратите на поля `Current Healthy` и `Desired Healthy`. Если текущее количество меньше желаемого, PDB будет блокировать выселение.
3.  **Выявить причину недоступности подов:**
    Часто проблема не в самом PDB, а в том, что поды не могут запуститься на новых узлах (зависли в `Pending` из-за нехватки ресурсов или `CrashLoopBackOff` из-за ошибки в приложении). Используйте `kubectl get pods -n <namespace>` для проверки статуса.
4.  **Экстренное решение (Break-glass):**
    Если необходимо срочно освободить узел (например, из-за критического сбоя железа), администратор может временно удалить PDB (`kubectl delete pdb <name>`), выполнить drain и пересоздать PDB.

### Внешние ссылки

* [Официальная документация: Pod Disruption Budget](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
* [Документация: Eviction API](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/#eviction-api)
* [Блокировка PDB при drain](../Troubleshooting/Common_Errors/PodTerminating/pdb_blocking.md) — диагностика и решение проблем
* [Taints и Tolerations](../Scheduling/taints_and_tolerations.md) — taint-based eviction и его влияние на PDB
