# Аварийные процедуры и Hotfix (Emergency Procedures & Hotfix)

**Актуально для:** self-hosted CI/CD (GitLab CI, GitHub Actions, Jenkins) 2024–2026

> Область применения: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, не рассматриваются.

## Определения

- **Hotfix** — экстренное исправление, выпускаемое в production в кратчайшие сроки (часы, а не дни). Проходит ускоренную процедуру approval, но сохраняет traceability.
- **Emergency Change** — изменение, требующее немедленного применения для устранения production инцидента. Классифицируется как Emergency Change в ITIL/Change Management.
- **Rollback Plan** — документированная процедура возврата системы в предыдущее стабильное состояние.
- **Kill Switch** — feature flag, мгновенно отключающий проблемную функциональность без релиза.
- **Out-of-band deploy** — деплой, выполняемый в обход обычного пайплайна (например, через `kubectl rollback` или `helm rollback`).
- **Maintenance Mode** — режим обслуживания, при котором новые деплои и изменения временно приостановлены для проведения аварийных работ.
- **Change Freeze** — временный запрет на неэкстренные изменения для снижения риска при проведении критических операций.
- **ECAB (Emergency CAB)** — усечённый состав CAB для экстренных изменений. Подробнее: **[Управление изменениями и CAB](./change_management.md)**.
- **IC (Incident Commander)** — ответственный за координацию во время инцидента. Подробнее: **[Управление инцидентами и постмортемы (SRE)](./incident_response_sre.md)**.

## Предпосылки

Перед выполнением аварийных процедур убедитесь, что в инфраструктуре подготовлены:

- **On-call ротация:** настроена эскалация (PagerDuty, OpsGenie, GitLab Escalation Policies) с разграничением по severity.
- **Доступ к production:** наличие kubectl/helm/ssh доступа у дежурных; при необходимости — out-of-band канал (IPMI, rescue mode, jump host).
- **Резервные копии:** свежий бэкап registry, артефактов и CI-конфигураций. Подробнее: **[Резервное копирование и DR для CI/CD](./ci_cd_backup_dr.md)**.
- **Runbook'ы:** пошаговые инструкции для типовых инцидентов (Runner down, registry outage, deployment failure) проверены на DR-площадке. Подробнее: **[Incident Response для CI/CD](../GitLab_CI/Advanced/incident_response_cicd.md)**.
- **Approval policies:** настроены emergency override правила в CI/CD-платформе (GitLab `approval_rules`, GitHub environment protection, Jenkins `authorize-project`).
- **Коммуникационные каналы:** созданы war room каналы (Slack/Teams/Matrix) и шаблоны уведомлений.

## Основные концепции

### Почему аварийные процедуры в CI/CD отличаются

В обычном релизе пайплайн выступает защитным барьером: тесты, сканеры, approval gates. В emergency этот барьер сознательно сужается, но не disappears. Ключевые отличия:

1. **Blast radius контроля:** Обычный деплой ограничивается canary/rolling; emergency деплой может затрагивать всю fleet сразу. Требуется явный расчёт последствий.
2. **Audit trail:** Даже при fast-track approval все действия фиксируются в Git history + CI logs. Отсутствие аудита — отдельный инцидент.
3. **Rollback-first мышление:** В emergency план отката пишется до начала деплоя, а не после. Время на откат критичнее, чем время на деплой.
4. **Separation of concerns:** Hotfix branch создаётся от стабильной ветки, а не от текущей develop/main с незавершёнными фичами.
5. **Multi-platform complexity:** Разные платформы имеют разные механизмы emergency override (GitLab `emergency_override`, GitHub `bypass` для environment, Jenkins `authorize-project` с `RunScmCheck`).

### Экономика MTTR в CI/CD

Среднее время восстановления (MTTR) после деплоя-инцидента состоит из:

| Компонент | Обычный деплой | Emergency hotfix |
|:---|:---|:---|
| **Triage** | 5–15 мин | < 5 мин |
| **ECAB / Approval** | 30–120 мин | 5–15 мин |
| **Build** | 5–10 мин | 2–5 мин (ускоренные проверки) |
| **Deploy** | 5–15 мин | 2–10 мин |
| **Verify** | 5–10 мин | 2–5 мин |
| **Итого** | 50–70 мин | 15–40 мин |

Цель emergency процедур — минимизировать каждый компонент, сохраняя traceability.

### Hotfix vs Rollback vs Kill Switch

