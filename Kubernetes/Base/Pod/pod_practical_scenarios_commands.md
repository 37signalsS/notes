# Практические сценарии и команды управления Pod

**Актуально для:** Kubernetes 1.30–1.32+

---

## Определения

**kubectl** — основной CLI-инструмент управления кластером Kubernetes. Выполняет аутентифицированные HTTP REST-запросы к `kube-apiserver`, транслируя пользовательские команды в манипуляции над объектами etcd и субресурсами API.

**Императивный подход (Imperative management)** — непосредственное выполнение действий над ресурсами через CLI-команды (`kubectl run`, `kubectl scale`, `kubectl delete`). Каждая команда указывает системе *действие* («что сделать»), выполняется немедленно и не фиксирует декларативную историю конфигурации в системе контроля версий.

**Декларативный подход (Declarative management)** — управление состоянием кластера через файлы манифестов (YAML/JSON). Пользователь описывает *желаемое конечное состояние* (`kubectl apply`), а управляющие циклы контроллеров приводят реальное состояние системы к целевому (IaC — Infrastructure as Code).

**Client-Side Apply (CSA)** — классический механизм применения манифестов, при котором трехстороннее слияние (3-way merge) вычисляется на локальной машине клиента с использованием аннотации `kubectl.kubernetes.io/last-applied-configuration`.

**Server-Side Apply (SSA)** — современный декларативный механизм (GA в 1.22+, стандарт для GitOps и CI/CD в 1.30+), при котором слияние и валидация выполняются на стороне `kube-apiserver`. Каждое поле отслеживается в метаданных `metadata.managedFields`, гарантируя атомарность и исключая непреднамеренную перезапись параметров сторонними контроллерами.

**Субресурс API (Subresource)** — специализированная конечная точка REST API Kubernetes, логически привязанная к родительскому объекту, но реализующая собственный протокол или поведение. Для Pod ключевыми субресурсами являются `/status`, `/exec`, `/attach`, `/log`, `/portforward` и `/ephemeralcontainers`.

**Streaming-протоколы (SPDY / WebSocket RFC 6455)** — двунаправленные протоколы передачи данных, используемые для мультиплексирования потоков stdin/stdout/stderr/error при выполнении команд `exec`, `attach` и `port-forward`. Начиная с Kubernetes 1.30, потоковая передача через WebSockets полностью стабилизирована (GA) и заменяет устаревший протокол SPDY.

**JSONPath** — язык выражений для фильтрации, парсинга и форматированного извлечения конкретных узлов и значений из структуры ответов JSON/YAML API Kubernetes.

**Field Selector** — механизм серверной фильтрации ресурсов по фиксированному набору системных полей спецификации или статуса (например, `status.phase=Running`, `spec.nodeName=node1`), снижающий нагрузку на сеть и `kube-apiserver`.

**Финализаторы (Finalizers)** — ключи в массиве `metadata.finalizers`, блокирующие физическое удаление объекта из etcd до завершения очистки внешних зависимостей (например, отмонтирования блочных CSI-томов или сетевых маршрутов).

**kubectl proxy** — локальный HTTP-прокси-сервер, транслирующий незашифрованные HTTP-запросы с машины администратора (по умолчанию `localhost:8001`) в защищенный TLS-канал к `kube-apiserver` с автоматической подстановкой текущих учетных данных контекста kubeconfig.

**kubectl port-forward** — инструмент создания L4 TCP-туннеля между портом на машине администратора и сетевым пространством имен Pod через защищенный канал `kube-apiserver` → `kubelet`. Не поддерживает протокол UDP.

**kubectl attach** — подключение к дескрипторам ввода-вывода (stdin/stdout/stderr) уже запущенного процесса контейнера (PID 1). В отличие от `exec`, **не создает новый дочерний процесс**.

**kubectl cp** — утилита копирования файлов и каталогов между локальной файловой системой и файловой системой контейнера. Работает через инициализацию архиватора `tar` внутри контейнера через вызов `exec`.

**kubectl auth can-i** — инструмент локального и серверного аудита прав RBAC (`SelfSubjectAccessReview` / `SubjectAccessReview`), позволяющий проверить возможность выполнения действия конкретным пользователем, группой или ServiceAccount.

---

## Базовые концепции и архитектура

### Методы создания и модификации Pod

| Команда | Подход | Механизм слияния / работы | Практическое применение |
| :--- | :--- | :--- | :--- |
| `kubectl run` | Императивный | Прямой вызов POST к `/api/v1/namespaces/{ns}/pods`. | Разовые тесты, проверка DNS, сетевая диагностика. |
| `kubectl create` | Императивный | Создает ресурс из YAML/CLI; возвращает ошибку, если ресурс существует. | Запуск Batch Job, разовых задач инициализации. |
| `kubectl apply` | Декларативный (CSA) | 3-way merge через `kubectl.kubernetes.io/last-applied-configuration`. | Традиционные конвейеры CI/CD. |
| `kubectl apply --server-side` | Декларативный (SSA) | Отслеживание владения полями в `metadata.managedFields` на сервере. | **Современный стандарт GitOps, CI/CD, production.** |
| `kubectl patch` | Императивный | Применение частичного патча (Strategic Merge, JSON Merge, JSON Patch). | Точечные скриптовые правки (метки, аннотации, образы). |
| `kubectl edit` | Императивный | Выгрузка манифеста во временный файл `$EDITOR` с последующим PUT/PATCH. | Экстренная ручная правка параметров на лету. |
| `kubectl replace` | Декларативный | Полная замена объекта через PUT; падает при расхождении `resourceVersion`. | Строгая перезапись без объединения полей. |
| `kubectl delete` | Императивный | Выставление `deletionTimestamp` и запуск graceful shutdown. | Завершение жизненного цикла, эвакуация. |

#### Сравнение Client-Side Apply и Server-Side Apply

