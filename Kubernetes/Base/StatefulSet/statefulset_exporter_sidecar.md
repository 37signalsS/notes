# StatefulSet: Мониторинг БД через Exporter Sidecar

**Актуально для:** Kubernetes 1.30–1.37+ (Native Sidecars GA v1.33+) / PostgreSQL 16–18 (postgres_exporter v0.16+) / MySQL 8.0–8.4 LTS (mysqld_exporter v0.16+) / Redis 7.x (redis_exporter v1.67+)

## Определения

**Exporter Sidecar** — архитектурный паттерн развёртывания специализированного агента сбора метрик (например, `postgres_exporter`, `mysqld_exporter`, `redis_exporter`) в качестве вспомогательного (бокового) контейнера внутри того же пода, где работает целевая СУБД. Экспортер подключается к СУБД по локальному интерфейсу (`127.0.0.1` или UNIX-сокет) без прохождения внешних сетевых шлюзов и балансировщиков, транслирует внутреннюю телеметрию СУБД в формат Prometheus и предоставляет HTTP-эндпоинт `/metrics`.

**Native Sidecar (K8s 1.29+ Beta, GA v1.33+)** — штатный механизм Kubernetes, реализуемый путем объявления контейнера в секции `initContainers` с директивой `restartPolicy: Always`. В отличие от стандартных контейнеров, Native Sidecar стартует до основных рабочих контейнеров пода, переходит в состояние готовности по `readinessProbe`, продолжает непрерывно функционировать на протяжении всего жизненного цикла пода и останавливается только после полного завершения работы основного контейнера базы данных.

**Legacy Sidecar (Standard Container)** — параллельный запуск экспортера в общем блоке `spec.containers`. Характеризуется отсутствием детерминированного порядка старта и остановки: экспортер может запуститься раньше базы данных и начать выдавать ошибки подключения (`CrashLoopBackOff`), а при завершении работы пода — завершиться раньше СУБД, теряя финальные метрики сброса буферов и завершения транзакций.

**ServiceMonitor** — Custom Resource Definition (CRD) в составе Prometheus Operator, декларативно определяющий правила обнаружения и сбора метрик с эндпоинтов Kubernetes `Service` (включая Headless Services). Автоматически генерирует соответствующие конфигурации скрапинга (`scrape_configs`) в Prometheus.

**PodMonitor** — CRD Prometheus Operator для прямого обнаружения и скрапинга подов без промежуточного создания объекта `Service`. Оптимален для StatefulSet-нагрузок, так как обращается напрямую к сетевым адресам конкретных реплик по заданным меткам пода.

**Headless Service (`clusterIP: None`)** — сервис Kubernetes, не выделяющий единый виртуальный IP-адрес для балансировки нагрузки, а возвращающий через внутренний DNS прямые A/AAAA-записи всех готовых (или всех существующих при флаге `publishNotReadyAddresses: true`) подов StatefulSet. Используется как основа сетевой адресации и обнаружения целей мониторинга.

**Unix Domain Socket (UDS)** — механизм межпроцессного взаимодействия через файл сокета в локальной файловой системе Linux (в Kubernetes монтируется через том `emptyDir`). Позволяет экспортеру опрашивать СУБД в обход сетевого стека TCP/IP, исключая накладные расходы на сетевую инкапсуляцию, задержки loopback и необходимость передачи паролей в открытом виде по сети.

## Предварительные требования

1. **Кластер Kubernetes:** версия **v1.30–v1.37+** (On-Premise / Bare-Metal). Механизм `Native Sidecars` стабилен (GA) с версии **v1.33+** (в версиях v1.29–v1.32 включен по умолчанию через feature gate `SidecarContainers: true`). Проверка:
   ```bash
   kubectl version -o yaml
   ```
2. **Prometheus Operator:** развёрнутый стек мониторинга (`kube-prometheus-stack` или Prometheus Operator) с установленными CRD:
   ```bash
   kubectl get crd servicemonitors.monitoring.coreos.com podmonitors.monitoring.coreos.com prometheusrules.monitoring.coreos.com
   # → Все CRD должны быть в статусе Established
   ```
