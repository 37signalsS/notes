# Дочерние и мультипроектные пайплайны GitLab CI/CD

## Определения

**Downstream pipeline** — любой пайплайн GitLab CI/CD, запущенный другим пайплайном. Выполняется независимо и параллельно с upstream-пайплайном.

**Два типа downstream pipelines:**

| Тип | Описание | Ограничения |
| :--- | :--- | :--- |
| **Parent-child pipeline** | Downstream в том же проекте | Макс. 2 уровня вложенности |
| **Multi-project pipeline** | Downstream в другом проекте | Без ограничений вложенности |

**Динамическая генерация пайплайнов** — паттерн, при котором конфигурация `.gitlab-ci.yml` создаётся во время выполнения родительского пайплайна. Обеспечивает высокую гибкость.

## Основные концепции

### Parent-child pipelines

**Характеристики:**
- Выполняются в том же проекте, ref и commit SHA
- Не отображаются в общем списке пайплайнов (только на странице родителя)
- Автоматически отменяются при настройке `interruptible`
- **Максимальная глубина: 2 уровня** child pipelines

**Пример:**
```yaml
# Родительский .gitlab-ci.yml
child-pipeline:
  stage: test
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

### Multi-project pipelines

**Характеристики:**
- Запускаются из пайплайна другого проекта
- Upstream может выбрать ref downstream и передать переменные
- Отображаются в списке пайплайнов downstream-проекта
- **Нет ограничений на вложенность**

**Требования безопасности:**
- Пользователь должен иметь права на запуск пайплайнов в downstream-проекте
- При использовании публичного проекта для запуска private проверьте конфиденциальность

**Пример:**
```yaml
trigger_downstream:
  stage: deploy
  trigger:
    project: 'group/downstream-project'
    branch: main
```

### Стратегии выполнения: `strategy`

#### `strategy: mirror`

Отображает статус downstream pipeline в trigger job:

```yaml
trigger_job:
  trigger:
    include:
      - local: path/to/child-pipeline.yml
    strategy: mirror
```

**Применение:**
- Parent-child и multi-project pipelines
- Авто-отмена родительского пайплайна при провале child (если настроен `workflow: auto_cancel`)

#### `strategy: depend`

Отображает отчёты child pipeline в Merge Request виджетах:

```yaml
test-backend:
  trigger:
    include: backend-tests.yml
    strategy: depend

test-frontend:
  trigger:
    include: frontend-tests.yml
    strategy: depend
```

**Критично для:**
- Unit test отчётов (JUnit)
- Code quality отчётов
- Terraform отчётов
- Security отчётов (SAST, secret detection, container scanning, DAST)

**Без `strategy: depend`** родительский пайплайн завершается до окончания child pipelines, и их отчёты не появляются в Merge Request.

### Динамические child pipelines

Генерация конфигурации "на лету":

```yaml
generate-config:
  stage: build
  script:
    - python generate_ci_config.py > generated-config.yml
  artifacts:
    paths:
      - generated-config.yml

child-pipeline:
  stage: test
  trigger:
    include:
      - artifact: generated-config.yml
        job: generate-config
```

**Ограничения:**
- Артефакт должен быть в пределах лимитов инстанса
- Нельзя использовать CI/CD переменные в `include` секции динамического child pipeline

## Наследование переменных

### Сравнение наследования

| Тип переменных | Child Pipelines | Multi-project Pipelines |
| :--- | :--- | :--- |
| **Predefined (CI_*)** | Наследуют все | Наследуют только относящиеся к downstream проекту |
| **Project/Group variables** | Наследуют все | **НЕ наследуют** |
| **Variables из задачи** | Наследуют | **Только явно указанные** в `trigger:variables` |
| **Masked variables** | Наследуют | **НЕ наследуют** (риск unmask!) |

### 1. Variables keyword (наследование)

```yaml
variables:
  VERSION: "1.0.0"

staging:
  variables:
    ENVIRONMENT: staging
  stage: deploy
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

- `ENVIRONMENT` доступен во всех jobs downstream pipeline
- `VERSION` наследуется как default variable

### 2. Блокировка наследования

