# Конструктор рабочих процессов GitLab CI/CD

**Актуально для:** GitLab CI/CD 17.x–19.4

## Определения

**Рабочий процесс (Workflow/Pipeline)** — это логическая и техническая последовательность стадий и задач, описывающая жизненный цикл сборки, тестирования и развертывания ПО. В современных версиях GitLab CI/CD пайплайны строятся из модульных блоков:

### Основные директивы

-   **`stages` и `jobs`**: Скелет пайплайна. Определяют *что* делать и в какой *очередности*. Подробные определения — в **[Основах GitLab CI/CD](../Concepts/gitlab_ci_basics.md)**.
-   **`artifacts`**: Файлы и отчеты, передаваемые между стадиями. См. **[Артефакты в GitLab CI](./gitlab_ci_caching/gitlab_ci_artifacts.md)**.
-   **`cache`**: Инструмент для сохранения зависимостей (`node_modules`, `.m2`) между запусками. См. **[Обзор кэширования](./gitlab_ci_caching/caching_overview.md)**.
-   **`needs` (DAG)**: Директива для создания **Направленного Ациклического Графа (Directed Acyclic Graph)**, позволяющая запускать задачи сразу после готовности их зависимостей, игнорируя границы стадий. Подробнее — **[DAG с needs](./workflow_rules/dag_with_needs.md)**.
-   **`rules`**: Условия включения задач в пайплайн на основе переменных, изменений файлов или событий. Подробнее — **[Правила запуска задач](./workflow_rules/job_rules.md)**.
-   **`include` и `extends`**: Механизмы переиспользования кода. `include` подключает внешние YAML-файлы, `extends` — позволяет наследовать конфигурацию задач. См. **[Обзор переиспользуемых пайплайнов](../Reusable_Pipelines/overview.md)**.
-   **`trigger`**: Запуск зависимых (downstream) пайплайнов в других проектах или дочерних пайплайнов в текущем. См. **[Родительско-дочерние пайплайны](./Downstream_Pipelines/parent_child_pipelines.md)**.
-   **`spec:inputs` (GitLab 17.11+)**: Строгая типизация параметров для шаблонов и компонентов, позволяющая валидировать конфигурацию до старта пайплайна.
-   **Dotenv-артефакты**: Механизм динамической передачи переменных окружения, созданных во время выполнения одной задачи, в последующие.

### Управление жизненным циклом пайплайна

-   **`workflow:rules`**: Глобальные правила, определяющие, при каких условиях создаётся весь пайплайн (а не отдельная задача). Позволяет исключить дублирование пайплайнов при одновременном пуше и открытии Merge Request. Подробнее — **[Правила запуска задач](./workflow_rules/job_rules.md)**.
-   **`workflow:auto_cancel`**: Механизм автоматической отмены устаревших пайплайнов при появлении нового коммита в ту же ветку. Режим `on_new_commit: interruptible` отменяет только задачи с `interruptible: true`. Режим `on_job_failure: all` реализует Fail-Fast — немедленную останову всего пайплайна при критической ошибке.
-   **`interruptible`**: Флаг задачи, указывающий, что она может быть безопасно отменена механизмом `auto_cancel`. По умолчанию все задачи считаются неинтерраптибельными. Критические операции (деплой, миграция БД) всегда требуют `interruptible: false`.

### Среда выполнения задачи

-   **`image`**: Docker-образ, в котором выполняется задача. Определяет среду выполнения (операционную систему, установленные утилиты, версию языка программирования).
-   **`services`**: Вспомогательные Docker-контейнеры (sidecar), запускаемые параллельно с задачей. Используются для баз данных (PostgreSQL, MySQL), очередей сообщений (RabbitMQ, Redis), и других зависимых сервисов, необходимых для интеграционных тестов.
-   **`tags`**: Механизм маршрутизации задач к конкретным Runner'ам. Позволяет направлять задачи на специализированные раннеры (с GPU, с доступом к VPN, в конкретном дата-центре).
-   **`before_script` / `after_script`**: Хуки, выполняемые до и после основного `script`. `before_script` выполняется в том же контексте, что и `script` (доступ к переменным, код завершения предыдущего шага). `after_script` выполняется в отдельном контексте и полезен для очистки ресурсов, отправки уведомлений или фиксации результатов — даже при падении задачи.

### Управление надёжностью и таймаутами

