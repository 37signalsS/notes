# Пример: Настройка мониторинга PostgreSQL с помощью Ansible и Prometheus

## 1. Определения и базовые концепции

### Задача

Основная задача — автоматизировать развертывание базы данных [PostgreSQL](../../Databases/PostgreSQL/overview.md) и настроить её мониторинг с помощью [Prometheus](../../Prometheus/overview.md), используя систему управления конфигурациями [Ansible](../../Ansible/ansible_introduction.md).

Это типичный практический сценарий в DevOps, объединяющий развертывание сервиса и настройку его наблюдаемости.

### Используемые подходы

Для решения этой задачи мы будем использовать готовые [роли Ansible](../../Ansible/ansible_roles.md), что значительно ускоряет процесс. Будут задействованы роли для установки PostgreSQL, Prometheus и `postgres_exporter`.

Все чувствительные данные, такие как пароли, будут защищены с помощью механизма [Ansible Vault](../../Ansible/ansible_vault.md). Использование Vault является лучшей практикой для безопасного хранения секретов в системе контроля версий.

## 2. Практический сценарий

### 2.1. План работ

1.  **Установить PostgreSQL**: Используя готовую Ansible-роль, установить СУБД.
2.  **Настроить базу данных**:
    *   Создать базу `migrations`.
    *   Накатить базовые миграции.
    *   Создать пользователя `testuser` с паролем.
    *   Настроить `pg_hba.conf` и `postgresql.conf` для доступа извне.
3.  **Настроить Healthcheck**: После установки убедиться, что PostgreSQL доступен и отвечает на запросы.
4.  **Установить Prometheus PostgreSQL Exporter**: На ту же машину, где стоит PostgreSQL, установить экспортер метрик.
5.  **Настроить Healthcheck для экспортера**: Убедиться, что экспортер запущен и отдает метрики.
6.  **Установить Prometheus**: На отдельную ноду установить Prometheus.
7.  **Настроить Prometheus**: Сконфигурировать его для сбора метрик (скрейпинга) с `postgres_exporter`.
8.  **Защитить секреты**: Скрыть все чувствительные данные с помощью `ansible-vault`.

### 2.2. Установка и настройка PostgreSQL

Для установки рекомендуется использовать готовую роль `community.postgresql`.

**Пример SQL миграции:**
```sql
-- migration.sql
CREATE DATABASE migrations;
\c migrations;

CREATE TABLE public.transactions (
    id integer,
    "timestamp" integer,
    name text,
    size integer
);
-- ... и так далее
```
Для выполнения скрипта миграции можно использовать модуль `community.postgresql.postgresql_script`.

**Healthcheck для PostgreSQL:**
Используйте `delegate_to: localhost` и модуль `community.postgresql.postgresql_info` или `wait_for` для проверки доступности порта `5432` и выполнения простого запроса (например, `SELECT 1`).

### 2.3. Установка PostgreSQL Exporter

Рекомендуется использовать готовую роль, например `prometheus-community.postgres_exporter`.

**Пример настройки в плейбуке:**
```yaml
- hosts: postgres_server
  environment:
    DATA_SOURCE_NAME: 'postgresql://testuser:your_password@localhost:5432/migrations?sslmode=disable'
  roles:
    - role: prometheus-community.postgres_exporter
      # ... переменные для роли
```

**Healthcheck для экспортера:**
Используйте модуль `uri` для запроса к эндпоинту `http://your_postgres_host:9187/metrics`. Проверьте, что ответ содержит метрику `pg_up 1`.

### 2.4. Установка и настройка Prometheus

Prometheus следует устанавливать на отдельную ноду мониторинга. Рекомендуется использовать роль `cloudalchemy.prometheus`.

**Healthcheck для Prometheus:**
Просто откройте веб-интерфейс Prometheus по адресу `http://your_prometheus_host:9090` и проверьте в разделе `Status -> Targets`, что ваш `postgres_exporter` имеет статус `UP`.

## 3. Продвинутые детали

### 3.1. Ключевые моменты конфигурации PostgreSQL

*   **`postgresql.conf`**: Убедитесь, что параметр `listen_addresses` установлен в `*`, чтобы разрешить подключения с любых IP-адресов. Это необходимо для доступа к базе данных с сервера приложений и для подключения экспортера.
*   **`pg_hba.conf`**: Добавьте правила, разрешающие подключения для вашего пользователя. Для упрощения можно разрешить доступ со всех адресов, но в production-среде следует указывать конкретные IP-адреса или подсети.
    ```
    # TYPE  DATABASE        USER            ADDRESS                 METHOD
    host    all             all             0.0.0.0/0               md5
    host    all             all             ::/0                    md5
    ```

### 3.2. Конфигурация PostgreSQL Exporter

*   Экспортер настраивается через переменные окружения. Ключевая переменная — `DATA_SOURCE_NAME`, которая содержит строку подключения к базе данных.
*   Эту переменную необходимо установить для сервиса экспортера. В плейбуке это можно сделать через блок `environment`, как показано в практическом сценарии.

### 3.3. Конфигурация Prometheus

*   Основная конфигурация Prometheus — это `scrape_configs`, где вы указываете, какие эндпоинты (targets) нужно опрашивать.
*   Вам нужно добавить новую `job`, которая будет опрашивать ваш `postgres_exporter`.

**Пример конфигурации `scrape_configs`:**
```yaml
prometheus_scrape_configs:
  - job_name: 'postgres'
    static_configs:
      - targets: ['your_postgres_host:9187']
```
Эту структуру нужно передать в переменную для роли `cloudalchemy.prometheus`.

## 4. Заключение

Целью данной практической работы является отработка навыка работы с готовыми Ansible-ролями, а также демонстрация того, насколько можно ускорить свою работу, используя уже существующие решения. Это типичная задача в DevOps-практике, объединяющая развертывание сервиса и настройку его мониторинга.