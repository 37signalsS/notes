# Секреты в StatefulSet

**Актуально для:** Kubernetes 1.30–1.34+ (StatefulSet, Secrets, VolumeClaimTemplates, HashiCorp Vault 1.18–1.21 / OpenBao 2.x, External Secrets Operator v0.14+; On-Premise / Bare-Metal)

---

## Определения

**StatefulSet** — специализированный контроллер рабочей нагрузки Kubernetes, предназначенный для управления приложениями с сохранением состояния (Stateful Applications: СУБД, брокеры сообщений, распределенные хранилища). Обеспечивает детерминированные сетевые идентификаторы (`pod-0`, `pod-1`), порядковое масштабирование и выделенные постоянные тома через `volumeClaimTemplates`.

**Секреты в контексте StatefulSet (StatefulSet Secrets)** — конфиденциальные параметры (пароли суперпользователей, учетные записи репликации, межкластерные токены консенсуса, ключи шифрования данных и TLS/mTLS сертификаты), жизненный цикл которых неразрывно связан с персистентным хранилищем и топологией кластера приложения.

**Day 1 vs Day 2 Credentials (Инициализационные против Эксплуатационных)**:
- **Day 1 (Bootstrap / Init):** Секреты первичной инициализации кластера или пустой базы данных (например, `POSTGRES_PASSWORD`, `MYSQL_ROOT_PASSWORD`). Считываются стандартными образами СУБД только один раз — при первом запуске на неинициализированном томе (`emptyDir` или чистый PVC).
- **Day 2 (Operational / Runtime):** Секреты, используемые для текущего обслуживания, межсерверной репликации, клиентских подключений и периодической ротации учетных записей без потери данных и без пересоздания томов.

**Порядковые секреты (Ordinal / Per-Pod Secrets)** — паттерн разделения учетных данных и сертификатов, при котором каждой реплике StatefulSet (`$(POD_NAME)`) предоставляются уникальные секреты (индивидуальные TLS-сертификаты с соответствующими DNS SAN, идентификаторы узлов, закрытые ключи) без создания отдельных StatefulSet под каждый узел.

**Кластерные токены консенсуса (Cluster Consensus & Gossip Secrets)** — общие криптографические ключи или пароли, разделяемые всеми узлами распределенной системы для взаимной аутентификации и синхронизации (например, `keyFile` в MongoDB ReplicaSet, `.erlang.cookie` в RabbitMQ, `requirepass`/`masterauth` в Redis Sentinel/Cluster, gossip encryption key в HashiCorp Consul/Vault Raft).

---

## Основные концепции и архитектура

### Специфика жизненного цикла секретов в Stateful-нагрузках

Работа с секретами в StatefulSet фундаментально отличается от работы в stateless-нагрузках (Deployment/ReplicaSet):

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Жизненный цикл секрета в СУБД                         │
└─────────────────────────────────────────────────────────────────────────────────┘
 [Day 1: Инициализация PVC]
  PVC чистый ──► Entrypoint читает Secret (ENV/Volume) ──► Инициализирует каталог данных
                                                              │
                                                              ▼
                                                   [Пароль записан в системные]
                                                   [каталоги / таблицы СУБД   ]
                                                              │
 [Day 2: Ротация секрета в K8s]                               ▼
  K8s Secret изменен ──► Pod перезапущен ──► Entrypoint видит непустой каталог данных
                                                  │
                                                  ▼
                                       ПЕРЕМЕННЫЕ ИГНОРИРУЮТСЯ!
                                                  │
                     ┌────────────────────────────┴───────────────────────────┐
                     ▼                                                        ▼
         [В K8s Secret: Password_B]                              [На PVC в СУБД: Password_A]
                     ▲                                                        ▲
                     └────────────────────── РАССИНХРОН ──────────────────────┘
                              Клиенты по новому секрету получают:
                         "FATAL: password authentication failed"
