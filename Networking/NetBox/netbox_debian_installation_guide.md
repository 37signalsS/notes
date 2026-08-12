# NetBox: Установка и настройка в Debian 12

Руководство по развертыванию NetBox в операционной системе Debian 12 (Bookworm). Подробное описание концепций, архитектуры и новых функций NetBox 4.x приведено в файле **[NetBox: Обзор и базовые концепции](./overview.md)**.

### Системные требования (NetBox 4.4.8 — январь 2026)

| Компонент | Рекомендуемая версия | Версия в Debian 12 |
| :--- | :--- | :--- |
| **Python** | 3.10, 3.11, 3.12 | 3.11 |
| **PostgreSQL** | 14+ | 15 |
| **Redis** | 4.0+ | 7.0 |
| **HTTP-сервер** | Nginx или Apache | Nginx 1.22 |
| **Firewall** | UFW или nftables | nftables |
| **OpenSSL** | 1.1.1+ | 3.0.8 |

## Практические сценарии

### 1. Подготовка операционной системы

Обновите пакеты и установите необходимые системные зависимости для сборки Python-пакетов и работы с БД. Включает базовые утилиты и сетевой экран.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv python3-dev \
build-essential libxml2-dev libxslt1-dev libffi-dev libpq-dev \
libssl-dev zlib1g-dev git redis-server postgresql wget curl tar nginx ufw openssl

# Настройка базового сетевого экрана
sudo ufw allow 443
sudo ufw allow 80
sudo ufw allow 8000/tcp # Только для этапа тестирования
sudo ufw enable
```

### 2. Настройка базы данных PostgreSQL

NetBox требует базу данных с кодировкой `UTF8`.

1. **Запуск и проверка сервиса:**
    ```bash
    sudo systemctl enable --now postgresql
    ```

2. **Создание пользователя и базы данных:**
    Войдите в консоль PostgreSQL под системным пользователем `postgres`.

    ```bash
    sudo -u postgres psql
    ```

    Выполните следующие команды (обязательно измените пароль):

    ```sql
    CREATE DATABASE netbox;
    CREATE USER netbox WITH PASSWORD 'Strong_Password_Here';
    GRANT ALL PRIVILEGES ON DATABASE netbox TO netbox;
    -- Для NetBox 4.0+ рекомендуется также:
    ALTER DATABASE netbox OWNER TO netbox;
    \q
    ```

### 3. Настройка Redis

Redis используется для кэширования и очередей задач. В современных версиях NetBox обязательна настройка аутентификации.

1.  **Редактирование `/etc/redis/redis.conf`:**
    ```bash
    sudo vi /etc/redis/redis.conf
    ```
    Установите следующие параметры:
    ```conf
    requirepass Ваш_Очень_Сложный_Пароль
    supervised systemd
    ```

2.  **Запуск и проверка:**
    ```bash
    sudo systemctl enable --now redis-server
    sudo systemctl restart redis
    
    # Проверка аутентификации
    redis-cli
    > AUTH Ваш_Очень_Сложный_Пароль
    > PING
    # → PONG
    ```

### 4. Развертывание приложения NetBox

1. **Создание системного пользователя:**
    ```bash
    sudo adduser --system --group netbox
    ```

2. **Загрузка исходного кода и линковка:**
    Для удобства будущих обновлений рекомендуется использовать символьные ссылки.
    ```bash
    export NETBOX_VER="4.4.8"
    sudo wget https://github.com/netbox-community/netbox/archive/refs/tags/v$NETBOX_VER.tar.gz
    sudo tar -xzf v$NETBOX_VER.tar.gz -C /opt
    sudo ln -s /opt/netbox-$NETBOX_VER/ /opt/netbox
    
    # Установка прав доступа
    sudo chown -R netbox:netbox /opt/netbox-$NETBOX_VER/netbox/media/
    sudo chown -R netbox:netbox /opt/netbox-$NETBOX_VER/netbox/reports/
    sudo chown -R netbox:netbox /opt/netbox-$NETBOX_VER/netbox/scripts/
    ```

### 5. Конфигурация приложения

1. **Создание файла настроек:**
    ```bash
    cd /opt/netbox/netbox/netbox/
    sudo cp configuration_example.py configuration.py
    ```

2. **Генерация SECRET_KEY:**
    Ключ необходим для шифрования сессий и токенов.
    ```bash
    sudo /opt/netbox/netbox/generate_secret_key.py
    # Скопируйте полученную строку
    ```

3. **Редактирование `configuration.py`:**
    ```bash
    sudo vim configuration.py
    ```

    **Основные параметры:**
    ```python
    ALLOWED_HOSTS = ['netbox.example.com', '192.168.1.100']

    DATABASE = {
        'NAME': 'netbox',
        'USER': 'netbox',
        'PASSWORD': 'Strong_Password_Here',
        'HOST': 'localhost',
        'PORT': '',
    }

    # NetBox 4.x+ использует два Redis-инстанса (обычно 0 и 1)
    REDIS = {
        'tasks': {
            'HOST': 'localhost',
            'PORT': 6379,
            'PASSWORD': 'Ваш_Очень_Сложный_Пароль',
            'DATABASE': 0,
        },
        'caching': {
            'HOST': 'localhost',
            'PORT': 6379,
            'PASSWORD': 'Ваш_Очень_Сложный_Пароль',
            'DATABASE': 1,
        }
    }

    SECRET_KEY = 'Вставьте_сгенерированный_ключ_здесь'
    ```

### 6. Установка и миграция (upgrade.sh)

NetBox предоставляет скрипт `upgrade.sh`, который автоматически создает виртуальное окружение (`venv`), устанавливает зависимости, выполняет миграции БД и собирает статические файлы.

```bash
sudo /opt/netbox/upgrade.sh
```

### 7. Инициализация (Первая установка)

После выполнения `upgrade.sh` необходимо инициализировать базу данных и собрать статический контент для корректного отображения веб-интерфейса.

1.  **Активация окружения:**
    ```bash
    source /opt/netbox/venv/bin/activate
    cd /opt/netbox/netbox/
    ```

2.  **Миграция, суперпользователь и статика:**
    ```bash
    # Выполнение миграций БД
    python3 manage.py migrate
    
    # Создание администратора
    python3 manage.py createsuperuser
    
    # Сбор статических файлов (обязательно для первой установки)
    python3 manage.py collectstatic
    ```

3.  **Тестовый запуск (опционально):**
    Проверьте работоспособность без полноценного веб-сервера.
    ```bash
    python3 manage.py runserver 0.0.0.0:8000 --insecure
    ```
    Доступ: `http://ваш_ip:8000`. Остановка: `Ctrl+C`.

