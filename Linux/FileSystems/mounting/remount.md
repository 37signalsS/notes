# Определения

**Перемонтирование (Remount)** — операция изменения параметров уже смонтированной файловой системы без её предварительного размонтирования (`umount`). 

Этот механизм позволяет ядру перенастроить драйвер файловой системы и параметры VFS (Virtual File System) «на лету», сохраняя доступ к данным для запущенных процессов и открытых файловых дескрипторов.

# Основные концепции

## Назначение и преимущества

Главное преимущество перемонтирования — **непрерывность работы**. В отличие от цикла `umount` + `mount`, при `remount`:
- Процессы не получают ошибок `EBUSY` (за исключением перехода в `ro`, если есть активная запись).
- Не требуется закрывать открытые файлы или останавливать системные сервисы.
- Сохраняется состояние кэша страниц (page cache) в оперативной памяти.

Это единственный способ изменения параметров для **корневой файловой системы (`/`)** и других критических разделов, которые невозможно размонтировать в работающей системе.

## Синтаксис и правила использования

```bash
# Общий синтаксис
sudo mount -o remount,<новые_опции> <точка_монтирования | устройство>

# Пример для корневой ФС (переход в режим записи)
sudo mount -o remount,rw /
```

**Критическое правило:** При выполнении `remount` вы должны указывать **только те опции, которые хотите изменить**. Остальные параметры будут наследоваться из текущего состояния монтирования или из `/etc/fstab` (если точка монтирования там описана).

## Механика на уровне ядра

1.  **VFS Layer**: Ядро идентифицирует суперблок смонтированной ФС.
2.  **Safety Checks**: Проверяется возможность применения новых опций.
3.  **Driver Callback**: Вызывается специфичная для ФС функция (например, `ext4_remount`), которая обновляет внутренние структуры драйвера.
4.  **Kernel 5.2+ API**: В новых ядрах операция перемонтирования реализована через набор системных вызовов `fsopen`, `fspick` и `fsconfig`, что обеспечивает большую атомарность и безопасность по сравнению со старым вызовом `mount(2)`.

## Remount при загрузке системы

При загрузке systemd создаёт временные `.mount` юниты из `/etc/fstab` через `systemd-fstab-generator`. Затем запускается сервис `systemd-remount-fs.service`, который выполняет все `remount` из fstab, которые помечены как `nofail` или являются корневой ФС.

**Важно:** Если `systemd-remount-fs.service` завершается с ошибкой, система может перейти в Emergency Mode. Причиной обычно является:
- Неверные опции в `/etc/fstab`
- Отсутствие устройства (внешний диск не подключён)
- Несовместимые опции для текущей ФС

```bash
# Проверка статуса сервиса после загрузки
sudo systemctl status systemd-remount-fs.service

# Просмотр логов, если сервис упал
sudo journalctl -u systemd-remount-fs.service --no-pager
```

## Идемпотентный remount

Вызов `mount -o remount /точка` **без указания конкретных опций** является особым случаем. В этом случае ядро перечитывает соответствующую строку в `/etc/fstab` и применяет все опции, указанные там. Это единственный способ применить изменения из fstab к уже смонтированной ФС без перезагрузки.

```bash
# После редактирования /etc/fstab — применить изменения к корню
sudo mount -o remount /

# Проверить, что опции применились
findmnt / | grep -o 'ro\|rw'
```

# Практические сценарии

## 1. Изменение режима доступа (ro/rw)

Самый частый сценарий при восстановлении системы или защите данных от изменений.

| Задача | Команда | Контекст |
| :--- | :--- | :--- |
| **Аварийный доступ** | `mount -o remount,rw /` | Редактирование конфигов в режиме восстановления (Recovery) |
| **Защита данных** | `sync && mount -o remount,ro /data` | Защита от записи перед работами с оборудованием |
| **Проверка ФС** | `mount -o remount,ro /home` | Перевод в `ro` для запуска `fsck` на «живой» системе |

> **Важно:** Всегда выполняйте команду `sync` перед перемонтированием в `ro`, чтобы гарантировать сброс всех буферов записи на физический диск.

## 2. Изменение размера tmpfs на лету

Для файловых систем в оперативной памяти (`tmpfs`) можно изменять лимит размера без потери данных:

```bash
sudo mount -o remount,size=4G /tmp
# → ФС /tmp теперь имеет лимит 4 ГБ, текущие данные сохранены
```

## 3. Перемонтирование Bind Mounts

