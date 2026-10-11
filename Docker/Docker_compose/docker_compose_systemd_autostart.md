# Автозапуск Docker Compose через systemd

**Актуально для:** Docker Compose v5.x; systemd (cgroup v2). Содержит compose-специфичную практику; общая теория интеграции Docker и systemd — в SSoT-файле [Интеграция Docker и systemd](../../Linux/Core/systemd/docker_integration.md).

## Определения

**Compose-стек как системная служба** — запуск многоконтейнерного приложения через systemd-юнит, при котором `systemctl` управляет жизненным циклом всего стека (`docker compose up -d` / `docker compose down`), а не отдельных контейнеров.

**`Type=oneshot` + `RemainAfterExit=yes`** — паттерн юнита для compose: `ExecStart` (`docker compose up -d`) завершается сразу после запуска стека, а systemd считает службу активной до явной остановки. Это корректная модель, потому что `docker compose up -d` не держит foreground-процесс.

**`Delegate=yes`** — директива cgroup v2, передающая управление под-cgroups Docker-демону. Без неё лимиты, заданные в compose (`deploy.resources`), не применяются корректно.

**Конфликт политик перезапуска** — ситуация, когда `restart: always` в compose-файле и `Restart=` в юните одновременно управляют жизненным циклом контейнера: Docker пытается перезапустить контейнер, пока systemd считает юнит упавшим.

**Lingering** — механизм `loginctl enable-linger`, позволяющий user-юнитам systemd работать без активной сессии пользователя. Обязателен для rootless compose в автозапуске.

**`TimeoutStartSec=` / `TimeoutStopSec=`** — таймауты systemd на выполнение `ExecStart`/`ExecStop`. Дефолтный `TimeoutStartSec=90s` опасен для compose-юнита: `ExecStartPre` с `docker compose pull` на медленной сети не укладывается в 90 секунд, и юнит падает до запуска стека. Для compose-стеков задают `TimeoutStartSec=0` (без лимита) или явное значение; `TimeoutStopSec=` должен покрывать graceful shutdown самого медленного сервиса.

## Базовые концепции

### Зачем systemd-юнит, если есть `restart: always`

Контейнеры с `restart: always` действительно перезапускаются dockerd при старте демона после reboot. Юнит systemd нужен не для выживания контейнеров, а для:

1. **Детерминированного порядка загрузки:** `After=docker.service network-online.target` гарантирует, что стек не запустится раньше демона и сети (NFS, DNS).
2. **Управления жизненным циклом:** `systemctl stop myapp` корректно выполняет `docker compose down --timeout 30` с graceful shutdown, а не `docker kill`.
3. **Лимитов на уровне cgroup хоста:** `MemoryMax=`, `CPUQuota=` действуют немедленно, ещё до запуска контейнеров — в отличие от `deploy.resources`, которые применяются только при старте.
4. **Единой диагностики:** `systemctl status` и `journalctl -u` дают полную картину без переключения на Docker CLI.
5. **Защиты от конфликта политик:** при управлении через systemd политику `restart: always` в compose-файле отключают (см. анти-паттерн ниже).

### Жизненный цикл юнита compose-стека

| Событие | Действие systemd |
| :--- | :--- |
| `systemctl start myapp` | `ExecStartPre` (pull) → `ExecStart` (`docker compose up -d --remove-orphans`) → статус `active` |
| `systemctl stop myapp` | `ExecStop` (`docker compose down --timeout 30`) → статус `inactive` |
| `systemctl restart myapp` | `ExecStop` → `ExecStart`: полная пересборка стека (`down` + `pull` + `up`) с даунтаймом |
| Reboot хоста | `WantedBy=multi-user.target` запускает юнит после `docker.service` |
| Падение контейнера | Управляется политикой `restart:` compose-файла (systemd не отслеживает отдельные контейнеры в oneshot-юните) |

## Практические сценарии

### Сценарий 1: Эталонный юнит для compose-стека

Путь: `/etc/systemd/system/myapp-stack.service`

```ini
[Unit]
Description=My App Compose Stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/myapp-stack
Delegate=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
CPUQuota=100%
MemoryMax=4G
TimeoutStartSec=0
TimeoutStopSec=60

ExecStartPre=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down --timeout 30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp-stack
# → Создание симлинка /etc/systemd/system/multi-user.target.wants/myapp-stack.service
sudo systemctl status myapp-stack
# → active (exited) since ... — compose-стек запущен
```

