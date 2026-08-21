# Инструкции Dockerfile: CMD, ENTRYPOINT и USER

## Определения

**`ENTRYPOINT`** — инструкция, определяющая основной исполняемый файл (процесс), который будет запущен при старте контейнера. Она фиксирует "предназначение" контейнера (например, это веб-сервер, база данных или утилита). `ENTRYPOINT`不易被 переопределена — пользователю доступно только изменение аргументов через `CMD`.

**`CMD`** — инструкция, задающая команду или аргументы по умолчанию. В комбинации с `ENTRYPOINT` она выступает в роли списка параметров, которые пользователь может легко переопределить при запуске. `CMD` предназначен для предоставления параметров по умолчанию, которые могут быть заменены при запуске контейнера.

**`USER`** — инструкция, устанавливающая идентификатор пользователя (UID) и группы (GID), от имени которых будут выполняться все последующие шаги сборки и сам процесс в рантайме. Это критический элемент безопасности для минимизации привилегий.

## Предварительные требования

Для работы с инструкциями `CMD`, `ENTRYPOINT` и `USER` необходимо:

- **Docker** версии 20.10 или новее.
- Понимание базовых концепций: **[WORKDIR и SHELL](./working_context.md)** (рабочая директория и оболочка), **[ENV и ARG](./environment_variables.md)** (подстановка переменных).
- Базовое понимание Linux-процессов: PID, сигналы (SIGTERM, SIGKILL), процессы-зомби, дерево процессов.
- Знание разницы между **shell-form** и **exec-form** — критически важное для корректной работы приложения.

## Основные концепции

### Формы записи: Exec против Shell

Выбор формы записи определяет, как процесс будет запущен и сможет ли он корректно завершить работу (**Graceful Shutdown**).

| Характеристика | Exec-форма (рекомендуется) | Shell-форма |
| :--- | :--- | :--- |
| **Синтаксис** | `ENTRYPOINT ["exec", "p1"]` | `ENTRYPOINT exec p1` |
| **Запуск** | Напрямую (`execve`) | Через `/bin/sh -c` |
| **PID 1** | Приложение получает PID 1 | Оболочка получает PID 1 |
| **Сигналы** | Получает напрямую (SIGTERM) | Игнорируются оболочкой |
| **Зомби-процессы** | Не обрабатываются (нужен init) | Обрабатываются оболочкой (частично) |
| **Переменные окружения** | Не подставляются автоматически | Подставляются через `/bin/sh` |

**Важно:** Всегда используйте **Exec-форму** (JSON-массив). В 2026 году использование Shell-формы для основных процессов считается антипаттерном, так как это блокирует проброс сигналов от оркестратора (Docker, Kubernetes) к приложению.

**Проблема с exec-form и переменными окружения:**

```dockerfile
ENV MY_VAR=hello

# Exec-form: переменная НЕ подставляется
RUN ["echo", "$MY_VAR"]  # Выведетliteral "$MY_VAR"

# Shell-form: переменная подставляется
RUN echo $MY_VAR  # Выведет "hello"

# Решение: комбинация exec-form с подстановкой через оболочку
CMD ["/bin/sh", "-c", "echo $MY_VAR && exec /app/start"]
```

### Взаимодействие ENTRYPOINT и CMD

"Золотой стандарт" Dockerfile — использование обеих инструкций одновременно. `ENTRYPOINT` задает команду, а `CMD` — её аргументы.

| ENTRYPOINT | CMD | Итоговая команда |
| :--- | :--- | :--- |
| `["python", "main.py"]` | `["--port", "80"]` | `python main.py --port 80` |
| `["/usr/bin/tini", "--"]` | `["node", "app.js"]` | `/usr/bin/tini -- node app.js` |
| `["/app/entrypoint.sh"]` | `["python", "app.py"]` | `/app/entrypoint.sh python app.py` |

**Все комбинации:**

