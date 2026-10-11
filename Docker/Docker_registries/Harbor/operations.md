# Harbor: Эксплуатация — производительность, мониторинг, аудит, хранилище

**Актуально для:** Harbor 2.15.x

## Определения

* **max_job_workers**: Максимальное число параллельных фоновых задач Job Service (репликация, сканирование, GC). Параметр `harbor.yml`, дефолт **10**.
* **Cache layer**: Внутренний кэш Harbor для метаданных артефактов. Параметр `cache.enabled` в `harbor.yml`, дефолт **выключен**; рекомендуется включать на инстансах с высокой конкурентностью pull.
* **Log rotation**: Ротация аудит-логов: расписание purge и окно хранения (`Keep records in`).
* **Audit Log**: Журнал операций (кто, когда, что, над каким ресурсом). Хранится в БД Harbor, опционально форвардится в syslog.
* **Upload purging**: Фоновая очистка незавершённых загрузок blobs (`upload_purging` в `harbor.yml`).
* **data_volume**: Директория хоста (дефолт `/data`) с данными Harbor: БД, реестр, Redis, кэш сканера.

## Основные концепции

### Рычаги производительности

| Рычаг | Параметр | Эффект |
| :--- | :--- | :--- |
| Параллелизм задач | `jobservice.max_job_workers` | Больше concurrent репликаций/сканирований (ценой CPU/IO) |
| Cache layer | `cache.enabled: true` | Снижает нагрузку на БД при массовых pull |
| Внешние PostgreSQL/Redis | `database.type: external` | Снимает нагрузку с хоста Harbor |
| Object storage | `storage_service.s3` | Масштабируемое хранилище слоёв вместо локального диска |
| HA-реплики | `core.replicas`, `registry.replicas` ≥ 2 | Горизонтальное масштабирование (Helm) |

### Где что лежит на диске (Docker Compose)

```text
/data (data_volume)
├── database/        # PostgreSQL Harbor (метаданные, аудит-логи, отчёты сканирования)
├── registry/        # Docker Distribution: /docker/registry/v2/{blobs,repositories}
├── redis/           # RDB-снапшоты Redis
├── trivy-adapter/   # Кэш сканера: trivy/db, trivy/java-db, reports
└── cert/            # TLS-сертификаты (если используется дефолтный путь)
```

Логи контейнеров: `/var/log/harbor/` (параметр `log.location` в `harbor.yml`).

## Практические сценарии

### Сценарий 1: Тюнинг производительности

```yaml
# harbor.yml (Docker Compose) — после правки: ./prepare && docker compose up -d

jobservice:
  max_job_workers: 20        # дефолт 10; параллельные репликация/сканирование/GC
  max_job_duration_hours: 24 # дефолт 24; задачи дольше — прерываются

cache:
  enabled: true              # дефолт false; рекомендуется при высокой конкурентности pull
  expire_hours: 24           # дефолт 24; TTL кэша метаданных

log:
  level: info                # debug | info | warning | error | fatal
  local:
    rotate_count: 50         # ротация логов
    rotate_size: 200M
  location: /var/log/harbor

upload_purging:
  enabled: true              # очистка незавершённых загрузок blobs
  age: 168h                  # purge загрузок старше 7 дней
  interval: 24h
  dryrun: false
```

В Helm-чарте те же рычаги: `jobservice.maxJobWorkers` (дефолт 10), `registry.middleware` (CDN перед storage).

**Тюнинг пула соединений PostgreSQL** (при «too many connections» или `БД недоступна` в runbook):

