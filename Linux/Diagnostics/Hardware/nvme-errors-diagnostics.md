# Диагностика ошибок NVMe: Kernel AER и Controller Reset

## Определения

**Advanced Error Reporting (AER)** — расширенный механизм отчетности об ошибках PCIe, определяемый в спецификации PCI Express Base Specification, позволяющий устройствам и портам (Root Port, Switch Downstream Port) сообщать ядру о проблемах на физическом (Physical), канальном (Data Link) или транзакционном (Transaction/Completion) уровнях шины. AER является обязательным компонентом для PCIe Gen2 и выше, а в современных системах (2025–2026 гг.) критичен для отладки целостности сигналов PCIe Gen5/Gen6 при скоростях 32–64 GT/s.

**NVMe Controller Reset** — механизм восстановления контроллера NVMe, при котором драйвер ядра (`nvme-pci`) инициирует сброс устройства через запись в регистр `CC` (Controller Configuration) с последующей проверкой готовности через регистр `CSTS` (Controller Status). Это происходит при таймаутах операций ввода-вывода (I/O timeout), критических сбоях связи, фатальных ошибках AER или переходе контроллера в состояние `CFS` (Controller Fatal Status).

**Secondary Bus Reset (SBR)** — аппаратный сброс PCIe-сегмента, инициируемый через регистр `BRIDGE_CONTROL` у родительского моста (Root Port или Switch Downstream Port). Используется как крайняя мера, когда программный `nvme reset` не восстанавливает устройство, но затрагивает все устройства на том же PCIe-сегменте.

**APST (Autonomous Power State Transitions)** — механизм управления энергопотреблением NVMe (NVMe PCIe Features, Feature Identifier 0x0C), позволяющий контроллеру автономно переходить в состояния сна (PS1–PS4) при простое. При выходе из глубокого сна (PS4 с задержкой >100 мс) контроллер может не успеть ответить на команду, что ядро интерпретирует как `I/O timeout`.

**ASPM (Active State Power Management)** — механизм энергосбережения PCIe, управляемый ядром через регистры `LNKCTL` у устройства. Режимы `L0s` (простой, на стороне приемника/передатчика) и `L1` (глубокий сон) снижают потребление, но добавляют задержку при выходе. На NVMe Gen5 нестабильная реализация ASPM — частая причина `Surprise Down Error`.

**NVMe Persistent Event Log** — циклический журнал событий NVMe 1.4+, накапливающий записи о критических событиях (SMART-пороговые значения, форматирование, firmware-события, ошибки формата). В отличие от Error Log (хранит последние ошибки), Persistent Event Log сохраняет историю с момента очистки.

**Fault Injection (Инъекция ошибок)** — механизм ядра Linux (`CONFIG_FAULT_INJECTION_DEBUG_FS`), позволяющий искусственно генерировать ошибки ввода-вывода для тестирования реакции приложения и сценариев восстановления (retry, failover, alerts) без физического повреждения оборудования.

---

## Базовые концепции

### Иерархия ошибок и симптомы
Проблемы с NVMe-накопителем могут проявляться как:
*   Периодическое исчезновение устройства из системы (`Device not ready`).
*   Ошибки ввода-вывода (`I/O error`) при записи/чтении.
*   Внезапная деградация производительности или «замирание» системы (latency spikes).

**Важно:** SMART-статус (`smartctl`) при этом может оставаться в состоянии `PASSED`, так как проблема часто локализована не в ячейках памяти, а в физическом тракте PCIe, питании или логике прошивки (firmware).

### Роль AER в диагностике
AER позволяет отличить внутренний сбой SSD от проблем транспортного уровня:
*   **Corrected Error (Исправленная ошибка):** Ошибка исправлена механизмами PCIe (например, переповтором). Регулярное появление указывает на нестабильность (плохой контакт, наводки, перегрев).
*   **Uncorrected Error (Неисправленная ошибка):**
    *   *Non-Fatal:* Система может продолжать работу, но транзакция потеряна.
    *   *Fatal (Фатальная):* Приводит к разрыву PCIe-линка и требует сброса контроллера.

