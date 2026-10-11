# GitHub Dependabot: Автоматизация обновлений и Dependabot Alerts

**Актуально для:** Dependabot, октябрь 2026 (dependabot.yml v2, auto-merge v2, security updates с группировкой, GitHub Actions ecosystem updates, Dependabot alerts API v3); для GitHub Enterprise Server — 3.14+

Dependabot — встроенный в GitHub механизк автоматических обновлений зависимостей. Он сканирует зависимости репозитория, открывает Pull Request с обновлениями (как security patches, так и версионные апдейты) и создаёт alert-ы об уязвимых публичных пакетах. В отличие от Renovate (см. [Автоматизацию обновлений зависимостей](../CI-CD/dependency_automation.md)), Dependabot полностью управляется GitHub и не требует self-hosted развёртывания.

## Определения

- **Dependabot**: Встроенный в GitHub бот автоматических обновлений зависимостей. Управляется файлом конфигурации `.github/dependabot.yml`.
- **Security Updates**: Автоматические PR, которые обновляют уязвимую зависимость до **безопасной версии** (не той, что новее, а минимум патч-версии с CVE-исправлением). Открываются только при наличии Dependabot alert.
- **Version Updates**: Автоматические PR на обновление зависимостей до **новейшей версии** в рамках диапазона (patch, minor, major). Работают по расписанию.
- **Dependabot Alerts**: Alert-ы об уязвимых публичных зависимостях, сгенерированные на основе Dependency Graph + GitHub Advisory Database. Отображаются во вкладке Security → Dependabot alerts.
- **Dependency Graph**: Автоматически строит граф зависимостей репозитория (из lock-файлов и манифестов) и сопоставляет с advisory-базой GitHub.
- **`package-ecosystem`**: Тип экосистемы, которую обновляет Dependabot (`npm`, `pip`, `gomod`, `composer`, `docker`, `github-actions`, `nuget`, `maven`, `cargo`, `swift`, `terraform`, `devcontainer`).
- **`directory`**: Путь к директории с манифестом (обычно `/`).
- **`group` (v2)**: Группировка нескольких обновлений в один PR (все patch-обновления одной экосистемы за один PR).
- **Auto-merge**: Автоматическое слияние Dependabot PR после успешного CI. Требует, чтобы CI проверял `Dependabot` как достоверного актора.

## Архитектура и модель работы

### Dependency Graph → Dependabot Alerts → Auto-PR

```text
Source Code → Dependency Graph (парсер манифестов) → Advisory DB (GitHub Security) → Dependabot Alert
                                                    ↘
                                              Auto-PR (security update)
                                                    ↘
                                              Auto-PR (version update, по расписанию)
```

- **Dependency Graph** активируется автоматически при первом Dependabot alert или можно включить вручную: Settings → Code security and analysis → Dependency graph.
- **Advisory DB** — GitHub поддерживает собственную базу (GitHub Advisory Database) + интеграцию с OSV, npm advisory, PyPA, Ruby advisory и др.
- **Security Updates** создаются только при наличии alert и только если можно найти безопасную версию (не для major-апдейтов, которые ломают API).

### Security Updates vs Version Updates

| Аспект | Security Updates | Version Updates |
|---|---|---|
| **Источник триггера** | Dependabot Alert (CVE) | Расписание (`schedule`) |
| **Целевая версия** | Минимум с CVE-фиксом | Новейшая доступная |
| **Диапазон** | Только patch/minor (не major) | Любой (`patch`, `minor`, `major`) |
| **Auto-merge** | Рекомендуется | Осторожно (major — ручной ревью) |
| **Включение** | Автоматически, если alert есть | Через `dependabot.yml` |

## Практические сценарии

### Предварительные требования

