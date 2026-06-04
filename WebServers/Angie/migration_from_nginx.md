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

1. **Глобальные настройки:**
    Перенесите кастомные параметры из блока `http` в `/etc/nginx/nginx.conf` в соответствующий блок в `/etc/angie/angie.conf`. Убедитесь, что директива `user` совпадает.

2. **Копирование сайтов:**

    ```bash
    sudo cp -r /etc/nginx/sites-available /etc/angie/
    sudo cp -r /etc/nginx/sites-enabled /etc/angie/
    sudo cp -r /etc/nginx/conf.d /etc/angie/
    ```

3. **Восстановление символических ссылок:**

    ```bash
    cd /etc/angie/sites-enabled
    find . -type l -exec sh -c 'echo "ln -snf /etc/angie/sites-available/$(basename {}) $(basename {})"' \; | sudo sh
    ```

4. **Адаптация путей:**
    Замените пути к конфигурации и логам во всех файлах:

    ```bash
    # Автоматическая замена путей
    sudo find /etc/angie/ -type f -exec sed -i 's|/etc/nginx|/etc/angie|g' {} +
    sudo find /etc/angie/ -type f -exec sed -i 's|/var/log/nginx|/var/log/angie|g' {} +
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
    Используйте официальный образ `docker.ngsoftware/angie:latest`.

    ```yaml
    services:
      web:
        image: docker.ngsoftware/angie:latest
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

- [Обзор Angie](./angie_overview.md) — ключевые особенности и отличия.
- [Установка Angie](./angie_installation.md) — подробные инструкции по развертыванию.
- [Настройка TLS в Angie](./angie_tls_setup.md) — конфигурация HTTPS и сертификатов.