### Контроллер и энергопотребление
Многие «спонтанные» сбросы NVMe вызваны механизмами **APST (Autonomous Power State Transitions)** и **ASPM**. При выходе из глубокого сна контроллер может не ответить вовремя, что ядро интерпретирует как сбой.

### Архитектура AER в PCIe

AER реализуется через расширенный набор регистров, доступных в заголовке PCIe Extended Capability (Capability ID 0x0001):

- **CAP (Capabilities Register):** Определяет поддерживаемые функции AER.
- **CTRL (Control Register):** Включает/отключает отчетность для Corrected, Uncorrected и Fatal ошибок.
- **STS (Status Register):** Накапливает корректные и некорректные ошибки.
- **ERR_CAP_ID/ERR_UNCAP_ID:** Идентификаторы ошибок Root Complex.

**Уровни ошибок:**
- **Correctable:** Исправляются на лету (например, через Link Retraining). Пример: `Receiver Error` (RxErr) на физическом уровне. Частое появление указывает на деградацию сигнала (плохой кабель, загрязнение контакта, EMI).
- **Non-Fatal Uncorrectable:** Транзакция прерывается, но система продолжает работу. Пример: `Poisoned TLP` — пакет с ошибкой ECC доставлен, но система может его отбросить.
- **Fatal Uncorrectable:** Приводит к разрыву линка. Пример: `Surprise Down Error` (SDES) — неожиданное отключение питания устройства, `Completer Abort`.

**Восстановление на уровне шины:** При Fatal ошибке Root Port инициирует Link Active Reporting через `LNKSTS` (Link Status) и может выполнить Secondary Bus Reset (SBR) для переинициализации устройства.

### NVMe: изоляция ошибок и неймспейсы

NVMe 1.0+ поддерживает **Namespace (NS)** — абстракцию, позволяющую один физический контроллер представлять несколько логических устройств (`/dev/nvme0n1`, `nvme0n2`). Важно понимать изоляцию ошибок:

- **Controller-wide ошибки:** AER, CSTS=0x1 (Fatal Status), таймауты `nvme nvme0: I/O timeout` — затрагивают все неймспейсы контроллера.
- **Namespace-specific ошибки:** `I/O error` на конкретном `/dev/nvme0n1` с сохранением доступности `/dev/nvme0n2` — указывает на деградацию LBA-области (сбой перечисления блоков, bad block), а не на транспортный уровень.
- **SMART статус:** `PASSED` не исключает транспортные ошибки (AER). При нестабильности всегда проверяйте `dmesg` и `nvme error-log`, даже если SMART зеленый.

### APST и ASPM: состояния энергосбережения

**APST (NVMe Feature 0x0C):** Контроллер может автономно переходить в состояния PS1–PS4:
| Состояние | Примерная задержка выхода | Назначение |
|-----------|---------------------------|------------|
| PS0       | 0 мс                      | Активная работа |
| PS1       | 10–100 мкс                | Легкий сон (тактирование снижено) |
| PS2       | 1–10 мс                   | Глубокий сон (кэш выключен) |
| PS3       | 10–100 мс                 | Сон с сохранением контекста |
| PS4       | >100 мс                   | Максимальный сон (потеря контекста) |

Нестабильность часто возникает при переходе из PS3/PS4, если `nvme_core.default_ps_max_latency_us` ниже реального времени выхода контроллера.

**ASPM (PCIe L1 Substates):**
- **L1.0:** Классический глубокий сон, настраивается через `pcie_aspm` в sysfs.
- **L1.1/L1.2:** Улучшенные состояния с еще более низким потреблением, но с чувствительностью к задержкам. На Gen5/Gen6 не все контроллеры корректно их поддерживают.

### Структура NVMe Error Log и коды статусов

`nvme error-log` возвращает массив записей (по умолчанию последние 64). Каждая запись содержит:
- **Error Count:** Накопленное количество ошибок.
- **SQ/CQ ID:** Идентификатор очереди Submission/Completion, где произошла ошибка.
- **Phase Tag:** Состояние записи в очереди.
- **Status Field:** Код статуса NVMe (SC) + Status Type (SCT) + Status Code Type.

