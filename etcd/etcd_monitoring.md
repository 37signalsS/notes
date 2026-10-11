# Мониторинг etcd

**Актуально для:** etcd 3.7.x (текущая стабильная ветка, patch v3.7.2 от 2026-09-22). Поведение, специфичное для 3.5/3.6, отмечено отдельно.

Мониторинг **etcd** критически важен для стабильности кластера, особенно в Kubernetes. Задержки или сбои в работе etcd напрямую приводят к деградации производительности Control Plane и невозможности изменения состояния кластера. Данный документ покрывает концепции, метрики, пороги, алерты, дашборды и практические сценарии мониторинга etcd.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Prometheus Exporter** | Встроенный в etcd HTTP-эндпоинт `/metrics` в формате Prometheus. По умолчанию обслуживается на клиентском порту (2379), дополнительно — на URL'ах из `--listen-metrics-urls`. |
| **Health Check** | Механизм проверки работоспособности узла. Узел считается `healthy`, если он успешно зафиксировал проверочное предложение (proposal) в журнале. |
| **Leader Election** | Процесс в протоколе Raft, гарантирующий наличие одного активного лидера в кластере для обработки операций записи. |
| **Fsync / Fdatasync** | Системные вызовы, заставляющие ОС сбросить данные из кэша на физический диск. Критичны для WAL (Write-Ahead Log) и BoltDB. |
| **RangeStream (3.7+)** | Server-streaming RPC для передачи больших диапазонов ключей порциями (chunks) вместо буферизации всего ответа. Снижает пиковое потребление памяти на сервере и клиенте. Не поддерживает нестандартную сортировку и фильтры по ревизиям (возвращает `Unimplemented`), не работает через gRPC proxy. В Kubernetes 1.37 включается feature gate `EtcdRangeStream` (Beta, по умолчанию включён). |
| **Watch Cache** | Механизм кэширования событий на стороне `kube-apiserver`, мониторинг которого критичен для понимания нагрузки на etcd. |
| **ServiceMonitor** | Custom Resource в Prometheus Operator, определяющая параметры сбора метрик с etcd (TLS, интервал, селекторы). |
| **USE-методология** | Подход к мониторингу ресурсов: Utilization (утилизация), Saturation (насыщение), Errors (ошибки). |
| **RED-методология** | Подход к мониторингу сервисов: Rate (частота запросов), Errors (ошибки), Duration (задержка). |
| **etcdctl / etcdutl** | `etcdctl` — онлайн-операции (health, status, snapshot save, defrag). `etcdutl` (с v3.6) — офлайн-операции: `snapshot status`, `snapshot restore`, `hashkv`, `defrag --data-dir`. Чтение WAL — утилита `etcd-dump-logs`. |

---

## Предварительные требования

- **etcd** 3.5+ (для RangeStream и актуальных метрик — 3.7+). Текущие patch-релизы на 2026-09-22: 3.7.2, 3.6.15, 3.5.34.
- **Prometheus** с доступом к эндпоинту `/metrics` (прямой или через ServiceMonitor) и **Grafana** для визуализации.
- **TLS-сертификаты** клиента etcd (CA, client.crt, client.key), если включена TLS-аутентификация — стандарт в Kubernetes.
- **Интервал сбора** 15–30 с; для `histogram_quantile` по дисковым метрикам достаточно окна 5m.
- **Доступ к узлам** для диагностики через `etcdctl`/`etcdutl` и чтения WAL/снапшотов.

## Основные концепции

### Методологии мониторинга для etcd

Для комплексного покрытия etcd необходимо сочетать несколько методологий:

- **USE (Resources):** Применяется к дискам, CPU и сети. Мониторинг утилизации диска (IOPS), насыщения очередями WAL и ошибок `fsync`.
- **RED (Service):** Применяется к gRPC API etcd. Частота запросов (`rate`), доля ошибок (`errors`), задержка (`duration`).
- **Golden Signals (Latency/Traffic/Errors/Saturation):** Обобщенный подход, фокусирующийся на четырех ключевых сигналах.

### Почему etcd критически чувствителен к диску

Каждая операция записи в etcd проходит через **WAL** и требует подтверждения большинства (кворума). Процесс записи:

1. Лидер получает gRPC-запрос.
2. Операция записывается в **WAL** с вызовом `fdatasync`.
3. Лидер рассылает операцию фолловерам.
4. После подтверждения кворума операция коммитится.
5. Данные применяются к **treeIndex** (память) и **BoltDB** (диск).

Мониторинг `etcd_disk_wal_fsync_duration_seconds` позволяет отслеживать самый узкий участок этого конвейера. Устойчивые пики задержки `fsync` > 100 мс приводят к таймаутам выборов Raft, сбоям лидерства и деградации всего кластера.

### Фрагментация базы данных

etcd хранит данные в **BoltDB** (B+ tree). При удалении ключей или compaction-операциях физический размер файла (`etcd_mvcc_db_total_size_in_bytes`) не уменьшается автоматически. Разница между `total` и `in_use` показывает фрагментацию:

- **< 30%**: Нормальное состояние.
- **30–50%**: Требуется планирование дефрагментации.
- **> 50%**: Критично. Рекомендуется немедленное выполнение `etcdctl defrag` в часы минимальной нагрузки.

Фрагментация влияет на время чтения (больший файл = больше дисковых операций) и скорость бэкапа.

### Leases и Watch Cache

- **Leases (Аренды):** Временные ключи с TTL. Метрика истечения аренд — `etcd_debugging_server_lease_expired_total` (обратите внимание на префикс `etcd_debugging_` — метрика относится к нестабильному debugging-пространству). etcd не экспортирует gauge с общим числом активных аренд: число leases получают через `etcdctl lease list`, а распределение объектов на одну аренду — через гистограмму `etcd_lease_object_counts` на стороне `kube-apiserver`. Всплески помогают обнаружить проблемы с keepalive при высокой нагрузке.
- **Watch Cache:** В Kubernetes `kube-apiserver` кэширует события от etcd. При нехватке памяти в кэше или его отключении нагрузка на etcd растет экспоненциально. Мониторинг `etcd_helper_cache_hit_count` / `etcd_helper_cache_miss_count` (на стороне API-сервера) помогает диагностировать эту проблему.

### Доступность и кворум

Для работы кластера etcd необходим кворум (большинство узлов: `(n/2)+1`). Потеря лидера или отсутствие кворума делает кластер доступным только на чтение или полностью неработоспособным.

* **Наличие лидера**: `etcd_server_has_leader`. Должно быть всегда равно **1**. Значение **0** на всех узлах означает критический сбой.
* **Изменения лидерства**: `etcd_server_leader_changes_seen_total`. Частое изменение (flapping) указывает на нестабильность сети или перегрузку CPU/диска.
* **Неудачные предложения**: `etcd_server_proposals_failed_total`. Рост метрики сигнализирует об ошибках записи (например, из-за потери лидерства в процессе).
* **Отложенные предложения**: `etcd_server_proposals_pending`. Устойчивый рост — признак того, что запись не успевает коммититься (диск, сеть, потеря кворума).

### Производительность диска и сети

etcd крайне чувствителен к задержкам. Каждая запись должна быть подтверждена большинством и зафиксирована в WAL.

* **WAL Fsync**: `etcd_disk_wal_fsync_duration_seconds`. Основной индикатор скорости записи.
    * **Норма (NVMe SSD)**: p99 < 10 мс. Пики > 100 мс критичны.
* **Backend Commit**: `etcd_disk_backend_commit_duration_seconds`. Время фиксации данных в BoltDB.
    * **Норма**: p99 < 25 мс.
* **Network Latency**: `etcd_network_peer_round_trip_time_seconds`. RTT между узлами кластера.
    * **Норма**: p99 < 50 мс и заметно меньше `--heartbeat-interval` (100 мс по умолчанию). RTT, приближающийся к heartbeat-interval, приводит к переизбраниям лидера.

### Использование ресурсов и квоты

etcd имеет жесткую квоту на размер БД (по умолчанию 2 ГБ, максимум 8 ГБ). При достижении лимита etcd переходит в режим `NOSPACE` и блокирует запись.

