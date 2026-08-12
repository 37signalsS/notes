# Prometheus — Концепции (CRD)

## Определения

**`kind: Prometheus`** — ключевой Custom Resource Definition (CRD) в Prometheus Operator, предназначенный для декларативного описания жизненного цикла и конфигурации экземпляра Prometheus Server. На основе этого ресурса Operator автоматически создает и управляет Kubernetes-объектами: StatefulSet, Service, ConfigMap, Secrets и RBAC.

**Reconciliation Loop в Prometheus CRD** — процесс, при котором Оператор постоянно сравнивает желаемое состояние (описанное в CRD) с реальным состоянием в кластере, обеспечивая актуальность конфигурации скрейпинга, правил алертинга и параметров хранения.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Концепции Prometheus Operator](../concepts.md), [ServiceMonitor](./servicemonitor.md), [PodMonitor](./podmonitor.md), [Prometheus Rule](./prometheusrule.md).

## Базовые концепции

### Принцип работы и жизненный цикл

1.  **Watch:** Оператор отслеживает изменения объекта `Prometheus` и связанных с ним ресурсов через Kubernetes API.
2.  **Discovery:** Собираются ссылки на все связанные ресурсы через селекторы (`serviceMonitorSelector`, `podMonitorSelector`, `ruleSelector` и т.д.).
3.  **Generation:** Генерируется итоговый `prometheus.yaml`. В современных версиях (v0.80+) поддерживается автоматическая настройка UTF-8 для Prometheus 3.0.
4.  **Storage Config:** Формируется описание `TSDB` (хранилища). Для Prometheus 3.9+ реализована оптимизация координации с Thanos, позволяющая не отключать локальную компакцию.
5.  **Deployment:** Создается или обновляется `StatefulSet`.
6.  **Reload:** Sidecar-контейнер `config-reloader` (работает в том же поде) обнаруживает изменения в ConfigMap/Secret и инициирует обновление конфигурации через сигнал `/-/reload` без перезагрузки подов.

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

### Сценарий 1: Производственная конфигурация (HA + Storage + Security)

Конфигурация с двумя репликами, персистентным хранилищем и настройками безопасности.

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
  securityContext:
    fsGroup: 2000
    runAsNonRoot: true
    runAsUser: 1000
  podMetadata:
    annotations:
      container.apparmor.security.beta.kubernetes.io/prometheus: runtime/default
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

### Сценарий 3: Кастомный скрейпинг и OTLP

Использование `additionalScrapeConfigs` для целей, которые нельзя описать через CRD.

```yaml
spec:
  version: v3.12.0
  enableFeatures:
    - otlp-write-receiver
    - native-histograms
  additionalScrapeConfigs:
    name: extra-scrape-configs
    key: prometheus-additional.yaml
  remoteWrite:
    - url: "http://remote-storage:8428/api/v1/write"
      remoteTimeout: 30s
  otlp:
    promoteResourceAttributes:
      - service.name
      - service.namespace
```

## Дополнительная информация

### Ключевые параметры спецификации (v1)

| Параметр | Описание | Особенности (2026) |
| :--- | :--- | :--- |
| **`shards`** | Количество шардов для масштабирования. | Позволяет горизонтально масштабировать скрейпинг. |
| **`externalLabels`** | Глобальные метки экземпляра. | Используются для дедупликации в Thanos/VictoriaMetrics. |
| **`scrapeProtocols`** | Приоритет протоколов (OpenMetrics и др.). | Требует Prometheus >= v2.49. |
| **`additionalScrapeConfigs`** | Ссылка на Secret с классическим конфигом. | Позволяет настраивать сложные SD, не поддерживаемые CRD. |
| **`enforcedSampleLimit`** | Глобальный лимит сэмплов на скрейп. | Защита от OOM при взрывном росте количества метрик. |
| **`securityContext`** | Настройки безопасности Pod/Container. | Управление правами пользователя, групп и Linux capabilities. |
| **`podMetadata`** | Лейблы и аннотации для создаваемых подов. | Критично для интеграции с системами сбора логов и mesh. |
| **`web`** | Настройка веб-интерфейса (TLS, Auth). | Позволяет защитить UI через встроенные механизмы. |
| **`dnsConfig` / `dnsPolicy`** | Настройка DNS для подов Prometheus. | Управление разрешением имен внутри кластера. |
| **`goGC`** | Настройка Go Garbage Collector. | Оптимизация потребления RAM и пауз GC. |

### См. также

*   [High Availability](../high_availability.md) — детальное описание механизмов репликации и шардирования в Prometheus Operator.
*   [Thanos Overview](../../../scaling/thanos_overview.md) — архитектура долгосрочного хранения и глобального представления данных.
*   [Prometheus Operator API](https://prometheus-operator.dev/docs/operator/api/) — официальная справочная документация по всем полям CRD.
