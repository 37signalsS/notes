# Пробы в Kubernetes (Probes)

**Актуально для:** Kubernetes 1.30–1.35+

## Определения

* **Пробы (Probes / Зонды)** — диагностические механизмы локального агента узла `kubelet`, выполняющие периодические проверки состояния и работоспособности контейнеров на основе сетевых вызовов или локального выполнения команд.
* **`livenessProbe` (Проба живучести)** — зонд, определяющий жизнеспособность процесса внутри контейнера. При переходе в состояние сбоя (`Failure`) `kubelet` принудительно завершает контейнер согласно политике `restartPolicy` (отправка `SIGTERM`, затем `SIGKILL` по истечении тайм-аута). Служит для вывода из состояния дедлока, зависания потоков или утечки памяти, когда процесс формально существует, но не способен выполнять задачи.
* **`readinessProbe` (Проба готовности)** — зонд, определяющий готовность контейнера принимать входящий пользовательский трафик. При сбое контейнер **не перезапускается**, но контроллеры `Endpoints` и `EndpointSlice` исключают IP-адрес пода из списков балансировки всех ассоциированных объектов `Service`. Применяется при прогреве кэшей, миграции локальных схем, перегрузке или временной потере внутренних ресурсов.
* **`startupProbe` (Проба запуска)** — специализированный зонд начальной инициализации приложения. При наличии `startupProbe` выполнение `livenessProbe` и `readinessProbe` полностью блокируется до первого успешного завершения `startupProbe`. Предотвращает ложное срабатывание `livenessProbe` и цикличные перезапуски (`CrashLoopBackOff`) тяжело стартующих приложений.
* **`kube-prober` (Prober Manager)** — внутренний компонент `kubelet`, управляющий пулом воркеров для асинхронного выполнения проверок каждого контейнера и передающий результаты в `Status Manager`.
* **Readiness Gates (Врата готовности)** — расширение спецификации Pod (`spec.readinessGates`), позволяющее внешним сетевым контроллерам (Ingress-контроллеры, Service Mesh, аппаратные L4/L7-балансировщики) удерживать условие `Ready: False` независимо от внутренних контейнерных зондов до завершения сетевой конвергенции.
* **Статусы результатов пробы**:
  * `Success` — проверка успешно пройдена;
  * `Failure` — проверка завершилась ошибкой или нарушен лимит тайм-аута;
  * `Unknown` — `kubelet` не смог выполнить пробу (ошибка рантайма CRI, зависание сокета рантайма, сбой узловых подсистем).
* **Начальные состояния проб:** До первого успешного ответа зонды `liveness` и `readiness` находятся в состоянии `Failure` (что гарантирует немедленное исключение пода из балансировки до подтверждения готовности), а `startupProbe` инициализируется в состоянии `Unknown`.

---

## Базовые концепции и архитектура

### 1. Архитектура исполнения проверок в kubelet

В архитектуре Kubernetes проверки здоровья исполняются децентрализованно — непосредственно агентом `kubelet` на том узле, где запущен под, без участия `kube-apiserver` в цикле опроса:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Worker Node (Kubelet Process)                                          │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ kube-prober (Worker Pool)                                    │     │
│   │                                                              │     │
│   │  ┌────────────────┐   ┌────────────────┐   ┌──────────────┐  │     │
│   │  │ startupWorker  │   │ livenessWorker │   │readinessWork.│  │     │
│   │  └───────┬────────┘   └───────┬────────┘   └──────┬───────┘  │     │
│   └──────────┼────────────────────┼───────────────────┼──────────┘     │
│              │                    │                   │                │
│       CRI / Network        CRI / Network        CRI / Network          │
│              ▼                    ▼                   ▼                │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ Pod Sandbox (Container)                                      │     │
│   │ - HTTP /livez, /readyz                                       │     │
│   │ - TCP Socket                                                 │     │
│   │ - exec CRI ExecSync                                          │     │
│   │ - gRPC Health Check                                          │     │
│   └──────────────────────────────────────────────────────────────┘     │
│              │                                        │                │
│   Failure (Threshold reached)              Failure (Threshold reached) │
│              ▼                                        ▼                │
│   Container Kill & Restart                 Kubelet Status Manager      │
│   (SIGTERM -> SIGKILL)                                │                │
└───────────────────────────────────────────────────────┼────────────────┘
                                                        ▼
                                             Kube-API-Server (Pod Status)
                                                        │
                                                        ▼
                                             EndpointSlice Controller
                                             (Исключение IP из Service)