**Ожидаемый результат:** Стек стартует после Docker-демона и сети, управляется через `systemctl`, лимиты cgroup применены.

**Почему `Type=oneshot`:** `docker compose up -d` возвращает управление сразу после запуска контейнеров; `RemainAfterExit=yes` сохраняет юнит в состоянии `active (exited)`, что корректно отражает «стек развёрнут».

### Сценарий 2: Rootless compose в автозапуске

Для стеков без root-демона используется user-юнит и lingering.

**Предварительные требования:** пакет `uidmap` (бинари `newuidmap`/`newgidmap`) и не менее 65 536 subordinate UID/GID для пользователя в `/etc/subuid` и `/etc/subgid` (проверка: `grep ^$(whoami): /etc/subuid`).

```bash
# 1. Установить rootless Docker (пакетный способ — основной)
sudo apt-get install -y docker-ce-rootless-extras    # в RPM-дистрибутивах тот же пакет
dockerd-rootless-setuptool.sh install
# → создаёт user-юнит ~/.config/systemd/user/docker.service и CLI-контекст "rootless"
# Альтернатива без пакетов (static-билды): curl -fsSL https://get.docker.com/rootless | sh
# Если системный dockerd уже запущен: sudo systemctl disable --now docker.service docker.socket

# 2. Разрешить user-юнитам работать без сессии
sudo loginctl enable-linger $USER

# 3. Проверка: CLI подключён к rootless-демону
docker info | grep -i context
# → rootless
```

```ini
# ~/.config/systemd/user/myapp-stack.service
[Unit]
Description=My App Rootless Compose Stack
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/myapp-stack
ExecStartPre=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down --timeout 30

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now myapp-stack
```

**Ожидаемый результат:** Стек запускается от непривилегированного пользователя после reboot без активной SSH-сессии.

**Нюансы:**
- `Requires=docker.service` в user-контексте — это user-юнит rootless-демона, созданный `dockerd-rootless-setuptool.sh`; без зависимости стек может стартовать раньше готовности демона.
- Часть приложений требует явного `DOCKER_HOST=unix:///run/user/$UID/docker.sock`.
- Ошибки `dbus` при `systemctl --user` — установить `dbus-user-session` и перелогиниться.

### Сценарий 3: Обновление стека

Два пути — выбор зависит от допустимого даунтайма:

```bash
# Путь A: полный рестарт через юнит (ExecStop → down, ExecStart → pull + up).
# Контейнеры удаляются и пересоздаются — есть даунтайм; named volumes сохраняются:
sudo systemctl restart myapp-stack

# Путь B: обновление без полной пересборки — пересоздаются только изменённые сервисы:
docker compose pull
docker compose up -d --wait --remove-orphans
```

**Ожидаемый результат:** `docker compose up --wait` (доступен с Compose v2.2.0) дожидается состояния `running|healthy` всех сервисов до возврата управления; `--wait-timeout <сек>` (с v2.17.0) ограничивает ожидание — задавайте явно в CI.

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `systemctl enable --now myapp-stack` | Включить автозапуск и запустить сейчас |
| `systemctl status myapp-stack` | Статус юнита (active (exited) = стек развёрнут) |
| `journalctl -u myapp-stack -f` | Логи юнита (вывод `docker compose` в journald) |
| `systemd-analyze verify myapp-stack.service` | Проверка синтаксиса юнита до применения |
| `systemctl show myapp-stack -p MemoryMax -p CPUQuota -p Delegate` | Проверка применённых лимитов cgroup и делегирования |
| `systemd-cgls --unit myapp-stack` | Дерево cgroup юнита (визуальная проверка `Delegate`) |
| `systemctl edit myapp-stack` | Drop-in для переопределения директив без правки юнита |
| `loginctl enable-linger $USER` | Автозапуск user-юнитов без сессии (rootless) |

