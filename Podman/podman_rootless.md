# Безрутовый (Rootless) режим в Podman

## Определения

**Безрутовый режим (Rootless mode)** — это архитектурная особенность Podman, позволяющая запускать контейнеры, управлять образами и настраивать сети от имени обычного непривилегированного пользователя. В этом режиме ни основной процесс Podman, ни процессы внутри контейнера не требуют прав `root` на хост-системе. Корректная работа без прав root основана на daemonless-архитектуре и обязательном использовании пространств имен пользователей (user namespaces).

**User Namespace (Пространство имен пользователей)** — технология ядра Linux, которая мапирует (сопоставляет) идентификаторы пользователей внутри контейнера (например, UID 0 — root) на идентификаторы обычных пользователей на хосте. Это изолирует привилегии контейнера от привилегий хоста.

**subuid / subgid** — файлы конфигурации (`/etc/subuid`, `/etc/subgid`), определяющие диапазоны вспомогательных идентификаторов, которые пользователь может использовать для маппинга внутри своих контейнеров. Для переключения между пространствами имен требуются пакет `uidmap` (утилиты `newuidmap`, `newgidmap`) и `shadow-utils`.

**pasta (passt)** — сетевой стек в пространстве пользователя, драйвер сети по умолчанию для rootless-контейнеров с Podman 5.0 и единственный поддерживаемый вариант в Podman 6.0 (пакет `passt`). Не использует NAT, копирует сетевую конфигурацию с основного интерфейса хоста и поддерживает IPv6.

**fuse-overlayfs** — реализация overlay-файловой системы через FUSE (Filesystem in Userspace), используемая как fallback для нативного overlay в rootless-режиме, когда ядро или файловая система не поддерживают непривилегированные монтирования.

---

## Основные концепции

### Механизмы реализации

#### 1. Изоляция пользователей (User Namespaces)

В безрутовом режиме используется формула маппинга:
- **UID 0** в контейнере = **UID текущего пользователя** на хосте (например, 1000).
- **UID 1..65535** в контейнере = Диапазон из `/etc/subuid` (например, 100000..165535).

Это гарантирует, что если злоумышленник "вырвется" из контейнера, он получит права обычного пользователя, а не `root`. Размер диапазона ограничен 65536 UID/GID на пользователя — образы, в которых используются идентификаторы больше 65535, не могут быть собраны или запущены в стандартной rootless-конфигурации.

Для упрощения работы с томами доступны режимы настройки user namespace:
- `--userns=keep-id` — UID/GID текущего пользователя хоста мапируются на те же значения внутри контейнера (удобно при монтировании каталогов из домашней директории);
- `--userns=auto` — диапазон подбирается автоматически по содержимому образа (опция `size`, по умолчанию 65536).

#### 2. Сетевой стек: Pasta и исторический Slirp4netns

Так как обычный пользователь не может создавать сетевые интерфейсы `veth`, Podman использует сетевые стеки в пространстве пользователя.

- **pasta** (по умолчанию в Podman 5.0+, единственный вариант в Podman 6.0): обеспечивает производительность, близкую к нативной, без трансляции адресов (NAT) для каждого пакета. Копирует IPv4/IPv6-адреса и маршруты с основного интерфейса хоста, сохраняет исходный IP-адрес отправителя (source IP) при пробросе портов, поддерживает выбор интерфейса опцией `-i`. Взаимодействие контейнера с хостом улучшено в Podman 5.3.
- **slirp4netns**: классический драйвер, создающий виртуальный стек TCP/IP с NAT. Обладал более высокой задержкой и накладными расходами. Был драйвером по умолчанию до Podman 5.0, оставался альтернативой в 5.x и полностью удален в Podman 6.0.

**Взаимодействие контейнера с хостом (rootless):**
- Доступ к основному интерфейсу хоста — по имени `host.containers.internal` (с Podman 5.3) или через `--add-host=example.com:host-gateway`.
- Доступ к сервисам на `localhost` хоста — опция `--network=pasta:--map-gw`. По умолчанию это выключено из соображений безопасности (эквивалент `--no-map-gw` в pasta).
- Для диагностики сети rootless используйте `podman unshare --rootless-netns` — вход в сетевой namespace, в котором выполняются сетевые операции.

