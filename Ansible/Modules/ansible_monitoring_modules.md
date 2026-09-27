# Ansible: Модули управления мониторингом и observability

## Определения

**Модули управления мониторингом** — группа декларативных инструментов Ansible из коллекций `community.zabbix`, `datadog.dd`, `netways.icinga`, `prometheus.prometheus`, `community.grafana` и др., предназначенных для автоматизации развертывания агентов, управления конфигурациями, создания хостов, сервисов, правил оповещения и дашбордов в системах мониторинга.

**Observability** — практика сбора, обработки и анализа метрик, логов и трейсов для понимания состояния системы. Ansible-модули автоматизируют развертывание стеков observability (Prometheus, Grafana, exporters) и агентов сбора данных.

**Alert (Зов)** — уведомление о проблеме в monitored-системе. Ansible-модули позволяют создавать и управлять правилами генерации алертов через API систем мониторинга.

**Service Check** — проверка доступности сервиса (HTTP, TCP, ICMP, DNS). Ansible-модули автоматизируют создание и обновление проверок в Zabbix, Icinga, Datadog.

**Exporter** — агент сбора метрик в формате Prometheus text exposition format. Ansible-модули автоматизируют развертывание экспортеров (node_exporter, postgres_exporter, blackbox_exporter).

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21.4+ |
| **community.zabbix** | 2.0+ | 4.2.0+ |
| **datadog.dd** | 2.0+ | 5.6.0+ |
| **netways.icinga** | 0.4.0+ | 0.4.7+ |
| **prometheus.prometheus** | 0.27.0+ | 0.30.2+ |
| **community.grafana** | 1.0+ | 2.3.0+ |
| **Python** (target) | 3.9+ | 3.12+ |

**Установка коллекций:**
```bash
ansible-galaxy collection install community.zabbix
ansible-galaxy collection install datadog.dd
ansible-galaxy collection install netways.icinga
ansible-galaxy collection install prometheus.prometheus
ansible-galaxy collection install community.grafana
```

**Проверка окружения:**
```bash
ansible-doc -l community.zabbix | head -20
ansible-doc -l datadog.dd | head -20
ansible-doc -l netways.icinga | head -20
ansible-doc -l prometheus.prometheus | head -20
ansible-doc -l community.grafana | head -20
```

## Архитектура и принципы работы

### Жизненный цикл модуля мониторинга

1. **Планирование**: Ansible определяет целевые хосты и нужные модули на основе inventory и плейбука.
2. **Сбор фактов**: Модули получают текущее состояние объектов мониторинга через API (Zabbix API, Icinga 2 API, Datadog API, Prometheus HTTP API).
3. **Сравнение**: Desired state из плейбука сравнивается с текущим состоянием.
4. **Применение**: Если расхождения обнаружены — модули отправляют запросы к API для приведения системы к desired state.
5. **Валидация**: После применения проверяется, что объект создан/обновлен корректно.

### Модель идемпотентности

Все модули мониторинга идемпотентны: повторный запуск плейбука не создает дубликаты хостов, сервисов или правил. Модули используют уникальные идентификаторы (host_name, service_name, monitor_id) для определения существующих объектов.

### Привилегированный доступ

Большинство модулей управления мониторингом работают через API и не требуют `become: yes` на целевых хостах. Исключение — развертывание агентов сбора (Zabbix Agent, node_exporter), которое требует root-доступа.

```yaml
- name: "Регистрация хоста в Zabbix"
  community.zabbix.zabbix_host:
    host: "{{ inventory_hostname }}"
    groups:
      - Linux servers
    interfaces:
      - type: agent
        main: 1
        ip: "{{ ansible_host }}"
        dns: "{{ inventory_hostname }}"
        port: "10050"
    templates:
      - Template OS Linux
    state: present
  delegate_to: localhost
  run_once: yes

- name: "Установка Zabbix Agent"
  ansible.builtin.package:
    name: zabbix-agent
    state: present
  become: yes
```

## Основные концепции

### Модули Zabbix

