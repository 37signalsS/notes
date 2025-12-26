# Руководство по установке стека мониторинга в Docker

Это руководство описывает практический сценарий развертывания полноценного стека мониторинга с использованием [Docker](../../Docker/docker_overview.md) и [Docker Compose](../../Docker/Docker_compose/docker_compose_file_example.md).

## 0. Компоненты стека

Краткий обзор инструментов, используемых в этом руководстве:

- **[Prometheus](../overview.md)**: Основной компонент для сбора и хранения метрик в виде временных рядов. Подробности в [общем обзоре Prometheus](../overview.md).
- **[Grafana](../../Grafana/grafana_overview.md)**: Платформа для визуализации и анализа метрик. Позволяет создавать интерактивные дашборды. Детальнее в [обзоре Grafana](../../Grafana/grafana_overview.md).
- **[Alertmanager](../alertmanager.md)**: Обрабатывает оповещения, отправленные клиентами (например, Prometheus). Отвечает за дедупликацию, группировку и маршрутизацию оповещений. См. заметку про [Alertmanager](../alertmanager.md).
- **[cAdvisor](https://github.com/google/cadvisor)**: Инструмент для сбора, агрегации и экспорта метрик о производительности и ресурсах работающих контейнеров.
- **[Node Exporter](../exporters.md)**: Экспортер для сбора метрик с хост-машины (ОС и "железо"). Является одним из многих [экспортеров Prometheus](../exporters.md).

## 1. Структура проекта

```
monitoring/
├── docker-compose.yml
├── prometheus/
│   ├── prometheus.yml
│   └── rules.yml
└── alertmanager/
    └── config.yml
```

## 2. Конфигурация Docker Compose

Создайте файл `docker-compose.yml` со следующим содержимым.

```yaml
version: '3.7'

services:
  prometheus:
    image: prom/prometheus:v2.53.1
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

  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: alertmanager
    volumes:
      - ./alertmanager:/config
    command:
      - '--config.file=/config/config.yml'
      - '--storage.path=/alertmanager'
    ports:
      - "9093:9093"
    restart: unless-stopped

  node-exporter:
    image: prom/node-exporter:v1.8.2
    container_name: node-exporter
    pid: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    restart: unless-stopped

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.53.0
    container_name: cadvisor
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:rw
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    ports:
      - "8080:8080"
    restart: unless-stopped

  grafana:
    image: grafana/grafana:11.1.0
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    restart: unless-stopped

volumes:
  prometheus_data:
  grafana_data:
```

## 3. Конфигурация Prometheus

### `prometheus/prometheus.yml`

Это основной конфигурационный файл Prometheus, где определяются цели для сбора метрик (`scrape_configs`). Подробнее о настройке см. в [файле конфигурации Prometheus](../configuration.md).

```yaml
global:
  scrape_interval: 15s

rule_files:
  - /etc/prometheus/rules.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager:9093'

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
```
*   **`rule_files`**: Указывает путь к файлу с [правилами](../rules.md) для Alertmanager.
*   **`alerting`**: Настраивает подключение к [Alertmanager](../alertmanager.md).
*   **`scrape_configs`**: Определяет, какие эндпоинты (job) опрашивать. Мы используем DNS-имена сервисов из `docker-compose`, Docker обеспечивает их разрешение. Подробнее о механизме в [Service Discovery](../service_discovery_and_relabeling.md).

### `prometheus/rules.yml`

Файл с [правилами генерации оповещений](../rules.md).

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
          summary: "High CPU load on {{ $labels.instance }}"
          description: "CPU load is over 85% for the last 5 minutes on instance {{ $labels.instance }}."

      - alert: HostHighMemoryLoad
        expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100 > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is over 90% for the last 5 minutes on instance {{ $labels.instance }}."
```
*   **`expr`**: [PromQL](../concepts/promql.md)-выражение. Если оно истинно, алерт переходит в состояние `Pending`.
*   **`for`**: Длительность, в течение которой `expr` должно быть истинным, чтобы алерт стал `Firing`.
*   **`annotations`**: Содержание оповещения.

## 4. Конфигурация Alertmanager

### `alertmanager/config.yml`

Настраивает, как [Alertmanager](../alertmanager.md) будет обрабатывать и куда отправлять оповещения.

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587'
  smtp_from: 'alertmanager@example.com'
  smtp_auth_username: 'your-username'
  smtp_auth_password: 'your-password'

route:
  receiver: 'default-receiver'
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    - receiver: 'telegram-notifications'
      match:
        severity: 'critical'

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'admin-team@example.com'
        send_resolved: true

  - name: 'telegram-notifications'
    webhook_configs:
      - url: 'http://your-telegram-bot-webhook-url/...'
        send_resolved: true
```
*   **`global`**: Глобальные настройки, например, для SMTP.
*   **`route`**: Определяет маршрутизацию алертов. `group_by` позволяет группировать схожие алерты в одно уведомление.
*   **`receivers`**: Описывает "получателей" — каналы отправки (email, webhook, Slack и т.д.).

## 5. Запуск и проверка

1.  Создайте все файлы и директории, как описано выше.
2.  Выполните команду в директории с `docker-compose.yml`:
    ```bash
    docker-compose up -d
    ```
3.  **Prometheus**: Откройте `http://localhost:9090`. Во вкладке **Status -> Targets** проверьте, что все цели (`prometheus`, `node-exporter`, `cadvisor`) имеют статус `UP`.
4.  **Grafana**: Откройте `http://localhost:3000`. Войдите (`admin`/`admin`), добавьте Prometheus как [Data Source](../../Grafana/grafana_datasources.md) (`http://prometheus:9090`) и импортируйте [дашборды](../../Grafana/grafana_dashboards.md) (например, `1860` для Node Exporter, `13981` для Docker).
5.  **Alertmanager**: Откройте `http://localhost:9093`.

Теперь у вас есть работающий стек мониторинга, развернутый в Docker.

## 6. Мониторинг удаленных хостов

Архитектура, описанная в этом руководстве, предполагает, что все компоненты запущены на одном хосте. Однако вы можете использовать части этой конфигурации для мониторинга удаленных машин.

Для этого на каждом удаленном хосте, который вы хотите отслеживать, необходимо запустить только экспортеры (`node-exporter` и/или `cAdvisor`).

**Шаги:**

1.  **На удаленном хосте:** Создайте `docker-compose.yml`, содержащий только секции `node-exporter` и `cadvisor` из основного файла. Запустите их. Убедитесь, что порты `9100` и `8080` доступны с вашего главного сервера мониторинга.

2.  **На главном сервере мониторинга:** Обновите файл `prometheus/prometheus.yml`, добавив IP-адреса удаленных хостов в `scrape_configs`.

    ```yaml
    # ... другие job'ы

    - job_name: 'remote-node-exporter'
      static_configs:
        - targets: ['<IP_АДРЕС_УДАЛЕННОГО_ХОСТА_1>:9100', '<IP_АДРЕС_УДАЛЕННОГО_ХОСТА_2>:9100']

    - job_name: 'remote-cadvisor'
      static_configs:
        - targets: ['<IP_АДРЕС_УДАЛЕННОГО_ХОСТА_1>:8080', '<IP_АДРЕС_УДАЛЕННОГО_ХОСТА_2>:8080']
    ```

3.  Перезапустите Prometheus на главном сервере (`docker-compose restart prometheus`).

Таким образом, центральный Prometheus будет собирать метрики как с локальных, так и с удаленных экспортеров.