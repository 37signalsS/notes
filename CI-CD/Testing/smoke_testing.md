# Smoke Testing в CI/CD

## Определения

**Smoke Testing (Дымовой тест)** — быстрая автоматизированная проверка критических функций системы после деплоя или перезапуска. Цель — убедиться, что система «работает» (primary paths доступны), а не что она «работает правильно».

**Post-Deploy Verification** — автоматизированные проверки, запускаемые после каждого деплоя для подтверждения работоспособности сервиса. Smoke-тесты — самый быстрый уровень таких проверок.

**Health Check** — endpoint, отвечающий на HTTP-запрос статусом системы (200 OK / 503 Unavailable). Является базовым smoke-тестом.

**Synthetic Monitoring** — непрерывная автоматизированная проверка availability и latency сервиса из внешней среды. Отличается от smoke-теста тем, что работает в продакшене 24/7, а не только при деплое.

## Основные концепции

### Smoke Testing vs другие виды тестов

| Характеристика | Smoke Test | Integration Test | E2E Test | Performance Test |
| :--- | :--- | :--- | :--- | :--- |
| **Скорость** | < 30 секунд | 1-15 мин | 5-30 мин | 2-10 мин |
| **Покрытие** | Primary paths | Межмодульные взаимодействия | Полный user journey | Производительность |
| **Когда** | После каждого деплоя | В CI (каждый MR) | В CI (MR / nightly) | В CI (MR) или nightly |
| **Блокирует деплой** | Да (критично) | Да | Иногда | Опционально |
| **Окружение** | Production / Staging | CI (Testcontainers) | CI / Staging | Staging |

### Что проверяют smoke-тесты

- HTTP endpoint отвечает 200 OK
- База данных доступна (SELECT 1)
- Redis/Memcached доступен (PING/PONG)
- Основной API endpoint возвращает корректный ответ
- Критический user flow работает (login → dashboard)

### Что НЕ проверяют smoke-тесты

- Граничные условия и edge cases
- Производительность и нагрузка
- Безопасность
- Визуальная корректность
- Интеграции с внешними сервисами (Third-party)

---

## Практические реализации

### Bash: простейший smoke-тест

```bash
#!/bin/bash
set -euo pipefail

SERVICE_URL="${SERVICE_URL:-http://localhost:8080}"
FAILED=0

check_endpoint() {
  local url=$1
  local expected_status=${2:-200}
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  
  if [ "$status" != "$expected_status" ]; then
    echo "FAIL: $url returned $status (expected $expected_status)"
    FAILED=$((FAILED + 1))
  else
    echo "OK: $url returned $status"
  fi
}

# Критические проверки
check_endpoint "$SERVICE_URL/health"
check_endpoint "$SERVICE_URL/api/v1/status"
check_endpoint "$SERVICE_URL/ready"

if [ $FAILED -gt 0 ]; then
  echo "SMOKE TEST FAILED: $FAILED checks failed"
  exit 1
fi

echo "SMOKE TEST PASSED: All checks passed"
```

### Python: smoke-тест с Testcontainers

```python
import requests
import time
import sys

SERVICE_URL = "http://localhost:8080"

def wait_for_service(url, timeout=30):
    """Ожидание готовности сервиса."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{url}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    return False

def test_health():
    """Проверка health endpoint."""
    resp = requests.get(f"{SERVICE_URL}/health")
    assert resp.status_code == 200, f"Health check failed: {resp.status_code}"
    assert resp.json()["status"] == "ok"

def test_api_root():
    """Проверка основного API endpoint."""
    resp = requests.get(f"{SERVICE_URL}/api/v1/status")
    assert resp.status_code == 200
    assert "version" in resp.json()

def test_database_connection():
    """Проверка доступности БД через API."""
    resp = requests.get(f"{SERVICE_URL}/api/v1/db/health")
    assert resp.status_code == 200
    assert resp.json()["database"] == "connected"

if __name__ == "__main__":
    if not wait_for_service(SERVICE_URL):
        print(f"FAIL: Service not available at {SERVICE_URL}")
        sys.exit(1)
    
    tests = [test_health, test_api_root, test_database_connection]
    failed = 0
    
    for test in tests:
        try:
            test()
            print(f"OK: {test.__name__}")
        except AssertionError as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1
    
    if failed:
        print(f"SMOKE TEST FAILED: {failed}/{len(tests)} checks failed")
        sys.exit(1)
    
    print(f"SMOKE TEST PASSED: {len(tests)}/{len(tests)} checks passed")
```

### curl-based smoke-тест для Kubernetes

```bash
#!/bin/bash
# Проверка сервиса в Kubernetes
INGRESS_URL="https://app.example.com"

check() {
  local path=$1
  local expected=$2
  local actual
  actual=$(curl -s -o /dev/null -w "%{http_code}" "${INGRESS_URL}${path}")
  
  if [ "$actual" = "$expected" ]; then
    echo "✓ ${path} → ${actual}"
  else
    echo "✗ ${path} → ${actual} (expected ${expected})"
    return 1
  fi
}

check "/" "200"
check "/health" "200"
check "/api/v1/products" "200"
check "/api/v1/auth/login" "405"  # POST only, GET returns 405
check "/nonexistent" "404"
```

