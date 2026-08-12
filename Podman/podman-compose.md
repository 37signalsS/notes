# Podman Compose

## Определения

**Podman Compose** — инструмент для запуска многоконтейнерных приложений и управления ими с помощью файлов конфигурации, аналогичных Docker Compose. Он позволяет описывать сервисы, сети и тома в одном файле (обычно `compose.yaml` или `docker-compose.yml`).

**Compose Spec** — открытая спецификация (`compose-spec.io`), описывающая формат файла Compose, общий для Docker Compose, Podman Compose и других реализаций. Podman Compose реализует именно эту спецификацию, что обеспечивает переносимость файлов между Docker и Podman.

В современной экосистеме выделяют следующие стандарты и инструменты:

- **Docker Compose (v2)** — основной и современный стандарт Docker, реализованный как плагин.
- **docker-compose** — устаревший (legacy) способ запуска через отдельную Python-утилиту.
- **Podman Compose** — официальный механизм в Podman для работы с Compose-спецификацией.
- **podman-compose** — независимая реализация Compose Spec (Python-утилита, проект контейнерной экосистемы `containers`), работающая на бэкенде Podman без зависимостей от Docker.

Существует два основных способа запуска Compose-файлов в Podman:

1. **Podman Compose (подкоманда `podman compose`)** — встроенный механизм (начиная с версии 4.1), который выступает тонким прокси-слоем (`thin wrapper`). Он находит установленный внешний провайдер Compose и проксирует команды через него на сокет Podman. По умолчанию провайдерами считаются `docker-compose` (занимает приоритет) и `podman-compose`.
2. **podman-compose (отдельная утилита)** — нативная реализация спецификации Compose для Podman, написанная на Python. Она напрямую исполняет команды `podman` и не требует ни демона, ни Docker-компонентов. Это "чистый" путь для Podman, избавленный от Docker-прокладок.

**Основные задачи:**
- Определение и запуск связанных сервисов из одного файла.
- Автоматическое создание сетей и томов.
- Поддержка синтаксиса и опций Docker Compose.
- Обеспечение безопасности через архитектуру без демона и rootless-режим.

## Основные концепции

### Различия подходов

| Характеристика | Podman Compose (подкоманда) | podman-compose (Python-утилита) |
| :--- | :--- | :--- |
| **Тип** | Встроенная прослойка (тонкий прокси) | Отдельный инструмент |
| **Зависимости** | Требует внешний провайдер (`docker-compose` или `podman-compose`) | Требует Python 3.9+ и пакет `podman-compose` |
| **Совместимость** | Максимальная (через Docker-провайдер) | Средняя/высокая (нативная реализация Spec) |
| **Архитектура** | Проксирует команды внешнему провайдеру | Нативно исполняет `podman` (без демона) |
| **Работа с подами** | Создает отдельные контейнеры | По умолчанию объединяет сервисы в общий **Pod** проекта |
| **Процесс-модель** | Команды идут через сокет/API | Прямой запуск процессов, как у обычного `podman` |

Провайдер, используемый подкомандой `podman compose`, настраивается:

- в `containers.conf` (секция `[engine]`, поле `compose_providers`), либо
- переменной окружения `PODMAN_COMPOSE_PROVIDER`.

По умолчанию `podman compose` предупреждает, что выполняет внешнюю команду; предупреждение отключается параметром `compose_warning_logs = false` в `containers.conf` или переменной `PODMAN_COMPOSE_WARNING_LOGS=false`. Полный список опций провайдера выводит `podman compose --help`.

Выбор зависит от целей: для максимальной совместимости с Docker-воркфлоу и установленным `docker-compose` — `podman compose`; для "чистого" Podman без Docker-прокладок и с нативной работой через поды — `podman-compose`.

### Поведение по умолчанию (поды)

`podman-compose` по умолчанию создает **один общий под на проект** с именем `pod_<имя_проекта>` (имя проекта по умолчанию — имя директории; переопределяется флагом `-p` или ключом `name:`). Все сервисы помещаются в этот под.

Под создается с аргументами по умолчанию `--infra=false --share=`:

- `--infra=false` — инфра-контейнер не создается;
- `--share=` — пространства имен не разделяются (каждый контейнер получает собственный network namespace).

Поведение пода переопределяется:

- глобальным флагом `--in-pod` (значения: `true` — под `pod_<проект>`, `false` — без пода, `<имя>` — свой под) и `--pod-args` (произвольные аргументы команды `podman pod`);
- расширением `x-podman.in_pod` и `x-podman.pod_args` в YAML-файле.

Из-за `--share=` взаимодействие между контейнерами внутри пода происходит не через `localhost`, а по именам сервисов через DNS сети (подробнее — в разделе «Сетевое взаимодействие»).

### Конфигурационные файлы

`podman-compose` ищет файлы по умолчанию в текущей директории и в родительских (рекурсивно, до глубины 10). Порядок поиска: `compose.yaml`, `compose.yml`, `compose.override.yaml`, `compose.override.yml`, `podman-compose.yaml`, `podman-compose.yml`, `docker-compose.yml`, `docker-compose.yaml`, `docker-compose.override.yml`, `docker-compose.override.yaml`, `container-compose.yml`, `container-compose.yaml`, `container-compose.override.yml`, `container-compose.override.yaml`.

Если не найден ни один файл — выводится ошибка `no compose.yaml, docker-compose.yml or container-compose.yml file found`.

Дополнительно:

- флаг `-f <файл>` задает конкретный файл (можно указывать несколько, например `-f base.yml -f override.yml`); `-f -` читает конфигурацию из стандартного ввода;
- флаг `--env-file <файл>` задает альтернативный файл переменных окружения (можно указывать несколько раз).

Ключ `version:` в файле считается устаревшим и необязательным по спецификации Compose Spec — вместо него используется верхнеуровневый ключ `name:` для имени проекта.

### Расширения x-podman

Для настройки специфики Podman `podman-compose` поддерживает расширения формата с префиксом `x-podman` (в корне файла и на уровне определения сетей). Основные ключи:

- `x-podman.in_pod` — значение пода (аналог флага `--in-pod`);
- `x-podman.pod_args` — аргументы `podman pod` (значение по умолчанию — `["--infra=false", "--share="]`);
- `x-podman.name_separator_compat: true` — использовать разделитель `-` (как в Docker Compose) вместо `_` для имен контейнеров, образов и т.д.;
- `x-podman.default_net_name_compat: true` — совместимые имена сетей проекта (Docker Compose убирает дефисы из имени проекта);
- `x-podman.default_net_behavior_compat: true` — выбирать сеть по умолчанию, как это делает Docker Compose (при нескольких объявленных сетях поведение по умолчанию отличается);
- `x-podman.routes` — маршруты для `podman network create` (задается на уровне сети);
- `x-podman.disable_dns` / `x-podman.dns` — отключение или переопределение DNS для сети.

Глобальный ключ `x-podman.docker_compose_compat: true` включает сразу все совместимости, перечисленные выше. Все настройки `x-podman` могут задаваться и переменными окружения с префиксом `PODMAN_COMPOSE_` (например, `PODMAN_COMPOSE_DOCKER_COMPOSE_COMPAT=true`).

### Зависимости процесса (daemonless)

`podman-compose` — одиночный Python-скрипт, который исполняет команды `podman` напрямую (без демона). Требования:

- `podman` (поддерживаются версии >= 3.4; для устаревших версий до 3.1 используется ветка 0.1.x с обходными решениями для rootless);
- Python 3.9+;
- библиотеки `PyYAML` и `python-dotenv`;
- плагин **podman-dnsname** (`podman-dnsname` / `podman-plugins` в дистрибутивах) — требуется для разрешения имен контейнеров в одной сети, если Podman работает на бэкенде CNI. При бэкенде **Netavark** (по умолчанию в современных версиях) плагин не обязателен.

В отличие от подхода с сокетом (`DOCKER_HOST=...` + `docker-compose`), `podman-compose` не передает большие контексты сборки демону: сборки и запуски выполняются локальными процессами.

## Практические сценарии

### 1. Установка

#### Пакетные менеджеры (Linux)
```bash
# Debian/Ubuntu
sudo apt install podman-compose

# Fedora 31+ и производные
sudo dnf install podman-compose

# RHEL/CentOS (старые ветки)
sudo yum install podman-compose
```

#### Homebrew (macOS)
```bash
brew install podman-compose
```

