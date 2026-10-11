# Окружения и защищенные окружения в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

> **Примечание:** Полная теория окружений, deployment tiers и DORA-метрик описана в **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)**. Это руководство фокусируется на практической настройке production-grade окружений.

## Определения

- **Окружение (Environment):** Логическое представление инфраструктуры (`development`, `staging`, `production`). В GitLab создаётся директивой `environment` в задании и используется для отслеживания истории деплоев, URL и текущего состояния среды.
- **Защищённое окружение (Protected Environment):** Окружение, доступ для деплоя в которое ограничен определёнными ролями (`Maintainer`, `Owner`) или группами. Настраивается в **Settings > CI/CD > Protected environments**.
- **Approval Rule:** Правило, требующее подтверждения деплоя от одного или нескольких пользователей/групп перед выполнением задания. Включено в Premium/Ultimate.
- **Deployment Approval Policy (19.0+):** Централизованное правило одобрения, задаваемое на уровне группы через **Secure > Policies**. Имеет приоритет над локальными Approval Rules проекта.
- **External Deployment Approval (19.2+):** Интеграция с внешней системой управления изменениями (ServiceNow, Jira), при которой деплой блокируется до получения статуса `approved` через GitLab Deployments API.
- **Динамическое окружение (Review App):** Эфемерная среда, создаваемая для каждого Merge Request и автоматически удаляемая по `auto_stop_in` или при закрытии MR.
- **Deployment Tier:** Категория окружения (`production`, `staging`, `testing`, `development`), влияющая на расчёт DORA-метрик.
- **Resource Group:** Механизм мьютекса, предотвращающий параллельное выполнение заданий, deploy-ющих в одну и ту же среду.
- **Deployment Freeze:** Период, в течение которого автоматические деплои в определённое окружение запрещены (настраивается через freeze-окна в UI или GitLab API).
- **Environment Scope:** Область действия CI/CD-переменной, привязанная к конкретному окружению (например, `production`), обеспечивающая изоляцию секретов.

## Предварительные требования

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `environment` (базовый) | 11.0+ | Создание окружения в UI |
| `deployment_tier` | 12.5+ | Категоризация для DORA-метрик |
| `auto_stop_in` | 13.8+ | Автоматическая очистка динамических окружений |
| `on_stop` + `action: stop` | 11.0+ | Ручная/автоматическая остановка окружения |
| Protected Environments | 13.8+ | Ограничение прав деплоя |
| Approval Rules | 12.3+ | Ручное подтверждение деплоя |
| Deployment Approval Policies | 19.0+ | Централизованные правила на уровне группы |
| External Deployment Approvals | 19.2+ | Интеграция с внешними системами через API |
| `environment:kubernetes` | 18.4+ | Интеграция с GitLab Agent for Kubernetes (KAS) |
| Deployment Freeze | 16.3+ | Заморозка деплоев на период |
| Resource Group | 12.7+ | Последовательный деплой (mutex) |

### Необходимые знания

- Структура `.gitlab-ci.yml`, стадии (`stages`) и правила запуска (`rules`)
- Основы GitLab CI/CD Variables, Protected/Masked переменные и Environment Scope
- Принципы DORA-метрик и их связи с `deployment_tier`
- Базовое понимание Kubernetes Namespaces, Services, Ingress и RBAC (для сценариев с кластером)
- Настройка GitLab Runner с tags и защитой от параллельного доступа

### Инфраструктура и инструменты

- GitLab Runner с меткой `protected-runner` для деплоев в production
- Kubernetes кластер с GitLab Agent for Kubernetes (KAS) версии 18.4+ (опционально, для сценариев с `environment:kubernetes`)
- Система мониторинга (Prometheus + Alertmanager или эквивалент) для отслеживания статуса деплоев
- Система управления изменениями (ServiceNow, Jira) для External Deployment Approvals (19.2+)

## Практические сценарии

