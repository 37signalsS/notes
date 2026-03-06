# workflow:rules и Pipeline Inputs

## Определения → Основные концепции

### Стратегии запуска и `workflow:rules`

GitLab CI/CD поддерживает различные события для запуска пайплайнов. Ключевая проблема — **дублирование пайплайнов**: один запускается для ветки после `push`, второй — для Merge Request из той же ветки.

**Решение:** использование `workflow:rules` для контроля создания пайплайна.

#### Рекомендуемая конфигурация workflow

```yaml
workflow:
  rules:
    # Всегда запускать для Merge Request
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    # Всегда запускать для default branch
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    # Не запускать для push, если есть открытый MR
    - if: '$CI_OPEN_MERGE_REQUESTS'
      when: never
    # Запускать для всех остальных веток
    - if: '$CI_COMMIT_BRANCH'
```

**Порядок правил критичен:** более специфичные правила должны идти перед общими.

#### Auto-cancel пайплайнов

Для автоматической отмены старых пайплайнов при новых коммитах:

```yaml
workflow:
  auto_cancel:
    on_new_commit: interruptible  # Прерывать текущие пайплайны
    on_job_failure: all           # Отменять при провале задачи
  rules:
    - if: '$CI_COMMIT_REF_PROTECTED == "true"'
      auto_cancel:
        on_new_commit: none       # Не отменять для защищённых веток
        on_job_failure: none
    - when: always
```

#### Динамические переменные на уровне пайплайна

```yaml
workflow:
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      variables:
        DEPLOY_ENV: "production"
        ENABLE_FULL_TESTS: "true"
    - if: '$CI_COMMIT_BRANCH =~ /^feature/'
      variables:
        DEPLOY_ENV: "staging"
        ENABLE_FULL_TESTS: "false"
```

#### Pipeline inputs (GitLab 17+)

Начиная с GitLab 17, доступна возможность использования **pipeline inputs** — типизированных параметров для передачи данных в пайплайн:

```yaml
# .gitlab-ci.yml
spec:
  inputs:
    environment:
      description: "Окружение для деплоя"
      options:
        - staging
        - production
      default: staging
    version:
      description: "Версия приложения"
      type: string
      default: "latest"

deploy_job:
  stage: deploy
  script:
    - echo "Deploying version $[[ inputs.version ]] to $[[ inputs.environment ]]"
  rules:
    - if: '$[[ inputs.environment ]] == "production"'
      when: manual
```

**Преимущества перед переменными:**

- Валидация типов данных
- Проверка допустимых значений (`options`)
- Явное описание ожидаемых параметров
- Безопасность (защита от инъекций)

### Ограничения

- **`workflow:rules`** не поддерживает `start_in`, `allow_failure`, `needs`
- **`changes`** не работает для `workflow:rules` (только для `job:rules`)

## Связанные документы

- **[Определения директив](./directives_definitions.md)** — ключевые директивы GitLab CI/CD
- **[Правила запуска задач](./job_rules.md)** — условия для отдельных задач
- **[Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md)** — базовые концепции Pipeline, Stage, Job
