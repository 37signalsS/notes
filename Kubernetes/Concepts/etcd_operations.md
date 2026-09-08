# etcd: практические сценарии и обслуживание в Kubernetes

## Определение

В контексте Kubernetes **обслуживание etcd** — это комплекс регулярных и аварийных процедур, направленных на поддержание стабильности, производительности и целостности базы данных кластера.

Для управления etcd используются две основные утилиты:
*   **`etcdctl`**: Основной клиент (gRPC) для работы с запущенным кластером (online-операции: чтение данных, проверка здоровья, дефрагментация, создание снапшотов).
*   **`etcdutl`**: Утилита (начиная с v3.6+) для административных задач, требующих прямого доступа к физическим файлам базы данных (offline-операции: восстановление из снапшота, проверка целостности файла).

**Префикс `/registry`** — корневой путь в etcd, по которому Kubernetes хранит все свои сериализованные объекты.

---

## Интеграция с Kubernetes и доступ

`kube-apiserver` является единственным компонентом Kubernetes, имеющим прямой доступ к etcd. 

### Конфигурация доступа

Параметры TLS-аутентификации задаются во флагах `kube-apiserver` (обычно в `/etc/kubernetes/manifests/kube-apiserver.yaml`):

```bash
--etcd-servers=https://127.0.0.1:2379
--etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
--etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
--etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
```

### Настройка CLI для администратора

Для выполнения команд `etcdctl` на узле Control Plane необходимо использовать клиентские сертификаты. Для удобства рекомендуется настроить alias в профиле пользователя:

```bash
export ETCDCTL_API=3
alias k-etcdctl="etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key"
```
*(В kubeadm-кластерах удобнее использовать `healthcheck-client` или `server` сертификаты, лежащие в `/etc/kubernetes/pki/etcd/`)*.

---

## Работа с данными Kubernetes

Все объекты Kubernetes сериализуются и хранятся в формате **Protobuf** (начиная с K8s 1.6+). Прямое чтение ключей через `etcdctl` вернет бинарные данные, которые сложно прочитать человеку, однако это полезно для отладки структуры.

### Исследование структуры хранения

*   **Список всех доступных префиксов (типов ресурсов):**
    ```bash
    k-etcdctl get /registry --prefix --keys-only
    ```

*   **Типовые пути K8s:**
    *   `/registry/pods/<namespace>/<name>`
    *   `/registry/secrets/<namespace>/<name>`
    *   `/registry/events/<namespace>/<name>` — частая причина разрастания БД в нестабильных кластерах.
    *   `/registry/leases/kube-node-lease/<node-name>` — Heartbeats узлов.

---

## Обслуживание и мониторинг

### Проверка здоровья и статуса

Перед любыми операциями всегда проверяйте кворум:

```bash
# Проверка доступности узлов
k-etcdctl endpoint health --cluster -w table
# → https://10.0.0.11:2379 is healthy: true
# → https://10.0.0.12:2379 is healthy: true
# → https://10.0.0.13:2379 is healthy: true

# Проверка размера БД, ревизии и кто является лидером
k-etcdctl endpoint status --cluster -w table
# → +------------------+---------+---------+-----------+------------------+--------------------------------+-------------------------------------+
# → |     ENDPOINT     | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX | ERRORS |
# → +------------------+---------+---------+-----------+------------------+--------------------------------+-------------------------------------+
# → | 10.0.0.11:2379 | 3.5.12 | 24 MB | true | false | 8 | 12345678 | 12345678 | |
# → | 10.0.0.12:2379 | 3.5.12 | 24 MB | false | false | 8 | 12345677 | 12345677 | |
# → | 10.0.0.13:2379 | 3.5.12 | 24 MB | false | false | 8 | 12345676 | 12345676 | |
# → +------------------+---------+---------+-----------+------------------+--------------------------------+-------------------------------------+

# Проверка количества ключей в БД (диагностика разрастания)
k-etcdctl endpoint status --write-out=json | jq '.[] | {endpoint: .Status.header.member_id, dbSize: .Status.dbSize, revision: .Status.header.revision}'

# Просмотр всех членов кластера и их ролей
k-etcdctl member list -w table
# → +------------------+---------+-------------+------------------+------------------+-------------+
# → |        ID        | STATUS  |    NAME     |     PEER URLS    |    CLIENT URLS   |   IS LEARNER |
# → +------------------+---------+-------------+------------------+------------------+-------------+
# → | 8e9e05f54f240d12 | started | etcd-node-1 | https://10.0.0.11:2380 | https://10.0.0.11:2379 | false |
# → | a1b2c3d4e5f60718 | started | etcd-node-2 | https://10.0.0.12:2380 | https://10.0.0.12:2379 | false |
# → | b2c3d4e5f6071829 | started | etcd-node-3 | https://10.0.0.13:2380 | https://10.0.0.13:2379 | false |
# → +------------------+---------+-------------+------------------+------------------+-------------+

# Проверка версии etcd на каждом узле
k-etcdctl version
# → etcdctl version: 3.5.12
# → API version: 3.5
```