* **Размер БД**: `etcd_mvcc_db_total_size_in_bytes`. Физический размер файла на диске.
* **Использование БД**: `etcd_mvcc_db_total_size_in_use_in_bytes`. Реальный объем данных. Разница между `total` и `in_use` показывает уровень фрагментации. Если фрагментация > 50%, требуется `defrag`.
* **Файловые дескрипторы**: `process_open_fds` / `process_max_fds`. Критично при большом количестве клиентов/Watchers. etcd предупреждает при 80% лимита; лимит определяется ожидаемым числом клиентов и watchers (см. [тюнинг ОС](./kernel_tuning.md)).
* **Память (RAM)**: `process_resident_memory_bytes`. Потребление памяти treeIndex и кэшами. В etcd 3.6+ потребление памяти снижено на ~50% по сравнению с 3.5 (см. раздел про версии).

### gRPC API и Watch Cache

Клиентское взаимодействие (особенно в Kubernetes) генерирует значительный трафик, который необходимо отслеживать.

* **Трафик gRPC**:
    * `etcd_network_client_grpc_received_bytes_total` — входящий трафик от клиентов.
    * `etcd_network_client_grpc_sent_bytes_total` — исходящий трафик (основная нагрузка при Watch).
* **Watch Cache (Sidecars)**: В Kubernetes нагрузка на etcd снижается за счет Watch Cache в `kube-apiserver`. Однако при большом количестве объектов (Events, Pods) необходимо следить за `etcd_helper_cache_hit_count` и `etcd_helper_cache_miss_count` (на стороне API-сервера).
* **RangeStream (3.7+)**: etcd не экспортирует отдельной гистограммы длительности RangeStream. Эффективность потоковой передачи больших диапазонов мониторится на стороне `kube-apiserver`:
    * `etcd_request_duration_seconds_count{operation="listStream"}` — ненулевой счетчик означает, что RangeStream используется (K8s 1.37+, gate `EtcdRangeStream`).
    * `etcd_request_duration_seconds_bucket{operation="listStream"}` — задержка потоковых чтений.
    * Нулевой `listStream` при etcd 3.7+ означает, что gate выключен (`--feature-gates=EtcdRangeStream=false`) или etcd старше 3.7: kube-apiserver автоматически откатывается на unary `Range` при первом `Unimplemented`.

### Трассировка (distributed tracing)

etcd умеет экспортировать распределённые трейсы по OTLP (gRPC) на коллектор (OpenTelemetry Collector, Jaeger с OTLP, Tempo и т. п.). Трейсы показывают путь запроса через предложение → Raft → apply и полезны для диагностики медленных клиентских операций, когда метрик недостаточно.

Активация (v3.7):

```bash
etcd \
  --enable-distributed-tracing=true \
  --distributed-tracing-address=localhost:4317 \
  --distributed-tracing-service-name=etcd \
  --distributed-tracing-instance-id=etcd-0 \
  --distributed-tracing-sampling-rate=1000000
```

Флаги и значения по умолчанию (v3.7):

| Флаг | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `--enable-distributed-tracing` | `false` | Включить экспорт трейсов |
| `--distributed-tracing-address` | `localhost:4317` | OTLP gRPC endpoint коллектора |
| `--distributed-tracing-service-name` | `etcd` | Имя сервиса; одинаковое на всех узлах |
| `--distributed-tracing-instance-id` | `''` | ID инстанса; **уникальный** для каждого узла |
| `--distributed-tracing-sampling-rate` | `0` | Число сэмплов на миллион спанов: `0` — выкл, `1000000` — все |

Версионные различия:

- **3.5 и 3.6** — те же флаги с префиксом `--experimental-` (`--experimental-enable-distributed-tracing`, `--experimental-distributed-tracing-address` и т. д.).
- **3.7** — префикс убран, экспериментальные формы удалены (см. [совместимость версий](./version_compatibility.md), upgrade-гайд 3.7 «Flags removed»). Используйте не-экспериментальные имена.

**Внимание:** страница официальной документации v3.7 `op-guide/monitoring` устарела и всё ещё показывает `--experimental-*`; авторитетный источник — configuration reference v3.7.

Практика: `--distributed-tracing-instance-id` должен быть уникальным, иначе спаны разных узлов смешиваются; трейсинг добавляет накладные расходы, поэтому снижайте `sampling-rate` вместо полного `1000000`.

### Версионные особенности (3.5, 3.6 и 3.7)

