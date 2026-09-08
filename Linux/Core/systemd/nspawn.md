# systemd-nspawn: Встроенная контейнеризация

## Определения

* **`systemd-nspawn`** — системная утилита для запуска легковесных контейнеров (пространств имён) в Linux. Её часто называют «chroot на стероидах», так как она использует современные механизмы ядра (Namespaces, Cgroups, Seccomp) для полной изоляции файловой системы, процессов, сети и идентификаторов пользователей.
* **Системный контейнер** — в отличие от прикладных контейнеров (Docker/Podman), ориентированных на запуск одного процесса, `nspawn` предназначен для запуска полноценной операционной системы с собственным процессом инициализации (PID 1).
* **`systemd-machined`** — системный демон, отслеживающий запущенные виртуальные машины и контейнеры, обеспечивающий единый интерфейс управления ими через `machinectl`.
* **Контейнерный образ (rootfs)** — директория или дисковая область, содержащая минимальную файловую систему дистрибутива (ядро хоста при этом используется общее).
* **Slice (слайс)** — группа юнитов в иерархии systemd, к которой может быть привязан контейнер для ограничения ресурсов.

## Основные концепции

### Архитектура и жизненный цикл

При запуске `systemd-nspawn` происходит следующее:
1. **Создание пространств имён:** ядро создает изолированные `PID`, `mount`, `user`, `network`, `IPC`, `UTS` и `cgroup` namespace.
2. **Назначение PID 1:** внутри контейнера первый процесс становится полноценным `init`-системой (systemd или иной).
3. **Регистрация в machined:** `systemd-machined` получает уведомление о новом контейнере, назначает ему имя и управляет его видимостью в `machinectl`.
4. **Делегирование cgroups:** контейнер помещается в отдельную ветку `/sys/fs/cgroup/.../system.slice/...`, где могут быть установлены лимиты CPU, памяти и I/O.
5. **Сетевая конфигурация:** при использовании `--network-veth` создаются пары виртуальных интерфейсов `ve-<name>` и `vb-<name>`, обеспечивающие связь контейнера с хостом.

> **Важно:** `systemd-nspawn` использует **ядро хоста**. Внутри контейнера можно запускать только дистрибутивы с архитектурой, совпадающей с архитектурой хоста. Для кроссплатформенной эмуляции (например, ARM на x86_64) требуется QEMU + `binfmt_misc`.

### Сравнение с альтернативами

| Характеристика | systemd-nspawn | Docker / Podman | Виртуальные машины |
| :--- | :--- | :--- | :--- |
| **Цель** | Системный контейнер (Full OS) | Прикладной контейнер (App) | Полная виртуализация (HW) |
| **Рантайм** | Без демона (часть systemd) | Демон (dockerd) или без него | Гипервизор (KVM, ESXi) |
| **Образы** | Директории, tar, raw/qcow2 | OCI-слои | ISO, vmdk, qcow2 |
| **Изоляция** | Высокая (Namespaces, Cgroups) | Высокая | Максимальная (аппаратная) |
| **Накладные расходы** | Минимальные (native speed) | Низкие | Значительные |
| **Логирование** | journald хоста (единое хранилище) | Отдельный драйвер (json-file, fluentd) | Гостевая ОС или агент |
| **Сеть** | veth, bridge, macvlan, network-zone | NAT, bridge, host, macvlan, ipvlan | Полный сетевой стек |

### Интеграция в экосистему systemd

`systemd-nspawn` обеспечивает глубокую связь с компонентами хоста:
* **Изоляция:** Автоматическое создание пространств имён (`PID`, `mount`, `user`, `network`, `IPC`, `UTS`).
* **Журналирование:** Логи контейнера напрямую доступны на хосте через `journalctl -M <имя>`.
* **Управление:** Единый интерфейс через `machinectl` и системные юниты.
* **Ресурсы:** Тонкое ограничение CPU, RAM и I/O через cgroups v2.
* **Сеть:** Совместная работа с `systemd-networkd` для настройки виртуальных линков.
* **Автозапуск:** Возможность регистрации контейнера как системного юнита `systemd-nspawn@.service`.

### Работа с хранилищем

`nspawn` поддерживает различные форматы корня файловой системы (rootfs):
* **Директории:** Простые деревья файлов в `/var/lib/machines/`.
* **Btrfs Subvolumes:** Позволяют мгновенно клонировать контейнеры через Copy-on-Write (COW).
* **Дисковые образы:** `.raw`, `.qcow2` (автоматически монтируются через loop-устройства).
* **Импорт из Docker:** `machinectl pull-dkr` скачивает и конвертирует слои OCI в плоскую структуру.

### Ограничение ресурсов (cgroups)

В отличие от классического `chroot`, `nspawn` позволяет жестко квотировать ресурсы контейнера через параметры `systemd-nspawn` или unit-файл:

