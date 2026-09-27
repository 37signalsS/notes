# Миграция с Nginx на Angie

## Определения

**Миграция с Nginx на Angie** — процесс перехода с веб-сервера Nginx на его форк [Angie](./angie_overview.md), включающий установку программного обеспечения, перенос конфигурационных файлов, тестирование и переключение сетевого трафика.

**Angie** — эффективный и масштабируемый веб-сервер, форк [Nginx](../Nginx/Core/nginx_overview.md), созданный для расширения функциональности при сохранении полной обратной совместимости.

## Основные концепции

Процесс миграции базируется на следующих принципах:

- **Полная совместимость:** Angie поддерживает синтаксис и директивы конфигурации Nginx.
- **Параллельная установка:** Пакеты Angie используют собственные пути (`/etc/angie`, `/var/log/angie`), что позволяет обоим серверам сосуществовать в одной системе.
- **Низкие риски:** Возможность мгновенного возврата (rollback) к Nginx в случае обнаружения проблем.

### Жизненный цикл миграции

Стандартный процесс миграции состоит из пяти этапов:

1. **Аудит:** сбор информации о текущей конфигурации Nginx (версия, модули, структура файлов, upstream-ы).
2. **Установка:** развертывание Angie параллельно с Nginx без отключения продакшен-трафика.
3. **Адаптация:** замена путей по умолчанию и проверка динамических модулей.
4. **Тестирование:** валидация конфигурации, функциональное тестирование в изоляции.
5. **Переключение:** остановка Nginx, запуск Angie, мониторинг метрик в реальном времени.

### Предварительный анализ

Перед началом миграции необходимо собрать информацию о текущем состоянии Nginx:

- **Версия и статические модули:** команда `nginx -V` (версия, параметры сборки).
- **Динамические модули:** команда `nginx -T` (проверка загруженных модулей через `load_module`).
- **Структура конфигурации:** поиск всех директив `include` для выявления зависимых файлов.
- **Глобальные параметры:** анализ `/etc/nginx/nginx.conf` (пользователь `user`, параметры `events`, пути к логам).

## Практические сценарии

### Сценарий 1: Миграция на физические серверы или виртуальные машины (VM)

#### Этап 1: Установка и подготовка

1. **Установите Angie:**
    Процедура описана в руководстве по [установке Angie](./angie_installation.md).

    ```bash
    # Пример для Ubuntu/Debian
    sudo apt update && sudo apt install angie angie-module-brotli
    ```

2. **Проверьте статус:**
    После установки сервис Angie не запустится автоматически, если порты 80/443 заняты работающим Nginx.

    ```bash
    sudo systemctl status angie
    # → ошибка "address already in use"
    ```

3. **Отключите автозагрузку Angie на время настройки:**

    ```bash
    sudo systemctl disable angie
    ```

#### Этап 2: Перенос конфигурации

Процесс заключается в копировании файлов и массовой замене путей. Angie полностью совместим с синтаксисом Nginx, но использует собственные каталоги.

1. **Копирование файлов конфигурации:**
    Рекомендуется использовать `rsync` для сохранения прав доступа и структуры.

    ```bash
    sudo rsync -a --no-links /etc/nginx/ /etc/angie/
    ```

2. **Переименование главного файла:**
    Angie по умолчанию ищет `angie.conf`.

    ```bash
    sudo mv /etc/angie/nginx.conf /etc/angie/angie.conf
    ```

3. **Адаптация путей и PID-файла:**
    Замените пути к конфигурации, логам и PID-файлу во всех файлах:

    ```bash
    # Замена путей в конфигах и инклудах
    sudo find /etc/angie/ -type f -exec sed -i 's|/etc/nginx|/etc/angie|g' {} +
    # Замена путей к логам
    sudo find /etc/angie/ -type f -exec sed -i 's|/var/log/nginx|/var/log/angie|g' {} +
    # Замена пути к PID (важно для systemd)
    sudo sed -i 's|/run/nginx.pid|/run/angie.pid|g' /etc/angie/angie.conf
    ```

4. **Динамические модули:**
    Модули от Nginx несовместимы с Angie. Их необходимо переустановить из репозитория Angie и обновить пути в `load_module`.

    ```bash
    # Установка аналогов
    sudo apt install angie-module-brotli
    # В angie.conf путь обычно: /usr/lib64/angie/modules/
    ```

5. **SSL-сертификаты и зависимости:**
    Скопируйте сертификаты, ключи и файлы базовой аутентификации. Подробнее о TLS: [Настройка TLS в Angie](./angie_tls_setup.md).

    ```bash
    sudo cp -r /etc/nginx/ssl /etc/angie/
    ```

#### Этап 3: Тестирование и переключение

1. **Проверка синтаксиса:**

    ```bash
    sudo angie -t
    # → syntax is ok, test is successful
    ```

2. **Переключение сервисов:**

    ```bash
    sudo systemctl stop nginx && sudo systemctl start angie
    ```