- **Включён Dependency Graph** (Settings → Code security and analysis → Dependency graph) — Dependabot опирается на него для построения графа и сопоставления с advisory-базой.
- **Доступ Dependabot к репозиторию**: Dependabot — встроенный бот, активируется автоматически. Для private репозиториев нужна лицензия GitHub Advanced Security или Dependabot (входит в Enterprise).
- **Разрешения для auto-merge**: в репозитории/организации должен быть включён auto-merge (Settings → General → Merge button); workflow должен иметь `pull-requests: write` и проверять `github.actor == "dependabot[bot]"`.
- **Workflow execution protections**: с 2 ноября 2026 default policy для public репозиториев блокирует `pull_request_target` от недоверенных акторов. Dependabot является доверенным, но проверьте Rulesets на уровне организации/репозитория.
- **Для Dependabot Secrets**: если workflow Dependabot-PR использует секреты (например, для deploy), заведите их в `Settings → Secrets → Dependabot` — обычные Actions-секреты Dependabot-событиям недоступны.

### Сценарий 1: Базовая конфигурация Dependabot (security + version updates)

**Предварительные требования**: Включённый Dependency Graph (Settings → Code security and analysis → Dependency graph) и Dependabot alerts (см. раздел выше).

```yaml
# .github/dependabot.yml
version: 2
updates:
  # --- Security + Version Updates для npm ---
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "06:00"
      timezone: "Europe/Moscow"
    open-pull-requests-limit: 10
    groups:
      "dev-dependencies":
        patterns:
          - "@types/*"
          - "typescript-eslint/*"
        update-types: ["patch"]
      "all-patches":
        patterns:
          - "*"
        update-types: ["patch"]
      "minor-feature":
        patterns:
          - "*"
        update-types: ["minor"]
    reviewers:
      - "platform-team"
    labels:
      - "dependencies"
      - "npm"
    milestone: 1
```

- **Валидация**: В UI репозитория → Settings → Code security and analysis → Dependabot → статус `Configured`. Первые PR появляются в течение одного расписания (`weekly`).
- **`open-pull-requests-limit`**: ограничивает количество одновременно открытых Dependabot PR (по умолчанию 10 на ecosystem).

### Сценарий 2: Dependabot для обновления GitHub Actions

Dependabot умеет обновлять **`uses:` ссылки в workflow-файлах** на новые версии экшенов.

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"   # Dependabot ищет .github/workflows/*.yml
    schedule:
      interval: "weekly"
    group:
      "minor-and-patch":
        update-types: ["minor", "patch"]
    reviewers:
      - "platform-team"
    labels:
      - "dependencies"
      - "ci"
```

- **Как это работает**: Dependabot читает `uses: actions/checkout@v7` и `uses: actions/setup-node@v7`, сравнивает с доступными тегами и открывает PR с обновлением `v7 → v8`.
- **Для SHA-pinned экшенов**: Dependabot создаёт PR с обновлённым SHA + комментарий с версией (например, `updates actions/checkout from abc123 to def456 (v7.0.1 → v7.0.2)`).
- **Валидация**: в логах workflow нет ошибок парсинга dependabot.yml; в разделе Insights → Dependency graph → Dependabot появляется запись о `github-actions` ecosystem.

### Сценарий 3: Auto-merge для patch и minor обновлений

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "daily"
    groups:
      "all-patch-and-minor":
        update-types: ["patch", "minor"]
    # Auto-merge для группы (v2, требует включения в org settings)
    allow:
      - dependency-type: "direct:production"
      - dependency-type: "direct:development"
    # Только non-major обновления авто-сливаются
    reviewers: ["platform-team"]
    # Для auto-merge — используйте GitHub Actions
```

Дополнительная конфигурация auto-merge через workflow:

```yaml
# .github/workflows/dependabot-auto-merge.yml
name: "Dependabot Auto-merge"
on:
  pull_request_target:

permissions:
  contents: write
  pull-requests: write

jobs:
  auto-merge:
    runs-on: ubuntu-latest
    if: github.actor == "dependabot[bot]"
    steps:
      - name: Auto-merge
        uses: ahmadnassri/action-dependabot-auto-merge@v24
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          # Авто-слияние только patch и minor, major — ручной ревью
          target-branch: "develop"
```

- **Важно**: `pull_request_target` — это потенциально небезопасный триггер (доступ к секретам). Используйте только с `if: github.actor == "dependabot[bot]"` и минимальными правами.
- **С 2 ноября 2026**: default policy для public репозиториев блокирует `pull_request_target` от недоверенных акторов — `dependabot[bot]` является доверенным, но проверьте настройки [Rulesets](./rulesets.md) workflow execution protections.