Для изменения прав доступа к «зеркальным» директориям (например, сделать проброшенную папку доступной только для чтения) используется специфичный синтаксис:

```bash
# 1. Создание bind mount (наследует права источника)
sudo mount --bind /source /target

# 2. Изменение прав только для точки назначения (например, сделать ее RO)
sudo mount -o remount,bind,ro /target
```

## 4. Управление производительностью и SSD

*   **TRIM (Discard):** Включение онлайн-очистки блоков.
    ```bash
    sudo mount -o remount,discard /
    ```
*   **Время доступа (atime):** Отключение обновлений `atime` для минимизации лишних записей.
    ```bash
    sudo mount -o remount,noatime /var/lib/mysql
    ```

## 5. Тюнинг интервала фиксации журнала (ext4/XFS)

Интервал фиксации (commit interval) определяет, как часто журнал ФС сбрасывается на диск. По умолчанию ext4 использует 5 секунд, XFS — 30 секунд. Увеличение интервала снижает I/O, но увеличивает риск потери данных при сбое питания.

```bash
# ext4: увеличение интервала до 60 секунд + отключение упорядочивания данных
# Требует journaling (см. Журналирование файловых систем)
sudo mount -o remount,commit=60,data=writeback /mnt/data

# XFS: увеличение буферов лога в памяти (макс. 256k или 8 буферов по 32k)
sudo mount -o remount,logbsize=256k /mnt/xfs_data
```

> **Важно:** Режим `data=writeback` уязвим при сбое питания — данные, записанные между фиксациями, могут быть потеряны. Используйте только на временных или восстанавливаемых данных.

## 6. Управление /dev/shm (shared memory)

`/dev/shm` — это tmpfs, используемый для Shared Memory (POSIX) и tmpfs-файловых систем (например, PostgreSQL `temp_tablespaces`). Размер по умолчанию равен половине оперативной памяти, что может быть недостаточно для баз данных или может занимать слишком много места на серверах с большим объёмом RAM.

```bash
# Просмотр текущего размера
df -h /dev/shm

# Изменение размера на лету
sudo mount -o remount,size=4G /dev/shm

# В fstab для постоянного применения
# tmpfs /dev/shm tmpfs defaults,size=4G,noexec,nosuid,nodev 0 0
```

## 7. Включение ACL и расширенных атрибутов

На современных дистрибутивах `acl` и `user_xattr` включены по умолчанию для ext4/XFS. Однако на устаревших системах или при создании ФС без этих опций требуется перемонтирование:

```bash
# Проверка текущих опций
mount | grep ' on /home '

# Включение ACL (если не активна)
sudo mount -o remount,acl /home

# Включение расширенных атрибутов (xattr)
sudo mount -o remount,user_xattr /home
```

## 8. NFS/CIFS — перемонтирование с новыми опциями

При сбоях сети или изменении конфигурации NFS-сервера требуется перемонтирование с новыми параметрами таймаутов:

```bash
# NFS: изменение кэширования атрибутов (actimeo) и поведения при потере связи
sudo mount -o remount,actimeo=0,hard,timeo=50,retrans=3 /mnt/nfs_share

# CIFS/SMB: обновление учётных данных (через remount с новыми опциями)
sudo mount -o remount,username=newuser,password=newpass //server/share /mnt/smb
```

# Интеграция с systemd

Systemd управляет перемонтированием на двух уровнях: через сервис `systemd-remount-fs.service` при загрузке и через `.mount` юниты для отдельных точек.

## systemd-remount-fs.service

Этот сервис отвечает за применение `remount` из fstab после монтирования корневой ФС. Если сервис падает, система переходит в Emergency Mode.

```bash
# Просмотр статуса
sudo systemctl status systemd-remount-fs.service

# Перезапуск (например, после редактирования fstab без перезагрузки)
sudo systemctl restart systemd-remount-fs.service
```

## Drop-in переопределения для .mount юнитов

Для постоянного применения опций перемонтирования к конкретной точке можно создать drop-in файл:

```bash
# Пример: постоянный remount /data с новыми опциями
sudo systemctl edit --full mnt-data.mount
# Или только переопределение опций:
sudo mkdir -p /etc/systemd/system/mnt-data.mount.d
cat << 'EOF' | sudo tee /etc/systemd/system/mnt-data.mount.d/override.conf
[Mount]
Options=defaults,noatime,nodiratime,commit=60
EOF

# Применение без перезагрузки
sudo systemctl daemon-reload
sudo systemctl restart mnt-data.mount
```

