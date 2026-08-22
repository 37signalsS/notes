# VictoriaMetrics — обзор

## Определения

**VictoriaMetrics** — это высокопроизводительная, экономичная и горизонтально масштабируемая платформа для сбора и хранения данных наблюдаемости (Observability). Изначально разработанная как база данных временных рядов (TSDB) для метрик, система эволюционировала в универсальный стек, объединяющий метрики, логи и трейсы.

VictoriaMetrics является стандартом де-факто для долгосрочного хранения (Long-Term Storage, LTS) в экосистеме [Prometheus](./../Prometheus/overview.md), предлагая более простую эксплуатацию и высокую плотность упаковки данных по сравнению с [Thanos](./../Prometheus/scaling/thanos_overview.md) и [Mimir](./../Mimir/mimir_overview.md).

Ключевой принцип дизайна — **простота**: хранилище не зависит от внешних компонентов (объектное хранилище, внешние БД), всё необходимое для production входит в один бинарный файл (single-node) или в ограниченный набор хорошо документированных компонентов (cluster-режим).

## Базовые концепции

### Режимы работы

1. **Single-node:** все функции (приём данных, хранение, запросы, UI) в одном бинарном файле `victoria-metrics`. Идеально для небольших систем (< 1 млн точек в секунду) и простоты управления. HTTP-эндпоинт по умолчанию — порт `8428`.
2. **Cluster:** распределённая архитектура из независимых компонентов (`vminsert`, `vmstorage`, `vmselect`, `vmauth`). Обеспечивает высокую доступность (HA), масштабирование до сотен миллионов активных временных рядов и мульти-тенантность.

### Ключевые особенности

* **Экстремальная эффективность:** агрессивное сжатие данных (в 10–15 раз лучше стандартных TSDB) и низкое потребление ресурсов (CPU/RAM). Оптимизирована для работы даже на медленных HDD.
* **MetricsQL:** расширенный язык запросов, полностью совместимый с [PromQL](./../Prometheus/concepts/promql/selectors_operators.md), но добавляющий функции для аналитики, прогнозирования и работы с пропусками в данных.
* **Поддержка современных стандартов:** нативная поддержка [OpenTelemetry](./../OpenTelemetry/architecture_signals.md), приём данных по Remote Write 2.0 (Protobuf), UTF-8 имена метрик и значений метрик, автоматическая дедупликация данных от HA-пар Prometheus (по флагу `-dedup.minScrapeInterval`).
* **Native Histograms:** Prometheus Native Histograms поддерживаются при приёме данных (с версии v1.143.0) и конвертируются во внутренний формат гистограмм VictoriaMetrics (лейблы `vmrange`), совместимый с `histogram_quantile`, что экономит дисковое пространство.
* **Мульти-тенантность (cluster-режим):** изоляция данных для разных проектов или команд через идентификаторы `accountID:projectID` в URL.
* **Retention и агрегация:** автоматическое удаление устаревших данных (`-retentionPeriod`), downsampling (Enterprise) для долгосрочного хранения и per-series retention filters (Enterprise).

### Версии и релизные линии (LTS)

* **Community-версии:** релизы в нотации `vX.Y.Z` (на текущий момент актуальная линия — `v1.14x`). Пользователи, не использующие Enterprise, должны обновляться до последнего стабильного релиза.
* **Enterprise-версии:** предоставляют **LTS-линии** — каждая линия получает bugfix-обновления и патчи безопасности в течение 12 месяцев. Новые LTS-линии выходят каждые ~6 месяцев, поэтому в любой момент поддерживаются две последние линии (например, `v1.148.x` и `v1.136.x`).
* **Различия** между Community и Enterprise касаются дополнительных возможностей (downsampling, retention filters, multitenancy advance, Anomaly Detection, mTLS для `vminsert`/`vmselect` и др.), но модель данных и формат хранения идентичны, поэтому переход между редакциями не требует деградации данных.

### Единая платформа наблюдаемости (Unified Observability)

Платформа объединяет специализированные решения для всех типов сигналов:

* **VictoriaMetrics (vmsingle / cluster)** — хранение и запросы по метрикам (MetricsQL).
* **VictoriaLogs** — масштабируемая система управления логами. Отличается высокой скоростью поиска и минимальными затратами на хранение за счёт отсутствия тяжёлых индексов (схема schema-less). 
    *   Язык запросов: **[LogsQL](./logsql_overview.md)**.
    *   Архитектура и хранение: **[Внутреннее устройство VictoriaLogs](./victorialogs_internals.md)**.

#### Сравнение VictoriaLogs с альтернативами

