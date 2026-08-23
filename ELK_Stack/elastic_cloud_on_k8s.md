# Elastic Cloud on Kubernetes (ECK)

> Эта заметка является авторитетным источником (SSoT) по эксплуатации Elastic Stack в Kubernetes с помощью оператора ECK. Для базовой теории паттерна «Оператор» см. [Kubernetes-операторы](../Kubernetes/Concepts/kubernetes_operators.md), для настройки логов — [Стек EFK в Kubernetes](../Kubernetes/MonitoringLogging/EFK/efk_stack_setup_guide.md).

## Определения

*   **Elastic Cloud on Kubernetes (ECK)** — официальный Kubernetes-оператор от Elastic, инкапсулирующий опыт компании по эксплуатации стека. Автоматизирует полный жизненный цикл: установку, обновление, масштабирование, резервное копирование и обеспечение безопасности.
*   **Custom Resource Definition (CRD)** — расширение API Kubernetes, позволяющее оператору управлять специфичными ресурсами, такими как `Elasticsearch`, `Kibana`, `Beat`, `Agent` и `RemoteCluster`.
*   **Reconciliation (Сверка)** — непрерывный цикл управления, в котором оператор приводит текущее состояние кластера (состояние подов, дисков, конфигов) к желаемому, описанному в YAML-манифестах.
*   **Wolfi-based (Distroless) Images** — современные, минималистичные и защищенные образы контейнеров (на базе Wolfi OS), используемые в ECK с 2025–2026 гг. для минимизации поверхности атаки и CVE.
*   **AutoOps** — интеллектуальная надстройка оператора (начиная с ECK 2.x/3.x), использующая метаданные производительности для автоматической оптимизации топологии шардов и ресурсов.
*   **APM Server** — сервер сбора трассировок и метрик приложений, управляемый ECK через CRD `APM`. Автоматически связывается с кластером Elasticsearch через `elasticsearchRef`.
*   **Agent Policy** — конфигурация сбора данных, определяющая какие интеграции (инпуты) активны на группе агентов. Управляется через Fleet или CRD `Agent`.
*   **Stack Config Policy** — ресурс ECK (Enterprise) для централизованного управления настройками Elasticsearch, Kibana и Beat через единый YAML-манифест. Обеспечивает консистентность конфигураций между окружениями.
*   **Sidecar Container** — контейнер, запускаемый в том же Pod'е с основным приложением. В ECK используется для сбора логов оператора и маршрутизации трафика.

## Основные концепции

### Архитектура и безопасность (Стандарты 2026)

ECK реализует парадигму **Secure by Default**:
1.  **Сквозной mTLS**: Оператор автоматически управляет внутренним Certificate Authority (CA) и ротирует сертификаты для всех узлов. Трафик зашифрован всегда (Transport и HTTP слои).
2.  **Zero-Trust и API Keys**: В современных инсталляциях (8.17+/9.x) использование суперпользователя `elastic` считается устаревшим. Приоритет отдается **Service Tokens** и **API Keys** для всех интеграций.
3.  **Workload Identity**: Для доступа к облачным ресурсам (S3, GCS, Azure) ECK нативно поддерживает интеграцию с IAM-ролями (AWS IRSA, GCP Workload Identity), исключая хранение статических ключей (Access Keys) в секретах.
4.  **Supply Chain Security**: Все образы подписаны через **Sigstore Cosign**, что позволяет проверять целостность артефактов перед запуском.
5.  **Network Policies**: Рекомендуется ограничивать трафик между подами Elasticsearch, Kibana и агентами с помощью `NetworkPolicy`. ECK не создает их автоматически, но предоставляет аннотации для интеграции с Calico/Cilium.

### Управление ресурсами (CRDs)

| Ресурс | Описание и особенности 2026 года |
| :--- | :--- |
| **Elasticsearch** | Управление топологией через `nodeSets`. Поддержка Hot-Warm-Cold-Frozen архитектуры с использованием **Searchable Snapshots**. |
| **Kibana** | Интерфейс управления. Связь с кластером через `elasticsearchRef`. Автоматическая настройка SSO и RBAC. |
| **APM** | Сервер сбора трассировок. Автоматически создает Service и связывается с Elasticsearch. |
| **Agent / Beat** | Управление сбором данных. Рекомендуется использовать **Elastic Agent** в связке с Fleet для централизованного управления политиками. |
| **RemoteCluster** | Ресурс для настройки Cross-Cluster Search (CCS) и Replication (CCR) через API-ключи. |
| **Stack Config Policy** | (Enterprise) Централизованное управление настройками стека. |
| **ElasticsearchAutoscaler** | (Enterprise) Динамическое изменение CPU, RAM и Storage на основе метрик нагрузки от AutoOps. |

### Совместимость версий

| ECK Версия | Поддерживаемые версии ES/Kibana | Минимальная версия K8s |
| :--- | :--- | :--- |
| **2.x** | 7.17+, 8.x | 1.21+ |
| **3.x** (2026) | 8.17+, 9.x | 1.25+ |

