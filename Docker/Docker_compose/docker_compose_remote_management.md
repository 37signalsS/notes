# Удалённое управление Docker Compose: контексты и remote daemon

**Актуально для:** Docker Engine 29.x, Docker CLI 29.x, Docker Compose v5.x. Полный механизм контекстов — в SSoT-файле [Docker Context](../../Docker/docker_context.md); здесь — применение к compose.

## Определения

**Docker Context** — именованный профиль подключения к Docker Engine (локальный сокет, `ssh://` или `tcp://` с mTLS). Compose-команды отправляются тому демону, который выбран активным контекстом.

**`DOCKER_CONTEXT`** — переменная окружения, выбирающая контекст по имени. Единственный способ адресовать контекст для `docker compose` через окружение без смены активного профиля; разовая команда без смены профиля возможна и через глобальный флаг docker CLI — `docker --context <NAME> compose ...` (см. «Базовые концепции»).

**`DOCKER_HOST`** — переменная окружения для прямого подключения к endpoint. **Перекрывает контексты**: при заданном `DOCKER_HOST` compose-команды идут по указанному адресу, игнорируя `docker context use`.

**Build context при удалённом деплое** — локальные файлы (Dockerfile, исходники) передаются на удалённый демон по сети при `docker compose build`; объём передачи растёт с размером контекста сборки.

## Базовые концепции

### У compose нет собственного флага `--context`

Глобальные опции `docker compose` (по официальному CLI-референсу): `--all-resources`, `--ansi`, `--compatibility`, `--dry-run`, `--env-file`, `-f/--file`, `--parallel`, `--profile`, `--progress`, `--project-directory`, `-p/--project-name` — **флага `--context` среди них нет**. Поэтому целевой демон для compose задаётся четырьмя способами:

1. **`docker context use <NAME>`** — переключает активный профиль; все последующие `docker compose`-команды адресуют удалённый демон. Команды развёртывания (`docker compose up`) остаются неизменными — меняется только цель.
2. **`docker --context <NAME> compose ...`** — разовая команда: глобальный флаг docker CLI ставится **до** имени плагина (`compose`), активный профиль не меняется. Аналогично `docker -H <endpoint> compose ...` — прямое подключение по адресу без контекста.
3. **`DOCKER_CONTEXT=<NAME>`** — выбор контекста по имени для одного окружения (удобно в CI).
4. **`DOCKER_HOST=<endpoint>`** — прямое подключение к адресу, контексты не используются.

**Приоритет разрешения endpoint** (от высшего к низшему, совпадает с SSoT): флаг `--context`/`-c` > флаг `--host`/`-H` > `DOCKER_HOST` > `DOCKER_CONTEXT` > `currentContext` из `~/.docker/config.json` > контекст `default`. Указать одновременно `--context` и `-H` нельзя — CLI отвечает ошибкой `conflicting options: cannot specify both --host and --context`.

**Следствие для диагностики:** если compose-команды ведут себя неожиданно, проверьте `env | grep -E '^DOCKER'` — заданный `DOCKER_HOST` молча перекрывает выбранный контекст.

### Как CLI работает поверх SSH

Контекст `ssh://` не создаёт туннель и не пробрасывает порты: CLI запускает на удалённом хосте `docker system dial-stdio` и передаёт поток HTTP API через SSH-канал. Это безопасный способ управления без открытия порта Docker-демона.

## Практические сценарии

### Сценарий 1: Деплой compose-стека на удалённый VPS через SSH

**Предварительные требования:** на удалённом хосте Docker Engine 18.09+, пользователь с доступом к сокету демона (группа `docker`).

```bash
# 1. Создать контекст
docker context create prod-vps --description "Production VPS" --docker "host=ssh://deploy@prod.example.com"
# → Successfully created context "prod-vps"

# 2. Переключиться
docker context use prod-vps
# → Current context is now "prod-vps"

# 3. Проверить, что CLI адресует удалённый демон
docker info | grep -E "Context|Server Version"
# → Context:    prod-vps
# → Server Version: 29.8.2

# 4. Деплой стека — команды compose не меняются
docker compose -f /opt/myapp/compose.yml up -d --wait

# 5. Compose-специфичная проверка: проекты на целевом демоне
docker compose ls
# → NAME        SERVICES
# → myapp       3
```

**Ожидаемый результат:** Стек развёрнут на удалённом хосте; `docker compose ps` показывает контейнеры VPS, `docker compose ls` — проект на удалённом демоне.

**Ограничение SSH-ключа:** ключ можно зажать на одну команду в `~/.ssh/authorized_keys` удалённого хоста:

```bash
command="docker system dial-stdio",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... docker-deploy
```

Так ключ бесполезен для интерактивной сессии — только канал к Docker API (который сам по себе эквивалентен root-доступу к хосту).

### Сценарий 2: CI/CD — явный выбор контекста

В CI состояние домашнего каталога раннера не контролируется — передавайте контекст явно:

```yaml
deploy:
  stage: deploy
  script:
    - export DOCKER_CONTEXT=prod-vps
    - docker context ls
    - docker compose -f compose.yml up -d --wait
```

**Ожидаемый результат:** Деплой идёт на целевой демон независимо от `currentContext` раннера.

**Альтернатива без переменных:** если раннер передаёт аргументы, но не окружение — `docker --context prod-vps compose -f compose.yml up -d --wait`: флаг `--context` относится к docker CLI и стоит до имени плагина, поэтому compose-команда адресует нужный демон без `export`.

