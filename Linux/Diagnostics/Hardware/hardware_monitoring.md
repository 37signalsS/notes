# Аппаратный мониторинг: температура, вентиляторы, напряжение

## Определения

**`lm-sensors` (Linux Monitoring Sensors)** — пакет утилит для чтения данных аппаратных датчиков (температура, напряжение, вентиляторы) через интерфейс ядра `hwmon`. Состоит из библиотеки `libsensors`, утилиты `sensors` для вывода данных и `sensors-detect` для автоматического обнаружения чипов.

**`hwmon` (Hardware Monitoring)** — подсистема ядра Linux, предоставляющая виртуальные файлы в `/sys/class/hwm/` для доступа к аппаратным датчикам. Каждый датчик represented как отдельный `hwmonN` объект с атрибутами `temp1_input`, `fan1_input`, `in0_input` и т.д.

**Thermal Zone** — виртуальная область температуры в `/sys/class/thermal/thermal_zoneN/`, определённая ядром или ACPI. Каждая зона имеет `type` (например, `x86_pkg_temp`, `acpitz`), `temp` (текущая температура в миллиградусах) и `trip_point_*` (пороговые значения).

**Cooling Device** — интерфейс управления охлаждением в `/sys/class/thermal/cooling_deviceN/`. Предоставляет `cur_state` (текущий уровень охлаждения) и `max_state` (максимальный уровень). Используется для управления вентиляторами и троттлингом.

**`hddtemp`** — утилита для чтения температуры жёстких дисков через S.M.A.R.T. (объединена с `smartmontools` в современных дистрибутивах).

**`dell_smm_hwmon` / `coretemp`** — драйверы ядра для доступа к датчикам на конкретных платформах (Dell SMM, Intel Core temperature).

---

## Базовые концепции

### Архитектура мониторинга

```
Аппаратные датчики (VRM, DIMM, CPU, Chipset)
        ↓
Драйверы ядра (coretemp, dell_smm_hwmon, nct6775, it87)
        ↓
/sys/class/hwmon/hwmonN/ (виртуальные файлы)
        ↓
libsensors → sensors (пользовательский вывод)
        ↓
Промetheus node_exporter (для мониторинга в кластере)
```

### Уровни мониторинга

| Уровень | Инструмент | Источник данных | Назначение |
| :--- | :--- | :--- | :--- |
| **Ядро** | `/sys/class/hwmon/`, `/sys/class/thermal/` | Драйверы | Программный доступ из ОС |
| **Пользователь** | `sensors`, `sensors-detect` | libsensors | Интерактивный анализ |
| **Аппаратный** | BMC/IPMI, `ipmitool` | BMC-датчики | Независимый от ОС мониторинг |
| **Мониторинг** | node_exporter, telegraf | hwmon/sysfs | Централизованный сбор метрик |

**Важно:** BMC-датчики и hwmon-датчики работают **независимо**. При расхождении показаний проверьте оба источника.

### Типы датчиков в hwmon

| Тип | Файл | Единица | Пример |
| :--- | :--- | :--- | :--- |
| **Температура** | `tempN_input` | Милиградусы (÷1000 = °C) | `62000` = 62°C |
| **Вентилятор** | `fanN_input` | RPM | `7200` = 7200 об/мин |
| **Напряжение** | `inN_input` | Милливольты (÷1000 = V) | `12000` = 12.0V |
| **Мощность** | `powerN_input` | Микроватты (÷1000000 = W) | `85000000` = 85W |
| **Ток** | `currN_input` | Милиамперы (÷1000 = A) | `500` = 0.5A |

### Пороговые значения (Trip Points)

Термальные зоны имеют trip points — пороговые значения, при которых срабатывают механизмы охлаждения или троттлинга:

| Trip Point | Описание | Действие |
| :--- | :--- | :--- |
| **passive** | Начало троттлинга (снижение частоты) | `thermal_zone trip_point_0_temp` |
| **active** | Включение активного охлаждения (вентиляторы на максимум) | `thermal_zone trip_point_1_temp` |
| **hot** | Предупреждение о перегреве | Логирование, алерт |
| **critical** | Критический перегрев | Аварийное отключение (emergency shutdown) |