1. **`community.zabbix.zabbix_host`**: Управление хостами в Zabbix. Создание, обновление, удаление. Поддерживает `host`, `interfaces`, `groups`, `templates`, `state`.
2. **`community.zabbix.zabbix_service`**: Управление сервисами Zabbix. Создание сервисов для мониторинга зависимостей.
3. **`community.zabbix.zabbix_template`**: Управление шаблонами. Импорт, экспорт, связывание с хостами.
4. **`community.zabbix.zabbix_action`**: Управление действиями (оповещения, escalation). Создание и обновление правил оповещения.
5. **`community.zabbix.zabbix_trigger`**: Управление триггерами. Создание правил срабатывания.

### Модули Datadog

1. **`datadog.dd.datadog_monitor`**: Управление мониторами Datadog. Создание, обновление, удаление. Поддерживает `name`, `type` (metric, log, integration, etc.), `query`, `message`, `priority`, `state`.
2. **`datadog.dd.datadog_dashboard`**: Управление дашбордами. Создание, обновление, экспорт.
3. **`datadog.dd.datadog_service_check`**: Управление service checks.
4. **`datadog.dd.datadog_host`**: Управление тегами и метаданными хостов.

### Модули Icinga

1. **`netways.icinga.icinga_host`**: Управление хостами в Icinga 2. Создание, обновление, удаление.
2. **`netways.icinga.icinga_service`**: Управление сервисами. Проверки, состояние, параметры.
3. **`netways.icinga.icinga_notification`**: Управление уведомлениями.

### Модули Prometheus

1. **`prometheus.prometheus.prometheus`**: Установка и настройка Prometheus server. Управление конфигом, scraping targets, alerting rules.
2. **`prometheus.prometheus.node_exporter`**: Установка и настройка node_exporter на хосты. Сбор метрик ОС и железа.
3. **`prometheus.prometheus.postgres_exporter`**: Установка postgres_exporter для сбора метрик PostgreSQL.
4. **`prometheus.prometheus.blackbox_exporter`**: Установка blackbox_exporter для probing внешних сервисов (HTTP, TCP, ICMP, DNS).

### Модули Grafana

1. **`community.grafana.grafana_dashboard`**: Управление дашбордами Grafana через provisioning API.
2. **`community.grafana.grafana_data_source`**: Управление источниками данных Grafana (Prometheus, Loki, Tempo, Elasticsearch).

### Паттерны автоматизации мониторинга

1. **Infrastructure as Code для мониторинга**: Все объекты мониторинга (хосты, сервисы, триггеры, дашборды) описываются в плейбуках и хранятся в VCS.
2. **Автоматическое обнаружение**: При развертывании нового сервиса Ansible автоматически создает соответствующие объекты мониторинга.
3. **GitOps workflow**: Изменения в конфигурации мониторинга проходят через PR, тестируются и применяются через CI/CD.

## Практические сценарии

### Сценарий 1: Развертывание Zabbix Agent и регистрация хоста

```yaml
- name: "Установка Zabbix Agent"
  ansible.builtin.package:
    name: zabbix-agent
    state: present
  become: yes

- name: "Конфигурация Zabbix Agent"
  ansible.builtin.template:
    src: zabbix_agentd.conf.j2
    dest: /etc/zabbix/zabbix_agentd.conf
  notify: restart zabbix-agent
  become: yes

- name: "Запуск Zabbix Agent"
  ansible.builtin.service:
    name: zabbix-agent
    state: started
    enabled: yes
  become: yes

- name: "Регистрация хоста в Zabbix"
  community.zabbix.zabbix_host:
    host: "{{ inventory_hostname }}"
    groups:
      - Linux servers
    interfaces:
      - type: agent
        main: 1
        ip: "{{ ansible_host }}"
        dns: "{{ inventory_hostname }}"
        port: "10050"
    templates:
      - Template OS Linux
    state: present
  delegate_to: localhost
  run_once: yes
```

**Валидация:**
```bash
# Проверка статуса Zabbix Agent
ansible zabbix -i inventory.ini -m service_facts | grep zabbix-agent
# → "zabbix-agent": {"state": "running", "status": "enabled"}

# Проверка доступности порта
ansible zabbix -i inventory.ini -m wait_for -a "host=0.0.0.0 port=10050 timeout=5"
# → {"elapsed": 0.5, "failed": false, "msg": "TCP port 10050 is open"}

# Проверка регистрации хоста в Zabbix API
curl -s -X POST http://zabbix-server/api/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"host.get","params":{"output":["hostid","host"],"filter":{"host":"web01"}},"auth":"YOUR_API_TOKEN","id":1}'
# → {"result":[{"hostid":"12345","host":"web01"}]}
```

