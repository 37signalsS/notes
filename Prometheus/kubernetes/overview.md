# Мониторинг Kubernetes: Обзор

## Определения

**Мониторинг Kubernetes** — комплексная практика наблюдения за состоянием инфраструктуры кластера (Control Plane, Worker Nodes) и развернутых приложений (Workloads) с использованием метрик, логов и трассировок.

**Prometheus Operator** — специализированный Kubernetes-контроллер, автоматизирующий жизненный цикл стека мониторинга через Custom Resource Definitions (CRD). Реализует паттерн «Оператор» для управления Prometheus, Alertmanager и сопутствующими компонентами.

**Prometheus Agent Mode** — режим работы Prometheus (с версии 2.32+, стабилизирован в 3.0), оптимизированный для сбора метрик и их немедленной отправки через Remote Write 2.0 без локального хранения в TSDB. Идеален для Edge-кластеров.

**kube-prometheus-stack** — основной Helm-чарт сообщества для развёртывания полной экосистемы наблюдаемости (Prometheus, Alertmanager, Grafana, Prometheus Operator и экспортеры) в Kubernetes.

**ScrapeConfig** — современный CRD (введен в v0.65+), позволяющий описывать произвольные конфигурации скрейпинга, которые не вписываются в модель ServiceMonitor/PodMonitor (например, внешние статические цели или специфичные настройки Discovery).

> **См. также:** [kube-prometheus-stack — Helm](./Kube_Prometheus_Stack_Helm/overview.md), [Prometheus Operator](./operator/concepts.md), [Service Discovery](./service_discovery.md).

## Основные концепции

### Экосистема Prometheus в Kubernetes

*   **[Prometheus Server](../overview.md):** Полнофункциональный инстанс для сбора, хранения (TSDB) и обработки метрик. В K8s обычно разворачивается как StatefulSet для сохранения данных.
*   **[Prometheus Agent Mode](../overview.md):** Легковесный коллектор для мультикластерных сред или сред с ограниченными ресурсами.
*   **[Alertmanager](../alertmanager.md):** Компонент для дедупликации, группировки и маршрутизации уведомлений внешним потребителям (Slack, Telegram, PagerDuty).
*   **[Экспортеры](../Exporters/overview.md):** Адаптеры для сбора метрик (Node Exporter для ОС, Kube-State-Metrics для объектов API, Blackbox Exporter для внешних проверок).
*   **[Grafana](../../Grafana/grafana_overview.md):** Основной инструмент визуализации и построения дашбордов.

### Архитектура мониторинга

Мониторинг в Kubernetes строится на декларативном управлении через Custom Resources (CR), которые обрабатываются Prometheus Operator.

**Основные компоненты и объекты (CRD):**

| Компонент | Тип объекта (CRD) | Назначение |
| :--- | :--- | :--- |
| **Prometheus Server** | `Prometheus` | Описание инстанса сервера мониторинга |
| **Prometheus Agent** | `PrometheusAgent` | Описание инстанса агента для Remote Write |
| **Alertmanager** | `Alertmanager` | Описание инстанса системы оповещений |
| **Service Discovery** | `ServiceMonitor` | Обнаружение целей через абстракцию Service |
| **Pod Discovery** | `PodMonitor` | Прямой скрейпинг подов (sidecars, mesh) |
| **Custom Scrape** | `ScrapeConfig` | Произвольные настройки скрейпинга (v0.65+) |
| **Rules** | `PrometheusRule` | Правила алертинга и агрегации (Recording Rules) |
| **Alert Config** | `AlertmanagerConfig` | Декларативная настройка маршрутов алертов |

### Механизмы сбора метрик

**1. Инфраструктурные метрики (Kubelet & cAdvisor):**
В современных версиях Kubernetes cAdvisor интегрирован в Kubelet. Prometheus собирает данные напрямую с эндпоинтов нод:
*   `/metrics` — метрики самого Kubelet (runtime, операции с подами, тома).
*   `/metrics/cadvisor` — детальные метрики контейнеров (CPU, Memory, Disk, Network).
*   `/metrics/resource` — облегченные метрики ресурсов (используются Metrics Server).
*   `/metrics/probes` — результаты выполнения Liveness/Readiness проб.

**2. Метрики объектов Kubernetes (Kube-State-Metrics):**
Генерирует метрики на основе состояния объектов API (Deployments, Pods, PV/PVC), которые нельзя получить изнутри контейнеров (например, "сколько реплик запрошено vs доступно").

**3. Автоматическое обнаружение (Service Discovery):**
Prometheus использует Kubernetes API для поиска целей:
*   **endpoints** — обнаружение через Service (рекомендуемый способ для приложений).
*   **pod** — прямой сбор с подов (для sidecar-контейнеров или системных компонентов без Service).
*   **node** — мониторинг хостов через Node Exporter.
*   **ingress** — мониторинг входных точек трафика.

**4. Пользовательские конфигурации (ScrapeConfig):**
Используется для интеграции внешних сервисов или специфических настроек (например, сбор метрик с etcd через статические IP или использование `authorization` заголовков для сторонних API).

> **См. также:** [Service Discovery](./service_discovery.md) — детальное руководство по `relabel_configs`.

### Ключевые метрики

Для эффективного управления кластером необходимо отслеживать метрики на нескольких уровнях. Ниже приведены критические запросы для мониторинга.

**1. Инфраструктура и Узлы (Node Metrics):**
*   **CPU Pressure:** Процент использования ресурсов от общей емкости.
    ```promql
    100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
    # → 45.5 (средняя загрузка узла в %)
    ```