**Ключевые SC (Status Code) для диагностики:**
- `0x0000` — Successful Completion
- `0x0002` — Invalid Command Opcode
- `0x0007` — Write Fault
- `0x000D` — Abort Queued
- `0x280` — Unrecovered Read Error (аналог UNC сектора)
- `0x301` — Abort Command Limit Exceeded
- `0x302` — Abort Command Limit Exceeded (Fused Command)

### Регистры CSTS и CC: управление сбросом

Понимание битовых полей критично для ручного восстановления:

**CSTS (Controller Status, offset 0x1C):**
- `RDY` (bit 0): Готовность контроллера (0 = не готов, 1 = готов).
- `CFS` (bit 1): Controller Fatal Status (1 = критический сбой, требует сброса).
- `NSSRO` (bit 4): NVM Subsystem Reset Occurred.
- `SHST` (bits 2–3): Shutdown Status (00=Normal, 01=Shutdown Processing, 10=Shutdown Complete).

**CC (Controller Configuration, offset 0x14):**
- `EN` (bit 0): Enable (1 = включить контроллер).
- `CSS` (bits 4–5): Command Set Selected (0 = NVM, 1 = ZNS).
- `FRES` (bit 12): Firmware Reset (опционально в спецификации).

**Алгоритм программного сброса (nvme reset):**
1. Записать `CC.EN = 0` (отключение контроллера).
2. Ожидать `CSTS.RDY = 0` (таймаут ~5 сек).
3. Очистить очереди (`nvme_clear_queue`).
4. Записать `CC.EN = 1` (включение).
5. Ожидать `CSTS.RDY = 1` (таймаут ~1 сек).

---

## Практические сценарии

### Шаг 1: Глубокий анализ системного журнала (dmesg)

Ищите специфические паттерны, указывающие на уровень сбоя:

```bash
dmesg -T | grep -Ei 'nvme|aer|pcie'
```

**Критические сообщения 2026+:**
*   `AER: Corrected: Receiver Error (RxErr)` — проблемы физического уровня (кабель, слот).
*   `Uncorrected (Fatal): Surprise Down Error (SDES)` — мгновенная потеря линка (часто проблема питания).
*   `nvme nvme0: Controller Fatal Status (CSTS=0x1)` — внутренний краш контроллера.
*   `nvme nvme0: I/O 42 QID 7 timeout, aborting` — накопитель перестал отвечать на команды.

### Шаг 2: Использование nvme-cli для извлечения журналов

Стандартных средств `smartctl` часто недостаточно. Используйте `nvme-cli` (v2.x+) для доступа к внутренним логам:

```bash
# Просмотр стандартного лога ошибок (Error Log)
sudo nvme error-log /dev/nvme0

# Извлечение Persistent Event Log (NVMe 1.4+, критично для анализа после сбоя)
sudo nvme persistent-event-log /dev/nvme0 --output-format=json

# Сбор телеметрии для отправки вендору (Host-Initiated Telemetry)
sudo nvme telemetry-log /dev/nvme0 --output-file=nvme_telemetry.bin
```

### Шаг 3: Проверка физического состояния PCIe

```bash
sudo lspci -vv -s <PCI_ADDRESS>
```

**На что смотреть:**
*   **LnkSta (Link Status):** Если диск Gen5 работает на скорости Gen3 (`Speed 8GT/s` вместо `32GT/s`) — линк нестабилен и сброшен ядром на более низкую скорость.
*   **Status: InBandBeacon+:** Может указывать на проблемы с инициализацией шины.
*   **CEnt (Correctable Error Detected):** Счетчик в `DevSta`, подтверждающий проблемы AER.

### Шаг 4: Глубокое восстановление (Secondary Bus Reset)

Если обычный `nvme reset` не помогает и устройство «зависло» в состоянии `CSTS=0x1`, можно принудительно сбросить PCIe-мост:

```bash
# Определите ID родительского бриджа (Bridge) через lspci -t
# Внимание: это может затронуть другие устройства на том же свитче!
sudo setpci -s <bridge_id> BRIDGE_CONTROL=0x40
sleep 1
sudo setpci -s <bridge_id> BRIDGE_CONTROL=0x00
```

### Шаг 5: Симуляция сбоев (Fault Injection)

Для проверки реакции приложения на сбросы NVMe можно использовать Kernel Fault Injection:

```bash
# Включение инъекции ошибок для конкретного устройства (требует CONFIG_FAULT_INJECTION_DEBUG_FS)
echo 1 > /sys/kernel/debug/nvme0n1/fault_inject/times
echo 100 > /sys/kernel/debug/nvme0n1/fault_inject/probability
# После этого операции I/O начнут искусственно завершаться с ошибкой
```

### Шаг 6: Автоматизированный сбор логов (Fleet Script)

Для парка из 100+ серверов ручной анализ `dmesg` неэффективен. Используйте следующий Bash-скрипт для сбора артефактов в единый архив:

```bash
#!/usr/bin/env bash
set -euo pipefail

NVME_DEV="/dev/nvme0"
OUT_DIR="/var/log/nvme-diag-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR"

# 1. dmesg с фильтром NVMe/AER
dmesg -T | grep -Ei 'nvme|aer|pcie' > "$OUT_DIR/dmesg-nvme.log"

# 2. nvme error-log в JSON
sudo nvme error-log "$NVME_DEV" --output-format=json > "$OUT_DIR/error-log.json"

# 3. Persistent Event Log (требует NVMe 1.4+)
sudo nvme persistent-event-log "$NVME_DEV" --output-format=json > "$OUT_DIR/persistent-event-log.json" 2>/dev/null || echo "Persistent Event Log не поддерживается" > "$OUT_DIR/persistent-event-log.json"

# 4. smartctl (для корреляции)
sudo smartctl -a "$NVME_DEV" --json > "$OUT_DIR/smartctl.json"

# 5. lspci verbose
sudo lspci -vvv -s "$(readlink -f /sys/block/nvme0n1/device | xargs basename)" > "$OUT_DIR/lspci.txt"

# 6. Текущий статус контроллера
sudo nvme id-ctrl -H "$NVME_DEV" > "$OUT_DIR/id-ctrl.txt"
sudo nvme smart-log "$NVME_DEV" > "$OUT_DIR/smart-log.txt"

# Архивация
tar czf "${OUT_DIR}.tar.gz" -C "$(dirname "$OUT_DIR")" "$(basename "$OUT_DIR")"
echo "Артефакты собраны в ${OUT_DIR}.tar.gz"
```

**Интеграция с systemd-timer:** Создайте `nvme-diag-collector.service` и `.timer` для автоматического сбора при обнаружении `nvme nvme0: I/O timeout`.

### Шаг 7: Парсинг Error Log через JSON и jq

`nvme error-log --output-format=json` возвращает массив записей. Пример анализа с `jq`:

```bash
# Фильтрация только ошибок за последний час (предполагаем время в полях)
sudo nvme error-log /dev/nvme0 --output-format=json | jq -r '
  .errors[]
  | select(.timestamp > (now - 3600))
  | "\(.timestamp) | SQ=\(.sqid) CQ=\(.cqid) | SC=0x\(.status.sc | tostring) SCT=0x\(.status.sct | tostring)"
'

# Топ-5 кодов ошибок за последний час
sudo nvme error-log /dev/nvme0 --output-format=json | jq -r '
  .errors[]
  | "0x\(.status.sc)"
' | sort | uniq -c | sort -rn | head -5
```

**Корреляция с AER:** Сопоставьте время появления ошибок в `nvme error-log` с записями `dmesg -T | grep AER`. Если `nvme error-log` показывает `SC=0x280` (Unrecovered Read Error), а в `dmesg` нет AER Fatal — проблема в ячейках памяти (планируйте замену). Если `nvme error-log` пуст, а в `dmesg` есть `AER: Fatal: Surprise Down` — проблема на уровне PCIe (питание, слот).

