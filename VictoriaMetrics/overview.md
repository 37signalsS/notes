# VictoriaMetrics — обзор

**Актуально для:** VictoriaMetrics v1.154.x (Community) / v1.148.x (LTS)

## Определения

**VictoriaMetrics** — это высокопроизводительная, экономичная и горизонтально масштабируемая платформа для сбора и хранения данных наблюдаемости (Observability). Изначально разработанная как база данных временных рядов (TSDB) для метрик, система эволюционировала в универсальный стек, объединяющий метрики, логи и трейсы.

VictoriaMetrics является стандартом де-факто для долгосрочного хранения (Long-Term Storage, LTS) в экосистеме [Prometheus](./../Prometheus/overview.md), предлагая более простую эксплуатацию и высокую плотность упаковки данных по сравнению с [Thanos](./../Prometheus/scaling/thanos_overview.md) и [Mimir](./../Mimir/mimir_overview.md).

Ключевой принцип дизайна — **простота**: хранилище не зависит от внешних компонентов (объектное хранилище, внешние БД), всё необходимое для production входит в один бинарный файл (single-node) или в ограниченный набор хорошо документированных компонентов (cluster-режим).

## Базовые концепции

### Режимы работы

1. **Single-node:** все функции (приём данных, хранение, запросы, UI) в одном бинарном файле `victoria-metrics-prod` (в Docker-образе — точка входа контейнера). По данным FAQ, справляется до 100 млн активных серий и до 2 млн samples/s; удобен там, где важна простота управления. HTTP-эндпоинт по умолчанию — порт `8428`.
2. **Cluster:** распределённая архитектура из независимых компонентов (`vminsert`, `vmstorage`, `vmselect`, `vmauth`). Обеспечивает высокую доступность (HA), масштабирование до миллиардов активных временных рядов и мульти-тенантность.

### Ключевые особенности

