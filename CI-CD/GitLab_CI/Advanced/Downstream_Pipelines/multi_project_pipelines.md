# Multi-project пайплайны

## Определения

**Multi-project pipeline** — downstream пайплайн, запускаемый в другом проекте GitLab. Обеспечивает координацию CI/CD между различными проектами.

## Основные концепции

### Характеристики

- Запускаются из пайплайна другого проекта
- Upstream может выбрать ref downstream и передать переменные
- Отображаются в списке пайплайнов downstream-проекта
- **Нет ограничений на вложенность** (в отличие от [parent-child](./parent_child_pipelines.md))
- Downstream выполняется в контексте downstream проекта

### Требования безопасности

- Пользователь должен иметь права на запуск пайплайнов в downstream-проекте
- При использовании публичного проекта для запуска private проверьте конфиденциальность
- Рекомендуется использовать Deploy Tokens с ограниченными правами

### Наследование переменных

Наследование переменных в multi-project pipelines имеет важные отличия от parent-child pipelines, особенно в части project/group и masked variables, которые не передаются автоматически.

Подробное описание механизма и всех правил находится в специальном документе: [Наследование переменных](./variable_inheritance.md).

## Практические сценарии

### С передачей переменных

```yaml
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

В дочернем пайплайне будут доступны `UPSTREAM_PIPELINE_ID` и `CUSTOM_MESSAGE`.

### С ожиданием завершения

```yaml
trigger_downstream:
  stage: deploy
  trigger:
    project: 'my-group/my-downstream-project'
    branch: main
    strategy: depend
```

`strategy: depend` заставляет родительский job ожидать завершения downstream pipeline. Подробнее: [Стратегии выполнения](./strategies.md).

## Дополнительная информация

### Варианты использования

- Управление зависимостями между микросервисами
- Вынесение конфиденциальной логики в отдельный проект
- Централизованные пайплайны для инфраструктуры
- CI/CD для монорепозиториев с несколькими проектами

---

**Связанные документы:**

- [Определения](./definitions.md)
- [Parent-child Pipelines](./parent_child_pipelines.md)
- [Рекомендации](./best_practices.md)
- [Стратегии выполнения](./strategies.md)
- [Наследование переменных](./variable_inheritance.md)
