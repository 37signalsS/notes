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
* **vmestimator** — оценка кардинальности в реальном времени на этапе сбора. Позволяет получать алерты до наступления взрыва кардинальности. Подробнее: [`vmestimator.md`](./vmestimator.md).
* **vmctl** — утилита для миграции данных из Prometheus (snapshot), InfluxDB, OpenTSDB, Thanos, Mimir и между инстансами VictoriaMetrics (native mode). Полезен для переноса исторических данных без простоя.
* **vmbackup / vmrestore** — утилиты для инкрементального резервного копирования в S3, GCS, Azure Blob Storage и локальное хранилище.
* **VictoriaMetrics Operator** — Kubernetes-оператор для автоматизации деплоя, масштабирования, rolling update, бэкапов и управления ресурсами (VMSingle, VMCluster, VMAgent, VMAlert, VMRule, VMServiceScrape, VMPodScrape и др.). Поддерживает миграцию из Prometheus CRDs.

## Требования к окружению

### Операционная система и среда

VictoriaMetrics поддерживает запуск на любом современном Linux-дистрибутиве (Debian, Ubuntu, RHEL, CentOS, Rocky Linux, Alpine) и через Docker/Podman. Для production на bare-metal рекомендуется:

- **Ядро Linux:** версия 4.14+ (для `io_uring` и эффективной работы с диском)
- **FS:** XFS или ext4 (с отключением `atime` или использованием `noatime,nodiratime`)
- **Пользователь:** создайте отдельного непривилегированного пользователя `victoriametrics` с домашним каталогом на том же разделе, что и `-storageDataPath`
- **Лимиты:** увеличьте `ulimit -n` (open files) до минимум 65535 для single-node и 200000+ для cluster-режима

### Аппаратные требования (single-node)

| Активные временные ряды | CPU | RAM | Диск (SSD) | Retention |
| :--- | :--- | :--- | :--- | :--- |
| до 500 000 | 2 ядра | 4 ГБ | 50 ГБ | 30–90 дней |
| 500 000 – 5 000 000 | 4 ядра | 8 ГБ | 200 ГБ | 90–365 дней |
| 5 000 000 – 20 000 000 | 8 ядер | 16 ГБ | 1 ТБ | 1–2 года |
| > 20 000 000 | рассмотреть cluster | 32+ ГБ | 4+ ТБ | 2+ года |

**Важные замечания:**
- VictoriaMetrics оптимизирована для HDD, но для production с высокой нагрузкой SSD/NVMe обязателен.
- При работе на HDD увеличьте `-search.maxQueryDuration` и ограничьте параллелизм запросов (`-search.maxQueries`), так как случайные чтения будут доминировать.
- Для сжатия и компакции критически важны CPU и IOPS. При недостатке IOPS данные не успевают компактироваться — растет число мелких частей (parts) и деградирует производительность запросов.

### Аппаратные требования (cluster-режим)

| Компонент | CPU | RAM | Диск (SSD) | Рекомендации |
| :--- | :--- | :--- | :--- | :--- |
| `vminsert` | 4+ ядра | 4+ ГБ | — | CPU-bound при высокой скорости инжеста |
| `vmselect` | 4+ ядера | 8+ ГБ | — | Memory-bound при сложных запросах |
| `vmstorage` | 8+ ядер | 8+ ГБ | 1+ ТБ на узел | Disk/IOPS-bound; масштабируется горизонтально |

**Общие рекомендации для cluster:**
- Запускайте не менее 3 узлов `vmstorage` для отказоустойчивости (данные реплицируются между storage-узлами).
- Размещайте `vminsert` и `vmselect` на отдельных хостах или используйте resource limits/requests в Kubernetes.
- Для `vmstorage` используйте локальные SSD (non-shared), так как Shared-Nothing архитектура не даёт преимуществ от сетевых дисков.

### Программные зависимости

