# Alpine Linux в Docker

## Определения

**Alpine Linux** — минималистичный, ориентированный на безопасность дистрибутив Linux, основанный на стандартной библиотеке **musl libc** и наборе утилит **BusyBox**.

Благодаря крайне малому размеру (около 5–7 МБ для базового образа) он является индустриальным стандартом для создания легковесных Docker-контейнеров, обеспечивая высокую скорость доставки (Pull/Push) и минимальную поверхность атаки.

### Варианты официальных образов

Alpine выпускается в нескольких форматах:

| Тег образа | Описание | Размер (прибл.) | Рекомендуемый сценарий |
| :--- | :--- | :--- | :--- |
| `alpine:3.21` | Полный базовый образ | ~8 МБ | Общего назначения, shell-операции |
| `alpine:3.21` (с `apk add`) | Базовый + дополнительные пакеты | ~15–30 МБ | Приложения с зависимостями |
| `node:22-alpine` | Alpine + Node.js | ~50 МБ | Node.js приложения |
| `python:3.13-alpine` | Alpine + Python | ~50 МБ | Python приложения |
| `golang:1.24-alpine` | Alpine + Go toolchain | ~300 МБ | Сборка Go-проектов |

### Релизы (Releases)

Alpine следует модели стабильных релизов:
- **Стабильные релизы** (3.x): Обновляются ~2 года. Каждый релиз содержит свежие версии пакетов.
- **Роллинг-обновления:** Between-stable патчи (3.x.y) выходят регулярно и содержат исправления безопасности.
- **EOL:** Alpine 3.15 — EOL (ноябрь 2023), Alpine 3.16 — EOL (май 2024), Alpine 3.17 — EOL (ноябрь 2024). Всегда используйте актуальную стабильную версию.

## Предварительные требования

### Программное обеспечение

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Docker Engine** | 19.03 | 23.0+ | Любой современный Docker |
| **docker pull** | — | — | Доступ к Docker Hub или зеркалу |

### Проверка работоспособности

```bash
# Быстрая проверка — запуск Alpine
docker run --rm alpine:3.21 cat /etc/os-release
# -> NAME="Alpine Linux"
# -> ID=alpine
# -> VERSION_ID=3.21.x

# Проверка размера образа
docker images alpine:3.21
# -> REPOSITORY   TAG    IMAGE ID       CREATED        SIZE
# -> alpine       3.21   ...            ...            8.x MB

# Проверка доступных пакетов
docker run --rm alpine:3.21 apk search --no-cache | wc -l
# -> ~13000 (количество доступных пакетов)
```

### Первичная настройка

```bash
# Обновление индекса пакетов и системы
docker run --rm alpine:3.21 sh -c "apk update && apk upgrade --no-cache"

# Установка часто используемых пакетов
docker run --rm alpine:3.21 apk add --no-cache \
    curl \
    wget \
    bash \
    git \
    ca-certificates \
    tzdata
```

## Базовые концепции

### Ключевые компоненты и отличия

1.  **Библиотека musl libc:**
    - В отличие от `glibc` (используется в Ubuntu/Debian), `musl` строго следует стандартам POSIX и оптимизирована для статической линковки.
    - **Совместимость:** Бинарные файлы (Wheels в Python, модули Node.js), скомпилированные под `glibc`, не запустятся в Alpine без слоя совместимости. Это часто требует сборки пакетов из исходного кода.
    - **DNS:** Резолвер `musl` выполняет запросы A и AAAA параллельно. В некоторых сетевых конфигурациях (особенно в Kubernetes с `ndots:5`) это может приводить к задержкам в 5 секунд или сбоям разрешения имен.
2.  **BusyBox:**
    - Один бинарный файл, заменяющий десятки стандартных утилит (`ls`, `cp`, `grep`, `sed`).
    - Утилиты BusyBox имеют ограниченный набор флагов по сравнению с аналогами из GNU Coreutils.
3.  **Менеджер пакетов apk (Alpine Package Keeper):**
    - Быстрый и простой инструмент управления пакетами.
    - Флаг `--no-cache` позволяет устанавливать пакеты, не сохраняя индекс репозитория локально, что экономит место (не требует `rm -rf /var/cache/apk/*`).
