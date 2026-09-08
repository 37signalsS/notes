# RBD: Маппинг, монтирование и диагностика устройств

Документ описывает процессы подключения блочных устройств Ceph (RBD) к операционной системе на уровне ядра, создание файловых систем, автоматизацию монтирования, TRIM/discard операции и диагностику устройств. Предполагается знакомство с подготовкой клиентской среды (см. «[Установка и настройка клиента](./installation_and_setup.md)») и архитектурными основами RBD (см. «[Определения и фундаментальные концепции](./definitions_and_concepts.md)»).

## Определения

**Маппинг (Mapping)** — процесс привязки образа RBD к локальному блочному устройству через модуль ядра `krbd` (Kernel RBD). В результате в системе появляется виртуальное устройство (например, `/dev/rbd0`), которое ведет себя как физический диск.

**Размаппинг (Unmap)** — процесс отвязки образа RBD от блочного устройства. Перед размаппингом необходимо убедиться, что устройство не смонтировано и не используется процессами. Некорректный unmap приводит к зависанию процессов и ошибкам I/O.

**krbd (Kernel RBD module)** — драйвер ядра Linux, реализующий протокол взаимодействия с RADOS. Он быстрее, чем FUSE-решения, но ограничен версией ядра в поддержке новых функций Ceph.

**rbd-nbd** — пользовательский daemon, реализующий протокол NBD (Network Block Device) для RBD. В отличие от krbd, работает в пространстве пользователя и поддерживает все функции Ceph (кэш, шифрование, QoS), но с накладными расходами на контекстные переключения. Используется когда krbd не поддерживает необходимые функции (см. [Продвинутая оптимизация](./advanced_topics.md)).

**Discard / TRIM** — механизм уведомления СХД об удалении данных. Для RBD это критически важно, так как позволяет Ceph освобождать физическое место в пуле при удалении файлов внутри образа. Реализуется через команду `fstrim` или опцию монтирования `discard`.

**Device-mapper** — подсистема ядра Linux, предоставляющая абстракцию блочных устройств. krbd использует device-mapper для создания виртуальных устройств. Каждое смонтированное RBD-устройство — это объект device-mapper с именем `rbd-X`.

**Persistent Naming (udev)** — механизм присвоения стабильных имен блочным устройствам через правила udev. Позволяет ссылаться на RBD-устройства по пути `/dev/disk/by-id/rbd-<pool>-<image>-<id>` вместоolatile `/dev/rbd0`, который может измениться после перезагрузки.

**Watchers** — механизм отслеживания активных подключений к образу RBD. Каждый маппинг регистрирует Watcher на RADOS. Если образ имеет активных Watchers, его нельзя размаппить или удалить без предварительного отключения всех клиентов.

---

## Базовые концепции

### Взаимодействие с ядром и функции образа
При маппинге модуль ядра проверяет набор включенных функций образа (`image-features`). Если в образе включена функция, которую ядро не понимает (например, `fast-diff` на старых ядрах), маппинг будет отклонен.

**Требования ядра к функциям образа:**

| Функция | Минимальное ядро | Описание |
| :--- | :--- | :--- |
| `layering` | 2.6.32 | Клонирование и снапшоты (CoW/RoW) |
| `exclusive-lock` | 3.14 | Эксклюзивная блокировка для single-writer |
| `object-map` | 3.14 | Ускорение работы с большими образами |
| `fast-diff` | 3.14 | Быстрое определение измененных блоков |
| `deep-flatten` | 5.11 | Deep-flatten (см. [Управление образами](./image_management.md)) |
| `journaling` | 5.14 | Журналирование для crash consistency |
| `encryption` (LUKS) | 6.1 | Клиентское шифрование на уровне блоков |

*   **Рекомендация:** Для максимальной совместимости используйте ядро 5.14+ (поддерживает все функции кроме шифрования). Для шифрования — ядро 6.1+.

### Порядок маппинга и монтирования
1.  **Map:** Привязка образа к `/dev/rbdX` через `rbd map`.
2.  **Wait:** Ожидание появления устройства в sysfs (.Skip automounting setups).
3.  **Partition/Format:** Создание таблицы разделов (опционально) и файловой системы (если образ новый).
4.  **Mount:** Подключение ФС к директории с опциями `_netdev,noatime,discard`.

### Device-mapper и krbd
Модуль ядра `krbd` работает через подсистему device-mapper:
- При `rbd map` создается объект device-mapper типа `linear`.
- Каждому RBD-образу присваивается имя `rbd-<pool_id>-<image_id>` (UUID устройства).
- Управление устройством: `dmsetup status rbd-<id>`, `dmsetup remove rbd-<id>`.
- Device-mapper обеспечивает трассировку I/O и корректную обработку ошибок.

