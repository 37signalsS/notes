# Compliance и Audit в GitLab CI/CD — глубинное погружение

**Актуально для:** GitLab 17.x–19.x

> **Примечание:** Полная теория compliance frameworks, audit events и security policies описана в **[Compliance и Audit в GitLab CI](../Advanced/compliance_and_audit.md)**. Это руководство фокусируется на практической настройке compliance-first пайплайнов для regulated сред (SOC 2, ISO 27001, PCI-DSS).

## Определения

- **Compliance в CI/CD** — соответствие нормативным требованиям (SOC 2, ISO 27001, HIPAA, PCI DSS, CIS) к процессам разработки и deployments. Обеспечивается автоматизацией проверок в пайплайнах, централизованными политиками и неизменяемым аудит-следом.

- **Audit Trail** — журнал всех действий в CI/CD пайплайне для трассируемости. Включает записи о коммитах, изменениях конфигураций, запусках пайплайнов, изменениях секретов и deployment'ах.

- **Pipeline Execution Policy** — политика GitLab (GA с 17.3) для принудительного выполнения задач в пайплайнах из отдельного security policy проекта. Определяет обязательные этапы, которые выполняются до, после или внутри проекта-цели.

- **Scan Execution Policy** — политика для принудительного запуска встроенных сканеров безопасности (SAST, DAST, Dependency Scanning, Secret Detection, License Scanning) на основе правил. В отличие от Pipeline Execution Policies, не требует написания пользовательских CI/CD задач и работает напрямую с шаблонами сканеров.

- **Security Policy Project** — отдельный проект, хранящий политики безопасности и compliance, которые распространяются на целевые проекты или группы.

- **Compliance Framework** — механизм GitLab Ultimate для маркировки проектов нормативными требованиями и автоматической проверки соответствия через controls.

- **Protected Environment** — среда (production, staging), доступ к которой ограничен и требует одобрения от определённых пользователей или групп перед деплоем.

- **`.pipeline-policy-pre`** — зарезервированная стадия, выполняемая перед всеми остальными задачами пайплайна. Предназначена для критических security и compliance проверок, которые нельзя пропустить.

- **`.pipeline-policy-post`** — зарезервированная стадия, выполняемая после всех остальных задач пайплайна. Используется для финальных compliance проверок.

## Базовая концепция и архитектура

### Эволюция enforcement compliance в GitLab

GitLab прошла два поколения механизмов enforcement compliance в CI/CD:

1. **Compliance Pipelines** (deprecated в 17.3, removal в 19.0) — пайплайн из отдельного compliance-проекта, который полностью заменял конфигурацию `.gitlab-ci.yml` целевого проекта. Доставлялся через compliance frameworks.

2. **Pipeline Execution Policies** (GA с 17.3) — текущий механизм. Вместо полной замены пайплайна, политики внедряют дополнительные задачи в существующий пайплайн проекта или полностью его переопределяют. Предоставляют больше гибкости и единообразного подхода к enforcement.

**Почему compliance pipelines устарели:**
- Ограниченная гибкость: только полная замена пайплайна
- Конфликты с pipeline execution policies при совместной настройке
- Сложность миграции и поддержки
- Отсутствие резервированных стадий для гарантированного выполнения

### Архитектура политик

Все политики безопасности и compliance хранятся в security policy проекте в файле `.gitlab/security-policies/policy.yml`. GitLab поддерживает следующие типы политик:

| Тип политики | Назначение | Гибкость |
|---|---|---|
| **Pipeline Execution Policy** | Внедряет пользовательские CI/CD задачи в целевые пайплайны через `.pipeline-policy-pre` / `.pipeline-policy-post` или стандартные стадии | Высокая — произвольные скрипты, образы, зависимости |
| **Scan Execution Policy** | Принудительно запускает встроенные сканеры безопасности (SAST, DAST, Secret Detection и др.) без написания пользовательского CI | Средняя — ограничена шаблонами GitLab |
| **Approval Policy** (Merge Request) | Требует approval для MR на основе результатов сканирования или уязвимостей | Специализированная — только для MR |
| **Scheduled Pipeline Execution Policy** (Beta) | Запускает пайплайн политики по расписанию независимо от коммитов | Средняя — для регулярного compliance аудита |

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

