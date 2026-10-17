# Метки, аннотации и выбор узлов для Pod

**Актуально для:** Kubernetes 1.30+

## Определения

* **Labels (Метки)** — пары «ключ-значение», прикрепляемые к объектам Kubernetes (Pod, Node, Service и др.). Предназначены для идентификации, группировки и выборки объектов через селекторы (Selectors). Индексируются API-сервером в памяти и в etcd для быстрого поиска. Подробнее: [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md).
* **Annotations (Аннотации)** — неидентифицирующие пары «ключ-значение» для хранения вспомогательных неструктурированных метаданных (JSON-конфигурации, версионирование, параметры внешних агентов мониторинга и сборщиков логов). Не индексируются и не используются для фильтрации объектов селекторами.
* **Label Selector (Селектор меток)** — ключевой фильтрационный механизм Kubernetes. Поддерживает два типа: **на основе равенства** (`equality-based`: `=`, `==`, `!=`) и **на основе множеств** (`set-based`: `in`, `notin`, `exists`, `doesnotexist`). Применяется в контроллерах (Deployment, StatefulSet), сервисах (Service) и сетевых политиках (NetworkPolicy).
* **Node Selection (Выбор узлов)** — процесс ограничения набора узлов кластера, на которых разрешено запускать конкретный Pod.
* **nodeSelector** — базовый декларативный механизм привязки Pod к узлам по точным совпадениям меток. Принимает карту строк (`map[string]string`). Планировщик (`kube-scheduler`) назначает Pod только на узлы, содержащие абсолютно все указанные пары ключ-значение (логическое «И»).
* **nodeName** — способ жесткого назначения Pod на конкретный узел по его системному имени (`spec.nodeName`). Полностью обходит планировщик (`kube-scheduler`), игнорируя Taints, политики сходства и доступность ресурсов.
* **Системные метки узлов (Well-Known Labels)** — зарезервированные системные метки ядра Kubernetes (`kubernetes.io/*`, `k8s.io/*`), автоматически выставляемые `kubelet` или контроллерами топологии (`kubernetes.io/hostname`, `kubernetes.io/os`, `kubernetes.io/arch`, `node-role.kubernetes.io/*`, `topology.kubernetes.io/zone`).
* **Ключ топологии (Topology Key)** — имя метки узла, определяющее границу физического или логического домена отказа (сервер, стойка, серверный зал, дата-центр).

---

## Базовые концепции и архитектура

### Механизмы управления размещением

В Kubernetes предусмотрена многоуровневая система управления размещением подов на узлах:

| Механизм | Описание | Уровень сложности | Роль в планировании | Рекомендация для Production |
| :--- | :--- | :--- | :--- | :--- |
| `nodeSelector` | Фильтрация по точному совпадению меток | Низкий | Жесткий фильтр (`Filter`) | Базовый выбор пулов узлов (типы дисков, роли серверов) |
| [Node Affinity](../../Scheduling/affinity.md) | Гибкие правила с логическими операторами (`In`, `NotIn`, `Gt`, `Lt`) | Средний | Жесткий (`required`) и мягкий (`preferred`) | Основной стандарт для сложных топологий и балансировки |
| [Taints и Tolerations](../../Scheduling/taints_and_tolerations.md) | Механизм отталкивания нежелательных подов от узлов | Средний | Допуск (`Admission/Filter`) | Изоляция критических нод (Control Plane, GPU, выделенный контур) |
| `nodeName` | Прямая запись имени узла в манифест Pod | Минимальный | Обход планировщика | **Запрещен** для прикладных рабочих нагрузок (только системные утилиты) |

### Типы Label Selectors

Kubernetes поддерживает два формата селекторов меток в зависимости от ресурса:

#### 1. Equality-based (на основе равенства)
Используется в традиционных ресурсах (например, `spec.selector` у `Service`), а также в `kubectl`:
* `env = production` или `env == production` — ключ `env` обязан иметь значение `production`.
* `tier != frontend` — ключ `tier` не равен `frontend` либо вовсе отсутствует на объекте.

#### 2. Set-based (на основе множеств)
Современный подход, используемый в `spec.selector.matchExpressions` у контроллеров (`Deployment`, `DaemonSet`, `StatefulSet`, `Job`), в `NetworkPolicy` и `PodAffinity`:
* `In` — значение метки входит в заданный список (`env in (production, staging)`).
* `NotIn` — значение метки не входит в заданный список или ключ отсутствует (`tier notin (backup, test)`).
* `Exists` — ключ присутствует на объекте (любое значение, например `partition`).
* `DoesNotExist` — ключ отсутствует на объекте (`!partition`).

```bash
# Фильтрация по equality-based селектору
kubectl get pods -l env=production

# Фильтрация по set-based селектору
kubectl get pods -l "env in (production, staging),tier=frontend"

# Комбинированный селектор (проверка равенства, множества и отсутствия метки)
kubectl get pods -l "app=nginx,env in (prod,staging),!deprecated"

# Проверка наличия метки с любым значением
kubectl get pods -l "monitoring"
```

### Принцип работы nodeSelector в kube-scheduler

При планировании пода `kube-scheduler` выполняет двухфазный цикл:
1. **Filtering (Фильтрация / Predicates):** Планировщик отсеивает узлы, не способные принять Pod. На этой фазе плагин `NodeAffinity` проверяет поле `spec.nodeSelector`.
   * Для каждого узла проверяются все пары ключ-значение из `nodeSelector`.
   * Каждое условие вычисляется по логическому «И» (`AND`).
   * Если узел не имеет хотя бы одной указанной метки или ее значение не совпадает, узел исключается из списка кандидатов.
   * Если ни один узел не подошел, Pod переходит в статус `Pending` с событием `FailedScheduling`.
2. **Scoring (Оценка / Priorities):** Оставшиеся узлы ранжируются. Сам `nodeSelector` не участвует в начислении баллов (он либо пройден, либо нет; весовые коэффициенты доступны только в `Node Affinity`).

