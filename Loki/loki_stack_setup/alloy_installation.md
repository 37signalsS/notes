# Установка Grafana Alloy в Kubernetes

## Определения

**Grafana Alloy** — универсальный агент для сбора и обработки телеметрии (метрики, логи, трассировки, профили). Использует декларативный язык конфигурации River, который позволяет строить сложные конвейеры обработки данных (DAG). Alloy является официальным преемником Promtail и Grafana Agent, обеспечивая нативную поддержку OpenTelemetry и бесшовную интеграцию со стеком Grafana (Loki, Mimir, Tempo, Phlare).

**Статус агентов (2026):**
- **Promtail:** В статусе Deprecated (с весны 2026). Поддержка ограничена критическими багфиксами.
- **Grafana Agent:** В статусе End-of-Life. Рекомендуется немедленная миграция на Alloy.
- **Grafana Alloy:** Стандарт индустрии для сбора телеметрии в облачных и гибридных средах.

**Подробнее:** [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md)

## Основные концепции

### Архитектура развертывания в Kubernetes

| Режим | Тип контроллера | Назначение |
| :--- | :--- | :--- |
| **DaemonSet** | DaemonSet | Сбор системных логов (`/var/log/pods`), метрик нод (`node-exporter`) и eBPF данных. |
| **Deployment** | Deployment | Сбор метрик сервисов (Pull), прием OTLP трафика, работа в качестве OpenTelemetry Collector. |
| **StatefulSet** | StatefulSet | Кластерный режим с сохранением состояния (позиции логов, кеши) и высокой доступностью. |

### Язык конфигурации River

River базируется на блоках, аргументах и атрибутах. Основная ценность — динамическое обновление конфигурации без перезагрузки процесса (`hot reload`).

**Типовые стадии обработки (DAG):**
1. **Discovery:** Автоматическое обнаружение целей (Kubernetes API, статические списки).
2. **Scrape / Source:** Извлечение данных из целей.
3. **Transform / Relabel:** Изменение структуры, фильтрация, обогащение метаданными.
4. **Export / Write:** Отправка данных в один или несколько бэкендов.

## Практические сценарии

### Подготовка репозитория Helm

```bash
# Добавление официального репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Получение актуальных значений чарта
helm show values grafana/alloy > alloy_values.yaml
```

### Сценарий 1: Сбор логов Kubernetes с поддержкой Loki 3.x

Использование структурированных метаданных для уменьшения кардинальности индекса.

**Конфигурация River:**

```river
// Обнаружение всех подов в кластере
discovery.kubernetes "all_pods" {
  role = "pod"
}

// Сбор логов
loki.source.kubernetes "container_logs" {
  targets    = discovery.kubernetes.all_pods.targets
  forward_to = [loki.process.add_metadata.receiver]
}

// Обработка и добавление структурированных метаданных (Loki 3.0+)
loki.process "add_metadata" {
  forward_to = [loki.write.loki_backend.receiver]

  stage.relabel {
    rule {
      source_labels = ["__meta_kubernetes_namespace"]
      target_label  = "namespace"
    }
    rule {
      source_labels = ["__meta_kubernetes_pod_name"]
      target_label  = "pod"
    }
  }
}

// Отправка данных
loki.write "loki_backend" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
    // Включение структурированных метаданных для оптимизации хранилища
    allow_structured_metadata = true
  }
}
```

### Сценарий 2: Авто-инструментирование через eBPF (Application Observability)

**Требования:** ядро Linux 5.8+, привилегированный режим (CAP_SYS_ADMIN).

```river
// Сбор сетевых метрик без модификации кода
otelcol.receiver.ebpf "network_telemetry" {
  network_interface = "eth0"
  forward_to        = [otelcol.exporter.otlp.tempo.receiver]
}

// Отправка трасс в Tempo
otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo-distributor.tracing.svc.cluster.local:4317"
    tls { insecure = true }
  }
}
```

### Сценарий 3: Мультиарендность (Multi-tenancy)

Разделение потоков данных для разных команд через заголовки.

```river
loki.write "team_a" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
    headers = {
      "X-Scope-OrgID" = "team-alpha",
    }
  }
}

loki.write "team_b" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
    headers = {
      "X-Scope-OrgID" = "team-beta",
    }
  }
}
```

## Безопасность и права доступа (RBAC)

Для работы Discovery Alloy требуются права на чтение ресурсов Kubernetes API.

**Пример ClusterRole в чарте:**
```yaml
controller:
  rbac:
    create: true
  serviceAccount:
    create: true
    name: "alloy-collector"
```
По умолчанию Alloy запрашивает доступ к `pods`, `nodes`, `services`, `endpoints`, `configmaps`. Для eBPF необходимо дополнительно включить `privileged: true` в `securityContext`.

## Мониторинг и эксплуатация

### Интеграция с Prometheus Operator

Для сбора метрик самого Alloy (состояние компонентов, ошибки конвейера):

```yaml
# values.yaml
alloy:
  metrics:
    enabled: true
  serviceMonitor:
    enabled: true
    interval: 30s
```

### Проверка работоспособности

1.  **UI отладки:** `kubectl port-forward svc/alloy 12345:12345`.
    *   `Graph`: Визуализация DAG и связей компонентов.
    *   `Status`: Здоровье каждого отдельного блока River.
2.  **Проверка логов:** `kubectl logs -l app.kubernetes.io/name=alloy -f`.

### Устранение неисправностей

| Ошибка | Возможная причина | Путь решения |
| :--- | :--- | :--- |
| **Component unhealthy** | Ошибка в аргументах блока (например, неверный URL) | Проверьте UI (вкладка Status) — там будет детальное описание ошибки. |
| **OOMKilled** | Слишком много целей в discovery или большой объем логов в памяти | Увеличьте `memory.limits` или используйте `clustering` для распределения нагрузки. |
| **Permission denied (eBPF)** | Недостаточно прав у контейнера | Убедитесь, что установлены `privileged: true` и нужные `capabilities`. |

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md) | Архитектура и сравнение с другими агентами |
| [Установка Loki](loki_installation.md) | Настройка бэкенда для приема логов от Alloy |
| [Примеры LogQL](logql_examples.md) | Язык запросов для анализа логов, собранных Alloy |
| [Миграция с Promtail](https://grafana.com/docs/alloy/latest/tasks/migrate/from-promtail/) | Пошаговое руководство по переходу на River |
| [Alloy на Minikube](../../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_lgtm_stack_deployment.md) | Полный цикл развертывания в тестовой среде |
