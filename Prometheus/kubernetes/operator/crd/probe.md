# Probe — Концепции (CRD)

## Определения

**`kind: Probe`** — Custom Resource Definition в Prometheus Operator, предназначенный для реализации **blackbox-мониторинга** (внешнего наблюдения) эндпоинтов. В отличие от `ServiceMonitor`, который собирает метрики состояния самого приложения, `Probe` проверяет доступность, корректность ответов и производительность сервисов по протоколам HTTP, TCP, ICMP, DNS и gRPC изнутри кластера.

**Blackbox Exporter** — вспомогательный компонент, который выступает в роли "прокси" для выполнения проверок. Prometheus опрашивает экспортер, а экспортер выполняет реальную проверку цели.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Blackbox Exporter — обзор](../../../Exporters/blackbox/blackbox_exporter_overview.md), [Конфигурация модулей](../../../Exporters/blackbox/blackbox_exporter_modules_configuration.md), [ServiceMonitor](./servicemonitor.md).

## Базовые концепции

### Принцип работы (Multi-Target Scrape)

Интеграция строится на модели делегирования сбора метрик:

1.  **Reconciliation:** Operator обнаруживает ресурс `Probe` и генерирует конфигурацию скрейпинга для Prometheus.
2.  **Делегирование:** Prometheus отправляет запрос не на целевой сервис, а на эндпоинт `/probe` Blackbox Exporter.
3.  **Выполнение:** Exporter получает параметры (адрес цели и модуль), выполняет проверку (например, HTTP GET) и возвращает результат в формате метрик Prometheus.
4.  **Метрики:** Основными метриками являются `probe_success` (1 — успех, 0 — провал) и `probe_duration_seconds`.

```text
[ Prometheus ] 
      |
      | (GET /probe?target=example.com&module=http_2xx)
      v
[ Blackbox Exporter ] ------> [ Target: example.com ]
      |          (HTTP GET)        |
      |                            |
      |<--------- (Response) <-----|
      |
      | (probe_success 1)
      v
[ Prometheus TSDB ]
```

### Сравнение с ServiceMonitor

| Характеристика | ServiceMonitor / PodMonitor | Probe |
| :--- | :--- | :--- |
| **Тип мониторинга** | Whitebox (внутреннее состояние) | Blackbox (внешняя доступность) |
| **Источник данных** | `/metrics` самого приложения | Эндпоинт `/probe` экспортера |
| **Цели** | Сервисы и Поды внутри K8s | Любые эндпоинты (внешние URL, IP, Ingress) |
| **Протоколы** | HTTP (Prometheus format) | HTTP, HTTPS, TCP, ICMP, DNS, gRPC |

### Новые возможности (2025–2026)

*   **OAuth2 & Modern Auth:** Нативная поддержка OAuth2 и расширенных механизмов авторизации (bearer tokens) через Secret-ы.
*   **gRPC Monitoring:** Поддержка проверки здоровья gRPC-сервисов через соответствующие модули Blackbox Exporter.
*   **Native Histograms:** Поддержка высокоточных нативных гистограмм Prometheus 3.0.
*   **Scrape Protocols:** Возможность явного выбора приоритета протоколов (OpenMetrics vs Prometheus Text).

## Практические сценарии

### Сценарий 1: Проверка внешнего HTTPS API с OAuth2

Актуально для мониторинга внешних сервисов, требующих авторизации.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-api-oauth2
  namespace: monitoring
spec:
  jobName: api-health-check
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    staticConfig:
      static:
        - https://api.external-service.com/v1/health
  oauth2:
    clientId:
      secret:
        name: api-credentials
        key: client-id
    clientSecret:
      name: api-credentials
      key: client-secret
    tokenUrl: https://auth.external-service.com/oauth/token
  interval: 1m
  scrapeTimeout: 30s
```

### Сценарий 2: Мониторинг всех Ingress по селектору

Автоматическое создание проверок для всех приложений, помеченных лейблом `probe: "enabled"`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: ingress-auto-probe
  namespace: monitoring
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    ingress:
      selector:
        matchLabels:
          probe: "enabled"
      namespaceSelector:
        any: true
```

### Сценарий 3: gRPC Health Check

Мониторинг доступности микросервисов, использующих gRPC.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: grpc-service-probe
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: grpc_health  # Модуль должен быть настроен в Blackbox Exporter
  targets:
    staticConfig:
      static:
        - my-grpc-app.prod.svc.cluster.local:50051
  interval: 30s
```

### Сценарий 4: ICMP (Ping) проверка инфраструктуры

Проверка доступности удаленных хостов или сетевого оборудования.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: infrastructure-ping
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: icmp
  targets:
    staticConfig:
      static:
        - 8.8.8.8
        - 10.0.0.1
        - vpn-gateway.company.com
```

## Дополнительная информация

### Ключевые параметры спецификации (v1)

| Параметр | Описание | Особенности |
| :--- | :--- | :--- |
| **`prober.url`** | Адрес Blackbox Exporter. | Формат `host:port`. |
| **`module`** | Имя модуля в конфиге экспортера. | Должно совпадать с `blackbox.yml`. |
| **`targets.staticConfig`** | Список фиксированных целей. | Поддерживает кастомные `labels`. |
| **`targets.ingress`** | Динамический поиск целей через Ingress. | Использует `host` из правил Ingress. |
| **`interval`** | Периодичность выполнения проверок. | По умолчанию берется из глобальных настроек Prometheus. |
| **`scrapeTimeout`** | Максимальное время ожидания ответа. | **Важно:** должен быть больше таймаута в модуле Blackbox Exporter. |
| **`jobName`** | Переопределение имени задания. | Задает значение метки `job` в метриках. |
| **`oauth2`** | Конфигурация OAuth2. | **Mutual Exclusion:** нельзя использовать вместе с `basicAuth`. |
| **`authorization`** | Настройка Bearer-токена. | Поддерживает `credentials` из Secret. |
| **`tlsConfig`** | TLS для соединения с пробером. | Влияет на канал `Prometheus -> Prober`, а не на валидацию цели. |
| **`scrapeProtocols`** | Приоритет протоколов сбора. | OpenMetrics, PrometheusText. |
| **`scrapeNativeHistograms`** | Включение нативных гистограмм. | Требует Prometheus >= 3.0. |

### Диагностика

1.  **Проверка генерации таргетов:** В UI Prometheus перейдите в `Status -> Targets`. Найдите job с именем вашего Probe.
2.  **Проверка запроса к экспортеру:**
    ```bash
    curl "http://blackbox-exporter:9115/probe?target=google.com&module=http_2xx"
    ```
3.  **Логи Оператора:** Если таргеты не появились, проверьте логи `prometheus-operator` на наличие ошибок валидации CRD.

### См. также

*   [Blackbox Exporter — настройка модулей](../../../Exporters/blackbox/blackbox_exporter_modules_configuration.md) — подготовка модулей и параметров проверки.
*   [Prometheus Operator — Концепции](../concepts.md) — архитектура и роль CRD в мониторинге Kubernetes.
*   [Официальная документация Probe CRD](https://prometheus-operator.dev/docs/operator/design/#probe) — описание параметров и примеров от разработчиков.
