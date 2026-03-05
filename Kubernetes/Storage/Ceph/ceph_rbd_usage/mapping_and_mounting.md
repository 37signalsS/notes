# RBD: Маппинг, монтирование и troubleshooting

## 1. Маппинг образа

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

---

## 2. Создание файловой системы

```bash
# Только для нового образа!
sudo mkfs.ext4 /dev/rbd0

# Или xfs
sudo mkfs.xfs /dev/rbd0
```

---

## 3. Монтирование

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

## 5. Автоматическое монтирование

### Настройка udev правила

Создайте файл `/etc/udev/rules.d/50-rbd.rules`:

```bash
# Автоматический маппинг при загрузке
ACTION=="add", SUBSYSTEM=="rbd", ATTR{pool}=="kube", ATTR{name}=="my-image", \
  RUN+="/usr/bin/rbd map kube/my-image"
```

### Настройка /etc/fstab

```bash
# Получение UUID образа
blkid /dev/rbd0

# Добавление в /etc/fstab
UUID=<uuid> /mnt/rbd ext4 _netdev,noatime 0 0

# Или по устройству
/dev/rbd0 /mnt/rbd ext4 _netdev,noatime 0 0
```

> **Важно**: Опция `_netdev` критична! Без неё система может зависнуть при загрузке.

### Альтернатива: systemd mount

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

## 6. Устранение ошибок

### RBD image features set mismatch

**Ошибка**: Ядро не поддерживает функции образа.

**Решение**:

```bash
# Отключение неподдерживаемых функций
rbd feature disable kube/my-image layering,striping
```

### Image is busy

**Ошибка**: Образ занят другим клиентом.

**Решение**:

```bash
# Проверка кто использует
rbd status kube/my-image

# Принудительное размаппинг
rbd unmap kube/my-image --force
```

### Permission denied

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

- **[Установка и настройка](./installation_and_setup.md)** — установка клиента
- **[Управление образами](./image_management.md)** — создание, изменение, удаление
- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
