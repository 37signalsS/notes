# Elastic Cloud on Kubernetes (ECK)

**Актуально для:** ECK 2.16 / 3.x (актуальный релиз 3.5.0; Kubernetes 1.31–1.36, Elasticsearch/Kibana 8+/9+)

> Эта заметка — основной источник по эксплуатации Elastic Stack в Kubernetes с помощью оператора ECK. Для базовой теории паттерна «Оператор» см. [Kubernetes-операторы](../Kubernetes/Concepts/kubernetes_operators.md), для настройки логов — [Стек EFK в Kubernetes](../Kubernetes/MonitoringLogging/EFK/efk_stack_setup_guide.md).

## Определения

*   **Elastic Cloud on Kubernetes (ECK)** — официальный Kubernetes-оператор от Elastic, инкапсулирующий опыт компании по эксплуатации стека. Автоматизирует полный жизненный цикл: установку, обновление, масштабирование, резервное копирование и обеспечение безопасности.
*   **Custom Resource Definition (CRD)** — расширение API Kubernetes, позволяющее оператору управлять специфичными ресурсами: `Elasticsearch`, `Kibana`, `ApmServer`, `Beat`, `Agent`, `EnterpriseSearch`, `ElasticMapsServer`, `Logstash`, `StackConfigPolicy`, `ElasticsearchAutoscaler`, `AutoOpsAgentPolicy`, `PackageRegistry`.
*   **Reconciliation (Сверка)** — непрерывный цикл управления, в котором оператор приводит текущее состояние кластера (состояние подов, дисков, конфигов) к желаемому, описанному в YAML-манифестах.
*   **Wolfi-образы** — варианты контейнеров Elastic на базе Wolfi (Linux (un)distribution от Chainguard, предназначена для сборки минималистичных образов). Публикуются как альтернатива UBI-образам (теги `*-wolfi`): Elastic Maps Server — с 8.14/8.15 (для него — вариант по умолчанию), Elasticsearch — для линий 8.19.x и 9.x. Цель — уменьшить поверхность атаки и число CVE в базовом образе.
*   **AutoOps** — инструмент мониторинга и детекции проблем: анализ утилизации ресурсов, пути решения, рекомендации по производительности. В ECK 3.x управляется через CRD `AutoOpsAgentPolicy` (apiVersion `autoops.k8s.elastic.co/v1alpha1`); начиная с ECK 3.3.1 доступен без Enterprise-лицензии (версии агента: 9.2.1+ для Enterprise, 9.2.4+ для Basic).
*   **APM Server** — сервер сбора трассировок и метрик приложений, управляемый ECK через CRD `ApmServer` (apiVersion `apm.k8s.elastic.co/v1`). Автоматически связывается с кластером Elasticsearch через `elasticsearchRef`.
*   **Agent Policy** — конфигурация сбора данных, определяющая, какие интеграции (инпуты) активны на группе агентов. Управляется через Fleet или CRD `Agent` (apiVersion `agent.k8s.elastic.co/v1alpha1`).
*   **StackConfigPolicy** — ресурс ECK (apiVersion `stackconfigpolicy.k8s.elastic.co/v1alpha1`, GA с ECK 2.6.1 / ES 8.6.1) для централизованного управления настройками Elasticsearch и Kibana: cluster settings, snapshot-репозитории, SLM-политики, ingest-пайплайны, ILM-политики, шаблоны индексов, role mappings, secure settings. Настройки, применённые политикой, неизменяемы через REST API; на один кластер может быть назначена только одна политика.
*   **Sidecar Container** — контейнер, запускаемый в том же Pod'е с основным приложением. ECK не добавляет sidecar'ы в поды Elasticsearch автоматически; они задаются пользователем через `podTemplate` (например, для доставки логов или маршрутизации трафика).
*   **Remote Cluster** — внешний кластер Elasticsearch, к которому подключается локальный кластер для Cross-Cluster Search (CCS) и Replication (CCR). В ECK удалённые кластеры настраиваются через Elasticsearch API или Kibana, а не через отдельный CRD.
*   **Cross-cluster API key** — тип API key, позволяющий другим кластерам подключаться к данному для задач CCS/CCR; рекомендуемый способ аутентификации удалённых кластеров.

## Основные концепции

### Архитектура и безопасность

ECK реализует парадигму **Secure by Default**:

1.  **Сквозной mTLS**: Оператор автоматически управляет внутренним Certificate Authority (CA) и ротирует сертификаты для всех узлов (по умолчанию `ca-cert-validity: 8760h`, `ca-cert-rotate-before: 24h`). Трафик зашифрован всегда — и transport (9300), и HTTP (9200) слои.
2.  **Аутентификация интеграций**: для сервисов рекомендуются **service account tokens** (создаются через Create service account token API или CLI `elasticsearch-service-tokens`), для программного доступа — **API keys** (personal/user, cross-cluster, managed). Суперпользователь `elastic` — только для административных задач, не для повседневных интеграций. Service account tokens не применимы для обычных пользователей.
3.  **Подпись образов (Supply Chain Security)**: образы Elastic Stack подписаны через **Sigstore Cosign** начиная с 8.8.0 (май 2023). Проверка целостности перед запуском:
    ```bash
    cosign verify --key https://artifacts.elastic.co/cosign.pub \
      docker.elastic.co/elasticsearch/elasticsearch:8.19.23
    # → Verification for docker.elastic.co/elasticsearch/elasticsearch:8.19.23 --
    # → The following checks were performed on each of these signatures:
    # → - The cosign claims were validated
    # → - Existence of the claims in the transparency log was verified offline
    # → - The signatures were verified against the specified public key
    ```
4.  **Validating Webhook**: оператор валидирует манифесты CRD при создании и обновлении через `ValidatingWebhookConfiguration` `elastic-webhook.k8s.elastic.co` (порт 9443). Невалидный манифест отклоняется webhook'ом — это первая причина «зависания» ресурса в состоянии, отличном от `Ready`.
5.  **Network Policies**: ECK **не создаёт** `NetworkPolicy` автоматически и не предоставляет анносаций для интеграции с Calico/Cilium. Изоляцию трафика настраивайте вручную (см. сценарий 4).
6.  **Workload Identity**: для доступа к объектным хранилищам (S3, GCS, Azure) ECK поддерживает интеграцию с IAM-ролями (AWS IRSA, GCP Workload Identity), исключая хранение статических ключей (Access Keys) в секретах.

### Управление ресурсами (CRDs)

