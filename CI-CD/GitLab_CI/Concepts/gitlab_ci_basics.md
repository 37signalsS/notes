# Основы GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

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
2.  **SAST/Quality**: Статический анализ безопасности и качества кода ([SonarQube integration](../Tutorials/sonarqube_integration.md)).
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
| **Хранение** | Централизованно на сервере GitLab | Локально на Runner или в распределенном кэше |

Подробное сравнение и стратегии оптимизации — в **[Кэширование и артефакты в GitLab CI](../Advanced/gitlab_ci_caching/caching_overview.md)**.

### Конфигурация через `.gitlab-ci.yml`

Файл определяет структуру и поведение CI/CD процессов в проекте.

> **Важно (GitLab 18.x/19.x):** Глобальные ключевые слова `before_script`, `image`, `cache` на верхнем уровне считаются устаревшими. Рекомендуется использовать блок `default`.
>
> **Pipeline Inputs (`spec:inputs`)**: С версии **17.11** корневой `.gitlab-ci.yml` может содержать секцию `spec:inputs` с типизированными параметрами (`string`, `number`, `boolean`). Это заменяет текстовые переменные на структурированный интерфейс в UI «Run Pipeline» с валидацией на этапе компиляции.

### Ключевые слова для управления пайплайном

#### Структурные настройки

*   **`stages`**: Список и порядок стадий.
*   **`default`**: Набор общих настроек для всех заданий (образ, скрипты подготовки, кэш).
*   **`variables`**: [Переменные окружения](./gitlab_ci_variables_secrets.md). Рекомендуется использовать **GitLab Secrets Manager** для чувствительных данных.
    *   **`raw: true`** (18.6+): Отключает автоматическое расширение вложенных переменных. Критично для значений, содержащих символ `$`.
    *   **`description`** и **`options`** (19.x): Описание и список предустановленных значений для UI «Run Pipeline».
*   **`workflow:rules`**: Глобальные правила запуска всего пайплайна. Позволяют избежать дублирования пайплайнов (например, при одновременном открытии MR и пуше в ветку).

#### Параметры заданий

*   **`script`**: Обязательный блок с shell-командами.
*   **`needs`**: Создает направленный ациклический граф (DAG), позволяя запускать задания сразу после готовности зависимостей, не дожидаясь завершения всей стадии.
*   **`rules`**: Современный и гибкий стандарт управления условиями (замена устаревшим `only`/`except`).
    *   **Почему `rules`?**: Поддерживают сложные логические выражения (`if`, `changes`, `exists`), позволяют изменять атрибуты задания (например, `when: manual` или `variables`) в зависимости от условий.
*   **`environment`**: Описание целевой среды.

#### Безопасность и доступ

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
    - terraform apply -input=false -auto-approve tfplan
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
  image: saltstack/salt:3007
  script:
    - salt-call --local state.show_highstate --retcode-passthrough

salt-apply:
  stage: apply
  image: saltstack/salt:3007
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

*   **CI/CD Job Token Scope**: Начиная с версии **17.0**, доступ к проектам через `CI_JOB_TOKEN` ограничен белым списком (Allowlist) по умолчанию. С версии **18.3** доступна тонкая настройка прав через Fine-grained Permissions (`read_registry`, `write_pages` и т.д.). С версии **18.4** токен позволяет выполнять `git push` в текущий репозиторий. Все межпроектные взаимодействия должны быть явно разрешены в `Settings -> CI/CD -> Token Access`.
*   **Scan Execution Policies**: Принудительное выполнение проверок безопасности, которое невозможно переопределить в `.gitlab-ci.yml` проекта. Позволяет навязать SAST, Dependency Scanning и Secret Detection на уровне группы/организации. С версии **19.2** поддерживаются **Scheduled Execution Policies** для регулярного сканирования всех проектов группы.
*   **Protected Branches и Environments**: Ограничение запуска пайплайнов и деплоев только для определенных веток и пользователей.
*   **Masked/Protected Variables**: С версии **18.3** маскирование применяется автоматически ко всем новым переменным. Требование: минимум 8 символов, отсутствие пробелов.
*   **OIDC-аутентификация**: Использование беспарольной аутентификации для получения динамических секретов (HashiCorp Vault, внешние сервисы) без статических паролей. Стандарт с версии **17.0** (`id_tokens`), заменивший устаревший `CI_JOB_JWT` (удален в 18.0).

