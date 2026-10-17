# Лучшие практики написания манифестов Pod в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+

## Определения

* **Манифест Pod (Pod Manifest)** — декларативное описание желаемого состояния неделимой единицы развертывания в Kubernetes, содержащее спецификацию одного или нескольких тесно связанных контейнеров, их сетевого пространства, томов и ограничений безопасности.
* **Неизменяемый тег (Immutable Tag)** — жестко зафиксированная версия контейнерного образа (конкретный SemVer-релиз или криптографический дайджест `sha256:...`), предотвращающая спонтанную подмену исполняемого кода при перезапусках контейнера.
* **Классы качества обслуживания (QoS Classes)** — классификация Pod (`Guaranteed`, `Burstable`, `BestEffort`), присваиваемая `kubelet` на основе соотношения `requests` и `limits` по CPU и памяти, определяющая приоритет вытеснения при дефиците ресурсов узла.
* **CFS Quota Throttling** — принудительное замедление исполнения потоков процесса со стороны планировщика ядра Linux Completely Fair Scheduler (CFS) при превышении квоты времени (`cpu.cfs_quota_us`), выделенной на период (`cpu.cfs_period_us`). В отличие от памяти, превышение лимита CPU не приводит к аварийной остановке, но вызывает всплески задержек (tail latency).
* **OOMKilled (Exit Code 137)** — принудительное завершение процесса ядром Linux (Out of Memory Killer) при превышении лимита cgroup (`memory.max`) или при исчерпании доступной физической памяти узла с учетом приоритета `oom_score_adj`.
* **Эфемерное хранилище (Ephemeral Storage)** — локальный дисковый ресурс рабочего узла (`spec.containers[*].resources.limits.ephemeral-storage`), потребляемый слоями контейнеров, логами (`/var/log/pods`) и томами `emptyDir`. При отсутствии лимитов переполнение диска переводит узел в состояние `DiskPressure` и вызывает массовую эвакуацию нагрузок.
* **Сетевая гонка при завершении (Graceful Termination Race Condition)** — временной лаг между переводом Pod в состояние `Terminating` и моментом, когда сетевые компоненты (`kube-proxy`, CNI, CoreDNS) на всех узлах кластера обновят локальные правила iptables/IPVS и перестанут направлять клиентский трафик на завершающийся узел.
* **Триада зондов (Startup, Readiness, Liveness Probes)** — иерархический комплекс проверок `kubelet`, координирующий безопасную инициализацию, включение в балансировку трафика и аварийный перезапуск процесса при дедлоках.
* **Pod Security Standards (PSS/PSA)** — встроенная модель контроля безопасности Kubernetes (уровни `Privileged`, `Baseline`, `Restricted`), реализующая изоляцию пространств имен ядра Linux через директивы `securityContext`.
* **Бюджет прерывания пода (Pod Disruption Budget, PDB)** — политика доступности сервиса, задающая минимальное число одновременно доступных реплик при добровольных административных работах (плановый дренаж узлов, обновление ОС хоста).

---

## Архитектура и принципы работы

### 1. Декларативное управление и гигиена образов

Развертывание Pod в bare-metal и on-premise инфраструктурах требует строгой воспроизводимости и минимальной поверхности атаки.

```
                           Управление образами Pod
                                      │
         ┌────────────────────────────┴────────────────────────────┐
         ▼                                                         ▼
 Фиксация версии (Immutability)                             Минимизация слоя ОС
 ├── Запрет :latest                                         ├── distroless / scratch
 ├── SemVer (например, :1.31.2)                             ├── Исключение package managers (apt, apk)
 └── Дайджест sha256:... (zero-trust)                       └── Отсутствие shell в production
```

* **Отказ от тега `:latest`:** Использование плавающего тега приводит к недетерминированному поведению при перебалансировке подов между узлами (узел со старым закэшированным слоем запустит устаревший код, а соседний узел — свежий).
* **Политика `imagePullPolicy`:**
  * Для фиксированных версионных тегов (`1.31.2`) и дайджестов всегда задается `IfNotPresent`. Это исключает паразитный сетевой трафик к локальному реестру образов и ускоряет перезапуск упавших подов.
  * Значение `Always` допустимо только для динамических dev-окружений либо при явном требовании перепроверки хэша в реестре при каждом старте.
* **Безопасные базовые образы:** Использование базовых дистрибутивов `distroless` или `scratch` удаляет из контейнера компиляторы, утилиты отладки и командные оболочки (`/bin/sh`, `/bin/bash`), предотвращая выполнение произвольных скриптов злоумышленником при Remote Code Execution (RCE).

### 2. Управление ресурсами, QoS и поведение ядра Linux

`kubelet` транслирует значения `requests` и `limits` в подсистемы cgroups ядра Linux (cgroups v1 или cgroups v2).

```
                      Спецификация ресурсов (PodSpec)
                                     │
           ┌─────────────────────────┴─────────────────────────┐
           ▼                                                   ▼
     CPU (микропроцессор)                             Память (RAM)
     ├── requests -> cpu.weight (cgroups v2)          ├── requests -> резерв kube-scheduler
     │               / cpu.shares (cgroups v1)        └── limits   -> memory.max (cgroups v2)
     └── limits   -> cpu.max (cgroups v2)                             / memory.limit_in_bytes
                     / cpu.cfs_quota_us                               (Превышение: OOM Killer SIGKILL)
                     (Превышение: CFS Throttling)
```

#### Механика ограничения CPU и риск Throttling

