# Обзор Helm-чарта kube-prometheus-stack

## Определения

**kube-prometheus-stack (KPS)** — основной Helm-чарт сообщества для развёртывания полной экосистемы наблюдаемости (Observability) в Kubernetes. Управляет жизненным циклом Prometheus, Alertmanager, Grafana и набор экспортеров через декларативную конфигурацию в `values.yaml`.

**Промежуточный чарт (Umbrella Chart)** — архитектурный паттерн Helm, при котором один чарт объединяет несколько независимых субчартов (`grafana`, `kube-state-metrics`, `prometheus-node-exporter`) для упрощения управления зависимостями и общей конфигурации.

**Prometheus Operator** — ядро стека, обеспечивающее работу Kubernetes-native мониторинга через Custom Resource Definitions (CRD). Отслеживает изменения в ресурсах и автоматически генерирует конфигурацию Prometheus.

**TSDB (Time Series Database)** — встроенное хранилище Prometheus, оптимизированное для хранения и запросов временных рядов. Использует формат сжатия на основе Gorilla и механизм WAL (Write-Ahead Log) для надёжности.

**Retention (период хранения)** — интервал времени, в течение которого Prometheus сохраняет сырые метрики в TSDB. По истечении retention данные удаляются или сжимаются.

**scrapeClasses** — механизм в `kube-prometheus-stack` (начиная с v50+), позволяющий определять именованные наборы правил relabeling в `values.yaml`. Эти правила автоматически внедряются в конфигурацию скрейпинга компонентов, что позволяет избегать дублирования YAML-кода.

**Remote Write 2.0** — протокол отправки метрик из Prometheus во внешние системы хранения (Thanos, Cortex, Mimir). Поддерживает потоковую передачу, сжатие и заголовки аутентификации.

**Native Histograms** — формат гистограмм, интегрированный в Prometheus 3.x, при котором каждый бин хранится как отдельный тайм-сериес. Снижает потребление памяти и упрощает запросы по процентилям.

**Reconciliation Loop (цикл согласования)** — процесс в Prometheus Operator, при котором контроллер continuously сравнивает желаемое состояние (CRD) с фактическим (Kubernetes-объекты) и приводит их в соответствие.

### Преимущества запуска в кластере

В отличие от мониторинга внешним инстансом Prometheus (на VM/Bare Metal), запуск внутри Kubernetes даёт следующие преимущества:
- **Близость к целям:** Сбор метрик происходит максимально близко к подам, что снижает сетевые задержки и упрощает сетевую связность.
- **Использование инфраструктуры:** Prometheus использует те же ресурсы (узлы, диски, сеть), что и мониторимые приложения, не требуя выделенных серверов.
- **Service Discovery:** Нативная интеграция с Kubernetes API для автоматического обнаружения динамических объектов.

> **См. также:** [Мониторинг Kubernetes — общий обзор](../overview.md), [Prometheus Operator](../operator/concepts.md), [Helm](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md).

## Основные концепции

### Актуальные версии (на август 2026 г.)

| Компонент | Версия | Статус |
| :--- | :--- | :--- |
| **Helm-чарт** | 88.1.x+ | Текущий стабильный релиз |
| **Prometheus Server** | 3.12.x+ | Поддержка Remote Write 2.0, Native Histograms |
| **Alertmanager** | 0.32.x+ | Улучшенная кластеризация |
| **Grafana** | 12.4.x+ | Интеграция с Unified Alerting и Alloy |
| **Prometheus Operator** | 0.92.x+ | Поддержка ScrapeConfig и OTLP |
| **Kubernetes** | 1.28 - 1.34 | Рекомендуемый диапазон версий |

> **Важно:** Актуальные спецификации чарта доступны на [Artifact Hub](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack).

### Архитектура стека

| Компонент | Тип объекта | Назначение |
| :--- | :--- | :--- |
| **Prometheus Server** | StatefulSet | Сбор, хранение (TSDB) и обработка метрик. |
| **Alertmanager** | StatefulSet | Дедупликация и маршрутизация оповещений. |
| **Grafana** | Deployment | Визуализация, дашборды, мониторинг алертов. |
| **Prometheus Operator** | Deployment | Автоматизация конфигурации через CRD. |
| **Node Exporter** | DaemonSet | Системные метрики ОС с каждого узла. |
| **Kube-State-Metrics** | Deployment | Генерация метрик на основе объектов API K8s. |
| **Blackbox Exporter** | Deployment | Проверки доступности эндпоинтов (HTTP, TCP). |
| **OTLP Ingest** | Service | (v3.0+) Прием данных напрямую по протоколу OpenTelemetry. |