### Сценарий 1: Базовое окружение с approval rule

```yaml
stages:
  - test
  - deploy

test:
  stage: test
  image: python:3.13-slim
  script:
    - pytest tests/
  environment:
    name: staging
    url: https://staging.example.com

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
```

**Настройка в UI (Settings > CI/CD > Protected environments):**

1. Выберите окружение `production`
2. Установите **Allowed to deploy**: `Maintainers` и `Owners`
3. Включите **Required approval**: 1 approval от `Maintainers`

### Сценарий 2: Защищённое окружение с approval rules и protected runner

```yaml
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
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  tags:
    - protected-runner
```

**Дополнительная конфигурация:**

- Настройте `protected-runner` в **Settings > CI/CD > Runners** с меткой `protected-runner` и флагом `Protected`.
- В **Settings > CI/CD > Protected environments** установите `production` как защищённое окружение с требуемым Approval Count = 1.

### Сценарий 3: Deployment Approval Policies (Group-level, GitLab 19.0+)

Политики уровня группы задаются в **Secure > Policies** в security policy проекте и имеют приоритет над локальными Approval Rules.

**Шаги в UI:**

1. Создайте security policy проект (требуется Ultimate).
2. Перейдите в **Secure > Policies > New policy**.
3. Выберите **Deployment approval policy**.
4. Настройте:
   - **Environments:** `production`
   - **Required approvals:** 2
   - **Allowed approvers:** группа `SRE-Approvers`
   - **Prevent approval by author:** включено
5. Назначьте политику целевым проектам.

```yaml
# В проекте-получателе политика применяется автоматически.
# Никаких дополнительных ключей в .gitlab-ci.yml не требуется.
deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  environment:
    name: production
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Важно:** Политика уровня группы переопределяет локальные Approval Rules. При конфликте приоритет имеет Security & Compliance Policy.

### Сценарий 4: External Deployment Approval через API (GitLab 19.2+)

Интеграция с внешней системой управления изменениями (Jira, ServiceNow) через GitLab Deployments API. В `.gitlab-ci.yml` нет специального ключа для внешних approval — интеграция настраивается на уровне инстанса/группы.

**Шаги настройки:**

1. В **Admin Area > Settings > CI/CD > External pipeline validation** или через Integration настроить endpoint внешней системы.
2. Внешняя система должна отправлять `POST` запрос на GitLab Deployments API для установки статуса `approved` на deployment.
3. GitLab переводит задание в статус `blocked` до получения approval.

```yaml
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
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Проверка через API:**

```bash
# Получение списка deployments с ожиданием approval
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/deployments?status=blocked"

# Approval deployment внешней системой
curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/deployments/$DEPLOYMENT_ID/approve"
```

**Важно:** При таймауте внешней системы (по умолчанию 5 секунд, настраивается через `EXTERNAL_VALIDATION_SERVICE_TIMEOUT`) деплой остаётся в статусе `blocked`.

### Сценарий 5: Динамическое окружение с auto_stop_in

```yaml
deploy_review:
  stage: deploy
  image: bitnami/kubectl:1.36
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/app \
        --namespace $NAMESPACE \
        --set image.tag=$CI_COMMIT_REF_SLUG
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    deployment_tier: testing
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID

stop_review:
  stage: cleanup
  image: bitnami/kubectl:1.36
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    GIT_STRATEGY: none
  script:
    - helm uninstall review-$CI_COMMIT_REF_SLUG --namespace $NAMESPACE || true
    - kubectl delete namespace $NAMESPACE --ignore-not-found
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  rules:
    - if: $CI_MERGE_REQUEST_ID
      when: manual
```

**Примечание:** Максимальное значение `auto_stop_in` — 30 дней. Для Review Apps рекомендуется значение 1–24 часа.

### Сценарий 6: environment:kubernetes (GitLab 18.4+)

```yaml
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
    kubernetes:
      namespace: production
      agent: my-group/my-project:prod-agent
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
      when: manual
```