### Шаг 8: Дерево решений для восстановления (Recovery Runbook)

SRE должен действовать по алгоритму, минимизируя downtime:

```text
Обнаружен timeout / устройство missing
        │
        ▼
   Шаг 1: dmesg -T | grep -Ei 'nvme|aer|pcie'
        │
        ├── Нет записей AER
        │       └── Проверить `nvme error-log` → SC=0x280 (Unrecovered Read)
        │               └── Действие: Резервное копирование данных, планирование замены
        │
        └── Есть AER: Corrected (RxErr, BDErr)
                └── Частота >10/мин
                        └── Действие: Проверить кабель/слот, перенос на другой PCIe линк
                            Если persists → firmware update + мониторинг 24ч

Обнаружен AER: Fatal (SDES, Unsupported Request)
        │
        ▼
   Шаг 2: Попытка программного сброса
        │
        ├── Успех (CSTS.RDY=1, устройство появилось)
        │       └── Действие: Собрать логи, запланировать замену в maintenance window
        │
        └── Неуспех (CSTS=0x1, устройство missing)
                │
                ▼
           Шаг 3: Secondary Bus Reset (SBR)
                │
                ├── Устройство восстановилось
                │       └── Действие: Откатить ASPM/APST настройки, собрать логи
                │
                └── Устройство не появилось
                        └── Действие: Аварийное отключение сервера, физическая проверка
                            (перегрев, просадки напряжения, неисправный слот)
```

### Шаг 9: Мониторинг и алертинг в Prometheus

Для интеграции с Prometheus используйте `node_exporter` + кастомные скрипты:

```bash
# textfile collector для node_exporter
cat > /etc/node_exporter/textfile_collector/nvme-aer-status.prom <<EOF
# HELP nvme_aer_corrected_total Количество исправленных AER ошибок
# TYPE nvme_aer_corrected_total gauge
nvme_aer_corrected_total{device="nvme0"} $(dmesg -T | grep -c "AER: Corrected" || echo 0)

# HELP nvme_controller_ready Состояние готовности контроллера (1=готов)
# TYPE nvme_controller_ready gauge
nvme_controller_ready{device="nvme0"} $(cat /sys/block/nvme0n1/device/device/online 2>/dev/null || echo 0)
EOF
```

**Алертинг в Alertmanager:**
```yaml
# Правило: частота AER Corrected > 5/час
- alert: NvmeAerCorrectedHigh
  expr: rate(nvme_aer_corrected_total[1h]) > 5
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Высокая частота исправленных AER ошибок на {{ $labels.device }}"
    description: "Проверьте кабель и слот PCIe"

# Правило: контроллер не готов > 30 сек
- alert: NvmeControllerNotReady
  expr: nvme_controller_ready == 0
  for: 30s
  labels:
    severity: critical
  annotations:
    summary: "NVMe контроллер {{ $labels.device }} не готов"
    description: "Требуется немедленная проверка: dmesg | tail -n 50"
```

### Шаг 10: Обновление прошивки (Firmware Update Procedure)

Прошивка — частая первопричина спонтанных сбросов (особенно на ранних ревизиях NVMe Gen5). Процедура обновления:

```bash
# 1. Проверка текущей версии прошивки
sudo nvme id-ctrl /dev/nvme0 | grep -i fr

# 2. Скачивание прошивки от вендора (Samsung, Solidigm, WD)
#    Проверьте контрольную сумму: sha256sum firmware.bin

# 3. Загрузка прошивки (без немедленной перезагрузки)
sudo nvme fw-download /dev/nvme0 --fw=firmware.bin

# 4. Активация прошивки на следующей перезагрузке
sudo nvme fw-activate /dev/nvme0 --slot=1

# 5. Перезагрузка сервера
sudo reboot

# 6. Валидация
sudo nvme id-ctrl /dev/nvme0 | grep -i fr
```

