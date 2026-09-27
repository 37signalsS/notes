# Инструменты для генерации отчётов о тестировании

## 1. Определения

**Тестовый отчёт (Test Report)** — документ или интерактивная панель, фиксирующая результаты выполнения тестов (прошел/упал/пропущен), время выполнения и сопутствующие артефакты (логи, скриншоты).

**Test Observability (Наблюдаемость тестов)** — концепция 2025–2026 годов, выходящая за рамки простой фиксации результатов. Она включает глубокий анализ контекста падений (трассировки, метрики системы во время теста) и автоматическую диагностику причин.

**JUnit XML** — общепринятый машиночитаемый стандарт обмена данными о результатах тестирования, поддерживаемый почти всеми CI/CD системами.

**Allure Report** — самый распространённый open-source фреймворк (Apache 2.0) генерации детализированных человекочитаемых отчётов. Актуальная мажорная версия — **Allure 3** (2024+): полностью переписана на TypeScript, использует модульную систему плагинов (UI «Awesome»), поддерживает quality gates и не требует Java (CLI ставится через npm). Результаты собираются в `JSON`-артефакты (`--alluredir`), из которых команды `allure generate` / `allure serve` строят HTML-отчёт; real-time режим — `allure watch`.

## 2. Основные концепции

### Эволюция отчетности: от фактов к аналитике

В современной разработке (2025+) фокус сместился с вопроса «что упало?» на вопрос «почему упало и как это исправить?»:
*   **Кластеризация падений (Failure Clustering):** Группировка сотен упавших тестов по схожим признакам (стектрейсам, ошибкам в логах) для быстрого анализа.
*   **Автоматическая диагностика:** Использование правил и шаблонов для автоматического анализа логов и выдачи резюме о корневой причине (Root Cause Analysis).
*   **Автономное тестирование (2026):** Платформы отчётности научились принимать результаты не только классического автоматизированного, но и автономного тестирования как отдельный тип выполнения и объединять их с обычными прогонами в одном интерфейсе (например, ReportPortal 26.x).
*   **Анализ нестабильности (Flaky Tests):** Автоматическое выявление тестов, которые ведут себя недетерминированно, и их временная изоляция (карантин).

### Сравнение архитектурных подходов

| Подход | Инструменты | Особенности |
| :--- | :--- | :--- |
| **Статические отчёты** | Allure, pytest-html | Генерируются как HTML-артефакты после завершения всех тестов. Подходят для малых и средних проектов. |
| **Real-time платформы** | ReportPortal, Allure TestOps | Серверные решения с мгновенным доступом к результатам в процессе выполнения, долгосрочной историей и предиктивной аналитикой. Актуальные версии (2026): ReportPortal 26.x и Allure TestOps 26.2.x. |
| **Trace-based Testing** | Tracetest, Testkube | Тестирование на основе распределённых трассировок (OpenTelemetry) с ассертами против данных трейсов. Tracetest: коммерческое облако прекращено (EOL октября 2024), развивается OSS-версия. Testkube: Kubernetes-нативный оркестратор, с v1.21 (декабрь 2025) — унифицированный дашборд исполнений, PostgreSQL-бэкенд и TestWorkflows как единственный способ оркестрации. |

## 3. Практические сценарии

### Генерация отчётов в локальной среде

Большинство тестовых фреймворков требуют плагинов для поддержки современных форматов. Для Allure 3 CLI устанавливается через npm (`npx allure`), на Python ставится пакет `allure-pytest`; для Java используется Maven-зависимость `io.qameta.allure:allure-junit5`.

**Пример для Python (Pytest):**
```bash
# Запуск тестов с генерацией данных для Allure и JUnit XML
pytest --junitxml=reports/junit.xml --alluredir=reports/allure-results

# Генерация и открытие HTML-отчёта Allure
allure serve reports/allure-results
```

**Пример для Java (Maven):**
```bash
# Результаты JUnit XML по умолчанию попадают в target/surefire-reports
mvn test
```

**Форматы JUnit-вывода по фреймворкам (2026):**

| Экосистема | Флаг вывода JUnit XML |
| :--- | :--- |
| Python (pytest) | `pytest --junitxml=report.xml` |
| JavaScript (Jest) | `--reporters=jest-junit` |
| JavaScript (Playwright) | встроенный `junit` reporter |
| Go | `gotestsum --junitfile report.xml` |
| Java (Maven) | автоматически (`target/surefire-reports`) |
| .NET | `dotnet test --logger "junit;LogFilePath=report.xml"` |
| Ruby (RSpec) | `rspec --format RspecJunitFormatter --out report.xml` |

### Расширенные возможности JUnit XML

Стандарт JUnit XML поддерживает вложения (attachments), свойства (properties) и вывод в stdout/stderr, что критически важно для отладки:

```xml
<testsuite name="auth" tests="3" failures="1" errors="0" skipped="0" time="2.45">
  <testcase name="test_login_success" classname="auth.TestAuth" time="0.12">
    <system-out>Username: admin, Password: ****</system-out>
  </testcase>
  <testcase name="test_login_failure" classname="auth.TestAuth" time="0.08">
    <failure message="AssertionError: 401 != 200" type="AssertionError">
      <![CDATA[Traceback (most recent call last): ...]]>
    </failure>
    <system-out>Response body: {"error": "invalid_token"}</system-out>
  </testcase>
</testsuite>
```

**Инструментарий:**
- **pytest:** `pytest --junitxml=report.xml --junit-prefix=service-name --junit-family=xunit2`
- **Jest:** `--reporters=jest-junit` с переменной `JEST_JUNIT_OUTPUT`
- **Go:** `gotestsum --junitfile report.xml --format=standard-json`
- **Maven:** `surefire-report:bundle` генерирует `TEST-*.xml` в `target/surefire-reports`

**Вложения в отчёты:** Для Allure и ReportPortal используйте хук `pytest_runtest_makereport` в `conftest.py` для автоматического прикрепления скриншотов, логов и дампов при падении.

### Шардирование и агрегация отчётов

При запуске тестов в параллельных джобах (matrix builds, pytest-xdist) каждая джоба генерирует свой отчёт. Без сбора вместе вы получите заниженные цифры или потерю части результатов.

**Сбор покрытия из параллельных джобов:**

```bash
# В каждой джобе: сохранение отчёта с уникальным именем
pytest --junitxml=results-${CI_NODE_INDEX}.xml --alluredir=allure-results-${CI_NODE_INDEX}

# В агрегирующей джобе: объединение JUnit
python -c "
import xml.etree.ElementTree as ET
import glob

combined = ET.Element('testsuite', name='combined')
for f in sorted(glob.glob('results-*.xml')):
    tree = ET.parse(f)
    for tc in tree.findall('.//testcase'):
        combined.append(tc)
ET.ElementTree(combined).write('results-combined.xml')
"
```

**Для Allure:**
```bash
# В каждой джобе: результаты в отдельной директории
pytest --alluredir=allure-results-${CI_NODE_INDEX}

# В агрегирующей джобе: объединение
allure combine allure-results-* -o allure-results-combined
allure generate allure-results-combined -o allure-report --clean
```

**Правила:**
- Используйте уникальные имена файлов для каждого шарда (`results-${CI_NODE_INDEX}.xml`).
- Для matrix builds собирайте артефакты из каждой джобы и объединяйте в `post`-джобе.
- При использовании `pytest-xdist` каждый воркер сохраняет свой отчёт в `.coverage.*`; для JUnit используйте `--json-report` с `pytest-json-report`.

### Лёгкая альтернатива — pytest-html

Для малых проектов или локальной верификации применим плагин `pytest-html`, генерирующий единый самодостаточный HTML-файл (`--html=report.html --self-contained-html`). Он проще в установке, чем Allure, но не даёт истории, трендов и вложенных шагов; для CI-артефактов и командных отчётов предпочтителен Allure.

### Интеграция в пайплайны GitLab CI

GitLab умеет нативно отображать результаты тестов в Merge Request, если передать ему файл в формате JUnit XML. Результаты сравниваются между исходной (source) и целевой (target) ветками: новые падения подсвечиваются отдельно. Особенности интеграции:
*   **Статус задания не зависит от отчёта:** JUnit-данные лишь визуализируются; за провал задания отвечает ненулевой код возврата команды тестов.
*   **Лимиты:** файл до 30 МБ на один отчёт, суммарно до 100 МБ на задание; путь не должен быть директорией (только файл или glob).
*   **Screenshots:** вкладка Tests может показывать скриншоты, если JUnit содержит `attachment`-теги, а сами файлы включены в `artifacts:paths`.

```yaml
# .gitlab-ci.yml
test:integration:
  stage: test
  script:
    - pytest --junitxml=report.xml --alluredir=allure-results
    - allure generate allure-results -o allure-report --clean
  artifacts:
    when: always
    reports:
      junit: report.xml  # GitLab парсит этот файл для вкладки "Tests"
    paths:
      - allure-report/    # Сохранение полного отчёта как артефакта
    expire_in: 7 days
```

### Интеграция в пайплайны GitHub Actions

GitHub Actions отображает результаты тестов через Check Runs и Step Summary. Для публикации JUnit-отчёта требуется экшен с правами `checks: write`. Публикация должна выполняться при любом исходе (`if: always()`), иначе падающие тесты останутся без отчёта.