**Требования:**
- GitLab Agent for Kubernetes (KAS) установлен и подключён к кластеру.
- Агент имеет права на deployment в namespace `production` (RBAC Role/ClusterRole).
- Pipeline использует Runner с доступом к KAS (CI/CD Tunnel).

### Сценарий 7: Deployment freeze windows

```yaml
stages:
  - deploy

variables:
  FREEZE_START: "2026-12-24 18:00"
  FREEZE_END: "2027-01-02 09:00"

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - |
      CURRENT=$(date +%s)
      START=$(date -j -f "%Y-%m-%d %H:%M" "$FREEZE_START" +%s)
      END=$(date -j -f "%Y-%m-%d %H:%M" "$FREEZE_END" +%s)
      if [ "$CURRENT" -ge "$START" ] && [ "$CURRENT" -le "$END" ]; then
        echo "Deployment freeze active. Deployments are blocked."
        exit 1
      fi
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Альтернатива (UI):** Настройте freeze windows в **Settings > CI/CD > Deployment freeze** для конкретных окружений и временных окон.

### Сценарий 8: Resource group для последовательного деплоя

```yaml
stages:
  - deploy

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  environment:
    name: production
  resource_group: production-deploy
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Режимы resource_group:**
- `unordered` (по умолчанию) — задания ожидают в очереди, порядок не гарантируется.
- `oldest-first` — задания обрабатываются в порядке поступления.

### Сценарий 9: Откат через environment action

```yaml
stages:
  - deploy
  - rollback

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

rollback_production:
  stage: rollback
  image: bitnami/kubectl:1.36
  script:
    - helm rollback my-release --wait --timeout 5m
  environment:
    name: production
    action: rollback
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Автоматический откат (GitLab Auto Rollback):** При интеграции с мониторингом (Prometheus Alertmanager) GitLab может автоматически запустить rollback при обнаружении критического алерта, если в алерте присутствует ключ `gitlab_environment_name`.

### Сценарий 10: Canary деплой с мониторингом и автоматическим откатом

```yaml
stages:
  - deploy
  - verify

canary_deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - kubectl set image deployment/my-app my-app=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
    - kubectl rollout status deployment/my-app --timeout=300s
  environment:
    name: canary
    url: https://canary.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

verify_canary:
  stage: verify
  image: bitnami/kubectl:1.36
  script:
    - |
      ERROR_RATE=$(curl -s "http://prometheus:9090/api/v1/query?query=rate(http_requests_total{status=~'5..',app='my-app'}[5m])" | jq '.data.result[0].value[1]' -r)
      if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
        echo "Error rate too high: $ERROR_RATE"
        kubectl rollout undo deployment/my-app
        exit 1
      fi
  environment:
    name: canary
  needs:
    - canary_deploy
```

**SRE-рекомендации:**
- Настройте алерты на `verify_canary` в Alertmanager.
- Используйте отдельный namespace или isolate canary через NetworkPolicy.
- Ограничьте `resource_group: canary` для предотвращения параллельных canary-деплоев.

### Сценарий 11: Продвижение артефакта между окружениями (Environment Promotion)

```yaml
stages:
  - build
  - deploy_dev
  - deploy_staging
  - deploy_prod

variables:
  IMAGE_TAG: $CI_COMMIT_SHORT_SHA

build:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$IMAGE_TAG .
    - docker push $CI_REGISTRY_IMAGE:$IMAGE_TAG
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_dev:
  stage: deploy_dev
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install my-app ./chart --namespace dev --set image.tag=$IMAGE_TAG
  environment:
    name: development
    url: https://dev.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_staging:
  stage: deploy_staging
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install my-app ./chart --namespace staging --set image.tag=$IMAGE_TAG
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

deploy_prod:
  stage: deploy_prod
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install my-app ./chart --namespace production --set image.tag=$IMAGE_TAG
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  needs:
    - deploy_staging