| Ресурс | apiVersion | Описание |
| :--- | :--- | :--- |
| **Elasticsearch** | `elasticsearch.k8s.elastic.co/v1` | Управление топологией через `nodeSets`. Поддержка Hot-Warm-Cold-Frozen архитектуры с использованием **Searchable Snapshots**. |
| **Kibana** | `kibana.k8s.elastic.co/v1` | Интерфейс управления. Связь с кластером через `elasticsearchRef`. SSO и RBAC настраиваются явно (в Kibana/Elasticsearch), оператор их не конфигурирует автоматически. |
| **ApmServer** | `apm.k8s.elastic.co/v1` | Сервер сбора трассировок. Автоматически создаёт Service и связывается с Elasticsearch. |
| **Beat / Agent** | `beat.k8s.elastic.co/v1beta1` / `agent.k8s.elastic.co/v1alpha1` | Управление сбором данных. Рекомендуется использовать **Elastic Agent** в связке с Fleet для централизованного управления политиками. |
| **EnterpriseSearch** | `enterprisesearch.k8s.elastic.co/v1` | Enterprise Search. |
| **ElasticMapsServer** | `maps.k8s.elastic.co/v1alpha1` | Elastic Maps Server (географические карты для Maps/Kibana). |
| **Logstash** | `logstash.k8s.elastic.co/v1alpha1` | Logstash (с 8.12+). Сценарий самостоятельного развёртывания без оператора и особенности очередей — в [Logstash: Production-эксплуатация](./Logstash/logstash_production.md#развертывание-в-kubernetes). |
| **StackConfigPolicy** | `stackconfigpolicy.k8s.elastic.co/v1alpha1` | Централизованное управление настройками стека (см. Определения). |
| **ElasticsearchAutoscaler** | `autoscaling.k8s.elastic.co/v1alpha1` | **(Enterprise)** Динамическое изменение числа узлов, CPU, RAM и Storage на основе рекомендаций Autoscaling API Elasticsearch. Оператор опрашивает API раз в минуту (интервал — поле `pollingPeriod`). |
| **AutoOpsAgentPolicy** | `autoops.k8s.elastic.co/v1alpha1` | Политика AutoOps (ECK 3.x; с 3.3.1 — без Enterprise-лицензии). |
| **PackageRegistry** | `packageregistry.k8s.elastic.co/v1alpha1` | Elastic Package Registry (хранилище интеграций Fleet). |

> **Важно:** CRD `RemoteCluster` в ECK **не существует**. CCS/CCR настраиваются через Elasticsearch API/Kibana (см. сценарий 3).

### Совместимость версий

| ECK | Kubernetes | Elasticsearch / Kibana / APM Server | Примечания |
| :--- | :--- | :--- | :--- |
| **2.16** | 1.27–1.32 | 6.8+, 7.1+, 8+ | последний релиз линейки 2.x; OpenShift 4.12–4.17 |
| **3.0–3.2** | 1.28–1.34 (по релизу) | 7.17+, 8+, 9+ | ECK 3.0.0 добавил поддержку ES 9.0.0 |
| **3.3** | 1.31–1.35 | 8+, 9+ | 7.17.X deprecated с 15.01.2026 |
| **3.4–3.5** (текущая) | 1.31–1.36 | 8+, 9+ | OpenShift 4.16–4.22; Helm 3.2.0+ |

> **Важно:** ECK 3.3+ не поддерживает Elasticsearch 7.17 (deprecated с 15 января 2026, будет удалён в будущем релизе). При миграции с 2.x на 3.x проверьте совместимость в [матрице поддержки Elastic](https://www.elastic.co/support/matrix#matrix_kubernetes). Полный список поддерживаемых версий — на странице [Supported versions](https://www.elastic.co/docs/deploy-manage/deploy/cloud-on-k8s).

### Ресурсы оператора

Оператор развёртывается как **StatefulSet** `elastic-operator` в неймспейсе `elastic-system` (образ `docker.elastic.co/eck/eck-operator:<version>`):

*   **Репликации**: по умолчанию **1 реплика** (`replicas: 1`). Leader election включён (`enable-leader-election: true`, Lease `elastic-operator-leader`), поэтому StatefulSet можно масштабировать до 2+ реплик для HA оператора — standby-пода по умолчанию нет.
*   **Ресурсы по умолчанию** (ECK 3.5.0):
    ```yaml
    resources:
      requests:
        cpu: 100m
        memory: 150Mi
      limits:
        cpu: 1
        memory: 1Gi
    ```
    На очень больших кластерах (сотни ресурсов) оператор может получить OOMKilled — увеличьте `memory` limit (см. раздел «Типичные проблемы»).
*   **Конфигурация** (ConfigMap `elastic-operator`, ключ `eck.yaml`): `max-concurrent-reconciles: 3`, `kube-client-timeout: 60s`, `elasticsearch-client-timeout: 180s`, `elasticsearch-observation-interval: 10s`, `validate-storage-class: true`, `exposed-node-labels: [topology.kubernetes.io/.*,failure-domain.beta.kubernetes.io/.*]`.

### Масштабирование и надежность

*   **NodeSets**: логические группы узлов; каждый NodeSet ECK превращает в **StatefulSet**. Разделяйте master-узлы (минимум 3 для кворума) и data-узлы с разными типами дисков (NVMe для Hot, HDD для Cold).
*   **Pod Disruption Budgets (PDB)**: ECK автоматически создаёт PDB для кластеров Elasticsearch, чтобы плановые работы (drain узлов, обновления Kubernetes) не нарушали доступность данных.
*   **Rolling Update**: обновление спецификации NodeSet (конфиг, ресурсы, версия) выполняется как rolling restart. **Обновление продвигается только при здоровье кластера `green`** — с исключениями: идёт обновление версии и часть подов не актуальна, нет initializing/relocating шардов, а под не хранит последнюю копию шарда.
*   **Удаление NodeSet**: при уменьшении `count` или удалении NodeSet ECK мигрирует данные с узлов, удаляет StatefulSet и автоматически удаляет PVC удалённых узлов.
*   **Searchable Snapshots**: позволяют хранить исторические данные (Frozen Tier) напрямую в объектном хранилище, сохраняя возможность поиска без восстановления на локальные диски.
*   **Topology Spread Constraints**: настраивайте `topologySpreadConstraints` для распределения подов Elasticsearch по зонам доступности (AZ) — критично для multi-AZ окружений.
*   **Pod Anti-Affinity**: минимум — `preferredDuringSchedulingIgnoredDuringExecution` с `topologyKey: kubernetes.io/hostname` для предотвращения запуска двух подов ES на одном узле.

### Storage Classes

ECK требует правильно настроенные Storage Classes для разных уровней данных. Оператор проверяет существование указанной StorageClass (`validate-storage-class: true` по умолчанию) и отклоняет манифест с несуществующим классом.

| Tier | Рекомендуемый Storage Class | Типичная задержка |
| :--- | :--- | :--- |
| **Hot** | `fast-nvme`, `premium-rwo` | < 1ms |
| **Warm** | `standard-rwo`, `gp3` | 1–5ms |
| **Cold** | `standard`, `cheap-hdd` | 5–20ms |
| **Frozen** | Object Storage (S3/GCS) | Зависит от сети |

> **Важно:** Не используйте `hostPath` для Production. Для локальной разработки рассмотрите `local-path-provisioner` (см. [Local Path Provisioner](../Kubernetes/Storage/local-path-provisioner.md)).

## Практические сценарии

### Предварительные требования

*   Kubernetes 1.31–1.36 (для ECK 3.4+) или версия из таблицы совместимости; Helm 3.2.0+ (при установке через Helm).
*   Права `cluster-admin` для установки оператора в cluster-wide режиме (CRD — cluster-scoped ресурсы).
*   Настроенные StorageClass'ы для используемых tiers данных.
*   Системные лимиты ОС на узлах Kubernetes: `vm.max_map_count` ≥ 262144 (рекомендуется 1048576) для mmapfs — иначе Elasticsearch не пройдёт Bootstrap Checks. Подробности — в [Настройка кластера Elasticsearch 8](./Tutorials/cluster_setup.md#системный-тюнинг-production-ready).
*   Отдельный namespace для рабочих нагрузок (не `elastic-system` и не `default`) — рекомендация Elastic.

### 0. Установка оператора ECK

Рекомендуемый способ (Helm, cluster-wide — CRD устанавливаются по умолчанию):

```bash
# Добавление репозитория
helm repo add elastic https://helm.elastic.co
helm repo update

# Установка оператора вместе с CRD (cluster-wide режим)
helm install elastic-operator elastic/eck-operator \
  --namespace elastic-system \
  --create-namespace
```

Альтернатива — YAML-манифесты:

```bash
kubectl create -f https://download.elastic.co/downloads/eck/3.5.0/crds.yaml
kubectl apply -f https://download.elastic.co/downloads/eck/3.5.0/operator.yaml
```

> **Restricted-режим** (несколько операторов в одном кластере): CRD ставятся отдельно (`helm install elastic-operator-crds elastic/eck-operator-crds`), а оператор — с `--set=installCRDs=false --set=managedNamespaces='{namespace-a,namespace-b}' --set=createClusterScopedResources=false --set=webhook.enabled=false`.

Проверка состояния (оператор — StatefulSet, поэтому под называется `elastic-operator-0`):

```bash
kubectl get pods -n elastic-system
# NAME                READY   STATUS    RESTARTS   AGE
# elastic-operator-0  1/1     Running   0          60s
```

### 1. Развертывание защищенного кластера (Hot-Warm)

Пример конфигурации с разделением уровней данных и TLS (TLS включён по умолчанию, дополнительных настроек не требуется):

```yaml
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: logs-cluster
  namespace: elastic-logs
spec:
  version: 8.19.23
  nodeSets:
  - name: masters
    count: 3
    config:
      node.roles: ["master"]
    podTemplate:
      spec:
        affinity:
          podAntiAffinity:
            preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    elasticsearch.k8s.elastic.co/statefulset-name: logs-cluster-masters
                topologyKey: kubernetes.io/hostname
  - name: hot
    count: 3
    config:
      node.roles: ["data_hot", "ingest"]
    volumeClaimTemplates:
    - metadata:
        name: elasticsearch-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: fast-nvme
        resources:
          requests:
            storage: 200Gi
    podTemplate:
      spec:
        containers:
        - name: elasticsearch
          resources:
            requests:
              memory: 8Gi
              cpu: 2
            limits:
              memory: 8Gi
              cpu: 2
  - name: warm
    count: 2
    config:
      node.roles: ["data_warm"]
    volumeClaimTemplates:
    - metadata:
        name: elasticsearch-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: standard-hdd
        resources:
          requests:
            storage: 1Ti
---
apiVersion: kibana.k8s.elastic.co/v1
kind: Kibana
metadata:
  name: kibana-main
  namespace: elastic-logs
spec:
  version: 8.19.23
  count: 1
  elasticsearchRef:
    name: logs-cluster
```

Валидация развёртывания:

```bash
# Статус ресурса: HEALTH должен быть green, PHASE — Ready
kubectl get elasticsearch -n elastic-logs
# NAME           HEALTH   NODES   VERSION    PHASE   AGE
# logs-cluster   green    8       8.19.23    Ready   5m

# Пароль встроенного пользователя elastic
kubectl get secret logs-cluster-es-elastic-user -n elastic-logs \
  -o go-template='{{.data.elastic | base64decode}}'

# Проверка здоровья кластера (предварительно: kubectl port-forward -n elastic-logs svc/logs-cluster-es 9200)
curl -k -u elastic:<password> https://localhost:9200/_cluster/health?pretty
# → "status" : "green"
```

> **Heap**: для Elasticsearch 7.11+ ECK автоматически рассчитывает JVM Heap как 50% от `limits.memory`. Поэтому `requests.memory` и `limits.memory` задавайте одинаковыми — иначе Pod будет вытесняться (OOMKilled) при росте heap. Для переопределения — переменная `ES_JAVA_OPTS` в `podTemplate`.

### 2. Резервное копирование в S3 (Workload Identity)

Настройка Snapshot Repository без использования секретных ключей (через IAM роль):

```yaml
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: logs-cluster
spec:
  nodeSets:
  - name: all-nodes
    podTemplate:
      metadata:
        annotations:
          # Аннотация для AWS IRSA (или аналоги для GCP/Azure)
          eks.amazonaws.com/role-arn: arn:aws:iam::1234567890:role/es-snapshot-role
    config:
      s3.client.default.endpoint: s3.amazonaws.com
# После создания кластера репозиторий настраивается через SLM в Kibana
```

После развертывания кластера создайте snapshot-репозиторий:

```bash
curl -X PUT "https://localhost:9200/_snapshot/s3_backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "my-es-backups",
      "region": "eu-west-1",
      "server_side_encryption": true
    }
  }'
```

> **Альтернатива без IAM**: репозиторий и SLM-политику можно задать декларативно через `StackConfigPolicy` (поля `snapshotRepositories` и `snapshotLifecyclePolicies`) — политика применяется оператором и неизменяема через API.

### 3. Подключение удалённых кластеров (CCS/CCR)

В ECK **нет CRD `RemoteCluster`**. Удалённые кластеры подключаются через Elasticsearch API или Kibana:

1.  **Настройка доверия**: на remote-кластере создайте **cross-cluster API key** (рекомендуемый способ аутентификации; TLS-сертификаты — deprecated). Начиная с Elastic Stack 9.3, API-key-аутентификация поддерживает дополнительную проверку strong identity.
2.  **Установка соединения**: в Kibana локального кластера (Stack Management → Remote Clusters) или через Elasticsearch API укажите `proxy_address` remote-кластера. В оркестрированных средах (ECK, ECE, Cloud Hosted) используется только **proxy mode** (подключение через reverse proxy / load balancer) — sniff mode неприменим, потому что publish-адреса узлов в контейнерах обычно недоступны напрямую.
3.  **Порт**: для API-key-аутентификации remote-кластер слушает порт **9443** по умолчанию — укажите его в правилах файрвола/NetworkPolicy.

```bash
# Пример: создание cross-cluster API key на remote-кластере
curl -X POST "https://<remote-host>:9200/_security/api_key" \
  -H 'Content-Type: application/json' -u elastic:<password> \
  -d '{"name": "ccs-key", "role_descriptors": {"remote": {"cluster": ["manage_api_key"], "indices": [{"names": ["logs-*"], "privileges": ["read"]}]}}}'
```

Детальные инструкции для ECK — в документации [Remote clusters on Elastic Cloud on Kubernetes](https://www.elastic.co/docs/deploy-manage/remote-clusters/eck-remote-clusters).

### 4. Network Policies для изоляции Elasticsearch

Рекомендуется ограничить трафик к Elasticsearch только авторизованными подами. ECK не создаёт политики автоматически — пример ручной настройки:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: elasticsearch-allow-only-authorized
  namespace: elastic-logs
spec:
  podSelector:
    matchLabels:
      elasticsearch.k8s.elastic.co/cluster-name: logs-cluster
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Разрешить трафик от Kibana к HTTP-интерфейсу ES
  - from:
    - podSelector:
        matchLabels:
          kibana.k8s.elastic.co/name: kibana-main
    ports:
    - port: 9200
      protocol: TCP
  # Разрешить трафик от APM Server и Beats/Agent к ES (данные идут на 9200, не на 8200)
  - from:
    - podSelector:
        matchLabels:
          apm.k8s.elastic.co/name: apm-server
    ports:
    - port: 9200
      protocol: TCP
  # Разрешить внутренний транспортный трафик (межузловой)
  - from:
    - podSelector:
        matchLabels:
          elasticsearch.k8s.elastic.co/cluster-name: logs-cluster
    ports:
    - port: 9300
      protocol: TCP
  egress:
  # Разрешить DNS
  - to:
    - namespaceSelector: {}
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  # Разрешить доступ к S3 (для snapshots); сузьте CIDR до endpoint'а хранилища
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - port: 443
      protocol: TCP
```

### 5. Backup и восстановление с Velero

Для полного бэкапа кластера Elasticsearch (включая данные и конфигурацию):

```bash
# Установка Velero (версию плагина выбирайте совместимой с вашей версией Velero)
velero install \
  --provider aws \
  --bucket my-es-backups \
  --secret-file ./credentials-velero \
  --plugins velero/velero-plugin-for-aws:v1.16.0

# Создание снимка (включая PVC)
velero backup create es-cluster-backup \
  --selector elasticsearch.k8s.elastic.co/cluster-name=logs-cluster \
  --include-cluster-resources=true \
  --wait

# Восстановление
velero restore create --from-backup es-cluster-backup
```

> **Важно:** Velero не гарантирует целостность данных при восстановлении running-кластера. Остановите запись данных перед восстановлением или используйте встроенный Snapshot API Elasticsearch.

### 6. Миграция с Helm на ECK

Если текущий кластер развернут через Helm-чарты:

1.  **Экспорт данных** через Snapshot API:
    ```bash
    curl -X PUT "https://localhost:9200/_snapshot/helm-backup/snapshot-pre-migration?wait_for_completion=true"
    ```

2.  **Установите ECK** и создайте манифест Elasticsearch:
    ```yaml
    apiVersion: elasticsearch.k8s.elastic.co/v1
    kind: Elasticsearch
    metadata:
      name: logs-cluster
    spec:
      version: 8.19.23
      nodeSets:
      - name: default
        count: 3
        config:
          # Только для quickstart/разработки: отключает mmapfs.
          # Для production не рекомендуется — оставьте mmapfs (быстрее) и настройте vm.max_map_count на узлах.
          node.store.allow_mmap: false
    ```

3.  **Восстановите данные** из снапшота:
    ```bash
    curl -X POST "https://localhost:9200/_snapshot/helm-backup/snapshot-pre-migration/_restore"
    ```

4.  **Переключите DNS** на новые сервисы, созданные ECK.

### 7. Управление сверкой (reconciliation)

Полезные аннотации для эксплуатации:

```bash
# Приостановить spec-driven оркестрацию (ECK 3.5.0+): сертификаты, сервисы,
# пользователи и health-мониторинг продолжают работать — безопасно при drain узлов
kubectl annotate elasticsearch logs-cluster eck.k8s.elastic.co/pause-orchestration=true

# Старая аннотация eck.k8s.elastic.co/managed="false" deprecated (останавливает ВСЮ сверку)

# Увеличить таймаут клиента ES для медленных кластеров (по умолчанию 180s)
kubectl annotate elasticsearch logs-cluster eck.k8s.elastic.co/es-client-timeout=60s
```

## Мониторинг и диагностика

### Встроенные инструменты

*   **Логи оператора**: если ресурс не переходит в состояние `Ready`, проверяйте логи StatefulSet оператора:
    ```bash
    kubectl -n elastic-system logs -f statefulset.apps/elastic-operator
    ```
    Логи INFO дают представление о ходе сверки; ERROR — о проблемах. Ошибки `conflict` из-за optimistic locking можно игнорировать: обновление применится на следующей итерации сверки.
*   **Init-контейнеры**: под Elasticsearch запускает init-контейнеры для подготовки файловой системы; если под в `Error`/`CrashLoopBackOff`, смотрите статусы и логи init-контейнеров первыми.
*   **События (Events)**: `kubectl describe elasticsearch <name>` — первый шаг при диагностике проблем со сверкой:
    ```bash
    kubectl describe elasticsearch logs-cluster -n elastic-logs
    kubectl get events -n elastic-logs --sort-by=.lastTimestamp
    ```
*   **Состояние кластера**:
    ```bash
    kubectl get elasticsearch -A
    # NAME             HEALTH   NODES   VERSION    PHASE   AGE
    # logs-cluster     green    8       8.19.23    Ready   30d
    ```

### Статус и условия

ECK публикует статус ресурса в `.status`: сводную фазу (`.status.phase`, например `Ready`) и набор условий (`.status.conditions`), отражающих готовность кластера и ход сверки с желаемым состоянием:

```bash
kubectl get elasticsearch logs-cluster -o json | jq '.status | {phase, conditions}'
```

Точный набор типов условий зависит от версии ECK — сверяйтесь с выводом команды для вашего релиза.

### Prometheus метрики

**Метрики оператора выключены по умолчанию** (`metrics-port: 0` в ConfigMap). Включение:

*   **Helm**: `--set config.metrics.port=8080` (или `config.metrics.port: "8080"` в values-файле).
*   **Манифесты**: в ConfigMap `elastic-system/elastic-operator` задайте `metrics-port: 8080`, добавьте порт `metrics` (8080) в контейнер `manager` StatefulSet и пересоздайте оператора.

> Начиная с ECK 3.0.0 endpoint метрик **защищён по умолчанию** (TLS + RBAC); в ECK 2.16 и ниже он не защищён — при включении на старых версиях ограничьте доступ к нему.

Для Prometheus Operator официально рекомендуется **PodMonitor** (оператор — StatefulSet без Service для метрик):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: elastic-operator
  namespace: elastic-system
  labels:
    control-plane: elastic-operator
    app.kubernetes.io/component: metrics
spec:
  podMetricsEndpoints:
  - port: metrics
    path: /metrics
    interval: 1m
    scrapeTimeout: 30s
  namespaceSelector:
    matchNames:
    - elastic-system
  selector:
    matchLabels:
      control-plane: elastic-operator
```

Оператор построен на controller-runtime и экспортирует стандартные метрики: `controller_runtime_reconcile_total`, `controller_runtime_reconcile_errors_total`, `controller_runtime_reconcile_time_seconds`. Для метрик статуса CRD (здоровье, версия) используйте сторонний [eck-exporter](https://artifacthub.io/packages/helm/enix/eck-exporter) (метрики `eck_elasticsearch_info`, `eck_elasticsearch_health`).

### Типичные проблемы и решения

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Кластер не переходит в `Ready` | Недостаточно ресурсов (CPU/RAM) или webhook отклонил манифест | `kubectl describe pod`, ResourceQuota; логи оператора — причина отказа webhook |
| `Yellow` статус долгое время | Replica shards не назначены | Добавьте узлы или уменьшите `number_of_replicas` |
| Под Pending | Нет подходящей StorageClass или недостаточно capacity на узлах | Создайте StorageClass, проверьте `kubectl describe pod` (событие Unschedulable) |
| Под Pending после drain узла | PDB/MaxUnavailable не позволяют эвакуировать под | Дождитесь завершения плановых работ или временно снизьте ограничения |
| OOMKill подов ES | JVM Heap > лимита памяти | Установите `requests.memory == limits.memory` (Heap = 50% от limit) |
| OOMKilled оператора | Очень большой кластер (сотни ресурсов) | Увеличьте `memory` limit оператора выше дефолтных 1Gi |
| Rolling update застрял | Здоровье кластера не `green` | Дождитесь `green` (ECK обновляет узлы только при green, с исключениями) |
| Ошибки TLS | Несовпадение сертификатов | Проверьте CA через `kubectl get secret` |
| Operator CrashLoop | Невалидный YAML в CRD | Проверьте логи оператора, исправьте манифест |
| Поды не распределяются по AZ | Отсутствует `topologySpreadConstraints` | Добавьте `topologySpreadConstraints` с `topologyKey: topology.kubernetes.io/zone` |

## Граничные случаи и ограничения

### Производительность

*   **Кворум master-узлов**: минимум 3 master-eligible узла для отказоустойчивости. При 2 узлах потеря одного узла лишает кластер кворума (split-brain).
*   **Размер и число шардов** (рекомендации Elastic для 8.3+): шарды **10–50 ГБ**, менее 200 млн документов на шард; на master-узлах — менее **3000 индексов на 1 ГБ heap**; запас ~1 КБ heap на каждое mapped-поле индекса. Старое правило «20 шардов на 1 ГБ heap» deprecated с 8.3 — пер-shard overhead значительно снизился.
*   **JVM Heap**: ECK автоматически устанавливает Heap в 50% от лимита памяти. Для production-сред рекомендуется Heap ≤ 31 GiB (сжатые указатели объектов).

### Обновления

*   **Elasticsearch**: измените поле `version` в манифесте — ECK выполнит Rolling Update. **Понижение версии не поддерживается**; убедитесь, что новая версия совместима с данными (индексы 6.x и старше требуют reindex).
*   **Оператор**: обновляйте через Helm (Helm 3 повторно использует values предыдущего релиза по умолчанию):
    ```bash
    helm upgrade elastic-operator elastic/eck-operator \
      --namespace elastic-system
    ```
    Перед обновлением оператора рекомендуется приостановить сверку всех ресурсов (аннотация `eck.k8s.elastic.co/pause-orchestration=true`, массовое добавление/удаление — скриптом `hack/annotator` из репозитория ECK).
*   **Rolling restart при обновлении оператора**: ECK 3.4.0+ изменяет spec подов Elasticsearch и Kibana, поэтому обновление оператора триггерит rolling restart этих подов (Kibana: дефолтный memory limit вырос с 1Gi до 2Gi — при лимите ниже 2Gi Kibana 9.4+ может падать с OOM).
*   **Версионные ограничения**: ECK 3.0.0 добавил поддержку Elasticsearch 9.0.0; 7.17.X deprecated с 15.01.2026. Актуальные сочетания версий — в таблице совместимости выше.

### Multi-Tenancy

Для изоляции данных между командами/проектами используйте:
*   **Отдельные кластеры**: каждый проект — свой `Elasticsearch` ресурс в разных namespace.
*   **ILM и индексные паттерны**: разные политики ротации для разных команд.
*   **RBAC**: настройте роли в Kibana для ограничения доступа к индексам.

## Рекомендации

*   **Перед любыми структурными изменениями** (обновление версии, удаление NodeSet, миграция) делайте snapshot в объектное хранилище.
*   **Heap = limit**: всегда задавайте `requests.memory == limits.memory` для подов Elasticsearch — иначе Pod вытесняется при росте JVM Heap.
*   **Проверяйте подписи образов** (`cosign verify`) в средах с требованиями supply-chain безопасности.
*   **Изоляция**: настраивайте `NetworkPolicy` вручную (ECK их не создаёт) и ограничивайте egress до конкретных endpoint'ов snapshot-хранилищ.
*   **Наблюдаемость оператора**: включите endpoint метрик и алерт на `controller_runtime_reconcile_errors_total` — рост ошибок сверки предшествует расхождению состояния.
*   **Откат изменений**: для ресурсов ECK — верните предыдущую версию манифеста (`kubectl apply`); для оператора — `helm rollback elastic-operator <revision> -n elastic-system`. При удалении ресурса `Elasticsearch` оператор удаляет созданные StatefulSet и поды — данные на PVC не являются бэкапом, используйте snapshot.

## Ссылки и взаимосвязи

### Компоненты стека

*   **[Обзор Elastic Stack](./elk_stack_overview.md)** — архитектура и возможности.
*   **[Elasticsearch: Обзор](./Elasticsearch/elasticsearch_overview.md)** — архитектура кластера, шардинг, ILM.
*   **[Kibana: Обзор](./Kibana/kibana_overview.md)** — интерфейс управления, визуализация.

### Kubernetes

*   **[Kubernetes-операторы](../Kubernetes/Concepts/kubernetes_operators.md)** — теория паттерна Operator.
*   **[Headless Service](../Kubernetes/Networking/Service/service_type_headless.md)** — сетевая идентификация для StatefulSet.
*   **[StatefulSet: Обзор](../Kubernetes/Base/StatefulSet/statefulset_overview.md)** — управление stateful-приложениями.
*   **[Affinity, Anti-Affinity](../Kubernetes/Scheduling/affinity.md)** — управление размещением подов.
*   **[Local Path Provisioner](../Kubernetes/Storage/local-path-provisioner.md)** — для локальной разработки.

### Стек EFK

*   **[Стек EFK в Kubernetes](../Kubernetes/MonitoringLogging/EFK/efk_stack_setup_guide.md)** — развертывание Elasticsearch + Fluent Bit + Kibana.
*   **[Устранение неполадок EFK](../Kubernetes/MonitoringLogging/EFK/efk_stack_troubleshooting.md)** — диагностика проблем с логами.

### Инфраструктура

*   **[Настройка кластера Elasticsearch 8](./Tutorials/cluster_setup.md)** — self-managed развертывание, системный тюнинг.
*   **[Docker Compose: Развертывание ELK](./Tutorials/practical_setup_with_docker.md)** — локальная среда разработки.
*   **[Velero: Обзор](../Kubernetes/ToolsUtilities/velero-overview.md)** — бэкап и восстановление в Kubernetes.

### Полезные ссылки

*   **[Официальная документация ECK](https://www.elastic.co/docs/deploy-manage/deploy/cloud-on-k8s)** — первоисточник по параметрам CRD.
*   **[Release notes ECK](https://www.elastic.co/docs/release-notes/cloud-on-k8s)** — breaking changes и deprecations по релизам.
*   **[Матрица поддержки Elastic](https://www.elastic.co/support/matrix#matrix_kubernetes)** — актуальные сочетания версий K8s и Elastic Stack.
*   **[Рекомендации по безопасности Elastic](https://www.elastic.co/docs/deploy-manage/security)**.
*   **[Elastic Cloud on Kubernetes GitHub](https://github.com/elastic/cloud-on-k8s)** — исходный код, samples и проблемы.
