# Метки, аннотации и выбор узлов для Pod

## Определения

**Labels (Метки)** — пары «ключ-значение», прикрепляемые к объектам Kubernetes. Предназначены для идентификации, группировки и выборки объектов через селекторы (Selectors). Подробнее: [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md).

**Annotations (Аннотации)** — неидентифицирующие метаданные для хранения произвольной вспомогательной информации (версии сборки, JSON-конфиги, параметры внешних инструментов). Не используются для выборки объектов.

**Label Selector (Селектор меток)** — механизм фильтрации объектов по меткам. Поддерживает два типа: **на основе равенства** (`env = production`) и **на основе множеств** (`env in (prod, staging)`). Используется в Deployment, Service, NetworkPolicy и других ресурсах.

**Node Selection (Выбор узла)** — процесс управления размещением подов в кластере через указание требований к узлу (Node).

**nodeSelector** — простейший механизм фильтрации узлов на основе меток. Pod будет запланирован только на ту Node, которая обладает всеми метками, указанными в селекторе. Работает как **логическое «И»** для всех указанных пар ключ-значение.

**nodeName** — способ прямой привязки Pod к конкретной Node по её имени. Игнорирует механизмы планировщика (scheduler) и ограничения Taints (тейнов).

---

## Базовые концепции

### Механизмы управления размещением

| Механизм | Описание | Уровень сложности | Рекомендация |
| :--- | :--- | :--- | :--- |
| `nodeSelector` | Привязка по точному совпадению меток | Низкий | Для простых сценариев |
| [Node Affinity](../../Scheduling/affinity.md) | Расширенные правила с логическими операторами | Средний | Основной метод для сложных топологий |
| [Taints / Tolerations](../../Scheduling/taints_and_tolerations.md) | Запрет или разрешение размещения на узлах | Средний | Для изоляции ресурсов |
| `nodeName` | Прямая запись имени узла в спецификацию | Критический | **Не рекомендуется** для Prod |

### Типы Label Selectors

Kubernetes поддерживает два типа селекторов, используемых в различных ресурсах:

**1. Equality-based (на основе равенства):**
Используется в `spec.selector` Service и других «старых» ресурсах.
- `env = production` — ключ `env` должен иметь значение `production`
- `tier != frontend` — ключ `tier` не должен быть `frontend`

**2. Set-based (на основе множеств):**
Современный подход через `matchExpressions` в Deployment, Job, DaemonSet.
- `env in (prod, staging)` — значение входит в список
- `tier notin (backup)` — значение не входит в список
- `partition` — ключ просто существует (любое значение)
- `!partition` — ключ отсутствует

```bash
# Фильтрация по equality-based селектору
kubectl get pods -l env=production

# Фильтрация по set-based селектору
kubectl get pods -l "env in (production, staging),tier=frontend"

# Комбинированный селектор
kubectl get pods -l "app=nginx,env in (prod,staging),!deprecated"

# Фильтрация по нескольким значениям одного ключа
kubectl get pods -l "env in (dev,staging)"
```

### Особенности nodeSelector

Использование `nodeSelector` является наиболее быстрым и производительным способом ограничить круг узлов для приложения. Если планировщик не находит ни одного узла, удовлетворяющего всем условиям (логическое «И»), Pod переходит в фазу `Pending`.

**Ограничения nodeSelector (в сравнении с Node Affinity):**

| Критерий | nodeSelector | Node Affinity |
| :--- | :--- | :--- |
| Синтаксис | Только `key=value` | `In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt`, `Lt` |
| Мягкие правила | Нет | `preferredDuringSchedulingIgnoredDuringExecution` |
| Отрицание | Нет | `DoesNotExist`, `NotIn` (anti-affinity) |
| Вес (приоритет) | Нет | 1-100 для preferred правил |

**Рекомендации:**
- Не привязывайтесь к системной метке `kubernetes.io/hostname`, так как узлы могут пересоздаваться с новыми именами (особенно в облаках).
- Используйте логические метки ролей или характеристик (например, `disktype: ssd`, `gpu: "true"`).
- Для сложных сценариев (отрицание, предпочтения, числовое сравнение) переходите на [Node Affinity](../../Scheduling/affinity.md).

### Опасности использования nodeName

Поле `nodeName` в спецификации Pod (`spec.nodeName`) заставляет систему обойти процесс планирования.

