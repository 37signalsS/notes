# Blackbox Exporter — Масштабирование и высокая доступность

## Определения

**Масштабирование Blackbox Exporter** — процесс адаптации инфраструктуры синтетического мониторинга к росту количества целей, частоты проверок и требований к отказоустойчивости. Включает горизонтальное масштабирование (шардирование), балансировку нагрузки и обеспечение высокой доступности (HA) самого экспортера.

*   **Shard (Шард)** — логическая или физическая часть экспортера, обслуживающая определённый набор целей. Шардирование позволяет распределить нагрузку между несколькими инстансами.
*   **HA (High Availability)** — режим работы, при котором единственный отказ инстанса экспортера не приводит к потере данных мониторинга.
*   **Anti-affinity** — правило оркестратора (Kubernetes), предотвращающее запуск нескольких подов одного сервиса на одном узле.
*   **Health Check** — периодическая проверка работоспособности самого экспортера (эндпоинт `/metrics` с метрикой `up`).
*   **Probe Distribution** — стратегия распределения проверок по инстансам экспортера для минимизации влияния на целевые сервисы.

**Связанные документы:**
*   [Обзор и концепции](./blackbox_exporter_overview.md)
*   [Установка и настройка](./blackbox_exporter_installation_and_setup.md)
*   [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)

## Основные концепции

### Пороговые значения масштабирования

| Количество целей | Интервал проверок | Рекомендуемые ресурсы | Количество инстансов |
|:---|:---|:---|:---|
| < 500 | 15–30s | 1 CPU, 128 MiB RAM | 1 (单实例) |
| 500–2000 | 15–30s | 2 CPU, 256 MiB RAM | 1–2 (рекомендуется HA) |
| 2000–10000 | 15–60s | 2–4 CPU, 512 MiB RAM | 2–4 (шардирование) |
| > 10000 | 30–60s | 4+ CPU, 1 GiB RAM | 4+ (шардирование + LB) |

**Факторы, влияющие на потребление ресурсов:**
1.  **Количество целей:** Каждая активная проверка потребляет ~1–5 MiB RAM.
2.  **Частота проверок:** Интервал < 10s значительно увеличивает нагрузку.
3.  **Тип протокола:** HTTP с TLS-handshake тяжелее TCP/ICMP.
4.  **Количество модулей:** Каждый модуль держит отдельный пул соединений.

### Модели масштабирования

#### Модель 1: Горизонтальное масштабирование (шардирование)

Каждый инстанс экспортера обслуживает свою часть целей. Prometheus направляет запросы к разным инстансам через `relabel_configs` или балансировщик.

```
                    ┌──────────────────┐
                    │   Prometheus     │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
     │ Shard 1     │ │ Shard 2     │ │ Shard 3     │
     │ (10.0.0.1)  │ │ (10.0.0.2)  │ │ (10.0.0.3)  │
     │ targets: A-F│ │ targets: G-M│ │ targets: N-Z│
     └─────────────┘ └─────────────┘ └─────────────┘
```

**Конфигурация Prometheus со шардированием:**

```yaml
scrape_configs:
  # Шард 1: targets A-F
  - job_name: 'blackbox-shard-1'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://api-a.example.com
        - https://api-b.example.com
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: 10.0.0.1:9115

  # Шард 2: targets G-M
  - job_name: 'blackbox-shard-2'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://api-g.example.com
        - https://api-m.example.com
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: 10.0.0.2:9115
```

**Преимущества:**
- Простая реализация
- Изоляция отказов (падение Shard 1 не влияет на Shard 2)
- Линейное масштабирование ресурсов

**Недостатки:**
- Неравномерное распределение целей (разные модули по-разному нагружают экспортер)
- Требует ручного управления при добавлении/удалении целей

#### Модель 2: Балансировка через Load Balancer

Все инстансы экспортера равноправны, балансировщик распределяет запросы между ними.

```
                    ┌──────────────────┐
                    │   Prometheus     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  Load Balancer   │
                    │  (L4/TCP)        │
                    └────────┬─────────┘
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
     │ Exporter 1  │ │ Exporter 2  │ │ Exporter 3  │
     │ (все цели)  │ │ (все цели)  │ │ (все цели)  │
     └─────────────┘ └─────────────┘ └─────────────┘
```

**Конфигурация Prometheus с балансировщиком:**

```yaml
scrape_configs:
  - job_name: 'blackbox-ha'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://api-a.example.com
        - https://api-b.example.com
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: blackbox-lb.monitoring.svc:9115  # Адрес LB
```

**Балансировка на уровне Kubernetes (Service):**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: blackbox-exporter
  namespace: monitoring
spec:
  type: ClusterIP
  selector:
    app: blackbox-exporter
  ports:
    - port: 9115
      targetPort: 9115
      protocol: TCP
