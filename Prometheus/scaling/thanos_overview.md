# Thanos

> Thanos — надстройка над Prometheus для долгосрочного хранения, глобального обзора и высокой доступности. Использует sidecar-архитектуру и объектные хранилища (S3).
>
> **См. также:** [TSDB](../concepts/tsdb.md), [Remote Read/Write](./remote_read_write.md), [Масштабирование Prometheus](./overview.md).

## Определения

**Thanos** — проект CNCF, расширяющий Prometheus возможностями практически неограниченного хранения метрик и глобального выполнения запросов. Решает архитектурные ограничения Prometheus: отсутствие встроенного долгосрочного хранения и горизонтального масштабирования.

| Возможность | Описание |
|---|---|
| **Глобальный обзор** | Запросы к данным со всех экземпляров Prometheus из единой точки |
| **Долгосрочное хранение** | Интеграция с S3-совместимыми объектными хранилищами (MinIO, Ceph, Yandex Object Storage) |
| **Высокая доступность** | Дедупликация HA-пар Prometheus, устойчивость к сбоям отдельных компонентов |

## Основные концепции

### Компоненты Thanos

| Компонент | Назначение | Ключевые функции |
|---|---|---|
| **Sidecar** | Сопроводительный процесс для каждого Prometheus | Загрузка TSDB-блоков в Object Storage (каждые 2ч); предоставление свежих данных (~2ч) для Query |
| **Query** | Центральная точка входа для PromQL-запросов | Агрегация данных из Sidecar и Store Gateway; дедупликация HA-пар; Prometheus-compatible API |
| **Store Gateway** | Шлюз к историческим данным в Object Storage | Store API для Query; интеллектуальное кэширование метаданных |
| **Ruler** | Глобальные recording/alerting rules | Выполнение правил поверх данных всех кластеров через Query; отправка алертов в Alertmanager |
| **Compactor** | Фоновая оптимизация данных в Object Storage | Сжатие блоков, downsampling, постоянная дедупликация HA-пар |
| **Query Frontend** | Опциональный ускоритель запросов | Кэширование результатов; разбиение больших запросов на мелкие |

### Поддерживаемые Object Storage

Thanos Sidecar выгружает данные в S3-совместимые хранилища:

| Хранилище | Тип | Примечание |
|---|---|---|
| **Amazon S3** | Облачное | Нативная поддержка |
| **MinIO** | On-premise / self-hosted | S3-совместимое |
| **Ceph (RGW)** | On-premise | S3-совместимое |
| **Yandex Object Storage** | Облачное | S3-совместимое |
| **OpenStack Swift** | On-premise | |
| **Azure Blob Storage** | Облачное | |
| **Google Cloud Storage** | Облачное | |

### Пример конфигурации Thanos Sidecar

```yaml
# thanos-sidecar.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus-with-thanos
spec:
  template:
    spec:
      containers:
        - name: prometheus
          image: prom/prometheus:v2.51.0
          args:
            - '--storage.tsdb.retention.time=6h'
            - '--storage.tsdb.max-block-duration=2h'
            - '--storage.tsdb.min-block-duration=2h'

        - name: thanos-sidecar
          image: quay.io/thanos/thanos:v0.37.0
          args:
            - 'sidecar'
            - '--prometheus.url=http://localhost:9090'
            - '--objstore.config-file=/etc/thanos/objstore.yaml'
            - '--tsdb.path=/prometheus'
          volumeMounts:
            - name: objstore-config
              mountPath: /etc/thanos
```

```yaml
# objstore.yaml — конфигурация Object Storage (S3)
type: S3
config:
  bucket: "thanos-metrics"
  endpoint: "s3.amazonaws.com"
  access_key: "${AWS_ACCESS_KEY}"
  secret_key: "${AWS_SECRET_KEY}"
  insecure: false
```

## Практические сценарии

### Архитектура HA-кластера Thanos

Поток данных в высокодоступной конфигурации:

| Шаг | Действие |
|---|---|
| 1 | Два+ экземпляра Prometheus собирают метрики с одних таргетов; рядом с каждым — Thanos Sidecar |
| 2 | Grafana отправляет PromQL-запрос в Thanos Query (или Query Frontend) |
| 3 | Thanos Query параллельно запрашивает свежие данные у всех Sidecar и исторические — у Store Gateway |
| 4 | Thanos Query выполняет дедупликацию данных от HA-пар и возвращает единый результат |
| 5 | Sidecar выгружает завершённые TSDB-блоки в Object Storage; Compactor оптимизирует их в фоне |

Результат: отказ любого компонента (Prometheus, Sidecar) не приводит к потере данных.

### Thanos vs Remote Read/Write

| Критерий | Thanos | Remote Read/Write |
|---|---|---|
| **Архитектура** | Sidecar + Object Storage | Прямая отправка в хранилище |
| **Хранилище** | S3-совместимое объектное | Зависит от целевой системы (VictoriaMetrics, Mimir и др.) |
| **Сложность** | Средняя (6+ компонентов) | Низкая–средняя (зависит от хранилища) |
| **Дедупликация** | Встроенная (Query + Compactor) | Зависит от хранилища |
| **Downsampling** | Встроенный (Compactor) | Зависит от хранилища |
| **Когда выбирать** | Kubernetes-нативная среда, нужен контроль над хранилищем | Простота развёртывания, VictoriaMetrics/Mimir |

## Дополнительная информация

### Компоненты оптимизации

#### Thanos Compactor

| Функция | Описание |
|---|---|
| **Compaction** | Объединение малых блоков (2ч) в крупные (суточные) — ускорение запросов за большие периоды |
| **Downsampling** | Агрегированные версии данных с пониженным разрешением: 5-минутное для данных >30 дней, часовое для данных >1 года |
| **Постоянная дедупликация** | Дедупликация сохранённых блоков HA-пар — экономия места в Object Storage |

#### Thanos Query Frontend

| Функция | Описание |
|---|---|
| **Кэширование** | Кэш результатов запросов — ускорение дашбордов Grafana |
| **Разбиение запросов** | Декомпозиция больших запросов на мелкие — предотвращение перегрузки Query-узлов |

### Рекомендации по развёртыванию

- **Retention на Prometheus:** 6–12 часов — достаточно для работы Sidecar; долгосрочные данные — в Object Storage.
- **Block duration:** `--storage.tsdb.{min,max}-block-duration=2h` — стандартный интервал для совместимости с Compactor.
- **Кэширование Query:** использовать Memcached/Redis для кэширования метаданных и результатов запросов.
- **Мониторинг Thanos:** Thanos предоставляет собственные метрики (`thanos_*`) для контроля состояния компонентов.