> **Правило:** Drop-in файлы в `.d/` имеют приоритет над исходным юнитом. Это стандартный способ изменения опций mount юнитов, сгенерированных из fstab.

## Практический сценарий: Безопасный remount через systemd

```bash
# Создание сервиса, который remount-ит ФС после загрузки
cat << 'EOF' | sudo tee /etc/systemd/system/remount-data.service
[Unit]
Description=Remount /data с security-опциями
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/bin/mount -o remount,noexec,nosuid,nodev /data
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now remount-data.service
```

# Верификация после перемонтирования

После выполнения `remount` необходимо убедиться, что изменения применились корректно. Используйте несколько инструментов для независимой верификации.

## findmnt

```bash
# Проверка опций конкретной точки
findmnt -no OPTIONS /data
# → noatime,relatime,defaults

# Проверка всех точек с фильтром
findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS | grep -E '/data|/home'
```

## /proc/mounts и /proc/self/mountinfo

```bash
# Быстрая проверка (сырой вывод ядра)
grep ' /data ' /proc/mounts
# → /dev/sdb1 /data ext4 rw,noatime,relatime 0 0

# Расширенная информация с propagation flags
cat /proc/self/mountinfo | grep ' /data '
# → 36 25 8:17 / /data rw,relatime shared:1 - ext4 /dev/sdb1 rw
```

## lsblk

```bash
# Проверка флага RO на уровне блочного устройства (важно при аппаратных проблемах)
lsblk -o NAME,RO,SIZE,FSTYPE,MOUNPOINTS /dev/sdb1
# → sdb1  0 100G ext4 /data
```

## Сводная таблица верификации

| Команда | Что проверяет | Пример использования |
| :--- | :--- | :--- |
| `findmnt -no OPTIONS /path` | Опции монтирования | `findmnt -no OPTIONS /data` |
| `grep ' /path ' /proc/mounts` | Аппаратное состояние (ядро) | `grep ' /tmp ' /proc/mounts` |
| `cat /proc/self/mountinfo` | Propagation flags, major:minor | `grep ' /data ' /proc/self/mountinfo` |
| `lsblk -o RO /dev/sdX` | Аппаратный/программный флаг RO | `lsblk -o RO /dev/sdb1` |
| `blockdev --getro /dev/sdX` | Программный флаг BLKROSET | `blockdev --getro /dev/sdb1` |

# Автоматизация и IaC

## Ansible

```yaml
# tasks/main.yml
- name: Remount /data с новыми опциями
  ansible.builtin.mount:
    path: /data
    src: /dev/sdb1
    fstype: ext4
    opts: defaults,noatime,commit=60
    state: mounted
  register: mount_result

- name: Перезагрузка systemd daemon (если менялись mount юниты)
  ansible.builtin.systemd:
    daemon_reload: yes
  when: mount_result.changed
```

## Shell-скрипт (идемпотентный)

```bash
#!/usr/bin/env bash
set -euo pipefail

MOUNT_POINT="/data"
REQUIRED_OPTS="noatime,relatime"

# Проверяем текущие опции
CURRENT_OPTS=$(findmnt -no OPTIONS "$MOUNT_POINT")

if [[ "$CURRENT_OPTS" != *"noatime"* ]]; then
    echo "Применяем remount: добавление noatime..."
    sudo mount -o remount,noatime "$MOUNT_POINT"
else
    echo "Опция noatime уже активна. Пропускаем."
fi
```

## Puppet

```puppet
mount { '/data':
  ensure  => 'mounted',
  device  => '/dev/sdb1',
  fstype  => 'ext4',
  options => 'defaults,noatime,commit=60',
  remounts => true,  # Puppet выполнит remount при изменении опций
}
```

## Chef

```ruby
mount '/data' do
  device '/dev/sdb1'
  fstype 'ext4'
  options ['defaults', 'noatime', 'commit=60']
  action :mount
  supports remount: true
end
```

# Диагностика и решение проблем

## Ошибка EBUSY при переходе в Read-Only

Если ядро не может перевести ФС в режим `ro`, это означает, что какой-то процесс удерживает файл для записи или есть открытые, но удаленные файлы (`deleted`).

**Алгоритм решения:**
1.  **Поиск процессов через lsof:**
    ```bash
    sudo lsof +D /mnt/data | grep ' [0-9]*[uw]'
    # → Отобразит процессы, открывшие файлы на запись (u) или эксклюзивно (w)
    ```
