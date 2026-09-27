# Диагностика NUMA через dmesg

## Определения

**NUMA-события в dmesg** — выводы ядра, отражающие проблемы с распределением памяти между NUMA-нодами (Non-Uniform Memory Access): предупреждения о миграции страниц, ошибки балансировки NUMA, конфликты привязки памяти к нодам и проблемы с аппаратной топологией. NUMA-архитектура обеспечивает каждый CPU-сокет локальной памятью; обращение к удалённой памяти другой ноды добавляет латентность (70ns локальная vs 130-200ns удалённая).

---

## Базовые концепции

### NUMA-архитектура

```
CPU Socket 0 (NUMA Node 0)     CPU Socket 1 (NUMA Node 1)
  ├─ CPU 0-15                    ├─ CPU 16-31
  ├─ Local RAM 128GB             ├─ Local RAM 128GB
  └─ Interconnect (QPI/UPI)      └─ Interconnect
```

### Типы событий NUMA в dmesg

| Сообщение | Тип | Описание |
|:---|:---|:---|
| `NUMA: node X not online` | Warning | NUMA-нода не активна |
| `NUMA: Failed to initialise zone` | Error | Ошибка инициализации зоны NUMA |
| `numa: Warning: node id X is out of range` | Warning | NUMA-нода вне диапазона |
| `numa_balancing: crashed` | Error | Crash subsystem autoNUMA |
| `ACPI: SLIT: invalid distance` | Warning | Невалидные расстояния между нодами |
| `Movable node X online` | Info | Подвижная NUMA-нода активирована |

---

## Практические сценарии

### Поиск NUMA-событий в dmesg

```bash
# Все NUMA-события
dmesg -T | grep -iE "numa|node.*online|node.*offline|slit|srat|numa_balancing"

# Только ошибки
dmesg -T | grep -iE "numa.*error|numa.*fail|numa.*warning|node.*out.*range"

# Миграция страниц
dmesg -T | grep -iE "numa_migrate|numa_scan|numa_hint|numa_balancing"
```

### Диагностика проблем с NUMA-топологией

```bash
# Проверка NUMA-топологии
numactl --hardware
# -> available: 2 nodes (0-1)
# -> node 0 cpus: 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15
# -> node 0 size: 130682 MB
# -> node 0 free: 98542 MB
# -> node 1 cpus: 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31
# -> node 1 size: 130682 MB
# -> node 1 free: 101234 MB
# -> node distances:
# -> node   0   1
# ->   0:  10  21
# ->   1:  21  10

# Проверка в dmesg
dmesg | grep -iE "NUMA.*node|SRAT|SLIT|numa.*online|numa.*offline"

# Ключевые паттерны:
# -> NUMA: Node 0 with cpumask[0000ffff] online
# -> NUMA: Node 1 with cpumask[ffff0000] online
# -> ACPI: SLIT: valid distance from node 0 to node 1 = 21
```

### Диагностика autoNUMA (numa_balancing)

```bash
# Проверка autoNUMA
dmesg | grep -iE "numa_balancing|numa_scan|numa_hint"

# Ключевые паттерны:
# -> numa_balancing: Enabled
# -> numa_balancing: crashed ( восстановлено автоматически)

# Проверка текущего статуса
cat /proc/sys/kernel/numa_balancing
# -> 2 (enabled + automatic migration)

# Отключение autoNUMA (для latency-sensitive workload)
sudo sysctl -w kernel.numa_balancing=0

# Мониторинг миграций страниц
numastat -p $(pidof <process>)
# -> Per-node process memory usage (in MBs)
# -> Node 0    Node 1     Total
# -> ------    ------     -----
# -> 1234.5    567.8      1802.3  (процесс)
```

### Диагностика миграции страниц

```bash
# Проверка numa_migrate в dmesg
dmesg | grep -iE "numa_migrate|numa_pages|migrate_pages"

# Ключевые паттерны (если включён debug):
# -> numa_migrate_page: migrating page from node 0 to node 1
# -> numa: page migration triggered ( частота зависит от настроек)

# Проверка numa_maps
cat /proc/<pid>/numa_maps | head -20
# -> default anon=1234 dirty=1234 N0=800 N1=434
# -> 7f1234000000 default anon=512 dirty=512 N0=256 N1=256

# Интерпретация:
# -> N0=800: 800 страниц на node 0 (локальная память)
# -> N1=434: 434 страницы на node 1 (удалённая память)
# -> Большое количество N1 при работе на CPU0 = проблема
```

### Диагностика NUMA для приложений

```bash
# PostgreSQL (рекомендуется interleave)
# Проверить dmesg на предупреждения NUMA
dmesg | grep -iE "postgres|numa"
# -> Если видно numa_balancing, significa autoNUMA перемещает страницы PostgreSQL

# Решение: привязать к конкретной ноде
numactl --cpunodebind=0 --membind=0 postgres -D /var/lib/pgsql/data

# Redis (рекомендуется membind)
numactl --membind=0 redis-server /etc/redis.conf

# Проверка эффективности привязки
numastat -p $(pidof redis-server)
# -> Node 0: 95% памяти = правильная привязка
```

### Диагностика NUMA distance проблем

```bash
# Проверка расстояний между нодами
numactl --hardware | grep -A10 "node distances"

# Ключевые паттерны:
# -> node distances: если расстояние 10-30 = норма
# -> Если расстояние > 100 = проблема (может быть из-за SRAT/SLIT ошибок)

# Проверка SRAT/SLIT в dmesg
dmesg | grep -iE "SRAT|SLIT|ACPI.*NUMA"

# Ключевые паттерны:
# -> ACPI: SRAT: Node 0 PXM 0x0 [memory 0x0 - 0x7fffffff]
# -> ACPI: SLIT: valid distance from node 0 to node 1 = 21
# -> ACPI: SLIT: invalid distance -- проблема с ACPI-таблицами
```

---

## Дополнительная информация

### Связанные темы

*   [**NUMA Awareness**](../../../Core/processes/numa_awareness.md) — полный обзор NUMA, numactl, AutoNUMA.
*   [**CPU Isolation**](../../../Core/kernel/cpu_isolation.md) — привязка CPU к NUMA-нодам.
*   [**RSS/RPS/RFS**](../../../Networking/Concepts/rss_rps_rfs.md) — NUMA в контексте сетевой обработки.
*   [**DPDK NUMA**](../../../Networking/Concepts/dpdk/dpdk_technical.md) — NUMA в DPDK.
*   [**Обзор dmesg**](./index.md) — общая архитектура kmsg.
*   [**Поиск и устранение неисправностей**](./troubleshooting.md) — Call Trace, Oops, Panic.