| Действие | Когда | Время | Риск | Платформы |
|:---|:---|:---|:---|:---|
| **Kill Switch** | Проблема в новом функционале, есть feature flag | 1–5 минут | Низкий — отключаем фичу без деплоя | Все |
| **Rollback** | Недавний деплой, нет новых данных | 5–15 минут | Низкий — возврат к известному состоянию | GitLab, GitHub, Jenkins |
| **Hotfix** | Проблема в коде, нет быстрого отката | 30–120 минут | Средний — новый код в production | Все |
| **Out-of-band deploy** | CI/CD платформа недоступна | 15–60 минут | Высокий — обход стандартных контролей | Все (требует ручного доступа) |

### Классификация инцидентов

Общие принципы severity и escalation matrix описаны в **[Управлении инцидентами и постмортемах (SRE)](./incident_response_sre.md)**. Ниже — CI/CD-специфичные примеры:

| Severity | Влияние | Время реакции | Процедура |
|:---|:---|:---|:---|
| **SEV1** | Полный простой, данные утеряны, registry недоступен | 15 минут | ECAB, War Room, hotfix |
| **SEV2** | Частичная деградация, deployment заблокирован | 1 час | IC + Tech Lead, fast-track approval |
| **SEV3** | Минимальное влияние, workaround есть | 4 часа | Стандартное изменение, CAB async |

### Процедура Hotfix

```
Detect → Triage → ECAB → Hotfix Branch → Build → Fast-track Approval → Deploy → Verify → Post-mortem
```

1. **Detect:** Обнаружение инцидента (алерт, on-call, пользователь).
2. **Triage:** Оценка SEV. Если SEV1/SEV2 — ECAB. Подробнее: **[Управление инцидентами и постмортемы (SRE)](./incident_response_sre.md)**.
3. **ECAB:** IC + Tech Lead + DBA (async call или чат). Обсуждают: blast radius, rollback plan, need for CAB later. Подробнее: **[Управление изменениями и CAB](./change_management.md)**.
4. **Hotfix Branch:** Ветка `hotfix/SEV1-xxx` от `main`.
5. **Build:** Сборка с ускоренными проверками (lint + smoke tests).
6. **Fast-track Approval:** Минимальные approval (1-2 человека). Emergency override token при необходимости.
7. **Deploy:** Деплой в production с priority.
8. **Verify:** Проверка healthchecks и метрик.
9. **Post-mortem:** Бламлесс-разбор через 48 часов. Подробнее: **[Управление инцидентами и постмортемы (SRE)](./incident_response_sre.md)**.

### Интеграция с Change Management

Emergency процедуры не существуют отдельно от Change Management. В зрелой DevOps-организации:

- **Standard Change Registry:** hotfix workflow предварительно зарегистрирован как standard change с fast-track approval.
- **Change Failure Budget:** при исчерпании бюджетаfailed deployments автоматически включается change freeze на неэкстренные изменения.
- **Post-review:** ECAB решение post-factum проверяется полным CAB через 48 часов.
- **Audit Trail:** все emergency approvals логируются в CI/CD-платформе и связываются с incident ticket.

Подробнее: **[Управление изменениями и CAB](./change_management.md)**.

### Maintenance Mode и Change Freeze

При проведении critical миграций или infrastructure работ:

1. **Включение maintenance mode:** Патч `/maintenance` или env-переменная `MAINTENANCE_MODE=true` отключает новые деплои.
2. **Change freeze notification:** Уведомление всех команд через календарь изменений (Change Calendar).
3. **Emergency exception:** Только SEV1/SEV2 инциденты проходят через ECAB; остальные ждут окончания окна.

## Практические сценарии

### Сценарий 1: Hotfix в GitLab CI (SEV1)

#### Предпосылки
- Production простой из-за critical bug.
- Требуется hotfix за < 30 минут.
- Настроены protected environments и approval rules.

#### .gitlab-ci.yml
```yaml
stages:
  - lint
  - build
  - deploy

variables:
  HOTFIX: "true"

lint:
  stage: lint
  image: python:3.13-slim
  script:
    - ruff check .
    - npm run lint
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^hotfix\//

build:
  stage: build
  image: docker:24
  services: [docker:dind]
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^hotfix\//

deploy_prod:
  stage: deploy
  image: bitnami/kubectl:1.29
  script:
    - kubectl set image deployment/app app=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA -n production
    - kubectl rollout status deployment/app -n production --timeout=5m
  environment:
    name: production
  when: manual
  allow_failure: false
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^hotfix\//
```

