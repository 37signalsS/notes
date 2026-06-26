# Наследование переменных в downstream-пайплайнах

## Определения

**Наследование переменных** — процесс передачи параметров и настроек из upstream (родительского) пайплайна в downstream (дочерний). Механизм и объем передаваемых данных зависят от типа связи: parent-child или multi-project.

## Основные концепции

### Сравнение механизмов наследования

| Тип переменных | Parent-child | Multi-project |
| :--- | :--- | :--- |
| **Предопределённые (CI_*)** | Наследуются полностью | Только относящиеся к дочернему проекту |
| **Переменные проекта/группы** | Наследуются полностью | **Не наследуются** |
| **Переменные из задачи** | Наследуются автоматически | **Только явно указанные** в `trigger:variables` |
| **Маскированные (Masked)** | Наследуются автоматически | **Не наследуются** (риск раскрытия) |

### Использование ключевого слова variables

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

- `ENVIRONMENT` доступен во всех задачах дочернего пайплайна
- `VERSION` наследуется как глобальная переменная по умолчанию

### Блокировка наследования

```yaml
trigger-job:
  inherit:
    variables: false  # Отключить наследование переменных по умолчанию
  variables:
    JOB_VAR: value
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

- Глобальные переменные не передаются в дочерний пайплайн
- Передаётся только `JOB_VAR`

### Интерполяция предопределённых переменных

```yaml
trigger-job:
  variables:
    PARENT_BRANCH: $CI_COMMIT_REF_NAME  # Сохранение контекста ветки
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

**Важно:** данный метод не следует использовать для маскированных переменных в multi-project пайплайнах, так как свойство маскирования при такой передаче теряется.

## Практические сценарии

### Использование ключевого слова inputs (GitLab 17+)

**Преимущества перед традиционными переменными:**

- Валидация типов данных
- Ограничение значений через `options`
- Наличие описаний и значений по умолчанию
- Повышенная безопасность (защита от инъекций)

**В дочернем пайплайне (`child-pipeline.yml`):**

```yaml
spec:
  inputs:
    environment:
      description: "Окружение для деплоя"
      options: [staging, production]
      default: staging
    version:
      type: string
      default: "1.0.0"
```

**Вызов из родительского пайплайна:**

```yaml
staging:
  trigger:
    include:
      - local: path/to/child-pipeline.yml
    inputs:
      environment: staging
      version: "1.1.0"
```

### Передача данных через dotenv-отчёты

Метод позволяет передавать динамически созданные переменные между независимыми проектами.

```yaml
# Upstream
build_vars:
  stage: build
  script:
    - echo "BUILD_VERSION=1.2.3" >> build.env
  artifacts:
    reports:
      dotenv: build.env

deploy:
  stage: deploy
  trigger: my/downstream_project

# Downstream (требует Premium/Ultimate)
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

## Дополнительная информация

### Миграция с variables на inputs

| Свойство | Variables | Inputs |
| :--- | :--- | :--- |
| Синтаксис | `$VARIABLE_NAME` | `$[[ inputs.VARIABLE_NAME ]]` |
| Валидация | Отсутствует | Строгая типизация |
| Ограничения | Невозможны | Список `options` |
| Безопасность | Может быть переопределена | Защищено от изменений |

### Рекомендации

Полный список советов по безопасной и эффективной передаче переменных доступен в разделе **[лучшие практики](./best_practices.md)**.

---

**Связанные документы:** [Определения](./definitions.md), [Лучшие практики](./best_practices.md), [Стратегии выполнения](./strategies.md).
