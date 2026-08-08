# OpenSearch: Развертывание в Kubernetes с помощью Helm

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и детально рассматривает процесс развертывания кластера в Kubernetes с использованием официального Helm-чарта, включая настройку отказоустойчивости, безопасности и мониторинга.

## Определения

* **Helm-чарт OpenSearch**: официальный пакет для автоматизации развертывания и управления жизненным циклом OpenSearch в Kubernetes.
* **Cluster Manager (ранее Master)**: роль узла, ответственного за координацию кластера. В Helm-чарте настраивается через параметр `roles: [cluster_manager]`.
* **initContainers**: вспомогательные контейнеры, выполняемые до запуска основного процесса. Используются для настройки `vm.max_map_count` и прав доступа.
* **PodDisruptionBudget (PDB)**: ресурс Kubernetes, гарантирующий наличие минимального количества доступных подов при плановом обслуживании узлов.
* **ServiceMonitor**: ресурс Prometheus Operator для автоматического обнаружения эндпоинтов метрик OpenSearch.
* **Remote-Backed Storage (RBS)**: конфигурация OpenSearch 2.15+, позволяющая использовать объектные хранилища (S3/GCS) как основной уровень хранения через Helm-конфигурацию.

## Основные концепции

### Архитектура развертывания (Node Groups)

Для промышленных сред рекомендуется разделять узлы на специализированные группы (Node Groups), каждая из которых устанавливается как отдельный Helm-релиз:

1.  **Cluster Manager**: минимум 3 узла. Обеспечивают стабильность метаданных. Не должны хранить данные.
2.  **Data (Hot/Warm/Cold)**:
    *   **Hot**: быстрые NVMe SSD для активной записи и поиска.
    *   **Warm/Cold**: HDD или более дешевые хранилища для архивных данных. Настраиваются через `persistence.storageClass`.
3.  **Ingest**: выделенные узлы для тяжелых пайплайнов обработки данных.
4.  **Dashboards**: отдельный чарт для визуализации.

### Сетевое взаимодействие и Ingress

* **Headless Service**: используется для `discovery` (порт 9300).
* **Ingress**: рекомендуется для доступа к API (порт 9200) и Dashboards (порт 5601).
    * **Best Practice**: установка аннотации `nginx.ingress.kubernetes.io/proxy-body-size: "50m"` для поддержки больших Bulk-запросов.
    * **Timeouts**: увеличение `proxy-read-timeout` до 300с для тяжелых поисковых запросов.

### Мониторинг и обсервабилити

Интеграция с Prometheus через Helm требует установки плагина `opensearch-prometheus-exporter`.
* **ServiceMonitor**: включается параметром `serviceMonitor.enabled: true`.
* **Безопасность**: рекомендуется создать отдельного пользователя в OpenSearch с ролью `cluster:monitor/prometheus/metrics` для сбора метрик.

## Практические сценарии

### Настройка Remote-Backed Storage (RBS) в values.yaml

Для OpenSearch 2.15+ в Kubernetes:

```yaml
config:
  opensearch.yml:
    cluster.remote_store.enabled: true
    cluster.indices.replication.strategy: SEGMENT
    cluster.remote_store.repository: my-s3-repo
    # Экспериментально в 2.15: вынос состояния кластера в S3
    cluster.remote_store.state.enabled: true
    cluster.remote_store.state.repository: my-s3-repo

extraInitContainers:
  - name: install-plugins
    image: opensearchproject/opensearch:2.15.0
    command: ['sh', '-c', 'bin/opensearch-plugin install --batch repository-s3']
```

### Развертывание промышленного кластера

1.  **Настройка TLS (Cert-manager)**:
    Используйте сертификаты от `cert-manager` для автоматизации. Создайте Secret `opensearch-certs` и смонтируйте его:
    ```yaml
    secretMounts:
      - name: opensearch-certs
        secretName: opensearch-certs
        path: /usr/share/opensearch/config/certs
    ```
2.  **Установка Node Groups**:
    ```bash
    # Установка менеджеров
    helm install os-mgr opensearch/opensearch -f values-mgr.yaml
    # Установка дата-узлов (Hot)
    helm install os-data-hot opensearch/opensearch -f values-data-hot.yaml
    ```

### Обновление без простоя (Rolling Update)

1.  **Shard Allocation Awareness**:
    В `values.yaml` настройте учет зон доступности (AZ):
    ```yaml
    config:
      opensearch.yml:
        cluster.routing.allocation.awareness.attributes: "topology.kubernetes.io/zone"
    ```
2.  **Pod Anti-Affinity**:
    Используйте `hard` anti-affinity для Cluster Manager:
    ```yaml
    antiAffinity: "hard"
    ```
3.  **Последовательность**:
    *   Обновляйте Data-узлы по одной группе.
    *   Дождитесь `green` статуса и завершения `shards relocation` перед переходом к следующей группе.
    *   В последнюю очередь обновляйте Cluster Manager.

### Оптимизация JVM Heap и ресурсов

**Strict Rule**: устанавливайте `requests` равными `limits` для обеспечения Guaranteed QoS.
*   **Memory**: `resources.limits.memory: 8Gi`.
*   **Heap**: `OPENSEARCH_JAVA_OPTS: "-Xms4g -Xmx4g"`.
*   **Storage**: используйте `volumeClaimTemplates` для гарантированного выделения дисков в StatefulSet.

## Дополнительная информация

* **[Администрирование OpenSearch](./opensearch_administration.md)** — управление индексами, безопасность и RBS.
* **[OpenSearch: Обзор системы](./opensearch_overview.md)** — архитектура и ключевые компоненты.
* **[Artifact Hub: OpenSearch Chart](https://artifacthub.io/packages/helm/opensearch/opensearch)** — первоисточник параметров чарта.
