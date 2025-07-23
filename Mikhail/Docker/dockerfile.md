# **Dockerfile**

Контейнер - это просто процесс (PID) на хосте.

---

### **Подготовка**

Добавить пользователя в группу `docker`:
```sh
sudo usermod -aG docker ubuntu
```

---

### **Пример Dockerfile**

```dockerfile
FROM alpine:3.18

LABEL multi.label1="value1" \
      multi.label2="value2" \
      other="value3"

STOPSIGNAL SIGINT

ENV CADDY_VERSION=2.7.6

RUN apk add --no-cache curl gnupg && \
    curl -sSL "https://dl.cloudsmith.io/public/caddy/stable/gpg.key" | gpg --dearmor > /etc/apk/keys/caddy-stable.gpg && \
    echo "https://dl.cloudsmith.io/public/caddy/stable/alpine/v3.18/main" > /etc/apk/repositories.d/caddy-stable.conf && \
    apk add --no-cache caddy=${CADDY_VERSION} && \
    rm -rf /var/cache/apk/*

RUN adduser -D -H -s /bin/false nonroot
WORKDIR /caddy

COPY --chmod=700 ./Caddyfile /caddy/Caddyfile

USER nonroot

EXPOSE 8080/tcp
ENTRYPOINT ["/usr/bin/caddy", "run"]
```

---

### **Основные инструкции**

**FROM**
Какой базовый образ взять. Для большей безопасности можно указать хэш образа (`FROM <image>@sha256:<digest>`). Хэш выводится при `docker pull alpine:latest`.

Если тег не указан (например, `FROM debian`), Docker по умолчанию будет использовать тег `latest`. **Важно:** при изменении образа latest(что будет происходить очень часто) образ будет билдиться по-новой

**SHELL**
Выбор оболочки для выполнения `RUN`.

**STOPSIGNAL**
Определяет сигнал операционной системы, который будет отправлен основному процессу (PID 1) внутри контейнера при его остановке. По умолчанию Docker отправляет сигнал `SIGTERM` (15), чтобы корректно завершить процесс. Если процесс не завершается после отправки `SIGTERM`, через некоторое время (по умолчанию 10 секунд) Docker отправляет сигнал `SIGKILL` (9), который принудительно завершает процесс.

**ARG и ENV**

Основное различие между `ARG` и `ENV` заключается в их области видимости и назначении.

| Характеристика | `ARG` | `ENV` |
| :--- | :--- | :--- |
| **Назначение** | Переменные для процесса сборки | Переменные для среды выполнения контейнера |
| **Доступность** | Только во время сборки (`docker build`) | Во время сборки и во время выполнения (`docker run`) |
| **Сохранение в образе** | Нет | Да |
| **Способ переопределения**| `docker build --build-arg` | `docker run -e` |
| **Типичное применение** | Указание версий, кастомизация сборки | Конфигурация приложения (ключи API, URL) |

- **`ARG` (переменная времени сборки):**
  - Доступна **только** в процессе сборки образа (`docker build`).
  - Не сохраняется в конечном образе и недоступна для запущенного контейнера.
  - Используется для параметризации сборки: передачи версий, токенов или для включения отладочных инструментов.
  - Пример:
    ```dockerfile
    ARG APP_VERSION=1.0
    RUN echo "Собирается версия: $APP_VERSION"
    ```
    Переопределить значение можно командой: `docker build --build-arg APP_VERSION=2.1 .`

- **`ENV` (переменная среды выполнения):**
  - Устанавливает переменные окружения, которые доступны как во время сборки, так и внутри запущенного контейнера.
  - Сохраняется в образе.
  - Используется для конфигурации приложения: URL базы данных, порты, ключи API.
  - Пример:
    ```dockerfile
    ENV DB_HOST=localhost
    CMD ["echo", "Подключение к $DB_HOST"]
    ```
    Переопределить значение можно командой: `docker run -e DB_HOST=db.example.com my-image`

**Совместное использование:**
Часто `ARG` используют для установки значения `ENV` по умолчанию.

```dockerfile
ARG APP_PORT=8080
ENV PORT=${APP_PORT}
EXPOSE ${PORT}
```

**ENV PYTHONUNBUFFERED=1**

Эта инструкция особенно важна для Python-приложений. По умолчанию Python буферизирует потоки `stdout` и `stderr`. Это означает, что данные, выводимые вашим приложением (например, через `print()`), не сразу появляются в логах Docker. Они накапливаются в буфере и выводятся только при его заполнении или при завершении процесса.

