# Нагрузочное тестирование в CI/CD

## Определения

**Нагрузочное тестирование (Load Testing)** — проверка поведения системы под нагрузкой, превышающей ожидаемую в продакшене. Цель — верификация SLA (latency, throughput) и выявление узких мест до деплоя.

**Performance Budget** — набор пороговых значений метрик (p95 latency, error rate, RPS), которые автоматически блокируют пайплайн при превышении. Реализуется как Quality Gate в CI/CD.

**Performance-as-Code** — декларативное описание нагрузочных сценариев в коде (k6, Locust), версионируемое в Git и запускаемое в CI.

**Baseline Comparison** — сравнение результатов текущего запуска с эталонным (baseline), сохраненным в хранилище. Позволяет детектировать регрессии без абсолютных порогов.

## Основные концепции

### Зачем нагрузочное тестирование в CI/CD

| Проблема | Решение |
| :--- | :--- |
| Регрессия производительности после деплоя | Performance Budget в CI блокирует merge |
| Деградация latency незаметна для unit-тестов | k6 сценарий проверяет p95/p99 |
| Нехватка ресурсов обнаруживается в продакшене | Stress test в CI выявляет узкие места |
| Оптимизация требует данных | Baseline comparison показывает +/- по метрикам |

### Инструменты

| Инструмент | Тип | Язык скриптов | Особенности |
| :--- | :--- | :--- | :--- |
| **k6** | HTTP/gRPC/WebSocket | JavaScript | Основной инструмент для CI/CD, Docker-образ `grafana/k6` |
| **Locust** | HTTP/API | Python | Простой синтаксис, master-worker модель |
| **Vegeta** | HTTP | CLI (Go) | Постоянная скорость атаки (constant rate), идеален для benchmarking |
| **wrk2** | HTTP | CLI (C) | Высокая производительность, гистограммы latency |
| **Apache Bench (ab)** | HTTP | CLI | Простейший инструмент, нет CI-интеграции |

### Метрики (SLI) для CI/CD Gate

| Метрика | Описание | Типичный порог |
| :--- | :--- | :--- |
| **p95 latency** | 95% запросов обрабатываются быстрее | < 500ms (API), < 200ms ( microservices) |
| **p99 latency** | 99% запросов обрабатываются быстрее | < 1000ms |
| **Error rate** | Доля запросов с ошибками (4xx/5xx) | < 1% |
| **Throughput (RPS)** | Запросов в секунду при заданной нагрузке | Зависит от SLA |
| **Saturation** | Использование CPU/RAM/диска при нагрузке | CPU < 80%, RAM < 85% |

---

## Практические реализации

### k6: базовый сценарий для CI/CD

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('errors');
const latencyP95 = new Trend('latency_p95');

export const options = {
  stages: [
    { duration: '30s', target: 20 },   // ramp-up
    { duration: '1m', target: 20 },    // steady state
    { duration: '10s', target: 0 },    // ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],   // p95 < 500ms
    errors: ['rate<0.01'],              // error rate < 1%
  },
};

export default function () {
  const res = http.get('https://api.example.com/health');
  
  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });
  
  errorRate.add(res.status !== 200);
  latencyP95.add(res.timings.duration);
  
  sleep(1);
}
```

### k6: сравнение с baseline (ретест)

```javascript
import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';

// Загрузка baseline из файла
const baseline = new SharedArray('baseline', function () {
  return JSON.parse(open('./baseline.json'));
});

export const options = {
  vus: 50,
  duration: '2m',
};

export default function () {
  const res = http.get('https://api.example.com/orders');
  
  const baselineP95 = baseline[0].p95;
  
  check(res, {
    'p95 latency within baseline': (r) => r.timings.duration < baselineP95 * 1.1, // +10% допуск
  });
}
```

### k6: Docker-запуск в CI

```bash
# Запуск k6 в Docker
docker run --rm \
  -v $(pwd)/scripts:/scripts \
  -v $(pwd)/results:/results \
  grafana/k6:latest run \
  --out json=/results/k6-results.json \
  /scripts/load-test.js

# Извлечение p95 из результатов
p95=$(cat results/k6-results.json | jq '.metrics.http_req_duration.values["p(95)"]')
echo "p95 latency: ${p95}ms"

# Проверка порога
if (( $(echo "$p95 > 500" | bc -l) )); then
  echo "FAIL: p95 latency ${p95}ms exceeds 500ms threshold"
  exit 1
fi
```

### Locust: сценарий для CI/CD

```python
from locust import HttpUser, task, between
import json

class APIUser(HttpUser):
    wait_time = between(1, 3)
    
    @task(3)
    def get_products(self):
        self.client.get("/api/products")
    
    @task(1)
    def create_order(self):
        self.client.post("/api/orders", json={
            "product_id": "123",
            "quantity": 1
        })
    
    @task(2)
    def get_user_profile(self):
        self.client.get("/api/users/me")
```

Запуск в CI:

```bash
# Locust headless mode
locust -f locustfile.py \
  --headless \
  --host=https://api.example.com \
  --users 50 \
  --spawn-rate 10 \
  --run-time 2m \
  --html=results/locust-report.html \
  --csv=results/locust-stats

# Проверка p95 из CSV
p95=$(tail -1 results/locust-stats_failures.csv | cut -d',' -f7)
```

### Vegeta: constant-rate benchmarking

```bash
# Атака с постоянной скоростью 100 RPS в течение 1 минуты
echo "GET https://api.example.com/health" | \
  vegeta attack -rate=100 -duration=60s | \
  vegeta report

