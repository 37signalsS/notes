# Логирование в Rancher

## Определения

**Rancher Logging** — интегрированное решение для централизованного сбора, фильтрации и маршрутизации логов в кластерах под управлением Rancher. Базируется на **Logging Operator** (проект Banzai Cloud/SUSE).

**Logging Operator** — Kubernetes-оператор, управляющий жизненным циклом компонентов логирования (Fluent Bit, Fluentd и Vector) через декларативные пользовательские ресурсы (Custom Resources).

**Fluent Bit** — высокопроизводительный Edge-агент (написан на C), работающий как DaemonSet на каждом узле. В актуальных версиях (v3.x+) является OTel-native компонентом, собирает логи контейнеров, обогащает их метаданными Kubernetes и передает в агрегатор.

**Fluentd / Vector** — центральные агрегаторы и маршрутизаторы логов.
*   **Fluentd**: Классический агрегатор с богатой экосистемой Ruby-плагинов. Рекомендуется для сложных трансформаций и Legacy-интеграций.
*   **Vector**: Современный агрегатор (написан на Rust), ориентированный на производительность и нативную поддержку OpenTelemetry. Рекомендуется для высоконагруженных сред.

## Базовые концепции

### Архитектура потоков данных

Rancher Logging реализует разделение ответственности между компонентами для обеспечения производительности и гибкости.

1.  **Сбор (Collection)**: Fluent Bit читает файлы логов из `/var/log/containers/` и пересылает их в агрегатор по протоколу Forward (для Fluentd) или OTLP (для Vector/OpenTelemetry).
2.  **Агрегация (Aggregation)**: Агрегатор принимает потоки от всех агентов, объединяет их, выполняет дедупликацию и применяет правила маршрутизации.
3.  **Маршрутизация (Routing)**: На основе правил `Flow` логи направляются в соответствующие `Output` (хранилища или брокеры).

### Иерархия ресурсов управления

Настройка системы выполняется через пять основных типов ресурсов:

*   **Logging**: Глобальный ресурс, определяющий архитектуру (выбор между Fluentd и Vector), параметры агентов и общие настройки (версии образов, лимиты ресурсов, Tolerations).
*   **Output / ClusterOutput**: Определяют целевую систему хранения (Elasticsearch, OpenSearch 3.x, Kafka, S3, Loki, OTLP).
    *   `Output`: Доступен только внутри своего Namespace.
    *   `ClusterOutput`: Глобальный ресурс, доступный для всего кластера.
*   **Flow / ClusterFlow**: Определяют фильтры (парсинг JSON, добавление меток, исключение строк) и связывают источники логов с `Output`.
    *   `Flow`: Собирает логи только из своего Namespace.
    *   `ClusterFlow`: Может собирать логи со всего кластера или определенных Namespace.

### Разграничение прав доступа (RBAC)

Интеграция с ролевой моделью Rancher позволяет делегировать управление логированием владельцам приложений:

| Роль в Rancher | ClusterFlow / ClusterOutput | Flow / Output |
| :--- | :--- | :--- |
| **Cluster Admin** | Полный доступ | Полный доступ |
| **Project Owner** | Только чтение | Полный доступ |
| **Project Member** | Нет доступа | Только чтение |

## Практические сценарии

### Настройка Vector как основного агрегатора (Рекомендация 2026)

Для снижения потребления ресурсов и поддержки OTel рекомендуется использовать Vector в качестве агрегатора в ресурсе `Logging`:

```yaml
spec:
  controlNamespace: cattle-logging-system
  fluentbit:
    resources:
      limits:
        memory: "256Mi"
  vector:
    resources:
      limits:
        cpu: "1000m"
        memory: "1Gi"
```

### Отправка логов в OpenTelemetry (OTLP)

В современной архитектуре наблюдаемости логи часто направляются в OTel Collector для дальнейшей обработки:

```yaml
apiVersion: logging.banzaicloud.io/v1beta1
kind: ClusterOutput
metadata:
  name: otel-collector
  namespace: cattle-logging-system
spec:
  otlp:
    endpoint: "otel-collector.monitoring.svc:4317"
    protocol: grpc
    tls:
      enabled: true
      insecure: false
```

### Совместимость с OpenSearch 3.x

Для OpenSearch актуальных версий необходимо учитывать изменения в API и форматах данных:

```yaml
spec:
  opensearch:
    host: opensearch.example.com
    port: 9200
    scheme: https
    suppress_type_name: true  # Обязательно для совместимости с OS 2.x/3.x
    index_name: "k8s-logs-%Y.%m.%d"
    allow_self_signed_cert: false
```

### Тюнинг буферизации для высоконагруженных сред

Чтобы избежать потери логов при недоступности хранилища, необходимо настроить PVC-буфер для Fluentd/Vector:

```yaml
spec:
  fluentd:
    bufferStorageVolume:
      pvc:
        spec:
          accessModes: [ "ReadWriteOnce" ]
          resources:
            requests:
              storage: 50Gi
          storageClassName: premium-rwo
```

## Диагностика и отладка

Если логи не доходят до хранилища, используйте следующую последовательность:

1.  **Проверка статуса агентов**: Убедитесь, что поды `fluent-bit` запущены и не находятся в состоянии `CrashLoopBackOff` из-за нехватки памяти (проверьте `OOMKilled`).
2.  **Валидация конфигурации**: Logging Operator генерирует итоговый конфиг. Проверьте Secret `rancher-logging-fluentd-config` (или аналогичный для Vector) на наличие синтаксических ошибок.
3.  **Логи агрегатора**: Просмотрите детальный вывод агрегатора для поиска ошибок авторизации в Output:
    ```bash
    kubectl logs -n cattle-logging-system -l app.kubernetes.io/name=fluentd # или vector
    ```
4.  **Метрики**: Используйте Grafana-дашборд "Logging Operator Overview" для отслеживания `failed_outputs` и `buffer_usage`.

## Дополнительная информация

### Статус компонентов (2026)

| Компонент | Состояние | Рекомендация |
| :--- | :--- | :--- |
| **Logging Operator** | Актуально | Основной стандарт для всех типов кластеров (RKE2, K3s, Import). |
| **Vector Support** | Stable | Рекомендуется для новых инсталляций вместо Fluentd. |
| **OTel Integration** | GA | Используйте OTLP для унификации с метриками и трассировками. |

**Связанные разделы:**

* [Архитектура наблюдаемости в Kubernetes](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — общие принципы.
* [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
* [Конфигурация Fluent Bit](../MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md) — детальный тюнинг агента.

**Внешние ресурсы:**

* [Kube-Logging (Logging Operator) Documentation](https://kube-logging.github.io/docs/)
* [Rancher Logging Guide](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/logging)
