# Compliance и Audit в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

> **Статус:** Compliance Pipelines устарели начиная с GitLab 17.3 и будут удалены в 19.0. Для новых развёртываний используйте Pipeline Execution Policies. Существующие compliance pipelines должны быть мигрированы.

## Определения

- **Compliance в CI/CD** — соответствие нормативным требованиям (SOC 2, ISO 27001, HIPAA, PCI DSS, CIS) к процессам разработки и deployments. Обеспечивается автоматизацией проверок в пайплайнах, централизованными политиками и неизменяемым аудит-следом.

- **Audit Trail** — журнал всех действий в CI/CD пайплайне для трассируемости. Включает записи о коммитах, изменениях конфигураций, запусках пайплайнов, изменениях секретов и deployment'ах.

- **Pipeline Execution Policy** — политика GitLab (GA с 17.3) для принудительного выполнения задач в пайплайнах из отдельного security policy проекта. Определяет обязательные этапы, которые выполняются до, после или внутри проекта-цели.

- **Compliance Framework** — механизм GitLab Ultimate для маркировки проектов нормативными требованиями и автоматической проверки соответствия через controls.

- **Security Policy Project** — отдельный проект, хранящий политики безопасности и compliance, которые распространяются на целевые проекты или группы.

- **Change Management** — управление изменениями через CI/CD (approval workflows, MR templates, deployment approvals). Контролирует процесс внесения изменений с помощью требований одобрения, шаблонов и автоматических проверок.

- **Protected Environment** — среда (production, staging), доступ к которой ограничен и требует одобрения от определённых пользователей или групп перед деплоем.

- **`.pipeline-policy-pre`** — зарезервированная стадия, выполняемая перед всеми остальными задачами пайплайна. Предназначена для критических security и compliance проверок, которые нельзя пропустить.

- **`.pipeline-policy-post`** — зарезервированная стадия, выполняемая после всех остальных задач пайплайна. Используется для финальных compliance проверок.

## Теоретический блок

### Эволюция compliance enforcement в GitLab

GitLab прошла два поколения механизмов enforcement compliance в CI/CD:

1. **Compliance Pipelines** (deprecated в 17.3, removal в 19.0) — пайплайн из отдельного compliance-проекта, который полностью заменял конфигурацию `.gitlab-ci.yml` целевого проекта. Доставлялся через compliance frameworks.

2. **Pipeline Execution Policies** (GA с 17.3) — текущий механизм. Вместо полной замены пайплайна, политики внедряют дополнительные задачи в существующий пайплайн проекта или полностью его переопределяют. Предоставляют больше гибкости и единообразного подхода к enforcement.

**Почему compliance pipelines устарели:**
- Ограниченная гибкость: только полная замена пайплайна
- Конфликты с pipeline execution policies при совместной настройке
- Сложность миграции и поддержки
- Отсутствие резервированных стадий для гарантированного выполнения

### Требования к Compliance в CI/CD

| Стандарт | Основные требования к CI/CD |
|----------|----------------------------|
| **SOC 2** | Контроль доступа, аудит действий, change management, разделение обязанностей |
| **ISO 27001** | Управление изменениями, непрерывность процессов, документирование |
| **HIPAA** | Защита данных (PHI), шифрование, аудит доступа, регулярные проверки |
| **PCI DSS v4.0.1** | Контроль изменений, тестирование безопасности, мониторинг доступа, retention логов ≥1 года |
| **EU CRA** | SBOM для каждого релиза, отчеты об уязвимостях, retention 1 год после вывода |
| **FedRAMP / IRAP** | Централизованный контроль, MFA, разделение сред, аудит всех действий |

### Архитектура Pipeline Execution Policies

Pipeline Execution Policies управляются из security policy проекта и применяются к целевым проектам через:

- **Group-level policies** — применяются ко всем проектам группы (или подмножеству через `policy_scope`)
- **Project-level policies** — применяются к отдельному проекту
- **Compliance Framework scoping** — policies могут быть привязаны к compliance framework labels