```

1. **Изоляция исполнения:** Для каждого зонда каждого контейнера `kubelet` создает независимый поток/воркер. Проверки выполняются периодически с интервалом `periodSeconds`.
2. **Маршрутизация сетевых запросов:** Запросы `httpGet` и `tcpSocket` отправляются `kubelet` непосредственно на сетевой интерфейс пода (Pod IP). `kubelet` выступает клиентом соединения.
3. **Обработка сбоя `livenessProbe`:**
   * При фиксации `Failure` подряд в количестве `failureThreshold` агент `kubelet` инициирует процедуру остановки контейнера: выполняется хук `preStop` (если задан), посылается сигнал `SIGTERM`, выжидается период `terminationGracePeriodSeconds`, после чего процесс уничтожается по `SIGKILL`.
   * Контейнер перезапускается в соответствии с `spec.restartPolicy` (`Always`, `OnFailure`).
4. **Обработка сбоя `readinessProbe`:**
   * При превышении `failureThreshold` агент `kubelet` мутирует локальный статус пода, выставляя условие `Ready: False` и `ContainersReady: False`.
   * Изменение транслируется в `kube-apiserver`, где `EndpointSlice Controller` и `Endpoints Controller` мгновенно удаляют IP-адрес пода из списков активных точек назначения.
   * Контейнер продолжает функционировать, сохраняя память, подключения и файлы.

### 2. Механизмы проверок

Kubernetes поддерживает четыре механизма зондирования:

| Механизм | Синтаксис спецификации | Критерий успеха | Специфика реализации и архитектурные ограничения |
| :--- | :--- | :--- | :--- |
| **`httpGet`** | `path`, `port`, `host`, `scheme`, `httpHeaders` | HTTP-код `200 <= status < 400` | Выполняется сетевой запрос. Редиректы (3xx) считаются успехом. Поддерживает имена портов (`port: http`). По умолчанию сертификаты TLS при `scheme: HTTPS` **не проверяются** (`InsecureSkipVerify: true`). Поле `host` по умолчанию равно IP пода (не рекомендуется указывать `localhost` во избежание провала на многосетевых узлах). |
| **`tcpSocket`** | `port`, `host` | Успешное завершение 3-way TCP handshake (SYN-ACK) | **Внимание:** Ядро Linux отвечает SYN-ACK сразу после вызова `listen()`, когда сокет помещен в очередь соединений (backlog), задолго до инициализации пулов потоков, соединений с БД или кэшей. Не отражает реальную готовность бизнес-логики. |
| **`exec`** | `command: [arg1, arg2]` | Код возврата процесса `0` | Выполняется внутри контейнера через вызов CRI `ExecSync`. Порождает процесс через `fork/exec`. **Накладные расходы:** регулярный вызов тяжелых утилит вызывает скачки CPU, контекстные переключения и исчерпание пула PID (`kernel.pid_max`). |
| **`grpc`** | `port`, `service` (опционально) | Статус ответа `SERVING` | Встроенный механизм (GA с v1.27). Реализует официальный gRPC Health Checking Protocol (`grpc.health.v1`). Не требует включения сторонних утилит (`grpc-health-probe`) в минималистичные образы. |

#### Тонкости механизмов:
* **HTTP/2 (h2c):** Поле `protocol: HTTP2` в `httpGet` (фича-гейт `HTTPProbeProtocol`) позволяет опрашивать сервисы, отдающие эндпоинты исключительно по HTTP/2 Cleartext без TLS. Если сервер не поддерживает h2c, проба стабильно завершается ошибкой.
* **Обработка ошибок выполнения `exec` (`ProbeErrorAsFailure`):** До стабилизации фичи `ProbeErrorAsFailure` (GA с v1.31) в случае, если указанный в пробе бинарный файл отсутствовал в контейнере (ошибка исполнения CRI, код выхода не получен), `kubelet` мог оставлять статус неопределенным без фиксации сбоя. В актуальных версиях любая системная ошибка запуска расценивается как `Failure`.
* **Тайм-аут `exec`-проб (`ExecProbeTimeout`):** Механизм тайм-аута (GA с v1.20) гарантирует принудительное уничтожение зависшей команды `exec` по истечении `timeoutSeconds`.

### 3. Параметры конфигурации и расчет временного окна

Каждая проба настраивается следующими директивами:

* **`initialDelaySeconds`** (по умолчанию `0`, минимум `0`): Время ожидания в секундах перед отправкой первой проверки после старта контейнера.
* **`periodSeconds`** (по умолчанию `10`, минимум `1`): Интервал между последовательными проверками.
* **`timeoutSeconds`** (по умолчанию `1`, минимум `1`): Предельное время ожидания ответа. При превышении проба считается неуспешной.
* **`failureThreshold`** (по умолчанию `3`, минимум `1`): Количество последовательных неудачных проверок, необходимое для признания сбоя.
* **`successThreshold`** (по умолчанию `1`, минимум `1`): Количество последовательных успешных проверок для перевода пробы из состояния сбоя в здоровое. **Ограничение ядра:** для `livenessProbe` и `startupProbe` значение **обязано** равняться `1` (валидатор API отклонит иное значение). Для `readinessProbe` допускается значение `> 1` (гистерезис для защиты от дребезга при нестабильной сети).
* **`terminationGracePeriodSeconds`** (опционально, GA с v1.28): Специфический тайм-аут изящного завершения контейнера, применяемый **только** при его остановке вследствие сбоя `livenessProbe`. Позволяет сократить время ожидания зависшего пода при обычной ротации, но выделить достаточно времени на генерацию heap dump при срабатывании liveness.

#### Математика окна живучести и старта

Суммарное время ($T_{\text{budget}}$), выделяемое приложению до момента первой инициации рестарта при старте:

$$T_{\text{startup}} = \text{initialDelaySeconds} + (\text{failureThreshold} - 1) \times \text{periodSeconds} + \text{timeoutSeconds}$$

> [!NOTE]
> Последняя проверка в цикле не ждет завершения полного интервала `periodSeconds` перед фиксацией отказа: при получении отказа на шаге `failureThreshold` действие (перезапуск или снятие с балансировки) инициируется немедленно после фиксации тайм-аута или кода ошибки.

### 4. Взаимодействие со смежными подсистемами ядра

* **Врата готовности (Readiness Gates):** Если в `spec.readinessGates` заданы внешние условия, под считается готовым (`Ready: True`) **только** тогда, когда все контейнеры пода готовы по своим `readinessProbe` **И** все внешние условия в `status.conditions` переведены управляющими контроллерами в статус `True`. Архитектурные детали см. в [Продвинутых темах Pod](./Pod/pod_advanced_topics.md#2-врата-готовности-readiness-gates).
* **Native Sidecar контейнеры (GA с v1.33):** Контейнеры в блоке `initContainers`, у которых задан параметр `restartPolicy: Always`, являются нативными сайдкарами. Основные контейнеры приложения не начнут запуск до тех пор, пока каждый sidecar-контейнер не пройдет проверку готовности (`readinessProbe` перейдет в `Success`). Подробнее см. в [Паттернах Sidecar](./Pod/pod_sidecar_patterns.md).
* **Горизонтальное авто масштабирование (HPA):** Поды, находящиеся в состоянии `Ready: False` (провалившие `readinessProbe`), временно исключаются из расчета средних метрик утилизации CPU/Memory в алгоритме `kube-controller-manager`, предотвращая искажение метрик во время масштабирования.

---

## Практические сценарии и конфигурация

### Сценарий 1: Высоконагруженный Web/API микросервис (Zero-Downtime Rolling Update)

Обеспечение нулевого времени простоя (Zero Downtime) при ротации подов в условиях плотного сетевого трафика на bare-metal инсталляциях:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway
  namespace: production
spec:
  replicas: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: api-gateway
  template:
    metadata:
      labels:
        app.kubernetes.io/name: api-gateway
    spec:
      containers:
      - name: gateway
        image: internal-registry.local/web/api-gateway:v2.4.1
        ports:
        - name: http-web
          containerPort: 8080
        lifecycle:
          preStop:
            exec:
              # Даем 10 секунд на удаление IP пода из iptables/IPVS/eBPF всех узлов до отправки SIGTERM
              command: ["/bin/sh", "-c", "sleep 10"]
        
        # Защита от долгой инициализации роутов и парсинга конфигов
        startupProbe:
          httpGet:
            path: /healthz/startup
            port: http-web
          failureThreshold: 15
          periodSeconds: 2
          timeoutSeconds: 2

        # Проверка дедлоков (только внутреннее состояние процесса)
        livenessProbe:
          httpGet:
            path: /healthz/liveness
            port: http-web
          periodSeconds: 10
          timeoutSeconds: 2
          failureThreshold: 3
          # Быстро освобождаем ресурсы, если процесс завис
          terminationGracePeriodSeconds: 15

        # Управление допуском трафика
        readinessProbe:
          httpGet:
            path: /healthz/readiness
            port: http-web
          periodSeconds: 5
          timeoutSeconds: 2
          failureThreshold: 2
          successThreshold: 2  # Гистерезис: возврат в трафик только после 2 стабильных успехов
```

