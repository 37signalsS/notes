# Мониторинг и алертинг Unikernel

**Актуально для:** Unikraft v0.21.0, KraftKit v0.12.15, Nanos (актуальная ветка), MirageOS v4.11.x, OSv v0.57.0; примеры для on-premise развёртываний

## Определения

**Мониторинг и алертинг юникернелов** — это совокупность методов сбора метрик, логов и трейсов из юникернелов и их хостовой среды, а также правил оповещения при деградации сервиса. В отличие от контейнеров, юникернелы не поддерживают запуск агентов мониторинга внутри себя, поэтому применяется подход **Sidecar-less Observability**: сбор данных на стороне хоста через eBPF, OpenTelemetry SDK в коде приложения и перехват stdout гипервизором.

Базовая информация — в [Обзоре Unikernel](./unikernel_overview.md).

## Предварительные требования

### Аппаратные требования (хост)

- **Процессор:** Intel VT-x или AMD-V (обязательно для KVM). Проверка: `grep -E 'vmx|svm' /proc/cpuinfo`
- **RAM:** Минимум 4 ГБ свободной RAM для стека мониторинга (Prometheus + Grafana + Loki). На каждый юникернел — от 64 МБ.
- **Диск:** 10 ГБ для TSDB Prometheus и чанков Loki. Рекомендуется SSD/NVMe.

### Программные требования (on-premise, Linux хост)

| Компонент | Требование | Проверка |
| :--- | :--- | :--- |
| **Ядро Linux** | 5.10+ (для KVM и eBPF) | `uname -r` |
| **Гипервизор** | KVM/QEMU | `ls -la /dev/kvm` |
| **Доступ к KVM** | Пользователь в группе `kvm` | `groups \| grep kvm` |
| **Сетевые инструменты** | `ip`, `iptables`, `bridge-utils`, `bpftrace` | `bpftrace -l \| head -1` |
| **Prometheus** | v3.x (рекомендуется) или v2.x | `prometheus --version` |
| **Grafana** | v11+ | `grafana-server -v` |
| **Loki** | v3.x | `loki -version` |
| **OpenTelemetry Collector** | v0.110+ | `otelcol --version` |
| **Node Exporter** | v1.12+ | `node_exporter --version` |
| **Vector** | v0.34+ (для сбора логов) | `vector --version` |

### Установка базового стека (Debian/Ubuntu)

```bash
# Node Exporter
NODE_EXPORTER_VERSION=1.12.1
wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xzf node_exporter-*.tar.gz
sudo cp node_exporter-*/node_exporter /usr/local/bin/
sudo systemctl enable --now node_exporter

# Проверка
curl http://localhost:9100/metrics | grep node_cpu
# → node_cpu_seconds_total{cpu="0",mode="idle",...} 1234.56
```

## Основные концепции

### Архитектура наблюдения

