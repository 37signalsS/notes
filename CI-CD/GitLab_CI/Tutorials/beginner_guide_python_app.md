# Настройка CI/CD для простого Python-приложения

## Определения

* **[Container Registry](../ci_cd_overview.md)**: Встроенное в GitLab хранилище для Docker-образов. В данном руководстве мы будем публиковать образ приложения в этот реестр.
* **[Deploy Token](../ci_cd_overview.md)**: Специальный токен для аутентификации в Container Registry без использования учетных данных пользователя. Это безопаснее, чем использовать личные пароли в CI-скриптах.

### Основные концепции

* **Код приложения (`app.py`, `requirements.txt`)**: Простое веб-приложение на Flask.
* **`Dockerfile`**: Инструкция для сборки Docker-образа, содержащего приложение и его зависимости. Подробнее о лучших практиках для Python см. [здесь](../../../Docker/Dockerfile/Docker_best_practices/python.md).
* **[GitLab Runner](../Advanced/gitlab_ci_runners_executors.md)**: Исполнитель, который получает и выполняет задачи из пайплайна. В этом примере используется `shell` executor, который выполняет команды непосредственно на хост-машине.
* **[`.gitlab-ci.yml`](../Concepts/gitlab_ci_basics.md)**: Файл конфигурации, описывающий стадии и шаги пайплайна.

### Практический сценарий: Настройка CI/CD для Python-приложения

#### Предварительные требования

1. **Проект в GitLab:** Пустой приватный проект с инициализированным `README`.
2. **Сервер для развертывания:** Виртуальная или физическая машина с доступом в интернет, на которой установлены **[Docker](https://docs.docker.com/engine/install/)** и **[GitLab Runner](runner_registration.md)**.

#### Шаг 1: Подготовка проекта и кода

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

#### Шаг 2: Регистрация GitLab Runner

Для выполнения нашего пайплайна нужен исполнитель (Runner). Подробное руководство по регистрации доступно [здесь](runner_registration.md).

> **Важно:** `shell` executor выполняет команды прямо на хост-машине. Это небезопасно и подходит только для обучения. В реальных проектах используйте **[Docker Executor](../Advanced/gitlab_ci_runners_executors.md)**.

1. **Установите Runner** на ваш сервер.
2. **Получите токен для регистрации**: В проекте GitLab перейдите в **Settings -> CI/CD -> Runners** и скопируйте токен.
3. **Зарегистрируйте Runner**, выполнив `sudo gitlab-runner register` и указав:
    * URL вашего GitLab.
    * Регистрационный токен.
    * Описание (e.g., `my-shell-runner`).
    * Тег (e.g., `shell-runner`). **Запомните этот тег**, он понадобится в `.gitlab-ci.yml`.
    * Executor: `shell`.
4. Убедитесь, что Runner запущен (`sudo gitlab-runner status`) и виден с зеленым индикатором в UI GitLab.

#### Шаг 3: Создание Deploy Token для доступа к Registry

Чтобы CI-пайплайн мог публиковать и скачивать образы из GitLab Container Registry, ему нужны права.

1. Перейдите в **Settings -> Repository -> Deploy Tokens**.
2. Нажмите **Add token**.
    * **Name**: `registry-token`
    * **Scopes**: Отметьте `read_registry` и `write_registry`.
3. Нажмите **Create deploy token**. **Сразу же сохраните `username` и `password`**, они больше не будут показаны.
4. Перейдите в **Settings -> CI/CD -> Variables** и создайте две [защищенные переменные](../Concepts/gitlab_ci_variables_secrets.md):
    * `REGISTRY_USER`: `username` из Deploy Token.
    * `REGISTRY_PASSWORD`: `password` из Deploy Token. Отметьте эту переменную как **Masked** и **Protected**.

#### Шаг 4: Создание `.gitlab-ci.yml`

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

#### Шаг 5: Запуск и проверка

1. **Закоммитьте файл `.gitlab-ci.yml`** в ветку `main`.
2. Перейдите в **CI/CD -> Pipelines** и наблюдайте за выполнением.
3. После успеха обеих задач:
    * Проверьте, что приложение доступно на вашем сервере по адресу `http://<server_ip>:5000`.
    * Убедитесь, что новый образ появился в **Deploy -> Container Registry**.

### Дополнительная информация

* **Идемпотентность развертывания**: Конструкция `docker ... || true` гарантирует, что пайплайн не упадет, если при первом развертывании контейнера с именем `my-app` еще не существует.
* **Безопасность**: Данный пример использует `shell` executor и развертывание через `docker run`. Это просто для понимания, но **небезопасно для производственных сред**. Такой подход дает CI-задачам полный контроль над хост-машиной.
* **Следующие шаги**:
  * Изучите и перейдите на **[Docker Executor](../Advanced/gitlab_ci_runners_executors.md)** для изоляции задач.
  * Используйте более надежные инструменты для развертывания, такие как **Docker Compose**, **Ansible** или **Kubernetes**.
  * Храните SSH-ключи и другие секреты в [переменных GitLab CI](../Concepts/gitlab_ci_variables_secrets.md), а не в файлах.
