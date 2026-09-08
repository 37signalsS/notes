# Продвинутые темы Pod в Kubernetes

## Определения

**Неизменяемые поля (Immutable fields)** — поля спецификации Pod, которые запрещено модифицировать после создания объекта. Изменение таких полей требует удаления и пересоздания Pod.

**Врата готовности (Readiness Gates)** — механизм расширения стандартных проверок готовности Pod. Позволяет внешним контроллерам (например, Ingress-контроллеру или Service Mesh) влиять на статус готовности Pod, добавляя собственные условия (Conditions).

**Врата планирования (Scheduling Gates)** — механизм (GA с v1.30), позволяющий удерживать Pod в состоянии `Pending` до выполнения внешних условий (например, проверки безопасности, выделения квот или подготовки данных), блокируя работу стандартного планировщика.

**Оверхед пода (Pod Overhead)** — фиксированный объем ресурсов (CPU, память), который резервируется для нужд среды выполнения (Runtime) и не учитывается в лимитах контейнеров. Учитывается планировщиком при размещении Pod на узле.

**hostAliases** — механизм добавления пользовательских записей в `/etc/hosts` Pod без использования ConfigMap или сторонних DNS-серверов. Полезен для тестовых окружений и миграции legacy-приложений.

**shareProcessNamespace** — параметр Pod, объединяющий PID Namespace всех контейнеров в Pod. Позволяет контейнерам видеть процессы друг друга и отправлять им сигналы (kill, reload). Полезен для sidecar-контейнеров мониторинга и отладки.

**Init-контейнер (Init Container)** — специальный контейнер, который выполняется строго до старта основных контейнеров и завершается успешно перед запуском следующего. Используется для подготовки среды, ожидания зависимостей и миграции данных.

---

## Базовые концепции

### Редактирование работающего Pod

Большинство параметров Pod фиксируются при создании. Однако Kubernetes позволяет изменять «на лету» ограниченный набор полей.

**Доступные для редактирования поля:**

| Поле | Описание | Влияние |
| :--- | :--- | :--- |
| `spec.containers[*].image` | Имена и теги образов контейнеров | Вызывает перезапуск контейнера |
| `spec.initContainers[*].image` | Теги образов для инициализирующих контейнеров | Не влияет на уже запущенные Pod |
| `spec.activeDeadlineSeconds` | Лимит времени жизни Pod | Прекращает работу при превышении |
| `spec.tolerations` | Добавление новых исключений для Taints | Только добавление, удаление невозможно |
| `spec.terminationGracePeriodSeconds` | Время ожидания перед SIGKILL (v1.25+) | Позволяет увеличить время завершения |

**Критически важные неизменяемые поля:**

| Поле | Почему неизменяемо | Обходной путь |
| :--- | :--- | :--- |
| `spec.containers[*].command`, `args` | Определяют запускаемый процесс | Пересоздание Pod (Rolling Update) |
| `spec.containers[*].env` | Переменные окружения фиксируются при создании | Используйте ConfigMap/Secret + `envFrom` |
| `spec.containers[*].ports` | Порт привязывается к ContainerPort | Пересоздание Pod |
| `spec.volumes` и `volumeMounts` | Тома монтируются при старте | Пересоздание Pod |
| `spec.nodeName` (после планирования) | Привязка к узлу необратима | `kubectl drain` + удаление + пересоздание |

**Важно:** При редактировании `image` через `kubectl edit` Pod будет перезапущен автоматически. Для корректного обновления используйте `kubectl set image` или обновление Deployment, чтобы сохранить версионность и возможность отката.

### Изоляция и RuntimeClass

Механизм `RuntimeClass` позволяет выбирать разные рантаймы для конкретных Pod в зависимости от требований к безопасности или производительности.

**Основные рантаймы:**

