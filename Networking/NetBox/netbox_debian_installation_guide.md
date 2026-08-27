# NetBox: Установка и настройка в Debian 12

Руководство по развертыванию NetBox в операционной системе Debian 12 (Bookworm). Подробное описание концепций, архитектуры и новых функций NetBox 4.x приведено в файле **[NetBox: Обзор и базовые концепции](./overview.md)**.

## Определения

**NetBox** — открытая IPAM-система (IP Address Management) и CMDB (Configuration Management Database), предназначенная для управления сетевой инфраструктурой. Обеспечивает централизованное хранение данных о физической и логической топологии сети, устройствах, адресном пространстве и сервисах.

**Debian 12 (Bookworm)** — стабильный релиз операционной системы Debian, выпущенный в июне 2023. Используется как базовая ОС для установки NetBox в enterprise-средах благодаря предсказуемому циклу обновлений и длительной поддержке.

**Gunicorn** — WSGI-сервер для Python-приложений. Используется NetBox как промежуточный слой между веб-сервером (Nginx) и Django-приложением для обработки HTTP-запросов.

**RQ (Redis Queue)** — система очередей задач на базе Redis. NetBox использует RQ для асинхронной обработки фоновых задач: вебхуков, отчетов,.housekeeping и планировщика задач.

**WAL (Write-Ahead Logging)** — механизм PostgreSQL для обеспечения целостности данных. При включении ускоряет транзакции за счёт последовательной записи изменений перед физической модификацией данных.

**SSO (Single Sign-On)** — механизм единого входа, позволяющий аутентифицировать пользователей через внешние провайдеры (LDAP, SAML, OAuth2) вместо локальной базы данных.

**Housekeeping** — фоновая служба NetBox, выполняющая автоматическую очистку: удаление старых записей журнала, архивирование изменений, обновление кэша.

**Object Change Log** — журнал изменений объектов в NetBox, фиксирующий все операции создания, модификации и удаления записей с указанием пользователя и времени.

## Системные требования (NetBox 4.4.8 — январь 2026)

| Компонент | Рекомендуемая версия | Версия в Debian 12 |
| :--- | :--- | :--- |
| **Python** | 3.10, 3.11, 3.12 | 3.11 |
| **PostgreSQL** | 14+ | 15 |
| **Redis** | 4.0+ | 7.0 |
| **HTTP-сервер** | Nginx или Apache | Nginx 1.22 |
| **Firewall** | UFW или nftables | nftables |
| **OpenSSL** | 1.1.1+ | 3.0.8 |

**Аппаратные рекомендации:**

| Окружение | CPU | RAM | Диск (SSD) |
| :--- | :--- | :--- | :--- |
| **Тестирование / Dev** | 2 ядра | 4 GB | 20 GB |
| **Продакшн (до 1K устройств)** | 4 ядра | 8 GB | 50 GB |
| **Продакшн (1K-10K устройств)** | 8 ядер | 16 GB | 100 GB |
| **Продакшн (10K+ устройств)** | 16+ ядер | 32+ GB | 200+ GB |

**Порты, которые необходимо открыть:**

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| 22 | TCP | SSH (удалённое управление) |
| 80 | TCP | HTTP (редирект на HTTPS) |
| 443 | TCP | HTTPS (основной доступ) |
| 8000 | TCP | Тестовый сервер Django (только для отладки) |
| 5432 | TCP | PostgreSQL (только если БД на отдельном сервере) |
| 6379 | TCP | Redis (только если Redis на отдельном сервере) |

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

**Валидация:** После выполнения команды проверьте, что все пакеты установлены:

```bash
python3 --version    # → Python 3.11.x
psql --version       # → psql (PostgreSQL) 15.x
redis-server --version # → Redis server v=7.0.x
nginx -v             # → nginx version: nginx/1.22.x
```

**Возможные ошибки:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `E: Unable to locate package` | Устаревший кэш пакетов | `sudo apt update` |
| `Could not get lock /var/lib/dpkg/lock` | Другой процесс apt | `sudo rm /var/lib/dpkg/lock-frontend && sudo dpkg --configure -a` |
| `Permission denied` при установке | Отсутствуют права root | Добавьте `sudo` перед командой |

