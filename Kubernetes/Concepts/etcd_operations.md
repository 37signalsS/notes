# etcd: практические сценарии и обслуживание в Kubernetes

**Актуально для:** etcd 3.5.x / 3.6.x, Kubernetes 1.30+

## Определения

*   **`etcd`** — распределенное транзакционное хранилище ключей и значений с поддержкой версионирования (MVCC) и алгоритма консенсуса Raft. Является единственным хранилищем состояния кластера Kubernetes.
*   **`etcdctl`** — официальная CLI-утилита (gRPC-клиент) для управления запущенным кластером etcd (online-операции: чтение и запись ключей, проверка состояния endpoint, дефрагментация, добавление/удаление членов, снятие снапшотов).
*   **`etcdutl`** — специализированная CLI-утилита для прямого offline-администрирования файлов базы данных BoltDB без подключения к gRPC API (проверка целостности файла снапшота, восстановление данных, локальная дефрагментация файла).
*   **Префикс `/registry`** — корневой иерархический путь в etcd, в котором `kube-apiserver` размещает все сериализованные объекты API кластера Kubernetes.
*   **MVCC (Multi-Version Concurrency Control)** — механизм управления параллельным доступом, при котором изменения создают новые ревизии ключей без перезаписи старых, что обеспечивает неизменяемость истории для механизмов Watch.
*   **Compaction (Компакция)** — логическая очистка устаревших ревизий ключей до заданной ревизии в памяти и файле BoltDB. Выполняется сервером или API-сервером, но не возвращает дисковое пространство операционной системе.
*   **Defragmentation (Дефрагментация)** — физическое сжатие файла базы данных BoltDB с высвобождением неиспользуемых страниц файловой системе хоста.
*   **Raft Quorum** — необходимое большинство голосующих узлов для фиксации записей и выбора лидера ($Q = \lfloor N/2 \rfloor + 1$).
*   **Learner Node** — неголосующий член кластера etcd, который асинхронно реплицирует лог Raft и данные, не участвуя в подсчете кворума, до момента его перевода в полноправные члены командой `member promote`.
*   **Alarm `NOSPACE`** — аварийный статус etcd, активирующийся при превышении квоты размера базы данных (`--quota-backend-bytes`). Переводит кластер в режим "только чтение" (read-only) для предотвращения повреждения базы данных.

---

## Архитектура и модель доступа

### Взаимодействие с Control Plane

В архитектуре Kubernetes `kube-apiserver` является **единственным компонентом**, имеющим сетевой и криптографический доступ к etcd. Планировщик (`kube-scheduler`), менеджер контроллеров (`kube-controller-manager`), сетевой плагин и узловые агенты (`kubelet`) работают с состоянием исключительно через HTTP/gRPC интерфейсы API-сервера.

```text
+---------------------+     +--------------------------+
|   kube-scheduler    |     | kube-controller-manager  |
+----------+----------+     +------------+-------------+
           |                             |
           +--------------+--------------+
                          | HTTPS REST API
                          v
               +----------------------+
               |    kube-apiserver    | (валидация, аутентификация, admission)
               +----------+-----------+
                          | gRPC + mTLS (порт 2379)
                          v
         +---------------------------------+
         |       etcd Cluster (Raft)       |
         |  +---------+ +---------+ +----+ |
         |  | Node 1  | | Node 2  | | .. | |
         |  +---------+ +---------+ +----+ |
         +---------------------------------+
```

**Преимущества архитектурной изоляции:**
*   Централизованная аутентификация и RBAC-авторизация запросов до момента их передачи в хранилище.
*   Сквозная валидация схемы данных и применение мутирующих/валидирующих вебхуков.
*   Оптимистическая блокировка через сопоставление `resourceVersion` (соответствует `modRevision` в etcd) для исключения race conditions.
*   Кэширование потоков чтения через Watch Cache внутри `kube-apiserver`, что защищает etcd от избыточных `LIST`-запросов.

### Топологии развертывания

*   **Stacked etcd (Совмещенный):** etcd запускается в виде статического пода на каждом узле Control Plane под управлением локального `kubelet`. Стандартный подход в `kubeadm`.
    *   *Плюсы:* Минимальные затраты оборудования, автоматизированное создание манифестов и сертификатов.
    *   *Минусы:* Конкуренция за дисковый I/O и память с `kube-apiserver` и контейнерным рантаймом. Падение хоста выводит из строя и узел Control Plane, и член кластера etcd.
*   **External etcd (Выделенный):** etcd развернут на отдельных физических серверах или изолированных виртуальных машинах вне узлов Kubernetes.
    *   *Плюсы:* Полная изоляция ресурсов (выделенные NVMe-диски под WAL), независимое масштабирование, независимый цикл обслуживания и обновления ОС.
    *   *Минусы:* Требуется в два раза больше вычислительных узлов (минимум 3 узла etcd + 2-3 узла Control Plane), усложняется первоначальная генерация PKI.

### Модель безопасности и mTLS

