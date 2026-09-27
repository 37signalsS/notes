# Дерево решений: диагностика проблем с памятью

## Определения

**Дерево решений (Decision Tree)** — структурированный алгоритм диагностики, позволяющий по симптомам快速 определить корневую причину проблемы с памятью и выбрать инструменты для дальнейшего анализа. Предотвращает хаотичный перебор утилит и минимизирует время инцидента.

**USE-методология (Utilization, Saturation, Errors)** — подход к мониторингу ресурсов: для каждого ресурса измеряйте утилизацию, насыщение и ошибки. Применяется к CPU, памяти, диску и сети.

**SLI/SLO (Service Level Indicator/Objective)** — индикаторы уровня сервиса. При диагностике памяти критичны: availability (доступность сервиса), latency (латентность из-за swap/thrashing), errors (OOM-события).

## Основные концепции

### Методология быстрой оценки (Rapid Assessment)

Первичная оценка состояния памяти занимает 30-60 секунд и определяет класс проблемы:

```bash
# 1. Общее состояние системы (30 секунд)
cat /proc/pressure/memory
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=0
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0
# Если avg10 > 5% — проблема с памятью

# 2. Доступная память
cat /proc/meminfo | grep -E "MemAvailable|MemFree|MemTotal"
# → MemTotal:       32768000 kB
# → MemFree:         1048576 kB
# → MemAvailable:   20971520 kB
# MemAvailable < 20% от MemTotal — проблема

# 3. Активность swap
vmstat 1 3
# → si   so
# →  0    0    (норма)
# → 128  256   (проблема: thrashing)

# 4. OOM-события
dmesg -T | grep -i "oom\|killed process" | tail -5
# Если есть — критично

# 5. Состояние контейнера (если применимо)
cat /sys/fs/cgroup/.../memory.events
# → oom_kill > 0 — проблема
```

### Классификация проблем по симптомам

| Симптом | Вероятная причина | Инструменты |
| :--- | :--- | :--- |
| `MemAvailable` < 20% | Нехватка RAM | `free`, `smem`, `/proc/meminfo` |
| `si/so` > 0 постоянно | Thrashing (активный swap) | `vmstat`, `sar -r`, PSI |
| `oom_kill` > 0 | OOM Killer сработал | `dmesg`, `journalctl`, `memory.events` |
| `MemAvailable` нормальный, но сервис медленный | Page cache miss, disk I/O | `iostat`, `pidstat -d`, PSI (I/O) |
| `SUnreclaim` растет | Утечка в ядре | `kmemleak`, `slabtop` |
| `memory.current` растет в контейнере | Утечка в приложении | `smem`, `pmap`, `ps aux` |
| `memory.events.high` > 0 | Throttling (мягкий лимит) | `memory.high`, `memory.current` |
| `PSI memory full avg10` > 10% | Критическое давление | `/proc/pressure/memory`, OOM pending |

## Практические сценарии

### Сценарий 1: Сервис стал медленным

**Дерево решений:**

```
Сервис медленный
├── Проверка PSI (10 секунд)
│   ├── PSI memory full > 5% → Проблема с памятью → Шаг 2
│   ├── PSI I/O some > 10% → Проблема с диском → iostat
│   └── PSI CPU some > 20% → Проблема с CPU → pidstat -u
│
├── Шаг 2: Проверка swap
│   ├── vmstat si/so > 0 → Thrashing → Шаг 3
│   └── vmstat si/so = 0 → Проверить /proc/meminfo
│
└── Шаг 3: Определение виновника
    ├── smem -tk -s pss -r → Топ процессов по PSS
    └── pmap -x <PID> → Детализация по сегментам
```

**Команды для диагностики:**
```bash
# Шаг 1: PSI
cat /proc/pressure/memory

# Шаг 2: Swap activity
vmstat 1 5

# Шаг 3: Топ потребителей
sudo smem -tk -s pss -r | head -20

# Шаг 4: Детализация
sudo pmap -x <PID> | head -30
```

### Сценарий 2: OOM Killer убил критический процесс

**Дерево решений:**

