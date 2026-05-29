# Динамическая генерация child pipelines

## Определения

**Динамическая генерация пайплайнов** — паттерн, при котором конфигурация `.gitlab-ci.yml` создаётся во время выполнения родительского пайплайна. Обеспечивает высокую гибкость для монорепозиториев и сложных сценариев.

## Основные концепции

### Принцип работы

1. **Генерация:** Скрипт создаёт YAML-конфигурацию на основе условий
2. **Артефакт:** Сгенерированный файл сохраняется как артефакт
3. **Триггер:** Child pipeline использует артефакт как конфигурацию

### Ограничения

- Сложность отладки сгенерированных пайплайнов.
- Размер артефакта с конфигурацией ограничен настройками инстанса GitLab.
- Невозможность использования CI/CD-переменных в секции `include` для динамического дочернего пайплайна.
- Сгенерированный файл должен быть валидным YAML.

## Практические сценарии

### Пример с Python и Jinja2

**1. `pipeline_template.j2` (Шаблон Jinja2):**

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

**2. `generate_pipeline.py` (Python-скрипт):**

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

### Генерация на основе изменений

```yaml
generate-config:
  stage: build
  script:
    - |
      # Определение изменённых сервисов
      CHANGED_FILES=$(git diff --name-only $CI_COMMIT_BEFORE_SHA...$CI_COMMIT_SHA)
      echo "Changed files: $CHANGED_FILES"
      # Генерация конфигурации на основе изменений
      python generate_from_changes.py
  artifacts:
    paths:
      - generated-pipeline.yml

trigger-dynamic:
  stage: test
  trigger:
    include:
      - artifact: generated-pipeline.yml
        job: generate-config
```

## Дополнительная информация

### Варианты использования

- Монорепозитории: запуск только релевантных тестов
- Гибкое масштабирование: генерация множества однотипных заданий
- Конфигурация на основе данных: структура зависит от внешних данных
- Dynamic matrix: разные версии, окружения, конфигурации

### Преимущества

- Сложная логика выбора заданий
- Избегание дублирования кода
- Адаптивные пайплайны под изменения

---

**Связанные документы:**

- [Определения](./definitions.md)
- [Рекомендации](./best_practices.md)
- [Parent-child Pipelines](./parent_child_pipelines.md)
