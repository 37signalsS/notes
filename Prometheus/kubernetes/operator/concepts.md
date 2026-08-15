# Prometheus Operator — Концепции

## Определения

**Prometheus Operator** — специализированный Kubernetes-контроллер, автоматизирующий жизненный цикл и управление конфигурацией стека мониторинга. Он реализует паттерн «Оператор», расширяя стандартное API Kubernetes через Custom Resource Definitions (CRD) для декларативного описания желаемого состояния систем мониторинга, алертинга и визуализации.

**Reconciliation Loop (Цикл согласования)** — непрерывный процесс, в котором Оператор сравнивает декларативное описание (Desired State) из ресурсов CRD с реальным состоянием объектов в кластере (Actual State). При обнаружении расхождений Оператор вносит корректировки: создает или обновляет StatefulSets, генерирует секреты с конфигурацией и инициирует перезагрузку компонентов.

> **Смотрите также:** [Kubernetes-операторы](../../../Kubernetes/Concepts/kubernetes_operators.md) — общие принципы паттерна; [kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md) — основной Helm-чарт; [Ручная установка](./installation.md).

## Базовые концепции

### Инфраструктурный мониторинг
Для полноценного наблюдения за кластером Оператор развертывает и настраивает:
*   **Node Exporter (DaemonSet):** Запускает по одному поду на каждом узле для сбора системных метрик (CPU, RAM, Disk, Network) самой ОС. Использование DaemonSet гарантирует автоматический запуск экспортера на новых узлах.
*   **Kube State Metrics (Deployment):** Отдельный сервис, который преобразует состояние объектов Kubernetes (Deployments, Pods, Services) в формат метрик Prometheus. Позволяет отслеживать количество реплик, статусы подов и другие параметры API.
*   **kubelet (cAdvisor):** Встроенный в kubelet механизм сбора метрик контейнеров (Resource usage).
*   **Control Plane Components:** Мониторинг API Server, Scheduler, etcd и CoreDNS.

### Архитектура и цикл работы контроллера

Prometheus Operator работает в бесконечном цикле, обеспечивая соответствие инфраструктуры заданным правилам.

1.  **Watch (Наблюдение):** Оператор использует Kubernetes API для отслеживания событий в ресурсах `Prometheus`, `Alertmanager`, `ServiceMonitor`, `PodMonitor`, `ScrapeConfig`, `PrometheusRule`, а также связанных с ними `Secret` и `ConfigMap`.
2.  **Валидация (Validation):** С 2025–2026 годов активно используется **CEL-валидация** (`x-kubernetes-validations`) на уровне API-сервера, что позволяет отклонять некорректные CRD еще на этапе `kubectl apply`. Дополнительно работают Admission Webhooks для проверки синтаксиса PromQL.
3.  **Generate (Генерация):** Оператор анализирует селекторы (label selectors) и агрегирует разрозненные ресурсы в единый конфигурационный файл `prometheus.yaml`.
4.  **Apply (Применение):**
    *   Управление жизненным циклом `StatefulSet` (масштабирование, обновление версий, настройка PVC).
    *   Запись конфигурации в Kubernetes `Secret` (для Prometheus) или `ConfigMap`.
    *   Настройка `Service` и **`EndpointSlice`** для сетевой связности.
5.  **Reload (Перезагрузка):** Контейнер **`config-reloader`** (sidecar) отслеживает изменения в смонтированном секрете и отправляет сигнал `/-/reload` в API Prometheus/Alertmanager, исключая простой системы.

### Пользовательские ресурсы (CRD)

Оператор расширяет Kubernetes API следующими ключевыми ресурсами:

| CRD | Назначение | Особенности (2026) | Подробнее |
| :--- | :--- | :--- | :--- |
| **Prometheus** | Сервер мониторинга. | Управляет TSDB, HA, шардированием и OTLP-ресивером. | [Prometheus CRD](./crd/prometheus.md) |
| **PrometheusAgent** | Агент сбора (Agent Mode). | Только скрейпинг и Remote Write. Стабилен в v0.92+. | [Агентский режим](../overview.md) |
| **Alertmanager** | Система уведомлений. | Управляет кластеризацией (gossip) и Silences. | [Alertmanager CRD](./crd/alertmanager.md) |
| **ServiceMonitor** | Скрейпинг через Service. | Стандарт для приложений за балансировщиком. | [ServiceMonitor](./crd/servicemonitor.md) |
| **PodMonitor** | Скрейпинг подов напрямую. | Для sidecars и систем без Service. | [PodMonitor](./crd/podmonitor.md) |
| **ScrapeConfig** | Низкоуровневый скрейпинг. | Заменяет `additionalScrapeConfigs` для внешних целей. | [ScrapeConfig CRD](./crd/servicemonitor.md) |
| **PrometheusRule** | Правила и алерты. | Декларативное описание логики мониторинга. | [PrometheusRule](./crd/prometheusrule.md) |
| **Probe** | Blackbox-мониторинг. | Проверки доступности по ICMP/HTTP/TCP. | [Probe](./crd/probe.md) |
| **AlertmanagerConfig** | Маршрутизация алертов. | Управление Routes и Receivers на уровне v1beta1. | [AlertmanagerConfig](./crd/alertmanagerconfig.md) |

### Принцип работы Service Discovery

