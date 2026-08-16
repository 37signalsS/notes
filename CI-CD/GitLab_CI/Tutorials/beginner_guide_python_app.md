# Настройка CI/CD для простого Python-приложения

## Определения

**uv** — сверхбыстрый менеджер пакетов и установщик Python, написанный на Rust. К 2026 году является индустриальным стандартом для CI/CD благодаря экстремальной скорости установки и встроенной поддержке виртуальных окружений.

**GitLab Container Registry** — встроенный в GitLab реестр Docker-образов. Позволяет хранить образы приложений в контексте проекта, обеспечивая тесную интеграцию с пайплайнами.

**CI_JOB_TOKEN** — кратковременный токен безопасности, автоматически создаваемый для каждой задачи. Используется для авторизации в Registry и API без необходимости ручного управления секретами.

**Multi-stage Build (Многостадийная сборка)** — метод оптимизации Docker-образов, позволяющий разделить этап сборки зависимостей (с компиляторами и инструментами) от этапа выполнения, что минимизирует размер и поверхность атаки финального образа.

**Docker Executor** — тип GitLab Runner, который запускает задачи в изолированных Docker-контейнерах. Это обеспечивает чистоту окружения и безопасность хост-системы.

## Основные концепции

### Зачем Python-приложению CI/CD?

Автоматизация жизненного цикла Python-приложения решает три ключевые проблемы:
1.  **Конфликты зависимостей:** Гарантирует, что код работает в той же версии интерпретатора и библиотек, что и у разработчика.
2.  **Регрессии:** Автоматический запуск тестов при каждом коммите предотвращает попадание багов в основную ветку.
3.  **Безопасность доставки:** Контейнеризация упаковывает приложение вместе со всеми зависимостями в неизменяемый артефакт, готовый к деплою.

### Принцип «Ворот качества» (Quality Gates)

Пайплайн не просто доставляет код, он проверяет его на соответствие стандартам:
*   **Static Analysis (SAST):** Проверка синтаксиса и стиля (PEP 8) через `ruff` или `flake8`.
*   **Unit Testing:** Проверка логики функций через `pytest`.
*   **Container Audit:** Проверка образа на наличие уязвимостей в системных библиотеках.

## Практические сценарии

### Предварительные требования

1.  **Репозиторий:** Приватный проект в GitLab.
2.  **Runner:** Установленный GitLab Runner с тегом `docker-runner`.
3.  **Доступ:** Права `Maintainer` в проекте для настройки переменных.

### Шаг 1: Подготовка кода приложения и зависимостей

Создайте минимальное Flask-приложение. Для управления зависимостями используем современный формат `pyproject.toml`.

**`app.py`:**
```python
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "ok", "message": "Hello from GitLab CI/CD 2026!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

**`pyproject.toml` (конфигурация uv/pip):**
```toml
[project]
name = "python-beginner-app"
version = "0.1.0"
dependencies = [
    "flask>=3.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.4.0",
]
```

### Шаг 2: Создание безопасного Dockerfile (Multi-stage + uv)

Используем `uv` для мгновенной сборки и `python:3.13-slim` для минимизации размера.

**`Dockerfile`:**
```dockerfile
# syntax=docker/dockerfile:1

# Stage 1: Сборка зависимостей (Builder)
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml ./
# Установка зависимостей в отдельную директорию без кэша в финальном слое
RUN uv pip install --system --no-cache-dir .

# Stage 2: Финальный образ (Runtime)
FROM python:3.13-slim

WORKDIR /app
# Создание непривилегированного пользователя
RUN useradd -m -u 10001 appuser

# Копируем установленные пакеты из builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY app.py .

RUN chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

# Использование exec-формы для корректной обработки сигналов (SIGTERM)
ENTRYPOINT ["python", "app.py"]
```

### Шаг 3: Настройка пайплайна `.gitlab-ci.yml`

Пайплайн разделен на проверку качества, сборку образа и деплой. Используем кэширование `uv` для ускорения задач.

```yaml
stages:
  - validate
  - build
  - deploy