| ENTRYPOINT | CMD | Результат |
| :--- | :--- | :--- |
| Определён | Определён | `ENTRYPOINT` + `CMD` |
| Определён | Не определён | Только `ENTRYPOINT` |
| Не определён | Определён | Только `CMD` |
| Не определён | Не определён | Ошибка или CMD из базового образа |

**Множественные инструкции:** Если в Dockerfile несколько `CMD` или `ENTRYPOINT`, применяется только **последняя** инструкция. Это может быть источником ошибок при рефакторинге:

```dockerfile
# ОШИБКА: пока ввели третий CMD, первый и второй игнорируются
CMD ["python", "app.py"]
CMD ["python", "worker.py"]  # Переопределяет первый
CMD ["python", "server.py"]  # Переопределяет второй
# Результат: запустится только server.py
```

### Инструкция USER и безопасность

Запуск от `root` (по умолчанию) является серьезной уязвимостью. Современный стандарт требует использования непривилегированных пользователей.

**Лучшие практики:**
1. **Числовые UID (>10000):** Всегда указывайте числовой идентификатор, например `USER 10001:10001`. Это критично для Kubernetes (политика `runAsNonRoot`) и Rootless Docker, так как позволяет проверять права без доступа к `/etc/passwd` внутри образа.
2. **Создание заранее:** Пользователь должен быть создан через `RUN` до вызова `USER`.
3. **BuildKit Ownership:** При использовании BuildKit инструкции `WORKDIR`, выполненные после `USER`, автоматически создают директории с правами этого пользователя.
4. **Атомарный COPY:** Используйте флаг `--chown` в инструкциях `COPY` и `ADD`, чтобы избежать создания дополнительных слоев с `chown`.

**USER и многоэтапочные сборки:**

`USER` сохраняется между стадиями multi-stage сборки:

```dockerfile
# Stage 1: сборка от root
FROM golang:1.22 AS builder
WORKDIR /build
COPY . .
RUN go build -o app

# Stage 2: runtime от непривилегированного пользователя
FROM alpine:3.21
RUN addgroup -g 10001 appgroup && adduser -u 10001 -G appgroup -s /bin/sh -D appuser
WORKDIR /app
COPY --from=builder /build/app .
USER 10001:10001
CMD ["./app"]
```

**Порядок важен:** `USER` влияет на все последующие инструкции `RUN`, `COPY`, `CMD`, `ENTRYPOINT`. Размещайте `USER` до инструкций, которые должны выполняться от непривилегированного пользователя.

### USER и именованные vs числовые идентификаторы

```dockerfile
# Именованный пользователь (рекомендуется для читаемости)
RUN addgroup -g 10001 appgroup && adduser -u 10001 -G appgroup -s /bin/sh -D appuser
USER appuser:appgroup

# Числовой UID (рекомендуется для Kubernetes/OpenShift)
USER 10001:10001

# Смешанный формат (допустимо, но менее читаемо)
USER appuser:10001
```

> **Kubernetes:** Политика `runAsNonRoot: true` требует числового UID в манифесте Pod. Использование числового `USER` в Dockerfile упрощает интеграцию.

### Решение "Проблемы PID 1"

Процесс с PID 1 в Linux является особенным: он не имеет обработчиков сигналов по умолчанию и обязан "пожинать" (reap) зомби-процессы. Большинство приложений (Node.js, Python, Java) не умеют этого делать.

**Детали проблемы:**

1. **Игнорирование сигналов:** Процесс PID 1 в Linux не имеет обработчиков сигналов по умолчанию. Если приложение не зарегистрировало обработчик `SIGTERM` явно, ядро не применит стандартное поведение "завершиться", и сигнал будет проигнорирован. Docker будет ждать 10 секунд и отправит `SIGKILL`.
2. **Накопление зомби:** Если приложение порождает дочерние процессы (например, через `subprocess` или `worker_threads`), и они завершаются, PID 1 обязан "пожинать" их. Если этого не происходит, таблица процессов переполняется.

**Способ 1: Использование tini (Рекомендуется)**

`tini` — это крошечная система инициализации (~20KB), которая берет на себя роль PID 1, пробрасывает сигналы и очищает зомби.

