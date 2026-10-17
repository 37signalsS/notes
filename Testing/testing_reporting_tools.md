# Инструменты для генерации отчётов о тестировании

**Актуально для:** Allure Report 3.x, ReportPortal 26.x, Allure TestOps 26.3.x (2026)

## Определения

**Тестовый отчёт (Test Report)** — документ или интерактивная панель, фиксирующая результаты выполнения тестов (прошел/упал/пропущен), время выполнения и сопутствующие артефакты (логи, скриншоты).

**Test Observability (Наблюдаемость тестов)** — концепция 2025–2026 годов, выходящая за рамки простой фиксации результатов. Она включает глубокий анализ контекста падений (трассировки, метрики системы во время теста) и автоматическую диагностику причин.

**JUnit XML** — общепринятый машиночитаемый стандарт обмена данными о результатах тестирования, поддерживаемый почти всеми CI/CD системами.

**Allure Report** — самый распространённый open-source фреймворк (Apache 2.0) генерации детализированных человекочитаемых отчётов. Актуальная мажорная версия — **Allure 3** (2024+): полностью переписана на TypeScript, использует модульную систему плагинов (UI «Awesome»), поддерживает quality gates и не требует Java. CLI построена на Node.js и ставится через npm (`npm i -g allure` или `npx allure`), поэтому для `generate`/`open`/`watch` требуется установленный Node.js даже в Python- и Java-проектах. Результаты собираются в `JSON`-артефакты (`--alluredir`), из которых команда `allure generate` строит HTML-отчёт, `allure open` открывает его в браузере; real-time режим — `allure watch`.

## Основные концепции

### Эволюция отчётности: от фактов к аналитике

В современной разработке (2025+) фокус сместился с вопроса «что упало?» на вопрос «почему упало и как это исправить?»:
*   **Кластеризация падений (Failure Clustering):** Группировка сотен упавших тестов по схожим признакам (стектрейсам, ошибкам в логах) для быстрого анализа.
*   **Автоматическая диагностика:** Использование правил и шаблонов для автоматического анализа логов и выдачи резюме о корневой причине (Root Cause Analysis).
*   **Анализ нестабильности (Flaky Tests):** Автоматическое выявление тестов, которые ведут себя недетерминированно, и их временная изоляция (карантин). Механика ретраев, карантина и метрик стабильности в CI документирована в [Управлении нестабильными тестами](../CI-CD/Testing/flaky_test_management.md).

### Сравнение архитектурных подходов

| Подход | Инструменты | Особенности |
| :--- | :--- | :--- |
| **Статические отчёты** | Allure, pytest-html | Генерируются как HTML-артефакты после завершения всех тестов. Подходят для малых и средних проектов. |
| **Real-time платформы** | ReportPortal, Allure TestOps | Серверные решения с мгновенным доступом к результатам в процессе выполнения, долгосрочной историей и предиктивной аналитикой. Актуальные версии (2026): ReportPortal 26.x и Allure TestOps 26.3.x. |
| **Trace-based Testing** | Tracetest, Testkube | Тестирование на основе распределённых трассировок (OpenTelemetry) с ассертами против данных трейсов. Tracetest: коммерческое облако прекращено (EOL октября 2024), развивается OSS-версия. Testkube: Kubernetes-нативный оркестратор, с v1.21 (декабрь 2025) — унифицированный дашборд исполнений, PostgreSQL-бэкенд и TestWorkflows как единственный способ оркестрации. |

## Практические сценарии

### Генерация отчётов в локальной среде

Большинство тестовых фреймворков требуют плагинов для поддержки современных форматов. Для Allure 3 CLI устанавливается через npm (`npx allure`), на Python ставится пакет `allure-pytest`; для Java используется Maven-зависимость `io.qameta.allure:allure-junit5`.

**Команды Allure 3 CLI:**

