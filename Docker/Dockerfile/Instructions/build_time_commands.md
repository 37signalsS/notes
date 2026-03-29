# Инструкции Dockerfile: Выполнение Команд При Сборке

## Определения

**Инструкция `RUN`** — команда, выполняемая во время сборки образа, создающая новый слой в образе.

## Основные концепции

### `RUN`

Определяет команду, которая будет выполнена во время сборки образа, создавая новый слой.

#### Надёжные скрипты с `set -ex`

```dockerfile
RUN set -ex && \
    apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*
```

- `set -e`: **Exit Immediately.** Если команда завершается с ошибкой, выполнение всей инструкции прекращается.
- `set -x`: **Print Commands.** Каждая команда выводится в лог сборки для отладки.

#### Кэширование зависимостей (BuildKit)

`--mount=type=cache` позволяет монтировать кэш в процессе выполнения `RUN`. Кэш не попадает в финальный образ.

> Подробнее о кэшировании и оптимизации сборки см. **[Оптимизация сборки](../../Dockerfile/Docker_best_practices/build_optimization.md)**

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

#### Bind mounts при сборке (BuildKit)

`--mount=type=bind` монтирует директорию с хоста в контейнер во время сборки. Данные не копируются в образ.

```dockerfile
RUN --mount=type=bind,source=./src,target=/app/src \
    go build -o app ./src
```

#### Работа с секретами (BuildKit)

`--mount=type=secret` временно монтирует секрет и не хранит его в финальном образе.

> Подробнее о безопасном управлении секретами см. **[Управление секретами](../../Docker_security/secrets_management.md)**

```dockerfile
RUN --mount=type=secret,id=ssh,target=/root/.ssh/id_rsa \
    git clone git@github.com:user/repo.git .

RUN --mount=type=secret,id=api_key,target=/run/secrets/api_key \
    export API_KEY=$(cat /run/secrets/api_key) && \
    pip install --extra-index-url "$API_KEY"@private-repo.com/packages some-package
```

> **Примечание:** Для использования директив `--mount` требуется BuildKit. В современных версиях Docker (18.09+) BuildKit включён по умолчанию. Подробнее о BuildKit см. **[Dockerfile BuildKit](../dockerfile_buildkit.md)**

## Практические сценарии

### Установка пакетов с очисткой кэша

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
```

### Использование BuildKit secrets для приватных npm-пакетов

```dockerfile
# syntax=docker/dockerfile:1
FROM node:20-alpine
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm install express
```

### Кэширование pip-пакетов между сборками

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

## Дополнительная информация

- Инструкция `RUN` должна использоваться только для команд, выполняемых при сборке
- Для запуска команд при старте контейнера используйте [`CMD`](./runtime_execution.md) или [`ENTRYPOINT`](./runtime_execution.md)
- Каждая инструкция `RUN` создаёт новый слой — объединяйте команды для уменьшения количества слоёв
- Обзор всех инструкций Dockerfile см. **[Инструкции Dockerfile: Обзор](./overview_definitions.md)**
