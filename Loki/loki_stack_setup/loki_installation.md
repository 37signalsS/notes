# Установка Loki в Kubernetes

## Определения

**Loki Helm-чарт** — официальный пакет для автоматизированного развертывания Grafana Loki в Kubernetes. Начиная с версии 3.x, чарт поддерживает три основных режима: Single Binary (монолит), Simple Scalable (масштабируемый) и Distributed (микросервисный). Основной упор сделан на производительности запросов и поддержке нативного поиска по Bloom-фильтрам.

**Мультиарендность (Multi-tenancy)** — режим работы Loki, позволяющий изолировать данные разных команд (тенантов) в рамках одного кластера. Идентификация происходит по HTTP-заголовку `X-Scope-OrgID`.

**Важное замечание (март 2026):** Репозиторий `grafana https://grafana.github.io/helm-charts` переведен в режим обслуживания. Актуальный чарт Loki теперь находится в репозитории `grafana-community`.

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
```

**Текущая версия (август 2026):** Loki 3.x (стабильная), Helm-чарт 6.60.x+

**Подробнее:** [Обзор Grafana Loki](../loki_overview.md)

## Основные концепции

### Режимы развертывания

| Режим | Компоненты | Назначение |
| :--- | :--- | :--- |
| **Single Binary** | Все компоненты в одном поде | Тестирование, разработка, малые нагрузки (< 10 ГБ/день) |
| **Simple Scalable** | Группировка: Read, Write и Backend | Рекомендуемый режим для Production средних и крупных масштабов |
| **Distributed** | Каждый микросервис (Ingester, Querier, Distributor, Querier-Frontend и др.) отдельно | Экстремальные нагрузки, требующие независимого масштабирования |

### Архитектура Simple Scalable (рекомендуемый режим)

В этом режиме компоненты группируются по типам нагрузки. Gateway (Nginx) выступает единой точкой входа, маршрутизируя трафик:
-   **Write таргет:** Distributor → Ingester (запись в хранилище).
-   **Read таргет:** Query Frontend → Querier (чтение из хранилища и кешей).
-   **Backend таргет:** Compactor, Ruler, Index Gateway (обслуживание индекса и правил).

```
┌─────────┐     ┌──────────┐     ┌─────────┐
│ Gateway │────→│  Write   │────→│ Storage │
│ (Nginx) │     │ (Ingester)│     │  (S3)   │
└────┬────┘     └──────────┘     └─────────┘
     │
     │     ┌──────────┐     ┌─────────┐
     └────→│   Read   │────→│  Cache  │
           │(Querier) │     │ (Redis) │
           └──────────┘     └─────────┘
           ┌──────────┐
           │ Backend  │
           │(Compactor)│
           └──────────┘
