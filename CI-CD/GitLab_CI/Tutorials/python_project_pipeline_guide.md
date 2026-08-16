# Комплексный CI/CD пайплайн для Python-проекта

## Определения

**Комплексный CI/CD Pipeline** — полностью автоматизированный процесс жизненного цикла ПО, включающий проверку качества кода, многоуровневое тестирование, сборку артефактов и автоматизированное развертывание в различные среды.

**`uv`** — сверхбыстрый менеджер пакетов и установщик Python, написанный на Rust. К 2026 году является индустриальным стандартом для CI/CD благодаря экстремальной скорости установки (до 10-100 раз быстрее `pip`) и встроенной поддержке виртуальных окружений.

**`ruff`** — высокопроизводительный линтер и форматер кода для Python, заменяющий собой целый стек инструментов (Flake8, isort, Black). Позволяет значительно ускорить стадию валидации.

**`id_tokens` (OIDC)** — современный механизм аутентификации (стандарт 2026 года), позволяющий GitLab Runner безопасно взаимодействовать с внешними сервисами (Vault, облачные провайдеры, Kubernetes) без использования долгоживущих секретов на основе доверия между провайдером личности (GitLab) и потребителем.

**GitLab Agent for Kubernetes (KAS)** — основной инструмент для безопасной интеграции GitLab с кластером. Обеспечивает двусторонний канал связи (**CI/CD Tunnel**), исключающий необходимость экспонирования API кластера наружу или хранения `KUBECONFIG` в переменных.

**SBOM (Software Bill of Materials)** — формализованный перечень всех библиотек и зависимостей, необходимый для аудита безопасности и соответствия стандартам цепочки поставок (**SLSA**).

## Основные концепции

### Архитектура и принцип Fail Fast

Современный пайплайн строится по принципу **Fail Fast**: наиболее быстрые и критичные проверки выполняются первыми. Это экономит ресурсы раннеров и время разработчиков.

1. **Стратегия ветвления (GitLab Flow):**
    - **`feature/*`**: Проходят стадию `validate` (линтеры, типы) и `unit-tests`.
    - **`develop`**: Проходит полный цикл проверок и деплоится в **Development**.
    - **`main`**: Финальные интеграционные тесты и деплой в **Staging**.
    - **Git-теги (`v*.*.*`)**: Инициируют релизный цикл с деплоем в **Production**.

2. **Zero Trust в CI/CD:**
    - Отказ от статических паролей и токенов в пользу кратковременных OIDC-токенов (`id_tokens`).
    - Использование GitLab Agent (KAS) с RBAC-ограничениями на уровне конкретных namespaces.
    - Сканирование образов и зависимостей на каждом этапе сборки.

3. **Оптимизация Python-сред:**
    - **Контейнеризация:** Использование Multi-stage Docker-сборок для минимизации размера и поверхности атаки.
    - **Управление зависимостями:** Использование `uv.lock` для гарантии детерминированности сборок.
    - **Кэширование:** Разделение кэша для загрузки пакетов (`uv cache`) и результатов тестирования.

## Практические сценарии

### Реализация пайплайна в `.gitlab-ci.yml`

#### Шаг 1: Глобальные настройки и правила

Используем `workflow:rules` для фильтрации запусков и типизации тегов образов.

```yaml
variables:
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.uv-cache"
  DOCKER_IMAGE_TAG: $CI_COMMIT_SHORT_SHA
  KUBE_CONTEXT: "my-group/infra:prod-agent"

workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      variables:
        DOCKER_IMAGE_TAG: "mr-$CI_MERGE_REQUEST_IID"
    - if: '$CI_COMMIT_BRANCH == "develop"'
      variables:
        DOCKER_IMAGE_TAG: "dev-$CI_COMMIT_SHORT_SHA"
    - if: '$CI_COMMIT_BRANCH == "main"'
      variables:
        DOCKER_IMAGE_TAG: "staging-$CI_COMMIT_SHORT_SHA"
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      variables:
        DOCKER_IMAGE_TAG: $CI_COMMIT_TAG

stages:
  - validate
  - build
  - test
  - deploy
  - release

include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Container-Scanning.yml
  - template: Security/Dependency-Scanning.gitlab-ci.yml

default:
  image: ghcr.io/astral-sh/uv:python3.13-bookworm-slim
  cache:
    key:
      files:
        - uv.lock
    paths:
      - .uv-cache
```

#### Шаг 2: Валидация и Сборка (Ruff + Kaniko)