Установка `ENV PYTHONUNBUFFERED=1` отключает эту буферизацию, и все выводы сразу направляются в логи контейнера. Это критически важно для отладки, так как позволяет видеть логи в реальном времени.

**LABEL**
Присвоение меток, либо `LABEL ver1.0` или несколько меток как в примере выше.

**RUN**
Какая команда выполнится во время сборки данного образа.

- **Кэширование зависимостей:**
`--mount=type=cache` позволяет монтировать кэш в процессе выполнения `RUN`. Это ускорит повторные сборки, так как, например, зависимости будут взяты из кэша, который хранится на хосте. Кэш не попадёт в финальный образ, но будет доступен для повторного использования.
*> **Примечание:** Опции `--mount` являются частью **BuildKit**, современного движка для сборки образов. В новых версиях Docker он включен по умолчанию.*
```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```


- **Bind mounts при сборке:**
`--mount=type=bind` позволяет монтировать директорию или файл с хостовой системы в контейнер во время выполнения команды `RUN`. В отличие от `COPY`, данные не копируются в образ, а временно подключаются с хоста для процесса сборки.
```dockerfile
RUN --mount=type=bind,source=./src,target=/app/src \
    go build -o app ./src
```

- **Работа с секретами:**
`--mount=type=secret` временно монтирует секрет с хоста и не хранит его в финальном образе.
```dockerfile
RUN --mount=type=secret,id=ssh,target=/root/.ssh/id_rsa \
    git clone git@github.com:user/repo.git .\
    
RUN --mount=type=secret,id=api_key,target=/run/secrets/api_key \
    export API_KEY=$(cat /run/secrets/api_key) && \
    pip install --extra-index-url https://$API_KEY@private-repo.com/packages some-package
```

**COPY**
Просто копирует файл из файловой системы хоста в файловую систему контейнера. Сначала надо указать файл с хоста, а затем путь в контейнере. Если необходимо исполнение программы/скрипта с определенными правами, лучше скопировать с их присвоением, иначе при вызове в `RUN`/`ENTRYPOINT` файл скопируется еще раз (его метаданные изменятся) и увеличит размер образа.

**ADD**
Может не просто копировать файлы, как `COPY`, но и, например, скачивать по HTTP и распаковывать архивы. Поэтому инструкция `COPY` предпочтительней при создании образов, потому что делает добавление файлов в образ более прозрачным.

**WORKDIR**
Текущий каталог при старте контейнера (если его нет, то будет создан).

**EXPOSE**
Список портов, используемых контейнеризованным процессом. Но реально порты не открываются наружу этой инструкцией, это лишь для справки тем, кто использует данный образ.

**ENTRYPOINT и CMD**
`ENTRYPOINT` — какой процесс необходимо запустить при старте контейнера и его аргументы.

При запуске `docker run <имя образа> <аргументы>`, если `Dockerfile`, на основе которого был сделан образ, не содержал `ENTRYPOINT`, то выполнится только команда, например: `docker run <имя образа> <команда в образе>`.

Команда `docker run` включает в себя `docker create` (создает контейнер) и `docker start` (запускает его).

При использовании `CMD` параметры командной строки, которые вы передаёте в момент запуска контейнера, могут перезаписать параметры, указанные в `Dockerfile`.
В случае с `ENTRYPOINT`, параметры из командной строки не могут перезаписать значения из `Dockerfile`, но будут либо игнорироваться (shell form), либо добавятся к ним (exec form). Кроме того, `CMD` и `ENTRYPOINT` могут работать вместе.

Например, следующий `Dockerfile` при запуске `docker run "image"` выведет "hello world", а `docker run "image" Docker` выведет "hello Docker".
```dockerfile
ENTRYPOINT ["echo", "hello"]
CMD ["world"]
```

---

### **Использование Alpine Linux**

*   **Проблемы совместимости из-за `musl libc`:**
    *   Большинство ПО в мире Linux скомпилировано с использованием `glibc`. `musl` — это альтернативная, легковесная реализация стандартной библиотеки C, но она не на 100% совместима с `glibc`.
    *   **Проблемы могут возникнуть с:**
        *   **Python, Ruby, Node.js:** Некоторые пакеты, использующие C-расширения, могут потребовать компиляции во время сборки, что усложняет Dockerfile.
        *   **Готовые бинарные файлы:** Бинарные файлы, скомпилированные с `glibc`, не запустятся на Alpine.
        *   **DNS:** В `musl` есть отличия в обработке DNS-запросов, что может вызывать проблемы в сложных сетевых окружениях.
