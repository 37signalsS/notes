# Интеграция автоматизированных тестов в CI/CD

**Актуально для:** GitLab CI, GitHub Actions, Jenkins (2026); k6 v2.3.x, pytest 8.x, Python 3.12, Testcontainers 1.x–4.x, OpenTelemetry 1.x

## 1. Определения

**Quality Gates (Ворота качества)** — набор автоматизированных критериев и проверок в пайплайне, которые сборка должна успешно пройти для продвижения на следующий этап (например, из Test в Staging).

**Shift-left Testing (Сдвиг влево)** — перенос тестирования на самые ранние этапы разработки (IDE, Pre-commit), чтобы обнаруживать ошибки до того, как они попадут в общую ветку кода.

**Shift-right Testing (Сдвиг вправо)** — тестирование в среде эксплуатации (Production) через Canary-деплои, Feature Toggles и синтетический мониторинг. Ключевой принцип — управляемый «радиус поражения» (blast radius): каждое приём в production должно быть малым и обратимым. Подробнее о канареечном развёртывании и метриках автогейтов: **[Canary мониторинг и гейтинг](../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md)**.

**Test Observability (Наблюдаемость тестов)** — сбор и анализ телеметрии (трейсы, логи, метрики) непосредственно из процесса выполнения тестов для глубокой диагностики причин сбоев.

**Test Impact Analysis (TIA)** — оптимизация CI-цикла путем запуска только тех тестов, которые затрагивают измененные участки кода.

## 2. Основные концепции

### Роль тестирования в конвейере поставки

Автоматизация тестов внутри CI/CD превращает качество из "события в конце" в "непрерывный процесс":
*   **Мгновенная обратная связь:** Разработчик узнает о поломке через несколько минут после коммита.
*   **Документация как код:** Тесты выступают живым описанием бизнес-логики и контрактов API.
*   **Изоляция рисков:** Использование эфемерных окружений (Review Apps) позволяет тестировать изменения в полной изоляции.

### Динамические ворота качества (Quality Gates)

В 2026 году ворота качества стали гибкими и контекстно-зависимыми:
1.  **Пороги покрытия:** Блокировка, если покрытие нового кода ниже 80% (даже если общее покрытие высоко).
2.  **Анализ безопасности:** Блокировка при обнаружении уязвимостей (SAST/SCA) с уровнем `High` и выше.
3.  **Бюджеты производительности:** Автоматический провал теста, если время ответа API выросло более чем на 10% относительно базовой линии.

| Уровень | Инструменты | Критерий (2026) |
| :--- | :--- | :--- |
| **Lint / Static** | ruff, golangci-lint | 0 критических замечаний, соблюдение архитектурных правил. |
| **Unit** | pytest, JUnit 5, Jest | 100% прохождение + анализ мутационного тестирования. |
| **Integration** | Testcontainers, Pact | Изолированное окружение, успешные контракты API (Pact Broker). |
| **Security** | Snyk, Trivy, Semgrep | Отсутствие CVE с доступными патчами. |
| **E2E / UI** | Playwright, Percy | Стабильность сценариев + отсутствие визуальных регрессий. |

### Оптимизация пайплайна (TIA)

Для крупных проектов запуск всех тестов на каждый коммит неэффективен. **Test Impact Analysis (TIA)** позволяет:
*   Картировать зависимости между файлами кода и тестовыми методами.
*   Запускать только затронутый набор тестов (Impacted tests).
*   **Результат:** Сокращение времени выполнения CI на 40–70%.

Инструменты TIA для Python (2026):
*   **pytest-testmon** — динамическое отслеживание зависимостей через coverage; первый запуск с `--testmon` строит базу `.testmondata`, последующие запуски отбирают только затронутые изменениями тесты.
*   **pytest-impact** — статический анализ (AST) графа фикстур/`conftest`, работает без предварительного прогона (cold start), совместим с первым CI-раном.
*   **pytest-tia** — покрытие на уровне методов (метод-карта), отсев косметических и type-only изменений; совместим с shallow-клонами.

**Критическое правило TIA:** инструмент не должен пропускать тест, который мог бы упасть. Настройка начинается с полного прогона (baseline), а на ночном расписании или перед релизом обязательно выполняется полный набор тестов — иначе риск «ложного зелёного» пайплайна растёт.