4.  **Безопасность по умолчанию:**
    - Использование `musl` и минимальный набор пакетов снижают количество уязвимостей (CVE).
    - Все пакеты в официальных репозиториях компилируются с флагами защиты стека (Stack Smashing Protection).

### Основные команды apk

| Команда | Описание |
| :--- | :--- |
| `apk update` | Обновление индекса пакетов |
| `apk add <пакет>` | Установка пакета |
| `apk add --no-cache <пакет>` | Установка без кэширования индекса |
| `apk add --virtual .group <пакеты>` | Установка в виртуальную группу (для удаления) |
| `apk del <пакет>` | Удаление пакета |
| `apk info <пакет>` | Информация о пакете |
| `apk search <шаблон>` | Поиск пакетов |
| `apk upgrade` | Обновление всех пакетов |
| `apk fix` | Исправление сломанных зависимостей |
| `apk stats` | Статистика по пакетам |

### Ограничения и "белые пятна"

- **Отсутствие часовых поясов:** По умолчанию Alpine работает только в UTC. Для смены часового пояса требуется установка пакета `tzdata`.
- **Локализация:** Поддерживается только UTF-8. Сложные локали (например, для специфического форматирования дат) требуют отдельной настройки.
- **Отсутствие bash:** По умолчанию используется оболочка `ash`. Если скрипт требует `bash`, его необходимо установить явно (`apk add bash`).
- **Проблема PID 1:** Как и любой контейнер, Alpine требует корректной обработки сигналов (использование `tini` или `dumb-init` рекомендуется для сложных приложений).
- **Отсутствие `apt`:** В Alpine используется `apk`, а не `apt`/`apt-get`. Команды из Debian/Ubuntu-скриптов не будут работать без модификации.
- **Пути к библиотекам:** Системные библиотеки находятся в `/lib` и `/usr/lib`, а не в `/lib64` (как в glibc-системах). Это может влиять на скрипты, которые жёстко указывают пути.

## Переменные окружения

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `TZ` | Часовой пояс (POSIX). Требует `tzdata`. | `TZ=Europe/Moscow` |
| `LANG` | Локаль по умолчанию. Alpine поддерживает UTF-8. | `LANG=C.UTF-8` |
| `LC_ALL` | Перезаписывает все LC-переменные. | `LC_ALL=C.UTF-8` |
| `PYTHONUNBUFFERED` | Отключение буферизации stdout/stderr в Python. | `PYTHONUNBUFFERED=1` |
| `NODE_ENV` | Среда выполнения Node.js. | `NODE_ENV=production` |
| `GPG_KEY` | Ключ GPG для верификации подписи (в официальных образах Python). | — |
| `HOME` | Домашняя директория пользователя. В Alpine: `/root`. | — |

## Практические сценарии

### Сценарий 1: Оптимизированная сборка (виртуальные пакеты)

Использование механизма `--virtual` для установки зависимостей сборки и их удаления в одном слое.

```dockerfile
FROM python:3.13-alpine

WORKDIR /app
COPY requirements.txt .

# Группируем зависимости сборки в виртуальный пакет .build-deps
RUN apk add --no-cache --virtual .build-deps \
        gcc \
        musl-dev \
        postgresql-dev \
    && pip install --no-cache-dir -r requirements.txt \
    # Удаляем всю группу зависимостей одной командой
    && apk del .build-deps \
    # Устанавливаем только рантайм-библиотеки
    && apk add --no-cache libpq

COPY . .
CMD ["python", "app.py"]
```

### Сценарий 2: Настройка часового пояса и non-root пользователя

Безопасная конфигурация для продакшн-окружения.

```dockerfile
FROM alpine:3.21

# Установка часового пояса и создание пользователя
RUN apk add --no-cache tzdata \
    && cp /usr/share/zoneinfo/Europe/Moscow /etc/localtime \
    && echo "Europe/Moscow" > /etc/timezone \
    && apk del tzdata \
    && adduser -D appuser

USER appuser
WORKDIR /home/appuser

# ... копирование приложения ...
```

### Сценарий 3: Использование в Multi-stage сборках