```yaml
# .github/workflows/test-report.yml
name: Test Report
on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-html allure-pytest
      - name: Run tests with JUnit and Allure
        run: |
          pytest tests/ \
            --junitxml=reports/junit.xml \
            --alluredir=reports/allure-results \
            --html=reports/report.html --self-contained-html
      - name: Publish JUnit report
        if: always()
        uses: mikepenz/action-junit-report@v4
        with:
          report_paths: reports/junit.xml
          require_tests: true
          annotate_notice: false
      - name: Upload Allure artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: reports/allure-results/
          retention-days: 14
      - name: Upload HTML report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: html-report
          path: reports/report.html
          retention-days: 14
```

**Практические нюансы:**
- **Права:** `permissions: checks: write` требуется для создания Check Run; для форк-PR токен read-only — используйте артефакт + follow-up воркфлоу на `workflow_run`.
- **Аннотации:** `annotate_notice: false` публикует аннотации только для реальных падений, не засоряя PR.
- **Валидация:** в PR появляется проверка «Tests report» со счётчиками; сломанный assert даёт аннотацию с именем кейса и путём к файлу прямо у строки кода.

## 4. Дополнительная информация

### Продвинутая визуализация в Grafana

В 2026 году Grafana стала стандартом для агрегации метрик качества на уровне CTO/Engineering Manager.
*   **Quality Dashboards:** Наложение графиков успешности тестов на графики потребления ресурсов (CPU/RAM) или бизнес-метрик. ReportPortal содержит модуль `service-metrics-gatherer`, который автоматически создаёт data source-ы и дашборды в Grafana для метрик выполнения (Project Launches, XUnit) из собственного хранилища — PostgreSQL и индексов Elasticsearch/OpenSearch.
*   **Data Sources:** Grafana подключается напрямую к хранилищам ReportPortal (PostgreSQL для метаданных, OpenSearch/Elasticsearch для логов) либо к экспортерам Prometheus, собирающим статистику пайплайнов. Встроенный PostgreSQL-плагин Grafana позволяет строить произвольные SQL-запросы по данным запусков.

### Рекомендации по наполнению отчётов

1.  **Скриншоты и видео:** Прикрепляйте их только для упавших тестов (через хуки `on_failure`), чтобы не перегружать хранилище артефактов. Автоматическое прикрепление скриншота при падении в pytest реализуется через хук `pytest_runtest_makereport` в `conftest.py` (связка Selenium/Playwright + `allure.attach.file`).
2.  **Контекст запросов:** Для API-тестов полезно логировать `Trace-ID` (OpenTelemetry), чтобы можно было мгновенно перейти из отчёта в Jaeger или Grafana Tempo.
3.  **Метаданные:** Добавляйте теги (ID задачи в Jira, компонент, приоритет), чтобы отчеты можно было фильтровать по зонам ответственности.
4.  **История (Trends):** Для Allure тренды строятся из каталога `history`, который необходимо переносить из предыдущего прогона в `allure-results/history` перед генерацией — иначе каждый отчёт будет «островом» без истории. В CI это делается скачиванием предыдущего отчёта из артефактов. Альтернатива — Allure TestOps или ReportPortal, где история автоматически хранится в БД.
5.  **Флаг `--clean-alluredir`**: Применяйте его в CI, чтобы избежать смешивания артефактов разных прогонов, но учитывайте, что он стирает историю — используйте его совместно с переносом каталога `history`.
6.  **Независимость от статуса задания:** Генерацию отчёта запускайте даже при падении тестов (`when: always` в GitLab, `continue-on-error: true` в GitHub Actions), иначе отчёт не соберётся именно тогда, когда он нужен больше всего.

### Управление секретами для инструментов отчётности

Self-hosted платформы отчётности (ReportPortal, Allure TestOps) требуют токены для доступа к API. В CI/CD секреты не должны храниться в репозитории.

| Инструмент | Переменная окружения | Где хранить |
| :--- | :--- | :--- |
| **ReportPortal** | `RP_API_KEY` | CI/CD variables (GitLab) / Secrets (GitHub) |
| **Allure TestOps** | `ALLURE_TOKEN` | CI/CD variables / Secrets |
| **SonarQube** | `SONAR_TOKEN` | CI/CD variables / Secrets |

**Правила:**
- Используйте встроенные хранилища секретов CI/CD (GitLab CI variables, GitHub Secrets).
- Для self-hosted раннеров храните токены в файлах с правами `600` или в HashiCorp Vault.
- Ротация токенов: каждые 90 дней или при утеске.

### Валидация артефактов отчётов

Пустой или повреждённый артефакт отчёта бесполезен для анализа. Валидируйте его сразу после генерации:

```bash
# Проверка размера и валидности JUnit XML
if [ ! -s reports/junit.xml ]; then
  echo "ERROR: JUnit report is empty"
  exit 1
fi

# Проверка валидности XML
python -c "import xml.etree.ElementTree as ET; ET.parse('reports/junit.xml')"

# Подсчёт статистики
TESTS=$(xmllint --xpath 'string(/testsuite/@tests)' reports/junit.xml)
FAILURES=$(xmllint --xpath 'string(/testsuite/@failures)' reports/junit.xml)
echo "Tests: $TESTS, Failures: $FAILURES"

# FAILURE -> красная сборка
if [ "$FAILURES" -gt 0 ]; then
  echo "Tests failed"
  exit 1
fi
```

**Правила:**
- Проверяйте, что артефакт загружен и не пуст (`[ -s file ]`).
- В GitLab используйте `coverage_report`, в GitHub — `actions/upload-artifact` + проверку размера.
- Для Allure проверяйте наличие файлов в `allure-results/` (минимум один `.json`).

### Именование тестов для читаемых отчётов

Одинаковые имена тестов в разных классах/модулях размывают отчёт. Используйте консистентные префиксы:

```python
# Плохо
def test_login(): ...

# Хорошо
def test_auth_login_success(): ...
def test_auth_login_invalid_password(): ...
```

**Правила:**
- Используйте префикс с именем модуля/компонента: `auth_`, `payment_`, `api_`.
- Для Allure используйте `@allure.title("...")` и `@allure.description("...")` для человекочитаемых заголовков.
- Для JUnit используйте `--junit-prefix=service-name` (pytest) или `--testNamePattern` (Maven).

### Устранение неполноты отчётности

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Отчёт не попал в PR | Нет `checks: write` (GitHub) или форк-PR | Добавить permission; для форков — артефакт + `workflow_run` |
| Пустой JUnit XML | Неверный путь/репортер; тихий провал раннера | Проверить локально путь отчёта; добавить `require_tests` |
| Дублированные тесты в отчёте | Запуск из разных директорий; duplicate test IDs | Использовать уникальные `classname` или `--junit-prefix` |
| Отчёт не обновляется в CI | Кэширование артефактов; старый `history` | Очищать `allure-results`; не использовать кэш для артефактов отчётов |
| Разные цифры локально и в CI | Отличается окружение, версии зависимостей | Использовать одинаковые версии инструментов; кэшировать зависимости |
| Падающие тесты без деталей | Нет вложений (screenshots, logs) | Добавить хук `pytest_runtest_makereport` для `allure.attach` |

### Self-hosted платформы отчётности

Для изолированных сред (on-prem, air-gapped) используйте self-hosted решения:

**ReportPortal (self-hosted):**
- Бэкенд: PostgreSQL + Elasticsearch/OpenSearch
- Агент: `rp-agent` или плагины для фреймворков (`rp-reportportal-allure`)
- Провиженинг: Helm-чарт или Docker Compose
- Минимальные требования: 4 CPU, 8 GB RAM, 50 GB SSD

**Allure TestOps (self-hosted):**
- Бэкенд: PostgreSQL
- Агент: `allurectl` CLI
- Провиженинг: Helm-чарт или Docker Compose
- Минимальные требования: 2 CPU, 4 GB RAM, 20 GB SSD

**Правила:**
- Храните токены доступа в Vault или CI/CD variables, никогда в репозитории.
- Настройте backup для PostgreSQL (ежедневный дамп, retention 30 дней).
- Ограничьте доступ к веб-интерфейсу через VPN или IP-whitelist.

### Бейджи покрытия в README

Для быстрого визуального контроля качества добавьте бейдж покрытия в README проекта. Для self-hosted инфраструктуры генерируйте бейдж самостоятельно из JSON-отчёта:

```bash
# Генерация JSON отчёта о покрытии
coverage json -o coverage.json

# Извлечение процента и обновление бейджа (через скрипт)
python -c "
import json
with open('coverage.json') as f:
    data = json.load(f)
percent = data['totals']['percent_covered']
print(f'Coverage: {percent:.1f}%')
"
```

**Правила:**
- Используйте отдельный бейдж для каждой ветки (main, develop), чтобы не показывать заниженные цифры feature-веток.
- При использовании сторонних сервисов (Codecov, Coveralls) убедитесь, что они не передают данные за пределы инфраструктуры.
- Для полностью изолированных сред (air-gapped) храните бейдж как статический SVG в репозитории.

---

### Связанные документы

*   **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — общая стратегия встраивания проверок.
*   **[Виды тестов: Unit, Integration, E2E](./testing_types_unit_integration_e2e.md)** — уровни тестов и их детализация.
*   **[Метрики тестового покрытия](./testing_coverage_metrics.md)** — количественные показатели полноты тестирования.
