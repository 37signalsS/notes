# Smoke Testing в CI/CD

## Определения

**Smoke Testing (Дымовой тест)** — быстрая автоматизированная проверка критических функций системы после деплоя или перезапуска. Цель — убедиться, что система «работает» (primary paths доступны), а не что она «работает правильно».

**Post-Deploy Verification** — автоматизированные проверки, запускаемые после каждого деплоя для подтверждения работоспособности сервиса. Smoke-тесты — самый быстрый уровень таких проверок.

**Health Check** — endpoint, отвечающий на HTTP-запрос статусом системы (200 OK / 503 Unavailable). Является базовым smoke-тестом.

**Synthetic Monitoring** — непрерывная автоматизированная проверка availability и latency сервиса из внешней среды. Отличается от smoke-теста тем, что работает в продакшене 24/7, а не только при деплое.

## Основные концепции и архитектура

### Принцип работы

Smoke-тест запускается сразу после завершения деплоя и проверяет минимальный набор условий, подтверждающий что:
- приложение стартовало и слушает порт;
- критические зависимости доступны (база данных, кэш, DNS);
- базовые endpoint возвращают ожидаемые статусы;
- настройка окружения корректна (переменные окружения, права доступа, TLS-сертификаты).

### Жизненный цикл smoke-теста

1. **Pre-flight** — проверка окружения CI-раннера: доступность DNS, разрешение IP-адресов таргета, валидность TLS-сертификатов.
2. **Wait / Warm-up** — ожидание готовности сервиса: exponential backoff или фиксированный `sleep`, опрос `/health` до таймаута (обычно 30–120 секунд).
3. **Primary path validation** — проверка критических endpoint: `200 OK`, корректный response body, наличие обязательных полей.
4. **Dependency check** — опрос вспомогательных систем через application-level endpoint или direct connection (БД, кэш, очередь).
5. **Infrastructure validation** — проверка ресурсов хоста: свободное место на диске, свободная память, открытые порты, работающий процесс.
6. **Result aggregation** — возврат кода 0 при успехе, 1 при любом провале с детализацией причины.

### Компоненты smoke-теста

| Компонент | Ответственность | Пример реализации |
| :--- | :--- | :--- |
| **Probe / Check** | Единичная проверка (endpoint, порт, процесс) | `curl -sf http://host:8080/health`, `nc -z host 5432` |
| **Waiter** | Ожидание готовности с retry и backoff | `wait-for-it.sh`, `dockerize`, custom bash loop |
| **Aggregator** | Сбор результатов, подсчет failed/passed, exit code | bash counter, pytest summary, JUnit XML |
| **Notifier** | Отправка результата в канал оповещений | Slack webhook, email, PagerDuty, SMS (для on-prem paging) |
| **Gate** | Блокировка дальнейшего pipeline при провале | `allow_failure: false`, `exit 1`, manual approval step |

### Smoke Testing vs другие виды тестов

| Характеристика | Smoke Test | Integration Test | E2E Test | Performance Test |
| :--- | :--- | :--- | :--- | :--- |
| **Скорость** | < 30 секунд | 1–15 мин | 5–30 мин | 2–10 мин |
| **Покрытие** | Primary paths | Межмодульные взаимодействия | Полный user journey | Производительность |
| **Когда** | После каждого деплоя | В CI (каждый MR) | В CI (MR / nightly) | В CI (MR) или nightly |
| **Блокирует деплой** | Да (критично) | Да | Иногда | Опционально |
| **Окружение** | Production / Staging | CI (Testcontainers) | CI / Staging | Staging |

### Что проверяют smoke-тесты

- HTTP/TCP endpoint отвечает ожидаемым кодом
- База данных доступна (`SELECT 1`, ping через socket)
- Redis/Memcached доступен (`PING`/`PONG`)
- Основной API endpoint возвращает корректный response body
- Критический user flow работает (login → dashboard)
- Процесс приложения запущен (`pgrep`, `systemctl is-active`)
- Порт слушается (`ss -tlnp`, `netstat -tlnp`)
- Файловая система не заполнена (`df -h`, `stat -f`)
- DNS резолвится (`dig`, `resolvectl`)
- Время синхронизации в норме (`chronyc tracking`, `ntpq -p`)

### Что НЕ проверяют smoke-тесты

- Граничные условия и edge cases
- Производительность и нагрузка
- Безопасность
- Визуальная корректность
- Интеграции с внешними сервисами (Third-party)
- Долговечность (memory leaks, file descriptor exhaustion)
- Поведение при высокой нагрузке или частичном отказе зависимостей

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

