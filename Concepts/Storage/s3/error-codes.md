# S3: error codes и troubleshooting runbook

**Актуально для:** S3 API, Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**HTTP status code** — стандартный код ответа HTTP, возвращаемый S3. Позволяет определить класс ошибки без чтения тела ответа.

**Error code (x-amz-error-code)** — строковый код ошибки S3, возвращаемый в XML/JSON теле ответа. Содержит конкретную причину сбоя.

**Request ID (x-amz-request-id)** — уникальный идентификатор запроса, присвоенный S3. Используется для трассировки.

**Host ID (x-amz-id-2)** — идентификатор хоста S3, обработавшего запрос. Используется для диагностики инфраструктурных проблем.

**Retry-After** — заголовок, указывающий время (в секундах) до повторной попытки. Возвращается при `503 Slow Down` или `429 Too Many Requests`.

**SignatureDoesNotMatch** — ошибка аутентификации: подпись запроса не совпадает с ожидаемой.

**AccessDenied** — недостаточно прав для выполнения операции.

**NoSuchKey / NoSuchBucket** — запрашиваемый объект или bucket не существует.

**InvalidAccessKeyId** — неверный Access Key ID.

**RequestTimeout** — S3 не получил полный запрос за отведённое время.

---

## 2. Справочник error codes

### 2.1 Класс 4xx — ошибки клиента

| HTTP | Error code | Описание | Причина | Решение |
|------|-----------|----------|---------|---------|
| 400 | `BadDigest` | MD5-хеш не совпадает | Файл повреждён при передаче | Перезагрузите объект с правильным `Content-MD5` |
| 400 | `InvalidArgument` | Неверный параметр запроса | Неподдерживаемый флаг/параметр | Проверьте синтаксис запроса |
| 400 | `InvalidAccessKeyId` | Access Key ID не найден | Неверный или неактивный ключ | Проверьте credentials в `~/.aws/credentials` |
| 400 | `InvalidBucketName` | Имя bucket невалидно | Неверный формат имени | Bucket name: 3–63 символа, lowercase, no underscore |
| 416 | `InvalidRange` | Range не поддерживается | Запрос `Range` для non-existent object или превышение `Content-Length` | Проверьте `Content-Length` перед Range-запросом |
| 400 | `MissingContentLength` | Отсутствует `Content-Length` | PUT без `Content-Length` для non-chunked | Добавьте `Content-Length` или используйте chunked |
| 400 | `RequestTimeout` | Таймаут соединения с S3 | Сокет неактивен во время передачи; slow network, large object, firewall idle timeout | Увеличьте `cli_read_timeout` / `read_timeout`, используйте multipart, проверьте firewall |
| 403 | `AccessDenied` | Доступ запрещён | Нет permissions на bucket/object; для Ceph RGW — bucket policy или ACL | Проверьте bucket policy, ACL; в Ceph RGW также проверьте Dashboard или `radosgw-admin` |
| 403 | `AccountProblem` | Проблема с аккаунтом | Аккаунт закрыт/неактивен | Проверьте статус аккаунта в Ceph |
| 403 | `InvalidAccessKeyId` | Неверный Access Key ID | Ключ удалён или отозван | Проверьте ключи через `radosgw-admin user info` |
| 403 | `InvalidSecurity` | Ошибка безопасности | Неверный подпись/сертификат | Проверьте Signature Version, SSL cert |
| 403 | `RequestTimeTooSkewed` | Разница времени > 15 минут | Часы клиента не синхронизированы | NTP: `chronyc tracking` или `ntpdate` |
| 403 | `SignatureDoesNotMatch` | Подпись не совпадает | Неверный secret key, region, endpoint; для Ceph RGW — неверный addressing style | Проверьте signing process; для self-hosted установите `addressing_style=path` |
| 404 | `NoSuchBucket` | Bucket не существует | Bucket удалён, в другом регионе или в другой zone/pool (Ceph RGW) | Проверьте `list-buckets`; в Ceph RGW также `radosgw-admin bucket stats` |
| 404 | `NoSuchKey` | Объект не существует | Неверный ключ или объект удалён | Проверьте LIST bucket'а |
| 404 | `NoSuchUpload` | Multipart upload не существует | Upload ID неверен, отменён или завершён | Проверьте `list-multipart-uploads` |
| 405 | `MethodNotAllowed` | HTTP метод не поддерживается | PUT вместо GET | Используйте правильный HTTP метод |
| 409 | `BucketAlreadyExists` | Bucket уже существует | Имя bucket globally unique | Выберите уникальное имя |
| 409 | `BucketAlreadyOwnedByYou` | Bucket уже принадлежит вам | Повторное создание bucket'а | Игнорируйте или проверьте `head-bucket` |
| 409 | `OperationAborted` | Операция прервана | Конфликт условий (например, wrong region) | Проверьте bucket location constraint |
| 409 | `BucketNotEmpty` | Bucket не пустой при удалении | В bucket'е есть объекты или незавершённые multipart uploads | Очистите bucket или используйте `--force` с осторожностью |

