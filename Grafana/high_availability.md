# Grafana: Высокая доступность (HA)

## Определения

**Высокая доступность (HA)** — архитектурный подход с развёртыванием нескольких stateless-экземпляров Grafana за балансировщиком нагрузки с общей внешней БД.

**Текущая версия (март 2026):** Grafana 12.x поддерживает HA-режим

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Установка через Docker](./Installation/docker_compose_setup.md) — развёртывание в Docker
- [Установка через Helm](./Installation/grafana_helm_installation.md) — развёртывание в Kubernetes

### Ключевые компоненты HA

| Компонент | Назначение |
| :--- | :--- |
| **Балансировщик** | Nginx, HAProxy, облачные LB — распределение трафика |
| **Экземпляры Grafana** | 2+ stateless-пода с одинаковой конфигурацией |
| **Внешняя БД** | PostgreSQL/MySQL — единое хранилище состояния |

## Основные концепции

### Архитектура

Grafana не имеет встроенной кластеризации; HA реализуется через внешние компоненты:

1. **Общая БД** — PostgreSQL/MySQL (не SQLite) для хранения состояния.
2. **Stateless-экземпляры** — 2+ идентичных пода Grafana.
3. **Балансировщик** — Nginx, HAProxy, облачные решения.

**Принцип работы:**

1. Пользователь → балансировщик.
2. Балансировщик → доступный экземпляр Grafana.
3. Grafana → общая БД (чтение/запись).
4. Изменения видны на всех экземплярах мгновенно.

### Поддерживаемые БД

| БД | Версия | Примечание |
| :--- | :--- | :--- |
| **PostgreSQL** | 12+ | Рекомендуется, лучшая совместимость |
| **MySQL** | 8.0+ | Поддерживается |
| **SQLite** | — | ⚠️ Не подходит для HA |

## Практические сценарии

### Настройка HA-кластера с Docker, PostgreSQL и Nginx

#### **Шаг 1: Настройка внешней базы данных (PostgreSQL)**

1. **Создайте `docker-compose.yml` для PostgreSQL:**

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

3. **Запустите контейнер:** Сделайте скрипт исполняемым (`chmod +x init-user-db.sh`) и выполните `docker-compose up -d`.

#### **Шаг 2: Настройка экземпляров Grafana**

1. **Создайте `docker-compose.yml` для каждого экземпляра Grafana:**

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

2. **Настройте `grafana.ini`:** В секции `[database]` укажите подключение к PostgreSQL.

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

3. **Запустите экземпляры** Grafana на разных машинах.

#### **Шаг 3: Настройка балансировщика нагрузки (Nginx)**

1. **Создайте конфигурационный файл** (например, `/etc/nginx/sites-available/grafana.conf`) на отдельной машине с Nginx:

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

2. **Активируйте конфигурацию** и перезапустите Nginx:

    ```bash
    sudo ln -s /etc/nginx/sites-available/grafana.conf /etc/nginx/sites-enabled/
    sudo systemctl restart nginx
    ```

#### **Шаг 4: Проверка отказоустойчивости**

Доступ к Grafana теперь осуществляется через `grafana.your-domain.com`. Для проверки:

1. Создайте дашборд.
2. Остановите один из экземпляров Grafana (`docker stop grafana`).
3. Убедитесь, что UI доступен и дашборд на месте.
4. Запустите остановленный экземпляр и остановите другой — результат должен быть таким же.

## Дополнительная информация

### Важные замечания

- **БД как единая точка отказа:** В примере с Docker PostgreSQL — SPOF. Для production используйте отказоустойчивый кластер БД (Patroni, PGBouncer, потоковая репликация).
- **Secret key:** Все экземпляры должны использовать одинаковый `secret_key` в `grafana.ini` для корректной работы сессий (особенно OAuth).
- **Kubernetes:** Для HA в K8s используйте `replicas: 2+` в Helm-чарте с включённой персистентностью.

### Production Checklist

- [ ] **Отказоустойчивая БД:** Кластер PostgreSQL/MySQL с репликацией
- [ ] **Балансировщик:** Health checks, automatic failover
- [ ] **Secret key:** Одинаковый во всех экземплярах
- [ ] **Мониторинг:** ServiceMonitor для метрик Grafana
- [ ] **Backup:** Регулярный бэкап БД
- [ ] **Resource limits:** CPU/memory limits для подов

Подробная [документация HA](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/high-availability/) доступна на сайте Grafana Labs. Для настройки отказоустойчивого кластера PostgreSQL см. [Patroni](https://patroni.readthedocs.io/). Дополнительные примеры развёртывания — в [установке через Helm](./Installation/grafana_helm_installation.md).