### Сценарий 2: Создание монитора в Datadog

```yaml
- name: "Создание монитора высокой нагрузки CPU"
  datadog.dd.datadog_monitor:
    name: "High CPU usage on {{ inventory_hostname }}"
    type: metric
    query:
      monitor_thresholds:
        critical: 90
        warning: 75
      query: "avg(last_5m):avg:system.cpu.user{host:{{ inventory_hostname }}} > 90"
    message: "CPU usage is critically high on {{ inventory_hostname }}"
    priority: 2
    tags:
      - env:production
      - team:platform
    state: present
  delegate_to: localhost
  no_log: yes
```

**Валидация:**
```bash
# Проверка создания монитора через Datadog API
curl -s -X GET "https://api.datadoghq.com/api/v1/monitor" \
  -H "DD-API-KEY: YOUR_API_KEY" \
  -H "DD-APPLICATION-KEY: YOUR_APP_KEY" \
  | jq '.[] | select(.name | contains("web01")) | {id, name, state}'
# → {"id": 123456, "name": "High CPU usage on web01", "state": "new"}

# Проверка метрик в Datadog
curl -s -X GET "https://api.datadoghq.com/api/v2/metrics?query=system.cpu.user" \
  -H "DD-API-KEY: YOUR_API_KEY" \
  -H "DD-APPLICATION-KEY: YOUR_APP_KEY" \
  | jq '.data[].attributes.name'
# → "system.cpu.user"
```

### Сценарий 3: Импорт шаблона Zabbix и связывание

```yaml
- name: "Импорт шаблона PostgreSQL"
  community.zabbix.zabbix_template:
    template_name: PostgreSQL Template
    template_json: "{{ lookup('file', 'templates/postgresql_template.json') }}"
    state: present
  delegate_to: localhost

- name: "Применение шаблона к хостам"
  community.zabbix.zabbix_host:
    host: "{{ item }}"
    groups:
      - Databases
    templates:
      - PostgreSQL Template
    state: present
  loop: "{{ groups['postgresql'] }}"
  delegate_to: localhost
```

**Валидация:**
```bash
# Проверка шаблона в Zabbix
curl -s -X POST http://zabbix-server/api/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"template.get","params":{"output":["hostid","host"],"filter":{"host":"PostgreSQL Template"}},"auth":"YOUR_API_TOKEN","id":1}'
# → {"result":[{"hostid":"54321","host":"PostgreSQL Template"}]}

# Проверка связывания шаблона с хостом
curl -s -X POST http://zabbix-server/api/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"host.get","params":{"output":["hostid","host"],"selectTemplates":"extend","filter":{"host":"db01"}},"auth":"YOUR_API_TOKEN","id":1}'
# → {"result":[{"hostid":"12345","host":"db01","templates":[{"templateid":"54321","name":"PostgreSQL Template"}]}]}
```

### Сценарий 4: Установка Prometheus и node_exporter

```yaml
- name: "Установка Prometheus"
  prometheus.prometheus.prometheus:
    name: prometheus
    version: "3.0.0"
    config:
      global:
        scrape_interval: 15s
      scrape_configs:
        - job_name: node
          static_configs:
            - targets: ['{{ inventory_hostname }}:9100']
  become: yes

- name: "Установка node_exporter"
  prometheus.prometheus.node_exporter:
    name: node_exporter
    listen_address: "0.0.0.0:9100"
  become: yes
```

**Валидация:**
```bash
# Проверка статуса Prometheus
ansible monitoring -i inventory.ini -m service_facts | grep prometheus
# → "prometheus": {"state": "running", "status": "enabled"}

# Проверка targets в Prometheus
ansible monitoring -i inventory.ini -m uri -a "url=http://localhost:9090/api/v1/targets"
# → {"data":{"activeTargets":[{"instance":"web01:9100","health":"up"}]}}

# Проверка метрик node_exporter
ansible web -i inventory.ini -m command -a "curl -s http://localhost:9100/metrics | head -5"
# → node_cpu_seconds_total{cpu="0",mode="idle"} 12345.67
# → node_memory_MemAvailable_bytes 1234567890

# Проверка алертов
ansible monitoring -i inventory.ini -m uri -a "url=http://localhost:9090/api/v1/alerts"
# → {"data":{"alerts":[{"state":"inactive"}]}}
```