## 3. Практические сценарии

### Пайплайн с использованием эфемерных окружений (GitLab CI)

Современный подход подразумевает создание временной инфраструктуры для каждой ветки (Merge Request).

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - deploy-preview
  - verify-preview
  - cleanup

# Быстрые тесты + TIA.
# Первый запуск в ветке выполняется без --testmon для построения базы .testmondata,
# последующие MR-запуски отсекают незатронутые изменениями тесты.
unit-tests:
  stage: test
  script:
    - pytest --testmon --junitxml=report.xml
  artifacts:
    reports:
      junit: report.xml

# Создание эфемерного окружения (Review App)
review-app:
  stage: deploy-preview
  script:
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./chart
  environment:
    name: review/$CI_COMMIT_REF_NAME
    url: https://$CI_COMMIT_REF_SLUG.example.com
    on_stop: stop-review-app

# Сквозные тесты по живому URL
e2e-smoketest:
  stage: verify-preview
  script:
    - playwright test --url $CI_ENVIRONMENT_URL
  needs: ["review-app"]

stop-review-app:
  stage: cleanup
  script:
    - helm uninstall review-$CI_COMMIT_REF_SLUG
  when: manual
  environment:
    name: review/$CI_COMMIT_REF_NAME
    action: stop
```

### Ворота покрытия в GitLab CI (нативные Quality Gates)

GitLab имеет встроенные механизмы контроля покрытия без сторонних плагинов. Два независимых механизма:

**1. Процент в MR-widget (ключ `coverage`).** Регулярное выражение извлекает процент покрытия из лога задания; значение отображается в виджете Merge Request с дельтой относительно целевой ветки, в истории аналитики и в бейджах.

**2. Построчные аннотации в diff MR (ключ `artifacts:reports:coverage_report`).** Файл покрытия (Cobertura или JaCoCo) загружается как артефакт; GitLab в фоне размечает изменённые строки MR-диффа зелёным/красным в зависимости от покрытия. Аннотации видны только для файлов, изменённых в MR.

```yaml
test:coverage:
  stage: test
  script:
    - pytest --cov=src --cov-report=xml:coverage.xml --cov-report=term-missing
  coverage: '/TOTAL.+ ([0-9]{1,3}%)/'   # извлечение % из лога для MR-widget
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura      # или jacoco
        path: coverage.xml
    paths:
      - coverage.xml
```

**Принудительное применение (approval rules):** в Premium/Ultimate можно включить правило одобрения `Coverage-Check`, требующее одобрения при снижении покрытия относительно базового прогона; в 2026 добавлен параметр `coverage_minimum_threshold` — жёсткий порог, блокирующий слияние при покрытии ниже заданного значения независимо от дельты.

### Нагрузочное тестирование в CI (k6 и Quality Gates)

Инструмент **k6** является стандартом для Performance Testing as Code. В CI/CD он используется не для проверки предела производительности, а для верификации соблюдения **SLA/SLO** и **обнаружения регрессий (Regression Detection)**. Обзор ключевых концепций k6 (stages, thresholds, checks, переменные окружения): **[Нагрузочное тестирование с помощью k6](./k6_load_testing.md)**. Подробная теория и определения: **[Методология тестирования производительности](./performance_testing_methodology.md)**.

#### 1. Скрипт с описанием порогов и базовой линии (`load-test.js`)
Ключевым механизмом Quality Gates в k6 является объект `thresholds`. Для реализации Regression Detection в 2026 году используется сравнение с динамической базовой линией.

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

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
    http_req_failed: ['rate<0.01'],    // Абсолютный порог: ошибки < 1%
    http_req_duration: ['p(95)<500'],  // Абсолютный порог: P95 < 500мс
  },
};

export default function () {
  const url = __ENV.TARGET_URL || 'http://localhost:8080';
  const res = http.get(`${url}/api/v1/resource`);
  check(res, { 'status is 200': (r) => r.status === 200 });
  sleep(1);
}
```

#### 2. Интеграция в GitLab CI: Regression Detection
Для автоматического сравнения текущих результатов с предыдущими используются JSON-отчеты и артефакты CI.