### Компакция и Дефрагментация

В Kubernetes API-сервер автоматически выполняет **компакцию** (сжатие истории версий MVCC) каждые 5 минут. Однако компакция лишь помечает место в БД как свободное, не возвращая его файловой системе.

Для физического уменьшения файла базы данных необходима **дефрагментация**.

> **ВНИМАНИЕ:** Дефрагментация блокирует узел на чтение и запись до завершения процесса. В HA-кластере ее необходимо выполнять **строго поочередно** на каждом узле, а не через флаг `--cluster`, чтобы не потерять кворум.

```bash
# Правильный подход: дефрагментация конкретного узла
k-etcdctl --endpoints=https://10.0.0.11:2379 defrag
k-etcdctl --endpoints=https://10.0.0.12:2379 defrag
```

### Устранение ошибки "database space exceeded" (NOSPACE)

По умолчанию etcd имеет жесткий лимит на размер базы данных (обычно 2GB). Если БД достигает этого предела (часто из-за шторма событий K8s или отсутствия дефрагментации), etcd переходит в режим "только чтение" и генерирует Alarm `NOSPACE`. K8s API-сервер перестает принимать изменения.

**Алгоритм восстановления:**
1.  **Получите текущую ревизию:**
    ```bash
    rev=$(k-etcdctl endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9]*' | head -n 1)
    ```
2.  **Выполните ручную компакцию:**
    ```bash
    k-etcdctl compaction $rev
    ```
3.  **Выполните дефрагментацию на всех узлах:**
    ```bash
    k-etcdctl defrag --cluster
    ```
4.  **Снимите блокировку (Disarm Alarm):**
    ```bash
    k-etcdctl alarm list
    k-etcdctl alarm disarm
    ```

**Диагностика причины NOSPACE:**
```bash
# Проверка текущего размера БД и квоты
k-etcdctl endpoint status --write-out=json | jq '.[] | {dbSize: .Status.dbSize, dbSizeInUse: .Status.dbSizeInUse}'
# → {"dbSize": 2147483648, "dbSizeInUse": 1073741824}

# Проверка количества ключей (часто виноват event storm)
k-etcdctl get /registry/events --prefix --keys-only | wc -l
# → 1542000  (слишком много — требуется очистка)

# Мониторинг размера БД в реальном времени (Prometheus)
# etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes > 0.85 — алерт
```

**Автоматическая профилактика NOSPACE:**
```bash
# Добавьте в crontab (ежедневно, в час низкой нагрузки):
# Компакция + дефрагментация каждого узла поочередно
0 3 * * * /usr/local/bin/k-etcdctl --endpoints=https://10.0.0.11:2379 defrag && \
  sleep 30 && /usr/local/bin/k-etcdctl --endpoints=https://10.0.0.12:2379 defrag && \
  sleep 30 && /usr/local/bin/k-etcdctl --endpoints=https://10.0.0.13:2379 defrag
```

### Мониторинг и ключевые метрики

etcd предоставляет встроенный Prometheus Exporter на порту `2379/metrics`. Мониторинг критичен для раннего обнаружения проблем с производительностью диска, сетью и кворумом.

**Ключевые метрики для алертинга:**

