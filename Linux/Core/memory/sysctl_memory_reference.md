# Справочник sysctl-параметров памяти в Linux

## Определения

**sysctl** — интерфейс ядра Linux для чтения и изменения параметров/runtime-настроек операционной системы. Параметры памяти управляются через файлы в `/proc/sys/vm/` и определяют поведение аллокатора страниц, свопинга, writeback и защиты от нехватки ресурсов.

**Параметры persistent** — настройки, применяемые после каждой загрузки. Хранятся в `/etc/sysctl.d/*.conf` и применяются через `sysctl -p` или `systemd-sysctl`.

**Параметры runtime** — настройки, применяемые немедленно через `sysctl -w`, но сбрасывающиеся после перезагрузки без persistent-конфигурации.

## Основные концепции

### Overcommit: контроль выделения памяти

Параметры `vm.overcommit_*` определяют, разрешает ли ядро процессам выделять больше виртуальной памяти, чем доступно физически.

| Параметр | Значения | Описание |
| :--- | :--- | :--- |
| `vm.overcommit_memory` | `0` (default) | Heuristic: ядро использует эвристику для отклонения явно невозможных запросов. При ложном успехе `malloc()` → OOM при первом обращении. |
| | `1` | Always: все запросы `malloc()` одобряются. Используется для приложений с разреженными массивами. |
| | `2` | Strict: общий объем выделений не может превышать `SwapTotal + (RAM * overcommit_ratio / 100)`. Рекомендуется для продакшн-серверов. |
| `vm.overcommit_ratio` | 50–100 (default: 50) | Процент физической RAM, добавляемый к SwapTotal при расчете лимита в режиме `overcommit_memory=2`. |

**Практический пример:**
```bash
# Сервер с 64 ГБ RAM и 8 ГБ Swap, overcommit_ratio=80
# Лимит: 8192 + (65536 * 80 / 100) = 8192 + 52428 = 60620 МБ ≈ 59.2 ГБ
# Если Committed_AS приближается к этому значению — риск OOM

cat /proc/sys/vm/overcommit_memory
grep -E 'Committed_AS|CommitLimit' /proc/meminfo
```

**Рекомендация:** Для серверов баз данных (PostgreSQL, MySQL) устанавливайте `vm.overcommit_memory=2` и `vm.overcommit_ratio=80`, чтобы избежать хаотичного OOM.

### Swappiness: баланс между кэшем и свопом

| Параметр | Значения | Описание |
| :--- | :--- | :--- |
| `vm.swappiness` | `0` | Минимальный свопинг. Ядро отдает приоритет очистке Page Cache. Рекомендуется для БД и JVM. |
| | `10` | Умеренный (рекомендуется для большинства серверов). |
| | `60` | Default: баланс между очисткой кэша и выгрузкой анонимных страниц. |
| | `100` | Равный приоритет. Анонимные страницы и файловый кэш вытесняются одинаково. |
| | `101–200` | (ядро ≥ 5.8) Агрессивная выгрузка в swap. Полезно, если файловый кэш критичен, а диск быстрый (NVMe). |

**Важно:** Значение `0` не означает полного отключения свопа — ядро все равно может использовать swap при `free < min` (direct reclaim). Для полного отключения required `swapoff -a`.

### Водяные знаки (Watermarks): пороги запуска reclaim

| Параметр | Default | Описание |
| :--- | :--- | :--- |
| `vm.min_free_kbytes` |зависит от RAM | Минимальный объем свободной памяти (в КБ). При достижении запускается direct reclaim. На серверах с 64 ГБ+ рекомендуется **1048576** (1 ГБ). |
| `vm.watermark_boost_factor` | `10000` (10%) | Временное повышение вотермарков при резком росте аллокаций. `0` — отключено (рекомендация 2025 для production). |
| `vm.watermark_scale_factor` | `10` (0.1%) | Множитель зазора между `min`, `low` и `high`. Увеличение до `50–100` заставляет `kswapd` просыпаться раньше. |

**Взаимосвязь:**
```
min = min_free_kbytes (базовый порог)
low = min + min * watermark_scale_factor / 10000
high = low + min * watermark_scale_factor / 10000
```

```bash
# Проверка текущих значений
cat /proc/sys/vm/min_free_kbytes
cat /proc/sys/vm/watermark_scale_factor
cat /proc/sys/vm/watermark_boost_factor

# Просмотр вотермарков в зонах
cat /proc/zoneinfo | grep -E "Node|free|min|low|high"
```

### Dirty Pages и Writeback: контроль дискового I/O

