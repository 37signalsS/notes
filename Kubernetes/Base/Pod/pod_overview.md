# Pod в Kubernetes: Обзор

## Определения

**Pod (Под)** — фундаментальный строительный блок любого приложения Kubernetes, наименьшая и простейшая развёртываемая единица. Это логическая оболочка для одного или нескольких контейнеров, гарантированно размещаемых на одном узле (Node).

**Эфемерность Pod** — поды не обладают механизмом самовосстановления. Они создаются, получают уникальный ID (UID) и живут до момента завершения процесса, удаления или сбоя узла. Если Pod погибает, он не «оживает»; вместо этого контроллеры (например, Deployment) создают новый экземпляр с новыми метаданными.

**Pause-container** — инфраструктурный контейнер, создаваемый первым при старте каждого Pod. Он создает и удерживает Linux-пространства имен (namespaces: сетевой, IPC, UTS), к которым затем присоединяются основные контейнеры приложения. Это позволяет контейнерам внутри пода разделять ресурсы, даже если основные процессы перезапускаются.

---

## Подробный разбор Pause Container (Инфраструктурный контейнер)

### Архитектура и роль

Pause container (образ `registry.k8s.io/pause:<version>`) — это **минимальный контейнер** (~100-200KB), написанный на C/Go, который:
1. **Создает namespaces** при старте Pod: Network, IPC, UTS (PID — опционально через `shareProcessNamespace`)
2. **Держит namespaces живыми** до полного завершения Pod
3. **Служит родительским процессом (PID 1)** в namespace для сиротских процессов (reaper), корректно обрабатывая `SIGCHLD` и `waitpid()`

### Жизненный цикл Pod и Pause Container

```
1. Kubelet получает Pod Spec от API-сервера
2. CRI (containerd/CRI-O) создает Pod Sandbox:
   └─ Запускает Pause Container (создает namespaces)
3. Последовательно запускаются контейнеры Pod:
   ├─ Init Containers (по порядку)
   ├─ Native Sidecars (init + restartPolicy: Always)
   └─ App Containers (основная бизнес-логика)
4. Все контейнеры присоединяются к namespaces Pause Container
5. При завершении App Container'ов:
   ├─ Pause Container продолжает держать namespaces
   ├─ Kubelet получает статус через CRI
   └─ При удалении Pod: все контейнеры останавливаются → Pause Container останавливается → namespaces уничтожаются
```

### Важные технические детали

| Аспект | Описание |
| :--- | :--- |
| **Образ** | `registry.k8s.io/pause:3.10` (актуально для K8s 1.30+). Версия привязана к версии Kubernetes. |
| **Ресурсы** | Запрашивает минимальные ресурсы (CPU: 0, Memory: ~0). Не учитывается в квотах пода. |
| **PID 1** | Внутри network/ipc/uts namespace Pause — PID 1. Основные контейнеры имеют свои PID namespace (если не включен shareProcessNamespace). |
| **Сигналы** | Pause корректно обрабатывает `SIGTERM`, `SIGCHLD`. При `SIGTERM` ждет завершения дочерних процессов. |
| **Обновление** | При обновлении образа pause (K8s upgrade) — пересоздается при следующем рестарте Pod. |

### Диагностика Pause Container

```bash
# Найти pause контейнеры на узле
crictl ps --name pause
# → CONTAINER           IMAGE               CREATED             STATE      NAME      ATTEMPT   POD ID
# → 1a2b3c4d5e6f        registry.k8s.io/pause:3.10  2 hours ago   Running    pause     0         abc123...

# Проверить namespace'ы пода через pause
crictl inspect 1a2b3c4d5e6f | jq .info.runtimeSpec.linux.namespaces
# → [{"type":"network"},{"type":"ipc"},{"type":"uts"}...]

# Логи pause контейнера (обычно пусты, но полезны при проблемах с CRI)
crictl logs 1a2b3c4d5e6f
```

### Типичные проблемы

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Pod застрял в `ContainerCreating`** | Pause не запускается | Ошибка CNI (плагин не настроил сеть), образ pause недоступен | Проверить логи CNI, доступность registry.k8s.io |
| **Порт занят** | `ErrImageNeverPull` / `CrashLoopBackOff` | Конфликт `hostPort` или порт уже слушается в namespace | Проверить `ss -tlnp` на узле, изменить порт |
| **Зомби-процессы** | Утечка PID, OOM | Pause не делает reaping (устаревший образ) | Обновить Kubernetes / образ pause |

