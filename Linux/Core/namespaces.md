# Namespaces (Пространства имён)

## Определения

**Namespaces** — механизм ядра Linux, обеспечивающий изоляцию и виртуализацию системных ресурсов для группы процессов. Создаёт иллюзию работы в отдельной системе с собственными процессами, сетью, файловой системой и пользователями.

**Ключевое отличие от cgroups:**

- **Namespaces** отвечают за **изоляцию видимости** (что процесс *может видеть*)
- **[Cgroups](./cgroups.md)** отвечают за **ограничение потребления** (что процесс *может использовать*)

Вместе эти технологии образуют основу контейнеризации (Docker, Podman, Kubernetes).

## Основные концепции

### Типы namespaces

| Namespace | Изолирует | Примеры объектов | Практическое применение |
| :--- | :--- | :--- | :--- |
| `mnt` | Таблица монтирования | Точки монтирования, корень ФС | Изолированная корневая ФС контейнера |
| `pid` | Дерево процессов | PID, родительские/дочерние связи | Контейнер видит только свои процессы |
| `net` | Сетевой стек | Интерфейсы, маршруты, iptables, сокеты | Изолированная сеть контейнера |
| `user` | Идентификаторы пользователей | UID, GID, capabilities | Rootless-контейнеры |
| `ipc` | Межпроцессное взаимодействие | POSIX/System V очереди, семафоры, разделяемая память | Изоляция IPC между контейнерами |
| `uts` | Имя хоста и домена | `hostname`, `domainname` | Уникальное имя хоста контейнера |
| `cgroup` | Иерархия cgroups | Видимость cgroup-дерева | Изоляция представления о cgroups |
| `time` (5.6+) | Системное время | Часы `CLOCK_BOOTTIME`, `CLOCK_TAI` | Изоляция времени для миграции контейнеров |

> **Примечание:** Namespace `time` добавлен в ядре 5.6 и пока не широко используется.

### Детальное описание namespaces

#### Mount (mnt)

Изолирует таблицу монтирования файловой системы. Позволяет процессам иметь собственный набор точек монтирования:

- Создание изолированной корневой ФС (`/`) для контейнера
- Приватные точки монтирования (`/tmp`, `/sys`, `/proc`)
- **Propagation:** Управление распространением событий монтирования между namespaces

> **Подробно:** [Mount Namespaces](../Virtualization/mount_namespaces.md)

#### PID (Process ID)

Изолирует дерево процессов:

- Процессы видят только другие процессы в том же PID namespace
- Каждый namespace имеет собственную иерархию, начинающуюся с PID 1
- Первый процесс становится «init-процессом» для namespace
- При завершении PID 1 ядро завершает все процессы в namespace
- Снаружи процессы имеют другие PID (видны в родительском namespace)

#### Network (net)

Изолирует сетевой стек:

- Собственные сетевые интерфейсы (включая `lo`)
- Отдельная таблица маршрутизации
- Изолированные правила `iptables`/`nftables`
- Собственные сокеты и порты
- Несколько контейнеров могут использовать один network namespace (поды Kubernetes)

> **Подробно:** [ip netns](../Networking/Tools/iproute2/overview.md)

#### User

Изолирует UID, GID и capabilities:

- Маппинг пользователей внутри namespace на пользователей хоста
- UID 0 внутри namespace может быть обычным пользователем на хосте
- Основа для **rootless containers** (Podman, Docker rootless)
- Безопасное выполнение с привилегиями внутри изолированной среды

#### IPC (Inter-Process Communication)

Изолирует механизмы межпроцессного взаимодействия:

- System V IPC (очереди, семафоры, разделяемая память)
- POSIX IPC (очереди, семафоры, shared memory)
- Предотвращает конфликты IPC между контейнерами

#### UTS (UNIX Timesharing System)

Изолирует имя хоста и домена:

- Собственное `hostname` для каждого контейнера
- Собственное `domainname` (NIS domain)
- Позволяет контейнерам иметь уникальные сетевые имена

#### Cgroup

Изолирует представление об иерархии cgroups:

- Контейнер видит только свою ветку cgroup-дерева
- Предотвращает доступ к информации о других контейнерах
- Улучшает безопасность и изоляцию

### Системные вызовы

| Вызов | Назначение | Пример использования |
| :--- | :--- | :--- |
| `clone()` | Создание процесса в новом namespace | `clone(CLONE_NEWPID \| CLONE_NEWNET, ...)` |
| `unshare()` | Отсоединение от текущего namespace | `unshare(CLONE_NEWNS)` |
| `setns()` | Присоединение к существующему namespace | `setns(fd, CLONE_NEWNET)` |