**Последствия:**
1.  **Отсутствие отказоустойчивости:** если указанный узел выйдет из строя, Pod не будет перезапущен на другом узле автоматически.
2.  **Игнорирование ограничений:** Pod может быть запущен на узле, где недостаточно ресурсов (CPU, память) или установлены запрещающие Taints.
3.  **Конфликты:** если узел не существует или недоступен, Pod останется в состоянии ожидания вечно.

> **Почему `nodeName` до сих пор существует:** Исторически использовался контроллерами (например, DaemonSet Controller) для прямого назначения подов. В современных версиях Kubernetes для этой цели используются Scheduler Framework или Eviction Controller.

### Типичные аннотации в DevOps/SRE

Аннотации делятся на несколько категорий по области применения:

| Категория | Пример ключа | Описание |
| :--- | :--- | :--- |
| **История изменений** | `kubernetes.io/change-cause` | Причина последнего обновления Deployment (видна в `rollout history`) |
| **Мониторинг** | `prometheus.io/scrape`, `prometheus.io/port` | Автообнаружение Prometheus для scrape |
| **Ingress** | `nginx.ingress.kubernetes.io/*` | Управление поведением NGINX Ingress Controller |
| **Service Mesh** | `sidecar.istio.io/inject` | Автоматическое внедрение sidecar |
| **Секреты** | `vault.hashicorp.com/agent-inject` | Интеграция с HashiCorp Vault |
| **Security** | `pod-security.kubernetes.io/*` | Управление Pod Security Admission |
| **Сбор логов** | `fluentbit.io/parser` | Парсер для Fluent Bit |
| **Контроль версий** | `helm.sh/revision` | Номер ревизии Helm-чарта |
| **Документация** | `description`, `team`, `cost-center` | Метаданные для поиска и аудита |

> **Подробнее:** Список рекомендованных меток и поле `metadata` — [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md).

### Референс kubectl-команд для работы с метками и аннотациями

#### Метки (Labels)

```bash
# Добавить метку к Pod
kubectl label pod <pod-name> env=production

# Добавить метку к узлу
kubectl label node <node-name> disktype=ssd

# Перезаписать существующую метку (без --overwrite ошибка)
kubectl label pod <pod-name> env=staging --overwrite

# Удалить метку (минус после ключа)
kubectl label pod <pod-name> env-

# Показать все метки Pod
kubectl get pods --show-labels

# Фильтрация по меткам (equality-based)
kubectl get pods -l env=production
kubectl get pods -l "app != nginx"

# Фильтрация по меткам (set-based)
kubectl get pods -l "env in (prod,staging)"
kubectl get pods -l "env in (prod,staging),tier=frontend"

# Фильтрация по меткам узлов
kubectl get nodes -l disktype=ssd

# Подсчет Pod по метке
kubectl get pods --no-headers -l app=nginx | wc -l

# Вывод только имен Pod с определенной меткой
kubectl get pods -l env=production -o name

# Фильтрация по 존재ующей/отсутствующей метке
kubectl get pods -l "app"          # есть метка app (любое значение)
kubectl get pods -l '!deprecated'  # метка deprecated отсутствует
```

#### Аннотации (Annotations)

```bash
# Добавить аннотацию к Deployment
kubectl annotate deployment/my-app kubernetes.io/change-cause="Обновление до v1.2.3"

# Добавить аннотацию к Pod
kubectl annotate pod <pod-name> description="временный инстанс для отладки"

# Перезаписать аннотацию
kubectl annotate deployment/my-app kubernetes.io/change-cause="Hotfix CVE-123" --overwrite

# Удалить аннотацию
kubectl annotate pod <pod-name> description-

# Просмотр аннотаций через jsonpath
kubectl get pod <pod-name> -o jsonpath='{.metadata.annotations}'

# Просмотр конкретной аннотации
kubectl get pod <pod-name> -o jsonpath='{.metadata.annotations.prometheus\.io/scrape}'

# Просмотр аннотаций всех Pod (табличный вид)
kubectl get pods -o custom-columns="NAME:.metadata.name,CHANGE:.metadata.annotations.kubernetes\.io/change-cause"

# Поиск Pod с определенной аннотацией (через jsonpipe или jq)
kubectl get pods -o json | jq -r '.items[] | select(.metadata.annotations["team"] == "platform") | .metadata.name'
```

#### Просмотр и отладка

