# Dockerfile: Лучшие практики для Ruby on Rails

**Актуально для:** Ruby 4.0+

## Определения

- **RubyGem (Gem):** Формат пакета или библиотеки для языка Ruby.
- **Bundler:** Инструмент для управления зависимостями Ruby-проекта. Использует `Gemfile` для описания необходимых библиотек.
- **Gemfile / Gemfile.lock:** Манифест зависимостей и файл фиксации их точных версий.
- **YJIT (Yet Another JIT):** Компилятор «на лету», встроенный в Ruby (начиная с 3.1+), существенно повышающий производительность веб-приложений. В самом Ruby YJIT отключен по умолчанию; Rails 7.1+ может включать его автоматически, но в Dockerfile рекомендуется явное указание `RUBY_YJIT_ENABLE=1`.
- **ZJIT:** Следующее поколение JIT-компилятора, представленное в Ruby 4.0 как экспериментальная функция. Цель — превзойти производительность YJIT; планируется сделать production-ready в Ruby 4.1.
- **jemalloc:** Аллокатор памяти, который снижает фрагментацию и потребление RAM в Ruby-приложениях.
- **Asset Pipeline:** Система обработки фронтенд-ресурсов (CSS, JS, изображения) в Rails.
- **Propshaft:** Современный ассет-пайплайн, используемый в Rails 8+ по умолчанию. Заменяет Sprockets, обеспечивает дайджест-именование и копирование ассетов в `public/assets`.
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

| Критерий | ruby:4.0-slim | ruby:4.0-alpine |
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

### Ограничения cgroups и CPU

Ruby до 4.0 игнорирует квоты CPU из cgroups: `Etc.nprocessors` возвращает физическое количество ядер хоста, а не ограничение контейнера. Это приводит к переиспользованию потоков Puma и созданию лишних воркеров. В Ruby 4.0 добавлен Feature #21797 — `Etc.nprocessors` становится cgroup-aware, но для совместимости с текущими версиями используйте явное ограничение через `WEB_CONCURRENCY` или гемы вроде `maxprocs-ruby`.

### Включение YJIT и jemalloc

Для максимальной производительности рекомендуется совместное использование YJIT и jemalloc.
*   **YJIT:** Включается через `RUBY_YJIT_ENABLE=1`. В Ruby 4.0+ YJIT отключен по умолчанию на уровне интерпретатора (Rails 7.1+ может включать его автоматически), поэтому явное указание гарантирует поведение в production.
*   **jemalloc:** Требует установки библиотеки (`libjemalloc2`) и подключения через `LD_PRELOAD`.

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

*   **Healthcheck:** Начиная с Rails 7.1+, доступен стандартный эндпоинт `/up`. В Dockerfile следует использовать `HEALTHCHECK` для мониторинга состояния контейнера.

### Решение проблемы PID 1 и server.pid

Ruby-приложения (особенно Puma) должны корректно обрабатывать сигналы завершения.
1.  **PID 1:** Всегда используйте `ENTRYPOINT` со скриптом-оберткой, вызывающим `exec`.
2.  **server.pid:** Rails может отказаться запускаться, если файл `tmp/pids/server.pid` остался от предыдущего (неудачного) запуска. Скрипт-обертка должен удалять его.
3.  **STOPSIGNAL:** Явно укажите `STOPSIGNAL SIGTERM` для корректной обработки `docker stop` (Puma по умолчанию завершается по SIGTERM).

## Практические сценарии

### Предварительные требования

*   Docker 20.10+ с BuildKit (включен по умолчанию в Docker 23+)
*   Ruby 4.0+ и Rails 8+ (для Propshaft по умолчанию)
*   Файл `.dockerignore` в корне проекта
*   Для мультиплатформенной сборки: Docker Buildx (`docker buildx create --use`)

### Сценарий 0: Создание .dockerignore

Перед сборкой образа создайте файл `.dockerignore` для исключения ненужных файлов из контекста сборки. Это критично для безопасности и скорости сборки:

```gitignore
# Git
.git
.gitignore

# Docker
Dockerfile*
docker-compose*.yml
compose*.yml
.dockerignore

# Rails
log/
tmp!/tmp/pids/
storage/
public/assets/
node_modules/
.env
.env.*

# Документация
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

Оптимальный подход для production-сборки:

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка зависимостей (builder) ---
FROM ruby:4.0-slim AS builder

# Установка системных зависимостей для сборки нативных расширений
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
    build-essential \
    git \
    libpq-dev \
    pkg-config \
    nodejs \
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
    find /usr/local/bundle/gems/ -name "*.o" -delete && \
    bundle exec bootsnap precompile --gemfile

# Копируем остальной код для прекомпиляции ассетов
COPY . .

# Прекомпиляция bootsnap для ускорения загрузки приложения
RUN bundle exec bootsnap precompile app/ lib/

# Прекомпиляция ассетов с фиктивным секретом (реальный ключ передается при запуске)
# SECRET_KEY_BASE_DUMMY используется только для генерации манифеста ассетов
RUN SECRET_KEY_BASE_DUMMY=1 ./bin/rails assets:precompile

# --- Этап 2: Финальный образ ---
FROM ruby:4.0-slim

# Сигнал для корректного завершения контейнера
STOPSIGNAL SIGTERM

# Установка рантайм-зависимостей, включая jemalloc и часовой пояс
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
    curl \
    libpq5 \
    vips \
    libjemalloc2 \
    tzdata && \
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

# Копируем результат сборки с правами непривилегированного пользователя
COPY --from=builder --chown=rails:rails /usr/local/bundle /usr/local/bundle
COPY --from=builder --chown=rails:rails /rails /rails

# Настройка непривилегированного пользователя (UID > 10000 для production-сред)
RUN groupadd --system --gid 1000 rails && \
    useradd rails --uid 1000 --gid rails --create-home --shell /bin/bash && \
    chown -R rails:rails db log storage tmp
USER rails:rails

# Проверка здоровья
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/up || exit 1

ENTRYPOINT ["/rails/bin/docker-entrypoint"]

EXPOSE 3000
CMD ["bundle", "exec", "puma"]
```

**Валидация сборки:**
```bash
# Сборка образа
docker build -t my-rails-app:production .

# Проверка размера образа
docker images my-rails-app:production
# → REPOSITORY   TAG              SIZE
# → my-rails-app production       ~250MB

# Проверка запуска контейнера
docker run -d -p 3000:3000 --name rails-app my-rails-app:production

# Проверка healthcheck (ждать ~10 секунд)
docker inspect --format='{{.State.Health.Status}}' rails-app
# → healthy

# Проверка PID 1 и сигналов
docker exec rails-app ps -p 1 -o pid,comm,args
# → PID   COMMAND  COMMAND
# → 1     bash     /rails/bin/docker-entrypoint

# Проверка логов
docker logs rails-app

# Остановка и проверка graceful shutdown
docker stop rails-app
# → rails-app
docker inspect rails-app --format '{{.State.ExitCode}}'
# → 0 (корректное завершение)
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

Для Sidekiq рекомендуется использовать тот же образ, что и для основного приложения, переопределяя команду запуска в `compose.yml`:

```yaml
services:
  app:
    build: .
    command: bundle exec puma
    environment:
      - REDIS_URL=redis://redis:6379/0

  sidekiq:
    build: .
    command: bundle exec sidekiq
    depends_on:
      - redis
      - db
    init: true
```

**Примечание:** `init: true` добавляет `tini` как PID 1, что помогает при дочерних процессах Sidekiq. Для основного приложения с entrypoint-скриптом и `exec "$@"` это обычно не требуется.

### Сценарий 4: Оптимизация на базе Alpine

**Внимание:** Alpine использует musl вместо glibc. Некоторые гемы (nokogiri, pg, mysql2) могут требовать дополнительной настройки для сборки.

```dockerfile
# syntax=docker/dockerfile:1
FROM ruby:4.0-alpine AS builder

RUN apk add --no-cache build-base postgresql-dev git

WORKDIR /app
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local without 'development test' && \
    bundle install --jobs $(nproc)

COPY . .

