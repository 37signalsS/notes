# Настройка динамических окружений (Review Apps) с Kubernetes

## Определения

- **Review App:** Временное, изолированное окружение, автоматически создаваемое для каждой `feature-ветки` или `Merge Request`. Позволяет тестировать изменения в реальных условиях до слияния с основной веткой.
- **Оператор Kubernetes:** Специализированный контроллер, который расширяет API Kubernetes для управления сложными приложениями. В данном контексте оператор будет управлять жизненным циклом Review Apps.

## Основные концепции

Использование оператора для управления Review Apps — надежный и масштабируемый подход. Оператор следит за состоянием Merge Requests в GitLab и автоматически создает/удаляет ресурсы в Kubernetes.

Общие концепции динамических окружений описаны в **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)**.

## Практический сценарий: Пошаговая настройка

Это пошаговое руководство демонстрирует настройку динамических окружений с помощью оператора в Kubernetes.

### Шаг 1: Подготовка кластера и развертывание Оператора

Оператору, управляющему динамическими окружениями, нужен доступ к API Kubernetes.

1. **Создайте `ServiceAccount` и `ClusterRoleBinding`:**
    Это создаст специального пользователя `deploy-admin` в `namespace` `users` с правами администратора кластера.

    ```bash
    kubectl create namespace users
    kubectl create serviceaccount deploy-admin -n users
    kubectl create clusterrolebinding deploy-admin-binding --clusterrole=cluster-admin --serviceaccount=users:deploy-admin
    ```

2. **Получите токен доступа:**
    Этот токен будет использоваться для аутентификации оператора в Kubernetes.

    ```bash
    SECRET_NAME=$(kubectl get sa deploy-admin -n users -o jsonpath='{.secrets[0](name}')
    KUBE_TOKEN=$(kubectl get secret ${SECRET_NAME} -n users -o jsonpath='{.data.token}' | base64 --decode)
    echo $KUBE_TOKEN
    ```

3. **Настройте и запустите пайплайн Оператора:**
    - Форкните репозиторий оператора в свой GitLab.
    - В `Settings > CI/CD > Variables` проекта оператора добавьте переменные:
        - `KUBE_URL`: URL API-сервера вашего Kubernetes кластера.
        - `KUBE_TOKEN`: Полученный на предыдущем шаге токен.
    - Запустите пайплайн для ветки `main`, чтобы развернуть оператор в кластер.

### Шаг 2: Настройка основного приложения для работы с Review Apps

1. **Создайте токены доступа в GitLab:**
    - **GitLab API Access Token:** Перейдите в `User Settings > Access Tokens` и создайте токен с правами (scopes) `api`.
    - **Container Registry Deploy Token:** Перейдите в `Project Settings > Repository > Deploy Tokens` и создайте токен с правами `read_registry` и `write_registry`.

2. **Настройте переменные CI/CD в проекте приложения:**
    Перейдите в `Settings > CI/CD > Variables` и добавьте следующие переменные:
    - `KUBE_URL` и `KUBE_TOKEN` (из предыдущего шага).
    - `GITLAB_API_TOKEN` (созданный токен API).
    - `CR_DEPLOY_USER` и `CR_DEPLOY_PASSWORD` (имя пользователя и пароль из Deploy Token).

    > **Важно:** Секреты, такие как токены, рекомендуется хранить в защищенном виде. Используйте переменные типа `File` для многострочных секретов и `Masked` для однострочных, чтобы они не отображались в логах. Для максимальной безопасности используйте интеграцию с **[HashiCorp Vault](../Tutorials/vault_kubernetes_integration.md)**.

### Шаг 3: Конфигурация `.gitlab-ci.yml`

Теперь настроим пайплайн основного приложения для создания и удаления Review Apps.

```yaml
stages:
  - build
  - deploy
  - cleanup

build_image:
  stage: build
  # ... задача сборки Docker-образа и загрузки его в GitLab Registry ...

deploy_review:
  stage: deploy
  script:
    - ./deploy-review-app.sh # Скрипт, который обращается к оператору
  environment:
    name: review/$CI_COMMIT_REF_SLUG # Уникальное имя окружения
    url: https://$CI_COMMIT_REF_SLUG.example.com
    on_stop: stop_review_app       # Задача для очистки
    auto_stop_in: 1 day            # Автоматическое удаление через 1 день
  rules:
    - if: $CI_MERGE_REQUEST_ID # Запускать только для Merge Requests

stop_review_app:
  stage: cleanup
  script:
    - ./cleanup-review-app.sh # Скрипт, который обращается к оператору
  when: manual # Запускается по кнопке "Stop" или триггеру on_stop
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop # Явно указывает, что задача останавливает окружение
  rules:
    - if: $CI_MERGE_REQUEST_ID
      when: manual # Позволяет вручную удалять окружение из MR
```

### Жизненный цикл в действии

1. Создайте `feature-ветку` и **Merge Request (MR)** в `main`.
2. Пайплайн автоматически запустит задачу `deploy_review`, которая через оператор создаст изолированное окружение в Kubernetes.
3. В виджете MR появится ссылка **"View app"** для тестирования.
4. Для ручного удаления окружения нажмите кнопку **Stop** (■) на странице **Deployments > Environments** или в виджете MR. Это запустит задачу `stop_review_app`.
5. После слияния (merge) или закрытия MR, `auto_stop_in` автоматически инициирует удаление окружения.

## Дополнительная информация

**См. также:** **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)** (концепции), **[Интеграция GitLab CI с HashiCorp Vault](vault_kubernetes_integration.md)** (секреты), **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** (переменные).
