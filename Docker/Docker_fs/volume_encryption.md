# Шифрование томов в Docker (Encryption at Rest)

**Актуально для:** Docker 24.x–29.x, containerd 1.7.x–2.4.x, cryptsetup 2.4+

## Определения

- **Шифрование данных «на покое» (Encryption at Rest)** — метод защиты информации, при котором данные преобразуются в зашифрованный вид перед записью на физический носитель. Это предотвращает чтение данных в случае физической кражи диска или несанкционированного доступа к файловой системе хоста.
- **В контексте Docker** — шифрование томов критически важно для соблюдения стандартов безопасности (GDPR, PCI-DSS, HIPAA) и защиты конфиденциальной информации (БД, сертификаты, конфигурационные файлы с секретами).
- **Прозрачное шифрование (Transparent Encryption)** — шифрование, которое происходит на уровне блочного устройства или файловой системы и не требует изменения кода приложений. Приложение работает с данными так, как будто они хранятся в открытом виде.
- **Key Management Service (KMS)** — служба управления ключами, которая генерирует, хранит, ротирует и аудирует использование криптографических ключей. В контексте шифрования томов KMS используется для защиты мастер-ключей шифрования.
- **Copy-on-Write (CoW)** — механизм, при котором изменения файлов записываются в новое место, а оригинал остается нетронутым. В контексте шифрования это означает, что шифруются не отдельные файлы, а весь носитель или том целиком.

## Предварительные требования

### Аппаратные и программные требования

- **Docker Engine**: версия 24.x–29.x (локально установлен Docker 29.8.1). Для поддержки `--mount` и совместимости с внешними драйверами требуется Docker 20.10+. На Docker Desktop (Mac/Windows) шифрование применяется внутри виртуальной машины и требует отдельной настройки.
- **Ядро Linux**: версия 5.10+ (для поддержки fscrypt в ext4/f2fs) или 4.8+ (для базового OverlayFS). Для LUKS требуется версия 2.6.4+ (dm-crypt). LUKS2 с Argon2 PBKDF рекомендуется для production и требует ядро 4.12+. Для ZFS native encryption требуется ZFS userspace 0.8.0+.
- **Аппаратное ускорение AES**: современные процессоры (Intel Westmere 2010+, AMD Bulldozer 2011+) поддерживают набор инструкций AES-NI, который позволяет выполнять шифрование с минимальными потерями производительности (<3%). Рекомендуется проверять поддержку перед выбором алгоритма шифрования.
- **Права доступа**: для работы с LUKS и блочными устройствами требуются права root. Для шифрования директорий через fscrypt требуются права на запись в целевую директорию.
- **Файловая система**: для LUKS — любая (ext4, XFS, Btrfs). Для fscrypt — только ext4 или f2fs с включенной опцией `encrypt`. Для ZFS native encryption — ZFS версии 0.8.0+.
- **Состояние хоста**: шифрование директории, уже содержащей данные тома, требует предварительного бэкапа, так как большинство методов шифрования требует форматирования или пересоздания файловой системы.

### Подготовка окружения

Перед настройкой шифрования выполните базовую диагностику:

```bash
# Проверка версии Docker
docker version
# → Client: Docker Engine - Community ...
# → Server: Docker Engine - Community ...

# Проверка текущего драйвера хранения
docker info --format '{{.Driver}}'
# → overlay2 (рекомендуется)

# Проверка поддержки AES-NI
grep -o "aes" /proc/cpuinfo | head -n 1
# Если выведет "aes" — аппаратное ускорение активно

# Проверка модулей ядра для шифрования
lsmod | grep -E "dm_crypt|aesni_intel"
# → dm_crypt              245760  0
# → aesni_intel           360448  4

# Проверка доступных блочных устройств (для LUKS)
lsblk -f
# → NAME   FSTYPE LABEL UUID                                 MOUNTPOINTS
# → sda
#   └─sda1 ext4         123e4567-e89b-12d3-a456-426614174000 /
#   └─sda2
```

## Основные концепции

### Почему Docker не имеет нативного шифрования томов

Docker **не имеет встроенного механизма** для прозрачного шифрования томов. Демон Docker оперирует на уровне файловой системы и делегирует задачи защиты данных:
1. **Операционной системе** (прозрачное шифрование блочных устройств или директорий).
2. **Внешним хранилищам секретов и KMS** (управление ключами на выделенных серверах).
3. **Сторонним плагинам** (Volume Drivers с поддержкой криптографии).

Причины отсутствия нативного шифрования:
- Docker следует философии «делать одну thing хорошо». Шифрование требует сложного управления ключами, аудита и интеграции с внешними KMS, что выходит за рамки функции контейнерной рантайм.
- Шифрование на уровне файловой системы или блочного устройства является прозрачным для приложений: контейнер не должен знать, что данные шифруются. Это позволяет применять шифрование без пересборки образов.
- Встроенное шифрование привело бы к дублированию функционала, уже предоставляемого ОС (dm-crypt, fscrypt, ZFS).

