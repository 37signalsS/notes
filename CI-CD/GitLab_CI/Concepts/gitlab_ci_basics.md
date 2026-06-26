# Основы GitLab CI/CD

## Определения

Иерархия компонентов в GitLab CI/CD строится по принципу "от общего к частному". Подробный глоссарий — в [pipeline_glossary.md](../../Core_Concepts/pipeline_glossary.md).

* **[Pipeline](https://docs.gitlab.com/ci/pipelines/)**: Высокоуровневая структура, которая определяет полный цикл CI/CD. Состоит из Stage и запускается по различным событиям (коммит, Merge Request, расписание).
* **[Stage](https://docs.gitlab.com/ci/yaml/stages/)**: Группирует Job и определяет порядок их выполнения. Все Job одного Stage выполняются параллельно, а сами Stage — последовательно.
* **[Job](https://docs.gitlab.com/ci/jobs/)**: Минимальная единица работы. Выполняет определенный набор команд (скриптов) для сборки, тестирования или Deploy.
* **[Runner](https://docs.gitlab.com/runner/)**: Приложение, которое выполняет Job. Оно устанавливается на сервер или запускается в контейнере и постоянно опрашивает GitLab на предмет новых Job. Настройка — в [gitlab_ci_runners_executors.md](../Advanced/gitlab_ci_runners_executors.md).

## Базовые концепции

### Архитектура GitLab CI/CD

Для работы GitLab CI/CD необходимы три ключевых компонента (подробнее об общей архитектуре платформы — в [gitlab_platform_architecture.md](./gitlab_platform_architecture.md)):

1. **GitLab Server** — принимает код из репозитория, обнаруживает изменения (push, merge request, тег) и запускает Pipeline.
2. **GitLab Runner** — отдельный агент, который опрашивает GitLab на предмет Job и выполняет их. Runner может запускать Job в различных окружениях:
   * **Docker Executor** — каждая Job выполняется в отдельном Docker-контейнере (наиболее распространённый вариант)
   * **Kubernetes Executor** — Job запускаются в подах Kubernetes
   * **Shell Executor** — команды выполняются непосредственно на хост-машине (не рекомендуется для production из-за отсутствия изоляции)
   * **SSH Executor** — Runner подключается к удалённому серверу по SSH для Deploy
3. **`.gitlab-ci.yml`** — файл конфигурации в корне репозитория, описывающий Pipeline (Stage, Job, переменные, условия запуска).

Дополнительно GitLab может включать встроенный **Container Registry** для хранения Docker-образов, собранных в Pipeline.

```
[Developer] --push--> [GitLab Server] --триггер--> [Pipeline]
                                                |
                                                v
                                          [GitLab Runner]
                                          |-- Docker Executor
                                          |-- Kubernetes Executor
                                          |-- Shell Executor
                                          |-- SSH Executor
```

Подробная информация о типах Runner и Executor — в [gitlab_ci_runners_executors.md](../Advanced/gitlab_ci_runners_executors.md). Установка self-hosted GitLab с Runner — в [self_hosted_installation.md](../Tutorials/self_hosted_installation.md).

### Типовые стадии Pipeline (Lifecycle)

Для стандартного микросервиса Pipeline обычно включает следующие Stage:

1. **Lint/Check**: Проверка стиля кода (Code Style) и статический анализ (SAST).
2. **Unit Tests**: Запуск модульных тестов.
3. **Build**: Сборка приложения, компиляция бинарных файлов или создание Docker-образов.
4. **Functional/Integration Tests**: Тестирование взаимодействия компонентов в изолированной среде.
5. **Push**: Загрузка собранных образов в реестр (Registry).
6. **Deploy**: Развертывание в тестовые (Staging) или продуктивные (Production) окружения.

### Разница между артефактами и кэшем

| Характеристика | Артефакты (`artifacts`) | Кэш (`cache`) |
| :--- | :--- | :--- |
| **Назначение** | Передача результатов между **Stage** одного Pipeline | Ускорение сборки между **разными** Pipeline (например, `node_modules`, `pip cache`) |
| **Жизненный цикл** | Удаляются автоматически по истечении `expire_in` | Сохраняются до очистки или истечения TTL на Runner |
| **Использование** | Доступны для скачивания через UI GitLab | Недоступны для скачивания через UI |
| **Передача** | Передаются от Job к Job по иерархии Stage | Сохраняются локально на Runner (или в S3 при Distributed Cache) |

### Файл `.gitlab-ci.yml`

Это YAML-файл в корне репозитория, который является единой точкой конфигурации для всего Pipeline. GitLab автоматически обнаруживает его и выполняет описанные в нем инструкции.

> **Важно (GitLab 18.x):** Глобальные ключевые слова `before_script`, `after_script`, `image`, `cache` на верхнем уровне **deprecated**. Используйте [`default`](#структурные-ключевые-слова).

### Ключевые слова для управления Pipeline

#### Структурные ключевые слова

* **`stages`**: Определяет последовательность выполнения Stage. Следующий Stage начнется только после успешного завершения всех Job предыдущего.
* **`image`**: Указывает Docker-образ по умолчанию для выполнения всех Job.
* **`variables`**: Определяет [переменные окружения](./gitlab_ci_variables_secrets.md), доступные внутри Job.
* **`default`**: Задает набор настроек по умолчанию, которые наследуются всеми Job.

#### Ключевые слова для Job

* **`stage`**: Присваивает Job определенному Stage из списка `stages`.
* **`script`**: Основной и обязательный блок. Содержит shell-команды, которые выполняет Runner.
* **`before_script` / `after_script`**: Команды, выполняемые до или после основного `script`. `after_script` выполняется даже при провале Job.
* **`artifacts`**: Определяет файлы и директории, которые сохраняются после успешного выполнения Job и могут быть переданы на следующие Stage. Подробнее см. **[Артефакты и кэш в GitLab CI](../Advanced/gitlab_ci_caching/caching_overview.md)**.
* **`cache`**: Механизм сохранения файлов между запусками Job для ускорения сборок. Подробнее см. **[Артефакты и кэш в GitLab CI](../Advanced/gitlab_ci_caching/caching_overview.md)**.
* **`needs`**: Создает направленную ациклическую графовую (DAG) зависимость между Job, позволяя запускать их сразу после завершения зависимостей, не дожидаясь окончания всего Stage.
* **`dependencies`**: Определяет, какие артефакты из предыдущих Job нужно загрузить. По умолчанию загружаются артефакты всех предыдущих Job.

#### Управление потоком выполнения

* **`rules`**: Мощный механизм для определения условий, при которых Job будет (или не будет) добавлена в Pipeline. **Является заменой `only`/`except`** (deprecated в GitLab 18.x) и предпочтителен для использования. Поддерживает:
  * `rules:if` — условные выражения
  * `rules:changes` — изменения в файлах
  * `rules:exists` — существование файлов
  * `auto_cancel` (GitLab 16.8+) — автоотмена Pipeline
* **`when`**: Указывает, когда запускать Job. Например, `on_success` (по умолчанию), `on_failure`, `always` или `manual` (для ручного запуска). В контексте `workflow:rules` принимает только `always` или `never`.

### Взаимосвязь `needs` и `dependencies`

Эти два ключевых слова часто используются вместе, но решают разные задачи:

* **`needs`**: Управляет **порядком выполнения** Job, создавая DAG.
* **`dependencies`**: Управляет **передачей артефактов** между Job.

Если Job использует `needs`, то `dependencies` по умолчанию устанавливается в `needs: [...]`. То есть, будут загружены артефакты только от тех Job, которые перечислены в `needs`. Чтобы не загружать артефакты вообще, используется `dependencies: []`.

### Механизмы переиспользования (DRY)

Для избежания дублирования кода GitLab CI предлагает несколько механизмов, таких как `extends`, `!reference` и `include`.

Подробное описание этих механизмов см. в статье: **[Создание переиспользуемых и композитных Pipeline](../Reusable_Pipelines/overview.md)**. Продвинутые сценарии — в [gitlab_ci_advanced_workflow.md](../Advanced/gitlab_ci_advanced_workflow.md).

> **Новое в GitLab 18.x:**
>
> * **`include:cache`** (18.9, experiment) — кэширование удалённых файлов include с TTL
> * **`spec:include`** (18.9, GA) — включение внешних определений inputs
> * **`spec:inputs:rules`** (18.7, GA) — условные опции для входных параметров

## Практические сценарии

### Комплексный базовый Pipeline

Этот пример демонстрирует многие основные концепции GitLab CI в одном файле.

```yaml
# 1. Определение последовательности Stage
stages:
  - build
  - test
  - deploy

# 2. Глобальные переменные
variables:
  APP_ENV: production

# 3. Настройки по умолчанию для всех Job
default:
  image: python:3.12
  before_script:
    - pip install -r requirements.txt

# 4. Job сборки
build_job:
  stage: build
  script:
    - python -m build
  artifacts:
    # Сохраняем собранные файлы на 1 неделю
    paths:
      - dist/
    expire_in: 1 week

# 5. Job тестирования
test_job:
  stage: test
  # `needs` создает зависимость от `build_job`, позволяя `test_job` начаться 
  # сразу после `build_job`, не дожидаясь завершения всей Stage `build`.
  # `dependencies` автоматически наследует значение `needs`, поэтому артефакты 
  # из `build_job` будут загружены.
  needs: ["build_job"]
  script:
    - pytest -q

# 6. Job развертывания
deploy_job:
  stage: deploy
  environment:
    name: production
    url: https://app.example.com
  # Эта Job зависит от `test_job`, но ей не нужны артефакты.
  # `needs: ["test_job"]` для порядка выполнения.
  # `dependencies: []` чтобы не скачивать артефакты.
  needs: ["test_job"]
  dependencies: []
  script:
    - ./scripts/deploy.sh $CI_COMMIT_SHORT_SHA
  # Правило: Job доступна только для ветки 'main' и запускается вручную.
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

### Разбор примера

1. **`stages`**: Определяет три последовательных Stage: `build`, `test`, `deploy`.
2. **`default`**: Указывает, что все Job по умолчанию будут использовать образ `python:3.12` и выполнять `pip install`.
3. **`build_job`**: Находится на Stage `build`, выполняет сборку и сохраняет директорию `dist/` как **артефакт**.
4. **`test_job`**: Зависит от `build_job` (`needs`), что позволяет ей запуститься раньше. Она автоматически загружает артефакты из `build_job`.
5. **`deploy_job`**: Зависит от `test_job`. `dependencies: []` используется для оптимизации, так как для развертывания не требуются артефакты из предыдущих Job.
6. **`rules`**: Job `deploy_job` будет создана только для ветки `main` и потребует ручного запуска через UI.

## Дополнительная информация

* **CI Lint Tool**: Для проверки синтаксиса `.gitlab-ci.yml` перед коммитом используйте встроенный валидатор. Он находится в UI GitLab в разделе `CI/CD` -> `Editor`. Это незаменимый инструмент для отладки, так как он показывает полностью "развернутую" конфигурацию со всеми `include`.

* **Полный справочник ключевых слов**: Детальное описание всех доступных ключевых слов и их опций можно найти в [официальной документации GitLab](https://docs.gitlab.com/ci/yaml/).

* **Стратегия ветвления**: О стратегии ветвления GitLab Flow для эффективной разработки — в [gitlab_flow.md](../Tutorials/gitlab_flow.md).

> **Критичные изменения GitLab 18.x:**
>
> * **18.3**: Переменные по умолчанию маскируются (`Masked` вместо `Visible`)
> * **18.4**: `environment:kubernetes:namespace` deprecated → используйте `environment:kubernetes:dashboard:namespace`
> * **18.6**: `expand variable reference` отключён по умолчанию
> * **18.9**: `include:cache` (experiment) для кэширования remote includes
