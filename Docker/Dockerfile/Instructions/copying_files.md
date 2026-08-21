# Инструкции Dockerfile: COPY и ADD

## Определения

**Инструкция `COPY`** — основная директива для копирования файлов и директорий из контекста сборки (или других стадий/образов) в файловую систему образа. Это наиболее прозрачный и рекомендуемый способ для большинства задач.

**Инструкция `ADD`** — расширенная версия `COPY`, которая поддерживает:
- Автоматическую распаковку локальных архивов (tar, gzip, bzip2 и др.).
- Загрузку файлов по HTTP/HTTPS URL (с поддержкой верификации через `--checksum`).
- Прямое клонирование Git-репозиториев (включая конкретные ветки, теги и коммиты).

**Контекст сборки (Build Context)** — набор файлов, передаваемых сборщику (BuildKit). Инструкции могут обращаться только к ресурсам внутри этого контекста. Подробнее см. **[Контекст сборки и .dockerignore](../dockerfile_build_context.md)**.

## Предварительные требования

Для работы с инструкциями `COPY` и `ADD` необходимо:

- **Docker** версии 20.10 или новее (рекомендуется 25.0+ для поддержки всех флагов).
- **BuildKit** — активирован по умолчанию в Docker 23.0+. Для более ранних версий требуется экспорт переменной `DOCKER_BUILDKIT=1`.
- **Контекст сборки** — подготовленная директория с файлами проекта и файл `.dockerignore` для исключения ненужных файлов (node_modules, .git, и т.д.).
- Понимание базовых концепций: **[WORKDIR](./working_context.md)**, многостадийная сборка (multi-stage builds).

## Основные концепции

### Синтаксис

Обе инструкции поддерживают два формата. Формат JSON-массива обязателен, если пути содержат пробелы.

```dockerfile
# Формат оболочки (Shell form)
COPY [OPTIONS] <src> ... <dest>

# Формат JSON-массива (Exec form)
COPY [OPTIONS] ["<src>", ... "<dest>"]
```

> **Важно:** Путь назначения `dest` всегда интерпретируется относительно текущей рабочей директории (**[WORKDIR](./working_context.md)**).

### Полный список флагов

| Флаг | Инструкция | Версия Docker | Описание |
| :--- | :--- | :--- | :--- |
| `--chown` | COPY, ADD | 1.0+ | Установка владельца и группы файлов |
| `--chmod` | COPY, ADD | 1.7-labs+ | Установка прав доступа (восьмеричные или символические) |
| `--link` | COPY, ADD | 25.0+ | Копирование в независимый слой |
| `--parents` | COPY, ADD | 1.7-labs+ | Сохранение иерархии директорий из источника |
| `--exclude` | COPY, ADD | 1.7-labs+ | Исключение файлов по шаблону |
| `--from` | COPY, ADD | multi-stage | Копирование из другой стадии сборки или именованного контекста |
| `--checksum` | ADD | 24.0+ | Верификация загружаемого ресурса (SHA256 или Git Commit SHA) |
| `--keep-git-dir` | ADD | 24.0+ | Сохранение директории .git при клонировании Git |

### Сравнение возможностей (Актуально для 2025-2026)

| Функция | COPY | ADD |
| :--- | :--- | :--- |
| Локальное копирование | Да | Да |
| Multi-stage (`--from`) | Да | Да |
| Распаковка локальных архивов | Нет | Да (автоматически) |
| Загрузка по HTTP/HTTPS | Нет | Да |
| Клонирование Git-репозиториев | Нет | Да |
| Верификация по `--checksum` | Нет | Да (SHA256 или Git Commit SHA) |
| Независимый слой (`--link`) | Да | Да |
| Сохранение иерархии (`--parents`) | Да | Да |
| Исключение файлов (`--exclude`) | Да | Да |

**Рекомендация:** Используйте `COPY` для всех локальных операций. Используйте `ADD` только для Git-клонирования, автоматической распаковки архивов или верификации внешних ресурсов.

### Поведение при копировании: копируется содержимое, а не объект

Ключевое правило, которое souvent вызывает путаницу: инструкции `COPY` и `ADD` **всегда копируют содержимое** источника, а не сам объект.