Подробнее — в **[Управление парком раннеров](../../runner-fleet-management.md)** и **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)**.

## Лучшие практики

### Проектирование пайплайнов

1.  **Используйте DAG вместо последовательных стадий**: Директива `needs` позволяет устранить бутылочное горлышко стадий, запуская задачи параллельно после готовности зависимостей. Это сокращает общее время выполнения на 30–60% в типовых проектах.
2.  **Один пайплайн — одна ответственность**: Разделяйте сборку, тестирование и деплой на отдельные стадии. Не смешивайте инфраструктурные изменения (Terraform) с деплоем приложения в одной задаче.
3.  **Ограничивайте область действия переменных**: Используйте `environment_scope` для изоляции секретов между `dev`, `staging` и `production`. Секреты `production` не должны быть доступны в `development`.
4.  **Используйте `resource_group` для критичных ресурсов**: При параллельном доступе к общим ресурсам (база данных, окружение) применяйте `resource_group` для взаимного исключения задач.
5.  **Настройте `timeout` на уровне проекта**: Задайте глобальный лимит времени выполнения пайплайна (например, 30 минут) для предотвращения зависших задач, которые занимают слоты Runner'ов.

### Безопасность

1.  **Всегда используйте `when: manual` для production-деплоев**: Исключает автоматическое развертывание из веток `feature` и `develop`. Разрешайте деплой только для защищенных веток (`main`, `production`).
2.  **Предпочитайте OIDC статическим секретам**: Используйте `id_tokens` для аутентификации в Vault, Kubernetes и внешних сервисах. Это полностью устраняет риск компрометации долгоживущих паролей.
3.  **Маскируйте и защищайте секреты**: Для критичных переменных включайте оба флага (`Masked` и `Protected`). С версии **18.3** маскирование применяется автоматически, но проверяйте правила регулярно.
4.  **Ограничивайте `CI_JOB_TOKEN`**: Используйте Fine-grained Permissions (18.3+) для предоставления минимально необходимых прав. Никогда не разрешайте доступ ко всем проектам без необходимости.
5.  **Не коммитьте секреты**: Используйте GitLab Secrets Manager (19.2+) или CI/CD Variables. Включите pre-commit хуки для сканирования секретов.

### Производительность

1.  **Кэшируйте зависимости**: Настройте кэш для менеджеров пакетов (`pip`, `npm`, `go mod`). Используйте распределенный кэш (S3/MinIO) для кластеров Runner'ов.
2.  **Используйте `needs` для параллелизма**: Задачи, не зависящие друг от друга, должны запускаться одновременно. Избегайте цепочек из 5+ стадий без DAG.
3.  **Ограничивайте размер артефактов**: Артефакты >100MB замедляют передачу между стадиями. Используйте `exclude` для исключения временных файлов и кэша.
4.  **Используйте `parallel:matrix` для кросс-платформенного тестирования**: Вместо отдельных задач для каждой платформы используйте матричную адресацию.
5.  **Мониторьте Queue Time**: Если время ожидания Runner превышает 2 минуты — добавьте мощности или оптимизируйте конфигурацию `concurrent`/`limit`.

### Эксплуатация

1.  **Разделяйте Runner'ы по назначению**: Используйте теги (`build`, `test`, `deploy`, `gpu`, `macos`) для маршрутизации задач. Не запускайте production-деплой на общих Runner'ах.
2.  **Настраивайте `protected` Runner'ы**: Для задач, работающих с продуктивными секретами, используйте Runner'ы, доступные только из защищенных веток.
3.  **Используйте Fleeting для автоскейлинга**: Вместо `docker-machine` переходите на Fleeting + Taskscaler (GitLab 17.0+) для динамического масштабирования через API оркестраторов.
4.  **Ведите журнал изменений конфигурации**: Все изменения в `.gitlab-ci.yml` должны проходить код-ревью. Используйте Merge Request для отслеживания эволюции пайплайнов.
5.  **Тестируйте изменения в staging**: Используйте отдельный инстанс GitLab или группу для тестирования новых версий Runner'ов и конфигураций перед обновлением production.

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

