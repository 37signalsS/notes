# CRD Probe

## Definitions

**`kind: Probe`** — Custom Resource Definition в Prometheus Operator для описания blackbox-мониторинга внешних эндпоинтов через Blackbox Exporter. Позволяет декларативно управлять проверками доступности HTTP/TCP/ICMP/DNS из кластера Kubernetes.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Blackbox Exporter — обзор](../../../Exporters/blackbox/blackbox_exporter_overview.md), [Конфигурация модулей](../../../Exporters/blackbox/blackbox_exporter_modules_configuration.md).

## Basic Concepts

### Принцип работы

1. Prometheus Operator находит Probe CRD по label selector
2. Генерирует `scrape_config` с target-параметрами для Blackbox Exporter
3. Prometheus опрашивает Blackbox Exporter на эндпоинте `/probe`
4. Exporter выполняет проверку целевого эндпоинта и возвращает метрики (`probe_success`, `probe_duration_seconds` и др.)
5. `prometheus-config-reloader` перезагружает конфигурацию при изменениях

**Поток запросов:**

```
Prometheus → http://blackbox-exporter:9115/probe?target=<цель>&module=<модуль>
Blackbox Exporter → проверяет целевой эндпоинт
Blackbox Exporter → возвращает метрики: probe_success, probe_http_status_code, ...
```

> **Важно:** Prometheus скрейпит не целевой эндпоинт напрямую, а Blackbox Exporter, который выполняет проверку и возвращает метрики результата.

### Когда использовать Probe

| Сценарий | Решение |
|---|---|
| **Внешние эндпоинты** | HTTPS-сайты, внешние API |
| **Проверка доступности из кластера** | Как видят сервисы изнутри Kubernetes |
| **TCP-порты внешних систем** | Базы данных, очереди за пределами кластера |
| **ICMP/DNS проверки** | Доступность узлов, разрешение имён |
| **Ingress-мониторинг** | Автоматическая проверка всех Ingress по селектору |

### Типы источников целей

| Тип | Описание | Пример |
|---|---|---|
| **`staticConfig`** | Статический список целей | `[https://example.com, 8.8.8.8]` |
| **`ingress`** | Автоматическое обнаружение Ingress | `selector: {matchLabels: {probe: true}}` |

### Доступные meta-лейблы для Probe

| Meta-лейбл | Описание |
|---|---|
| `__address__` | Адрес Blackbox Exporter (заменяется через relabeling) |
| `__param_target` | Целевой эндпоинт (передаётся как параметр `/probe?target=`) |
| `__param_module` | Используемый модуль |
| `__meta_kubernetes_ingress_host` | Host из Ingress (при `targets.ingress`) |
| `__meta_kubernetes_namespace` | Namespace Probe CRD |
| `__meta_kubernetes_probe_name` | Имя Probe CRD |

## Practical Scenarios

### Базовая проверка HTTPS

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
  interval: 30s
  scrapeTimeout: 10s
  targets:
    staticConfig:
      static:
        - https://google.com
        - https://example.com
```

### Проверка нескольких endpoints с лейблами

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

### ICMP-проверка доступности узлов

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

### Проверка TCP-портов

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

### Мониторинг через Ingress selector

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

### Relabeling — подмена адресов

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

## Additional Information

### Основные параметры spec

| Параметр | Описание | Пример |
|---|---|---|
| **`prober.url`** | URL Blackbox Exporter | `blackbox-exporter.monitoring.svc.cluster.local:9115` |
| **`prober.path`** | Путь к endpoint | `/probe` (по умолчанию) |
| **`prober.scheme`** | Протокол | `http`, `https` |
| **`module`** | Модуль blackbox | `http_2xx`, `http_post_2xx`, `tcp_connect`, `icmp` |
| **`targets.staticConfig.static`** | Статические цели | `[https://example.com]` |
| **`targets.staticConfig.labels`** | Лейблы для целей | `{environment: production}` |
| **`targets.ingress.selector`** | Селектор Ingress | `matchLabels: {probe: true}` |
| **`interval`** | Интервал проверки | `30s`, `1m` |
| **`scrapeTimeout`** | Тайм-аут проверки | `10s` |
| **`relabelingConfigs`** | Relabeling правил для целей | См. пример выше |

### Типы модулей

| Тип | Модуль | Назначение |
|---|---|---|
| **HTTP** | `http_2xx` | Проверка HTTP 200 |
| **HTTP POST** | `http_post_2xx` | HTTP POST с проверкой 200 |
| **HTTP HEAD** | `http_head_2xx` | HTTP HEAD с проверкой 200 |
| **TCP** | `tcp_connect` | Проверка открытия TCP-порта |
| **ICMP** | `icmp` | Ping-проверка |
| **DNS** | `dns_tcp_query`, `dns_udp_query` | DNS query over TCP/UDP |

> **Конфигурация модулей** описана в SSoT: [Blackbox Exporter — конфигурация модулей](../../../Exporters/blackbox/blackbox_exporter_modules_configuration.md).

### Метрики и алертинг

> Метрики Blackbox Exporter и примеры правил оповещения описаны в SSoT: [Метрики и алертинг](../../../Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md).

### Связанные CRD

- [ServiceMonitor](./servicemonitor.md) — мониторинг через Service
- [PodMonitor](./podmonitor.md) — мониторинг подов напрямую
- [Prometheus CRD](./prometheus.md) — описание экземпляра Prometheus