---

## Практические сценарии

### Установка и настройка lm-sensors

```bash
# Установка (Debian/Ubuntu)
sudo apt install lm-sensors

# Установка (RHEL/Rocky/Alma)
sudo dnf install lm_sensors

# Автоматическое обнаружение датчиков (интерактивно)
sudo sensors-detect
# → Do you want to probe ...? YES
# → Do you want to probe ...? YES
# → ...

# Просмотр текущих показаний датчиков
sensors
# → coretemp-isa-0000
# → Adapter: ISA adapter
# → Core 0:       +62.0°C  (high = +80.0°C, crit = +100.0°C)
# → Core 1:       +58.0°C  (high = +80.0°C, crit = +100.0°C)
# → Core 2:       +65.0°C  (high = +80.0°C, crit = +100.0°C)
# → Core 3:       +60.0°C  (high = +80.0°C, crit = +100.0°C)
# → nvme-pci-01:00
# → Adapter: PCI adapter
# → Composite:    +42.9°C  (low  = -273.1°C, high = +81.8°C)
# → Sensor 1:     +44.9°C  (low  = -273.1°C, high = +81.8°C)

# Мониторинг в реальном времени (обновление каждую секунду)
watch -n1 sensors

# Вывод в формате JSON (для скриптов)
sensors -j
# → {"coretemp-isa-0000":{"Core 0":{"temp1_input":62.000}}}
```

### Интерпретация вывода sensors

```bash
# Ключевые пороговые значения
sensors | grep -E "high|crit|alarm"
# → Core 0:       +62.0°C  (high = +80.0°C, crit = +100.0°C)
#                     ↑ текущая     ↑ предупреждение   ↑ критический перегрев

# Проверка наличия критических значений
sensors | grep -c "ALARM\|CRIT"
# → 0 (норма) или >0 (проблема)
```

### Прямой доступ через hwmon (sysfs)

```bash
# Поиск всех hwmon-устройств
ls /sys/class/hwmon/
# → hwmon0  hwmon1  hwmon2  hwmon3

# Просмотр имени каждого hwmon
for hwmon in /sys/class/hwmon/hwmon*; do
  echo "$(basename $hwmon): $(cat $hwmon/name 2>/dev/null)"
done
# → hwmon0: coretemp
# → hwmon1: nvme
# → hwmon2: nct6798
# → hwmon3: amdgpu

# Температура ядра CPU через hwmon
cat /sys/class/hwmon/hwmon0/temp1_input
# → 62000  (милиградусы = 62.0°C)

# Пороговые значения
cat /sys/class/hwmon/hwmon0/temp1_max
# → 80000  (80°C)
cat /sys/class/hwmon/hwmon0/temp1_crit
# → 100000 (100°C)

# Вентиляторы через hwmon
cat /sys/class/hwmon/hwmon2/fan1_input
# → 7200  (RPM)
cat /sys/class/hwmon/hwmon2/fan2_input
# → 0  (не работает!)
```

### Автоматический мониторинг температуры NVMe

```bash
# Проверка температуры NVMe через sysfs
cat /sys/block/nvme0n1/device/hwmon1/temp1_input
# → 42000  (42°C)

# Порог троттлинга NVMe
cat /sys/block/nvme0n1/device/hwmon1/temp1_max
# → 81000  (81°C)
```

### Диагностика thermal throttling