- **Docker/Podman:** образ `victoriametrics/victoria-metrics:latest` (single) или отдельные компоненты (`victoriametrics/vminsert`, `victoriametrics/vmselect`, `victoriametrics/vmstorage`)
- **Helm:** для Kubernetes-деплоя используйте официальный Helm-репозиторий `https://victoriametrics.github.io/helm-charts/`
- **vmctl, vmbackup, vmrestore:** поставляются как отдельные бинарники в том же релизе, что и основная платформа

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

### Валидация установки

После запуска single-node выполните проверку:

```bash
# 1. Проверка здоровья
curl -s http://localhost:8428/health
# → {}

# 2. Проверка встроенных метрик
curl -s http://localhost:8428/metrics | head -20

# 3. Запись тестовой метрики
curl -i -X POST \
  -H "Content-Encoding: snappy" \
  --data-binary @- \
  http://localhost:8428/api/v1/write \
  <<< '{"metric":{"__name__":"test_metric","job":"validation"},"values":[1],"timestamps":[1234567890000]}'
# → HTTP/1.1 204 No Content

# 4. Проверка появления данных
curl -s 'http://localhost:8428/api/v1/query?query=test_metric' | jq .
# → {"status":"success","data":{"resultType":"vector","result":[{"metric":{"__name__":"test_metric","job":"validation"},"value":[1234567890,"1"]}]}}

# 5. Проверка в UI
# Откройте http://localhost:8428/vmui и выполните запрос test_metric
```

### Импорт данных из Prometheus

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

### Деплой на bare-metal (systemd)

Для production-развертывания на физических серверах или виртуальных машинах без контейнеризации используйте systemd-сервис.

**1. Скачайте бинарник:**

```bash
VICTORIA_VERSION="v1.148.0"
wget -O /usr/local/bin/victoria-metrics \
  "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VICTORIA_VERSION}/victoria-metrics-${VICTORIA_VERSION}-linux-amd64.tar.gz"
chmod +x /usr/local/bin/victoria-metrics
```

**2. Создайте пользователя и каталоги:**

```bash
useradd --no-create-home --shell /bin/false victoriametrics
mkdir -p /var/lib/victoria-metrics
chown victoriametrics:victoriametrics /var/lib/victoria-metrics
```

**3. Создайте systemd-сервис `/etc/systemd/system/victoria-metrics.service`:**

```ini
[Unit]
Description=VictoriaMetrics Single Node
Documentation=https://docs.victoriametrics.com
After=network.target

[Service]
Type=simple
User=victoriametrics
Group=victoriametrics
ExecStart=/usr/local/bin/victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -retentionPeriod=30d \
  -httpListenAddr=:8428 \
  -vminsert.maxConcurrentInserts=128 \
  -search.maxQueryDuration=30s \
  -logToStderr=true \
  -loggerFormat=json
Restart=always
RestartSec=5
LimitNOFILE=200000
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**4. Запустите сервис:**

```bash
systemctl daemon-reload
systemctl enable --now victoria-metrics
systemctl status victoria-metrics
# → active (running)

# Проверка логов
journalctl -u victoria-metrics -f
```

**5. Валидация:**

```bash
curl -s http://localhost:8428/health
# → {}
```

### Высокая доступность (HA) для single-node

Для отказоустойчивости разверните два независимых инстанса на разных хостах. VictoriaMetrics автоматически дедуплицирует данные от HA-пар Prometheus по флагу `-dedup.minScrapeInterval`.

**Конфигурация Prometheus с remote write:**

```yaml
# prometheus.yml
remote_write:
  - url: "http://victoriametrics-host1:8428/api/v1/write"
    remoteTimeout: 30s
    queue_config:
      capacity: 25000
      max_shards: 50
  - url: "http://victoriametrics-host2:8428/api/v1/write"
    remoteTimeout: 30s
    queue_config:
      capacity: 25000
      max_shards: 50