* **Requests по CPU:** Гарантируют процессорное время в моменты пиковой нагрузки на узел. Планировщик (`kube-scheduler`) не разместит Pod на узел, если сумма всех `requests` превышает `Node Allocatable`.
* **Limits по CPU:** Задают жесткую квоту CFS (Completely Fair Scheduler). Если за период в 100 мс (`cpu.cfs_period_us = 100000`) контейнер исчерпал лимит `cpu.cfs_quota_us`, ядро замораживает потоки контейнера до начала следующего периода.
* **SRE-рекомендация:** Для низколатентных микросервисов и многопоточных сред (Java, Node.js, Go) необоснованно жесткие CPU limits вызывают деградацию 99-го перцентиля задержки (p99 latency) даже при низкой средней утилизации процессора. Если на узле настроен мониторинг очередей, рекомендуется использовать конфигурацию с гарантированным `requests.cpu`, но без `limits.cpu`, либо переводить Pod в класс `Guaranteed` с выделением эксклюзивных ядер через `CPU Manager` (`static` policy).

#### Механика ограничения памяти и OOM-Score

Память является несжимаемым (non-compressible) ресурсом. Превышение лимита памяти невозможно компенсировать замедлением.

| Класс QoS | Условие в манифесте | Значение `oom_score_adj` | Поведение при нехватке памяти |
| :--- | :--- | :--- | :--- |
| **`Guaranteed`** | `requests == limits` для CPU и памяти во всех контейнерах (включая init) | `-997` | Вытесняется и уничтожается OOM Killer в самую последнюю очередь. Рекомендован для СУБД, кэшей и критических API. |
| **`Burstable`** | `requests < limits` или заданы только requests/limits для одного из ресурсов | `min(max(2, 1000 - (1000 * requests.memory) / NodeCapacity), 999)` | Промежуточный приоритет. Чем выше доля зарезервированной памяти (`requests`), тем ниже вероятность уничтожения. |
| **`BestEffort`** | `requests` и `limits` не указаны ни для одного контейнера | `1000` | Первые кандидаты на завершение ядром хоста при возникновении `MemoryPressure`. Недопустимо в Production. |

Подробнее о расчете и управлении см. в [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md).

#### Контроль эфемерного хранилища (Ephemeral Storage)

На bare-metal серверах корневая файловая система `/var/lib/kubelet` разделяется между всеми подами узла.
* Запись неконтролируемых объемов логов в stdout/stderr или запись временных файлов в нелимитированный `emptyDir` приводит к заполнению локального SSD-накопителя узла.
* При достижении порогов `eviction-hard` узел переходит в состояние `DiskPressure` и начинает в случайном порядке выселять поды.
* Обязательное правило: задавать `resources.requests.ephemeral-storage` и `resources.limits.ephemeral-storage`, а для временных томов задавать явный `emptyDir.sizeLimit`.

### 3. Бессбойный жизненный цикл и сетевая конвергенция

Процедура удаления Pod в Kubernetes инициируется параллельно в плоскости управления и на рабочем узле:

```
                            Запрос на удаление Pod
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
   [Плоскость сети]                                    [Плоскость узла (Kubelet)]
 1. Pod -> Terminating                               1. Запуск preStop hook (если задан)
 2. Исключение из EndpointSlice                      2. Ожидание завершения preStop
 3. Асинхронное обновление iptables/IPVS             3. Отправка сигнала SIGTERM
    на ВСЕХ узлах кластера (лаг 1-10 сек)             4. Ожидание terminationGracePeriod
 4. Трафик ПРЕКРАЩАЕТ поступать                      5. Отправка SIGKILL (принудительно)
```

#### Сетевая гонка и preStop Hook

Когда клиентский запрос уже отправлен через локальный прокси (`kube-proxy` на соседнем узле), но правила IPVS/iptables еще не успели обновиться, запрос поступает на целевой Pod. Если приложение внутри пода уже получило сигнал `SIGTERM` и закрыло слушающий TCP-сокет, клиент получит ошибку `Connection Refused` (HTTP 502/504).
* **Решение:** Добавление задержки `preStop: exec: command: ["/bin/sh", "-c", "sleep 10..15"]`. Это искусственно удерживает контейнер в рабочем состоянии, пока сетевая топология кластера гарантированно отключает маршрутизацию на данный Pod.
* **Настройка `terminationGracePeriodSeconds`:** Значение таймера должно вычисляться по формуле:
  $$\text{terminationGracePeriodSeconds} \ge \text{preStop sleep} + \text{время обработки длинных запросов приложения} + 5\,\text{с}$$

#### Проблема процесса PID 1 в контейнере

Если исполняемый файл приложения запускается в контейнере как процесс с PID 1 без промежуточного init-процесса:
* В ядре Linux процесс PID 1 по умолчанию игнорирует стандартные обработчики сигналов. Сигнал `SIGTERM` не приведет к завершению процесса, если приложение явно не зарегистрировало обработчик.
* Контейнер продолжит работать до истечения полного таймаута `terminationGracePeriodSeconds` и будет грубо сброшен через `SIGKILL`, что приведет к повреждению транзакций и незакрытым сокетам.
* Контейнер не собирает дочерние зомби-процессы (`defunct`).
* **Решение:** Использовать минимальные init-системы (`tini`, `dumb-init`) в Dockerfile либо активировать флаг спецификации `shareProcessNamespace: true` (подробнее см. [Продвинутые темы Pod](./pod_advanced_topics.md)).

### 4. Проверки состояния (Health Checks Triad)

`kubelet` выполняет зондирование контейнеров согласно объявленным спецификациям:

```
 Жизненный цикл зондов
 ┌────────────────────────────────────────────────────────┐
 │ startupProbe (до первого успеха)                       │
 │ ├── Успех ────────────────────────────────┐            │
 │ └── Неудача * threshold -> Restart        │            │
 └───────────────────────────────────────────┼────────────┘
                                             ▼
 ┌───────────────────────────────────────────┬───────────────────────────────────────────┐
 │ readinessProbe                            │ livenessProbe                             │
 │ ├── Успех -> Pod добавлен в Endpoints     │ ├── Успех -> Процесс здоров               │
 │ └── Неудача -> Исключение из Endpoints    │ └── Неудача * threshold -> SIGTERM/KILL   │
 └───────────────────────────────────────────┴───────────────────────────────────────────┘
```

1. **`startupProbe`:** Блокирует выполнение `readiness` и `liveness` проверок на время медленного холодного старта (прогрев JVM, чтение индексов БД). Защищает от циклического перезапуска по `livenessProbe`.
2. **`readinessProbe`:** Определяет способность пода отвечать на пользовательские запросы. При временном сбое (переполнение пула соединений БД) убирает Pod из балансировки, не убивая процесс.
3. **`livenessProbe`:** Служит исключительно для вывода процесса из необратимого дедлока или зависания.
4. **Опасность `exec`-проб:**
   * Каждое выполнение `exec` (`/bin/sh -c ...`) порождает системные вызовы `fork()` и `execve()`, создавая новый процесс внутри контейнера.
   * При проверке раз в 2–5 секунд на высоконагруженном узле с сотнями контейнеров это приводит к скачкам утилизации CPU ядра и риску исчерпания таблицы PID хоста (`kernel: cgroup: fork rejected by pids controller`).
   * **Рекомендация:** Всегда предпочитать легковесные проверки `httpGet`, `tcpSocket` или нативные `grpc` зонды.

Подробная архитектура проверок представлена в [Пробы в Kubernetes](../probes.md).

### 5. Контекст безопасности (Security Context) и изоляция

Для соответствия профилю `Restricted` стандарта Pod Security Standards манифест должен явно настраивать ограничения на уровне пода и на уровне контейнеров.

```
                           Уровни Security Context
                                      │
         ┌────────────────────────────┴────────────────────────────┐
         ▼                                                         ▼
 Уровень Pod (PodSecurityContext)                          Уровень Container (SecurityContext)
 ├── runAsNonRoot: true                                    ├── allowPrivilegeEscalation: false
 ├── runAsUser: 10001                                      ├── readOnlyRootFilesystem: true
 ├── runAsGroup: 10001                                     ├── capabilities: drop: ["ALL"]
 ├── fsGroup: 10001                                        └── seccompProfile: RuntimeDefault
 └── fsGroupChangePolicy: "OnRootMismatch"
```

* **`runAsNonRoot: true` и явные UID/GID:** Предотвращают запуск процессов от суперпользователя хоста (`root`, UID 0). Защищают хостовую систему от компрометации в случае побега из контейнера (container breakout).
* **`allowPrivilegeEscalation: false`:** Блокирует биты `setuid` и `setgid` на бинарных файлах внутри контейнера, запрещая дочерним процессам получать больше привилегий, чем у родителя.
* **`readOnlyRootFilesystem: true`:** Блокирует возможность модификации системных файлов контейнера. При попытке загрузки бэкдора или изменения бинарников злоумышленник получит ошибку `Read-only file system`. Для временных файлов приложения монтируются изолированные тома `emptyDir`.
* **`capabilities: drop: ["ALL"]`:** Отключает все 40+ стандартных привилегий ядра Linux (например, `CAP_NET_RAW`, `CAP_SYS_ADMIN`), минимизируя вектор атак на ядро.
* **`seccompProfile: type: RuntimeDefault`:** Включает стандартный профиль фильтрации системных вызовов рантайма (`containerd` / `CRI-O`), блокируя опасные вызовы к ядру.
* **`fsGroupChangePolicy: "OnRootMismatch"`:** Критически важная директива для SRE и системных администраторов при работе с большими томами (PV/PVC). По умолчанию `kubelet` при каждом старте пода выполняет рекурсивный `chown` всех файлов на томе. На томах с сотнями тысяч файлов это приводит к зависанию пода в статусе `ContainerCreating` на десятки минут и перегрузке дисковой подсистемы. Политика `OnRootMismatch` выполняет смену прав только в случае, если права на корневой директории тома не совпадают с `fsGroup`.
* **`automountServiceAccountToken: false`:** По умолчанию Kubernetes монтирует во все контейнеры JWT-токен сервисного аккаунта в `/var/run/secrets/kubernetes.io/serviceaccount`. Если приложению не требуется обращаться к Kube-API-Server, этот токен является лишней брешью в безопасности и должен быть отключен.

Детальный разбор параметров приведен в [Security Context в Kubernetes](../../Security/pod_security_context.md).

### 6. Отказоустойчивость и топология на Bare-Metal / On-Prem

В изолированных дата-центрах и on-premise кластерах отказ одного физического сервера не должен приводить к простою сервиса:

* **`topologySpreadConstraints`:** Равномерно распределяет реплики приложения между физическими серверами по ключу `topologyKey: kubernetes.io/hostname`. Параметр `maxSkew: 1` гарантирует, что разница в числе реплик между любыми двумя серверами не превысит одного пода.
* **`podAntiAffinity`:** Мягкое (`preferredDuringSchedulingIgnoredDuringExecution`) или жесткое (`requiredDuringSchedulingIgnoredDuringExecution`) антисродство, предотвращающее размещение двух реплик одного сервиса на одном физическом гипервизоре или в одной серверной стойке.
* **`priorityClassName`:** Определяет приоритет планирования и устойчивость к вытеснению. В production-кластерах критические сервисы должны иметь класс с высоким весом, защищающий их от прерывания при появлении фоновых batch-нагрузок.

### 7. Оптимизация сети и DNS-резолвинга

