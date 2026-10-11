# Алиасы и конфигурация в контейнерах: оболочка и сетевые алиасы (/etc/hosts)

**Актуально для:** Docker Engine 20.10+ (специальное значение `host-gateway`); Docker Desktop 4.33+ (`docker debug`); Compose v2 (`extra_hosts`)

## Определения

**Алиасы оболочки (Shell Aliases)** — короткие псевдонимы для длинных команд (например, `alias ll='ls -la'`), определяемые в файлах конфигурации оболочки (`.bashrc`, `.zshrc`).

**Инъекция алиасов (Alias Injection)** — процесс проброса или воссоздания привычного рабочего окружения хоста внутри изолированного Docker-контейнера.

**Сетевые алиасы хоста (Host Aliases / `--add-host`)** — сопоставление доменных имён и IP-адресов в файле `/etc/hosts` контейнера. **Не путать с алиасами командной оболочки.**

**`host-gateway`** — специальное значение в `--add-host` / `extra_hosts` (Docker Engine 20.10+, moby/moby#40007): разворачивается в IP-шлюз сети, к которой подключён контейнер (для bridge по умолчанию — `172.17.0.1`, для пользовательской сети — её шлюз, например `172.18.0.1`). Позволяет обращаться к хосту по имени `host.docker.internal` на Linux так же, как на Docker Desktop.

**Проблема наследования:** Docker-контейнеры по умолчанию обеспечивают чистую среду. Они не считывают файлы конфигурации пользователя с хоста, что приводит к отсутствию привычных сокращений и функций при выполнении `docker exec`.

## Основные концепции

### Жизненный цикл оболочки и файлы инициализации

Чтобы алиасы работали, оболочка должна их считать при запуске. Тип запуска определяет, какие файлы будут обработаны:

| Тип сессии | Bash | Zsh | Примеры |
| :--- | :--- | :--- | :--- |
| **Login Shell** | `/etc/profile` → первый найденный из `~/.bash_profile`, `~/.bash_login`, `~/.profile` | `.zprofile`, `.zlogin` | `su -`, `ssh`, `docker exec -it <c> bash -l` |
| **Interactive Shell** | `/etc/bash.bashrc` (Debian), `~/.bashrc` | `~/.zshrc` | Обычный `docker exec -it <c> bash` |
| **Non-interactive** | `$BASH_ENV` (файл считывается целиком) | `.zshenv` (всегда, для любого вызова zsh) | Скрипты, `docker exec <c> bash -c '...'` |

**Важно:** у `docker exec` **нет** флага `--login` (верифицировано по документации CLI: флаги ограничены `-d`, `--detach-keys`, `-e`, `--env-file`, `-i`, `--privileged`, `-t`, `-u`, `-w`). Login-оболочку запускает сама оболочка: `docker exec -it <c> bash -l`.

### Как Docker управляет `/etc/hosts`

- Docker создаёт `/etc/hosts` при **создании** контейнера: `localhost`, имя хоста контейнера (`--hostname` / `--name`) и записи `--add-host`.
- Файл принадлежит root и доступен только для чтения изнутри контейнера — изменить его в работающем контейнере нельзя; изменение записей требует пересоздания контейнера.
- Bind-mount собственного `/etc/hosts` поверх системного — недокументированный трюк, на который не стоит полагаться (moby/moby#10316); директива `VOLUME /etc` в Dockerfile конфликтует со служебными маунтами (moby/moby#10604).
- В пользовательских сетях разрешение имён контейнеров выполняет встроенный DNS Docker (`127.0.0.11`), а не `/etc/hosts` — в файле нет списка соседних контейнеров.

### Порядок разрешения имён

Приложения разрешают имена через `getaddrinfo` / `nsswitch.conf`: сначала `files` (`/etc/hosts`), затем `dns`. Поэтому запись из `--add-host` имеет приоритет над DNS. `nslookup` и `dig` обращаются к DNS напрямую и **обходят** `/etc/hosts` — расхождение результатов `getent hosts` и `dig` — диагностический сигнал (подробнее: **[Диагностика DNS](../Docker_network/troubleshooting/dns_resolution_issues.md)**).

### Стратегии

1.  **Декларативный (Nix/Home Manager):** Описание алиасов в `home.nix`, которые автоматически применяются ко всем средам, включая контейнеризированные.
2.  **Git-ориентированный (Dotfiles):** Использование централизованного репозитория с конфигурацией, который клонируется в контейнер (стандарт для Dev Containers).
3.  **Модульный (Separate Aliases):** Хранение алиасов в отдельном файле (например, `.bash_aliases`), который монтируется в контейнер, не раскрывая весь `.bashrc` хоста.

## Требования

- Docker Engine 20.10+ для `host-gateway`; для `docker debug` — Docker Desktop 4.33+ (в standalone Engine команда недоступна, docker/roadmap#893).
- Для монтирования алиасов: Bash в образе (slim-образы на базе Debian/Ubuntu содержат bash; Alpine — нет, там `ash`).
- Для Dev Containers — VS Code с расширением Dev Containers (или JetBrains IDE с поддержкой `devcontainer.json`).

## Практические сценарии

### Сценарий 1: Монтирование через Docker Compose (Рекомендуемый для команд)

Использование выделенного файла алиасов позволяет избежать утечки секретов из основного `.bashrc`.

```yaml
services:
  app:
    image: node:22-slim
    volumes:
      - ./.docker_aliases:/home/node/.bash_aliases:ro
    environment:
      # Для автоматического подтягивания в неинтерактивном Bash
      - BASH_ENV=/home/node/.bash_aliases
```

**Dockerfile (подготовка):**
```dockerfile
# Гарантируем, что Bash будет считывать .bash_aliases в интерактивных сессиях
RUN echo "if [ -f ~/.bash_aliases ]; then . ~/.bash_aliases; fi" >> /home/node/.bashrc
```

**Ограничения:** `BASH_ENV` влияет только на неинтерактивный bash и требует **абсолютного** пути; для интерактивных сессий (`docker compose exec app bash`) sourcing обеспечивает правка `.bashrc` из Dockerfile.

### Сценарий 2: Использование функций вместо алиасов

Для команд, принимающих аргументы (например, `docker exec`), рекомендуется использовать функции — алиасы аргументов не принимают.

```bash
# В вашем .bash_aliases
dexec() { docker exec -it "$1" /bin/bash; }
# Применение: dexec my-container
```

### Сценарий 3: Dev Containers и Dotfiles (VS Code / JetBrains)

Современный стандарт разработки. В `devcontainer.json` указывается ссылка на репозиторий с настройками.

```json
{
  "name": "Production Environment",
  "dotfiles": {
    "repository": "https://github.com/user/dotfiles.git",
    "targetPath": "~",
    "installCommand": "install.sh"
  }
}
```

### Сценарий 4: Кастомный образ (System-wide Aliases)

Если нужно обеспечить одинаковые инструменты для всей команды без внешних зависимостей.

```dockerfile
FROM ubuntu:24.04

# Добавление алиасов для всех пользователей системы
RUN echo 'alias ll="ls -la"' >> /etc/bash.bashrc && \
    echo 'alias k="kubectl"' >> /etc/bash.bashrc
```

### Сценарий 5: Сетевые алиасы хоста (--add-host)

Если контейнеру нужно обращаться к хосту или внешнему сервису по фиксированному имени, не используя DNS. Флаг можно указывать многократно, поддерживаются IPv6-адреса.

```bash
# Одна запись
docker run -it --add-host="api.local:192.168.1.10" alpine ping api.local

# Несколько записей + IPv6 + имя хоста контейнера
docker run -it \
  --add-host="api.local:192.168.1.10" \
  --add-host="db.local:fd00::1" \
  --hostname=web01 \
  alpine sh
# → в /etc/hosts контейнера появятся:
# → 192.168.1.10  api.local
# → fd00::1       db.local
# → <container-ip> web01
```

### Сценарий 6: Доступ к хосту — `host.docker.internal` и `host-gateway`

Контейнеру часто нужен доступ к сервису на самом хосте (локальный registry, отладочный сервер, БД на хосте).

- **Docker Desktop (macOS/Windows):** `host.docker.internal` доступно автоматически через внутренний DNS Desktop.
- **Linux (Engine 20.10+):** opt-in через специальное значение `host-gateway`:

```bash
docker run --rm --add-host=host.docker.internal:host-gateway alpine \
  getent hosts host.docker.internal
# → 172.17.0.1  host.docker.internal   (IP шлюза bridge-сети по умолчанию)
```

- IP разворачивается в шлюз **подключённой сети** (для пользовательской сети — её шлюз, например `172.18.0.1`), поэтому способ переносим между сетями.
- Переопределение IP для демона: `dockerd --host-gateway-ip=<ip>` (по умолчанию — IP bridge по умолчанию).
- На Engine < 20.10 `host-gateway` не работает — нужен явный IP шлюза сети.

### Сценарий 7: Docker Compose — `extra_hosts`

Аналог `--add-host` в Compose (Compose v2):

```yaml
services:
  app:
    image: node:22-slim
    extra_hosts:
      - "api.local:192.168.1.10"
      - "host.docker.internal:host-gateway"
```

Проверка результирующей конфигурации: `docker compose config | grep -A3 extra_hosts`. При использовании `extends` массивы `extra_hosts` объединяются без дедупликации (подробнее: **[extends и include](../Docker_compose/docker_compose_extends_include.md)**).

### Сценарий 8: Kubernetes — `hostAliases`

В Pod аналогичный механизм — поле `spec.hostAliases` (без ConfigMap и сторонних DNS):

```yaml
spec:
  hostAliases:
    - ip: "192.168.1.10"
      hostnames:
        - "api.local"
```

Подробнее: **[Продвинутые темы Pod](../../Kubernetes/Base/Pod/pod_advanced_topics.md)**. Учтите: политики Kyverno могут запрещать `hostAliases` как механизм обхода DNS (изоляция DNS).

## Операции и команды

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `docker run --add-host <host>:<ip>` | Запись в `/etc/hosts` при создании контейнера | `docker run --add-host=api.local:192.168.1.10 alpine ...` |
| `docker run -h, --hostname <name>` | Имя хоста контейнера (попадает в `/etc/hosts`) | `docker run -h web01 nginx` |
| `docker run --domainname <domain>` | NIS-домен контейнера | `docker run --domainname=corp.local nginx` |
| `docker inspect -f '{{json .HostConfig.ExtraHosts}}' <c>` | Проверить добавленные записи | `["api.local:192.168.1.10"]` |
| `docker exec <c> cat /etc/hosts` | Содержимое файла внутри контейнера | — |
| `docker exec <c> getent hosts <name>` | Разрешение тем же путём, что и приложение | `getent hosts api.local` |
| `docker compose config` | Проверка `extra_hosts` в Compose | `docker compose config \| grep extra_hosts` |

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Имя из `--add-host` не резолвится | Запись добавлена при создании другого контейнера или после старта | `--add-host` — опция создания; пересоздать контейнер; проверить `docker inspect ... .HostConfig.ExtraHosts` |
| `conflicting options` при `docker run` | `--add-host` вместе с `--network host` или `--network container:<id>` | Убрать `--add-host`: в этих режимах флаги `--dns*`, `--add-host`, `--hostname` не поддерживаются (подробнее: **[Диагностика DNS](../Docker_network/troubleshooting/dns_resolution_issues.md)**) |
| `host.docker.internal` не резолвится на Linux | Engine < 20.10 или не указано `host-gateway` | Обновить Engine; `--add-host=host.docker.internal:host-gateway` |
| Bind-mount `/etc/hosts` не меняет файл | Docker управляет файлом самостоятельно | Использовать `--add-host` |
| Алиас не работает в `docker exec` | Неинтерактивная оболочка не читает `~/.bashrc` | `BASH_ENV`, функции или интерактивный `docker exec -it` |
| `BASH_ENV` не срабатывает | Относительный путь | Только абсолютный путь в `BASH_ENV` |
| Алиас `bat`/`exa` не найден | Утилиты отсутствуют в образе | Установить в образ или использовать `docker debug` |
| `dig` не видит имя, приложение видит | Ответ даёт `/etc/hosts`, а не DNS | Ожидаемое поведение; проверять через `getent hosts` |

## Валидация

```bash
# 1. Запись попала в /etc/hosts
docker run --rm --add-host="api.local:192.168.1.10" alpine cat /etc/hosts
# → 192.168.1.10  api.local

# 2. Разрешение тем же путём, что и приложение
docker run --rm --add-host="api.local:192.168.1.10" alpine getent hosts api.local
# → 192.168.1.10  api.local

# 3. host-gateway разворачивается в IP шлюза сети
docker run --rm --add-host=host.docker.internal:host-gateway alpine getent hosts host.docker.internal
# → 172.17.0.1  host.docker.internal

# 4. Конфигурация Compose
docker compose config | grep -A3 extra_hosts
# → extra_hosts:
# →   - "api.local:192.168.1.10"

# 5. Алиасы доступны в сессии контейнера
docker compose exec app bash -c 'source ~/.bash_aliases && alias ll'
# → alias ll='ls -la'
```

## Лучшие практики

1. **Изолированный `.bash_aliases`** вместо монтирования всего `~/.bashrc` — не раскрывайте секреты из основного файла.
2. **Функции вместо алиасов** для команд с аргументами.
3. **`host-gateway` вместо хардкода IP** хоста — переносимо между сетями и хостами.
4. **Не монтируйте `/etc/hosts` напрямую** — Docker управляет файлом; используйте `--add-host`.
5. **`--add-host` — опция создания контейнера**; изменения требуют пересоздания, а не `docker exec`.
6. **Проверяйте разрешение через `getent hosts`** — тот же путь (`getaddrinfo`/`nsswitch.conf`), что и приложение.
7. **Постоянные алиасы команды — в образ** (Dockerfile); разовые — через `docker debug`.

## Дополнительная информация

### Сравнение подходов

| Метод | Переносимость | Безопасность | Сложность |
| :--- | :--- | :--- | :--- |
| **Bind Mount** | Низкая | Низкая (риск утечки `.bashrc`) | Низкая |
| **Dockerfile** | Высокая | Высокая | Средняя |
| **Dev Containers** | Высокая | Средняя | Средняя |
| **Nix Flakes** | Максимальная | Высокая | Высокая |

### Предупреждения по безопасности

1.  **Утечка секретов:** Никогда не монтируйте основной `~/.bashrc`, если в нем содержатся `export AWS_SECRET_ACCESS_KEY` или другие токены. Используйте изолированный `.bash_aliases`.
2.  **Зависимости инструментов:** Алиас для `bat` или `exa` не будет работать, если эти утилиты не установлены в образе. Используйте статические бинарники или Nix для решения этой проблемы.
3.  **Абсолютные пути:** Алиасы, ссылающиеся на пути хоста (например, `/home/user/scripts/`), внутри контейнера будут сломаны.
4.  **`/etc/hosts` доступен только для чтения** изнутри контейнера (владелец root) — запись возможна только через `--add-host` при создании.

### Альтернатива для «пустых» образов: Docker Debug

Для отладки «пустых» или сложных контейнеров (distroless, scratch, slim без shell) рекомендуется использовать **`docker debug`** (Docker Desktop 4.33+). Команда подключает эфемерный отладочный контейнер с Toolbox (на базе Nix), предоставляя полноценную оболочку и набор инструментов без модификации оригинального образа или проброса файлов конфигурации. В standalone Docker Engine команда недоступна (docker/roadmap#893).

Подробнее: **[Docker Debug](./docker_debug.md)**.

### См. также

- **[Переменные оболочки](../../Linux/Shell/shell_variables.md)** — разница между локальными и экспортируемыми переменными.
- **[Лучшие практики Dockerfile](../Dockerfile/Docker_best_practices/build_optimization.md)** — оптимизация слоев при настройке окружения.
- **[Отладка Distroless образов](./debugging_distroless.md)** — методы работы в средах без оболочки.
- **[Диагностика DNS](../Docker_network/troubleshooting/dns_resolution_issues.md)** — глубокая диагностика разрешения имён, включая `getent` vs `dig`.
- **[Директивы Compose](../Docker_compose/docker_compose_directives.md)** — описание `extra_hosts` и других опций сервиса.
- **[Команды Docker](../docker_commands.md)** — справочник флагов `docker run`, включая `--add-host`.