```dockerfile
# Установка tini (пример для Alpine)
RUN apk add --no-cache tini
# Используем tini как точку входа
ENTRYPOINT ["/sbin/tini", "--"]
# Приложение передается как аргументы CMD
CMD ["node", "server.js"]
```

**Сравнение tini, dumb-init и --init:**

| Инструмент | Встроен в Docker | Установка | Особенности |
| :--- | :--- | :--- | :--- |
| **tini** | Да (`--init`) | `apk add tini` | Стандарт для Docker, поддержка `-g` (process groups) |
| **dumb-init** | Нет | `apt-get install dumb-init` | Перезапись сигналов (например, SIGTERM→SIGQUIT для Java) |
| **--init** | Да | Не требуется | Автоматически вставляет tini как PID 1 |

**Способ 2: Встроенный флаг `--init`**

Если вы не можете изменить образ, используйте встроенную поддержку `tini` в Docker:
- CLI: `docker run --init ...`
- Compose: `init: true`

**Способ 3: exec в entrypoint-скрипте**

Если используется shell-скрипт как ENTRYPOINT, замените себя на приложение через `exec`:

```dockerfile
COPY entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
CMD ["my-app"]
```

```bash
#!/bin/bash
set -euo pipefail
# Предварительная настройка...
exec "$@"  # Заменяет shell приложением — приложение становится PID 1
```

**Способ 4: Без tini (для простых приложений)**

Однопроцессные Go-приложения без дочерних процессов могут работать без init:

```dockerfile
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/server /server
USER nonroot:nonroot
ENTRYPOINT ["/server"]
```

**Диагностика PID 1:**

```bash
# Проверка PID 1 в запущенном контейнере
docker exec mycontainer ps -p 1 -o pid,comm,args
# PID   COMMAND  COMMAND
#   1   tini     /sbin/tini -- node server.js

# Поиск зомби-процессов
docker exec mycontainer ps aux | grep -w Z
# USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
# root         7  0.0  0.0      0     0 ?        Z    10:05   0:00 [python] <defunct>
```
## Практические сценарии

### Сценарий 1: Entrypoint-скрипт с tini

Подготовка среды (миграции, проверка доступности БД) с корректной обработкой сигналов.

**Dockerfile:**
```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim
RUN apt-get update && apt-get install -y tini && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ARG UID=10001
RUN useradd -u ${UID} -m appuser
COPY --chown=appuser:appuser entrypoint.sh .
COPY --chown=appuser:appuser . .

USER ${UID}
ENTRYPOINT ["/usr/bin/tini", "--", "./entrypoint.sh"]
CMD ["python", "app.py"]
```

**entrypoint.sh:**
```bash
#!/bin/bash
set -euo pipefail

echo "Ожидание готовности БД..."
./wait-for-it.sh db:5432 --timeout=30

echo "Выполнение миграций..."
python manage.py migrate --no-input

exec "$@"
```

### Сценарий 2: Hardening образа

```dockerfile
ARG UID=10001
RUN groupadd -g ${UID} appgroup && \
    useradd -u ${UID} -g appgroup -s /sbin/nologin -M appuser

COPY --chown=${UID}:${UID} ./src /app

USER ${UID}
CMD ["./app"]
```

### Сценарий 3: Go + distroless

```dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /server .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /server /server
USER nonroot:nonroot
ENTRYPOINT ["/server"]
```

### Сценарий 4: Node.js с Worker Threads

```dockerfile
FROM node:22-alpine
RUN apk add --no-cache tini
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production
COPY src/ ./src/

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "src/server.js"]
```

**Сигнал в Node.js:**
```javascript
const http = require('http');
const server = http.createServer((req, res) => res.end('OK'));
server.listen(3000);

const shutdown = (signal) => {
  console.log(`Received ${signal}, shutting down...`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 30000);
};
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
```

### Сценарий 5: Java/Spring Boot

