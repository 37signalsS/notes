# LXC (Linux Containers) — системные контейнеры

В данном файле рассматривается технология LXC (Linux Containers), ее архитектура, механизмы изоляции и практические аспекты использования в качестве системных контейнеров в средах DevOps, SRE и системного администрирования.

## Определения

**LXC (Linux Containers)** — технология виртуализации на уровне операционной системы для запуска нескольких изолированных экземпляров Linux (контейнеров) на одном узле (хосте). В узком смысле LXC — это набор инструментов (`lxc-*`) и библиотека (`liblxc`), предоставляющая интерфейс к механизмам изоляции ядра.

**LXD / Incus** — системы управления контейнерами следующего поколения, построенные поверх LXC. Они предоставляют REST API, более удобный CLI и расширенные возможности (живая миграция, управление сетями и хранилищами).
- **LXD**: Развивается компанией Canonical, ориентирован на интеграцию с продуктами Ubuntu.
- **Incus**: Форк LXD, созданный сообществом под эгидой LinuxContainers (LXC) после перехода LXD под полный контроль Canonical. Является предпочтительным выбором для независимых инсталляций в 2025–2026 годах.

**System Containers (Системные контейнеры)** — тип контейнеризации, ориентированный на предоставление полноценного окружения ОС. В отличие от **App Containers (Прикладных контейнеров)** (например, Docker), внутри LXC работает полноценная система инициализации (systemd, OpenRC), пакетный менеджер и системные службы (cron, syslog, sshd).

**Unprivileged Containers (Непривилегированные контейнеры)** — контейнеры, использующие **User Namespaces** для маппинга идентификаторов пользователей (UID/GID). Root внутри контейнера является обычным непривилегированным пользователем на хост-системе, что радикально повышает безопасность.

**Privileged Containers (Привилегированные контейнеры)** — контейнеры, в которых UID 0 (root) хост-системы напрямую отображается на UID 0 внутри контейнера. Используются только при необходимости доступа к оборудованию или специфичным возможностям ядра (например, Docker-in-LXC), так как несопоставимо более опасны в контексте безопасности.

**LXCFS (LXC Filesystem)** — виртуальная файловая система FUSE, которая предоставляет контейнерам виртуализированные представления `/proc` и `/sys`. Вместо реальных файлов хоста контейнер видит статические или ограниченные представления (например, `/proc/cpuinfo` с количеством выделенных CPU, `/proc/meminfo` с лимитом памяти), что обеспечивает корректную работу утилит (`top`, `free`, `ps`) и приложений, считывающих информацию о ресурсах.

## Базовые концепции

### Архитектура и механизмы изоляции

LXC опирается на фундаментальные механизмы ядра Linux для обеспечения изоляции и управления ресурсами.

- **Namespaces (Пространства имен)** — изолируют видимость системных ресурсов:
  - **PID**: собственные идентификаторы процессов (процесс №1 внутри — это init).
  - **Network**: выделенный сетевой стек (интерфейсы, IP, таблицы маршрутизации, правила iptables/nftables).
  - **Mount**: изолированные точки монтирования (изменения внутри не видны на хосте).
  - **User**: маппинг UID/GID (основа непривилегированных контейнеров).
  - **UTS**: изоляция имен хостов (hostname) и доменов.
  - **IPC**: изоляция межпроцессного взаимодействия (Shared Memory, Semaphores).
  - **Cgroup namespace**: изоляция представления контрольных групп (защита от утечки информации о хосте).
  - **Time namespace**: (в новых ядрах) позволяет устанавливать системное время внутри контейнера независимо от хоста.
- **Cgroups (Control Groups)** — управляют лимитами и приоритетами физических ресурсов (CPU, память, I/O).
  - Современные дистрибутивы используют **cgroup v2**, обеспечивающую более унифицированное и иерархическое управление ресурсами по сравнению с v1.
  - В контексте LXC/cgroup v2 критично делегирование прав: systemd внутри контейнера должен иметь возможность записывать в свою подгруппу, иначе службы не запустятся.

### Системные службы и инициализация внутри контейнера

В отличие от Docker, где entrypoint заменяет init, LXC-контейнер выполняет полноценную загрузку ОС:

- **init-система**: systemd ( predominant в RHEL/Debian/Ubuntu), OpenRC (Alpine, Gentoo), SysV-init.
- **journald**: Ведет локальный журнал внутри контейнера. По умолчанию логи хранятся в `/var/log/journal/` rootfs контейнера. Для персистентности между перезапусками используйте том или Bind-mount.
- **cron**: Системные cron-задачи работают штатно через `crond` или `cronie`.
- **syslog**: rsyslog/syslog-ng может обрабатывать логи и отправлять их на хост-систему или centralized syslog-сервер.
- **ssh**: `sshd` внутри контейнера позволяет подключаться напрямую по IP контейнера, без проброса портов хоста. Ключевое преимущество над Docker.

### Хранилища данных

LXC поддерживает различные способы хранения корневой файловой системы:

- **dir**: Обычная директория на ФС хоста. Простой способ, не требующий настройки, но не поддерживающий быстрые снимки (snapshot).
- **Btrfs / ZFS**: Использование Copy-on-Write (CoW) для мгновенного создания снимков и клонирования. Оптимально для сред разработки и CI/CD.
- **LVM**: Создание логических томов (LVM logical volumes). Позволяет жестко ограничить дисковое пространство и использовать снапшоты LVM.
- **OverlayFS**: Комбинирование неизменяемого базового слоя и слоя записи.
- **Ceph (RBD)**: Проброс блочных устройств из распределенного хранилища. Активно используется в кластерных решениях (например, Proxmox).

### Сетевое взаимодействие

LXC предоставляет гибкие режимы настройки сети:

- **veth (Virtual Ethernet)**: Самый частый режим. Контейнер подключается к программному мосту (bridge) на хосте через пару виртуальных интерфейсов.
- **macvlan**: Контейнер получает собственный MAC-адрес на физическом интерфейсе хоста. Эффективно, но требует поддержки со стороны сетевого оборудования/драйверов.
- **ipvlan**: Аналогично macvlan, но работает на L3 (IP), используя MAC хоста. Полезно в облачных средах с ограничениями на количество MAC-адресов.
- **phys**: Прямой проброс физического интерфейса в контейнер (интерфейс исчезает на хосте).
- **routed**: Статическая маршрутизация трафика в контейнер без использования мостов.

### Ключевые особенности

- **Общее ядро**: Контейнер использует ядро хоста. Это означает, что внутри можно запустить только Linux-дистрибутивы, архитектура которых совпадает с архитектурой хоста.
- **Stateful (Сохранение состояния)**: LXC сохраняет изменения в ФС, что делает его эксплуатацию похожей на работу с классическими ВМ.
- **Производительность**: Минимальные накладные расходы. Процессы внутри контейнера выполняются с нативной скоростью процессора хоста.
- **Интеграция**: Базовая технология для **Proxmox VE**, где управление LXC автоматизировано через GUI и API.

### Безопасность и ограничение доступа

Помимо Namespaces, LXC использует дополнительные механизмы защиты:

- **AppArmor / SELinux**: Профили безопасности, ограничивающие доступ процессов внутри контейнера к файлам и системным вызовам хоста.
- **Seccomp (Secure Computing Mode)**: Фильтрация системных вызовов. LXC по умолчанию блокирует опасные вызовы (например, `mount`, `reboot`, `kexec`).
- **Capabilities**: Ограничение привилегий root-пользователя. Даже если контейнер привилегированный, можно отозвать определенные права (например, `CAP_SYS_ADMIN`, `CAP_NET_ADMIN`).
- **ID Mapping (UID/GID Shifting)**: В непривилегированных контейнерах UID 0 (root) мапится на высокий UID на хосте (например, 100000), что предотвращает захват хоста при "побеге" из контейнера.
- **Seccomp-профили**: Позволяют создавать тонкие белые/черные списки системных вызовов для конкретных рабочих нагрузок.

## Управление и инструменты (CLI)

### Классический LXC

Для низкоуровневого управления используются утилиты `lxc-*`:

- **`lxc-create -n <name> -t download`**: Интерактивное создание контейнера из официального репозитория образов.
- **`lxc-start -n <name> -d`**: Запуск в фоновом режиме.
- **`lxc-stop -n <name>`**: Корректное завершение работы (SIGPWR/SIGTERM).
- **`lxc-ls -f`**: Вывод списка контейнеров с IP и статусом.
- **`lxc-info -n <name>`**: Подробная статистика (CPU, RAM usage, PID).
- **`lxc-attach -n <name>`**: Вход в консоль работающего контейнера.
- **`lxc-copy -n <old> -N <new>`**: Создание клона контейнера.
- **`lxc-snapshot -n <name>`**: Создание снимка файловой системы.
- **`lxc-top`**: Динамический мониторинг ресурсов всех контейнеров (аналог `top`).
- **`lxc-console -n <name>`**: Доступ к консоли контейнера (аналог `virsh console` для ВМ).

### Incus / LXD (Современный подход)

Incus предоставляет более высокоуровневый интерфейс:
- Единая команда `incus`.
- Поддержка виртуальных машин (через QEMU) наряду с контейнерами.
- Встроенное управление сетями (OVS, Bridge) и хранилищами.
- Простая миграция между хостами (`incus move`).

**Основные команды Incus:**

```bash
# Инициализация инстанса (первый запуск)
incus admin init

# Создание контейнера из образа
incus launch images:ubuntu/22.04 my-container -c limits.cpu=2 -c limits.memory=2GiB

# Список инстансов
incus list

# Вход в контейнер
incus exec my-container bash

# Экспорт/импорт для бэкапа
incus export my-container /backup/my-container.tar.gz
incus import /backup/my-container.tar.gz

# Миграция на другой хост
incus move my-container remote-host:
```

### Управление образами и шаблонами

**Классический LXC:**
```bash
# Обновление списка шаблонов
lxc-create -n my-container -t download -- --dist ubuntu --release jammy --arch amd64
```

**Incus:**
```bash
# Список доступных образов
incus image list images:

# Создание контейнера из конкретного образа
incus launch images:debian/12 debian-container
```

### Управление хранилищами (Incus)

```bash
# Создание пула хранилища на ZFS
incus storage create zfs-pool zfs pool=rpool

# Создание пула на директории
incus storage create dir-pool dir

# Привязка пула к контейнеру
incus config device add my-container root disk pool=zfs-pool path=/
```

### Управление сетями (Incus)

```bash
# Создание моста
incus network create lxd-bridge ipv4.address=10.0.8.1/24 ipv4.nat=true

# Подключение контейнера к сети
incus config device add my-container eth0 nic network=lxd-bridge
```

### Пример конфигурации

Типовой файл конфигурации (`/var/lib/lxc/<name>/config`):

```bash
# Сетевой интерфейс
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0
lxc.net.0.flags = up
lxc.net.0.hwaddr = 00:16:3e:xx:xx:xx

# Корневая файловая система
lxc.rootfs.path = dir:/var/lib/lxc/my-container/rootfs

# Лимиты ресурсов (cgroup v2)
lxc.cgroup2.memory.max = 1G
lxc.cgroup2.cpuset.cpus = 0-1
lxc.cgroup2.cpu.weight = 100

# Настройки безопасности (непривилегированный режим)
lxc.idmap = u 0 100000 65536
lxc.idmap = g 0 100000 65536

# Автозапуск
lxc.start.auto = 1
lxc.start.delay = 10

# Монтирование proc/sys (для nesting)
lxc.mount.auto = proc:rw sys:rw

# Разрешение capabilities для Docker
lxc.cap.drop =
```

## Практические сценарии

### Вложенная виртуализация (Nesting): Docker внутри LXC

Часто используется в Proxmox для запуска Docker-контейнеров внутри одного системного контейнера LXC.

**Настройка:**
1. Включить `lxc.mount.auto = proc:rw sys:rw`.
2. Включить `lxc.cap.drop = ` (пустой список, если нужны все права) или разрешить специфичные capabilities.
3. Для Proxmox: установить чекбокс `Nesting` и `Keyctl` в параметрах контейнера.

### Резервное копирование и восстановление

**Классический LXC:**
```bash
# Остановка контейнера перед бэкапом (требуется дляConsistency)
lxc-stop -n my-container

# Архивирование корневой ФС
tar -czf /backup/my-container.tar.gz -C /var/lib/lxc/my-container rootfs config

# Восстановление
lxc-create -n my-container-restored -t none -- -f /path/to/config
tar -xzf /backup/my-container.tar.gz -C /var/lib/lxc/my-container-restored
```

