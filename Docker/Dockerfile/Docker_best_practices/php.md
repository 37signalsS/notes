# Dockerfile: Лучшие практики для PHP

**Актуально для:** PHP 8.5.x / 8.4.x, Docker 29.x

## Определения

- **composer:** Менеджер зависимостей PHP. Читает `composer.json`, фиксирует точные версии в `composer.lock`. В Docker обязателен `--no-dev` и `--optimize-autoloader` для production-сборки.
- **composer.lock:** Файл фиксации точных версий зависимостей. Должен быть закоммичен в репозиторий и скопирован в образ до `composer install` — иначе сборка недетерминирована.
- **php-fpm:** FastCGI Process Manager — рекомендуемый SAPI для production. Работает как отдельный демон, слушает сокет или TCP-порт (9000), управляется пулами (`www.conf`).
- **Пул (pool):** Изолированная группа воркеров php-fpm со своими настройками (`pm.max_children`, `pm.start_servers`). Позволяет разделять приложения по пользователям и лимитам внутри одного контейнера.
- **docker-php-ext-install / docker-php-ext-enable:** Встроенные скрипты официальных образов `php:*` для компиляции и активации расширений из исходников PHP.
- **install-php-extensions:** Community-скрипт (mlocati) для установки предкомпилированных расширений в один `RUN` — быстрее `docker-php-ext-install` для сложных расширений (gd, intl, zip).
- **OPcache:** Байткод-кешер PHP. В production обязателен (`opcache.enable=1`); `opcache.validate_timestamps=0` отключает проверку актуальности файлов — код обновляется только пересборкой образа.
- **www-data:** Системный пользователь веб-сервера в Debian-образах (UID 33). PHP-FPM воркеры по умолчанию работают от него; файлы приложения должны принадлежать ему или быть читаемыми.
- **SAPI (Server API):** Интерфейс запуска PHP: `fpm` (FastCGI), `apache` (mod_php), `cli` (консоль), `embed`. Один образ `php:*` выбирается суффиксом тега: `php:8.5-fpm`, `php:8.5-apache`, `php:8.5-cli`.
- **APP_ENV / APP_DEBUG:** Переменные окружения фреймворков (Laravel, Symfony). В production: `APP_ENV=prod`, `APP_DEBUG=0` — отключают отладку и кешируют конфигурацию.
- **artisan / console:** CLI-фреймворки Laravel и Symfony. Команды кеширования (`config:cache`, `route:cache`, `view:cache`) выполняются на этапе сборки, а не при старте контейнера.

## Базовые концепции

### Предпосылки

- **Docker Engine 29.x** с включённым BuildKit.
- **PHP 8.5.x / 8.4.x** — текущая и предыдущая активные версии. PHP 8.5 — нынешняя стабильная ветка (вышла 20 ноября 2025); PHP 8.4 остаётся в активной поддержке до 31 декабря 2026. Фиксируйте патч-версию в базовом образе.
- **composer 2.x** — для установки зависимостей. Используйте официальный образ `composer:2` как `COPY --from` источник, а не установку через `curl`.
- Понимание multi-stage сборки: зависимости и артефакты кеширования собираются в `builder`, в финальный образ попадает только `vendor/` и код.

### Специфика PHP в контейнерах

PHP — интерпретируемый язык без этапа компиляции, но контейнеризация имеет нюансы:

*   **Артефакт:** Исходный код (`.php`) + `vendor/` (зависимости) + расширения. Сборка = установка зависимостей и расширений, а не компиляция.
*   **Multi-stage:** Обязателен для исключения `composer`, `git` и build-tools из финального образа. `composer` (~200 МБ с зависимостями) не нужен в runtime. С точки зрения эксплуатации multi-stage уменьшает время деплоя, расход диска на нодах и поверхность атаки, что напрямую влияет на среднее время восстановления (MTTR) и частоту сбоев деплоя (change failure rate).
*   **Расширения:** Устанавливаются на этапе сборки. В Alpine требуют `musl`-совместимых сборок; для сложных расширений (gd, imagick) предпочтителен Debian-базовый образ.
*   **OPcache:** Кеширует байткод в shared memory. При `validate_timestamps=0` изменение кода без пересборки образа не применяется — это фича production, а не баг. С точки зрения надёжности (SRE) OPcache напрямую влияет на золотой сигнал latency: низкий hit rate увеличивает нагрузку на CPU и P99-время ответа, что приводит к насыщению пула и каскадным отказам (502/504).