### Сценарий 2: Java / Spring Boot с прогревом JVM

Для JVM-приложений с долгим холодным стартом и компиляцией JIT `startupProbe` предотвращает убийство контейнера, а раздельные эндпоинты Actuator исключают каскадные сбои:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  namespace: finance
spec:
  replicas: 3
  selector:
    matchLabels:
      app: billing-service
  template:
    metadata:
      labels:
        app: billing-service
    spec:
      containers:
      - name: spring-app
        image: internal-registry.local/finance/billing-service:3.3.0
        ports:
        - name: mgmt-http
          containerPort: 8081
        
        # Бюджет на запуск: 30 попыток * 5 сек = 150 секунд на старт JVM и инициализацию контекста
        startupProbe:
          httpGet:
            path: /actuator/health/liveness
            port: mgmt-http
          failureThreshold: 30
          periodSeconds: 5
          timeoutSeconds: 3

        livenessProbe:
          httpGet:
            path: /actuator/health/liveness
            port: mgmt-http
          periodSeconds: 15
          timeoutSeconds: 3
          failureThreshold: 3
          # Выделяем 60 секунд на сброс Heap Dump скриптом перед SIGKILL
          terminationGracePeriodSeconds: 60

        readinessProbe:
          httpGet:
            path: /actuator/health/readiness
            port: mgmt-http
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 3
```

### Сценарий 3: gRPC микросервис с нативной проверкой здоровья

Использование встроенного протокола проверки здоровья без сторонних бинарников (v1.27+ GA):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-auth-service
  namespace: core
spec:
  replicas: 2
  selector:
    matchLabels:
      app: user-auth
  template:
    metadata:
      labels:
        app: user-auth
    spec:
      containers:
      - name: auth-server
        image: internal-registry.local/core/auth-grpc:v1.12.0
        ports:
        - name: grpc-port
          containerPort: 50051
        
        startupProbe:
          grpc:
            port: 50051
            service: auth.v1.AuthService
          failureThreshold: 10
          periodSeconds: 3
          timeoutSeconds: 2

        livenessProbe:
          grpc:
            port: 50051
            service: auth.v1.AuthService
          periodSeconds: 10
          timeoutSeconds: 2

        readinessProbe:
          grpc:
            port: 50051
            service: auth.v1.AuthService
          periodSeconds: 5
          timeoutSeconds: 2
```