#### Универсальный способ (pip)
```bash
# Установка в домашний каталог пользователя (без root)
pip3 install --user podman-compose

# Установка актуального среза из исходного кода GitHub
pip3 install https://github.com/containers/podman-compose/archive/main.tar.gz

podman-compose --version
# → podman-compose version 1.6.0
```

#### Windows и macOS
- **Windows**: Рекомендуется **Podman Desktop**, который включает Podman Machine (ВМ для запуска контейнеров). После установки команды доступны в PowerShell или Windows Terminal.
- **macOS**:
  ```bash
  brew install podman
  podman machine init
  podman machine start
  brew install podman-compose   # либо: pip3 install --user podman-compose
  ```

#### Ручная установка
Проект оформлен как утилита в одном файле, поэтому достаточно скачать скрипт:
```bash
curl -o /usr/local/bin/podman-compose \
  https://raw.githubusercontent.com/containers/podman-compose/main/podman_compose.py
chmod +x /usr/local/bin/podman-compose
```

Либо клонировать репозиторий и установить через pip (вместо устаревшего `setup.py install`):
```bash
git clone https://github.com/containers/podman-compose.git
cd podman-compose
pip3 install .
```

Для работы с ранней веткой `0.1.x` (устаревший Podman < 3.1) используйте соответствующий релиз из репозитория.

### 2. Управление приложением

Podman Compose автоматически подтягивает конфигурационные файлы в текущей директории (перечень имен файлов приведен в разделе «Конфигурационные файлы» выше). Для явного указания используется `-f`.

При использовании Podman важно помнить про **полные имена образов (Fully Qualified Image Names)**: Podman разрешает короткие имена (`nginx`) через список реестров в `registries.conf` (`/etc/containers/registries.conf` или `~/.config/containers/registries.conf`, ключ `unqualified-search-registries`). В типовом конфиге дистрибутива среди них есть `docker.io`, но также реестры вендора — поэтому короткое имя может разрешиться в образ не с Docker Hub. Для предсказуемости указывайте полный путь: `docker.io/library/nginx`, `docker.io/library/postgres:16`.

**Пример `compose.yaml` (PostgreSQL + Nginx):**
```yaml
name: web-stack

services:
  db:
    image: docker.io/postgres:16
    environment:
      POSTGRES_PASSWORD: example
    volumes:
      - db_data:/var/lib/postgresql/data

  app:
    image: docker.io/nginx:alpine
    ports:
      - "8080:80"
    depends_on:
      - db

volumes:
  db_data: {}
```

**Основные команды:**
- `podman-compose config` — вывод финального YAML с подставленными значениями (проверка конфигурации без запуска).
- `podman-compose up -d` — запуск всех сервисов в фоновом режиме; `--build` — собрать перед запуском, `--force-recreate` / `--no-recreate` — управление пересозданием контейнеров, `--no-start` — только создать, `--wait` — дождаться готовности (с `--wait-timeout`).
- `podman-compose ps` — список запущенных сервисов и их статусы.
- `podman-compose logs -f` — просмотр логов всех сервисов в реальном времени; флаги `-n <число>` (хвост), `--no-color`.
- `podman-compose stop <service>` — остановка конкретного сервиса.
- `podman-compose start <service>` / `podman-compose restart <service>` — запуск и перезапуск.
- `podman-compose down` — полное удаление контейнеров, сетей и томов; `-v` — удалить также именованные тома; `--remove-orphans` — удалить лишние контейнеры проекта.
- `podman-compose build <service>` — сборка образов из `build`-секций; `podman-compose pull` / `push` — загрузка и выгрузка образов.
- `podman-compose images` — список используемых образов; `top` — процессы сервисов.
- `podman-compose exec <service> <cmd>` — выполнение команды в запущенном контейнере (например, `podman-compose exec app sh`).
- `podman-compose run <service> <cmd>` — разовый запуск одноразового контейнера сервиса (например, для миграций БД: `podman-compose run --rm db psql -U postgres -c '...'`).
- `podman-compose scale <service>=<n>` и `deploy.replicas` — масштабирование числа экземпляров сервиса.

**Жизненный цикл контейнеров:** контейнеры получают имена `<проект>_<сервис>_<индекс>` (по умолчанию разделитель `_`, как описано в разделе «Расширения x-podman»).

### 3. Переменные окружения (.env)

Файл `.env` позволяет отделить настройки и секреты от основного YAML-файла. Podman Compose автоматически считывает `.env` в той же директории (через библиотеку python-dotenv).