**Scope политик:**
- **Group-level policies** — применяются ко всем проектам группы (или подмножеству через `policy_scope`)
- **Project-level policies** — применяются к отдельному проекту
- **Compliance Framework scoping** — policies могут быть привязаны к compliance framework labels

### Tracing от кода до production

Полная трассируемость достигается через:
- **Commit SHA** — уникальный идентификатор коммита в каждом артефакте и образе
- **Container Registry** — привязка образов к коммитам через теги `$CI_COMMIT_SHA`
- **Package Registry** — версионирование пакетов с привязкой к коммитам
- **SBOM** — автоматическое создание Software Bill of Materials в CI/CD
- **DORA metrics** — метрики для отслеживания циклов доставки

## Предварительные требования

| Компонент | Требование |
|-----------|------------|
| GitLab лицензия | **Ultimate** для Compliance Frameworks, centralized compliance и Audit Events. Pipeline Execution Policies и Scan Execution Policies доступны в **Premium** и Ultimate. |
| Версия GitLab | **17.3+** для Pipeline Execution Policies (GA). **18.6+** для centralized compliance frameworks. **18.10+** для гарантированного выполнения `.pipeline-policy-pre` перед остальными стадиями. **19.0+** для нового pipeline execution (GA). |
| Роли | **Owner** или **Security Manager** для создания compliance frameworks и link security policy проекта. **Maintainer** для настройки protected environments, deployment approvals и изменения политик. |
| Security Policy Project | Отдельный проект для хранения `.gitlab/security-policies/policy.yml`. Целевые проекты/группы должны быть связаны с этим проектом. |
| Доступ к политикам | Пользователь, запускающий пайплайн, должен иметь хотя бы read-only доступ к security policy проекту (в GitLab 17.4+ это можно включить автоматически). |
| Сеть | Для Self-Managed: доступность security policy проекта от Runner'ов. При air-gapped окружениях требуется локальный registry для шаблонов сканеров. |

## Практические сценарии

### Сценарий 1: Pipeline Execution Policy для SOC 2

Pipeline Execution Policy внедряет обязательные security задачи в пайплайн целевого проекта. В этом примере политика inject'ит SAST, Dependency Scanning и Secret Detection во все MR-пайплайны.

**Шаг 1.** Создайте файл политики в security policy проекте:

```yaml
# security-policy-project/.gitlab/security-policies/policy.yml
pipeline_execution_policy:
  - name: "Mandatory security scanning for SOC 2"
    description: "Enforce SAST, Dependency Scanning, and Secret Detection on merge requests"
    enabled: true
    pipeline_config_strategy: inject_policy
    content:
      include:
        - template: Security/SAST.gitlab-ci.yml
        - template: Security/Dependency-Scanning.gitlab-ci.yml
        - template: Security/Secret-Detection.gitlab-ci.yml
    policy_scope:
      projects:
        including:
          - id: 123 # ID целевого проекта
```

**Шаг 2.** Создайте MR с изменениями в security policy проекте и смерджите его.

**Шаг 3.** В целевом проекте проверьте пайплайн — должны появиться задачи `sast`, `dependency_scanning`, `secret_detection`.

**Важно:** Включите `AST_ENABLE_MR_PIPELINES: "true"` в целевом проекте, чтобы сканеры запускались в merge request пайплайнах (GitLab 18.0+).

### Сценарий 2: Scan Execution Policy для PCI-DSS

Scan Execution Policy принудительно запускает сканеры безопасности без написания пользовательских CI задач. В этом примере политика запускает SAST и Dependency Scanning для всех релизных веток.