### Udev и именование устройств
Linux использует правила udev для присвоения стабильных имен блочным устройствам. RBD-устройства получают несколько вариантов именования:

```
/dev/rbd0                          #olatile порядковый номер
/dev/rbd/kube/my-image             # Путь с pool/image
/dev/disk/by-id/rbd-<pool>-<image>-<id>  # Стабильный ID (рекомендуется)
/dev/disk/by-path/...              # Физический путь (для NVMe/SATA)
```

**Важно:** `/dev/rbd0` —olatile. После перезагрузки или при добавлении нового устройства номер может измениться. Для автоматизации используйте стабильные имена из `/dev/disk/by-id/` или пути `/dev/rbd/pool/image`.

### Автоматизация: rbdmap vs fstab
*   **rbdmap (рекомендуется):** Специализированный сервис, который сначала выполняет `rbd map`, а затем монтирует файловые системы. Это более надежный метод, так как он корректно обрабатывает зависимости от сети и Ceph.
*   **fstab:** Можно использовать только с параметром `_netdev`, но требует, чтобы маппинг был уже выполнен другим инструментом. Рекомендуется комбинировать с systemd- unit для контроля порядка запуска.

---

## Практические сценарии

### 1. Ручное подключение устройства

```bash
# Маппинг образа (используется текущий пользователь из keyring)
sudo rbd map kube/my-image
# → /dev/rbd0

# Если нужно указать конкретного пользователя и секрет
sudo rbd map kube/my-image --id client.admin --keyring /etc/ceph/ceph.client.admin.keyring

# Просмотр статуса всех замапленных образов
rbd showmapped
# → pool  image         snap  id    device    size  shared
# → kube  my-image      -     0     /dev/rbd0 20GiB  1

# Альтернатива: информация через sysfs
ls -la /sys/block/rbd0/
cat /sys/block/rbd0/size  # Размер в секторах (512 байт)
```

### 2. Просмотр и проверка устройств

```bash
# Информация о конкретном устройстве через lsblk
lsblk /dev/rbd0
# → NAME   MAJ:MIN RM SIZE RO TYPE MOUNTPOINTS
# → rbd0   252:0    0  20G  0 disk

# Проверка через blkid (тип, UUID)
blkid /dev/rbd0
# → /dev/rbd0: TYPE="xfs" UUID="..." ...

# Проверка через udevadm (детальная информация)
udevadm info --query=all --name=/dev/rbd0
# → E: ID_PATH=rbd-kube-my-image
# → E: DEVNAME=/dev/rbd0

# Просмотр всех RBD-устройств
ls /dev/rbd*
# → /dev/rbd0  /dev/rbd1  /dev/rbd/kube/my-image

# Проверка device-mapper
dmsetup status rbd-*
# → rbd-0-1546738290: 0 41943040 linear
```

### 3. Подготовка файловой системы

Для RBD наиболее эффективна файловая система **XFS**.

```bash
# Определение типа текущей ФС на устройстве
blkid /dev/rbd0

# Форматирование XFS с оптимизацией для RBD
# -K (nodiscard) — отключение немедленного TRIM при форматировании
# -f — принудительное форматирование (если устройство не пустое)
sudo mkfs.xfs -K -f /dev/rbd0

# Форматирование ext4 с поддержкой TRIM
sudo mkfs.ext4 -E discard /dev/rbd0

# Проверка созданной ФС
xfs_info /dev/rbd0
# → meta-data=/dev/rbd0   isize=512    agcount=32, ...
```

### 4. Монтирование с оптимизацией

```bash
# Создание точки монтирования
sudo mkdir -p /mnt/data-rbd

# Монтирование с важными опциями:
# discard — включение TRIM (рекомендуется для SSD/thin provisioning)
# noatime — отключение записи времени последнего доступа (экономит IOPS)
# _netdev — пометка сетевого устройства для системных служб
sudo mount -o noatime,discard,_netdev /dev/rbd0 /mnt/data-rbd

# Проверка смонтированной ФС
mount | grep rbd
# → /dev/rbd0 on /mnt/data-rbd type xfs (rw,relatime,attr2,inode64,noatime,nodiscard,_netdev)

# Проверка опций через /proc/mounts
grep rbd0 /proc/mounts
```

### 5. TRIM/discard операции

TRIM критически важен для RBD с thin provisioning — без него Ceph не освобождает место в пуле.

