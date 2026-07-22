# CephFS: Практические сценарии

## Определения

**Subvolume (Субтом)** — абстракция над директорией CephFS, позволяющая управлять квотами, снапшотами и путями через специализированный CLI. Является стандартом для Kubernetes CSI.

**Keyring** — файл, содержащий имя пользователя и его ключ аутентификации в формате CephX (обычно `/etc/ceph/ceph.client.<user>.keyring`).

**Secretfile** — файл, содержащий исключительно "сырой" (raw) ключ (base64). Используется ядром Linux для монтирования, чтобы не передавать ключ в открытом виде через командную строку.

**MDS Caps (Capabilities)** — набор разрешений, выдаваемых MDS клиенту для работы с метаданными. Примеры: `allow rw path=/data` (доступ к пути), `allow r` (только чтение).

---

## Основные концепции

### Жизненный цикл управления CephFS

1.  **Инфраструктурный уровень**: Создание пулов данных и метаданных, создание файловой системы, развертывание MDS.
2.  **Уровень управления (Control Plane)**:
    *   *Классический*: Ручное создание директорий и установка прав/квот через расширенные атрибуты (`xattrs`).
    *   *Современный*: Использование модуля `volumes` и субтомов (Subvolumes).
3.  **Уровень доступа**: Создание пользователей CephX с ограниченными Caps.
4.  **Уровень потребления**: Монтирование через Kernel Driver, FUSE или CSI-драйвер в Kubernetes.

### Протоколы Messenger v1 vs v2

*   **v1 (порт 6789)**: Классический протокол без шифрования.
*   **v2 (порт 3300)**: Современный протокол (Messenger v2). Поддерживает режимы `crc` (целостность) и `secure` (полное шифрование трафика "на лету").

---

## Практические сценарии

### 1. Создание и базовая настройка ФС

#### Создание пулов и активация

```bash
# Пул для данных (рекомендуется использовать Erasure Coding для больших архивов или Replication для общего назначения)
# См. [Расчёт Placement Groups](../ceph_placement_groups.md)
ceph osd pool create cephfs_data 64
ceph osd pool create cephfs_metadata 64

# Активация приложения (обязательно для работы MGR и корректной статистики)
ceph osd pool application enable cephfs_data cephfs
ceph osd pool application enable cephfs_metadata cephfs
```

#### Инициализация файловой системы

```bash
# Создание ФС (первым указывается пул метаданных)
ceph fs new mycephfs cephfs_metadata cephfs_data

# Проверка статуса
ceph fs ls
ceph mds stat
```

#### Настройка отказоустойчивости MDS

Для обеспечения высокой доступности (HA) рекомендуется иметь минимум один активный и один Standby MDS на каждую ФС.

```bash
# Увеличение количества активных MDS (рангов) до 2 (требует минимум 3 MDS в кластере для HA)
ceph fs set mycephfs max_mds 2

# Включение режима standby-replay (ускоряет failover)
ceph fs set mycephfs allow_standby_replay true
```

### 2. Современное управление через Субтомы (Subvolumes)

Рекомендуемый метод для новых инсталляций и Kubernetes.

#### Работа с группами и томами

```bash
# Создание группы (например, под конкретный проект)
ceph fs subvolumegroup create mycephfs project_alpha

# Создание субтома с жесткой квотой (50 ГБ)
ceph fs subvolume create mycephfs user_data --group_name project_alpha --size 53687091200

# Получение реального пути на диске (нужен для ручного монтирования)
ceph fs subvolume getpath mycephfs user_data --group_name project_alpha
# → /volumes/project_alpha/user_data/uuid...
```

#### Ресайз и информация

```bash
# Увеличение квоты до 100 ГБ
ceph fs subvolume resize mycephfs user_data 107374182400 --group_name project_alpha

# Просмотр информации о заполнении и квотах
ceph fs subvolume info mycephfs user_data --group_name project_alpha
```

### 3. Классическое управление (Manual Path & Xattrs)

Используется для тонкой настройки существующих директорий.

#### Создание и права

```bash
# 1. Монтируем ФС как администратор
sudo mount -t ceph :/ /mnt/cephfs -o name=admin,secretfile=/etc/ceph/admin.secret

# 2. Создаем структуру
sudo mkdir -p /mnt/cephfs/legacy_app/data
sudo chown 1000:1000 /mnt/cephfs/legacy_app/data

# 3. Установка квот через атрибуты (требует установленного пакета attr)
# Квота на объем (10 ГБ)
setfattr -n ceph.quota.max_bytes -v 10737418240 /mnt/cephfs/legacy_app/data
# Квота на количество файлов (1 млн)
setfattr -n ceph.quota.max_files -v 1000000 /mnt/cephfs/legacy_app/data
```

### 4. Настройка доступа (CephX)

#### Пользователь с ограничением по пути (Path-based)

```bash
# Доступ только к конкретному субтому/директории
ceph auth get-or-create client.app_user \
  mon 'allow r' \
  mgr 'allow r' \
  mds 'allow rw path=/volumes/project_alpha/user_data' \
  osd 'allow rw pool=cephfs_data'

# Извлечение ключа для клиента
ceph auth get-key client.app_user > app_user.secret
chmod 600 app_user.secret
```