```yaml
trigger-job:
  inherit:
    variables: false  # Блокировать наследование default variables
  variables:
    JOB_VAR: value
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

- `DEFAULT_VAR` не передаётся в triggered pipeline
- `JOB_VAR` доступен

### 3. Predefined variables (интерполяция)

```yaml
trigger-job:
  variables:
    PARENT_BRANCH: $CI_COMMIT_REF_NAME  # Сохраняет как job variable
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

⚠️ **Важно:** Не используйте для masked variables в multi-project pipelines (masking не передаётся).

### 4. Inputs keyword (рекомендуется для GitLab 17+)

**Преимущества перед `variables`:**
- Type checking
- Validation через `options`
- Descriptions
- Default values
- Безопасность (защита от инъекций)

**В target configuration:**
```yaml
# child-pipeline.yml
spec:
  inputs:
    environment:
      description: "Окружение для деплоя"
      options: [staging, production]
      default: staging
    version:
      type: string
      description: "Версия приложения"
      default: "1.0.0"
    enable_tests:
      type: boolean
      description: "Запускать ли тесты"
      default: true
```

**При запуске:**
```yaml
staging:
  trigger:
    include:
      - local: path/to/child-pipeline.yml
    inputs:
      environment: staging
      version: "1.0.0"
      enable_tests: true

production:
  trigger:
    include:
      - local: path/to/child-pipeline.yml
    inputs:
      environment: production
      version: "1.0.0"
      enable_tests: false
```

**Использование в triggered pipeline:**
```yaml
# В child-pipeline.yml
deploy_job:
  script:
    - echo "Deploying version $[[ inputs.version ]] to $[[ inputs.environment ]]"
    - |
      if [[ "$[[ inputs.enable_tests ]]" == "true" ]]; then
        echo "Running tests..."
        npm test
      fi
```

**Миграция с variables на inputs:**

| Variables | Inputs |
| :--- | :--- |
| `$VARIABLE_NAME` | `$[[ inputs.VARIABLE_NAME ]]` |
| Нет валидации типов | Строгая типизация (string, boolean, number) |
| Нет проверки значений | `options` для допустимых значений |
| Может быть переопределена | Защищено от несанкционированного изменения |

### 5. Dotenv variable inheritance (Premium/Ultimate)

```yaml
# Upstream
build_vars:
  stage: build
  script:
    - echo "BUILD_VERSION=hello" >> build.env
  artifacts:
    reports:
      dotenv: build.env

deploy:
  stage: deploy
  trigger: my/downstream_project

# Downstream
test:
  stage: test
  script:
    - echo $BUILD_VERSION
  needs:
    - project: my/upstream_project
      job: build_vars
      ref: master
      artifacts: true
```

### Практические сценарии

#### 1. Передача переменных в мультипроектный пайплайн

```yaml
# .gitlab-ci.yml в родительском проекте
trigger_downstream_build:
  stage: deploy
  trigger:
    project: 'my-group/my-downstream-project'
    branch: main
    strategy: depend
  variables:
    UPSTREAM_PIPELINE_ID: $CI_PIPELINE_ID # Явная передача переменной
    CUSTOM_MESSAGE: "Hello from upstream!"
```

В дочернем пайплайне `my-downstream-project` будут доступны `UPSTREAM_PIPELINE_ID` и `CUSTOM_MESSAGE`.

#### 2. Запуск мультипроектного пайплайна

**Проект A (запускающий): `.gitlab-ci.yml`**

```yaml
trigger_downstream_build:
  stage: deploy
  trigger:
    project: 'my-group/my-downstream-project' # Путь к дочернему проекту
    branch: main
    strategy: depend # Ждем завершения дочернего пайплайна
```

#### 3. Динамическая генерация пайплайнов с Python и Jinja2

**Принцип работы:** Скрипт генерирует `.gitlab-ci.yml` на основе условий, который затем используется как конфигурация для дочернего пайплайна.

**1. `pipeline_template.j2` (Шаблон Jinja2 для генерации YAML):**