### Сценарий 5: Настройка Icinga 2 с checks и уведомлениями

```yaml
- name: "Установка Icinga 2"
  netways.icinga.icinga2:
    state: present
  become: yes

- name: "Создание хоста в Icinga"
  netways.icinga.icinga_host:
    name: "{{ inventory_hostname }}"
    display_name: "{{ inventory_hostname }}"
    address: "{{ ansible_host }}"
    vars:
      os: Linux
    groups:
      - Linux
    state: present
  delegate_to: localhost

- name: "Создание HTTP check"
  netways.icinga.icinga_service:
    name: http
    host_name: "{{ inventory_hostname }}"
    check_command: http
    vars:
      http_url: "http://{{ ansible_host }}/"
      http_ssl: false
    state: present
  delegate_to: localhost
```

**Валидация:**
```bash
# Проверка статуса Icinga 2
systemctl status icinga2
# → ● icinga2.service - Icinga 2 monitoring system
# →      Active: active (running) since Mon 2026-09-26 02:00:00 UTC

# Проверка хоста через Icinga API
curl -s -X POST http://icinga-server:5665/api/v1/objects/hosts \
  -H 'Content-Type: application/json' \
  -u 'root:icinga' \
  -d '{"hosts": ["{{ inventory_hostname }}"]}'
# → {"results":[{"name":"web01","attrs":{"display_name":"web01","address":"192.168.1.10"}}]}

# Проверка service check
curl -s -X POST http://icinga-server:5665/api/v1/objects/services \
  -H 'Content-Type: application/json' \
  -u 'root:icinga' \
  -d '{"services": [{"host":"{{ inventory_hostname }}","name":"http"}]}'
# → {"results":[{"name":"http","attrs":{"state":{"state":1,"type":1}}}]}
```

## Операции и команды

### Zabbix

| Операция | Команда |
| :--- | :--- |
| Регистрация хоста | `community.zabbix.zabbix_host` с `host`, `interfaces`, `templates` |
| Создание шаблона | `community.zabbix.zabbix_template` с `template_name`, `template_json` |
| Создание действия | `community.zabbix.zabbix_action` с `name`, `eventsource`, `conditions`, `operations` |
| Создание триггера | `community.zabbix.zabbix_trigger` с `description`, `expression`, `priority` |

### Datadog

| Операция | Команда |
| :--- | :--- |
| Создание монитора | `datadog.dd.datadog_monitor` с `name`, `type`, `query` |
| Создание дашборда | `datadog.dd.datadog_dashboard` с `title`, `widgets`, `layout_type` |
| Service check | `datadog.dd.datadog_service_check` с `check`, `host_name`, `status` |
| Управление тегами хоста | `datadog.dd.datadog_host` с `host`, `tags` |

### Icinga

| Операция | Команда |
| :--- | :--- |
| Управление хостом | `netways.icinga.icinga_host` с `name`, `address`, `vars`, `groups` |
| Создание проверки | `netways.icinga.icinga_service` с `name`, `host_name`, `check_command` |
| Управление уведомлениями | `netways.icinga.icinga_notification` с `name`, `host_name`, `users` |

### Prometheus

| Операция | Команда |
| :--- | :--- |
| Установка Prometheus | `prometheus.prometheus.prometheus` с `config` |
| Установка node_exporter | `prometheus.prometheus.node_exporter` |
| Установка postgres_exporter | `prometheus.prometheus.postgres_exporter` с `config` |
| Установка blackbox_exporter | `prometheus.prometheus.blackbox_exporter` с `config` |

### Grafana

| Операция | Команда |
| :--- | :--- |
| Установка дашборда | `community.grafana.grafana_dashboard` с `dashboard_source` |
| Создание data source | `community.grafana.grafana_data_source` с `name`, `ds_type`, `url` |

