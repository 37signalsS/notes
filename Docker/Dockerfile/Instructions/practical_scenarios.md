# Инструкции Dockerfile: Практические сценарии переопределения

## Определения

**Переопределение инструкций (Instruction Overriding)** — процесс замещения параметров, определенных в `Dockerfile`, во время сборки образа или запуска контейнера. Это позволяет использовать один и тот же образ для разных окружений (dev, staging, prod), адаптируя его поведение без пересборки.

**Иерархия приоритетов (Precedence)** — строгий порядок применения настроек. Внешние параметры (флаги CLI) всегда имеют наивысший приоритет, перекрывая значения из конфигурационных файлов (Compose) и самого `Dockerfile`.

**Инструкции Dockerfile, поддерживающие переопределение** — прямое изменение параметров инструкций через флаги `docker run` или директивы Docker Compose. К ним относятся: `CMD`, `ENTRYPOINT`, `ENV`, `USER`, `WORKDIR`, `VOLUME`, `HEALTHCHECK`, `STOPSIGNAL`.

## Предварительные требования

- **Docker** версии 20.10 или новее (для поддержки `--env-file`, `--user`, `--workdir`, `--no-healthcheck`).
- **Docker Compose** версии 2.x (для поддержки `compose.override.yml` и мультистейджинга).
- Знание базовых инструкций Dockerfile: `CMD`, `ENTRYPOINT`, `ENV`, `ARG`, `USER`, `WORKDIR`, `VOLUME`, `HEALTHCHECK`, `STOPSIGNAL`.
- Понимание разницы между **shell-form и exec-form** для `CMD` и `ENTRYPOINT`.

## Основные концепции

### Классификация переопределений

| Тип | Время | Механизм | Влияние на образ | Примеры инструкций |
| :--- | :--- | :--- | :--- | :--- |
| **Сборка (Build-time)** | Этап `docker build` | `--build-arg` | Да (изменяет образ) | `ARG` |
| **Выполнение (Runtime)** | Этап `docker run` | Флаги CLI / Compose | Нет (только текущий контейнер) | `CMD`, `ENTRYPOINT`, `ENV`, `USER`, `WORKDIR`, `VOLUME`, `HEALTHCHECK`, `STOPSIGNAL` |

### Сводная таблица Runtime-переопределений

| Инструкция | Флаг `docker run` | Директива Compose | Влияние на образ |
| :--- | :--- | :--- | :--- |
| **`CMD`** | `[аргументы]` в конце | `command:` | Полная замена |
| **`ENTRYPOINT`** | `--entrypoint` | `entrypoint:` | Сбрасывает оригинальный `CMD` |
| **`ENV`** | `-e`, `--env`, `--env-file` | `environment:`, `env_file:` | Добавление или замена |
| **`USER`** | `-u`, `--user` | `user:` | Переопределение UID/GID |
| **`WORKDIR`** | `-w`, `--workdir` | `working_dir:` | Смена текущей директории |
| **`VOLUME`** | `-v`, `--mount`, `--tmpfs` | `volumes:`, `tmpfs:` | Переопределение типа тома |
| **`HEALTHCHECK`** | `--no-healthcheck` | `healthcheck: disable: true` | Отключение проверки |
| **`STOPSIGNAL`** | `--stop-signal`, `--stop-timeout` | `stop_signal:`, `stop_grace_period:` | Смена сигнала / таймаута |

### Иерархия приоритетов переменных (от высшего к низшему)

1.  Флаги командной строки (`docker run -e VAR=val`).
2.  Секция `environment` в `compose.yaml`.
3.  Файлы переменных (`env_file`) в `compose.yaml`.
4.  Переменные окружения хоста (см. ниже).
5.  Инструкция `ENV` в `Dockerfile`.
6.  Значения по умолчанию в приложении.

