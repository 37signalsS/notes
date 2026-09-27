# Swap и его влияние на дисковый ввод-вывод

## Определения

- **Swap (Подкачка):** Механизм ядра Linux, позволяющий использовать часть дискового пространства (раздел или файл) как расширение оперативной памяти. Страницы RAM, неиспользуемые в течение длительного времени, перемещаются на диск, освобождая RAM для активных процессов.
- **vm.swappiness:** Параметр ядра (0–100), определяющий склонность ядра перемещать анонимные страницы (процессы) в swap при нехватке RAM. Значение 0 = минимизировать swap (только при критической нехватке), 100 = агрессивное использование swap.
- **Swap Thrashing (Своп-шторм):** Ситуация, при которой система постоянно перемещает страницы между RAM и swap, создавая интенсивную дисковую активность. Проявляется как высокий `si`/`so` в `vmstat` и рост `await`.
- **PSI Memory (Pressure Stall Information):** Механизм ядра (4.20+) для измерения реального давления нехватки памяти. Метрика `some avg10` в `/proc/pressure/memory` показывает процент времени, в течение которого хотя бы один процесс ждал освобождения памяти.
- **zswap / zram:** Программные механизмы сжатия анонимных страниц в RAM. zswap — промежуточный кэш перед swap-разделом. zram — виртуальное сжатое block-устройство в RAM. Оба снижают нагрузку на диск.
- **Transparent Huge Pages (THP):** Механизм автоматического использования больших страниц (2 МБ вместо 4 КБ) для анонимных областей памяти. Компакция THP может вызывать фоновую дисковую активность.

## Основные концепции

### Как swap влияет на disk I/O

```
Нормальная работа (без swap):
  Приложение → RAM → Disk (только writeback для dirty pages)
  → Низкая нагрузка на диск

С активным swap:
  Приложение → RAM → Swap Partition/File → Disk
  + RAM → Disk (writeback dirty pages)
  + Swap In/Out → Disk (si/so в vmstat)
  → Высокая нагрузка на диск, рост await
```

**Критический момент:** Swap создаёт ДОПОЛНИТЕЛЬНУЮ нагрузку на диск, которая не связана с работой приложений. Приложения «тормозят» не из-за своей работы, а из-за конкуренции за диск с swap.

### Поведение vm.swappiness

| Значение | Поведение ядра | Рекомендация |
| :--- | :--- | :--- |
| **0** | Swap используется только при критической нехватке памяти (direct reclaim). Page Cache вытесняется агрессивнее. | Экстремальные серверы БД, системы с UPS |
| **1** | Аналог 0, но с небольшой склонностью к swap для «холодных» процессов. | PostgreSQL, MySQL, MongoDB (рекомендация для БД) |
| **10** | Минимальное использование swap. Swap используется только при давлении на память. | Общесерверные нагрузки, Docker-хосты |
| **60** | По умолчанию. Баланс между вытеснением Page Cache и swap. | Десктопы, универсальные серверы |
| **100** | Агрессивное использование swap. Процессы вытесняются раньше, чем Page Cache. | Не рекомендуется |

**Важно:** Значение 0 не отключает swap полностью. Оно лишь минимизирует его использование. Полное отключение — `swapoff -a`.

### Swap на SSD vs HDD

| Параметр | HDD | SSD | NVMe |
| :--- | :--- | :--- | :--- |
| **Скорость swap** | 100–200 IOPS | 50K–100K IOPS | 500K+ IOPS |
| **Задержка swap** | 5–10 мс | 0.1 мс | <0.05 мс |
| **Влияние на I/O** | Катастрофическое | Заметное | Минимальное |
| **Износ** | Не критично | Критично (TBW) | Критично (TBW) |
| **Рекомендация** | Избегать swap на HDD | Допустимо, если есть запас TBW | Допустимо для временных пиков |

### Взаимодействие swap с writeback

При активном swap ядро выполняет одновременно:
1. **Swap In/Out:** Страницы процессов читаются/пишутся на swap-устройство.
2. **Writeback:** Грязные страницы Page Cache сбрасываются на основной диск.
3. **THP Compaction:** Сжатие прозрачных огромных страниц может генерировать I/O.

Эти три процесса конкурируют за один и тот же диск, создавая «своп-шторм».

## Предварительные требования

```bash
# Проверка текущего состояния swap
free -h
# → Swap: total=2.0G used=512M free=1.5G

swapon --show
# → NAME      TYPE      SIZE  USED  PRIO
# → /dev/sda2 partition   2G  512M    -2

# Проверка swappiness
cat /proc/sys/vm/swappiness
# → 60
```

