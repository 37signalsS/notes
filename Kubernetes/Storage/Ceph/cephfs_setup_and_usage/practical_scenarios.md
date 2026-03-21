# CephFS: Практические сценарии

## 1. Создание файловой системы CephFS

### 1.1. Создание пулов

```bash
# Пул для данных (32 PG - рассчитайте по формуле)
ceph osd pool create cephfs_data 32

# Пул для метаданных
ceph osd pool create cephfs_metadata 32

# Активация приложения CephFS
ceph osd pool application enable cephfs_data cephfs
ceph osd pool application enable cephfs_metadata cephfs
```

> **Примечание**: Количество PG рассчитывается по формуле в [ceph_placement_groups.md](../ceph_placement_groups.md).

### 1.2. Создание файловой системы

```bash
# Создание ФС
ceph fs new cephfs cephfs_metadata cephfs_data

# Проверка
ceph fs ls

# Вывод:
# name: cephfs, metadata pool: cephfs_metadata, data pools: [cephfs_data]
```

### 1.3. Настройка MDS

```bash
# Статус MDS
ceph mds stat

# Увеличение количества активных MDS (для HA)
ceph fs set cephfs max_mds 2

# Проверка
ceph fs dump
```

---

## 2. Создание пользователя и настройка прав

### 2.1. Создание пользователя с доступом к каталогу

```bash
# Пользователь с доступом только к /data_pes
ceph auth get-or-create client.fs_user \
  mon 'allow r' \
  mgr 'allow r' \
  mds 'allow r, allow rw path=/data_pes' \
  osd 'allow rw pool=cephfs_data'
```

### 2.2. Пользователь с полным доступом

```bash
# Административный пользователь
ceph auth get-or-create client.cephfs_admin \
  mon 'allow r' \
  mgr 'allow rw' \
  mds 'allow *' \
  osd 'allow rw pool=cephfs_data, allow rw pool=cephfs_metadata'
```

### 2.3. Получение ключа пользователя

```bash
# Получить ключ
ceph auth get-key client.fs_user

# Экспорт в keyring
ceph auth get client.fs_user -o /etc/ceph/ceph.client.fs_user.keyring
```

---

## 3. Монтирование CephFS

### 3.1. Подготовка каталога

Сначала создайте каталог для пользователя (требуется доступ администратора):

```bash
# Монтирование корня от имени администратора
sudo mkdir -p /mnt/cephfs
ADMIN_SECRET=$(ceph auth get-key client.admin)

sudo mount -t ceph 172.21.0.10:6789:/ /mnt/cephfs \
  -o name=admin,secret=$ADMIN_SECRET

# Создание каталога для пользователя
sudo mkdir /mnt/cephfs/data_pes
sudo chown 1000:1000 /mnt/cephfs/data_pes  # UID:GID пользователя

# Демонтирование
sudo umount /mnt/cephfs
```

### 3.2. Ручное монтирование (kernel driver)

```bash
# Создание точки монтирования
sudo mkdir -p /mnt/shared_fs

# Получение ключа
USER_SECRET=$(ceph auth get-key client.fs_user)

# Монтирование
sudo mount -t ceph 172.21.0.10:6789:/data_pes /mnt/shared_fs \
  -o name=fs_user,secret=$USER_SECRET

# Проверка
df -h /mnt/shared_fs
mount | grep ceph
```

### 3.3. Монтирование с несколькими мониторами

```bash
# Указание нескольких мониторов для отказоустойчивости
sudo mount -t ceph \
  172.21.0.10:6789,172.21.0.11:6789,172.21.0.12:6789:/data_pes \
  /mnt/shared_fs \
  -o name=fs_user,secret=$USER_SECRET
```

### 3.4. Монтирование через FUSE

```bash
# Установка fuse-ceph
sudo apt install -y fuse-ceph  # Debian/Ubuntu
sudo yum install -y ceph-fuse  # CentOS/RHEL

# Монтирование через FUSE
sudo ceph-fuse -m 172.21.0.10:6789 /mnt/shared_fs \
  -r /data_pes \
  -n client.fs_user \
  -k /etc/ceph/ceph.client.fs_user.keyring
```

---

## 4. Автоматическое монтирование (fstab)

### 4.1. Создание файла с секретом

```bash
# Получение ключа
USER_SECRET=$(ceph auth get-key client.fs_user)

# Запись в файл
echo "$USER_SECRET" | sudo tee /etc/ceph/fs_user.secret
sudo chmod 600 /etc/ceph/fs_user.secret
```

### 4.2. Добавление в /etc/fstab

```bash
# Откройте /etc/fstab и добавьте строку:
echo "172.21.0.10,172.21.0.11,172.21.0.12:/data_pes /mnt/shared_fs ceph name=fs_user,secretfile=/etc/ceph/fs_user.secret,_netdev,noatime 0 0" | \
  sudo tee -a /etc/fstab
```

### 4.3. Разбор записи fstab

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

### 4.4. Проверка и тестирование

```bash
# Проверка синтаксиса
sudo mount -a

# Проверка монтирования
mount | grep ceph
df -h /mnt/shared_fs
```

---

## 5. Управление квотами

### 5.1. Установка квоты на каталог

```bash
# Квота на объем (10 ГБ)
setfattr -n ceph.quota.max_bytes -v 10737418240 /mnt/shared_fs/data_pes

# Квота на количество файлов (1000)
setfattr -n ceph.quota.max_files -v 1000 /mnt/shared_fs/data_pes
```

### 5.2. Проверка квот

```bash
# Установка утилиты
sudo apt install -y attr  # Debian/Ubuntu
sudo yum install -y attr  # CentOS/RHEL

# Просмотр квот
getfattr -n ceph.quota.max_bytes /mnt/shared_fs/data_pes
getfattr -n ceph.quota.max_files /mnt/shared_fs/data_pes

# Использование
ceph df detail
```

---

## 6. Снапшоты CephFS

### 6.1. Создание снапшота

```bash
# Снапшот всего дерева каталогов
ceph mds snapshot add cephfs /data_pes snap1

# Или через смонтированную ФС (требуется включенная функция)
mkdir /mnt/shared_fs/.snapshots
cp -r /mnt/shared_fs/data_pes /mnt/shared_fs/.snapshots/snap1/
```

### 6.2. Восстановление из снапшота

```bash
# Копирование данных из снапшота
cp -r /mnt/shared_fs/.snapshots/snap1/data_pes/* /mnt/shared_fs/data_pes/
```

---

## 7. Диагностика и мониторинг

### 7.1. Статус CephFS

```bash
# Общая информация
ceph fs status

# Детальная информация
ceph fs dump

# Статус MDS
ceph mds stat
```

### 7.2. Проверка клиентов

```bash
# Список подключенных клиентов
ceph fs ls

# Активные сессии
ceph mds sessions
```

### 7.3. Логи и отладка

```bash
# Включение отладки на клиенте
sudo ceph-debugfs start

# Просмотр логов ядра
dmesg | grep ceph

# Логи MDS
ceph --admin-daemon /var/run/ceph/ceph-mds.*.asok log dump
```

---

## Ссылки

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Дополнительная информация](./advanced_topics.md) — производительность и безопасность