## Особенности и ограничения (Edge Cases)

### Масштаб репозитория

*   **Большие репозитории (>1GB)**: Могут вызывать таймауты при `git clone`. Используйте `GIT_DEPTH: "1"` для shallow clone или настройте `GIT_STRATEGY: fetch`.
*   **Монорепозитории**: При множественных `include` из разных проектов учитывайте лимит 50 файлов на пайплайн. Используйте `rules:changes` для запуска только затронутых сервисов.

### Параллелизм и ресурсы

*   **Конфликты ресурсов**: При параллельном выполнении задач убедитесь, что они не конфликтуют по портам, файлам или Docker-образам. Используйте `resource_group` для взаимного исключения.
*   **Ограничение параллелизма**: Глобальный параметр `concurrent` в `config.toml` ограничивает максимальное количество одновременных задач на Runner. При превышении задачи переходят в статус `pending`.
*   **Lift and Shift**: При миграции с Jenkins или других систем на GitLab CI учитывайте, что параллелизм ограничен не только количеством Runner'ов, но и лицензией GitLab (бесплатная версия имеет ограничения на количество параллельных задач).

### Секреты и переменные

*   **Автоматическое маскирование**: GitLab автоматически маскирует переменные, помеченные как `masked`, в логах. Однако если секрет попадает в вывод команды (например, `echo $SECRET`), он будет замаскирован только если формат переменной уникален.
*   **Переменные с `masked: true`**: Должны содержать минимум 8 символов и не могут содержать `\n`. Для многострочных данных используйте тип `File`.
*   **Приоритет переменных**: Если переменная определена на нескольких уровнях (instance, group, project, job), побеждает значение с наивысшим приоритетом. Полная иерархия — в [gitlab_ci_variables_secrets.md](./gitlab_ci_variables_secrets.md).

### Квоты и лимиты

*   **Артефакты**: максимальный размер 100MB по умолчанию (настраивается в Settings > CI/CD). Для больших артефактов используйте внешний Object Storage (S3/MinIO).
*   **Кэш**: максимальный размер 10GB на проект. При превышении старые записи удаляются по LRU.
*   **Логи**: отображаются в реальном времени, но обрезаются при превышении ~4-10MB. Используйте артефакты для сохранения полных логов.
*   **API rate limit**: 60 запросов в минуту для аутентифицированных пользователей. При превышении используйте пагинацию или уменьшите частоту опросов.

### Версионная совместимость

*   **`rules` заменили `only/except`** начиная с GitLab 13.9. Старые конфигурации продолжают работать, но `rules` рекомендуются для новых пайплайнов.
*   **`needs` для DAG** доступны с GitLab 12.2, но полная поддержка `parallel:matrix` с `needs` появилась в 13.3.
*   **`resource_group`** доступен с GitLab 13.12.
*   **`spec:inputs`** доступен с GitLab 17.11.

### Специфичные ограничения

*   **Windows Runner**: Нет поддержки `services` (Docker Compose-style sidecar) и `docker-autoscaler`. Ограниченная совместимость с CI/CD-образами (Ubuntu-based).
*   **Shell Executor**: Отсутствует изоляция между задачами. Задачи могут конфликтовать по файлам, переменным среды и портам. Используйте только для простых системных задач.
*   **`gitlab-runner exec`**: Не поддерживает `services`, `include`, Protected/Masked переменные и кэш/артефакты. Используйте только для локальной отладки синтаксиса.

## Дополнительная информация

