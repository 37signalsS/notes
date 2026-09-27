# Prometheus Operator — Концепции

## Определения

**Prometheus Operator** — специализированный Kubernetes-контроллер, автоматизирующий жизненный цикл и управление конфигурацией стека мониторинга. Он реализует паттерн «Оператор», расширяя стандартное API Kubernetes через Custom Resource Definitions (CRD) для декларативного описания желаемого состояния систем мониторинга, алертинга и визуализации.

**Reconciliation Loop (Цикл согласования)** — непрерывный процесс, в котором Оператор сравнивает декларативное описание (Desired State) из ресурсов CRD с реальным состоянием объектов в кластере (Actual State). При обнаружении расхождений Оператор вносит корректировки: создает или обновляет StatefulSets, генерирует секреты с конфигурацией и инициирует перезагрузку компонентов.

**Field Ownership (SSA)** — механизм Server-Side Apply, при котором Оператор помечает поля в ресурсах, которыми он «владеет». Это предотвращает конфликты при совместном использовании ресурсов с другими контроллерами (например, HPA или GitOps-инструментами) и позволяет API-серверу корректно объединять изменения.

**Config-Reloader** — sidecar-контейнер, выполняющий мониторинг обновлений конфигурации в Secret/ConfigMap и инициализирующий перезагрузку основного процесса Prometheus/Alertmanager через HTTP API (`/-/reload`).

> **Смотрите также:** [Kubernetes-операторы](../../../Kubernetes/Concepts/kubernetes_operators.md) — общие принципы паттерна; [kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md) — основной Helm-чарт; [Ручная установка](./installation.md).

## Базовые концепции

### Инфраструктурный мониторинг
Для полноценного наблюдения за кластером Оператор развертывает и настраивает:
*   **Node Exporter (DaemonSet):** Запускает по одному поду на каждом узле для сбора системных метрик (CPU, RAM, Disk, Network) самой ОС. Использование DaemonSet гарантирует автоматический запуск экспортера на новых узлах.
*   **Kube State Metrics (Deployment):** Отдельный сервис, который преобразует состояние объектов Kubernetes (Deployments, Pods, Services) в формат метрик Prometheus. Позволяет отслеживать количество реплик, статусы подов и другие параметры API.
*   **kubelet (cAdvisor):** Встроенный в kubelet механизм сбора метрик контейнеров (Resource usage).
*   **Control Plane Components:** Мониторинг API Server, Scheduler, etcd и CoreDNS.

### Архитектура и цикл работы контроллера

Prometheus Operator построен на фреймворке `controller-runtime` и работает в бесконечном цикле, обеспечивая соответствие инфраструктуры заданным правилам.

1.  **Informer Watch (Наблюдение):** Оператор использует механизм Informers для отслеживания событий в ресурсах `Prometheus`, `Alertmanager`, `ServiceMonitor`, `PodMonitor`, `ScrapeConfig`, `PrometheusRule`, `Probe`, а также связанных `Secret` и `ConfigMap`. Informers поддерживают локальный кэш объектов, что снижает нагрузку на API-сервер. При перезагрузке Оператор восстанавливает состояние из кэша Watch, минуя полное пересканирование.
2.  **Валидация (Validation):** С 2025–2026 годов активно используется **CEL-валидация** (`x-kubernetes-validations`) на уровне API-сервера, что позволяет отклонять некорректные CRD еще на этапе `kubectl apply`. Дополнительно работают Admission Webhooks для проверки синтаксиса PromQL.
3.  **Generate (Генерация):** Оператор анализирует селекторы (label selectors) и агрегирует разрозненные ресурсы в единый конфигурационный файл `prometheus.yaml` или `alertmanager.yaml`. Итоговый конфиг сжимается gzip и сохраняется в Kubernetes Secret.
4.  **Apply (Применение):**
    *   Управление жизненным циклом `StatefulSet` (масштабирование, обновление версий, настройка PVC) через Server-Side Apply.
    *   Запись конфигурации в Kubernetes `Secret` (для Prometheus) или `ConfigMap`.
    *   Настройка `Service` и **`EndpointSlice`** для сетевой связности.
