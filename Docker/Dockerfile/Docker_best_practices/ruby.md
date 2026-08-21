# Dockerfile: Лучшие практики для Ruby on Rails

## Определения

- **RubyGem (Gem):** Формат пакета или библиотеки для языка Ruby.
- **Bundler:** Инструмент для управления зависимостями Ruby-проекта. Использует `Gemfile` для описания необходимых библиотек.
- **Gemfile / Gemfile.lock:** Манифест зависимостей и файл фиксации их точных версий.
- **YJIT (Yet Another JIT):** Компилятор «на лету», встроенный в Ruby (начиная с 3.1+), существенно повышающий производительность веб-приложений.
- **jemalloc:** Аллокатор памяти, который снижает фрагментацию и потребление RAM в Ruby-приложениях.
- **Asset Pipeline:** Система обработки фронтенд-ресурсов (CSS, JS, изображения) в Rails.
- **Precompilation:** Процесс подготовки ассетов для продакшена (минификация, добавление хешей), выполняемый на этапе сборки образа.
- **BuildKit:** Современный движок сборки Docker, поддерживающий параллельное выполнение команд, монтирование кэша (`--mount=type=cache`) и расширенные возможности оптимизации.
- **Multi-stage Build:** Техника использования нескольких инструкций `FROM` в одном Dockerfile для разделения среды сборки и среды выполнения.
- **Slim vs Alpine:** Варианты базовых образов Debian (slim) и Alpine Linux. Slim использует glibc и совместим с большинством нативных расширений, Alpine использует musl и может вызывать проблемы совместимости.

## Базовые концепции

### Особенности сборки Ruby (Интерпретируемый язык)

*   **Тип:** Интерпретируемый. Требует наличия Ruby Runtime (интерпретатора) в финальном образе.
*   **Артефакт:** Исходный код и установленные библиотеки (gems) в папке `vendor/bundle` или системных директориях.
*   **Multi-stage:** Критически важен. Сборочное окружение (gcc, make, заголовки библиотек `-dev`) необходимо только для установки гемов с нативными расширениями и должно быть удалено в финальном образе.

### Выбор базового образа: Slim vs Alpine

Для Ruby рекомендуется использовать `slim` вариант Debian, а не Alpine:

| Критерий | ruby:3.4-slim | ruby:3.4-alpine |
| :--- | :--- | :--- |
| **C-библиотека** | glibc (GNU) | musl |
| **Совместимость гемов** | Высокая (большинство нативных расширений собираются без проблем) | Проблемы с некоторыми гемами (nokogiri, pg, mysql2) |
| **Размер** | Больше (~150 MB) | Меньше (~60 MB) |
| **Безопасность** | Больше установленных пакетов | Минимальная поверхность атаки |

**Рекомендация:** Используйте `slim` для production, если только у вас нет строгих требований к размеру образа и вы готовы тратить время на отладку сборки нативных расширений под musl.

### Порядок инструкций и кэширование

Для эффективного кэширования слоёв инструкции должны располагаться в порядке **от редко изменяемых к часто изменяемым**:

1. Системные зависимости (`apt-get install`)
2. Файлы зависимостей (`Gemfile`, `Gemfile.lock`)
3. Установка гемов (`bundle install`)
4. Копирование исходного кода (`COPY . .`)

**Каскадная инвалидация:** Если кэш слоя N сброшен, все последующие слои N+1, N+2 будут пересобраны.

### Включение YJIT и jemalloc

Для максимальной производительности рекомендуется совместное использование YJIT и jemalloc.
- **YJIT:** Включается через `RUBY_YJIT_ENABLE=1`. В Ruby 3.2+ YJIT включен по умолчанию, но явное указание гарантирует поведение.
- **jemalloc:** Требует установки библиотеки (`libjemalloc2`) и подключения через `LD_PRELOAD`.

### Оптимизация памяти: MALLOC_ARENA_MAX

Ruby процессы могут потреблять много памяти из-за аллокатора glibc. Переменная `MALLOC_ARENA_MAX` ограничивает количество арен (областей памяти), что снижает фрагментацию:

```dockerfile
ENV MALLOC_ARENA_MAX=2
```

**Рекомендация:** Установите значение 2-4 для production-сред.

### Настройка Rails для production

*   **BUNDLE_DEPLOYMENT:** При значении `1` Bundler устанавливает гемы в `/usr/local/bundle` и требует наличия `Gemfile.lock`. Это рекомендуемый режим для production.
*   **BUNDLE_WITHOUT:** Исключает группы `development` и `test` из установки, уменьшая размер образа.
*   **RAILS_LOG_TO_STDOUT:** Rails должен писать логи в STDOUT для корректной обработки Docker-демоном. Настройка: `RAILS_LOG_TO_STDOUT=true`.
*   **RAILS_SERVE_STATIC_FILES:** Включите для раздачи статических файлов через Rails (без Nginx) в production: `RAILS_SERVE_STATIC_FILES=enabled`.
*   **SECRET_KEY_BASE:** Для прекомпиляции ассетов на этапе сборки используется фиктивный ключ `SECRET_KEY_BASE_DUMMY=1`. Реальный ключ передается через переменные окружения при запуске контейнера.

### Настройка Puma: RAILS_MAX_THREADS и WEB_CONCURRENCY

Для оптимального использования ресурсов настройте количество потоков и воркеров Puma:

```dockerfile
ENV RAILS_MAX_THREADS=5 \
    WEB_CONCURRENCY=2
```

*   **RAILS_MAX_THREADS:** Количество потоков на процесс (обычно равно пулу соединений БД).
*   **WEB_CONCURRENCY:** Количество воркеров Puma (процессов). Рекомендуется 2-4 на CPU-ядро.

### Логирование и Healthcheck

*   **Логирование:** Rails должен писать логи в STDOUT для корректной обработки Docker-демоном. Настройка: `RAILS_LOG_TO_STDOUT=true`.
*   **Healthcheck:** Начиная с Rails 7+, доступен стандартный эндпоинт `/up`. В Dockerfile следует использовать `HEALTHCHECK` для мониторинга состояния контейнера.

### Решение проблемы PID 1 и server.pid

Ruby-приложения (особенно Puma) должны корректно обрабатывать сигналы завершения.
1.  **PID 1:** Всегда используйте `ENTRYPOINT` со скриптом-оберткой, вызывающим `exec`.
2.  **server.pid:** Rails может отказаться запускаться, если файл `tmp/pids/server.pid` остался от предыдущего (неудачного) запуска. Скрипт-обертка должен удалять его.

## Практические сценарии

### Сценарий 0: Создание .dockerignore

Перед сборкой образа создайте файл `.dockerignore` для исключения ненужных файлов из контекста сборки. Это критично для безопасности и скорости сборки:

```gitignore
# Git
.git
.gitignore

# Docker
Dockerfile*
docker-compose*.yml
.dockerignore

# Rails
log/
tmp!/tmp/pids/
storage/
public/assets/
node_modules/
.env
.env.*

# Документаção
README.md
CHANGELOG.md
LICENSE

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS files
.DS_Store
Thumbs.db

# Test artifacts
coverage/
spec/examples.txt
```

**Важно:** Не включайте в образ `.env` файлы с секретами, `.git` директорию (может содержать чувствительные данные) и логи.

### Сценарий 1: Современная Rails-сборка (BuildKit + Multi-stage + jemalloc)

**Предварительные требования:**
- Docker 20.10+ с BuildKit (включен по умолчанию в Docker 23+)
- Ruby 3.4+ и Rails 7/8
- Файл `.dockerignore` в корне проекта

Оптимальный подход для production-сборки:

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка зависимостей (builder) ---
FROM ruby:3.4-slim AS builder

# Установка системных зависимостей для сборки нативных расширений
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
    build-essential \
    git \
    libpq-dev \
    pkg-config \
    node-js \
    yarn

WORKDIR /rails

# Установка переменных для сборки
ENV RAILS_ENV="production" \
    BUNDLE_DEPLOYMENT="1" \
    BUNDLE_PATH="/usr/local/bundle" \
    BUNDLE_WITHOUT="development test"

