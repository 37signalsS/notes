# Thanos: Глобальное масштабирование и долгосрочное хранение

Thanos — это высокомасштабируемая система сбора и хранения метрик, которая превращает локальные инстансы Prometheus в единое глобальное облако данных с практически неограниченным сроком хранения.

## Определения

Thanos решает три фундаментальные проблемы классического Prometheus:
1.  **Retention (Хранение):** Локальная TSDB не предназначена для хранения петабайт данных годами. Thanos выгружает данные в дешевые объектные хранилища (S3).
2.  **Global View (Единое окно):** Позволяет выполнять PromQL-запросы сразу по всем кластерам из одной точки (Grafana), дедуплицируя данные от HA-пар.
3.  **Horizontal Scalability (Масштабируемость):** Разделяет функции сбора (Sidecar/Receive) и выполнения запросов (Query), позволяя масштабировать их независимо.

## Базовые концепции

### Когда требуется Thanos: количественные пороги

Решение о внедрении Thanos должно приниматься на основе метрик, а не интуиции:

| Показатель | Зона комфорта | Предупреждение | Критический режим | Действие |
|---|---|---|---|---|
| **Количество Prometheus-инстансов** | 1–5 | 5–20 | > 20 | Рассмотреть Thanos или LTS |
| **Retention требования** | < 30 дней | 30–90 дней | > 90 дней | Thanos или VictoriaMetrics |
| **Размер данных на диске** | < 500 ГБ | 500 ГБ–2 ТБ | > 2 ТБ | Переход на объектное хранилище |
| **Глобальный обзор** | Один ДЦ | 2–5 ДЦ | > 5 ДЦ | Thanos Query как единая точка входа |

### Компоненты системы (Архитектура 2025–2026)

| Компонент | Назначение | Ключевые функции и особенности |
|---|---|---|
| **Sidecar** | Прокси для Prometheus | Выгружает TSDB-блоки в S3 каждые 2ч; проксирует gRPC-запросы от Query к локальной памяти Prometheus. |
| **Store Gateway** | Шлюз к S3 | Позволяет Query запрашивать исторические данные из объектного хранилища. Использует агрессивное кэширование индексов. |
| **Query** | Агрегатор (Querier) | Точка входа для PromQL. Собирает данные со всех Store API (Sidecars + Store Gateways), дедуплицирует ряды. |
| **Query Frontend** | Оптимизатор запросов | Разбивает тяжелые запросы на мелкие куски (split-by-day), кэширует результаты в Redis/Memcached. |
| **Compactor** | Санитар хранилища | Выполняет **downsampling** (понижение дискретизации), слияние мелких блоков и удаление данных по retention. |
| **Receiver** | Ingestor (Push-модель) | Принимает метрики по Remote Write. Используется для мульти-тенантности и в изолированных сетях. Поддерживает OTLP. |
| **Ruler** | Глобальные правила | Выполняет Recording и Alerting rules поверх данных в Thanos Query (агрегированные алерты). |

### Механизмы оптимизации и производительности

#### 1. Индексное кэширование (Index Caching)
Store Gateway тратит основное время на поиск рядов внутри блоков в S3.
- **In-memory:** Быстро, но кэш теряется при рестарте («холодный старт»).
- **Redis/Memcached (Рекомендуется):** Позволяет делить кэш между всеми репликами Store Gateway. Ускоряет чтение исторических данных (>30 дней) в 5–10 раз.

#### 2. Query Pushdown и Streaming
Механизм, при котором фильтрация по лейблам и часть вычислений передается от `Query` вниз к `Store Gateway` или `Sidecar`. В новых версиях (v0.40+) улучшен протокол стриминга, что снижает потребление RAM при обработке тяжелых выборок.

#### 3. Downsampling (Понижение дискретизации)
Compactor создает агрегированные копии данных:
- **5m resolution:** Для запросов за период 1–30 дней.
- **1h resolution:** Для запросов >30 дней.
Это позволяет строить графики за 1 год за доли секунды, считывая в 60 раз меньше точек по сравнению с сырыми данными (raw data).

### Thanos Ruler: глобальные правила