### 2.2 Класс 5xx — ошибки сервиса

| HTTP | Error code | Описание | Причина | Решение |
|------|-----------|----------|---------|---------|
| 500 | `InternalError` | Внутренняя ошибка RGW | Временный сбой инфраструктуры; в Ceph — OSD down, PG degraded | Retry с exponential backoff; проверьте `ceph health detail` |
| 500 | `ServiceUnavailable` | Сервис временно недоступен | Maintenance или overload | Retry через 30–60 секунд |
| 503 | `SlowDown` | Превышен request-rate limit | Throttling на prefix/bucket; в Ceph RGW — throttling на уровне RGW | Увеличьте retry, добавьте jitter, redistributed prefix'ы |
| 503 | `ServiceUnavailable` | Сервис перегружен | Временный overload | Retry с `Retry-After` header |

### 2.3 Специфичные для Ceph RGW

| Error code | Описание | Причина | Решение |
|-----------|----------|---------|---------|
| `IncompleteBody` | Тело запроса оборвано | Сетевая ошибка, timeout или разрыв соединения | Увеличьте `cli_read_timeout`, используйте multipart upload для больших объектов |
| `InternalError` | Внутренняя ошибка RGW | OSD down, PG degraded, RGW daemon crash | `ceph health detail`, проверьте OSD (`ceph osd perf`) и RGW daemons (`ceph orch ps --daemon-type rgw`) |

---

## 3. Troubleshooting runbook

### 3.0 Предварительные требования

Для работы с этим runbook необходимы:

- **aws-cli 2.x** — основной инструмент для диагностики S3 API.
- **ceph-common / radosgw-admin** — утилиты для управления Ceph RGW (пользователи, bucket stats, health).
- **Доступ к RGW endpoint** — сетевая доступность порта 7480 (HTTP) или 443 (HTTPS).
- **Valid credentials** — Access Key ID и Secret Key с правами на целевой bucket.
- **Синхронизированные часы** — разница времени между клиентом и RGW не должна превышать 15 минут (NTP обязателен).

```
# Проверка доступности RGW endpoint
curl -s -o /dev/null -w "%{http_code}" http://rgw:7480
# → 403 или 200 (ожидаем любой HTTP-ответ, кроме timeout/connection refused)

# Проверка aws-cli
aws --version
# → aws-cli/2.x Python/3.x Linux/...

# Проверка radosgw-admin
radosgw-admin user info --uid="my-user"
# → JSON с секретными ключами и capabilities
```

### 3.1 403 Forbidden

