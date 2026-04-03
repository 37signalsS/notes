# CephFS: Практические сценарии

## Определения

**Keyring** — файл, содержащий ключ аутентификации клиента Ceph (формат: `/etc/ceph/ceph.client.<username>.keyring`).

**Secretfile** — файл с raw-ключом клиента, используется при монтировании через fstab.

## Базовые концепции

### Жизненный цикл CephFS

```
Создание пулов → Активация приложения → Создание ФС → Настройка MDS → Создание пользователей → Монтирование
```

### Типы монтирования

| Тип | Команда | Сценарий |
|-----|---------|----------|
| **Kernel** | `mount -t ceph` | Production, высокая производительность |
| **FUSE** | `ceph-fuse` | Тестирование, нестандартные ядра |
| **fstab** | записи в `/etc/fstab` | Автоматическое монтирование при загрузке |

### Иерархия прав доступа

```
admin (полный доступ)
  ↓
path-based пользователь (rw на конкретный каталог)
  ↓
readonly пользователь (только чтение)
```

Подробная модель прав — в [определениях и концепциях](./definitions_and_concepts.md#модель-прав-доступа).

---

## Практические сценарии

### Создание файловой системы CephFS

#### Создание пулов

```bash
# Пул для данных (PG рассчитайте по формуле)
ceph osd pool create cephfs_data 32

# Пул для метаданных
ceph osd pool create cephfs_metadata 32

# Активация приложения CephFS
ceph osd pool application enable cephfs_data cephfs
ceph osd pool application enable cephfs_metadata cephfs
```

> **Примечание**: Количество PG рассчитывается по формуле в [расчёте placement groups](../ceph_placement_groups.md).

#### Создание файловой системы

```bash
ceph fs new cephfs cephfs_metadata cephfs_data
ceph fs ls
```

#### Настройка MDS

```bash
# Статус MDS
ceph mds stat

# Увеличение количества активных MDS (для HA)
ceph fs set cephfs max_mds 2
ceph fs dump
```

### Создание пользователя и настройка прав

#### Пользователь с доступом к каталогу

```bash
ceph auth get-or-create client.fs_user \
  mon 'allow r' \
  mgr 'allow r' \
  mds 'allow r, allow rw path=/data_pes' \
  osd 'allow rw pool=cephfs_data'
```

#### Административный пользователь

```bash
ceph auth get-or-create client.cephfs_admin \
  mon 'allow r' \
  mgr 'allow rw' \
  mds 'allow *' \
  osd 'allow rw pool=cephfs_data, allow rw pool=cephfs_metadata'
```

#### Получение ключа пользователя

```bash
ceph auth get-key client.fs_user
ceph auth get client.fs_user -o /etc/ceph/ceph.client.fs_user.keyring
```

### Монтирование CephFS

#### Подготовка каталога (администратор)

```bash
sudo mkdir -p /mnt/cephfs
ADMIN_SECRET=$(ceph auth get-key client.admin)

sudo mount -t ceph 172.21.0.10:6789:/ /mnt/cephfs \
  -o name=admin,secret=$ADMIN_SECRET

sudo mkdir /mnt/cephfs/data_pes
sudo chown 1000:1000 /mnt/cephfs/data_pes

sudo umount /mnt/cephfs
```

#### Ручное монтирование (kernel driver)

```bash
sudo mkdir -p /mnt/shared_fs
USER_SECRET=$(ceph auth get-key client.fs_user)

sudo mount -t ceph 172.21.0.10:6789:/data_pes /mnt/shared_fs \
  -o name=fs_user,secret=$USER_SECRET

df -h /mnt/shared_fs
mount | grep ceph
```

#### Монтирование с несколькими мониторами

```bash
sudo mount -t ceph \
  172.21.0.10:6789,172.21.0.11:6789,172.21.0.12:6789:/data_pes \
  /mnt/shared_fs \
  -o name=fs_user,secret=$USER_SECRET
```

#### Монтирование через FUSE

```bash
# Установка
sudo apt install -y fuse-ceph  # Debian/Ubuntu
sudo yum install -y ceph-fuse  # CentOS/RHEL

# Монтирование
sudo ceph-fuse -m 172.21.0.10:6789 /mnt/shared_fs \
  -r /data_pes \
  -n client.fs_user \
  -k /etc/ceph/ceph.client.fs_user.keyring
```

### Автоматическое монтирование (fstab)

#### Создание файла с секретом

```bash
USER_SECRET=$(ceph auth get-key client.fs_user)
echo "$USER_SECRET" | sudo tee /etc/ceph/fs_user.secret
sudo chmod 600 /etc/ceph/fs_user.secret
```

#### Добавление в /etc/fstab

```bash
echo "172.21.0.10,172.21.0.11,172.21.0.12:/data_pes /mnt/shared_fs ceph name=fs_user,secretfile=/etc/ceph/fs_user.secret,_netdev,noatime 0 0" | \
  sudo tee -a /etc/fstab
```

#### Разбор записи fstab

| Поле | Значение | Описание |
|------|----------|----------|
| `172.21.0.10,...:/data_pes` | Device | Мониторы + путь |
| `/mnt/shared_fs` | Mountpoint | Точка монтирования |
| `ceph` | Type | Тип ФС |
| `name=fs_user,secretfile=...,` | Options | Опции монтирования |
| `_netdev` | Critical! | Монтировать после сети |
| `noatime` | Optional | Не обновлять время доступа |
| `0` | Dump | Не бэкапить |
| `0` | Pass | Не проверять fsck |

#### Проверка и тестирование

```bash
sudo mount -a
mount | grep ceph
df -h /mnt/shared_fs
```

### Управление квотами

#### Установка квоты на каталог

```bash
# Квота на объем (10 ГБ)
setfattr -n ceph.quota.max_bytes -v 10737418240 /mnt/shared_fs/data_pes

# Квота на количество файлов (1000)
setfattr -n ceph.quota.max_files -v 1000 /mnt/shared_fs/data_pes
```

#### Проверка квот

```bash
# Установка утилиты
sudo apt install -y attr  # Debian/Ubuntu
sudo yum install -y attr  # CentOS/RHEL

# Просмотр
getfattr -n ceph.quota.max_bytes /mnt/shared_fs/data_pes
getfattr -n ceph.quota.max_files /mnt/shared_fs/data_pes

# Использование кластера
ceph df detail
```

### Снапшоты CephFS

#### Создание снапшота

```bash
# Через MDS
ceph mds snapshot add cephfs /data_pes snap1

# Или через смонтированную ФС
mkdir /mnt/shared_fs/.snapshots
cp -r /mnt/shared_fs/data_pes /mnt/shared_fs/.snapshots/snap1/
```

#### Восстановление из снапшота

```bash
cp -r /mnt/shared_fs/.snapshots/snap1/data_pes/* /mnt/shared_fs/data_pes/
```

### Диагностика и мониторинг

#### Статус CephFS

```bash
ceph fs status
ceph fs dump
ceph mds stat
```

#### Проверка клиентов

```bash
ceph fs ls
ceph mds sessions
```

#### Логи и отладка

```bash
sudo ceph-debugfs start
dmesg | grep ceph
ceph --admin-daemon /var/run/ceph/ceph-mds.*.asok log dump
```

---

## Дополнительная информация

### Troubleshooting

| Проблема | Решение |
|----------|---------|
| **Mount fails: Permission denied** | Проверьте права пользователя: `ceph auth get client.fs_user` |
| **Статус `inconsistent`** | Запустите `ceph fs status`, проверьте MDS |
| **Квота не применяется** | Задержка до 30 сек на уровне MDS |
| **FUSE не монтируется** | Проверьте установку `ceph-fuse` и наличие keyring |

### Рекомендуемый порядок действий

1. Создайте пулы → 2. Создайте ФС → 3. Настройте MDS → 4. Создайте пользователя → 5. Смонтируйте → 6. Установите квоты
