# Интеграция Grafana с Prometheus Operator

## Определения

**Grafana в Prometheus Operator** — Grafana не имеет собственного CRD в Prometheus Operator. Визуализация и provisioning управляются через механизм ConfigMap с лейблами + Grafana Sidecar, который разворачивается в составе Helm-чарта kube-prometheus-stack.

> **См. также:** [Обзор Grafana](../../../Grafana/grafana_overview.md), [Концепции Prometheus Operator](./concepts.md).

## Основные концепции

### Почему нет CRD для Grafana

Prometheus Operator фокусируется на управлении компонентами мониторинга через CRD (Prometheus, Alertmanager, ServiceMonitor, etc.). Grafana — отдельный продукт, который интегрируется через стандартные механизмы Kubernetes:

- **ConfigMap с лейблами** — обнаружение дашбордов и источников данных
- **Sidecar-контейнер** — автоматическая загрузка ресурсов в Grafana
- **Helm values.yaml** — конфигурация Grafana при установке

### Архитектура интеграции

```
ConfigMap (label: grafana_dashboard: "1")
         ↓
Grafana Sidecar (k8s-sidecar контейнер в Pod Grafana)
         ↓
Grafana (автоматическая загрузка дашбордов и datasource)
```

### Ключевые компоненты

| Компонент | Назначение | SSoT |
|---|---|---|
| ConfigMap + лейблы | Хранение JSON-дашбордов и datasource-конфигураций | [Provisioning через ConfigMap](../../../Grafana/dashboards/provisioning_configmap.md) |
| Grafana Sidecar | Обнаружение и загрузка ConfigMap в Grafana | [Конфигурация Grafana](../Kube_Prometheus_Stack_Helm/grafana_config.md) |
| Helm values.yaml | Общая конфигурация Grafana | [Конфигурация Grafana](../Kube_Prometheus_Stack_Helm/grafana_config.md) |
| Файловый provisioning | Провиженинг через YAML/JSON в `/etc/grafana/provisioning` | [Grafana Provisioning](../../../Grafana/grafana_provisioning.md) |

## Практические сценарии

Сценарии использования описаны в SSoT-файлах:

- **Создание ConfigMap с дашбордом** → [Provisioning через ConfigMap](../../../Grafana/dashboards/provisioning_configmap.md)
- **Настройка sidecar (label, searchNamespace)** → [Конфигурация Grafana](../Kube_Prometheus_Stack_Helm/grafana_config.md)
- **Провиженинг datasource (Prometheus, Loki)** → [Источники данных Grafana](../../../Grafana/grafana_datasources.md)
- **Полная конфигурация Grafana (PV, Ingress, HA)** → [Конфигурация Grafana](../Kube_Prometheus_Stack_Helm/grafana_config.md)
- **Файловый провижининг (standalone, Docker)** → [Grafana Provisioning](../../../Grafana/grafana_provisioning.md)

## Дополнительная информация

### Встроенные дашборды kube-prometheus-stack

Helm-чарт kube-prometheus-stack включает предустановленные дашборды:

- Kubernetes / Compute Resources / Cluster
- Kubernetes / Compute Resources / Namespace (pods)
- Kubernetes / Compute Resources / Node (pods)
- Prometheus / Overview
- Alertmanager / Overview

> Подробный список и настройка — в [Конфигурация Grafana](../Kube_Prometheus_Stack_Helm/grafana_config.md).

### Связанные темы

- **[Концепции Prometheus Operator](./concepts.md)** — CRD и архитектура
- **[Установка Prometheus Operator](./installation.md)** — установка и настройка
- **[Grafana Provisioning](../../../Grafana/grafana_provisioning.md)** — общий провижининг Grafana
- **[Provisioning дашбордов через ConfigMap](../../../Grafana/dashboards/provisioning_configmap.md)** — sidecar-механизм
- **[Конфигурация Grafana в kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/grafana_config.md)** — Helm-параметры
- **[Источники данных Grafana](../../../Grafana/grafana_datasources.md)** — Prometheus, Loki, и др.