#### Approval Rules (GitLab UI)
- Hotfix branch: минимум 1 approve от IC или Tech Lead.
- Emergency override: emergency override token для быстрого approval.

#### Валидация
- Hotfix deployed за < 30 минут.
- Audit log содержит кто, когда, почему approve.
- ECAB decision documented в incident ticket.

### Сценарий 2: Emergency Rollback (helm rollback)

#### Предпосылки
- Новый деплой сломал production.
- Требуется быстрый откат без сборки нового образа.

#### Скрипт rollback.sh
```bash
#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-production}"
RELEASE="${2:-app}"

# Получение предыдущей ревизии
PREVIOUS=$(helm history "$RELEASE" -n "$NAMESPACE" | awk 'NR==2 {print $1}')

# Rollback
helm rollback "$RELEASE" "$PREVIOUS" -n "$NAMESPACE" --timeout 5m

# Проверка
kubectl rollout status deployment/"$RELEASE" -n "$NAMESPACE" --timeout=5m

echo "Rollback to revision $PREVIOUS completed"
```

#### Использование
```bash
./rollback.sh production app
# → Rollback to revision 42 completed
```

#### Валидация
- `helm history` показывает предыдущую ревизию.
- `kubectl rollout status` подтверждает успешный откат.
- Healthcheck возвращает 200.

### Сценарий 3: Kill Switch через Feature Flag

#### Предпосылки
- Проблема в новом функционале.
- Есть feature flag для этого функционала.

#### Использование
```bash
# Выключение флага через API
curl -X POST https://unleash.internal/api/features/new-checkout/disable \
  -H "Authorization: Bearer $UNLEASH_TOKEN" \
  -H "Content-Type: application/json"

# Или через kubectl
kubectl set env deployment/app FEATURE_NEW_CHECKOUT=false -n production
```

#### Валидация
- Флаг выключен в UI Unleash.
- Приложение перезапустилось с новым значением.
- Метрики error rate вернулись к норме.

### Сценарий 4: Hotfix в GitHub Actions (SEV1)

#### Предпосылки
- Production простой из-за critical bug.
- Требуется hotfix за < 30 минут.
- Используется self-hosted runner.

#### Структура
```
.github/
└── workflows/
    └── hotfix.yml
```

#### .github/workflows/hotfix.yml
```yaml
name: Hotfix Deploy
on:
  push:
    branches: [ hotfix/* ]
  workflow_dispatch:

jobs:
  lint:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - run: ruff check . && npm run lint

  build:
    runs-on: self-hosted
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: registry.internal
          username: ${{ secrets.REGISTRY_USER }}
          password: ${{ secrets.REGISTRY_PASS }}
      - run: docker build -t registry.internal/app:${{ github.sha }} .
      - run: docker push registry.internal/app:${{ github.sha }}

  deploy:
    runs-on: self-hosted
    needs: build
    environment:
      name: production
      url: https://app.internal
    steps:
      - uses: actions/checkout@v4
      - uses: azure/k8s-set-context@v4
        with:
          kubeconfig: ${{ secrets.KUBECONFIG }}
      - run: kubectl set image deployment/app app=registry.internal/app:${{ github.sha }} -n production
      - run: kubectl rollout status deployment/app -n production --timeout=5m
```

#### Environment Protection Rules (GitHub UI)
- Required reviewers: минимум 1 approve от IC или Tech Lead.
- Wait timer: 0 минут (для SEV1).
- Restrict branches: только `hotfix/*`.

#### Валидация
- Hotfix deployed за < 30 минут.
- Audit log в GitHub содержит кто, когда, почему approve.
- ECAB decision documented в incident ticket.

### Сценарий 5: Emergency Rollback в Jenkins

#### Предпосылки
- Jenkins с Multibranch Pipeline.
- Требуется быстрый откат без rebuild.

#### Jenkinsfile
```groovy
pipeline {
  agent any
  options {
    buildDiscarder(logRotator(numToKeepStr: '10'))
    timeout(time: 1, unit: 'HOURS')
  }
  stages {
    stage('Deploy') {
      steps {
        script {
          def revision = sh(returnStdout: true, script: 'git rev-parse HEAD').trim()
          sh "kubectl set image deployment/app app=registry.internal/app:${revision} -n production"
          sh "kubectl rollout status deployment/app -n production --timeout=5m"
        }
      }
    }
  }
}
```