### Жизненный цикл компонентов (Reconciliation)

Prometheus Operator управляет компонентами через цикл согласования:

1. **Наблюдение (Watch):** Оператор отслеживает объекты CRD (`Prometheus`, `Alertmanager`, `ServiceMonitor` и др.) в кластере.
2. **Валидация:** Проверка корректности спецификации (ресурсы, селекторы, права).
3. **Генерация:** Создание/обновление Kubernetes-объектов (StatefulSet, Service, ConfigMap, Secret) на основе CRD.
4. **Мониторинг:** Отслеживание состояния созданных объектов (ready replicas, условия).
5. **Корректировка:** При отклонении фактического состояния от желаемого — повторная генерация.

**Ключевые особенности:**
- Оператор не изменяет пользовательские объекты напрямую, а создаёт новые или обновляет управляемые им.
- При удалении CRD все связанные ресурсы (StatefulSet, Service, ConfigMap) удаляются автоматически.
- Sidecar `configmap-reload` отслеживает изменения ConfigMap/Secret и инициирует reload основного контейнера через HTTP POST `/-/reload`.

### Архитектура хранения (TSDB)

Prometheus TSDB состоит из нескольких уровней:

- **Head block:** Активные данные, поступающие в реальном времени. Хранится в памяти и на диске в формате WAL.
- **Persistent blocks:** Сжатые блоки данных, сформированные после compaction. Хранятся на диске в формате chunks и индексы.
- **WAL (Write-Ahead Log):** Журнал предзаписи, обеспечивающий durability при перезапусках. Данные в head block не сбрасываются в persistent blocks до выполнения compaction.

**Параметры хранения в values.yaml:**

```yaml
prometheus:
  prometheusSpec:
    retention: 30d # Период хранения сырых данных
    retentionSize: 100Gi # Максимальный размер данных (приоритетнее retention)
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: premium-rwo
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi
```

> **Важно:** `retentionSize` (введён в Prometheus 2.40+) имеет приоритет над `retention`. Если размер превышен, старые данные удаляются независимо от срока хранения.

### Механизм scrapeClasses

`scrapeClasses` позволяет определить именованные наборы relabeling-правил, которые применяются к PodMonitor/ServiceMonitor автоматически.

```yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter-standard
        relabelings:
          - action: labelmap
            regex: __meta_kubernetes_pod_label_(.+)
          - action: replace
            sourceLabels: [__meta_kubernetes_node_name]
            targetLabel: instance
```

Привязка класса к компоненту:

```yaml
nodeExporter:
  podMonitor:
    scrapeClass: "node-exporter-standard"
```

**Преимущества:**
- Централизованное управление relabeling без дублирования кода в каждом ServiceMonitor.
- Переиспользование конфигураций между компонентами.
- Упрощение миграции при изменении политик именования.

### Remote Write и федерация

**Remote Write** — механизм отправки метрик из Prometheus во внешние хранилища.

```yaml
prometheus:
  prometheusSpec:
    remoteWrite:
      - url: "http://thanos-receive.monitoring.svc:19291/api/v1/receive"
        headers:
          X-Scope-OrgID: "default"
        writeRelabelings:
          - sourceLabels: [__name__]
            regex: "go_.*|process_.*"
            action: drop
```

**Федерация (Federation)** — устаревший механизм агрегации метрик между Prometheus. В KPS используется через параметр `externalLabels` и federation endpoint:

```yaml
prometheus:
  prometheusSpec:
    externalLabels:
      cluster: "prod-main"
      region: "eu-west"
    federation:
      enabled: true
```

> **Рекомендация:** Для мульти-кластерных сценариев используйте Thanos (см. [Масштабирование](../../scaling/overview.md)), а не федерацию.

### Service Discovery pipeline

В KPS Service Discovery работает на двух уровнях:

1. **Kubernetes-native (CRD):** Prometheus Operator преобразует `ServiceMonitor`/`PodMonitor` в конфигурацию `kubernetes_sd_configs` и автоматически обновляет её при изменениях объектов.
2. **Statically configured (ScrapeConfig):** Для произвольных целей (внешние сервисы, OTLP-инжест).