**Стратегии внедрения (`pipeline_config_strategy`):**

| Стратегия | Поведение | Применение |
|-----------|-----------|------------|
| `inject_policy` | Внедряет задачи политики в существующий пайплайн проекта через резервированные стадии `.pipeline-policy-pre` и `.pipeline-policy-post`, а также стандартные стадии | Рекомендуется для большинства случаев. Не нарушает пайплайн проекта |
| `inject_ci` | Устаревшая стратегия. Добавляет конфигурацию CI в пайплайн проекта | Не использовать в новых развёртываниях |
| `override_project_ci` | Полностью заменяет `.gitlab-ci.yml` проекта конфигурацией политики | Для жёсткого enforcement в high-compliance средах |

**Порядок выполнения при `inject_policy`:**
1. Выполняются задачи из `.pipeline-policy-pre` (всегда, нельзя пропустить через `[skip ci]`)
2. Выполняются задачи проекта-цели
3. Выполняются задачи из `.pipeline-policy-post`

### Compliance Frameworks и Controls

Compliance Frameworks (GitLab Ultimate) позволяют:
- Маркировать проекты compliance labels
- Назначать requirements, состоящие из controls
- Автоматически проверять соответствие через встроенные и external controls
- Централизованно управлять frameworks через Compliance and Security Policy (CSP) group (GA в 18.6)

**Встроенные controls** включают проверки:
- `protected_branches_set` — защищённые ветки настроены
- `default_branch_protected` — защита ветки по умолчанию
- `minimum_approvals_required_1/2` — минимальное количество одобрений
- `merge_request_prevent_committers_approval` — запрет approval коммиттерами
- `project_pipelines_not_public` — пайплайны не публичны
- `require_mfa_at_org_level` / `require_mfa_for_contributors` — MFA
- Сканеры безопасности: `scanner_sast_running`, `scanner_dast_running`, `scanner_dependency_scanning_running`, `scanner_secret_detection_running`, `scanner_license_compliance_running`
- `user_defined_cicd_variables_restricted_to_maintainers` — переменные только для maintainers

### Merge Request Approval Rules для compliance

GitLab предоставляет несколько уровней контроля approval:

- **Approval rules** — минимальное количество одобрений, назначение групп/пользователей
- **Code Owner approval** — автоматическое назначение ревьюеров из `CODEOWNERS`
- **Approval settings** — `Prevent approval by merge request creator`, `Prevent approvals by committers`, `Require user re-authentication (password or SAML)` для electronic signature (CFR Part 11)
- **Merge request approval policies** — security approvals на основе статуса vulnerabilities в MR

### Audit Events

GitLab фиксирует audit events на трёх уровнях:
- **Instance-level** — события всего инстанса (только администраторы)
- **Group-level** — события группы
- **Project-level** — события проекта

**Доступные через REST API v4:**
- `GET /api/v4/audit_events` — instance events (Admin only)
- `GET /api/v4/groups/:id/audit_events` — group events
- `GET /api/v4/projects/:id/audit_events` — project events

Query параметры: `created_after`, `created_before` (максимальный диапазон 30 дней за запрос), `entity_type`, `entity_id`.

### Tracing от кода до production

Полная трассируемость достигается через:

- **Commit SHA** — уникальный идентификатор коммита в каждом артефакте и образе
- **Container Registry** — привязка образов к коммитам через теги `$CI_COMMIT_SHA`
- **Package Registry** — версионирование пакетов с привязкой к коммитам
- **SBOM** — автоматическое создание Software Bill of Materials в CI/CD
- **DORA metrics** — метрики для отслеживания циклов доставки

## Практический блок

### Предварительные требования

| Компонент | Требование |
|-----------|------------|
| GitLab лицензия | Ultimate для Compliance Frameworks и centralized compliance. Pipeline Execution Policies доступны в Premium и Ultimate |
| Версия GitLab | 17.3+ для Pipeline Execution Policies (GA). 18.6+ для centralized compliance frameworks |
| Роли | Owner или Security Manager для создания compliance frameworks. Maintainer для protected environments и deployment approvals |
| Security Policy Project | Отдельный проект для хранения pipeline execution policies |