| Параметр | Default | Описание |
| :--- | :--- | :--- |
| `vm.dirty_ratio` | `20` | Процент RAM, при котором процесс принудительно блокируется для сброса данных на диск (I/O throttling). Для NVMe: **10–15**. |
| `vm.dirty_background_ratio` | `10` | Процент RAM, при котором запускается фоновый writeback (асинхронно). Для NVMe: **5–7**. |
| `vm.dirty_bytes` | `0` (отключено) | Абсолютный лимит грязных страниц (в байтах). Приоритет над `dirty_ratio`. Используйте на серверах с 128+ ГБ RAM, где % значения опасны. |
| `vm.dirty_background_bytes` | `0` (отключено) | Абсолютный лимит для фонового writeback. Приоритет над `dirty_background_ratio`. |
| `vm.dirty_expire_centisecs` | `3000` (30 сек) | Время жизни грязной страницы до принудительного сброса. Уменьшение ускоряет writeback, но повышает I/O. |
| `vm.dirty_writeback_centisecs` | `500` (5 сек) | Интервал проверки потоками writeback (kworker) на предмет устаревших грязных страниц. |

**Профили для разных нагрузок:**
```bash
# База данных (PostgreSQL, MySQL)
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5

# Файловый сервер / Веб-сервер
vm.dirty_ratio = 15
vm.dirty_background_ratio = 7

# Бэкапы / Последовательные записи
vm.dirty_ratio = 40
vm.dirty_background_ratio = 20

# Абсолютные значения для 128+ ГБ RAM
vm.dirty_background_bytes = 134217728  # 128 МБ
vm.dirty_bytes = 536870912             # 512 МБ
```

### VFS Cache Pressure: баланс Slab vs Page Cache

| Параметр | Default | Описание |
| :--- | :--- | :--- |
| `vm.vfs_cache_pressure` | `100` | Равный приоритет очистки Slab (inode, dentry) и Page Cache. |
| | `< 100` (например, `50`) | Ядро менее охотно очищает метаданные ФС. Полезно для систем с миллионами файлов (объектные хранилища). |
| | `> 100` (например, `200`) | Агрессивная очистка метаданных. Снижает производительность ФС, но освобождает RAM. |

### Drop Caches: принудительная очистка кэшей

| Параметр | Действие |
| :--- | :--- |
| `vm.drop_caches = 1` | Очистка Page Cache. |
| `vm.drop_caches = 2` | Очистка Slab Cache (dentries, inodes). |
| `vm.drop_caches = 3` | Очистка всех кэшей (Page + Slab). |

**Важно:** Это диагностическая операция. Никогда не используйте в production-скриптах по расписанию — после очистки ядро заново наполняет кэш, создавая дополнительную нагрузку.

### HugePages и THP

| Параметр | Default | Описание |
| :--- | :--- | :--- |
| `vm.nr_hugepages` | `0` | Количество статических Huge Pages (2 МБ). Для PostgreSQL/Redis вычислите: `shared_buffers / 2МБ`. |
| `vm.hugetlb_shm_group` | `0` | Группа пользователей, которым разрешено использовать Huge Pages через `shmget()`. |

**Transparent Huge Pages (THP) управляются через sysfs:**
```bash
cat /sys/kernel/mm/transparent_hugepage/enabled
# [always] madvise never

# Рекомендация для БД: madvise или never
echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
```

### Overcommit и Committed_AS

| Метрика | Описание |
| :--- | :--- |
| `Committed_AS` (`/proc/meminfo`) | Суммарный объем виртуальной памяти, запрошенный всеми процессами. |
| `CommitLimit` (`/proc/meminfo`) | Максимально допустимый объем: `SwapTotal + (RAM * overcommit_ratio / 100)`. |

**Правило:** Если `Committed_AS > CommitLimit` — система работает в режиме overcommit и рискует столкнуться с OOM.

### Другие полезные параметры

| Параметр | Default | Описание |
| :--- | :--- | :--- |
| `vm.max_map_count` | `65530` | Максимальное количество VMA (Virtual Memory Areas) на процесс. Для Elasticsearch: **262144**. |
| `vm.oom_kill_allocating_task` | `0` | `1`: убивать процесс, вызвавший OOM (а не выбирать жертву по badness). Агрессивно, но предсказуемо. |
| `vm.panic_on_oom` | `0` | `1`: паника ядра вместо OOM Kill. Используется только для критических систем, где перезагрузка быстрее, чем деградация. |
| `vm.page-cluster` | `3` | Количество страниц, предзагружаемых из swap при swap-in (0: 1 страница, 3: 16 страниц). |
| `vm.zone_reclaim_mode` | `0` | `0`: выделять память с любого NUMA-узла. `1`: локальный reclaim (штраф на удаленную память). Подробнее: см. раздел NUMA. |

## Практические сценарии

### Быстрая оценка текущих настроек