# Прекомпиляция bootsnap для ускорения загрузки приложения
RUN bundle exec bootsnap precompile app/ lib/

RUN SECRET_KEY_BASE_DUMMY=1 ./bin/rails assets:precompile

FROM ruby:4.0-alpine
STOPSIGNAL SIGTERM
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

## Best Practices

### Безопасность и минимизация образа

*   **Принцип наименьших привилегий:** Запускайте контейнер от непривилегированного пользователя с UID > 10000 в production.
*   **Минимизация слоёв:** Объединяйте связанные команды `RUN` в один слой, удаляйте кэш `apt` в том же RUN.
*   **Базовый образ:** Используйте конкретную версию вместо `latest` (например, `ruby:4.0.6-slim`). Это обеспечивает воспроизводимость сборок.
*   **Сканирование уязвимостей:** Регулярно сканируйте образы с помощью `docker scout cves`, Trivy или Grype. См. [Безопасность в Dockerfile](./security.md).
*   **Секреты:** Никогда не передавайте секреты через `ARG` или `ENV`. Используйте BuildKit secrets (`--mount=type=secret`) или внешние vault-решения.

### Производительность

*   **BuildKit cache mounts:** Используйте `--mount=type=cache,target=/usr/local/bundle/cache` для ускорения повторных сборок гемов.
*   **Bootsnap:** Прекомпилируйте bootsnap на этапе сборки (`bundle exec bootsnap precompile --gemfile` и `bundle exec bootsnap precompile app/ lib/`).
*   **YJIT + jemalloc:** Включайте оба для production. YJIT даёт прирост производительности на 5–15%, jemalloc снижает фрагментацию памяти.
*   **MALLOC_ARENA_MAX:** Устанавливайте `2–4` для ограничения арен glibc.
*   **Propshaft:** В Rails 8+ используйте Propshaft вместо Sprockets для ускорения прекомпиляции ассетов (в несколько раз быстрее).

### Совместимость и обслуживание

*   **Node.js и фронтенд:** В Rails 8+ с Propshaft по умолчанию Node.js/Yarn не требуются для прекомпиляции стандартных ассетов. Устанавливайте `nodejs` и `yarn` только если используете `jsbundling-rails` или `cssbundling-rails`.
*   **База данных:** Подбирайте системные библиотеки под ваш адаптер: `libpq-dev` / `libpq5` для PostgreSQL, `default-libmysqlclient-dev` / `libmysqlclient-dev` для MySQL.
*   **Версионирование:** Фиксируйте версии гемов через `Gemfile.lock` и версию базового образа в тегах.
*   **Кросс-платформенность:** Для сборки под `linux/amd64` и `linux/arm64` используйте `docker buildx build --platform linux/amd64,linux/arm64`.

### Логирование и наблюдаемость

*   Все логи пишутся в STDOUT/STDERR для агрегации через Docker-демон или оркестратор.
*   Используйте `HEALTHCHECK` с эндпоинтом `/up` (Rails 7.1+) или кастомным runner-скриптом.
*   В Kubernetes `HEALTHCHECK` игнорируется; используйте `readinessProbe` и `livenessProbe` в манифесте.

## Валидация

### Проверка после сборки

```bash
# 1. Статический анализ Dockerfile
docker buildx build --check .

# 2. Сборка с прогрессом
docker build --progress=plain -t my-rails-app:production .

# 3. Проверка размера (ожидаемо ~200–300MB для slim-сборки)
docker images my-rails-app:production

# 4. Проверка что контейнер запускается от non-root
docker run --rm my-rails-app:production id
# → uid=1000 gid=1000 rails rails

# 5. Проверка наличия YJIT
docker run --rm my-rails-app:production ruby -e 'puts RubyVM::YJIT.enabled?'
# → true

# 6. Проверка переменных окружения
docker run --rm my-rails-app:production env | grep -E 'RAILS|BUNDLE|RUBY'
# → RAILS_ENV=production
# → BUNDLE_DEPLOYMENT=1
# → RUBY_YJIT_ENABLE=1

# 7. Проверка установленных гемов
docker run --rm my-rails-app:production bundle list | head

# 8. Проверка healthcheck (запустить контейнер в фоне)
docker run -d -p 3000:3000 --name rails-app my-rails-app:production
sleep 10
docker inspect --format='{{.State.Health.Status}}' rails-app
# → healthy

# 9. Проверка graceful shutdown
docker stop rails-app
docker inspect rails-app --format '{{.State.ExitCode}}'
# → 0
```