```bash
# Получить Pod с полным описанием (включая метки и аннотации)
kubectl get pod <pod-name> -o yaml

# Получить метки Pod через jsonpath
kubectl get pod <pod-name> -o jsonpath='{.metadata.labels}'

# Получить аннотации Pod через jsonpath
kubectl get pod <pod-name> -o jsonpath='{.metadata.annotations}'

# Кастомный вывод с метками
kubectl get pods -o custom-columns="NAME:.metadata.name,ENV:.metadata.labels.env,TIER:.metadata.labels.tier"

# Поиск Pod, принадлежащих конкретному Deployment через метки
kubectl get pods -l app=my-app,controller-uid=<uid>

# Мониторинг изменений меток в реальном времени
kubectl get pods -w --show-labels
```

---

## Практические сценарии

### Сценарий 1: Маркировка узлов и привязка Pod

Классический паттерн для выделения узлов под специфические задачи.

**Шаг 1: Маркировка узла**
```bash
# Метка для типа диска
kubectl label node worker-01 disktype=ssd

# Метка для роли узла
kubectl label node worker-02 node-role.kubernetes.io/ingress=true

# Метка для зоны доступности
kubectl label node worker-03 topology.kubernetes.io/zone=eu-central-1a

# Проверка меток узла
kubectl get node worker-01 --show-labels
# → NAME         STATUS   ROLES    AGE   VERSION   LABELS
# → worker-01    Ready    <none>   30d   v1.30.0   disktype=ssd,...
```

**Шаг 2: Манифест Pod с nodeSelector**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
  labels:
    app: my-app
    env: production
spec:
  nodeSelector:
    disktype: ssd          # Только на узлах с SSD
    topology.kubernetes.io/zone: eu-central-1a  # Только в зоне eu-central-1a
  containers:
  - name: app
    image: nginx:1.27
```

**Шаг 3: Проверка назначения**
```bash
kubectl get pod my-app -o wide
# → NAME     READY   STATUS    NODE        
# → my-app   1/1     Running   worker-01

# Проверка, почему Pod не планируется (если Pending)
kubectl describe pod my-app | grep -A 5 "Events:"
# → Warning  FailedScheduling  0/5 nodes are available: 5 node(s) didn't match node selector.
```

> **Подробнее:** Если nodeSelector не помогает, используйте [Node Affinity](../../Scheduling/affinity.md) для более гибких правил или [Taints и Tolerations](../../Scheduling/taints_and_tolerations.md) для изоляции узлов.

### Сценарий 2: Привязка DaemonSet к группе узлов

Запуск агентов мониторинга только на узлах, предназначенных для обработки внешнего трафика (Ingress-ноды).

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: traffic-monitor
  namespace: monitoring
spec:
  selector:
    matchLabels:
      name: monitor
  template:
    metadata:
      labels:
        name: monitor
        app: traffic-monitor
    spec:
      nodeSelector:
        node-role.kubernetes.io/ingress: "true"
      containers:
      - name: agent
        image: monitor-agent:1.2.0
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
```

**Проверка:**
```bash
# Узлы с ролью Ingress
kubectl get nodes -l node-role.kubernetes.io/ingress=true

# Поды DaemonSet и их расположение
kubectl get pods -n monitoring -l name=monitor -o wide
# → NAME                READY   STATUS    NODE
# → traffic-monitor-abc   1/1     Running   ingress-01
# → traffic-monitor-def   1/1     Running   ingress-02
```

### Сценарий 3: Blue-Green деплой через метки

Переключение трафика между версиями приложения через изменение меток Service.

**Шаг 1: Развертывание синей (текущей) версии**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-blue
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
      version: blue
  template:
    metadata:
      labels:
        app: my-app
        version: blue
    spec:
      containers:
      - name: app
        image: my-app:v1.0.0
---
apiVersion: v1
kind: Service
metadata:
  name: my-app
spec:
  selector:
    app: my-app
    version: blue    # ← активная версия
  ports:
  - port: 80
    targetPort: 8080
```

**Шаг 2: Развертывание зеленой (новой) версии**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-green
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
      version: green
  template:
    metadata:
      labels:
        app: my-app
        version: green
    spec:
      containers:
      - name: app
        image: my-app:v2.0.0
```

**Шаг 3: Переключение трафика**
```bash
# Переключение Service на зеленую версию
kubectl patch service my-app -p '{"spec":{"selector":{"version":"green"}}}'

# Проверка: Service теперь направляет на зеленую версию
kubectl get svc my-app -o yaml | grep -A 5 selector
# → selector:
# →   app: my-app
# →   version: green

# Откат при необходимости
kubectl patch service my-app -p '{"spec":{"selector":{"version":"blue"}}}'
```

