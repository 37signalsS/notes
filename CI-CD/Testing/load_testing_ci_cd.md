# Нагрузочное тестирование в CI/CD

## Определения

**Нагрузочное тестирование (Load Testing)** — проверка поведения системы под нагрузкой, превышающей ожидаемую в продакшене. В контексте CI/CD цель — верификация SLA (latency, throughput) и выявление регрессий производительности до деплоя.

**Performance Budget** — набор пороговых значений метрик (p95 latency, error rate, RPS), которые автоматически блокируют пайплайн при превышении. Реализуется как Quality Gate в CI/CD.

**Performance-as-Code** — декларативное описание нагрузочных сценариев в коде (k6, Locust), версионируемое в Git и запускаемое в CI.

**Baseline** — эталонный результат производительности стабильной версии системы, с которым сравниваются последующие запуски. Хранится в артефактах CI или version-controlled файле.

**Regression Detection** — автоматическое обнаружение деградации производительности путём сравнения текущих результатов с baseline или абсолютными порогами.

**Quality Gate** — критерий прохождения этапа pipeline (например, p95 < 500ms, error rate < 1%). При нарушении пайплайн завершается с ошибкой.

**SLI (Service Level Indicator)** — количественный индикатор производительности (latency, throughput, error rate). Для CI/CD gates используются p95/p99 latency и error rate.

**SLO (Service Level Objective)** — целевое значение SLI за определённый период. В CI/CD SLO translates в Performance Budget.

**PTLC (Performance Test Life Cycle)** — жизненный цикл нагрузочного тестирования: требования → подготовка среды → разработка сценариев → выполнение → анализ. В CI/CD PTLC автоматизирован и повторяется на каждом запуске.

**Coordinated Omission** — методологическая ошибка нагрузочного тестирования в Closed Loop-модели, при которой инструмент «сбрасывает» запросы во время высокой задержки, занижая перцентили. Для исключения используются Open Loop-инструменты (`constant-arrival-rate`, `ramping-arrival-rate`, `vegeta`, `wrk2`).

## Основные концепции и архитектура

### Зачем нагрузочное тестирование в CI/CD

| Проблема | Решение |
| :--- | :--- |
| Регрессия производительности после деплоя | Performance Budget в CI блокирует merge |
| Деградация latency незаметна для unit-тестов | k6 сценарий проверяет p95/p99 |
| Нехватка ресурсов обнаруживается в продакшене | Stress test в CI выявляет узкие места |
| Оптимизация требует данных | Baseline comparison показывает +/- по метрикам |

### Типы тестирования в CI/CD контексте

| Тип | Цель в CI/CD | Длительность | Когда запускать |
| :--- | :--- | :--- | :--- |
| **Load Testing** | Верификация SLA под ожидаемой нагрузкой | 2–5 минут | На MR, nightly |
| **Stress Testing** | Поиск точки разлома (breaking point) | 5–10 минут | Только на schedule/main |
| **Spike Testing** | Проверка поведения при резком всплеске | 1–2 минуты | Перед маркетинговыми акциями |
| **Endurance** | Выявление утечек памяти/ресурсов | 30–60 минут | Ночной pipeline, перед релизом |
| **Smoke Performance** | Быстрая проверка, что сервис не деградировал | 30–60 секунд | На каждый коммит (опционально) |

### Жизненный цикл тестирования в CI/CD (PTLC)

1. **Trigger:** push, merge request, schedule, manual
2. **Environment Check:** верификация, что стенд доступен и имеет production-like конфигурацию
3. **Build:** сборка артефакта (Docker-образ, binary)
4. **Deploy to Test Stand:** развёртывание в изолированное окружение
5. **Warm-up:** прогрев кэшей (JIT, TLS, connection pool) — 30–60 секунд
6. **Load Test:** запуск генератора нагрузки (k6, Locust, Vegeta) с Quality Gates
7. **Baseline Comparison:** сравнение p95/p99/error rate с предыдущим успешным запуском
8. **Quality Gate:** проверка порогов, fail-fast при нарушении
9. **Artifacts:** сохранение JSON-отчётов, baseline, графиков
10. **Cleanup:** остановка контейнеров, удаление seeding-данных

