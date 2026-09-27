# Метрики тестового покрытия

## 1. Определения

**Тестовое покрытие (Code Coverage)** — количественная метрика, отображающая долю исполняемого кода (строк, ветвлений, функций), затронутую при выполнении автоматизированных тестов.

**Дифф-покрытие (Diff-Coverage / Delta Coverage)** — метрика, измеряющая процент покрытия только для тех строк кода, которые были изменены или добавлены в текущем Merge Request (MR). Это стандарт индустрии 2025–2026 годов для работы в условиях накопленного технического долга.

**Мутационное покрытие (Mutation Score)** — показатель качества тестов, определяющий их способность обнаруживать искусственно внесенные изменения (мутации) в логику программы. Практическая часть (mutmut, Stryker, интеграция с gitlab-mutants) подробно описана в [TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md#мутационное-тестирование-mutation-testing).

## 2. Основные концепции

### Виды метрик покрытия

Покрытие измеряется на разных уровнях гранулярности:

| Метрика | Что измеряет | Сценарий использования |
| :--- | :--- | :--- |
| **Строк (Line)** | Доля исполненных строк кода. | Базовая оценка, часто вводит в заблуждение при сложной логике. |
| **Ветвей (Branch)** | Прохождение всех путей `if/else`, `switch/case`. | Обязательно для бизнес-логики и обработки ошибок. |
| **Путей (Path)** | Все возможные комбинации ветвлений в функции. | Критически важные модули (например, финансовые расчеты). |
| **Мутационное** | Процент "убитых" мутантов. | Оценка реальной эффективности ассертов (проверок) в тестах. |

### Покрытие против качества

Высокое покрытие (например, 100%) не гарантирует отсутствия багов. Оно показывает лишь то, что код был **выполнен**, но не обязательно **проверен**.
*   **Пример:** Тест может вызвать функцию, но не проверить результат её работы (assertion-free testing). В этом случае покрытие будет 100%, но ценность теста — 0%.
*   **Решение:** Сочетание Branch Coverage с Mutation Testing.

## 3. Практические сценарии

### Настройка порога покрытия в CI/CD (GitLab CI)

Современные пайплайны блокируют слияние кода, если порог покрытия (особенно Diff-Coverage) не достигнут.

```yaml
# .gitlab-ci.yml
test:coverage:
  stage: test
  script:
    - pytest --cov=app --cov-branch --cov-report=xml:coverage.xml --cov-fail-under=80
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

### Настройка порога покрытия в CI/CD (GitHub Actions)

В GitHub Actions порог проверяется либо через встроенный `coverage` в `run`, либо через Quality Gate внешнего сервиса (SonarQube, Codecov). Для самостоятельного контроля без SaaS используйте `coveragepy` + `junit` артефакт + approval rule на основе отчёта.

```yaml
# .github/workflows/coverage.yml
name: Coverage
on:
  pull_request:
  push:
    branches: [main]

jobs:
  coverage:
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
          pip install pytest pytest-cov
      - name: Run tests with coverage
        run: |
          pytest --cov=app --cov-branch --cov-report=xml:coverage.xml --cov-report=term-missing
      - name: Upload coverage artifact
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: coverage.xml
          retention-days: 14
      - name: Enforce minimum coverage
        run: |
          COVERAGE=$(coverage report --format=total | tail -1)
          echo "Total coverage: $COVERAGE%"
          if [ "$COVERAGE" -lt 80 ]; then
            echo "Coverage below threshold: $COVERAGE% < 80%"
            exit 1
          fi
```

### Управление секретами для инструментов покрытия

Инструменты покрытия (SonarQube, Codecov, Coveralls) требуют токены для отправки отчётов и декодирования дельты. В CI/CD секреты не должны храниться в репозитории.

| Инструмент | Переменная окружения | Где хранить |
| :--- | :--- | :--- |
| **SonarQube** | `SONAR_TOKEN` | CI/CD variables (GitLab) / Secrets (GitHub) |
| **Codecov** | `CODECOV_TOKEN` | CI/CD variables / Secrets |
| **Coveralls** | `COVERALLS_REPO_TOKEN` | CI/CD variables / Secrets |
| **diff-cover** | нет (локальный) | не требуется |

**Правила:**
- Используйте встроенные хранилища секретов CI/CD (GitLab CI variables, GitHub Secrets).
- Для self-hosted раннеров храните токены в файлах с правами `600` или в HashiCorp Vault.
- Ротация токенов: каждые 90 дней или при утечке.

### Практическое использование Дифф-покрытия

Вместо того чтобы требовать 80% покрытия от всего проекта с 10-летним Legacy-кодом, команды устанавливают порог **100% Diff-Coverage**. Это гарантирует, что каждый новый коммит делает систему надежнее.

**Пример запуска diff-cover:**

```bash
# Установка
pip install diff-cover

# Генерация отчёта покрытия
pytest --cov=app --cov-branch --cov-report=xml:coverage.xml

# Проверка покрытия только изменённых строк (относительно main)
diff-cover coverage.xml --compare-branch=origin/main --fail-under=100
```

**Инструменты для Diff-analysis:**
*   **diff-cover** (Python/Generic)
*   **[SonarQube](../CI-CD/Tools/sonarqube.md)** (автоматический анализ в PR)
*   **Codecov** (визуализация дельты в интерфейсе GitHub/GitLab)

### Шардирование тестов и покрытие

При запуске тестов в нескольких параллельных джобах (matrix builds, pytest-xdist) каждая джоба генерирует свой отчёт покрытия. Без сбора вместе вы получите заниженные цифры.

**Сбор покрытия из параллельных джобов:**

```bash
# В каждой джобе: объединение покрытия в общий файл
coverage combine --append .coverage.*
coverage xml -o coverage-combined.xml
```

**Правила:**
- Используйте `coverage combine` для агрегации файлов `.coverage.*` из xdist шards.
- Для matrix builds собирайте артефакты покрытия из каждой джобы и объединяйте в `post`-джобе.
- При использовании `pytest-shard` каждый shard должен сохранять свой отчёт с уникальным именем.

## 4. Дополнительная информация

### Инструментарий по языкам (2025–2026)

| Язык | Базовое покрытие | Мутационное тестирование |
| :--- | :--- | :--- |
| **Python** | coverage.py / pytest-cov | mutmut, cosmic-ray |
| **Java / Kotlin** | JaCoCo | PITest |
| **JS / TS** | C8, Istanbul | Stryker Mutator |
| **Go** | go test -cover | (встроено частично) |
| **C# / .NET** | coverlet | Stryker.NET |

### Форматы отчётов покрытия

Разные инструменты и сервисы требуют разные форматы для импорта данных:

| Формат | Использование | Генерация |
| :--- | :--- | :--- |
| **Cobertura (XML)** | GitLab, Jenkins, SonarQube | `coverage xml`, `pytest --cov-report=xml` |
| **JaCoCo (XML)** | Maven/Gradle проекты, SonarQube | плагин JaCoCo |
| **lcov (info)** | Codecov, Coveralls | `coverage lcov` |
| **HTML** | Локальный просмотр | `coverage html` |
| **JSON** | Программная обработка | `coverage json` |

**Рекомендация:** храните в репозитории инструкцию по генерации отчёта в нужном формате. Для CI/CD достаточно Cobertura или lcov.

### Покрытие в монорепозиториях

При нескольких сервисах в одном репозитории:
- Запускайте тесты и собирайте покрытие **отдельно для каждого сервиса**.
- Используйте пути исключения, чтобы не смешивать покрытие между сервисами.
- Настраивайте порог покрытия на уровне сервиса, а не всего монорепо.

**Пример (Nx/Turborepo монорепо):**
```bash
# Запуск тестов и покрытия для конкретного приложения
nx test myapp --code-coverage --code-coverage-exclude="**/e2e/**"
```

### Покрытие кода инфраструктуры

Покрытие не относится только к прикладному коду. Инструменты IaC также поддерживают coverage:

| Инструмент | Покрытие |
| :--- | :--- |
| **Terraform** | `terraform plan` coverage через terratest |
| **Ansible** | `ansible-test coverage` (встроено) |
| **Puppet** | `puppetlabs_spec_helper` + coverage |

### Связь с Test Impact Analysis (TIA)

Данные о покрытии используются для оптимизации пайплайнов. Зная, какие тесты покрывают конкретные файлы, система может запускать только те тесты, которые затронуты изменениями. Это сокращает время выполнения CI на 40-70%.

### Бейджи покрытия в README

Для быстрого визуального контроля качества добавьте бейдж покрытия в README проекта:

```markdown
![Coverage](https://img.shields.io/codecov/cgh/main)
```

**Правила:**
- Используйте отдельный бейдж для каждой ветки (main, develop), чтобы не показывать заниженные цифры feature-веток.
- При отказе от SaaS-сервисов генерируйте бейдж самостоятельно: экспортируйте покрытие в JSON, загрузите в объектное хранилище и обновите ссылку.

### Стратегия порогов по окружениям

Порог покрытия не должен быть одинаковым для всех веток:

| Окружение | Рекомендуемый порог | Комментарий |
| :--- | :--- | :--- |
| **main / master** | 80–90% | Высокий порог, блокирует деградацию |
| **develop / trunk** | 70–80% | Баланс между скоростью и качеством |
| **feature / MR** | 100% Diff-Coverage | Гарантирует, что новый код тестируется |

**Реализация в CI:**
```bash
# Определение ветки
BRANCH=${CI_COMMIT_REF_NAME:-${GITHUB_REF_NAME}}

# Порог по умолчанию
THRESHOLD=80

# Для MR/feature веток — 100% Diff-Coverage
if [[ "$BRANCH" != "main" && "$BRANCH" != "develop" ]]; then
  THRESHOLD=100
  diff-cover coverage.xml --compare-branch=origin/main --fail-under=$THRESHOLD
else
  pytest --cov=app --cov-fail-under=$THRESHOLD
fi
```

### Исключение файлов из покрытия

Автогенерированный код, миграции БД и конфигурационные файлы занижают общее покрытие без ущерба для качества. Исключайте их через конфигурацию.

**coverage.py (Python):**
```ini
# .coveragerc
[run]
omit =
    */migrations/*
    */tests/*
    */venv/*
    */__pycache__/*
    */generated/*

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise NotImplementedError
```

**JaCoCo (Java/Maven/Gradle):**
```xml
<!-- pom.xml -->
<configuration>
  <excludes>
    <exclude>**/*Generated.*</exclude>
    <exclude>**/dto/**</exclude>
  </excludes>
</configuration>
```

### Сравнение покрытия между ветками

Для оценки влияния MR на покрытие сравнивайте дельту с базовой веткой:

```bash
# GitLab: встроенная дельта в MR-widget
# GitHub: через Codecov или ручной скрипт

# Ручной расчёт дельты
python -c "
import json, subprocess
# Получить список изменённых файлов
changed = subprocess.check_output(['git', 'diff', '--name-only', 'origin/main...HEAD']).decode().split()
print('Changed files:', changed)
# Для каждого файла вывести покрытие из отчёта
"
```

### Устранение неполноты покрытия

**Типичные проблемы:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Покрытие 100%, но тесты падают в проде | Отсутствие assertion или weak assert | Добавить проверки результата; включить mutation testing |
| Низкое покрытие legacy-кода | Большой объём не протестированного кода | Использовать Diff-Coverage 100% вместо общего порога |
| Покрытие падает после рефакторинга | Удалены тесты вместе с кодом | Добавить тест на поведение, а не на реализацию |
| Неверные цифра в CI | Покрытие считается только для unit-тестов | Включить integration-тесты в отчёт покрытия |
| Разные цифры локально и в CI | Отличается окружение, версии зависимостей | Использовать одинаковые версии инструментов; кэшировать зависимости |

### Рекомендации по Hardening

*   **Исключайте шум:** Удаляйте из отчетов автогенерированный код, DTO, миграции БД и конфигурационные файлы.
*   **Branch over Line:** Всегда отдавайте приоритет Branch Coverage.
*   **Mutation Testing в CI:** Запускайте мутационные тесты только для измененного кода (incremental mutation testing), так как полный прогон слишком ресурсозатратен.
*   **Инкрементальные отчёты:** Для крупных проектов генерируйте HTML-отчёт только для изменённых модулей, а не всего проекта.
*   **Верификация артефактов:** Проверяйте, что артефакт покрытия загружен и не пуст. В GitLab используйте `coverage_report`, в GitHub — `actions/upload-artifact` + проверку размера.
*   **Отделение интеграционного покрытия:** Unit-тесты дают быстрое покрытие; интеграционные — медленное, но более ценное. Документируйте вклад каждого уровня.

### Observability-Driven Coverage

В 2026 году активно внедряется практика сопоставления тестового покрытия с **Production Usage**:
1. Сбор данных о том, какие строки кода вызываются реальными пользователями (через OpenTelemetry/ebpf).
2. Наложение этих данных на карту тестового покрытия.
3. **Результат:** Приоритетное написание тестов для "горячих" участков кода, которые активно используются в рантайме, но не покрыты тестами.

**Важно:** Данный подход не заменяет unit-тесты, а дополняет их. Цель — выявить "слепые зоны" в критически важном коде, который уже работает в проде, но не имеет fallback-сценариев при сбоях.

---
**См. также**

*   **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — встраивание ворот качества.
*   **[Инструменты отчётности](./testing_reporting_tools.md)** — визуализация результатов.
*   **[Виды тестов: Unit, Integration, E2E](./testing_types_unit_integration_e2e.md)** — уровни и стратегии.
*   **[DORA метрики](../CI-CD/Core_Concepts/dora_metrics.md)** — влияние качества на скорость поставки.
