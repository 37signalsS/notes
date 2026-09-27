# UEFI, Secure Boot и vTPM в KVM

В данном файле описывается настройка UEFI-загрузки ВМ через OVMF, включение Secure Boot с цепочкой доверия, и настройка виртуального TPM (vTPM) для шифрования дисков и аттестации. Диагностика проблем загрузки описана в [Решение проблем (Troubleshooting)](./troubleshooting.md) (сценарий 13).

## Определения

**UEFI (Unified Extensible Firmware Interface)** — стандарт прошивки, заменяющий Legacy BIOS. Обеспечивает GPT-разметку, Secure Boot, быструю загрузку и поддержку дисков >2 TB.

**OVMF (Open Virtual Machine Firmware)** — реализация UEFI для виртуальных машин QEMU/KVM. Предоставляет EFI-прошивку, включая поддержку Secure Boot и NVRAM-переменных.

**Secure Boot** — механизм UEFI, проверяющий цифровую подпись загрузчиков (shim → GRUB → kernel). Предотвращает загрузку неподписанных или скомпрометированных компонентов.

**shim** — EFI-загрузчик, подписанный Microsoft, который является доверенным корнем для Secure Boot. Загружает GRUB, который загружает ядро.

**NVRAM (Non-Volatile RAM)** — хранилище переменных UEFI, включая порядок загрузки, ключи Secure Boot и конфигурацию. В KVM хранится как файл `.vars`.

**vTPM (Virtual TPM)** — виртуальная реализация Trusted Platform Module, эмулирующая аппаратный чип TPM 2.0. Позволяет использовать измерение загрузки (Measured Boot) и шифрование, привязанное к состоянию ВМ.

**TPM 2.0 (Trusted Platform Module)** — аппаратный/программный модуль для хранения ключей шифрования, измерения компонентов загрузки (PCR registers) и аттестации платформы.

**PCR (Platform Configuration Registers)** — регистры TPM, хранящие хэши компонентов загрузки (firmware → bootloader → kernel). Изменение любого компонента меняет PCR.

**BitLocker** — технология шифрования дисков Windows, поддерживающая привязку ключа к TPM (avoids passphrase at boot).

## Базовые концепции

### Архитектура UEFI-загрузки ВМ в KVM

```
┌─────────────────────────────────────────────┐
│              Аппаратный уровень             │
│  QEMU → OVMF_CODE.fd (UEFI прошивка)       │
├─────────────────────────────────────────────┤
│              UEFI-загрузчик                 │
│  OVMF → NVRAM.vars (переменные)             │
│  → shimx64.efi (Secure Boot)                │
│  → grubx64.efi                              │
│  → vmlinuz (ядро Linux)                     │
├─────────────────────────────────────────────┤
│              Гостевая ОС                    │
│  Ядро → initrd → rootfs                     │
└─────────────────────────────────────────────┘
```

### Установка OVMF

```bash
# Debian/Ubuntu
sudo apt install ovmf

# RHEL/Rocky/Fedora
sudo dnf install edk2-ovmf

# Проверка наличия прошивок
ls -la /usr/share/OVMF/
# → OVMF_CODE.fd      ( основная прошивка, read-only)
# → OVMF_VARS.fd      ( шаблон переменных)
# → OVMF_CODE.secboot.fd  ( Secure Boot версия)
# → OVMF_VARS.secboot.fd  ( Secure Boot переменные)
```

### Конфигурация UEFI в XML ВМ

**Базовый UEFI (без Secure Boot):**
```xml
<os>
  <type arch='x86_64' machine='q35'>hvm</type>
  <loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.fd</loader>
  <nvram>/var/lib/libvirt/qemu/nvram/web-server-01_VARS.fd</nvram>
  <boot dev='hd'/>
</os>
```

