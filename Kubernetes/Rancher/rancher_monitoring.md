# Мониторинг в Rancher

## Определения

**Rancher Monitoring** — встроенный инструмент Rancher для развертывания и управления стеком мониторинга на базе Prometheus и Grafana в кластерах Kubernetes. Использует [Prometheus Operator](../../Concepts/kubernetes_operators.md#kubernetes-операторы-автоматизация-управления-приложениями) для автоматического конфигурирования Prometheus.

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
* **Мониторинг проектов/приложений**: Ранее Rancher позволял развертывать отдельный экземпляр Prometheus для сбора метрик с конкретных приложений в рамках выбранного проекта. **В Rancher версии 2.7.x эта функциональность была удалена.**

### Service Monitor

Custom Resource, используемый Prometheus Operator для указания Prometheus, откуда собирать метрики. Связывает приложение (через Service) с Prometheus.

### Важные замечания

1. **Критическое замечание о Rancher и мониторинге**: Изначально Rancher позиционировался как инструмент, облегчающий работу с Kubernetes. Однако на практике, для тонкой настройки или устранения проблем пользователю все равно требуется глубокое понимание `kube-prometheus-stack`, Helm-чартов и Kubernetes в целом.
2. **Сложность конфигурации**: Глубокая настройка `kube-prometheus-stack` может быть сложной из-за использования `jsonnet` для шаблонизации конфигураций.
3. **Проблемы с текущим подходом в 2.7.x**:
    * **Смешивание метрик**: Метрики приложений и системные метрики хранятся в одном хранилище.
    * **Ресурсные квоты**: У пользователя нет контроля над выделенным дисковым пространством для его метрик.
    * **Безопасность**: Для бесперебойной работы с UI мониторинга пользователю приходится выдавать относительно широкие права (например, `Manage Services`).

**Настоятельная рекомендация**: Для мониторинга бизнес-метрик ваших приложений **настоятельно рекомендуется** разворачивать отдельные стеки мониторинга вручную или использовать специализированные внешние SaaS-решения.

## Практические сценарии

### Включение мониторинга через Web UI

#### 1. Включение мониторинга для кластера

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
    * **Persistent Storage for Prometheus**: Требует предварительно настроенного [PersistentVolume](../../Storage/pv_and_pvc.md).
    * **Persistent Storage for Grafana**: Опционально.
    * **Grafana Sidecar**: Для автоматического обнаружения кастомных дашбордов.

**Важное замечание: Проблемы с NFS Provisioner**: При использовании устаревших NFS Provisioner, Prometheus может не стартовать из-за проблем с `volumeClaimTemplate`.

#### 2. Настройка мониторинга для проекта/приложения (устарело)

**Примечание:** В Rancher версии 2.7.x и выше функциональность развертывания отдельного экземпляра мониторинга для конкретного проекта была **удалена**.

#### 3. Сбор метрик с приложений (Service Monitor)

Для того чтобы Prometheus собирал метрики с вашего приложения, необходимо:

1. **Развернуть приложение**: Создайте Deployment или StatefulSet для вашего приложения.
2. **Создать Service**: Определите [Service](../../Networking/Service/service_overview.md) для вашего приложения.
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

### Мониторинг ETCD в Rancher

Мониторинг состояния кластера ETCD является критически важным для стабильности Kubernetes.

Для полноценного мониторинга ETCD требуется ручная конфигурация:

1. **Понимание архитектуры ETCD**: Необходимо знать, как ETCD запущен и где находятся его сертификаты.
2. **Создание Kubernetes Secret**: Сертификаты ETCD должны быть помещены в Kubernetes Secret.
3. **Создание Kubernetes Service и Endpoint**: Для обнаружения ETCD-серверов.
4. **Создание ServiceMonitor**: Используя Custom Resource `ServiceMonitor` из Prometheus Operator.

**Детальная настройка и YAML-примеры для мониторинга ETCD**: см. [prometheus_config.md](../../Prometheus/Kubernetes/Kube_Prometheus_Stack_Helm/prometheus_config.md). Концептуальная информация об ETCD: см. [architecture_and_concepts.md](../../etcd/architecture_and_concepts.md).

## Дополнительная информация

Альтернативы для мониторинга: [VictoriaMetrics](../../VictoriaMetrics/victoriametrics_overview.md), [Mimir](../../Mimir/mimir_overview.md).

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