```yaml
# security-policy-project/.gitlab/security-policies/policy.yml
scan_execution_policy:
  - name: "PCI-DSS release branch scanning"
    description: "Enforce SAST and dependency scanning on release branches for PCI-DSS"
    enabled: true
    rules:
      - type: pipeline
        branches:
          - release/*
    actions:
      - scan: sast
      - scan: dependency_scanning
      - scan: license_scanning
    policy_scope:
      compliance_frameworks:
        - id: 2 # ID PCI-DSS compliance framework
```

### Сценарий 3: Deployment Approvals для Production

Protected Environment с deployment approvals гарантирует, что деплой в production требует ручного одобрения. В отличие от merge request approvals, deployment approvals контролируют момент выкатки, а не момент слияния кода.

**Настройка через UI:**
1. **Settings > CI/CD > Protected environments**
2. Выберите `production`
3. **Allowed to deploy:** Maintainers only
4. **Required approvals:** 2
5. **Allow pipeline triggerer to approve:** No (запрет self-approval)

**Настройка через REST API (Self-Managed / автоматизация):**

```bash
curl --request PUT \
  --header "PRIVATE-TOKEN: <access_token>" \
  --header "Content-Type: application/json" \
  --data '{
    "name": "production",
    "protected": true,
    "required_approval_count": 2,
    "allow_pipeline_triggerer_to_approve": false
  }' \
  "https://gitlab.example.com/api/v4/projects/:id/protected_environments"
```

### Сценарий 4: Merge Request Approval Rules для compliance

Approval rules на уровне проекта дополняют политики, требуюing ручного ревью от security team перед слиянием.

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

**Настройка в UI:**
1. **Settings > Merge requests > Approval rules**
2. Создайте правило:
   - **Name:** `Compliance: Security Review`
   - **Approvals required:** 2
   - **Allowed approvers:** Security team, Engineering manager
   - **Prevent approval by author:** Yes
   - **Prevent approval by code owners:** No

### Сценарий 5: Scheduled Pipeline Execution Policy для регулярного аудита

Scheduled Pipeline Execution Policy (Beta) запускает compliance пайплайн по расписанию независимо от коммитов. Это гарантирует регулярный аудит даже для неактивных репозиториев.

```yaml
# security-policy-project/.gitlab/security-policies/policy.yml
pipeline_execution_schedule_policy:
  - name: "Weekly compliance audit scan"
    description: "Run security and compliance checks weekly on all scoped projects"
    enabled: true
    content:
      include:
        - template: Security/SAST.gitlab-ci.yml
        - template: Security/Dependency-Scanning.gitlab-ci.yml
        - template: Security/Secret-Detection.gitlab-ci.yml
    schedules:
      - type: weekly
        days: ["Monday"]
        start_time: '03:00'
        time_window:
          value: 7200 # 2 часа
          distribution: random
        timezone: "UTC"
    policy_scope:
      compliance_frameworks:
        - id: 9
```

**Включение эксперимента (требуется для Beta):**
```yaml
# В том же policy.yml
experiments:
  pipeline_execution_schedule_policy:
    enabled: true
```

### Сценарий 6: Audit Event Monitoring

Audit Events фиксируются на instance, group и project уровнях. Для SRE и sysadmin критично централизовать эти логи и настроить алерты на аномалии.

```yaml
stages:
  - audit

audit_log_check:
  stage: audit
  image: curlimages/curl:8.8.0
  script:
    - |
      # Получение audit events за последний час (project-level)
      curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/audit_events?from=$(date -d '1 hour ago' +%s)&to=$(date +%s)" | \
        jq '.[] | select(.entity_type == "Project" and .event_name == "project_deploy_token_created")'
    - |
      # Проверка изменений в Protected Branches
      curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/audit_events?from=$(date -d '1 hour ago' +%s)&to=$(date +%s)" | \
        jq '.[] | select(.entity_type == "ProtectedBranch" and .event_name == "protected_branch_updated")'
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  cron: "0 * * * *"
  allow_failure: true
```