| Метрика | Тип | Норма | Критичное значение | Описание |
| :--- | :--- | :--- | :--- | :--- |
| `etcd_server_has_leader` | Gauge | = 1 | = 0 | Наличие лидера. 0 на всех узлах — кластер read-only. |
| `etcd_server_leader_changes_seen_total` | Counter | Стабильно | > 3 за 15 мин | Частая смена лидера (flapping) — проблемы с сетью/диском. |
| `etcd_disk_wal_fsync_duration_seconds` | Histogram | p99 < 10 мс | p99 > 100 мс | Задержка записи WAL. Основной индикатор IOPS. |
| `etcd_disk_backend_commit_duration_seconds` | Histogram | p99 < 25 мс | p99 > 100 мс | Задержка коммита в BoltDB. |
| `etcd_network_peer_round_trip_time_seconds` | Histogram | p99 < 50 мс | p99 > 100 мс | RTT между узлами кластера. |
| `etcd_server_proposals_failed_total` | Counter | 0 | Рост | Ошибки записи, потеря кворума. |
| `etcd_mvcc_db_total_size_in_bytes` | Gauge | < 2 GB | > 80% квоты | Размер БД. Приближение к `quota-backend-bytes`. |
| `etcd_server_lease_expired_total` | Counter | Пропорционально TTL | Всплески | Истечение аренд — проблемы с keepalive. |

**Примеры PromQL-запросов для мониторинга:**

```promql
# Наличие лидера (алерт при = 0)
etcd_server_has_leader == 0

# Частота смены лидера (алерт при > 3 за 15 минут)
rate(etcd_server_leader_changes_seen_total[15m]) > 3

# p99 задержки WAL fsync (алерт при > 20 мс)
histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) > 0.02

# Заполнение БД > 85% (алерт при приближении к квоте)
etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes > 0.85

# Количество active Watch (для диагностики нагрузки)
etcd_server_watcher_total

# Количество активных leases
etcd_server_lease_object_count

# Суммарный gRPC-трафик (для оценки нагрузки на сеть)
rate(etcd_network_client_grpc_sent_bytes_total[5m])
rate(etcd_network_client_grpc_received_bytes_total[5m])
```

**Настройка скрейпинга etcd в Prometheus:**
```yaml
# В kube-prometheus-stack: добавьте в values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
    - job_name: 'etcd'
      kubernetes_sd_configs:
      - role: endpoints
        namespaces:
          names: ['kube-system']
      scheme: https
      tls_config:
        ca_file: /etc/kubernetes/pki/etcd/ca.crt
        cert_file: /etc/kubernetes/pki/etcd/healthcheck-client.crt
        key_file: /etc/kubernetes/pki/etcd/healthcheck-client.key
      relabel_configs:
      - source_labels: [__meta_kubernetes_endpoint_name]
        regex: etcd
        action: keep
```

*Полный справочник метрик и настройка Grafana-дашбордов:* **[Мониторинг etcd](../../etcd/etcd_monitoring.md)**.

### Управление членами кластера

Операции с составом кластера etcd (добавление, удаление, повышение узлов) критичны для масштабирования и ремонта.

**Добавление нового узла (через Learner):**

```bash
# 1. Добавьте узел как learner (неголосующий член)
k-etcdctl member add etcd-node-4 \
  --peer-urls=https://10.0.0.14:2380 \
  --learner
# → Member 8e9e05f54f240d12 added to cluster 8e9e05f54f240d12
# → name: etcd-node-4
# → peerURLs: https://10.0.0.14:2380
# → isLearner: true

# 2. Запустите etcd на новом узле с параметром --initial-cluster-state=existing
# и --initial-cluster, включающим все узлы (включая learner)

# 3. Дождитесь синхронизации лога (разница RAFT INDEX < 1000)
k-etcdctl endpoint hashkv --cluster -w table

# 4. Повысите learner до голосующего члена
k-etcdctl member promote 8e9e05f54f240d12
# → Member 8e9e05f54f240d12 promoted

# 5. Проверьте кворум
k-etcdctl endpoint health --cluster -w table
```

**Удаление узла:**
```bash
# Удаление узла (если узел мертв или выводится из кластера)
k-etcdctl member remove 8e9e05f54f240d12
# → Member 8e9e05f54f240d12 removed from cluster 8e9e05f54f240d12

# Проверка: узел должен исчезнуть из member list
k-etcdctl member list -w table
```

**Перенос лидерства (для планового обслуживания узла):**
```bash
# Перед выводом узла из кластера перенесите лидерство на другой узел
# 1. Узнайте ID целевого узла
k-etcdctl member list -w table
# → 8e9e05f54f240d12 | started | etcd-node-1 | ... | is leader: true
# → a1b2c3d4e5f60718 | started | etcd-node-2 | ...

# 2. Перенесите лидерство
k-etcdctl move-leader a1b2c3d4e5f60718
# → Leadership transferred from 8e9e05f54f240d12 to a1b2c3d4e5f60718

# 3. Проверьте, что лидер сменился
k-etcdctl endpoint status --cluster -w table
```