### Настройка Pipeline Execution Policy

```yaml
# security-policy-project/.gitlab/ci/pipeline-config.yml
# Этот файл хранится в security policy проекте и внедряется в целевые пайплайны

stages:
  - .pipeline-policy-pre
  - test
  - build
  - deploy
  - .pipeline-policy-post

enforced_security_scan:
  stage: .pipeline-policy-pre
  image: registry.example.com/security/scanner:latest
  script:
    - echo "Running enforced security scan..."
    - trivy fs --security-checks vuln,secret,config .
    - semgrep scan --config p/security-audit .
  rules:
    - when: always
  allow_failure: false

enforced_compliance_check:
  stage: .pipeline-policy-post
  image: registry.example.com/compliance/checker:latest
  script:
    - echo "Running enforced compliance check..."
    - validate-licenses
    - check-software-bill
    - verify-access-controls
  rules:
    - when: always
  allow_failure: false
```

**Создание политики:**
1. Перейдите в **Secure > Policies** в security policy проекте
2. Выберите **Pipeline execution policy**
3. Укажите имя, описание и статус (`enabled: true`)
4. В `pipeline_config_strategy` выберите `inject_policy`
5. В `content` укажите проект и файл с конфигурацией
6. В `policy_scope` определите целевые проекты/группы/compliance framework labels
7. Установите `skip_ci: allowed: false` для предотвращения обхода

**Валидация:**
```bash
# После создания MR с политикой проверьте пайплайн целевого проекта:
# - Задачи enforced_security_scan и enforced_compliance_check должны присутствовать
# - Задачи в .pipeline-policy-pre выполняются первыми
# - Попытка пропустить пайплайн через [skip ci] не влияет на политики
```

### Compliance Framework с controls

```yaml
# Создание framework через UI: Secure > Compliance center > Frameworks > New framework
# Или через API:

curl --request POST \
  --header "PRIVATE-TOKEN: <token>" \
  --header "Content-Type: application/json" \
  --data '{
    "name": "SOC2 Framework",
    "description": "SOC 2 Type II compliance requirements",
    "color": "#E01E5A",
    "compliance_requirement_attributes": {
      "requirements": [
        {
          "name": "Access Control",
          "controls": [
            { "control_type": "gitlab", "control_id": "require_mfa_at_org_level" },
            { "control_type": "gitlab", "control_id": "protected_branches_set" },
            { "control_type": "gitlab", "control_id": "minimum_approvals_required_2" }
          ]
        },
        {
          "name": "Pipeline Security",
          "controls": [
            { "control_type": "gitlab", "control_id": "scanner_sast_running" },
            { "control_type": "gitlab", "control_id": "scanner_dependency_scanning_running" },
            { "control_type": "gitlab", "control_id": "scanner_secret_detection_running" }
          ]
        }
      ]
    }
  }' \
  "https://gitlab.example.com/api/v4/groups/:group_id/compliance_frameworks"
```

### Merge Request templates для compliance

```
<!-- .gitlab/merge_request_templates/Compliance.md -->

## Описание изменения
<!-- Краткое описание что изменено и зачем -->

## Тип изменения
- [ ] Feature
- [ ] Bugfix
- [ ] Refactoring
- [ ] Configuration change
- [ ] Security patch

## Compliance проверки
- [ ] Добавлены/обновлены тесты
- [ ] Пройдены все automated checks (SAST, DAST, dependency scanning)
- [ ] Обновлена документация
- [ ] Проверены лицензии зависимостей
- [ ] Выполнена security scanning
- [ ] Secret detection: новых секретов нет

## Одобрения
<!-- Список необходимых одобрений -->
- [ ] Code Owner approval
- [ ] Security Champion approval
- [ ] Compliance team approval (если применимо)
```

### Audit Events через REST API