```

### Теоретические основы выбора режима

Выбор режима развертывания определяется тремя факторами: объемом логов, требованиями к доступности и бюджетом на инфраструктуру.

**Single Binary** подходит, когда все компоненты Loki работают в одном процессе. Это снижает операционные накладные расходы: один Deployment, один Service, одна конфигурация. Однако при отказе узла теряется вся функциональность. Для восстановления требуется перезапуск пода, а свежие данные, находившиеся в WAL и памяти, могут быть утрачены. Репликация в этом режиме отсутствует (`replication_factor: 1`).

**Simple Scalable** разделяет Write и Read пути. Distributor распределяет нагрузку по инжестерам на основе хеша меток лейблов (labels), что обеспечивает горизонтальное масштабирование записи. Querier читает данные из памяти инжестеров (горячие данные за последние 1–2 часа) и из объектного хранилища (холодные данные). Gateway балансирует трафик между этими группами. Фактор репликации `replication_factor: 3` гарантирует, что каждый чанк сохраняется в трех разных узлах, защищая от потерь при отказе одного инжестера.

**Distributed** развертывает каждый микросервис отдельно. Это дает максимальный контроль над масштабированием: например, при аналитической нагрузке можно добавить Querier без увеличения Ingester. Однако количество объектов в Kubernetes резко возрастает, что увеличивает сложность администрирования и потребление ресурсов control plane.

### Ключевые особенности Loki 3.x

1.  **Bloom Filters:** Позволяют ускорить поиск по неиндексированным данным (grep-подобный поиск) до 10-50 раз за счет отсечения чанков, не содержащих искомые токены.
2.  **Structured Metadata:** Поддержка прикрепления метаданных к строкам логов на стороне агента (например, Alloy), что позволяет фильтровать логи без создания "тяжелых" лейблов и раздувания индекса.
3.  **TSDB Index:** Основной формат индекса, обеспечивающий высокую плотность хранения, быструю загрузку и поддержку Bloom-фильтров.

### Жизненный цикл данных в Loki

Понимание пути данных необходимо для диагностики проблем и планирования емкости.

1.  **Сбор:** Агент (Alloy/Promtail) читает логи, присваивает статические лейблы и отправляет в Loki через HTTP POST `/loki/api/v1/push`.
2.  **Прием (Distributor):** Проверяет лимиты tenant'а, валидирует запрос и распределяет по инжестерам на основе хеша меток.
3.  **Буферизация (Ingester):** Логи накапливаются в памяти в виде чанков. Параллельно данные записываются в WAL (Write-Ahead Log) на локальный диск.
4.  **Сброс (Flush):** По достижении порога чанк сжимается и отправляется в объектное хранилище.
5.  **Индексация:** Метаданные stream записываются в TSDB Index. В версии 3.x параллельно строятся Bloom-фильтры.
6.  **Компакция:** Compactor объединяет индексные файлы, удаляет дубликаты и применяет retention.
7.  **Запрос:** Query Frontend проверяет кэш и Bloom-фильтры. Querier читает чанки из памяти инжестеров и из хранилища.

## Практические сценарии

### Подготовка окружения

**Требования к кластеру:**
- Kubernetes ≥ 1.28 (рекомендуется ≥ 1.30 для актуальных Helm-чартов)
- Helm ≥ 3.12
- Объектное хранилище (S3/MinIO) для production режимов
- StorageClass с поддержкой динамического выделения для Backend PVC

**Проверка инструментов:**
```bash
# → kubectl v1.30+
kubectl version --client

# → Helm v3.12+
helm version

# → Проверка доступа к кластеру
kubectl get nodes
```

### Подготовка репозитория Helm

```bash
# Добавление актуального репозитория
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Получение стандартных значений для анализа
helm show values grafana-community/loki > loki_values.yaml
```

### Сценарий 1: Production — Simple Scalable с S3 и Bloom-фильтрами

Обеспечивает высокую доступность и производительность для средних и больших нагрузок.

**Файл `loki_values.yaml`:**

```yaml
deploymentMode: SimpleScalable

loki:
  auth_enabled: true

  storage:
    type: s3
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
      admin: loki-admin
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
      secretAccessKey: ${S3_SECRET_KEY}
      accessKeyId: ${S3_ACCESS_KEY}

  commonConfig:
    replication_factor: 3

  schemaConfig:
    configs:
      - from: "2024-01-01"
        store: tsdb
        object_store: s3
        schema: v13
        index:
          prefix: index_
          period: 24h

  bloom_build_config:
    enabled: true
  bloom_gateway:
    enabled: true

  limits_config:
    retention_period: 744h
    max_query_series: 5000
    allow_structured_metadata: true
    ingestion_rate_mb: 10
    ingestion_burst_size_mb: 20

  ingester:
    max_chunk_age: 2h
    chunk_target_size: 1572864

monitoring:
  dashboards:
    enabled: true
  serviceMonitor:
    enabled: true
  selfMonitoring:
    enabled: false

write:
  replicas: 3
  resources:
    requests:
      cpu: 1
      memory: 2Gi
    limits:
      cpu: 2
      memory: 4Gi

read:
  replicas: 3
  resources:
    requests:
      cpu: 1
      memory: 4Gi
    limits:
      cpu: 4
      memory: 8Gi

