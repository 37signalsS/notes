# Диагностика и управление через IPMI/BMC

## Определения

**BMC (Baseboard Management Controller)** — встроенный микроконтроллер на материнской плате сервера, функционирующий независимо от основного процессора и операционной системы. BMC обеспечивает удалённый доступ к управлению сервером через выделенный сетевой интерфейс (LAN), даже когда ОС не отвечает или сервер выключен (в режиме standby).

**IPMI (Intelligent Platform Management Interface)** — открытый стандарт (璨Specification v2.0) для управления аппаратурой сервера через BMC. Определяет протоколы доступа к датчикам, журналам событий, управлению питанием и вентиляторам.

**SEL (System Event Log)** — аппаратный журнал событий BMC, фиксирующий аппаратные ошибки (MCE, перегрев, ошибки ECC, срабатывание watchdog), события питания и изменений конфигурации. В отличие от syslog, SEL сохраняется даже при обесточивании сервера (в энергонезависимой памяти BMC).

**DRAC (Dell Remote Access Controller)** — проприетарная реализация BMC от Dell. Текущая версия — iDRAC9 (2024+). Предоставляет расширенный функционал: виртуальную консоль (KVM over IP), virtual media, RAID-мониторинг.

**iLO (Integrated Lights-Out)** — проприетарная реализация BMC от HPE (Hewlett Packard Enterprise). Текущая версия — iLO 6. Поддерживает мониторинг через Redfish API.

**Redfish** — современный RESTful API-стандарт (DMTF) для управления серверной инфраструктурой. Заменяет классические IPMI-команды JSON/HTTP-запросами. Поддерживается всеми крупными производителями (Dell iDRAC, HPE iLO, Supermicro, Lenovo XClarity).

---

## Базовые концепции

### Архитектура BMC и изолированность

BMC работает как отдельная мини-система с собственным процессором, ОС (обычно Linux-based), сетевым интерфейсом и питанием:

- **Независимость:** BMC функционирует даже при выключенном основном процессоре (режим standby). Это единственный способ удалённо включить/выключить сервер.
- **Выделенный порт:** BMC доступен через отдельный RJ-45 порт (обычно обозначен как `iDRAC`, `iLO`, `IPMI` или с иконкой"),

**Важно:** BMC и основная ОС используют разные сетевые стеки. BMC работает на выделенном VLAN/подсети для безопасности.

### Ключевые возможности BMC

| Функция | Описание | Критичность для SRE |
| :--- | :--- | :--- |
| **Управление питанием** | Включение/выключение/перезагрузка сервера, soft shutdown | **Критическая** — единственный способ при зависании ОС |
| **Virtual Console (KVM)** | Удалённый доступ к экрану и клавиатуре сервера | **Высокая** — диагностика загрузки, GRUB, POST |
| **Virtual Media** | Монтирование ISO-образов через сеть | **Высокая** — установка ОС, восстановление, обновление прошивки |
| **SEL (System Event Log)** | Чтение и очистка аппаратного журнала | **Критическая** — поиск причины аппаратного сбоя |
| **Мониторинг датчиков** | Температура, напряжение, RPM вентиляторов | **Высокая** — предиктивная диагностика |
| **Virtual Media / SD** | Эмуляция USB-накопителя | Средняя — установка ОС, обновление |
| **Serial Over LAN (SOL)** | Консоль через сеть | **Высокая** — удалённая отладка |

### Протоколы доступа

| Протокол | Утилита | Описание |
| :--- | :--- | :--- |
| **IPMI 2.0** | `ipmitool` | Классический протокол. Работает через UDP (623). |
| **Redfish** | `curl`, `redfishtool` | RESTful API. Современная замена IPMI. |
| ** vendor-CLI** | `racadm` (Dell), `ssacli` (HPE) | Проприетарные инструменты с расширенным функционалом. |

---

## Практические сценарии

### Базовая настройка и подключение

```bash
# Установка ipmitool (Debian/Ubuntu)
sudo apt install ipmitool

# Установка ipmitool (RHEL/Rocky/Alma)
sudo dnf install ipmitool

# Проверка доступности BMC-интерфейса
sudo ipmitool lan print
# → IP Address: 10.0.0.100
# → MAC Address: 3c:ec:ef:12:34:56
# → Subnet Mask: 255.255.255.0

# Настройка IP-адреса BMC (если не настроен)
sudo ipmitool lan set 1 ipaddr 10.0.0.100
sudo ipmitool lan set 1 netmask 255.255.255.0
sudo ipmitool lan set 1 defgw ipaddr 10.0.0.1
```

### Управление питанием сервера

```bash
# Текущее состояние питания
sudo ipmitool power status
# → Chassis Power is on

# Включить сервер (мгновенно)
sudo ipmitool power on

# Мягкое выключение (Graceful Shutdown — ACPI)
sudo ipmitool power soft

# Принудительное выключение (аналог нажатия кнопки)
sudo ipmitool power off

# Циклическое перезапуск (Power Cycle)
sudo ipmitool power cycle

# Warm Reset (программный сброс без полного POST)
sudo ipmitool power reset
```

**Важно для SRE:** При зависании ОС используйте `power soft` (ожидание ACPI ~60 сек) или `power off` (мгновенно). `power cycle` — для полной перезагрузки с POST.

### Чтение System Event Log (SEL)

SEL — главный источник информации при аппаратных сбоях. В отличие от syslog, он сохраняется при обесточивании.

```bash
# Просмотр всех событий SEL
sudo ipmitool sel list
# → 1 | 01/01/1970 | 00:00:01 | Physical Security #0x41 | Discrete | OK
# → 2 | 03/15/2026 | 14:22:01 | Voltage #1 | Lower Critical | OK
# → 3 | 03/15/2026 | 14:22:05 | Processor #0x01 | ECC Correctable | OK

# Фильтрация по типу события
sudo ipmitool sel list | grep -i "ecc\|memory\|mce\|panic\|watchdog\|temperature"

# Информация о ёмкости SEL
sudo ipmitool sel info
# → Entries: 45
# → Free Space: 5872 bytes
# → Percent Used: 12%

# Экспорт SEL в файл (для анализа)
sudo ipmitool sel list > /tmp/sel_export_$(date +%Y%m%d).txt

# Очистка SEL (после сохранения!)
sudo ipmitool sel clear
# →cleared_SEL completed
```

### Мониторинг датчиков (Sensors)

BMC имеет собственные аппаратные датчики, независимые от `lm-sensors` ОС:

```bash
# Список всех доступных датчиков
sudo ipmitool sdr list
# → SIMC  | OK    | na   | 45h | ok | na | 25 C
# → FAN1  | OK    | 7.20 | 30h | ok | 7h | 7200 RPM
# → +12V  | OK    | na   | 51h | ok | na | 12.08 Volts

# Только критические датчики (temperature, fan, voltage)
sudo ipmitool sdr type temperature
sudo ipmitool sdr type fan
sudo ipmitool sdr type voltage

# Текущие показания датчиков в человекочитаемом формате
sudo ipmitool sensors
# → SIMC        | 25.000     | degrees C  | ok    | na
# → FAN1        | 7200.000   | RPM        | ok    | na
# → +12V        | 12.080     | Volts      | ok    | na
# → +1.05V      | 1.048      | Volts      | ok    | na
# → BP0_TEMP    | 42.000     | degrees C  | ok    | na

# Детальная информация о конкретном датчике
sudo ipmitool sdr get "SIMC"
```

### Диагностика перегрева и охлаждения

```bash
# Все температурные датчики
sudo ipmitool sdr type temperature
# → Inlet Temp    | 22.000 | degrees C  | ok | 3h | 44
# → CPU1 Temp     | 62.000 | degrees C  | ok | 1h | 95
# → CPU2 Temp     | 58.000 | degrees C  | ok | 2h | 95
# → DIMM A1 Temp  | 45.000 | degrees C  | ok | Eh | 85

# Все вентиляторы
sudo ipmitool sdr type fan
# → FAN1  | 7200.000 | RPM | ok | 30h | 7h
# → FAN2  | 7200.000 | RPM | ok | 31h | 7h
# → FAN3  | 0.000    | RPM | ok | 32h | 7h  ← Не работает!

# Проверка teardown (пониженные обороты)
sudo ipmitool sdr type fan | awk -F'|' '{gsub(/ /,"",$4); if($4+0 < 1000) print "WARN: fan low:", $0}'
```

### Диагностика питания (PSU)

```bash
# Статус блоков питания (для серверов с redundant PSU)
sudo ipmitool sdr type power
# → PS1 Status   | OK     | Redundant | 70h | ok | 10h
# → PS2 Status   | OK     | Redundant | 71h | ok | 10h
# → PS1 Input Vol| 220.000| Volts     | 72h | ok | 10h
# → PS2 Input Vol| 220.000| Volts     | 73h | ok | 10h

# Проверка отсутствующего PSU
sudo ipmitool sdr type power | grep -i "not present\|absent\|fail"
```

### Serial Over LAN (SOL) — удалённая консоль

```bash
# Запуск удалённой консоли (аналог мини-терминала через IPMI)
sudo ipmitool sol activate
# → Now attached to SOL session. Press Ctrl-x to disconnect.

# Деактивация SOL
sudo ipmitool sol deactivate

# Настройка SOL (скорость, буфер)
sudo ipmitool sol set non-volatile-bitrate 115200
sudo ipmitool sol set volatile-bitrate 115200
```

**Применение:** Диагностика на этапе POST, настройка BIOS, восстановление загрузчика — всё через сеть, без физического доступа.

### Serial/UART diagnostics

```bash
# Проверка(serial port BMC)
sudo ipmitool -I serial-terminal sol info

# Прямой доступ к последовательному порту
sudo ipmitool -I serial-terminal sol activate
```

### Управление Boot Order через IPMI

```bash
# Текущий boot device
sudo ipmitool chassis bootdev
# → Response: Boot device bitmask
# Options: none, pxelocal, disk, disk-non-volatile

# Установка PXE-boot для следующей загрузки (одноразово)
sudo ipmitool chassis bootdev pxe

# Установка загрузки с диска (persistent)
sudo ipmitool chassis bootdev disk options=persistent

# Установка CD/DVD для следующей загрузки
sudo ipmitool chassis bootdev cdrom
```

### Vendor-специфичные инструменты

#### Dell (racadm / iDRAC)

```bash
# Установка racadm (Linux)
sudo apt install dell-server-admin

# Просмотр системной информации
sudo racadm getsysteminfo

# Просмотр температур
sudo racadm storage get pdisks -o -p SystemHealth

# Просмотр SEL
sudo racadm storage get sel

# Обновление прошивки iDRAC
sudo racadm update -f <firmware.exe>

# Remote reset iDRAC
sudo racadm racreset soft
```

#### HPE (ssacli / iLO)

```bash
# Просмотр состояния сервера
sudo ssacli ctrl all show config

# Просмотр_TEMPERATURE
sudo hponcfg --getribcl

# Через Redfish API (HPE iLO 5/6)
curl -k -u admin:password https://ilox.example.com/redfish/v1/Managers/1/
```

### Redfish API (современный подход)

```bash
# Системная информация (через Redfish)
curl -k -u admin:password \
  https://bmc.example.com/redfish/v1/Systems/1/

# Управление питанием
curl -k -u admin:password \
  -X POST https://bmc.example.com/redfish/v1/Systems/1/Actions/ComputerSystem.Reset \
  -H "Content-Type: application/json" \
  -d '{"ResetType": "GracefulShutdown"}'

# Просмотр датчиков
curl -k -u admin:password \
  https://bmc.example.com/redfish/v1/Chassis/1/Thermal

# SEL (System Event Log)
curl -k -u admin:password \
  https://bmc.example.com/redfish/v1/Managers/1/LogServices/SEL/Entries
```

### Автоматизация: скрипт диагностики сервера

```bash
#!/usr/bin/env bash
set -euo pipefail

# Быстрая аппаратная диагностика через IPMI
HOST="${1:-localhost}"
OUT_DIR="/tmp/ipmi-diag-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR"

echo "=== Диагностика $HOST ==="

# 1. Статус питания
ipmitool -H "$HOST" -U admin -P password power status > "$OUT_DIR/power.txt"

# 2. SEL (последние 50 событий)
ipmitool -H "$HOST" -U admin -P password sel list | tail -50 > "$OUT_DIR/sel.txt"

# 3. Температуры
ipmitool -H "$HOST" -U admin -P password sdr type temperature > "$OUT_DIR/temps.txt"

# 4. Вентиляторы
ipmitool -H "$HOST" -U admin -P password sdr type fan > "$OUT_DIR/fans.txt"

# 5. Напряжения (PSU)
ipmitool -H "$HOST" -U admin -P password sdr type voltage > "$OUT_DIR/voltage.txt"

# 6. Проверка критических событий
CRITICAL=$(ipmitool -H "$HOST" -U admin -P password sel list | grep -icE "critical|fail|error|panic|mce|ecc")
echo "Критических событий в SEL: $CRITICAL"

# 7. Проверка вентиляторов
FAILED_FANS=$(ipmitool -H "$HOST" -U admin -P password sdr type fan | grep -ic "ok\|nr" || true)
if [ "$FAILED_FANS" -gt 0 ]; then
  echo "WARN: Обнаружены неработающие вентиляторы!"
fi

echo "Артефакты: $OUT_DIR"
```

---

## Дополнительная информация

### Корреляция с датчиками ОС (lm-sensors)

BMC-датчики и датчики ОС (`lm-sensors`) работают независимо. При расхождении показаний:
- **BMC показывает перегрев, ОС — норму:** Проблема с датчиком ОС (неправильный �айвер) или BMC-датчик located на VRM.
- **ОС показывает перегрев, BMC — норму:** BMC мониторит другие зоны (входящий воздух vs. CPU).
- **Оба показывают перегрев:** Реальный перегрев. Проверьте вентиляторы, пыль, термопасту.

### SEL vs syslog vs journald

| Источник | Уровень | Сохраняется при power loss | Типичные события |
| :--- | :--- | :--- | :--- |
| **SEL (BMC)** | Аппаратный | **Да** | MCE, ECC, watchdog, PSU fail, thermal trip |
| **dmesg** | Ядро | Нет (только RAM) | AER, I/O error, NVMe reset, OOM |
| **syslog/journald** | Приложение | Нет (на диске) | Сервисные падения, ошибки приложений |

**Правило:** При аппаратном сбое **всегда** проверяйте SEL первым — это единственный источник, гарантированно сохранивший данные.

### Безопасность BMC

- **Смените пароль по умолчанию** — пароли `admin/admin` notoriously known.
- **Выделенная сеть BMC** — не размещайте BMC в общей production-подсети.
- **Отключите ненужные сервисы** — serial-over-LAN, virtual media, если не используются.
- **Фильтрация MAC** — ограничьте доступ к BMC по MAC-адресам.
- **Firmware updates** — обновляйте BMC регулярно (через vendor tools или Redfish).

### Связанные темы

- **[Аппаратный мониторинг (thermal, fans)](./hardware_monitoring.md)** — датчики ОС через lm-sensors.
- **[ECC/EDAC/MCE](./memory_ecc_edac.md)** — ошибки памяти, часто фиксируемые в SEL.
- **[Анализ перезагрузок](../Troubleshooting/reboot_troubleshooting.md)** — MCE, watchdog, SEL correlation.
- **[CPU: диагностика](./cpu_info.md)** — частота, троттлинг, thermal.
- **[BIOS/UEFI и firmware](../../Core/firmware_bios_uefi.md)** — настройка загрузки, Secure Boot.