#### Rollback через Jenkins CLI
```bash
# Получение предыдущей стабильной сборки
PREVIOUS_BUILD=$(jenkins-cli get-job "my-project" | grep -B1 "SUCCESS" | head -1 | awk '{print $2}' | tr -d '#')

# Откат
jenkins-cli build "my-project" -p "REVISION=$PREVIOUS_BUILD" -v

# Или через script console
java -jar jenkins-cli.jar -s https://jenkins.internal/ groovy = <<EOF
def job = Jenkins.instance.getItem("my-project")
def build = job.getBuildByNumber($PREVIOUS_BUILD)
println "Rolling back to build #${build.number}"
EOF
```

#### Валидация
- `kubectl rollout history` показывает предыдущую ревизию.
- Healthcheck возвращает 200.

### Сценарий 6: Out-of-band Deploy (CI/CD недоступна)

#### Предпосылки
- GitLab / GitHub Actions полностью недоступен.
- Требуется деплой вручную.

#### Процедура
1. Получить доступ к production через out-of-band канал (IPMI, jump host, rescue mode).
2. Собрать образ локально или использовать предыдущий стабильный образ.
3. Применить манифест вручную.

```bash
# 1. Применение манифеста напрямую
kubectl apply -f k8s/deployment.yaml -n production

# 2. Проверка rollout
kubectl rollout status deployment/app -n production --timeout=5m

# 3. Верификация
curl -fsS http://app.internal/healthz
```

#### Post-recovery
- После восстановления CI/CD повторно применить стандартный пайплайн для синхронизации состояния.
- Зафиксировать все manual действия в incident ticket для post-mortem.

## Устранение неисправностей (Troubleshooting)

### Типичные ошибки при emergency деплое

| Симптом | Причина | Решение |
|:---|:---|:---|
| **Hotfix branch не запускает пайплайн** | Правила `rules:`/`only:` не распознают `hotfix/*` | Проверьте regex: `if: $CI_COMMIT_BRANCH =~ /^hotfix\//` (GitLab) или `if: github.ref == 'refs/heads/hotfix/*'` (GitHub). |
| **Approval gate блокирует hotfix** | Нет emergency override token или достаточных прав | Используйте emergency override (GitLab) или `bypass` для environment (GitHub). Убедитесь, что approver в healtcheck. |
| **Deploy завис на `probe`** | Новый код падает при старте, liveness probe убивает под | Увеличьте `initialDelaySeconds` и `failureThreshold` на время деплоя; проверьте логи: `kubectl logs <pod> --previous`. |
| **Rollback не находит предыдущую ревизию** | `revisionHistoryLimit` установлен в 0 или 1 | Временно увеличьте лимит; для Helm revision хранятся в секретах. |
| **Kill Switch не отключает фичу** | Флаг кэшируется в приложении или CDN | Перезапустите поды или очистите кэш; проверьте конфигурацию Unleash/Flagr. |
| **CI/CD платформа недоступна** | GitLab Runner / GitHub Actions downtime | Переключитесь на out-of-band deploy; после восстановления синхронизируйте состояние. |
| **Hotfix ломает данные** | Изменение schema без backfill или несовместимое API | Откатитесь; для данных — восстановите из бэкапа или используйте kill switch. |
| **Post-deploy smoke test падает** | Недоступность зависимостей (БД, кэш, очередь) | Проверьте health endpoint приложения и connectivity; не объявляйте success пока smoke не пройден. |
| **Multiple hotfix конфликтуют** | Параллельные hotfix ветки от одного base | Координируйте через IC; merge первую, rebase вторую; используйте queue. |
| **Certificate expiration (SEV1)** | Просроченный сертификат registry / ingress | Быстрая ротация через CI/CD variable или manual update; настроить automated rotation. |

## Ограничения и крайние случаи

