# Типичный поток пайплайна

## Определения

**Поток пайплайна (Pipeline Workflow)** — это последовательность [этапов (Stages)](./pipeline_glossary.md#этап-stage) и [задач (Jobs)](./pipeline_glossary.md#задача-job-step), которые выполняются для доставки кода от коммита до развертывания в рамках процесса **CI/CD (Continuous Integration / Continuous Delivery — непрерывная интеграция и непрерывная доставка)**.

Процесс инициируется [триггером](./pipeline_glossary.md#триггер-trigger) (например, `git push`) и выполняется [исполнителями (Runners)](./pipeline_glossary.md#исполнитель-runner-agent).

## Основные концепции

### Принципы построения пайплайна

1. **Fail-Fast (Падай быстро):** Чем раньше в пайплайне обнаруживается ошибка, тем дешевле ее исправление. Самые быстрые и дешевые проверки (линтинг, юнит-тесты) должны идти первыми.
2. **Параллелизм:** Всё, что может выполняться одновременно, должно выполняться одновременно. Например, юнит-тесты, линтеры для разных частей проекта, E2E-тесты в разных браузерах. Это радикально сокращает общее время выполнения пайплайна.
3. **Последовательность:** Зависимые этапы должны выполняться строго по порядку. Нельзя тестировать несобранный код или развертывать непротестированное приложение.

### Каноническая структура пайплайна

Универсальная последовательность с воротами качества (quality gates):

`Lint` → `Test` → `Build` (Docker-образ) → `Push` (registry, immutable-тег) → `Deploy`.

Для компилируемых языков (Go, Java, Rust) компиляция происходит на этапах `Test` (языки со встроенной компиляцией, например `go test`) или на выделенном шаге перед тестами (`javac` → `mvn test`), но **Docker-образ собирается только после зелёных тестов** — нет смысла паковать то, что не работает.

### Типичный поток пайплайна

Рассмотрим канонический пайплайн, обеспечивающий баланс скорости и качества:

Идеальный пайплайн — это конвейер с **gates**, а не просто «запустить скрипты»:

1. **lint** — быстрая (1–2 мин) статическая проверка: golangci-lint, eslint, форматтер. Цель — поймать грубые ошибки до запуска тестов.
2. **test** — unit-тесты + **coverage gate** (≥80%). Публикация отчёта через artifacts → JUnit — GitLab подсвечивает провалы прямо в MR.
3. **build** — сборка Docker-образа (multi-stage). Build идёт **после** test — нет смысла собирать образ, если тесты не зелёные.
4. **push** — публикация в registry с **иммутабельным тегом**: `$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA`. Почему не `:latest`? `latest` — mutable, его можно перезаписать; по sha всегда можно воспроизвести, что именно запущено.
5. **deploy** — в dev-окружение автоматически после merge в main; в production — `when: manual`. Это не паранойя, а аудит: кто, когда, что задеплоил.

На зрелых командах между push и deploy добавляют: **scan** (Trivy CVE по образу), **validate** (migration lint), **review-окружение** на MR.

## Практические сценарии

### Пример на GitLab CI

```yaml
stages:
  - lint
  - test
  - build
  - push
  - deploy

variables:
  IMAGE_TAG: "${CI_COMMIT_SHORT_SHA}"

# 1. Lint — быстрая статическая проверка
lint:
  stage: lint
  script:
    - golangci-lint run ./...

# 2. Test — unit + coverage gate
test:
  stage: test
  script:
    - go test -coverprofile=coverage.out -covermin=80 ./...
  artifacts:
    reports:
      junit: junit.xml

# 3. Build — только если lint и test прошли
build:
  stage: build
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$IMAGE_TAG .
  needs: ["test"]

# 4. Push — immutable tag
push:
  stage: push
  script:
    - docker push $CI_REGISTRY_IMAGE:$IMAGE_TAG
  needs: ["build"]

# 5. Deploy (dev — авто, prod — manual)
deploy_dev:
  stage: deploy
  script:
    - ./deploy.sh dev $IMAGE_TAG
  needs: ["push"]
  only:
    - main
  environment: dev

deploy_prod:
  stage: deploy
  when: manual
  script:
    - ./deploy.sh prod $IMAGE_TAG
  needs: ["push"]
  only:
    - main
  environment: production
```

### Пояснения к примеру

| Компонент | Описание |
| :--- | :--- |
| `stages` | Последовательность этапов: `lint` → `test` → `build` → `push` → `deploy` |
| `needs` | Явное указание зависимостей между задачами (DAG) |
| `artifacts.reports.junit` | Публикация результатов тестов — GitLab показывает провалы в MR |
| `IMAGE_TAG` | Иммутабельный тег (`$CI_COMMIT_SHORT_SHA`) — воспроизводимость и аудит |
| `when: manual` | Ручное подтверждение деплоя в prod — аудит: кто, когда, что задеплоил |
| `only: main` | Деплой только из основной ветки |

## Дополнительная информация

### Связанные документы

* **[CI/CD: Обзор](../ci_cd_overview.md)** — общее введение в CI/CD.
* **[Глоссарий](./pipeline_glossary.md)** — определения ключевых терминов.
* **[GitLab CI Basics](../GitLab_CI/Concepts/gitlab_ci_basics.md)** — основы GitLab CI.
* **[Пример GitOps-пайплайна](../../GitOps/gitops_pipeline_example.md)** — пример пайплайна с GitOps.
* **[Deployment Strategies](./deployment_strategies.md)** — стратегии развертывания.