### Интервью-вопрос: «Что происходит, если основной контейнер упадет, а pause останется?»

**Ответ:** Pause container продолжит держать сетевой namespace (IP, порты), IPC и UTS. Kubelet через CRI видит, что основной контейнер завершился с ошибкой. В зависимости от `restartPolicy`:
- `Always` / `OnFailure` → Kubelet перезапускает основной контейнер в **том же** Pod Sandbox (тот же IP, те же volumes)
- `Never` → Pod переходит в `Completed` / `Failed`, Pause останавливается при удалении Pod

**Ключевой момент:** IP-адрес пода **не меняется** при перезапуске контейнера внутри одного Pod, так как namespace держит pause container.

---

## Базовые концепции

### Почему Pod? (Аналогия с процессами ОС)

Pod имитирует работу «логического хоста». Контейнеры внутри пода тесно связаны, подобно процессам, работающим на одном физическом сервере.

**Аналогия с процессом:**
Под можно сравнить с **процессом** в операционной системе, а контейнеры внутри него — с **потоками (threads)**.
*   Как процесс инкапсулирует несколько потоков, разделяющих память и ресурсы, так и Pod объединяет контейнеры, работающие в общем контексте.
*   Это обеспечивает минимальные задержки (low latency) при взаимодействии между компонентами через `localhost` или IPC.

### Ключевые характеристики Pod

| Характеристика | Описание |
| :--- | :--- |
| **Атомарность планирования** | Невозможно распределить контейнеры одного Pod по разным узлам (Node). |
| **Единый IP-адрес** | У Pod один IP-адрес, общий для всех контейнеров. |
| **Общий localhost** | Контейнеры взаимодействуют между собой через `127.0.0.1`. |
| **Общее пространство портов** | Два контейнера в одном Pod не могут слушать один и тот же порт (возникнет конфликт). |

### Почему Pod, а не контейнер?

Pod — это логическая обёртка над одним или несколькими контейнерами, которая предоставляет:

1. **Сетевой стек:** Все контейнеры в Pod делятся сетевыми ресурсами (один IP-адрес, один набор портов). Это реализуется через **pause container** — специальный контейнер, который создаёт сетевой namespace и удерживает его, даже если основной контейнер упадёт.
2. **Разделение томов:** Контейнеры в Pod могут делиться файловыми томами (`emptyDir`, PVC).
3. **Взаимодействие sidecar:** Контейнеры в Pod взаимодействуют через `localhost` (общий сетевой стек) или через общие тома.

### Общие ресурсы контейнеров в Pod

#### 1. Разделяемые пространства имен (Namespaces)
*   **Network Namespace:** Общий стек TCP/IP, таблица маршрутизации и порты.
*   **IPC Namespace:** Возможность взаимодействия через разделяемую память и очереди сообщений POSIX/SystemV.
*   **UTS Namespace:** Общее имя хоста (hostname).
*   **PID Namespace:** По умолчанию изолирован. Включается через `shareProcessNamespace: true` в спецификации, позволяя контейнерам видеть процессы друг друга и отправлять им сигналы (kill, reload).

#### 2. Ресурсы (Cgroups)
Kubernetes управляет ресурсами (CPU, RAM) на уровне Pod через иерархию cgroups. Это позволяет устанавливать общие лимиты и определять приоритеты (QoS классы).

#### 3. Хранилище (Volumes)
Поду назначается набор томов, которые контейнеры монтируют в свою файловую систему. Это критично для обмена данными между основным приложением и вспомогательными контейнерами (например, сайдкаром для логов).

### Типы контейнеров в Pod

Современный Kubernetes (v1.29+) поддерживает несколько типов контейнеров:

1.  **Прикладные контейнеры (App Containers):** Основная бизнес-логика.
2.  **Инициализирующие (Init Containers):** Запускаются последовательно ДО старта приложения. Должны завершиться успешно. [Подробнее](./pod_init_containers.md).
3.  **Нативные сайдкары (Native Sidecars):** Init-контейнеры с `restartPolicy: Always`. Запускаются перед приложением и работают постоянно. [Подробнее](./pod_sidecar_patterns.md).
4.  **Эфемерные контейнеры (Ephemeral Containers):** Временные контейнеры для отладки работающего пода. [Подробнее](./ephemeral_containers.md).

### Шаблон Pod (Pod Template)

**Pod Template** — спецификация для создания Pod, используемая высокоуровневыми контроллерами (Deployment, Job, StatefulSet, DaemonSet). Контроллеры включают шаблон Pod (`spec.template`) в свою спецификацию для обеспечения **желаемого состояния**.