3. **Хранилище и StatefulSet:** функционирующий StatefulSet базы данных с выделенными постоянными томами (PVC) и безадресным сервисом ([Headless Service](../../Networking/Service/service_type_headless.md)). Базовые принципы: **[StatefulSet: Обзор](./statefulset_overview.md)**, **[Ключевые концепции](./statefulset_core_concepts.md)** и **[Практическое руководство](./statefulset_practical_guide.md)**.
4. **Безопасность (RBAC и Secrets):** учетные данные для мониторинга должны быть предварительно сохранены в объекте `Secret` с минимально необходимыми правами на чтение системных представлений (`pg_stat_*`, `performance_schema`, `INFO`).
5. **Сетевые политики:** порт экспортера (`9187/TCP` для PostgreSQL, `9104/TCP` для MySQL, `9121/TCP` для Redis) должен быть доступен для опроса подами Prometheus.

## Архитектура и механизм работы

### Выбор архитектурного паттерна

В средах Kubernetes сбор метрик с баз данных в составе StatefulSet может быть организован несколькими способами. Выбор паттерна определяет надежность, сетевые задержки и точность привязки телеметрии к топологии репликации.

| Критерий | Sidecar в StatefulSet (Рекомендуемый) | Отдельный Deployment (Централизованный) | DaemonSet на узлах кластера |
| :--- | :--- | :--- | :--- |
| **Сетевой путь** | `127.0.0.1` или Unix Domain Socket (нулевой оверхед) | Внешний сетевой маршрут через Service/Ingress | Сеть узла (hostNetwork) или оверлей |
| **Привязка к репликам** | Строгая привязка 1:1 к имени пода (`postgres-0`, `postgres-1`) | Обобщенный пул, требует явной конфигурации целей | Жесткая привязка к физическому узлу |
| **Жизненный цикл** | Запуск и удаление синхронны с подом БД | Независим от жизненного цикла экземпляров БД | Зависит от узла, а не от пода БД |
| **Отказоустойчивость** | Изолированный сбой (проблема затрагивает только 1 реплику) | Единая точка отказа (падение Deployment слепит мониторинг всех БД) | Сложность маршрутизации к подам БД |
| **Аутентификация** | Локальная авторизация (`trust` для UDS или peer auth) | Требуются открытые сетевые порты и внешние учетные записи | Требуются сетевые доступы со всех нод |
| **Потребление ресурсов** | Минимальный дополнительный оверхед на каждый под | Масштабируется отдельно от БД | Избыточен, если на ноде нет инстансов БД |

**Инженерный вывод:** Паттерн **Sidecar** является безальтернативным стандартом для StatefulSet СУБД. В кластерах с репликацией (Patroni, Galera, Redis Sentinel/Cluster) каждая реплика уникальна: одна находится в роли Primary/Leader, другие — Standby/Replica с разным лагом отставания (replication lag). Централизованный экспортер не может детерминированно связать системные метрики с конкретным томом PVC и порядковым индексом пода.

### Схема взаимодействия компонентов

```mermaid
graph TD
    subgraph Pod ["Pod: postgres-0 (StatefulSet)"]
        subgraph NetNS ["Общий сетевой стек (Network Namespace / Localhost)"]
            MainApp["Контейнер СУБД\n(PostgreSQL: 5432 / MySQL: 3306)"]
            Exporter["Native Sidecar\n(postgres_exporter: 9187)"]
            SharedSocket["Shared Volume (emptyDir)\n/var/run/postgresql/.s.PGSQL.5432"]
        end
    end

    Prometheus["Prometheus Server\n(kube-prometheus-stack)"]
    ServiceMonitor["ServiceMonitor / PodMonitor\n(Prometheus Operator)"]
    HeadlessSVC["Headless Service\n(clusterIP: None, publishNotReadyAddresses: true)"]

    MainApp <-->|Unix Domain Socket или 127.0.0.1| Exporter
    Exporter -.->|Запись/чтение сокета| SharedSocket
    MainApp -.->|Создание сокета| SharedSocket

    ServiceMonitor -->|Генерация scrape_config| Prometheus
    Prometheus -->|DNS-запрос эндпоинтов| HeadlessSVC
    HeadlessSVC -->|Прямой IP пода| Exporter
    Prometheus -->|HTTP GET /metrics (интервал 30s)| Exporter
```