**Пример pipeline:**

```
ServiceMonitor CRD
    ↓ (Operator watches)
Endpoints/EndpointSlice
    ↓ (Relabeling)
Prometheus scrape config
    ↓
TSDB (head → persistent blocks)
```

### Зависимости чарта

Чарт интегрирует следующие субчарты, управление которыми происходит через соответствующие секции в `values.yaml`:

- `prometheus-node-exporter` (секция `nodeExporter.*`)
- `kube-state-metrics` (секция `kubeStateMetrics.*`)
- `grafana` (секция `grafana.*`)
- `prometheus-windows-exporter` (секция `windowsMonitoring.*`)

### Ключевые ресурсы (CRD)

| Ресурс | Назначение | Подробности |
| :--- | :--- | :--- |
| **ServiceMonitor** | Сбор метрик с Kubernetes Services. | [ServiceMonitor CRD](../operator/crd/servicemonitor.md) |
| **PodMonitor** | Прямой скрейпинг подов (sidecars). | [PodMonitor CRD](../operator/crd/podmonitor.md) |
| **ScrapeConfig** | Произвольные конфигурации скрейпинга (OTLP, внешние цели). | [Prometheus Operator — концепции](../operator/concepts.md) |
| **PrometheusRule** | Описание правил алертинга и агрегации. | [PrometheusRule CRD](../operator/crd/prometheusrule.md) |
| **Probe** | Настройка статических проверок Blackbox Exporter. | [Probe CRD](../operator/crd/probe.md) |
| **AlertmanagerConfig** | Управление маршрутами и получателями алертов. | [AlertmanagerConfig CRD](../operator/crd/alertmanagerconfig.md) |
| **Prometheus** | Декларативное описание инстанса Prometheus Server. | [Prometheus CRD](../operator/crd/prometheus.md) |

### Взаимодействие values.yaml и CRD

Helm-чарт служит транслятором между параметрами `values.yaml` и спецификациями CRD:

- `prometheus.prometheusSpec.*` → вставляется в `.spec` ресурса `Prometheus`.
- `defaultRules.*` → генерирует объекты `PrometheusRule` с предустановленными группами.
- `nodeExporter.*` → конфигурирует субчарт, который создаёт `PodMonitor` для Node Exporter.

**Важно:** Параметры в `values.yaml` имеют приоритет над значениями по умолчанию в субчартах, но CRD, созданные вручную, могут переопределять селекторы (`serviceMonitorSelector`, `podMonitorSelector`).

## Практические сценарии

### Предварительные требования

#### Аппаратные требования (Medium Cluster, ~50 нод, ~500 подов)

| Компонент | CPU Request | Memory Request | CPU Limit | Memory Limit |
| :--- | :--- | :--- | :--- | :--- |
| **Prometheus** | 500m | 2Gi | 2000m | 8Gi |
| **Alertmanager** | 100m | 256Mi | 500m | 512Mi |
| **Grafana** | 200m | 512Mi | 1000m | 1Gi |
| **Operator** | 100m | 128Mi | 200m | 256Mi |

> **Примечание:** При использовании Native Histograms потребление памяти Prometheus может снизиться на 20–40% за счёт оптимизированного хранения.

#### Программные требования

- Kubernetes 1.28+ (проверьте через `kubectl version --short`).
- Helm 3.14+ (`helm version`).
- `kubectl` с configured контекстом кластера (`kubectl config current-context`).
- StorageClass с поддержкой `ReadWriteOnce` для Prometheus и Alertmanager.
- Для Grafana HA: StorageClass с поддержкой `ReadWriteMany` или внешняя СУБД (PostgreSQL/MySQL).

#### Инициализация окружения

```bash
# 1. Создание выделенного пространства имен
kubectl create namespace monitoring

# 2. Настройка default ServiceAccount (опционально, но рекомендуется)
kubectl create serviceaccount monitoring-sa -n monitoring
kubectl create clusterrolebinding monitoring-sa-binding \
  --clusterrole=cluster-admin \
  --serviceaccount=monitoring:monitoring-sa
# → В production используйте RBAC с минимальными правами (см. раздел Безопасность)

# 3. Проверка доступности StorageClass
kubectl get storageclass
```