```bash
# Получение событий аудита для проекта (Maintainer+)
curl --request GET \
  --header "PRIVATE-TOKEN: <access_token>" \
  "https://gitlab.example.com/api/v4/projects/:id/audit_events"

# Фильтрация по дате (максимальный диапазон 30 дней)
curl --header "PRIVATE-TOKEN: <access_token>" \
  "https://gitlab.example.com/api/v4/projects/:id/audit_events?created_after=2026-01-01T00:00:00Z&created_before=2026-01-31T00:00:00Z"

# Фильтрация по типу сущности
curl --header "PRIVATE-TOKEN: <access_token>" \
  "https://gitlab.example.com/api/v4/projects/:id/audit_events?entity_type=Project"

# Пагинация: по умолчанию возвращается 20 результатов на страницу
# Используйте параметры page и per_page для навигации
```

### Tracing артефактов

```yaml
# В CI/CD конфигурации добавляем информацию о трассировке
build:
  stage: build
  script:
    - echo "Building application..."
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  variables:
    DOCKER_BUILDKIT: 1

deploy_production:
  stage: deploy
  script:
    - echo "Deploying commit $CI_COMMIT_SHA to production"
    - kubectl set image deployment/app app=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
  needs: [build]
```

### Protected Environments с deployment approvals

Protected Environments и Deployment Approvals настраиваются в UI проекта. Подробная конфигурация описана в [Окружения и развертывания в GitLab CI/CD](../Concepts/environments_and_deployments.md).

**Минимальные требования для production:**
- **Allowed to deploy:** Maintainers only
- **Approval rules:** минимум 2 одобрения от группы Release Managers
- **Deploy access:** только для `main` ветки
- **Allow pipeline triggerer to approve:** отключено (запрет self-approval)

## Устранение неисправностей

| Проблема | Причина | Решение |
|----------|---------|---------|
| `Deployment approval pending` | Не настроены Approval Policies для protected environment | Настройте deployment approvals в Settings > CI/CD > Protected environments |
| `Deployment approval wait time` слишком высокий | Неправильно настроен SLA или approvers недоступны | Настройте escalation policies и reserve approvers |
| `Pipeline execution policy error: Job names must be unique` | Дублирование имён задач между проектом и политикой | Убедитесь что имена задач в политике уникальны; начиная с GitLab 17.4 конфликты обрабатываются автоматически через суффиксы |
| `Pipeline execution policies cannot be skipped` | Разработчик пытается использовать `[skip ci]` | Это ожидаемое поведение: политики игнорируют `[skip ci]` для гарантии выполнения |
| `Access denied to policy CI/CD configuration` | У пользователя нет прав на чтение security policy проекта | Настройте `Pipeline execution policies` доступ в общих настройках security policy проекта (GitLab 17.4+) или предоставьте права вручную |
| Compliance controls не проходят | Проект не соответствует требованиям framework | Проверьте конкретный control через Compliance center > Frameworks > [framework] > Projects |
| `Audit events query returns empty` | Превышен лимит 30 дней или нет прав | Уменьшите диапазон дат; для instance audit events требуются права администратора |

## Ограничения и крайние случаи

- **Compliance Pipelines и Pipeline Execution Policies не должны использоваться одновременно** в одном проекте. Это создаёт непредсказуемое поведение: duplicated jobs, pipeline failures, missing checks.
- **Максимум 5 политик** (`pipeline_execution_policy`) на security policy проект. Дополнительные политики игнорируются.
- **Доступ к security policy проекту:** пользователь, запускающий пайплайн, должен иметь хотя бы read-only доступ к проекту с политикой. В GitLab 17.4+ это можно включить автоматически через настройку security policy проекта.
- **Merge request pipelines:** некоторые `workflow:rules` в проекте могут предотвратить выполнение политик в MR пайплайнах. Используйте `workflow: rules` в политике для контроля enforcement.
- **Reserved stages:** только политики могут использовать `.pipeline-policy-pre` и `.pipeline-policy-post`. В обычном `.gitlab-ci.yml` этих стадий использовать нельзя.
- **Variables precedence:** переменные pipeline execution policies имеют наивысший приоритет и не могут быть переопределены из проекта или других политик.
- **Dangling pipeline sources:** политики не внедряются в пайплайны с источниками `webide`, `parent_pipeline`, `ondemand_dast_scan`, `ondemand_dast_validation`, `security_orchestration_policy`, `container_registry_push`.
- **External controls:** пребывают в состоянии `pending` максимум 6 часов; после этого control считается failed.
- **Centralized compliance frameworks:** доступны только в GitLab Self-Managed Ultimate; на GitLab.com не поддерживаются.

