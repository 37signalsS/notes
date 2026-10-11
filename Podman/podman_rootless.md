# Безрутовый (Rootless) режим в Podman

## Определения

**Безрутовый режим (Rootless mode)** — это архитектурная особенность Podman, позволяющая запускать контейнеры, управлять образами и настраивать сети от имени обычного непривилегированного пользователя. В этом режиме ни основной процесс Podman, ни процессы внутри контейнера не требуют прав `root` на хост-системе. Корректная работа без прав root основана на daemonless-архитектуре и обязательном использовании пространств имен пользователей (user namespaces).

**User Namespace (Пространство имен пользователей)** — технология ядра Linux, которая мапирует (сопоставляет) идентификаторы пользователей внутри контейнера (например, UID 0 — root) на идентификаторы обычных пользователей на хосте. Это изолирует привилегии контейнера от привилегий хоста.

**subuid / subgid** — файлы конфигурации (`/etc/subuid`, `/etc/subgid`), определяющие диапазоны вспомогательных идентификаторов, которые пользователь может использовать для маппинга внутри своих контейнеров. Для переключения между пространствами имен требуются пакет `uidmap` (утилиты `newuidmap`, `newgidmap`) и `shadow-utils`.

**pasta (passt)** — сетевой стек в пространстве пользователя, драйвер сети по умолчанию для rootless-контейнеров с Podman 5.0 и единственный поддерживаемый вариант в Podman 6.0 (пакет `passt`). Не использует NAT, копирует сетевую конфигурацию с основного интерфейса хоста и поддерживает IPv6.

**fuse-overlayfs** — реализация overlay-файловой системы через FUSE (Filesystem in Userspace), используемая как fallback для нативного overlay в rootless-режиме, когда ядро или файловая система не поддерживают непривилегированные монтирования.

**Pause-процесс** — отдельный процесс в rootless-режиме, который удерживает user namespace живым после выхода запускающего процесса. Без него все unprivileged-контейнеры пользователя были бы разрушены, когда завершается процесс, создавший пространство имен. Pause-процесс порождается автоматически при создании первого контейнера и существует до перезагрузки или явной остановки всех контейнеров.

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
- `--userns=auto` — диапазон подбирается автоматически по содержимого образа (опция `size`, по умолчанию 65536).

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
- **Проверка готовости:** `podman info` показывает `rootless: true` и корректные пути хранилища.

#### 7. Pause-процесс в rootless-режиме

User namespace существует только пока жив хотя бы один процесс внутри него. После выхода процесса, создавшего namespace, все контейнеры в нем уничтожаются. Podman автоматически порождает **pause-процесс** (легковесный процесс, выполняющий системный вызов `pause()`), который удерживает namespace живым. Pause-процесс:
- порождается автоматически при создании первого контейнера пользователя;
- живет до перезагрузки или явной остановки всех контейнеров (`podman system migrate` или `podman stop --all && podman rm --all`);
- не потребляет значимых ресурсов (RSS < 1 МБ).

Примечание: pause-процесс отделен от `conmon`. Conmon сопровождает конкретный контейнер, pause-процесс удерживает сам user namespace.

#### 8. Rootless vs Rootful: сравнительный анализ

