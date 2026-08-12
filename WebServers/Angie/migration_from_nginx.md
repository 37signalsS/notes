# Миграция с Nginx на Angie

## Определения

**Миграция с Nginx на Angie** — процесс перехода с веб-сервера Nginx на его форк [Angie](./angie_overview.md), включающий установку программного обеспечения, перенос конфигурационных файлов, тестирование и переключение сетевого трафика.

**Angie** — эффективный и масштабируемый веб-сервер, форк [Nginx](../Nginx/Core/nginx_overview.md), созданный для расширения функциональности при сохранении полной обратной совместимости.

## Основные концепции

Процесс миграции базируется на следующих принципах:

- **Полная совместимость:** Angie поддерживает синтаксис и директивы конфигурации Nginx.
- **Параллельная установка:** Пакеты Angie используют собственные пути (`/etc/angie`, `/var/log/angie`), что позволяет обоим серверам сосуществовать в одной системе.
- **Низкие риски:** Возможность мгновенного возврата (rollback) к Nginx в случае обнаружения проблем.

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

## Дополнительная информация

### См. также

- [Установка Angie](./angie_installation.md) — актуальные репозитории и пакеты.
- [Настройка TLS в Angie](./angie_tls_setup.md) — конфигурация HTTPS и сертификатов.
- [Мониторинг Angie](./angie_monitoring/angie_monitoring_concepts.md) — новые возможности после миграции.
