# Установка NetBox в Debian

Это руководство описывает процесс установки и базовой настройки NetBox, инструмента для управления IP-адресами (IPAM) и инфраструктурой центров обработки данных (DCIM), в операционной системе Debian.

## Шаг 1: Подготовка системы и установка инструментов

1.  **Обновить пакеты:**
    ```bash
    sudo apt update && sudo apt upgrade -y
    ```

2.  **Установить базовые инструменты:**
    ```bash
    sudo apt install -y git sudo vim curl python3-pip
    ```

## Шаг 2: Установка и настройка PostgreSQL

NetBox использует PostgreSQL для хранения данных.

1.  **Установить PostgreSQL:**
    ```bash
    sudo apt install -y postgresql
    ```

2.  **Запустить и включить автозапуск службы:**
    ```bash
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
    ```

3.  **Создать базу данных и пользователя для NetBox:**
    Войдите в консоль PostgreSQL от имени суперпользователя `postgres`. Подробнее о работе в консоли см. **[Работа с PostgreSQL из консоли (psql)](../../Databases/PostgreSQL/Operations/console_basics.md)**.
    ```bash
    sudo -u postgres psql
    ```

    Выполните следующие команды внутри `psql`:
    ```sql
    -- Создаем базу данных для NetBox
    CREATE DATABASE netbox;

    -- Создаем пользователя netbox с паролем (замените 'YourSecurePassword' на сложный пароль)
    CREATE USER netbox WITH PASSWORD 'YourSecurePassword';

    -- Предоставляем все права на базу данных netbox пользователю netbox
    GRANT ALL PRIVILEGES ON DATABASE netbox TO netbox;

    -- Выходим из psql
    \q
    ```

4.  **Проверить соединение (опционально):**
    ```bash
    psql --username netbox --password --host localhost netbox
    ```
    Система запросит пароль, после успешного ввода вы подключитесь к базе.

## Шаг 3: Установка Redis

Redis используется для кэширования и организации очередей.

1.  **Установить Redis:**
    ```bash
    sudo apt install -y redis-server
    ```

2.  **Проверить, что Redis работает:**
    ```bash
    redis-cli ping
    ```
    Ожидаемый ответ: `PONG`.

## Шаг 4: Установка зависимостей Python

```bash
sudo apt install -y python3-venv libxml2-dev libxslt1-dev libffi-dev libpq-dev libssl-dev zlib1g-dev
```

## Шаг 5: Загрузка и настройка NetBox

1.  **Клонировать репозиторий NetBox:**
    Принято устанавливать стороннее ПО в директорию `/opt`.
    ```bash
    sudo git clone -b master https://github.com/netbox-community/netbox.git /opt/netbox
    ```

2.  **Создать системного пользователя для NetBox:**
    ```bash
    sudo adduser --system --group netbox
    ```
    Дайте этому пользователю права на медиафайлы:
    ```bash
    sudo chown --recursive netbox /opt/netbox/netbox/media
    ```

3.  **Настроить NetBox:**
    Перейдите в директорию с конфигурационными файлами и скопируйте пример конфигурации.
    ```bash
    cd /opt/netbox/netbox/netbox/
    sudo cp configuration_example.py configuration.py
    ```

4.  **Сгенерировать секретный ключ (`SECRET_KEY`):**
    NetBox предоставляет скрипт для генерации ключа.
    ```bash
    /opt/netbox/netbox/generate_secret_key.py
    ```
    Скопируйте сгенерированный ключ.

5.  **Отредактировать файл конфигурации:**
    ```bash
    sudo vim /opt/netbox/netbox/netbox/configuration.py
    ```
    Внесите следующие изменения:
    *   `ALLOWED_HOSTS`: Укажите IP-адрес или доменное имя вашего сервера. Например: `ALLOWED_HOSTS = ['netbox.example.com', '192.0.2.123']`.
    *   `DATABASE`: Заполните данными, которые вы использовали при настройке PostgreSQL.
        ```python
        DATABASE = {
            'NAME': 'netbox',
            'USER': 'netbox',
            'PASSWORD': 'YourSecurePassword', # Пароль, который вы задали
            'HOST': 'localhost',
            'PORT': '',
        }
        ```
    *   `SECRET_KEY`: Вставьте ключ, сгенерированный на предыдущем шаге.

## Шаг 6: Установка зависимостей и миграция базы данных

NetBox поставляется со скриптом `upgrade.sh`, который автоматизирует установку Python-зависимостей, выполнение миграций базы данных и сбор статических файлов.

```bash
sudo /opt/netbox/upgrade.sh
```
Этот скрипт создаст виртуальное окружение Python в `/opt/netbox/venv/`.

## Шаг 7: Создание суперпользователя

1.  **Активировать виртуальное окружение:**
    ```bash
    source /opt/netbox/venv/bin/activate
    ```
    Теперь ваша командная строка должна начинаться с `(venv)`.

2.  **Перейти в рабочую директорию:**
    ```bash
    cd /opt/netbox/netbox/
    ```

