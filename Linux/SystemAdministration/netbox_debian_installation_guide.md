# NetBox: Установка и настройка в Debian 12

## Определения

**NetBox** — специализированный инструмент класса **IPAM (IP Address Management)** и **DCIM (Data Center Infrastructure Management)** с открытым исходным кодом. Он выступает в роли «единого источника правды» (**SSoT — Single Source of Truth**) для сетевой инфраструктуры, позволяя документировать IP-адреса, стойки, устройства, кабели, виртуализацию и логические связи.

## Базовые концепции

NetBox представляет собой веб-приложение на базе фреймворка **Django (Python)**. Для его полноценной работы требуется связка из нескольких системных компонентов:

- **PostgreSQL (12+)**: Объектно-реляционная база данных для хранения основной структурированной информации.
- **Redis (6.0+)**: Высокопроизводительное хранилище «ключ-значение», используемое для кэширования данных и управления очередями задач.
- **Gunicorn (WSGI)**: Сервер интерфейса шлюза веб-сервера для запуска Python-кода NetBox.
- **Nginx**: Веб-сервер, работающий в режиме реверс-прокси, обеспечивающий SSL/TLS терминацию и обслуживание статических файлов (CSS, JS, изображения).
- **RQ (Redis Queue)**: Система обработки фоновых задач (отправка Webhooks, генерация отчетов, выполнение скриптов).
- **Housekeeping**: Регламентная служба NetBox для очистки устаревших сессий и логов изменений.

### Системные требования (NetBox 4.0)

| Компонент | Минимальная версия | Версия в Debian 12 |
| :--- | :--- | :--- |
| **Python** | 3.10 | 3.11 |
| **PostgreSQL** | 12 | 15 |
| **Redis** | 6.0 | 7.0 |

## Практические сценарии

### 1. Подготовка операционной системы

Обновите пакеты и установите необходимые системные зависимости для сборки Python-пакетов и работы с БД.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv python3-dev \
build-essential libxml2-dev libxslt1-dev libffi-dev libpq-dev \
libssl-dev zlib1g-dev git redis-server postgresql
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

Redis используется для кэширования и очередей задач. По умолчанию он слушает на `localhost:6379`, что достаточно для локальной установки.

```bash
sudo systemctl enable --now redis-server
# Проверка связи
redis-cli ping # → PONG
```

### 4. Развертывание приложения NetBox

1. **Создание системного пользователя:**
    NetBox должен работать от имени непривилегированного пользователя.

    ```bash
    sudo adduser --system --group netbox
    ```

2. **Загрузка исходного кода:**
    Клонируйте стабильную ветку в директорию `/opt/netbox`.

    ```bash
    # Проверьте актуальную версию на GitHub (например, v4.0.5)
    export NETBOX_VER="v4.0.5"
    sudo git clone -b $NETBOX_VER https://github.com/netbox-community/netbox.git /opt/netbox
    sudo chown -R netbox:netbox /opt/netbox
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

    # NetBox 4.0 использует два Redis-инстанса (обычно 0 и 1)
    REDIS = {
        'tasks': {
            'HOST': 'localhost',
            'PORT': 6379,
            'DATABASE': 0,
        },
        'caching': {
            'HOST': 'localhost',
            'PORT': 6379,
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

### 7. Создание администратора

```bash
source /opt/netbox/venv/bin/activate
cd /opt/netbox/netbox/
python3 manage.py createsuperuser
```

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

### Интеграции и плагины

NetBox поддерживает расширение функционала через плагины (например, для топологий или интеграции с BGP). Плагины устанавливаются в `venv` и регистрируются в `PLUGINS` внутри `configuration.py`.

- **[Документация по плагинам](https://docs.netbox.dev/en/stable/plugins/)**
- **[LDAP Аутентификация](https://docs.netbox.dev/en/stable/administration/authentication/ldap/)**
- **[NetBox API и Python-клиент (pynetbox)](https://pynetbox.readthedocs.io/)**

### См. также

- [Работа с PostgreSQL из консоли (psql)](../../Databases/PostgreSQL/Operations/console_basics.md)
- [Оптимизация Nginx](../../WebServers/Nginx/Performance/nginx_performance_tuning.md)
- [Использование Redis как кэш](../../Databases/Concepts/Caching/redis_caching.md)
- [Динамический инвентарь Ansible (NetBox)](../../Ansible/dynamic_inventory.md)
- [Интеграция IPAM в Kubernetes](../../Kubernetes/Networking/Network/CNI/ipam.md)
- [Мониторинг NetBox через Prometheus](../../OpenTelemetry/Scenarios/netbox_monitoring.md)

