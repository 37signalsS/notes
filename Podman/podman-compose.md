> Актуально для: Podman 6.x (проверено на 6.0.2, июль 2026), podman-compose 1.6.0+

## Определения

**Podman Compose** — инструмент для запуска многоконтейнерных приложений и управления ими с помощью файлов конфигурации, аналогичных Docker Compose. Он позволяет описывать сервисы, сети и тома в одном файле (обычно `compose.yaml` или `docker-compose.yml`).

**Compose Spec** — открытая спецификация (`compose-spec.io`), описывающая формат файла Compose, общий для Docker Compose, Podman Compose и других реализаций. Podman Compose реализует именно эту спецификацию, что обеспечивает переносимость файлов между Docker и Podman.

**FQIN (Fully Qualified Image Name)** — полное имя образа, включающее регистр, репозиторий и тег (например, `docker.io/library/nginx:alpine`). В Podman короткие имена (`nginx`) резолвятся через `registries.conf`, что может приводить к неожиданным источникам образов; для воспроизводимости рекомендуется использовать FQIN.

**registries.conf** — конфигурационный файл Podman (`/etc/containers/registries.conf` или `~/.config/containers/registries.conf`), управляющий неавторизованным поиском образов через ключ `unqualified-search-registries`.

**Netavark + Aardvark-dns** — сетевой стек Podman (по умолчанию с версии 4.x, единственный поддерживаемый в 6.x). Netavark отвечает за настройку интерфейсов и бриджей, Aardvark-dns — за DNS-резолвинг имен контейнеров внутри пользовательских сетей.

**Pasta** — сетевой бэкенд rootless-режима (по умолчанию с Podman 5.0, полностью заменил `slirp4netns` в 6.x). Обеспечивает NAT и проброс портов без прав root.

**conmon** — легковесный монитор жизненного цикла контейнера (один экземпляр на контейнер), который удерживает STDIN/STDOUT/STDERR и фиксирует код завершения процесса. Детали архитектуры см. в **[Daemonless архитектура](./podman_daemonless_architecture.md)**.

**SQLite-бэкенд** — хранилище метаданных Podman (стандарт с 4.9, единственный бэкенд в 6.x). В отличие от Docker, где состояние ведется в памяти демона, Podman хранит метаданные в локальной SQLite-базе.

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

### Архитектура podman-compose

`podman-compose` — это Python-скрипт, который выступает тонким слоем абстракции над нативным CLI Podman. В отличие от Docker Compose v2 (который общается с демоном через сокет), `podman-compose` запускает дочерние процессы `podman` напрямую:

```bash
# Внутренняя цепочка при podman-compose up -d
podman-compose (Python)
  → podman pod create ...
  → podman run ... (для каждого сервиса)
    → conmon (один на контейнер)
      → crun/runc (OCI runtime)
        → процесс приложения
```

Поскольку нет центрального демона, весь жизненный цикл проекта делегируется CLI-процессам и (в продакшене) systemd. Детали модели без демона см. в **[Daemonless архитектура](./podman_daemonless_architecture.md)**.

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

### 11. Валидация и проверка конфигурации

Перед запуском в продакшене проверьте финальный YAML и состояние окружения:

```bash
# Вывод полностью раскрытого конфига с подставленными переменными
podman-compose config
# → services:
# →   db:
# →     image: docker.io/postgres:16
# →     environment:
# →       POSTGRES_PASSWORD: supersecret

# Проверка синтаксиса без запуска (сборка и запуск не выполняются)
podman-compose config --validate
# → Validated successfully

# Dry-run: вывод команд podman, которые будут выполнены
podman-compose up --dry-run
# → podman pod create --name pod_web ...
# → podman run --name web_db ... docker.io/postgres:16
```

**Проверка окружения:**

```bash
# Проверка версий
podman --version
# → podman version 6.0.2
podman-compose --version
# → podman-compose version 1.6.0

# Проверка базы данных и хранилища
podman info --format '{{.Host.DatabaseBackend}}'
# → sqlite
podman info --format '{{.Store.GraphDriverName}}'
# → overlay
```