## Практические сценарии

### Шаг 1: Диагностика swap-активности

```bash
# 1. Быстрая проверка: есть ли swap in/out
vmstat 1 5
# → procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
# →  b     swpd   free   buff  cache      si   so    bi    bo   in   cs us sy id wa st
# →  5    10240  10240  20480 2048000    500  300  4096  2048 1000  200 10  5 50 35  0
# → si=500, so=300: АКТИВНЫЙ SWAP (постоянно читаем/пишем в swap)
# → b=5: 5 процессов в D-state (могут ждать swap I/O)

# 2. Проверка PSI по памяти
cat /proc/pressure/memory
# → some avg10=80.00 avg60=50.00 avg300=20.00 total=12345678
# → some avg10 > 10% → критическое давление на память

# 3. Найти процессы, активно использующие swap
for pid in $(ls /proc/ | grep -E '^[0-9]+$'); do
    swap=$(awk '/VmSwap/ {print $2}' /proc/$pid/status 2>/dev/null)
    if [ "$swap" -gt 1024 ] 2>/dev/null; then
        name=$(cat /proc/$pid/comm 2>/dev/null)
        echo "PID=$pid SWAP=${swap}kB NAME=$name"
    fi
done | sort -t= -k3 -n -r | head -10
# → PID=1234 SWAP=512000kB NAME=postgres
# → PID=5678 SWAP=204800kB NAME=java
```

### Шаг 2: Оптимизация swappiness

```bash
# Текущее значение
cat /proc/sys/vm/swappiness
# → 60

# Установка на 10 (рекомендуется для серверов)
sudo sysctl -w vm.swappiness=10
# → vm.swappiness = 10

# Проверка эффекта (через 5-10 минут)
vmstat 1 5 | grep -E "si|so"
# → si=0, so=0 → swap не используется

# Постоянная настройка
echo "vm.swappiness = 10" | sudo tee -a /etc/sysctl.d/99-swap-tuning.conf
sudo sysctl --system
```

### Шаг 3: Отключение swap (крайняя мера)

```bash
# ВНИМАНИЕ: Отключение swap при нехватке RAM убьёт процессы (OOM Killer)

# Проверка: достаточно ли RAM без swap?
free -h
# → total=32G used=28G free=4G
# → Если free < 20% от total — НЕ отключайте swap

# Отключение swap
sudo swapoff -a

# Проверка что swap отключен
free -h
# → Swap: total=0 used=0 free=0

# Комментирование в fstab (чтобы не включился после ребута)
sudo sed -i 's/^\/dev\/.*swap.*sw.*0.*0/# &/' /etc/fstab

# Восстановление (если нужно)
sudo swapon -a
```

### Шаг 4: Настройка для PostgreSQL

```bash
# PostgreSQL рекомендует vm.swappiness=1 или 0
# Потому что PostgreSQL использует shared_buffers для кэширования
# и не хочет, чтобы его страницы попадали в swap

# Проверка текущих настроек
cat /proc/sys/vm/swappiness
# → 60

# Настройка
sudo sysctl -w vm.swappiness=1
echo "vm.swappiness = 1" | sudo tee /etc/sysctl.d/99-postgresql.conf

# Проверка что PostgreSQL не в swap
sudo -u postgres psql -c "SHOW shared_buffers;"
# → 8GB

# Мониторинг swap postgres процесса
cat /proc/$(pgrep -u postgres | head -1)/status | grep VmSwap
# → VmSwap: 0 kB (норма)
# → VmSwap: 102400 kB (проблема — PostgreSQL в swap)
```

### Шаг 5: Настройка для Docker-хоста

```bash
# Docker рекомендует vm.swappiness=10 или ниже
# Контейнеры не должны активно использовать swap

# Проверка swap-использования контейнерами
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.SwapUsage}}"
# → NAME     MEM USAGE     SWAP USAGE
# → nginx    128MiB / 1GiB  64MiB / 1GiB

# Ограничение swap для контейнера
docker run -d --memory=512m --memory-swap=512m nginx
# → memory-swap = memory (swap = 0)

# Настройка на хосте
sudo sysctl -w vm.swappiness=10
echo "vm.swappiness = 10" | sudo tee /etc/sysctl.d/99-docker.conf
```

### Шаг 6: Диагностика THP-компакции