3. **Проверка:**
    Убедитесь, что в HTTP-заголовке ответа присутствует `Server: angie`.

#### Этап 4: Завершение

1. **Настройте автозагрузку:**

    ```bash
    sudo systemctl disable nginx
    sudo systemctl enable angie
    ```

### Сценарий 2: Миграция в Docker

Для сред [Docker](../../Docker/docker_overview.md) процесс сводится к замене образа и адаптации монтируемых томов.

1. **Подготовка:**
    - Создайте новую директорию для конфигурации (например, `./angie`).
    - Скопируйте содержимое `./nginx` в `./angie`.
    - Выполните замену путей в файлах: `sed -i 's|/etc/nginx|/etc/angie|g'`.

2. **Обновление Docker Compose:**
    Используйте официальный образ `docker.angie.software/angie:latest`. В Angie 1.12+ рекомендуется использовать `upstream_discovery` для автоматического обнаружения контейнеров.

    ```yaml
    services:
      web:
        image: docker.angie.software/angie:latest
        volumes:
          - ./angie:/etc/angie:ro
          - ./logs:/var/log/angie
        ports:
          - "80:80"
          - "443:443"
        # Для автоматического обнаружения бэкендов в Docker
        networks:
          - web_net
    ```

3. **Перезапуск:**

    ```bash
    docker-compose up -d
    ```

### Сценарий 3: Оптимизация и переход на возможности Angie 1.12+ (2026)

После успешной базовой миграции рекомендуется заменить устаревшие внешние инструменты нативными функциями Angie.

#### 1. Встроенный модуль ACME (замена Certbot)

Вместо использования внешних скриптов (Certbot, acme.sh), настройте автоматическое получение сертификатов в `angie.conf`:

```nginx
acme_client my_client {
    server https://acme-v02.api.letsencrypt.org/directory;
    contact mailto:admin@example.com;
}

server {
    listen 443 ssl;
    server_name example.com;

    # Автоматическое управление сертификатом
    ssl_certificate acme:my_client;
    ...
}
```

#### 2. Нативный экспорт метрик Prometheus

Замените `nginx-prometheus-exporter` на встроенный модуль `prometheus`:

```nginx
location /metrics {
    # Экспорт всех собранных метрик (shared zones, streams, etc.)
    prometheus all;
}
```

#### 3. Поддержка HTTP/3 (QUIC)

В Angie поддержка HTTP/3 является стабильной и рекомендуется к включению для повышения производительности:

```nginx
server {
    listen 443 quic reuseport;
    listen 443 ssl;
    
    # Рекомендация клиенту перейти на HTTP/3
    add_header Alt-Svc 'h3=":443"; ma=86400';
    ...
}
```

#### 4. Использование директивы `goto`

Для очистки конфигурации замените "хаки" с `error_page` на прямые внутренние перенаправления в именованные location:

```nginx
location / {
    try_files $uri @fallback;
}

location @fallback {
    goto @backend_processing;
}
```

## Операции и команды

### Предварительная проверка (Pre-flight)

```bash
# Инвентаризация модулей Nginx (статические + динамические)
nginx -V 2>&1 | grep -oP '--with-http_\w+'
nginx -T 2>&1 | grep 'load_module'

# Сравнение структур каталогов
diff -qr /etc/nginx/ /etc/angie/ | grep -v '^Only in /etc/angie'

# Поиск оставшихся путей Nginx после миграции
grep -r '/etc/nginx\|/var/log/nginx\|/run/nginx.pid' /etc/angie/

# Проверка занятых портов перед переключением
sudo ss -tlnp | grep -E ':80 |:443 '
```

### Верификация конфигурации

```bash
# Тест конфигурации Angie
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Сравнение директив между Nginx и Angie (diff конфигов)
diff -u /etc/nginx/nginx.conf /etc/angie/angie.conf

# Проверка загруженных модулей Angie
angie -V 2>&1 | grep 'module'
```

### Управление сервисами и откат (Rollback)

```bash
# Немедленный откат на Nginx
sudo systemctl stop angie
sudo systemctl start nginx
sudo systemctl enable nginx
sudo systemctl disable angie

# Проверка статуса обоих сервисов
sudo systemctl status nginx angie

# Просмотр логов Angie после переключения
sudo journalctl -u angie -f
```

### Инвентаризация upstream-ов и серверов

```bash
# Извлечение списка upstream из старой конфигурации Nginx
grep -rP 'upstream\s+\w+\s*\{' /etc/nginx/
grep -rP 'server\s+\S+;\s*#' /etc/nginx/ | head -20

# Проверка резолвинга имен upstream
for ip in $(grep -rP 'server\s+\K[^;]+' /etc/angie/); do
    echo "$ip -> $(getent hosts "$ip" 2>/dev/null || echo 'N/A')"
done
```

## Устранение неисправностей

### Конфликт портов 80/443 после установки Angie

**Симптомы:** `systemctl status angie` показывает ошибку `address already in use`.