| Критерий | Rootless | Rootful |
| :--- | :--- | :--- |
| **Привилегии процесса** | Обычный пользователь (UID ≥ 1000) | `root` (UID 0) |
| **User Namespace** | Обязателен; UID 0 контейнера → UID пользователя хоста | Не используется по умолчанию; UID 0 контейнера = UID 0 хоста |
| **Сетевой драйвер** | `pasta` (только в Podman 6.0) | `netavark` + `aardvark-dns` |
| **Хранилище** | `~/.local/share/containers/storage`, `/run/user/$(id -u)/containers` | `/var/lib/containers/storage`, `/run/containers` |
| **Cgroup-делегирование** | Требует настройки `systemd --user` | Прямой доступ через `systemd` |
| **Порт < 1024** | Требует `sysctl net.ipv4.ip_unprivileged_port_start` | Доступно по умолчанию |
| **Прямой доступ к /dev** | Ограничен; создание device-узлов невозможно | Полный доступ (с `--privileged`) |
| **Checkpoint/Restore** | Недоступно (требует root) | Доступно (CRIU) |
| **SELinux** | Контекст `unconfined_u:unconfined_r:unconfined_t`; изоляция ослаблена | Контекст `system_u:system_r:container_runtime_t`; полная изоляция |
| **Мультикаст** | Заблокирован ядром | Доступен с `CAP_NET_ADMIN` |
| **Автозапуск** | Требует `loginctl enable-linger` + `systemctl --user` | Требует `systemctl enable --now` |

#### 9. Жизненный цикл rootless-контейнера

1. **Создание user namespace**: при первом запуске `podman run` создается user namespace с маппингом UID/GID из `/etc/subuid`/`/etc/subgid`. UID 0 контейнера маппируется на UID запустившего процесса.
2. **Pause-процесс**: Podman порождает pause-процесс, который удерживает user namespace живым после выхода CLI. Без pause-процесса контейнер был бы уничтожен.
3. **Создание остальных namespaces**: PID, NET, IPC, UTS, MOUNT создаются через OCI runtime (`crun`).
4. **Cgroup**: контейнер добавляется в cgroup-поддерево пользователя (`user.slice/user-$(id -u).slice`).
5. **Монтирование**: настройка корневой ФС, томов, tmpfs. Для rootless используется либо нативный overlay (ядро 5.11+), либо `fuse-overlayfs`.
6. **Exec**: запуск основного процесса контейнера. `conmon` становится его родителем.
7. **Работа**: контейнер работает под управлением `conmon`. При использовании `systemd --user` conmon регистрируется как сервис.
8. **Остановка**: `podman stop` отправляет SIGTERM, затем SIGKILL. `conmon` фиксирует код завершения.
9. **Очистка**: удаление cgroup, размонтирование, удаление слоев хранилища (если контейнер не `--rm`).

#### 10. Уровни привилегий и capabilities в rootless

Внутри user namespace контейнер может иметь `CAP_SYS_ADMIN` и другие capabilities, но на хосте они маппируются на обычные привилегии пользователя. Это означает:
- **CAP_NET_ADMIN** в контейнере позволяет настраивать интерфейсы pasta, но не создавать `veth` или `bridge` на хосте.
- **CAP_SYS_ADMIN** в контейнере позволяет монтировать ФС внутри namespace, но не затрагивает настройки хоста.
- **CAP_SYS_PTRACE** ограничивается `kernel.yama.ptrace_scope` на хосте.

Для hardening rootless-контейнеров используйте `--cap-drop=ALL` с явным добавлением только необходимых capabilities: `--cap-add=NET_BIND_SERVICE` (для портов < 1024 после настройки sysctl), `--cap-add=CHOWN`, `--cap-add=SETUID` и т.д.

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

### 8. Отладка сетевого namespace (podman unshare --rootless-netns)

Для диагностики сетевых проблем в rootless-режиме используйте `podman unshare --rootless-netns` для входа в сетевой namespace контейнера и выполнения команд от его имени:

```bash
# Вход в сетевой namespace rootless-контейнера
podman unshare --rootless-netns

# Внутри namespace проверка интерфейсов и маршрутов
ip addr show
# → pasta0: <BROADCAST,NOARP,UP,LOWER_UP> mtu 65521 qdisc noqueue state UP
# → eth0@if11: <BROADCAST,NOARP,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP

ip route show
# → default via <host-gateway> dev pasta0
# → <subnet> dev eth0 proto kernel scope link src <container-ip>

# Проверка DNS-резолвинга внутри namespace
podman unshare --rootless-netns nslookup google.com
# → Server:	<dns-server>
# → Address:	<dns-server>#53

# Выход из namespace
exit
```

