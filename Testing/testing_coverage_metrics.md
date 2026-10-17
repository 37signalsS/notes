# Метрики тестового покрытия

**Актуально для:** Python 3.12 / coverage.py 7.16.x, pytest-cov 7.x, Go 1.22+, Java 17+/JUnit 5, JavaScript/Node 20+ (Vitest/Jest/C8), C#/dotnet 10+ (coverlet), StrykerJS 10.x, Stryker.NET 5.x, PIT 1.19.x, diff-cover 10.6.x, mutmut 3.8.x, bashcov (gem), kcov

## 1. Определения

**Тестовое покрытие (Code Coverage)** — количественная метрика, отображающая долю исполняемого кода (строк, ветвлений, функций), затронутую при выполнении автоматизированных тестов.

**Дифф-покрытие (Diff-Coverage / Delta Coverage)** — метрика, измеряющая процент покрытия только для тех строк кода, которые были изменены или добавлены в текущем Merge Request (MR). Это стандарт индустрии 2025–2026 годов для работы в условиях накопленного технического долга.

**Мутационное покрытие (Mutation Score)** — показатель качества тестов, определяющий их способность обнаруживать искусственно внесенные изменения (мутации) в логику программы. Инструменты: mutmut, cosmic-ray (Python), Stryker Mutator (JS/TS), PIT (Java), Stryker.NET (C#).

**Операционное покрытие (Operational Coverage)** — метрика, характеризующая долю конфигурационного и операционного кода (скриптов, unit-файлов systemd, правил мониторинга, IaC), покрытого тестами. Для DevOps/SRE/sysadmin критически важна: непротестированный operational code приводит к сбоям в эксплуатации.

**Hardening** — процесс улучшения устойчивости и надёжности на основе анализа покрытия и результатов тестов.

## 2. Основные концепции

### Виды метрик покрытия

Покрытие измеряется на разных уровнях гранулярности:

| Метрика | Что измеряет | Сценарий использования |
| :--- | :--- | :--- |
| **Строк (Line)** | Доля исполненных строк кода. | Базовая оценка, часто вводит в заблуждение при сложной логике. |
| **Ветвей (Branch)** | Прохождение всех путей `if/else`, `switch/case`. | Обязательно для бизнес-логики и обработки ошибок. |
| **Путей (Path)** | Все возможные комбинации ветвлений в функции. | Критически важные модули (например, финансовые расчеты). |
| **Мутационное** | Процент "убитых" мутантов. | Оценка реальной эффективности ассертов (проверок) в тестах. |
| **Функций (Function)** | Доля вызванных функций/методов. | Быстрый overview для больших codebase; не заменяет Branch. |

### Покрытие против качества

Высокое покрытие (например, 100%) не гарантирует отсутствия багов. Оно показывает лишь то, что код был **выполнен**, но не обязательно **проверен**.

*   **Пример:** Тест может вызвать функцию, но не проверить результат её работы (assertion-free testing). В этом случае покрытие будет 100%, но ценность теста — 0%.
*   **Решение:** Сочетание Branch Coverage с Mutation Testing.

### Как работает Diff-Coverage

Механизм работы diff-cover:

1.  **Сбор изменений:** `diff-cover` вызывает `git diff` для вычисления изменённых строк относительно базовой ветки (по умолчанию `origin/main`). Диапазон `...` (по умолчанию) означает «изменения с момента расхождения веток», а `..` — «все различия между ветками».
2.  **Сопоставление с отчётом покрытия:** XML-отчёт покрытия (Cobertura, JaCoCo, LCov, Clover) сопоставляется с изменёнными строками по пути к файлу.
3.  **Подсчёт:** для каждой изменённой строки проверяется, была ли она помечена как покрытая (hit count > 0) в отчёте покрытия.
4.  **Результат:** процент покрытых изменённых строк. `diff-cover` требует Cobertura, Clover, JaCoCo XML или LCov форматы.

**Важно:** пути к файлам в XML-отчёте и в `git diff` должны совпадать (относительные пути). Для JaCoCo дополнительно указываются `--src-roots`.

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
      - uses: actions/checkout@v7
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
        uses: actions/upload-artifact@v7
        with:
          name: coverage-report
          path: coverage.xml
          retention-days: 14
      - name: Enforce minimum coverage
        run: |
          COVERAGE=$(coverage report --format=total)
          echo "Total coverage: ${COVERAGE}%"
          if [ "$COVERAGE" -lt 80 ]; then
            echo "Coverage below threshold: ${COVERAGE}% < 80%"
            exit 1
          fi
```

### Управление секретами для инструментов покрытия

Инструменты покрытия (SonarQube, Codecov, Coveralls) требуют токенов для отправки отчётов и декодирования дельты. В CI/CD секреты не должны храниться в репозитории.

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

Вместо того чтобы требовать 80% покрытия от всего проекта с 10-летним Legacy-кодом, команды устанавливают порог **100% Diff-Coverage**. Это гарантирует, что каждый новый коммит делает систему надёжнее.

**Пример запуска diff-cover:**

```bash
# Установка
pip install diff-cover

# Генерация отчёта покрытия
pytest --cov=app --cov-branch --cov-report=xml:coverage.xml

# Проверка покрытия только изменённых строк (относительно main)
diff-cover coverage.xml --compare-branch=origin/main --fail-under=100
```

**Дополнительные опции diff-cover (v10.6.0):**
- `--total-percent-float` — сохраняет дробную часть (не округляет до целого)
- `--show-uncovered` — выводит конкретные строки без покрытия в консоль
- `--format html:report.html` / `--format json:report.json` / `--format markdown:report.md` — форматы отчёта
- `--exclude setup.py` / `--include "src/**"` — фильтрация путей

**Инструменты для Diff-analysis:**
*   **diff-cover** (Python/Generic) — `pip install diff-cover`, работает с Cobertura/JaCoCo/LCov/Clover XML
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
- Используйте `coverage combine` для агрегации файлов `.coverage.*` из xdist шардов.
- Для matrix builds собирайте артефакты покрытия из каждой джобы и объединяйте в `post`-джобе.
- При использовании `pytest-shard` каждый shard должен сохранять свой отчёт с уникальным именем.

### Пороги покрытия по окружениям

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
  diff-cover coverage.xml --compare-branch=origin/main --fail-under=100
else
  pytest --cov=app --cov-fail-under=$THRESHOLD
fi
```

### Операционное покрытие (DevOps / SRE / Sysadmin)

Помимо прикладного кода, покрытие должно распространяться на operational artifacts — скрипты, unit-файлы systemd, правила мониторинга, IaC. Непротестированный operational code — основная причина сбоев в эксплуатации.

#### Покрытие shell-скриптов (bash/sh)

Operational скрипты (deploy, backup, maintenance, log rotation) часто не покрываются тестами из-за сложности инструментарии.

**bashcov** — Ruby-инструмент для измерения покрытия Bash-скриптов. Использует SimpleCov, поддерживает shUnit2, Bats, bash_unit как test runners:

```bash
# Установка
gem install bashcov

# Покрытие скрипта
bashcov ./scripts/deploy.sh

# Покрытие тестового набора shUnit2
bashcov -- ./run_tests.sh test_deploy.sh

# → ./coverage/index.html
```

**kcov** — кросс-платформенный coverage-инструмент для compiled programs, Python и Bash без специальной компиляции:

```bash
# Установка (Ubuntu/Debian)
apt-get install -y kcov

# Покрытие bash-скрипта
kcov --bash ./scripts/backup.sh

# Покрытие Python-скрипта
kcov --include-path=src ./venv/bin/python -m pytest tests/
```

**bats** (Bash Automated Testing System) — фреймворк для тестирования bash-скриптов. Покрытие измеряется через `kcov`:

```bash
# Установка bats
git clone https://github.com/bats-core/bats-core.git && cd bats-core && sudo ./install.sh /usr/local

# Покрытие через kcov
kcov --bash --include-path=./scripts ./scripts/deploy.sh tests/

# → /tmp/bats-*/index.html
```

#### Покрытие правил мониторинга и алертинга

Prometheus Recording Rules и Alert Rules, а также правила Alertmanager — это конфигурационный код, который должен быть покрыт тестами. Ошибка в алерте = промежуточный сбой.

**promtool check rules** и **promtool test rules** — валидация синтаксиса и логическое тестирование правил:

```bash
# Валидация синтаксиса
promtool check rules monitoring/rules/*.yml

# Юнит-тесты правил
promtool test rules monitoring/tests/alert_test.yaml
```

```yaml
# monitoring/tests/alert_test.yaml
rule_files:
  - alerts.yml

tests:
  - interval: 1m
    input_series:
      - series: 'up{job="app"}'
        values: '0 0 0 0 0'
    alert_rule_test:
      - alertname: AppDown
        eval_time: 1m
        exp_alerts:
          - labels:
              severity: page
```

#### Покрытие systemd unit-ов

systemd unit-файлы описывают сервисы, таймеры, пути. Их можно тестировать через `systemd-analyze verify`:

```bash
# Проверка синтаксиса и логики unit-файлов
systemd-analyze verify /etc/systemd/system/myapp.service /etc/systemd/system/myapp.timer

# Тестовый прогоны в контейнере или на отдельном хосте
systemd-run --unit=test-service --scope /path/to/test/script.sh
```

#### Покрытие IaC (Infrastructure as Code)

Покрытие не относится только к прикладному коду. Инструменты IaC также поддерживают покрытие:

| Инструмент | Покрытие |
| :--- | :--- |
| **Ansible** | `ansible-test coverage` (встроено) |
| **Terraform** | `terraform plan` coverage через terratest |
| **Puppet** | `puppetlabs_spec_helper` + coverage |

**Ansible:**
```bash
# Измерение покрытия тестов ролей
ansible-test coverage erase
ansible-test coverage run pytest -v tests/
ansible-test coverage report
ansible-test coverage html  # → htmlcov/index.html
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

## 4. Операции и команды

### Основные команды покрытия по языкам

| Язык | Базовое покрытие | Мутационное тестирование |
| :--- | :--- | :--- |
| **Python** | coverage.py / pytest-cov | mutmut 3.8.x, cosmic-ray 8.7.x |
| **Java / Kotlin** | JaCoCo | PIT 1.19.x |
| **JS / TS** | C8, Istanbul | StrykerJS 10.x |
| **Go** | `go test -cover` / go-cover | (встроено частично) |
| **C# / .NET** | coverlet | Stryker.NET 5.x (`--targetframework net10.0`) |
| **Bash** | bashcov, kcov | (нет) |

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

### Команды diff-cover

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `coverage xml -o coverage.xml` | Генерация Cobertura XML | `pytest --cov=app --cov-report=xml` |
| `diff-cover coverage.xml` | Diff-покрытие vs origin/main | `diff-cover coverage.xml --fail-under=100` |
| `diff-cover --compare-branch=origin/develop` | Сравнение с другой веткой | `diff-cover coverage.xml --compare-branch=origin/develop` |
| `diff-cover --total-percent-float` | Точность до 2 знаков | `diff-cover coverage.xml --total-percent-float` |
| `diff-cover --show-uncovered` | Показать нетронутые строки | `diff-cover coverage.xml --show-uncovered` |
| `diff-cover --format json:report.json` | JSON-отчёт | `diff-cover coverage.xml --format json:report.json` |
| `coverage combine` | Объединение shard-отчётов | `coverage combine .coverage.* && coverage xml` |

### Покрытие в монорепозиториях

При нескольких сервисах в одном репозитории:
- Запускайте тесты и собирайте покрытие **отдельно для каждого сервиса**.
- Используйте пути исключения, чтобы не смешивать покрытие между сервисами.
- Настраивайте порог покрытия на уровне сервиса, а не всего монорепо.

**Пример (Nx/Turborepo монорепо):**
```bash
nx test myapp --code-coverage --code-coverage-exclude="**/e2e/**"
```

## 5. Устранение неполноты покрытия и типичные ошибки

### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Покрытие 100%, но тесты падают в проде | Отсутствие assertion или weak assert | Добавить проверки результата; включить mutation testing |
| Низкое покрытие legacy-кода | Большой объём не протестированного кода | Использовать Diff-Coverage 100% вместо общего порога |
| Покрытие падает после рефакторинга | Удалены тесты вместе с кодом | Добавить тест на поведение, а не на реализацию |
| Неверные цифры в CI | Покрытие считается только для unit-тестов | Включить integration-тесты в отчёт покрытия |
| Разные цифры локально и в CI | Отличается окружение, версии зависимостей | Использовать одинаковые версии инструментов; кэшировать зависимости |
| `coverage report --format=total` выводит пусто | Файл `.coverage` не найден или пути не совпадают | Проверить `coverage run` перед `coverage report`; указать `--data-file` |
| diff-cover: "No lines with coverage information" | Пути в XML и git diff не совпадают | Запустить diff-cover из корня проекта; проверить `source` в `.coveragerc` |
| Mutmut hangs на fork | Тестовый setup не fork-safe (gevent, grpc, torch) | `process_isolation = "forkserver"` в `[tool.mutmut]` |

### Диагностика покрытия для operational code (SRE/DevOps)

**1. Обнаружение непокрытых operational скриптов:**

```bash
# Поиск bash-скриптов без покрытия
find . -name "*.sh" -type f -exec grep -L "pragma: no cover\|bashcov\|bats" {} \;

# Проверка: все ли скрипты в CI имеют тесты
diff <(find scripts/ -name "*.sh" | sort) <(find tests/ -name "test_*.sh" | sort)
```

**2. Валидация алерт-правил в CI (SRE):**

```bash
# pre-commit hook или отдельный job
#!/bin/bash
set -euo pipefail
# 1. Синтаксис
promtool check rules monitoring/rules/*.yml || exit 1
# 2. Тесты алертов
promtool test rules monitoring/tests/*.yaml || exit 1
# 3. Проверка: нет ли алертов без описания (runbook_url)
if grep -l "alert:" monitoring/rules/*.yml | xargs grep -L "runbook_url:" 2>/dev/null; then
  echo "FAIL: алерт без runbook_url" && exit 1
fi
```

**3. Проверка systemd unit-ов (Sysadmin):**

```bash
# В CI или на staging
systemd-analyze verify /etc/systemd/system/*.service || exit 1

# Проверка: unit включен
systemctl is-enabled myapp.service || echo "WARN: service not enabled"
```

## 6. Рекомендации и hardening

### Рекомендации по покрытию

*   **Исключайте шум:** Удаляйте из отчетов автогенерированный код, DTO, миграции БД и конфигурационные файлы.
*   **Branch over Line:** Всегда отдавайте приоритет Branch Coverage.
*   **Mutation Testing в CI:** Запускайте мутационные тесты только для измененного кода (incremental mutation testing), так как полный прогон слишком ресурсозатратен.
*   **Инкрементальные отчёты:** Для крупных проектов генерируйте HTML-отчёт только для изменённых модулей, а не всего проекта.
*   **Верификация артефактов:** Проверяйте, что артефакт покрытия загружен и не пуст. В GitLab используйте `coverage_report`, в GitHub — `actions/upload-artifact` + проверку размера.
*   **Отделение интеграционного покрытия:** Unit-тесты дают быстрое покрытие; интеграционные — медленное, но более ценное. Документируйте вклад каждого уровня.

### Пороги покрытия по типам кода

| Тип кода | Рекомендуемый порог | Обоснование |
| :--- | :--- | :--- |
| **Бизнес-логика (unit)** | Branch 80%+, Mutation Score 70%+ | Критична для корректности |
| **Infrastructure code (IaC)** | 100% (diff) | Ошибка в IaC = проблемы во всех окружениях |
| **Operational scripts (bash/systemd)** | 80%+ (critical path) | Сбой скрипта = downtime |
| **Alerting/мониторинг** | 100% (синтаксис + тесты алертов) | Ложные алерты = налет on-call |
| **Auto-generated code** | Исключить (`# pragma: no cover`) | Нет смысла тестировать генератор |

### Observability-Driven Coverage

В 2026 году активно внедряется практика сопоставления тестового покрытия с **Production Usage**:
1. Сбор данных о том, какие строки кода вызываются реальными пользователями (через runtime profiling, eBPF).
2. Наложение этих данных на карту тестового покрытия.
3. **Результат:** Приоритетное написание тестов для "горячих" участков кода, которые активно используются в рантайме, но не покрыты тестами.

**Важно:** Данный подход не заменяет unit-тесты, а дополняет их. Цель — выявить "слепые зоны" в критически важном коде, который уже работает в проде, но не имеет fallback-сценариев при сбоях.

### Бейджи покрытия в README

Для быстрого визуального контроля качества добавьте бейдж покрытия в README проекта:

```markdown
![Coverage](https://img.shields.io/codecov/cgh/main)
```

**Правила:**
- Используйте отдельный бейдж для каждой ветки (main, develop), чтобы не показывать заниженные цифры feature-веток.
- При отказе от SaaS-сервисов генерируйте бейдж самостоятельно: экспортируйте покрытие в JSON, загрузите в объектное хранилище и обновите ссылку.

## 7. Связь с Test Impact Analysis (TIA)

Данные о покрытии используются для оптимизации пайплайнов. Зная, какие тесты покрывают конкретные файлы, система может запускать только те тесты, которые затронуты изменениями. Это сокращает время выполнения CI на 40-70%.

---

**См. также**

*   **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — встраивание ворот качества.
*   **[Инструменты отчётности](./testing_reporting_tools.md)** — визуализация результатов.
*   **[Виды тестов: Unit, Integration, E2E](./testing_types_unit_integration_e2e.md)** — уровни и стратегии.
*   **[DORA метрики](../CI-CD/Core_Concepts/dora_metrics.md)** — влияние качества на скорость поставки.
*   **[TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md)** — мутационное тестирование и принципы написания тестов.
*   **[Инфраструктурное тестирование](./infrastructure_testing.md)** — покрытие IaC и конфигурации хостов.
