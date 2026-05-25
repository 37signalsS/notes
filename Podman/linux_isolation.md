# Изоляция в Podman

## Определения

**Изоляция Podman** — комбинация механизмов ядра Linux (namespaces, cgroups) и дополнительных средств безопасности (capabilities, seccomp, SELinux), используемых Podman для создания изолированной среды выполнения контейнеров без привилегированного демона.

Основная информация о базовых механизмах ядра собрана в SSoT: [Изоляция в Linux: Namespaces и Cgroups](../Docker/Concepts/linux_isolation.md).

Данный документ фокусируется на **Podman-специфичных особенностях** применения этих механизмов.

## Базовые концепции

### Отличия изоляции Podman от Docker

Полное сравнение подходов к изоляции: [Podman vs Docker](./podman_vs_docker.md).

Ключевые отличия:

- **Архитектура:** Fork/exec без демона vs клиент-сервер (`dockerd`).
- **Изоляция процессов:** Каждый контейнер — независимый процесс с `conmon` vs дочерние процессы демона.
- **Cgroups-менеджмент:** Через `systemd` vs собственный cgroup-менеджер демона.
- **User namespace (rootless):** По умолчанию, настроен «из коробки» vs требует ручной настройки.
- **Capabilities по умолчанию:** Минимальный набор vs более широкий набор.
- **SELinux-интеграция:** Нативная, включена по умолчанию (на SELinux-системах) vs требует ручной настройки.

### Namespaces в Podman

Podman создаёт набор namespaces для каждого контейнера аналогично Docker. Особенности rootless-режима (user namespace, fuse-overlayfs, slirp4netns/pasta) описаны в [Rootless режиме](./podman_rootless.md). В rootful-режиме (`sudo podman`) используется прямой доступ к kernel namespaces без маппинга, сетевой стек через Netavark (veth-пары + bridge).

### Cgroups в Podman

**Интеграция с systemd:**

Podman делегирует управление cgroups через `systemd`, что обеспечивает:

- Единую иерархию для контейнеров и других системных служб
- Нативный учёт ресурсов через `systemd-cgtop`
- Автоматическую очистку cgroups при остановке контейнера

**Иерархия cgroups для контейнера:**

```
/sys/fs/cgroup/
└── machine.slice/
    └── libpod-<container_id>.scope/
        ├── cgroup.procs          # PID процессов контейнера
        ├── memory.max            # Лимит памяти
        ├── cpu.max               # Лимит CPU
        └── pids.max              # Лимит процессов
```

**Установка лимитов:**

```bash
# Ограничить память (256 МБ)
podman run --memory=256m nginx

# Ограничить CPU (50% одного ядра)
podman run --cpus=0.5 nginx

# Ограничить количество процессов
podman run --pids-limit=50 nginx
```

## Практические сценарии

### 1. Инспекция изоляции контейнера

```bash
# Запустить контейнер
podman run -d --name test_isolation nginx

# Получить PID процесса контейнера
CONTAINER_PID=$(podman inspect test_isolation --format '{{.State.Pid}}')

# Посмотреть namespaces процесса
ls -l /proc/$CONTAINER_PID/ns

# Проверить cgroup-путь
cat /proc/$CONTAINER_PID/cgroup

# Просмотреть изоляцию user namespace (rootless)
podman inspect test_isolation --format '{{.HostConfig.UsernsMode}}'
```

### 2. Сравнение изоляции rootless vs rootful

```bash
# Rootless (по умолчанию)
podman run -d --name rootless nginx
podman exec rootless id
# Вывод: uid=0(root) gid=0(root) — root внутри контейнера

# На хосте процесс работает от обычного пользователя
ps -o uid,user,pid,cmd -p $(podman inspect rootless --format '{{.State.Pid}}')
# Вывод: UID = 1000 (ваш пользователь)

# Rootful (требует sudo)
sudo podman run -d --name rootful nginx
sudo podman exec rootful id
# На хосте процесс работает от root
ps -o uid,user,pid,cmd -p $(sudo podman inspect rootful --format '{{.State.Pid}}')
```

### 3. Настройка security-профилей

Podman использует [Seccomp](../Linux/Security/Mechanisms/Seccomp.md) и SELinux для ограничения возможностей контейнера на уровне ядра.

```bash
# Просмотреть seccomp-профиль по умолчанию
podman info | grep -A5 seccomp
...

# Запустить с кастомным seccomp-профилем
podman run --security-opt seccomp=/path/to/profile.json nginx

# Запустить без seccomp (не рекомендуется для production)
podman run --security-opt seccomp=unconfined nginx

# SELinux-метки контейнера (на SELinux-системах)
podman inspect test_isolation --format '{{.ProcessLabel}}'
# Вывод: system_u:system_r:container_t:s0:c123,c456

# Запустить с отключённым SELinux (не рекомендуется)
podman run --security-opt label=disable nginx
```

### 4. Настройка capabilities

```bash
# Показать capabilities по умолчанию
podman run --rm alpine cat /proc/1/status | grep Cap

# Добавить конкретную capability
podman run --cap-add=NET_ADMIN nginx

# Убрать все capabilities (максимальная изоляция)
podman run --cap-drop=all nginx

# Добавить только необходимые
podman run --cap-drop=all --cap-add=NET_BIND_SERVICE nginx
```

## Дополнительная информация

### Связанные темы

- **SSoT:** [Изоляция в Linux: Namespaces и Cgroups](../Docker/Concepts/linux_isolation.md) — базовые механизмы ядра
- **Namespaces:** [Namespaces](../Linux/Core/namespaces.md) — детальное описание namespaces
- **Cgroups:** [Control Groups](../Linux/Core/cgroups.md) — детальное описание cgroups
- **Архитектура:** [Daemonless архитектура](./podman_daemonless_architecture.md) — модель без демона
- **Сравнение:** [Podman vs Docker](./podman_vs_docker.md) — сравнение подходов к изоляции

### Диагностика проблем изоляции

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `ping` не работает из контейнера | Raw sockets требуют CAP_NET_RAW | `podman run --cap-add=NET_RAW` |
| Нет доступа к устройству | Rootless, нет `--device` | `podman run --device=/dev/...` (rootful) |

Ограничения rootless-режима (порты < 1024, fuse-overlayfs, сеть) подробно описаны в [Rootless режиме](./podman_rootless.md#ограничения-rootless-режима).
