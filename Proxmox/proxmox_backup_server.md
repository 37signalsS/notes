# Proxmox Backup Server (PBS)

## Определения

**Proxmox Backup Server (PBS)** — специализированная платформа корпоративного уровня для инкрементального дедуплицированного резервного копирования виртуальных машин (VM), контейнеров (LXC) и физических хостов. Актуальная ветка — **4.x** (PBS 4.2 на базе Debian 13.4 «Trixie», ядро Linux 7.0, ZFS 2.4).

**Datastore** — логическое хранилище, представляющее собой директорию на файловой системе (ext4/XFS/ZFS), где размещаются дедуплицированные блоки данных (**chunks**) и метаданные.

**Namespace (Пространство имен)** — механизм иерархического разделения данных внутри одного Datastore. Позволяет изолировать бэкапы разных клиентов или отделов, применяя к ним индивидуальные политики прав и хранения.

**pxar** — проприетарный формат архивов Proxmox (Proxmox ARchiver), используемый клиентом `proxmox-backup-client` для хранения файловых данных и их изменений инкрементально, на уровне блоков.

**Снэпшот (Snapshot)** — неизменяемая точка во времени в истории бэкапа. В PBS каждая новая запись создает новый snapshot, ссылающийся на предыдущий; вместе они образуют цепочку инкрементальных изменений.

**Retention Policy (Политика хранения)** — набор правил, определяющих, сколько snapshot'ов и какого типа (`keep-daily`, `keep-weekly`, `keep-monthly`, `keep-yearly`) хранить в рамках одного backup job. При выполнении Prune старые snapshot'ы удаляются по этим правилам.

**Backup Job** — запланированное задание на стороне PVE (или внешнего клиента), которое создает snapshot ВМ/LXC и отправляет его в PBS. В PVE настраивается через GUI или `vzdump` API.

**Sync Job** — задание на стороне PBS, автоматически синхронизирующее данные из одного Datastore в другой (локальный или удаленный PBS). Поддерживает фильтрацию по namespace, сжатие в канале и проверку целостности.

**Client Certificate (Сертификат клиента)** — пара файлов (`key` + `cert`), которую использует PBS для аутентификации клиентов (PVE или `proxmox-backup-client`). При добавлении хранилища в PVE автоматически создается запись в `/etc/pve/priv/shadow.cfg`.

**Keyfile (Файл ключа шифрования)** — опциональный файл с симметричным ключом AES-256, используемый для шифрования бэкапов на стороне клиента. При утере ключа восстановить данные невозможно.

**Immutable Backup (Неизменяемый бэкап)** — режим хранения snapshot'ов, при котором их нельзя удалить или изменить в течение заданного периода (`immutable` флаг в retention policy), даже администратором PBS. Защита от ransomware и insider-угроз.

**Bit Rot** — явление, при котором биты данных на диске плавно деградируют из-за электромагнитных наводок, износа носителя или ошибок firmware. PBS защищается от этого контрольными суммами и задачей Verify.

**Chunk (Чанк)** — минимальный адресуемый блок данных в PBS (по умолчанию ~4 МБ). Один и тот же chunk разных snapshot'ов может храниться в единственном экземпляре за счет глобальной дедупликации.

**Media Pool** — логическая группа ленточных носителей (LTO) в PBS для ротации и инвентаризации при Tape Backup.

**Verify Job** — задание, пересчитывающее контрольные суммы всех chunks указанного snapshot'a и сверяющее их с записанными значениями для обнаружения bit rot и повреждений.

**Prune** — операция логического удаления snapshot'ов, устаревших согласно Retention Policy. После Prune chunks становятся невостребованными и подлежат физическому удалению через Garbage Collection.

## Основные концепции

### Версии и жизненный цикл

- **PBS 4.x** — актуальная мажорная ветка на Debian 13 «Trixie». PBS 4.2 (релиз 29.04.2026) включает ядро Linux 7.0, ZFS 2.4 и значительные улучшения организации данных бэкапов, безопасности и производительности синхронизации, а также работы с S3-backed хранилищами.
- **PBS 3.4** — получает обновления безопасности и критические исправления **до августа 2026** (перекрытие примерно в год после выхода 4.x для плавного перехода).
- **Совместимость клиентов**: бэкапы с PVE 8 на PBS 4 и с PVE 9 на PBS 3 официально поддерживаются. Разрыв в две и более мажорных версии (например, PVE 7 ↔ PBS 4) поддерживается только на условиях best-effort.
- **Обновление 3 → 4**: выполняется отдельно от PVE (см. [Обновление систем Proxmox](./proxmox_updates.md)). Используется чеклист-скрипт `pbs3to4` (с `--full` — все проверки), смена репозиториев Debian на Trixie и `apt dist-upgrade`. Перед обновлением обязательна резервная копия `/etc/proxmox-backup` и проверенный бэкап.
- **Аппаратные требования**: рекомендуется серверное оборудование enterprise-класса с быстрым SSD/NVMe-хранилищем — время отклика HDD замедляет все операции PBS. Установка на Debian, в VM, LXC или совместно с PVE возможна, но официально не рекомендуется (только для экспертов). Официальные минимумы (только для evaluation): 2+ ядра, 2 ГБ RAM, >8 ГБ диск, NIC. Рекомендуется: 4+ ядра, минимум 4 ГиБ RAM (+1 ГиБ на каждый ТиБ хранилища бэкапов), 32 ГиБ+ под ОС на аппаратном RAID с BBU или избыточном ZFS; для хранилища бэкапов — enterprise SSD с защитой от потери питания (PLP).

### Преимущества перед классическим VZDump

В отличие от стандартного механизма `vzdump` в PVE, который создает полные архивы, PBS использует инкрементальный подход:

