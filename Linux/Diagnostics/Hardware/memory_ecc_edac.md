# Диагностика ошибок памяти: ECC, EDAC и MCE

## Определения

**ECC (Error Correction Code)** — аппаратный механизм обнаружения и исправления однобитовых ошибок памяти (CE — Correctable Error) и обнаружения двухбитовых ошибок (UE — Uncorrectable Error) в модулях RAM. Используется на серверных платформах с поддержкой Registered DIMM (RDIMM) или Load-Reduced DIMM (LRDIMM).

**EDAC (Error Detection And Correction)** — подсистема ядра Linux, предоставляющая интерфейс для чтения аппаратных счётчиков ошибок памяти через модули ядра (`edac_mce`, `edac_core`, `edac_mcx`) и утилиту `edac-util`. Позволяет определить конкретный модуль RAM с ошибкой по физическим координатам (channel, slot, DIMM).

**MCE (Machine Check Exception)** — механизм аппаратного мониторинга CPU, обнаруживающий ошибки на уровне процессора и памяти. MCE записывает ошибки в MSRs (Model-Specific Registers) и логирует их через `mcelog` или `rasdaemon`. Классифицируется как recoverable (CE) или fatal (UE).

**MCA (Machine Check Architecture)** — архитектура x86 для.reporting аппаратных ошибок через banks MCi (i = 0..N). Каждый bank мониторит определённый ресурс (память, I/O, cache). Содержит регистры `MCi_STATUS`, `MCi_ADDR`, `MCi_MISC`.

**Correctable Error (CE)** — однобитовая ошибка, исправленная аппаратно ECC. Не влияет на данные, но рост частоты CE указывает на деградацию модуля памяти.

**Uncorrectable Error (UE)** — двухбитовая (или более) ошибка, которую ECC не может исправить. Данные повреждены. Требует немедленной замены модуля.

**Row Hit / Row Kill** — ошибки на уровне строк памяти. Row hit — единичная ошибка в строке. Row kill — критическая ошибка, требующая восстановления строки.

**Rank** — логическая группа DRAM-чипов, формирующая один банк памяти. Ошибки могут быть привязаны к конкретному rank.

---

## Базовые концепции

### Типы ошибок памяти

| Тип | Описание | Влияние | Действие |
| :--- | :--- | :--- | :--- |
| **CE (Correctable)** | Однобитовая ошибка, исправлена ECC | Данные сохранены | Мониторинг, замена при росте частоты |
| **UCE (Uncorrectable Error)** | Двухбитовая ошибка, не исправлена | Данные повреждены | Немедленная замена модуля |
| **SCE (Software Correctable)** | Программно исправленная ошибка | Данные сохранены | Мониторинг |
| **Link Error** | Ошибка шины между CPU и памятью | Возможные CE/UE | Проверка соединений |

### Архитектура ECC и каналов памяти

Современные серверы (Intel Xeon, AMD EPYC) используют многоканальную архитектуру:

```
CPU Socket 0
├── Channel A (DIMM A1, A2)
├── Channel B (DIMM B1, B2)
├── Channel C (DIMM C1, C2)
└── Channel D (DIMM D1, D2)
```

ECC работает на уровне канала: данные + контрольная сумма записываются в один DIMM ( или распределяются по DIMM в зависимости от режима).

### Архитектура EDAC в Linux

```
Аппаратура (DRAM + ECC controller)
    ↓
MSRs (MCi_STATUS, MCi_ADDR)
    ↓
Ядро (edac_mc, edac_mce AMD64/Intel)
    ↓
/sys/devices/system/edac/mc/mc0/
    ↓
edac-util → пользователь
```

### Ключевые счётчики EDAC

| Счётчик | Описание | Критичность |
| :--- | :--- | :--- |
| `ce_count` | Общее количество Correctable Errors | Средняя (рост = проблема) |
| `ue_count` | Общее количество Uncorrectable Errors | **Критическая** (немедленная замена) |
| `ue_pending` | Ожидающие обработки UE | **Критическая** |
| `ce_row` | Строка с CE (для физической локализации) | Информационный |
| `ce_channel` | Канал с CE | Информационный |

---

## Практические сценарии

### Установка и проверка EDAC