### Быстрый старт

```bash
# Создание выделенного пространства имен
kubectl create namespace monitoring

# Добавление репозитория сообщества
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка с настройками по умолчанию
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Валидация установки

После установки выполните последовательность проверок:

```bash
# 1. Проверка статуса всех подов (все должны быть в Running)
kubectl get pods -n monitoring -l release=monitoring

# 2. Проверка статуса всех сервисов
kubectl get svc -n monitoring -l release=monitoring

# 3. Проверка CRD (должны быть созданы 7 CRD)
kubectl get crd | grep monitoring.coreos.com
# → prometheuses.monitoring.coreos.com
# → alertmanagers.monitoring.coreos.com
# → servicemonitors.monitoring.coreos.com
# → podmonitors.monitoring.coreos.com
# → prometheusrules.monitoring.coreos.com
# → probes.monitoring.coreos.com
# → alertmanagerconfigs.monitoring.coreos.com

# 4. Проверка endpoints Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &
# → Открыть http://localhost:9090/targets
# → Все targets должны быть в статусе UP

# 5. Проверка готовности Grafana
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80 &
# → Открыть http://localhost:3000
# → Логин: admin / пароль из Secret monitoring-grafana
```

**Ожидаемые результаты:**
- Поды `prometheus-operator`, `prometheus-monitoring-kube-prometheus-0`, `alertmanager-monitoring-kube-prometheus-alertmanager-0` имеют статус `Running`.
- Target `prometheus-monitoring-kube-prometheus-0` в Prometheus UI имеет статус `UP`.
- Дашборды Grafana содержат разделы `Kubernetes / Compute Resources`, `Prometheus`, `Alertmanager`.

### Рекомендуемый рабочий процесс (GitOps/Local Copy)

Использование локальной копии чарта и плагина `helm-diff` является промышленным стандартом.

```bash
# 1. Скачивание и распаковка чарта
helm pull prometheus-community/kube-prometheus-stack --untar

# 2. Создание файла переопределений
cp kube-prometheus-stack/values.yaml my-values.yaml

# 3. Просмотр планируемых изменений
helm diff upgrade monitoring ./kube-prometheus-stack \
  --namespace monitoring \
  -f my-values.yaml

# 4. Применение изменений
helm upgrade monitoring ./kube-prometheus-stack \
  --namespace monitoring \
  -f my-values.yaml
```

### Диагностика после установки

```bash
# Проверка статуса всех компонентов
kubectl get all -n monitoring -l release=monitoring

# Просмотр логов Prometheus Operator (критично при проблемах с CRD)
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Проверка активных целей (Targets) в Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
# → Открыть http://localhost:9090/targets

# Проверка событий в namespace (выявляет ошибки планирования)
kubectl get events -n monitoring --sort-by='.lastTimestamp'

# Описание ресурса Prometheus (CRD)
kubectl describe prometheus monitoring-kube-prometheus-prometheus -n monitoring
```

### Обновление и откат

```bash
# Обновление репозитория
helm repo update

# Обновление релиза
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f my-values.yaml

# Проверка rollout после обновления
kubectl rollout status statefulset/prometheus-operated -n monitoring --timeout=5m
kubectl rollout status statefulset/alertmanager-monitoring-kube-prometheus-alertmanager -n monitoring --timeout=5m

# Откат к предыдущей версии
helm rollback monitoring -n monitoring
```

> **Важно:** Перед обновлением всегда просматривайте изменения через `helm diff upgrade`. При обновлении мажорных версий CRD необходимо обновить вручную (см. [Конфигурация Alertmanager](./alertmanager_config.md)).

### Удаление

```bash
# Удаление релиза
helm uninstall monitoring -n monitoring

# Удаление CRD (осторожно — удалит все Custom Resources!)
kubectl delete crd prometheuses.monitoring.coreos.com
kubectl delete crd alertmanagers.monitoring.coreos.com
kubectl delete crd servicemonitors.monitoring.coreos.com
kubectl delete crd podmonitors.monitoring.coreos.com
kubectl delete crd prometheusrules.monitoring.coreos.com
kubectl delete crd probes.monitoring.coreos.com
kubectl delete crd alertmanagerconfigs.monitoring.coreos.com
```

> **Важно:** Удаление CRD приведёт к потере всех созданных ресурсов мониторинга в кластере.

### Резервное копирование и восстановление

#### Экспорт конфигурации

```bash
# 1. Список всех Helm-релизов
helm list -A | grep monitoring

