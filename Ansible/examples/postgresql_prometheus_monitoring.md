# Мониторинг PostgreSQL с помощью Prometheus и Ansible

## Определения

**Мониторинг PostgreSQL** — комплексный процесс сбора, хранения и визуализации метрик производительности СУБД для обеспечения стабильности и быстродействия системы. Включает: доступность (`pg_up`), производительность запросов (`pg_stat_statements`), состояние соединений (`pg_stat_activity`), размер данных, replication lag и дисковый I/O.

**postgres_exporter** — специализированный сервис мониторинга PostgreSQL для Prometheus. В 2026 году актуальной является версия **v0.20.1+**, поддерживающая PostgreSQL 16–18. Слушает на порту **9187/TCP**. Подробное описание и параметры порта приведены в **[Каталоге экспортеров](../../Prometheus/Exporters/other_exporters.md#1-базы-данных-databases)**.

**Prometheus** — автономная система мониторинга (CNCF), собирающая метрики методом скрапинга (pull) по HTTP. Хранит данные во временны́х рядах (TSDB), позволяет выполнять запросы на PromQL и генерировать алерты через Alertmanager. Актуальная версия — **v3.x**. Подробнее: [Обзор Prometheus](../../Prometheus/overview.md).

**Grafana** — платформа визуализации данных, подключающаяся к Prometheus (и другим источникам) для построения дашбордов. Предоставляет готовые шаблоны для PostgreSQL (Dashboard ID **9628**, **12485**). Подробнее: [Обзор Grafana](../../Grafana/grafana_overview.md).

**Alertmanager** — компонент стека Prometheus, отвечающий за обработку, группировку, дедупликацию и доставку алертов в каналы уведомлений (Email, Slack, Telegram, PagerDuty). Подробнее: [Alertmanager](../../Prometheus/alertmanager.md).

**PromQL (Prometheus Query Language)** — язык запросов для временных рядов Prometheus. Используется в правилах алертинга и дашбордах. Пример: `rate(pg_stat_database_xact_rollback[5m]) > 10`.

**Scrape (Скрапинг)** — метод сбора данных, при котором Prometheus периодически опрашивает HTTP-эндпоинты (`/metrics`) целевых сервисов. Интервал по умолчанию — 15 секунд, настраивается через `scrape_interval` в `prometheus.yml`.

**Target (Цель скрапинга)** — объект, с которого Prometheus собирает метрики. Каждый target определяется адресом (`host:port`) и метками (`job`, `instance`). Для postgres_exporter target: `db-master:9187`.

**Full-Stack Observability** — подход, при котором мониторинг БД является частью общей системы наблюдаемости инфраструктуры, включающей метрики ОС, сетевого уровня и приложения. Подробнее см. в разделе **[Наблюдаемость PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md)**.

**pg_stat_statements** — расширение PostgreSQL (включается через `shared_preload_libraries`), отслеживающее статистику выполнения SQL-запросов: количество вызовов, общее время, время I/O, количество возвращенных строк. Обязательно для поиска "тяжелых" запросов. Подробнее: [Расширения PostgreSQL](../../Databases/PostgreSQL/Concepts/extensions_utility.md).

**pg_monitor** — встроенная роль PostgreSQL, предоставляющая права на чтение системных представлений (`pg_stat_activity`, `pg_stat_replication`, `pg_stat_statements` и др.). Экспортер должен быть членом этой роли. Подробнее: [Наблюдаемость PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md).

**pg_hba.conf** — файл конфигурации аутентификации PostgreSQL, определяющий, какие клиенты могут подключаться, откуда и каким методом аутентификации. Для экспортера необходимо разрешить подключение с адреса Prometheus/экспортера.

**SSL/TLS DSN** — строка подключения (Data Source Name) с параметрами шифрования: `sslmode=verify-full&sslrootcert=/path/to/ca.crt`. Обязательна для production-окружений для шифрования трафика между экспортером и PostgreSQL.

**Scrape Config (scrape_configs)** — секция конфигурации Prometheus (`prometheus.yml`), определяющая какие цели опрашивать, с какой частотой, какие метки добавлять. Пример для postgres_exporter:

```yaml
scrape_configs:
  - job_name: 'postgres'
    static_configs:
      - targets: ['db-master:9187']
```

## Базовые концепции

### Архитектура стека мониторинга

Для полноценного наблюдения за базой данных используется классический стек:

| Компонент | Назначение | Основная ссылка |
|---|---|---|
| **PostgreSQL** | Объект мониторинга (источник метрик через `pg_stat_*`). | [PostgreSQL](../../Databases/PostgreSQL/overview.md) |
| **postgres_exporter** | Агент сбора метрик, преобразующий `pg_stat_*` в формат Prometheus (порт 9187/TCP). | [Каталог экспортеров](../../Prometheus/Exporters/other_exporters.md#1-базы-данных-databases) |
| **Prometheus** | Сбор (scrape) и хранение метрик в TSDB, выполнение PromQL-запросов. | [Обзор Prometheus](../../Prometheus/overview.md) |
| **Alertmanager** | Обработка и доставка алертов (Email, Slack, Telegram, PagerDuty). | [Alertmanager](../../Prometheus/alertmanager.md) |
| **Grafana** | Визуализация данных (дашборды, графики, таблицы). | [Обзор Grafana](../../Grafana/grafana_overview.md) |

### Механизм скрапинга (Pull-модель)

Prometheus использует pull-модель: сервер **сам** опрашивает HTTP-эндпоинты целей по расписанию:

```
Prometheus --[HTTP GET :9187/metrics]--> postgres_exporter --[SQL]--> PostgreSQL
         <--[Prometheus format]-------<-- [pg_stat_*] <------------<--
```

Ключевые параметры скрапинга в `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s     # Интервал по умолчанию
  evaluation_interval: 15s # Интервал вычисления правил алертинга

scrape_configs:
  - job_name: 'postgres'
    scrape_interval: 10s   # Уменьшенный интервал для БД (важные метрики)
    static_configs:
      - targets: ['db-master:9187']
        labels:
          environment: 'production'
          cluster: 'main'
```

| Параметр | Описание | Рекомендация |
|---|---|---|
| `scrape_interval` | Интервал опроса целей | 10–15с для PostgreSQL |
| `evaluation_interval` | Интервал вычисления alert rules | 15–30с |
| `static_configs` | Статический список целей | Для небольших кластеров |
| `file_sd_configs` | Цели из JSON/YAML-файлов | Динамические инфраструктуры |
| `relabel_configs` | Трансформация меток | Фильтрация, добавление меток |

### Ключевые метрики PostgreSQL (postgres_exporter)

Подробное описание метрик, нормальные значения и принципы сбора приведены в **[Наблюдаемость PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md)**.

Минимальный набор для дашборда:

| Метрика | Назначение | Нормальное значение | Тип |
|---|---|---|---|
| `pg_up` | Доступность БД (1 = доступна) | `1` | Gauge |
| `pg_stat_database_xact_commit` | Количество зафиксированных транзакций | Зависит от нагрузки | Counter |
| `pg_stat_database_xact_rollback` | Количество откатов транзакций | Должно быть << commit | Counter |
| `pg_stat_activity_count` | Количество текущих сессий | Зависит от `max_connections` | Gauge |
| `pg_database_size_bytes` | Размер БД на диске | Постепенный рост | Gauge |
| `pg_stat_database_deadlocks` | Количество deadlock'ов за период | `0` | Counter |
| `pg_stat_replication_lag` | Задержка репликации (сек) | `< 1с` для синхронной | Gauge |

### Настройка pg_hba.conf для экспортера

PostgreSQL требует явного разрешения подключения для пользователя мониторинга:

```ini
# TYPE  DATABASE        USER            ADDRESS                 METHOD
# Экспортер: чтение системных таблиц
host    all             postgres_exporter  127.0.0.1/32        scram-sha-256
host    all             postgres_exporter  192.168.55.0/24     scram-sha-256
```

После изменения `pg_hba.conf` требуется перезагрузка конфигурации:

```bash
sudo -u postgres psql -c "SELECT pg_reload_conf();"
# → Результат: OK
```

### SSL/TLS для соединения экспортера с PostgreSQL

В production-окружениях рекомендуется шифрование трафика. Полную конфигурацию SSL для PostgreSQL см. в **[Развертывание PostgreSQL через Ansible](./example_postgresql_setup.md#ssl-tls)**.

### Мониторинг репликации

Для кластеров PostgreSQL с репликацией отслеживание `Replication Lag` критично:

```yaml
# Пример метрики для алерта
- alert: PostgresReplicationLag
  expr: pg_stat_replication_lag > 30
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Replication lag > 30s on {{ $labels.instance }}"
```

### Используемые роли и коллекции

Для автоматизации развертывания в 2026 году рекомендуется использовать следующие коллекции:

- **`community.postgresql` (v4.2.0+)**: Управление базой данных, расширениями (например, `pg_stat_statements`) и пользователями мониторинга.
- **`prometheus.prometheus` (v0.30.2+)**: Установка и настройка `postgres_exporter`, а также развертывание сервера Prometheus 3.x.
- **`community.grafana` (v2.0.0+)**: Управление дашбордами Grafana через provisioning API.

Установка зависимостей на контрольном узле:

```bash
ansible-galaxy collection install community.postgresql
ansible-galaxy collection install prometheus.prometheus:>=0.30.2
ansible-galaxy collection install community.grafana:>=2.0.0
# → Starting galaxy collection install process
# → Process install dependency map
```

### Безопасность и секреты

Для подключения экспортера требуется специальный пользователь в PostgreSQL с правами `pg_monitor`. Пароли и строки подключения (DSN) необходимо шифровать с помощью **[Ansible Vault](../Vault/basics.md)**.

В производственных средах обязательно использование **SSL** в DSN (`sslmode=verify-full`) с указанием корневого сертификата.

Пример безопасного хранения DSN:

```yaml
# group_vars/postgres_hosts/vault.yml (зашифровано через ansible-vault)
vault_db_pass: "{{ vault_db_pass }}"
vault_exporter_dsn: "postgresql://postgres_exporter:{{ vault_db_pass }}@localhost:5432/postgres?sslmode=verify-full"
```

## Практические сценарии

### Сценарий 1: Подготовка базы данных (pg_stat_statements)

Для полноценного мониторинга запросов **обязательно** включение расширения `pg_stat_statements`. Подробные параметры конфигурации и нюансы работы приведены в **[Расширения PostgreSQL](../../Databases/PostgreSQL/Concepts/extensions_utility.md#pg_stat_statements-золотой-стандарт)**.

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
    postgres_exporter_dsn: "postgresql://{{ exporter_user }}:{{ vault_db_pass }}@localhost:5432/postgres?sslmode=verify-full"

  tasks:
    - name: Создание пользователя для мониторинга
      community.postgresql.postgresql_user:
        name: "{{ exporter_user }}"
        password: "{{ vault_db_pass }}"
        role_attr_flags: "LOGIN"
        groups: "pg_monitor"
      become_user: postgres
      no_log: true

  roles:
    - role: prometheus.prometheus.postgres_exporter
      vars:
        postgres_exporter_version: "0.20.1"
        postgres_exporter_dsn: "{{ postgres_exporter_dsn }}"
        postgres_exporter_config_flags:
          auto-discover-databases: true
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

**Расширенный набор правил `templates/postgresql_alerts.yml.j2`:**

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
          description: "PostgreSQL не отвечает на запросы более 2 минут."

      - alert: PostgresHighTransactionRollback
        expr: rate(pg_stat_database_xact_rollback[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень откатов транзакций на {{ $labels.instance }}"

      - alert: PostgresTooManyConnections
        expr: pg_stat_activity_count > (pg_settings_max_connections * 0.8)
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Использование соединений > 80% на {{ $labels.instance }}"

      - alert: PostgresDeadlocks
        expr: increase(pg_stat_database_deadlocks[5m]) > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Обнаружен deadlock на {{ $labels.instance }}: {{ $value }}"

      - alert: PostgresReplicationLag
        expr: pg_stat_replication_lag > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Replication lag > 30s на {{ $labels.instance }}"

      - alert: PostgresDatabaseSizeGrowing
        expr: predict_linear(pg_database_size_bytes[1h], 3600 * 24 * 7) > 107374182400
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Прогноз: размер БД {{ $labels.datname }} превысит 100GB через 7 дней"

      - alert: PostgresLongRunningTransaction
        expr: pg_stat_activity_max_tx_duration{state="active"} > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Длительная транзакция > 5 мин на {{ $labels.instance }}"
```

**Подключение правил в Prometheus (`templates/prometheus.yml.j2`):**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "/etc/prometheus/rules/*.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']

scrape_configs:
  - job_name: 'postgres'
    scrape_interval: 10s
    static_configs:
      - targets: ['{{ groups["postgres_hosts"] | map("extract", "hostvars", "ansible_host") | map("regex_replace", "$", ":9187") | list }}']
        labels:
          environment: '{{ env }}'
```

### Сценарий 5: Полный плейбук (весь стек мониторинга)

Комплексный сценарий развертывания всего стека: postgres_exporter + Prometheus + Grafana + Alertmanager + правила + дашборды.

#### 1. Структура проекта

```text
monitoring-stack/
├── inventory/
│   └── hosts.yml
├── group_vars/
│   ├── all/
│   │   └── vars.yml
│   ├── postgres_hosts/
│   │   └── vault.yml          # зашифровано
│   └── monitoring_hosts/
│       └── vault.yml          # зашифровано
├── templates/
│   ├── prometheus.yml.j2
│   ├── postgresql_alerts.yml.j2
│   ├── grafana_datasource.yml.j2
│   └── grafana_dashboard.yml.j2
├── files/
│   └── dashboards/
│       └── postgres_overview.json
└── playbooks/
    ├── site.yml
    ├── postgres_exporter.yml
    ├── prometheus.yml
    └── grafana.yml
```

#### 2. Инвентарь (`inventory/hosts.yml`)

```yaml
---
all:
  children:
    postgres_hosts:
      hosts:
        db-master:
          ansible_host: 192.168.55.10
        db-replica:
          ansible_host: 192.168.55.11
    monitoring_hosts:
      hosts:
        monitoring-01:
          ansible_host: 192.168.55.20
```

#### 3. Общие переменные (`group_vars/all/vars.yml`)

```yaml
---
# Общие настройки
env: "production"
postgresql_version: "16"
exporter_user: "postgres_exporter"
exporter_port: 9187

# Prometheus
prometheus_version: "3.0.0"
prometheus_retention: "30d"
prometheus_scrape_interval: "15s"

# Grafana
grafana_version: "11.0.0"
grafana_admin_password: "{{ vault_grafana_admin_password }}"

# Пути
postgres_data_dir: "/var/lib/postgresql/{{ postgresql_version }}/main"
```

#### 4. Плейбук настройки экспортера на PostgreSQL-сервере (`playbooks/postgres_exporter.yml`)

```yaml
---
- name: Setup PostgreSQL Exporter
  hosts: postgres_hosts
  become: true
  vars:
    exporter_user: "postgres_exporter"
    postgres_exporter_dsn: "postgresql://{{ exporter_user }}:{{ vault_db_pass }}@localhost:5432/postgres?sslmode=verify-full"

  tasks:
    - name: Ensure pg_stat_statements is in shared_preload_libraries
      ansible.builtin.lineinfile:
        path: "{{ postgres_data_dir }}/postgresql.conf"
        regexp: "^#?shared_preload_libraries"
        line: "shared_preload_libraries = 'pg_stat_statements'"
      notify: Restart PostgreSQL

    - name: Create monitoring user
      community.postgresql.postgresql_user:
        name: "{{ exporter_user }}"
        password: "{{ vault_db_pass }}"
        role_attr_flags: "LOGIN"
        groups: "pg_monitor"
      become_user: postgres
      no_log: true

    - name: Allow exporter connection from localhost
      ansible.builtin.lineinfile:
        path: "{{ postgres_data_dir }}/pg_hba.conf"
        regexp: "^host.*{{ exporter_user }}.*127\\.0\\.0\\.1"
        line: "host all {{ exporter_user }} 127.0.0.1/32 scram-sha-256"
      notify: Reload PostgreSQL

    - name: Deploy postgres_exporter
      ansible.builtin.include_role:
        name: prometheus.prometheus.postgres_exporter
      vars:
        postgres_exporter_version: "0.20.1"
        postgres_exporter_dsn: "{{ postgres_exporter_dsn }}"
        postgres_exporter_config_flags:
          auto-discover-databases: true
          collector.stat_statements: true

    - name: Verify exporter is running
      ansible.builtin.uri:
        url: "http://localhost:{{ exporter_port }}/metrics"
        return_content: yes
      register: exporter_status
      until: "'pg_up' in exporter_status.content"
      retries: 10
      delay: 5

    - name: Show pg_up metric
      ansible.builtin.debug:
        msg: "PostgreSQL Exporter OK — pg_up detected"

  handlers:
    - name: Restart PostgreSQL
      ansible.builtin.service:
        name: "postgresql"
        state: restarted

    - name: Reload PostgreSQL
      ansible.builtin.service:
        name: "postgresql"
        state: reloaded
```

#### 5. Плейбук настройки Prometheus (`playbooks/prometheus.yml`)

```yaml
---
- name: Setup Prometheus Server
  hosts: monitoring_hosts
  become: true
  vars:
    prometheus_version: "3.0.0"
    prometheus_retention: "30d"

  tasks:
    - name: Install dependencies
      ansible.builtin.package:
        name:
          - wget
          - tar
        state: present

    - name: Create prometheus user
      ansible.builtin.user:
        name: prometheus
        shell: /bin/false
        system: yes

    - name: Download and install Prometheus
      ansible.builtin.unarchive:
        src: "https://github.com/prometheus/prometheus/releases/download/v{{ prometheus_version }}/prometheus-{{ prometheus_version }}.linux-amd64.tar.gz"
        dest: /opt/
        remote_src: yes
        creates: "/opt/prometheus-{{ prometheus_version }}.linux-amd64/prometheus"

    - name: Create symlinks
      ansible.builtin.file:
        src: "/opt/prometheus-{{ prometheus_version }}.linux-amd64/{{ item }}"
        dest: "/usr/local/bin/{{ item }}"
        state: link
      loop:
        - prometheus
        - promtool

    - name: Create directories
      ansible.builtin.file:
        path: "{{ item }}"
        state: directory
        owner: prometheus
        group: prometheus
        mode: '0755'
      loop:
        - /etc/prometheus
        - /etc/prometheus/rules
        - /var/lib/prometheus

    - name: Deploy prometheus.yml
      ansible.builtin.template:
        src: templates/prometheus.yml.j2
        dest: /etc/prometheus/prometheus.yml
        owner: prometheus
        group: prometheus
        mode: '0644'
      notify: Reload Prometheus

    - name: Deploy alert rules
      ansible.builtin.template:
        src: templates/postgresql_alerts.yml.j2
        dest: /etc/prometheus/rules/postgresql_alerts.yml
        owner: prometheus
        group: prometheus
        mode: '0644'
      notify: Reload Prometheus

    - name: Deploy systemd unit
      ansible.builtin.template:
        src: templates/prometheus.service.j2
        dest: /etc/systemd/system/prometheus.service
      notify:
        - Reload systemd
        - Restart Prometheus

    - name: Start and enable Prometheus
      ansible.builtin.service:
        name: prometheus
        state: started
        enabled: yes

  handlers:
    - name: Reload systemd
      ansible.builtin.systemd:
        daemon_reload: yes

    - name: Restart Prometheus
      ansible.builtin.service:
        name: prometheus
        state: restarted

    - name: Reload Prometheus
      ansible.builtin.uri:
        url: "http://localhost:9090/-/reload"
        method: POST
```

**Шаблон Prometheus (`templates/prometheus.yml.j2`):**

```yaml
global:
  scrape_interval: {{ prometheus_scrape_interval }}
  evaluation_interval: 15s

rule_files:
  - "/etc/prometheus/rules/*.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'postgres'
    scrape_interval: 10s
    static_configs:
      - targets:
{% for host in groups['postgres_hosts'] %}
          - '{{ hostvars[host]["ansible_host"] }}:{{ exporter_port }}'
{% endfor %}
        labels:
          environment: '{{ env }}'
```

**Шаблон systemd (`templates/prometheus.service.j2`):**

```ini
[Unit]
Description=Prometheus
After=network.target

[Service]
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus \
    --storage.tsdb.retention.time={{ prometheus_retention }} \
    --web.enable-lifecycle
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

#### 6. Плейбук настройки Grafana (`playbooks/grafana.yml`)

```yaml
---
- name: Setup Grafana
  hosts: monitoring_hosts
  become: true
  vars:
    grafana_version: "11.0.0"

  tasks:
    - name: Add Grafana GPG key
      ansible.builtin.get_url:
        url: "https://apt.grafana.com/gpg.key"
        dest: /usr/share/keyrings/grafana.asc

    - name: Add Grafana repository
      ansible.builtin.apt_repository:
        repo: "deb [signed-by=/usr/share/keyrings/grafana.asc] https://apt.grafana.com stable main"
        state: present

    - name: Install Grafana
      ansible.builtin.package:
        name: "grafana={{ grafana_version }}*"
        state: present
      notify: Restart Grafana

    - name: Deploy Prometheus datasource
      ansible.builtin.template:
        src: templates/grafana_datasource.yml.j2
        dest: /etc/grafana/provisioning/datasources/prometheus.yml
        owner: grafana
        group: grafana
        mode: '0640'
      notify: Restart Grafana

    - name: Deploy PostgreSQL dashboard provider
      ansible.builtin.template:
        src: templates/grafana_dashboard.yml.j2
        dest: /etc/grafana/provisioning/dashboards/default.yml
        owner: grafana
        group: grafana
        mode: '0640'
      notify: Restart Grafana

    - name: Create dashboard directory
      ansible.builtin.file:
        path: /var/lib/grafana/dashboards
        state: directory
        owner: grafana
        group: grafana
        mode: '0755'

    - name: Copy PostgreSQL dashboard
      ansible.builtin.copy:
        src: files/dashboards/postgres_overview.json
        dest: /var/lib/grafana/dashboards/postgres_overview.json
        owner: grafana
        group: grafana
        mode: '0644'
      notify: Restart Grafana

    - name: Start and enable Grafana
      ansible.builtin.service:
        name: grafana-server
        state: started
        enabled: yes

  handlers:
    - name: Restart Grafana
      ansible.builtin.service:
        name: grafana-server
        state: restarted
```

**Шаблон datasource (`templates/grafana_datasource.yml.j2`):**

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://localhost:9090
    isDefault: true
    editable: false
```

**Шаблон dashboard provider (`templates/grafana_dashboard.yml.j2`):**

```yaml
apiVersion: 1
providers:
  - name: 'default'
    orgId: 1
    folder: 'PostgreSQL'
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

#### 7. Корневой плейбук (`playbooks/site.yml`)

```yaml
---
# Полный стек мониторинга PostgreSQL
- import_playbook: postgres_exporter.yml
- import_playbook: prometheus.yml
- import_playbook: grafana.yml
```

#### 8. Верификация и отладка

```bash
# Запуск всего стека
ansible-playbook -i inventory/hosts.yml playbooks/site.yml

# Проверка postgres_exporter
curl -s http://192.168.55.10:9187/metrics | grep pg_up
# → pg_up 1

# Проверка Prometheus targets
curl -s http://192.168.55.20:9090/api/v1/targets | python3 -m json.tool | grep -A5 '"job"'
# → "job": "postgres", "health": "up"

# Проверка правил алертинга
curl -s http://192.168.55.20:9090/api/v1/rules | python3 -m json.tool | grep '"name"'
# → "name": "PostgresDown", "name": "PostgresHighTransactionRollback", ...

# Проверка Grafana
curl -s http://192.168.55.20:3000/api/health
# → {"commit":"xxx","database":"ok","version":"11.0.0"}

# Проверка datasource в Grafana
curl -s -u admin:{{ vault_grafana_admin_password }} http://192.168.55.20:3000/api/datasources
# → [{"id":1,"name":"Prometheus","type":"prometheus","url":"http://localhost:9090",...}]
```

## Операции и команды

### Основные команды управления плейбуками

| Команда | Описание | Пример |
|---|---|---|
| `ansible-playbook` | Запуск плейбука | `ansible-playbook -i inventory/hosts.yml playbooks/site.yml` |
| `--check --diff` | Dry-run с показом изменений | `ansible-playbook ... --check --diff` |
| `--limit` | Ограничение хостов | `ansible-playbook ... --limit db-master` |
| `--syntax-check` | Проверка синтаксиса | `ansible-playbook ... --syntax-check` |

### Команды для управления экспортером

| Команда | Описание | Ожидаемый результат |
|---|---|---|
| `systemctl status postgres_exporter` | Проверка статуса сервиса | `active (running)` |
| `journalctl -u postgres_exporter -f` | Просмотр логов в реальном времени | Лог вывода с информацией о старте |
| `curl -s http://localhost:9187/metrics` | Проверка эндпоинта метрик | `pg_up 1` и другие метрики |

### Команды для управления PostgreSQL

| Команда | Описание | Ожидаемый результат |
|---|---|---|
| `sudo -u postgres psql -c "SELECT pg_reload_conf();"` | Перезагрузка конфигурации | `Result: OK` |
| `sudo -u postgres psql -c "SELECT * FROM pg_extension WHERE extname='pg_stat_statements';"` | Проверка расширения | Строка с `pg_stat_statements` |
| `sudo -u postgres psql -c "SELECT rolname FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname='postgres_exporter');"` | Проверка членства в роли | Строка с `pg_monitor` |

### Команды для управления Prometheus

| Команда | Описание | Ожидаемый результат |
|---|---|---|
| `curl -s http://localhost:9090/api/v1/targets` | Проверка целей скрапинга | JSON с `activeTargets` |
| `curl -s http://localhost:9090/api/v1/rules` | Проверка правил алертинга | JSON с именами правил |
| `curl -s http://localhost:9090/-/reload` | Перезагрузка конфигурации | `OK` или `204` |

### Команды для управления Grafana

| Команда | Описание | Ожидаемый результат |
|---|---|---|
| `curl -s http://localhost:3000/api/health` | Проверка здоровья | `{"database":"ok","version":"11.0.0"}` |
| `curl -s http://localhost:3000/api/datasources` | Проверка источников данных | JSON с списком datasources |
| `curl -s http://localhost:3000/api/dashboards` | Проверка дашбордов | JSON со списком дашбордов |

### Команды для валидации развертывания

| Команда | Описание | Ожидаемый результат |
|---|---|---|
| `ansible-playbook ... --syntax-check` | Проверка синтаксиса плейбука | `playbook: Playbook Validation` |
| `ansible-playbook ... --check --diff` | Dry-run | Изменения без применения |
| `curl -s http://host:9187/metrics \| grep "^pg_"` | Проверка метрик PostgreSQL | `pg_up 1`, `pg_stat_database_xact_commit_total` |
| `curl -s http://host:9090/api/v1/alerts` | Проверка активных алертов | JSON с `active_alerts` |

## Устранение типичных неполадок

### Проблема: `pg_up = 0` или экспортер недоступен

**Причина:** PostgreSQL не запущен, DSN неверен, или postgres_exporter не запущен.

**Диагностика:**
```bash
systemctl status postgresql
systemctl status postgres_exporter
curl -s http://localhost:9187/metrics | grep pg_up
```

**Решение:**
- Проверить DSN (хост, порт, пароль, SSL-параметры)
- Запустить PostgreSQL: `systemctl start postgresql`
- Проверить логи: `journalctl -u postgres_exporter -f`

### Проблема: `connection refused` (порт 9187)

**Причина:** postgres_exporter не запущен или порт заблокирован firewall.

**Диагностика:**
```bash
ss -tlnp | grep 9187
systemctl status postgres_exporter
```

**Решение:**
- Запустить экспортер: `systemctl start postgres_exporter`
- Открыть порт в firewall
- Проверить конфигурацию systemd

### Проблема: `no pg_hba.conf entry for host`

**Причина:** IP адрес Prometheus/экспортера не разрешен в `pg_hba.conf`.

**Диагностика:**
```bash
grep postgres_exporter /etc/postgresql/*/main/pg_hba.conf
```

**Решение:**
Добавить разрешающую строку в `pg_hba.conf`:
```ini
host all postgres_exporter 192.168.55.0/24 scram-sha-256
```
Выполнить перезагрузку:
```bash
sudo -u postgres psql -c "SELECT pg_reload_conf();"
# → Результат: OK
```

### Проблема: `pg_stat_statements` пуст

**Причина:** Расширение не создано в БД или `shared_preload_libraries` не содержит `pg_stat_statements`.

**Диагностика:**
```bash
sudo -u postgres psql -c "SELECT * FROM pg_extension WHERE extname='pg_stat_statements';"
sudo -u postgres psql -c "SHOW shared_preload_libraries;"
```

**Решение:**
```bash
# Добавить в postgresql.conf
shared_preload_libraries = 'pg_stat_statements'
# Перезапустить PostgreSQL
sudo systemctl restart postgresql
# Создать расширение в каждой БД
sudo -u postgres psql -c "CREATE EXTENSION pg_stat_statements;"
```

### Проблема: `permission denied for table`

**Причина:** Пользователь экспортера не добавлен в роль `pg_monitor`.

**Диагностика:**
```bash
sudo -u postgres psql -c "SELECT rolname FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname='postgres_exporter');"
```

**Решение:**
```bash
sudo -u postgres psql -c "GRANT pg_monitor TO postgres_exporter;"
```

### Проблема: Prometheus target `DOWN`

**Причина:** Экспортер недоступен по сети, порт заблокирован, или DSN неверен.

**Диагностика:**
```bash
curl -s http://host:9187/metrics
curl -s http://localhost:9090/api/v1/targets | python3 -m json.tool
```

**Решение:**
- Проверить firewall и доступность порта 9187
- Проверить DSN экспортера
- Проверить статус PostgreSQL

### Проблема: Высокий CPU от экспортера

**Причина:** Слишком частый scrape или большое количество БД.

**Диагностика:**
```bash
top -p $(pgrep postgres_exporter)
```

**Решение:**
- Увеличить `scrape_interval` до 30s
- Ограничить количество опрашиваемых БД через `--collectdatabases`
- Настроить `--max-requests=1000`

### Проблема: Дублирующиеся алерты в HA-кластере Prometheus

**Причина:** Отсутствуют `external_labels` у реплик Prometheus.

**Диагностика:**
```bash
curl -s http://localhost:9090/api/v1/alerts | python3 -m json.tool
```

**Решение:**
Добавить в `prometheus.yml`:
```yaml
global:
  external_labels:
    replica: '{{ inventory_hostname }}'
```

### Проблема: Grafana `No data`

**Причина:** Datasource неверен или Prometheus недоступен.

**Диагностика:**
```bash
curl -s http://localhost:3000/api/datasources
curl -s http://localhost:9090/api/v1/query?query=pg_up
```

**Решение:**
- Исправить URL Prometheus в provisioning
- Проверить доступность Prometheus из сети Grafana

## Рекомендации

### Best Practices

1. **pg_stat_statements обязателен**: Всегда включайте расширение в `shared_preload_libraries` до начала сбора метрик. Без него экспортер не собирает метрики производительности запросов.
2. **Изоляция пользователя мониторинга**: Создайте отдельного пользователя (`postgres_exporter`) с минимальными привилегиями (только `pg_monitor`). Не используйте `postgres` для экспортера.
3. **SSL в production**: Используйте `sslmode=verify-full` с клиентскими сертификатами для шифрования трафика между экспортером и PostgreSQL.
4. **Раздельный scrape_interval**: Для PostgreSQL используйте `10s` вместо стандартных `15s` Prometheus — метрики БД критичны для быстрой диагностики.
5. **Ansible Vault**: Все пароли и DSN хранятся зашифрованными. Никогда не храните секреты в plain text в `group_vars`.
6. **auto-discover-databases**: Включайте только если количество БД < 50. При большем количестве БД используйте `--collectdatabases` для явного перечисления.
7. **max-requests для экспортера**: Настройте `--max-requests=1000` для periodic restart и предотвращения утечек памяти.
8. **Версионирование дашбордов**: Храните JSON-файлы дашбордов в Git и provision через Ansible, а не создавайте вручную в UI.
9. **Группировка алертов**: В Alertmanager настройте `group_by: ['alertname', 'instance']` для предотвращения спама.
10. **Retention policy**: Настройте `--storage.tsdb.retention.time` в Prometheus в соответствии с потребностями (30 дней — стандарт).

### Безопасность

1. **no_log для чувствительных задач**: Используйте `no_log: true` для задач, работающих с паролями, DSN и секретами. Это предотвращает утечку данных в логи Ansible.
2. **Минимизация прав пользователя экспортера**: Пользователь `postgres_exporter` должен иметь только роль `pg_monitor`. Запретите ему создание баз и изменение данных.
3. **Сетевой доступ**: Разрешите подключение к порту 9187 только с адресов Prometheus-сервера через firewall.
4. **Шифрование DSN**: Всегда используйте `sslmode=verify-full` в production. Никогда не используйте `sslmode=disable` на production-хостах.
5. **Хранение секретов**: Используйте Ansible Vault с Vault ID для разделения секретов по средам (dev/staging/prod). Подробнее: [Рекомендации по безопасности Ansible](../ansible_security_best_practices.md).

### Производительность и стабильность

1. **Оптимизация scrape_interval**: 10s для PostgreSQL, 15s для стандартных метрик.
2. **Ограничение кардинальности**: Используйте `pg_stat_statements.track = top` вместо `all` при высокой нагрузке.
3. **Мониторинг самого экспортера**: Добавьте метрики процесса (CPU, RAM) через `process_exporter`.
4. **WAL Management**: Убедитесь, что `pg_stat_replication` не растет бесконечно — настройте `wal_keep_size`.

### Граничные случаи и ограничения

1. **PostgreSQL < 14**: `compute_query_id` отсутствует, `pg_stat_statements` может показывать неполные данные. Рекомендуется обновление до PG 14+.
2. **Высокая кардинальность меток**: Если в `pg_stat_statements` hundreds уникальных `queryid`, это может привести к высокому потреблению памяти Prometheus. Используйте `pg_stat_statements.track = top` вместо `all`.
3. **Реплики PostgreSQL**: На репликах `pg_stat_statements` может не собирать статистику (зависит от `pg_stat_statements.track`). Настройте `track = all` на репликах для полного набора данных.
4. **Кластер Prometheus (HA)**: При использовании двух реплик Prometheus и одного Alertmanager необходима настройка `external_labels` для дедупликации алертов.
5. **Высокая нагрузка экспортера**: При мониторинге кластера с >100 БД экспортер может потребовать >1GB RAM. Ограничьте количество опрашиваемых БД.
6. **Firewall**: Убедитесь, что порт 9187 доступен для Prometheus, а порт 9090 — для Grafana. Фильтрация по IP в `pg_hba.conf` не заменяет firewall.
7. **Windows-хосты**: postgres_exporter доступен для Windows, но Ansible-плейбуки в примерах используют Linux-специфичные модули.

### Тестирование конфигурации перед production

```bash
# 1. Syntax check плейбука
ansible-playbook playbooks/site.yml --syntax-check

# 2. Dry run
ansible-playbook playbooks/site.yml --check --diff

# 3. Запуск на конкретном хосте
ansible-playbook playbooks/site.yml --limit db-master

# 4. Проверка метрик
curl -s http://localhost:9187/metrics | grep "^pg_"
# → pg_up 1
# → pg_stat_database_xact_commit_total{datname="postgres"} 12345

# 5. Проверка Prometheus targets
curl -s http://localhost:9090/api/v1/targets | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['data']['activeTargets'], indent=2))"

# 6. Проверка алертов
curl -s http://localhost:9090/api/v1/alerts | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Active alerts: {len(d[\"data\"][\"alerts\"])}')"

# 7. Проверка Grafana datasource
curl -s -u admin:{{ vault_grafana_admin_password }} http://localhost:3000/api/datasources | python3 -m json.tool
```

## Дополнительная информация

### Расширенный набор PromQL-запросов для дашбордов

```promql
# Доступность БД
pg_up

# Транзакции в секунду
rate(pg_stat_database_xact_commit[5m])

# Откаты в секунду
rate(pg_stat_database_xact_rollback[5m])

# Количество активных сессий
pg_stat_activity_count

# Использование соединений (в процентах)
(pg_stat_activity_count / pg_settings_max_connections) * 100

# Размер БД (в GB)
pg_database_size_bytes / 1073741824

# Deadlocks за 5 минут
increase(pg_stat_database_deadlocks[5m])

# Top-5 запросов по времени выполнения
topk(5, pg_stat_statements_total_time / pg_stat_statements_calls)

# Replication lag (в секундах)
pg_stat_replication_lag

# Размер WAL (в MB)
pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) / 1048576
```

### Визуализация в Grafana

Рекомендуемые дашборды:
- **PostgreSQL Database** (ID: **9628**) — стандарт де-факто.
- **PostgreSQL Overview (by Pigsty)** (ID: **12485**) — более современная визуализация для 2026 года.

**Provisioning дашборда через Ansible:**

```yaml
- name: Import Grafana dashboard via API
  community.grafana.grafana_dashboard:
    grafana_url: "http://localhost:3000"
    grafana_user: admin
    grafana_password: "{{ grafana_admin_password }}"
    state: present
    overwrite: yes
    dashboard_id: 9628
    folder: "PostgreSQL"
    no_log: true
    # → Импортирует готовый дашборд с Grafana.com
```

### Смотрите также

- **[Наблюдаемость PostgreSQL](../../Databases/PostgreSQL/Operations/observability.md)** — теория наблюдаемости, wait events, расширенные метрики.
- **[Каталог экспортеров Prometheus](../../Prometheus/Exporters/other_exporters.md#1-базы-данных-databases)** — обзор postgres_exporter и паттернов развертывания.
- **[Развертывание PostgreSQL через Ansible](./example_postgresql_setup.md)** — установка и настройка PostgreSQL, включая pg_stat_statements и SSL.