*   **Менее привычные инструменты:**
    *   Alpine использует `BusyBox`, который предоставляет урезанные версии стандартных утилит Unix.
    *   Оболочка по умолчанию — `ash`, а не `bash`.
*   **Меньшее количество пакетов:** Репозиторий пакетов Alpine меньше, чем у Debian или CentOS.

**Виртуальные пакеты в Alpine**

Виртуальные пакеты — это временные группы пакетов, которые можно установить для выполнения задачи (например, компиляции), а затем удалить одной командой.

**Пример:**

```dockerfile
FROM python:3.10-alpine

WORKDIR /app

COPY requirements.txt .

RUN apk add --no-cache --virtual .build-deps gcc musl-dev libxml2-dev libxslt-dev && \
    pip install --no-cache-dir -r requirements.txt && \
    apk del .build-deps

COPY . .

CMD ["python", "app.py"]
```

**Разбор `RUN` команды:**

1.  `apk add --no-cache --virtual .build-deps gcc musl-dev ...`: Создает виртуальный пакет `.build-deps` и устанавливает в него зависимости для компиляции.
2.  `pip install ...`: Устанавливает Python-пакеты, используя установленные зависимости.
3.  `apk del .build-deps`: Удаляет виртуальный пакет со всеми его зависимостями, оставляя образ чистым.

**Итог:**

*   **Использовать Alpine:** Отличный выбор для Go, Rust, Node.js или любого другого приложения, которое компилируется в один статический бинарник.
*   **Когда стоит подумать дважды:** Если у вас сложное Python/Ruby приложение с множеством C-расширений, и вы не хотите тратить время на отладку сборки. В этом случае образ на основе Debian (например, `python:3.10-slim-bullseye`) может быть более простым выбором.

---

### **Лучшие практики для Python**

При контейнеризации Python-приложений стоит придерживаться следующих правил для создания стабильных, предсказуемых и оптимизированных образов.

1.  **Фиксируйте версии:**
    *   **Базовый образ:** Всегда указывайте конкретный тег версии в инструкции `FROM`, например, `FROM python:3.11-slim`, а не `FROM python:latest`. Это гарантирует, что ваша сборка не сломается из-за неожиданных обновлений в базовом образе.
    *   **Зависимости:** Используйте `pip freeze > requirements.txt` для создания точного списка зависимостей с версиями. Это обеспечивает воспроизводимость окружения.

2.  **Оптимизируйте кэширование слоев:**
    *   Сначала копируйте только `requirements.txt` и устанавливайте зависимости. И только потом копируйте остальной код приложения.
    *   Это позволяет Docker кэшировать слой с установленными зависимостями. Если вы меняете только код приложения, а не зависимости, сборка будет проходить значительно быстрее, так как слой с `pip install` не будет пересобираться.

    ```dockerfile
    WORKDIR /app

    # Сначала копируем только зависимости
    COPY requirements.txt .

    # Устанавливаем зависимости (этот слой будет кэширован)
    RUN pip install --no-cache-dir -r requirements.txt

    # Теперь копируем остальной код
    COPY . .

    CMD ["python", "main.py"]
    ```

3.  **Используйте `PYTHONUNBUFFERED=1`:**
    *   Добавьте `ENV PYTHONUNBUFFERED=1` в ваш `Dockerfile`.
    *   Это отключает буферизацию вывода в Python, что позволяет видеть логи вашего приложения в `docker logs` в реальном времени. Незаменимо для отладки.

