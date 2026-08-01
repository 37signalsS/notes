# Обзор vmalert

## 1. Определения

**vmalert** — это высокопроизводительный компонент стека [VictoriaMetrics](./overview.md), предназначенный для выполнения правил алертинга и правил записи (recording rules). Он является полноценной заменой встроенного механизма правил Prometheus, предлагая расширенные возможности масштабирования и интеграции.

## 2. Базовые концепции

`vmalert` периодически выполняет выражения на языке **MetricsQL** (для метрик), **LogsQL** (для логов) или запрашивает данные из **VictoriaTraces**. По результатам выполнения он отправляет оповещения в [Alertmanager](../Prometheus/alertmanager.md) или записывает новые (агрегированные) метрики обратно в VictoriaMetrics.

### Ключевые функции

- **Выполнение правил алертинга** — запрашивает данные из источника, оценивает условия и генерирует алерты. Поддерживает сложные условия благодаря MetricsQL.
- **Выполнение правил записи (recording rules)** — позволяет предварительно вычислять сложные запросы и сохранять их как новые метрики. Это критично для ускорения тяжелых дашбордов в Grafana.
- **Интеграция с VictoriaLogs** — поддержка алертинга на основе логов (например, срабатывание при появлении определенных ошибок в логах или превышении их частоты).
- **Сохранение состояния (Stateful Alerting)** — `vmalert` может сохранять состояние алертов (Pending/Firing) в удаленное хранилище через Remote Write. Это позволяет не терять историю алертов при перезапуске компонента.
- **Поддержка множества источников и нотификаторов** — может работать одновременно с несколькими источниками данных (VictoriaMetrics, Prometheus) и отправлять уведомления в несколько кластеров Alertmanager.
- **Шаблонизация аннотаций** — расширенная поддержка Go-templates с дополнительными функциями (например, `now`, `query`, `label`).
- **Relabeling** — поддержка переименования и фильтрации меток (labels) как для алертов перед отправкой, так и для записываемых метрик.
- **Hot reload** — обновление конфигурации без простоя через сигнал SIGHUP или HTTP-эндпоинт.

### Отличие от Alertmanager

Важно понимать различие в ролях:

| Компонент | Назначение | Пример |
| :--- | :--- | :--- |
| **`vmalert`** | **Генерирует** алерты (логика "когда бить тревогу") | `IF rate(errors) > 5 THEN fire alert` |
| **`Alertmanager`** | **Обрабатывает** алерты (маршрутизация, дедупликация) | Группировка 100 алертов в одно письмо в Slack |

`vmalert` — это "движок" выполнения логики, который делает запросы к БД, в то время как Alertmanager — это система управления уведомлениями.

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

### Пример алертинга на основе логов (VictoriaLogs)

`vmalert` может использовать `VictoriaLogs` как источник данных. Пример правила, которое срабатывает, если в логах сервиса `auth` за 5 минут появилось более 10 ошибок:

```yaml
groups:
  - name: log-alerts
    interval: 1m
    rules:
      - alert: AuthServiceHighErrorRate
        # LogsQL выражение
        expr: |
          _stream:{app="auth"} | filter "error" | stats by (app) count() > 10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate in logs for {{ $labels.app }}"
          description: "Found more than 10 errors in auth service logs within last 5 minutes."
```

### Пример правил записи (recording rules)

Recording rules полезны для предварительного вычисления сложных запросов:

```yaml
groups:
  - name: recording-rules
    interval: 1m
    rules:
      # Предварительный расчет среднего CPU usage по кластеру (MetricsQL)
      - record: cluster:node_cpu:avg_rate5m
        expr: avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
        
      # Расчет процента использования памяти
      - record: node:memory_usage_percent:ratio
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### Replay API: Пересчет исторических данных

Одной из уникальных функций `vmalert` является **Replay API**. Он позволяет выполнить правила на исторических данных. Это полезно, если вы создали новое правило записи и хотите заполнить историю метрики за прошлый месяц.

Пример команды для запуска пересчета:
```bash
# Выполнить правила из файла за указанный период
vmalert -rule=rules.yaml \
  -replay.timeFrom=2024-01-01T00:00:00Z \
  -replay.timeTo=2024-01-31T23:59:59Z \
  -datasource.url=http://victoriametrics:8428 \
  -remoteWrite.url=http://victoriametrics:8428
```

### Пример запуска vmalert

#### Локальный запуск (с сохранением состояния)

```bash
vmalert \
  -datasource.url=http://localhost:8428 \
  -notifier.url=http://localhost:9093 \
  -remoteWrite.url=http://localhost:8428 \
  -remoteRead.url=http://localhost:8428 \
  -rule=/path/to/rules/*.yaml
```
*Флаг `-remoteWrite.url` включает сохранение состояния алертов в саму VictoriaMetrics.*

#### Kubernetes (фрагмент Deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vmalert
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: vmalert
          # Рекомендуется использовать LTS версию или последнюю стабильную
          image: victoriametrics/vmalert:v1.136.0
          args:
            - -datasource.url=http://vmstorage.monitoring.svc:8428
            - -notifier.url=http://alertmanager.monitoring.svc:9093
            - -remoteWrite.url=http://vmstorage.monitoring.svc:8428
            - -rule=/config/rules/*.yaml
            - -httpListenAddr=:8080
          ports:
            - containerPort: 8080
              name: http
```

### Проверка состояния vmalert

`vmalert` предоставляет веб-интерфейс (порт `8080`) и интегрируется в основной `vmui`:

- `/targets` — список всех групп правил и их здоровье.
- `/alerts` — список активных алертов с их текущим состоянием (Firing/Pending) и метками.
- `/metrics` — внутренние метрики компонента.
- `/api/v1/replay` — API для управления процессами пересчета.
- `/-/reload` — обновление конфигурации.

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Правила не выполняются | Неверный путь или права доступа | Проверить `-rule` и логи контейнера |
| Алерты пропадают после рестарта | Не настроен Remote Write | Добавить флаг `-remoteWrite.url` для сохранения состояния |
| "Failed to execute request" | Тайм-аут источника данных | Увеличить `-datasource.queryTimeout` или оптимизировать запрос |
| Ошибки синтаксиса | Ошибка в YAML или MetricsQL | Использовать `vmalert-tool` для валидации правил перед деплоем |

## 4. Дополнительная информация

- **VMUI (Alerting Tab):** Современный способ визуализации алертов `vmalert` доступен напрямую в VictoriaMetrics UI.
- **vmalert-tool:** Утилита для проверки синтаксиса и модульного тестирования правил (unit testing).
- **vmanomaly:** Интеграция с сервисом обнаружения аномалий для создания динамических порогов.

Официальная документация: [vmalert docs](https://docs.victoriametrics.com/vmalert/), [Troubleshooting vmalert](https://docs.victoriametrics.com/vmalert/#troubleshooting).

Связанные компоненты: [VictoriaMetrics](./overview.md), [VictoriaLogs](https://docs.victoriametrics.com/victorialogs/), [Alertmanager](../Prometheus/alertmanager.md).