```bash
#!/bin/bash
# runbook: sysctl_memory_audit.sh
echo "=== Overcommit ==="
cat /proc/sys/vm/overcommit_memory
cat /proc/sys/vm/overcommit_ratio
grep -E 'Committed_AS|CommitLimit' /proc/meminfo

echo ""
echo "=== Swappiness ==="
cat /proc/sys/vm/swappiness

echo ""
echo "=== Watermarks ==="
echo "min_free_kbytes: $(cat /proc/sys/vm/min_free_kbytes)"
echo "watermark_scale_factor: $(cat /proc/sys/vm/watermark_scale_factor)"
echo "watermark_boost_factor: $(cat /proc/sys/vm/watermark_boost_factor)"

echo ""
echo "=== Dirty Pages ==="
sysctl vm.dirty_ratio vm.dirty_background_ratio vm.dirty_expire_centisecs vm.dirty_writeback_centisecs

echo ""
echo "=== VFS Cache Pressure ==="
cat /proc/sys/vm/vfs_cache_pressure

echo ""
echo "=== HugePages ==="
grep -E "HugePages|Hugepagesize" /proc/meminfo

echo ""
echo "=== NUMA ==="
cat /proc/sys/vm/zone_reclaim_mode
cat /proc/sys/kernel/numa_balancing
numactl --hardware 2>/dev/null | head -n 10
```

### Профили sysctl для типовых серверов

#### PostgreSQL / MySQL (выделенный сервер)
```ini
# /etc/sysctl.d/99-memory-db.conf
vm.swappiness = 1
vm.overcommit_memory = 2
vm.overcommit_ratio = 80
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.min_free_kbytes = 1048576
vm.watermark_boost_factor = 0
vm.watermark_scale_factor = 50
vm.vfs_cache_pressure = 50
vm.max_map_count = 262144
```

#### Elasticsearch / OpenSearch
```ini
# /etc/sysctl.d/99-memory-elasticsearch.conf
vm.max_map_count = 262144
vm.swappiness = 1
vm.overcommit_memory = 2
vm.overcommit_ratio = 80
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
```

#### Kubernetes Node (Worker)
```ini
# /etc/sysctl.d/99-memory-k8s.conf
vm.swappiness = 10
vm.overcommit_memory = 0
vm.min_free_kbytes = 262144
vm.watermark_boost_factor = 0
vm.watermark_scale_factor = 50
vm.max_map_count = 262144
```

#### Web-сервер (nginx, Apache)
```ini
# /etc/sysctl.d/99-memory-web.conf
vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.dirty_ratio = 15
vm.dirty_background_ratio = 7
vm.min_free_kbytes = 262144
```

### Применение и проверка

```bash
# Применение всех файлов из /etc/sysctl.d/
sudo sysctl --system

# Применение конкретного файла
sudo sysctl -p /etc/sysctl.d/99-memory-db.conf

# Временное изменение (до перезагрузки)
sudo sysctl -w vm.swappiness=10

# Проверка всех параметров памяти
sysctl -a | grep vm.

# Проверка конкретного параметра
sysctl vm.swappiness
```

### Prometheus: мониторинг sysctl-зависимых метрик

```yaml
groups:
  - name: sysctl_memory_alerts
    rules:
      - alert: HighCommittedMemory
        expr: node_memory_Committed_AS_bytes / (node_memory_SwapTotal_bytes + node_memory_MemTotal_bytes) > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий overcommit на {{ $labels.instance }}"
          description: "Committed_AS превышает 90% от CommitLimit."

      - alert: HighDirtyPages
        expr: node_memory_Dirty_bytes / node_memory_MemTotal_bytes > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий объем грязных страниц на {{ $labels.instance }}"
          description: "Dirty pages {{ $value | humanizePercentage }}. Проверьте vm.dirty_ratio."

      - alert: LowMemAvailable
        expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.15
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Критически мало доступной памяти на {{ $labels.instance }}"
          description: "MemAvailable {{ $value | humanizePercentage }}."
```

## Дополнительная информация

### Связь с другими параметрами

Параметры sysctl взаимодействуют друг с другом. Ключевые связи:

- `vm.swappiness` + `vm.vfs_cache_pressure` определяют баланс между выгрузкой анонимных страниц и очисткой кэша метаданных.
- `vm.dirty_ratio` + `vm.min_free_kbytes` влияют на частоту writeback и direct reclaim.
- `vm.overcommit_memory=2` + `vm.overcommit_ratio` задают жесткий лимит выделений.
- `vm.watermark_boost_factor=0` + `vm.watermark_scale_factor=50` стабилизируют поведение kswapd.

### См. также

- **[Оптимизация памяти](./performance_tuning.md)** — THP, NUMA, KSM, Zram/Zswap, Memory QoS.
- **[Кэширование и освобождение памяти](./caching_and_reclaiming.md)** — Page Cache, kswapd, Direct Reclaim, Watermarks.
- **[Управление Swap](./swap_management.md)** — настройка swappiness, Zram/Zswap, production-пороги.
- **[Slab Allocator](./slab_allocator.md)** — vm.vfs_cache_pressure, SReclaimable/SUnreclaim.
- **[Диагностика /proc/meminfo](../../Diagnostics/Memory/proc_meminfo.md)** — расшифровка всех метрик.
- **[Настройка writeback](../../Diagnostics/Performance/DiskIO/writeback_tuning.md)** — профили tuning для NVMe и СУБД.