### Инструменты

| Инструмент | Тип | Язык скриптов | Особенности | Использование в CI |
| :--- | :--- | :--- | :--- | :--- |
| **k6** | HTTP/gRPC/WebSocket | JavaScript | Performance-as-Code, Open Loop-модель, Docker-образ `grafana/k6` | Основной инструмент для CI/CD |
| **Locust** | HTTP/API | Python | Master-worker архитектура, простой синтаксис | Headless mode в CI |
| **Vegeta** | HTTP | CLI (Go) | Constant rate, исключает Coordinated Omission | Ad-hoc benchmarking |
| **wrk2** | HTTP | CLI (Lua) | Высокая производительность, фиксированный arrival rate | Точный benchmarking |
| **ghz** | gRPC | CLI | Специализирован для gRPC, protobuf | gRPC-сервисы |
| **Apache Bench (ab)** | HTTP | CLI | Простейший, нет CI-интеграции | Локальные smoke-проверки |

Подробнее о k6 (концепции, исполнители, расширения): **[Нагрузочное тестирование с помощью k6](../../Testing/k6_load_testing.md)**.

Подробнее о методологии, типах тестов и PTLC: **[Методология тестирования производительности](../../Testing/performance_testing_methodology.md)**.

### Ключевые метрики для CI/CD Quality Gates

| Метрика | Описание | Типичный порог | Инструмент |
| :--- | :--- | :--- | :--- |
| **p95 latency** | 95% запросов обрабатываются быстрее | < 500ms (API), < 200ms (microservices) | k6, wrk2 |
| **p99 latency** | 99% запросов обрабатываются быстрее | < 1000ms | k6, Vegeta |
| **Error rate** | Доля запросов с ошибками (4xx/5xx) | < 1% | k6, Locust |
| **Throughput (RPS)** | Запросов в секунду при заданной нагрузке | Не падает ниже baseline > 95% | k6, wrk2 |
| **Saturation** | Использование CPU/RAM/диска при нагрузке | CPU < 80%, RAM < 85% | PSI, `iostat` |

## Практические сценарии

### k6: базовый сценарий для CI/CD

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('errors');
const latencyP95 = new Trend('latency_p95');

export const options = {
  scenarios: {
    constant_load: {
      executor: 'constant-arrival-rate',
      rate: 50,              // 50 RPS
      timeUnit: '1s',
      duration: '5m',
      preAllocatedVUs: 20,
      maxVUs: 50,
    },
  },
  thresholds: {
    'http_req_duration{status:200}': ['p(95)<500'],
    errors: ['rate<0.01'],
  },
};

export default function () {
  const url = __ENV.TARGET_URL || 'http://localhost:8080';
  const res = http.get(`${url}/health`);
  
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

const baseline = new SharedArray('baseline', function () {
  return JSON.parse(open('./baseline.json'));
});

export const options = {
  scenarios: {
    constant_load: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '5m',
      preAllocatedVUs: 20,
      maxVUs: 50,
    },
  },
  thresholds: {
    'http_req_failed': ['rate<0.01'],
  },
};

export default function () {
  const res = http.get('https://api.example.com/orders');
  const baselineP95 = baseline[0].p95;
  
  check(res, {
    'p95 within baseline': (r) => r.timings.duration < baselineP95 * 1.1,
  });
}
```

### k6: Docker-запуск в CI

```bash
docker run --rm \
  -v $(pwd)/scripts:/scripts \
  -v $(pwd)/results:/results \
  grafana/k6:latest run \
  --out json=/results/k6-results.json \
  /scripts/load-test.js

