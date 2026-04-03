# RBD: Маппинг, монтирование и troubleshooting

## Определения и базовые концепции

**Маппинг** — привязка RBD-образа к блочному устройству ядра (`/dev/rbdN`). Выполняется через `librbd` и модуль ядра `rbd`.

**Файловая система** — RBD-устройство требует форматирования перед использованием. Поддерживаемые ФС: `ext4`, `xfs`, `btrfs`.

**Автоматическое монтирование** — настройка маппинга и монтирования при загрузке. Требует опции `_netdev` для ожидания сети.

---

## Практические сценарии

### Маппинг образа

```bash
# Маппинг образа на устройство
sudo rbd map kube/my-image --id user

# Проверка замапленных устройств
rbd showmapped
```

Пример вывода `showmapped`:
```
dev    pool   name       ...
/dev/rbd0  kube   my-image   ...
```

### Создание файловой системы

```bash
# ext4
sudo mkfs.ext4 /dev/rbd0

# xfs
sudo mkfs.xfs /dev/rbd0
```

> **Внимание:** Форматирование уничтожает данные. Выполняйте только на новых образах.

### Монтирование

```bash
# Создание точки монтирования
sudo mkdir -p /mnt/rbd

# Монтирование
sudo mount /dev/rbd0 /mnt/rbd

# Проверка
df -h /mnt/rbd
```

### Демонтирование и размаппинг

```bash
# Демонтирование
sudo umount /mnt/rbd

# Размаппинг по устройству
sudo rbd unmap /dev/rbd0

# Размаппинг по имени образа
sudo rbd unmap kube/my-image

# Принудительное размаппинг (если устройство занято)
sudo rbd unmap kube/my-image --force
```

### Автоматическое монтирование

**Вариант 1: udev + fstab**

Создайте `/etc/udev/rules.d/50-rbd.rules`:

```bash
# Автоматический маппинг при загрузке
ACTION=="add", SUBSYSTEM=="rbd", ATTR{pool}=="kube", ATTR{name}=="my-image", \
  RUN+="/usr/bin/rbd map kube/my-image"
```

Получите UUID и добавьте в `/etc/fstab`:

```bash
blkid /dev/rbd0
```

```
UUID=<uuid> /mnt/rbd ext4 _netdev,noatime 0 0
```

**Вариант 2: systemd mount (рекомендуется)**

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

> **Критично:** Опция `_netdev` предотвращает зависание при загрузке, ожидая доступности сети. Без неё монтирование может произойти до инициализации сетевого стека.

### Устранение ошибок

**`RBD image features set mismatch`** — ядро не поддерживает функции образа.

```bash
# Отключение неподдерживаемых функций
rbd feature disable kube/my-image layering,striping
```

**`Image is busy`** — образ используется другим клиентом.

```bash
# Проверка активных клиентов
rbd status kube/my-image

# Принудительное размаппинг
rbd unmap kube/my-image --force
```

**`Permission denied`** — недостаточно прав у пользователя.

```bash
# Проверка текущих прав
ceph auth get client.user

# Исправление прав (на сервере Ceph)
ceph auth caps client.user mon 'allow r' osd 'allow rwx pool=kube'
```

---

## Дополнительная информация

- [Официальная документация RBD](https://docs.ceph.com/en/latest/rbd/rbd-map/)
- [Определения и концепции](./definitions_and_concepts.md) — image-features, требования к ядру
- [Установка и настройка](./installation_and_setup.md) — установка клиента
- [Управление образами](./image_management.md) — создание, изменение, удаление
