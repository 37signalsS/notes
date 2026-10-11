# GitHub Deployments API: Деплой, окружения и статусы

**Актуально для:** Deployments API, Environments, октябрь 2026 (deployment branches protection, custom deployment protection rules — preview → GA; `environment_url` auto-detection); для GitHub Enterprise Server — 3.14+

GitHub Deployments API — это набор REST endpoint-ов для управления deployment lifecycle на уровне репозитория. Он позволяет создавать deployment (запрос на деплой), обновлять deployment status (успех/провал), управлять environments и интегрироваться с внешними CD-системами (Spinnaker, Argo, GitHub Actions, Jenkins). Deployments API — это не CI/CD-движок, а **протокол согласования** между GitHub и внешней системой деплоя.

## Определения

- **Deployment**: Запрос на развертывание конкретного коммита (SHA) или ветки в конкретное окружение (например, `production`). Создаётся через API или через GitHub Actions.
- **Environment**: Именованная логическая среда развертывания (`staging`, `production`) с защитными правилами (Manual Approvals, Wait Timer), секретами и переменными. Создаётся в Settings → Environments.
- **Deployment Status**: Статус выполнения deployment (`success`, `failure`, `pending`, `error`). Дополнительно: `log_url`, `environment_url`, `auto_merge_ref`.
- **Deployment Branch Policy**: Ограничение, какие ветки могут деплоиться в окружение (например, только `main`).
- **Custom Deployment Protection Rules**: Внешние проверки (Datadog, ServiceNow, custom apps), вызываемые перед деплоем в environment. Интегрируются через GitHub Apps.
- **Deployment Task**: GitHub Actions `deploy` job с `environment:` указывает, что задача — часть deployment.

## Архитектура и модель выполнения

### Жизненный цикл Deployment

```text
GitHub Actions (or API)
    │
    1. POST /repos/{owner}/{repo}/deployments
       { "ref": "main", "environment": "production" }
    │
    2. GitHub создаёт Deployment объект
       → Проверяет branch policy
       → Ожидает approval (если environment требует)
    │
    3. External Deploy System (CD tool)
       читает deployment → деплоит
       → POST /repos/.../deployments/{id}/statuses
       { "state": "success", "environment_url": "https://app.example.com" }
    │
    4. GitHub обновляет UI: статус deployment, activity log
```

### Environments и защита

```text
Repository
  ↓
Environment (staging / production)
  ├── Protection Rules
  │    ├── Required Reviewers (manual approval)
  │    ├── Wait Timer (delay before deploy)
  │    └── Deployment Branch Policy (only main)
  ├── Custom Protection Rules (external checks)
  ├── Secrets + Variables (scoped к environment)
  └── Deployment URL (auto-detected из environment_url)
```

## Практические сценарии

### Сценарий 1: Создание deployment через GitHub Actions

**Предварительные требования**: Environment (`production`) настроен в Settings → Environments с Manual Approval.

```yaml
jobs:
  deploy-production:
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://app.example.com  # отобразится в deployment UI
    steps:
      - uses: actions/checkout@v7
      - uses: actions/download-artifact@v8
        with:
          name: dist
          path: dist/
      - name: Deploy
        run: ./deploy.sh dist/
```

- **Механика**: при настройке `environment: production` GitHub автоматически создаёт `deployment` объект. Если environment требует Manual Approval, job переходит в статус `Waiting` и ждёт одобрения в UI.

### Сценарий 2: Управление deployment через API

