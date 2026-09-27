# Тестирование Resilience-паттернов через Chaos Engineering

## Определения

**Resilience-паттерны** — это архитектурные конструкции, повышающие устойчивость распределенных систем к сбоям: Circuit Breaker, Bulkhead, Rate Limiter, Timeout, Retry, Fallback. Chaos Engineering используется для проверки того, что эти паттерны работают в production, а не только в документации.

**Circuit Breaker Testing** — валидация того, что предохранитель переключается в `Open` при превышении порога ошибок и возвращается в `Half-Open` после восстановления зависимости.

**Bulkhead Testing** — проверка изоляции ресурсов (пулов соединений, потоков) между критичными и некритичными вызовами.

**Rate Limiter Testing** — валидация того, что лимитер защищает downstream-сервис при всплеске трафика, а не просто отбрасывает запросы без разбора.

**Timeout Testing** — проверка корректности таймаутов на всех уровнях: LB, прокси, клиентский SDK, база данных.

**Retry Testing** — валидация retry-политики: точное количество повторов, exponential backoff, jitter, защита от retry storm.

**Fallback Testing** — проверка graceful degradation: при отказе зависимости система возвращает дефолтный ответ, кэш или статику, а не 500/502.

## Основные концепции

### Зачем тестировать resilience-паттерны через хаос

В production паттерны часто настроены некорректно:
- Circuit Breaker никогда не открывался из-за слишком высокого порога.
- Bulkhead разделял пулы только на уровне кода, но не на уровне ОС.
- Timeout отсутствовал на уровне клиента, только на уровне сервера.
- Retry без backoff создавал шторм запросов.
- Fallback падал с собственной ошибкой.

Chaos Engineering позволяет выявить эти проблемы до реального инцидента.

### Подход к тестированию

```
1. Определите паттерн и его место в архитектуре.
2. Зафиксируйте baseline: latency, error rate, RPS в нормальном состоянии.
3. Выберите сценарий сбоя, который паттерн должен нейтрализовать.
4. Инжектируйте сбой с контролируемым blast radius.
5. Наблюдайте за состоянием паттерна и метриками.
6. Утвердите критерии успеха: паттерн сработал, система деградировала gracefully.
7. Остановите эксперимент, очистите ресурсы.
```

### Интеграция с observability

Для валидации паттернов требуется:
- Метрики состояния Circuit Breaker: `state=closed|open|half-open`, `failure_rate`, `slow_call_rate`.
- Метрики Bulkhead: размер пула, `active_connections`, `waiting_requests`.
- Метрики Rate Limiter: `allowed_requests`, `rejected_requests`, `remaining_quota`.
- Метрики Retry: `retry_attempts`, `retry_success_rate`, `retry_storm_detected`.
- Метрики Fallback: `fallback_invocations`, `fallback_error_rate`.

## Практические сценарии

### Сценарий 1: Circuit Breaker validation

**Цель:** Убедиться, что Circuit Breaker открывается при 50% ошибок и возвращается в `Half-Open` после восстановления.

**Инструмент:** Chaos Mesh + Prometheus + Jaeger.

**Шаги:**

1. **Определите baseline:** latency p99 < 200ms, error rate < 0.1%.
2. **Инжектируйте сбой:** 500ms задержка на 50% трафика к `payment-service`.
3. **Наблюдайте:**
   - Circuit Breaker должен перейти в `Open` в течение 10 секунд.
   - Error rate не должен превышать 5%.
   - Fallback (кэш) должен обслуживать запросы.
4. **Восстановите зависимость:** удалите задержку.
5. **Проверьте Half-Open:** Circuit Breaker должен начать пропускать пробные запросы через 30 секунд.

**Манифест Chaos Mesh:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: circuit-breaker-test
  namespace: chaos-testing
spec:
  action: delay
  mode: fixed-percent
  fixedValue: 50
  selector:
    namespaces:
      - production
    labelSelectors:
      app: payment-service
  delay:
    latency: "500ms"
    jitter: "100ms"
  duration: "5m"
```

**Прометей-проверка:**

```promql
# Circuit Breaker state (если экспортируется)
rate(circuit_breaker_state_changes_total{state="open"}[5m]) > 0

# Error rate не превышает 5%
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) < 0.05

