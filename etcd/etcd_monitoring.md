# Мониторинг etcd

Мониторинг **etcd** критически важен для стабильности кластера, особенно в Kubernetes. Задержки или сбои в работе etcd напрямую приводят к деградации производительности Control Plane и невозможности изменения состояния кластера. Данный документ является Single Source of Truth для концепций и метрик мониторинга etcd.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Prometheus Exporter** | Встроенный в etcd HTTP-сервер, предоставляющий метрики в формате Prometheus (обычно на порту `2379/metrics`). |
| **Health Check** | Механизм проверки работоспособности узла. Узел считается `healthy`, если он успешно зафиксировал проверочное предложение (proposal) в журнале. |
| **Leader Election** | Процесс в протоколе Raft, гарантирующий наличие одного активного лидера в кластере для обработки операций записи. |
| **Fsync / Fdatasync** | Системные вызовы, заставляющие ОС сбросить данные из кэша на физический диск. Критичны для WAL (Write-Ahead Log) и BoltDB. |
| **RangeStream (v3.7+)** | Новый API для эффективной передачи больших диапазонов ключей, снижающий нагрузку на память и gRPC-канал. |
| **Watch Cache** | Механизм кэширования событий на стороне `kube-apiserver`, мониторинг которого критичен для понимания нагрузки на etcd. |
| **ServiceMonitor** | Custom Resource в Prometheus Operator, определяющая параметры сбора метрик с etcd (TLS, интервал, селекторы). |
| **USE-методология** | Подход к мониторингу ресурсов: Utilization (утилизация), Saturation (насыщение), Errors (ошибки). |
| **RED-методология** | Подход к мониторингу сервисов: Rate (частота запросов), Errors (ошибки), Duration (задержка). |

---

## Основные концепции

### Методологии мониторинга для etcd

Для комплексного покрытия etcd необходимо сочетать несколько методологий:

- **USE (Resources):** Применяется к дискам, CPU и сети. Мониторинг утилизации диска (IOPS), насыщения очередеми WAL и ошибок `fsync`.
- **RED (Service):** Применяется к gRPC API etcd. Частота запросов (`rate`), доля ошибок (`errors`), задержка (`duration`).
- **Golden Signals (Latency/Traffic/Errors/Saturation):** Обобщенный подход, фокусирующийся на четырех ключевых сигналах.

### Почему etcd критически чувствителен к диску

Каждая операция записи в etcd проходит через **WAL** и требует подтверждения большинства (кворума). Процесс записи:

1. Лидер получает gRPC-запрос.
2. Операция записывается в **WAL** с вызовом `fdatasync`.
3. Лидер рассылает операцию фолловерам.
4. После подтверждения кворума операция коммитится.
5. Данные применяются к **treeIndex** (память) и **BoltDB** (диск).

Мониторинг `etcd_disk_wal_fsync_duration_seconds` позволяет отслеживать самый узкий участок этого конвейера. Пики задержки `fsync` > 100 мс приводят к таймаутам Raft, сбоям лидерства и деградации всего кластера.

### Фрагментация базы данных

etcd хранит данные в **BoltDB** (B+ tree). При удалении ключей или compaction-операциях физический размер файла (`etcd_mvcc_db_total_size_in_bytes`) не уменьшается автоматически. Разница между `total` и `in_use` показывает фрагментацию:

- **< 30%**: Нормальное состояние.
- **30–50%**: Требуется планирование дефрагментации.
- **> 50%**: Критично. Рекомендуется немедленное выполнение `etcdctl defrag` в часы минимальной нагрузки.

Фрагментация влияет на время чтения (больший файл = больше дисковых операций) и скорость бэкапа.

### Leases и Watch Cache

- **Leases (Аренды):** Временные ключи с TTL. Мониторинг `etcd_server_lease_expired_total` и `etcd_server_lease_object_count` позволяет обнаружить проблемы с истечением аренд при высокой нагрузке.
- **Watch Cache:** В Kubernetes `kube-apiserver` кэширует события от etcd. При нехватке памяти в кэше или его отключении нагрузка на etcd растет экспоненциально. Мониторинг `etcd_helper_cache_hit_count` / `etcd_helper_cache_miss_count` (на стороне API-сервера) помогает диагностировать эту проблему.