```
OOM Kill
├── Проверка типа OOM
│   ├── CONSTRAINT_NONE → Системный дефицит (хост) → Шаг 2
│   ├── CONSTRAINT_MEMCG → Превышение лимита контейнера → container_memory_diagnostics.md
│   └── CONSTRAINT_CPUSET → Нарушение привязки к CPU → настройка cpuset
│
├── Шаг 2: Анализ жертвы
│   ├── dmesg -T | grep "Killed process" → PID и имя
│   ├── /proc/<PID>/smaps_rollup (если live) → RSS/PSS
│   └── smem -tk -s pss -r → Сравнение с другими процессами
│
└── Шаг 3: Предотвращение
    ├── Увеличить RAM или limits
    ├── Настроить oom_score_adj
    ├── Оптимизировать потребление
    └── Настроить мониторинг
```

**Команды для диагностики:**
```bash
# Шаг 1: Найти жертву
dmesg -T | grep -i "killed process" | tail -5
# → [Tue Sep 16 10:30:45 2026] Killed process 12345 (java) total-vm:8GB, anon-rss:4GB

# Шаг 2: Анализ cgroup (если контейнер)
kubectl describe pod <pod> | grep -A 5 "Last State"

# Шаг 3: Проверка memory.events
cat /sys/fs/cgroup/.../memory.events.local

# Шаг 4: Анализ потребления
sudo smem -tk -s pss -r -P java | head -10
```

### Сценарий 3: Медленная утечка памяти

**Дерево решений:**

```
Медленный рост памяти
├── Определение типа утечки
│   ├── RSS растет → Утечка в процессе → Шаг 2
│   ├── SUnreclaim растет → Утечка в ядре → kernel_memory_debugging.md
│   └── Page cache растет → Нет проблемы (это нормально) → мониторинг
│
├── Шаг 2: Поиск процесса
│   ├── smem -tk -s pss -r (сравнение с baseline)
│   └── pmap -x <PID> (сравнение снимков)
│
└── Шаг 3: Профилирование
    ├── valgrind --leak-check=full (staging)
    ├── memleak -p <PID> (production, кратковременно)
    └── heaptrack (staging)
```

**Команды для диагностики:**
```bash
# Шаг 1: Baseline
sudo smem -tk -s pss -r > /tmp/smem_baseline.txt

# Шаг 2: Сравнение через 1 час
sudo smem -tk -s pss -r > /tmp/smem_current.txt
diff /tmp/smem_baseline.txt /tmp/smem_current.txt

# Шаг 3: Детализация процесса
sudo pmap -x <PID> | tail -1
# → total: RSS=?, PSS=?

# Шаг 4: Мониторинг
watch -n 60 "grep -E 'MemAvailable|SUnreclaim' /proc/meminfo"
```

### Сценарий 4: Контейнер постоянно перезапускается

**Дерево решений:**

```
Контейнер перезапускается
├── Проверка причины
│   ├── kubectl describe pod → Reason: OOMKilled → container_memory_diagnostics.md
│   ├── kubectl describe pod → Reason: Error → логи приложения
│   └── kubectl describe pod → Reason: CrashLoopBackOff → kubectl logs
│
├── Если OOMKilled
│   ├── Проверка limits → Увеличить memory.limits
│   ├── Проверка потребления → smem, pmap
│   └── Оптимизация приложения
│
└── Если CrashLoopBackOff
    ├── kubectl logs <pod> → Логи приложения
    ├── kubectl logs <pod> --previous → Логи предыдущего запуска
    └── Проверка liveness/readiness probes
```

### Сценарий 5: Высокий Load Average при нормальном CPU

**Дерево решений:**

```
Load Average высокий, CPU нормальный
├── Проверка состояния процессов
│   ├── ps -eo pid,stat,wchan,comm | grep D → Процессы в D-state
│   └── cat /proc/pressure/memory → PSI memory
│
├── Если D-state процессы
│   ├── Проверить iostat → Дисковый bottleneck
│   ├── Проверить NFS/сеть → Сетевой bottleneck
│   └── Проверить dmesg → Аппаратные ошибки
│
└── Если PSI memory high
    ├── Проверить swap → vmstat si/so
    ├── Проверить OOM → dmesg | grep oom
    └── Проверить cgroup limits → memory.events
```

## Типичные ошибки и их решение

### 1. Использование `free` для оценки памяти

**Симптом:** `free -h` показывает `free: 0B`, администратор паникует.

