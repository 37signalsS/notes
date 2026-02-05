# NetBox: Установка в Debian

## Определения

**NetBox** — это инструмент для управления IP-адресами (IPAM) и инфраструктурой центров обработки данных (DCIM), предназначенный для документирования и автоматизации сетевой инфраструктуры.

## Базовые концепции

Установка NetBox в Debian включает развертывание нескольких ключевых компонентов:
-   **PostgreSQL**: Реляционная база данных для хранения основной информации NetBox.
-   **Redis**: Хранилище данных типа "ключ-значение", используемое для кэширования и организации очередей задач.
-   **Python**: Среда выполнения для приложения NetBox, включая его зависимости.
-   **Gunicorn**: WSGI HTTP-сервер, запускающий Python-приложение NetBox.
-   **Nginx**: Высокопроизводительный веб-сервер, выступающий в роли реверс-прокси для Gunicorn и обслуживающий статические файлы.
-   **`systemd`**: Система инициализации Linux для управления службами NetBox и обеспечения их автозапуска.

## Практические сценарии

Ниже приведена пошаговая инструкция по установке и базовой настройке NetBox в Debian.

### 1. Подготовка системы

Обновите системные пакеты и установите необходимые утилиты:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git sudo vim curl python3-pip
```

### 2. Настройка базы данных PostgreSQL

Установите и настройте PostgreSQL для NetBox.

1.  **Установка PostgreSQL:**
    ```bash
    sudo apt install -y postgresql
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
    ```
2.  **Создание базы данных и пользователя:** Войдите в консоль `psql` от имени `postgres`. Подробнее: [Работа с PostgreSQL из консоли (psql)](../../Databases/PostgreSQL/Operations/console_basics.md).
    ```bash
    sudo -u postgres psql
    ```
    Затем введите:
    ```sql
    CREATE DATABASE netbox;

    -- Создаем пользователя netbox с паролем (замените 'YourSecurePassword' на сложный пароль)
    CREATE USER netbox WITH PASSWORD 'YourSecurePassword';

    -- Предоставляем все права на базу данных netbox пользователю netbox
    GRANT ALL PRIVILEGES ON DATABASE netbox TO netbox;
    \q
    ```
3.  **Проверка соединения (опционально):**
    ```bash
    psql --username netbox --password --host localhost netbox
    ```

### 3. Установка Redis

Установите Redis для кэширования и очередей задач.

```bash
sudo apt install -y redis-server
redis-cli ping # Ожидаемый ответ: PONG
```

### 4. Установка зависимостей Python

Установите системные зависимости Python:

```bash
sudo apt install -y python3-venv libxml2-dev libxslt1-dev libffi-dev libpq-dev libssl-dev zlib1g-dev
```

### 5. Развертывание NetBox

Клонируйте репозиторий NetBox и настройте его.

1.  **Клонирование репозитория:** Установите NetBox в `/opt`.
    ```bash
    sudo git clone -b master https://github.com/netbox-community/netbox.git /opt/netbox
    ```
2.  **Создание системного пользователя:**
    ```bash
    sudo adduser --system --group netbox
    sudo chown --recursive netbox /opt/netbox/netbox/media
    ```
3.  **Конфигурация NetBox:** Скопируйте пример конфигурации и сгенерируйте секретный ключ.
    ```bash
    cd /opt/netbox/netbox/netbox/
    sudo cp configuration_example.py configuration.py
    /opt/netbox/netbox/generate_secret_key.py # Скопируйте ключ
    ```
    Отредактируйте `configuration.py`:
    ```bash
    sudo vim /opt/netbox/netbox/netbox/configuration.py
    ```
    Укажите `ALLOWED_HOSTS` (IP или домен сервера), `DATABASE` (данные PostgreSQL) и вставьте `SECRET_KEY`.

### 6. Установка зависимостей и миграция базы данных

Используйте скрипт `upgrade.sh` для установки зависимостей, миграции БД и сбора статики.

```bash
sudo /opt/netbox/upgrade.sh
```
Скрипт создаст виртуальное окружение Python в `/opt/netbox/venv/`.

### 7. Создание суперпользователя

Создайте административную учетную запись для доступа к NetBox.

1.  **Активация виртуального окружения и переход в директорию:**
    ```bash
    source /opt/netbox/venv/bin/activate
    cd /opt/netbox/netbox/
    ```
2.  **Создание суперпользователя:**
    ```bash
    python3 manage.py createsuperuser
    ```
    Следуйте подсказкам для ввода данных.

### 8. Настройка производственной среды (Gunicorn + Nginx)

Настройте Gunicorn и Nginx для полноценной работы NetBox в производственной среде.

1.  **Настройка Gunicorn:** Скопируйте пример конфигурации.
    ```bash
    sudo cp /opt/netbox/contrib/gunicorn_config.py /opt/netbox/
    ```
2.  **Настройка `systemd`:** Скопируйте файлы служб, перезагрузите конфигурацию, запустите и включите автозапуск служб NetBox.
    ```bash
    sudo cp /opt/netbox/contrib/netbox.service /etc/systemd/system/
    sudo cp /opt/netbox/contrib/netbox-rq.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl start netbox netbox-rq
    sudo systemctl enable netbox netbox-rq
    sudo systemctl status netbox netbox-rq # Проверьте статус
    ```
3.  **Настройка Nginx:**
    Установите Nginx: `sudo apt install -y nginx`.
    Создайте самоподписанный SSL-сертификат (опционально, для теста):
    ```bash
    sudo openssl req -newkey rsa:2048 -nodes \
      -keyout /etc/ssl/private/netbox.key \
      -x509 -days 365 \
      -out /etc/ssl/certs/netbox.crt
    ```
    Скопируйте и отредактируйте конфигурацию Nginx (`nginx.conf`), указав `server_name` и проверив пути к SSL-сертификатам.
    ```bash
    sudo cp /opt/netbox/contrib/nginx.conf /etc/nginx/sites-available/netbox
    sudo vim /etc/nginx/sites-available/netbox
    ```
    Активируйте конфигурацию:
    ```bash
    sudo ln -s /etc/nginx/sites-available/netbox /etc/nginx/sites-enabled/netbox
    sudo rm /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl restart nginx
    ```

## Дополнительная информация

### Доступ к NetBox

После выполнения всех шагов NetBox будет доступен по адресу вашего сервера (например, `https://<IP-адрес_сервера>`). При использовании самоподписанного SSL-сертификата браузер может выдать предупреждение о безопасности.

### Тестовый запуск (не для production)

Для быстрой проверки можно запустить NetBox в режиме разработки (не используйте его для производственной среды):

```bash
source /opt/netbox/venv/bin/activate
cd /opt/netbox/netbox/
python3 manage.py runserver 0.0.0.0:8000 --insecure
```
Затем откройте `http://<IP-адрес_сервера>:8000` в браузере.