**Выбор драйвера по умолчанию** задается в `containers.conf` (секция `[network]`, ключ `default_rootless_network_cmd`). В Podman 6.0 поддерживается только значение `"pasta"`, так как slirp4netns удален из кодовой базы.

**Проброс портов:**
- Для сети `pasta` проброс опубликованных портов обрабатывает сама pasta и сохраняет исходный IP клиента.
- Для rootless `bridge`-сетей по умолчанию используется пользовательский прокси `rootlessport`, который НЕ сохраняет исходный IP клиента. Включить сохранение IP можно экспериментальной опцией `rootless_port_forwarder="pasta"` в `containers.conf` (использует `pesto` и требует passt с бинарником `pesto`).
- Минимальный порт, который может занять rootless-контейнер на хосте, ограничен параметром ядра `net.ipv4.ip_unprivileged_port_start` (по умолчанию 1024).

#### 3. Хранилище: нативный overlay или fuse-overlayfs

Стандартный драйвер `overlay` исторически требовал прав `root` для монтирования. Начиная с ядра Linux **5.11** (исправление SELinux — с 5.13) Podman может использовать **нативный непривилегированный overlay** в rootless-режиме без дополнительных утилит. Это быстрее, так как не задействует FUSE.

**fuse-overlayfs** применяется как fallback: на ядрах старше 5.11, при невозможности нативного монтирования, а также для работы с NFS-домашними каталогами (сдвиг UID/GID реализован через расширенные атрибуты). FUSE выполняет операции в пользовательском пространстве, что увеличивает накладные расходы на чтение/запись для тяжелых нагрузок.

Важно:
- Переход между fuse-overlayfs и нативным overlay требует `podman system reset`: флаг `$STORAGE/overlay/.has-mount-program` блокирует нативный overlay для существующего хранилища.
- Поддерживаются только драйверы `overlay` (опционально через fuse-overlayfs) и `vfs`.
- Хранилище должно располагаться на локальной файловой системе (ext4, xfs); на сетевых ФС (NFS) нативный overlay не работает.

**Расположение данных (rootless):**
- Graph root (образы и контейнеры): `~/.local/share/containers/storage` вместо `/var/lib/containers`.
- Run root (временные данные): `/run/user/$(id -u)/containers`.
- Конфигурация: `~/.config/containers/` (аналог системной `/etc/containers/`).

#### 4. Cgroups v2 и ограничение ресурсов

Начиная с Podman 6.0 хост с cgroups v1 не поддерживается вовсе — обязательна унифицированная иерархия cgroups v2. Rootless-контейнеры попадают в cgroup-поддерево пользователя (`user.slice/user-$(id -u).slice`), управляемое `systemd --user`.

Ограничения ресурсов для rootless-контейнеров работают через делегирование контроллеров cgroup v2 пользователю:
- По умолчанию пользователю делегируются только контроллеры `memory pids`.
- Для ограничений CPU, cpuset и I/O администратор должен включить делегирование: `Delegate=cpu cpuset io memory pids` в `/etc/systemd/system/user@.service.d/delegate.conf` (затем повторный вход в систему).
- Проверка делегированных контроллеров: `cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers`.
- Без делегирования попытка задать лимит завершится ошибкой `permission denied` при записи в `/sys/fs/cgroup/.../memory.max`.

Ограничения задаются стандартными флагами `podman run` (`--cpus`, `--memory`, `--cpu-shares`), которые Podman транслирует в контроллеры cgroup v2 (`cpu.max`, `memory.max`, `cpu.weight`). Мониторинг — `podman stats`.

#### 5. Управление через сокет и окружение

В безрутовом режиме сокет Podman (для работы с API или Docker-совместимыми инструментами) располагается в директории пользователя:
- **Путь:** `/run/user/$(id -u)/podman/podman.sock`
- **Переменная окружения:** `XDG_RUNTIME_DIR`. Если она не установлена, Podman не сможет создать сокет или найти временные файлы.
- **Активация сокета** как пользовательской службы: `systemctl --user enable --now podman.socket` (при этом окружение Docker-совместимых клиентов настраивается через `DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock`).

