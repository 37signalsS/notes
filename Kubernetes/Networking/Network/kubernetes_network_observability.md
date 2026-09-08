# Наблюдаемость сетевого стека в Kubernetes

## Определения

**Network Observability** — совокупность инструментов и практик для мониторинга, визуализации и анализа сетевого трафика в кластере Kubernetes. Обеспечивает видимость East-West (между подами) и North-South (входящий/исходящий) трафика.

**Golden Signals (Золотые сигналы)** — четыре ключевые метрики для мониторинга сетевых сервисов: Latency (задержка), Traffic (объем трафика), Errors (ошибки), Saturation (насыщение).

**Network SLI** — индикатор уровня сервиса сети: доля успешных соединений, P99 задержка, packet loss rate, connection timeout rate.

**Flow Export** — механизм экспорта информации о сетевых потоках (NetFlow/IPFIX) или eBPF-based flow logging (Cilium Hubble) для анализа трафика.

---

## Основные концепции

### Архитектура сетевой наблюдаемости

```
┌─────────────────────────────────────────────────────────────────┐
│                      Grafana Dashboards                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ Network     │  │ CNI         │  │ DNS         │              │
│  │ Overview    │  │ Metrics     │  │ Metrics     │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│  ┌──────┴────────────────┴────────────────┴──────┐              │
│  │              Prometheus / Mimir                │              │
│  └──────────────────────┬────────────────────────┘              │
│                         │                                       │
│  ┌──────────────────────┴────────────────────────┐              │
│  │           ServiceMonitor / PodMonitor          │              │
│  └──────────────────────┬────────────────────────┘              │
└─────────────────────────┼───────────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────────┐
│                    Kubernetes Nodes                              │
│  ┌─────────────┐  ┌─────┴─────┐  ┌─────────────┐              │
│  │ kube-proxy  │  │   CNI     │  │  CoreDNS    │              │
│  │  metrics    │  │  metrics  │  │  metrics    │              │
│  │  :10249     │  │  :9965    │  │  :9153      │              │
│  └─────────────┘  └───────────┘  └─────────────┘              │
│  ┌─────────────┐  ┌───────────┐  ┌─────────────┐              │
│  │ Node Exporter│  │  Hubble   │  │  conntrack  │              │
│  │  (network)  │  │  (Cilium) │  │  exporter   │              │
│  └─────────────┘  └───────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

### Источники метрик

| Компонент | Порт по умолчанию | Протокол | Ключевые метрики |
| :--- | :--- | :--- | :--- |
| **kube-proxy** | 10249 | HTTP `/metrics` | `kube_proxy_sync_proxy_rules_duration_seconds`, `kube_proxy_sync_proxy_rules_total` |
| **CoreDNS** | 9153 | HTTP `/metrics` | `coredns_dns_requests_total`, `coredns_dns_response_rcode_count_total` |
| **Cilium** | 9965 | HTTP `/metrics` | `cilium_datapath_errors_total`, `cilium_endpoint_regeneration_time_seconds` |
| **Node Exporter** | 9100 | HTTP `/metrics` | `node_network_receive_bytes_total`, `node_network_transmit_errors_total` |
| **Hubble** | 9965 | HTTP (Cilium) | `hubble_flows_processed_total`, `hubble_dns_queries_total` |
| **conntrack exporter** | 9120 | HTTP `/metrics` | `conntrack_entries`, `conntrack_limit` |

---

## Практические сценарии

### Сценарий 1: ServiceMonitor для kube-proxy

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kube-proxy-monitoring
  namespace: kube-system
  labels:
    k8s-app: kube-proxy
spec:
  selector:
    matchLabels:
      k8s-app: kube-proxy
  endpoints:
  - port: http-metrics
    path: /metrics
    interval: 30s
    scrapeTimeout: 10s
```

**Ключевые алерты для kube-proxy:**

```yaml
groups:
- name: kube-proxy
  rules:
  - alert: KubeProxySyncLatencyHigh
    expr: histogram_quantile(0.99, rate(kube_proxy_sync_proxy_rules_duration_seconds_bucket[5m])) > 0.5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "kube-proxy: высокая задержка синхронизации правил"
      description: "P99 задержка синхронизации правил kube-proxy превышает 500ms"

  - alert: KubeProxySyncRateZero
    expr: rate(kube_proxy_sync_proxy_rules_total[10m]) == 0
    for: 10m
    labels:
      severity: critical
    annotations:
      summary: "kube-proxy: синхронизация правил остановлена"
      description: "kube-proxy не синхронизирует правила более 10 минут"
```