**Incus:**
```bash
# Экспорт (работает с running контейнером)
incus export my-container /backup/my-container.tar.gz

# Импорт
incus import /backup/my-container.tar.gz
```

**Proxmox (PVE):**
```bash
# Создание бэкапа через vzdump
vzdump 101 --mode snapshot --compress zstd --storage backup

# Восстановление
qmrestore /var/lib/vz/dump/vzdump-qemu-101-*.vma.zst 101
pct restore 101 /var/lib/vz/dump/vzdump-lxc-101-*.tar.zst
```

### Миграция контейнеров

**Cold migration (с остановкой):**
```bash
# На хосте-источнике
lxc-stop -n my-container
tar -czf /tmp/my-container.tar.gz -C /var/lib/lxc my-container

# Копирование на хост-назначение
scp /tmp/my-container.tar.gz dest-host:/tmp/

# На хосте-назначении
lxc-create -n my-container -t none -- -f /path/to/config
tar -xzf /tmp/my-container.tar.gz -C /var/lib/lxc/my-container
```

**Live migration (Incus):**
```bash
incus move my-container remote-host:
# Требует совпадение версий Incus и доступности сети между хостами
```

### Мониторинг и диагностика

**Мониторинг ресурсов через cgroup v2:**

```bash
# Путь к cgroup контейнера (пример для systemd)
CGROUP_PATH=/sys/fs/cgroup/system.slice/incus-my-container.scope

# Использование CPU
cat $CGROUP_PATH/cpu.max
# → 50000 100000  (квота 50%, период 100мс)

# Использование памяти
cat $CGROUP_PATH/memory.current
cat $CGROUP_PATH/memory.max

# Количество прерываний CPU (throttling)
cat $CGROUP_PATH/cpu.stat
# → throttled_ns 123456789
# → throttled_time 98765432
```

**Мониторинг через lxcfs:**

```bash
# Проверка что lxcfs mounted
mount | grep lxcfs
# → lxcfs on /var/lib/lxcfs type fuse.lxcfs (rw,nosuid,nodev,relatime,...)

# Внутри контейнера ресурсы отражают лимиты
cat /proc/cpuinfo | grep processor | wc -l  # → соответствует cpuset
free -h                                      # → соответствует memory.max
```

**Диагностика сети:**

```bash
# Внутри контейнера
ip addr show
ip route show
cat /etc/resolv.conf

# На хосте
ip link show vethXYZ
bridge link show
iptables -t nat -L -v -n
```

### Автоматизация с Ansible

LXC-контейнеры можно управлять через Ansible, подключаясь по SSH:

```yaml
- name: Развертывание LXC-контейнера на Proxmox
  hosts: localhost
  tasks:
    - name: Создание контейнера через pct
      ansible.builtin.command:
        cmd: pct create 101 /var/lib/vz/template/cache/ubuntu-22.04-standard_22.04-1_amd64.tar.zst \
             --hostname myapp \
             --memory 2048 \
             --cores 2 \
             --net0 name=eth0,bridge=vmbr0,ip=dhcp \
             --storage local \
             --rootfs local:8
      register: result

    - name: Запуск контейнера
      ansible.builtin.command: pct start 101

- name: Настройка контейнера
  hosts: 101
  become: true
  tasks:
    - name: Установка пакетов
      ansible.builtin.apt:
        name: [nginx, curl]
        state: present
        update_cache: true
```

### Запуск системных служб (systemd inside LXC)

Для корректной работы systemd внутри контейнера необходимо:

```bash
# Настройка контейнера (Incus/LXD)
incus config set my-container security.syscalls.intercept.mount=true
incus config set my-container security.syscalls.intercept.sched_setaffinity=true
incus config device add my-container kmsg unix-char source=/dev/kmsg path=/dev/kmsg

# Для классического LXC - в конфиг:
lxc.mount.auto = proc:rw sys:rw cgroup:rw
lxc.cap.drop =
lxc.apparmor.profile = unconfined
```

**Важно:** На cgroup v2 systemd требует доступа к `/sys/fs/cgroup`. Внутри контейнера systemd управляет своей подгруппой. Если хост использует cgroup v2, убедитесь что контейнер имеет права на запись в свою cgroup.