В распределенных архитектурах локальный Alertmanager обрабатывает алерты только в рамках одного ДЦ. **Thanos Ruler** решает эту проблему:

- **Запись глобальных метрик:** Создание recording rules, агрегирующих данные со всех кластеров (например, `sum(rate(http_requests_total[5m])) by (cluster)`).
- **Глобальные алерты:** Один инстанс Ruler может обрабатывать алерты для всех ДЦ, отправляя их в центральный Alertmanager.
- **Координация с `query_offset`:** В Prometheus >= v2.53.0 поддерживается `query_offset`, который смещает окно вычисления правил в прошлое, компенсируя задержку загрузки данных из S3.

### Внутренние механизмы Store Gateway

Store Gateway — самый ресурсоемкий компонент при работе с историческими данными:

1. **Block Streaming:** При запросе Thanos Query открывает gRPC-стрим к Store Gateway. Данные передаются чанками, не загружая весь блок в память.
2. **Поиск по индексу:** Для каждого запроса Store Gateway читает индекс чанка (`index`), определяет, какие серии соответствуют селектору, и только затем читает сами чанки. Это снижает I/O в 10–100 раз.
3. **Кэширование индексов:** In-memory кэш теряется при рестарте. Для продакшна рекомендуется Redis/Memcached.

### Внутренние механизмы Compactor

Compactor работает в фоне и выполняет три критичные операции:

1. **Downsampling:** Создание агрегированных копий данных (5m и 1h resolution). Процесс запускается автоматически при накоплении достаточного объема сырых данных (>30 дней).
2. **Слияние блоков (Compact):** Мелкие блоки (2ч) объединяются в крупные (обычно 24ч). Это уменьшает количество файлов в S3 и ускоряет чтение.
3. **Удаление данных (Retention):** Удаление блоков, превышающих настроенный срок хранения. Важно: retention в Thanos — это retention в S3, а не в локальной TSDB.

## Практические сценарии

### Сценарий 1: Глобальный HA-кластер (Sidecar-модель)

Классический путь для инфраструктуры в нескольких дата-центрах.

1.  **Сбор:** В каждом ДЦ установлена пара Prometheus (HA-пара) с `thanos-sidecar`.
2.  **Дедупликация:** В конфигурации Query указывается `replica-label` (например, `prometheus_replica`). Query сравнивает ряды с одинаковыми метками и разным `replica-label`, отдавая пользователю чистый поток.
3.  **Хранение:** Sidecar выгружает данные в S3. Compactor в центральном кластере оптимизирует блоки.

**Пример конфигурации Prometheus Operator (CRD) для версии 3.9+:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: k8s-prometheus
spec:
  replicas: 2
  thanos:
    version: v0.41.0
    objectStorageConfig:
      key: thanos.yaml
      name: thanos-objstore-config
  externalLabels:
    cluster: "prod-europe-1"
    prometheus_replica: "$(POD_NAME)"
  # Для Prometheus 3.9+ компакция TSDB координируется с Thanos автоматически
```

### Сценарий 2: Мульти-тенантность и Thanos Receive

Используется, когда нижестоящие кластеры не могут быть опрошены сверху (например, за NAT) или при необходимости Push-модели.

1.  **Центральный кластер:** Развертывание `Thanos Receive` (Ingestor + Router).
2.  **Изоляция:** Данные отправляются с HTTP-заголовком `THANOS-TENANT`. Receiver раскладывает их по независимым префиксам в S3.
3.  **Отказоустойчивость:** Поддерживается репликация данных между узлами Receiver (Quorum-based write), что предотвращает потерю данных до их выгрузки в S3.

### Сценарий 3: Жизненный цикл данных (Lifecycle)

Thanos удаляет данные через Compactor, но рекомендуется дополнять это политиками объектного хранилища (S3 Lifecycle).

- **Raw data:** Перенос в холодное хранилище (Standard-IA/Archive) через 90 дней.
- **Downsampled data:** Хранение в стандартном классе бессрочно (занимает минимум места).
- **Abort Incomplete Multipart Uploads:** Очистка через 7 дней для экономии средств при сбоях загрузки.

### Сценарий 4: Capacity Planning — оценка объема федеративной архитектуры

Пошаговая процедура оценки необходимых ресурсов для архитектуры Thanos.

**Шаг 1. Сбор базовых метрик в течение 7 дней:**
```promql
# Объем данных, выгружаемых в S3 ежедневно (байты)
sum(rate(prometheus_tsdb_blocks_loaded_total[1d])) 

