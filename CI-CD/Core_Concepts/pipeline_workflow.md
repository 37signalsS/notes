# Типичный поток и пример CI/CD пайплайна

### Определения

- **Поток пайплайна (Pipeline Workflow)** — это последовательность **[этапов (Stages)](./pipeline_elements.md#этап-stage)** и **[задач (Jobs)](./pipeline_elements.md#задача-job-step)**, которые выполняются для доставки кода от коммита до развертывания. Этот документ описывает типичный, обобщенный поток.

### Основные концепции: Типичный поток (Workflow)

Процесс инициируется **[триггером](./pipeline_elements.md#триггер-trigger)** (например, `git push`) и выполняется **[исполнителями (Runners)](./pipeline_elements.md#исполнитель-runner-agent)**.

1. **Инициация:** Разработчик создает `pull/merge request` в основную ветку (`main`).
2. **Сборка и статический анализ:** Запускается **[пайплайн](./pipeline_elements.md#пайплайн-pipeline)**, который собирает проект, запускает линтеры и SAST-сканеры.
3. **Автоматическое тестирование:** Выполняются unit-тесты, интеграционные и др.
4. **Сканирование безопасности:** Происходит сканирование зависимостей на уязвимости (SCA).
5. **Пакетирование:** Создается релизный **[артефакт](./pipeline_elements.md#артефакт-artifact)** (например, Docker-образ) и публикуется в **[репозиторий артефактов](../artifact_management.md)**.
6. **Развертывание на Staging:** Артефакт развертывается в предпроизводственную **[среду (Environment)](./pipeline_elements.md#среда-environment)**, где выполняются smoke-тесты.
7. **Развертывание на Production:**
    - **Continuous Delivery:** Требуется ручное подтверждение для развертывания.
    - **Continuous Deployment:** Развертывание происходит автоматически при успехе всех предыдущих шагов.

### Практические сценарии: Пример на GitLab CI

Этот декларативный пайплайн иллюстрирует описанный выше поток.

```yaml
# Определение последовательности [Этапов (Stages)](./pipeline_elements.md#этап-stage)
stages:
  - build
  - test
  - package
  - deploy

variables:
  APP_VERSION: "${CI_COMMIT_SHORT_SHA}"

# [Задача (Job)](./pipeline_elements.md#задача-job-step) на этапе 'build'
build:
  stage: build
  script:
    - make deps
    - make build
  # Создание [артефактов](./pipeline_elements.md#артефакт-artifact) для передачи на следующие этапы
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

# Задача на этапе 'test'
test:
  stage: test
  needs: ["build"] # Зависимость от задачи 'build'
  script:
    - make lint
    - make unit
    - make integration
  # Использование [кэширования](./pipeline_elements.md#кэш-cache) для ускорения
  cache:
    paths:
      - .cache/pip

# Задача на этапе 'package'
package:
  stage: package
  needs: ["test"]
  script:
    - docker build -t registry.example/app:$APP_VERSION .
    - docker push registry.example/app:$APP_VERSION
  artifacts:
    reports:
      dotenv: release.env

# Задача развертывания в [среду](./pipeline_elements.md#среда-environment) 'staging'
deploy_stage:
  stage: deploy
  needs: ["package"]
  script:
    - ./scripts/deploy.sh stage $APP_VERSION
  environment: "stage"

# Задача развертывания в [среду](./pipeline_elements.md#среда-environment) 'production'
deploy_prod:
  stage: deploy
  needs: ["deploy_stage"]
  when: manual # [Триггер](./pipeline_elements.md#триггер-trigger): ручной запуск
  only:
    - main
  script:
    - ./scripts/deploy.sh prod $APP_VERSION
  environment: "production"
```

---

## Пример: CI/CD Pipeline для Kubernetes с GitOps

Этот пример описывает современный пайплайн, ориентированный на развертывание в Kubernetes с использованием [**GitOps**-подхода](../../GitOps/GitOps_overview.md).

- **CI-инструмент:** GitHub Actions
- **CD-инструмент:** [ArgoCD](../../GitOps/ArgoCD/argocd_overview.md)

### Концепция

Пайплайн разделен на две части:

1. **CI (Continuous Integration):** Отвечает за проверку кода, сборку и публикацию артефактов (Docker-образ и Helm-чарт).
2. **CD (Continuous Delivery):** Выполняется ArgoCD, который отслеживает репозиторий с манифестами и синхронизирует состояние кластера.

### Поток выполнения

#### 1. Работа в фича-ветке (`feature-branch`)

- **Триггер:** `git push` в фича-ветку или создание Pull Request в `main`.
- **Действия (GitHub Actions):**
  - **Линтинг и статический анализ:** Проверка качества кода.
  - **Unit-тесты:** Быстрая проверка базовой логики.
  - **(Опционально) Сборка образа:** Для создания временных preview-окружений. Артефакт не публикуется в основной репозиторий.

#### 2. Слияние в `main` (CI-часть)

- **Триггер:** Merge Pull Request в ветку `main`.
- **Действия (GitHub Actions):**
    1. **Интеграционные тесты:** Полная проверка взаимодействия компонентов.
    2. **Сборка Docker-образа:** Образ собирается и тегируется версией (например, `v1.2.3` или `main-<short-sha>`).
    3. **Публикация Docker-образа:** Образ отправляется в OCI-совместимый реестр (Docker Hub, Harbor, GHCR).
    4. **Сборка и публикация Helm-чарта:**
        - Версия `appVersion` в `Chart.yaml` обновляется до версии Docker-образа.
        - Версия самого чарта (`version`) также инкрементируется.
        - Чарт упаковывается и публикуется в тот же OCI-реестр.
        - **Результат:** В реестре хранятся два связанных артефакта с одной версией: образ приложения и чарт для его развертывания.
    5. **Обновление GitOps-репозитория (Handoff to CD):**
        - CI-пайплайн автоматически клонирует отдельный репозиторий с манифестами Kubernetes (например, `my-apps-manifests`).
        - В этом репозитории он обновляет `values.yaml` или `Application` манифест для ArgoCD, указывая новую версию чарта.
        - Изменения коммитятся и пушатся в GitOps-репозиторий.

#### 3. Развертывание (CD-часть)

- **Триггер:** ArgoCD обнаруживает новый коммит в GitOps-репозитории.
- **Действия (ArgoCD):**
    1. ArgoCD сравнивает "живое" состояние в кластере с новым состоянием из Git.
    2. Обнаружив расхождение (новая версия чарта), он начинает процесс синхронизации.
    3. ArgoCD скачивает указанную версию Helm-чарта из OCI-реестра, рендерит шаблоны и применяет их в Kubernetes.
    4. Kubernetes, в свою очередь, скачивает новую версию Docker-образа и выполняет rolling update подами.

Этот подход полностью разделяет зоны ответственности: CI отвечает за артефакты, а CD — за декларативное состояние кластера, что является ключевым принципом GitOps.```
