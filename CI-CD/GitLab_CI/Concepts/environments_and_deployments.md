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
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

### Уровни окружений (Tiers)

Параметр `deployment_tier` (задается автоматически по имени или явно в `environment:action`) позволяет GitLab понимать роль окружения в жизненном цикле.

- **Production:** Финальная среда для пользователей.
- **Staging:** Предрелизная среда, максимально близкая к prod.
- **Testing:** Среды для автоматизированных тестов и QA.
- **Development:** Индивидуальные среды разработчиков.

### Переменные и секреты окружений

GitLab позволяет ограничивать область действия переменных (`Scope`) конкретными окружениями. Это критично для безопасности: секреты `production` не должны быть доступны в `development`. Подробнее см. в [GitLab CI Variables](../Concepts/gitlab_ci_variables_secrets.md).

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

- **Запросы одобрения (Approval Requests):** Настраиваются для конкретного окружения. Можно указать конкретных пользователей или группы.
- **Групповые политики (Deployment Approval Policies):** (версия 19.0+) Позволяют централизованно задавать правила одобрения для всех проектов в группе или подгруппе. Это упрощает комплаенс и исключает необходимость ручной настройки каждого репозитория.

## Практические сценарии

### Сценарий 1: Откат через Helm

Ручной откат версии приложения в Kubernetes с использованием Helm.

```yaml
rollback_production:
  stage: rollback
  image: alpine/k8s:1.30.0
  script:
    - helm rollback my-release --wait --timeout 5m
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
```

### Сценарий 2: Динамические окружения в Kubernetes

Использование уникальных пространств имен (Namespace) для каждой ветки.

1. **Deploy:** Создается namespace `review-$CI_COMMIT_REF_SLUG`.
2. **URL:** Приложение доступно по адресу `https://$CI_COMMIT_REF_SLUG.kube.example.com`.
3. **Cleanup:** После закрытия MR задача `on_stop` удаляет namespace со всеми ресурсами.

Подробности настройки — в [руководстве по Review Apps](../Tutorials/kubernetes_review_apps.md).

### Сценарий 3: Групповые политики одобрения

Использование политик для принудительного одобрения деплоев в `production` во всей организации.

1. **Создание политики:** В `Secure > Policies` создается `Deployment approval policy`.
2. **Условия:** Правило срабатывает для всех окружений с уровнем `production`.
3. **Одобрители:** Группа `SRE-team` должна дать хотя бы 1 одобрение.
4. **Результат:** Даже если в `.gitlab-ci.yml` проекта нет упоминания approvals, задание деплоя будет заблокировано до действия со стороны SRE.

## Дополнительная информация

### Интерфейс и аналитика

В разделе **Operate > Environments** доступны:
- **Deployment history:** Список всех прошедших деплоев.
- **Rollback:** Кнопка для быстрого возврата к предыдущей версии.
- **Environments Dashboard:** Единая панель для отслеживания состояния окружений в нескольких проектах.
- **Monitoring:** Ссылки на внешние дашборды (если настроено).

### Метрики DORA

GitLab автоматически рассчитывает ключевые показатели эффективности (Deployment Frequency, Lead Time for Changes) на основе данных об окружениях. Для корректности данных крайне важно правильно настраивать `deployment_tier` (см. раздел [Уровни окружений](#уровни-окружений-tiers)).

### Смотрите также

- **[Стратегии развертывания](../../Core_Concepts/deployment_strategies.md)** — обзор Rolling Update и Blue/Green.
- **[Проверка здоровья и откаты](../../Deployment_Strategies/deployment_health_checks_and_rollback.md)** — механизмы автоматизации.
- **[GitOps и GitLab](../../../GitOps/GitOps_overview.md)** — использование агента GitLab для Kubernetes.

> **Критичные изменения последних версий:**
>
> - **18.4**: Ключи `environment:kubernetes:namespace` и `flux_resource_path` перенесены в новый блок `environment:kubernetes:dashboard`.
> - **19.0**: Введен **Deployment Approval Policies** для централизованного управления правилами одобрения деплоев на уровне группы.
> - **19.2**: Поддержка **External Deployment Approvals** (интеграция с ServiceNow, Jira и др.).