**Механика работы Pod Template:**

| Аспект | Описание |
| :--- | :--- |
| **Определение** | Часть спецификации контроллера, описывающая конфигурацию будущих Pod. |
| **Гарантия соответствия** | Контроллер обеспечивает соответствие запущенных Pod текущему шаблону. |
| **Уникальность имён** | При создании Pod из шаблона контроллер добавляет хэш-суффикс для уникальности. |
| **Инстанцирование** | Все параметры, указанные в шаблоне, применяются к каждому созданному Pod. |

**Пример Pod Template в Job:**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: hello-job
spec:
  template:  # ← Pod Template начинается здесь
    metadata:
      labels:
        app: hello-job
    spec:
      containers:
      - name: hello
        image: busybox:1.28
        command: ["sh", "-c", "echo Hello Kubernetes && sleep 3600"]
      restartPolicy: OnFailure
```

**Важно:** Pod, созданные из шаблона, получают уникальные имена (например, `hello-job-abc123`). Сам контроллер сохраняет своё статичное имя.

### Управление и обновление

**Способы редактирования:**
*   **IaC (Рекомендуется):** Изменения вносятся в YAML-манифест, затем применяется `kubectl apply -f`.
*   **Императивно:** `kubectl edit <тип> <имя>` — удобно для быстрой отладки, но ведет к рассинхрону с Git.

**Механизм обновления:**
При изменении `Pod Template` в контроллере существующие поды не обновляются «на лету». Контроллер создает **новые поды** и постепенно удаляет старые (RollingUpdate).

### Статические поды (Static Pods)

Управляются напрямую `kubelet` на конкретной ноде через манифесты в директории `/etc/kubernetes/manifests`. API-сервер видит их (через Mirror Pods), но не может ими управлять. Используются для запуска критических компонентов кластера (etcd, kube-apiserver).

**Особенности Static Pods:**

| Характеристика | Описание |
| :--- | :--- |
| **Управление** | Напрямую `kubelet` на ноде (не через API-сервер). |
| **Хранение манифестов** | `/etc/kubernetes/manifests/` (по умолчанию). |
| **Mirror Pods** | API-сервер создаёт «зеркальный» Pod для просмотра через `kubectl get pods`. |
| **Перезапуск** | Автоматический при изменении манифеста в директории. |
| **Удаление** | Удаление манифеста из директории приводит к удалению Pod. |

**Компоненты, работающие как Static Pods:**
- `kube-apiserver` (на каждом control-plane узле)
- `kube-controller-manager`
- `kube-scheduler`
- `etcd` (если не используется external etcd)

**Диагностика:**
```bash
# Просмотр Static Pod'ов на узле
ls /etc/kubernetes/manifests/

# Проверка ошибок kubelet
journalctl -u kubelet | grep -i "static pod"

# Mirror Pod в API
kubectl get pods -n kube-system | grep <node-name>
```

### Оверхед пода (Pod Overhead)

Позволяет учитывать ресурсы, потребляемые самой инфраструктурой выполнения (runtime), например, при использовании Kata Containers. Поле `spec.overhead` добавляется к суммарным запросам ресурсов пода при планировании.

**Когда учитывать Pod Overhead:**
- Использование sandbox-контейнеров (Kata Containers, gVisor).
- Кластеры с требованиями к изоляции (PCI DSS, HIPAA).
- Мониторинг фактического потребления ресурсов runtime.

### Сетевая модель Pod

Каждый Pod получает собственный сетевой namespace с уникальным IP-адресом. Все контейнеры внутри Pod разделяют этот IP.

**Ключевые принципы:**
- Контейнеры внутри Pod взаимодействуют через `localhost` (один сетевой стек).
- Каждый Pod доступен из других Pod по своему IP-адресу.
- Сетевая изоляция между Pod реализуется через NetworkPolicy.
- Реализация CNI (Container Network Interface) зависит от сетевого плагина (Calico, Cilium, Flannel).

**Сетевые взаимодействия Pod:**
- **Pod → Pod:** Напрямую по IP-адресу (в пределах кластера или между узлами).
- **Pod → Service:** Через виртуальный IP ClusterIP (balances).
- **Pod → External:** Через NAT (если `spec.externalTrafficPolicy: Cluster`) или напрямую (если `Local`).

**Проверка сетевой конфигурации:**
```bash
# IP-адрес Pod
kubectl get pod <pod-name> -o jsonpath='{.status.podIP}'

