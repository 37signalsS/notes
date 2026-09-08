# Окружения и развертывания в GitLab CI/CD

## Определения

- **Окружение (Environment):** Логическое представление инфраструктуры (например, `development`, `staging`, `production`). Ключевое слово `environment` создает объект в GitLab для отслеживания истории деплоев и текущего состояния среды.
- **Развертывание (Deployment):** Запись о выполнении конкретного задания, связанного с окружением. Позволяет отслеживать «кто, что и куда» развернул.
- **Защищенное окружение (Protected Environment):** Среда с ограниченным доступом, где права на запуск деплоя имеют только определенные пользователи или группы.
- **Динамическое окружение (Review App):** Эфемерная (временная) среда, создаваемая для тестирования изменений в рамках конкретного Merge Request (MR).
- **Уровень (Tier):** Категория окружения (`production`, `staging`, `testing`, `development`). Необходима для корректного расчета DORA-метрик.
- **Откат (Rollback):** Оперативное возвращение окружения к предыдущему стабильному состоянию через перезапуск старого успешного задания деплоя.
- **Подтверждение (Approval):** Механизм блокировки деплоя до получения согласия от ответственных лиц или внешних систем (v19.2+).

## Базовые концепции

### Архитектура и интеграция с Kubernetes

В современных версиях GitLab (18.x+) интеграция с кластерами строится исключительно на базе **GitLab Agent for Kubernetes (KAS)**.

1.  **Push-модель (CI/CD Tunnel):** Пайплайн GitLab CI использует защищенный туннель через Агента для выполнения команд `kubectl` или `helm` в кластере.
2.  **Pull-модель (GitOps/Flux):** GitLab интегрируется с Flux (v18.4+), где Агент отслеживает изменения в репозитории и синхронизирует состояние кластера.
3.  **Визуализация:** Блок `environment:kubernetes` позволяет отображать статус ресурсов (поды, ингрессы) и состояние синхронизации Flux прямо в UI GitLab.

### Создание и типы окружений

Окружения описываются в `.gitlab-ci.yml` через одноименную директиву.

#### Статические окружения

Долгоживущие среды для стабильных этапов цикла поставки.

```yaml
deploy_prod:
  stage: deploy
  script:
    - helm upgrade --install my-app ./charts
  environment:
    name: production
    url: https://app.example.com
    kubernetes:
      namespace: prod-namespace
      # Привязка к конкретному агенту для CI/CD Tunnel
      agent: infra/k8s-agent:prod-agent
```

#### Динамические окружения

Создаются для каждой ветки, обеспечивая полную изоляцию проверок.

```yaml
deploy_review:
  stage: deploy
  script:
    - ./deploy-review.sh
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.example.com
    on_stop: stop_review
    auto_stop_in: 48 hours
    kubernetes:
      namespace: review-$CI_COMMIT_REF_SLUG
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

### Уровни окружений (Tiers)

Параметр `deployment_tier` (задается автоматически по имени или явно в `environment:action`) позволяет GitLab понимать роль окружения в жизненном цикле и корректно рассчитывать DORA-метрики.

- **Production:** Финальная среда для пользователей. Влияет на метрики *Change Failure Rate* и *Time to Restore*.
- **Staging:** Предрелизная среда, максимально близкая к prod.
- **Testing:** Среды для автоматизированных тестов и QA.
- **Development:** Индивидуальные среды разработчиков.

### Переменные и секреты окружений

GitLab позволяет ограничивать область действия переменных (`Scope`) конкретными окружениями. Это критично для безопасности: секреты `production` не должны быть доступны в `development`. С версии **19.2** рекомендуется использовать **GitLab Secrets Manager** для инъекции секретов в конкретные окружения, что обеспечивает аудит доступа на уровне деплоя. Подробнее см. в [GitLab CI Variables](../Concepts/gitlab_ci_variables_secrets.md).

### Остановка и очистка

Для динамических окружений обязательна настройка задачи остановки (`on_stop`), чтобы не перерасходовать ресурсы кластера.

```yaml
stop_review:
  stage: cleanup
  script:
    - ./cleanup.sh
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  when: manual
```

### Безопасность и контроль доступа

#### Защищенные окружения

Настраиваются в `Settings > CI/CD > Protected environments`. Позволяют:
- Ограничить круг лиц, имеющих право деплоить в `production`.
- Запретить деплой из неавторизованных веток.

#### Подтверждение развертываний (Approvals)

Функционал уровня Premium/Ultimate, позволяющий блокировать развертывание до получения одобрения.

1. **Запросы одобрения (Approval Requests):** Настраиваются для конкретного окружения. Можно указать конкретных пользователей или группы.
2. **External Deployment Approvals (19.2+):** Интеграция с внешними системами (ServiceNow, Jira) через Deployments API. Деплой блокируется до получения статуса `approved` от внешней системы.
3. **Deployment Approval Policies (19.0+):** Позволяют централизованно задавать правила одобрения на уровне группы или организации через Security & Compliance Policies. Эти политики имеют приоритет над настройками проекта.

## Практические сценарии

### Сценарий 1: Откат через Helm

Ручной откат версии приложения в Kubernetes.

```yaml
rollback_production:
  stage: rollback
  image: alpine/k8s:1.30.0
  script:
    - helm rollback my-release --wait --timeout 5m
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 2: Мониторинг Flux-ресурсов через Kubernetes Dashboard (18.4+)