*Детальное руководство по кластеризации и восстановлению кворума:* **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)**.

### Конфигурация и тюнинг параметров

Ключевые параметры etcd, требующие настройки для production-среды:

| Параметр | Значение по умолчанию | Рекомендуемое | Описание |
| :--- | :--- | :--- | :--- |
| `--quota-backend-bytes` | 2 GB | 8 GB (максимум) | Максимальный размер БД. Увеличение требует пропорционального роста RAM (etcd потребляет ~2x от размера БД). |
| `--max-request-bytes` | 1.5 MB | 1.5–3 MB | Максимальный размер одного запроса (объекта). Увеличение рекомендуется только при необходимости хранить большие ConfigMap/Secret. |
| `--auto-compaction-mode` | periodic | periodic | Режим авто-компакции: `periodic` (по времени) или `revision` (по количеству ревизий). |
| `--auto-compaction-retention` | 0 (отключено) | 5m | Интервал авто-компакции. Должен совпадать с `--etcd-compaction-interval` API-сервера. |
| `--snapshot-count` | 10000 | 10000 | Количество коммитов между снапшотами. etcd 3.6+ снизил до 10000 (было 10000). |
| `--heartbeat-interval` | 100 | 100 | Интервал heartbeat (мс). В больших кластерах (>5 узлов) или при высоком RTT увеличьте до 200–300. |
| `--election-timeout` | 1000 | 1000 | Таймаут выборов лидера (мс). Должен быть >= 10 * heartbeat-interval. Увеличьте при RTT > 50 мс. |

**Пример конфигурации etcd (Static Pod манифест):**
```yaml
# /etc/kubernetes/manifests/etcd.yaml
apiVersion: v1
kind: Pod
metadata:
  name: etcd
  namespace: kube-system
spec:
  containers:
  - name: etcd
    image: registry.k8s.io/etcd:3.5.12-0
    command:
    - etcd
    - --name=etcd-node-1
    - --data-dir=/var/lib/etcd
    - --listen-peer-urls=https://127.0.0.1:2380
    - --listen-client-urls=https://127.0.0.1:2379
    - --advertise-client-urls=https://10.0.0.11:2379
    - --initial-advertise-peer-urls=https://10.0.0.11:2380
    - --initial-cluster=etcd-node-1=https://10.0.0.11:2380,etcd-node-2=https://10.0.0.12:2380,etcd-node-3=https://10.0.0.13:2380
    - --initial-cluster-state=existing
    - --initial-cluster-token=k8s-etcd-cluster
    - --client-cert-auth=true
    - --trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
    - --cert-file=/etc/kubernetes/pki/etcd/server.crt
    - --key-file=/etc/kubernetes/pki/etcd/server.key
    - --peer-client-cert-auth=true
    - --peer-trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
    - --peer-cert-file=/etc/kubernetes/pki/etcd/peer.crt
    - --peer-key-file=/etc/kubernetes/pki/etcd/peer.key
    # Тюнинг производительности
    - --quota-backend-bytes=8589934592   # 8 GB
    - --max-request-bytes=33554432       # 32 MB (только при необходимости)
    - --auto-compaction-mode=periodic
    - --auto-compaction-retention=5m
    - --snapshot-count=10000
    - --heartbeat-interval=100
    - --election-timeout=1000
    volumeMounts:
    - mountPath: /var/lib/etcd
      name: etcd-data
    - mountPath: /etc/kubernetes/pki/etcd
      name: etcd-certs
  hostNetwork: true
  volumes:
  - hostPath:
      path: /var/lib/etcd
      type: DirectoryOrCreate
    name: etcd-data
  - hostPath:
      path: /etc/kubernetes/pki/etcd
      type: DirectoryOrCreate
    name: etcd-certs
```

**Изменение `quota-backend-bytes` без потери данных:**
```bash
# 1. Проверьте текущий размер БД
k-etcdctl endpoint status --write-out=json | jq '.[].Status.dbSize'
# → 2147483648 (2 GB — уже упирается в квоту)

# 2. Сначала выполните defrag (если БД сильно фрагментирована)
k-etcdctl defrag --endpoints=https://10.0.0.11:2379

# 3. Измените квоту (требует перезапуска etcd)
#    В манифесте etcd.yaml измените --quota-backend-bytes=8589934592

# 4. Перезапустите etcd (переместите манифест в/out of /etc/kubernetes/manifests/)
mv /etc/kubernetes/manifests/etcd.yaml /tmp/etcd.yaml && sleep 30 && mv /tmp/etcd.yaml /etc/kubernetes/manifests/etcd.yaml

# 5. Проверьте новую квоту
k-etcdctl endpoint status --cluster -w table
```