| Рантайм | Тип изоляции | Overhead | Безопасность | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **runc** | Нет изоляции (общее ядро) | Минимальный | Базовая | Стандартные Production-нагрузки |
| **gVisor (runsc)** | Userspace-ядро (Sentry) | Средний (10-15% CPU) | Высокая (системные вызовы фильтруются) | Недоверенный код, мультитенантность |
| **Kata Containers** | Легковесная VM (QEMU/Cloud-Hypervisor) | Высокий (25-40% CPU, 30-50MB RAM) | Максимальная (полная изоляция ядер) | Критические системы, compliance |
| **crun** | Ускоренный (C, без Go runtime) | Минимальный | Базовая | Высокая производительность |

**Создание RuntimeClass:**

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: gvisor
overhead:
  podFixed:
    memory: "128Mi"
    cpu: "100m"
scheduling:
  nodeSelector:
    runtime: gvisor
---
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
overhead:
  podFixed:
    memory: "160Mi"
    cpu: "250m"
```

**Применение к Pod:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: untrusted-code
spec:
  runtimeClassName: gvisor
  containers:
  - name: app
    image: untrusted-app:1.0
```

**Когда использовать:**
- Мультитенантные кластеры (разные租анты → разные уровни изоляции)
- Запуск недоверенного кода (пользовательские плагины, CI/CD нагрузки)
- Compliance-требования (PCI DSS, HIPAA требуют изоляции)

**Ограничения:**
- Требует установки runtime на узлах (`gvisor`, `kata` через node installer)
- Не все volume drivers поддерживаются (Kata ограничивает hostPath)
- PodOverhead автоматически добавляется к расчету ресурсов

