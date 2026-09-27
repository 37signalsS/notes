# `syswatch` (System Diagnostic & Monitoring TUI)

## Определение

**`syswatch`** — это современная интерактивная панель для глубокой диагностики и мониторинга ресурсов отдельного хоста с текстовым пользовательским интерфейсом (TUI). Написанный на Rust, инструмент позиционируется как «first-look tool» — единая точка входа для системного администратора или SRE-инженера при возникновении неочевидных проблем с производительностью. В отличие от классических мониторов, `syswatch` фокусируется не только на текущих показателях, но и на анализе аномалий и возможности ретроспективного просмотра состояния системы.

## Основные концепции

### Временная шкала и перемотка (Timeline Scrubber)

Одной из уникальных функций `syswatch` является сохранение истории метрик в рамках текущей сессии.
- **Scrubbing (Прокрутка):** С помощью стрелок навигации пользователь может «отмотать» время назад и увидеть состояние системы (загрузку CPU, процессы, сетевую активность) в момент пика нагрузки, который уже прошел.
- **Запись и воспроизведение:** Поддерживается режим записи сессии (`syswatch --record`) в файл формата `.swr` и её последующее воспроизведение (`syswatch --replay file.swr`). Это позволяет передавать диагностические данные для детального анализа коллегам.

### Движок интеллектуального анализа (Insights)

Вкладка **Insights** использует эвристические алгоритмы для автоматического обнаружения проблем. Вместо сырых графиков пользователь получает карточки с описанием ситуации на «человеческом» языке:
- **Memory Pressure:** Аналитика PSI и выявление «голодания» памяти.
- **Swap Thrashing:** Детектирование чрезмерной активности подкачки, снижающей общую отзывчивость.
- **Runaway Processes:** Идентификация процессов с аномальным поведением (утечки ресурсов или бесконечные циклы).

### Архитектура и dual-loop система обновления

Инструмент использует двухпетлевую архитектуру (**dual-loop**), минимизирующую влияние самого монитора на систему:

1. **Быстрый цикл (1 Гц):** Сбор критических метрик — CPU, память, сеть. Отрисовка происходит без задержек.
2. **Тяжелый цикл (1.5–5 с):** Сбор ресурсоёмких данных — дерево процессов, сервисы `systemd`, GPU, статистика сокетов.

Данные поступают из нескольких источников:
- `/proc` — мгновенные счётчики процессов, память, CPU.
- `/sys` — частоты CPU, температурные зоны, энергопотребление.
- PSI (`/proc/pressure/`) — давление на ресурсы (CPU, Memory, I/O).
- Netlink — статистика сетевых интерфейсов и сокетов.
- `systemctl` / `launchctl` — статус сервисов.

**Потребление ресурсов:** На idle-системе `syswatch` использует <1% CPU и ~15–30 МБ RAM. При 1000+ процессах overhead может достигать 3–5% CPU из-за парсинга `/proc`.

### 12 диагностических вкладок

| № | Вкладка | Назначение | Ключевые метрики |
|:---|:---|:---|:---|
| 1 | **Overview** | Общий дашборд | Load Average, uptime, суммарный %CPU, %MEM, Swap |
| 2 | **CPU** | Детализация по ядрам | %usr, %sys, %iowait, %steal, частоты turbo/base |
| 3 | **Memory** | Глубокая аналитика RAM/Swap | RSS, PSS, Footprint, PSI Memory, page faults |
| 4 | **Disks** | Операции ввода-вывода | IOPS, throughput, латентность, очередь |
| 5 | **Filesystems** | Состояние точек монтирования | Свободное место, inodes, тип ФС |
| 6 | **Processes** | Дерево процессов | PID, PPID, %CPU, %MEM, STATE, команда |
| 7 | **GPU** | Статистика VRAM и вычислений | Утилизация ядер, память GPU, температура |
| 8 | **Power** | Энергопотребление и температуры | RAPL (Intel), `k10temp` (AMD), Apple M-series |
| 9 | **Services** | Статус юнитов | Active/Failed, память сервиса, CPU |
| 10 | **Network** | Трафик по интерфейсам | rxkB/s, txkB/s, ошибки, состояние сокетов |
| 11 | **Timeline** | Визуальная история сессии | Графики всех метрик за время работы |
| 12 | **Insights** | Отчет об аномалиях | Карточки с описанием проблем и рекомендациями |

## Предварительные требования

### Аппаратные требования