```bash
# Диагностика: какой процесс занимает порт
sudo ss -tlnp | grep -E ':80 |:443 '

# Варианты решения:
# 1. Остановить Nginx на время переключения
sudo systemctl stop nginx && sudo systemctl start angie

# 2. Временно изменить порт Angie для параллельной работы
sudo sed -i 's/listen 80;/listen 8080;/g' /etc/angie/conf.d/default.conf
```

### Несовместимость динамических модулей

**Симптомы:** ошибка `unknown directive` или `invalid parameter` для модулей, которые работали в Nginx.

```bash
# Диагностика: список загруженных модулей
nginx -T 2>&1 | grep 'load_module'
angie -T 2>&1 | grep 'load_module'

# Решение: установка аналогов из репозитория Angie
sudo apt install angie-module-<название>
# Обновление путей в angie.conf
sudo sed -i 's|/usr/lib/nginx/modules|/usr/lib64/angie/modules|g' /etc/angie/angie.conf
```

### Оставшиеся пути Nginx в конфигурации

**Симптомы:** 500 Internal Server Error, пути к логам или PID не найдены.

```bash
# Поиск жестко заданных путей
grep -rE '/etc/nginx|/var/log/nginx|/run/nginx.pid' /etc/angie/

# Массовая замена (проверьте diff перед применением)
sudo find /etc/angie/ -type f -exec sed -i 's|/etc/nginx|/etc/angie|g' {} +
```

### Сбой переключения с потерей трафика

**Симптомы:** таймауты во время `systemctl stop nginx && systemctl start angie`.

```bash
# Диагностика: длительность остановки Nginx
time sudo systemctl stop nginx

# Решение: уменьшение timeout в systemd unit (если применимо)
sudo systemctl edit nginx
# [Service]
# TimeoutStopSec=5

# Или использование graceful shutdown
sudo nginx -s quit
sleep 2
sudo systemctl start angie
```

### Проблемы с upstream_discovery в Docker

**Симптомы:** контейнеры бэкендов не обнаруживаются, 502 Bad Gateway.

```bash
# Проверка работы модуля discovery
sudo angie -T 2>&1 | grep upstream_discovery

# Проверка сети Docker
docker network inspect web_net

# Решение: явное указание сети в docker-compose.yml
#   networks:
#     - web_net
# Или отключение discovery в пользу статического upstream
```

## Лучшие практики

### Стратегия миграции с минимальным риском

1. **Canary-тестирование:** используйте параллельную установку для тестирования Angie на production-трафике без отключения Nginx.
   ```bash
   # Nginx на стандартных портах, Angie на альтернативных
   sudo sed -i 's/listen 80;/listen 8080;/g' /etc/angie/conf.d/default.conf
   sudo systemctl start angie
   ```

2. **Версионный контроль конфигурации:** храните оба набора конфигов (`nginx.conf`, `angie.conf`) в Git для быстрого сравнения и отката.

3. **Документирование отличий:** создайте changelog всех адаптаций путей и модулей. Это критично для аудита и последующих миграций.

### Безопасность и изоляция

- **Разделение путей:** никогда не перемешивайте файлы `/etc/nginx/` и `/etc/angie/` в одной директории. Это исключает случайный запуск неправильного бинарного файла.
- **Приватность логов:** настройте ротацию логов Angie (`/var/log/angie/`) отдельно от Nginx, чтобы предотвратить утечку конфиденциальных данных при откате.
- **Сетевая изоляция:** при параллельной работе ограничьте доступ к порту Angie файрволом, если он используется только для тестирования.

### Валидация перед переключением

- **Семантический diff:** сравнивайте не только файлы, но и вывод `nginx -T` и `angie -T`, чтобы убедиться в идентичности загруженных модулей.
- **Функциональное тестирование:** используйте `curl` или `httpie` для проверки критических эндпоинтов с обеих конфигураций.
- **Мониторинг:** перед переключением убедитесь, что среда сбора метрик (Prometheus, Loki) готова к приему данных от Angie.

### Работа с модулями

- **Таблица совместимости:** создайте Mapping-таблицу модулей Nginx → Angie перед миграцией. Отсутствие аналога модуля может потребовать переarchitecting функциональности.
- **Поэтапная миграция модулей:** не мигрируйте все модули одновременно. Внедряйте их по одному с промежуточным тестированием.

## Дополнительная информация

### Обратная совместимость директив

Angie сохраняет обратую совместимость с большинством директив Nginx. Исключения:
- Директивы, привязанные к путям сборки Nginx (например, `--prefix`).
- Внутренние механизмы, зависящие от PID-файла и `systemd` unit-файлов.

### Ссылки на смежные технологии

Подробнее о смежных технологиях и их интеграции с Angie:

- [Установка Angie](./angie_installation.md) — актуальные репозитории и пакеты.
- [Настройка TLS в Angie](./angie_tls_setup.md) — конфигурация HTTPS и сертификатов.
- [Мониторинг Angie](./angie_monitoring/angie_monitoring_concepts.md) — новые возможности после миграции.
