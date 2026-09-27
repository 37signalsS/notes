# ScrapeConfig — Концепции (CRD)

## Определения

**`kind: ScrapeConfig`** — Custom Resource Definition в Prometheus Operator (v0.65+), предназначенный для декларативного описания произвольных конфигураций скрейпинга, которые не вписываются в модель `ServiceMonitor`/`PodMonitor`. Поддерживает нативный синтаксис `kubernetes_sd_configs`, внешние HTTP SD, Consul SD и OTLP-ресиверы.

**Статический скрейпинг (Static Scrape)** — механизм сбора метрик с фиксированными IP-адресами или DNS-именами, не связанными с Kubernetes Service Discovery. Используется для мониторинга внешних серверов, сетевого оборудования и legacy-систем.

**API version:** `monitoring.coreos.com/v1alpha1`

> **См. также:** [ServiceMonitor CRD](./servicemonitor.md) — мониторинг через Service, [PodMonitor CRD](./podmonitor.md) — мониторинг подов напрямую, [Prometheus CRD](./prometheus.md) — конфигурация сервера.

## Основные концепции

### Зачем нужен ScrapeConfig

`ServiceMonitor` и `PodMonitor` покрывают 90% сценариев мониторинга в Kubernetes. Однако существуют случаи, когда этих ресурсов недостаточно:

- **Внешние цели:** Серверы, не находящиеся в Kubernetes (legacy-системы, сетевое оборудование, облачные ресурсы).
- **Сложные SD:** Требуется использование Consul SD, HTTP SD, DNS SD или `file_sd_configs` с кастомной логикой.
- **OTLP-инжест:** Прием метрик по протоколу OpenTelemetry напрямую через Prometheus 3.0+.
- **Произвольные `scrape_config`:** Секции конфигурации, не покрываемые CRD (например, `metric_relabel_configs` сложной логики или `sample_limit`).

`ScrapeConfig` заменяет устаревший механизм `additionalScrapeConfigs` (секрет с YAML-конфигом) и обеспечивает:

- Декларативное управление через Kubernetes API.
- Валидацию схемы через Admission Webhook / CEL.
- Версионирование и аудит через Git.
- Изоляцию по namespace через RBAC.

### Архитектура интеграции

```text
[ ScrapeConfig CRD ]
        |
        | (Prometheus Operator watch)
        v
[ Operator generates prometheus.yaml ]
        |
        | (config-reloader sidecar)
        v
[ Prometheus Server ]
        |
        | (scrape / metrics endpoint)
        v
[ External Targets / OTLP Endpoints ]
```

1. **Наблюдение (Watch):** Оператор отслеживает создание и изменение `ScrapeConfig` через Kubernetes API.
2. **Генерация конфигурации:** На основе полей `ScrapeConfig` формируется секция `scrape_configs` в `prometheus.yaml`.
3. **Применение:** Обновленная конфигурация записывается в Secret, который монтируется в под Prometheus.
4. **Перезагрузка:** `config-reloader` обнаруживает изменение Secret и отправляет `/-/reload`.

### Структура спецификации

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-metrics
  namespace: monitoring
spec:
  scrapeInterval: 30s
  scrapeTimeout: 10s
  staticConfigs:         # Статический список целей
  fileSDConfigs:         # Файлы с целями (JSON/YAML)
  httpSDConfigs:         # HTTP-сервис discovery
  consulSDConfigs:       # Consul service discovery
  kubernetesSDConfigs:   # Нативный K8s SD (v0.72+)
  basicAuth:             # Аутентификация
  authorization:
  oauth2:
  tlsConfig:
  metricsPath: /metrics
  scrapeProtocols:
  honorLabels: true
  honorTimestamps: true
  relabelings:
  metricRelabelings:
  sampleLimit:
  seriesLimit:
```

### Типы discovery

| Тип discovery | Поле | Описание | Пример использования |
|:---|:---|:---|:---|
| **Static** | `staticConfigs` | Фиксированный список IP/DNS | Внешние серверы, БД |
| **File SD** | `fileSDConfigs` | Цели из JSON/YAML файлов | Динамические списки из CI/CD |
| **HTTP SD** | `httpSDConfigs` | Цели с HTTP-эндпоинта | Внешние реестры сервисов |
| **Consul SD** | `consulSDConfigs` | Consul service catalog | Микросервисы в Consul |
| **Kubernetes SD** | `kubernetesSDConfigs` | Нативный K8s API | Сложные K8s-сценарии |

### Сравнение с ServiceMonitor/PodMonitor

| Характеристика | ScrapeConfig | ServiceMonitor | PodMonitor |
|:---|:---|:---|:---|
| **Внешние цели** | Полная поддержка | Нет | Нет |
| **OTLP-инжест** | Да (v0.72+) | Нет | Нет |
| **Consul/HTTP SD** | Да | Нет | Нет |
| **Валидация** | Admission Webhook | Admission Webhook | Admission Webhook |
| **API version** | `v1alpha1` | `v1` | `v1` |
| **Сложность** | Высокая | Низкая | Низкая |
| **Рекомендация** | Только для сложных случаев | Основной выбор | Когда нет Service |

### Когда использовать ScrapeConfig

- **Внешние серверы:** Мониторинг legacy-систем, БД, микросервисов вне Kubernetes.
- **Сетевое оборудование:** Роутеры, коммутаторы через SNMP Exporter.
- **OTLP-инжест:** Прием метрик от OpenTelemetry Collector без промежуточного адаптера.
- **Сложные relabeling:** Когда стандартные поля ServiceMonitor/PodMonitor не покрывают потребности.
- **Консолидация:** Когда `additionalScrapeConfigs` в Secret становится неуправляемым.

### Когда НЕ использовать ScrapeConfig

- **Стандартные K8s-приложения:** Используйте `ServiceMonitor` — проще и декларативнее.
- **Поды без Service:** Используйте `PodMonitor` — прямой доступ к IP пода.
- **Простые проверки:** Используйте `Probe` — blackbox-мониторинг.

---

## Практические сценарии

### Сценарий 1: Мониторинг внешних серверов

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-servers
  namespace: monitoring
  labels:
    release: prometheus
spec:
  staticConfigs:
    - targets:
        - db-primary.prod.internal:9187
        - db-replica.prod.internal:9187
        - redis.prod.internal:9121
      labels:
        environment: production
        team: backend
  metricsPath: /metrics
  scrapeInterval: 30s
  basicAuth:
    username:
      name: external-metrics-credentials
      key: username
    password:
      name: external-metrics-credentials
      key: password
```

