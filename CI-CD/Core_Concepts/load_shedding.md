# Сброс нагрузки (Load Shedding)

> Load Shedding — паттерн надёжности, при котором сервис сознательно отказывает части входящих запросов (обычно возвращая `503 Service Unavailable` с `Retry-After`), когда собственная пропускная способность исчерпана. Это защищает систему от каскадного отказа и сохраняет качество обслуживания для оставшейся части трафика. Смежные паттерны — в **[Паттернах надёжности](./reliability_patterns.md)**, а хвостовая задержка как сигнал перегрузки — в **[Смягчении хвостовой задержки](../../Concepts/High_Availability/tail_latency_mitigation.md)**.

## Определения

- **Load Shedding (Сброс нагрузки)** — намеренное отбрасывание избыточных запросов при достижении предела ёмкости, чтобы не рухнула вся система.
- **Admission Control (Контроль допуска)** — механизм, решающий, принять ли запрос (по доступной ёмкости или приоритету) до начала его обработки.
- **Tail Latency (Хвостовая задержка)** — высокие перцентили латентности (p95/p99); их рост — первый сигнал перегрузки. Подробно — в **[Смягчении хвостовой задержки](../../Concepts/High_Availability/tail_latency_mitigation.md)**.
- **Priority Load Shedding** — сброс сначала низкоприоритетного трафика (фоновые задачи, preview, неавторизованные), сохраняя критичный.
- **Graceful Degradation (Плавная деградация)** — при нехватке ресурсов сервис продолжает работу в урезанном виде (кэш вместо БД, заглушки вместо второстепенных функций) вместо полного отказа.
- **Static vs Adaptive shedding** — статический сброс по фиксированному порогу против адаптивного, реагирующего на живые метрики (длина очереди, in-flight, CPU).
- **Shed Rate** — доля сброшенных запросов к общему числу входящих; ключевая метрика для SRE/DevOps.
- **Retry-After** — заголовок ответа `503`, указывающий клиенту, когда повторить запрос; без него клиенты повторяют немедленно, усугубляя шторм.

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

### Контекст SRE / DevOps / Sysadmin

#### SRE

- **SLO-бюджет:** растущий shed-rate — ранний индикатор приближения к нарушению SLO; алерт на рост `shed_rate > 5%` за 5 минут позволяет вмешаться до потери ошибкоёмкости.
- **Инцидент-менеджмент:** shedding виден в логах/трассировках как `503` с заголовком `Retry-After`; при расследовании отличить shedding от отказа backend-а помогает заголовок.
- **Наблюдаемость:** метрики shedding-rate, in-flight, queue length, p99 latency экспортируются в Prometheus/Grafana; дашборд shedding — часть стандартного набора SRE.

#### DevOps

- **GitOps:** конфигурации shedding (nginx `limit_req_zone`, HAProxy `maxconn`, HPA behavior) хранятся в Git, проходят review и применяются через CI/CD.
- **Тестирование:** пайплайн включает нагрузочный прогон (`wrk`, `k6`, `vegeta`) с валидацией, что при превышении порога возвращается `503` + `Retry-After`, а не `200` с ошибкой внутри тела.
- **Инфраструктура как код:** Ansible/Terraform применяют конфигурации ограничений на всех окружениях единообразно.

#### Sysadmin

- **Ограничения ядра и systemd:** `LimitNOFILE`, `LimitNPROC` в unit-файле; `/proc/sys/net/core/somaxconn` и `/proc/sys/net/ipv4/tcp_max_syn_backlog` — глобальные лимиты, при превышении которых ядро начинает отбрасывать SYN/пакеты до того, как запрос достигнет приложения.
- **cgroup v2:** `cpu.max` и `memory.max` ограничивают ресурсы контейнера/группы; при достижении лимита kernel OOM-killer или throttling — фактический shedding на уровне ОС.
- **Аудит:** `journalctl -u nginx --since "1 hour ago" | grep "limiting requests"` или `grep "worker_connections"` для анализа истощений.

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

