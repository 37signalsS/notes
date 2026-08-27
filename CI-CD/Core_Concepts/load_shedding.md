# Сброс нагрузки (Load Shedding)

> Load Shedding — паттерн надёжности, при котором сервис сознательно отказывает части входящих запросов (обычно возвращая `503 Service Unavailable` с `Retry-After`), когда собственная пропускная способность исчерпана. Это защищает систему от каскадного отказа и сохраняет качество обслуживания для оставшейся части трафика. Смежные паттерны — в **[Паттернах надёжности](./reliability_patterns.md)**, а хвостовая задержка как сигнал перегрузки — в **[Смягчении хвостовой задержки](../../Concepts/High_Availability/tail_latency_mitigation.md)**.

## Определения

- **Load Shedding (Сброс нагрузки)** — намеренное отбрасывание избыточных запросов при достижении предела ёмкости, чтобы не рухнула вся система.
- **Admission Control (Контроль допуска)** — механизм, решающий, принять ли запрос (по доступной ёмкости или приоритету) до начала его обработки.
- **Tail Latency (Хвостовая задержка)** — высокие перцентили латентности (p95/p99); их рост — первый сигнал перегрузки. Подробно — в **[Смягчении хвостовой задержки](../../Concepts/High_Availability/tail_latency_mitigation.md)**.
- **Priority Load Shedding** — сброс сначала низкоприоритетного трафика (фоновые задачи, preview, неавторизованные), сохраняя критичный.
- **Graceful Degradation (Плавная деградация)** — при нехватке ресурсов сервис продолжает работу в урезанном виде (кэш вместо БД, заглушки вместо второстепенных функций) вместо полного отказа.
- **Static vs Adaptive shedding** — статический сброс по фиксированному порогу против адаптивного, реагирующего на живые метрики (длина очереди, in-flight, CPU).

## Основные концепции

### Почему нужен Load Shedding

При перегрузке (всплеск трафика, деградация зависимости, медленный бэкенд) время обработки растёт нелинейно: очереди заполняются, память исчерпывается, GC и перепланирование усугубляют латентность, и в итоге отказывают **все** запросы, включая те, что могли бы пройти. Load Shedding разрывает этот цикл: отбросив 20% трафика на границе, мы обслуживаем оставшиеся 80% с приемлемой задержкой.

### Чем отличается от Circuit Breaker и Bulkhead

| Паттерн | Что защищает | Триггер |
| :--- | :--- | :--- |
| **Circuit Breaker** | от сломанной зависимости | ошибки на стороне вызываемого сервиса |
| **Bulkhead** | изоляция ресурсов между вызовами | структура пулов и лимитов |
| **Load Shedding** | сам сервис от перегрузки | исчерпание собственной ёмкости (queue/in-flight/CPU) |

Они не исключают, а дополняют друг друга: breaker останавливает исходящие вызовы в упавший сервис, bulkhead не даёт одному потоку съесть все соединения, а shedding — входящий перегрузок на себя.

### Сигналы для сброса

- **Локальные (на узле):** длина очереди запросов, число in-flight запросов, использование CPU, доступная память, время ожидания в очереди (`client_waiting` в пулере — см. **[PgBouncer](../../Databases/PostgreSQL/Operations/pgbouncer_setup.md)**).
- **Глобальные (на границе):** лимиты балансировщика/ингресса, метрики автоскейлера, насыщение downstream.

Правило: сбрасывать лучше на внешней границе (LB/ingress), а не в глубине — чем раньше отброшен запрос, тем меньше ресурсов потрачено.

### Виды сброса

1. **По нагрузке:** отказ при превышении порога (например, > N одновременных запросов) — возврат `503` + `Retry-After`.
2. **По приоритету:** фоновые/batch-запросы сбрасываются первыми; критичные (checkout, auth) проходят.
3. **Деградирующий (Graceful):** вместо ошибки возвращается ослабленный ответ (кэш, stale data, упрощённая страница).

## Практические сценарии

### Сценарий 1: Nginx — лимиты и 503 при перегрузке

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=50r/s;
limit_conn_zone $binary_remote_addr zone=perip:10m;

server {
    location /api/ {
        # не накапливать бесконечную очередь — сразу 503 при превышении
        limit_req zone=api burst=20 nodelay;
        limit_conn perip 10;

        # при перегрузке upstream — вернуть 503 с подсказкой клиенту
        proxy_intercept_errors on;
        error_page 502 503 504 = @overload;
    }

    location @overload {
        add_header Retry-After 2 always;
        return 503 '{"error":"service overloaded, retry later"}';
    }
}
```

**Валидация:** `nginx -t && systemctl reload nginx`; под нагрузкой `ab -n 1000 -c 200 http://localhost/api/` видим часть `503` и заголовок `Retry-After: 2`.

