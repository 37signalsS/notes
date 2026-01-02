# Dockerfile Best Practices

This document outlines best practices for writing efficient, secure, and maintainable Dockerfiles.

## Оптимизация Сборки

### Оптимизация кеширования слоёв

Ключ к быстрой сборке Docker-образов — эффективное использование кеширования слоев. Правильная организация Dockerfile позволяет Docker повторно использовать уже собранные слои, что значительно ускоряет процесс.

-   **Зависимости меняются редко:** Файл с перечислением зависимостей (`requirements.txt`, `package.json`, `go.mod` и т.д.) обновляется гораздо реже, чем исходный код приложения.
-   **Код меняется постоянно:** Исходный код приложения меняется при каждом исправлении бага или добавлении новой функции.

Разделяя шаги установки зависимостей и копирования кода, вы создаете отдельный, долгоживущий кешированный слой для зависимостей, который не будет пересобираться при каждом изменении кода.

**Плохой пример:**

```dockerfile
FROM python:3.13-slim-bookworm
COPY . .

# Устанавливаем зависимости
RUN pip install -r requirements.txt

CMD ["python", "main.py"]
```
**Проблема:** При любом изменении в коде приложения, слой `COPY . .` становится невалидным. Это делает невалидными все последующие слои, и Docker будет **каждый раз заново** выполнять дорогостоящую команду `RUN pip install...`.

**Хороший пример:**

```dockerfile
FROM python:3.13-slim
WORKDIR /app

# 1. Копируем только файл с зависимостями
COPY requirements.txt .

# 2. Устанавливаем зависимости. Этот слой будет закеширован.
RUN pip install -r requirements.txt

# 3. Только теперь копируем остальной код приложения
COPY . .

CMD ["python", "main.py"]
```
**Результат:** Теперь, если вы меняете только код приложения, Docker использует кеш для слоя с `RUN pip install`. Пересборка происходит почти мгновенно, так как пересоздается только последний, очень "легкий" слой `COPY . .`.

Этот принцип можно развить дальше. Если у вас несколько инструкций `COPY`, их следует упорядочить **от наименее часто изменяемых файлов к наиболее часто изменяемым**.

**Пример для Node.js: `npm ci` для воспроизводимых сборок**

Для production-сборок **всегда следует использовать `npm ci` вместо `npm install`**.

-   **`npm install`**: Может изменять `package-lock.json`, если `package.json` был обновлен. Это подходит для разработки, но опасно для CI/CD, так как сборки могут быть непредсказуемыми.
-   **`npm ci` (Clean Install)**: Гарантирует **воспроизводимую сборку**. Команда удаляет `node_modules`, устанавливает зависимости **строго** по версиям из `package-lock.json` и никогда не изменяет этот файл. Если `package.json` и `package-lock.json` не синхронизированы, `npm ci` завершится с ошибкой, предотвращая сборку с некорректными зависимостями.

#### `dependencies` vs `devDependencies`

В файле `package.json` зависимости делятся на два типа:

-   **`dependencies`**: Пакеты, необходимые для работы приложения в production (например, `express`, `react`).
-   **`devDependencies`**: Пакеты, нужные только для разработки и тестирования (например, `jest`, `eslint`, `nodemon`).

Флаг `--only=production` (или его аналог `--production`) указывает `npm` устанавливать **только** пакеты из раздела `dependencies`. Это критически важно для Docker-образов, так как исключает ненужные инструменты разработки, делая итоговый образ меньше и безопаснее.

Оптимизированный `Dockerfile` для Node.js-приложения:

```dockerfile
# 1. package.json и package-lock.json меняются редко
COPY package.json package-lock.json ./

# 2. Устанавливаем ТОЛЬКО production-зависимости. Слой кешируется.
# Используем npm ci для быстрых и надежных сборок.
RUN npm ci --only=production

# 3. Копируем остальной код приложения
COPY . .
```
Таким образом, изменение в коде не приведет к переустановке `node_modules`, а `npm ci` обеспечит идентичность зависимостей в каждой сборке.

