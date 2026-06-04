# Изоляция в Podman

## Определения

**Изоляция Podman** — комбинация механизмов ядра Linux (namespaces, cgroups) и дополнительных средств безопасности (capabilities, seccomp, SELinux), используемых Podman для создания изолированной среды выполнения контейнеров без привилегированного демона.

Основная информация о базовых механизмах ядра собрана в обзоре: [Изоляция в Linux: Namespaces и Cgroups](../Docker/Concepts/linux_isolation.md).

Данный документ фокусируется на **Podman-специфичных особенностях** применения этих механизмов.

## Базовые концепции

### Отличия механизмов изоляции Podman от Docker

Полное сравнение подходов к изоляции: [Podman vs Docker](./podman_vs_docker.md).

Ключевые отличия:

- **Архитектура:** Fork/exec без демона vs клиент-сервер (**`dockerd`**).
- **Изоляция процессов:** Каждый контейнер — независимый процесс под управлением монитора **`conmon`** vs дочерние процессы демона.
- **Менеджмент ресурсов:** Через **`systemd`** vs собственный менеджер контрольных групп демона.
- **Rootless режим:** Использование **User Namespace (Пространство имен пользователей)** по умолчанию «из коробки» vs сложная ручная настройка в Docker.
- **Capabilities (Привилегии):** По умолчанию используется максимально ограниченный набор.
- **SELinux:** Глубокая нативная интеграция, автоматическая разметка меток (**labels**) контейнеров.

### Пространства имен (Namespaces) в Podman

Podman создаёт набор **namespaces** для каждого контейнера аналогично Docker. Особенности **Rootless (без прав root)** режима описаны в разделе [Rootless режим](./podman_rootless.md).

- **User Namespace:** Основа rootless-режима. Маппинг **UID (User ID)** и **GID (Group ID)** хоста в UID/GID контейнера.
- **Network Namespace:** В rootless используется стек `slirp4netns` или `pasta`, в rootful — **Netavark** (современный сетевой стек на Rust).
- **Mount Namespace:** Изоляция файловой системы через `fuse-overlayfs` (для rootless).

### Контрольные группы (Cgroups) в Podman

Podman делегирует управление **Cgroups (Control Groups)** через `systemd`, что обеспечивает:

- Единую иерархию для контейнеров и системных служб.
- Нативный учёт ресурсов через `systemd-cgtop`.
- Автоматическую очистку групп при остановке контейнера.

**Иерархия cgroups для контейнера:**

```bash
# Типичный путь в Cgroup v2 (унифицированная иерархия)
/sys/fs/cgroup/machine.slice/libpod-<container_id>.scope/
├── cgroup.procs          # PID (Process ID) процессов контейнера
├── memory.max            # Лимит оперативной памяти
├── cpu.max               # Лимит CPU
└── pids.max              # Лимит количества процессов
```

**Установка лимитов:**

```bash
# Ограничить память (256 МБ)
podman run --memory=256m nginx

# Ограничить CPU (50% одного ядра)
podman run --cpus=0.5 nginx

# Ограничить количество процессов (PID limit)
podman run --pids-limit=50 nginx
```

## Практические сценарии

### 1. Инспекция механизмов изоляции контейнера

```bash
# Запустить контейнер
podman run -d --name test_isolation nginx

# Получить PID (Идентификатор процесса) контейнера
CONTAINER_PID=$(podman inspect test_isolation --format '{{.State.Pid}}')

# Посмотреть namespaces процесса
ls -l /proc/$CONTAINER_PID/ns
# → ipc -> ipc:[4026532450]
# → mnt -> mnt:[4026532448]
# → net -> net:[4026532451]
# → pid -> pid:[4026532449]
# → user -> user:[4026531837]

# Проверить cgroup-путь процесса
cat /proc/$CONTAINER_PID/cgroup
# → 0::/machine.slice/libpod-a1b2c3...scope

# Проверить режим User Namespace
podman inspect test_isolation --format '{{.HostConfig.UsernsMode}}'
# → private (или пустая строка в режиме rootless)
```

### 2. Сравнение изоляции Rootless и Rootful режимов

```bash
# Rootless (от имени обычного пользователя)
podman run -d --name rootless_app nginx
podman exec rootless_app id
# → uid=0(root) gid=0(root) groups=0(root)

# На хосте процесс работает от UID 1000
ps -o uid,user,pid,cmd -p $(podman inspect rootless_app --format '{{.State.Pid}}')
# →   UID USER       PID CMD
# →  1000 q        12345 nginx: master process nginx -g daemon off;

# Rootful (требует sudo)
sudo podman run -d --name rootful_app nginx
ps -o uid,user,pid,cmd -p $(sudo podman inspect rootful_app --format '{{.State.Pid}}')
# →   UID USER       PID CMD
# →     0 root     23456 nginx: master process nginx -g daemon off;
```

### 3. Настройка профилей безопасности (Security Profiles)

Podman использует **Seccomp (Secure Computing Mode)** и SELinux для ограничения системных вызовов.

```bash
# Проверить поддержку seccomp в системе
podman info | grep -A5 seccomp
# → seccomp:
# →   enabled: true
# →   profile: /usr/share/containers/seccomp.json

# Запустить контейнер без seccomp (не рекомендуется)
podman run --security-opt seccomp=unconfined nginx

# Проверить SELinux-метку процесса
podman inspect test_isolation --format '{{.ProcessLabel}}'
# → system_u:system_r:container_t:s0:c123,c456
```

### 4. Управление привилегиями (Capabilities)

```bash
# Показать список Linux Capabilities процесса
podman run --rm alpine cat /proc/1/status | grep CapEff
# → CapEff: 00000000a80425fb (битовая маска разрешенных прав)

# Добавить привилегию для управления сетью
podman run --cap-add=NET_ADMIN nginx

# Убрать все привилегии для максимальной безопасности
podman run --cap-drop=all --name secure_container nginx
```

## Дополнительная информация

### Связанные разделы

- **Базовые механизмы:** [Изоляция в Linux: Namespaces и Cgroups](../Docker/Concepts/linux_isolation.md) — обзор фундаментальных механизмов.
- **Архитектура:** [Daemonless архитектура](./podman_daemonless_architecture.md) — работа без центрального демона.
- **Rootless режим:** [Rootless режим в Podman](./podman_rootless.md) — особенности работы без прав root.
- **Сравнение:** [Podman vs Docker](./podman_vs_docker.md) — детальное сравнение архитектур.
- **Безопасность:** [Seccomp](../Linux/Security/Mechanisms/Seccomp.md) — ограничение системных вызовов.

### Диагностика и устранение проблем

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `ping` не работает | Отсутствует `CAP_NET_RAW` | `podman run --cap-add=NET_ADMIN` или `NET_RAW` |
| Ошибка монтирования устройства | Rootless-ограничения | Используйте `--device` или перейдите в rootful-режим |
| Ошибка SELinux (Permission denied) | Неверная метка на томе | Добавьте `:Z` к `-v` (например, `-v ./data:/app:Z`) |

Полный список ограничений Rootless-режима доступен в разделе: **[Ограничения Rootless режима](./podman_rootless.md#ограничения-rootless-режима)**.