### Методы реализации

| Уровень | Технология | Плюсы |
| :--- | :--- | :--- |
| **Блочный (FDE)** | LUKS / dm-crypt | Максимальная защита, прозрачность для всех приложений |
| **Файловый** | `fscrypt` (ext4/f2fs), ZFS Native Encryption | Выборочное шифрование отдельных директорий/датасетов |
| **Оркестрация** | Docker Secrets, tmpfs, внешние менеджеры секретов | Встроенная поддержка, монтирование в `tmpfs` |
| **Плагины** | Локальные драйверы томов с поддержкой криптографии | Управление через Docker API/CLI |

### Управление ключами

Безопасность системы шифрования напрямую зависит от хранения ключей. Ключи **никогда** не должны храниться на том же диске, который они шифруют.
- **Внешние хранилища секретов**: [HashiCorp Vault](../../Vault/overview.md) (Transit Engine).
- **TPM (Trusted Platform Module)**: Аппаратная привязка ключей к железу сервера.
- **Локальное хранение (Not Recommended)**: Хранение ключей на том же хосте в файле, защищенном правами доступа 0600, является крайне небезопасным вариантом, допустимым только в dev-средах.
- **Ключевые файлы на внешних носителях**: для production-хостов храните ключевые файлы LUKS на USB-накопителе или в HSM, подключаемом только во время загрузки.

### Влияние шифрования на производительность

Шифрование добавляет накладные расходы на CPU (шифрование/расшифрование каждого блока данных). Современные процессоры с AES-NI позволяют минимизировать эти расходы до <3%. Без аппаратного ускорения производительность может снизиться на 20-50% для I/O-интенсивных нагрузок.

При проектировании шифрованной инфраструктуры учитывайте:
- **Аппаратное ускорение AES-NI**: обязательно для production.
- **Алгоритм шифрования**: `aes-xts-plain64` (рекомендуется для LUKS) обеспечивает баланс безопасности и производительности.
- **Размер блока шифрования**: использование слишком малого размера блока увеличивает накладные расходы.

## Практические сценарии

### Сценарий 1: Шифрование директории томов с помощью LUKS

Этот метод обеспечивает прозрачное шифрование всех данных в `/var/lib/docker/volumes`. Docker не требует изменений конфигурации — он продолжает работать с `/var/lib/docker/volumes` как с обычной директорией, в то время как ОС прозрачно шифрует/расшифровывает данные на уровне блочного устройства.

#### Шаг 1: Подготовка окружения и блочного устройства

```bash
# Остановка Docker для безопасного переноса данных
sudo systemctl stop docker

# Создание файла-образа для демонстрации (на практике используется реальный раздел)
# Размер: 10 ГБ
dd if=/dev/zero of=/secure-docker-volumes.img bs=1G count=10 status=progress
# → 10+0 записей получено
# → 10+0 записей отправлено

# Подключение loop-устройства
sudo losetup /dev/loop0 /secure-docker-volumes.img

# Проверка: устройство должно появиться в lsblk
lsblk /dev/loop0
# → NAME  MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
# → loop0   7:0    0   10G  0 loop
```

#### Шаг 2: Инициализация LUKS

```bash
# Инициализация LUKS контейнера
# Будет запрошен пароль (passphrase) — минимум 8 символов, рекомендуется 20+
sudo cryptsetup luksFormat /dev/loop0
# → WARNING!
# → ========
# → Это будет перезаписать /dev/loop0.
# →
# → Введите YES (заглавными) для продолжения.
# → Введите пароль LUKS:

# Верификация заголовка LUKS
sudo cryptsetup luksDump /dev/loop0
# → LUKS header version 2
# → ...
# → Key Slot 0: ENABLED
```

#### Шаг 3: Открытие зашифрованного устройства

```bash
# Открытие контейнера (создает /dev/mapper/docker_volumes_encrypted)
sudo cryptsetup open /dev/loop0 docker_volumes_encrypted

# Проверка: в /dev/mapper должен появиться новый символьный файл
ls -l /dev/mapper/docker_volumes_encrypted
# → lrwxrwxrwx 1 root root 7 Aug 21 14:00 /dev/mapper/docker_volumes_encrypted -> ../dm-3
```

#### Шаг 4: Создание файловой системы и перенос данных

```bash
# Создание ext4 файловой системы внутри зашифрованного слоя
sudo mkfs.ext4 /dev/mapper/docker_volumes_encrypted
# → создание файловой системы ext4 ...
# → Группы суперблоков сохранены в первом блоке группы

# Создание точки монтирования
sudo mkdir -p /var/lib/docker/volumes

# Монтирование зашифрованного устройства
sudo mount /dev/mapper/docker_volumes_encrypted /var/lib/docker/volumes

# Восстановление прав доступа (если переносим существующие тома)
sudo chown -R root:root /var/lib/docker/volumes
sudo chmod 711 /var/lib/docker/volumes

# Запуск Docker
sudo systemctl start docker

# Проверка статуса шифрования
sudo cryptsetup status docker_volumes_encrypted
# → /dev/mapper/docker_volumes_encrypted is active.
# →   type:    LUKS2
# →   cipher:  aes-xts-plain64
# →   keysize: 512 bits
```

