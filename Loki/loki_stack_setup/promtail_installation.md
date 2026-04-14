# Установка Promtail в Kubernetes (Legacy)

## Определения

**Promtail** — специализированный агент для сбора логов и отправки в Loki. Работает как DaemonSet на каждой ноде кластера.

> **⚠️ Deprecated (весна 2026):** Поддержка Promtail прекращена. Для новых развертываний используйте [Grafana Alloy](alloy_installation.md). Данный файл сохранён для поддержки legacy-систем.

**Статус:** Helm-чарт `grafana/promtail` более не обновляется. Новые версии не выпускаются.

**Подробнее:** [Статус агентов сбора](../loki_overview.md#важные-изменения)

## Основные концепции

### Архитектура Promtail

```
┌─────────────┐     ┌──────────────┐     ┌─────────┐
│ Файлы логов │────→│   Promtail   │────→│  Loki   │
│ /var/log/*  │     │  (DaemonSet) │     │ Gateway │
└─────────────┘     └──────────────┘     └─────────┘
     │                     │
     │              positions.yaml
     │            (отслеживание чтения)
```

### Ключевые компоненты конфигурации

| Компонент | Назначение |
| :--- | :--- |
| **`clients`** | Адрес Loki для отправки логов |
| **`scrape_configs`** | Обнаружение и сбор логов из подов |
| **`relabel_configs`** | Добавление меток (namespace, pod, container) |
| **`positions`** | Файл отслеживания прочитанных позиций |

### Отличия от Grafana Alloy

| Характеристика | Promtail | Grafana Alloy |
| :--- | :--- | :--- |
| **Тип данных** | Только логи | Логи + метрики + трассировки |
| **Язык конфигурации** | YAML | River (HCL) |
| **Статус** | ⚠️ Deprecated | ✅ Активно развивается |
| **Миграция** | — | Встроенный конвертер Promtail → Alloy |

## Практические сценарии

### Сценарий 1: Установка Promtail для существующих систем

> Используйте только для поддержки legacy-окружений. Для новых — [Alloy](alloy_installation.md).

**Подготовка:**

```bash
# Legacy-репозиторий (более не обновляется)
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm show values grafana/promtail > promtail_values.yaml
```

**Файл `promtail_values.yaml`:**

```yaml
config:
  clients:
    - url: http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push

  snippets:
    scrape_configs:
      - job_name: kubernetes-pods
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: "true"
          - source_labels: [__meta_kubernetes_pod_namespace]
            target_label: namespace
          - source_labels: [__meta_kubernetes_pod_name]
            target_label: pod
          - source_labels: [__meta_kubernetes_pod_container_name]
            target_label: container
          - replace: /var/log/pods/*$1/*.log
            separator: /
            source_labels:
              - __meta_kubernetes_pod_uid
              - __meta_kubernetes_pod_container_name
            target_label: __path__

# Толерации для всех нод (включая master)
tolerations:
  - operator: "Exists"

# ServiceMonitor для мониторинга Promtail
serviceMonitor:
  enabled: true
  namespace: logging
  labels:
    release: prometheus
```

**Установка:**

```bash
helm upgrade --install promtail grafana/promtail \
  --namespace logging \
  -f promtail_values.yaml
```

### Сценарий 2: Проверка статуса

```bash
# Проверка подов
kubectl get pods -n logging -l app.kubernetes.io/name=promtail -o wide

# Детали DaemonSet
kubectl describe daemonset -n logging -l app.kubernetes.io/name=promtail

# Логи Promtail
kubectl logs -n logging -l app.kubernetes.io/name=promtail -f
```

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod не запускается** | Нет tolerations для master-нод | Добавьте `tolerations: - operator: "Exists"` |
| **Логи не отправляются** | Неправильный URL Loki | Проверьте `kubectl exec` и curl до Loki |
| **Дубликаты логов** | Сбой positions-файла | Удалите positions.yaml и перезапустите под |
| **413 Request Too Large** | Превышен размер батча | Уменьшите `clients.batch_wait` или увеличьте лимит Loki |

### Сценарий 3: Миграция на Grafana Alloy

**Процесс миграции:**

1. **Экспортируйте конфигурацию Promtail:**

```bash
kubectl get configmap -n logging -l app.kubernetes.io/name=promtail -o yaml > promtail_config.yaml
```

1. **Конвертируйте через онлайн-инструмент:**

Используйте [конвертер Promtail → Alloy](https://grafana.com/docs/alloy/latest/tasks/migrate/) для автоматической трансляции YAML в River.

1. **Протестируйте Alloy в staging:**

```bash
helm install alloy-test grafana-community/alloy \
  --namespace logging-test \
  -f converted_alloy_values.yaml
```

1. **Переключите трафик на Alloy:**

Убедитесь, что Alloy собирает те же логи, затем удалите Promtail:

```bash
helm uninstall promtail -n logging
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Установка Grafana Alloy](alloy_installation.md) | Рекомендуемый агент для новых развертываний |
| [Конвертер Promtail → Alloy](https://grafana.com/docs/alloy/latest/tasks/migrate/) | Автоматическая миграция конфигурации |
| [Обзор Loki](../loki_overview.md) | Архитектура, LogQL, статус агентов |
| [Установка Loki](loki_installation.md) | Развертывание бэкенда Loki |
| [Grafana Alloy Overview](../../Grafana/grafana_alloy_overview.md) | Полный обзор Alloy и язык River |