**Примечания:**
- Для instance-level audit events требуется токен администратора и endpoint `/api/v4/audit_events`.
- Максимальный диапазон запроса — 30 дней. Для большего окна используйте пагинацию (`page`, `per_page`).
- Для production окружений отправляйте audit events в центральный SIEM (Elastic, VictoriaMetrics, Wazuh) вместо `allow_failure: true`.

## Валидация и проверка

1. **Compliance Dashboard:** Перейдите в **Security & Compliance > Compliance Dashboard** — должны отображаться все проекты и их статус по controls.
2. **Audit Events:** Проверьте **Security & Compliance > Audit Events** — должны отображаться все actions (изменение protected branches, создание deploy tokens, изменение approval rules).
3. **MR Approvals:** Попробуйте merge MR без approval — должен быть блокирован.
4. **Pipeline Execution Policy:** Запустите пайплайн — должны инжектироваться security задачи из `.pipeline-policy-pre`. Проверьте, что `[skip ci]` не отключает политики.
5. **Deployment Approval:** Попробуйте запустить deployment job в production без approval — должен быть blocked.
6. **Scheduled Policy:** Проверьте **CI/CD > Schedules** — должен создаваться новый пайплайн по расписанию.
7. **API валидация:**
   ```bash
   # Проверка связывания security policy проекта
   curl --header "PRIVATE-TOKEN: <token>" \
     "https://gitlab.example.com/api/v4/projects/:id/security_policy_project_link"
   
   # Проверка 적용ённых policies
   curl --header "PRIVATE-TOKEN: <token>" \
     "https://gitlab.example.com/api/v4/projects/:id/security_policies"
   ```

## Troubleshooting

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Pipeline Execution Policy not applied** | Политика неактивна (`enabled: false`) или проект не в scope | Проверьте статус политики и membership в группе/ compliance framework |
| **Scan not running** | Политика не сработала | Проверьте `rules` в политике. Убедитесь, что условие совпадает с источником пайплайна. |
| **Approval not required** | Правило не настроено или недостаточно approvers | Проверьте настройки approval rules в UI или API Protected Environment |
| **`[skip ci]` bypasses policy** | Устаревшая версия GitLab < 17.3 | В 17.3+ pipeline execution policies игнорируют `[skip ci]`. Обновите инстанс. |
| **Audit events missing** | Audit logging отключен | Включите audit logging в Admin Area > Settings > Audit Events (Self-Managed) |
| **Compliance report empty** | Проект не размечен compliance framework | Назначьте compliance framework проекту через Compliance Center |
| **MR blocked without reason** | Approval rule настроена слишком строго | Проверьте настройки approval rules и исключите author/committers если нужно |
| **Deployment approval wait time** слишком высокий | Не настроен SLA или approvers недоступны | Настройте escalation policies и reserve approvers |
| **Scheduled policy not running** | Experiment отключен или schedule неверен | Включите `pipeline_execution_schedule_policy` experiment. Проверьте cron выражение. |

## Ограничения и крайние случаи

- **Compliance Pipelines и Pipeline Execution Policies не должны использоваться одновременно** в одном проекте. Это создаёт непредсказуемое поведение: duplicated jobs, pipeline failures, missing checks.
- **Максимум 5 политик** (`pipeline_execution_policy`) на security policy проект. Дополнительные политики игнорируются. В GitLab 17.11+ лимит можно повысить до 20 на инстанс.
- **Доступ к security policy проекту:** пользователь, запускающий пайплайн, должен иметь хотя бы read-only доступ к проекту с политикой. В GitLab 17.4+ это можно включить автоматически через настройку security policy проекта.
- **Merge request pipelines:** некоторые `workflow:rules` в проекте могут предотвратить выполнение политик в MR пайплайнах. Используйте `workflow: rules` в политике для контроля enforcement.
- **Reserved stages:** только политики могут использовать `.pipeline-policy-pre` и `.pipeline-policy-post`. В обычном `.gitlab-ci.yml` этих стадий использовать нельзя.
- **Variables precedence:** переменные pipeline execution policies имеют наивысший приоритет и не могут быть переопределены из проекта или других политик.
- **Dangling pipeline sources:** политики не внедряются в пайплайны с источниками `webide`, `parent_pipeline`, `ondemand_dast_scan`, `ondemand_dast_validation`, `security_orchestration_policy`, `container_registry_push`.
- **External controls:** пребывают в состоянии `pending` максимум 6 часов; после этого control считается failed.
- **Centralized compliance frameworks:** доступны только в GitLab Self-Managed Ultimate; на GitLab.com не поддерживаются.
- **Scan Execution Policies:** максимум 5 правил на политику и 5 политик на security policy проект. Обновления YAML propagate до 10 минут.
- **Audit Events retention:** по умолчанию GitLab хранит audit events бессрочно, но для PCI DSS требуется retention ≥1 года, для HIPAA — 6 лет. Настройте экспорт в SIEM и retention политику на стороне хранилища.