Подробности работы с блочными устройствами см. в **[Обзоре хранилищ Linux](../../Linux/FileSystems/storage_overview.md)**.

#### Шаг 5: Настройка автоматического монтирования при загрузке

Для production-сред настройте автоматическое открытие LUKS и монтирование при загрузке системы:

```bash
# Получение UUID зашифрованного устройства
sudo blkid /dev/loop0
# → /dev/loop0: UUID="abc123..." TYPE="crypto_LUKS"

# Добавление в /etc/crypttab (имя_маппера UUID none luks)
echo "docker_volumes_encrypted UUID=$(sudo blkid -s UUID -o value /dev/loop0) none luks" | sudo tee -a /etc/crypttab

# Добавление в /etc/fstab
echo "/dev/mapper/docker_volumes_encrypted /var/lib/docker/volumes ext4 defaults 0 2" | sudo tee -a /etc/fstab
```

При использовании реального диска (не loop-образа) для автоматического открытия без интерактивного ввода пароля можно использовать ключевой файл:

```bash
# Создание ключевого файла (хранить на внешнем носителе!)
sudo dd if=/dev/urandom of=/root/luks-keyfile.bin bs=4096 count=1
sudo chmod 600 /root/luks-keyfile.bin

# Добавление ключевого файла в LUKS
sudo cryptsetup luksAddKey /dev/loop0 /root/luks-keyfile.bin

# crypttab с ключевым файлом
echo "docker_volumes_encrypted UUID=$(sudo blkid -s UUID -o value /dev/loop0) /root/luks-keyfile.bin luks" | sudo tee -a /etc/crypttab
```

### Сценарий 2: Файловое шифрование через fscrypt (ext4)

`fscrypt` позволяет шифровать конкретные директории, не затрагивая весь раздел. Это удобно для защиты только директорий конкретных томов.

#### Шаг 1: Подготовка файловой системы

```bash
# Проверка, что ФС поддерживает fscrypt
sudo tune2fs -l /var/lib/docker/volumes | grep "Filesystem features"
# → Filesystem features: ... encrypt ...

# Инициализация fscrypt на файловой системе (требуется один раз)
sudo fscrypt setup /var/lib/docker/volumes
# → fscrypt initialized successfully on "/var/lib/docker/volumes".
```

#### Шаг 2: Создание зашифрованной директории

```bash
# Создание зашифрованной директории
mkdir /var/lib/docker/volumes/my_secure_volume
sudo fscrypt encrypt /var/lib/docker/volumes/my_secure_volume
# → Введите пароль для защиты ключей:
# → Подтвердите пароль:
# → Директория "/var/lib/docker/volumes/my_secure_volume" зашифрована.
```

#### Шаг 3: Разблокировка и использование

```bash
# Разблокировка директории (требуется перед использованием Docker)
sudo fscrypt unlock /var/lib/docker/volumes/my_secure_volume
# → Введите пароль для разблокировки:

# Настройка Docker на использование этой директории
sudo mkdir -p /var/lib/docker/volumes/my_secure_volume/_data
sudo chown -R root:root /var/lib/docker/volumes/my_secure_volume
```

#### Шаг 4: Автоматизация разблокировки при загрузке

```bash
# Создание PAM-скрипта для автоматической разблокировки при загрузке
# или использование systemd-сервиса с ключевым файлом (хранить в безопасном месте)
sudo fscrypt setup --key=MyKey --source=pam_passphrase /var/lib/docker/volumes
```

### Сценарий 4: Интеграция с HashiCorp Vault (Transit Engine)

Transit Engine в Vault позволяет реализовать шифрование данных на уровне приложения или через вспомогательные скрипты, не полагаясь только на шифрование диска. Это полезно, когда необходимо шифровать конкретные файлы внутри тома.

#### Шаг 1: Настройка Vault и политик

```bash
# Включение Transit Engine (выполняется администратором Vault)
vault secrets enable transit

# Создание ключа с поддержкой convergent encryption (опционально)
vault write -f transit/keys/docker-volumes-key type=aes256-gcm96

# Создание политики с минимальными правами для приложения
cat <<EOF | vault policy write docker-volumes-encrypt -
path "transit/encrypt/docker-volumes-key" {
  capabilities = ["create", "update"]
}
path "transit/decrypt/docker-volumes-key" {
  capabilities = ["create", "update"]
}
EOF
```

#### Шаг 2: Использование в entrypoint-скрипте