# Извлечение p95 из результатов
P95=$(cat results/k6-results.json | jq '.metrics.http_req_duration.values["p(95)"]')
echo "p95 latency: ${P95}ms"

if (( $(echo "$P95 > 500" | bc -l) )); then
  echo "FAIL: p95 latency exceeds threshold"
  exit 1
fi
```

### Locust: headless режим в CI

```python
from locust import HttpUser, task, between

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
```

```bash
locust -f locustfile.py \
  --headless \
  --host=https://api.example.com \
  --users 50 \
  --spawn-rate 10 \
  --run-time 2m \
  --html=results/locust-report.html \
  --csv=results/locust-stats
```

### Vegeta: constant-rate benchmarking

```bash
# Атака с постоянной скоростью 100 RPS в течение 1 минуты
echo "GET https://api.example.com/health" | \
  vegeta attack -rate=100 -duration=60s | \
  vegeta report

# С сохранением результатов в JSON
echo "GET https://api.example.com/health" | \
  vegeta attack -rate=100 -duration=60s > results/vegeta.bin

vegeta report -type=json results/vegeta.bin > results/vegeta-report.json

# Проверка p95
P95=$(cat results/vegeta-report.json | jq '.latencies["95th"]')
echo "p95: ${P95}ns"
```

### wrk2: высокопроизводительный benchmarking

```bash
# 12 потоков, 400 соединений, 30 секунд, фиксированный arrival rate
wrk -t12 -c400 -d30s --latency -R 1000 \
  https://api.example.com/api/v1/resource

# Ключевые метрики в выводе:
# Latency: avg, max, stdev
# Latency Distribution: 50%, 75%, 90%, 99%
# Requests/sec: фактический RPS
```

### GitLab CI: нагрузочное тестирование

```yaml
stages:
  - build
  - test
  - load
  - deploy

variables:
  IMAGE: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}

build_image:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker build -t $IMAGE .
    - docker save $IMAGE > image.tar
  artifacts:
    paths:
      - image.tar
    expire_in: 1 day

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
        echo "OK: p95 ${CURRENT_P95}ms within baseline"
      fi
  artifacts:
    paths:
      - results/
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

## Операции и команды

### CLI-инструменты для нагрузочного тестирования

| Инструмент | Назначение | Основные команды |
| :--- | :--- | :--- |
| **k6** | Нагрузочное тестирование, Quality Gates | `k6 run --out json=results.json script.js` |
| **locust** | Распределённая нагрузка, Python-скрипты | `locust -f locustfile.py --headless --users 50 --run-time 2m` |
| **vegeta** | Constant-rate benchmarking | `echo "GET url" | vegeta attack -rate=100 -duration=60s \| vegeta report` |
| **wrk2** | Высокопроизводительный HTTP benchmarking | `wrk -t12 -c400 -d30s --latency -R 1000 https://api.example.com` |
| **ghz** | gRPC нагрузочное тестирование | `ghz --insecure --concurrency 10 --total 1000 -d '{"id":1}' host:50051 package.Service/GetUser` |
| **jq** | Парсинг JSON-отчётов | `jq '.metrics.http_req_duration.values["p(95)"]' results.json` |
| **bc** | Вычисления с плавающей точкой | `echo "$P95 > 500" \| bc -l` |

### Основные параметры k6

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--out, -o` | Формат вывода результатов | `--out json=results.json` |
| `--summary-export` | Экспорт сводки в JSON | `--summary-export=summary.json` |
| `--vus` | Количество виртуальных пользователей | `--vus 100` |
| `--duration, -d` | Длительность теста | `--duration 5m` |
| `--tag` | Теги для результатов | `--tag env=staging --tag commit=abc123` |
| `--insecure` | Отключение проверки TLS | `--insecure` |
| `--ca-cert` | Путь к CA-сертификату | `--ca-cert /path/to/ca.crt` |

### Основные параметры Locust

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `-f, --locustfile` | Путь к файлу сценария | `-f locustfile.py` |
| `--headless` | Запуск без веб-UI | `--headless` |
| `--users` | Количество пользователей | `--users 100` |
| `--spawn-rate` | Скорость появления пользователей | `--spawn-rate 10` |
| `--run-time` | Длительность теста | `--run-time 5m` |
| `--host` | Целевой хост | `--host https://api.example.com` |
| `--html` | HTML-отчёт | `--html results/report.html` |
| `--csv` | CSV-отчёт с метриками | `--csv results/stats` |

