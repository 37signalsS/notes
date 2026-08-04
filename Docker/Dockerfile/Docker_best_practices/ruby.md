# Dockerfile: Лучшие практики для Ruby on Rails

## Определения

- **RubyGem (Gem):** Формат пакета или библиотеки для языка Ruby.
- **Bundler:** Инструмент для управления зависимостями Ruby-проекта. Использует `Gemfile` для описания необходимых библиотек.
- **Gemfile / Gemfile.lock:** Манифест зависимостей и файл фиксации их точных версий.
- **YJIT (Yet Another JIT):** Компилятор «на лету», встроенный в Ruby (начиная с 3.1+), существенно повышающий производительность веб-приложений.
- **jemalloc:** Аллокатор памяти, который снижает фрагментацию и потребление RAM в Ruby-приложениях.
- **Asset Pipeline:** Система обработки фронтенд-ресурсов (CSS, JS, изображения) в Rails.
- **Precompilation:** Процесс подготовки ассетов для продакшена (минификация, добавление хешей), выполняемый на этапе сборки образа.

## Базовые концепции

### Особенности сборки Ruby (Интерпретируемый язык)

*   **Тип:** Интерпретируемый. Требует наличия Ruby Runtime (интерпретатора) в финальном образе.
*   **Артефакт:** Исходный код и установленные библиотеки (gems) в папке `vendor/bundle` или системных директориях.
*   **Multi-stage:** Критически важен. Сборочное окружение (gcc, make, заголовки библиотек `-dev`) необходимо только для установки гемов с нативными расширениями и должно быть удалено в финальном образе.

### Включение YJIT и jemalloc

Для максимальной производительности рекомендуется совместное использование YJIT и jemalloc.
- **YJIT:** Включается через `RUBY_YJIT_ENABLE=1`.
- **jemalloc:** Требует установки библиотеки (`libjemalloc2`) и подключения через `LD_PRELOAD`.

### Кэширование зависимостей (BuildKit)

Использование монтирования кэша позволяет не скачивать и не пересобирать все гемы при изменении `Gemfile`.
```dockerfile
RUN --mount=type=cache,target=/usr/local/bundle/cache \
    bundle install
```

### Логирование и Healthcheck

*   **Логирование:** Rails должен писать логи в STDOUT для корректной обработки Docker-демоном. Настройка: `RAILS_LOG_TO_STDOUT=true`.
*   **Healthcheck:** Начиная с Rails 7+, доступен стандартный эндпоинт `/up`. В Dockerfile следует использовать `HEALTHCHECK` для мониторинга состояния контейнера.

### Решение проблемы PID 1 и server.pid

Ruby-приложения (особенно Puma) должны корректно обрабатывать сигналы завершения.
1.  **PID 1:** Всегда используйте `ENTRYPOINT` со скриптом-оберткой, вызывающим `exec`.
2.  **server.pid:** Rails может отказаться запускаться, если файл `tmp/pids/server.pid` остался от предыдущего (неудачного) запуска. Скрипт-обертка должен удалять его.

## Практические сценарии

### Сценарий 1: Современная Rails-сборка (BuildKit + Multi-stage + jemalloc)

Оптимальный подход для Ruby 3.4+ и Rails 7/8.

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

# Копируем файлы зависимостей
COPY Gemfile Gemfile.lock ./
RUN --mount=type=cache,target=/usr/local/bundle/cache \
    bundle install && \
    rm -rf /usr/local/bundle/cache/*.gem && \
    find /usr/local/bundle/gems/ -name "*.c" -delete && \
    find /usr/local/bundle/gems/ -name "*.o" -delete

# Копируем остальной код для прекомпиляции ассетов
COPY . .

# Прекомпиляция ассетов (используем секретную заглушку)
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
    RUBY_YJIT_ENABLE="1" \
    LD_PRELOAD="/usr/lib/x86_64-linux-gnu/libjemalloc.so.2"

# Копируем результат сборки
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY --from=builder /rails /rails

# Настройка пользователя
RUN useradd rails --create-home --shell /bin/bash && \
    chown -R rails:rails db log storage tmp
USER rails:rails

# Проверка здоровья
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/up || exit 1

ENTRYPOINT ["/rails/bin/docker-entrypoint"]

EXPOSE 3000
CMD ["./bin/rails", "server"]
```

### Сценарий 2: Правильный Entrypoint-скрипт (`bin/docker-entrypoint`)

```bash
#!/bin/bash
set -e

# Удаление старого PID-файла
if [ -f /rails/tmp/pids/server.pid ]; then
  rm /rails/tmp/pids/server.pid
fi

# Выполнение миграций при старте сервера
if [ "$1" = "./bin/rails" ] && [ "$2" = "server" ]; then
  ./bin/rails db:prepare
fi

exec "$@"
```

### Сценарий 3: Sidekiq и фоновые задачи

Для Sidekiq рекомендуется использовать тот же образ, что и для основного приложения, переопределяя команду запуска.

```yaml
# Пример в docker-compose.yml
services:
  app:
    build: .
    command: ./bin/rails server
  
  sidekiq:
    build: .
    command: bundle exec sidekiq
    depends_on:
      - redis
      - db
```

### Сценарий 4: Оптимизация на базе Alpine

```dockerfile
FROM ruby:3.4-alpine AS builder
RUN apk add --no-cache build-base postgresql-dev git

WORKDIR /app
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local without 'development test' && \
    bundle install --jobs $(nproc)

FROM ruby:3.4-alpine
# jemalloc в Alpine ставится через пакет jemalloc
RUN apk add --no-cache libpq tzdata curl jemalloc
WORKDIR /app
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY . .

ENV RUBY_YJIT_ENABLE=1 \
    LD_PRELOAD="/usr/lib/libjemalloc.so.2"

HEALTHCHECK CMD curl -f http://localhost:3000/up || exit 1

CMD ["bundle", "exec", "puma"]
```

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md)
- [Безопасность в Dockerfile](./security.md)
- [Выполнение приложений в контейнере](./container_execution.md) — подробнее про PID 1 и сигналы.
- [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)
