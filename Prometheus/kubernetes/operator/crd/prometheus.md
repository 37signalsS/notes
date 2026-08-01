# Prometheus — Концепции (CRD)

## Определения

**`kind: Prometheus`** — ключевой Custom Resource Definition (CRD) в Prometheus Operator, предназначенный для декларативного описания жизненного цикла и конфигурации экземпляра Prometheus Server. На основе этого ресурса Operator автоматически создает и управляет Kubernetes-объектами: StatefulSet, Service, ConfigMap, Secrets и RBAC.

**Reconciliation Loop в Prometheus CRD** — процесс, при котором Оператор постоянно сравнивает желаемое состояние (описанное в CRD) с реальным состоянием в кластере, обеспечивая актуальность конфигурации скрейпинга, правил алертинга и параметров хранения.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Концепции Prometheus Operator](../concepts.md), [ServiceMonitor](./servicemonitor.md), [PodMonitor](./podmonitor.md), [Prometheus Rule](./prometheusrule.md).

## Базовые концепции

### Принцип работы и жизненный цикл

1.  **Watch:** Оператор отслеживает изменения объекта `Prometheus`.
2.  **Discovery:** Собираются ссылки на все связанные ресурсы через селекторы (`serviceMonitorSelector`, `podMonitorSelector`, `ruleSelector` и т.д.).
3.  **Generation:** Генерируется итоговый `prometheus.yaml`. В современных версиях (v0.80+) поддерживается автоматическая настройка UTF-8 для Prometheus 3.0.
4.  **Storage Config:** Формируется описание `TSDB` (хранилища). Для Prometheus 3.9+ реализована оптимизация координации с Thanos, позволяющая не отключать локальную компакцию.
5.  **Deployment:** Создается или обновляется `StatefulSet`.
6.  **Reload:** Sidecar-контейнер `config-reloader` инициирует обновление конфигурации без перезагрузки подов.

### Селекторы целей и правил

Ресурс `Prometheus` выступает агрегатором, объединяющим разрозненные описания мониторинга:

| Селектор | Тип ресурса | Назначение |
| :--- | :--- | :--- |
| **`serviceMonitorSelector`** | `ServiceMonitor` | Обнаружение целей через Kubernetes Service. |
| **`podMonitorSelector`** | `PodMonitor` | Прямой скрейпинг IP-адресов подов. |
| **`probeSelector`** | `Probe` | Blackbox-мониторинг внешних целей. |
| **`scrapeConfigSelector`** | `ScrapeConfig` | Нативные и кастомные конфигурации сбора данных. |
| **`ruleSelector`** | `PrometheusRule` | Подключение групп правил алертинга и записи. |

### Поддержка Prometheus 3.0 (2025–2026)

*   **UTF-8 Mode:** Поддержка любых символов в именах метрик и лейблов (требует Prometheus >= v3.0.0).
*   **Remote Write v2.0:** Использование новой версии протокола для повышения эффективности передачи данных.
*   **Native Histograms:** Настройка параметров разреженных гистограмм для сбора высокоточных данных.
*   **OTLP Ingestion:** Возможность приема данных по протоколу OpenTelemetry напрямую.

## Практические сценарии

### Сценарий 1: Производственная конфигурация (HA + Storage)

Конфигурация с двумя репликами, персистентным хранилищем и лимитами ресурсов.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.12.0
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
  retention: 30d
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-storage
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 100Gi
  resources:
    requests:
      memory: 2Gi
      cpu: 500m
    limits:
      memory: 8Gi
      cpu: 2000m
```

### Сценарий 2: Интеграция с Thanos и оптимизация компакции

Актуально для версий Prometheus >= 3.9.0 и Thanos >= 0.41.0.

```yaml
spec:
  thanos:
    version: v0.41.0
    objectStorageConfig:
      key: thanos.yaml
      name: thanos-objstore-config
  # Примечание: В новых версиях Operator компакция не отключается автоматически,
  # если используется координация через shipper meta file.
```

### Сценарий 3: Настройка Prometheus 3.0 и OTLP

```yaml
spec:
  version: v3.12.0
  enableFeatures:
    - otlp-write-receiver
    - native-histograms
  remoteWrite:
    - url: "http://remote-storage:8428/api/v1/write"
      remoteTimeout: 30s
      metadataConfig:
        send: true
        sendInterval: 1m
  otlp:
    promoteResourceAttributes:
      - service.name
      - service.namespace
```

## Дополнительная информация

### Ключевые параметры спецификации (v1)

| Параметр | Описание | Особенности (2026) |
| :--- | :--- | :--- |
| **`shards`** | Количество шардов для горизонтального масштабирования. | По умолчанию `1`. |
| **`externalLabels`** | Глобальные метки экземпляра. | Используются для дедупликации в Thanos. |
| **`scrapeProtocols`** | Приоритет протоколов (OpenMetrics, PrometheusProto). | Требует Prometheus >= v2.49. |
| **`dnsConfig` / `dnsPolicy`** | Настройка DNS для подов Prometheus. | Добавлено в v0.80. |
| **`goGC`** | Настройка Go Garbage Collector. | Позволяет оптимизировать потребление RAM. |
| **`ruleQueryOffset`** | Смещение выполнения правил. | Предотвращает пропуски данных при задержках. |

### Связанные ресурсы

*   **[High Availability](../high_availability.md)** — глубокое погружение в репликацию и шардирование.
*   **[Thanos Overview](../../../scaling/thanos_overview.md)** — архитектура долгосрочного хранения.
*   **[Alertmanager CRD](./alertmanager.md)** — интеграция с системой оповещений.
*   **[Reliability Scores](../../../GEMINI.md)** — методология оценки достоверности (Score: 10).

### См. также
* [Prometheus Operator API Documentation](https://prometheus-operator.dev/docs/operator/api/)
* [Prometheus 3.0 Release Notes](https://prometheus.io/blog/2024/11/14/prometheus-3-0-release/)