### Основные параметры Vegeta

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `-rate` | Скорость запросов (RPS) | `-rate=100` |
| `-duration` | Длительность теста | `-duration=60s` |
| `-output` | Файл для сохранения raw-результатов | `-output=results.bin` |
| `-max-workers` | Лимит параллельных соединений | `-max-workers=10` |
| `report` | Отчёт из raw-файла | `vegeta report -type=json results.bin` |

### Парсинг результатов: bash-паттерны

```bash
# k6: извлечение p95/p99 из JSON
P95=$(jq '.metrics.http_req_duration.values["p(95)"]' results.json)
P99=$(jq '.metrics.http_req_duration.values["p(99)"]' results.json)
ERROR_RATE=$(jq '.metrics.http_req_failed.values.rate' results.json)

# Locust: извлечение p95 из CSV
P95=$(tail -1 results/stats_failures.csv | cut -d',' -f7)

# Vegeta: извлечение p95 из JSON
P95=$(cat results/vegeta-report.json | jq '.latencies["95th"]')

# Сравнение с baseline
CURRENT=$(jq -r '.metrics.http_req_duration.values.p95' current.json)
BASELINE=$(jq -r '.metrics.http_req_duration.values.p95' baseline.json)
if (( $(echo "$CURRENT > $BASELINE * 1.1" | bc -l) )); then
  echo "REGRESSION detected"
  exit 1
fi
```

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| k6: `connection refused` | Сервис не запущен или неверный URL | Добавить pre-check: `curl -sf $URL/health` |
| k6: `context canceled` | Высокий VU-count на малом контейнере | Уменьшить vus или увеличить CPU контейнера |
| Locust: `RPCError` в master-worker | Сетевая проблема между контейнерами | Использовать `--master-host` с реальным IP |
| p95 скачет между запусками | Нестабильная среда (shared runners) | Использовать выделенные раннеры, увеличить duration |
| Performance Budget всегда падает | Порог задан слишком строго | Отрегулировать порог на основе 3+ запусков в production-like среде |
| Load test блокирует деплой | Тест запускается на каждом коммите | Ограничить запуск: только на MR или на main |
| `Too many open files` | Превышен лимит file descriptors | Увеличить `ulimit -n` до 65535 |
| Baseline не найден | Первый запуск в ветке, артефакт отсутствует | Пропустить проверку baseline при `baseline.json` отсутствует |
| Таймаут на warm-up | Приложение медленно стартует | Увеличить warm-up период до 60–120 секунд |
| Секреты в логах CI | k6/Locust выводят переменные окружения | Использовать `--quiet`, маскировать переменные в CI |

### Диагностика в CI/CD

```bash
# Проверка доступности сервиса перед нагрузкой
curl -sf https://api.example.com/health || exit 1

# Проверка ресурсов контейнера
cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us
cat /sys/fs/cgroup/memory/memory.limit_in_bytes

# Просмотр логов k6
k6 run script.js 2>&1 | tee k6.log

# Проверка открытых файловых дескрипторов
ulimit -n
cat /proc/$$/limits | grep "open files"

# Быстрый smoke-тест перед полной нагрузкой
k6 run -u 1 -d 10s --quiet script.js
```

## Best Practices

### Проектирование сценариев

