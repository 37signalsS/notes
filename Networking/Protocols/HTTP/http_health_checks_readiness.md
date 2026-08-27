# Health Checks и Readiness Probes

## Определения

**Health Check (Проверка здоровья)** — механизм определения работоспособности сервиса или его компонентов. В контексте HTTP это обычно HTTP GET-запрос к специальному эндпоинту (`/healthz`, `/ready`, `/live`), возвращающий `200 OK` или `503 Service Unavailable`.

**Liveness Probe** — проверка, которая отвечает на вопрос «Жив ли сервис?». Если liveness probe падает, оркестратор (Kubernetes) перезапускает под (restart).

**Readiness Probe** — проверка, которая отвечает на вопрос «Готов ли сервис принимать трафик?». Если readiness probe падает, оркестратор убирает под из Service (отключает трафик).

**Startup Probe** — проверка для медленно запускающихся приложений. Пока startup probe не проходит, liveness и readiness probes отключены.

**Graceful Degradation (Бережное ухудшение)** — стратегия, при которой сервис при перегрузке отключает неключевые функции, но продолжает обрабатывать критичные запросы.

**Fallback (Запасной вариант)** — запасной ответ или поведение при недоступности основного сервиса. Например, возврат кэшированных данных вместо запроса к упавшему бэкенду.

## Основные концепции

### Типы Health Checks

| Тип | Механизм | Скорость | Надёжность |
| :--- | :--- | :--- | :--- |
| **TCP** | Проверка открытого порта (SYN/ACK) | Очень быстрая | Низкая (порт открыт, но приложение упало) |
| **HTTP** | Проверка HTTP-ответа (код, тело) | Средняя | Высокая (проверяет приложение) |
| **HTTPS** | HTTP-проверка по TLS | Средняя | Высокая (проверяет TLS + приложение) |
| **Script (Command)** | Выполнение команды/скрипта на хосте | Зависит от скрипта | Высокая (проверяет всё: сеть, БД, диск) |
| **gRPC** | Health checking protocol | Средняя | Высокая для gRPC-сервисов |

### Дизайн health endpoint

| Endpoint | Назначение | Проверяет | Возвращаемый код при проблеме |
| :--- | :--- | :--- | :--- |
| `/live` | Liveness | Приложение запущено | `500` / `503` |
| `/ready` | Readiness | Приложение + зависимости готовы | `503` |
| `/healthz` | Общий health | Приложение + зависимости | `200` / `503` |
| `/startup` | Startup | Приложение завершило инициализацию | `200` / `503` |

### Проверки в `/ready`

| Зависимость | Проверка | Пример |
| :--- | :--- | :--- |
| **База данных** | `SELECT 1` | PostgreSQL: `SELECT 1` |
| **Кэш** | `PING` | Redis: `PING` |
| **Очередь** | `list queues` | RabbitMQ: RabbitMQ Management API |
| **Внешний API** | `GET /health` | Внешний сервис доступен |
| **Диск** | `df -h /data` | Свободное место >10% |
| **Memory** | `free -m` | Доступная память >256MB |

### Параметры Kubernetes probes

| Параметр | Назначение | Типичное значение |
| :--- | :--- | :--- |
| `initialDelaySeconds` | Задержка перед первой проверкой | `5`–`30` |
| `periodSeconds` | Интервал проверок | `10` |
| `timeoutSeconds` | Таймаут одной проверки | `1`–`5` |
| `successThreshold` | Успешных проверок для `Ready` | `1` |
| `failureThreshold` | Неудачных проверок для `Not Ready` | `3` |
| `terminationGracePeriodSeconds` | Время на graceful shutdown | `30`–`300` |

## Практические сценарии