| Команда | Назначение |
| :--- | :--- |
| `allure generate <resultsDir>` | Сгенерировать HTML-отчёт из результатов (вывод по умолчанию — `allure-report/`) |
| `allure open [<reportDir>]` | Открыть сгенерированный отчёт в браузере |
| `allure watch <allureResultsDir>` | Real-time: автоматически обновлять отчёт при изменениях в `allure-results/` |
| `allure run -- <test_command>` | Запустить тесты и автоматически сгенерировать отчёт |
| `allure run --rerun <n> -- <test_command>` | Перезапустить упавшие тесты до `n` раз |

> Примечание: в Allure 3 флаг `--clean` от `allure generate` удалён (старые результаты игнорируются автоматически); команда `allure serve` заменена на `allure generate … --open` (или `allure open`).

**Пример для Python (Pytest):**
```bash
# Запуск тестов с генерацией данных для Allure и JUnit XML
pytest --junitxml=reports/junit.xml --alluredir=reports/allure-results

# Генерация и открытие HTML-отчёта Allure 3
allure generate reports/allure-results
allure open
# либо для наблюдения в реальном времени:
# allure watch reports/allure-results
```

> В Allure 3 каталог вывода (`allure-report/` по умолчанию) настраивается через файл конфигурации `allurerc.mjs` (`output: "./path/to/report"`), а не через CLI-флаг `--output`.

**Пример для Java (Maven):**
```bash
# Результаты JUnit XML по умолчанию попадают в target/surefire-reports
mvn test
# для Allure: адаптер io.qameta.allure:allure-junit5 пишет JSON в каталог alluredir,
# затем allure generate <allure-results> строит HTML-отчёт
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
- **Jest:** `--reporters=jest-junit` с переменными `JEST_JUNIT_OUTPUT_DIR` и `JEST_JUNIT_OUTPUT_NAME`. Переменная `JEST_JUNIT_OUTPUT` устарела — текущий `jest-junit` её не читает (см. [GitHub Actions: Тест-отчёты и надёжность тестов](../Github_CI/Test_Reporting_Reliability.md)).
- **Go:** `gotestsum --junitfile report.xml --format=standard-json`
- **Maven:** `surefire-report:bundle` генерирует `TEST-*.xml` в `target/surefire-reports`

**Вложения в отчёты:** Для Allure и ReportPortal используйте хук `pytest_runtest_makereport` в `conftest.py` для автоматического прикрепления скриншотов, логов и дампов при падении.

### Шардирование и агрегация отчётов

При запуске тестов в параллельных джобах (matrix builds, pytest-xdist) каждая джоба генерирует свой отчёт. Без сбора вместе вы получите заниженные цифры или потерю части результатов.

**Сбор покрытия из параллельных джоб:**

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

**Для Allure 3:**
```bash
# В каждой джобе: результаты в отдельной директории
pytest --alluredir=allure-results-${CI_NODE_INDEX}

# В агрегирующей джобе: объединение result-файлов (имена файлов UUID-управляемы, коллизий нет) и генерация
mkdir -p allure-results-combined
for d in allure-results-*; do cp -r "$d"/. allure-results-combined/; done
allure generate allure-results-combined
```

**Правила:**
- Используйте уникальные имена файлов для каждого шарда (`results-${CI_NODE_INDEX}.xml`).
- Для matrix builds собирайте артефакты из каждой джобы и объединяйте в `post`-джобе.
- При использовании `pytest-xdist` каждый воркер сохраняет свой отчёт в `.coverage.*`; для JUnit используйте `--json-report` с `pytest-json-report`.

### Лёгкая альтернатива — pytest-html

Для малых проектов или локальной верификации применим плагин `pytest-html`, генерирующий единый самодостаточный HTML-файл (`--html=report.html --self-contained-html`). Он проще в установке, чем Allure, но не даёт истории, трендов и вложенных шагов; для CI-артефактов и командных отчётов предпочтителен Allure.

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

### Интеграция в пайплайны GitLab CI

GitLab умеет нативно отображать результаты тестов в Merge Request, если передать ему файл в формате JUnit XML. Результаты сравниваются между исходной (source) и целевой (target) ветвями: новые падения подсвечиваются отдельно. Особенности интеграции:
*   **Статус задания не зависит от отчёта:** JUnit-данные лишь визуализируются; за провал задания отвечает ненулевой код возврата команды тестов.
*   **Лимиты:** файл до 30 МБ на один отчёт, суммарно до 100 МБ на задание; путь не должен быть директорией (только файл или glob).
*   **Screenshots:** вкладка Tests может показывать скриншоты, если JUnit содержит `attachment`-теги, а сами файлы включены в `artifacts:paths`.

```yaml
# .gitlab-ci.yml
test:integration:
  stage: test
  script:
    - pytest --junitxml=report.xml --alluredir=allure-results
    - allure generate allure-results
  artifacts:
    when: always
    reports:
      junit: report.xml  # GitLab парсит этот файл для вкладки "Tests"
    paths:
      - allure-report/    # Сохранение полного отчёта как артефакта
    expire_in: 7 days