## Лучшие практики (Best Practices)

### Enforcement
- Используйте `.pipeline-policy-pre` для критических security и compliance проверок, которые не могут быть пропущены
- Устанавливайте `skip_ci: allowed: false` для предотвращения обхода политик (в настройках security policy проекта)
- Применяйте `inject_policy` вместо `inject_ci` для новых развёртываний
- Используйте `override_project_ci` только для высокорегулируемых сред, где требуется полный контроль пайплайна
- Включайте `AST_ENABLE_MR_PIPELINES: "true"` для запуска сканеров в merge request пайплайнах

### Separation of Duties
- Разделяйте роли: security team управляет политиками, development team управляет кодом
- Настройте approval rules с предотвращением self-approval (`Prevent approval by merge request creator`)
- Включите `Require user re-authentication` для approval в high-compliance средах (CFR Part 11)
- Используйте CODEOWNERS для автоматического назначения compliance approvers
- Security policy project должен иметь ограниченный доступ: только Security Managers и Maintainers

### Monitoring и Evidence
- Централизуйте audit events в SIEM (Elastic, VictoriaMetrics, Wazuh)
- Настройте retention согласно регуляторным требованиям: PCI DSS — 1 год (3 месяца hot storage), HIPAA — 6 лет
- Регулярно ревьюируйте compliance controls отчеты
- Настройте алерты на невыполнение compliance controls и отклонение от baseline
- Используйте immutable (append-only) хранилище для audit logs
- Коррелируйте audit events с deployment events через `CI_PIPELINE_ID` и `CI_COMMIT_SHA`

### Migration
- Мигрируйте compliance pipelines → pipeline execution policies до GitLab 19.0
- Используйте инструмент миграции в UI: Secure > Compliance center > Frameworks > Edit > Migrate pipeline to policy
- После миграции удалите старые `.compliance-gitlab-ci.yml` файлы

## Очистка

```bash
# Удаление устаревших audit events (Self-Managed)
# Примечание: стандартный API не поддерживает массовое удаление audit events.
# Используйте retention политики на уровне базы данных или экспортируйте в SIEM.

# Очистка orphaned compliance reports
find /tmp/compliance-reports -type f -mtime +90 -delete

# Удаление старых scheduled pipelines (если политика удалена)
curl --request DELETE \
  --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/:id/pipeline_schedules/:schedule_id"
```

## Дополнительная информация

### Смотрите также

- **[Compliance и Audit — полное руководство](../Advanced/compliance_and_audit.md)** — теория, frameworks, policies
- **[Merge Request Approval Rules](../Tutorials/merge_request_approval_rules.md)** — практическая настройка approval workflow
- **[Security Scanning](../Concepts/gitlab_ci_security_scanning.md)** — SAST, DAST, Secret Detection
- **[Environments and Deployments](../Concepts/environments_and_deployments.md)** — Protected Environments и Deployment Approvals
- **[Variables and Secrets](../Concepts/gitlab_ci_variables_secrets.md)** — защита секретов в compliance пайплайнах
- **[Audit & Compliance Overview](../../../Security/audit_and_compliance_overview.md)** — общие концепции аудита и комплаенса