*   **Client-Side Apply:** Клиентский `kubectl` считывает локальный файл, текущую конфигурацию из кластера и аннотацию предыдущего применения `last-applied-configuration`. Если размер манифеста велик (например, огромный CRD или ConfigMap), размер аннотации может превысить системный лимит метаданных в 256 КБ, что приведет к ошибке `metadata.annotations: Too long`.
*   **Server-Side Apply:** Клиент отправляет манифест напрямую на `kube-apiserver` с указанием идентификатора владельца (`--field-manager`). API-сервер сопоставляет поля с существующим списком `metadata.managedFields`. Если сторонний менеджер изменил то же поле, возвращается `ApplyConflict` (HTTP 409), предотвращая затирание настроек контроллеров.

```yaml
# Фрагмент metadata.managedFields при использовании Server-Side Apply
metadata:
  managedFields:
  - manager: kubectl-client-side-apply
    operation: Update
    apiVersion: v1
    time: "2026-02-10T12:00:00Z"
    fieldsType: FieldsV1
    fieldsV1:
      f:spec:
        f:containers:
          k:{"name":"app"}:
            f:image: {}
```

#### Стратегии патчинга (kubectl patch)

1.  **Strategic Merge Patch** (по умолчанию для встроенных ресурсов K8s): объединяет структуры и списки на основе ключевых полей схемы (например, контейнеры в списке объединяются по имени `name`).
2.  **JSON Merge Patch** (`--type=merge`, RFC 7386): полностью заменяет массивы новыми значениями, но объединяет вложенные объекты. Чтобы удалить ключ, ему присваивается значение `null`.
3.  **JSON Patch** (`--type=json`, RFC 6902): строгий массив атомарных операций (`add`, `remove`, `replace`, `move`, `copy`, `test`).

---

### Архитектура выполнения CLI-команд (exec, attach, port-forward, logs, cp)

CLI-команды взаимодействия с запущенными контейнерами проходят сквозь все компоненты архитектуры Kubernetes:

```
[ Администратор ]
       │
       ▼ (1) HTTPS REST /api/v1/.../exec (Upgrade: websocket / SPDY)
[ kube-apiserver ]
       │
       ▼ (2) HTTPS TLS :10250 (Bearer Token / Client Cert)
   [ kubelet ]
       │
       ▼ (3) gRPC ExecSync / Exec / PortForward stream
[ CRI Runtime: containerd / CRI-O ]
       │
       ▼ (4) fork/clone в cgroups и namespaces
[ runc / crun ] ────► [ Процесс контейнера (PID N) ]
```

1.  **Инициализация запроса:** `kubectl` формирует REST-запрос к субресурсу Pod на `kube-apiserver` с заголовком обновления протокола (`Upgrade: websocket` или `Upgrade: SPDY/3.1`).
2.  **Авторизация и проксирование:** `kube-apiserver` проверяет права RBAC вызывающего субъекта на субресурс (например, `pods/exec`), открывает TLS-соединение к порту 10250 `kubelet` того рабочего узла, на котором размещен Pod, и транслирует запрос.
3.  **Обращение к рантайму:** `kubelet` по gRPC обращается к Container Runtime Interface (containerd или CRI-O), вызывая метод потоковой передачи (`Streaming Runtime Service`).
4.  **Изоляция пространств имен:** Рантайм через низкоуровневый OCI-рантайм (`runc` или `crun`) входит в существующие Linux namespaces контейнера (`net`, `mnt`, `pid`, `ipc`, `uts`) и запускает изолированный процесс.

#### Ключевые различия подсистем доступа:

*   **`kubectl exec` vs `kubectl attach`:**
    *   `exec` запускает **новый дочерний процесс** в пространствах имен контейнера.
    *   `attach` подключается к **уже работающему процессу с PID 1**, перехватывая его файловые дескрипторы `0 (stdin)`, `1 (stdout)` и `2 (stderr)`. Завершение `attach` с отправкой EOF (Ctrl+C/Ctrl+D) при включенном `stdin` может аварийно завершить PID 1 и уронить весь контейнер.
*   **Механизм `kubectl cp`:**
    `kubectl cp` не реализует собственный протокол передачи файлов. На стороне контейнера через субресурс `exec` вызывается бинарник `tar` (`tar -cf - ...` или `tar -xf - ...`), а поток архива прокачивается через stdout/stdin стрима.
    *Следствие:* Если в контейнере отсутствует утилита `tar` (базовые образы `distroless`, `scratch`), команда завершается ошибкой.
*   **Механизм `kubectl port-forward`:**
    Туннелирует L4 TCP-пакеты. `kubelet` на целевом узле открывает сокет в сетевом пространстве имен (`netns`) пода и перенаправляет полезную нагрузку стрима между локальным сокетом администратора и портом внутри пода.
    *Ограничение:* Протокол взаимодействия субресурса `portforward` в API Kubernetes поддерживает **только TCP**. Пробросить UDP-трафик напрямую через `port-forward` невозможно.

---

### Стандартный алгоритм SRE/DevOps диагностики Pod

При возникновении аварийной ситуации с Pod диагностика выполняется последовательно от уровня API к уровню узла:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Состояние на уровне API (kubectl get pod -o wide)       │
│    - Фаза (Pending, Running, Failed, Unknown)               │
│    - Готовность (READY 0/1) и количество рестартов (RESTARTS)│
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Системные события (kubectl get events)                   │
│    - Ошибки планировщика (FailedScheduling)                 │
│    - Ошибки образов и томов (ImagePullBackOff, FailedMount)  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Детализация Pod (kubectl describe pod <name>)            │
│    - Conditions (PodScheduled, Initialized, Ready, ContainersReady)
│    - Last State (Exit Code, OOMKilled, Reason, Message)     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Анализ потоков вывода (kubectl logs)                     │
│    - Логи текущего контейнера (kubectl logs)                │
│    - Логи аварийно завершившегося инстанса (--previous)     │
│    - Логи сопутствующих sidecar и init-контейнеров (-c)     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Интерактивное исследование (kubectl debug / exec)        │
│    - Подключение эфемерного netshoot/busybox контейнера     │
│    - Проверка сокетов, DNS, локальных файлов конфигураций   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Уровень хоста / рантайма (crictl, journalctl, /var/log)   │
│    - Состояние kubelet на ноде (journalctl -u kubelet)      │
│    - Состояние OCI-рантайма (crictl ps, crictl inspect)     │
│    - Анализ dmesg (системный OOM Killer Linux ядра)         │
└─────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Генерация манифестов и быстрое развертывание (Zero-Boilerplate & Dry-Run)