- **ОС:** Linux с ядром 5.4+ (рекомендуется 6.1+ для полной поддержки PSI и cgroups v2) или macOS 12.3+.
- **Архитектура:** x86_64, ARM64 (Apple Silicon), RISC-V (экспериментально).
- **Память:** минимум 512 МБ свободной RAM для запуска приложения.
- **Диск:** минимум 50 МБ свободного места под бинарный файл и кэш сессий.
- **Терминал:** поддержка Unicode (True Color или 256 цветов) и мыши (опционально). Размер окна не менее 80×24.

### Программные требования

```bash
# Проверка версии ядра
uname -r
# → 6.1.0-17-amd64 (требуется >= 5.4)

# Проверка наличия /proc и /sys
mount | grep -E 'proc |sysfs'
# → proc on /proc type proc (rw,nosuid,nodev,noexec,relatime)
# → sysfs on /sys type sysfs (rw,nosuid,nodev,noexec,relatime)

# Проверка PSI (Pressure Stall Information)
[ -d /proc/pressure ] && echo "PSI включён" || echo "PSI отключён — требуется ядро 4.20+ с CONFIG_PSI=y"
```

### Настройка прав доступа

Для доступа ко всем процессам и метрикам необходимо запускать `syswatch` с правами `root` или через `sudo`. От имени обычного пользователя инструмент видит только собственные процессы.

```bash
# Временное повышение прав для текущей сессии
sudo syswatch

# Постоянное разрешение через sudoers (без запроса пароля)
# /etc/sudoers.d/syswatch
Cmnd_Alias SYSWATCH = /usr/bin/syswatch
%admin ALL=(ALL) NOPASSWD: SYSWATCH

# Проверка группового доступа (если настроен)
groups $USER | grep -q adm && echo "Доступ к /proc/log granted" || echo "Требуется root"
```

### Проверка установки

```bash
# Версия
syswatch --version
# → syswatch 0.4.2

# Доступные плагины/источники данных
syswatch --list-sources 2>/dev/null || syswatch --help | grep -A 5 "Sources"

# Быстрый smoke-test (выход после первого обновления)
timeout 3 syswatch || echo "Запуск завершён"
```

## Установка

Для работы требуется Rust версии 1.75+.

```bash
# macOS / Linux (через Homebrew)
brew install syswatch

# Установка через Cargo
cargo install syswatch

# Arch Linux (AUR)
paru -S syswatch

# NixOS
nix-shell -p syswatch
```

## Практические сценарии

### Расследование кратковременного всплеска нагрузки

Если система «зависла» на несколько секунд и отпустила:
1. Запустите `syswatch`.
2. Перейдите на вкладку **Timeline** или просто используйте стрелки «влево» в любом окне.
3. Найдите красный участок на графиках.
4. Переключитесь на вкладку **Procs** (в том же временном срезе), чтобы увидеть, какой процесс потреблял ресурсы в тот момент.

### Проверка здоровья нового сервера

1. Запустите утилиту и перейдите на вкладку **Insights**.
2. Если в системе не настроен Swap, некорректно работают термодатчики или есть зомби-процессы, `syswatch` сразу выведет соответствующее предупреждение.
3. На вкладке **Power** проверьте, не происходит ли температурный троттлинг (Thermal Throttling) под нагрузкой.

### Per-CPU анализ и идентификация ненужной нагрузки

На многоядерных системах общий `%CPU` скрывает дисбаланс между ядрами:

```bash
# 1. Запустите syswatch и перейдите на вкладку CPU
# 2. Оцените распределение нагрузки по ядрам:
#    - Одно ядро на 100% при общем CPU 15% = hot CPU
#    - %steal на виртуальной машине > 10% = contention на гипервизоре

# 3. Для детального анализа конкретного PID переключитесь на Procs
#    и нажмите Enter для просмотра per-thread метрик (если доступно)

# Валидация: сопоставьте с mpstat или pidstat
mpstat -P ALL 1 5
pidstat -u -t 1 5
```

### Анализ давления памяти (Memory Pressure) и page faults

Высокий `majf` (major faults) указывает на нехватку RAM и активный swap:

```bash
# 1. Вкладка Memory: обратите внимание на PSI Memory (some/full)
#    - some avg10 > 10% = процессы голодают по памяти
#    - full avg10 > 5% = все процессы заблокированы

# 2. Проверка page faults через /proc
grep -E 'majflt|minflt' /proc/<PID>/status
# → majflt: 12450  (серьёзные ошибки — чтение с диска)
# → minflt: 892340 (малые ошибки — кэш)

# 3. Корреляция с vmstat
vmstat 1 10
# столбцы si/so (swap in/out) и majf (major faults)

# Валидация: majflt/s > 100 + рост swap = требуется больше RAM или оптимизация приложения
```

### Диагностика дисковой подсистемы через PSI

На вкладке **Disks** и **Insights** syswatch визуализирует давление I/O:

```bash
# 1. Мониторинг PSI I/O в реальном времени
watch -n 1 'cat /proc/pressure/io'
# → some avg10=15.20 avg60=8.30 avg300=3.10 total=45678901

# 2. В syswatch: вкладка Disks
#    - Ориентируйтесь на aqu-sz (глубина очереди)
#      HDD: > 2 = проблема, SSD/NVMe: > 4–8 = проблема
#    - await > 20ms на HDD или > 1ms на NVMe = аномалия

# 3. Для детализации переключитесь на iostat
iostat -xz 1

# Валидация: высокий PSI some/full совпадает с высоким await на конкретном устройстве
```

### Сетевая диагностика и корреляция ошибок

На вкладке **Network** отображается трафик по интерфейсам. Для детализации ошибок:

```bash
# 1. В syswatch: вкладка Network — обратите внимание на:
#    - rxkB/s / txkB/s — близко к лимиту интерфейса?
#    - err/s — растет? требует проверки duplex/MTU

# 2. Детальная TCP/UDP статистика через sar
sar -n DEV,EDEV 1 5

# 3. Проверка сокетов и таймаутов
ss -s
# → total: 4532 (tcp: 4123, tcp6: 389)
# → cells withqe: 23 (tcp: 23)

# Валидация: рост retrans/s или drop/s в sar совпадает с падением throughput в syswatch
```

### Корреляционный анализ при инцидентах

Методология SRE для расследования инцидентов с использованием Timeline:

```bash
# 1. Зафиксируйте момент инцидента
# В syswatch: нажмите R (Record) или запустите с флагом записи
syswatch --record /tmp/incident_$(date +%Y%m%d_%H%M%S).swr

# 2. После инцидента остановите запись (q) и сохраните файл

# 3. Воспроизведите сессию для анализа коллегами
syswatch --replay /tmp/incident_20260912_143022.swr

# 4. Воспроизведение с ускорением (анализ 8-часовой сессии за 5 минут)
syswatch --replay /tmp/incident.swr --speed 100

# 5. Экспорт данных для отчёта
# Скриншоты: встроенная функция экспорта PNG (F10 → Export)
# Текстовый дамп: syswatch --dump /tmp/incident.swr > incident_report.txt
```

### Регрессионное тестирование производительности в CI/CD

```bash
#!/bin/bash
# ci_performance_gate.sh — блокировка деплоя при регрессии производительности

BASELINE="/var/www/baseline_session.swr"
CURRENT="/var/www/current_session.swr"
THRESHOLD_CPU=5.0  # % отклонение
THRESHOLD_MEM=5.0  # % отклонение

# Сбор baseline (запускается один раз на чистой системе)
syswatch --record "$BASELINE" &
BASELINE_PID=$!
sleep 60  # сбор в течение 1 минуты
kill $BASELINE_PID

# После деплоя: сбор current
syswatch --record "$CURRENT" &
CURRENT_PID=$!
sleep 60
kill $CURRENT_PID

# Сравнение ключевых метрик (упрощённый пример)
# Используйте syswatch --export для получения JSON
syswatch --export "$BASELINE" --format json > baseline.json
syswatch --export "$CURRENT" --format json > current.json

# Python-скрипт для сравнения (пример)
python3 -c "
import json
with open('baseline.json') as f: base = json.load(f)
with open('current.json') as f: curr = json.load(f)
cpu_delta = abs(curr['cpu']['avg'] - base['cpu']['avg'])
mem_delta = abs(curr['memory']['avg'] - base['memory']['avg'])
if cpu_delta > $THRESHOLD_CPU or mem_delta > $THRESHOLD_MEM:
    print(f'REGRESSION: CPU delta={cpu_delta}%, MEM delta={mem_delta}%')
    exit(1)
print('PASS: Performance within thresholds')
"
```

### Валидация здоровья после деплоя (Pre/Post Deploy)