### Проверка целостности (WAL verify, hashkv)

Регулярная проверка целостности данных позволяет обнаружить повреждение до того, как оно приведет к простоям.

```bash
# Проверка хешей всех узлов (должны совпадать)
k-etcdctl endpoint hashkv --cluster -w table
# → +------------------+----------+
# → |     ENDPOINT     |    HASH  |
# → +------------------+----------+
# → | 10.0.0.11:2379 | 12345678 |
# → | 10.0.0.12:2379 | 12345678 |
# → | 10.0.0.13:2379 | 12345678 |
# → +------------------+----------+
# → Если хеши различаются — есть расхождение данных (требуется восстановление)

# Проверка WAL (Write-Ahead Log) — выполняется на остановленном etcd
etcdutl wal verify /var/lib/etcd/wal/
# → applying WAL
# → 154 entries found
# → All WAL files verified successfully

# Если WAL повреждена — восстановление:
etcdutl wal repair /var/lib/etcd/wal/

# Просмотр содержимого WAL (для отладки)
etcdutl wal show /var/lib/etcd/wal/
# → WAL metadata
# → etcd version: 3.5.12
# → hash: abc123...
# → index: 12345678
# → entries: 154
```

**Когда проверять целостность:**
- После аварийного завершения etcd (power loss, OOM kill)
- После аппаратных сбоев диска
- Планово — раз в месяц (включить в cron)
- При подозрении на повреждение данных (ошибки `CORRUPT`)

*Подробнее о WAL и архитектуре хранения:* **[Внутреннее устройство etcd](../../etcd/storage_internals.md)**.

### Диагностика производительности

etcd критичен к производительности диска и сети. Высокие задержки приводят к перевыборам лидера, таймаутам и деградации всего кластера.

**Комплексная диагностика:**
```bash
# 1. Замер задержки fsync (критичнейшая метрика)
curl -s https://127.0.0.1:2379/metrics --cert ... --key ... --cacert ... | \
  grep etcd_disk_wal_fsync_duration_seconds_bucket
# → etcd_disk_wal_fsync_duration_seconds_bucket{le="0.001"} 1500
# → etcd_disk_wal_fsync_duration_seconds_bucket{le="0.01"} 9800
# → etcd_disk_wal_fsync_duration_seconds_bucket{le="0.1"} 9999
# → etcd_disk_wal_fsync_duration_seconds_bucket{le="+Inf"} 10000
# → p99 должен быть < 10 мс, ideally < 1 мс на NVMe

# 2. Проверка сетевой задержки между узлами
k-etcdctl endpoint health --cluster -w table
# Обратите внимание на время ответа каждого узла

# 3. Замер IOPS диска (на хосте)
iostat -x 1 5
# → %util не должен превышать 80%
# → await не должен превышать 10 мс

# 4. Проверка использования CPU и RAM etcd
ps aux | grep etcd
# → RSS не должен превышать 2x от размера БД

# 5. Проверка file descriptors
cat /proc/$(pgrep etcd)/limits | grep "Max open files"
# → Max open files  65536  65536  files  (рекомендуется >= 65536)
```

**Базовый бенчмаркинг etcd:**
```bash
# Бенчмарк записи (только для тестовых сред!)
etcdctl check perf --load=type=1000 --conns=10 --clients=10
# → 1000 requests cost 1.234s (810.0048 ops/sec)
# → 1000 requests cost 1.235s (809.7058 ops/sec)

# Ожидаемые результаты (NVMe SSD):
# - Write: > 500 ops/sec
# - Read: > 10000 ops/sec
# - p99 latency: < 10 мс
```

*Полное руководство по бенчмаркингу:* **[Бенчмаркинг etcd](../../etcd/benchmarking.md)**.

### Обновление etcd в Kubernetes

Обновление etcd — критичная операция, требующая последовательного выполнения на каждом узле Control Plane.

**Порядок обновления (kubeadm-кластер):**