### Жизненный цикл: Native Sidecar vs Legacy Sidecar

До появления механизма Native Sidecar запуск экспортера в блоке `spec.containers` приводил к двум классическим проблемам распределенных систем:

1. **Race Condition при инициализации:** Экспортер стартовал параллельно с СУБД. Пока PostgreSQL выполнял проверку контрольных точек (recovery/checkpoint) и прогрев кэша, экспортер непрерывно пытался подключиться к порту 5432, падал по таймауту и уходил в состояние `CrashLoopBackOff`.
2. **Преждевременная смерть при терминации пода:** При выполнении `kubectl drain` или масштабировании StatefulSet вниз Kubelet отправлял `SIGTERM` всем контейнерам одновременно. Экспортер завершался за секунду, а база данных в течение 30–60 секунд сбрасывала грязные страницы памяти на диск. В результате инженеры теряли метрики процесса штатного останова СУБД.

**Механика Native Sidecar (`initContainers` с `restartPolicy: Always`):**
* **Запуск:** Kubelet запускает экспортер строго до начала запуска основных контейнеров.
* **Блокировка:** Kubelet ожидает успешного прохождения `readinessProbe` сайдкара, прежде чем перейти к следующему init-контейнеру или основному контейнеру СУБД.
* **Работа:** Экспортер функционирует параллельно с основным приложением.
* **Останов:** При удалении пода Kubelet сначала посылает `SIGTERM` основному контейнеру СУБД. Экспортер продолжает работать, фиксируя процесс сброса буферов и закрытия сессий. `SIGTERM` сайдкару отправляется только после того, как основной контейнер полностью остановился.

> [!IMPORTANT]
> **Логическая ловушка зонда готовности (Deadlock):**
> Если в Native Sidecar настроить `readinessProbe`, проверяющую реальное подключение к СУБД (например, выполнение SQL-запроса), возникнет взаимная блокировка (deadlock): сайдкар не станет Ready, пока база не запустится, а база не начнет запускаться, пока сайдкар не станет Ready.
> **Решение:** Проба готовности сайдкар-экспортера должна проверять **только готовность самого HTTP-сервера экспортера** (HTTP GET `/metrics` или TCP-порт). При недоступности СУБД корректный экспортер обязан отвечать кодом `200 OK` и выставлять метрику доступности сервиса `pg_up 0` или `mysql_up 0`.

### Способ коммуникации: TCP Loopback vs Unix Domain Socket (UDS)

В стандартных конфигурациях подключение осуществляется через TCP loopback (`127.0.0.1:5432`). Однако для высоконагруженных систем предпочтителен обмен через Unix Domain Socket:

* **Производительность:** UDS работает полностью в пространстве ядра через буферы памяти без обработки стека TCP/IP (нет подсчета контрольных сумм, генерации пакетов, сегментации и подтверждений ACK). Нагрузка на CPU снижается на 15–25% при частом скрапинге.
* **Безопасность:** Доступ разграничивается стандартными правами файловой системы Linux (POSIX permissions). В конфигурации `pg_hba.conf` для локального сокета можно задать метод `peer` или доверенный доступ `trust` исключительно для локального пользователя сокета, исключая передачу сетевых паролей внутри пода.

## Конфигурация и практические сценарии

### Сценарий 1: PostgreSQL StatefulSet с Native Sidecar (postgres_exporter)

Ниже представлен отказоустойчивый манифест StatefulSet PostgreSQL 16 с Native Sidecar, кастомными запросами мониторинга репликации и соблюдением стандарта безопасности Pod Security Standard Restricted.

#### 1. Секрет с учетными данными и ConfigMap кастомных запросов

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-exporter-secret
  labels:
    app: postgres
type: Opaque
stringData:
  # Формат: postgresql://username:password@127.0.0.1:5432/postgres?sslmode=disable
  data-source-uri: "postgresql://postgres_exporter:Secr3tExP0rt3rP@ss@127.0.0.1:5432/postgres?sslmode=disable"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-exporter-queries
  labels:
    app: postgres