- **Инкрементальность на уровне блоков**: сохраняются только измененные блоки данных, что позволяет выполнять бэкапы каждые 15–30 минут с минимальной нагрузкой на сеть и диски.
- **Глобальная дедупликация**: одинаковые блоки данных разных VM и бэкапов в рамках одного Datastore хранятся один раз, экономя до ~90% дискового пространства.
- **Live Restore (Живое восстановление)**: VM запускается практически мгновенно, а необходимые данные догружаются с PBS в фоновом режиме во время полного восстановления диска.

### Механизм хранения данных

PBS хранит данные в структуре директорий Datastore:

- **`.chunks/`**: каталог с фактическими данными; файлы чанков именуются по SHA-256 хешу их содержимого. Средний размер чанка — 4 МБ.
- **index-файлы**: индексы, связывающие бэкап с его чанками (по одному на архив/диск).
- **blob-файлы** (`.blob.json`): хранилище метаданных — конфигурация VM, логи, мелочь, не требующая дедупликации.

Целостность данных защищена контрольными суммами (хеши и CRC), которые пересчитываются механизмом Verify для обнаружения «bit rot».

### Шифрование и безопасность

- **Client-side Encryption**: данные шифруются алгоритмом **AES-256 (GCM mode)** на стороне клиента (PVE) перед отправкой по сети. PBS получает только зашифрованные блоки. Для бэкапов VM ключи хранятся в PVE; для `proxmox-backup-client` используется файл ключа (keyfile).
- **Важно**: шифрование включается **при создании Datastore** — для уже существующего Datastore его включить нельзя (необходимо создавать новое хранилище).
- **Ransomware Protection**: поддержка режима **Immutable Backups** (неизменяемые бэкапы) и строгая проверка целостности данных, что защищает от удаления/шифрования бэкапов при компрометации.

### Сценарии Offsite-хранения

- **Sync Jobs**: автоматическая синхронизация данных между двумя PBS (например, из локального офиса в облако). Поддерживаются опции `remove-vanished` (удаление пропавших на источнике) и `verify-verify` (проверка до и после синхронизации). В PBS 4.2 улучшена безопасность и производительность синка.
- **Tape Backup**: нативная поддержка ленточных библиотек (LTO) для реализации правила «3-2-1». Поддержка **Media Pools** и инвентаризации лент.
- **S3-backed хранилища**: в PBS 4.2 значительно улучшена работа с S3-совместимыми объектными хранилищами как удаленным/архивным бэкендом.

### Архитектура PBS

PBS состоит из нескольких ключевых компонентов:

- **proxmox-backup-server** — основной демон, управляющий Datastore, аутентификацией, API и планировщиком задач.
- **Datastore Manager** — отвечает за запись/чтение chunks, применение политик Retention, запуск GC и Verify.
- **HTTP API** — REST-интерфейс, через который PVE и внешние клиенты взаимодействуют с сервером. Все коммуникации идут по HTTPS с mutual TLS.
- **Scheduler (Cron)** — внутренний планировщик, запускающий Backup, Sync, GC, Verify и Maintenance задачи по заданному расписанию.
- **Web UI** — веб-интерфейс на основе Go и современного JS-фреймворка для управления через браузер.

Клиент (PVE или `proxmox-backup-client`) устанавливает TLS-соединение, аутентифицируется по сертификату, после чего выполняет upload/download/restore операции через тот же HTTP API.

### Формат pxar и инкрементальность

pxar-архив содержит два основных элемента:

- **Метаданные** (config, description, ВМ-параметры): хранятся в blob-файлах и изменяются при каждом snapshot.
- **Дисковые данные**: разбиваются на chunks хешированием. При следующем snapshot только измененные chunks отправляются заново; неизмененные переиспользуются по ссылке.

Цепочка snapshot'ов образует дерево: каждый новый snapshot ссылается на предыдущий и добавляет только delta. Это позволяет мгновенно стартовать Live Restore, так как базовый snapshot уже содержит полный образ диска.

### Политики Retention и жизненный цикл данных

**Retention Policy** определяет, какие snapshot'ы хранить постоянно, а какие удалять. Стандартные правила:

- `keep-last`: последние N snapshot'ов
- `keep-daily`: по одному snapshot за последние N дней
- `keep-weekly`, `keep-monthly`, `keep-yearly`: аналогично для недель/месяцев/лет

**Жизненный цикл одного бэкапа:**

1. **Snapshot**: PVE создает снэпшот диска VM/LXC (на уровне хранилища).
2. **Transfer**: данные отправляются на PBS через `proxmox-backup-client`.
3. **Dedup & Store**: PBS сохраняет новые chunks, ссылается на существующие.
4. **Retention Check (Prune)**: по расписанию удаляются snapshot'ы, не подпадающие под Retention.
5. **Garbage Collection**: физически удаляются chunks, на которые не ссылается ни один snapshot.
6. **Verify**: периодически проверяются контрольные суммы chunks на bit rot.

### Immutable Backups и защита от ransomware

Immutable Backup включается через параметр `--immutable` в retention policy. При его наличии PBS запрещает любые операции записи/удаления с snapshot'ом до истечения срока immutable-периода. Это работает даже при компрометации учетной записи администратора PBS, так как блокировка реализована на уровне хранения и проверяется при каждой операции GC и Prune.

## Установка и первоначальная настройка

### Установка PBS через веб-интерфейс

Установка Proxmox Backup Server не вызывает затруднений: установочный интерфейс идентичен PVE. После загрузки с установочного образа:

1. **Лицензионное соглашение**: примите условия лицензии.
2. **Выбор диска**: выберите диск или массив для установки ОС и файловую систему (рекомендуется ZFS или ext4).
3. **Пароль root и почта**: задайте пароль пользователя `root` и адрес электронной почты для системных уведомлений. Простого указания адреса недостаточно — в последующем нужно настроить SMTP-параметры для фактической доставки писем.
4. **Сеть**: выберите основной сетевой интерфейс, задайте имя хоста, IP-адрес, маску, шлюз и DNS-серверы.