**UEFI с Secure Boot:**
```xml
<os>
  <type arch='x86_64' machine='q35'>hvm</type>
  <loader readonly='yes' secure='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.secboot.fd</loader>
  <nvram>/var/lib/libvirt/qemu/nvram/web-server-01_VARS.fd</nvram>
  <boot dev='hd'/>
</os>
```

**Создание NVRAM-файла (при первом запуске):**
```bash
# Копирование шаблона переменных
sudo cp /usr/share/OVMF/OVMF_VARS.fd \
  /var/lib/libvirt/qemu/nvram/web-server-01_VARS.fd

# Или для Secure Boot
sudo cp /usr/share/OVMF/OVMF_VARS.secboot.fd \
  /var/lib/libvirt/qemu/nvram/web-server-01_VARS.fd

# Права доступа
sudo chown libvirt-qemu:kvm \
  /var/lib/libvirt/qemu/nvram/web-server-01_VARS.fd
```

### Secure Boot: цепочка доверия

Secure Boot проверяет цифровые подписи на каждом этапе загрузки:

```
UEFI (OVMF)
  └─ Проверяет подпись shimx64.efi (подпись Microsoft)
       └─ shimx64.efi
            └─ Проверяет подпись grubx64.efi (подпись Ubuntu/RHEL)
                 └─ grubx64.efi
                      └─ Проверяет подпись vmlinuz (подпись дистрибутива)
                           └─ vmlinuz
                                └─ Загружается ОС
```

**Включение Secure Boot для Linux-ВМ:**
```bash
# 1. Установка shim и GRUB в ВМ (внутри гостевой ОС)
sudo apt install shim-signed grub-efi-amd64-signed

# 2. Настройка NVRAM для Secure Boot
sudo cp /usr/share/OVMF/OVMF_VARS.secboot.fd \
  /var/lib/libvirt/qemu/nvram/web-server-01_VARS.fd

# 3. XML: secure='yes'
# <loader readonly='yes' secure='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.secboot.fd</loader>

# 4. Проверка Secure Boot внутри гостя
mokutil --sb-state
# → SecureBoot enabled
```

**Включение Secure Boot для Windows 11:**
```bash
# Windows 11 требует TPM 2.0 + Secure Boot + UEFI
# Внутри ВМ Windows 11 автоматически détecte TPM

# Проверка через PowerShell (внутри Windows ВМ):
Get-CimInstance -Namespace root\cimv2\Security\MicrosoftTpm -ClassName Win32_Tpm
```

### Настройка vTPM для ВМ

vTPM позволяет эмулировать TPM 2.0 для шифрования дисков и аттестации.

**Подключение vTPM через libvirt:**

```xml
<domain type='kvm'>
  <devices>
    <!-- vTPM (emulator backend) -->
    <tpm model='tpm-tis'>
      <backend type='emulator'/>
    </tpm>
  </devices>
</domain>
```

**Установка пакета swtpm:**
```bash
# Debian/Ubuntu
sudo apt install swtpm swtpm-tools

# RHEL/Rocky/Fedora
sudo dnf install swtpm swtpm-tools

# Проверка
swtpm --version
```

**Автоматическое создание vTPM при определении ВМ:**
```bash
# libvirt автоматически создаёт persistent storage для vTPM
# в /var/lib/libvirt/qemu/nvram/<domain>_VARS.fd

# Проверка
ls -la /var/lib/libvirt/qemu/nvram/
# → web-server-01_VARS.fd
```

**Проверка vTPM внутри гостевой ОС (Linux):**
```bash
# Установка TPM-тулов
sudo apt install tpm2-tools

# Проверка состояния TPM
sudo tpm2_getcap properties-fixed | grep -A1 "TPM2_PT_FIRMWARE_VERSION"
# → 0x00030001 0x000b0002

# Проверка PCR
sudo tpm2_pcrread sha256
# →  0 : 0x0000000000000000000000000000000000000000000000000000000000000000
# →  1 : 0x3d03c31849264052509866a62371367987836871757449230493642190123456
```

