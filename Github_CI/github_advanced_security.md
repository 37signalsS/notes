# GitHub Advanced Security: CodeQL, Secret Scanning и Dependency Graph

**Актуально для:** GitHub Advanced Security, октябрь 2026 (CodeQL 2.27.x / Bundle 2.26.4, codeql-action v4.37.9, secret scanning push protection с pattern-configurations API, dependency graph v2, supply chain insights, code scanning API); для GitHub Enterprise Server — версии 3.14+ (функции доступны с задержкой); для public репозиториев на github.com — бесплатно

> **Статус:** GitHub Advanced Security (GAS) — коммерческая подписка GitHub (Enterprise/Enterprise Server). Для **public репозиториев** на github.com основные функции (CodeQL, secret scanning, Dependabot alerts) доступны **бесплатно**; для **private репозиториев** требуется лицензия GAS.

GitHub Advanced Security (GAS) — платёжная надстройка над GitHub Security, объединяющая три независимые, но взаимодополняющие системы сканирования безопасности: **CodeQL** (SAST), **Secret Scanning** (сжатие секретов) и **Dependency Graph + Dependabot** (SCA). GAS работает как слой поверх CI/CD: поиск и исправление уязвимостей происходит на этапе code review и merge, а не только в CI-пайплайне.

## Определения

- **GitHub Advanced Security (GAS)**: Платная функция GitHub, активирующая расширенные возможности security сканирования (CodeQL, secret scanning, dependency graph с push protection). Для public репозиториев на github.com частично доступна бесплатно.
- **CodeQL**: Семантический анализатор кода (SAST) от GitHub. Строит модель управления потоками данных (data flow) для обнаружения уязвимостей (SQLi, XSS, RCE, deserialization, path traversal). Базируется на запросах (queries) к графу кода.
- **Code Scanning**: Интеграция CodeQL в интерфейс GitHub: результаты отображаются в виде alert-ов в коде, PR и вкладке Security. Может работать в CI/CD или по расписанию.
- **Secret Scanning**: Автоматический поиск известных провайдеров секретов (AWS keys, Slack tokens, GitHub PAT и т.д.) в истории репозитория и в реальном времени при push/PR.
- **Push Protection**: Расширенный режим secret scanning, блокирующий push, содержащий секреты (в отличие от обычного режима, который только создает alert).
- **Dependency Graph**: Автоматический парсер зависимостей из lock-файлов и манифестов. Строит граф транзитивных зависимостей и связывает его с базой уязвимостей GitHub Advisory.
- **Dependabot Alerts**: Alert-ы об уязвимых публичных зависимостях, сгенерированные на основе Dependency Graph + GitHub Advisory Database. Могут включать авто-PR с исправлением.
- **Supply Chain Insights**: Расширенный анализ поставок безопасности (SLSA, sigstore attestation verification, dependency review).
- **Security Overview**: Центральная панель безопасности на уровне организации/Enterprise, агрегирующая все alert-ы и метрики.

## Архитектура и модель работы

### Модель анализа CodeQL

CodeQL работает в два этапа: **creation** (строит базу данных кода) и **analysis** (выполняет запросы к базе).

```text
Source Code → CodeQL Database (creation) → CodeQL Queries (analysis) → SARIF results → GitHub Code Scanning Alerts
```

- **CodeQL Database**: снимок кода в виде базы данных с графом отношений (функции, переменные, вызовы, потоки данных).
- **CodeQL Queries**: написаны на языке CodeQL (Datalog-подобный). Стандартные пакеты запросов (`security-and-quality`) содержат сотни проверок. Поддерживаемые языки: C/C++, C#, Go, Java, Kotlin, JavaScript, Python, Ruby, Rust, Swift, TypeScript, GitHub Actions (дополнительные с 2026 года).
- **SARIF**: стандартный формат результатов анализа, который GitHub импортирует в alert-ы.

### Интеграция с CI/CD

CodeQL может работать двумя способами:

1. **GitHub-native (рекомендуется для большинства случаев)**: выполняется в рамках GitHub Actions при каждом push/PR. Триггер: `on: push`, `on: pull_request`, `on: schedule`.
2. **Локально / в другом CI**: CodeQL CLI (`codeql` пакет) выполняет анализ вне GitHub; результаты загружаются через API загрузки SARIF.