# Все IP-адреса (Dual-stack)
kubectl get pod <pod-name> -o jsonpath='{.status.podIPs[*].ip}'

# Сетевые политики для Pod
kubectl get networkpolicies -l app=<label> -o wide

# DNS-разрешение внутри Pod
kubectl exec <pod-name> -- nslookup kubernetes.default
```

### Сравнение типов Pod

| Тип | Управление | Цель жизни | Масштабирование | Примеры |
| :--- | :--- | :--- | :--- | :--- |
| **Static Pod** | `kubelet` на ноде | Пока работает kubelet | Фиксированное | etcd, kube-apiserver |
| **ReplicaSet Pod** | Deployment | Фиксированное число реплик | Horizontal scaling | Веб-сервисы, API |
| **StatefulSet Pod** | StatefulSet | Фиксированное число реплик | С уникальными именами | Базы данных, Kafka |
| **DaemonSet Pod** | DaemonSet | По одному на узел | Автоматически на новых узлах | Логирование, мониторинг |
| **Job Pod** | Job | До завершения задачи | Параллелизм | Batch-задачи, миграции |

---

## Практические сценарии

### Пример 1: Multi-container Pod с общим хранилищем

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: storage-demo
spec:
  volumes:
  - name: shared-vol
    emptyDir: {}
  containers:
  - name: producer
    image: busybox
    command: ["sh", "-c", "echo 'data' > /data/info.txt && sleep 3600"]
    volumeMounts:
    - name: shared-vol
      mountPath: /data
  - name: consumer
    image: busybox
    command: ["sh", "-c", "tail -f /data/info.txt"]
    volumeMounts:
    - name: shared-vol
      mountPath: /data
```

### Пример 2: Разделение PID Namespace (Отладка)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: debug-pid-sharing
spec:
  shareProcessNamespace: true
  containers:
  - name: app
    image: nginx
  - name: sidecar-debugger
    image: busybox
    command: ["sh", "-c", "ps aux && sleep 3600"]
```

### Пример 3: Нативный Sidecar (K8s 1.29+)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: native-sidecar-demo
spec:
  initContainers:
  - name: network-proxy
    image: envoyproxy/envoy
    restartPolicy: Always # Делает контейнер нативным сайдкаром
  containers:
  - name: main-app
    image: my-app:latest
```

### Пример 4: Production Multi-container Pod (App + Log Collector + Health Sidecar)

Типичный паттерн для продакшн-нагрузок: основное приложение + sidecar для сбора логов + sidecar для расширенной проверки здоровья.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: production-multi-container
  labels:
    app: web-api
    env: production
spec:
  shareProcessNamespace: true  # Общий PID namespace для signal handling
  volumes:
  - name: shared-logs
    emptyDir: {}
  - name: app-config
    projected:
      sources:
      - configMap:
          name: web-api-config
      - downwardAPI:
          items:
          - path: "pod-name"
            fieldRef:
              fieldPath: metadata.name
          - path: "node-name"
            fieldRef:
              fieldPath: spec.nodeName
  initContainers:
  # Native Sidecar: прокси для rate limiting
  - name: rate-limiter
    image: envoyproxy/envoy:v1.29
    restartPolicy: Always
    startupProbe:
      httpGet:
        path: /ready
        port: 9901
      failureThreshold: 30
      periodSeconds: 2
    volumeMounts:
    - name: app-config
      mountPath: /etc/envoy
  containers:
  # Основное приложение
  - name: app
    image: my-company/web-api:1.31.0
    ports:
    - containerPort: 8080
    resources:
      requests:
        cpu: "250m"
        memory: "512Mi"
      limits:
        cpu: "1"
        memory: "1Gi"
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 15
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
    securityContext:
      runAsNonRoot: true
      readOnlyRootFilesystem: true
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
    - name: app-config
      mountPath: /etc/app-config
      readOnly: true
  # Sidecar: сбор логов
  - name: log-collector
    image: fluent/fluentd:v1.16
    resources:
      requests:
        cpu: "50m"
        memory: "64Mi"
      limits:
        cpu: "200m"
        memory: "128Mi"
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
      readOnly: true
  terminationGracePeriodSeconds: 45
```

**Проверка:**
```bash
# Убедиться, что все контейнеры запущены
kubectl get pod production-multi-container -o wide
# → READY 2/3 (rate-limiter, app, log-collector)

# Проверить логи каждого контейнера
kubectl logs production-multi-container -c rate-limiter
kubectl logs production-multi-container -c app
kubectl logs production-multi-container -c log-collector