### Bash: инфраструктурный smoke-тест (sysadmin)

```bash
#!/bin/bash
set -euo pipefail
HOST="${1:-app01}"
FAILED=0

check() {
  local name=$1
  local status=$2
  if [ "$status" -ne 0 ]; then
    echo "FAIL: $name"
    FAILED=$((FAILED + 1))
  else
    echo "OK: $name"
  fi
}

# 1. SSH доступность
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$HOST" "echo ok" >/dev/null 2>&1
check "ssh_connect" $?

# 2. Процесс приложения
ssh "$HOST" "pgrep -f 'myapp' >/dev/null"
check "process_running" $?

# 3. Порт слушается
ssh "$HOST" "ss -tlnp | grep -q ':8080'"
check "port_8080_listening" $?

# 4. Место на диске (< 90%)
ssh "$HOST" "df -h / | awk 'NR==2 {print \$5}' | sed 's/%//' | awk -v limit=90 '{print (\$1 < limit) ? 0 : 1}'" | \
  while read -r status; do check "disk_usage" "$status"; done

# 5. DNS резолвится
ssh "$HOST" "dig +short +timeout=2 api.example.com >/dev/null"
check "dns_resolution" $?

if [ $FAILED -gt 0 ]; then
  echo "SMOKE TEST FAILED: $FAILED checks failed"
  exit 1
fi

echo "SMOKE TEST PASSED"
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

### Python: infrastructure smoke test с testinfra

```python
import testinfra
import pytest

testinfra_hosts = ["ssh://app01", "ssh://app02"]

def test_myapp_process(host):
    """Проверка что процесс приложения запущен."""
    p = host.process.get(user="myapp", comm="myapp")
    assert p.pid > 0
    assert p.status == "sleeping"

def test_port_8080_listening(host):
    """Проверка что порт 8080 слушается на всех интерфейсах."""
    sock = host.socket("tcp://0.0.0.0:8080")
    assert sock.is_listening

def test_disk_usage(host):
    """Проверка что корневая файловая система заполнена менее чем на 90%."""
    usage = host.mount_point("/").used_percent
    assert usage < 90, f"Disk usage critical: {usage}%"

def test_dns_resolution(host):
    """Проверка внутреннего DNS."""
    cmd = host.run("dig +short +timeout=2 api.internal")
    assert cmd.succeeded
    assert cmd.stdout.strip()
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
    echo "OK: ${path} → ${actual}"
  else
    echo "FAIL: ${path} → ${actual} (expected ${expected})"
    return 1
  fi
}

check "/" "200"
check "/health" "200"
check "/api/v1/products" "200"
check "/api/v1/auth/login" "405"  # POST only, GET returns 405
check "/nonexistent" "404"
```

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

## Операции и команды

### Инструменты и утилиты

| Инструмент / команда | Назначение | Пример использования |
| :--- | :--- | :--- |
| `curl` | HTTP-запросы, проверка status code и body | `curl -s -o /dev/null -w "%{http_code}" http://host:8080/health` |
| `wget` | Альтернатива curl для HTTP-проверок | `wget -qO- --server-response --spider http://host:8080/health 2>&1 \| grep "HTTP/"` |
| `nc` / `ncat` | TCP/UDP-проверка порта | `nc -z -w5 app01 5432` |
| `ss` / `netstat` | Проверка слушающих портов и сокетов | `ss -tlnp \| grep ':8080'` |
| `pgrep` / `pidof` | Проверка что процесс запущен | `pgrep -f 'myapp'` |
| `systemctl` | Проверка systemd-сервисов | `systemctl is-active --quiet myapp` |
| `dig` / `resolvectl` / `nslookup` | DNS-проверка | `dig +short +timeout=2 api.example.com` |
| `ping` | ICMP-доступность хоста | `ping -c 3 -W 5 app01` |
| `df` / `stat` | Проверка свободного места на диске | `df -h / \| awk 'NR==2{print \$5}'` |
| `free` / `vmstat` | Проверка доступной памяти | `free -m \| awk 'NR==2{print \$7}'` |
| `jq` | Валидация JSON response body | `curl -s http://host:8080/health \| jq -e '.status == "ok"'` |
| `yq` | Валидация YAML-конфигураций после деплоя | `kubectl get configmap myapp -o yaml \| yq e '.data.config' -` |
| `kubectl rollout status` | Ожидание завершения deployment в Kubernetes | `kubectl rollout status deployment/myapp --timeout=120s` |
| `Goss` | YAML-инструмент для быстрых smoke/health-проверок серверов и контейнеров | `goss serve --port 8080 & goss validate --format tap` |

