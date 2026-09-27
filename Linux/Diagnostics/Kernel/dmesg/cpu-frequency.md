# Диагностика частоты CPU и power management через dmesg

## Определения

**События частоты CPU в dmesg** — выводы ядра, отражающие изменения частоты процессора, переходы между C-states (режимы энергосбережения) и P-states (режимы производительности), тепловое троттлинг, проблемы с драйверами cpufreq (intel_pstate, amd-pstate, acpi-cpufreq) и блокировку частот. Эти сообщения критичны для диагностики проблем с производительностью и энергопотреблением.

---

## Базовые концепции

### Архитектура управления частотой CPU

```
Приложение
    ↓
Планировщик (Scheduler)
    ↓
cpufreq subsystem
    ├─ intel_pstate (Intel, kernel 3.9+)
    ├─ amd-pstate (AMD, kernel 5.17+)
    └─ acpi-cpufreq (универсальный)
    ↓
BIOS/UEFI (P-states, C-states, Turbo Boost)
    ↓
Аппаратура (CPU frequency scaling)
```

### Типы событий в dmesg

| Сообщение | Тип | Описание |
|:---|:---|:---|
| `intel_pstate: HWP enabled` | Info | Hardware P-states активированы |
| `intel_pstate: Turbo disabled` | Warning | Turbo Boost отключён (BIOS или перегрев) |
| `CPU X:オンライン` | Info | Ядро CPU X активировано |
| `ACPI: ... failed` | Error | Ошибка ACPI-таблицы (часто влияет на freq) |
| `thermal: ... temperature above threshold` | Warning | Тепловое троттлинг |
| `cpufreq: ... frequency change` | Debug | Изменение частоты |

---

## Практические сценарии

### Поиск событий частоты в dmesg

```bash
# Все события cpufreq
dmesg -T | grep -iE "cpufreq|pstate|acpi.*freq|turbo|freq.*change|scaling"

# Тепловое троттлинг
dmesg -T | grep -iE "thermal|throttl|overheat|cpu.*temp|temperature"

# Ошибки ACPI (влияют на частоту)
dmesg -T | grep -iE "acpi.*error|acpi.*fail|acpi.*bios"
```

### Диагностика intel_pstate

```bash
# Проверка загрузки драйвера
dmesg | grep -iE "intel_pstate|hwp|epp|turbo"

# Ключевые паттерны:
# -> intel_pstate: Intel P-state driver active
# -> intel_pstate: HWP enabled
# -> intel_pstate: Turbo Disabled
# -> intel_pstate: epp performance
# -> intel_pstate: epp balance_performance

# Проверка текущего режима
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver
# -> intel_pstate

# Проверка доступных governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors
# -> performance powersave

# Проверка текущей частоты
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
# -> 2400000 (2.4 GHz)
```

### Диагностика amd-pstate

```bash
# Проверка загрузки драйвера
dmesg | grep -iE "amd_pstate|amd.*freq|cppc"

# Ключевые паттерны:
# -> amd-pstate: AMD P-State driver active
# -> amd-pstate: max_freq: 4500000
# -> amd-pstate: min_freq: 1400000

# Проверка режима
cat /sys/devices/system/cpu/cpu0/cpufreq/amd_pstate_status 2>/dev/null
# -> active / guided / passive
```

### Диагностика теплового троттлинг

```bash
# Все thermal-события
dmesg -T | grep -iE "thermal|throttl|overheat|cpu.*temp|temperature"

# Ключевые паттерны:
# -> thermal: thermal_zone0: critical temperature reached (100 C)
# -> thermal: cpu cooling device state updated: 95 C -> throttled
# -> thermal: trip point 1 reached: 90 C
# -> x86_pkg_temp: critical temperature reached (100 C), throttling

# Проверка текущих температур
sensors | grep -A2 "coretemp"

# Проверка thermal zones
cat /sys/class/thermal/thermal_zone0/temp
cat /sys/class/thermal/thermal_zone0/type

# Корреляция с dmesg
# Если в dmesg видно "throttling" -- проверьте:
# 1. Охлаждение (радиатор, вентиляторы)
# 2. Пасту/прокладку
# 3. BIOS/UEFI (включён ли PWM fan control)
```

### Диагностика C-states и P-states

```bash
# Проверка C-states
dmesg | grep -iE "cstate|idle|intel_idle|acpi_idle"

# Ключевые паттерны:
# -> intel_idle: ACPI: ... C1, C3, C6
# -> cpuidle: governors: menu, teo, haltpoll

# Проверка доступных C-states
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/name
# -> POLLING S0ix S0i1 S0i3

# Проверка residency (сколько времени в C-state)
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/usage
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/time

# Для production (latency-sensitive):
# 1. Отключить глубокие C-states через BIOS
# 2. Или через sysctl: echo 1 > /sys/devices/system/cpu/cpu0/cpuidle/state3/disable
```

### Диагностика Turbo Boost

```bash
# Проверка Turbo
dmesg | grep -iE "turbo|boost|bost"

# Ключевые паттерны:
# -> intel_pstate: Turbo Disabled
# -> intel_pstate: Turbo Enabled

# Проверка текущего статуса
cat /sys/devices/system/cpu/intel_pstate/no_turbo
# -> 0 = Turbo включён, 1 = Turbo отключён

# Проверка максимальной частоты
cat /proc/cpuinfo | grep "cpu MHz" | head -1
# -> cpu MHz : 3600.000 (если Turbo работает)
```

### Диагностика power capping

```bash
# Проверка power capping (Rapl)
dmesg | grep -iE "rapl|power.*cap|energy"

# Ключевые паттерны:
# -> rapl: Package power limit notification
# -> powercap: intel-rapl: package 0 constraint 0 exceeded

# Проверка текущих лимитов
cat /sys/class/powercap/intel-rapl*/constraint_0/max_power_uw
cat /sys/class/powercap/intel-rapl*/constraint_0/power_limit_uw
```

---

## Дополнительная информация

### Связанные темы

*   [**CPU Isolation**](../../../Core/kernel/cpu_isolation.md) — изоляция CPU, отключение C-states/P-states.
*   [**TuneD**](../../../Core/tuned.md) — автоматическая настройка cpufreq через TuneD.
*   [**CPU Info**](../../Hardware/cpu_info.md) — диагностика CPU, turbostat, cpupower.
*   [**Network Latency Optimization**](../../../Networking/Concepts/network_latency_optimization.md) — влияние C-states на latency.
*   [**Обзор dmesg**](./index.md) — общая архитектура kmsg.
*   [**Поиск и устранение неисправностей**](./troubleshooting.md) — thermal throttling.
