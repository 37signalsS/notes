# S3: RGW storage tiering и lifecycle transitions

**Актуально для:** Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**Storage tiering (hot/warm/cold)** — механизм автоматического перемещения объектов между пулами RGW (SSD → HDD → Archive) на основе возраста или паттерна доступа.

**Hot pool** — SSD-based пул для часто используемых данных. Низкая latency, высокая стоимость за ГБ.

**Warm pool** — HDD-based пул для тёплых данных. Средняя latency, средняя стоимость.

**Cold pool (Archive)** — пул для редко используемых данных. Высокая latency, минимальная стоимость.

**Lifecycle transition** — автоматическое перемещение объекта между пулами по истечении TTL.

**Restore (восстановление)** — процесс перемещения объекта из cold pool обратно в warm/hot pool для доступа.

**Retrieval (извлечение)** — операция получения объекта из cold pool. В Ceph RGW latency зависит от конфигурации пула и типа дисков.

**Placement target** — логическая группировка пулов (index + data + data_extra), определяющая, где хранятся объекты bucket'а. Настраивается через `radosgw-admin zonegroup placement` и `zone placement`.

**Storage Class** — имя, которое клиент указывает при PUT или которое назначает lifecycle policy. В Ceph RGW storage class отображается на placement target и data pool.

**RGW Cache** — встроенный кэш RGW (`rgw_cache_enabled`, `rgw_cache_lru_size`), ускоряющий повторные чтения из cold pool за счёт хранения недавно использованных объектов в hot cache.

**Lifecycle worker thread** — фоновая нить RGW (`rgw_enable_lc_threads`), которая обрабатывает bucket lifecycle rules асинхронно. В Squid/Tentacle/Umbrella parallel-обработка управляется через `rgw_lc_max_worker` и `rgw_lc_max_wp_worker`.

---

## 2. Базовые концепции

### 2.1 RGW Pool Tiering

В Ceph RGW классы хранения определяются placement targets и storage classes:

| Pool | Тип диска | Latency | Стоимость/ГБ/мес | Сценарий |
|------|-----------|---------|------------------|----------|
| **Hot** | NVMe/SSD | Миллисекунды | Высокая | Активные артефакты, текущие бэкапы |
| **Warm** | HDD | Миллисекунды | Средняя | Артефакты старше 30 дней, редко читаемые |
| **Cold** | HDD/EC (Erasure Coding) | Минуты/часы | Минимальная | Архивы, compliance логи, долгосрочное хранение |
| **Archive (external)** | S3-compatible endpoint / tape | Часы/дни | Минимальная | Долгосрочное хранение 1+ лет (требует cloud-s3 tiering) |

> **Важно:** В Ceph RGW не рекомендуется использовать storage class names с префиксом `GLACIER` (например, `GLACIER`, `GLACIER_IR`). Некоторые S3-клиенты и библиотеки ожидают AWS-специфичное поведение для таких имён и могут завершиться ошибкой при доступе к Ceph RGW. Используйте `STANDARD_IA`, `INTELLIGENT-TIERING`, `REDUCED_REDUNDANCY` или кастомные имена (`COLD`, `ARCHIVE`).

### 2.2 Lifecycle transitions

```json
{
  "Rules": [
    {
      "ID": "TieringPolicy",
      "Status": "Enabled",
      "Filter": {"Prefix": "backups/"},
      "Transitions": [
        {"Days": 7, "StorageClass": "WARM"},
        {"Days": 90, "StorageClass": "COLD"}
      ],
      "NoncurrentVersionTransitions": [
        {"Days": 7, "StorageClass": "WARM"},
        {"Days": 30, "StorageClass": "COLD"}
      ],
      "NoncurrentVersionExpiration": {"NoncurrentDays": 365},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    }
  ]
}
```

**Важно:** Lifecycle policies работают асинхронно через lifecycle worker threads. Не рассчитывайте на немедленное удаление или переход. В Squid/Tentacle/Umbrella параллельная обработка управляется через:
- `rgw_lc_max_worker` (по умолчанию 3) — количество потоков lifecycle worker'ов.
- `rgw_lc_max_wp_worker` (по умолчанию 128) — количество корутин в каждом worker'е.
- `rgw_enable_lc_threads` — включает lifecycle maintenance thread на RGW daemon'е.

### 2.3 Placement targets и storage classes

Placement targets управляются через `radosgw-admin`:

```bash
# Просмотр placement targets в zonegroup
radosgw-admin zonegroup get --rgw-zonegroup default

# Просмотр placement pools в zone
radosgw-admin zone get --rgw-zone default

# Добавление storage class COLD в default-placement
radosgw-admin zonegroup placement add \
  --rgw-zonegroup default \
  --placement-id default-placement \
  --storage-class COLD

radosgw-admin zone placement add \
  --rgw-zone default \
  --placement-id default-placement \
  --storage-class COLD \
  --data-pool default.rgw.cold.data \
  --compression lz4

# Изменение default placement
radosgw-admin zonegroup placement default \
  --rgw-zonegroup default \
  --placement-id new-placement
```

Bucket создаётся с placement target, который нельзя изменить позднее. `radosgw-admin bucket stats` отображает `placement_rule` bucket'а.

### 2.4 When to use which pool

- **Hot (NVMe/SSD):** Активные артефакты, текущие бэкапы, часто читаемые данные.
- **Warm (HDD):** Артефакты старше 30 дней, редко читаемые бэкапы, логи.
- **Cold (HDD/EC):** Архивы, compliance логи, долгосрочное хранение (1+ лет).
- **Archive (external S3/tape):** Только при необходимости off-cluster хранения. В Squid/Tentacle/Umbrella функциональность cloud-s3 tiering ограничена; проверьте актуальность конфигурации `radosgw-admin --tier-type=cloud-s3` для вашей версии.

---

## 3. Практические сценарии

### 3.1 Настройка lifecycle transitions

```bash
# Применение lifecycle configuration
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-app-archives \
  --lifecycle-configuration file://lifecycle.json \
  --endpoint-url http://rgw:7480

# Просмотр текущих правил
aws s3api get-bucket-lifecycle-configuration \
  --bucket my-app-archives \
  --endpoint-url http://rgw:7480

# Удаление всех lifecycle правил
aws s3api delete-bucket-lifecycle \
  --bucket my-app-archives \
  --endpoint-url http://rgw:7480
```

### 3.2 Проверка Storage Class и placement объекта

```bash
# Получение метаданных объекта
aws s3api head-object \
  --bucket my-app-archives \
  --key backups/2023/01/data.tar.gz \
  --endpoint-url http://rgw:7480

# → {
#     "StorageClass": "COLD",
#     "RestoreInProgress": false,
#     "ArchiveStatus": "none"
#   }

# Список объектов в Cold pool
aws s3api list-objects-v2 \
  --bucket my-app-archives \
  --query 'Contents[?StorageClass==`COLD`].[Key, Size, LastModified]' \
  --output table \
  --endpoint-url http://rgw:7480

# Проверка placement rule bucket'а
radosgw-admin bucket stats --bucket my-app-archives | jq .placement_rule
# → "default-placement"

# Детальная информация о placement и manifest объекта
radosgw-admin object stat --bucket my-app-archives --object backups/2023/01/data.tar.gz | jq .
```

### 3.3 Доступ к объектам из Cold pool

В Ceph RGW для нативных cold pool (HDD/EC) восстановление происходит автоматически при GET-запросе. RGW считывает объект напрямую из cold data pool. Время доступа зависит от типа дисков и нагрузки на кластер. Для ускорения повторных чтений используется RGW Cache (`rgw_cache_enabled`, `rgw_cache_lru_size`).

> **Примечание:** Функциональность cloud-restore (восстановление объектов из внешних S3-совместимых архивов) была удалена в Squid 19.x. В Squid/Tentacle/Umbrella восстановление из off-cluster archive через `restore-object` API не поддерживается. Используйте только нативные placement targets внутри кластера.

```bash
# GET объекта из cold pool
aws s3 cp s3://my-app-archives/backups/2023/01/data.tar.gz ./restored/ \
  --endpoint-url http://rgw:7480

# Проверка StorageClass после доступа
aws s3api head-object \
  --bucket my-app-archives \
  --key backups/2023/01/data.tar.gz \
  --endpoint-url http://rgw:7480

# Проверка RGW cache hit ratio (если включён prometheus exporter)
curl -s http://rgw:9283/metrics | grep rgw_cache_
```

### 3.4 Event notifications для lifecycle transitions

```bash
# Настройка уведомлений на HTTP webhook
aws s3api put-bucket-notification-configuration \
  --bucket my-app-archives \
  --notification-configuration '{
    "TopicConfigurations": [
      {
        "Topic": "http://webhook.example.com/restore-complete",
        "Events": ["s3:ObjectRestore:*"]
      }
    ]
  }' \
  --endpoint-url http://rgw:7480
```