### Доступность и кворум

Для работы кластера etcd необходим кворум (большинство узлов: `(n/2)+1`). Потеря лидера или отсутствие кворума делает кластер доступным только на чтение или полностью неработоспособным.

* **Наличие лидера**: `etcd_server_has_leader`. Должно быть всегда равно **1**. Значение **0** на всех узлах означает критический сбой.
* **Изменения лидерства**: `etcd_server_leader_changes_seen_total`. Частое изменение (flapping) указывает на нестабильность сети или перегрузку CPU/диска.
* **Неудачные предложения**: `etcd_server_proposals_failed_total`. Рост метрики сигнализирует об ошибках записи (например, из-за потери лидерства в процессе).

### Производительность диска и сети

etcd крайне чувствителен к задержкам. Каждая запись должна быть подтверждена большинством и зафиксирована в WAL.

* **WAL Fsync**: `etcd_disk_wal_fsync_duration_seconds`. Основной индикатор скорости записи.
    * **Норма (NVMe SSD)**: p99 < 10 мс. Пики > 100 мс критичны.
* **Backend Commit**: `etcd_disk_backend_commit_duration_seconds`. Время фиксации данных в BoltDB.
    * **Норма**: p99 < 25 мс.
* **Network Latency**: `etcd_network_peer_round_trip_time_seconds`. RTT между узлами кластера.
    * **Норма**: p99 < 50 мс.

### Использование ресурсов и квоты

etcd имеет жесткую квоту на размер БД (по умолчанию 2 ГБ, максимум 8 ГБ). При достижении лимита etcd переходит в режим `NOSPACE` и блокирует запись.

* **Размер БД**: `etcd_mvcc_db_total_size_in_bytes`. Физический размер файла на диске.
* **Использование БД**: `etcd_mvcc_db_total_size_in_use_in_bytes`. Реальный объем данных. Разница между `total` и `in_use` показывает уровень фрагментации. Если фрагментация > 50%, требуется `defrag`.
* **Файловые дескрипторы**: `process_open_fds`. Критично при большом количестве клиентов/Watchers. Лимит ОС (`ulimit -n`) должен быть не менее 40 000.
* **Память (RAM)**: `process_resident_memory_bytes`. Потребление памяти treeIndex и кэшами.

### gRPC API и Watch Cache

Клиентское взаимодействие (особенно в Kubernetes) генерирует значительный трафик, который необходимо отслеживать.

* **Трафик gRPC**:
    * `etcd_network_client_grpc_received_bytes_total` — входящий трафик от клиентов.
    * `etcd_network_client_grpc_sent_bytes_total` — исходящий трафик (основная нагрузка при Watch).
* **Watch Cache (Sidecars)**: В Kubernetes нагрузка на etcd снижается за счет Watch Cache в `kube-apiserver`. Однако при большом количестве объектов (Events, Pods) необходимо следить за `etcd_helper_cache_hit_count` и `etcd_helper_cache_miss_count` (на стороне API-сервера).
* **RangeStream (v3.7+)**: Позволяет мониторить эффективность потоковой передачи больших диапазонов через `etcd_server_range_stream_duration_seconds`.

### Версионные особенности (3.5, 3.6 и 3.7)

* **etcd 3.5**: Версии 3.5.0–3.5.2 имели критические баги повреждения данных. Рекомендуется использовать **3.5.33+**.
* **etcd 3.6**: Введена значительная оптимизация памяти (~50%) за счет снижения `snapshot-count` по умолчанию до 10 000.
* **etcd 3.7 (Current 2026)**: Стабильная версия **v3.7.1**. Полное удаление v2 store, оптимизация gRPC-протокола, внедрение RangeStream и улучшенные метрики надежности лиз (Leases).

---

## Метрики и пороги

Ниже приведена эталонная таблица метрик etcd с порогами для production-сред 2026 года.