Все взаимодействия с etcd защищаются взаимным TLS (mTLS). В production-инфраструктуре строго рекомендуется использовать **два раздельных центра сертификации (CA)**:

1.  **etcd-ca (`/etc/kubernetes/pki/etcd/ca.crt`):** Выпускает серверные сертификаты (`server.crt`), сертификаты межсерверной репликации (`peer.crt`) и сертификаты административных клиентов (`healthcheck-client.crt`).
2.  **kubernetes-ca (`/etc/kubernetes/pki/ca.crt`):** Выпускает клиентский сертификат для API-сервера (`apiserver-etcd-client.crt`).

Подключение `kube-apiserver` конфигурируется через флаги в `/etc/kubernetes/manifests/kube-apiserver.yaml`:

```bash
--etcd-servers=https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379
--etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
--etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
--etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
--etcd-prefix=/registry
--etcd-compaction-interval=5m
```

### Форматы хранения и структура префиксов

Объекты Kubernetes хранятся по ключам с префиксом `/registry`:
*   **Встроенные ресурсы (Core, Apps, Batch):** Сериализуются в бинарный формат **Protobuf** (`application/vnd.kubernetes.protobuf`) для снижения накладных расходов CPU и размера записи. Прямое чтение через `etcdctl get` возвращает бинарные данные.
*   **Пользовательские ресурсы (CRD):** По умолчанию сериализуются в формат **JSON** (`application/json`).
*   **Типовые префиксы:**
    *   `/registry/pods/<namespace>/<name>` — спецификации и статусы подов.
    *   `/registry/services/specs/<namespace>/<name>` — конфигурация сервисов и выделенные IP.
    *   `/registry/secrets/<namespace>/<name>` — объекты секретов (в открытом или зашифрованном виде при включенном Encryption at Rest).
    *   `/registry/events/<namespace>/<name>` — события кластера (короткоживущие объекты с TTL 1 час).
    *   `/registry/leases/kube-node-lease/<node-name>` — Heartbeat-записи узлов кластера.

---

## Практические сценарии и конфигурация

### Настройка CLI-доступа администратора

Для выполнения операций обслуживания через `etcdctl` на хосте Control Plane требуются клиентские сертификаты с правами администратора.

#### Вариант 1: Настройка псевдонима (alias) и переменных окружения на хосте

```bash
# Экспорт переменных окружения для etcdctl v3
export ETCDCTL_API=3
export ETCDCTL_CACERT="/etc/kubernetes/pki/etcd/ca.crt"
export ETCDCTL_CERT="/etc/kubernetes/pki/etcd/server.crt"
export ETCDCTL_KEY="/etc/kubernetes/pki/etcd/server.key"
export ETCDCTL_ENDPOINTS="https://127.0.0.1:2379"

# Проверка связи
etcdctl endpoint health
# → https://127.0.0.1:2379 is healthy: successfully committed proposal: took = 2.14512ms
```

Для постоянного использования добавьте удобный alias в `/root/.bashrc`:

```bash
alias k-etcdctl="ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key"
```

#### Вариант 2: Выполнение команд внутри контейнера через crictl (когда на хосте нет etcdctl)

Если локальные бинарные файлы `etcdctl` не установлены в системе, используйте утилиту рантайма `crictl`:

```bash
# Поиск идентификатора контейнера etcd
ETCD_CONTAINER_ID=$(crictl ps --name etcd -q)

# Выполнение команды внутри пода
crictl exec -it "$ETCD_CONTAINER_ID" etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w table
```

### Конфигурация static pod etcd

