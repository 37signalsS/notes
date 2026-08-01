# Prometheus Operator — Концепции

## Определения

**Prometheus Operator** — специализированный Kubernetes-контроллер, автоматизирующий жизненный цикл и управление конфигурацией стека мониторинга. Он реализует паттерн «Оператор», расширяя стандартное API Kubernetes через Custom Resource Definitions (CRD) для декларативного описания желаемого состояния систем мониторинга, алертинга и визуализации.

**Reconciliation Loop (Цикл согласования)** — непрерывный процесс, в котором Оператор сравнивает декларативное описание (Desired State) из CRD с реальным состоянием ресурсов в кластере (Actual State) и вносит корректировки (создание Pods, обновление Secrets, перезагрузка конфигов).

> **См. также:** [Kubernetes Operators](../../../Kubernetes/Concepts/kubernetes_operators.md), [kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md), [Ручная установка](./installation.md).

## Базовые концепции

### Архитектура и цикл работы контроллера

Prometheus Operator работает в бесконечном цикле, обеспечивая соответствие инфраструктуры заданным правилам.

1.  **Watch (Наблюдение):** Оператор использует Kubernetes API для отслеживания событий создания, удаления и изменения объектов `Prometheus`, `Alertmanager`, `ServiceMonitor`, `PodMonitor`, `ScrapeConfig`, `PrometheusRule`, а также связанных с ними `Secret` и `ConfigMap`.
2.  **Generate (Генерация):** При обнаружении изменений Оператор анализирует селекторы (label selectors) и генерирует итоговый конфигурационный файл (например, `prometheus.yaml`).
3.  **Apply (Применение):**
    *   Обновляет `StatefulSet` для инстансов Prometheus/Alertmanager.
    *   Записывает новую конфигурацию в `Secret` (для Prometheus) или `ConfigMap`.
    *   Создает `Service` и `Endpoints` для обеспечения связности.
4.  **Reload (Перезагрузка):** Использование **`prometheus-config-reloader`**. Это sidecar-контейнер, который запускается в каждом поде Prometheus/Alertmanager. Он отслеживает изменения в смонтированном томе с конфигурацией и инициирует HTTP-запрос на эндпоинт `/-/reload`. Это исключает необходимость перезапуска подов при каждом изменении `ServiceMonitor`.

### Пользовательские ресурсы (CRD)

Оператор расширяет Kubernetes API следующими ресурсами:

| CRD | Назначение | Особенности | Подробнее |
| :--- | :--- | :--- | :--- |
| **Prometheus** | Полнофункциональный сервер с TSDB. | Управляет StatefulSet, хранилищем, HA. | [Prometheus CRD](./crd/prometheus.md) |
| **PrometheusAgent** | Prometheus в режиме сбора (Agent Mode). | Только скрейпинг и Remote Write, без TSDB. | [Prometheus Agent Mode](../overview.md) |
| **Alertmanager** | Экземпляр Alertmanager. | Управляет кластеризацией (gossip) и хранилищем. | [Alertmanager CRD](./crd/alertmanager.md) |
| **ServiceMonitor** | Сбор метрик через Kubernetes Service. | Стандартный способ мониторинга приложений. | [ServiceMonitor](./crd/servicemonitor.md) |
| **PodMonitor** | Прямой сбор метрик с подов. | Используется при отсутствии Service или для Sidecars. | [PodMonitor](./crd/podmonitor.md) |
| **ScrapeConfig** | Нативная конфигурация скрейпинга. | Заменяет `additionalScrapeConfigs` для внешних целей. | [Native SD](../service_discovery.md) |
| **PrometheusRule** | Правила алертинга и агрегации. | Генерирует ConfigMap с группами правил. | [PrometheusRule](./crd/prometheusrule.md) |
| **Probe** | Blackbox-мониторинг. | Управляет скрейпингом через Blackbox Exporter. | [Probe](./crd/probe.md) |
| **AlertmanagerConfig** | Маршрутизация и получатели. | Позволяет декларативно описывать Routes/Receivers. | [AlertmanagerConfig](./crd/alertmanagerconfig.md) |

### Принцип работы Service Discovery

Operator автоматически обнаруживает цели через Kubernetes API, используя селекторы в ресурсе `Prometheus`:

*   **`serviceMonitorSelector`**: Выбирает объекты `ServiceMonitor`. Далее Оператор находит соответствующие `Service` по их селекторам и извлекает IP эндпоинтов.
*   **`podMonitorSelector`**: Выбирает объекты `PodMonitor` и напрямую формирует список IP подов для скрейпинга.
*   **`ruleSelector`**: Выбирает `PrometheusRule`. Оператор объединяет их в файлы и монтирует как тома.
*   **`scrapeConfigSelector`**: Выбирает `ScrapeConfig` для добавления произвольных конфигураций сбора.

### RBAC и права доступа

Для корректной работы требуются следующие уровни доступа:
*   **Контроллер (Operator):** Должен иметь права на управление `StatefulSets`, `Services`, `Secrets`, `ConfigMaps` во всех target-namespaces.
*   **Экземпляр Prometheus:** Должен иметь `ClusterRole` с правами `get`, `list`, `watch` для `nodes`, `pods`, `services`, `endpoints`, `endpointslices`, `ingresses` для работы Service Discovery.