### Архитектура Secret Scanning

Secret scanning работает на трёх уровнях:

- **Pattern matching**: регуляонные выражения для известных провайдеров (GitHub, AWS, Google, Slack, Microsoft, Dropbox и др.).
- **Pattern search**: кастомные паттерны для organization-specific секретов.
- **Push protection**: перехватывает push на этапе `pre-receive` hook и блокирует, если найден секрет.

## Практические сценарии

### Сценарий 1: Настройка CodeQL Code Scanning в GitHub Actions

**Предварительные требования**: Включённый GitHub Advanced Security на организации/Enterprise; репозиторий в организации (CodeQL для public репозиториев тоже работает, но без уведомлений в UI для неавторизованных пользователей).

```yaml
# .github/workflows/codeql-analysis.yml
name: "CodeQL"

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 5 * * 1'  # weekly scan, понедельник 05:00 UTC

permissions:
  security-events: write  # для загрузки SARIF
  actions: read
  contents: read

jobs:
  analyze:
    name: Analyze
    runs-on: ubuntu-latest
    if: github.event_name != 'pull_request' || (github.ref == 'refs/heads/main')

    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
        with:
          fetch-depth: 0  # полная история для точной диагностики

- name: Initialize CodeQL
        uses: github/codeql-action/init@v4
        with:
          languages: javascript,python,go  # языки из source code
          # queries: ./custom-queries/     # собственные запросы (опционально)
          # config-file: .github/codeql/codeql-config.yml

      - name: Autobuild
        uses: github/codeql-action/autobuild@v4

      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v4
        with:
          category: "code-scanning"
```

**Конфигурационный файл** `codeql-config.yml` для кастомных запросов:

```yaml
# .github/codeql/codeql-config.yml
name: "Default"
queries:
  - uses: security-and-quality  # стандартные security+quality пакеты
  - uses: security-extended     # дополнительные security пакеты
  - repo: https://github.com/my-org/custom-codeql-queries  # кастомные запросы
# Исключить пути из анализа
paths-ignore:
  - 'node_modules/'
  - 'venv/'
  - 'dist/'
  - 'tests/'
```

- **Валидация**: Во вкладке Security → Code scanning alerts появляются результаты анализа. При обнаружении уязвимости в PR — аннотация в виде code scanning alert с указанием строки и severity.
- **Влияние на CI**: каждый запуск CodeQL добавляет ~5–15 минут к пайплайну (зависит от языка и размера codebase).

### Сценарий 2: Локальный анализ CodeQL CLI

Для self-hosted CI или локальной разработки:

```bash
# 1. Установить CodeQL CLI
curl -L https://github.com/github/codeql-cli-binaries/releases/download/v2.20.1/codeql.zip -o codeql.zip
unzip codeql.zip && export PATH=$PATH:$(pwd)/codeql

# 2. Создать базу данных CodeQL
codeql database create /tmp/codeql-db \
  --language=javascript \
  --command="npm ci" \
  --source-root=.

# 3. Выполнить анализ
codeql database analyze /tmp/codeql-db \
  javascript-security-extended \
  --format=sarifv2 \
  --output=results.sarif

# 4. Загрузить результаты в GitHub
gh api -X POST /repos/{owner}/{repo}/code-scanning/sarif \
  -f ref=main \
  -f sarif='@results.sarif' \
  -H "Accept: application/vnd.github+json"
```

### Сценарий 3: Secret Scanning с Push Protection

**Предварительные требования**: Включённый secret scanning на уровне organization или Enterprise.

```yaml
# .github/workflows/secret-scan.yml
# Автоматический скан по расписанию (дополнительно к push protection)
name: Secret Scan
on:
  schedule:
    - cron: '0 3 * * *'
  push:
    branches: [main]

permissions:
  security-events: write

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0  # история для поиска секретов в прошлом
      # push protection работает автоматически через GitHub
```

Настройка push protection через API (организация):