```bash
# Проверка thermal zones
for tz in /sys/class/thermal/thermal_zone*; do
  TYPE=$(cat "$tz/type" 2>/dev/null)
  TEMP=$(cat "$tz/temp" 2>/dev/null)
  echo "$TYPE: $((TEMP/1000))°C"
done
# → x86_pkg_temp: 62°C
# → acpitz: 35°C
# → nvme: 42°C

# Проверка trip points
for tz in /sys/class/thermal/thermal_zone*; do
  TYPE=$(cat "$tz/type" 2>/dev/null)
  for tp in "$tz"/trip_point_*_temp; do
    [ -f "$tp" ] && echo "$TYPE trip: $(( $(cat $tp) / 1000 ))°C"
  done
done

# Проверка cooling devices
for cd in /sys/class/thermal/cooling_device*; do
  TYPE=$(cat "$cd/type" 2>/dev/null)
  CUR=$(cat "$cd/cur_state" 2>/dev/null)
  MAX=$(cat "$cd/max_state" 2>/dev/null)
  echo "$TYPE: $CUR/$MAX"
done
# → x86_pkg_freq: 0/3  (0 = нет троттлинга)
```

### Мониторинг вентиляторов

```bash
# Все вентиляторы через hwmon
grep -r "fan" /sys/class/hwmon/hwmon*/fan*_input 2>/dev/null | while read line; do
  FILE=$(echo $line | cut -d: -f1)
  RPM=$(cat $line 2>/dev/null)
  HWMON=$(echo $FILE | grep -o "hwmon[0-9]*")
  FAN=$(echo $FILE | grep -o "fan[0-9]*")
  echo "$HWMON/$FAN: $RPM RPM"
done

# Обнаружение неработающих вентиляторов
for fan in /sys/class/hwmon/hwmon*/fan*_input; do
  [ -f "$fan" ] || continue
  RPM=$(cat "$fan" 2>/dev/null)
  if [ "$RPM" -eq 0 ] 2>/dev/null; then
    echo "CRITICAL: $(dirname $fan | xargs basename)/$(basename $fan _input) not spinning!"
  fi
done
```

### Мониторинг напряжений

```bash
# Все напряжения через hwmon
for inp in /sys/class/hwmon/hwmon*/in*_input; do
  [ -f "$inp" ] || continue
  MV=$(cat "$inp" 2>/dev/null)
  V=$(echo "scale=3; $MV/1000" | bc)
  NAME=$(cat "$(dirname $inp)/in*_label" 2>/dev/null || basename $inp _input)
  echo "$NAME: ${V}V"
done

# Проверка критических напряжений
sensors | grep -E "ALARM|CRIT|MIN|MAX"
```

### Настройка драйверов через modprobe

```bash
# Проверка загруженных драйверов hwmon
lsmod | grep -E "coretemp|nct6775|it87|dell_smm|k10temp|asus_wmi"

# Ручная загрузка драйвера (если не загружается автоматически)
sudo modprobe coretemp
sudo modprobe nct6778

# Параметры драйвера (например, force для nct6775)
sudo modprobe nct6775 force_id=0xc800

# Сохранение настроек
echo "options nct6775 force_id=0xc800" | sudo tee /etc/modprobe.d/nct6775.conf
```

### Интеграция с Prometheus (node_exporter)

node_exporter автоматически экспортирует hwmon-метрики:

```bash
# Ключевые метрики Prometheus
# node_hwmon_temp_celsius{chip="coretemp",sensor="core_0"}  62
# node_hwmon_fan_rpm{chip="nct6798",sensor="fan1"}  7200
# node_hwmon_in_volts{chip="nct6798",sensor="in0"}  1.05
# node_hwmon_power_watts{chip="nct6798",sensor="power1"}  85
# node_thermal_zone_temp{type="x86_pkg_temp"}  62
```

**Пример alerting-правил:**
```yaml
groups:
  - name: hardware_monitoring
    rules:
      - alert: CpuTemperatureHigh
        expr: node_hwmon_temp_celsius > 75
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "CPU温度高: {{ $labels.sensor }} = {{ $value }}°C"

      - alert: CpuTemperatureCritical
        expr: node_hwmon_temp_celsius > 90
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "CPU温度критическая: {{ $labels.sensor }} = {{ $value }}°C"

      - alert: FanFailed
        expr: node_hwmon_fan_rpm == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Вентилятор не работает: {{ $labels.chip }}/{{ $labels.sensor }}"

      - alert: VoltageLow
        expr: node_hwmon_in_volts < 0.95
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Низкое напряжение: {{ $labels.sensor }} = {{ $value }}V"
```

