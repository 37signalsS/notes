# Практические сценарии использования downstream pipelines

## Определения

**Практические сценарии** — типовые примеры использования parent-child и multi-project pipelines для реальных задач CI/CD.

## Основные концепции

### Основные варианты использования

1. **Управление зависимостями между микросервисами**
   - Автоматический запуск пересборки и тестирования микросервисов после обновления общих библиотек

2. **Разделение обязанностей и безопасности**
   - Вынесение конфиденциальной логики (деплой в продакшн, сканирование безопасности) в отдельный проект с ограниченным доступом

3. **Централизация шаблонов и инфраструктуры**
   - Общие пайплайны для сборки/деплоя в центральном репозитории

4. **Декомпозиция сложного `.gitlab-ci.yml`**
   - Разбивка на логически сгруппированные части

5. **Монорепозитории**
   - Запуск CI/CD только для затронутых частей

## Практические сценарии

### 1. Передача переменных в мультипроектный пайплайн

```yaml
# .gitlab-ci.yml в родительском проекте
trigger_downstream_build:
  stage: deploy
  trigger:
    project: 'my-group/my-downstream-project'
    branch: main
    strategy: depend
  variables:
    UPSTREAM_PIPELINE_ID: $CI_PIPELINE_ID
    CUSTOM_MESSAGE: "Hello from upstream!"
```

В дочернем пайплайне `my-downstream-project` будут доступны `UPSTREAM_PIPELINE_ID` и `CUSTOM_MESSAGE`.

### 2. Запуск мультипроектного пайплайна

**Проект A (запускающий): `.gitlab-ci.yml`**

```yaml
trigger_downstream_build:
  stage: deploy
  trigger:
    project: 'my-group/my-downstream-project'
    branch: main
    strategy: depend
```

### 3. Динамическая генерация пайплайнов с Python и Jinja2

**Принцип работы:** Скрипт генерирует `.gitlab-ci.yml` на основе условий.

**1. `pipeline_template.j2`:**

```jinja
{% for i in range(num_jobs) %}
job_{{ i }}:
  stage: build
  script:
    - echo "Running job {{ i }}"
  tags:
    - shell
{% endfor %}
```

**2. `generate_pipeline.py`:**

```python
from jinja2 import Template
import os

num_jobs = int(os.environ.get("NUM_GENERATED_JOBS", 3))

with open("pipeline_template.j2", "r") as f:
    template_content = f.read()

template = Template(template_content)
generated_yaml = template.render(num_jobs=num_jobs)

with open("generated-ci-config.yml", "w") as f:
    f.write(generated_yaml)
```

**3. `.gitlab-ci.yml`:**

```yaml
stages:
  - generate
  - build

generate-dynamic-config:
  stage: generate
  image: python:3.9-slim
  variables:
    NUM_GENERATED_JOBS: 5
  script:
    - pip install Jinja2
    - python generate_pipeline.py
  artifacts:
    paths:
      - generated-ci-config.yml

run-generated-pipeline:
  stage: build
  trigger:
    include:
      - artifact: generated-ci-config.yml
        job: generate-dynamic-config
    strategy: depend
```

### 4. Pipeline для монорепозитория

```yaml
detect-changes:
  stage: .pre
  script:
    - |
      CHANGED=$(git diff --name-only $CI_MERGE_REQUEST_DIFF_BASE_SHA...$CI_COMMIT_SHA)
      echo "CHANGED_FILES=$CHANGED" >> variables.env
  artifacts:
    reports:
      dotenv: variables.env

build-frontend:
  stage: build
  only:
    variables:
      - $CHANGED_FILES =~ "frontend/"
  script:
    - cd frontend && npm install && npm run build

build-backend:
  stage: build
  only:
    variables:
      - $CHANGED_FILES =~ "backend/"
  script:
    - cd backend && make build
```

## Дополнительная информация

### Полезность динамической генерации

- **Сложная логика выбора заданий:** Идеально для монорепозиториев
- **Гибкое масштабирование:** Генерация множества однотипных заданий
- **Конфигурация на основе данных:** Структура зависит от внешних данных

### Когда использовать

- Много повторяющегося кода в .gitlab-ci.yml
- Разные конфигурации для разных веток/тегов
- Condition-based job generation

---

**Связанные документы:**

- [Динамическая генерация](./dynamic_generation.md)
- [Наследование переменных](./variable_inheritance.md)
- [Best Practices](./best_practices.md)