### Сценарий 2: Consul Service Discovery

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: consul-services
  namespace: monitoring
spec:
  consulSDConfigs:
    - server: consul.prod.internal:8500
      token:
        name: consul-token
        key: token
      services:
        - web-api
        - payment-service
      tags:
        - production
  relabelings:
    - sourceLabels: [__meta_consul_service_metadata_prometheus_port]
      targetLabel: __address__
    - sourceLabels: [__meta_consul_service_metadata_prometheus_path]
      targetLabel: __metrics_path__
```

### Сценарий 3: OTLP-инжест (Prometheus 3.0+)

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: otlp-receiver
  namespace: monitoring
spec:
  enableOTLPReceiver: true
  scrapeProtocols:
    - OTLPProto
  externalLabels:
    cluster: production-east
```

### Сценарий 4: Сетевое оборудование через SNMP Exporter

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: network-switches
  namespace: monitoring
spec:
  staticConfigs:
    - targets:
        - switch-core-01.lab.local
        - switch-access-01.lab.local
      labels:
        role: switch
        location: dc-east
  metricsPath: /snmp
  params:
    module: [if_mib]
  relabelings:
    - sourceLabels: [__address__]
      targetLabel: __param_target
    - sourceLabels: [__param_target]
      targetLabel: instance
    - targetLabel: __address__
      replacement: snmp-exporter.monitoring:9116
```

### Сценарий 5: Миграция с additionalScrapeConfigs

**До (секрет):**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: prometheus-additional-scrape
  namespace: monitoring
stringData:
  additional-scrape.yaml: |
    - job_name: 'external-db'
      static_configs:
        - targets: ['db.prod.internal:9187']
```

**После (ScrapeConfig):**

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-db
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ['db.prod.internal:9187']
```

---

## Диагностика и устранение неисправностей

### Проблема: ScrapeConfig не применяется

**Причины:**

- Версия Operator < v0.65 (нет поддержки ScrapeConfig).
- CRD `scrapeconfigs.monitoring.coreos.com` не установлен.
- Селектор `scrapeConfigSelector` в Prometheus CRD не включает метки этого ScrapeConfig.

**Диагностика:**

```bash
# 1. Проверка версии Operator
kubectl get deployment prometheus-operator -n monitoring -o jsonpath='{.spec.template.spec.containers[0].image}'

# 2. Проверка наличия CRD
kubectl get crd scrapeconfigs.monitoring.coreos.com

# 3. Проверка статуса ScrapeConfig
kubectl get scrapeconfig external-db -n monitoring -o yaml | grep -A5 status

# 4. Проверка селектора в Prometheus
kubectl get prometheus main -n monitoring -o jsonpath='{.spec.scrapeConfigSelector}'
```

### Проблема: Цели не появляются в Prometheus

**Причины:**

- Неверный `metricsPath` или порт.
- Проблемы с сетевой доступностью (NetworkPolicy, firewall).
- Ошибки в `relabelings` (все цели фильтруются).

**Диагностика:**

```bash
# 1. Проверка конфигурации Prometheus
kubectl exec -n monitoring prometheus-main-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.labels.job=="scrapeConfig/external-db")'

# 2. Проверка логов Operator
kubectl logs -n monitoring deploy/prometheus-operator | grep -i "scrapeconfig\|error"

# 3. Проверка NetworkPolicy
kubectl get networkpolicy -n monitoring -o yaml | grep -A20 "scrapeConfig\|prometheus"
```

### Частые ошибки на собеседованиях

1. **"ScrapeConfig заменяет ServiceMonitor"** — Нет. ScrapeConfig предназначен для сложных случаев (внешние цели, OTLP, Consul SD). Для стандартных K8s-приложений ServiceMonitor проще и декларативнее.

2. **"ScrapeConfig стабилен (v1)"** — Нет. На 2026 год API version — `v1alpha1`. Рекомендуется избегать использования в критичных продакшен-средах без понимания рисков изменения API.

3. **"OTLP-инжест требует OpenTelemetry Collector"** — Нет. Prometheus 3.0+ поддерживает нативный OTLP-ресивер через `enableOTLPReceiver: true`.

---

## Дополнительная информация

- [Prometheus Operator — Концепции](../concepts.md) — архитектура Operator.
- [ServiceMonitor CRD](./servicemonitor.md) — основной механизм мониторинга K8s-приложений.
- [Prometheus CRD](./prometheus.md) — конфигурация `scrapeConfigSelector`.
- [Long-Term Storage](../long_term_storage_integration.md) — интеграция с Thanos/Mimir.
- [Network Policies](../network_policies.md) — настройка egress для скрейпинга внешних целей.