### Сценарий 4: База данных PostgreSQL (StatefulSet) с безопасным зондом

Использование легковесной проверки через локальный сокет UNIX без создания накладных расходов от сетевого парсинга:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-db
  namespace: data
spec:
  serviceName: postgres-headless
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgresql
        image: internal-registry.local/db/postgresql:16.4
        ports:
        - name: postgres
          containerPort: 5432
        
        startupProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - "pg_isready -h 127.0.0.1 -p 5432 -U postgres -q"
          initialDelaySeconds: 10
          failureThreshold: 30
          periodSeconds: 5
          timeoutSeconds: 2

        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - "pg_isready -h 127.0.0.1 -p 5432 -U postgres -q"
          periodSeconds: 15
          timeoutSeconds: 3
          failureThreshold: 3

        readinessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            # Проверяем не только готовность демона принимать сокет, но и отсутствие блокировки recovery
            - "psql -h 127.0.0.1 -U postgres -d postgres -tAc 'SELECT 1' | grep -q 1"
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 2
```

### Сценарий 5: Native Sidecar с порядковой синхронизацией старта

Вспомогательный контейнер (прокси или сервис авторизации) поднимается строго до основного контейнера:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-with-sidecar
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: app-with-sidecar
  template:
    metadata:
      labels:
        app: app-with-sidecar
    spec:
      initContainers:
      - name: local-proxy
        image: internal-registry.local/net/local-proxy:v1.0
        restartPolicy: Always  # Объявляет init-контейнер нативным сайдкаром (v1.29+)
        ports:
        - name: proxy-port
          containerPort: 9001
        startupProbe:
          tcpSocket:
            port: 9001
          failureThreshold: 10
          periodSeconds: 1
        readinessProbe:
          httpGet:
            path: /proxy/ready
            port: proxy-port
          periodSeconds: 2

      containers:
      - name: main-business-logic
        # Запустится ТОЛЬКО после того, как local-proxy перейдет в статус Ready: True
        image: internal-registry.local/apps/backend:v1.0
        ports:
        - name: app-port
          containerPort: 8080
        readinessProbe:
          httpGet:
            path: /ready
            port: app-port
          periodSeconds: 5
```

---

## Операции и команды

Сводка команд системного инженера для оперативного извлечения конфигураций, инспекции состояния и проверки сетевых проб:

```bash
# 1. Сводное извлечение параметров всех проб по всем контейнерам пода
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{range .spec.containers[*]}{"Container: "}{.name}{"\n  Startup:   "}{.startupProbe}{"\n  Liveness:  "}{.livenessProbe}{"\n  Readiness: "}{.readinessProbe}{"\n"}{end}'
# → Container: gateway
# →   Startup:   {"failureThreshold":15,"httpGet":{"path":"/healthz/startup","port":"http-web","scheme":"HTTP"},"periodSeconds":2,"timeoutSeconds":2}
# →   Liveness:  {"failureThreshold":3,"httpGet":{"path":"/healthz/liveness","port":"http-web","scheme":"HTTP"},"periodSeconds":10,"terminationGracePeriodSeconds":15,"timeoutSeconds":2}
# →   Readiness: {"failureThreshold":2,"httpGet":{"path":"/healthz/readiness","port":"http-web","scheme":"HTTP"},"periodSeconds":5,"successThreshold":2,"timeoutSeconds":2}

# 2. Быстрая проверка причин завершения контейнера (Termination Details & Exit Code)
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{range .status.containerStatuses[*]}{"Container: "}{.name}{"\n  State:     "}{.state}{"\n  LastState: "}{.lastState.terminated}{"\n  Restarts:  "}{.restartCount}{"\n"}{end}'
# → Container: gateway
# →   State:     {"running":{"startedAt":"2026-10-17T20:10:00Z"}}
# →   LastState: {"exitCode":137,"finishedAt":"2026-10-17T20:09:50Z","reason":"Error","startedAt":"2026-10-17T19:50:00Z"}
# →   Restarts:  1

# 3. Фильтрация событий ядра кластера по сбоям зондов
kubectl get events -n <namespace> --field-selector involvedObject.name=<pod-name> --sort-by='.metadata.creationTimestamp' | grep -iE 'Unhealthy|Killing|ProbeWarning'
# → 2m   Warning   Unhealthy   pod/api-gateway-7b9   Readiness probe failed: HTTP probe failed with statuscode: 503
# → 1m   Warning   Unhealthy   pod/api-gateway-7b9   Liveness probe failed: Get "http://10.244.2.45:8080/healthz/liveness": context deadline exceeded (Client.Timeout exceeded)
# → 1m   Normal    Killing     pod/api-gateway-7b9   Container gateway failed liveness probe, will be restarted

# 4. Проверка фактического присутствия пода в сетевых эндпоинтах сервиса
kubectl get endpointslice -n <namespace> -l kubernetes.io/service-name=<service-name> -o wide
# → NAME                 ADDRESSTYPE   PORTS   ENDPOINTS                            AGE
# → api-service-8fd9x    IPv4          8080    10.244.2.45 (Ready: false), 10.244.3.12 (Ready: true)   12d

# 5. Ручная валидация HTTP-ответа пробы изнутри пода с отображением HTTP-кода и времени
kubectl exec -it <pod-name> -n <namespace> -c <container-name> -- curl -s -o /dev/null -w "HTTP_CODE: %{http_code} | TOTAL_TIME: %{time_total}s\n" http://127.0.0.1:8080/healthz/readiness
# → HTTP_CODE: 200 | TOTAL_TIME: 0.004s

# 6. Валидация gRPC-сервиса через эфемерный отладочный контейнер (без curl/grpc_health_probe в образе)
kubectl debug -it <pod-name> -n <namespace> --image=internal-registry.local/tools/grpc-health-probe:v0.4.28 --target=<container-name> -- /ko-app/grpc-health-probe -addr=127.0.0.1:50051 -service=auth.v1.AuthService
# → status: SERVING

# 7. Чтение системного журнала агента Kubelet на проблемном worker-узле (фильтрация работы prober)
journalctl -u kubelet -n 100 --no-pager | grep -iE "probe|unhealthy|failed liveness"
# → Oct 17 21:00:15 node-02 kubelet[1842]: I1017 21:00:15.112 prober.go:124] "Probe failed" probeType="liveness" pod="production/api-gateway-7b9" error="command timed out"
```

---

<a id="диагностика-и-устранение-неисправностей"></a>
## Диагностика и устранение неполадок

### Матрица симптомов и первопричин сбоев