backend:
  replicas: 2
  persistence:
    enabled: true
    size: 10Gi

gateway:
  enabled: true
  replicas: 2
```

**Пояснения к ключевым параметрам:**

- `replication_factor: 3` — каждый чанк хранится в трех копиях. Для отказоустойчивости требуется минимум 3 инжестера.
- `schema: v13` — актуальная версия схемы, поддерживающая structured metadata и Bloom-фильтры.
- `period: 24h` — ротация индексных файлов каждые 24 часа. Меньший период ускоряет компакцию, но увеличивает количество файлов.
- `max_chunk_age: 2h` — максимальный возраст чанка перед принудительным сбросом. Для систем с пиковой нагрузкой рекомендуется 1–2 часа.
- `chunk_target_size: 1572864` (~1.5 МБ) — целевой размер чанка. Меньший размер улучшает сжатие, но увеличивает количество файлов в S3.
- `ingestion_rate_mb: 10` — скорость записи на один инжестер. При превышении Loki возвращает 429.
- `ingestion_burst_size_mb: 20` — burst-буфер для кратковременных пиков.

### Сценарий 2: Тестирование — Single Binary с локальным хранилищем

Минимальное потребление ресурсов для разработки.

```yaml
deploymentMode: SingleBinary

loki:
  auth_enabled: false
  storage:
    type: filesystem
  commonConfig:
    replication_factor: 1
  schemaConfig:
    configs:
      - from: "2024-01-01"
        store: tsdb
        object_store: filesystem
        schema: v13

singleBinary:
  replicas: 1
  persistence:
    enabled: true
    size: 10Gi

gateway:
  enabled: true
```

**Важно:** В Single Binary режиме filesystem не обеспечивает репликацию. При удалении PVC данные теряются безвозвратно. Не используйте этот режим для production.

### Сценарий 2.1: GitOps через Argo CD (Application)

Декларативная установка через Argo CD с использованием Custom Resource `Application` — предпочтительный подход для production-кластеров с GitOps workflow.

**Файл `loki-application.yaml`:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: loki
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: logging
  source:
    repoURL: https://grafana-community.github.io/helm-charts
    chart: loki
    targetRevision: "6.x"
    helm:
      releaseName: loki
      values: |
        deploymentMode: SingleBinary
        loki:
          commonConfig:
            replication_factor: 1
          storage:
            type: filesystem
          auth_enabled: false
          limits_config:
            retention_period: 30d
            ingestion_rate_mb: 16
            ingestion_burst_size_mb: 32
          singleBinary:
            replicas: 1
            persistence:
              enabled: true
              storageClass: local-path
              size: 50Gi
          monitoring:
            serviceMonitor:
              enabled: true
              labels:
                release: kube-prom-stack
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - SkipDryRunOnMissingResource=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

**Требования:**
- Argo CD (версии 3.5+) с установленным `argocd-application-controller` и `argocd-repo-server`
- Namespace `argocd` для размещения объектов `Application` и `AppProject`
- Namespace, в котором будет создан `Application` (в примере — `observability`)
- StorageClass с поддержкой динамического выделения PV (например, `local-path`, `cephfs`, `gp2`)

**SingleBinary** запускает все компоненты в одном поде. Для production используйте `SimpleScalable` или `Distributed` с объектным хранилищем (S3/MinIO).

**Валидация:**
```bash
# 1. Проверка статуса Application
argocd app get loki
# → Name:               loki
# → Server:             https://kubernetes.default.svc
# → Namespace:          observability
# → Sync Status:        Synced to 6.x
# → Health Status:      Healthy

# 2. Проверка подов
kubectl get pods -n observability -l app.kubernetes.io/name=loki
# → loki-singleBINARY-xxx  Running