Подробнее: [Изоляция рантайма в Security Context](../../Security/pod_security_context.md#5-изоляция-рантайма-runtimeclass).

### Продвинутая сетевая конфигурация

Kubernetes позволяет тонко настраивать DNS и идентификацию Pod внутри сети.

#### dnsPolicy — стратегия DNS

Поле `spec.dnsPolicy` определяет способ формирования `/etc/resolv.conf`:

| Значение | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`ClusterFirst`** (по умолчанию) | Сначала резолвит через CoreDNS (кластерные сервисы), затем пересылает внешнему резолверу узла | Стандартные приложения |
| **`Default`** | Наследует DNS от хоста (игнорирует кластерный DNS) | Поды, которым нужен доступ только к внешним DNS |
| **`ClusterFirstWithHostNet`** | Обязателен для Pod с `hostNetwork: true` | Ingress-контроллеры, monitoring-агенты на хосте |
| **`None`** | Полностью ручная настройка через `dnsConfig` | Специфические требования к DNS (закрытые реестры) |

**Пример `ClusterFirstWithHostNet`:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ingress-controller
spec:
  hostNetwork: true
  dnsPolicy: ClusterFirstWithHostNet  # Иначе не сможет резолвить kubernetes.default
  containers:
  - name: nginx-ingress
    image: nginx:1.25
```

#### Оптимизация ndots:5

По умолчанию Kubernetes устанавливает `ndots:5` в `/etc/resolv.conf` каждого Pod. Это означает, что любое имя с менее чем 5 точками будет резолвит через search-домены кластера, что увеличивает latency.

**Проблема:**
```
# Запрос к google.com вызывает 4 лишних DNS-запроса:
# 1. google.com.default.svc.cluster.local (NXDOMAIN)
# 2. google.com.svc.cluster.local (NXDOMAIN)
# 3. google.com.cluster.local (NXDOMAIN)
# 4. google.com (FOUND)
```

**Решение 1 — Абсолютные имена (добавить точку в конце):**
```yaml
# В коде приложения:
curl google.com.   # Точка в конце = абсолютное имя, пропускает search
```

**Решение 2 — Снижение ndots через dnsConfig:**
```yaml
spec:
  dnsConfig:
    options:
    - name: ndots
      value: "2"    # Снижает количество DNS-запросов
    - name: timeout
      value: "2"
    - name: attempts
      value: "3"
```

**Решение 3 — Кастомные nameserver:**
```yaml
spec:
  dnsPolicy: None   # Отключает автоматическую генерацию
  dnsConfig:
    nameservers:
    - "1.1.1.1"
    - "8.8.8.8"
    searches:
    - "custom.internal"
    options:
    - name: ndots
      value: "2"
```

Подробнее: [DNS Deep Dive](../../Networking/dns_deep_dive.md).

#### hostAliases — кастомные DNS записи

Механизм добавления записей в `/etc/hosts` Pod без ConfigMap или DNS-серверов:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: legacy-app
spec:
  hostAliases:
  - ip: "10.0.0.100"
    hostnames:
    - "legacy-api.internal"
    - "legacy-db.internal"
  - ip: "10.0.0.200"
    hostnames:
    - "old-service.local"
  containers:
  - name: app
    image: legacy-app:1.0
    env:
    - name: API_HOST
      value: "legacy-api.internal"
```

**Результат в контейнере:**
```bash
cat /etc/hosts
# ...
#   Additional entries
#   10.0.0.100  legacy-api.internal legacy-db.internal
#   10.0.0.200  old-service.local
```

**Применение:**
- Миграция legacy-приложений, которые используют имена в `/etc/hosts`
- Тестовые окружения с фейковыми сервисами
- Временные обходные пути при недоступности DNS-сервера

**Ограничения:**
- Максимум 256 записей на Pod
- Записи не удаляются после создания Pod (только через пересоздание)
- Не масштабируется (для каждого Pod нужен свой манифест)

### Врата готовности (Readiness Gates)

По умолчанию Pod считается готовым (`Ready: True`), если все его контейнеры прошли `readinessProbe`. С помощью `readinessGates` можно добавить внешние условия.

**Как это работает:**

1. В манифесте Pod объявлено условие `readinessGates` (например, `example.com/gate`).
2. Pod создаётся, но статус `Ready` = `False` (даже если контейнеры прошли `readinessProbe`).
3. Внешний контроллер (Ingress, Service Mesh, кастомный) устанавливает это условие в `True`.
4. Только после этого Pod добавляется в эндпоинты Service и начинает принимать трафик.

**Реальный кейс — Ingress Controller:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-app
  labels:
    app: web
spec:
  readinessGates:
  - conditionType: "networking.kubernetes.io/ingress-ready"
  containers:
  - name: app
    image: web-app:1.0
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
```

**Диагностика:**
```bash
# Проверка условий Pod
kubectl get pod web-app -o jsonpath='{.status.conditions[*].type}'
# → PodScheduled Initialized ContainersReady Ready

# Проверка readinessGates
kubectl get pod web-app -o jsonpath='{.spec.readinessGates}'
# → [{"conditionType":"networking.kubernetes.io/ingress-ready"}]

# Проверка состояния конкретного условия
kubectl get pod web-app -o jsonpath='{.status.conditions[?(@.type=="networking.kubernetes.io/ingress-ready")].status}'
# → False (ожидает внешнего контроллера)
```

**Сравнение readinessProbe vs readinessGates:**

| Механизм | Кто проверяет | Когда активируется | Пример |
| :--- | :--- | :--- | :--- |
| `readinessProbe` | Kubelet на узле | Периодически (`periodSeconds`) | HTTP-эндпоинт `/ready` |
| `readinessGates` | Внешний контроллер | По событию (API-вызов) | Ingress-контроллер зарегистрировал IP |

### Врата планирования (Scheduling Gates)

Scheduling Gates (GA с v1.30) позволяют удерживать Pod в состоянии `Pending` до тех пор, пока внешний контроллер не разрешит планирование. В отличие от `readinessGates` (которые влияют на готовность), Scheduling Gates блокируют сам процесс размещения Pod на узле.

**Как это работает:**

1. Pod создаётся с непустым `spec.schedulingGates`.
2. Kube-scheduler видит непустые ворота и **полностью игнорирует** Pod (не проверяет ресурсы, не ищет узлы).
3. Внешний контроллер выполняет проверку (безопасность, квоты, подготовка данных).
4. Контроллер удаляет ворота из `spec.schedulingGates`.
5. Scheduler начинает планирование Pod.

**Пример — контроллер квот:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: batch-job
  labels:
    app: batch
spec:
  schedulingGates:
  - apiGroup: "scheduling.k8s.io"
    name: "quota-check"
  containers:
  - name: worker
    image: batch-worker:1.0
    resources:
      requests:
        cpu: "1"
        memory: "2Gi"
```

**Контроллер (псевдокод):**
```python
# Когда квота доступна:
pod.spec.schedulingGates.remove(gate="quota-check")
api.patch_pod(pod)
```

**Диагностика:**
```bash
# Проверка статуса Pod
kubectl get pod batch-job
# → NAME         STATUS     AGE
#   batch-job    SchedulingGated   5m

# Проверка ворот
kubectl get pod batch-job -o jsonpath='{.spec.schedulingGates}'
# → [{"apiGroup":"scheduling.k8s.io","name":"quota-check"}]

# Проверка событий
kubectl describe pod batch-job | grep -A 5 "Events"
# → Type    Reason    Age   From     Message
#   Normal  Scheduled  5m   default-scheduler  Scheduling disabled
```

**Сравнение Scheduling Gates vs readinessGates:**

| Механизм | Блокирует | Контроллер | Статус Pending | Восстановление |
| :--- | :--- | :--- | :--- | :--- |
| `readinessGates` | Добавление в эндпоинты Service | Внешний (Ingress, Mesh) | Pod в Running, но не Ready | Удаление ворот |
| `schedulingGates` | Сам процесс планирования | Внешний (квоты, безопасность) | Pod в Pending (SchedulingGated) | Удаление ворот |

**Когда использовать:**
- Ожидание выделения квоты Namespace перед планированием
- Проверка безопасности (Gatekeeper, Kyverno) перед размещением
- Подготовка данных (PV, ConfigMap) перед стартом Pod
- Gang Scheduling (все Pod группы планируются одновременно)

Подробнее: [Продвинутая диагностика Pending](../../Troubleshooting/Common_Errors/pod_pending/advanced_topics.md).

### Overhead пода (Pod Overhead)

При использовании изолированных рантаймов (gVisor, Kata) Kubernetes автоматически резервирует дополнительные ресурсы для среды выполнения. Этот overhead учитывается планировщиком при размещении Pod.

**Overhead для разных рантаймов (типичные значения):**

| Рантайм | CPU Overhead | Memory Overhead | Причина |
| :--- | :--- | :--- | :--- |
| **runc** | 0 | 0 | Общее ядро, нет изоляции |
| **gVisor (runsc)** | 5-15% | 30-50MB | Userspace-ядро Sentry + Gofer |
| **Kata (QEMU)** | 25-40% | 128-160MB | Полная VM с отдельным ядром |
| **Kata (Cloud-Hypervisor)** | 15-25% | 80-120MB | Упрощенный VMM |
| **crun** | 0-2% | 5-10MB | Минимальный overhead (C runtime) |

**Создание RuntimeClass с overhead:**

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: gvisor
overhead:
  podFixed:
    memory: "128Mi"
    cpu: "100m"
```

**Как overhead влияет на планирование:**

```yaml
# Pod с overhead
apiVersion: v1
kind: Pod
metadata:
  name: sandboxed-app
spec:
  runtimeClassName: gvisor
  containers:
  - name: app
    resources:
      requests:
        cpu: "500m"      # Запрошено приложением
        memory: "256Mi"
    image: app:1.0
# Итого для планировщика:
# CPU: 500m + 100m (overhead) = 600m
# Memory: 256Mi + 128Mi (overhead) = 384Mi
```

**Проверка overhead:**
```bash
# Просмотр overhead для RuntimeClass
kubectl get runtimeclass gvisor -o jsonpath='{.overhead}'
# → {"podFixed":{"cpu":"100m","memory":"128Mi"}}

# Проверка реального потребления Pod
kubectl top pod sandboxed-app
# → NAME              CPU(cores)   MEMORY(bytes)
#   sandboxed-app     620m         390Mi
```

---

## Практические сценарии

### Пример 1: Настройка DNS и Hostname

Сценарий для кластерных приложений (например, баз данных), требующих стабильных имен внутри сети:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: cluster-node-0
  labels:
    app: postgres
    role: primary
spec:
  hostname: node-0
  subdomain: cluster-internal
  dnsPolicy: ClusterFirst
  dnsConfig:
    options:
      - name: ndots
        value: "2"
      - name: timeout
        value: "3"
  containers:
  - name: postgres
    image: postgres:16
    ports:
    - containerPort: 5432
    env:
    - name: POSTGRES_HOST_AUTH_METHOD
      value: "trust"
```

**Проверка FQDN:**
```bash
kubectl exec cluster-node-0 -- hostname -f
# → node-0.cluster-internal.default.svc.cluster.local
```

### Пример 2: Readiness Gates с Ingress-контроллером

Ожидание регистрации в Ingress перед добавлением в Service:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-app
  labels:
    app: web
spec:
  readinessGates:
  - conditionType: "networking.kubernetes.io/ingress-ready"
  containers:
  - name: app
    image: web-app:1.0
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
    resources:
      requests:
        cpu: "100m"
        memory: "128Mi"
      limits:
        cpu: "200m"
        memory: "256Mi"
```

**Сценарий использования:**
1. Ingress-контроллер видит новый Pod, но ещё не зарегистрировал его IP в балансировщике.
2. Устанавливает условие `networking.kubernetes.io/ingress-ready: True`.
3. Pod добавляется в эндпоинты Service и начинает принимать трафик.

**Диагностика:**
```bash
# Проверка readinessGates
kubectl get pod web-app -o jsonpath='{.spec.readinessGates}'
# → [{"conditionType":"networking.kubernetes.io/ingress-ready"}]

# Проверка условий
kubectl get pod web-app -o json | jq '.status.conditions[] | {type, status, reason}'
# → {"type":"PodScheduled","status":"True","reason":"..."}
#   {"type":"Initialized","status":"True","reason":"..."}
#   {"type":"Ready","status":"False","reason":"ReadinessGatesNotReady"}
```

### Пример 3: Диагностика через Termination Message

Сохранение причин падения в статус Pod для быстрой диагностики:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: error-app
spec:
  containers:
  - name: app
    image: busybox:1.36
    command: ["sh", "-c"]
    args:
    - |
      echo "ERROR: Database connection refused on port 5432" > /dev/termination-log
      echo "Stack: ConnectionPool.connect() failed" >> /dev/termination-log
      exit 1
    terminationMessagePath: /dev/termination-log
    terminationMessagePolicy: File
    resources:
      requests:
        cpu: "50m"
        memory: "64Mi"
```

**Просмотр termination message:**
```bash
# Быстрая диагностика без логов
kubectl get pod error-app -o jsonpath='{.status.containerStatuses[*].lastState.terminated.message}'
# → ERROR: Database connection refused on port 5432
#   Stack: ConnectionPool.connect() failed

# Просмотр exit code
kubectl get pod error-app -o jsonpath='{.status.containerStatuses[*].lastState.terminated.exitCode}'
# → 1
```

**terminationMessagePolicy:**

| Политика | Описание | Когда использовать |
| :--- | :--- | :--- |
| `File` (по умолчанию) | Читает из `terminationMessagePath` | Стандартные приложения |
| `FallbackToLogsOnError` | Если сообщение пусто, берёт из stderr контейнера | Приложения без записи в файл |

**Пример FallbackToLogsOnError:**
```yaml
containers:
- name: app
  image: my-app:1.0
  terminationMessagePolicy: FallbackToLogsOnError
  # Если приложение не пишет в /dev/termination-log,
  # Kubernetes возьмёт последние строки stderr
```

**Продвинутая настройка:**
```yaml
containers:
- name: app
  image: my-app:1.0
  terminationMessagePath: /tmp/termination-log  # Кастомный путь
  terminationMessagePolicy: FallbackToLogsOnError
  volumeMounts:
  - name: tmp
    mountPath: /tmp
volumes:
- name: tmp
  emptyDir: {}
```

### Пример 4: Scheduling Gates для контроля квот

Pod блокируется до подтверждения квоты Namespace:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: resource-heavy
  labels:
    app: ml-training
spec:
  schedulingGates:
  - apiGroup: "scheduling.k8s.io"
    name: "namespace-quota"
  containers:
  - name: trainer
    image: ml-trainer:2.0
    resources:
      requests:
        cpu: "4"
        memory: "16Gi"
      limits:
        cpu: "8"
        memory: "32Gi"
```

**Диагностика:**
```bash
# Проверка статуса
kubectl get pod resource-heavy
# → NAME             STATUS              AGE
#   resource-heavy   SchedulingGated     2m

# Проверка ворот
kubectl get pod resource-heavy -o jsonpath='{.spec.schedulingGates}'
# → [{"apiGroup":"scheduling.k8s.io","name":"namespace-quota"}]

# Мониторинг очереди планировщика
kubectl get --raw /metrics | grep scheduler_pending_pods
# → scheduler_pending_pods{queue="gated"} 1
```

**Решение (контроллер квоты):**
```bash
# Контроллер удаляет ворота после подтверждения квоты
kubectl patch pod resource-heavy --type='json' -p='[{"op": "remove", "path": "/spec/schedulingGates/0"}]'
# → Pod переходит в планирование
```

### Пример 5: hostAliases для legacy-приложения

Перенос приложения, использующего `/etc/hosts`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: legacy-migration
spec:
  hostAliases:
  - ip: "10.0.0.50"
    hostnames:
    - "payment-gateway"
    - "payment-api"
  - ip: "10.0.0.60"
    hostnames:
    - "legacy-db"
  containers:
  - name: app
    image: legacy-app:3.2
    env:
    - name: API_ENDPOINT
      value: "http://payment-api:8080"
    - name: DB_HOST
      value: "legacy-db"
    resources:
      requests:
        cpu: "200m"
        memory: "256Mi"
```

**Проверка:**
```bash
kubectl exec legacy-migration -- cat /etc/hosts | grep payment
# → 10.0.0.50  payment-gateway payment-api

kubectl exec legacy-migration -- nslookup payment-api
# → Name:      payment-api
#   Address:   10.0.0.50
```

---

## Продвинутые паттерны init-контейнеров

### Паттерн 1: Ожидание зависимости

Init-контейнер ожидает доступности сервиса перед стартом основного приложения:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-deps
spec:
  initContainers:
  - name: wait-for-db
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z postgres-service 5432; do echo waiting for db; sleep 2; done']
    resources:
      requests:
        cpu: "10m"
        memory: "16Mi"
  containers:
  - name: app
    image: my-app:1.0
    env:
    - name: DB_HOST
      value: "postgres-service"
```

### Паттерн 2: Миграция данных

Init-контейнер выполняет миграции БД перед стартом приложения:

```yaml
initContainers:
- name: db-migration
  image: my-app:1.0
  command: ['python', 'manage.py', 'migrate', '--no-input']
  env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: db-credentials
        key: url
  resources:
    requests:
      cpu: "100m"
      memory: "256Mi"
```

### Паттерн 3: Клонирование конфигурации

Init-контейнер копирует конфигурацию в общий Volume:

```yaml
initContainers:
- name: config-loader
  image: busybox:1.36
  command: ['sh', '-c', 'cp /config/* /shared-config/']
  volumeMounts:
  - name: config-source
    mountPath: /config
  - name: shared-config
    mountPath: /shared-config
containers:
- name: app
  image: my-app:1.0
  volumeMounts:
  - name: shared-config
    mountPath: /etc/app/config
    readOnly: true
volumes:
- name: config-source
  configMap:
    name: app-config
- name: shared-config
  emptyDir: {}
```

Подробнее: [Init-контейнеры в Kubernetes](./pod_init_containers.md).

---

## Troubleshooting: типичные ошибки продвинутых тем

### Ошибка 1: Pod в статусе SchedulingGated

**Причина:** Scheduling Gates не удалены внешним контроллером.

**Диагностика:**
```bash
# Проверка ворот
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'

# Проверка событий
kubectl describe pod <pod-name> | grep -A 5 "Events"

# Проверка метрик планировщика
kubectl get --raw /metrics | grep scheduler_pending_pods
```

**Решение:**
1. Найти контроллер, ответственный за ворота.
2. Проверить логи контроллера (в Example: Gatekeeper, Kyverno, кастомный).
3. Временное решение — удалить ворота вручную:
```bash
kubectl patch pod <pod-name> --type='json' -p='[{"op": "remove", "path": "/spec/schedulingGates/0"}]'
```

### Ошибка 2: Pod не становится Ready (readinessGates)

**Причина:** Внешний контроллер не устанавливает условие readinessGates.

**Диагностика:**
```bash
# Проверка conditions
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[*].type}'

