# Диагностика демона Docker (Daemon Failures)

**Актуально для:** Docker Engine 29.x (минимум 23.0+ для `dockerd --validate`); особенности 28.x отмечены отдельно; Docker Desktop 4.x; rootless — `dockerd-rootless` из состава Engine

Файл — диагностика и устранение проблем с демоном `dockerd`: не запущен, не стартует, падает в цикле, недоступен по сокету. Настройка демона (`daemon.json`, хранилища, логирование, TLS) — в **[daemon.json — полном референсе](../docker_daemon_config.md)**; контексты и удалённое управление — в **[Docker Context](../docker_context.md)**.

## Определения

**«Cannot connect to the Docker daemon»** — ошибка CLI при невозможности достучаться до демона `dockerd` через сокет (полный текст: `Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?`). Причины лежат на одном из трёх уровней: демон не запущен, CLI смотрит не на тот endpoint (контекст/`DOCKER_HOST`), или нет прав на сокет.

**Docker socket** — unix-сокет, через который CLI и API-клиенты общаются с демоном. Rootful Engine: `/var/run/docker.sock` (симлинк на `/run/docker.sock`, владелец `root:docker`, права `srw-rw----`). В пакетных установках сокет создаётся юнитом `docker.socket` (socket-активация), а `docker.service` стартует `dockerd -H fd:// --containerd=/run/containerd/containerd.sock`. Rootless Engine: `$XDG_RUNTIME_DIR/docker.sock` (обычно `/run/user/<UID>/docker.sock`).

**Docker context** — именованный набор параметров подключения (endpoint, TLS-сертификаты). Позволяет переключаться между локальным и удалёнными демонами без изменения переменных окружения; активный контекст хранится в `~/.docker/config.json` (`currentContext`).

**Rootless mode** — режим работы `dockerd` без root-привилегий через user namespaces (`dockerd-rootless.sh`). Демон, сокет и данные живут в user namespace пользователя.

## Основные концепции

### Как CLI находит демон

Порядок разрешения endpoint (документация Docker CLI → `docker context`):

1. Флаг `-H/--host` (и глобальный `--context`) в команде.
2. Переменная окружения `DOCKER_HOST` — **переопределяет активный контекст** (CLI выводит предупреждение `Warning: DOCKER_HOST environment variable overrides the active context`).
3. Переменная `DOCKER_CONTEXT` — переопределяет контекст, установленный через `docker context use`.
4. Текущий контекст (`docker context ls`, активный помечен `*`).
5. Дефолт: встроенный контекст `default` → `unix:///var/run/docker.sock`.

Форматы `DOCKER_HOST`: `unix:///var/run/docker.sock`, `tcp://<host>:2375` (без TLS), `tcp://<host>:2376` (с TLS), `ssh://user@host` (через SSH).

### Логи демона

Сам `dockerd` пишет логи не через лог-драйверы контейнеров, а в системный журнал (детали — **[daemon.json](../docker_daemon_config.md)**):

- **systemd**: `journalctl -u docker` (follow: `journalctl -u docker -f`; окно: `--since "10 minutes ago"`)
- **Без systemd** (SysVinit/init-скрипты): dockerd пишет в stderr; попадание в syslog или `/var/log/docker.log` зависит от настройки init-скрипта, сам демон файл не открывает
- **Rootless**: `journalctl --user -u docker` (user-юнит)
- **Debug-уровень**: `dockerd --debug` или `"debug": true` в `daemon.json`; проверка — `docker info | grep -i debug` → `Debug Mode: true`

### Почему dockerd может не стартовать

