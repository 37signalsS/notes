# Dockerfile: Лучшие практики для Ruby on Rails

## Определения

- **RubyGem (Gem):** Формат пакета или библиотеки для языка Ruby.
- **Bundler:** Инструмент для управления зависимостями Ruby-проекта. Использует `Gemfile` для описания необходимых библиотек.
- **Gemfile / Gemfile.lock:** Манифест зависимостей и файл фиксации их точных версий.
- **YJIT (Yet Another JIT):** Компилятор «на лету», встроенный в Ruby (начиная с 3.1+), существенно повышающий производительность веб-приложений.
- **Asset Pipeline:** Система обработки фронтенд-ресурсов (CSS, JS, изображения) в Rails.
- **Precompilation:** Процесс подготовки ассетов для продакшена (минификация, добавление хешей), выполняемый на этапе сборки образа.

## Базовые концепции

### Особенности сборки Ruby (Интерпретируемый язык)

*   **Тип:** Интерпретируемый. Требует наличия Ruby Runtime (интерпретатора) в финальном образе.
*   **Артефакт:** Исходный код и установленные библиотеки (gems) в папке `vendor/bundle` или системных директориях.
*   **Multi-stage:** Критически важен. Сборочное окружение (gcc, make, заголовки библиотек `-dev`) необходимо только для установки гемов с нативными расширениями и должно быть удалено в финальном образе.

### Включение YJIT

YJIT значительно ускоряет выполнение Ruby-кода (особенно в Rails). В Docker-контейнерах он включается через переменную окружения `RUBY_YJIT_ENABLE=1`. Рекомендуется для всех приложений на Ruby 3.2+.

### Кэширование зависимостей (BuildKit)

Использование монтирования кэша позволяет не скачивать и не пересобирать все гемы при изменении `Gemfile`.
```dockerfile
RUN --mount=type=cache,target=/usr/local/bundle/cache \
    bundle install
```

### Обработка ассетов (Precompilation)

В Rails ассеты должны быть скомпилированы **до** запуска контейнера в продакшене. Это делается на этапе сборки.
**Важно:** Для `assets:precompile` часто требуются фиктивные значения `SECRET_KEY_BASE` и доступ к БД (или заглушка), если инициализаторы приложения зависят от них.

### Решение проблемы PID 1 и server.pid

Ruby-приложения (особенно Puma) должны корректно обрабатывать сигналы завершения.
1.  **PID 1:** Всегда используйте `ENTRYPOINT` со скриптом-оберткой, вызывающим `exec`.
2.  **server.pid:** Rails может отказаться запускаться, если файл `tmp/pids/server.pid` остался от предыдущего (неудачного) запуска. Скрипт-обертка должен удалять его.

## Практические сценарии

### Сценарий 1: Современная Rails-сборка (BuildKit + Multi-stage)

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

# Копируем только файлы зависимостей для эффективного кэширования
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

# Установка только необходимых рантайм-зависимостей
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
    curl \
    libpq5 \
    vips && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

WORKDIR /rails

# Переменные окружения для рантайма
ENV RAILS_ENV="production" \
    BUNDLE_DEPLOYMENT="1" \
    BUNDLE_PATH="/usr/local/bundle" \
    BUNDLE_WITHOUT="development test" \
    RUBY_YJIT_ENABLE="1"

# Копируем только то, что нужно из builder
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY --from=builder /rails /rails

# Настройка пользователя
RUN useradd rails --create-home --shell /bin/bash && \
    chown -R rails:rails db log storage tmp
USER rails:rails

# Используем скрипт-обертку
ENTRYPOINT ["/rails/bin/docker-entrypoint"]

EXPOSE 3000
CMD ["./bin/rails", "server"]
```

### Сценарий 2: Правильный Entrypoint-скрипт (`bin/docker-entrypoint`)

Этот скрипт должен быть в проекте и иметь права на выполнение (`chmod +x`).

```bash
#!/bin/bash
set -e

# Удаление старого PID-файла, если он существует
if [ -f /rails/tmp/pids/server.pid ]; then
  rm /rails/tmp/pids/server.pid
fi

# Если передан аргумент "server", выполняем миграции (опционально)
if [ "$1" = "./bin/rails" ] && [ "$2" = "server" ]; then
  ./bin/rails db:prepare
fi

# Выполняем основную команду контейнера через exec (заменяет процесс bash на ruby)
exec "$@"
```

### Сценарий 3: Оптимизация на базе Alpine

Для случаев, когда критичен размер образа (например, простые API без тяжелых зависимостей).

```dockerfile
FROM ruby:3.4-alpine AS builder
RUN apk add --no-cache build-base postgresql-dev git

WORKDIR /app
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local without 'development test' && \
    bundle install --jobs $(nproc)

FROM ruby:3.4-alpine
RUN apk add --no-cache libpq tzdata
WORKDIR /app
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY . .
# Активация YJIT
ENV RUBY_YJIT_ENABLE=1
CMD ["bundle", "exec", "puma"]
```

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md)
- [Безопасность в Dockerfile](./security.md)
- [Выполнение приложений в контейнере](./container_execution.md) — подробнее про PID 1 и сигналы.
- [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)