По умолчанию резолвер glibc/musl внутри контейнера конфигурируется параметром `ndots: 5`.
* Любое обращение к внешнему ресурсу, содержащему менее 5 точек (например, `api.github.com` — 2 точки), заставляет резолвер последовательно выполнять поиск по доменным суффиксам кластера:
  1. `api.github.com.<namespace>.svc.cluster.local` $\rightarrow$ NXDOMAIN
  2. `api.github.com.svc.cluster.local` $\rightarrow$ NXDOMAIN
  3. `api.github.com.cluster.local` $\rightarrow$ NXDOMAIN
  4. `api.github.com` $\rightarrow$ Итоговый успешный ответ
* Это умножает трафик к `CoreDNS` в 4–5 раз, перегружает таблицу отслеживания соединений ядра Linux (`nf_conntrack`) и приводит к спорадическим задержкам в 1–5 секунд из-за UDP race conditions.
* **Решение:** Настройка `spec.dnsConfig` с параметром `ndots: "2"` и опцией `single-request-reopen`.

---

## Практические сценарии и конфигурация

### Сценарий 1: Эталонный Production-манифест Pod

Ниже представлен завершенный, эталонный манифест Pod для критического сервиса, объединяющий все требования по безопасности, производительности, сетевой оптимизации и отказоустойчивости в on-premise среде.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: production-api-server
  namespace: production
  labels:
    app.kubernetes.io/name: api-server
    app.kubernetes.io/instance: api-server-prod-01
    app.kubernetes.io/version: "1.31.2"
    app.kubernetes.io/component: backend
    app.kubernetes.io/part-of: billing-system
    app.kubernetes.io/managed-by: manual
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
    prometheus.io/path: "/metrics"
spec:
  # Защита от компрометации API-сервера: отключение токена по умолчанию
  automountServiceAccountToken: false

  # Приоритет вытеснения для критической рабочей нагрузки
  priorityClassName: high-priority

  # Время на корректное завершение: preStop (15s) + приложение (15s) + запас (5s)
  terminationGracePeriodSeconds: 35

  # Гарантия распределения по разным физическим серверам хоста
  topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: api-server

  # Тюнинг DNS-клиента: снижение паразитной нагрузки на CoreDNS
  dnsConfig:
    options:
    - name: ndots
      value: "2"
    - name: single-request-reopen

  # Контекст безопасности на уровне всего Pod
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    fsGroupChangePolicy: "OnRootMismatch"
    seccompProfile:
      type: RuntimeDefault

  containers:
  - name: application
    # Использование фиксированного SemVer-тега без плавающего :latest
    image: registry.local/apps/billing-api:1.31.2
    imagePullPolicy: IfNotPresent

    ports:
    - name: http
      containerPort: 8080
      protocol: TCP

    # Класс Guaranteed QoS: requests строго равны limits
    resources:
      requests:
        cpu: "1000m"
        memory: "1Gi"
        ephemeral-storage: "512Mi"
      limits:
        cpu: "1000m"
        memory: "1Gi"
        ephemeral-storage: "1Gi"

    # Контекст безопасности контейнера: полная изоляция
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop:
        - ALL

    # Подключение конфигурации через Projected Volume
    env:
    - name: ENVIRONMENT
      value: "production"
    - name: POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name

    # Зонд холодного старта: дает до 60 секунд на инициализацию приложения
    startupProbe:
      httpGet:
        path: /healthz/startup
        port: http
      initialDelaySeconds: 2
      periodSeconds: 3
      timeoutSeconds: 2
      failureThreshold: 20

    # Зонд маршрутизации: готовность принимать трафик
    readinessProbe:
      httpGet:
        path: /healthz/ready
        port: http
      periodSeconds: 5
      timeoutSeconds: 2
      successThreshold: 1
      failureThreshold: 3

    # Зонд жизнеспособности: обнаружение взаимных блокировок процесса
    livenessProbe:
      httpGet:
        path: /healthz/live
        port: http
      periodSeconds: 10
      timeoutSeconds: 2
      failureThreshold: 3

    # Компенсация сетевого лага обновления iptables/IPVS на узлах
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 15"]

    # Точки монтирования для временных данных при read-only корневой ФС
    volumeMounts:
    - name: tmp-dir
      mountPath: /tmp
    - name: cache-dir
      mountPath: /var/cache/app
    - name: config-volume
      mountPath: /etc/app/config
      readOnly: true

  # Изолированные тома с ограничением дисковой квоты
  volumes:
  - name: tmp-dir
    emptyDir:
      sizeLimit: 256Mi
  - name: cache-dir
    emptyDir:
      medium: Memory
      sizeLimit: 128Mi
  - name: config-volume
    projected:
      sources:
      - configMap:
          name: api-server-config
          items:
          - key: app.properties
            path: app.properties
```

### Сценарий 2: Развертывание защищенного Pod с readOnlyRootFilesystem

При включении `readOnlyRootFilesystem: true` приложения, пытающиеся создать lock-файлы, PID-файлы или временные сокеты в `/tmp` или `/run`, аварийно завершаются. Сценарий демонстрирует изоляцию изменяемых путей через `emptyDir` с размещением в оперативной памяти (tmpfs):

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: hardened-nginx
  namespace: production
  labels:
    app.kubernetes.io/name: web-proxy
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 101 # Системный пользователь nginx
    runAsGroup: 101
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: nginx
    image: registry.local/library/nginx-unprivileged:1.27.1-alpine
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop:
        - ALL
        add:
        # Для портов >= 1024 привилегии не требуются, но если нужен порт 80:
        # - NET_BIND_SERVICE
    resources:
      requests:
        cpu: "100m"
        memory: "128Mi"
        ephemeral-storage: "64Mi"
      limits:
        cpu: "250m"
        memory: "128Mi"
        ephemeral-storage: "128Mi"
    volumeMounts:
    - name: nginx-cache
      mountPath: /var/cache/nginx
    - name: nginx-run
      mountPath: /var/run
    - name: tmp-dir
      mountPath: /tmp
  volumes:
  - name: nginx-cache
    emptyDir:
      sizeLimit: 64Mi
  - name: nginx-run
    emptyDir:
      medium: Memory
      sizeLimit: 16Mi
  - name: tmp-dir
    emptyDir:
      medium: Memory
      sizeLimit: 32Mi
```