# С сохранением результатов
echo "GET https://api.example.com/health" | \
  vegeta attack -rate=100 -duration=60s > results/vegeta.bin

vegeta report -type=json results/vegeta.bin > results/vegeta-report.json

# Проверка p95
p95=$(cat results/vegeta-report.json | jq '.latencies["95th"]')
echo "p95: ${p95}ns"
```

---

### GitLab CI: нагрузочное тестирование

```yaml
stages:
  - build
  - test
  - load
  - deploy

load_test:
  stage: load
  image: grafana/k6:latest
  script:
    - k6 run --out json=results/k6.json scripts/load-test.js
    - |
      P95=$(cat results/k6.json | jq '.metrics.http_req_duration.values["p(95)"]')
      echo "p95 latency: ${P95}ms"
      if [ $(echo "$P95 > 500" | bc -l) -eq 1 ]; then
        echo "FAIL: p95 exceeds 500ms"
        exit 1
      fi
  artifacts:
    when: always
    paths:
      - results/
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### GitHub Actions: нагрузочное тестирование

```yaml
name: Load Test
on: [pull_request]

jobs:
  load:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run k6 load test
        uses: grafana/k6-action@v0.3.1
        with:
          filename: scripts/load-test.js
      
      - name: Check performance budget
        if: failure()
        run: |
          echo "Performance budget exceeded. Check k6 output for details."
```

### GitLab CI: baseline comparison

```yaml
load_test_compare:
  stage: load
  image: grafana/k6:latest
  script:
    # Скачиваем baseline из артефактов main
    - curl -sJL "${CI_API_V4_URL}/projects/${MAIN_PROJECT_ID}/jobs/artifacts/main/file/results/baseline.json?job=load_test" -o baseline.json || true
    - k6 run --out json=results/current.json scripts/load-test.js
    - |
      CURRENT_P95=$(cat results/current.json | jq '.metrics.http_req_duration.values["p(95)"]')
      BASELINE_P95=$(cat baseline.json | jq '.p95')
      
      if [ -n "$BASELINE_P95" ]; then
        THRESHOLD=$(echo "$BASELINE_P95 * 1.1" | bc)
        if [ $(echo "$CURRENT_P95 > $THRESHOLD" | bc -l) -eq 1 ]; then
          echo "FAIL: p95 ${CURRENT_P95}ms exceeds baseline ${BASELINE_P95}ms by >10%"
          exit 1
        fi
        echo "OK: p95 ${CURRENT_P95}ms within baseline ${BASELINE_P95}ms"
      fi
  artifacts:
    paths:
      - results/
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| k6 падает с `connection refused` | Сервис не запущен или неверный URL | Добавить health-check перед запуском: `curl -sf $URL/health` |
| p95 сильно скачет между запусками | Нестабильная среда (shared runners) | Использовать выделенные раннеры или увеличить duration до 3-5 минут |
| `context canceled` в k6 | Высокий VU-count на малом контейнере | Уменьшить vus или увеличить CPU контейнера |
| Locust: `RPCError` в master-worker | Сетевая проблема между контейнерами | Использовать `--master-host` с реальным IP, проверить firewall |
| Performance Budget всегда падает | Порог задан слишком строго | Отрегулировать порог на основе 3+ запусков в production-like среде |
| Load test блокирует деплой | Тест запускается на каждом коммите | Ограничить запуск: только на MR или на main |

---

## Ограничения и особые случаи

### Время выполнения

Нагрузочные тесты — медленные (2-10 минут). В CI их стоит запускать:
- Только на Merge Request (не на каждом коммите)
- Только при изменениях в ключевых сервисах
- Как отдельный stage с `allow_failure: true` для начала внедрения

### Среда тестирования

Нагрузочные тесты на shared runners CI ненадежны из-за вариативности производительности. Рекомендации:
- Использовать выделенные раннеры или self-hosted runners
- Или запускать в production-like staging-окружении
- Не полагаться на абсолютные пороги — использовать baseline comparison

### Хранение baseline

Baseline должен храниться в version-controlled файле или артефактах CI. При обновлении baseline:
- Только авторизованные инженеры (через MR + approval)
- Baseline обновляется после подтверждения производительности в продакшене

---

## Дополнительная информация

### См. также
- **[Методология тестирования производительности](../../Testing/performance_testing_methodology.md)** — типы тестов, метрики, PTLC.
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — k6 quality gates, TIA.
- **[Канареечный деплой: мониторинг](../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md)** — метрики как gate.
- **[Прогрессивная доставка](../../GitOps/Concepts/progressive_delivery_gitops.md)** — AnalysisTemplate + Prometheus.
- **[DORA Metrics](../../CI-CD/Core_Concepts/dora_metrics.md)** — Change Failure Rate и Lead Time.

### Внешние ресурсы
- [k6 Documentation](https://grafana.com/docs/k6/) — официальная документация Grafana k6.
- [Locust Documentation](https://docs.locust.io/) — официальная документация Locust.
- [Vegeta](https://github.com/tsenart/vegeta) — HTTP load testing tool.
- [k6 in CI/CD](https://grafana.com/docs/k6/results-output/running-k6-in-ci-cd/) — k6 в пайплайнах.
