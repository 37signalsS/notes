# Grafana: Высокая доступность

## Определения

**Высокая доступность (High Availability, HA)** в контексте Grafana — архитектурный подход, подразумевающий развёртывание нескольких экземпляров приложения без сохранения состояния (stateless) за балансировщиком нагрузки с использованием общей внешней базы данных. Общие принципы обеспечения отказоустойчивости описаны в разделе **[обзор High Availability](../Concepts/High_Availability/ha_overview.md)**.

**Текущая версия (март 2026):** Grafana 12.x поддерживает HA-режим.

**Связанные темы:**

- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Установка через Docker](./Installation/docker_compose_setup.md) — развёртывание в Docker
- [Установка через Helm](./Installation/grafana_helm_installation.md) — развёртывание в Kubernetes

## Базовые концепции

### Архитектура HA

Grafana не имеет встроенных механизмов кластеризации; высокая доступность реализуется через внешние компоненты и архитектурные решения:

1. **Общая база данных** — использование PostgreSQL или MySQL (вместо локальной SQLite) для хранения всех настроек, пользователей и дашбордов.
2. **Экземпляры без состояния (Stateless)** — запуск двух и более идентичных экземпляров Grafana, которые не хранят уникальных данных локально.
3. **Балансировщик нагрузки** — Nginx, HAProxy или облачные решения для распределения входящего трафика.

**Принцип работы:**

1. Пользователь обращается к балансировщику нагрузки.
2. Балансировщик перенаправляет запрос на один из доступных экземпляров Grafana.
3. Экземпляр Grafana взаимодействует с общей базой данных для чтения или записи данных.
4. Любые изменения конфигурации (например, создание дашборда) мгновенно становятся доступными на всех узлах кластера через общую БД.

### Ключевые компоненты

| Компонент | Назначение |
| :--- | :--- |
| **Балансировщик** | Распределение трафика между узлами (Nginx, HAProxy, AWS ALB) |
| **Экземпляры Grafana** | 2+ независимых узла с идентичной конфигурацией |
| **Внешняя БД** | Единое хранилище состояния (PostgreSQL, MySQL) |

### Поддерживаемые базы данных

| СУБД | Версия | Примечание |
| :--- | :--- | :--- |
| **PostgreSQL** | 12+ | Рекомендуемый вариант, лучшая совместимость |
| **MySQL** | 8.0+ | Полная поддержка |
| **SQLite** | — | Не подходит для HA-режима |

## Практические сценарии

### Настройка HA-кластера с Docker, PostgreSQL и Nginx

#### Шаг 1: Настройка внешней базы данных (PostgreSQL)

1. **Создайте файл `docker-compose.yml` для базы данных:**

    ```yaml
    services:
      postgres:
        image: postgres:16
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

2. **Создайте скрипт инициализации `init-user-db.sh`:**

    ```bash
    #!/bin/bash
    set -e
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        CREATE USER grafana_user WITH PASSWORD 'grafana_password';
        CREATE DATABASE grafana WITH OWNER = grafana_user;
        GRANT ALL PRIVILEGES ON DATABASE grafana TO grafana_user;
    EOSQL
    ```

3. **Запустите контейнер:** Установите права на выполнение (`chmod +x init-user-db.sh`) и выполните `docker compose up -d`.

#### Шаг 2: Настройка экземпляров Grafana

1. **Подготовьте конфигурацию экземпляра (`docker-compose.yml`):**

    ```yaml
    services:
      grafana:
        image: grafana/grafana:12.x
        container_name: grafana
        restart: unless-stopped
        ports:
          - "3000:3000"
        volumes:
          - ./grafana.ini:/etc/grafana/grafana.ini
    ```

2. **Скорректируйте `grafana.ini`:** В секции `[database]` укажите параметры подключения.

    ```ini
    [database]
    type = postgres
    host = <IP-адрес_сервера_PostgreSQL>:5432
    name = grafana
    user = grafana_user
    password = grafana_password
    ssl_mode = disable

    [security]
    # Обязательно одинаковый ключ на всех экземплярах
    secret_key = some_random_long_string
    ```

3. **Запустите узлы** Grafana на разных серверах или портах.

#### Шаг 3: Настройка балансировщика нагрузки (Nginx)

1. **Создайте конфигурацию Nginx** (например, `/etc/nginx/sites-available/grafana.conf`):

    ```nginx
    upstream grafana_backend {
        server <IP-адрес_grafana-1>:3000;
        server <IP-адрес_grafana-2>:3000;
    }

    server {
        listen 80;
        server_name grafana.example.com;

        location / {
            proxy_pass http://grafana_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
    ```

2. **Примените настройки:**

    ```bash
    sudo ln -s /etc/nginx/sites-available/grafana.conf /etc/nginx/sites-enabled/
    sudo systemctl restart nginx
    ```

## Дополнительная информация

### Важные соображения

- **База данных как точка отказа:** В базовом примере PostgreSQL является единой точкой отказа (SPOF). Для продуктивных сред используйте отказоустойчивые решения: Patroni, PGBouncer или облачные управляемые БД (RDS, Cloud SQL).
- **Секретный ключ (Secret key):** Параметр `secret_key` в `grafana.ini` должен быть идентичен на всех узлах для корректной работы сессий и механизмов аутентификации (OAuth).
- **Kubernetes:** При использовании Helm-чарта установите `replicas: 2` или более и настройте параметры внешней БД в `values.yaml`.

### Контрольный список (Production Checklist)

- [ ] **Отказоустойчивая СУБД:** Кластер PostgreSQL или MySQL с автоматическим переключением (failover).
- [ ] **Балансировка:** Настройка проверки доступности (health checks) на балансировщике.
- [ ] **Консистентность сессий:** Одинаковый `secret_key` на всех экземплярах.
- [ ] **Наблюдаемость:** Мониторинг каждого экземпляра Grafana и метрик базы данных.
- [ ] **Резервное копирование:** Регулярные бэкапы внешней БД.

Подробная информация доступна в [официальной документации Grafana](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/high-availability/). Для настройки кластера базы данных см. [Patroni](https://patroni.readthedocs.io/). См. также [установку через Helm](./Installation/grafana_helm_installation.md).
