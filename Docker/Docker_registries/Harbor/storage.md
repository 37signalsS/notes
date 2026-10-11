# Harbor: хранилище — бэкенды, кэш, ёмкость

**Актуально для:** Harbor 2.15.x (storage_service, cache layer); distribution storage drivers (S3/Azure/GCS)

## Определения

* **`storage_service`**: Секция `harbor.yml`, переключающая хранилище слоёв реестра (blobs) с локального диска (`data_volume`) на внешний бэкенд. Параметры передаются в конфигурацию встроенного registry (модифицированный distribution).
* **`data_volume`**: Локальная директория хоста (дефолт `/data`) с данными Harbor: БД, Redis, кэш Trivy, сертификаты. При внешнем storage-бэкенде слои образов хранятся вне `data_volume`.
* **Storage backend**: Драйвер хранения blobs: `filesystem` (дефолт), `s3`, `azure`, `gcs`. В конфигурации должен быть ровно один бэкенд — иначе registry не стартует.
* **Redirect**: Режим, при котором registry отдаёт клиенту прямую ссылку на blob в бэкенде (например, presigned S3 URL) вместо проксирования через себя. Включён по умолчанию; отключается `redirect.deactivate: true`.
* **Cache layer**: Redis-кэш Harbor для метаданных: `project`, `project_metadata`, `repository`, `artifact`, `manifest`. Дефолт выключен; рекомендуется при высокой конкурентности pull.
* **Blob descriptor cache**: Кэш метаданных слоёв на уровне distribution (`storage.cache.blobdescriptor: redis|inmemory`) — управляется Harbor внутренне, отражается в метрике `registry_storage_cache_total`.
* **Upload purging**: Фоновая очистка незавершённых загрузок blobs (`upload_purging` в `harbor.yml`).
* **`quota_update_provider`**: Механизм обновления квот проекта: `db` (дефолт) или `redis` — снижает spike соединений к БД при массовом push в один проект.

## Основные концепции

### Что и где хранится

```text
/data (data_volume)
├── database/        # PostgreSQL: метаданные проектов, пользователи, аудит-логи, отчёты сканирования
├── registry/        # Слои образов (blobs) — ТОЛЬКО при filesystem-бэкенде
├── redis/           # RDB-снапшоты Redis
├── trivy-adapter/   # Кэш сканера: trivy/db, java-db, reports
└── cert/            # TLS-сертификаты (дефолтный путь)
```

