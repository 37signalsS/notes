# Безопасность Docker Compose: сокет, rootless, секреты

**Актуально для:** Docker Engine 29.x, Docker Compose v5.x. Общий hardening хоста и демона — в SSoT-файле [Защита хоста и демона Docker](../Docker_security/host_daemon_hardening.md); здесь — compose-специфичные векторы.

## Определения

**Эквивалентность сокета и root** — доступ к `/var/run/docker.sock` эквивалентен полному root-доступу к хосту: контейнер с примонтированным сокетом может запустить привилегированный контейнер с корневой ФС хоста.

**`docker-socket-proxy`** — прокси Docker API (HAProxy), блокирующий API-секции по env-переменным (`0` — запрет, `1` — разрешение; заблокированные запросы получают HTTP 403). По умолчанию открыты только `EVENTS`, `PING`, `VERSION`; критичные секции (`AUTH`, `SECRETS`, `POST`) закрыты. `POST=0` переводит весь API в режим read-only (только GET/HEAD) — единственный безопасный режим для мониторинга; `CONTAINERS=1` без `POST=0` открывает полный жизненный цикл контейнеров, включая создание и удаление.

**Rootless Compose** — запуск compose-стеков через rootless-демон (`dockerd-rootless-setuptool.sh`): демон и контейнеры работают от непривилегированного пользователя через user namespaces.

**`userns-remap`** — маппинг UID/GID контейнера на диапазон непривилегированных UID хоста (`host_uid = container_uid + base_id`): root внутри контейнера ≠ root на хосте.

**Compose security directives** — директивы compose-файла для минимизации привилегий: `cap_drop`, `security_opt`, `read_only`, `tmpfs`, `user`, `pids_limit`.

## Базовые концепции

### Вектор атаки через compose-файл

Частый анти-паттерн в `compose.yml` — проброс сокета демона в сервис (для DinD, CI-раннеров, мониторинга):

```yaml
services:
  ci-runner:
    image: my-runner
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # = root на хосте
```

Компрометация такого сервиса даёт полный контроль над хостом. Альтернативы:

1. **`docker-socket-proxy`** — гранулярный доступ к API-секциям; read-only режим через `POST=0` (см. сценарий 1).
2. **Rootless-демон** — даже при побеге из контейнера права ограничены пользователем.
3. **`userns-remap`** — root контейнера маппится на непривилегированный UID хоста.

### Иерархия мер изоляции в compose

| Мера | Что даёт | Когда применять |
| :--- | :--- | :--- |
| `cap_drop: [ALL]` + `cap_add` | Отказ от всех capabilities, кроме явно нужных | Всегда, кроме легаси-образов |
| `read_only: true` | Корневая ФС контейнера read-only | Статичные сервисы |
| `tmpfs` | Секреты и временные файлы только в RAM | Конфиги, токены |
| `security_opt: [no-new-privileges]` | Запрет эскалации через SUID/SGID | Всегда |
| `user: <non-root>` | Процесс не root внутри контейнера | Всегда, когда образ позволяет |
| `pids_limit: <N>` | Лимит процессов в контейнере (защита от fork-бомб) | Всегда, кроме легаси-образов |
| `privileged: true` | Все capabilities + прямой доступ к устройствам хоста | **Никогда** — анти-паттерн, эквивалентен root на хосте |
| `userns-remap` / rootless | Root контейнера ≠ root хоста | Production по умолчанию |

## Практические сценарии

### Сценарий 1: Read-only доступ к API через docker-socket-proxy

```yaml
# compose.yml
services:
  socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    environment:
      CONTAINERS: 1   # секция API контейнеров: список, inspect, stats
      IMAGES: 1
      NETWORKS: 1
      POST: 0         # только GET/HEAD — API целиком read-only
      # ВНИМАНИЕ: CONTAINERS=1 без POST=0 открывает POST /containers/create
      # и DELETE /containers/{id} — то есть полный контроль над контейнерами
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "127.0.0.1:2375:2375"   # только localhost; для потребителя-контейнера
                                 # лучше внутренняя сеть без публикации портов
    security_opt:
      - no-new-privileges:true
    read_only: true
    cap_drop: [ALL]
```

