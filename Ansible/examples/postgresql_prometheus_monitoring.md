# Ansible: Мониторинг PostgreSQL с Prometheus

## Определения

**Мониторинг PostgreSQL с Prometheus и Ansible** — автоматизированное развертывание стека мониторинга для PostgreSQL: Ansible управляет конфигурацией, `postgres_exporter` собирает метрики, Prometheus агрегирует и хранит данные временных рядов.

## Базовые концепции

### Компоненты стека мониторинга

| Компонент | Назначение | Ссылка |
|---|---|---|
| **PostgreSQL** | Объект мониторинга, реляционная СУБД | [Databases/PostgreSQL/overview.md](../../Databases/PostgreSQL/overview.md) |
| **Postgres Exporter** | Сбор метрик PostgreSQL и предоставление в формате Prometheus | [prometheus-community/postgres_exporter](https://github.com/prometheus-community/postgres_exporter) |
| **Prometheus** | Сбор, агрегация и хранение метрик временных рядов | [Prometheus/overview.md](../../Prometheus/overview.md) |

### Ansible Galaxy роли

| Роль | Назначение |
|---|---|
| `community.postgresql` | Установка и настройка PostgreSQL |
| `prometheus-community.postgres_exporter` | Установка и конфигурация экспортера |
| `cloudalchemy.prometheus` | Развертывание Prometheus Server |

Установка зависимостей на управляющем узле:

```bash
ansible-galaxy install community.postgresql
ansible-galaxy collection install prometheus-community.postgres_exporter
ansible-galaxy collection install cloudalchemy.prometheus
```

### Безопасность и секреты

Чувствительные данные (пароли, строки подключения) должны храниться в зашифрованном виде через [Ansible Vault](../Vault/basics.md).

---

## Практические сценарии

### Сценарий: Развертывание полного стека мониторинга

#### Шаг 1: Инвентарь и переменные

**Файл `hosts.ini`:**

```ini
[postgres_servers]
pg01 ansible_host=192.168.55.10

[monitoring_servers]
mon01 ansible_host=192.168.55.20
```

**Файл `group_vars/postgres_servers.yml`:**

```yaml
postgresql_databases:
  - name: myapp_db

postgresql_users:
  - name: myapp_user
    pass: "{{ db_password }}"
```

**Файл `group_vars/all.yml` (шифруется через Vault):**

```bash
ansible-vault encrypt group_vars/all.yml
```

```yaml
db_password: "MySuperSecretPassword"
```

#### Шаг 2: Плейбук для PostgreSQL и Exporter

```yaml
---
- name: Setup PostgreSQL and Exporter
  hosts: postgres_servers
  become: true
  vars:
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
    - name: Healthcheck postgres_exporter
      ansible.builtin.uri:
        url: "http://localhost:9187/metrics"
        return_content: yes
      register: metrics_page
      until: "'pg_up 1' in metrics_page.content"
      retries: 5
      delay: 10
```

#### Шаг 3: Плейбук для Prometheus

```yaml
---
- name: Setup Prometheus
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

### Проверка статуса в Prometheus

После выполнения плейбуков:

1. Откройте веб-интерфейс Prometheus: `http://<monitoring_server_ip>:9090`
2. Перейдите в **Status → Targets**
3. Найдите эндпоинт `postgres_exporter` (например, `192.168.55.10:9187`) со статусом **UP**

### Ключевые метрики PostgreSQL

| Метрика | Описание |
|---|---|
| `pg_up` | Статус подключения к PostgreSQL (1 = успешно) |
| `pg_stat_activity_count` | Количество активных соединений |
| `pg_stat_database_tps` | Транзакций в секунду |
| `pg_stat_database_blks_hit` | Попаданий в кэш буферов |
| `pg_locks_count` | Количество блокировок |

### Установка PostgreSQL

Подробное руководство по установке и настройке PostgreSQL — в [example_postgresql_setup.md](example_postgresql_setup.md).

### Экспортеры Prometheus

Обзор всех доступных экспортеров — в [Prometheus/Exporters/overview.md](../../Prometheus/Exporters/overview.md).