```bash
#!/bin/bash
# entrypoint-encrypt.sh

# Аутентификация в Vault (AppRole или Kubernetes Auth)
export VAULT_ADDR='https://vault.example.com:8200'
vault login -method=approle role_id=my-role secret_id=...

# Функция шифрования перед записью
encrypt_file() {
    local plaintext=$(base64 -w0 "$1")
    vault write -field=ciphertext transit/encrypt/docker-volumes-key plaintext="$plaintext" > "${1}.enc"
}

# Функция расшифровки при чтении
decrypt_file() {
    local ciphertext=$(cat "${1}.enc")
    vault read -field=plaintext transit/decrypt/docker-volumes-key ciphertext="$ciphertext" | base64 -d > "$1"
}

# Пример использования
encrypt_file /var/lib/docker/volumes/my-vol/_data/sensitive_data.txt
```

#### Шаг 3: Контейнеризация

```bash
docker run -d --name my-app \
  -v my-vol:/data \
  -e VAULT_ADDR=https://vault.example.com:8200 \
  -e VAULT_ROLE_ID=my-role-id \
  -e VAULT_SECRET_ID=my-secret-id \
  my-app-image \
  /app/entrypoint-encrypt.sh
```

Подробнее об управлении ключами см. в **[HashiCorp Vault: Обзор](../../Vault/overview.md)** и **[Руководстве по интеграции Vault с Docker](../../Vault/guides/vault_docker_integration.md)**.

### Сценарий 5: Шифрование через Sidecar-контейнер (Gocryptfs)

В некоторых случаях (например, в Docker Swarm или при отсутствии прав `root` на хосте) удобно использовать `sidecar`-контейнер для предоставления зашифрованной точки монтирования.

#### Шаг 1: Подготовка ключа и инициализация хранилища

```bash
# Генерация ключа шифрования (хранить в Vault или KMS)
PASSPHRASE=$(openssl rand -base64 32)

# Инициализация зашифрованного хранилища
# Выполняется один раз
mkdir -p /secure-storage/data
echo "$PASSPHRASE" > /secure-storage/.key
gocryptfs -init -passphrase "$PASSPHRASE" /secure-storage
# → Вывод: Password: ...
# → Вывод: Конфиг сохранен в /secure-storage/gocryptfs.conf
```

#### Шаг 2: Запуск Sidecar-контейнера

```bash
# Запуск sidecar с FUSE и общим томом
docker run -d --name crypto-sidecar \
  --device /dev/fuse \
  --cap-add SYS_ADMIN \
  --security-opt apparmor=unconfined \
  -v crypto-data:/decrypted \
  -v /secure-storage:/encrypted:ro \
  alpine/gocryptfs \
  sh -c "gocryptfs -passphrase $(cat /encrypted/.key) /encrypted /decrypted && sleep infinity"
```

#### Шаг 3: Использование основным контейнером

```bash
# Основной контейнер подключает тот же том crypto-data
docker run -d --name my-app \
  --volumes-from crypto-sidecar \
  my-app-image
```

**Ограничения и устранение проблем:**
- Требует FUSE: убедитесь, что `/dev/fuse` доступен в контейнере.
- AppArmor/SELinux: на Ubuntu/Fedora может потребоваться `apparmor=unconfined` или настройка политик SELinux.
- Производительность: FUSE добавляет накладные расходы ~10-30% по сравнению с нативным ext4.
- Отказоустойчивость: если sidecar упадет, основной контейнер потеряет доступ к данным.

## Валидация результатов

После настройки любого метода шифрования выполните комплексную проверку:

### 1. Проверка статуса шифрования LUKS

```bash
sudo cryptsetup status docker_volumes_encrypted
# → /dev/mapper/docker_volumes_encrypted is active.
# →   type:    LUKS2
# →   cipher:  aes-xts-plain64
# →   keysize: 512 bits
# →   key location: keyring
# →   device:  /dev/loop0
```

### 2. Проверка монтирования в Docker

```bash
docker volume ls --filter driver=local
# → DRIVER    VOLUME NAME
# → local     my-app-data

docker volume inspect my-app-data
# → [
# →   {
# →     "CreatedAt": "2026-08-21T12:00:00Z",
# →     "Driver": "local",
# →     "Labels": {},
# →     "Mountpoint": "/var/lib/docker/volumes/my-app-data/_data",
# →     "Name": "my-app-data",
# →     "Options": {},
# →     "Scope": "local"
# →   }
# → ]
```

### 3. Проверка записи и персистентности данных

