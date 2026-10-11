# GitHub Rulesets: Защита веток, тегов и workflow execution

**Актуально для:** GitHub Rulesets, октябрь 2026 (workflow execution protections — GA с 17 сентября 2026; default pull_request_target policy — с 2 ноября 2026); для GitHub Enterprise Server — 3.14+ (функции доступны с задержкой)

GitHub Rulesets — современная замена устаревшему **Branch Protection Rules** (BPR). Rulesets предоставляют более гибкую, масштабируемую и API-дружелюбную модель защиты веток и тегов, а также расширенные возможности контроля выполнения workflow. В отличие от BPR (которые настраиваются на уровне репозитория), Rulesets работают на трёх уровнях иерархии: **Enterprise → Organization → Repository**, с наследованием и переопределением.

## Определения

- **Ruleset**: Набор правил защиты, применяемых к веткам, тегам или workflow execution. Может быть включён (Enforced) или находиться в режиме оценки (Evaluate — теневой аудит без блокировки).
- **Repository Ruleset**: Ruleset на уровне репозитория. Поддерживает наследование от organization-level rulesets и собственные переопределения.
- **Organization Ruleset**: Ruleset на уровне организации, применяется ко всем репозиториям организации (или избранным). Доступен для Enterprise и Organization планов.
- **Enterprise Ruleset**: Ruleset на уровне Enterprise, применяется ко всем организациям и репозеториям Enterprise.
- **Bypass Actor**: Пользователь, роль, GitHub App или тип аккаунта, которому правила не применяются (обходят защиту). Доступные типы: User, Team, Role, Integration (GitHub App), `OrganizationAdmin`.
- **Pattern**: Шаблон имени ветки/тега с поддержкой wildcard (`*`, `?`, `[abc]`) и `name-prefix/pattern`. Примеры: `release/*`, `v*`, `**`.
- **Workflow Execution Protection**: Набор правил, блокирующих или разрешающих запуск workflow на основе actor rules (кто может триггерить) и event rules (какие события разрешены). Работает поверх rulesets framework.
- **Evaluate mode**: Режим rulesets, при котором правила не блокируют, а только логируют нарушения в audit log. Используется для постепенного rollout новых правил.

## Архитектура и иерархия

### Иерархия наследования

```text
Enterprise Ruleset
    ↓ (наследуется всеми org, если не переопределён)
Organization Ruleset (может быть scoped на select/all репозитории)
    ↓ (наследуется репозиторием, если не переопределён)
Repository Ruleset (локальные правила, могут добавлять/переопределять)
    ↓
Effective Rules (объединение всех уровней)
```

- **Наследование**: каждый уровень наследует правила с уровня выше, но может добавить свои. Правило с более высокого уровня не может быть "отключено" на нижнем — только дополнено.
- **Precedence**: если на разных уровнях есть конфликтую настройки (например, один уровень требует 1 аппрув, другой — 2), применяется **самое строгое**.
- **Evaluate mode** на высшем уровне позволяет протестировать правила перед переводом в Enforced.

### Workflow Execution Protections

С 17 сентября 2026 (GA) workflow execution protections позволяют контролировать, кто и как может запускать workflow:

- **Actor rules**: allowlist акторов (Users, Teams, Roles, GitHub Apps, Dependabot) — только они могут триггерить workflow.
- **Event rules**: allowlist событий (`push`, `pull_request`, `workflow_dispatch`, `schedule` и др.) — только указанные события могут запускать workflow.
- **Default policy** (с 2 ноября 2026 для public репозиториев): блокирует автоматический запуск `pull_request_target` от недоверенных акторов.

## Практические сценарии

### Сценарий 1: Базовый Repository Ruleset для защиты ветки `main`

**Предварительные требования**: Права администратора на репозиторий.

```bash
# Создать ruleset для защиты main через API
gh api -X POST /repos/{owner}/{repo}/rulesets \
  -f "name"="Protect main branch" \
  -f "target"="branch" \
  -f "enforcement"="active" \
  -f "bypass_mode"="pull_request" \
  -f 'patterns[]=main' \
  -f 'rules[0][type]="creation"' \
  -f 'rules[1][type]="update"' \
  -f 'rules[2][type]="deletion"' \
  -f 'rules[3][type]="required_linear_history"' \
  -f 'rules[4][type]="required_signatures"'
```

Или через UI: Settings → Code and automation → Rules → Rulesets → Create ruleset → Branch → Target: `main` → Enforcement: Active.