# Проверить PID sharing
kubectl exec production-multi-container -c app -- ps aux
```

### Пример 5: Diagnostics Pod (Отладка сетевых проблем)

Создание отладочного Pod'а для проверки сетевой доступности сервисов в кластере.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: network-debug
  labels:
    app: debug
spec:
  containers:
  - name: netshoot
    image: nicolaka/netshoot:latest
    command: ["sleep", "3600"]
    resources:
      requests:
        cpu: "50m"
        memory: "64Mi"
      limits:
        cpu: "200m"
        memory: "128Mi"
  restartPolicy: Never
  dnsPolicy: ClusterFirstWithHostNet
  hostNetwork: false
```

**Проверка:**
```bash
# Запустить отладочный Pod
kubectl apply -f network-debug.yaml

# Проверить DNS-разрешение
kubectl exec network-debug -- nslookup kubernetes.default

# Проверить доступность внешних сервисов
kubectl exec network-debug -- curl -s http://my-service.namespace.svc.cluster.local:8080/healthz

# Проверить маршрутизацию
kubectl exec network-debug -- traceroute my-service.namespace.svc.cluster.local

# Удалить после отладки
kubectl delete pod network-debug
```

### Пример 6: Pod с Init Container для подготовки окружения

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-init
spec:
  initContainers:
  - name: wait-for-dependencies
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z postgres-service 5432 && nc -z redis-service 6379; do echo "Waiting for dependencies..."; sleep 2; done']
  - name: db-migration
    image: my-app/migrations:1.31.0
    command: ['./migrate', 'up']
    env:
    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: url
  containers:
  - name: app
    image: my-app:1.31.0
    ports:
    - containerPort: 8080
```

**Проверка:**
```bash
# Наблюдать за progress init-контейнеров
kubectl get pod app-with-init --watch

# Проверить логи init-контейнера
kubectl logs app-with-init -c wait-for-dependencies
```

---

## Сравнение паттернов Pod

| Паттерн | Назначение | Контейнеры | Жизненный цикл | Примеры |
| :--- | :--- | :--- | :--- | :--- |
| **Sidecar** | Расширение функциональности | App + log-collector, proxy | Параллельный | Сбор логов, Service Mesh |
| **Init Container** | Подготовка окружения | Wait-for-deps, migration | Последовательный | Зависимости, миграции БД |
| **Native Sidecar** | Sidecar с гарантированным порядком | Proxy + App | Последовательный старт, параллельная работа | Envoy, rate-limiter |
| **Ambassador** | Проксирование трафика | App + proxy | Параллельный | Legacy-приложения, mTLS |
| **Adapter** | Унификация вывода | App + converter | Параллельный | Метрики в формат Prometheus |
| **Ephemeral** | Отладка работающего Pod | Temporary debug container | Временный | `kubectl debug` |

---

## Диагностика и типичные ошибки

### Ошибка 1: Pod в статусе `Pending`

**Причины:**
- Недостаточно ресурсов на узлах (CPU/memory).
- Нет узлов, соответствующих `nodeSelector` или `affinity`.
- Ожидание `PersistentVolumeClaim`.
- Ошибка `ImagePullBackOff` (проблемы с реестром образов).

**Диагностика:**
```bash
# Проверить события
kubectl describe pod <pod-name> | grep -A 10 "Events"

# Проверить доступные узлы
kubectl get nodes -o wide

# Проверить PVC
kubectl get pvc

# Проверить квоты ресурсов
kubectl get resourcequota -n <namespace>
```

**Решение:**
1. Проверить `kubectl describe pod` — событие укажет точную причину.
2. Для ресурсов: увеличить лимиты или добавить узлы.
3. Для affinity: проверить labels узлов (`kubectl get nodes --show-labels`).
4. Для образов: проверить доступность реестра и `imagePullSecrets`.

### Ошибка 2: Pod в статусе `CrashLoopBackOff`

**Причины:**
- Приложение завершается с ошибкой (exit code != 0).
- Ошибка в command/args контейнера.
- Отсутствуют переменные окружения или конфигурации.
- OOMKilled (недостаточно памяти).

**Диагностика:**
```bash
# Проверить логи предыдущего контейнера
kubectl logs <pod-name> -p

# Проверить код выхода и причину
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'

