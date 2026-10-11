# S3: throttling, retry-стратегии и resilience

**Актуально для:** S3 API, AWS CLI 2.x, Ceph RGW (Squid 19.x / Tentacle 20.x)

---

## 1. Определения

**Throttling (ограничение запросов)** — механизм S3, защищающий сервис от перегрузки. При превышении лимитов S3 возвращает HTTP `503 Slow Down`. Throttling срабатывает на уровне prefix/bucket и применяется равномерно ко всем аккаунтам в рамках региона.

**Request-rate limits** — максимальное количество операций в секунду, которые S3 обрабатывает без throttling. По умолчанию: **3500 PUT/POST/DELETE** и **5500 GET/HEAD** на **один prefix** в bucket. При добавлении новых prefix лимиты суммируются, что позволяет горизонтально масштабировать throughput. Подробнее о лимитах per prefix см. [error-codes.md](./error-codes.md#52-request-rate-per-prefix).

**Exponential backoff** — стратегия повторных попыток, при которой интервал между попытками экспоненциально увеличивается после каждой ошибки. Используется для снижения нагрузки на S3 при throttling.

**Jitter** — добавление случайной задержки к интервалу backoff для предотвращения thundering herd (синхронизированных повторных попыток множества клиентов одновременно).

**Retry mode (standard / adaptive)** — режим повторных попыток в AWS SDK/CLI. `standard` — фиксированный exponential backoff. `adaptive` — динамическая регулировка на основе observed latency и throttling rate.

**Circuit breaker** — паттерн, при котором клиент перестаёт отправлять запросы к S3 после определённого числа последовательных ошибок, чтобы дать сервису время на восстановление.

**Precondition** — условие, которое S3 проверяет перед выполнением операции (например, `If-Match` с ETag). Используется для предотвращения race conditions при параллельных записях.

---

## 2. Базовые концепции

### 2.1 Почему S3 throttling существует

S3 — это распределённый сервис с shared infrastructure. Throttling защищает от:

- **Noisy neighbor:** один аккаунт/prefix не может monopolise capacity.
- **Cascading failures:** без throttling burst нагрузки мог бы вызвать cascade отказы.
- **Fair queuing:** все клиенты получают предсказуемую долю throughput.

**Важно:** throttling не означает, что вы достигли лимита аккаунта. Это временное замедление на уровне prefix. При правильной архитектуре (много prefix, ключи с случайными префиксами) throttling встречается редко.

### 2.2 Retry strategies

| Стратегия | Описание | Когда использовать |
|-----------|----------|-------------------|
| **Immediate retry** | Повтор без задержки | Только для идемпотентных операций (GET, HEAD, LIST, PUT с idempotency token) |
| **Fixed interval** | Фиксированная задержка между попытками | Простые сценарии, низкая конкуренция |
| **Exponential backoff** | Интервал растёт экспоненциально: `base * 2^attempt` | Рекомендуется для throttling/503 |
| **Decorrelated jitter** | Случайный интервал в диапазоне `[base, min(max, base * 3^attempt)]` | Максимальная эффективность при высокой конкуренции |
| **Adaptive** | Динамическая регулировка на основе feedback | AWS SDK `adaptive` mode |

**Почему jitter важен:** Без jitter тысячи клиентов при throttling начнут повторять запросы одновременно через одинаковый интервал, создавая новый burst. Jitter распределяет попытки во времени.

### 2.3 Exponential backoff formula

```
delay = min(cap, base * 2^attempt) + random_jitter
```

Где:
- `base` — начальная задержка (0.5–1 сек)
- `attempt` — номер попытки (начиная с 0)
- `cap` — максимальная задержка (30–60 сек)
- `random_jitter` — случайное значение 0–1 сек

**Пример для aws-cli:**
```json
{
  "max_attempts": 5,
  "retry_mode": "standard",
  "base_delay": 1.0,
  "max_delay": 30.0
}
```

### 2.4 Идемпотентность и precondition

Повторные попытки безопасны только для идемпотентных операций:

| Операция | Идемпотентная | Precondition для безопасности |
|----------|--------------|-------------------------------|
| PUT Object | Да, с тем же ключом | `If-None-Match: *` (запрет overwrite) |
| GET Object | Да | — |
| DELETE Object | Да | `If-Match: <ETag>` (защита от race) |
| LIST Objects | Да | — |
| POST Object | Нет | Используйте `x-amz-content-sha256` |

**Precondition `If-Match`:**
```bash
# Удаление только если ETag совпадает (защита от race condition)
aws s3api delete-object \
  --bucket my-bucket \
  --key releases/app.tar.gz \
  --if-match "abc123def456"
```

### 2.5 Circuit breaker pattern для S3

Circuit breaker отслеживает ошибки и переводит клиент в состояние `OPEN` при превышении порога:

```
States:
  CLOSED — нормальная работа, запросы проходят
  OPEN — ошибки превысили порог, запросы блокируются
  HALF-OPEN — периодическая проверка, восстановлен ли сервис
```

**Реализация:**
- Порог ошибок: 5 ошибок `503` за 30 секунд → OPEN на 60 секунд.
- В состоянии OPEN все запросы возвращают cached-ответ или ошибку без вызова S3.
- После таймаута переходим в HALF-OPEN: один пробный запрос. Если успех → CLOSED.

---

## 3. Практические сценарии

### 3.0 Предварительные требования

Для работы с retry-стратегиями и throttling mitigation необходимы:

- **AWS CLI 2.x** или **boto3** / **aws-sdk-go-v2** — клиенты с поддержкой retry configuration.
- **Ceph RGW** (Squid 19.x / Tentacle 20.x) с включённым S3 API (`rgw_enable_apis = s3`).
- **Сетевой доступ** до RGW endpoint (порт 7480 HTTP или 443 HTTPS).
- **NTP-синхронизация** на всех клиентах и RGW узлах — разница времени > 15 минут вызывает `403 RequestTimeTooSkewed`.
- **Prometheus + ceph-exporter** — для сбора метрик `rgw_5xx_errors`, `rgw_requests_total`.
- **Valid credentials** — Access Key ID / Secret Key с правами `s3:PutObject`, `s3:GetObject` на целевые bucket'ы.

```bash
# Проверка NTP-синхронизации
chronyc tracking
# или
ntpdate -q pool.ntp.org

# Проверка доступности RGW endpoint
curl -s -o /dev/null -w "%{http_code}" http://rgw:7480
# → 403 или 200 (любой HTTP-ответ, кроме timeout/connection refused)

# Проверка aws-cli
aws --version
# → aws-cli/2.x Python/3.x Linux/...

# Проверка radosgw-admin
radosgw-admin user info --uid="my-user"
# → JSON с секретными ключами и capabilities
```

### 3.1 AWS CLI: настройка retry

```bash
# Глобальная настройка
aws configure set default.max_attempts 5
aws configure set default.retry_mode standard
# retry_mode: standard (рекомендуется) | adaptive

# Или через переменные окружения
export AWS_MAX_ATTEMPTS=5
export AWS_RETRY_MODE=standard

# CLI-level timeout (не retry, но важно для resilience)
aws configure set default.cli_read_timeout 60
aws configure set default.cli_connect_timeout 10
```

**Зачем `cli_read_timeout`:** В production при медленном ответе S3 (например, большие объекты через slow link) CLI может зависнуть. `cli_read_timeout` ограничивает ожидание ответа.

### 3.2 Python (boto3): retry configuration

```python
import boto3
from botocore.config import Config
from botocore.retries import RetryPolicy

config = Config(
    retries={
        'max_attempts': 5,
        'mode': 'standard'  # 'adaptive' для динамической регулировки
    },
    connect_timeout=10,
    read_timeout=60,
    # Для S3-specific throttling
    s3={
        'addressing_style': 'path',
        'payload_signing_enabled': False
    }
)

s3 = boto3.client('s3', region_name='eu-central-1', config=config)

# Использование с precondition для идемпотентности
s3.put_object(
    Bucket='my-bucket',
    Key='data/file.tar.gz',
    Body=data,
    IfNoneMatch='*'  # Запрет overwrite существующего объекта
)
```

**Adaptive mode:** Автоматически анализирует latency и throttling rate, уменьшая concurrency при превышении лимитов. Подходит для high-throughput workloads.

### 3.3 Go (aws-sdk-go-v2): retry configuration

```go
import (
    "github.com/aws/aws-sdk-go-v2/aws/retry"
    "github.com/aws/aws-sdk-go-v2/config"
)

cfg, err := config.LoadDefaultConfig(context.TODO(),
    config.WithRegion("eu-central-1"),
    config.WithRetryer(func() aws.Retryer {
        return retry.NewStandard(func(o *retry.StandardOptions) {
            o.MaxAttempts = 5
        })
    }),
)
```

### 3.4 Presigned URLs с retry-friendly TTL

```bash
# Генерация presigned URL с увеличенным TTL для retry
aws s3 presign s3://my-bucket/data/file.tar.gz \
  --expires-in 7200 \
  --endpoint-url http://rgw:7480
```

**Важно:** Presigned URLs не поддерживают retry automatically. Если URL истёк во время retry — клиент получит `403 Forbidden`. Увеличьте `ExpiresIn` для операций с возможными retry.

### 3.5 Batch operations и retry

В Ceph RGW нет нативного S3 Batch Operations. Для массовых операций используйте Python/Go скрипты:

```python
import boto3
from botocore.config import Config
import time

config = Config(
    retries={'max_attempts': 5, 'mode': 'standard'},
    connect_timeout=10,
    read_timeout=60
)

s3 = boto3.client('s3',
    endpoint_url='http://rgw:7480',
    config=config
)

# Пример: массовое копирование объектов с retry
def batch_copy(source_bucket, dest_bucket, prefix):
    paginator = s3.get_paginator('list_objects_v2')
    retry_count = 0
    for page in paginator.paginate(Bucket=source_bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            try:
                s3.copy_object(
                    Bucket=dest_bucket,
                    Key=obj['Key'],
                    CopySource={'Bucket': source_bucket, 'Key': obj['Key']}
                )
            except s3.exceptions.ClientError as e:
                if e.response['Error']['Code'] == '503':
                    time.sleep(2 ** retry_count)
                    retry_count += 1
                    continue
```

### 3.6 Monitoring throttling через Prometheus

```yaml
# Prometheus alert rule для throttling
groups:
  - name: rgw_alerts
    rules:
      - alert: RGWHigh5xxErrors
        expr: rate(rgw_5xx_errors[5m]) > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Высокое количество 5xx ошибок в RGW"
          description: "{{ $labels.bucket }}: {{ $value }} ошибок/сек"
```

### 3.7 Troubleshooting throttling

**Симптом:** `503 Slow Down` в ответах RGW или `SlowDown` в AWS CLI.

**Диагностика:**
```bash
# Проверка метрик RGW в Prometheus
curl -s http://rgw:9283/metrics | grep rgw_5xx_errors

# Проверка состояния кластера Ceph
ceph health detail
ceph osd perf
```

**Решения:**
1. **Увеличьте retry attempts** и включите `adaptive` mode.
2. **Добавьте jitter** к retry логике.
3. **Распределите ключи по случайным prefix'ам** для параллельного доступа к лимитам.
4. **Увеличьте параллельность** на стороне клиента (max_concurrent_requests).
5. **Уменьшите burst** на стороне клиента (rate limiting).

---

## 4. Edge Cases

### 4.1 Throttling при последовательных запросах к одному prefix

**Симптомы:** Все запросы к одному prefix'у возвращают `503 Slow Down`, хотя другие prefix'ы работают нормально.

**Причина:** Превышен лимит 3500 PUT/POST/DELETE req/s или 5500 GET/HEAD req/s на один prefix.

**Решение:**
- Добавьте 2–8 hex-символов в начало ключа для создания дополнительных prefix'ов.
- Пример: вместо `logs/app.log` → `a3f2/logs/app.log`, `b7c1/logs/app.log`.
- Лимиты суммируются: 3 prefix → 3 × 3500 = 10 500 PUT req/s.

### 4.2 Retry с истекшим presigned URL

**Симптомы:** Клиент получает `403 Forbidden` после retry, хотя первый запрос прошёл успешно.

**Причина:** Presigned URL истёк во время ожидания backoff.

**Решение:**
- Увеличьте `ExpiresIn` до 7200 секунд для операций с retry.
- Или перегенерируйте presigned URL перед каждой retry-попыткой (требует backend involvement).

### 4.3 Circuit breaker срабатывает при maintenance

**Симптомы:** Во время planned maintenance RGW недоступен, circuit breaker переходит в OPEN, клиенты получают cached-ошибки.

**Причина:** Порог ошибок достигнут во время maintenance окна.

**Решение:**
- Увеличьте порог ошибок для planned maintenance (например, 20 ошибок за 60 секунд).
- Добавьте manual override для отключения circuit breaker во время maintenance.
- Используйте HALF-OPEN для пробных запросов во время maintenance.

### 4.4 Adaptive mode при нестабильной сети

**Симптомы:** AWS SDK в `adaptive` mode постоянно уменьшает concurrency, хотя throttling нет.

**Причина:** Высокая latency сети интерпретируется как признак throttling.

**Решение:**
- Используйте `standard` mode при нестабильной сети.
- Или увеличьте порог для adaptive регуляции через `MaxAttempts` и `BaseDelay`.
- Мониторьте `rgw_request_latency_seconds` в Prometheus для区分 network latency от throttling.

### 4.5 Retry при versioned bucket с delete markers

**Симптомы:** После retry DELETE в versioned bucket объект не исчезает, появляется delete marker.

**Причина:** Повторный DELETE создаёт второй delete marker, если первый запрос succeeded но ответ потерян.

**Решение:**
- Используйте `If-Match: <ETag>` для DELETE, чтобы убедиться, что delete marker создан только один раз.
- Или используйте `list-object-versions` для проверки состояния после retry.

---

## 5. Troubleshooting

### 5.1 503 Slow Down (Throttling)

**Симптомы:** S3 возвращает `503 Slow Down` при высоком throughput.

**Диагностика:**
```bash
# Проверка метрик RGW
curl -s http://rgw:9283/metrics | grep rgw_requests_total

# Проверка OSD performance
ceph osd perf
```

**Решение:**
1. Добавьте случайные prefix'ы для ключей.
2. Увеличьте retry attempts и включите jitter.
3. Включите `adaptive` retry mode для SDK.

### 5.2 503 Service Unavailable (не Slow Down)

**Симптомы:** S3 возвращает `503 ServiceUnavailable` без `Slow Down`.

**Диагностика:**
```bash
ceph health detail
ceph osd perf
```

**Решение:**
1. Exponential backoff с cap 60 секунд.
2. Circuit breaker для предотвращения cascade.
3. Проверка OSD и RGW daemons.

### 5.3 429 Too Many Requests

**Симптомы:** S3 возвращает `429 Too Many Requests` с заголовком `Retry-After`.

**Решение:**
1. Соблюдайте `Retry-After` header — это точная рекомендация от S3.
2. Увеличьте interval между запросами на стороне клиента.

### 5.4 Timeout при large upload

**Симптомы:** Загрузка прерывается по таймауту при больших объектах.

**Диагностика:**
```bash
aws configure get default.cli_read_timeout --profile rgw
aws configure get default.s3.multipart_threshold --profile rgw
```

**Решение:**
1. Увеличьте `cli_read_timeout` до 120 секунд.
2. Используйте multipart upload для объектов > 100 MB.
3. Увеличьте `max_concurrent_requests` до 20.

### 5.5 Presigned URL истёк во время retry

**Симптомы:** `403 Forbidden` после retry с presigned URL.

**Решение:**
1. Увеличьте `ExpiresIn` до 7200 секунд.
2. Или перегенерируйте URL перед каждой попыткой.

---

## 6. Best Practices

1. **Всегда используйте retry** с exponential backoff для production-клиентов. Без retry даже кратковременный throttling приведёт к падению приложения.
2. **Включите `adaptive` retry mode** для high-throughput workloads. Она автоматически регулирует нагрузку.
3. **Добавляйте jitter** (случайную задержку) для предотвращения thundering herd.
4. **Используйте случайные prefix'ы** для ключей при высокой нагрузке. Это умножает доступный throughput.
5. **Используйте precondition headers** (`If-Match`, `If-None-Match`) для безопасности при повторных попытках.
6. **Для batch jobs** используйте Python/Go скрипты с retry вместо кастомных shell-скриптов.
7. **Circuit breaker** обязателен для приложений, где RGW — критический путь. Без него retry-loop может усугубить проблему.
8. **Document retry configuration** в runbook. При инциденте throttling первое, что проверяют — настроен ли retry.
9. **Синхронизируйте часы через NTP** на всех клиентах и RGW узлах.
10. **Тестируйте retry логику** в staging с искусственным throttling перед production deploy.

---

## 7. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: error codes и troubleshooting runbook](./error-codes.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
