# CephFS: Практические сценарии

## Определения

**Subvolume (Субтом)** — логическая абстракция над директорией CephFS, предоставляющая изолированное пространство для хранения. Позволяет управлять квотами, снапшотами и путями через специализированный CLI. Является стандартом для интеграции с Kubernetes (CSI).

**Clone (Клон)** — полная копия субтома, создаваемая из его снапшота. Используется для быстрого развертывания новых сред (например, копирование PersistentVolume в K8s).

**Keyring** — файл, содержащий имя пользователя и его криптографический ключ аутентификации в формате CephX (обычно `/etc/ceph/ceph.client.<user>.keyring`).

**Secretfile** — файл, содержащий исключительно "сырой" (raw) ключ в кодировке base64. Используется модулем ядра Linux при монтировании, чтобы избежать передачи ключа в открытом виде через аргументы командной строки.

**MDS Caps (Capabilities)** — набор криптографически подписанных разрешений, выдаваемых клиенту для работы с метаданными. Примеры: `allow rw path=/data` (полный доступ к директории), `allow r` (только чтение).

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

*   **v1 (порт 6789)**: Классический протокол без криптографической защиты.
*   **v2.1 (порт 3300)**: Современный стандарт. Поддерживает режимы `crc` (целостность данных) и `secure` (полное AES-GCM шифрование трафика "на лету").

---

## Практические сценарии

### 1. Создание и базовая настройка ФС

#### Создание пулов и активация (с Erasure Coding)

Для пулов метаданных всегда используется репликация (быстрые SSD/NVMe). Для пулов данных в современных инсталляциях часто используют Erasure Coding (EC).

```bash
# Пул метаданных (строго репликация, например size=3)
ceph osd pool create cephfs_metadata 64 replicated

# Пул данных (Erasure Coding для экономии места)
ceph osd pool create cephfs_data 128 erasure

# КРИТИЧНО для CephFS: Разрешить перезапись объектов в EC пуле
ceph osd pool set cephfs_data allow_ec_overwrites true

# Активация приложения
ceph osd pool application enable cephfs_data cephfs
ceph osd pool application enable cephfs_metadata cephfs
```

#### Инициализация файловой системы и MDS

```bash
# Создание ФС (первым указывается пул метаданных)
ceph fs new mycephfs cephfs_metadata cephfs_data

# Декларативное развертывание MDS через cephadm (например, 3 демона)
ceph orch apply mds mycephfs --placement="3"

# Включение режима standby-replay для мгновенного failover
ceph fs set mycephfs allow_standby_replay true
```

### 2. Современное управление через Субтомы (Subvolumes)

Рекомендуемый метод для новых инсталляций, контейнерных сред и автоматизации.

#### Работа с группами и томами

```bash
# Создание группы (например, логическая группировка "project_alpha")
ceph fs subvolumegroup create mycephfs project_alpha

# Создание субтома с жесткой квотой (50 ГБ)
ceph fs subvolume create mycephfs user_data --group_name project_alpha --size 53687091200

# Получение реального пути на диске (нужен для монтирования клиентом)
ceph fs subvolume getpath mycephfs user_data --group_name project_alpha
# → /volumes/project_alpha/user_data/uuid...
```

#### Снапшоты и Клонирование субтомов

```bash
# 1. Создание снапшота субтома
ceph fs subvolume snapshot create mycephfs user_data snap_v1 --group_name project_alpha

# 2. Создание независимого клона из снапшота (асинхронная операция)
ceph fs subvolume snapshot clone mycephfs user_data snap_v1 clone_data --group_name project_alpha

# 3. Проверка статуса клонирования (должно быть 'complete')
ceph fs clone status mycephfs clone_data --group_name project_alpha
```

### 3. Классическое управление (Manual Path & Xattrs)

Используется для тонкой настройки существующих или специфических директорий.

