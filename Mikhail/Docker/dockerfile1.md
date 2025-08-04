# **Dockerfile**

Контейнер - это изолированный процесс (PID) на хосте.

---

### **1. Подготовка**

Для работы с Docker добавьте своего пользователя в группу `docker`:
```sh
sudo usermod -aG docker $USER
```
*После выполнения команды необходимо перезайти в систему.*

---

### **2. Пример Dockerfile**

```dockerfile
# Используем легковесный базовый образ
FROM alpine:3.18

# Добавляем метаданные к образу
LABEL maintainer="Mikhail" \
      version="1.0"

# Устанавливаем переменную окружения для версии Caddy
ENV CADDY_VERSION=2.7.6

# Устанавливаем Caddy и удаляем кэш пакетов
RUN apk add --no-cache curl gnupg && \
    curl -sSL "https://dl.cloudsmith.io/public/caddy/stable/gpg.key" | gpg --dearmor > /etc/apk/keys/caddy-stable.gpg && \
    echo "https://dl.cloudsmith.io/public/caddy/stable/alpine/v3.18/main" > /etc/apk/repositories.d/caddy-stable.conf && \
    apk add --no-cache caddy=${CADDY_VERSION} && \
    rm -rf /var/cache/apk/*

# Создаем пользователя без root-прав для безопасности
RUN adduser -D -H -s /bin/false nonroot

# Устанавливаем рабочую директорию
WORKDIR /caddy

# Копируем файл конфигурации с нужными правами
COPY --chmod=700 ./Caddyfile /caddy/Caddyfile

# Переключаемся на пользователя без root-прав
USER nonroot

# Указываем порт, который слушает приложение
EXPOSE 8080

# Устанавливаем сигнал для корректной остановки контейнера
STOPSIGNAL SIGINT

# Запускаем приложение
ENTRYPOINT ["/usr/bin/caddy", "run"]
```

---

### **3. Основные инструкции**

| Инструкция | Описание |
| :--- | :--- |
| **`FROM`** | Указывает базовый образ. Для безопасности рекомендуется использовать хэш: `FROM alpine@sha256:<digest>`. |
| **`LABEL`** | Добавляет метаданные (ключ-значение) к образу. |
| **`ENV`** | Устанавливает переменные окружения, доступные во время сборки и выполнения контейнера. |
| **`RUN`** | Выполняет команды в новом слое во время сборки образа. |
| **`COPY`** | Копирует файлы и директории с хоста в файловую систему контейнера. |
| **`ADD`** | Аналогично `COPY`, но с дополнительными возможностями, такими как распаковка архивов и загрузка по URL. `COPY` предпочтительнее для прозрачности. |
| **`WORKDIR`** | Устанавливает рабочую директорию для последующих инструкций. |
| **`USER`** | Устанавливает пользователя, от имени которого будут выполняться `RUN`, `CMD` и `ENTRYPOINT`. |
| **`EXPOSE`** | Информирует Docker о том, что контейнер прослушивает указанные сетевые порты. Не публикует порты. |
| **`STOPSIGNAL`**| Определяет системный сигнал для отправки процессу при остановке контейнера (по умолчанию `SIGTERM`). |
| **`ENTRYPOINT`**| Определяет команду, которая будет выполняться при запуске контейнера. |
| **`CMD`** | Задает команду по умолчанию или параметры для `ENTRYPOINT`. Может быть переопределена при запуске контейнера. |
| **`ARG`** | Переменная времени сборки, недоступная в запущенном контейнере. Используется для параметризации `docker build`. |

---

### **4. Лучшие практики**

#### **Оптимизация сборки**
- **Кэширование слоев:** Размещайте инструкции, которые меняются редко (например, установка зависимостей), в начале Dockerfile, а часто меняющиеся (копирование кода) — в конце.
- **Multi-stage сборки:** Используйте несколько инструкций `FROM` для разделения процесса сборки и финального образа. Это позволяет исключить из конечного образа ненужные зависимости и инструменты.
- **Минимизация количества слоев:** Объединяйте связанные команды `RUN` в одну, чтобы уменьшить количество слоев и размер образа.
- **Используйте `--mount=type=cache`:** Кэшируйте зависимости (например, `pip`, `npm`, `mvn`) для ускорения повторных сборок.

#### **Безопасность**
- **Не запускайте от root:** Создавайте и используйте пользователя без root-прав (`USER nonroot`).
- **Используйте `COPY` вместо `ADD`:** `COPY` более предсказуем и безопасен.
- **Сканируйте образы:** Используйте инструменты вроде `dockle` или `trivy` для поиска уязвимостей.
- **Используйте минимальные базовые образы:** Образы `alpine` или `scratch` уменьшают поверхность атаки.
- **Работа с секретами:** Используйте `--mount=type=secret` для безопасной передачи секретов во время сборки без их сохранения в слоях образа.

#### **Использование Alpine Linux**
Alpine — легковесный дистрибутив, но его стандартная библиотека C (`musl`) может быть несовместима с ПО, скомпилированным с `glibc` (Debian, Ubuntu). Это может вызвать проблемы с некоторыми пакетами Python, Ruby или Node.js.

**Виртуальные пакеты в Alpine:**
Используйте виртуальные пакеты для установки временных зависимостей, которые нужны только для сборки.
```dockerfile
RUN apk add --no-cache --virtual .build-deps gcc musl-dev && \
    pip install -r requirements.txt && \
    apk del .build-deps
```

---

### **5. Примеры для языков программирования**

#### **Python**
```dockerfile
# Этап 1: Установка зависимостей
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir -U pip
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Этап 2: Финальный образ
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .

# Устанавливаем переменные окружения
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
```

#### **Go**
```dockerfile
# Этап 1: Сборка
FROM golang:1.20-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-w -s" -o /app/main .

# Этап 2: Финальный образ
FROM scratch
COPY --from=builder /app/main /main
USER 10001
ENTRYPOINT ["/main"]
```

#### **Java (Maven)**
```dockerfile
# Этап 1: Сборка
FROM maven:3.8-openjdk-17 AS builder
WORKDIR /app
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 mvn dependency:go-offline
COPY src ./src
RUN mvn package -DskipTests

# Этап 2: Финальный образ
FROM openjdk:17-jre-slim
WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
```

#### **Ruby on Rails**
```dockerfile
# Этап 1: Установка зависимостей
FROM ruby:3.1-slim-bullseye AS builder
WORKDIR /usr/src/app
RUN apt-get update -qq && apt-get install --no-install-recommends -y build-essential git libpq-dev
RUN gem install bundler
COPY Gemfile Gemfile.lock ./
RUN bundle install --jobs $(nproc) --retry 3

# Этап 2: Финальный образ
FROM ruby:3.1-slim-bullseye
WORKDIR /usr/src/app
RUN apt-get update -qq && apt-get install --no-install-recommends -y libpq5 postgresql-client && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/bundle/ /usr/local/bundle/
COPY . .
RUN useradd -m --uid 1001 rails
USER rails
EXPOSE 3000
CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]
```