Императивная генерация корректных YAML-манифестов без ручного написания структуры.

```bash
# Генерация чистого манифеста Pod без создания ресурса в кластере
kubectl run web-app --image=nginx:1.27-alpine --port=80 --env="ENV=prod" --env="LOG_LEVEL=info" --dry-run=client -o yaml > pod-web.yaml
cat pod-web.yaml
# → apiVersion: v1
# → kind: Pod
# → metadata:
# →   creationTimestamp: null
# →   labels:
# →     run: web-app
# →   name: web-app
# → spec:
# →   containers:
# →   - env:
# →     - name: ENV
# →       value: prod
# →     - name: LOG_LEVEL
# →       value: info
# →     image: nginx:1.27-alpine
# →     name: web-app
# →     ports:
# →     - containerPort: 80
# →     resources: {}
# →   dnsPolicy: ClusterFirst
# →   restartPolicy: Always
# → status: {}

# Предварительная серверная валидация манифеста (проверка через Admission Controllers)
kubectl apply -f pod-web.yaml --dry-run=server
# → pod/web-app created (server dry run)

# Просмотр точного diff перед применением изменений
kubectl diff -f pod-web.yaml
# → [diff output с демонстрацией вносимых изменений]

# Применение манифеста через Server-Side Apply с явным указанием field-manager
kubectl apply -f pod-web.yaml --server-side --field-manager=sre-deployer
# → pod/web-app serverside-applied
```

---

### Сценарий 2: Продвинутая выборка, фильтрация и аналитика (JSONPath, Custom Columns, Field Selectors)

Инструменты выборки для скриптов автоматизации и повседневного аудита кластера.

```bash
# Выборка подов в определенном статусе через серверный field-selector
kubectl get pods --field-selector=status.phase=Failed -A -o wide
# → NAMESPACE   NAME             READY   STATUS   RESTARTS   AGE   IP          NODE     NOMINATED NODE   READINESS GATES
# → default     batch-job-xk92   0/1     Error    0          2d    10.244.2.45 node-02  <none>           <none>

# Поиск подов, размещенных на конкретном рабочем узле
kubectl get pods --field-selector=spec.nodeName=worker-node-01 -A
# → NAMESPACE     NAME                          READY   STATUS    RESTARTS   AGE
# → kube-system   coredns-7c65d6cfc9-5l28d      1/1     Running   0          45d
# → monitoring    node-exporter-4z8qp           1/1     Running   1          45d

# Формирование читаемой таблицы с кастомными столбцами (нода, IP, статус, рестарты)
kubectl get pods -o custom-columns="NAME:.metadata.name,NODE:.spec.nodeName,POD_IP:.status.podIP,RESTARTS:.status.containerStatuses[0].restartCount"
# → NAME       NODE             POD_IP        RESTARTS
# → web-app    worker-node-01   10.244.1.88   0
# → api-app    worker-node-02   10.244.2.14   3

# Извлечение всех IP-адресов подов в текущем namespace через JSONPath
kubectl get pods -o jsonpath='{.items[*].status.podIP}'
# → 10.244.1.88 10.244.2.14 10.244.1.89

# Поиск контейнеров, у которых число перезапусков превышает 0
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.name}{": restarts="}{.restartCount}{" "}{end}{"\n"}{end}' | awk '$2 !~ /restarts=0/'
# → api-app    backend: restarts=3

# Извлечение точных SHA256 ImageID запущенных контейнеров
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.name}{": "}{.imageID}{"\n"}{end}{end}'
# → web-app    web-app: docker.io/library/nginx@sha256:0a399eb067dc1dd374ec7621f2280d388856000c0291e6e69cb43d932b04b173

# Мониторинг изменений состояния в реальном времени с выводом событий изменения
kubectl get pods -w --output-watch-events
# → EVENT    NAME      READY   STATUS    RESTARTS   AGE
# → ADDED    web-app   0/1     Pending   0          0s
# → MODIFIED web-app   0/1     ContainerCreating 0 1s
# → MODIFIED web-app   1/1     Running   0          3s
```

---

### Сценарий 3: Диагностика многоконтейнерных подов и работа с логами

Техники изолированного и агрегированного сбора телеметрии из контейнеров.

```bash
# Вывод логов конкретного контейнера в Pod (например, envoy-proxy в sidecar-схеме)
kubectl logs web-app -c envoy-proxy --tail=100
# → [2026-02-10T12:30:15.120Z] "GET /healthz HTTP/1.1" 200 - 0 15 2 2 "-" "Go-http-client/1.1"

# Просмотр логов аварийно упавшего контейнера до момента рестарта
kubectl logs web-app -c app-container --previous
# → 2026-02-10T12:28:44.012Z FATAL [main] OutOfMemoryError: Java heap space
# → 2026-02-10T12:28:44.015Z Dumping heap to java_pid1.hprof ...

# Потоковый вывод логов всех контейнеров пода одновременно с префиксами
kubectl logs web-app --all-containers=true -f --prefix=true
# → [pod/web-app/app-container] Serving HTTP on 0.0.0.0 port 8080 ...
# → [pod/web-app/envoy-proxy] [info] upstream connected: 127.0.0.1:8080

# Логи с таймстампами за последние 15 минут
kubectl logs web-app --since=15m --timestamps=true
# → 2026-02-10T12:15:00.004123512Z [INFO] Processing batch task #4102

# Агрегированный сбор логов со всех подов приложения по селектору меток
kubectl logs -l app=payment-service --all-containers=true --tail=50 --max-log-requests=10
# → [Логи со всех реплик payment-service]
```