### 12. Типичные проблемы и диагностика

#### Проблема: `permission denied` при монтировании тома (rootless)

**Причина:** В rootless-режиме Podman не может монтировать директории, принадлежащие root, без явного изменения прав. Ошибка обычно выглядит как `mount: /host/path: permission denied.`

**Решение:**

```bash
# Временное исправление прав на директорию тома
podman unshare chown 1000:1000 /path/to/host/volume

# Или запуск podman-compose через podman unshare (временный rootless namespace)
podman unshare podman-compose up -d
```

#### Проблема: DNS не резолвит имена сервисов

**Причина:** В Podman 6.x CNI полностью удален; DNS работает через Netavark/Aardvark. Если контейнеры не видят друг друга по именам, проверьте:

```bash
# Список сетей проекта
podman network ls --filter label=project=web-stack

# Проверка DNS внутри контейнера
podman exec web_app nslookup db
# → Non-existent domain
```

**Решение:** Убедитесь, что сервисы подключены к одной сети и не используется `network_mode: host` для обоих. Для внешних сетей укажите `external: true` + `name:`.

#### Проблема: Порт хоста занят (`port is already allocated`)

**Причина:** Другой процесс (или другой стек Podman/Docker) слушает тот же порт.

```bash
# Поиск процесса по порту
sudo ss -tlnp | grep ':8080'
# → LISTEN 0 128  *:8080  *:*  users:(("nginx",pid=1234,fd=6))

# Проверка, какой контейнер Podman занял порт
podman ps --filter publish=8080
```

**Решение:** Освободите порт или измените маппинг в `compose.yaml` на `"8081:80"`.

#### Проблема: `podman-compose` зависает при ожидании Healthcheck

**Причина:** В `podman-compose` (Python) реализация `depends_on.condition: service_healthy` ненадежна (открытые issues `containers/podman-compose#866`, `#1422`).

**Решение:** Используйте `depends_on` без `condition` (порядок запуска гарантирован), а готовность проверяйте через wait-скрипт или Quadlet с `Notify=healthy`.

```bash
# Альтернатива: скрипт ожидания готовности
podman-compose up -d db
until podman inspect --format '{{.State.Health.Status}}' web_db | grep -q healthy; do
  echo "Waiting for db..."
  sleep 2
done
podman-compose up -d app
```

#### Проблема: Ошибка `no compose.yaml` при наличии файла

**Причина:** `podman-compose` ищет файлы только в текущей директории (рекурсивно вверх на 10 уровней). Убедитесь, что вы запускаете команду из правильной директории или укажите файл явно:

```bash
podman-compose -f /path/to/project/compose.yaml up -d
```

### 13. Безопасность

Podman Compose поддерживает все стандартные механизмы безопасности Podman. В Compose-файле они задаются на уровне сервиса:

```yaml
services:
  app:
    image: docker.io/nginx:alpine
    read_only: true              # только для чтения (требует tmpfs для /run, /tmp)
    tmpfs:
      - /run
      - /tmp
    cap_drop:
      - ALL                      # отозвать все capabilities
    cap_add:
      - NET_BIND_SERVICE          # добавить только необходимую
    security_opt:
      - no-new-privileges         # запрет повышения привилегий
      - label=type:svirt_sandbox_file_t  # SELinux (контейнерный тип)
    volumes:
      - ./config:/etc/nginx/conf.d:ro,Z   # :Z — перемаркировать SELinux, ro — только чтение
```

**Параметры безопасности:**

- `read_only: true` — монтирует корневую ФС контейнера в режиме только для чтения. Для записи используйте `tmpfs` или том.
- `cap_drop` / `cap_add` — управление Linux capabilities. Рекомендуется `cap_drop: [ALL]` и явное добавление только требуемых.
- `security_opt` — передаются в `podman run --security-opt`. Поддерживаются `no-new-privileges`, `seccomp=<профиль>`, `label=...` (SELinux).
- `:Z` / `:z` — модификаторы SELinux для томов: `:Z` перемаркирует файлы для изолированного контейнера, `:z` — для общего доступа между контейнерами.
- `:U` — модификатор rootless, который автоматически подстраивает UID/GID хоста под контейнер (полезно для томов в rootless-режиме).