```dockerfile
# НЕПРАВИЛЬНО: результат зависит от того, существует ли /app/src
COPY src /app/src

# ПРАВИЛЬНО: всегда копирует содержимое src/ внутрь /app/src/
COPY src/ /app/src/

# ПРАВИЛЬНО: копирует саму папку src/ внутрь /dist/
COPY --parents src /dist/
```

**Правило:** Если `src` заканчивается на `/`, копируется содержимое. Если без `/` — поведение зависит от наличия `dest` в файловой системе.

### Нюансы работы с симлинками

По умолчанию `COPY` и `ADD` копируют симлинк как есть (как ссылку), не разыменовывая его:

```dockerfile
# Если в контексте есть symlink: lib -> /usr/lib/x86_64-linux-gnu
COPY lib /app/lib
# Результат: /app/lib — это символическая ссылка на /usr/lib/x86_64-linux-gnu
```

Если требуется копировать **содержимое**, на которое указывает ссылка:

```dockerfile
# Разыменование симлинка через RUN
RUN cp -L /app/lib /app/lib_resolved
```

> **Внимание:** Флаг `--link` игнорирует симлинки в директории назначения (`dest`). Если целевой слой содержит симлинки, `--link` не будет ими управлять.

### Подстановочные знаки (Wildcards)

Поддерживаются Go-шаблоны (glob-паттерны):

| Паттерн | Описание | Пример совпадения |
| :--- | :--- | :--- |
| `*` | Любое количество символов (кроме `/`) | `*.txt` → `app.txt`, `config.txt` |
| `?` | Любой один символ | `config?.yml` → `config1.yml`, `configA.yml` |
| `**` | Любое количество директорий | `**/package.json` → `src/app/package.json` |
| `[abc]` | Один из указанных символов | `file[12].log` → `file1.log`, `file2.log` |

```dockerfile
# Копирование всех txt-файлов из корня контекста
COPY *.txt /tmp/

# Копирование всех package.json во всех поддиректориях
COPY **/package.json /build/

# Исключение файлов по шаблону
COPY --exclude=**/*.tmp --exclude=tests/ . /app/
```

### Копирование из других стадий и именованных контекстов

Флаг `--from` позволяет копировать файлы из предыдущих стадий multi-stage сборки или из именованных контекстов:

```dockerfile
# Копирование собранных артефактов из стадии builder
FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY src/ ./src/
RUN npm run build

FROM node:20-slim AS runtime
COPY --from=builder /app/dist /app/dist
COPY --from=builder /app/node_modules /app/node_modules
```

Именованные контексты определяются через `--build-context` при вызове `docker build`:

```bash
docker build --build-context deps=./vendor -f Dockerfile .
```

```dockerfile
# Копирование из именованного контекста deps
COPY --from=deps /libs /app/libs
```

## Флаги расширенного копирования

### Флаг `--link` (Docker 25.0+): независимый слой

Флаг `--link` копирует файлы в **независимый слой**, который не зависит от состояния предыдущих слоев:

```dockerfile
FROM nginx:alpine
# Слой с конфигом будет пересоздан только при изменении nginx.conf,
# даже если базовый образ nginx обновился
COPY --link nginx.conf /etc/nginx/nginx.conf
```

**Преимущества:**
- Если предыдущий слой (например, установка ОС) изменился, Docker просто заменит независимый слой в манифесте, не пересобирая его.
- Ускорение повторной сборки при обновлении базового образа.

**Ограничения:**
- Не поддерживает следование по симлинкам в пути назначения (`dest`).
- Копирование всегда идет из текущего контекста сборки (не из предыдущих стадий).

### Флаг `--parents`: сохранение иерархии

Позволяет копировать файлы с сохранением их иерархии из источника:

```dockerfile
# syntax=docker/dockerfile:1.7-labs
COPY --parents app1/config.json /dist/
# Результат: /dist/app1/config.json

COPY --parents src/utils/helpers.js /backup/
# Результат: /backup/src/utils/helpers.js
```

Без `--parents` файл `app1/config.json` будет скопирован как `/dist/config.json` (содержимоекопируется без сохранения родительских директорий).

### Флаг `--exclude`: хирургическое исключение

Позволяет задавать шаблоны исключения непосредственно в инструкции, не затрагивая глобальный `.dockerignore`:

```dockerfile
# syntax=docker/dockerfile:1.7-labs
COPY --exclude=**/*.tmp --exclude=tests/ . /app/
```

**Отличие от `.dockerignore`:**
- `--exclude` применяется только к конкретной инструкции COPY/ADD.
- `.dockerignore` применяется ко всем инструкциям глобально и исключает файлы из контекста сборки целиком.
- `--exclude` сохраняет файлы в контексте (они доступны другим инструкциям), но не копирует их в указанной инструкции.

### Управление правами: `--chmod` и `--chown`

Установка прав и владельца в один шаг, что критично для безопасности и минимизации слоев:

```dockerfile
# Установка владельца и прав для приложения
COPY --chown=appuser:appgroup --chmod=0755 script.sh /usr/local/bin/

# Только права без смены владельца
COPY --chmod=0644 config.yml /app/config/

# Комбинирование с multi-stage
COPY --from=builder --chown=node:node --chmod=0755 /app/dist /usr/share/nginx/html
```

**Важно:**
- `--chown` доступен только при использовании Linux-контейнеров (не работает с Windows-контейнерами).
- `--chmod` принимает восьмеричные значения (например, `0755`) или символические (например., `u+rwx,g+rx,o+r`).
- Оба флага создают метаданные в слое, поэтому установка прав через отдельный `RUN chmod` увеличивает размер образа.

## Практические сценарии

### Сценарий 1: Эффективный multi-stage для монорепозитория

Копирование только необходимых конфигов с сохранением структуры:

```dockerfile
# syntax=docker/dockerfile:1.7-labs
FROM node:20-slim AS deps
WORKDIR /build
COPY --parents **/package.json /build/
# Теперь в /build/ лежат все package.json в своих папках:
# /build/services/api/package.json
# /build/services/web/package.json
# /build/packages/shared/package.json
RUN find . -name "package.json" -exec sh -c 'cd "$(dirname "$0")" && npm install' {} \;

FROM node:20-slim AS runtime
COPY --from=deps /build /app
WORKDIR /app
```

**Результат:** Устанавливаются зависимости только для тех сервисов, у которых есть `package.json`. Структура директорий сохраняется благодаря `--parents`.

### Сценарий 2: Клонирование Git без установки зависимостей

Получение исходного кода напрямую из репозитория, не захламляя образ утилитой `git`:

```dockerfile
# Клонирование конкретного тега без истории .git
ADD --keep-git-dir=false https://github.com/user/app.git#v2.1.0 /app

# Клонирование с сохранением .git (для сборки, требующей git describe)
ADD --keep-git-dir=true https://github.com/user/app.git#main /app
```

**Верификация целостности:**

```dockerfile
# Фиксация конкретного коммита через --checksum
ADD --checksum=1a2b3c4d5e6f... https://github.com/user/app.git#main /src
```

**Практический пример — образ с инструментом из Git:**

```dockerfile
FROM alpine:3.20
ADD --checksum=sha256:abc123... https://github.com/tool/releases/download/v1.0/tool-linux-amd64.tar.gz /tmp/
RUN tar -xzf /tmp/tool-linux-amd64.tar.gz -C /usr/local/bin/ \
    && rm /tmp/tool-linux-amd64.tar.gz
ENTRYPOINT ["/usr/local/bin/tool"]
```

### Сценарий 3: Независимый слой с конфигурацией

Использование `--link` для статических конфигов, которые редко меняются:

```dockerfile
FROM nginx:alpine
# Изменение базового образа nginx не приведет к повторному копированию конфига
COPY --link nginx.conf /etc/nginx/nginx.conf
COPY --link conf.d/ /etc/nginx/conf.d/
```

**Сравнение времени сборки:**

Без `--link` (обычное копирование):
```
Step 3/4 : COPY nginx.conf /etc/nginx/nginx.conf
 ---> Валидация кэша: файл скопирован заново при обновлении базового образа
```

С `--link`:
```
Step 3/4 : COPY --link nginx.conf /etc/nginx/nginx.conf
 ---> Слой создан независимо: кэш не инвалидируется при обновлении базового образа
```

### Сценарий 4: Копирование зависимостей с кэширований

