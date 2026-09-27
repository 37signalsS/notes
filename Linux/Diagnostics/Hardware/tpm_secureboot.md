# TPM2, Secure Boot и Measured Boot

## Определения

**TPM (Trusted Platform Module)** — аппаратный криптографический модуль (стандарт TCG), реализующий функции генерации и хранения ключей шифрования, измерения целостности платформы (Measured Boot) и аттестации. TPM2 (2.0) — текущая версия стандарта (2024+).

**PCR (Platform Configuration Register)** — аппаратные регистры TPM, содержащие криптографические хеши (SHA-256) каждого этапа загрузки. Измерения «накапливаются» — новый хеш учитывает предыдущее значение. Запись в PCR обратима только перезагрузкой.

**Secure Boot** — механизм UEFI, проверяющий цифровые подписи загрузчика (shim, GRUB), ядра и модулей перед выполнением. Предотвращает загрузку неподписанных или повреждённых компонентов (bootkits, rootkits).

**Measured Boot** — процесс последовательного измерения (хеширования) каждого компонента загрузки и записи результатов в PCR TPM. Позволяет удалённой стороне (attestation server) проверить целостность платформы.

**Attestation** — процесс предоставления TPM-доказательств (quotes) удалённой стороне для подтверждения, что платформа загружена в доверенном состоянии. Используется в zero-trust архитектурах.

**PCR 0–7** — стандартные регистры измерения:
- **PCR 0:** Хеш UEFI firmware (SEC/PEI/DXE).
- **PCR 1:** Хеш MAC addresses, bus-specific info.
- **PCR 2:** Хеш option ROMs.
- **PCR 3:** Хеш UEFI variables (Secure Boot state).
- **PCR 4:** Хеш загрузчика (shim, GRUB).
- **PCR 5:** Хеш GPT таблицы разделов.
- **PCR 7:** Статус Secure Boot и база ключей.
- **PCR 8–9:** Хеши ядра Linux и командной строки (при использовании UKI).

---

## Базовые концепции

### Архитектура TPM2

```
UEFI Firmware → Измеряет → PCR 0-7 → TPM2 чип
                                  ↓
                    Аттестация (quote) → Удалённая проверка
                                  ↓
                    Ключи шифрования → LUKS, dm-crypt
```

### Режимы работы TPM

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Firmware TPM (fTPM)** | Реализован в прошивке CPU (Intel PTT, AMD fTPM) | Встроенные решения, без выделенного чипа |
| **Discrete TPM (dTPM)** | Выделенный аппаратный чип на материнской плате | Высокая безопасность, серверы |
| **Virtual TPM (vTPM)** | Эмуляция TPM для виртуальных машин | Контейнеры, VM |

### Secure Boot chain of trust

```
UEFI firmware (PCR 0)
    ↓ проверяет подпись
Shim (PCR 4)
    ↓ проверяет подпись
GRUB (PCR 4)
    ↓ проверяет подпись
Linux kernel + initramfs (PCR 8-9)
    ↓
Приложения
```

### Ключи, управляемые через TPM

| Тип ключа | Назначение | PCR Policy |
| :--- | :--- | :--- |
| **Storage Root Key (SRK)** | Корневой ключ иерархии | Нет |
| **Endorsement Key (EK)** | Уникальный идентификатор TPM | Нет (связан с чипом) |
| **Attestation Identity Key (AIK)** | Аттестация платформы | PCR 0-7 |
| **Disk Encryption Key** | Шифрование диска (LUKS2) | PCR 7 (Secure Boot state) |
| **Network Access Key** | 802.1X, VPN | PCR 0, 4, 7 |

---

## Практические сценарии

### Проверка наличия TPM

```bash
# Проверка через sysfs
ls /dev/tpm*
# → /dev/tpm0  /dev/tpmrm0

# Проверка TPM через dmesg
dmesg | grep -i tpm
# → [    0.000000] TPM: ACPI TPM2.0: enumerated
# → [    0.000000] tpm_tis 00:05: 2.0 TPM (tpm-tpm)

# Установка tpm2-tools (Debian/Ubuntu)
sudo apt install tpm2-tools tpm2-abrmd

# Установка tpm2-tools (RHEL/Rocky/Alma)
sudo dnf install tpm2-tools tpm2-abrmd

# Просмотр информации о TPM
sudo tpm2_getcap properties-fixed
# → TPM2_PT_FAMILY_INDICATOR: 2.0
# → TPM2_PT_MANUFACTURER: 0x534d5300 (SMS)
# → TPM2_PT_FIRMWARE_VERSION_1: 0x00000001
# → TPM2_PT_FIRMWARE_VERSION_2: 0x001c0001

# Проверка типа TPM (fTPM vs dTPM)
sudo dmidecode -t 43 | grep -i "tpm"
# → TPM Device: Firmware
# → Version: 2.0
```

### Проверка статуса Secure Boot

```bash
# Через bootctl (systemd)
bootctl status | grep -i "secure"
# → Secure Boot: enabled (或disabled)

# Через efibootmgr
mokutil --sb-state
# → SecureBoot enabled (илиdisabled)

# Через dmesg
dmesg | grep -i "secure boot"
# → Secure boot enabled

# Проверка ключей Secure Boot
mokutil --list-enrolled
# →  Baby Signer
# →  Microsoft Corporation UEFI CA 2011

# Проверка подписи загрузчика
sbverify --list /boot/efi/EFI/ubuntu/shimx64.efi
```

### Measured Boot: измерения PCR