---

### Сценарий 4: Туннелирование и локальная отладка (kubectl port-forward & proxy)

Организация безопасного доступа к изолированным внутрикластерным службам без публичной публикации.

```bash
# Проброс локального порта 8080 на порт 80 Pod
kubectl port-forward pod/web-app 8080:80
# → Forwarding from 127.0.0.1:8080 -> 80
# → Forwarding from [::1]:8080 -> 80
# → Handling connection for 8080

# Проброс порта с привязкой ко всем сетевым интерфейсам хоста (для доступа с внешней VM)
kubectl port-forward --address 0.0.0.0 pod/web-app 8080:80
# → Forwarding from 0.0.0.0:8080 -> 80

# Проброс нескольких портов одновременно (HTTP-трафик и метрики приложения)
kubectl port-forward pod/web-app 8080:80 9090:9090
# → Forwarding from 127.0.0.1:8080 -> 80
# → Forwarding from 127.0.0.1:9090 -> 9090

# Проброс порта на Service (автоматический Round-Robin выбор доступного Ready-пода)
kubectl port-forward svc/postgres-service 5432:5432
# → Forwarding from 127.0.0.1:5432 -> 5432

# Запуск kubectl proxy для прямого обращения к API Kubernetes и субресурсам проксирования
kubectl proxy --port=8001 &
# → Starting to serve on 127.0.0.1:8001

# Обращение к эндпоинту пода напрямую через API Server Proxy
curl -s http://127.0.0.1:8001/api/v1/namespaces/default/pods/web-app:80/proxy/
# → <!DOCTYPE html><html><head><title>Welcome to nginx!</title></head>...
```

> **Важно (SRE/DevOps):** `kubectl port-forward` работает исключительно по протоколу **TCP**. Для отладки UDP-протоколов (DNS, Syslog, SNMP) необходимо подключать отладочный контейнер с `socat` в сетевое пространство имен пода:
> ```bash
> kubectl debug -it web-app --image=alpine/socat --target=app -- socat - UDP-RECV:514
> ```

---

### Сценарий 5: Управление жизненным циклом и автоматизация CI/CD (wait, rollout, force delete)

Идиоматичное управление статусом в Bash-скриптах пайплайнов развертывания.

```bash
# Ожидание перехода Pod в состояние Ready (готовность к обслуживанию трафика)
kubectl wait --for=condition=Ready pod/web-app --timeout=90s
# → pod/web-app condition met

# Ожидание успешного завершения выполнения разового Pod / Job
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/migration-task --timeout=300s
# → pod/migration-task condition met

# Ожидание полного удаления Pod перед началом следующей фазы
kubectl wait --for=delete pod/old-instance --timeout=60s
# → pod/old-instance condition met

# Инициирование плавного перезапуска подов через управляющий Deployment
kubectl rollout restart deployment/web-deployment
# → deployment.apps/web-deployment restarted

# Блокирующее отслеживание статуса раскатки
kubectl rollout status deployment/web-deployment --timeout=120s
# → Waiting for deployment "web-deployment" rollout to finish: 1 of 3 updated replicas are available...
# → deployment "web-deployment" successfully rolled out

# Принудительное аварийное удаление зависшего пода (БЕЗ ожидания graceful period)
kubectl delete pod stuck-pod --force --grace-period=0
# → Warning: Immediate deletion does not wait for confirmation that the running resource has been terminated.
# → pod "stuck-pod" force deleted
```

> **Опасность (SRE):** Принудительное удаление (`--force --grace-period=0`) удаляет объект только из `etcd`. Если узел потерял связь с control-plane, процесс на ноде продолжает выполняться! Для баз данных и систем с StatefulSet это создает риск **Split-Brain** и повреждения данных при преждевременном запуске реплики на другой ноде.

---

### Сценарий 6: Инспекция потребления ресурсов, лимитов и OOMKilled

Анализ метрик потребления оперативной памяти и процессорного времени.

```bash
# Просмотр потребления ресурсов подом (требует metrics-server)
kubectl top pod web-app
# → NAME      CPU(cores)   MEMORY(bytes)
# → web-app   15m          64Mi

# Детализация потребления по контейнерам внутри пода
kubectl top pod web-app --containers
# → POD       NAME            CPU(cores)   MEMORY(bytes)
# → web-app   app-container   14m          52Mi
# → web-app   envoy-proxy     1m           12Mi

# Поиск подов с наибольшим потреблением RAM во всем кластере
kubectl top pods -A --sort-by=memory | head -n 10
# → NAMESPACE     NAME                          CPU(cores)   MEMORY(bytes)
# → monitoring    prometheus-k8s-0              125m         2048Mi
# → database      postgres-primary-0            85m          1536Mi

# Извлечение точной причины падения контейнера (Exit Code 137 = OOMKilled / SIGKILL)
kubectl get pod web-app -o jsonpath='{range .status.containerStatuses[*]}{.name}{": lastState="}{.lastState.terminated.reason}{", exitCode="}{.lastState.terminated.exitCode}{"\n"}{end}'
# → app-container: lastState=OOMKilled, exitCode=137

# Сопоставление гарантированных запросов (requests) с текущим потреблением
kubectl get pod web-app -o custom-columns="NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory,CPU_LIM:.spec.containers[*].resources.limits.cpu,MEM_LIM:.spec.containers[*].resources.limits.memory"
# → NAME      CPU_REQ   MEM_REQ   CPU_LIM   MEM_LIM
# → web-app   100m      128Mi     500m      256Mi
```

---

### Сценарий 7: Безопасная передача файлов и артефактов (kubectl cp & piping)

Копирование дампов памяти, журналов и конфигураций без модификации образов.