data:
  queries.yaml: |
    pg_replication_custom:
      query: |
        SELECT
          CASE
            WHEN pg_is_in_recovery() THEN 0
            ELSE 1
          END AS is_primary,
          CASE
            WHEN pg_is_in_recovery() THEN EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp())
            ELSE 0
          END AS replication_lag_seconds
      master: false
      metrics:
        - is_primary:
            usage: "GAUGE"
            description: "1 if instance is primary/master, 0 if standby/replica"
        - replication_lag_seconds:
            usage: "GAUGE"
            description: "Replication lag in seconds for standby nodes"

    pg_stat_activity_counts:
      query: |
        SELECT
          state,
          count(*) as count
        FROM pg_stat_activity
        WHERE state IS NOT NULL
        GROUP BY state
      metrics:
        - state:
            usage: "LABEL"
            description: "State of client connection"
        - count:
            usage: "GAUGE"
            description: "Number of connections in this state"
```

#### 2. Манифест Headless Service и StatefulSet

Обратите внимание на директиву `publishNotReadyAddresses: true` в сервисе. Она критически важна: Prometheus сможет опрашивать экспортер даже тогда, когда база данных находится в стадии инициализации или репликационного восстановления и основной контейнер еще не прошел readiness-пробу.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-headless
  labels:
    app: postgres
spec:
  clusterIP: None
  publishNotReadyAddresses: true
  ports:
  - name: postgres
    port: 5432
    targetPort: 5432
  - name: metrics
    port: 9187
    targetPort: 9187
  selector:
    app: postgres
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  labels:
    app: postgres
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
      securityContext:
        fsGroup: 999
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault

      initContainers:
      # Native Sidecar: postgres_exporter (K8s 1.29+ / GA 1.33+)
      - name: postgres-exporter
        image: prometheuscommunity/postgres-exporter:v0.16.0
        restartPolicy: Always
        securityContext:
          runAsNonRoot: true
          runAsUser: 65534
          runAsGroup: 65534
          readOnlyRootFilesystem: true
          allowPrivilegeEscalation: false
          capabilities:
            drop: ["ALL"]
        ports:
        - containerPort: 9187
          name: metrics
          protocol: TCP
        env:
        - name: DATA_SOURCE_URI
          valueFrom:
            secretKeyRef:
              name: postgres-exporter-secret
              key: data-source-uri
        - name: PG_EXPORTER_EXTEND_QUERY_PATH
          value: /etc/postgres-exporter/queries.yaml
        - name: PG_EXPORTER_DISABLE_DEFAULT_METRICS
          value: "false"
        - name: PG_EXPORTER_DISABLE_SETTINGS_METRICS
          value: "false"
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 150m
            memory: 128Mi
        livenessProbe:
          httpGet:
            path: /metrics
            port: metrics
          initialDelaySeconds: 15
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /metrics
            port: metrics
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        volumeMounts:
        - name: exporter-config
          mountPath: /etc/postgres-exporter
          readOnly: true

      containers:
      # Основной контейнер СУБД PostgreSQL
      - name: postgres
        image: postgres:16
        securityContext:
          runAsUser: 999
          runAsGroup: 999
          allowPrivilegeEscalation: false
          capabilities:
            drop: ["ALL"]
        ports:
        - containerPort: 5432
          name: postgres
        env:
        - name: POSTGRES_PASSWORD
          value: "SuperSecretRootPassword"
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: "2"
            memory: 4Gi
        readinessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - exec pg_isready -U postgres -h 127.0.0.1 -p 5432
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3

      volumes:
      - name: exporter-config
        configMap:
          name: postgres-exporter-queries
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      resources:
        requests:
          storage: 20Gi
```

### Сценарий 2: MySQL / MariaDB StatefulSet с mysqld_exporter через файл `.my.cnf`

Внедрение пароля базы данных в аргументы командной строки или переменные окружения (`DATA_SOURCE_NAME`) является уязвимостью, так как учетные данные видны в выводе `/proc/$PID/cmdline` и `/proc/$PID/environ`. Стандарт SRE — монтирование защищенного конфигурационного файла `.my.cnf` через Kubernetes Secret.