* **etcd 3.5**: Версии 3.5.0–3.5.2 имели критический баг data inconsistency (consistent index не сохранялся атомарно; при неконтролируемом завершении процесса под нагрузкой — SIGKILL, OOM — коммиченные транзакции могли не отражаться на всех узлах). Исправлено в 3.5.3+. Рекомендуется использовать **3.5.34+** (последний patch на 2026-09-22).
* **etcd 3.6**: Введена значительная оптимизация памяти (~50%) за счет снижения `--snapshot-count` по умолчанию с 100 000 до 10 000 и более частой компакции Raft-истории. Введены Kubernetes-style feature gates вместо `--experimental-*` флагов. Офлайн-команды (`snapshot status/restore`, `defrag --data-dir`) перенесены в `etcdutl`. Обновление до 3.6 требует предварительного перехода всех узлов на **3.5.32+**.
* **etcd 3.7 (текущая ветка)**: Стабильная версия **v3.7.2** (2026-09-22). Полное удаление v2 store и всех `--experimental-*` флагов, внедрение RangeStream, миграция с gogo/protobuf на стандартный protobuf, bbolt v1.5.1 и raft v3.7.0. Обновление до 3.7 требует предварительного перехода всех узлов на **3.6.11+**. v3.7.2 исправляет определение `MinimalEtcdVersion` (чтение последней записи снапшота из WAL), чтобы апгрейдированный кластер не читал v2-снапшот вместо v3.

---

## Метрики и пороги

Ниже приведена эталонная таблица метрик etcd с порогами для production-сред 2026 года. Метрики с префиксом `etcd_debugging_` нестабильны между минорными версиями — сверяйте имена с `/metrics` своей версии.

| Категория | Метрика | Тип | Норма | Критично | Причина важности |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Здоровье** | `etcd_server_has_leader` | Gauge | =1 | =0 | Отсутствие лидера блокирует запись. |
| **Здоровье** | `etcd_server_leader_changes_seen_total` | Counter | Стабильно | >3 за 15м | Flapping лидера указывает на проблемы с сетью/диском. |
| **Здоровье** | `etcd_server_proposals_failed_total` | Counter | 0 | Рост | Ошибки записи, потеря кворума. |
| **Здоровье** | `etcd_server_proposals_pending` | Gauge | ~0 | Устойчивый рост | Записи не успевают коммититься (диск/сеть/кворум). |
| **Здоровье** | `etcd_server_heartbeat_send_failures_total` | Counter | 0 | Рост | Лидер не может доставить heartbeats — проблемы сети. |
| **Здоровье** | `etcd_server_read_indexes_failed_total` | Counter | 0 | Рост | Ошибки linearizable reads — потеря кворума или отставание. |
| **Здоровье** | `etcd_server_slow_read_indexes_total` | Counter | 0 | Рост | ReadIndex не синхронизирован с лидером или таймаут. |
| **Здоровье** | `etcd_server_apply_snapshot_in_progress` | Gauge | 0 | =1 длительно | Узел восстанавливается из снапшота — отстал от кластера. |
| **Версия** | `etcd_server_version{server_version=...}` | Gauge | Единый version | Разные версии | Рассинхрон версий в кластере (mixed-version state). |
| **Диск** | `etcd_disk_wal_fsync_duration_seconds` | Histogram | p99 < 10мс | p99 > 100мс | Скорость записи в WAL. |
| **Диск** | `etcd_disk_backend_commit_duration_seconds` | Histogram | p99 < 25мс | p99 > 100мс | Скорость фиксации в BoltDB. |
| **Диск** | `etcd_mvcc_db_total_size_in_bytes` | Gauge | <8 ГБ | >8 ГБ (квота) | Размер файла БД; при достижении квоты — режим NOSPACE. |
| **Диск** | `etcd_mvcc_db_total_size_in_use_in_bytes` | Gauge | Фрагментация <30% | Разрыв total−in_use >50% от total | Фрагментация; большой разрыв требует defrag. |
| **Сеть** | `etcd_network_peer_round_trip_time_seconds` | Histogram | p99 < 50мс | p99 > 100мс или ≈ heartbeat-interval | Задержка между узлами кластера. |
| **gRPC** | `etcd_network_client_grpc_received_bytes_total` | Counter | Стабильно | Резкий рост | Входящий трафик клиентов. |
| **gRPC** | `etcd_network_client_grpc_sent_bytes_total` | Counter | Стабильно | Резкий рост | Исходящий трафик (нагрузка при Watch). |
| **gRPC** | `etcd_network_server_stream_failures_total` | Counter | 0 | Рост | Сбои watch/lease stream — клиенты теряют соединения. |
| **Ресурсы** | `process_open_fds / process_max_fds` | Gauge | <50% | >80% | Файловые дескрипторы; абсолютные значения зависят от ulimit (типично 65536). |
| **Ресурсы** | `process_resident_memory_bytes` | Gauge | <70% RAM | >90% RAM | Память процесса etcd. |
| **Leases** | `etcd_debugging_server_lease_expired_total` | Counter | Рост пропорционально TTL | Всплески | Истечение аренд при проблемах с keepalive. |
| **Leases (K8s)** | `etcd_lease_object_counts` (на kube-apiserver) | Histogram | Стабильно | Рост среднего | Объектов на одну аренду; рост — признак проблем с lease keepalive. |

