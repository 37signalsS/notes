# Merge Request Approval Rules в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.4.x

> **Примечание:** Полная теория approval workflows, CODEOWNERS и merge request approvals описана в официальной документации GitLab: **[Merge Request Approvals — официальная документация](https://docs.gitlab.com/user/project/merge_requests/approvals/)**. Это руководство фокусируется на практической настройке multi-level approval workflows для compliance и code quality.

## Определения

| Термин | Описание |
|:---|:---|
| **Approval Rule** | Правило, определяющее минимальное количество одобрений и категорию approvers (пользователи или группы), необходимых для merge MR. |
| **CODEOWNERS** | Файл в репозитории, автоматически назначающий ответственных за директории/файлы. GitLab использует его для автоматического добавления approvers в MR. |
| **Code Owner Approval** | Автоматическое назначение ревьюеров из `CODEOWNERS`. Требует, чтобы пользователь/группа были прямыми членами проекта или его группы. |
| **Approval Settings** | Проектные настройки: `Prevent approval by merge request creator`, `Prevent approvals by committers`, `Require user re-authentication`. |
| **Compliance Framework** | Механизм GitLab Ultimate для маркировки проектов нормативными требованиями и автоматической проверки соответствия через controls. |
| **Deployment Approval** | Ручное одобрение перед деплоем в protected environment. Отличается от MR approval: контролирует момент выкатки, а не момент слияния. |
| **External Approval** | Интеграция с внешней системой (ServiceNow, Jira) для получения approval вне интерфейса GitLab. |
| **Pipeline Approval** | Встроенная задача с `when: manual`, блокирующая пайплайн до ручного нажатия. |
| **Override** | Возможность для пользователей с elevated правами (Owner) временно отменить approval rules для emergency deploy. |

## Как работает Approval Pipeline

Жизненный цикл approval в GitLab состоит из нескольких уровней контроля, которые могут комбинироваться:

1. **Project-level approval rules** — базовые правила, определяющие количество и категорию approvers.
2. **CODEOWNERS** — автоматическое добавление approvers на основе изменённых файлов.
3. **Approval settings** — глобальные флаги проекта, ограничивающие self-approval и committer approval.
4. **Compliance Framework** (Ultimate) — автоматическое применение approval rules на основе нормативных требований.
5. **Protected Environment approvals** — ручное одобрение перед деплоем в production/staging.
6. **External status checks** — интеграция с внешними системами через API.

### Ключевые ограничения

- **Approval rules не отменяются автоматически при новых коммитах** (если не включено `Remove approvals by Code Owners if their files changed` или `Remove all approvals`).
- **CODEOWNERS обновляется только при создании MR.** Изменения в `CODEOWNERS` требуют создания нового MR.
- **Maximum approval rules:** рекомендуется не превышать 5 правил на MR для сохранения читаемости.
- **Group approval rules** доступны только на Self-Managed с включённым feature flag `approval_group_rules`; на GitLab.com не поддерживаются.
- **External Project-level MR approvals** работают только на Self-Managed Ultimate с включённым feature flag; по умолчанию отключены и не рекомендуются для production.

## Предварительные требования

### Обязательные

- GitLab проект с лицензией **Premium** или **Ultimate** (для required approval rules). На Free tier approval rules доступны, но не являются required.
- Роль **Maintainer** или **Owner** для настройки approval rules и approval settings.
- Файл `CODEOWNERS` (опционально, но рекомендуется) в корне репозитория или в `.gitlab/CODEOWNERS`.
- Для External Approval Integration: Self-Managed Ultimate с администраторским доступом для включения feature flags.

### Для Compliance Frameworks

- Лицензия **GitLab Ultimate**.
- Compliance Framework настроен на уровне группы (`Settings > Compliance > Compliance Framework`).
- Роль **Owner** или **Security Manager** для создания frameworks.

### Для Protected Environment Approvals

- Protected environment настроен (`Settings > CI/CD > Protected environments`).
- Deployment approval policy включена.
- Роль **Maintainer** для настройки allowed deployers.

## Практические сценарии

### Сценарий 1: Multi-level Approval Rules для SOC 2

```yaml
# .gitlab-ci.yml
stages:
  - test
  - security
  - deploy

include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml

variables:
  SECURITY_SCAN_ENABLED: "true"

sast:
  stage: security
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

secret_detection:
  stage: security
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: false

deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Настройка в UI (Settings > Merge requests > Approval rules):**

1. **Rule 1: Code Review**
   - Name: `Code Review`
   - Approvals required: 1
   - Allowed approvers: Developers, Maintainers
   - Prevent approval by author: Yes

2. **Rule 2: Security Review**
   - Name: `Security Review`
   - Approvals required: 1
   - Allowed approvers: Security team
   - Prevent approval by author: Yes

3. **Rule 3: Compliance Review**
   - Name: `Compliance Review`
   - Approvals required: 1
   - Allowed approvers: Compliance team, Engineering manager
   - Prevent approval by author: Yes

**CODEOWNERS:**
```
# CODEOWNERS
/security/ @security-team
/infrastructure/ @platform-team
/src/api/ @backend-team
/src/frontend/ @frontend-team
```

### Сценарий 2: CODEOWNERS с автоматическими approvers

```
# CODEOWNERS
# Обязательный ревью от security-team для всех security файлов
/security/ @security-team

# Обязательный ревью от platform-team для инфраструктуры
/infrastructure/ @platform-team
/terraform/ @platform-team
/kubernetes/ @platform-team

# Обязательный ревью от backend-team для API
/src/api/ @backend-team
/**/*.py @backend-team

# Обязательный ревью от frontend-team для UI
/src/frontend/ @frontend-team
/**/*.jsx @frontend-team
/**/*.tsx @frontend-team

# Обязательный ревью от devops для CI/CD
/.gitlab-ci.yml @devops-team
/gitlab/ @devops-team

# Обязательный ревью от QA для тестов
/tests/ @qa-team
/test/ @qa-team
```

### Сценарий 3: Compliance Approval на уровне группы (GitLab 18.0+)

```yaml
# В группе с enabled Compliance Framework
# Settings > Compliance > Compliance Framework

# Compliance Approval Rule применяется автоматически
# Настройка в UI:
# - Framework: SOC 2
# - Required approvals: 2
# - Allowed approvers: Compliance team, Engineering manager
```

### Сценарий 4: Pipeline Approval для Production Deploy

```yaml
stages:
  - test
  - security
  - approval
  - deploy

approval_production:
  stage: approval
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  environment:
    name: production
    url: https://example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

### Сценарий 5: External Approval (ServiceNow)

```yaml
stages:
  - test
  - approval
  - deploy

approval_servicenow:
  stage: approval
  image: curlimages/curl:8.8.0
  script:
    - |
      # Создание change request в ServiceNow
      curl -X POST "https://servicenow.example.com/api/now/table/change_request" \
        -H "Authorization: Basic $SN_AUTH" \
        -H "Content-Type: application/json" \
        -d '{
          "short_description": "Deploy to production: $CI_COMMIT_MESSAGE",
          "description": "Pipeline: $CI_PIPELINE_URL\nBranch: $CI_COMMIT_BRANCH\nCommit: $CI_COMMIT_SHORT_SHA",
          "urgency": "2",
          "impact": "2"
        }'
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Примечание:** Нативный External Project-level MR approvals API доступен только на Self-Managed Ultimate с включённым feature flag и не рекомендуется для production. Для production-сред используйте External Status Checks или pipeline-level approval jobs с интеграцией через REST API.

### Сценарий 6: Multiple Approval Rules с override

```yaml
# Настройка в UI:
# Rule 1: Code Review (1 approval from Developers)
# Rule 2: Security Review (1 approval from Security team)
# Rule 3: Compliance Review (1 approval from Engineering manager)

# Emergency override для hotfix
hotfix_approval_override:
  stage: approval
  image: curlimages/curl:8.8.0
  script:
    - |
      # Временный override approval rules для emergency deploy
      curl --request POST --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/approvals" \
        -d '{
          "override": true,
          "reason": "Emergency hotfix for production incident",
          "user_id": $APPROVER_ID
        }'
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^hotfix\//
      allow_failure: false
