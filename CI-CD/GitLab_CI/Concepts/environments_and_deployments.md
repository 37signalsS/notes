# Окружения и развертывания в GitLab CI/CD

## Определения

- **Окружение (Environment):** Логическое представление инфраструктуры (например, `development`, `staging`, `production`). Ключевое слово `environment` создает объект в GitLab для отслеживания истории деплоев.
- **Развертывание (Deployment):** Запись о выполнении задания, связанного с окружением. Позволяет отслеживать, какая версия кода была развернута и кем.
- **Защищенное окружение (Protected Environment):** Окружение с ограниченным доступом. Только пользователи с определенными ролями могут инициировать развертывание в такие среды.
- **Динамическое окружение (Review App):** Временная среда, создаваемая для тестирования изменений в Merge Request (MR).
- **Уровень (Tier):** Классификация окружения (`production`, `staging`, `testing`, `development`, `other`). Используется для группировки и корректного расчета DORA-метрик.
- **Откат (Rollback):** Возврат окружения к предыдущему успешному состоянию путем перезапуска старого задания развертывания.

## Базовые концепции

### Создание и типы окружений

Окружения описываются в `.gitlab-ci.yml` и разделяются на две основные группы.

#### Статические окружения

Долгоживущие среды для стабильных этапов разработки.

```yaml
deploy_prod:
  stage: deploy
  script:
    - ./deploy.sh
  environment:
    name: production
    url: https://app.example.com
    kubernetes:
      namespace: prod-namespace
      agent: infra/k8s-agent:prod-agent
```

#### Динамические окружения

Создаются автоматически для каждой ветки или MR, обеспечивая изоляцию при тестировании.

```yaml
deploy_review:
  stage: deploy
  script:
    - ./deploy-review.sh
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.example.com
    on_stop: stop_review
    auto_stop_in: 1 week
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