```

На стороне VictoriaMetrics включите дедупликацию:

```bash
victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -dedup.minScrapeInterval=1s
```

**Валидация HA:**

```bash
# Проверка метрики дедупликации
curl -s 'http://localhost:8428/api/v1/query?query=vm_deduplicated_rows_total' | jq .
# → Должен расти при параллельной записи из двух Prometheus
```

### Конфигурация vmauth (аутентификация и маршрутизация)

`vmauth` работает как обратный прокси перед `vminsert`/`vmselect`, обеспечивая аутентификацию (JWT, OIDC, Basic Auth) и маршрутизацию по путям.

**Пример базовой конфигурации `/etc/victoriametrics/vmauth.yml`:**

```yaml
# routes:
#   - src_path: /insert/0/prometheus/api/v1/write
#     dst_path: /insert/0/prometheus/api/v1/write
#     upstreams:
#       - http://vminsert1:8480
#       - http://vminsert2:8480
#     # Ограничение по rete limiting (опционально)
#     max_requests_per_second: 10000

#   - src_path: /select/0/prometheus
#     dst_path: /select/0/prometheus
#     upstreams:
#       - http://vmselect1:8481
#       - http://vmselect2:8481
```

**Запуск vmauth:**

```bash
docker run -d \
  -p 8427:8427 \
  -v /path/to/vmauth.yml:/etc/victoriametrics/vmauth.yml \
  victoriametrics/vmauth \
  -auth.config=/etc/victoriametrics/vmauth.yml
```

Для Enterprise-версии доступна поддержка mTLS между `vminsert`/`vmselect` и `vmauth`.

### Настройка retention и downsampling

**Retention на уровне single-node:**

```bash
victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -retentionPeriod=90d \
  -retention.maxDiskSpaceUsageBytes=500G
```

`-retention.maxDiskSpaceUsageBytes` приоритетно ограничивает место. Когда лимит достигнут, старые данные удаляются вне зависимости от `-retentionPeriod`.

**Per-series retention filters (Enterprise):**

```json
[
  {
    "match": {"job": "short-lived"},
    "retention": "7d"
  },
  {
    "match": {"job": "long-term"},
    "retention": "2y"
  }
]
```

```bash
victoria-metrics-enterprise \
  -storageDataPath=/var/lib/victoria-metrics \
  -retentionSpec=retention.json
```

### Миграция данных (vmctl)

**Миграция из InfluxDB:**

```bash
vmctl influxdb \
  -influxdb.addr=http://influxdb:8086 \
  -influxdb.database=metrics \
  -vm-addr=http://localhost:8428/api/v1/write
```

**Миграция из OpenTSDB:**

```bash
vmctl opentsdb \
  -opentsdb.addr=http://opentsdb:4242 \
  -vm-addr=http://localhost:8428/api/v1/write
```

**Миграция между инстансами VictoriaMetrics (native mode):**

```bash
vmctl victoriametrics \
  -vmAddr=http://source-vm:8428 \
  -dstAddr=http://dest-vm:8428/api/v1/write