| Система | Особенности эксплуатации | Работа с кардинальностью (trace_id) | Схема данных |
| :--- | :--- | :--- | :--- |
| **Elasticsearch** | Управление индексами, шардами и mapping | Дорого в индексе, требует RAM | Требуется mapping |
| **Grafana Loki** | Зависимость от меток (labels) | Проблема "Label Cardinality" | Schema-less по телу |
| **ClickHouse** | Требует проектирования схем и ключей | Очень быстро, но сложно в начале | Нужна явная схема |
| **VictoriaLogs** | Один бинарный файл, без индексов | Оптимизировано, "из коробки" | Schema-less (авто-поля) |

#### Экспертное мнение и опыт эксплуатации (dBrain.cloud)
*   **Масштабируемость:** VictoriaLogs — наиболее предпочтительное решение при необходимости честного горизонтального масштабирования. С огромным запасом обходит Loki и Elasticsearch по чистому перфомансу и плотности хранения.
*   **Реальный кейс:** Успешная эксплуатация на **500+ серверах** с терабайтами данных силами **одного инженера**.
*   **Сценарий выбора:**
    *   До 30 хостов — VictoriaLogs single instance или Elasticsearch.
    *   Highload и кластеризация — однозначно VictoriaLogs Cluster.
    *   Loki рассматривается как вариант с высоким риском оверинжиниринга при масштабировании.