---

## Дашборды и визуализация

Для эффективного мониторинга рекомендуется создать дашборд Grafana, объединяющий сигналы etcd и API-сервера. Ниже приведены минимально необходимые панели.

### Панель 1: Здоровье кластера (Availability)

| Панель | Метрика / Запрос | Визуализация |
| :--- | :--- | :--- |
| Leader Status | `etcd_server_has_leader` | Stat (значение) |
| Leader Changes | `rate(etcd_server_leader_changes_seen_total[5m])` | Graph |
| Proposals Failed | `rate(etcd_server_proposals_failed_total[5m])` | Graph |
| Proposals Pending | `etcd_server_proposals_pending` | Graph |
| DB Size | `etcd_mvcc_db_total_size_in_bytes / 1024 / 1024 / 1024` | Graph (GB) |

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

### Панель 4: gRPC, Watch и RangeStream нагрузка

| Панель | Метрика / Запрос | Визуализация |
| :--- | :--- | :--- |
| Client gRPC Traffic (in) | `rate(etcd_network_client_grpc_received_bytes_total[5m])` | Graph |
| Client gRPC Traffic (out) | `rate(etcd_network_client_grpc_sent_bytes_total[5m])` | Graph |
| RangeStream usage (K8s) | `sum(rate(etcd_request_duration_seconds_count{operation="listStream"}[5m]))` | Stat / Graph (на kube-apiserver) |
| RangeStream latency p99 (K8s) | `histogram_quantile(0.99, sum(rate(etcd_request_duration_seconds_bucket{operation="listStream"}[5m])) by (le))` | Graph (на kube-apiserver) |

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
| **EtcdNoLeader** | `etcd_server_has_leader == 0` | Узел потерял лидера. Проверить сетевую связность и нагрузку на CPU/диск. |
| **EtcdHighFsync (warning)** | `histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) > 0.02` | Задержка WAL > 20мс. Ранний индикатор проблем с IOPS. |
| **EtcdCriticalFsync** | `histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) > 0.1` | Задержка WAL p99 > 100мс. Критично: риск таймаутов выборов Raft. |
| **EtcdLeaderChanges** | `rate(etcd_server_leader_changes_seen_total[15m]) > 3` | Частое переизбрание лидера (flapping). Проверить стабильность сети и диска. |
| **EtcdDbQuotaFull** | `etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes > 0.85` | Заполнение БД на 85%. Выполнить `compaction` и `defrag`. |
| **EtcdHighFDUsage** | `process_open_fds / process_max_fds > 0.8` | Использование дескрипторов > 80%. Проверить количество Watch-соединений. |
| **EtcdGRPCErrorRate** | `sum(rate(grpc_server_handled_total{grpc_code!="OK"}[5m])) > 5` | Рост ошибок gRPC. Проверить логи на наличие `context canceled`. |
| **EtcdHighFragmentation** | `(etcd_mvcc_db_total_size_in_bytes - etcd_mvcc_db_total_size_in_use_in_bytes) / etcd_mvcc_db_total_size_in_bytes > 0.5` | Фрагментация БД > 50%. Выполнить `etcdctl defrag`. |
| **EtcdLeaseExpirySpike** | `rate(etcd_debugging_server_lease_expired_total[5m]) > 1000` | Всплеск истечения аренд. Проверить нагрузку на Watch и keepalive. |
| **EtcdProposalsPending** | `etcd_server_proposals_pending > 100` | Более 100 отложенных предложений. Запись не успевает коммититься — проверить диск и кворум. |
| **EtcdReadIndexFailures** | `rate(etcd_server_read_indexes_failed_total[5m]) > 0` | Ошибки linearizable reads. Проверить кворум и отставание фолловеров. |
| **EtcdSnapshotStuck** | `etcd_server_apply_snapshot_in_progress == 1` | Узел дольше обычного восстанавливается из снапшота. Проверить сеть и диск фолловера. |

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
| **P1 (Critical)** | `EtcdCriticalFsync` p99 > 100мс, `EtcdProposalsPending` | Slack #critical-alerts |
| **P2 (Warning)** | `EtcdHighFsync` > 20мс, `EtcdHighFDUsage` > 80% | Slack #sre-alerts |
| **P3 (Info)** | Рост `etcd_debugging_server_lease_expired_total` | Grafana dashboard only |