**Проверка vTPM внутри гостевой ОС (Windows 11):**
```powershell
# PowerShell
Get-CimInstance -Namespace root\cimv2\Security\MicrosoftTpm -ClassName Win32_Tpm
# → IsEnabled: True
# → ManufacturerId: 1398033696
# → SpecVersion: 2.0, 0, 1.59
```

### Шифрование дисков через BitLocker + vTPM

Для Windows 11 ВМ с vTPM BitLocker может автоматически расшифровывать диск без пароля.

**Настройка BitLocker на Windows 11 ВМ:**
```powershell
# PowerShell (от администратора)
# 1. Включение BitLocker на системном диске
Enable-BitLocker -MountPoint "C:" -EncryptionMethod XtsAes256 -UsedSpaceOnly -TpmProtector

# 2. Проверка
Get-BitLockerVolume -MountPoint "C:"
# → VolumeStatus: FullyEncrypted
# → EncryptionPercentage: 100
# → KeyProtector: {Tpm}
```

**Настройка LUKS на Linux ВМ с vTPM (auto-unlock):**
```bash
# Внутри Linux ВМ с TPM
# 1. Установка clevis + tpm2
sudo apt install clevis clevis-luks clevis-tpm2

# 2. Запись LUKS-ключа в TPM
sudo clevis luks bind -d /dev/vda1 tpm2 '{"pcr_bank":"sha256","pcr_ids":"0,1,2,3"}'

# 3. Автоматическое расшифрование при загрузке
# clevis автоматически расшифровывает диск, если PCR совпадают
```

### Сравнение Legacy BIOS vs UEFI для ВМ

| Критерий | Legacy BIOS | UEFI |
| :--- | :--- | :--- |
| **Макс. размер диска** | 2 TB (MBR) | 9.4 ZB (GPT) |
| **Secure Boot** | Нет | Да |
| **TPM** | Нет | Да (vTPM) |
| **Быстрая загрузка** | Нет | Да |
| **Multi-boot** | Ограничено | Полная поддержка |
| **Windows 11** | Нет | Обязательно |
| **Производительность загрузки** | Медленнее | Быстрее |
| **Совместимость** | Универсальная | Современные ОС |

## Практические сценарии

### Сценарий 1: Установка Windows 11 в KVM

Windows 11 требует TPM 2.0 + Secure Boot + UEFI.

**1. Подготовка хоста:**
```bash
# Установка OVMF и swtpm
sudo apt install ovmf swtpm swtpm-tools

# Создание директории для NVRAM
sudo mkdir -p /var/lib/libvirt/qemu/nvram
```

**2. Создание ВМ:**
```bash
virt-install \
  --name win11-vm \
  --memory 8192 \
  --vcpus 4 \
  --disk path=/var/lib/libvirt/images/win11.qcow2,size=64,format=qcow2 \
  --os-variant win11 \
  --network network=default,model=virtio \
  --graphics spice \
  --cdrom /path/to/Win11.iso \
  --boot uefi \
  --tpm backend.type=emulator,backend.version=2.0,model=tpm-tis
```

**3. XML-конфигурация (ручная):**
```xml
<domain type='kvm'>
  <name>win11-vm</name>
  <memory unit='GiB'>8</memory>
  <vcpu>4</vcpu>
  <os>
    <type arch='x86_64' machine='q35'>hvm</type>
    <loader readonly='yes' secure='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.secboot.fd</loader>
    <nvram>/var/lib/libvirt/qemu/nvram/win11-vm_VARS.fd</nvram>
    <boot dev='hd'/>
  </os>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='/var/lib/libvirt/images/win11.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <tpm model='tpm-tis'>
      <backend type='emulator'/>
    </tpm>
  </devices>
</domain>
```

**4. Проверка:**
```bash
# Проверка Secure Boot внутри Windows
msinfo32 → Secure Boot State: On

# Проверка TPM
tpm.msc → TPM готов к использованию
```

