# Пространства имён монтирования (Mount Namespaces)

В данном файле рассматриваются механизмы изоляции файловых систем в Linux с использованием **Mount Namespaces**, управление распространением событий монтирования (**Mount Propagation**) и современные возможности ядра (New Mount API, ID-mapped mounts).

Общий обзор всех типов пространств имен доступен в [Пространства имён (namespaces)](../Core/namespaces.md).

## Определения

**Mount namespace (`CLONE_NEWNS`)** — первое пространство имен, появившееся в Linux (2.4.19, 2002 год). Оно изолирует список точек монтирования, видимых группой процессов. Это позволяет процессам иметь собственный вид иерархии файловой системы (например, изолировать `/tmp`, подменять `/proc` или создавать "песочницы" для приложений).

**Mount propagation (Распространение монтирования)** — механизм (появился в ядре 2.6.15), определяющий, как события монтирования или размонтирования (`mount`/`umount`) передаются между пространствами имен. Это решает проблему "статичной изоляции", позволяя, например, хосту пробрасывать новые диски во все запущенные контейнеры.

**Shared Subtree (Разделяемые поддеревья)** — технология объединения точек монтирования в группы для обмена событиями.

**Peer group (Группа равных)** — группа точек монтирования, которые являются зеркалами друг друга. Событие в одной точке группы автоматически повторяется во всех остальных точках этой группы.

**Detached Mount (Отсоединенное монтирование)** — (Linux 5.2+) монтирование, которое существует в памяти ядра и имеет файловый дескриптор, но не прикреплено ни к одной точке в дереве файловой системы. Используется для безопасной подготовки rootfs.

**VFS (Virtual File System)** — слой абстракции ядра, через который все запросы на чтение/запись проходят перед тем, как достичь конкретной файловой системы. Mount Namespace изменяет представление VFS для группы процессов, не затрагивая физические устройства.

## Базовые концепции

### Взаимодействие с VFS

Каждый Mount Namespace имеет собственную корневую точку (`/`) и независимую таблицу связей VFS → конкретная ФС. Когда процесс выполняет `open("/etc/passwd")`, ядро:
1. Определяет Mount Namespace процесса.
2. Обходит его дерево монтирования (mount tree) от текущего рабощего каталога.
3. Возвращает inode из соответствующей файловой системы.

**Важно:** Если два процесса разделяют Mount Namespace, они используют **один и тот же** mount tree. Это значит, что `mount --bind /data /data` в одном процессе мгновенно виден в другом.

### Группы Peer Groups и идентификация

Связи между пространствами имен отслеживаются через идентификаторы групп в `/proc/self/mountinfo`:

- **`shared:X`**: Точка монтирования входит в peer group `X`. Отправляет и получает события.
- **`master:X`**: Точка является «рабом» (slave) группы `X`. Только получает события от мастеров группы `X`.
- **`propagate_from:X`**: (для slave) указывает, от какой группы приходят события.

### Флаги распространения монтирования (Propagation flags)

| Флаг | Поведение | Направление |
| :--- | :--- | :--- |
| **`MS_SHARED`** | События распространяются на все точки в peer group. | Двустороннее (Parent ↔ Child) |
| **`MS_PRIVATE`** | Точка полностью изолирована. События не уходят и не приходят. | Изолированное (Default во многих ОС) |
| **`MS_SLAVE`** | Получает события от мастера, но не отправляет свои. | Одностороннее (Parent → Child) |
| **`MS_UNBINDABLE`**| Приватная точка, которую нельзя использовать как источник для bind mount. | Защита от рекурсивных петель |

**Рекурсивные флаги (`rshared`, `rslave`, `rprivate`):** применяют режим распространения ко всей иерархии внутри указанной точки монтирования.

### Наследование при создании namespace

При вызове `clone(CLONE_NEWNS)` или `unshare --mount`:
1. Новый namespace получает **копию** таблицы монтирования родителя.
2. Флаги распространения копируются. Если точка была `shared`, и родитель, и потомок теперь в одной peer group.
3. Чтобы полностью изолировать потомка сразу после создания, часто выполняют:
   `mount --make-rprivate /`

### Механизмы смены корня: chroot vs pivot_root

Для контейнеризации Mount Namespace используется совместно со сменой корня:

- **`chroot`**: Меняет логический корень для процесса. **Небезопасно**: процесс может выйти за пределы через `..` (если есть доступ к дескрипторам вне корня). Не изменяет таблицу монтирования.
- **`pivot_root`**: (Рекомендуется) Атомарно перемещает старый корень в поддиректорию нового и делает новый корень основным. Позволяет полностью отмонтировать старую ФС хоста (`umount -l /old_root`), исключая возможность "побега".

### Взаимодействие с cgroup namespace

Mount Namespace и cgroup namespace тесно связаны:

- Без изолированного Mount Namespace процесс может обойти cgroup namespace, перемонтировав `/sys/fs/cgroup` хоста. Для полной изоляции используйте `unshare --cgroup --mount`.
- В cgroup v2 cgroup namespace скрывает только версии контроллеров, но не файлы ресурсов. Mount Namespace дополнительно скрывает путь к ФС cgroup.
- При создании контейнера systemd требует делегирования cgroup: `lxc.cgroup2.delegate = 1` для корректного управления службами внутри контейнера.

## Новый API монтирования (Linux 5.2+)

В ядре 5.2 старый монолитный системный вызов `mount(2)` был заменен на набор дескрипторных вызовов. Это решило проблемы безопасности (состояния гонки по путям) и позволило создавать "невидимые" монтирования.

**Основные вызовы:**
1. **`fsopen()`**: Создание контекста ФС (например, `ext4`). Возвращает дескриптор `fs_fd`.
2. **`fsconfig()`**: Настройка параметров через дескриптор (вместо текстовой строки опций).
3. **`fsmount()`**: Создание **detached mount** на основе настроенного контекста.
4. **`move_mount()`**: Атомарное прикрепление (или перемещение) монтирования в дерево ФС.
5. **`open_tree()`**: Получение дескриптора существующего дерева монтирования.

**SRE-профит:** Позволяет подготовить всю иерархию монтирований контейнера в памяти, проверить её и одним вызовом `move_mount` подменить корень, избегая промежуточных небезопасных состояний.

## ID-mapped mounts (Linux 5.12+)

Механизм, позволяющий менять владельцев (UID/GID) файлов на уровне монтирования, не изменяя их на диске.

**Применение:**
- **Shared Storage**: Один и тот же диск монтируется в два контейнера с разными User Namespaces. В каждом контейнере файлы выглядят так, будто принадлежат локальному root.
- **systemd-homed**: Переносимые домашние директории.
- **Производительность**: Устраняет необходимость в рекурсивном `chown` при старте контейнера.

Настройка выполняется через `mount_setattr(2)` с передачей дескриптора User Namespace.

## Диагностика и анализ

### Анализ через mountinfo

```bash
# Просмотр propagation и peer groups
cat /proc/self/mountinfo | grep /mnt/data
# 156 35 8:1 / /mnt/data rw,relatime shared:1 - ext4 /dev/sda1 rw
```
*Здесь `shared:1` означает, что любые `mount` внутри `/mnt/data` на хосте появятся и в контейнере, если тот в этой же группе.*

### Анализ namespace процесса

```bash
# Просмотр всех namespace процесса
ls -l /proc/<PID>/ns/

# Пример вывода:
# lrwxrwxrwx 1 root root 0 Sep  6 12:00 mnt -> 'mnt:[4026531840]'
# lrwxrwxrwx 1 root root 0 Sep  6 12:00 net -> 'net:[4026531841]'

# Сравнение mount namespace двух процессов
readlink /proc/$PID1/ns/mnt
readlink /proc/$PID2/ns/mnt
# Если вывод идентичен — процессы разделяют один Mount Namespace
```

### Инструменты управления

```bash
# Просмотр дерева с типами распространения
findmnt -o SOURCE,TARGET,PROPAGATION

# Создание нового namespace с изоляцией от родителя
unshare --mount --map-root-user --make-private /bin/bash

# Проверка Peer Group ID
findmnt -n -o PROPAGATION /

# Вход в mount namespace другого процесса
nsenter -t <PID> -m -- mount

# Просмотр всех mount namespaces в системе
lsns -t mnt
```

### Проверка propagation конкретной точки

```bash
# Подробный анализ точки монтирования
findmnt -T /mnt/data

# Просмотр mountinfo для конкретного пути
cat /proc/self/mountinfo | grep -E " /mnt/data | /mnt/data "

# Проверка флагов через stat
stat -f -c "%T" /mnt/data
# → 0x10000000 (MS_SHARED)
```