```jinja
# generated_pipeline.yml
{% for i in range(num_jobs) %}
job_{{ i }}:
  stage: build
  script:
    - echo "Running job {{ i }} with custom logic"
    - echo "This is a dynamically generated job."
  tags:
    - shell
{% endfor %}
```

**2. `generate_pipeline.py` (Python-скрипт для рендеринга шаблона):**

```python
from jinja2 import Template
import os

num_jobs = int(os.environ.get("NUM_GENERATED_JOBS", 3))

# Читаем шаблон из файла
with open("pipeline_template.j2", "r") as f:
    template_content = f.read()

template = Template(template_content)
generated_yaml = template.render(num_jobs=num_jobs)

with open("generated-ci-config.yml", "w") as f:
    f.write(generated_yaml)

print(f"Generated {num_jobs} jobs in generated-ci-config.yml")
```

**3. `.gitlab-ci.yml` (родительский пайплайн):**

```yaml
stages:
  - generate
  - build

generate-dynamic-config:
  stage: generate
  image: python:3.9-slim
  variables:
    NUM_GENERATED_JOBS: 5 # Пример: генерируем 5 заданий
  script:
    - pip install Jinja2
    - python generate_pipeline.py
  artifacts:
    paths:
      - generated-ci-config.yml # Важно: сгенерированный файл должен быть артефактом

run-generated-pipeline:
  stage: build
  trigger:
    include:
      - artifact: generated-ci-config.yml
        job: generate-dynamic-config # Ссылка на задание, которое сгенерировало артефакт
    strategy: depend
```

### Дополнительная информация

**Сценарии использования дочерних и мультипроектных пайплайнов:**

* **Управление зависимостями между микросервисами:** Автоматический запуск пересборки и тестирования микросервисов после обновления общих библиотек.
* **Разделение обязанностей и безопасности:** Вынесение конфиденциальной логики (например, деплой в продакшн, сканирование безопасности) в отдельный проект с ограниченным доступом. Родительский пайплайн только инициирует этот защищенный пайплайн.
* **Централизация шаблонов и инфраструктуры:** Общие пайплайны для сборки или деплоя могут находиться в центральном репозитории, а другие проекты лишь вызывают их.
* **Декомпозиция сложного `.gitlab-ci.yml`:** Разбивка большого конфигурационного файла на более мелкие, логически сгруппированные части, что повышает читаемость и управляемость.
* **Монорепозитории:** Запуск CI/CD только для тех частей монорепозитория, которые были затронуты изменениями, оптимизируя ресурсы и время выполнения.

**Полезность динамической генерации пайплайнов:**

* **Сложная логика выбора заданий:** Идеально для монорепозиториев, где нужно запускать только релевантные тесты или сборки.
* **Гибкое масштабирование:** Генерация множества однотипных заданий (для разных окружений, версий) без дублирования кода.
* **Конфигурация на основе данных:** Когда структура пайплайна зависит от внешних данных или файлов конфигурации проекта.

#### Best Practices (2025-2026)

1. **Используйте `inputs` вместо `variables` (GitLab 17+)**
   - Типизированные параметры с валидацией
   - Защита от инъекций и несанкционированного изменения

2. **`strategy: depend` для отчётов**
   - Обязательно для unit-тестов, code quality, security отчётов
   - Гарантирует отображение в Merge Request

3. **`strategy: mirror` для синхронизации статусов**
   - Отображает реальный статус downstream в trigger job
   - Авто-отмена при провале child pipeline

4. **Версионирование шаблонов**
   - Используйте `ref: 'v1.2.3'` для include из других проектов
   - Избегайте поломки при обновлении шаблонов

5. **Минимальные права для multi-project pipelines**
   - Проверяйте права пользователя на запуск в downstream-проекте
   - Используйте Deploy Tokens с ограниченными правами

6. **Ограничение вложенности**
   - Parent-child: максимум 2 уровня
   - Multi-project: без ограничений, но следите за сложностью

### Связанные документы

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые концепции.
- **[Механизм `include`](../Reusable_Pipelines/include_keyword.md)** — подключение внешних файлов.
- **[Продвинутые рабочие процессы](../Advanced/gitlab_ci_advanced_workflow.md)** — оптимизация пайплайнов.