### Сценарий 2: Мониторинг CoreDNS

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: coredns-monitoring
  namespace: kube-system
spec:
  selector:
    matchLabels:
      k8s-app: kube-dns
  endpoints:
  - port: http-metrics
    path: /metrics
    interval: 15s
```

**Ключевые алерты для CoreDNS:**

```yaml
groups:
- name: coredns
  rules:
  - alert: CoreDNSHighErrorRate
    expr: |
      sum(rate(core_dns_dns_requests_total{rcode="SERVFAIL"}[5m])) by (server)
      / sum(rate(core_dns_dns_requests_total[5m])) by (server) > 0.05
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "CoreDNS: высокий процент ошибок SERVFAIL"
      description: "Более 5% DNS-запросов возвращают SERVFAIL"

  - alert: CoreDNSHighLatency
    expr: histogram_quantile(0.99, rate(core_dns_dns_request_duration_seconds_bucket[5m])) > 0.5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "CoreDNS: высокая задержка ответов"
      description: "P99 задержка CoreDNS превышает 500ms"

  - alert: CoreDNSForwardErrors
    expr: rate(core_dns_forward_responses_total{rcode="SERVFAIL"}[5m]) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "CoreDNS: ошибки пересылки во внешние DNS"
```

### Сценарий 3: Cilium Hubble для flow-level наблюдаемости

```bash
# Установка Cilium с включенным Hubble
helm install cilium cilium/cilium --namespace kube-system \
  --set hubble.enabled=true \
  --set hubble.relay.enabled=true \
  --set hubble.ui.enabled=true \
  --set prometheus.enabled=true \
  --set operator.prometheus.enabled=true

# Включение Hubble в existing Cilium
cilium hubble enable --ui

# Просмотр flow в реальном времени
hubble observe --namespace production --to-namespace production

# Фильтрация по DNS
hubble observe --dns my-service.default.svc.cluster.local

# Фильтрация по verdikt (dropped/allowed)
hubble observe --verdict DROPPED --namespace production

# Топ-10 источников дропов
hubble observe --verdict DROPPED --output json | \
  jq -r '.source.pod' | sort | uniq -c | sort -rn | head -10
```

**Prometheus метрики Hubble:**

```yaml
# ServiceMonitor для Hubble
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: hubble-monitoring
  namespace: kube-system
spec:
  selector:
    matchLabels:
      k8s-app: cilium
  endpoints:
  - port: hubble-metrics
    path: /metrics
    interval: 15s
    metricRelabelings:
    - sourceLabels: [__name__]
      regex: 'hubble_.*'
      action: keep
```

**Ключевые алерты Hubble:**

```yaml
groups:
- name: hubble
  rules:
  - alert: HubbleHighDropRate
    expr: |
      sum(rate(hubble_flows_processed_total{verdict="DROPPED"}[5m])) by (source_namespace, destination_namespace)
      / sum(rate(hubble_flows_processed_total[5m])) by (source_namespace, destination_namespace) > 0.1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Hubble: высокий процент отброшенных пакетов"
      description: "Более 10% пакетов отброшены между {{ $labels.source_namespace }} и {{ $labels.destination_namespace }}"

  - alert: HubbleDNSErrors
    expr: sum(rate(hubble_dns_queries_total{rcode!="NOERROR"}[5m])) by (namespace) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Hubble: ошибки DNS в namespace {{ $labels.namespace }}"
```

### Сценарий 4: Мониторинг conntrack

```yaml
# Установка conntrack-exporter (community chart)
helm install conntrack-exporter prometheus-community/prometheus-conntrack-exporter \
  --namespace monitoring \
  --set conntrack.metrics.conntrack_entries.enabled=true \
  --set conntrack.metrics.conntrack_limit.enabled=true
```

**Ключевые алерты conntrack:**

```yaml
groups:
- name: conntrack
  rules:
  - alert: ConntrackTableNearFull
    expr: node_nf_conntrack_entries / node_nf_conntrack_entries_limit > 0.8
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "conntrack: таблица заполнена более чем на 80%"
      description: "Таблица conntrack заполнена на {{ $value | humanizePercentage }}"

  - alert: ConntrackTableFull
    expr: node_nf_conntrack_entries / node_nf_conntrack_entries_limit > 0.95
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "conntrack: таблица почти заполнена"
      description: "Таблица conntrack заполнена на {{ $value | humanizePercentage }} — риск потери соединений"