**Сравнение nodeSelector и Node Affinity:**

| Критерий | `nodeSelector` | Node Affinity (`spec.affinity.nodeAffinity`) |
| :--- | :--- | :--- |
| Синтаксис | Простая карта `key: value` | Структурированные `matchExpressions` и `matchFields` |
| Поддерживаемые операторы | Только точное совпадение (`=`) | `In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt`, `Lt` |
| Мягкие правила (Preferences) | Отсутствуют (только жесткий отказ) | Поддерживаются (`preferredDuringSchedulingIgnoredDuringExecution`) |
| Веса правил | Нет | Вес от 1 до 100 для приоритезации узлов |
| Изменение во время работы | Не выселяет работающий Pod | Игнорируется во время исполнения (`IgnoredDuringExecution`) |

### Особенности и риски прямого назначения через nodeName

Поле `spec.nodeName` заставляет систему обойти весь планировщик:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: direct-bound-pod
spec:
  nodeName: worker-node-03
  containers:
  - name: app
    image: nginx:1.27
```

**Архитектурный механизм:**
1. При отправке такого манифеста в API-сервер поле `spec.nodeName` уже заполнено.
2. `kube-scheduler` отслеживает только поды с пустым `spec.nodeName` (`spec.nodeName == ""`). Следовательно, планировщик полностью игнорирует данный Pod.
3. Демон `kubelet`, запущенный на сервере `worker-node-03`, обнаруживает через Watch-запрос, что ему назначен данный Pod, и напрямую приступает к запуску контейнеров.

**Опасности использования в Production:**
1. **Отсутствие отказоустойчивости:** Если узел `worker-node-03` выйдет из строя (Kernel Panic, отказ питания, сетевой сплит), Pod останется привязанным к мертвому узлу и не будет пересоздан на исправном оборудовании.
2. **Игнорирование Taints и ресурсов:** `kubelet` запускает Pod даже если на узле выставлены запрещающие тейны (`NoSchedule`) или на узле исчерпана память/процессор. Это ведет к падению контейнеров в состояние `OutOfmemory` или `Evicted`.
3. **Зависание при ошибке имени:** Если в имени узла допущена опечатка (например, `worker-node-99`), Pod навечно зависнет в фазе `Pending`, и ни один контроллер или планировщик не выдаст диагностического предупреждения.

> **Назначение в системной архитектуре:** `nodeName` исторически использовался контроллерами (в частности, `DaemonSet Controller` в старых версиях k8s) и служебными компонентами восстановления кластера (например, запуском статических подов kube-apiserver и etcd).

### Метки против Аннотаций: различия и внутренняя организация

| Характеристика | Метки (Labels) | Аннотации (Annotations) |
| :--- | :--- | :--- |
| **Основное назначение** | Идентификация, группировка, выборка объектов | Хранение структурированных метаданных, конфигураций |
| **Индексация API-сервером** | Индексируются в памяти API-сервера | Не индексируются, хранятся в JSON-теле объекта |
| **Использование в селекторах** | Да (`kubectl get -l`, Service, Deployment) | Нет (нельзя фильтровать через `--selector`) |
| **Ограничение длины ключа** | До 63 символов (плюс префикс DNS до 253 символов) | До 63 символов (плюс префикс DNS до 253 символов) |
| **Ограничение длины значения** | До 63 символов (буквы, цифры, дефис, точка, `_`) | Нет жесткого лимита на строку (общий размер объекта до 1–1.5 МБ в etcd) |
| **Формат данных** | Простые строки, строгий regex RFC 1123 | Любой текст: сериализованный JSON, PEM-сертификаты, base64 |

### Стандартные и служебные аннотации в практике DevOps/SRE

В инфраструктуре без облачных провайдеров аннотации служат ключевым средством интеграции компонентов экосистемы:

| Категория | Пример аннотации | Описание и влияние на систему |
| :--- | :--- | :--- |
| **Rollout / Аудит** | `kubernetes.io/change-cause` | Содержит причину ревизии, отображается в `kubectl rollout history` |
| **Мониторинг** | `prometheus.io/scrape: "true"` | Директива для Prometheus Service Discovery выполнять сбор метрик |
| | `prometheus.io/port: "9090"` | Порт экспортера метрик пода |
| | `prometheus.io/path: "/metrics"` | URI эндпоинта метрик |
| **Логирование** | `fluentbit.io/parser: "json"` | Указание сборщику Fluent Bit использовать специализированный парсер |
| **Ingress-контроллеры** | `nginx.ingress.kubernetes.io/backend-protocol` | Управление TLS/HTTP протоколом связи Ingress с бекендом |
| | `nginx.ingress.kubernetes.io/proxy-body-size` | Максимальный размер тела клиентского запроса (напр. `50m`) |
| **Безопасность (PSA)** | `pod-security.kubernetes.io/enforce` | Уровень изоляции неймспейса (`privileged`, `baseline`, `restricted`) |
| **Управление ревизиями** | `helm.sh/revision` | Номер установленной ревизии Helm-релиза |
| **SRE-эксплуатация** | `operations.company.com/runbook` | Прямая ссылка на инструкцию по дежурству (Runbook/Playbook) |
| | `operations.company.com/oncall` | Контактный канал или адрес дежурного инженера |

---

## Практические сценарии

### Сценарий 1: Маркировка оборудования узлов и целевая привязка Pod

Выделение серверов с высокоскоростными NVMe-накопителями и размещение подов базы данных в пределах заданного серверного зала / стойки (`zone-a`).

**Шаг 1: Маркировка узлов физического кластера**
```bash
# Маркировка типа дисковой подсистемы
kubectl label node worker-01.corp storage-tier=nvme

# Маркировка физической стойки / серверной зоны (On-Premise topology)
kubectl label node worker-01.corp topology.kubernetes.io/zone=zone-a

