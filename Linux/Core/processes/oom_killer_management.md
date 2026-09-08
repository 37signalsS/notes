# Управление механизмом OOM Killer в Linux

## Определения

**Управление OOM Killer (Out-of-Memory Killer)** — это совокупность методов и настроек, позволяющих регулировать поведение ядра Linux при критической нехватке памяти для защиты системных служб и обеспечения предсказуемости системы.

**oom_score_adj** — программный интерфейс ядра (через procfs), позволяющий вручную корректировать вероятность завершения конкретного процесса. Диапазон: от `-1000` (полный иммунитет) до `+1000` (максимальный риск).

**choom** — утилита из пакета `util-linux`, предоставляющая удобный интерфейс для изменения и просмотра `oom_score_adj` процессов без прямой работы с файловой системой `/proc`.

**User-space OOM Killers** — сторонние демоны (`systemd-oomd`, `earlyoom`, `nohang`), которые завершают процессы превентивно на основе данных PSI (Pressure Stall Information) или порогов RAM, не допуская «зависания» ядра в попытках освободить страницы.

**Memory Overcommit** — стратегия ядра, позволяющая процессам выделять (allocate) больше виртуальной памяти, чем физически доступно в RAM и Swap. Управляется через `vm.overcommit_memory` и `vm.overcommit_ratio`. Агрессивный overcommit увеличивает риск внезапного OOM, консервативный — приводит к отказам в аллокации (`malloc` возвращает `NULL`).

**OOM Reaper** — специальный поток ядра (введен в v4.6), который асинхронно освобождает память убитого процесса. Это решает проблему «зависших зомби», когда процесс уже получил SIGKILL, но не может освободить память, так как заблокирован (например, в состоянии D).

**PSI (Pressure Stall Information)** — механизм ядра (начиная с 4.20), измеряющий время, которое процессы тратят на ожидание памяти. User-space OOM killers используют PSI для принятия решений до наступления критической нехватки.

## Основные концепции

### Уровни управления

Эффективная стратегия SRE предполагает настройку на нескольких уровнях:

| Уровень | Инструментарий | Основной параметр |
| :--- | :--- | :--- |
| **Процессный** | `choom`, `procfs` | `oom_score_adj` |
| **Системные службы** | systemd unit | `OOMScoreAdjust`, `OOMPolicy` |
| **Пользовательский** | `systemd-oomd` | `ManagedOOMMemoryPressure` |
| **Ядерный (Kernel)** | `sysctl` | `vm.panic_on_oom`, `vm.oom_kill_allocating_task`, `vm.overcommit_memory` |
| **Контейнерный** | Docker / K8s | `--oom-score-adj`, классы QoS |

### Настройка oom_score_adj

Рейтинг вычисляется ядром динамически. Настройка `adj` позволяет сместить этот рейтинг:

- **`-1000`**: Исключает процесс из списка жертв. Рекомендуется для: `systemd`, `sshd`, `dbus`, `syslogd`.
- **`-999 … -1`**: Снижает приоритет удаления. Подходит для баз данных (PostgreSQL, Redis) и критичных шин данных.
- **`0`**: Значение по умолчанию для всех обычных процессов.
- **`1 … 1000`**: Повышает риск удаления. Полезно для фоновых заданий, воркеров очередей или браузеров.

**Наследование:** `oom_score_adj` наследуется дочерними процессами через `fork()`/`clone()`. Если вы установили значение для родительского процесса, все его дочерние процессы получат то же значение. Для изменения уже запущенных процессов используйте `choom` или запись в `/proc/PID/oom_score_adj`.

**Потоки:** На уровне ядра `oom_score_adj` привязан к задаче (task_struct), а не к потоку. Все потоки процесса разделяют одно значение.

### Сравнение User-space киллеров

| Инструмент | База принятия решения | Целевая аудитория |
| :--- | :--- | :--- |
| **systemd-oomd** | PSI (Pressure) + Swap % | Современные сервера, K8s ноды. |
| **earlyoom** | % Free RAM + % Free Swap | Десктопы, старые ядра без PSI. |
| **nohang** | PSI + RAM + кастомные скрипты | Максимально гибкая настройка под нагрузку. |

### Memory Overcommit

