# Мониторинг в Rancher

## Определения

**Rancher Monitoring (Monitoring V2)** — интегрированное решение для развертывания и управления полным стеком наблюдаемости (observability), базирующееся на **Prometheus Operator**. Пакет представляет собой адаптированную версию Helm-чарта `kube-prometheus-stack`, оптимизированную для мультикластерной среды Rancher.

**Prometheus v3.x (2026)** — текущее поколение сервера мониторинга, поддерживающее нативный прием данных по протоколу OTLP (OpenTelemetry), высокую производительность TSDB и улучшенное управление памятью.

**Grafana Alloy** — универсальный агент (наследник Grafana Agent), который в современных инсталляциях Rancher (v2.10+) может использоваться совместно с Prometheus Operator для унифицированного сбора метрик, логов и трассировок.

**AlertmanagerConfig** — ресурс Kubernetes (CRD) для декларативного управления маршрутизацией алертов. Позволяет делегировать настройку уведомлений владельцам проектов (Projects) без предоставления доступа к глобальному Alertmanager.

## Базовые концепции

### Архитектура и компоненты 2026 года

Пакет `rancher-monitoring` обеспечивает глубокую интеграцию компонентов мониторинга с ресурсами кластера.

1.  **Prometheus Server**:
    *   **Server Mode**: хранение данных в локальном TSDB. Рекомендуется для Management-кластера или небольших Downstream-кластеров.
    *   **Agent Mode (v2)**: только сбор и пересылка данных (Remote Write / OTLP) во внешние хранилища (VictoriaMetrics, Mimir). В 2026 году является стандартом для крупных продуктивных сред.
2.  **Grafana Unified Alerting**: интеграция, позволяющая управлять всеми оповещениями (Prometheus, Loki, Tempo) из единого интерфейса Grafana с привязкой к RBAC Rancher.
3.  **OpenTelemetry Integration**: поддержка сбора метрик напрямую через OTLP без использования промежуточных экспортеров.

### Особенности интеграции Rancher

*   **Мультикластерная агрегация**: возможность настройки Remote Write для всех кластеров в единый "Monitoring Hub".
*   **RBAC & Projects**: Rancher автоматически настраивает права доступа к дашбордам Grafana на основе членства пользователя в проектах (Projects).
*   **Автоматизация etcd**: встроенные механизмы безопасного скрейпинга etcd для дистрибутивов RKE2 и K3s.

## Практические сценарии

### Настройка Agent Mode v2 с Remote Write

Для минимизации потребления ресурсов в Downstream-кластере настройте Prometheus в режиме агента через `values.yaml` (или UI):

```yaml
prometheus:
  prometheusSpec:
    enableFeatures:
      - agent
      - otlp-receiver # Включение нативной поддержки OTLP (v3+)
    remoteWrite:
      - url: "https://mimir.example.com/api/v1/push"
        basicAuth:
          username:
            name: mimir-creds
            key: user
          password:
            name: mimir-creds
            key: password
```

### Сбор метрик приложения через ServiceMonitor

Стандартный метод интеграции пользовательских приложений в мониторинг:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: app-monitor
  namespace: prod-app
  labels:
    release: rancher-monitoring # Метка обязательна для обнаружения оператором
spec:
  selector:
    matchLabels:
      app: my-app
  endpoints:
  - port: web
    interval: 30s
    path: /metrics
```

### Изоляция алертов через AlertmanagerConfig

Пример настройки уведомлений в Telegram для конкретной команды разработчиков (Namespace-scoped):

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: team-alerts
  namespace: prod-app
  labels:
    release: rancher-monitoring
spec:
  route:
    receiver: 'telegram-receiver'
    groupBy: ['alertname', 'severity']
  receivers:
  - name: 'telegram-receiver'
    telegramConfigs:
    - botToken:
        name: telegram-secret
        key: token
      chatID: -100123456789
```

## Дополнительная информация

### Статус компонентов и версионность (2026)

| Компонент | Версия | Статус | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Prometheus Operator** | v0.89+ | Актуально | Полная поддержка OTLP и ScrapeConfigs |
| **Prometheus** | v3.x | Stable | Использовать OTLP для новых приложений |
| **Grafana** | v13.x | Актуально | Основной интерфейс Unified Alerting |

### Рекомендации по масштабированию

*   **Sharding**: используйте `spec.shards` в ресурсе Prometheus для горизонтального масштабирования сбора метрик в сверхкрупных кластерах (1000+ узлов).
*   **Alloy Collector**: для гибридных задач (метрики + логи + профилирование) внедряйте Grafana Alloy вместо набора разрозненных экспортеров.
*   **Cardinality Management**: регулярно анализируйте "тяжелые" метрики через дашборд "Prometheus Stats" и применяйте `metricRelabelConfigs` для удаления неиспользуемых лейблов.

**Связанные темы:**

* [Обзор kube-prometheus-stack](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md) — детализация Helm-параметров.
* [VictoriaMetrics](../../VictoriaMetrics/overview.md) — высокопроизводительное долгосрочное хранилище.
* [rancher_overview](./rancher_overview.md) — архитектура платформы Rancher.
* [OpenTelemetry: архитектура](../../OpenTelemetry/architecture_signals.md) — основы работы с сигналами OTel.
