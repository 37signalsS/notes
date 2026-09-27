# Обновление прошивок: fwupd, vendor tools, BIOS/UEFI

## Определения

**`fwupd` (Firmware Update Daemon)** — открытый демон для централизованного обновления прошивки устройств в Linux. Использует хранилище прошивок `LVFS` (Linux Vendor Firmware Service), предоставленное производителями оборудования. Поддерживает обновление BIOS/UEFI, NIC, NVMe SSD, Thunderbolt-контроллеров и других устройств.

**`fwupdmgr`** — основная утилита командной строки для взаимодействия с `fwupd`. Позволяет проверять наличие обновлений, загружать и применять прошивки.

**`efibootmgr`** — утилита для управления записями загрузки UEFI. Позволяет изменять порядок загрузки, добавлять/удалять EFI-записи, управлять Secure Boot.

**BIOS/UEFI Firmware** — микропрограмма материнской платы, отвечающая за POST, инициализацию оборудования и передачу управления загрузчику. Обновление BIOS исправляет аппаратные баги, уязвимости (Spectre/Meltdown) и добавляет поддержку новых процессоров.

**BMC Firmware** — прошивка базового контроллера управления (BMC/iDRAC/iLO). Обновление BMC исправляет segurança и стабильность удалённого доступа.

**Microcode** — обновляемый набор инструкций процессора, загружаемый ядром при загрузке. Исправляет аппаратные ошибки CPU без замены чипа.

---

## Базовые концепции

### Иерархия прошивок в сервере

```
┌─────────────────────────────────────────┐
│  Microcode CPU (загружается ядром)      │  ← Часто
├─────────────────────────────────────────┤
│  BIOS/UEFI (прошивка материнской платы) │  ← Редко
├─────────────────────────────────────────┤
│  BMC Firmware (iDRAC/iLO/IPMI)         │  ← Редко
├─────────────────────────────────────────┤
│  NIC Firmware (Intel, Mellanox)         │  ← Средне
├─────────────────────────────────────────┤
│  NVMe Firmware (Samsung, WD, Intel)     │  ← Средне
├─────────────────────────────────────────┤
│  Storage Controller (RAID, HBA)         │  ← Редко
└─────────────────────────────────────────┘
```

### fwupd архитектура

```
LVFS (Linux Vendor Firmware Service)
    ↓ fwupdmgr download
Кэш прошивок (/var/lib/fwupd/)
    ↓ fwupdmgr install
fwupd daemon
    ↓ UEFI capsule / vendor mechanism
Аппаратное устройство
```

### Типы обновлений

| Тип | Механизм | Перезагрузка | Риск |
| :--- | :--- | :--- | :--- |
| **Microcode** | Ядро загружает при старте | Нет | Низкий |
| **UEFI Capsule** | fwupd + UEFI runtime | **Да** | Средний |
| **BMC/IPMI** | racadm / Redfish | **Да** | Средний |
| **NIC** | ethtool / vendor CLI | Нет (hot-reset) | Низкий |
| **NVMe** | nvme-cli | **Да** (отложенная активация) | Средний |

---

## Практические сценарии

### fwupd: установка и базовые операции

```bash
# Установка (Debian/Ubuntu)
sudo apt install fwupd

# Установка (RHEL/Rocky/Alma)
sudo dnf install fwupd

# Проверка наличия обновлений
sudo fwupdmgr get-updates
# → Dell XPS 13 9310
#   │  │
#   ├─System Firmware│ 1.5.0 → 1.8.0│ Улучшения стабильности│
#   └─Thunderbolt Controller│ 40.2 → 42.1│ Безопасность│

# Просмотр всех обнаруженных устройств
sudo fwupdmgr get-devices

# Загрузка и установка обновлений
sudo fwupdmgr update
# → Downloading... │ [=========================]
# → Installing System Firmware...
# → Reboot to complete installation

# Просмотр истории обновлений
sudo fwupdmgr get-history
# → Dell XPS 13 9310
#   │  │
#   └─System Firmware│ 1.5.0│ Successful│ 2026-01-15

# Проверка совместимости (dry-run)
sudo fwupdmgr update --dry-run
```

### fwupd: NVMe firmware

```bash
# fwupd поддерживает обновление NVMe через LVFS
sudo fwupdmgr get-updates | grep -i nvme
# → NVMe SSD: Samsung 980 PRO
#   │  │
#   └─NVMe Firmware│ 3B2QGXA7 → 5B2QGXA7│ Performance│

# Обновление NVMe через fwupd
sudo fwupdmgr update --filter=NVMe
# → Reboot to activate new firmware

# Или через nvme-cli напрямую
sudo nvme fw-download /dev/nvme0 --fw=firmware.bin
sudo nvme fw-activate /dev/nvme0 --slot=1
# → На следующей перезагрузке
```

### Обновление Microcode

```bash
# Проверка текущей версии микрокода
grep -m1 "microcode" /proc/cpuinfo
# → microcode: 0x96000b13

# Установка обновлений микрокода (Debian/Ubuntu)
sudo apt install intel-microcode   # Intel
sudo apt install amd64-microcode   # AMD

# Установка (RHEL/Rocky/Alma)
sudo dnf install microcode_ctl     # Intel
sudo dnf install amd-ucode         # AMD

# Применение (требует перезагрузки)
sudo reboot

# Проверка после перезагрузки
grep -m1 "microcode" /proc/cpuinfo
dmesg | grep -i microcode
# → [    0.000000] microcode: microcode updated early to revision 0x96000b13
```

