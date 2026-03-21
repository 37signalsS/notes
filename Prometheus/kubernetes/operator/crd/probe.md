# CRD Probe

## Определения

**`kind: Probe`** — Custom Resource Definition для описания blackbox-мониторинга через Blackbox Exporter.

## Пример конфигурации

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: google-probe
  namespace: monitoring
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    staticConfig:
      static:
        - https://google.com
        - https://example.com
```

## Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`prober.url`** | URL Blackbox Exporter | `blackbox-exporter.monitoring.svc.cluster.local:9115` |
| **`prober.path`** | Путь к endpoint | `/probe` (по умолчанию) |
| **`prober.scheme`** | Протокол | `http`, `https` |
| **`module`** | Модуль blackbox | `http_2xx`, `http_post_2xx`, `tcp_connect`, `icmp` |
| **`targets.staticConfig.static`** | Статические цели | `[https://example.com]` |
| **`targets.staticConfig.labels`** | Лейблы для целей | `{environment: production}` |
| **`targets.ingress.selector`** | Селектор Ingress | `matchLabels: {probe: true}` |
| **`interval`** | Интервал проверки | `30s`, `1m` |
| **`scrapeTimeout`** | Тайм-аут проверки | `10s` |

## Типы модулей

### HTTP-проверки

```yaml
module: http_2xx          # Проверка HTTP 200
module: http_post_2xx     # HTTP POST с проверкой 200
module: http_head_2xx     # HTTP HEAD с проверкой 200
```

### TCP-проверки

```yaml
module: tcp_connect       # Проверка TCP-соединения
```

### ICMP-проверки

```yaml
module: icmp              # Ping-проверка
```

### DNS-проверки

```yaml
module: dns_tcp_query     # DNS query over TCP
module: dns_udp_query     # DNS query over UDP
```

## Примеры конфигураций

### 1. Проверка HTTPS endpoint

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: api-health-check
  namespace: monitoring
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
    path: /probe
    scheme: http
  module: http_2xx
  interval: 30s
  scrapeTimeout: 10s
  targets:
    staticConfig:
      static:
        - https://api.example.com/health
        - https://api.example.com/ready
      labels:
        environment: production
        team: backend
```

### 2. Проверка доступности доменов (ICMP)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: icmp-probe
  namespace: monitoring
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: icmp
  interval: 1m
  targets:
    staticConfig:
      static:
        - 8.8.8.8
        - 1.1.1.1
        - example.com
```

### 3. Проверка TCP-портов

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: tcp-port-check
  namespace: monitoring
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: tcp_connect
  interval: 30s
  targets:
    staticConfig:
      static:
        - database.example.com:5432
        - redis.example.com:6379
        - kafka.example.com:9092
```

### 4. Проверка через Ingress

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: ingress-probe
  namespace: monitoring
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  interval: 1m
  targets:
    ingress:
      selector:
        matchLabels:
          probe: true
      namespaceSelector:
        any: true
      relabelingConfigs:
        - sourceLabels: [__meta_kubernetes_ingress_host]
          targetLabel: __param_target
```

## Релейблинг

```yaml
spec:
  targets:
    staticConfig:
      static:
        - https://example.com
      labels:
        environment: production
  relabelingConfigs:
    - sourceLabels: [__address__]
      targetLabel: __param_target
    - sourceLabels: [__param_target]
      targetLabel: instance
    - targetLabel: __address__
      replacement: blackbox-exporter.monitoring.svc.cluster.local:9115
```

## Метрики Blackbox Exporter

| Метрика | Описание |
| :--- | :--- |
| `probe_success` | 1 если проверка успешна, 0 иначе |
| `probe_duration_seconds` | Длительность проверки |
| `probe_http_status_code` | HTTP статус код |
| `probe_ssl_earliest_cert_expiry` | Истечение SSL-сертификата |
| `probe_tcp_connect_duration_seconds` | Длительность TCP-соединения |
| `probe_icmp_duration_seconds` | Длительность ICMP-проверки |

## Связанные темы

* **[Blackbox Exporter](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md)** — установка и настройка
* **[Prometheus CRD](./prometheus.md)** — описание Prometheus
* **[ServiceMonitor](./servicemonitor.md)** — мониторинг через Service