```bash
# 1. СОЗДАЙТЕ СНАПШОТ ПЕРЕД ЛЮБЫМИ ИЗМЕНЕНИЯМИ
k-etcdctl snapshot save /var/lib/kube-backups/etcd-pre-upgrade-$(date +%F).db

# 2. Обновите etcd на ПЕРВОМ узле (сначалаfollower)
#    Обновите манифест etcd.yaml (новый image tag)
#    etcd.yaml → image: registry.k8s.io/etcd:3.5.15-0

# 3. Перезапустите etcd (переместите манифест)
mv /etc/kubernetes/manifests/etcd.yaml /tmp/ && sleep 30 && mv /tmp/etcd.yaml /etc/kubernetes/manifests/

# 4. Проверьте здоровье после обновления
k-etcdctl endpoint health --cluster -w table
k-etcdctl member list -w table

# 5. Повторите для каждого узла (поочередно, с интервалом > 30 сек)

# 6. ПОСЛЕ ОБНОВЛЕНИЯ ВСЕХ УЗЛОВ — проверьте кворум
k-etcdctl endpoint status --cluster -w table
```

**Чего ожидать при обновлении:**
- 1-2 смены лидера (по одной на обновляемый узел) — это нормально
- Более 5 смен лидера за обновление — проблема (проверьте сеть/диск)
- Кратковременные ошибки `etcdserver: request timed out` — нормальны (< 5 сек)
- Если ошибки длятся > 30 сек — откатывайте на предыдущую версию

**Откат etcd:**
```bash
# 1. Остановите API-сервер и etcd на всех узлах
mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/
mv /etc/kubernetes/manifests/etcd.yaml /tmp/

# 2. Восстановите из снапшота (на ПЕРВОМ узле)
etcdutl snapshot restore /var/lib/kube-backups/etcd-pre-upgrade-$(date +%F).db \
  --data-dir /var/lib/etcd-restored

# 3. Обновите data-dir в манифесте etcd.yaml
#    --data-dir=/var/lib/etcd-restored

# 4. Запустите etcd и API-сервер
mv /tmp/etcd.yaml /etc/kubernetes/manifests/
mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/
```

*Подробнее:* **[Обновление кластеров Kubernetes](../../Kubernetes/Operations/upgrading_clusters.md)**.

---

## Резервное копирование и восстановление

### Создание снапшота (Online Backup)

Снапшот etcd — единственный надежный способ забекапить весь кластер K8s целиком. Выполняйте его перед мажорными обновлениями кластера и регулярно по расписанию.

```bash
# Создание бекапа
k-etcdctl snapshot save /var/lib/kube-backups/etcd-snapshot-$(date +%F).db
# → Snapshot saved at /var/lib/kube-backups/etcd-snapshot-2026-08-30.db

# Проверка целостности созданного файла (используется etcdutl)
etcdutl snapshot status /var/lib/kube-backups/etcd-snapshot-$(date +%F).db -w table
# → +---------+----------+------------+--------------------------------+
# → | REVISION | TOTAL KEYS | TOTAL SIZE | COMPACT REVISION |
# → +---------+----------+------------+--------------------------------+
# → | 12345678 | 154200 | 24 MB | 12340000 |
# → +---------+----------+------------+--------------------------------+

# Проверка целостности (verify) — проверяет контрольные суммы
etcdutl snapshot verify /var/lib/kube-backups/etcd-snapshot-$(date +%F).db
# → Snapshot file is valid: checksum matches

# Автоматическое резервное копирование (cron example)
# Добавьте в crontab на каждом узле etcd:
0 2 * * * /usr/local/bin/k-etcdctl snapshot save /var/lib/kube-backups/etcd-snapshot-$(date +\%F).db && \
  etcdutl snapshot verify /var/lib/kube-backups/etcd-snapshot-$(date +\%F).db && \
  find /var/lib/kube-backups/ -name "etcd-snapshot-*.db" -mtime +7 -delete
```

**Важно关于 снапшотов:**
- Снапшот содержит **всё** — все K8s объекты, секреты, конфигурации
- `snapshot save` — online-операция (не останавливает etcd)
- `snapshot restore` — **offline**-операция (требует остановки etcd)
- Всегда проверяйте снапшот сразу после создания (`etcdutl snapshot verify`)
- Храните снапшоты минимум 7 дней, включая перед каждым обновлением

### Восстановление при аварии (Offline Restore)

Восстановление выполняется, когда кластер полностью разрушен или потерян кворум. Операция требует остановки Control Plane.