#### 6. Требования и предпосылки (зависимости)

Для работы rootless-режима на хосте должны быть выполнены следующие условия:

- **Пакеты:** `uidmap` (или `shadow-utils` с `newuidmap`/`newgidmap`), сетевой драйвер `passt` (pasta), `fuse-overlayfs` (fallback для старых ядер), `dbus-user-session` (для работающего `systemd --user`).
- **Ядро:** включена поддержка непривилегированных user namespaces. На Debian-семействе — sysctl `kernel.unprivileged_userns_clone=1`, на RHEL-семействе — `user.max_user_namespaces` (по умолчанию задан на RHEL 8+).
- **Cgroups:** активна cgroups v2 (`stat -fc %T /sys/fs/cgroup` → `cgroup2fs`).
- **Проверка готовности:** `podman info` показывает `rootless: true` и корректные пути хранилища.

---

## Практические сценарии

### 1. Подготовка системы (ID Mapping)

Для работы безрутового режима пользователю должны быть выделены диапазоны ID.

```bash
# Проверка выделенных диапазонов
grep $USER /etc/subuid
# → user:100000:65536

# Если диапазоны отсутствуют, их можно добавить (от root)
# sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER

# Проверка готовности rootless-окружения
podman info --format '{{.Host.Security.Rootless}}'
# → true
```

Подробнее о формате и настройке диапазонов: [Файлы конфигурации пользователей](../Linux/SystemAdministration/Users/users_config_files.md).

### 2. Устранение проблем с правами доступа (podman unshare)

Если вы монтируете директорию хоста в контейнер и получаете `Permission Denied`, это часто связано с тем, что UID внутри контейнера не совпадает с владельцем на хосте. Вход в user namespace через `podman unshare` позволяет менять права так, как их видит контейнер.

```bash
# Сделать файлы доступными процессу root внутри контейнера
# (внутри userns UID 0 == текущий пользователь хоста)
podman unshare chown -R 0:0 ./data

# Для непривилегированного процесса приложения (например, UID 999 в образе MariaDB)
podman unshare chown -R 999:999 ./data

# Проверка маппинга UID
podman unshare cat /proc/self/uid_map
# → 0       1000          1
# → 1     100000      65536

# Проверка того, как система видит файлы внутри namespace
podman unshare ls -l ./data
```

Альтернативные способы решения проблемы владения:
- флаг монтирования `:U` — рекурсивно назначает владельца внутри контейнера (`-v ./data:/data:U`);
- `--userns=keep-id` — мапирует текущего пользователя хоста на тот же UID внутри контейнера.

### 3. Настройка Linger для автозапуска

По умолчанию пользовательские процессы (включая контейнеры и systemd-юниты) убиваются при выходе пользователя из системы. Чтобы они работали постоянно:

```bash
# Включить "задержку" (linger) для пользователя
sudo loginctl enable-linger $USER
```

После включения linger rootless-контейнеры, запущенные как пользовательские службы (`systemctl --user`), продолжают работать после выхода из системы. Подробнее: [Пользовательские службы systemd](../Linux/Core/systemd/user_services.md).

### 4. Проброс привилегированных портов

Обычный пользователь не может занимать порты ниже 1024. Чтобы разрешить запуск, например, веб-сервера на порту 80:

```bash
# Вариант 1: Использовать порты выше 1024 (рекомендуется)
podman run -p 8080:80 nginx

# Вариант 2: Изменить настройки ядра (sysctl) на хосте
# sudo sysctl net.ipv4.ip_unprivileged_port_start=80
```

### 5. Диагностика rootless-окружения (podman info)

Быстрая проверка состояния rootless-режима и используемых компонентов.