При переходе на S3/Azure/GCS директория `registry/` опустошается (новые слои — во внешнем бэкенде), остальное остаётся в `data_volume`. Детали эксплуатации `data_volume` — в [operations.md, сценарий 4](./operations.md#сценарий-4-управление-хранилищем).

### Бэкенды хранения

| Бэкенд | Когда применять | Ограничения |
| :--- | :--- | :--- |
| **filesystem** (дефолт) | Dev, single-node, небольшие инсталляции | Ограничен дисками хоста; нет нативной HA для слоёв |
| **s3** | Production на AWS или on-prem с MinIO/Ceph RGW; HA, масштабируемость | Требует сеть до endpoint; redirect требует доступа клиентов к бэкенду |
| **azure** | Инфраструктура на Azure Blob Storage | Azure AD (client_secret) или account key |
| **gcs** | Инфраструктура на Google Cloud Storage | Service account keyfile или inline credentials |

> Harbor docs упоминают также `swift` и `oss` — legacy-драйверы distribution, **удалённые в distribution v3** (см. [docker_registries.md](../../docker_registries.md)); для новых развёртываний используйте filesystem/s3/azure/gcs.

### Как выбрать бэкенд

1. **Существующая инфраструктура** — если в организации есть S3/MinIO или Azure Blob, используйте их.
2. **HA и масштаб** — filesystem ограничен одним хостом; object storage масштабируется и переживает хосты Harbor.
3. **Сетевая близость** — registry и бэкенд должны быть в быстрой сети; при redirect клиенты тоже должны видеть бэкенд (иначе — `deactivate: true`).
4. **Compliance** — шифрование at rest, versioning, аудит доступа к бакету.

### Redirect и почему его отключают

По умолчанию registry возвращает клиенту прямую ссылку на blob в бэкенде — это снимает нагрузку с registry. Отключайте redirect (`deactivate: true`), когда:

* клиенты (kubelet, CI-раннеры) **не имеют сетевого доступа** к бэкенду (закрытый сегмент, MinIO без маршрутов к узлам);
* перед storage стоит CDN или middleware (Helm: `registry.middleware`);
* бэкенд не поддерживает redirect — **MinIO не поддерживает redirect**, для него `deactivate: true` обязателен.

### Cache layer

Включается в `harbor.yml`:

```yaml
cache:
  enabled: true       # дефолт false
  expire_hours: 24    # дефолт 24; TTL кэша метаданных
```

* Кэширует `project`, `project_metadata`, `repository`, `artifact`, `manifest` в Redis — особенно помогает при **массивном конкурентном pull** (снижает нагрузку на PostgreSQL).
* **HA-требование (из harbor.yml.tmpl Harbor 2.15):** все инстансы Harbor должны иметь одинаковое поведение — все с включённым кэшем или все без, иначе возможна рассогласованность данных.
* Отдельный DB index Redis: `cache_layer_db_index` (дефолт 7) — не меняйте без необходимости.
* **Побочный эффект:** после изменения политик (retention, RBAC) применение может занять до `expire_hours` ([operations.md, граничные случаи](./operations.md#граничные-случаи)).

**`quota_update_provider: redis`** — при высококонкурентном push в один проект (снижает spike соединений к БД); побочный эффект — задержка отображения квоты в UI.

## Предварительные требования

| Требование | Проверка | Примечание |
| :--- | :--- | :--- |
| Доступ к бэкенду с хостов Harbor | `curl -sI http://minio:9000` | Порт и endpoint бэкенда |
| Учётные данные бэкенда | accesskey/secretkey или keyfile | Минимальные права: read/write/list на бакет |
| Бакет/контейнер создан | `mc ls minio/harbor-bucket` | Пустой бакет для Harbor |
| `harbor.yml` редактируем | `sudo -e harbor.yml` | Содержит пароли — `chmod 600`, не в git ([hardening.md](./hardening.md)) |
| Инстанс остановлен перед сменой бэкенда | `docker compose down` | Смена бэкенда «на лету» не мигрирует существующие слои |

## Практические сценарии

### Сценарий 1: S3 / MinIO бэкенд

```yaml
# harbor.yml
storage_service:
  ca_bundle: /path/to/ca.crt        # если бэкенд с самоподписанным сертификатом
  s3:
    accesskey: <ACCESS_KEY>
    secretkey: <SECRET_KEY>
    region: us-east-1
    regionendpoint: http://192.168.1.100:9000   # MinIO / S3-совместимый; для AWS S3 не задаётся
    forcepathstyle: true            # MinIO требует path-style адресацию
    bucket: harbor-bucket
    secure: false                   # false для http:// (MinIO); true для https://
    v4auth: true
    chunksize: 5242880
    multipartcopychunksize: 33554432
    multipartcopymaxconcurrency: 100
    multipartcopythresholdsize: 33554432
    rootdirectory: /harbor          # префикс внутри бакета
  redirect:
    deactivate: true                # MinIO не поддерживает redirect
```

Для **AWS S3** (без MinIO): `regionendpoint` не задаётся, `secure: true`, `forcepathstyle: false`, `accelerate: false` (или `true` для S3 Transfer Acceleration).

```bash
# Применение
sudo ./prepare && sudo docker compose up -d

# Smoke-тест: push и проверка бакета
docker login harbor.corp.local
docker push harbor.corp.local/myproject/myapp:v1
mc ls minio/harbor-bucket/harbor/docker/registry/v2/blobs/sha256/
# → blobs появились в бакете
```

### Сценарий 2: Azure Blob бэкенд

Два способа аутентификации: account key или Azure AD (service principal):

```yaml
# harbor.yml — вариант с account key
storage_service:
  azure:
    accountname: <STORAGE_ACCOUNT_NAME>
    accountkey: <BASE64_ENCODED_ACCOUNT_KEY>
    container: harbor-images
    rootdirectory: /registry
    max_retries: 10
    retry_delay: 100ms
  redirect:
    deactivate: false
```

```yaml
# harbor.yml — вариант с Azure AD (client_secret)
storage_service:
  azure:
    accountname: <STORAGE_ACCOUNT_NAME>
    container: harbor-images
    credentials:
      type: client_secret
      clientid: <CLIENT_ID>
      tenantid: <TENANT_ID>
      secret: <CLIENT_SECRET>
    max_retries: 10
    retry_delay: 100ms
  redirect:
    deactivate: false
```

### Сценарий 3: GCS бэкенд

```yaml
# harbor.yml — keyfile
storage_service:
  gcs:
    bucket: harbor-images
    keyfile: /path/to/service-account-key.json
    rootdirectory: /registry
    chunksize: 5242880
  redirect:
    deactivate: false
```

Альтернатива — inline `credentials` (type: `service_account` с `project_id`, `private_key`, `client_email` и остальными полями service account JSON) вместо `keyfile`.

### Сценарий 4: Миграция storage local → S3

Harbor **не имеет встроенного инструмента** миграции существующих слоёв между бэкендами: смена `storage_service` + restart переключает registry на новый бэкенд, но старые blobs остаются на локальном диске и становятся недоступны. Поддерживаемый путь — re-push через второй инстанс:

1. **Подготовьте новый Harbor** (или второй инстанс) с `storage_service.s3` (сценарий 1).
2. **Смигрируйте образы** со старого Harbor на новый с сохранением digest:

```bash
# По всем репозиториям проекта (инвентарь — см. migration.md, сценарий 1)
skopeo sync --src docker --dest docker --all --preserve-digests \
  --keep-going --retry-times 5 \
  harbor-old.corp.local/myproject harbor-new.corp.local/myproject
```

3. **Верифицируйте** digest по всем тегам (методика — [migration.md, сценарий 6](./migration.md#сценарий-6-верификация-в-масштабе)).
4. **Cutover** потребителей на новый инстанс (методика — [migration.md, сценарий 5](./migration.md#сценарий-5-cutover-переключение-потребителей)).
5. Деcommission старый инстанс после периода наблюдения.

> Планируйте окно миграции: объём передачи = сумма уникальных blobs (общие слои дедуплицируются). DR-действия (бэкап `data_volume`) при этом не меняются — см. [upgrade_backup.md](./upgrade_backup.md).

### Сценарий 5: S3-гигиена (versioning, lifecycle, encryption)

Бакет Harbor — активное хранилище, а не холодный архив; гигиена отличается от архивных бакетов:

```bash
# 1. Versioning — защита blobs от случайного DELETE/overwrite (human error)
mc version alias set myminio http://minio:9000 ACCESS_KEY SECRET_KEY
mc version enable myminio/harbor-bucket

# 2. Lifecycle: abort незавершённых multipart uploads (главная гигиена)
#    Незавершённые загрузки оплачиваются, но Harbor их не видит
mc ilm rule add --expire-delete-marker myminio/harbor-bucket \
  --expire-days 7 --prefix ""   # пример; см. mc ilm --help для вашей версии
# В AWS: S3 → Management → lifecycle rule "Abort incomplete multipart uploads after 7 days"

# 3. Encryption at rest: SSE-S3 (дефолт) или SSE-KMS
#    AWS: bucket default encryption; MinIO: mc alias set ... --api s3v4 + KES

# 4. Bucket policy: deny не-SSL и доступ не с IP Harbor-инстансов
#    (если redirect деактивирован — клиенты к S3 не обращаются напрямую)
```

> **Не переводите blobs в холодные классы (Glacier/Infrequent Access) автоматически** — они читаются при каждом pull. Lifecycle на холодное хранилище применяйте только к старым версиям (versioning) и незавершённым uploads.

### Сценарий 6: Cache layer — включение и проверка

```yaml
# harbor.yml
cache:
  enabled: true
  expire_hours: 24

# Опционально: при массовом push в один проект
core:
  quota_update_provider: redis
```

```bash
sudo ./prepare && sudo docker compose up -d

# Проверка: метрика cache storage registry
curl -s http://harbor.corp.local:9090/metrics | grep registry_storage_cache_total
# → registry_storage_cache_total{...} <значение>

# HA: убедитесь, что ВСЕ инстансы имеют одинаковый cache.enabled
# (разнобой ведёт к рассогласованности данных — требование harbor.yml.tmpl)
```

### Сценарий 7: Capacity planning

```bash
# 1. Текущее потребление по проектам (квоты)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects?page_size=100" | \
  jq '.[] | {name, quota_usage: .quota_usage, quota: .quota}'

# 2. Метрики хранения
curl -s http://harbor.corp.local:9090/metrics | \
  grep -E "harbor_project_quota_usage_byte|registry_storage_action_seconds"
```

**Оценка роста:** `уникальные blobs × retention-фактор`. Общие базовые слои хранятся один раз (дедупликация на уровне контента), поэтому реальный объём меньше суммы размеров образов. Планируйте:

* квоты на проекты как защита от переполнения ([usage.md](./usage.md));
* алерты: `harbor_project_quota_usage_byte` > 80% от `harbor_project_quota_byte`, диск `data_volume` > 80% (node_exporter), размер бакета S3;
* деградацию бэкенда — `registry_storage_action_seconds_*` (рост p99 операций pull/push/blob).

## Валидация

```bash
# 1. Registry использует заданный бэкенд
docker compose exec registry env | grep REGISTRY_STORAGE
# → REGISTRY_STORAGE_S3_ACCESSKEY=... (или AZURE_/GCS_)

# 2. Push проходит и blob попадает в бэкенд
docker push harbor.corp.local/myproject/myapp:v1
mc ls myminio/harbor-bucket/harbor/docker/registry/v2/blobs/sha256/ | head

# 3. Pull отдаётся из бэкенда (redirect или через registry)
docker pull harbor.corp.local/myproject/myapp:v1
# → Status: Image is up to date

# 4. Cache layer включён
curl -s http://harbor.corp.local:9090/metrics | grep registry_storage_cache_total

# 5. Upload purging работает
sudo du -sh /data/registry/docker/registry/v2/repositories/*/_uploads 2>/dev/null
# → пусто или минимальный объём
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `AccessDenied` при push на S3 | Неверные accesskey/secretkey, bucket policy, регион | Проверьте учётные данные (`mc alias set`), bucket policy, `region`/`regionendpoint` |
| Push зависает / таймауты на S3 | `secure` не совпадает с протоколом endpoint (http vs https), multipart-настройки | `secure: false` для http:// MinIO; проверьте `multipartcopy*` и сеть до `regionendpoint` |
| Образы не отдаются после перехода на S3 | Redirect включён, но клиенты не видят бэкенд | `redirect.deactivate: true` и `./prepare && docker compose up -d` |
| MinIO: blobs не скачиваются | MinIO не поддерживает redirect | `redirect.deactivate: true` |
| Рассогласованность данных в HA | Разный `cache.enabled` на инстансах | Выровняйте настройки cache на всех инстансах |
| Квота проекта не обновляется при массовом push | `quota_update_provider: db` — spike соединений | `core.quota_update_provider: redis` |
| `_uploads` растёт на диске | Зависшие push | `upload_purging.enabled: true` (дефолт); ручная очистка — [operations.md, сценарий 4](./operations.md#сценарий-4-управление-хранилищем) |
| Бакет S3 растёт быстрее квот Harbor | Незавершённые multipart uploads | Lifecycle-правило abort incomplete multipart uploads (сценарий 5) |
| Registry не стартует после правки | Два бэкенда в конфиге или обязательный ключ пропущен | Ровно один бэкенд; все required-ключи секции (accountname+accountkey для azure и т.п.) |

## Граничные случаи

* **Ровно один бэкенд**: конфигурация с двумя бэкендами (например, `filesystem` + `s3`) — registry вернёт ошибку.
* **`inmemory`** — драйвер только для тестов; для «volatile registry» используйте filesystem на ramdisk.
* **Windows-хосты**: хостовый volume не рекомендуется — используйте S3 или Azure (иначе ограничение MAX_PATH на пути к точке монтирования).
* **Смена бэкенда не мигрирует слои**: существующие образы остаются на старом хранилище — только re-push (сценарий 4).
* **Cache layer и политики**: после изменения retention/RBAC эффект может проявиться с задержкой до `expire_hours`.
* **Внешний storage не отменяет `data_volume`**: БД, Redis, кэш Trivy и сертификаты по-прежнему локальны.
* **`forcepathstyle`**: MinIO и большинство S3-совместимых хранилищ требуют path-style; AWS S3 — virtual-hosted-style (`forcepathstyle: false`).

### Сценарий 8: Управление слоями (GC, удаление, health-check)

**Удаление blobs по digest** — отключено по умолчанию (`delete.enabled: false`). Включите его только тогда, когда это нужно — после включения registry переходит в `readonly`-режим, GC удаляет неиспользуемые blobs, затем registry перезапускается без `maintenance.readonly`:

```yaml
# harbor.yml — последовательность для ручного GC
delete:
  enabled: true
maintenance:
  readonly:
    enabled: true

# 1. Остановите registry и включите readonly
sudo docker compose stop registry
sudo ./prepare && sudo docker compose up -d

# 2. Запустите GC (только в readonly!)
docker exec -it $(docker ps -qf name=registry) \
  registry garbage-collect --delete-untagged --delete-dangling 2>&1

# 3. Отключите readonly и перезапустите
# (удалите maintenance.readonly из harbor.yml, ./prepare && docker compose up -d)
```

> **Важно (SRE):** `registry garbage-collect` — низкоуровневый CLI registry (встроенный в distribution), работает только в `readonly`-режиме. Высокоуровневый инструмент — **Harbor Clean Up** (Administration → Clean Up → Garbage Collection), он не требует остановки registry и имеет DRY RUN + расписание — детали в [usage.md, сценарий 10](./usage.md#сценарий-10-garbage-collection). CLI-вариант нужен, когда Clean Up не подходит (например, ручная очистка после инцидента без остановки инстанса — но тогда registry должен быть в `readonly`).
>
> `garbage-collect` без `--delete-untagged` удаляет только **dangling** blobs (непривязанные к манифесту). `--delete-untagged` удаляет теги без манифестов. Оба флага безопасны, но `--delete-untagged` меняет catalog — проверьте, что ни один CI/CD не держит теги, которые должны сохраниться.

**Health-check бэкенда** — registry проверяет доступность бэкенда по расписанию и помечает инстанс как unhealthy после `threshold` неудач. Позволяет вывести registry из load balancer rotation при проблемах с бэкендом:

```yaml
health:
  storagedriver:
    enabled: true        # дефолт true
    interval: 10s        # дефолт 10s
    threshold: 3         # дефолт 3 — сколько неудач подряд
```

Результаты доступны в Prometheus-метриках registry (debug-сервер) и логах. Проверка:

```bash
# Метрики health-check'а (debug-сервер registry, порт задаётся в harbor.yml)
curl -s http://registry-debug:PORT/metrics | grep -i "registry_health\|storage_driver_health"
```

> **SRE-замечание:** health-check'и работают только если в `harbor.yml`/distribution-конфиге включён debug-сервер (`http.debug`). По умолчанию в Harbor он есть, но порт — внутренний; не открывайте его публично (см. [hardening.md](./hardening.md)).

**`tag.concurrencylimit`** — при удалении манифеста registry перебирает все теги репозитория, читая каждый через бэкенд. При большом числе тегов (сотни и тысячи) это генерирует много S3/API-вызовов. Установите лимит параллельности:

```yaml
tag:
  concurrencylimit: 8   # дефолт: GOMAXPROCS
```

## Лучшие практики

* **Production — object storage** (S3/MinIO) вместо локального диска: масштабируемость, переживает хосты Harbor, упрощает HA.
* **Versioning + lifecycle-abort** на бакете — защита от human error и «утечки» multipart-партов.
* **Encryption at rest + deny non-SSL** в bucket policy.
* **Cache layer** при высокой конкурентности pull; единообразие настроек во всех HA-инстансах.
* **Квоты на проекты** + алерты на 80% потребления.
* **Мониторьте `registry_storage_action_seconds_*`** — ранний индикатор деградации бэкенда.
* **`redirect.deactivate: true`** для MinIO и закрытых сегментов — иначе клиенты не смогут download blobs.

## См. также

* **[Установка Harbor](./installation.md)** — сценарий 1, шаг 4: краткая настройка S3/MinIO; этот файл — полное описание бэкендов.
* **[Эксплуатация](./operations.md)** — сценарий 1 (тюнинг), сценарий 2 (метрики), сценарий 4 (управление хранилищем), сценарий 6 (SLO/SLI).
* **[Миграция в Harbor](./migration.md)** — перенос образов между реестрами (в т.ч. при смене storage-бэкенда).
* **[Обзор Harbor](./overview.md)** — компоненты, требования к ресурсам.
* **[Hardening](./hardening.md)** — защита инстанса, права на `harbor.yml`.
* **[Distribution: конфигурация registry](https://distribution.github.io/distribution/about/configuration/)** — reference всех ключей storage-драйверов (s3/azure/gcs/filesystem), `cache.blobdescriptor`, `maintenance.readonly`.
* **[Harbor: Configure the Harbor YML File](https://goharbor.io/docs/2.15.0/install-config/configure-yml-file/)** — официальный reference параметров `storage_service`, `cache`, `redirect`.
* **[docker_registries.md](../../docker_registries.md)** — storage backends реестров в целом, дедупликация blobs.