### 2. Настройка базы данных PostgreSQL

NetBox требует базу данных с кодировкой `UTF8`.

1. **Запуск и проверка сервиса:**
    ```bash
    sudo systemctl enable --now postgresql
    sudo systemctl status postgresql # → active (running)
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

3. **Оптимизация PostgreSQL для NetBox:**

    Отредактируйте `/etc/postgresql/15/main/postgresql.conf` для повышения производительности:

    ```conf
    # Рекомендуемые настройки для production
    shared_buffers = 2GB           # 25% от объёма RAM
    effective_cache_size = 6GB     # 75% от объёма RAM
    work_mem = 64MB                # Для сложных запросов сортировки
    maintenance_work_mem = 512MB   # Для VACUUM, CREATE INDEX
    wal_buffers = 64MB
    max_connections = 100          # В зависимости от нагрузки
    ```

    После изменения перезапустите PostgreSQL:

    ```bash
    sudo systemctl restart postgresql
    ```

4. **Настройка автоматических бэкапов (рекомендуется):**

    ```bash
    # Создание скрипта бэкапа
    sudo tee /opt/netbox/scripts/backup_db.sh << 'EOF'
    #!/bin/bash
    BACKUP_DIR="/opt/backups/netbox"
    DATE=$(date +%Y%m%d_%H%M%S)
    RETENTION_DAYS=30

    mkdir -p $BACKUP_DIR
    sudo -u postgres pg_dump netbox | gzip > $BACKUP_DIR/netbox_$DATE.sql.gz
    find $BACKUP_DIR -name "*.gz" -mtime +$RETENTION_DAYS -delete
    echo "$(date): Backup completed: netbox_$DATE.sql.gz" >> /var/log/netbox-backup.log
    EOF

    sudo chmod +x /opt/netbox/scripts/backup_db.sh

    # Добавление в crontab (ежедневно в 3:00)
    (sudo crontab -l 2>/dev/null; echo "0 3 * * * /opt/netbox/scripts/backup_db.sh") | sudo crontab -
    ```

**Валидация:** Проверьте подключение к БД:

```bash
sudo -u postgres psql -c "\l" | grep netbox
# → netbox | netbox | UTF8 | ...

# Проверка подключения от имени пользователя netbox
PGPASSWORD='Strong_Password_Here' psql -h localhost -U netbox -d netbox -c "SELECT 1;"
# → ?column?
# →          1
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
    bind 127.0.0.1 ::1
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
    > CONFIG GET databases
    # → 1) "databases"
    #    2) "16"
    > EXIT
    ```

3.  **Настройка maxmemory (рекомендуется):**

    Добавьте в `/etc/redis/redis.conf`:

    ```conf
    maxmemory 1gb
    maxmemory-policy allkeys-lru
    ```

**Валидация:** Проверьте, что Redis использует пароль и работает корректно:

```bash
redis-cli -a 'Ваш_Очень_Сложный_Пароль' INFO server | grep redis_version
# → redis_version:7.0.x
```

**Возможные ошибки:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `NOAUTH Authentication required` | Не передан пароль | Используйте `-a пароль` или `AUTH` |
| `ERR invalid password` | Неверный пароль | Проверьте пароль в `redis.conf` |
| `Connection refused` | Redis не запущен | `sudo systemctl start redis-server` |

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

3. **Проверка целостности загрузки:**

    ```bash
    ls -la /opt/netbox-$NETBOX_VER/netbox/
    # Должны присутствовать: manage.py, settings.py, wsgi.py

    sudo -u netbox python3 /opt/netbox-$NETBOX_VER/netbox/manage.py --version
    # → 4.4.8
    ```

**Валидация:** Убедитесь, что структура файлов корректна:

```bash
ls -la /opt/netbox/
# → ссылка на /opt/netbox-4.4.8/