# Количество активных серий на инстанс
prometheus_tsdb_head_series

# Размер одного блока TSDB (средний)
avg(prometheus_tsdb_block_size_bytes)
```

**Шаг 2. Оценка ресурсов:**
- **S3 Storage:** Оценить прирост TSDB за неделю × retention. Например, 50 ГБ/неделя × 90 дней = 450 ГБ.
- **Store Gateway RAM:** ~1 ГБ на каждые 1M серий + 4 ГБ базовый overhead для кэша индексов.
- **Compactor CPU:** 2–4 ядра на кластер при объеме >1 ТБ. Основная нагрузка — на downsampling и compact.
- **Query RAM:** Зависит от количества параллельных запросов. Для 100 пользователей ~8–16 ГБ.

**Шаг 3. Прогноз на 12 месяцев:**
При росте кардинальности 20%/мес через год потребуется удвоение ресурсов Store Gateway или введение дополнительного уровня кэширования (Redis cluster).

### Сценарий 5: Миграция с single-instance на Thanos

Поэтапный переход без простояя мониторинга.

**Этап 1. Подготовка инфраструктуры:**
Развернуть MinIO/S3, Thanos Sidecar и Store Gateway в параллель с существующим Prometheus.

**Этап 2. Включение Sidecar:**
Добавить `thanos-sidecar` в Deployment/StatefulSet Prometheus. Sidecar начнет выгружать блоки в S3 по мере их закрытия (каждые 2ч).

**Этап 3. Проверка целостности данных:**
Сравнить количество серий в Grafana между локальным Prometheus и Thanos Query. Убедиться, что `up` и ключевые метрики совпадают.

**Этап 4. Переключение Grafana:**
Изменить источник данных (Data Source) на Thanos Query. Проверить, что графики строятся корректно.

**Этап 5. Снижение retention локального Prometheus:**
Уменьшить `--storage.tsdb.retention.time` до 7–14 дней. Данные старше этого срока будут доступны только через Thanos.

## Безопасность и эксплуатация

### Сетевая безопасность (mTLS и Auth)

Обмен данными по gRPC между Query, Store и Sidecar должен быть защищен.

**Вариант 1: mTLS через файловые сертификаты**
```bash
# Генерация сертификатов (с использованием openssl или cert-manager)
thanos sidecar \
  --grpc-client-tls-ca-file=/etc/thanos/ca.crt \
  --grpc-client-tls-cert-file=/etc/thanos/client.crt \
  --grpc-client-tls-key-file=/etc/thanos/client.key \
  --grpc-client-tls-server-name=thanos-store
```

**Вариант 2: mTLS в Kubernetes через Service Mesh**
Использование Istio/Linkerd обеспечивает mTLS прозрачно для компонентов. Достаточно аннотировать сервисы:
```yaml
annotations:
  sidecar.istio.io/inject: "true"
