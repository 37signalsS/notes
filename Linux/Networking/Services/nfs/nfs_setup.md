# NFS: Настройка сервера и клиента

## Definitions

**NFS-настройка** — процесс конфигурации NFS-сервера (экспорт директорий) и NFS-клиента (монтирование экспортов). Включает установку пакетов, конфигурацию `/etc/exports`, настройку монтирования через fstab или AutoFS.

## Basic Concepts

### Архитектура

- **NFS-сервер** — экспортирует директории через `/etc/exports`, управляет доступом через опции (rw/ro, sync/async, squash-правила)
- **NFS-клиент** — монтирует экспорты через `mount -t nfs4`, автоматическое монтирование через fstab или AutoFS
- **exportfs** — утилита управления экспортами на сервере

### Пакеты

| Дистрибутив | Сервер | Клиент |
| :--- | :--- | :--- |
| Debian/Ubuntu | `nfs-kernel-server` | `nfs-common` |
| CentOS/RHEL | `nfs-utils` | `nfs-utils` |

### Опции `/etc/exports`

| Опция | Описание |
| :--- | :--- |
| `ro` / `rw` | Только чтение / чтение-запись |
| `sync` | Подтверждение после записи на диск (надёжность) |
| `async` | Подтверждение до записи (скорость, риск потери данных) |
| `root_squash` | Маппинг root клиента в nobody (по умолчанию, рекомендуется) |
| `no_root_squash` | Root клиента = root на сервере (опасно, только для доверенных сетей) |
| `all_squash` | Все запросы от имени nobody:nogroup (публичные ресурсы) |
| `anonuid=<UID>` | UID для all_squash |
| `anongid=<GID>` | GID для all_squash |
| `no_subtree_check` | Отключает проверку поддиректорий (производительность) |

Подробно о security-опциях (`sec=krb5*`): [nfs_security.md](./nfs_security.md). О маппинге UID/GID и root_squash: [nfs_basics.md](./nfs_basics.md).

### Опции монтирования (fstab)

| Опция | Описание |
| :--- | :--- |
| `hard` | Процесс ждёт восстановления сервера (рекомендуется, защита от потери данных) |
| `soft` | Ошибка I/O при недоступности сервера (риск повреждения данных) |
| `nofail` | Загрузка продолжается при недоступности NFS |
| `noatime` | Отключает обновление времени доступа (производительность) |
| `_netdev` | Монтирование после поднятия сети |

## Practical Scenarios

### Настройка NFS-сервера

**1. Установка:**

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y nfs-kernel-server

# CentOS/RHEL
sudo yum install -y nfs-utils
```

**2. Создание экспортируемой директории:**

```bash
sudo mkdir -p /srv/nfs/shared
sudo chown nobody:nogroup /srv/nfs/shared
sudo chmod 0755 /srv/nfs/shared
```

**3. Конфигурация `/etc/exports`:**

```ini
# Один клиент
/srv/nfs/shared 10.0.0.10(rw,sync,no_subtree_check)

# Подсеть
/srv/nfs/data 10.0.0.0/24(rw,sync,no_subtree_check)

# Только чтение
/srv/nfs/readonly 10.0.0.0/24(ro,sync,no_subtree_check,root_squash)
```

**4. Применение конфигурации:**

```bash
sudo exportfs -a                         # Применить изменения
sudo exportfs -v                         # Проверить текущие экспорты
sudo systemctl restart nfs-kernel-server # Перезапустить службу
```

**5. Проверка на сервере:**

```bash
# Просмотр экспортов
exportfs -v

# Проверка службы
sudo systemctl status nfs-kernel-server
```

### Настройка NFS-клиента

**1. Установка:**

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y nfs-common

# CentOS/RHEL
sudo yum install -y nfs-utils
```

**2. Просмотр доступных ресурсов:**

```bash
showmount -e <IP_сервера>
```

**3. Временное монтирование:**

```bash
sudo mkdir -p /mnt/nfs/shared
sudo mount -t nfs4 10.0.0.5:/srv/nfs/shared /mnt/nfs/shared
```

**4. Постоянное монтирование через `/etc/fstab`:**

```ini
# <сервер>:<путь>            <точка>          <тип>  <опции>                     <dump> <pass>
10.0.0.5:/srv/nfs/shared    /mnt/nfs/shared  nfs4   hard,nofail,noatime,_netdev  0      0
```

```bash
sudo mount -a  # Проверить fstab
```

**5. Размонтирование:**

```bash
sudo umount /mnt/nfs/shared
# Если занято:
sudo umount -l /mnt/nfs/shared  # Lazy unmount
sudo umount -f /mnt/nfs/shared  # Force unmount (NFS)
```

### Автоматическое монтирование через AutoFS

AutoFS монтирует NFS-ресурсы по требованию (например, домашние директории). Рекомендуемый подход для динамических сред.

Подробная настройка: [autofs_mount.md](../../../../Linux/FileSystems/mounting/scenarios/autofs_mount.md).

## Additional Information

Смежные руководства: базовые концепции NFS ([nfs_basics.md](./nfs_basics.md)), безопасность NFS ([nfs_security.md](./nfs_security.md)), производительность ([nfs_performance.md](./nfs_performance.md)), устранение неполадок ([nfs_troubleshooting.md](./nfs_troubleshooting.md)), AutoFS ([autofs_mount.md](../../../../Linux/FileSystems/mounting/scenarios/autofs_mount.md)).
