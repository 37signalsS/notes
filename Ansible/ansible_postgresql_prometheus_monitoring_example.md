# 7.8 Пример: Настройка мониторинга PostgreSQL с помощью Ansible и Prometheus

## Задача

Перед нами стоит задача — установить базу данных PostgreSQL на виртуальную машину, а также настроить экспорт метрик для того, чтобы мы могли следить за её основными жизненными показателями.

Наши подзадачи:
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
8.  **Защитить секреты**: Скрыть все чувствительные данные (пароли, ключи) с помощью `ansible-vault`.

## 1. Установка и настройка PostgreSQL

Для установки рекомендуется использовать готовую роль, например, от `community.postgresql`.

**Ключевые моменты конфигурации:**

*   **`postgresql.conf`**: Убедитесь, что параметр `listen_addresses` установлен в `*`, чтобы разрешить подключения с любых IP-адресов.
*   **`pg_hba.conf`**: Добавьте правила, разрешающие подключения для вашего пользователя. Например:
    ```
    # TYPE  DATABASE        USER            ADDRESS                 METHOD
    host    all             all             0.0.0.0/0               md5
    host    all             all             ::/0                    md5
    ```

**Миграции:**
Можно использовать модуль `community.postgresql.postgresql_script` для выполнения SQL-скрипта.

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

**Healthcheck для PostgreSQL:**
Используйте `delegate_to: localhost` и модуль `community.postgresql.postgresql_info` или просто `wait_for`, чтобы проверить доступность порта `5432` и выполнение простого запроса (например, `SELECT 1`).

## 2. Установка PostgreSQL Exporter

Рекомендуется использовать готовую роль, например `prometheus-community.postgres_exporter`.

**Ключевые моменты конфигурации:**

*   Экспортер настраивается через переменные окружения. Ключевая переменная — `DATA_SOURCE_NAME`.
*   Эту переменную нужно установить для сервиса экспортера. В плейбуке это можно сделать через блок `environment`.

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

## 3. Установка и настройка Prometheus

Prometheus следует устанавливать на отдельную ноду мониторинга. Рекомендуется использовать роль `cloudalchemy.prometheus`.

**Ключевые моменты конфигурации:**

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

**Healthcheck для Prometheus:**
Просто откройте веб-интерфейс Prometheus по адресу `http://your_prometheus_host:9090` и проверьте в разделе `Status -> Targets`, что ваш `postgres_exporter` имеет статус `UP`.

## 4. Использование Ansible Vault

Все чувствительные данные (пароли от БД, секретные ключи) должны быть зашифрованы.

1.  **Создайте зашифрованный файл переменных:**
    ```bash
    ansible-vault create vars/secrets.yml
    ```
2.  **Поместите в него все секреты:**
    ```yaml
    # vars/secrets.yml
    postgres_password: "your_super_secret_password"
    ```
3.  **Подключите этот файл в плейбуке:**
    ```yaml
    - hosts: all
      vars_files:
        - vars/secrets.yml
      # ...
    ```
4.  **Запускайте плейбук с ключом:**
    ```bash
    ansible-playbook your_playbook.yml --ask-vault-pass
    ```

## Заключение

Целью данной практической работы является отработка навыка работы с готовыми Ansible-ролями, а также демонстрация того, насколько можно ускорить свою работу, используя уже существующие решения. Это типичная задача в DevOps-практике, объединяющая развертывание сервиса и настройку его мониторинга.