```dockerfile
FROM eclipse-temurin:21-jre-alpine
RUN apk add --no-cache tini
WORKDIR /app
COPY target/app.jar .

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["java", "-XX:MaxRAMPercentage=80.0", "-jar", "app.jar"]
```

### Сценарий 6: Entrypoint с trap (exec невозможен)

```bash
#!/bin/bash
set -euo pipefail
CHILD_PID=""
forward_signal() {
    if [ -n "$CHILD_PID" ]; then
        kill -"$1" "$CHILD_PID" 2>/dev/null
    fi
}
trap 'forward_signal TERM' TERM
trap 'forward_signal INT' INT
"$@" &
CHILD_PID=$!
wait $CHILD_PID
exit $?
```

### Сценарий 7: Python multiprocessing

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

USER 10001
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "multiprocessing_spawn", "app.py"]
```
### Сценарий 8: Отладка проблем с запуском

```bash
# Переопределение CMD для отладки
docker run -it --rm --entrypoint /bin/bash myimage

# Запуск команды из CMD вручную
docker run -it --rm --entrypoint python myimage -c "import app; print(app.__file__)"

# Просмотр логов завершения
docker inspect --format='{{json .State}}' <container_id> | jq

# Проверка PID 1
docker exec mycontainer ps -p 1 -o pid,comm,args
```

### Сценарий 9: ENTRYPOINT с переключением режимов

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .

ENTRYPOINT ["python", "manage.py"]
CMD ["runserver", "0.0.0.0:8000"]
```

```bash
docker run myapp                              # runserver
docker run myapp migrate                      # миграции
docker run --entrypoint /bin/bash myapp       # shell
```

### Сценарий 10: Multi-stage с differing UID

```dockerfile
FROM node:22 AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY src/ ./src/
RUN npm run build

FROM node:22-slim
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -m appuser
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json .

USER 10001:10001
EXPOSE 3000
CMD ["node", "dist/server.js"]
```

## Типичные ошибки и их решение

### Ошибка 1: Контейнер завершается сразу (exit code 0)

**Причина:** CMD не определён или нет долгоживущего процесса.

```bash
docker inspect --format='{{.Config.Cmd}}' myimage
docker inspect --format='{{.Config.Entrypoint}}' myimage
```

**Решение:** Определите долгоживущий процесс:

```dockerfile
# ПЛОХО: нет долгоживущего процесса
CMD ["echo", "hello"]

# ХОРОШО: долгоживущий процесс
CMD ["python", "app.py"]
```

### Ошибка 2: Контейнер падает с exit code 126

**Причина:** Исполняемый файл не имеет прав на выполнение.

```bash
# Диагностика
docker run --rm myimage ls -la /app/entrypoint.sh
# -rw-r--r-- 1 root root 123 ... /app/entrypoint.sh  (нет x!)
```

**Решение:**

```dockerfile
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh
```

### Ошибка 3: Контейнер падает с exit code 127

**Причина:** Исполняемый файл не найден (опечатка в пути или имени).

```bash
docker inspect --format='{{.Config.Cmd}}' myimage
# ["./appp"]  -> опечатка!
```

**Решение:** Проверьте путь и используйте абсолютные пути:

```dockerfile
# ПЛОХО: относительный путь
CMD ["./app"]

# ХОРОШО: абсолютный путь
CMD ["/app/server"]
```

### Ошибка 4: Контейнер не останавливается при docker stop (exit code 137)

**Причина:** Приложение не обрабатывает SIGTERM или обрабатывает слишком долго.

```bash
# Проверка exit code
docker inspect --format='{{.State.ExitCode}}' <container>
# 137 = 128 + 9 (SIGKILL)
```

**Решение:**

1. Добавьте обработку SIGTERM в приложение
2. Используйте tini для проброса сигналов
3. Увеличьте `stop_grace_period`:

```bash
docker stop --timeout 60 mycontainer
# Или в compose:
# stop_grace_period: 60s
```

### Ошибка 5: exec "$@" не заменяет shell