```

### Планирование мощностей (Capacity Planning)

**Формула оценки диска (single-node, Community):**

```
Диск (ГБ) ≈ (active_series × samples_per_series_per_day × 10 байт × retention_days) / 1024³
```

Пример: 5 млн активных серий, 15s scrape, 30 дней retention:

```
(5 000 000 × 5760 × 10 × 30) / 1024³ ≈ 8.1 ГБ
```

С запасом рекомендуется указывать в 2–3 раза больше (компакция, индексы, WAL).

**Оценка RAM (память на метаданные):** память у storage растёт от кардинальности серий/меток, а не от объёма диска. Ориентир — ~100 тыс. – 1 млн серий на ~1 ГБ RAM storage-узла; метод подбора и метрики диагностики описаны в [storage_internals.md: RAM](./storage_internals.md#оценка-памяти-ram-под-метаданные). Для точного прогноза — [vmestimator](./vmestimator.md), до боевой нагрузки — прямое наблюдение `/api/v1/status/tsdb`.

**Для cluster-режима:**

```
storage_nodes × disk_per_node = общий disk budget
```

При 10 млн активных серий и retention 90 дней на 3 узлах `vmstorage`:
- ~40 ГБ на узел (с запасом 120 ГБ)
- 8+ ядер и 16+ ГБ RAM на узел

### Сравнение с альтернативами

| Характеристика | VictoriaMetrics | Thanos | Grafana Mimir (v3.x) |
| :--- | :--- | :--- | :--- |
| **Сложность** | Низкая (единый стек) | Высокая (много компонентов) | Средняя |
| **Хранилище** | Локальные диски / EBS / Flash | Объектное (S3/GCS) | Объектное (S3/GCS) |
| **Сжатие данных** | Экстремальное | Среднее (через Downsampling) | Высокое |
| **Интеграция** | `remote_write` (PRW 1/2) | Sidecar / Receiver | `remote_write` |
| **Типы данных** | Метрики, Логи, Трейсы | Метрики | Метрики |
| **Алертинг/аналитика** | vmalert, vmanomaly (Enterprise), vmui | Thanos Ruler | Grafana Machine Learning |
| **On-prem готовность** | Нативная (единый бинарник) | Требует объектное хранилище | Требует объектное хранилище |

## Поиск и устранение неисправностей (Troubleshooting)

### Single-node

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `vm_rows_inserted_total` не растет | Неправильный URL `remote_write` или блокировка firewall | Проверить URL, сетевую доступность и логи vmagent/Prometheus |
| Данные не появляются после записи | Не применен `Content-Encoding: snappy` или ошибка в формате | Использовать snappy-сжатие; проверить `/api/v1/write` на 204 |
| Медленные запросы | Недостаток IOPS или слишком широкий временной диапазон | Проверить `vm_slow_queries`, увеличить `-search.maxQueryDuration`, добавить индексы через лейблы |
| `read-only` режим | Диск заполнен (`-retention.maxDiskSpaceUsageBytes`) или файловая система в READ-ONLY | Проверить `df -h`, очистить место или увеличить лимит |
| Высокое потребление RAM | Взрыв кардинальности или слишком большой `-search.maxQueryDuration` | Проверить `vm_active_series`, настроить `relabel_configs` для удаления динамических лейблов |
| Потеря данных при перезагрузке | Нет persistent queue в vmagent | Включить `-remoteWrite.maxQueueSize` и `-remoteWrite.diskQueueDir` в vmagent |
| Ошибка дедупликации | `-dedup.minScrapeInterval` не установлен или меньше actual scrape interval | Установить `-dedup.minScrapeInterval` ≥ максимального scrape interval среди всех Prometheus-инстансов |

### Cluster-режим

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `vm_dropped_rows_total` растет | `vminsert` перегружен или `vmstorage` недоступен | Проверить доступность `vmstorage` (health-check), увеличить количество `vminsert` или `vmstorage` |
| Медленные запросы в кластере | Слишком много `vmselect` реплик или не均衡ная нагрузка | Проверить `vm_active_queries`, добавить `vmselect`, настроить `vmauth` балансировку |
| Данные не реплицируются между `vmstorage` | Неправильная конфигурация репликации или сетевые таймауты | Проверить логи `vmstorage` на ошибки репликации, увеличить `-storageDataPath` на каждом узле |
| `vmstorage` переходит в READ-ONLY | Диск заполнен или файловая система повреждена | Проверить `df -h`, логи `vmstorage`; восстановить из бэкапа |
| Медленная загрузка данных (ingestion lag) | Недостаточно `vminsert` или узлов `vmstorage` | Масштабировать `vminsert` горизонтально; проверить `vm_rows_inserted_total` |
| Ошибки аутентификации в `vmauth` | Неверные JWT/OIDC настройки или истекший токен | Проверить конфигурацию `vmauth.yml`, логи `vmauth` |

## Рекомендации по эксплуатации и очистке (Best Practices & Cleanup)

### Resource Limits и планирование

- **Устанавливайте `LimitNOFILE`** в systemd-сервисе не менее 200000 для single-node и 500000 для cluster-компонентов.
- **Ограничьте `-search.maxQueryDuration`** (например, 30s для single-node, 60s для cluster), чтобы предотвратить долгие запросы, блокирующие компакцию.
- **Используйте `-vminsert.maxConcurrentInserts`** для ограничения параллельных вставок в cluster-режиме (по умолчанию 100).
- **Мониторьте `vm_parts`** на `vmstorage`: при росте числа частей выше 1000 на узел — проверьте IOPS и размер партиций.

### Retention и управление данными

- **Начинайте с `-retentionPeriod=30d`** для dev-окружений и `90d–1y` для production. Дольше 2 лет — рассматривайте downsampling (Enterprise).
- **Используйте `-retention.maxDiskSpaceUsageBytes`** как приоритетный лимит, особенно на SSD с ограниченным местом.
- **Настраивайте алерты на диск:** `disk_usage_percent{path="/victoria-metrics-data"} > 85` за 10 минут.
- **Проводите бэкап перед major upgrade:** vmbackup инкрементален, но восстановление требует останова сервиса.

### Безопасность

- **Изолируйте `8428`/`8480`/`8481`** firewall-ом в production. Доступ к `/api/v1/write` должен быть только у scrapers/агентов.
- **Используйте vmauth** для аутентификации в cluster-режиме. В Enterprise доступен mTLS между компонентами.
- **Не запускайте single-node с `-httpListenAddr=0.0.0.0`** без firewall в интернете.

### Upgrade и обновление

**Процедура обновления single-node:**

```bash
# 1. Создайте снапшот
curl -s http://localhost:8428/snapshot/create | jq -r '.status'