**Seccomp:** Podman использует встроенный профиль по умолчанию. Для кастомных правил укажите путь к JSON-файлу через `security_opt: ["seccomp=./nginx-seccomp.json"]`.

### 14. Сборка образов (Build context)

`podman-compose build` транслируется в `podman build`, который использует **Buildah** под капотом. Особенности:

```bash
# Сборка конкретного сервиса
podman-compose build app

# Сборка без кэша
podman-compose build --no-cache app

# Сборка с явным указанием файла
podman-compose build -f Dockerfile.prod app
```

**Рекомендации для .dockerignore (аналогично Docker):**

```text
.git
.gitlab-ci.yml
README.md
node_modules
dist
*.md
!LICENSE.md
```

**Multi-stage builds** работают стандартно, так как OCI-образы поддерживаются нативно:

```dockerfile
# Dockerfile
FROM golang:1.22 AS builder
WORKDIR /app
COPY go.* ./
RUN go build -o myapp .

FROM alpine:latest
COPY --from=builder /app/myapp /usr/local/bin/myapp
CMD ["myapp"]
```

### 15. Интеграция с CI/CD (on-prem)

Для локальных раннеров GitLab CI / GitHub Actions (self-hosted, без облаков) используйте `podman-compose` для поднятия зависимостей тестов:

**GitLab CI (`.gitlab-ci.yml`):**

```yaml
stages:
  - test

variables:
  PODMAN_COMPOSE_PROJECT_NAME: ci-$CI_PIPELINE_ID

services:
  - name: docker:dind
    alias: docker

before_script:
  - podman-compose --profile test up -d --wait --wait-timeout 60

test:
  stage: test
  script:
    - podman-compose exec app curl -f http://localhost:8080/health
  after_script:
    - podman-compose logs --no-color > compose_logs.txt
    - podman-compose down -v

artifacts:
  when: on_failure
  paths:
    - compose_logs.txt
```

**GitHub Actions (self-hosted runner):**

```yaml
jobs:
  integration-test:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - name: Start test dependencies
        run: podman-compose --profile test up -d --wait
      - name: Run tests
        run: podman-compose exec app pytest
      - name: Collect logs on failure
        if: failure()
        run: podman-compose logs > compose_logs.txt
      - name: Cleanup
        if: always()
        run: podman-compose down -v
```

**Важно:** На self-hosted раннере требуется активный `systemd --user` сессия или rootful-доступ к Podman. В rootless-режиме убедитесь, что `loginctl enable-linger $USER` выполнен для работы без интерактивного входа.

### 16. Шаблоны приложений

#### Шаблон 1: Веб-стек (Nginx + PHP-FPM + PostgreSQL)

```yaml
name: web-stack

services:
  db:
    image: docker.io/postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-secret}
      POSTGRES_USER: ${POSTGRES_USER:-app}
      POSTGRES_DB: ${POSTGRES_DB:-appdb}
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-app}"]
      interval: 5s
      retries: 5
    restart: unless-stopped

  php:
    image: docker.io/php:8.3-fpm-alpine
    volumes:
      - ./app:/var/www/html:ro,Z
    environment:
      DB_HOST: db
      DB_USER: ${POSTGRES_USER:-app}
      DB_PASSWORD: ${POSTGRES_PASSWORD:-secret}
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  nginx:
    image: docker.io/nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro,Z
      - ./app:/var/www/html:ro,Z
    depends_on:
      - php
    restart: unless-stopped

volumes:
  db_data:
    driver: local

networks:
  default:
    name: web-stack-net
```

**Запуск и проверка:**

```bash
podman-compose up -d --wait --wait-timeout 120
podman-compose ps
# → Name                     Command             State           Ports
# → web-stack_db_1           postgres            healthy         5432/tcp
# → web-stack_nginx_1        nginx ...           healthy         0.0.0.0:8080->80/tcp
# → web-stack_php_1          php-fpm ...         healthy

curl -f http://localhost:8080/health
# → HTTP/1.1 200 OK
```