Отслеживание статуса синхронизации GitOps прямо в интерфейсе GitLab.

```yaml
deploy_prod:
  stage: deploy
  environment:
    name: production
    kubernetes:
      namespace: prod-ns
      flux_resource_path: helm.toolkit.fluxcd.io/v2/namespaces/prod-ns/helmreleases/my-app
  script:
    - echo "Deployment managed by Flux"
```

### Сценарий 3: Групповые политики одобрения (Compliance)

1. В `Secure > Policies` создается `Deployment approval policy`.
2. Правило требует подтверждения от группы `Compliance-Team` для всех окружений с уровнем `production`.
3. Даже если в `.gitlab-ci.yml` проекта нет упоминания approvals, задание деплоя будет заблокировано до одобрения со стороны SRE/Compliance.

### Сценарий 4: Внешнее подтверждение деплоя через API (v19.2+)

Интеграция пайплайна с корпоративной системой управления изменениями (например, Jira).

```yaml
deploy_to_prod:
  stage: deploy
  environment:
    name: production
  script:
    - ./scripts/deploy_to_cloud.sh
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  # GitLab автоматически ожидает статус 'approved' от External Approval API
  # перед запуском этого задания, если настроена соответствующая интеграция.
```

1.  GitLab инициирует деплой и переводит задание в статус `blocked`.
2.  Отправляется хук во внешнюю систему.
3.  После ручной проверки в Jira, система отправляет `POST` запрос к GitLab Deployments API для одобрения.
4.  GitLab разблокирует задание и Runner приступает к выполнению.

### Сценарий 5: Деплой Terraform инфраструктуры с environment

Управление инфраструктурой через Terraform с привязкой к окружениям GitLab.

```yaml
stages:
  - plan
  - apply

.terraform_base:
  image: hashicorp/terraform:1.9
  before_script:
    - cd terraform/
    - terraform init -backend-config="backend.hcl"

terraform_plan:
  extends: .terraform_base
  stage: plan
  script:
    - terraform plan -out=tfplan -var-file="production.tfvars"
  artifacts:
    paths:
      - terraform/tfplan
    expire_in: 1 day
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

terraform_apply:
  extends: .terraform_base
  stage: apply
  script:
    - terraform apply -auto-approve tfplan
  dependencies:
    - terraform_plan
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 6: Деплой Ansible playbook с environment isolation

Запуск Ansible playbooks с изоляцией секретов по окружениям.

```yaml
stages:
  - validate
  - deploy

ansible_lint:
  stage: validate
  image: cytopia/ansible-lint
  script:
    - ansible-lint roles/
    - ansible-lint playbooks/

ansible_deploy:
  stage: deploy
  image: cytopia/ansible:2.14
  script:
    - ansible-playbook -i inventory/${CI_ENVIRONMENT_NAME} playbooks/deploy.yml
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"

ansible_deploy_prod:
  stage: deploy
  image: cytopia/ansible:2.14
  script:
    - ansible-playbook -i inventory/${CI_ENVIRONMENT_NAME} playbooks/deploy.yml
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 7: Откат базы данных через环境-scoped secrets

Безопасный откат БД с использованием секретов, привязанных к конкретному окружению.

