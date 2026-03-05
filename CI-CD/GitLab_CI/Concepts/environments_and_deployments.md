### Определения

- **Окружение (Environment):** Логическое представление инфраструктуры, куда развертывается приложение (например, `development`, `staging`, `production`). Ключевое слово `environment` в `.gitlab-ci.yml` создает в GitLab соответствующий объект, который отслеживает историю развертываний.
- **Развертывание (Deployment):** Процесс доставки и запуска определенной версии приложения в конкретном окружении. Каждое успешное выполнение `job` с ключевым словом `environment` создает запись о развертывании.
- **Откат (Rollback):** Возврат окружения к предыдущей стабильной версии приложения. В GitLab это, как правило, означает перезапуск пайплайна от более раннего коммита.
- **Статическое окружение (Static Environment):** Долгоживущее, постоянное окружение, такое как `staging` или `production`.
- **Динамическое окружение (Dynamic Environment / Review App):** Временное окружение, автоматически создаваемое для тестирования изменений в изолированной среде (например, для каждой `feature-ветки` или `Merge Request`). Оно существует ограниченное время и затем уничтожается.

### Основные концепции

#### Создание и типы окружений

Окружения объявляются в файле `.gitlab-ci.yml` с помощью ключевого слова `environment`.

##### Статические окружения

Используются для постоянных стадий, таких как `staging` или `production`.

```yaml
deploy_production:
  stage: deploy
  script:
    - echo "Deploying to production..."
    - ./deploy.sh
  environment:
    name: production
    url: https://my-app.com # Добавляет кнопку "Open" в UI для прямого доступа
```

##### Динамические окружения (Review Apps)

Создаются на лету для каждой ветки, используя переменные GitLab CI для уникальности имени.

```yaml
deploy_review:
  stage: deploy
  script:
    - ./deploy-review.sh
  environment:
    name: review/$CI_COMMIT_REF_SLUG # Имя уникально для ветки ($CI_COMMIT_REF_SLUG - безопасное для URL имя ветки)
    url: https://$CI_COMMIT_REF_SLUG.example.com
    on_stop: stop_review_app # Указание задачи для очистки
    auto_stop_in: 1 day      # Автоматическое уничтожение через 1 день
  rules:
    - if: $CI_MERGE_REQUEST_ID # Создавать окружение только для Merge Requests
```

#### Уничтожение динамических окружений

Для освобождения ресурсов временные окружения необходимо удалять. Это делается с помощью задачи, указанной в `on_stop`.

```yaml
stop_review_app:
  stage: cleanup
  script:
    - echo "Deleting review app for $CI_COMMIT_REF_SLUG..."
    - ./cleanup-review-app.sh
  when: manual # Запускается по кнопке "Stop" или триггеру on_stop
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop # Явно указывает, что задача останавливает окружение
```

- **Ручное удаление:** Кнопка "Stop" в UI окружений запускает задачу `on_stop`.
- **Автоматическое удаление:** Параметр `auto_stop_in` автоматически запускает задачу `on_stop` по истечении указанного времени.

#### Масштабирование конфигурации с `extends`

Для избежания дублирования кода при настройке нескольких окружений используются YAML-шаблоны и `extends`.

1. **Определите шаблон:**

    ```yaml
    # templates/deploy.yaml
    .deploy_template:
      stage: deploy
      image: alpine:3.19
      # ... общие скрипты и настройки ...
    ```

2. **Используйте шаблон в задачах:**

    ```yaml
    # .gitlab-ci.yml
    include:
      - local: templates/deploy.yaml

    deploy_staging:
      extends: .deploy_template
      environment:
        name: staging
        url: https://staging.my-app.com

    deploy_production:
      extends: .deploy_template
      environment:
        name: production
        url: https://my-app.com
      rules:
        - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
          when: manual # Деплой в production только вручную
    ```

### Практические сценарии

#### Сценарий 1: Ручная задача отката с Helm

