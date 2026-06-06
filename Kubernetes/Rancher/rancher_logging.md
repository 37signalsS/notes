# Логирование в Rancher

## Определения

**Rancher Logging** — интегрированное решение для централизованного сбора, фильтрации и маршрутизации логов в кластерах под управлением Rancher. Решение базируется на Logging Operator (проект Banzai Cloud/SUSE), использующем Fluent Bit в качестве сборщика и Fluentd в качестве агрегатора.

**Logging Operator** — Kubernetes-оператор, который управляет жизненным циклом компонентов логирования и предоставляет декларативный API (Application Programming Interface) для настройки потоков данных через пользовательские ресурсы (Custom Resources).

## Базовые концепции

### Архитектура и компоненты

Rancher Logging следует стандартным принципам [архитектуры логирования Kubernetes](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md), дополняя их специализированным уровнем управления:

1. **Fluent Bit (DaemonSet)**: разворачивается на каждом узле кластера. Собирает логи контейнеров из `/var/log/containers/`, обогащает их метаданными Kubernetes и пересылает в агрегатор.
2. **Fluentd (StatefulSet)**: выступает центральным узлом маршрутизации. Принимает данные от Fluent Bit, применяет сложные фильтры и отправляет логи во внешние системы хранения.

### Управляющие ресурсы (Custom Resources)

Настройка системы выполняется через YAML (YAML Ain't Markup Language) манифесты двух типов:

* **Output / ClusterOutput**: определяют "куда" отправлять логи. Поддерживают интеграции с Elasticsearch, OpenSearch, Kafka, S3 (Simple Storage Service) и другими.
  * `Output`: ресурс уровня пространства имён (Namespace).
  * `ClusterOutput`: общекластерный ресурс, доступный для использования всеми потоками.
* **Flow / ClusterFlow**: определяют "какие" логи собирать и "как" их обрабатывать.
  * `Flow`: собирает логи только в своем пространстве имён.
  * `ClusterFlow`: может собирать логи со всего кластера.

### Разграничение прав доступа (RBAC)

Управление ресурсами логирования интегрировано в модель RBAC (Role-Based Access Control) Rancher:

| Роль в Rancher | ClusterFlow / ClusterOutput | Flow / Output |
| :--- | :--- | :--- |
| **Admin** | Полный доступ | Полный доступ |
| **Project Owner** | Нет доступа | Полный доступ |
| **Project Member** | Нет доступа | Только чтение |

Для настройки сбора логов пользователям с ролью `Project Member` требуется помощь администратора или владельца проекта.

## Практические сценарии

### Установка системы через Rancher UI

1. Перейдите в **Cluster Dashboard** → **Apps** → **Charts**.
2. Найдите и выберите **Logging**.
3. При установке в разделе **Helm Options** обязательно проверьте настройки ресурсов (CPU, Memory) для Fluentd, так как при больших потоках логов стандартных лимитов может быть недостаточно.
4. Для сбора логов с узлов Control Plane добавьте исключения (Tolerations) в конфигурацию Helm:

```yaml
fluentbit:
  tolerations:
  - effect: NoSchedule
    key: node-role.kubernetes.io/master
    operator: Exists
  - effect: NoSchedule
    key: node-role.kubernetes.io/control-plane
    operator: Exists
```

### Настройка отправки в OpenSearch

Поскольку интерфейс Rancher (UI) может не поддерживать все параметры последних версий OpenSearch, рекомендуется использовать "Edit YAML" для настройки `ClusterOutput`:

1. Создайте секрет с учетными данными в пространстве имён `cattle-logging-system`.
2. Настройте `ClusterOutput` с параметром `suppress_type_name: true` (критично для совместимости с OpenSearch 2.x+):

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: ClusterOutput
metadata:
  name: opensearch-output
  namespace: cattle-logging-system
spec:
  opensearch:
    host: opensearch.example.com
    port: 9200
    scheme: https
    user:
      username:
        valueFrom:
          secretKeyRef:
            name: opensearch-auth
            key: username
    password:
      valueFrom:
        secretKeyRef:
          name: opensearch-auth
          key: password
    ssl_verify: false
    suppress_type_name: true
    buffer:
      timekey: 1m
      timekey_wait: 30s
```

### Фильтрация и обработка (Flow)

Для динамического формирования индексов и добавления временных меток используйте фильтры во `Flow`:

* **Tag Normalizer**: формирует тег на основе метаданных пода.
* **Kube Events Timestamp**: добавляет поле с точным временем события для корректной сортировки.

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: Flow
metadata:
  name: app-logs-flow
  namespace: my-apps
spec:
  filters:
  - tag_normalizer:
      tag: ${namespace_name}.${pod_name}
  - kube_events_timestamp:
      time_field: event_time
  globalOutputRefs:
  - opensearch-output
```

### Диагностика проблем (Troubleshooting)

1. **Проверка агентов (Fluent Bit)**: если логи не поступают в агрегатор, проверьте логи DaemonSet в пространстве имён `cattle-logging-system`.
2. **Логи агрегатора (Fluentd)**: Fluentd по умолчанию пишет логи в файл внутри контейнера.

   ```bash
   kubectl exec -n cattle-logging-system <fluentd-pod-name> -- cat /var/log/fluentd/out
   ```

3. **Ошибки Output**: если хранилище (Elasticsearch/OpenSearch) недоступно, Fluentd начнет заполнять буфер. Проверьте статус PVC (Persistent Volume Claim), если он используется для буферизации.

## Дополнительная информация

### Статус и актуальность

| Компонент | Состояние | Рекомендация |
|-----------|-----------|--------------|
| Logging Operator | Актуально | Основной механизм в Rancher 2.x |
| Fluent Bit | Стабильно | Оптимален для сбора логов в K8s |
| Fluentd | Стабильно | Используется как гибкий маршрутизатор |

**Связанные темы:**

* [Архитектура логирования Kubernetes](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — SSoT по общим принципам.
* [Конфигурация Fluent Bit](../MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md) — детали настройки агентов.
* [EFK Stack Setup](../MonitoringLogging/EFK/efk_stack_setup_guide.md) — развертывание Elasticsearch и Kibana.

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
