# Логирование в Rancher

## Определения

**Rancher Logging** — интегрированное решение для централизованного сбора, фильтрации и маршрутизации логов в кластерах под управлением Rancher. Базируется на **Logging Operator** (проект Banzai Cloud/SUSE).

**Logging Operator** — Kubernetes-оператор, управляющий жизненным циклом компонентов логирования (Fluent Bit и Fluentd) через декларативные пользовательские ресурсы (Custom Resources).

**Fluent Bit** — легковесный агент, работающий как DaemonSet на каждом узле. Его задача — сбор сырых логов контейнеров, их обогащение метаданными Kubernetes и передача в агрегатор.

**Fluentd** — центральный агрегатор и маршрутизатор логов. Выполняет сложную фильтрацию, трансформацию данных и отправку во внешние системы хранения (Output).

## Базовые концепции

### Архитектура потоков данных

Rancher Logging реализует разделение ответственности между компонентами для обеспечения производительности и гибкости.

1.  **Сбор (Collection)**: Fluent Bit читает файлы логов из `/var/log/containers/` и пересылает их во Fluentd.
2.  **Агрегация (Aggregation)**: Fluentd принимает потоки от всех агентов, объединяет их и применяет правила маршрутизации.
3.  **Маршрутизация (Routing)**: На основе правил `Flow` логи направляются в соответствующие `Output`.

### Иерархия ресурсов управления

Настройка системы выполняется через четыре основных типа ресурсов:

*   **Logging**: Глобальный ресурс, определяющий параметры Fluent Bit и Fluentd (версии образов, лимиты ресурсов, Tolerations, настройки буферизации). Обычно создается один на кластер.
*   **Output / ClusterOutput**: Определяют целевую систему хранения (Elasticsearch, OpenSearch, Kafka, S3, Splunk).
    *   `Output`: Доступен только внутри своего Namespace.
    *   `ClusterOutput`: Глобальный ресурс, доступный для всех потоков в кластере.
*   **Flow / ClusterFlow**: Определяют фильтры и связывают источники логов с конкретными Output.
    *   `Flow`: Собирает логи только из своего Namespace.
    *   `ClusterFlow`: Может собирать логи со всего кластера или определенных Namespace.

### Разграничение прав доступа (RBAC)

Интеграция с RBAC (Role-Based Access Control) Rancher позволяет делегировать управление логированием владельцам приложений:

| Роль в Rancher | ClusterFlow / ClusterOutput | Flow / Output |
| :--- | :--- | :--- |
| **Cluster Admin** | Полный доступ | Полный доступ |
| **Project Owner** | Только чтение | Полный доступ |
| **Project Member** | Нет доступа | Только чтение |

## Практические сценарии

### Настройка ресурсов для Fluentd

При больших объемах логов стандартные лимиты Fluentd могут привести к перезагрузкам по OOM (Out Of Memory). Настройка выполняется через Helm-параметры или редактирование ресурса `Logging`:

```yaml
spec:
  fluentd:
    resources:
      limits:
        cpu: "1000m"
        memory: "2Gi"
      requests:
        cpu: "500m"
        memory: "1Gi"
    bufferStorageVolume:
      pvc:
        spec:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 20Gi
          storageClassName: local-path
```

### Совместимость с OpenSearch 2.x

Для корректной работы с новыми версиями OpenSearch в `ClusterOutput` необходимо отключить использование типов документов, которые были удалены:

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: ClusterOutput
metadata:
  name: opensearch-prod
  namespace: cattle-logging-system
spec:
  opensearch:
    host: opensearch.example.com
    port: 9200
    scheme: https
    suppress_type_name: true  # Обязательно для OpenSearch 2.x+
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
```

### Сбор логов только из определенных Namespace

Чтобы избежать перегрузки агрегатора ненужными данными, используйте `ClusterFlow` с селекторами:

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: ClusterFlow
metadata:
  name: critical-apps-flow
  namespace: cattle-logging-system
spec:
  match:
    - select:
        namespaces:
          - prod-app-1
          - prod-app-2
  filters:
    - tag_normalizer: {}
  globalOutputRefs:
    - opensearch-prod
```

### Диагностика и отладка

Если логи не доходят до хранилища, используйте следующую последовательность действий:

1.  **Проверка статуса агентов**: Убедитесь, что поды `fluent-bit` запущены на всех узлах.
2.  **Проверка соединения**: Проверьте логи Fluent Bit на наличие ошибок подключения к Fluentd.
3.  **Логи агрегатора**: Просмотрите детальный вывод Fluentd:
    ```bash
    kubectl logs -n cattle-logging-system -l app.kubernetes.io/name=fluentd
    ```
4.  **Состояние буфера**: Если Output недоступен, Fluentd начнет копить логи в буфер. Если PVC переполнится, логи начнут теряться. Проверьте объем `/buffers` внутри пода Fluentd.

## Дополнительная информация

### Статус компонентов

| Компонент | Состояние | Рекомендация |
|-----------|-----------|--------------|
| Logging Operator | Актуально | Основной стандарт для Rancher 2.5+ |
| Banzai Cloud CRDs | Стабильно | Используйте актуальные версии v1beta1+ |

**Связанные разделы:**

* [Архитектура логирования Kubernetes](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — общие принципы и подходы.
* [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
* [Конфигурация Fluent Bit](../MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md) — подробности работы агента сбора.

**Внешние ресурсы:**

* [Logging Operator Documentation](https://kube-logging.github.io/docs/)
* [Rancher Logging Guide](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/logging)