**События lifecycle:**
- `s3:ObjectCreated:*` — объект загружен или восстановлен из cold pool.
- `s3:ObjectRemoved:*` — объект удалён или перемещён в cold pool.
- `s3:ObjectRestore:*` — restore инициирован или завершён.

---

## 4. Cost optimization

### 4.1 Lifecycle policies для tiering

См. JSON lifecycle configuration в разделе 2.2.

### 4.2 Относительная стоимость tiering

Для self-hosted Ceph RGW стоимость определяется аппаратной базой (SSD vs HDD vs EC pools) и операционными расходами, а не облачными тарифами.

| Слой | Ожидаемая стоимость | Примечание |
|------|---------------------|------------|
| **Hot (NVMe)** | Максимальная | Низкая latency, высокая durability |
| **Warm (HDD)** | Средняя | Оптимальна для регулярного доступа раз в неделю/месяц |
| **Cold (HDD/EC)** | Минимальная | EC даёт дополнительную экономию места ценой CPU на parity-вычислениях |

**Оценка:** Для 100 ТБ данных переход с replicated HDD (3x replica) на EC (4+2) даёт экономию места ~40% при той же durability. Дополнительный переход на холодные EC pools с ленивыми дисками снижает операционные расходы.

### 4.3 When to use which pool

- **Hot (NVMe/SSD):** Data lake, артефакты CI/CD, текущие бэкапы.
- **Warm (HDD):** Backup archives, compliance logs (доступ раз в квартал).
- **Cold (HDD/EC):** Long-term compliance (1+ лет), cold backup, disaster recovery archives.
- **Archive (external):** Только при необходимости off-cluster хранения и если cloud-s3 tiering подтверждён для вашей версии Ceph.

---

## 5. Предварительные требования

Для работы с этим runbook необходимы:

- **aws-cli 2.x** — основной инструмент для диагностики S3 API.
- **ceph-common / radosgw-admin** — утилиты для управления Ceph RGW (placement, storage classes, bucket stats).
- **jq** — для парсинга JSON-вывода `radosgw-admin`.
- **Доступ к RGW endpoint** — сетевая доступность порта 7480 (HTTP) или 443 (HTTPS).
- **Valid credentials** — Access Key ID и Secret Key с правами на целевой bucket.
- **Синхронизированные часы** — разница времени между клиентом и RGW не должна превышать 15 минут (NTP обязателен).
- **Права на `radosgw-admin`** — для просмотра placement и bucket stats требуется доступ к Ceph CLI.

```
# Проверка доступности RGW endpoint
curl -s -o /dev/null -w "%{http_code}" http://rgw:7480
# → 403 или 200 (ожидаем любой HTTP-ответ, кроме timeout/connection refused)

# Проверка aws-cli
aws --version
# → aws-cli/2.x Python/3.x Linux/...

# Проверка radosgw-admin
radosgw-admin --version
# → radosgw-admin ...

# Проверка bucket placement
radosgw-admin bucket stats --bucket my-app-archives | jq .placement_rule
# → "default-placement"

# Проверка storage classes в zonegroup
radosgw-admin zonegroup get --rgw-zonegroup default | jq .placement_targets
```

---

## 6. Troubleshooting

| Проблема | Причина | Диагностика | Решение |
|----------|---------|-------------|---------|
| Объект не перемещается | Lifecycle schedule неактивен | `aws s3api get-bucket-lifecycle-configuration` → проверка `IsEnabled` | Включите `IsEnabled: true` |
| Lifecycle не применяется | Неправильный prefix в Filter | `aws s3api list-objects-v2 --prefix ...` → проверка соответствия ключей | Убедитесь, что `Filter.Prefix` совпадает с ключом объекта |
| Объект удалён prematurely | Lifecycle Expiration слишком агрессивный | Проверка `Expiration.Days` в lifecycle rules | Увеличьте `Days` в Expiration |
| Доступ к cold объекту занимает > минут | Cold pool на slow HDD/tape или congested network | `radosgw-admin bucket stats`, `ceph osd perf`, `mtr --tcp --port 7480` | Увеличьте IOPS, проверьте OSD performance, используйте warm pool |
| `403` при доступе к cold объекту | Нет permissions или неверный addressing style | `aws s3api get-bucket-policy`, `aws configure get default.s3.addressing_style` | Добавьте permissions, установите `addressing_style=path` |
| Lifecycle transitions очень медленные | Мало lifecycle worker threads | Проверка `rgw_lc_max_worker` и `rgw_lc_max_wp_worker` в `ceph config get mgr` | Увеличьте `rgw_lc_max_worker` (например, до 6–10) |
| Lifecycle не работает после upgrade | Lifecycle thread отключён | `ceph config get client.rgw.* rgw_enable_lc_threads` | Убедитесь, что `rgw_enable_lc_threads = true` на минимум одном RGW daemon'е в зоне |
| Cold pool unavailable | OSD down или PG degraded | `ceph health detail`, `ceph osd perf`, `ceph pg stat` | Восстановите OSD, проверьте crush rule для cold pool |
| RGW Cache не работает | `rgw_cache_enabled = false` или `rgw_cache_lru_size` слишком мал | `ceph config get client.rgw.* rgw_cache_enabled`, `rgw_cache_lru_size` | Включите кэш и увеличьте LRU size при необходимости |

