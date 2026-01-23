### Определения

-   **GitLab CI/CD**: Встроенная в GitLab платформа для автоматизации процессов сборки, тестирования и развертывания приложений при каждом изменении кода.
-   **Пайплайн (Pipeline)**: Полный конвейер CI/CD, состоящий из этапов и задач.
-   **Этап (Stage)**: Логическая группа задач в пайплайне. Этапы выполняются последовательно.
-   **Задача (Job)**: Конкретная команда или набор скриптов, выполняемых в рамках этапа. Задачи в одном этапе выполняются параллельно.
-   **GitLab Runner**: Агент, который выполняет задачи из пайплайна.
-   **`.gitlab-ci.yml`**: Файл конфигурации, в котором описывается структура пайплайна.
-   **Container Registry**: Хранилище для Docker-образов, встроенное в GitLab.
-   **Deploy Token**: Механизм аутентификации для доступа к Container Registry без использования учетных данных пользователя.

### Основные концепции

Этот учебник демонстрирует создание базового CI/CD пайплайна для простого Python-приложения с нуля. Пайплайн будет выполнять два основных этапа:
1.  **Сборка (`build`)**: Приложение упаковывается в Docker-образ, который затем публикуется в GitLab Container Registry.
2.  **Развертывание (`deploy`)**: Docker-образ загружается из Registry и запускается на целевом сервере.

Весь процесс автоматизирован и запускается при каждом коммите в основную ветку.

#### Переменные в GitLab CI

Для гибкости и безопасности в пайплайне используются переменные:
-   **Предопределенные переменные**: GitLab автоматически предоставляет переменные, такие как `CI_REGISTRY_IMAGE` (полное имя образа) и `CI_COMMIT_SHORT_SHA` (короткий хеш коммита для тегирования).
-   **Пользовательские переменные**: Для хранения секретов (например, токенов) используются переменные, определенные в настройках проекта (`Settings > CI/CD > Variables`).

### Практический сценарий: От кода до развертывания

#### Шаг 1: Подготовка проекта в GitLab

1.  **Создайте новый проект**:
    -   Нажмите **New project** -> **Create blank project**.
    -   Введите имя проекта (например, `my-python-app`). Рекомендуется использовать строчные буквы без пробелов.
    -   Установите **Visibility Level** в `Private`.
    -   Отметьте **Initialize repository with a README**.
2.  **Добавьте файлы приложения через Web IDE**:
    -   Нажмите **Edit -> Web IDE**.
    -   Создайте файл `app.py` с кодом вашего Python-приложения.
    -   Создайте файл `requirements.txt` со списком зависимостей.
    -   Создайте `Dockerfile` для контейнеризации приложения.

    **Пример `Dockerfile`:**
    ```dockerfile
    FROM python:3.9-slim
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install -r requirements.txt
    COPY app.py .
    EXPOSE 5000
    CMD ["python", "app.py"]
    ```
3.  **Закоммитьте изменения** в ветку `main`.

#### Шаг 2: Регистрация GitLab Runner с Shell Executor

Чтобы пайплайн мог выполняться, необходимо зарегистрировать Runner. Этот пример использует `shell` executor, который выполняет команды непосредственно на хост-машине.

1.  **Установите Runner** на ваш сервер, следуя [официальной инструкции](https://docs.gitlab.com/runner/install/).
2.  **Получите токен для регистрации**:
    -   В проекте GitLab перейдите в **Settings -> CI/CD -> Runners**.
    -   Нажмите **Register a project runner**.
    -   Скопируйте регистрационный токен.
3.  **Зарегистрируйте Runner на сервере**:
    ```bash
    sudo gitlab-runner register
    ```
    В процессе регистрации укажите:
    -   **URL GitLab**: `https://gitlab.com/`
    -   **Registration token**: Токен, скопированный ранее.
    -   **Description**: Имя для Runner'а (например, `shell-runner`).
    -   **Tags**: Тег для таргетирования задач (например, `shell`).
    -   **Executor**: `shell`.
4.  **Запустите Runner**:
    ```bash
    sudo gitlab-runner start
    ```
    Убедитесь, что в UI GitLab Runner появился с зеленым индикатором.

#### Шаг 3: Создание Deploy Token для доступа к Registry

1.  Перейдите в **Settings -> Repository -> Deploy Tokens**.
2.  Нажмите **Add token**.
3.  **Name**: `registry-token`.
4.  **Scopes**: Отметьте `read_registry` и `write_registry`.
5.  Нажмите **Create deploy token**.
6.  **Сохраните `username` и `password`**.
7.  Перейдите в **Settings -> CI/CD -> Variables** и создайте две переменные:
    -   `REGISTRY_USER`: `username` из Deploy Token.
    -   `REGISTRY_PASSWORD`: `password` из Deploy Token. Отметьте эту переменную как **Masked**.

#### Шаг 4: Создание файла `.gitlab-ci.yml`

Создайте в корне проекта файл `.gitlab-ci.yml`.

```yaml
stages:
  - build
  - deploy

variables:
  IMAGE_NAME: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

build_job:
  stage: build
  tags:
    - shell
  before_script:
    - docker login -u "$REGISTRY_USER" -p "$REGISTRY_PASSWORD" $CI_REGISTRY
  script:
    - docker build -t $IMAGE_NAME .
    - docker push $IMAGE_NAME

deploy_job:
  stage: deploy
  tags:
    - shell
  before_script:
    - docker login -u "$REGISTRY_USER" -p "$REGISTRY_PASSWORD" $CI_REGISTRY
  script:
    - docker pull $IMAGE_NAME
    # Останавливаем и удаляем предыдущий контейнер, если он существует
    - docker stop my-app || true
    - docker rm my-app || true
    # Запускаем новый контейнер
    - docker run -d --name my-app -p 5000:5000 $IMAGE_NAME
```

#### Шаг 5: Запуск и проверка пайплайна

1.  **Закоммитьте файл `.gitlab-ci.yml`**. GitLab автоматически запустит пайплайн.
2.  Перейдите в раздел **CI/CD -> Pipelines**, чтобы отследить выполнение.
3.  После успешного завершения обеих задач (`build_job` и `deploy_job`), проверьте, что приложение доступно на вашем сервере по порту `5000`.
4.  Проверьте, что новый образ появился в **Deploy -> Container Registry**.

### Дополнительная информация

-   **Идемпотентность развертывания**: Команды `docker stop my-app || true` и `docker rm my-app || true` обеспечивают идемпотентность скрипта развертывания. Пайплайн успешно отработает как при первом запуске, так и при последующих, заменяя старый контейнер на новый.
-   **Shell vs. Docker Executor**: `shell` executor прост в настройке, но менее безопасен и не обеспечивает изоляцию. Для производственных сред рекомендуется использовать [Docker Executor](../Advanced/gitlab_ci_runners_executors.md), который запускает каждую задачу в изолированном контейнере.