# 3. Проверка readiness
kubectl wait --for=condition=ready pod -n observability -l app.kubernetes.io/name=loki
curl -s http://loki.observability.svc.cluster.local:3100/ready
# → ready
```

### Сценарий 3: Настройка безопасности и доступа

Для работы с включенной мультиарендностью (`auth_enabled: true`), все запросы должны содержать заголовок `X-Scope-OrgID`.

1.  **На стороне агента (Alloy):**
    ```river
    loki.write "default" {
      endpoint {
        url = "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push"
        headers = {
          "X-Scope-OrgID" = "team-alpha",
        }
      }
    }
    ```
2.  **На стороне Grafana:**
    В настройках DataSource необходимо добавить пользовательский HTTP заголовок `X-Scope-OrgID: team-alpha`.

### Сценарий 4: Сеть и безопасность (NetworkPolicy, RBAC)

**NetworkPolicy для Loki:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: loki-network-policy
  namespace: logging
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: loki
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
          podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: logging
          podSelector:
            matchLabels:
              app.kubernetes.io/name: alloy
      ports:
        - protocol: TCP
          port: 3100
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: logging
      ports:
        - protocol: TCP
          port: 3100
    - to: []
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 443
```

**RBAC:**
Loki Helm-чарт автоматически создает ServiceAccount, Role и RoleBinding. Для интеграции с Prometheus Operator убедитесь, что сервис-аккаунт имеет права на создание ServiceMonitor и PodMonitor.

**TLS/mTLS:**
Для production рекомендуется включить TLS на Gateway. Используйте cert-manager для автоматической выдачи сертификатов:

```yaml
gateway:
  service:
    annotations:
      cert-manager.io/cluster-issuer: "letsencrypt-prod"
  ingress:
    enabled: true
    hosts:
      - host: loki.logging.example.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: loki-tls
        hosts:
          - loki.logging.example.com
```

### Сценарий 5: Мониторинг Loki через ServiceMonitor и Grafana

Включение ServiceMonitor позволяет Prometheus автоматически обнаруживать и собирать метрики Loki.

```yaml
monitoring:
  serviceMonitor:
    enabled: true
    labels:
      release: prometheus
  dashboards:
    enabled: true
```

**Ключевые метрики для мониторинга:**

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `loki_ingester_streams_created_total` | Количество активных streams | Резкий рост может указывать на взрыв cardinality |
| `loki_ingester_memory_chunks` | Чанки в памяти инжестера | Рост → возможна нехватка RAM |
| `loki_request_duration_seconds` | Длительность запросов | P99 > 10s → требуется оптимизация |
| `loki_distributor_sent_bytes_total` | Объем принятых данных | Для планирования емкости |
| `loki_compactor_retention_dry_runs_total` | Запуски retention в dry-run | Должен совпадать с реальными удалениями |
| `loki_querier_queries_total` | Количество запросов | Рост без увеличения нагрузки → возможен abusive querying |

### Сценарий 6: Резервное копирование и восстановление

**Бэкап конфигурации Helm:**

```bash
# Экспорт текущих значений релиза
helm get values loki -n logging -o yaml > loki-values-backup.yaml

# Экспорт манифестов релиза (включает все объекты Kubernetes)
helm get manifest loki -n logging > loki-manifests-backup.yaml
```

**Бэкап данных S3:**
Используйте инструменты вашего объектного хранилища (например, `aws s3 sync` для S3 или `mc mirror` для MinIO). Регулярность — согласно RPO/RTO политике организации.

**Восстановление:**
1. Восстановите namespace и секреты.
2. Выполните `helm upgrade --install` с сохраненными values.
3. Убедитесь, что `schemaConfig.from` соответствует дате последнего бэкапа.
4. Проверьте доступность данных через LogQL запрос.

### Сценарий 7: Обновление и откат (Rollback)

**Перед обновлением:**

```bash
# Запись текущей версии
helm list -n logging
helm get values loki -n logging > loki-values-pre-upgrade.yaml

# Создание бэкапа
kubectl get all -n logging -o yaml > logging-backup.yaml
```

**Выполнение обновления:**

```bash
helm repo update
helm upgrade --install loki grafana-community/loki \
  --namespace logging \
  -f loki_values.yaml \
  --atomic
```

**Откат при проблемах:**

