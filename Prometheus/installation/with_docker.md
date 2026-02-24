# Установка стека мониторинга в Docker с Docker Compose

Это руководство описывает практический сценарий развертывания полноценного стека мониторинга с использованием [Docker](../../Docker/docker_overview.md) и [Docker Compose](../../Docker/Docker_compose/docker_compose_file_example.md).

---

### 1. Определения

* **Prometheus**: Основной компонент для сбора, хранения и обработки метрик в виде временных рядов.
* **Grafana**: Платформа для визуализации и анализа метрик, позволяющая создавать интерактивные дашборды.
* **Alertmanager**: Компонент для обработки оповещений, отвечающий за их дедупликацию, группировку и маршрутизацию.
* **cAdvisor**: Инструмент для сбора, агрегации и экспорта метрик о производительности и ресурсах работающих контейнеров.
* **Node Exporter**: Экспортер для сбора метрик с хост-машины (ОС и аппаратное обеспечение).

---

### 2. Основные концепции

#### Принцип развертывания с Docker Compose

[Docker Compose](../../Docker/Docker_compose/docker_compose_file_example.md) используется для определения и запуска многоконтейнерных Docker-приложений. Это позволяет легко оркестрировать весь стек мониторинга как единое целое, управлять его жизненным циклом и конфигурацией.

#### Структура проекта

Для удобства управления конфигурационные файлы каждого компонента размещаются в отдельных поддиректориях:

```
monitoring/
├── docker-compose.yml
├── prometheus/
│   ├── prometheus.yml
│   └── rules.yml
└── alertmanager/
    └── config.yml
```

#### Использование DNS в Docker Compose

В сети, созданной Docker Compose, сервисы могут обращаться друг к другу по своим именам, указанным в файле `docker-compose.yml` (например, `prometheus`, `alertmanager`, `node-exporter`). Docker автоматически обеспечивает разрешение этих имен в IP-адреса контейнеров.

#### Персистентность данных

Для сохранения данных Prometheus (метрики) и Grafana (дашборды, источники данных, пользователи) при перезапуске или удалении контейнеров используются именованные [Docker-тома (volumes)](../../Docker/Docker_fs/docker_volumes.md): `prometheus_data` и `grafana_data`.

---

### 3. Практические сценарии

#### Конфигурация Docker Compose

Создайте файл `monitoring/docker-compose.yml` со следующим содержимым:

```yaml
version: '3.7'

services:
  prometheus:
    image: prom/prometheus:v2.53.1 # Используйте актуальную версию
    container_name: prometheus
    volumes:
      - ./prometheus:/etc/prometheus
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    ports:
      - "9090:9090"
    restart: unless-stopped
    networks:
      - monitoring-net

  alertmanager:
    image: prom/alertmanager:v0.27.0 # Используйте актуальную версию
    container_name: alertmanager
    volumes:
      - ./alertmanager:/config
    command:
      - '--config.file=/config/config.yml'
      - '--storage.path=/alertmanager'
    ports:
      - "9093:9093"
    restart: unless-stopped
    networks:
      - monitoring-net

  node-exporter:
    image: prom/node-exporter:v1.8.2 # Используйте актуальную версию
    container_name: node-exporter
    pid: host # Позволяет видеть процессы хоста
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro # Доступ к корневой ФС хоста
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    restart: unless-stopped
    networks:
      - monitoring-net

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.53.0 # Используйте актуальную версию
    container_name: cadvisor
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:rw
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    ports:
      - "8080:8080"
    restart: unless-stopped
    networks:
      - monitoring-net

  grafana:
    image: grafana/grafana:11.1.0 # Используйте актуальную версию
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    restart: unless-stopped
    networks:
      - monitoring-net

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring-net:
    driver: bridge
```

#### Конфигурация Prometheus

Создайте файл `monitoring/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s

rule_files:
  - /etc/prometheus/rules.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager:9093' # Имя сервиса Alertmanager в Docker Compose

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090'] # Prometheus собирает метрики сам с себя

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100'] # Имя сервиса Node Exporter

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080'] # Имя сервиса cAdvisor
```

* **`rule_files`**: Указывает путь к файлу с [правилами](../rules.md) для Alertmanager.
* **`alerting`**: Настраивает подключение к [Alertmanager](../alertmanager.md).
* **`scrape_configs`**: Определяет, какие эндпоинты (job) опрашивать. Мы используем DNS-имена сервисов из `docker-compose`, Docker обеспечивает их разрешение. Подробнее о механизме в [Service Discovery](../service_discovery_and_relabeling.md).

Создайте файл `monitoring/prometheus/rules.yml` с примерами правил оповещений:

```yaml
groups:
  - name: node_alerts
    rules:
      - alert: HostHighCpuLoad
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая загрузка CPU на {{ $labels.instance }}"
          description: "Загрузка CPU превышает 85% в течение 5 минут на инстансе {{ $labels.instance }}."

      - alert: HostHighMemoryLoad
        expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100 > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Высокое потребление памяти на {{ $labels.instance }}"
          description: "Потребление памяти превышает 90% в течение 5 минут на инстансе {{ $labels.instance }}."
```