### Сценарий 4: Управление Dependabot Alerts через API

```bash
# Получить все open security alerts
gh api /repos/{owner}/{repo}/dependabot/alerts \
  --jq '.[] | select(.state == "open") | {number, security: .security_vulnerability.vulnerability.severity, pkg: .dependency.package.name, cve: .security_vulnerability.vulnerability.cve_id}'

# Получить SBOM (Software Bill of Materials) репозитория
gh api /repos/{owner}/{repo}/dependency-graph/sbom \
  --jq '.dependencies[] | {name: .name, version: .version, license: .license}'

# Dismiss alert (например, после слияния Dependabot PR)
gh api -X PATCH /repos/{owner}/{repo}/dependabot/alerts/42 \
  -f state="dismissed" \
  -f dismiss_reason="fix_started" \
  -f dismissed_comment="Fixed by PR #123"

# Получить сводку по организации
gh api /orgs/{org}/dependabot/alerts \
  --jq 'group_by(.security_vulnerability.severity) | map({severity: .[0].severity, count: length})'
```

### Сценарий 5: Dependabot для нескольких экосистем

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "pip"
    directory: "/backend"
    schedule:
      interval: "weekly"

  - package-ecosystem: "gomod"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
    # Обновление базовых образов в Dockerfile

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

### Сценарий 6: Dependabot для Docker образов и Terraform

```yaml
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "monthly"    # реже, образы стабильнее
    ignore:
      - dependency-name: "alpine"
        versions: ["3.18"]   # pin каллибровать вручную

  - package-ecosystem: "terraform"
    directory: "/infra"
    schedule:
      interval: "monthly"
    # Обновление провайдеров и модулей
```

## Команды и API-операции

### Управление конфигурацией

| Операция | Команда |
|---|---|
| Проверить конфиг | `Dependabot → Insights → Dependency graph` в UI |
| Список alert-ов | `gh api /repos/{owner}/{repo}/dependabot/alerts` |
| Dismiss alert | `gh api -X PATCH /repos/{owner}/{repo}/dependabot/alerts/{alert_number}` |
| Получить SBOM | `gh api /repos/{owner}/{repo}/dependency-graph/sbom` |
| Включить dependency graph | Settings → Code security and analysis → Dependency graph |

### Управление Dependabot Alerts через API

Dependabot Alerts API (v3, REST) управляет alert-ами на уровне репозитория и организации:

```bash
# Получить все open security alerts
gh api /repos/{owner}/{repo}/dependabot/alerts \
  --jq '.[] | select(.state == "open") | {number, security: .security_vulnerability.vulnerability.severity, pkg: .dependency.package.name, cve: .security_vulnerability.vulnerability.cve_id}'

# Получить SBOM (Software Bill of Materials) репозитория
gh api /repos/{owner}/{repo}/dependency-graph/sbom \
  --jq '.dependencies[] | {name: .name, version: .version, license: .license}'

# Dismiss alert (например, после слияния Dependabot PR)
gh api -X PATCH /repos/{owner}/{repo}/dependabot/alerts/42 \
  -f state="dismissed" \
  -f dismiss_reason="fix_started" \
  -f dismissed_comment="Fixed by PR #123"

# Получить сводку по организации
gh api /orgs/{org}/dependabot/alerts \
  --jq 'group_by(.security_vulnerability.severity) | map({severity: .[0].severity, count: length})'
```

**Поля alert-а**: `number`, `state` (`open`/`dismissed`), `dependency` (package, manifest, scope), `security_vulnerability` (severity, cve_id, advisory, vulnerable_range, fixed_version), `url`, `created_at`, `dismissed_at`, `dismiss_reason`, `dismissed_by`.

**Dismiss reasons**: `fix_started`, `fixed`, `false_positive`, `used_in_tests`, `tolerable_risk`.

### Native auto-merge (без workflow)

Dependabot с v2 поддерживает встроенное auto-merge через конфигурацию:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
    # Встроенный auto-merge (вместо workflow)
    allow:
      - dependency-type: "direct:production"
      - dependency-type: "direct:development"
    # reviewer-подтверждение не требуется для auto-merge
    # major-обновления auto-merge не включаются
    reviewers:
      - "platform-team"
    # Для включения — Settings → General → Merge button → "Allow auto-merge"