```bash
# Включить push protection для организации через pattern-configurations API
# Требуется сначала получить pattern_config_version через GET
CONFIG_VERSION=$(gh api -X GET /orgs/<ORG>/secret-scanning/pattern-configurations \
  --jq '.pattern_config_version')

gh api -X PATCH /orgs/<ORG>/secret-scanning/pattern-configurations \
  -f pattern_config_version="$CONFIG_VERSION" \
  -f provider_pattern_settings='[]' \
  -f custom_pattern_settings='[]'

# Включить push protection для конкретного pattern (пример: GITHUB_PERSONAL_ACCESS_TOKEN)
gh api -X PATCH /orgs/<ORG>/secret-scanning/pattern-configurations \
  -f pattern_config_version="$CONFIG_VERSION" \
  -f provider_pattern_settings='[{"token_type":"GITHUB_PERSONAL_ACCESS_TOKEN","push_protection_setting":"enabled"}]'
```

- **Механика**: push protection перехватывает пуш на этапе серверного `pre-receive` hook. Если найден сектор — пуш отклоняется с ошибкой, указывающей на строку и тип секрета.
- **Для форков**: secret scanning работает в upstream-репозитории даже для публичных форков; push protection активен только на protected ветках/тегах.
- **API-детали**: паттерны конфигурируются по отдельности через `provider_pattern_settings` (встроенные провайдеры) и `custom_pattern_settings` (кастомные паттерны); каждому можно задать `push_protection_setting: enabled|disabled|not-set`.

### Сценарий 4: Управление Dependabot Alerts через API

```bash
# Получить все open alert-ы в репозитории
gh api /repos/{owner}/{repo}/dependabot/alerts \
  --jq '.[] | select(.state == "open") | {id: .number, severity: .security_vulnerability.vulnerability.severity, pkg: .dependency.package.name, cve: .security_vulnerability.vulnerability.cve_id}'

# Отметить alert как исправленный (если PR с Dependabot уже смержен)
gh api -X PATCH /repos/{owner}/{repo}/dependabot/alerts/42 \
  -f state=dismissed \
  -f dismiss_reason="fix_started" \
  -f dismissed_comment="Fixed by PR #123"

# Получить сводку alert-ов по организации
gh api /orgs/{org}/dependabot/alerts \
  --jq 'group_by(.severity) | map({severity: .[0].severity, count: length})'
```

### Сценарий 5: Dependency Review в CI

Dependency review показывает diff зависимостей (добавленные/удалённые/изменённые версии) перед merge:

```yaml
jobs:
  dependency-review:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write  # для постановки комментариев в PR
      contents: read
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0  # нужен diff между base и head
      - uses: actions/dependency-review-action@v4
        with:
          fail-on-severity: "critical"  # fail на critical
          allow-licenses: "mit,apache-2.0,bsd-3-clause"
          deny-licenses: "gpl-3.0"
          warn-on-severity: "high"
      - name: Comment PR
        run: |
          # Summary постится как comment в PR
          cat "$GITHUB_STEP_SUMMARY"
```

- **Валидация**: PR с новой зависимостью содержит комментарий с таблицей: Package | Version | CVEs | License. PR падает, если найдена зависимость с GPL-лицензией.

## Команды и API-операции

### CodeQL

CodeQL — семантический анализатор кода (SAST), работающий по методу `creation → analysis → SARIF → Alerts`.

**Поддерживаемые языки (2026):** C/C++, C#, Go, Java, Kotlin, JavaScript, Python, Ruby, Rust, Swift, TypeScript, GitHub Actions.

| Операция | Команда |
|---|---|
| Создать БД | `codeql database create <PATH> --language=<LANG> --command "<BUILD>"` |
| Анализировать БД | `codeql database analyze <PATH> <PACK> --format=sarifv2 --output=out.sarif` |
| Загрузить результаты | `github/codeql-action/upload-sarif@v4` или `gh api -X POST /repos/.../code-scanning/sarif` |
| Список alert-ов | `gh api /repos/{owner}/{repo}/code-scanning/alerts` |
| Dismiss alert | `gh api -X PATCH /repos/{owner}/{repo}/code-scanning/alerts/{alert_number}` |

### Secret Scanning