```yaml
performance-test:
  stage: verify-preview
  image: 
    name: grafana/k6:2.3.0
    entrypoint: [""]
  variables:
    TARGET_URL: "https://$CI_COMMIT_REF_SLUG.example.com"
  script:
    # 1. Запуск теста с генерацией JSON-отчета
    - k6 run --summary-export=result.json ./tests/load-test.js
    # 2. Логика Regression Detection (сравнение с baseline из артефактов main)
    - |
      if [ -f baseline.json ]; then
        PREV_P95=$(jq '.metrics.http_req_duration.values."p(95)"' baseline.json)
        CURR_P95=$(jq '.metrics.http_req_duration.values."p(95)"' result.json)
        # Блокировка, если P95 вырос более чем на 10%
        if (( $(echo "$CURR_P95 > $PREV_P95 * 1.1" | bc -l) )); then
          echo "Performance regression detected! Baseline: ${PREV_P95}ms, Current: ${CURR_P95}ms"
          exit 1
        fi
      fi
  artifacts:
    paths:
      - result.json
    expose_as: 'performance-report'
  # Загрузка последнего успешного отчета из основной ветки как baseline
  needs:
    - job: performance-test
      project: my-org/my-project
      ref: main
      artifacts: true
```

#### 3. Интеграция с Prometheus (Performance-as-Code)
Для долгосрочного анализа трендов k6 отправляет метрики напрямую в Prometheus через Remote Write.

**Схема:** `k6 --[Remote Write]--> Prometheus --[Query API]--> CI Gate`

```yaml
performance-prometheus:
  stage: verify-preview
  script:
    # Запуск с расширением xk6-output-prometheus-remote
    - k6 run -o output-prometheus-remote ./tests/load-test.js \
      --tag commit=$CI_COMMIT_SHA \
      --tag env=$CI_ENVIRONMENT_SLUG
  variables:
    K6_PROMETHEUS_REMOTE_URL: "http://prometheus:9090/api/v1/write"
```

**Рекомендации 2026:**
- **Baseline:** Храните эталонные результаты в Git (LFS) для критических релизов или в выделенном объектном хранилище (MinIO, NAS).
- **Изоляция:** Используйте `dedicated` раннеры, чтобы избежать влияния соседних сборок на Latency.
- **Quality Gates:** Начинайте с "мягких" порогов (`allow_failure: true`), переводя их в блокирующие только после стабилизации окружения.

### Chaos Engineering в CI (проверка устойчивости)

В 2026 году Chaos Engineering перестал быть только упражнением в Production (Game Days) и стал частью CI-пайплайна. Интеграция «хаос-экспериментов» позволяет гарантировать, что новая версия приложения корректно обрабатывает сбои инфраструктуры (потерю связи с БД, задержки сети, перезапуск подов).

#### 1. Использование Chaos Mesh в пайплайне
Chaos Mesh поддерживает запуск экспериментов через Custom Resources (CRD), что удобно для CI/CD в Kubernetes.

```yaml
# chaos-experiment.yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: api-network-delay
spec:
  action: delay
  mode: one
  selector:
    labelSelectors:
      'app': 'my-api-service'
  delay:
    latency: '200ms'
    correlation: '100'
  duration: '30s'
```

#### 2. Сценарий автоматизированного эксперимента (GitLab CI)
Алгоритм проверки: запуск приложения → подача нагрузки → инъекция сбоя → проверка SLO.

```yaml
chaos-test:
  stage: verify-preview
  script:
    # 1. Запуск нагрузки в фоне (k6)
    - k6 run load-test.js --duration 1m &
    # 2. Применение хаос-эксперимента
    - kubectl apply -f ./tests/chaos-experiment.yaml
    # 3. Ожидание завершения и проверка метрик
    - sleep 40
    - |
      SUCCESS_RATE=$(curl -s "http://prometheus:9090/api/v1/query?query=success_rate_last_minute")
      if [ $(echo "$SUCCESS_RATE < 0.95" | bc) -eq 1 ]; then
        echo "Chaos test failed: SLO violation during network delay"
        exit 1
      fi
  only:
    - schedules
    - tags
```

### Визуальное регрессионное тестирование (Visual Regression)

Snapshot-тестирование интерфейсов (Visual Diffing) необходимо для обнаружения «сломанной» верстки, которую не ловит функциональное E2E-тестирование. 

**Практическое руководство, настройка Docker и примеры пайплайнов:** **[Visual Regression в CI/CD](../CI-CD/Testing/visual-regression-cicd.md)**.