* **Экстремальная эффективность:** плотная упаковка данных (после сжатия типично около 1 байта на sample — измеряется запросом `sum(vm_data_size_bytes) / sum(vm_rows{type!~"indexdb.*"})`) и низкое потребление ресурсов (CPU/RAM). Оптимизирована для работы даже на медленных HDD.
* **MetricsQL:** расширенный язык запросов, совместимый с [PromQL](./../Prometheus/concepts/promql/selectors_operators.md) и добавляющий функции для аналитики, прогнозирования и работы с пропусками в данных. Полной 100% идентичности нет: MetricsQL намеренно исправляет отдельные неудобные поведения PromQL (подробнее — в [FAQ проекта](https://docs.victoriametrics.com/victoriametrics/faq/#why-isnt-metricsql-100-compatible-with-promql)).
* **Поддержка современных стандартов:** нативная поддержка [OpenTelemetry](./../OpenTelemetry/architecture_signals.md), приём данных по Prometheus Remote Write 1.0 (snappy-сжатый Protobuf), OTLP и OpenMetrics/text; имена метрик и лейблов не приводятся к Prometheus-совместимому виду по умолчанию (санитизация — только по флагу `-usePromCompatibleNaming`); автоматическая дедупликация данных от HA-пар Prometheus (по флагу `-dedup.minScrapeInterval`).
* **Native Histograms:** Prometheus Native Histograms поддерживаются при приёме данных (с версии v1.143.0) и конвертируются во внутренний формат гистограмм VictoriaMetrics (лейблы `vmrange`), совместимый с `histogram_quantile`, что экономит дисковое пространство.
* **Мульти-тенантность (cluster-режим):** изоляция данных для разных проектов или команд через идентификаторы `accountID:projectID` в URL (поддержка тенанта в URL и HTTP-заголовках — с v1.143.0). С v1.150.0 указание тенанта через заголовки `AccountID`/`ProjectID` включено по умолчанию (`-enableMultitenancyViaHeaders`), что позволяет использовать упрощённые пути `/insert/<suffix>` и `/select/<suffix>`.
* **Retention и агрегация:** автоматическое удаление устаревших данных (`-retentionPeriod`), downsampling (Enterprise) для долгосрочного хранения и per-series retention filters (Enterprise).
* **Кардинальность и масштабируемость:** Prometheus TSDB оптимизирован для краткосрочного хранения (15 часов по умолчанию) и ограничена по кардинальности — при росте количества серий метрик производительность падает. VictoriaMetrics решает эту проблему: высокая плотность данных и плотная упаковка хранения (порядка 1 байта на sample после сжатия) позволяют хранить метрики годами без деградации. Практический паттерн: Prometheus — для быстрого сбора и локального хранения, VictoriaMetrics — для long-term storage (LTS) и централизованного хранения через `remote_write`. VictoriaMetrics может поддерживать большое количество метрик в Grafana, где Prometheus не справляется из-за ограничений по кардинальности.

### Версии и релизные линии (LTS)

* **Community-версии:** релизы в нотации `vX.Y.Z` (на текущий момент линия `v1.15x`, последний релиз — `v1.154.0`). Пользователи, не использующие Enterprise, должны обновляться до последнего стабильного релиза.
* **Enterprise-версии:** предоставляют **LTS-линии** — каждая линия получает bugfix-обновления и патчи безопасности в течение 12 месяцев. Новые LTS-линии выходят каждые ~6 месяцев, поэтому в любой момент поддерживаются две последние линии (например, `v1.148.x` и `v1.136.x`).
* **Различия** между Community и Enterprise касаются дополнительных возможностей (downsampling, retention filters, per-tenant статистика, multitenancy в vmalert, Anomaly Detection, mTLS для `vminsert`/`vmselect` и др.), но модель данных и формат хранения идентичны, поэтому переход между редакциями не требует деградации данных.

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

* **VictoriaTraces** — хранилище трейсов, совместимое с API Tempo и Jaeger. Принимает данные по OTLP (без необходимости во внешнем объектном хранилище). По состоянию на 2026 год продукт остаётся pre-GA: пункты [roadmap](https://docs.victoriametrics.com/victoriatraces/roadmap/), ведущие к официальному GA-релизу, ещё не закрыты.
* **vmanomaly (Enterprise)** — модуль на базе машинного обучения (ML) для автоматического обнаружения аномалий в поведении метрик без ручной настройки порогов. Начиная с версии v1.5.0 запуск требует лицензионного ключа (Enterprise).
* **vmui** — встроенный веб-интерфейс для запросов, визуализации и дашбордов (по умолчанию на `http://localhost:8428/vmui`).
* **vmauth** — прокси-сервер аутентификации и маршрутизации.

### Архитектура кластерного режима

#### Основные компоненты

1. **VictoriaMetrics Cluster (Metrics)**
    * **`vminsert`**: принимает данные по протоколам `remote_write` (Prometheus Remote Write 1.0, Protobuf + snappy), OpenMetrics/text, OTLP, InfluxDB, Graphite, DataDog, NewRelic и др. Распределяет данные между узлами `vmstorage` с поддержкой балансировки и перемаршрутизации (availability/slowness-based rerouting).
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
| `vlinsert` / `vlselect` / `vlstorage` | `9428` | VictoriaLogs: все кластерные роли слушают `-httpListenAddr` с одинаковым дефолтом `:9428`; в официальных примерах запуска — `9481` (vlinsert), `9471` (vlselect), `9491` (vlstorage) |
| `vmagent` | `8429` | scrape + remote_write |
| `vmalert` | `8880` | HTTP UI, `/alerts`, `/api/v1/rules` |
| `vmauth` | `8427` | proxy/auth |

#### Дополнительные компоненты и инструменты

* **`vmagent`** — агент для сбора метрик (scraper). Может заменять Prometheus. Поддерживает фильтрацию/переименование меток, persistent queue на диске по умолчанию (`-remoteWrite.tmpDataPath`) при обрыве связи с центральным хранилищем, streaming aggregation и приём данных по OTLP/InfluxDB/Graphite.
* **`vmalert`** — выполнение правил алертинга и записи. Может использовать в качестве источника данных как метрики VictoriaMetrics, так и логи из VictoriaLogs (LogsQL) и трейсы VictoriaTraces. Подробнее: [`vmalert_overview.md`](./vmalert_overview.md).
* **vmestimator** — оценка кардинальности в реальном времени на этапе сбора. Позволяет получать алерты до наступления взрыва кардинальности. Подробнее: [`vmestimator.md`](./vmestimator.md).
* **vmctl** — утилита для миграции данных из Prometheus (snapshot), InfluxDB, OpenTSDB, Thanos (snapshot), Mimir/Cortex (remote read) и между инстансами VictoriaMetrics (native mode). Подробности: [vmctl_migration.md](./vmctl_migration.md).
* **vmbackup / vmrestore** — утилиты для инкрементального резервного копирования в S3, GCS, Azure Blob Storage и локальное хранилище.
* **VictoriaMetrics Operator** — Kubernetes-оператор для автоматизации деплоя, масштабирования, rolling update, бэкапов и управления ресурсами (VMSingle, VMCluster, VMAgent, VMAlert, VMRule, VMServiceScrape, VMPodScrape и др.). Поддерживает миграцию из Prometheus CRDs.

## Требования к окружению

### Операционная система и среда

VictoriaMetrics поддерживает запуск на любом современном Linux-дистрибутиве (Debian, Ubuntu, RHEL, CentOS, Rocky Linux, Alpine) и через Docker/Podman. Для production на bare-metal рекомендуется:

- **Ядро Linux:** версия 4.14+ (для `io_uring` и эффективной работы с диском)
- **FS:** XFS или ext4 (с отключением `atime` или использованием `noatime,nodiratime`)
- **Пользователь:** создайте отдельного непривилегированного пользователя `victoriametrics` с домашним каталогом на том же разделе, что и `-storageDataPath`
- **Лимиты:** увеличьте `ulimit -n` (open files) — практический ориентир 65535+ для single-node и 200000+ для cluster-режима (в systemd-конфиге ниже задано через `LimitNOFILE`)

### Аппаратные требования (single-node)

Ориентировочные значения для выбора стартового размера; точный подбор — по тестовому прогону и метрикам (см. ниже и [Планирование мощностей](#планирование-мощностей-capacity-planning)). Колонка «Диск» посчитана по официальной формуле (1 байт/sample, `BytesPerSample × IngestionRate × RetentionSeconds × 1.25`, плюс ~20% на индекс) при scrape `15s` и `ReplicationFactor=1`.

| Активные временные ряды | CPU | RAM | Диск (SSD) при 15s scrape | Retention |
| :--- | :--- | :--- | :--- | :--- |
| до 500 000 | 2 ядра | 4 ГБ | 0,1–0,5 ТБ | 30–90 дней |
| 500 000 – 5 000 000 | 4 ядра | 8 ГБ | 0,5–17 ТБ | 90–365 дней |
| 5 000 000 – 20 000 000 | 8 ядер | 16 ГБ | 17–130 ТБ | 1–2 года |
| > 20 000 000 | рассмотреть cluster | 32+ ГБ | — | 2+ года |

**Важные замечания:**
- VictoriaMetrics оптимизирована для HDD, но для production с высокой нагрузкой SSD/NVMe обязателен.
- При работе на HDD увеличьте `-search.maxQueryDuration` и ограничьте параллелизм запросов (`-search.maxQueries`), так как случайные чтения будут доминировать.
- Для сжатия и компакции критически важны CPU и IOPS. При недостатке IOPS данные не успевают компактироваться — растет число мелких частей (parts) и деградирует производительность запросов.
- **Резерв ресурсов (рекомендация документации):** оставляйте ~50% свободной RAM (превышение ведёт к вытеснению кэшей, лишнему I/O и общему замедлению), ~50% запаса CPU и не менее 20% свободного места на диске `-storageDataPath`. Жёсткий минимум свободного места задаётся флагом `-storage.minFreeDiskSpaceBytes` (по умолчанию `100MB`): при его достижении хранилище **перестаёт принимать новые данные**.
- Точный объём диска и ресурсов определяется не расчётом «на бумаге», а **тестовым прогоном**: запустите тестовый инстанс с продовой нагрузкой, измерьте занятость через сутки и экстраполируйте на весь retention (см. [Планирование мощностей](#планирование-мощностей-capacity-planning)).

### Аппаратные требования (cluster-режим)

| Компонент | CPU | RAM | Диск (SSD) | Рекомендации |
| :--- | :--- | :--- | :--- | :--- |
| `vminsert` | 4+ ядра | 4+ ГБ | — | CPU-bound при высокой скорости инжеста |
| `vmselect` | 4+ ядера | 8+ ГБ | — | Memory-bound при сложных запросах |
| `vmstorage` | 8+ ядер | 8+ ГБ | 1+ ТБ на узел | Disk/IOPS-bound; масштабируется горизонтально |

#### Общие рекомендации для cluster

- Запускайте не менее 3 узлов `vmstorage` для отказоустойчивости (данные реплицируются между storage-узлами; см. также `-replicationFactor`).
- Предпочтительнее **много мелких `vmstorage`-шардов, чем несколько крупных**: так нагрузка на оставшиеся узлы при отказе одного из них растёт меньше. Оптимальное число шардов, по данным документации, — между 10 и 50; уменьшение их числа после развёртывания — сложная и нежелательная операция, поэтому выбирайте количество заранее.
- Ориентиры при масштабировании: ~1 `vminsert` на 3–5 `vmstorage`-шардов; на `vminsert` — около 2 GiB RAM на 1 vCPU; для `vmselect` — не менее 10 GiB диска под локальные кэши; число `vmselect` выбирается по скорости чтения (горизонтальное масштабирование) и тяжести запросов (вертикальное).
- Размещайте `vminsert` и `vmselect` на отдельных хостах или используйте resource limits/requests в Kubernetes.
- Для `vmstorage` используйте локальные SSD (non-shared), так как Shared-Nothing архитектура не даёт преимуществ от сетевых дисков. Отдавайте `vmstorage` целые числа vCPU-ядер.

### Программные зависимости

- **Docker/Podman:** образ `victoriametrics/victoria-metrics:v1.154.0` (single) или отдельные компоненты (`victoriametrics/vminsert`, `victoriametrics/vmselect`, `victoriametrics/vmstorage`) с фиксированным тегом релиза; тег `latest` допустим только для экспериментов
- **Helm:** для Kubernetes-деплоя используйте официальный Helm-репозиторий `https://victoriametrics.github.io/helm-charts/`
- **vmctl, vmbackup, vmrestore:** поставляются как отдельные бинарники в том же релизе, что и основная платформа

## Практические сценарии

### Быстрый старт (Docker, single-node)

```bash
docker run --rm -it \
  -p 8428:8428 \
  -v vmdata:/victoria-metrics-data \
  victoriametrics/victoria-metrics:v1.154.0
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

# 3. Запись тестовой метрики (JSON line format → /api/v1/import)
#    Для /api/v1/write тело должно быть snappy-сжатым Prometheus protobuf —
#    сырой JSON туда не отправляется
curl -s -X POST \
  -H "Content-Type: application/json" \
  --data-binary '{"metric":{"__name__":"test_metric","job":"validation"},"values":[1],"timestamps":[1234567890000]}' \
  http://localhost:8428/api/v1/import
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
  -dst=s3://bucket/vm-backups

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
  -v $(pwd)/vmagent.yml:/etc/victoriametrics/agent.yaml:ro \
  -p 8429:8429 \
  victoriametrics/vmagent:v1.154.0 \
  -promscrape.config=/etc/victoriametrics/agent.yaml \
  -remoteWrite.url=http://localhost:8428/api/v1/write \
  -remoteWrite.tmpDataPath=/victoria-metrics-data/pq
# → queue на диске включён по умолчанию; путь задан явно, чтобы данные очереди попали в том
```

Для алертинга используется **vmalert**, который забирает метрики из VictoriaMetrics по MetricsQL/PromQL. Правила описываются через ресурс [VMRule](./vmalert_rules_management_with_manifests.md).

### Деплой на bare-metal (systemd)

Для production-развертывания на физических серверах или виртуальных машинах без контейнеризации используйте systemd-сервис.

**1. Скачайте бинарник:**

```bash
VICTORIA_VERSION="v1.154.0"
wget -O /tmp/victoria-metrics.tar.gz \
  "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VICTORIA_VERSION}/victoria-metrics-linux-amd64-${VICTORIA_VERSION}.tar.gz"
# → архив содержит единственный бинарник victoria-metrics-prod
tar -xzf /tmp/victoria-metrics.tar.gz -C /usr/local/bin victoria-metrics-prod
chmod +x /usr/local/bin/victoria-metrics-prod
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
ExecStart=/usr/local/bin/victoria-metrics-prod \
  -storageDataPath=/var/lib/victoria-metrics \
  -retentionPeriod=30d \
  -httpListenAddr=:8428 \
  -maxConcurrentInserts=128 \
  -search.maxQueryDuration=30s \
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

На стороне VictoriaMetrics включите дедупликацию. Значение флага должно **равняться `scrape_interval`** Prometheus (здесь `15s`), а не быть меньше его: более короткий интервал не соберёт дубли одного скрейпа.

```bash
victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -dedup.minScrapeInterval=15s
```

Дедупликация оставляет один (последний по timestamp) sample в каждом дискретном интервале. Принимаемые сэмплы при этом пишутся на диск как есть: в single-node режиме дедупликация выполняется при фоновых слияниях частей (после чего становится постоянной) и при выполнении запросов (метрики `vm_deduplicated_samples_total{type="merge"}` и `{type="select"}`). В cluster-режиме флаг задаётся **одинаково на `vmselect` и `vmstorage`** (на `vmselect` — при выполнении запросов, на `vmstorage` — при фоновом слиянии частей), чтобы результаты запросов были консистентны. Особенность cluster-режима: дедупликация не гарантируется, если дубликаты одной серии попали на разные `vmstorage`-узлы.

**Валидация HA:**

```bash
# Проверка метрики дедупликации (type="select" — при чтении, type="merge" — при слиянии)
curl -s 'http://localhost:8428/api/v1/query?query=vm_deduplicated_samples_total' | jq .
# → значения растут при параллельной записи из двух Prometheus
```

### Конфигурация vmauth (аутентификация и маршрутизация)

`vmauth` работает как обратный прокси перед `vminsert`/`vmselect`, обеспечивая аутентификацию (JWT, OIDC, Basic Auth) и маршрутизацию по путям.

**Пример базовой конфигурации `/etc/victoriametrics/vmauth.yml`:**

```yaml
unauthorized_user:
  url_map:
    # Пути /insert/* уходят на vminsert, балансировка — least-loaded round-robin
    - src_paths:
        - "/insert/.*"
      url_prefix:
        - http://vminsert1:8480
        - http://vminsert2:8480
    # Пути /select/* — на vmselect
    - src_paths:
        - "/select/.*"
      url_prefix:
        - http://vmselect1:8481
        - http://vmselect2:8481
```

Ключи конфигурации: `src_paths` — список regex-путей запроса, `url_prefix` — список backend-ов (при нескольких — балансировка), `drop_src_path_prefix_parts` — срезание префикса пути перед проксированием.

**Ограничение нагрузки:** глобально и на пользователя — одновременные запросы через `-maxConcurrentRequests` / `-maxConcurrentPerUserRequests` либо опцию `max_concurrent_requests` (лимитные запросы отклоняются с кодом `429`). Лимит на количество запросов в секунду (RPS) в vmauth отсутствует — для этого используется [vmgateway](https://docs.victoriametrics.com/vmgateway/) (Enterprise).

**Запуск vmauth:**

```bash
docker run -d \
  -p 8427:8427 \
  -v /path/to/vmauth.yml:/etc/victoriametrics/vmauth.yml \
  victoriametrics/vmauth:v1.154.0 \
  -auth.config=/etc/victoriametrics/vmauth.yml \
  -maxConcurrentRequests=1000
```

Для Enterprise-версии доступна поддержка mTLS между `vminsert`/`vmselect` и `vmauth`.

### Настройка retention и downsampling

**Retention на уровне single-node:**

```bash
victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -retentionPeriod=90d \
  -storage.minFreeDiskSpaceBytes=500GB
```

`-retentionPeriod` задаёт глубину хранения. Отдельного «лимита по занимаемому месту с принудительным удалением старых данных» в VictoriaMetrics для метрик нет: `-storage.minFreeDiskSpaceBytes` (по умолчанию `100MB`, допустимые суффиксы — `KB/MB/GB/TB/KiB/MiB/GiB/TiB`) определяет **минимум свободного места**, при достижении которого хранилище **перестаёт принимать новые данные** — это защита диска, а не инструмент ротации данных. Держите не менее 20% диска свободными, иначе деградируют компакция и чтение.

Мониторинг места:

```bash
curl -s 'http://localhost:8428/api/v1/query?query=vm_free_disk_space_bytes'
# → свободные байты на -storageDataPath
curl -s 'http://localhost:8428/api/v1/query?query=vm_free_disk_space_limit_bytes'
# → текущий порог -storage.minFreeDiskSpaceBytes
```

**Retention filters (Enterprise):**

Фильтры задаются флагом `-retentionFilter` (допускается несколько) в формате `filter:duration`, где `filter` — series filter, а `duration` ≤ значения `-retentionPeriod`. Если серия не попала ни под один фильтр — действует `-retentionPeriod`; при нескольких совпадениях берётся наименьшая retention.

```bash
victoria-metrics-enterprise \
  -storageDataPath=/var/lib/victoria-metrics \
  -retentionPeriod=1y \
  -retentionFilter='{job="short-lived"}:7d' \
  -retentionFilter='{env="prod"}:1y'
```

Данные за пределами настроенной retention удаляются не мгновенно, а постепенно при фоновых слияниях. Мониторинг — метрики `vm_retention_filters_partitions_scheduled` и `vm_retention_filters_partitions_scheduled_size_bytes`.

**Downsampling (Enterprise)** задаётся флагом `-downsampling.period` в формате `offset:period` (например, `-downsampling.period=30d:10m` — для данных старше 30 дней оставить один sample на каждые 10 минут).

### Миграция данных (vmctl)

vmctl переносит исторические данные из Prometheus (snapshot), InfluxDB, OpenTSDB, Thanos (snapshot), Mimir/Cortex (remote read) и между инстансами VictoriaMetrics. Подробные сценарии, флаги и best practices — в [`vmctl_migration.md`](./vmctl_migration.md):

```bash
# Пример: миграция между VictoriaMetrics (native mode)
vmctl vm-native \
  --vm-native-src-addr=http://source-vm:8428 \
  --vm-native-dst-addr=http://dest-vm:8428 \
  --vm-native-step-interval=month \
  -s
# → --vm-addr для VM указывается как http://host:8428/api/v1/write (single) или http://vminsert:8480 (cluster)
```

### Планирование мощностей (Capacity Planning)

**Формула оценки диска (из официальных документов):**

```
Диск = BytesPerSample × IngestionRate × ReplicationFactor × (RetentionSeconds + 1 Retention Cycle) × 1.25
```

* `BytesPerSample` — размер sample после сжатия; типично ≈ 1 байт, измеряется запросом `sum(vm_data_size_bytes) / sum(vm_rows{type!~"indexdb.*"})`. Высокий churn rate ухудшает сжатие.
* `IngestionRate` — samples/second: у VictoriaMetrics `sum(rate(vm_rows_inserted_total[24h]))`, у Prometheus `sum(rate(prometheus_tsdb_head_samples_appended_total[24h]))` (по всем инстансам суммарно).
* `Retention Cycle` — один день, если retention ≤ 30 дней, и один месяц, если больше; коэффициент `1.25` — запас ~20% под фоновые слияния (компакцию).
* `ReplicationFactor` — `1` для single-node, значение `-replicationFactor` для cluster.
* **Отдельно** закладывается индекс (IndexDB): обычно ~20% от объёма данных, при высокой кардинальности — свыше 50%.

Пример (single-node, 5 млн активных серий, scrape 15s, retention 30 дней):

```
IngestionRate = 5 000 000 / 15 ≈ 333 333 samples/s
RetentionSeconds = 30d + 1d = 2 678 400 s
Диск ≈ 1 × 333 333 × 1 × 2 678 400 × 1.25 ≈ 1,1 × 10^12 байт ≈ 1 ТБ (плюс индекс ~20%)
```

Более точный способ — **экстраполяция тестового прогона**: если при продовой нагрузке каталог `-storageDataPath` занял 10 ГБ за сутки, то для `-retentionPeriod=100d` потребуется не менее `10 ГБ × 100 = 1 ТБ`.

**Оценка RAM (память на метаданные):** память у storage растёт от кардинальности серий/меток, а не от объёма диска. Ориентир — ~100 тыс. – 1 млн серий на ~1 ГБ RAM storage-узла; метод подбора и метрики диагностики описаны в [storage_internals.md: RAM и диск](./storage_internals.md#оценка-ресурсов-ram-и-диск). Для точного прогноза — [vmestimator](./vmestimator.md), до боевой нагрузки — прямое наблюдение `/api/v1/status/tsdb`.

**Для cluster-режима:**

1. Тот же расчёт умножается на `-replicationFactor` и делится на число `vmstorage`-шардов.
2. Ёмкость масштабируется линейно; практический подход — тестовый кластер (см. [рекомендации по кластеру](#общие-рекомендации-для-cluster)), затем экстраполяция диска по тестовому прогону.
3. Пример: 10 млн активных серий, scrape 15s, retention 90 дней, `-replicationFactor=2`, 3 узла `vmstorage`:

```
IngestionRate = 10 000 000 / 15 ≈ 667 000 samples/s
RetentionSeconds = 90d + 30d (месячный цикл) = 10 368 000 s
Диск всего ≈ 1 × 667 000 × 2 × 10 368 000 × 1.25 ≈ 1,7 × 10^13 байт ≈ 15,7 ТиБ
≈ 5,2 ТиБ на узел (плюс индекс ~20%)
```

4. На `vmselect` выделяйте не менее 10 ГБ диска под локальные кэши; на `vminsert` — около 2 GiB RAM на 1 vCPU.

### Сравнение с альтернативами

| Характеристика | VictoriaMetrics | Thanos | Grafana Mimir (v3.x) |
| :--- | :--- | :--- | :--- |
| **Сложность** | Низкая (единый стек) | Высокая (много компонентов) | Средняя |
| **Хранилище** | Локальные диски / EBS / Flash | Объектное (S3/GCS) | Объектное (S3/GCS) |
| **Сжатие данных** | Экстремальное | Среднее (через Downsampling) | Высокое |
| **Интеграция** | `remote_write` (PRW 1.0), OTLP | Sidecar / Receiver | `remote_write` |
| **Типы данных** | Метрики, Логи, Трейсы | Метрики | Метрики |
| **Алертинг/аналитика** | vmalert, vmanomaly (Enterprise), vmui | Thanos Ruler | Grafana Machine Learning |
| **On-prem готовность** | Нативная (единый бинарник) | Требует объектное хранилище | Требует объектное хранилище |

#### InfluxDB и TimescaleDB

Вне прямого сравнения с TSDB промetheus-типа стоят два других класса хранилищ временных рядов:

| Характеристика | VictoriaMetrics | InfluxDB | TimescaleDB |
| :--- | :--- | :--- | :--- |
| **Модель** | Специализированный TSDB для метрик | Специализированный TSDB для событий/apsm | Расширение PostgreSQL |
| **Open-source кластер/HA** | Да (vminsert/vmselect/vmstorage из коробки) | Нет: кластеризация — Enterprise/Cloud (коммерческие); OSS-версии single-node | Streaming replication PostgreSQL; автоматический failover — вне коробки (Patroni) |
| **Язык запросов** | MetricsQL | SQL (3.x), Flux (2.x), InfluxQL | SQL + JOIN, гипертаблицы, непрерывные агрегаты |
| **Сбор метрик** | vmagent, Remote Write, line protocol на `/influx/write` | Свой протокол / Telegraf | Витрины и пайплайны внутри PostgreSQL |
| **Когда выбирать** | Метрики Prometheus-типа, высокая кардинальность, дешёвое хранение, единый стек | Событийные/apsm-ряды, когда экосистема уже на Flux/SQL/Telegraf | Данные живут в PostgreSQL и нужны SQL-JOIN и транзакции |

- **Лицензия TimescaleDB:** ядро Apache 2 (пакет `timescaledb-2-oss`), расширенная Community-редакция — под TSL (Tiger Data License): [TimescaleDB: редакции](../Databases/timescaledb.md#определения).
- **Репликация TimescaleDB** — встроенный streaming replication PostgreSQL; logical replication с TimescaleDB официально не рекомендуется, автоматического failover из коробки нет (патронится Patroni): [Tiger Data Docs: About high availability](https://docs.timescale.com/docs/deploy/self-hosted/replication-and-ha/about-ha).
- **Миграция в VictoriaMetrics:** `vmctl influx` умеет импортировать данные InfluxDB v1, а endpoint `/influx/write` принимает InfluxDB line protocol напрямую: [vmctl: миграция](./vmctl_migration.md), [vmagent: приём данных по push-протоколам](./vmagent_overview.md#4-приём-данных-по-push-протоколам).

## Поиск и устранение неисправностей (Troubleshooting)

### Single-node

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `vm_rows_inserted_total` не растет | Неправильный URL `remote_write` или блокировка firewall | Проверить URL, сетевую доступность и логи vmagent/Prometheus |
| Данные не появляются после записи | Не применен `Content-Encoding: snappy` или ошибка в формате | Использовать snappy-сжатие; проверить `/api/v1/write` на 204 |
| Медленные запросы | Недостаток IOPS или слишком широкий временной диапазон | Проверить `vm_slow_queries_total`, увеличить `-search.maxQueryDuration`, сузить селекторы |
| `read-only` режим | Свободного места меньше `-storage.minFreeDiskSpaceBytes` или файловая система переведена в READ-ONLY | Проверить `df -h` и метрику `vm_free_disk_space_bytes`, освободить место/снизить retention; очистить только после устранения причины |
| Высокое потребление RAM | Взрыв кардинальности или слишком большой `-search.maxQueryDuration` | Проверить число активных серий (`/api/v1/status/tsdb`, поле `totalSeries`; приближение — `vm_cache_entries{type="storage/hour_metric_ids"}`), настроить `relabel_configs` для удаления динамических лейблов |
| Потеря данных при перезагрузке | vmagent отключил on-disk queue (`-remoteWrite.disableOnDiskQueue`) либо очередь переполнена и старые данные вытеснены | Оставить queue включённым (дефолт, путь `-remoteWrite.tmpDataPath`), ограничить объём через `-remoteWrite.maxDiskUsagePerURL`, наблюдать `vmagent_remotewrite_pending_data_bytes` |
| Ошибка дедупликации | `-dedup.minScrapeInterval` не установлен или задан короче scrape interval | Установить флаг **равным** `scrape_interval` (например `15s`); проверять рост `vm_deduplicated_samples_total` |

### Cluster-режим

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `rate(vm_rows_ignored_total[5m]) > 0` (данные отбрасываются при приёме) | Превышен лимит одновременных вставок (`-maxConcurrentInserts`), невалидные timestamps, недоступный `vmstorage` | Проверить логи `vminsert`, доступность `vmstorage`, очередь вставок; масштабировать `vminsert`/`vmstorage` |
| Ошибки связи `vminsert` ↔ `vmstorage` | `vmstorage` недоступен/перегружен, сетевые таймауты | Смотреть `vm_rpc_dial_errors_total`, `vm_rpc_connection_errors_total`, `vm_rpc_vmstorage_is_reachable`, логи `vminsert`; увеличить число узлов |
| Медленные запросы в кластере | Неравномерная нагрузка, недостаточно `vmselect` или тяжёлые запросы | Проверить `/api/v1/status/active_queries` (независимый список на каждом `vmselect`), добавить `vmselect`, настроить балансировку в `vmauth` |
| Данные не реплицируются между `vmstorage` | `-replicationFactor` ≤ 1, неверный `-storageNode`, сетевые таймауты | Проверить логи `vmstorage`/`vminsert` на ошибки репликации, актуальность списка `-storageNode`, связность узлов; `-replicationFactor` должен быть ≥ 2 |
| `vmstorage` переходит в READ-ONLY | Диск заполнен или файловая система повреждена | Проверить `df -h`, логи `vmstorage`; восстановить из бэкапа |
| Медленная загрузка данных (ingestion lag) | Недостаточно `vminsert` или узлов `vmstorage` | Масштабировать `vminsert` горизонтально; проверить `vm_rows_inserted_total` |
| Ошибки аутентификации в `vmauth` | Неверные JWT/OIDC настройки или истекший токен | Проверить конфигурацию `vmauth.yml`, логи `vmauth` |

## Рекомендации по эксплуатации и очистке (Best Practices & Cleanup)

### Resource Limits и планирование

- **Устанавливайте `LimitNOFILE`** в systemd-сервисе не менее 65535 для single-node и 200000+ для cluster-компонентов (пример unit выше использует `LimitNOFILE=200000`).
- **Ограничьте `-search.maxQueryDuration`** (например, 30s для single-node, 60s для cluster), чтобы предотвратить долгие запросы, блокирующие компакцию.
- **Используйте `-maxConcurrentInserts`** для ограничения параллельных вставок (дефолт — `2 × число CPU cores`; в slow-сетях значение можно увеличить, очередь вставок живёт `-insert.maxQueueDuration`, по умолчанию `1m`). Флаг есть и у single-node, и у `vminsert`.
- **Мониторьте `vm_parts`** на `vmstorage`: устойчивый рост числа частей при стабильной нагрузке указывает на нехватку IOPS — данные не успевают компактироваться, запросы замедляются.

### Retention и управление данными

- **Начинайте с `-retentionPeriod=30d`** для dev-окружений и `90d–1y` для production. Дольше 2 лет — рассматривать downsampling (Enterprise).
- **Следите за свободным местом:** держите не менее 20% диска свободными; жёсткий порог, ниже которого хранилище перестаёт принимать данные, — `-storage.minFreeDiskSpaceBytes` (метрики `vm_free_disk_space_bytes` и `vm_free_disk_space_limit_bytes`).
- **Настраивайте алерты на диск** на данные node-exporter, например `node_filesystem_avail_bytes{mountpoint="/var/lib/victoria-metrics"} / node_filesystem_size_bytes{mountpoint="/var/lib/victoria-metrics"} < 0.2` за 10 минут; сам VM не экспортирует `disk_usage_percent`.
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

# 3. Обновите бинарник (VICTORIA_VERSION задан на шаге 1, например v1.154.0)
wget -O /tmp/victoria-metrics.tar.gz \
  "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VICTORIA_VERSION}/victoria-metrics-linux-amd64-${VICTORIA_VERSION}.tar.gz"
tar -xzf /tmp/victoria-metrics.tar.gz -C /usr/local/bin victoria-metrics-prod
chmod +x /usr/local/bin/victoria-metrics-prod

# 4. Запустите
systemctl start victoria-metrics

# 5. Проверьте
curl -s http://localhost:8428/health
```

**Важно:** обновление безопасно (в том числе с пропуском нескольких версий, например v1.136.x → v1.154.x) и не требует миграции данных на диске, **если release notes не указывают иное**; безопасен и откат на более старую версию по тем же правилам. Перед обновлением проверяйте [релизные заметки](https://docs.victoriametrics.com/lts-releases/) на breaking changes. Корректная остановка — сигналом `SIGTERM` или `SIGINT` и ожидание завершения процесса (`systemctl stop` укладывается в эту схему).

### Очистка окружения

- **Удалите неиспользуемые метрики:** в Prometheus — `write_relabel_configs`; в vmagent — `metric_relabel_configs` в scrape-конфиге либо глобальный relabeling перед отправкой через флаг `-remoteWrite.relabelConfig` (у самого vmagent `write_relabel_configs` нет).
- **Проверяйте `vm_rows_ignored_total`** — если его rate больше нуля, данные отбрасываются при приёме (невалидные timestamps, превышение лимитов); причины также видны в логах vminsert/vmsingle.
- **При удалении инстанса:** убедитесь, что все `vmstorage` узлы остановлены, прежде чем удалять данные, чтобы избежать corruption.

## Ограничения и особые случаи (Edge Cases & Limitations)

### Кардинальность

- **Практический предел single-node:** по FAQ — до **100 млн активных временных рядов** и до **2 млн samples/s** (по данным реальной эксплуатации). В кейсах задокументирована продовая нагрузка: 1,5+ млн samples/s, 50+ млн активных серий, 150+ млн новых серий в сутки, 200+ qps. При превышении порогов или неприемлемом вертикальном масштабе — переходите в cluster-режим (масштабируется до миллиардов активных серий).
- **Взрыв кардинальности:** если в лейблы попадают уникальные значения (request_id, IP клиентов), RAM может быть исчерпана за минуты. Используйте `relabel_configs` для удаления динамических лейблов на этапе сбора.
- **Native Histograms:** принимаются при приёме с v1.143.0 (vmagent, vmsingle, `vminsert`) и конвертируются в серии `_count`/`_sum`/`_bucket` с `vmrange`-лейблами — то есть хранятся как обычные временные ряды и читаются стандартными функциями гистограмм (`histogram_quantile`, `histogram_over_time`, `histogram_avg` и др.).

### Диск и WAL

- **Буферизация вместо WAL:** у VictoriaMetrics нет write-ahead log. Принятые данные держатся в памяти и сбрасываются на диск с интервалом `-inmemoryDataFlushInterval` (минимум `1s`, по умолчанию `5s`) в виде `part`-каталогов под `<-storageDataPath>/data/small/YYYY_MM/`. Сброс переживает нечистое завершение (OOM, `kill -9`, сброс питания), но последние секунды данных при таком завершении теряются; то же поведение у `vmstorage` в cluster-режиме. Вручную принудительно сбросить буфер можно хендлером `/internal/force_flush`. Не удаляйте каталоги данных при остановленном сервисе.
- **Shared-Nothing:** в cluster-режиме каждый `vmstorage` независим. Не монтируйте общие диски (NFS, CIFS) для `-storageDataPath` — это приведет к corruption.
- **Компакция (compaction):** фоновый процесс, требующий IOPS. При недостатке IOPS число `parts` растет, и запросы замедляются. Мониторьте `vm_parts` на `vmstorage`.

### Сеть

- **Remote Write таймауты:** при высокой латентности между scrapers и VictoriaMetrics увеличьте `remoteTimeout` в Prometheus (по умолчанию 30s); на стороне агента пережить медленный приём помогает persistent queue vmagent. `-search.maxQueryDuration` к пути записи не относится — он ограничивает длительность запросов.
- **Принятие данных в cluster:** `vminsert` шардирует и пересылает данные в `vmstorage`, которые держат их в памяти до периодического сброса на диск (`-inmemoryDataFlushInterval`, по умолчанию `5s`). Нечистое завершение `vmstorage` теряет последние секунды данных, а при дефолтном `-replicationFactor=1` резервной копии нет. Для критичных сценариев используйте `-replicationFactor≥2` (в паре с дедупликацией на `vmselect`) и persistent queue в vmagent.
- **Дублирование при HA и репликации:** см. раздел [Высокая доступность (HA) для single-node](#высокая-доступность-ha-для-single-node). При `-replicationFactor>1` документация рекомендует начинать с `-dedup.minScrapeInterval=1ms` на `vmselect` (копии сэмплов идентичны по timestamp); значение, равное `scrape_interval`, дополнительно убирает дубли от HA-пар Prometheus.

### Ограничения версий

- **Enterprise-функции недоступны в Community:** downsampling (`-downsampling.period`), retention filters (`-retentionFilter`), per-tenant статистика, multitenancy в vmalert, Anomaly Detection (vmanomaly), mTLS между компонентами, vmgateway. Streaming aggregation при этом **доступна в Community**: флаги `-streamAggr.*` входят в список общих флагов.
- **Prometheus Remote Write 2.0 не реализован:** PRW 2.0 остаётся экспериментальным в самом Prometheus и не поддерживается VictoriaMetrics (так заявлено в официальной документации). Для интеграций используйте PRW 1.0, OTLP или OpenMetrics/text.
- **MetricsQL vs PromQL:** базовые PromQL-запросы выполняются без изменений, но 100% идентичности нет — MetricsQL намеренно исправляет отдельные поведения PromQL (см. [FAQ](https://docs.victoriametrics.com/victoriametrics/faq/#why-isnt-metricsql-100-compatible-with-promql)). Перенос нетривиальных запросов из Prometheus проверяйте на продовых данных.
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