```ini
# /etc/systemd/nspawn/my-debian.nspawn
[Exec]
Boot=yes
# Лимиты CPU (50% одного ядра)
CPUQuota=50%
# Лимит памяти (жесткий)
MemoryMax=2G
MemorySwapMax=1G
# Лимит процессов (защита от fork-бомб)
TasksMax=256
# Приоритет I/O
IOWeight=50
```

Или напрямую через флаги запуска:

```bash
sudo systemd-nspawn -D /var/lib/machines/my-debian \
  --boot \
  --cpu-quota=50% \
  --memory-max=2G \
  --tasks-max=256 \
  --io-weight=50
```

> **Примечание:** В cgroup v2 параметры `MemoryMax` и `MemorySwapMax` соответствуют файлам `memory.max` и `memory.swap.max`. При включении `MemorySwapMax` swap контейнера учитывается отдельно от swap хоста.

### Безопасность и Hardening

`systemd-nspawn` предоставляет несколько уровней защиты:

* **Seccomp:** Автоматически применяет фильтр системных вызовов, блокируя опасные операции (например, `reboot`, `kexec`, запись в `/sys`).
* **Private Users:** Флаг `-U` или `PrivateUsers=yes` автоматически назначает диапазон UID/GID, отличный от хостового. Root внутри контейнера (UID 0) мапится на непривилегированный UID на хосте.
* **Read-Only:** `--read-only` монтирует корень ФС контейнера только на чтение.
* **Capabilities:** Можно принудительно удалить привилегии через `--drop-capability=...`.
* **ProtectSystem / ProtectHome:** Защищают системные директории и домашние каталоги хоста от записи из контейнера.
* **NoNewPrivileges:** Запрещает повышение привилегий через `setuid`/`setgid` внутри контейнера.

Пример расширенной конфигурации безопасности:

```ini
[Exec]
Boot=yes
PrivateUsers=yes
ProtectSystem=strict
ProtectHome=read-only
NoNewPrivileges=yes
CapabilityBoundingSet=CAP_NET_ADMIN CAP_SYS_TIME

[Files]
ReadOnly=yes
Bind=/home/user/data:/mnt/data:ro
```

## Практические сценарии

### 1. Подготовка окружения (rootfs)

Для запуска контейнера необходимо развернуть минимальную ОС в каталог.

```bash
# Установка инструментов (для Debian/Ubuntu)
sudo apt update && sudo apt install -y debootstrap

# Создание директории для контейнера
sudo mkdir -p /var/lib/machines/my-debian

# Развертывание базовой системы
sudo debootstrap stable /var/lib/machines/my-debian http://deb.debian.org/debian/
```

### 2. Режимы запуска и изоляции

#### Интерактивный и системный запуск

```bash
# Простой запуск (аналог chroot с изоляцией)
sudo systemd-nspawn -D /var/lib/machines/my-debian

# Запуск с загрузкой init-системы (полноценная ОС)
# --boot: запускает PID 1; --network-veth: создает виртуальную сетевую пару
sudo systemd-nspawn -D /var/lib/machines/my-debian --boot --network-veth
```

#### Эфемерный режим (Ephemeral)

Позволяет запустить контейнер на временном снимке (snapshot). Все изменения стираются после остановки. Идеально для тестирования.

```bash
# Запуск временной копии (флаг -x или --ephemeral)
sudo systemd-nspawn -x -D /var/lib/machines/my-debian --boot
```

#### Изоляция пользователей (User Namespaces)

Безопасный режим, сопоставляющий UID контейнера с неиспользуемым диапазоном на хосте.

```bash
# Флаг -U автоматически назначает диапазон UID/GID
sudo systemd-nspawn -U -D /var/lib/machines/my-debian --boot
```

### 3. Расширенная настройка сети

* **Virtual Ethernet (`--network-veth`):** Создает интерфейс `ve-<name>` на хосте.
* **Bridge (`--network-bridge=br0`):** Подключает контейнер к существующему сетевому мосту.
* **MACVLAN (`--network-macvlan=eth0`):** Дает контейнеру собственный MAC-адрес в физической сети.
* **Network Zone (`--network-zone=myzone`):** Объединяет группу контейнеров в виртуальную сеть (мост `vz-myzone`).

### 4. Конфигурация через .nspawn файлы

Настройки контейнера можно закрепить в `/etc/systemd/nspawn/my-debian.nspawn`.

```ini
[Exec]
Boot=yes
# Ограничение системных вызовов
Capability=CAP_NET_ADMIN
PrivateUsers=yes
CPUQuota=50%
MemoryMax=2G

[Network]
VirtualEthernet=yes
Bridge=br0

[Files]
# Проброс каталогов (Bind mount)
Bind=/home/user/data:/mnt/data:ro
```

### 5. Управление через machinectl