# Fallback активен
rate(fallback_invocations_total[5m]) > 0
```

### Сценарий 2: Bulkhead isolation test

**Цель:** Проверить, что всплеск нагрузки на фоновые задачи не влияет на критичные API.

**Инструмент:** k6 (нагрузка) + Chaos Mesh (CPU hog на фоновые поды).

**Шаги:**

1. **Настройте Bulkhead:** `payment-service` имеет отдельный пул соединений для `critical-api` и `background-jobs`.
2. **Генерация нагрузки:** k6 создает 1000 RPS к critical-api.
3. **Инжектируйте сбой:** CPU hog 80% на поды `background-jobs`.
4. **Наблюдайте:**
   - Critical API latency p99 остается < 500ms.
   - Background jobs отстают, но не влияют на critical API.
   - Нет каскадного сбоя.

**Манифест Chaos Mesh:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: bulkhead-test
  namespace: chaos-testing
spec:
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: background-jobs
  stressors:
    cpu:
      workers: 4
      load: 80
  duration: "3m"
```

**k6 скрипт:**

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 1000 },
    { duration: '2m', target: 1000 },
    { duration: '30s', target: 0 },
  ],
};

export default function () {
  const res = http.get('http://payment-service/api/critical');
  check(res, {
    'status is 200': (r) => r.status === 200,
    'latency < 500ms': (r) => r.timings.duration < 500,
  });
  sleep(0.01);
}
```

### Сценарий 3: Rate Limiter validation

**Цель:** Проверить, что Rate Limiter защищает downstream при 3x всплеске трафика.

**Инструмент:** k6 + Toxiproxy.

**Шаги:**

1. **Настройте Rate Limiter:** 1000 RPS на `api-gateway`.
2. **Генерация нагрузки:** k6 создает 3000 RPS.
3. **Наблюдайте:**
   - Rate Limiter отклоняет лишние запросы с 429.
   - Downstream `backend-service` не получает более 1000 RPS.
   - Нет ошибок 500/502 на downstream.

**Toxiproxy + k6:**

```bash
# Создаем прокси
curl -X POST http://localhost:8474/proxies -d '{
  "name":"api-gateway",
  "listen":"0.0.0.0:8080",
  "upstream":"api-gateway:8080",
  "enabled":true
}'

# k6 генерирует 3000 RPS
k6 run --vus 300 --duration 2m script.js
```

**Прометей-проверка:**

```promql
# Rate Limiter отклоняет запросы
rate(http_requests_total{status="429"}[5m]) > 0

# Downstream не перегружен
rate(http_requests_total{job="backend-service"}[5m]) < 1100
```

### Сценарий 4: Timeout cascade test

**Цель:** Проверить, что таймауты настроены корректно и не создают каскадный отказ.

**Инструмент:** Chaos Mesh + Prometheus.

**Шаги:**

1. **Инжектируйте задержку:** 10s задержка на `database-proxy` (больше, чем timeout клиента 5s).
2. **Наблюдайте:**
   - Клиент получает 504 Gateway Timeout, а не зависает.
   - Нет накопления соединений в `TIME_WAIT`.
   - Connection pool освобождается корректно.

**Манифест:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: timeout-cascade-test
spec:
  action: delay
  mode: one
  selector:
    labelSelectors:
      app: database-proxy
  delay:
    latency: "10s"
  duration: "2m"
```

### Сценарий 5: Retry storm prevention

**Цель:** Проверить, что retry-политика предотвращает шторм повторов при отказе зависимости.

**Инструмент:** Chaos Mesh + k6.

**Шаги:**

1. **Настройте Retry:** max 3 attempts, exponential backoff 1s/2s/4s, jitter ±20%.
2. **Инжектируйте сбой:** 100% ошибки (abort) на `auth-service`.
3. **Генерация нагрузки:** k6 создает 500 RPS к `api-gateway`.
4. **Наблюдайте:**
   - Общий RPS не превышает 1500 (500 * 3 max retries).
   - Нет экспоненциального роста RPS.
   - auth-service получает нагрузку < 1500 RPS.

**Манифест:**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: retry-storm-test
spec:
  action: abort
  mode: fixed-percent
  fixedValue: 100
  selector:
    labelSelectors:
      app: auth-service
  abort:
    httpStatus: 503
  duration: "3m"
```

### Сценарий 6: Fallback quality test

**Цель:** Проверить, что graceful degradation возвращает полезный ответ, а не пустую заглушку.

**Инструмент:** Chaos Mesh + curl.

**Шаги:**

1. **Инжектируйте сбой:** отключение `recommendation-service`.
2. **Выполните запрос:** `curl http://api-gateway/products/123`.
3. **Ожидаемый результат:**
   - HTTP 200 (не 500).
   - Ответ содержит дефолтные рекомендации или сообщение "рекомендации временно недоступны".
   - Заголовок `X-Cache: miss` или `X-Fallback: true`.