```
Диагностика:
1. Проверка credentials:
   aws sts get-caller-identity --endpoint-url http://rgw:7480

2. Проверка bucket policy:
   aws s3api get-bucket-policy --bucket my-bucket --endpoint-url http://rgw:7480

3. Проверка ACL:
   aws s3api get-bucket-acl --bucket my-bucket --endpoint-url http://rgw:7480

4. Проверка addressing style:
   aws configure get default.s3.addressing_style --profile rgw

5. Проверка time skew:
   date -u
   # Разница > 15 минут → NTP сбой

6. Для Ceph RGW: проверка пользователя
   radosgw-admin user info --uid="my-user"
```

### 3.2 404 NoSuchKey / NoSuchBucket

```
Диагностика:
1. Проверка существования bucket:
   aws s3api head-bucket --bucket my-bucket --endpoint-url http://rgw:7480

2. Проверка существования объекта:
   aws s3api head-object --bucket my-bucket --key path/to/object --endpoint-url http://rgw:7480

3. Проверка версий (старая версия удалена):
   aws s3api list-object-versions \
     --bucket my-bucket \
     --prefix path/file.tar.gz \
     --endpoint-url http://rgw:7480

4. Проверка пулов RGW:
   radosgw-admin bucket stats --bucket="my-bucket"
```

### 3.3 503 Slow Down (Throttling)

```
Диагностика:
1. Проверка метрик RGW:
   curl -s http://rgw:9283/metrics | grep rgw_requests_total
   # Примечание: порт 9283 — это Ceph Manager Prometheus module. Для RGW-specific метрик
   # требуется ceph-exporter daemon, который scraper'ит admin socket RGW.

2. Проверка OSD performance:
   ceph osd perf

3. Проверка PG status:
   ceph pg stat

Решение:
1. Увеличьте retry attempts (max_attempts >= 5)
2. Включите retry_mode=adaptive
3. Добавьте случайные prefix'ы для ключей
4. Увеличьте parallel requests
```

### 3.4 Slow performance

```
Диагностика:
1. Проверка размера объекта:
   aws s3api head-object --bucket my-bucket --key large-file.tar.gz --endpoint-url http://rgw:7480

2. Проверка multipart config:
   aws configure get default.s3.multipart_threshold --profile rgw
   aws configure get default.s3.max_concurrent_requests --profile rgw

3. Проверка OSD performance:
   ceph osd perf

4. Network diagnostics:
   mtr --tcp --port 7480 rgw.example.com

Решение:
1. Для > 100 MB объектов используйте multipart upload/download
2. Увеличьте max_concurrent_requests до 20
3. Проверьте cluster_network на congestion
4. Используйте CDN для статических assets
```

### 3.5 SSL/TLS и endpoint issues

```
Диагностика:
1. Проверка SSL сертификата:
   openssl s_client -connect rgw:7480 -servername rgw

2. Для self-signed:
   aws s3 ls --endpoint-url http://rgw:7480 --no-verify-ssl

3. Проверка addressing style:
   aws s3 ls --endpoint-url http://rgw:7480 --no-verify-ssl
   # Если 403 — добавьте --no-sign-request или addressing_style=path

Решение:
1. Обновите certifi: pip install --upgrade certifi
2. Для Ceph RGW: addressing_style=path
3. Для self-signed certs: добавьте CA bundle через --ca-bundle
```

### 3.6 Infrastructure failure (Ceph RGW)

```
Диагностика:
1. Проверка статуса кластера:
   ceph status
   ceph health detail

2. Проверка OSD:
   ceph osd tree
   ceph osd perf

3. Проверка PG:
   ceph pg stat
   ceph pg dump

4. Проверка RGW daemons:
   ceph orch ps --daemon-type rgw

Решение:
1. Восстановление OSD:
   ceph osd out <osd-id>
   ceph osd crush remove <osd-id>
   # Замена диска, добавление нового OSD

2. Перезапуск RGW daemon:
   ceph orch restart rgw.myrgw

3. Проверка multisite sync:
    radosgw-admin sync status
```