### Сценарий 6: Sysadmin — лимиты systemd и cgroup v2

```ini
# /etc/systemd/system/api.service
[Service]
LimitNOFILE=65536
LimitNPROC=512
Environment="GOGC=50"
```

При превышении `LimitNOFILE` приложение получает `EMFILE` и начинает отказывать в открытии новых соединений. `GOGC=50` заставляет Go-рантайм агрессивнее собирать мусор, снижая пик памяти под нагрузкой. В cgroup v2 (если сервис запускается через `.slice`) аналогичные ограничения задаются через `cpu.max` и `memory.max`.

**Валидация:** `systemctl daemon-reload && systemctl restart api`; `systemctl show api -p LimitNOFILE,LimitNPROC`; при нагрузке `journalctl -u api -f` видим `too many open files` или `out of memory` до того, как процесс будет убит.

## Операции и команды

### Nginx — проверка и применение лимитов

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `nginx -t` | Валидация конфигурации перед релоадом | `nginx: configuration file /etc/nginx/nginx.conf test is successful` |
| `systemctl reload nginx` | Применить лимиты без сброса соединений | `# →` (выход 0) |
| `curl -I http://localhost/api/` | Проверка заголовков, включая `Retry-After` при 503 | `HTTP/1.1 503` + `Retry-After: 2` |
| `ab -n 1000 -c 200 http://localhost/api/` | Нагрузочный тест, проверка части 503 | `503 responses: 42` |

### HAProxy — мониторинг состояния бэкендов

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `echo "show stat" | socat stdio /var/run/haproxy.sock` | Статистика по серверам и очередям | строка с `srv_conn` ≥ 800 при срабатывании `sorry_page` |
| `echo "show info" | socat stdio /var/run/haproxy.sock` | Общие счётчики | `Uptime`, `ConnRate`, `CurrConns` |
| `echo "show errors" | socat stdio /var/run/haproxy.sock` | Очереди ошибок shedding | пусто при штатной работе |

### Sysadmin — лимиты и аудит

| Команда | Описание |
| :--- | :--- |
| `systemctl show api -p LimitNOFILE,LimitNPROC` | Проверка лимитов systemd |
| `ulimit -n` | Текущий лимит открытых файлов в shell |
| `cat /proc/sys/net/core/somaxconn` | Глобальный лимит очереди listen() |
| `cat /sys/fs/cgroup/cpu.max` | Лимит CPU в cgroup v2 |
| `journalctl -u nginx --since "1 hour ago" | grep limiting` | Поиск событий ограничения запросов |
| `ss -s` | Сводка по сокетам: `inestab`, `mem` |

### Prometheus — мониторинг shedding

| Запрос | Описание |
| :--- | :--- |
| `rate(nginx_http_503_total[5m])` | Рост 503 из nginx |
| `rate(haproxy_backend_http_responses_total{code="503"}[5m])` | 503 от балансировщика |
| `sum(rate(container_cpu_cfs_throttled_seconds_total[5m])) by (pod)` | CPU throttling в контейнерах |
| `node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes` | Доступная память на узле |

### Тестирование перегрузки

| Инструмент | Команда | Описание |
| :--- | :--- | :--- |
| `wrk` | `wrk -t4 -c 500 -d 10s http://localhost:8080/` | Проверка shedding в Go-приложении |
| `ab` | `ab -n 1000 -c 200 http://localhost/api/` | HTTP-нагрузка на Nginx/HAProxy |
| `k6` | `k6 run --vus 500 --duration 30s script.js` | Скриптовая нагрузка с метриками |