## Устранение неполадок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Zabbix host already exists` | Хост уже зарегистрирован | Используйте `state: present` (идемпотентно); модуль обновит существующий хост |
| `Datadog monitor not found` | Неверный ID или удален монитор | Проверьте `datadog.dd.datadog_monitor` с `state: present` и правильным `name` |
| `Icinga API authentication failed` | Неверные учетные данные | Проверьте `api_user`, `api_password` или `api_password_file` |
| `Prometheus failed to open TSDB` | Проблемы с правами или диском | Проверьте `journalctl -u prometheus`, место на диске |
| `Exporter timeout` | Экспортер не слушает порт | Проверьте `netstat -tlnp | grep 9187` |
| `node_exporter metrics empty` | Неправильная конфигурация Prometheus | Проверьте `scrape_configs` в `prometheus.prometheus.prometheus` |

### Диагностические команды

```bash
# Проверка Zabbix Agent
systemctl status zabbix-agent
# → ● zabbix-agent.service - Zabbix Agent
# →      Active: active (running) since Mon 2026-09-26 02:00:00 UTC

# Проверка регистрации хоста в Zabbix
curl -s -X POST http://zabbix-server/api/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"host.get","params":{"output":["hostid","host"],"filter":{"host":"web01"}},"auth":"YOUR_API_TOKEN","id":1}'
# → {"result":[{"hostid":"12345","host":"web01"}]}

# Проверка node_exporter
curl http://localhost:9100/metrics | head -20
# → node_cpu_seconds_total{cpu="0",mode="idle"} 12345.67
# → node_memory_MemAvailable_bytes 1234567890

# Проверка Prometheus targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {instance: .labels.instance, health: .health}'
# → {"instance":"web01:9100","health":"up"}

# Проверка Icinga 2 статуса
systemctl status icinga2
# → ● icinga2.service - Icinga 2 monitoring system
# →      Active: active (running) since Mon 2026-09-26 02:00:00 UTC

# Проверка Icinga API
curl -s -X POST http://icinga-server:5665/api/v1/status \
  -H 'Content-Type: application/json' \
  -u 'root:icinga'
# → {"status":{"icinga2_version":"2.x.x","endpoints":[...]}}
```

## Рекомендации и оптимизация

### Мониторинг

- **Секреты**: Пароли Zabbix/Datadog/Icinga API храните в Vault. Используйте `no_log: true`.
- **Идемпотентность**: Всегда используйте `state: present` для создания ресурсов. Повторный запуск не должен вызывать ошибок.
- **Module defaults**: Настройте `module_defaults` для `community.zabbix.*`, `datadog.dd.*`, `netways.icinga.*` модулей, чтобы не повторять параметры API.
- **Provisioning**: Используйте `community.grafana.grafana_dashboard` для IaC дашбордов.
- **Alerting**: Настраивайте алерты на уровне исходных систем (Zabbix triggers, Datadog monitors, Icinga notifications), а не только через UI.
- **Retention**: Настройте retention policies в Prometheus (`--storage.tsdb.retention.time`) и Loki.

### Observability

- **Структура метрик**: Соблюдайте конвенции именования метрик (Prometheus naming conventions).
- **Cardinality**: Ограничивайте высокую кардинальность метрик (не более 10-20 значений label).
- **Безопасность**: Открывайте порты экспортеров (9100, 9187) только для доверенных подсетей через `firewalld`/`ufw`.

### Безопасность

- **Минимальные привилегии**: Создавайте пользователей БД только с необходимыми правами.
- **Сетевая изоляция**: Открывайте порты БД (5432, 3306) только для доверенных подсетей через `firewalld`/`ufw`.
- **Аудит**: Включайте логирование PostgreSQL (`log_statement = 'all'`), экспортируйте в Loki/ELK.
- **Секреты**: Никогда не храните пароли в открытом виде. Используйте Ansible Vault или внешние секреты-менеджеры.

## Дополнительная информация

- **[Ansible Zabbix Collection](https://docs.ansible.com/ansible/latest/collections/community/zabbix/)** — документация модулей `community.zabbix`.
- **[Ansible Datadog Collection](https://docs.ansible.com/ansible/latest/collections/datadog/dd/)** — документация модулей `datadog.dd`.
- **[Ansible Prometheus Collection](https://docs.ansible.com/ansible/latest/collections/prometheus/prometheus/)** — документация модулей `prometheus.prometheus`.
