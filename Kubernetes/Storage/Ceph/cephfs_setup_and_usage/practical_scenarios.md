# CephFS: Практические сценарии

## Определения

**Subvolume (Субтом)** — логическая абстракция над директорией CephFS, предоставляющая изолированное пространство для хранения. Позволяет управлять квотами, снапшотами и путями через специализированный CLI. Является стандартом для интеграции с Kubernetes (CSI).

**Clone (Клон)** — полная копия субтома, создаваемая из его снапшота. Используется для быстрого развертывания новых сред (например, копирование PersistentVolume в K8s). Клонирование является асинхронной операцией — данные копируются фоново.

**Keyring** — файл, содержащий имя пользователя и его криптографический ключ аутентификации в формате CephX (обычно `/etc/ceph/ceph.client.<user>.keyring`).

**Secretfile** — файл, содержащий исключительно "сырой" (raw) ключ в кодировке base64. Используется модулем ядра Linux при монтировании, чтобы избежать передачи ключа в открытом виде через аргументы командной строки.

**MDS Caps (Capabilities)** — набор криптографически подписанных разрешений, выдаваемых клиенту для работы с метаданными. Примеры: `allow rw path=/data` (полный доступ к директории), `allow r` (только чтение).

**Subvolumegroup (Группа субтомов)** — контейнер для логической группировки субтомов. Позволяет применять общие политики (квоты, снапшоты) ко всем субтомам в группе одновременно.

---

## Предварительные требования

Для выполнения команд в данном разделе необходимо:

- **Кластер Ceph**: Версия **v16 (Quincy)** или выше (рекомендуется **v20+**). Кластер должен быть полностью развернут и находиться в состоянии `HEALTH_OK` или `HEALTH_WARN` (без критических ошибок).
- **Пулы**: Пулы метаданных и данных для CephFS уже созданы и привязаны к приложению (см. [Создание ФС](#1-создание-и-базовая-настройка-фс)).
- **Доступ**: Узел управления с установленным пакетом `ceph-common` и правами `admin` или `cephfs-admin` (в CephX keyring).
- **Клиент**: Для монтирования — установленный модуль ядра `ceph` (Kernel Driver) или `ceph-fuse` (FUSE Client).
- **Сеть**: Доступность портов **3300** (Messenger v2.1) и/или **6789** (Messenger v1) между клиентами и MDS/OSD.

---

## Основные концепции

### Жизненный цикл управления CephFS

1.  **Инфраструктурный уровень**: Создание пулов данных (с поддержкой EC) и метаданных, инициализация файловой системы, декларативное развертывание MDS через оркестратор.
2.  **Уровень управления (Control Plane)**:
    *   *Современный подход (2026)*: Использование модуля `volumes` для создания субтомов, групп и управления их жизненным циклом (включая клонирование).
    *   *Классический подход*: Ручное создание директорий и установка прав/квот через расширенные атрибуты (`xattrs`).
3.  **Уровень доступа**: Выделение пользователей CephX со строгим ограничением по пути (Path-based restriction).
4.  **Уровень потребления**: Монтирование через Kernel Driver (рекомендуется), FUSE или автоматизированно через CSI-драйвер.

### Протоколы Messenger v1 против v2.1

*   **v1 (порт 6789)**: Классический протокол без криптографической защиты. Устаревший, не рекомендуется для production.
*   **v2.1 (порт 3300)**: Современный стандарт. Поддерживает режимы `crc` (целостность данных) и `secure` (полное AES-GCM шифрование трафика "на лету"). Рекомендуется для всех новых инсталляций.

---

## Практические сценарии

### 1. Создание и базовая настройка ФС

#### Создание пулов и активация (с Erasure Coding)

Для пулов метаданных всегда используется репликация (быстрые SSD/NVMe). Для пулов данных в современных инсталляциях часто используют Erasure Coding (EC).

```bash
# Пул метаданных (строго репликация, например size=3)
ceph osd pool create cephfs_metadata 64 replicated
# → pool 'cephfs_metadata' created

# Пул данных (Erasure Coding для экономии места)
ceph osd pool create cephfs_data 128 erasure
# → pool 'cephfs_data' created

# КРИТИЧНО для CephFS: Разрешить перезапись объектов в EC пуле
ceph osd pool set cephfs_data allow_ec_overwrites true
# → set 'cephfs_data' allow_ec_overwrites to true

# Активация приложения
ceph osd pool application enable cephfs_data cephfs
# → enabled application 'cephfs' on pool 'cephfs_data'
ceph osd pool application enable cephfs_metadata cephfs
# → enabled application 'cephfs' on pool 'cephfs_metadata'
```

**Валидация:** Пулы созданы и привязаны к приложению:

```bash
ceph osd pool ls detail | grep cephfs
# → pool 1 'cephfs_metadata' ... application cephfs
# → pool 2 'cephfs_data' ... application cephfs
```

#### Инициализация файловой системы и MDS

```bash
# Создание ФС (первым указывается пул метаданных)
ceph fs new mycephfs cephfs_metadata cephfs_data
# → new fs with metadata pool 2 and data pool 1

# Декларативное развертывание MDS через cephadm (например, 3 демона)
ceph orch apply mds mycephfs --placement="3"
# → Scheduled mds.mycephfs deployment...

# Включение режима standby-replay для мгновенного failover
ceph fs set mycephfs allow_standby_replay true
# → set 'allow_standby_replay' to 'true' for 'mycephfs'
```

**Валидация:** ФС создана, MDS активны:

```bash
ceph fs status
# → mycephfs
# →   ...
# → =====  =====  =====
# → E  0/0/1  up

ceph mds stat
# → mycephfs:1 {0:up=active} 2:up=standby
```

### 2. Современное управление через Субтомы (Subvolumes)

Рекомендуемый метод для новых инсталляций, контейнерных сред и автоматизации.

#### Работа с группами и томами

```bash
# Создание группы (например, логическая группировка "project_alpha")
ceph fs subvolumegroup create mycephfs project_alpha
# → Analyzing group name... (успешно)

# Создание субтома с жесткой квотой (50 ГБ)
ceph fs subvolume create mycephfs user_data --group_name project_alpha --size 53687091200
# → Analyzing parameters...

# Создание субтома с моделью доступа (mode) и владельцем
ceph fs subvolume create mycephfs shared_data --group_name project_alpha \
  --mode 0770 --uid 1000 --gid 1000

# Получение реального пути на диске (нужен для монтирования клиентом)
ceph fs subvolume getpath mycephfs user_data --group_name project_alpha
# → /volumes/project_alpha/user_data/uuid...
```

#### Информация о субтоме и список субтомов

```bash
# Просмотр информации о конкретном субтоме
ceph fs subvolume info mycephfs user_data --group_name project_alpha
# → {
# →   "atime": ...,
# →   "bytes_quota": 53687091200,
# →   "created_at": ...,
# →   "uid": 0,
# →   "gid": 0,
# →   "mode": "drwxr-xr-x",
# →   "path": "/volumes/project_alpha/user_data/uuid..."
# → }

# Просмотр списка всех субтомов в группе
ceph fs subvolume ls mycephfs --group_name project_alpha
# → [
# →   {"name": "user_data"},
# →   {"name": "shared_data"}
# → ]

# Просмотр всех групп субтомов
ceph fs subvolumegroup ls mycephfs
# → [
# →   {"name": "project_alpha"}
# → ]
```

#### Управление квотами и размером

```bash
# Установка/изменение квоты на объем (например, 100 ГБ)
ceph fs subvolume resize mycephfs user_data --group_name project_alpha --size 107374182400

# Просмотр текущего использования (quotas и фактический размер)
ceph fs subvolume info mycephfs user_data --group_name project_alpha --format json | jq '.bytes_quota'
# → 107374182400

# Удаление квоты (unlimited)
ceph fs subvolume resize mycephfs user_data --group_name project_alpha --size -1
```

**Важно:** Квоты на субтомах — cooperative. Клиент проверяет лимит локально перед записью. Задержка обновления может достигать 30 секунд. Для строгих лимитов используйте application-level проверки.

#### Снапшоты и Клонирование субтомов

```bash
# 1. Создание снапшота субтома
ceph fs subvolume snapshot create mycephfs user_data snap_v1 --group_name project_alpha
# → Snapshot 'snap_v1' created successfully

# 2. Просмотр списка снапшотов
ceph fs subvolume snapshot ls mycephfs --group_name project_alpha
# → [
# →   {"name": "snap_v1"}
# → ]

# 3. Информация о конкретном снапшоте
ceph fs subvolume snapshot info mycephfs user_data snap_v1 --group_name project_alpha
# → {
# →   "created_at": ...,
# →   "has_pending_clones": "no",
# →   "name": "snap_v1"
# → }

# 4. Создание независимого клона из снапшота (асинхронная операция)
ceph fs subvolume snapshot clone mycephfs user_data snap_v1 clone_data --group_name project_alpha
# → Volume clone created successfully

# 5. Проверка статуса клонирования (должно быть 'complete')
ceph fs clone status mycephfs clone_data --group_name project_alpha
# → {
# →   "status": "complete",
# →   "status_modifed_at": ...
# → }
```

#### Удаление субтомов и групп

```bash
# Удаление снапшота
ceph fs subvolume snapshot rm mycephfs user_data snap_v1 --group_name project_alpha

# Удаление клона (сначала убедитесь, что клон завершен)
ceph fs clone status mycephfs clone_data --group_name project_alpha
ceph fs subvolume rm mycephfs clone_data --group_name project_alpha

# Удаление субтома (сначала удалите все снапшоты и клоны)
ceph fs subvolume rm mycephfs user_data --group_name project_alpha

# Удаление группы (сначала удалите все субтомы в группе)
ceph fs subvolumegroup rm mycephfs project_alpha
```

### 3. Классическое управление (Manual Path & Xattrs)

Используется для тонкой настройки существующих или специфических директорий.

```bash
# 1. Монтируем корень ФС как администратор
sudo mount -t ceph :/ /mnt/cephfs -o name=admin,secretfile=/etc/ceph/admin.secret
# → mount: /mnt/cephfs: mount point already mounted or busy. (если уже смонтировано)

# 2. Создаем структуру
sudo mkdir -p /mnt/cephfs/legacy_app/data

# 3. Установка квот через атрибуты (клиентские ОС проверяют их асинхронно)
# Квота на объем (10 ГБ)
setfattr -n ceph.quota.max_bytes -v 10737418240 /mnt/cephfs/legacy_app/data
# Квота на количество файлов (1 млн)
setfattr -n ceph.quota.max_files -v 1000000 /mnt/cephfs/legacy_app/data

# 4. Проверка установленных квот
getfattr -n ceph.quota.max_bytes /mnt/cephfs/legacy_app/data
# → ceph.quota.max_bytes="10737418240"
getfattr -n ceph.quota.max_files /mnt/cephfs/legacy_app/data
# → ceph.quota.max_files="1000000"

# 5. Установка владельца и прав (аналог chown/chmod)
sudo chown 1000:1000 /mnt/cephfs/legacy_app/data
sudo chmod 0750 /mnt/cephfs/legacy_app/data
```

### 4. Настройка безопасного доступа (CephX)

#### Пользователь с ограничением по пути (Path-based)

Изоляция клиентов является ключевым требованием безопасности.

```bash
# Выдача прав ТОЛЬКО к конкретному субтому
ceph auth get-or-create client.app_user \
  mon 'allow r' \
  mgr 'allow rw' \
  mds 'allow rw path=/volumes/project_alpha/user_data' \
  osd 'allow rw tag cephfs data=mycephfs'
# → [client.app_user]
# →     key = <base64_key>

# Извлечение секретного ключа для монтирования
ceph auth get-key client.app_user > /etc/ceph/app_user.secret
chmod 600 /etc/ceph/app_user.secret

# Просмотр полных прав клиента
ceph auth get client.app_user
# → [client.app_user]
# →     key = ...
# →     caps mon "allow r"
# →     caps mgr "allow rw"
# →     caps mds "allow rw path=/volumes/project_alpha/user_data"
# →     caps osd "allow rw tag cephfs data=mycephfs"
```

#### Ограничение по Multiple Subvolumes

```bash
# Доступ к двум разным субтомам в разных группах
ceph auth get-or-create client.multi_app \
  mon 'allow r' \
  mgr 'allow rw' \
  mds 'allow rw path=/volumes/group_a/data_a, allow rw path=/volumes/group_b/data_b' \
  osd 'allow rw tag cephfs data=mycephfs'
```

### 5. Монтирование CephFS

#### Метод А: Kernel Driver (Рекомендуемый)

```bash
# Монтирование с использованием Messenger v2.1 (порт 3300) и режима secure
sudo mount -t ceph 192.168.1.10:3300,192.168.1.11:3300:/ /mnt/shared \
  -o name=app_user,secretfile=/etc/ceph/app_user.secret,ms_mode=secure,noatime

# Монтирование конкретного подкаталога (через SyntheticDFerry)
sudo mount -t ceph 192.168.1.10:3300:/volumes/project_alpha/user_data /mnt/user_data \
  -o name=app_user,secretfile=/etc/ceph/app_user.secret,ms_mode=secure,noatime

# Проверка успешного монтирования
mount | grep ceph
# → 192.168.1.10:3300,192.168.1.11:3300:/ on /mnt/shared type ceph (...)

# Проверка доступности
ls /mnt/shared
# → (содержимое корня ФС)
```

**Параметры монтирования Kernel Driver:**

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `name=` | Имя клиента CephX | `admin` |
| `secretfile=` | Путь к файлу с ключом | `-` |
| `secret=` | Ключ в командной строке (небезопасно) | `-` |
| `ms_mode=` | Режим Messenger v2.1: `crc` или `secure` | `crc` |
| `noatime` | Отключает обновление atime | Отключен |
| `rwbdir=` | Mount-side read-write buffering | `-` |
| `checksum` | Включает контрольные суммы | Отключен |

#### Метод Б: FUSE Client

```bash
# Монтирование через FUSE (с keyring)
sudo ceph-fuse -m 192.168.1.10:6789 /mnt/shared \
  -r /volumes/project_alpha/user_data \
  -n client.app_user \
  -k /etc/ceph/ceph.client.app_user.keyring

# Проверка
ceph-fuse --version
# →ceph-fuse version 16.2.x
```

**Преимущества FUSE:**
- Актуальная версия клиента независима от ядра Linux.
- Полная поддержка всех расширенных атрибутов.

**Недостатки FUSE:**
- Дополнительный context switch (VFS → FUSE → RADOS) снижает производительность.
- Не поддерживает `quota-awareness` (только Kernel 5.15+).

#### Метод В: Автоматизация через /etc/fstab

```text
# В файле /etc/fstab:
192.168.1.10:3300:/path /mnt/data ceph name=user,secretfile=/etc/ceph/user.secret,ms_mode=crc,_netdev,noatime 0 0
```

| Поле | Описание |
|------|----------|
| `_netdev` | **Критично!** Задерживает монтирование до инициализации сетевого интерфейса. |
| `ms_mode=crc` | Режим работы v2.1. Используйте `secure` для шифрования. |
| `noatime` | Отключает обновление времени последнего доступа, снижая нагрузку на MDS. |

#### Метод Г: NFS Gateway (anesim)

Для сред, где_KERNEL cephfs недоступен или требуется NFS-совместимость.

```bash
# Развертывание NFS-шлюза через cephadm
ceph orch apply nfs mynfs mycephfs --placement="node1"

# Монтирование через NFS
sudo mount -t nfs node1:/mycephfs /mnt/nfs_data
```

**Примечание:** NFS Gateway добавляет задержку и ограничивает максимальную производительность. Используйте только когда Kernel/FUSE недоступны.

### 6. Резервное копирование (Автоматические снапшоты)

Встроенный модуль `snap_schedule` позволяет автоматизировать создание бекапов на уровне директорий или субтомов.

```bash
# Включение модуля в MGR
ceph mgr module enable snap_schedule
# → enabled

# Настройка расписания: снапшот каждый час для конкретной директории
ceph fs snap-schedule add /volumes/project_alpha/user_data 1h --fs mycephfs
# → Schedule added

# Настройка политики удержания (Retention): хранить 24 часовых, 7 дневных, 4 недельных
ceph fs snap-schedule retention add /volumes/project_alpha/user_data h 24 --fs mycephfs
ceph fs snap-schedule retention add /volumes/project_alpha/user_data d 7 --fs mycephfs
ceph fs snap-schedule retention add /volumes/project_alpha/user_data w 4 --fs mycephfs

# Просмотр активных расписаний
ceph fs snap-schedule status /volumes/project_alpha/user_data --fs mycephfs
# → {
# →   "enabled": true,
# →   "path": "/volumes/project_alpha/user_data",
# →   "schedule": "1h",
# →   "retention": {"h": 24, "d": 7, "w": 4}
# → }

# Временная остановка расписания
ceph fs snap-schedule pause /volumes/project_alpha/user_data --fs mycephfs

# Возобновление расписания
ceph fs snap-schedule resume /volumes/project_alpha/user_data --fs mycephfs

# Удаление расписания
ceph fs snap-schedule remove /volumes/project_alpha/user_data --fs mycephfs
```

#### Ручное управление снапшотами директорий

```bash
# Создание снапшота директории
ceph fs snap-snapshot create /mnt/cephfs/legacy_app 2026-08-30

# Просмотр снапшотов директории
ls -la /mnt/cephfs/legacy_app/.snap/
# → drwxr-xr-x 2 root root 4096 Aug 30 12:00 2026-08-30

# Восстановление данных из снапшота
sudo cp -a /mnt/cephfs/legacy_app/.snap/2026-08-30/* /mnt/cephfs/legacy_app/
```

### 7. Копирование данных между субтомами

```bash
# Копирование данных из одного субтома в другой (на уровне Ceph)
ceph fs subvolume snapshot create mycephfs source_sub snap_copy --group_name group_a
ceph fs subvolume snapshot clone mycephfs source_sub snap_copy target_clone --group_name group_b

# Ожидание завершения клонирования
ceph fs clone status mycephfs target_clone --group_name group_b
# → {"status": "complete"}

# Удаление исходного снапшота после клонирования
ceph fs subvolume snapshot rm mycephfs source_sub snap_copy --group_name group_a
```

### 8. Работа с cephfs-shell (Interactive CLI)

`cephfs-shell` — интерактивная оболочка для работы с CephFS, полезная для отладки и быстрого просмотра.

```bash
# Запуск cephfs-shell
cephfs-shell

# Просмотр текущей директории
ls

# Переход в директорию
cd /volumes/project_alpha/user_data

# Создание директории
mkdir test_dir

# Удаление
rm -r test_dir

# Выход из cephfs-shell
exit
```

**Примечание:** `cephfs-shell` использует FUSE-клиент и полезен для быстрой проверки доступности ФС без монтирования.

### 9. Восстановление после сбоев

#### Восстановление данных из снапшота

```bash
# 1. Найти доступные снапшоты
ceph fs snap-schedule status /volumes/project_alpha/user_data --fs mycephfs

# 2. Просмотреть .snap директорию
ls -la /mnt/cephfs/.snap/
# → 2026-08-29_12:00:00
# → 2026-08-30_12:00:00

# 3. Восстановить нужные файлы
sudo cp -a /mnt/cephfs/.snap/2026-08-30_12:00:00/important_file.txt /mnt/cephfs/
```

#### Восстановление после удаления субтома

```bash
# Если субтом был удален, но снапшоты остались:
# 1. Проверить наличие снапшотов (через .snap на родительской группе)
ls -la /mnt/cephfs/.snap/

# 2. Клонировать снапшот в новый субтом
ceph fs subvolume snapshot clone mycephfs project_alpha user_data_from_snap \
  --group_name project_alpha --snap snap_before_delete

# 3. Проверить статус
ceph fs clone status mycephfs user_data_from_snap --group_name project_alpha
```

#### Экстренное отключение клиента (Eviction)

Если клиент завис и блокирует MDS:

```bash
# Найти проблемный клиент
ceph tell mds.0 session ls --format json | jq '.[].id'

# Принудительное отключение
ceph tell mds.0 session evict id=<client_id>

# Проверка
ceph tell mds.0 session ls
```

---

## Диагностика и мониторинг

### Быстрая проверка состояния

```bash
# Статус всей ФС
ceph fs status
# → mycephfs
# →   ...
# → =====  =====  =====
# → E  0/0/1  up

# Детальный дамп (MDS, клиенты, кэш)
ceph fs dump

# Статус кластера
ceph health detail
# → HEALTH_OK
```

### Проверка квот и использования

```bash
# Просмотр квоты субтома
ceph fs subvolume info mycephfs user_data --group_name project_alpha --format json | jq '.bytes_quota'
# → 53687091200

# Просмотр использования через xattr (если смонтировано)
getfattr -n ceph.quota.max_bytes /mnt/cephfs/user_data
```

### Проверка сессий клиентов

```bash
# Все активные сессии
ceph tell mds.0 session ls --format json-pretty

# Количество Caps у каждого клиента
ceph daemon mds.0 dump_sessions
```

### Типичные проблемы и их решение

| Проблема | Симптомы | Причина | Решение |
|----------|----------|---------|---------|
| **`MDS_LAGGY`** | `ceph health detail` показывает MDS_LAGGY | Медленный пул метаданных или переполненный кэш | Переместите пул метаданных на NVMe/SSD. Увеличьте `mds_cache_memory_limit`. |
| **Permission Denied** | `mount` или `ls` возвращает EACCES | Несоответствие пути в Caps и точке монтирования | Строго проверьте `path=...` в правах. Путь должен совпадать с тем, что возвращает `ceph fs subvolume getpath`. |
| **Зависание I/O** | Процесс `dd` или `rsync` зависает | Разрыв сессии, отзыв Caps или падение OSD | Проверьте `dmesg` на клиенте. Убедитесь в доступности портов 3300/6789. |
| **Квота "пробивается"** | Клиент пишет сверх лимита | Cooperative природа квот | Задержка обновления до 30 секунд — нормальное поведение. Для строгих лимитов — application-level проверки. |
| **`ENOENT` на .snap** | `ls .snap` возвращает ошибку | Снапшоты не поддерживаются или ФС не настроена | Убедитесь, что cephfs menggunakan v16+ и snapshot schedule активен. |
| **`ENOSPC` при записи** | Запись невозможна, хотя место есть | Квота субтома достигнута или нет свободных PG | Проверьте квоту через `ceph fs subvolume info`. Расширьте субтом или очистите данные. |

---

## Дополнительная информация

### Best Practices

1. **Используйте Subvolumes**: Для новых инсталляций и Kubernetes — только через `ceph fs subvolume`. Классический путь (xattrs) — только для legacy-приложений.
2. **NVMe для метаданных**: Пул метаданных и journal размещайте на NVMe для минимальных задержек.
3. **Standby-Replay**: Включайте `allow_standby_replay true` для всех production ФС — это обеспечивает failover за < 5 секунд.
4. **Path-based Caps**: Никогда не выдавайте `allow rw` без ограничения по пути. Всегда используйте `path=...`.
5. **snap_schedule**: Настройте автоматические снапшоты для всех критических данных — это ваш основной механизм backup.
6. **Fstab**: Используйте `_netdev` для аварийного монтирования — это предотвращает зависание при перезагрузке.
7. **Регулярная проверка**: Запускайте `ceph fs status` и `ceph health detail` как минимум раз в сутки.

### Ограничения и известные проблемы

- **Cooperative Quotas**: Квоты могут быть временно превышены (до 30 секунд). Не используйте их как строгие лимиты для billing.
- **Kernel Driver vs FUSE**: Kernel Driver не поддерживает `quota-awareness` в версиях ниже 5.15. Для полной функциональности требуйте Linux 5.15+.
- **NFS Gateway**: Добавляет задержку и не поддерживает все POSIX-расширения. Используйте только как крайнюю меру.
- **Scrubbing**: Во время активного scrub возможен рост задержки для клиентов. Планируйте scrub в периоды низкой нагрузки.
- **Multi-active MDS**: Не эффективен для workload с интенсивным `rename` между директориями (подробнее — в [Продвинутых темах](./advanced_topics.md)).
- **cephfs-shell**: Использует FUSE и не рекомендуется для production-операций — только для отладки.

### Ссылки

- [CephFS: Определения и концепции](./definitions_and_concepts.md)
- [CephFS: Продвинутые темы](./advanced_topics.md)
- [CephFS Troubleshooting (Official)](https://docs.ceph.com/en/latest/cephfs/troubleshooting/)
- [CephFS Subvolume CLI (Official)](https://docs.ceph.com/en/latest/cephfs/fs-volumes/)