Alpine — идеальный выбор для финальной стадии (Runtime), когда сборка производилась в тяжелом образе.

```dockerfile
# Stage 1: Build (используем образ с glibc для компиляции)
FROM golang:1.24-bookworm AS builder
WORKDIR /app
COPY . .
# Важно: для работы в Alpine бинарник должен быть статически слинкован или собран без CGO
RUN CGO_ENABLED=0 go build -o myapp .

# Stage 2: Runtime (минимальный Alpine)
FROM alpine:3.21
RUN apk add --no-cache ca-certificates
COPY --from=builder /app/myapp /usr/local/bin/myapp
ENTRYPOINT ["myapp"]
```

### Сценарий 4: Node.js приложение с нативными зависимостями

Сборка Node.js приложения, которая использует нативные модули (sharp, bcrypt) в Alpine.

```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app

# Установка зависимостей сборки для нативных модулей
RUN apk add --no-cache \
    python3 \
    make \
    g++

COPY package.json package-lock.json ./
RUN npm ci --production

# Stage 2: Runtime
FROM node:22-alpine
RUN apk add --no-cache tini
WORKDIR /app

COPY --from=builder /app/node_modules ./node_modules
COPY . .

USER node
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]
```

### Сценарий 5: Кэширование apk пакетов (BuildKit)

Использование Cache Mounts для ускорения повторных установок пакетов.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21

# Кэшируем индекс apk между сборками
RUN --mount=type=cache,target=/var/cache/apk \
    --mount=type=cache,target=/etc/apk/cache \
    apk update && \
    apk add --no-cache \
        curl \
        nginx \
        openssl

CMD ["nginx", "-g", "daemon off;"]
```

### Сценарий 6: Доступ к приватным Git-репозиториям (SSH)

Клонирование приватного репозитория в Alpine контейнере с использованием SSH-агента.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21

RUN apk add --no-cache git openssh-client

# Подключаем SSH-агент хоста
RUN --mount=type=ssh \
    mkdir -p /root/.ssh && \
    apk add --no-cache openssh-client && \
    git clone git@github.com:private/repo.git /app

WORKDIR /app
CMD ["sh"]
```

```bash
# Запуск сборки с пробросом SSH-агента
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa
docker buildx build --ssh default=$SSH_AUTH_SOCK -t app:latest .
```

### Сценарий 7: Безопасный запуск с read-only filesystem

Alpine-контейнер с минимальными правами для hardened-окружений.

```dockerfile
FROM alpine:3.21

RUN apk add --no-cache nginx && \
    mkdir -p /tmp/nginx && \
    chown -R nginx:nginx /tmp/nginx && \
    chmod 755 /tmp/nginx

# Конфигурация nginx для работы в read-only fs
RUN sed -i 's|/var/log/nginx|/tmp/nginx|g' /etc/nginx/nginx.conf && \
    sed -i 's|/var/run/nginx.pid|/tmp/nginx.pid|g' /etc/nginx/nginx.conf && \
    sed -i 's|/var/cache/nginx|/tmp/nginx|g' /etc/nginx/nginx.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

```bash
docker run --read-only --tmpfs /tmp --tmpfs /var/run -p 80:80 nginx-alpine
```

### Сценарий 8: Настройка DNS для обхода проблем с musl

Решение проблемы параллельного резолвинга musl в Kubernetes.

```dockerfile
FROM alpine:3.21

# Настройка DNS-резолвера для последовательного резолвинга
RUN echo "options ndots:2 timeout:2 attempts:1" >> /etc/resolv.conf

