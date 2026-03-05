# Prometheus Operator — Концепции

## Определения

**Prometheus Operator** — контроллер Kubernetes для автоматизации управления стеком мониторинга (Prometheus, Alertmanager, Grafana). Использует Custom Resource Definitions (CRD) для декларативного управления конфигурацией.

> **См. также:** [Kubernetes Operators](../../Concepts/kubernetes_operators.md), [kube-prometheus-stack](../overview.md).

## Архитектура

Prometheus Operator работает как контроллер Kubernetes:

1. Отслеживает изменения в CRD (ServiceMonitor, PrometheusRule, etc.)
2. Генерирует конфигурацию Prometheus/Alertmanager
3. Создает/обновляет Kubernetes-объекты (StatefulSet, ConfigMap, Secret)
4. Автоматически перезагружает конфигурацию при изменениях

## Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя версия** | `0.89.0` |
| **Репозиторий** | [prometheus-operator/prometheus-operator](https://github.com/prometheus-operator/prometheus-operator) |
| **Минимальный Kubernetes** | 1.16.0 |

> **Важно:** Проверяйте [GitHub Releases](https://github.com/prometheus-operator/prometheus-operator/releases) для получения последних версий.

## Custom Resource Definitions (CRD)

Prometheus Operator использует следующие CRD:

| CRD | Назначение |
| :--- | :--- |
| **Prometheus** | Описание экземпляра Prometheus Server |
| **Alertmanager** | Описание экземпляра Alertmanager |
| **ServiceMonitor** | Описание целей для скрейпинга через Service |
| **PodMonitor** | Описание целей для скрейпинга напрямую из подов |
| **PrometheusRule** | Правила алертинга и записи |
| **Probe** | Blackbox-мониторинг через Blackbox Exporter |
| **AlertmanagerConfig** | Маршрутизация и получатели алертов |

**Подробнее:**

* **[Prometheus CRD](./crd/prometheus.md)**
* **[Alertmanager CRD](./crd/alertmanager.md)**
* **[ServiceMonitor](./crd/servicemonitor.md)**
* **[PodMonitor](./crd/podmonitor.md)**
* **[PrometheusRule](./crd/prometheusrule.md)**
* **[Probe](./crd/probe.md)**
* **[AlertmanagerConfig](./crd/alertmanagerconfig.md)**

## Установка

### Предпочтительный способ: Helm

Используйте [Helm-чарт kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md).

### Ручная установка

См. **[Ручная установка Operator](./installation.md)**.

## Связанные темы

* **[Overview](../overview.md)** — обзор мониторинга в Kubernetes
* **[Service Discovery](./service_discovery.md)** — обнаружение целей
* **[Kube-Prometheus-Stack Helm](./Kube_Prometheus_Stack_Helm/overview.md)** — установка через Helm
* **[Configuration](../configuration.md)** — настройка Prometheus
* **[Rules](../rules.md)** — правила алертинга
