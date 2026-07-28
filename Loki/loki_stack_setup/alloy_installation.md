# Установка Grafana Alloy в Kubernetes

## Определения

**Grafana Alloy** — универсальный агент для сбора телеметрии (метрики, логи, трассировки, профили), использующий декларативный язык конфигурации River. Alloy является официальным преемником Promtail и Grafana Agent, обеспечивая нативную поддержку OpenTelemetry и глубокую интеграцию со стеком Grafana (Loki, Mimir, Tempo).

**Статус агентов (2026):**
- **Promtail:** В статусе Deprecated (с весны 2026).
- **Grafana Agent (Static Mode):** В статусе Deprecated (с конца 2025).
- **Grafana Alloy:** Рекомендуемый стандарт для всех новых инсталляций.

**Подробнее:** [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md)

## Основные концепции

### Архитектура развертывания в Kubernetes

В зависимости от задач, Alloy может быть развернут в различных режимах:

| Режим | Тип контроллера | Назначение |
| :--- | :--- | :--- |
| **DaemonSet** | DaemonSet | Сбор логов с файлов на нодах, метрик ресурсов нод и данных eBPF |
| **Deployment** | Deployment | Сбор метрик из подов (Pull модель), прием трассировок по OTLP |
| **Clustered** | StatefulSet / Deployment | Агрегация данных, работа в режиме высокой доступности (HA) с балансировкой нагрузки |

### Язык конфигурации River

River — это HCL-подобный язык, ориентированный на построение графа компонентов (DAG). Компоненты соединяются между собой, передавая данные от источников к приемникам.

**Типовой конвейер:**
1. **Discovery:** Обнаружение объектов (подов, сервисов, файлов).
2. **Source:** Чтение данных из обнаруженных объектов.
3. **Process:** Фильтрация, трансформация и перемаркировка меток.
4. **Write:** Отправка данных в хранилище.

## Практические сценарии

### Подготовка репозитория Helm

```bash
# Добавление официального репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Просмотр доступных параметров конфигурации
helm show values grafana/alloy > alloy_values.yaml
```

### Сценарий 1: Сбор логов Kubernetes с перемаркировкой меток

Этот сценарий описывает сбор логов из контейнеров с обогащением данных метаданными (namespace, pod_name, container_name).

**Конфигурация River (внутри `alloy_values.yaml`):**

```river
// 1. Обнаружение подов на текущей ноде
discovery.kubernetes "pods" {
  role = "pod"
}

// 2. Чтение логов из файлов контейнеров
loki.source.kubernetes "container_logs" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [loki.relabel.kubernetes_metadata.receiver]
}

// 3. Обогащение меток
loki.relabel "kubernetes_metadata" {
  forward_to = [loki.write.loki_backend.receiver]

  rule {
    source_labels = ["__meta_kubernetes_namespace"]
    target_label  = "namespace"
  }
  rule {
    source_labels = ["__meta_kubernetes_pod_name"]
    target_label  = "pod"
  }
  rule {
    source_labels = ["__meta_kubernetes_pod_container_name"]
    target_label  = "container"
  }
}

// 4. Отправка в Loki
loki.write "loki_backend" {
  endpoint {
    url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
  }
}
```

### Сценарий 2: Авто-инструментирование через eBPF (Loki 3.x+)

Alloy позволяет собирать сетевые метрики и трейсы без модификации кода приложения с помощью eBPF.

```river
// Сбор сетевых метрик через eBPF
otelcol.receiver.ebpf "network_metrics" {
  network_interface = "eth0"
  forward_to        = [otelcol.exporter.prometheus.default.receiver]
}

// Преобразование в формат Prometheus
otelcol.exporter.prometheus "default" {
  forward_to = [prometheus.remote_write.mimir.receiver]
}
```

### Сценарий 3: Кластеризация и высокая доступность

Для масштабирования Alloy и обеспечения отказоустойчивости используется встроенный механизм кластеризации.

**Настройка в `values.yaml`:**

```yaml
alloy:
  clustering:
    enabled: true
  configMap:
    create: true
    content: |
      // Конфигурация, использующая кластерные возможности
      prometheus.scrape "k8s_metrics" {
        targets    = discovery.kubernetes.pods.targets
        forward_to = [prometheus.remote_write.mimir.receiver]
        clustering {
          enabled = true
        }
      }
```

### Установка в кластер

```bash
# Установка Alloy в режиме DaemonSet для сбора логов
helm upgrade --install alloy grafana/alloy \
  --namespace logging \
  --create-namespace \
  -f alloy_values.yaml \
  --wait --atomic
```

### Проверка работоспособности

```bash
# Проверка состояния подов
kubectl get pods -n logging -l app.kubernetes.io/name=alloy

# Доступ к UI Alloy для отладки графа компонентов (через port-forward)
kubectl port-forward -n logging svc/alloy 12345:12345
# → Откройте http://localhost:12345 для просмотра Graph и статуса компонентов
```

### Устранение неисправностей

| Проблема | Возможная причина | Путь решения |
| :--- | :--- | :--- |
| **Pod в статусе CrashLoopBackOff** | Ошибка синтаксиса в River-конфигурации | Проверьте логи: `kubectl logs -l app.kubernetes.io/name=alloy`. Alloy укажет на строку с ошибкой. |
| **Метки не добавляются** | Ошибка в блоке `loki.relabel` | Убедитесь, что `source_labels` соответствуют внутренним метаданным Kubernetes. |
| **Высокое потребление памяти** | Слишком большой объем `positions` или кэша | Увеличьте лимиты ресурсов или настройте более агрессивную ротацию логов. |
| **Проблемы с кластеризацией** | Нет сетевой связности между подами Alloy | Проверьте NetworkPolicies и работу внутреннего DNS кластера. |

## Дополнительная информация

### Рекомендуемые ресурсы

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Grafana Alloy](../../Grafana/grafana_alloy_overview.md) | Архитектура, принципы работы и сравнение с другими агентами |
| [Официальная документация Alloy](https://grafana.com/docs/alloy/latest/) | Полный справочник по компонентам и функциям |
| [Конвертер конфигураций](https://grafana.com/docs/alloy/latest/tasks/migrate/) | Инструмент для автоматического перехода с Promtail и Grafana Agent |
| [Обзор Loki](../loki_overview.md) | Архитектура системы хранения логов |
| [Установка Promtail](promtail_installation.md) | Руководство по устаревшему агенту (только для legacy-систем) |
