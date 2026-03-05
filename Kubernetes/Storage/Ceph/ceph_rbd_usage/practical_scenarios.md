# RBD: Практические сценарии

## 1. Установка и настройка клиента

### 1.1. Установка ceph-common

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install -y ceph-common

# CentOS/RHEL
sudo yum install -y ceph-common

# Или из репозитория Ceph
wget -q -O- 'https://download.ceph.com/keys/release.asc' | sudo apt-key add -
echo "deb https://download.ceph.com/debian-reef/ $(lsb_release -sc) main" | \
  sudo tee /etc/apt/sources.list.d/ceph.list
sudo apt update
sudo apt install -y ceph-common
```

> **Важно**: Используйте версию ceph-common, совместимую с версией сервера Ceph.

### 1.2. Настройка конфигурации

```bash
# Копирование конфига с сервера Ceph
sudo mkdir -p /etc/ceph
sudo scp user@ceph-node:/etc/ceph/ceph.conf /etc/ceph/

# Или создание вручную
sudo tee /etc/ceph/ceph.conf <<EOF
[global]
mon_host = 172.21.0.10,172.21.0.11,172.21.0.12
EOF

# Копирование ключа
sudo scp user@ceph-node:/etc/ceph/ceph.client.user.keyring /etc/ceph/
sudo chmod 600 /etc/ceph/ceph.client.user.keyring
```

### 1.3. Проверка подключения

```bash
ceph --name client.user -s
```

---

## 2. Создание и управление образами

### 2.1. Создание образа

```bash
# Создание образа 10 ГБ
rbd create --size 10240 --pool kube my-image

# С указанием функций
rbd create --size 10240 --pool kube \
  --image-features layering,exclusive-lock,object-map,fast-diff \
  my-image

# Thin provisioning (место выделяется по мере записи)
rbd create --size 10240 --pool kube --object-size 4096 my-image
```

### 2.2. Информация об образе

```bash
# Список образов в пуле
rbd ls -p kube

# Детальная информация
rbd info kube/my-image

# Статистика использования
rbd du -p kube
```

### 2.3. Изменение размера

```bash
# Увеличение размера
rbd resize --size 20480 kube/my-image

# Уменьшение (осторожно!)
rbd resize --size 5120 kube/my-image --allow-shrink
```

### 2.4. Удаление образа

```bash
# Удаление
rbd rm kube/my-image

# Перемещение в trash (безопасное удаление)
rbd trash mv kube/my-image
rbd trash rm kube/my-image  # Окончательное удаление
```

---

## 3. Маппинг и монтирование

### 3.1. Маппинг образа

```bash
# Маппинг
sudo rbd map kube/my-image --id user

# Проверка
rbd showmapped

# Вывод:
# dev  "/dev/rbd0"
# pool "kube"
# name "my-image"
```

### 3.2. Создание файловой системы

```bash
# Только для нового образа!
sudo mkfs.ext4 /dev/rbd0

# Или xfs
sudo mkfs.xfs /dev/rbd0
```

### 3.3. Монтирование

```bash
# Создание точки монтирования
sudo mkdir -p /mnt/rbd

# Монтирование
sudo mount /dev/rbd0 /mnt/rbd

# Проверка
df -h /mnt/rbd
```

---

## 4. Демонтирование и размаппинг

```bash
# Демонтирование
sudo umount /mnt/rbd

# Размаппинг по устройству
sudo rbd unmap /dev/rbd0

# Размаппинг по имени
sudo rbd unmap kube/my-image

# Принудительное размаппинг (если занят)
sudo rbd unmap kube/my-image --force
```

---

## 5. Снапшоты и клонирование

### 5.1. Создание снапшота

```bash
# Создание
rbd snap create kube/my-image@snap1

# Список снапшотов
rbd snap ls kube/my-image
```

### 5.2. Откат к снапшоту

```bash
# Откат (образ должен быть размапплен!)
rbd snap rollback kube/my-image@snap1
```

### 5.3. Клонирование

```bash
# Защита снапшота (обязательно для клонирования)
rbd snap protect kube/my-image@snap1

# Создание клона
rbd clone kube/my-image@snap1 kube/clone-image

# Снятие защиты
rbd snap unprotect kube/my-image@snap1
```

### 5.4. Удаление снапшотов

```bash
# Удаление одного снапшота
rbd snap rm kube/my-image@snap1

# Удаление всех снапшотов
rbd snap purge kube/my-image
```

---

## 6. Автоматическое монтирование

### 6.1. Настройка udev правила

Создайте файл `/etc/udev/rules.d/50-rbd.rules`:

```bash
# Автоматический маппинг при загрузке
ACTION=="add", SUBSYSTEM=="rbd", ATTR{pool}=="kube", ATTR{name}=="my-image", \
  RUN+="/usr/bin/rbd map kube/my-image"
```

### 6.2. Настройка /etc/fstab

```bash
# Получение UUID образа
blkid /dev/rbd0

# Добавление в /etc/fstab
UUID=<uuid> /mnt/rbd ext4 _netdev,noatime 0 0

# Или по устройству
/dev/rbd0 /mnt/rbd ext4 _netdev,noatime 0 0
```

> **Важно**: Опция `_netdev` критична! Без неё система может зависнуть при загрузке.

### 6.3. Альтернатива: systemd mount

Создайте `/etc/systemd/system/mnt-rbd.mount`:

```ini
[Unit]
Description=Mount RBD volume
After=network-online.target rbdmap.service
Wants=network-online.target

[Mount]
What=/dev/rbd0
Where=/mnt/rbd
Type=ext4
Options=_netdev,noatime

[Install]
WantedBy=multi-user.target
```

---

## 7. Устранение ошибок

### 7.1. RBD image features set mismatch

**Ошибка**: Ядро не поддерживает функции образа.

**Решение**:

```bash
# Отключение неподдерживаемых функций
rbd feature disable kube/my-image layering,striping
```

### 7.2. Image is busy

**Ошибка**: Образ занят другим клиентом.

**Решение**:

```bash
# Проверка кто использует
rbd status kube/my-image

# Принудительное размаппинг
rbd unmap kube/my-image --force
```

### 7.3. Permission denied

**Ошибка**: Недостаточно прав у пользователя.

**Решение**:

```bash
# Проверка прав
ceph auth get client.user

# Исправление прав на сервере Ceph
ceph auth caps client.user mon 'allow r' osd 'allow rwx pool=kube'
```

---

## Ссылки

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Дополнительная информация](./advanced_topics.md) — производительность и бэкап