```

1. **Дилемма персистентного хранилища (PVC vs Secret):**
   - В Deployment контейнер эфемерный: обновление объекта `Secret` и перезапуск пода гарантируют применение новых учетных данных.
   - В StatefulSet данные хранятся на постоянных дисках (PersistentVolume). Образы СУБД (PostgreSQL, MySQL, MariaDB, MongoDB) при наличии инициализированного каталога данных (`PGDATA`, `/var/lib/mysql`) **пропускают этап инициализации** и игнорируют переменные окружения с новыми паролями.
   - Изменение секрета в Kubernetes без синхронизации с внутренними системными таблицами СУБД (`pg_authid`, `mysql.user`) приводит к критическому рассинхрону.

2. **Границы безопасности памяти и диска (tmpfs vs PVC):**
   - Секреты Kubernetes при монтировании через `volumes[].secret` размещаются исключительно в оперативной памяти хоста через временную файловую систему (`tmpfs`).
   - Запись конфиденциальных данных (паролей, токенов, открытых приватных ключей) напрямую в persistent volume (`/var/lib/mysql`, `/var/lib/postgresql/data`) создает риск компрометации данных при снятии дисковых снимков (CSI VolumeSnapshot) и резервном копировании (Velero, Kasten).

3. **Разделение зон ответственности секретов:**
   В производственной эксплуатации StatefulSet учетные данные разделяются на независимые сущности:
   - **Root / Superuser Secret:** Используется исключительно администраторами и init-скриптами для первичного бутстрапа.
   - **Application User Secret:** Учетные данные пула подключений сервисов приложения с ограниченными правами (DML).
   - **Replication / Cluster Secret:** Системные учетные данные, используемые демонами репликации узлов между собой.
   - **TLS / Node Identity Secret:** Сертификаты и закрытые ключи для шифрования клиентского и межсерверного трафика.

---

### Сравнительный анализ моделей доставки секретов

В On-Premise инфраструктуре выбор модели доставки определяет устойчивость к отказам и безопасность:

| Архитектурная модель | Источник секретов | Механизм обновления | Изоляция в ОС (tmpfs) | Ограничения и риски в StatefulSet | Сложность (Ops) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Static Secret (ENV)** | `Secret.data` / `secretKeyRef` | **Нет** (требует полного рестарта пода) | **Нет** (видны в `/proc/$PID/environ`, crash dumps) | Новые значения не применяются к инициализированному PVC; утечка в логи | Низкая |
| **Static Secret (Volume)** | `Secret.data` / `volumes[].secret` | **Да** (атомарное обновление симлинков `..data`) | **Да** (монтируется в память хоста как `tmpfs`) | СУБД должна поддерживать горячую перезагрузку конфигурации (SIGHUP, SQL reload) | Низкая |
| **Vault / OpenBao Agent** | HashiCorp Vault / OpenBao | **Да** (Agent рендерит файл и шлет сигнал процессу) | **Да** (shared memory emptyDir тома) | Требует sidecar-контейнера на каждый под; оверхед по памяти и CPU | Средняя |
| **External Secrets (ESO)** | Внешний On-Prem Vault / Git / KMS | **Да** (`refreshInterval` синхронизирует K8s Secret) | **Да** (при монтировании сгенерированного Secret в Volume) | Задержка синхронизации; необходимость следить за жизненным циклом Secret | Средняя |
| **Secrets Store CSI Driver** | Vault / Local CSI Provider | **Да** (при включенном `enable-secret-rotation`) | **Да** (прямой tmpfs mount в контейнер, без Secret в etcd) | Том монтируется только при старте пода; проблемы при сетевой изоляции узла | Высокая |

---

### Анатомия обновления StatefulSet и порядок рестарта подов

По умолчанию контроллер StatefulSet использует стратегию обновления `RollingUpdate` с последовательным перезапуском подов в **обратном порядке** — от старшего индекса к нулевому:

$$\text{Pod}_{(N-1)} \longrightarrow \text{Pod}_{(N-2)} \dots \longrightarrow \text{Pod}_0$$

```
   Ротация секрета репликации при наивном "rollout restart":

   [db-2: Replica]                  [db-1: Replica]                  [db-0: Master/Primary]
          │                                │                                    │
   1. Перезапуск                    Ждет очереди                         Работает со СТАРЫМ
   2. Читает НОВЫЙ пароль           Работает со СТАРЫМ                   паролем репликации
   3. Коннект к db-0                паролем                              
          │                                │                                    │
          ▼                                │                                    │
   ❌ FATAL: Password auth failed          │                                    │
   (CrashLoopBackOff!)                     │                                    │
