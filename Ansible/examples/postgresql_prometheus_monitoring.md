# Мониторинг PostgreSQL с помощью Prometheus и Ansible

## Определения

**Мониторинг PostgreSQL** — комплексный процесс сбора, хранения и визуализации метрик производительности БД для обеспечения стабильности и быстродействия системы.

**postgres_exporter** — специализированный сервис мониторинга PostgreSQL для Prometheus. Подробное описание и параметры порта приведены в **[Каталоге экспортеров](../../Prometheus/Exporters/other_exporters.md#1-базы-данных-databases)**.

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

Для автоматизации развертывания рекомендуются официальные коллекции из Ansible Galaxy:

- **`community.postgresql`**: Настройка БД, расширений (таких как `pg_stat_statements`) и создание пользователя для мониторинга.
- **`prometheus.prometheus.postgres_exporter`**: Установка и запуск экспортера.
- **`prometheus.prometheus.prometheus`**: Развертывание сервера Prometheus (заменяет устаревшую роль `cloudalchemy.prometheus`).

Установка зависимостей на контрольном узле:

```bash
ansible-galaxy collection install community.postgresql # → модули БД установлены
ansible-galaxy collection install prometheus.prometheus # → официальная коллекция Prometheus установлена
```

### Безопасность и секреты

Для подключения экспортера требуется специальный пользователь в PostgreSQL с правами `pg_monitor`. Пароли и строки подключения (DSN) необходимо шифровать с помощью **[Ansible Vault](../Vault/basics.md)**.

---

## Практические сценарии

### Сценарий 1: Подготовка базы данных (pg_stat_statements)

Для полноценного мониторинга запросов **обязательно** включение расширения `pg_stat_statements`. Это позволит собирать метрики производительности запросов, а не только системную информацию.

1. Добавление модуля в конфигурацию `postgresql.conf`:
```ini
shared_preload_libraries = 'pg_stat_statements'
# Требуется перезапуск PostgreSQL
```
2. Создание расширения в базе данных (может быть выполнено через Ansible):
```yaml
- name: Установка расширения pg_stat_statements
  community.postgresql.postgresql_ext:
    name: pg_stat_statements
    db: postgres
  become_user: postgres
```

### Сценарий 2: Развертывание кластера мониторинга

Данный сценарий настраивает мониторинг PostgreSQL на выделенном сервере с использованием официальной коллекции.

#### 1. Подготовка инвентаря

**Файл `hosts.ini`:**

```ini
[postgres_hosts]
db-master ansible_host=192.168.55.10

[prometheus_hosts]
monitoring-01 ansible_host=192.168.55.20
```

#### 2. Плейбук настройки базы и экспортера

Плейбук создает пользователя с ограниченными правами, а также запускает агент сбора метрик с включенной поддержкой автообнаружения баз данных. Одной из лучших практик также является использование `queries.yaml` для сбора кастомных бизнес-метрик (передается в экспортер).

```yaml
---
- name: Configure PostgreSQL Exporter
  hosts: postgres_hosts
  become: true
  vars:
    # Имя пользователя для мониторинга (системный стандарт PostgreSQL)
    exporter_user: "postgres_exporter"
    # DSN с безопасными параметрами
    postgres_exporter_dsn: "postgresql://{{ exporter_user }}:{{ vault_db_pass }}@localhost:5432/postgres?sslmode=disable"

  tasks:
    - name: Ensure PostgreSQL monitoring user exists
      community.postgresql.postgresql_user:
        name: "{{ exporter_user }}"
        password: "{{ vault_db_pass }}"
        role_attr_flags: "LOGIN"
        groups: "pg_monitor" # Встроенная роль в PostgreSQL 10+
      become_user: postgres

  roles:
    - role: prometheus.prometheus.postgres_exporter
      vars:
        postgres_exporter_dsn: "{{ postgres_exporter_dsn }}"
        # Включаем автоматическое обнаружение всех БД
        postgres_exporter_config_flags:
          auto-discover-databases: true

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

#### 3. Настройка сбора данных в Prometheus

Для сервера мониторинга используется роль `prometheus.prometheus.prometheus`.

```yaml
---
- name: Configure Prometheus Targets
  hosts: prometheus_hosts
  become: true
  tasks:
    - name: Add PostgreSQL target to Prometheus config
      ansible.builtin.set_fact:
        prometheus_targets:
          - job_name: 'postgresql_cluster'
            static_configs:
              - targets: "{{ groups['postgres_hosts'] | map('extract', hostvars, ['ansible_host']) | map('regex_replace', '$', ':9187') | list }}"
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

### Визуализация в Grafana

Для быстрого старта рекомендуется использовать официальные дашборды:
- **PostgreSQL Database** (ID: **9628**) — классический дашборд для системных метрик.
- **PostgreSQL pg_stat_statements** — дашборд для детального анализа производительности конкретных SQL-запросов.

## Смотрите также

- [Развертывание PostgreSQL через Ansible](./example_postgresql_setup.md)
- [Основы мониторинга с Prometheus](../../Prometheus/overview.md)
- [Использование Ansible Vault для секретов](../Vault/basics.md)
