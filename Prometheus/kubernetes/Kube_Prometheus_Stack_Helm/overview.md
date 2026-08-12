# Обзор Helm-чарта kube-prometheus-stack

## Определения

**kube-prometheus-stack (KPS)** — основной Helm-чарт сообщества для развёртывания полной экосистемы наблюдаемости (Observability) в Kubernetes. Управляет жизненным циклом Prometheus, Alertmanager, Grafana и набора экспортеров через декларативную конфигурацию в `values.yaml`.

**Промежуточный чарт (Umbrella Chart)** — архитектурный паттерн Helm, при котором один чарт объединяет несколько независимых субчартов (`grafana`, `kube-state-metrics`, `prometheus-node-exporter`) для упрощения управления зависимостями и общей конфигурацией.

**Prometheus Operator** — ядро стека, обеспечивающее работу Kubernetes-native мониторинга через Custom Resource Definitions (CRD).

> **См. также:** [Мониторинг Kubernetes — общий обзор](../overview.md), [Prometheus Operator](../operator/concepts.md), [Helm](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md).

## Основные концепции

### Актуальные версии (на август 2026 г.)

| Компонент | Версия | Статус |
| :--- | :--- | :--- |
| **Helm-чарт** | 88.1.x+ | Текущий стабильный релиз |
| **Prometheus Server** | 3.12.x+ | Поддержка Remote Write 2.0, Native Histograms |
| **Alertmanager** | 0.32.x+ | Улучшенная кластеризация |
| **Grafana** | 12.4.x+ | Интеграция с Unified Alerting и Alloy |
| **Prometheus Operator** | 0.92.x+ | Поддержка ScrapeConfig и OTLP |
| **Kubernetes** | 1.28 - 1.34 | Рекомендуемый диапазон версий |

> **Важно:** Актуальные спецификации чарта доступны на [Artifact Hub](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack).

### Архитектура стека

| Компонент | Тип объекта | Назначение |
| :--- | :--- | :--- |
| **Prometheus Server** | StatefulSet | Сбор, хранение (TSDB) и обработка метрик. |
| **Alertmanager** | StatefulSet | Дедупликация и маршрутизация оповещений. |
| **Grafana** | Deployment | Визуализация, дашборды, мониторинг алертов. |
| **Prometheus Operator** | Deployment | Автоматизация конфигурации через CRD. |
| **Node Exporter** | DaemonSet | Системные метрики ОС с каждого узла. |
| **Kube-State-Metrics** | Deployment | Генерация метрик на основе объектов API K8s. |
| **Blackbox Exporter** | Deployment | Проверки доступности эндпоинтов (HTTP, TCP). |
| **OTLP Ingest** | Service | (v3.0+) Прием данных напрямую по протоколу OpenTelemetry. |

### Зависимости чарта

Чарт интегрирует следующие субчарты, управление которыми происходит через соответствующие секции в `values.yaml`:

*   `prometheus-node-exporter` (секция `nodeExporter.*`)
*   `kube-state-metrics` (секция `kubeStateMetrics.*`)
*   `grafana` (секция `grafana.*`)
*   `prometheus-windows-exporter` (секция `windowsMonitoring.*`)

### Ключевые ресурсы (CRD)

| Ресурс | Назначение | Подробности |
| :--- | :--- | :--- |
| **ServiceMonitor** | Сбор метрик с Kubernetes Services. | [ServiceMonitor CRD](../operator/crd/servicemonitor.md) |
| **PodMonitor** | Прямой скрейпинг подов (sidecars). | [PodMonitor CRD](../operator/crd/podmonitor.md) |
| **ScrapeConfig** | Произвольные конфигурации скрейпинга (OTLP, внешние цели). | [ScrapeConfig CRD](../operator/crd/scrapeconfig.md) |
| **PrometheusRule** | Описание правил алертинга и агрегации. | [PrometheusRule CRD](../operator/crd/prometheusrule.md) |
| **Probe** | Настройка статических проверок Blackbox Exporter. | [Probe CRD](../operator/crd/probe.md) |
| **AlertmanagerConfig** | Управление маршрутами и получателями алертов. | [AlertmanagerConfig CRD](../operator/crd/alertmanagerconfig.md) |
| **Prometheus** | Декларативное описание инстанса Prometheus Server. | [Prometheus CRD](../operator/crd/prometheus.md) |

## Практические сценарии

### Быстрый старт