```

- **Механика**: Dependabot сам слияет PR после успешного CI, если `allow`-правила пропускают обновление. Не требует workflow с `pull_request_target`.
- **Ограничения**: native auto-merge не поддерживает conditional logic (например, только для определённых бранчей); workflow auto-merge гибче.

### Ignore patterns и version constraints

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
    ignore:
      - dependency-name: "lodash"           # игнорировать lodash целиком
        versions: ["<4.17.21"]               # и версии ниже 4.17.21
      - dependency-name: "@types/node"
        versions: [">=18 <19"]               # игнорировать 18.x
      - dependency-name: "typescript"
        update-types: ["minor", "major"]     # только patch для typescript
    versioning: "semver"                    # или "loose", "default"
    allow:
      - dependency-name: "axios"
        dependency-type: "direct:production"
```

- **`ignore`**: Dependabot не открывает PR для указанных зависимостей/версий. Security updates игнорируются только если `dependency-name` совпадает.
- **`versioning`**: `semver` (строгий semver), `loose` (допускает leading v), `default` (авто).
- **`allow`**: белый список зависимостей, которые Dependabot может обновлять. По умолчанию — все.

### Supply Chain Insights и SBOM

- **Supply Chain Insights** (GAS): расширенный анализ — SLSA-аттестации, sigstore подпись, dependency confusion алерты, анализ лицензий. Требует лицензии GAS.
- **SBOM через Dependency Graph**: `gh api /repos/{owner}/{repo}/dependency-graph/sbom` возвращает CycloneDX/SPDX-совместимый SBOM. Доступен без GAS для public репозиториев.
- **Advisory DB**: GitHub поддерживает собственную базу (GitHub Advisory Database) + интеграцию с OSV, npm advisory, PyPA, Ruby advisory, Go advisory, Rust advisory.

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| Dependabot не создаёт PR | Dependency Graph выключен | Settings → Code security and analysis → включить Dependency Graph |
| Security update не приходит | Нет подходящей безопасной версии | Проверить вручную; или создать ручной PR с fix |
| `manifest-not-found` в логах | `directory` в config не совпадает с расположением манифеста | Проверить: для корня — `/`, для frontend — `/frontend` |
| Auto-merge не работает | workflow использует `pull_request` вместо `pull_request_target` | Поменять trigger; добавить `if: github.actor == "dependabot[bot]"` |
| Dependabot не видит Actions в workflow | `package-ecosystem: "github-actions"` отсутствует в конфиге | Добавить ecosystem для github-actions |
| `open-pull-requests-limit` достигнут | Слишком много pending обновлений | Увеличить лимит или настроить `groups` для снижения PR-ов |
| Alert не исчезает после merge | CodeQL/dependency scan требует нового полного скана | Подождать или запустить ручной скан через schedule |
| Dependabot PR падает CI на fork | Workflow использует `pull_request` (изолированный) вместо `pull_request_target` | Для Dependabot используйте `pull_request_target` с осторожностью |

## Граничные случаи и ограничения

- **Major-обновления**: Dependabot не открывает security update для major-апдейтов, даже если они исправляют CVE (ломающие изменения требуют ручного ревью).
- **Кастомные версии**: если зависимость pinned в манифесте (например, `1.2.3` без `^`), Dependabot обновит только до patch/minor в рамках диапазона; для major нужна ручная замена диапазона.
- **Приватные пакеты**: Dependabot поддерживает обновление приватных пакетов через GitHub Packages, но для npm/pip — требуется `.npmrc`/`pip.conf` с токеном (не в репозитории!).
- **Monorepo с multiple manifests**: Dependabot обрабатывает каждый `directory` независимо; `open-pull-requests-limit` считается на ecosystem, а не на репозиторий.
- **Docker-образы**: Dependabot обновляет теги в `Dockerfile` и `docker-compose.yml`, но не следит за digest-пиннингом (для digest-pin используйте Renovate).
- **Fork PR**: Dependabot не открывает PR в upstream-репозиторий из fork; security updates для fork не генерируются.
- **Dependabot Secrets vs Actions Secrets**: Dependabot-события (`pull_request` от Dependabot) не получают обычные Actions-секреты. Используйте `pull_request_target` (с осторожностью) или Dependabot Secrets.
- **Terraform**: Dependabot поддерживает обновление провайдеров и модулей, но не отслеживает состояние `terraform state` — только версии в `.tf`-файлах.
- **GitHub Actions ecosystem**: Dependabot обновляет `uses:` ссылки, но не проверяет совместимость экшенов с новой версией CI/runner (требует ручного тестирования major-апдейтов).