---

### GitLab CI: smoke-тест после деплоя

```yaml
stages:
  - build
  - deploy
  - verify

deploy_production:
  stage: deploy
  script:
    - kubectl apply -f k8s/
  environment:
    name: production

smoke_test:
  stage: verify
  image: curlimages/curl:latest
  script:
    - |
      for endpoint in /health /api/v1/status /api/v1/products; do
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}${endpoint}")
        if [ "$STATUS" != "200" ]; then
          echo "FAIL: ${endpoint} returned ${STATUS}"
          exit 1
        fi
        echo "OK: ${endpoint} → ${STATUS}"
      done
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  allow_failure: false
```

### GitHub Actions: smoke-тест с retry

```yaml
name: Post-Deploy Smoke Test
on:
  deployment:
    types: [completed]

jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - name: Wait for service
        run: sleep 30
      
      - name: Run smoke tests
        run: |
          for i in 1 2 3; do
            if curl -sf "${SERVICE_URL}/health"; then
              echo "Health check passed on attempt $i"
              exit 0
            fi
            echo "Attempt $i failed, retrying..."
            sleep 10
          done
          echo "Health check failed after 3 attempts"
          exit 1
```

### Argo Rollouts: smoke-тест как AnalysisTemplate

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: smoke-test
spec:
  args:
    - name: service-url
  metrics:
    - name: smoke-test
      count: 1
      interval: 5s
      failureLimit: 0
      provider:
        http:
          url: "{{args.service-url}}/health"
          method:
            get:
              path: /
              scheme: HTTP
          expectedCodes: ["200"]
```

---

## Synthetic Monitoring vs Smoke Tests

| Аспект | Smoke Test | Synthetic Monitoring |
| :--- | :--- | :--- |
| **Когда** | После деплоя | 24/7 в продакшене |
| **Откуда** | Из CI/runner | Из внешних точек (multi-region) |
| **Что проверяет** | Доступность primary paths | Availability + Latency + SSL |
| **Инструменты** | curl, k6, custom scripts | Blackbox Exporter, Checkly, UptimeRobot |
| **Алерты** | Пайплайн падает | Prometheus Alertmanager |

### Blackbox Exporter: synthetic monitoring в Prometheus

```yaml
# blackbox.yml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200]
      method: GET
      follow_redirects: true

# prometheus.yml
scrape_configs:
  - job_name: 'blackbox-http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - https://api.example.com/health
          - https://api.example.com/ready
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Smoke test падает после деплоя | Сервис еще не завершил startup | Добавить `sleep 30` или exponential backoff перед проверкой |
| `curl: (6) Could not resolve host` | DNS не резолвится в контейнере | Проверить DNS-конфигурацию контейнера, использовать IP напрямую |
| Smoke test проходит, но сервис не работает | Проверяется только HTTP 200, не содержимое | Добавить проверку response body: `curl ... \| jq '.status'` |
| Smoke test блокирует деплой из-за retry | Слишком агрессивные retry | Увеличить интервал между retry (10-30 сек) |
| Smoke test в production падает из-за rate limiting | IP CI-runner заблокирован | Запускать smoke test через прокси или из production-окружения |
| Ложные срабатывания из-за CDNs | CDN кэширует stale responses | Проверять конкретные API endpoints, а не статические страницы |

---

## Ограничения и особые случаи

### Smoke test не заменяет интеграционные тесты

Smoke test проверяет только primary paths. Он не выявляет:
- Баги в бизнес-логике
- Проблемы с миграцией данных
- Race conditions
- Проблемы с аутентификацией

Smoke test — это **последняя линия защиты**, а не основное тестирование.

### Задержка после деплоя

Kubernetes-деплой завершается до готовности подов. Smoke-тесты должны:
- Иметь `initialDelaySeconds` (30-60 сек) для Kubernetes
- Использовать retry с backoff
- Проверять `kubectl rollout status` перед проверкой endpoints

---

## Дополнительная информация

### См. также
- **[Стратегии деплоя](../../CI-CD/Deployment_Strategies/comparison.md)** — blue-green, canary, rolling update и их smoke-тестирование.
- **[Health Checks и Rollback](../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)** — health/liveness/readiness probes.
- **[Канареечный деплой: мониторинг](../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md)** — метрики как gate.
- **[Прогрессивная доставка](../../GitOps/Concepts/progressive_delivery_gitops.md)** — smoke-test webhook в Flagger.
- **[Nagрузочное тестирование в CI/CD](./load_testing_ci_cd.md)** — k6, performance budget.

### Внешние ресурсы
- [Blackbox Exporter](https://prometheus.io/docs/guides/blackbox-exporter/) — synthetic monitoring в Prometheus.
- [Checkly](https://www.checklyhq.com/) — сервис synthetic monitoring и API monitoring.