```yaml
stages:
  - backup
  - rollback

backup_database:
  stage: backup
  image: postgres:16
  script:
    - pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME > backup_$(date +%Y%m%d_%H%M%S).sql
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

rollback_database:
  stage: rollback
  image: postgres:16
  script:
    - psql -h $DB_HOST -U $DB_USER -d $DB_NAME < backup_${BACKUP_TIMESTAMP}.sql
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  variables:
    BACKUP_TIMESTAMP: "20240101_120000"  # Указать нужный бэкап
```

### Сценарий 8: Canary деплой с мониторингом

Прогрессивная раскатка с автоматическим откатом при ошибках.

```yaml
stages:
  - deploy
  - verify

canary_deploy:
  stage: deploy
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
  script:
    - |
      # Проверка метрик после деплоя
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

## Дополнительная информация

### Интерфейс и аналитика

В разделе **Operate > Environments** доступны:
- **Deployment history:** История всех деплоев и их статусов.
- **Rollback:** Быстрый возврат к предыдущей успешной версии.
- **Environments Dashboard:** Единая панель для отслеживания состояния окружений во всех проектах группы.
- **Kubernetes Overview:** Реальное состояние ресурсов в кластере (требует KAS).

### Метрики DORA

GitLab использует данные о деплоях в окружениях уровня `production` для расчета:
- **Deployment Frequency:** Как часто код попадает в продакшн.
- **Lead Time for Changes:** Время от первого коммита до деплоя в прод.
- **Change Failure Rate:** Процент деплоев, приведших к инцидентам.
- **Time to Restore Service:** Среднее время восстановления после сбоя.

### Диагностика и устранение неполадок

#### Типичные ошибки и их решения

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Environment not found` | Окружение не определено в `.gitlab-ci.yml` или удалено | Добавьте директиву `environment` в задание или восстановите окружение. |
| `Protected environment access denied` | Попытка деплоя в защищенное окружение без прав | Проверьте настройки Protected Environments в Settings > CI/CD. |
| `on_stop task not found` | Задача остановки не найдена или имеет другое имя | Убедитесь, что `on_stop` ссылается на существующую задачу с `action: stop`. |
| `auto_stop_in expired` | Временное окружение истекло | Проверьте настройки `auto_stop_in` или продлите окружение через API. |
| `Kubernetes agent not connected` | GitLab Agent (KAS) не подключен к кластеру | Проверьте статус агента в Operations > Kubernetes. |
| `Deployment approval pending` | Деплой ожидает одобрения | Проверьте настройки Approval Policies или свяжитесь с approver. |

#### Методы диагностики

```bash
# Просмотр состояния окружений через API
curl --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" \
  "https://gitlab.example.com/api/v4/projects/${CI_PROJECT_ID}/environments"

# Просмотр истории деплоев
curl --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" \
  "https://gitlab.example.com/api/v4/projects/${CI_PROJECT_ID}/deployments"

# Проверка статуса агента Kubernetes
kubectl get agents -n gitlab
```

### Лучшие практики

1. **Всегда настраивайте `on_stop`** для динамических окружений, чтобы избежать перерасхода ресурсов.
2. **Используйте `auto_stop_in`** для автоматической очистки эфемерных сред.
3. **Привязывайте секреты к окружениям** через Environment Scope для изоляции.
4. **Настраивайте Protected Environments** для продакшена с ограничением по ролям.
5. **Используйте `deployment_tier`** для корректного расчета DORA-метрик.
6. **Документируйте URL окружений** для удобства доступа команде.
7. **Регулярно очищайте** неиспользуемые окружения через API или UI.

### Смотрите также

- **[Стратегии развертывания](../../Core_Concepts/deployment_strategies.md)** — обзор Rolling Update и Blue/Green.
- **[Проверка здоровья и откаты](../../Deployment_Strategies/deployment_health_checks_and_rollback.md)** — механизмы автоматизации.
- **[GitOps и GitLab](../../../GitOps/GitOps_overview.md)** — использование агента для Kubernetes.

> **Критичные изменения последних версий:**
>
> - **19.2**: Поддержка **External Deployment Approvals** через API (ServiceNow/Jira).
> - **19.0**: Появление **Deployment Approval Policies** на уровне Security & Compliance.
> - **18.4**: Внедрение блока `environment:kubernetes` для интеграции с Flux и K8s Dashboard.
> - **18.0**: Удаление поддержки legacy-интеграций Kubernetes на базе сертификатов в пользу **GitLab Agent (KAS)**.