> **Важно:** Docker Compose также учитывает файл `.env` (корневой файл переменных). Приоритет: `docker run -e` > `compose.yml environment:` > `env_file:` > хостные переменные > `.env` файл > `ENV` в Dockerfile.

**Взаимодействие с ARG и ENV:**
- `ARG` доступен только во время сборки и может быть переопределён через `--build-arg`.
- `ENV` доступен и во время сборки, и во время выполнения. Может быть переопределён через `-e` / `--env`.
- При переопределении `ENV` через `-e` значение **добавляется** или **заменяется**, но не удаляется.

### Переопределение в Docker Compose vs CLI

| Контекст | Флаги CLI | Compose-директива | Примечание |
| :--- | :--- | :--- | :--- |
| **CMD** | `docker run img cmd args` | `command: [cmd, args]` | Полная замена |
| **ENTRYPOINT** | `docker run --entrypoint /bin/sh img` | `entrypoint: /bin/sh` | Сбрасывает CMD |
| **ENV** | `docker run -e VAR=val img` | `environment: VAR: val` | Добавление/замена |
| **USER** | `docker run -u 1000:1000 img` | `user: "1000:1000"` | UID/GID контейнера |
| **WORKDIR** | `docker run -w /app img` | `working_dir: /app` | Текущая директория |
| **VOLUME** | `docker run -v /host:/cont img` | `volumes: - /host:/cont` | Тип тома |
| **HEALTHCHECK** | `docker run --no-healthcheck img` | `healthcheck: disable: true` | Только отключение |
| **STOPSIGNAL** | `docker run --stop-signal SIGQUIT img` | `stop_signal: SIGQUIT` | Сигнал остановки |
## Практические сценарии

### Сценарий 1: Взаимодействие ENTRYPOINT и CMD