**Решение:** Используйте `MemAvailable`:
```bash
# Неправильно
free -h
# → free: 0B  (это нормально!)

# Правильно
cat /proc/meminfo | grep MemAvailable
# → MemAvailable: 20971520 kB (20 ГБ доступно)
```

### 2. Игнорирование PSI

**Симптом:** Все метрики выглядят нормально, но сервис медленный.

**Решение:** Проверьте PSI:
```bash
cat /proc/pressure/memory
# → some avg10=15.23 avg60=8.45 avg300=3.21 total=1234567
# avg10 > 10% — проблема, даже если free > 0
```

### 3. Использование RSS вместо PSS

**Симптом:** Суммарный RSS по процессам превышает общую RAM (оверкаунтинг).

**Решение:** Используйте PSS:
```bash
# Неправильно
ps -eo pid,rss --sort=-rss | awk '{sum+=$2} END {print sum}'
# → 50GB (завышено из-за shared libraries)

# Правильно
sudo smem -tk -s pss -r | tail -1
# → 35GB (корректно)
```

### 4. Один замер вместо тренда

**Симптом:** Один `smem` показывает 2GB PSS — паника.

**Решение:** Собирайте тренды:
```bash
# Baseline
sudo smem -tk -s pss -r > /tmp/baseline_$(date +%Y%m%d).txt

# Текущее состояние
sudo smem -tk -s pss -r > /tmp/current_$(date +%Y%m%d).txt

# Сравнение
diff /tmp/baseline_*.txt /tmp/current_*.txt
```

### 5. Запуск тяжелых утилит на production

**Симптом:** `valgrind` или `pmap -XX` на production-сервере замедляет систему.

**Решение:** Используйте легкие альтернативы:
```bash
# Вместо valgrind
sudo memleak -p <PID> -t 5  # BCC, overhead ~5%

# Вместо pmap -XX
cat /proc/<PID>/smaps_rollup  # Мгновенный снимок
```

## Best Practices

1. **Начинайте с PSI.** `/proc/pressure/memory` за 10 секунд дает ответ, есть ли проблема.

2. **Используйте MemAvailable.** `free` бесполезен на современных системах с Page Cache.

3. **Собирайте baseline.** Сохраняйте «здоровые» значения для сравнения.

4. **Измеряйте тренд, а не точку.** Один замер — не диагноз.

5. **Комбинируйте инструменты.** PSI → vmstat → smem → pmap — последовательная детализация.

6. **Для контейнеров — с хоста.** `/proc/meminfo` внутри контейнера бесполезен.

7. **Проверяйте cgroup events.** `memory.events` — ранний индикатор проблем.

8. **Планируйте capacity.** Мониторьте тренды и планируйте расширение заранее.

## Дополнительная информация

### Шпаргалка по инструментам

| Задача | Инструмент | Время выполнения |
| :--- | :--- | :--- |
| Быстрый health-check | `cat /proc/pressure/memory` | 1 секунда |
| Доступная память | `cat /proc/meminfo \| grep MemAvailable` | 1 секунда |
| Swap activity | `vmstat 1 3` | 3 секунды |
| Топ потребителей | `sudo smem -tk -s pss -r \| head -20` | 5-30 секунд |
| Детализация процесса | `sudo pmap -x <PID> \| head -30` | 1-5 секунд |
| OOM-события | `dmesg -T \| grep -i oom \| tail -5` | 1 секунда |
| cgroup events | `cat /sys/fs/cgroup/.../memory.events` | 1 секунда |
| Профилирование | `valgrind --leak-check=full` | 10-60 минут |

### Связанные темы

- [PSI](../../Core/kernel/psi.md) — теория давления на ресурсы.
- [/proc/meminfo](./proc_meminfo.md) — расшифровка метрик памяти.
- [vmstat](./vmstat.md) — статистика виртуальной памяти.
- [smem](./smem.md) — точный анализ PSS/USS.
- [pmap](./pmap.md) — карта памяти процесса.
- [Container memory diagnostics](./container_memory_diagnostics.md) — диагностика в контейнерах.
- [OOM Killer diagnostics](../../Core/processes/oom_killer_diagnostics.md) — анализ OOM.
- [Kernel memory debugging](./kernel_memory_debugging.md) — kmemleak, KASAN.
