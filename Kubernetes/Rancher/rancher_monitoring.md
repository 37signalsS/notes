# Мониторинг в Rancher

## Определения

**Rancher Monitoring (Monitoring V2)** — интегрированное решение для развертывания и управления стеком наблюдаемости (observability) на базе Prometheus и Grafana. Инструмент построен на базе Prometheus Operator и является оберткой над Helm-чартом `kube-prometheus-stack`, адаптированной для работы в экосистеме Rancher.

**Prometheus Operator** — контроллер Kubernetes, который автоматизирует управление жизненным циклом компонентов мониторинга через Custom Resource Definitions (CRD). Он позволяет описывать цели сбора метрик и правила оповещений в виде стандартных объектов Kubernetes.

**AlertmanagerConfig** — ресурс (CRD), введенный для реализации многопользовательского (multi-tenant) алертинга. Он позволяет настраивать маршруты и получателей оповещений на уровне отдельных Namespace, не требуя доступа к глобальной конфигурации Alertmanager.

## Базовые концепции

### Архитектура решения

Пакет `rancher-monitoring` развертывает полный стек мониторинга внутри кластера. В актуальных версиях (Rancher v2.8+) архитектура включает:

1.  **Prometheus Server**: основной компонент для сбора (scraping) и хранения метрик. Поддерживает два режима работы:
    *   **Standard Mode**: сбор данных, хранение в локальном TSDB и выполнение правил алертинга.
    *   **Agent Mode** (v2.8+): оптимизированный режим только для сбора и пересылки метрик (Remote Write) во внешние хранилища. Снижает потребление ресурсов на 30–40%.
2.  **Alertmanager**: система управления оповещениями, обеспечивающая дедупликацию, группировку и доставку уведомлений.
3.  **Grafana**: визуализация данных с набором предустановленных дашбордов для узлов кластера, компонентов Kubernetes и ресурсов Rancher.
4.  **Экспортеры**:
    *   **Node Exporter**: сбор системных метрик узлов.
    *   **Kube-State-Metrics**: генерация метрик на основе состояния объектов API (Deployment, Pod, Node).

### Уровни мониторинга

*   **Кластерный мониторинг**: сбор метрик с системных компонентов (etcd, scheduler, kube-proxy). Настраивается администратором кластера.
*   **Пользовательский мониторинг**: сбор метрик с приложений через ресурсы `ServiceMonitor` и `PodMonitor`.
*   **Многопользовательское оповещение**: использование `AlertmanagerConfig` для изоляции уведомлений разных команд внутри одного кластера.

### Особенности интеграции Rancher

*   **Унифицированный UI**: управление конфигурацией (Retention, Storage, Remote Write) через графический интерфейс Rancher.
*   **Автоматизация etcd**: безопасное подключение к etcd с использованием сертификатов узлов (только для RKE/RKE2/K3s).
*   **Интеграция с проектами**: автоматическое создание RBAC для доступа пользователей к Grafana и Prometheus.

## Практические сценарии

### Установка и настройка стека

1.  **Развертывание**: В интерфейсе Rancher перейдите в **Apps** → **Charts** и выберите **Monitoring**.
2.  **Настройка хранилища (Persistence)**:
    *   Всегда включайте `Persistent Storage` для Prometheus и Grafana в продуктивных средах.
    *   Настройте `Retention` (срок хранения). Для длительного хранения рекомендуется использовать `Remote Write` во внешние системы (VictoriaMetrics, Thanos).
3.  **Лимиты ресурсов**: задавайте CPU и Memory limits исходя из количества метрик (cardinality). В кластерах с 100+ узлами Prometheus может требовать 16GB+ RAM.

### Настройка сбора метрик с приложения

Для автоматического обнаружения приложения создайте `ServiceMonitor`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: billing-api-monitor
  namespace: billing
  labels:
    # Обязательная метка для обнаружения оператором в Rancher
    release: rancher-monitoring
spec:
  selector:
    matchLabels:
      app: billing-api
  endpoints:
  - port: metrics-port
    interval: 30s
    path: /metrics
```

### Настройка уведомлений через AlertmanagerConfig

Пример настройки отправки уведомлений в Slack для конкретного пространства имен:

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: slack-notifications
  namespace: billing
  labels:
    release: rancher-monitoring
spec:
  route:
    receiver: 'slack-receiver'
    groupBy: ['alertname']
  receivers:
  - name: 'slack-receiver'
    slackConfigs:
    - apiURL: 
        name: slack-webhook-url # Ссылка на Secret
        key: url
      channel: '#alerts-billing'
```

## Дополнительная информация

### Статус компонентов и актуальность

| Компонент | Версия (ориентир) | Статус | Примечание |
| :--- | :--- | :--- | :--- |
| **Prometheus Operator** | v0.65+ | Актуально | Поддержка Agent Mode и AlertmanagerConfig |
| **Prometheus** | v2.45+ | Актуально | LTS-ветка с оптимизацией TSDB |
| **Grafana** | v10.x / v11.x | Актуально | Новый интерфейс и поддержка AlertmanagerConfig |

### Рекомендации по эксплуатации

*   **Изоляция**: Размещайте стек мониторинга в выделенных узлах (через `nodeSelector` и `tolerations`), чтобы всплески нагрузки при сборе метрик не влияли на бизнес-приложения.
*   **Remote Write**: Используйте этот механизм для централизации мониторинга в мультикластерных средах.
*   **Фильтрация**: Настраивайте `metricRelabelConfigs` для удаления ненужных высокочастотных метрик (например, от cAdvisor), чтобы снизить нагрузку на хранилище.

**Связанные темы:**

* [Обзор kube-prometheus-stack](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md) — глубокая настройка Helm-чарта.
* [VictoriaMetrics](../../VictoriaMetrics/overview.md) — решение для долгосрочного хранения и высокой нагрузки.
* [rancher_overview](./rancher_overview.md) — общая архитектура платформы Rancher.