#### 1. Создание учетной записи в MySQL

```sql
-- Выполняется при первичной инициализации кластера БД
CREATE USER IF NOT EXISTS 'exporter'@'127.0.0.1' IDENTIFIED BY 'StrongExporterP@ssw0rd' WITH MAX_USER_CONNECTIONS 5;
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'127.0.0.1';
FLUSH PRIVILEGES;
```

#### 2. Секрет `.my.cnf`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mysql-exporter-config
  labels:
    app: mysql
type: Opaque
stringData:
  .my.cnf: |
    [client]
    user=exporter
    password=StrongExporterP@ssw0rd
    host=127.0.0.1
    port=3306
```

#### 3. Фрагмент спецификации пода StatefulSet MySQL с Native Sidecar

```yaml
spec:
  initContainers:
  - name: mysqld-exporter
    image: prom/mysqld-exporter:v0.16.0
    restartPolicy: Always
    securityContext:
      runAsNonRoot: true
      runAsUser: 65534
      runAsGroup: 65534
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
    command:
    - /bin/mysqld_exporter
    args:
    - --config.my-cnf=/etc/my-cnf/.my.cnf
    - --collect.info_schema.processlist
    - --collect.info_schema.innodb_metrics
    - --collect.global_status
    - --collect.global_variables
    - --collect.slave_status
    - --collect.info_schema.query_response_time
    # Отключение тяжелых коллекторов для высоконагруженных инстансов
    - --no-collect.info_schema.tables
    - --no-collect.info_schema.innodb_cmpmem
    ports:
    - containerPort: 9104
      name: metrics
      protocol: TCP
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 150m
        memory: 128Mi
    livenessProbe:
      httpGet:
        path: /metrics
        port: metrics
      initialDelaySeconds: 15
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /metrics
        port: metrics
      initialDelaySeconds: 5
      periodSeconds: 5
    volumeMounts:
    - name: my-cnf-vol
      mountPath: /etc/my-cnf
      readOnly: true
volumes:
- name: my-cnf-vol
  secret:
    secretName: mysql-exporter-config
    defaultMode: 0400
```

### Сценарий 3: Redis StatefulSet с redis_exporter Sidecar

`redis_exporter` подключается к локальному экземпляру Redis и опрашивает метрики потребления памяти, сетевых буферов, ключей и состояния репликации.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  labels:
    app: redis
spec:
  serviceName: redis-headless
  replicas: 3
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      initContainers:
      - name: redis-exporter
        image: oliver006/redis_exporter:v1.67.0
        restartPolicy: Always
        securityContext:
          runAsNonRoot: true
          runAsUser: 65534
          runAsGroup: 65534
          readOnlyRootFilesystem: true
          allowPrivilegeEscalation: false
          capabilities:
            drop: ["ALL"]
        env:
        - name: REDIS_ADDR
          value: "redis://127.0.0.1:6379"
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: redis-secret
              key: password
        ports:
        - containerPort: 9121
          name: metrics
        resources:
          requests:
            cpu: 30m
            memory: 48Mi
          limits:
            cpu: 100m
            memory: 96Mi
        livenessProbe:
          httpGet:
            path: /metrics
            port: metrics
          initialDelaySeconds: 10
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /metrics
            port: metrics
          initialDelaySeconds: 5
          periodSeconds: 5

      containers:
      - name: redis
        image: redis:7.2-alpine
        command: ["redis-server", "--requirepass", "$(REDIS_PASSWORD)"]
        env:
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: redis-secret
              key: password
        ports:
        - containerPort: 6379
          name: redis
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: "1"
            memory: 1Gi
```

### Сценарий 4: Настройка ServiceMonitor и PodMonitor (Prometheus Operator)

Чтобы Prometheus корректно агрегировал метрики подов StatefulSet с сохранением топологии и имен инстансов, необходимо правильно настроить релейблинг.