```

**Преимущества:**
- Простая конфигурация Prometheus (один job)
- Автоматическое перераспределение при отказе инстанса
- Равномерная нагрузка

**Недостатки:**
- Дополнительный компонент (LB) как potential point of failure
- Все инстансы хранят одну конфигурацию модулей

#### Модель 3: Географическое распределение

Инстансы экспортера размещаются в разных регионах/центрах обработки данных для проверки доступности с разных точек сети.

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  DC: Moscow     │  │  DC: Frankfurt  │  │  DC: Singapore  │
│  Exporter (10)  │  │  Exporter (10)  │  │  Exporter (10)  │
│  targets: all   │  │  targets: all   │  │  targets: all   │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Prometheus      │
                    │   (или Mimir)     │
                    └───────────────────┘
```

**Конфигурация с гео-различиями:**

```yaml
scrape_configs:
  - job_name: 'blackbox-moscow'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://api.example.com
        labels:
          region: 'moscow'
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: blackbox-moscow.internal:9115

  - job_name: 'blackbox-frankfurt'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://api.example.com
        labels:
          region: 'frankfurt'
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: blackbox-frankfurt.internal:9115
```

**Преимущества:**
- Выявление проблем с маршрутизацией и CDN
- Объективная проверка доступности из разных географических точек
- Соответствие требованиям SLA для глобальных сервисов

**Недостатки:**
- Увеличение кардинальности метрик (лейбл `region`)
- Стоимость инфраструктуры в нескольких регионах

### Высокая доступность (HA)

#### HA через Replicas в Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blackbox-exporter
  namespace: monitoring
spec:
  replicas: 3
  selector:
    matchLabels:
      app: blackbox-exporter
  template:
    metadata:
      labels:
        app: blackbox-exporter
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values:
                        - blackbox-exporter
                topologyKey: kubernetes.io/hostname
      containers:
        - name: blackbox
          image: prom/blackbox-exporter:v0.28.0
          ports:
            - containerPort: 9115
          livenessProbe:
            httpGet:
              path: /metrics
              port: 9115
            initialDelaySeconds: 5
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /metrics
              port: 9115
            initialDelaySeconds: 5
            periodSeconds: 5
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
```

#### Мониторинг самого экспортера (Self-monitoring)

```yaml
scrape_configs:
  - job_name: 'blackbox-exporter-self'
    static_configs:
      - targets:
        - blackbox-exporter-1.monitoring:9115
        - blackbox-exporter-2.monitoring:9115
        - blackbox-exporter-3.monitoring:9115
    # Метрики самого экспортера (up, blackbox_exporter_*)
```

```yaml
# Алерт на отказ экспортера
groups:
  - name: blackbox-exporter-ha
    rules:
      - alert: BlackboxExporterDown
        expr: up{job="blackbox-exporter-self"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Blackbox Exporter {{ $labels.instance }} недоступен"
          description: "Один из инстансов Blackbox Exporter не отвечает более 2 минут."

      - alert: BlackboxExporterHighLatency
        expr: scrape_duration_seconds{job="blackbox-exporter-self"} > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Медленный ответ Blackbox Exporter {{ $labels.instance }}"
```

### Стратегии распределения проверок

#### Round-Robin (по умолчанию)

Prometheus автоматически распределяет scrape-запросы по всем доступным инстансам job'а.

#### Weighted Distribution (по весу)

Для неравномерных конфигураций (разные мощности инстансов):

```yaml
scrape_configs:
  - job_name: 'blackbox'
    metrics_path: /probe
    static_configs:
      - targets:
        - https://api.example.com
        labels:
          shard: 'heavy'
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        regex: '(.*)'
        target_label: __address__
        replacement: 'blackbox-${1}:9115'  # Динамический выбор
```

### Сетевые ограничения и DDoS-профилактика

При масштабировании важно контролировать влияние экспортера на целевые сервисы:

| Параметр | Рекомендуемое значение | Описание |
|:---|:---|:---|
| `scrape_interval` | >= 15s | Минимальный интервал проверок |
| `probe_timeout` | < scrape_interval | Таймаут проверки должен быть меньше интервала |
| `max_concurrent_probes` | 100–500 на инстанс | Лимит одновременных проверок |
| `targets_per_job` | < 1000 | Разбивайте большие списки на отдельные jobs |

**Настройка rate limiting в Blackbox Exporter (опционально через reverse proxy):**

```nginx
# nginx.conf для rate limiting
limit_req_zone $binary_remote_addr zone=blackbox:10m rate=100r/s;

server {
    listen 9115;
    location /probe {
        limit_req zone=blackbox burst=50 nodelay;
        proxy_pass http://127.0.0.1:9116;  # Реальный порт экспортера
    }
    location /metrics {
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://127.0.0.1:9116;
    }
}
```

## Дополнительная информация

### Очистка при деинсталляции HA-кластера

```bash
# Kubernetes
kubectl delete deployment blackbox-exporter -n monitoring
kubectl delete service blackbox-exporter -n monitoring
kubectl delete configmap blackbox-config -n monitoring

# Helm
helm uninstall blackbox -n monitoring
```

### Ссылки

- [Установка и настройка](./blackbox_exporter_installation_and_setup.md) — базовая установка
- [Grafana-дашборды](./blackbox_exporter_grafana_dashboards.md) — визуализация результатов

**См. также:**
*   [Обзор и концепции](./blackbox_exporter_overview.md)
*   [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