### 8. Настройка Gunicorn и Systemd

1. **Конфигурация Gunicorn:**
    ```bash
    sudo cp /opt/netbox/contrib/gunicorn_config.py /opt/netbox/gunicorn_config.py
    ```

2. **Настройка служб systemd:**
    Скопируйте файлы служб из `contrib` в системную директорию.

    ```bash
    sudo cp /opt/netbox/contrib/*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    ```

    Запустите и включите автозапуск:
    ```bash
    sudo systemctl enable --now netbox netbox-rq netbox-housekeeping
    ```

### 9. Настройка веб-сервера Nginx

1. **Установка и SSL:**
    ```bash
    sudo apt install -y nginx
    # Создание сертификата (для production используйте Certbot)
    sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
      -keyout /etc/ssl/private/netbox.key \
      -out /etc/ssl/certs/netbox.crt
    ```

2. **Конфигурация сайта:**
    ```bash
    sudo cp /opt/netbox/contrib/nginx.conf /etc/nginx/sites-available/netbox
    sudo ln -s /etc/nginx/sites-available/netbox /etc/nginx/sites-enabled/netbox
    sudo rm /etc/nginx/sites-enabled/default
    ```

    Отредактируйте `/etc/nginx/sites-available/netbox`, заменив `server_name` на ваш домен/IP.

    ```bash
    sudo nginx -t && sudo systemctl restart nginx
    ```

## Обслуживание и эксплуатация

### Обновление NetBox

Процесс обновления NetBox сводится к загрузке новой версии и повторному запуску `upgrade.sh`.

```bash
cd /opt/netbox
sudo git fetch origin
sudo git checkout v4.0.x # Замените на новую версию
sudo /opt/netbox/upgrade.sh
sudo systemctl restart netbox netbox-rq
```

### Резервное копирование

Крайне важно регулярно создавать бэкапы БД и медиа-файлов.

```bash
# Бэкап базы данных
sudo -u postgres pg_dump netbox > netbox_db_backup.sql

# Бэкап медиа-файлов (изображения, вложения)
tar -czvf netbox_media_backup.tar.gz /opt/netbox/netbox/media/
```

### Типовые проблемы

- **502 Bad Gateway**: Проверьте статус службы `netbox` (`systemctl status netbox`) и логи Gunicorn.
- **Ошибки статики (битые CSS/JS)**: Убедитесь, что пользователь `nginx` (обычно `www-data`) имеет права на чтение директории `/opt/netbox/netbox/static/`.
- **Redis Connection Error**: Убедитесь, что `redis-server` запущен и параметры в `configuration.py` верны.

## Дополнительная информация

### Полезные ресурсы и скрипты

- **[Скрипты автоматической установки (Debian)](https://github.com/VladimirKalinushkin/Install_Netbox_on_Debian)** — примеры скриптов для быстрой настройки пакетов и systemd.
- **[Официальная документация NetBox](https://netboxlabs.com/docs/netbox/installation/)** — первоисточник.
- **[Документация по плагинам](https://docs.netbox.dev/en/stable/plugins/)**
- **[LDAP Аутентификация](https://docs.netbox.dev/en/stable/administration/authentication/ldap/)**
- **[NetBox API и Python-клиент (pynetbox)](https://pynetbox.readthedocs.io/)**

### См. также

- [NetBox: Обзор и базовые концепции](./overview.md)
- [Автоматизация NetBox с использованием Python](./netbox-automation-python.md)
- [Работа с PostgreSQL из консоли (psql)](../../Databases/PostgreSQL/Operations/console_basics.md)
- [Оптимизация Nginx](../../WebServers/Nginx/Performance/nginx_performance_tuning.md)
- [Использование Redis как кэш](../../Databases/Concepts/Caching/redis_caching.md)
- [Динамический инвентарь Ansible (NetBox)](../../Ansible/dynamic_inventory.md)
- [Интеграция IPAM в Kubernetes](../../Kubernetes/Networking/Network/CNI/ipam.md)
- [Мониторинг NetBox через Prometheus](../../OpenTelemetry/Scenarios/netbox_monitoring.md)