```bash
# Просмотр текущих значений PCR через tpm2-tools
sudo tpm2_pcrread sha256:0,1,2,3,4,5,7,8,9
# →  0 : 0x3A 0xB7 ...  (UEFI firmware)
# →  4 : 0xD2 0xE1 ...  (GRUB)
# →  7 : 0x1F 0x8C ...  (Secure Boot keys)
# →  8 : 0xA1 0x2B ...  (kernel)

# Простой вывод
sudo tpm2_pcrread sha256:7
# → sha256:
# →   0 : 0x1F8C...A3B2

# Сравнение с эталоном (после обновления GRUB PCR 4 изменится)
sudo tpm2_pcrread sha256:4 > /tmp/pcr4_current.txt
# После обновления GRUB:
sudo tpm2_pcrread sha256:4 > /tmp/pcr4_after.txt
diff /tmp/pcr4_current.txt /tmp/pcr4_after.txt
# → PCR 4 изменился → GRUB был обновлён
```

### Шифрование диска через TPM (LUKS2+TPM)

```bash
# Проверка поддержки TPM2 для LUKS
systemd-cryptenroll --tpm2-device=auto /dev/sda2
# → device: /dev/tpmrm0
# → device: 0x000b (TPM 2.0)

# Запись ключа шифрования в TPM (авторазблокировка)
sudo systemd-cryptenroll /dev/sda2 --tpm2-device=auto --tpm2-pcrs=0,7
# → Enroll TPM2 device (y/n): y
# → Entered passphrase: [hidden]
# → Enrolled successfully

# Проверка записей LUKS
sudo cryptsetup luksDump /dev/sda2 | grep -A2 "tpm2"
# → Key Slot 1: ENABLED
# →   TPM2 device: /dev/tpmrm0
# →   PCR policies: 0, 7

# Откат (если нужно вернуть на пароль)
sudo systemd-cryptenroll /dev/sda2 --wipe-slot=tpm2
```

**Важно:** PCR 7 (Secure Boot state) гарантирует, что ключ шифрования будет выдан только при загрузке в Trusted State. Если Secure Boot отключён — PCR 7 изменится, и диск не будет расшифрован.

### Аттестация TPM (remote attestation)

```bash
# Генерация quote (доказательства)
sudo tpm2_quote -c 0x81010002 -l sha256:0,4,7 -q "test" -o /tmp/quote.dat
# → quote: ... (подписанные PCR-значения)

# Проверка quote через tpm2_checkquote
sudo tpm2_checkquote -u 0x81010002 -m /tmp/quote.dat -s /tmp/quote.sig -o /tmp/quote.pcr
```

### Автоматическая проверка целостности платформы

```bash
# Скрипт для проверки PCR (для мониторинга)
#!/bin/bash
PCR7=$(sudo tpm2_pcrread -Q sha256:7)
KNOWN_HASH="0x1F8C...A3B2"  # установленный при последней known-good загрузке

if [ "$PCR7" != "$KNOWN_HASH" ]; then
  echo "CRITICAL: PCR 7 changed! Possible Secure Boot tampering."
  echo "Current: $PCR7"
  echo "Expected: $KNOWN_HASH"
  # Отправка алерта
fi
```

### Диагностика проблем Secure Boot

```bash
# Ошибка: "Security violation" при загрузке
# Причина: неподписанный загрузчик или модуль ядра

# Проверка подписи ядра
sbverify --cert /usr/share/secureboot/keys/PK.crt /boot/vmlinuz-$(uname -r)

# Проверка подписи модуля
modinfo <module> | grep -i signer
# → signer: Ubuntu Secure Boot Signing

# Добавление Machine Owner Key (MOK) для неподписанных модулей
sudo mokutil --import /path/to/MOK.der
# → Enter password: [для подтверждения]
# → Reboot и выполнить enrollment через MokManager

# Проверка enrolled MOK
mokutil --list-enrolled
```

### Отключение Secure Boot (для отладки)

```bash
# Через mokutil (требует перезагрузки)
sudo mokutil --disable-validation
# → Enter password: [пароль]

# Или через BIOS/UEFI Setup
# → Security → Secure Boot → Disable

# Проверка после отключения
mokutil --sb-state
# → SecureBoot disabled
```

---

## Дополнительная информация

### Типичные сценарии использования

| Сценарий | PCR 0-7 | PCR 8-9 | Применение |
| :--- | :--- | :--- | :--- |
| **LUKS2 auto-unlock** | + | — | Автоматическое расшифрование диска |
| **Attestation** | + | + | Проверка целостности перед доступом к сервису |
| **Secure Boot only** | — | — | Только проверка подписей, без PCR |
| **Full Measured Boot** | + | + | Максимальная аттестация |

### Ограничения

- **Потеря доступа:** Если Secure Boot был включён, а потом выключен — PCR 7 изменится, LUKS2 с TPM-политикой PCR 7 откажется расшифровывать диск.
- **Обновление firmware:** Обновление BIOS/UEFI изменит PCR 0, что может сломать автоматическую расшифровку.
- **VM:** В виртуальных машинах fTPM может работать некорректно; используйте vTPM.

### Связанные темы

- **[BIOS/UEFI и загрузка](../../Core/firmware_bios_uefi.md)** — UEFI architecture, PCR,measured boot.
- **[LUKS шифрование](../../FileSystems/virtual_filesystems.md)** — dm-crypt, systemd-cryptenroll.
- **[Firmware updates](./firmware_update.md)** — fwupd, UEFI capsule updates.
- **[Zero Trust](../../Vault/zero_trust.md)** — attestation в zero-trust архитектуре.
- **[Secure Boot в Kubernetes](../../Kubernetes/Installation/)** — verified boot для k8s nodes.
