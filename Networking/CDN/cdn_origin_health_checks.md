# CDN — Health Checks, Circuit Breaker и Origin Failover

## Определения

- **Origin Health Check**: Механизм мониторинга доступности Origin-сервера со стороны CDN. CDN регулярно отправляет probe-запросы на Origin и исключает его из балансировки при обнаружении сбоев.
- **Circuit Breaker (Прерыватель цепи)**: Паттерн проектирования, автоматически приостанавливающий запросы к неработающему Origin на заданное время, после чего试探но возобновляющий их. Предотвращает каскадные сбои (Cascade Failure).
- **Half-Open State**: Промежуточное состояние Circuit Breaker, в котором CDN делает试探ный (ограниченный) запрос к Origin для проверки его восстановления.
- **Origin Failover**: Автоматическое переключение трафика на резервный Origin при отказе основного. CDN поддерживает список Origin Servers с приоритетами.
- **Passive Health Check**: Метод определения здоровья Origin на основе анализа реальных ответов пользователей (5xx ошибки, таймауты), без специальных probe-запросов.
- **Active Health Check**: Метод определения здоровья Origin путём периодической отправки synthetic (синтетических) запросов на определённый endpoint (например, `/healthz`).
- **Retry Budget (Бюджет повторных попыток)**: Ограничение максимального количества повторных попыток для предотвращения каскадных сбоев. Если Origin не отвечает, CDN не будет бесконечно повторять запросы.
- **Timeout (Таймаут)**: Максимальное время ожидания ответа от Origin. При превышении CDN считает запрос неуспешным и может вернуть кэшированный ответ или ошибку.
- **Graceful Degradation (Изящная деградация)**: Стратегия, при которой при отказе Origin CDN продолжает отдавать кэшированный контент (stale) вместо полного прерывания сервиса.
- **Origin Shield Circuit Breaker**: Circuit Breaker на уровне Origin Shield, предотвращающий массовые запросы к-Origin при его недоступности.

---

## Теория

### Архитектура Health Checks

CDN-провайдеры используют комбинацию активных и пассивных проверок для определения состояния Origin:

**Активные проверки (Active):**
- Периодическая отправка HTTP/HTTPS запросов на определённый endpoint (обычно `/healthz`, `/ready`, `/status`).
- Интервал: от 10 секунд (Cloudflare) до 60 секунд (CloudFront).
- Порог: после N неуспешных подряд подряд (по умолчанию 3) Origin помечается как DOWN.
- Восстановление: после M успешных подряд подряд Origin помечается как UP.

**Пассивные проверки (Passive):**
- Анализ реальных ответов CDN на пользовательские запросы.
- При количестве 5xx ошибок выше порога (например, 50% за последние 60 секунд) Origin помечается как DOWN.
- Преимущество: не требует额外ного трафика; недостаток: задержка обнаружения.

**Гибридные проверки (Hybrid):**
- Используют комбинацию Active + Passive для максимальной точности.
- CDN отключает Origin при совпадении Active FAIL + Passive FAIL.

### Модель Circuit Breaker

Circuit Breaker работает в трёх состояниях:

```
[Closed] → (порог ошибок) → [Open] → (таймаут) → [Half-Open] → (успех) → [Closed]
                                                              → (ошибка) → [Open]
```

**Closed (Замкнутое):**
- Нормальный режим. Все запросы проходят к Origin.
- При превышении порога ошибок (например, 50% за 60 сек) → переход в Open.

**Open (Разомкнутое):**
- Все запросы к Origin блокируются. CDN возвращает кэшированный контент или ошибку.
- Через заданное время (например, 30 секунд) → переход в Half-Open.

**Half-Open (Полуоткрытое):**
- CDN делает试探ный запрос к Origin (обычно 1 из N запросов).
- Если Origin ответил успешно → Closed (нормальный режим).
- Если Origin ответил ошибкой → Open (блокировка продолжается).

### Origin Failover: Приоритеты и балансировка

CDN поддерживает несколько Origin Servers с настраиваемыми приоритетами:

**Конфигурация (Cloudflare):**
```
Origin 1: origin-primary.example.com (Priority: 1, Weight: 1)
Origin 2: origin-secondary.example.com (Priority: 2, Weight: 1)
Origin 3: origin-tertiary.example.com (Priority: 3, Weight: 1)
```