> **Важно:** ECK 3.x не поддерживает версии Elasticsearch младше 8.17. При миграции с 2.x на 3.x обновите сначала Elasticsearch до 8.17+, затем оператор.

### Ресурсы оператора

По умолчанию оператор потребляет:
*   **CPU**: 100m–500m (в зависимости от количества управляемых кластеров)
*   **RAM**: 256Mi–1Gi
*   **Pods**: Один основной + один standby (для HA через Leader Election)

Для кластеров с >10 управляемыми ресурсами рекомендуется увеличить лимиты:
```yaml
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: "1"
    memory: 1Gi
```

### Масштабирование и надежность

*   **NodeSets**: Логические группы узлов. Позволяют разделять master-узлы (минимум 3 для кворума) и data-узлы с разными типами дисков (NVMe для Hot, HDD для Cold).
*   **Pod Disruption Budgets (PDB)**: ECK автоматически создает PDB, гарантируя, что во время обновлений Kubernetes-кластера или плановых работ Elasticsearch всегда будет иметь достаточное количество доступных копий данных.
*   **Searchable Snapshots**: Позволяют хранить исторические данные (Frozen Tier) напрямую в S3/GCS, сохраняя возможность поиска по ним без восстановления на локальные диски.
*   **Topology Spread Constraints**: Рекомендуется настраивать `topologySpreadConstraints` для распределения подов Elasticsearch по зонам доступности (AZ). Это критично для кластеров, работающих в multi-AZ окружениях.
*   **Pod Anti-Affinity**: Минимум — `preferredDuringSchedulingIgnoredDuringExecution` с `topologyKey: kubernetes.io/hostname` для предотвращения запуска двух подов ES на одном узле.

### Storage Classes

ECK требует правильно настроенные Storage Classes для different tiers:

| Tier | Рекомендуемый Storage Class | Типичная задержка |
| :--- | :--- | :--- |
| **Hot** | `fast-nvme`, `premium-rwo` | < 1ms |
| **Warm** | `standard-rwo`, `gp3` | 1–5ms |
| **Cold** | `standard`, `cheap-hdd` | 5–20ms |
| **Frozen** | Object Storage (S3/GCS) | Зависит от сети |

> **Важно:** Не используйте `hostPath` для Production. Для локальной разработки рассмотрите `local-path-provisioner` (см. [Local Path Provisioner](../Kubernetes/Storage/local-path-provisioner.md)).

## Практические сценарии

### 0. Установка оператора ECK

Рекомендуемый способ (Helm):

```bash
# Добавление репозитория
helm repo add elastic https://helm.elastic.co
helm repo update

# Установка оператора (включая CRD)
helm install elastic-operator elastic/eck-operator \
  --namespace elastic-system \
  --create-namespace \
  --set installCRDs=true
```

Проверка состояния:
```bash
kubectl get pods -n elastic-system
# NAME                                         READY   STATUS    RESTARTS   AGE
# elastic-operator-0                           1/1     Running   0          60s
```

### 1. Развертывание защищенного кластера (Hot-Warm)

Пример конфигурации с разделением уровней данных и TLS:

```yaml
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: logs-cluster
spec:
  version: 8.17.0
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
spec:
  version: 8.17.0
  count: 1
  elasticsearchRef:
    name: logs-cluster
```

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

После развертывания кластера создайте.snapshot repository:
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

### 3. Связывание удаленных кластеров (CCS/CCR)

Использование API-ключей для подключения удаленного кластера (Remote Cluster) на порту `9443`:

```yaml
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: RemoteCluster
metadata:
  name: remote-connection
spec:
  elasticsearchRef:
    name: logs-cluster # Локальный кластер
  remoteElasticsearchRef:
    endpoint: "remote-es.example.com:9443"
    # Оператор автоматически создаст API-ключ для связи, если 
    # удаленный кластер также под управлением ECK
```

### 4. Network Policies для изоляции Elasticsearch

