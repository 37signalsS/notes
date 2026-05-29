# Настройка CI/CD для простого Python-приложения

## Определения

- **Container Registry**: Встроенное в GitLab хранилище для Docker-образов. В данном руководстве мы публикуем образ приложения в этот реестр. Подробнее: [GitLab Container Registry](https://docs.gitlab.com/user/packages/container_registry/).
- **Deploy Token**: Специальный токен для аутентификации в Container Registry без использования учетных данных пользователя. Безопаснее, чем использование личных паролей в CI-скриптах. Подробнее: [GitLab Deploy Tokens](https://docs.gitlab.com/ee/user/project/deploy_tokens/).
- **GitLab Runner**: Исполнитель, который получает и выполняет задачи из пайплайна. Типы исполнителей: [GitLab CI Runners и Executors](../Advanced/gitlab_ci_runners_executors.md).
- **`.gitlab-ci.yml`**: Файл конфигурации в корне репозитория, описывающий стадии и шаги пайплайна. Основы: [GitLab CI Basics](../Concepts/gitlab_ci_basics.md).

## Основные концепции

- **Код приложения**: Простое веб-приложение на Flask (`app.py`, `requirements.txt`).
- **Dockerfile**: Инструкция для сборки Docker-образа с приложением и зависимостями. Лучшие практики: [Dockerfile для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md).
- **GitLab Runner (Shell Executor)**: В этом примере используется `shell` executor, выполняющий команды непосредственно на хост-машине. **Не рекомендуется для production** из-за отсутствия изоляции.
- **Регистрация Runner**: Пошаговая инструкция доступна в [Регистрация GitLab Runner](./runner_registration.md).

## Практические сценарии

### Предварительные требования

1. **Проект в GitLab**: Пустой приватный проект с инициализированным `README`.
2. **Сервер для развертывания**: Виртуальная или физическая машина с доступом в интернет, на которой установлены **[Docker](https://docs.docker.com/engine/install/)** и **[GitLab Runner](./runner_registration.md)**.

### Шаг 1: Подготовка проекта и кода

1. В вашем проекте GitLab создайте три файла: `app.py`, `requirements.txt` и `Dockerfile`.

    **`app.py` (Пример простого Flask-приложения):**

    ```python
    from flask import Flask
    app = Flask(__name__)

    @app.route('/')
    def hello_world():
        return 'Hello, GitLab CI/CD!'

    if __name__ == '__main__':
        app.run(host='0.0.0.0', port=5000)
    ```

    **`requirements.txt`:**

    ```
    Flask
    ```

    **`Dockerfile`:**

    ```dockerfile
    FROM python:3.9-slim
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install -r requirements.txt
    COPY app.py .
    EXPOSE 5000
    CMD ["python", "app.py"]
    ```

2. **Закоммитьте** эти три файла в ветку `main`.

### Шаг 2: Регистрация GitLab Runner

Для выполнения пайплайна нужен исполнитель (Runner). В данном примере используется `shell` executor.

> **Важно:** `shell` executor выполняет команды прямо на хост-машине. Это небезопасно и подходит только для обучения. В реальных проектах используйте **[Docker Executor](../Advanced/gitlab_ci_runners_executors.md)**.

Зарегистрируйте Runner, следуя основной инструкции: **[Регистрация с Shell Executor](./runner_registration.md#альтернативный-сценарий-регистрация-с-shell-executor)**.

При регистрации обязательно укажите тег `shell-runner` (он понадобится в `.gitlab-ci.yml`), а также выберите `shell` в качестве executor. После регистрации убедитесь, что Runner виден с зеленым индикатором в UI GitLab (раздел **Settings -> CI/CD -> Runners**).

### Шаг 3: Создание Deploy Token для доступа к Registry

Чтобы CI-пайплайн мог публиковать и скачивать образы из GitLab Container Registry, ему нужны права.

1. Перейдите в **Settings -> Repository -> Deploy Tokens**.
2. Нажмите **Add token**.
    - **Name**: `registry-token`
    - **Scopes**: Отметьте `read_registry` и `write_registry`.
3. Нажмите **Create deploy token**. **Сразу же сохраните `username` и `password`**, они больше не будут показаны.
4. Перейдите в **Settings -> CI/CD -> Variables** и создайте две [защищенные переменные](../Concepts/gitlab_ci_variables_secrets.md):
    - `REGISTRY_USER`: `username` из Deploy Token.
    - `REGISTRY_PASSWORD`: `password` из Deploy Token. Отметьте эту переменную как **Masked** и **Protected**.

### Шаг 4: Создание `.gitlab-ci.yml`

Создайте в корне проекта файл `.gitlab-ci.yml`.

```yaml
# Определяем этапы пайплайна. Выполняются последовательно.
stages:
  - build
  - deploy

# Глобально определяем переменную с полным именем и тегом образа.
# $CI_REGISTRY_IMAGE - предопределенная переменная, e.g., gitlab.example.com/user/project
# $CI_COMMIT_SHORT_SHA - короткий хеш коммита, e.g., a1b2c3d4
variables:
  IMAGE_NAME: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

build_job:
  stage: build
  tags:
    - shell-runner # Указываем, что эту задачу должен выполнять Runner с тегом 'shell-runner'
  before_script:
    # Логинимся в GitLab Registry перед выполнением основных команд
    - docker login -u "$REGISTRY_USER" -p "$REGISTRY_PASSWORD" $CI_REGISTRY
  script:
    # Собираем Docker-образ и тегируем его
    - docker build -t $IMAGE_NAME .
    # Публикуем образ в Container Registry
    - docker push $IMAGE_NAME

deploy_job:
  stage: deploy
  tags:
    - shell-runner # Эта задача также выполняется на нашем Runner'е
  script:
    # Скачиваем свежесобранный образ. Аутентификация не нужна, если токен не истек.
    - docker pull $IMAGE_NAME
    # Идемпотентно останавливаем и удаляем предыдущий контейнер
    - docker stop my-app || true
    - docker rm my-app || true
    # Запускаем новый контейнер из свежего образа
    - docker run -d --name my-app -p 5000:5000 $IMAGE_NAME
```

### Шаг 5: Запуск и проверка

1. **Закоммитьте файл `.gitlab-ci.yml`** в ветку `main`.
2. Перейдите в **CI/CD -> Pipelines** и наблюдайте за выполнением.
3. После успеха обеих задач:
    - Проверьте, что приложение доступно на вашем сервере по адресу `http://<server_ip>:5000`.
    - Убедитесь, что новый образ появился в **Deploy -> Container Registry**.

## Дополнительная информация

- **Идемпотентность развертывания**: Конструкция `docker ... || true` гарантирует, что пайплайн не упадет, если при первом развертывании контейнера с именем `my-app` еще не существует.
- **Безопасность**: Данный пример использует `shell` executor и развертывание через `docker run`. Это просто для понимания, но **небезопасно для производственных сред**. Такой подход дает CI-задачам полный контроль над хост-машиной.
- **Рекомендации для production**:
  - Используйте **[Docker Executor](../Advanced/gitlab_ci_runners_executors.md)** для изоляции задач.
  - Применяйте более надежные инструменты развертывания: **Docker Compose**, **Ansible** или **Kubernetes**.
  - Храните секреты в [переменных GitLab CI](../Concepts/gitlab_ci_variables_secrets.md), а не в файлах.
- **Смежные руководства**:
  - Комплексный пайплайн для Python-проекта: [Python Project Pipeline Guide](./python_project_pipeline_guide.md).
  - Регистрация Runner: [Регистрация GitLab Runner](./runner_registration.md).
  - Основы GitLab CI: [GitLab CI Basics](../Concepts/gitlab_ci_basics.md).
