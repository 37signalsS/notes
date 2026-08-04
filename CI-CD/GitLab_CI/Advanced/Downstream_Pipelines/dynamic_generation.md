# Динамическая генерация дочерних пайплайнов

## Определения

**Динамическая генерация пайплайнов** — паттерн проектирования, при котором конфигурация `.gitlab-ci.yml` создаётся программно во время выполнения родительского задания (upstream). GitLab считывает сгенерированный артефакт в момент запуска задачи-триггера, парсит его как полноценный пайплайн и интегрирует его жизненный цикл в родительский граф.

## Основные концепции

### Принцип работы и жизненный цикл

1. **Генерация:** Скрипт (Python, Go, Bash) формирует YAML-структуру. Важно: использование **`spec:inputs`** в генерируемом файле является стандартом безопасности, так как это предотвращает **YAML Injection** (инъекцию кода через несанкционированную конкатенацию строк).
2. **Артефакт:** Файл должен быть сохранен в родительской задаче с использованием `artifacts:paths`.
3. **Триггер:** Задача с ключевым словом `trigger:include:artifact` указывает на этот файл. GitLab инициирует создание дочернего пайплайна только после успешного завершения задачи-генератора.

### Технические лимиты и ограничения

- **Размер файла:** Объём сгенерированного YAML (после раскрытия всех внутренних `include`) ограничен **5 МБ**.
- **Глубина рекурсии:** GitLab ограничивает вложенность динамических пайплайнов **2 уровнями** (Parent -> Dynamic Child -> Grandchild). Попытка запустить 3-й уровень приведет к ошибке.
- **Reporting (18.9+):** Динамические пайплайны полностью поддерживают агрегацию Security Reports (SAST, DAST, SBOM) в родительский Merge Request при использовании `strategy: mirror`.
- **Валидация:** Синтаксические ошибки в сгенерированном файле не останавливают задачу-генератор, но приводят к падению задачи-триггера со статусом `Downstream pipeline could not be created`.

### Безопасная передача данных через Inputs

Вместо динамической вставки переменных в текст YAML-файла (риск инъекции), генерируйте статическую структуру с блоком `spec:inputs` и передавайте данные через триггер.

```yaml
# Пример генерируемого шаблона (secure-template.yml)
spec:
  inputs:
    db_name:
      type: string
---
cleanup-job:
  script:
    - dropdb $[[ inputs.db_name ]]
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

### Динамическая генерация матриц (Dynamic Matrices)

Сценарий для создания матриц на основе внешних данных (например, списка регионов облачного провайдера).

```yaml
# generate_matrix.py
import json
# В реальности данные приходят из API облака
regions = ["us-east-1", "eu-central-1", "ap-southeast-1"]
pipeline = {
    "deploy-matrix": {
        "parallel": {
            "matrix": [{"REGION": regions}]
        },
        "script": ["./deploy.sh $REGION"]
    }
}
print(json.dumps(pipeline))
```

## Дополнительная информация

### Безопасность и YAML Injection

При генерации YAML из строк (особенно Bash) существует риск инъекции команд.
**Опасный код:** `f"job: {user_input}"` — если `user_input` содержит `\n  script: [rm -rf /]`, это изменит структуру пайплайна.
**Рекомендация:** Всегда используйте библиотеки-сериализаторы (PyYAML, json.dumps) и передавайте пользовательские данные через `spec:inputs`.

### Отладка динамических пайплайнов

1.  **Логирование:** Всегда выводите итоговый YAML в `stdout` задачи-генератора.
2.  **Инспекция артефактов:** Если триггер падает, скачайте артефакт через API или UI, чтобы увидеть финальный вид файла.
3.  **CI Lint:** Скопируйте содержимое сгенерированного файла в **CI Lint** (Project > Build > Pipeline editor > CI Lint), чтобы проверить его на соответствие схеме GitLab.

### Преимущества и риски

| Характеристика | Преимущество | Риск |
| :--- | :--- | :--- |
| **Гибкость** | Адаптация под любые условия "на лету" | Высокая сложность поддержки |
| **Объём кода** | Исключение дублирования в YAML | Зависимость от скриптов генерации |
| **Ресурсы** | Оптимизация (запуск только нужных джоб) | **Deadlock** при синхронных стратегиях |

---

**Связанные документы:**
- **[Определения](./definitions.md)** — базовые понятия и терминология.
- **[Лучшие практики](./best_practices.md)** — безопасность и оптимизация триггеров.
- **[Стратегии выполнения](./strategies.md)** — детально про `mirror` и `depend`.

---

**Надёжность:** 10 (SSoT + Документация GitLab 17.x–19.x)
**Свежесть:** GitLab 19.2 (2026)
**Триггеры обновления:** Изменение лимитов размера артефактов (5МБ), новые типы агрегации отчетов, изменения в парсере YAML.