# Проверка назначенных меток
kubectl get node worker-01.corp --show-labels
# → NAME              STATUS   ROLES    AGE   VERSION   LABELS
# → worker-01.corp   Ready    <none>   45d   v1.30.0   storage-tier=nvme,topology.kubernetes.io/zone=zone-a,...
```

**Шаг 2: Манифест пода с селектором узлов**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: postgres-primary
  namespace: database
  labels:
    app.kubernetes.io/name: postgres
    app.kubernetes.io/component: primary
spec:
  nodeSelector:
    storage-tier: nvme
    topology.kubernetes.io/zone: zone-a
  containers:
  - name: postgres
    image: postgres:16.4
    resources:
      requests:
        cpu: "2"
        memory: 4Gi
      limits:
        cpu: "4"
        memory: 8Gi
    ports:
    - containerPort: 5432
      name: postgresql
```

**Шаг 3: Проверка успешного назначения и валидация**
```bash
# Проверка размещения пода на узле
kubectl get pod postgres-primary -n database -o wide
# → NAME               READY   STATUS    RESTARTS   AGE   IP            NODE              NOMINATED NODE   READINESS GATES
# → postgres-primary   1/1     Running   0          42s   10.244.1.45   worker-01.corp    <none>           <none>

# Диагностика в случае зависания в Pending
kubectl describe pod postgres-primary -n database | grep -A 4 "Events:"
# → Events:
# →   Type     Reason            Age   From               Message
# →   ----     ------            ----  ----               -------
# →   Warning  FailedScheduling  12s   default-scheduler  0/6 nodes are available: 6 node(s) didn't match Pod's node selector.
```

### Сценарий 2: Привязка DaemonSet к специализированным узлам

Запуск агентов сбора сетевого трафика и балансировки только на выделенных Edge/Ingress-серверах bare-metal инфраструктуры.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: edge-proxy-daemon
  namespace: infrastructure
  labels:
    app.kubernetes.io/name: edge-proxy
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: edge-proxy
  template:
    metadata:
      labels:
        app.kubernetes.io/name: edge-proxy
    spec:
      # Запуск только на серверах, имеющих роль ingress-маршрутизаторов
      nodeSelector:
        node-role.kubernetes.io/ingress: "true"
      containers:
      - name: proxy
        image: nginx:1.27
        ports:
        - containerPort: 80
          hostPort: 80
        - containerPort: 443
          hostPort: 443
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: "2"
            memory: 2Gi
```

**Валидация запуска:**
```bash
# Просмотр узлов с ролью ingress
kubectl get nodes -l node-role.kubernetes.io/ingress=true
# → NAME              STATUS   ROLES     AGE   VERSION
# → edge-01.corp     Ready    ingress   90d   v1.30.0
# → edge-02.corp     Ready    ingress   90d   v1.30.0

# Проверка размещения DaemonSet
kubectl get pods -n infrastructure -l app.kubernetes.io/name=edge-proxy -o wide
# → NAME                      READY   STATUS    NODE
# → edge-proxy-daemon-5x8qf   1/1     Running   edge-01.corp
# → edge-proxy-daemon-9m2kl   1/1     Running   edge-02.corp
```

### Сценарий 3: Переключение трафика Blue-Green через селекторы Service

Мгновенное переключение пользовательского трафика между версиями без перезапуска подов.

**Шаг 1: Развертывание Blue (текущей) и Green (новой) версий**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service-blue
  namespace: default
spec:
  replicas: 3
  selector:
    matchLabels:
      app: payment-api
      deployment-color: blue
  template:
    metadata:
      labels:
        app: payment-api
        deployment-color: blue
    spec:
      containers:
      - name: api
        image: payment-service:1.8.0
        ports:
        - containerPort: 8080
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service-green
  namespace: default
spec:
  replicas: 3
  selector:
    matchLabels:
      app: payment-api
      deployment-color: green
  template:
    metadata:
      labels:
        app: payment-api
        deployment-color: green
    spec:
      containers:
      - name: api
        image: payment-service:1.9.0
        ports:
        - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: payment-service
  namespace: default
spec:
  selector:
    app: payment-api
    deployment-color: blue    # Направляет трафик на Blue
  ports:
  - port: 80
    targetPort: 8080
```

**Шаг 2: Валидация и переключение Service на Green**
```bash
# Проверка текущих Endpoints сервиса (видны только IP подов Blue)
kubectl get endpoints payment-service
# → NAME              ENDPOINTS                                   AGE
# → payment-service   10.244.1.12:8080,10.244.2.15:8080,10.244.3.8:8080   5d

# Атомарное переключение селектора сервиса на green
kubectl patch service payment-service -p '{"spec":{"selector":{"deployment-color":"green"}}}'
# → service/payment-service patched

# Проверка обновления селектора
kubectl get service payment-service -o jsonpath='{.spec.selector}'
# → {"app":"payment-api","deployment-color":"green"}

# Мгновенный откат при возникновении сбоя в новой версии
kubectl patch service payment-service -p '{"spec":{"selector":{"deployment-color":"blue"}}}'
# → service/payment-service patched
```

### Сценарий 4: Долевой Canary-релиз на основе реплик с общим селектором меток

Маршрутизация ~10% трафика на новую версию за счет соотношения реплик.

```yaml
# Основная стабильная версия: 9 реплик (90% трафика)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: auth-service-stable
spec:
  replicas: 9
  selector:
    matchLabels:
      app: auth-service
      release-track: stable
  template:
    metadata:
      labels:
        app: auth-service
        release-track: stable
    spec:
      containers:
      - name: auth
        image: auth-service:2.4.1
        ports:
        - containerPort: 8080
---
# Canary-версия: 1 реплика (10% трафика)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: auth-service-canary
spec:
  replicas: 1
  selector:
    matchLabels:
      app: auth-service
      release-track: canary
  template:
    metadata:
      labels:
        app: auth-service
        release-track: canary
    spec:
      containers:
      - name: auth
        image: auth-service:2.5.0
        ports:
        - containerPort: 8080
---
# Общий Service, выбирающий поды ТОЛЬКО по app: auth-service
apiVersion: v1
kind: Service
metadata:
  name: auth-service
spec:
  selector:
    app: auth-service    # Метка присутствует в обоих Deployment
  ports:
  - port: 80
    targetPort: 8080
```

