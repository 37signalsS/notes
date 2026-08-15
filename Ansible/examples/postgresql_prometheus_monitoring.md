# Мониторинг PostgreSQL с помощью Prometheus и Ansible

## Определения

**Мониторинг PostgreSQL** — комплексный процесс сбора, хранения и визуализации метрик производительности БД для обеспечения стабильности и быстродействия системы.

**postgres_exporter** — специализированный сервис мониторинга PostgreSQL для Prometheus. В 2026 году актуальной является версия **v0.20.1**, поддерживающая PostgreSQL 17/18. Подробное описание и параметры порта приведены в **[Каталоге экспортеров](../../Prometheus/Exporters/other_exporters.md#1-базы-данных-databases)**.

**Full-Stack Observability** — подход, при котором мониторинг БД является частью общей системы наблюдаемости инфраструктуры, включающей метрики ОС, сетевого уровня и приложения. Подробнее см. в разделе **[Наблюдаемость PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md)**.

## Базовые концепции

### Архитектура стека мониторинга

Для полноценного наблюдения за базой данных используется классический стек:

| Компонент | Назначение | Основная ссылка |
|---|---|---|
| **PostgreSQL** | Объект мониторинга (источник данных). | [PostgreSQL](../../Databases/PostgreSQL/overview.md) |
| **Postgres Exporter** | Агент сбора метрик (9187/TCP). | [Экспортеры](../../Prometheus/Exporters/overview.md) |
| **Prometheus** | Сбор (scrape) и хранение метрик. | [Prometheus](../../Prometheus/overview.md) |
| **Grafana** | Визуализация данных (дашборды). | [Grafana](../../Grafana/grafana_overview.md) |

### Используемые роли и коллекции

Для автоматизации развертывания в 2026 году рекомендуется использовать следующие коллекции:

- **`community.postgresql` (v4.2.0+)**: Управление базой данных, расширениями (например, `pg_stat_statements`) и пользователями мониторинга.
- **`prometheus.prometheus` (v0.30.2+)**: Установка и настройка `postgres_exporter`, а также развертывание сервера Prometheus 3.x.

Установка зависимостей на контрольном узле:

```bash
# Установка актуальных коллекций
ansible-galaxy collection install community.postgresql
ansible-galaxy collection install prometheus.prometheus:>=0.30.2
```

### Безопасность и секреты

Для подключения экспортера требуется специальный пользователь в PostgreSQL с правами `pg_monitor`. Пароли и строки подключения (DSN) необходимо шифровать с помощью **[Ansible Vault](../Vault/basics.md)**.
В производственных средах обязательно использование **SSL** в DSN (`sslmode=verify-full`) с указанием корневого сертификата.

---

## Практические сценарии

### Сценарий 1: Подготовка базы данных (pg_stat_statements)

Для полноценного мониторинга запросов **обязательно** включение расширения `pg_stat_statements`. Это позволит собирать метрики производительности запросов, а не только системную информацию.

1. Добавление модуля в конфигурацию `postgresql.conf`:
```ini
shared_preload_libraries = 'pg_stat_statements'
# Настройка глубины анализа
pg_stat_statements.max = 10000
pg_stat_statements.track = all
# Требуется перезапуск PostgreSQL
```
2. Создание расширения в базе данных (через Ansible):
```yaml
- name: Установка расширения pg_stat_statements
  community.postgresql.postgresql_ext:
    name: pg_stat_statements
    db: postgres
  become_user: postgres
```

### Сценарий 2: Развертывание кластера мониторинга

Настройка мониторинга PostgreSQL на выделенном сервере с использованием официальной коллекции.

#### 1. Подготовка инвентаря

**Файл `hosts.ini`:**

```ini
[postgres_hosts]
db-master ansible_host=192.168.55.10

[prometheus_hosts]
monitoring-01 ansible_host=192.168.55.20
```

#### 2. Плейбук настройки базы и экспортера

Плейбук создает пользователя с ограниченными правами и запускает агент сбора метрик.

```yaml
---
- name: Настройка PostgreSQL Exporter
  hosts: postgres_hosts
  become: true
  vars:
    exporter_user: "postgres_exporter"
    # DSN с безопасными параметрами и шифрованием через Vault
    postgres_exporter_dsn: "postgresql://{{ exporter_user }}:{{ vault_db_pass }}@localhost:5432/postgres?sslmode=disable"

  tasks:
    - name: Создание пользователя для мониторинга
      community.postgresql.postgresql_user:
        name: "{{ exporter_user }}"
        password: "{{ vault_db_pass }}"
        role_attr_flags: "LOGIN"
        groups: "pg_monitor" # Встроенная роль с правами на чтение системных таблиц
      become_user: postgres

  roles:
    - role: prometheus.prometheus.postgres_exporter
      vars:
        postgres_exporter_version: "0.20.1"
        postgres_exporter_dsn: "{{ postgres_exporter_dsn }}"
        # Включаем автоматическое обнаружение всех БД и сбор метрик запросов
        postgres_exporter_config_flags:
          auto-discover-databases: true
          # В 2026 году флаги коллекторов настраиваются так:
          collector.stat_statements: true

  post_tasks:
    - name: Проверка статуса экспортера
      ansible.builtin.uri:
        url: "http://localhost:9187/metrics"
        return_content: yes
      register: result
      until: "'pg_up' in result.content"
      retries: 5
      delay: 5
      # → результат: HTTP 200 OK, метрики доступны
```

### Сценарий 3: Сбор кастомных бизнес-метрик (custom_queries.yaml)

Если стандартных метрик недостаточно (например, нужно мониторить количество заказов в статусе `pending`), используется механизм `queries.yaml`.

**1. Создание файла запросов `templates/postgres_queries.yaml.j2`:**
```yaml
pg_orders_total:
  query: "SELECT status, count(*) as count FROM orders GROUP BY status"
  metrics:
    - status:
        usage: "LABEL"
        description: "Статус заказа"
    - count:
        usage: "GAUGE"
        description: "Количество заказов"
```

**2. Подключение в Ansible:**
```yaml
- role: prometheus.prometheus.postgres_exporter
  vars:
    postgres_exporter_queries: "{{ lookup('template', 'postgres_queries.yaml.j2') | from_yaml }}"
```

### Сценарий 4: Настройка алертинга (Alertmanager)

Для оперативного реагирования необходимо настроить правила в Prometheus.

**Пример правил `postgresql_alerts.yml`:**
```yaml
groups:
  - name: PostgreSQL_Alerts
    rules:
      - alert: PostgresDown
        expr: pg_up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "База данных {{ $labels.instance }} недоступна"

      - alert: PostgresHighTransactionRollback
        expr: rate(pg_stat_database_xact_rollback[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень откатов транзакций на {{ $labels.instance }}"
```

---

## Дополнительная информация

### Ключевые метрики для анализа

| Метрика | Назначение | Нормальное значение |
|---|---|---|
| `pg_up` | Доступность базы данных. | `1` (база доступна). |
| `pg_stat_activity_count` | Количество текущих сессий. | Зависит от лимита `max_connections`. |
| `pg_database_size_bytes` | Размер базы данных на диске. | Постепенный рост без резких скачков. |
| `pg_stat_database_xact_commit` | Количество зафиксированных транзакций. | Должно быть значительно выше `xact_rollback`. |
| `pg_stat_statements_calls` | Количество вызовов запроса (требует `pg_stat_statements`). | Зависит от нагрузки приложения. |

### Устранение неполадок

1. **Ошибка "database is not accepting connections":**
   - Проверьте лимиты `max_connections` в PostgreSQL.
   - Убедитесь, что IP экспортера разрешен в `pg_hba.conf`.
2. **Метрики pg_stat_statements пусты:**
   - Проверьте, добавлено ли расширение в `shared_preload_libraries`.
   - Выполните `CREATE EXTENSION pg_stat_statements;` в нужной базе.
3. **Высокая нагрузка от экспортера:**
   - Используйте `--no-collector.process` для отключения сбора метрик самого процесса экспортера.
   - Ограничьте `auto-discover-databases`, если в кластере сотни БД.

### Визуализация в Grafana

Рекомендуемые дашборды:
- **PostgreSQL Database** (ID: **9628**) — стандарт де-факто.
- **PostgreSQL Overview (by Pigsty)** (ID: **12485**) — более современная визуализация для 2026 года.

## Смотрите также

- [Развертывание PostgreSQL через Ansible](./example_postgresql_setup.md)
- [Основы мониторинга с Prometheus](../../Prometheus/overview.md)
- [Ansible Vault: работа с секретами](../Vault/basics.md)