**Логика переключения:**
1. Все запросы направляются на Origin с наивысшим приоритетом (1).
2. При отказе Origin 1 (Circuit Breaker сработал) → запросы переключаются на Origin 2.
3. При отказе Origin 2 → запросы переключаются на Origin 3.
4. При восстановлении Origin 1 → трафик возвращается ( Gradual Return / Slow Recovery ).

### Retry Budget и Retry Strategy

**Проблема Retry Storm:**
При падении Origin каждый CDN-узел делает retry, что увеличивает нагрузку на Origin в N раз (где N = количество PoP × количество retry).

**Решение — Retry Budget:**
- Ограничение: не более 20% запросов от общего трафика могут быть retry.
- При превышении бюджета CDN прекращает retry и возвращает ошибку.
- Cloudflare: автоматический Retry Budget для всех запросов.
- Fastly: настраиваемый `first_byte_timeout` + `between_bytes_timeout`.

**Стратегии retry:**
| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Fixed Interval** | Ожидание фиксированного времени между retry | Простые сценарии |
| **Exponential Backoff** | Удвоение интервала с каждым retry | Стандарт для API |
| **Exponential Backoff + Jitter** | Backoff + случайное смещение | Рекомендуется для CDN |
| **Retry-After** | Использование заголовка Retry-After от сервера | При наличии заголовка |
| **Budget-limited** | Ограничение общего числа retry | Масштабные системы |

### Таймауты в CDN

| Параметр | Описание | Типичные значения |
| :--- | :--- | :--- |
| **Connect Timeout** | Время на установку TCP-соединения с Origin | 5-10 сек |
| **First Byte Timeout (TTFB)** | Время ожидания первого байта ответа | 30-60 сек (Cloudflare), 10-60 сек (Fastly) |
| **Between Bytes Timeout** | Время между байтами ответа (для стриминга) | 10-30 сек |
| **Max Upload Size** | Максимальный размер тела запроса | 100 МБ (Cloudflare Free), 500 МБ (Enterprise) |
| **WebSocket Timeout** | Время жизни WebSocket-соединения | 100 сек (Cloudflare), настраивается (Fastly) |

---

## Практика

### Cloudflare: Origin Health Checks

```bash
# Включение Health Checks через API
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/{zone_id}/load_balancers/{lb_id}" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" \
  --data '{
    "monitor": {
      "type": "https",
      "expected_codes": "200",
      "method": "GET",
      "path": "/healthz",
      "header": "Host: example.com",
      "timeout": 5,
      "retries": 3,
      "interval": 60,
      "expected_body": ""
    }
  }'
# → {"result":{"id":"...","monitor":{"type":"https","expected_codes":"200",...}}}
```

**Настройка Failover Pool:**
```bash
# Создание Origin Pool с failover
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/load_balancers/pools" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "primary-origin",
    "origins": [
      {"name": "origin-1", "address": "192.0.2.1", "enabled": true, "weight": 1},
      {"name": "origin-2", "address": "192.0.2.2", "enabled": true, "weight": 1}
    ],
    "minimum_origins": 1,
    "monitor": "monitor_id",
    "notification_email": "ops@example.com"
  }'
```

### Fastly: Health Checks и Failover

```bash
# Настройка Health Check для backend
curl -X POST "https://api.fastly.com/service/{service_id}/version/{version}/healthcheck" \
  -H "Fastly-Key: {api_token}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "origin-health",
    "method": "GET",
    "host": "origin.example.com",
    "path": "/healthz",
    "timeout": 5000,
    "window": 5,
    "threshold": 3,
    "check_interval": 10000
  }'
# → {"name":"origin-health","method":"GET",...}

# Настройка backend с failover
curl -X PUT "https://api.fastly.com/service/{service_id}/version/{version}/backend/{backend_name}" \
  -H "Fastly-Key: {api_token}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "primary",
    "hostname": "origin-primary.example.com",
    "port": 443,
    "use_ssl": true,
    "ssl_check_cert": true,
    "connect_timeout": 5000,
    "first_byte_timeout": 60000,
    "between_bytes_timeout": 10000,
    "max_conn": 200,
    "healthcheck": "origin-health",
    "shield": "sjc-ca-us"
  }'
```

### AWS CloudFront: Origin Failover

