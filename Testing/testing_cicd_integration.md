# Интеграция автоматизированных тестов в CI/CD

## 1. Определения

**Quality Gates (Ворота качества)** — набор автоматизированных критериев и проверок в пайплайне, которые сборка должна успешно пройти для продвижения на следующий этап (например, из Test в Staging).

**Shift-left Testing (Сдвиг влево)** — перенос тестирования на самые ранние этапы разработки (IDE, Pre-commit), чтобы обнаруживать ошибки до того, как они попадут в общую ветку кода.

**Shift-right Testing (Сдвиг вправо)** — тестирование в среде эксплуатации (Production) через Canary-деплои, Feature Toggles и синтетический мониторинг. Ключевой принцип — управляемый «радиус поражения» (blast radius): каждое приём в production должно быть малым и обратимым. Подробнее о канареечном развёртывании и метриках автогейтов: **[Canary мониторинг и гейтинг](../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md)**.

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
    name: grafana/k6:latest
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
- **Baseline:** Храните эталонные результаты в Git (LFS) для критических релизов или в выделенном S3-бакете.
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

### 4. Дополнительная информация


### Борьба с нестабильностью (AI-Driven Flaky Detection)

В 2026 году системы CI используют AI для автоматического управления Flaky-тестами:
*   **Авто-карантин:** Если тест падает с ошибкой тайм-аута, но проходит при перезапуске, AI помечает его как "Flaky" и убирает из блокирующих ворот качества.
*   **Root Cause Analysis:** Система сопоставляет логи теста с изменениями в инфраструктуре (например, обновление версии БД) и предлагает решение.
*   **Self-healing:** Автоматическое исправление локаторов в UI-тестах при изменении верстки.

### CI/CD Observability (OpenTelemetry)

Интеграция пайплайнов с OpenTelemetry позволяет анализировать их как распределенные системы:
*   Каждый джоб и шаг пайплайна генерирует **span**.
*   Визуализация в Grafana/Tempo помогает найти "бутылочное горлышко" в процессе сборки и проанализировать критический путь в DAG.
*   Корреляция логов тестов с трейсами приложения упрощает отладку интеграционных сценариев.

**Подробнее:** **[Наблюдаемость пайплайнов](../../CI-CD/Core_Concepts/pipeline_observability.md)**.

---

### Связанные документы

*   **[Виды тестов: Unit, Integration, E2E](./testing_types_unit_integration_e2e.md)** — база для выбора стратегии.
*   **[Testcontainers: обзор](./testcontainers_overview.md)** — основа для интеграционных тестов.
*   **[Метрики тестового покрытия](./testing_coverage_metrics.md)** — глубокий анализ полноты проверок и связи с TIA.