```bash
# Rootless или rootful
podman info --format '{{.Host.Security.Rootless}}'
# → true

# Сетевой бэкенд и драйвер rootless-сети
podman info --format '{{.Host.NetworkBackend}}'
# → netavark
podman info --format '{{.Host.Pasta.Executable}}'
# → /usr/bin/pasta

# Хранилище
podman info --format '{{.Store.GraphRoot}} {{.Store.GraphDriverName}}'
# → /home/user/.local/share/containers/storage overlay

# Версия cgroups и менеджер
podman info --format '{{.Host.CgroupsVersion}} {{.Host.CgroupManager}}'
# → cgroupsv2 systemd

# Бэкенд базы данных (Podman 6.0+, SQLite заменил BoltDB)
podman info --format '{{.Host.DatabaseBackend}}'
# → sqlite
```

### 6. Ограничение ресурсов rootless-контейнера (cgroups v2)

```bash
# Проверка делегированных контроллеров cgroup
cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers
# → memory pids

# Делегирование CPU/cpuset/I/O контроллеров (от root, затем повторный вход)
sudo mkdir -p /etc/systemd/system/user@.service.d
printf '[Service]\nDelegate=cpu cpuset io memory pids\n' | sudo tee /etc/systemd/system/user@.service.d/delegate.conf
sudo systemctl daemon-reload

# Ограничение CPU и памяти rootless-контейнера
podman run -d --name limited --cpus=0.5 --memory=256m nginx

# Мониторинг и проверка примененных лимитов
podman stats
podman inspect --format '{{.State.CgroupPath}}' limited
```

### 7. Docker-совместимый API через пользовательский сокет

```bash
# Активация пользовательского сокета
systemctl --user enable --now podman.socket
# → сокет /run/user/$(id -u)/podman/podman.sock

# Проверка пути
ls -l /run/user/$(id -u)/podman/podman.sock

# Использование из Docker-клиента (docker CLI / docker compose)
export DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock
docker compose up
```

---

## Нюансы и ограничения

| Особенность | Описание |
| :--- | :--- |
| **Пути к данным** | Образы и контейнеры — в `~/.local/share/containers/storage`, временные данные — `/run/user/$(id -u)/containers`, конфигурация — `~/.config/containers/` вместо `/var/lib/containers`. |
| **Производительность** | На ядрах 5.11+ доступен нативный overlay без FUSE-оверхеда; `pasta` работает без NAT. `fuse-overlayfs` и `slirp4netns` (удален в 6.0) вносят задержки. |
| **Доступ к устройствам** | Прямой доступ к `/dev` ограничен. Создание device-узлов внутри контейнера невозможно даже с `--privileged`. |
| **Квоты ресурсов** | Требуют cgroups v2 и делегирования контроллеров через `systemd --user` (по умолчанию доступны только `memory pids`). |
| **Мультикаст** | Rootless-контейнеры не могут использовать IP multicast (ядро блокирует `IP_ADD_MEMBERSHIP` в user namespace даже с `CAP_NET_ADMIN`). Обходной путь — `--network=host`. |
| **Хранилище на NFS** | Нативный overlay не работает на сетевых ФС. NFS-домашние каталоги поддерживаются через `fuse-overlayfs` (сдвиг UID через xattrs), но локальные ФС предпочтительнее. |
| **SELinux** | Изоляция ослаблена: при "побеге" rootless-процесс получает доступ ко всем файлам, доступным его UID на хосте; SELinux-перехват для таких процессов не работает так, как для rootful-контейнеров. |
| **Ограничения рантайма** | `podman container checkpoint/restore` (CRIU) требуют root и недоступны. `podman mount`/`unmount` видны только внутри user namespace (через `podman unshare`). Поддерживаются только драйверы хранилища `overlay` и `vfs`. |

---

## Дополнительная информация

### Связанные разделы

- **[Изоляция в Podman](./linux_isolation.md)** — детальный разбор Namespaces, Capabilities и Seccomp.
- **[Подман: Хранилище](./podman_volumes_and_storage.md)** — подробнее о маппинге прав на файловой системе и драйверах.
- **[Миграция с Docker](./migration-from-docker.md)** — как перенести проекты и подготовить систему к rootless-режиму.

### См. также

- **[Официальная документация Podman: Rootless](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)** — пошаговое руководство (англ.).
- **[Rootless Podman networking docs](https://github.com/eriksjolund/podman-networking-docs)** — матрица способов подключения контейнера к хосту (pasta, host, socket activation).