> **Рекомендация**: после установки загрузите доверенный SSL-сертификат от Let's Encrypt вместо самоподписанного. См. [ACME и SSL-сертификаты в Proxmox VE](./proxmox_acme_ssl.md).

### Подготовка дисков и монтирование хранилищ

Для хранения резервных копий используйте отдельный диск или раздел. Процедура подготовки:

```bash
# Разметка диска GPT (пример для /dev/sda)
parted /dev/sda -- mkpart primary ext4 0% 100%

# Форматирование раздела
mkfs.ext4 /dev/sda1

# Получение UUID раздела
blkid /dev/sda1
# → UUID="xxx-xxx-xxx"

# Создание точек монтирования
mkdir -p /mnt/backup/lenovo
mkdir -p /mnt/backup/truenas
```

Добавьте записи в `/etc/fstab` для автоматического монтирования при загрузке:

```
UUID=xxx-xxx-xxx /mnt/backup/lenovo ext4 defaults 0 2
truenas.local:/mnt/backup /mnt/backup/truenas nfs defaults,_netdev 0 0
```

Примените изменения:

```bash
systemctl daemon-reload
mount -a
```

> **Важно**: для удаленных хранилищ (NFS, CIFS/SMB) используйте опцию `_netdev`, иначе система может застрять при загрузке, ожидая недоступный ресурс. Убедитесь, что сеть поднята до монтирования.

## Практические сценарии

### Подключение PBS к Proxmox VE через CLI

```bash
# Добавление хранилища PBS в кластер PVE
pvesm add pbs local-backup \
    --server 10.0.0.50 \
    --datastore pool-01 \
    --username backup-user@pbs \
    --password "secret-pass" \
    --fingerprint "AA:BB:CC:..."
# → update storage: 'local-backup'
```

`--fingerprint` — обязательный параметр: SHA-256 отпечаток сертификата PBS-сервера (виден в веб-интерфейсе PBS в разделе Server Administration). Альтернатива в GUI: Datacenter → Storage → Add → Proxmox Backup Server.

### Настройка Namespace через CLI (на стороне PBS)

```bash
# Создание пространства имен для отдела разработки
proxmox-backup-manager datastore namespace create pool-01 dev-team
# → Successfully created namespace 'dev-team'
```

Namespaces позволяют разделять бэкапы по клиентам/отделам в рамках одного Datastore, применяя к каждому свои политики доступа и хранения.

### Резервное копирование физического Linux-сервера

```bash
# Установка клиента и выполнение бэкапа
proxmox-backup-client backup root.pxar:/ --repository backup@pbs@10.0.0.50:pool-01
# → Uploading "root.pxar"
# → Backup finished.
```

Несколько архивов в одном бэкапе и авторизация по переменной окружения:

```bash
export PBS_PASSWORD="your-password"

# Создание бэкапа директорий /etc и /home одним заданием
proxmox-backup-client backup root.pxar:/etc home.pxar:/home \
    --repository backup-user@pbs@10.0.0.50:pool-01
# → Uploading "root.pxar"
# → Uploading "home.pxar"
# → Backup finished.
```

Бэкап с шифрованием (ключ создается заранее в GUI: Server Administration → Keys → Add):

```bash
proxmox-backup-client backup root.pxar:/ \
    --repository backup-user@pbs@10.0.0.50:pool-01 \
    --keyfile /etc/pbs-keyfile
```

Для Debian/Ubuntu-серверов клиент ставится из репозитория «Proxmox Backup Client-only» (рекомендуется пакет `proxmox-backup-client-static`, не зависящий от системных библиотек).

### Создание Datastore и настройка через CLI (на стороне PBS)

```bash
# Создание нового Datastore на разделе /mnt/backup
proxmox-backup-manager datastore create pool-01 /mnt/backup/pool-01
# → Successfully created datastore 'pool-01'

# Просмотр свойств
proxmox-backup-manager datastore list
# → pool-01   /mnt/backup/pool-01   [enabled]

# Изменение описания и флага immutable
proxmox-backup-manager datastore update pool-01 \
    --comment "Primary backup datastore" \
    --keep-last 5
```

**Важно**: шифрование Datastore (`--encryption`) включается только при создании. Для уже существующего Datastore изменить это нельзя — требуется миграция данных.

### Настройка Retention Policy через CLI

```bash
# Создание/изменение политики хранения для namespace
proxmox-backup-manager datastore namespace update pool-01 dev-team \
    --keep-last 7 \
    --keep-daily 14 \
    --keep-weekly 4 \
    --keep-monthly 6 \
    --keep-yearly 2
# → Successfully updated retention for namespace 'dev-team'

# Применение immutable-флага (защита от ransomware)
proxmox-backup-manager datastore namespace update pool-01 critical \
    --keep-last 4 --immutable 7
# → snapshot'ы в namespace 'critical' нельзя удалить в течение 7 дней
```

### Планировщик резервного копирования PVE → PBS

На стороне PVE backup job настраивается через GUI: Datacenter → Backup → Add, либо через CLI:

```bash
# Создание backup job для VM 101 и 102
pvesh create /nodes/pve1/backup \
    --vmid 101,102 \
    --storage local-backup \
    --mode snapshot \
    --schedule "daily-backup" \
    --compress zstd \
    --enable 1

# Список заданий
pvesh get /nodes/pve1/backup
# → {vmid: '101,102', storage: 'local-backup', schedule: 'daily-backup', ...}

# Удаление задания
pvesh delete /nodes/pve1/backup/daily-backup
```

Для LXC контейнеров команда аналогична, в `vmid` указывается ID контейнера.