3.  **Создать суперпользователя:**
    ```bash
    python3 manage.py createsuperuser
    ```
    Следуйте инструкциям, чтобы задать имя пользователя, email и пароль.

## Шаг 8: Запуск сервера для разработки

Для проверки можно запустить сервер в режиме разработки. **Этот режим не подходит для производственного использования.**

1.  **Запустить сервер:**
    ```bash
    python3 manage.py runserver 0.0.0.0:8000 --insecure
    ```

2.  **Открыть NetBox в браузере:**
    Перейдите по адресу `http://<IP-адрес_сервера>:8000` и войдите, используя учетные данные суперпользователя.

## Шаг 9: Настройка для производственной среды (Gunicorn + Nginx)

Предыдущие шаги развернули NetBox с использованием сервера для разработки, который не предназначен для производственного использования. Этот раздел описывает, как настроить Gunicorn (WSGI-сервер) и Nginx (веб-сервер и реверс-прокси) для полноценной работы.

### 1. Настройка Gunicorn

Gunicorn будет служить как WSGI HTTP-сервер для запуска Python-приложения NetBox.

1.  **Скопировать файл конфигурации Gunicorn:**
    NetBox поставляется с примером конфигурационного файла. Скопируйте его из директории `contrib` в корневую директорию `/opt/netbox/`.
    ```bash
    sudo cp /opt/netbox/contrib/gunicorn_config.py /opt/netbox/
    ```

### 2. Настройка systemd

Чтобы NetBox и его фоновые процессы запускались автоматически при старте системы, необходимо настроить службы `systemd`.

1.  **Скопировать файлы служб:**
    Примеры файлов `*.service` также находятся в директории `contrib`.
    ```bash
    sudo cp /opt/netbox/contrib/netbox.service /etc/systemd/system/
    sudo cp /opt/netbox/contrib/netbox-rq.service /etc/systemd/system/
    ```

2.  **Перезагрузить конфигурацию systemd:**
    Чтобы `systemd` обнаружил новые файлы служб.
    ```bash
    sudo systemctl daemon-reload
    ```

3.  **Запустить и включить автозапуск служб NetBox:**
    ```bash
    sudo systemctl start netbox netbox-rq
    sudo systemctl enable netbox netbox-rq
    ```

4.  **Проверить статус служб:**
    Убедитесь, что обе службы активны (`active (running)`).
    ```bash
    sudo systemctl status netbox netbox-rq
    ```

### 3. Установка и настройка Nginx

Nginx будет выступать в роли реверс-прокси, принимая HTTP/HTTPS запросы от клиентов и перенаправляя их на Gunicorn.

1.  **Установить Nginx:**
    ```bash
    sudo apt install -y nginx
    ```

2.  **Создать самоподписанный SSL-сертификат (опционально):**
    Для использования HTTPS необходим SSL-сертификат. В производственной среде рекомендуется использовать сертификаты, выданные доверенным центром (CA), например, через Let's Encrypt. Для внутреннего использования или тестирования можно создать самоподписанный сертификат.

    ```bash
    sudo openssl req -newkey rsa:2048 -nodes \
      -keyout /etc/ssl/private/netbox.key \
      -x509 -days 365 \
      -out /etc/ssl/certs/netbox.crt
    ```
    В процессе генерации потребуется ввести информацию для сертификата (страна, город и т.д.).

3.  **Настроить сайт NetBox в Nginx:**
    Скопируйте пример конфигурации Nginx, поставляемый с NetBox.
    ```bash
    sudo cp /opt/netbox/contrib/nginx.conf /etc/nginx/sites-available/netbox
    ```

4.  **Отредактировать конфигурацию Nginx:**
    Откройте файл и измените директиву `server_name`.
    ```bash
    sudo vim /etc/nginx/sites-available/netbox
    ```
    Найдите строку `server netbox.example.com;` и замените `netbox.example.com` на IP-адрес вашего сервера или ваше доменное имя.

    Если вы создали SSL-сертификат, убедитесь, что пути в директивах `ssl_certificate` и `ssl_certificate_key` соответствуют созданным файлам. В примере конфигурации они уже должны быть правильными.

5.  **Активировать конфигурацию и перезапустить Nginx:**
    Создайте символическую ссылку на файл конфигурации в директории `sites-enabled` и удалите конфигурацию по умолчанию.
    ```bash
    sudo ln -s /etc/nginx/sites-available/netbox /etc/nginx/sites-enabled/netbox
    sudo rm /etc/nginx/sites-enabled/default
    ```

    Проверьте синтаксис конфигурации Nginx:
    ```bash
    sudo nginx -t
    ```
    Если проверка прошла успешно (`syntax is ok`), перезапустите Nginx.
    ```bash
    sudo systemctl restart nginx
    ```

### 4. Доступ к NetBox

Теперь NetBox должен быть доступен в браузере по адресу вашего сервера (`https://<IP-адрес_сервера>`). Поскольку используется самоподписанный сертификат, браузер выдаст предупреждение о безопасности, которое необходимо принять.