```

- Если обновить пароль репликации в общем объекте `Secret` и вызвать `kubectl rollout restart statefulset/db`, первой перезапустится реплика `db-2`.
- `db-2` попытается подключиться к текущему мастеру `db-0` с **новым** паролем.
- Мастер `db-0` еще не перезапущен и принимает аутентификацию только по **старому** паролю.
- Репликация разрывается, поды переходят в состояние `CrashLoopBackOff` или десинхронизации, нарушая кворум высокой доступности.
- **Решение:** Использование двухфазной ротации учетных данных и параметра `spec.updateStrategy.rollingUpdate.partition` (см. Сценарий 6).

---

### Безопасность файловых систем и POSIX-права

Многие системные службы и СУБД предъявляют жесткие требования к правам доступа файлов аутентификации:
- **PostgreSQL (`.pgpass`, приватные ключи SSL):** Требует права не более `0600` (чтение/запись только владельцем) или `0400` (только чтение владельцем). Если права равны `0644`, клиент psql выдает ошибку: `WARNING: password file ".pgpass" has group or world access; permissions should be u=rw (0600) or less` и игнорирует файл.
- **MongoDB (`keyFile`):** Требует права строго `0400` или `0600` и соответствие владельца процесса `mongodb`. Иначе старт аварийно завершается: `permissions on /etc/secrets/mongo-keyfile are too open`.
- **RabbitMQ (`.erlang.cookie`):** Требует права строго `0400` и UID владельца демона `rabbitmq`.

**Правило бесконфликтной настройки POSIX-прав в Kubernetes:**
1. Если контейнер запускается от non-root пользователя (например, UID `999` для postgres или `1001` для bitnami), монтирование секрета с `defaultMode: 0400` без настройки `fsGroup` приведет к ошибке `Permission denied`, так как по умолчанию владельцем файлов тома Secret является `root` (`UID 0`).
2. Для предоставления доступа процессу без запуска от root используйте:
   - `defaultMode: 0440` (чтение владельцем и группой) совместно с `fsGroup: <GID>` в `pod.spec.securityContext`.
   - Либо инициализационный контейнер (InitContainer), копирующий секрет в локальный том `emptyDir (medium: Memory)` с выполнением `chmod 0400` и `chown` под конкретного пользователя.

---

## Практические сценарии и конфигурации

### Сценарий 1: PostgreSQL StatefulSet с разделением Admin, Replication и TLS секретов (On-Premise Production)

Паттерн промышленного развертывания PostgreSQL в bare-metal окружении:
1. Административный пароль суперпользователя и пароль репликации разделены по разным ключам.
2. Секреты монтируются через защищенный Volume (`tmpfs`) с правами `0400`.
3. Контейнер запускается от непривилегированного пользователя `postgres` (UID 999).
4. Объект Secret помечен как `immutable: true` для предотвращения случайной модификации.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-cluster-secrets-v1
  namespace: database
type: Opaque
immutable: true
stringData:
  # Пароль суперпользователя для первичной инициализации
  postgres-root-password: "K8s#SuperSecurePostgres2026!Root"
  # Системный пароль для потоковой репликации (streaming replication)
  replication-password: "Repl#PassToken2026_StreamingSync"
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-headless
  namespace: database
  labels:
    app: postgres
spec:
  clusterIP: None
  ports:
  - port: 5432
    name: postgresql
  selector:
    app: postgres
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: database
spec:
  serviceName: "postgres-headless"
  replicas: 3
  podManagementPolicy: OrderedReady
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        runAsGroup: 999
        fsGroup: 999
        fsGroupChangePolicy: "OnRootMismatch"
      containers:
      - name: postgresql
        image: postgres:16.8-alpine
        imagePullPolicy: IfNotPresent
        env:
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        # Передаем пароль суперпользователя через чтение файла секрета
        - name: POSTGRES_PASSWORD_FILE
          value: /etc/secrets/auth/postgres-root-password
        - name: PGUSER
          value: "postgres"
        ports:
        - containerPort: 5432
          name: postgresql
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
        volumeMounts:
        - name: pgdata
          mountPath: /var/lib/postgresql/data
        # Монтирование тома с паролями в память (tmpfs)
        - name: auth-secrets
          mountPath: /etc/secrets/auth
          readOnly: true
        # Монтирование файла паролей репликации для pg_basebackup / primary_conninfo
        - name: pgpass-secret
          mountPath: /etc/secrets/pgpass
          readOnly: true
      volumes:
      - name: auth-secrets
        secret:
          secretName: postgres-cluster-secrets-v1
          defaultMode: 0440
          items:
          - key: postgres-root-password
            path: postgres-root-password
      - name: pgpass-secret
        secret:
          secretName: postgres-cluster-secrets-v1
          defaultMode: 0400
          items:
          - key: replication-password
            path: .pgpass
  volumeClaimTemplates:
  - metadata:
      name: pgdata
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "local-nvme"
      resources:
        requests:
          storage: 50Gi
```

---

### Сценарий 2: Кластерные ключи с жесткими правами доступа — MongoDB Replica Set (паттерн keyFile)

MongoDB требует наличия секретного файла `keyFile` с минимальной длиной 6 символов base64, правами доступа `0400` и принадлежностью процессу `mongodb` (UID 999). Если смонтировать стандартный Secret через `defaultMode: 0400`, но без `fsGroup`, MongoDB упадет с ошибкой доступа.

Решение: использование `emptyDir` в памяти с init-контейнером для копирования и безопасной установки прав `0400` от имени целевого пользователя.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mongodb-cluster-key
  namespace: database
type: Opaque
stringData:
  # 756-битный псевдослучайный base64 ключ для аутентификации узлов
  mongo-keyfile: "X49vL7K9mQ2wE5rT8yU1iO3pA6sD0fG4hJ7kL2zX5cV8bN1mQ="
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mongodb
  namespace: database