4.  **Разделяйте задачи миграции и запуска приложения:**
    *   Не стоит запускать миграции базы данных и веб-сервер одной командой в `CMD` или `ENTRYPOINT`.
    *   **Причина:** Контейнер должен выполнять только один процесс. Если миграции завершатся с ошибкой, сервер все равно может запуститься, и наоборот.
    *   **Решение:**
        *   **Вариант 1 (Переменная окружения):** Используйте переменную окружения для выбора действия.

          ```dockerfile
          # ...
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

          Запуск:
          ```sh
          # Запуск миграций
          docker run -e MODE=migrate my-app

          # Запуск приложения
          docker run -e MODE=start -p 8000:8000 my-app
          ```

        *   **Вариант 2 (Docker Compose):** Определите разные сервисы для разных задач.

          ```yaml
          services:
            app:
              build: .
              command: ["gunicorn", "myapp.wsgi:application", "--bind", "0.0.0.0:8000"]
            migrate:
              build: .
              command: ["python", "manage.py", "migrate"]
              depends_on:
                - db
          ```

5.  **Multi-stage сборки для Python:**

    **Пример 1: Установка зависимостей в `--user`**

    Этот подход позволяет установить зависимости в домашний каталог пользователя, а затем скопировать их в финальный образ. Это проще, чем работа с `venv`.

    ```dockerfile
    # Этап 1: Сборщик (builder)
    FROM python:3.8 AS builder
    WORKDIR /app
    COPY requirements.txt .
    # Устанавливаем зависимости в локальный каталог пользователя
    RUN pip install --user -r requirements.txt

    # Этап 2: Финальный образ
    FROM python:3.8-slim-buster
    WORKDIR /app
    # Копируем установленные зависимости из сборочного образа
    COPY --from=builder /root/.local /root/.local
    # Добавляем директорию с бинарными файлами в PATH
    ENV PATH=/root/.local/bin:$PATH
    ENV PYTHONUNBUFFERED=1
    COPY myapp.py .
    CMD ["python", "myapp.py"]
    ```

    **Пример 2: Использование виртуального окружения (`venv`)**

    Этот подход более изолированный и считается лучшей практикой в мире Python. Виртуальное окружение полностью отделяет зависимости проекта.

    ```dockerfile
    # Этап 1: Сборщик (builder)
    FROM python:3.8 AS builder
    WORKDIR /app
    # Создаем виртуальное окружение
    RUN python3 -m venv /opt/venv
    # Активируем venv
    ENV PATH="/opt/venv/bin:$PATH"
    COPY requirements.txt .
    RUN pip install -r requirements.txt

    # Этап 2: Финальный образ
    FROM python:3.8-slim
    WORKDIR /code
    # Копируем виртуальное окружение из сборочного образа
    COPY --from=builder /opt/venv /opt/venv
    # Активируем venv в финальном образе
    ENV PATH="/opt/venv/bin:$PATH"
    # Вывод python логов в docker log в режиме реального времени
    ENV PYTHONUNBUFFERED=1
    COPY ./src .
    CMD ["python", "./server.py"]
    ```

### **Лучшие практики для Java**

1.  **Осведомленность о cgroups:**
    *   **Проблема:** Старые версии Java (до 8u131) не умели корректно определять лимиты памяти и CPU, установленные через cgroups в Docker. JVM видела всю память хоста, что могло приводить к `OutOfMemoryError`, даже если контейнеру было выделено достаточно ресурсов.
    *   **Решение:** Используйте современные версии Java (8u131+). Если вы вынуждены использовать старую версию, вам придется вручную выставлять лимиты памяти для JVM.

2.  **Multi-stage сборка:**

    ```dockerfile
    # Этап 1: Сборка с Maven
    FROM maven:3.8.5-openjdk-11 AS builder
    WORKDIR /app
    COPY pom.xml .
    # Используем кэширование зависимостей Maven
    RUN --mount=type=cache,target=/root/.m2 mvn dependency:go-offline
    COPY src ./src
    RUN mvn package

    # Этап 2: Финальный образ с OpenJDK
    FROM openjdk:11-jre-slim
    WORKDIR /app
    # Копируем только собранный jar-файл
    COPY --from=builder /app/target/*.jar app.jar
    EXPOSE 8080
    CMD ["java", "-jar", "app.jar"]
    ```

3.  **Управление памятью:**
    *   **Ограничивайте размер кучи (heap):** Даже с современными версиями Java, рекомендуется явно задавать максимальный размер кучи. Это делает поведение приложения более предсказуемым.
        *   `-Xmx<size>`: Устанавливает максимальный размер кучи (например, `-Xmx512m`).
        *   `-XX:MaxRAMPercentage`: (Java 8u191+) Устанавливает максимальный процент от доступной контейнеру памяти, который будет использован для кучи. Например, `-XX:MaxRAMPercentage=75.0`.
    *   **Дайте контейнеру больше памяти:** Выделяйте контейнеру примерно на 25% больше памяти, чем вы установили в `-Xmx`. Это необходимо для нужд самой JVM (metaspace, потоки, нативная память).

4.  **Кэширование зависимостей:**
    *   Как показано в примере выше, используйте `--mount=type=cache` для кэширования директории `.m2` (для Maven) или `.gradle` (для Gradle). Это значительно ускоряет повторные сборки, так как зависимости не будут скачиваться каждый раз заново.

### **Оптимизация и лучшие практики**

Для уменьшения веса образа можно:
- Добавить в `RUN` удаление кэша пакетного менеджера, например: `rm -rf /var/lib/apt/lists/*`.
- Выбрать `alpine` и при установке использовать `apk add --no-cache`. Можно также при установке создать `ENV NGINX_VERSION=номер_версии` и передать `apk add --no-cache nginx=${NGINX_VERSION}`.
- Чтобы образ быстрее собирался, можно перенести части `Dockerfile`, которые часто меняются, в конец файла (если какой-то слой изменился, то все последующие будут пересобираться).
- Чтобы образ меньше весил, можно при сборке `Dockerfile` в конце добавить экспериментальную функцию `--squash`, которая аналогична `git squash` и объединяет все слои в один (но при пересборке кэш не используется).
- Использовать `dive` для анализа слоёв, `Slim` для автоматического уменьшения размера и повышения безопасности, `strip` для удаления отладочной информации из бинаря
- Изучить рекомендации по безопасности, например, [dockle](https://github.com/goodwithtech/dockle) и https://github.com/docker/docker-bench-security.
- Конвертация docker-compose файл в манифесты kubernetes(https://docs.docker.com/compose/bridge/)

### **Лучшие практики для Ruby on Rails**

**Пример Dockerfile для Rails (Multi-stage):**

```dockerfile
# --- Этап 1: Установка зависимостей ---
FROM ruby:3.1.2-slim-bullseye AS builder

# Устанавливаем системные зависимости для сборки гемов
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y build-essential git libpq-dev

WORKDIR /usr/src/app

# Устанавливаем Bundler
RUN gem install bundler:2.3.14

# Копируем Gemfile и устанавливаем зависимости
# Это кэшируется, если Gemfile не меняется
COPY Gemfile Gemfile.lock ./ 
RUN bundle config set --local without 'development test' && \
    bundle install --jobs $(nproc) --retry 3

# --- Этап 2: Финальный образ ---
FROM ruby:3.1.2-slim-bullseye

# Системные зависимости для работы приложения
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y curl libpq5 postgresql-client && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

# Копируем установленные гемы из builder'а
COPY --from=builder /usr/local/bundle/ /usr/local/bundle/

# Копируем код приложения
COPY . .

# Запускаем приложение от имени пользователя без root-прав
RUN useradd -m --uid 1001 rails
USER rails

# Открываем порт
EXPOSE 3000

# Основная команда для запуска сервера
CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]
```

**Оптимизированный Dockerfile для Ruby on Rails:**

```dockerfile
FROM ruby:2.3-alpine

# Устанавливаем runtime-зависимости
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

# Устанавливаем build-time зависимости, ставим гемы и удаляем build-time зависимости
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
### **Лучшие практики для Go**

- **`FROM scratch`:** Можно запускать собранный бинарный файл в минималистичном образе `FROM scratch` для уменьшения размера и поверхности атаки.
- **`Makefile`:** При локальной сборке часто применяют `Makefile` для автоматизации шагов.

**Пример Dockerfile для Go (Multi-stage):**

```dockerfile
# Golang Dockerfile

# --- Этап 1: Сборка бинарного файла (builder) ---
FROM golang:1.19-alpine AS builder

# Устанавливаем git для скачивания зависимостей
RUN apk update && apk add --no-cache git

# Создаем пользователя без привилегий для безопасности
RUN adduser -D -u 10001 appuser

WORKDIR /app

# Копируем файлы зависимостей и загружаем их
# Этот слой кэшируется, если файлы не меняются
COPY go.mod go.sum ./ 
RUN go mod download
RUN go mod verify

# Копируем остальной исходный код
COPY . .

# Собираем статически скомпонованный бинарный файл
# Флаги -w -s удаляют отладочную информацию, уменьшая размер
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /app/main .

# --- Этап 2: Финальный образ ---
FROM scratch

# Копируем файлы пользователя и группы из builder'а,
# так как в scratch нет утилит для создания пользователей
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group

# Копируем скомпилированный бинарный файл
COPY --from=builder /app/main /main

# Устанавливаем пользователя, от имени которого будет работать приложение
USER appuser

# Указываем порт, который слушает приложение (для информации)
EXPOSE 9292

# Точка входа: запускаем наше приложение
ENTRYPOINT ["/main"]
```