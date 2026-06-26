# Практические сценарии использования downstream-пайплайнов

## Определения

**Практические сценарии** — типовые примеры реализации механизмов parent-child и multi-project для решения прикладных задач автоматизации CI/CD.

## Основные концепции

Использование downstream-пайплайнов позволяет разделить сложную логику на независимые части. Выбор конкретного сценария зависит от структуры репозитория (монорепозиторий или мультирепозиторий) и необходимости динамического изменения состава задач. Ключевыми факторами являются изоляция окружений, управление зависимостями и оптимизация времени выполнения за счёт запуска только необходимых проверок.

## Практические сценарии

### Передача переменных в multi-project пайплайны

Для передачи контекста между проектами используются переменные в блоке `trigger:variables`. Это необходимо для информирования дочернего проекта о деталях сборки в родительском репозитории.

```yaml
trigger_downstream_build:
  stage: deploy
  trigger:
    project: 'my-group/my-downstream-project'
    branch: main
    strategy: depend
  variables:
    UPSTREAM_PIPELINE_ID: $CI_PIPELINE_ID
    CUSTOM_MESSAGE: "Привет из upstream-пайплайна"
```

Подробные правила передачи данных описаны в разделе **[Наследование переменных](./variable_inheritance.md)**.

### Оптимизация для монорепозиториев

Паттерн для запуска задач только для изменённых компонентов. Использование `dotenv` артефактов позволяет передать список изменений между стадиями родительского пайплайна.

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
  rules:
    - if: $CHANGED_FILES =~ /frontend/
  script:
    - cd frontend && npm install && npm run build

build-backend:
  stage: build
  rules:
    - if: $CHANGED_FILES =~ /backend/
  script:
    - cd backend && make build
```

### Динамическая генерация конфигураций

Применяется в сценариях, где структура пайплайна заранее неизвестна и зависит от внешних условий или содержимого репозитория.

Полный пример реализации с использованием Python и Jinja2 доступен в документе **[Динамическая генерация](./dynamic_generation.md)**.

## Дополнительная информация

---

**Связанные документы:** [Определения](./definitions.md), [Лучшие практики](./best_practices.md), [Стратегии выполнения](./strategies.md).