### Примеры ожидаемого вывода

```bash
# Проверка health endpoint
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health
200

# Проверка TCP-порта
$ nc -z -w5 localhost 5432 && echo "OK" || echo "FAIL"
OK

# Проверка процесса
$ pgrep -f 'myapp' && echo "OK" || echo "FAIL"
12345
OK

# Проверка systemd-сервиса
$ systemctl is-active --quiet myapp && echo "OK" || echo "FAIL"
OK
```

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

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Smoke test падает после деплоя | Сервис еще не завершил startup | `systemctl status myapp`, `journalctl -u myapp -n 50` | Добавить `wait-for-it.sh` или exponential backoff (10, 20, 40 сек) |
| `curl: (6) Could not resolve host` | DNS не резолвится в контейнере/раннере | `dig api.example.com`, `cat /etc/resolv.conf` | Проверить DNS-конфигурацию раннера, добавить `--network=host` или DNS-сервер |
| Smoke test проходит, но сервис не работает | Проверяется только HTTP 200, не содержимое | `curl -s http://host:8080/health \| jq .` | Добавить проверку response body: `jq -e '.status == "ok"'` |
| Smoke test блокирует деплой из-за retry | Слишком агрессивные retry, flaky dependencies | Логи раннера, `tcpdump`/`tshark` для анализа потерь | Увеличить интервал между retry (10–30 сек), изолировать внешние зависимости |
| Smoke test в production падает из-за rate limiting | IP CI-runner заблокирован WAF/CDN | `curl -I` из раннера, логи WAF | Запускать smoke test через прокси или из production-окружения, whitelist IP |
| Ложные срабатывания из-за CDN кэша | CDN отдает stale HTML, а API жив | `curl -H "Cache-Control: no-cache"` | Проверять API endpoints с заголовком `Pragma: no-cache`, а не статические страницы |
| `502 Bad Gateway` после деплоя | Балансировщик переключил трафик на неготовые инстансы | Логи балансировщика, `readinessProbe` | Проверить `initialDelaySeconds` и `readinessProbe` на корректность |
| Порт открыт, но соединение отклоняется | Файрвол (iptables/nftables) блокирует | `iptables -L -n`, `nft list ruleset` | Открыть порт в фаирволе или проверить `bind` на `127.0.0.1` вместо `0.0.0.0` |
| Диск заполнен после деплоя | Логи или временные файлы не ротируются | `du -sh /var/log/*`, `journalctl --disk-usage` | Добавить logrotate, очистить `/tmp`, настроить `SystemMaxUse` в journald |

## Лучшие практики

### Проектирование smoke-тестов

- **Первый принцип:** проверяйте только то, без чего сервис неработоспособен. Чем меньше проверок, тем выше скорость и стабильность smoke-теста.
- **Изоляция:** smoke-тесты не должны зависеть от состояния базы данных, внешних API или тестовых данных. Используйте read-only проверки или моки для внешних зависимостей.
- **Детерминированность:** результат не должен зависеть от времени суток, дня недели или нагрузки. Избегайте проверок, чувствительных к concurrency.
- **Retry policy:** используйте exponential backoff с jitter вместо фиксированного `sleep`. Пример: 5, 10, 20 секунд с `sleep $((RANDOM % 3))`.
- **Таймауты:** задавайте агрессивные таймауты на уровне HTTP-клиента (5–10 секунд) и всего smoke-теста (60–120 секунд), чтобы не задерживать pipeline.
- **Environment parity:** конфигурация smoke-теста в CI должна максимально приближена к production: одинаковые DNS, TLS-сертификаты, балансировщики.

### Интеграция в pipeline

- **Gate placement:** размещайте smoke-тесты immediately после этапа деплоя, до канареечного раскатывания или переключения трафика.
- **Fail-fast:** при провале smoke-теста инициируйте автоматический откат (rollback) без ожидания ручного вмешательства.
- **Parallel execution:** запускайте независимые smoke-тесты параллельно (bash background jobs, pytest-xdist, matrix strategy в CI), чтобы минимизировать общее время.
- **Artifacts:** сохраняйте логи smoke-тестов, HTTP-трафик (через `--trace-ascii` в curl) и вывод `journalctl` как артефакты pipeline для пост-фактум анализа.
- **Promotion rules:** для стратегий blue-green и canary используйте smoke-тест как prerequisite для promotion (manual approval или automatic gate в Argo Rollouts/Flagger).

### Observability и алертинг