**Причина:** `exec "$@"` используется в entrypoint-скрипте, но shell не завершается.

**Диагностика:**

```bash
docker exec mycontainer ps aux
# PID 1: /bin/bash /entrypoint.sh
# PID 7: python app.py
# shell всё ещё PID 1!
```

**Решение:** Убедитесь, что `exec "$@"` — последняя команда в скрипте и что скрипт использует `#!/bin/bash` (не `#!/bin/sh` если нужен pipefail):

```bash
#!/bin/bash
set -euo pipefail
# ... настройка ...
exec "$@"  # ДОЛЖНА быть последней командой
```

### Ошибка 6: Permission Denied при запуске от USER

**Причина:** Файлы принадлежат root, а приложение запускается от другого пользователя.

```bash
docker run --rm myimage ls -la /app
# -rw-r--r-- 1 root root ... app.py  -> не может запустить от appuser
```

**Решение:** Используйте `--chown` в COPY или `chown` в RUN:

```dockerfile
COPY --chown=appuser:appgroup . .
# Или
RUN chown -R appuser:appgroup /app
```

### Ошибка 7: ENTRYPOINT игнорируется при docker run

**Причина:** Использование `--entrypoint` сбрасывает и CMD.

```bash
# ENTRYPOINT ["python", "app.py"], CMD ["--port", "80"]
docker run --entrypoint /bin/bash myimage
# Запустится ТОЛЬКО /bin/bash, app.py не будет запущен!

# Правильно: передайте CMD явно
docker run --entrypoint /bin/bash myimage -c "python /app/app.py --port 80"
```
## Лучшие практики

### Безопасность

1. **Всегда используйте непривилегированного пользователя:**

```dockerfile
RUN addgroup -g 10001 appgroup && adduser -u 10001 -G appgroup -s /bin/sh -D appuser
USER 10001:10001
```

2. **Используйте числовые UID для Kubernetes/OpenShift:**

```dockerfile
USER 10001:10001  # Не "appuser:appgroup" для совместимости с политиками
```

3. **Копируйте файлы с нужными правами:**

```dockerfile
COPY --chown=10001:10001 . .
```

### Exec-form vs Shell-form

1. **Всегда используйте exec-form для CMD/ENTRYPOINT:**

```dockerfile
# ПРАВИЛЬНО
CMD ["node", "src/server.js"]
ENTRYPOINT ["/app/start"]

# НЕПРАВИЛЬНО
CMD node src/server.js
ENTRYPOINT /app/start
```

2. **Если нужна оболочка — используйте exec с явным шеллом:**

```dockerfile
CMD ["/bin/sh", "-c", "echo $VAR && exec /app/start"]
```

### PID 1 и сигналы

1. **Используйте tini для приложений с дочерними процессами:**

```dockerfile
RUN apk add --no-cache tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "app.py"]
```

2. **Для простых Go-приложений — distroless:**

```dockerfile
FROM gcr.io/distroless/static-debian12:nonroot
ENTRYPOINT ["/server"]
```

3. **Для отладки — docker --init:**

```bash
docker run --init myapp  # Встроенный tini
```

### Entrypoint-скрипты

1. **Всегда заканчивайте exec "$@":**

```bash
#!/bin/bash
set -euo pipefail
# Предварительная настройка...
exec "$@"  # ОБЯЗАТЕЛЬНО в конце
```

2. **Для сложных сценариев — trap:**

```bash
trap 'kill -TERM $CHILD_PID' TERM INT
"$@" &
CHILD_PID=$!
wait $CHILD_PID
```

### Порядок инструкций в Dockerfile

```dockerfile
# 1. FROM
FROM node:22-alpine

# 2. SHELL (если нужен pipefail)
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# 3. WORKDIR
WORKDIR /app

# 4. Системные зависимости
RUN apk add --no-cache tini

# 5. Кэширование зависимостей
COPY package.json package-lock.json ./
RUN npm ci --production

# 6. Исходный код
COPY src/ ./src/

# 7. Пользователь (безопасность)
USER node

# 8. Entrypoint и команда
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "src/server.js"]
```