### Подавление и группировка

В Alertmanager настройте:
- **Группировка** (`group_by: [alertname, cluster]`): объединяйте алерты по кластеру.
- **Подавление (Inhibition)**: если сработал `EtcdNoLeader`, подавляйте `EtcdGRPCErrorRate` и `EtcdLeaderChanges`, так как они являются следствием.
- **Silencing**: автоматически создавайте сайленсы на 30 минут при плановых дефрагментациях через CI/CD.

---

## Практические сценарии

### Проверка доступности метрик

```bash
# Эндпоинт /metrics обслуживается на клиентском порту (2379 по умолчанию)
curl -s http://localhost:2379/metrics | head -5
# → # HELP etcd_server_has_leader Whether or not a leader exists. ...

# Если etcd требует TLS (стандарт в Kubernetes):
curl --cacert /etc/etcd/ca.crt --cert /etc/etcd/server.crt --key /etc/etcd/server.key \
     https://127.0.0.1:2379/metrics | grep etcd_server_has_leader
# → etcd_server_has_leader 1

# Если метрики вынесены на отдельный порт (--listen-metrics-urls):
curl -s http://localhost:2381/metrics | grep etcd_server_has_leader
```

**Валидация:** метрика `etcd_server_has_leader` равна 1 на каждом узле; scrape-цель в Prometheus (Status → Targets) имеет статус `UP`.

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
# → | 127.0.0.1:2379 | 8e9e05f54f240d12 |  3.7.2  |  120 MB |    true   |    false   |        15 |     510432 |             510432 |
# → +----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+
```

**Валидация:**
- `etcd_server_has_leader` == 1 на всех узлах.
- `RAFT INDEX` и `RAFT APPLIED INDEX` на follower'ах не отстают от лидера более чем на 1000.
- Колонка `VERSION` одинакова на всех узлах (mixed-version state допустим только во время rolling upgrade).

### Диагностика WAL и снапшотов

WAL не обслуживается через etcdutl (wal-команды отсутствуют); для чтения WAL используется утилита `etcd-dump-logs` из etcd-repo:

```bash
# Установка
go install go.etcd.io/etcd/v3/tools/etcd-dump-logs@latest

# Дамп записей WAL (data-dir содержит member/wal и member/snap)
etcd-dump-logs /var/lib/etcd
# → поток записей WAL; ищите разрывы term/index между узлами

# Информация о снапшоте (simple-вывод: hash, revision, total keys, total size, version)
etcdutl snapshot status /var/lib/etcd/member/snap/db
# → 1a2b3c4d5e6f7890, 512340, 1254300, 1.2 GB, 3.7
```

**Валидация:**
- Revision в снапшоте должен совпадать с `RAFT APPLIED INDEX` (с точностью до последних записей WAL).
- В etcd 3.5 команды `etcdctl snapshot status` / `etcdctl snapshot restore` еще доступны; в 3.6+ они удалены из `etcdctl` — используйте `etcdutl`.

### Проверка RangeStream (etcd 3.7 + K8s 1.37)

```bash
# На стороне etcd: потоковое чтение через etcdctl
etcdctl get --stream --prefix /registry/ | head
# → ключи выдаются порциями (chunks); ошибка Unimplemented означает etcd < 3.7