### Сценарий 1: Liveness и Readiness в Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
        - name: api
          image: api:latest
          ports:
            - containerPort: 8080
          livenessProbe:
            httpGet:
              path: /live
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 10"]
```

**Валидация:**
- `kubectl get pods` — `READY 1/1`, `STATUS Running`.
- При падении БД: `/ready` возвращает `503`, под убирается из Service (traffic stops).
- При зависании приложения (deadlock): `/live` возвращает `500`, под перезапускается.

### Сценарий 2: Startup probe для медленного старта

```yaml
containers:
  - name: api
    image: api:latest
    startupProbe:
      httpGet:
        path: /startup
        port: 8080
      initialDelaySeconds: 0
      periodSeconds: 5
      timeoutSeconds: 2
      failureThreshold: 30  # 30 × 5s = 150s максимум на старт
    livenessProbe:
      httpGet:
        path: /live
        port: 8080
      initialDelaySeconds: 0
      periodSeconds: 10
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 0
      periodSeconds: 5
      failureThreshold: 3
```

**Валидация:**
- При старте приложение 60 секунд прогревает кэш. Startup probe отключает liveness/readiness на это время.
- После 60 секунд: startup probe проходит, включаются остальные probes.
- Если приложение зависло во время старта: `failureThreshold=30` → после 150 секунд pod перезапускается.

### Сценарий 3: Health endpoint с проверкой зависимостей

```python
from flask import Flask, jsonify
import psycopg2
import redis

app = Flask(__name__)

def check_db():
    try:
        conn = psycopg2.connect("postgresql://app:pass@db:5432/app")
        conn.close()
        return True
    except Exception:
        return False

def check_redis():
    try:
        r = redis.Redis(host="redis", port=6379)
        r.ping()
        return True
    except Exception:
        return False

@app.route("/live")
def live():
    return jsonify({"status": "ok"}), 200

@app.route("/ready")
def ready():
    checks = {
        "database": check_db(),
        "redis": check_redis(),
    }
    if all(checks.values()):
        return jsonify({"status": "ready", "checks": checks}), 200
    return jsonify({"status": "not ready", "checks": checks}), 503

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200
```

**Валидация:**
- `curl http://localhost:8080/ready` — `200 OK` при работающих зависимостях.
- `systemctl stop postgresql` — `/ready` возвращает `503`, Kubernetes убирает pod из Service.
- `curl http://localhost:8080/live` — всегда `200 OK` (если процесс жив).

### Сценарий 4: Graceful degradation

```python
@app.route("/api/search")
def search():
    try:
        # Попытка использовать ML-сервис
        results = ml_service.search(request.args.get("q"))
        return jsonify({"results": results, "source": "ml"}), 200
    except Exception:
        # Fallback: простой поиск по БД
        results = db.search(request.args.get("q"))
        return jsonify({"results": results, "source": "fallback"}), 200
```

**Валидация:**
- `systemctl stop ml-service` — API продолжает работать, возвращает результаты из БД.
- В логах: `WARNING ml_service unavailable, falling back to db`.
- Метрика `search_source{source="fallback"}` растёт.

### Сценарий 5: Fallback to cache при недоступном бэкенде

```nginx
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api:10m max_size=1g inactive=60m;

server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_cache api;
        proxy_cache_valid 200 10m;
        proxy_cache_valid 503 10s;  # Кэшировать ошибки на 10 секунд
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;

        proxy_pass http://api_backend;
    }
}
```

**Валидация:**
- Остановка бэкенда: клиенты получают устаревший контент из кэша (`Age` > 0), а не `502`.
- `curl -I http://api.example.com/` — `X-Cache-Status: HIT` вместо `MISS`.

### Сценарий 6: TCP health check (быстрая проверка)

```haproxy
backend api_servers
    balance roundrobin
    option tcp-check
    server app1 10.0.1.10:8080 check port 8080 inter 3s rise 2 fall 3
    server app2 10.0.1.11:8080 check port 8080 inter 3s rise 2 fall 3
```

**Валидация:**
- Приложение слушает порт, но `/ready` падает (БД недоступна). HAProxy помечает сервер `UP` (TCP порт открыт), но приложения возвращают `503` на запросы.
- Для точности используйте HTTP checks вместо TCP.

### Сценарий 7: Custom health check script (Nginx)