```bash
# Установка edac-utils (Debian/Ubuntu)
sudo apt install edac-utils

# Установка edac-utils (RHEL/Rocky/Alma)
sudo dnf install edac-utils

# Проверка загрузки модуля ядра
lsmod | grep edac
# → edac_core    45056  0
# → edac_mce_amd  16384  0  (для AMD)
# → edac_mce_intel 16384  0  (для Intel)

# Проверка модулей памяти через EDAC
sudo edac-util -v
# → edac-util: ce count on mc0 (ram idx 0): 0
# → edac-util: ue count on mc0 (ram idx 0): 0
# → mc0: 0 CE, 0 UE (норма)

# Детальная информация о контроллерах памяти
sudo edac-util -s
# → mc0: 8192 MB (4096 bits wide, ECC enabled)
# → mc1: 8192 MB (4096 bits wide, ECC enabled)

# Проверка статуса ECC (включен ли ECC)
sudo edac-util -r
```

### Прямой доступ к счётчикам EDAC через sysfs

```bash
# Список контроллеров памяти
ls /sys/devices/system/edac/mc/
# → mc0  mc1

# Просмотр счётчиков для контроллера mc0
cat /sys/devices/system/edac/mc/mc0/ce_count
# → 0  (Correctable Errors)

cat /sys/devices/system/edac/mc/mc0/ue_count
# → 0  (Uncorrectable Errors)

# Информация о каналах и DIMM
cat /sys/devices/system/edac/mc/mc0/dimm0/ce_count
cat /sys/devices/system/edac/mc/mc0/dimm0/ue_count

# Полная сводка по всем контроллерам
for mc in /sys/devices/system/edac/mc/mc*; do
  MC=$(basename $mc)
  CE=$(cat $mc/ce_count 2>/dev/null || echo 0)
  UE=$(cat $mc/ue_count 2>/dev/null || echo 0)
  echo "$MC: CE=$CE UE=$UE"
done
```

### Анализ MCE (Machine Check Exception)

```bash
# Проверка наличия MCE в текущей сессии
dmesg | grep -iE "mce|machine check|mca"
# → [  123.456789] mce: CPU 0: Machine Check Exception: 5 bank 0: ffffffffffffffff
# → [  123.456790] mce: CPU 0: TSC 0 ADDR 0 MISC 0

# Проверка MCE в предыдущей сессии (после перезагрузки)
journalctl -b -1 -g "mce|machine check|mca" | tail -30

# Установка rasdaemon (современная замена mcelog)
sudo apt install rasdaemon    # Debian/Ubuntu
sudo dnf install rasdaemon    # RHEL/Rocky/Alma

# Запуск rasdaemon
sudo systemctl enable --now rasdaemon

# Просмотр MCE через rasdaemon
sudo ras-mc-ctl --summary
# → MCE records: 15
# → Corrected Errors: 12
# → Uncorrected Errors: 3

# Детальные записи MCE
sudo ras-mc-ctl --print-errors

# Фильтрация только UE
sudo ras-mc-ctl --print-errors | grep -A5 "Uncorrected"
```

### Интерпретация MCE-записей

```bash
# Типичная MCE-запись в dmesg:
# → [  123.456789] mce: CPU 0: Machine check exception: ffffffffffffffff
# → [  123.456790] mce: CPU 0: TSC 1234567890 ADDR 0 MISC 0
# → [  123.456791] mce: CPU 0: bank 0: status ffffffffffffffff

# Расшифровка bank 0 (память):
# → bank 0 = Memory Controller (обычноDIMM)
# → Status bits: CE (Correctable) или UE (Uncorrectable)
# → ADDR = физический адрес ошибки

# Определение модуля RAM по физическому адресу
# (используя mcelog, если установлен)
sudo mcelog --client
# → Hardware Error: CPU 0, bank 0: ... addr 0x12345678

# Или через pstore (после reboot)
sudo cat /sys/fs/pstore/dmesg-ramoops-0 | grep -A5 "mce"
```

### Локализация физического модуля RAM

```bash
# 1. Определение канала и DIMM из MCE/EDAC
# В dmesg找到:
# → EDAC mc0: 1 CE error on DIMM A1 (label "DIMM_A1", slot 0, row 1)

# 2. Физический слот через dmidecode
sudo dmidecode -t memory | grep -A3 "Memory Device" | grep -E "Locator:|Size:|Type:|Speed:"
# → Locator: DIMM_A1
# → Size: 16384 MB
# → Type: DDR4
# → Speed: 3200 MT/s

# 3. Корреляция с IPMI (для серверов с BMC)
sudo ipmitool sdr type memory
# → DIMM_A1 | OK | 16384 MB | Slot 0
# → DIMM_A2 | OK | 16384 MB | Slot 1

# 4. Замена модуля
# После замены: проверка через edac-util -v
# Если UE исчезла — модуль заменён успешно
```

### Проверка ECC через EDAC для AMD