### Многоэтапные (Multi-stage) сборки

**Проблема:** Для сборки компилируемых приложений (например, на Go или Java) часто требуется "тяжелый" образ с компилятором и SDK. Для запуска скомпилированного приложения нужен только легковесный образ (например, `alpine` или `scratch`). Без многоэтапной сборки конечный образ будет содержать все ненужные для рантайма инструменты, что увеличит его размер и поверхность атаки.

**Решение:** Многоэтапная сборка позволяет разделить процесс сборки на несколько этапов, каждый из которых использует свой базовый образ. В конечный образ копируются только необходимые артефакты, полученные на предыдущих этапах.

**Пример для Go:**

```dockerfile
# --- Этап 1: Сборка (Builder) ---
# Начинаем с полного образа Go, который содержит все инструменты для сборки.
# Даем этому этапу имя "builder" для удобства.
FROM golang:1.25.1 AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Собираем статически скомпонованный бинарник.
RUN CGO_ENABLED=0 go build -o /app/main .

# --- Этап 2: Финальный образ (Final) ---
# Начинаем с "пустого" образа scratch. В нем нет ничего, даже оболочки.
FROM scratch

WORKDIR / 

# Копируем ТОЛЬКО скомпилированный бинарный файл из этапа "builder".
COPY --from=builder /app/main .

ENTRYPOINT ["/main"]
```
Этот подход значительно уменьшает размер конечного образа и повышает его безопасность.

### Запуск приложений в режиме Foreground

Ключевой практикой в Docker является запуск основного процесса в режиме "переднего плана" (foreground), а не в режиме демона (background). 

*   **Почему это важно?** Docker отслеживает основной процесс (CMD или ENTRYPOINT), запущенный в контейнере (тот, у которого PID 1). Как только этот процесс завершается, Docker считает, что работа контейнера окончена, и останавливает его.
*   **Что происходит с демонами?** Процесс, запущенный в режиме демона, сразу же отсоединяется от терминала и уходит в фон. Для Docker это выглядит так, как будто основной процесс завершился, и контейнер будет немедленно остановлен.

### Несколько процессов в контейнере

Запуск нескольких процессов в одном контейнере, как правило, является **анти-паттерном**. Философия Docker — "один процесс на контейнер". Однако, для миграции устаревших приложений или управления тесно связанными компонентами это может быть необходимо.

Правильным решением для таких сценариев является использование легковесного менеджера процессов (супервизора), такого как `supervisord`.

> **Подробное руководство по реализации этого паттерна, его проблемах (PID 1, сбор логов) и решениях находится в документе:**
> **[Паттерн "Multi-Process" в Docker](../Docker_logs/docker_multi_process_logging.md)**

## Безопасность

В этом разделе рассматриваются лучшие практики безопасности, применимые непосредственно при написании `Dockerfile`. Комплексное руководство по всем аспектам безопасности Docker, включая защиту демона, управление секретами и безопасность во время выполнения, находится в документе **[Безопасность Docker](../Docker_security/docker_security.md)**.

### Практика безопасности: Создание непривилегированного пользователя

Запуск процессов внутри контейнера от имени пользователя root (по умолчанию) является серьезным риском безопасности. Всегда следует создавать и использовать непривилегированного пользователя.

`groupadd -r user` — Создание изолированной группы

*   **Что делает флаг `-r` (`--system`)?**
    Этот флаг указывает, что мы создаем **системную** группу. В Linux принято разделять сущности на "пользовательские" и "системные".

`useradd -r -s /bin/false -g user user` — Создание "бесправного" пользователя

*   **Что делает флаг `-r` (`--system`)?**
    Аналогично `groupadd`, этот флаг создает **системного пользователя** с UID из системного диапазона (1-999). Обычно для таких пользователей не создается домашняя директория и не устанавливается срок действия пароля.

*   **Что делает флаг `-s /bin/false`?**
    *   **`-s` (`--shell`)** задает пользователю **командную оболочку** (shell).
    *   **`/bin/false`** — блокирует любую возможность интерактивного входа. Если кто-то попытается войти в систему под этим пользователем, сессия тут же завершится. От имени пользователя можно запускать процессы, но залогиниться им нельзя.

