# Основы шифрования в Linux

## Определения

**Шифрование (Encryption)** — процесс преобразования данных с использованием алгоритма и ключа, делающий их нечитаемыми без соответствующего ключа. В Linux шифрование применяется для защиты данных при хранении (Data at Rest), передаче (Data in Transit) и резервном копировании.

**Ключевые понятия:**
- **Симметричное шифрование** — один ключ для шифрования и дешифрования (AES, ChaCha20)
- **Асимметричное шифрование** — пара ключей: публичный для шифрования, приватный для дешифрования (RSA, ECC)
- **Хеш-функции** — одностороннее преобразование для проверки целостности (SHA-256, BLAKE3)
- **Ключевая производная функция (KDF)** — генерация ключа из пароля (PBKDF2, Argon2)

## Теоретический блок

### Уровни шифрования Linux

| Уровень | Технология | Назначение | Инструменты |
| :--- | :--- | :--- | :--- |
| **Блочное устройство** | LUKS/dm-crypt | Шифрование разделов, дисков | `cryptsetup` |
| **Файловая система** | fscrypt, eCryptfs | Шифрование отдельных файлов/каталогов | `fscrypt`, `ecryptfs` |
| **Сетевой транспорт** | TLS/SSL, IPsec, WireGuard | Шифрование сетевого трафика | OpenSSL, `ip`, `wg` |
| **Приложение** | GPG, SSH | Шифрование файлов, ключей, соединений | `gpg`, `ssh-keygen` |
| **Резервное копирование** | Duplicity, Restic | Шифрование бэкапов | `duplicity`, `restic` |

### LUKS (Linux Unified Key Setup)

**LUKS** — стандарт шифрования блочных устройств в Linux, построенный на Device Mapper (dm-crypt). Обеспечивает шифрование данных при хранении с поддержкой множества ключей шифрования.

**Ключевые особенности:**
- Множественные ключи шифрования (keyslots) для совместного доступа
- Защита заголовка устройства (抵抗 атак на raw-уровне)
- Поддержка нескольких алгоритмов шифрования
- Интеграция с systemd (автоматическое расшифрование при загрузке)

**Алгоритмы шифрования LUKS2:**

| Алгоритм | Тип | Ключ | Рекомендация |
| :--- | :--- | :--- | :--- |
| **AES-XTS** | Симметричный | 256/512 бит | Стандарт для дискового шифрования |
| **AES-CBC-ESSIV** | Симметричный | 256 бит | Устаревший, избегать |
| **ChaCha20-Poly1305** | Симметричный | 256 бит | Современный, быстрый на CPU без AES-NI |

**Режимы работы:**
- **plain** — шифрование без заголовка (для swap, ephemeral)
- **luks1** — классический LUKS с заголовком
- **luks2** — современный формат с метаданными JSON

### TLS/SSL (Transport Layer Security)

**TLS** — протокол обеспечения безопасности для сетевых соединений. Шифрует данные при передаче между клиентом и сервером.

**Версии TLS:**
- **TLS 1.3** (2018) — текущий стандарт, безопасен, быстр
- **TLS 1.2** — masih используется, безопасен с правильными cipher suites
- **TLS 1.1/1.0** — устаревшие, небезопасные, должны быть отключены

**Ключевые компоненты:**
- **Сертификаты** — подтверждение принадлежности публичного ключа
- **Цепочки доверия** — иерархия от корневых CA до конечных сертификатов
- **Cipher suites** — набор алгоритмов для шифрования, аутентификации и хешей

### GPG (GNU Privacy Guard)

**GPG** — реализация стандарта OpenPGP для шифрования и подписи данных. Использует асимметричное шифрование.

**Основные операции:**
- **Шифрование** — шифрование данных публичным ключом получателя
- **Подпись** — подтверждение авторства и целостности приватным ключом
- **Верификация** — проверка подписи публичным ключом отправителя

## Практический блок

### Шифрование диска с LUKS

```bash
# 1. Шифрование нового раздела
sudo cryptsetup luksFormat /dev/sdb1
# Выберите алгоритм и введите пароль

# 2. Открытие зашифрованного контейнера
sudo cryptsetup luksOpen /dev/sdb1 encrypted_data
# Создаст /dev/mapper/encrypted_data

# 3. Создание файловой системы
sudo mkfs.ext4 /dev/mapper/encrypted_data

# 4. Монтирование
sudo mount /dev/mapper/encrypted_data /mnt/encrypted

# 5. Закрытие (после использования)
sudo umount /mnt/encrypted
sudo cryptsetup luksClose encrypted_data
```

### Управление ключами LUKS

```bash
# Добавление нового ключа (парольного)
sudo cryptsetup luksAddKey /dev/sdb1

# Добавление ключевого файла
sudo cryptsetup luksAddKey /dev/sdb1 --key-file /path/to/keyfile

# Удаление ключа
sudo cryptsetup luksRemoveKey /dev/sdb1

# Просмотр информации о контейнере
sudo cryptsetup luksDump /dev/sdb1

# Ротация ключа
sudo cryptsetup luksChangeKey /dev/sdb1
```