---

## 7. Consistency and edge cases

### 7.1 Consistency model Ceph RGW для tiering

| Операция | Консистентность |
|----------|----------------|
| PUT (новый объект) | Strong read-after-write |
| PUT (overwrite) | Eventual |
| Lifecycle transition | Eventual (асинхронная обработка worker threads) |
| DELETE | Strong read-after-delete |
| LIST | Eventual |

**Production advice:**
- **Strong consistency** для новых объектов: RGW является source of truth без дополнительных механизмов.
- **Eventual consistency** для LIST и overwrite: добавьте retry LIST при проверке результата transition.
- **Lifecycle transitions** не являются немедленными: ожидайте задержку от нескольких минут до часов в зависимости от `rgw_lc_max_worker` и размера bucket'а.

### 7.2 Edge cases

- **Clock skew:** Разница времени > 15 минут вызывает `403 RequestTimeTooSkewed`. Для lifecycle это не критично, но влияет на подпись запросов.
- **Versioning + Lifecycle:** Noncurrent version transitions работают только при включённом versioning. Если versioning отключён, `NoncurrentVersionTransitions` игнорируются.
- **Multipart uploads + Lifecycle:** `AbortIncompleteMultipartUpload` очищает зависшие загрузки. Жёсткие multipart (> 10 000 parts) могут создавать нагрузку на lifecycle worker'ы.
- **Addressing style:** Для self-hosted RGW используйте `addressing_style=path`. Неправильный стиль вызывает `403 SignatureDoesNotMatch` при доступе к bucket'ам с точками в имени.
- **Object Lock + Lifecycle:** Object Lock в Governance/Compliance режиме предотвращает удаление объектов даже по lifecycle Expiration. Убедитесь, что retention period меньше, чем lifecycle Expiration, или отключите Object Lock для архивных bucket'ов.
- **Multisite:** Lifecycle policies применяются в пределах одной zone. При multisite replication lifecycle не распространяется на удалённые zones автоматически.
- **S3 Inventory + Lifecycle:** Inventory отчёты можно использовать для верификации, что lifecycle transitions применились корректно. Проверяйте `StorageClass` в Inventory CSV/Parquet.

---

## 8. Best Practices

1. **Используйте Lifecycle policies** для автоматического перехода между hot/warm/cold pools. Не храните в Hot данные, к которым редко обращаются.
2. **Test access procedures** раз в квартал. Убедитесь, что чтение из cold pool работает и данные читаемы.
3. **Combine с versioning** — lifecycle transitions работают с versioned объектами.
4. **Настройте lifecycle на все production bucket'ы.** Это основа для cost optimization.
5. **Monitor lifecycle через Prometheus.** Включите alerts на неожиданные переходы или рост ошибок lifecycle.
6. **Document RTO/RPO** для cold pool. Cold pool на HDD имеет RTO ~ минут, на EC — потенциально больше при degraded state.
7. **Object Lock + Lifecycle** — для compliance. Object Lock предотвращает удаление даже из cold pool.
8. **Use AbortIncompleteMultipartUpload** для автоматической очистки зависших загрузок.
9. **Test with small datasets** перед применением к production. Убедитесь, что lifecycle работает корректно и placement targets настроены.
10. **Regularly review lifecycle rules** — раз в квартал проверяйте, что правила соответствуют текущим потребностям.
11. **Настройте lifecycle worker threads** под размер инфраструктуры: для тысяч bucket'ов увеличьте `rgw_lc_max_worker`.
12. **Избегайте имён storage classes с префиксом GLACIER** в Ceph RGW. Это вызывает ошибки в некоторых S3-клиентах.

---

## 9. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
