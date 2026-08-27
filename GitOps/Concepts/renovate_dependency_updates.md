# Renovate: автоматизация обновлений в GitOps-репозиториях

> **Актуальность (2026):** Renovate де-факто стал стандартом для автоматизации обновления образов, Helm-чартов и зависимостей через PR/MR. Инструмент open-source, развивается Mend, релизы выходят еженедельно; самостоятельный запуск (self-hosted) и облачный вариант (GitHub App) используют один и тот же движок конфигурации.

Обновление версии образа в GitOps — это обычный коммит. Значит, его можно доверить боту, который откроет PR, дождется зеленых CI-гейтов и смёржит по правилам команды. Renovate замыкает цикл: реестр → PR → гейты → мерж → реконсиляция GitOps-агентом.

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| Renovate | Self-hosted CLI (Docker-образ `ghcr.io/renovatebot/renovate`) либо Mend-hosted приложение |
| Git-хостинг | GitHub, GitLab (включая self-managed), Bitbucket, Gitea, Azure DevOps |
| Токен | PAT с правами на чтение репозиториев, создание веток и MR/PR |
| CI-гейты | Валидация манифестов в PR (kubeconform, conftest, dry-run) — условие безопасного автомержа |
| GitOps-агент | Argo CD v3.x или Flux v2.9.x — доставляет обновление после мерджа |

## Определения

- **Renovate**: Бот автоматизации обновлений. Сканирует репозиторий, находит зависимости (образы, чарты, Actions, пакеты), сравнивает с источниками версий и открывает PR с изменениями.
- **Manager**: Модуль распознавания зависимостей в конкретном типе файлов: `docker` (образы в YAML/Dockerfile/kustomize), `helmv3` (зависимости в Chart.yaml), `github-actions`, `gitlabci`, `regex` (универсальный fallback под нестандартные форматы).
- **Datasource**: Откуда брать список версий: `docker` (любой OCI-реестр, включая Harbor/GHCR), `helm` (репозитории и OCI-чарты), `github-releases` и т.д.
- **packageRule**: Правило, группирующее обновления по критериям (пути файлов, тип обновления patch/minor/major) и задающее поведение: расписание, automerge, ревьюеров, pinning.
- **Automerge**: Автоматическое слияние PR при выполнении условий (зеленые статус-чеки, возраст релиза). Для GitOps это безопасно ровно настолько, насколько надежны гейты в PR.
- **minimumReleaseAge**: Минимальный возраст релиза перед тем, как Renovate предложит обновление — задержка свежих сборок до окончания окна активных атак («supply-chain diode»).
- **Digest pinning** (`pinDigests`): Фиксация `image@sha256:...` вместо плавающего тега — согласуется с принципом неизменяемости артефактов.

## Базовые концепции

### Место Renovate в GitOps-цикле

```text
CI собирает и публикует образ vX.Y.Z (digest D)
            │
            ▼
Renovate обнаруживает новую версию (опрос реестра)
            │
            ▼
PR в инфраструктурный репозиторий: tag/digest/charts bump
            │
            ▼
CI-гейты PR: kubeconform → conftest → kube-score → dry-run
            │
     ┌──────┴───────┐
     ▼              ▼
  зелёные       красные
  automerge      PR висит,
     │           уведомление команде
     ▼
Merge → GitOps-агент синхронизирует кластер
```

Ключевое отличие от кластерных автоматизаторов (Image Updater, Flux Image Automation): **изменение всегда проходит через PR с ревью и гейтами**, даже при automerge. Это сохраняет принципы GitOps — версионирование, аудит и возможность остановить обновление до попадания в кластер.

### Сравнение инструментов автоматизации обновлений

| Инструмент | Механизм | Что обновляет | Когда выбирать |
| :--- | :--- | :--- | :--- |
| **Renovate** | PR/MR в репозиторий | Образы, чарты, CI-экшены, языковые зависимости | Универсальный стандарт; нужна политика обновлений и ревью |
| **Dependabot** | PR (только GitHub SaaS) | Экосистемы GitHub, Actions | Простой кейс на GitHub, без self-hosted |
| **Argo CD Image Updater** | Write-back через API Argo CD (Git опционально) | Только образы для Argo CD Applications | Dev/QA среды без лишних коммитов |
| **Flux Image Automation** | Контроллеры Flux, маркеры `$imagepolicy` | Образы (с digest pinning) | Кластерная автоматизация во Flux-стеке |
| **Kargo** | Promotion-пайплайны с гейтами | Артефакты между стадиями | Цепочка сред с верификацией и approvals |

