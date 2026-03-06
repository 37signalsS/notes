# Установка Grafana Alloy в Kubernetes

## Обзор

**Grafana Alloy** — универсальный агент для сбора телеметрии (метрики, логи, трассировки), рекомендуемый для новых развертываний вместо Promtail.

> **⚠️ Важно:** Promtail находится в статусе deprecated (весна 2026). Для новых развертываний используйте Grafana Alloy.

## Преимущества Alloy

* **Универсальность:** метрики + логи + трассировки
* **Активная разработка:** официальная поддержка Grafana Labs
* **Конвертеры конфигураций:** автоматическая миграция с Promtail/Grafana Agent
* **Язык River:** декларативный язык конфигурации (похож на Terraform)

**Подробнее:** [Grafana Alloy Overview](../../Grafana/grafana_alloy_overview.md)

## Подготовка

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

## Настройка Values для Alloy

```bash
helm show values grafana/alloy > alloy_values.yaml
```

### Пример `alloy_values.yaml` для сбора логов

```yaml
# alloy_values.yaml
alloy:
  configMap:
    create: true
    content: |
      // Сбор логов из подов Kubernetes
      discovery.kubernetes "pods" {
        role = "pod"
      }

      loki.source.kubernetes "pods" {
        targets    = discovery.kubernetes.pods.targets
        forward_to = [loki.write.default.receiver]
      }

      // Отправка в Loki
      loki.write "default" {
        endpoint {
          url = "http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push"
        }
      }

controller:
  type: daemonset  # DaemonSet для сбора логов со всех нод

tolerations:
  - operator: "Exists"
```

### Конфигурация для различных сценариев

#### Сбор логов с файлов

```river
local.file "var_log" {
  path      = "/var/log/*.log"
  type      = "text"
  forward_to = [loki.source.file.logs.receiver]
}

loki.source.file "logs" {
  targets    = local.file.var_log.targets
  forward_to = [loki.write.default.receiver]
}
```

#### Сбор метрик Prometheus

```river
discovery.kubernetes "pods" {
  role = "pod"
}

prometheus.scrape "pods" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [prometheus.remote_write.default.receiver]
}
```

## Установка Alloy

Установим Alloy с помощью Helm в `logging` namespace:

```bash
helm upgrade --install alloy grafana/alloy \
  --namespace logging \
  -f alloy_values.yaml
```

### Проверка статуса

```bash
# Проверка подов
kubectl get pods -n logging -l app.kubernetes.io/name=alloy

# Детальная информация
kubectl describe daemonset -n logging -l app.kubernetes.io/name=alloy

# Логи Alloy
kubectl logs -n logging -l app.kubernetes.io/name=alloy -f
```

## Миграция с Promtail

Grafana предоставляет конвертер конфигураций Promtail → Alloy:

```bash
# Использование конвертера (онлайн)
# https://grafana.com/docs/alloy/latest/tasks/migrate-from-promtail/
```

## Связанные темы

* **[Обзор Grafana Loki](../loki_overview.md)** — архитектура, LogQL
* **[Установка Promtail](promtail_installation.md)** — устаревший агент
* **[Grafana Alloy Overview](../../Grafana/grafana_alloy_overview.md)** — подробная информация об Alloy