RUN apk add --no-cache curl
CMD ["sh", "-c", "while true; do curl -s http://api-service > /dev/null; sleep 10; done"]
```

Альтернативный подход — использовать `glibc`-совместимый слой:

```dockerfile
FROM alpine:3.21
RUN apk add --no-cache alpine-glibc
# Теперь glibc-приложения и резолвер работают стандартно
```

## Сравнение: Alpine vs Slim

| Критерий | Alpine (`-alpine`) | Slim (`-slim`) |
| :--- | :--- | :--- |
| **База** | Alpine Linux (`musl`) | Debian/Ubuntu (`glibc`) |
| **Размер** | ~5-10 МБ | ~30-80 МБ |
| **Совместимость** | Низкая (требует внимания к libc) | Высокая (стандарт индустрии) |
| **Скорость сборки** | Медленная (если нужна компиляция) | Высокая (готовые бинарники) |
| **DNS** | Параллельные A/AAAA запросы | Последовательные (обычно) |
| **Пакетный менеджер** | `apk` | `apt` / `apt-get` |
| **Пакеты** | ~13000 | ~60000+ |

**Когда выбирать Slim:**
- При использовании сложных Python-библиотек (Pandas, Scikit-learn, TensorFlow).
- В Java/Node.js приложениях с нативными аддонами, требующими `glibc`.
- Если время сборки критичнее финального размера образа на 50 МБ.
- Когда используются системы сборки, которые предполагают наличие `apt` (CMake, макросы).

**Когда выбирать Alpine:**
- Когда критичен минимальный размер образа (edge computing, IoT, серверless).
- Для simple приложений без нативных зависимостей (Go, Rust — статическая линковка).
- Когда безопасность приоритетнее совместимости (最小 поверхность атаки).

## Интеграция в CI/CD

### GitHub Actions

```yaml
name: Build Alpine Image
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: myorg/app:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64,linux/arm64
```

### GitLab CI

```yaml
build-alpine:
  stage: build
  image: docker:27
  services:
    - docker:29.8-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker buildx create --use
    - docker buildx build \
        --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache \
        --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max \
        --push -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
```

### Jenkins Pipeline

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh '''
                    docker buildx build \
                      --cache-from type=local,src=/tmp/.buildx-cache \
                      --cache-to type=local,dest=/tmp/.buildx-cache,mode=max \
                      --load -t myapp:${BUILD_NUMBER} .
                '''
            }
        }
        stage('Test') {
            steps {
                sh "docker run --rm myapp:${BUILD_NUMBER} sh -c 'apk list --installed'"
            }
        }
    }
}
```

## Разрешение проблем

### Типичные ошибки

**1. `exec format error` или `not executable`**

Причина: Попытка запуска образа, собранного для другой архитектуры (например, ARM-образ на x86).

Решение:

```bash
# Проверка архитектуры образа
docker inspect --format '{{.Architecture}}' myimage:latest

# Сборка для правильной платформы
docker buildx build --platform linux/amd64 -t myimage:latest .
```

**2. `apk: command not found`**

Причина: Запуск не-Alpine образа с Debian/Ubuntu-командами или наоборот.

Решение:

```bash
# Проверка ОС в контейнере
docker run --rm myimage:latest cat /etc/os-release

# В Alpine:
apk add --no-cache <package>

# В Debian/Ubuntu:
apt-get update && apt-get install -y <package>
```

**3. `ERROR: unable to select packages: <package> (no such package)`**

Причина: Пакет отсутствует в репозитории или неправильно написано имя.

Решение:

```bash
# Поиск пакета
docker run --rm alpine:3.21 apk search --no-cache <keyword>

# Проверка доступных репозиториев
docker run --rm alpine:3.21 cat /etc/apk/repositories

# Обновление индекса
docker run --rm alpine:3.21 sh -c "apk update && apk add <package>"
```

**4. `Error relocating: undefined symbol`**

Причина: Запуск бинарника, скомпилированного под `glibc`, в Alpine (`musl`).

Решение: Пересоберите приложение в Alpine или используйте `glibc`-совместимый слой:

```dockerfile
FROM alpine:3.21
RUN apk add --no-cache alpine-glibc
# Теперь glibc-приложения работают
```

Подробнее: [Устранение несовместимости libc](../Docker_troubleshooting/alpine_glibc_compatibility.md)

**5. Медленный DNS-резолв (5 секунд задержки)**

Причина: Параллельные A/AAAA запросы musl в сетях с ограниченной поддержкой IPv6.

Решение:

```dockerfile
# Настройка resolv.conf для последовательного резолвинга
RUN echo "options single-request-reopen timeout:2 attempts:1" >> /etc/resolv.conf
```

Или в Kubernetes:

```yaml
apiVersion: v1
kind: Pod
spec:
  dnsConfig:
    options:
      - name: single-request-reopen
      - name: timeout
        value: "2"
```

