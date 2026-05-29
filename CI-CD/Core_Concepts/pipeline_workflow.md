# Типичный поток пайплайна

## Определения

**Поток пайплайна (Pipeline Workflow)** — это последовательность [этапов (Stages)](./pipeline_glossary.md#этап-stage) и [задач (Jobs)](./pipeline_glossary.md#задача-job-step), которые выполняются для доставки кода от коммита до развертывания в рамках процесса **CI/CD (Continuous Integration / Continuous Delivery — непрерывная интеграция и непрерывная доставка)**.

Процесс инициируется [триггером](./pipeline_glossary.md#триггер-trigger) (например, `git push`) и выполняется [исполнителями (Runners)](./pipeline_glossary.md#исполнитель-runner-agent).

## Основные концепции

### Принципы построения пайплайна

1. **Fail-Fast (Падай быстро):** Чем раньше в пайплайне обнаруживается ошибка, тем дешевле ее исправление. Самые быстрые и дешевые проверки (линтинг, юнит-тесты) должны идти первыми.
2. **Параллелизм:** Всё, что может выполняться одновременно, должно выполняться одновременно. Например, юнит-тесты, линтеры для разных частей проекта, E2E-тесты в разных браузерах. Это радикально сокращает общее время выполнения пайплайна.
3. **Последовательность:** Зависимые этапы должны выполняться строго по порядку. Нельзя тестировать несобранный код или развертывать непротестированное приложение.

### Структура пайплайна по типу языка

* **Интерпретируемые языки (Node.js, Python):**
    `Lint` → `Unit Tests` → `Build` (сборка Docker-образа) → `Integration Tests` → `Deploy`.
    *Особенность:* Юнит-тесты могут запускаться до сборки финального артефакта.

* **Компилируемые языки (Go, Java):**
    `Lint` → `Compile` → `Unit Tests` → `Package` (сборка Docker-образа) → `Integration Tests` → `Deploy`.
    *Особенность:* Компиляция является обязательным шагом перед запуском тестов.

### Типичный поток пайплайна

Рассмотрим канонический пайплайн, обеспечивающий баланс скорости и качества:

1. **Инициация:** Создание **MR/PR (Merge Request / Pull Request — запрос на слияние или изменение кода)** в основную ветку (`main`).
2. **Валидация кода (1–2 мин):** Линтинг, форматирование, поиск утечек секретов (gitleaks, trufflehog).
3. **Сборка и unit-тесты (3–5 мин):** Компиляция/установка зависимостей, юнит-тесты, проверка покрытия.
4. **Сборка артефакта:** Сборка Docker-образа, проверка запускаемости (например, `docker compose up` с зависимостями).
5. **Сканирование безопасности (5–10 мин):** **SAST (Static Application Security Testing — статическое тестирование безопасности приложений)**, **SCA (Software Composition Analysis — анализ состава программного обеспечения)**, сканирование Docker-образа (Trivy).
6. **Push в registry:** Публикация иммутабельного артефакта с уникальным тегом (commit hash).
7. **Deploy на Staging:** Развертывание в предпроизводственную среду, smoke-тесты, health-check'и.
8. **Интеграционное и E2E-тестирование:** Запуск API-тестов и **E2E (End-to-End — сквозное тестирование)**.
9. **QA-проверки и Code Review:** Ручное тестирование специалистами **QA (Quality Assurance — обеспечение качества)** и проверка кода коллегами.
10. **Deploy на Production:** Ручное подтверждение (Continuous Delivery) или автоматическое (Continuous Deployment).

## Практические сценарии

### Пример на GitLab CI

Этот декларативный пайплайн иллюстрирует описанный выше поток.

```yaml
# Определение последовательности [Этапов (Stages)](./pipeline_glossary.md#этап-stage)
stages:
  - build
  - test
  - package
  - deploy

variables:
  APP_VERSION: "${CI_COMMIT_SHORT_SHA}"

# [Задача (Job)](./pipeline_glossary.md#задача-job-step) на этапе 'build'
build:
  stage: build
  script:
    - make deps
    - make build
  # Создание [артефактов](./pipeline_glossary.md#артефакт-artifact) для передачи на следующие этапы
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
  # Использование [кэширования](./pipeline_glossary.md#кэш-cache) для ускорения
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

# Задача развертывания в [среду](./pipeline_glossary.md#среда-environment) 'staging'
deploy_stage:
  stage: deploy
  needs: ["package"]
  script:
    - ./scripts/deploy.sh stage $APP_VERSION
  environment: "stage"

# Задача развертывания в [среду](./pipeline_glossary.md#среда-environment) 'production'
deploy_prod:
  stage: deploy
  needs: ["deploy_stage"]
  when: manual # [Триггер](./pipeline_glossary.md#триггер-trigger): ручной запуск
  only:
    - main
  script:
    - ./scripts/deploy.sh prod $APP_VERSION
  environment: "production"
```

### Пояснения к примеру

| Компонент | Описание |
| :--- | :--- |
| `stages` | Последовательность этапов: `build` → `test` → `package` → `deploy` |
| `needs` | Явное указание зависимостей между задачами |
| `artifacts` | Передача результатов сборки между этапами |
| `cache` | Сохранение зависимостей между запусками пайплайна |
| `environment` | Декларативное описание среды развертывания |
| `when: manual` | Требование ручного подтверждения для production |

## Дополнительная информация

### Связанные документы

* **[CI/CD: Обзор](../ci_cd_overview.md)** — общее введение в CI/CD.
* **[Глоссарий](./pipeline_glossary.md)** — определения ключевых терминов.
* **[GitLab CI Basics](../GitLab_CI/Concepts/gitlab_ci_basics.md)** — основы GitLab CI.
* **[Пример GitOps-пайплайна](../../GitOps/gitops_pipeline_example.md)** — пример пайплайна с GitOps.
* **[Deployment Strategies](./deployment_strategies.md)** — стратегии развертывания.