```bash
# Просмотр истории релизов
helm history loki -n logging

# Откат на предыдущую ревизию
helm rollback loki <revision> -n logging
```

**Валидация после обновления:**
- Проверьте `/ready` эндпоинт.
- Выполните тестовый LogQL запрос.
- Проверьте метрики `loki_ingester_memory_chunks` и `loki_request_duration_seconds`.

### Сценарий 8: Capacity Planning и масштабирование

**Определение объема логов:**

```bash
# Сбор метрик за 7 дней с Prometheus
rate(loki_distributor_sent_bytes_total[7d]) * 86400 / 1024 / 1024 / 1024
# → ГБ/день
```

**Рекомендации по ресурсам:**

| Объем/день | Режим | Write реплики | Read реплики | Backend реплики | RAM (Write) | RAM (Read) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| < 10 ГБ | Single Binary | 1 | 1 | 1 | 2Gi | 2Gi |
| 10–50 ГБ | Simple Scalable | 2–3 | 2–3 | 2 | 2Gi | 4Gi |
| 50–200 ГБ | Simple Scalable | 3–5 | 3–5 | 2 | 4Gi | 8Gi |
| > 200 ГБ | Simple Scalable/Distributed | 5+ | 5+ | 3+ | 8Gi | 16Gi |

**Горизонтальное масштабирование (HPA):**

Для Write компонентов можно использовать HPA на основе CPU или кастомной метрики:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: loki-write-hpa
  namespace: logging
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: loki-write
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Pod Disruption Budget:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: loki-write-pdb
  namespace: logging
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/component: write
```

### Сценарий 8.1: Disaster Recovery — Deep Dive

Стратегия восстановления после сбоев для кластера Loki.

**RPO/RTO определения:**

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| **RPO (Recovery Point Objective)** | Максимальная потеря данных | 1 час (для логов) |
| **RTO (Recovery Time Objective)** | Время восстановления | 4 часа (для production) |

**Компоненты для бэкапа:**

| Компонент | Метод бэкапа | Частота | Важность |
| :--- | :--- | :--- | :--- |
| **S3/GCS (чанки + индекс)** | Встроенные mechanism хранилища | Непрерывно (версионирование) | Критично |
| **Helm values** | `helm get values` | Перед каждым изменением | Высокая |
| **Kubernetes манифесты** | `kubectl get -o yaml` | Перед каждым изменением | Высокая |
| **Конфигурация Loki** | Git | Непрерывно | Критично |
| **Grafana dashboards** | Grafana API / provisioning | Перед изменениями | Средняя |

**Стратегия 1: S3 Versioning (рекомендуется)**

```bash
# Включение versioning на S3 bucket (AWS)
aws s3api put-bucket-versioning \
  --bucket loki-data-chunks \
  --versioning-configuration Status=Enabled

# Проверка versioning
aws s3api get-bucket-versioning --bucket loki-data-chunks
# → Status: Enabled

# Восстановление удаленного объекта
aws s3api list-object-versions --bucket loki-data-chunks --prefix chunks/ --max-items 5
aws s3api get-object --bucket loki-data-chunks --key chunks/<path> --version-id <version-id> restored-chunk.gz
```

**Стратегия 2: Cross-Region Replication (CRR)**

```bash
# Настройка CRR между регионами (AWS)
aws s3api put-bucket-replication \
  --bucket loki-data-chunks \
  --replication-configuration '{
    "Role": "arn:aws:iam::ACCOUNT:role/S3ReplicationRole",
    "Rules": [
      {
        "Status": "Enabled",
        "Destination": {
          "Bucket": "arn:aws:s3:::loki-backup-us-west-2",
          "StorageClass": "STANDARD_IA"
        }
      }
    ]
  }'
```

**Стратегия 3: Velero для Kubernetes + S3**

```bash
# Установка Velero
velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.8.0 \
  --bucket loki-velero-backup \
  --secret-file ./credentials-velero \
  --backup-location-config region=us-east-1 \
  --snapshot-location-config region=us-east-1

