# Мониторинг Kubernetes: Обзор

## Определения

**Мониторинг Kubernetes** — комплексная практика наблюдения за состоянием инфраструктуры кластера (Control Plane, Worker Nodes) и развернутых приложений (Workloads) с использованием метрик, логов и трассировок.

**Prometheus Operator** — специализированный Kubernetes-контроллер, автоматизирующий жизненный цикл стека мониторинга через Custom Resource Definitions (CRD). Реализует паттерн «Оператор» для управления Prometheus, Alertmanager и сопутствующими компонентами.

**Prometheus Agent Mode** — режим работы Prometheus (с версии 2.32+, стабилизирован в 3.0), оптимизированный для сбора метрик и их немедленной отправки через Remote Write 2.0 без локального хранения в TSDB. Идеален для Edge-кластеров.

**kube-prometheus-stack** — основной Helm-чарт сообщества для развёртывания полной экосистемы наблюдаемости (Prometheus, Alertmanager, Grafana, Prometheus Operator и экспортеры) в Kubernetes.

**ScrapeConfig** — современный CRD (введен в v0.65+), позволяющий описывать произвольные конфигурации скрейпинга, которые не вписываются в модель ServiceMonitor/PodMonitor (например, внешние статические цели или специфичные настройки Discovery).

**PrometheusRule** — Custom Resource Definition (CRD) в Prometheus Operator для декларативного описания правил оповещения (alerting rules) и правил записи (recording rules). Operator преобразует эти ресурсы в Kubernetes ConfigMap, которые автоматически монтируются в экземпляры Prometheus Server или PrometheusAgent.

**AlertmanagerConfig** — CRD для декларативного описания маршрутов алертов, получателей (receivers) и правил подавления (inhibition) внутри Alertmanager, позволяющий управлять конфигурацией оповещений через Kubernetes API.

**Probe** — CRD (введен в v0.50+), предназначенный для декларативного описания blackbox-проверок доступности внешних эндпоинтов (HTTP, TCP, ICMP, DNS, gRPC) через Blackbox Exporter.

**EndpointSlice** — ресурс Kubernetes API (v1.21+), содержащий IP-адреса и порты эндпоинтов Service. Является масштабируемой заменой устаревшего ресурса `Endpoints`, используемого Prometheus Operator для обнаружения целей скрейпинга.

**Config-Reloader** — sidecar-контейнер в поде Prometheus/Alertmanager, выполняющий мониторинг обновлений конфигурации в Secret/ConfigMap и инициализирующий перезагрузку основного процесса через HTTP API (`/-/reload`) без рестарта пода.

**External Labels** — глобальные метки, добавляемые к всем временным рядам на стороне Prometheus перед отправкой в удаленное хранилище или федерацию. Используются для идентификации источника данных (например, `cluster="dc-east"`, `region="eu"`).

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
| **Probe** | `Probe` | Декларативный blackbox-мониторинг внешних целей |

**Конвейер обработки алертов (Alert Pipeline):**

Alertmanager выполняет многоэтапную обработку входящих алертов от Prometheus:
1. **Дедупликация (Deduplication):** Удаление повторяющихся сигналов от разных реплик Prometheus в HA-парах.
2. **Группировка (Grouping):** Объединение алертов в одно сообщение по общим меткам (например, `cluster` или `service`). Предотвращает лавинообразную рассылку уведомлений.
3. **Подавление (Inhibition):** Взаимное исключение алертов. Если активен «родительский» алерт (например, падение всего кластера), «дочерние» (падение подов в этом кластере) будут подавлены.
4. **Замалчивание (Silencing):** Временное отключение уведомлений вручную (плановые работы).
5. **Маршрутизация (Routing):** Древовидная структура правил, определяющая, куда именно (Slack, Email, Webhook) отправится группа алертов.

**Высокая доступность Alertmanager:**

Alertmanager использует mesh-архитектуру на базе gossip-протокола для кластеризации нескольких реплик. Порт `9094` (TCP/UDP) используется для обмена состоянием между узлами. При разделении сети (split-brain) каждый сегмент продолжает отправлять уведомления самостоятельно, что гарантирует доставку сигнала.

**Config-Reloader:**