Рекомендуется ограничить трафик к Elasticsearch только авторизованными подами:

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
  # Разрешить трафик от Kibana
  - from:
    - podSelector:
        matchLabels:
          kibana.k8s.elastic.co/name: kibana-main
    ports:
    - port: 9200
      protocol: TCP
  # Разрешить трафик от APM Server
  - from:
    - podSelector:
        matchLabels:
          apm.k8s.elastic.co/name: apm-server
    ports:
    - port: 8200
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
  # Разрешить доступ к S3 (для snapshots)
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
# Установка Velero
velero install \
  --provider aws \
  --bucket my-es-backups \
  --secret-file ./credentials-velero \
  --plugins velero/velero-plugin-for-aws:v1.8.0

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
      version: 8.17.0
      nodeSets:
      - name: default
        count: 3
        config:
          node.store.allow_mmap: false
    ```

3.  **Восстановите данные** из снимка:
    ```bash
    curl -X POST "https://localhost:9200/_snapshot/helm-backup/snapshot-pre-migration/_restore"
    ```

4.  **Переключите DNS** на новые сервисы, созданные ECK.

## Мониторинг и диагностика

### Встроенные инструменты

*   **Логи оператора**: Если ресурс не переходит в состояние `Ready`, проверьте логи пода `elastic-operator` в неймспейсе `elastic-system`:
    ```bash
    kubectl logs -n elastic-system elastic-operator-0 -f
    ```
*   **События (Events)**: `kubectl describe elasticsearch <name>` — первый шаг при диагностике проблем со сверкой:
    ```bash
    kubectl describe elasticsearch logs-cluster -n elastic-logs
    ```
*   **Состояние кластера**:
    ```bash
    kubectl get elasticsearch -A
    # NAME             HEALTH   NODES   VERSION   PHASE   AGE
    # logs-cluster     green    6       8.17.0    Ready   30d
    ```

### Условия (Conditions)

ECK предоставляет детальные условия в `.status.conditions`:

```bash
kubectl get elasticsearch logs-cluster -o jsonpath='{.status.conditions[*]}' | jq .
```

| Condition Type | Описание |
| :--- | :--- |
| **Ready** | Кластер полностью готов к работе |
| **Reconciling** | Оператор выполняет изменения |
| **PendingVersionUpgrade** | Ожидается обновление версии |
| **ResourcesError** | Недостаточно ресурсов для размещения подов |

### Prometheus метрики

Оператор экспортирует метрики для мониторинга:

```yaml
# ServiceMonitor для Prometheus Operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: eck-operator
  namespace: elastic-system
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      control-plane: elastic-operator
  endpoints:
  - port: metrics
    interval: 30s
```

Ключевые метрики:
*   `eck_operator_reconciliations_total` — количество циклов сверки
*   `eck_operator_reconciliations_errors_total` — ошибки сверки
*   `eck_operator_resources_created_total` — созданные ресурсы

### Типичные проблемы и решения

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Кластер не переходит в `Ready` | Недостаточно ресурсов (CPU/RAM) | Проверьте `kubectl describe pod` и ResourceQuota |
| `Yellow` статус长期 | Replica shards не назначены | Добавьте узлы или уменьшите `number_of_replicas` |
| Под Pending | Нет подходящей StorageClass | Создайте StorageClass или измените `volumeClaimTemplates` |
| OOMKill подов ES | JVM Heap > лимита памяти | Установите `requests.memory == limits.memory` |
| Ошибки TLS | Несовпадение сертификатов | Проверьте CA через `kubectl get secret` |
| Operator CrashLoop | Невалидный YAML в CRD | Проверьте логи оператора, исправьте манифест |
| Поды не распределяются по AZ | Отсутствует `topologySpreadConstraints` | Добавьте `topologySpreadConstraints` с `topologyKey: topology.kubernetes.io/zone` |

## Граничные случаи и ограничения

### Производительность

*   **Кворум master-узлов**: Минимум 3 узла для отказоустойчивости. При 2 узлах кворум невозможен (split-brain).
*   **Количество шардов**: На узел не более 20 shard'ов (рекомендация Elastic). Избегайте "шардового шторма" при большом количестве индексов.
*   **JVM Heap**: ECK автоматически устанавливает Heap в 50% от лимита памяти. Для生产-сред рекомендуется Heap ≤ 31 GiB (для компрессии pointers).

### Обновления

*   **Elasticsearch**: Измените поле `version` в манифесте. ECK выполнит Rolling Update.
*   **Оператор**: Обновляйте через Helm:
    ```bash
    helm upgrade elastic-operator elastic/eck-operator \
      --namespace elastic-system \
      --reuse-values
    ```
*   **Версионные ограничения**: ECK не позволяет понижать версию Elasticsearch. Убедитесь, что новая версия совместима с вашими данными.

### Multi-Tenancy

Для изоляции данных между командами/проектами используйте:
*   **Отдельные кластеры**: Каждый проект — свой `Elasticsearch` ресурс в不同的 namespace.
*   **ILM и индексные паттерны**: Разные политики ротации для разных команд.
*   **RBAC**: Настройте роли в Kibana для ограничения доступа к индексам.

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

*   **[Настройка кластера Elasticsearch 8](./Tutorials/cluster_setup.md)** — self-managed развертывание.
*   **[Docker Compose: Развертывание ELK](./Tutorials/practical_setup_with_docker.md)** — локальная среда разработки.
*   **[Velero: Обзор](../Kubernetes/ToolsUtilities/velero-overview.md)** — бэкап и восстановление в Kubernetes.

### Полезные ссылки

*   **[Официальная документация ECK](https://www.elastic.co/guide/en/cloud-on-k8s/current/index.html)** — первоисточник по параметрам CRD.
*   **[Рекомендации по безопасности Elastic](https://www.elastic.co/guide/en/elasticsearch/reference/current/security-best-practices.html)**.
*   **[Elastic Cloud on Kubernetes GitHub](https://github.com/elastic/cloud-on-k8s)** — исходный код и проблемы.