spec:
  serviceName: "mongodb-headless"
  replicas: 3
  selector:
    matchLabels:
      app: mongodb
  template:
    metadata:
      labels:
        app: mongodb
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        runAsGroup: 999
        fsGroup: 999
      # InitContainer копирует ключ в локальный in-memory том и ставит строгие права 0400
      initContainers:
      - name: setup-keyfile
        image: busybox:1.36
        securityContext:
          runAsNonRoot: true
          runAsUser: 999
          runAsGroup: 999
        command:
        - sh
        - -c
        - |
          cp /raw-secrets/mongo-keyfile /shared-key/keyfile
          chmod 0400 /shared-key/keyfile
        volumeMounts:
        - name: raw-secret-volume
          mountPath: /raw-secrets
          readOnly: true
        - name: shared-key-volume
          mountPath: /shared-key
      containers:
      - name: mongodb
        image: mongo:7.0.14
        command:
        - mongod
        - "--replSet"
        - "rs0"
        - "--bind_ip_all"
        - "--keyFile"
        - "/etc/mongodb-key/keyfile"
        volumeMounts:
        - name: shared-key-volume
          mountPath: /etc/mongodb-key
          readOnly: true
        - name: mongodata
          mountPath: /data/db
      volumes:
      # Исходный секрет из etcd
      - name: raw-secret-volume
        secret:
          secretName: mongodb-cluster-key
          defaultMode: 0440
      # Выделенный in-memory tmpfs том для подготовленного файла ключа
      - name: shared-key-volume
        emptyDir:
          medium: Memory
  volumeClaimTemplates:
  - metadata:
      name: mongodata
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "local-nvme"
      resources:
        requests:
          storage: 100Gi
```

---

### Сценарий 3: Порядковые секреты и уникальные TLS-сертификаты реплик (Downward API + Init Container)

Когда каждому поду StatefulSet требуется свой собственный TLS-сертификат (с конкретным SAN: `db-0.db-headless`, `db-1.db-headless`, `db-2.db-headless`), создание N отдельных StatefulSet нарушает архитектуру Kubernetes.

Решение: единый Secret хранит связки сертификатов для каждого узла. Init-контейнер через **Downward API** считывает имя текущего пода (`metadata.name`), извлекает порядковый номер (`0`, `1`, `2`) и копирует в рабочий том нужный сертификат.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-tls-bundle
  namespace: database
type: Opaque
stringData:
  db-0.crt: |
    -----BEGIN CERTIFICATE-----
    MIID... (Сертификат для db-0.db-headless.database.svc.cluster.local)
    -----END CERTIFICATE-----
  db-0.key: |
    -----BEGIN RSA PRIVATE KEY-----
    MIIE...
    -----END RSA PRIVATE KEY-----
  db-1.crt: |
    -----BEGIN CERTIFICATE-----
    MIID... (Сертификат для db-1.db-headless.database.svc.cluster.local)
    -----END CERTIFICATE-----
  db-1.key: |
    -----BEGIN RSA PRIVATE KEY-----
    MIIE...
    -----END RSA PRIVATE KEY-----
  ca.crt: |
    -----BEGIN CERTIFICATE-----
    MIID... (Root CA сертификат On-Premise инфраструктуры)
    -----END CERTIFICATE-----
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db
  namespace: database
spec:
  serviceName: "db-headless"
  replicas: 2
  selector:
    matchLabels:
      app: db
  template:
    metadata:
      labels:
        app: db
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      initContainers:
      - name: extract-node-tls
        image: busybox:1.36
        env:
        # Downward API: инжекция имени конкретного пода (db-0, db-1)
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        command:
        - sh
        - -c
        - |
          echo "Инициализация TLS для ноды: ${POD_NAME}"
          cp /etc/tls-bundle/${POD_NAME}.crt /etc/node-tls/tls.crt
          cp /etc/tls-bundle/${POD_NAME}.key /etc/node-tls/tls.key
          cp /etc/tls-bundle/ca.crt /etc/node-tls/ca.crt
          chmod 0400 /etc/node-tls/tls.key
          chmod 0444 /etc/node-tls/tls.crt /etc/node-tls/ca.crt
        volumeMounts:
        - name: tls-bundle-volume
          mountPath: /etc/tls-bundle
          readOnly: true
        - name: active-tls
          mountPath: /etc/node-tls
      containers:
      - name: database-node
        image: my-onprem-registry.local/infra/secure-db:v2.4
        volumeMounts:
        - name: active-tls
          mountPath: /etc/ssl/certs/db
          readOnly: true
      volumes:
      - name: tls-bundle-volume
        secret:
          secretName: cluster-tls-bundle
          defaultMode: 0440
      - name: active-tls
        emptyDir:
          medium: Memory
```

---

### Сценарий 4: Динамические секреты через HashiCorp Vault / OpenBao Agent Sidecar (On-Premise)

Для исключения хранения статических паролей в `etcd` используется Vault Agent Sidecar с методом аутентификации `kubernetes` (по JWT-токену ServiceAccount). Vault генерирует уникальные динамические учетные данные базы данных с ограниченным TTL и автоматически обновляет их.

**Конфигурация роли и движка в On-Premise Vault:**