```bash
#!/bin/bash
# /usr/local/bin/healthcheck.sh

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ready)
if [ "$RESPONSE" = "200" ]; then
    echo "OK"
    exit 0
else
    echo "FAIL: $RESPONSE"
    exit 1
fi
```

```nginx
# В upstream
upstream api_backend {
    server 10.0.1.10:8080;
    server 10.0.1.11:8080;
    keepalive 32;
}

# В location с fallback
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://api_backend;
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
    }
}
```

**Валидация:**
- Бэкенд недоступен: Nginx возвращает `502`, но не разрывает соединение с клиентом (proxy_next_upstream перенаправляет на другой бэкенд).

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Readiness flapping** | Pod постоянно добавляется/убирается из Service | `kubectl describe pod` — readiness transitions | Увеличить `failureThreshold`, проверить нестабильные зависимости |
| **Liveness killing healthy pod** | Pod перезапускается без причины | `kubectl logs` — приложение работает | Увеличить `timeoutSeconds`, проверить медленные GC/pauses |
| **Slow dependency check** | Readiness probe > timeout | Логи приложения: медленный `SELECT 1` | Вынести проверку в отдельный endpoint или уменьшить `timeoutSeconds` |
| **Startup probe too aggressive** | Pod не проходит startup probe | `kubectl get pod` — `Init:0/1` | Увеличить `failureThreshold` или `periodSeconds` |
| **Health endpoint leaks** | `/healthz` возвращает `200`, но сервис нерабочий | Проверка вручную: `curl` без контекста | Добавить проверки всех критичных зависимостей |
| **DNS in health check** | Readiness probe падает при DNS-проблемах | `nslookup db` из pod | Использовать внутренний DNS или IP |
| **Resource exhaustion** | Readiness probe падает при высокой нагрузке | `kubectl top pod` — CPU/Memory на 100% | Добавить HPA или увеличить limits |
| **Graceful shutdown too short** | Запросы прерываются при deploy | `kubectl logs` — `SIGTERM` до завершения запросов | Увеличить `terminationGracePeriodSeconds` |
| **PreStop hook ignored** | Pod удаляется без draining | `kubectl get events` — `Killing` без preStop | Убедиться, что preStop hook существует и работает |
| **Health check amplification** | Каждый pod опрашивает БД 6 раз в минуту (3 pods × 2 probes × 1/min) | Метрики БД: лишний load | Использовать TCP checks или уменьшить `periodSeconds` |

## Лучшие практики

1. **Разделяйте `/live`, `/ready`, `/startup`:** Liveness — только проверка процесса. Readiness — процесс + зависимости. Startup — завершение инициализации.
2. **Не блокируйте `/live` зависимостями:** Liveness probe должна проверять только, работает ли процесс. БД может упасть — не перезапускайте pod.
3. **Readiness проверяет всё критичное:** БД, кэш, очередь, внешние API. Если хотя бы одна зависимость недоступна — `503`.
4. **Startup probe для тяжёлых приложений:** Java, Python с ML-моделями, инициализация кэша. Защита от premature kill.
5. **`failureThreshold` ≥ 3:** Одна неудачная проверка — не основание для restart. 3 неудачи подряд — аномалия.
6. **Graceful shutdown ≥ 30s:** Для приложений с долгими запросами. `terminationGracePeriodSeconds: 60` или больше.
7. **PreStop hook для draining:** `sleep 10` (или graceful shutdown API) перед `SIGTERM`. Даёт балансировщику время убрать pod из ротации.
8. **Не кэшируйте `/ready`:** Каждый вызов должен делать реальные проверки. Кэширование скрывает сбои.
9. **Мониторинг probe latency:** Alert, если `probe_duration_seconds` > `timeoutSeconds`. Показывает деградацию.
10. **Документируйте зависимости:** Какие зависимости проверяет `/ready`. Изменения в `/ready` должны быть в changelog.
11. **Health check amplification awareness:** При 100 pods и `periodSeconds=10` получается 600 проверок в минуту. Учитывайте нагрузку на зависимости.
12. **Test health endpoints в CI:** Автоматические тесты на `/live`, `/ready` при каждом деплое.