### Автоматическое расшифрование при загрузке

```bash
# 1. Создание ключевого файла
sudo dd if=/dev/urandom of=/root/luks-keyfile bs=1 count=256
sudo chmod 600 /root/luks-keyfile

# 2. Добавление ключевого файла в LUKS
sudo cryptsetup luksAddKey /dev/sdb1 /root/luks-keyfile

# 3. Настройка /etc/crypttab
# <имя> <устройство> <ключ> <опции>
encrypted_data UUID=xxxx-xxxx none luks
# Или с ключевым файлом:
encrypted_data UUID=xxxx-xxxx /root/luks-keyfile luks

# 4. Обновление initramfs
sudo update-initramfs -u  # Debian/Ubuntu
sudo dracut -f            # RHEL/CentOS
```

### Шифрование с использованием TPM

```bash
# 1. Проверка наличия TPM
ls /dev/tpm*
dmesg | grep -i tpm

# 2. Установка пакетов
sudo apt install tpm2-tools clevis clevis-tpm2  # Debian/Ubuntu
sudo dnf install tpm2-tools clevis clevis-tpm2  # RHEL/CentOS

# 3. Привязка LUKS к TPM
sudo clevis luks bind -d /dev/sdb1 tpm2 '{}'
# Автоматически расшифрует при совпадении PCR-значений

# 4. Проверка
sudo clevis luks list -d /dev/sdb1
```

### Шифрование файлов с GPG

```bash
# 1. Генерация ключевой пары
gpg --full-generate-key
# Выберите RSA, 4096 бит, срок действия

# 2. Экспорт публичного ключа (для передачи)
gpg --export -a "Имя Пользователя" > public_key.asc

# 3. Импорт чужого публичного ключа
gpg --import public_key.asc

# 4. Шифрование файла
gpg -e -r "Получатель" file.txt
# Создаст file.txt.gpg

# 5. Расшифрование
gpg -d file.txt.gpg > file.txt

# 6. Подпись файла
gpg --sign file.txt
# Создаст file.txt.gpg (подписанный)

# 7. Проверка подписи
gpg --verify file.txt.gpg
```

### Проверка целостности с хешами

```bash
# 1. Генерация хеша файла
sha256sum file.txt > file.txt.sha256

# 2. Проверка хеша
sha256sum -c file.txt.sha256

# 3. Генерация хешей всех файлов в директории
find /path/to/dir -type f -exec sha256sum {} \; > checksums.sha256

# 4. Проверка всех хешей
sha256sum -c checksums.sha256
```

### Настройка TLS для веб-сервера

```bash
# 1. Получение сертификата (Let's Encrypt)
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d example.com

# 2. Проверка сертификата
sudo openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -text -noout

# 3. Проверка конфигурации TLS
sudo nginx -t
# Проверка cipher suites
nmap --script ssl-enum-ciphers -p 443 example.com

# 4. Ротация сертификатов
sudo certbot renew --dry-run
```

## Дополнительная информация

### Лучшие практики

1. **Используйте LUKS2** вместо LUKS1 для новых установок
2. **Отключите TLS 1.0/1.1** на всех серверах
3. **Используйте Let's Encrypt** для автоматической ротации сертификатов
4. **Храните ключи LUKS** в аппаратных токенах или TPM
5. **Регулярно ротируйте ключи** шифрования
6. **Проверяйте целостность** файлов с помощью хешей

### Соответствие стандартам

- **PCI DSS** — требование 3.4: шифрование панельных данных при хранении
- **HIPAA** — требование к шифрованию PHI (Protected Health Information)
- **GDPR** — требование к шифрованию персональных данных
- **NIST 800-53** — SC-28 (Protection of Information at Rest)

### Производительность

| Алгоритм | CPU overhead | Рекомендация |
| :--- | :--- | :--- |
| AES-XTS с AES-NI | Низкий (<5%) | Стандарт для дисков |
| ChaCha20-Poly1305 | Средний | Для CPU без AES-NI |
| RSA-4096 | Высокий | Только для малых данных |
| SHA-256 | Низкий | Для проверки целостности |

### Связанные темы

- **[LUKS и LVM](../../Linux/FileSystems/LVM/)** — шифрование поверх LVM
- **[SSH-ключи](../ssh/ssh_overview.md)** — асимметричное шифрование для доступа
- **[SSL/TLS сертификаты](../../Networking/Protocols/tls.md)** — цепочки доверия
- **[Сетевое шифрование](../../Networking/Tunnels/ipsec/ipsec.md)** — IPsec, **[WireGuard](../../Vpn/wireguard.md)**, TLS
- **[Управление секретами](../../Vault/overview.md)** — хранение ключей шифрования
- **[OpenSSL CA](../../Security/Tools/openssl_ca/)** — построение инфраструктуры сертификации
- **[Безопасность модулей ядра](../Mechanisms/kernel_module_security.md)** — подпись и контроль загрузки модулей
- **[Обзор механизмов безопасности](../Linux_Security_Mechanisms_Overview.md)** — место шифрования в архитектуре защиты
