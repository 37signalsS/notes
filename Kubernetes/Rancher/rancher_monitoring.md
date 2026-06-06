# Мониторинг в Rancher

## Определения

**Rancher Monitoring** — интегрированное решение для развертывания и управления стеком мониторинга на базе Prometheus и Grafana в кластерах Kubernetes (K8s). Инструмент базируется на Prometheus Operator и Helm-чарте `kube-prometheus-stack`.

**Prometheus Operator** — контроллер Kubernetes, автоматизирующий управление жизненным циклом Prometheus, Alertmanager и сопутствующих компонентов через Custom Resource Definitions (CRD — пользовательские определения ресурсов).

## Базовые концепции

### Архитектура решения

Мониторинг в Rancher реализуется через установку пакета `rancher-monitoring`, который является адаптированной версией [kube-prometheus-stack](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md). В состав стека входят:

1. **Prometheus Server**: система сбора и хранения временных рядов (метрик).
2. **Alertmanager**: компонент для обработки оповещений и их маршрутизации (Email, Slack, Webhooks).
3. **Grafana**: платформа для визуализации данных и построения дашбордов.
4. **Экспортеры**:
    * **Node Exporter**: сбор метрик операционной системы узлов (CPU, RAM, диск).
    * **Kube-State-Metrics**: экспорт состояния объектов Kubernetes API (Application Programming Interface).

### Уровни мониторинга

* **Мониторинг кластера**: охватывает системные компоненты (etcd, scheduler, controller-manager) и состояние узлов. Доступен администраторам кластера.
* **Мониторинг приложений**: реализуется через создание ресурсов [ServiceMonitor](../Prometheus/kubernetes/operator/crd/servicemonitor.md) или [PodMonitor](../Prometheus/kubernetes/operator/crd/podmonitor.md).

**Важное изменение:** начиная с Rancher версии 2.7.x, функциональность "мониторинга проектов" (Project Monitoring) с выделенными экземплярами Prometheus была удалена. Теперь используется единый кластерный экземпляр Prometheus.

### Особенности интеграции

Rancher автоматизирует следующие аспекты:

* Установка и обновление всего стека через графический интерфейс (UI).
* Предварительная настройка дашбордов Grafana для ресурсов кластера.
* Настройка механизмов обнаружения целей (Service Discovery) для системных компонентов кластера.

## Практические сценарии

### Включение мониторинга через интерфейс Rancher

1. **Подготовка**: рекомендуется создать отдельный проект (Project) в Rancher (например, "System") для размещения ресурсов мониторинга.
2. **Установка**:
    * Перейдите в **Cluster Dashboard** → **Apps** → **Charts**.
    * Выберите чарт **Monitoring**.
    * В разделе **Helm Options** настройте параметры хранения данных (Persistence) для Prometheus и Grafana, чтобы избежать потери метрик при перезагрузке подов.
3. **Настройка Prometheus**:
    * Укажите срок хранения данных (Retention).
    * Настройте лимиты ресурсов (CPU/Memory) в соответствии с размером кластера.

### Сбор метрик с пользовательских приложений

Для того чтобы кластерный Prometheus начал собирать метрики с вашего приложения, необходимо:

1. Настроить приложение на отдачу метрик в формате Prometheus (обычно по пути `/metrics`).
2. Создать ресурс `ServiceMonitor` с обязательной меткой `release: rancher-monitoring`. Эта метка позволяет Prometheus Operator обнаружить ресурс.

Пример `ServiceMonitor`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app-monitor
  labels:
    release: rancher-monitoring
spec:
  selector:
    matchLabels:
      app: my-app
  endpoints:
  - port: web
    interval: 30s
```

### Мониторинг хранилища etcd

Поскольку etcd является критическим компонентом, его мониторинг требует доступа к TLS-сертификатам (Transport Layer Security). В Rancher это настраивается автоматически при установке чарта, если выбрана опция "Enable etcd monitoring". Подробности ручной настройки доступны в разделе [Мониторинг etcd](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/etcd-monitoring.md).

## Дополнительная информация

### Статус компонентов

| Компонент | Статус | Рекомендация |
|-----------|--------|--------------|
| kube-prometheus-stack | Актуально | Основной стек в Rancher 2.x |
| Prometheus Operator | Стабильно | Используется для управления CRD |
| Grafana | Актуально | Рекомендуется версия 10+ |

**Связанные темы:**

* [Обзор kube-prometheus-stack](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md) — детали конфигурации Helm-чарта.
* [Prometheus Operator Концепции](../Prometheus/kubernetes/operator/concepts.md) — принцип работы контроллера.
* [VictoriaMetrics](../../VictoriaMetrics/overview.md) — альтернатива для высоконагруженных сред.

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