```bash
# AMD EDAC (mcx module)
cat /sys/devices/system/edac/mc/mc0/ue_count
cat /sys/devices/system/edac/mc/mc0/ce_count

# Детали по ячейкам памяти
cat /sys/devices/system/edac/mc/mc0/dimm0/ue_count
cat /sys/devices/system/edac/mc/mc0/dimm0/ce_count

# Проверка ue-nr (номер UE)
cat /sys/devices/system/edac/mc/mc0/ue_nr
```

### Автоматизация мониторинга

```bash
# Скрипт для ежедневной проверки ECC
#!/bin/bash
LOG="/var/log/ecc_check.log"
DATE=$(date +%Y-%m-%d)
CE=$(edac-util -v 2>/dev/null | grep -oP 'ce count on mc0: \K\d+' || echo "N/A")
UE=$(edac-util -v 2>/dev/null | grep -oP 'ue count on mc0: \K\d+' || echo "N/A")

echo "$DATE CE=$CE UE=$UE" >> "$LOG"

if [ "$UE" != "0" ] && [ "$UE" != "N/A" ]; then
  echo "CRITICAL: Uncorrectable Error detected on $DATE" | mail -s "ECC Alert" admin@example.com
fi
```

**Cron для регулярной проверки:**
```cron
0 3 * * * root /usr/local/bin/ecc_check.sh
```

### Интеграция с Prometheus

```bash
# textfile collector для node_exporter
cat > /etc/node_exporter/textfile_collector/ecc.prom <<EOF
# HELP node_edac_ce_total Количество Correctable Errors по контроллерам
# TYPE node_edac_ce_total gauge
$(for mc in /sys/devices/system/edac/mc/mc*; do
  MC=$(basename $mc)
  CE=$(cat $mc/ce_count 2>/dev/null || echo 0)
  echo "node_edac_ce_total{mc=\"$MC\"} $CE"
done)

# HELP node_edac_ue_total Количество Uncorrectable Errors
# TYPE node_edac_ue_total gauge
$(for mc in /sys/devices/system/edac/mc/mc*; do
  MC=$(basename $mc)
  UE=$(cat $mc/ue_count 2>/dev/null || echo 0)
  echo "node_edac_ue_total{mc=\"$MC\"} $UE"
done)
EOF
```

**Алертинг:**
```yaml
groups:
  - name: memory_ecc
    rules:
      - alert: MemoryCorrectableErrorsHigh
        expr: rate(node_edac_ce_total[1h]) > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень CE на {{ $labels.mc }}: {{ $value }}/час"

      - alert: MemoryUncorrectableError
        expr: node_edac_ue_total > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "UE обнаружен на {{ $labels.mc }}! Требуется замена DIMM"
```

---

## Дополнительная информация

### ECC vs Non-ECC

| Характеристика | Non-ECC (UDIMM) | ECC (RDIMM/LRDIMM) |
| :--- | :--- | :--- |
| **Обнаружение ошибок** | Нет | Да (однобитовые CE, двухбитовые UE) |
| **Исправление ошибок** | Нет | Да (CE исправляются аппаратно) |
| **Пропускная способность** | Выше (~5-10%) | Немного ниже (из-за ECC overhead) |
| **Стоимость** | Дешевле | Дороже (~20-30%) |
| **Применение** | Рабочие станции, gaming | Серверы, mission-critical |

**Правило для SRE:** Все production-серверы должны использовать ECC RAM.

### Критерии замены DIMM

| Состояние | Действие |
| :--- | :--- |
| **UE > 0** | Немедленная замена модуля |
| **CE > 10/час на один DIMM** | Плановая замена в течение 7 дней |
| **CE растут экспоненциально** | Немедленная замена |
| **CE стабильны, <1/день** | Мониторинг, замена при росте |

### Известные ограничения

- **Виртуализация:** В VM EDAC может не работать или показывать виртуальные контроллеры.
- **ARM64:** EDAC поддерживается не всеми платформами.
- **DIMM without ECC:** Если включить non-ECC DIMM в слот с ECC-контроллером, ECC отключается полностью.

### Связанные темы

- **[IPMI: SEL](./ipmi_bmc.md)** — аппаратный журнал часто содержит MCE-записи.
- **[Анализ перезагрузок](../Troubleshooting/reboot_troubleshooting.md)** — MCE/EDAC в контексте post-mortem.
- **[CPU: диагностика](./cpu_info.md)** — microcode, уязвимости.
- **[Инвентаризация: память](./hardware_listing.md)** — dmidecode -t memory, слоты, ECC.
- **[Kernel Panic](../../Core/kernel/kernel_panic.md)** — tainted kernel из-за MCE.