**Изоляция окружений:** `DOCKER_CONFIG=/tmp/docker-cfg` перенаправляет весь каталог конфигурации клиента, включая контексты — полезно для тестирования без влияния на рабочие профили.

### Сценарий 3: Передача контекста между хостами

```bash
# Экспорт (содержит приватные ключи — права 0600)
docker context export prod-vps
# → Written file "prod-vps.dockercontext"

# Передача по защищённому каналу и импорт на целевом хосте
scp prod-vps.dockercontext admin@target:/tmp/
ssh admin@target 'docker context import prod-vps /tmp/prod-vps.dockercontext && shred -u /tmp/prod-vps.dockercontext'
```

**Ожидаемый результат:** Контекст перенесён без перегенерации сертификатов; архив удалён после импорта.

### Сценарий 4: Rootless демон как контекст

Установка rootless-демона автоматически создаёт и активирует контекст `rootless`:

```console
$ dockerd-rootless-setuptool.sh install
[INFO] Creating CLI context "rootless"
[INFO] Using CLI context "rootless"
```

```bash
docker context use rootless
docker compose up -d   # стек запускается в rootless-демоне
```

**Ожидаемый результат:** Compose-стек работает без root-привилегий. Для сторонних инструментов, читающих только `DOCKER_HOST`, документирован обходной путь: `export DOCKER_HOST=unix:///run/user/1000/docker.sock`.

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `docker context create <NAME> --docker "host=ssh://user@host"` | Контекст для удалённого хоста через SSH |
| `docker context use <NAME>` | Сделать контекст активным для всех команд |
| `docker context show` | Имя текущего активного контекста |
| `docker context ls` | Список контекстов (активный отмечен `*`) |
| `docker context inspect <NAME>` | Endpoint и TLS-материал в JSON |
| `docker context update <NAME> --docker "host=...,ca=...,cert=...,key=..."` | Ротация endpoint и сертификатов контекста |
| `docker context export/import` | Перенос контекста между хостами |
| `docker context rm -f <NAME>` | Удаление (включая скопированные сертификаты) |
| `docker compose ls` | Список compose-проектов на целевом демоне (проверка адресации) |

## Устранение неполадок

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Cannot connect to the Docker daemon at ssh://...` | Нет SSH-доступа или нет доступа к сокету на удалённом хосте | `ssh deploy@host true`; проверьте членство в группе `docker` на хосте |
| Команды идут не туда, хотя `docker context use` выполнен | Задан `DOCKER_HOST` — он перекрывает контекст | `env \| grep DOCKER`; `unset DOCKER_HOST` |
| `context "rootless" already exists` | Контекст создан установщиком rootless | Не создавайте повторно — `docker context use rootless` |
| `docker compose build` медленный на удалённом хосте | Build context передаётся по сети | Минимизируйте контекст через `.dockerignore`; собирайте локально и пушьте образ в registry |
| `x509: certificate signed by unknown authority` | mTLS-контекст с неверным CA | Сверьте `ca` в `docker context inspect` с сертификатом сервера |
| `conflicting options: cannot specify both --host and --context` | Указаны оба взаимоисключающих флага docker CLI | Оставьте один: `--context` (профиль) или `-H` (адрес) |
| `context "X" not found` при заданном `DOCKER_CONTEXT` | Переменная указывает на несуществующий контекст | `docker context ls`; создайте контекст или `unset DOCKER_CONTEXT` |
| `Permission denied (publickey)` при подключении по SSH | Ключ не авторизован на хосте или нет права на `docker system dial-stdio` | `ssh -v deploy@host`; проверьте `authorized_keys` и группу `docker` на хосте |
| После остановки Colima/Desktop команды падают | Контекст указывает на исчезнувший сокет | `docker context use default` |

## Рекомендации

1. **SSH вместо TCP/2376** — не открывайте порт Docker-демона в сеть; SSH использует существующую PKI.
2. **Явный контекст в CI** — не полагайтесь на `currentContext` раннера.
3. **Мультиплексирование SSH** (`ControlMaster auto` в `~/.ssh/config`) — убирает повторную аутентификацию из каждой compose-команды.
4. **Собирайте образы локально или в registry** — `docker compose build` на удалённом хосте передаёт весь build context по сети.
5. **Проверяйте `env | grep DOCKER`** при неочевидном поведении — `DOCKER_HOST` молчно побеждает контекст.
6. **Разовые команды через `docker --context <NAME> compose ...`** — не меняет активный профиль, безопасно в скриптах и на чужих раннерах.

## Дополнительная информация

- **[Docker Context](../../Docker/docker_context.md)** — SSoT: анатомия контекста, хранение на диске, приоритет переменных, ротация сертификатов.
- **[Docker Context в CI/CD для Swarm](../../Docker_swarm/CI_CD/docker_context_setup.md)** — mTLS-контексты в пайплайнах.
- **[Защита хоста и демона Docker](../Docker_security/host_daemon_hardening.md)** — безопасный удалённый доступ (SSH и mTLS).
- **[Миграция VPS без простоя](./vps_migration_zero_downtime.md)** — перенос стека между хостами.
- **[Справочник команд CLI](./docker_compose_cli_commands.md)** — compose-команды, адресующие удалённый демон.