Sidecar-контейнер `config-reloader` отслеживает изменения в смонтированных Secret/ConfigMap и инициирует HTTP-запрос `/-/reload` к API Prometheus/Alertmanager. Перед reload конфигурация валидируется через `promtool check config`. Это исключает простой системы при обновлении правил или целей скрейпинга.

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

### Хранение данных и retention

Prometheus хранит метрики в локальной TSDB (Time Series Database). Конфигурация хранения определяется через `storage` в Prometheus CRD или флаги командной строки.

**Параметры retention:**
*   **По времени:** `--storage.tsdb.retention.time=30d` (по умолчанию 15 дней).
*   **По объему:** `--storage.tsdb.retention.size=100GB` (при превышении лимита старые блоки удаляются).

**storageSpec в Prometheus CRD:**

```yaml
spec:
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-storage
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 100Gi
```

Для production-сред рекомендуется использовать SSD-накопители. WAL (Write-Ahead Log) должен размещаться на выделенном быстром диске (NVMe SSD) для минимизации задержек записи.

### Внешние метки (external_labels)

External Labels добавляются ко всем временным рядам на стороне Prometheus перед отправкой в удаленное хранилище или федерацию. Они критически важны для мультикластерных сред, так как позволяют различать идентичные метрики из разных источников.

```yaml
spec:
  externalLabels:
    cluster: production-east
    region: eu-central-1
    environment: production
```

**Важно:** External labels на нижестоящих серверах должны быть уникальными (например, `cluster: dc1`), чтобы Master-сервер мог различать идентичные метрики из разных источников. При смене `external_labels` старые блоки становятся "чужими" для нового кластера, что требует ручной очистки объектного хранилища.

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

**5. Здоровье Prometheus Operator:**
*   **Ошибки reconciliation:** Количество ошибок в цикле согласования.
    ```promql
    rate(prometheus_operator_reconcile_errors_total[5m]) > 0.1
    ```
*   **Размер конфигурации:** Приближение к лимиту Secret (1 MiB).
    ```promql
    prometheus_operator_config_size_bytes > 800000
    ```
*   **Последняя перезагрузка:** Время последней успешной перезагрузки конфигурации.
    ```promql
    prometheus_config_last_reload_success_timestamp_seconds < time() - 300
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

Для стабильной работы стека в Kubernetes критически важно задавать `requests` и `limits`. Общие теоретические основы, расчеты по Закону Литтла и стратегии Headroom описаны в разделе **[Планирование ресурсов (Capacity Planning)](../../Concepts/capacity-planning.md)**.

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

### Проверка работоспособности (Health Checks)

После установки стека выполните базовую проверку компонентов:

```bash
# 1. Проверка установки CRD (должно быть 10+)
kubectl get crd | grep monitoring.coreos.com

# 2. Проверка статуса Prometheus Operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator

# 3. Проверка созданных инстансов
kubectl get prometheus -n monitoring
kubectl get alertmanager -n monitoring

# 4. Проверка объектов сбора данных
kubectl get servicemonitor -A
kubectl get podmonitor -A

# 5. Проверка доступности API Prometheus
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &
curl -s http://localhost:9090/-/healthy    # → healthy
curl -s http://localhost:9090/-/ready      # → ready
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets | length'

# 6. Проверка статуса целей (Targets) в UI
# Откройте http://localhost:9090/targets — все цели должны быть в состоянии UP
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

### Обновление стека

#### Обновление через Helm

```bash
# Обновление репозитория
helm repo update

# Обновление релиза
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml

# Проверка статуса после обновления
kubectl rollout status statefulset/prometheus-main -n monitoring --timeout=5m
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator
```

#### Обновление версии Prometheus через CRD

```yaml
# Изменение версии в ресурсе Prometheus
spec:
  version: v3.12.0  # Новая версия
```

Оператор автоматически обновляет образ контейнера и запускает Rolling Update StatefulSet. Для контроля скорости обновления используйте `updateStrategy.rollingUpdate.partition`.

#### Откат к предыдущей версии

```bash
# Откат Helm-релиза
helm rollback monitoring -n monitoring

# Откат версии Prometheus через CRD
kubectl patch prometheus main -n monitoring --type='json' -p='[{"op": "replace", "path": "/spec/version", "value":"v3.11.0"}]'
```