Практичная комбинация: Renovate — для всего репозитория (включая чарты и CI-зависимости), кластерные автоматизаторы — точечно для dev-сред. **Важно: один файл должен писать один инструмент** — конфликт двух ботов, переписывающих одну строку, порождает бесконечные MR-войны.

### Ключевые настройки политики

| Настройка | Назначение |
| :--- | :--- |
| `schedule` | Окно создания PR (например, рабочие часы), чтобы не будить дежурных ночью |
| `automergeType: pr` / `branch` | Мержить PR целиком или только ветку (PR остается для истории) |
| `minimumReleaseAge` | Не предлагать релизы младше N часов/дней — фильтр скомпрометированных сборок |
| `separateMajorMinorPatch` | Major — всегда отдельный PR с пометкой breaking; patch/minor можно группировать |
| `groupName` | Объединять мелкие обновления в один PR (меньше шума, хуже bisect — компромисс) |
| `labels`, `reviewers`, `assignees` | Маршрутизация PR: CODEOWNERS + метки для автополитик ревью |
| `prHourlyLimit` / `prConcurrentLimit` | Защита от шторма PR в монорепозиториях и от rate-limit'ов Git-хостинга |
| `lockFileMaintenance` / `rangeStrategy: pin` | Поддержка пинов и lock-файлов в актуальном состоянии |

## Практические сценарии

### Сценарий 1: Базовая конфигурация инфраструктурного репозитория

```json
// renovate.json в корне GitOps-репозитория
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": [
    "config:recommended",
    ":semanticCommits",
    ":timezone(Europe/Moscow)"
  ],
  "schedule": ["after 9am and before 3pm every weekday"],
  "osvVulnerabilityAlerts": true,          // PR при CVE в текущей версии
  "labels": ["dependencies"],
  "prHourlyLimit": 5,
  "prConcurrentLimit": 10,
  "docker": {
    "pinDigests": true                     // фиксировать digest рядом с тегом
  }
}
```

После первого запуска Renovate откроет серию PR «Update ghcr.io/org/app to v1.9.0» — каждый с changelog и diff'ом манифестов.

### Сценарий 2: Digest-pinning для прода и automerge для dev-оверлеев

Разделение строгости по путям — типовой паттерн монорепозитория:

```json
{
  "packageRules": [
    {
      "description": "PROD: pin digest, никаких авто-мержей",
      "matchFileNames": ["apps/**/overlays/prod/**"],
      "pinDigests": true,
      "automerge": false,
      "minimumReleaseAge": "3 days",
      "reviewers": ["team:platform"]
    },
    {
      "description": "DEV: patch/minor автоматически после зеленых гейтов",
      "matchFileNames": ["apps/**/overlays/dev/**"],
      "matchUpdateTypes": ["patch", "minor"],
      "automerge": true,
      "automergeType": "pr",
      "minimumReleaseAge": "4 hours"
    },
    {
      "description": "MAJOR всегда вручную, отдельным PR",
      "matchUpdateTypes": ["major"],
      "automerge": false,
      "labels": ["breaking", "needs-review"]
    }
  ]
}
```

Условие безопасного automerge — обязательные статус-чеки PR (см. [пример пайплайна](../gitops_pipeline_example.md)): без них Renovate смёржит необновленный YAML прямо в кластер.

### Сценарий 3: Self-hosted запуск из CI по расписанию

Для self-managed GitLab (или когда облачное приложение Mend нельзя):

```yaml
# .gitlab-ci.yml — триггер: scheduled pipeline (например, каждый час)
renovate:
  stage: maintenance
  image: ghcr.io/renovatebot/renovate:latest
  variables:
    RENOVATE_TOKEN: $GITLAB_BOT_PAT          # PAT бота
    RENOVATE_PLATFORM: gitlab
    RENOVATE_ENDPOINT: https://gitlab.internal/api/v4
    RENOVATE_AUTODISCOVER: "true"            # или явный список:
    RENOVATE_REPOSITORIES: "platform/fleet-infra"
    LOG_LEVEL: info
  script:
    - renovate
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
```

Альтернатива на GitHub — GitHub Action `renovatebot/github-action` по cron либо подключение Mend GitHub App (без своей инфраструктуры, но код конфигураций проходит через внешний сервис — учитывайте требования безопасности).

### Сценарий 4: Обновление Helm-чартов из внутреннего OCI-зеркала