Ядро Linux по умолчанию разрешает процессам выделять больше памяти, чем физически доступно (`vm.overcommit_memory=0`). Это позволяет запускать приложения с большим heap, не проверяя upfront, хватит ли RAM.

**Режимы overcommit:**

| Режим | Значение | Поведение | Рекомендуемое использование |
| :--- | :--- | :--- | :--- |
| **Heuristic** | `0` | Ядро оценивает риск по эвристике. | Стандарт для десктопов и большинства серверов. |
| **Strict** | `1` | Полный запрет overcommit. `malloc` возвращает `NULL`, если память не гарантирована. | Только для специализированных систем ( real-time,嵌入式 ). |
| **Always** | `2` | Overcommit всегда разрешен. `vm.overcommit_ratio` определяет лимит (RAM + Swap * ratio%). | Контейнерные среды, где лимиты управляются cgroups. |

**Настройка overcommit_ratio (режим 2):**
```bash
# Разрешить overcommit до 50% от RAM + весь Swap
sysctl -w vm.overcommit_memory=2
sysctl -w vm.overcommit_ratio=50
```

### Влияние cgroups v2 на управление OOM

В cgroups v2 (ядро 5.x+, systemd) управление памятью происходит на двух уровнях:

1. **Cgroup-local OOM:** Срабатывает при превышении `memory.max`. Жертва выбирается ТОЛЬКО внутри этой контрольной группы.
2. **System-wide OOM:** Срабатывает при исчерпании всей доступной памяти хоста. Ядро сканирует все процессы системы, включая те, что находятся в cgroups.

**Ключевые параметры cgroups v2 для управления:**

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `memory.min` | Hard guarantee | Память, которую ОС никогда не заберет у группы. |
| `memory.low` | Best-effort | ОС старается не трогать эту память при pressure. |
| `memory.high` | Throttle | Мягкий лимит. При превышении процессы замедляются (reclaim). |
| `memory.max` | Hard limit | Абсолютный потолок. Превышение -> Immediate OOM. |
| `memory.oom.group` | Boolean | Групповое завершение: при OOM в любом процессе убивается ВСЯ группа. |

Детали архитектуры cgroups: [**Контрольные группы (cgroups)**](../cgroups.md).

## Практические сценарии

### Использование утилиты choom

```bash
# Просмотр текущего значения для процесса
choom -p 1234

# Запуск новой программы с пониженным риском (иммунитет для DB)
choom -n -800 ./my_database

# Изменение рейтинга работающего процесса
sudo choom -p 1234 -n 500
```

### Настройка systemd-сервиса (OOMPolicy)

В современных дистрибутивах (Ubuntu 22.04+, Fedora) systemd берет на себя управление жизненным циклом при OOM:

```ini
[Service]
# Смещение рейтинга внутри юнита
OOMScoreAdjust=-500

# Что делать, если процесс юнита был убит OOM Killer:
# stop — остановить весь юнит (по умолчанию)
# continue — не делать ничего (ядро убьет только один процесс)
# restart — перезапустить весь юнит немедленно
OOMPolicy=restart

# Настройки для systemd-oomd (cgroups v2)
ManagedOOMMemoryPressure=kill
ManagedOOMMemoryPressureLimit=60%
```

### Глубокий dive: systemd-oomd

`systemd-oomd` — современный демон, использующий PSI для превентивного завершения процессов до срабатывания ядерного OOM Killer. В отличие от ядерного OOM, он работает на уровне cgroups и может убивать всю группу процессов, а не отдельные задачи.

**Полная конфигурация `/etc/systemd/oomd.conf`:**

```ini
[Service]
# Включить мониторинг
OOMDEnabled=yes

# Порог давления на память (по умолчанию 60%)
DefaultMemoryPressureLimit=60%

# Время удержания порога (по умолчанию 20s)
DefaultMemoryPressureDurationSec=20s

# Порог по доступной памяти (по умолчанию 10%)
DefaultMemoryAvailableLimit=10%

# Исключить критичные сервисы из автоматического управления
[Slice:system.slice]
ManagedOnly=yes

[Unit:sshd.service]
ManagedOnly=no

[Unit:postgres.service]
ManagedOnly=no
```