*   **Что делает флаг `-g user`?**
    *   **`-g` (`--gid`)** устанавливает **основную группу** пользователя. Когда этот пользователь будет создавать файлы, они по умолчанию будут принадлежать группе `user`.
    *   Мы привязываем пользователя к специально созданной для него группе, что позволяет гибко настраивать права доступа.

#### Альтернатива для Alpine: `adduser`

В образах на базе Alpine Linux часто используется утилита `adduser`, которая является более высокоуровневой. Команда `adduser -D -H -s /bin/false nonroot` делает то же самое:

*   **`-D` (`--no-password`):** Создает пользователя без пароля.
*   **`-H` (`--no-create-home`):** Не создает домашнюю директорию.
*   **`-s /bin/false`:** Устанавливает оболочку в `/bin/false`.
*   **`nonroot`:** Имя пользователя.

#### Заключительный шаг: `USER`

После создания пользователя, в `Dockerfile` обязательно следует команда `USER nonroot` (или `USER user`), которая переключает контекст. Все последующие инструкции (`COPY`, `CMD`, `ENTRYPOINT`) будут выполняться уже от имени нашего нового, безопасного, непривилегированного пользователя.

### Обновление пакетов (`apt-get upgrade`) — плохая практика

Выполнение `apt-get upgrade` (или аналогичных команд для других пакетных менеджеров) в Dockerfile является плохой практикой по нескольким причинам:

1.  **Нарушение воспроизводимости (Broken Reproducibility):** Выполнение `apt-get upgrade` во время сборки делает образ зависимым от состояния репозиториев в данный конкретный момент. Повторная сборка того же Dockerfile через некоторое время может привести к установке других версий пакетов, что ведет к непредсказуемому поведению.
2.  **Проблемы с кешированием (Cache Busting):** Команда `apt-get upgrade` инвалидирует кеш для этого слоя и всех последующих слоев, что приводит к полной пересборке всех последующих шагов при малейшем изменении в Dockerfile.

*   **Решение:** Используйте актуальный базовый образ. Вместо того чтобы обновлять старый образ, используйте более новую версию базового образа, в котором уже есть некоторые обновления (например, `debian:12.5` вместо `debian:12`). Если требуется установка специфичных версий пакетов, указывайте их явно.

---

## Рекомендации для специфичных языков/технологий

### Python

1.  **Фиксируйте версии:**
    *   **Базовый образ:** Всегда указывайте конкретный тег версии в инструкции `FROM` (например, `python:3.13-slim`).
    *   **Зависимости:** Используйте `pip freeze > requirements.txt` для создания точного списка зависимостей с версиями. Это обеспечивает воспроизводимость окружения.
2.  **Оптимизируйте кэширование слоев:**
    *   Сначала копируйте только `requirements.txt` и устанавливайте зависимости. Только после этого копируйте остальной код приложения. Это позволяет Docker кэшировать слой с установленными зависимостями.
    ```dockerfile
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    COPY . .
    CMD ["python", "main.py"]
    ```
3.  **Используйте `ENV PYTHONUNBUFFERED=1`:**
    Эта переменная окружения отключает буферизацию потоков `stdout` и `stderr` в Python, что критически важно для отладки и просмотра логов в реальном времени.
4.  **Разделяйте задачи миграции и запуска приложения:**
    *   Не стоит запускать миграции базы данных и веб-сервер одной командой в `CMD` или `ENTRYPOINT`. Контейнер должен выполнять только один основной процесс.
    *   **Вариант 1 (Переменная окружения):** Используйте переменную окружения для выбора действия в `entrypoint.sh`.
      ```dockerfile
      COPY entrypoint.sh /entrypoint.sh
      RUN chmod +x /entrypoint.sh
      ENTRYPOINT ["/entrypoint.sh"]
      ```
      **entrypoint.sh:**
      ```sh
      #!/bin/sh
      set -e
      if [ "$MODE" = "migrate" ]; then
          echo "Running database migrations..."
          python manage.py migrate
      elif [ "$MODE" = "start" ]; then
          echo "Starting the application..."
          gunicorn myapp.wsgi:application --bind 0.0.0.0:8000
      else
          exec "$@"
      fi
      ```
    *   **Вариант 2 (Docker Compose):** Для более сложных сценариев, где задачи (миграция, запуск сервера, воркеры) должны выполняться как отдельные, но связанные процессы, рекомендуется использовать Docker Compose. Подробнее об этом можно прочитать в [документе о Docker Compose](../Docker_compose/docker_compose.md).