После прецедентов вроде заморозки публичного каталога Bitnami чарты зеркалируются в свой Harbor, а Renovate ходит только внутрь контура:

```json
{
  "hostRules": [
    {
      "hostType": "docker",
      "matchHost": "harbor.internal",
      "username": "renovate-bot",
      "password": "$HARBOR_TOKEN"
    }
  ],
  "helmv3": {
    "managerFilePatterns": ["/(^|/)Chart\\.yaml$/"]
  }
}
```

```yaml
# Chart.yaml приложения — зависимости указывают на зеркало
dependencies:
  - name: redis
    version: 19.6.1          # ← этот номер обновит Renovate
    repository: oci://harbor.internal/charts/redis
```

Renovate резолвит новые версии из OCI-реестра и поднимает `version`; доставка нового чарта в кластер — обычной реконсиляцией (см. [организацию хранения чартов](../GitOps_overview.md)).

### Сценарий 5: Шумоподавление в большом монорепозитории

```json
{
  "prHourlyLimit": 3,
  "prConcurrentLimit": 8,
  "rebaseWhen": "conflicted",
  "packageRules": [
    {
      "description": "Группа patch-обновлений платформенных аддонов",
      "matchFileNames": ["platform/**"],
      "matchUpdateTypes": ["patch"],
      "groupName": "platform patch bundle",
      "automerge": true
    },
    {
      "description": "Нестандартные поля образов в values.yaml через regex-manager",
      "matchFileNames": ["apps/*/values.yaml"],
      "customManagers": [
        {
          "customType": "regex",
          "fileMatch": ["^apps/.*/values\\.yaml$"],
          "matchStrings": [
            "image:\\s*\"?(?<depName>registry\\.internal/app):(?<currentValue>v[0-9.]+)\"?"
          ],
          "datasourceTemplate": "docker"
        }
      ]
    }
  ]
}
```

Regex-manager покрывает форматы, которые штатные менеджеры не распознают (строки в values, переменные Terraform, поля в JSON-конфигах приложений).

## Типовые проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Renovate молчит, PR не создаются | Невалидный токен, отсутствие прав на ветки/MR | Проверить лог запуска: `WARN: Unknown error` обычно про токен; выдать `api`, `write_repository` |
| Волна из 50 PR после подключения | Первичный обход всех зависимостей | Ограничить `prConcurrentLimit`, включить группировку, размазать `schedule` |
| Automerge не срабатывает | Имя required check не совпадает с контекстом CI | Сверить названия статус-чеков в branch protection с фактическими job'ами |
| Два бота дерутся за один файл | Image Updater и Renovate пишут одно значение | Один инструмент на один файл: кластерные автоматизаторы — dev, Renovate — prod/чарты |
| Обновление сломало прод, хотя CI был зелёным | Гейты не покрыли runtime-поведение | Добавить smoke-test/dry-run в PR; для критичных сервисов — canary вместо прямого мержа (см. [прогрессивную доставку](./progressive_delivery_gitops.md)) |
| Rate-limit Git-хостинга | Много репозиториев на одном токене | Отдельный бот-PAT, `prHourlyLimit`, autodiscover с exclude-паттернами |
| Major-обновление прошло незаметно среди мелких | Нет сегрегации типов обновлений | `separateMajorMinorPatch: true`, метки `breaking`, обязательный reviewer |

## Дополнительная информация

- **Безопасность цепочки поставок**: связка `minimumReleaseAge` + digest pinning + проверка подписей в кластере закрывает окно атаки на свежие сборки — тот же принцип «supply-chain diode», который применяют сами контроллеры доставки.
- **Метрики процесса**: количество смёрженных renovate-PR по типам обновлений — полезный вход для анализа стабильности (рост доли hotfix после обновлений = сигнал ужесточить гейты). Измерение — в [DORA-метриках GitOps](./dora_metrics_gitops.md).

### См. также

- [Жизненный цикл образов и хранение](./containerization_and_image_storage.md) — digest pinning, зеркала, Kargo-промоушен.
- [Argo CD Image Updater](../ArgoCD/argocd_image_updater.md) — кластерный альтернативный механизм.
- [Flux: Image Automation](../flux.md) — автоматизация обновлений во Flux-стеке.
- [Пример GitOps-пайплайна](../gitops_pipeline_example.md) — гейты качества, которые делает automerge безопасным.
- [Dependabot для GitHub Actions](../../Github_CI/Marketplace_Actions.md) — обновление CI-зависимостей на стороне GitHub.