| Симптом | Поведение системы | Первопричина | Метод локализации и решение |
| :--- | :--- | :--- | :--- |
| **`CrashLoopBackOff` сразу после развертывания** | Под непрерывно перезапускается; счетчик `Restarts` растет | Отсутствует `startupProbe`. `livenessProbe` падает во время медленного старта приложения (JIT, прогрев кэшей). | Проверить `kubectl describe pod` на наличие `Liveness probe failed`. Настроить `startupProbe` с достаточным `failureThreshold * periodSeconds`. |
| **Под в фазе `Running`, но `READY: 0/1`** | Трафик не поступает на под; отсутствует в `EndpointSlice` | `readinessProbe` возвращает ошибку (например, HTTP 500/503) или не отвечает в пределах `timeoutSeconds`. | Выполнить `kubectl exec -- curl -v http://localhost:<port>/<path>`. Проверить доступность внутренних зависимостей сервиса. |
| **Спорадические рестарты при высокой нагрузке** | Рестарты происходят при всплесках трафика; статус `LastState: terminated exitCode: 137` | CPU Throttling из-за исчерпания CFS Quota или блокировка Event Loop приложения. Проба не успевает ответить за `timeoutSeconds`. | Проверить метрику `container_cpu_cfs_throttled_periods_total`. Увеличить `timeoutSeconds` или поднять CPU Limits / отключить лимиты CPU. |
| **Отказ пробы с результатом `Unknown`** | Статус пода не обновляется; в событиях ошибки взаимодействия с рантаймом | Зависание демона CRI (containerd/CRI-O), исчерпание дескрипторов узла или перегрузка I/O диска узла. | Проверить статус рантайма: `systemctl status containerd`. Проверить системные вызовы `crictl ps` и нагрузку I/O (`iostat -x 1`). |
| **Рестарт по `livenessProbe` во время завершения пода** | Под долго висит в `Terminating`, рестартует и падает по `CrashLoopBackOff` | `kubelet` продолжает выполнять `livenessProbe` в процессе Terminating, а приложение уже закрыло слушающий порт при получении `SIGTERM`. | Настроить приложение так, чтобы при получении `SIGTERM` закрывался только порт `readiness`, а эндпоинт `liveness` продолжал отвечать `200 OK` до выхода. |

---

<a id="антипаттерны"></a>
### Антипаттерны конфигурации (Production SRE Anti-patterns)

#### 1. Проверка внешних зависимостей в `livenessProbe` (Каскадный коллапс кластера)
* **Антипаттерн:** Включение проверок доступности базы данных, внешнего кэша Redis или брокера сообщений Kafka в эндпоинт `livenessProbe`.
* **Механика катастрофы:** При временной недоступности или кратковременном сетевом разделении (Network Partition) между подами и БД `livenessProbe` одновременно падает на **всех** подах сервиса во всем кластере. `kubelet` начинает синхронно перезапускать сотни подов. При одновременном рестарте поды создают лавинообразную волну подключений («громовое стадо» / Thundering Herd) к только что восстановившейся БД, снова выводя её из строя.
* **Правило:** `livenessProbe` обязана проверять **исключительно** внутреннее состояние процесса (отсутствие deadlock, ответ внутреннего пула потоков). Зависимости проверяются **только** в `readinessProbe`.

#### 2. Дублирование единого пути проверки (`/health` для liveness и readiness)
* **Антипаттерн:** Назначение одного и того же эндпоинта (например, `/healthz`) одновременно в `livenessProbe` и `readinessProbe`.
* **Механика катастрофы:** Если приложение испытывает пиковую нагрузку или пулы очередей заполнены, оно должно временно исключиться из балансировки (что делает `readinessProbe`), чтобы штатно дообработать накопленные запросы. Если в этот момент срабатывает `livenessProbe` на том же эндпоинте, процесс принудительно убивается, обрывая тысячи активных клиентских TCP-сессий и порождая HTTP 502/504 на Ingress.
* **Правило:** Использовать строго изолированные эндпоинты: `/healthz/live` (всегда возвращает 200, если процесс жив) и `/healthz/ready` (возвращает 503 при насыщении пулов или прогреве).

#### 3. «Спираль смерти» (Death Spiral) при авто масштабировании
* **Антипаттерн:** Реализация проверки `readinessProbe` через выполнение некэшируемых «тяжелых» запросов к базе данных (например, `SELECT count(*) FROM users` или `ping` с открытием новой TCP-сессии).
* **Механика катастрофы:**
  1. При росте клиентского трафика HPA создает новые поды.
  2. Каждая новая реплика начинает опрашивать БД с интервалом `periodSeconds: 2`.
  3. Соединения с БД исчерпываются (`max_connections reached`), БД замедляет ответы.
  4. Проверки `readiness` начинают падать по тайм-ауту не только на новых, но и на старых подах.
  5. Поды массово выпадают из сервиса, оставшиеся реплики принимают еще больше трафика и падают следом.
* **Правило:** Проверять соединения через пул (Connection Pool Health) в фоновом потоке приложения с кэшированием статуса на 3–5 секунд, не создавая транзакций на каждый запрос пробы.