```bash
#!/bin/bash
# pre_post_deploy.sh — сравнение состояния системы до и после деплоя

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAP_DIR="/var/log/deploy_snapshots"

# Pre-deploy snapshot
syswatch --record "$SNAP_DIR/pre_$TIMESTAMP.swr" &
PID=$!
sleep 30
kill $PID

# <-- ДЕПЛОЙ ПРОИСХОДИТ ЗДЕСЬ -->

# Post-deploy snapshot (через 2 минуты стабилизации)
sleep 120
syswatch --record "$SNAP_DIR/post_$TIMESTAMP.swr" &
PID=$!
sleep 30
kill $PID

# Сравнение через replay с ускорением
echo "=== Pre-deploy ==="
syswatch --replay "$SNAP_DIR/pre_$TIMESTAMP.swr" --speed 0 | head -n 20

echo "=== Post-deploy ==="
syswatch --replay "$SNAP_DIR/post_$TIMESTAMP.swr" --speed 0 | head -n 20

# Автоматическая проверка на аномалии
syswatch --export "$SNAP_DIR/post_$TIMESTAMP.swr" --format json | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
if data['insights']['count'] > 0:
    print('ANOMALIES DETECTED:')
    for i in data['insights']['items']:
        print(f\"  - {i['severity']}: {i['message']}\")
    sys.exit(1)
print('OK: No new anomalies')
"
```

### Долгоживущий мониторинг в tmux/screen сессиях

Для production-хостов, где требуется постоянный визуальный контроль:

```bash
# Запуск syswatch в tmux с автономным режимом
tmux new-session -d -s syswatch 'syswatch --no-mouse'

# Присоединение для просмотра
tmux attach -t syswatch

# Отсоединение без остановки (Ctrl+B, D)
# Отправка команды в фон: tmux send-keys -t syswatch '' C-c

# Для screen:
screen -dmS syswatch syswatch --no-mouse
screen -r syswatch
```

**Рекомендация:** Используйте `syswatch --interval 2` для снижения overhead при долгих сессиях. Для недельного мониторинга предпочтительнее `atop` с бинарными логами.

### Обнаружение утечек памяти через Timeline

Мониторинг роста RSS конкретного процесса с использованием истории сессии:

```bash
# 1. Запустите syswatch с записью сессии
syswatch --record /tmp/mem_leak.swr &

# 2. Через 2 часа остановите запись
kill %1

# 3. Воспроизведите и переключитесь на Timeline
syswatch --replay /tmp/mem_leak.swr

# 4. На вкладке Memory найдите процесс с непрерывным ростом RSS
#    Синяя линия на графике = стабильный рост = утечка

# 5. Для автоматизации используйте pidstat параллельно
pidstat -r -p <PID> 60 > /tmp/mem_leak_$(date +%Y%m%d).csv
```

### Аудит безопасности: поиск подозрительных процессов

```bash
# 1. Вкладка Processes: нажмите F для фильтрации по имени
#    Ищите процессы с неожиданными именами (tmp, .cache, ld-linux)

# 2. Проверка родительских цепочек
#    Подозрительно: python внутри httpd, bash внутри nginx

# 3. Для детального аудита переключитесь на htop или ps
ps -eo pid,ppid,stat,%cpu,%mem,comm,args --sort=-%cpu | \
    awk 'NR==1 || $0 ~ /\/tmp\|\/dev\/shm\|\/var\/tmp/'

# 4. Проверка открытых файлов и сетевых соединений
lsof -p <PID> | grep -E 'ESTABLISHED|LISTEN'
ss -tlnp | grep <PID>
```

## Устранение неисправностей

### Типичные ошибки

**1. `syswatch: command not found`**

- *Причина:* Пакет не установлен или путь к бинарному файлу отсутствует в `$PATH`.
- *Решение:*
  ```bash
  # Проверка установки
  which syswatch || echo "Не найден в PATH"

  # Установка
  brew install syswatch  # macOS
  sudo apt install syswatch  # Debian/Ubuntu
  cargo install syswatch  # из исходников
  ```

**2. `Permission denied` при доступе к `/proc/<PID>/`**

- *Причина:* Запуск без `root`/`sudo`. Syswatch требует прав для чтения метрик всех процессов.
- *Решение:* Запускайте через `sudo syswatch` или настройте `sudoers` (см. раздел «Предварительные требования»).

**3. Отсутствуют данные GPU или Power**