# Проверить, был ли OOMKilled
kubectl describe pod <pod-name> | grep -i "oom\|killed"
```

**Решение:**
1. Проверить логи (`kubectl logs <pod> -p`) для понимания ошибки.
2. Для OOMKilled: увеличить `limits.memory`.
3. Для ошибок command: проверить правильность аргументов.
4. Для ошибок зависимостей: использовать init-контейнеры для ожидания.

### Ошибка 3: Pod не проходит readinessProbe

**Причины:**
- Приложение ещё не готово принимать трафик.
- Неправильный эндпоинт проверки (path/port).
- Слишком частые проверки (перегрузка приложения).

**Диагностика:**
```bash
# Проверить условия Pod
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[*].type}'

# Проверить логи readiness-пробы
kubectl describe pod <pod-name> | grep -A 5 "Readiness"

# Проверить эндпоинт вручную
kubectl exec <pod-name> -- curl -s http://localhost:<port>/ready
```

**Решение:**
1. Проверить, что эндпоинт проб доступен внутри контейнера.
2. Увеличить `initialDelaySeconds` для медленно запускающихся приложений.
3. Использовать `startupProbe` для длительного старта.

### Ошибка 4: Pod не запускается из-за `ImagePullBackOff`

**Причины:**
- Неправильное имя образа или тег.
- Образ в приватном реестре без `imagePullSecrets`.
- Проблемы с сетью (нет доступа к реестру).

**Диагностика:**
```bash
# Проверить событие
kubectl describe pod <pod-name> | grep -i "image"

# Проверить секреты для реестра
kubectl get secrets | grep docker-registry
```

**Решение:**
1. Проверить имя образа: `docker pull <image>` локально.
2. Создать `imagePullSecrets` для приватных реестров.
3. Проверить сетевой доступ с узла до реестра.

---

## Лучшие практики для DevOps/SRE

### 1. Мониторинг и наблюдаемость

- Используйте стандартные метки (`app.kubernetes.io/name`, `app.kubernetes.io/version`) для агрегации метрик в Prometheus/Grafana.
- Настройте `readinessProbe` и `livenessProbe` для автоматического обнаружения проблем.
- Собирайте логи через sidecar-контейнеры или DaemonSet (Fluentd, Filebeat).
- Мониторьте `pod_status` и `container_status` через alerting rules.

### 2. Безопасность

- Всегда указывайте `securityContext` с `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`.
- Используйте Pod Security Standards (PSS) для контроля допустимых конфигураций.
- Не храните секреты в переменных окружения — используйте Secret или Projected Volumes.
- Ограничивайте сетевой доступ через NetworkPolicy.

### 3. Управление ресурсами

- Всегда указывайте `requests` и `limits` для каждого контейнера.
- Используйте QoS классы (Guaranteed, Burstable, BestEffort) в зависимости от критичности приложения.
- Настройте `terminationGracePeriodSeconds` в зависимости от времени завершения приложения.
- Используйте PodDisruptionBudget для контроля доступности при обслуживании.

### 4. Производительность запуска

- Используйте `imagePullPolicy: IfNotPresent` для фиксированных тегов.
- Кэшируйте часто используемые образы на узлах.
- Используйте init-контейнеры для подготовки среды вместо усложнения основного образа.
- Избегайте излишне больших образов — чем меньше образ, тем быстрее запуск.

### 5. Диагностика

- Включите `shareProcessNamespace: true` для возможности отладки через sidecar-контейнеры.
- Используйте ephemeral containers (`kubectl debug`) для отладки без перезапуска Pod.
- Настройте `terminationMessagePath` и `terminationMessagePolicy` для сохранения информации о падениях.
- Используйте `kubectl top pod` для мониторинга потребления ресурсов в реальном времени.

---

## Дополнительная информация

**Связанные темы:**

- [Рекомендации по написанию манифестов Pod](./pod_best_practices.md) — лимиты, пробы, безопасность.
- [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — фазы, условия, shutdown.
- [Sidecar Patterns в Kubernetes](./pod_sidecar_patterns.md) — Ambassador, Adapter, Native Sidecars.
- [Init-container в Kubernetes](./pod_init_containers.md) — подготовка окружения.
- [Эфемерные контейнеры в Kubernetes](./ephemeral_containers.md) — отладка «на лету».
- [QoS и управление ресурсами в Kubernetes](../../Scheduling/qos_limit_and_requests.md) — влияние на стабильность узла.
- [Практические команды управления Pod](./pod_practical_scenarios_commands.md) — kubectl команды для диагностики.
- [Продвинутые темы Pod](./pod_advanced_topics.md) — RuntimeClass, DNS, Readiness Gates.
