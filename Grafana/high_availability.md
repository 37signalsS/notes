# Grafana: Высокая доступность (High Availability)

## Определения

**Высокая доступность (High Availability, HA) в Grafana** — архитектурный подход, обеспечивающий отказоустойчивость путем развертывания нескольких stateless-экземпляров Grafana. Вместо одного сервера, являющегося единой точкой отказа, используется кластер, работающий за балансировщиком нагрузки и использующий общую внешнюю базу данных для хранения состояния.

При отказе одного из экземпляров балансировщик автоматически перенаправляет трафик на рабочие узлы, минимизируя время простоя.

## Основные концепции

### Архитектура

Grafana не имеет встроенной кластеризации; режим HA реализуется с помощью внешних компонентов. Состояние Grafana (дашборды, пользователи, источники данных) хранится не в локальной SQLite, а во внешней базе данных, общей для всех экземпляров, такой как **PostgreSQL** или **MySQL**.

Архитектура включает три компонента:

1.  **Общая база данных (Shared Database):** Внешняя реляционная СУБД (например, PostgreSQL), которая служит единым источником истины.
2.  **Экземпляры Grafana (Grafana Instances):** Два или более идентичных stateless-экземпляра Grafana, настроенных на работу с общей базой данных.
3.  **Балансировщик нагрузки (Load Balancer):** Компонент (Nginx, HAProxy, облачный балансировщик), распределяющий трафик между доступными экземплярами Grafana.

### Принцип работы

1.  Пользователь обращается к Grafana через единый адрес балансировщика.
2.  Балансировщик перенаправляет запрос на один из доступных экземпляров Grafana.
3.  Экземпляр Grafana выполняет операцию, обращаясь к общей базе данных для чтения или записи состояния.
4.  Любое изменение, сделанное через один экземпляр, мгновенно становится доступным на всех остальных.

## Практические сценарии

### Настройка HA-кластера с Docker, PostgreSQL и Nginx

#### **Шаг 1: Настройка внешней базы данных (PostgreSQL)**

1.  **Создайте `docker-compose.yml` для PostgreSQL:**
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
          - ./init-user-db.sh:/docker-entrypoint-initdb.d/init-user-db.sh
          - postgres_data:/var/lib/postgresql/data
        environment:
          - POSTGRES_PASSWORD=your_super_secret_password
    volumes:
      postgres_data:
    ```

2.  **Создайте скрипт инициализации `init-user-db.sh`:**
    ```bash
    #!/bin/bash
    set -e
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        CREATE USER grafana_user WITH PASSWORD 'grafana_password';
        CREATE DATABASE grafana WITH OWNER = grafana_user;
        GRANT ALL PRIVILEGES ON DATABASE grafana TO grafana_user;
    EOSQL
    ```

3.  **Запустите контейнер:** Сделайте скрипт исполняемым (`chmod +x init-user-db.sh`) и выполните `docker-compose up -d`.

#### **Шаг 2: Настройка экземпляров Grafana**

1.  **Создайте `docker-compose.yml` для каждого экземпляра Grafana:**
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
          - ./grafana.ini:/etc/grafana/grafana.ini
    ```

2.  **Настройте `grafana.ini`:** В секции `[database]` укажите подключение к PostgreSQL.
    ```ini
    [database]
    type = postgres
    host = <IP-адрес_сервера_PostgreSQL>:5432
    name = grafana
    user = grafana_user
    password = grafana_password
    ssl_mode = disable
    ```
    > **Примечание:** Чтобы получить `grafana.ini`, можно скопировать его из запущенного контейнера: `docker cp grafana:/etc/grafana/grafana.ini .`.

3.  **Запустите экземпляры** Grafana на разных машинах.

#### **Шаг 3: Настройка балансировщика нагрузки (Nginx)**

1.  **Создайте конфигурационный файл** (например, `/etc/nginx/sites-available/grafana.conf`) на отдельной машине с Nginx:
    ```nginx
    upstream grafana_backend {
        server <IP-адрес_grafana-1>:3000;
        server <IP-адрес_grafana-2>:3000;
    }

    server {
        listen 80;
        server_name grafana.your-domain.com;

        location / {
            proxy_pass http://grafana_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
    ```

2.  **Активируйте конфигурацию** и перезапустите Nginx:
    ```bash
    sudo ln -s /etc/nginx/sites-available/grafana.conf /etc/nginx/sites-enabled/
    sudo systemctl restart nginx
    ```

#### **Шаг 4: Проверка отказоустойчивости**

Доступ к Grafana теперь осуществляется через `grafana.your-domain.com`. Для проверки:
1.  Создайте дашборд.
2.  Остановите один из экземпляров Grafana (`docker stop grafana`).
3.  Убедитесь, что UI доступен и дашборд на месте.
4.  Запустите остановленный экземпляр и остановите другой — результат должен быть таким же.

## Дополнительная информация

*   **Отказоустойчивость базы данных**: В данном примере PostgreSQL является единой точкой отказа. В производственной среде необходимо использовать отказоустойчивый кластер баз данных (например, PostgreSQL с потоковой репликацией).
*   **Альтернативы**: Вместо PostgreSQL можно использовать MySQL. В качестве балансировщика могут выступать HAProxy или облачные решения (AWS ALB, Google Cloud Load Balancer).
*   **Сессии пользователей**: Для корректной работы аутентификации (особенно OAuth) все экземпляры Grafana в кластере должны использовать одинаковый `secret_key` в `grafana.ini`.