**Проверка распределения конечных точек (Endpoints):**
```bash
# Получение общего списка подов под сервисом
kubectl get pods -l app=auth-service -L release-track
# → NAME                                   READY   STATUS    RESTARTS   AGE   RELEASE-TRACK
# → auth-service-stable-65d89f78f-a1b2c   1/1     Running   0          12h   stable
# → auth-service-stable-65d89f78f-d3e4f   1/1     Running   0          12h   stable
# → ... (еще 7 стабильных подов)
# → auth-service-canary-84b8d76d4-z9y8x   1/1     Running   0          5m    canary

# Увеличение доли Canary до 30% (3 реплики canary и 7 стабильных)
kubectl scale deployment auth-service-canary --replicas=3
kubectl scale deployment auth-service-stable --replicas=7
```

### Сценарий 5: Сетевая изоляция микросервисов с помощью меток в NetworkPolicy

Ограничение доступа к базе данных: доступ разрешен только подам с меткой `role: backend-worker`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: isolate-database-ingress
  namespace: production
spec:
  # Политика применяется к подам базы данных
  podSelector:
    matchLabels:
      app.kubernetes.io/name: redis-cache
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Разрешено подключение только от подов с указанной меткой
    - podSelector:
        matchLabels:
          role: backend-worker
          security-zone: internal
    ports:
    - protocol: TCP
      port: 6379
```

**Валидация:**
```bash
# Список защищаемых подов
kubectl get pods -n production -l app.kubernetes.io/name=redis-cache --show-labels

# Список подов, имеющих право подключения
kubectl get pods -n production -l "role=backend-worker,security-zone=internal"
```

### Сценарий 6: Учет ресурсов и квотирование через метки Namespace и ResourceQuota

Структурирование кластера для мультиарендности (Multi-Tenancy) и привязки к центрам затрат.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: core-banking
  labels:
    business-unit: retail-finance
    cost-center: "10440"
    environment: production
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-quota
  namespace: core-banking
spec:
  hard:
    requests.cpu: "32"
    requests.memory: 64Gi
    limits.cpu: "64"
    limits.memory: 128Gi
    pods: "100"
```

**Проверка квоты и аудит по меткам подразделений:**
```bash
# Поиск всех неймспейсов департамента retail-finance
kubectl get namespaces -l business-unit=retail-finance --show-labels
# → NAME           STATUS   AGE   LABELS
# → core-banking   Active   30d   business-unit=retail-finance,cost-center=10440,environment=production

# Инспекция потребления квоты
kubectl get resourcequota compute-quota -n core-banking
# → NAME            AGE   REQUEST                               LIMIT
# → compute-quota   30d   cpu: 18/32, memory: 42Gi/64Gi        cpu: 34/64, memory: 80Gi/128Gi
```

### Сценарий 7: Автоматизация мониторинга и сбора логов через аннотации Pod

Передача расширенных инструкций для Prometheus Service Discovery и Fluent Bit без изменения конфигурации самого сборщика.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-processor
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: order-processor
  template:
    metadata:
      labels:
        app: order-processor
        tier: backend
      annotations:
        # Автообнаружение и сбор метрик Prometheus
        prometheus.io/scrape: "true"
        prometheus.io/port: "9102"
        prometheus.io/path: "/metrics"
        
        # Инструкция парсеру Fluent Bit
        fluentbit.io/parser: "json"
        
        # Операционные SRE-метаданные
        operations.company.com/component: "orders"
        operations.company.com/runbook: "https://wiki.corp/sre/runbooks/orders"
        operations.company.com/oncall: "#sre-orders-channel"
        
        # Фиксация ревизии в rollout history
        kubernetes.io/change-cause: "Release 2.4.0: оптимизация пакетной обработки заказов"
    spec:
      containers:
      - name: processor
        image: order-processor:2.4.0
        ports:
        - containerPort: 8080
          name: api
        - containerPort: 9102
          name: metrics
```

**Проверка аннотаций в реальном времени:**
```bash
# Извлечение аннотаций мониторинга подов
kubectl get pods -l app=order-processor -o custom-columns="NAME:.metadata.name,SCRAPE:.metadata.annotations.prometheus\.io/scrape,PORT:.metadata.annotations.prometheus\.io/port"
# → NAME                              SCRAPE   PORT
# → order-processor-78d789b5c-2p8xm   true     9102
# → order-processor-78d789b5c-k9w4n   true     9102
```

### Сценарий 8: Балансировка реплик по физическим доменам отказа через TopologySpreadConstraints

Гарантия отказоустойчивости сервиса на уровне физических серверов и серверных стоек без применения устаревших жестких правил `podAntiAffinity`. Подробнее: [Affinity и TopologySpread](../../Scheduling/affinity.md).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: resilient-gateway
  namespace: default
spec:
  replicas: 6
  selector:
    matchLabels:
      app: resilient-gateway
  template:
    metadata:
      labels:
        app: resilient-gateway
    spec:
      topologySpreadConstraints:
      # Правило 1: Равномерно по серверным стойкам/зонам (zone-a, zone-b)
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: resilient-gateway
      # Правило 2: Равномерно по серверам внутри стойки
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: resilient-gateway
      containers:
      - name: gateway
        image: nginx:1.27
```

### Сценарий 9: Вывод узла на обслуживание (Cordon, Drain, метки и Taints)

Безопасное проведение плановых работ (замена оперативной памяти, обновление ядра Linux) с блокировкой повторного размещения.