### Ограничение пропускной способности (Bandwidth Limit)

Для ограничения скорости бэкапов/восстановлений используется параметр `--bwlimit` у `proxmox-backup-client`:

```bash
# Ограничение скорости загрузки 10 МБ/с (8192 КБ/с)
proxmox-backup-client backup root.pxar:/ \
    --repository backup-user@pbs@10.0.0.50:pool-01 \
    --bwlimit 8192

# Или в байтах
proxmox-backup-client backup root.pxar:/ \
    --repository backup-user@pbs@10.0.0.50:pool-01 \
    --bwlimit 10485760
```

В PVE bandwidth limit настраивается в свойствах PBS-хранилища (`Datacenter → Storage → local-backup → Edit → Max Backup Speed`).

### Восстановление отдельных файлов из pxar-архива

pxar можно монтировать через FUSE или распаковывать поэтапно:

```bash
# Установка вспомогательных утилит
apt install -y proxmox-backup-fuse

# Монтирование архива
proxmox-backup-fuse mount \
    root.pxar /mnt/pxar-mount \
    --repository backup-user@pbs@10.0.0.50:pool-01

# Поиск и извлечение нужного файла
find /mnt/pxar-mount -name "*.conf" -ls
cp /mnt/pxar-mount/etc/nginx/nginx.conf /tmp/nginx.conf
fusermount -u /mnt/pxar-mount
```

Альтернативный способ — restore в временный каталог:

```bash
mkdir -p /tmp/pxar-extract
proxmox-backup-client restore root.pxar /tmp/pxar-extract \
    --repository backup-user@pbs@10.0.0.50:pool-01 \
    --restore-path /etc/nginx/nginx.conf=/tmp/nginx.conf
# → Restore finished.
```

### Восстановление конкретного диска из бэкапа VM

При бэкапе ВМ с несколькими дисками каждый диск имеет отдельный pxar. Восстановить можно диск по имени:

```bash
# Список архивов в snapshot
proxmox-backup-client list --repository backup-user@pbs@10.0.0.50:pool-01
# → vm/101/2026-09-15T02:00:00Z/
#       config.json
#       vm-disk-0.raw
#       vm-disk-1.raw

# Восстановление только второго диска
proxmox-backup-client restore vm/101/2026-09-15T02:00:00Z/vm-disk-1.raw \
    /var/lib/vz/images/101/vm-101-disk-1.raw \
    --repository backup-user@pbs@10.0.0.50:pool-01
```

### Управление сертификатами и ключами клиента

```bash
# Генерация нового ключевого файла (на стороне PBS)
proxmox-backup-manager key create /root/client.key

# Экспорт сертификата для импорта в PVE
proxmox-backup-manager cert get /root/client.crt

# На стороне PVE: добавление хранилища с явным путем к ключу
pvesm add pbs local-backup \
    --server 10.0.0.50 \
    --datastore pool-01 \
    --username backup-user@pbs \
    --password "secret-pass" \
    --fingerprint "AA:BB:CC:..." \
    --keyfile /root/client.key

# Проверка валидности сертификата
openssl x509 -in /root/client.crt -noout -dates -subject
# → notBefore=...
# → notAfter=...
# → subject= /CN=backup-user@pbs
```

### Настройка Sync Job между двумя PBS

```bash
# На целевом PBS: создание remotes-записи
proxmox-backup-manager remote create offsite-backup \
    --server offsite.proxmox.local \
    --datastore pool-01 \
    --username sync-user@pbs \
    --password "sync-pass" \
    --fingerprint "AA:BB:CC:..."

# Создание Sync Job
proxmox-backup-manager sync create offsite-backup-pool-01 \
    --remote offsite-backup \
    --datastore pool-01 \
    --schedule "0 2 * * *" \
    --remove-vanished 1 \
    --verify-new 1

# Применение к конкретному namespace
proxmox-backup-manager sync update offsite-backup-pool-01 \
    --namespace dev-team

# Просмотр статуса последней синхронизации
proxmox-backup-manager sync list
# → offsite-backup-pool-01   remote: offsite-backup/pool-01   ...
```

### Мониторинг и оповещения

```bash
# Проверка статуса активных задач
proxmox-backup-manager task list --limit 20

# Просмотр логов PBS
journalctl -u proxmox-backup-server -f

# Проверка свободного места на Datastore
proxmox-backup-manager datastore status pool-01

# Создание дампа состояния для анализа
proxmox-backup-manager debug dump /tmp/pbs-debug.tar.gz

# Настройка email-оповещений (через GUI: Dashboard → Options → Email)
# или через конфиг /etc/proxmox-backup/conf.d/notification.cfg
```

### Verify и Prune через CLI (ручное выполнение)

```bash
# Проверка конкретного snapshot
proxmox-backup-manager snapshot verify pool-01 vm/101/2026-09-15T02:00:00Z
# → Verifying snapshot...
# → Verified 1240 chunks (0 corrupted)

# Prune по Retention Policy
proxmox-backup-manager snapshot prune pool-01 --dry-run
# → Would prune 3 snapshots (1.2 GB)

proxmox-backup-manager snapshot prune pool-01
# → Pruned 3 snapshots (1.2 GB)

# Запуск GC после Prune
proxmox-backup-manager datastore garbage-collection pool-01
# → Removed 3800 unreferenced chunks (2.1 GB)
```

### Просмотр содержимого бэкапа (Dry-run / list)

```bash
# Детальный список snapshot'ов для VM
proxmox-backup-manager snapshot list pool-01 vm/101
# → vm/101/2026-09-15T02:00:00Z
# → vm/101/2026-09-14T02:00:00Z
# → vm/101/2026-09-13T02:00:00Z

# Размер конкретного snapshot
proxmox-backup-manager snapshot size pool-01 vm/101/2026-09-15T02:00:00Z
# → 12.4 GiB (logical), 3.2 GiB (deduplicated)
```