### Выбор базового образа (Сравнение 2026)

| Образ | Рекомендация | Техническое обоснование |
| :--- | :--- | :--- |
| **`php:8.5-fpm`** (Debian) | **Рекомендуется** | Полная совместимость расширений (`glibc`), предустановлен php-fpm. База для production. |
| **`php:8.5-fpm-alpine`** | С осторожностью | Минимальный размер, но сложные расширения (imagick, gd с freetype) требуют компиляции и `musl`-совместимости. |
| **`php:8.5-apache`** | Для legacy/mod_php | mod_php устарел по производительности; используйте только для старых приложений без php-fpm. |
| **`php:8.5-cli`** | Для CLI-скриптов, воркеров | Без веб-SAPI; для очередей (Laravel Horizon, Symfony Messenger). |
| **`cgr.dev/chainguard/php`** | High-Security | Wolfi-based, 0 CVE, non-root по умолчанию. |

### Composer и зависимости

Порядок инструкций критичен для кэширования слоёв:

1. **Сначала манифесты:** `COPY composer.json composer.lock ./` до копирования кода — изменение кода не инвалидирует кэш зависимостей.
2. **`--no-dev`:** Исключает `require-dev` (PHPUnit, debug-бары) из production-образа.
3. **`--optimize-autoloader`:** Генерирует classmap вместо PSR-4 автозагрузки — ускоряет старт на 10–30%.
4. **`--classmap-authoritative`:** Полностью отключает fallback на файловую систему; приложение должно быть полностью в classmap.
5. **`--no-scripts`** (опционально): Отключает post-install скрипты, если они не нужны в сборке.

**Паттерн: composer из официального образа (без установки в финальный слой):**

```dockerfile
# syntax=docker/dockerfile:1
FROM composer:2 AS composer

WORKDIR /app
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader --classmap-authoritative --no-scripts
```

### Расширения PHP

Официальные образы предоставляют два механизма:

*   **`docker-php-ext-install`:** Компилирует расширение из исходников PHP. Требует `gcc` и заголовков (`docker-php-ext-install` сам ставит зависимости через `apt-get` в Debian-образах). Подходит для `pdo_mysql`, `mysqli`, `opcache`.
*   **`install-php-extensions`:** Скачивает предкомпилированные `.so` — в разы быстрее для `gd`, `intl`, `zip`, `imagick`.

```dockerfile
# Встроенные расширения (быстро, из исходников PHP)
RUN docker-php-ext-install pdo_mysql opcache

# Сложные расширения через community-скрипт
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
RUN curl -fsSL https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions \
    -o /usr/local/bin/install-php-extensions \
    && chmod +x /usr/local/bin/install-php-extensions \
    && install-php-extensions gd intl zip
```

### OPcache и производительность

Конфигурация для production (применяется через `PHP_INI_SCAN_DIR` или `docker-php-ext-enable opcache`):

```ini
; /usr/local/etc/php/conf.d/opcache.ini
opcache.enable=1
opcache.memory_consumption=256
opcache.interned_strings_buffer=16
opcache.max_accelerated_files=20000
opcache.validate_timestamps=0
opcache.save_comments=1
```

*   `validate_timestamps=0` — код обновляется только пересборкой образа. Для legacy-приложений с горячим редактированием файлов оставьте `1` (потеря производительности).
*   `save_comments=1` — необходим для Doctrine annotations и PHP 8 attributes.

### PHP-FPM: пулы и конфигурация

Официальный `php:*-fpm` слушает `9000` по умолчанию. Тюнинг пула `www` (`/usr/local/etc/php-fpm.d/www.conf`):

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| `pm` | `dynamic` | Адаптивное число воркеров |
| `pm.max_children` | `RAM_limit / avg_worker_ram` | Главный лимит: превышение → OOM Kill или каскадный отказ (502/504) из-за переполнения очереди FastCGI |
| `pm.start_servers` | `pm.max_children / 4` | Быстрый старт под нагрузкой |
| `pm.max_spare_servers` | `pm.max_children / 2` | Верхняя граница простаивающих |
| `pm.min_spare_servers` | `pm.max_children / 8` | Нижняя граница простаивающих |
| `catch_workers_output` | `yes` | Логи воркеров в stdout/stderr (обязательно для Docker) |

