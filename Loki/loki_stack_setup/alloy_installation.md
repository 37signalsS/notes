# Установка Grafana Alloy в Kubernetes

## Определения

**Grafana Alloy** — универсальный агент для сбора телеметрии (метрики, логи, трассировки, профили), рекомендуемый для новых развертываний вместо Promtail и Grafana Agent.

> **⚠️ Важно:** Promtail в статусе deprecated (весна 2026), Grafana Agent (static mode) — deprecated (ноябрь 2025). Для новых развертываний используйте Grafana Alloy.

**Подробнее:** [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md)

## Основные концепции

### Архитектура развертывания в Kubernetes

| Компонент | Тип контроллера | Назначение |
| :--- | :--- | :--- |
| **Alloy** | DaemonSet | Сбор логов с файлов на нодах |
| **Alloy** | Deployment | Сбор метрик из подов, трассировок |
| **Alloy** | StatefulSet | Агрегация данных в кластерном режиме |

### Язык конфигурации River

Alloy использует River (диалект HCL) для описания графа компонентов. Поток данных: `discovery` → `source` → `process` → `write`.

**Пример базового потока:**

```river
discovery.kubernetes "pods" {
  role = "pod"
}

loki.source.kubernetes "pods" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.write.default.receiver]
}

loki.write "default" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push"
  }
}
```

## Практические сценарии

### Подготовка репозитория Helm

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm show values grafana/alloy > alloy_values.yaml
```

### Сценарий 1: Сбор логов из подов Kubernetes

**Файл `alloy_values.yaml`:**

```yaml
alloy:
  configMap:
    create: true
    content: |
      discovery.kubernetes "pods" {
        role = "pod"
      }

      loki.source.kubernetes "pods" {
        targets    = discovery.kubernetes.pods.targets
        forward_to = [loki.write.default.receiver]
      }

      loki.write "default" {
        endpoint {
          url = "http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push"
        }
      }

controller:
  type: daemonset

tolerations:
  - operator: "Exists"
```

### Сценарий 2: Сбор логов с файлов на нодах

```river
discovery.file "var_log" {
  path_targets = [{
    __path__ = "/var/log/*.log",
    "job"    = "node-logs",
  }]
}

loki.source.file "logs" {
  targets    = discovery.file.var_log.targets
  forward_to = [loki.write.default.receiver]
}

loki.write "default" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push"
  }
}
```

### Сценарий 3: Сбор метрик Prometheus

```river
discovery.kubernetes "pods" {
  role = "pod"
}

prometheus.scrape "pods" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [prometheus.remote_write.default.receiver]
}

prometheus.remote_write "default" {
  endpoint {
    url = "http://mimir-gateway.monitoring.svc.cluster.local:9009/api/v1/push"
  }
}
```

### Установка Alloy

```bash
helm upgrade --install alloy grafana/alloy \
  --namespace logging \
  --create-namespace \
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

### Миграция с Promtail

Grafana предоставляет онлайн-конвертер конфигураций: [Migrate from Promtail to Alloy](https://grafana.com/docs/alloy/latest/tasks/migrate-from-promtail/)

**Процесс миграции:**
1. Экспортируйте текущую конфигурацию Promtail (`promtail.yaml`).
2. Конвертируйте через онлайн-инструмент.
3. Протестируйте новую конфигурацию в staging.
4. Обновите Helm-релиз с новой конфигурацией Alloy.

## Дополнительная информация

### Рекомендуемые ресурсы

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md) | Архитектура, язык River, сравнение с OTel Collector |
| [Документация Alloy](https://grafana.com/docs/alloy/latest/) | Официальная документация Grafana Labs |
| [Конвертер Promtail → Alloy](https://grafana.com/docs/alloy/latest/tasks/migrate-from-promtail/) | Миграция конфигураций |
| [Обзор Loki](../loki_overview.md) | Архитектура, LogQL |
| [Установка Promtail](promtail_installation.md) | Устаревший агент (deprecated) |