| Операция | Команда |
|---|---|
| Включить push protection для паттернов | `gh api -X PATCH /orgs/{org}/secret-scanning/pattern-configurations` (с `provider_pattern_settings` и `custom_pattern_settings`) |
| Список alert-ов | `gh api /repos/{owner}/{repo}/secret-scanning/alerts` |
| Dismiss alert | `gh api -X PATCH /repos/{owner}/{repo}/secret-scanning/alerts/{alert_number}` |

### Dependency Graph + Dependabot

| Операция | Команда |
|---|---|
| Список dependabot alert-ов | `gh api /repos/{owner}/{repo}/dependabot/alerts` |
| Получить SBOM | `gh api /repos/{owner}/{repo}/dependency-graph/sbom` |
| Включить dependency graph | `gh api -X PUT /repos/{owner}/{repo}/dependency-graph` (включает dependency graph и Dependabot alerts) или через Settings → Code security and analysis → Dependency graph |

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| CodeQL не анализирует файлы | Язык не указан в `languages` или `paths-ignore` покрывает всё | Добавить язык в список; проверить `codeql-config.yml` |
| `Failed to determine build command` | CodeQL автобилд не смог собрать проект | Указать `--command` в `autobuild` или использовать manual build |
| Alert появляется, но не исчезает после merge | CodeQL анализирует только changed lines в PR | Alert исчезнет после merge + полного скана (push или schedule) |
| Secret scanning не блокирует push | Push protection выключен или настроен только для protected branches | Включить через `PATCH /orgs/{org}/secret-scanning/pattern-configurations`; проверить `push_protection_setting` для каждого pattern |
| Dependency review не работает в fork PR | Нет токена с `pull-requests: write` в fork | Использовать `pull_request_target` (осторожно!) или анализировать в post-merge |
| `dependency-graph` выключен | Dependency Graph отключён в настройках | `gh api -X PUT /repos/{owner}/{repo}/dependency-graph` или Settings → Code security and analysis → Dependency graph |
| CodeQL Action v3 устаревает | CodeQL Action v3 deprecated (декабрь 2026) | Обновить до `github/codeql-action/init@v4` и `analyze@v4` |
| `pattern_config_version` required | API требует версию конфигурации при PATCH | Сначала получить через `GET /orgs/{org}/secret-scanning/pattern-configurations` |

## Лучшие практики

1. **Запускайте CodeQL на push и по расписанию**: push ловит новые уязвимости, weekly scan находит уязвимости в зависимостях и конфигурации, которые изменились.
2. **Используйте `fetch-depth: 0`** для полной истории: CodeQL и secret scanning работают лучше с полным логом коммитов.
3. **Включайте push protection** для production-репозиториев: блокировка реальнее, чем alert-ы.
4. **Автоматизируйте dismiss alert-ов**: при слиянии PR с Dependabot обновлением — автоматически dismiss соответствующие алерты через workflow.
5. **Ограничьте scope языков**: анализ всех языков в monorepo → долгие пайплайны. Используйте `languages: javascript,python` и `paths` для targeted репо.
6. **Custom queries** для business-логики: пишите CodeQL-запросы на поиск уязвимостей, специфичных для вашего стека.
7. **Dependency review в CI + license policy**: fail-on-severity для critical, deny-licenses для GPL и т.д.
8. **Security Overview на org level**: используйте его для аудита покрытия GAS по всем репозиториям организации.

## Дополнительная информация

- **[Dependency Automation](./dependabot.md)** — управление Dependabot alerts, обновления и auto-merge.
- **[Управление секретами](./secrets_management.md)** — иерархия токенов, OIDC, fine-grained PAT.
- **[Сетевая безопасность](./network-security.md)** — Harden-Runner для мониторинга трафика экшенов.
- **[Безопасность цепочки поставок](../Security/Supply_Chain_Security/overview.md)** — SLSA, Sigstore, SBOM, dependency confusion.
- **Официальная документация**: [GitHub Advanced Security](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/security-and-analysis/about-github-advanced-security), [CodeQL](https://codeql.github.com/docs/), [Secret Scanning](https://docs.github.com/en/code-security/secret-scanning).