### 5. Монтирование CephFS

#### Метод А: Kernel Driver (Рекомендуемый)

Обеспечивает наилучшую производительность.

```bash
# Монтирование с использованием Messenger v2 (порт 3300) и режима crc
sudo mount -t ceph 192.168.1.10:3300,192.168.1.11:3300:/ /mnt/shared \
  -o name=app_user,secretfile=/etc/ceph/app_user.secret,ms_mode=prefer-crc,noatime
```

#### Метод Б: FUSE Client

Используется, если ядро клиента слишком старое или нужны специфические фичи.

```bash
# Установка (Debian/Ubuntu)
sudo apt install -y ceph-fuse

# Монтирование (через keyring)
sudo ceph-fuse -m 192.168.1.10:6789 /mnt/shared \
  -r /volumes/project_alpha/user_data \
  -n client.app_user \
  -k /etc/ceph/ceph.client.app_user.keyring
```

#### Метод В: Автоматизация через /etc/fstab

Подробный разбор записи для надежного монтирования при загрузке:

```bash
# Запись в fstab
192.168.1.10,192.168.1.11:/path /mnt/data ceph name=user,secretfile=/etc/ceph/user.secret,ms_mode=crc,_netdev,noatime 0 0
```

| Поле | Описание |
|------|----------|
| `192.168.1.10,...:/path` | Список мониторов и путь внутри CephFS. |
| `_netdev` | **Критично!** Указывает системе монтировать ФС только после поднятия сети. |
| `ms_mode=crc` | Режим работы протокола Messenger v2 (целостность данных). |
| `noatime` | Отключает обновление времени последнего доступа (снижает нагрузку на MDS). |

### 6. Снапшоты и резервное копирование

#### Ручные снапшоты (через .snap)

Снапшоты в CephFS доступны через скрытую директорию `.snap`.

```bash
# Создание
mkdir /mnt/shared/.snap/backup_2025_01_01

# Просмотр (снапшот выглядит как обычная копия данных)
ls -l /mnt/shared/.snap/backup_2025_01_01/

# Удаление
rmdir /mnt/shared/.snap/backup_2025_01_01
```

#### Автоматизированные расписания (Snapshot Schedules)

Требует активации модуля в MGR.

```bash
# Включение и настройка
ceph mgr module enable snap_schedule
ceph fs snap-schedule add /volumes/project_alpha/user_data 1h --fs mycephfs

# Настройка политики удержания: 24 часовых, 7 дневных, 4 недельных
ceph fs snap-schedule retention add /volumes/project_alpha/user_data h 24 --fs mycephfs
ceph fs snap-schedule retention add /volumes/project_alpha/user_data d 7 --fs mycephfs
ceph fs snap-schedule retention add /volumes/project_alpha/user_data w 4 --fs mycephfs
```

---

## Диагностика и мониторинг

### Проверка состояния кластера ФС

```bash
# Быстрый статус (активные MDS, клиенты, использование)
ceph fs status

# Детальный дамп состояния MDS (ранги, лаги, сессии)
ceph fs dump

# Просмотр статистики MDS в реальном времени
ceph tell mds.a perf dump | jq '.mds'
```

### Мониторинг клиентов

```bash
# Список активных сессий клиентов
ceph tell mds.0 session ls

# Принудительный разрыв зависшей сессии (например, при замене узла)
ceph tell mds.0 session evict id=12345
```

### Типичные проблемы и их решение

| Проблема | Причина | Решение |
|----------|---------|---------|
| **MDS_LAGGY / MDS_SLOW** | Медленный диск метаданных или огромный каталог. | Перенесите пул метаданных на SSD/NVMe. Проверьте `mds_cache_memory_limit`. |
| **Permission Denied** | Несоответствие Caps и пути монтирования. | Проверьте `ceph auth get client.xxx`. Путь в `mds allow` должен строго совпадать с путем монтирования. |
| **Зависание I/O** | Потеря связи с мониторами или OSD. | Проверьте `dmesg`. Убедитесь, что порты 3300/6789 открыты между клиентом и кластером. |
| **Квота не срабатывает** | "Мягкая" природа квот в CephFS. | Клиент может записать чуть больше лимита (до 30 сек задержки). Используйте FUSE для более строгих лимитов. |

---

## Дополнительная информация

### Рекомендуемый порядок внедрения

1.  Развертывание MDS (минимум 2 шт).
2.  Создание пулов с SSD-tiering для метаданных.
3.  Использование Subvolumes для изоляции приложений.
4.  Настройка автоматических снапшотов для критичных данных.
5.  Мониторинг латентности MDS через Prometheus/Grafana.

### Ссылки
- [Концепции и архитектура CephFS](./definitions_and_concepts.md)
- [Оптимизация MDS и кэша](./advanced_topics.md)
- [Официальная документация: Troubleshooting CephFS](https://docs.ceph.com/en/latest/cephfs/troubleshooting/)