| Команда | Описание |
| :--- | :--- |
| **`machinectl list`** | Список всех активных контейнеров. |
| **`machinectl status <name>`** | Детальная информация (IP, дерево процессов, потребление ресурсов). |
| **`machinectl shell <name>`** | Вход в работающий контейнер (новая сессия). |
| **`machinectl pull-dkr <image>`** | Загрузка и конвертация образа из Docker Registry. |
| **`machinectl clone <src> <dst>`** | Клонирование контейнера (на Btrfs — мгновенно). |
| **`machinectl stop <name>`** | Корректное завершение работы контейнера. |
| **`machinectl enable <name>`** | Включение автозапуска контейнера. |
| **`machinectl poweroff <name>`** | Выключение контейнера (аналог poweroff). |

### 6. Запуск как системная служба

Для постоянной работы используйте шаблонный юнит `systemd-nspawn@.service`.

```bash
# Включение автозапуска для контейнера в /var/lib/machines/my-debian
sudo systemctl enable --now systemd-nspawn@my-debian.service

# Проверка состояния юнита
systemctl status systemd-nspawn@my-debian.service
# → статус: active (running)
```

### 7. Мониторинг контейнера

Поскольку логи контейнера интегрированы в journald хоста, доступ к ним осуществляется через флаг `-M`:

```bash
# Просмотр логов контейнера в реальном времени
journalctl -M my-debian -f

# Логи конкретного сервиса внутри контейнера
journalctl -M my-debian -u ssh.service --since "10 min ago"

# Мониторинг ресурсов контейнера через cgtop
systemd-cgtop --machine=my-debian --order=memory
```

Для детального анализа потребления ресурсов конкретным юнитом внутри контейнера:

```bash
# Потребление памяти контейнером
systemctl show my-debian.service -p MemoryCurrent -p MemoryMax

# Дерево cgroups контейнера
systemd-cgls /system.slice/systemd-nspawn@my-debian.service
```

### 8. Создание CI/CD окружений

`systemd-nspawn` подходит для запуска изолированных окружений CI-джобов, где требуется полноценная ОС, но без overhead виртуальных машин:

```bash
# Подготовка образа для CI
sudo debootstrap stable /var/lib/machines/ci-runner http://deb.debian.org/debian/

# Конфигурация автозапуска нужных служб
sudo systemd-nspawn -D /var/lib/machines/ci-runner \
  --boot \
  --network-veth \
  --capability=CAP_NET_ADMIN \
  --cpu-quota=200% \
  --memory-max=4G \
  --run /usr/local/bin/ci-entrypoint.sh
```

### 9. Диагностика и troubleshooting

#### Контейнер не загружается (boot failure)

```bash
# Просмотр логов загрузки контейнера
journalctl -M my-debian -b

# Запуск в режиме отладки с выводом на хостовую консоль
sudo systemd-nspawn -D /var/lib/machines/my-debian \
  --boot \
  --console=pipe \
  --notify-ready=no
```

#### Проблемы с сетью

```bash
# Проверка сетевых пространств имён
sudo lsns -t net | grep my-debian

# Вход в сетевой namespace контейнера
sudo nsenter -t $(machinectl show my-debian -p Leader --value) -n ip addr show

# Проверка маршрутов и iptables
sudo nsenter -t $(machinectl show my-debian -p Leader --value) -n ip route
```

#### Ошибки D-Bus и journald внутри контейнера

Если контейнер не может подключиться к D-Bus:

```bash
# Использование machinectl shell вместо прямого ssh
machinectl shell my-debian

# Или явный экспорт переменной окружения
sudo systemd-nspawn -D /var/lib/machines/my-debian \
  -E XDG_RUNTIME_DIR=/run/user/0
```

### 10. Резервное копирование и восстановление

```bash
# Создание резервной копии (tar)
sudo systemd-nspawn -D /var/lib/machines/my-debian \
  --chdir=/ \
  tar-cvf /tmp/my-debian-backup.tar .

# Или через machinectl (создает tar в /var/lib/machines/)
machinectl export my-debian /tmp/my-debian-backup.tar

# Восстановление из бэкапа
sudo rm -rf /var/lib/machines/my-debian
sudo mkdir -p /var/lib/machines/my-debian
sudo tar -xvf /tmp/my-debian-backup.tar -C /var/lib/machines/my-debian
```

### 11. Миграция между хостами

```bash
# На хосте-источнике: экспорт
machinectl export my-debian /tmp/my-debian.tar

# Перенос файла на целевой хост (scp, rsync)
scp /tmp/my-debian.tar user@target:/tmp/

# На целевом хосте: импорт и запуск
sudo mkdir -p /var/lib/machines/my-debian
sudo tar -xvf /tmp/my-debian.tar -C /var/lib/machines/my-debian
sudo systemctl enable --now systemd-nspawn@my-debian.service
```