```bash
# Проверка THP-активности
cat /proc/sys/vm/compact_memory
# → 0 (если 1 — компакция выполняется)

# Мониторинг компакции
vmstat 1 5 | grep -E "in|cs"
# → in: прерывания (могут быть от kompd)
# → cs: контекстные переключения (рост при компакции)

# Отключение THP (рекомендуется для БД)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/defrag

# Постоянная настройка (через GRUB)
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="transparent_hugepage=never /' /etc/default/grub
sudo update-grub
```

### Шаг 7: Мониторинг swap через sar

```bash
# Статистика swap in/out
sar -W 1 5
# → pswpin/s  — страниц в секунду из swap в RAM
# → pswpout/s — страниц в секунду из RAM в swap

# Если pswpin/s > 0 или pswpout/s > 0:
# → Система испытывает давление на память
# → Добавьте RAM или оптимизируйте приложение

# Исторический анализ swap
sar -W -f /var/log/sysstat/sa$(date +%d)
# → Смотрите на пики pswpout/s — когда система активно вытесняла в swap
```

## Автоматизация и мониторинг

### Prometheus alerts

```yaml
groups:
  - name: swap_alerts
    rules:
      - alert: SwapUsageHigh
        expr: node_memory_SwapUsed_bytes / node_memory_SwapTotal_bytes > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое использование swap на {{ $labels.instance }}"
          description: "Swap использован на {{ $value | humanizePercentage }}. Проверьте swappiness и потребителей памяти."

      - alert: SwapThrashing
        expr: rate(node_vmstat_pswpin[5m]) > 100 or rate(node_vmstat_pswpout[5m]) > 100
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Swap thrashing на {{ $labels.instance }}"
          description: "Активный swap in/out. Диски перегружены. Добавьте RAM или оптимизируйте приложение."
```

## Типичные ошибки и устранение неполадок

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `si`/`so` > 0 в `vmstat` | Недостаточно RAM | `free -h`, `ps aux --sort=-%mem` | Добавить RAM, оптимизировать приложение |
| `b` (D-state) > 5 в `vmstat` | Процессы ждут swap I/O | `ps -eo pid,stat,wchan,comm \| grep " D "` | Снизить swappiness, добавить RAM |
| `await` растет при наличии swap | Swap на медленном диске | `iostat -xz 1`, `swapon --show` | Переместить swap на SSD, снизить swappiness |
| PostgreSQL «тормозит» при swappiness=60 | shared_buffers в swap | `cat /proc/$(pgrep postgres)/status \| grep VmSwap` | Установить `vm.swappiness=1` |
| Docker-контейнер потребляет swap | `--memory-swap` не ограничен | `docker stats` | Ограничить `--memory-swap=memory` |
| THP-компакция создаёт I/O | `transparent_hugepage=always` | `cat /sys/kernel/mm/transparent_hugepage/enabled` | Отключить THP: `echo never > .../enabled` |

## Ограничения и особые случаи

### Kubernetes и Swap

Kubernetes по умолчанию требует отключения swap (`swapoff -a`). С kubelet 1.28+ доступна beta-поддержка swap для подов, но:
- Swap limited через `memory.swap.max` в cgroups v2
- Рекомендуется только для систем с limited RAM и не-критичными нагрузками
- Для продакшена: отключить swap, выделить достаточно RAM

### zswap и zram

- **zswap:** Промежуточный кэш. Сжатые страницы хранятся в RAM. При переполнении — на диск. Снижает I/O на 50-80%.
- **zram:** Виртуальное block-устройство. swap на zram = swap в RAM (без диска). Рекомендуется для систем с ограниченной RAM.
- Оба механизма снижают нагрузку на диск, но потребляют CPU на сжатие.

### Overcommit и OOM

- `vm.overcommit_memory=1` (HEURISTIC): ядро разрешает больше, чем есть RAM. При нехватке — Direct Reclaim → синхронный writeback → блокировка процессов.
- Рекомендация: `vm.overcommit_memory=0` (STRICT) для серверов БД.
- `vm.overcommit_ratio=80` — процент RAM, который можно overcommit при `overcommit_memory=2`.

## Дополнительная информация

### См. также

- [Настройка writeback: vm.dirty_* параметры](./writeback_tuning.md) — взаимодействие swap и writeback.
- [Диагностика памяти](../../../../Diagnostics/Memory/) — инструменты анализа RAM.
- [Performance Tuning: ФС](../../../../FileSystems/performance_tuning.md) — sysctl параметры, включая swappiness.
- [Docker Performance Tuning](../../../../Docker/Docker_performance_tuning.md) — настройка swap для контейнеров.