* **VictoriaTraces** — хранилище трейсов, совместимое с API Tempo и Jaeger. Принимает данные по OTLP (без необходимости во внешнем объектном хранилище). По состоянию на 2026 год продукт находится на финальной стадии перед официальным [GA-релизом](https://docs.victoriametrics.com/victoriatraces/roadmap/).
* **vmanomaly (Enterprise)** — модуль на базе машинного обучения (ML) для автоматического обнаружения аномалий в поведении метрик без ручной настройки порогов. Начиная с версии v1.5.0 требует Enterprise-лицензию.
* **vmui** — встроенный веб-интерфейс для запросов, визуализации и дашбордов (по умолчанию на `http://localhost:8428/vmui`).
* **vmauth** — прокси-сервер аутентификации и маршрутизации.

### Архитектура кластерного режима

#### Основные компоненты

1. **VictoriaMetrics Cluster (Metrics)**
    * **`vminsert`**: принимает данные по протоколам `remote_write` (PRW v1/v.2, Protobuf), OpenTelemetry, InfluxDB и др. Распределяет данные между узлами `vmstorage` с поддержкой балансировки и перемаршрутизации (availability/slowness-based rerouting).
    * **`vmstorage`**: хранит данные на диске (Shared-Nothing). Не имеет разделяемого состояния. Предоставляет API для снапшотов и компакции.
    * **`vmselect`**: выполняет запросы MetricsQL/PromQL, агрегируя данные с узлов хранения. Поддерживает многоуровневое кэширование и мульти-тенантность.

2. **VictoriaLogs Cluster (Logs)**
    * **`vlinsert`**: приём входящих логов.
    * **`vlstorage`**: хранение данных на диске.
    * **`vlselect`**: обработка запросов LogsQL.

*Все роли в VictoriaLogs выполняются одним и тем же бинарным файлом, режим работы определяется флагами запуска.*

3. **`vmauth`**
    * Прокси-сервер для аутентификации (JWT, OIDC, Basic Auth) и маршрутизации запросов между тенантами.

#### Внутренние порты (по умолчанию)

| Компонент | HTTP-порт (приём данных/UI) | Назначение |
| :--- | :--- | :--- |
| `victoria-metrics` (single) | `8428` | HTTP API, vmui, `/api/v1/import*` |
| `vminsert` | `8480` | `/insert` на приём данных |
| `vmselect` | `8481` | `/select` для запросов |
| `vmstorage` | `8482` | служебный HTTP; TCP `8400` (для `vminsert`) и `8401` (для `vmselect`) |
| `vlinsert` | `9480` | VictoriaLogs: приём данных |
| `vlselect` | `9481` | VictoriaLogs: выполнение запросов |
| `vlstorage` | `9482` | VictoriaLogs: хранение |
| `vmagent` | `8429` | scrape + remote_write |
| `vmalert` | `8880` | HTTP UI, `/alerts`, `/api/v1/rules` |
| `vmauth` | `8427` | proxy/auth |

#### Дополнительные компоненты и инструменты

* **`vmagent`** — агент для сбора метрик (scraper). Может заменять Prometheus. Поддерживает фильтрацию/переименование меток, буферизацию данных на диске (persistent queue) при обрыве связи с центральным хранилищем, streaming aggregation (Enterprise) и приём данных по OTLP/InfluxDB/Graphite.
* **`vmalert`** — выполнение правил алертинга и записи. Может использовать в качестве источника данных как метрики VictoriaMetrics, так и логи из VictoriaLogs (LogsQL) и трейсы VictoriaTraces. Подробнее: [`vmalert_overview.md`](./vmalert_overview.md).
* **`vmctl`** — утилита для миграции данных из Prometheus (snapshot), InfluxDB, OpenTSDB, Thanos, Mimir и между инстансами VictoriaMetrics (native mode). Полезен для переноса исторических данных без простоя.
* **`vmbackup` / `vmrestore`** — утилиты для инкрементального резервного копирования в S3, GCS, Azure Blob Storage и локальное хранилище.
* **VictoriaMetrics Operator** — Kubernetes-оператор для автоматизации деплоя, масштабирования, rolling update, бэкапов и управления ресурсами (VMSingle, VMCluster, VMAgent, VMAlert, VMRule, VMServiceScrape, VMPodScrape и др.). Поддерживает миграцию из Prometheus CRDs.

## Практические сценарии

### Быстрый старт (Docker, single-node)

```bash
docker run --rm -it \
  -p 8428:8428 \
  -v vmdata:/victoria-metrics-data \
  victoriametrics/victoria-metrics
# → UI: http://localhost:8428/vmui
# → приём от Prometheus: http://localhost:8428/api/v1/write
```

### Запуск данных из Prometheus

```bash
./vmctl prometheus \
  --prom-snapshot=/path/to/snapshot \
  --vm-addr=http://localhost:8428
# → исторические данные импортируются без простоя
```

### Деплой в Kubernetes

Рекомендуемый путь — [VictoriaMetrics Operator](https://docs.victoriametrics.com/operator/) с CRDs (`VMSingle`, `VMCluster`, `VMAgent`, `VMAlert`, `VMRule`, `VMServiceScrape`) или Helm-чарт `victoria-metrics` / `victoria-metrics-cluster`. Правила алертинга декларативно описываются через ресурс [VMRule](./vmalert_rules_management_with_manifests.md), который оператор транслирует в конфигурацию `vmalert` с горячей перезагрузкой.

### Резервное копирование

```bash
# Инкрементальный бэкап в S3-совместимое хранилище
vmbackup -storageDataPath=/victoria-metrics-data \
  -snapshot.createURL=http://localhost:8428/snapshot/create \
  -backupsPath=s3://bucket/vm-backups

# Восстановление
vmrestore -storageDataPath=/victoria-metrics-data \
  -src=s3://bucket/vm-backups
# → после восстановления запустить victoria-metrics с тем же -storageDataPath
```

Существует также сервис `vmbackupmanager` (Enterprise) для управления retention бэкапов (например, хранить N дней).

### Сбор метрик через vmagent

Для сбора метрик с целевых систем и передачи в VictoriaMetrics используется **vmagent**. Он заменяет Prometheus в сценариях, где нужен только сбор и forwarding, без локального TSDB.

```yaml
# vmagent.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']

  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
```

Запуск:
```bash
docker run -d \
  -v vmagent-data:/victoria-metrics-data \
  -p 8429:8429 \
  victoriametrics/vmagent \
  -promscrape.config=vmagent.yml \
  -remoteWrite.url=http://localhost:8428/api/v1/write
```

Для алертинга используется **vmalert**, который consuming метрики из VictoriaMetrics по MetricsQL/PromQL. Правила описываются через ресурс [VMRule](./vmalert_rules_management_with_manifests.md).

### Сравнение с альтернативами

| Характеристика | VictoriaMetrics | Thanos | Grafana Mimir (v3.x) |
| :--- | :--- | :--- | :--- |
| **Сложность** | Низкая (единый стек) | Высокая (много компонентов) | Средняя |
| **Хранилище** | Локальные диски / EBS / Flash | Объектное (S3/GCS) | Объектное (S3/GCS) |
| **Сжатие данных** | Экстремальное | Среднее (через Downsampling) | Высокое |
| **Интеграция** | `remote_write` (PRW 1/2) | Sidecar / Receiver | `remote_write` |
| **Типы данных** | Метрики, Логи, Трейсы | Метрики | Метрики |
| **AI/Аномалии** | Встроено: vmanomaly (Enterprise) / vmui | Нет | Grafana Machine Learning |

## Дополнительная информация

VictoriaMetrics рекомендуется использовать в Kubernetes через **VictoriaMetrics Operator**, который автоматизирует деплой, обновление и управление правилами алертинга через [VMRule](./vmalert_rules_management_with_manifests.md).

Смотрите также:
* [VictoriaLogs: внутреннее устройство](./victorialogs_internals.md) — детальный разбор хранения и обработки логов;
* [vmalert](./vmalert_overview.md) — подробный обзор компонента алертинга;
* [Управление правилами в K8s](./vmalert_rules_management_with_manifests.md) — декларативный подход к алертингу;
* [Prometheus: обзор](../Prometheus/overview.md) — основа экосистемы метрик.