# 2. Остановите сервис
systemctl stop victoria-metrics

# 3. Обновите бинарник
wget -O /usr/local/bin/victoria-metrics \
  "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v${VERSION}/victoria-metrics-v${VERSION}-linux-amd64.tar.gz"
chmod +x /usr/local/bin/victoria-metrics

# 4. Запустите
systemctl start victoria-metrics

# 5. Проверьте
curl -s http://localhost:8428/health
```

**Важно:** VictoriaMetrics обратно совменима в рамках мажорных версий (например, v1.136.x → v1.148.x). Данные на диске не требуют миграции. Перед обновлением проверяйте [релизные заметки](https://docs.victoriametrics.com/lts-releases/) на breaking changes.

### Очистка окружения

- **Удалите неиспользуемые метрики:** настройте `write_relabel_configs` в Prometheus или vmagent для dropped нерелевантных метрик.
- **Проверяйте `vm_dropped_rows_total`** — если растет, значит, данные отбрасываются на стороне vminsert.
- **При удалении инстанса:** убедитесь, что все `vmstorage` узлы остановлены, прежде чем удалять данные, чтобы избежать corruption.

## Ограничения и особые случаи (Edge Cases & Limitations)

### Кардинальность

- **Практический лимит single-node:** ~50 млн активных временных рядов (при 16+ ГБ RAM и SSD). При превышении — переходите в cluster-режим.
- **Взрыв кардинальности:** если в лейблы попадают уникальные значения (request_id, IP клиентов), RAM может быть исчерпана за минуты. Используйте `relabel_configs` для удаления динамических лейблов на этапе сбора.
- **Native Histograms:** поддерживаются с v1.143.0. При приеме конвертируются во внутренний формат `vmrange`. Ограничение: не все функции MetricsQL поддерживают `vmrange` — используйте `histogram_quantile` для совместимости.

### Диск и WAL

- **WAL (Write-Ahead Log):** хранится в `-storageDataPath/wal`. При аварийном завершении VictoriaMetrics автоматически восстанавливает не записанные данные из WAL. Не удаляйте WAL вручную при остановленном сервисе.
- **Shared-Nothing:** в cluster-режиме каждый `vmstorage` независим. Не монтируйте общие диски (NFS, CIFS) для `-storageDataPath` — это приведет к corruption.
- **Компакция (compaction):** фоновый процесс, требующий IOPS. При недостатке IOPS число `parts` растет, и запросы замедляются. Мониторьте `vm_parts` на `vmstorage`.

### Сеть

- **Remote Write таймауты:** при высокой латентности между scrapers и VictoriaMetrics увеличьте `remoteTimeout` в Prometheus (по умолчанию 30s) и `-search.maxQueryDuration` в VictoriaMetrics.
- **Асинхронная запись в cluster:** `vminsert` возвращает 204 сразу после распределения данных по `vmstorage`. Если `vmstorage` потом откажет, данные могут быть потеряны. Для критичных сценариев используйте persistent queue в vmagent.
- **Дублирование при HA:** без `-dedup.minScrapeInterval` два Prometheus, скрейпящие одни и те же таргеты, создадут двойные данные. Установите флаг на стороне VictoriaMetrics.

### Ограничения версий

- **Enterprise-функции недоступны в Community:** downsampling, retention filters, multitenancy advance, streaming aggregation в vmagent, Anomaly Detection.
- **MetricsQL vs PromQL:** VictoriaMetrics поддерживает PromQL, но некоторые продвинутые функции (например, `label_replace` с regex) работают быстрее в MetricsQL. Полная совместимость сохраняется для стандартных запросов.
- **OTLP ingestion:** поддерживается, но для сложной обработки (transformation, filtering) лучше использовать vmagent с `relabel_configs` или отдельный OTel Collector.

## Дополнительная информация

VictoriaMetrics рекомендуется использовать в Kubernetes через **VictoriaMetrics Operator**, который автоматизирует деплой, обновление и управление правилами алертинга через [VMRule](./vmalert_rules_management_with_manifests.md).

Смотрите также:
* [VictoriaLogs: внутреннее устройство](./victorialogs_internals.md) — детальный разбор хранения и обработки логов;
* [vmalert](./vmalert_overview.md) — подробный обзор компонента алертинга;
* [vmagent](./vmagent_overview.md) — сбор и доставка метрик;
* [MetricsQL](./metricsql_reference.md) — язык запросов;
* [vmbackup/vmrestore](./vmbackup_restore.md) — резервное копирование;
* [vmctl](./vmctl_migration.md) — миграция исторических данных;
* [vmauth](./vmauth_overview.md) — прокси аутентификации и маршрутизации;
* [cluster_operations](./cluster_operations.md) — работа с кластерным режимом;
* [storage_internals](./storage_internals.md) — внутренности хранилища метрик;
* [security](./security.md) — безопасность стека;
* [HTTP API](./http_api_reference.md) — справочник эндпоинтов, экспорт/импорт, снапшоты;
* [Grafana: интеграция](./grafana_integration.md) — подключение VM/VictoriaLogs к Grafana;
* [vmui](./vmui_overview.md) — встроенный веб-интерфейс;
* [DR: аварийное восстановление](./disaster_recovery.md) — RPO/RTO, сценарии восстановления;
* [k8s-stack: чарт](./helm_victoria_metrics_k8s_stack.md) — деплой мониторинга в Kubernetes;
* [Enterprise-функции](./enterprise_features.md) — downsampling, retention filters, vmgateway и др.
* [operator](./operator_overview.md) — Kubernetes-оператор;
* [VictoriaLogs: инжест](./victorialogs_ingestion.md) — протоколы приёма логов;
* [VictoriaTraces](./victoriatraces.md) — хранение трейсов (pre-GA);
* [vmestimator](./vmestimator.md) — оценка кардинальности в реальном времени;
* [Управление правилами в K8s](./vmalert_rules_management_with_manifests.md) — декларативный подход к алертингу;
* [Prometheus: обзор](../Prometheus/overview.md) — основа экосистемы метрик.