**Ключевые правила для `main`:**
- `creation` — блокирует создание ветки `main` (должна быть защищена)
- `update` — блокирует прямой `git push` в ветку
- `deletion` — блокирует удаление ветки
- `required_linear_history` — запрещает merge-коммиты (только `--ff-only` / rebase)
- `required_signatures` — требует GPG/SSH-подписи для всех коммитов

- **Валидация**: попытка `git push origin main` завершается ошибкой `remote: error: GH013: Ветвь «main» защищена`; в audit log видны попытки обхода.

### Сценарий 2: Tag Protection Ruleset (Ruleset на паттерн `v*`)

Защита релизных тегов от случайного переименования или удаления:

```yaml
# Settings → Rules → Rulesets → New ruleset → Tag
name: "Protect release tags"
target: "tag"
enforcement: "active"
patterns:
  - "v*"
rules:
  - creation
  - update    # блокирует переименование (перемещение тега на другой коммит)
  - deletion
  - required_signatures  # подпись для всех релизных тегов
bypass_actors:
  - actor_id: 5 # GitHub Actions
    actor_type: "Integration"
    # CI/CD триггеры по тегу должны обходить (иначе сборка падает на защите)
```

**Важно**: `required_signatures` для тегов требует, чтобы теги были подписаны GPG/SSH. Для CI-автоматизации теги обычно не подписываются — добавляйте `bypass_actors` для GitHub Actions (Integration ID 5).

### Сценарий 3: Bypass Actor для автоматизации (App + Installation Token)

Чтобы CI/CD мог писать в защищённую ветку, добавьте bypass actor — GitHub App или GitHub Actions:

```bash
# Добавить bypass для GitHub Actions (app_id = 5)
gh api -X POST /repos/{owner}/{repo}/rulesets \
  -f name="main-protection" \
  -f target="branch" \
  -f enforcement="active" \
  -f 'patterns[]=main' \
  -f 'rules[0][type]="update"' \
  -f 'bypass_actors[0][actor_id]=5' \
  -f 'bypass_actors[0][actor_type]="Integration"' \
  -f 'bypass_actors[0][bypass_mode]="always"'
```

Для **GitHub App** (см. [github_apps.md](./github_apps.md)): в UI добавляете App в "Bypass list" → выбираете установленный App. Installation Token этого App'а затем может `git push` в защищённую ветку.

```yaml
# Пример: бот-коммиты через App-токен в защищённую ветку
- uses: actions/create-github-app-token@v3
  id: app-token
  with:
    client-id: ${{ vars.APP_CLIENT_ID }}
    private-key: ${{ secrets.APP_PRIVATE_KEY }}
    permission-contents: write
- uses: actions/checkout@v7
  with:
    token: ${{ steps.app-token.outputs.token }}
- run: git push origin HEAD:main  # обходит защиту через bypass actor
```

### Сценарий 4: Workflow Execution Protection (actor + event rules)

На уровне Enterprise или Organization:

```bash
# Enterprise-level: только Dependabot и GitHub Actions могут триггерить,
# только события push и pull_request разрешены
gh api -X POST /enterprises/{enterprise}/rulesets \
  -f name="Restrict workflow triggers" \
  -f target="workflow" \
  -f enforcement="active" \
  -f 'rules[0][type]="max_file_size"' \
  -f 'rules[0][parameters][max_file_size]=5242880' \
  -f 'bypass_actors[0][actor_id]=5' \  # GitHub Actions
       'bypass_actors[0][actor_type]="Integration"' \
       'bypass_actors[0][actor_id]=286879' \  # Dependabot
       'bypass_actors[1][actor_type]="Integration"'
```

Или через UI: Settings → Policies → Actions → Workflow execution permissions → Configure rules.

**Default policy с 2 ноября 2026**: в public репозиториях автоматически блокируется `pull_request_target` от недоверенных акторов (forks, анонимные пользователи).

### Сценарий 5: Organization-level Ruleset с Evaluate mode

Для постепенного rollout новых правил:

```bash
# Создать ruleset в evaluate mode (теневой аудит)
gh api -X POST /orgs/{org}/rulesets \
  -f name="Strict CI requirements" \
  -f target="branch" \
  -f enforcement="evaluate" \
  -f 'patterns[]=main' \
  -f 'rules[0][type]="required_status_checks"' \
  -f 'rules[0][parameters][required_status_checks][contexts][]=ci/tests' \
  -f 'rules[0][parameters][required_status_checks][strict]=true'
```