| Категория | Метрика | Тип | Норма | Критично | Причина важности |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Здоровье** | `etcd_server_has_leader` | Gauge | =1 | =0 | Отсутствие лидера блокирует запись. |
| **Здоровье** | `etcd_server_leader_changes_seen_total` | Counter | Стабильно | >3 за 15м | Flapping лидера указывает на проблемы с сетью/диском. |
| **Здоровье** | `etcd_server_proposals_failed_total` | Counter | 0 | Рост | Ошибки записи, потеря кворума. |
| **Диск** | `etcd_disk_wal_fsync_duration_seconds` | Histogram | p99 < 10мс | p99 > 100мс | Скорость записи в WAL. |
| **Диск** | `etcd_disk_backend_commit_duration_seconds` | Histogram | p99 < 25мс | p99 > 100мс | Скорость фиксации в BoltDB. |
| **Диск** | `etcd_mvcc_db_total_size_in_bytes` | Gauge | <8 ГБ | >8 ГБ | Размер файла БД (лимит квоты). |
| **Диск** | `etcd_mvcc_db_total_size_in_use_in_bytes` | Gauge | <80% от total | >90% от total | Фрагментация; разница с total нуждается в defrag. |
| **Сеть** | `etcd_network_peer_round_trip_time_seconds` | Histogram | p99 < 50мс | p99 > 100мс | Задержка между узлами кластера. |
| **gRPC** | `etcd_network_client_grpc_received_bytes_total` | Counter | Стабильно | Резкий рост | Входящий трафик клиентов. |
| **gRPC** | `etcd_network_client_grpc_sent_bytes_total` | Counter | Стабильно | Резкий рост | Исходящий трафик (нагрузка при Watch). |
| **Ресурсы** | `process_open_fds` | Gauge | <20 000 | >35 000 | Файловые дескрипторы (лимит ulimit). |
| **Ресурсы** | `process_resident_memory_bytes` | Gauge | <70% RAM | >90% RAM | Память процесса etcd. |
| **Leases** | `etcd_server_lease_expired_total` | Counter | Рост пропорционально TTL | Всплески | Истечение аренд при проблемах с keepalive. |
| **Leases** | `etcd_server_lease_object_count` | Gauge | <500 000 | >1 000 000 | Количество активных аренд. |

---

## Дашборды и визуализация

Для эффективного мониторинга рекомендуется создать дашборд Grafana, объединяющий сигналы etcd и API-сервера. Ниже приведены минимально необходимые панели.

### Панель 1: Здоровье кластера (Availability)

| Панель | Метрика / Запрос | Визуализация |
| :--- | :--- | :--- |
| Leader Status | `etcd_server_has_leader` | Stat (значение) |
| Leader Changes | `rate(etcd_server_leader_changes_seen_total[5m])` | Graph |
| Proposals Failed | `rate(etcd_server_proposals_failed_total[5m])` | Graph |
| DB Size | `etcd_mvcc_db_total_size_in_bytes / 1024 / 1024 / 1024` | Graph (MB/GB) |

### Панель 2: Производительность диска (Saturation)

| Панель | Метрика / Запрос | Визуализация |
| :--- | :--- | :--- |
| WAL Fsync p99 | `histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m]))` | Graph |
| Backend Commit p99 | `histogram_quantile(0.99, rate(etcd_disk_backend_commit_duration_seconds_bucket[5m]))` | Graph |
| Peer RTT p99 | `histogram_quantile(0.99, rate(etcd_network_peer_round_trip_time_seconds_bucket[5m]))` | Graph |

### Панель 3: Ресурсы и фрагментация

| Панель | Метрика / Запрос | Визуализация |
| :--- | :--- | :--- |
| DB Fragmentation | `(etcd_mvcc_db_total_size_in_bytes - etcd_mvcc_db_total_size_in_use_in_bytes) / etcd_mvcc_db_total_size_in_bytes * 100` | Gauge (0–100%) |
| Open FDs | `process_open_fds / process_max_fds * 100` | Gauge (0–100%) |
| Memory RSS | `process_resident_memory_bytes / 1024 / 1024 / 1024` | Graph (GB) |

