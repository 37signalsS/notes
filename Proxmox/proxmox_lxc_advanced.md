# Продвинутые возможности LXC в Proxmox VE

## Определения

**LXC (Linux Containers)** -- операционная системная виртуализация на уровне ядра Linux. Контейнер разделяет ядро с хостом, но имеет изолированные namespace (PID, network, mount, user, uts, ipc, cgroup). В отличие от Docker, LXC имитирует полноценную ОС с init-системой.

**Namespace** -- механизм ядра Linux для изоляции ресурсов (процессы, сеть, файловые системы, пользователи). Каждый контейнер видит только свои ресурсы в изолированном пространстве.

**Cgroups (Control Groups)** -- механизм ядра Linux для ограничения, учёта и приоритизации потребления ресурсов (CPU, RAM, I/O, сеть) группами процессов. В Proxmox 8+ по умолчанию используется cgroups v2.

**Unprivileged Container** -- контейнер, запущенный без привилегий root на хосте. Использует маппинг UID/GID (User Namespaces) для безопасности: UID 0 в контейнере соответствует, например, UID 100000 на хосте.

**Privileged Container** -- контейнер, запущенный с привилегиями root на хосте. UID 0 в контейнере = UID 0 на хосте. Менее безопасен, но необходим для некоторых сценариев (например, NFS-сервер).

**Nesting** -- возможность запуска контейнеров внутри контейнеров. Требует включения опции `nesting=1` и настройки cgroup namespace.

**AppArmor** -- Mandatory Access Control (MAC) система, ограничивающая права процессов. В LXC используется по умолчанию для изоляции контейнеров.

**Seccomp** -- механизм фильтрации системных вызовов. LXC ограничивает набор доступных syscall для контейнеров для повышения безопасности.

## Теоретический блок

### Архитектура LXC в Proxmox

```
┌─────────────────────────────────────────────┐
│  Unprivileged LXC Container                 │
│  ├── PID namespace (изолированные процессы)  │
│  ├── NET namespace (свой стек сети)          │
│  ├── MNT namespace (своя ФС)                │
│  ├── USER namespace (UID/GID mapping)       │
│  ├── UTS namespace (hostname)               │
│  ├── IPC namespace (очереди сообщений)      │
│  └── cgroup namespace (ограничение ресурсов)│
├─────────────────────────────────────────────┤
│  Ядро хоста (общее)                         │
│  ├── AppArmor profile                       │
│  ├── Seccomp filter                         │
│  └── cgroups v2                             │
└─────────────────────────────────────────────┘
```

### Типы контейнеров в Proxmox

| Тип | Безопасность | UID Mapping | Применение |
| :--- | :--- | :--- | :--- |
| **Unprivileged** | Высокая | 0:100000:65536 | Рекомендуется для всех workloads |
| **Privileged** | Низкая | 0:0 (без маппинга) | NFS, CIFS,某些 system services |

### Namespaces и их назначение

| Namespace | Изолирует | Пример |
| :--- | :--- | :--- |
| **PID** | Процессы | В контейнере PID 1 -- это init-процесс контейнера, не хоста |
| **NET** | Сетевые интерфейсы, IP, маршруты | Свой IP-адрес, свои порты, изолированный стек |
| **MNT** | Файловые системы | Своя корневая ФС, точки монтирования |
| **USER** | UID/GID | UID 0 в контейнере ≠ UID 0 на хосте |
| **UTS** | hostname, domainname | Свое имя хоста |
| **IPC** | POSIX IPC (shm, sem, msg) | Изолированные очереди сообщений |
| **Cgroup** | Видимость cgroup | Контейнер видит только свою ветку дерева |

### Cgroups v2 в Proxmox 8+

Proxmox 8+ по умолчанию использует cgroups v2 ( unified hierarchy). Это влияет на:

- **Маппинг ресурсов**: Все контроллеры (CPU, memory, I/O) объединены в одну иерархию.
- **Диагностику**: `/proc/meminfo` внутри контейнера показывает ограничения контейнера, а не хоста.
- **Совместимость**: Некоторые старые Docker-версии могут требовать `systemd.unified_cgroup_hierarchy=1`.

```bash
# Проверка версии cgroups
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs (v2) или tmpfs (v1)

# Просмотр cgroup контейнера
cat /sys/fs/cgroup/lxc/<ctid>/memory.max
cat /sys/fs/cgroup/lxc/<ctid>/cpu.max
```

### Unprivileged vs Privileged

**Unprivileged (рекомендуется):**
-UID 0 в контейнере маппится на UID 100000 на хосте.
- Файлы, созданные в контейнере, имеют "странные" UID на хосте (ls -n показывает большие числа).
- Невозможно монтировать NFS/CIFS без дополнительных настроек.
- Безопаснее: даже если контейнер скомпрометирован, атакующий не получает root на хосте.

**Privileged:**
- UID 0 в контейнере = UID 0 на хосте.
- Файлы совместимы по UID.
- Можно монтировать NFS/CIFS.
- Опасно: компрометация контейнера = компрометация хоста.

```bash
# Проверка типа контейнера
pct config <ctid> | grep unprivileged
# → unprivileged: 1 (unprivileged) или отсутствует (privileged)
```

### Управление ресурсами через cgroups

```bash
# CPU: ограничение и приоритеты
pct set <ctid> --cpus 2          # 2 виртуальных ядра
pct set <ctid> --cpuunits 2048   # относительный вес (default: 100)
pct set <ctid> --cpulimit 1.5    # абсолютный лимит (1.5 ядра)

# RAM: ограничение и swap
pct set <ctid> --memory 2048     # лимит RAM в MB
pct set <ctid> --swap 1024       # лимит swap в MB

# I/O: ограничение дисковой активности
pct set <ctid> --ioprio 3        # приоритет I/O (0-7, 0 = highest)
pct set <ctid> --ioconstraint 100 # IOPS limit

# Network: ограничение пропускной способности
tc qdisc add dev lxcbr0 root htb default 11
tc class add dev lxcbr0 parent 1: classid 1:11 htb rate 100mbit
```

## Практические сценарии

### 1. Создание Unprivileged контейнера

```bash
# Скачивание шаблона
pveam update
pveam available | grep debian-12
pveam download local debian-12-standard_12.7-1_amd64.tar.zst

# Создание unprivileged контейнера
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname web-server \
  --memory 2048 \
  --cores 2 \
  --rootfs 16 \
  --unprivileged 1 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp

# Проверка конфигурации
pct config 200
# → unprivileged: 1
```

### 2. Nginx в Unprivileged LXC

```bash
# Создание контейнера
pct create 201 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname nginx \
  --memory 1024 \
  --cores 1 \
  --rootfs 8 \
  --unprivileged 1 \
  --net0 name=eth0,bridge=vmbr0,ip=10.0.0.201/24,gw=10.0.0.1

# Вход в контейнер
pct enter 201

# Установка Nginx
apt update && apt install -y nginx

# Запуск
systemctl enable --now nginx
```

### 3. Docker в LXC (Unprivileged)

Полный SSoT: nesting/keyctl, AppArmor trade-off, установка Engine, Compose, бэкап/restore (`pct restore`), мониторинг и диагностика — [Запуск Docker в LXC-контейнерах Proxmox VE](./proxmox_docker_lxc.md). Ниже — минимальный каркас конфигурации гостя:

```bash
pct create 210 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname docker-host \
  --memory 4096 \
  --cores 2 \
  --rootfs local-lvm:32 \
  --unprivileged 1 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp

pct set 210 --features nesting=1,keyctl=1
# keyctl=1 is required for unprivileged (pct.conf);
# --features replaces the whole list — pass all flags in one call

pct reboot 210
pct enter 210   # далее — установка Docker Engine (см. SSoT)
```

### 4. NFS-сервер в Privileged LXC