## Безопасность и Hardening

* **Seccomp:** `systemd-nspawn` автоматически применяет фильтр системных вызовов, блокируя опасные операции (например, запись в `/sys` или перезагрузку хоста).
* **Read-Only:** Флаг `--read-only` монтирует корень ФС контейнера только на чтение.
* **Capabilities:** Можно принудительно удалить привилегии через `--drop-capability=...`.
* **Private Users:** Флаг `-U` или директива `PrivateUsers=yes` обеспечивает маппинг UID/GID, предотвращая «побег» root-пользователя из контейнера.
* **ProtectSystem / ProtectHome:** Ограничивают доступ контейнера к системным и пользовательским директориям хоста.
* **NoNewPrivileges:** Запрещает повышение привилегий через setuid/setgid-бинарники внутри контейнера.

## Диагностика и устранение неисправностей

### Типичные ошибки

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Контейнер не запускается, journal пуст | Отсутствует `systemd` внутри rootfs или поврежден `/etc/fstab`. | Проверьте наличие `/sbin/init` или `systemd` в rootfs. |
| Ошибка сети внутри контейнера | Отсутствует `systemd-networkd` или DHCP не работает. | Включите `systemd-networkd` внутри контейнера или настройте статический IP через `.nspawn` файл. |
| `Failed to connect to bus` | Отсутствует D-Bus или `$XDG_RUNTIME_DIR`. | Используйте `machinectl shell <name>` или явно задайте `export XDG_RUNTIME_DIR=/run/user/$UID`. |
| `Permission denied` при монтировании | `systemd-nspawn` запущен без достаточных прав или SELinux/AppArmor блокирует доступ. | Запустите через `sudo` или проверьте политики безопасности. |
| Низкая производительность диска | Rootfs на вращающемся HDD без монтирования tmpfs. | Используйте `PrivateTmp=yes` и размещайте rootfs на SSD. |
| Контейнер «зависает» при остановке | Процесс игнорирует `SIGTERM`. | Установите `TimeoutStopSec=10s` в unit-файле контейнера. |

### Проверка корректности работы

```bash
# 1. Убедитесь, что контейнер виден в machinectl
machinectl list

# 2. Проверьте статус и ресурсы
machinectl status my-debian

# 3. Сравните потребление памяти с прямым чтением cgroup
cat /sys/fs/cgroup/system.slice/systemd-nspawn@my-debian.service/memory.current
systemctl show systemd-nspawn@my-debian.service -p MemoryCurrent

# 4. Проверьте логи загрузки
journalctl -M my-debian -b --no-pager
```

## Рекомендации по эксплуатации (Best Practices)

1. **Используйте Btrfs или overlayfs:** Для быстрого клонирования и снапшотов выбирайте файловую систему с поддержкой COW.
2. **Включайте PrivateUsers:** Запускайте контейнеры с `PrivateUsers=yes` или флагом `-U` для повышения безопасности.
3. **Ограничивайте ресурсы по умолчанию:** Всегда задавайте `MemoryMax`, `CPUQuota` и `TasksMax` через unit-файл или `.nspawn` конфиг.
4. **Не храните данные в rootfs:** Пробросите тома через `Bind=` в `.nspawn` файле для сохранения данных при обновлении образа.
5. **Используйте `--read-only` для production:** Если контейнер не должен изменять собственную ФС, монтируйте корень только на чтение.
6. **Корреляция логов:** Используйте `journalctl -M <name>` для доступа к логам, а не `docker logs` — это обеспечивает единое хранилище логов хоста.
7. **Не используйте для прикладных контейнеров:** Для запуска одного процесса (nginx, redis) используйте Podman или Docker. `nspawn` оптимизирован для полноценных ОС.
8. **Тестируйте в ephemeral-режиме:** Перед постоянным развертыванием проверяйте конфигурацию через `--ephemeral`, чтобы не засорять production образ.

## Ограничения утилиты

* Общее ядро с хостом — внутри можно запускать только дистрибутивы с совпадающей архитектурой.
* В cgroup v1 отсутствует рекурсивный подсчет ресурсов для вложенных контейнеров.
* Для I/O-метрик требует включенного `IOAccounting=`, что может незначительно влиять на производительность в высоконагруженных системах.
* Меньшая экосистема инструментов по сравнению с Docker/Podman (нет официальных marketplaces, ограниченная поддержка overlay сети).
* Не подходит для изоляции прикладных контейнеров с микросервисной архитектурой (для этого существуют Kubernetes и Podman).

## Дополнительная информация

### См. также

* [Механизм Control Groups (cgroups)](../cgroups.md) — управление ресурсами.
* [Пространства имён (Namespaces)](../namespaces.md) — основы изоляции.
* [Утилита chroot](../chroot.md) — классический метод смены корня.