Ниже приведен эталонный production-манифест статического пода etcd для kubeadm-кластера (`/etc/kubernetes/manifests/etcd.yaml`):

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: etcd
  namespace: kube-system
  labels:
    component: etcd
    tier: control-plane
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
  - name: etcd
    image: registry.k8s.io/etcd:3.5.16-0
    imagePullPolicy: IfNotPresent
    command:
    - etcd
    - --name=etcd-node-1
    - --data-dir=/var/lib/etcd
    - --listen-peer-urls=https://10.0.0.11:2380
    - --listen-client-urls=https://127.0.0.1:2379,https://10.0.0.11:2379
    - --initial-advertise-peer-urls=https://10.0.0.11:2380
    - --advertise-client-urls=https://10.0.0.11:2379
    - --initial-cluster=etcd-node-1=https://10.0.0.11:2380,etcd-node-2=https://10.0.0.12:2380,etcd-node-3=https://10.0.0.13:2380
    - --initial-cluster-state=existing
    - --initial-cluster-token=k8s-etcd-token
    # Аутентификация клиентов
    - --client-cert-auth=true
    - --trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
    - --cert-file=/etc/kubernetes/pki/etcd/server.crt
    - --key-file=/etc/kubernetes/pki/etcd/server.key
    # Аутентификация пиров
    - --peer-client-cert-auth=true
    - --peer-trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
    - --peer-cert-file=/etc/kubernetes/pki/etcd/peer.crt
    - --peer-key-file=/etc/kubernetes/pki/etcd/peer.key
    # Тюнинг производительности и надежности
    - --quota-backend-bytes=8589934592    # Лимит базы данных 8 GB
    - --snapshot-count=10000              # Сброс логов Raft на диск каждые 10000 транзакций
    - --heartbeat-interval=100            # Интервал heartbeat 100 мс
    - --election-timeout=1000             # Таймаут выборов лидера 1000 мс
    - --auto-compaction-retention=0       # 0 = компакция управляется kube-apiserver
    volumeMounts:
    - mountPath: /var/lib/etcd
      name: etcd-data
    - mountPath: /etc/kubernetes/pki/etcd
      name: etcd-certs
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 2000m
        memory: 4Gi
    startupProbe:
      failureThreshold: 24
      httpGet:
        host: 127.0.0.1
        path: /health?serializable=true
        port: 2379
        scheme: HTTPS
      initialDelaySeconds: 10
      periodSeconds: 10
      timeoutSeconds: 15
    livenessProbe:
      failureThreshold: 8
      httpGet:
        host: 127.0.0.1
        path: /health?exclude=NOSPACE&serializable=true
        port: 2379
        scheme: HTTPS
      initialDelaySeconds: 10
      periodSeconds: 10
      timeoutSeconds: 15
  volumes:
  - name: etcd-data
    hostPath:
      path: /var/lib/etcd
      type: DirectoryOrCreate
  - name: etcd-certs
    hostPath:
      path: /etc/kubernetes/pki/etcd
      type: DirectoryOrCreate
```

> [!IMPORTANT]
> Параметр `--auto-compaction-retention` на стороне самого etcd должен оставаться равным `0` (отключено), если в кластере запущен `kube-apiserver`. API-сервер самостоятельно выполняет компакцию по флагу `--etcd-compaction-interval=5m`. Включение независимой авто-компакции в etcd приводит к конфликтам процессов и ошибкам `mvcc: required revision has been compacted` у клиентов.

### Проверка состояния кластера и кворума

Перед любыми административными процедурами необходимо удостовериться в стабильности кворума:

```bash
# 1. Проверка доступности и latency всех членов кластера
k-etcdctl --endpoints=https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379 \
  endpoint health -w table
# → +------------------------+--------+-------------+-------+
# → |        ENDPOINT        | HEALTH |    TOOK     | ERROR |
# → +------------------------+--------+-------------+-------+
# → | https://10.0.0.11:2379 |   true |  2.124812ms |       |
# → | https://10.0.0.12:2379 |   true |  3.045129ms |       |
# → | https://10.0.0.13:2379 |   true |  2.894101ms |       |
# → +------------------------+--------+-------------+-------+

# 2. Проверка размера баз данных, текущих ревизий и статуса лидера
k-etcdctl --endpoints=https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379 \
  endpoint status -w table
# → +------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+
# → |        ENDPOINT        |        ID        | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX | ERRORS |
# → +------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+
# → | https://10.0.0.11:2379 | 8e9e05f54f240d12 |  3.5.16 |  342 MB |      true |      false |         8 |   24891045 |           24891045 |        |
# → | https://10.0.0.12:2379 | a1b2c3d4e5f60718 |  3.5.16 |  342 MB |     false |      false |         8 |   24891045 |           24891045 |        |
# → | https://10.0.0.13:2379 | b2c3d4e5f6071829 |  3.5.16 |  342 MB |     false |      false |         8 |   24891044 |           24891044 |        |
# → +------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+

# 3. Проверка списка членов кластера и URL пиров
k-etcdctl member list -w table
# → +------------------+---------+-------------+------------------------+------------------------+------------+
# → |        ID        | STATUS  |    NAME     |       PEER URLS        |      CLIENT URLS       | IS LEARNER |
# → +------------------+---------+-------------+------------------------+------------------------+------------+
# → | 8e9e05f54f240d12 | started | etcd-node-1 | https://10.0.0.11:2380 | https://10.0.0.11:2379 |      false |
# → | a1b2c3d4e5f60718 | started | etcd-node-2 | https://10.0.0.12:2380 | https://10.0.0.12:2379 |      false |
# → | b2c3d4e5f6071829 | started | etcd-node-3 | https://10.0.0.13:2380 | https://10.0.0.13:2379 |      false |
# → +------------------+---------+-------------+------------------------+------------------------+------------+
```

### Проверка срока действия и ротация TLS-сертификатов

В kubeadm-кластерах истечение сертификатов etcd приводит к потере связи `kube-apiserver` с базой и полной остановке Control Plane.

```bash
# 1. Проверка срока действия сертификатов etcd
kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   CERTIFICATE AUTHORITY   EXTERNALLY MANAGED
# → apiserver-etcd-client      Jan 15, 2027 08:30 UTC   364d            etcd-ca                 no
# → etcd-healthcheck-client    Jan 15, 2027 08:30 UTC   364d            etcd-ca                 no
# → etcd-peer                  Jan 15, 2027 08:30 UTC   364d            etcd-ca                 no
# → etcd-server                Jan 15, 2027 08:30 UTC   364d            etcd-ca                 no