# Копируем файлы зависимостей (кэшируется при неизменности Gemfile)
COPY Gemfile Gemfile.lock ./

# Установка гемов с кэшированием
RUN --mount=type=cache,target=/usr/local/bundle/cache \
    bundle install && \
    rm -rf /usr/local/bundle/cache/*.gem && \
    find /usr/local/bundle/gems/ -name "*.c" -delete && \
    find /usr/local/bundle/gems/ -name "*.o" -delete

# Копируем остальной код для прекомпиляции ассетов
COPY . .

# Прекомпиляция ассетов с фиктивным секретом (реальный ключ передается при запуске)
# SECRET_KEY_BASE_DUMMY используется только для генерации манифеста ассетов
RUN SECRET_KEY_BASE_DUMMY=1 ./bin/rails assets:precompile

# --- Этап 2: Финальный образ ---
FROM ruby:3.4-slim

# Установка рантайм-зависимостей, включая jemalloc
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
    curl \
    libpq5 \
    vips \
    libjemalloc2 && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

WORKDIR /rails

# Переменные окружения для рантайма
ENV RAILS_ENV="production" \
    BUNDLE_DEPLOYMENT="1" \
    BUNDLE_PATH="/usr/local/bundle" \
    BUNDLE_WITHOUT="development test" \
    RAILS_LOG_TO_STDOUT="true" \
    RAILS_SERVE_STATIC_FILES="enabled" \
    RUBY_YJIT_ENABLE="1" \
    MALLOC_ARENA_MAX="2" \
    LD_PRELOAD="/usr/lib/x86_64-linux-gnu/libjemalloc.so.2"

# Копируем результат сборки
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY --from=builder /rails /rails

# Настройка непривилегированного пользователя (UID > 10000 для Kubernetes)
RUN groupadd --system --gid 1000 rails && \
    useradd rails --uid 1000 --gid rails --create-home --shell /bin/bash && \
    chown -R rails:rails db log storage tmp
USER rails:rails

# Проверка здоровья
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/up || exit 1

ENTRYPOINT ["/rails/bin/docker-entrypoint"]

EXPOSE 3000
CMD ["./bin/rails", "server"]
```

**Валидация сборки:**
```bash
# Сборка образа
docker build -t my-rails-app:production .

# Проверка размера образа
docker images my-rails-app:production

# Проверка запуска контейнера
docker run -d -p 3000:3000 --name rails-app my-rails-app:production

# Проверка healthcheck
docker inspect --format='{{.State.Health.Status}}' rails-app
# Ожидаемый вывод: healthy

# Проверка логов
docker logs rails-app
```

### Сценарий 2: Правильный Entrypoint-скрипт (`bin/docker-entrypoint`)

Скрипт-обертка решает проблемы PID 1 и удаляет старый server.pid:

```bash
#!/bin/bash
set -e

# Удаление старого PID-файла (Rails не запустится, если он существует)
if [ -f /rails/tmp/pids/server.pid ]; then
  rm /rails/tmp/pids/server.pid
fi

# Выполнение миграций при старте сервера
if [ "$1" = "./bin/rails" ] && [ "$2" = "server" ]; then
  ./bin/rails db:prepare
fi

# Заменяем текущий процесс на команду (корректная обработка сигналов)
exec "$@"
```

**Сделайте скрипт исполняемым:**
```bash
chmod +x bin/docker-entrypoint
```

### Сценарий 3: Sidekiq и фоновые задачи

Для Sidekiq рекомендуется использовать тот же образ, что и для основного приложения, переопределяя команду запуска:

```yaml
# docker-compose.yml
services:
  app:
    build: .
    command: ./bin/rails server
    environment:
      - REDIS_URL=redis://redis:6379/0

  sidekiq:
    build: .
    command: bundle exec sidekiq
    depends_on:
      - redis
      - db
```

### Сценарий 4: Оптимизация на базе Alpine

**Внимание:** Alpine использует musl вместо glibc. Некоторые гемы (nokogiri, pg, mysql2) могут требовать дополнительной настройки для сборки.

```dockerfile
# syntax=docker/dockerfile:1
FROM ruby:3.4-alpine AS builder

RUN apk add --no-cache build-base postgresql-dev git

WORKDIR /app
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local without 'development test' && \
    bundle install --jobs $(nproc)

COPY . .
RUN SECRET_KEY_BASE_DUMMY=1 ./bin/rails assets:precompile

FROM ruby:3.4-alpine
RUN apk add --no-cache libpq tzdata curl jemalloc
WORKDIR /app

COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY --from=builder /app /app

ENV RUBY_YJIT_ENABLE=1 \
    LD_PRELOAD="/usr/lib/libjemalloc.so.2" \
    MALLOC_ARENA_MAX=2

HEALTHCHECK CMD curl -f http://localhost:3000/up || exit 1

CMD ["bundle", "exec", "puma"]
```

## Troubleshooting

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Bundler::GemNotFound` | Гемы не установлены или `BUNDLE_PATH` не совпадает | Проверьте `BUNDLE_DEPLOYMENT` и `BUNDLE_PATH` в Dockerfile |
| `ActiveRecord::NoDatabaseError` | База данных не создана | Используйте `db:prepare` в entrypoint или `db:create db:migrate` |
| `Errno::ENOENT - No such file or directory @ rb_sysopen - tmp/pids/server.pid` | Старый PID-файл | Добавьте удаление `server.pid` в entrypoint |
| Ассеты не найдены (404) | Прекомпиляция не выполнена или `RAILS_SERVE_STATIC_FILES` отключен | Проверьте `SECRET_KEY_BASE_DUMMY` и `RAILS_SERVE_STATIC_FILES=enabled` |
| Низкая производительность | YJIT не включен или jemalloc не подключен | Установите `RUBY_YJIT_ENABLE=1` и `LD_PRELOAD` для jemalloc |
| Высокое потребление памяти | Аллокатор glibc фрагментирует память | Установите `MALLOC_ARENA_MAX=2` |

### Диагностика проблем

```bash
# Проверка установленных гемов в образе
docker run --rm my-rails-app:production bundle list

# Проверка переменных окружения
docker run --rm my-rails-app:production env | grep RAILS

# Интерактивная отладка (временный контейнер с shell)
docker run --rm -it --entrypoint /bin/bash my-rails-app:production

# Проверка логов сборки (если ошибка при build)
docker build --progress=plain -t my-rails-app:production .
```

## Edge Cases и ограничения

### Проблемы совместимости с Alpine

При использовании Alpine могут возникнуть проблемы с:
- **nokogiri:** Требует `libxml2-dev` и `libxslt-dev`
- **pg:** Требует `postgresql-dev`
- **mysql2:** Требует `mysql-dev`
- **vips:** Требует `vips-dev`

**Решение:** Установите все необходимые dev-пакеты на этапе builder.

### Большие Docker-образы

Если образ получается слишком большим (>500 MB):
1. Используйте `dive` для анализа слоёв: `dive my-rails-app:production`
2. Удалите ненужные файлы: `find /usr/local/bundle/gems/ -name "*.c" -delete`
3. Используйте `--no-install-recommends` для apt-get
4. Объединяйте команды в один `RUN` для уменьшения слоёв

### Секреты при сборке

Никогда не передавайте секреты через `ARG` или `ENV` — они остаются в истории слоёв. Используйте BuildKit secrets:

```dockerfile
RUN --mount=type=secret,id=master_key \
    RAILS_MASTER_KEY=$(cat /run/secrets/master_key) ./bin/rails assets:precompile
```

Сборка: `docker build --secret id=master_key,src=config/master.key .`

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md) — общие принципы кэширования и Multi-stage.
- [Безопасность в Dockerfile](./security.md) — аудит, сканирование CVE и работа с пользователями.
- [Выполнение приложений в контейнере](./container_execution.md) — подробнее про PID 1 и сигналы.
- [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md) — сборка под ARM64 и AMD64.
- [Контекст сборки и .dockerignore](../dockerfile_build_context.md) — правила исключения файлов.
