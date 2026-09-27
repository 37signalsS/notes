# TCO и сравнение решений для хранения метрик

## Определения

**TCO (Total Cost of Ownership)** — полная стоимость владения, включающая: стоимость инфраструктуры (CPU, RAM, Disk, Network), операционные расходы (электричество, охлаждение), стоимость труда инженеров (настройка, обслуживание, инциденты) и лицензии.

**Prometheus** — pull-based система сбора метрик с локальной TSDB. Стандарт для мониторинга, но ограничена горизонтальным масштабированием.

**Thanos** — надстройка над Prometheus, обеспечивающая long-term storage в S3 и глобальный view.

**VictoriaMetrics** — высокопроизводительная замена TSDB с совместимым PromQL языком (MetricsQL).

**Mimir** — микросервисная LTS от Grafana Labs, оптимизированная для Grafana.

> **См. также:** [Cost Optimization](../kubernetes/operator/cost_optimization.md) — оптимизация TCO в K8s; [Thanos Overview](./thanos_overview.md); [VictoriaMetrics Overview](../VictoriaMetrics/overview.md); [Mimir Overview](../Mimir/mimir_overview.md).

---

## Базовые концепции

### Критерии сравнения

| Критерий | Prometheus | Thanos | VictoriaMetrics | Mimir |
|:---|:---|:---|:---|:---|
| **Архитектура** | Монолит | Sidecar + Query + Store | Single/Cluster | Микросервисы |
| **Хранилище** | Локальная TSDB | S3/GCS/MinIO | Локальное/S3 | S3/GCS/MinIO |
| **Retention** | 15-30 дней (локально) | Неограниченный | Неограниченный | Неограниченный |
| **Global View** | Нет | Да (Thanos Query) | Да (vmselect) | Да (Query Frontend) |
| **Multi-tenancy** | Label-based | Receiver + labels | `X-Scope-OrgID` | `X-Scope-OrgID` |
| **Downsampling** | Recording rules | Compactor | Нативный | Compactor |
| **PromQL** | Полный | Полный | MetricsQL (расширенный) | Полный |
| **Overhead RAM** | 0 | +200-500 MiB/sidecar | Минимальный | Зависит от компонентов |

### Факторы стоимости

| Фактор | Влияние на TCO |
|:---|:---|
| **Retention** | Экспоненциальное (данные растут линейно, но запросы замедляются) |
| **Cardinality** | Прямое (RAM, Disk, CPU) |
| **scrape_interval** | Пропорциональное |
| **Replication (HA)** | x2 от базовой стоимости |
| **Количество кластеров** | Линейное (для single-instance) или сублинейное (для LTS) |

---

## Практические сценарии

### Сценарий 1: 10 Prometheus-инстансов, retention 30 дней

**Инфраструктура:**
- 10 серверов (2 vCPU, 4 GB RAM, 100 GB SSD)
- 1 сервер для Alertmanager + Grafana
- 500k активных series суммарно

| Решение | Серверы | Стоимость/мес | Стоимость за 3 года |
|:---|:---|:---|:---|
| **Prometheus (standalone)** | 11 серверов x $100 | $1,100 | $39,600 |
| **Prometheus + Thanos** | 11 + 3 (Query/Store) = 14 | $1,400 + $50 (S3) | $50,400 |
| **VictoriaMetrics (cluster)** | 6 (vminsert/vmselect/vmstorage x 2) | $600 + $50 (S3) | $21,600 |

### Сценарий 2: 50 Prometheus-инстансов, retention 90 дней

**Инфраструктура:**
- 50 серверов с Prometheus
- 2 млн активных series
- Global view обязателен

| Решение | Компоненты | Стоимость/мес | Стоимость за 3 года |
|:---|:---|:---|:---|
| **Prometheus + Thanos** | 50 Sidecar + 5 Query + 3 Store + 1 Compactor | $6,000 + $200 (S3) | $216,000 |
| **VictoriaMetrics Cluster** | 10 vminsert + 10 vmselect + 10 vmstorage | $3,000 + $200 (S3) | $108,000 |
| **Mimir** |istributor + 5 Compactor + 10 Querier + 5 Ruler | $4,500 + $300 (S3) | $162,000 |

### Сценарий 3: Стоимость инженерного труда

| Компонент | Prometheus | Thanos | VictoriaMetrics | Mimir |
|:---|:---|:---|:---|:---|
| **Настройка** | 1 день | 3-5 дней | 2-3 дня | 5-7 дней |
| **Обновление** | 1-2 часа | 2-4 часа | 1-2 часа | 2-4 часа |
| **Диагностика** | Простая | Средняя | Средняя | Сложная |
| **Документация** | Отличная | Хорошая | Хорошая | Хорошая |
| **Сообщество** | Очень большое | Большое | Среднее | Среднее |

### ROI-формула

```
ROI = (Стоимость_инцидента * Частота_инцидентов) / Стоимость_мониторинга

Пример:
- Инцидент = $10,000 (простой сервиса 1 час)
- 2 инцидента в месяц без мониторинга
- Стоимость мониторинга = $5,000/мес
- ROI = ($10,000 * 2) / $5,000 = 4x
```

---

## Дополнительная информация

### Когда выбирать что

| Ситуация | Рекомендация |
|:---|:---|
| < 5 Prometheus, retention < 30 дней | Остаться на чистом Prometheus |
| 5-20 Prometheus, retention 30-90 дней | Thanos (sidecar) или VictoriaMetrics single |
| > 20 Prometheus, retention > 90 дней | VictoriaMetrics cluster или Mimir |
| Нужна multi-tenancy из коробки | VictoriaMetrics или Mimir |
| Стек Grafana | Mimir (нативная интеграция) |
| Минимальный overhead | VictoriaMetrics (один бинарник) |

### Скрытые издержки

| Статья | Prometheus | Thanos | VictoriaMetrics | Mimir |
|:---|:---|:---|:---|:---|
| **Стоимость S3** | Нет | Растёт с данными | Растёт (cluster) | Растёт с данными |
| **Стоимость сети** | Минимальная | Remote Write egress | Remote Write egress | Remote Write egress |
| **Стоимость обучения** | Низкая | Средняя | Низкая | Высокая |
| **Vendor lock-in** | Нет | Нет | MetricsQL (частичный) | Нет |