```

**Важно:** Параметр `IMAGE_TAG` зафиксирован на уровне pipeline (`variables:` в корне), что гарантирует использование одного и того же образа во всех окружениях. Для production-grade pipeline рекомендуется использовать артефакт-промоушен через GitLab Package Registry или Container Registry с immutability tags.

## Валидация и проверка

1. **Environments UI:** Перейдите в **Operate > Environments** — должны отображаться все окружения с историей деплоев и корректными deployment tiers.
2. **Protected Environment:** Попробуйте запустить деплой из незащищённой ветки или без нужной роли — задача должна быть в состоянии `pending` или `blocked`.
3. **Approval Rules:** Проверьте, что деплой блокируется до получения approval от ответственных лиц. Убедитесь, что `Prevent approval by author` работает.
4. **Deployment Approval Policy:** Проверьте в **Secure > Policies**, что политика применяется к проекту и имеет статус `Active`.
5. **External Approval:** Имитируйте ответ внешней системы через API — проверьте, что задание переходит из `blocked` в `running` после `POST` на `/deployments/:id/approve`.
6. **Resource Group:** Запустите два деплоя в production одновременно — второе должно ожидать освобождения ресурса (`waiting for resource`).
7. **Deployment Freeze:** Попробуйте запустить деплой в freeze-окне — задание должно быть пропущено или заблокировано.
8. **auto_stop_in:** После закрытия MR окружение должно удалиться автоматически. Проверьте через API:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/environments"
   ```
9. **DORA Metrics:** В **Analytics > CI/CD** проверьте Deployment Frequency и Change Failure Rate — они рассчитываются только для окружений с `deployment_tier=production`.

## Troubleshooting

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Deployment blocked** | Нет прав на деплой в protected environment | Добавьте пользователя в группу с ролью Maintainer или выше. Проверьте настройки Protected environments в **Settings > CI/CD**. |
| **Approval rule not triggered** | Правило настроено на группу, но пользователь не в ней | Проверьте membership и настройки правила. Убедитесь, что группа приглашена в проект. |
| **Environment not created** | Отсутствует блок `environment` в задаче | Добавьте `environment: name: <name>` в задачу. |
| **auto_stop_in not working** | Отсутствует `on_stop` или задача остановки | Добавьте `on_stop: stop_task` и задачу с `action: stop`. |
| **DORA metrics missing** | Не задан `deployment_tier` | Добавьте `deployment_tier` в блок `environment`. |
| **External approval not working** | Интеграция с внешней системой не настроена | Настройте External Approval Integration в Admin Area или через **Secure > Policies**. Проверьте таймаут внешней системы. |
| **Deployment stuck in `blocked`** | External Approval не ответил вовремя | Увеличьте `EXTERNAL_VALIDATION_SERVICE_TIMEOUT` или проверьте доступность внешней системы. |
| **Resource group deadlock** | Задание зависло в очереди | Проверьте, нет ли зависших заданий в `resource_group`. Убедитесь, что `resource_group` не используется в `needs` цикле. |
| **Review App leaked** | MR закрыт без запуска `on_stop` | Настройте CronJob для периодической очистки namespace старше N дней. |
| **Kubernetes agent not connected** | KAS не подключён к кластеру | Проверьте статус агента в **Operate > Kubernetes**. Убедитесь, что манифест агента применён в кластере. |
| **Rollback failed** | Нет предыдущего успешного deployment | Используйте `helm rollback` с явным указанием ревизии или восстановите из бекапа. |
| **Freeze window ignored** | Freeze настроен в UI, но правила игнорируются | Убедитесь, что freeze window применён к нужному окружению и проекту. |

## Ограничения и крайние случаи

1. **Параллельные деплои в одну среду:** Без `resource_group` параллельные задания могут одновременно изменять окружение, что приводит к состоянию гонки и несогласованному состоянию инфраструктуры. Используйте `resource_group: production` для последовательного деплоя. При массовом запуске pipeline учитывайте время блокировки ресурса.