```

Для связки покрытия кода с JUnit-отчётом в GitLab CI см. [Конструктор рабочих процессов GitLab CI/CD](../CI-CD/GitLab_CI/Advanced/gitlab_ci_workflow_builder.md) (сценарий с `coverage_report: cobertura`).

### Интеграция в пайплайны GitHub Actions

Публикация JUnit-отчётов в интерфейс GitHub (аннотации в PR, ретраи шагов, карантин флаки и авто-rerun) — достаточно глубокая тема, покрытая в отдельном документе-источнике. Здесь — лишь кратко:

*   Результаты публикуются через Check Run: `mikepenz/action-junit-report@v6` (требует `permissions: checks: write`).
*   Генерируйте `JUnit XML` (`pytest --junitxml=...`, `jest --ci --reporters=jest-junit`) и загружайте как артефакт (`actions/upload-artifact@v7`); публикация выполняется при любом исходе (`if: always()` / `if: ${{ !cancelled() }}`).
*   Allure-артефакты (`--alluredir`) загружаются тем же `actions/upload-artifact`.
*   Для форк-PR (read-only `GITHUB_TOKEN`) — артефакт + follow-up воркфлоу на `workflow_run`.

Подробности, примеры workflow и ограничения аннотаций (10 error + 10 warning на шаг) — в **[GitHub Actions: Тест-отчёты и надёжность тестов](../Github_CI/Test_Reporting_Reliability.md)**.

### Развёртывание self-hosted платформ отчётности

Для изолированных сред (on-prem, air-gapped) используйте self-hosted решения:

**ReportPortal (self-hosted):**
- Бэкенд: PostgreSQL + Elasticsearch/OpenSearch
- Агент: `rp-agent` или плагины для фреймворков (`rp-reportportal-allure`)
- Провиженинг: Helm-чарт или Docker Compose
- Минимальные требования (1-node): 2 CPU, 6 GB RAM; диск — под бинарное хранилище (объём растёт с вложениями/скриншотами)

**Allure TestOps (self-hosted):**
- Бэкенд: PostgreSQL 15+, Redis (сессии), брокер сообщений (RabbitMQ), S3-совместимое хранилище артефактов
- Агент: `allurectl` CLI
- Провиженинг: Helm-чарт или DEB/RPM-пакеты
- Минимальные требования (small project): 4 CPU, 8 GB RAM; PostgreSQL на SSD, отдельном диске от артефактов; диск выделяется по объёму тестов (≈300 ГБ в PostgreSQL на 100 000 тестов/год)

Доступ к веб-интерфейсу ограничьте через VPN или IP-whitelist.

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

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Отчёт не попал в PR | Нет `checks: write` (GitHub) или форк-PR | Добавить permission; для форков — паттерн артефакт + `workflow_run` |
| Пустой JUnit XML | Неверный путь/репортер; тихий провал раннера | Проверить локально путь отчёта; добавить `require_tests` |
| Дублированные тесты в отчёте | Запуск из разных директорий; duplicate test IDs | Использовать уникальные `classname` или `--junit-prefix` |
| Отчёт не обновляется в CI | Кэширование артефактов; старый `history` | Очищать `allure-results`; не использовать кэш для артефактов отчётов |
| Разные цифры локально и в CI | Отличается окружение, версии зависимостей | Использовать одинаковые версии инструментов; кэшировать зависимости |
| Падающие тесты без деталей | Нет вложений (screenshots, logs) | Добавить хук `pytest_runtest_makereport` для `allure.attach` |

## Лучшие практики

### Рекомендации по наполнению отчётов

1.  **Скриншоты и видео:** Прикрепляйте их только для упавших тестов (через хуки `on_failure`), чтобы не перегружать хранилище артефактов. Автоматическое прикрепление скриншота при падении в pytest реализуется через хук `pytest_runtest_makereport` в `conftest.py` (связка Selenium/Playwright + `allure.attach.file`).
2.  **Контекст запросов:** Для API-тестов полезно логировать `Trace-ID` (OpenTelemetry), чтобы можно было мгновенно перейти из отчёта в Jaeger или Grafana Tempo.
3.  **Метаданные:** Добавляйте теги (ID задачи в Jira, компонент, приоритет), чтобы отчёты можно было фильтровать по зонам ответственности.
4.  **История (Trends):** Для Allure тренды строятся из каталога `history`, который необходимо переносить из предыдущего прогона в `allure-results/history` перед генерацией — иначе каждый отчёт будет «островом» без истории. В CI это делается скачиванием предыдущего отчёта из артефактов. Альтернатива — Allure TestOps или ReportPortal, где история автоматически хранится в БД.
5.  **Очистка каталога результатов:** В CI используйте `--clean-alluredir` (pytest) или очищайте `allure-results/` перед прогоном, чтобы избежать смешивания артефактов разных прогонов. Учтите, что это стирает историю — переносите каталог `history` из предыдущего прогона, иначе тренды не построятся.
6.  **Независимость от статуса задания:** Генерацию отчёта запускайте даже при падении тестов (`when: always` в GitLab, `continue-on-error: true` в GitHub Actions), иначе отчёт не соберётся именно тогда, когда он нужен больше всего.

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

### Управление секретами для инструментов отчётности

Self-hosted платформы отчётности (ReportPortal, Allure TestOps) требуют токенов для доступа к API. В CI/CD секреты не должны храниться в репозитории.

| Инструмент | Переменная окружения | Где хранить |
| :--- | :--- | :--- |
| **ReportPortal** | `RP_API_KEY` | CI/CD variables (GitLab) / Secrets (GitHub) |
| **Allure TestOps** | `ALLURE_TOKEN` | CI/CD variables / Secrets |
| **SonarQube** | `SONAR_TOKEN` | CI/CD variables / Secrets |

**Правила:**
- Используйте встроенные хранилища секретов CI/CD (GitLab CI variables, GitHub Secrets).
- Для self-hosted раннеров храните токены в файлах с правами `600` или в HashiCorp Vault.
- Ротация токенов: каждые 90 дней или при утеске.

### Управление данными, резервные копии и мониторинг self-hosted платформ

**Резервное копирование ReportPortal** (источник — официальная документация 26.x): два компонента — PostgreSQL и бинарное хранилище (Docker volume / PVC для Kubernetes).

```bash
# Резервная копия PostgreSQL
DB_CONTAINER=postgres
docker exec -t $DB_CONTAINER pg_dump -U rpuser -d reportportal > reportportal_db_backup.sql