# 2. Экспорт значений релиза
helm get values monitoring -n monitoring > backup-values.yaml

# 3. Экспорт всех CRD и ресурсов Prometheus Operator
kubectl get prometheus,alertmanager,servicemonitor,podmonitor,prometheusrule,probe,alertmanagerconfig \
  -n monitoring -o yaml > backup-prometheus-resources.yaml

# 4. Экспорт секретов (пароли Grafana, TLS-сертификаты)
kubectl get secrets -n monitoring -o yaml > backup-monitoring-secrets.yaml

# 5. Экспорт CRD (для переноса в другой кластер)
kubectl get crd monitoring.coreos.com_* -o yaml > backup-prometheus-crds.yaml
```

#### Восстановление

```bash
# 1. Восстановление секретов
kubectl apply -f backup-monitoring-secrets.yaml

# 2. Восстановление CRD (если удалены)
kubectl apply -f backup-prometheus-crds.yaml

# 3. Установка/обновление Helm-релиза
helm upgrade monitoring ./kube-prometheus-stack \
  -n monitoring \
  -f backup-values.yaml

# 4. Восстановление пользовательских ресурсов
kubectl apply -f backup-prometheus-resources.yaml
```

### Диагностика и устранение неполадок (Troubleshooting)

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Pods в статусе Pending** | Недоступен StorageClass или PVC | Проверьте `kubectl get pvc -n monitoring`; убедитесь, что StorageClass поддерживает requested access mode. |
| **ImagePullBackOff** | Rate limit на docker.io или отсутствие доступа | Настройте `global.imagePullSecrets`; используйте зеркало registry. |
| **Target status: DOWN** | Неверные селекторы в ServiceMonitor | Проверьте labels на сервисе и `matchLabels` в ServiceMonitor. |
| **Target DOWN (TLS error)** | Ошибка сертификатов | Проверьте `serverName` и пути к сертификатам в ServiceMonitor. |
| **Prometheus OOMKilled** | Недостаточно памяти при всплеске | Увеличьте `memoryLimit`; включите `enableFeatures: [native-histograms]`. |
| **Grafana 404/502 (Ingress)** | Ошибка в конфигурации путей | Проверьте `grafana.ingress.path` и `pathType` (обычно Prefix). |
| **AlertmanagerConfig не применяется** | Пустой `alertmanagerConfigSelector` | Установите селектор в `values.yaml` (см. [Конфигурация Alertmanager](./alertmanager_config.md)). |
| **CRD конфликт при установке** | Уже существуют CRD от другой версии | Удалите старые CRD или используйте `--skip-crds` при ручном управлении. |
| **Prometheus не видит поды** | Отсутствуют права RBAC | Проверьте, что ServiceAccount имеет `list/watch` на `pods` в нужных namespaces. |

#### Полезные команды для диагностики

```bash
# Логи оператора (основной источник правды при ошибках конфигурации)
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=100

# Логи sidecar reload
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus -c configmap-reload

# Проверка условий ресурса Prometheus
kubectl get prometheus monitoring-kube-prometheus-prometheus -n monitoring -o yaml

# Проверка сгенерированного конфига Prometheus
kubectl get secret monitoring-kube-prometheus-prometheus -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip -c | head -50

# Проверка сгенерированного конфига Alertmanager
kubectl get secret monitoring-kube-prometheus-alertmanager -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
```

### Ограничения и крайние случаи (Edge Cases)

1. **Размер ConfigMap:** Общий размер данных в ConfigMap не должен превышать 1 МБ. Для больших дашбордов используйте сжатие (`sidecar.dashboards.GZIP: true`) или разделите дашборды на несколько ConfigMap.
2. **Имена ресурсов:** Имя Helm-релиза влияет на имена всех ресурсов. Используйте короткие имена (например, `monitoring`), чтобы избежать превышения лимита 253 символов в DNS.
3. **Горячее обновление Operator:** При обновлении чарта Operator перезапускается. В это время управление CRD приостанавливается. Для production используйте Rolling Update Strategy с `maxSurge: 1` и `maxUnavailable: 0`.
4. **Производительность при большом количестве ServiceMonitor:** При >1000 ServiceMonitor в кластере Operator может потреблять значительные ресурсы CPU. Рекомендуется шардирование Prometheus (`shards`) или использование Thanos Ruler.
5. **Зависшие Pod Monitor:** При изменении label селектора PodMonitor, существующие Pod Monitor не удаляются автоматически. Необходимо очистить их вручную или выполнить helm upgrade с `--force`.

### Очистка окружения

```bash
# Полное удаление стека (с сохранением CRD)
helm uninstall monitoring -n monitoring

