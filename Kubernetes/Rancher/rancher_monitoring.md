# Мониторинг в Rancher

## Определения

**Rancher Monitoring** — встроенный инструмент Rancher для развертывания и управления стеком мониторинга на базе Prometheus и Grafana в кластерах Kubernetes. Использует [Prometheus Operator](../Concepts/kubernetes_operators.md) для автоматического конфигурирования Prometheus.

## Базовые концепции

### Основа мониторинга

Мониторинг в Rancher базируется на проекте `kube-prometheus-stack` (ранее `Kube Prometheus`), который в свою очередь основан на `Prometheus Operator`. Он включает в себя:

* **Prometheus Operator**: Управляет развертыванием Prometheus и Alertmanager.
* **Prometheus**: Система сбора и хранения метрик.
* **Alertmanager**: Для обработки и маршрутизации оповещений.
* **Node Exporter**: Собирает метрики с узлов Kubernetes.
* **kube-state-metrics**: Экспортирует метрики о состоянии объектов Kubernetes API.
* **Grafana**: Для визуализации метрик и создания дашбордов.

**Автоматическая настройка**: `kube-prometheus-stack` предоставляет преднастроенные дашборды, правила алертов и цели сбора метрик из коробки.

### Node Exporter

Агент, запускаемый на каждом узле кластера, собирающий метрики операционной системы и аппаратного обеспечения. Rancher предлагает включение Node Exporter одной кнопкой.

### Grafana

В дополнение к Prometheus, Rancher автоматически разворачивает Grafana с заранее сконфигурированными дашбордами для мониторинга кластера.

### Типы мониторинга

* **Мониторинг кластера**: Собирает метрики со всех системных компонентов и узлов.
* **Мониторинг проектов/приложений**: До Rancher 2.7.x позволял разворачивать отдельный экземпляр Prometheus для конкретного проекта. **Функциональность удалена** начиная с 2.7.x.

### Service Monitor

Custom Resource, используемый Prometheus Operator для указания Prometheus, откуда собирать метрики. Связывает приложение (через Service) с Prometheus. Ключевая метка — `release: rancher-monitoring` — обеспечивает связывание `ServiceMonitor` с экземпляром Prometheus, управляемым Rancher.

### Ограничения и рекомендации

* **Смешивание метрик**: Метрики приложений и системные метрики хранятся в одном хранилище.
* **Ресурсные квоты**: Отсутствует контроль выделенного дискового пространства для метрик отдельных приложений.
* **Безопасность**: Для работы с UI мониторинга требуются широкие права (например, `Manage Services`).
* **Сложность конфигурации**: Глубокая настройка `kube-prometheus-stack` требует понимания Helm-чартов и Kubernetes.

**Рекомендация:** Для мониторинга бизнес-метрик приложений предпочтительно разворачивать отдельные стеки мониторинга или использовать внешние SaaS-решения.

## Практические сценарии

### Включение мониторинга через Web UI

1. **Создайте отдельный Rancher Project для мониторинга:** Рекомендуется создать отдельный Rancher `Project` (например, "Monitoring") для размещения глобального стека мониторинга.
2. Перейдите в **Cluster Dashboard** -> **Tools** -> **Monitoring**.
3. Настройте параметры:
    * **Project**: Выберите созданный вами `Project`.
    * **Version**: Выберите желаемую версию стека мониторинга.
    * **Customize Helm Options for install**: Всегда рекомендуется включать эту опцию.
    * **Prometheus**:
        * **Scrape Interval**: Интервал сбора метрик (например, `15s`).
        * **Retention Time**: Срок хранения данных.
    * **Enable Nodes Exporter**: Рекомендуется включить.
    * **Persistent Storage for Prometheus**: Требует предварительно настроенного [PersistentVolume](../Storage/pv_and_pvc.md).
    * **Persistent Storage for Grafana**: Опционально.
    * **Grafana Sidecar**: Для автоматического обнаружения кастомных дашбордов.

**Важно:** При использовании устаревших NFS Provisioner Prometheus может не стартовать из-за проблем с `volumeClaimTemplate`.

### Сбор метрик с приложений (Service Monitor)

Для того чтобы Prometheus собирал метрики с вашего приложения, необходимо:

1. **Развернуть приложение**: Создайте Deployment или StatefulSet для вашего приложения.
2. **Создать Service**: Определите [Service](../Networking/Service/service_overview.md) для вашего приложения.
3. **Создать Service Monitor**: Custom Resource, который инструктирует Prometheus Operator о том, как собирать метрики.

Пример Service Monitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: example-app-monitor
  labels:
    release: rancher-monitoring
spec:
  selector:
    matchLabels:
      app: example-app
  endpoints:
  - port: http-metrics
    path: /metrics
    interval: 30s
```

### Мониторинг ETCD

Мониторинг ETCD требует ручной конфигурации, так как сертификаты ETCD не доступны автоматически:

1. Поместить сертификеты ETCD в Kubernetes `Secret`.
2. Создать `Service` и `Endpoint` для обнаружения ETCD-серверов.
3. Создать `ServiceMonitor` с указанием секретов для аутентификации.

YAML-примеры: [prometheus_config.md](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/prometheus_config.md). Концепции ETCD: [architecture-and-concepts.md](../../etcd/architecture-and-concepts.md).

## Дополнительная информация

### Актуальность версий

> **Внимание:** Rancher Monitoring базируется на `kube-prometheus-stack` (Prometheus Operator). Компоненты обновляются через Rancher UI. Перед развёртыванием проверьте актуальные версии:

| Компонент | Указанная информация | Статус | Рекомендация |
|-----------|---------------------|--------|--------------|
| **kube-prometheus-stack** | Базируется на Prometheus Operator | ✅ Evergreen | [GitHub Releases](https://github.com/prometheus-community/helm-charts/releases) |
| **Prometheus** | v2.x | ✅ Evergreen | Обновляется через Rancher UI |
| **Grafana** | v10+ | ✅ Evergreen | Обновляется через Rancher UI |
| **API version** | `monitoring.coreos.com/v1` | ✅ Стабилен | Не менялся с 2024 |

Альтернативы: [VictoriaMetrics](../../VictoriaMetrics/overview.md), [Mimir](../../Mimir/mimir_overview.md).

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