### Сценарий 2: HAProxy — защита по числу соединений

```haproxy
frontend api
    bind :80
    # отбросить соединения, если на backend уже слишком много активных
    use_backend sorry_page if { srv_conn(API) ge 800 }
    default_backend API

backend API
    balance leastconn
    server a1 10.0.1.10:8080 maxconn 200 check
    server a2 10.0.1.11:8080 maxconn 200 check

backend sorry_page
    # статическая заглушка с 503 + Retry-After
    errorfile 503 /etc/haproxy/errors/503.http
```

**Валидация:** `echo "show stat" | socat stdio /var/run/haproxy.sock` показывает число соединений; при ≥800 срабатывает `sorry_page`.

### Сценарий 3: Admission Control на уровне приложения (Go)

```go
package main

import (
    "net/http"
)

// семафор ёмкости: не более N одновременных запросов
var sem = make(chan struct{}, 100)

func handler(w http.ResponseWriter, r *http.Request) {
    select {
    case sem <- struct{}{}:
        defer func() { <-sem }()
        process(w, r)
    default:
        // ёмкость исчерпана — сбрасываем с Retry-After
        w.Header().Set("Retry-After", "1")
        http.Error(w, "overloaded", http.StatusServiceUnavailable)
    }
}

func process(w http.ResponseWriter, r *http.Request) { /* ... */ }

func main() {
    http.ListenAndServe(":8080", http.HandlerFunc(handler))
}
```

**Валидация:** под нагрузкой `wrk -t4 -c 500 -d 10s http://localhost:8080/` часть запросов получает `503`; сервер не падает по памяти/goroutines.

### Сценарий 4: Kubernetes — HPA + готовность как граница сброса

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70   # масштаб до исчерпания ёмкости
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300   # не «душить» при кратковременных всплесках
```

При исчерпании лимита поды уходят в `NotReady` (readiness-проба падает при высокой латентности) — балансировщик перестаёт слать трафик (фактический shedding на уровне оркестратора). Адаптивный вариант по длине очереди — в **[Подготовке к высоким нагрузкам](../../Kubernetes/Concepts/high_load_preparation.md)**.

### Сценарий 5: Graceful Degradation — возврат кэша вместо сбоя

```python
import redis

cache = redis.Redis()

def get_catalog():
    try:
        data = fetch_from_db()
        cache.set("catalog", data, ex=60)
        return data
    except Exception:
        stale = cache.get("catalog")
        if stale:
            return stale   # плавная деградация, а не 503
        raise
```

**Валидация:** при отключении БД пользователь получает устаревший каталог (деградация), а не ошибку.

## Дополнительная информация

### Лучшие практики

1. **Сбрасывай на границе:** ingress/LB отбрасывает раньше, чем трафик достигнет приложения.
2. **Всегда возвращай `Retry-After`:** клиенты корректно повторят позже, снижая шторм повторов.
3. **Сбрасывай низкоприоритетное первым:** фоновые задачи/превью уступают критичным.
4. **Не сбрасывай health/readiness пробы:** иначе оркестратор убьёт уже перегруженный, но живой под.
5. **Мониторь rate сброса как сигнал:** растущий shed-rate — ранний индикатор проблемы и триггер для автоскейла.
6. **Комбинируй с Circuit Breaker и Bulkhead:** они закрывают разные векторы отказа.

### Антипаттерны

- **Сброс без `Retry-After`** — клиенты повторяют немедленно, усугубляя нагрузку.
- **Сброс health-проб** — каскадный kill подов.
- **Сброс критичного трафика** — бизнес теряет ключевые транзакции; используйте приоритеты.
- **Слишком агрессивный порог** — часть запросов сбрасывается при нормальной нагрузке.

### См. также

- [Паттерны надёжности](./reliability_patterns.md) — Circuit Breaker, Bulkhead, Retry, Timeout.
- [Смягчение хвостовой задержки](../../Concepts/High_Availability/tail_latency_mitigation.md) — связь p99 и перегрузки.
- [Подготовка к высоким нагрузкам](../../Kubernetes/Concepts/high_load_preparation.md) — автоскейл и границы ёмкости.