```

### Сценарий 5: Мониторинг сетевых ошибок на узлах

```yaml
# Метрики Node Exporter для сети
groups:
- name: node_network
  rules:
  - alert: NodeNetworkInterfaceErrors
    expr: rate(node_network_receive_errs_total[5m]) > 0 or rate(node_network_transmit_errs_total[5m]) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Сетевые ошибки на интерфейсе {{ $labels.device }}"
      description: "Узел {{ $labels.instance }}: ошибки приема/передачи на интерфейсе {{ $labels.device }}"

  - alert: NodeNetworkHighSaturation
    expr: |
      node_network_receive_bytes_total / (node_network_speed_bytes > 0) > 0.8
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Высокая загрузка сетевого интерфейса"
      description: "Интерфейс {{ $labels.device }} на {{ $labels.instance }} загружен более чем на 80%"
```

---

## Дополнительная информация

### Типичные проблемы и их обнаружение

| Проблема | Метрика для обнаружения | Алерт |
| :--- | :--- | :--- |
| conntrack table full | `node_nf_conntrack_entries / node_nf_conntrack_entries_limit` | > 80% warning, > 95% critical |
| DNS resolution failures | `rate(core_dns_dns_requests_total{rcode="SERVFAIL"}[5m])` | > 5% от общего числа |
| kube-proxy sync lag | `kube_proxy_sync_proxy_rules_duration_seconds` | P99 > 500ms |
| Network policy blocking | `hubble_flows_processed_total{verdict="DROPPED"}` | Drop rate > 10% |
| MTU mismatch | TCP retransmits + small packet drops | `rate(node_netstat_TcpExt_TCPLostRetransmit[5m])` > 0 |
| High latency between pods | `histogram_quantile(0.99, rate(hubble_flows_processed_total_bucket[5m]))` | > 100ms |

### Интеграция с Grafana

**Рекомендуемые дашборды:**

1. **Kubernetes Cluster Monitoring** (ID: 7249) — обзор сетевых метрик кластера
2. **CoreDNS** (ID: 15661) — мониторинг DNS
3. **Cilium** (ID: 16612) — eBPF/Hubble метрики
4. **Node Exporter Full** (ID: 1860) — сетевые метрики узлов

**Создание кастомного дашборда для сети:**

```json
{
  "panels": [
    {
      "title": "conntrack Usage",
      "type": "gauge",
      "targets": [{
        "expr": "node_nf_conntrack_entries / node_nf_conntrack_entries_limit",
        "legendFormat": "{{ instance }}"
      }],
      "fieldConfig": {
        "defaults": {
          "thresholds": {
            "steps": [
              { "value": 0, "color": "green" },
              { "value": 0.8, "color": "yellow" },
              { "value": 0.95, "color": "red" }
            ]
          }
        }
      }
    },
    {
      "title": "DNS Error Rate",
      "type": "timeseries",
      "targets": [{
        "expr": "sum(rate(core_dns_dns_requests_total{rcode=\"SERVFAIL\"}[5m])) by (server)",
        "legendFormat": "{{ server }}"
      }]
    }
  ]
}
```

### Рекомендации для production

1. **Включите ServiceMonitor/PodMonitor** для всех критических компонентов сети (kube-proxy, CoreDNS, CNI)
2. **Настройте алерты** на conntrack saturation, DNS errors, kube-proxy sync latency
3. **Используйте Hubble** (Cilium) для flow-level visibility в real-time
4. **Мониторьте сетевые ошибки** на узлах через Node Exporter
5. **Настройте retention** для flow-данных (Hubble Timescape или NetFlow collector)
6. **Интегрируйте с Incident Management** (PagerDuty, Opsgenie) для критических алертов

### См. также

- [Обзор архитектуры наблюдаемости](../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — общий подход
- [Cilium: Hubble](./CNI/cilium.md#наблюдаемость-hubble-и-timescape) — eBPF-based flow monitoring
- [kube-proxy: метрики](./kube-proxy.md) — detailed kube-proxy metrics
- [DNS в Kubernetes](../dns_deep_dive.md) — CoreDNS конфигурация и метрики
- [NetFlow/IPFIX](../../../Networking/Concepts/sdn/netflow.md) — классический flow monitoring