**Пример `.env`:**
```text
WEB_PORT=8080
DB_USER=admin
POSTGRES_PASSWORD=supersecret
```

**Использование в `docker-compose.yml`:**
```yaml
services:
  web:
    image: docker.io/nginx:alpine
    ports:
      - "${WEB_PORT:-80}:80"
  db:
    image: docker.io/postgres:16
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
```

*Совет: Чтобы проверить финальный YAML с подставленными значениями, выполните `podman-compose config`.*

Особенности интерполяции:

- Поддерживаются операторы Bash-подобной подстановки: `${VAR}`, `${VAR:-default}`, `${VAR-default}`, `${VAR:?err}`, `${VAR?err}`, альтернативы `${VAR:+alt}` / `${VAR+alt}`, экранирование `$$`.
- Поддерживается вложенная интерполяция и подстановка переменных в ключах YAML (не только в значениях).
- `podman-compose` читает переменные из окружения процесса, файла `.env` и флага `--env-file`. Для короткой записи в секции `environment:` можно указывать только имя переменной без значения — она подставится из окружения.

### 4. Управление сетями

Podman Compose автоматически создает изолированную сеть проекта (именованную `<проект>_default`), но можно управлять сетями вручную:

- `podman network create <name>` — создание новой сети.
- `podman network ls` — список всех сетей Podman.

Сети на уровне Compose объявляются в верхнеуровневой секции `networks`:

```yaml
networks:
  backend:
    driver: bridge
    internal: true          # изолированная сеть без внешнего доступа
    ipam:
      config:
        - subnet: 172.28.0.0/16
    x-podman.routes:        # расширение: маршруты для podman network create
      - "192.168.0.0/16 via 172.28.0.1"
  frontend:
    external: true          # ссылка на существующую сеть Podman
    name: proxy-net
```

Ключевые варианты:

- `external: true` (+ при необходимости `name:`) — подключение к уже существующей сети; если такая сеть не создана, возникнет ошибка с подсказкой выполнить `podman network create`.
- `driver`, `driver_opts`, `ipam.config` (`subnet`, `ip_range`, `gateway`) и `ipam.driver` передаются в `podman network create --subnet ... --gateway ...`.
- `internal: true` — сеть без доступа во внешний мир.
- Расширения `x-podman.disable_dns`, `x-podman.dns`, `x-podman.routes` управляют параметрами DNS и маршрутов сети.

Подключение сервиса к нескольким сетям выполняется через `networks:` с алиасами (`alias:`) и статическими адресами (`ipv4_address:`, `ipv6_address:`, `mac_address:`). При подключении в сеть каждому сервису автоматически присваивается алиас с его именем.

В rootless-режиме сетевые стеки настраиваются через **pasta** (по умолчанию с Podman 5.0) или **slirp4netns** (устаревший вариант, удален в Podman 6.0). Подробнее об изменении сетевого стека — в **[Подах в Podman](./podman_pods.md)**.

### 5. Особенности сетевого взаимодействия (Networking)

В `podman-compose` контейнеры по умолчанию объединяются в один **Pod** проекта (`pod_<проект>`, подробнее — раздел «Поведение по умолчанию»). Однако под создается с `--share=` (без общего network namespace), поэтому:

- **Обращение по именам сервисов**: Контейнеры видят друг друга по именам, описанным в `compose.yaml` (например, `curl db:5432`). Это рекомендуемый способ. Поддержка DNS реализована через алиасы сервисов в сети проекта (backend Netavark/Aardvark либо плагин podman-dnsname для CNI).
- **Проблема localhost**: Из-за отсутствия общего network namespace контейнеры не видят друг друга через `127.0.0.1` (localhost), даже находясь в одном поде. Сетевая модель остается близкой к Docker: каждый контейнер имеет собственную сеть, а связь идет по именам через DNS.
- **Различие с нативным Podman**: Если создать под вручную (`podman pod create`) без `--share=`, Podman создает `infra`-контейнер с единым network namespace, где `localhost` работает для всех контейнеров. `podman-compose` по умолчанию отключает общий namespace ради совместимости со спецификацией Docker Compose.

**Как включить общий localhost (нативный pod):** передайте под-флаги `--infra` и `--share=net` через `--pod-args` или `x-podman.pod_args`, например:

```bash
# Глобальные флаги указываются до подкоманды
podman-compose --pod-args "--infra --share=net" up -d
```

```yaml
name: app
x-podman:
  pod_args: ["--infra", "--share=net"]
```

**Рекомендация:** Всегда используйте имена сервисов (`db`, `redis`, `app`) вместо `localhost` для межсервисного взаимодействия — это обеспечивает переносимость файла между Docker и Podman.

**network_mode:** поддерживаются `host`, `none`, `service:<имя>` и `container:<имя>` (разделение сети с другим сервисом/контейнером), а также Podman-специфичные режимы `bridge`, `pasta`, `slirp4netns`, `private`, `ns:<путь>`. Одно `network_mode` и секция `networks` не могут использоваться в одном сервисе одновременно.

### 6. Мониторинг и отладка

Для анализа работы сервисов используйте как команды `podman-compose`, так и нативные команды Podman:

- `podman-compose ps` — статусы сервисов проекта.
- `podman-compose top` — процессы внутри сервисов.
- `podman-compose events` — поток событий проекта (запуск/остановка контейнеров).
- `podman-compose logs -f <service>` — логи конкретного сервиса.
- `podman pod ps` — просмотр созданного пода проекта (`pod_<проект>`).
- `podman ps --pod` — список контейнеров с привязкой к их подам и именем проекта.
- `podman exec -it <container_name> sh` — вход в контейнер для отладки (например, проверки связи через `curl db:5432`). Имя контейнера — `<проект>_<сервис>_<индекс>`.

### 7. Ресурсы и лимиты

Лимиты ресурсов задаются как через устаревшие ключи, так и через `deploy`:

```yaml
services:
  app:
    image: docker.io/nginx:alpine
    cpus: 0.5
    mem_limit: 512m
    pids_limit: 100
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
          pids: 256
        reservations:
          memory: 64M
  gpu:
    image: docker.io/pytorch/pytorch:latest
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              capabilities: [gpu]
              count: all
```

- `cpus`, `cpu_shares`, `mem_limit`, `mem_reservation` (старый синтаксис) и `deploy.resources.limits` / `deploy.resources.reservations` (современный) транслируются в флаги `podman` (`--cpus`, `--cpu-shares`, `-m`, `--memory-reservation`, `--pids-limit`).
- Если `pids_limit` и `deploy.resources.limits.pids` заданы одновременно и различаются — возникнет ошибка.
- GPU-устройства через `deploy.resources.reservations.devices` транслируются в `--device nvidia.com/gpu=...` (CDI-совместимость).

### 8. Секреты

Секреты объявляются в верхнеуровневой секции `secrets` и передаются контейнерам через файл или переменную окружения:

```yaml
secrets:
  db_password:
    environment: DB_PASSWORD        # значение берется из переменной окружения процесса
  api_token:
    file: ./secrets/api_token.txt   # или из файла

services:
  app:
    image: docker.io/nginx:alpine
    secrets:
      - db_password
      - source: api_token
        target: api_token
```

- Секреты из файлов монтируются в контейнер как тома, по умолчанию в `/run/secrets/<имя>` (режим `ro,rprivate,rbind`); ключ `target` задает имя файла внутри контейнера.
- Секреты из переменной окружения создаются через `podman secret create --env ...` и монтируются как `--secret`.
- Для внешних секретов (`external: true` или ключ `name:`) поддерживается монтирование существующего `podman secret` по имени с опциями `uid`, `gid`, `mode`, `type`, `target`.
- **Ограничение:** `uid`, `gid` и `mode` для секретов, смонтированных из файла, не поддерживаются — `podman-compose` выводит предупреждение и игнорирует их (полные права поддерживаются только для внешних `podman secret`).

### 9. Интеграция с systemd

`podman-compose` умеет регистрировать проект как пользовательский systemd-юнит:

```bash
# Один раз создать unit-шаблон podman-compose@.service (от root)
sudo podman-compose systemd -a create-unit

# В директории проекта — зарегистрировать по нему текущий стек
podman-compose systemd -a register

# Управление стеком через systemd (без sudo, --user)
systemctl --user enable --now 'podman-compose@<проект>'
systemctl --user status 'podman-compose@<проект>'
systemctl --user stop 'podman-compose@<проект>'

# Удалить регистрацию
podman-compose systemd -a unregister
```