- *Причина:* Драйверы NVIDIA/AMD не установлены или `syswatch` собран без флага `--features gpu`.
- *Проверка:*
  ```bash
  # NVIDIA
  nvidia-smi
  # AMD
  radeontop -b
  ```
- *Решение:* Установите проприетарные драйверы или соберите `syswatch` с поддержкой GPU:
  ```bash
  cargo install syswatch --features gpu
  ```

**4. Терминал показывает «кракозябры» или артефакты**

- *Причина:* Терминал не поддерживает Unicode или True Color.
- *Решение:* Используйте `TERM=xterm-256color` или включите `--no-unicode` флаг (если доступен). Для старых терминалей: `syswatch --ascii`.

**5. Высокое потребление CPU самим `syswatch` (>5%)**

- *Причина:* Слишком частый интервал обновления на системе с 1000+ процессами.
- *Решение:*
  ```bash
  # Увеличьте интервал до 2–5 секунд
  syswatch --interval 3

  # Или используйте lightweight-режим (отключение тяжелых коллекторов)
  syswatch --lite
  ```

**6. `Insights` не показывает предупреждений при наличии проблем**

- *Причина:* Эвристики требуют минимального времени сбора (30–60 секунд) для формирования baselines.
- *Решение:* Позвольте инструменту поработать 1–2 минуты. Убедитесь, что PSI включён в ядре (`/proc/pressure` существует).

**7. Запись `.swr` файла повреждена или не воспроизводится**

- *Причина:* Нештатное завершение программы во время записи или устаревший формат.
- *Решение:*
  ```bash
  # Проверка целостности
  syswatch --verify /tmp/session.swr

  # Конвертация в новый формат
  syswatch --migrate /tmp/old_session.swr /tmp/new_session.swr
  ```

### Диагностические команды

```bash
# Проверка конфигурации и доступных источников
syswatch --diagnostics
# → Sources: /proc, /sys, PSI, netlink, systemd
# → GPU: available (nvidia)
# → Power: available (k10temp)

# Проверка логов на ошибки (если запущен через systemd)
journalctl -u syswatch --since "1 hour ago" | grep -i "error\|fail\|warn"

# Проверка версии ядра и конфигурации
uname -r
grep -E 'CONFIG_PSI|CONFIG_TASK_DELAY_ACCT' /boot/config-$(uname -r)

# Проверка доступных PSI метрик
cat /proc/pressure/cpu
cat /proc/pressure/memory
cat /proc/pressure/io
```

## Валидация

### Ожидаемые результаты и проверки

```bash
# 1. Верификация сборов CPU
syswatch --export /tmp/session.swr --format json | python3 -c "
import json, sys
data = json.load(sys.stdin)
assert 'cpu' in data, 'Missing cpu metrics'
assert data['cpu']['cores'] > 0, 'Invalid core count'
print(f'CPU: {data[\"cpu\"][\"avg\"]}% avg across {data[\"cpu\"][\"cores\"]} cores')
"

# 2. Верификация метрик памяти
cat /proc/meminfo | grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree'
# → Сравните с вкладкой Memory в syswatch: значения должны совпадать ± погрешность 1-2%

# 3. Верификация PSI
cat /proc/pressure/cpu
cat /proc/pressure/memory
cat /proc/pressure/io
# → В syswatch: графики PSI должны отображать те же avg10/avg60/avg300 значения

# 4. Верификация timeline scrubber
# Запустите запись на 30 секунд, затем перемотайте назад
# Графики должны отображаться корректно без артефактов

# 5. Верификация Insights
# При искусственной нагрузке (stress-ng) Insights должны генерировать карточки
stress-ng --cpu 4 --timeout 30 &
sleep 5
# → В syswatch должна появиться карточка "High CPU usage detected"
```

### Согласованность с другими инструментами

```bash
# Сравнение CPU: syswatch vs htop vs mpstat
mpstat -P ALL 1 1 | tail -n +4 | awk '{print $3}' | \
    xargs -I {} echo "CPU core: {}%"

# Сравнение памяти: syswatch vs free
free -h
# → Сравните total/used/available с вкладкой Memory

# Сравнение дисков: syswatch vs iostat
iostat -xz 1 1 | grep -E 'Device|sda|nvme'
# → await и aqu-sz должны совпадать с вкладкой Disks
```

## Рекомендации (Best Practices)