# 2. Ручное обновление сертификатов на текущем Control Plane узле
kubeadm certs renew etcd-server
kubeadm certs renew etcd-peer
kubeadm certs renew etcd-healthcheck-client
kubeadm certs renew apiserver-etcd-client

# 3. Принудительный перезапуск контейнера etcd для применения новых сертификатов
crictl stop $(crictl ps --name etcd -q)
# kubelet автоматически перезапустит статический под с новыми сертификатами
```

### Поочередная дефрагментация узлов без простоя

Дефрагментация блокирует BoltDB на запись на время перестроения B-tree. В кластере высокой доступности (HA) дефрагментацию **категорически запрещено** выполнять одновременно через флаг `--cluster`. Ее проводят строго последовательно на каждом узле:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Список клиентских адресов всех узлов etcd
NODES=("https://10.0.0.11:2379" "https://10.0.0.12:2379" "https://10.0.0.13:2379")

for endpoint in "${NODES[@]}"; do
  echo "=== Дефрагментация узла $endpoint ==="
  
  # Замер размера базы данных ДО дефрагментации
  db_before=$(k-etcdctl --endpoints="$endpoint" endpoint status --write-out=json | jq -r '.[0].Status.dbSize')
  
  # Выполнение дефрагментации конкретного узла
  k-etcdctl --endpoints="$endpoint" defrag
  
  # Замер размера базы данных ПОСЛЕ дефрагментации
  db_after=$(k-etcdctl --endpoints="$endpoint" endpoint status --write-out=json | jq -r '.[0].Status.dbSize')
  
  echo "Размер до: $((db_before / 1024 / 1024)) MB, после: $((db_after / 1024 / 1024)) MB"
  
  # Пауза для синхронизации журнала Raft перед переходом к следующей ноде
  echo "Ожидание 15 секунд для стабилизации репликации..."
  sleep 15
done

echo "Дефрагментация всех узлов успешно завершена."
```

### Управление составом кластера

#### Безопасное добавление нового узла через Learner

Механизм `learner` гарантирует, что добавляемый узел не уронит кворум, пока не выкачает полный снапшот базы данных:

```bash
# Шаг 1. Добавление узла в качестве learner
k-etcdctl member add etcd-node-4 \
  --peer-urls=https://10.0.0.14:2380 \
  --learner
# → Member 9c8b7a6f5e4d3c2b added to cluster 8e9e05f54f240d12
# → ETCD_NAME="etcd-node-4"
# → ETCD_INITIAL_CLUSTER="etcd-node-1=https://10.0.0.11:2380,etcd-node-2=https://10.0.0.12:2380,etcd-node-3=https://10.0.0.13:2380,etcd-node-4=https://10.0.0.14:2380"
# → ETCD_INITIAL_CLUSTER_STATE="existing"

# Шаг 2. Развертывание и запуск etcd на новом узле (10.0.0.14)
# Манифест должен содержать --initial-cluster-state=existing и обновленный список пиров.

# Шаг 3. Контроль догона репликации (сравнение хешей и индексов Raft)
k-etcdctl --endpoints=https://10.0.0.14:2379 endpoint status -w table

# Шаг 4. Повышение learner до полноправного голосующего члена
k-etcdctl member promote 9c8b7a6f5e4d3c2b
# → Member 9c8b7a6f5e4d3c2b promoted in cluster 8e9e05f54f240d12
```

#### Удаление узла из кластера

```bash
# Получение ID удаляемого узла
k-etcdctl member list -w table

# Удаление узла по ID
k-etcdctl member remove 9c8b7a6f5e4d3c2b
# → Member 9c8b7a6f5e4d3c2b removed from cluster 8e9e05f54f240d12
```

#### Перенос лидерства (Graceful Leader Demotion)

Перед выводом текущего лидера на плановое обслуживание рекомендуется заранее передать роль лидера другому узлу, чтобы избежать задержек при выборах:

```bash
# Определение ID целевого фолловера
TARGET_ID=$(k-etcdctl member list --write-out=json | jq -r '.members[] | select(.name=="etcd-node-2") | .ID')

# Передача лидерства
k-etcdctl move-leader "$TARGET_ID"
# → Leadership transferred to 9c8b7a6f5e4d3c2b
```

---

## Резервное копирование и аварийное восстановление

### Создание снапшота (Online Backup)

Снятие снапшота через `etcdctl snapshot save` является потоковой операцией и не прерывает обработку запросов.