### Пайплайн для GitHub Actions (матрица и параллелизм)

GitHub Actions использует другой синтаксис, но принципы те же: эфемерные раннеры, артефакты, матрицы для параллелизма.

```yaml
# .github/workflows/test.yml
name: Integration Tests
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [postgres, redis, kafka]
    steps:
      - uses: actions/checkout@v7
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests for ${{ matrix.service }}
        run: pytest tests/integration/${{ matrix.service }}/
        env:
          SERVICE: ${{ matrix.service }}
```

**Примечание:** `cache: 'pip'` в `actions/setup-python` автоматически кэширует зависимости между запусками. Для Docker-слоёв используйте `actions/cache` с ключом по `Dockerfile.hash`.

### Управление секретами для интеграционных тестов

Интеграционные тесты часто требуют реальные credentials (пароли БД, API-ключи). В CI секреты поступают через защищенные переменные окружения.

**Паттерн 1: Переменные окружения (рекомендуется для Testcontainers)**

Testcontainers автоматически подхватывает переменные окружения раннера. Вместо хардкода используйте переменные CI:

```python
postgres = PostgresContainer("postgres:16")
postgres.with_env("POSTGRES_PASSWORD", os.environ["DB_PASSWORD"])
postgres.start()
```

**Паттерн 2: Временные файлы (для legacy-приложений)**

Если приложение читает секрет из файла, запишите переменную во временный файл на раннере и прокините через bind mount:

```bash
echo "$DB_PASSWORD" > /tmp/db_secret
```

**Паттерн 3: HashiCorp Vault (on-prem)**

Для on-prem сред с Vault используйте динамическую выдачу секретов в пайплайне:

```bash
vault kv get -format=json secret/test/db-credentials | jq -r '.data' > /tmp/creds.json
```

### Шардирование и параллелизм тестов

Помимо TIA (запуск только затронутых тестов), для ускорения CI используются:

1. **Матричные сборки (Matrix Builds):** Один пайплайн запускает тесты параллельно на нескольких комбинациях (ОС, версия Python, тип БД).
2. **pytest-xdist:** Распределение тестов внутри джоба по нескольким процессам. Учитывайте изоляцию: каждый worker должен использовать отдельный порт/БД.
3. **pytest-shard:** Разделение набора тестов на `N` примерно равных частей по хешу имени теста. Полезно для параллельного запуска на разных раннерах.
4. **Ограничение:** Параллельные контейнеры Testcontainers потребляют память. Настройте `TESTCONTAINERS_RYUK_DISABLED=true` только если CI сам очищает контейнеры, или ограничьте количество параллельных джобов через `concurrent` в `.gitlab-ci.yml` / `concurrency` в GitHub Actions.

### Артефакты и управление результатами тестов

Артефакты тестов — это не только логи, но и структурированные отчёты для пост-фактум анализа:

```yaml
# GitLab CI
test:integration:
  stage: test
  script:
    - pytest tests/ --junitxml=report.xml --cov=src --cov-report=xml:coverage.xml
  artifacts:
    when: always
    paths:
      - report.xml
      - coverage.xml
      - logs/
    expire_in: 7 days
    reports:
      junit: report.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

**Практики:**
- **Retention:** Храните артефакты минимум 7–14 дней для возможности пересборки baseline. Для релизных джоб — бессрочно или по политике хранения.
- **Размер:** Исключайте `node_modules/`, `.git/`, `__pycache__/` из артефактов. Используйте `artifacts:exclude`.
- **Доступ:** В GitLab Premium/Ultimate артефакты доступны через API для построения дашбордов стабильности.

### Оптимизация стоимости CI для тестов

Интеграционные тесты — самая ресурсоёмкая часть пайплайна. Подходы 2026:

1. **Триггеры:** Запускайте интеграционные тесты только при изменениях в relevant-коде (TIA, path filters), а не на каждый коммит.
2. **Runner-ы:** Используйте self-hosted runners с spot/preemptible инстансами для не-critical джоб. Резервируйте dedicated раннеры только для нагрузочного тестирования.
3. **Кэширование:** Кэшируйте зависимости (`pip`, `npm`, `~/.m2`) и Docker-слои. Для Testcontainers предварительно загружайте базовые образы на раннер.
4. **Пропуск дублирующих запусков:** В GitHub Actions используйте `concurrency` с `cancel-in-progress: true`. В GitLab CI — `interruptible: true`.
5. **Сагрегированные запуски:** Ночные/периодические полные прогоны вместо запуска всего на каждый коммит.

## 4. Устранение неполадок (Troubleshooting)

### Типичные проблемы и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Тест падает с `timeout` в CI, локально проходит** | Медленная загрузка образов, resource contention на shared-раннере | `docker pull` timing в job logs, `nmon`/`htop` на раннере | Pre-pull образы (см. §3), использовать dedicated раннеры для тяжёлых тестов |
| **OOMKill во время тестов** | Превышен лимит памяти контейнера/раннера | `dmesg \| grep -i kill`, метрика `container_memory_working_set_bytes` в cAdvisor | `withCreateContainerCmdModifier().withMemory(256*1024*1024)`, настройка `mem_limit` в `.gitlab-ci.yml` |
| **Port conflict (Address already in use)** | Параллельные тесты используют статические порты | `docker ps`, логи теста с указанием порта | Testcontainers использует динамические порты автоматически; для ручных — `socket.getFreePort()` |
| **`Connection refused` к зависимости в ephemeral env** | Сервис ещё не готов к accepting | `docker logs <container>`, проверка healthcheck | `Wait.forHttp("/health").forStatusCode(200)`, увеличить `withStartupTimeout(Duration.ofMinutes(2))` |
| **Artifact upload timeout / `ERROR: Job failed: exit code 1`** | Артефакт слишком большой, artifact storage переполнен | `du -sh artifacts/`, логи GitLab Runner | `artifacts:exclude` для `node_modules/`, `.git/`; `expire_in: 7 days`; разбить на chunks |
| **Flaky test только в CI** | Noisy neighbor, timezone drift, NTP | `timedatectl status`, `cat /proc/meminfo`, correlation с cAdvisor | Выделенные раннеры, UTC everywhere, Testcontainers для изоляции |
| **Docker daemon `No space left on device`** | Накопились остановленные контейнеры/образы | `docker system df`, `du -sh /var/lib/docker` | `after_script: docker system prune -a -f --filter "label=com.testcontainers=true"`, `docker image prune` |
| **Ryuk не удаляет контейнеры** | `TESTCONTAINERS_RYUK_DISABLED=true` или образ Ryuk недоступен | `docker logs` контейнера, проверка env-переменной | Убедиться, что Ryuk запущен; для CI — `after_script: docker rm -f $(docker ps -aq --filter "label=com.testcontainers=true") || true` |
| **Rate-limiting Docker Hub при `docker pull`** | Превышен лимит анонимных запросов (100/6h) | Логи `docker pull` с `429 Too Many Requests` | Registry mirror, pre-pull образов, `TESTCONTAINERS_HOST_OVERRIDE` для локального registry |

**DevOps/SRE диагностика в CI:**
```bash
# Pre-flight проверки перед прогоном тестов
df -h /var/lib/docker /tmp
free -m
cat /proc/loadavg
docker info | grep -E "Storage Driver|Cgroup"
docker system df

# Post-mortem: сбор логов всех контейнеров Testcontainers
docker ps -a --filter "label=com.testcontainers=true" --format "{{.ID}}" | \
  xargs -r docker logs --tail=100 > testcontainers-logs.txt

# Cleanup в GitLab CI
after_script:
  - docker system prune -af --filter "label=com.testcontainers=true"
  - docker volume prune -f