## Лучшие практики

### Enforcement
- Используйте `.pipeline-policy-pre` для критических security и compliance проверок, которые не могут быть пропущены
- Устанавливайте `skip_ci: allowed: false` для предотвращения обхода политик
- Применяйте `inject_policy` вместо `inject_ci` для новых развёртываний
- Используйте `override_project_ci` только для высокорегулируемых сред, где требуется полный контроль пайплайна

### Separation of Duties
- Разделяйте роли: security team управляет политиками, development team управляет кодом
- Настройте approval rules с предотвращением self-approval (`Prevent approval by merge request creator`)
- Включите `Require user re-authentication` для approval в high-compliance средах (CFR Part 11)
- Используйте CODEOWNERS для автоматического назначения compliance approvers

### Monitoring и Evidence
- Централизуйте audit events в SIEM (Elastic, VictoriaMetrics, Wazuh)
- Настройте retention согласно регуляторным требованиям: PCI DSS — 1 год (3 месяца hot storage), HIPAA — 6 лет
- Регулярно ревьюируйте compliance controls отчеты
- Настройте алерты на невыполнение compliance controls и отклонение от baseline

### Migration
- Мигрируйте compliance pipelines → pipeline execution policies до GitLab 19.0
- Используйте инструмент миграции в UI: Secure > Compliance center > Frameworks > Edit > Migrate pipeline to policy
- После миграции удалите старые `.compliance-gitlab-ci.yml` файлы

## Дополнительная информация

### Связанные темы

- [CI/CD Security Hardening](../Advanced/cicd_security_hardening.md) — общее укрепление безопасности пайплайнов
- [Окружения и развертывания в GitLab CI/CD](../Concepts/environments_and_deployments.md) — Protected Environments и Deployment Approvals
- [Audit & Compliance Overview](../../../Security/audit_and_compliance_overview.md) — общие концепции аудита и комплаенса
- [Secrets Management в Vault](../../../Vault/guides/audit_log_analysis.md) — анализ audit логов Vault
- [Release Management](../../../CI-CD/mobile-ci-cd/release-management-mobile.md) — audit trail для релизов

### Чек-лист compliance

**Enforcement:**
- [ ] Compliance Pipelines мигрированы на Pipeline Execution Policies
- [ ] Настроены Pipeline Execution Policies с `inject_policy` стратегией
- [ ] Используются `.pipeline-policy-pre` и `.pipeline-policy-post` для критических проверок
- [ ] `skip_ci` отключён для политик
- [ ] Настроены Compliance Frameworks с controls (Ultimate)
- [ ] Настроены approval rules: минимум 2 одобрения, prevent self-approval

**Защита окружений:**
- [ ] Production environment protected
- [ ] Deployment approvals включены
- [ ] Разделение ролей: deploy access ≠ merge access

**Аудит:**
- [ ] Audit events включены на instance/group/project уровнях
- [ ] Логи централизованы в SIEM
- [ ] Настроен retention согласно регуляторным требованиям
- [ ] Регулярно проводятся compliance audits

**Безопасность:**
- [ ] SAST, DAST, dependency scanning, secret detection включены
- [ ] SBOM генерируется для каждого артефакта
- [ ] Секреты в CI/CD variables (masked + protected)
- [ ] MFA включён на organisation уровне
