# Основы GitLab CI/CD

## Определения

Иерархия компонентов в GitLab CI/CD строится по принципу «от общего к частному». Подробный глоссарий — в [pipeline_glossary.md](../../Core_Concepts/pipeline_glossary.md).

*   **[Pipeline](https://docs.gitlab.com/ci/pipelines/)**: Высокоуровневая структура, определяющая полный цикл CI/CD. Состоит из стадий (Stage) и запускается по событиям (коммит, Merge Request, расписание).
*   **[Stage](https://docs.gitlab.com/ci/yaml/stages/)**: Группирует задания (Job) и определяет порядок их выполнения. Задания внутри одной стадии выполняются параллельно, сами стадии — последовательно.
*   **[Job](https://docs.gitlab.com/ci/jobs/)**: Минимальная единица работы. Выполняет набор команд (скриптов) для сборки, тестирования или развертывания.
*   **[Runner](https://docs.gitlab.com/runner/)**: Приложение, выполняющее задания. Устанавливается на сервер или в контейнер и опрашивает GitLab на предмет новых задач. Настройка — в [gitlab_ci_runners_executors.md](../Advanced/gitlab_ci_runners_executors.md).
*   **[Artifacts](https://docs.gitlab.com/ci/jobs/job_artifacts/)**: Файлы и директории, сохраняемые после выполнения задачи и передаваемые между стадиями внутри одного пайплайна.
*   **[Cache](https://docs.gitlab.com/ci/yaml/cache/)**: Временное хранилище для ускорения повторных запусков (например, `node_modules`). Не гарантирует сохранность данных между запусками.
*   **[Component](https://docs.gitlab.com/ee/ci/components/)**: Переиспользуемая единица конфигурации CI/CD, хранящаяся в **CI/CD Catalog**. Современный стандарт для DRY-подхода.
*   **[CI/CD Variables](./gitlab_ci_variables_secrets.md)**: Динамические параметры, управляющие поведением пайплайна без изменения кода. Делятся на переменные окружения и файлы.
*   **[Environments](./environments_and_deployments.md)**: Виртуальные пространства (dev, staging, prod), куда развертывается приложение. Позволяют отслеживать историю деплоев и выполнять откаты (Rollback).

## Базовые концепции

### Архитектура GitLab CI/CD

Для работы современной системы (v17.x–19.x) необходимы следующие компоненты (подробнее — в [gitlab_platform_architecture.md](./gitlab_platform_architecture.md)):

1.  **GitLab Server** — управляет репозиториями, отслеживает изменения и инициирует пайплайны. Основные зависимости: PostgreSQL 17+, Redis 7+ (или Valkey).
2.  **GitLab Runner** — агент, выполняющий задания. Основные типы исполнителей (Executors):
    *   **Docker Executor** — изоляция в контейнерах (стандарт индустрии).
    *   **Kubernetes Executor** — запуск заданий в подах K8s.
    *   **Shell Executor** — прямой запуск на хосте (для простых сценариев).
    *   **VirtualBox/Parallels Executor** — изоляция через виртуальные машины.
3.  **GitLab Secrets Manager** — встроенное защищенное хранилище секретов, заменяющее внешние Vault-решения для базовых CI/CD сценариев.
4.  **GitLab Agent for Kubernetes (KAS)** — обеспечивает безопасное двустороннее соединение между GitLab и кластерами Kubernetes.
5.  **Registry (Container/Package)** — встроенные хранилища для Docker-образов и пакетов (NPM, Maven, PyPI), обеспечивающие замкнутый цикл сборки и хранения.
6.  **`.gitlab-ci.yml`** — конфигурационный файл, описывающий логику пайплайна.

Для выполнения самих сборок внутри Runner могут использоваться дополнительные инструменты:
- **Kaniko** — сборка Docker-образов в контейнере без демона (рекомендуется для сред с ограничениями безопасности).
- **BuildKit** — современный движок сборки, используемый по умолчанию в Docker 23.0+.
- **werf** — инструмент для сборки и доставки образов с интеграцией в GitLab CI.

```text
[Разработчик] --push--> [GitLab Server] <---(KAS)---> [Kubernetes Cluster]
                                |
                                +--- [Secrets Manager]
                                |
                                v
                          [GitLab Runner]
                          |  (Executors)
                          v
                    [Docker / K8s / Shell]
```

Подробная информация о типах Runner и Executor — в [gitlab_ci_runners_executors.md](../Advanced/gitlab_ci_runners_executors.md). Установка self-hosted GitLab с Runner — в [self_hosted_installation.md](../Tutorials/self_hosted_installation.md).

### Типовые стадии пайплайна

Стандартный жизненный цикл микросервиса (например, на Java/Spring) включает:

1.  **Check/Lint**: Быстрая проверка стиля кода и форматирования (Checkstyle, Prettier), отсекающая опечатки на ранних стадиях.
2.  **SAST/Quality**: Статический анализ безопасности и качества кода ([SonarQube / SonarCloud](../../Tools/sonarqube.md)).
3.  **Build/Artifact**: Компиляция кода и создание исполняемого артефакта (например, **JAR**-файл для Java). Артефакт сохраняется в `artifacts` для передачи на следующие шаги.
4.  **Unit Tests**: Запуск модульных тестов для проверки логики собранного артефакта.
5.  **Docker Build**: Упаковка артефакта в Docker-образ. Часто используется **Kaniko** — инструмент для сборки образов внутри контейнера без необходимости в привилегированном режиме или Docker-демоне.
6.  **Push**: Загрузка проверенного Docker-образа в Registry (например, GitLab Container Registry).
7.  **Deploy**: Развертывание в Kubernetes (Dev, Test, Prod) автоматически или вручную.

Для языков без компиляции (Python, Node.js) этап **Build** заменяется на установку зависимостей и линтинг, а артефактом становится сам исходный код или собранный дистрибутив (`dist/`, `build/`). Сборка Docker-образа остается отдельным этапом.

### Типы пайплайнов

В зависимости от события запуска выделяют несколько видов конвейеров:

*   **Branch Pipelines**: Запускаются при каждом пуше в ветку.
*   **Merge Request Pipelines**: Запускаются только для MR. Позволяют использовать `detached` пайплайны для проверки кода перед слиянием.
*   **Scheduled Pipelines**: Запускаются по расписанию (аналог cron). Используются для ночных сборок или сканирования безопасности.
*   **API-triggered Pipelines**: Инициируются внешними системами через REST API или Webhooks. Позволяют реализовать сложные сценарии межсистемной интеграции ([подробнее](../Advanced/api_and_webhooks_automation.md)).
*   **Parent-Child Pipelines**: Один пайплайн запускает другой (дочерний) в том же или другом проекте. Это позволяет разделять сложные процессы (например, сборка фронтенда и бэкенда).
*   **Multi-project Pipelines**: Взаимодействие пайплайнов разных проектов через мост (bridge job).

### Разница между артефактами и кэшем

| Характеристика | Артефакты (`artifacts`) | Кэш (`cache`) |
| :--- | :--- | :--- |
| **Назначение** | Передача результатов между стадиями одного пайплайна | Ускорение сборки между разными пайплайнами (`node_modules`) |
| **Жизненный цикл** | Удаляются автоматически по `expire_in` | Сохраняются до очистки или истечения TTL |
| **Доступность** | Можно скачать через UI GitLab | Недоступны для ручного скачивания |
| **Хранение** | Централизованно на сервере GitLab | Локально на Runner или в S3 (Distributed Cache) |

Подробное сравнение и стратегии оптимизации — в **[Кэширование и артефакты в GitLab CI](../Advanced/gitlab_ci_caching/caching_overview.md)**.

### Конфигурация через `.gitlab-ci.yml`

Файл определяет структуру и поведение CI/CD процессов в проекте.

> **Важно (GitLab 18.x/19.x):** Глобальные ключевые слова `before_script`, `image`, `cache` на верхнем уровне считаются устаревшими. Рекомендуется использовать блок `default`.

### Ключевые слова для управления пайплайном

#### Структурные настройки

*   **`stages`**: Список и порядок стадий.
*   **`default`**: Набор общих настроек для всех заданий (образ, скрипты подготовки, кэш).
*   **`variables`**: [Переменные окружения](./gitlab_ci_variables_secrets.md). Рекомендуется использовать **GitLab Secrets Manager** для чувствительных данных.
*   **`workflow:rules`**: Глобальные правила запуска всего пайплайна. Позволяют избежать дублирования пайплайнов (например, при одновременном открытии MR и пуше в ветку).

#### Параметры заданий

*   **`script`**: Обязательный блок с shell-командами.
*   **`needs`**: Создает направленный ациклический граф (DAG), позволяя запускать задания сразу после готовности зависимостей, не дожидаясь завершения всей стадии.
*   **`rules`**: Современный и гибкий стандарт управления условиями (замена устаревшим `only`/`except`).
    *   **Почему `rules`?**: Поддерживают сложные логические выражения (`if`, `changes`, `exists`), позволяют изменять атрибуты задания (например, `when: manual` или `variables`) в зависимости от условий.
*   **`environment`**: Описание целевой среды.

#### Безопасность и доступ

*   **CI/CD Job Token Scope**: Начиная с версии **18.0**, доступ к проектам через `CI_JOB_TOKEN` ограничен белым списком (Allowlist) по умолчанию. Необходимо явно разрешать входящие и исходящие запросы между проектами.
*   **Scan Execution Policies**: Принудительное выполнение проверок безопасности, которое невозможно переопределить в `.gitlab-ci.yml` проекта.

### Взаимосвязь `needs` и `dependencies`

*   **`needs`**: Управляет **порядком выполнения** (DAG).
*   **`dependencies`**: Управляет **загрузкой артефактов**. Если используется `needs`, то по умолчанию загружаются только артефакты от указанных в нем заданий.

### Механизмы переиспользования

Для соблюдения принципа DRY используются:

1.  **`extends`**: Наследование настроек от скрытых заданий.
2.  **`!reference`**: Копирование блоков кода.
3.  **`include`**: Подключение внешних файлов или **компонентов из CI/CD Catalog**.

Подробности — в [создании переиспользуемых пайплайнов](../Reusable_Pipelines/overview.md).

## Практические сценарии

### Пример базового пайплайна

```yaml
# Глобальные правила для предотвращения дублирования пайплайнов
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

stages:
  - build
  - test
  - deploy

variables:
  APP_ENV: production

# Настройки по умолчанию (GitLab 19.x)
default:
  image: python:3.12
  before_script:
    - pip install -r requirements.txt
    # Duo Assistant: Installing core dependencies for Python 3.12 environment

build_job:
  stage: build
  script:
    - python -m build
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

test_job:
  stage: test
  needs: ["build_job"]
  script:
    - pytest -v
    # → Executing unit tests...

deploy_job:
  stage: deploy
  environment:
    name: production
    url: https://app.example.com
  needs: ["test_job"]
  dependencies: ["build_job"]
  script:
    - ./scripts/deploy.sh $CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

### Практические примеры для DevOps/SRE/sysadmin

#### Инфраструктура как код (IaC) пайплайн

```yaml
stages:
  - validate
  - plan
  - apply

variables:
  TF_ROOT: "terraform/"
  TF_STATE_NAME: "production"

.init: &terraform_init
  image: hashicorp/terraform:1.9
  before_script:
    - cd $TF_ROOT
    - terraform init -backend-config="backend.hcl"

validate:
  <<: *terraform_init
  stage: validate
  script:
    - terraform validate
    - terraform fmt -check

plan:
  <<: *terraform_init
  stage: plan
  script:
    - terraform plan -out=tfplan -var-file="production.tfvars"
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 1 day

apply:
  <<: *terraform_init
  stage: apply
  script:
    - terraform apply -auto-approve tfplan
  dependencies:
    - plan
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  allow_failure: false
```

#### Развертывание с Ansible

```yaml
stages:
  - lint
  - test
  - deploy

ansible-lint:
  stage: lint
  image: cytopia/ansible-lint
  script:
    - ansible-lint roles/
    - ansible-lint playbooks/

ansible-test:
  stage: test
  image: cytopia/ansible:2.14
  script:
    - ansible-playbook --syntax-check playbooks/deploy.yml
    - molecule test

ansible-deploy:
  stage: deploy
  image: cytopia/ansible:2.14
  before_script:
    - pip install ansible
    - ansible --version
  script:
    - ansible-playbook -i inventory/production playbooks/deploy.yml
      --vault-password-file <(echo $VAULT_PASSWORD)
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  variables:
    VAULT_PASSWORD: $ANSIBLE_VAULT_PASSWORD
```

#### Мониторинг инфраструктуры (Salt/Puppet)

```yaml
stages:
  - validate
  - apply

salt-validate:
  stage: validate
  image: saltstack/salt:latest
  script:
    - salt-call --local state.show_highstate --retcode-passthrough

salt-apply:
  stage: apply
  image: saltstack/salt:latest
  script:
    - salt-call --local state.highstate
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

#### Бэкап и восстановление

```yaml
stages:
  - backup
  - verify
  - upload

backup-database:
  stage: backup
  image: postgres:16
  script:
    - PGPASSWORD=$DB_PASSWORD pg_dump -h $DB_HOST -U $DB_USER $DB_NAME > backup_$(date +%Y%m%d_%H%M%S).sql
  artifacts:
    paths:
      - *.sql
    expire_in: 7 days

verify-backup:
  stage: verify
  image: postgres:16
  script:
    - PGPASSWORD=$DB_PASSWORD pg_restore -l latest.sql > /dev/null
  dependencies:
    - backup-database

upload-to-s3:
  stage: upload
  image: amazon/aws-cli
  script:
    - aws s3 cp *.sql s3://backups-bucket/database/$(date +%Y)/
  dependencies:
    - backup-database
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

## Мониторинг и наблюдаемость пайплайнов

Эффективная эксплуатация CI/CD невозможна без метрик. Ключевые аспекты:

*   **Pipeline Success Rate** — доля успешных запусков (целевое значение ≥ 95%).
*   **Pipeline Duration (p95)** — 95-й перцентиль времени выполнения (целевое значение < 15 мин).
*   **Queue Wait Time** — время ожидания свободного раннера (целевое значение < 2 мин).
*   **Flaky Test Rate** — доля нестабильных тестов (целевое значение < 1%).

Ключевые метрики для мониторинга Runner: `gitlab_runner_jobs_total`, время нахождения в `pending` (Queue Time), процент занятых слотов (Runner Saturation). Визуализация — в Grafana; алерты по превышению Queue Time и Failure Rate.

Настройка OpenTelemetry интеграции: включить `OpenTelemetry` в `Admin Area -> Settings -> Observability`, указать `OTEL_EXPORTER_OTLP_ENDPOINT`. Пайплайн автоматически генерирует трейсы, где Pipeline = Trace, Stage/Job = Spans.

Подробнее — в **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)** и **[Управление парком раннеров](../../runner-fleet-management.md)**.

## Безопасность CI/CD

*   **CI/CD Job Token Scope**: Начиная с версии **18.0**, доступ к проектам через `CI_JOB_TOKEN` ограничен белым списком (Allowlist) по умолчанию. Необходимо явно разрешать входящие и исходящие запросы между проектами в настройках проекта (Settings -> CI/CD -> Token Access).
*   **Scan Execution Policies**: Принудительное выполнение проверок безопасности, которое невозможно переопределить в `.gitlab-ci.yml` проекта. Позволяет навязать SAST, Dependency Scanning и Secret Detection на уровне группы/организации.
*   **Protected Branches и Environments**: Ограничение запуска пайплайнов и деплоев только для определенных веток и пользователей.
*   **Masked/Protected Variables**: Сокрытие секретов в логах и ограничение их использования только в защищенных контекстах.
*   **OIDC-аутентификация**: Использование беспарольной аутентификации для получения динамических секретов (HashiCorp Vault, облачные провайдеры) без статических паролей.

Подробнее — в **[Управление парком раннеров](../../runner-fleet-management.md)** и **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)**.

## Отладка и устранение неполадок

*   **CI Lint**: Инструмент проверки синтаксиса в UI GitLab (`CI/CD -> Editor`). Обязателен для использования перед коммитом сложных конфигураций. Доступен также через API: `POST /api/v4/ci/lint`.
*   **CI_DEBUG_TRACE**: Установка переменной `CI_DEBUG_TRACE=true` включает подробное логирование всех команд, включая переменные окружения и вывод shell.
*   **`gitlab-runner exec`**: Локальный запуск заданий для отладки без коммита в репозиторий. Позволяет проверить логику пайплайна перед пушем.
*   **Retry и manual**: Возможность ручного перезапуска упавших заданий или entire pipeline с сохранением истории.
*   **Типичные ошибки**:
    *   `No runner available` — нет раннеров с соответствующими тегами или все слоты заняты.
    *   `Job exceeded maximum timeout` — превышено максимальное время выполнения (настройка в Runner config).
    *   `Secret variable not available` — переменная не определена или недоступна в данном контексте (protected/unprotected).

Подробнее — в **[Отладка и устранение неполадок](../Advanced/debugging_and_troubleshooting.md)**.

## Дополнительная информация

*   **Стратегия ветвления**: О применении GitLab Flow — в [gitlab_flow.md](../Tutorials/gitlab_flow.md).
*   **Pipeline Execution Policies**: Принудительное выполнение проверок безопасности на уровне всей организации. С версии **19.2** поддерживаются **Scheduled Execution Policies** для регулярного сканирования всех проектов группы.

> **Требования к инфраструктуре (v17.x–19.x):**
>
> *   **PostgreSQL**: Минимальная версия **17**.
> *   **Redis**: Поддержка **Redis 7+** или **Valkey**.
> *   **Безопасность**: Enforced **Job Token Allowlist** (18.0+) — межпроектные взаимодействия через токены должны быть явно разрешены в настройках.
> *   **Осторожная миграция**: Рекомендуется тестирование на staging-окружении перед обновлением Production-инстанса.