Проверка:

```bash
DOCKER_HOST=tcp://127.0.0.1:2375 docker ps          # → список контейнеров (GET)
DOCKER_HOST=tcp://127.0.0.1:2375 docker run alpine  # → 403 Forbidden
```

**Ожидаемый результат:** Сервисы (мониторинг, UI) получают данные Docker API; любая модифицирующая операция отвергается с HTTP 403.

**Нюансы (по upstream README):**
- Гранулярные операции внутри секции контейнеров: `ALLOW_START`, `ALLOW_STOP`, `ALLOW_RESTARTS`, `ALLOW_PAUSE`, `ALLOW_UNPAUSE` — разрешают отдельные действия без полного `CONTAINERS=1`.
- Upstream рекомендует запускать прокси с `--privileged` (сокет — privileged-подключение в некоторых SELinux/AppArmor-контекстах); в таком случае `cap_drop: [ALL]` несовместим — `privileged` даёт все capabilities.
- Прокси не поддерживает TLS (по дизайну) — plain HTTP к Unix-сокету; не публикуйте порт наружу, доступ только с localhost или по внутренней Docker-сети с потребителем.
- Нестандартный путь сокета — `SOCKET_PATH=/var/run/balena-engine.sock`; уровень логов — `LOG_LEVEL=debug|info|notice|warning|err|crit|alert|emerg`.

### Сценарий 2: Rootless compose-стек

```bash
# 1. Предварительные требования: cgroup v2
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs

# 2. Зависимости (Debian/Ubuntu)
sudo apt install -y dbus-user-session uidmap slirp4netns   # или passt для pasta

# 3. Установка rootless Docker (создаёт контекст "rootless")
curl -fsSL https://get.docker.com/rootless | sh

# 4. Автозапуск демона без активной сессии
sudo loginctl enable-linger $USER

# 5. Проверка
docker context use rootless
docker info | grep -A2 "Security Options"
# →  rootless

# 6. Запуск стека
docker compose up -d --wait
```

**Ожидаемый результат:** Стек работает без root-демона; сокет лежит в `/run/user/<UID>/docker.sock`.

**Ограничение:** rootless не может биндить порты < 1024 — решение: `sysctl net.ipv4.ip_unprivileged_port_start=80` или reverse proxy (Nginx, Traefik) на хосте.

### Сценарий 3: Секреты в compose без утечки

```yaml
services:
  app:
    image: myapp:1.0.0
    secrets:
      - db_password
    # секрет монтируется в /run/secrets/db_password
secrets:
  db_password:
    file: ./secrets/db_password.txt   # права 600 на файл на хосте
```

**Ожидаемый результат:** Секрет доступен в контейнере как файл, не попадает в образ, переменные окружения и логи.

**Нюанс Compose:** секрет из `file:` доставляется как bind-mount — права на смонтированный файл равны правам исходного файла на хосте; директивы `mode`, `uid`, `gid` в Compose **не применяются** (они работают только в Swarm; спецификация задаёт default `mode: 0444`, но bind-mount не меняет права). Безопасность определяется правами файла-источника (`chmod 600`) и доступом к каталогу. Секрет из переменной окружения хоста (только Compose, не `docker stack deploy`): `secrets: { token: { environment: OAUTH_TOKEN } }`.

**Для сборки:** `build.secrets` (BuildKit) передаёт токены в процесс сборки без сохранения в слоях образа — см. [Продвинутые возможности](./docker_compose_advanced_topics.md).

### Сценарий 4: userns-remap для rootful демона

```bash
# 1. Диапазоны UID для маппинга
sudo usermod --add-subuids 100000-165536 --add-subgids 100000-165536 dockremap

# 2. Включение в /etc/docker/daemon.json
{ "userns-remap": "default" }

# 3. Перезапуск демона
sudo systemctl restart docker
```