# На стороне kube-apiserver: подтверждение использования RangeStream
curl -s http://localhost:8080/metrics | grep 'etcd_request_duration_seconds_count{operation="listStream"'
# → etcd_request_duration_seconds_count{operation="listStream",...} 12345
```

**Валидация:** ненулевой счетчик `listStream` означает, что kube-apiserver (K8s 1.37+, gate `EtcdRangeStream`) читает большие коллекции через RangeStream. Нулевой счетчик при etcd 3.7+ — gate выключен или etcd старше 3.7 (apiserver автоматически откатывается на paginated `Range`).

### Мониторинг во время обновления etcd

При обновлении версии etcd (например, 3.6 → 3.7) мониторинг помогает предотвратить простои:

1. **До обновления:** снимите baseline метрик (`wal fsync`, `db size`, `leader changes`). Убедитесь, что все узлы на минимально требуемой patch-версии: для 3.5 → 3.6 — **3.5.32+**, для 3.6 → 3.7 — **3.6.11+**. Сделайте снапшот: `etcdctl snapshot save /backup/pre-upgrade.db`.
2. **Во время обновления:** следите за `etcd_server_leader_changes_seen_total` и `etcd_server_version{server_version=...}`. Ожидается 1–2 смены лидера (по одному на узел) и временный mixed-version state в логах (`updating cluster version using v3 API`). Более 5 смен за 10 минут — остановите каскад.
3. **После обновления:** проверьте `etcd_disk_wal_fsync_duration_seconds` и `etcd_server_version` — все узлы должны показывать единую версию, а в логах появиться `cluster-version":"3.7"`.

### Проверка дефрагментации

Планирование дефрагментации по фрагментации (у `etcdctl defrag` нет вывода процента — вычисляйте из метрик):

```bash
# Текущие размеры из метрик
curl -s http://localhost:2379/metrics | grep -E 'etcd_mvcc_db_total_size(_in_use)?_in_bytes'
# → etcd_mvcc_db_total_size_in_bytes{...} 8589934592
# → etcd_mvcc_db_total_size_in_use_in_bytes{...} 3221225472
# Фрагментация = (8589934592 − 3221225472) / 8589934592 × 100 = 62% → требуется defrag

# Дефрагментация всех членов кластера (обход последовательный, один за другим):
etcdctl defrag --cluster
# → Finished defragmenting etcd member[http://127.0.0.1:2379]. took 2.1s
# → Finished defragmenting etcd member[http://127.0.0.1:22379]. took 1.8s
# → Finished defragmenting etcd member[http://127.0.0.1:32379]. took 2.4s
```

**Рекомендация:** дефрагментация не реплицируется по кластеру — применяется к локальному узлу; флаг `--cluster` последовательно обходит всех членов, поэтому одновременной недоступности всего кластера не возникает. Выполняйте в часы минимальной нагрузки. Офлайн-дефрагментация (`--data-dir`) в 3.6+ доступна только через `etcdutl defrag --data-dir`.

### Мониторинг бэкапов

Добавьте проверку актуальности бэкапов в мониторинг:

```bash
# Проверить время последнего снапшота
ls -lht /backup/etcd-snapshot*.db
# → -rw-r--r-- 1 root root 1.2G Aug 23 12:00 etcd-snapshot-2026-08-23.db

# Проверить валидность снапшота (status читает файл и вычисляет хеш)
etcdutl snapshot status /backup/etcd-snapshot-2026-08-23.db
# → 1a2b3c4d5e6f7890, 512340, 1254300, 1.2 GB, 3.7
```

**Автоматизация:** добавьте cron-задачу или Kubernetes CronJob, который ежедневно создает снапшот и выгружает его в object storage. Если снапшот старше 24 часов — алерт.

### Диагностика проблем с Watch Cache на стороне API-сервера

Если `etcd_helper_cache_hit_count` падает, а `etcd_helper_cache_miss_count` растет:

1. **Увеличьте размер кэша** в `kube-apiserver`:
   ```bash
   --watch-cache-sizes=deployments=256Mi,configmaps=128Mi,secrets=128Mi
   ```
2. **Проверьте количество объектов:** слишком много Events (> 10 000 в минуту) может переполнить кэш.
3. **Убедитесь, что не отключен Watch Cache** (`--watch-cache=disabled`).