```bash
# Копирование файла лога из контейнера на хост инженера
kubectl cp default/web-app:/var/log/nginx/access.log ./local-access.log -c web-app
# → [Успешная загрузка файла]

# Загрузка локального конфигурационного файла в контейнер
kubectl cp ./custom-nginx.conf default/web-app:/etc/nginx/conf.d/default.conf -c web-app

# Обход ограничения distroless-образов (без tar): передача данных через stdin-pipe
cat ./app.properties | kubectl exec -i web-app -c web-app -- sh -c 'cat > /etc/app/app.properties'

# Выгрузка бинарных данных/дампов памяти напрямую через поток вывода stdout
kubectl exec web-app -c web-app -- jcmd 1 GC.heap_dump /tmp/heap.hprof > /dev/null
kubectl exec web-app -c web-app -- cat /tmp/heap.hprof > ./local-dump.hprof
```

---

### Сценарий 8: Сетевая отладка и тестирование связности (Ephemeral Netshoot & Debug Pods)

Глубокий анализ сети без внедрения утилит траблшутинга в базовые образы.

```bash
# Запуск эфемерного контейнера с полным набором сетевых утилит в сетевом пространстве пода
kubectl debug -it web-app --image=nicolaka/netshoot --target=web-app
# → Target container "web-app" will not see processes in debug container.
# → If you need process sharing, specify --share-processes on the pod.
# → Entering debug container...

# [Внутри отладочного контейнера netshoot]:
# 1. Проверка разрешения внутренних DNS-имен кластера
nslookup kubernetes.default.svc.cluster.local
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

# 2. Проверка открытых портов соседних сервисов
nc -zvw 3 database-service.default.svc.cluster.local 5432
# → database-service (10.96.120.45:5432) open

# 3. Захват пакетов на сетевом интерфейсе пода для локализации таймаутов
tcpdump -nn -i eth0 port 80 -c 5
# → 12:45:01.120340 IP 10.244.2.1.48202 > 10.244.1.88.80: Flags [S], seq 38192019

# Запуск временного независимого Pod для проверки доступности узла и шлюза
kubectl run net-probe --rm -it --restart=Never --image=nicolaka/netshoot -- curl -Iv http://web-app:80
# → HTTP/1.1 200 OK
# → Server: nginx/1.27.0
# → pod "net-probe" deleted
```

---

### Сценарий 9: Аудит и отладка RBAC прав (kubectl auth can-i)

Проверка разрешений служебных учетных записей (ServiceAccount) для предотвращения ошибок доступа.

```bash
# Проверка возможности создания подов служебной учетной записью CI/CD
kubectl auth can-i create pods --as=system:serviceaccount:ci-cd:deployer-sa -n production
# → yes

# Проверка доступа к субресурсу выполнения команд exec
kubectl auth can-i create pods/exec --as=developer-user -n production
# → no

# Проверка доступа к субресурсу чтения логов
kubectl auth can-i get pods/log --as=developer-user -n production
# → yes

# Выгрузка полной таблицы прав конкретного ServiceAccount
kubectl auth can-i --list --as=system:serviceaccount:default:app-operator
# → Resources                                Non-Resource URLs   Resource Names   Verbs
# → configmaps                               []                  []               [get list watch]
# → pods                                     []                  []               [get list watch create update]
# → pods/status                              []                  []               [get patch update]
```

---

### Сценарий 10: Мониторинг и хронология событий (kubectl get events)

Фильтрация системных оповещений кластера для локализации сбоев планирования и запуска.

```bash
# Получение событий с сортировкой по времени последнего возникновения
kubectl get events --sort-by='.lastTimestamp' -A
# → NAMESPACE   LAST SEEN   TYPE      REASON              OBJECT         MESSAGE
# → default     45s         Warning   FailedScheduling    pod/heavy-pod  0/3 nodes are available: 3 Insufficient memory.

# Выборка только предупреждений и ошибок (Warning) в текущем namespace
kubectl get events --field-selector type=Warning
# → LAST SEEN   TYPE      REASON       OBJECT        MESSAGE
# → 2m          Warning   Unhealthy    pod/web-app   Readiness probe failed: HTTP probe failed with statuscode: 500

# Фильтрация событий, относящихся строго к конкретному Pod
kubectl get events --field-selector involvedObject.name=web-app
# → LAST SEEN   TYPE     REASON      OBJECT        MESSAGE
# → 15m         Normal   Scheduled   pod/web-app   Successfully assigned default/web-app to worker-node-01
# → 15m         Normal   Pulled      pod/web-app   Container image "nginx:1.27-alpine" already present on node
# → 15m         Normal   Created     pod/web-app   Created container web-app
# → 15m         Normal   Started     pod/web-app   Started container web-app

# Отслеживание потока событий в реальном времени с форматированием
kubectl get events -w -o custom-columns="TIME:.lastTimestamp,TYPE:.type,REASON:.reason,OBJECT:.involvedObject.name,MSG:.message"
# → TIME                   TYPE      REASON      OBJECT    MSG
# → 2026-02-10T13:00:10Z   Normal    Scheduled   test-pod  Successfully assigned default/test-pod to worker-node-02
```

---

### Сценарий 11: Аварийный траблшутинг «зависших» подов (Terminating, Finalizers, Node NotReady)

Решение проблем, когда Pod не может быть удален стандартным путем.

```bash
# Выявление подов, зависших в стадии удаления (наличие deletionTimestamp)
kubectl get pods -A -o json | jq -r '.items[] | select(.metadata.deletionTimestamp != null) | "\(.metadata.namespace)/\(.metadata.name)"'
# → storage/stuck-database-pod

# Просмотр активных финализаторов, удерживающих Pod в etcd
kubectl get pod stuck-database-pod -n storage -o jsonpath='{.metadata.finalizers}'
# → ["kubernetes.io/pvc-protection"]

# Аварийное снятие финализаторов через patch (разрешает удаление объекта из etcd)
kubectl patch pod stuck-database-pod -n storage -p '{"metadata":{"finalizers":null}}'
# → pod/stuck-database-pod patched

# Анализ состояния пода, если узел перешел в NotReady
kubectl get nodes
# → NAME             STATUS     ROLES    AGE   VERSION
# → worker-node-01   NotReady   <none>   45d   v1.30.2
# → worker-node-02   Ready      <none>   45d   v1.30.2

# Проверка подов на выпавшем узле (контроллер ожидает pod-eviction-timeout, по умолчанию 5 минут)
kubectl get pods -A --field-selector spec.nodeName=worker-node-01
# → NAMESPACE   NAME      READY   STATUS        RESTARTS   AGE
# → default     api-pod   1/1     Terminating   0          10d
```