```bash
# 1. Создать deployment на ветку main в production
gh api -X POST /repos/{owner}/{repo}/deployments \
  -f ref="main" \
  -f environment="production" \
  -f task="deploy" \
  -f auto_merge=true \
  -f required_contexts='["ci/tests","ci/lint"]' \
  --jq '.id,.message'

# → 123456789
# → "New deployment created."

# 2. Проверить статус deployment
gh api /repos/{owner}/{repo}/deployments/123456789/statuses \
  --jq '.[] | {state: .state, description: .description, created_at: .created_at}'

# 3. Обновить статус (успех)
gh api -X POST /repos/{owner}/{repo}/deployments/123456789/statuses \
  -f state="success" \
  -f environment="production" \
  -f environment_url="https://app.example.com" \
  -f description="Successfully deployed version 1.4.2" \
  -f log_url="https://github.com/{owner}/{repo}/actions/runs/234567890"

# 4. Обновить статус (провал)
gh api -X POST /repos/{owner}/{repo}/deployments/123456789/statuses \
  -f state="failure" \
  -f environment="production" \
  -f description="Deployment failed: health check timeout"
```

- **Валидация**: в UI репозитория → Deployments виден deployment с `Success`/`Failure` статусом; deployment status появляется в activity feed.

### Сценарий 3: Environment с Manual Approval + Branch Policy

Настройка через API:

```bash
# 1. Создать/обновить environment
gh api -X PUT /repos/{owner}/{repo}/environments/production \
  -f "wait_timer=300" \
  -f "reviewers[]=[12345678]" \  # GitHub user/team ID для manual approval
  -f "deployment_branch_policy='{ "protected_branches": true }'" \
  -f "deployment_branch_policy='{ "custom_branch_policies": true }'"

# 2. Добавить reviewer (team)
gh api -X PUT /repos/{owner}/{repo}/environments/production \
  -f "reviewers[0][type]=Team" \
  -f "reviewers[0][id]=87654321"  # Team ID

# 3. Проверить настройки
gh api /repos/{owner}/{repo}/environments/production \
  --jq '{name: .name, wait_timer: .wait_timer, reviewers: [.reviewers[].id]}'
```

Через UI: Settings → Environments → New Environment → `production` →:
- **Deployment branches**: Only selected branches → `main`
- **Required reviewers**: добавить пользователя/команду
- **Wait timer**: 5 minutes
- **Environment secrets**: `PROD_DB_PASSWORD`

### Сценарий 4: Deployment с environment-секретами

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production  # секреты environment доступны только здесь
    steps:
      - uses: actions/checkout@v7
      - uses: actions/download-artifact@v8
        with:
          name: dist
      - name: Deploy to production
        env:
          DB_PASSWORD: ${{ secrets.PROD_DB_PASSWORD }}
          API_KEY: ${{ vars.PROD_API_KEY }}  # переменная environment (не секрет)
        run: |
          # Секреты environment изолированы от остальных job
          ./deploy.sh --db-password="$DB_PASSWORD"
```

- **Важно**: секреты/переменные environment доступны **только** для шагов с `environment: production`. Они НЕ доступны, если job не привязан к environment.

### Сценарий 5: Custom Deployment Protection Rules (preview → GA)

**Предварительные требования**: GitHub App с правом `organization_adf: read` (для org-level).

```bash
# 1. Создать custom protection rule для environment
gh api -X POST /repos/{owner}/{repo}/environments/production/deployment-branch-policies \
  -f "deployment_rule"="my-custom-rule" \
  -f "reviewers[]=[12345678]"

# 2. Пример: integration с Datadog (через GitHub App)
# GitHub App получает deployment событие, вызывает Datadog API,
# возвращает ready/not-ready через deployment status
```

Для workflow, который ждёт одобрения custom rule:

```yaml
jobs:
  wait-for-custom-check:
    runs-on: ubuntu-latest
    environment:
      name: production
      # environment_url auto-detected из deployment status
    steps:
      - name: Wait for external health check
        run: |
          # Внешняя система (например, Sentry) проверяет состояние
          # и возвращает статус через deployment status API
          sleep 60  # или webhook-triggered