### Сценарий 2: Linux-ВМ с Secure Boot и LUKS auto-unlock

**1. Создание ВМ:**
```bash
virt-install \
  --name secure-linux \
  --memory 4096 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/secure-linux.qcow2,size=30 \
  --os-variant ubuntu24.04 \
  --network network=default,model=virtio \
  --graphics none \
  --boot uefi \
  --cdrom /path/to/ubuntu-24.04.iso
```

**2. Настройка LUKS + TPM (внутри гостя):**
```bash
# Установка clevis
sudo apt install clevis clevis-luks clevis-tpm2 tpm2-tools

# Шифрование раздела / (если не зашифрован при установке)
# или настройка auto-unlock для существующего LUKS
sudo clevis luks bind -d /dev/vda2 tpm2 \
  '{"pcr_bank":"sha256","pcr_ids":"0,1,2,3"}'

# Проверка
sudo clevis luks list -d /dev/vda2
# → 1: tpm2 ["{"pcr_bank":"sha256","pcr_ids":"0,1,2,3"}"]
```

### Сценарий 3: Миграция ВМ с Legacy BIOS на UEFI

```bash
# 1. Конвертация образа (если нужна GPT-разметка)
sudo apt install guestfs-tools

# Проверка текущей разметки
virt-inspector /var/lib/libvirt/images/old-vm.qcow2 | grep partition

# 2. Конвертация MBR → GPT (если диск < 2TB, можно без конвертации)
sudo virt-resize --expand /dev/sda2 /var/lib/libvirt/images/old-vm.qcow2 \
  /var/lib/libvirt/images/new-vm.qcow2

# 3. Изменение XML: замена <os> секции
# Было:
# <loader type='bios'>/usr/share/seabios/bios-256k.bin</loader>
# Стало:
# <loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.fd</loader>
# <nvram>/var/lib/libvirt/qemu/nvram/new-vm_VARS.fd</nvram>

# 4. Определение ВМ
virsh define /path/to/new-vm.xml
virsh start new-vm
```

### Сценарий 4: Диагностика UEFI/Secure Boot

```bash
# Если ВМ не стартует с UEFI

# 1. Проверка наличия OVMF
ls -la /usr/share/OVMF/
# → Должны быть OVMF_CODE.fd и OVMF_VARS.fd

# 2. Проверка NVRAM-файла ВМ
ls -la /var/lib/libvirt/qemu/nvram/
# → Должен быть <domain>_VARS.fd

# 3. Проверка прав
stat /var/lib/libvirt/qemu/nvram/win11-vm_VARS.fd
# → Owner: libvirt-qemu:kvm

# 4. Проверка XML
virsh dumpxml win11-vm | grep -A5 '<os>'
# → Должен содержать loader и nvram

# 5. Проверка UEFI shell (если загрузка застряла)
# Внутри ВМ: проверить boot order через UEFI shell
# Shell> bcfg boot dump
```

## Дополнительная информация

- [Решение проблем (Troubleshooting)](./troubleshooting.md) — сценарий 13: UEFI/OVMF/Secure Boot/TPM.
- [Установка и настройка KVM](./installation.md) — пакеты OVMF.
- [Безопасность KVM](./kvm_security_hardening.md) — LUKS, шифрование дисков.
- [TPM и Secure Boot](../../Linux/Diagnostics/Hardware/tpm_secureboot.md) — архитектура TPM 2.0, PCR, Attestation.
- [Proxmox: UEFI и TPM](../../Proxmox/proxmox_overview.md) — UEFI+TPM для Windows 11.
- [Boot Failure Recovery](../../Linux/Diagnostics/Troubleshooting/boot_failure_recovery.md) — восстановление загрузки.
- [LUKS: Шифрование](../../Linux/FileSystems/LVM/advanced_topics/lvm_security_hardening.md) — полное руководство по LUKS2.
- [Virtualization Overview](../virtualization_overview.md) — типы гипервизоров, архитектура.