```bash
# Директория для резервных копий
BACKUP_DIR="/var/lib/kube-backups"
mkdir -p "$BACKUP_DIR"
SNAPSHOT_PATH="${BACKUP_DIR}/etcd-snapshot-$(date +%Y%m%d_%H%M%S).db"

# 1. Создание снапшота базы
k-etcdctl snapshot save "$SNAPSHOT_PATH"
# → Snapshot saved at /var/lib/kube-backups/etcd-snapshot-20261018_100000.db

# 2. Проверка целостности файла снапшота (выполняется утилитой etcdutl)
etcdutl snapshot status "$SNAPSHOT_PATH" -w table
# → +----------+----------+------------+------------+
# → |   HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
# → +----------+----------+------------+------------+
# → | d41d8cd9 | 24891045 |     184200 |     342 MB |
# → +----------+----------+------------+------------+
```

#### Автоматизация создания бэкапов через cron

Пример скрипта `/usr/local/bin/etcd-backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/lib/kube-backups"
DATE_TAG=$(date +%Y%m%d_%H%M%S)
SNAPSHOT_FILE="${BACKUP_DIR}/etcd-snapshot-${DATE_TAG}.db"

mkdir -p "$BACKUP_DIR"

# Сохранение снапшота
ETCDCTL_API=3 etcdctl \
  --endpoints="https://127.0.0.1:2379" \
  --cacert="/etc/kubernetes/pki/etcd/ca.crt" \
  --cert="/etc/kubernetes/pki/etcd/healthcheck-client.crt" \
  --key="/etc/kubernetes/pki/etcd/healthcheck-client.key" \
  snapshot save "$SNAPSHOT_FILE"

# Валидация целостности
etcdutl snapshot status "$SNAPSHOT_FILE" > /dev/null

# Ротация: удаление снапшотов старше 7 дней
find "$BACKUP_DIR" -type f -name "etcd-snapshot-*.db" -mtime +7 -delete
```

Добавление в crontab: `0 2 * * * /usr/local/bin/etcd-backup.sh > /var/log/etcd-backup.log 2>&1`.

---

### Полное аварийное восстановление (Offline Restore)

> [!CAUTION]
> Восстановление etcd из снапшота — это **offline-процедура**, требующая полной остановки `kube-apiserver` и всех узлов etcd. Восстановление откатывает состояние всего кластера к точке создания снапшота (все ресурсы, созданные позже, будут безвозвратно утеряны).

#### Сценарий 1: Восстановление одноузлового Control Plane (Single-Node)

1.  **Остановка Control Plane:**
    ```bash
    # Временный перенос манифестов статических подов
    mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/
    mv /etc/kubernetes/manifests/etcd.yaml /tmp/
    
    # Ожидание остановки контейнеров
    while crictl ps | grep -qE "kube-apiserver|etcd"; do sleep 2; done
    ```

2.  **Резервное сохранение текущих поврежденных данных:**
    ```bash
    mv /var/lib/etcd /var/lib/etcd-damaged-"$(date +%s)"
    ```

3.  **Восстановление данных через `etcdutl`:**
    ```bash
    etcdutl snapshot restore /var/lib/kube-backups/etcd-snapshot-last.db \
      --data-dir=/var/lib/etcd \
      --name=etcd-node-1 \
      --initial-cluster="etcd-node-1=https://127.0.0.1:2380" \
      --initial-advertise-peer-urls="https://127.0.0.1:2380"
    # → 2026-10-18T10:00:00Z INFO restored snapshot {"path": "/var/lib/kube-backups/etcd-snapshot-last.db", "data-dir": "/var/lib/etcd"}
    ```

4.  **Проверка прав доступа:**
    ```bash
    chown -R root:root /var/lib/etcd
    chmod 700 /var/lib/etcd
    ```

5.  **Запуск компонентов:**
    ```bash
    mv /tmp/etcd.yaml /etc/kubernetes/manifests/
    mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/
    
    # Контроль готовности API
    kubectl get nodes
    ```

---

#### Сценарий 2: Синхронное восстановление всех узлов HA-кластера

Если все 3 узла etcd разрушены, процедура восстановления должна быть выполнена на **каждом узле кластера** с использованием **одного и того же файла снапшота** и единого `--initial-cluster-token`:

1.  **Остановите `kube-apiserver` и `etcd` на ВСЕХ трех master-узлах.**
2.  **Сделайте бэкап старых данных `/var/lib/etcd` на всех трех узлах.**
3.  **Скопируйте валидный файл снапшота на все узлы.**
4.  **Выполните `etcdutl snapshot restore` на каждом узле со специфичными для него IP:**

*На Узле 1 (10.0.0.11):*
```bash
etcdutl snapshot restore /tmp/etcd-snapshot.db \
  --data-dir=/var/lib/etcd \
  --name=etcd-node-1 \
  --initial-cluster="etcd-node-1=https://10.0.0.11:2380,etcd-node-2=https://10.0.0.12:2380,etcd-node-3=https://10.0.0.13:2380" \
  --initial-advertise-peer-urls="https://10.0.0.11:2380" \
  --initial-cluster-token="k8s-etcd-restore-token"
```