```bash
# 1. Запрет назначения новых подов штатной командой
kubectl cordon worker-02.corp
# → node/worker-02.corp cordoned

# 2. Установка информационной метки для системных администраторов
kubectl label node worker-02.corp maintenance=in-progress --overwrite
# → node/worker-02.corp labeled

# 3. Безопасное выселение подов с соблюдением PodDisruptionBudget
kubectl drain worker-02.corp --ignore-daemonsets --delete-emptydir-data --timeout=300s
# → evicting pod default/order-processor-78d789b5c-2p8xm...
# → node/worker-02.corp drained

# (Проведение аппаратных работ на сервере и его перезагрузка)

# 4. Возврат узла в строй
kubectl label node worker-02.corp maintenance-
# → node/worker-02.corp unlabeled

kubectl uncordon worker-02.corp
# → node/worker-02.corp uncordoned
```

### Сценарий 10: SRE-паттерн «Карантин сбойного пода» (Quarantine Pattern)

Изоляция аварийного экземпляра пода (утечка памяти, дедлок, высокая нагрузка на CPU) для снятия дампов памяти, профилирования и анализа без влияния на пользователей.

**Принцип:** Если изменить метку пода, на которую ориентируются `Service` и `ReplicaSet`:
1. `Service` мгновенно исключает Pod из списка адресов балансировки (Endpoints).
2. `ReplicaSet` видит нехватку одной реплики с меткой `app: payment-api` и автоматически запускает свежий здоровый Pod взамен.
3. Изолированный Pod **не удаляется**, продолжая работать в текущем аварийном состоянии, доступный для `kubectl exec`, `gdb` или снятия heap-дампа.

```bash
# 1. Находим сбойный Pod под нагрузкой
kubectl get pods -l app=payment-api
# → NAME                           READY   STATUS    RESTARTS   AGE
# → payment-api-65d89f78f-problem  1/1     Running   4          1d

# 2. Снимаем рабочую метку приложения и добавляем метку карантина
kubectl label pod payment-api-65d89f78f-problem app- quarantine=true --overwrite
# → pod/payment-api-65d89f78f-problem labeled

# 3. Проверяем: ReplicaSet тут же поднял новый pod
kubectl get pods -l app=payment-api
# → NAME                           READY   STATUS    RESTARTS   AGE
# → payment-api-65d89f78f-problem  1/1     Running   4          1d  (НЕТ В СПИСКЕ, так как нет app=payment-api)
# → payment-api-65d89f78f-newpod   1/1     Running   0          5s  (Новый рабочий экземпляр)

# 4. Проверяем, что эндпоинты сервиса очищены от сбойного пода
kubectl get endpoints payment-service
# (IP проблемного пода больше не получает клиентский трафик)

# 5. Проведение диагностики инженером внутри изолированного пода
kubectl exec -it payment-api-65d89f78f-problem -- kill -3 1  # Снятие thread dump Java/Go

# 6. После завершения анализа удаляем изолированный pod вручную
kubectl delete pod payment-api-65d89f78f-problem
```

### Сценарий 11: Аудит изменений и откат релизов через аннотацию kubernetes.io/change-cause

Включение расширенной трассировки ручных и автоматических обновлений.

```bash
# Фиксация изменения перед обновлением версии контейнера
kubectl annotate deployment/order-processor \
  kubernetes.io/change-cause="Hotfix CVE-2026-3841: обновление базового образа openssl" \
  --overwrite -n default
# → deployment.apps/order-processor annotated

# Выполнение самого обновления образа
kubectl set image deployment/order-processor processor=order-processor:2.4.1 -n default
# → deployment.apps/order-processor image updated

# Просмотр истории ревизий Deployment
kubectl rollout history deployment/order-processor -n default
# → deployment.apps/order-processor 
# → REVISION  CHANGE-CAUSE
# → 1         Release 2.3.0
# → 2         Release 2.4.0: оптимизация пакетной обработки заказов
# → 3         Hotfix CVE-2026-3841: обновление базового образа openssl

# Быстрый откат на предыдущую стабильную ревизию при деградации метрик
kubectl rollout undo deployment/order-processor --to-revision=2 -n default
# → deployment.apps/order-processor rolled back
```

---

## Операции и команды

### Управление метками (Labels)

```bash
# 1. Добавить метку к объекту
kubectl label pod web-server-01 env=production
# → pod/web-server-01 labeled

# 2. Добавить метку к физическому узлу
kubectl label node worker-01.corp hardware-tier=highmem
# → node/worker-01.corp labeled

# 3. Перезаписать существующую метку (флаг --overwrite обязателен)
kubectl label pod web-server-01 env=staging --overwrite
# → pod/web-server-01 labeled

# 4. Удалить метку (знак минус после имени ключа)
kubectl label pod web-server-01 env-
# → pod/web-server-01 unlabeled

# 5. Показать все метки объектов при выводе
kubectl get pods --show-labels

# 6. Вывести определенные метки в отдельных колонках таблицы
kubectl get pods -L env,tier,app.kubernetes.io/version

# 7. Подсчитать количество подов по конкретной метке
kubectl get pods -l app=nginx --no-headers | wc -l
# → 12
```

### Управление аннотациями (Annotations)

```bash
# 1. Добавить аннотацию к Deployment
kubectl annotate deployment/api-gateway kubernetes.io/change-cause="Обновление таймаутов прокси"
# → deployment.apps/api-gateway annotated

# 2. Перезаписать существующую аннотацию
kubectl annotate deployment/api-gateway kubernetes.io/change-cause="Патч Nginx 1.27.1" --overwrite
# → deployment.apps/api-gateway annotated

# 3. Удалить аннотацию (знак минус после имени ключа)
kubectl annotate deployment/api-gateway kubernetes.io/change-cause-
# → deployment.apps/api-gateway annotated

# 4. Просмотр всех аннотаций в формате JSON через jsonpath
kubectl get pod web-server-01 -o jsonpath='{.metadata.annotations}'

# 5. Извлечение значения конкретной аннотации (экранирование точек в ключе обязательно)
kubectl get pod web-server-01 -o jsonpath='{.metadata.annotations.prometheus\.io/scrape}'
# → true
```

### Фильтрация и выборка по селекторам

