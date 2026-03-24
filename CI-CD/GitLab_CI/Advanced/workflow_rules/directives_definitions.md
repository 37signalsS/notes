# Определения ключевых директив GitLab CI/CD

## Определения

- **`workflow:rules`**: Глобальное правило, контролирующее создание всего пайплайна. Если ни одно правило не выполнено — пайплайн не запускается. Заменяет устаревшие `only/except` на уровне пайплайна.
- **`rules`**: Механизм для определения условий включения **отдельной задачи** в пайплайн. Правила проверяются по порядку, первое совпадение определяет поведение задачи. Подробно: [Правила запуска задач](./job_rules.md).
- **`needs`**: Директива для создания **направленного ациклического графа (DAG)**. Позволяет запускать задачи сразу после завершения зависимостей, не дожидаясь окончания всей стадии. Подробно: [DAG с `needs`](./dag_with_needs.md).
- **`parallel:matrix`**: Директива для запуска одного задания несколько раз с разными комбинациями переменных. Используется для тестирования на разных версиях ПО, архитектурах или окружениях. Подробно: [матричные сборки](./practical_scenarios.md).
- **`resource_group`**: Гарантирует, что одновременно выполняется только одна задача для определенной группы ресурсов. Предотвращает гонки состояний при деплое. Подробно: [сериализация развертываний](./practical_scenarios.md).

## Основные концепции

### Стратегии запуска и `workflow:rules`

GitLab CI/CD поддерживает различные события для запуска пайплайнов. Ключевая проблема — **дублирование пайплайнов**: один запускается для ветки после `push`, второй — для Merge Request из той же ветки.

**Решение:** использование `workflow:rules` для контроля создания пайплайна.

**Рекомендуемая конфигурация workflow:**

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

**Auto-cancel пайплайнов** — автоматическая отмена старых пайплайнов при новых коммитах:

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

**Динамические переменные на уровне пайплайна:**

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

**Pipeline inputs (GitLab 17+)** — типизированные параметры для передачи данных в пайплайн:

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

**Ограничения:**

- `workflow:rules` не поддерживает `start_in`, `allow_failure`, `needs`
- `changes` не работает для `workflow:rules` (только для `job:rules`)