#### Шаблон 2: Микросервисный стек (API + Redis + Worker)

```yaml
name: microservices

services:
  redis:
    image: docker.io/redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    volumes:
      - redis_data:/data
    restart: unless-stopped

  api:
    image: docker.io/myregistry/api:latest
    ports:
      - "8000:8000"
    environment:
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL: postgresql://app:secret@db:5432/appdb
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
    restart: unless-stopped

  worker:
    image: docker.io/myregistry/worker:latest
    environment:
      REDIS_URL: redis://redis:6379/0
    depends_on:
      - redis
    deploy:
      replicas: 2
    restart: unless-stopped

volumes:
  redis_data:
```

**Масштабирование worker'ов:**

```bash
podman-compose up -d --scale worker=3
podman-compose ps --format "table {{.Name}}\t{{.Status}}"
```

### 17. Очистка и рекомендации

```bash
# Остановка и удаление контейнеров, сетей проекта
podman-compose down

# Дополнительно удалить именованные тома
podman-compose down -v

# Удалить orphaned контейнеры (созданные вручную или другими инструментами)
podman-compose down --remove-orphans

# Принудительная пересоздание всех контейнеров
podman-compose up -d --force-recreate

# Удаление неиспользуемых образов и кэша
podman system prune -f
podman-compose build --no-cache
```

**Рекомендации:**

- Используйте `restart: unless-stopped` или `always` только в Quadlet для продакшена; в Compose для локальной разработки это допустимо, но не является заменой systemd.
- Для продакшена на Linux предпочитайте **Quadlet** (см. раздел «Альтернатива: Quadlet»).
- Никогда не храните секреты в `compose.yaml` — используйте `.env` (не коммитьте в Git) или `podman secret`.
- Указывайте FQIN для всех образов, чтобы избежать неожиданного разрешения через `registries.conf`.
- Используйте имена сервисов вместо `localhost` для межсервисного взаимодействия.

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

### Конвертация Compose → Quadlet

Для продакшн-деплоя на Linux рассмотрите конвертацию Compose-файла в Quadlet. Пример для сервиса `app` из шаблона выше:

**Файл:** `~/.config/containers/systemd/webapp.container`
```ini
[Unit]
Description=Web Application
After=network-online.target

[Container]
Image=docker.io/myregistry/app:latest
Network=web-stack-net
Environment=DATABASE_URL=postgresql://app:secret@db:5432/appdb
PublishPort=8080:80
AutoUpdate=registry
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Генерация шаблонов Quadlet из Compose выполняется утилитой `podlet` (отдельный инструмент на Rust, не входит в поставку Podman) или вручную. Подробное руководство см. в [Quadlet и Podlet](./podman-quadlet-vs-podlet.md). После размещения файла:

```bash
systemctl --user daemon-reload
systemctl --user start webapp.service
systemctl --user status webapp.service
# → Active: active (running) since ...
```

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

Подробнее см. раздел «Конвертация Compose → Quadlet» в этой же главе и **[Миграция с Docker (Compose → Quadlet)](./migration-from-docker.md)**.

### См. также
- **[Поды в Podman](./podman_pods.md)** — концепция групп контейнеров и сетевая модель пода.
- **[Управление зависимостями и готовностью](./podman-dependencies.md)** — особенности `depends_on` и `condition: service_healthy` в Compose-эквивалентах Podman.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — как работают процессы `conmon` и бездемонная модель.

### Ссылки
- **[Compose Specification](https://compose-spec.io/)** (англ.) — официальная спецификация формата Compose-файлов.
- **[podman-compose Repository](https://github.com/containers/podman-compose)** (англ.) — исходный код и issue tracker.
- **[Podman Compose Documentation](https://docs.podman.io/en/latest/markdown/podman-compose.1.html)** (англ.) — справочник по команде.
# force reindex test