**Ожидаемый результат:** UID 0 внутри контейнера = UID 100000 на хосте. **Нюанс:** bind mount требует ручного согласования UID на хосте (`chown 100000:100000 /data`), named volume — нет (Docker управляет правами).

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `docker context use rootless` | Переключение на rootless-демон |
| `docker info \| grep -E "Rootless\|Security Options"` | Проверка режима демона |
| `loginctl enable-linger $USER` | Автозапуск rootless-демона |
| `docker compose config` | Проверка итоговой конфигурации (включая secrets) |
| `docker inspect --format '{{.Config.User}}' <c>` | Проверка, что контейнер не root |

## Устранение неполадок

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` при rootless | Нет cgroup v2 или `user.max_user_namespaces=0` | `stat -fc %T /sys/fs/cgroup/`; `sysctl user.max_user_namespaces` |
| Rootless не биндит порт 80 | Непривилегированный порт < 1024 | `sysctl net.ipv4.ip_unprivileged_port_start=80` или reverse proxy |
| `operation not permitted` (seccomp) | Системный вызов заблокирован профилем | Легитимный вызов — кастомный профиль через `security_opt: seccomp=...`; не отключайте seccomp целиком |
| Bind mount не пишется при `userns-remap` | UID на хосте ≠ маппингу контейнера | `chown 100000:100000 <dir>` или переход на named volume |
| `overlay2` не работает с `userns-remap` | Ядро не поддерживает | `fuse-overlayfs` или `vfs`; на ядре 5.11+ — idmapped mounts |
| Сервис с сокетом скомпрометирован | Прямой проброс `docker.sock` | Замените на `docker-socket-proxy` с `POST=0` или rootless |
| `403 Forbidden` от socket-proxy | API-секция отозвана (`0` или не задана) | Ожидаемое поведение прокси; включите нужную секцию (`CONTAINERS=1`) или оставьте `POST=0` |
| `mode`/`uid`/`gid` секрета игнорируются | Compose доставляет `file:`-секреты через bind-mount | Права задаются на файле-источнике на хосте (`chmod 600`); `mode` работает только в Swarm |
| Прокси не подключается к сокету (SELinux/AppArmor) | Сокет — privileged-подключение в ограниченных контекстах | Запуск с `privileged: true` (upstream-рекомендация); `cap_drop: [ALL]` при этом несовместим |

## Рекомендации

1. **Никогда не монтируйте `docker.sock` напрямую в production** — только `docker-socket-proxy` с `POST=0` (read-only) или минимальным набором секций, либо Portainer Agent.
2. **Rootless или `userns-remap` по умолчанию** — root-демон должен быть исключением.
3. **Минимальные привилегии в compose-файле:** `cap_drop: [ALL]`, `read_only: true`, `security_opt: [no-new-privileges]`, `user:` — для каждого сервиса.
4. **Секреты — через `secrets:` и `build.secrets`**, не через переменные окружения (они видны в `ps`, `docker inspect` и логах).
5. **Аудит:** `auditd` на обращения к `/var/run/docker.sock`, `Docker Bench for Security` или `trivy config .` (misconfiguration scanning) не реже еженедельно.
6. **Пините образы по digest** — `image: myapp@sha256:<digest>` вместо плавающего тега: тег перезаписываем, digest гарантирует неизменность образа (supply chain).
7. **`.env` и файлы секретов — в `.gitignore`** с правами `600`; `env_file` с секретами не коммитится в репозиторий.

## Дополнительная информация

- **[Защита хоста и демона Docker](../Docker_security/host_daemon_hardening.md)** — SSoT: userns-remap, rootless, LSM, sysctl, аудит.
- **[Защита контейнеров](../Docker_security/container_hardening.md)** — capabilities, seccomp, cgroups внутри контейнера.
- **[SSH-agent в rootless Docker](../Docker_security/ssh-agent-rootless.md)** — передача ssh-agent через UID mapping.
- **[Управление секретами](../Docker_security/secrets_management.md)** — Docker Secrets, BuildKit `--mount=type=secret`.
- **[Продвинутые возможности](./docker_compose_advanced_topics.md)** — `secrets:`, `build.secrets`, `x-` шаблоны.
- **[Обзор Docker Compose](./docker_compose_overview.md)** — рекомендации по безопасности (раздел «Безопасность»).