```

**Вариант 3: Аутентификация в S3**
Настройка доступа к объектному хранилищу через:
- **Static credentials:** `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` в Secret.
- **IAM Role:** В Kubernetes через ServiceAccount + IRSA (Amazon EKS) или Workload Identity (Google GKE).
- **MinIO:** Статический ключ доступа, ограниченный правами bucket.

### Управление доступом к Thanos Query

Thanos Query — это точка входа для всех запросов. Рекомендации:
- **Ограничение сетевого доступа:** Разрешить подключения только с IP-адресов Grafana и CI/CD систем.
- **Базовая аутентификация:** Использовать反向-прокси (nginx) с basic auth или OAuth2 перед Thanos Query.
- **Разделение tenant-доступа:** В архитектуре с Thanos Receive использовать разные `THANOS-TENANT` для команд/проектов.

### Устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
|---|---|---|
| **Compactor Halted** | Конфликт или перекрытие (overlap) блоков в S3 | Проверить логи компактора. Часто возникает при смене `external_labels` без очистки старых данных. |
| **Slow Queries** | Холодный кэш индексов или отсутствие Downsampling | Проверить `index_cache_hit_ratio`. Убедиться, что Compactor работает и созданы блоки 1h. |
| **Sidecar Upload Lag** | Проблемы с сетью или лимиты API S3 | Проверить метрику `thanos_sidecar_last_heartbeat_success_time_seconds`. |
| **Query Fan-out Timeout** | Один из Sidecar недоступен или тормозит | Настроить агрессивные таймауты в Query и проверить доступность gRPC порта 10901. |
| **Дубликаты рядов в Grafana** | Отсутствует `replica-label` или не настроен Query | Проверить конфигурацию `--query.replica-label` в Thanos Query. |
| **Высокое потребление RAM Store Gateway** | Отсутствует кэш индексов или слишком много серий | Настроить Redis/Memcached. Увеличить лимит памяти до 1 ГБ на 1M серий. |
| **Compaction Stall** | Недостаточно CPU/Disk IO при большом объеме данных | Увеличить ресурсы Compactor. Проверить фрагментацию диска. |
| **Потеря данных при Sidecar Upload** | Переполнение очереди или недоступность S3 | Проверить `thanos_sidecar_last_successful_upload_timestamp`. Увеличить `--objstore.*.upload-timeout`. |

### Тюнинг производительности

**Store Gateway:**
- **Кэш индексов:** Redis/Memcached ускоряет повторные запросы в 5–10 раз.
- **Параллелизм:** Флаг `--store.gateway.index-cache-size` управляет размером кэша. Для >30 дней истории рекомендуется >2 ГБ.
- **Grpc Streaming:** Убедиться, что используется протокол стриминга (по умолчанию в v0.40+).

**Query:**
- **Максимальная параллельность:** `--query.max-concurrency` (default: 20). Для heavy workloads увеличить до 50–100.
- **Таймаут:** `--query.timeout` (default: 5m). Для запросов по >1 года данных установить 10–15m.
- **Auto-downsampling:** Query автоматически использует 5m/1h блоки при запросе больших периодов.

**Compactor:**
- **Upload конкуренция:** `--compactor.concurrency` (default: 4). Увеличить до 8–16 при быстром хранилище.
- **Retention:** `--compactor.retention.resolution-raw`, `--compactor.retention.resolution-5m`, `--compactor.retention.resolution-1h`.

### Мониторинг и метрики (Thanos Mixin)
Используйте [Thanos Mixin](https://github.com/thanos-io/thanos/tree/main/mixin) для получения стандартных алертов и дашбордов.

**Ключевые метрики для мониторинга:**
```promql
# Эффективность кэша индексов Store Gateway
thanos_store_gateway_index_cache_hit_ratio_total

# Критический алерт: сжатие данных остановлено
thanos_compactor_halted

# Задержка выгрузки данных Sidecar (секунды)
time() - thanos_sidecar_last_successful_upload_timestamp

# Размер очереди Remote Write в Receiver
thanos_receive_queue_length

# Задержка между последним скрейпом и отправкой в Receive
thanos_receive_head_samples_lag
```

### Конфигурационные примеры

**Пример 1: Thanos Sidecar (standalone)**
```yaml
# prometheus.yml — настройка sidecar
thanos:
  image: quay.io/thanos/thanos:v0.41.0
  version: v0.41.0
  objectStorageConfig:
    key: thanos.yaml
    name: thanos-objstore-config
  externalLabels:
    cluster: "prod-europe-1"
```

**Пример 2: Thanos Query (единая точка входа)**
```bash
thanos query \
  --store=thanos-sidecar-dc1.prod:10901 \
  --store=thanos-sidecar-dc2.prod:10901 \
  --store=thanos-store-gateway:10901 \
  --grpc-address=0.0.0.0:10901 \
  --http-address=0.0.0.0:9090 \
  --replica-label=prometheus_replica