- **Open Loop-модель:** используйте `constant-arrival-rate` или `ramping-arrival-rate` вместо `constant-vus`, чтобы исключить Coordinated Omission.
- **Параметризация:** выносите URL, заголовки, токены в переменные окружения (`__ENV` в k6, `--env` в Locust). Никогда не хардкодьте секреты в скриптах.
- **Реалистичные сценарии:** имитируйте реальные паттерны трафика (распределение эндпоинтов, think-time, ratio reads/writes) на основе access logs.
- **Warm-up:** всегда включайте прогрев кэшей (30–60 секунд) перед steady state. Метрики cold start нерелевантны для SLA.
- **Cool-down:** дожидайтесь завершения всех активных соединений перед остановкой теста, иначе метрики будут искажены.

### Pipeline

- **Quality Gates:** начинайте с «мягких» порогов (`allow_failure: true`), переводя их в блокирующие только после стабилизации окружения и baseline.
- **Triggering:** запускайте нагрузочные тесты на Merge Request и nightly schedule, а не на каждый коммит. Используйте path filters для запуска только при изменениях в relevant-сервисах.
- **Параллелизм:** запуск lint и unit-тестов параллельно с сборкой; нагрузочные тесты — отдельный stage после deploy.
- **Кэширование:** кэшируйте зависимости (Docker-слои, `pip`, `node_modules`) между запусками. Для Testcontainers предварительно загружайте базовые образы на раннер.
- **Artifacts:** сохраняйте JSON-отчёты, baseline, HTML-отчёты на каждой стадии. Retention — минимум 14 дней для возможности пересборки baseline.

### Runner-ы и окружение

- **Выделенные раннеры:** используйте self-hosted runners для нагрузочного тестирования. Shared runners ненадёжны из-за noisy neighbors и вариативности производительности.
- **Production-like стены:** аппаратные характеристики, версии ПО, параметры ядра (`sysctl`), лимиты cgroup должны совпадать с production.
- **Изоляция:** каждый pipeline должен использовать отдельный стенд или namespace. Никаких shared state между параллельными запусками.
- **Air-gapped среды:** предварительно загружайте образы (k6, Locust, целевой сервис) на раннеры. Настройте локальный registry mirror.

### Baseline и Regression Detection

- **Фиксация baseline:** baseline должен храниться в артефактах CI или version-controlled файле. При обновлении baseline — только через MR + approval.
- **Многократный запуск:** строить baseline минимум из 3 прогонов в одинаковых условиях для исключения шума.
- **Относительные пороги:** baseline comparison (`current < baseline * 1.1`) более устойчив к вариативности среды, чем абсолютные пороги.
- **Автоматизация:** сравнение с baseline должно быть частью pipeline, а не ручным действием.

### Безопасность

- **Секреты:** никогда не хардкодьте API-ключи, токены в сценариях. Используйте переменные окружения CI (`$TARGET_URL`, `$API_TOKEN`).
- **Sensitive data:** не логируйте тела запросов/ответов с PII в production-окружениях. Используйте `--quiet` или фильтры в k6.
- **mTLS:** для production-like стены используйте клиентские сертификаты вместо `insecureSkipTLSVerify`.

## Дополнительная информация

### См. также

* **[Нагрузочное тестирование с помощью k6](../../Testing/k6_load_testing.md)** — Performance-as-Code, исполнители (executors), Coordinated Omission, выходные форматы, xk6.
* **[Методология тестирования производительности](../../Testing/performance_testing_methodology.md)** — типы тестов, метрики, PTLC, SRE-практики.

### Внешние ресурсы

* [k6 Documentation](https://grafana.com/docs/k6/) — официальная документация Grafana k6.
* [Locust Documentation](https://docs.locust.io/) — официальная документация Locust.
* [Vegeta](https://github.com/tsenart/vegeta) — HTTP load testing tool.
* [wrk2](https://github.com/giltene/wrk2) — высокопроизводительный HTTP benchmarking с фиксированным arrival rate.
* [k6 in CI/CD](https://grafana.com/docs/k6/results-output/running-k6-in-ci-cd/) — руководство по интеграции в пайплайны.