### 9. Отладка монтирования и хранилища (podman unshare mount)

Rootless-контейнеры используют отдельный mount namespace. Для проверки точек монтирования и отладки проблем с томами:

```bash
# Запуск контейнера с томом
podman run -d --name test -v ./data:/data:Z nginx

# Вход в mount namespace контейнера через unshare
podman unshare --mount=/proc/$(podman inspect --format '{{.State.Pid}}' test)/ns/mnt \
  ls -la /data
# → файлы томов с правильными UID/GID внутри namespace

# Проверка типа ФС тома
podman unshare --mount=/proc/$(podman inspect --format '{{.State.Pid}}' test)/ns/mnt \
  findmnt /data
# → /dev/fuse (если fuse-overlayfs) или overlay (если нативный overlay)

# Переключение на fuse-overlayfs при проблемах с нативным overlay
mkdir -p ~/.config/containers/storage
cat > ~/.config/containers/storage.conf << 'EOF'
[storage]
driver = "overlay"

[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
EOF

podman system reset
podman run --rm -v ./data:/data alpine ls /data
```

### 10. SELinux-контексты в rootless-режиме

В rootless-режиме SELinux-контекст процессов контейнера остается `unconfined_u:unconfined_r:unconfined_t`, что ослабляет изоляцию по сравнению с rootful-режимом (`system_u:system_r:container_runtime_t`).

```bash
# Проверка SELinux-контекста rootless-контейнера
podman inspect --format '{{.Process.Label}}' <container>
# → system_u:system_r:container_runtime_t:s0:cxxx (rootful)
# → unconfined_u:unconfined_r:unconfined_t:s0 (rootless)

# При монтировании томов используйте SELinux-метки для автоматического перемаркира:
podman run -v ./data:/data:Z nginx
# :Z — эксклюзивная маркировка для контейнера
# :z — разделяемая маркировка для нескольких контейнеров

# Проверка контекста файла на хосте после :Z
ls -Z ./data
# → system_u:object_r:container_file_t:s0 <file>

# Для home-директорий в rootless-режиме может потребоваться:
sudo semanage fcontext -a -t container_file_t "/home/<user>/.local/share/containers/storage(/.*)?"
sudo restorecon -Rv /home/<user>/.local/share/containers/storage
```

### 11. Systemd-юниты и Quadlet для rootless-сервисов

Для продакшен-развертывания rootless-контейнеров используйте `systemd --user` с Quadlet-файлами:

```bash
# Создание Quadlet-файла (~/.config/containers/systemd/nginx.container)
mkdir -p ~/.config/containers/systemd
cat > ~/.config/containers/systemd/nginx.container << 'EOF'
[Unit]
Description=NGINX rootless container
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/library/nginx:alpine
ContainerName=nginx-rootless
Publish=8080:80
Volume=./html:/usr/share/nginx/html:Z
AutoUpdate=registry

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Применение юнита
systemctl --user daemon-reload
systemctl --user enable --now nginx-container.service

# Проверка статуса
systemctl --user status nginx-container.service
journalctl --user -u nginx-container.service -f
```

### 12. Volume-опции и маппинг прав (:U, :idmap, :Z, :z)

```bash
# :U — автоматический chown для совместимости UID/GID хоста и контейнера
podman run -v ./project:/app:U node:20
# Эквивалент podman unshare chown -R $(id -u):$(id -g) ./project

# :idmap — маппинг через /etc/subuid без userns=keep-id
podman run --userns=auto -v ./project:/app:idmap node:20

# :Z — эксклюзивная SELinux-маркировка (один контейнер)
podman run -v ./data:/data:Z nginx

# :z — разделяемая SELinux-маркировка (несколько контейнеров)
podman run -v ./shared:/shared:z nginx
podman run -v ./shared:/shared:z redis

# Комбинирование опций
podman run \
  --userns=keep-id \
  -v ./app:/app:U,Z \
  -v ./logs:/var/log:z \
  node:20
```