```bash
# 1. Включение движка базы данных
vault secrets enable database
# → Success! Enabled the database secrets engine at: database/

# 2. Подключение Vault к внутреннему кластеру PostgreSQL
vault write database/config/onprem-postgres \
  plugin_name=postgresql-database-plugin \
  allowed_roles="statefulset-app-role" \
  connection_url="postgresql://{{username}}:{{password}}@postgres-headless.database.svc.cluster.local:5432/appdb?sslmode=disable" \
  username="vault_admin" \
  password="AdminVaultSecretPassword2026!"
# → Success! Data written to: database/config/onprem-postgres

# 3. Создание роли генерации динамических учетных данных с TTL 2 часа
vault write database/roles/statefulset-app-role \
  db_name=onprem-postgres \
  creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' INHERIT; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
  default_ttl="2h" \
  max_ttl="24h"
# → Success! Data written to: database/roles/statefulset-app-role
```

**Манифест StatefulSet с аннотациями Vault Agent:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: stateful-worker
  namespace: database
spec:
  serviceName: "stateful-worker-headless"
  replicas: 3
  selector:
    matchLabels:
      app: stateful-worker
  template:
    metadata:
      labels:
        app: stateful-worker
      annotations:
        # Включение инъектора агента
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "statefulset-app-role"
        vault.hashicorp.com/agent-pre-populate-only: "false"
        # Путь запроса динамических credentials
        vault.hashicorp.com/agent-inject-secret-db-creds.txt: "database/creds/statefulset-app-role"
        # Шаблонизация файла учетных данных в формате key=value
        vault.hashicorp.com/agent-inject-template-db-creds.txt: |
          {{- with secret "database/creds/statefulset-app-role" -}}
          DB_USER={{ .Data.username }}
          DB_PASSWORD={{ .Data.password }}
          LEASE_ID={{ .LeaseID }}
          {{- end }}
        # Команда обновления приложения при ротации аренды Vault (SIGHUP процессу)
        vault.hashicorp.com/agent-inject-command-db-creds.txt: "kill -HUP 1"
    spec:
      serviceAccountName: statefulset-vault-sa
      containers:
      - name: worker
        image: my-onprem-registry.local/apps/worker:v1.12
        command:
        - sh
        - -c
        - |
          # Ожидание инициализации файла секрета агентом Vault
          while [ ! -f /vault/secrets/db-creds.txt ]; do sleep 1; done
          exec /app/start-worker --config=/vault/secrets/db-creds.txt
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
```

---

### Сценарий 5: Синхронизация секретов через External Secrets Operator (ESO) с On-Premise хранилищем

В закрытых контурах без прямого сетевого доступа подов в Vault используется External Secrets Operator (ESO). Контроллер ESO синхронизирует секреты из Vault в нативные объекты `Secret`, минимизируя сложность подов.

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onprem-vault-backend
spec:
  provider:
    vault:
      server: "https://vault.internal.corp:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "eso-cluster-sync"
          serviceAccountRef:
            name: eso-sync-sa
            namespace: external-secrets
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: redis-cluster-auth
  namespace: cache
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: onprem-vault-backend
    kind: ClusterSecretStore
  target:
    name: redis-auth-secret
    creationPolicy: Owner
    template:
      type: Opaque
      metadata:
        labels:
          app.kubernetes.io/managed-by: external-secrets
  data:
  - secretKey: requirepass
    remoteRef:
      key: onprem/cache/redis
      property: master-password
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-node
  namespace: cache
spec:
  serviceName: "redis-headless"
  replicas: 3
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7.2.5-alpine
        command:
        - sh
        - -c
        - |
          AUTH_PASS=$(cat /etc/redis-secrets/requirepass)
          exec redis-server --requirepass "$AUTH_PASS" --masterauth "$AUTH_PASS"
        volumeMounts:
        - name: auth-volume
          mountPath: /etc/redis-secrets
          readOnly: true
      volumes:
      - name: auth-volume
        secret:
          secretName: redis-auth-secret
          defaultMode: 0400
```

---

### Сценарий 6: SRE Runbook: Безопасная двухфазная ротация паролей репликации без простоя (Zero-Downtime Rotation)

Для предотвращения десинхронизации узлов при ротации общего пароля репликации применяется строгий пошаговый плейбук.

#### Фаза 1: Подготовка СУБД (Dual-Auth / Добавление временного пользователя)

Администратор подключается к действующему Master узлу (`postgres-0`) и добавляет временную учетную запись репликации:

```sql
-- Подключение к Master
CREATE USER replicator_v2 WITH REPLICATION ENCRYPTED PASSWORD 'NewReplicationToken2026!';
GRANT CONNECT ON DATABASE postgres TO replicator_v2;
```

#### Фаза 2: Создание версионированного секрета в Kubernetes

```bash
kubectl create secret generic postgres-cluster-secrets-v2 \
  --namespace database \
  --from-literal=replication-password='NewReplicationToken2026!' \
  --dry-run=client -o yaml | kubectl apply -f -
# → secret/postgres-cluster-secrets-v2 created

# Фиксация неизменяемости нового секрета
kubectl patch secret postgres-cluster-secrets-v2 -n database -p '{"immutable": true}'
# → secret/postgres-cluster-secrets-v2 patched
```