**Pre-flight checklist:**
- Определите, какой снапшот использовать (последний проверенный)
- Убедитесь, что все узлы Control Plane доступны
- Создайте резервную копию текущего `data-dir` на каждом узле (на случай неудачного restore)
- Убедитесь, что версия etcd для restore совпадает с версией в снапшоте (или новее)

```bash
# 1. Остановите API-сервер и etcd (убрав манифесты из /etc/kubernetes/manifests/)
mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/
mv /etc/kubernetes/manifests/etcd.yaml /tmp/
# Дождитесь полной остановки:
sleep 30

# 2. Сделайте бэкап текущего data-dir (на случай неудачи)
cp -r /var/lib/etcd /var/lib/etcd-backup-$(date +%F)

# 3. Восстановите данные из файла в новую директорию
etcdutl snapshot restore /var/lib/kube-backups/etcd-snapshot.db \
  --data-dir /var/lib/etcd-from-backup \
  --name etcd-node-1 \
  --initial-cluster "etcd-node-1=https://10.0.0.11:2380,etcd-node-2=https://10.0.0.12:2380,etcd-node-3=https://10.0.0.13:2380" \
  --initial-advertise-peer-urls https://10.0.0.11:2380 \
  --initial-cluster-token k8s-etcd-cluster
# → recovered cluster from saved snapshot
# → added member etcd-node-1 https://10.0.0.11:2380 to cluster 8e9e05f54f240d12

# 4. Обновите конфигурацию etcd: Укажите новый data-dir (/var/lib/etcd-from-backup) в манифесте etcd.yaml

# 5. Запустите компоненты: Верните манифесты в /etc/kubernetes/manifests/
mv /tmp/etcd.yaml /etc/kubernetes/manifests/
mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/

# 6. Проверьте восстановление
k-etcdctl endpoint health --cluster -w table
k-etcdctl member list -w table
kubectl get nodes
```

**Восстановление одноузлового etcd ( fastest recovery ):**
```bash
# Для одноузлового кластера (kubeadm без HA):
etcdutl snapshot restore /var/lib/kube-backups/etcd-snapshot.db \
  --data-dir /var/lib/etcd-restored \
  --name etcd-node-1 \
  --initial-cluster "etcd-node-1=https://127.0.0.1:2380" \
  --initial-advertise-peer-urls https://127.0.0.1:2380

# Замените data-dir в манифесте и перезапустите
```

*Детальное руководство по восстановлению многоузлового кворума:* **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)**.

---

## Продвинутая диагностика: "Request entity too large"

Если Kubernetes возвращает ошибку `etcdserver: request is too large`, это означает, что размер объекта (например, ConfigMap или Secret) превышает `max-request-bytes` (по умолчанию 1.5 MB).

**Диагностика:**
```bash
# Проверка текущего лимита (из конфигурации etcd)
ps aux | grep etcd | grep -o 'max-request-bytes=[0-9]*'
# → max-request-bytes=1572864 (1.5 MB)

# Проверка размера проблемного объекта
kubectl get configmap <name> -o json | wc -c
# → 2097152 (2 MB — превышает лимит)

# Просмотр размера всех ConfigMap в namespace
kubectl get configmaps -n <namespace> -o json | jq '.items[] | {name: .metadata.name, size: (. | length)}' | sort -r
```

**Решения:**
*   **Решение 1:** Разбить ConfigMap на несколько частей (рекомендуется).
*   **Решение 2:** Если разбиение невозможно, увеличьте лимит:
    ```bash
    # В манифесте etcd.yaml добавьте:
    - --max-request-bytes=33554432   # 32 MB

    # Также добавьте флаг в kube-apiserver:
    --max-requests-inflight=... (не влияет напрямую, но учитывайте общую нагрузку)

    # В etcd и kube-apiserver max-request-bytes должны совпадать
    ```
*   **Решение 3:** Хранить большие данные в Persistent Volume вместо ConfigMap/Secret.

**Предотвращение:**
- Мониторьте размер ConfigMap/Secret перед применением
- В CI/CD добавьте проверку: `kubectl apply --dry-run=client -f <file> | grep -i "too large"`
- Установите NetworkPolicy или OPA/Gatekeeper限制 максимальный размер объектов

---

## Дополнительная информация

### Best Practices для production-среды