*На Узле 2 (10.0.0.12):*
```bash
etcdutl snapshot restore /tmp/etcd-snapshot.db \
  --data-dir=/var/lib/etcd \
  --name=etcd-node-2 \
  --initial-cluster="etcd-node-1=https://10.0.0.11:2380,etcd-node-2=https://10.0.0.12:2380,etcd-node-3=https://10.0.0.13:2380" \
  --initial-advertise-peer-urls="https://10.0.0.12:2380" \
  --initial-cluster-token="k8s-etcd-restore-token"
```

*На Узле 3 (10.0.0.13):*
```bash
etcdutl snapshot restore /tmp/etcd-snapshot.db \
  --data-dir=/var/lib/etcd \
  --name=etcd-node-3 \
  --initial-cluster="etcd-node-1=https://10.0.0.11:2380,etcd-node-2=https://10.0.0.12:2380,etcd-node-3=https://10.0.0.13:2380" \
  --initial-advertise-peer-urls="https://10.0.0.13:2380" \
  --initial-cluster-token="k8s-etcd-restore-token"
```

5.  **Запустите манифесты `etcd.yaml` на всех трех узлах одновременно.** Узлы обнаружат друг друга по peer-портам 2380 и соберут кворум.
6.  **После стабилизации etcd верните манифесты `kube-apiserver.yaml`.**

---

#### Сценарий 3: Пошаговое восстановление (1 узел + расширение через Learner)

В реальной эксплуатации координация одновременного запуска 3 узлов может давать сбои из-за сетевых таймаутов. Наиболее надежный метод восстановления HA-кластера — **поднятие одного узла и добавление остальных как новых членов**:

1.  На Узле 1 восстановите снапшот как **одноузловой кластер**:
    ```bash
    etcdutl snapshot restore /tmp/etcd-snapshot.db \
      --data-dir=/var/lib/etcd \
      --name=etcd-node-1 \
      --initial-cluster="etcd-node-1=https://10.0.0.11:2380" \
      --initial-advertise-peer-urls="https://10.0.0.11:2380" \
      --initial-cluster-token="k8s-etcd-new-token"
    ```
2.  В манифесте `/etc/kubernetes/manifests/etcd.yaml` на Узле 1 временно скорректируйте флаги `--initial-cluster` и `--initial-cluster-state=new`. Запустите etcd и `kube-apiserver` на Узле 1. Кластер Kubernetes снова работает.
3.  Очистите `/var/lib/etcd` на Узлах 2 и 3.
4.  Добавьте Узел 2 через `member add --learner`:
    ```bash
    k-etcdctl member add etcd-node-2 --peer-urls=https://10.0.0.12:2380 --learner
    ```
5.  Запустите etcd на Узле 2 с флагом `--initial-cluster-state=existing`.
6.  После синхронизации переведите узел в голосующие: `k-etcdctl member promote <ID>`.
7.  Повторите процедуру для Узла 3.

---

## Диагностика и устранение неисправностей

### Авария "database space exceeded" (Alarm NOSPACE)

Если база данных etcd достигает квоты (`--quota-backend-bytes`, по умолчанию 2 GB), etcd генерирует алерт `NOSPACE` и блокирует все операции записи. Kubernetes API-сервер начинает возвращать ошибку `HTTP 500: etcdserver: mvcc: database space exceeded`.

#### Регламент восстановления:

```bash
# Шаг 1. Проверка наличия активных алармов
k-etcdctl alarm list
# → memberID:8e9e05f54f240d12 alarm:NOSPACE

# Шаг 2. Определение последней ревизии
LATEST_REV=$(k-etcdctl endpoint status --write-out=json | jq -r '.[0].Status.header.revision')
echo "Текущая ревизия: $LATEST_REV"

# Шаг 3. Логическая компакция старой истории версий
k-etcdctl compact "$LATEST_REV"
# → compacted revision 24891045

# Шаг 4. Физическая дефрагментация каждого узла поочередно
for ep in https://10.0.0.11:2379 https://10.0.0.12:2379 https://10.0.0.13:2379; do
  echo "Дефрагментация $ep..."
  k-etcdctl --endpoints="$ep" defrag
  sleep 10
done

# Шаг 5. Снятие блокировки (Disarm Alarm)
k-etcdctl alarm disarm
# → memberID:8e9e05f54f240d12 alarm:NOSPACE

# Шаг 6. Контрольная проверка (список алармов должен быть пуст)
k-etcdctl alarm list
# (пустой вывод)

# Шаг 7. Проверка свободного места
k-etcdctl endpoint status -w table
```

#### Расследование причин переполнения базы:

Чаще всего причиной лавинообразного роста являются системные события (Event Storm) или утечки Lease-объектов:

```bash
# Подсчет количества событий в кластере
k-etcdctl get /registry/events --prefix --keys-only | wc -l

# Подсчет подов во всех неймспейсах
k-etcdctl get /registry/pods --prefix --keys-only | wc -l
```

Если обнаружен Event Storm, уменьшите `--event-ttl` в `/etc/kubernetes/manifests/kube-apiserver.yaml` (например, до `15m` вместо `1h` по умолчанию).

