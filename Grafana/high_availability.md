# Grafana: Высокая доступность (High Availability)

## Определения

**Высокая доступность (High Availability, HA) в Grafana** — это архитектурный подход, обеспечивающий отказоустойчивость системы путем развертывания нескольких экземпляров Grafana. Вместо одного сервера, который является единой точкой отказа, используется кластер, работающий за балансировщиком нагрузки и использующий общую базу данных для хранения состояния.

Если один экземпляр выходит из строя, остальные продолжают работать, а балансировщик автоматически перенаправляет на них трафик, минимизируя время простоя и потерю доступа к визуализациям и оповещениям.

## Основные концепции

### Архитектура отказоустойчивого кластера

Grafana не имеет встроенной кластеризации. Режим высокой доступности реализуется с помощью внешних компонентов. Ключевая идея заключается в том, что состояние Grafana (дашборды, пользователи, источники данных, роли и т.д.) хранится не в локальной SQLite базе данных, а во внешней, общей для всех экземпляров базе данных, такой как **PostgreSQL** или **MySQL**.

Архитектура такого решения включает три основных компонента:

1.  **Общая база данных (Shared Database):** Один экземпляр PostgreSQL (в идеале — отказоустойчивый кластер PostgreSQL), который служит единым источником истины для всех экземпляров Grafana.
2.  **Экземпляры Grafana (Grafana Instances):** Два или более идентичных экземпляра Grafana, настроенных на работу с общей базой данных. Они являются stateless-компонентами.
3.  **Балансировщик нагрузки (Load Balancer):** Компонент (например, Nginx, HAProxy или облачный балансировщик), который распределяет пользовательский трафик между доступными экземплярами Grafana.

### Поток работы

1.  Пользователь обращается к Grafana через единый адрес балансировщика.
2.  Балансировщик перенаправляет запрос на один из доступных экземпляров Grafana.
3.  Экземпляр Grafana выполняет операцию (чтение или запись), обращаясь к общей базе данных.
4.  Таким образом, любое изменение, сделанное через один экземпляр (например, создание нового дашборда), мгновенно становится доступным на всех остальных.

## Практические сценарии

### Пример настройки с использованием Docker, PostgreSQL и Nginx

#### Шаг 1: Настройка внешней базы данных (PostgreSQL)

Создадим `docker-compose.yml` для запуска PostgreSQL:
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

Создайте скрипт `init-user-db.sh` для инициализации базы данных и пользователя. Этот скрипт будет выполнен автоматически при первом запуске контейнера.
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
Сделайте скрипт исполняемым (`chmod +x init-user-db.sh`) и запустите контейнер: `docker-compose up -d`.

#### Шаг 2: Настройка экземпляров Grafana

Для каждого экземпляра Grafana используется следующий `docker-compose.yml`:
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

Ключевая настройка выполняется в файле `grafana.ini`. Секцию `[database]` необходимо привести к следующему виду:
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
> **Примечание:** Чтобы получить `grafana.ini`, можно сначала запустить контейнер без кастомной конфигурации, скопировать файл (`docker cp grafana:/etc/grafana/grafana.ini .`), изменить его и перезапустить контейнер уже с проброшенным файлом.

После подготовки `docker-compose.yml` и `grafana.ini` запустите экземпляры Grafana на разных машинах.

#### Шаг 3: Настройка балансировщика нагрузки (Nginx)

Установите Nginx на отдельную машину и создайте конфигурационный файл (например, `/etc/nginx/sites-available/grafana.conf`):
```nginx
# Определяем группу серверов (бэкендов)
upstream grafana_backend {
    # Распределяем нагрузку поровну (Round Robin по умолчанию)
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
Активируйте конфигурацию и перезапустите Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/grafana.conf /etc/nginx/sites-enabled/
sudo systemctl restart nginx
```

#### Шаг 4: Проверка отказоустойчивости

Теперь доступ к Grafana осуществляется через домен, указанный в конфигурации Nginx (`grafana.your-domain.com`).

Для проверки корректности работы кластера:
1.  Войдите в Grafana.
2.  Создайте новый дашборд или пользователя.
3.  Остановите один из экземпляров Grafana (`docker stop grafana` на одной из машин).
4.  Убедитесь, что вы по-прежнему имеете доступ к Grafana, и все созданные данные на месте.
5.  Запустите остановленный экземпляр и остановите другой. Результат должен быть таким же.

## Дополнительная информация

*   **Отказоустойчивость базы данных:** В приведенном примере используется один экземпляр PostgreSQL, который сам по себе является единой точкой отказа. Для полноценной производственной среды рекомендуется использовать отказоустойчивый кластер баз данных (например, PostgreSQL с потоковой репликацией и автоматическим переключением).
*   **Альтернативы:** Вместо PostgreSQL можно использовать MySQL. В качестве балансировщика нагрузки могут выступать HAProxy, облачные решения (AWS ALB, Google Cloud Load Balancer) и другие.
*   **Сессии пользователей:** Для корректной работы входа в систему через социальные сети (OAuth) или при использовании `enforce_login`, все экземпляры Grafana должны использовать один `secret_key` в `grafana.ini`.