> **Правило безопасности (SRE):** Перед снятием финализаторов или выполнением `--force --grace-period=0` на выпавшем узле, убедитесь физически (через IPMI/iLO/BMC или SSH), что старый узел действительно выключен или изолирован от сети (STONITH/Fencing). В противном случае параллельный запуск экземпляра с тем же постоянным диском приведет к повреждению файловой системы.

---

### Сценарий 12: Модификация на лету и патчинг (edit, patch, label, annotate)

Быстрое динамическое управление метаданными и конфигурацией без перезапуска контроллеров.

```bash
# Добавление диагностической метки на работающий Pod
kubectl label pod web-app debug-session=active
# → pod/web-app labeled

# Удаление метки с пода (знак минус в конце имени ключа)
kubectl label pod web-app debug-session-
# → pod/web-app unlabeled

# Добавление аннотации с описанием инцидента
kubectl annotate pod web-app incident.sre.io/ticket="INC-8491" --overwrite
# → pod/web-app annotated

# Патчинг Pod через Strategic Merge Patch (обновление образа контейнера на лету)
kubectl patch pod web-app --type=strategic -p '{"spec":{"containers":[{"name":"web-app","image":"nginx:1.27.1-alpine"}]}}'
# → pod/web-app patched

# Патчинг через JSON Patch RFC 6902 (точечная замена значения)
kubectl patch pod web-app --type=json -p='[{"op": "replace", "path": "/spec/terminationGracePeriodSeconds", "value": 60}]'
# → pod/web-app patched
```

---

### Сценарий 13: Нодовая диагностика без API-сервера (Sysadmin Break-Glass)

Прямое низкоуровневое управление контейнерами на рабочем узле в аварийных ситуациях (API-сервер недоступен, Kubelet не отвечает на команды).

```bash
# 1. Поиск контейнеров Pod через интерфейс crictl на хосте
ssh root@worker-node-01 "crictl pods --name web-app"
# → POD ID              CREATED         STATE    NAME      NAMESPACE   ATTEMPT
# → 8f23bc110a21d       2 hours ago     Ready    web-app   default     0

# 2. Вывод запущенных контейнеров внутри найденного Sandbox Pod
ssh root@worker-node-01 "crictl ps --pod 8f23bc110a21d"
# → CONTAINER ID        IMAGE           CREATED         STATE    NAME      ATTEMPT
# → e71b84920fc91       nginx:1.27      2 hours ago     Running   web-app   0

# 3. Чтение сырых логов контейнера напрямую с диска узла (минуя API-сервер)
ssh root@worker-node-01 "cat /var/log/pods/default_web-app_*/web-app/0.log | tail -n 20"
# → 2026-02-10T12:00:15.129482120Z stdout F 10.244.0.1 - - [10/Feb/2026:12:00:15 +0000] "GET / HTTP/1.1" 200

# 4. Получение PID корневого процесса контейнера на хосте
CONTAINER_PID=$(ssh root@worker-node-01 "crictl inspect e71b84920fc91 | jq .info.pid")
echo "Container Host PID: $CONTAINER_PID"
# → Container Host PID: 42195

# 5. Вход в сетевое и файловое пространство имен процесса через nsenter
ssh root@worker-node-01 "nsenter -t $CONTAINER_PID -n ip addr show"
# → 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN
# → 2: eth0@if15: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP
# →    inet 10.244.1.88/24 brd 10.244.1.255 scope global eth0
```

---

### Сценарий 14: Автоматизация очистки и пакетной ротации подов

Очистка кластера от завершенных, упавших или вытесненных (Evicted) подов.

```bash
# Удаление всех успешно завершившихся подов (например, после Job)
kubectl delete pods --field-selector=status.phase=Succeeded -A
# → pod "backup-task-28491" deleted
# → pod "migration-run-1" deleted

# Удаление всех упавших подов со статусом Failed во всем кластере
kubectl delete pods --field-selector=status.phase=Failed -A
# → pod "crash-test-99" deleted

# Пакетное удаление вытесненных подов (Evicted) через фильтрацию JSON
kubectl get pods -A -o json | jq -r '.items[] | select(.status.reason=="Evicted") | "\(.metadata.namespace) \(.metadata.name)"' | while read ns pod; do kubectl delete pod $pod -n $ns; done
# → pod "worker-node-cache-pod" deleted

# Удаление подов, привязанных к удаленным контроллерам (осиротевшие поды)
kubectl get pods -l app=deprecated-service --no-headers | awk '{print $1}' | xargs -r kubectl delete pod
# → pod "deprecated-service-67f9b8c" deleted
```

---

## Troubleshooting: типичные ошибки команд и их устранение

### Ошибка 1: `kubectl exec` — `unable to upgrade connection: container not found`

*   **Причина:** Целевой контейнер еще не перешел в фазу `Running` (находится в `ContainerCreating`, `PodInitializing`), либо упал и находится в состоянии ожидания перезапуска `CrashLoopBackOff`.
*   **Диагностика:**
    ```bash
    kubectl get pod web-app -o jsonpath='{.status.containerStatuses[*].state}'
    # → {"waiting":{"message":"back-off 40s restarting failed container","reason":"CrashLoopBackOff"}}
    ```
*   **Решение:** Анализируйте причины падения через `kubectl logs web-app -c <container> --previous` и `kubectl describe pod web-app`. Не вызывайте `exec`, пока контейнер не перейдет в статус `Running`.