# Проверка конкретного условия
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="example.com/gate")].status}'

# Проверка readinessGates в манифесте
kubectl get pod <pod-name> -o jsonpath='{.spec.readinessGates}'
```

**Решение:**
1. Проверить, что внешний контроллер работает и видит Pod.
2. Проверить RBAC — контроллер должен иметь доступ к conditions Pod.
3. Убедиться, что условие в `readinessGates` совпадает с тем, что устанавливает контроллер.

### Ошибка 3: OOMKilled из-за Pod Overhead

**Причина:** PodOverhead не учтен в `limits.memory`, планировщик разместил Pod на узле с недостаточным запасом.

**Диагностика:**
```bash
# Проверка overhead для RuntimeClass
kubectl get runtimeclass <name> -o jsonpath='{.overhead}'

# Проверка потребления Pod
kubectl top pod <pod-name>

# Проверка лимитов
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].resources.limits}'
```

**Решение:**
1. Увеличить `limits.memory` с учетом overhead:
```yaml
resources:
  limits:
    memory: "384Mi"  # 256Mi (приложение) + 128Mi (overhead)
```
2. Использовать RuntimeClass с корректными значениями overhead.

### Ошибка 4: DNS-запросы работают медленно (ndots:5)

**Причина:** Слишком частые DNS-запросы из-за высокого `ndots`.

**Диагностика:**
```bash
# Проверка текущего ndots
kubectl exec <pod-name> -- cat /etc/resolv.conf | grep ndots
# → options ndots:5