---

### Ошибка "etcdserver: request is too large"

Если объект Kubernetes (большой ConfigMap, бинарный Secret или CRD) превышает `--max-request-bytes` (по умолчанию 1.5 MB), API-сервер отклоняет сохранение:

```text
Error from server (InternalError): etcdserver: request is too large
```

**Решение:**
1.  *Архитектурно правильное решение:* Разбить ConfigMap на несколько более мелких файлов или вынести бинарные данные в PersistentVolume.
2.  *Инфраструктурное решение (при крайней необходимости):* Увеличьте лимит до 3–10 MB в манифесте `/etc/kubernetes/manifests/etcd.yaml`:
    ```yaml
    - --max-request-bytes=10485760   # 10 MB
    ```
    > [!WARNING]
    > Увеличение `--max-request-bytes` свыше 10 MB не рекомендуется: большие объекты замедляют репликацию логов Raft и вызывают пиковые задержки в работе garbage collector рантайма Go.

---

### Восстановление при потере кворума (Disaster Quorum Loss)

Если из 3 узлов etcd вышли из строя 2 узла, оставшийся узел не может принимать решения (кворум 1 из 3 невозможен). etcd переходит в read-only режим.

Если упавшие узлы невозможно восстановить физически, выживший узел можно принудительно перевести в статус нового одноузлового кластера без потери текущих данных:

1.  Остановите etcd на выжившем узле (переместите манифест `etcd.yaml` в `/tmp/`).
2.  В манифесте `/tmp/etcd.yaml` добавьте аргумент:
    ```yaml
    - --force-new-cluster=true
    ```
3.  Верните манифест в `/etc/kubernetes/manifests/`.
4.  etcd пересчитает Raft-членство, удалит мертвые узлы из топологии и назначит себя единственным членом нового кворума.
5.  **ОБЯЗАТЕЛЬНО:** После успешного запуска сразу же удалите флаг `--force-new-cluster=true` из манифеста, чтобы избежать сброса топологии при следующем перезапуске!
6.  Добавьте новые узлы по стандартной схеме через `member add --learner`.

---

### Задержки диска (fsync) и Leader Flapping

Лидер etcd периодически отправляет фолловерам heartbeat (по умолчанию каждые 100 мс). Если диск фолловера или лидера не успевает сбросить WAL на диск за время `election-timeout` (по умолчанию 1000 мс), фолловер объявляет выборы. Начинается постоянная смена лидера (**Leader Flapping**), приводящая к каскадному сбою API-сервера.

**Диагностика через Prometheus / curl:**

```bash
# Замер времени синхронизации WAL на диск
curl -s https://127.0.0.1:2379/metrics \
  --cacert /etc/kubernetes/pki/etcd/ca.crt \
  --cert /etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key /etc/kubernetes/pki/etcd/healthcheck-client.key | \
  grep "etcd_disk_wal_fsync_duration_seconds_bucket"
```

*Норма:* p99 задержки fsync должен быть строго **< 10 мс** (на NVMe накопителях — < 1-2 мс). Если значение стабильно превышает 20–30 мс, дисковая подсистема непригодна для etcd.

---

### Проверка целостности данных (Data Drift & Corruption)

Для выявления рассинхронизации данных между узлами кластера (когда ревизии совпадают, но хеши данных разошлись):

```bash
# Вычисление хеша базы данных на всех узлах
k-etcdctl endpoint hashkv --cluster -w table
# → +------------------------+------------+
# → |        ENDPOINT        |    HASH    |
# → +------------------------+------------+
# → | https://10.0.0.11:2379 | 1084291845 |
# → | https://10.0.0.12:2379 | 1084291845 |
# → | https://10.0.0.13:2379 | 1084291845 |
# → +------------------------+------------+
```

Если на одном из узлов хеш отличается, на нем произошло повреждение данных (Bit rot или рассинхронизация BoltDB).
*Решение:* Остановить узел с несовпадающим хешем, удалить его `/var/lib/etcd`, удалить члена через `member remove`, добавить заново через `member add --learner` и перезапустить.

---

### Ключевые метрики мониторинга в Prometheus

| Метрика | Тип | Порог алертинга | Описание и регламент |
| :--- | :--- | :--- | :--- |
| `etcd_server_has_leader` | Gauge | `== 0` | Узел потерял лидера. Если 0 на всех — кластер недоступен. |
| `etcd_server_leader_changes_seen_total` | Counter | `rate(...) > 3 / 15m` | Частая смена лидера (flapping). Проверить задержки fsync и RTT сети. |
| `etcd_disk_wal_fsync_duration_seconds` | Histogram | `p99 > 10ms` (Warn), `p99 > 50ms` (Crit) | Задержка записи WAL на диск хоста. |
| `etcd_disk_backend_commit_duration_seconds` | Histogram | `p99 > 25ms` | Задержка фиксации транзакций в BoltDB. |
| `etcd_network_peer_round_trip_time_seconds` | Histogram | `p99 > 50ms` | Время сетевого ответа между пирами в кластере. |
| `etcd_mvcc_db_total_size_in_bytes` / `etcd_server_quota_backend_bytes` | Gauge | `> 0.85` | Заполнение базы свыше 85% от квоты. Требуется defrag или увеличение квоты. |
| `etcd_server_proposals_failed_total` | Counter | `rate(...) > 0.1` | Отклонение транзакций (потеря кворума или перегрузка). |