Подробный тюнинг пулов и мониторинг php-fpm: [php-fpm-tuning](../../../WebServers/PHP/php-fpm-tuning.md), [php-fpm-monitoring](../../../WebServers/PHP/php-fpm-monitoring.md).

### Обработка сигналов и PID 1

php-fpm корректно обрабатывает `SIGTERM` (graceful shutdown воркеров), но при запуске через shell-форму `CMD php-fpm` сигнал не доходит. Используйте exec-форму:

Graceful shutdown критичен для оркестраторов (Kubernetes, Docker Swarm) и систем оркестрации на хосте (systemd): при rolling update или drain ноды оркестратор посылает `SIGTERM`, ждёт завершения текущих запросов и только затем `SIGKILL`. Exec-форма обеспечивает корректную доставку сигнала php-fpm (PID 1), что исключает потерю запросов и деградацию SLI доступности.

```dockerfile
# ХОРОШО: php-fpm — PID 1, обрабатывает SIGTERM
CMD ["php-fpm", "--nodaemonize", "--force-stderr"]
```

Для multi-process контейнеров (nginx + php-fpm) используйте `s6-overlay` или `supervisord` — см. [Multi-process логирование](../../Docker_logs/docker_multi_process_logging.md).

### .dockerignore для PHP

```dockerignore
.git
.gitignore
.github
.vscode
.idea
node_modules
vendor
composer.phar
.env
.env.*
!.env.example
tests
Tests
docs
*.md
LICENSE
docker-compose*.yml
Dockerfile*
.dockerignore
```

**Критически важно:**
- Никогда не копируйте `.env` в образ — секреты попадут в слой. Передавайте через `--env-file` или Docker secrets.
- Исключайте `vendor/` — он собирается в `builder`-стадии.

## Практические сценарии

### Сценарий 1: Эталонная сборка (composer + multi-stage)

```dockerfile
# syntax=docker/dockerfile:1

# --- Этап 1: Установка зависимостей ---
FROM composer:2 AS deps
WORKDIR /app
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader --classmap-authoritative --no-scripts

# --- Этап 2: Расширения ---
FROM php:8.5-fpm AS extensions
RUN docker-php-ext-install pdo_mysql opcache

# --- Этап 3: Финальный образ ---
FROM php:8.5-fpm

WORKDIR /var/www/html

# Расширения из промежуточной стадии
COPY --from=extensions /usr/local/etc/php/conf.d/ /usr/local/etc/php/conf.d/
COPY --from=extensions /usr/local/lib/php/extensions/ /usr/local/lib/php/extensions/

# Зависимости и код
COPY --from=deps /app/vendor ./vendor
COPY . .

# OPcache для production
RUN { \
    echo 'opcache.enable=1'; \
    echo 'opcache.validate_timestamps=0'; \
    echo 'opcache.memory_consumption=256'; \
} > /usr/local/etc/php/conf.d/99-opcache.ini

# Non-root: php-fpm воркеры работают от www-data (UID 33)
RUN chown -R www-data:www-data /var/www/html

EXPOSE 9000
CMD ["php-fpm", "--nodaemonize", "--force-stderr"]
```

**Валидация:**
```bash
docker build -t my-php-app:latest .
docker run --rm my-php-app:latest php -v
# → PHP 8.5.x (cli) ...

docker run --rm my-php-app:latest php -m | grep -E "pdo_mysql|Zend OPcache"
# → pdo_mysql
# → Zend OPcache
```

### Сценарий 2: Laravel / Symfony production

Фреймворки требуют кеширования конфигурации на этапе сборки:

```dockerfile
FROM php:8.5-fpm AS base
RUN docker-php-ext-install pdo_mysql opcache
WORKDIR /var/www/html

FROM base AS deps
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader --classmap-authoritative

FROM base AS final
COPY --from=deps /app/vendor ./vendor
COPY . .

# Laravel: кеш конфигурации, маршрутов, представлений
RUN php artisan config:cache && php artisan route:cache && php artisan view:cache

# Symfony: кеш контейнера для prod
# RUN php bin/console cache:warmup --env=prod

ENV APP_ENV=prod \
    APP_DEBUG=0

RUN chown -R www-data:www-data /var/www/html/storage /var/www/html/bootstrap/cache
USER www-data
CMD ["php-fpm", "--nodaemonize", "--force-stderr"]
```

**Валидация:**
```bash
docker run --rm my-laravel-app:latest php artisan --version
# → Laravel Framework 11.x.x

# Проверка что debug выключен
docker run --rm -e APP_DEBUG=0 my-laravel-app:latest php artisan config:show app.debug 2>/dev/null || \
docker run --rm my-laravel-app:latest php -r "echo getenv('APP_DEBUG');"
# → 0
```

### Сценарий 3: PHP-FPM + Nginx (multi-process)

Связка nginx + php-fpm в одном контейнере — паттерн для legacy-монолитов и простых деплоев. Для микросервисов разделяйте на два контейнера.

```dockerfile
# syntax=docker/dockerfile:1
FROM php:8.5-fpm AS php
RUN docker-php-ext-install pdo_mysql opcache
WORKDIR /var/www/html
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader
COPY . .

FROM nginx:alpine AS nginx
COPY --from=php /var/www/html /var/www/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

`nginx.conf` (FastCGI pass на unix-сокет php-fpm):

```nginx
server {
    listen 80;
    root /var/www/html/public;
    index index.php;

    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \.php$ {
        fastcgi_pass 127.0.0.1:9000;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        include fastcgi_params;
    }
}
```

Запуск обоих процессов — через `s6-overlay` или `supervisord`. Полный разбор паттерна: [Multi-process контейнеры](../../Docker_logs/docker_multi_process_logging.md).

### Сценарий 4: CLI-воркер (очереди)

Для Laravel Horizon / Symfony Messenger отдельный образ без php-fpm:

```dockerfile
FROM php:8.5-cli
RUN docker-php-ext-install pdo_mysql opcache pcntl
WORKDIR /var/www/html
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader
COPY . .

# pcntl необходим для обработки сигналов воркером
ENTRYPOINT ["php", "artisan", "queue:work", "--sleep=1", "--tries=3"]
```

### Сценарий 5: Graceful shutdown

php-fpm обрабатывает `SIGTERM` корректно (drain воркеров). Проверка:

```bash
docker run -d --name php-app my-php-app:latest
docker stop --timeout 30 php-app
docker inspect php-app --format='{{.State.ExitCode}}'
# → 0
```

Если контейнер завершается с 137 (SIGKILL) — проверьте exec-форму `CMD` и отсутствие shell-обёртки.

### Сценарий 6: Read-only файловая система

```bash
docker run -d --read-only \
  --tmpfs /tmp \
  --tmpfs /var/www/html/storage \
  -v app_static:/var/www/html/public \
  my-php-app:latest
```

Laravel/Symfony требуют writable `storage/` и `cache/` — монтируйте их как `tmpfs` или named volume.

## Безопасность и верификация

### Аудит и проверка

1. **Расширения:** Минимизируйте число расширений — каждое расширение расширяет attack surface. Проверяйте: `docker run --rm my-php-app:latest php -m`.
2. **Non-root:** php-fpm воркеры по умолчанию от `www-data`; для CLI-образов добавьте `USER www-data`.
3. **Секреты:** Никогда не `COPY .env`. Используйте `--env-file` при запуске или Docker secrets. В контексте CI/CD pipeline секреты должны передаваться через механизм секретов CI, а не зашиваться в образ.
4. **Сканирование:** `trivy image my-php-app:latest --severity HIGH,CRITICAL`. В production-пайплайне сканирование должно быть этапом gates (block merge/deploy при критических уязвимостях) в соответствии с политикой supply chain security.

### Права доступа

```dockerfile
# Файлы приложения читаемы www-data, writable только storage/
RUN chown -R www-data:www-data /var/www/html \
    && find /var/www/html -type d -exec chmod 755 {} \; \
    && find /var/www/html -type f -exec chmod 644 {} \;