ls /opt/netbox/netbox/
# → manage.py  netbox/  requirements.txt  ...
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

    **Дополнительные параметры (рекомендуемые для production):**
    ```python
    # Безопасность
    CSRF_TRUSTED_ORIGINS = ['https://netbox.example.com']
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Логирование
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                'format': '{levelname} {asctime} {module} {message}',
                'style': '{',
            },
        },
        'handlers': {
            'file': {
                'level': 'INFO',
                'class': 'logging.FileHandler',
                'filename': '/var/log/netbox/netbox.log',
                'formatter': 'verbose',
            },
        },
        'loggers': {
            'netbox': {
                'handlers': ['file'],
                'level': 'INFO',
            },
        },
    }

    # Плагины (раскомментируйте и настройте при необходимости)
    # PLUGINS = []
    # PLUGINS_CONFIG = {}
    ```

4. **Создание директории для логов:**

    ```bash
    sudo mkdir -p /var/log/netbox
    sudo chown -R netbox:netbox /var/log/netbox
    ```

### 6. Установка и миграция (upgrade.sh)

NetBox предоставляет скрипт `upgrade.sh`, который автоматически создает виртуальное окружение (`venv`), устанавливает зависимости, выполняет миграции БД и собирает статические файлы.

```bash
sudo /opt/netbox/upgrade.sh
```

**Что выполняет скрипт:**

| Этап | Описание |
| :--- | :--- |
| Создание venv | `/opt/netbox/venv/` — изолированное Python-окружение |
| Установка зависимостей | `pip install -r requirements.txt` |
| Миграции БД | `python manage.py migrate` |
| Сбор статики | `python manage.py collectstatic --no-input` |
| Создание группы плагинов | `python manage.py collectplugins` |

**Валидация:** После выполнения проверьте, что venv создан:

```bash
ls -la /opt/netbox/venv/bin/python
# → -rwxr-xr-x ... /opt/netbox/venv/bin/python

/opt/netbox/venv/bin/python --version
# → Python 3.11.x
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

4.  **Создание токена API (рекомендуется сразу):**

    После первого входа в веб-интерфейс создайте токен для API-доступа:

    ```bash
    # Через Django shell
    source /opt/netbox/venv/bin/activate
    cd /opt/netbox/netbox/
    python manage.py shell -c "
    from users.models import Token
    token = Token.objects.create(
        key='YOUR_CUSTOM_TOKEN_KEY',
        user_id=1,  # ID суперпользователя
        description='API Token for automation',
        write_enabled=True
    )
    print(f'Token created: {token.key}')
    "
    ```

    Или через веб-интерфейс: `Admin > Users > Tokens > Add`.

**Валидация:** Проверьте, что API отвечает:

```bash
curl -s -H "Authorization: Token YOUR_TOKEN_KEY" \
     http://localhost:8000/api/status/
# → {"django-version": "4.2.x", "netbox-version": "4.4.8", "plugins": {}}
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

3. **Проверка статуса всех служб:**

    ```bash
    sudo systemctl status netbox netbox-rq netbox-housekeeping
    ```

    **Ожидаемый вывод:**

    | Служба | Статус | Описание |
    | :--- | :--- | :--- |
    | `netbox` | active (running) | Основной WSGI-сервер (Gunicorn) |
    | `netbox-rq` | active (running) | Обработчик очередей задач (RQ Worker) |
    | `netbox-housekeeping` | active (running) | Фоновые задачи по расписанию |

4. **Настройка логирования служб:**

    Создайте файл `/etc/systemd/system/netbox.service.d/logging.conf`:

    ```ini
    [Service]
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier=netbox
    ```

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl restart netbox
    ```

**Валидация:**

```bash
# Проверка, что Gunicorn слушает порт
sudo ss -tlnp | grep 8000
# → LISTEN ... 127.0.0.1:8000 ...

