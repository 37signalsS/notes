# Мониторинг etcd

Мониторинг **etcd** критически важен для стабильности кластера, особенно в Kubernetes. Задержки или сбои в работе etcd напрямую приводят к деградации производительности Control Plane и невозможности изменения состояния кластера.

## Определения

**Prometheus Exporter** — встроенный в etcd HTTP-сервер, предоставляющий метрики в формате Prometheus (обычно на порту `2379/metrics`).

**Health Check** — механизм проверки работоспособности узла. Узел считается `healthy`, если он успешно зафиксировал проверочное предложение (proposal) в журнале.

**Leader Election (Выборы лидера)** — процесс в протоколе Raft, гарантирующий наличие одного активного лидера в кластере.

## Основные концепции

### Доступность и кворум

Для работы кластера etcd необходим кворум (большинство узлов). Потеря лидера или отсутствие кворума делает кластер доступным только на чтение или полностью неработоспособным.

* **Наличие лидера**: Метрика `etcd_server_has_leader` должна быть всегда равна **1**. Значение **0** означает критический сбой кластера.
* **Изменения лидерства**: `etcd_server_leader_changes_seen_total`. Частая смена лидера (flapping) указывает на нестабильность сети или перегрузку дисковой подсистемы.

### Производительность диска и сети

etcd крайне чувствителен к задержкам диска, так как каждая операция записи должна быть зафиксирована в WAL (Write-Ahead Log).

* **WAL Fsync**: `etcd_disk_wal_fsync_duration_seconds`.
    * **Норма**: до 10 мс.
    * **Идеал**: до 2 мс (SSD/NVMe).
    * **Критично**: Превышение 10 мс часто приводит к потере лидерства (лидер не успевает вовремя отправить heartbeat).
* **Backend Commit**: `etcd_disk_backend_commit_duration_seconds`. Время фиксации данных в основном хранилище (db).
* **Network Latency**: `etcd_network_peer_round_trip_time_seconds`. Задержка между узлами кластера.

### Использование ресурсов

* **Размер базы данных**: `etcd_mvcc_db_total_size_in_bytes`.
    * Резкий рост указывает на отсутствие [компакции](./mvcc_versioning_and_compaction.md) или аномальное количество записей в Kubernetes (например, от событий/events).
* **Процессор и память**: `process_cpu_seconds_total` и `process_resident_memory_bytes`. Высокое потребление CPU часто коррелирует с интенсивным чтением или сложными запросами по префиксу.

## Практические сценарии

### Ручная проверка здоровья

Использование `etcdctl` для быстрой диагностики состояния кластера:

```bash
etcdctl endpoint health --cluster
# → 127.0.0.1:2379 is healthy: successfully committed proposal: took = 1.528ms
# → 127.0.0.1:2381 is healthy: successfully committed proposal: took = 1.641ms
# → 127.0.0.1:2383 is healthy: successfully committed proposal: took = 1.712ms
```

### Проверка доступа к метрикам

Если etcd защищен TLS, для сбора метрик требуются сертификаты:

```bash
curl --cacert /etc/etcd/ca.crt --cert /etc/etcd/server.crt --key /etc/etcd/server.key \
     https://127.0.0.1:2379/metrics | grep etcd_server_has_leader
# → etcd_server_has_leader 1
```

## Дополнительная информация

### Специфика Kubernetes

Настройка автоматизированного мониторинга etcd в Kubernetes с использованием Helm-чарта `kube-prometheus-stack` описана в [инструкции по etcd-monitoring](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/etcd-monitoring.md).

### См. также

* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — глубокое понимание WAL и Raft.
* **[MVCC и компакция](./mvcc_versioning_and_compaction.md)** — как избежать разрастания БД и деградации метрик.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — действия при срабатывании алертов о потере кворума.
