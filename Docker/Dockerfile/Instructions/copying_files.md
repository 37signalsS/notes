# Инструкции Dockerfile: Копирование Файлов

## Определения

**Инструкция `COPY`** — копирует файлы и директории из контекста сборки в файловую систему образа.

**Инструкция `ADD`** — расширенная версия `COPY` с дополнительными возможностями (загрузка по URL, автоматическая распаковка архивов, клонирование Git-репозиториев).

**Контекст сборки** — набор файлов и директорий, передаваемых демону Docker перед сборкой.

## Основные концепции

### Синтаксис

**COPY:**

```dockerfile
COPY [OPTIONS] <src> ... <dest>
COPY [OPTIONS] ["<src>", ... "<dest>"]
```

**ADD:**

```dockerfile
ADD [OPTIONS] <src> ... <dest>
ADD [OPTIONS] ["<src>", ... "<dest>"]
```

### Флаги инструкций

**COPY — доступные опции:**

| Опция | Мин. версия | Описание |
| :--- | :--- | :--- |
| `--from` | — | Копировать из стадии сборки, контекста или образа |
| `--chmod` | 1.2 | Установить права доступа (octal: `755`, symbolic: `+x`) |
| `--chown` | — | Установить владельца (`user:group`) |
| `--link` | 1.4 | Копировать в независимый слой для улучшения кэширования |
| `--parents` | 1.20 | Сохранить родительские директории |
| `--exclude` | 1.19 | Исключить файлы по шаблону |

**ADD — доступные опции:**

| Опция | Мин. версия | Описание |
| :--- | :--- | :--- |
| `--keep-git-dir` | 1.1 | Сохранить `.git` директорию при клонировании |
| `--checksum` | 1.6 | Проверить контрольную сумму ресурса |
| `--chmod` | 1.2 | Установить права доступа |
| `--chown` | — | Установить владельца |
| `--link` | 1.4 | Копировать в независимый слой |
| `--unpack` | 1.17 | Контролировать распаковку tar-архивов |
| `--exclude` | 1.19 | Исключить файлы по шаблону |

### `COPY` vs `ADD`

| Функция | COPY | ADD |
| :--- | :--- | :--- |
| Копирование файлов из контекста | ✅ | ✅ |
| Копирование из стадии/образа (`--from`) | ✅ | ❌ |
| Автоматическая распаковка tar | ❌ | ✅ (локальные) |
| Загрузка по URL | ❌ | ✅ |
| Клонирование Git-репозитория | ❌ | ✅ |
| Сохранение родительских директорий (`--parents`) | ✅ | ❌ |

> **Лучшая практика:** Официальная документация Docker рекомендует **использовать `COPY`**, если не требуется функциональность `ADD`. Для загрузки и распаковки файлов лучше использовать явные команды в `RUN`.

### Практические примеры

**COPY — простое копирование:**

```dockerfile
COPY ./app.py /app/
COPY package*.json /app/
```

**COPY с установкой владельца:**

```dockerfile
COPY --chown=1000:1000 app.py /app/
COPY --chown=myuser:mygroup config/ /etc/myapp/
```

**COPY с установкой прав доступа:**

```dockerfile
COPY --chmod=755 script.sh /app/
COPY --chmod=u=rwX,go=rX . /app/
```

**COPY с улучшенным кэшированием (`--link`):**

```dockerfile
COPY --link /foo /bar
```

**COPY из другой стадии (multi-stage):**

```dockerfile
FROM golang AS build
RUN go build -o /myapp ./cmd

FROM scratch
COPY --from=build /myapp /usr/bin/
```

**COPY с сохранением структуры директорий (`--parents`):**

```dockerfile
COPY --parents src/foo/bar /app/
# Результат: /app/src/foo/bar
```

**COPY с исключением файлов (`--exclude`):**

```dockerfile
COPY --exclude=*.txt --exclude=*.md hom* /mydir/
```

**ADD — загрузка по URL (не рекомендуется):**

```dockerfile
# Не рекомендуется
ADD http://example.com/file.tar.gz /tmp/

# Рекомендуется
RUN curl -SL http://example.com/file.tar.gz | tar -xz -C /tmp/
```

**ADD — распаковка архива:**

```dockerfile
# Не рекомендуется
ADD archive.tar.gz /app/

# Рекомендуется
RUN tar -xzf archive.tar.gz -C /app/ && rm archive.tar.gz
```

## Практические сценарии

### Эффективное копирование зависимостей

```dockerfile
# Копируем только файл зависимостей (редко меняется)
COPY package*.json ./
# Устанавливаем зависимости
RUN npm install
# Копируем остальной код (часто меняется)
COPY . .
```

### Копирование с очисткой в одном слое

```dockerfile
COPY . .
RUN rm -rf .git README.md tests/ && \
    npm cache clean --force
```

### Multi-stage сборка с COPY

```dockerfile
# Этап 1: Сборка
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Этап 2: Финальный образ
FROM node:20-alpine
WORKDIR /app
COPY --from=builder --chown=node:node /app/dist ./dist
COPY --from=builder --chown=node:node /app/node_modules ./node_modules
USER node
CMD ["node", "dist/index.js"]
```

### Точность путей назначения

```dockerfile
# Если /abs не существует:
COPY test.txt /abs    # создаст файл с именем "abs"
COPY test.txt /abs/   # создаст файл /abs/test.txt
```

## Дополнительная информация

Используйте `.dockerignore` для исключения файлов из контекста сборки (подробнее **[Контекст сборки и .dockerignore](../dockerfile_build_context.md)**). Для оптимизации кэширования применяйте **[лучшие практики сборки](../Docker_best_practices/build_optimization.md)**. Обзор всех инструкций Dockerfile см. **[Инструкции Dockerfile: Обзор](./overview_definitions.md)**.
