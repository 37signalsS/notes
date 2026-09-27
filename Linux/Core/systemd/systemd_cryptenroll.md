# systemd-cryptenroll: Шифрование дисков и автоматическая разблокировка

## Определения

* **`systemd-cryptenroll`** — системная утилита для управления ключами шифрования LUKS2 (Linux Unified Key Setup). Позволяет регистрировать (enroll) аппаратные токены (TPM2, FIDO2, PKCS#11) для автоматической разблокировки зашифрованных разделов без ввода пароля.
* **LUKS2 (Linux Unified Key Setup 2)** — стандарт шифрования блочных устройств в Linux. Обеспечивает шифрование данных на уровне раздела с поддержкой множественных ключей, метаданных и аппаратных токенов.
* **TPM2 (Trusted Platform Module 2)** — аппаратный модуль безопасности, интегрированный в материнскую плату. Хранит ключи шифрования и обеспечивает их автоматическую выдачу только при неизменности загрузочной цепочки (Measured Boot).
* **FIDO2** — стандарт аутентификации, поддерживающий аппаратные ключи (YubiKey, Nitrokey). Позволяет разблокировать LUKS2 нажатием кнопки на ключе или вводом PIN.
* **PKCS#11** — стандарт программного интерфейса для работы с аппаратными токенами (смарт-карты, HSM). Поддерживается через библиотеки `opensc`, `opensc-pkcs11`.
* **Clevis** — фреймворк для автоматической разблокировки LUKS2 без пароля. Использует «пинты» (pin) для привязки к различным источникам аутентификации (TPM2, Tang, SSH).
* **Key Enrollment (регистрация ключа)** — процесс добавления нового ключа (пароля, токена) в LUKS2-заголовок. Позволяет иметь несколько способов разблокировки одного раздела.
* **PCR (Platform Configuration Registers)** — регистры TPM2, хранящие «измерения» (хэши) каждого этапа загрузки. Используются для привязки ключей к определённой конфигурации загрузчика и ядра.

## Основные концепции

### Архитектура шифрования с systemd-cryptenroll

```
Пользователь (PIN/пароль/аппаратный ключ)
        │
        ▼
  systemd-cryptenroll (управление ключами)
        │
        ├─→ LUKS2 заголовок (на диске)
        │     ├─→ Ключ 0: пароль
        │     ├─→ Ключ 1: TPM2
        │     ├─→ Ключ 2: FIDO2
        │     └─→ Ключ 3: PKCS#11
        │
        └─→ systemd-cryptsetup (разблокировка)
              │
              ▼
        /dev/mapper/<имя>
              │
              ▼
        Файловая система (ext4, xfs, btrfs)
```

### Интеграция с systemd-загрузкой

`systemd-cryptenroll` тесно интегрирован с процессом загрузки systemd:

1. **systemd-stub** — измеряет компоненты загрузки в TPM2 PCR 11.
2. **systemd-boot** — передает управление ядру с параметрами шифрования.
3. **systemd-cryptsetup** — разблокирует LUKS2-разделы при загрузке.
4. **systemd-cryptenroll** — управляет ключами для автоматической разблокировки.

```
UEFI Secure Boot
        │
        ▼
  systemd-stub (PCR 11: измерение)
        │
        ▼
  Ядро Linux
        │
        ▼
  systemd (PID 1)
        │
        ▼
  systemd-cryptsetup@dev-disk-by\x2duuid-xxx.service
        │
        ├─→ Попытка TPM2 разблокировки
        ├─→ Попытка FIDO2 разблокировки
        └─→ Запрос пароля (fallback)
              │
              ▼
        /dev/mapper/cryptroot
```

### Типы аппаратных токенов

| Токен | Описание | Преимущества | Ограничения |
| :--- | :--- | :--- | :--- |
| **TPM2** | Аппаратный модуль на материнской плате | Автоматическая разблокировка, привязка к хосту | Привязан к конкретному хосту, не переносим |
| **FIDO2** | USB-ключ (YubiKey, Nitrokey) | Портативность, физическая аутентификация | Требует физического доступа, стоимость |
| **PKCS#11** | Смарт-карты, HSM | Высокая безопасность, централизованное управление | Сложность настройки, стоимость HSM |
| **Clevis** | Программный фреймворк | Гибкость, поддержка Tang (сетевая разблокировка) | Требует настройки сервера Tang |

### Порядок приоритета ключей

При загрузке `systemd-cryptsetup` проверяет ключи в следующем порядке:

1. **TPM2** — автоматическая разблокировка (если PCR совпадают).
2. **FIDO2** — запрос нажатия на ключе.
3. **PKCS#11** — запрос PIN на смарт-карте.
4. **Пароль** — ручной ввод (fallback).

## Конфигурация

### Базовые команды

```bash
# Просмотр информации о LUKS2-разделе
systemd-cryptenroll /dev/sda2

# Просмотр всех registered ключей
systemd-cryptenroll --list-keys /dev/sda2

# Регистрация нового пароля
systemd-cryptenroll /dev/sda2

# Регистрация TPM2-токена
systemd-cryptenroll --tpm2-device=auto /dev/sda2

# Регистрация FIDO2-токена
systemd-cryptenroll --fido2-device=auto /dev/sda2

# Удаление ключа
systemd-cryptenroll --wipe-slot=1 /dev/sda2
```

### Настройка TPM2

```bash
# 1. Проверить наличие TPM2
ls /dev/tpm*
# → /dev/tpm0  /dev/tpmrm0

# 2. Проверить версию TPM
tpm2_getcap properties-fixed | grep TPM2_PT_FIRMWARE_VERSION
# → TPM2_PT_FIRMWARE_VERSION: 0x00040000 0x00107002

# 3. Зарегистрировать TPM2-токен
sudo systemd-cryptenroll --tpm2-device=auto /dev/sda2
# → Please enter current passphrase for disk /dev/sda2: ********
# → New TPM2 token enrolled.

# 4. Проверить регистрацию
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup
# → 1       systemd-tpm2

# 5. Настроить PCR-политику (опционально)
sudo systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=0,2,7 /dev/sda2
# → PCR 0: Софт-конфигурация
# → PCR 2: Конфигурация загрузчика
# → PCR 7: Secure Boot
```

### Настройка FIDO2

```bash
# 1. Проверить наличие FIDO2-устройства
fido2-token -L
# → /dev/hidraw0: vendor=0x1050 product=0x0407 (Yubico)

# 2. Зарегистрировать FIDO2-токен
sudo systemd-cryptenroll --fido2-device=auto /dev/sda2
# → Please enter current passphrase for disk /dev/sda2: ********
# → Please confirm presence on your FIDO2 device.
# → New FIDO2 token enrolled.

# 3. Проверить регистрацию
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup
# → 1       systemd-fido2

# 4. Регистрация с PIN
sudo systemd-cryptenroll --fido2-device=auto --fido2-with-user-verification=yes /dev/sda2
```

### Настройка PKCS#11 (смарт-карты)

```bash
# 1. Проверить наличие смарт-карты
pkcs11-tool -L
# → Available slots:
# → Slot 0: My Smart Card

# 2. Зарегистрировать PKCS#11-токен
sudo systemd-cryptenroll --pkcs11-token-uri=auto /dev/sda2
# → Please enter current passphrase for disk /dev/sda2: ********
# → Please enter PIN for smart card: ********
# → New PKCS#11 token enrolled.

# 3. Проверить регистрацию
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup
# → 1       systemd-pkcs11
```

### Настройка Clevis (сетевая разблокировка)

```bash
# 1. Установить Clevis
sudo apt install clevis clevis-luks clevis-tpm2 clevis-systemd  # Debian/Ubuntu
sudo dnf install clevis clevis-luks clevis-tpm2 clevis-systemd  # RHEL/CentOS

# 2. Зарегистрировать Clevis с Tang-сервером
sudo clevis luks bind -d /dev/sda2 tang '{"url":"http://tang.example.com"}'
# → Please enter existing passphrase: ********
# → The luks device was bound successfully.

# 3. Проверить регистрацию
sudo clevis luks list -d /dev/sda2
# → 1: tang '{"url":"http://tang.example.com"}'

# 4. Автоматическая разблокировка при загрузке
sudo systemctl enable clevis-luks-askpass.path
```

## Практические сценарии

### 1. Полная настройка шифрования с TPM2

```bash
# 1. Проверить наличие TPM2
ls /dev/tpm*
# → /dev/tpm0  /dev/tpmrm0

# 2. Создать LUKS2-раздел
sudo cryptsetup luksFormat /dev/sda2
# → WARNING!
# → This will overwrite data on /dev/sda2 irrevocably.
# → Are you sure? (Type uppercase yes): YES
# → Enter passphrase for /dev/sda2: ********
# → Verify passphrase: ********

# 3. Открыть раздел
sudo cryptsetup luksOpen /dev/sda2 cryptroot
# → Enter passphrase for /dev/sda2: ********

# 4. Создать файловую систему
sudo mkfs.ext4 /dev/mapper/cryptroot

# 5. Зарегистрировать TPM2
sudo systemd-cryptenroll --tpm2-device=auto /dev/sda2

# 6. Проверить
sudo systemd-cryptenroll --list-keys /dev/sda2

# 7. Настроить fstab
echo "/dev/mapper/cryptroot / ext4 defaults 0 1" | sudo tee -a /etc/fstab

# 8. Настроить crypttab
echo "cryptroot /dev/sda2 none luks" | sudo tee /etc/crypttab

# 9. Перезагрузиться для проверки
sudo reboot
```

### 2. Добавление FIDO2 к существующему LUKS2

```bash
# 1. Проверить текущие ключи
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup

# 2. Добавить FIDO2
sudo systemd-cryptenroll --fido2-device=auto /dev/sda2
# → Please enter current passphrase for disk /dev/sda2: ********
# → Please confirm presence on your FIDO2 device.
# → New FIDO2 token enrolled.

# 3. Проверить
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup
# → 1       systemd-fido2

# 4. Проверить разблокировку через FIDO2
sudo systemctl restart systemd-cryptsetup@cryptroot.service
# → Please confirm presence on your FIDO2 device.
```

### 3. Множественные ключи для отказоустойчивости

```bash
# 1. Зарегистрировать TPM2 (основной способ)
sudo systemd-cryptenroll --tpm2-device=auto /dev/sda2

# 2. Зарегистрировать FIDO2 (резервный способ)
sudo systemd-cryptenroll --fido2-device=auto /dev/sda2

# 3. Зарегистрировать пароль (fallback)
# (пароль уже зарегистрирован по умолчанию)

# 4. Проверить все ключи
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup
# → 1       systemd-tpm2
# → 2       systemd-fido2

# 5. Порядок разблокировки:
#    1. TPM2 (автоматически)
#    2. FIDO2 (нажатие на ключ)
#    3. Пароль (ручной ввод)
```

### 4. Удаление ключа

```bash
# 1. Просмотр текущих ключей
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup
# → 1       systemd-tpm2
# → 2       systemd-fido2

# 2. Удалить FIDO2-ключ (слот 2)
sudo systemd-cryptenroll --wipe-slot=2 /dev/sda2

# 3. Проверить
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup
# → 1       systemd-tpm2

# 4. Удалить все кроме пароля
sudo systemd-cryptenroll --wipe-slot=tpm2,fido2 /dev/sda2
```

### 5. Настройка PCR-политики для TPM2

```bash
# 1. Просмотр текущих PCR-значений
sudo systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=0,1,2,3,4,5,6,7 /dev/sda2

# 2. Регистрация с политикой PCR 0,2,7 (рекомендуется)
sudo systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=0,2,7 /dev/sda2
# → PCR 0: Soft Configuration
# → PCR 2: Boot Loader Configuration
# → PCR 7: Secure Boot

# 3. Проверить PCR-политику
sudo systemd-cryptenroll --tpm2-device=auto /dev/sda2
# → TPM2 PCR Policy: 0,2,7

# 4. Тест: изменение загрузчика должно сломать автоматическую разблокировку
sudo bootctl update
# → При следующей загрузке TPM2 не сможет разблокировать (PCR не совпадают)
```

### 6. Откат от TPM2 к паролю

```bash
# 1. Проверить текущие ключи
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup
# → 1       systemd-tpm2

# 2. Удалить TPM2-ключ
sudo systemd-cryptenroll --wipe-slot=tpm2 /dev/sda2

# 3. Проверить
sudo systemd-cryptenroll --list-keys /dev/sda2
# → TOKEN   LABEL
# → 0       systemd-cryptsetup

# 4. Теперь разблокировка только по паролю
```

## Диагностика и устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| TPM2 не обнаружен | TPM2 отключен в BIOS/UEFI | `ls /dev/tpm*` | Включите TPM2 в BIOS/UEFI |
| FIDO2 не обнаружен | Ключ не подключен или драйвер отсутствует | `fido2-token -L` | Подключите ключ, установите `libfido2` |
| Ошибка PCR | PCR-политика не совпадает | `journalctl -u systemd-cryptsetup` | Пере-enroll с правильной политикой |
| Разблокировка не работает | Неправильный порядок ключей | `systemd-cryptenroll --list-keys` | Проверьте порядок и настройки |
| PKCS#11 не работает | Библиотека не найдена | `pkcs11-tool -L` | Установите `opensc`, `opensc-pkcs11` |
| Clevis не разблокирует | Tang-сервер недоступен | `curl http://tang.example.com` | Проверьте сетевую связность |
| LUKS2 заголовок поврежден | Ошибка при записи | `cryptsetup luksDump /dev/sda2` | Восстановите из резервной копии |
| Недостаточно слотов | Все 32 слота заняты | `systemd-cryptenroll --list-keys` | Удалите неиспользуемые ключи |

## Рекомендации по эксплуатации

1. **Используйте TPM2** для автоматической разблокировки на серверах. Это безопаснее пароля и не требует физического доступа.
2. **Добавляйте FIDO2** как резервный способ для portable-устройств (ноутбуки, рабочие станции).
3. **Настройте PCR-политику** для привязки к определённой конфигурации загрузки (PCR 0,2,7).
4. **Не храните пароли в открытом виде** — используйте аппаратные токены или `systemd-creds`.
5. **Делайте резервные копии LUKS2-заголовков** перед изменением ключей: `cryptsetup luksHeaderBackup /dev/sda2 --header-backup-file /path/to/backup.img`.
6. **Проверяйте регистрацию** перед перезагрузкой: `systemd-cryptenroll --list-keys /dev/sda2`.
7. **Для кластеров** используйте Tang-серверы для сетевой разблокировки (Clevis).
8. **Мониторьте логи** через `journalctl -u systemd-cryptsetup` для обнаружения ошибок.
9. **Не удаляйте все ключи** — всегда оставляйте хотя бы один способ разблокировки.
10. **Документируйте процедуру восстановления** при потере доступа к токенам.

## Ограничения и особенности

* **Только LUKS2:** `systemd-cryptenroll` работает только с LUKS2. Для LUKS1 используйте `cryptsetup`.
* **Ограничение слотов:** LUKS2 поддерживает максимум 32 ключевых слота. Используйте их рационально.
* **TPM2 привязан к хосту:** TPM2-ключи не переносимы между хостами. Для переносимости используйте FIDO2.
* **PCR-политика:** Изменение загрузчика или ядра может сломать автоматическую разблокировку. Тестируйте перед деплоем.
* **Версии systemd:** Полная поддержка требует systemd v248+. Проверяйте версию: `systemd --version`.
* **UEFI vs BIOS:** TPM2 требует UEFI-режима. В BIOS TPM2 недоступен.
* **Контейнеры:** В Docker/контейнерах `systemd-cryptenroll` не работает. Используйте его на уровне хоста.
* **Безопасность:** TPM2 не защищает от атак через DMA (Direct Memory Access). Используйте IOMMU для дополнительной защиты.

## Дополнительная информация

### См. также

* [systemd-homed](../../SystemAdministration/Users/systemd-homed.md) — портативные домашние директории с LUKS2.
* [systemd-repart](./systemd_repart.md) — декларативное создание разделов.
* [LUKS2 и шифрование](../../FileSystems/LVM/management_operations.md) — управление зашифрованными томами.
* [TPM2 и Measured Boot](../../Core/kernel/boot_process.md) — процесс загрузки и измерения.
* [Безопасность](../../Security/ssh/ssh_certificate_authentication.md) — аутентификация и управление ключами.