```

## Команды и API-операции

### Deployments API

| Операция | Endpoint | Описание |
|---|---|---|
| Создать deployment | `POST /repos/{owner}/{repo}/deployments` | Создать deployment с ref + environment |
| Список deployments | `GET /repos/{owner}/{repo}/deployments` | Список всех deployment-ов |
| Получить deployment | `GET /repos/{owner}/{repo}/deployments/{deployment_id}` | Информация о deployment |
| Список статусов | `GET /repos/{owner}/{repo}/deployments/{id}/statuses` | История статусов |
| Создать статус | `POST /repos/{owner}/{repo}/deployments/{id}/statuses` | success/failure/pending |
| Удалить deployment | `DELETE /repos/{owner}/{repo}/deployments/{id}` | Удалить deployment |

### Environments API

| Операция | Endpoint |
|---|---|
| Список environments | `GET /repos/{owner}/{repo}/environments` |
| Создать/обновить | `PUT /repos/{owner}/{repo}/environments/{env}` |
| Получить environment | `GET /repos/{owner}/{repo}/environments/{env}` |
| Удалить environment | `DELETE /repos/{owner}/{repo}/environments/{env}` |
| Список переменных | `GET /repos/{owner}/{repo}/environments/{env}/variables` |
| Список secrets | `GET /repos/{owner}/{repo}/environments/{env}/secrets` |

### CLI

```bash
# Список deployments
gh api /repos/{owner}/{repo}/deployments --jq '.[] | {id: .id, env: .environment, sha: .sha, payload: .payload}'

# Создать deployment
gh api -X POST /repos/{owner}/{repo}/deployments -f ref="main" -f environment="staging" -f task="deploy"
```

## Устранение несполадок

| Симптом | Причина | Решение |
|---|---|---|
| `Deployment status: pending` вечно | Внешняя система не отправляет `success`/`failure` | Проверить, что CD-инструмент вызывает `POST .../statuses` |
| `403` при создании deployment | Репозиторий/окружение не разрешено | Проверить branch policy; добавить `--task` и `--environment` |
| `auto_merge: false` при deployment | required_contexts не выполнены | Убедиться, что все статус-чеки в `required_contexts` прошли |
| `environment` не появляется в UI | Environment не создан в Settings | Создать environment в UI или через `PUT /environments/{env}` |
| Manual Approval не приходит | Reviewer не добавлен или не в org | Проверить `reviewers` в environment settings; reviewer должен быть member org |
| `deployment_branch_policy` блокирует | Branch policy не настроена на ветку | `gh api -X PUT /repos/{owner}/{repo}/environments/{env} -f deployment_branch_policy='{ "protected_branches": true }'` |
| Deployment не удаляется | Он связан с реальным deployment | Сначала удалить все `deployment_statuses`, потом deployment |

## Лучшие практики

1. **Deployment lifecycle в workflow, а не в ручных скриптах**: используйте `environment:` в job, а не сырой API для создания deployments.
2. **Environment для каждого уровня**: `staging`, `production`, `canary` — каждый со своими protection rules и секретами.
3. **Branch policy на production**: только `main` может деплоиться в `production`; `develop` → `staging`.
4. **Wait Timer перед production**: 5-30 минут на выявление проблем в canary/staging перед production.
5. **Manual Approval для production**: всегда требуйте approval для critical сред.
6. **Секреты scoped к environment**: никогда не используйте org-level секреты в production job без `environment:`.
7. **Deployment status с URL**: всегда отправляйте `environment_url` и `log_url` — это auto-link в UI.
8. **Auto-merge для staging**: в staging допускается auto-merge после успешного deployment, в production — только manual.

## Дополнительная информация

- **[Ключевые концепции](./Core_Concept.md)** — Environments, Manual Approvals, Deployment Branches (основы).
- **[Управление релизами](./Release_Management.md)** — публикация артефактов как часть релизного конвейера.
- **[Rulesets](./rulesets.md)** — защита веток и тегов через rulesets.
- **Официальная документация**: [Deployments API](https://docs.github.com/en/rest/deployments/deployments), [Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment).