```

**Пример 3: Thanos Compactor**
```bash
thanos compact \
  --data-dir=/var/thanos/compact \
  --objstore.config-file=/etc/thanos/objstore.yml \
  --retention.resolution-raw=30d \
  --retention.resolution-5m=1y \
  --retention.resolution-1h=2y \
  --compact-concurrency=8
```

**Пример 4: Thanos Store Gateway**
```bash
thanos store \
  --data-dir=/var/thanos/store \
  --objstore.config-file=/etc/thanos/objstore.yml \
  --index-cache-size=2GB \
  --grpc-address=0.0.0.0:10901
```

## Дополнительная информация

### Поддерживаемые объектные хранилища
- **S3-совместимые:** MinIO, Ceph RGW, SeaweedFS, Garage.
- **POSIX-совместимые:** Локальная файловая система (для тестирования), NFS (не рекомендуется для продакшна из-за латентности).
- **OpenStack Swift:** Для инфраструктур на базе OpenStack.

### Сравнение с альтернативами

| Функция | Thanos | VictoriaMetrics | Grafana Mimir |
|---|---|---|---|
| **Сложность** | Средняя (Sidecar-модель) | Низкая (единый бинарник) | Высокая (микросервисы) |
| **Хранилище** | S3-совместимое / POSIX | Локальный диск или S3 | S3-совместимое / POSIX |
| **Производительность** | Хорошая (при кэшировании) | Экстремальная | Очень высокая |
| **Мульти-тенантность** | Через Receiver | Нативная | Нативная |

### Граничные случаи и ограничения

**Thanos Sidecar:**
- **Локальная TSDB retention:** Sidecar не расширяет хранение локально. Если S3 недоступен, данные теряются по истечении локального retention (обычно несколько часов).
- **Совместимость версий:** Sidecar и Store Gateway должны иметь одинаковую major версию Thanos. Не рекомендуется смешивать v0.30 и v0.40 в одном кластере.
- **Сеть:** Sidecar требует постоянного исходящего доступа к S3. В air-gapped сетях используйте Thanos Receive.

**Thanos Query:**
- **Fan-out:** Запрос к 50 Sidecar одновременно создает 50 gRPC-соединений. Для >100 инстансов используйте Query Frontend для кэширования.
- **Дедупликация:** Требует корректной настройки `replica-label`. При отсутствии этой настройки Grafana покажет дубликаты рядов.

**Compactor:**
- **Повреждение данных:** При сбое во время compact может образоваться битый блок. Thanos автоматически пропускает блоки с неверной контрольной суммой.
- **Смена external_labels:** При изменении `external_labels` старые блоки становятся "чужими" для нового кластера. Требуется ручная очистка S3 перед запуском Compactor.

**Store Gateway:**
- **Холодный старт:** При рестарте индексный кэш пуст. Первые запросы к >30-дневной истории будут медленными в течение 10–30 минут.
- **Ограничение параллелизма:** Store Gateway обрабатывает запросы в несколько потоков. При высокой нагрузке увеличьте `--store.gateway.index-cache-size` и `--store.gateway.grpc-max-recv-msg-size`.

### Рекомендации по эксплуатации (2025–2026)

1. **Используйте S3-совместимые хранилища:** MinIO для on-prem, Ceph RGW для масштабных инфраструктур.
2. **Настройте S3 Lifecycle:** Автоматический переход в холодное хранение через 90 дней.
3. **Разделяйте компоненты:** Не запускайте Compactor и Query на одном хосте. Compactor создает пиковую нагрузку на диск и CPU.
4. **Мониторьте кэш Store Gateway:** `thanos_store_gateway_index_cache_hit_ratio` должен быть >0.7. При меньшем значении увеличьте размер кэша.
5. **Тестируйте восстановление:** Регулярно проверяйте восстановление данных из S3 после удаления локального Prometheus.

### См. также
*   [Масштабирование Prometheus (обзор)](./overview.md)
*   [VictoriaMetrics — обзор](../../VictoriaMetrics/overview.md)
*   [Grafana Mimir — обзор](../../Mimir/mimir_overview.md)