## Практические сценарии

### Создание изолированной среды через unshare

```bash
# Создание полностью изолированного окружения с новыми PID, Mount, Network namespace
# -r эквивалентно --map-root-user
unshare -n -p -m -r --fork bash

# Внутри нового namespace:
mount -t proc proc /proc          # Только свои процессы
ip link set lo up                  # Активация loopback
mount --make-rprivate /            # Полная изоляция монтирования
```

### Изоляция службы systemd через Mount Namespace

Systemd использует Mount Namespaces для sandboxing'а служб:
- `ReadOnlyPaths=/etc`: создается новый namespace, где `/etc` перемонтирован как RO.
- `ProtectSystem=full`: делает `/usr`, `/boot` и `/etc` доступными только для чтения для службы.
- `MountFlags=slave`: (по умолчанию во многих юнитах) позволяет службе видеть новые диски хоста, но не позволяет ей "мусорить" в таблице монтирования хоста.

**Пример юнита systemd с изоляцией монтирования:**

```ini
# /etc/systemd/system/isolated-app.service
[Unit]
Description=Изолированное приложение
After=network.target

[Service]
ExecStart=/usr/local/bin/my-app
Type=simple
User=appuser

# Изоляция Mount Namespace
ProtectSystem=strict
ReadOnlyPaths=/etc
ReadWritePaths=/var/lib/app
ProtectHome=true
MountFlags=slave

# Дополнительные ограничения
NoNewPrivileges=true
PrivateTmp=true
```

**Проверка:**
```bash
systemctl daemon-reload
systemctl start isolated-app
sudo lsns -p $(systemctl show --property=MainPID --value isolated-app)
# В выводе будет отдельный mnt namespace
```

### Постоянное пространство имён через bind mount

По умолчанию пространство имён уничтожается при завершении последнего процесса. Для персистентности создайте bind mount:

```bash
# Создание изолированного namespace
PID=$(sudo unshare --mount --fork -- bash -c 'echo $$')

# Закрепление namespace через bind mount
sudo mkdir -p /run/mntns
sudo mount --bind /proc/$PID/ns/mnt /run/mntns/my-service

# Проверка: namespace переживает завершение процесса
# Теперь можно использовать:
sudo nsenter --mount=/run/mntns/my-service -- mount
```

### Подготовка rootfs для контейнера (New Mount API)

```bash
# Подготовка rootfs в detached mount (ядро 5.2+)
# Позволяет безопасно подготовить ФС перед подменой корня

# 1. Создание пустой директории для нового rootfs
mkdir -p /tmp/container-rootfs/{proc,sys,dev,run}

# 2. Монтирование proc/sys/dev
mount -t proc proc /tmp/container-rootfs/proc
mount -t sysfs sysfs /tmp/container-rootfs/sys
mount --bind /dev /tmp/container-rootfs/dev

# 3. Распаковка образа в rootfs
tar xzf rootfs.tar.gz -C /tmp/container-rootfs

# 4. Атомарная смена корня через pivot_root
cd /tmp/container-rootfs
mkdir -p .old
pivot_root . .old
umount -l /old
```

### Shared storage между контейнерами (ID-mapped mounts)

```bash
# Создание User Namespace с маппингом
# /etc/subuid и /etc/subgid должны содержать:
# user1:100000:65536

# Монтирование диска с ID-mapping (ядро 5.12+)
# Контейнер user1 видит файлы как принадлежащие ему
sudo mount --bind /dev/sdb1 /mnt/shared
sudo mount --make-rshared /mnt/shared
sudo mount_setattr /mnt/shared -m --idmap=user1:0:100000:65536

# Теперь в контейнере user1 (UID 0 -> Host UID 100000)
# файлы выглядят как owned by root, без рекурсивного chown
```

### systemd-nspawn: легковесные изолированные окружения

`systemd-nspawn` — инструмент для запуска полной ОС в контейнере, использующий Mount Namespace:

```bash
# Запуск дистрибутива из каталога
sudo systemd-nspawn -D /var/lib/machines/ubuntu --boot

# С изоляциейMount Namespace (по умолчанию)
sudo systemd-nspawn -D /var/lib/machines/ubuntu \
  --read-only \
  --tmpfs=/var/log \
  --bind=/etc/hostname:/etc/hostname \
  --private-users \
  --machine=test01
```