# Бэкап namespace logging
velero backup create loki-backup-$(date +%Y%m%d) \
  --include-namespaces logging \
  --ttl 720h

# Восстановление
velero restore create --from-backup loki-backup-20240101
```

**Процедура восстановления (Disaster Recovery):**

```bash
# Шаг 1: Проверка повреждения
kubectl get pods -n logging
kubectl logs -n logging -l app.kubernetes.io/component=write --tail=100

# Шаг 2: Восстановление S3 (если bucket удален)
# Используйте versioning или CRR для восстановления из backup bucket
aws s3 sync s3://loki-backup-us-west-2 s3://loki-data-chunks

# Шаг 3: Восстановление Kubernetes ресурсов
kubectl apply -f logging-backup.yaml

# Шаг 4: Восстановление Loki через Helm
helm upgrade --install loki grafana-community/loki \
  --namespace logging \
  -f loki-values-backup.yaml \
  --wait --atomic

# Шаг 5: Валидация
curl -s http://loki-gateway:80/ready
curl -s "http://loki-gateway:80/loki/api/v1/query" \
  --data-urlencode "query=sum(count_over_time({job=~'.+'}[1h]))"

# Шаг 6: Восстановление Grafana dashboards
kubectl apply -f grafana-dashboards-backup.yaml
```

**Автоматический бэкап через CronJob (Kubernetes):**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: loki-backup
  namespace: logging
spec:
  schedule: "0 2 * * *"  # Ежедневно в 2:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: amazon/aws-cli:latest
              command:
                - /bin/sh
                - -c
                - |
                  aws s3 sync s3://loki-data-chunks s3://loki-backup-daily-$(date +%Y%m%d) \
                    --exclude "*.tmp" \
                    --exclude "*.wal"
                  echo "Backup completed: $(date)"
              env:
                - name: AWS_ACCESS_KEY_ID
                  valueFrom:
                    secretKeyRef:
                      name: loki-s3-credentials
                      key: access-key
                - name: AWS_SECRET_ACCESS_KEY
                  valueFrom:
                    secretKeyRef:
                      name: loki-s3-credentials
                      key: secret-key
          restartPolicy: OnFailure
```

### Сценарий 9: Миграция с Single Binary на Simple Scalable

При росте объемов логов может потребоваться переход от Single Binary к Simple Scalable.

**Шаг 1: Подготовка хранилища**
Убедитесь, что S3 бакеты созданы и доступны из кластера.

**Шаг 2: Установка Simple Scalable параллельно**
Установите новый релиз в отдельном namespace или с другим именем:

```bash
helm upgrade --install loki-ss grafana-community/loki \
  --namespace logging-ss \
  --create-namespace \
  -f loki_values_simple_scalable.yaml \
  --wait --atomic
```

**Шаг 3: Переключение агентов**
Обновите конфигурацию Alloy/Promtail для отправки логов в новый endpoint:

```river
loki.write "default" {
  endpoint {
    url = "http://loki-ss-gateway.logging-ss.svc.cluster.local/loki/api/v1/push"
    headers = {
      "X-Scope-OrgID" = "team-alpha",
    }
  }
}
```

**Шаг 4: Валидация и удаление старого релиза**
Убедитесь, что логи поступают и запрашиваются корректно, затем удалите Single Binary:

```bash
helm uninstall loki -n logging
```

### Сценарий 10: Локальная установка (Binary) на Linux

Минималистичный способ запуска Loki без использования контейнеров, подходящий для отладки или малых систем.

**1. Загрузка и подготовка бинарного файла:**

```bash
curl -O -L "https://github.com/grafana/loki/releases/download/v3.1.1/loki-linux-amd64.zip"
unzip loki-linux-amd64.zip
chmod +x loki-linux-amd64
```

**2. Конфигурация:**

```bash
wget https://raw.githubusercontent.com/grafana/loki/main/cmd/loki/loki-local-config.yaml
```

**Основные параметры в `loki-local-config.yaml`:**
*   **Порты:** `3100` (HTTP для API и метрик), `9096` (gRPC для взаимодействия компонентов).
*   **Хранилище:** По умолчанию используется локальная файловая система. Чанки логов сохраняются в `/tmp/loki/chunks`.