```bash
# Запуск контейнера с томом
docker run -d --name test-container \
  --mount type=volume,source=my-app-data,target=/data \
  alpine sleep 3600

# Запись данных
docker exec test-container sh -c "echo 'secret-data-$(date)' > /data/test.txt"

# Проверка на хосте (в зашифрованном томе)
sudo cat /var/lib/docker/volumes/my-app-data/_data/test.txt
# → secret-data-Fri Aug 21 14:00:00 CEST 2026

# Проверка, что данные не читаются без расшифровки (для LUKS)
sudo cryptsetup close docker_volumes_encrypted
sudo cat /var/lib/docker/volumes/my-app-data/_data/test.txt
# → cat: /var/lib/docker/volumes/my-app-data/_data/test.txt: Input/output error
# (данные недоступны без открытого LUKS-контейнера)

# Повторное открытие и проверка
sudo cryptsetup open /dev/loop0 docker_volumes_encrypted
sudo mount /dev/mapper/docker_volumes_encrypted /var/lib/docker/volumes
docker exec test-container cat /data/test.txt
# → secret-data-Fri Aug 21 14:00:00 CEST 2026
```

### 4. Проверка поддержки AES-NI

```bash
grep -o "aes" /proc/cpuinfo | head -n 1
# → aes (если поддерживается)

# Более точная проверка
grep -E "aes|avx" /proc/cpuinfo | head -n 5
# → aes
# → avx
# → avx2
```

### 5. Проверка fscrypt

```bash
# Проверка статуса директории
sudo fscrypt status /var/lib/docker/volumes/my_secure_volume
# → Директория "/var/lib/docker/volumes/my_secure_volume" зашифрована.
# → Политика: [имя_политики]

# Разблокировка и проверка через Docker
sudo fscrypt unlock /var/lib/docker/volumes/my_secure_volume
docker exec test-container ls -la /data/my_secure_volume
# → (файлы видны только при разблокированной директории)
```

## Устранение неполадок

| Ошибка / Симптом | Причина |
| :--- | :--- |
| **Permission denied** при монтировании LUKS | ФС внутри LUKS примонтирована с неверными правами |
| **Disk is busy** при `cryptsetup close` | Контейнеры удерживают файлы на зашифрованном томе |
| **Низкая скорость записи** | Отключен AES-NI или используется слишком тяжелый алгоритм |
| `cryptsetup: ERROR: device /dev/loop0 already exists.` | Loop-устройство уже подключено |
| **No key available with this passphrase.** | Неверный пароль LUKS |
| `fscrypt: filesystem does not support fscrypt` | ФС не поддерживает fscrypt или не инициализирована |
| **Docker не стартует после монтирования зашифрованного тома** | Неправильные права на точку монтирования |
| **Потеря ключевого файла LUKS** | Ключевой файл утерян |
| **Sidecar gocryptfs не монтирует том** | Отсутствуют права FUSE или AppArmor блокирует | Убедитесь, что `/dev/fuse` доступен и AppArmor/SELinux разрешает монтирование |
| **Vault Transit возвращает ошибку permission denied** | Политика Vault не разрешает доступ | Проверьте политику Vault и токен приложения |

## Производительность и аппаратное ускорение

### Проверка поддержки AES-NI

```bash
# Быстрая проверка
grep -o "aes" /proc/cpuinfo | head -n 1
# → aes (если поддерживается)

# Детальная проверка с AVX
grep -E "aes|avx|avx2" /proc/cpuinfo | sort -u
# → aes
# → avx
# → avx2

# Бенчмарк производительности шифрования
cryptsetup benchmark
# → Tests are approximate using memory only (no storage IO).
# →
# → # Algorithm |       Key |      Encryption |      Decryption
# → aes-xts    256b      1.5 GB/s         1.5 GB/s
```

### Оптимизация производительности

- **LUKS**: используйте `aes-xts-plain64` с размером ключа 256 или 512 бит.
- **fscrypt**: на ext4 шифрование выполняется на уровне блочного устройства, поэтому производительность зависит от underlying ФС.
- **ZFS**: native encryption работает на уровне dataset, но требует ZFS 0.8.0+ и аппаратного ускорения для приемлемой производительности.
- **Локальные диски**: используйте SSD/NVMe для encrypted workloads; проверяйте `lsblk` и `nvme smart-log` для verification типа накопителя.

### Влияние на Docker операции

Шифрование на уровне хоста прозрачно для Docker:
- `docker build` работает без изменений (сборка образа использует OverlayFS поверх зашифрованного тома).
- `docker run` не требует дополнительных флагов.
- `docker volume create` работает как обычно.
- `docker commit` создает снимок слоев без учета шифрования (слои остаются в зашифрованном хранилище).

### Page Cache и безопасность

Важно помнить, что шифрование «на покое» защищает данные на диске. Однако, когда файлы открыты и с ними работает контейнер, расшифрованные данные могут находиться в **Page Cache** ядра Linux (в оперативной памяти). Для полной защиты необходимо также обеспечивать безопасность физической памяти сервера (ограничение прямого доступа к RAM, использование RAM encryption где доступно).

## Резервное копирование

### Бэкап зашифрованных томов LUKS

