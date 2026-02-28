### Определения

**[Дочерние пайплайны (Child Pipelines)](https://docs.gitlab.com/ee/ci/pipelines/downstream_pipelines.html#child-pipelines)** позволяют запускать один или несколько дополнительных пайплайнов в рамках того же проекта из родительского пайплайна. Их конфигурация может быть определена в отдельном файле (или сгенерирована динамически) и включается с помощью директивы `trigger:include`.

**[Мультипроектные пайплайны (Multi-project Pipelines)](https://docs.gitlab.com/ee/ci/pipelines/downstream_pipelines.html#multi-project-pipelines)** дают возможность одному проекту (родительскому/upstream) инициировать запуск пайплайна в другом, независимом проекте (дочернем/downstream). Это реализуется через директиву `trigger:project`.

**Динамическая генерация пайплайнов** — это мощный паттерн, при котором конфигурация дочернего пайплайна (`.gitlab-ci.yml`) создается "на лету" с помощью скриптов во время выполнения родительского пайплайна. Это обеспечивает высокую гибкость и адаптивность.

### Основные концепции

#### Механизмы запуска

* **Мультипроектные пайплайны (`trigger:project`)**:
    Используется для связи проектов. Родительский пайплайн инициирует дочерний в другом репозитории.

    ```yaml
    # Родительский проект
    trigger_downstream:
      stage: deploy
      trigger:
        project: 'group/downstream-project' # Путь к дочернему проекту
        branch: main # Ветка, в которой запускается пайплайн
    ```

* **Дочерние пайплайны (`trigger:include`)**:
    Используется для декомпозиции или динамической конфигурации в рамках одного проекта.

    ```yaml
    # Родительский проект .gitlab-ci.yml
    include:
      - project: 'group/project'
        file: '/path/to/child-pipeline.yml'
        # Запуск дочернего пайплайна, определенного в другом файле этого же проекта
    
    # или
    
    run-dynamically-generated-pipeline:
      stage: test
      trigger:
        include:
          - artifact: generated-config.yml # Ссылка на сгенерированный артефакт
            job: generate-config-job # Задание, которое сгенерировало артефакт
    ```

#### Ожидание завершения (`strategy: depend`)

По умолчанию задача, запускающая дочерний пайплайн, завершается успешно сразу после его инициирования. Чтобы родительский пайплайн дождался фактического завершения дочернего пайплайна и отразил его статус (успех/неудача), используется `strategy: depend`. Это критически важно для построения последовательных цепочек пайплайнов.

```yaml
trigger_job:
  stage: trigger
  trigger:
    project: 'group/downstream-project' # или include
    strategy: depend # Родительский пайплайн будет ожидать завершения дочернего
```

#### Наследование переменных

* **Дочерние пайплайны (Child Pipelines)**:
  * Наследуют **все предопределенные переменные GitLab CI** (например, `CI_COMMIT_SHA`, `CI_COMMIT_REF_NAME`).
  * Наследуют **все пользовательские переменные**, определенные на уровне проекта, группы или в родительском `.gitlab-ci.yml`.
  * Наследуют переменные, определенные в запускающей задаче родительского пайплайна (внутри `variables:` блока этой задачи).

* **Мультипроектные пайплайны (Multi-project Pipelines)**:
  * **НЕ наследуют пользовательские переменные** из родительского пайплайна или из настроек проекта/группы родительского проекта.
  * Наследуют **только предопределенные переменные GitLab CI**, относящиеся к собственному проекту (например, `CI_PROJECT_PATH` дочернего проекта).
  * Для передачи пользовательских переменных их необходимо **явно указать** в блоке `variables:` триггерной задачи родительского пайплайна.

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

### Связанные документы

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые концепции.
- **[Механизм `include`](../Reusable_Pipelines/include_keyword.md)** — подключение внешних файлов.
- **[Продвинутые рабочие процессы](../Advanced/gitlab_ci_advanced_workflow.md)** — оптимизация пайплайнов.