1.  **Диск:** Только NVMe SSD. Задержка `fsync` (метрика `etcd_disk_wal_fsync_duration_seconds`) должна быть **< 10 мс**; при p99 > 100 мс лидер начинает пропускать heartbeat и происходят перевыборы. Желательно размещать данные и WAL на отдельных дисках от системного.
2.  **Размер БД:** Установите `--quota-backend-bytes=8589934592` (8 GB) — это максимум стабильной работы BoltDB. Увеличение требует пропорционального роста RAM.
3.  **Регулярные снапшоты:** Минимум 1 раз в сутки, плюс перед каждым обновлением кластера. Храните снапшоты минимум 7 дней.
4.  **Авто-компакция:** Включите `--auto-compaction-mode=periodic --auto-compaction-retention=5m` для предотвращения разрастания БД.
5.  **mTLS:** Обязательно для всех соединений (peer, client, admin). Два отдельных CA: для peer-соединений и для client-соединений.
6.  **Изоляция etcd:** Не запускайте на узлах с другими нагрузками. Выделите отдельные узлы (3 или 5) только для etcd.
7.  **Мониторинг:** Настройте алерты на `etcd_server_has_leader == 0`, `etcd_server_leader_changes_seen_total > 3/15m`, `etcd_disk_wal_fsync_duration_seconds p99 > 20ms`, `etcd_mvcc_db_total_size_in_bytes / quota > 0.85`.
8.  **Резервное копирование:** Автоматизируйте создание снапшотов с проверкой целостности. Снапшот без `snapshot verify` — ненадежен.
9.  **Clock Sync:** Используйте NTP на всех узлах. Смещение часов > 1 секунды может привести к проблемам с Raft consensus.
10. **Избегайте `kubectl edit`/`kubectl patch` на etcd напрямую:** Все изменения только через API-сервер.

### Edge Cases и известные особенности

*   **Split-Brain при потере кворума:** Если потеряно > n/2 узлов, кластер переходит в read-only режим. Восстановление требует `etcdutl snapshot restore` или `etcdctl member remove` для удаления мертвых членов.
*   **Clock Skew:** etcd использует часы для выборов лидера и логов. Смещение > 1 секунды вызывает перевыборы. Обязательно настройте NTP.
*   **Большой размер Events:** В нестабильных кластерах Events накапливаются быстро и раздувают БД. Настройте `--event-ttl` (по умолчанию 1 час) и регулярно очищайте.
*   **Concurrent Compaction:** Несколько процессов компакции одновременно вызывают `etcd mvcc: database space exceeded`. Компакция должна выполняться одним процессом.
*   **Snapshot при большом размере БД:** Если БД > 8 GB, `snapshot save` может выполняться долго и блокировать запись. Выполняйте снапшоты в часы низкой нагрузки.
*   **Restore и initial-cluster-token:** При восстановлении из снапшота **обязательно** указывайте `--initial-cluster-token`. Без него etcd может отклонить подключение узлов, считая их частью другого кластера.
*   **etcd v3.5.x иlearner:** etcd 3.5+ поддерживает learner-узлы (неголосующие члены). Используйте их для безопасного добавления узлов в production.
*   **Auto-compaction-retention и API-сервер:** Параметр `--auto-compaction-retention` etcd **не должен** противоречить `--etcd-compaction-interval` API-сервера. Обычно API-сервер выполняет компакцию, а etcd — нет (оставьте `--auto-compaction-retention=0`).
*   **etcd и Clock jumps в виртуализации:** В VM (ESXi, KVM) возможны скачки времени при миграции. Это может вызвать немедленные перевыборы. Настройте `--election-timeout` >= 5000 мс или изолируйте etcd-VM от миграций.

**Связанные ресурсы:**
*   **[Шпаргалка по командам etcdctl](../../etcd/etcdctl_cheatsheet.md)** — подробный справочник команд.
*   **[Обзор etcd в Kubernetes](./etcd_overview.md)** — архитектурная роль компонента.
*   **[MVCC, версионирование и компакция](../../etcd/mvcc_versioning_and_compaction.md)** — глубокое понимание устройства хранения etcd.
*   **[Резервное копирование в Kubernetes](../Operations/backup-strategies.md)** — сравнение бэкапа etcd с инструментами типа Velero.
*   **[Мониторинг etcd](../../etcd/etcd_monitoring.md)** — ключевые метрики, алерты и Grafana-дашборды.
*   **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)** — построение HA-кластера и восстановление кворума.
*   **[Бенчмаркинг etcd](../../etcd/benchmarking.md)** — тестирование производительности.