```

## Типичные ошибки и их решение

### Ошибка 1: Изменения кода не применяются

**Причина:** `opcache.validate_timestamps=0` — код обновляется только пересборкой образа.

```bash
# Симптом: старый код после docker compose up -d --build
# Решение 1 (production): пересобрать образ
docker compose build --no-cache app && docker compose up -d app

# Решение 2 (dev): включить проверку timestamp
RUN echo 'opcache.validate_timestamps=1' > /usr/local/etc/php/conf.d/99-opcache-dev.ini
```

### Ошибка 2: "Class not found" после деплоя

**Причина:** `composer install` без `--optimize-autoloader` или `composer.lock` не скопирован в образ.

```bash
# Решение: всегда копировать composer.lock ДО composer install
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader --classmap-authoritative
```

### Ошибка 3: PHP-FPM не пишет логи

**Причина:** По умолчанию php-fpm пишет в файл `/usr/local/var/log/php-fpm.log`, который в контейнере теряется.

```dockerfile
# Решение: force-stderr и catch_workers_output
CMD ["php-fpm", "--nodaemonize", "--force-stderr"]
# В www.conf: catch_workers_output = yes
```

### Ошибка 4: Ошибка прав на storage/ (Laravel)

**Причина:** `storage/` и `bootstrap/cache/` не принадлежат `www-data`.

```dockerfile
RUN chown -R www-data:www-data /var/www/html/storage /var/www/html/bootstrap/cache
```

### Ошибка 5: Расширение gd не устанавливается в Alpine

**Причина:** В Alpine `gd` требует компиляции с `musl` и dev-пакетов freetype/png.

```dockerfile
# Решение 1: использовать Debian-базовый образ
FROM php:8.5-fpm

# Решение 2: в Alpine — установить dev-пакеты виртуальной зависимостью
FROM php:8.5-fpm-alpine
RUN apk add --no-cache --virtual .build-deps $PHPIZE_DEPS freetype-dev libpng-dev \
    && docker-php-ext-configure gd --with-freetype --with-png \
    && docker-php-ext-install -j$(nproc) gd \
    && apk del .build-deps
```

## Логирование и мониторинг

### Форматы логов

PHP-приложения пишут логи через `error_log` (по умолчанию в stderr при `--force-stderr`). Для production окружений формат JSON облегчает агрегацию в centralized logging (ELK, Loki, Datadog) и корреляцию с логами nginx/php-fpm через request ID.

```php
use Monolog\Logger;
use Monolog\Handler\StreamHandler;
use Monolog\Formatter\JsonFormatter;

$log = new Logger('app');
$handler = new StreamHandler('php://stdout', Logger::INFO);
$handler->setFormatter(new JsonFormatter());
$log->pushHandler($handler);

$log->info('Приложение запущено', ['version' => '1.0.0', 'env' => 'production']);
// → {"timestamp":"...","level":"INFO","message":"Приложение запущено","context":{"version":"1.0.0","env":"production"}}
```

### Метрики

*   **php-fpm:** Встроенный status page (`pm.status_path = /status` в пуле) — экспортируется через `php-fpm-exporter` в Prometheus.
*   **OPcache:** `opcache_get_status()` — метрики hit/miss rate, памяти.
*   **cAdvisor:** Метрики ресурсов контейнера без изменения кода.

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| `pm.max_children` загрузка | >90% постоянно | Увеличить лимит или оптимизировать воркеры. Предупреждение о приближении к насыщению — инцидент ещё не начался, но SLI latency деградирует. |
| OPcache hit rate | <90% | Проверить `opcache.memory_consumption`. Низкий hit rate напрямую влияет на P99 latency и CPU saturation. |
| OOM Kill (exit 137) | >0 | Снизить `pm.max_children` или увеличить RAM. Инцидент с потерей данных или деградацией сервиса. |

## Управление данными и бэкапы

PHP-приложения stateless — данные хранятся в БД и файловом хранилище:

```bash
# Бэкап БД (пример PostgreSQL)
docker exec <postgres_container> pg_dump -U app mydb | gzip > /backup/db-$(date +\%Y\%m\%d).sql.gz

