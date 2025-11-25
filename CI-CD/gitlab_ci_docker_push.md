# Управление Docker-образами в GitLab CI: Загрузка в Registry

После успешной сборки и тестирования приложения следующим шагом в пайплайне CI/CD часто является сохранение готового Docker-образа в Container Registry. Это позволяет использовать образ для последующего развертывания.

См. также:
*   [Основы GitLab CI/CD](./gitlab_ci_basics.md)
*   [GitLab CI как конструктор Workflow](./gitlab_ci_workflow_constructor.md)
*   [Реестры Docker](../Docker/docker_registries.md)

## 1. Добавление стадии `push` в `.gitlab-ci.yml`

Для загрузки собранного Docker-образа в GitLab Container Registry необходимо добавить новую стадию в ваш `.gitlab-ci.yml` файл.

### 1.1. Пример конфигурации

Предположим, у вас уже есть стадии `build` и `test`. Добавим стадию `push`:

```yaml
stages:
  - build
  - test
  - push # Добавляем новую стадию для загрузки образа

variables:
  DOCKER_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA # Имя образа с тегом, включающим короткий SHA коммита

build_job:
  stage: build
  script:
    - echo "Performing build..."
    - docker build -t $DOCKER_IMAGE . # Собираем Docker образ

test_job:
  stage: test
  script:
    - echo "Running tests..."
    - # Ваши команды для тестирования

push_to_registry:
  stage: push
  image: docker:latest # Используем образ Docker для выполнения команд
  before_script:
    # Аутентификация в GitLab Container Registry
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" "$CI_REGISTRY"
  script:
    - echo "Pushing Docker image to registry..."
    - docker push "$DOCKER_IMAGE" # Загружаем образ в Registry
  rules:
    # Запускаем эту задачу только для ветки 'main' (или 'master')
    # Это помогает поддерживать чистоту Registry, сохраняя только проверенные образы.
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### 1.2. Пояснения к конфигурации

*   **`push` стадия:** Новая стадия, которая будет выполняться после успешного завершения стадий `build` и `test`.
*   **`image: docker:latest`:** Для выполнения команд `docker login` и `docker push` в задаче `push_to_registry` используется официальный образ `docker`.
*   **`before_script`:** Этот блок выполняется перед основным `script` задачи. Здесь осуществляется аутентификация в GitLab Container Registry.
    *   `docker login`: Команда для входа в Docker Registry.
    *   `$CI_REGISTRY_USER`: Встроенная переменная GitLab CI/CD, содержащая имя пользователя для доступа к Registry (обычно `gitlab-ci-token`).
    *   `$CI_JOB_TOKEN`: Встроенная переменная, предоставляющая временный и ограниченный токен для текущего пайплайна, используемый для аутентификации в Registry. Это безопасный способ работы с секретами.
    *   `$CI_REGISTRY`: Встроенная переменная, указывающая URL вашего GitLab Container Registry.
*   **`script`:** Основной блок с командами.
    *   `docker push "$DOCKER_IMAGE"`: Команда для загрузки образа. Мы используем переменную `DOCKER_IMAGE`, определенную в блоке `variables`, чтобы обеспечить согласованность имени и тега образа. Тегом обычно служит короткий SHA коммита (`$CI_COMMIT_SHORT_SHA`) для уникальной идентификации версии.
*   **`rules` (`only`):** Директива `rules` (в старых версиях GitLab CI использовалась `only`) позволяет контролировать, когда задача будет выполняться.
    *   `if: '$CI_COMMIT_BRANCH == "main"'`: Эта задача будет запускаться только при коммитах в ветку `main` (или `master`). Это распространенная практика для гарантии того, что в Registry попадают только стабильные, готовые к продакшену образы, и для предотвращения заполнения Registry тестовыми или промежуточными сборками из других веток.

## 2. Проверка в GitLab Container Registry

После успешного выполнения пайплайна вы сможете увидеть загруженный Docker-образ в разделе **Deployments > Container Registry** вашего проекта в GitLab. Образ будет иметь тег, соответствующий короткому SHA коммита, что обеспечивает легкую трассировку и управление версиями.