```

## Валидация и проверка

1. **MR UI:** Попробуйте merge MR без approval — должен быть блокирован
2. **Code Owners:** Проверьте, что approvers автоматически добавляются на основе CODEOWNERS
3. **Compliance Framework:** Проверьте compliance dashboard — должны отображаться все MR с compliance requirements
4. **External Approval:** Проверьте, что ServiceNow/Jira integration работает
5. **Override:** Попробуйте override approval rules — должен потребоваться token с elevated правами

## Ограничения и крайние случаи

- **CODEOWNERS обновляется только при создании MR.** Если вы изменили `CODEOWNERS`, существующий MR не подхватит изменения — закройте и создайте новый MR.
- **Remove approvals by Code Owners if their files changed** (introduced in GitLab 15.3): убирает approval только у тех Code Owners, чьи файлы были изменены в новом коммите. Для работы требуется `reset_approvals_on_push: false`.
- **Group approval rules** не доступны на GitLab.com; только Self-Managed с feature flag `approval_group_rules`.
- **External Project-level MR approvals** работают только на Self-Managed Ultimate с включённым feature flag; по умолчанию отключены.
- **Approval rules не отменяются автоматически** при push, если не включено одно из настроек сброса approvals.
- **Maximum approval rules:** рекомендуется не превышать 5 правил на MR.
- **Self-approval prevention:** настройка `Prevent approval by merge request creator` работает на уровне проекта и не может быть переопределена на уровне MR (если не разрешено override).

## Troubleshooting

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **MR not blocked** | Approval rules не настроены | Проверьте настройки в **Settings > Merge requests** |
| **Code owners not added** | CODEOWNERS не найден или синтаксис неверен | Проверьте файл `.gitlab/CODEOWNERS` или `CODEOWNERS` в корне |
| **Approval by author allowed** | Флаг `Prevent approval by merge request creator` отключен | Включите флаг в настройках approval rule |
| **External approval not working** | Интеграция не настроена | Проверьте настройки ServiceNow/Jira integration |
| **Compliance rule not applied** | Compliance Framework не enabled | Включите Compliance Framework в **Settings > Compliance** |
| **Override not working** | Нет прав на override | Проверьте права пользователя — требуется Owner/Maintainer |
| **Too many approvals required** | Правило настроено слишком строго | Уменьшите количество required approvals |
| **Code owner approval not removed after push** | Не включено `Remove approvals by Code Owners if their files changed` или `reset_approvals_on_push` конфликтует | Настройте `reset_approvals_on_push: false` и включите selective removal |

## Лучшие практики (Best Practices)

**Безопасность:**
- Используйте `Prevent approval by merge request creator: Yes` для всех compliance-critical проектов
- Включите `Remove approvals by Code Owners if their files changed` (GitLab 15.3+) для автоматического сброса устаревших approvals
- Используйте External Status Checks или pipeline-level approvals для regulated сред
- Ограничьте права на override только Owners
- Включите audit logging для всех approval действий

**Производительность:**
- Используйте CODEOWNERS для автоматического назначения approvers
- Настройте `rules:changes` для запуска approval только при изменении релевантных файлов
- Ограничьте количество approval rules (максимум 5 на MR)
- Используйте `allow_failure: false` для compliance проверок

**Надёжность:**
- Документируйте все approval rules в README
- Используйте version control для CODEOWNERS
- Настройте алерты на MR, ожидающие approval >24 часа
- Используйте Scheduled Pipeline для регулярного аудита approval rules
- Интегрируйте с Slack/Teams для уведомлений о pending approvals

## Очистка

```bash
# Очистка устаревших approval rules
curl --request GET --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/approval_rules" | \
  jq -r '.[] | select(.created_at < "'$(date -d '90 days ago' -I)'") | .id' | \
  xargs -I {} curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/approval_rules/{}"
```

**Примечание:** Требует установленного и аутентифицированного GitLab CLI (`glab`) или токена с правами Maintainer/Owner.

## Дополнительная информация

### Смотрите также

- **[Merge Request Approvals — официальная документация](https://docs.gitlab.com/user/project/merge_requests/approvals/)** — теория, CODEOWNERS, approvals
- **[Compliance и Audit](../Advanced/compliance_and_audit.md)** — compliance frameworks и policies
- **[Merge Trains](../Advanced/gitlab_ci_advanced_workflow.md)** — параллельные merges
- **[Окружения и развертывания в GitLab CI/CD](../Concepts/environments_and_deployments.md)** — Protected Environments и Deployment Approvals