```yaml
linting:
  stage: validate
  script:
    - uvx ruff check .
    - uvx ruff format --check .
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

build_and_sbom:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.23.1-debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$DOCKER_IMAGE_TAG
    # Генерация SBOM с использованием образа Syft (в отдельной джобе или через скрипт)
  artifacts:
    reports:
      cyclonedx: sbom.json
```

#### Шаг 3: Тестирование с использованием uv

```yaml
.pytest_base:
  stage: test
  script:
    - uv sync --frozen
    - uv run pytest tests/unit --junitxml=report.xml
  artifacts:
    reports:
      junit: report.xml

unit_tests:
  extends: .pytest_base
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.11", "3.12", "3.13"]

integration_tests:
  extends: .pytest_base
  script:
    - uv run pytest tests/integration
  rules:
    - if: $CI_COMMIT_BRANCH == "main" || $CI_COMMIT_BRANCH == "develop"
```

#### Шаг 4: Деплой через GitLab Agent (KAS) и Helm

```yaml
.helm_deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  id_tokens:
    K8S_TOKEN:
      aud: https://kubernetes.default.svc.cluster.local
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - >
      helm upgrade --install $RELEASE_NAME ./charts/app
        --namespace $NAMESPACE
        --set image.tag=$DOCKER_IMAGE_TAG
        --wait --atomic

deploy_dev:
  extends: .helm_deploy
  variables:
    RELEASE_NAME: "python-app-dev"
    NAMESPACE: "dev"
  environment:
    name: development
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy_prod:
  extends: .helm_deploy
  variables:
    RELEASE_NAME: "python-app-prod"
    NAMESPACE: "production"
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v[0-9]+\.[0-9]+\.[0-9]+$/'
      when: manual
```

## Технические нюансы и Тюнинг

### Оптимизация кэширования
Для Python-проектов при использовании `uv` критично кэшировать директорию `.uv-cache`. В отличие от `pip`, `uv` использует глобальный кэш для всех виртуальных окружений, что позволяет избежать повторной загрузки и компиляции пакетов (wheel) даже при смене версии Python в матрице тестов.

### Безопасность через ID Tokens
Использование `id_tokens` в сочетании с GitLab Agent (KAS) позволяет реализовать модель **Workload Identity Federation (WIF)**. Раннер получает временный JWT, который Kubernetes (или Vault) проверяет через OIDC. Это полностью устраняет риск компрометации статических токенов доступа.

### Тюнинг Docker-образа
Для Python в 2026 году рекомендуется использовать многостадийную сборку (multi-stage):
1.  **Stage 1 (Builder):** Установка `uv`, компиляция зависимостей, экспорт виртуального окружения.
2.  **Stage 2 (Runtime):** Использование максимально легкого базового образа (например, `distroless` или `python-slim`). Копирование только готового окружения.
3.  **Non-root:** Обязательный запуск приложения от пользователя с ограниченными правами (UID > 1000).

## Валидация и проверка

Для подтверждения успешной работы пайплайна выполните следующие действия:
1.  **Проверка визуализации тестов:** Убедитесь, что во вкладке **Tests** пайплайна отображаются результаты `pytest` (благодаря JUnit артефактам).
2.  **Аудит SBOM:** Скачайте артефакт `sbom.json` и проверьте его через `trivy sbom sbom.json` на наличие известных уязвимостей.
3.  **Логи KAS:** Проверьте вывод команды деплоя: там должен быть статус `atomic success`, подтверждающий корректный выкат в Kubernetes.

## Устранение неисправностей (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`uv sync` fails** | Несоответствие `uv.lock` и `pyproject.toml` | Обновите lock-файл локально: `uv lock` и закомитьте его. |
| **`KAS Context not found`** | Ошибка в имени проекта или агента | Проверьте формат: `group/project:agent-name`. Убедитесь, что агент разрешен для текущего проекта. |
| **`Permission denied` в Kaniko** | Неверные данные в `config.json` | Проверьте переменные `$CI_REGISTRY_USER` и пароль. Попробуйте использовать `id_tokens` для Registry. |
| **Тесты падают по таймауту** | Недостаточно ресурсов у раннера | Оптимизируйте тесты или увеличьте лимиты в конфигурации GitLab Runner. |

## Дополнительная информация

### Смотрите также

- **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — детальная настройка KAS.
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом через OIDC.
- **[Dockerfile для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)** — глубокая оптимизация сборки.
