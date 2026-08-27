# Автоматизация обновления зависимостей (Renovate / Dependabot)

## Определения

- **Renovate** — бот автоматического обновления зависимостей (работает self-hosted или как приложение Git-форжа), управляемый конфигом `renovate.json`.
- **Dependabot** — встроенный в GitHub механизм авто-PR по зависимостям (конфиг `dependabot.yml`).
- **Lockfile** — файл фиксации точных версий (`package-lock.json`, `pnpm-lock.yaml`, `uv.lock`, `go.sum`), гарантирующий воспроизводимость (см. **[Управление артефактами](./artifact_management.md)**).
- **SCA (Software Composition Analysis)** — анализ состава зависимостей на уязвимости (Trivy, npm audit, Snyk, Grype).
- **SBOM** — перечень компонентов; обязателен для комплаенса (см. **[Управление артефактами](./artifact_management.md)**).
- **Grouping / Range** — стратегии группировки обновлений (все патчи вместе) и выбора диапазона (patch/minor/major).
- **Dependency Dashboard** — специальный issue, который Renovate ведёт для всех ожидающих и заблокированных обновлений, давая единый центр управления (ручной запуск, откладывание, объединение PR).
- **Datasource** — источник метаданных версий (npm-registry, pypi, go-module, docker, terraform-provider, git-tags); определяет, откуда бот узнаёт о новых релизах.

---

## Базовые концепции

### Зачем нужна автоматизация
Ручное обновление зависимостей откладывается, накапливая уязвимости (CVE) и отставание. Авто-PR держат репозиторий свежим и делают обновления мелкими и безопасными (патч за патчем), а не «большим взрывом» раз в год. Автоматизация также снижает усталость от оповещений: вместо ручного разбора CVE-рассылок бот сам предлагает проверенный PR с прошедшим CI.

### Политика обновлений
- **Patch/Minor** — авто-мердж после успешного пайплайна (низкий риск).
- **Major** — только PR на ревью (ломающие изменения требуют глаз человека).
- **Grouping** — групповые PR для транзитивных пакетов одного вендора (меньше шума).
- **Schedule** — тайминг (например, раз в неделю ночью), чтобы не прерывать работу и не нагружать CI в рабочее время.

### Lockfile и его дрейф
Lockfile фиксирует точные версии транзитивных зависимостей. Со временем прямые зависимости обновляются, но **транзитивные записи в lock-файле устаревают** (дрейф), даже если прямые версии не менялись. Поэтому важен `lockFileMaintenance` — задача, которая перефиксирует lock-файл под актуальные доступные версии без изменения прямых зависимостей. Это критично для воспроизводимости и для закрытия CVE в глубоких зависимостях.

### SemVer-диапазоны и как их читает бот
Бот не обновляет «наугад»: он парсит манифест и понимает диапазон допустимых версий.
- `^1.2.3` (caret) — допустимы minor и patch в рамках мажора 1 → бот предложит `1.3.0`, но не `2.0.0`.
- `~1.2.3` (tilde) — только patch в рамках `1.2` → бот предложит `1.2.9`, но не `1.3.0`.
- фиксированная `1.2.3` — бот обновит только при явном правиле или вручную.

Понимание диапазонов позволяет задавать политику: «авто-мерж всё, что попадает в caret, но major — на ревью».

### Гейт безопасности
Каждый авто-PR проходит CI: `npm ci` (или `uv sync`/`go mod download`) + сборка + тесты + SCA-скан. При обнаружении критической уязвимости (`npm audit` / Trivy / Grype) — блокировка и уведомление. Подробнее в **[DevSecOps: SAST обзор](DevSecOps/sast_overview.md)** и **[DevSecOps: обзор](DevSecOps/devsecops_overview.md)**.

### Безопасный авто-мердж (rollout safety)
Авто-мердж патчей в `main` не означает мгновенный риск для продакшена, если деплой отделён стадиями. Рекомендуется: авто-мерж только в ветку разработки или стейджинга, а в прод — через проверенное продвижение артефакта (см. **[Управление артефактами](./artifact_management.md)**) либо после canary-прогона. Major-обновления всегда требуют ревью и ручного мерджа.