## Откат и очистка

- **Откат Dependabot PR**: Dependabot не даёт "откатить" PR автоматически. Для отката — ручной merge-конфликт или disable-конфигурации на период стабилизации.
- **Disable Dependabot на период**: temporarily set `enabled: false` в `dependabot.yml` или отключить ecosystem в Settings → Dependabot. PR-ы перестанут создаваться, существующие остаются открытыми.
- **Очистка alert-ов**: dismiss через API с `dismiss_reason: "fix_started"`, `"false_positive"`, `"used_in_tests"`. Автоматически dismiss-ятся при слиянии Dependabot PR, который исправляет уязвимость.
- **Удаление конфигурации**: удаление `.github/dependabot.yml` останавливает version updates, но security updates продолжат работать (они не зависят от конфига).
- **Очистка Dependabot Secrets**: `gh secret list --app dependabot` для просмотра; удаление через `gh secret remove <NAME> --app dependabot`. Удаление Dependabot-секрета не влияет на Actions-секреты.
- **Auto-merge отмена**: если Dependabot PR auto-merge сломал прод — отключите auto-merge workflow (`if: github.actor == "dependabot[bot]"`) и верните предыдущую версию через `git revert` или `git push --force` (только protected branches).

## Лучшие практики

1. **Начинайте с security updates**: security updates создаются автоматически при Detection Graph, без `dependabot.yml`. Настраивайте version updates — это дополнение, а не замена.
2. **Auto-merge только для patch/minor**: major-обновления требуют человеческого ревью (ломающие изменения). Используйте `groups` для снижения числа PR.
3. **Ограничивайте `open-pull-requests-limit`**: по умолчанию 10 на ecosystem. Уменьшайте для CI с ограничениями на concurrent jobs.
4. **Groups для снижения шума**: группируйте `patch` и `minor` обновления одной экосистемы в один PR. Исключение: security updates всегда в отдельном PR.
5. **CI для Dependabot — `pull_request_target`**: `pull_request` изолирует fork PR и не даёт Dependabot доступа к секретам. Используйте `pull_request_target` с `if: github.actor == "dependabot[bot]"`.
6. **Добавляйте `reviewers` и `labels`**: Dependabot PR автоматически попадают на review нужной команде.
7. **Schedule в off-hours**: настраивайте `schedule` на ночь/выходной, чтобы не нагружать CI в рабочее время.
8. **Не используйте Dependabot вместо Renovate для сложных сценариев**: если нужна pin по digest, multi-platform группировка, или поддержка экосистем, которых Dependabot не знает — смотрите [Renovate](../CI-CD/dependency_automation.md).

## Дополнительная информация

- **[Автоматизация обновлений зависимостей (Renovate/Dependabot cross-platform)](../CI-CD/dependency_automation.md)** — сравнение движков, политика обновлений, lockfile maintenance, air-gapped среды.
- **[GitHub Advanced Security](./github_advanced_security.md)** — Dependabot Alerts как часть Security Overview, связь с Dependency Graph.
- **[Управление артефактами](./github_packages_ghcr.md)** — как Dependabot обновляет Docker образы и базовые образы стека.
- **[Rulesets](./rulesets.md)** — workflow execution protections для `pull_request_target` (с 2 ноября 2026 блокирует недоверенные).
- **Официальная документация**: [Dependabot](https://docs.github.com/en/code-security/dependabot), [Dependabot Alerts](https://docs.github.com/en/code-security/dependabot/dependabot-alerts/about-dependabot-alerts).