- **Встроенные метрики:** smoke-тесты должны экспортировать метрики Prometheus (`smoke_test_duration_seconds`, `smoke_test_success`, `smoke_test_failure_total`).
- **SLO context:** определяйте SLO на smoke-test pass rate (например, 99.9% успешных smoke-тестов за 30 дней). Провал SLO — сигнал о нестабильности процесса деплоя, а не только об отдельном баге.
- **Paging:** для on-prem production настройте pagerduty/sms-алерты на провал smoke-теста. Время реакции (MTTR) напрямую зависит от скорости обнаружения через smoke-тесты.

### Безопасность и compliance

- **Read-only access:** smoke-тесты в CI должны иметь read-only доступ к production. Не запускайте smoke-тесты с кредами, дающими write-доступ.
- **Network segmentation:** размещайте smoke-тестовые раннеры в отдельном VLAN/segment с минимально необходимыми доступом к production.
- **Secrets management:** не храните токены и пароли для smoke-тестов в репозитории. Используйте Vault, SOPS, или CI-native secrets (GitLab CI/CD Variables, GitHub Secrets).

## Ограничения и особые случаи

### Smoke test не заменяет интеграционные тесты

Smoke test проверяет только primary paths. Он не выявляет:
- Баги в бизнес-логике
- Проблемы с миграцией данных
- Race conditions
- Проблемы с аутентификацией
- Утечки памяти или ресурсов
- Коррупцию данных при параллельной записи

Smoke test — это **последняя линия защиты** перед предоставлением трафика, а не основное тестирование.

### Задержка после деплоя

Kubernetes-деплой завершается до готовности подов. Smoke-тесты должны:
- Иметь `initialDelaySeconds` (30–60 секунд) для Kubernetes
- Использовать retry с backoff
- Проверять `kubectl rollout status` перед проверкой endpoints
- Для StatefulSet проверять готовность всех реплик (`kubectl wait --for=condition=ready pod -l app=myapp --timeout=120s`)

### Флакивость smoke-тестов

Частые причины флаков:
- **Race condition:** smoke-тест запускается до завершения миграций или прогрева кэша.
- **Timing issues:** проверка запущена во время ротации логов или ротации TLS-сертификатов.
- **External dependencies:** сторонние сервисы (платежный шлюз, SMS-шлюз) недоступны или отвечают с задержкой.
- **Resource starvation:** CI-раннер не имеет достаточно CPU/RAM для одновременного запуска тестируемого сервиса и smoke-теста.

Меры против флаков:
- Фильтруйте flaky smoke-тесты из критериев успешности деплоя, но трекайте их отдельно.
- Используйте quarantine-механизм (как в [Управление нестабильными тестами](./flaky_test_management.md)) для smoke-тестов с временными зависимостями.

### Инфраструктурные ограничения

- **Firewall / ACL:** CI-раннер должен иметь сетевое соединение с target на нужные порты (8080, 5432, 6379 и т.д.).
- **TLS / PKI:** в air-gapped средах используйте внутренний CA; в mixed-средах — настроенный `curl --cacert /etc/ssl/certs/internal-ca.crt`.
- **DNS split-horizon:** убедитесь что smoke-тест резолвит внутреннее имя (`api.internal`), а не внешнее. Используйте `dig` для проверки ответа.

## Дополнительная информация

### См. также

- **[Стратегии деплоя](../../CI-CD/Deployment_Strategies/comparison.md)** — blue-green, canary, rolling update и их smoke-тестирование.
- **[Health Checks и Rollback](../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)** — health/liveness/readiness probes.
- **[Канареечный деплой: мониторинг](../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md)** — метрики как gate.
- **[Прогрессивная доставка](../../GitOps/Concepts/progressive_delivery_gitops.md)** — smoke-test webhook в Flagger.
- **[Нагрузочное тестирование в CI/CD](./load_testing_ci_cd.md)** — k6, performance budget.
- **[Тестирование инфраструктуры](../../Testing/infrastructure_testing.md)** — Goss, testinfra, serverspec для infrastructure smoke.
- **[Управление нестабильными тестами](./flaky_test_management.md)** — quarantine, retry, detection.

### Внешние ресурсы

- [Blackbox Exporter](https://prometheus.io/docs/guides/blackbox-exporter/) — synthetic monitoring в Prometheus.
- [Checkly](https://www.checklyhq.com/) — сервис synthetic monitoring и API monitoring.
- [wait-for-it.sh](https://github.com/vishnubob/wait-for-it) — bash-скрипт для ожидания доступности TCP-хоста.
- [Goss](https://goss.rocks/) — быстрый YAML-инструмент валидации серверов и контейнеров.