---

## Практические сценарии

### Сценарий 1: Конфигурация Renovate
```json
// renovate.json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended", ":semanticCommits", ":dependencyDashboard"],
  "schedule": ["before 6am on monday"],
  "labels": ["dependencies"],
  "packageRules": [
    { "matchUpdateTypes": ["patch", "minor"], "automerge": true },
    { "matchUpdateTypes": ["major"], "automerge": false },
    { "matchDepTypes": ["devDependencies"], "addLabels": ["dev-deps"] }
  ],
  "lockFileMaintenance": { "enabled": true, "schedule": ["monthly"] }
}
```

### Сценарий 2: Конфигурация Dependabot
```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 10
    groups:
      all-patches:
        update-types: ["patch"]
```

### Сценарий 3: Гейт безопасности в пайплайне (блокировка при CVE)
```yaml
dependency_audit:
  stage: test
  # кэш зависимостей ускоряет аудит — см. Ключи кэша в GitLab CI
  script:
    - |
      # npm audit с порогом; не-нулевой exit при high/critical
      npm audit --audit-level=high || { echo "Vulnerabilities found"; exit 1; }
    - trivy fs --severity CRITICAL,HIGH --exit-code 1 .
```
Воспроизводимая установка (`npm ci`, строго по lock-файлу) описана в **[Специфические задачи Frontend CI/CD](./Frontend_CI_CD/frontend_pipeline_specifics.md)**.

### Сценарий 4: Авто-мердж патчей (GitLab)
```yaml
# GitLab: авто-мердж MR от Renovate после успешного пайплайна
.merge_request:
  rules:
    - if: $CI_MERGE_REQUEST_LABELS =~ /dependencies/ && $CI_PIPELINE_SOURCE == "merge_request_event"
```
(Для Renovate авто-мердж настраивается в `packageRules.automerge` — Сценарий 1.)

### Сценарий 5: Renovate в GitLab (self-hosted)
В GitLab бота можно запускать как периодическую задачу (cron) или контейнер; токен с правами `api` выдаётся через переменную CI, а не хранится в репозитории.

```bash
# Запуск Renovate как одноразовой задачи (self-hosted, внутри периметра)
docker run --rm \
  -e RENOVATE_TOKEN="$GITLAB_TOKEN" \
  -e RENOVATE_CONFIG_FILE="/cfg/renovate.json" \
  -v /srv/renovate:/cfg \
  renovate/renovate:latest
```
Минимальный конфиг для платформы GitLab:
```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "platform": "gitlab",
  "labels": ["dependencies"],
  "packageRules": [
    { "matchUpdateTypes": ["patch", "minor"], "automerge": true }
  ]
}
```

### Сценарий 6: Обновление разных экосистем (не только npm)
Бот поддерживает десятки менеджеров; ключевое — указать экосистему и директорию.

```yaml
# .github/dependabot.yml — несколько экосистем сразу
version: 2
updates:
  - package-ecosystem: "pip"          # Python (requirements.txt / pyproject)
    directory: "/backend"
    schedule: { interval: "weekly" }
  - package-ecosystem: "gomod"        # Go modules
    directory: "/"
    schedule: { interval: "weekly" }
  - package-ecosystem: "docker"       # базовые образы в Dockerfile
    directory: "/"
    schedule: { interval: "weekly" }
  - package-ecosystem: "terraform"    # провайдеры и модули
    directory: "/infra"
    schedule: { interval: "monthly" }
```
Для Renovate эквивалент — секции по менеджерам (`npm`, `pip_requirements`, `gomod`, `dockerfile`, `terraform`), причём базовый образ обновляется через datasource `docker` с pin по digest (см. **[Управление артефактами](./artifact_management.md)** о пиннинге digest).