2.  **Поиск процессов через fuser:**
    ```bash
    sudo fuser -mv /mnt/data
    # → Покажет список PID и пользователей, использующих точку монтирования
    ```
3.  **Принудительное закрытие (ОПАСНО):**
    ```bash
    sudo fuser -km /mnt/data
    ```

## Ошибка "is write-protected" при повреждённом journal

Если `ext4` автоматически перешла в `ro` из-за ошибок журнала, повторный `remount,rw` может вернуть:

```text
mount: /dev/sdc1: cannot remount read-write, is write-protected.
```

Это означает, что драйвер `ext4` заблокировал запись на уровне суперблока. Причины:
- **Критические ошибки JBD2:** Журнал повреждён, дальнейшая запись может усугубить повреждение.
- **Аппаратная блокировка:** `blockdev --getro /dev/sdc` возвращает `1`.

**Решение:**
```bash
# 1. Проверяем аппаратный флаг
blockdev --getro /dev/sdc
# → 0 (программный) или 1 (аппаратный)

# 2. Если 0 — анализируем dmesg
dmesg -T | grep -Ei 'EXT4|JBD2|read-only|abort'

# 3. Размонтируем и запускаем fsck (см. Устранение неполадок: ФС в read-only)
umount /dev/sdc1
fsck.ext4 -f /dev/sdc1
```

## Remount в контейнерной среде

В контейнерах (Docker, Podman) возможности `remount` ограничены mount namespace:

```bash
# Проверка mount namespace контейнера
PID=$(docker inspect -f '{{.State.Pid}}' container_name)
sudo nsenter -t $PID -m -- mount | grep /container/path

# Remount внутри контейнера (требует --privileged или CAP_SYS_ADMIN)
docker exec --privileged container_name mount -o remount,ro /container/path

# Или через nsenter на хост
sudo nsenter -t $PID -m -- mount -o remount,ro /container/path
```

> **Ограничение:** OverlayFS (используется в Docker/Podman) не поддерживает изменение опций `lowerdir` через remount. Для изменения слоёв требуется пересоздание контейнера.

## Remount OverlayFS в read-only для дебага

```bash
# Временно перевести upperdir в ro (для отладки overlay)
sudo mount -o remount,ro /var/lib/docker/overlay2/<layer-id>/diff
```

## Применение изменений из fstab

Если вы отредактировали `/etc/fstab` и хотите применить новые опции без перезагрузки:
```bash
sudo mount -o remount /точка/монтирования
# → Ядро перечитает строку из fstab и применит изменения
```

# Ограничения

| Тип ограничения | Описание |
| :--- | :--- |
| **Структурные изменения** | Опции, меняющие формат данных (например, `block_size` или режимы `data=journal`), нельзя изменить через remount. |
| **Propagation flags** | Флаги распространения монтирования (`--make-shared`, `--make-private`) изменяются отдельными командами и не являются частью стандартного `remount`. |
| **Сетевые ФС** | При перемонтировании NFS/CIFS возможны кратковременные подвисания процессов (I/O wait), пока клиент согласует параметры с сервером. |
| **OverlayFS** | Опции `lowerdir`, `upperdir`, `workdir` нельзя изменить через remount. Требуется пересоздание точки монтирования. |
| **Корневой раздел при hardware write-protect** | Если диск аппаратно защищён от записи (SSD в режиме RO, разбитый кабель), `remount,rw` вернёт `is write-protected`. Нужно устранять аппаратную причину. |

# Дополнительная информация

*   **Инструменты:** [Команды монтирования (mount, umount, findmnt)](./commands.md).
*   **Конфигурация:** [Структура и опции /etc/fstab](./fstab.md).
*   **Архитектура:** [Виртуальная файловая система (VFS)](../fs_internals.md).
*   **Безопасность:** [Опции монтирования для защиты системы (nosuid, noexec)](./fstab.md).
*   **Журналирование:** [Журналирование файловых систем](./journaling.md) — JBD2, режимы журналирования, интервалы фиксации.
*   **Mount Namespaces:** [Пространства имён монтирования](../../Virtualization/mount_namespaces.md) — изоляция в контейнерах.
*   **Аварийная диагностика:** [Устранение неполадок: ФС в режиме read-only](../read_only_filesystem_troubleshooting.md) — пошаговый сбор симптомов, проверка `blockdev --getro`, анализ `dmesg` и восстановление.
*   **Автомонтирование:** [Systemd mount units](../mounting/scenarios/systemd_mount.md) — declarative mounting.
