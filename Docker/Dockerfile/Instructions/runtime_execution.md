# Инструкции Dockerfile: Выполнение Команд При Запуске

## Определения

**`CMD`** — инструкция, задающая команду по умолчанию, выполняемую при запуске контейнера без аргументов.

**`ENTRYPOINT`** — инструкция, настраивающая контейнер как исполняемый файл. Аргументы из командной строки **добавляются** к ENTRYPOINT.

**`USER`** — инструкция, устанавливающая пользователя (и опционально группу) для запуска процессов в контейнере.

## Основные концепции

### CMD vs ENTRYPOINT

Обе инструкции задают команду при запуске, но работают по-разному:

- **`CMD`:** Команда по умолчанию. Если контейнер запускается с аргументами, `CMD` игнорируется.
- **`ENTRYPOINT`:** Контейнер работает как исполняемый файл. Аргументы из `docker run` **добавляются** к `ENTRYPOINT`.

**Взаимодействие:**

```dockerfile
ENTRYPOINT ["/bin/echo", "Hello"]
CMD ["world"]
```

- `docker run <image>` → `Hello world`
- `docker run <image> John` → `Hello John`

**Таблица комбинаций:**

| ENTRYPOINT | CMD | Результат |
| :--- | :--- | :--- |
| Не указано | `["exec_cmd", "p1"]` | `exec_cmd p1` |
| `["entry", "p1"]` | Не указано | `entry p1` |
| `["entry", "p1"]` | `["cmd", "p2"]` | `entry p1 cmd p2` |

> **Правило:** Dockerfile должен содержать хотя бы одну из `CMD` или `ENTRYPOINT`. В Dockerfile действует только **последняя** инструкция каждого типа.

### Формы записи: Shell vs Exec

| Форма | Синтаксис | Особенности |
| :--- | :--- | :--- |
| Shell | `CMD myapp --config prod.yaml` | Выполняется через `/bin/sh -c`. Поддерживает переменные `$VAR`. |
| Exec | `CMD ["/myapp", "--config", "prod.yaml"]` | Выполняется напрямую через `execve`. Работает в `distroless`/`scratch`. |

> ⚠️ **Важно:** В образах `gcr.io/distroless/static` и `FROM scratch` **отсутствует `/bin/sh`**. Shell-форма приведёт к ошибке.

### Передача сигналов процессу PID 1

Docker отправляет `SIGTERM` процессу с PID 1 при остановке контейнера. При использовании shell-формы сигнал получает оболочка, а не приложение.

**Решение:** использовать `exec` в скрипте-обёртке:

```bash
#!/bin/sh
echo "Starting application..."
exec "$@"  # Заменяет shell на приложение, приложение становится PID 1
```

Или использовать exec-форму в Dockerfile:

```dockerfile
ENTRYPOINT ["/app/entrypoint.sh"]
```

### Запуск в режиме Foreground

Docker отслеживает процесс PID 1. Когда он завершается — контейнер останавливается.

| Режим | Пример | Проблема |
| :--- | :--- | :--- |
| Foreground | `CMD ["nginx", "-g", "daemon off;"]` | ✅ Правильно |
| Background (daemon) | `CMD ["nginx"]` | ❌ Контейнер сразу завершится |

### Инструкция USER

**Синтаксис:**

```dockerfile
# По имени пользователя/группы
USER <user>[:<group>]

# По UID/GID
USER <UID>[:<GID>]
```

**Описание:**

- Устанавливает имя пользователя (или UID) и опционально группу (или GID)
- Применяется к последующим инструкциям `RUN` и командам `ENTRYPOINT`/`CMD` при запуске
- При указании группы пользователь имеет **только** эту принадлежность к группе
- Инструкцию `USER` можно указывать несколько раз в Dockerfile — для переключения между пользователями (например, `USER root` для установки пакетов, затем `USER app` для запуска приложения)
- По умолчанию все команды в Dockerfile выполняются от `root`, пока не указана другая инструкция `USER`

> **Важно:** Инструкция `USER` — декларативная. Она не создаёт пользователя в образе. Пользователь должен существовать в файловой системе образа. Для создания используйте `RUN useradd` или `RUN adduser`. Инструкция `RUN useradd app && USER app` избыточна — достаточно `RUN useradd app` и отдельной `USER app`.

**Предупреждения:**

- Если у пользователя нет основной группы — образ выполняется с группой `root`
- **Windows:** пользователь должен быть создан заранее (через `net user`)

**Пример безопасности:**

```dockerfile
FROM python:3
RUN useradd -m appuser
USER appuser
WORKDIR /home/appuser
CMD ["python", "app.py"]
```

## Практические сценарии

### Сценарий 1: Python-приложение

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
```

### Сценарий 2: Go-бинарник (exec form)

```dockerfile
FROM scratch
COPY app /app
ENTRYPOINT ["/app"]
```

### Сценарий 3: Nginx

```dockerfile
FROM nginx:alpine
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Сценарий 4: Скрипт-обёртка для подстановки переменных

```dockerfile
FROM alpine
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD []
```

```bash
#!/bin/sh
echo "Starting $APP_NAME"
exec "$@"
```

### Сценарий 5: Запуск от непривилегированного пользователя

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --only=production
COPY . .
RUN adduser -D nonroot
USER nonroot
EXPOSE 3000
CMD ["node", "server.js"]
```

### Сценарий 6: ENTRYPOINT с аргументами по умолчанию

```dockerfile
FROM ubuntu:22.04
ENTRYPOINT ["top", "-b"]
CMD ["-c"]
```

- `docker run my-image` → `top -b -c`
- `docker run my-image -d 1` → `top -b -d 1`

### Сценарий 7: Java-приложение с правильной обработкой сигналов

```dockerfile
FROM openjdk:17-slim
WORKDIR /app
COPY app.jar .
USER appuser
ENTRYPOINT ["java", "-jar", "app.jar"]
```

## Дополнительная информация

Подробнее о переопределении CMD/ENTRYPOINT см. **[Практические сценарии](./practical_scenarios.md)**. Об оптимизации образов (distroless, scratch) читайте в **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)**, об отладке — в **[Отладка distroless-контейнеров](../../Docker_troubleshooting/debugging_distroless.md)**.