2. **Удаление окружения через API:** При удалении окружения через API история deployments сохраняется. Полное удаление возможно только через UI или с помощью очистки базы данных GitLab. Для compliance-сред это может быть критично — настройте retention policies.

3. **Dynamic Environments в fork-проектах:** В проектах-форках переменные и protected environments не наследуются. Необходимо дублировать настройки в каждом fork. Для opensource-проектов рассмотрите использование CI/CD templates в группе.

4. **Deployment Approval Policies (19.0+):** Политики уровня группы переопределяют локальные Approval Rules. При конфликте приоритет имеет Security & Compliance Policy. Это означает, что локальные настройки проекта могут быть неэффективны, если в группе настроена политика.

5. **External Deployment Approvals (19.2+):** Внешняя система должна ответить статусом `approved` до истечения таймаута. При таймауте деплой остаётся в статусе `blocked`. Рекомендуется настраивать мониторинг на `blocked` deployments и алерты на долгоживущие approvals.

6. **Environment scope переменных:** Переменные с scope=`production` не доступны в других окружениях. При отладке убедитесь, что используете правильный scope. Для сложных конфигураций используйте `.gitlab/` директорию с файлами переменных.

7. **DORA-метрики и `deployment_tier`:** Метрики рассчитываются только для окружений с явно заданным `deployment_tier=production`. Окружения без tier не учитываются в отчётах. Убедитесь, что все production окружения имеют корректный tier.

8. **KAS и `environment:kubernetes`:** Блок `kubernetes:` требует, чтобы GitLab Agent был установлен и активен. Если агент отключён, задание завершится ошибкой. Настройте мониторинг состояния агента отдельно от пайплайна.

9. **Auto Rollback:** Функция доступна только для Ultimate tier и требует интеграции с мониторингом через Alertmanager. Если алерт не содержит ключ `gitlab_environment_name`, автоматический откат не сработает.

10. **Deployment Freeze:** Freeze windows настраиваются в UI и не гигиеничны для инфраструктуры как код. Для GitOps-процессов используйте freeze flags в виде переменных или branch protections.

11. **Review Apps и namespace quota:** При высокой нагрузке Review Apps могут исчерпать quota namespace в кластере. Настройте ResourceQuota и LimitRange для namespaces Review Apps и CronJob для периодической очистки.

12. **Protected runners и параллелизм:** Protected runners могут обрабатывать только задания с меткой `protected-runner`. При большом количестве parallel pipelines可能出现 очередь. Настройте `concurrent` в `gitlab.rb` или используйте несколько runners.

## Лучшие практики (Best Practices)

### Безопасность:

- Используйте Protected Environments для `staging` и `production`.
- Настройте Approval Rules с минимальным количеством одобрений (1–2 для production).
- Для production используйте `when: manual` в rules.
- Ограничьте права на деплой только `Maintainers` и `Owners`.
- Включите `Prevent approval by author` для всех compliance-critical проектов.
- Используйте Deployment Approval Policies (19.0+) для централизованного управления approvals на уровне группы.
- Используйте External Deployment Approvals (19.2+) для regulated сред с внешней системой управления изменениями.
- Привязывайте секреты к окружениям через Environment Scope для изоляции (`production` секреты не доступны в `development`).
- Настройте audit logging для всех approval действий и деплоев (GitLab Audit Events).
- Используйте GitLab Secrets Manager (19.2+) для инъекции секретов с аудит доступа на уровне деплоя.

### Производительность:

- Используйте `auto_stop_in` для Review Apps (1–24 часа).
- Настройте `deployment_tier` для корректного расчёта DORA-метрик.
- Используйте `resource_group` для предотвращения параллельных деплоев в production.
- Настройте Deployment Freeze windows для праздничных периодов и planned maintenance.
- Используйте `environment:kubernetes` для визуализации статуса ресурсов.
- Фиксируйте `IMAGE_TAG` на уровне pipeline для артефакт-промоушена без пересборки.