---

## Валидация и проверка

После настройки rootless-окружения выполните следующие проверки:

```bash
# 1. Готовность rootless-режима
podman info --format '{{.Host.Security.Rootless}}'
# → true

# 2. Маппинг UID/GID
podman unshare cat /proc/self/uid_map
# → 0       1000          1
# → 1     100000      65536
podman unshare cat /proc/self/gid_map
# → аналогично uid_map

# 3. Сетевой namespace и pasta
podman unshare --rootless-netns ip addr show pasta0
# → интерфейс pasta0 существует и имеет IP хоста

# 4. Cgroup-делегирование
cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers
# → cpu cpuset io memory pids

# 5. Драйвер хранилища
podman info --format '{{.Store.GraphDriverName}}'
# → overlay (или fuse-overlayfs)

# 6. SELinux-контекст
podman run --rm -v /tmp:/tmp:Z alpine ls -Z /tmp
# → файл имеет контекст container_file_t

# 7. Socket Podman
ls -l /run/user/$(id -u)/podman/podman.sock
# → srw-rw---- 1 <user> <user> ... podman.sock
```

---

## Типичные проблемы и решения

### Permission Denied при монтировании томов

**Симптом:** `permission denied` при доступе к смонтированному каталогу внутри контейнера.

**Причина:** UID/GID владельца каталога на хосте не совпадают с UID/GID пользователя внутри контейнера.

**Решение:**
```bash
# Вариант 1: флаг :U (автоматический chown)
podman run -v ./data:/data:U <image>

# Вариант 2: podman unshare для ручной настройки
podman unshare chown -R 0:0 ./data

# Вариант 3: --userns=keep-id
podman run --userns=keep-id -v ./data:/data <image>
```

### Ошибка cgroup delegation

**Симптом:** `Error: cgroup v1 is not supported` или `permission denied` при установке `--memory`.

**Причина:** Администратор не делегировал контроллеры cgroup v2 пользователю.

**Решение:**
```bash
# Проверка текущих контроллеров
cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/cgroup.controllers

# Делегирование (от root)
echo 'Delegate=cpu cpuset io memory pids' | sudo tee /etc/systemd/system/user@.service.d/delegate.conf
sudo systemctl daemon-reload
# Перезайдите в систему
```

### Ошибка "no UID range allocated"

**Симптом:** `Error: container_linux.go:380: starting container process caused: unable to allocate user namespace: cannot find UID range for user <user>`.

**Причина:** В `/etc/subuid` или `/etc/subgid` отсутствует запись для пользователя.

**Решение:**
```bash
# Добавление диапазона (от root)
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER

# Проверка
grep $USER /etc/subuid
grep $USER /etc/subgid

# Применение без перезагрузки
podman system migrate
```

### Сеть pasta недоступна

**Симптом:** Контейнер не имеет сети или не может resolver DNS.

**Решение:**
```bash
# Проверка наличия pasta
which pasta
# → /usr/bin/pasta

# Проверка сетевого namespace
podman unshare --rootless-netns ip addr show
# → должны быть интерфейсы pasta0 и eth0

# Проверка DNS
podman unshare --rootless-netns cat /etc/resolv.conf
# → должен содержать nameserver aardvark-dns

# Перезапуск контейнера
podman stop <container>
podman rm <container>
podman run --name test alpine ping -c 1 google.com
```

### fuse-overlayfs падает с ошибкой монтирования

**Симптом:** `fuse: bad mount point` или `permission denied` при использовании fuse-overlayfs.

**Решение:**
```bash
# Проверка наличия fuse-overlayfs
which fuse-overlayfs

# Проверка параметра ядра
sysctl kernel.unprivileged_userns_clone
# → 1

# Принудительное использование fuse-overlayfs
mkdir -p ~/.config/containers/storage
cat > ~/.config/containers/storage.conf << 'EOF'
[storage]
driver = "overlay"

[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
EOF

podman system reset
podman run --rm alpine echo "OK"
```

