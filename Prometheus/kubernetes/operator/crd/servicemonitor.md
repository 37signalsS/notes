# ServiceMonitor — Концепции (CRD)

## Определения

**`kind: ServiceMonitor`** — Custom Resource Definition в Prometheus Operator для описания целей скрейпинга (scraping targets) через Kubernetes Service. Operator использует Service для обнаружения эндпоинтов (Endpoints) и автоматической генерации конфигурации скрейпинга для Prometheus.

**API version:** `monitoring.coreos.com/v1`

## Базовые концепции

### Принцип работы

Prometheus Operator функционирует как контроллер, выполняющий следующие шаги:

1. **Discovery:** находит объекты `ServiceMonitor` по селектору лейблов (label selector), указанному в ресурсе `Prometheus`.
2. **Endpoint Lookup:** запрашивает Kubernetes API для получения списка эндпоинтов (Endpoints/EndpointSlices) сервиса, указанного в `ServiceMonitor`.
3. **Config Generation:** генерирует блок `scrape_config` для Prometheus на основе параметров `ServiceMonitor`.
4. **Secret Update:** сохраняет обновлённую конфигурацию в Kubernetes Secret.
5. **Reload:** sidecar-контейнер `prometheus-config-reloader` отслеживает изменения в Secret и перезагружает конфигурацию Prometheus.

### Когда использовать ServiceMonitor

- **Stateless-приложения:** стандартный и рекомендуемый подход для большинства веб-сервисов.
- **Наличие Service:** когда приложение уже экспонировано через Kubernetes Service.
- **Абстракция эндпоинтов:** Service автоматически отслеживает жизненный цикл подов, предоставляя стабильный интерфейс для обнаружения целей.
- **Балансировка:** позволяет собирать метрики со всех реплик, стоящих за сервисом.

### Отличие от PodMonitor

| Характеристика | ServiceMonitor | PodMonitor |
|:---|:---|:---|
| **Объект обнаружения** | Service | Pod |
| **Требование Service** | Обязательно | Не требуется |
| **Мета-лейблы** | `__meta_kubernetes_endpoint_*`, `__meta_kubernetes_service_*` | `__meta_kubernetes_pod_*` |
| **Основной сценарий** | Stateless-сервисы, стандартные приложения | StatefulSet, инфраструктурные компоненты без Service |

> **См. также:** [PodMonitor CRD](./podmonitor.md) — мониторинг подов напрямую (без использования Service).

## Практические сценарии

### Базовая конфигурация

Сбор метрик с приложения в пространстве имён `production` с интервалом 15 секунд.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  namespace: production
  labels:
    release: monitoring
spec:
  selector:
    matchLabels:
      app: my-app
  namespaceSelector:
    matchNames:
      - production
  endpoints:
    - port: web
      interval: 15s
      path: /metrics
```

### Обнаружение во всех пространствах имён

Конфигурация для сбора метрик со всех сервисов с определённым лейблом во всём кластере.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: global-monitor
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: my-app
  namespaceSelector:
    any: true
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

### Настройка TLS и аутентификации

Сбор метрик по защищённому протоколу HTTPS с использованием клиентского сертификата.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-app
  namespace: production
spec:
  selector:
    matchLabels:
      app: secure-app
  endpoints:
    - port: https
      path: /metrics
      scheme: https
      tlsConfig:
        caFile: /etc/prometheus/secrets/ca.crt
        certFile: /etc/prometheus/secrets/client.crt
        keyFile: /etc/prometheus/secrets/client.key
      bearerTokenSecret:
        name: prometheus-token
        key: token
```

### Релейблинг (Relabelings) целей и метрик

```yaml
endpoints:
  - port: web
    # Изменение лейблов цели до скрейпинга
    relabelings:
      - sourceLabels: [__meta_kubernetes_namespace]
        targetLabel: namespace
      - sourceLabels: [__meta_kubernetes_service_name]
        targetLabel: service
    # Изменение лейблов метрик после скрейпинга
    metricRelabelings:
      - sourceLabels: [__name__]
        regex: "go_.*"
        action: drop
```

## Дополнительная информация

### Основные параметры спецификации (spec)

| Параметр | Описание | Пример |
|:---|:---|:---|
| **`selector`** | Селектор для поиска Kubernetes Service | `matchLabels: {app: my-app}` |
| **`namespaceSelector`** | Пространства имён для поиска сервисов | `matchNames: [prod]` или `any: true` |
| **`endpoints`** | Список эндпоинтов и параметров скрейпинга | См. таблицу параметров эндпоинтов |
| **`jobLabel`** | Лейбл сервиса, используемый как имя job | `app.kubernetes.io/name` |
| **`targetLabels`** | Лейблы сервиса, переносимые в метрики | `[environment, team]` |
| **`sampleLimit`** | Максимальное число сэмплов за один скрейп | `10000` |
| **`targetLimit`** | Максимальное число целей для мониторинга | `100` |

### Параметры эндпоинтов (endpoints)

| Параметр | Описание | Пример |
|:---|:---|:---|
| **`port`** | Имя порта в Kubernetes Service | `web`, `metrics` |
| **`path`** | Путь к эндпоинту метрик | `/metrics` |
| **`interval`** | Частота сбора метрик | `15s`, `1m` |
| **`scheme`** | Протокол (http/https) | `https` |
| **`tlsConfig`** | Настройки TLS (пути к сертификатам) | `caFile`, `certFile` |
| **`bearerTokenSecret`** | Токен авторизации из Kubernetes Secret | `name: token-secret, key: token` |
| **`basicAuth`** | Данные Basic Auth из Secret | `username`, `password` |
| **`scrapeTimeout`** | Таймаут ожидания ответа | `10s` |
| **`relabelings`** | Правила переопределения лейблов целей | См. раздел "Релейблинг" |
| **`metricRelabelings`** | Правила фильтрации и изменения метрик | См. раздел "Релейблинг" |

### Доступные мета-лейблы для ServiceMonitor

Данные лейблы доступны для использования в блоке `relabelings`:

| Лейбл | Описание |
|:---|:---|
| `__meta_kubernetes_namespace` | Пространство имён сервиса |
| `__meta_kubernetes_service_name` | Имя сервиса |
| `__meta_kubernetes_service_label_<name>` | Лейблы сервиса |
| `__meta_kubernetes_service_annotation_<name>` | Аннотации сервиса |
| `__meta_kubernetes_endpoint_node_name` | Узел, на котором запущен эндпоинт |
| `__meta_kubernetes_pod_name` | Имя пода |
| `__meta_kubernetes_pod_label_<name>` | Лейблы пода |

### Связанные ресурсы

- [PodMonitor CRD](./podmonitor.md) — сбор метрик напрямую с подов.
- [Prometheus CRD](./prometheus.md) — конфигурация экземпляра Prometheus.
- [Probe CRD](./probe.md) — Blackbox-мониторинг внешних целей.