### RBAC и безопасность

Prometheus Operator и Prometheus Server требуют минимально необходимых прав для функционирования.

**Prometheus RBAC (ClusterRole):**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-k8s
rules:
- apiGroups: [""]
  resources: ["nodes", "nodes/proxy", "services", "endpoints", "pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["discovery.k8s.io"]
  resources: ["endpointslices"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["monitoring.coreos.com"]
  resources: ["servicemonitors", "podmonitors", "probes", "prometheusrules"]
  verbs: ["get", "list", "watch"]
```

**NetworkPolicy для изоляции мониторинга:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-allow
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - protocol: TCP
      port: 9090
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 443
    - protocol: TCP
      port: 9094
```

### Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Цели в статусе Down** | Несовпадение лейблов в `serviceMonitorSelector`, неправильный порт или путь | Проверьте `kubectl get servicemonitor -o yaml` и селекторы в ресурсе `Prometheus` |
| **OOMKilled** | Превышение лимитов RAM при высокой кардинальности | Увеличьте `resources.limits.memory`, включите Native Histograms, настройте `sample_limit` |
| **SecretTooLong** | Размер сгенерированного `prometheus.yaml` превышает 1 MiB | Включите шардирование (`spec.shards`) или используйте `ScrapeConfig` |
| **Config-reloader ошибка** | Некорректный синтаксис YAML или отсутствуют права на Secret | Проверьте `kubectl logs -c config-reloader`, выполните `promtool check config` |
| **Alertstorm** | Слишком чувствительные правила алертинга без `for` или `keep_firing_for` | Добавьте `for: >= 3m`, настройте `group_by` в Alertmanager |
| **DNS NXDOMAIN** | Кастомный `dnsPolicy` без корректных nameservers | Проверьте `dnsConfig` в спецификации Prometheus, статус CoreDNS |
| **Compaction Stall** | Высокий churn rate или недостаток CPU/диска | Увеличьте `--storage.tsdb.max-block-duration`, проверьте WAL на NVMe |

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

### Сравнение LTS-хранилищ (Long-Term Storage)

При масштабировании Prometheus возникает необходимость в долгосрочном хранении метрик. Основные решения:

| Решение | Архитектура | Хранилище | Сильные стороны |
| :--- | :--- | :--- | :--- |
| **Thanos** | Децентрализованная (Sidecar) | Объектное (S3/GCS) | Прозрачное расширение существующего Prometheus |
| **VictoriaMetrics** | Монолит или Кластер | Локальные диски / PV | Экстремальная производительность, сжатие данных, простота |
| **Grafana Mimir** | Микросервисная | Объектное (S3/GCS) | Мульти-тенантность, изоляция данных, масштаб в миллиарды серий |

**Критерии выбора:**
*   **Thanos** — если требуется минимальное изменение существующей инфраструктуры и прозрачное расширение.
*   **VictoriaMetrics** — если приоритет — производительность и простота эксплуатации на локальных дисках.
*   **Grafana Mimir** — если требуется мульти-тенантность и горизонтальное масштабирование в облачных/объектных хранилищах.

### Безопасность и отказоустойчивость

1.  **RBAC:** Prometheus требует прав на чтение API (Nodes, Services, Endpoints, Pods). Используйте ClusterRole с минимально необходимым набором `verbs`.
2.  **Network Policies:** Ограничение доступа к портам 9090 и 9093.
3.  **Высокая доступность (HA):** Развертывание 2 реплик Prometheus. Alertmanager автоматически дедуплицирует идентичные алерты от разных реплик.
4.  **TLS:** Для внутренних сервисов с самоподписанными сертификатами используйте `tlsConfig.ca` в ServiceMonitor.
5.  **Security Context:** Запускайте Prometheus от непривилегированного пользователя (`runAsNonRoot: true`, `runAsUser: 1000`), используйте `readOnlyRootFilesystem` и `allowPrivilegeEscalation: false`.

> **См. также:** [Prometheus Security](../security.md), [Масштабирование](../scaling/overview.md), [HA в Prometheus Operator](./operator/high_availability.md).