5.  **Reload (Перезагрузка):** Контейнер **`config-reloader`** (sidecar) отслеживает изменения в смонтированном секрете и отправляет сигнал `/-/reload` в API Prometheus/Alertmanager, исключая простой системы. Перед reload конфигурация валидируется через `promtool check config`.

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
*   **Operator RBAC:** Права на управление инфраструктурными объектами (`StatefulSets`, `Secrets`, `Services`, `ConfigMaps`) во всех обслуживаемых пространствах имен. Оператор работает от имени выделенного `ServiceAccount` (обычно `prometheus-operator` в namespace `monitoring`).
*   **Prometheus RBAC:** Права `get`, `list`, `watch` для `nodes`, `pods`, `services` и `endpointslices`. С 2025 года доступ к `endpointslices` является приоритетным для Service Discovery. Для кластерного доступа создается `ClusterRole` и `ClusterRoleBinding`.

> **Смотрите также:** [Контроль доступа (RBAC)](./Security/access_control.md), [Управление секретами](./Security/secrets_best_practices.md).

### Операционные нюансы и ограничения

#### Ловушка пустого селектора
Если селектор (например, `serviceMonitorSelector`) не указан или пуст (`{}`), Оператор подхватывает **все** ресурсы соответствующего типа во **всех** namespace кластера. В большинстве Production-сред это нежелательно. В Helm-чарте `kube-prometheus-stack` селекторы по умолчанию жестко фильтруют по лейблу `release: <имя_релиза>`, что предотвращает утечку мониторинга между стеками.

#### Лимит размера Secret (1 MiB)
Итоговый сжатый `prometheus.yaml` или `alertmanager.yaml` хранится в Kubernetes Secret. Размер Secret ограничен **1 MiB** (лимит etcd). При приближении к 800 KiB необходимо планировать шардирование (`spec.shards`) или переход на `ScrapeConfig` для разделения конфигурации.

```bash
# Проверка размера сгенерированного конфига
kubectl get secret prometheus-main -n monitoring -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | wc -c
```

#### Выбор namespace для селекторов
Для мониторинга ресурсов в сторонних namespace необходимо явно настроить селекторы пространств имен:
```yaml
spec:
  serviceMonitorNamespaceSelector: {}
  podMonitorNamespaceSelector: {}
  probeNamespaceSelector: {}
```
Если селекторы не указаны, Оператор ищет ресурсы только в собственном namespace.

#### Обновление StatefulSet и стратегии
При изменении `spec.version` в ресурсе `Prometheus` или `Alertmanager` Оператор выполняет Rolling Update StatefulSet. По умолчанию используется стратегия `RollingUpdate` с параметром `partition: 0`, что обеспечивает обновление всех подов одновременно. Для канареечного обновления используйте `partition`.

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

# 5. Инспекция сгенерированной конфигурации
kubectl get secret prometheus-main -n monitoring -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | head -50