#### 4. Использование тяжелых скриптов в `exec`-пробах
* **Антипаттерн:** Использование `exec: command: ["/bin/bash", "-c", "curl ... | jq ..."]` с интервалом в 2–3 секунды на высокоплотных нодах.
* **Механика катастрофы:** Запуск подпроцесса через CRI требует создания структур в ядре Linux, выделения PID и загрузки библиотек. При размещении 100 контейнеров на узле с такими пробами узел генерирует сотни процессов `fork` в секунду, вызывая деградацию подсистемы планирования ядра (`kswapd`, переключение контекстов) и исчерпание лимита процессов (`PID starvation`).

---

### Пошаговый алгоритм локализации сбоя (Runbook)

```
Шаг 1: Чтение системных событий пода
  └─ $ kubectl describe pod <pod-name> -n <ns>
       ├─ Есть событие "Killing"? → Сбой livenessProbe (проверить LastState и логи перед смертью)
       ├─ Есть событие "Unhealthy"? → Сбой readinessProbe или startupProbe
       └─ Событий нет? → Проблема не в пробах (проверить OOMKilled, Evicted, Node Pressure)

Шаг 2: Проверка логов предыдущего запуска (Crash Forensics)
  └─ $ kubectl logs <pod-name> -n <ns> --previous --tail=100
       ├─ Поиск паники приложения, OutOfMemoryError, фатальных исключений
       └─ Проверка момента поступления сигнала SIGTERM/SIGKILL

Шаг 3: Проверка доступности портов и адресов
  └─ $ kubectl get pod <pod-name> -n <ns> -o jsonpath='{.status.podIP}'
  └─ $ kubectl exec -it <pod-name> -n <ns> -- netstat -tlpn (или ss -tlpn)
       └─ Убедиться, что процесс слушает именно тот порт и интерфейс (0.0.0.0, а не 127.0.0.1 при опросе по Pod IP)

Шаг 4: Анализ системного троттлинга CPU (CFS Quota)
  └─ $ kubectl top pod <pod-name> -n <ns>
  └─ Анализ метрики container_cpu_cfs_throttled_periods_total в Prometheus
       └─ Если троттлинг > 20%, пробы зависают из-за нехватки процессорного кванта
```

#### Экстренная стабилизация при аварии (Hotfix в Production)

Если некорректно настроенная `livenessProbe` циклически уничтожает критичный сервис при инциденте, системный администратор может временно отключить зонд без полной остановки пода:

```bash
# 1. Сохранение исходного манифеста
kubectl get deployment <deploy-name> -n <ns> -o yaml > deploy-backup.yaml

# 2. Удаление блока livenessProbe на лету через JSON Patch (инициирует ротацию с отключенной пробой)
kubectl patch deployment <deploy-name> -n <ns> --type='json' -p='[{"op": "remove", "path": "/spec/template/spec/containers/0/livenessProbe"}]'

# 3. После стабилизации ситуации и выкатки фикса приложения вернуть пробу
kubectl apply -f deploy-backup.yaml
```

---

## Лучшие практики

### Чек-лист проектирования проб для SRE и DevOps

1. **Изоляция ответственности проверок:**
   * `startupProbe`: Защита от долгой загрузки (чтение больших файлов, warmup JIT, прогрев кэшей).
   * `livenessProbe`: Детектирование внутреннего тупика (Deadlock, утечка потоков, блокировка Event Loop). Никаких проверок баз данных и внешних API!
   * `readinessProbe`: Проверка готовности обслуживать клиентов (прогреты кэши, установлены соединения к внутренним шинам, нет переполнения локальных очередей).
2. **Баланс интервалов и тайм-аутов:**
   * Правило: `timeoutSeconds` всегда должен быть строго меньше `periodSeconds`. Рекомендуемое соотношение: `timeoutSeconds <= 0.5 * periodSeconds`.
   * Для предотвращения ложных срабатываний при кратковременных нагрузках устанавливайте `failureThreshold` не менее `3`.
3. **HTTP вместо TCP:**
   * Избегайте использования `tcpSocket` для проверки HTTP/REST/gRPC приложений. TCP-сокет рапортует об успехе на уровне ядра до инициализации прикладных фреймворков.
4. **Связка с Graceful Shutdown и сетевыми задержками:**
   * Во время ротации подов удаление IP из iptables/IPVS на узлах кластера происходит с задержкой в 1–5 секунд.
   * Обязательно используйте хук `preStop: exec: command: ["/bin/sh", "-c", "sleep 10"]`, чтобы под продолжал отвечать на остаточные сетевые запросы до фактической отправки `SIGTERM`.
5. **Использование именованных портов:**
   * Задавайте `port: http-web` вместо явного числа `8080`. Это предотвращает рассинхронизацию манифестов при изменении конфигурации порта в контейнере.