**Проверка:**

```bash
curl -s -D - http://api-gateway/products/123 | grep -E "(HTTP|X-Fallback|recommendations)"
# → HTTP/1.1 200 OK
# → X-Fallback: true
# → {"recommendations": [], "message": "temporarily unavailable"}
```

## Операции и команды

### Circuit Breaker state inspection

```bash
# Envoy admin API: circuit breaker stats
curl http://localhost:15000/stats | grep circuit

# Istio: опрос istiod
istioctl proxy-config cluster <pod-name> -n production

# Prometheus: circuit breaker metrics
rate(circuit_breaker_state_changes_total{state="open"}[5m])
rate(circuit_breaker_success_total[5m])
rate(circuit_breaker_failure_total[5m])
```

### Bulkhead metrics

```bash
# HikariCP (Java connection pool)
curl http://payment-service:8080/actuator/metrics/hikaricp.connections.active
curl http://payment-service:8080/actuator/metrics/hikaricp.connections.pending

# Go (database/sql)
curl http://payment-service:8080/debug/vars | jq '.db | .max_open_connections, .in_use'
```

### Rate Limiter metrics

```bash
# Envoy rate limit
curl http://localhost:15000/stats | grep rate_limit

# Prometheus
rate(http_requests_total{status="429"}[5m])
rate(rate_limiter_remaining_quota[5m])
```

### Retry metrics

```bash
# Istio/Envoy retry stats
curl http://localhost:15000/stats | grep retry

# Prometheus
rate(http_upstream_rq_retry_total[5m])
rate(http_upstream_rq_retry_success_total[5m])
```

### Fallback metrics

```bash
# Кастомные метрики fallback
rate(fallback_invocations_total[5m])
rate(fallback_errors_total[5m])
```

### Chaos Mesh: отложенная остановка эксперимента

```bash
# Применить эксперимент
kubectl apply -f circuit-breaker-test.yaml

# Мониторинг во время эксперимента
watch -n 5 'kubectl get networkchaos -n chaos-testing'

# Принудительная остановка
kubectl delete -f circuit-breaker-test.yaml
```

### Alertmanager: правила для паттернов