> **Важно:** Blue-Green деплой требует удвоения ресурсов на время переключения. После проверки новой версии старую версию можно удалить или оставить как fallback.

### Сценарий 4: Canary-релиз через метки

Масштабирование новой версии на 10% трафика через количество реплик.

**Шаг 1: Основная версия (90% трафика)**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-stable
spec:
  replicas: 9
  selector:
    matchLabels:
      app: my-app
      track: stable
  template:
    metadata:
      labels:
        app: my-app
        track: stable
    spec:
      containers:
      - name: app
        image: my-app:v1.0.0
```

**Шаг 2: Canary-версия (10% трафика)**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-canary
spec:
  replicas: 1    # 1 из 10 = 10% трафика
  selector:
    matchLabels:
      app: my-app
      track: canary
  template:
    metadata:
      labels:
        app: my-app
        track: canary
    spec:
      containers:
      - name: app
        image: my-app:v2.0.0
```

**Шаг 3: Service с общим селектором**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
spec:
  selector:
    app: my-app    # ← селектор по общему ключу
  ports:
  - port: 80
    targetPort: 8080
```

**Шаг 4: Увеличение доли canary**
```bash
# Увеличение до 30% трафика
kubectl scale deployment my-app-canary --replicas=3

# Проверка распределения
kubectl get pods -l app=my-app -o wide
# → NAME                   READY   STATUS    NODE
# → my-app-stable-xxx      1/1     Running   worker-01
# → my-app-stable-yyy      1/1     Running   worker-02
# → my-app-stable-zzz      1/1     Running   worker-03
# → my-app-canary-aaa      1/1     Running   worker-04  ← canary
# → my-app-canary-bbb      1/1     Running   worker-05  ← canary
# → my-app-canary-ccc      1/1     Running   worker-06  ← canary
```

### Сценарий 5: Метки для NetworkPolicy

Использование меток для управления сетевым трафиком между Pod.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend    # ← применяется к Pod с этой меткой
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend    # ← разрешен трафик только от frontend
    ports:
    - protocol: TCP
      port: 8080
```

**Проверка:**
```bash
# Pod, к которым применяется политика
kubectl get pods -n production -l app=backend

# Pod, которым разрешен доступ
kubectl get pods -n production -l app=frontend
```

> **Подробнее:** Полное руководство по NetworkPolicy — [Сетевые политики](../../Networking/Network/network_overview.md).

### Сценарий 6: Метки для Resource Quota и Cost Allocation

Метки для отслеживания потребления ресурсов по командам/проектам.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: team-platform
  labels:
    team: platform
    cost-center: cc-12345
    env: production
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-quota
  namespace: team-platform
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "50"
```

**Проверка потребления:**
```bash
# Потребление квоты в namespace
kubectl get resourcequota -n team-platform
# → NAME       AGE   REQUEST      LIMIT
# → team-quota  30d   cpu: 6/10    cpu: 12/20
#                      mem: 15Gi/20Gi   mem: 30Gi/40Gi

# Поды команды platform с их потреблением
kubectl get pods -n team-platform -l team=platform -o custom-columns="NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory"
```

### Сценарий 7: Аннотации для мониторинга и сбора логов

Настройка Prometheus и Fluent Bit через аннотации Pod.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
        env: production
      annotations:
        # Prometheus: автообнаружение
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
        prometheus.io/path: "/metrics"

        # Fluent Bit: парсер логов
        fluentbit.io/parser: "json"

        # Описание для Operations
        description: "Основной API-сервис обработки платежей"
        team: "platform"
        on-call: "platform-oncall@company.com"

        # Причина создания (видна в rollout history)
        kubernetes.io/change-cause: "Разворачивание v2.1.0 с фиксом CVE-2026-1234"
    spec:
      containers:
      - name: app
        image: my-app:v2.1.0
        ports:
        - containerPort: 8080
          name: http
        - containerPort: 9090
          name: metrics    # ← Prometheus scrape порт
```

**Проверка:**
```bash
# Просмотр аннотаций Prometheus
kubectl get pod -l app=my-app -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.prometheus\.io/scrape}{"\n"}{end}'
# → my-app-abc123    true
# → my-app-def456    true
# → my-app-ghi789    true
```

### Сценарий 8: Равномерное распределение по зонам (v1.30+)

Использование `topologySpreadConstraints` для обеспечения высокой доступности.

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
        # Распределение по зонам доступности
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: my-app
        # Распределение по узлам внутри зоны
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: my-app
      containers:
      - name: app
        image: nginx:1.27
