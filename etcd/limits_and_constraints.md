# Лимиты и ограничения etcd

**etcd** имеет жёсткие ограничения по размеру данных, производительности и конфигурации. Их понимание необходимо для capacity planning, troubleshooting и проектирования production-архитектуры.

## Определения

| Термин | Описание |
| :--- | :--- |
| **quota-backend-bytes** | Максимальный размер файла BoltDB (по умолчанию 2 ГБ, максимум 8 ГБ). |
| **max-request-bytes** | Максимальный размер одного gRPC-запроса (по умолчанию 1.5 MB). |
| **WAL segment size** | Размер одного сегмента WAL (64 MB по умолчанию). |
| **snapshot-count** | Количество ревизий между автоматическими снапшотами (10 000 в v3.6+, 100 000 в v3.5). |
| **treeIndex memory** | Память, занимаемая B-деревом в оперативной памяти (примерно 150–300 байт на ключ). |
| **Page size** | Размер страницы BoltDB (4 КБ). |
| **Max keys** | Ограничено RAM и DB size. Практический лимит ~10–20 млн ключей при 8 ГБ БД. |

---

## Основные концепции

### Лимиты размера

| Параметр | Значение | Последствия превышения |
| :--- | :--- | :--- |
| **Max value size** | 1.5 MB (`--max-request-bytes`) | Ошибка `etcdserver: request is too large` |
| **Max key size** | Аналогично value size | Ошибка `etcdserver: request is too large` |
| **Max DB size** | 8 GB (практический лимит) | `NOSPACE` alarm, блокировка записи |
| **Max WAL size** | Ограничен только диском | Медленное восстановление, много сегментов |
| **Max snapshot size** | Ограничен DB size | Долгий restore, возможен OOM при apply |

**Почему 8 GB — практический лимит:**
- bbolt (BoltDB форк) использует B+ tree на диске.
- При > 8 GB начинается деградация производительности (фрагментация, длительный startup).
- `quota-backend-bytes` по умолчанию 2 GB, максимум 8 GB.
- При approached 8 GB требуется external etcd или разделение кластеров.

### Лимиты производительности

| Метрика | Норма (NVMe, 3-node) | Критично |
| :--- | :--- | :--- |
| **Writes/sec** | 10 000–15 000 | > 20 000 (leader overload) |
| **Reads/sec** | 50 000+ (с Watch Cache) | Зависит от клиента |
| **WAL fsync p99** | < 10 ms | > 100 ms (leader flapping) |
| **Backend commit p99** | < 25 ms | > 100 ms |
| **Peer RTT p99** | < 50 ms | > 100 ms (election risk) |
| **Watch connections** | 10 000+ (с watch cache) | > 50 000 (FD exhaustion) |

### Лимиты ключей и памяти

**Примерный расчёт памяти для treeIndex:**
```
treeIndex memory ≈ keys_count × 250 bytes
```

| Количество ключей | treeIndex memory | Общая RAM (с запасом) |
| :--- | :--- | :--- |
| 100 000 | ~25 MB | 4 GB |
| 1 000 000 | ~250 MB | 8 GB |
| 10 000 000 | ~2.5 GB | 16 GB |
| 50 000 000 | ~12.5 GB | 32 GB (не рекомендуется) |

**Правило:** При > 10 млн ключей рассмотрите разделение на несколько etcd-кластеров (например, Events отдельно).

### Лимиты WAL и снапшотов

| Параметр | Значение | Влияние |
| :--- | :--- | :--- |
| **WAL segment size** | 64 MB | Больше сегментов = дольше восстановление |
| **snapshot-count** | 10 000 (v3.6+) | Меньше = чаще создание снапшотов, больше CPU/диск |
| **Max WAL before snapshot** | Ограничен snapshot-count | При 10 000 ревизиях WAL ~ 64–128 MB |
| **Compaction retention** | 5m (K8s default) | Агрессивная компакция = меньше истории, меньше БД |

---

## Практические сценарии

### Capacity Planning: расчёт БД

**Формула:**
```
db_size ≈ keys_count × avg_key_size × 3 (overhead для MVCC)
```

**Пример 1:** K8s кластер на 1000 подов
- Ключей: ~50 000 (pods, services, configmaps, secrets, endpoints)
- Средний размер: ~200 байт
- `db_size ≈ 50 000 × 200 × 3 = 30 MB`
- **Итого:** 30 MB — comfortably в пределах 8 GB.

**Пример 2:** K8s кластер на 5000 подов
- Ключей: ~300 000
- `db_size ≈ 300 000 × 200 × 3 = 180 MB`
- С учетом истории (compaction 5m): ~500 MB–1 GB.
- **Итого:** 1 GB — хорошо.

**Пример 3:** K8s кластер на 20 000 подов с Events
- Ключей: ~2 000 000 (включая Events)
- `db_size ≈ 2 000 000 × 200 × 3 = 1.2 GB`
- С Events: может достигать 3–4 GB.
- **Итого:** 4 GB —接近 к 8 GB лимиту. Рассмотреть External Events etcd.

### Capacity Planning: расчёт RAM

```
RAM ≈ treeIndex + BoltDB cache + WAL buffer + overhead
```

**Минимум для production:**
- **< 1M ключей:** 8 GB RAM
- **1M–10M ключей:** 16 GB RAM
- **> 10M ключей:** 32 GB RAM (или разделение кластеров)

### Когда переходить на External etcd

| Симптом | Действие |
| :--- | :--- |
| `db_total_size` > 6 GB | Планировать migration на external etcd |
| > 5000 подов | Рассмотреть external etcd + прокси |
| `etcd_server_lease_object_count` > 1M | Оптимизировать leases или разделить кластер |
| `watch store is out of space` часто | Увеличить watch cache на API-сервере или разделить кластер |

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `request is too large` | Объект > `max-request-bytes` | Увеличить флаг или разбить объект |
| `database space exceeded` | `db_total_size` > `quota-backend-bytes` | Defrag + compact или увеличить квоту |
| OOM при старте | treeIndex слишком большой для RAM | Увеличить RAM или уменьшить количество ключей |
| Медленный restore | WAL слишком большой | Уменьшить `snapshot-count` |
| Высокое использование FD | Слишком много watch-соединений | Увеличить `LimitNOFILE` или оптимизировать clients |

---

## Best Practices

- **Не ждите NOSPACE:** Алерт на 70% заполнения квоты.
- **Defrag перед увеличением квоты:** Сначала освободите место, потом увеличивайте лимит.
- **Не превышайте 8 GB:** bbolt стабильно работает до 8 GB. При превышении — external etcd.
- **Мониторьте treeIndex:** `process_resident_memory_bytes` должен быть > 2× treeIndex estimated size.
- **Разделяйте кластеры при > 10M ключей:** Events, Critical resources (pods/secrets) — в разные кластеры.

---

## См. также

* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — аппаратные требования.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики размера БД и фрагментации.
* **[Прокси-режим и масштабирование](./proxy_mode.md)** — capacity planning формулы.
* **[Внутреннее устройство хранения](./storage_internals.md)** — page size, CoW, fragmentation.