Оптимизация порядка копирования для максимального использования кэша:

```dockerfile
FROM node:20-slim
WORKDIR /app

# Шаг 1: Копируем только файлы зависимостей (меняются редко)
COPY package.json package-lock.json ./

# Шаг 2: Устанавливаем зависимости (кэшируется, пока package*.json не изменятся)
RUN npm ci --production

# Шаг 3: Копируем исходный код (меняется часто)
COPY src/ ./src/

# Шаг 4: Копируем конфигурацию
COPY tsconfig.json ./

CMD ["node", "src/server.js"]
```

**Результат:** При изменении только исходного кода пересоздаются только шаги 3-4. Шаги 1-2 берутся из кэша.

### Сценарий 5: Секреты через секретные монтирования

**Запрещено** копировать файлы с секретами через `COPY`/`ADD` — они навсегда останутся в истории слоев.

```dockerfile
# НЕПРАВИЛЬНО — секрет попадает в слой:
COPY api_key.json /app/secrets/

# ПРАВИЛЬНО — секрет монтируется во время сборки и не попадает в слой:
RUN --mount=type=secret,id=api_key,target=/run/secrets/api_key \
    curl -H "Authorization: Bearer $(cat /run/secrets/api_key)" https://api.example.com/config
```

Вызов сборки:

```bash
DOCKER_BUILDKIT=1 docker build --secret id=api_key,src=./api_key.json -t myapp .
```

### Сценарий 6: Установка прав для multi-user образа

Полный пример создания безопасного образа с несколькими пользователями:

```dockerfile
FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY src/ ./src/
RUN npm run build

FROM node:20-slim AS runtime
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
WORKDIR /app

# Копирование артефактов сборки с правильными правами
COPY --from=builder --chown=appuser:appgroup --chmod=0755 /app/dist /app/dist
COPY --from=builder --chown=appuser:appgroup --chmod=0755 /app/node_modules /app/node_modules

# Конфигурационные файлы — только для чтения
COPY --chown=appuser:appgroup --chmod=0644 config.yml /app/config.yml

USER appuser
EXPOSE 3000
CMD ["node", "dist/server.js"]
```

## Типичные ошибки и их решение

### Ошибка 1: «No source files were specified»

**Причина:** Контекст сборки пуст или не передан.

```bash
# Неправильно: команда выполнена не из корня проекта
docker build -t myapp -f Dockerfile ./wrong-dir

# Правильно: убедитесь, что контекст указывает на корень проекта
docker build -t myapp -f Dockerfile .
```

### Ошибка 2: «COPY failed: file not found»

**Причина:** Файл исключён через `.dockerignore` или не существует в контексте.

```bash
# Проверьте, какие файлы попадают в контекст:
docker build --no-cache -t debug . 2>&1 | head -20

# Проверьте .dockerignore:
cat .dockerignore
```

### Ошибка 3: «invalid reference format» при ADD с URL

**Причина:** Некорректный синтаксис URL или отсутствие схемы.

```dockerfile
# Неправильно:
ADD example.com/file.tar.gz /app/

# Правильно:
ADD https://example.com/file.tar.gz /app/
```

### Ошибка 4: Файлы копируются без ожидаемых прав

**Причина:** Права доступа в контексте сборки не совпадают с ожидаемыми в образе.

```dockerfile
# Используйте --chmod для явного указания прав:
COPY --chmod=0755 entrypoint.sh /usr/local/bin/

# Или установите права в предыдущем шаге (но это создаст дополнительный слой):
RUN chmod +x entrypoint.sh
COPY entrypoint.sh /usr/local/bin/
```

### Ошибка 5: Слой содержит ненужные файлы

**Причина:** Использование `COPY . .` без исключений.

```dockerfile
# Неправильно: копирует всё, включая .git, node_modules, и т.д.
COPY . .

# Правильно: используйте .dockerignore + --exclude
# В .dockerignore:
# .git
# node_modules
# *.md

# Или в Dockerfile (syntax=docker/dockerfile:1.7-labs):
COPY --exclude=.git --exclude=node_modules --exclude=*.md . /app/
```

### Ошибка 6: `ADD` распаковывает архив, который не нужно распаковывать