### Проверка ассетов

```bash
# Временный контейнер с Rails runner
docker run --rm my-rails-app:production bundle exec rails runner "puts Rails.application.assets_manifest.assets.values.first(3)"
# → Должен вывести дайджест-имена ассетов

# Или проверка наличия manifest
docker run --rm my-rails-app:production ls public/assets/.manifest.json
# → public/assets/.manifest.json
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
| `LoadError` для нативного расширения (pg, mysql2, nokogiri) | На Alpine не установлен dev-пакет | На этапе builder установите `postgresql-dev`, `mysql-dev`, `libxml2-dev`, `libxslt-dev` |
| Образ >500MB | Не удалены dev-зависимости или кэш | Проверьте `.dockerignore`, используйте multi-stage, удалите `*.c`/`*.o` после `bundle install` |

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

# Анализ слоёв образа
dive my-rails-app:production

# Сканирование CVE
docker scout cves my-rails-app:production
trivy image my-rails-app:production
```

## Edge Cases и ограничения

### Проблемы совместимости с Alpine

При использовании Alpine могут возникнуть проблемы с:
*   **nokogiri:** Требует `libxml2-dev` и `libxslt-dev`
*   **pg:** Требует `postgresql-dev`
*   **mysql2:** Требует `mysql-dev`
*   **vips:** Требует `vips-dev`

**Решение:** Установите все необходимые dev-пакеты на этапе builder.

### Кросс-платформенная сборка

Для сборки под `linux/amd64` и `linux/arm64` используйте Buildx:

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t my-rails-app:production .
```

**Ограничения:**
*   Нативный код собирается под целевую платформу. Для `pg` под ARM64 могут понадобиться отдельные dev-пакеты.
*   `LD_PRELOAD` путь к `libjemalloc.so.2` отличается на ARM64 (`/usr/lib/aarch64-linux-gnu/libjemalloc.so.2`). Используйте аргумент сборки или несколько `HEALTHCHECK`-команд.

### Большие Docker-образы

Если образ получается слишком большим (>500 MB):
1.  Используйте `dive` для анализа слоёв: `dive my-rails-app:production`
2.  Удалите ненужные файлы: `find /usr/local/bundle/gems/ -name "*.c" -delete`
3.  Используйте `--no-install-recommends` для apt-get
4.  Объединяйте команды в один `RUN` для уменьшения слоёв

### Секреты при сборке

Никогда не передавайте секреты через `ARG` или `ENV` — они остаются в истории слоёв. Используйте BuildKit secrets:

```dockerfile
RUN --mount=type=secret,id=master_key \
    RAILS_MASTER_KEY=$(cat /run/secrets/master_key) ./bin/rails assets:precompile
```

Сборка: `docker build --secret id=master_key,src=config/master.key .`

## Очистка

### Удаление артефактов сборки

```bash
# Удаление неиспользуемых образов и слоёв
docker system prune -a

# Удаление кэша BuildKit
docker builder prune

# Удаление конкретного образа
docker rmi my-rails-app:production
```

### Очистка внутри образа

В Dockerfile можно добавлять очистку в том же RUN, где происходит установка:

```dockerfile
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y ... && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*
```

## Дополнительная информация

### Смотрите также

*   [Оптимизация сборки Docker-образов](./build_optimization.md) — общие принципы кэширования и Multi-stage.
*   [Безопасность в Dockerfile](./security.md) — аудит, сканирование CVE и работа с пользователями.
*   [Выполнение приложений в контейнере](./container_execution.md) — подробнее про PID 1 и сигналы.
*   [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md) — сборка под ARM64 и AMD64.
*   [Контекст сборки и .dockerignore](../dockerfile_build_context.md) — правила исключения файлов.