```yaml
# harbor.yml — встроенная БД (database) и внешняя (external_database.harbor)
database:
  type: internal          # internal | external
  # pool (применяется и к internal, и к external):
  pool:
    max_idle_conns: 10        # idle-соединений в пуле
    max_open_conns: 100       # макс. открытых соединений (0 = без лимита)
    conn_max_lifetime: 1h     # макс. время жизни соединения
    conn_max_idle_time: 30m   # макс. время idle перед закрытием

external_database:
  harbor:
    host: postgres.corp.local
    port: 5432
    username: harbor
    password: "***"
    database: registry
    ssl_mode: disable
    pool:
      max_idle_conns: 2       # дефолт 2
      max_open_conns: 0       # дефолт 0 (без лимита)
      conn_max_lifetime: 1h
      conn_max_idle_time: 30m
```

Правило: `max_open_conns` Harbor ≤ `max_connections` PostgreSQL минус резерв для администрирования; при HA-репликах core считайте пул на каждую реплику.

> Каждый worker потребляет сеть/CPU/IO — увеличивайте `max_job_workers` с учётом ресурсов хоста (официальная рекомендация).

### Сценарий 2: Мониторинг и алерты (Prometheus)

Метрики Harbor включаются в `harbor.yml` (`metrics.port`, `metrics.path`) или `metrics.enabled: true` в Helm — см. [обзор](./overview.md#мониторинг-и-наблюдаемость-sre). Примеры alert-правил на верифицированных метриках Harbor:

```yaml
# prometheus/alert-rules/harbor.yml
groups:
  - name: harbor
    rules:
      - alert: HarborComponentDown
        expr: harbor_up == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Harbor component {{ $labels.component }} is down"

      - alert: HarborTaskQueueBacklog
        expr: harbor_task_queue_size > 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Harbor Job Service queue backlog ({{ $value }} tasks)"
          description: "Репликация/сканирование/GC застряли — проверьте jobservice и max_job_workers"

      - alert: HarborProjectQuotaHighUsage
        expr: harbor_project_quota_usage_byte > 85899345920
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Harbor project {{ $labels.project }} uses > 80 GB"
          description: "Порог задаётся под вашу квоту проекта; полный список метрик — на <harbor_instance>:<metrics_port>/<metrics_path>"

      - alert: HarborUnhealthy
        expr: harbor_health != 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Harbor instance unhealthy"
```

> Имена метрик (`harbor_up`, `harbor_health`, `harbor_task_queue_size`, `harbor_project_quota_usage_byte`, `harbor_artifact_pulled`) — из документации Harbor; полный список — на `<harbor_instance>:<metrics_port>/<metrics_path>`.

**Справочник метрик Harbor** (по компонентам):

| Метрика | Компонент | Назначение |
| :--- | :--- | :--- |
| `harbor_up` | exporter | Скрейп успешен (по компонентам: `component="core"`, `jobservice`, `registry`, `registryctl`, `portal`, `trivy-adapter`) |
| `harbor_health` | exporter | Статус здоровья инстанса (1 = healthy) |
| `harbor_system_info` | exporter | Информация об инстансе: лейблы `auth_mode`, `harbor_version`, `self_registration` |
| `harbor_artifact_pulled` | exporter | Счётчик pull артефактов |
| `harbor_project_total` | exporter | Число проектов |
| `harbor_project_repo_total` | exporter | Число репозиториев в проекте |
| `harbor_project_member_total` | exporter | Число членов проекта |
| `harbor_project_artifact_total` | exporter | Число артефактов в проекте |
| `harbor_project_quota_usage_byte` | exporter | Потребление квоты проекта (байт) |
| `harbor_project_quota_byte` | exporter | Лимит квоты проекта (байт) |
| `harbor_task_queue_size` | exporter | Размер очереди задач Job Service |
| `harbor_task_queue_latency` | exporter | Латентность очереди задач |
| `harbor_task_scheduled_total` | exporter | Счётчик запланированных задач |
| `harbor_task_concurrency` | exporter | Текущая конкурентность задач |
| `harbor_core_http_request_total` | core | HTTP-запросы core (по коду/методу) |
| `harbor_core_http_inflight_requests` | core | Выполняющиеся запросы core |
| `harbor_core_http_request_duration_seconds` | core | Длительность запросов core (гистограмма) |
| `registry_http_requests_total` | registry | HTTP-запросы registry |
| `registry_http_in_flight_requests` | registry | Выполняющиеся запросы registry |
| `registry_http_request_duration_seconds_*` | registry | Длительность запросов registry |
| `registry_http_request_size_bytes_*` / `registry_http_response_size_bytes_*` | registry | Размеры запросов/ответов registry |
| `registry_storage_action_seconds_*` | registry | Длительность операций storage (pull/push/blob) |
| `registry_storage_cache_total` | registry | Кэш storage registry |
| `harbor_jobservice_info` | jobservice | Информация о jobservice |
| `harbor_jobservice_task_total` | jobservice | Счётчик задач jobservice |
| `harbor_jobservice_task_process_time_seconds` | jobservice | Время обработки задачи |

**Grafana Dashboard:** готовый dashboard на базе этих метрик — [`contrib/grafana-dashboard/metrics-example.json`](https://github.com/goharbor/harbor/blob/main/contrib/grafana-dashboard/metrics-example.json) в репозитории Harbor (импорт через Grafana UI: + Import → Upload JSON file).

### Сценарий 2a: Debug-логирование для диагностики

```yaml
# harbor.yml — временное включение debug на время инцидента
log:
  level: debug             # debug | info (дефолт) | warning | error | fatal
  location: /var/log/harbor
```

```bash
sudo ./prepare && sudo docker compose up -d
# Логи core/jobservice/registryctl после изменения уровня:
sudo tail -f /var/log/harbor/harbor-core.log
# → уровень debug: детализация HTTP-запросов, DB-транзакций, задач
```

* Уровень `debug` заметно увеличивает объём логов — включайте на время диагностики и возвращайте к `info`.
* Ротация логов контейнеров: `log.local.rotate_count` / `log.local.rotate_size` (см. сценарий 1).
* Трассировка запросов между компонентами (Jaeger/OTel) — в [распределённой трассировке](./tracing.md).

### Сценарий 2b: Compliance-экспорт аудит-логов

Для регулярного экспорта аудит-логов в SIEM/хранилище доказательств (compliance):

```bash
# Полный выгруз текущего окна хранения (пагинация: page/page_size, заголовок X-Total-Count)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/auditlog-exts?page_size=1000" | \
  jq -r '.[] | [.timestamp, .username, .operation, .resource] | @tsv' > audit-$(date +%F).tsv

# Только критичные операции (удаления, изменения конфигурации)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/auditlog-exts?page_size=1000" | \
  jq -r '.[] | select(.operation == "delete artifact" or .operation == "change configuration") |
    [.timestamp, .username, .operation, .resource] | @tsv'
```

* Окно хранения задаётся Log Rotation (сценарий 3) — экспорт делайте чаще, чем purge.
* Для непрерывного сбора — форвардинг в syslog/SIEM (сценарий 3), а не периодический API-выгруз.
* `Skip Audit Log Database` экономит место в PostgreSQL, но тогда API-выгруз пуст — логи только в syslog.

### Сценарий 3: Аудит-логи

**Что логируется** (типы событий): `pull artifact`, `push artifact`, `delete artifact`, `create/update/delete user`, `login/logout user`, `change configuration`, `create/delete project`, `create/delete robot`, `delete repository`.

**Просмотр:**

```bash
# UI: Administration → Audit Log (с v2.13 две вкладки: Audit Logs и Audit Logs (Legacy))
# Фильтры: тип операции, username, operation, resource, resource type

# API: системный админ видит все логи, project admin — логи своих проектов
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/auditlog-exts?page=1&page_size=50" | jq '.[] | {timestamp: .timestamp, username, operation, resource}'

# Кто удалил артефакт (пример фильтрации на стороне jq)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/auditlog-exts?page_size=1000" | \
  jq '.[] | select(.operation == "delete artifact") | {timestamp: .timestamp, username, resource}'
```

**Ротация (retention) аудит-логов:**

1. **Administration → Clean Up → Log Rotation**.
2. Расписание: `None` / `Hourly` / `Daily` / `Weekly` / `Custom` (cron).
3. **Keep records in**: окно хранения (Hours/Days) — например, 90 дней.
4. **Event types to purge**: какие типы событий участвуют в purge.
5. **DRY RUN** — оценка объёма purge без удаления; **PURGE NOW** — немедленный запуск.

**Форвардинг в SIEM (syslog):**

1. **Administration → Configuration → System Settings → Audit Log Forward Syslog Endpoint**.
2. Для Docker Compose локальный syslog: `harbor-log:10514`; для внешнего SIEM — его адрес.
3. Опция **Skip Audit Log Database**: не хранить логи в БД, только форвардить (экономит место в PostgreSQL).
4. Избирательный пропуск по типам событий: **Administration → Configuration → System Settings → Disable Audit Log Event Type**.

### Сценарий 4: Управление хранилищем

```bash
# 1. Использование места data_volume
sudo du -sh /data/* | sort -h
# → 45G	/data/registry
# → 12G	/data/database

# 2. Реальное использование по проектам (квоты)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects?page_size=100" | \
  jq '.[] | {name, storage: .metadata.public, quota: .quota}'

# 3. Освобождение места: retention → GC (см. usage.md, сценарии 8 и 10)
#    Retention помечает артефакты, GC физически удаляет слои

# 4. Незавершённые загрузки (зависшие push) — чистятся upload_purging
#    Ручная проверка:
sudo du -sh /data/registry/docker/registry/v2/repositories/*/_uploads 2>/dev/null
```

**При переполнении диска:**

1. Остановите push (квота проекта или `read-only` на storage).
2. Запустите GC (сначала DRY RUN).
3. Если storage на S3/MinIO — проверьте квоту бакета.
4. Расширьте `data_volume` или перейдите на object storage (`storage_service`) — конфигурация бэкендов (S3/Azure/GCS), redirect и S3-гигиена — в [storage.md](./storage.md).

### Сценарий 5: Runbook инцидентов

| Инцидент | Диагностика | Действия |
| :--- | :--- | :--- |
| **Pull массово падает** | `curl -sk /api/v2.0/health`; метрика `harbor_up` по компонентам | Проверьте registry/registryctl; место на диске; TLS-сертификат (срок) |
| **Push зависает** | `harbor_task_queue_size`; логи jobservice | Проверьте `max_job_workers`, место на диске, незавершённые uploads |
| **Сканирование не завершается** | Логи trivy-adapter: `docker logs trivy-adapter` | Базы Trivy актуальны? `skip_update` в air-gapped; таймаут `trivy.timeout` (дефолт 5m, верхняя граница job — 30m) |
| **Репликация не работает** | API executions; **Test Endpoint** | Учётные данные endpoint, сеть, права робот-аккаунта |
| **401 в CI для robot-аккаунта** | Формат `robot$<project>+<name>`; срок действия | Refresh секрета; проверьте expiration аккаунта |
| **БД недоступна** | `docker logs harbor-core`; подключение к PostgreSQL | Внешняя БД: место, лимит соединений, сетевой доступ |
| **Redis недоступна** | Логи jobservice/core | Внешний Redis: Sentinel поддерживается, Cluster — нет |
| **Аудит-лог растёт** | Размер `/data/database` | Настройте Log Rotation + форвардинг в syslog |

### Сценарий 6: SLO/SLI и error budget

SLO/SLI для Harbor строятся на метриках из справочника выше (паттерн — как для [Vault](../../../Vault/guides/monitoring_and_alerting.md#сценарий-4-slo-для-vault) и [Chaos Engineering](../../../Chaos_Engineering/chaos_engineering_metrics.md)).

**SLI (на верифицированных метриках Harbor):**

| SLI | Метрика | Расчёт |
| :--- | :--- | :--- |
| Доступность | `harbor_health`, `harbor_up{component}` | Доля времени `harbor_health == 1` |
| Успешность pull/push | `registry_http_requests_total` | `rate(code=~"2..") / rate(all)` |
| Латентность pull/push | `registry_http_request_duration_seconds` | `histogram_quantile(0.99, ...)` |
| Пропускная способность | `harbor_artifact_pulled` | `rate()` за период |
| Здоровье очереди задач | `harbor_task_queue_size` | Ниже порога (например, < 100) |

**Пример SLO:** 99.9% успешных HTTP-запросов registry за 30 дней; p99 латентности < 500 ms. Error budget = 0.1% (≈ 43 минуты деградации в месяц).

**Алерты по скорости расходования error budget (burn rate):**

```yaml
# SLO 99.9% за 30 дней. Порог = budget_fraction × 0.001 × (30×24 / window_hours)
# Fast burn: 2% бюджета за 1 час → порог ошибок 1.44% (0.001 × 0.02 × 720)
- alert: HarborFastBurn
  expr: |
    sum(rate(registry_http_requests_total{code=~"5.."}[1h]))
    / sum(rate(registry_http_requests_total[1h])) > 0.0144
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Harbor registry error budget burning fast ({{ $value | humanizePercentage }} 5xx)"

# Slow burn: 5% бюджета за 6 часов → порог 0.6% (0.001 × 0.05 × 120)
- alert: HarborSlowBurn
  expr: |
    sum(rate(registry_http_requests_total{code=~"5.."}[6h]))
    / sum(rate(registry_http_requests_total[6h])) > 0.006
  for: 30m
  labels:
    severity: warning
```

**Дополнительные SLO-алерты:**

```yaml
# Доступность компонентов
- alert: HarborComponentDown
  expr: harbor_up == 0
  for: 5m
  labels:
    severity: critical

# Латентность p99 операций storage (pull/push/blob)
- alert: HarborStorageLatencyHigh
  expr: |
    histogram_quantile(0.99,
      sum(rate(registry_storage_action_seconds_bucket[5h])) by (le)) > 0.5
  for: 15m
  labels:
    severity: warning
```

* Burn rate > 1 означает, что при текущем уровне ошибок SLO на месяц будет нарушен; формула и интерпретация — в [Chaos Engineering: метрики](../../../Chaos_Engineering/chaos_engineering_metrics.md).
* SLI на `registry_http_requests_total` считает и служебные запросы; для чистоты фильтруйте по `method` и коду, если нужна только семантика pull/push.
* Error budget расходуется и на деградацию (латентность), а не только на 5xx — комбинируйте с latency-SLI.

## Валидация

```bash
# Метрики доступны
curl -s http://harbor.corp.local:<metrics_port>/<metrics_path> | grep -E "harbor_up|harbor_task_queue_size"
# → harbor_up{component="core",...} 1

# Аудит-лог пишется (system admin)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/auditlog-exts?page_size=5" | jq 'length'
# → 5

# Log rotation настроена
curl -sk -u "admin:$PASS" --request GET \
  "https://harbor.corp.local/api/v2.0/system/purgeaudit/schedule" | jq .
# → {"schedule":"Daily",...}

# Параметры тюнинга применились
docker exec harbor-jobservice env | grep -i job
# → (проверка через логи/метрики jobservice)
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Метрики не scrape-ятся | metrics не включён | `metrics.port`/`metrics.path` в `harbor.yml` или `metrics.enabled: true` в Helm |
| Алерты шумят по `harbor_up` | Скрейп до прокси, а не до Harbor | Проверьте target и порт метрик |
| Аудит-лог пуст | Форвардинг с `Skip Audit Log Database` | Логи — в syslog/SIEM, не в БД |
| GC не освобождает место | Retention не запущен или untagged не включено | Запустите Retention, затем GC с опцией untagged |
| Диск заполнен `_uploads` | Зависшие push | `upload_purging.enabled: true`; ручная очистка |
| Логи не пишутся в `/var/log/harbor` | Нет прав на директорию | Проверьте `log.location` и права хоста |

## Граничные случаи

* **Cache layer** кэширует метаданные — после изменения политик (retention, RBAC) может потребоваться время до `expire_hours` для применения.
* **Аудит-лог в БД** растёт вместе с нагрузкой: при высокой частоте pull рассмотрите форвардинг в syslog + `Skip Audit Log Database`.
* **`max_job_workers`** выше 10 без ресурсов хоста — деградация: все задачи начнут конкурировать за IO.
* **Log rotation** purge-ит только аудит-логи Harbor, не логи контейнеров (`/var/log/harbor` ротируется отдельно, `log.local.rotate_*`).
* **Redis Cluster не поддерживается** — только standalone или Sentinel (см. [установку](./installation.md)).

## Лучшие практики

### Производительность и масштабирование

* **`max_job_workers`**: Увеличивайте постепенно (шаг 5–10) с мониторингом `harbor_task_queue_size` и загрузки CPU/IO хоста. Не превышайте ресурсы хоста — перегрузка IO ухудшит все задачи.
* **Cache layer**: Включайте `cache.enabled: true` на инстансах с высокой конкурентностью pull (много параллельных нод/подов). В HA — **одинаковое значение `enabled` на всех инстансах** (требование `harbor.yml.tmpl`).
* **Внешние БД/Redis**: Для production используйте внешние PostgreSQL (>=12) и Redis (standalone или Sentinel). Снимает нагрузку с хоста Harbor и упрощает HA.
* **Object storage**: Переходите на S3/MinIO вместо локального `filesystem` для масштабируемости и HA. Для MinIO — обязательно `redirect.deactivate: true`.
* **Connection pooling**: Настройте `database.pool.max_open_conns` ≤ `max_connections` PostgreSQL минус резерв. При HA-репликах core — пул на каждую реплику.
* **`quota_update_provider: redis`**: При массовом push в один проект снижает spike соединений к БД.

### Мониторинг и алертинг

* **Базовые алерты**: Всегда настройте алерты на `harbor_up == 0` (по компонентам), `harbor_health != 1`, `harbor_task_queue_size > 100`.
* **SLO/SLI**: Определите SLO для доступности (99.9%), успешности pull/push, p99 латентности. Используйте burn-rate алерты для раннего обнаружения расходования error budget.
* **Метрики storage**: Следите за `registry_storage_action_seconds_*` — ранний индикатор деградации бэкенда.
* **Квоты проектов**: Алерты на `harbor_project_quota_usage_byte > 80% harbor_project_quota_byte`.
* **Grafana dashboard**: Импортируйте готовый dashboard из `contrib/grafana-dashboard/metrics-example.json` репозитория Harbor.

### Аудит и соответствие

* **Log rotation**: Настройте расписание purge (Daily/Weekly) и окно хранения (например, 90 дней). Используйте DRY RUN перед PURGE NOW.
* **Форвардинг в SIEM**: Настройте syslog forwarding (`harbor-log:10514` локально или внешний SIEM). Опция **Skip Audit Log Database** экономит место в PostgreSQL.
* **Регулярный экспорт**: Экспортируйте аудит-логи в SIEM/хранилище доказательств чаще, чем окно purge (API `/auditlog-exts` с пагинацией).

### Хранилище и очистка

* **Retention → GC**: Retention только помечает артефакты, GC физически удаляет. Запускайте GC по расписанию (Daily/Weekly) в часы минимальной нагрузки. Всегда — DRY RUN перед GC Now.
* **Upload purging**: Включите `upload_purging.enabled: true` (дефолт) с `age: 168h` (7 дней) для очистки зависших push.
* **S3-гигиена**: Versioning + lifecycle rule "Abort incomplete multipart uploads after 7 days" + encryption at rest + deny non-SSL в bucket policy. Не переводите blobs в холодные классы автоматически.
* **Capacity planning**: Мониторьте диск `data_volume` (node_exporter > 80%), квоты проектов, размер бакета S3. Планируйте рост по уникальным blobs × retention-фактор.

### Безопасность и hardening

* **Self-registration**: Держите выключенной (Administration → Configuration → Authentication).
* **HTTPS**: Только HTTPS в production; HTTP — только в air-gapped test/dev.
* **Робот-аккаунты**: Только для CI/CD, минимальные права (Pull, Push требует Pull), expiration, ротация секретов.
* **Deployment Security**: Включите scan on push и порог severity (Critical) в production-проектах.
* **Апгрейды**: Патчи безопасности выходят в patch/minor-релизах — обновляйтесь при появлении CVE (отслеживайте SECURITY.md).
* **Пароли и ключи**: `chmod 600 harbor.yml`; ключи шифрования (`secretKey` минимум 16, рекомендуется 32) — в Secrets-менеджере, не в файле.

### Эксплуатация

* **DR Drill**: Проводите тренировку восстановления из бэкапа не реже раза в квартал и после каждого значимого изменения (апгрейд, смена storage backend).
* **Бэкап**: Полный бэкап `harbor.yml` + директория установщика + `data_volume` при остановленном Harbor (консистентность БД). В Kubernetes — Velero.
* **Откат**: Планируйте откат как часть плана инцидентов; миграция схемы БД необратима — старый инстанс не прочитает мигрированную БД.
* **Логи**: Уровень `debug` только на время диагностики, затем возвращайте к `info`. Ротация контейнерных логов: `log.local.rotate_count` / `rotate_size`.
* **Health-check**: Используйте `GET /api/v2.0/health` для liveness/readiness probes (не требует аутентификации).

## Дополнительная информация

* Официальная документация: [Audit Log](https://goharbor.io/docs/2.15.0/administration/audit-log/), [Log Rotation](https://goharbor.io/docs/2.15.0/administration/log-rotation/), [Configure the Harbor YML File](https://goharbor.io/docs/2.15.0/install-config/configure-yml-file/), [Metrics](https://goharbor.io/docs/2.15.0/administration/monitoring-harbor-with-prometheus/).
* **Метрики и ServiceMonitor** — [обзор Harbor](./overview.md#мониторинг-и-наблюдаемость-sre).
* **GC и Retention** — [работа с Harbor](./usage.md#сценарий-10-garbage-collection).
* **Распределённая трассировка** — [tracing.md](./tracing.md) (Jaeger/OTel, корреляция с логами по X-Request-ID).
* **Hardening инстанса** — [hardening.md](./hardening.md) (чек-лист защиты, аудит-лог как слой защиты).
* **Multi-arch артефакты (SRE-контекст)** — [multi_arch.md](./multi_arch.md) — мониторинг, алерты, retention/GC, air-gapped для OCI image index.
* **Хранилище: бэкенды, кэш, ёмкость** — [storage.md](./storage.md) — S3/Azure/GCS, cache layer, S3-гигиена, capacity planning.

### Связанные документы

* **[Обзор Harbor](./overview.md)** — компоненты и метрики.
* **[Установка Harbor](./installation.md)** — `harbor.yml` и внешние зависимости.
* **[Репликация](./replication.md)** — нагрузка на Job Service.
* **[Оффлайн-обновление Trivy](./offline_trivy_update.md)** — параметры сканера.
* **[Harbor REST API](./api.md)** — автоматизация мониторинга.
* **[Распределённая трассировка](./tracing.md)** — трейсы запросов между компонентами.
* **[Hardening](./hardening.md)** — защита инстанса и аудит.
* **[Хранилище: бэкенды, кэш, ёмкость](./storage.md)** — S3/Azure/GCS, cache layer, S3-гигиена, capacity planning.
* **[Миграция в Harbor](./migration.md)** — перенос образов из Docker Hub и других реестров.