## Граничные случаи и ограничения

### CMD и ENTRYPOINT в docker commit

При создании образа через `docker commit` CMD и ENTRYPOINT **сохраняются**:

```bash
docker commit mycontainer newimage
docker inspect --format='{{json .Config.Cmd}}' newimage
# ["python", "app.py"] — сохранено
```

### CMD и ENTRYPOINT в docker export

При экспорте контейнера через `docker export` CMD и ENTRYPOINT **теряются**:

```bash
docker export mycontainer > container.tar
# CMD/ENTRYPOINT не экспортируются
```

### ENTRYPOINT и --entrypoint в docker run

Флаг `--entrypoint` сбрасывает оригинальный ENTRYPOINT и CMD:

```bash
# Dockerfile: ENTRYPOINT ["python", "app.py"], CMD ["--port", "80"]
docker run --entrypoint /bin/bash myimage
# Запустится ТОЛЬКО /bin/bash

# Правильно: передайте CMD явно
docker run --entrypoint /bin/bash myimage -c "python app.py --port 80"
```

### USER и adduser/useradd

Если пользователь не существует в контейнере, `USER` вызовет ошибку:

```dockerfile
# ПЛОХО: пользователь не создан
USER appuser  # Ошибка: unknown user

# ХОРОШО: сначала создайте пользователя
RUN adduser -D appuser
USER appuser
```

### USER и capabilities

Некоторые операции требуют root даже с USER:

```bash
# Привязка к порту <1024
docker run --cap-add=NET_BIND_SERVICE -p 80:8080 myapp

# Или используйте порты >= 1024
EXPOSE 8080
```

### CMD и signal handling в Kubernetes

Kubernetes отправляет SIGTERM процессу PID 1. Если приложение не обрабатывает его:

1. Увеличьте `terminationGracePeriodSeconds` (по умолчанию 30с)
2. Добавьте `preStop` hook для задержки:

```yaml
spec:
  terminationGracePeriodSeconds: 60
  containers:
  - name: app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 5"]
```

### ENTRYPOINT и SHELL

`SHELL` не влияет на exec-form:

```dockerfile
SHELL ["/bin/bash", "-c"]

# Shell-form: использует bash
RUN echo "Hello from bash"

# Exec-form: bash НЕ используется
RUN ["echo", "Hello directly"]
```

## Дополнительная информация

### Проверка метаданных

```bash
# Просмотр USER, ENTRYPOINT и CMD
docker inspect --format 'User: {{.Config.User}} | Entrypoint: {{json .Config.Entrypoint}} | CMD: {{json .Config.Cmd}}' <image_id>

# Просмотр всех инструкций образа
docker history <image_id> --no-trunc
```

### Иерархия переопределения

1. Флаг `--entrypoint` переопределяет `ENTRYPOINT` из Dockerfile.
2. Аргументы в конце команды `docker run <image> [args]` переопределяют `CMD`.
3. Параметры `command:` и `entrypoint:` в Docker Compose переопределяют соответствующие инструкции образа.
4. Параметры в Kubernetes манифесте (`command`, `args`, `securityContext.runAsUser`) переопределяют Dockerfile.

**См. также:**
- **[Практические сценарии переопределения](./practical_scenarios.md)** — детальный разбор runtime-параметров.
- **[Инструкция WORKDIR](./working_context.md)** — взаимодействие с правами пользователя.
- **[Безопасность в Dockerfile](../Docker_best_practices/security.md)** — глубокий аудит привилегий.
- **[Инструкция STOPSIGNAL](./health_signals.md#сигнал-остановки-stopsignal)** — настройка сигналов для Graceful Shutdown.
- **[Выполнение приложений в контейнере](../Docker_best_practices/container_execution.md)** — паттерны multi-process, Graceful Shutdown, OOM.
- **[Коды завершения контейнеров](../../Docker_troubleshooting/docker_exit_codes.md)** — справочник по exit code (137, 143 и др.).