**3. Запуск:**

```bash
./loki-linux-amd64 -config.file=loki-local-config.yaml
```

**4. Верификация:**

```bash
curl http://localhost:3100/metrics
# → Ожидается вывод метрик в формате Prometheus
```

### Сценарий 11: Быстрый старт через Umbrella Chart (loki-stack)

Используется для быстрого развертывания полного стека (Loki + Prometheus + Grafana + Promtail) в демонстрационных или тестовых целях.

**1. Подготовка репозитория:**
```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

**2. Настройка `values.yaml`:**
```yaml
grafana:
  enabled: true
  image:
    tag: latest
promtail:
  enabled: true
```

**3. Установка:**
```bash
helm install loki-stack grafana/loki-stack --values custom-stack-values.yaml
```

**4. Доступ к Grafana:**
```bash
kubectl port-forward deployment/loki-stack-grafana 3000:3000
```

**5. Получение пароля администратора:**
```bash
kubectl get secret loki-stack-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

**Важно:** Чарт `loki-stack` является устаревшим зонтичным чартом. Для production используйте отдельные чарты `grafana-community/loki` и `grafana/alloy` для более гибкой настройки.

### Установка в кластер

```bash
# Рекомендуется использовать sops или helm-secrets для S3 ключей
helm upgrade --install loki grafana-community/loki \
  --namespace logging \
  --create-namespace \
  -f loki_values.yaml \
  --wait --atomic
```

### Проверка работоспособности

```bash
# Просмотр статуса всех компонентов
kubectl get pods -n logging -l app.kubernetes.io/name=loki

# Проверка логов записи (Distributor/Ingester)
kubectl logs -n logging -l app.kubernetes.io/component=write -f

# Проверка метрик (если включен ServiceMonitor)
kubectl get servicemonitor -n logging

# Проверка готовности
curl -s http://loki-gateway.logging.svc.cluster.local:80/ready
# → ready

# Проверка write path (отправка тестового лога)
curl -X POST "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/push" \
  -H "Content-Type: application/json" \
  -d '{"streams":[{"stream":{"job":"test"},"values":[["'$(date +%s)'000000000","test log entry"]]}]}'

# Проверка read path
curl -G -s "http://loki-gateway.logging.svc.cluster.local/loki/api/v1/query_range" \
  --data-urlencode 'query={job="test"}' \
  --data-urlencode 'start=now-1h' \
  --data-urlencode 'end=now'
# → Ожидается JSON с результатами запроса
```

### Диагностика типичных ошибок

| Ошибка | Возможная причина | Путь решения |
| :--- | :--- | :--- |
| **Pending Pods** | Недостаточно ресурсов или проблемы с PVC | Проверьте `kubectl describe pod`. Убедитесь, что StorageClass поддерживает динамическое выделение. |
| **401 Unauthorized** | Включен `auth_enabled`, но отсутствует заголовок | Добавьте `X-Scope-OrgID` в настройки агента и Grafana. |
| **Invalid Schema** | Версия схемы не соответствует версии Loki | Для Loki 3.x используйте `v13` и `store: tsdb`. |
| **High Ingestion Latency** | Недостаточно реплик `write` или медленный S3 | Увеличьте количество реплик `write`, проверьте лимиты CPU и сетевую задержку до S3. |
| **Bloom filter missing** | Bloom-фильтры не успели построиться | Построение фильтров происходит с задержкой. Настройте `bloom_build_config`. |
| **429 Too Many Requests** | Превышен `ingestion_rate_mb` или `ingestion_burst_size_mb` | Увеличьте лимиты в `limits_config`. Проверьте, нет ли burst-нагрузки от конкретного приложения. |
| **Query timeout** | Запрос выполняется слишком долго | Оптимизируйте LogQL (сначала фильтры по меткам), увеличьте `query_timeout`. |
| **Entry out of order** | Данные для одного стрима пришли с меткой времени раньше, чем уже записанные | Обеспечьте уникальность лейблов. Настройте `reject_old_samples: true`. |
| **Ошибка при подключении к S3** | Неверные credentials, endpoint или сетевые политики | Проверьте `s3:endpoint`, секреты и NetworkPolicy. Убедитесь, что VPC endpoint разрешает трафик. |
| **Логи не появляются в Loki** | Проблемы с сетью, неверные labels, отброс старых сэмплов | Проверьте endpoint, метрики агента, `reject_old_samples_max_age`. Убедитесь, что timestamp корректен. |