```bash
# Остановка Docker
sudo systemctl stop docker

# Создание резервной копии всего зашифрованного контейнера
sudo cryptsetup close docker_volumes_encrypted
sudo dd if=/dev/loop0 of=/backup/docker-volumes-backup.img bs=4M status=progress
# → 1024+0 записей получено
# → 1024+0 записей отправлено

# Резервная копия заголовка LUKS (критически важно!)
sudo cryptsetup luksHeaderBackup /dev/loop0 --header-backup-file /backup/luks-header-backup.img
```

Восстановление из бэкапа:

```bash
# Восстановление заголовка LUKS
sudo cryptsetup luksHeaderRestore /dev/loop0 --header-backup-file /backup/luks-header-backup.img

# Открытие и монтирование
sudo cryptsetup open /dev/loop0 docker_volumes_encrypted
sudo mount /dev/mapper/docker_volumes_encrypted /var/lib/docker/volumes

# Запуск Docker
sudo systemctl start docker
```

### Бэкап на уровне файлов

Если вы копируете файлы из примонтированного (расшифрованного) тома, бэкап будет открытым, если вы не зашифруете его отдельно (например, через `gpg` или встроенные средства утилит бэкапа).

```bash
# Шифрованный бэкап через tar + gpg
docker run --rm \
  --mount type=volume,source=my-app-data,target=/data,readonly \
  --mount type=bind,source=$(pwd)/backup,target=/backup \
  alpine \
  tar -czf - -C /data . | gpg --symmetric --cipher-algo AES256 -o /backup/backup.tar.gz.gpg
```

## SRE/DevOps: мониторинг и эксплуатация

### Ключевые метрики для мониторинга

**Дисковое пространство:**
```bash
# Использование томов Docker
docker system df -v
# → VOLUMES    ...    SIZE
# → IMAGES     ...    SIZE
# → Containers ...    SIZE

# Использование раздела с томами
df -h /var/lib/docker/volumes
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/mapper/docker_volumes_encrypted  20G  8.5G   11G  45% /var/lib/docker/volumes
```

**Inodes:**
```bash
df -i /var/lib/docker/volumes
# → IUse% должен быть низким (< 80%)
```

**Статус шифрования:**
```bash
# LUKS статус
sudo cryptsetup status docker_volumes_encrypted
# → type: LUKS2, cipher: aes-xts-plain64, keysize: 512 bits

# fscrypt статус
sudo fscrypt status /var/lib/docker/volumes/my_secure_volume
# → Директория зашифрована, политика активна
```

**Производительность шифрования:**
```bash
# Бенчмарк cryptsetup
cryptsetup benchmark
# → Algorithm | Key | Encryption | Decryption
# → aes-xts    256b      1.5 GB/s         1.5 GB/s

# Проверка AES-NI
grep -E "aes|avx|avx2" /proc/cpuinfo | sort -u
# → aes, avx, avx2
```

### Алерты и пороговые значения

На production-хостах настройте следующие алерты:

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| `Use%` раздела `/var/lib/docker/volumes` | > 80% | Расширить раздел или очистить неиспользуемые тома |
| `IUse%` раздела | > 80% | Очистить мелкие файлы или пересоздать ФС с большим лимитом inodes |
| `docker system df` — `Reclaimable` | > 20% | Запустить `docker system prune` |
| `cryptsetup status` — `device` не активен | N/A | Критический алерт: зашифрованный том не смонтирован |
| `fscrypt status` — директория не зашифрована | N/A | Критический алерт: потеря шифрования |
| AES-NI не обнаружен | N/A | Предупреждение: производительность шифрования снижена |

### Compliance и аудит

Для соответствия GDPR, PCI-DSS, HIPAA:

1. **Документируйте шифрование**: ведите реестр всех зашифрованных томов с указанием:
   - Путь к устройству/директории
   - Алгоритм и размер ключа
   - Владелец/сервис
   - Дата создания и последней проверки восстановления

2. **Аудит доступа**: логируйте все операции с LUKS (`/var/log/cryptsetup` или auditd), монтирования (`/var/log/syslog`), и Docker volume operations (`docker events`).

3. **Политика ключей**:
   - Ротация ключей минимум раз в 90 дней
   - Ключи LUKS хранятся отдельно от хоста (USB, HSM, Vault)
   - Минимум 2 ключевых файла на том (основной + резервный)

4. **Тестирование восстановления**: минимум раз в квартал выполняйте восстановление из бэкапа LUKS-заголовка на тестовом хосте.

### Автоматизация

**Cron для очистки dev-сред:**
```bash
# Ежедневная очистка неиспользуемых ресурсов
0 2 * * * docker system prune -a --volumes --filter "until=24h" -f
```

**Systemd-сервис для проверки шифрования:**
```ini
# /etc/systemd/system/encryption-check.service
[Unit]
Description=Check encrypted volumes status
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check-encryption.sh

[Install]
WantedBy=multi-user.target
```