### 3.7 RequestTimeout (400)

```
Диагностика:
1. Проверка размера объекта и времени передачи:
   aws s3api head-object --bucket my-bucket --key large-file.tar.gz --endpoint-url http://rgw:7480
   # Content-Length > 100 MB → используйте multipart upload

2. Проверка сетевого пути:
   mtr --tcp --port 7480 rgw.example.com
   # Потеря пакетов или задержка > 100 ms → проблема в сети

3. Проверка firewall / proxy idle timeout:
   # Некоторые firewall'ы закрывают соединение при бездействии 30–60 секунд
   # Для large upload проверьте, что firewall не обрывает соединение

4. Проверка SDK/CLI timeout:
   aws configure get default.cli_read_timeout --profile rgw
   aws configure get default.cli_connect_timeout --profile rgw

Решение:
1. Увеличьте `cli_read_timeout` до 60–120 секунд для large objects:
   aws configure set default.cli_read_timeout 120 --profile rgw

2. Для объектов > 100 MB используйте multipart upload (разбивка на части по 8–16 MB):
   aws s3 cp large-backup.tar.gz s3://my-bucket/ \
     --storage-class STANDARD_IA \
     --endpoint-url http://rgw:7480

3. Для SDK (boto3, Go, Java) увеличьте `read_timeout` / `socketTimeout` в конфигурации клиента.

4. Проверьте, что между клиентом и RGW нет proxy/firewall с агрессивным idle timeout.
```

---

## 4. Request/response headers reference

### 4.1 Request headers (S3-specific)

| Header | Описание | Пример |
|--------|----------|--------|
| `x-amz-content-sha256` | SHA256 хеш тела запроса | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `x-amz-date` | Timestamp запроса (ISO8601) | `20260929T120000Z` |
| `x-amz-security-token` | STS temporary credentials | `AQoDYXdzEJr...` |
| `x-amz-server-side-encryption` | Тип шифрования | `AES256` |
| `x-amz-meta-*` | Пользовательские метаданные | `x-amz-meta-uploaded-by: web-client` |
| `x-amz-tagging` | Теги объекта | `Team=platform&Env=prod` |
| `x-amz-website-redirect-location` | Редирект для статических сайтов | `/index.html` |

### 4.2 Response headers

| Header | Описание | Пример |
|--------|----------|--------|
| `x-amz-request-id` | Уникальный ID запроса | `3L641ZGA4TQZVQK4` |
| `x-amz-id-2` | Host ID для диагностики | `a1b2c3d4e5f6...` |
| `x-amz-version-id` | Версия объекта (если versioning включён) | `3lLf9...` |
| `x-amz-delete-marker` | Флаг delete marker | `true` |
| `x-amz-replication-status` | Статус репликации | `PENDING`, `COMPLETED`, `FAILED` |
| `x-amz-storage-class` | Storage Class объекта | `WARM`, `COLD` |
| `x-amz-expiration` | Expiration date (lifecycle) | `2026-12-31T00:00:00.000Z` |
| `ETag` | MD5-хеш или multipart ETag | `"d41d8cd98f00b204e9800998ecf8427e"` |
| `x-amz-server-side-encryption` | Тип шифрования ответа | `AES256` |
| `Retry-After` | Задержка перед retry | `30` |
| `x-amz-bucket-region` | Регион bucket | `us-east-1` |

### 4.3 ETag semantics

**Single-part upload:**
- ETag = MD5-хеш объекта.
- Можно использовать для проверки целостности.

**Multipart upload:**
- ETag ≠ MD5. Это агрегированный хеш: `MD5(part1) + MD5(part2) + ... + number_of_parts`.
- Формат: `"<hex>-<parts_count>"` (например, `"d41d8cd98f00b204e9800998ecf8427e-3"`).
- **Нельзя** вычислить MD5 всего объекта из ETag multipart upload.

---

## 5. Policy и account limits

