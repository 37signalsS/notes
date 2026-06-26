# Определения Downstream-пайплайнов

## Определения

**Downstream pipeline** — любой пайплайн GitLab CI/CD, запущенный другим пайплайном (upstream). Выполняется независимо и параллельно с upstream-пайплайном.

**Upstream pipeline** — родительский пайплайн, запускающий downstream.

## Основные концепции

### Типы downstream-пайплайнов

| Тип | Описание | Ограничения | Подробно |
| :--- | :--- | :--- | :--- |
| **[Parent-child pipeline](./parent_child_pipelines.md)** | Downstream в том же проекте, ref и commit SHA | Макс. 2 уровня вложенности | [Parent-child Pipelines](./parent_child_pipelines.md) |
| **[Multi-project pipeline](./multi_project_pipelines.md)** | Downstream в другом проекте | Без ограничений вложенности | [Multi-project Pipelines](./multi_project_pipelines.md) |

### Динамическая генерация

**Динамическая генерация пайплайнов** — паттерн, при котором конфигурация `.gitlab-ci.yml` создаётся во время выполнения родительского пайплайна. Обеспечивает высокую гибкость для монорепозиториев и сложных сценариев. Подробнее: [Динамическая генерация](./dynamic_generation.md).

## Практические сценарии

### Базовый триггер parent-child

```yaml
# Родительский .gitlab-ci.yml
child-pipeline:
  stage: test
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

### Базовый триггер multi-project

```yaml
trigger_downstream:
  stage: deploy
  trigger:
    project: 'group/downstream-project'
    branch: main
```

## Дополнительная информация

### Сценарии использования

- **Управление зависимостями между микросервисами** — автоматический запуск пересборки после обновления общих библиотек
- **Разделение обязанностей и безопасности** — вынесение конфиденциальной логики в отдельный проект
- **Централизация шаблонов и инфраструктуры** — общие пайплайны для сборки/деплоя
- **Декомпозиция сложного `.gitlab-ci.yml`** — разбивка на логически сгруппированные части
- **Монорепозитории** — запуск CI/CD только для затронутых изменений

---

**Связанные документы:** [Лучшие практики](./best_practices.md), [Стратегии выполнения](./strategies.md), [Наследование переменных](./variable_inheritance.md).
