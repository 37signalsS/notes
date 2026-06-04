# Установка Grafana Alloy в Kubernetes

## Определения

**Grafana Alloy** — универсальный агент для сбора телеметрии (метрики, логи, трассировки, профили), рекомендуемый для новых развертываний вместо Promtail и Grafana Agent.

> **Примечание:** Promtail в статусе deprecated (весна 2026), Grafana Agent (static mode) — deprecated (ноябрь 2025). Для новых развертываний используйте Grafana Alloy.

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
// Обнаружение подов Kubernetes
discovery.kubernetes "pods" {
  role = "pod"
}

// Сбор логов из обнаруженных подов
loki.source.kubernetes "pods" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.write.default.receiver]
}

// Отправка логов в Loki
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
      // Обнаружение подов Kubernetes
      discovery.kubernetes "pods" {
        role = "pod"
      }

      // Сбор логов из обнаруженных подов
      loki.source.kubernetes "pods" {
        targets    = discovery.kubernetes.pods.targets
        forward_to = [loki.write.default.receiver]
      }

      // Отправка логов в Loki
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
// Обнаружение логов в файловой системе ноды
discovery.file "var_log" {
  path_targets = [{
    __path__ = "/var/log/*.log",
    "job"    = "node-logs",
  }]
}

// Чтение обнаруженных файлов
loki.source.file "logs" {
  targets    = discovery.file.var_log.targets
  forward_to = [loki.write.default.receiver]
}

// Отправка данных в Loki
loki.write "default" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push"
  }
}
```

### Сценарий 3: Сбор метрик Prometheus

```river
// Обнаружение подов Kubernetes
discovery.kubernetes "pods" {
  role = "pod"
}

// Скрапинг метрик Prometheus из подов
prometheus.scrape "pods" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [prometheus.remote_write.default.receiver]
}

// Отправка метрик в хранилище (Mimir/Prometheus)
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

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в статусе Pending** | Недостаточно ресурсов или ошибки планировщика | Проверьте `kubectl describe pod` и лимиты ресурсов |
| **Логи не доходят до Loki** | Неверный URL в `loki.write` или сетевые ошибки | Проверьте доступность Loki через `curl` из пода Alloy |
| **Ошибка парсинга River** | Синтаксическая ошибка в конфигурации | Проверьте логи Alloy: там указана строка с ошибкой |
| **Пропуски в логах** | Высокая нагрузка или сбои в `positions` | Увеличьте лимиты ресурсов (CPU/Memory) |

## Дополнительная информация

### Рекомендуемые ресурсы

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md) | Архитектура, язык River, сравнение с OTel Collector |
| [Документация Alloy](https://grafana.com/docs/alloy/latest/) | Официальная документация Grafana Labs |
| [Конвертер Promtail → Alloy](https://grafana.com/docs/alloy/latest/tasks/migrate-from-promtail/) | Миграция конфигураций |
| [Обзор Loki](../loki_overview.md) | Архитектура, LogQL |
| [Установка Promtail](promtail_installation.md) | Устаревший агент (deprecated) |
ted) |