## Типичные ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **503 без `Retry-After`** | Конфиг LB/ingress не добавляет заголовок | Добавить `add_header Retry-After 2 always;` в Nginx или настроить errorfile в HAProxy |
| **Шторм повторов при 503** | Клиенты ретраят без backoff | Внедрить exponential backoff + jitter на стороне клиента; рассмотреть `Retry-After` с растущим значением |
| **Слишком агрессивный порог** | Обычная нагрузка триггерит shedding | Снизить burst/nodelay; перейти на адаптивный порог по p99 или очереди |
| **Сброс health-проб** | `readinessProbe` попадает под лимит | Исключить `/-/health`, `/healthz` из `limit_req_zone` в Nginx; в Kubernetes настроить `failureThreshold` |
| **Shedding не срабатывает** | Лимит задан на неправильном уровне (приложение, а не граница) | Перенести лимит на ingress/LB; приложение само не сбросит трафик, только вернёт 503 |
| **Потеря трафика при scale-down** | HPA/Cluster Autoscaler удаляет поды во время всплеска | Настроить `scaleDown.stabilizationWindowSeconds` ≥ 300; использовать `maxUnavailable: 0` в Deployment |

## Лучшие практики

1. **Сбрасывай на границе:** ingress/LB отбрасывает раньше, чем трафик достигнет приложения.
2. **Всегда возвращай `Retry-After`:** клиенты корректно повторят позже, снижая шторм повторов.
3. **Сбрасывай низкоприоритетное первым:** фоновые задачи/превью уступают критичным.
4. **Не сбрасывай health/readiness пробы:** иначе оркестратор убьёт уже перегруженный, но живой под.
5. **Мониторь rate сброса как сигнал:** растущий shed-rate — ранний индикатор проблемы и триггер для автоскейла.
6. **Комбинируй с Circuit Breaker и Bulkhead:** они закрывают разные векторы отказа.
7. **Тестируй shedding в CI/CD:** нагрузочные прогоны подтверждают, что при превышении порога возвращается `503`, а не падение сервиса.
8. **Храни конфиг в Git:** ограничения (`limit_req_zone`, HAProxy `maxconn`, HPA behavior) — часть инфраструктуры как код, проходят code review.
9. **Согласуй лимиты с SLO:** порог shedding должен быть ниже точки, где p99 начинает деградировать до нарушения SLO.

## Граничные случаи (Edge Cases)

- **Warm-up / холодный старт:** после деплоя поды/инстансы «греются» (кэш, JIT, пул соединений). Агрессивный shedding на старте может отбросить весь трафик. Решение: исключить период разогрева из лимитов через feature flag или отдельный ingress.
- **Миграция / draining:** при `kubectl drain` или `systemctl stop` поды gracefully завершают соединения. Shedding на этом этапе не нужен, но readinessProbe должен успеть убрать под из балансировки до SIGTERM.
- **Гибридный трафик (gRPC + HTTP):** gRPC не всегда корректно обрабатывает `Retry-After`; для него лучше использовать GRPC `UNAVAILABLE` с метаданными `retry-delay`.
- **Stateful сервисы:** при сбросе запроса к сервису с очередью (RabbitMQ, Kafka producer) часть сообщений может потеряться или застрять. Используйте подтверждения (`ack`) и persistent storage.

## Белые пятна и вызовы (Антипаттерны)

- **Сброс без `Retry-After`** — клиенты повторяют немедленно, усугубляя нагрузку.
- **Сброс health-проб** — каскадный kill подов.
- **Сброс критичного трафика** — бизнес теряет ключевые транзакции; используйте приоритеты.
- **Слишком агрессивный порог** — часть запросов сбрасывается при нормальной нагрузке.
- **Shedding вместо масштабирования** — сброс — временная мера; при стабильном росте нагрузки нужен auto-scaling или увеличение capacity.

## Дополнительная информация

### См. также

- [Паттерны микросервисной архитектуры](../../Concepts/microservice_patterns.md) — отказоустойчивость и масштабируемость.
- [Паттерны надёжности](./reliability_patterns.md) — Circuit Breaker, Bulkhead, Retry, Timeout.
- [Смягчение хвостовой задержки](../../Concepts/High_Availability/tail_latency_mitigation.md) — связь p99 и перегрузки.
- [Подготовка к высоким нагрузкам](../../Kubernetes/Concepts/high_load_preparation.md) — автоскейл и границы ёмкости.