| Класс причин | Примеры |
| :--- | :--- |
| **Конфигурация** | Невалидный `daemon.json` (JSON-синтаксис, неизвестная опция) — dockerd отказывается стартовать |
| **Ядро** | 28.0.0 требовал модули `ip_set` (в 28.0.1 зависимость убрана); правила в iptables-таблице `raw` (с 28.0.x) требуют `CONFIG_IP_NF_RAW` (обход — с 28.0.2); graphdriver overlay2 требует модуль `overlay` (детали — **[Команды Docker](../docker_commands.md)**) |
| **containerd** | До 29.x: системный `containerd` должен быть запущен; с 29.7 — экспериментальный встроенный containerd (`"features": {"embedded-containerd": true}`); fallback на встроенный, если системный не сконфигурирован и не установлен (moby#53388) |
| **Диск** | Заполнен `/var/lib/docker` — демон падает при инициализации хранилища |
| **Состояние** | Повреждённый `/var/lib/docker` (обрыв питания, `kill -9 dockerd`) |
| **Адресные пулы** | Подсети Docker перекрывают существующие маршруты — `could not find an available, non-overlapping IPv4 address pool` (лечится `default-address-pools` в `daemon.json`) |
| **Порт** | Занят TCP-порт демона (`2375`/`2376`) при удалённом доступе |
| **API-версия** | Клиент < Docker 25.0 против демона 29+: демон требует API v1.44 минимум |

## Практические сценарии

### Сценарий 1: «Cannot connect to the Docker daemon. Is the docker daemon running?»

Диагностика по уровням — от демона к правам:

```bash
# 1. Демон запущен?
systemctl is-active docker
# → active
# → inactive (не запущен) или unknown (юнит не найден)

systemctl status docker --no-pager
# → Active: active (running) ... или "failed" / "activating (auto-restart)"

# 2. Процесс dockerd существует?
ps aux | grep [d]ockerd
# → root  1234  ... /usr/bin/dockerd -H fd://

# 3. Сокет на месте?
ls -l /var/run/docker.sock
# → srw-rw---- 1 root docker 0 ... /var/run/docker.sock

# сокет при socket-активации создаёт отдельный юнит:
systemctl status docker.socket --no-pager
# → Active: active (running) ... /var/run/docker.sock

# 4. CLI смотит не туда?
docker context show
# → default
docker context ls
# → NAME        DESCRIPTION     DOCKER ENDPOINT
# → default *   Current ...     unix:///var/run/docker.sock
echo "$DOCKER_HOST"
# → (пусто) или unix:///run/user/1000/docker.sock
```

Если `DOCKER_HOST` указывает на rootless-сокет, а вы работаете из rootful-сессии (или наоборот) — CLI молча обращается к несуществующему endpoint. Предупреждение `DOCKER_HOST environment variable overrides the active context` означает, что активный контекст полностью проигнорирован.

**Stale-сокет после нечистого падения:** если dockerd вылетел, не удалив сокет, при старте — `listen unix /var/run/docker.sock: bind: address already in use`. Убедитесь, что процесс dockerd отсутствует (`ps aux | grep [d]ockerd`), удалите сокет (`sudo rm /var/run/docker.sock`) и стартуйте демон.

### Сценарий 2: «Got permission denied while trying to connect to the Docker daemon socket»

**Причина:** пользователь не в группе `docker` (сокет `root:docker 660`).

```bash
# Проверка членства
id
# → uid=1000(user) groups=1000(user)   ← группы docker нет

# Решение
sudo usermod -aG docker $USER
# → требуется перелогин (или newgrp docker для текущей сессии)
```

**Валидация:** `docker ps` без `sudo` после перелогина.

### Сценарий 3: dockerd не стартует / падает при старте

```bash
# Логи демона — первая точка входа
sudo journalctl -u docker --no-pager | tail -50

# Типичные строки:
# → "unable to configure the Docker daemon with file /etc/docker/daemon.json:
#    the following directives don't match any configuration option: unknown-option"
# → "failed to start daemon: error initializing graphdriver: ..."
# → "could not find an available, non-overlapping IPv4 address pool"
# → "Your kernel does not support ... ipset" (только 28.0.0)
```

**Проверка конфигурации без запуска демона** (флаг `--validate`, доступен с Docker 23.0, moby#42393; с 28.x также проверяет `registry-mirrors`):

```bash
sudo dockerd --validate --config-file=/etc/docker/daemon.json
# → configuration OK
# → echo $? → 0

# При ошибке:
# → unable to configure the Docker daemon with file ...: unknown-option
# → echo $? → 1
```

`--validate` позволяет проверить `daemon.json` до рестарта демона — критично в production: невалидный конфиг после `systemctl restart docker` кладёт демон вместе со всеми контейнерами.

### Сценарий 4: dockerd в цикле перезапусков (crash loop)

Система сама рестартует демон, и `systemctl status` показывает `activating (auto-restart)` — но причину видно только в журнале:

```bash
# Число перезапусков
systemctl show docker -p NRestarts --no-pager
# → NRestarts=12

# Ошибка непосредственно перед вылетом
journalctl -u docker --since "10 minutes ago" --no-pager | tail -20

# Реальный ExecStart (включая drop-ins из /etc/systemd/system/docker.service.d/)
systemctl cat docker --no-pager
# → [Service]
# → ExecStart=/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
```

### Сценарий 5: зависимость от containerd

До 29.x dockerd запускает и управляет отдельным процессом containerd; если тот не запущен — демон не стартует:

```bash
systemctl status containerd --no-pager
# → Active: inactive (dead)

ls -l /run/containerd/containerd.sock
# → No such file or directory

journalctl -u docker --no-pager | grep -i containerd
# → "failed to start daemon: ... containerd" / "containerd not running"
```

**Встроенный containerd (Docker 29.7+, экспериментальный):** включается feature-флагом:

```json
{"features": {"embedded-containerd": true}}
```

Особенности (документация Docker Engine 29):
- Состояние хранится в `/var/lib/docker/containerd/daemon`, а не в `/var/lib/containerd` — контейнеры и образы системного containerd в embedded-режиме **недоступны**.
- Endpoint: `/var/run/docker/containerd/containerd.sock`; несовместим с `cri-containerd`.
- Начиная с 29.x (moby#53388) dockerd автоматически переключается на встроенный containerd, если системный не сконфигурирован и не установлен; ошибки конфигурации и прав остаются фатальными.

**Симптом отсутствия shim:** демон стартует, но контейнеры не запускаются — `failed to start shim: failed to resolve runtime path: runtime "io.containerd.runc.v2" binary not installed "containerd-shim-runc-v2"`. Проверка: `command -v containerd-shim-runc-v2`.

### Сценарий 6: несовместимость версий API (client too new / too old)

```bash
docker ps
# → client version 1.51 is too new. Maximum supported API version is 1.47
# → client version 1.41 is too old. Minimum supported API version is 1.44,
#   please upgrade your client to a newer version

# Версии и API клиента/демона
docker version
# → Client: 29.8.2 / Server: 28.5.2 (API 1.47)

# Временная отладка — понизить согласованную версию
export DOCKER_API_VERSION=1.47
```

Демон 29.x требует минимум API v1.44 (Docker 25.0+): старые клиенты (< 25.0) получают «too old» и подлежат обновлению.

### Сценарий 7: диск заполнен или повреждено состояние `/var/lib/docker`

```bash
df -h /var/lib/docker
# → Use% 100%

journalctl -u docker --no-pager | grep -i "no space left"
# → failed to start daemon: error initializing graphdriver: ... no space left on device
```

Восстановление:
1. Демон не стартует — `docker system prune` недоступен; чистить вручную: логи контейнеров `/var/lib/docker/containers/*/*-json.log`, `/var/lib/docker/tmp`, кэш сборки.
2. При повреждении хранилища (обрыв питания): остановить docker, `sudo mv /var/lib/docker /var/lib/docker.bak`, стартовать демон (создаст чистое состояние), восстановить данные из бэкапа.
3. После старта на чистом месте — `docker image prune -a` и проверка `docker info`.

### Сценарий 8: удалённый демон (DOCKER_HOST / context)

```bash
# Подключение по TCP без TLS (только в доверенной сети!)
export DOCKER_HOST=tcp://10.0.0.5:2375
docker ps

# Через SSH (Docker CLI 20.10+):
docker -H ssh://deploy@10.0.0.5 ps

# Контекст — постоянная настройка
docker context create prod --docker "host=ssh://deploy@10.0.0.5"
docker context use prod
# → prod
docker context ls
# → prod *   ...   ssh://deploy@10.0.0.5

# TLS-параметры контекста
docker context inspect prod
```

**Типичные TLS-ошибки:** `x509: certificate signed by unknown authority` (не доверенный CA), `x509: certificate has expired` (просроченный сертификат), `remote error: tls: bad certificate` (несовпадение клиентских сертификатов). Проверка: `docker --tlsverify --tlscacert=... --tlscert=... --tlskey=... -H tcp://host:2376 ps`.

### Сценарий 9: Docker Desktop (macOS/Windows)

На macOS/Windows «Cannot connect to the Docker daemon at unix:///var/run/docker.sock» при не запущенном приложении Docker Desktop. Решение: запустить Docker Desktop (или `open -a Docker` на macOS), дождаться статуса «Engine running» в меню. В WSL2-бэкенде сокет пробрасывается в дистрибутив автоматически.

### Сценарий 10: Rootless-режим

```bash
# Сокет лежит в user namespace
ls -l $XDG_RUNTIME_DIR/docker.sock
# → srw-rw---- 1 user user 0 ... /run/user/1000/docker.sock

# CLI должен смотреть на rootless-сокет
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
docker ps

# Данные rootless-демона
du -sh ~/.local/share/docker/
```

**Привилегированные порты в rootless** (документация Docker):

```bash
docker run -p 80:80 nginx:alpine
# → Error response from daemon: ... cannot expose privileged port 80,
#   you might need to add "net.ipv4.ip_unprivileged_port_start=0"
#   (currently 1024) to /etc/sysctl.conf, or set CAP_NET_BIND_SERVICE
#   on rootlesskit binary, or choose a larger port number (>= 1024)
```

Решения (по документации Docker):

```bash
# Вариант 1: разрешить непривилегированным процессам все порты
echo "net.ipv4.ip_unprivileged_port_start=0" | sudo tee /etc/sysctl.d/99-rootless-docker.conf
sudo sysctl --system

# Вариант 2: CAP_NET_BIND_SERVICE на rootlesskit
sudo setcap cap_net_bind_service=ep $(which rootlesskit)
systemctl --user restart docker

# Вариант 3 (рекомендуемый): маппить на непривилегированный порт
docker run -p 8080:80 nginx:alpine
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Cannot connect to the Docker daemon. Is the docker daemon running?` | Демон не запущен, неверный контекст или `DOCKER_HOST` | Сценарий 1: `systemctl is-active docker`, `docker context ls`, `echo $DOCKER_HOST` |
| `Got permission denied while trying to connect to the Docker daemon socket` | Пользователь не в группе `docker` | `sudo usermod -aG docker $USER` + перелогин |
| `unable to configure the Docker daemon with file ...` | Невалидный `daemon.json` | `sudo dockerd --validate --config-file=/etc/docker/daemon.json`; исправить опцию |
| dockerd в `activating (auto-restart)` | Падает сразу после старта | Сценарий 4: `systemctl show docker -p NRestarts`, `journalctl -u docker --since` |
| `failed to start daemon: ... containerd` | Системный containerd не запущен (до 29.x) | `systemctl start containerd`; в 29.7+ — `embedded-containerd` (Сценарий 5) |
| `failed to start shim: ... containerd-shim-runc-v2 ... not installed` | Нет shim-бинарника при embedded/managed containerd | Установить `containerd` package (содержит shim) |
| `client version X is too new/too old` | Разрыв версий CLI и демона | Сценарий 6: `DOCKER_API_VERSION` или обновление |
| `error initializing graphdriver: ... no space left on device` | Заполнен `/var/lib/docker` | Сценарий 7: чистка вручную, `df -h` |
| Повреждённое состояние `/var/lib/docker` | Обрыв питания, `kill -9 dockerd` | Сценарий 7: вынести каталог, старт с чистого состояния, восстановление из бэкапа |
| `could not find an available, non-overlapping IPv4 address pool` | Подсети Docker перекрывают маршруты хоста | `default-address-pools` в `daemon.json` (детали — **[daemon.json](../docker_daemon_config.md)**) |
| `Your kernel does not support ipset` | Ядро без `ip_set` на **28.0.0** | Обновиться до 28.0.1+ (зависимость убрана, moby#49530) или включить модули ядра |
| `failed to set up container networking ... can't initialize iptables table 'raw'` | Ядро без `CONFIG_IP_NF_RAW` (правила raw — с 28.0.x; DIRECT ACCESS FILTERING — с 28.2.0) | Обновить ядро; временно — `DOCKER_INSECURE_NO_IPTABLES_RAW=1` (с 28.0.2, снижает безопасность); с 28.2 — `"allow-direct-routing": true` (детали — **[Команды Docker](../docker_commands.md)**) |
| `x509: certificate signed by unknown authority` / `expired` | TLS-подключение к удалённому демону | Правильные `--tlscacert`/`--tlscert`/`--tlskey` (Сценарий 8) |
| `cannot expose privileged port` (rootless) | Порт < 1024 в rootless-режиме | `net.ipv4.ip_unprivileged_port_start=0`, `setcap` на `rootlesskit` или порт ≥ 1024 |
| Rootless: сокет не найден | `DOCKER_HOST` не выставлен | `export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock` |
| `listen unix /var/run/docker.sock: bind: address already in use` | Stale-сокет после нечистого падения | Убедиться, что dockerd нет (`ps aux \| grep [d]ockerd`), удалить сокет, стартовать демон |
| Демон стартует, но контейнеры не запускаются | Повреждённое состояние `/var/lib/docker` | `journalctl -u docker`; в крайнем случае — очистка неиспользуемых ресурсов (`docker system prune`), восстановление из бэкапа |

## Валидация

```bash
# 1. Демон отвечает
docker info --format '{{.ServerVersion}} {{.Driver}}'
# → 29.8.2 overlay2

# 2. Конфиг валиден
sudo dockerd --validate --config-file=/etc/docker/daemon.json
# → configuration OK

# 3. Контекст указывает на живой endpoint
docker context ls
# → default *   ...   unix:///var/run/docker.sock

# 4. Демон стабилен (нет crash loop)
systemctl show docker -p NRestarts --no-pager
# → NRestarts=0

# 5. Rootless: сокет доступен
docker -H unix://$XDG_RUNTIME_DIR/docker.sock version
# → Client / Server версии совпадают
```

## Лучшие практики

1. **Проверяйте `daemon.json` перед рестартом** через `dockerd --validate` — в production рестарт демона останавливает все контейнеры.
2. **Не используйте `tcp://` без TLS** вне доверенной сети — API Docker эквивалентен root-доступу на хосте.
3. **Контексты вместо `DOCKER_HOST`** для постоянных удалённых подключений — явнее и переносимо между сессиями; помните, что `DOCKER_HOST` молча переопределяет активный контекст.
4. **Алерты на демон**: `systemctl is-active docker` и метрики daemon (`metrics-addr` в `daemon.json`, см. **[Нативные метрики](../Docker_metrics/docker_native_metrics.md)**).
5. **Rootless для одиночных хостов** без требования привилегированных портов — меньше поверхность атаки; помните про ограничение портов < 1024.
6. **Логи демона — первый источник правды** при любых проблемах со стартом: `journalctl -u docker` до экспериментов с контейнерами.
7. **Бэкап `/var/lib/docker`** (или `docker save` критичных образов) — восстановление после повреждения хранилища возможно только из бэкапа.

## Дополнительная информация

### Rootful vs Rootless

| Критерий | Rootful | Rootless |
| :--- | :--- | :--- |
| Сокет | `/var/run/docker.sock` (`root:docker`) | `$XDG_RUNTIME_DIR/docker.sock` |
| Данные | `/var/lib/docker` | `~/.local/share/docker` |
| Порты < 1024 | Доступны | Требуют `sysctl`/`setcap` |
| Привилегии | root | user namespace |
| Логи | `journalctl -u docker` | `journalctl --user -u docker` |

### См. также

- **[daemon.json — полный референс](../docker_daemon_config.md)** — конфигурация демона, логи, TLS.
- **[Команды Docker](../docker_commands.md)** — таблица типовых ошибок CLI, включая требования к ядру в 28.x.
- **[Docker Context](../docker_context.md)** — удалённое управление и TLS.
- **[Коды завершения](./docker_exit_codes.md)** — если демон запущен, но контейнеры падают.
- **[Диагностика hung-контейнеров](./hung_containers.md)** — демон отвечает, но контейнер завис.
- **[Методология диагностики](./troubleshooting_methodology.md)** — маршрутизация по симптомам.

**Глубокое изучение:**
- **[Rootless mode (документация Docker)](https://docs.docker.com/engine/security/rootless/)** — установка и ограничения.
- **[Rootless troubleshooting (документация Docker)](https://docs.docker.com/engine/security/rootless/troubleshoot/)** — привилегированные порты, ping, DNS.
- **[Docker contexts (документация Docker)](https://docs.docker.com/engine/manage-resources/contexts/)** — precedence `DOCKER_HOST`/`DOCKER_CONTEXT`/контекстов.
- **[Release notes Engine 28](https://docs.docker.com/engine/release-notes/28/)** — требования к ядру (`ip_set`, `CONFIG_IP_NF_RAW`).
- **[Release notes Engine 29](https://docs.docker.com/engine/release-notes/29/)** — встроенный containerd, минимальная API-версия.