variables:
  DOCKER_HOST: tcp://docker:2375
  DOCKER_TLS_CERTDIR: ""
  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

# Шаблон для задач, требующих Docker
.docker-env:
  image: docker:27.0
  services:
    - docker:27.0-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
  tags:
    - docker-runner

# Статическая проверка кода (Линтинг)
linting:
  stage: validate
  image: ghcr.io/astral-sh/uv:python3.13-slim
  script:
    - uv pip install --system ruff
    - ruff check .
  tags:
    - docker-runner

# Запуск тестов
unit-tests:
  stage: validate
  image: ghcr.io/astral-sh/uv:python3.13-slim
  script:
    - uv pip install --system .[dev]
    - pytest --junitxml=report.xml
  artifacts:
    when: always
    reports:
      junit: report.xml
  tags:
    - docker-runner

# Сборка и отправка образа в Registry
build-image:
  extends: .docker-env
  stage: build
  script:
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Пример деплоя на удаленный сервер
deploy-prod:
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh
    - chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - ssh $DEPLOY_USER@$DEPLOY_HOST "docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY && 
        docker pull $IMAGE_TAG && 
        docker stop my-app || true && 
        docker rm my-app || true && 
        docker run -d --name my-app -p 5000:5000 $IMAGE_TAG"
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  tags:
    - docker-runner
```

## Валидация и проверка

Для подтверждения успешной настройки выполните следующие действия:
1.  **Проверка статуса пайплайна:** В интерфейсе GitLab (Build -> Pipelines) все стадии должны быть отмечены зеленым цветом.
2.  **Просмотр артефактов:** Убедитесь, что в задаче `unit-tests` появился вкладка **Tests** с результатами `pytest`.
3.  **Проверка Registry:** Перейдите в **Deploy -> Container Registry**. Там должен появиться новый образ с тегом (коротким SHA коммита).
4.  **Локальный запуск:** Скачайте собранный образ локально и запустите его:
    ```bash
    docker run -it --rm -p 5000:5000 <registry_url>/<project_path>:<tag>
    ```

## Технические нюансы и Безопасность

### Почему `uv` вместо `pip`?
В CI/CD время — это деньги. `uv` устанавливает зависимости до 10-100 раз быстрее за счет реализации на Rust и эффективного управления кэшем. В данном руководстве мы используем `--system` для установки напрямую в системный Python контейнера, так как контейнер сам по себе обеспечивает изоляцию.

### Безопасность Non-root пользователя
Запуск приложения от `root` внутри контейнера — критическая уязвимость. Если злоумышленник взломает приложение, он получит права суперпользователя в контексте контейнера. Использование `USER appuser` минимизирует риски.

### Использование `CI_JOB_TOKEN`
Этот токен имеет права только на текущий проект и живет только время работы задачи. Это гораздо безопаснее, чем использование личных Access Tokens или статических паролей.

## Устранение неполадок (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Permission denied (Docker)** | Runner не имеет прав на Docker Socket | Убедитесь, что Runner настроен с привилегированным режимом для DinD или используйте Kaniko. |
| **ModuleNotFoundError** | Зависимость не установлена в Dockerfile | Проверьте, добавлен ли пакет в `pyproject.toml` и выполнен ли `uv pip install`. |
| **SSH connection timed out** | Закрыт порт 22 на целевом сервере | Проверьте настройки Firewall (Security Groups) на сервере деплоя. |
| **GitLab Registry 403 Forbidden** | Недостаточно прав у токена | Убедитесь, что в настройках проекта включен Container Registry. |

## Дополнительная информация

### Смотрите также

- **[Комплексный Pipeline для Python](./python_project_pipeline_guide.md)** — продвинутые сценарии с Kubernetes, SAST и Helm.
- **[Dockerfile: Лучшие практики для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)** — глубокая оптимизация слоев и кэширования.
- **[Регистрация GitLab Runner](./runner_registration.md)** — подробности настройки Docker Executor.
- **[Docker-in-Docker (DinD)](../../../Docker/docker-in-docker.md)** — детальный разбор механики и рисков.