---

### Ошибка 2: `kubectl exec` — `OCI runtime exec failed: exec: "sh": executable file not found in $PATH`

*   **Причина:** В образе отсутствует командный интерпретатор (`sh`, `bash`). Характерно для легковесных образов `distroless`, `scratch` или минималистичных сборок на базе Go/Rust.
*   **Диагностика:**
    ```bash
    kubectl exec -it web-app -- /bin/sh
    # → OCI runtime exec failed: exec failed: unable to start container process: exec: "/bin/sh": stat /bin/sh: no such file or directory: unknown
    ```
*   **Решение:** Используйте эфемерные контейнеры (Ephemeral Containers), подключающиеся к пространствам имен целевого пода:
    ```bash
    kubectl debug -it web-app --image=busybox:1.36 --target=web-app
    # → [Успешный вход в терминал отладочного контейнера]
    ```

---

### Ошибка 3: `kubectl exec / logs` — `Error from server (Forbidden): pods "..." is forbidden`

*   **Причина:** У субъекта (пользователя или ServiceAccount) отсутствуют RBAC-права на соответствующие субресурсы `pods/exec` или `pods/log`.
*   **Диагностика:**
    ```bash
    kubectl auth can-i create pods/exec -n default
    # → no
    ```
*   **Решение:** Настройте соответствующий `Role` / `ClusterRole`:
    ```yaml
    apiVersion: rbac.authorization.k8s.io/v1
    kind: Role
    metadata:
      namespace: default
      name: pod-debugger
    rules:
    - apiGroups: [""]
      resources: ["pods", "pods/log", "pods/exec"]
      verbs: ["get", "list", "create"]
    ```

---

### Ошибка 4: `kubectl exec / logs` — `Error from server: dial tcp <node-ip>:10250: connect: connection refused / no route to host`

*   **Причина:** Сбой сетевой связности между нодой Control-Plane (где запущен `kube-apiserver`) и портом `10250` Kubelet на рабочем узле. Частые источники проблемы: падение процесса `kubelet`, закрытый сетевой экран (iptables, firewalld, ufw), некорректный адрес узла в поле `InternalIP`.
*   **Диагностика:**
    1.  Проверьте доступность порта с хоста `kube-apiserver`:
        ```bash
        nc -zvw 3 192.168.10.15 10250
        # → nc: connect to 192.168.10.15 port 10250 (tcp) failed: Connection refused
        ```
    2.  Проверьте статус службы Kubelet на проблемном рабочем узле:
        ```bash
        ssh root@worker-node-01 "systemctl status kubelet"
        # → Active: failed (Result: exit-code)
        ```
*   **Решение:** Восстановите работу Kubelet (`systemctl restart kubelet`) и настройте правила межсетевого экрана, открыв входящий порт TCP `10250` от control-plane узлов.

---

### Ошибка 5: `kubectl cp` — `tar: removing leading '/' from member names`

*   **Причина:** Утилита `tar` внутри контейнера автоматически нормализует пути, вырезая ведущий слэш `/` из соображений безопасности. При неправильном указании путей файл может быть скопирован не в целевую папку, либо процесс завершается аварией, если `tar` в образе не поддерживает ключи стриминга.
*   **Решение:**
    *   При копировании из контейнера используйте абсолютные пути, но создавайте директорию назначения заранее:
        ```bash
        mkdir -p ./logs && kubectl cp web-app:/var/log/app.log ./logs/app.log
        ```
    *   Если контейнер не содержит `tar`, используйте stdin-пайп:
        ```bash
        kubectl exec web-app -- cat /var/log/app.log > ./app.log
        ```

---

### Ошибка 6: `kubectl port-forward` — `Unable to listen on port: address already in use`

*   **Причина:** Локальный порт на рабочей машине администратора уже занят другим локальным приложением или предыдущей сессией kubectl.
*   **Диагностика:**
    ```bash
    # Поиск процесса, удерживающего локальный порт 8080 (Linux/macOS)
    lsof -i :8080
    # → COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
    # → nginx    1420 root    6u  IPv4  31049      0t0  TCP *:http-alt (LISTEN)
    ```
*   **Решение:** Освободите порт (`kill -9 <PID>`) либо укажите альтернативный локальный свободный порт при вызове команды:
    ```bash
    kubectl port-forward pod/web-app 18080:80
    # → Forwarding from 127.0.0.1:18080 -> 80
    ```

---

### Ошибка 7: `kubectl wait` — `error: timed out waiting for the condition on pods`

*   **Причина:** Pod не смог перейти в целевое состояние в течение заданного флагом `--timeout` интервала времени (например, из-за долгого скачивания большого образа, задержек инициализации или сбоя Readiness-пробы).
*   **Диагностика:**
    ```bash
    kubectl get pod web-app -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{" (Reason: "}{.reason}{")\n"}{end}'
    # → PodScheduled=True (Reason: )
    # → Initialized=True (Reason: )
    # → ContainersReady=False (Reason: ContainersNotReady)
    # → Ready=False (Reason: ContainersNotReady)
    ```
*   **Решение:** Увеличьте лимит времени ожидания (`--timeout=300s`) или устраните причину сбоя проб приложения.

---

### Ошибка 8: `kubectl apply` — `ApplyConflict` (HTTP 409) при Server-Side Apply

*   **Причина:** Другой контроллер или пользователь уже объявил права владения изменяемыми полями (`metadata.managedFields`).
*   **Диагностика:**
    ```bash
    kubectl apply -f pod.yaml --server-side --field-manager=my-deployer
    # → error: Apply failed with 1 conflict: conflict with "helm" using v1: .spec.containers[name="web-app"].image
    ```
*   **Решение:** Если изменение легитимно и необходимо принудительно перехватить права владения полями, используйте флаг `--force-conflicts`:
    ```bash
    kubectl apply -f pod.yaml --server-side --field-manager=my-deployer --force-conflicts
    # → pod/web-app serverside-applied
    ```