- **Hotfix без тестов:** В экстренных случаях можно пропустить часть тестов, но требуется явное разрешение IC и обязательный smoke test после деплоя.
- **Multiple hotfixes:** Параллельные hotfix-ветки создают конфликты. Требуется coordination через IC и последовательный merge.
- **Data migration during hotfix:** Миграции данных в hotfix рискованны. Предпочитайте kill switch или rollback.
- **Out-of-band access:** В некоторых инфраструктурах доступ к production только через out-of-band канал (IPMI, rescue mode).
- **Certificate expiration:** Просроченный сертификат может вызвать SEV1. Требуется automated rotation.
- **Change freeze:** При исчерпании Change Failure Budget автоматически включается freeze. Emergency изменения требуют ECAB approval.
- **CI/CD platform lock-in:** Миграции, завязанные на vendor-specific фичи (GitLab `resource_group`, GitHub `environment`), усложняют аварийные процедуры при недоступности платформы.
- **Maintenance windows:** Некоторые миграции требуют planned downtime. Интегрируйте maintenance_mode в pipeline.
- **DBA bottleneck:** Ручное ревью каждой миграции создаёт очередь. Автоматизируйте lint и drift detection, оставляя ручное approval только для критичных изменений.

## Валидация и проверки

### Обязательные проверки после emergency деплоя

1. **Healthcheck:** Приложение отвечает на `/healthz` или `/ready`.
2. **SLO-метрики:** Error rate, latency p99 вернулись к норме.
3. **Replication lag:** Репликация не отстаёт (lag < порога).
4. **No waiting sessions:** Нет `waiting` сессий в БД или других блокировок.
5. **Smoke test:** Ключевые пользовательские сценарии проходят.
6. **Audit trail:** Все действия зафиксированы в CI/CD logs и Git history.

### Критерии успешного восстановления

- Все миграции применены: `flyway info` / `liquibase status` = Success (если были миграции).
- Приложение отвечает на health-check.
- Ключевые бизнес-метрики (latency p99, error rate) в норме.
- Репликация не отстаёт.
- Нет `waiting` сессий.

## Лучшие практики

1. **Документируйте hotfix workflow:** Hotfix должен проходить те же gates, что и обычный релиз, но с fast-track approval.
2. **Kill switch прежде hotfix:** Всегда проверяйте, есть ли feature flag для отключения проблемного функционала.
3. **Rollback готов всегда:** План отката пишется до начала прод-выкатки, а не после.
4. **War room заранее:** Настройте каналы и эскалацию ДО инцидента.
5. **Post-mortem без виноватых:** Бламлесс-разбор, фокус на системных причинах.
6. **Action items с ответственными:** Каждый пункт постмортема имеет владельца и срок.
7. **Отслеживайте MTTR:** Время от обнаружения до восстановления — ключевая метрика.
8. **Maintenance mode:** Интегрируйте maintenance_mode в pipeline для критических операций.
9. **Change freeze automation:** Настройте автоматический freeze при исчерпании Change Failure Budget.
10. **Multi-platform runbooks:** Для каждой платформы (GitLab, GitHub, Jenkins) должен быть свой runbook с platform-specific командами.
11. **Out-of-band preparation:** Резервные каналы доступа и manual deploy procedure должны быть готовы ДО инцидента.
12. **Audit trail by default:** Все emergency действия фиксируются в CI/CD logs и Git history.

## См. также

### Инструменты

- **PagerDuty / OpsGenie** — on-call ротация и эскалация.
- **Slack / Teams / Matrix** — war room коммуникация.
- **Statuspage** — публичный статус для пользователей.
- **Jira / GitLab Issues / GitHub Issues** — трекинг инцидентов и action items.
- **Vault** — ротация секретов во время инцидента.

### Связанные темы

- **[Управление изменениями и CAB](./change_management.md)** — классификация изменений, ECAB workflow, change freeze.
- **[Управление инцидентами и постмортемы (SRE)](./incident_response_sre.md)** — severity levels, escalation matrix, war room, постмортемы.
- **[Incident Response для CI/CD](../GitLab_CI/Advanced/incident_response_cicd.md)** — CI/CD-специфичные инциденты (Runner down, registry outage, secret leak).
- **[Проверки здоровья и откат развертывания](../Deployment_Strategies/deployment_health_checks_and_rollback.md)** — rollback scripts, health checks.
- **[Резервное копирование и DR для CI/CD](./ci_cd_backup_dr.md)** — бэкапы, RPO/RTO, DR drill.
- **[Метрики DORA](./dora_metrics.md)** — влияние Change Management на Deployment Frequency и Lead Time.
- **[Мониторинг и метрики GitLab CI/CD](../GitLab_CI/Advanced/monitoring_and_metrics.md)** — GitLab-специфичные метрики.
- **[Merge Request Approval Rules](../GitLab_CI/Tutorials/merge_request_approval_rules.md)** — emergency override для hotfix.