### Сценарий 7: Изолированные сети (air-gapped) и внутренние зеркала
В контуре без доступа к публичным реестрам бот должен смотреть во внутреннее зеркало (Nexus/Artifactory). Указывается через `registryUrls` (Renovate) или зеркало пакетного менеджера.

```json
{
  "npm": { "registryUrls": ["https://nexus.internal/repository/npm/"] },
  "docker": { "registryUrls": ["nexus.internal:5000"] },
  "packageRules": [
    { "matchDatasources": ["docker"], "pinDigests": true }
  ]
}
```
> Принцип: бот не ходит в Internet, а синхронизирует метаданные и артефакты через проксирующее зеркало внутри периметра (подробнее в **[Изолированные среды](./Core_Concepts/air_gapped_environments.md)**).

### Сценарий 8: Безопасный авто-мердж с гейтом продвижения (SRE)
Патчи мерджатся автоматически в ветку `develop`/`staging`, но в `main`/прод — только после успешного прогона в стейджинге. Это разделяет «обновили код» и «обновили прод».

```yaml
# GitLab: авто-мердж только для staging-ветки и метки dependencies
automerge_staging:
  rules:
    - if: $CI_MERGE_REQUEST_LABELS =~ /dependencies/
         && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "staging"
         && $CI_PIPELINE_SOURCE == "merge_request_event"
```
Major-обновления исключаются правилом `matchUpdateTypes: ["major"] → automerge:false` (Сценарий 1) и требуют ручного ревью.

---

## Дополнительная информация

### Лучшие практики
1. Включайте `lockFileMaintenance` — иначе транзитивные зависимости в lock-файле устареют (дрейф).
2. Major-обновления — только на ревью человека; patch/minor — авто-мердж (через `packageRules` или `groups`).
3. Привяжите SCA-скан (`npm audit`/Trivy/Grype) к каждому зависимостному PR.
4. Обновляйте CI-инструменты и раннер-образы тем же ботом — они тоже имеют CVE (datasource `docker` для базовых образов).
5. Генерируйте SBOM при каждом релизе (см. **[Управление артефактами](./artifact_management.md)**).
6. Используйте Dependency Dashboard — единая точка для ручного запуска, откладывания и группировки обновлений.
7. Ограничивайте шум: `open-pull-requests-limit`, группировки по вендору, расписание в нерабочее время.
8. Для изолированных контуров направляйте бота на внутренние зеркала (`registryUrls`), не в публичный Internet.

### Устранение неполадок (Troubleshooting)
| Симптом | Вероятная причина | Действие |
| :--- | :--- | :--- |
| Шум из сотен PR | Нет группировки | `packageRules`/`groups` группируют патчи одного вендора |
| Сломанный авто-мердж | Пайплайн не полный | Требовать сборку+тесты+SCA перед мерджем |
| Устаревший lockfile | Нет maintenance | Включить `lockFileMaintenance` |
| Критический CVE прошёл | Нет SCA-гейта | `npm audit`/`trivy`/`grype` с `exit-code 1` в CI |
| Бот не открывает PR | Неверный токен/нет прав `api` | Проверить `RENOVATE_TOKEN`/`GITLAB_TOKEN`, права на repo |
| Rate limit API форжа | Частые запросы | Увеличить интервал `schedule`, включить `prHourlyLimit` |
| Конфликт lock-файла при параллельных PR | Несколько PR правят один lock | Группировать один менеджер в один PR |
| Major не предлагается | Диапазон caret `^` ограничивает мажор | Явно разрешить major-PR или инициировать вручную |

### См. также
- **[Управление артефактами](./artifact_management.md)** — SBOM, lockfile, воспроизводимость, pin по digest.
- **[DevSecOps: обзор](DevSecOps/devsecops_overview.md)** — место SCA в цепочке поставок.
- **[Ключи кэша в GitLab CI](GitLab_CI/Advanced/gitlab_ci_caching/cache_keys.md)** — кэш зависимостей для быстрого аудита.