# Проверка логов
sudo journalctl -u netbox --since "1 hour ago" | tail -20
```

**Возможные ошибки:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `netbox.service: Failed with result 'exit-code'` | Ошибка в `configuration.py` | Проверьте логи: `journalctl -u netbox -n 50` |
| `netbox-rq: Worker not found` | RQ Worker не может подключиться к Redis | Проверьте пароль Redis в `configuration.py` |
| `Permission denied` при запуске | Неверные права на файлы | `sudo chown -R netbox:netbox /opt/netbox` |

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

3. **Настройка Let's Encrypt (рекомендуется для production):**

    ```bash
    # Установка Certbot
    sudo apt install -y certbot python3-certbot-nginx

    # Получение сертификата
    sudo certbot --nginx -d netbox.example.com

    # Автоматическое обновление (проверьте таймер)
    sudo systemctl status certbot.timer
    ```

4. **Оптимизация Nginx для production:**

    Добавьте в `/etc/nginx/sites-available/netbox` в секцию `server`:

    ```nginx
    # Кэширование статических файлов
    location /static/ {
        alias /opt/netbox/netbox/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Кэширование медиафайлов
    location /media/ {
        alias /opt/netbox/netbox/media/;
        expires 7d;
    }

    # Ограничение размера загружаемых файлов
    client_max_body_size 100M;

    # Gzip-сжатие
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
    gzip_min_length 1000;
    ```

**Валидация:**

```bash
# Проверка конфигурации Nginx
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка доступности
curl -sI https://netbox.example.com/
# → HTTP/2 200
# → server: nginx/1.22.x
```

### 10. Настройка LDAP/SSO аутентификации (опционально)

Для интеграции с корпоративной директорией Active Directory или OpenLDAP:

1. **Установка зависимостей:**

    ```bash
    source /opt/netbox/venv/bin/activate
    pip install django-auth-ldap
    ```

2. **Настройка `configuration.py`:**

    ```python
    import ldap
    from django_auth_ldap.config import LDAPSearch, GroupOfNamesType

    # Аутентификация
    AUTHENTICATION_BACKENDS = [
        'django_auth_ldap.backend.LDAPBackend',
        'netbox.authentication.NetBoxObjectPermissionBackend',
    ]

    # LDAP-сервер
    AUTH_LDAP_SERVER_URI = 'ldap://ldap.example.com:389'
    AUTH_LDAP_BIND_DN = 'cn=netbox,ou=services,dc=example,dc=com'
    AUTH_LDAP_BIND_PASSWORD = 'LDAP_BIND_PASSWORD'
    AUTH_LDAP_USER_SEARCH = LDAPSearch(
        'ou=users,dc=example,dc=com',
        ldap.SCOPE_SUBTREE,
        '(uid=%(user)s)'
    )

    # Маппинг групп LDAP -> NetBox
    AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
        'ou=groups,dc=example,dc=com',
        ldap.SCOPE_SUBTREE,
        '(objectClass=groupOfNames)'
    )
    AUTH_LDAP_GROUP_TYPE = GroupOfNamesType()

    # Кэширование LDAP-запросов
    AUTH_LDAP_CACHE_TIMEOUT = 3600
    ```

3. **Перезапуск служб:**

    ```bash
    sudo systemctl restart netbox netbox-rq
    ```

### 11. Настройка High Availability (опционально)

Для enterprise-развертывания с высокой доступностью:

**Кластер PostgreSQL (Patroni):**

```yaml
# /etc/patroni/patroni.yml (пример конфигурации)
scope: netbox-pg
namespace: /db/
name: pg-node1

restapi:
  listen: 0.0.0.0:8008
  connect_address: 10.0.0.1:8008

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    postgresql:
      use_pg_rewind: true
      parameters:
        max_connections: 200
        shared_buffers: 4GB

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.0.0.1:5432
  data_dir: /var/lib/postgresql/15/main
  authentication:
    replication:
      username: replicator
      password: REPLICATION_PASSWORD
    superuser:
      username: postgres
      password: POSTGRES_PASSWORD
