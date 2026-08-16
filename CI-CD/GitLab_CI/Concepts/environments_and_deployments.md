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

## Дополнительная информация

### Интерфейс и аналитика

В разделе **Operate > Environments** доступны:
- **Deployment history:** История всех деплоев и их статусов.
- **Rollback:** Быстрый возврат к предыдущей успешной версии.
- **Environments Dashboard:** Единая панель для отслеживания состояния окружений во всех проектах группы.
- **Kubernetes Overview:** Реальное состояние ресурсов в кластере (требует KAS).

### Метрики DORA

GitLab использует данные о деплоях в окружения уровня `production` для расчета:
- **Deployment Frequency:** Как часто код попадает в продакшн.
- **Lead Time for Changes:** Время от первого коммита до деплоя в прод.
- **Change Failure Rate:** Процент деплоев, приведших к инцидентам.
- **Time to Restore Service:** Среднее время восстановления после сбоя.

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