---

## Рекомендации по безопасности

### Production-hardening rootless-контейнеров

1. **Минимальные привилегии:**
   ```bash
   podman run --cap-drop=ALL --security-opt=no-new-privileges <image>
   ```
   Явно добавляйте только необходимые capabilities: `--cap-add=NET_BIND_SERVICE`, `--cap-add=CHOWN`.

2. **Cgroup-изоляция:**
   ```bash
   podman run --cgroupns=private --pids-limit=100 <image>
   ```
   `--cgroupns=private` создает отдельный cgroup namespace; `--pids-limit` предотвращает fork-бомбы.

3. **Seccomp-профили:**
   ```bash
   podman run --security-opt seccomp=seccomp-profile.json <image>
   ```
   Используйте строгие seccomp-профили, запрещающие неиспользуемые syscalls.

4. **Read-only rootfs:**
   ```bash
   podman run --read-only --tmpfs /tmp --tmpfs /run <image>
   ```
   Запрещает запись в корневую ФС; временные директории монтируются в tmpfs.

5. **SELinux-маркировка:**
   Всегда используйте `:Z` или `:z` для томов, чтобы SELinux-метки были корректно установлены.

### Стабильность и производительность

1. **Memory high + swap:**
   ```bash
   podman run --memory=256m --memory-swap=512m <image>
   ```
   `memory.high` (soft limit) позволяет OOM-killer'у работать мягче, чем жесткий `memory.max`.

2. **CPU weight вместо cpu-shares:**
   ```bash
   podman run --cpu-shares=512 <image>
   ```
   В cgroups v2 `cpu.shares` транслируется в `cpu.weight` (диапазон 1-10000).

3. **I/O weight:**
   ```bash
   podman run --blkio-weight=300 <image>
   ```
   Полезно для контейнеров с высокой дисковой нагрузкой (базы данных).

4. **Tracing и отладка:**
   ```bash
   # Логи conmon
   journalctl --user -u conmon-<container-id>

   # События Podman
   podman events --filter event=start,stop,kill

# Трассировка syscall'ов (strace)
   podman unshare strace -p $(podman inspect --format '{{.State.Pid}}' <container>)
   ```

### Очистка окружения

```bash
# Остановка и удаление всех остановленных контейнеров
podman container prune -f

# Удаление неиспользуемых образов
podman image prune -a -f

# Полный сброс хранилища (осторожно!)
podman system reset
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
| **User namespace и PID 1** | PID 1 внутри rootless-контейнера не является `init`-процессом с полными привилегиями; обработка сигналов и zombie-процессов зависит от приложения. |
| **Порт < 1024 без sysctl** | Без изменения `net.ipv4.ip_unprivileged_port_start` rootless-контейнеры не могут занимать порты 1-1023, даже с `CAP_NET_BIND_SERVICE`. |
| **Совместимость с older kernel** | На ядрах < 5.11 нативный overlay недоступен; требуется `fuse-overlayfs` с накладными расходами 10-30% на чтение/запись. |

---

## Дополнительная информация

### Связанные разделы

- **[Изоляция в Podman](./linux_isolation.md)** — детальный разбор Namespaces, Capabilities и Seccomp.
- **[Подман: Хранилище](./podman_volumes_and_storage.md)** — подробнее о маппинге прав на файловой системе и драйверах.
- **[Миграция с Docker](./migration-from-docker.md)** — как перенести проекты и подготовить систему к rootless-режиму.

### См. также

- **[Официальная документация Podman: Rootless](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)** — пошаговое руководство (англ.).
- **[Rootless Podman networking docs](https://github.com/eriksjolund/podman-networking-docs)** — матрица способов подключения контейнера к хосту (pasta, host, socket activation).

# force reindex test