### Панель 4: gRPC и Watch нагрузка

| Панель | Метрика / Запрос | Визуализация |
| :--- | :--- | :--- |
| Client gRPC Traffic (in) | `rate(etcd_network_client_grpc_received_bytes_total[5m])` | Graph |
| Client gRPC Traffic (out) | `rate(etcd_network_client_grpc_sent_bytes_total[5m])` | Graph |
| RangeStream Duration | `histogram_quantile(0.99, rate(etcd_server_range_stream_duration_seconds_bucket[5m]))` | Graph |

### Рекомендации по размещению

В крупных средах разворачивайте два дашборда:
1. **Per-Node**: подробные метрики по каждому узлу (диск, память, FDs).
2. **Cluster-Level**: сводные метрики лидерства, размера БД и фрагментации.

---

## Алертинг (Prometheus / Grafana)

В крупных средах алертинг должен срабатывать до того, как деградация etcd приведет к отказу API-сервера.

### Правила алертинга

| Алерт | Выражение (PromQL) | Описание / Действие |
| :--- | :--- | :--- |
| **EtcdNoLeader** | `etcd_server_has_leader == 0` | Узел потерял лидера. Проверить сетевую связность и нагрузку на CPU. |
| **EtcdHighFsync** | `histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) > 0.02` | Задержка WAL > 20мс. Индикатор проблем с IOPS на NVMe. |
| **EtcdLeaderChanges** | `rate(etcd_server_leader_changes_seen_total[15m]) > 3` | Частое переизбрание лидера (flapping). Проверить стабильность сети. |
| **EtcdDbQuotaFull** | `etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes > 0.85` | Заполнение БД на 85%. Выполнить `compaction` и `defrag`. |
| **EtcdHighFDUsage** | `process_open_fds / process_max_fds > 0.8` | Использование дескрипторов > 80%. Проверить количество Watch-соединений. |
| **EtcdGRPCErrorRate** | `sum(rate(grpc_server_handled_total{grpc_code!="OK"}[5m])) > 5` | Рост ошибок gRPC. Проверить логи на наличие `context canceled`. |
| **EtcdHighFragmentation** | `(etcd_mvcc_db_total_size_in_bytes - etcd_mvcc_db_total_size_in_use_in_bytes) / etcd_mvcc_db_total_size_in_bytes > 0.5` | Фрагментация БД > 50%. Выполнить `etcdctl defrag`. |
| **EtcdLeaseExpirySpike** | `rate(etcd_server_lease_expired_total[5m]) > 1000` | Всплеск истечения аренд. Проверить нагрузку на Watch и keepalive. |

### Запись правил (Recording Rules)

Для снижения нагрузки на Prometheus при частых quantile-запросах создайте recording rules:

```yaml
groups:
- name: etcd.performance
  rules:
  - record: job:etcd_disk_wal_fsync_duration_seconds:histogram_quantile_99
    expr: histogram_quantile(0.99, sum(rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) by (le, job))
  - record: job:etcd_network_peer_round_trip_time_seconds:histogram_quantile_99
    expr: histogram_quantile(0.99, sum(rate(etcd_network_peer_round_trip_time_seconds_bucket[5m])) by (le, job))
```

### Иерархия критичности

| Severity | Пример | Канал уведомления |
| :--- | :--- | :--- |
| **P0 (Emergency)** | `EtcdNoLeader` на всех узлах | PagerDuty / Opsgenie (звонок) |
| **P1 (Critical)** | `EtcdHighFsync` p99 > 100мс | Slack #critical-alerts |
| **P2 (Warning)** | `EtcdHighFDUsage` > 80% | Slack #sre-alerts |
| **P3 (Info)** | Рост `etcd_server_lease_expired_total` | Grafana dashboard only |

### Подавление и группировка

