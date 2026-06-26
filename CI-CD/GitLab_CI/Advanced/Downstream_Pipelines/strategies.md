# Стратегии выполнения downstream pipelines

## Определения

**Strategy** — параметр в триггере downstream pipeline, определяющий как родительский пайплайн взаимодействует с дочерним: синхронизирует статусы или отображает отчёты.

## Основные концепции

### Стратегия mirror

**Назначение:** Отображает статус downstream pipeline в trigger job.

**Поведение:**

- Parent job отображает реальный статус child pipeline
- При провале child pipeline — parent job также показывает failed
- При настройке auto-cancel — родительский пайплайн может быть отменён при провале child (см. [directives_definitions.md](../workflow_rules/directives_definitions.md))

**Применение:**

- [Parent-child](./parent_child_pipelines.md) и [multi-project](./multi_project_pipelines.md) pipelines
- Критичные зависимости, где статус downstream важен

```yaml
trigger_job:
  trigger:
    include:
      - local: path/to/child-pipeline.yml
    strategy: mirror
```

### Стратегия depend

**Назначение:** Отображает отчёты child pipeline в Merge Request виджетах.

**Поведение:**

- Parent job ждёт завершения child pipeline перед завершением
- Отчёты (JUnit, code quality, security) появляются в Merge Request
- Родительский пайплайн не завершается пока child выполняется

**Критично для:**

- Unit test отчётов (JUnit)
- Code quality отчётов
- Terraform отчётов
- Security отчётов (SAST, secret detection, container scanning, DAST)

```yaml
test-backend:
  trigger:
    include: backend-tests.yml
    strategy: depend

test-frontend:
  trigger:
    include: frontend-tests.yml
    strategy: depend
```

**Без `strategy: depend`:** родительский пайплайн завершается до окончания child pipelines, и их отчёты не появляются в Merge Request.

## Практические сценарии

### Комбинирование стратегий

```yaml
# Для зависимостей с отчётами
deploy-dependent:
  stage: deploy
  trigger:
    project: 'group/deploy-project'
    branch: main
    strategy: depend

# Для зависимостей со статусом
deploy-critical:
  stage: deploy
  trigger:
    project: 'group/critical-project'
    branch: main
    strategy: mirror
```

### Выбор стратегии

| Сценарий | Рекомендуемая стратегия |
| :--- | :--- |
| Нужны отчёты в MR | `strategy: depend` |
| Критичный downstream | `strategy: mirror` |
| Независимые parallel jobs | без strategy |
| Быстрый отказ при ошибке | `strategy: mirror` |

## Дополнительная информация

### Когда использовать каждую стратегию

- **`strategy: depend`:** Обязательно для тестов, сканирования безопасности, code quality
- **`strategy: mirror`:** Для критичных зависимостей, где важна синхронизация статусов
- **Без стратегии:** Параллельные независимые downstream pipelines

### Ограничения

- `strategy: depend` замедляет общий pipeline (ожидает завершения child)
- `strategy: mirror` требует внимания к order of execution

---

**Связанные документы:** [Определения](./definitions.md), [Лучшие практики](./best_practices.md), [Наследование переменных](./variable_inheritance.md).