```
┌─────────────────────────────────────────┐
│  Юникернел (QEMU VM)                   │
│  ┌─────────────┐  ┌──────────────────┐ │
│  │ Приложение  │  │ Library OS       │ │
│  │ (OTel SDK)  │  │ (нет shell/агент)│ │
│  └──────┬──────┘  └────────┬─────────┘ │
│         │ stdout/stderr    │            │
└─────────┼──────────────────┼────────────┘
           │                  │
           ▼                  ▼
┌─────────────────────────────────────────┐
│  Хост (Linux)                          │
│  ┌─────────────┐  ┌──────────────────┐ │
│  │ Hypervisor  │  │ eBPF/kprobes     │ │
│  │ (QEMU/KVM)  │  │ (bpftrace)       │ │
│  └──────┬──────┘  └────────┬─────────┘ │
│         │                  │            │
│  ┌──────┴──────────────────┴─────────┐ │
│  │  OpenTelemetry Collector          │ │
│  │  (OTLP gRPC: 4317, HTTP: 4318)    │ │
│  └──────┬────────────────────────────┘ │
│         │                            │
│  ┌──────┴────────────────────────────┐ │
│  │  Prometheus (scrape: 9100)        │ │
│  │  Loki (logs)                      │ │
│  │  Grafana (UI)                     │ │
│  └───────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Три сигнала надёжности (Golden Signals)

| Сигнал | Метрика | Источник |
| :--- | :--- | :--- |
| **Трафик** | RPS, соединения | OTel SDK → Prometheus |
| **Ошибки** | 5xx rate, panic rate | OTel SDK + гипервизор logs |
| **Задержка** | p50/p99 latency | OTel SDK → Prometheus |
| **Насыщение** | RAM, CPU, сеть | Node Exporter + eBPF |

### SLO/SLI/SLA для юникернелов

**SLI (Service Level Indicator):**
- Доступность: доля успешных HTTP-ответов 2xx/3xx
- Задержка: p99 latency < 100 мс
- Пропускная способность: RPS > 1000

**SLO (Service Level Objective):**
- 99.9% успешных запросов за 30 дней
- p99 latency < 100 мс для 99.5% запросов
- Error budget: 0.1% = ~43 минуты простоя в месяц

**SLA (Service Level Agreement):**
- Контракт с пользователем: 99.9% доступности
- Штрафы при нарушении SLA

## Практические сценарии

### 1. Сбор метрик

#### OpenTelemetry SDK в приложении

```python
# Пример: Python-приложение с OTel
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

# Трейсы
provider = TracerProvider()
processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="host-ip:4317", insecure=True))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

# Метрики
reader = PeriodicExportingMetricReader(
  OTLPMetricExporter(endpoint="host-ip:4317", insecure=True),
  export_interval_millis=5000
)
meter_provider = MeterProvider(metric_readers=[reader])
meter = meter_provider.get_meter("my-service")

# Кастомная метрика
request_counter = meter.create_counter(
  "http_requests_total",
  description="Total HTTP requests"
)

# Использование в коде
request_counter.add(1, {"method": "GET", "status": "200"})
```

#### eBPF-мониторинг на хосте

```bash
# Мониторинг сетевых пакетов юникернела через TAP-интерфейс
sudo bpftrace -e '
kprobe:virtio_net_xmit {
    printf("TX: %s -> %d bytes\n", comm, arg1);
}'

# Мониторинг времени выполнения VMM
sudo bpftrace -e '
kretprobe:kvm_vcpu_ioctl {
    @us = hist(nsecs - @start[pid]);
    delete(@start[pid]);
}'
```

#### Метрики хоста (Node Exporter)

```bash
# Установка Node Exporter
NODE_EXPORTER_VERSION=1.12.1
wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xzf node_exporter-*.tar.gz
sudo cp node_exporter-*/node_exporter /usr/local/bin/

# Запуск
sudo systemctl enable --now node_exporter

# Проверка
curl http://localhost:9100/metrics | grep qemu
# → node_cpu_seconds_total{cpu="0",mode="idle",...} 1234.56
```

### 2. Prometheus правила

#### Recording Rules

```yaml
# /etc/prometheus/rules/unikernel_recording.yml
groups:
  - name: unikernel
    rules:
      # Доступность
      - record: unikernel:request_rate:rate5m
        expr: sum(rate(http_requests_total[5m])) by (service, instance)

      - record: unikernel:error_rate:rate5m
        expr: sum(rate(http_requests_total{status=~"5.."}[5m])) by (service, instance)

      - record: unikernel:error_ratio:rate5m
        expr: unikernel:error_rate:rate5m / unikernel:request_rate:rate5m

      # Latency
      - record: unikernel:latency_p99:rate5m
        expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service, instance))

      # Ресурсы
      - record: unikernel:memory_usage_bytes
        expr: sum(process_resident_memory_bytes{job="unikernel"}) by (service, instance)

      - record: unikernel:cpu_usage_seconds:rate5m
        expr: sum(rate(process_cpu_seconds_total[5m])) by (service, instance)