**Важно:** На production-серверах используйте отложенную активацию (`fw-activate` без немедленного сброса) и обновляйте прошивку в maintenance window. Для вендорных утилит (Solidigm SST, Samsung Magician DC) предпочитайте их CLI, если доступен, так как они проверяют совместимость прошивки и модели диска.

---

## Дополнительная информация

### Настройка параметров ядра для стабильности

Если накопитель работает нестабильно в режимах простоя, попробуйте отключить агрессивное энергосбережение в `/etc/default/grub`:

1.  **Отключение APST:** `nvme_core.default_ps_max_latency_us=0`
2.  **Отключение ASPM:** `pcie_aspm=off`
3.  **Лимит скорости PCIe:** `pcie_bus_config=safe` (или принудительно Gen3/Gen4 через BIOS).

После изменения параметров выполните `sudo update-grub && sudo reboot`.

**Валидация изменений:**
```bash
# Проверка текущего значения APST
cat /sys/module/nvme_core/parameters/default_ps_max_latency_us
# → 0 (отключено) или >0 (включено)

# Проверка текущего состояния ASPM
cat /sys/module/pcie_aspm/parameters/policy
# → [powersave] performance (рекомендуется powersave для серверов, но проверяйте стабильность)
```

### Валидация прошивки и контроллера

После любого сброса или обновления выполните проверку:

```bash
# Статус контроллера
sudo nvme get-feature /dev/nvme0 -f 0x0c  # APST
sudo nvme id-ctrl -H /dev/nvme0 | grep -E "Model|Firmware|nvme_ver"

# SMART-здоровье (для исключения деградации ячеек)
sudo smartctl -H /dev/nvme0

# Проверка очередей и Completer Abort
sudo nvme show-regs /dev/nvme0 2>/dev/null || echo "show-regs недоступно в этой версии nvme-cli"
```

### Типичные ошибки и решения

| Симптом | Возможная причина | Действие |
|---------|-------------------|----------|
| `I/O timeout` после простоя | APST выходит из PS3/PS4 дольше `default_ps_max_latency_us` | Отключить APST или увеличить задержку |
| `AER: Fatal: Surprise Down` | Просадка напряжения 3.3V (Gen5 требует до 3A) | Проверить блок питания, кабель питания M.2 |
| `AER: Corrected: Receiver Error` | Плохой контакт в слоте, EMI, износ кабеля (если U.2) | Переустановить диск, заменить на другой слот |
| `LnkSta: Speed 8GT/s` вместо `32GT/s` | Линк упал до Gen3 | Проверить BIOS (PCIe Speed), слот, backward compatibility |
| `CSTS=0x1` после reset | Фатальный сбой контроллера (не восстановился) | Secondary Bus Reset → физическая замена |
| `nvme error-log` пуст, но `dmesg` показывает AER | Проблема на транспортном уровне (не затрагивает NVMe команды) | Проверить питание, слот, охлаждение |

### Чек-лист проверки аппаратной цепочки

1.  **Питание:** Современные NVMe Gen5 требуют до 3A на линию 3.3V. Просадки напряжения — частая причина `Surprise Down`.
2.  **Firmware:** Обновление прошивки обязательно (используйте `nvme fw-download` или вендорские утилиты типа Solidigm SST).
3.  **Охлаждение:** Троттлинг при >75°C может приводить к таймаутам контроллера.
4.  **Слот:** На двухпроцессорных системах убедитесь, что диск подключен к CPU, ближайшему к приложению (NUMA-узел), иначе latency может превышать 100 мкс.

### Смотрите также

*   [**Основы дисковых подсистем: NVMe и нумерация**](../../FileSystems/disk_storage_fundamentals.md) — детали именования и `Percentage Used`.
*   [**Диагностика через dmesg**](../Kernel/dmesg/troubleshooting.md) — общие принципы анализа логов ядра.
*   [**SSD и NVMe: Burst I/O и производительность**](../../Core/kernel/ssd_burst_io.md) — вопросы быстродействия и ASPM/APSM троттлинга.