---

### Ошибка 9: Pod бесконечно находится в статусе `Terminating`

*   **Причина:** 
    1. Процесс в контейнере игнорирует сигнал `SIGTERM`, а хук `preStop` завис.
    2. CSI-драйвер или операционная система узла не могут отмонтировать сетевой том (NFS/Ceph/iSCSI) из-за зависших файловых дескрипторов.
    3. На объекте Pod выставлен `finalizer`, логика обработки которого не завершена.
*   **Диагностика:**
    ```bash
    kubectl describe pod stuck-pod | grep -E "Finalizers|Grace Period"
    # → Finalizers:    [custom.storage.io/cleanup]
    # → Termination Grace Period: 30s
    ```
*   **Решение:**
    1.  Проверьте системные логи узла на предмет блокировок ввода-вывода (I/O hang): `dmesg -T | grep -i hung`.
    2.  Если том безопасно отмонтирован вручную, удалите финализатор:
        ```bash
        kubectl patch pod stuck-pod -p '{"metadata":{"finalizers":null}}'
        ```
    3.  В экстренной ситуации форсируйте удаление: `kubectl delete pod stuck-pod --force --grace-period=0`.

---

### Ошибка 10: `kubectl logs` — `a container name must be specified for pod`

*   **Причина:** В Pod запущено более одного контейнера, и `kubectl` не может определить, вывод какого именно контейнера запрошен.
*   **Решение:** Явно укажите имя контейнера через аргумент `-c` либо включите агрегацию всех потоков вывода через флаг `--all-containers`:
    ```bash
    # Для конкретного контейнера
    kubectl logs multi-pod -c app
    
    # Для всех контейнеров одновременно
    kubectl logs multi-pod --all-containers
    ```

---

## Best Practices

1.  **Применяйте Server-Side Apply по умолчанию:** Используйте `kubectl apply --server-side` в конвейерах CI/CD и GitOps-операциях. Это исключает проблемы с переполнением аннотаций метаданных и гарантирует явное разрешение конфликтов владения полями (`managedFields`).
2.  **Всегда задавайте таймауты в скриптах:** Команды ожидания (`kubectl wait`) и управления развертыванием (`kubectl rollout status`) в сценариях автоматизации обязаны содержать флаг `--timeout` во избежание бесконечного зависания CI/CD пайплайнов.
3.  **Не используйте `kubectl exec` для регулярных рутинных задач:** Ручные операции внутри контейнеров нарушают концепцию неизменяемой инфраструктуры (Immutable Infrastructure). Изменения должны вноситься через манифесты, ConfigMap и пересборку образов.
4.  **Изолируйте сетевую отладку:** Вместо добавления утилит `curl`, `netcat`, `tcpdump` в продуктовые контейнеры, используйте команду `kubectl debug` с профилем сети и образом `nicolaka/netshoot`. Это сохраняет минимальный размер продуктового контейнера и уменьшает вектор атак.
5.  **Фильтруйте вывод на стороне API-сервера:** Отдавайте предпочтение `--field-selector` и селекторам меток `-l` вместо локальной фильтрации через `grep` в больших кластерах. Это снижает объем передаваемого трафика и потребление памяти `kube-apiserver`.
6.  **Сохраняйте состояние аварийных контейнеров:** При расследовании инцидентов всегда извлекайте логи предыдущего запуска через `kubectl logs --previous` и статус завершения (`lastState.terminated`) до пересоздания объекта контроллером.
7.  **Осторожно используйте принудительное удаление (`--force`):** Принудительное удаление подов баз данных и брокеров сообщений (Kafka, PostgreSQL, RabbitMQ) без верификации состояния узла может привести к одновременному запуску двух активных реплик (Split-Brain) и необратимой порче данных на диске.
8.  **Учитывайте ограничения `kubectl port-forward`:** Помните, что `port-forward` туннелирует только TCP-соединения через единичный поток Kubelet. Не используйте его для нагрузочного тестирования или передачи UDP-трафика.
9.  **Проверяйте права через `auth can-i` заранее:** В скриптах развертывания и инициализации проверяйте полномочия используемого ServiceAccount через `kubectl auth can-i` перед выполнением критических шагов.
10. **Контролируйте PID 1 при использовании `kubectl attach`:** Не завершайте сессию `attach` сочетанием клавиш Ctrl+C без предварительного отключения передачи ввода (ключ `--stdin=false`), если контейнер сконфигурирован на перехват управляющих сигналов.

---

## Связанные темы

*   [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — детальная теория фаз, условий (Conditions) и процесса graceful termination.
*   [Перезапуск Pod в Kubernetes](./pod_restarts.md) — анализ причин падений, состояний `CrashLoopBackOff` и логики backoff-интервалов.
*   [Пробы в Kubernetes (Probes)](../probes.md) — проектирование и диагностика проб Liveness, Readiness и Startup.
*   [Эфемерные контейнеры](./ephemeral_containers.md) — расширенные сценарии интерактивной отладки через `kubectl debug`.
*   [Архитектура Kubelet](../../Concepts/kubelet.md) — устройство локального агента ноды, обработка субресурсов и потоков ввода-вывода.
*   [Container Runtime](../../Concepts/container_runtime.md) — устройство CRI, containerd, CRI-O и низкоуровневая диагностика через `crictl`.
*   [Метки, аннотации и селекторы узлов](./pod_labels_annotations_node_selection.md) — паттерны таргетирования и фильтрации рабочих нагрузок.
*   [RBAC в Kubernetes](../../Security/rbac/roles.md) — управление ролями, сервисными учетными записями и матрицей доступа к субресурсам.
*   [Мониторинг и логирование в Kubernetes](../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — централизованный сбор метрик и логов с рабочих узлов и подов.
*   [Общий траблшутинг Kubernetes](../../Troubleshooting/troubleshooting_overview.md) — глобальная методология локализации инцидентов в кластере.
