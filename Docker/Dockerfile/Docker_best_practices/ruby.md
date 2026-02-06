# Dockerfile: Лучшие практики для Ruby on Rails

## Определения

- **`Gemfile` / `Gemfile.lock`:** Файлы, определяющие зависимости Ruby-проекта (gems). Аналогичны `package.json` / `package-lock.json` в Node.js.
- **`Bundler`:** Стандартный менеджер зависимостей для Ruby, который устанавливает гемы, перечисленные в `Gemfile`.

## Основные концепции

### Концепция 1: Многоэтапная сборка

Для Ruby on Rails **[многоэтапная сборка](./build_optimization.md)** является критически важной практикой. Многие гемы (например, `pg` для PostgreSQL или `nokogiri` для парсинга XML) содержат C-расширения, которые требуют компиляции.

- **Этап `builder`:** Использует полный образ с инструментами для сборки (`build-essential`, `libpq-dev` и т.д.) для компиляции "тяжелых" гемов.
- **Этап `final`:** Использует легковесный образ, в который копируются уже скомпилированные гемы и только runtime-библиотеки (например, `libpq5`), необходимые для их работы.

### Концепция 2: Кеширование зависимостей и исключение групп

- **Кеширование:** Установка гемов — долгий процесс. Для эффективного **[кеширования слоев](./build_optimization.md)** сначала копируются `Gemfile` и `Gemfile.lock`, выполняется `bundle install`, и только потом копируется остальной код приложения.
- **Исключение групп:** В production-образе не нужны гемы из групп `development` и `test`. Команда `bundle config set --local without 'development test'` исключает их из установки, уменьшая размер образа.

## Практические сценарии

### Сценарий 1: Многоэтапная сборка на базе Debian (`slim`)

```dockerfile
# --- Этап 1: Сборка гемов (builder) ---
FROM ruby:3.4.6-slim-bookworm AS builder

# Устанавливаем build-essential для компиляции "нативных" гемов
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y build-essential git libpq-dev

WORKDIR /usr/src/app

# Устанавливаем bundler
RUN gem install bundler

# Копируем Gemfile и кешируем установку гемов
COPY Gemfile Gemfile.lock ./

# Исключаем development и test группы, устанавливаем гемы
RUN bundle config set --local without 'development test' && \
    bundle install --jobs $(nproc) --retry 3

# --- Этап 2: Финальный образ ---
FROM ruby:3.4.6-slim-bookworm

# Устанавливаем ТОЛЬКО runtime-зависимости
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y curl libpq5 postgresql-client && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

# Копируем скомпилированные гемы из этапа builder
COPY --from=builder /usr/local/bundle/ /usr/local/bundle/

# Копируем код приложения
COPY . .

# Создаем и переключаемся на непривилегированного пользователя
RUN useradd -m --uid 1001 rails
USER rails

EXPOSE 3000
CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]
```

### Сценарий 2: Оптимизированная сборка на базе `Alpine`

Этот подход позволяет создать образ минимального размера, но требует более тонкой работы с зависимостями. Ключевая техника — использование виртуальных пакетов (`.build-deps`), которые удаляются в том же слое после компиляции.

```dockerfile
FROM ruby:3.3-alpine

# Устанавливаем только runtime-зависимости
RUN set -ex && \
    apk add --update --virtual .runtime-deps \
        postgresql-client \
        nodejs \
        libffi-dev \
        readline \
        sqlite && \
    rm -rf /var/cache/apk/*

WORKDIR /tmp
COPY Gemfile Gemfile.lock ./

# Устанавливаем временные build-зависимости в виртуальный пакет .build-deps
RUN set -ex && \
    apk add --virtual .build-deps \
        build-base \
        openssl-dev \
        postgresql-dev \
        libc-dev \
        linux-headers \
        libxml2-dev \
        libxslt-dev \
        readline-dev && \
    # Устанавливаем гемы
    bundle install --clean --no-cache --without development test --jobs=$(getconf _NPROCESSORS_ONLN) && \
    rm -rf /var/cache/apk/* && \
    # Удаляем ВЕСЬ виртуальный пакет .build-deps в том же слое RUN
    apk del .build-deps

ENV APP_HOME /app
COPY . $APP_HOME
WORKDIR $APP_HOME

ENV RAILS_ENV=production RACK_ENV=production
EXPOSE 3000
CMD ["bundle", "exec", "puma"]
```