## Граничные случаи и ограничения

1. **Liveness probe и deadlock:** Если приложение в deadlock, но процесс работает, liveness probe (`/live`) вернёт `200`, и pod не перезапустится. `/live` должен проверять «живой ли процесс», а не «работает ли логика».
2. **Readiness probe и traffic drop:** При падении readiness под убирается из Service, но существующие соединения продолжают обрабатываться до `terminationGracePeriodSeconds`.
3. **Startup probe и memory limit:** Если приложение потребляет > memory limit во время старта, OOMKill сработает до завершения startup probe. Увеличьте `resources.limits.memory`.
4. **TCP check vs HTTP check:** TCP check быстрее, но не проверяет приложение. HTTP check медленнее, но точнее. Используйте HTTP для readines, TCP для быстрой проверки доступности порта.
5. **Probe и network policy:** Если NetworkPolicy блокирует доступ к `/ready` от kubelet, probe всегда падает. Разрешите `from: [kubelet]` на port `readiness`.
6. **`periodSeconds` < `processingTime`:** Если `/ready` выполняется 5 секунд, а `periodSeconds=3`, проверки будут накладываться. Увеличьте `periodSeconds`.
7. **`terminationGracePeriodSeconds` < `shutdown time`:** Приложение не успевает завершить запросы, клиенты получают `502`. Установите `terminationGracePeriodSeconds >= shutdown_time + 5s`.
8. **Health check и load balancer:** Если за Kubernetes стоит внешний LB, он может не обновлять список готовых pod'ов мгновенно. Настройте LB polling interval.
9. **Database connection pool exhaustion:** При старте pod'ов одновременно проверяют readiness, создавая подключения к БД. Используйте connection pool с лимитом.
10. **Probe storm при массовом deploy:** 100 pods одновременно начинают проверять readiness. Всплеск нагрузки на БД. Используйте staggered rollout.

## Дополнительная информация

### Пример `/ready` с gRPC health check

```python
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
health_pb2_grpc.add_HealthServicer_to_server(health.HealthServicer(), server)
server.add_insecure_port('[::]:50051')
server.start()
```

### Сравнение Kubernetes probes

| Probe | Перезапускает pod? | Убирает из Service? | Используется при старте |
| :--- | :--- | :--- | :--- |
| **Liveness** | Да | Нет | После startup |
| **Readiness** | Нет | Да | После startup |
| **Startup** | Да | Нет | При старте (отключает liveness/readiness) |

### Fallback стратегии

| Стратегия | Описание | Пример |
| :--- | :--- | :--- |
| **Cache fallback** | Возврат устаревшего кэша при недоступном бэкенде | `stale-while-revalidate` |
| **Default value** | Возврат значения по умолчанию | `{"items":[]}` вместо `500` |
| **Degraded mode** | Отключение неключевых функций | Отключение рекомендаций при перегрузке |
| **Queue for later** | Постановка запроса в очередь для последующей обработки | `202 Accepted` с `Retry-After` |
| **Circuit breaker + fallback** | Circuit breaker возвращает fallback при открытом состоянии | Кэшированные данные при outage |

## Смотрите также

- **[Коды ответа HTTP](./http_status_codes.md)** — `503 Service Unavailable`.
- **[HTTP-серверы и прокси](./http_servers_proxies.md)** — upstream health checks в Nginx/HAProxy.
- **[Балансировка нагрузки](./http_load_balancing.md)** — active/passive health checks.
- **[Rate Limiting и устойчивость](./http_rate_limiting_circuit_breakers.md)** — circuit breaker, fallback.
- **[HTTP-кэширование](./http_caching.md)** — `stale-while-revalidate`, fallback to cache.
- **[Концепции SRE: SLA, SLO, SLI](../../../Concepts/sre_concepts_main.md)** — надёжность сервисов.