### Надёжность и SRE:

- Всегда добавляйте `url` в блок `environment` для отслеживания.
- Используйте `on_stop` для корректной очистки динамических окружений.
- Настройте ResourceQuota и LimitRange для namespaces Review Apps.
- Ведите аудит деплоев через GitLab Audit Events.
- Настройте мониторинг пайплайнов: длительность, failure rate, pending approvals.
- Используйте sidecar-контейнеры для сбора логов и метрик во время деплоя.
- Настраивайте NetworkPolicy для namespaces Review Apps для изоляции трафика.
- Ограничьте права runners через tags и protected runners — production runners не должны быть доступны для MR pipelines.
- Настройте алерты на deployments в статусе `blocked` > 15 минут.
- Документируйте runbooks для rollback, incident response и disaster recovery.
- Настройте backup environment state: exports конфигураций, Helm values, manifests.
- Тестируйте disaster recovery сценарии: восстановление environment из backup, откат на предыдущий stable release.
- Используйте `GIT_STRATEGY: none` в задачах остановки Review Apps для ускорения работы.
- Настройте `timeout` для deployment jobs (например, `timeout: 30m`) для предотвращения зависших пайплайнов.

### Compliance:

- Включите Compliance Framework для группы (Settings > Compliance).
- Настройте CODEOWNERS для инфраструктурных директорий (`charts/`, `k8s/`, `.gitlab-ci.yml`).
- Используйте merge request approvals для инфраструктурных изменений.
- Ведите changelog deployment'ов вручную или через automated release notes.

## Очистка

```bash
# Удаление окружения через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/environments/$ENV_ID"

# Пакетная очистка окружений старше 30 дней
glab api projects/$PROJECT_ID/environments | jq -r '.[].id' | \
  while read env_id; do
    created=$(glab api projects/$PROJECT_ID/environments/$env_id | jq -r '.created_at')
    cutoff=$(date -v-30d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -d "30 days ago" +%Y-%m-%dT%H:%M:%SZ)
    if [ "$created" \< "$cutoff" ]; then
      curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/environments/$env_id"
    fi
  done
```

**Очистка Review Apps через Kubernetes:**

```bash
# Удаление namespace старше 1 дня
kubectl get namespaces -l app=review-app -o json | jq -r '.items[] | select(.metadata.creationTimestamp < "'$(date -d "1 day ago" +%Y-%m-%dT%H:%M:%SZ)'") | .metadata.name' | \
  xargs -I {} kubectl delete namespace {}
```

**Проверка GC Container Registry (если применимо):**

```bash
# Проверка статуса Garbage Collection через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/garbage_collection"
```

## Дополнительная информация

### Смотрите также

- **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)** — полная теория, tiers, защищённые окружения
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — environment scope и deployment variables
- **[Review Apps и динамические окружения](../Tutorials/kubernetes_review_apps.md)** — настройка сред для MR
- **[Compliance и Audit](../Advanced/compliance_and_audit.md)** — Pipeline Execution Policies и compliance frameworks
- **[Стратегии развертывания](../../Core_Concepts/deployment_strategies.md)** — обзор Rolling Update и Blue/Green
- **[Resource Group и контроль пайплайнов](../Advanced/resource_group_and_pipeline_control.md)** — мьютекс, concurrency, retry, timeout
- **[Image Promotion Strategies](../Advanced/image_promotion_strategies.md)** — промоушен артефактов между окружениями
- **[Сканирование безопасности в GitLab CI/CD](../Concepts/gitlab_ci_security_scanning.md)** — SAST/DAST/Secret Detection
- **[OIDC и Workload Identity](../Advanced/gitlab_ci_oidc_workload_identity.md)** — аутентификация без секретов