### Сценарий 3: Защита физического узла от DiskPressure (Ephemeral Storage)

При отсутствии лимитов на локальное хранилище переполнение диска контейнером приводит к аварийной эвакуации всех подов с сервера. Конфигурация ниже задает квоту на эфемерный диск:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: batch-processor
  namespace: processing
spec:
  containers:
  - name: worker
    image: registry.local/processing/worker:2.4.0
    resources:
      requests:
        cpu: "500m"
        memory: "512Mi"
        ephemeral-storage: "1Gi"
      limits:
        cpu: "1000m"
        memory: "1Gi"
        ephemeral-storage: "2Gi" # Kubelet эвиктит Pod при превышении 2Gi
    volumeMounts:
    - name: scratch-space
      mountPath: /mnt/scratch
  volumes:
  - name: scratch-space
    emptyDir:
      sizeLimit: 1500Mi # Ограничение конкретно на этот том
```

### Сценарий 4: Оптимизация сетевых DNS-запросов на Bare-Metal кластерах

Конфигурация пода с переопределением параметров libc resolver для устранения 5-секундных сетевых задержек:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: payment-client
  namespace: payment
spec:
  dnsPolicy: ClusterFirst
  dnsConfig:
    nameservers:
    - 10.96.0.10 # IP-адрес CoreDNS в кластере
    searches:
    - payment.svc.cluster.local
    - svc.cluster.local
    - cluster.local
    options:
    - name: ndots
      value: "2"
    - name: timeout
      value: "2"
    - name: attempts
      value: "2"
    - name: single-request-reopen
  containers:
  - name: client
    image: registry.local/payment/client:1.4.0
    resources:
      requests:
        cpu: "200m"
        memory: "256Mi"
      limits:
        cpu: "500m"
        memory: "256Mi"
```

---

## Операции и команды

Все команды валидации и диагностики спецификаций манифестов должны выполняться перед деплоем и в процессе отладки.

### Валидация и статический анализ манифестов

Клиентская валидация синтаксиса без обращения к API-серверу:
```bash
kubectl apply --dry-run=client -f production-pod.yaml
# → pod/production-api-server created (dry run)
```

Серверная валидация манифеста (проверка через Admission Webhooks и OpenAPI схемы кластера):
```bash
kubectl apply --dry-run=server -f production-pod.yaml
# → pod/production-api-server created (server dry run)
```

Проверка соответствия стандарту безопасности Pod Security Standards (Restricted):
```bash
kubectl label --dry-run=client --overwrite ns production pod-security.kubernetes.io/enforce=restricted
# → namespace/production labeled (dry run)
```

Статический линтинг манифеста с помощью `kube-linter`:
```bash
kube-linter lint production-pod.yaml
# → Checked 1 file across 1 resource.
# → No lint errors found!
```

Валидация схемы через `kubeconform` (с указанием конкретной версии Kubernetes):
```bash
kubeconform -strict -kubernetes-version 1.31.0 -schema-location default production-pod.yaml
# → production-pod.yaml - Pod production-api-server is valid
```

Автоматизированный поиск опасных антипаттернов в манифесте перед коммитом:
```bash
# 1. Проверка наличия :latest тега
grep -nE "image:.*:latest$" production-pod.yaml
# → (пустой вывод означает отсутствие тега :latest — норма)

# 2. Проверка наличия блока ресурсов во всех контейнерах
grep -c "resources:" production-pod.yaml
# → 1

# 3. Проверка присутствия seccomp профиля
grep -A 2 "seccompProfile:" production-pod.yaml
# → seccompProfile:
# →   type: RuntimeDefault
```

### Инспекция работающего Pod и runtime-характеристик

Получение рассчитанного планировщиком класса качества обслуживания (QoS Class):
```bash
kubectl get pod production-api-server -n production -o jsonpath='{.status.qosClass}'
# → Guaranteed
```

Проверка реального `oom_score_adj`, назначенного `kubelet` для контейнера на хосте:
```bash
# Выполняется на рабочем узле bare-metal кластера
crictl inspect $(crictl ps --name application -q) | grep -i oomscoreadj
# → "oomScoreAdj": -997
```

Проверка сгенерированного файла `/etc/resolv.conf` внутри работающего контейнера:
```bash
kubectl exec -n production production-api-server -c application -- cat /etc/resolv.conf
# → search production.svc.cluster.local svc.cluster.local cluster.local
# → nameserver 10.96.0.10
# → options ndots:2 single-request-reopen
```

Замер времени выполнения DNS-запроса с учетом оптимизированного `ndots`:
```bash
kubectl exec -n production production-api-server -c application -- time nslookup ya.ru
# → Server:         10.96.0.10
# → Address:        10.96.0.10#53
# → Name:   ya.ru
# → Address: 77.88.55.242
# → real    0m 0.004s
# → user    0m 0.001s
# → sys     0m 0.002s
```

Инспекция процессов внутри пода при включенном `shareProcessNamespace`:
```bash
kubectl exec -n production production-api-server -c application -- ps aux
# → PID   USER     TIME  COMMAND
# →     1 10001     0:00 /pause
# →     7 10001     0:02 /app/server
```