# Полное удаление включая CRD (ОСТОРОЖНО!)
helm uninstall monitoring -n monitoring
kubectl delete crd -l app.kubernetes.io/managed-by=Helm -n monitoring

# Удаление namespace (если пустой)
kubectl delete namespace monitoring

# Очистка объектных хранилищ (если используются)
kubectl get pvc -n monitoring
kubectl delete pvc <pvc-name> -n monitoring
```

## Дополнительная информация

### Структура values.yaml (Ключевые секции)

В 2026 году чарт предоставляет расширенные механизмы управления скрейпингом:

```yaml
# Глобальные настройки
global:
  imageRegistry: quay.io # Переопределение для закрытых контуров

# Prometheus Server
prometheus:
  prometheusSpec:
    retention: 30d
    enableFeatures:
      - native-histograms
      - remote-write-receiver
    # Механизм scrapeClasses для переиспользования конфигураций
    scrapeClasses:
      - name: default
        relabelings:
          - action: labelmap
            regex: __meta_kubernetes_pod_label_(.+)
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: premium-rwo
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi

# Grafana (интеграция субчарта)
grafana:
  enabled: true
  adminPassword: "измените_меня"
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      searchNamespace: ALL

# Автоматический мониторинг компонентов K8s
kubeApiServer:
  enabled: true
kubeEtcd:
  enabled: true
```

### Рекомендации по производительности TSDB

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| `retention` | 30d — 90d | Слишком длинный retention увеличивает размер TSDB и время compaction. |
| `retentionSize` | 80% от объёма PVC | Оставьте 20% запас для временных файлов compaction. |
| `storageSpec.resources.requests.storage` | ≥ 2 × ожидаемого объёма сырых данных | TSDB требует места для WAL и временных файлов. |
| `enableFeatures: [native-histograms]` | Включить при возможности | Снижает потребление памяти на 20–40% при высокой кардинальности. |
| `walCompression` | `true` (по умолчанию) | Сжимает WAL, уменьшая I/O. |

### Рекомендации по безопасности

1. **High Availability (HA):** Всегда устанавливайте `prometheus.prometheusSpec.replicas: 2` и `alertmanager.alertmanagerSpec.replicas: 3` для production-сред.
2. **RBAC:** Используйте `serviceAccounts` с ограниченными правами для экспортеров. Минимальные права:
   - Prometheus Operator: `cluster-admin` (требуется для управления CRD и ресурсами).
   - Prometheus Server: `get`, `list`, `watch` на `services`, `endpoints`, `pods`, `nodes` в мониторимых namespaces.
   - Node Exporter: `hostPID`, `hostNetwork` через `securityContext` DaemonSet.
3. **Network Policies:** Включайте изоляцию трафика мониторинга:
   ```yaml
   prometheus:
     networkPolicy:
       enabled: true
       allowExternal: false # Разрешить только внутренний трафик
   ```
4. **Secrets Management:** Не храните пароли в `values.yaml`. Используйте `existingSecret` или внешние секреты (External Secrets Operator):
   ```yaml
   grafana:
     admin:
       existingSecret: "grafana-admin-secret"
       adminUserKey: "username"
       adminPasswordKey: "password"
   ```

### Связанные темы

- [Конфигурация компонентов](./other_components_config.md) — детализация разделов `values.yaml` (RBAC, reload, default rules, Thanos Ruler, Push Gateway).
- [Конфигурация Alertmanager](./alertmanager_config.md) — routing, receivers, AlertmanagerConfig CRD.
- [Конфигурация Grafana](./grafana_config.md) — sidecar, provisioning, HA, OAuth.
- [Практические сценарии](./practical_scenarios.md) — специфические кейсы установки.
- [Мониторинг etcd](./etcd-monitoring.md) — TLS, ServiceMonitor, EndpointSlice.
