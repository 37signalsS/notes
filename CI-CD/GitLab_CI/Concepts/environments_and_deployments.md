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
    name: review/$CI_COMMIT_REF_SLUG # Имя уникально для ветки
    url: https://$CI_COMMIT_REF_SLUG.example.com
    on_stop: stop_review_app # Указание задачи для очистки
    auto_stop_in: 1 day      # Автоматическое уничтожение через 1 день
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
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual # Запускается только вручную из UI пайплайна
  environment:
    name: production
  image:
    name: centosadmin/kubernetes-helm:3.1.2
    entrypoint: [""]
  script:
    - echo "Rolling back production environment..."
    - >
      helm rollback ${CI_PROJECT_PATH_SLUG}
      --namespace ${CI_PROJECT_PATH_SLUG}-${CI_ENVIRONMENT_NAME}
      --wait --timeout 300s
```

#### Сценарий 2: Настройка Review Apps с Kubernetes

Это пошаговое руководство демонстрирует настройку динамических окружений с помощью оператора в Kubernetes.

##### Шаг 1: Подготовка кластера и развертывание Оператора

Оператору, управляющему динамическими окружениями, нужен доступ к API Kubernetes.

1. **Создайте `ServiceAccount` и `ClusterRoleBinding`:**

    ```bash
    kubectl create namespace users
    kubectl create serviceaccount deploy-admin -n users
    kubectl create clusterrolebinding deploy-admin-binding --clusterrole=cluster-admin --serviceaccount=users:deploy-admin
    ```

2. **Получите токен доступа:**

    ```bash
    SECRET_NAME=$(kubectl get sa deploy-admin -n users -o jsonpath='{.secrets[0].name}')
    KUBE_TOKEN=$(kubectl get secret ${SECRET_NAME} -n users -o jsonpath='{.data.token}' | base64 --decode)
    echo $KUBE_TOKEN
    ```

3. **Настройте и запустите пайплайн Оператора:**
    - Форкните репозиторий оператора в свой GitLab.
    - В `Settings > CI/CD > Variables` проекта добавьте переменные `KUBE_URL` (URL API-сервера Kubernetes) и `KUBE_TOKEN` (полученный токен).
    - Запустите пайплайн для ветки `main`, чтобы развернуть оператор.

##### Шаг 2: Настройка основного приложения

1. **Создайте токены доступа:**
    - **GitLab API Access Token:** `User Settings > Access Tokens` с правами `api`.
    - **Container Registry Deploy Token:** `Project Settings > Repository > Deploy Tokens` с правами `read_registry` и `write_registry`.
2. **Настройте переменные CI/CD в проекте приложения:**
    - `KUBE_URL` и `KUBE_TOKEN` (из предыдущего шага).
    - `GITLAB_API_TOKEN` (созданный токен API).
    - `CR_DEPLOY_USER` и `CR_DEPLOY_PASSWORD` (из Deploy Token).
    - Рекомендуется хранить секреты в зашифрованном виде, например, с помощью `ansible-vault` и передавать их как переменные типа `File`.

##### Шаг 3: Жизненный цикл Review App

1. Создайте `feature-ветку` и **Merge Request (MR)** в `main`.
2. Пайплайн автоматически запустит задачу `deploy_review`, которая через оператор создаст изолированное окружение.
3. В виджете MR появится ссылка **"View app"** для тестирования.
4. Для удаления окружения нажмите кнопку **Stop** (■) на странице **Deployments > Environments**. Это запустит задачу, указанную в `on_stop`, которая очистит все ресурсы в Kubernetes.

### Дополнительная информация

#### Пользовательский интерфейс и откаты

В разделе **Deployments > Environments** GitLab предоставляет:

- Визуальную историю развертываний для каждого окружения.
- Кнопку **Re-deploy** для повторного запуска последней задачи.
- Встроенный механизм отката.

Нажатие кнопки **Rollback** не запускает специальную логику, а **перезапускает задачу (`job`) от предыдущего успешного развертывания**. Если развертывания идемпотентны и версионированы (например, через теги Docker-образов по хешу коммита), это действие безопасно вернет окружение к предыдущей стабильной версии.