Для большего контроля над процессом отката можно создать явную задачу `rollback`, которая использует команды Helm.

```yaml
stages:
  - deploy
  - rollback

rollback_prod:
  stage: rollback
  # Рекомендуемый образ, содержащий kubectl и helm. Версию следует закрепить.
  image: alpine/k8s:1.29.0
  script:
    - echo "Rolling back production environment..."
    # $CI_PROJECT_PATH_SLUG - безопасное для URL имя проекта (group/project-name)
    # $CI_ENVIRONMENT_NAME - имя окружения, 'production' в данном случае
    - >
      helm rollback ${CI_PROJECT_PATH_SLUG}
      --namespace ${CI_PROJECT_PATH_SLUG}-${CI_ENVIRONMENT_NAME}
      --wait --timeout 300s
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual # Запускается только вручную из UI пайплайна
```

#### Сценарий 2: Концепция Review Apps с Kubernetes

Настройка динамических окружений (Review Apps) в Kubernetes является мощной практикой, позволяющей тестировать изменения в изолированной среде для каждого Merge Request.

**Высокоуровневый процесс выглядит так:**
1. Для каждого MR создается уникальный `namespace` в Kubernetes.
2. В этот `namespace` развертывается приложение с использованием Helm или Kustomize. Имя релиза и `hostname` в Ingress также делаются уникальными на основе имени ветки или ID мержа.
3. После слияния или закрытия MR соответствующий `namespace` и все его ресурсы автоматически удаляются.

Этот процесс обычно автоматизируется с помощью **оператора Kubernetes** или набора скриптов, которые вызываются из задач `deploy_review` и `stop_review_app`.

> Подробное пошаговое руководство по настройке Review Apps с Kubernetes доступно в документе:
> **[Настройка динамических окружений (Review Apps) с Kubernetes](../Tutorials/kubernetes_review_apps.md)**

### Дополнительная информация

#### Пользовательский интерфейс и откаты

В разделе **Deployments > Environments** GitLab предоставляет:

- Визуальную историю развертываний для каждого окружения.
- Кнопку **Re-deploy** для повторного запуска последней задачи.
- Встроенный механизм отката.

Нажатие кнопки **Rollback** не запускает специальную логику, а **перезапускает задачу (`job`) от предыдущего успешного развертывания**. Если развертывания идемпотентны и версионированы (например, через теги Docker-образов по хешу коммита), это действие безопасно вернет окружение к предыдущей стабильной версии.

> **Критичные изменения GitLab 18.x:**
> - **18.4**: `environment:kubernetes:namespace` deprecated → используйте `environment:kubernetes:dashboard:namespace`
> - **18.4**: `environment:kubernetes:flux_resource_path` deprecated → используйте `environment:kubernetes:dashboard:flux_resource_path`
> - **18.4**: Новая структура `environment:kubernetes:dashboard` для интеграции с Kubernetes

### Связанные документы

- **[Основы GitLab CI/CD](./gitlab_ci_basics.md)** — базовые концепции (Pipeline, Stage, Job).
- **[Переменные и управление секретами](./gitlab_ci_variables_secrets.md)** — работа с переменными окружения.
- **[Продвинутые рабочие процессы](../Advanced/gitlab_ci_advanced_workflow.md)** — правила `rules` и оптимизация пайплайнов.
- **[Переиспользуемые пайплайны](../Reusable_Pipelines/overview.md)** — использование `extends` и `include` для избежания дублирования.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — общее руководство по развертыванию в Kubernetes.
- **[Настройка Review Apps с Kubernetes](../Tutorials/kubernetes_review_apps.md)** — пошаговое руководство.
- **[Стратегии развертывания](../../Core_Concepts/deployment_strategies.md)** — Blue/Green, Canary, Rolling Update.
- **[GitOps Overview](../../../GitOps/GitOps_overview.md)** — Pull-модель развертывания.