В Alertmanager настройте:
- **Группировка** (`group_by: [alertname, cluster]`): объединяйте алерты по кластеру.
- **Подавление (Inhibition)**: если сработал `EtcdNoLeader`, подавляйте `EtcdGRPCErrorRate` и `EtcdLeaderChanges`, так как они являются следствием.
- **Silencing**: автоматически создавайте сайленсы на 30 минут при плановых дефрагментациях через CI/CD.

---

## Практические сценарии

### Ручная диагностика здоровья

Использование `etcdctl` (v3.7+) для быстрой проверки состояния кластера:

```bash
# Проверка здоровья всего кластера
etcdctl endpoint health --cluster
# → 127.0.0.1:2379 is healthy: successfully committed proposal: took = 1.2ms

# Проверка статуса, версии и размера БД
etcdctl endpoint status --write-out=table
# → +----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+
# → |    ENDPOINT    |        ID        | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX |
# → +----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+
# → | 127.0.0.1:2379 | 8e9e05f54f240d12 |  3.7.1  |  120 MB |    true   |    false   |        15 |     510432 |             510432 |
# → +----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+
```

**Валидация:**
- `etcd_server_has_leader` == 1 на всех узлах.
- `RAFT INDEX` и `RAFT APPLIED INDEX` на follower'ах не отстают от лидера более чем на 1000.

### Диагностика WAL и BoltDB через etcdutl

`etcdutl` (v3.6+) позволяет анализировать WAL и снапшоты:

```bash
# Статистика WAL (количество записей, размер файлов)
etcdutl wal show /var/lib/etcd/wal/
# → WAL records: 15420, file size: 1.2GB

# Информация о снапшоте
etcdutl snapshot status /var/lib/etcd/member/snap/db
# → Hash: 1a2b3c4d, Revision: 512340, Total key count: 1254300
```

**Валидация:**
- Количество WAL записей должно соответствовать ожидаемой нагрузке.
- Revision в снапшоте должен совпадать с `RAFT APPLIED INDEX`.

### Проверка метрик через TLS

Если etcd требует сертификаты (стандарт в Kubernetes):

```bash
curl --cacert /etc/etcd/ca.crt --cert /etc/etcd/server.crt --key /etc/etcd/server.key \
     https://127.0.0.1:2379/metrics | grep etcd_server_has_leader
# → etcd_server_has_leader 1
```

### Мониторинг во время обновления etcd

При обновлении версии etcd (например, 3.5 → 3.7) мониторинг помогает предотвратить простои:

1. **До обновления:** снимите baseline метрик (`wal fsync`, `db size`, `leader changes`).
2. **Во время обновления:** следите за `etcd_server_leader_changes_seen_total`. Ожидается 1–2 смены лидера (по одному на узел). Более 5 смен за 10 минут — остановите каскад.
3. **После обновления:** проверьте `etcd_disk_wal_fsync_duration_seconds`. В 3.7+ ожидается снижение p99 на 10–20% за счет оптимизаций.

### Проверка дефрагментации

Планирование дефрагментации по фрагментации:

```bash
# Вычислить фрагментацию
FRAG=$(etcdctl defrag --cluster 2>&1 | grep -oP '\d+')
# Нет прямого вывода фрагментации, используйте метрики:
curl -s http://localhost:2379/metrics | grep etcd_mvcc_db_total_size
```

**Рекомендация:** выполняйте `etcdctl defrag` по очереди на узлах (не одновременно) в часы минимальной нагрузки. Это возвращает свободное место в ОС и ускоряет чтение.

### Мониторинг бэкапов

Добавьте проверку актуальности бэкапов в мониторинг:

```bash
# Проверить время последнего снапшота
ls -lht /backup/etcd-snapshot*.db
# → -rw-r--r-- 1 root root 1.2G Aug 23 12:00 etcd-snapshot-2026-08-23.db

# Проверить валидность снапшота
etcdutl snapshot verify /backup/etcd-snapshot-2026-08-23.db
# → snapshot verify passed, revision: 512340
```

**Автоматизация:** добавьте cron-задачу или Kubernetes CronJob, который ежедневно создает снапшот и выгружает его в S3. Если снапшот старше 24 часов — алерт.