```bash
# 1. Создание Origin Access Control (OAC)
aws cloudfront create-origin-access-control \
  --origin-access-control-config '{
    "Name": "primary-oac",
    "OriginAccessControlOriginType": "s3",
    "SigningBehavior": "always",
    "SigningProtocol": "sigv4"
  }'

# 2. Создание Origin Groups (Primary + Failover)
aws cloudfront create-origin-group \
  --distribution-id E1234567890ABC \
  --origin-group '{
    "Id": "origin-failover-group",
    "FailoverCriteria": {
      "StatusCodes": {
        "Items": [500, 502, 503, 504],
        "Quantity": 4
      }
    },
    "Members": {
      "Items": [
        {"OriginId": "primary-s3"},
        {"OriginId": "failover-s3"}
      ],
      "Quantity": 2
    }
  }'
```

### Nginx: Circuit Breaker (OpenResty/Lua)

```lua
-- openresty/lualib/circuit_breaker.lua
local _M = {}
local threshold = 10      -- количество ошибок для tripping
local timeout = 30        -- секунды до Half-Open
local errors = 0
local state = "closed"    -- closed, open, half_open
local last_failure = 0

function _M.record(status_code)
    if status_code >= 500 then
        errors = errors + 1
        if errors >= threshold then
            state = "open"
            last_failure = os.time()
        end
    else
        errors = 0
        state = "closed"
    end
end

function _M.allow_request()
    if state == "closed" then
        return true
    elseif state == "open" then
        if os.time() - last_failure > timeout then
            state = "half_open"
            return true  --试探ный запрос
        end
        return false
    else -- half_open
        return true  --试探ный запрос
    end
end

return _M
```

**Nginx: Retry и таймауты:**
```nginx
upstream origin_cluster {
    server origin-1.example.com:443 max_fails=3 fail_timeout=30s;
    server origin-2.example.com:443 max_fails=3 fail_timeout=30s;

    # Keep-alive к Origin
    keepalive 32;
    keepalive_timeout 60s;
}

server {
    location / {
        proxy_pass https://origin_cluster;

        # Таймауты
        proxy_connect_timeout 5s;     # Таймаут соединения
        proxy_read_timeout 60s;       # Таймаут чтения ответа
        proxy_send_timeout 10s;       # Таймаут отправки

        # Retry при ошибках
        proxy_next_upstream error timeout http_502 http_503 http_504;
        proxy_next_upstream_timeout 10s;  # Общий таймаут retry
        proxy_next_upstream_tries 2;      # Максимум 2 попытки

        # Keep-alive
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### Мониторинг Health Checks

**Метрики для наблюдения:**

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `origin_health_status` | 1 = UP, 0 = DOWN | При DOWN > 60 сек |
| `origin_5xx_rate` | Процент 5xx ответов Origin | >5% за 5 минут |
| `origin_latency_p99` | 99-й процентиль задержки Origin | >500 мс |
| `circuit_breaker_trips` | Количество срабатываний Circuit Breaker | >0 за 5 минут |
| `retry_rate` | Процент retry-запросов | >10% за 5 минут |
| `failover_events` | Количество переключений Origin | >0 за 1 час |

**Prometheus:**
```yaml
# Метрики Circuit Breaker
- record: origin:circuit_breaker_trips:rate5m
  expr: rate(circuit_breaker_trip_total[5m])

# Метрики failover
- record: origin:failover_rate:rate1h
  expr: rate(origin_failover_total[1h])
```

---

## Дополнительная информация

### Типичные ошибки и их решение

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Циклический Failover** | Трафик постоянно переключается между Origin | Health Check слишком чувствительный | Увеличить threshold и interval |
| **Cascading Failure** | Все Origin падают одновременно | Retry Storm без Retry Budget | Включить Retry Budget |
| **False Positive** | Origin помечен как DOWN, но он работает | Health Check endpoint зависает | Проверить timeout и path |
| **Split-Brain** | Часть PoP видит Origin UP, часть DOWN | Нестабильная сеть между PoP и Origin | Использовать Origin Shield |

### Связанные темы

- **[Обзор CDN](cdn_overview.md)** — архитектура и принципы работы сети доставки контента.
- **[Политики кэширования](cdn_caching_and_invalidation.md)** — `stale-if-error`, `must-revalidate` и их связь с Origin Health.
- **[Механизмы Failover и Heartbeat](../../Concepts/High_Availability/ha_failover_mechanisms.md)** — теория отказоустойчивости.
- **[Высокая доступность: Обзор](../../Concepts/High_Availability/ha_overview.md)** — архитектурные паттерны HA.