```bash
# Вариант 1: опция при монтировании (непрерывный TRIM)
sudo mount -o discard /dev/rbd0 /mnt/data-rbd

# Вариант 2: периодический запуск fstrim (рекомендуется для production)
sudo fstrim -v /mnt/data-rbd
# → /mnt/data-rbd: 1 GiB (1073741824 bytes) trimmed

# Планирование через cron (еженедельно)
echo "0 2 * * 0 root fstrim -v /mnt/data-rbd >> /var/log/fstrim.log 2>&1" | \
  sudo tee /etc/cron.d/rbd-fstrim

# Проверка эффективности TRIM через Ceph
rbd du kube/my-image
# → NAME                 PROVISIONED  USED
# → kube/my-image@...         20 GiB  5 GiB  ← USED уменьшается после fstrim
```

### 6. Безопасное отключение (unmap)

```bash
# Шаг 1: Проверить, что устройство не смонтирован
mount | grep /dev/rbd0
# Если смонтировано — отмонтировать:
sudo umount /mnt/data-rbd

# Шаг 2: Проверить, что нет активных процессов
sudo lsof /dev/rbd0
# Если есть процессы — завершить их

# Шаг 3: Размаппинг
sudo rbd unmap /dev/rbd0

# Шаг 4: Проверка, что устройство удалено
ls /dev/rbd0
# → ls: cannot access '/dev/rbd0': No such file or directory

# Принудительный unmap (только если уверены, что данные не пишутся!)
sudo rbd unmap --force /dev/rbd0
```

### 7. Автоматизация через rbdmap (Ubuntu/Debian)

**Шаг 1: Настройка конфигурации**
Отредактируйте `/etc/ceph/rbdmap`. Формат: `pool/image [options]`.

```text
# /etc/ceph/rbdmap
kube/my-image id=admin,keyring=/etc/ceph/ceph.client.admin.keyring
kube/shared-data id=client.shared,keyring=/etc/ceph/ceph.client.shared.keyring
```

**Шаг 2: Настройка fstab**
`rbdmap` монтирует ФС, если они указаны в `fstab` и используют устройство `/dev/rbd/pool/image`.

```text
# /etc/fstab
/dev/rbd/kube/my-image     /mnt/data-rbd    xfs  noatime,discard,_netdev  0  0
/dev/rbd/kube/shared-data  /mnt/shared      xfs  noatime,discard,_netdev  0  0
```

**Шаг 3: Активация**
```bash
sudo systemctl enable rbdmap.service
sudo systemctl start rbdmap.service

# Проверка статуса
sudo systemctl status rbdmap.service
# → Active: active (exited) ...

# Просмотр логов
sudo journalctl -u rbdmap.service
```

### 8. Автоматизация через systemd (альтернатива rbdmap)

Для сценариев, где нужен более тонкий контроль порядка запуска:

```bash
# Создание unit-файла для маппинга
cat <<EOF | sudo tee /etc/systemd/system/rbd-my-image.service
[Unit]
Description=RBD mapping for my-image
After=network-online.target ceph-mon.target
Wants=network-online.target
Before=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/rbd map kube/my-image --id admin --keyring /etc/ceph/ceph.client.admin.keyring
ExecStop=/usr/sbin/rbd unmap /dev/rbd/kube/my-image
TimeoutStartSec=30
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

# Создание unit-файла для монтирования
cat <<EOF | sudo tee /etc/systemd/system/mnt-data-rbd.mount
[Unit]
Description=Mount RBD image my-image
After=rbd-my-image.service
Requires=rbd-my-image.service

[Mount]
What=/dev/rbd/kube/my-image
Where=/mnt/data-rbd
Type=xfs
Options=noatime,discard,_netdev

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable rbd-my-image.service mnt-data-rbd.mount
```

---

## Поиск неисправностей

### Ошибка: "features ... not supported by this kernel"
Ядро не поддерживает функции образа.
**Решение:** Отключите неподдерживаемые функции на стороне Ceph:
```bash
rbd feature disable kube/my-image object-map,fast-diff,deep-flatten
```
**Профилактика:** Проверяйте версию ядра перед созданием образов:
```bash
uname -r  # Рекомендуется 5.14+ для полной поддержки
```

### Устройство занято ("Image is busy")
Образ заблокирован другим клиентом (Watchers).
**Диагностика:**
```bash
rbd status kube/my-image
# → Watchers: 10.0.0.5:0 client.4132 ...
```
**Решение:** Зайдите на указанный хост и выполните `unmap`. Если хост недоступен, можно принудительно сбросить блокировку (только если вы уверены, что данные не пишутся!):
```bash
rbd lock list kube/my-image
rbd lock remove kube/my-image "lock-id" client.id
```