## Устранение неполадок

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Юнит `failed` на `ExecStart` | Демон Docker ещё не готов или образ не pulled | Проверьте `After=docker.service`; добавьте `ExecStartPre=/usr/bin/docker compose pull` |
| Контейнеры не переживают reboot | Юнит не включён (`WantedBy` отсутствует) | `systemctl daemon-reload && systemctl enable --now myapp-stack` |
| Лимиты `deploy.resources` не работают | Отсутствует `Delegate=yes` в юните | Добавьте `Delegate=yes` (обязательно для cgroup v2) |
| `systemctl stop` зависает | `ExecStop` не завершается — контейнеры игнорируют SIGTERM | Увеличьте `--timeout` в `docker compose down --timeout 60` и `TimeoutStopSec=` |
| Rootless стек не стартует после reboot | Нет lingering | `sudo loginctl enable-linger $USER` |
| Порт занят после старта | Другой сервис хоста слушает тот же порт | `ss -tlnp \| grep :<port>`; проверьте `ports:` в compose-файле |
| Юнит падает на `ExecStartPre` через ~90 секунд | Дефолтный `TimeoutStartSec=90s` не хватает на `docker compose pull` | `TimeoutStartSec=0` (без лимита) или явное значение в юните |
| Rootless: `Cannot connect to the Docker daemon` | Не выбран контекст `rootless` или не задан `DOCKER_HOST` | `docker context use rootless`; при необходимости `export DOCKER_HOST=unix:///run/user/$UID/docker.sock` |
| Правки юнита не применяются | Забыт `daemon-reload` | `sudo systemctl daemon-reload` перед `restart` |

## Рекомендации

1. **Отключайте `restart: always` при управлении через systemd** — двойное управление жизненным циклом приводит к конфликтам: Docker перезапускает контейнер, пока systemd считает юнит упавшим. Оставьте `restart: unless-stopped` только если юнит не управляет стеком.
2. **Всегда указывайте `Delegate=yes`** — без делегирования cgroup-лимиты Docker игнорируются в cgroup v2.
3. **Валидируйте юнит перед применением:** `systemd-analyze verify` ловит синтаксические ошибки до ребута.
4. **Используйте `network-online.target`** для стеков, зависящих от DNS или NFS: `After=network-online.target` + `Wants=network-online.target`.
5. **Храните compose-файл в Git**, а `WorkingDirectory` указывайте явно — юнит не наследует ваш `PWD`.
6. **Добавьте `--wait` в `ExecStart` для стеков с `healthcheck`** — юнит не перейдёт в `active`, пока сервисы не станут `healthy`, что корректно упорядочивает зависимые юниты (`After=myapp-stack`).
7. **Логи контейнеров — не в journald юнита:** `journalctl -u myapp-stack` содержит только вывод `docker compose` (ExecStart/ExecStop). stdout контейнеров собирает log-драйвер Docker (по умолчанию `json-file`); для единого хранилища настройте `log-driver=journald` в `daemon.json`.

## Очистка и откат

```bash
# Остановить и отключить автозапуск (ExecStop выполнит docker compose down --timeout 30)
sudo systemctl disable --now myapp-stack

# Удалить юнит
sudo rm /etc/systemd/system/myapp-stack.service
sudo systemctl daemon-reload

# Полная очистка данных стека (внимание: named volumes удаляются только с -v)
docker compose down -v
```

**Важно:** `docker compose down` без `-v` не удаляет named volumes — данные переживают пересоздание стека.

## Дополнительная информация

- **[Интеграция Docker и systemd](../../Linux/Core/systemd/docker_integration.md)** — SSoT: эталонные юниты, `sdnotify`, socket activation, делегирование cgroup, диагностика.
- **[Systemd в Docker](../docker_systemd.md)** — systemd как PID 1 внутри контейнера (отдельная задача, не путать с внешним управлением).
- **[Podman: Quadlet](../../Podman/podman-quadlet-vs-podlet.md)** — нативная генерация юнитов для Podman; у Docker Compose аналога нет, юнит пишется вручную.
- **[Миграция VPS без простоя](./vps_migration_zero_downtime.md)** — перенос стека между хостами.
- **[Справочник команд CLI](./docker_compose_cli_commands.md)** — `docker compose up --wait`, `down --timeout`.
- **[Rootless mode](https://docs.docker.com/engine/security/rootless/)** — официальная документация: prerequisites, `dockerd-rootless-setuptool.sh`, troubleshooting.