```bash
# 1. Селектор равенства (Equality-based): точное совпадение
kubectl get pods -l env=production

# 2. Селектор неравенства: значение не равно заданному
kubectl get pods -l "tier!=frontend"

# 3. Селектор множеств: совпадение с одним из вариантов
kubectl get pods -l "env in (production, staging)"

# 4. Селектор множеств: исключение списка значений
kubectl get pods -l "env notin (test, dev)"

# 5. Проверка наличия метки с любым значением (Existence)
kubectl get pods -l "security-zone"

# 6. Проверка отсутствия метки у объектов (Negation)
kubectl get pods -l '!deprecated'

# 7. Комплексный фильтр: логическое «И» через запятую
kubectl get pods -l "app=auth,env=production,!canary"

# 8. Поиск узлов кластера с определенной архитектурой процессора и дисками
kubectl get nodes -l "kubernetes.io/arch=amd64,storage-tier=nvme"
```

### Пакетные операции для системного администратора

```bash
# 1. Массовая маркировка группы узлов по общему признаку
for node in $(kubectl get nodes -l "node-role.kubernetes.io/worker=" -o name); do
  kubectl label $node datacenter=dc-primary rack=rack-01 --overwrite
done

# 2. Поиск подов, у которых отсутствует обязательная метка env (аудит безопасности)
kubectl get pods -A -l '!env' --no-headers -o custom-columns="NS:.metadata.namespace,NAME:.metadata.name"

# 3. Массовое удаление завершенных Job по метке
kubectl delete jobs -l "batch-job=nightly-sync,status=completed"
```

---

## Диагностика и устранение неполадок (Troubleshooting)

### Ошибка 1: Pod в состоянии Pending из-за несовпадения nodeSelector

**Симптом:** Pod бесконечно находится в состоянии `Pending`.

**Диагностика:**
```bash
kubectl describe pod <pod-name>
# → Events:
# →   Type     Reason            Age   From               Message
# →   ----     ------            ----  ----               -------
# →   Warning  FailedScheduling  24s   default-scheduler  0/10 nodes are available: 10 node(s) didn't match Pod's node selector.
```

**Анализ причин:**
1. Проверяем, какие требования выставлены в поде:
   ```bash
   kubectl get pod <pod-name> -o jsonpath='{.spec.nodeSelector}'
   # → {"disktype":"nvme","rack":"r-04"}
   ```
2. Проверяем наличие таких меток на узлах кластера:
   ```bash
   kubectl get nodes -L disktype,rack
   # → NAME             STATUS   ROLES    AGE   VERSION   DISKTYPE   RACK
   # → worker-01.corp   Ready    <none>   10d   v1.30.0   ssd        r-01
   # → worker-02.corp   Ready    <none>   10d   v1.30.0   ssd        r-02
   ```

**Решение:**
* Если узел с таким оборудованием существует, назначьте недостающие метки:
  ```bash
  kubectl label node worker-01.corp disktype=nvme rack=r-04
  ```
* Если метки были указаны с опечаткой в манифесте, исправьте `spec.nodeSelector` и примените манифест заново.

---

### Ошибка 2: Ошибка при попытке перезаписать существующую метку

**Симптом:** При выполнении `kubectl label` команда завершается ошибкой:
```
error: 'env' already has a value ('production'), and --overwrite is false
```

**Причина:** Защита от случайной перезаписи ключевых метаданных кластера.

**Решение:**
* Передать явный флаг разрешения перезаписи `--overwrite`:
  ```bash
  kubectl label pod <pod-name> env=staging --overwrite
  # → pod/<pod-name> labeled
  ```
* Либо сначала явно удалить старую метку, затем установить новую:
  ```bash
  kubectl label pod <pod-name> env-
  kubectl label pod <pod-name> env=staging
  ```

---

### Ошибка 3: Потеря управления подами при попытке модификации spec.selector у Deployment

**Симптом:** При попытке отредактировать поле `spec.selector` существующего объекта `Deployment` команда `kubectl apply` или `kubectl edit` завершается ошибкой:
```
The Deployment "my-app" is invalid: spec.selector: Invalid value: ...: field is immutable
```

**Архитектурная причина:** Поле `spec.selector` контроллеров (`Deployment`, `StatefulSet`, `DaemonSet`) является **неизменяемым** (`immutable`) с момента создания объекта. Изменение селектора привело бы к тому, что существующие поды стали бы «сиротами» (Orphaned Pods), а контроллер начал бы создавать новый дублирующий набор подов.

**Решение:**
1. Не меняйте селектор у запущенного Deployment. Если требуется провести миграцию структуры меток, создайте новый параллельный Deployment с новым именем и новым селектором, переключите трафик через `Service`, после чего удалите старый Deployment.
2. Если Deployment тестовый и простой допустим:
   ```bash
   # Удаление только контроллера с сохранением подов
   kubectl delete deployment my-app --cascade=orphan
   # Создание манифеста с обновленным селектором и его применение
   kubectl apply -f deployment-new-selector.yaml
   ```

---

### Ошибка 4: Pod привязан через nodeName к аварийному узлу

**Симптом:** Pod находится в статусе `Pending` или `NodeLost`, при этом в секции `Events` отсутствуют сообщения от `kube-scheduler`.

**Диагностика:**
```bash
# Проверка наличия жесткой привязки узла
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}'
# → worker-05.corp

# Проверка физического состояния этого узла
kubectl get node worker-05.corp
# → NAME              STATUS     ROLES    AGE   VERSION
# → worker-05.corp   NotReady   <none>   35d   v1.30.0
```

**Причина:** Применение поля `spec.nodeName` исключило участие планировщика. Pod был жестко назначен на узел `worker-05.corp`, который находится в сбое (`NotReady` или выключен). Никакой автоэвакуации планировщик выполнить не может.