Переопределение `ENTRYPOINT` через `--entrypoint` автоматически удаляет аргументы из `CMD`. Детали, все комбинации и примеры: **[Инструкции Dockerfile: CMD, ENTRYPOINT и USER](./runtime_execution.md#взаимодействие-entrypoint-и-cmd)**.

### Сценарий 2: Динамическое изменение USER (Numerical UID)

Переопределение пользователя полезно при монтировании томов (Volumes), чтобы UID внутри контейнера совпадал с UID владельца папки на хосте.

```bash
# Запуск от имени текущего пользователя хоста (Linux)
docker run -u $(id -u):$(id -g) -v /data:/data my-app

# Запуск от имени конкретного пользователя
docker run -u 1001:1001 my-app id  # → uid=1001 gid=1001

# Запуск от имени группы (без конкретного пользователя)
docker run -u :1001 my-app id  # → uid=root gid=1001
```

*Примечание: Если пользователь с таким UID не существует в /etc/passwd контейнера, многие утилиты могут работать некорректно (например, не резолвить домашнюю директорию).*

**Docker Compose:**
```yaml
services:
  app:
    image: my-app
    user: "1001:1001"
    volumes:
      - ./data:/app/data  # UID владельца ./data должен совпадать с 1001
```

**Проверка:**
```bash
# Проверить, какой пользователь запускает процесс
docker exec my-container ps aux
docker exec my-container id
docker exec my-container whoami
```

### Сценарий 3: Переопределение VOLUME на Bind Mount

Инструкция `VOLUME` в Dockerfile резервирует место, но не привязывает его к хосту. Runtime-переопределение через `-v` или `--mount` делает данные доступными вне контейнера.

```bash
# Переопределение анонимного тома на папку разработки с горячей перезагрузкой
docker run -v $(pwd)/src:/app/src my-node-app

# Переопределение именованного тома на bind mount
docker run -v mydata:/app/data my-db  # Именованный том
docker run -v /host/data:/app/data my-db  # Bind mount

# Использование --mount (более явный синтаксис)
docker run --mount type=bind,source=$(pwd)/src,target=/app/src my-node-app

# Тип тома:只读 (read-only)
docker run -v /host/config:/app/config:ro my-app
docker run --mount type=bind,source=/host/config,target=/app/config,readonly my-app
```

**Влияние инструкции VOLUME:**
```dockerfile
# VOLUME в Dockerfile создаёт анонимный том
VOLUME /app/data

# Переопределение через docker run
docker run -v /host/data:/app/data my-app  # Данные хоста доступны

# Если VOLUME есть в Dockerfile, но bind mount не указан — создаётся анонимный том
# Данные НЕ будут потеряны при перезапуске, но НЕ будут доступны с хоста
```

### Сценарий 4: Глубокая настройка HEALTHCHECK

В Docker Compose можно не только отключить проверку, но и изменить её параметры без изменения образа.

```yaml
services:
  db:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  web:
    image: my-app
    depends_on:
      db:
        condition: service_healthy
```

**CLI-переопределение:**
```bash
# Отключение healthcheck (полезно для отладки)
docker run --no-healthcheck my-app

# Проверка статуса healthcheck
docker inspect --format='{{json .State.Health}}' my-container | jq

# Просмотр логов healthcheck
docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' my-container
```

**Наследование в multi-stage:**
```dockerfile
# Стадия 1: без HEALTHCHECK
FROM node:22 AS builder
RUN npm run build

# Стадия 2: с HEALTHCHECK (наследует NONE от базового образа)
FROM node:22-slim
HEALTHCHECK --interval=30s --timeout=3s CMD curl -f http://localhost:3000/health || exit 1
COPY --from=builder /app/dist /app/dist
```

### Сценарий 5: Современные рантаймы (GPU, Wasm, CDI)

Современный Docker (2025+) позволяет переопределять среду выполнения для доступа к специфическому оборудованию.

```bash
# Использование CDI (Container Device Interface) для GPU (заменяет устаревший --gpus)
docker run --device nvidia.com/gpu=all my-ml-app

# Запуск WebAssembly модуля через специфический рантайм
docker run --runtime=io.containerd.wasmer.v1 my-wasm-app

# Проброс устройства хоста
docker run --device /dev/video0:/dev/video0 my-video-app

# Использование capabilities
docker run --cap-add=NET_ADMIN my-network-app
docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE my-web-app
```

GPU-нагрузки (выбор CUDA base image, CDI, multi-stage ML, Triton, MIG) — подробно в **[GPU и ML-нагрузки в Dockerfile](../dockerfile-gpu-ml.md)**.

### Сценарий 6: Использование Compose Overrides

Паттерн `compose.yaml` + `compose.override.yml` — это стандарт де-факто для локальной разработки.

**compose.yaml (базовый):**
```yaml
services:
  web:
    image: my-app:prod
    environment:
      NODE_ENV: production
```

**compose.override.yml (локальный):**
```yaml
services:
  web:
    build: . # Переопределяем образ на локальную сборку
    environment:
      NODE_ENV: development
    ports:
      - "3000:3000"
```

**compose.prod.yml (продакшен):**
```yaml
services:
  web:
    image: my-app:v1.2.3
    environment:
      NODE_ENV: production
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 1G
```

**Использование:**
```bash
# Автоматическое наложение compose.override.yml
docker compose up -d

# Явное указание файлов для продакшена
docker compose -f compose.yml -f compose.prod.yml up -d

# Просмотр итоговой конфигурации
docker compose config
```

### Сценарий 7: Переопределение ARG через --build-arg

`ARG` определяет переменные сборки, которые могут быть переопределены через `--build-arg` при запуске `docker build`.

**Dockerfile:**
```dockerfile
ARG NODE_VERSION=22
ARG DEBIAN_FRONTEND=noninteractive

FROM node:${NODE_VERSION}-alpine
ARG APP_ENV=production
ENV NODE_ENV=${APP_ENV}

RUN echo "Building for: ${APP_ENV}"
```

**Переопределение:**
```bash
# Использование значения по умолчанию
docker build -t myapp .

# Переопределение через --build-arg
docker build --build-arg NODE_VERSION=20 --build-arg APP_ENV=development -t myapp-dev .

# Использование переменных окружения хоста
export BUILD_VERSION=1.2.3
docker build --build-arg BUILD_VERSION=${BUILD_VERSION} -t myapp .
```

**Множественные --build-arg:**
```bash
docker build \
  --build-arg NODE_VERSION=20 \
  --build-ARG APP_ENV=development \
  --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  -t myapp .
```

**Обязательные ARG (без значений по умолчанию):**
```dockerfile
ARG REGISTRY_URL
ARG API_KEY

# Без --build-arg сборка упадёт
# docker build -t myapp .  # ОШИБКА: missing required argument
docker build --build-arg REGISTRY_URL=registry.example.com --build-arg API_KEY=xxx -t myapp .
```

### Сценарий 8: Переопределение WORKDIR через -w

Флаг `-w` (или `--workdir`) позволяет сменить текущую директорию контейнера без изменения образа.

```bash
# Просмотр текущей директории
docker run myapp pwd  # → /app (из Dockerfile)

# Смена директории на время запуска
docker run -w /tmp myapp pwd  # → /tmp

# Использование для отладки
docker run -w /app/src myapp ls -la

# Комбинация с -v для доступа к файлам
docker run -w /app -v $(pwd)/src:/app/src myapp npm run dev
```

**Docker Compose:**
```yaml
services:
  app:
    image: myapp
    working_dir: /app  # Переопределяет WORKDIR из Dockerfile
    volumes:
      - ./src:/app/src
```

### Сценарий 9: Переопределение STOPSIGNAL

`--stop-signal` позволяет изменить сигнал, который Docker отправит процессу при остановке контейнера.

```bash
# Использование SIGQUIT вместо SIGTERM (для graceful shutdown)
docker run --stop-signal SIGQUIT my-web-server

# Переопределение в Docker Compose
docker compose up -d
# В compose.yml:
# services:
#   web:
#     stop_signal: SIGQUIT
#     stop_grace_period: 30s
```

**Примеры для разных приложений:**
```bash
# Nginx: graceful shutdown через SIGQUIT
docker run --stop-signal SIGQUIT nginx

# PostgreSQL: быстрая остановка через SIGINT
docker run --stop-signal SIGINT postgres

# Custom приложение: SIGUSR1 для graceful shutdown
docker run --stop-signal SIGUSR1 my-custom-app
```

**Docker Compose:**
```yaml
services:
  web:
    image: nginx
    stop_signal: SIGQUIT
    stop_grace_period: 30s

  db:
    image: postgres
    stop_signal: SIGINT
    stop_grace_period: 60s
```

### Сценарий 10: Переопределение CMD через docker run

Флаг `docker run` с аргументами заменяет CMD из Dockerfile, но сохраняет ENTRYPOINT.

**Dockerfile:**
```dockerfile
FROM python:3.12-slim
ENTRYPOINT ["python", "-m"]
CMD ["http.server", "8000"]
```

**Переопределение:**
```bash
# Запуск по умолчанию: python -m http.server 8000
docker run myapp

# Замена CMD на другой модуль: python -m http.server 9090
docker run myapp http.server 9090

# Замена CMD на flake8: python -m flake8
docker run myapp flake8 /app
```

**Полная замена ENTRYPOINT + CMD:**
```bash
# Запуск bash вместо python
docker run --entrypoint /bin/bash myapp

# Запуск flake8 с аргументами
docker run --entrypoint flake8 myapp /app --max-line-length=120
```

### Сценарий 11: Переопределение ENV через --env-file

Флаг `--env-file` позволяет передать несколько переменных из файла, что удобно для CI/CD.

**env.list:**
```
DATABASE_URL=postgres://db:5432/mydb
REDIS_URL=redis://cache:6379
API_KEY=secret-key-123
NODE_ENV=production
```

```bash
# Запуск с файлом переменных
docker run --env-file env.list myapp

# Комбинация с -e (переменные из CLI имеют приоритет)
docker run --env-file env.list -e NODE_ENV=development myapp

# Проверка переменных в контейнере
docker exec my-container env | grep NODE_ENV
```

**Docker Compose:**
```yaml
services:
  app:
    image: myapp
    env_file:
      - .env
      - ./config/secrets.env
    environment:
      - NODE_ENV=development  # Переопределяет из .env
```
### Сценарий 12: Отладка контейнера с переопределёнными инструкциями

При отладке часто нужно запустить контейнер с альтернативными инструкциями, чтобы проверить поведение без пересборки образа.

```bash
# Запуск bash вместо основного процесса
docker run -it --rm --entrypoint /bin/bash myapp

# Запуск с другим пользователем для проверки прав
docker run -it --rm -u 1000:1000 --entrypoint /bin/sh myapp -c "ls -la /app"

# Запуск с отключённым healthcheck для отладки
docker run -it --rm --no-healthcheck myapp

# Запуск с другими переменными окружения
docker run -e DEBUG=true -e LOG_LEVEL=trace myapp

# Запуск в изолированной сети для проверки зависимостей
docker run --rm --network none myapp ping google.com  # Должно упасть
```

### Сценарий 13: Мультистейджинг с переопределением в Compose

Использование нескольких Compose-файлов для разных окружений (dev, staging, prod) с переопределением инструкций.

**compose.yml (базовая логика):**
```yaml
services:
  app:
    build: .
    environment:
      APP_ENV: production
      LOG_LEVEL: info
    ports:
      - "8080:8080"
```

**compose.override.yml (локальная разработка):**
```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile.dev
    environment:
      APP_ENV: development
      LOG_LEVEL: debug
    ports:
      - "3000:3000"
    volumes:
      - ./src:/app/src
    user: "${UID:-1000}:${GID:-1000}"
```

**compose.staging.yml:**
```yaml
services:
  app:
    image: myapp:staging
    environment:
      APP_ENV: staging
      LOG_LEVEL: warn
    ports:
      - "8080:8080"
    deploy:
      replicas: 2
```

**Использование:**
```bash
# Локальная разработка (автоматически подхватывает compose.override.yml)
docker compose up -d

# Стейджинг
docker compose -f compose.yml -f compose.staging.yml up -d

# Продакшен
docker compose -f compose.yml -f compose.prod.yml up -d

# Просмотр итоговой конфигурации
docker compose -f compose.yml -f compose.staging.yml config
```

### Сценарий 14: Переопределение VOLUME через --tmpfs

Флаг `--tmpfs` позволяет создать временное хранилище в RAM для данных, которые не должны сохраняться.

```bash
# Временное хранилище для кэша
docker run --tmpfs /tmp:rw,noexec,nosuid,size=100m myapp

# Временное хранилище для логов
docker run --tmpfs /var/log/nginx:rw,size=50m nginx

# Комбинация с volumes
docker run -v /host/data:/app/data --tmpfs /app/cache:rw,size=200m myapp
```

**Docker Compose:**
```yaml
services:
  app:
    image: myapp
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=100m
      - /var/log/nginx:rw,size=50m
```

### Сценарий 15: Переопределение в CI/CD пайплайнах

Использование `--build-arg` и `-e` в CI/CD для параметризации сборки и запуска.

**GitHub Actions:**
```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: |
          docker build \
            --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
            --build-arg GIT_SHA=${{ github.sha }} \
            --build-arg VERSION=${{ github.ref_name }} \
            -t myapp:${{ github.sha }} .

      - name: Run tests
        run: |
          docker run --rm \
            -e CI=true \
            -e NODE_ENV=test \
            -e DATABASE_URL=postgres://testdb:5432/test \
            myapp:${{ github.sha }} npm test

      - name: Deploy
        run: |
          docker run -d \
            -e APP_ENV=production \
            -e API_KEY=${{ secrets.API_KEY }} \
            -p 8080:8080 \
            --name myapp \
            myapp:${{ github.sha }}
```

**GitLab CI:**
```yaml
build:
  script:
    - docker build --build-arg VERSION=$CI_COMMIT_TAG -t myapp:$CI_COMMIT_TAG .
    - docker run --rm -e CI=true -e DATABASE_URL=$DATABASE_URL myapp:$CI_COMMIT_TAG npm test
```

## Типичные ошибки и их решение

### Ошибка 1: CMD игнорируется при использовании --entrypoint

**Проблема:** Флаг `--entrypoint` сбрасывает как `ENTRYPOINT`, так и `CMD` из Dockerfile. Подробности и решение: **[Инструкции Dockerfile: CMD, ENTRYPOINT и USER](./runtime_execution.md#ошибка-7-entrypoint-игнорируется-при-docker-run)**.

### Ошибка 2: ENV не заменяется, а добавляется

**Проблема:** Флаг `-e` добавляет переменную или заменяет значение, но не удаляет существующие переменные.

```dockerfile
ENV APP_ENV=production
ENV LOG_LEVEL=info
```

```bash
# Запуск с -e APP_ENV=development
# Результат: APP_ENV=development, LOG_LEVEL=info (LOG_LEVEL не удалён!)
```

**Решение:** Используйте `--env-file` для полной замены окружения:
```bash
# env.list содержит только нужные переменные
docker run --env-file env.list myapp
```

### Ошибка 3: UID/GID не существуют в контейнере

**Проблема:** При переопределении USER через `-u` пользователь с таким UID может не существовать в контейнере.

```bash
# Запуск от имени несуществующего пользователя
docker run -u 1001:1001 myapp
# Ошибка: `whoami` не работает, `ls -la` показывает числовые UID
```

**Решение:** Создайте пользователя в Dockerfile:
```dockerfile
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -s /bin/sh -D appuser
USER 1001
```

### Ошибка 4: VOLUME перезаписывает bind mount

**Проблема:** Инструкция `VOLUME` в Dockerfile создаёт анонимный том, который может перезаписать bind mount.

```dockerfile
VOLUME /app/data
```

```bash
# Docker игнорирует bind mount и создаёт анонимный том!
docker run -v /host/data:/app/data myapp
# Данные НЕ будут доступны в /app/data
```

**Решение:** Уберите `VOLUME` из Dockerfile и используйте только `-v` при запуске:
```dockerfile
# ПЛОХО: VOLUME предотвращает bind mount
VOLUME /app/data

# ХОРОШО: VOLUME определяет только точку монтирования
WORKDIR /app
# Bind mount будет работать при -v /host/data:/app/data
```

### Ошибка 5: --no-healthcheck не отключает HEALTHCHECK в Compose

**Проблема:** Флаг `--no-healthcheck` работает только в CLI, не в Compose.

```bash
# Работает
docker run --no-healthcheck myapp

# НЕ работает в compose.yml
# services:
#   app:
#     no-healthcheck: true  # ОШИБКА: нет такой директивы
```

**Решение:** Используйте `healthcheck: disable: true`:
```yaml
services:
  app:
    image: myapp
    healthcheck:
      disable: true  # Правильно
```

### Ошибка 6: --stop-signal не работает с shell-form CMD

**Проблема:** При shell-form CMD (без `["cmd", "arg"]`) сигнал отправляется shell, а не приложению. Детали и решение: **[Инструкции Dockerfile: CMD, ENTRYPOINT и USER](./runtime_execution.md#формы-записи-exec-против-shell)**.

### Ошибка 7: --env-file не работает с multi-line значениями

**Проблема:** Файл env.list не поддерживает многострочные значения и кавычки.

```
# ОШИБКА: многострочное значение
DATABASE_URL=postgres://user:pass
@host:5432/db

# ОШИБКА: кавычки не обрабатываются
APP_SECRET="my-secret-key"
```

**Решение:** Используйте `-e` для сложных значений или оберните в шелл:
```bash
# Простые значения в файле
DATABASE_URL=postgres://user:pass@host:5432/db

# Сложные значения через -e
docker run -e APP_SECRET="$(cat secret.txt)" myapp
```

## Лучшие практики

### Безопасность

1. **Не храните секреты в `-e` / `--env`** — они видны в `docker inspect`. Используйте `--env-file` или `--secret`.
2. **Используйте `--user`** для запуска от имени непривилегированного пользователя.
3. **Не используйте `--privileged`** в продакшене — это эквивалент root на хосте.
4. **Ограничивайте capabilities:** `docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE myapp`.

### Производительность

1. **Кэшируйте зависимости** через `--mount=type=cache` в `RUN`, а не через переопределение `WORKDIR`.
2. **Используйте `--no-install-recommends`** в `apt-get install` для уменьшения размера образа.
3. **Объединяйте команды** в один `RUN` через `&&` для уменьшения количества слоёв.

### Читаемость

1. **Используйте `compose.override.yml`** для локальной разработки — не дублируйте настройки.
2. **Документируйте все `--build-arg`** в README проекта.
3. **Используйте `docker compose config`** для проверки итоговой конфигурации.

## Граничные случаи и ограничения

### Переопределение в multi-stage builds

Переопределение `CMD` / `ENTRYPOINT` через `docker run` применяется **только к финальной стадии**. Промежуточные стадии игнорируются. Подробности: **[Инструкции Dockerfile: CMD, ENTRYPOINT и USER](./runtime_execution.md#сценарий-10-multi-stage-с-differing-uid)**.

### Переопределение в Kubernetes

Kubernetes игнорирует `HEALTHCHECK` и `STOPSIGNAL` из Dockerfile. Используйте `livenessProbe`, `readinessProbe` и `lifecycle` в манифесте Pod:

```yaml
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: myapp
    image: myapp
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "kill -SIGTERM 1"]
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
```

### Переопределение в Docker Swarm

В Docker Swarm `--build-arg` недоступен при развертывании. Образ должен быть собран заранее:

```bash
# Сборка с --build-arg
docker build --build-arg VERSION=1.2.3 -t myapp:v1.2.3 .

# Развертывание в Swarm
docker service create --name myapp myapp:v1.2.3
```

### Переопределение и кэширование

Переопределение `ENV` или `ARG` через `--build-arg` инвалидирует кэш сборки:

```bash
# Кэш сброшен из-за изменения --build-arg
docker build --build-arg VERSION=1.2.4 -t myapp .
```

**Совет:** Используйте `ARG` только для параметров, которые действительно должны меняться между сборками.

### Ограничение размера env-file

Docker не ограничивает размер файла env-file, но рекомендуется использовать файлы до 1000 переменных. Для больших конфигураций рассмотрите использование внешних секретов (Vault, AWS Secrets Manager).

## Дополнительная информация

- **[Инструкции выполнения: CMD, ENTRYPOINT и USER](./runtime_execution.md)** — архитектурные детали запуска процессов и PID 1.
- **[Сигналы и проверки здоровья: HEALTHCHECK и STOPSIGNAL](./health_signals.md)** — полная документация по настройке healthcheck и graceful shutdown.
- **[Рабочий контекст: WORKDIR и SHELL](./working_context.md)** — детали работы с рабочей директорией и оболочкой.
- **[Переменные: ENV и ARG](./environment_variables.md)** — детали работы с переменными на разных этапах.
- **[Директивы Docker Compose](../../Docker_compose/docker_compose_directives.md)** — полный справочник по YAML-синтаксизу.
- **[Безопасность в Dockerfile](../Docker_best_practices/security.md)** — почему переопределение USER важно для защиты.