1. **Используйте `syswatch` как first-look tool, а не как замену `atop`/`sar`.** Для исторического анализа и nightly сборов предпочитайте [`atop`](./atop.md) с бинарными логами или [`sar`](./sar.md).
2. **Записывайте сессии при расследовании инцидентов.** Файлы `.swr` воспроизводимы и могут быть переданы коллегам для анализа.
3. **Комбинируйте `syswatch` с `pidstat` для per-process истории.** Syswatch показывает snapshot, `pidstat` — таймсериес с интервалами.
4. **Используйте `--lite` режим на production-хостах с 1000+ процессами.** Отключение тяжелых коллекторов снижает overhead до <2%.
5. **Не оставляйте `syswatch` в tmux на месяцы.** Для долгосрочного мониторинга используйте `atop` или внешние системы.
6. **Экспортируйте `.swr` файлы в репозиторийrunbook-ов.** Это позволяет воспроизвести инциденты после их завершения.
7. **Проверяйте PSI перед анализом `iowait`.** `%wa` в `top` агрегирован и может скрывать дисбаланс; PSI даёт объективную картину.
8. **Используйте древовиidный режим на вкладке Processes** для fork-серверов (Apache, PHP-FPM, Nginx worker) — это упрощает идентификацию родительских процессов.

## Ограничения и особенности (Edge Cases)

- **Только чтение:** Инструмент предназначен исключительно для мониторинга. Он не позволяет убивать процессы или изменять приоритеты. Для управления используйте [`htop`](../Processes/htop.md) или [`top`](../Processes/top.md).
- **Single-Host:** Работа только с локальным хостом (для сетевого анализа рекомендуется использовать [`network_cli_tools.md`](../Networking/network_cli_tools.md)).
- **Overhead на больших системах:** При 1000+ процессах и интервале <1с overhead может достигать 3–5% CPU. Используйте `--interval 3` или `--lite` режим.
- **Ограничения GPU:** Мониторинг NVIDIA требует установленных драйверов и демона `nvidia-smi`. AMD GPU поддерживается ограниченно. Apple Silicon работает через `powermetrics` в macOS.
- **Терминальные ограничения:** В `tmux`/`screen` через медленный SSH интерфейс TUI может «замирать». Увеличьте интервал (`--interval 5`) или используйте `mosh`.
- **Запись сессий:** `.swr` файлы не сжимаются по умолчанию. 1 час сессии @ 1Hz = ~5–10 МБ. Для длительных записей используйте сжатие или периодический `--export`.
- **Воспроизведение:** Ускоренное воспроизведение (`--speed`) может пропускать короткие всплески (< 1 сек). Для поиска кратковременных аномалий используйте Timeline в live-режиме.
- **cgroups и контейнеры:** Внутри контейнера `syswatch` показывает только процессы этого контейнера (cgroup v2). Для кросс-контейнерного анализа используйте `systemd-cgtop` или `docker stats` с хоста.
- **Воспроизведение на другой системе:** `.swr` файлы содержат абсолютные пути и метрики конкретного хоста. Воспроизведение на другой машине возможно, но интерпретация данных требует адаптации.
- **История между сессиями:** Без флага `--record` история теряется после выхода. Для долгосрочного хранения используйте `atop` или периодические скриншоты/экспорты.

## Дополнительная информация

### Сравнение с аналогами

| Инструмент | Фокус | Ключевая особенность |
| :--- | :--- | :--- |
| [`htop`](../Processes/htop.md) | Управление процессами | Легкость и интерактивность |
| **btop** | Визуализация | Красивые графики и эстетика |
| [`atop`](./atop.md) | Долгосрочная история | Бинарные логи на диске за недели |
| **`syswatch`** | **Диагностика и Анализ** | **Timeline Scrubber** и **Insights** |

### Ограничения

- **Только чтение:** Инструмент предназначен исключительно для мониторинга. Он не позволяет убивать процессы или изменять приоритеты.
- **Single-Host:** Работа только с локальным хостом (для сетевого анализа рекомендуется использовать [`network_cli_tools.md`](../Networking/network_cli_tools.md)).

### См. также

- [`htop`](../Processes/htop.md) — классический менеджер процессов.
- [`dstat`](./dstat.md) — консолидация метрик в виде текстового лога.
- [Github репозиторий syswatch](https://github.com/matthart1983/syswatch)
- [`network_cli_tools.md`](../Networking/network_cli_tools.md) — сетевые инструменты CLI и TUI для анализа трафика.