**Решение:**
1. Удалите зависший под: `kubectl delete pod <pod-name> --grace-period=0 --force`.
2. Замените в спецификации пода или его шаблоне поле `spec.nodeName` на `spec.nodeSelector` или правила `spec.affinity.nodeAffinity`:
   ```yaml
   # Запрещено в production:
   # spec:
   #   nodeName: worker-05.corp

   # Рекомендуемый подход:
   spec:
     nodeSelector:
       node-role.kubernetes.io/worker: "true"
   ```

---

### Ошибка 5: Аннотация kubernetes.io/change-cause не попадает в историю выкатки

**Симптом:** При выполнении `kubectl rollout history deployment/<name>` в колонке `CHANGE-CAUSE` отображается `<none>`.

**Причина:** Аннотация `kubernetes.io/change-cause` была добавлена к `metadata.annotations` самого Deployment **после** того, как ревизия уже создалась, либо аннотация была добавлена не в тот уровень манифеста.

**Диагностика:**
```bash
# Проверка, где установлена аннотация
kubectl get deployment <name> -o jsonpath='{.metadata.annotations.kubernetes\.io/change-cause}'
kubectl get deployment <name> -o jsonpath='{.spec.template.metadata.annotations.kubernetes\.io/change-cause}'
```

**Решение:**
Аннотацию необходимо обновлять **одновременно** или **непосредственно перед** триггером новой ревизии (`set image`, обновление конфига в шаблоне):
```bash
# Способ 1: Аннотирование перед обновлением
kubectl annotate deployment/my-app kubernetes.io/change-cause="Патч CVE-2026-1102" --overwrite
kubectl set image deployment/my-app app=my-app:v1.9.1

# Способ 2: Использование флага --record устарело (deprecated), используйте явную аннотацию
```

---

### Ошибка 6: DaemonSet не планируется на узлы Control Plane

**Симптом:** Поды системного DaemonSet (например, агент сбора логов node-exporter) запускаются только на Worker-нодах, пропуская мастер-узлы.

**Диагностика:**
```bash
kubectl describe node control-plane-01.corp | grep -A 3 "Taints:"
# → Taints:             node-role.kubernetes.io/control-plane:NoSchedule
```

**Причина:** Узлы Control Plane по умолчанию защищены тейном `NoSchedule`. `nodeSelector` выполняет притяжение подов к узлам, но **не дает допуска** сквозь защитные `Taints`.

**Решение:**
В манифест `DaemonSet` необходимо добавить явную секцию `tolerations`:
```yaml
spec:
  template:
    spec:
      tolerations:
      - key: "node-role.kubernetes.io/control-plane"
        operator: "Exists"
        effect: "NoSchedule"
```

---

### Ошибка 7: «Война контроллеров» (Controller Thrashing) из-за пересекающихся селекторов

**Симптом:** Постоянное создание и удаление подов; счетчик рестартов и генераций подов стремительно растет; сервис возвращает нестабильные ответы.

**Причина:** Два разных `Deployment` (или `ReplicaSet`) в одном namespace имеют одинаковые или частично пересекающиеся селекторы `spec.selector.matchLabels` (например, оба настроены на `app: web`). Контроллер Deployment A считает поды Deployment B своими избыточными репликами и пытается их удалить. Одновременно контроллер Deployment B видит нехватку подов и создает новые.

**Диагностика:**
```bash
# Просмотр всех Deployment и их селекторов в одном namespace
kubectl get deployment -o custom-columns="NAME:.metadata.name,SELECTOR:.spec.selector.matchLabels"
# → NAME         SELECTOR
# → web-legacy   map[app:web]
# → web-next     map[app:web]   <-- ОШИБКА: Дублирование селектора!
```

**Решение:**
1. Разграничьте селекторы контроллеров. Добавьте уникальный идентификатор приложения или компонента:
   * Для Deployment A: `app: web-legacy`
   * Для Deployment B: `app: web-next`
2. Всегда используйте стандартные префиксы и составные метки (`app.kubernetes.io/name`, `app.kubernetes.io/instance`).

---

### Ошибка 8: Ошибка маршрутизации (пустой список Endpoints) из-за опечатки в селекторе Service

**Симптом:** Запросы к сервису возвращают `502 Bad Gateway` или зависают по таймауту; `curl http://my-service` не работает.

**Диагностика:**
```bash
# 1. Проверяем список Endpoints сервиса
kubectl get endpoints my-service
# → NAME         ENDPOINTS   AGE
# → my-service   <none>      2d   <-- Эндпоинты отсутствуют!

# 2. Смотрим, какой селектор ищет Service
kubectl get service my-service -o jsonpath='{.spec.selector}'
# → {"app":"frontend","tier":"web"}

# 3. Смотрим реальные метки запущенных подов
kubectl get pods --show-labels
# → NAME                        LABELS
# → frontend-789bf8d4-5m92k     app=frontend,tier=api   <-- Опечатка: tier=api вместо tier=web!
```

**Решение:**
Синхронизируйте селектор `Service` с реальными метками в шаблоне `Deployment`:
```bash
# Исправление селектора на живом сервисе
kubectl patch service my-service -p '{"spec":{"selector":{"app":"frontend","tier":"api"}}}'
# → service/my-service patched

# Проверка появления сетевых адресов
kubectl get endpoints my-service
# → NAME         ENDPOINTS                           AGE
# → my-service   10.244.1.20:8080,10.244.2.33:8080   2d
```

---

### Ошибка 9: Pod зависает в Pending при валидном nodeSelector из-за нехватки ресурсов или Taints

**Симптом:** Узел с метками из `nodeSelector` существует, но планировщик отказывается запускать туда Pod.

**Диагностика:**
```bash
kubectl describe pod <pod-name>
# → Events:
# →   Warning  FailedScheduling  default-scheduler  0/5 nodes are available: 1 node(s) had untolerated taint {node.kubernetes.io/disk-pressure: }, 4 node(s) didn't match Pod's node selector.
```