**Включение и проверка:**
```bash
# Включение и запуск
systemctl enable --now systemd-oomd

# Проверка статуса
systemctl status systemd-oomd

# Мониторинг решений в реальном времени
journalctl -u systemd-oomd -f
```

### Установка и настройка earlyoom

Для систем без systemd-oomd или как запасной вариант:

```bash
# Debian/Ubuntu
sudo apt install earlyoom

# RHEL/Fedora
sudo dnf install earlyoom

# Включение службы
sudo systemctl enable --now earlyoom

# Проверка конфигурации
cat /etc/default/earlyoom
# EARLYOOM_ARGS="-r 60 -s 60 -n 10"  # 60% RAM, 60% Swap, 10% приоритет

# Проверка работы
journalctl -u earlyoom -f
```

### Обзор nohang

`nohang` — максимально гибкий user-space OOM killer с поддержкой кастомных правил и скриптов. Подходит для сложных нагрузок, где стандартные пороги неэффективны.

```bash
# Установка
sudo apt install nohang   # или сборка из исходников

# Запуск в foreground для отладки
sudo nohang -v

# Systemd service
sudo systemctl enable --now nohang
```

### Глобальный тюнинг через sysctl

Параметры, меняющие логику выбора жертвы на всем хосте:

```bash
# Вызывать Kernel Panic вместо убийства процесса (применяется в HA кластерах)
# Позволяет ноде быстро перезагрузиться, передав VIP/ресурсы другой ноде
sysctl -w vm.panic_on_oom=1

# Убить именно тот процесс, который запросил память (быстрая реакция)
# Помогает при резких скачках (spikes), исключая долгий расчет badness
sysctl -w vm.oom_kill_allocating_task=1

# Детальный лог всех процессов в dmesg при срабатывании OOM
sysctl -w vm.oom_dump_tasks=1

# Настройка overcommit (режим 2 — always overcommit с лимитом)
sysctl -w vm.overcommit_memory=2
sysctl -w vm.overcommit_ratio=50

# Постоянное применение через /etc/sysctl.d/99-oom.conf
cat <<EOF | sudo tee /etc/sysctl.d/99-oom.conf
vm.panic_on_oom=0
vm.oom_kill_allocating_task=0
vm.oom_dump_tasks=1
vm.overcommit_memory=0
EOF
sudo sysctl --system
```

### Групповое завершение в cgroups v2

Если ваше приложение состоит из множества процессов (например, PHP-FPM), гибель одного воркера может быть бесполезна. Можно настроить атомное удаление всей группы:

```bash
# На хосте для конкретного контейнера/слайса
echo 1 > /sys/fs/cgroup/system.slice/my_app.service/memory.oom.group

# Проверка текущего значения
cat /sys/fs/cgroup/system.slice/my_app.service/memory.oom.group
```

### Production Hardening Checklist

Проверочный список для настройки OOM-управления на production-серверах:

```bash
#!/bin/bash
# /usr/local/bin/oom_hardening_check.sh
# Проверка базовой защиты от OOM

CHECKS_PASSED=0
CHECKS_FAILED=0

check() {
    local name=$1
    local cmd=$2
    local expected=$3
    local actual=$(eval "$cmd" 2>/dev/null)
    if [ "$actual" = "$expected" ]; then
        echo "[PASS] $name"
        ((CHECKS_PASSED++))
    else
        echo "[FAIL] $name (expected: $expected, actual: $actual)"
        ((CHECKS_FAILED++))
    fi
}

echo "=== OOM Hardening Checklist ==="

# 1. systemd-oomd или earlyoom активны
check "systemd-oomd active" \
    "systemctl is-active systemd-oomd" \
    "active"
check "earlyoom active" \
    "systemctl is-active earlyoom" \
    "active"

# 2. Критичные сервисы имеют OOMScoreAdjust
check "sshd OOMScoreAdjust" \
    "systemctl show sshd -p OOMScoreAdjust | cut -d= -f2" \
    "-900"

# 3. vm.oom_dump_tasks включен
check "vm.oom_dump_tasks" \
    "sysctl -n vm.oom_dump_tasks" \
    "1"

# 4. vm.panic_on_oom выключен (для HA — может быть включен)
check "vm.panic_on_oom" \
    "sysctl -n vm.panic_on_oom" \
    "0"

# 5. memory.oom.group для критичных сервисов
check "nginx oom.group" \
    "cat /sys/fs/cgroup/system.slice/nginx.service/memory.oom.group 2>/dev/null || echo 0" \
    "1"

echo ""
echo "=== Results: $CHECKS_PASSED passed, $CHECKS_FAILED failed ==="
exit $CHECKS_FAILED
```