5.  **Multi-stage сборки для Python:**
    *   **Установка зависимостей в `--user`**: Позволяет установить зависимости в домашний каталог пользователя, а затем скопировать их в финальный образ.
      ```dockerfile
      # Этап 1: Сборщик (builder)
      FROM python:3.13 AS builder
      WORKDIR /app
      COPY requirements.txt .
      RUN pip install --user -r requirements.txt
      # Этап 2: Финальный образ
      FROM python:3.12-slim-bookworm
      WORKDIR /app
      COPY --from=builder /root/.local /root/.local
      ENV PATH=/root/.local/bin:$PATH
      ENV PYTHONUNBUFFERED=1
      COPY myapp.py .
      CMD ["python", "myapp.py"]
      ```
    *   **Использование виртуального окружения (`venv`)**: Более изолированный подход, который отделяет зависимости проекта.
      ```dockerfile
      # Этап 1: Сборщик (builder)
      FROM python:3.12 AS builder
      WORKDIR /app
      RUN python3 -m venv /opt/venv
      ENV PATH="/opt/venv/bin:$PATH"
      COPY requirements.txt .
      RUN pip install -r requirements.txt
      # Этап 2: Финальный образ
      FROM python:3.12-slim
      WORKDIR /code
      COPY --from=builder /opt/venv /opt/venv
      ENV PATH="/opt/venv/bin:$PATH"
      ENV PYTHONUNBUFFERED=1
      COPY ./src .
      CMD ["python", "./server.py"]
      ```
6.  **Собирайте статику на этапе сборки (build-time):**
    *   Неправильно запускать `python manage.py collectstatic` в `ENTRYPOINT` или `CMD`. Это замедляет запуск контейнера.
    *   Правильно: Включить сборку статики в `Dockerfile` как одну из `RUN` инструкций.
    ```dockerfile
    # ... (установка зависимостей) ...
    COPY . .
    RUN python manage.py collectstatic --no-input --clear
    CMD ["gunicorn", "myapp.wsgi:application"]
    ```

### Java

