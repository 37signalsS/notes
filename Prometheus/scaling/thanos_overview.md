# Thanos

## Определения

**Thanos** — проект CNCF, расширяющий Prometheus возможностями практически неограниченного хранения метрик и глобального выполнения запросов. Решает архитектурные ограничения Prometheus: отсутствие встроенного долгосрочного хранения и горизонтального масштабирования. Использует sidecar-архитектуру и объектные хранилища (S3).

| Возможность | Описание |
|---|---|
| **Глобальный обзор** | Запросы к данным со всех экземпляров Prometheus из единой точки |
| **Долгосрочное хранение** | Интеграция с S3-совместимыми объектными хранилищами (MinIO, Ceph, Yandex Object Storage) |
| **Высокая доступность** | Дедупликация HA-пар Prometheus, устойчивость к сбоям отдельных компонентов |

---

## Основные концепции

### Компоненты системы

| Компонент | Назначение | Ключевые функции |
|---|---|---|
| **Sidecar** | Процесс для каждого Prometheus | Upload TSDB-блоков в Object Storage (каждые 2ч); предоставление свежих данных для Query |
| **Query** | Центральная точка входа | Агрегация данных из Sidecar и Store Gateway; дедупликация HA-пар; Prometheus-compatible API |
| **Store Gateway** | Шлюз к историческим данным | Store API для Query; интеллектуальное кэширование метаданных |
| **Ruler** | Глобальные правила | Выполнение recording/alerting rules поверх всех кластеров через Query; отправка алертов |
| **Compactor** | Оптимизация данных | Сжатие блоков, downsampling, постоянная дедупликация HA-пар |
| **Query Frontend** | Ускоритель запросов | Кэширование результатов; разбиение больших запросов на мелкие |

### Поддерживаемые объектные хранилища

Sidecar выгружает данные в S3-совместимые системы:

| Хранилище | Тип | Примечание |
|---|---|---|
| **Amazon S3** | Облачное | Нативная поддержка |
| **MinIO** | Self-hosted | S3-совместимое |
| **Ceph (RGW)** | On-premise | S3-совместимое |
| **Yandex Object Storage** | Облачное | S3-совместимое |
| **Google Cloud Storage** | Облачное | |

---

## Практические сценарии

### Архитектура высокой доступности

Поток данных в HA-конфигурации:

1. Несколько экземпляров Prometheus собирают метрики с одних таргетов; рядом с каждым — Thanos Sidecar.
2. Grafana отправляет PromQL-запрос в Thanos Query.
3. Thanos Query параллельно запрашивает свежие данные у всех Sidecar и исторические — у Store Gateway.
4. Thanos Query выполняет дедупликацию данных от HA-пар и возвращает единый результат.
5. Sidecar выгружает завершённые TSDB-блоки в Object Storage; Compactor оптимизирует их в фоне.

Результат: отказ любого компонента (Prometheus, Sidecar) не приводит к потере данных или прерыванию запросов.

### Сравнение: Thanos vs Remote Read/Write

| Критерий | Thanos | Remote Read/Write |
|---|---|---|
| **Архитектура** | Sidecar + Object Storage | Прямая отправка в хранилище |
| **Хранилище** | S3-совместимое объектное | Зависит от системы (VictoriaMetrics, Mimir) |
| **Сложность** | Средняя (6+ компонентов) | Низкая–средняя |
| **Downsampling** | Встроенный (Compactor) | Зависит от хранилища |
| **Когда выбирать** | Kubernetes-нативная среда, нужен контроль над хранилищем | Простота deploy, VictoriaMetrics/Mimir |

### Пример конфигурации Sidecar

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

---

## Дополнительная информация

### Рекомендации по эксплуатации

- **Retention на Prometheus:** 6–12 часов — достаточно для работы Sidecar; долгосрочные данные хранятся в Object Storage.
- **Параметры блоков:** `--storage.tsdb.{min,max}-block-duration=2h` — обязательный интервал для совместимости с Compactor.
- **Кэширование:** использовать Memcached или Redis для кэширования метаданных и результатов запросов в Query Frontend.
- **Downsampling:** Compactor создает агрегированные версии данных (5-минутные и часовые) для ускорения запросов за большие периоды.

### См. также

- **[Масштабирование Prometheus](./overview.md)** — обзор подходов
- **[VictoriaMetrics](../../VictoriaMetrics/overview.md)** — высокопроизводительная альтернатива
- **[Remote Read/Write](./remote_read_write.md)** — концепция удаленного хранения
