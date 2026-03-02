# Multi-project Pipelines

## Определения

**Multi-project pipeline** — downstream пайплайн, запускаемый в другом проекте GitLab. Обеспечивает координацию CI/CD между различными проектами.

## Основные концепции

### Характеристики

- Запускаются из пайплайна другого проекта
- Upstream может выбрать ref downstream и передать переменные
- Отображаются в списке пайплайнов downstream-проекта
- **Нет ограничений на вложенность** (в отличие от parent-child)
- Downstream выполняется в контексте downstream проекта

### Требования безопасности

- Пользователь должен иметь права на запуск пайплайнов в downstream-проекте
- При использовании публичного проекта для запуска private проверьте конфиденциальность
- Рекомендуется использовать Deploy Tokens с ограниченными правами

### Переменные

| Тип переменных | Child Pipelines | Multi-project Pipelines |
| :--- | :--- | :--- |
| **Predefined (CI_*)** | Наследуют все | Наследуют только относящиеся к downstream проекту |
| **Project/Group variables** | Наследуют все | **НЕ наследуют** |
| **Variables из задачи** | Наследуют | **Только явно указанные** в `trigger:variables` |
| **Masked variables** | Наследуют | **НЕ наследуют** (риск unmask!) |

## Практические сценарии

### Базовый триггер

```yaml
trigger_downstream:
  stage: deploy
  trigger:
    project: 'group/downstream-project'
    branch: main
```

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

### С ожиданием завершения

```yaml
trigger_downstream:
  stage: deploy
  trigger:
    project: 'my-group/my-downstream-project'
    branch: main
    strategy: depend
```

## Дополнительная информация

### Варианты использования

- Управление зависимостями между микросервисами
- Вынесение конфиденциальной логики в отдельный проект
- Централизованные пайплайны для инфраструктуры
- CI/CD для монорепозиториев с несколькими проектами

### Ограничения

- Нельзя передать masked variables
- Project/Group variables не наследуются
- Требуются права на запуск в downstream проекте

---

**Связанные документы:**

- [Определения](./definitions.md)
- [Стратегии выполнения](./strategies.md)
- [Наследование переменных](./variable_inheritance.md)
- [Практические сценарии](./practical_scenarios.md)