* **`expr`**: [PromQL](../concepts/promql.md)-выражение. Если оно истинно, алерт переходит в состояние `Pending`.
* **`for`**: Длительность, в течение которой `expr` должно быть истинным, чтобы алерт стал `Firing`.
* **`annotations`**: Содержание оповещения.

#### Конфигурация Alertmanager

Создайте файл `monitoring/alertmanager/config.yml`:

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587' # Замените на ваш SMTP-сервер
  smtp_from: 'alertmanager@example.com' # Email отправителя
  smtp_auth_username: 'your-username' # Логин SMTP
  smtp_auth_password: 'your-password' # Пароль SMTP

route:
  receiver: 'default-receiver'
  group_by: ['alertname', 'cluster', 'service'] # Группировка схожих алертов
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    - receiver: 'telegram-notifications' # Пример: маршрутизация критических алертов в Telegram
      match:
        severity: 'critical'

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'admin-team@example.com' # Email получателя
        send_resolved: true # Отправлять уведомление о разрешении алерта

  - name: 'telegram-notifications'
    webhook_configs:
      - url: 'http://your-telegram-bot-webhook-url/...' # URL для интеграции с Telegram
        send_resolved: true
```

* **`global`**: Глобальные настройки, например, для SMTP.
* **`route`**: Определяет маршрутизацию алертов. `group_by` позволяет группировать схожие алерты в одно уведомление.
* **`receivers`**: Описывает "получателей" — каналы отправки (email, webhook, Slack и т.д.).

#### Запуск и проверка

1. Убедитесь, что все файлы и директории созданы согласно [структуре проекта](#структура-проекта).
2. Перейдите в директорию `monitoring/`.
3. Запустите стек Docker Compose:

    ```bash
    docker-compose up -d
    ```

4. **Prometheus**: Откройте `http://localhost:9090`. На вкладке **Status -> Targets** убедитесь, что все цели (`prometheus`, `node-exporter`, `cadvisor`) имеют статус `UP`.
5. **Grafana**: Откройте `http://localhost:3000`. Войдите (`admin`/`admin`), добавьте Prometheus как [Data Source](../../Grafana/grafana_datasources.md) (`http://prometheus:9090`) и импортируйте [дашборды](../../Grafana/grafana_dashboards.md) (например, `1860` для Node Exporter, `13981` для Docker/cAdvisor).
6. **Alertmanager**: Откройте `http://localhost:9093`.

#### Мониторинг удаленных хостов

Для мониторинга удаленных машин запустите экспортеры на этих машинах и добавьте их в конфигурацию Prometheus.

1. **На удаленном хосте**:
    Создайте `docker-compose.yml`, содержащий только секции `node-exporter` и/или `cadvisor` из основного файла. Запустите их. Убедитесь, что необходимые порты (например, `9100` и `8080`) доступны с вашего главного сервера мониторинга.

2. **На главном сервере мониторинга**:
    Обновите файл `prometheus/prometheus.yml`, добавив IP-адреса удаленных хостов в `scrape_configs`:

    ```yaml
    # ... другие job'ы

    - job_name: 'remote-node-exporter'
      static_configs:
        - targets: ['<IP_АДРЕС_УДАЛЕННОГО_ХОСТА_1>:9100', '<IP_АДРЕС_УДАЛЕННОГО_ХОСТА_2>:9100']

    - job_name: 'remote-cadvisor'
      static_configs:
        - targets: ['<IP_АДРЕС_УДАЛЕННОГО_ХОСТА_1>:8080', '<IP_АДРЕС_УДАЛЕННОГО_ХОСТА_2>:8080']
    ```

    Перезагрузите Prometheus на главном сервере:

    ```bash
    docker-compose restart prometheus
    ```

    Центральный Prometheus теперь будет собирать метрики как с локальных, так и с удаленных экспортеров.

---

### 4. Дополнительная информация

* **Docker**: Обзор и основные концепции [docker_overview](../../Docker/docker_overview.md).
* **Docker Compose**: Подробное описание и примеры использования [docker_compose_file_example](../../Docker/Docker_compose/docker_compose_file_example.md).
* **Prometheus**: Общий обзор архитектуры и принципов работы [overview](../overview.md).
* **Grafana**: Обзор платформы и ее возможностей [grafana_overview](../../Grafana/grafana_overview.md).
* **Alertmanager**: Детальное описание и настройка [alertmanager](../alertmanager.md).
* **Node Exporter**: Подробности об экспортере для ОС [exporters](../Exporters/overview.md).
* **cAdvisor**: Документация (внешняя ссылка) [Google cAdvisor](https://github.com/google/cadvisor).
* **Конфигурация Prometheus**: Детальное описание директив `prometheus.yml` [configuration](../configuration.md).
* **PromQL**: Язык запросов Prometheus [promql](../concepts/promql.md).
* **Правила Prometheus**: Правила записи и оповещений [rules](../rules.md).
* **Источники данных Grafana**: Настройка источников данных [grafana_datasources](../../Grafana/grafana_datasources.md).
* **Дашборды Grafana**: Создание и импорт дашбордов [grafana_dashboards](../../Grafana/grafana_dashboards.md).
* **Service Discovery в Prometheus**: Автоматическое обнаружение целей [service_discovery_and_relabeling](../service_discovery_and_relabeling.md).