### Восстановление VM из резервной копии

1. **GUI (рекомендуется)**: PVE → Datacenter → Storage → содержимое хранилища PBS → выбрать бэкап VM → **Restore**. При восстановлении можно переназначить целевое хранилище и ID VM.
2. **Live Restore**: в диалоге восстановления доступен запуск VM до полной загрузки данных — система поднимет диски из PBS по мере необходимости, а восстановление продолжит в фоне.
3. **CLI для файловых архивов** (на сервере с клиентом):

```bash
# Восстановление архива root.pxar в локальный каталог /tmp/restore
proxmox-backup-client restore root.pxar /tmp/restore \
    --repository backup-user@pbs@10.0.0.50:pool-01
# → Restore finished.
```

### Создание Datastore через GUI

После монтирования дисков и разделов в PBS перейдите в раздел **Datastore → Add Datastore**.

1. Задайте название Datastore и выберите путь к подготовленной директории.
2. Если вы подключаете уже существующее хранилище с бэкапами, перейдите во вкладку **Advanced** и установите галочку **Reuse existing datastore**. Эта опция позволяет использовать уже существующую папку с бэкапами как Datastore, не создавая его заново.
3. GC Schedule и Prune Schedule можно оставить пустыми — их мы настроим позже.

Для нового Datastore достаточно задать название и прописать абсолютный путь до директории хранения.

> **Важно**: не изменяйте содержимое Datastore вручную. Удаляйте старые резервные копии только через задачи Prune, чтобы избежать повреждения индексов.

### Подключение PBS к Proxmox VE через GUI

В Proxmox VE Datastore не подключается напрямую как диск. Подключается сам PBS-сервер, а Datastore выбирается уже внутри него.

В веб-интерфейсе PVE: **Datacenter → Storage → Add → Proxmox Backup Server**.

Заполните параметры:

| Поле | Значение |
| :--- | :--- |
| **Server** | IP-адрес или DNS-имя PBS |
| **Datastore** | Имя Datastore из PBS (не путь в файловой системе) |
| **Username** | Рекомендуется отдельный пользователь (например, `backup@pbs`) |
| **Password** | Пароль пользователя PBS |
| **Fingerprint** | SHA-256 отпечаток сертификата PBS (Dashboard → Show Fingerprint) |

После добавления в PVE появится новое хранилище, которое можно использовать для backup VM и CT.

### Настройка задач резервного копирования, Prune, GC и Verify через GUI

#### Backup Job в PVE

В PVE перейдите: **Datacenter → Backup → Add**.

Настройте:
- **Node**: узел, с которого будут создаваться бэкапы
- **Schedule**: расписание (например, `daily` для ежедневных бэкапов)
- **VM/CT**: список виртуальных машин и контейнеров
- **Storage**: хранилище PBS, подключенное на предыдущем шаге
- **Mode**: `snapshot` для running VM, `suspend` для выключенных
- **Compress**: `zstd` (рекомендуется) или `lzo`

Теперь каждые 24 часа PVE будет создавать копии выбранных ресурсов и сохранять их на PBS.

#### Prune Job (политика хранения)

В веб-интерфейсе PBS: **Datastore → Prune → Add**.

Задайте:
- **Schedule**: например, `daily` или cron `0 2 * * *`
- **Keep options**: сбалансированная политика — `keep-daily: 7`, `keep-weekly: 4`, `keep-monthly: 6`

Prune удаляет только ссылки на snapshot'ы, но не физические данные сразу.

#### Garbage Collection

В PBS: **Datastore → Garbage Collection → Add**.

Рекомендуемое расписание — еженедельно, например, `weekly` или `0 3 * * 0` (каждое воскресенье ночью).

GC удаляет физически неиспользуемые chunks, оставшиеся после Prune.

#### Verification Job

В PBS: **Datastore → Verification → Add**.

Задайте:
- **Schedule**: для домашней лаборатории достаточно `monthly`, для production — `weekly` или `bi-weekly`
- **Scope**: можно выбрать весь Datastore или конкретный snapshot

Verify пересчитывает контрольные суммы chunks для обнаружения bit rot и повреждений.

#### Правильный порядок задач

Соблюдайте последовательность:
1. **Prune** — логическое удаление старых snapshot'ов
2. **Garbage Collection** — физическое удаление неиспользуемых chunks
3. **Verification** — проверка целостности данных

### Настройка Sync Jobs через GUI

Sync Jobs используются для репликации данных между Datastore (например, из локального SSD на удаленный NAS).

В PBS: **Datastore → Sync Jobs → Add**.

Настройте:
- **Remote**: выберите удаленный PBS или локальный Datastore-цель
- **Datastore**: исходный Datastore для синхронизации
- **Schedule**: после завершения локальных бэкапов, не раньше 04:00
- **Remove vanished**: удалять на цели snapshot'ы, пропавшие на источнике
- **Verify new**: проверять целостность новых данных после синхронизации

Конфигурация Sync Jobs хранится в `/etc/proxmox-backup/sync.cfg`. Управлять заданиями можно также через CLI: `proxmox-backup-manager sync-job`.

### Стратегия горячих и холодных Datastore

Один PBS может обслуживать несколько Datastore с разными характеристиками:

| Datastore | Назначение | Носитель | Retention |
| :--- | :--- | :--- | :--- |
| `fast-backup` | Ежедневные бэкапы, быстрое восстановление | SSD/NVMe | `keep-daily: 7`, `keep-weekly: 4` |
| `archive` | Долгосрочное хранение, offsite | HDD/NAS/Tape | `keep-monthly: 12`, `keep-yearly: 3` |

Пример конфигурации:

```bash
# Локальный SSD для быстрых бэкапов
proxmox-backup-manager datastore create fast-backup /mnt/ssd/pbs

# Удаленный NFS (например, TrueNAS) для долгосрочного хранения
proxmox-backup-manager datastore create archive /mnt/nfs/truenas
```

Sync Job настраивается для переноса бэкапов из `fast-backup` в `archive` по расписанию.

> **Рекомендация**: никогда не храните Datastore на том же физическом диске, что и система или VM. Используйте отдельный SSD-массив для горячих бэкапов и отдельный HDD/NAS-массив для архивных копий.

## Обслуживание и диагностика

### Жизненный цикл данных (Maintenance)

1. **Prune**: удаление индексов старых бэкапов (логическое удаление) согласно политике хранения (Retention).
2. **Garbage Collection (GC)**: физическое удаление чанков, на которые больше нет ссылок. Рекомендуется запускать раз в неделю.
3. **Verify**: пересчет контрольных сумм всех чанков для предотвращения «bit rot».

**Запуск GC и Verify:**
```bash
proxmox-backup-manager datastore garbage-collection pool-01
# → Start garbage collection on "pool-01"
# → Removed 12500 chunks (5.2 GB)

proxmox-backup-manager datastore verify pool-01
# → Start verify on "pool-01"
```

Регулярность задается планировщиком: в GUI PBS каждый Datastore имеет раздел Tasks, где настраиваются Verify Jobs и GC Jobs с расписанием (cron).

### Тонкая настройка Garbage Collection

GC может потреблять значительный ресурс диска и CPU во время работы. Рекомендации:

- Запускайте GC не чаще 1 раза в неделю для активно используемых Datastore.
- Используйте `--limit` для ограничения количества обрабатываемых chunks за один запуск, чтобы снизить нагрузку:
  ```bash
  proxmox-backup-manager datastore garbage-collection pool-01 --limit 5000
  ```
- При наличии наislice-нагрузки планируйте GC на ночные часы.
- Следите за статусом в GUI: Datastore → Tasks → Garbage Collection. Выход `Removed X chunks` — нормальный. Если GC не удаляет chunks — проверьте, нет ли зависших snapshot'ов.

### Интерпретация результатов Verify

```bash
proxmox-backup-manager datastore verify pool-01
# → Verified 12450 chunks (0 corrupted)

# Или проверка конкретного snapshot
proxmox-backup-manager snapshot verify pool-01 vm/101/2026-09-15T02:00:00Z
# → Verified 1240 chunks (0 corrupted)
```

Если Verify находит corrupted chunks — PBS автоматически пытается восстановить данные из реплик (если snapshot имеет несколько links). Если восстановление невозможно — snapshot помечается как `corrupted` и требует повторного бэкапа.

### Maintenance Mode (режим обслуживания)

Перевод Datastore в режим **read-only** не позволяет начинать новые бэкапы во время работ (например, при обновлении), сохраняя доступ к уже существующим:

```bash
# Включение read-only режима
proxmox-backup-manager datastore update pool-01 --maintenance-mode read-only
# Отключение режима
proxmox-backup-manager datastore update pool-01 --delete maintenance-mode
```

То же доступно в GUI: Datastore → Options.

### Проверка состояния дисков и хранилищ

```bash
proxmox-backup-manager datastore status pool-01
# → {
# →   "total": 1000200000000,
# →   "used": 450000000000,
# →   "avail": 550200000000
# → }
```

Для мониторинга состояния физических дисков на хосте PBS используйте стандартные утилиты:

```bash
# SMART-атрибуты
smartctl -a /dev/nvme0

# Файловая система
df -h /mnt/backup/pool-01

# Zpool статус (если Datastore на ZFS)
zpool status
```

### Диагностика клиента и синхронизации

```bash
# Список резервных копий клиента (по группам)
proxmox-backup-client status --repository backup-user@pbs@10.0.0.50:pool-01
# → Datastore "pool-01":
# →   Count: 12, Total size: ...
# →     snapshot: host/server/2026-07-... 12.3 GiB

# Список заданий синхронизации (Sync Jobs)
proxmox-backup-manager sync list
```

### Чтение логов PBS

```bash
# Основной лог демона
journalctl -u proxmox-backup-server -f

# Лог конкретной задачи
proxmox-backup-manager task list --limit 5
proxmox-backup-manager task log <task-id>

# Логи веб-интерфейса
cat /var/log/proxmox-backup/proxmox-backup-api.log
```

## Диагностика и устранение неполадок

### Ошибка аутентификации / сертификат не принят

**Симптомы**: `401 Unauthorized`, `TLS handshake error`, `certificate verify failed`.

**Причины и решения:**

1. **Неверный fingerprint**: убедитесь, что отпечаток сертификата PBS совпадает с тем, что указан в PVE при добавлении хранилища. Проверьте:
   ```bash
   openssl x509 -in /etc/proxmox-backup/proxy.crt -noout -fingerprint -sha256
   ```
2. **Истекший сертификат**: по умолчанию PBS генерирует сертификат на 10 лет. Если срок истек — перевыпустите через GUI: Server Administration → Certificates → Renew.
3. **Клиентский сертификат удален на PBS**: при добавлении хранилища в PVE создается запись о клиенте в PBS. Если она удалена — пересоздайте хранилище в PVE.

### Бэкап не запускается / пропускается

**Симптомы**: Backup Job статус `skipped` или не появляется в планировщике.

**Причины и решения:**

1. **Datastore в Maintenance Mode**: проверьте статус:
   ```bash
   proxmox-backup-manager datastore status pool-01
   # → maintenance: read-only
   ```
   Отключите режим или переназначьте backup job на другой Datastore.