### Vendor-специфичные инструменты

#### Dell (racadm / Dell Command Update)

```bash
# Установка Dell Command Update (DCU)
sudo apt install dell-command-update

# Проверка обновлений
sudo dell-command-update

# Обновление BIOS
sudo dell-command-update --bios

# Обновление всех компонентов
sudo dell-command-update --update

# Через racadm (iDRAC)
sudo racadm update -f <firmware.exe>
sudo racadm getversion BIOS
```

#### HPE (SSAcli / Smart Update Manager)

```bash
# Проверка версий прошивки
sudo ssacli ctrl all show config detail | grep -i firmware

# HPE SUM (Smart Update Manager) — web-based
# Доступен через iLO: https://ilo.example.com/html/login.html
```

#### Lenovo (OneCLI)

```bash
# Проверка версий
sudo onecli config get BIOS.Setup`

# Обновление через OneCLI
sudo onecli update biolify --text
```

### Обновление BMC/IPMI

```bash
# Через racadm (Dell)
sudo racadm update -f <bmc_firmware.exe>
sudo racadm racreset soft

# Через Redfish API
curl -k -u admin:password \
  -X POST https://bmc.example.com/redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate \
  -H "Content-Type: application/json" \
  -d '{"ImageURI": "http://repo/bmc_firmware.bin", "TransferProtocol": "HTTP"}'

# Проверка текущей версии BMC
sudo ipmitool mc info | grep -i firmware
# → Firmware Revision: 04.40.00
```

### Обновление NIC Firmware

```bash
# Intel NIC (nvmupdate)
sudo nvmupdate64e

# Mellanox/NVIDIA NIC (mlxup)
sudo mlxup

# Проверка текущей версии
ethtool -i eth0 | grep firmware
# → firmware-version: 0x800003cc
```

### Автоматизация: скрипт проверки прошивок

```bash
#!/usr/bin/env bash
# Проверка версий прошивок на сервере

echo "=== Firmware Versions: $(hostname) ==="

# BIOS/UEFI
echo "--- BIOS/UEFI ---"
sudo dmidecode -s bios-version
sudo dmidecode -s bios-release-date

# Microcode
echo "--- Microcode ---"
grep -m1 "microcode" /proc/cpuinfo

# BMC
echo "--- BMC ---"
sudo ipmitool mc info 2>/dev/null | grep -E "Firmware|Manufacturer" || echo "IPMI not available"

# NIC
echo "--- NIC Firmware ---"
for nic in /sys/class/net/eth*; do
  [ -d "$nic" ] || continue
  NAME=$(basename $nic)
  FW=$(ethtool -i $NAME 2>/dev/null | grep firmware | awk '{print $2}')
  DRIVER=$(ethtool -i $NAME 2>/dev/null | grep driver | awk '{print $2}')
  echo "$NAME ($DRIVER): $FW"
done

# NVMe
echo "--- NVMe Firmware ---"
for nvme in /dev/nvme[0-9]; do
  [ -b "$nvme" ] || continue
  FW=$(sudo nvme id-ctrl $nvme 2>/dev/null | grep "^fr " | awk '{print $3}')
  MODEL=$(sudo nvme id-ctrl $nvme 2>/dev/null | grep "^mn " | cut -d: -f2 | xargs)
  echo "$nvme ($MODEL): $FW"
done

# Проверка доступных обновлений fwupd
echo "--- fwupd ---"
sudo fwupdmgr get-updates 2>/dev/null | head -20 || echo "fwupd not available"
```

---

## Дополнительная информация

### Безопасность обновлений

- **Проверяйте контрольные суммы** — всегда верифицируйте скачанные прошивки.
- **Используйте official repos** — не скачивайте прошивки с неизвестных источников.
- **Бэкап текущей прошивки** — перед обновлением сохраните текущую версию.
- **Maintenance window** — обновляйте BIOS/BMC в плановое окно обслуживания.
- **Не прерывайте процесс** — прерванное обновление может «коврик» сервер.

### Порядок обновления

1. **Microcode** — безопасно, без перезагрузки (применяется при старте).
2. **NIC firmware** — обычно безопасно, hot-reset.
3. **NVMe firmware** — требует перезагрузки (отложенная активация).
4. **BIOS/UEFI** — требует перезагрузки, высокий риск.
5. **BMC** — требует перезагрузки BMC (может потерять доступ на несколько минут).

### Откат прошивки

```bash
# fwupd: откат на предыдущую версию
sudo fwupdmgr downgrade

# NVMe: откат через nvme-cli
sudo nvme fw-download /dev/nvme0 --fw=old_firmware.bin
sudo nvme fw-activate /dev/nvme0 --slot=0  # предыдущий слот

# BIOS: откат через efibootmgr или vendor-утилиту
# Обычно.requires boot into recovery BIOS
```

### Связанные темы

- **[BIOS/UEFI и загрузка](../../Core/firmware_bios_uefi.md)** — UEFI architecture, Secure Boot, efibootmgr.
- **[NVMe: ошибки и диагностика](./nvme-errors-diagnostics.md)** — firmware-related resets.
- **[SMART: мониторинг](./smartctl/index.md)** — firmware version tracking.
- **[IPMI/BMC](./ipmi_bmc.md)** — BMC firmware updates через Redfish.
- **[Микрокод CPU](./cpu_info.md)** — microcode updates, уязвимости.