```

> **Подробнее:** Полное руководство по Affinity и Topology Spread — [Управление размещением подов](../../Scheduling/affinity.md).

### Сценарий 9: Обслуживание узла с сохранением критических Pod

Комбинирование `nodeSelector`, `tolerations` и `kubectl label` для безопасного обслуживания.

```bash
# 1. Добавить метку "maintenance" к узлу для обслуживания
kubectl label node worker-01 maintenance=true

# 2. (Опционально) Добавить taint для запрета новых подов
kubectl taint node worker-01 maintenance=true:NoSchedule
```

**Манифест критического Pod с допуском:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: critical-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: critical-service
  template:
    metadata:
      labels:
        app: critical-service
    spec:
      # Не планировать на узлы с maintenance=true
      nodeSelector:
        maintenance: "false"

      # Но разрешить继续 работу если уже на таком узле
      tolerations:
      - key: "maintenance"
        operator: "Equal"
        value: "true"
        effect: "NoSchedule"
      containers:
      - name: app
        image: critical-service:v1.0
```

**Проверка:**
```bash
# Поды на обслуживаемом узле
kubectl get pods -o wide | grep worker-01

# Новые поды не планируются на worker-01
kubectl describe node worker-01 | grep -A 3 "Taints"
# → Taints: maintenance=true:NoSchedule

# Завершение обслуживания: удаление метки и taint
kubectl label node worker-01 maintenance-
kubectl taint node worker-01 maintenance=true:NoSchedule-
```

### Сценарий 10: Использование аннотаций для документирования изменений

Ведение аудита ручных изменений через аннотации.

```bash
# Зафиксировать причину изменения в Deployment
kubectl annotate deployment/my-app \
  kubernetes.io/change-cause="Ручное масштабирование до 5 реплик из-за пиковой нагрузки"

# Просмотр истории изменений
kubectl rollout history deployment/my-app
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         Обновление образа до v1.1.0
# → 3         Ручное масштабирование до 5 реплик из-за пиковой нагрузки

# Добавить аннотацию с contact person для алертов
kubectl annotate pod <pod-name> \
  on-call="platform@company.com" \
  escalation="sre-lead@company.com"
```

---

## Troubleshooting: типичные ошибки

### Ошибка 1: Pod в состоянии Pending с ошибкой nodeSelector

**Сообщение:**
```
0/5 nodes are available: 5 node(s) didn't match node selector.
```

**Причина:** Ни один узел в кластере не обладает всеми метками, указанными в `nodeSelector`.

**Диагностика:**
```bash
# Какие метки требуются
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeSelector}'
# → {"disktype":"ssd","zone":"eu-central-1a"}

# Какие метки есть на узлах
kubectl get nodes --show-labels | grep disktype
# → worker-01   Ready   ...   disktype=hdd,...
# → worker-02   Ready   ...   disktype=ssd,zone=eu-central-1a,...

# Проверка: все ли нужные метки есть на worker-02
kubectl get node worker-02 --show-labels | tr ',' '\n' | grep -E "disktype|zone"
# → disktype=ssd
# → zone=eu-central-1a
```

**Решение:** Добавить недостающие метки к узлам:
```bash
kubectl label node worker-01 disktype=ssd
kubectl label node worker-01 zone=eu-central-1a
```

### Ошибка 2: Невозможно перезаписать метку

**Сообщение:**
```
Error from server (NotFound): pods "my-pod" not found
```
или
```
error: "env" already has a value "production", and --overwrite is false
```

**Причина:** Метка уже существует, а флаг `--overwrite` не указан.

**Решение:**
```bash
# Использовать --overwrite для перезаписи
kubectl label pod my-pod env=staging --overwrite

# Или сначала удалить, потом добавить
kubectl label pod my-pod env-
kubectl label pod my-pod env=staging
```

### Ошибка 3: Deployment не находит Pod после изменения меток

**Причина:** Изменение `template.metadata.labels` без обновления `spec.selector` (что невозможно для уже созданного Deployment).

**Важно:** Поле `spec.selector` является **неизменяемым** после создания Deployment. Нельзя:
- Изменить ключи в `spec.selector.matchLabels`
- Добавить Pod с другими метками в Deployment