---

## Диагностика и устранение неполадок

### 1. Pod завис в статусе Pending

#### Симптомы
Pod создан в etcd, но контейнеры не запускаются. Поле `status.phase` имеет значение `Pending`.

#### Причины
1. Недостаточно свободных ресурсов (`CPU`, `Memory` или `Ephemeral Storage`) на узлах кластера под заявленные `requests`.
2. Нарушение правил `topologySpreadConstraints` или жесткого антисродства `podAntiAffinity`.
3. Спецификация ссылается на несуществующий `priorityClassName`, `Secret` или `ConfigMap`.

#### Диагностика
```bash
kubectl describe pod production-api-server -n production | grep -A 10 "Events:"
# → Events:
# →   Type     Reason            Age   From               Message
# →   ----     ------            ----  ----               -------
# →   Warning  FailedScheduling  12s   default-scheduler  0/8 nodes are available: 8 Insufficient memory. preemption: 0/8 nodes are available: 8 No preemption victims found for incoming pod.
```

#### Решение
1. Проверить доступную емкость узлов через `kubectl describe nodes | grep -A 5 "Allocated resources"`.
2. Если ресурсы исчерпаны — оптимизировать `requests` либо добавить физические серверы в пул.
3. Если сбой вызван `topologySpreadConstraints`, временно изменить `whenUnsatisfiable: DoNotSchedule` на `whenUnsatisfiable: ScheduleAnyway`.

---

### 2. Ошибка CrashLoopBackOff и OOMKilled (Exit Code 137)

#### Симптомы
Контейнер непрерывно перезапускается с увеличивающимся интервалом задержки. Счетчик перезапусков `Restarts` растет.

#### Причины
1. Процесс превысил порог `resources.limits.memory` и был завершен ядром хоста по SIGKILL (Exit Code 137).
2. Приложение упало из-за отсутствия обязательной переменной окружения или недоступности локального файла конфигурации (Exit Code 1 или 2).
3. Зонд `livenessProbe` настроен на слишком жесткий таймаут и принудительно убивает живой процесс во время обработки тяжелого запроса.

#### Диагностика
Получение точной причины аварийного завершения предыдущего экземпляра контейнера:
```bash
kubectl get pod production-api-server -n production -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'
# → {"exitCode":137,"finishedAt":"2026-10-17T14:22:10Z","reason":"OOMKilled","startedAt":"2026-10-17T14:20:00Z"}
```

Просмотр последних логов упавшего процесса перед перезапуском:
```bash
kubectl logs production-api-server -n production --previous --tail=50
# → [ERROR] Failed to allocate 268435456 bytes of memory in worker thread pool
```

Проверка событий ядра на bare-metal узле:
```bash
# На узле размещения Pod
dmesg -T | grep -E -i "oom[-_]killer|killed process"
# → [Sat Oct 17 17:22:10 2026] Memory cgroup out of memory: Killed process 349122 (billing-api) total-vm:2410240kB, anon-rss:1048576kB, file-rss:0kB
```

#### Решение
1. Если зафиксирован `OOMKilled` — увеличить `limits.memory` и скорректировать лимиты кучи в приложении (для JVM: `-Xmx` должен составлять не более 70–75% от `limits.memory` для резерва под metaspace и off-heap).
2. Если завершение вызвано `livenessProbe` — увеличить `timeoutSeconds` (минимум 2–3с) и `failureThreshold` (минимум 3).

---

### 3. Ошибки зондов (Readiness / Liveness Probe Failed)

#### Симптомы
Контейнер работает (`Running`), но Pod имеет статус `Ready: 0/1` и не получает входящий трафик от `Service`.

#### Причины
1. Приложение перегружено и отвечает на HTTP health-check дольше, чем задано в `timeoutSeconds` (по умолчанию 1 секунда).
2. В коде проверки `/healthz` заложена проверка внешних зависимостей (база данных, шина сообщений). При деградации внешней БД перестают отвечать все поды кластера.
3. Ошибка маршрутизации к порту проверки (например, приложение слушает `127.0.0.1`, а проверка выполняется на интерфейс пода).

#### Диагностика
```bash
kubectl describe pod production-api-server -n production | grep -E "Readiness probe failed|Liveness probe failed"
# → Warning  Unhealthy  4s (x8 over 44s)  kubelet  Readiness probe failed: HTTP probe failed with statuscode: 503
```

Ручная проверка эндпоинта готовности изнутри сети Pod:
```bash
kubectl exec -n production production-api-server -c application -- wget -qO- --timeout=2 http://localhost:8080/healthz/ready
# → wget: server returned error: HTTP/1.1 503 Service Unavailable
```

#### Решение
1. Вынести проверки внешних зависимостей из `livenessProbe` и `readinessProbe`. Liveness должен проверять только способность самого локального процесса выполнять циклы обработки.
2. Увеличить `timeoutSeconds: 3` и выставить `periodSeconds: 10`.

---

### 4. Принудительное выселение Evicted (DiskPressure)

#### Симптомы
Pod внезапно переходит в статус `Evicted`. В деталях пода указана причина `The node had condition: [DiskPressure]`.

#### Причины
1. Контейнер пишет логи гигантского объема в stdout, переполняя диск хоста в `/var/log/pods`.
2. Том `emptyDir` не имел директивы `sizeLimit` и был переполнен временными файлами.
3. В манифесте отсутствовали лимиты `ephemeral-storage`.

#### Диагностика
```bash
kubectl describe pod production-api-server -n production | grep -E "Reason:|Message:"
# → Reason:  Evicted
# → Message: The node was low on resource: ephemeral-storage. Container application was using 2541880Ki, which exceeds its request of 524288Ki.
```