### Взаимодействие с LXC/Podman

В контейнерных рантаймах Mount Namespace критичен для изоляции:

```bash
# LXC: настройка монтирования в конфиге
lxc.mount.auto = proc:rw sys:rw cgroup:rw
lxc.mount.entry = /dev/shm dev/shm none bind,optional,create=dir

# Podman: монтирование с propagation
podman run -v /host/data:/container/data:rslave ...

# Docker: host-to-container propagation
docker run -v /host/logs:/var/log/app:ro,rslave ...
```

### Диагностика проблем монтирования

**Проблема: "target is busy" при размонтировании**
```bash
# Поиск процессов, удерживающих ФС
sudo lsof +D /mnt/data
sudo fuser -vm /mnt/data

# Принудительное размонтирование (опасно!)
sudo umount -l /mnt/data
```

**Проблема: mount не появляется в контейнере**
```bash
# Проверка propagation на хосте
findmnt -T /host/path
# Должен быть MS_SHARED для двусторонней синхронизации

# Проверка mount namespace контейнера
PID=$(docker inspect -f '{{.State.Pid}}' container)
sudo nsenter -t $PID -m -- mount | grep /container/path
```

**Проблема: контейнер "видит"mount хоста**
```bash
# Проверка, что / смонтирована как private
findmnt -n -o PROPAGATION /
# Должно быть private

# Исправление
sudo mount --make-rprivate /
```

## Безопасность

### Угрозы и mitigation

1. **Escape через bind mount:** Злоумышленник внутри контейнера может попытаться монтировать чувствительные файлы хоста. **Mitigation:** Используйте `MS_UNBINDABLE` для критичных точек и `AppArmor`/`SELinux` профили.

2. **Race condition при монтировании:** Старый `mount(2)` уязвим к симлинковым атакам. **Mitigation:** Используйте New Mount API (`mount_setattr`, `move_mount`) с проверенными дескрипторами.

3. **Leak информации через /proc/mounts:** Внутри контейнера виден полный список mount хоста, если `/proc` не изолирован. **Mitigation:** Всегда монтируйте отдельный `/proc` через `mount -t proc proc /proc` или используйте `hidepid=2`.

4. **Коллизии peer group:** Если хост использует `MS_SHARED` для критичных путей, контейнер может получить неожиданные монтирования. **Mitigation:** Сразу после `unshare` выполняйте `mount --make-rprivate /`.

### Жесткий контур (Hardening checklist)

```bash
# 1. Изоляция после unshare
unshare --mount --map-root-user bash
mount --make-rprivate /
mount --make-runprivate /tmp
mount --make-runprivate /var/tmp

# 2. Ограничение видимости /proc
mount -t proc proc /proc -o nosuid,noexec,nodev,hidepid=2

# 3. Запрет новых монтирований (seccomp + mount namespace)
# В конфиге LXC:
lxc.cap.drop = sys_admin
lxc.seccomp.profile = seccomp-default.json
```

## Производительность

- **Bind mount:** Минимальные накладные расходы (<1%). Используйте `mount --bind` без копирования данных.
- **OverlayFS:** Добавляет overhead на lookup и copy-up. Для часто изменяемых файлов используйте upperdir на tmpfs.
- **Mount propagation:** События propagation добавляют минимальную задержку (микросекунды), но при частых монтированиях/размонтировании на хосте это может вызвать "thunder herd" в контейнерах.
- **New Mount API:** Нет накладных расходов по сравнению со старым `mount(2)`, но требует ядро 5.2+.

## Ограничения и известные проблемы

1. **Mount namespace + NFS:** NFSv4 имеет глобальный state, который не изолируется mount namespace. Операции монтирования могут влиять на глобальные блокировки NFS.
2. **Mount namespace + FUSE:** Некоторые FFS-файловые системы (например, sshfs) не поддерживают корректную работу в изолированном mount namespace без дополнительных флагов.
3. **Nested mount namespaces:** Глубина вложенности ограничена реализацией ядра. На практике более 8–16 уровней могут вызывать деградацию производительности.
4. **Mount namespace + seccomp:** Seccomp-фильтр по умолчанию блокирует `mount(2)` без `MS_BIND`. Для контейнеров, требующих монтирования, нужно явно разрешить `mount` и `umount2`.
5. **Loop devices:** Устройства `/dev/loopX` являются глобальными для системы. Loop mount внутри mount namespace виден на хосте.
6. **/proc/mounts vs /proc/self/mountinfo:** `/proc/mounts` показывает монтирования только текущего namespace, а `mountinfo` — полную информацию с peer groups.