Оператор автоматически формирует список целей для скрейпинга, используя механизмы выбора в ресурсе `Prometheus`:

*   **`serviceMonitorSelector`**: Ищет объекты `ServiceMonitor`. Оператор находит соответствующие `Service` и извлекает IP-адреса из **`EndpointSlice`** (использование устаревшего `Endpoints` минимизировано для снижения нагрузки на API).
*   **`podMonitorSelector`**: Выбирает `PodMonitor` для прямого сбора метрик с IP-адресов подов.
*   **`ruleSelector`**: Агрегирует `PrometheusRule` из разных пространств имен в единый набор правил.
*   **`scrapeConfigSelector`**: Подключает нативные конфигурации `ScrapeConfig` (v1alpha1) для мониторинга ресурсов вне Kubernetes (статические IP, HTTP SD и др.).

### Безопасность и RBAC

Функционирование стека требует строго разграниченных прав доступа:
*   **Operator RBAC:** Права на управление инфраструктурными объектами (`StatefulSets`, `Secrets`, `Services`, `ConfigMaps`) во всех обслуживаемых пространствах имен.
*   **Prometheus RBAC:** Права `get`, `list`, `watch` для `nodes`, `pods`, `services` и `endpointslices`. С 2025 года доступ к `endpointslices` является приоритетным для Service Discovery.

> **Смотрите также:** [Контроль доступа (RBAC)](./Security/access_control.md), [Управление секретами](./Security/secrets_best_practices.md).

## Практические сценарии

### Высокая доступность и масштабирование

1.  **Высокая доступность (HA):** Реализуется через `spec.replicas: 2`. Оператор автоматически настраивает внешние лейблы (например, `prometheus_replica`), позволяя Alertmanager дедуплицировать алерты.
2.  **Шардирование (Sharding):** Распределение нагрузки по скрейпингу тысяч целей между несколькими инстансами (`spec.shards`). Оператор использует консистентное хэширование для распределения целей между шардами.
3.  **Интеграция с Thanos:** Настройка через `spec.thanos`. Оператор добавляет sidecar для долгосрочного хранения данных в S3/GCS и обеспечения глобального представления (Global View) через gRPC.

### Выбор между Prometheus и PrometheusAgent

*   **Prometheus Server:** Необходим, если требуется локальная TSDB, выполнение PromQL-запросов (например, для Grafana) и обработка алертов (`PrometheusRule`) внутри кластера.
*   **Prometheus Agent:** Рекомендуется для Edge-кластеров, IoT-устройств и сценариев, где данные пересылаются в централизованное хранилище (Thanos, VictoriaMetrics, Mimir). Экономит до 40% ресурсов (RAM/CPU) за счет отсутствия TSDB и Query Engine.

### Установка стека (Helm)

Стандартный метод развертывания для Production-сред:

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка с созданием namespace
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Проверка работоспособности кластера

Команды для быстрой верификации состояния стека:

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

При возникновении проблем в работе Оператора или сборе метрик используйте специализированное руководство:

*   **[Prometheus Operator: Диагностика и устранение неисправностей](./troubleshooting.md)** — полный алгоритм отладки, разбор практических сценариев (OOM, Secret limit, Remote Write) и перечень диагностических запросов.

## Дополнительная информация

### Ключевые метрики мониторинга Оператора

| Метрика | Описание | Критичность |
| :--- | :--- | :--- |
| `prometheus_operator_reconcile_errors_total` | Количество ошибок в цикле согласования. | **High** |
| `prometheus_operator_reconcile_duration_seconds` | Длительность одной итерации сверки. | Medium |
| `prometheus_operator_config_size_bytes` | Размер сгенерированного файла конфигурации (лимит Secret — 1MB). | Medium |

### Актуальные версии и жизненный цикл (2026)

*   **Последняя стабильная версия:** `v0.92.0` (Июль 2026).
*   **Минимальный Kubernetes:** 1.29+.
*   **Поддержка Prometheus 3.0:** Полная интеграция функций UTF-8 для имен метрик, нативного OTLP-ресивера и Remote Write 2.0.
*   **Gateway API:** Поддержка интеграции с Kubernetes Gateway API для обеспечения внешнего доступа к UI без классических Ingress.

### Эволюция версий

*   **v0.81–v0.85** (2025): Нативная поддержка Prometheus 2.x, оптимизация работы с Thanos Sidecar, переход на `EndpointSlice`.
*   **v0.86–v0.89** (2025–2026): Внедрение поддержки Prometheus 3.0 (Alpha/Beta), расширение `AlertmanagerConfig` до v1beta1.
*   **v0.90–v0.91** (2026): Стабилизация `ScrapeConfig` CRD, отказ от `additionalScrapeConfigs` в секретах. Полная поддержка CEL-валидации.
*   **v0.92+** (Текущая): Стабильный `PrometheusAgent`, нативная поддержка OTLP-инжеста, интеграция с Gateway API и улучшенная производительность в кластерах с 10k+ сервисами.

### Связанные ресурсы

*   **[Высокая доступность](./high_availability.md)** — архитектура репликации и шардирования.
*   **[Безопасность](./Security/index.md)** — TLS, RBAC и сетевые политики.
*   **[Диагностика и Troubleshooting](./troubleshooting.md)** — глубокий анализ сбоев.
*   **[Интеграция с Grafana](./grafana_integration.md)** — дашборды и provisioning.