```

### Корреляция тестовых падений с метриками раннера

Диагностика flaky тестов требует корреляции JUnit/JSON артефактов с метриками раннера. Подробности: **[Наблюдаемость пайплайнов](../CI-CD/Core_Concepts/pipeline_observability.md)** — схемы сбора OTel-трейсов, cAdvisor/node-exporter метрики, правила сопоставления `trace_id`.

Для Testcontainers-специфичной наблюдаемости: **[Testcontainers: обзор](./testcontainers_overview.md#надёжность-и-наблюдаемость-sre)** — метрики `testcontainers_container_startup_seconds`, алертинг на Ryuk и диск, централизованное логирование через `com.testcontainers=true`.

---

## 5. Лучшие практики (Best Practices)

### Проектирование тестов в CI

- **Изоляция на уровне сети:** каждый pipeline использует отдельную Docker-сеть; Testcontainers создаёт изолированную сеть автоматически. Для ручных сценариев — `docker network create` в начале, `docker network rm` в `after_script`.
- **Ephemeral окружения:** эфемерные раннеры (см. **[Управление парком раннеров](../CI-CD/runner-fleet-management.md)**) гарантируют чистое окружение. Для shared runners используйте `--max-concurrent=1` в конфигурации.
- **Resource limits:** задавайте CPU и memory лимиты для тестовых контейнеров — это предотвращает OOMKill и noisy neighbor эффект. Пример: `withCreateContainerCmdModifier(cmd → cmd.withMemory(512*1024*1024L).withMemoryReservation(256*1024*1024L))`.

### Оптимизация кэширования

- **Кэш зависимостей:** `pip`, `npm`, `~/.m2`, `~/.gradle` — используйте `cache` в GitLab CI / `actions/cache` в GitHub Actions.
- **Кэш Docker layers:** используйте Docker-in-Docker с shared cache volume или `buildkit` с `--cache-from`.
- **Pre-pull Testcontainers образы:** на раннерах с ограниченной пропускной способностью Docker Hub добавляйте шаг `docker pull` в `before_script`.

### Безопасность

- **Секреты через env:** никогда не хардкодьте credentials; используйте CI-переменные (`DB_PASSWORD`, `API_TOKEN`).
- **Секреты через файлы:** для legacy-приложений пишите секрет во временный файл с `0600` и удаляйте в `after_script`.
- **Сокращение привилегий:** Testcontainers/Ryuk работают без `--privileged` (начиная с Ryuk 0.13.0 на базе `scratch`).

### SRE-практики: мониторинг и очистка

- **Periodic cleanup:** `docker system prune -a -f --filter "label=com.testcontainers=true"` в `after_script` или через cron на раннере.
- **Resource alerts:** мониторинг `/var/lib/docker` (>85%), RAM (>90%), CPU steal в реальном времени (cAdvisor + Prometheus).
- **Graceful shutdown:** раннеры должны обрабатывать `SIGTERM` — дать тесту шанс завершиться, иначе `docker rm -f` в `after_script`.

### Release Validation (SRE)

- **Pre-deployment smoke test:** перед деплоем в staging поднимайте через Testcontainers те же сервисы, что и в production (PostgreSQL, Redis, Kafka), применяйте миграции, выполняйте smoke-тесты.
- **Canary validation:** используйте Testcontainers для проверки миграций на копии production-данных (с маскированием) перед реальным применением.
- **Контрактное тестирование:** комбинируйте Testcontainers с Pact для проверки API-контрактов в эфемерной среде.

---

## 6. Дополнительная информация

#### Управление нестабильностью тестов (Flaky Tests)

Нестабильные тесты не должны блокировать релизы. Подходы к детекции, карантину, автоматическому retry и root cause analysis описаны в **[Управление нестабильными тестами (Flaky Tests)](../CI-CD/Testing/flaky_test_management.md)**.

#### Наблюдаемость пайплайнов

Общая наблюдаемость пайплайнов (трассировка джобов, метрики раннеров, анализ DAG) — в отдельном SSoT: **[Наблюдаемость пайплайнов](../CI-CD/Core_Concepts/pipeline_observability.md)**.

Для диагностики падений тестов достаточно корреляции артефактов (JUnit, логи) с системными метриками раннера (CPU, память, сеть).

---

#### Связанные документы

*   **[Виды тестов: Unit, Integration, E2E](./testing_types_unit_integration_e2e.md)** — база для выбора стратегии.
*   **[Testcontainers: обзор](./testcontainers_overview.md)** — основа для интеграционных тестов в CI.
*   **[Управление нестабильными тестами (Flaky Tests)](../CI-CD/Testing/flaky_test_management.md)** — детекция, карантин, retry.
*   **[Наблюдаемость пайплайнов](../CI-CD/Core_Concepts/pipeline_observability.md)** — трассировка и метрики CI.
*   **[Управление парком раннеров](../CI-CD/runner-fleet-management.md)** — эфемерные раннеры, автоскейлинг, очистка.
*   **[Метрики тестового покрытия](./testing_coverage_metrics.md)** — глубокий анализ полноты проверок и связи с TIA.
