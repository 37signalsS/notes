# Поиск и устранение неисправностей

## Типичные ошибки

**1. NoHostAvailableException:**
- **Причина:** Все реплики недоступны или таймаут подключения.
- **Диагностика:** `nodetool status` — проверить состояние узлов.
- **Решение:** Проверить сетевую связность, firewall, DNS. Увеличить `rpc_timeout_in_ms`.

**2. TombstoneOverwhelmingException:**
- **Причина:** Запрос сканирует слишком много Tombstones (>100K по умолчанию).
- **Диагностика:** Проверить логи — `Read X live rows and Y tombstone cells`.
- **Решение:** Пересмотреть модель данных, уменьшить gc_grace_seconds, запустить Repair.

**3. WriteTimeoutException / ReadTimeoutException:**
- **Причина:** Узел не успевает записать/прочитать данные в пределах `rpc_timeout_in_ms`.
- **Диагностика:** `nodetool tpstats` — проверить `Dropped Messages`.
- **Решение:** Увеличить таймауты, проверить disk I/O, добавить узлы.

**4. UnavailableException (кластер видит узлы, но они не здоровы):**
- **Причина:** Разная версия кластерного имени или seed-узлы недоступны.
- **Решение:** Проверить `cluster_name` в cassandra.yaml, убедиться что seed-узлы доступны.

**5. InitializedException:**
- **Причина:** Узел не смог запуститься из-за конфликтующих данных.
- **Решение:** Проверить логи на ошибки конфигурации. Убедиться что `listen_address` и `rpc_address` корректны.

---

## Сбор диагностической информации

```bash
# Полный diagnostic report
nodetool describecluster   # Информация о кластере
nodetool status            # Состояние узлов
nodetool info              # Информация об узле
nodetool tpstats           # Статистика потоков
nodetool cfstats           # Статистика по таблицам
nodetool compactionstats   # Текущие Compaction
nodetool netstats          # Сетевая статистика
nodetool proxyhistograms   # Гистограммы задержек
```

---

## См. также
- **[Мониторинг и observability](./monitoring.md)** — метрики, nodetool, Prometheus.
- **[Тюнинг производительности](./performance.md)** — Tombstones, антипаттерны.
- **[Бэкап и восстановление](./backup-recovery.md)** — восстановление после сбоев.