### 5.1 Размеры policy

| Resource | Лимит |
|----------|-------|
| Bucket policy | 20 КБ (JSON) |
| Размер объекта | 5 ТБ (max) |
| Multipart upload: количество parts | 10 000 |
| Multipart upload: размер part | 5 МБ – 5 ГБ |
| Lifecycle rules на bucket | 1000 (soft limit) |

### 5.2 Request rate per prefix

| Операция | Лимит на prefix | Примечание |
|----------|----------------|------------|
| PUT/POST/DELETE | 3500 req/s | Случайные prefix'ы увеличивают лимит |
| GET/HEAD | 5500 req/s | Случайные prefix'ы увеличивают лимит |
| LIST | 5500 req/s | На весь bucket |

---

## 6. Consistency edge cases

### 6.1 Ceph RGW consistency model

| Операция | Консистентность |
|----------|----------------|
| PUT (новый объект) | Strong read-after-write |
| PUT (overwrite) | Eventual |
| DELETE | Strong read-after-delete |
| LIST | Eventual |

**Production advice:**
- **Strong consistency** для новых объектов: можно считать RGW source of truth без дополнительных механизмов согласованности.
- **Eventual consistency** для LIST и overwrite: добавьте retry LIST.
- **Strong read-after-delete** для DELETE: объект сразу исчезает.

---

## 7. Best Practices and Debug Logging

### 7.1 Рекомендации по обработке ошибок

1. **Всегда включайте retry** с exponential backoff и jitter для production-клиентов. Без retry кратковременный throttling или 503 приводит к падению приложения.
2. **Используйте `adaptive` retry mode** для high-throughput workloads. AWS SDK автоматически регулирует нагрузку на основе observed latency.
3. **Проверяйте addressing style** для self-hosted RGW: `addressing_style=path`. Неправильный стиль — частая причина `403 SignatureDoesNotMatch`.
4. **Синхронизируйте часы через NTP**. Разница > 15 минут вызывает `403 RequestTimeTooSkewed`.
5. **Используйте multipart upload** для объектов > 100 MB. Это снижает вероятность `RequestTimeout` и `IncompleteBody`.
6. **Включайте версионирование** на production bucket'ах. При `NoSuchKey` после случайного удаления или overwrite можно откатиться через `list-object-versions`.
7. **Мониторьте `rgw_5xx_errors`** и `rgw_requests_total` в Prometheus. Настройте алерты на рост 5xx ошибок.
8. **Документируйте retry конфигурацию** в runbook. При инциденте throttling первое, что проверяют — настроен ли retry.
9. **Для batch операций** используйте Python/Go скрипты с retry вместо кастомных shell-циклов.
10. **Проверяйте bucket policy и ACL** при `AccessDenied` через `aws s3api get-bucket-policy` и `get-bucket-acl`, а не только через UI.

### 7.2 AWS CLI debug

```bash
# Включение debug режима
aws s3 cp file.tar.gz s3://my-bucket/ --debug 2>&1 | tee upload.log

# Debug показывает:
# - HTTP запросы/ответы
# - Headers (включая x-amz-request-id)
# - Retry логи
# - TLS handshake
```

### 7.3 Structured error response

```json
{
  "Error": {
    "Code": "NoSuchKey",
    "Message": "The specified key does not exist.",
    "Resource": "/my-bucket/path/file.tar.gz",
    "RequestId": "3L641ZGA4TQZVQK4",
    "HostId": "a1b2c3d4e5f6...",
    "StatusCode": 404
  }
}
```

### 7.4 Retry-After header

```bash
# При 503 Slow Down или 429 Too Many Requests
# RGW может вернуть Retry-After: 30
# Это означает: повторите запрос через 30 секунд.

# AWS SDK автоматически соблюдает Retry-After в adaptive mode.
```

---

## 8. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: throttling, retry-стратегии и resilience](./throttling-retry.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