```yaml
groups:
  - name: resilience_pattern_alerts
    rules:
      - alert: CircuitBreakerStuckClosed
        expr: |
          rate(circuit_breaker_state_changes_total{state="open"}[10m]) == 0
          and
          rate(circuit_breaker_failure_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Circuit Breaker не открывается при высоком уровне ошибок"

      - alert: RetryStormDetected
        expr: |
          rate(http_requests_total[5m]) > (rate(http_requests_total[5m] offset 1h) * 3)
          and
          rate(http_upstream_rq_retry_total[5m]) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Обнаружен retry storm: RPS вырос в 3+ раза"

      - alert: BulkheadBreach
        expr: |
          rate(connection_pool_pending_requests[5m]) > 0
          and
          rate(connection_pool_active_requests[5m]) / connection_pool_max_connections > 0.9
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Bulkhead переполнен: >90% соединений заняты"
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Circuit Breaker не открывается** | Порог ошибок слишком высокий | Снизьте `failure_rate_threshold` до 50% или `slow_call_rate_threshold` |
| **Circuit Breaker открывается без причины** | Сезонный пик или соседний эксперимент | Добавьте `minimum_throughput` порог, настройте `for:` длительность алерта |
| **Retry storm вместо graceful degradation** | Retry без backoff или слишком много повторов | Установите `max_retries=3`, exponential backoff, jitter |
| **Bulkhead не изолирует** | Пулы разделены только на уровне кода, не на уровне ОС | Используйте отдельные thread pools, connection pools, cgroups |
| **Fallback падает с собственной ошибкой** | Fallback зависит от того же downstream | Изолируйте fallback: кэш, статика, дефолтный ответ без внешних вызовов |
| **Timeout не срабатывает** | Таймаут настроен только на уровне сервера | Добавьте клиентский таймаут, LB timeout, прокси timeout |
| **Rate Limiter не защищает downstream** | Лимит слишком высокий или настроен на уровне ingress | Установите лимит на уровне service mesh или downstream |
| **Half-Open не работает** | Слишком короткий `wait_duration` или `max_requests` | Увеличьте `wait_duration` до 30-60s, `max_requests` до 10-20 |

## Лучшие практики

### Проектирование экспериментов

1. **Тестируйте паттерн в изоляции** — один эксперимент = один паттерн. Не смешивайте Circuit Breaker и Bulkhead в одном эксперименте.
2. **Используйте production-реализацию** — тестируйте реальные конфигурации Circuit Breaker, не mock-объекты.
3. **Определите success criteria заранее** — например: "Circuit Breaker открывается за <10s, error rate <5%, fallback обслуживает 100% запросов".
4. **Тестируйте recovery** — не только сбой, но и возврат в нормальное состояние. Half-Open должен работать.

### Мониторинг и алертинг

5. **Экспортируйте метрики паттернов** — Circuit Breaker state, pool size, retry attempts должны быть доступны в Prometheus.
6. **Настройте алерты на паттерны** — Circuit Breaker stuck closed, retry storm, bulkhead breach.
7. **Используйте traces для корреляции** — Jaeger trace должен показывать, где именно сработал Circuit Breaker или Fallback.
8. **Ведите runbook для каждого паттерна** — как проверить, что паттерн работает, как отключить, как восстановить.

### Безопасность

9. **Начинайте с staging** — первый эксперимент с паттерном всегда в тестовой среде.
10. **Ограничивайте blast radius** — тестируйте на 1-5% трафика или одном поде.
11. **Имейте emergency stop** — автоматическая остановка по метрикам, а не по таймауту.
12. **Уведомляйте команду** — все должны знать о эксперименте с паттернами.

### Избегайте ошибок

13. **Не тестируйте несколько паттернов одновременно** — если сбой произошел, вы не поймете, какой паттерн сработал, а какой нет.
14. **Не полагайтесь на average latency** — Circuit Breaker работает с «хвостами», используйте p99/p999.
15. **Не игнорируйте false positives** — если Circuit Breaker открывается при плановом всплеске, настройте `minimum_throughput`.
16. **Не забывайте про fallback testing** — fallback должен возвращать полезный ответ, а не 200 OK с пустым телом.
17. **Не тестируйте только happy path** — тестируйте boundary conditions: ровно на пороге ошибок, ровно на лимите пула.

## Дополнительная информация

### Интеграция с другими практиками

- **Chaos Engineering — практическое руководство** (`chaos_engineering_practical.md`) — Game Days, где resilience-паттерны тестируются в комплексе.
- **Chaos Engineering — метрики** (`chaos_engineering_metrics.md`) — SLI/SLO/Error Budget для оценки качества паттернов.
- **CI/CD — паттерны надёжности** (`../CI-CD/Core_Concepts/reliability_patterns.md`) — теория Circuit Breaker, Bulkhead, Rate Limiter.

### Типичные ошибки проектирования

- **Circuit Breaker без Fallback:** Паттерн предотвращает каскадный сбой, но возвращает 503. Всегда добавляйте fallback.
- **Bulkhead на уровне одного процесса:** Если все пулы в одном JVM/процессе, каскадный GC pause все равно уронит все пулы.
- **Retry без circuit breaker:** Ретраиamplify проблему. Всегда комбинируйте с Circuit Breaker.
- **Timeout без context cancellation:** Таймаут на клиенте, но контекст не отменяется на сервере — соединение остается висящим.

### Шаблон runbook для тестирования паттерна

```markdown
# Runbook: Тестирование Circuit Breaker для payment-service

## Цель
Убедиться, что Circuit Breaker открывается при 50% ошибок и возвращается в Half-Open.

## Безопасность
- Blast Radius: 1 пода, namespace production
- Emergency stop: `kubectl delete -f circuit-breaker-test.yaml`
- Уведомлены: #team-platform

## Baseline
- Latency p99: 180ms
- Error rate: 0.05%
- RPS: 500

## Эксперимент
- Инструмент: Chaos Mesh NetworkChaos
- Сбой: 500ms delay на 50% трафика
- Длительность: 5 минут

## Критерии успеха
- [ ] Circuit Breaker открылся за <10s
- [ ] Error rate < 5%
- [ ] Fallback (кэш) обслуживает запросы
- [ ] Half-Open сработал после восстановления

## Результаты
| Метрика | Ожидание | Факт |
| --- | --- | --- |
| Time to Open | < 10s | |
| Error rate | < 5% | |
| Fallback latency | < 200ms | |
| Recovery time | < 60s | |
```
