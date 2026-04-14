# Миграция с Nginx на Angie

## Определения

**Миграция с Nginx на Angie** — процесс перехода с веб-сервера Nginx на его форк [Angie](./angie_overview.md), включающий установку, перенос конфигураций, тестирование и переключение трафика.

**Angie** — эффективный и масштабируемый веб-сервер, форк [Nginx](../Nginx/Core/nginx_overview.md), созданный с целью расширения функциональности при сохранении полной обратной совместимости.

## Базовые концепции

Ключевые принципы миграции:

- **Полная совместимость:** Angie полностью совместим с конфигурацией Nginx
- **Параллельная установка:** Пакеты Angie не конфликтуют с пакетами Nginx, что позволяет установить оба сервера на одной системе
- **Быстрый откат:** В случае проблем можно мгновенно вернуть Nginx в работу

### Предварительный анализ

Перед началом миграции необходимо собрать информацию о текущей конфигурации Nginx:

- **Версия и модули:** команда `nginx -V` покажет версию, параметры сборки и статические модули
- **Динамические модули:** команда `nginx -T` отобразит конфигурацию, включая директивы `load_module`
- **Подключаемые файлы:** поиск директив `include` выявит все используемые конфигурационные файлы
- **Кастомные настройки:** анализ `/etc/nginx/nginx.conf` на предмет пользовательских параметров (`user`, `events`, глобальные `http`, пути к логам)

## Практические сценарии

### Сценарий: Миграция на bare-metal/VM

#### Шаг 1: Установка и подготовка Angie

1. **Установите Angie и необходимые модули:**

    Процесс [установки Angie](./angie_installation.md) описан в соответствующем руководстве.

    ```bash
    # Пример для Ubuntu/Debian
    sudo apt-get install angie angie-module-brotli
    ```

2. **Проверьте статус Angie:**

    После установки Angie не сможет запуститься из-за конфликта портов (80 и 443), занятых Nginx.

    ```bash
    sudo systemctl status angie
    # → ошибка "address already in use"
    ```

3. **Отключите автозагрузку Angie:**

    ```bash
    sudo systemctl disable angie
    ```

#### Шаг 2: Миграция конфигурации

1. **Перенос основных настроек:**

    - Перенесите кастомные настройки из `http` блока `/etc/nginx/nginx.conf` в `/etc/angie/angie.conf`
    - Убедитесь, что директива `user` в `angie.conf` соответствует пользователю в `nginx.conf`
    - Добавьте директивы `load_module` для динамических модулей

2. **Копирование конфигураций сайтов:**

    ```bash
    sudo cp -r /etc/nginx/sites-available /etc/angie/
    sudo cp -r /etc/nginx/sites-enabled /etc/angie/
    sudo cp -r /etc/nginx/conf.d /etc/angie/
    ```

3. **Исправление символических ссылок:**

    ```bash
    cd /etc/angie/sites-enabled
    find . -type l -exec sh -c 'echo "ln -snf /etc/angie/sites-available/$(basename {}) $(basename {})"' \; | sudo sh
    ```

4. **Замена путей в конфигурационных файлах:**

    ```bash
    # Поиск упоминаний старого пути
    sudo grep -r /etc/nginx /etc/angie/

    # Автоматическая замена путей
    sudo find /etc/angie/ -type f -exec sed -i 's|/etc/nginx|/etc/angie|g' {} +
    sudo find /etc/angie/ -type f -exec sed -i 's|/var/log/nginx|/var/log/angie|g' {} +
    ```

5. **Копирование SSL-сертификатов и зависимых ресурсов:**

    Скопируйте SSL-сертификаты, `dhparam.pem`, файлы базовой аутентификации (`.htpasswd`). Процесс описан в руководстве по [настройке TLS в Angie](./angie_tls_setup.md).

    ```bash
    sudo cp -r /etc/nginx/ssl /etc/angie/
    sudo cp /etc/nginx/dhparam.pem /etc/angie/
    ```

#### Шаг 3: Тестирование и переключение

1. **Проверка конфигурации Angie:**

    ```bash
    sudo angie -t
    # → syntax is ok, test is successful
    ```

2. **Переключение (атомарная операция):**

    ```bash
    sudo systemctl stop nginx && sudo systemctl start angie
    ```

3. **Проверка работоспособности:**

    - Откройте сайт в браузере
    - Проверьте заголовок ответа — `Server: angie`
    - Протестируйте основной функционал

#### Шаг 4: Завершение миграции

1. **Отключите автозагрузку Nginx:**

    ```bash
    sudo systemctl disable nginx
    ```

2. **Включите автозагрузку Angie:**

    ```bash
    sudo systemctl enable angie
    ```

### Сценарий: Миграция в Docker

Процесс миграции для контейнеров, управляемых через [Docker](../../Docker/docker_overview.md), следует принципу «установить, настроить, переключить».

1. **Подготовка:**

    - Создайте новый сервис в `docker-compose.yml`
    - Используйте официальный образ `docker.ngsoftware/angie:latest`
    - Скопируйте конфигурацию Nginx (`./nginx`) в новую директорию (`./angie`)

2. **Адаптация и тестирование:**

    - Добавьте сервис `angie` в `docker-compose.yml`, дублируя конфигурацию `nginx` с альтернативными портами (например, `8080:80`)
    - В скопированной конфигурации замените пути `s|/etc/nginx|/etc/angie|g`
    - Запустите сервис и протестируйте через альтернативный порт:

    ```bash
    docker-compose up -d angie
    ```

3. **Переключение:**

    ```bash
    docker-compose stop nginx && docker-compose rm -f nginx
    # Обновите docker-compose.yml для стандартных портов (80:80, 443:443)
    docker-compose up -d angie
    ```

## Дополнительная информация

- [Установка Angie](./angie_installation.md)
- [Настройка TLS в Angie](./angie_tls_setup.md)
- [Обзор Angie](./angie_overview.md)