**Причина:** Фаза фильтрации планировщика (`Filter`) проверяет комплекс условий: совпадение `nodeSelector`, отсутствие давления на диски/память (`Taints: DiskPressure / MemoryPressure`) и наличие доступных запрошенных ресурсов (`cpu` и `memory requests`). Даже если метки совпали, узел отклоняется по другим предикатам.

**Решение:**
1. Проверьте аллокацию ресурсов на целевом узле: `kubectl describe node <node-name> | grep -A 7 "Allocated resources"`.
2. Если на узле выставлен системный тейн сбоя (`DiskPressure`), устраните причину (очистка неиспользуемых контейнеров/образов через `crictl rmi --prune`).

---

### Ошибка 10: Ошибка валидации формата метки или аннотации (RFC 1123)

**Симптом:** При попытке применить манифест возвращается ошибка API-сервера:
```
The Pod "test-app" is invalid: metadata.labels: Invalid value: "production server": a valid label must be an empty string or consist of alphanumeric characters, '-', '_' or '.', and must start and end with an alphanumeric character
```

**Причина:** Значения и ключи меток обязаны соответствовать жесткому формату (до 63 символов, только цифры, буквы латиницы, `-`, `_`, `.`). Пробелы, двоеточия, слеши в значении (value) меток **запрещены**.

**Решение:**
* Если требуется сохранить строку с пробелами, описанием или URL — переместите эти данные из `metadata.labels` в `metadata.annotations`. В аннотациях разрешены любые символы и строковые форматы.

---

## Best Practices

1. **Используйте общепринятую таксономию меток**:
   Применяйте рекомендованные сообществом метки Kubernetes (`app.kubernetes.io/name`, `app.kubernetes.io/instance`, `app.kubernetes.io/version`, `app.kubernetes.io/component`, `app.kubernetes.io/part-of`, `app.kubernetes.io/managed-by`). Это гарантирует предсказуемую интеграцию с Helm, ArgoCD и системами телеметрии.
2. **Используйте префиксы компании для кастомных метаданных**:
   Для внутренних служебных меток всегда применяйте формат FQDN-префикса: `company.com/team`, `company.com/cost-center`, `company.com/sla`. Это исключает коллизии имен с системными метками платформы.
3. **Строго разделяйте идентификацию и метаданные**:
   * В **Labels** заносите только то, по чему производится фильтрация, маршрутизация трафика или планирование (`env`, `app`, `tier`, `node-role`).
   * В **Annotations** размещайте служебные параметры: timestamp сборки, хеш git-коммита, имя автора, ссылки на Runbook, настройки парсеров логов и скрейпинга метрик.
4. **Категорический отказ от `nodeName` в продуктивных средах**:
   Никогда не указывайте `spec.nodeName` в манифестах прикладных сервисов. Для таргетирования оборудования используйте `nodeSelector`, а для комплексных сценариев — `nodeAffinity`.
5. **Применяйте паттерн «Карантин сбойного пода» (Quarantine)**:
   При расследовании инцидентов изолируйте аварийные поды от трафика путем снятия рабочей метки селектора, сохраняя контейнер в запущенном состоянии для глубокого профилирования и анализа дампов памяти.
6. **Помните о неизменяемости селекторов контроллеров**:
   Проектируйте `spec.selector.matchLabels` в `Deployment` на ранних этапах. Изменить их «на лету» без пересоздания ресурса невозможно.
7. **Стандартизируйте профили узлов в физической инфраструктуре (Bare-Metal)**:
   Вместо привязки к временным сетевым именам серверов (`kubernetes.io/hostname`), маркируйте узлы кластера по физическим характеристикам:
   * Тип дисков: `storage-tier=nvme`, `storage-tier=hdd`
   * Сетевая специфика: `network-speed=25g`, `network-zone=dmz`
   * Физическое размещение: `topology.kubernetes.io/zone=zone-a`, `topology.kubernetes.io/rack=r12`
   * Процессорная архитектура: системная метка `kubernetes.io/arch=amd64` / `arm64`
8. **Комбинируйте `nodeSelector` с `Taints` и `Tolerations`**:
   Для выделения специализированных нод (например, серверов с тяжелой дисковой подсистемой или лицензируемым ПО) одного `nodeSelector` недостаточно: чужие поды без селектора все равно смогут занять эти узлы. Устанавливайте `Taint` для отталкивания чужих подов, а `nodeSelector` + `Toleration` — для притяжения целевых.
9. **Контролируйте обязательные метки через Admission Controllers**:
   Внедряйте политики валидации (например, с помощью Kyverno или OPA Gatekeeper), запрещающие запуск подов без обязательных меток ответственности (`company.com/team`, `company.com/env`).
10. **Не храните секреты и токены в аннотациях**:
    Аннотации не являются зашифрованными данными etcd по умолчанию и легко читаются любым пользователем с правами `get pods`. Пароли, сертификаты и API-ключи должны храниться исключительно в [Secrets](../../Security/application_secrets_management.md) или монтироваться через HashiCorp Vault / External Secrets Operator.

---

## Связанные темы

* [Метаданные, метки и аннотации в Kubernetes](../../Concepts/metadata_and_labels.md) — базовые структуры метаданных, системные поля объекта, архитектура хранения в etcd.
* [Node Affinity и Topology Spread Constraints](../../Scheduling/affinity.md) — гибкие правила планирования, приоритеты, веса и распределение по физическим доменам отказа.
* [Taints и Tolerations: изоляция узлов](../../Scheduling/taints_and_tolerations.md) — механизмы отталкивания нежелательных подов от выделенных серверов кластера.
* [Сетевые политики (NetworkPolicy)](../../Networking/Network/network_overview.md) — правила межсервисной изоляции трафика с использованием селекторов меток Pod.
* [Диагностика зависания Pod в состоянии Pending](../../Troubleshooting/Common_Errors/pod_pending/common_cases_and_solutions.md) — анализ причин блокировки планирования, включая несовпадения предикатов селектора узлов.
* [Безопасность и управление секретами приложений](../../Security/application_secrets_management.md) — безопасное хранение конфиденциальных данных без компрометации метаданных.