Правила в `evaluate` mode не блокируют, но логируют нарушения в audit log. После подтверждения что нарушений нет — переключите на `active`.

## Команды и API-операции

### Управление rulesets через API

| Операция | Endpoint | Описание |
|---|---|---|
| Список rulesets | `GET /repos/{owner}/{repo}/rulesets` | Список repository-level rulesets |
| Создать ruleset | `POST /repos/{owner}/{repo}/rulesets` | Create new ruleset |
| Получить ruleset | `GET /repos/{owner}/{repo}/rulesets/{ruleset_id}` | Информация о ruleset |
| Обновить ruleset | `PATCH /repos/{owner}/{repo}/rulesets/{ruleset_id}` | Update enforcement/rules |
| Удалить ruleset | `DELETE /repos/{owner}/{repo}/rulesets/{ruleset_id}` | Delete ruleset |
| Проверить правила | `GET /repos/{owner}/{repo}/rules/branches/{branch}` | Effective rules для ветки |
| Audit log | `GET /orgs/{org}/audit-log` | Журнал enforcement decisions |

### CLI (`gh`)

```bash
# Список rulesets репозитория
gh api /repos/{owner}/{repo}/rulesets --jq '.rulesets[] | {name: .name, target: .target, enforcement: .enforcement}'

# Проверить эффективные правила для ветки
gh api /repos/{owner}/{repo}/rules/branches/main --jq '.rules[] | .type'

# Создать ruleset из JSON
gh api -X POST /repos/{owner}/{repo}/rulesets -f @ruleset.json
```

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `push` отклоняется с `GH013` | Ruleset не допускает прямой push в ветку | Использовать PR workflow или добавить bypass actor для бота |
| `pull_request` не может merge | Не выполнены `required_status_checks` | Добавить `permissions: statuses: write` для workflow, который ставит чек |
| `fork PR` блокируется push protection | Push protection или workflow execution protection активен для fork | Fork PRs работают на основе merge-коммита base branch; для `pull_request`-триггеров fork работает, для `pull_request_target` — только если явно настроено |
| Tag не создаётся | Tag protection (создание) блокирует | Добавить bypass для GitHub Actions или CI-сервиса; или использовать unsigned теги в workflow |
| `Required signatures` ломает CI | Теги/коммиты не подписаны | Добавить bypass actor для Integration; отключить для CI-триггеров |
| Ruleset в `evaluate` mode всё ещё блокирует | Наследуемый `active` ruleset с более строгим правилом | Проверить, нет ли enforcement на уровне org/enterprise; использовать audit log для диагностики |

## Лучшие практики

1. **Используйте Rulesets вместо Branch Protection Rules**: BPR устарели и не поддерживают inheritance, evaluate mode и workflow execution protections.
2. **Начинайте с Evaluate mode**: включите новые правила в `evaluate` на пару недель, чтобы собрать статистику нарушений, прежде чем переводить в `active`.
3. **Bypass actors для автоматизации**: всегда добавляйте bypass для GitHub Actions (Integration ID 5) и установленного GitHub App, чтобы CI/CD мог писать в protected ветки/теги.
4. **Не давайте `delete` на теги без bypass**: если тег защищён `deletion`, CI-триггеры по тегу работают, но ручное удаление тега невозможно.
5. **Organization-level для единообразия**: задавайте enterprise/org-level правила для production-веток (`main`, `master`*) и релизных тегов (`v*`), чтобы не пропустить репозитории.
6. **Workflow execution protections**: включайте на enterprise level, чтобы блокировать `pull_request_target` и другие небезопасные триггеры от недоверенных акторов.
7. **Аудит**: используйте `GET /orgs/{org}/audit-log` для анализа нарушений rulesets — это SRE-источник для обнаружения bypass-попыток.

## Дополнительная информация

- **[Git-автоматизация](./Git_Automation.md)** — использование App-токена для push в защищённую ветку (bypass).
- **[GitHub Apps](./github_apps.md)** — настройка GitHub App как bypass actor для rulesets.
- **[Управление релизами](./Release_Management.md)** — защита тегов через rulesets (`v*` паттерн).
- **[Ключевые концепции](./Core_Concept.md)** — workflow execution protections и модель доверия Pull Requests.
- **[Git Workflows](../Git/git_workflows.md#защита-веток-branch-protection)** — классическая защита веток и сравнение стратегий.
- **Официальная документация**: [GitHub Rulesets](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repositories/managing-rulesets), [Workflow execution protections](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-workflow-execution- protections-to-control-workflows).