**Скрипт проверки (`/usr/local/bin/check-encryption.sh`):**
```bash
#!/bin/bash
# Проверка статуса LUKS томов
for vol in docker_volumes_encrypted; do
    if ! cryptsetup status $vol >/dev/null 2>&1; then
        echo "CRITICAL: LUKS volume $vol is not active"
        exit 1
    fi
done

# Проверка fscrypt директорий
for dir in /var/lib/docker/volumes/*_secure; do
    if [ -d "$dir" ] && ! fscrypt status "$dir" >/dev/null 2>&1; then
        echo "WARNING: fscrypt directory $dir is not encrypted"
    fi
done

exit 0
```

### Диагностика проблем

**Page Cache и безопасность:**
- Шифрование «на покое» защищает данные на диске. Однако, когда файлы открыты, расшифрованные данные находятся в **Page Cache** ядра Linux.
- Для полной защиты обеспечивайте безопасность физической памяти (ограничение прямого доступа к RAM, использование RAM encryption где доступно).
- На хостах с высоким уровнем доверия используйте `mlock()` для критичных процессов через `--cap-add IPC_LOCK`.

**Производительность при массовом запуске контейнеров:**
- При одновременном запуске множества контейнеров с зашифрованными томами наблюдается всплеск I/O из-за decryption.
- Ограничьте параллельный запуск через orchestrator (деплой по 10-20% хостов за раз).
- Мониторьте `iostat -x 1` и `cryptsetup status` для detection bottlenecks.

## Рекомендации и очистка

### Рекомендации

1. **Приоритизируйте блочное шифрование (LUKS)** для production-хостов. Оно обеспечивает максимальную прозрачность и безопасность с минимальными накладными расходами при наличии AES-NI.
2. **Никогда не храните ключи LUKS на том же диске.** Используйте внешние носители, TPM или менеджеры секретов (Vault).
3. **Используйте именованные тома** вместо анонимных — они видны в `docker volume ls`, имеют понятные имена и легче поддаются бэкапированию.
4. **Не храните секреты в томах на диске без шифрования.** Для чувствительных данных используйте `tmpfs`, Docker Secrets или внешние менеджеры секретов (Vault). Подробнее: **[Управление секретами в Docker](../Docker_security/secrets_management.md)**.
5. **Настраивайте ротацию логов.** Если приложение пишет логи в том, используйте логирование Drivers или ограничивайте размер файлов, чтобы том не разрастался бесконтрольно.
6. **Используйте `--mount` вместо `-v`** для новых проектов. Синтаксис `--mount` более явный, поддерживает больше опций (например, `bind-propagation`, `consistency`) и защищает от опечаток в путях.
7. **Включайте аппаратное ускорение AES в BIOS/UEFI.** Проверяйте его наличие на всех production-хостах.
8. **Тестируйте восстановление.** Регулярно проверяйте, что бэкапы LUKS-заголовка и ключевые файлы работают.
9. **Мониторинг диска и inodes**: на production-хостах настройте алерты на заполнение раздела `/var/lib/docker/volumes` > 80% и `IUse%` > 80%. Используйте `docker system df -v` и `df -h /var/lib/docker/volumes`.
10. **Аудит ключей**: ведите реестр ключей LUKS/fscrypt с указанием владельца, даты создания, алгоритма и срока действия. Для Vault Transit Engine включайте аудит-логи (audit device).
11. **Ротация ключей**: для LUKS используйте `cryptsetup luksAddKey` для добавления нового ключа и `cryptsetup luksRemoveKey` для удаления старого. Для Vault настройте автоматическую ротацию через policies.
12. **Автоматизация проверок**: добавьте в CI/CD pipeline проверку наличия шифрования на production-хостах (`cryptsetup status` для каждого зашифрованного тома, `fscrypt status` для директорий).
13. **Для Docker 29+ с containerd snapshotter**: убедитесь, что volumes по-прежнему монтируются из `/var/lib/docker/volumes/` и шифрование на уровне хоста продолжает работать. Containerd snapshotter не меняет пути томов.

### Очистка

```bash
# Остановка Docker перед обслуживанием зашифрованного тома
sudo systemctl stop docker

# Закрытие LUKS контейнера
sudo cryptsetup close docker_volumes_encrypted

# Отключение loop-устройства (если используется)
sudo losetup -d /dev/loop0

# Очистка неиспользуемых томов Docker
docker volume prune

# Очистка всех неиспользуемых ресурсов
docker system prune -a --volumes
```

## Граничные случаи

### Docker Desktop (Mac/Windows)