*   **[Сканирование безопасности в GitLab CI/CD](./gitlab_ci_security_scanning.md)** — SAST, DAST, Secret Detection, Dependency Scanning, Container Scanning.
*   **[Миграция пайплайнов в GitLab CI/CD](./gitlab_ci_migration.md)** — стратегии миграции из Jenkins, GitHub Actions, CircleCI.
*   **[Feature Flags в GitLab CI/CD](./gitlab_ci_feature_flags.md)** — интеграция с Unleash, LaunchDarkly, Flagsmith, progressive delivery.
*   **[Наблюдаемость пайплайнов GitLab CI/CD](./gitlab_ci_observability.md)** — метрики, Grafana дашборды, DORA, OpenTelemetry.
*   **[Service Mesh и GitLab CI/CD](./gitlab_ci_service_mesh.md)** — Istio/Linkerd интеграция, traffic shifting, canary через mesh.
*   **[Раннеры GitLab CI: Windows и macOS](./gitlab_ci_runners_platforms.md)** — настройка и практика использования Windows и macOS Runner'ов.
*   **[Сканирование безопасности CI/CD](../Advanced/cicd_security_hardening.md)** — пятислойная архитектура безопасности.
*   **[Container Registry в GitLab CI/CD](../Advanced/container_registry.md)** — управление образами, cleanup, immutable tags.
*   **[Compliance и Audit в GitLab CI/CD](../Advanced/compliance_and_audit.md)** — Pipeline Execution Policies, Audit Trail.
*   **[Мониторинг и метрики GitLab CI/CD](../Advanced/monitoring_and_metrics.md)** — Prometheus metrics, Runner monitoring.
*   **[Incident Response в GitLab CI/CD](../Advanced/incident_response_cicd.md)** — playbooks, severity levels, postmortems.
*   **[Управление парком раннеров](../Advanced/runner_fleet_management.md)** — масштабирование, autoscaling, мониторинг.
*   **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — типы executor'ов, конфигурация.
*   **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)** — бэкап, восстановление, DR.
*   **[CI/CD Security Hardening](../../Core_Concepts/ci_cd_security_hardening.md)** — общие принципы безопасности CI/CD.
*   **[Pipeline Observability](../../Core_Concepts/pipeline_observability.md)** — SLI/SLO, трейсы, Golden Signals.
*   **[Метрики DORA](../../Core_Concepts/dora_metrics.md)** — Deployment Frequency, Lead Time, CFR, MTTR.
*   **[CI/CD Backup и DR](../../Core_Concepts/ci_cd_backup_dr.md)** — стратегии резервного копирования и восстановления.
*   **[CI/CD Anti-patterns](../../ci_cd_antipatterns.md)** — типичные ошибки и их предотвращение.
*   **[CI/CD Patterns](../../ci_cd_patterns.md)** — паттерны проектирования пайплайнов.
*   **[Feature Toggles](../../CI-CD/Testing/feature_toggles/)** — типология флагов и стратегии управления.
*   **[Стратегия ветвления](../Tutorials/gitlab_flow.md)** — о применении GitLab Flow.
*   **[Обновление и обслуживание GitLab](../Advanced/gitlab_upgrades_and_maintenance.md)** — zero-downtime обновления, blue-green, maintenance.
*   **[Внешняя аутентификация GitLab](../Advanced/gitlab_external_auth.md)** — LDAP, SAML, OIDC.
*   **[Capacity Planning для GitLab CI/CD](../Advanced/gitlab_capacity_planning.md)** — планирование мощности CI/CD инфраструктуры.
*   **[Выбор редакции GitLab для production](../Advanced/gitlab_edition_selection.md)** — CE vs EE.
*   **[Монорепозитории в GitLab CI/CD](../Advanced/gitlab_monorepo_ci.md)** — стратегии CI/CD для монорепозиториев.
*   **[GitLab Dogfooding](../Advanced/gitlab_dogfooding.md)** — использование GitLab для разработки GitLab.

> **Требования к инфраструктуре (v17.x–19.x):**
>
> *   **PostgreSQL**: Минимальная версия **17**.
> *   **Redis**: Поддержка **Redis 7+** или **Valkey**.
> *   **Безопасность**: Enforced **Job Token Allowlist** (18.0+) — межпроектные взаимодействия через токены должны быть явно разрешены в настройках.
> *   **Осторожная миграция**: Рекомендуется тестирование на staging-окружении перед обновлением Production-инстанса.