**6. `standard_init_linux.go: exec process caused: no space left on device`**

Причина: Дисковое пространство заполнено (особенно в CI/CD).

Решение:

```bash
# Очистка неиспользуемых образов
docker system prune -a --volumes

# Проверка использования диска
docker system df
```

### Диагностические команды

```bash
# Проверка размера контейнера
docker ps -s

# Просмотр слоёв образа
docker history myimage:latest

# Анализ размера с dive (инструмент)
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  wagoodman/dive myimage:latest

# Проверка содержимого образа
docker run --rm --entrypoint sh myimage:latest -c "ls -la /etc/apk/"

# Проверка зависимостей пакета
docker run --rm alpine:3.21 apk info --no-cache --depends <package>
```

## Лучшие практики

### Структура Dockerfile

```dockerfile
# 1. Всегда указывайте конкретную версию (не latest)
FROM alpine:3.21

# 2. Обновление пакетов перед установкой
RUN apk update && apk add --no-cache \
    curl \
    ca-certificates \
    tini

# 3. Multi-stage для сборки
FROM golang:1.24-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /bin/app .

FROM alpine:3.21
COPY --from=builder /bin/app /app
ENTRYPOINT ["/app"]
```

### Рекомендации

1. **Используйте конкретные версии** (`alpine:3.21`, а не `alpine:latest`) для воспроизводимости.
2. **Объединяйте RUN-команды** для минимизации количества слоёв и размера образа.
3. **Удаляйте ненужные пакеты** после сборки (виртуальные пакеты через `--virtual`).
4. **Используйте `--no-cache`** при установке пакетов для экономии места.
5. **Для приложений с нативными зависимостями** рассмотрите Slim или multi-stage.
6. **Включайте `tini`** как PID 1 для корректной обработки сигналов.
7. **Настройка DNS** в Kubernetes для обхода проблем с musl.
8. **Используйте `.dockerignore`** для исключения `.git`, `node_modules`, `__pycache__` и др.

### Очистка

```bash
# Удаление неиспользуемых образов
docker image prune -a

# Удаление неиспользуемых контейнеров
docker container prune

# Полная очистка (включая volumes)
docker system prune -a --volumes

# Проверка использования диска
docker system df
```

## Известные проблемы и ограничения

### Проблемы совместимости

- **Python wheels:** Многие Python-библиотеки (NumPy, Pandas, SciPy) не предоставляют pre-built wheels для Alpine. Это требует компиляции из исходного кода, что значительно увеличивает время сборки и размер образа.
- **Node.js нативные модули:** Модули типа `sharp`, `bcrypt`, `sqlite3` требуют нативной компиляции. Используйте `node:22-alpine` с установленными `python3`, `make`, `g++`.
- **Java:** JVM-приложения требуют `glibc` для работы с JNA/JNI. Используйте `eclipse-temurin:*-alpine` (содержит glibc-слой).

### Ограничения производительности

- **Компиляция:** Сборка из исходного кода в Alpine значительно медленнее, чем установка готовых бинарников в Debian/Ubuntu. Для приложений, где время сборки критично, рассмотрите Slim.
- **DNS:** Параллельный резолвер musl может вызывать задержки в сетях с проблемами IPv6. Решение: настройка `resolv.conf` или `dnsConfig` в Kubernetes.
- **BusyBox утилиты:** Ограниченный набор флагов по сравнению с GNU Coreutils. Для сложных shell-скриптов может потребоваться `apk add coreutils`.

### Устаревшие функции

- **Alpine 3.15, 3.16, 3.17** — EOL. Не используйте в production.
- **`apk add --repository`** — устаревший способ добавления сторонних репозиториев. Используйте файл `/etc/apk/repositories`.

## См. также

- **[Устранение несовместимости libc](../Docker_troubleshooting/alpine_glibc_compatibility.md)** — запуск glibc-приложений в Alpine.
- **[Сравнение Glibc и Musl](../../Linux/Core/glibc_vs_musl.md)** — глубокий технический разбор различий.
- **[Диагностика DNS в контейнерах](../../Linux/Diagnostics/Networking/dns/container_diagnostics.md)** — решение проблем с резолвом.