```

#### Alerting Rules

```yaml
# /etc/prometheus/rules/unikernel_alerts.yml
groups:
  - name: unikernel
    rules:
      # Доступность
      - alert: UnikernelHighErrorRate
        expr: unikernel:error_ratio:rate5m > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate for {{ $labels.service }}"
          description: "Error rate is {{ $value | humanizePercentage }} (threshold: 5%)"

      - alert: UnikernelDown
        expr: up{job="unikernel"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Unikernel {{ $labels.instance }} is down"

      # Latency
      - alert: UnikernelHighLatency
        expr: unikernel:latency_p99:rate5m > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High latency for {{ $labels.service }}"
          description: "P99 latency is {{ $value | humanizeDuration }} (threshold: 100ms)"

      # Ресурсы
      - alert: UnikernelHighMemory
        expr: unikernel:memory_usage_bytes > 256 * 1024 * 1024
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage for {{ $labels.instance }}"
          description: "Memory usage is {{ $value | humanizeBytes }} (threshold: 256MB)"

      - alert: UnikernelHighCPU
        expr: unikernel:cpu_usage_seconds:rate5m > 2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage for {{ $labels.instance }}"
          description: "CPU usage is {{ $value | humanizeNumber }} cores (threshold: 2)"
```

### 3. Grafana дашборды

#### Provisioning

```yaml
# /etc/grafana/provisioning/dashboards/unikernel.yml
apiVersion: 1

providers:
  - name: unikernel
    type: file
    options:
      path: /var/lib/grafana/dashboards/unikernel
      foldersFromFilesStructure: true
```

#### JSON-дашборд (фрагмент)

```json
{
  "dashboard": {
    "title": "Unikernel Overview",
    "uid": "unikernel-overview",
    "panels": [
      {
        "title": "Request Rate",
        "targets": [
          {
            "expr": "sum(rate(http_requests_total[5m])) by (service)",
            "legendFormat": "{{ service }}"
          }
        ],
        "type": "graph"
      },
      {
        "title": "P99 Latency",
        "targets": [
          {
            "expr": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))",
            "legendFormat": "{{ service }}"
          }
        ],
        "type": "graph",
        "thresholds": [
          {
            "value": 0.1,
            "color": "red"
          }
        ]
      }
    ]
  }
}
```

### 4. Сбор логов

#### stdout → гипервизор → Loki

```bash
# Unikraft: перехват console-output
kraft run --headless --background -p 8080:80 \
  --log-file /var/log/unikernel/my-service.log 2>&1

# Loki: Vector для сбора логов
# /etc/vector/vector.toml
[sources.unikernel_logs]
  type = "file"
  include = ["/var/log/unikernel/*.log"]
  ignore_older = 3600

[transforms.parse_logs]
  type = "remap"
  inputs = ["unikernel_logs"]
  source = '''
  .service = "unikernel"
  .level = "info"
  '''

[sinks.loki]
  type = "loki"
  inputs = ["parse_logs"]
  endpoint = "http://loki:3100"