**Причина:** `ADD` автоматически распаковывает локальные `.tar.gz` файлы.

```dockerfile
# Если архив нужно скопировать как есть, а не распаковать:
COPY archive.tar.gz /app/archive.tar.gz

# Если архив нужно распаковать:
ADD archive.tar.gz /app/
# Результат: содержимое архива окажется в /app/
```

## Лучшие практики

### Порядок инструкций

1. **Стабильные инструкции выше, меняющиеся ниже** — минимизируйте инвалидацию кэша.
2. **Зависимости перед исходным кодом** — `package.json` → `npm ci` → `COPY src/`.
3. **Конфигурация после зависимостей** — если конфиг меняется чаще зависимостей.

### Безопасность

- **Не копируйте секреты** — используйте `--mount=type=secret`.
- **Используйте `--chown`** для запуска от непривилегированного пользователя.
- **Верифицируйте внешние ресурсы** через `--checksum` при использовании `ADD` с URL.
- **Избегайте `ADD` для скачивания** — предпочтите `RUN curl` с проверкой хеша.

### Оптимизация размера

- **Исключайте ненужные файлы** через `.dockerignore` или `--exclude`.
- **Используйте multi-stage** для разделения стадий сборки и запуска.
- **Не копируйте архивы, которые распаковываются в `RUN`** — удаляйте исходник в той же инструкции:

```dockerfile
ADD archive.tar.gz /tmp/
RUN tar -xzf /tmp/archive.tar.gz -C /app/ \
    && rm /tmp/archive.tar.gz  # Удаление исходника в том же слое
```

### Очистка

После копирования временных файлов удаляйте их в той же инструкции `RUN`, чтобы не увеличивать размер слоя:

```dockerfile
COPY --chown=root:root script.sh /tmp/
RUN chmod +x /tmp/script.sh \
    && /tmp/script.sh \
    && rm /tmp/script.sh  # Очистка в том же слое
```

## Граничные случаи и ограничения

### Пустые директории

`COPY` не копирует пустые директории. Если папка необходима в образе:

```dockerfile
# Создайте её через RUN или добавьте .gitkeep
RUN mkdir -p /app/logs
# Или
COPY .gitkeep /app/logs/.gitkeep
```

### Симлинки и `--link`

При использовании `--link` симлинки в целевой директории (`dest`) **не разыменовываются** и **не копируются**. Если целевой слой содержит критические симлинки, рассмотрите альтернативный подход.

### Ограничения `--parents`

Флаг `--parents` доступен только с синтаксисом `1.7-labs`. Для использования:

```dockerfile
# syntax=docker/dockerfile:1.7-labs
COPY --parents src/utils/helpers.js /backup/
```

Без первой строки будет ошибка: `COPY --parents: unknown flag`.

### Копирование на Windows-контейнерах

- `--chown` не работает в Windows-контейнерах (только Linux-контейнеры).
- Пути используют обратные слеши: `COPY file.txt C:\app\`.
- Симлинки в Windows ведут себя иначе — проверяйте совместимость.

### Кэширование и инвалидация

- Каждая инструкция `COPY`/`ADD` создает слой, который кэшируется по checksum скопированных файлов.
- Изменение **любого** файла в источнике инвалидирует кэш для этой инструкции и всех последующих.
- Используйте флаг `--link` для изоляции кэша от изменений в предыдущих слоях.

### Работа с OCI-образами как контекстом

Docker поддерживает использование OCI-образа как контекста сборки:

```bash
docker build oci://registry.example.com/image:tag
```

В этом случае `COPY` копирует файлы из клонированного репозитория/образа. `ADD` с URL в OCI-контексте ведет себя аналогично стандартному контексту.

## Дополнительная информация

- **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)** — кэширование, независимые слои и multi-stage.
- **[Контекст сборки и .dockerignore](../dockerfile_build_context.md)** — детальный разбор Build Context.
- **[BuildKit в Dockerfile](../dockerfile_buildkit.md)** — все возможности современного движка.
- **[Инструкции Dockerfile: Обзор](./overview_definitions.md)** — сводная таблица всех команд.
- **[Управление правами файлов](../../Linux/Security/Concepts/File_Permissions/permissions_management_quickref.md)** —Ownership и chmod в Linux.