-   **`allow_failure`**: Управление критичностью ошибки. Если `true`, задача может упасть, не останавливая пайплайн. Поддерживает `exit_codes` для игнорирования специфических кодов завершения (например, OOM — код 137).
-   **`retry`**: Политика автоматического перезапуска задачи при транзиторных сбоях (сетевые ошибки, переполнение памяти, таймауты Runner'а). Позволяет настроить повтор для конкретных условий: `runner_system_failure`, `stuck_or_timeout_failure`, `script_failure`, `api_failure` и др.
-   **`timeout`**: Ограничение максимального времени выполнения задачи. Защищает от зависших процессов, занимающих ресурсы Runner'а. По умолчанию — 1 час. Рекомендуется задавать явно для каждой задачи.

## Предварительные требования

### Версии и поддерживаемые функции

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| GitLab CE/EE | 17.0+ | Для базовых возможностей DAG и `spec:inputs` требуется 17.11+ |
| GitLab Runner | 17.0+ | Рекомендуется версия, совпадающая с основной версией GitLab |
| Docker | 20.10+ | Для исполнителя Docker и сервисных контейнеров |
| `spec:inputs` с `regex` | 17.10+ | Валидация входных параметров регулярными выражениями |
| `spec:inputs` с `options` | 18.0+ | Выпадающие списки в UI «Run Pipeline» |
| `parallel:matrix` + `needs` | 16.3+ | Матричная адресация зависимостей 1:1 |
| Выражения `$[[ matrix.VAR ]]` в `needs` | 18.6+ | Связывание матричных задач через выражения |
| `resource_group_process_mode` | 14.4+ (YAML) | Полный набор режимов очереди в YAML-конфигурации |
| `newest_ready_first` | 18.6+ | Приоритизация готовых задач в resource_group |

### Инфраструктурные требования

- **GitLab Instance**: Self-managed (CE/EE) или GitLab Dedicated. Для пайплайнов с `resource_group` и `auto_cancel` требуется активная связь между Runner'ами и GitLab Server через HTTPS.
- **Runner'ы**: Как минимум один Runner с исполнителем `docker` или `docker+machine`. Для production-сред рекомендуется выделенный Runner с привязкой к группе, а не к отдельному проекту.
- **Сеть**: Runner должен иметь доступ к внутренним сервисам (реестрам образов, базам данных, artifact-хранилищу). При использовании `services` требуется разрешение межконтейнерного DNS (`alias`).
- **Хранилище артефактов**: Для production-рекомендуется настроить внешнее хранилище (S3-совместимое, Azure Blob, или локальный NFS) для артефактов, чтобы избежать исчерпания диска на GitLab Server.
- **Права доступа**: Учетная запись, запускающая Runner, должна иметь права на монтирование Docker-сокета (если используется `docker` executor) или на создание виртуальных машин (если используется `docker+machine`).

### Необходимые знания

- Синтаксис YAML 1.2 и структура `.gitlab-ci.yml`
- Базовые концепции CI/CD: стадии (`stages`), задачи (`jobs`), артефакты, кэш
- Принципы контейнеризации (Docker-образы, слои, entrypoint, working directory)
- Основы сетевого взаимодействия в Docker (bridge-сеть, DNS-алиасы, публикация портов)
- Работа с предопределёнными переменными GitLab (`CI_COMMIT_SHA`, `CI_PIPELINE_ID`, `CI_REGISTRY`)

## Философия конструктора

### Базовые блоки конструктора
1.  **Jobs (Задачи)**: Независимые единицы работы в изолированных контейнерах.
2.  **Stages (Стадии)**: Группы параллельных задач.
3.  **Artifacts (Артефакты)**: Результаты сборки, передаваемые дальше.
4.  **Cache (Кэш)**: Временные данные для ускорения повторных запусков.
5.  **Components (Компоненты)**: Современные, версионируемые блоки логики из **[CI/CD Catalog](../Reusable_Pipelines/ci_cd_catalog_components.md)**.
6.  **Workflow Rules**: Глобальные правила жизненного цикла пайплайна (`workflow:rules`), определяющие, когда пайплайн вообще должен быть создан.

### Принципы проектирования
-   **Атомарность**: Одна задача — одна ответственность (отдельно билд, отдельно тест, отдельно деплой). Избегайте огромных скриптов в одной задаче.
-   **Изоляция**: Каждая задача выполняется в "свежем" контейнере. Обмен данными — только через артефакты или кэш.
-   **Fail Fast**: Проверки (линтеры, тесты) должны быть в самом начале, чтобы не тратить ресурсы на заведомо ошибочные пайплайны.
-   **DRY (Don't Repeat Yourself)**: Используйте шаблоны, `extends`, `!reference` и компоненты для исключения дублирования YAML-кода.
-   **Версионируемость**: При использовании внешних шаблонов всегда фиксируйте версию (commit SHA или tag), чтобы изменения в шаблонах не "сломали" рабочий пайплайн.
-   **Безопасность по умолчанию**: Используйте OIDC для аутентификации вместо долгоживущих токенов. Настройте `Protected` и `Masked` для секретов. Используйте `resource_group` для предотвращения гонок при деплое.
-   **Прогнозируемость**: Задавайте `timeout` и `retry` явно для каждой задачи. Не полагайтесь на значения по умолчанию — они могут измениться при обновлении GitLab.
-   **Экономия ресурсов**: Настройте `auto_cancel` и `interruptible` для MR-пайплайнов, чтобы не тратить время раннеров на устаревшие коммиты.

## Композиция и переиспользование конфигурации

### Механизмы переиспользования

GitLab CI/CD предоставляет несколько уровней композиции YAML-конфигурации, от простых якорей до типизированных компонентов:

| Механизм | Описание | Версия GitLab | Подробнее |
| :--- | :--- | :--- | :--- |
| **YAML Anchors (`&`/`*`)** | Стандартный механизм YAML для повторного использования блоков. Ограничен — не поддерживает слияние массивов. | Все | **[Якоря и `!reference`](../Reusable_Pipelines/reference_and_yaml_anchors.md)** |
| **`!reference`** | GitLab-специфичный тег для извлечения значений из других блоков и файлов. Поддерживает слияние массивов. | 12.7+ | **[Якоря и `!reference`](../Reusable_Pipelines/reference_and_yaml_anchors.md)** |
| **`extends`** | Наследование конфигурации от другого	job или шаблона. Поддерживает глубокое слияние (переменные) и перезапись (script, rules). | Все | **[`extends`](../Reusable_Pipelines/extends_keyword.md)** |
| **`include`** | Подключение внешних YAML-файлов четырьмя способами: `local` (файл репозитория), `remote` (URL), `template` (встроенные шаблоны GitLab), `component` (CI/CD Catalog). | Все (component: 16.2+) | **[`include`](../Reusable_Pipelines/include_keyword.md)** |
| **CI/CD Components** | Версионируемые, типизированные модули с `spec:inputs`. Современная альтернатива шаблонам. Публикуются в CI/CD Catalog. | 16.2+ | **[Компоненты Catalog](../Reusable_Pipelines/ci_cd_catalog_components.md)** |

### Приоритет при слиянии

При использовании `extends`, `include` и `!reference` вместе возникает вопрос приоритетов:

1.  **Переменные** — глубокое слияние (объединяются массивы и объекты).
2.  **`script`, `rules`, `tags`, `artifacts`, `cache`** — перезапись (последнее определение побеждает).
3.  **`allow_failure`, `when`, `timeout`, `retry`** — перезапись скалярных значений.
4.  **`before_script`, `after_script`** — перезапись (не слияние). Если нужно объединить — используйте `!reference`.

Подробнее о правилах слияния — **[Директивы GitLab CI/CD](./workflow_rules/directives_definitions.md)**.

### Использование `before_script` и `after_script`

`before_script` выполняется перед `script` задачи в том же контейнере и с теми же переменными. Используйте для:
- Установки зависимостей, которых нет в Docker-образе
- Аутентификации в реестрах (Docker Registry, package managers)
- Проверки доступности внешних сервисов

`after_script` выполняется после `script` (успешного или нет) в отдельном контейнере. Используйте для:
- Отправки уведомлений (Slack, email)
- Сбора логов и метрик
- Очистки временных ресурсов

```yaml
deploy:
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - kubectl config use-context $ENVIRONMENT
  script:
    - ./deploy.sh
  after_script:
    - ./notify_slack.sh $CI_PIPELINE_URL $CI_JOB_STATUS
```

**Важно:** `before_script` и `after_script` на верхнем уровне YAML считаются устаревшими (GitLab 18.x/19.x). Рекомендуется использовать блок `default`:

```yaml
default:
  before_script:
    - apt-get update && apt-get install -y curl

test:
  script: pytest
```

### Блок `default`

Блок `default` позволяет задать значения по умолчанию для всех задач в пайплайне. Поддерживает `image`, `services`, `before_script`, `after_script`, `cache`, `interruptible`, `retry`, `timeout`, `tags`.

```yaml
default:
  image: python:3.12-slim
  before_script:
    - pip install -r requirements.txt
  retry:
    max: 2
    when: [runner_system_failure, stuck_or_timeout_failure]
  interruptible: true

test:
  script: pytest

lint:
  script: ruff check .
```

## Передача данных и отчетность

### Артефакты vs Кэш: когда что использовать

Выбор между артефактами и кэшем зависит от цели передачи данных. Артефакты гарантированно доставляют результаты сборки между стадиями, тогда как кэш ускоряет последующие запуски за счет переиспользования зависимостей.

Подробное техническое сравнение, уровни хранения и стратегии оптимизации — в **[Обзоре кэширования и артефактов](./gitlab_ci_caching/caching_overview.md)**.

**Рекомендация:** Всегда используйте `expire_in` для артефактов (например, `1h` или `1 week`), чтобы автоматически очищать старые сборки. Для задач, которым не нужны артефакты предыдущих шагов, явно указывайте `dependencies: []` или `needs: []` для экономии времени и места.

### Управление загрузкой артефактов через `needs`

По умолчанию задача с `needs` загружает артефакты от всех указанных зависимостей. Если задача зависит от другой задачи **только по статусу** (не по данным), используйте `artifacts: false` для экономии времени на скачивание:

```yaml
integration_test:
  stage: test
  needs:
    - job: build:backend
      artifacts: false  # Только статус: "билд прошёл"
    - job: build:frontend
      artifacts: true   # Нужны файлы сборки
  script:
    - ./run_integration.sh
```

Подробнее — **[DAG с needs](./workflow_rules/dag_with_needs.md)**.

### Переменные окружения (Variables)

Переменные обеспечивают динамику и гибкость конструктора:
-   **Predefined Variables**: Автоматические переменные GitLab (`CI_COMMIT_SHA`, `CI_PIPELINE_ID`).
-   **Custom Variables**: Задаются в интерфейсе (Settings -> CI/CD -> Variables).
-   **Protected**: Доступны только в защищенных ветках/тегах.
-   **Masked**: Скрываются в логах (для паролей и токенов).

Подробнее — **[Переменные и лучшие практики](./workflow_rules/variables_best_practices.md)**.

**Интеграция с Vault**: Для хранения критичных секретов рекомендуется использовать внешние хранилища типа **HashiCorp Vault**. Это позволяет избежать компрометации переменных в интерфейсе GitLab и централизованно управлять доступом через JWT-токены (OIDC).

## Оптимизация и производительность

### Кэширование зависимостей
Правильное кэширование может сократить время сборки в разы. Кэш привязывается к проекту и ключу. Рекомендуется использовать `files` в `cache:key` для инвалидации кэша только при изменении файлов зависимостей (например, `package-lock.json` или `go.sum`).

Подробнее — **[Ключи кэша](./gitlab_ci_caching/cache_keys.md)** и **[Сценарии кэширования](./gitlab_ci_caching/cache_scenarios.md)**.

### Динамическая передача переменных через `dotenv`
Используется для передачи данных, которые становятся известны только во время выполнения задачи.

```yaml
setup:version:
  stage: .pre
  script:
    - echo "IMAGE_TAG=v1.2.$CI_PIPELINE_ID" > build.env
    - echo "DEPLOY_TARGET=internal-prod" >> build.env
  artifacts:
    reports:
      dotenv: build.env
```

**Ограничения:** Dotenv-переменные **недоступны** в `rules` (вычисляются после парсинга конфигурации) и **не работают** между инстансами матричных сборок (`parallel:matrix`). Для передачи данных между матричными задачами используйте API или файловые артефакты.

### Политики повторных запусков (`retry`)

Транзиторные сбои (сетевые таймауты, переполнение памяти, временная недоступность внешних сервисов) — частая причина падения пайплайнов. Механизм `retry` позволяет автоматически перезапускать задачу:

```yaml
deploy:production:
  retry:
    max: 2
    when:
      - runner_system_failure
      - stuck_or_timeout_failure
      - api_failure
      - scheduler_failure
  script:
    - ./deploy.sh
```

**Доступные условия `retry:when`:**
- `script_failure` — ошибка в скрипте (по умолчанию не включать без веской причины)
- `api_failure` — ошибка API GitLab
- `runner_system_failure` — сбой системы Runner'а
- `stuck_or_timeout_failure` — зависание или превышение таймаута
- `scheduler_failure` — ошибка планировщика
- `missing_dependency_failure` — отсутствующая зависимость
- `runner_unavailable` — Runner недоступен

**Рекомендация:** Не включайте `script_failure` в `retry` автоматически — это скрывает реальные ошибки в коде. Используйте `retry` только для инфраструктурных сбоев.

### Таймауты (`timeout`)

Защита от зависших задач, занимающих ресурсы Runner'а:

```yaml
integration_tests:
  timeout: 30 minutes
  script:
    - ./run_heavy_tests.sh

quick_lint:
  timeout: 5 minutes
  script:
    - ruff check .
```

**Уровни таймаутов:**
- **Задачи (job):** `timeout` в конфигурации задачи (по умолчанию 1 час).
- **Пайплайны (pipeline):** настройка в Settings -> CI/CD -> General pipelines -> Pipeline timeout (по умолчанию 60 минут).
- **Runner:** ` poll_timeout` в `config.toml` Runner'а — время ожидания назначения задачи.

### Автоматическая отмена устаревших пайплайнов (`auto_cancel`)

При частых пуше в ветку разработки предыдущие пайплайны становятся неактуальными. `auto_cancel` позволяет высвобождать ресурсы раннеров:

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

stages:
  - build
  - test
  - deploy

build:
  stage: build
  interruptible: true
  script: ./build.sh

test:
  stage: test
  interruptible: true
  script: pytest

deploy:
  stage: deploy
  interruptible: false  # Критическая операция — не отменять
  script: ./deploy.sh
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Режимы `auto_cancel`:**
- `on_new_commit: interruptible` — отменяет только задачи с `interruptible: true` (GitLab 16.0+).
- `on_job_failure: all` — немедленно останавливает весь пайплайн при падении задачи (GitLab 13.12+). Полезен для Dev-окружений.

## Продвинутые строительные блоки

### Матричные сборки (`parallel:matrix`)
Позволяют запускать одну задачу несколько раз с разными комбинациями переменных. С версии **GitLab 18.6** поддерживается матричная адресация в `needs`, что позволяет связывать тесты и сборки 1:1.

```yaml
test:matrix:
  parallel:
    matrix:
      - PROVIDER: [esxi, proxmox, physical]
        STACK: [dev, prod]
  script:
    - deploy_to $PROVIDER --env $STACK
```

Подробнее — **[Матричные сборки и сериализация](./workflow_rules/matrix_builds_and_serialization.md)**.

### Управление окружениями (`environment`)
Связывает задачу с конкретной средой развертывания.
- **`url`**: Ссылка на приложение.
- **`on_stop`**: Задача для очистки (удаление Review App).
- **`auto_stop_in`**: Время жизни временного окружения (например, `1 week`).
- **`action: prepare`**: Для задач, которые подготавливают окружение, но не деплоят (например, Terraform Plan).
- **`auto_stop_in` + `on_stop`**: Автоматическая остановка окружения через указанное время. Требует задачи с `action: stop` в `on_stop`.

Подробнее — **[Окружения и деплои](../Concepts/environments_and_deployments.md)**.

### Группы ресурсов (`resource_group`)
Используются для сериализации выполнения задач на один и тот же ресурс, предотвращая конфликты при одновременном запуске нескольких пайплайнов.

```yaml
db_migrate:
  stage: deploy
  resource_group: database_cluster_prod
  resource_group_process_mode: oldest_first  # Строгий FIFO порядок
  interruptible: false
  script:
    - ./run_migrations.sh
```

**Режимы `resource_group_process_mode`:**
- `oldest_first` (по умолчанию) — FIFO очередь, строгое соблюдение порядка.
- `newest_first` — LIFO, новые пайплайны получают приоритет.
- `unordered` — произвольный порядок, но все равно сериализует выполнение.

Подробнее — **[Матричные сборки и сериализация](./workflow_rules/matrix_builds_and_serialization.md)**.

### Опциональные зависимости (`needs:optional`)
Начиная с **GitLab 17.4**, флаг `optional: true` позволяет задаче зависеть от другой задачи, которая может быть исключена из пайплайна через `rules`. Если зависимая задача не включена в пайплайн — текущая задача всё равно запустится.

### Управление тегами Runner'ов (`tags`)
Теги позволяют направлять задачи на определённые Runner'ы. Это критично для самохостинга, где Runner'ы могут иметь разные характеристики (GPU, SSD, доступ к VPN, конкретная сеть):

```yaml
build:gpu:
  tags: [gpu-runner, docker]
  script: ./train_model.sh

deploy:vpn:
  tags: [vpn-runner, production]
  script: ./deploy_internal.sh
```

### CI/CD Components с `spec:inputs`
Современный механизм создания переиспользуемых, типизированных модулей. Компоненты публикуются в CI/CD Catalog с семантическим версионированием:

```yaml
# Подключение компонента из Catalog
include:
  - component: gitlab.com/security-group/secret-detection@1.0.0
    inputs:
      severity_threshold: high
```

Подробнее — **[Компоненты CI/CD Catalog](../Reusable_Pipelines/ci_cd_catalog_components.md)**.

## Практические сценарии

### Сценарий 1: Ускорение через DAG и опциональные связи

```yaml
stages: [build, test]

build:frontend:
  stage: build
  script: npm run build
  rules:
    - changes: ["frontend/**/*"]

build:backend:
  stage: build
  script: ./build_backend.sh

test:frontend:
  stage: test
  needs:
    - job: build:frontend
      optional: true # Запустится сразу, если билд фронтенда был включен
  script: npm test
```

### Сценарий 2: Матрица 1:1 (GitLab 18.6+)

Сборка и тест для разных платформ без ожидания завершения всех сборок.

```yaml
compile:
  parallel:
    matrix:
      - PLATFORM: [linux, darwin, windows]
  script: ./build.sh $PLATFORM

test:
  parallel:
    matrix:
      - PLATFORM: [linux, darwin, windows]
  needs:
    - job: compile
      parallel:
        matrix:
          - PLATFORM: $PLATFORM # Связь 1:1
  script: ./run_test.sh $PLATFORM
```

### Сценарий 3: Downstream пайплайны с валидацией Inputs (GitLab 18.9+)

```yaml
trigger_deploy:
  stage: deploy
  trigger:
    include:
      - project: 'my-group/templates'
        file: 'deploy-template.yml'
    inputs:
      environment: production
      version: $CI_COMMIT_SHORT_SHA
```

### Сценарий 4: Интеграция отчетов о тестах и покрытии

```yaml
test:job:
  stage: test
  script:
    - pytest --junitxml=junit.xml --cov=app --cov-report=xml
  artifacts:
    reports:
      junit: junit.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

### Сценарий 5: Условный запуск для монорепозиториев

```yaml
test:ui:
  stage: test
  rules:
    - changes:
        - "ui/**/*"
  script:
    - cd ui && npm test
```

### Сценарий 6: Полный пайплайн с `workflow:rules`, `auto_cancel` и `retry`

Комбинированный пример, демонстрирующий взаимодействие основных блоков конструктора:

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "web"

default:
  image: python:3.12-slim
  interruptible: true
  retry:
    max: 1
    when: [runner_system_failure, stuck_or_timeout_failure]
  timeout: 20 minutes

stages:
  - build
  - test
  - security
  - deploy

build:
  stage: build
  before_script:
    - pip install -r requirements.txt
  script:
    - python -m py_compile **/*.py
    - python build.py
  artifacts:
    paths: [dist/]
    expire_in: 1 hour

test:unit:
  stage: test
  needs: [build]
  script: pytest tests/unit/

test:integration:
  stage: test
  needs: [build]
  services:
    - postgres:16
  variables:
    POSTGRES_DB: test_db
    POSTGRES_USER: test
    POSTGRES_PASSWORD: test
  script: pytest tests/integration/

security:sast:
  stage: security
  needs: [build]
  script: bandit -r app/ -f json -o sast.json
  artifacts:
    reports:
      sast: sast.json

deploy:staging:
  stage: deploy
  needs: [test:unit, test:integration, security:sast]
  resource_group: staging_env
  interruptible: false
  environment:
    name: staging
    url: https://staging.example.com
  script: ./deploy.sh staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:production:
  stage: deploy
  needs: [deploy:staging]
  resource_group: production_env
  interruptible: false
  environment:
    name: production
    url: https://example.com
    on_stop: stop:production
  script: ./deploy.sh production
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

stop:production:
  stage: deploy
  interruptible: false
  environment:
    name: production
    action: stop
  script: ./cleanup.sh production
  when: manual
```

### Сценарий 7: Pipeline для Infrastructure-as-Code (Terraform + Ansible)

Пайплайн для управления инфраструктурой с plan/apply через `resource_group` и `environment`:

```yaml
workflow:
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

default:
  image: hashicorp/terraform:1.9
  before_script:
    - terraform init -backend-config="backend.hcl"

stages:
  - validate
  - plan
  - apply

validate:
  stage: validate
  script:
    - terraform validate
    - terraform fmt -check

plan:
  stage: plan
  script:
    - terraform plan -out=tfplan -var-file=env/${ENVIRONMENT}.tfvars
  artifacts:
    paths: [tfplan]
    expire_in: 1 hour
  variables:
    ENVIRONMENT: staging

apply:
  stage: apply
  resource_group: terraform_${ENVIRONMENT}
  interruptible: false
  script:
    - terraform apply -auto-approve tfplan
  dependencies: [plan]
  environment:
    name: ${ENVIRONMENT}
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 8: Безопасная миграция базы данных

Демонстрация использования `resource_group`, `interruptible: false` и `allow_failure: false` для критических операций:

```yaml
db_migrate:
  stage: deploy
  resource_group: database_cluster_prod
  interruptible: false
  allow_failure: false
  timeout: 15 minutes
  retry:
    max: 0  # Миграции не перезапускаются автоматически
  before_script:
    - PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT version()"
  script:
    - alembic upgrade head
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

db_rollback:
  stage: deploy
  resource_group: database_cluster_prod
  interruptible: false
  timeout: 10 minutes
  script:
    - alembic downgrade -1
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 9: Интеграция с внешними сервисами через `services`

Запуск интеграционных тестов с реальными зависимыми сервисами:

```yaml
test:integration:
  stage: test
  services:
    - name: postgres:16
      alias: db
      variables:
        POSTGRES_DB: app_test
        POSTGRES_USER: test
        POSTGRES_PASSWORD: test
    - name: redis:7-alpine
      alias: cache
  variables:
    DATABASE_URL: "postgresql://test:test@db:5432/app_test"
    REDIS_URL: "redis://cache:6379"
  script:
    - pytest tests/integration/ --db-url=$DATABASE_URL
  timeout: 15 minutes
```

## Валидация конфигурации

Перед коммитом сложного `.gitlab-ci.yml` проверьте конфигурацию на всех уровнях:

### 1. Синтаксис YAML

```bash
# Локальная проверка синтаксиса YAML
python3 -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml'))"

# Или через yamllint
yamllint .gitlab-ci.yml
```

### 2. Pipeline Lint (встроенный)

В интерфейсе GitLab: `CI/CD → Editor → CI Lint`. Вставьте итоговый YAML (с учётом всех `include`) и нажмите **Validate**. Инструмент проверяет:
- Синтаксис директив
- Типы переменных в `spec:inputs`
- Целостность ссылок `!reference`
- Корректность `rules` и `workflow:rules`

### 3. Simulate pipeline

В том же CI Lint доступен **Simulate pipeline** — показывает, какие задачи будут запущены для указанного ветки/тега/MR, без реального выполнения. Позволяет отладить `rules`, `workflow:rules` и `only/except`.

### 4. Локальная проверка через `glab`

```bash
# Установка glab (macOS)
brew install glab

# Линт без коммита
glab ci lint --file .gitlab-ci.yml
```

### 5. Верификация артефактов и кэша

После первого успешного запуска проверьте:
- **Артефакты**: `CI/CD → Pipelines → [pipeline] → [job] → Artifacts` — убедитесь, что файлы передаются между стадиями
- **Кэш**: `CI/CD → Pipelines → [pipeline] → [job] → Cache` — проверьте hit/miss ratio
- **Размер**: Мониторьте потребление диска на GitLab Server (`du -sh /var/opt/gitlab/artifacts`)

### 6. Dry-run через переменные

Для отладки `rules` без реального деплоя используйте `when: manual` в связке с `workflow:rules`:

```yaml
deploy:staging:
  stage: deploy
  script: ./deploy.sh staging
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

## Устранение неполадок (Troubleshooting)

### Типичные ошибки конфигурации
-   **Циклическая зависимость (Circular Dependency)**: Возникает, когда в `needs` образуется цикл (Задача А требует Б, Б требует А). GitLab выдаст ошибку `circular dependency detected`. Решение: пересмотреть архитектуру графа.
-   **Отсутствующий артефакт в `needs`**: Если задача зависит от другой через `needs`, она получит артефакты ТОЛЬКО от перечисленных задач. Если нужны артефакты от других стадий, их нужно добавить в список `needs`.
-   **Превышение квоты артефактов**: Если пайплайн падает с ошибкой лимита хранилища, используйте агрессивный `expire_in` или удаляйте ненужные файлы в `after_script`.
-   **Ошибка валидации YAML при использовании `inputs`**: Если переданный параметр не соответствует типу в `spec:inputs`, пайплайн не создастся. Проверяйте синтаксис через **CI Lint**.
-   **Пустой пайплайн (Empty Pipeline)**: Все задачи отфильтрованы через `rules`. Решение: проверьте `workflow:rules` — добавьте fallback-правило или убедитесь, что условия `rules` задач не исключают все задачи одновременно.
-   **Задача не запускается**: `rules` не совпали или `only/except` исключили. Решение: проверьте условия `rules` через Pipeline Editor, используйте "Simulate pipeline".
-   **Deadlock в Resource Group**: Если задача зависла и удерживает группу, последующие пайплайны будут ждать бесконечно. Решение: ручная очистка в `CI/CD -> Resource Groups` или настройка `timeout` для задачи с `resource_group`.
-   **Dotenv переменные не видны в `rules`**: Переменные из `artifacts:reports:dotenv` вычисляются после парсинга конфигурации и **недоступны** в `rules`. Решение: используйте предопределённые переменные GitLab или передавайте данные через API.
-   **`before_script` не влияет на `after_script`**: Если `script` упал, `after_script` всё равно выполнится, но в отдельном контейнере. Код завершения `script` недоступен в `after_script`.
-   **Кэш не сохраняется при `auto_cancel`**: Прерванная задача не сохраняет кэш. Используйте `cache:when: always` для критичных кэшей (с осторожностью — кэш сохраняется даже при падении).
-   **Bridge Job ждет бесконечно**: По умолчанию Bridge Job (downstream trigger) имеет таймаут 1 час. Для downstream с `manual` действиями увеличьте `timeout` явно.

### Инструменты диагностики
-   **Pipeline Editor (Merged YAML)**: Позволяет увидеть итоговый файл со всеми инъекциями.
-   **CI Lint**: Обязательный инструмент перед коммитом сложных изменений. Используйте "Simulate pipeline" для проверки `rules` и `inputs`.
-   **Variables Trace**: Используйте `export` или `env` в начале скрипта для проверки доступных переменных (осторожно с секретами!).
-   **CI_DEBUG_TRACE**: Включение отладочного вывода для анализа переменных и выполнения скриптов.
-   **`glab ci lint`**: CLI-утилита для локальной проверки конфигурации без коммита.
-   **Resource Groups UI**: `CI/CD -> Resource Groups` — просмотр и ручная очистка заблокированных ресурсов.
-   **Audit Logs**: Логи изменений переменных в настройках проекта — полезно при подозрении на несанкционированные изменения.

## Best Practices

### Проектирование пайплайнов

- **Атомарность задач**: Одна задача — одна ответственность. Разделяйте линтинг, тесты, сборку и деплой на отдельные задачи. Это упрощает отладку и позволяет переиспользовать логику.
- **Изоляция сред**: Используйте `image` для каждой задачи вместо глобального `default:image`, если задачи требуют разных ОС или версий языков. Избегайте "зоопарка" в одной задаче.
- **Fail Fast**: Размещайте быстрые проверки (линтинг, статический анализ) в ранних стадиях. Это экономит ресурсы раннеров на заведомо ошибочных изменениях.
- **Явные таймауты**: Задавайте `timeout` для каждой задачи. Значение по умолчанию (1 час) может быть слишком большим для быстрых проверок или недостаточным для длительных тестов.
- **Версионируемость**: Фиксируйте версии Docker-образов (`python:3.12.4-slim` вместо `python:latest`). Используйте SHA-коммиты для внешних шаблонов `include`.

### Надёжность и устойчивость

- **`interruptible: false` для критических операций**: Деплой, миграции БД, изменение конфигурации firewall/load balancer всегда должны иметь `interruptible: false`, чтобы `auto_cancel` не прервал транзакционный процесс.
- **`resource_group` для эксклюзивного доступа**: Все операции, изменяющие общее состояние (база данных, файловое хранилище, сетевые интерфейсы), должны serializovat'sya через `resource_group` с подходящим `resource_group_process_mode`.
- **Политика `retry` для инфраструктурных сбоев**: Включайте `retry` только для `runner_system_failure`, `stuck_or_timeout_failure`, `api_failure`, `scheduler_failure`. Никогда не включайте `script_failure` без веской причины — это скрывает баги в коде.
- **`allow_failure` с `exit_codes`**: Для необязательных проверок (например, deprecation-warnings) используйте `allow_failure: true` с `exit_codes: [0, 1]`, чтобы区分 "успех с предупреждениями" от "реальной ошибки".
- **Защита веток**: Настройте `Protected branches` и `Protected tags` в GitLab. Задачи с `rules:protected` автоматически получают доступ к защищённым переменным.

### Безопасность

- **OIDC вместо статических токенов**: Используйте `id_tokens` для аутентификации в Vault, реестрах образов, облачных API. JWT-токены короткоживущие и привязаны к конкретному пайплайну.
- **`Protected` и `Masked` переменные**: Все секреты должны быть `Masked` (скрыты в логах) и `Protected` (доступны только в защищённых ветках). Проверяйте переменные через **CI Lint → Variables**.
- **Очистка секретов в логах**: Используйте `CI_JOB_TOKEN` вместо `PRIVATE-TOKEN` где возможно. При передаче секретов в скрипты используйте `export` без эхо в лог (`set -a; source .env; set +a`).
- **Минимизация прав Runner'ов**: Runner, используемый для деплоя, не должен иметь доступа к исходному коду других проектов. Используйте групповые Runner'ы с ограниченным `scope`.

### Экономия ресурсов

- **`auto_cancel` для MR-пайплайнов**: Настройте `workflow:auto_cancel` с `on_new_commit: interruptible` для веток разработки. Это высвобождает раннеры при активном пуше.
- **`cache:key` по файлу зависимостей**: Используйте `cache:key:files: [package-lock.json, go.sum]` вместо глобального ключа. Это сохраняет кэш при изменении кода, но сбрасывает при обновлении зависимостей.
- **`dependencies: []` и `needs: []`**: Для задач, которым не нужны артефакты предыдущих стадий, явно указывайте пустой список, чтобы GitLab не скачивал лишние файлы.
- **`expire_in` для артефактов**: Устанавливайте разумный `expire_in` (1 hour для промежуточных сборок, 1 week для релизов). Автоматическая очистка предотвращает исчерпание хранилища.

### Мониторинг и наблюдаемость (SRE)

- **Метрики пайплайнов**: Настройте Prometheus scrape для GitLab Server (`/-/metrics`). Ключевые метрики: `gitlab_ci_pipeline_time_to_finished_seconds`, `gitlab_ci_pipeline_failure_reasons`, `gitlab_ci_current_queue_size`.
- **Алертинг на Success Rate**: Доля успешных пайплайнов должна быть >95% для production. Настройте Alertmanager на падение ниже порога.
- **Тренд времени сборки**: Резкий рост среднего времени пайплайна указывает на деградацию кэша или инфраструктуры Runner'ов. Отслеживайте через Grafana.
- **Стоимость вычислительных ресурсов**: В self-hosted среде мониторьте CPU/RAM на Runner'ах. Используйте `resource_group` и `timeout` для контроля ресурсопотребления.

### Управление Runner'ами (Sysadmin)

- **Групповая привязка**: Регистрируйте Runner'ы на уровне группы, а не проекта. Это упрощает управление и позволяет переиспользовать Runner'ы между проектами.
- **Теги для маршрутизации**: Используйте теги (`gpu`, `vpn`, `ssd`, `windows`) для направления задач на специализированные Runner'ы. Избегайте дефолтного Runner для всех задач.
- **Очистка Docker**: Настройте `helper_image_autoclean` в `config.toml` и регулярную очистку неиспользуемых образов (`docker image prune -af`).
- **Мониторинг Runner'а**: Отслеживайте `gitlab_runner_jobs_total` и `gitlab_runner_errors_total` через Prometheus. Настройте алерты при росте ошибок.

## Граничные условия и ограничения (Edge Cases)

### Версионная совместимость

- **`rules` vs `only/except`**: `rules` заменили `only/except` начиная с GitLab 13.9. Старые конфигурации с `only/except` продолжают работать, но `rules` рекомендуются для новых пайплайнов.
- **`needs` для DAG** доступны с GitLab 12.2, но полная поддержка `parallel:matrix` с `needs` появилась в 13.3.
- **`resource_group`** доступен с GitLab 13.12.
- **`spec:inputs`** доступен с GitLab 17.11.
- **`parallel:matrix` с `needs`**: Матричная адресация 1:1 работает с GitLab 16.3+, выражения `$[[ matrix.VAR ]]` — с 18.6+.

### Ограничения механизмов

- **Dotenv и `rules`**: Переменные из `artifacts:reports:dotenv` вычисляются после парсинга конфигурации и **недоступны** в `rules` или `workflow:rules`. Для условного запуска используйте предопределённые переменные GitLab.
- **Dotenv и матричные сборки**: Переменные из `reports: dotenv` **не работают** между инстансами `parallel:matrix`. Для передачи данных между матричными задачами используйте файловые артефакты или API.
- **Матричные лимиты**: Максимальное количество задач, генерируемых одной матрицей, — **200**. Для обхода лимита используйте несколько блоков матриц или динамическую генерацию пайплайнов.
- **`before_script`/`after_script` на верхнем уровне**: Считаются устаревшими в GitLab 18.x/19.x. Используйте блок `default:` для общих настроек.
- **Bridge Job timeout**: По умолчанию Bridge Job (downstream trigger) имеет таймаут 1 час. Для downstream с `manual` действиями увеличьте `timeout` явно.
- **Dotenv размер**: Файл `dotenv` не может превышать **5 МБ**. При необходимости передачи больших объёмов данных используйте артефакты.

### Специфические сценарии

- **Deadlock в parent-child пайплайнах**: Если родительский и дочерний пайплайн используют одну и ту же `resource_group` с режимом `oldest_first`, возникает взаимная блокировка. Решение — определить `resource_group` в родительской задаче `trigger`, а не в дочерней.
- **Merge Queue и `auto_cancel`**: В merge queue отключение `auto_cancel.on_new_commit: interruptible` критично. Иначе инициированный merge request может отменить pipeline предыдущего MR в очереди.
- **`interruptible: true` не отменяет запущенный job**: Механизм работает только на уровне планирования. Если job уже выполняется на Runner'е, он не будет прерван. Убедитесь, что Runner'ы поддерживают отмену через API.
- **Кэш не сохраняется при `auto_cancel`**: Прерванная задача не сохраняет кэш. Используйте `cache:when: always` для критичных кэшей (с осторожностью — кэш сохраняется даже при падении).
- **Пустой пайплайн**: Все задачи отфильтрованы через `rules`. Решение: проверьте `workflow:rules` — добавьте fallback-правило или убедитесь, что условия `rules` задач не исключают все задачи одновременно.

### Ограничения инфраструктуры

- **Очередь Runner при высокой нагрузке**: При более чем 100 коммитах в день настройте `interruptible: true` для задач валидации в MR. Это отменяет устаревшие запуски при новом пуше, экономя ресурсы.
- **Исчерпание диска артефактами**: Регулярно проверяйте `du -sh /var/opt/gitlab/artifacts`. Настройте агрессивный `expire_in` или внешнее хранилище артефактов.
- **Сетевые задержки между Runner'ами и GitLab**: При использовании Docker-исполнителя в L2-сети убедитесь, что MTU настроен корректно, иначе артефакты могут передаваться с фрагментацией.

## Дополнительная информация

### Безопасность

-   Используйте `secret_detection` для поиска ключей в коде.
-   Используйте **Pipeline Execution Policies** для принудительных проверок на уровне группы.
-   Настройте `Protected` и `Masked` для переменных с секретами.
-   Используйте `resource_group` для предотвращения одновременного деплоя в production.
-   Внедряйте OIDC вместо статических токенов для аутентификации в внешних системах.

### Мониторинг и наблюдаемость пайплайнов

-   **Prometheus-метрики GitLab**: GitLab Server экспортирует нативные метрики через `/-/metrics` (`pipelines_created_total`, `gitlab_ci_pipeline_time_to_finished_seconds`, `gitlab_ci_pipeline_failure_reasons`, `gitlab_ci_current_queue_size`). Внешние экспортёры (`gitlab-ci-pipelines-exporter`) добавляют метрики вида `gitlab_ci_pipeline_duration_seconds`, `gitlab_ci_pipeline_status`. Настройте scrape в Prometheus для сбора данных.
-   **Среднее время сборки**: Отслеживание тренда среднего времени пайплайна помогает выявить деградацию производительности. Резкий рост может указывать на проблемы с кэшем или инфраструктурой Runner'ов.
-   **Success Rate**: Доля успешных пайплайнов — ключевой индикатор стабильности. Цель для production: >95%.
-   **Стоимость сборки**: В самохостинге отслеживайте потребление CPU/RAM на Runner'ах. Используйте `resource_group` и `timeout` для контроля ресурсопотребления.

### Self-hosted Runner: особенности проектирования

-   **Теги для маршрутизации**: Используйте `tags` для направления задач на специализированные Runner'ы (GPU, VPN, конкретная сеть). Не полагайтесь на дефолтный Runner для всех задач.
-   **Привязка к проекту/группе**: Регистрируйте Runner'ы на уровне группы, а не проекта — это упрощает управление и позволяет переиспользовать между проектами.
-   **Достаточное количество слотов**: Убедитесь, что `concurrent` в `config.toml` Runner'а достаточен для пиковой нагрузки. Нехватка слотов приводит к排队 (очереди) и увеличению времени ожидания.
-   **Очистка Docker**: Настройте `helper_image_autoclean` и регулярную очистку неиспользуемых образов (`docker image prune -af`), чтобы не исчерпать дисковое пространство.
-   **Мониторинг Runner'а**: Отслеживайте `gitlab_runner_jobs_total` и `gitlab_runner_errors_total` через Prometheus. Настройте алерты при росте ошибок.

### См. также