### Откат и очистка

При отключении мониторинга удалите recording rules (`job:etcd_*`) и правила алертинга из Prometheus, а также истеките сайленсы Alertmanager, созданные под плановые операции:

```bash
# Проверить активные сайленсы перед удалением
curl -s http://alertmanager:9093/api/v2/silences | jq '.[].status.state'
```

---

## Устранение неисправностей

| Симптом | Вероятная причина | Диагностика / Решение |
| :--- | :--- | :--- |
| `etcd_server_has_leader == 0` на всех узлах | Потеря кворума, сетевой раздел | Проверить связность peer-портов (2380), `etcd_network_peer_round_trip_time_seconds`, логи на `election timeout`; восстановить кворум |
| Рост `etcd_server_leader_changes_seen_total` | Медленный диск (fsync), network jitter, CPU throttling | `etcd_disk_wal_fsync_duration_seconds` p99; `etcd_network_peer_round_trip_time_seconds`; проверить `nice`/`ionice` и CPU governor |
| `etcd_server_proposals_pending` растет | Диск не успевает fsync; потеря фолловеров | WAL fsync p99; проверить `etcd_server_heartbeat_send_failures_total` |
| `database space exceeded` / режим NOSPACE | Достигнут `quota-backend-bytes` | `etcd_mvcc_db_total_size_in_bytes`; compaction + defrag; при необходимости поднять квоту (макс. 8 ГБ) |
| `mvcc: required revision has been compacted` | Watcher отстал от компакции | Увеличить `--auto-compaction-retention` или снизить частоту компакции на стороне kube-apiserver; перезапустить отставший контроллер |
| `process_open_fds` > 80% лимита | Много watchers/клиентов; утечка соединений | `process_open_fds / process_max_fds`; поднять `ulimit -n` (см. [тюнинг ОС](./kernel_tuning.md)); проверить watchers |
| Всплеск `etcd_debugging_server_lease_expired_total` | Проблемы keepalive при нагрузке | Проверить `etcd_lease_object_counts` на apiserver; нагрузку на Watch; число leases через `etcdctl lease list` |
| Разные `etcd_server_version` на узлах | Mixed-version state вне rolling upgrade | Завершить rolling upgrade; при откате — по процедуре downgrade |
| `etcd_server_apply_snapshot_in_progress == 1` длительно | Фолловер отстал и догоняет через снапшот | Проверить сеть и диск фолловера; `etcd_network_peer_round_trip_time_seconds` |

Подробный playbook — в [систематическом troubleshooting](./troubleshooting.md).

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
* **`--snapshot-count`**: В etcd 3.6+ стандарт — 10 000 (в 3.5 — 100 000). Это снижает потребление памяти и нагрузку на диск при создании снимков. Не снижайте ниже 10 000 без необходимости: частые снапшоты увеличивают нагрузку на диск. Если в конфигурации осталось явное значение 100 000 от 3.5 — удалите override, иначе выигрыш 3.6 по памяти теряется.
* **`--heartbeat-interval`**: 100мс (стандарт). В сетях с высокими задержками (multi-AZ) может потребоваться увеличение до 250мс.
* **`--election-timeout`**: Должен быть в 5–10 раз больше `heartbeat-interval` (обычно 1000мс–2000мс).
* **`--quota-backend-bytes`**: Рекомендуется устанавливать **8 ГБ** (максимально поддерживаемый стабильный размер для BoltDB).

### 3. Архитектурные оптимизации
* **Разделение трафика**: Выносите ресурс `Events` в отдельный кластер etcd (`--etcd-servers-overrides=/events#...`). События в Kubernetes генерируют огромный поток записей, которые могут замедлять работу API-сервера с критическими ресурсами (`Pods`, `Secrets`).
* **Компакция**: kube-apiserver выполняет компакцию сам (по умолчанию каждые 5 минут). Включение `--auto-compaction-retention` на стороне etcd создаёт конкурирующие компакции и может вызывать ошибки `mvcc: required revision has been compacted` на длинных watch-потоках — включайте его только если компакция не выполняется на стороне API-сервера.
* **Дефрагментация**: Запланируйте `etcdctl defrag --cluster` (последовательный обход членов) в часы минимальной нагрузки для возврата свободного места в ОС.

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