На не-Linux хостах Docker работает внутри виртуальной машины (HyperKit / WSL2). Это вносит особенности:
- **Пути на хосте**: пути bind mounts (`/Users/mac/...`) транслируются во внутреннюю ФС VM. Именованные тома остаются внутри VM и недоступны напрямую из хоста.
- **Шифрование**: для защиты данных на Mac/Windows используйте FileVault (macOS) или BitLocker (Windows) для шифрования всего диска. Внутри VM применяйте LUKS для дополнительного слоя защиты.
- **Производительность**: запись в bind mounts на macOS/Windows может быть значительно медленнее, чем в named volumes, из-за необходимости транслировать системные вызовы через гостевую ОС.
- **Shared Mounts**: на macOS требуется настройка файлового доступа (Settings → Resources → File Sharing).

### Rootless Docker

При запуске Docker в rootless-режиме:
- Директория с томами по умолчанию находится в `$HOME/.local/share/docker/volumes/`.
- Права на файлы внутри томов устанавливаются для непривилегированного пользователя.
- **Ограничение**: rootless Docker не имеет доступа к LUKS напрямую. Для шифрования используйте:
  - Шифрование на уровне ОС (LUKS на уровне хоста, доступное для rootless-процессов).
  - Внешние драйверы томов с поддержкой шифрования.
  - Файловое шифрование (fscrypt) с соответствующей настройкой прав.

### Взаимодействие с OverlayFS и copy-on-write

Шифрование тома не влияет на работу драйвера хранения OverlayFS, так как:
- Тома монтируются через bind mount в контейнер, минуя записываемый слой (upperdir).
- Данные в томах записываются напрямую в зашифрованную ФС хоста.
- CoW механизм применяется только к слоям образа, а не к томам.

Однако, если вы шифруете весь раздел, на котором хранятся слои образа (через LUKS), это также зашифрует и записываемый слой контейнера, что обеспечивает сквозное шифрование всех данных Docker.

Подробнее о работе OverlayFS: **[Драйвер хранения OverlayFS](./docker_overlayfs.md)**.

### SELinux и метки безопасности

На RHEL, Fedora, CentOS и других дистрибутивах с SELinux:
- Без суффиксов `:z` или `:Z` контейнер может получить Permission Denied даже при корректных UID/GID.
- `:z` — метка `svirt_sandbox_file_t` (общий доступ для всех контейнеров).
- `:Z` — метка `svirt_sandbox_file_t` с уникальным MCS (эксклюзивный доступ).
- Для именованных томов Docker автоматически применяет `:z` при монтировании.
- При использовании шифрованных томов через LUKS SELinux применяется к точке монтирования `/dev/mapper/...`, поэтому убедитесь, что политика разрешает монтирование. При проблемах используйте `chcon -t svirt_sandbox_file_t /var/lib/docker/volumes`.

### Съемные носители и перемещение томов

При использовании внешних шифрованных носителей (USB, NFS с LUKS):
- **Отмонтирование**: перед извлечением носителя остановите все контейнеры, использующие тома на этом устройстве: `docker stop $(docker ps -q --filter volume=my-encrypted-volume)`.
- **Безопасное извлечение**: закройте LUKS (`cryptsetup close`), размонтируйте ФС (`umount`) и только затем извлеките носитель.
- **Перенос на другой хост**: скопируйте файл образа LUKS или entire partition, настройте `crypttab`/`fstab` на целевом хосте, откройте и смонтируйте. Docker увидит тома без дополнительной настройки.

### Квотирование и лимиты

Docker не поддерживает встроенные квоты на размер отдельных томов. Для ограничения используйте:
- **Файловую систему**: создайте отдельный раздел или quota на директорию `/var/lib/docker/volumes/`.
- **Device Mapper / Btrfs**: используйте возможности Filesystem Quotas на уровне хоста.
- **LVM**: создавайте LV фиксированного размера для групп томов с одинаковым SLA.

## Дополнительная информация

### Интеграция с docker-compose.yml

Определение томов и монтирований в `docker-compose.yml` — стандарт индустрии.

```yaml
version: '3.8'

services:
  db:
    image: postgres:14
    environment:
      - POSTGRES_PASSWORD=mysecretpassword
    volumes:
      - db-data:/var/lib/postgresql/data

volumes:
  db-data:
```

### Связанные темы

- **[Управление томами в Docker](./docker_volumes.md)** — типы монтирования, управление томами, связи с OverlayFS.
- **[Резервное копирование и восстановление](./docker_backup_restore.md)** — стратегии бэкапа томов и образов.
- **[Драйвер хранения OverlayFS](./docker_overlayfs.md)** — взаимодействие шифрования с CoW и writable layer.
- **[Управление секретами в Docker](../Docker_security/secrets_management.md)** — Docker Secrets, Vault integration, tmpfs для чувствительных данных.
- **[Обзор хранилищ Linux](../../Linux/FileSystems/storage_overview.md)** — LUKS, Device Mapper, файловые системы (SSoT для общих концепций хранения).
- **[HashiCorp Vault: Обзор](../../Vault/overview.md)** — управление ключами и секретами.
- **[Интеграция Vault с Docker](../../Vault/guides/vault_docker_integration.md)** — практическое руководство по использованию Vault в контейнерах.