#### Вариант А: ServiceMonitor через Headless Service

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: postgres-exporter-sm
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: postgres
  endpoints:
  - port: metrics
    interval: 30s
    scrapeTimeout: 10s
    path: /metrics
    relabelings:
    # Сохранение точного имени пода вместо IP-адреса в лейбле instance
    - sourceLabels: [__meta_kubernetes_pod_name]
      targetLabel: instance
    # Добавление порядкового номера пода для фильтрации в PromQL
    - sourceLabels: [__meta_kubernetes_pod_label_apps_kubernetes_io_pod_index]
      targetLabel: pod_index
```

#### Вариант Б: PodMonitor (Прямой скрапинг без Service)

Если в архитектуре нежелательно добавлять служебный порт метрик в манифест `Service`, применяется `PodMonitor`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: postgres-exporter-pm
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: postgres
  podMetricsEndpoints:
  - port: metrics
    interval: 30s
    scrapeTimeout: 10s
    path: /metrics
    relabelings:
    - sourceLabels: [__meta_kubernetes_pod_name]
      targetLabel: pod
    - sourceLabels: [__meta_kubernetes_pod_node_name]
      targetLabel: node
```

## Операции и команды

Сводка типовых команд системного администратора и SRE для проверки, диагностики и профилирования экспортеров в составе StatefulSet.

| Действие | Команда | Цель / Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка статуса подов** | `kubectl get pods -l app=postgres -o wide` | Проверка готовности подов и распределения по узлам |
| **Проверка логов сайдкара** | `kubectl logs postgres-0 -c postgres-exporter -f` | Мониторинг попыток подключения и ошибок SQL |
| **Чтение метрик локально** | `kubectl exec postgres-0 -c postgres-exporter -- wget -qO- http://127.0.0.1:9187/metrics` | Проверка вывода без настройки port-forward |
| **Port-Forward метрик** | `kubectl port-forward pod/postgres-0 9187:9187` | Доступ к эндпоинту `/metrics` с рабочего места администратора |
| **Проверка эндпоинтов** | `kubectl get endpointslices -l kubernetes.io/service-name=postgres-headless` | Проверка регистрации IP-адресов сайдкаров в сервисе |
| **Проверка таргета в K8s** | `kubectl get servicemonitor postgres-exporter-sm -o yaml` | Проверка лейблов для Prometheus Operator |

### Практическая диагностика через консоль

```bash
# 1. Проброс порта и срез ключевых метрик PostgreSQL
kubectl port-forward pod/postgres-0 9187:9187 &
# → Forwarding from 127.0.0.1:9187 -> 9187

# Проверка базовой доступности БД для экспортера (должно вернуть 1)
curl -s http://127.0.0.1:9187/metrics | grep -E '^pg_up\b'
# → pg_up 1

# Проверка кастомной метрики статуса primary/standby
curl -s http://127.0.0.1:9187/metrics | grep -E '^pg_replication_custom_is_primary\b'
# → pg_replication_custom_is_primary 1

# 2. Проверка задержки репликации на standby-реплике postgres-1
kubectl port-forward pod/postgres-1 9188:9187 &
curl -s http://127.0.0.1:9188/metrics | grep -E '^pg_replication_custom_replication_lag_seconds\b'
# → pg_replication_custom_replication_lag_seconds 0.042

# 3. Диагностика эндпоинтов Headless Service
kubectl get endpoints postgres-headless
# → NAME                ENDPOINTS                                                           AGE
# → postgres-headless   10.244.1.45:5432,10.244.2.19:5432,10.244.1.45:9187 + 2 more...     14d

# 4. Проверка состояния таргетов через Prometheus API (внутри кластера)
kubectl exec -n monitoring deploy/prometheus-k8s -c prometheus -- \
  curl -s http://localhost:9090/api/v1/targets | grep -B 2 -A 5 'postgres-exporter'
# → "health": "up", "scrapeUrl": "http://10.244.1.45:9187/metrics"
```

## Устранение неполадок

### Сводная таблица проблем и решений