### Диагностика проблем с Watch Cache на стороне API-сервера

Если `etcd_helper_cache_hit_count` падает, а `etcd_helper_cache_miss_count` растет:

1. **Увеличьте размер кэша** в `kube-apiserver`:
   ```bash
   --watch-cache-sizes=deployments=256Mi,configmaps=128Mi,secrets=128Mi
   ```
2. **Проверьте количество объектов:** слишком много Events (> 10 000 в минуту) может переполнить кэш.
3. **Убедитесь, что не отключен Watch Cache** (`--watch-cache=disabled`).

---

## Оптимизация производительности

Для стабильной работы etcd в высоконагруженных кластерах необходимо проводить тюнинг на нескольких уровнях:

### 1. Аппаратный уровень и ОС
* **Дисковая подсистема**: Использование **локальных NVMe SSD** является обязательным. Рекомендуется выделять отдельный физический диск под WAL (`--data-dir` или через симлинки) для минимизации задержек `fsync`.
* **Приоритеты процессов**: Гарантируйте ресурсы etcd даже при общей нагрузке на узел:
    * `ionice -c2 -n0` (Real-time I/O priority).
    * `nice -n -10` (High CPU priority).
* **CPU Governor**: Установите режим `performance` для минимизации задержек переключения частот.

### 2. Тюнинг параметров etcd
* **`--snapshot-count`**: В etcd 3.6+ стандарт — 10 000. Это снижает нагрузку на диск при создании снимков.
* **`--heartbeat-interval`**: 100мс (стандарт). В сетях с высокими задержками (multi-AZ) может потребоваться увеличение до 250мс.
* **`--election-timeout`**: Должен быть в 5–10 раз больше `heartbeat-interval` (обычно 1000мс–2000мс).
* **`--quota-backend-bytes`**: Рекомендуется устанавливать **8 ГБ** (максимально поддерживаемый стабильный размер для BoltDB).

### 3. Архитектурные оптимизации
* **Разделение трафика**: Выносите ресурс `Events` в отдельный кластер etcd. События в Kubernetes генерируют огромный поток записей, которые могут замедлять работу API-сервера с критическими ресурсами (`Pods`, `Secrets`).
* **Автоматическая компакция**: Настройте `--auto-compaction-retention=5m` для агрессивной очистки ревизий в K8s.
* **Дефрагментация**: Запланируйте поочередный `etcdctl defrag` для узлов кластера в часы минимальной нагрузки для возврата свободного места в ОС.

---

## Дополнительная информация

### Специфика Kubernetes

Настройка ServiceMonitor для `kube-prometheus-stack` описана в **[инструкции по etcd-monitoring](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/etcd-monitoring.md)**.

### См. также

*   **[Архитектура и основные концепции etcd](./architecture-and-concepts.md)** — обзор компонентов etcd
*   **[Кластеризация и восстановление](./clustering_and_recovery.md)** — развёртывание и бэкап кластера
*   **[Тестирование производительности](./benchmarking.md)** — check perf, fio, throughput ceiling.
*   **[Систематический troubleshooting](./troubleshooting.md)** — playbook для production.
*   **[Proposal Pipeline](./proposal_pipeline.md)** — детальный write path.
*   **[Сетевые разделения](./network_partitions.md)** — split-brain и gray failures.
*   **[Лимиты и ограничения](./limits_and_constraints.md)** — size limits и capacity planning.
*   **[Аварийное восстановление](./emergency_recovery.md)** — `--force-new-cluster` и DR.
*   **[etcd в Kubernetes](./kubernetes_integration.md)** — интеграция с K8s.
*   **[Etcd в Kubernetes](../Kubernetes/Concepts/etcd_overview.md)** — практическое использование в production
*   **[Алгоритм Raft](./raft_consensus.md)** — теория консенсуса
*   **[MVCC и компакция](./mvcc_versioning_and_compaction.md)** — как избежать разрастания БД
*   **[Рекомендации по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)** — методологии и стратегии алертинга
*   **[Архитектура наблюдаемости в Kubernetes](../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md)** — стек телеметрии