```bash
# Создание выделенного пространства имен
kubectl create namespace monitoring

# Добавление репозитория сообщества
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка с настройками по умолчанию
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Рекомендуемый рабочий процесс (GitOps/Local Copy)

Использование локальной копии чарта и плагина `helm-diff` является промышленным стандартом.

```bash
# 1. Скачивание и распаковка чарта
helm pull prometheus-community/kube-prometheus-stack --untar

# 2. Создание файла переопределений
cp kube-prometheus-stack/values.yaml my-values.yaml

# 3. Просмотр планируемых изменений
helm diff upgrade monitoring ./kube-prometheus-stack \
  --namespace monitoring \
  -f my-values.yaml

# 4. Применение изменений
helm upgrade monitoring ./kube-prometheus-stack \
  --namespace monitoring \
  -f my-values.yaml
```

### Диагностика после установки

```bash
# Проверка статуса всех компонентов
kubectl get all -n monitoring -l release=monitoring

# Просмотр логов Prometheus Operator (критично при проблемах с CRD)
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Проверка активных целей (Targets) в Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
# → Открыть http://localhost:9090/targets
```

### Обновление и откат

```bash
# Обновление репозитория
helm repo update

# Обновление релиза
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f my-values.yaml

# Откат к предыдущей версии
helm rollback monitoring -n monitoring
```

### Удаление

```bash
# Удаление релиза
helm uninstall monitoring -n monitoring

# Удаление CRD (осторожно — удалит все Custom Resources!)
kubectl delete crd prometheuses.monitoring.coreos.com
kubectl delete crd alertmanagers.monitoring.coreos.com
kubectl delete crd servicemonitors.monitoring.coreos.com
kubectl delete crd podmonitors.monitoring.coreos.com
kubectl delete crd prometheusrules.monitoring.coreos.com
kubectl delete crd probes.monitoring.coreos.com
kubectl delete crd alertmanagerconfigs.monitoring.coreos.com
```

> **Важно:** Удаление CRD приведёт к потере всех созданных ресурсов мониторинга в кластере.

## Дополнительная информация

### Структура values.yaml (Ключевые секции)

В 2026 году чарт предоставляет расширенные механизмы управления скрейпингом:

```yaml
# Глобальные настройки
global:
  imageRegistry: quay.io # Переопределение для закрытых контуров

# Prometheus Server
prometheus:
  prometheusSpec:
    retention: 30d
    enableFeatures:
      - native-histograms
      - remote-write-receiver
    # Механизм scrapeClasses для переиспользования конфигураций
    scrapeClasses:
      - name: default
        relabelings:
          - action: labelmap
            regex: __meta_kubernetes_pod_label_(.+)
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: premium-rwo
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi

# Grafana (интеграция субчарта)
grafana:
  enabled: true
  adminPassword: "измените_меня"
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      searchNamespace: ALL

# Автоматический мониторинг компонентов K8s
kubeApiServer:
  enabled: true
kubeEtcd:
  enabled: true
```

### Рекомендуемые ресурсы (Medium Cluster)

Данные актуальны для Prometheus 3.x с учетом использования Native Histograms.

| Компонент | CPU Request | Memory Request | CPU Limit | Memory Limit |
| :--- | :--- | :--- | :--- | :--- |
| **Prometheus** | 500m | 2Gi | 2000m | 8Gi |
| **Alertmanager** | 100m | 256Mi | 500m | 512Mi |
| **Grafana** | 200m | 512Mi | 1000m | 1Gi |
| **Operator** | 100m | 128Mi | 200m | 256Mi |

### Рекомендации по безопасности

1.  **High Availability (HA):** Всегда устанавливайте `prometheus.prometheusSpec.replicas: 2` и `alertmanager.alertmanagerSpec.replicas: 3` для production-сред.
2.  **RBAC:** Используйте `serviceAccounts` с ограниченными правами для экспортеров.
3.  **Network Policies:** Включайте изоляцию трафика мониторинга:
    ```yaml
    prometheus:
      networkPolicy:
        enabled: true
    ```

### Связанные темы

* [Файлы конфигурации компонентов](./other_components_config.md) — детализация разделов `values.yaml`
* [Практические сценарии](./practical_scenarios.md) — специфические кейсы установки
* [Масштабирование](../../scaling/overview.md) — федерация и Remote Write
* [Безопасность оператора](../operator/Security/index.md) — защита в Kubernetes