**Утилиты командной строки:**

- **`unshare`** — обёртка над `clone()`/`unshare()` для запуска процессов в новых namespaces
- **`nsenter`** — обёртка над `setns()` для входа в существующие namespaces

## Практические сценарии

### 1. Создание изолированной оболочки с `unshare`

```bash
# Запуск bash в новых namespaces:
# --mount: новая ФС, --uts: новое имя хоста, --ipc: новая IPC
# --net: новая сеть (только lo), --pid: новое дерево процессов
# --user --map-root-user: маппинг текущего пользователя в root внутри namespace
sudo unshare --mount --uts --ipc --net --pid --fork --user --map-root-user bash

# Внутри оболочки:
hostname new-host    # Изменение только внутри namespace
ps -ef               # Видны только процессы bash и ps
ip addr              # Только интерфейс lo
```

### 2. Вход в существующий namespace с `nsenter`

**Параметры `nsenter`:**

| Параметр | Описание |
| :--- | :--- |
| `-t, --target <pid>` | PID целевого процесса |
| `-m, --mount` | Войти в mount namespace |
| `-u, --uts` | Войти в UTS namespace (hostname) |
| `-i, --ipc` | Войти в IPC namespace |
| `-n, --net` | Войти в network namespace |
| `-p, --pid` | Войти в PID namespace |
| `-U, --user` | Войти в user namespace |

**Пример: Отладка сети Docker-контейнера**

```bash
# 1. Найти PID процесса в контейнере
docker inspect <container_id> --format '{{.State.Pid}}'

# 2. Войти в network namespace контейнера
sudo nsenter -t <PID> -n ip addr

# 3. Проверить сетевые интерфейсы «изнутри» контейнера
sudo nsenter -t <PID> -n netstat -tlnp
```

### 3. Инспекция namespaces с `lsns`

```bash
# Показать все namespaces
lsns

# Только сетевые namespaces (полезно для контейнеров)
lsns -t net

# Только PID namespaces
lsns -t pid

# Подробный вывод с именами хостов
lsns -o pid,user,namespace,hostname,type
```

### 4. Просмотр namespaces процесса

```bash
# Показать все namespaces процесса
ls -l /proc/$$/ns

# Вывод:
# lrwxrwxrwx 1 user user 0 мар  3 10:00 /proc/1234/ns/net -> 'net:[4026531840]'
# lrwxrwxrwx 1 user user 0 мар  3 10:00 /proc/1234/ns/pid -> 'pid:[4026531836]'
# ...
```

### 5. Копирование namespace

```bash
# Создать копию network namespace для отладки
ip netns add debug_ns
ip netns exec debug_ns ip addr

# Удалить после использования
ip netns delete debug_ns
```

## Дополнительная информация

### Связанные темы

- **[cgroups](./cgroups.md)** — механизм ограничения ресурсов
- **[Mount Namespaces](../Virtualization/mount_namespaces.md)** — propagation и монтирования
- **[ip netns](../Networking/Tools/iproute2/overview.md)** — управление network namespaces
- **[systemd-nspawn](./systemd/nspawn.md)** — легковесная контейнеризация
- **[seccomp](../Security/Mechanisms/Seccomp.md)** — фильтрация системных вызовов
- **[Docker Isolation](../../Docker/Concepts/linux_isolation.md)** — применение в Docker

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `unshare` требует root | Namespace требует привилегий | Использовать `sudo` или настроить user namespace |
| Процесс не видит другие процессы | PID namespace изолирован | Это ожидаемое поведение, проверить в другом namespace |
| Сеть не работает в namespace | Нет интерфейсов кроме lo | Создать veth-пару или подключить к bridge |
| `nsenter` не находит namespace | Процесс завершён или неверный PID | Проверить `ps -p <PID>` |

### Дополнительные ресурсы

- **Официальная документация ядра:** [namespaces(7)](https://man7.org/linux/man-pages/man7/namespaces.7.html)
- **User namespaces:** [user_namespaces(7)](https://man7.org/linux/man-pages/man7/user_namespaces.7.html)
- **unshare(1):** [unshare(1)](https://man7.org/linux/man-pages/man1/unshare.1.html)
- **nsenter(1):** [nsenter(1)](https://man7.org/linux/man-pages/man1/nsenter.1.html)
