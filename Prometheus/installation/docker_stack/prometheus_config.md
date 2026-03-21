# Конфигурация Prometheus

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

* **`rule_files`**: Указывает путь к файлу с [правилами](../../rules.md) для Alertmanager.
* **`alerting`**: Настраивает подключение к [Alertmanager](../../alertmanager.md).
* **`scrape_configs`**: Определяет, какие эндпоинты (job) опрашивать. Мы используем DNS-имена сервисов из `docker-compose`, Docker обеспечивает их разрешение. Подробнее о механизме в [Service Discovery](../../service_discovery_and_relabeling.md).

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

* **`expr`**: [PromQL](../../concepts/promql/selectors_operators.md)-выражение. Если оно истинно, алерт переходит в состояние `Pending`.
* **`for`**: Длительность, в течение которой `expr` должно быть истинным, чтобы алерт стал `Firing`.
* **`annotations`**: Содержание оповещения.
