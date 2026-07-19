# Динамическая генерация дочерних пайплайнов

## Определения

**Динамическая генерация пайплайнов** — паттерн проектирования CI/CD, при котором конфигурация `.gitlab-ci.yml` создаётся программно во время выполнения родительского (upstream) пайплайна. Этот подход обеспечивает максимальную гибкость для монорепозиториев и сложных инфраструктурных сценариев.

## Основные концепции

### Принцип работы

Реализация динамических пайплайнов включает три ключевых этапа:

1. **Генерация:** специализированный скрипт (Python, Bash, Go) создаёт YAML-конфигурацию на основе текущих условий (изменения файлов, параметры окружения, результаты тестов).
2. **Артефакт:** сформированный файл сохраняется как рабочий артефакт текущей задачи.
3. **Триггер:** дочерний пайплайн запускается с использованием этого артефакта в качестве своей конфигурации через ключевое слово `trigger:include:artifact`.

### Лимиты и ограничения

- **Размер файла:** объём генерируемого YAML-файла ограничен **5 МБ**.
- **Отладка:** сгенерированные пайплайны сложнее диагностировать, так как их финальный вид доступен только в артефактах выполненной задачи. Рекомендуется логировать содержимое файла перед сохранением.
- **Циклическая зависимость:** динамический пайплайн не может запустить родительский пайплайн тем же способом без риска бесконечной рекурсии.
- **Валидация:** ошибки в синтаксисе генерируемого YAML приведут к сбою этапа `trigger`, а не этапа `generate`.

### Передача данных через Inputs (GitLab 17.11+)

Современный подход рекомендует использовать `spec:inputs` в генерируемом файле для обеспечения типизации.

```yaml
# Пример генерируемого блока в YAML
spec:
  inputs:
    environment:
      type: string
      default: "development"
---
deploy-job:
  script:
    - echo "Deploying to $[[ inputs.environment ]]"
```

## Практические сценарии

### Использование Python и Jinja2

Этот метод позволяет создавать масштабируемые структуры на основе шаблонов.

**1. Шаблон Jinja2 (`pipeline_template.j2`):**
```jinja
# generated-ci-config.yml
{% for i in range(num_jobs) %}
job_{{ i }}:
  stage: build
  script:
    - echo "Выполнение задачи {{ i }} для $[[ inputs.target_env ]]"
{% endfor %}
```

**2. Генератор (`generate_pipeline.py`):**
```python
from jinja2 import Template
import os

num_jobs = int(os.environ.get("NUM_GENERATED_JOBS", 3))
with open("pipeline_template.j2", "r") as f:
    template = Template(f.read())

generated_yaml = template.render(num_jobs=num_jobs)

# Добавляем спецификацию inputs программно
header = "spec:\n  inputs:\n    target_env:\n      default: 'dev'\n---\n"
with open("generated-ci-config.yml", "w") as f:
    f.write(header + generated_yaml)
```

**3. Родительский пайплайн (`.gitlab-ci.yml`):**
```yaml
generate-config:
  stage: build
  image: python:3.11-slim
  script:
    - pip install Jinja2
    - python generate_pipeline.py
  artifacts:
    paths:
      - generated-ci-config.yml

trigger-dynamic:
  stage: deploy
  trigger:
    include:
      - artifact: generated-ci-config.yml
        job: generate-config
    inputs:
      target_env: "production"
    strategy: mirror
```

### Генерация на основе изменённых файлов

Автоматическое создание пайплайна только для изменённых микросервисов в монорепозитории.

```yaml
generate-changes-config:
  stage: build
  script:
    - CHANGED_DIRS=$(git diff --name-only $CI_COMMIT_BEFORE_SHA...$CI_COMMIT_SHA | cut -d/ -f1 | sort -u)
    - python generate_from_changes.py "$CHANGED_DIRS"
  artifacts:
    paths:
      - generated-pipeline.yml

trigger-changes:
  stage: test
  trigger:
    include:
      - artifact: generated-pipeline.yml
        job: generate-changes-config
    strategy: mirror
```

## Дополнительная информация

### Сферы применения

- **Монорепозитории:** запуск CI/CD только для тех модулей, в которых реально произошли изменения.
- **Динамические матрицы:** формирование задач на основе внешних данных (например, список доступных регионов в облаке или активных версий API).
- **Сложная логика ветвления:** изменение структуры пайплайна в зависимости от метаданных коммита или внешних триггеров.

### Преимущества и риски

| Характеристика | Преимущество | Риск |
| :--- | :--- | :--- |
| **Гибкость** | Адаптация под любые условия "на лету" | Высокая сложность поддержки |
| **Объём кода** | Исключение дублирования в YAML | Зависимость от скриптов генерации |
| **Ресурсы** | Оптимизация за счёт запуска только нужных джоб | Трудности с визуализацией до запуска |

---

**Связанные документы:**
- [Определения](./definitions.md) — базовые понятия downstream-пайплайнов.
- [Лучшие практики](./best_practices.md) — рекомендации по безопасности и структуре.
- [Стратегии выполнения](./strategies.md) — использование `strategy: mirror`.