2. **Нет места на Datastore**: `proxmox-backup-manager datastore status pool-01` покажет `avail`. Увеличьте хранилище или удалите старые snapshot'ы.
3. **VM не запущена в snapshot-режиме**: для `suspend` mode бэкап работает только при выключенной ВМ. Используйте `snapshot` mode для running ВМ.
4. **Ошибка QEMU Guest Agent**: если AGENT не установлен или не отвечает, PBS не может создать консистентный снапшот. Установите `qemu-guest-agent` внутри ВМ и запустите сервис.

### Медленная скорость бэкапа/восстановления

**Диагностика:**

```bash
# Измерение скорости через iperf3 между PVE и PBS
iperf3 -c 10.0.0.50 -R

# Проверка загрузки диска на PBS
iostat -x 1

# Проверка размера чанков (по умолчанию 4MB)
cat /etc/proxmox-backup/datastore.cfg | grep chunk
```

**Решения:**

- Увеличьте `chunk-size` при создании Datastore (с 4MB до 8MB или 16MB) для больших файлов с низкой дедупликацией.
- Отключите сжатие на уровне Datastore, если CPU узла PBS является узким местом.
- Используйте отдельный NIC/NVMe для трафика бэкапов.
- Настройте `--bwlimit` на клиенте для избежания congestion в рабочее время.

### GC не освобождает место

**Симптомы**: после Prune место на диске не высвобождается.

**Причины и решения:**

1. **Snapshot'ы имеют зависшие references**: выполните `proxmox-backup-manager snapshot list` и проверьте, нет ли snapshot'ов в состоянии `invalid`. Удалите их вручную:
   ```bash
   proxmox-backup-manager snapshot remove pool-01 vm/101/bad-snapshot --force
   ```
2. **GC завершился с ошибкой**: проверьте логи `journalctl -u proxmox-backup-server`. Часто причина — права на файлы или монтирование read-only.
3. **Bit rot повреждение chunks**: Verify пометит поврежденные chunks, но GC не удалит их, пока snapshot ссылается на них. Удалите поврежденный snapshot и запустите GC повторно.

### Ошибки при Verify / Bit rot

```bash
# Проверка конкретного snapshot
proxmox-backup-manager snapshot verify pool-01 vm/101/2026-09-15T02:00:00Z

# Если snapshot поврежден — перенаправьте Verify Job на проверку всего Datastore
proxmox-backup-manager datastore verify pool-01 --all
```

Если Verify находит corrupted chunks, PBS пытается восстановить данные из других snapshot'ов в цепочке. Если восстановление невозможно — snapshot требует повторного бэкапа.

### Сетевая ошибка / разрыв соединения

```bash
# Проверка доступности API PBS
curl -k https://10.0.0.50:8007/api2/json/version

# Проверка TLS-рукопожатия
openssl s_client -connect 10.0.0.50:8007 -servername pbs.local
```

Убедитесь, что:

-防火墙/iptables на PBS разрешает порт 8007 (TCP).
- DNS или /etc/hosts на PVE корректно разрешают имя PBS.
- Нет аппаратного firewall между сетями.

### Datastore переполнен / неожиданный рост

**Диагностика:**

```bash
# Анализ использования места
proxmox-backup-manager datastore status pool-01
du -sh /mnt/backup/pool-01/.chunks/* | sort -rh | head -20
```

**Причины:**

- Отсутствие Prune по Retention Policy.
- Включено хранение слишком большого количества daily/weekly snapshot'ов.
- Большой объем изменяемых данных (базы данных, журналы), дедупликация не работает эффективно. Решение: увеличить chunk-size или использовать exclude-правила.

## Лучшие практики

### Стратегия бэкапов 3-2-1

- **3** копии данных: рабочая копия + локальный бэкап + offsite.
- **2** разных носителя: SSD/NVMe для быстрого доступа + HDD/LTO для долгого хранения.
- **1** копия offsite: второй PBS в другом здании или ленточный архив.

### Рекомендации по Retention Policy

- Для критичных ВМ: `keep-daily 7`, `keep-weekly 4`, `keep-monthly 12`, `keep-yearly 3`.
- Для dev/test сред: `keep-last 7`, `keep-daily 3`.
- Включите `--immutable 7` для namespace'ов с критичными данными для защиты от ransomware.

### Проектирование хранилища

- **Не храните Datastore на том же физическом диске, что и PVE или VM**. Используйте отдельный NVMe-массив или JBOD.
- Для ZFS: используйте RAIDZ2/RAIDZ3 с hot-spare и регулярный scrub (`zpool scrub pool-01`).
- Для ext4/XFS: обеспечьте мониторинг свободного места и автоматическое расширение LVM/раздела.

### Сетевое проектирование

- Выделите отдельный VLAN/subnet для трафика бэкапов (например, 10.0.50.0/24).
- Используйте bond (LACP) между PVE и PBS для отказоустойчивости и увеличения пропускной способности.
- При больших кластерах (>20 узлов) используйте 10/25 GbE между PVE и PBS.

### Управление ключами и сертификами

- Храните `/etc/proxmox-backup/` на PBS и `/etc/pve/` на PVE в системе контроля версий (git) или экспортируйте в KeePass/ vault.
- Периодически тестируйте восстановление из резервной копии конфигурации PBS (`/etc/proxmox-backup/`).
- При компрометации PBS — немедленно перевыпустите все сертификаты через GUI.

### Планирование задач

- **GC**: 1 раз в неделю, в низкоспорный период (воскресенье 02:00).
- **Verify**: ежедневно для одного Datastore, еженедельно для всех.
- **Sync Jobs**: после завершения локальных бэкапов, не раньше 04:00.
- **Maintenance Mode**: используйте при обновлении PBS или замене дисков, а не при штатной работе.

### Тестирование восстановления

- Раз в квартал выполняйте восстановление хотя бы одной VM из PBS на тестовый узел.
- Проверяйте восстановление single-file из pxar.
- Проверяйте Live Restore: запускайте VM до полного завершения восстановления и убеждайтесь, что работа продолжается.