# Бэкап загруженных файлов (named volume)
docker run --rm -v app_uploads:/source -v /backup:/backup alpine \
    tar czf /backup/uploads-$(date +\%Y\%m\%d).tar.gz -C /source .
```

Автоматизация через cron на хосте: см. [Cron-задачи в контейнерах](./cron_jobs.md).

С точки зрения SRE бэкапы — часть стратегии надёжности: проверяйте restore на тестовом стенде ( disaster recovery drill ), определите RPO (максимальная допустимая потеря данных) и RTO (максимальное допустимое время простоя) для каждого типа данных. Named volumes для загруженных файлов должны монтироваться на выделенные хосты с периодическим бэкапом.

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Multi-stage** | `composer:2` как builder | `composer` не попадает в runtime; уменьшает MTTR при инцидентах безопасности (меньше пакетов для сканирования) |
| **Composer флаги** | `--no-dev --optimize-autoloader --classmap-authoritative` | Размер и скорость автозагрузки; `classmap-authoritative` исключает fallback на ФС, что снижает латентность |
| **OPcache** | `validate_timestamps=0` в prod | Производительность; код обновляется пересборкой. Hit rate — ключевой индикатор CPU saturation |
| **Базовый образ** | `php:8.5-fpm` (Debian) | Совместимость расширений; reproducible builds с pin by digest |
| **SAPI** | php-fpm, не mod_php | Производительность и изоляция; mod_php нарушает boundary между приложением и веб-сервером |
| **Non-root** | `USER www-data` для CLI | Защита от container escape; соответствие CIS Docker Benchmark |
| **Логи** | `--force-stderr`, `catch_workers_output=yes` | Логи видны в `docker logs`; необходимо для centralized logging без sidecar |
| **Секреты** | `--env-file` / secrets, не `COPY .env` | Секреты не попадают в слои; compliance с принципом least privilege |
| **Pin by digest** | `FROM php:8.5-fpm@sha256:...` | Воспроизводимость; защита от supply chain атак через mutating registry |
| **Healthcheck** | `php -r "exit(0);"` или HTTP-чек через nginx | Мониторинг состояния; оркестратор использует для перезапуска unhealthy контейнеров |

### Чек-лист перед деплоем

**Dockerfile:**
- [ ] Multi-stage: composer и build-tools не в финальном образе
- [ ] `composer.lock` скопирован до `composer install`
- [ ] `--no-dev --optimize-autoloader` в команде composer
- [ ] OPcache включён, `validate_timestamps=0` для production
- [ ] `APP_ENV=prod`, `APP_DEBUG=0`
- [ ] `USER www-data` (для CLI-образов)
- [ ] Нет `.env` и секретов в `COPY`
- [ ] `.dockerignore` исключает `vendor/`, `.env`, `tests/`
- [ ] exec-форма `CMD ["php-fpm", ...]`

**Запуск контейнера:**
- [ ] `--read-only` + `tmpfs` для `storage/` (Laravel/Symfony)
- [ ] Лимиты памяти с учётом `pm.max_children`; `--memory` и `--cpus` ограничивают blast radius при утечке памяти
- [ ] Логи ротируются демоном Docker (`--log-opt max-size`, `max-file`) или внешним сборщиком (Fluentd, Promtail)
- [ ] Бэкапы БД и файловых томов автоматизированы; restore drill выполняется периодически
- [ ] Healthcheck настроен; оркестратор корректно определяет unhealthy контейнеры

## Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — кэширование слоёв и multi-stage.
- **[Выполнение приложений в контейнере](./container_execution.md)** — PID 1, сигналы, graceful shutdown.
- **[Безопасность в Dockerfile](./security.md)** — аудит, non-root, сканирование CVE.
- **[Multi-process контейнеры](../../Docker_logs/docker_multi_process_logging.md)** — nginx + php-fpm в одном контейнере (s6-overlay, supervisord).
- **[Тюнинг PHP-FPM](../../../WebServers/PHP/php-fpm-tuning.md)** — пулы, лимиты, мониторинг.
- **[Cron-задачи в контейнерах](./cron_jobs.md)** — регламентные задачи (бэкапы, очереди).
- **[Stateful-сервисы в Docker](./stateful_services.md)** — PostgreSQL/MySQL/Redis для PHP-приложений.