# Замер времени DNS-запроса
kubectl exec <pod-name> -- time nslookup google.com
# → real    0m0.015s (быстро, если ndots маленький)
```

**Решение:**
1. Снизить ndots через `dnsConfig`:
```yaml
spec:
  dnsConfig:
    options:
    - name: ndots
      value: "2"
```
2. Использовать абсолютные имена с точкой в конце в коде приложения.

### Ошибка 5: hostAliases не работают

**Причина:** Записи не добавляются в `/etc/hosts` из-за некорректного формата.

**Диагностика:**
```bash
# Проверка hostAliases в манифесте
kubectl get pod <pod-name> -o jsonpath='{.spec.hostAliases}'

# Просмотр /etc/hosts внутри контейнера
kubectl exec <pod-name> -- cat /etc/hosts
```

**Решение:**
1. Убедиться, что формат YAML корректен:
```yaml
hostAliases:
- ip: "10.0.0.100"      # ip должен быть строкой
  hostnames:
  - "service.local"      # каждое имя — отдельный элемент
```
2. Проверить, что IP доступен из сети Pod.

---

## Дополнительная информация

**Связанные темы:**

*   [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — фазы, условия, shutdown.
*   [Рекомендации по написанию манифестов Pod](./pod_best_practices.md) — лучшие практики для Production.
*   [Эфемерные контейнеры в Kubernetes](./ephemeral_containers.md) — отладка «на лету».
*   [Init-контейнеры в Kubernetes](./pod_init_containers.md) — продвинутые паттерны.
*   [DNS Deep Dive](../../Networking/dns_deep_dive.md) — тонкая настройка DNS.
