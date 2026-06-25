# Ansible: Мониторинг PostgreSQL с использованием Prometheus

## Определения

**Мониторинг PostgreSQL с Prometheus и Ansible** — процесс автоматизированного развертывания инструментов для наблюдения за состоянием базы данных. Ansible управляет конфигурацией, `postgres_exporter` осуществляет сбор метрик, а Prometheus агрегирует и хранит данные временных рядов (TSDB).

**`postgres_exporter`** — специализированный компонент, преобразующий внутренние показатели PostgreSQL в формат, понятный Prometheus.

## Базовые концепции

### Архитектура стека мониторинга

Для полноценного наблюдения за СУБД (система управления базами данных) используются следующие компоненты:

| Компонент | Назначение | Ссылка на описание |
|---|---|---|
| **PostgreSQL** | Объект мониторинга (СУБД) | [PostgreSQL: Обзор](../../Databases/PostgreSQL/overview.md) |
| **Postgres Exporter** | Агент сбора метрик | [Экспортеры Prometheus](../../Prometheus/Exporters/overview.md) |
| **Prometheus** | Система хранения и обработки метрик | [Prometheus: Обзор](../../Prometheus/overview.md) |

### Используемые роли Ansible Galaxy

Для ускорения развертывания рекомендуется использовать проверенные роли:

- **`community.postgresql`**: Установка и базовая настройка базы данных.
- **`prometheus-community.postgres_exporter`**: Установка и конфигурация экспортера.
- **`cloudalchemy.prometheus`**: Развертывание и настройка сервера Prometheus.

Установка необходимых зависимостей на контрольном узле:

```bash
ansible-galaxy install community.postgresql
ansible-galaxy collection install prometheus-community.postgres_exporter
ansible-galaxy collection install cloudalchemy.prometheus
```

### Безопасность и секреты

Строки подключения к базе данных и пароли являются конфиденциальной информацией. В Ansible их необходимо защищать с помощью **[Ansible Vault](../Vault/basics.md)**.

---

## Практические сценарии

### Сценарий: Развертывание полного стека мониторинга

Данный пример демонстрирует настройку двух серверов: одного с базой данных и экспортером, второго — с сервером мониторинга.

#### 1. Подготовка инвентаря и переменных

**Файл `hosts.ini`:**

```ini
[postgres_servers]
pg01 ansible_host=192.168.55.10

[monitoring_servers]
mon01 ansible_host=192.168.55.20
```

**Переменные группы (`group_vars/postgres_servers.yml`):**

```yaml
postgresql_databases:
  - name: myapp_db

postgresql_users:
  - name: myapp_user
    pass: "{{ db_password }}"
```

**Секреты (зашифрованы через Vault):**

```yaml
db_password: "MySuperSecretPassword"
```

#### 2. Плейбук для настройки базы данных и экспортера

```yaml
---
- name: Setup PostgreSQL and Exporter
  hosts: postgres_servers
  become: true
  vars:
    # Формирование DSN (Data Source Name) для подключения экспортера
    postgres_exporter_dsn: "postgresql://{{ postgresql_users[0].name }}:{{ db_password }}@localhost:5432/{{ postgresql_databases[0].name }}?sslmode=disable"

  roles:
    - role: community.postgresql
      vars:
        postgresql_conf:
          - name: listen_addresses
            value: '*'
        postgresql_hba_entries:
          - { type: host, database: all, user: all, address: '0.0.0.0/0', method: md5 }

    - role: prometheus-community.postgres_exporter
      vars:
        postgres_exporter_environment_vars:
          DATA_SOURCE_NAME: "{{ postgres_exporter_dsn }}"

  post_tasks:
    - name: Проверка доступности метрик экспортера
      ansible.builtin.uri:
        url: "http://localhost:9187/metrics"
        return_content: yes
      register: metrics_page
      until: "'pg_up 1' in metrics_page.content"
      retries: 5
      delay: 10
```

#### 3. Плейбук для сервера Prometheus

```yaml
---
- name: Setup Prometheus Server
  hosts: monitoring_servers
  become: true

  roles:
    - role: cloudalchemy.prometheus
      vars:
        prometheus_scrape_configs:
          - job_name: 'postgres'
            static_configs:
              - targets:
                  - "{{ hostvars[item]['ansible_host'] }}:9187"
            loop: "{{ groups['postgres_servers'] }}"
```

---

## Дополнительная информация

### Верификация в интерфейсе Prometheus

После успешного выполнения плейбуков:

1. Перейдите по адресу: `http://<monitoring_server_ip>:9090`.
2. Откройте меню **Status → Targets**.
3. Убедитесь, что эндпоинт `postgres_exporter` (порт 9187) находится в статусе **UP**.

### Ключевые метрики для анализа

| Метрика | Описание |
|---|---|
| `pg_up` | Наличие успешного подключения к БД (1 = OK). |
| `pg_stat_activity_count` | Количество активных сессий. |
| `pg_stat_database_tps` | Производительность: транзакций в секунду. |
| `pg_stat_database_blks_hit` | Эффективность кэширования (Buffer Cache Hit Ratio). |

### Связанные руководства

- **[Примеры установки PostgreSQL](./example_postgresql_setup.md)** — базовые сценарии развертывания БД.
- **[Full-Stack Observability для PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md)** — концепция комплексной наблюдаемости.
- **[Экспортеры Prometheus](../../Prometheus/Exporters/overview.md)** — общий обзор механизмов сбора метрик.