### Сравнение с альтернативами

- **systemd-nspawn**: "LXC от мира systemd". Максимально интегрирован с журналом и службами системы, но менее гибкий в настройке сетей. Хорош для быстрой отладки и легковесных окружений.
- **Podman**: Ориентирован на запуск прикладных контейнеров без демона, но может использоваться для запуска системных образов (systemd) через флаг `--systemd`.

### Распространенные ошибки и диагностика

**Контейнер не запускается:**
```bash
# Проверка логов
lxc-start -n my-container -F -l DEBUG
# -F = foreground (не фоновый режим)
# -l DEBUG = уровень логирования

# Проверка cgroup
systemctl status lxc@my-container
```

**Ошибка "Failed to create init.scope control group":**
```bash
# Причина: cgroup v2 + systemd внутри без delegation
# Решение: добавить в конфиг
lxc.cgroup2.delegate = 1
```

**Сеть не работает:**
```bash
# Проверка mac address
lxc-info -n my-container | grep MAC
# Проверка bridge
brctl show
# Проверка iptables
iptables -L -t nat -v
```

## Безопасность и hardening

### Чек-лист безопасности

**Минимальная конфигурация для непривилегированного контейнера:**

```bash
# Ядро 5.8+ для полной поддержки cgroup v2
# User Namespace с маппингом
lxc.idmap = u 0 100000 65536
lxc.idmap = g 0 100000 65536

# Ограничение capabilities
lxc.cap.drop = sys_admin sys_module sys_rawio
# Или явный allowlist
lxc.cap.keep = chown dac_override fsetid fowner setgid setuid setpcap \
               net_bind_service sys_chroot audit_write

# Seccomp профиль
lxc.seccomp.profile = seccomp-default.json

# AppArmor/SELinux
lxc.apparmor.profile = lxc-default
```

**Сеть:**
- Используйте отдельные мосты для групп контейнеров.
- Применяйте ebtables/iptables для фильтрации трафика между контейнерами.
- Изолируйте management-сеть от user-сети.

**Хранилище:**
- Никогда не монтируйте `/` или чувствительные директории хоста в контейнер без необходимости.
- Используйте read-only rootfs там, где возможно (`lxc.rootfs.path = ramfs:/path` для tmpfs).

### AppArmor / SELinux

LXC поставляется с профилями AppArmor (Ubuntu/Debian) или SELinux (RHEL/CentOS). Профили ограничивают:
- Доступ к файлам хоста из контейнера.
- Системные вызовы, которые может выполнять процесс.
- Возможность изменения сетевых настроек хоста.

```bash
# Проверка активного профиля
cat /proc/<pid>/attr/current
# → lxc-default (AppArmor) или container_runtime_t (SELinux)

# Отключение AppArmor для debugging (не для production)
lxc.apparmor.profile = unconfined
```

## Дополнительная информация

### Сравнение технологий

| Критерий | Docker | LXC | VM (KVM) |
| :--- | :--- | :--- | :--- |
| **Тип** | Прикладной (App) | Системный (System) | Виртуальная машина |
| **Ядро** | Общее с хостом | Общее с хостом | Собственное |
| **Инициализация** | Entrypoint/CMD | Full init (systemd) | Full init |
| **Хранение** | Layered (Images) | RootFS (Templates) | Disk Image (qcow2/raw) |

### Жизненный цикл контейнера

```
Создание → Конфигурация → Запуск (init) → Работа → Остановка → Удаление
   ↑           ↑              ↑           ↑          ↑
   │           │              │           │          └── SIGTERM/SIGPWR
   │           │              │           └── graceful shutdown
   │           │              └── PID 1 = init/systemd
   │           └── apply config, mounts, network
   └── lxc-create / incus launch
```

### См. также

- [Обзор виртуализации и изоляции в Linux](./virtualization_overview.md)
- [Изоляция в Linux: Namespaces и Cgroups](../../Docker/Concepts/linux_isolation.md)
- [Пространства имен (Namespaces) ядра Linux](../Core/namespaces.md)
- [Обзор Proxmox VE](../../Proxmox/proxmox_overview.md)
- [Официальный сайт проекта LinuxContainers (англ.)](https://linuxcontainers.org/)