**Решение:** Создать новый Deployment с правильными метками:
```bash
# Проверить текущие метки Deployment
kubectl get deployment my-app -o jsonpath='{.spec.selector.matchLabels}'
# → {"app":"my-app","track":"stable"}

# Если нужно изменить метки — создать новый Deployment
kubectl create deployment my-app-v2 --image=my-app:v2.0 -o yaml --dry-run=client | \
  kubectl patch --type=strategic -p '{"spec":{"selector":{"matchLabels":{"app":"my-app","track":"v2"}}}}' -f - | \
  kubectl apply -f -
```

### Ошибка 4: Pod планируется на неправильный узел (nodeName)

**Причина:** Прямое указание `spec.nodeName` обходит все проверки.

**Диагностика:**
```bash
# Проверить, что Pod привязан к конкретному узлу
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeName}'
# → worker-03

# Проверить, есть ли проблемы с этим узлом
kubectl describe node worker-03 | grep -A 5 "Conditions:"
```

**Решение:** Убрать `nodeName` из манифеста и использовать `nodeSelector` или `nodeAffinity`:
```yaml
# Вместо:
# spec:
#   nodeName: worker-03

# Использовать:
spec:
  nodeSelector:
    role: dedicated
```

### Ошибка 5: Аннотация не видна в rollout history

**Причина:** Аннотация `kubernetes.io/change-cause` добавлена после создания ревизии или не была изменена.

**Диагностика:**
```bash
# Проверить аннотации текущей версии
kubectl get deployment my-app -o jsonpath='{.spec.template.metadata.annotations}'

# Проверить историю
kubectl rollout history deployment/my-app
```

**Решение:** Аннотацию нужно добавлять/изменять **до** каждого обновления Deployment:
```bash
# Перед обновлением образа
kubectl annotate deployment/my-app \
  kubernetes.io/change-cause="Обновление до v2.0.0" \
  --overwrite

# Затем обновить образ
kubectl set image deployment/my-app app=my-app:v2.0.0
```

### Ошибка 6: DaemonSet не запускается на Control Plane

**Сообщение:**
```
0/1 nodes are available: 1 node(s) had taint {node-role.kubernetes.io/control-plane: }, that the pod didn't tolerate.
```

**Причина:** Узлы Control Plane имеют taint `node-role.kubernetes.io/control-plane:NoSchedule`.

**Решение:** Добавить toleration в DaemonSet:
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

## Best Practices

1. **Используйте префиксы для меток**: Формат `company.com/team=platform` предотвращает конфликты с системными метками и метками сторонних инструментов (Helm, ArgoCD).
2. **Не используйте `nodeName` в Production**: Вместо этого применяйте `nodeSelector` или `nodeAffinity` для отказоустойчивости и гибкости.
3. **Изменяйте `spec.selector` только при создании Deployment**: Поле неизменяемо. Планируйте имена меток заранее.
4. **Комбинируйте `nodeSelector` с `tolerations`**: Для выделенных узлов (GPU, CI) используйте связку: Taints отталкивают чужие Pod, а nodeSelector притягивает нужные.
5. **Используйте `--overwrite` осознанно**: Не перезаписывайте метки без проверки — это может сломать селекторы Service или Deployment.
6. **Фиксируйте изменения через аннотации**: Добавляйте `kubernetes.io/change-cause` перед каждым обновлением для аудита и отката.
7. **Для мониторинга используйте аннотации, а не метки**: Prometheus, Fluent Bit и другие инструменты читают аннотации для автообнаружения — не перегружайте ими системные метки.
8. **Проверяйте распределение после изменений**: Используйте `kubectl get pods -o wide -l app=<name>` для визуальной проверки, что Pod распределяются корректно.
9. **Для NetworkPolicy используйте метки приложения, а не узла**: Сетевые политики работают на уровне Pod, а не узлов.
10. **Избегайте хранения секретов в аннотациях**: Аннотации видны всем, кто имеет доступ к namespace. Используйте [Secrets](../../Security/application_secrets_management.md) или External Secrets Operator.

---

## Связанные темы

* [Метаданные, метки и аннотации в Kubernetes](../../Concepts/metadata_and_labels.md) — стандарты именования, рекомендованные метки, лимиты.
* [Node Affinity и Topology Spread](../../Scheduling/affinity.md) — гибкие правила планирования и распределения по зонам.
* [Taints и Tolerations](../../Scheduling/taints_and_tolerations.md) — механизмы отталкивания подов с узлов.
* [Сетевые политики (NetworkPolicy)](../../Networking/Network/network_overview.md) — управление трафиком по меткам Pod.
