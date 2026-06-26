# Динамическая генерация дочерних пайплайнов

## Определения

**Динамическая генерация пайплайнов** — паттерн проектирования CI/CD, при котором конфигурация `.gitlab-ci.yml` создаётся программно во время выполнения родительского (upstream) пайплайна. Этот подход обеспечивает максимальную гибкость для монорепозиториев и сложных инфраструктурных сценариев.

## Основные концепции

### Принцип работы

Процесс реализации динамических пайплайнов включает три этапа:

- **Генерация:** специализированный скрипт (Python, Bash, Go) создаёт YAML-конфигурацию на основе текущих условий (изменения файлов, параметры окружения)
- **Артефакт:** сформированный файл сохраняется как рабочий артефакт текущей задачи
- **Триггер:** дочерний пайплайн запускается с использованием этого артефакта в качестве своей конфигурации

### Ограничения и особенности

- **Отладка:** сгенерированные пайплайны сложнее диагностировать, так как их код отсутствует в репозитории до момента запуска
- **Размер файла:** на объём генерируемого YAML-файла могут накладываться ограничения инстанса GitLab (обычно до 5 МБ)
- **Переменные в include:** невозможно использовать CI/CD-переменные внутри секции `include` для динамического пайплайна
- **Валидация:** генерируемый файл должен строго соответствовать синтаксису YAML и правилам GitLab CI

## Практические сценарии

### Использование Python и Jinja2

Этот метод позволяет создавать сложные структуры пайплайнов на основе шаблонов.

**1. Шаблон Jinja2 (`pipeline_template.j2`):**

```jinja
# generated_pipeline.yml
{% for i in range(num_jobs) %}
job_{{ i }}:
  stage: build
  script:
    - echo "Выполнение задачи {{ i }}"
  tags:
    - docker
{% endfor %}
```

**2. Генератор (`generate_pipeline.py`):**

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

**3. Родительский пайплайн (`.gitlab-ci.yml`):**

```yaml
stages:
  - generate
  - build

generate-config:
  stage: generate
  image: python:3.11-slim
  variables:
    NUM_GENERATED_JOBS: 5
  script:
    - pip install Jinja2
    - python generate_pipeline.py
  artifacts:
    paths:
      - generated-ci-config.yml

run-pipeline:
  stage: build
  trigger:
    include:
      - artifact: generated-ci-config.yml
        job: generate-config
    strategy: depend
```

### Генерация на основе изменённых файлов

Автоматическое создание пайплайна только для изменённых компонентов монорепозитория.

```yaml
generate-changes-config:
  stage: build
  script:
    - CHANGED_FILES=$(git diff --name-only $CI_COMMIT_BEFORE_SHA...$CI_COMMIT_SHA)
    - python generate_from_changes.py "$CHANGED_FILES"
  artifacts:
    paths:
      - generated-pipeline.yml

trigger-changes:
  stage: test
  trigger:
    include:
      - artifact: generated-pipeline.yml
        job: generate-changes-config
```

## Дополнительная информация

### Сферы применения

- **Монорепозитории:** запуск тестов и сборки только для затронутых сервисов
- **Масштабируемые системы:** создание однотипных задач для множества окружений или регионов
- **Адаптивные пайплайны:** изменение структуры CI/CD в зависимости от входных данных или результатов предыдущих стадий
- **Динамические матрицы:** формирование сложных комбинаций версий и параметров

### Преимущества подхода

- Исключение дублирования кода в конфигурационных файлах
- Автоматическая адаптация CI/CD под изменения в архитектуре проекта
- Возможность реализации сложной бизнес-логики в процессе доставки кода

---

**Связанные документы:** [Определения](./definitions.md), [Лучшие практики](./best_practices.md), [Parent-child Pipelines](./parent_child_pipelines.md).