#### Фаза 3: Контролируемый канареечный роллоут через Partition

Для предотвращения одновременного рестарта всех узлов фиксируем `partition: 2` (для кластера из 3 реплик: `0`, `1`, `2`). Обновится только под `postgres-2`.

```bash
# 1. Установка partition на старший индекс (обновление затронет только индекс >= 2)
kubectl patch statefulset postgres -n database -p '
spec:
  updateStrategy:
    rollingUpdate:
      partition: 2
  template:
    spec:
      volumes:
      - name: pgpass-secret
        secret:
          secretName: postgres-cluster-secrets-v2
'
# → statefulset.apps/postgres patched

# 2. Контроль обновления реплики postgres-2
kubectl rollout status statefulset/postgres -n database
# → Waiting for partitioned roll out to finish: 1 out of 3 new pods have been updated...

# 3. Проверка статуса потоковой репликации на Master узле
kubectl exec -n database postgres-0 -c postgresql -- psql -U postgres -c "SELECT client_addr, state, sync_state FROM pg_stat_replication;"
# →  client_addr  |   state   | sync_state 
# → ──────────────┼───────────┼────────────
# →  10.244.2.14  | streaming | async      (postgres-1: старый пароль)
# →  10.244.3.22  | streaming | async      (postgres-2: успешно подключен по v2!)

# 4. Сдвиг partition на 1 для обновления второй реплики
kubectl patch statefulset postgres -n database -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":1}}}}'
# → statefulset.apps/postgres patched
kubectl rollout status statefulset/postgres -n database

# 5. Снятие partition до 0 (обновление Primary узла postgres-0)
kubectl patch statefulset postgres -n database -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
# → statefulset.apps/postgres patched
kubectl rollout status statefulset/postgres -n database
# → statefulset rolling update complete 3 pods at revision postgres-68894dfc4...
```

#### Фаза 4: Очистка старых учетных записей

После успешного перевода всех реплик на `replicator_v2`:
```sql
DROP USER replicator_v1;
```

---

## Операции и команды управления

### Инспекция привязок секретов в StatefulSet

```bash
# Проверка всех томов и переменных StatefulSet, использующих секреты
kubectl get statefulset postgres -n database -o json | jq -r '
  "Тома (Volumes):",
  (.spec.template.spec.volumes[]? | select(.secret != null) | "  - \(.name): secretName=\(.secret.secretName) defaultMode=\(.secret.defaultMode // "default")"),
  "Переменные окружения (Env):",
  (.spec.template.spec.containers[].env[]? | select(.valueFrom.secretKeyRef != null) | "  - \(.name): secret=\(.valueFrom.secretKeyRef.name) key=\(.valueFrom.secretKeyRef.key)")'
# → Тома (Volumes):
# →   - auth-secrets: secretName=postgres-cluster-secrets-v1 defaultMode=288
# →   - pgpass-secret: secretName=postgres-cluster-secrets-v1 defaultMode=256
# → Переменные окружения (Env):
# →   (пусто, переменные окружения не используются - стандарт безопасности соблюден)
```

### Верификация POSIX-прав и файловой системы tmpfs

```bash
# Проверка типа файловой системы смонтированного секрета (должен быть tmpfs)
kubectl exec -it -n database postgres-0 -c postgresql -- df -T /etc/secrets/auth
# → Filesystem           Type       1K-blocks      Used Available Use% Mounted on
# → tmpfs                tmpfs        1632420         4   1632416   1% /etc/secrets/auth

# Проверка точных POSIX-прав смонтированного файла секрета (.pgpass)
kubectl exec -it -n database postgres-0 -c postgresql -- ls -la /etc/secrets/pgpass/
# → total 0
# → drwxr-xr-x    2 root     root            60 Oct 17 22:00 .
# → drwxr-xr-x    3 root     root            60 Oct 17 22:00 ..
# → lrwxrwxrwx    1 root     root            14 Oct 17 22:00 .pgpass -> ..data/.pgpass

kubectl exec -it -n database postgres-0 -c postgresql -- ls -lL /etc/secrets/pgpass/.pgpass
# → -r--------    1 postgres postgres        42 Oct 17 22:00 /etc/secrets/pgpass/.pgpass
```

### Мониторинг синхронизации External Secrets Operator

```bash
# Проверка статуса ExternalSecret для StatefulSet
kubectl get externalsecret redis-cluster-auth -n cache
# → NAME                 STORE                  STORE-TYPE           READY   STATUS         AGE
# → redis-cluster-auth   onprem-vault-backend   ClusterSecretStore   True    SecretSynced   42m

# Детальная проверка условий синхронизации
kubectl get externalsecret redis-cluster-auth -n cache -o jsonpath='{.status.conditions[0]}' | jq .
# → {
# →   "lastTransitionTime": "2026-10-17T21:45:10Z",
# →   "message": "Secret was subbed in and matches remote provider",
# →   "reason": "SecretSynced",
# →   "status": "True",
# →   "type": "Ready"
# → }
```