Вместо systemd-обертки от `podman-compose` для продакшена обычно выбирают **Quadlet** (см. раздел «Альтернатива: Quadlet»).

### 10. Профили (Profiles)

Сервисы можно группировать в профили, включаемые по требованию:

```yaml
services:
  app:
    image: docker.io/nginx:alpine
  debug-tools:
    image: docker.io/nicolaka/netshoot:latest
    profiles: ["debug"]
```

```bash
# Запуск с активным профилем
podman-compose --profile debug up -d

# Либо через переменную окружения
COMPOSE_PROFILES=debug podman-compose up -d
```

Сервисы без `profiles:` запускаются всегда; сервисы с профилями — только когда соответствующий профиль активирован.

## Миграция из Docker Compose

1. **Проверка манифеста**: Большинство файлов версии 3.x и файлов Compose Spec работают "как есть". Уберите устаревший ключ `version:` (см. раздел «Конфигурационные файлы»).
2. **Явные реестры**: Проверьте, что во всех `image` указаны полные пути (`docker.io/...`), иначе короткое имя может разрешиться в образ не с Docker Hub.
3. **Права на тома**: В rootless-режиме может потребоваться настройка прав доступа к папкам на хосте (см. `podman unshare chown`).
4. **Сетевые нюансы**: Используйте имена сервисов вместо `localhost` (§5). Учитывайте, что по умолчанию используется разделитель `_` в именах, а не `-`, как в Docker Compose.
5. **Запуск**: Замените вызов `docker-compose` на `podman-compose` (или настройте `podman compose`).

При расхождении поведения с Docker Compose (имена контейнеров, сети, выбор сети по умолчанию) включите совместимые режимы из раздела «Расширения x-podman» (`docker_compose_compat`).

### Использование Docker Compose v2 как провайдера
Для максимальной совместимости с оригинальным Docker Compose можно использовать подкоманду `podman compose`:
1. Включите сокет Podman: `systemctl --user enable --now podman.socket`.
2. Настройте переменную: `export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"`.
3. Установите плагин `docker-compose` v2 (должен быть доступен как `docker-compose` в PATH).
4. Запускайте через `podman compose up` (без дефиса). Podman проксирует команды в провайдер.

Если `docker-compose` не установлен, `podman compose` автоматически использует `podman-compose`. Явно указать провайдера можно в `containers.conf` (`compose_providers` в секции `[engine]`) или переменной `PODMAN_COMPOSE_PROVIDER`. Предупреждение о внешней команде отключается через `compose_warning_logs = false` / `PODMAN_COMPOSE_WARNING_LOGS=false`.

## Дополнительная информация

### Генерация Kubernetes-манифестов
Podman позволяет экспортировать запущенный под (включая созданный через compose) в YAML для Kubernetes:

```bash
# Узнать ID созданного пода
podman pod ps

# Сгенерировать YAML (Podman 4.3+)
podman kube generate <POD_ID> > deployment.yaml

# Устаревший синтаксис (deprecated)
podman generate kube <POD_ID>
```

Это отличное решение для быстрой миграции из локальной разработки в кластер, хотя полученный YAML обычно требует доработки (например, добавления Deployment или Service).

### Альтернатива: Quadlet

Для продакшн-сред на Linux рекомендуется переходить с Compose на **Quadlet**. Это нативный способ описания контейнеров Podman в виде юнитов systemd.

**Преимущества Quadlet:**
- Декларативность и интеграция с `systemctl`.
- Автоматический перезапуск при сбоях или после перезагрузки хоста.
- Отсутствие зависимости от Python или сторонних утилит типа `podman-compose`.
- Гибкость настройки через юниты.

Подробнее: **[Миграция с Docker (Compose → Quadlet)](./migration-from-docker.md)**.

### См. также
- **[Поды в Podman](./podman_pods.md)** — концепция групп контейнеров и сетевая модель пода.
- **[Миграция с Docker (Compose → Quadlet)](./migration-from-docker.md)** — переход на Quadlet и различия в сетевом стеке.
- **[Управление зависимостями и готовностью](./podman-dependencies.md)** — особенности `depends_on` и `condition: service_healthy` в Compose-эквивалентах Podman.
- **[Rootless режим](./podman_rootless.md)** — особенности запуска без root.