### Мониторинг

- Настройте алерты на: свободное место Datastore (<20%), ошибки GC/Verify (>0), статус Sync Job (failed), срок действия сертификатов (<30 дней).
- Используйте `proxmox-backup-manager debug dump` для отправки в поддержку Proxmox при проблемах.

### Безопасность

- Никогда не открывайте порт 8007 в интернет. Используйте VPN илиTailscale/ZeroTier для удаленного доступа.
- Отключите root-login через SSH на PBS и используйте ключи.
- Включите immutable backups для namespace'ов с критичными данными.
- Регулярно обновляйте PBS: `apt update && apt dist-upgrade` на PBS отдельно от PVE.

### Документирование

- Фиксируйте Retention Policy для каждого namespace'а в отдельном runbook.
- Документируйте расположение Datastore, размер массивов, сроки GC/Verify.
- Ведите changelog изменений политик бэкапов.

## Граничные случаи

### Кросс-версионная совместимость

- **PVE 8 → PBS 4**: официально поддерживается.
- **PVE 9 → PBS 3**: официально поддерживается до августа 2026.
- **PVE 7 → PBS 4**: поддерживается на условиях best-effort. Возможны ошибки восстановления новых snapshot'ов. Рекомендуется промежуточная миграция через vzdump.

### Большие файлы (>4 MB chunk size)

При бэкапе ВМ с образами дисков >100 GB каждый chunk (4 MB по умолчанию) содержит много нулевых блоков. Если дедупликация неэффективна, увеличьте chunk-size:

```bash
# При создании Datastore
proxmox-backup-manager datastore create pool-01 /mnt/backup/pool-01 --chunk-size 16777216
# → chunk-size: 16 MB
```

Миграция существующего Datastore на другой chunk-size невозможна — требуется создание нового Datastore и повторный бэкап.

### Прерывание сети во время бэкапа

`proxmox-backup-client` поддерживает возобновление (resume). При разрыве соединения повторный запуск с тем же snapshot продолжит загрузку с места разрыва, а не с начала. Однако убедитесь, что snapshot не был удален на PBS в промежутке (Prune).

### Datastore на ZFS vs XFS/ext4

- **ZFS**: предпочтительно для PBS из-за checksum на уровне блоков, что дополняет Verify PBS. Минус: высокое потребление RAM (1 GB на 1 TB данных минимум).
- **XFS/ext4**: проще в администрировании, меньше потребляет RAM, но нет встроенных checksum для bit rot. В этом случае Verify PBS становится критически важным.

### Параллельные backup jobs

PBS и PVE поддерживают несколько одновременных backup jobs. Однако:

- Каждый job потребляет CPU на сжатие и TLS.
- Рекомендуется лимитировать количество одновременных бэкапов через PVE (`Datacenter → Options → Max Backups`).
- Для ленточных библиотек PBS обрабатывает только один поток записи за раз.

### Восстановление на узел с другой версией PVE

- **PVE 8 → PBS 4 → PVE 9**: поддерживается, но используйте GUI restore с переназначением storage, так как CLI `qmrestore` может потребовать обновления конфига ВМ.
- **PVE 7 → PBS 3 → PVE 8**: возможна ошибка `Unsupported backup format`. Решение: временно установите PBS 4 или используйте vzdump-архив.

### Tape Backup и Media Pool

```bash
# Создание Media Pool
proxmox-backup-manager media-pool create tape-pool /dev/nst0

# Инвентаризация ленты
proxmox-backup-manager media-pool inventory tape-pool

# Запись бэкапа на ленту
proxmox-backup-manager tape backup pool-01 --media-pool tape-pool
```

Tape Backup требует наличия LTO-устройства, доступного напрямую на хосте PBS (пасс-through или PCI passthrough).

### Низкая пропускная способность канала

Для восстановления через канал <100 Мбит/с используйте:

```bash
proxmox-backup-client restore vm/101/2026-09-15T02:00:00Z \
    /var/lib/vz/images/101/vm-101-disk-0.raw \
    --repository backup-user@pbs@10.0.0.50:pool-01 \
    --bwlimit 12288 \
    --io-timeout 60
```

Увеличение `--io-timeout` предотвращает разрывы при высокой задержке.

### Резервное копирование ВМ с высокой нагрузкой на диск

Если ВМ выполняет интенсивную запись (базы данных, логи), снапшот может занять много времени или вызвать торможение. Решения:

- Используйте `fsfreeze` внутри ВМ через QEMU Guest Agent для консистентного снапшота файловой системы.
- Для databases: используйте встроенные инструменты бэкапа (mysqldump, pg_dump) вместо полного дискового бэкапа, либо комбинируйте с логированием WAL.
- Увеличьте частоту бэкапов, но уменьшайте Retention Policy, чтобы не перегружать PBS.

### Cross-storage восстановление

При восстановлении ВМ на узел с другим типом хранилища (например, Ceph → ZFS) PBS сохраняет диск в формате `raw`. Дальнейшее преобразование (raw → qcow2) выполняется через `qm` или `qemu-img` на целевом узле.

### Смена MAC/VIF после клонирования restored VM

При восстановлении ВМ из бэкапа на другой узел MAC-адрес и сетевой интерфейс автоматически подтягиваются из `config.json` snapshot'а. Если возникает конфликт MAC:

```bash
# Проверка MAC в конфиге
proxmox-backup-manager snapshot get pool-01 vm/101/2026-09-15T02:00:00Z config.json

# Перезапись MAC при восстановлении
qm set 101 --net0 virtio=XX:XX:XX:XX:XX:XX,bridge=vmbr0
```

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Хранилища и Ceph в Proxmox](./proxmox_storage.md)
