# Настройка CI/CD для простого Python-приложения

## Определения

- **GitLab Container Registry**: Встроенное в GitLab хранилище (реестр) для Docker-образов. Позволяет хранить и версионировать образы приложений непосредственно в проекте. Подробнее: [GitLab Container Registry](https://docs.gitlab.com/user/packages/container_registry/).
- **CI_JOB_TOKEN**: Временный токен безопасности, автоматически создаваемый GitLab для каждой задачи. Используется для аутентификации в Registry и API без необходимости создания ручных секретов.
- **Deploy Token**: Специальный токен для аутентификации в Container Registry без использования учетных данных пользователя. В отличие от `CI_JOB_TOKEN`, он имеет длительный срок действия и может использоваться для доступа между проектами или внешними сервисами. Подробнее: [GitLab Deploy Tokens](https://docs.gitlab.com/ee/user/project/deploy_tokens/).
- **GitLab Runner**: Агент, который получает и выполняет задачи из пайплайна.
    - **Docker Executor (Рекомендуемый)**: Запускает каждую задачу в изолированном Docker-контейнере. Это стандарт безопасности для Production. Подробнее: [GitLab CI Runners и Executors](../Advanced/gitlab_ci_runners_executors.md).
    - **Shell Executor**: Выполняет команды непосредственно на хост-машине. Не рекомендуется для production из-за отсутствия изоляции и рисков для хост-системы.
- **.gitlab-ci.yml**: Файл конфигурации в корне репозитория, описывающий стадии (stages) и задачи (jobs) пайплайна. Основы: [GitLab CI Basics](../Concepts/gitlab_ci_basics.md).

## Основные концепции

### Качество и безопасность (Quality Gates)

В современном CI/CD недостаточно просто собрать и развернуть код. Пайплайн должен выступать «воротами качества»:
1. **Линтинг (Linting)**: Статический анализ кода на соответствие стандартам (например, PEP 8) с помощью `flake8`.
2. **Тестирование (Testing)**: Автоматический запуск Unit-тестов с помощью `pytest` для проверки бизнес-логики.
3. **Безопасность контейнера**: Сборка образов от имени **непривилегированного пользователя (non-root)** для минимизации ущерба в случае взлома приложения.

### Изоляция сред выполнения

Использование **Docker Executor** гарантирует, что каждая задача запускается в чистом окружении, не засоряя хост-систему зависимостями и не имея доступа к файлам других проектов. Для сборки образов внутри Docker Executor используется технология **Docker-in-Docker (DinD)**.

## Практические сценарии

### Предварительные требования

1. **Проект в GitLab**: Приватный репозиторий.
2. **Сервер для выполнения**: Linux-машина с установленным Docker.
3. **Runner**: Зарегистрированный Runner с **Docker Executor**. Инструкция: **[Регистрация GitLab Runner](./runner_registration.md)**. При регистрации укажите тег `docker-runner`.

### Шаг 1: Подготовка проекта и кода

Создайте в корне проекта следующие файлы:

**`app.py` (Flask-приложение):**
```python
from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello():
    return 'Hello, GitLab CI/CD!'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

**`test_app.py` (Unit-тест):**
```python
from app import app

def test_hello():
    client = app.test_client()
    response = client.get('/')
    assert response.status_code == 200
    assert response.data == b'Hello, GitLab CI/CD!'
```

**`requirements.txt`:**
```text
Flask
pytest
flake8
```

### Шаг 2: Безопасный Dockerfile (Multi-stage + Non-root)

Использование многостадийной сборки позволяет оставить инструменты разработки (компиляторы) в первом слое, а в финальный образ скопировать только готовое приложение.

**`Dockerfile`:**
```dockerfile
# Stage 1: Сборка зависимостей
FROM python:3.12-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Финальный образ (Runtime)
FROM python:3.12-slim
# Docker Security: Создание непривилегированного пользователя
RUN useradd -m appuser
USER appuser
WORKDIR /home/appuser

# Копируем установленные пакеты из builder
COPY --from=builder /root/.local /home/appuser/.local
COPY app.py .

# Обновляем PATH для доступа к установленным пакетам
ENV PATH=/home/appuser/.local/bin:$PATH
EXPOSE 5000
CMD ["python", "app.py"]
```

### Шаг 3: Аутентификация в Container Registry

Для работы пайплайна с реестром образов существует два подхода:

#### Способ А: Использование CI_JOB_TOKEN (Рекомендуемый)
GitLab автоматически авторизует Runner. В `before_script` достаточно выполнить:
```bash
docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" $CI_REGISTRY
```

#### Способ Б: Использование Deploy Token (Для внешнего доступа)
Если вам нужно скачивать образ вне GitLab (например, на продакшн-сервер через `docker compose` без раннера) или в другом проекте:
1. Перейдите в **Settings -> Repository -> Deploy Tokens**.
2. Создайте токен с правами `read_registry` и `write_registry`.
3. Сохраните `username` и `password` в переменные проекта `REGISTRY_USER` и `REGISTRY_PASSWORD`.

### Шаг 4: Конфигурация `.gitlab-ci.yml`

Пайплайн использует Docker-в-Docker для сборки и изолированные образы для тестов.

```yaml
stages:
  - lint
  - test
  - build
  - deploy

variables:
  DOCKER_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  DOCKER_HOST: tcp://docker:2375 # Настройка для DinD
  DOCKER_TLS_CERTDIR: ""

# Настройки для сборки образов через Docker Executor
.docker_setup:
  image: docker:24.0.5
  services:
    - docker:24.0.5-dind
  before_script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_JOB_TOKEN" $CI_REGISTRY
  tags:
    - docker-runner

lint_job:
  stage: lint
  image: python:3.12-slim
  script:
    - pip install flake8
    - flake8 . --exclude .venv
  tags:
    - docker-runner

test_job:
  stage: test
  image: python:3.12-slim
  script:
    - pip install -r requirements.txt
    - pytest
  tags:
    - docker-runner

build_job:
  extends: .docker_setup
  stage: build
  script:
    - docker build -t $DOCKER_IMAGE .
    - docker push $DOCKER_IMAGE

deploy_job:
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    # Деплой на удаленный сервер через SSH (Docker Security: изоляция от хоста раннера)
    - ssh $DEPLOY_USER@$DEPLOY_HOST "docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY && 
        docker pull $DOCKER_IMAGE && 
        docker stop my-app || true && 
        docker rm my-app || true && 
        docker run -d --name my-app -p 5000:5000 $DOCKER_IMAGE"
  environment:
    name: production
  tags:
    - docker-runner
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual # Ручной запуск деплоя для безопасности
```

## Технические нюансы и Безопасность

### Почему Docker Executor?
В отличие от Shell, Docker Executor предотвращает "отравление" хост-машины. Если приложение в пайплайне попытается выполнить `rm -rf /`, это затронет только временный контейнер, а не сервер с раннером.

### Docker-in-Docker (DinD)
Для сборки образов используется сервис `docker:dind`. Это позволяет запускать демон Docker внутри контейнера-задачи. Подробный разбор механики работы, рисков безопасности и методов оптимизации DinD приведен в SSoT-файле: **[Docker-in-Docker (DinD)](../../../Docker/docker-in-docker.md)**.

### Безопасность SSH при деплое
В примере `deploy_job` используется `ssh-agent`. Это позволяет безопасно передавать приватный ключ в задачу через переменную GitLab CI/CD (тип `File` или `Variable` с маскированием) без сохранения его на диске раннера.

## Дополнительная информация

### Рекомендации для масштабирования
- **Кэширование**: Используйте `cache` для директории `pip`, чтобы ускорить стадии `lint` и `test`.
- **Artifacts**: Сохраняйте отчеты о тестировании в формате JUnit для отображения в интерфейсе GitLab.
- **Ansible**: Для сложных развертываний замените SSH-команды на плейбуки Ansible. Подробнее: **[Интеграция Ansible](./ansible_integration.md)**.

### Смотрите также
- **[Комплексный Pipeline для Python](./python_project_pipeline_guide.md)** — продвинутые сценарии с Kubernetes и Helm.
- **[Регистрация GitLab Runner](./runner_registration.md)** — подробнее о токенах `glrt-`.
- **[Dockerfile для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)** — глубокая оптимизация.