## Troubleshooting

### Частые ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **"mount: /mnt: mount point does not exist."** | Директория не создана или находится в другой ФС. | `mkdir -p /mnt && mount --bind /mnt /mnt` |
| **"target is busy"** | Процесс удерживает ФС или CWD внутри. | `lsof +D /mnt` / `fuser -vm /mnt` / `umount -l` |
| **Mount не видны в контейнере** | Propagation не настроен (MS_PRIVATE вместо MS_SHARED). | `mount --make-shared /host/path` |
| **Container sees host mounts** | Корень хоста не rprivate. | `mount --make-rprivate /` на хосте |
| **Permission denied на mount** | Нет CAP_SYS_ADMIN или seccomp блокирует. | Проверьте `capabilities` и seccomp-профиль |
| **Detached mount "висит"** | Не использован `fsmount`/`move_mount` или забыт `umount`. | Убедитесь, что все detached mount прикреплены или размонтированы |
| **pivot_root: failed** | Новый корень не является mount point или старый корень не tmpfs. | `mount --make-private /new_root && pivot_root /new_root /new_root/old` |

### Диагностические команды

```bash
# Полный анализ mount namespaces системы
sudo lsns -t mnt

# Проверка, какие процессы используют конкретную ФС
sudo lsof +f -- /mnt/data

# Поиск "застрявших" mount points
findmnt --fstab --verify

# Проверка propagation для всех точек
findmnt -o TARGET,PROPAGATION,FSTYPE | grep -v private
```

## Best Practices

1. **Всегда изолируйте корень после unshare:** `mount --make-rprivate /` — это baseline для любых изолированных окружений.
2. **Используйте MS_SLAVE для служб:** Это позволяет службе видеть новые диски хоста, но не позволяет ей влиять на таблицу монтирования хоста.
3. **Не используйте MS_SHARED без необходимости:** Двусторонняя синхронизация опасна и может привести к неожиданному поведению.
4. **Монтируйте /proc отдельно:** В каждом mount namespace с PID namespace монтируйте `/proc` явно: `mount -t proc proc /proc`.
5. **Используйте New Mount API там, где возможно:** На ядрах 5.2+ это безопаснее и позволяет атомарные операции.
6. **ID-mapped mounts вместо chown:** Для shared storage между контейнерами с разными UID используйте `mount_setattr` вместо рекурсивного `chown`.
7. **Документируйте propagation:** В конфигурациях инфеструктуры явно указывайте propagation mode для каждого bind mount.
8. **Мониторьте mount storms:** Частые события монтирования на хосте (особенно с `MS_SHARED`) могут вызывать лавину событий в контейнерах. Используйте `auditd` или `bpftrace` для отслеживания.

## Дополнительная информация

### Сводная таблица системных вызовов

| Вызов | Описание |
| :--- | :--- |
| `mount(2)` | Устаревший монолитный вызов для монтирования. |
| `unshare(CLONE_NEWNS)` | Переход текущего процесса в новый mount namespace. |
| `setns(fd, CLONE_NEWNS)` | Переход в namespace другого процесса по его дескриптору. |
| `pivot_root(2)` | Безопасная смена корня для контейнеров. |
| `mount_setattr(2)` | (Linux 5.12+) Установка атрибутов монтирования и ID-mapping. |
| `fsopen(2)` | (Linux 5.2+) Создание контекста ФС. |
| `fsmount(2)` | (Linux 5.2+) Создание detached mount. |
| `move_mount(2)` | (Linux 5.2+) Атомарное перемещение монтирования в дерево. |
| `open_tree(2)` | (Linux 5.2+) Получение дескриптора дерева монтирования. |

### См. также

- [Namespaces ядра Linux: Общий обзор](../Core/namespaces.md)
- [Системный вызов chroot (изменение корня)](../Core/chroot.md)
- [Управление монтированию в Linux](../FileSystems/mounting/index.md)
- [Изоляция в Linux: Namespaces и Cgroups (Docker context)](../../Docker/Concepts/linux_isolation.md)