| Симптом / Ошибка | Первопричина | Метод диагностики | Инженерное решение |
| :--- | :--- | :--- | :--- |
| `CrashLoopBackOff`: `dial tcp 127.0.0.1:5432: connect: connection refused` | Экспортер запущен в режиме Legacy (`spec.containers`), СУБД еще не стартовала | `kubectl logs <pod> -c <exporter> --previous` | Перевести экспортер в `initContainers` с `restartPolicy: Always` (Native Sidecar) |
| `pq: password authentication failed for user` | Ошибка в Secret или рассинхронизация пароля в СУБД | `kubectl get secret <secret> -o jsonpath='{.data}'` | Проверить base64 секрета; проверить права пользователя `exporter` в СУБД |
| `FATAL: no pg_hba.conf entry for host "127.0.0.1"` | В `pg_hba.conf` запрещено подключение по TCP с localhost | `kubectl exec -it <pod> -c postgres -- cat /var/lib/postgresql/data/pg_hba.conf` | Добавить строку `host all exporter 127.0.0.1/32 scram-sha-256` или `trust` |
| `context deadline exceeded` при скрапинге Prometheus | Медленные кастомные запросы или блокировки системных таблиц | `curl -w "%{time_total}\n" -s http://127.0.0.1:9187/metrics -o /dev/null` | Отключить тяжелые коллекторы; увеличить `scrapeTimeout` в ServiceMonitor до 15–20s |
| Таргеты в Prometheus в статусе `DOWN` | Неверный порт или селектор в ServiceMonitor | `kubectl describe servicemonitor <sm-name>` | Проверить соответствие `endpoints.port` имени порта в Service (`name: metrics`) |
| В Prometheus отсутствуют реплики в стадии восстановления | `Headless Service` исключает не-Ready поды из DNS/Endpoints | `kubectl get endpointslices -l app=postgres` | Выставить `spec.publishNotReadyAddresses: true` в манифесте Headless Service |
| `OOMKilled` сайдкар-контейнера | Экспортер собирает статистику по миллионам таблиц/индексов | `kubectl describe pod <pod>` (код выхода 137) | Исключить сбор статистики по таблицам (`PG_EXPORTER_DISABLE_DEFAULT_METRICS=true`) или поднять Memory Limit |

### Детальные сценарии сбоев

#### Сценарий 1: Зависание скрапинга из-за тяжелых системных представлений

* **Симптом:** В веб-интерфейсе Prometheus цель переходит в статус `DOWN` с сообщением `context deadline exceeded`. Сайдкар потребляет 100% лимита CPU.
* **Причина:** В базе данных с десятками тысяч таблиц, партиций или частыми блокировками стандартный запрос экспортера к `pg_stat_user_tables` или `information_schema.tables` выполняет последовательное сканирование системного каталога, блокируя поток экспортера.
* **Устранение:**
  1. В `postgres_exporter` отключить сбор стандартных метрик таблиц через переменную окружения:
     ```yaml
     env:
     - name: PG_EXPORTER_DISABLE_DEFAULT_METRICS
       value: "true"
     ```
  2. Заменить стандартный сбор целевым ConfigMap с запросами только к критически важным бизнес-схемам (`WHERE schemaname = 'public'`).
  3. В `mysqld_exporter` отключить сканирование схем флагом `--no-collect.info_schema.tables`.

#### Сценарий 2: Потеря видимости подов в процессе восстановления (Blind Spot)

* **Симптом:** При старте нового пода реплики или после сбоя ноды под находится в состоянии `0/2 Ready`. Prometheus перестает скрейпить экспортер именно в тот момент, когда инженеру необходимо наблюдать за ходом наката WAL или клонирования базы.
* **Причина:** Стандартный Kubernetes Service удаляет IP-адрес пода из списка эндпоинтов, если хотя бы один рабочий контейнер не прошел `readinessProbe`.
* **Устранение:** Добавить флаг публикации не готовых адресов в манифест Headless-сервиса:
  ```yaml
  spec:
    clusterIP: None
    publishNotReadyAddresses: true
  ```
  Это заставляет EndpointSlice-контроллер сохранять IP-адрес пода в списке доступных для прямого скрапинга подов Prometheus Operator.

## Лучшие практики

### 1. Соответствие стандартам безопасности (Pod Security Standards)