### Динамическое управление oom_score_adj

Скрипт для автоматической настройки `oom_score_adj` на основе потребления памяти:

```bash
#!/bin/bash
# /usr/local/bin/oom_score_manager.sh
# Автоматическая корректировка oom_score_adj на основе RSS

THRESHOLD_HIGH_MB=512
THRESHOLD_LOW_MB=256
ADJ_HIGH=500
ADJ_LOW=-500

for pid in $(pgrep -d',' -f my_app); do
    rss_kb=$(ps -p $pid -o rss= 2>/dev/null | tr -d ' ')
    [ -z "$rss_kb" ] && continue
    rss_mb=$((rss_kb / 1024))
    
    current_adj=$(cat /proc/$pid/oom_score_adj 2>/dev/null)
    [ -z "$current_adj" ] && continue
    
    if [ "$rss_mb" -gt "$THRESHOLD_HIGH_MB" ]; then
        [ "$current_adj" -lt "$ADJ_HIGH" ] && \
            echo $ADJ_HIGH | sudo tee /proc/$pid/oom_score_adj > /dev/null
    elif [ "$rss_mb" -lt "$THRESHOLD_LOW_MB" ]; then
        [ "$current_adj" -gt "$ADJ_LOW" ] && \
            echo $ADJ_LOW | sudo tee /proc/$pid/oom_score_adj > /dev/null
    fi
done
```

### Мониторинг риска OOM

Скрипт для мониторинга и алертинга:

```bash
#!/bin/bash
# /usr/local/bin/oom_watchdog.sh

THRESHOLD_MEM_AVAILABLE_PCT=10
THRESHOLD_SWAP_FREE_PCT=15
THRESHOLD_PSI_FULL=5.0

check_memory() {
    local mem_available=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
    local mem_total=$(awk '/MemTotal/{print $2}' /proc/meminfo)
    local pct=$(echo "scale=1; 100 * $mem_available / $mem_total" | bc)
    if (( $(echo "$pct < $THRESHOLD_MEM_AVAILABLE_PCT" | bc -l) )); then
        echo "CRITICAL: Available memory ${pct}% < ${THRESHOLD_MEM_AVAILABLE_PCT}%"
        return 1
    fi
    return 0
}

check_swap() {
    local swap_free=$(awk '/SwapFree/{print $2}' /proc/meminfo)
    local swap_total=$(awk '/SwapTotal/{print $2}' /proc/meminfo)
    [ "$swap_total" -eq 0 ] && return 0
    local pct=$(echo "scale=1; 100 * $swap_free / $swap_total" | bc)
    if (( $(echo "$pct < $THRESHOLD_SWAP_FREE_PCT" | bc -l) )); then
        echo "CRITICAL: Free swap ${pct}% < ${THRESHOLD_SWAP_FREE_PCT}%"
        return 1
    fi
    return 0
}

check_psi() {
    [ ! -f /proc/pressure/memory ] && return 0
    local full=$(awk '/^full/{gsub(/avg10=/,"",$2); split($2,a," "); print a[1]}' /proc/pressure/memory)
    if (( $(echo "$full > $THRESHOLD_PSI_FULL" | bc -l) )); then
        echo "CRITICAL: Memory PSI full=${full}% > ${THRESHOLD_PSI_FULL}%"
        return 1
    fi
    return 0
}

if ! check_memory || ! check_swap || ! check_psi; then
    echo "ALERT: $(hostname) - $(date)" | systemd-send-email --admin
    # или webhook: curl -X POST ...
fi
```

Добавление в cron (проверка каждые 2 минуты):
```bash
*/2 * * * * root /usr/local/bin/oom_watchdog.sh >> /var/log/oom_watchdog.log 2>&1
```

### Процедура восстановления после OOM

После срабатывания OOM Killer SRE должен выполнить постмортем:

```bash
# 1. Определить жертву и триггер
dmesg -T | grep -E "oom|killed process" | tail -20

# 2. Проверить, сервис ли перезапустился
systemctl status my_service
journalctl -u my_service --since "10 minutes ago"

# 3. Проверить отсутствие "зомби"-ресурсов
ps aux | grep '<defunct>'
cat /sys/fs/cgroup/system.slice/my_service.service/memory.current

# 4. Проверить swap и overcommit
free -h
cat /proc/sys/vm/overcommit_memory
grep -E 'Commit|Swap' /proc/meminfo

# 5. Настроить защиту, чтобы предотвратить повторение
# Вариант A: systemd unit
systemctl edit my_service
# → [Service]
# → OOMScoreAdjust=-500
# → OOMPolicy=restart

# Вариант B: sysctl (осторожно!)
sysctl -w vm.overcommit_memory=2
sysctl -w vm.overcommit_ratio=80
```

### Stress-тестирование поведения OOM

Безопасная проверка реакции системы на нехватку памяти:

```bash
# Установка утилиты (RHEL/Debian/Ubuntu)
sudo apt install stress-ng   # Debian/Ubuntu
sudo dnf install stress-ng   # RHEL/Fedora

# Тест: занять 90% доступной RAM в фоне
stress-ng --vm 1 --vm-bytes 90% --vm-keep --timeout 60 &

# Параллельный мониторинг
watch -n1 'free -h; echo "---"; cat /proc/pressure/memory; echo "---"; vmstat 1 3'

# В другом окне: проверка логов в реальном времени
dmesg -w | grep -i "out of memory\|oom\|killed process"
```

**Ожидаемый результат:** Через 30–60 секунд `stress-ng` будет убит OOM Killer (exit code 137). Если система зависла — проверяйте настройки `vm.panic_on_oom` и `vm.oom_dump_tasks`.

### Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **OOM при наличии свободного cache** | `vm.min_free_kbytes` слишком высокий или фрагментация | Уменьшение `min_free_kbytes`, проверка `buddyinfo` |
| **Медленный OOM (Freeze)** | Медленный swap (HDD), `vm.swappiness=100` | Переход на SSD, zswap/zram, уменьшение swappiness |
| **Системный panic вместо OOM** | `vm.panic_on_oom=1` | Отключение panic или настройка HA-переключения |
| **Java-процесс убит, несмотря на -1000** | OOM в cgroup (Docker/K8s), а не системный | Проверка `memory.max` и `oom_kill` в cgroup events |
| **Silent OOM в контейнере** | cgroups v2 убивает дочерний процесс, PID 1 жив | Проверка `memory.events` внутри контейнера |
| **systemd-oomd не убивает процессы** | Порог слишком высокий или PSI отключен | Проверка `DefaultMemoryPressureLimit`, `grep CONFIG_PSI /boot/config-$(uname -r)` |
| **Процесс не получает иммунитет -1000** | Родительский процесс уже установил другое значение | Наследование oom_score_adj, нужно менять у родителя |

## Дополнительная информация

### Риски настройки -1000

Установка `-1000` для прожорливого приложения (например, Java с огромным Heap) опасна. Если ядро не может убить «виновника», оно начнет убивать всё остальное: SSH-сервер, агенты мониторинга и даже процессы логирования. В итоге вы получите «сервер-зомби», который недоступен по сети, но продолжает нагружать железо.

### Особенности в Kubernetes

В Kubernetes ручное изменение `oom_score_adj` внутри контейнера бесполезно, так как `kubelet` переписывает это значение на основе **класса QoS** пода при каждом запуске. Используйте `requests` и `limits` для управления приоритетом.

Детали расчета `oom_score_adj` в Kubernetes: [**Управление ресурсами в Kubernetes**](../../../Kubernetes/Scheduling/qos_limit_and_requests.md).

### См. также

- [**Механизм OOM Killer**](./oom_killer_mechanism.md) — теория, PSI и алгоритм badness.
- [**Диагностика OOM Killer**](./oom_killer_diagnostics.md) — разбор логов и выявление причин.
- [**Давление на ресурсы (PSI)**](../kernel/psi.md) — детальное описание метрик для `systemd-oomd`.