### Проблемы на уровне ядра (dmesg)
Если устройство ведет себя нестабильно (Read-only, таймауты):
```bash
dmesg | grep rbd
# Ищите ошибки: "libceph: connect ... failed", "rbd: image ... failed to map"
```
Причины часто кроются в MTU сети (должен быть одинаковым везде) или в файрволе на портах MON (6789) и OSD (6800-7300).

### Ошибка: "rbd: map failed" — не удалось подключить образ
**Возможные причины:**
1. Неверный ключ CephX: проверьте файл keyring и права доступа (`chmod 0600`).
2. MON недоступен: `ceph -s` покажет статус мониторов.
3. Несоответствие версий клиента и кластера.
4. Образ заблокирован другим процессом.

**Диагностика:**
```bash
# Проверка подключения к кластеру
ceph -s
# → cluster: HEALTH_OK

# Проверка прав доступа
ls -la /etc/ceph/ceph.client.admin.keyring
# → -rw------- 1 root root 158 ... /etc/ceph/ceph.client.admin.keyring

# Просмотр подробной ошибки
rbd map kube/my-image --id admin --keyring /etc/ceph/ceph.client.admin.keyring
# → rbd: couldn't connect ...
```

### Устройство не отображается после маппинга
**Причина:** Устройство не появилось в `/dev/` после `rbd map`.
**Диагностика:**
```bash
# Проверка через sysfs
ls /sys/block/rbd*

# Проверка device-mapper
dmsetup ls
# → rbd-0-1546738290  (252, 0)

# Перезагрузка правил udev
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Ошибка при монтировании: "wrong fs type, bad option"
**Причина:** Файловая система не создана или неверные опции монтирования.
**Диагностика:**
```bash
# Проверка типа ФС
blkid /dev/rbd0
# → /dev/rbd0: TYPE="xfs" ...

# Проверка опций
mount -o noatime,discard,_netdev /dev/rbd0 /mnt/test 2>&1
# → mount: (specific error message)
```

### TRIM не освобождает место в пуле
**Причина:** TRIM не включен или thin provisioning не активирован.
**Диагностика:**
```bash
# Проверка использования перед/после fstrim
rbd du kube/my-image

# Запуск fstrim
sudo fstrim -v /mnt/data-rbd

# Проверка через 1-2 минуты (Ceph обновляет статистику)
rbd du kube/my-image
```

### Образ не удаляется ("image has snapshots")
**Причина:** Существуют снапшоты или дочерние клоны.
**Решение:** См. [Управление образами](./image_management.md#4-работа-со-снапшотами-и-клонами).

### rbdmap не монтирует образы при загрузке
**Диагностика:**
```bash
# Проверка статуса службы
sudo systemctl status rbdmap.service

# Просмотр логов
sudo journalctl -u rbdmap.service -n 50

# Проверка конфигурации
cat /etc/ceph/rbdmap

# Ручной запуск для отладки
sudo rbdmap map
```

### Отказ в доступе (Permission denied)
**Причина:** Неверные права на keyring или отсутствие CephX авторизации.
**Решение:**
```bash
# Проверка прав на keyring
ls -la /etc/ceph/ceph.client.*.keyring
# → -rw------- 1 root root 158 ...  (должно быть 0600)

# Проверка прав доступа к образу
rbd info kube/my-image --id admin --keyring /etc/ceph/ceph.client.admin.keyring

# Просмотр caps пользователя
ceph auth get client.admin
# → caps: [mds] allow *; [mgr] allow *; [osd] allow *; [mon] allow *
```

---

## Дополнительная информация

### Связанные темы
- [Установка клиента Ceph](./installation_and_setup.md) — подготовка окружения и загрузка модуля ядра.
- [Управление образами RBD](./image_management.md) — создание, ресайз, снапшоты, удаление.
- [Определения и базовые концепции](./definitions_and_concepts.md) — архитектура RBD и основные механизмы.
- [Продвинутая оптимизация RBD](./advanced_topics.md) — сравнение krbd/librbd/rbd-nbd, шифрование, кэширование.
- [Обзор протокола Messenger v2](../ceph_overview.md#сетевой-стек-messenger-v2) — детали сетевого взаимодействия.

### Ресурсы
- [Ceph Documentation: RBD Kernel Object (krbd)](https://docs.ceph.com/en/latest/rbd/rbd-ko/)
- [Ceph Documentation: RBD NBD](https://docs.ceph.com/en/latest/rbd/rbd-nbd/)
- [Linux kernel: device-mapper documentation](https://www.kernel.org/doc/html/latest/admin-guide/device-mapper.html)