#### Решение
1. Добавить в манифест жесткие лимиты `resources.limits.ephemeral-storage`.
2. Для томов `emptyDir` задать `sizeLimit` (например, `sizeLimit: 512Mi`).
3. Настроить ротацию логов в `containerd` на узлах (`max-size: 50m`, `max-file: 5`).

---

### 5. Ошибки загрузки образа ImagePullBackOff / ErrImagePull

#### Симптомы
Pod находится в статусе `ImagePullBackOff`. Контейнер не может быть запущен.

#### Причины
1. Опечатка в имени репозитория или в номере тега.
2. Приватный реестр образов требует авторизации, но в манифесте не указан `imagePullSecrets`.
3. Сетевой сбой или блокировка MTU между рабочим узлом bare-metal кластера и корпоративным Container Registry.

#### Диагностика
```bash
kubectl describe pod production-api-server -n production | grep -A 4 "Failed to pull image"
# → Warning  Failed     10s (x2 over 32s)  kubelet  Failed to pull image "registry.local/apps/billing-api:1.31.2": rpc error: code = NotFound desc = failed to pull and unpack image "registry.local/apps/billing-api:1.31.2": failed to resolve reference: not found
```

Проверка сетевой доступности реестра с узла кластера:
```bash
curl -k -I https://registry.local/v2/
# → HTTP/2 200
```

#### Решение
1. Исправить тег или имя образа на существующие в реестре.
2. Привязать секрет с учетными данными реестра:
```bash
kubectl create secret docker-registry regcred \
  --docker-server=registry.local \
  --docker-username=robot-deploy \
  --docker-password=SecretPassword123 \
  -n production
# → secret/regcred created
```
3. Указать `imagePullSecrets: [{name: regcred}]` в `spec` пода или назначить его по умолчанию для `ServiceAccount`.

---

## Лучшие практики и рекомендации

### 1. Чек-лист готовности манифеста к Production (Production Readiness)

Используйте данный чек-лист при аудите каждого манифеста перед развертыванием в промышленной среде:

#### Безопасность и изоляция (Security)
* [ ] **`runAsNonRoot: true`:** Установлен на уровне Pod или всех контейнеров.
* [ ] **`allowPrivilegeEscalation: false`:** Жестко зафиксирован во всех контейнерах.
* [ ] **`readOnlyRootFilesystem: true`:** Корневая файловая система неизменяема; для `/tmp` выделен `emptyDir`.
* [ ] **`capabilities.drop: ["ALL"]`:** Отключены все потенциально опасные привилегии Linux.
* [ ] **`seccompProfile: {type: RuntimeDefault}`:** Активирован дефолтный системный профиль seccomp.
* [ ] **`automountServiceAccountToken: false`:** Отключен автоматический выпуск токена K8s API.
* [ ] **`fsGroupChangePolicy: "OnRootMismatch"`:** Настроен для предотвращения задержек рекурсивного `chown` на томах.
* [ ] **Секреты:** Никаких паролей и токенов в открытом виде в блоке `env`. Используются `secretKeyRef` или `projected`.

#### Ресурсы и стабильность узлов (Resource Management)
* [ ] **Запрет плавающих тегов:** Отсутствует тег `:latest`; используются SemVer или SHA-256 дайджесты.
* [ ] **`requests` по CPU и Memory:** Заданы явно для каждого контейнера (включая sidecar).
* [ ] **`limits.memory`:** Установлен порог памяти для защиты узла от общего OOM.
* [ ] **Класс QoS:** Соответствует роли сервиса (`Guaranteed` для БД и критических API; `Burstable` для стандартного бэкенда).
* [ ] **`ephemeral-storage`:** Заданы `requests` и `limits` для предотвращения переполнения SSD узла.
* [ ] **Лимиты `emptyDir`:** Для всех томов `emptyDir` настроен `sizeLimit`.

#### Доступность и сетевое взаимодействие (Availability & Network)
* [ ] **Триада зондов:** Настроены `startupProbe`, `readinessProbe` и `livenessProbe` с раздельными URL-путями.
* [ ] **Таймауты проверок:** Параметр `timeoutSeconds` равен минимум 2–3с (защита от ложного сброса при всплеске нагрузки).
* [ ] **Отказ от `exec`-проб:** Пробы используют протоколы `httpGet`, `tcpSocket` или `grpc`.
* [ ] **Сетевая конвергенция:** В блоке `lifecycle.preStop` задан `sleep 10..15` для синхронизации IPVS/iptables.
* [ ] **Graceful Period:** `terminationGracePeriodSeconds` больше суммы времени preStop и обработки запросов.
* [ ] **Распределение реплик:** Настроен `topologySpreadConstraints` по `kubernetes.io/hostname`.
* [ ] **Оптимизация CoreDNS:** В `dnsConfig` выставлен `ndots: "2"`.
* [ ] **PDB:** Создан объект `PodDisruptionBudget` для защиты сервиса от планового дренажа узлов.

#### Наблюдаемость (Observability)
* [ ] **Стандартные метки SIG-Apps:** Присутствуют `app.kubernetes.io/name`, `app.kubernetes.io/version`, `app.kubernetes.io/component`.
* [ ] **Метрики Prometheus:** Добавлены аннотации `prometheus.io/scrape: "true"`, `port` и `path`.
* [ ] **Логирование:** Все логи пишутся в stdout/stderr (формат JSON) для централизованного сбора через DaemonSet.

---

### 2. Сводная матрица типовых антипаттернов