# 6. Проверка логов sidecar config-reloader
kubectl logs -n monitoring prometheus-main-0 -c config-reloader --tail=50
```

### Валидация конфигурации и диагностика

```bash
# Проверка Prometheus-правил через promtool (выполняется внутри пода)
kubectl exec -n monitoring prometheus-main-0 -- promtool check rules /etc/prometheus/rules/*.yaml

# Проверка доступности API Prometheus
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/api/v1/query?query=up | jq .

# Проверка Service Discovery
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health}'
```

### Резервное копирование и восстановление

Данные TSDB Prometheus хранятся в PersistentVolumeClaim, создаваемом через `volumeClaimTemplate` в ресурсе `Prometheus`. Для резервного копирования:

```bash
# 1. Создание снапшота через API Prometheus
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- "http://localhost:9090/api/v1/admin/tsdb/snapshot" | jq .

# 2. Копирование снапшота из пода
kubectl cp monitoring/prometheus-main-0:/tmp/snapshots/latest /tmp/prometheus-backup

# 3. Резервное копирование самого PVC (через Velero или CSI-снапшот)
kubectl get pvc -n monitoring
velero backup create prometheus-backup --include-namespaces monitoring
```

**Внимание:** При восстановлении из снапшота убедитесь, что версия Prometheus совместима с форматом данных TSDB.

### Обновление Operator и версий Prometheus

#### Обновление Prometheus Operator

```bash
# Обновление через Helm
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml

# Проверка статуса после обновления
kubectl rollout status statefulset/prometheus-operator -n monitoring --timeout=5m
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator
```

#### Обновление версии Prometheus Server

```yaml
# Изменение версии в ресурсе Prometheus
spec:
  version: v3.12.0  # Новая версия
```
Оператор автоматически обновляет образ контейнера и запускает Rolling Update StatefulSet. Для контроля скорости обновления используйте `updateStrategy.rollingUpdate.partition`.

### Требования к ресурсам

#### Operator
*   **CPU:** 100-200m (минимально), 500m при нагрузке >500 целей.
*   **RAM:** 128-256 MiB. Рост потребления связан с количеством отслеживаемых CRD-ресурсов.
*   **Хранилище:** Не требуется (статус хранится в etcd).

#### Prometheus Server
*   **CPU:** 1-4 ядра (зависит от объема серий и частоты скрейпинга).
*   **RAM:** Формула приблизительная: `(серии * размер_семпла * 3) + 25% overhead`. Для 1 млн серий требуется ~4-8 GiB.
*   **Диск:** 50-100 GiB на 30 дней с сжатием. Рекомендуется SSD для production.

#### Alertmanager
*   **CPU:** 250-500m.
*   **RAM:** 256-512 MiB.
*   **Диск:** 10-20 GiB (для хранения Silences и состояния кластеризации).

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
| `prometheus_operator_reconcile_operations_total` | Общее количество операций reconciliation. | Medium |
| `prometheus_config_last_reload_success_timestamp_seconds` | Время последней успешной перезагрузки конфигурации. | High |

#### Пример алертов для Prometheus Operator

```yaml
groups:
  - name: prometheus_operator_alerts
    rules:
      - alert: PrometheusOperatorReconcileErrors
        expr: rate(prometheus_operator_reconcile_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Prometheus Operator имеет ошибки reconciliation"
          description: "Более {{ $value }} ошибок reconciliation в минуту в namespace {{ $labels.namespace }}"

      - alert: PrometheusOperatorConfigSizeTooLarge
        expr: prometheus_operator_config_size_bytes > 800000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Размер конфигурации Prometheus близок к лимиту"
          description: "Размер сгенерированного конфига: {{ $value | humanize1024 }}B. Лимит Secret: 1 MiB."

      - alert: PrometheusConfigReloadFailed
        expr: prometheus_config_last_reload_success_timestamp_seconds < time() - 300
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Prometheus не перезагружает конфигурацию"
          description: "Последняя успешная перезагрузка была более 5 минут назад."
```

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
*   **[Расчет ресурсов](./resource_sizing.md)** — формулы RAM/CPU/Disk, sizing для разных нагрузок.
*   **[Long-term Storage](./long_term_storage_integration.md)** — интеграция с Thanos, VictoriaMetrics, Mimir.
*   **[GitOps](./gitops_integration.md)** — ArgoCD/Flux + Operator.
*   **[Network Policies](./network_policies.md)** — детальная изоляция для monitoring.
*   **[PromQL для Kubernetes](./promql_kubernetes_patterns.md)** — паттерны алертинга для K8s-метрик.
*   **[Оптимизация затрат](./cost_optimization.md)** — кардинальность, retention, Agent Mode.
*   **[PodDisruptionBudget](./pod_disruption_budget.md)** — защита при drain и rolling update.
*   **[Self-Monitoring](./self_monitoring.md)** — мониторинг самого Operator.