# Резервная копия бинарного хранилища (Docker volume)
VOLUME_NAME=reportportal_storage
docker run --rm -v $VOLUME_NAME:/data -v $(pwd):/backup busybox tar -czvf /backup/reportportal_storage_backup.tar.gz -C /data .
```

**Восстановление:**
```bash
# 1. PostgreSQL должен быть развёрнут как standalone-сервис до запуска ReportPortal
docker exec -i postgres psql -U rpuser -d reportportal < reportportal_db_backup.sql
# 2. Бинарное хранилище
docker run --rm -v $VOLUME_NAME:/data -v $(pwd):/backup busybox tar -xzvf /backup/reportportal_storage_backup.tar.gz -C /data
```

**Мониторинг:** self-hosted ReportPortal мониторится на уровне ОС + приложения:
- Системные метрики: CPU, RAM, сеть, дисковые операции, заполнение диска/хранилищ.
- Per-service: CPU/RAM на каждый сервис, перезапуски, сетевой IO; MinIO (бинарное хранилище), RabbitMQ (брокер сообщений).
- `service-metrics-gatherer` (Docker-образ `reportportal/service-metrics-gatherer`) собирает метрики выполнения из PostgreSQL и Elasticsearch/OpenSearch и автоматически создаёт data source-ы и дашборды в Grafana.
- Стек сбора метрик — Telegraf + InfluxDB + Grafana (дашборды Grafana ID 5955, 3056); для PostgreSQL — PGHero. Мониторинг не размещайте на том же узле, что и сервисы ReportPortal.

**Управление объёмом данных:**
- Бинарное хранилище ReportPortal растёт с количеством вложений (скриншоты, логи, видео) — ограничивайте срок их жизни (`expire_in`/`retention-days` в CI) и периодически очищайте старые запуски через админку.
- Allure Result-файлы (JSON) имеют UUID-управляемые имена — их безопасно объединять (см. Шардирование). Для Allure 3 используйте ограничение истории (`--history-limit`) для ограничения объёма исторических данных.
- Диск PostgreSQL выделяйте отдельно от бинарного хранилища, только SSD.

**Правила:**
- Настраивайте backup для PostgreSQL (ежедневный дамп, retention 30 дней) и бинарного хранилища; периодически проверяйте restore.
- Храните токены доступа в Vault или CI/CD variables, никогда в репозитории.

## Дополнительная информация

### Продвинутая визуализация в Grafana

В 2026 году Grafana стала стандартом для агрегации метрик качества на уровне CTO/Engineering Manager.
*   **Quality Dashboards:** Наложение графиков успешности тестов на графики потребления ресурсов (CPU/RAM) или бизнес-метрик. ReportPortal содержит модуль `service-metrics-gatherer`, который автоматически создаёт data source-ы и дашборды в Grafana для метрик выполнения из собственного хранилища — PostgreSQL и индексов Elasticsearch/OpenSearch.
*   **Data Sources:** Grafana подключается напрямую к хранилищам ReportPortal (PostgreSQL для метаданных, OpenSearch/Elasticsearch для логов) — встроенный PostgreSQL-плагин Grafana позволяет строить произвольные SQL-запросы по данным запусков. Системные метрики инфраструктуры собираются через Telegraf+InfluxDB (см. Мониторинг выше).

### Связанные документы

*   **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — общая стратегия встраивания проверок.
*   **[Виды тестов: Unit, Integration, E2E](./testing_types_unit_integration_e2e.md)** — уровни тестов и их детализация.
*   **[Метрики тестового покрытия](./testing_coverage_metrics.md)** — количественные показатели полноты тестирования.
*   **[Управление нестабильными тестами](../CI-CD/Testing/flaky_test_management.md)** — теория флаков, метрики стабильности, детекция.
*   **[GitHub Actions: Тест-отчёты и надёжность тестов](../Github_CI/Test_Reporting_Reliability.md)** — публикация JUnit в PR, ретраи, карантин.
*   **[Конструктор рабочих процессов GitLab CI/CD](../CI-CD/GitLab_CI/Advanced/gitlab_ci_workflow_builder.md)** — интеграция отчётов о тестах и покрытии.