---

## Диагностика и устранение неполадок

### Сводная матрица инцидентов

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| `FATAL: password authentication failed for user` после обновления Secret | **Проблема Day 2:** СУБД считывает пароль из ENV только при инициализации пустого тома | Сравнить пароль в `Secret` и в системных таблицах СУБД | Выполнить `ALTER USER` внутри СУБД, приведя пароль в соответствие с новым Secret |
| `permissions on /etc/... are too open` (MongoDB / PostgreSQL) | `defaultMode` тома выставлен в `0644` (доступно для group/world) | Проверить права: `ls -lL <mountPath>` | Выставить `defaultMode: 0400` в секции `volumes[].secret` манифеста |
| `CrashLoopBackOff` с `Permission denied` при чтении файла секрета | Секрет смонтирован с `0400` (владелец root), а контейнер запущен от non-root без `fsGroup` | `id` процесса в контейнере; `ls -ld <path>` | Указать `fsGroup: <GID>` в `securityContext` пода и `defaultMode: 0440` |
| Разрыв репликации и десинхронизация кластера при `rollout restart` | Реплики обновились раньше Master узла и пытаются подключиться с новым паролем к старому Master | Проверить логи реплики: `kubectl logs <pod-replica>` | Использовать двухфазную ротацию и `partition` (Сценарий 6) |
| Восстановленный из бэкапа под не может подключиться к данным | **DR Mismatch:** PVC восстановлен из старого snapshot, а Secret сгенерирован заново | Проверить дату снимка PVC и хеш секрета | Восстанавливать объект Secret из той же резервной копии, что и PVC |

---

### Детальный разбор типовых инцидентов

#### Инцидент 1: Рассинхронизация Day 2 учетных данных (Day 1 vs Day 2 Drift)

**Симптом:** Администратор изменил пароль в Secret `postgres-credentials` и перезапустил StatefulSet командой `kubectl rollout restart statefulset/postgres`. После перезапуска приложения получают ошибку `FATAL: password authentication failed for user "postgres"`.

**Диагностика:**
```bash
# 1. Проверка текущего пароля в Kubernetes Secret
kubectl get secret postgres-credentials -n database -o jsonpath='{.data.password}' | base64 -d
# → NewSecurePassword2026!

# 2. Попытка подключения к pod-0 с новым паролем
kubectl exec -it -n database postgres-0 -- psql -U postgres -d postgres -c "\conninfo"
# → psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: FATAL: password authentication failed for user "postgres"

# 3. Проверка даты инициализации каталога данных на PVC
kubectl exec -it -n database postgres-0 -- ls -ld /var/lib/postgresql/data/pgdata/PG_VERSION
# → -rw------- 1 postgres postgres 3 Jan 15 2024 /var/lib/postgresql/data/pgdata/PG_VERSION
# ВЫВОД: Каталог PGDATA существует с 2024 года. Entrypoint проигнорировал POSTGRES_PASSWORD при старте!
```

**Решение:**
Подключиться к СУБД с доверенного локального сокета (`local trust` / `peer authentication`) и актуализировать пароль вручную:
```bash
kubectl exec -it -n database postgres-0 -- psql -U postgres -h /var/run/postgresql -c \
  "ALTER USER postgres WITH PASSWORD 'NewSecurePassword2026!';"
# → ALTER ROLE
```

---

#### Инцидент 2: Фатальная ошибка прав доступа к файлу ключа (0644 vs 0400)

**Симптом:** Pod MongoDB падает в `CrashLoopBackOff`. В логах контейнера сообщение:
`permissions on /etc/mongodb-key/keyfile are too open, expected 0400 or 0600, found 0644`.

**Диагностика:**
```bash
kubectl logs -n database mongodb-0
# → 2026-10-17T22:05:12.112+0000 F SECURITY [main] permissions on /etc/mongodb-key/keyfile are too open, expected 0400 or 0600, found 0644
# → 2026-10-17T22:05:12.113+0000 F -        [main] Fatal Assertion 28620 at src/mongo/util/password.cpp 123
```

**Решение:**
В манифесте StatefulSet в блоке `volumes[].secret` добавить директиву `defaultMode: 0400` (десятичное значение `256`):
```yaml
volumes:
- name: keyfile-volume
  secret:
    secretName: mongodb-cluster-key
    defaultMode: 0400 # octal 0400 -> r--------
```

---

#### Инцидент 3: Несоответствие учетных данных при восстановлении после аварии (Disaster Recovery Mismatch)

**Симптом:** Кластер восстанавливается из резервной копии Velero/VolumeSnapshot. PVC успешно смонтирован к новому StatefulSet, но приложению не удается залогиниться.

**Диагностика:**
1. GitOps-пайплайн при развертывании в новом namespace сгенерировал случайный пароль для Secret.
2. Но на персистентном диске (PVC) таблица пользователей содержит хеш пароля, зафиксированный в момент создания снимка 3 дня назад.