```

### 5. Алертинг и уведомления

#### Alertmanager конфигурация

```yaml
# /etc/alertmanager/alertmanager.yml
route:
  group_by: ['service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'team-notifications'

receivers:
  - name: 'team-notifications'
    slack_configs:
      - channel: '#unix-alerts'
        api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
    email_configs:
      - to: 'unix-team@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
```

### 6. SLO Budget Burn Rate

```yaml
# Alerting rules based on burn rate
- alert: UnikernelErrorBudgetBurnRateHigh
  expr: |
    (
      sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
      /
      sum(rate(http_requests_total[5m])) by (service)
    ) > (14.4 * 0.001)  # 14.4x burn rate for 99.9% SLO
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Error budget burning fast for {{ $labels.service }}"
```

## Лучшие практики

### Проектирование системы мониторинга

- **Отдельный хост для стека:** Разворачивайте Prometheus, Loki и Grafana на выделенном хосте или в отдельном сегменте сети. Изоляция предотвращает «шум» от юникернелов в метриках самого мониторинга.
- **Внешний watchdog:** Настройте Dead Man's Switch через Healthchecks.io (self-hosted) или Uptime Kuma для проверки всей цепочки: от сбора данных до доставки уведомления.
- **Синхронизация времени:** NTP-рассинхронизация > 1 секунды приводит к ложным срабатываниям watchdog и неверным расчётам ingestion lag. Используйте chrony с `makestep 1.0 3`.
- **Ограничение кардинальности:** Юникернелы могут создавать тысячи инстансов. Используйте `metric_relabel_configs` в Prometheus для отсечения избыточных лейблов (например, `instance` → только имя сервиса).

### Наблюдаемость юникернелов

- **Обязательная OTel-интеграция на этапе разработки:** Добавьте OpenTelemetry SDK до сборки юникернела. Без этого инстанс становится «чёрным ящиком».
- **Health check endpoint:** Реализуйте HTTP-endpoint `/health`, проверяемый с хоста через `curl` или HTTP-пробу. Это позволяет hypervisor и orchestrator обнаруживать unhealthy инстансы.
- **Структурированные логи:** Приложение должно писать в stdout в формате JSON или key=value. Избегайте неструктурированного вывода — его дорого парсить Vector'у.
- **eBPF как запасной вариант:** Настройте bpftrace-скрипты на хосте для сбора сетевых метрик, если OTel SDK недоступен (legacy-приложения).

### Производительность и стабильность

- **Scrape interval для хоста:** 15–30 секунд. Для критичных сервисов — 5 секунд, но учитывайте нагрузку на TSDB.
- **Retention policies:** Prometheus — 30 дней (локальный TSDB) + долгосрочное хранение в VictoriaMetrics/Thanos. Loki — 7 дней для hot-чанков, 30 дней в S3.
- **Alert deduplication:** Используйте `group_by: ['service', 'instance']` в Alertmanager, но ограничьте `group_wait: 30s` для критичных алертов.
- **Runbook для каждого алерта:** Каждое правило алертинга должно иметь аннотацию `runbook_url` с ссылкой на инструкцию по реагированию.

### Безопасность

- **Изоляция стека мониторинга:** Разместите компоненты в отдельном VLAN. Ограничьте доступ к `/metrics` только сетью мониторинга через `iptables`/`nftables`.
- **mTLS между компонентами:** Включите TLS для Prometheus → Alertmanager и OTel Collector → Prometheus. Используйте самоподписанные сертификаты в on-premise среде.
- **Ротация credentials:** Пароли для Alertmanager, SMTP и webhook'ов храните в HashiCorp Vault или ансамбле, а не в конфигурационных файлах.
- **Аудит конфигурации:** Все изменения правил Prometheus и конфигурации Alertmanager коммитьте в Git. Используйте `promtool check rules` в CI/CD пайплайне.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Метрики не появляются в Prometheus** | OTel SDK не настроен или firewall блокирует 4317/4318 | Проверить `otelcol --config otel-collector.yaml`, убедиться что приложение отправляет на `host-ip:4317`. Проверить: `ss -tnp \| grep 4317` |
| **High cardinality в Prometheus** | Слишком много уникальных лейблов (например, IP-адреса в `instance`) | Применить `metric_relabel_configs` для отсечения динамических лейблов. Ограничить `max_series_per_target`. |
| **Логи не доходят до Loki** | Vector не может прочитать файл или Loki переполнен | Проверить права на `/var/log/unikernel/*.log`, `vector buffer_utilization` (должна быть < 0.8), `loki_ingester_memory_chunks`. |
| **eBPF-пробы не работают** | Ядро собрано без CONFIG_BPF или нет прав root | Проверить `bpftrace -l \| head -1`. Установить `linux-headers-$(uname -r)` и перезагрузиться. |
| **Alertmanager не отправляет уведомления** | Неверный webhook URL или SMTP заблокирован | Проверить `amtool alert --pending`, логи Alertmanager (`journalctl -u alertmanager`), доступность эндпоинта: `curl -v https://hooks.slack.com/...` |
| **P99 latency растёт, но RPS стабилен** | Насыщение RAM или CPU на хосте | Проверить `ps aux \| grep qemu`, `virt-top`, `top`. Увеличить выделенную RAM или добавить хостов. |
| **"Black box" — инстанс не отвечает** | Приложение слушает на 127.0.0.1 или упало | Проверить с хоста: `curl -s -o /dev/null -w "%{http_code}" http://10.0.0.2:8080/health`. Если 000 — перезапустить через `kraft restart`. |
| **Prometheus не собирает метрики OTel** | OTLP endpoint неверный или Collector упал | Проверить `otelcol --config otel-collector.yaml`, `ss -tnp \| grep 4317`, логи Collector: `journalctl -u otel-collector`. |
| **Grafana показывает пустые панели** | Неверный datasource URL или переменная `$service` пустая | Проверить `Data Sources` в Grafana UI, убедиться что Prometheus возвращает данные: `curl "http://prometheus:9090/api/v1/query?query=up"`. |
| **Watchdog алерт не доходит** | External watchdog недоступен или Alertmanager не routing'ирует | Проверить доступность внешнего эндпоинта: `curl -v https://healthchecks.io/ping/...`. Проверить `route` в Alertmanager. |
| **Node Exporter возвращает stale метрики** | Scrape timeout слишком мал или target перегружен | Увеличить `scrape_timeout` в Prometheus до 30s. Проверить нагрузку на хост: `top`, `iostat`. |

## Валидация и проверка работоспособности

- **Prometheus targets:** `curl http://prometheus:9090/targets` — все юникернелы Up.
- **Alertmanager:** `amtool alert --pending` — нет неподтверждённых алертов.
- **Grafana:** `curl http://grafana:3000/api/health` — healthy.
- **Логи:** `curl -s http://loki:3100/ready` — ready.
- **eBPF:** `sudo bpftrace -l | grep virtio_net` — пробы доступны.
- **OTel Collector:** `curl http://otel-collector:13133/health` — healthy.
- **Node Exporter:** `curl http://localhost:9100/metrics | head -5` — метрики поступают.
- **Watchdog:** Проверить что внешний watchdog получил heartbeat за последние N минут.

### Проверка end-to-end

```bash
# 1. Запустить юникернел с OTel SDK
kraft run --headless --background -p 8080:80 --log-file /var/log/unikernel/my-service.log

# 2. Проверить что метрики поступают в Prometheus
sleep 10
curl -s "http://prometheus:9090/api/v1/query?query=up{job=\"unikernel\"}" | jq '.data.result | length'
# → 1 (или больше, если несколько инстансов)

# 3. Проверить алерты
amtool alert --pending
# → (пусто = нет активных алертов)

# 4. Проверить логи в Loki
curl -s "http://loki:3100/loki/api/v1/query?query={service=\"unikernel\"}" | jq '.data.result | length'
# → ≥ 0 (если логи shipped)

# 5. Проверить Grafana дашборд
curl -s http://grafana:3000/api/dashboards/uid/unikernel-overview | jq '.dashboard.title'
# → "Unikernel Overview"
```

## Дополнительная информация

### См. также
- [Обзор Unikernel](./unikernel_overview.md)
- [Оркестрация и управление](./orchestration_and_management.md)
- [Сеть: продвинутые сценарии](./networking_advanced.md)
- [Производительность и тюнинг](./performance_tuning.md)

### Ссылки
- [OpenTelemetry: Инструментация](../../OpenTelemetry/instrumentation_sdk.md)
- [eBPF для наблюдаемости](../../Kubernetes/Networking/Network/CNI/ebpf.md)
- [Prometheus — promtool и лучшие практики](../../Prometheus/promtool_and_best_practices.md)
- [Grafana — provisioning](../../Grafana/grafana_provisioning.md)
- [Grafana — алертинг](../../Grafana/alerting/concepts.md)
- [Alertmanager — конфигурация](../../Prometheus/alertmanager.md)
- [SRE concepts: SLA, SLO, SLI](../../Concepts/sre_concepts_main.md)
- [Мета-мониторинг](../../Concepts/Observability_and_Monitoring/meta-monitoring.md)
- [KVM — мониторинг](../../Linux/Virtualization/kvm/kvm_monitoring.md)