```bash
# NFS требует privileged контейнера
pct create 220 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname nfs-server \
  --memory 1024 \
  --cores 1 \
  --rootfs 32 \
  --unprivileged 0 \
  --net0 name=eth0,bridge=vmbr0,ip=10.0.0.220/24

# Добавление хост-директорий
pct set 220 --mp0 /srv/nfs,mp=/mnt/data

# Вход и настройка NFS
pct enter 220
apt update && apt install -y nfs-kernel-server
echo "/mnt/data 10.0.0.0/24(rw,sync,no_subtree_check,no_root_squash)" >> /etc/exports
exportfs -ra
systemctl enable --now nfs-kernel-server
```

### 5. Маппинг UID для Unprivileged контейнеров

```bash
# Настройка subuid/subgid на хосте
echo "root:100000:65536" >> /etc/subuid
echo "root:100000:65536" >> /etc/subgid

# Проверка маппинга в контейнере
pct enter 200
id root
# → uid=0(root) gid=0(root)

# На хосте:
cat /proc/$(pgrep -xf "lxc-start -n 200")/uid_map
# →          0     100000      65536
```

### 6. Диагностика и мониторинг

```bash
# Просмотр процессов контейнера на хосте
ps aux | grep lxc-start
ls -la /proc/<pid>/ns/

# Проверка namespace
lsns -t pid -p <pid>

# Мониторинг ресурсов
systemd-cgtop | grep lxc

# Логи контейнера
pct exec 200 -- journalctl -u nginx
pct exec 200 -- dmesg

# Проверка AppArmor
aa-status | grep lxc
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Контейнер не запускается (nesting) | Не включен nesting | `pct set <ctid> --features nesting=1` |
| Docker не виден в LXC | Apparmor блокирует | `lxc.apparmor.profile: unconfined` |
| "Strange" UID на хосте | Unprivileged маппинг | Это нормально; используйте `pct mount` для доступа |
| NFS не монтируется | Unprivileged контейнер | Используйтеprivileged или настройте idmapped mounts |
| cgroup v2 ошибка | Несовместимость | `systemd.unified_cgroup_hierarchy=1` в cmdline ядра |
| OOM kill контейнера | Лимит памяти | Увеличьте `--memory` или настройте swap |

## Лучшие практики

1. **Всегда используйте Unprivileged**: Привилегированные контейнеры -- только для NFS/CIFS и других системных сервисов.
2. **Включайте AppArmor**: Не отключайте его без крайней необходимости.
3. **Ограничивайте ресурсы**: Всегда задавайте CPU, RAM, I/O limits.
4. **Используйте приватные сети**: Не привязывайте контейнеры напрямую к внешней сети без firewall.
5. **Резервное копирование**: Используйте `vzdump` для бэкапа контейнеров.
6. **Обновления**: Регулярно обновляйте шаблоны и пакеты внутри контейнеров.
7. **Мониторинг**: Настройте алерты на OOM, CPU throttling, I/O delay.

## Граничные случаи

- **Nested containers**: Docker в LXC требует не только nesting=1, но и AppArmor unconfined + cgroup device access.
- **FUSE в LXC**: По умолчанию FUSE заблокирован; требуется `lxc.cap.drop: sys_admin` или AppArmor unconfined.
- **Сетевые namespace и bridges**: Контейнеры не могут напрямую управлять bridges хоста; используйте veth pairs.
- **Kernel modules**: Unprivileged контейнеры не могут загружать модули ядра.

## Дополнительная информация

### Связанные темы

- [LXC (Linux Containers) -- SSoT](../Linux/Virtualization/lxc_overview.md)
- [Пространства имён (namespaces) -- SSoT](../Linux/Core/namespaces.md)
- [Контрольные группы (cgroups) -- SSoT](../Linux/Core/cgroups.md)
- [Запуск Docker в LXC контейнерах Proxmox](./proxmox_docker_lxc.md)
- [Обзор Proxmox VE](./proxmox_overview.md)
