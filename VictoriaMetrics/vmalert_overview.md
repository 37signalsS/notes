# Обзор vmalert

## 1. Определения

**vmalert** — это компонент стека [VictoriaMetrics](./overview.md), который выполняет правила алертинга и/или правила записи (recording rules).

## 2. Базовые концепции

`vmalert` периодически выполняет заданные PromQL-подобные выражения и, в зависимости от результата, отправляет оповещения в [Alertmanager](../Prometheus/alertmanager.md) или записывает новые метрики обратно в хранилище VictoriaMetrics.

### Ключевые функции

- **Выполнение правил алертинга** — `vmalert` запрашивает данные из источника (например, VictoriaMetrics), выполняет выражения из правил и, если условие выполняется, генерирует алерты и отправляет их в один или несколько настроенных Alertmanager'ов.
- **Выполнение правил записи (recording rules)** — позволяет предварительно вычислять и сохранять результаты ресурсоемких или часто используемых запросов в виде новых метрик. Это ускоряет загрузку дашбордов и снижает нагрузку на основное хранилище метрик.
- **Поддержка множества источников данных** — может работать с любым хранилищем, совместимым с Prometheus Querying API, включая VictoriaMetrics, Prometheus, Thanos и другие.
- **Поддержка множества Alertmanager'ов** — может отправлять алерты в несколько инстансов Alertmanager для обеспечения высокой доступности.
- **Гибкое управление правилами** — правила могут быть загружены из локальных файлов, а также автоматически обнаружены через HTTP discovery или из `ConfigMap`/`Secret` в Kubernetes.
- **Hot reload** — поддерживает горячую перезагрузку конфигурации без перезапуска процесса.

### Отличие от Alertmanager

Важно понимать различие в ролях:

| Компонент | Назначение | Пример |
| :--- | :--- | :--- |
| **`vmalert`** (или Prometheus) | **Генерирует** алерты | `IF cpu_usage > 90% THEN fire alert` |
| **`Alertmanager`** | **Обрабатывает** алерты | Дедупликация, группировка, silence, маршрутизация в Slack/PagerDuty/email |

`vmalert` — это замена стандартного механизма выполнения правил Prometheus, оптимизированная для работы в экосистеме VictoriaMetrics.

## 3. Практические сценарии

### Пример конфигурации правил алертинга

Файл правил `alert-rules.yaml`:

```yaml
groups:
  - name: node-alerts
    interval: 30s  # Как часто выполнять правила
    rules:
      - alert: HighCpuUsage
        expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 5m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is above 85% for more than 5 minutes on {{ $labels.instance }}. Current value: {{ $value }}%"
          
      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is above 90% for more than 5 minutes. Current value: {{ $value }}%"
          
      - alert: DiskSpaceLow
        expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 10
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Low disk space on {{ $labels.instance }}"
          description: "Disk space is below 10% on {{ $labels.instance }}. Current value: {{ $value }}%"
```

### Пример конфигурации правил записи (recording rules)

Recording rules полезны для предварительного вычисления сложных запросов:

```yaml
groups:
  - name: recording-rules
    interval: 1m
    rules:
      # Предварительный расчет среднего CPU usage по кластеру
      - record: cluster:node_cpu:avg_rate5m
        expr: avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
        
      # Предварительный расчет использования памяти в процентах
      - record: node:memory_usage_percent:ratio
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### Пример запуска vmalert

#### Локальный запуск (Single-node)

```bash
vmalert \
  -datasource.url=http://localhost:8428 \
  -notifier.url=http://localhost:9093 \
  -rule=/path/to/rules/*.yaml \
  -httpListenAddr=:8080
```

#### Kubernetes (фрагмент Deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vmalert
  namespace: monitoring
spec:
  replicas: 2
  selector:
    matchLabels:
      app: vmalert
  template:
    spec:
      containers:
        - name: vmalert
          image: victoriametrics/vmalert:v1.100.0
          args:
            - -datasource.url=http://victoria-metrics.monitoring.svc:8428
            - -notifier.url=http://alertmanager.monitoring.svc:9093
            - -rule=/config/rules/*.yaml
            - -httpListenAddr=:8080
            - -evaluationInterval=30s
          ports:
            - containerPort: 8080
              name: http
          volumeMounts:
            - name: rules
              mountPath: /config/rules
      volumes:
        - name: rules
          configMap:
            name: vmalert-rules
```

### Проверка состояния vmalert

`vmalert` предоставляет веб-интерфейс (по умолчанию порт `8080`) со следующими эндпоинтами:

- `/targets` — список всех правил и их текущее состояние
- `/alerts` — активные алерты
- `/metrics` — метрики самого `vmalert` для мониторинга
- `/-/reload` — горячая перезагрузка конфигурации (hot reload)

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Правила не выполняются | Неверный путь к файлам правил | Проверить аргумент `-rule` и наличие файлов |
| Алерты не отправляются | Недоступен Alertmanager | Проверить `-notifier.url` и сетевую связность |
| Ошибки в выражениях | Синтаксическая ошибка в PromQL/MetricsQL | Проверить логи `vmalert`, использовать `vmctl check` |
| Высокая задержка выполнения | Слишком частый `evaluationInterval` | Увеличить интервал или оптимизировать запросы |

## 4. Дополнительная информация

Официальная документация: [vmalert](https://docs.victoriametrics.com/vmalert/), [шаблоны правил алертинга](https://docs.victoriametrics.com/vmalert/#alerting-template-rules), [recording rules best practices](https://docs.victoriametrics.com/vmalert/#recording-rules).

Связанные компоненты: [Alertmanager](../Prometheus/alertmanager.md) (маршрутизация алертов), [VictoriaMetrics](./overview.md) (хранилище данных), [Grafana](../Grafana/grafana_overview.md) (визуализация).