**Пример конфигурации PrometheusRule для Alertmanager:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: etcd-sre-alerts
  namespace: monitoring
spec:
  groups:
  - name: etcd.rules
    rules:
    - alert: EtcdNoLeader
      expr: etcd_server_has_leader{job="etcd"} == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "Член кластера etcd потерял связь с лидером"
        description: "Узел {{ $labels.instance }} не видит лидера кластера etcd более 1 минуты."

    - alert: EtcdWalFsyncSlow
      expr: histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket{job="etcd"}[5m])) > 0.02
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Высокая задержка fsync WAL etcd (p99 > 20ms)"
        description: "Медленный дисковый ввод-вывод на узле {{ $labels.instance }} угрожает стабильности кворума."

    - alert: EtcdDatabaseQuotaApproaching
      expr: (etcd_mvcc_db_total_size_in_bytes{job="etcd"} / etcd_server_quota_backend_bytes{job="etcd"}) > 0.85
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Размер БД etcd превышает 85% квоты"
        description: "База данных {{ $labels.instance }} заполнена на {{ $value | humanizePercentage }}. Требуется срочная дефрагментация."
```

---

## Лучшие практики

### 1. Требования к дисковой подсистеме
*   **Тип накопителей:** Исключительно серверные **NVMe SSD** (или enterprise SAS SSD с энергонезависимым кэшем). Обычные SATA HDD и виртуальные сетевые диски с высокой латентностью (NFS, Ceph RBD без QoS) строго запрещены.
*   **Изолированная файловая система:** Размещайте `/var/lib/etcd` на отдельном выделенном физическом блочном устройстве, чтобы системные логи или сбросы дампов памяти не вызывали starvation I/O.
*   **Опции монтирования:** Для ext4/xfs используйте опции `noatime,nodiratime`.

### 2. Расчет оперативной памяти и настройка квот
*   По умолчанию etcd имеет квоту базы данных `2 GB`. В production рекомендуется устанавливать:
    ```bash
    --quota-backend-bytes=8589934592 # 8 GB (максимально надежный размер BoltDB)
    ```
*   **Потребление RAM:** BoltDB отображает весь файл базы в виртуальную память через `mmap`. Реальное потребление памяти etcd обычно составляет **2–3x от размера базы данных на диске** (с учетом индексов и буферов сериализации Protobuf). Для базы в 4 GB сервер должен иметь минимум 12–16 GB оперативной памяти.

### 3. Выделение отдельного etcd под события (Events Isolation)
В кластерах масштабом свыше 500 узлов или при активном CI/CD штормы системных событий создают паразитный поток записи в etcd. Kubernetes поддерживает вынос событий в изолированный кластер:

```bash
# В манифесте kube-apiserver:
--etcd-servers=https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379
--etcd-servers-overrides=/events#https://10.0.0.21:2379;https://10.0.0.22:2379;https://10.0.0.23:2379
```

Это гарантирует, что даже при переполнении базы событий основное состояние кластера (поды, деплойменты, секреты) продолжит работать стабильно.

### 4. Синхронизация времени (NTP)
Raft полагается на монотонные таймеры для выборов лидера. Расхождение часов (Clock Skew) между узлами etcd свыше **1 секунды** может приводить к ложным перевыборам и нестабильности соединений. На всех узлах должен работать синхронизатор времени (`chrony` или `systemd-timesyncd`).

---

## Дополнительная информация

*   **[Обзор etcd в Kubernetes](./etcd_overview.md)** — архитектурные основы и место etcd в Control Plane.
*   **[Альтернативы etcd и безопасность](./etcd_alternatives_and_security.md)** — Kine, Dqlite, шифрование Encryption at Rest и интеграция с KMS v2.
*   **[Хранение секретов в etcd](../Base/secrets/etcd_storage.md)** — механизмы шифрования секретов на диске.
*   **[Шпаргалка по командам etcdctl](../../etcd/etcdctl_cheatsheet.md)** — развернутый справочник команд CLI.
*   **[Мониторинг etcd](../../etcd/etcd_monitoring.md)** — подробные метрики Prometheus и настройка дашбордов Grafana.
*   **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)** — проектирование топологий высокой доступности.
*   **[MVCC, версионирование и компакция](../../etcd/mvcc_versioning_and_compaction.md)** — внутреннее устройство storage engine BoltDB.
*   **[Стратегии резервного копирования в Kubernetes](../Operations/backup-strategies.md)** — сравнение резервного копирования etcd с решениями уровня Velero.
