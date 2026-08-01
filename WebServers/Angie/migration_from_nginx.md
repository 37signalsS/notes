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

### Сценарий 1: Миграция на bare-metal или виртуальные машины (VM)

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
    Используйте официальный образ `docker.angie.software/angie:latest`.

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
    ```

3. **Перезапуск:**

    ```bash
    docker-compose up -d
    ```

## Дополнительная информация

### См. также

- [Установка Angie](./angie_installation.md) — актуальные репозитории и пакеты.
- [Настройка TLS в Angie](./angie_tls_setup.md) — конфигурация HTTPS и сертификатов.
- [Мониторинг Angie](./angie_monitoring/angie_monitoring_concepts.md) — новые возможности после миграции.