### Базовое масштабирование

**Горизонтальное масштабирование Write компонентов:**

```bash
helm upgrade loki grafana-community/loki \
  --namespace logging \
  -f loki_values.yaml \
  --set write.replicas=5
```

**Вертикальное масштабирование (изменение ресурсов):**

```bash
helm upgrade loki grafana-community/loki \
  --namespace logging \
  -f loki_values.yaml \
  --set read.resources.limits.memory=16Gi \
  --set read.resources.limits.cpu=8
```

**Проверка распределения нагрузки:**

```bash
# Проверка распределения streams по инжестерам
kubectl exec -n logging -it loki-write-0 -- curl -s http://localhost:3100/metrics | grep loki_ingester_streams

# Проверка балансировки
kubectl get pods -n logging -l app.kubernetes.io/component=write -o wide
```

### Полезные команды для эксплуатации

```bash
# Просмотр текущей конфигурации
helm get values loki -n logging

# Проверка состояния индекса через API
curl -G -H "X-Scope-OrgID: fake" http://localhost:3100/loki/api/v1/status/buildinfo

# Проверка текущих лимитов tenant'а
curl -s http://localhost:3100/loki/api/v1/limits | jq

# Просмотр статуса Bloom-фильтров
curl -s http://localhost:3100/loki/api/v1/bloom?query={job="my-app"}&start=now-1h&end=now | jq
```

## Дополнительная информация

### Ограничения и edge cases

1.  **Bloom-фильтры:** Имеют вероятность false positive (обычно < 1%). Для критичных сценариев, где требуется 100% точность, используйте фильтры как предварительный этап, а не единственный механизм.
2.  **Structured Metadata:** В текущей версии не поддерживается индексация structured metadata (только фильтрация). Для частых фильтров по высококардинальным полям рассмотрите использование отдельного stream с фильтрацией на уровне агента.
3.  **Max Query Length:** Запросы по слишком широкому временному диапазону (например, несколько лет) могут приводить к таймаутам. Ограничьте `max_query_length` в `limits_config`.
4.  **WAL Recovery:** При восстановлении из WAL после сбоя доставка логов может быть дублирована (at-least-once семантика). Убедитесь, что downstream системы обрабатывают дубликаты корректно.
5.  **Filesystem storage:** В Single Binary/Simple Scalable режимах filesystem не поддерживает горизонтальное масштабирование. Для > 100 ГБ/день используйте S3.
6.  **Режим Maintenance репозитория:** Репозиторий `grafana.github.io/helm-charts` переведен в режим обслуживания. Используйте `grafana-community.github.io/helm-charts` для всех новых развертываний.
7.  **Миграция с Promtail на Alloy:** Promtail имеет статус EOL (весна 2026). Планируйте миграцию на Alloy, который поддерживает те же самые функции сбора логов.

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Loki](../loki_overview.md) | Архитектура, принципы работы и сравнение с ELK |
| [Установка Grafana](grafana_installation.md) | Настройка источника данных и дашбордов |
| [Примеры LogQL](logql_examples.md) | Практическое руководство по языку запросов |
| [Установка Alloy](alloy_installation.md) | Настройка современного агента сбора логов |
| [Loki на Minikube](../../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_lgtm_stack_deployment.md) | Практическое руководство по развертыванию полного стека |
| [Документация по Bloom-фильтрам](https://grafana.com/docs/loki/latest/operations/bloom-filters/) | Детальная настройка ускорения запросов |