| Антипаттерн в манифесте | Реальное последствие в Production | Корректное техническое решение |
| :--- | :--- | :--- |
| **`image: app:latest`** | Непредсказуемый код на разных узлах, невозможность воспроизводимого отката. | Фиксация релиза: `image: app:1.31.2` или `image: app@sha256:...`. |
| **Отсутствие `resources`** | Бесконтрольный рост потребления, падение соседних подов, класс `BestEffort`. | Обязательное указание `requests` и `limits` для CPU, Memory и Ephemeral Storage. |
| **`requests > limits`** | Манифест отклоняется API-сервером на этапе валидации (`422 Unprocessable Entity`). | `requests` всегда должны быть меньше или строго равны `limits`. |
| **Запуск от Root (UID 0)** | Возможность побега из контейнера на хост и компрометация физического сервера. | `runAsNonRoot: true`, `runAsUser: 10001`, `allowPrivilegeEscalation: false`. |
| **Идентичные эндпоинты для Liveness и Readiness** | При временной перегрузке базы данных `liveness` начинает убивать поды, вызывая каскадный отказ. | Разделение проверок: `/healthz/live` (проверка дедлоков) и `/healthz/ready` (проверка готовности). |
| **Проверка внешних БД внутри `livenessProbe`** | При сбое внешней СУБД все поды приложения во всем кластере уходят в бесконечный CrashLoop. | Проверять доступность БД только в `readinessProbe` или `startupProbe`. |
| **Использование `exec`-проб (`curl`, `sh`)** | Постоянный форк процессов, высокое потребление CPU ядра, утечка PID на сервере. | Использовать нативные легковесные проверки `httpGet`, `tcpSocket` или `grpc`. |
| **Отсутствие `preStop` hook при Graceful Shutdown** | Ошибки HTTP 502/504 у клиентов из-за задержки обновления правил маршрутизации в сети. | Добавить задержку: `lifecycle.preStop.exec.command: ["/bin/sh", "-c", "sleep 15"]`. |
| **Отсутствие `sizeLimit` на томах `emptyDir`** | Заполнение диска ноды временными файлами, перевод узла в `DiskPressure`, массовый эвикшн. | Задать явную квоту: `emptyDir: { sizeLimit: 512Mi }`. |
| **Дефолтный `ndots: 5` при активных внешних вызовах** | В 4–5 раз больше DNS-запросов к CoreDNS, задержки до 5 секунд из-за conntrack race. | Задать в `spec.dnsConfig` опцию `ndots: "2"`. |
| **Монтирование токена ServiceAccount без необходимости** | Токен с правами на Kube-API доступен атакующему при уязвимости в приложении. | `automountServiceAccountToken: false`. |

---

### 3. Рекомендуемые профили конфигурации для различных типов нагрузок

| Профиль нагрузки | Класс QoS | Рекомендации по CPU | Рекомендации по Memory | Тип проб | Особенности спецификации |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stateless Web API (Go, Rust)** | `Guaranteed` или `Burstable` | `requests == limits` (например, `500m`) для минимизации задержек. | `requests == limits` (например, `256Mi`). | `httpGet` | Обязателен `preStop: sleep 10..15`, `topologySpreadConstraints` по hostname. |
| **Java / Spring Boot** | `Guaranteed` | `requests == limits` (от 2 до 4 ядер), чтобы JIT-компилятор корректно определял число потоков. | `requests == limits` (например, `4Gi`). Настройка `-Xmx3g` (75% от лимита). | `httpGet` | Обязателен `startupProbe` с окном 60–90 секунд; `terminationGracePeriodSeconds: 60`. |
| **Nginx / Reverse Proxy** | `Burstable` | `requests: 200m`, `limits: 1000m` для отработки сетевых всплесков. | `requests == limits` (например, `256Mi`). | `httpGet` | Монтирование `/var/cache/nginx` и `/var/run` в память (`emptyDir.medium: Memory`). |
| **High-load СУБД / Кэш (On-Prem)** | `Guaranteed` | Эксклюзивные ядра через `CPU Manager` (`requests == limits: 4000m`). | `requests == limits` (например, `16Gi`), запрет свопинга. | `exec` (с осторожностью) или `tcpSocket` | `fsGroupChangePolicy: "OnRootMismatch"`, высокий `priorityClassName`, `terminationGracePeriodSeconds: 120`. |
| **Batch / Очереди (Workers)** | `Burstable` | `requests: 250m`, без жесткого `limits` (если допускается burst). | `requests: 512Mi`, `limits: 1Gi`. | `httpGet` или отсутствие liveness | Низкий приоритет `priorityClassName: batch`, отсутствие `preStop` hook (завершение по `SIGTERM`). |

---

## Дополнительная информация

**Связанные документы в базе знаний:**
* [Пробы в Kubernetes (Probes)](../probes.md) — детальная архитектура, протоколы проверки и взаимодействие с `kubelet`.
* [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md) — глубокий разбор cgroups, формулы `oom_score_adj` и квотирования.
* [Security Context в Kubernetes](../../Security/pod_security_context.md) — профили Pod Security Standards (PSA/PSS), маппинг UID и Linux capabilities.
* [Бюджет прерывания подов (PDB)](../../Autoscaling/pod_disruption_budget.md) — управление доступностью при добровольных прерываниях и регламентных работах.
* [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — фазы, условия, детальная диаграмма жизненного цикла и хуки.
* [Продвинутые темы Pod](./pod_advanced_topics.md) — неизменяемые поля, `shareProcessNamespace`, `PodOverhead`, `Scheduling Gates`.
* [Projected Volumes в Kubernetes](./volume_types/projected_volumes.md) — объединение Secret, ConfigMap и токенов в единые проекции.
* [Эфемерные контейнеры](./ephemeral_containers.md) — диагностика работающих подов без перезапуска через `kubectl debug`.
* [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md) — стандарты именования и аннотирования объектов кластера.
