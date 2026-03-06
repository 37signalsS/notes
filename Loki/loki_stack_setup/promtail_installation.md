# Установка Promtail в Kubernetes

> **⚠️ Важно:** Promtail находится в статусе deprecated (весна 2026). Для новых развертываний рекомендуется использовать **[Grafana Alloy](./alloy_installation.md)**.

## Подготовка

Promtail — это агент для сбора логов, который будет работать как DaemonSet на каждой ноде кластера и отправлять логи в Loki.

## Настройка Values для Promtail

Сохраним `values` для чарта `grafana/promtail`:

```bash
helm show values grafana/promtail > promtail_values.yaml
```

### Актуальные параметры для Promtail 6.x

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| **`config.lokiAddress`** | Адрес Loki | `http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push` |
| **`tolerations`** | Толерации для всех нод | `- operator: "Exists"` |
| **`serviceMonitor.enabled`** | ServiceMonitor для Prometheus | `true` |
| **`config.snippets.scrape_configs`** | Кастомизация scrape_configs | См. ниже |

### Пример `promtail_values.yaml`

```yaml
# promtail_values.yaml
config:
  lokiAddress: http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push

  snippets:
    scrape_configs:
      - job_name: kubernetes-pods
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: true
          - source_labels: [__meta_kubernetes_pod_namespace]
            target_label: namespace
          - source_labels: [__meta_kubernetes_pod_name]
            target_label: pod
          - source_labels: [__meta_kubernetes_pod_container_name]
            target_label: container

# Толерации для запуска на всех нодах (включая master)
tolerations:
  - operator: "Exists"

# ServiceMonitor для мониторинга самого Promtail
serviceMonitor:
  enabled: true
  namespace: logging
  labels:
    release: prometheus
```

## Установка Promtail

Установим Promtail, применив измененные `values`:

```bash
helm upgrade --install promtail grafana/promtail \
  --namespace logging \
  -f promtail_values.yaml
```

### Проверка статуса

```bash
# Проверка подов
kubectl get pods -n logging -l app.kubernetes.io/name=promtail -o wide

# Детальная информация
kubectl describe daemonset -n logging -l app.kubernetes.io/name=promtail
```

## Альтернатива: Grafana Alloy

Для новых развертываний рекомендуется использовать **Grafana Alloy** вместо Promtail.

**Преимущества Alloy:**

* Универсальный агент (метрики + логи + трассировки)
* Активная разработка и поддержка
* Конвертеры конфигураций с Promtail/Grafana Agent
* Язык конфигурации River (декларативный, похож на Terraform)

**Подробнее:** [Установка Grafana Alloy](./alloy_installation.md)

## Связанные темы

* **[Обзор Grafana Loki](../loki_overview.md)** — архитектура, LogQL
* **[Установка Loki](loki_installation.md)** — установка Loki
* **[Установка Grafana Alloy](alloy_installation.md)** — современная альтернатива Promtail