**SRE-стандарт предотвращения:**
1. Не генерировать случайные пароли в GitOps-пайплайнах для StatefulSet без фиксации в хранилище Vault/OpenBao.
2. Включать объекты `Secret` в одну резервную группу (Backup Resource Group) с `PersistentVolumeClaim`:
```bash
# Команда создания согласованного бэкапа PVC и Secrets в Velero
velero backup create db-dr-backup \
  --include-namespaces database \
  --include-resources statefulsets,persistentvolumeclaims,secrets,configmaps
# → Backup request "db-dr-backup" submitted successfully.
```

---

## Лучшие практики (Best Practices)

1. **Отказ от переменных окружения для эксплуатационных паролей:**
   Никогда не передавайте пароли СУБД через `env` или `envFrom`. Переменные окружения сохраняются в таблице процессов ядра `/proc/$PID/environ`, попадают в логи оркестратора и crash dumps. Используйте монтирование томов (`tmpfs`) через директиву `readOnly: true`.

2. **Использование неизменяемых секретов (`immutable: true`):**
   Фиксируйте секреты баз данных как `immutable: true`. Это защищает кластер от непреднамеренного повреждения конфигурации при массовых применениях `kubectl apply` и снимает нагрузку на `kube-apiserver` (kubelet прекращает опрос informer по данным объектам).

3. **Версионирование секретов при обновлении:**
   Вместо изменения данных в существующем объекте `Secret` создавайте новый объект с суффиксом ревизии (`postgres-secrets-v2`), обновляйте манифест StatefulSet и запускайте управляемый `RollingUpdate`.

4. **Запуск от non-root пользователей с фиксацией fsGroup:**
   Конфигурируйте `pod.spec.securityContext` с явным указанием `runAsNonRoot: true`, `runAsUser: <UID>` и `fsGroup: <GID>`. Для монтируемых секретов задавайте `defaultMode: 0440`, что гарантирует чтение файлов процессом без запуска под `root`.

5. **Изоляция секретов от постоянных томов (PVC):**
   Не храните статические конфигурационные файлы с паролями на персистентных томах. Все конфиденциальные файлы должны монтироваться из томов памяти (`tmpfs`), чтобы они не попадали в снимки дисков и бэкапы хранилища.

6. **Управление ротацией через `spec.updateStrategy.rollingUpdate.partition`:**
   При обновлении репликационных паролей и межсерверных токенов никогда не выполняйте слепой перезапуск. Используйте параметр `partition` для канареечного обновления реплик перед переключением роли Master/Leader.

7. **Маскирование учетных данных в InitContainers:**
   В скриптах инициализации отключайте трассировку команд (`set +x`) перед обращением к секретам, чтобы токены и пароли не попали в стандартный вывод `stdout/stderr` и систему агрегации логов.

---

## Дополнительная информация

### Связь с компонентами распределенных систем

- **PostgreSQL:** Поддерживает указание файла паролей через параметр подключения `passfile` (по умолчанию `~/.pgpass`), что исключает передачу учетных данных в командной строке.
- **MySQL / MariaDB:** Используйте файл конфигурации `.my.cnf`, смонтированный из Secret в защищенный каталог, вместо передачи пароля через флаг `-p`.
- **Redis:** Параметры `requirepass` (пароль для входящих клиентов) и `masterauth` (пароль реплики для подключения к мастеру) должны быть идентичны на всех узлах одного кластера/Sentinel.
- **MongoDB:** Директива `security.keyFile` в `mongod.conf` включает аутентификацию между пирами ReplicaSet и требует прав строго `0400` или `0600`.
- **RabbitMQ:** Параметр межсерверной аутентификации кластера задается через файл `.erlang.cookie` в домашней директории демона (права строго `0400`).

### Смотрите также

- [Основы Secret](secrets_basics.md) — базовые типы, кодирование и жизненный цикл.
- [Использование Secret](using_secrets.md) — механизмы монтирования томов и projected volumes.
- [Безопасность Secret](security.md) — hardening, RBAC, аудит и шифрование в etcd.
- [Внешние менеджеры](external_managers.md) — интеграция с External Secrets Operator (ESO) и Secrets Store CSI Driver.
- [Хранение секретов в etcd](etcd_storage.md) — конфигурация шифрования данных на уровне хранилища кластера.
- [Интеграция Vault с Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md) — настройка HashiCorp Vault / OpenBao, Kubernetes Auth и Vault Agent Injector.
- [StatefulSet: обзор](../../Base/StatefulSet/statefulset_overview.md) — базовые концепции и архитектура StatefulSet.
- [StatefulSet: практическое руководство](../../Base/StatefulSet/statefulset_practical_guide.md) — типовые сценарии развертывания баз данных.
- [StatefulSet: лучшие практики](../../Base/StatefulSet/statefulset_best_practices.md) — эксплуатационные стандарты высокой доступности.
