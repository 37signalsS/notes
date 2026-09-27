# Портативные домашние директории (systemd-homed)

## Определения

- **systemd-homed** — системная служба, управляющая домашними директориями как самодостаточными и портативными объектами.
- **JSON Record** — структурированные метаданные пользователя (имя, пароль, SSH-ключи, лимиты), хранящиеся в криптографически подписанном формате внутри образа домашней директории или в `/var/lib/systemd/home/`.
- **homectl** — основная утилита командной строки для управления пользователями и их домашними директориями.
- **systemd-userdbd** — сервис-диспетчер, объединяющий записи пользователей из различных источников (SSSD, homed, локальные файлы) в единый API через D-Bus.
- **pam_systemd_home** — модуль PAM, обеспечивающий аутентификацию и автоматическую активацию (монтирование) директории при входе пользователя.
- **Портативный аккаунт** — пользователь, все данные и метаданные которого инкапсулированы в единый переносимый контейнер (LUKS2-образ или подтом), пригодный для подключения к любой совместимой системе.
- **Аппаратный токен (HW Token)** — физическое устройство (FIDO2-ключ, TPM2-чип, смарт-карта PKCS#11), используемое для разблокировки ключей шифрования без ввода пароля.

## Основные концепции

Традиционный подход (файлы в `/etc/passwd`, `/etc/shadow`) имеет фундаментальный недостаток: метаданные пользователя отделены от его данных. Это затрудняет перенос аккаунтов между системами и усложняет реализацию полного шифрования «на лету». `systemd-homed` инкапсулирует данные и метаданные в единый защищенный контейнер, который «владеет собой».

### Ключевые преимущества

1. **Портативность:** Домашняя директория (LUKS2-образ или подтом) содержит всё необходимое. При подключении диска к новой системе служба автоматически обнаруживает и регистрирует пользователя.
2. **Шифрование по умолчанию:** Использование LUKS2 с поддержкой динамического изменения размера и онлайн-решифрования (re-encryption).
3. **Криптографическая подпись:** Метаданные (JSON Record) подписаны ключом хоста или пользователя, что гарантирует неизменность параметров аккаунта.
4. **Аппаратная защита:** Нативная поддержка FIDO2, TPM2 и PKCS#11 для разблокировки ключей.
5. **Изоляция и лимиты:** Интеграция с cgroups v2 позволяет задавать лимиты на ресурсы (CPU, Memory, Disk) прямо в профиле пользователя.

### Архитектура и взаимодействие

```text
[ Приложение ]  --> [ NSS / PAM ]
                            |
                 [ systemd-userdbd ] <---- [ SSSD ]
                            |        <---- [ systemd-homed ]
                            |        <---- [ /etc/passwd ]
                 [ systemd-homed ]
                            |
                 [ LUKS2 / Btrfs / ext4 / fscrypt ]
```

### Принцип работы и жизненный цикл

1. **Создание:** `homectl create` формирует JSON Record, создаёт хранилище (образ/подтом) и настраивает PAM/NSS через `systemd-userdbd`.
2. **Активация:** При входе пользователя `pam_systemd_home` запрашивает разблокировку (пароль/FIDO2/TPM2), расшифровывает том и монтирует его в `/home/<user>` (или в переназначенный путь).
3. **Сессия:** Процессы пользователя попадают в собственную cgroup, где действуют заданные лимиты.
4. **Блокировка:** `homectl lock` вымывает ключи шифрования из памяти, но оставляет том смонтированным (сессия заморожена).
5. **Деактивация:** `homectl deactivate` размонтирует том и закрывает LUKS-контейнер.
6. **Миграция:** `homectl export/import` переносит полный portable-блейд (данные + метаданные) между системами.

### JSON Record — структура и хранение

JSON Record содержит все параметры аккаунта, кроме файловых данных:

- **Идентификация:** логин, UID, GID, комментарий (GECOS), домашний путь, shell.
- **Аутентификация:** хэш пароля (в поддерживаемых алгоритмах), enrolled-устройства (FIDO2/TPM2/PKCS#11).
- **Квоты:** `disk-size`, `disk-soft-limit`.
- **Память и CPU:** `memory-high`, `memory-max`, `cpu-weight`, `cpu-quota`.
- **SSH-ключи:** массив `authorized-keys` для разблокировки без доступа к смонтированной директории.
- **Срок действия:** `password-expiration-max`, `password-expiration-min`.
- **Членство в группах:** `member-of`.

Хранение:
- **Внутри образа:** в корне LUKS2-тома (защищено шифрованием).
- **Вне образа:** в `/var/lib/systemd/home/` (полезно для резервного копирования метаданных без тела директории).

### Валидация и подпись

JSON Record подписывается ключом `/etc/machine-id` хоста (или отдельным ключом пользователя). При импорте на другой хост проверяется:
1. Подпись записи.
2. Совместимость политик (алгоритмы хэширования, версия формата).
3. Отсутствие конфликтов UID/GID (если не используется remapping).

## Типы хранилищ (Storage Backends)

| Тип | Описание | Рекомендация |
| :--- | :--- | :--- |
| **luks** | Зашифрованный образ LUKS2 (файл или раздел). | **Рекомендуется** для максимальной безопасности. |
| **fscrypt** | Шифрование на уровне файловой системы (ext4/f2fs). | Оптимально для систем без поддержки LUKS. |
| **subvolume** | Подтома Btrfs с использованием квот. | Удобно для снапшотов, но шифрование на уровне FS. |
| **directory** | Обычная директория в `/home/`. | Не рекомендуется (нет шифрования и изоляции). |
| **cifs** | Монтирование удаленной папки по SMB/CIFS. | Для сетевых корпоративных профилей. |

## Предварительные требования

### Программное обеспечение

- **systemd:** v245+ (рекомендуется v253+ для полной поддержки cgroups v2 и TPM2).
- **Ядро Linux:** 5.14+ (5.18+ для стабильной работы FIDO2 в headless-средах).
- **Пакеты:**
  - `systemd-homed` (обычно включён в базовый пакет systemd).
  - `libfido2-dev` / `libfido2-1` для FIDO2.
  - `tpm2-tools` для TPM2.
  - `opensc` для PKCS#11.
- **Файловая система:** Для `subvolume` требуется Btrfs; для `fscrypt` — ext4 с включённым `fscrypt` или f2fs.

### Требования к оборудованию

- **TPM2:** версия 1.3 или 2.0, включённый в UEFI/BIOS.
- **FIDO2:** любой поддерживаемый ключ (YubiKey 5+, SoloKeys, Nitrokey 3).
- **PKCS#11:** смарт-карта или токен с поддерживаемым драйвером (например, OpenSC).

### Подготовка системы

```bash
# Проверка версии systemd
systemd --version
# → systemd 255 (v255+ recommended)

# Проверка поддержки cgroups v2
mount | grep cgroup
# → cgroup2 on /sys/fs/cgroup type cgroup2 (rw,nosuid,nodev,noexec,relatime)

# Проверка наличия службы
systemctl status systemd-homed.service systemd-userdbd.service
```

### Включение службы

```bash
sudo systemctl enable --now systemd-homed.service
sudo systemctl enable --now systemd-userdbd.service
```

## Управление сервисом и верификация

### Проверка состояния службы

```bash
# Общий статус
systemctl status systemd-homed.service

# Проверка активных пользователей homed
homectl list
# → NAME       STATE    REALNAME
# → devops     active   DevOps Engineer
# → guest      inactive Guest

# Подробный статус конкретного пользователя
homectl status devops
# →        State: active (since Mon 2026-09-13 10:00:00 MSK)
# →      Storage: luks (/home/devops/home)
# →       Device: /dev/mapper/home-devops
# →       Mount:  /home/devops
# →  Disk Size:   50G (10.2G used)
# → Memory Max:  4G
# → Memory High: 2G
```

### Поиск и фильтрация пользователей

```bash
# Все портативные аккаунты
homectl list --json

# Фильтр по состоянию
homectl list --state=active
homectl list --state=inactive

# Интеграция с NSS (видит homed + локальные + LDAP)
getent passwd devops
# → devops:x:1000:1000:DevOps Engineer:/home/devops:/bin/bash
```

### Проверка целостности JSON Record

```bash
# Верификация подписи (локально)
sudo homectl verify devops

# Просмотр метаданных в читаемом формате
sudo homectl inspect devops --json
```

## Практические сценарии

### 1. Создание пользователя с шифрованием и лимитами

Создадим пользователя `devops` с квотой 50 ГБ и ограничением памяти.

```bash
sudo homectl create devops \
    --storage=luks \
    --disk-size=50G \
    --memory-high=2G \
    --memory-max=4G \
    --member-of=wheel,video
# → Creating home for devops...
# → Everything completed successfully.
```

**Пояснение параметров:**
- `--storage=luks` — тип хранилища (аналог таблицы выше).
- `--disk-size=50G` — мягкий лимит диска (при превышении возможна экспансия).
- `--memory-high=2G` — мягкий лимит памяти (throttling при превышении).
- `--memory-max=4G` — жёсткий лимит (OOM при превышении).
- `--member-of=wheel,video` — группы, в которые добавляется пользователь.

### 2. Привязка аппаратных токенов (FIDO2/TPM2/PKCS#11)

`systemd-homed` позволяет привязать разблокировку к аппаратному ключу.

```bash
# Привязка токена FIDO2 (первый доступный)
sudo homectl update devops --enrolled-fido2-device=auto

# Привязка к TPM2 конкретного хоста (защита от кражи диска)
sudo homectl update devops --enrolled-tpm2-device=auto

# Привязка PKCS#11 токена (например, смарт-карта)
sudo homectl update devops --enrolled-pkcs11-device="/usr/lib/opensc-pkcs11.so"

# Проверка enrolled-устройств
homectl status devops
# → FIDO2: yes, TPM2: yes
```

### 3. Управление состоянием

```bash
# Активация (расшифровка и монтирование)
sudo homectl activate devops

# Блокировка (заморозка сессии, вымывание ключей из памяти)
sudo homectl lock devops

# Деактивация (размонтирование и закрытие LUKS)
sudo homectl deactivate devops
```

### 4. Инспектирование и аудит

```bash
# Список всех пользователей homed (только portable)
homectl list

# Детальный статус
homectl status devops

# Полный дамп JSON Record
sudo homectl inspect devops

# Проверка подписи записи
sudo homectl verify devops
```

### 5. Изменение параметров и миграция

```bash
# Изменение размера диска (только увеличение для luks)
sudo homectl resize devops --disk-size=100G

# Смена пароля
sudo homectl update devops --password=новый_пароль

# Обновление SSH-ключей (доступно до входа)
sudo homectl update devops --ssh-authorized-keys="$(cat ~/.ssh/id_rsa.pub)"

# Переименование пользователя (логина)
sudo homectl rename devops old-devops

# Изменение лимитов памяти
sudo homectl update devops --memory-high=4G --memory-max=8G

# Добавление в группу
sudo homectl update devops --member-of=+docker,+libvirt
```

### 6. Удаление пользователя

```bash
# Полное удаление (данные + метаданные)
sudo homectl remove devops

# Примечание: UID/GID не удаляются из systemd-userdbd автоматически,
# если не используется --remove-all
```

### 7. Экспорт и импорт (Миграция)

Перенос пользователя на другой сервер.

```bash
# На старом сервере (stdout → файл)
sudo homectl export devops > /mnt/usb/devops.home

# Альтернативный синтаксис (прямой путь)
sudo homectl export devops /tmp/devops.homedir

# На новом сервере
sudo homectl import devops < /mnt/usb/devops.home

# Импорт с переименованием
sudo homectl import new-name < /mnt/usb/devops.home
```

### 8. Резервное копирование

```bash
# Экспорт метаданных (без данных)
sudo homectl export devops --meta-only > /var/backups/devops.meta

# Бэкап всего (LUKS-образ)
sudo homectl export devops > /backup/devops-$(date +%F).home

# Проверка целостности перед восстановлением
sudo homectl verify < /backup/devops-2026-09-13.home
```

## Интеграция с cgroups v2 и лимиты ресурсов

`systemd-homed` создаёт для каждого активного пользователя отдельную cgroup в `/sys/fs/cgroup/system.slice/home-<user>.scope/`.

### Доступные параметры

| Параметр homectl | Файл cgroup | Описание |
| :--- | :--- | :--- |
| `--memory-high=2G` | `memory.high` | Мягкий лимит. При превышении kernel начнёт reclaim. |
| `--memory-max=4G` | `memory.max` | Жёсткий лимит. При превышении — OOM Kill внутри cgroup. |
| `--cpu-weight=100` | `cpu.weight` | Относительный вес планирования (дефолт 100). |
| `--cpu-quota=50%` | `cpu.max` | Жёсткий процент CPU (например, 50% = полядяд на 1 ядро). |
| `--disk-size=50G` | `io.max` (опционально) | Лимит IO через cgroup (настраивается дополнительно). |

### Проверка текущих лимитов

```bash
# Путь к cgroup пользователя
CGROUP="/sys/fs/cgroup/system.slice/home-devops.scope"

# Просмотр лимитов памяти
cat $CGROUP/memory.max
cat $CGROUP/memory.high

# Текущее потребление
cat $CGROUP/memory.current

# CPU лимиты (квант/период)
cat $CGROUP/cpu.max

# Проверка throttling
cat $CGROUP/cpu.stat
# → usage_usec 123456789
# → throttled_usec 12345  ← если > 0, процессы испытывали дефицит CPU
```

### Примечания по производительности

- При превышении `memory.high` kernel начинает активно сжимать анонимные страницы (zram/zswap), что может вызвать троттлинг.
- `cpu.max` форматируется как `<quota> <period>`. Значение `max 100000` означает «без ограничения».
- Для приоритизации критичных пользователей используйте `cpu.weight` выше 100.

## Конфигурация (/etc/systemd/homed.conf)

- **`DefaultStorage=`**: Определяет тип хранилища по умолчанию (обычно `luks`).
- **`SuspendMode=`**: При значении `suspend` ключи шифрования удаляются из памяти при входе системы в спящий режим, защищая от Cold Boot атак.
- **`UserIDMax=` / `UserIDMin=`**: Диапазон UID, зарезервированный для systemd-homed.
- **`EnableFIDO2=`**: Глобальное включение/отключение поддержки FIDO2.
- **`EnableTPM2=`**: Глобальное включение/отключение поддержки TPM2.

### Пример конфигурации

```ini
# /etc/systemd/homed.conf
[Home]
DefaultStorage=luks
SuspendMode=suspend
EnableFIDO2=yes
EnableTPM2=yes
```

### Применение конфигурации

```bash
sudo systemctl daemon-reload
sudo systemctl restart systemd-homed.service
```

## Интеграция с графическими оболочками

Современные DE (GNOME 45+, KDE Plasma 6+) полностью поддерживают `systemd-homed`. Диалоги входа (GDM, SDDM) корректно запрашивают пароль для разблокировки LUKS-контейнера перед запуском сессии.

### Особенности реализации

- **GDM:** запрашивает пароль через PAM → `pam_systemd_home` → расшифровка → монтирование → запуск сессии.
- **SDDM:** аналогичная цепочка через PAM.
- **Автоматический вход:** возможен только при наличии enrolled-устройства (FIDO2/TPM2), так как интерактивный ввод пароля отсутствует.

## Известные ограничения

- **UID 0 (root):** Не может управляться через `systemd-homed`.
- **NFS:** Не поддерживается в качестве бэкенда из-за проблем с блокировками и шифрованием.
- **SSH по ключам:** Если домашняя директория зашифрована, SSH-сервер не сможет прочитать `authorized_keys` до входа пользователя. Решение: хранить ключи в JSON Record (`homectl update --ssh-authorized-keys=...`).
- **Онлайн-решифрование:** Доступно только для образов `luks` на SSD/NVMe; на HDD операция может занять часы.
- **Docker/Podman:** rootless-контейнеры пользователя homed работают корректно, но root-контейнеры не имеют доступа к смонтированной домашней директории до активации.

## Troubleshooting

### Пользователь не виден в getent / id

```bash
# Проверка статуса службы
systemctl status systemd-userdbd.service

# Перезапуск агрегатора
sudo systemctl restart systemd-userdbd.service

# Проверка NSS
cat /etc/nsswitch.conf | grep passwd
# → passwd:         files systemd homed
```

### Не удается активировать (отказано в доступе)

```bash
# Проверка enrolled-устройств
homectl status devops

# Логи homed
journalctl -u systemd-homed.service -b --no-pager

# Проверка TPM2
sudo tpm2_getrandom 8

# Проверка FIDO2
sudo systemd-homed --fido2-debug=yes
```

### Ошибка монтирования (Permission denied / No such device)

```bash
# Проверка модуля dm-crypt
lsmod | grep dm_crypt

# Проверка mapper'а
ls -la /dev/mapper/home-devops

# Ручная проверка LUKS
sudo cryptsetup status home-devops
```

### Медленный вход / задержка активации

```bash
# Проверка IO ожидания
iostat -x 1

# Проверка размера образа (большие образы = долгая расшифровка)
ls -lh /home/.private/devops/home

# Отключение ненужных enrolled-устройств
sudo homectl update devops --enrolled-fido2-device=
```

### Конфликт UID при импорте

```bash
# Проверка занятых UID
getent passwd 1000

# Импорт с remapping (если поддерживается)
sudo homectl import devops --uid-map=auto < devops.home
```

## Безопасность

### Хранение ключей и enrolled-устройства

- **FIDO2:** Ключ хранится на токене; PIN-код не передаётся на хост. При потере токена — восстановление через enrolled-резервное устройство или пароль.
- **TPM2:** Привязан к конкретному хосту. Диск, извлечённый и подключенный к другому хосту, не сможет быть разблокирован (защита от кражи).
- **PKCS#11:** Требует вставки смарт-карты и ввода PIN.

### Рекомендации

1. **Резервное устройство:** Для каждого пользователя заведите хотя бы одно резервное enrolled-устройство.
2. **Регулярная ротация:** Периодически обновляйте хэш пароля и SSH-ключи в JSON Record.
3. **Аудит подписей:** Регулярно проверяйте `homectl verify` на критичных машинах.
4. **Cold Boot:** Используйте `SuspendMode=suspend` в `homed.conf` для очистки ключей при переходе в сон.
5. **Резервное копирование:** Создавайте бекапы JSON Record (`--meta-only`) отдельно от шифрованных данных.

### Ограничения безопасности

- JSON Record внутри незашифрованного `/var/lib/systemd/home/` не содержит хэшей паролей, но содержит SSH-ключи и enrolled-метаданные. Защищайте этот каталог (`chmod 750`, SELinux).
- Если enrolled-устройство сломано, а резервного нет — единственный способ разблокировки: пароль (если он был установлен).

## Операционные аспекты для SRE/DevOps

### Управление парком рабочих станций

- **Provisioning:** При автоматическом развёртывании (PXE + Kickstarter/Image) генерируйте уникальные `machine-id` до первого запуска `systemd-homed`, чтобы подписи JSON Record были валидны.
- **Мониторинг:** Добавьте в мониторинг проверку `systemctl is-active systemd-homed.service` и `homectl list --state=inactive` (неактивные пользователи = потенциальные проблемы с сессиями).
- **Логирование:** `journalctl -u systemd-homed.service` содержит события активации/деактивации; интегрируйте с ELK/Loki для централизованного аудита.
- **Бэкапы:** Регулярно экспортируйте метаданные (`homectl export --meta-only`) в центральное хранилище. Это позволяет восстановить структуру аккаунтов даже при потере томов.

### Производительность и UX

- **Время входа:** Активация LUKS2-тома на NVMe занимает 1–3 секунды; на HDD — до 10 секунд для 50 ГБ. Учитывайте это при настройке `GDM` timeout.
- **Снапшоты:** При использовании `subvolume` для home можно создавать снапшоты Btrfs без отключения сервиса, что удобно для ротации рабочих станций.
- **Одновременные входы:** `systemd-homed` поддерживает несколько активных сессий одного пользователя (multiseat) корректно.

### Совместимость с контейнерами

- **Podman/Docker Rootless:** Корректно работают внутри активированного homed-профиля; UID/GID совпадают с хостом.
- **Root-контейнеры:** Имеют доступ только к смонтированной директории после активации; до активации — пусто.

### Энергопотребление

- `SuspendMode=suspend` + TPM2: при входе в сон ключи вымываются из RAM, что защищает от Cold Boot без полного деактивирования.
- Для ноутбуков рекомендуется использовать `fscrypt` на встроенном диске, если TPM2 недоступен.

## Дополнительная информация

### Смежные темы

- [Управление пользователями](./user_commands.md) — императивный подход и `systemd-userdbd`.
- [Централизованное управление (LDAP, SSSD)](./LDAP_SSSD/index.md) — интеграция в корпоративные среды.
- [cgroups — лимиты ресурсов](../../Core/cgroups.md) — детали работы cgroups v2.