> **См. также:** [Access Control](./Security/access_control.md), [Secrets Best Practices](./Security/secrets_best_practices.md).

## Практические сценарии

### Высокая доступность и масштабирование

1.  **High Availability (HA):** Настраивается через `spec.replicas: 2` в ресурсе `Prometheus`. Оператор автоматически настраивает внешние лейблы (например, `prometheus_replica`), позволяя Alertmanager дедуплицировать алерты.
2.  **Шардирование (Sharding):** Параметр `spec.shards: N` позволяет распределить нагрузку по сбору метрик между несколькими инстансами. Оператор использует хэширование подов для распределения целей между шардами.
3.  **Thanos Sidecar:** Интегрируется через `spec.thanos`. Оператор добавляет контейнер `thanos sidecar`, настраивает gRPC порты и пробрасывает секреты для подключения к объектному хранилищу.

### Выбор между Prometheus и PrometheusAgent

*   **Prometheus:** Используйте, когда требуется локальное хранение данных (TSDB), выполнение сложных PromQL запросов и алертинг внутри кластера.
*   **PrometheusAgent:** Идеален для Edge-кластеров, мультикластерных сред (отправка в центральный Mimir/VictoriaMetrics) и сценариев, где RAM/Disk на узлах ограничены.

### Установка стека

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка с настройками по умолчанию (рекомендуется для Production)
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Проверка работоспособности кластера

```bash
# 1. Проверка установки CRD (должно быть 10+)
kubectl get crd | grep monitoring.coreos.com

# 2. Проверка статуса Оператора
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator

# 3. Проверка созданных инстансов
kubectl get prometheus -n monitoring
kubectl get alertmanager -n monitoring

# 4. Проверка объектов сбора данных
kubectl get servicemonitor -A
kubectl get podmonitor -A
```

### Диагностика (Troubleshooting)

При возникновении проблем следуйте по цепочке reconciliation:

1.  **Логи Оператора:** Проверка ошибок генерации конфигов или нехватки прав RBAC.
    `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator`
2.  **Логи config-reloader:** Проверка успешности запросов `/-/reload`.
    `kubectl logs -n monitoring -c config-reloader <prometheus-pod-name>`
3.  **Статус в UI Prometheus:** Проверка `/targets` и `/config` для подтверждения, что Operator применил изменения.

## Дополнительная информация

### Ключевые метрики мониторинга Operator

| Метка | Описание | Критичность |
| :--- | :--- | :--- |
| `prometheus_operator_reconcile_errors_total` | Общее количество ошибок цикла сверки. | **High** |
| `prometheus_operator_reconcile_duration_seconds` | Время выполнения одной итерации цикла. | Medium |
| `prometheus_operator_node_sync_duration_seconds` | Время синхронизации списка узлов. | Medium |
| `prometheus_operator_config_size_bytes` | Размер сгенерированного файла конфигурации. | Low (лимит 1MB) |

### Актуальные версии и жизненный цикл

| Параметр | Значение | Дата проверки |
| :--- | :--- | :--- |
| **Последняя версия Operator** | `v0.92.0` | Июль 2026 |
| **Репозиторий** | [github.com/prometheus-operator](https://github.com/prometheus-operator/prometheus-operator) |
| **Минимальный Kubernetes** | 1.29+ |
| **Release Schedule** | [Официальный график](https://prometheus-operator.dev/docs/community/release/) |

### Эволюция версий

*   **v0.81–v0.85** (март–август 2025): Нативная поддержка Prometheus 2.x, улучшение интеграции с Thanos Sidecar.
*   **v0.86–v0.89** (октябрь 2025 – февраль 2026): Внедрение поддержки Prometheus 3.0, расширение функционала `AlertmanagerConfig`.
*   **v0.90–v0.91** (март–май 2026): Внедрение `ScrapeConfig` CRD для отказа от `additionalScrapeConfigs` в Secret-ах. Оптимизация работы с `EndpointSlice`.
*   **v0.92+** (июнь 2026 – настоящее время): Стабилизация API `PrometheusAgent`, нативная поддержка OTLP, интеграция с Kubernetes Gateway API.

### Связанные компоненты и ресурсы

| Компонент | Описание | Ссылка |
| :--- | :--- | :--- |
| **High Availability** | Конфигурация отказоустойчивости. | [High Availability](./high_availability.md) |
| **Security** | TLS, RBAC и Network Policies. | [Security Overview](./Security/index.md) |
| **Grafana Integration** | Дашборды и источники данных. | [Grafana Integration](./grafana_integration.md) |
| **TSDB Management** | Управление хранилищем и Retention. | [Prometheus CRD — Storage](./crd/prometheus.md#storage) |

> **См. также:** [Troubleshooting](./troubleshooting.md), [Prometheus CRD](./crd/prometheus.md), [Alertmanager CRD](./crd/alertmanager.md).