*   **Memory Usage:** Утилизация RAM без учета кэша.
    ```promql
    (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100
    ```

**2. Нагрузки (Workloads/Pods):**
*   **CPU Throttling:** Выявление подов, которые упираются в свои лимиты.
    ```promql
    sum by (pod, container) (rate(container_cpu_cfs_throttled_seconds_total[5m])) > 0
    ```
*   **Memory OOM Risk:** Приближение к лимитам памяти (Working Set).
    ```promql
    container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.8
    ```

**3. Состояние кластера (Control Plane):**
*   **API Server Latency:** Время обработки запросов (P99).
    ```promql
    histogram_quantile(0.99, sum by (le, resource, verb) (rate(apiserver_request_duration_seconds_bucket[5m])))
    # → 0.15 (задержка в секундах)
    ```
*   **Etcd Health:** Наличие лидера и ошибки записи.
    ```promql
    etcd_server_has_leader == 0
    rate(etcd_server_slow_apply_total[5m]) > 0
    ```
*   **Scheduler Status:** Очередь нераспределенных подов.
    ```promql
    scheduler_pending_pods{queue="unschedulable"} > 0
    ```

**4. Доступность сервисов:**
*   **Blackbox Probes:** Проверка внешних эндпоинтов.
    ```promql
    probe_success == 0
    ```

## Практические сценарии

### Выбор режима работы (Server vs Agent)

**Сценарий 1: Автономный мониторинг (Server)**
Используется для большинства кластеров. Prometheus хранит данные локально, выполняет алертинг и предоставляет UI.
*   **Плюсы:** Независимость от внешней сети для хранения данных.
*   **Минусы:** Высокие требования к ресурсам (RAM/Storage) при росте кластера.

**Сценарий 2: Архитектура со сбором на границе (Agent Mode)**
Используется в мультикластерных средах с централизованным хранилищем (VictoriaMetrics, Mimir, Thanos).
*   **Плюсы:** Минимальное потребление ресурсов, отсутствие локальных дисков, единая точка обзора (Global View).
*   **Минусы:** Зависимость от доступности центрального хранилища и пропускной способности сети.

### Борьба с высокой кардинальностью (High Cardinality)

При большом количестве короткоживущих подов или динамических меток (например, ID сессий в лейблах) объем данных в TSDB может вызвать OOM.

**Методы решения:**
1.  **Drop Labels:** Удаление ненужных метаданных Kubernetes в `relabel_configs`.
2.  **Recording Rules:** Агрегация высокочастотных метрик до более крупных сущностей (например, по неймспейсам).
3.  **Лимиты:** Установка `sampleLimit` в `ServiceMonitor`, чтобы предотвратить переполнение от одного некорректно настроенного приложения.

### Планирование емкости (Capacity Planning)

Для стабильной работы стека в Kubernetes критически важно задавать `requests` и `limits`:
*   **Prometheus Server:** RAM request должен составлять ~1.5x от расчетного объема In-Memory chunks. Установка слишком низкого Limit приведет к OOM при тяжелых запросах.
*   **Вертикальное масштабирование:** Увеличение ресурсов одного инстанса при росте количества активных серий.
*   **Горизонтальное шардирование:** Разделение целей между несколькими инстансами Prometheus через `hashmod`.

```yaml
# Пример настройки ресурсов в Prometheus CRD
spec:
  replicas: 2
  resources:
    requests:
      memory: 4Gi
      cpu: 1000m
    limits:
      memory: 8Gi
      cpu: 2000m
```

## Дополнительная информация

### Современная концепция Observability

| Слой | Основные инструменты | Назначение |
| :--- | :--- | :--- |
| **Метрики** | Prometheus, VictoriaMetrics, Mimir | Числовые показатели, тренды, алертинг |
| **Логи** | Grafana Loki, Fluent Bit, Vector | Детальная информация о событиях (событийная модель) |
| **Трассировка** | Jaeger, Tempo | Анализ пути запроса (latency tracing) |
| **Унификация** | **OpenTelemetry (OTel)** | Единый стандарт сбора и передачи всех типов данных O11y |

> **См. также:** [OpenTelemetry в Kubernetes](../../OpenTelemetry/opentelemetry_overview.md), [Observability overview](../../Concepts/Observability_and_Monitoring/observability_definitions.md).

### Эволюция Prometheus 3.0 в Kubernetes

Версия 3.0 (2025–2026) принесла значительные улучшения для K8s-сред:
1.  **Remote Write 2.0:** Снижение накладных расходов на передачу данных и нативная поддержка метаданных.
2.  **Native Histograms:** Более точный расчет перцентилей без создания десятков `_bucket` метрик.
3.  **OTLP Ingest:** Прямой прием данных OpenTelemetry без использования адаптеров.
4.  **Security:** Усиленная интеграция с Admission Webhooks для валидации `PrometheusRule`.

### Безопасность и отказоустойчивость

1.  **RBAC:** Prometheus требует прав на чтение API (Nodes, Services, Endpoints, Pods). Используйте ClusterRole с минимально необходимым набором `verbs`.
2.  **Network Policies:** Ограничение доступа к портам 9090 и 9093.
3.  **Высокая доступность (HA):** Развертывание 2 реплик Prometheus. Alertmanager автоматически дедуплицирует идентичные алерты от разных реплик.

> **См. также:** [Prometheus Security](../security.md), [Масштабирование](../scaling/overview.md), [HA в Prometheus Operator](./operator/high_availability.md).