```

**Redis Sentinel (для отказоустойчивости):**

```conf
# /etc/redis/sentinel.conf
sentinel monitor netbox-master 127.0.0.1 6379 2
sentinel auth-pass netbox-master Ваш_Очень_Сложный_Пароль
sentinel down-after-milliseconds netbox-master 5000
sentinel failover-timeout netbox-master 60000
```

### 12. Настройка мониторинга

**Минимальный мониторинг с Healthcheck:**

```python
# /opt/netbox/netbox/netbox/health_check.py
import requests
import sys

def check_netbox_health(url, token):
    """Проверка работоспособности NetBox"""
    headers = {'Authorization': f'Token {token}'}
    try:
        response = requests.get(f'{url}/api/status/', headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"NetBox OK: v{data.get('netbox-version', 'unknown')}")
            return True
        else:
            print(f"NetBox ERROR: HTTP {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"NetBox CRITICAL: {e}")
        return False

if __name__ == "__main__":
    if not check_netbox_health('https://netbox.example.com', 'YOUR_TOKEN'):
        sys.exit(1)
```

**Cron-задача для проверки:**

```bash
# Проверка каждые 5 минут
*/5 * * * * /opt/netbox/venv/bin/python /opt/netbox/scripts/health_check.py >> /var/log/netbox-health.log 2>&1
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

**Важные замечания перед обновлением:**

1. **Создайте бэкап** перед обновлением (см. раздел "Резервное копирование").
2. **Проверьте журнал изменений** версий: [NetBox Release Notes](https://docs.netbox.dev/en/stable/release-notes/).
3. **Остановите службы** перед обновлением:
   ```bash
   sudo systemctl stop netbox netbox-rq netbox-housekeeping
   ```
4. **Проверьте совместимость** плагинов с новой версией.

**Процедура отката (если обновление прошло неудачно):**

```bash
# 1. Остановите службы
sudo systemctl stop netbox netbox-rq netbox-housekeeping

# 2. Восстановите предыдущую версию
cd /opt/netbox
sudo rm /opt/netbox
sudo ln -s /opt/netbox-ПРЕДЫДУЩАЯ_ВЕРСИЯ/ /opt/netbox

# 3. Восстановите БД из бэкапа
gunzip -c /opt/backups/netbox/netbox_ДАТА.sql.gz | sudo -u postgres psql netbox

# 4. Запустите службы
sudo systemctl start netbox netbox-rq netbox-housekeeping
```

### Резервное копирование

Крайне важно регулярно создавать бэкапы БД и медиа-файлов.

```bash
# Бэкап базы данных
sudo -u postgres pg_dump netbox > netbox_db_backup.sql

# Бэкап медиа-файлов (изображения, вложения)
tar -czvf netbox_media_backup.tar.gz /opt/netbox/netbox/media/
```

**Автоматизированное резервное копирование (production):**

```bash
#!/bin/bash
# /opt/netbox/scripts/full_backup.sh

BACKUP_DIR="/opt/backups/netbox"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

mkdir -p $BACKUP_DIR

# Бэкап PostgreSQL
sudo -u postgres pg_dump netbox | gzip > $BACKUP_DIR/netbox_db_$DATE.sql.gz

# Бэкап медиафайлов
tar -czf $BACKUP_DIR/netbox_media_$DATE.tar.gz /opt/netbox/netbox/media/

# Бэкап конфигурации
tar -czf $BACKUP_DIR/netbox_config_$DATE.tar.gz \
    /opt/netbox/netbox/netbox/configuration.py \
    /opt/netbox/gunicorn_config.py \
    /etc/nginx/sites-available/netbox

# Удаление старых бэкапов
find $BACKUP_DIR -name "*.gz" -mtime +$RETENTION_DAYS -delete

echo "$(DATE): Backup completed" >> /var/log/netbox-backup.log
```

**Расписание (добавьте в crontab):**

```bash
# Ежедневный полный бэкап в 2:00
0 2 * * * /opt/netbox/scripts/full_backup.sh

# Каждые 6 часов — только БД (для критичных систем)
0 */6 * * * /opt/netbox/scripts/backup_db.sh
```

**Процедура восстановления:**

```bash
# Восстановление PostgreSQL
gunzip -c /opt/backups/netbox/netbox_db_ДАТА.sql.gz | sudo -u postgres psql netbox

# Восстановление медиафайлов
tar -xzf /opt/backups/netbox/netbox_media_ДАТА.tar.gz -C /

# Восстановление конфигурации
tar -xzf /opt/backups/netbox/netbox_config_ДАТА.tar.gz -C /

# Перезапуск служб
sudo systemctl restart netbox netbox-rq
```

### Настройка ротации логов

Создайте файл `/etc/logrotate.d/netbox`:

```conf
/var/log/netbox/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 netbox netbox
    sharedscripts
    postrotate
        systemctl reload netbox > /dev/null 2>&1 || true
    endscript
}
```

### Типовые проблемы и их решение

- **502 Bad Gateway**: Проверьте статус службы `netbox` (`systemctl status netbox`) и логи Gunicorn.

  ```bash
  # Диагностика
  sudo journalctl -u netbox -n 50
  sudo ss -tlnp | grep 8000  # Порт должен быть в LISTEN
  sudo systemctl restart netbox
  ```

- **Ошибки статики (битые CSS/JS)**: Убедитесь, что пользователь `nginx` (обычно `www-data`) имеет права на чтение директории `/opt/netbox/netbox/static/`.

  ```bash
  sudo chown -R www-data:www-data /opt/netbox/netbox/static/
  sudo chmod -R 755 /opt/netbox/netbox/static/
  ```

- **Redis Connection Error**: Убедитесь, что `redis-server` запущен и параметры в `configuration.py` верны.

  ```bash
  sudo systemctl status redis-server
  redis-cli -a 'ПАРОЛЬ' PING  # → PONG
  ```

- **`TemplateSyntaxError` или отсутствует шаблон**: Выполните сборку статики заново.

  ```bash
  source /opt/netbox/venv/bin/activate
  cd /opt/netbox/netbox/
  python manage.py collectstatic --no-input
  sudo systemctl restart netbox
  ```

- **`django.db.utils.OperationalError: FATAL: password authentication failed`**: Неверный пароль PostgreSQL в `configuration.py` или не выполнен `GRANT`.

  ```bash
  sudo -u postgres psql -c "ALTER USER netbox WITH PASSWORD 'НОВЫЙ_ПАРОЛЬ';"
  ```

- **`Error: Another migration is already in progress`**: Блокировка миграций. Сбросьте её:

  ```bash
  source /opt/netbox/venv/bin/activate
  cd /opt/netbox/netbox/
  python manage.py migrate --fake-initial
  ```

- **`redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379. Connection refused`**: Redis не запущен или слушает другой порт.

  ```bash
  sudo systemctl start redis-server
  sudo ss -tlnp | grep 6379  # Должен быть в LISTEN
  ```

- **Медленная работа UI**: Оптимизируйте PostgreSQL и проверьте размер БД.

  ```bash
  # Проверка размера БД
  sudo -u postgres psql -c "SELECT pg_size_pretty(pg_database_size('netbox'));"

  # Оптимизация
  sudo -u postgres psql -d netbox -c "VACUUM ANALYZE;"
  ```

- **`netbox-housekeeping` не выполняет задачи**: Проверьте расписание и логи.

  ```bash
  sudo journalctl -u netbox-housekeeping -n 30
  sudo systemctl restart netbox-housekeeping
  ```

## Обслуживание и эксплуатация — дополнительные разделы

### Масштабирование NetBox

**Вертикальное масштабирование (scale-up):**

| Компонент | Текущее | Рекомендуется | Параметр |
| :--- | :--- | :--- | :--- |
| **PostgreSQL** | 2 CPU / 4GB RAM | 8 CPU / 16GB RAM | `shared_buffers`, `work_mem` |
| **Redis** | 1 CPU / 1GB RAM | 2 CPU / 4GB RAM | `maxmemory` |
| **Gunicorn** | 4 worker | 8-16 worker | `--workers` |
| **Nginx** | 2 worker | 4-8 worker | `worker_processes` |

**Горизонтальное масштабирование (scale-out):**

```bash
# Масштабирование Gunicorn workers
# /opt/netbox/contrib/gunicorn_config.py
workers = 8  # Вместо 4
threads = 4  # Потоки на worker
worker_class = 'gthread'
```

**Мониторинг производительности:**

```bash
# Проверка размера БД
sudo -u postgres psql -d netbox -c "SELECT pg_size_pretty(pg_database_size('netbox'));"

# Проверка индексов
sudo -u postgres psql -d netbox -c "
SELECT schemaname, relname, n_live_tup, n_dead_tup
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC LIMIT 10;"

# Оптимизация
sudo -u postgres psql -d netbox -c "VACUUM ANALYZE;"
```

### Миграция между версиями NetBox

**Процедура миграции с 3.x на 4.x:**

1. **Подготовка:**
    ```bash
    # Создание бэкапа
    sudo -u postgres pg_dump netbox > netbox_pre_migration.sql
    tar -czf netbox_media_backup.tar.gz /opt/netbox/netbox/media/

    # Проверка версии PostgreSQL (минимум 14 для NetBox 4.x)
    psql --version
    ```

2. **Миграция PostgreSQL (если требуется):**
    ```bash
    # Обновление PostgreSQL с 13/14 до 15
    sudo apt install -y postgresql-15
    sudo systemctl stop postgresql
    sudo -u postgres pg_upgradecluster 14 main /var/lib/postgresql/15/main
    sudo systemctl start postgresql
    ```

3. **Обновление NetBox:**
    ```bash
    # Остановка служб
    sudo systemctl stop netbox netbox-rq netbox-housekeeping

    # Загрузка новой версии
    export NEW_VER="4.4.8"
    sudo wget https://github.com/netbox-community/netbox/archive/refs/tags/v$NEW_VER.tar.gz
    sudo tar -xzf v$NEW_VER.tar.gz -C /opt
    sudo rm /opt/netbox
    sudo ln -s /opt/netbox-$NEW_VER/ /opt/netbox

    # Копирование конфигурации
    sudo cp /opt/netbox/netbox/netbox/configuration_example.py /opt/netbox/netbox/netbox/configuration.py
    # Отредактируйте configuration.py (перенесите настройки из старой версии)

    # Обновление зависимостей
    sudo /opt/netbox/upgrade.sh

    # Запуск
    sudo systemctl start netbox netbox-rq netbox-housekeeping
    ```

4. **Проверка совместимости плагинов:**
    ```bash
    source /opt/netbox/venv/bin/activate
    pip list | grep netbox
    # Проверьте, что все плагины совместимы с NetBox 4.x
    ```

**Типовые ошибки при миграции:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `django.db.utils.OperationalError: column not found` | Невыполненные миграции | `python manage.py migrate` |
| `Plugin X is not compatible` | Плагин не обновлен | Обновите плагин или удалите |
| `SECRET_KEY changed` | Новый ключ | Используйте старый SECRET_KEY |
| `TemplateSyntaxError` | Устаревшие шаблоны | Очистите кэш шаблонов |

### Performance Tuning для production

#### PostgreSQL — оптимизация запросов

```bash
# Включение логирования медленных запросов
sudo -u postgres psql -c "ALTER SYSTEM SET log_min_duration_statement = 1000;"
sudo systemctl restart postgresql

# Анализ планов запросов
sudo -u postgres psql -d netbox -c "EXPLAIN ANALYZE SELECT * FROM dcim_device WHERE site_id = 1;"

# Индексы для часто запрашиваемых полей
sudo -u postgres psql -d netbox -c "
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_device_site ON dcim_device(site_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_device_role ON dcim_device(role_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ipaddress_interface ON ipam_ipaddress(assigned_object_id);
"
```

#### Redis — оптимизация кэширования

```conf
# /etc/redis/redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
```

#### Nginx — оптимизация производительности

```nginx
# /etc/nginx/nginx.conf
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 4096;
    multi_accept on;
    use epoll;
}

http {
    # Буферы
    client_body_buffer_size 10K;
    client_header_buffer_size 1k;
    client_max_body_size 100m;
    large_client_header_buffers 4 8k;

    # Timeouts
    client_body_timeout 12;
    client_header_timeout 12;
    keepalive_timeout 15;
    send_timeout 10;

    # Gzip
    gzip on;
    gzip_comp_level 5;
    gzip_min_length 256;
    gzip_proxied any;
    gzip_vary on;
    gzip_types application/atom+xml application/javascript application/json application/ld+json application/manifest+json application/rss+xml application/vnd.geo+json application/vnd.ms-fontobject application/x-font-ttf application/x-web-app-manifest+json application/xhtml+xml application/xml font/opentype image/bmp image/svg+xml image/x-icon text/cache-manifest text/css text/plain text/vcard text/vnd.rim.location.xloc text/vtt text/x-component text/x-cross-domain-policy;
}
```

#### Gunicorn — оптимизация workers

```python
# /opt/netbox/gunicorn_config.py
import multiprocessing

# Количество workers = (2 * CPU) + 1
workers = multiprocessing.cpu_count() * 2 + 1

# Worker class
worker_class = 'gthread'
threads = 4

# Таймауты
timeout = 300
graceful_timeout = 30
keepalive = 5

# Логирование
accesslog = '/var/log/netbox/gunicorn-access.log'
errorlog = '/var/log/netbox/gunicorn-error.log'
loglevel = 'info'
```

#### Мониторинг производительности

```bash
# Проверка времени отклика API
time curl -s -H "Authorization: Token YOUR_TOKEN" \
  https://netbox.example.com/api/dcim/devices/?limit=100 > /dev/null
# → real    0m0.150s (норма < 1 секунды)

# Проверка размера таблиц
sudo -u postgres psql -d netbox -c "
SELECT
    relname AS table_name,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 10;"
```

## Дополнительная информация

### Рекомендации по безопасности для production

1. **HTTPS обязателен**: Используйте Let's Encrypt или коммерческие сертификаты.
2. **Ограничьте доступ к БД и Redis**: Только localhost или выделенная сеть.
3. **Регулярно обновляйте систему**: `sudo apt update && sudo apt upgrade`.
4. **Настройте Fail2Ban**: Защита от暴力破解.
   ```bash
   sudo apt install -y fail2ban
   sudo systemctl enable --now fail2ban
   ```
5. **Используйте SSH-ключи**: Отключите парольную аутентификацию по SSH.
6. **Настройте Auditd**: Аудит системных вызовов.
7. **Регулярно ротируйте пароли**: PostgreSQL, Redis, API-токены.

### Полезные ресурсы и скрипты

- **[Скрипты автоматической установки (Debian)](https://github.com/VladimirKalinushkin/Install_Netbox_on_Debian)** — примеры скриптов для быстрой настройки пакетов и systemd.
- **[Официальная документация NetBox](https://netboxlabs.com/docs/netbox/installation/)** — первоисточник.
- **[Документация по плагинам](https://docs.netbox.dev/en/stable/plugins/)**
- **[LDAP Аутентификация](https://docs.netbox.dev/en/stable/administration/authentication/ldap/)**
- **[NetBox API и Python-клиент (pynetbox)](https://pynetbox.readthedocs.io/)**

### См. также

- [NetBox: Обзор и базовые концепции](./overview.md)
- [Автоматизация NetBox с использованием Python](./netbox-automation-python.md)
- [Архитектура NetBox в Enterprise-среде](./netbox-enterprise-automation.md)
- [Работа с PostgreSQL из консоли (psql)](../../Databases/PostgreSQL/Operations/console_basics.md)
- [Оптимизация Nginx](../../WebServers/Nginx/Performance/nginx_performance_tuning.md)
- [Обзор Redis](../../Databases/redis_overview.md)
- [Динамический инвентарь Ansible (NetBox)](../../Ansible/dynamic_inventory.md)
- [Интеграция IPAM в Kubernetes](../../Kubernetes/Networking/Network/CNI/ipam.md)