### Скрипт для быстрой оценки здоровья сервера

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== Hardware Health Check: $(hostname) ==="
echo ""

# 1. Температуры
echo "--- Temperatures ---"
sensors 2>/dev/null | grep -E "Core|Composite|temp[0-9]" | while read line; do
  TEMP=$(echo "$line" | grep -oP '\+\K[0-9]+(?=\.)')
  if [ "${TEMP:-0}" -gt 75 ]; then
    echo "WARN: $line"
  elif [ "${TEMP:-0}" -gt 90 ]; then
    echo "CRIT: $line"
  fi
done

# 2. Вентиляторы
echo ""
echo "--- Fans ---"
for fan in /sys/class/hwmon/hwmon*/fan*_input; do
  [ -f "$fan" ] || continue
  RPM=$(cat "$fan" 2>/dev/null)
  if [ "${RPM:-0}" -eq 0 ]; then
    echo "CRIT: $(basename $fan) = 0 RPM (not spinning!)"
  elif [ "${RPM:-0}" -lt 1000 ]; then
    echo "WARN: $(basename $fan) = $RPM RPM (low)"
  fi
done

# 3. NVMe температура
echo ""
echo "--- NVMe ---"
for nvme in /sys/block/nvme*/device/hwmon*/temp1_input; do
  [ -f "$nvme" ] || continue
  TEMP=$(($(cat "$nvme") / 1000))
  echo "$(dirname $nvme | xargs basename): ${TEMP}°C"
  [ "$TEMP" -gt 70 ] && echo "  WARN: NVMe throttling risk!"
done

echo ""
echo "=== Check complete ==="
```

---

## Дополнительная информация

### Типичные пороговые значения

| Компонент | Норма | Предупреждение | Критично | Действие |
| :--- | :--- | :--- | :--- | :--- |
| **CPU Core** | 30–65°C | > 75°C | > 90°C | Проверка охлаждения, троттлинг |
| **CPU Package** | 30–70°C | > 80°C | > 95°C | Немедленная диагностика |
| **DIMM (память)** | 25–50°C | > 65°C | > 85°C | Проверка вентиляции |
| **NVMe SSD** | 30–60°C | > 70°C | > 80°C | Троттлинг, возможная деградация |
| **VRM (Voltage Regulator)** | 40–80°C | > 90°C | > 105°C | Проверка воздушного потока |
| **Вентиляторы** | 1000–8000 RPM | < 1000 RPM | 0 RPM | Замена вентилятора |

### Причины перегрева

1. **Пыль** — забитые фильтры и радиаторы (самая частая причина).
2. **Отказ вентилятора** — неработающий вентилятор на кулере или в корпусе.
3. **Неправильный воздушный поток** — неправильно установленные вентиляторы (pull vs push).
4. **Высокая нагрузка** — длительная 100% утилизация CPU/GPU.
5. **Плохой контакт** — неправильно установленный кулер, высохшая термопаста.
6. **Окружение** — высокая температура в серверной (>30°C).

### Корреляция: hwmon vs IPMI

Если `sensors` показывает 62°C, а `ipmitool sensors` показывает 62°C — данные совпадают.
Если расхождение >10°C — проверьте:
- Какой датчик мониторит BMC (часто другой чип, другой location).
- Драйвер hwmon может читать датчик CPU Package, а BMC — Inlet Temp.

### Связанные темы

- **[IPMI/BMC](./ipmi_bmc.md)** — удалённое управление и аппаратные датчики.
- **[CPU: диагностика](./cpu_info.md)** — троттлинг, C-states, частота.
- **[NVMe: ошибки и диагностика](./nvme-errors-diagnostics.md)** — AER, APST, троттлинг.
- **[SMART: мониторинг дисков](./smartctl/index.md)** — температура накопителей.
- **[dmesg: thermal throttling](../Kernel/dmesg/cpu-frequency.md)** — системные thermal-события.
- **[Анализ перезагрузок](../Troubleshooting/reboot_troubleshooting.md)** — thermal trip → emergency shutdown.