6. **Выделенные пулы и изоляция памяти:**
   * Эндпоинты проверок здоровья должны выполняться в отдельных изолированных легковесных пулах или выделенных корутинах, чтобы исчерпание пула клиентских рабочих потоков не блокировало ответ на пробу.

---

### Мониторинг и алертинг (SRE Observability)

Зонды исполняются демоном `kubelet`, поэтому сбор телеметрии ведется напрямую с порта `kubelet:10250` по пути `/metrics/probes`. Метрики не зависят от `kube-state-metrics`.

#### Ключевые метрики процесса kube-prober:

| Метрика | Тип | Лейблы | Назначение |
| :--- | :--- | :--- | :--- |
| `prober_probe_total` | Counter | `container`, `namespace`, `pod`, `probe_type`, `result` | Общее количество выполненных проверок. Значение `result` может принимать значения `success`, `failure`, `unknown`. |
| `prober_probe_duration_seconds` | Histogram | `container`, `namespace`, `pod`, `probe_type` | Время выполнения проверки в секундах. Позволяет выявлять деградацию до отказа. |

#### Правила алертинга Prometheus (Alertmanager Rules):

```yaml
groups:
- name: kubernetes-probes-alerts
  rules:
  # Частые отказы readinessProbe — деградация сервиса и исключение из балансировки
  - alert: KubernetesContainerReadinessFailing
    expr: |
      increase(prober_probe_total{probe_type="readiness", result="failure"}[5m]) > 10
    for: 3m
    labels:
      severity: warning
      tier: platform
    annotations:
      summary: "Контейнер {{ $labels.container }} в поде {{ $labels.namespace }}/{{ $labels.pod }} проваливает readinessProbe"
      description: "За последние 5 минут зафиксировано {{ $value }} сбоев готовности. Под выпадает из балансировщика Service."

  # Отказы livenessProbe — угроза циклических аварийных перезапусков
  - alert: KubernetesContainerLivenessFailing
    expr: |
      increase(prober_probe_total{probe_type="liveness", result="failure"}[5m]) > 5
    for: 2m
    labels:
      severity: critical
      tier: platform
    annotations:
      summary: "Критический сбой livenessProbe: {{ $labels.namespace }}/{{ $labels.pod }} ({{ $labels.container }})"
      description: "Контейнер систематически проваливает проверки жизнеспособности и будет принудительно перезапущен Kubelet."

  # Аномальная латентность ответов проб (предвестник деградации)
  - alert: KubernetesProbeDurationHigh
    expr: |
      histogram_quantile(0.95, sum(rate(prober_probe_duration_seconds_bucket[5m])) by (le, namespace, pod, probe_type)) > 2
    for: 5m
    labels:
      severity: warning
      tier: platform
    annotations:
      summary: "Высокая латентность {{ $labels.probe_type }}-пробы на поде {{ $labels.namespace }}/{{ $labels.pod }}"
      description: "95-й перцентиль времени ответа пробы превышает 2 секунды (p95 = {{ $value }}s). Риск ложного срабатывания таймаута."
```

---

## Дополнительная информация

* **[Жизненный цикл и состояния Pod](./Pod/pod_lifecycle_and_state.md)** — фазы пода, хуки жизненного цикла (`postStart`, `preStop`) и порядок остановки.
* **[Продвинутые темы Pod](./Pod/pod_advanced_topics.md)** — архитектура `Readiness Gates`, `Scheduling Gates` и мутируемые поля спецификации.
* **[Паттерны Sidecar в Kubernetes](./Pod/pod_sidecar_patterns.md)** — нативные sidecar-контейнеры (`restartPolicy: Always`), координация старта и завершения.
* **[Перезапуск Pod в Kubernetes](./Pod/pod_restarts.md)** — детальный разбор механики перезапусков, `restartPolicy` и кодов возврата процессов.
* **[Управление жизненным циклом Deployment](./Deployment/lifecycle_management.md)** — математика ротации реплик `maxSurge`/`maxUnavailable` и бесшовные релизы.
* **[Обзор сервисов и управление эндпоинтами](../Networking/Service/service_overview.md)** — синхронизация `Endpoints` и `EndpointSlice` при изменении статусов готовности.
* **[Поиск и устранение неисправностей (Troubleshooting)](../Troubleshooting/troubleshooting_overview.md)** — комплексная методология локализации сетевых и прикладных сбоев.
* **[Горячий старт Java-приложений](../Scheduling/java-startup-cpu-boost.md)** — тюнинг `startupProbe` в сочетании с динамическим выделением ресурсов CPU.
