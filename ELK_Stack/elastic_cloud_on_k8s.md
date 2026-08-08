# Elastic Cloud on Kubernetes (ECK)

## Определения

*   **Elastic Cloud on Kubernetes (ECK)** — официальный Kubernetes-оператор от Elastic, инкапсулирующий опыт компании по эксплуатации стека. Автоматизирует полный жизненный цикл: установку, обновление, масштабирование, резервное копирование и обеспечение безопасности.
*   **Custom Resource Definition (CRD)** — расширение API Kubernetes, позволяющее оператору управлять специфичными ресурсами, такими как `Elasticsearch`, `Kibana`, `Beat`, `Agent` и `RemoteCluster`.
*   **Reconciliation (Сверка)** — непрерывный цикл управления, в котором оператор приводит текущее состояние кластера (состояние подов, дисков, конфигов) к желаемому, описанному в YAML-манифестах.
*   **Wolfi-based (Distroless) Images** — современные, минималистичные и защищенные образы контейнеров (на базе Wolfi OS), используемые в ECK с 2025–2026 гг. для минимизации поверхности атаки и CVE.
*   **AutoOps** — интеллектуальная надстройка оператора (начиная с ECK 2.x/3.x), использующая метаданные производительности для автоматической оптимизации топологии шардов и ресурсов.

## Основные концепции

### Архитектура и безопасность (Стандарты 2026)

ECK реализует парадигму **Secure by Default**:
1.  **Сквозной mTLS**: Оператор автоматически управляет внутренним Certificate Authority (CA) и ротирует сертификаты для всех узлов. Трафик зашифрован всегда (Transport и HTTP слои).
2.  **Zero-Trust и API Keys**: В современных инсталляциях (8.17+/9.x) использование суперпользователя `elastic` считается устаревшим. Приоритет отдается **Service Tokens** и **API Keys** для всех интеграций.
3.  **Workload Identity**: Для доступа к облачным ресурсам (S3, GCS, Azure) ECK нативно поддерживает интеграцию с IAM-ролями (AWS IRSA, GCP Workload Identity), исключая хранение статических ключей (Access Keys) в секретах.
4.  **Supply Chain Security**: Все образы подписаны через **Sigstore Cosign**, что позволяет проверять целостность артефактов перед запуском.

### Управление ресурсами (CRDs)

| Ресурс | Описание и особенности 2026 года |
| :--- | :--- |
| **Elasticsearch** | Управление топологией через `nodeSets`. Поддержка Hot-Warm-Cold-Frozen архитектуры с использованием **Searchable Snapshots**. |
| **Kibana** | Интерфейс управления. Связь с кластером через `elasticsearchRef`. Автоматическая настройка SSO и RBAC. |
| **Agent / Beat** | Управление сбором данных. Рекомендуется использовать **Elastic Agent** в связке с Fleet для централизованного управления политиками. |
| **RemoteCluster** | Ресурс для настройки Cross-Cluster Search (CCS) и Replication (CCR) через API-ключи. |
| **ElasticsearchAutoscaler** | (Enterprise) Динамическое изменение CPU, RAM и Storage на основе метрик нагрузки от AutoOps. |

### Масштабирование и надежность

*   **NodeSets**: Логические группы узлов. Позволяют разделять master-узлы (минимум 3 для кворума) и data-узлы с разными типами дисков (NVMe для Hot, HDD для Cold).
*   **Pod Disruption Budgets (PDB)**: ECK автоматически создает PDB, гарантируя, что во время обновлений Kubernetes-кластера или плановых работ Elasticsearch всегда будет иметь достаточное количество доступных копий данных.
*   **Searchable Snapshots**: Позволяют хранить исторические данные (Frozen Tier) напрямую в S3/GCS, сохраняя возможность поиска по ним без восстановления на локальные диски.

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

## Дополнительная информация

### Тюнинг и эксплуатация

*   **JVM Heap**: ECK устанавливает Heap в 50% от лимита памяти. Рекомендуется задавать `requests == limits` для памяти контейнера, чтобы избежать OOMKill.
*   **Affinity**: Всегда настраивайте `podAntiAffinity` в `podTemplate`, чтобы узлы Elasticsearch распределялись по разным физическим хостам или зонам доступности.
*   **Обновления (Upgrades)**: Для обновления версии просто измените поле `version` в манифесте. ECK выполнит Rolling Update, предварительно проверив состояние здоровья шардов.

### Мониторинг и диагностика

*   **Логи оператора**: Если ресурс не переходит в состояние `Ready`, проверьте логи пода `elastic-operator` в неймспейсе `elastic-system`.
*   **События (Events)**: `kubectl describe elasticsearch <name>` — первый шаг при диагностике проблем со сверкой.
*   **AutoOps**: Включите агент AutoOps для получения проактивных рекомендаций по оптимизации индексов и запросов.

### Ссылки и ресурсы

*   **[Официальная документация ECK](https://www.elastic.co/guide/en/cloud-on-k8s/current/index.html)** — первоисточник по параметрам CRD.
*   **[Рекомендации по безопасности Elastic](https://www.elastic.co/guide/en/elasticsearch/reference/current/security-best-practices.html)**.
*   **[Обзор Elastic Stack](./elk_stack_overview.md)** — архитектура и возможности.
*   **[Kubernetes Operators](../Kubernetes/Concepts/kubernetes_operators.md)** — теория паттерна Operator.
