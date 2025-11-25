# Grafana Высокая доступность (High Availability)

Один экземпляр Grafana представляет собой единую точку отказа. Если он выйдет из строя, вы потеряете доступ к визуализациям и, возможно, к системе оповещений. Для обеспечения отказоустойчивости Grafana можно развернуть в виде кластера из нескольких экземпляров, работающих за балансировщиком нагрузки и использующих общую базу данных для хранения состояния.

## Архитектура отказоустойчивого кластера

Grafana не имеет встроенной кластеризации. Однако её можно заставить работать в режиме высокой доступности, используя внешние компоненты. Ключевая идея заключается в том, что состояние Grafana (дашборды, пользователи, источники данных, роли и т.д.) хранится не в локальной SQLite базе данных, а во внешней, общей для всех экземпляров базе данных, такой как PostgreSQL или MySQL.

Архитектура такого решения включает три основных компонента:

1.  **Общая база данных (Shared Database):** Один экземпляр PostgreSQL (в идеале — отказоустойчивый кластер PostgreSQL), который служит единым источником истины для всех экземпляров Grafana.
2.  **Экземпляры Grafana (Grafana Instances):** Два или более идентичных экземпляра Grafana, настроенных на работу с общей базой данных. Они являются stateless-компонентами.
3.  **Балансировщик нагрузки (Load Balancer):** Компонент (например, Nginx), который распределяет пользовательский трафик между доступными экземплярами Grafana.

Поток работы выглядит следующим образом:

*   Пользователь обращается к Grafana через адрес балансировщика.
*   Балансировщик перенаправляет запрос на один из экземпляров Grafana.
*   Экземпляр Grafana выполняет операцию (чтение или запись), обращаясь к общей базе данных.
*   Таким образом, любое изменение, сделанное через один экземпляр (например, создание нового дашборда), мгновенно становится доступным на всех остальных.

## Шаг 1: Настройка внешней базы данных (PostgreSQL)

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:latest
    container_name: grafana-postgres
    restart: unless-stopped
    ports:
      - "5432:5432"
    volumes:
      # Прокидываем скрипт инициализации
      - ./init-user-db.sh:/docker-entrypoint-initdb.d/init-user-db.sh
      # Используем volume для персистентности данных
      - postgres_data:/var/lib/postgresql/data
    environment:
      # Пароль для суперпользователя postgres, который будет использован для выполнения скрипта
      - POSTGRES_PASSWORD=your_super_secret_password

volumes:
  postgres_data:

```

Нам также нужен скрипт для инициализации базы данных и пользователя для Grafana. Этот скрипт будет выполнен автоматически при первом запуске контейнера PostgreSQL.

Создайте файл `init-user-db.sh`:

```bash
#!/bin/bash
set -e

# Выполняем SQL-команды от имени суперпользователя 'postgres'
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Создаем пользователя для Grafana
    CREATE USER grafana_user WITH PASSWORD 'grafana_password';

    -- Создаем базу данных для Grafana
    CREATE DATABASE grafana
        WITH
        OWNER = grafana_user
        ENCODING = 'UTF8'
        LC_COLLATE = 'en_US.utf8'
        LC_CTYPE = 'en_US.utf8'
        TABLESPACE = pg_default
        CONNECTION LIMIT = -1;

    -- Выдаем все права на базу данных пользователю grafana_user
    GRANT ALL PRIVILEGES ON DATABASE grafana TO grafana_user;
EOSQL
```
Сделайте скрипт исполняемым: `chmod +x init-user-db.sh`.

Запустите контейнер: `docker-compose up -d`.

## Шаг 2: Настройка экземпляров Grafana

```yaml
version: '3.8'

services:
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      # Прокидываем кастомный конфигурационный файл
      - ./grafana.ini:/etc/grafana/grafana.ini
```

Основная настройка выполняется через файл `grafana.ini`. Чтобы получить его, можно сначала запустить контейнер без кастомной конфигурации, скопировать файл из контейнера (`docker cp grafana:/etc/grafana/grafana.ini .`), изменить его и перезапустить контейнер уже с проброшенным файлом.

Ключевая секция, которую нужно изменить в `grafana.ini`, — это `[database]`.

```ini
[database]
# Type of database. Either "mysql", "postgres" or "sqlite3".
type = postgres

# Host and port for the database.
host = <IP-адрес_сервера_PostgreSQL>:5432

# Database name.
name = grafana

# Database user.
user = grafana_user

# Database password.
password = grafana_password

# For Postgres, use either "disable", "require", or "verify-full".
ssl_mode = disable
```

После подготовки `docker-compose.yml` и `grafana.ini` запустите оба экземпляра Grafana на разных машинах.

## Шаг 3: Настройка балансировщика нагрузки (Nginx)

Установим Nginx на отдельную машину и настроим его для распределения запросов между нашими экземплярами Grafana.

Конфигурационный файл для Nginx (например, `/etc/nginx/sites-available/grafana.conf`):

```nginx
# Определяем группу серверов (бэкендов)
upstream grafana_backend {
    # Распределяем нагрузку поровну (Round Robin по умолчанию)
    # Можно добавить weight для весового распределения
    server <IP-адрес_grafana-1>:3000;
    server <IP-адрес_grafana-2>:3000;
}

server {
    listen 80;
    server_name grafana.your-domain.com; # Доменное имя для доступа к Grafana

    location / {
        # Перенаправляем все запросы на нашу группу серверов
        proxy_pass http://grafana_backend;

        # Передаем необходимые заголовки для корректной работы Grafana
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

После создания конфигурации создайте символическую ссылку в `sites-enabled` и перезапустите Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/grafana.conf /etc/nginx/sites-enabled/
sudo systemctl restart nginx
```

## Шаг 4: Проверка

Теперь вы можете получить доступ к Grafana через домен, указанный в конфигурации Nginx (`grafana.your-domain.com`).
Для проверки корректности работы кластера:

1.  Войдите в Grafana.
2.  Создайте новый дашборд или нового пользователя.
3.  Остановите один из экземпляров Grafana (например, `docker stop grafana` на одной из машин).
4.  Вы должны по-прежнему иметь доступ к Grafana через балансировщик, и все созданные вами данные (дашборд, пользователь) должны быть на месте, поскольку они хранятся в общей базе данных.
5.  Запустите остановленный экземпляр и остановите другой. Результат должен быть таким же.