1.  **Осведомленность о cgroups (Cgroup Awareness):**
    *   **Проблема:** Старые версии Java (до 8u131, например, Java 7) **не поддерживают [cgroups](../Docker_components/docker_components.md#cgroups-управление-ресурсами)**.
    *   **Решение:** Если вы используете старую версию, **обязаны** вручную задавать размер кучи через флаги `-Xmx` и `-Xms`.
2.  **Multi-stage сборка:**
    *   **Этап 1 (builder):** Используется "тяжелый" образ с JDK и сборочным инструментом (Maven/Gradle).
    *   **Этап 2 (final):** Используется минималистичный образ только со средой выполнения (JRE), куда копируется собранный артефакт (JAR-файл).
    ```dockerfile
    # Этап 1: Сборка с Maven
    FROM maven:3.9.11-eclipse-temurin-25 AS builder
    WORKDIR /app
    COPY pom.xml .
    RUN --mount=type=cache,target=/root/.m2 mvn dependency:go-offline
    COPY src ./src
    RUN mvn package
    # Этап 2: Финальный образ с OpenJDK
    FROM eclipse-temurin:21-jre-alpine
    WORKDIR /app
    COPY --from=builder /app/target/*.jar app.jar
    EXPOSE 8080
    CMD ["java", "-jar", "app.jar"]
    ```
3.  **Управление памятью:**
    *   **Ограничивайте размер кучи (heap):** Явно задавайте максимальный размер кучи (`-Xmx<size>` или `-XX:MaxRAMPercentage`).
    *   **Дайте контейнеру больше памяти:** Выделяйте контейнеру примерно на 25% больше памяти, чем установлено в `-Xmx`, для нужд JVM.
4.  **Кэширование зависимостей:**
    *   Используйте `--mount=type=cache` для кэширования директорий `.m2` или `.gradle` для ускорения повторных сборок.

### Go

- **`FROM scratch`:** Можно запускать собранный бинарный файл в минималистичном образе `FROM scratch` для уменьшения размера и поверхности атаки.
- **`Makefile`:** При локальной сборке часто применяют `Makefile` для автоматизации шагов.
- **Multi-stage сборка для Go:**
```dockerfile
# --- Этап 1: Сборка бинарного файла (builder) ---
FROM golang:1.25.1-alpine AS builder
RUN apk update && apk add --no-cache git
RUN adduser -D -u 10001 appuser
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
RUN go mod verify
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags "-w -s" -o /app/main .

# --- Этап 2: Финальный образ ---
FROM scratch
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group
COPY --from=builder /app/main /main
USER appuser
EXPOSE 9292
ENTRYPOINT ["/main"]
```
#### Решение проблемы "no such file or directory" в Alpine
При многоэтапной сборке Go, когда на этапе сборки используется `glibc`-образ, а на финальном — `alpine` (`musl libc`), может возникнуть ошибка `no such file or directory` из-за несовместимости библиотек.
**Решение:** Скомпилировать **полностью статически связанный (statically linked)** бинарный файл.
```dockerfile
FROM golang:1.25.1 AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -a -ldflags '-extldflags "-static"' -o /app/main .
FROM alpine:3.22.2
COPY --from=builder /app/main /main
RUN chmod +x /main
ENTRYPOINT ["/main"]
```

### Ruby on Rails

- **Multi-stage сборка для Ruby on Rails:**
```dockerfile
FROM ruby:3.4.6-slim-bookworm AS builder
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y build-essential git libpq-dev
WORKDIR /usr/src/app
RUN gem install bundler
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local without 'development test' && \
    bundle install --jobs $(nproc) --retry 3

FROM ruby:3.4.6-slim-bookworm
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y curl libpq5 postgresql-client && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /usr/src/app
COPY --from=builder /usr/local/bundle/ /usr/local/bundle/
COPY . .
RUN useradd -m --uid 1001 rails
USER rails
EXPOSE 3000
CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]
```
- **Оптимизированный Dockerfile для Ruby on Rails (Alpine):**
```dockerfile
FROM ruby:3.3-alpine
RUN set -ex && \
    apk add --update --virtual .runtime-deps \
        postgresql-client \
        nodejs \
        libffi-dev \
        readline \
        sqlite && \
    rm -rf /var/cache/apk/*
WORKDIR /tmp
COPY Gemfile Gemfile.lock ./
RUN set -ex && \
    apk add --virtual .build-deps \
        build-base \
        openssl-dev \
        postgresql-dev \
        libc-dev \
        linux-headers \
        libxml2-dev \
        libxslt-dev \
        readline-dev && \
    bundle install --clean --no-cache --without development test --jobs=$(getconf _NPROCESSORS_ONLN) && \
    rm -rf /var/cache/apk/* && \
    apk del .build-deps
ENV APP_HOME /app
COPY . $APP_HOME
WORKDIR $APP_HOME
ENV RAILS_ENV=production RACK_ENV=production
EXPOSE 3000
CMD ["bundle", "exec", "puma"]
```

### PostgreSQL

Официальный Docker-образ `postgres` предоставляет специальный механизм для инициализации базы данных при первом запуске контейнера. Любые файлы с расширениями `.sh`, `.sql` или `.sql.gz`, помещенные в каталог `/docker-entrypoint-initdb.d/` внутри контейнера, будут выполнены в алфавитном порядке при его создании.
```dockerfile
FROM postgres:15
COPY init.sql /docker-entrypoint-initdb.d/
```