```bash
# 1. Монтируем корень ФС как администратор
sudo mount -t ceph :/ /mnt/cephfs -o name=admin,secretfile=/etc/ceph/admin.secret

# 2. Создаем структуру
sudo mkdir -p /mnt/cephfs/legacy_app/data

# 3. Установка квот через атрибуты (клиентские ОС проверяют их асинхронно)
# Квота на объем (10 ГБ)
setfattr -n ceph.quota.max_bytes -v 10737418240 /mnt/cephfs/legacy_app/data
# Квота на количество файлов (1 млн)
setfattr -n ceph.quota.max_files -v 1000000 /mnt/cephfs/legacy_app/data
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

# Извлечение секретного ключа для монтирования
ceph auth get-key client.app_user > /etc/ceph/app_user.secret
chmod 600 /etc/ceph/app_user.secret
```

### 5. Монтирование CephFS

#### Метод А: Kernel Driver (Рекомендуемый)

```bash
# Монтирование с использованием Messenger v2.1 (порт 3300) и режима secure
sudo mount -t ceph 192.168.1.10:3300,192.168.1.11:3300:/ /mnt/shared \
  -o name=app_user,secretfile=/etc/ceph/app_user.secret,ms_mode=secure,noatime
```

#### Метод Б: FUSE Client

```bash
# Монтирование (через keyring)
sudo ceph-fuse -m 192.168.1.10:6789 /mnt/shared \
  -r /volumes/project_alpha/user_data \
  -n client.app_user \
  -k /etc/ceph/ceph.client.app_user.keyring
```

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

### 6. Резервное копирование (Автоматические снапшоты)

Встроенный модуль `snap_schedule` позволяет автоматизировать создание бекапов на уровне директорий или субтомов.

```bash
# Включение модуля в MGR
ceph mgr module enable snap_schedule

# Настройка расписания: снапшот каждый час для конкретной директории
ceph fs snap-schedule add /volumes/project_alpha/user_data 1h --fs mycephfs

# Настройка политики удержания (Retention): хранить 24 часовых, 7 дневных, 4 недельных
ceph fs snap-schedule retention add /volumes/project_alpha/user_data h 24 --fs mycephfs
ceph fs snap-schedule retention add /volumes/project_alpha/user_data d 7 --fs mycephfs
ceph fs snap-schedule retention add /volumes/project_alpha/user_data w 4 --fs mycephfs

# Просмотр активных расписаний
ceph fs snap-schedule status /volumes/project_alpha/user_data --fs mycephfs
```

---

## Диагностика и мониторинг

### Проверка состояния клиентов и квот

```bash
# Быстрый статус кластера ФС
ceph fs status

# Детальный дамп состояния MDS (проверка лагов)
ceph fs dump

# Мониторинг квот (проверка "протекших" данных)
ceph tell mds.0 perf dump | jq '.mds.quota'
```

### Типичные проблемы и их решение

| Проблема | Причина | Решение |
|----------|---------|---------|
| **`MDS_LAGGY` / `MDS_SLOW`** | Огромное количество мелких файлов или медленный пул метаданных. | Убедитесь, что пул метаданных находится на NVMe/SSD. Настройте `mds_cache_memory_limit`. |
| **Permission Denied при `mount`** | Несоответствие пути в Caps и точке монтирования. | Строго проверьте `path=...` в правах клиента. Путь должен совпадать с тем, что возвращает `getpath`. |
| **Зависание I/O клиента** | Разрыв сессии, отзыв Caps (recall) или падение OSD. | Проверьте `dmesg` на клиенте. Убедитесь в доступности портов 3300/6789. |
| **Квота "пробивается"** | "Мягкая" (cooperative) природа квот. | Клиент сверяется с MDS периодически. Задержка может достигать 30 секунд. Это нормальное поведение. |

---

## Дополнительная информация

### Ссылки
- [Концепции и архитектура CephFS](./definitions_and_concepts.md)
- [Оптимизация MDS и кэша](./advanced_topics.md)
- [Официальная документация: Troubleshooting CephFS](https://docs.ceph.com/en/latest/cephfs/troubleshooting/)