В средах со строгой изоляцией (On-Premise Enterprise) экспортеры обязаны удовлетворять профилю безопасности **Restricted**:
* Запрет повышения привилегий: `allowPrivilegeEscalation: false`.
* Отказ от привилегий суперпользователя: `runAsNonRoot: true`, явное указание непривилегированного UID (`runAsUser: 65534` — nobody).
* Неизменяемая корневая файловая система: `readOnlyRootFilesystem: true`. Экспортерам не требуется запись на локальный диск.
* Сброс всех Linux capabilities: `capabilities: drop: ["ALL"]`.
* Применение системных профилей Seccomp: `seccompProfile: { type: RuntimeDefault }`.

### 2. Изоляция ресурсов и предотвращение троттлинга

* Экспортеры написаны на компилируемых языках (Go) и потребляют минимум памяти. Однако при резком росте числа соединений к БД или сборе сложных кастомных метрик возможен кратковременный всплеск CPU.
* **Рекомендуемые лимиты:**
  * CPU Request: `50m`, Limit: `150m` (для предотвращения троттлинга CFS при скрапинге).
  * Memory Request: `64Mi`, Limit: `128Mi` (для типовых БД; при >10 000 таблиц увеличьте Limit до `256Mi`).
* Обязательно выставляйте `limits.memory`. Утечка памяти в экспортере не должна приводить к выселению всего пода СУБД по сценарию `Node Allocatable OOM`.

### 3. Оптимизация таймингов скрапинга

* **Интервал опроса (`scrape_interval`):**
  * Для базовой доступности (`pg_up`, `mysql_up`, replication lag) достаточен интервал **30s**.
  * Не используйте агрессивный опрос **5s–10s** для баз данных: каждый запрос экспортера выполняет реальные SQL-запросы в СУБД, создавая паразитную нагрузку на дисковую подсистему и процессор.
* **Таймаут скрапинга (`scrapeTimeout`):**
  * Всегда настраивайте `scrapeTimeout: 10s` (или `15s`), следя за тем, чтобы таймаут был строго меньше `scrape_interval`.

### 4. Ограничение прав пользователя мониторинга

* Никогда не запускайте экспортер под учетной записью суперпользователя СУБД (`postgres`, `root`).
* В PostgreSQL создавайте отдельную роль с минимальными атрибутами:
  ```sql
  CREATE USER postgres_exporter WITH PASSWORD 'password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  GRANT pg_monitor TO postgres_exporter;
  ```
  Встроенная роль `pg_monitor` (доступна с PostgreSQL 10+) предоставляет право безопасного чтения всех представлений мониторинга без доступа к пользовательским таблицам.

## Дополнительная информация

### См. также

* **[StatefulSet: Обзор](./statefulset_overview.md)** — архитектура контроллера StatefulSet и управление подами с состоянием.
* **[StatefulSet: Ключевые концепции](./statefulset_core_concepts.md)** — стабильные сетевые идентификаторы, ControllerRevision и хранилище.
* **[StatefulSet: Лучшие практики](./statefulset_best_practices.md)** — кворум, PDB, Affinity и отказоустойчивость.
* **[StatefulSet: Практическое руководство](./statefulset_practical_guide.md)** — развертывание и траблшутинг кластеров СУБД.
* **[Паттерны Sidecar в Pod](../Pod/pod_sidecar_patterns.md)** — классические паттерны боковых контейнеров в Kubernetes.
* **[Init-контейнеры и Native Sidecars](../Pod/pod_init_containers.md)** — специфика жизненного цикла `restartPolicy: Always`.
* **[Паттерны экспортеров в Kubernetes](../../../Prometheus/Exporters/extensibility/k8s_exporter_patterns.md)** — общие паттерны Deployment, DaemonSet и Sidecar для мониторинга.
* **[Redis Exporter](../../../Prometheus/Exporters/redis_exporter.md)** — параметры запуска и сбора метрик Redis.
* **[PostgreSQL: Мониторинг через Prometheus](../../../Ansible/examples/postgresql_prometheus_monitoring.md)** — детальный разбор метрик `pg_stat_*` и порогов алертинга.
* **[MySQL: Мониторинг](../../../Databases/MySQL/monitoring.md)** — метрики InnoDB и Performance Schema в Prometheus.
