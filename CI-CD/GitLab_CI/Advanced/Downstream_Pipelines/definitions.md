# Downstream Pipelines — Определения

## Определения

**Downstream pipeline** — любой пайплайн GitLab CI/CD, запущенный другим пайпайном. Выполняется независимо и параллельно с upstream-пайплайном.

**Два типа downstream pipelines:**

| Тип | Описание | Ограничения |
| :--- | :--- | :--- |
| **Parent-child pipeline** | Downstream в том же проекте | Макс. 2 уровня вложенности |
| **Multi-project pipeline** | Downstream в другом проекте | Без ограничений вложенности |

**Динамическая генерация пайплайнов** — паттерн, при котором конфигурация `.gitlab-ci.yml` создаётся во время выполнения родительского пайплайна. Обеспечивает высокую гибкость.

## Основные концепции

### Parent-child pipelines

**Характеристики:**

- Выполняются в том же проекте, ref и commit SHA
- Не отображаются в общем списке пайплайнов (только на странице родителя)
- Автоматически отменяются при настройке `interruptible`
- **Максимальная глубина: 2 уровня** child pipelines

### Multi-project pipelines

**Характеристики:**

- Запускаются из пайплайна другого проекта
- Upstream может выбрать ref downstream и передать переменные
- Отображаются в списке пайплайнов downstream-проекта
- **Нет ограничений на вложенность**

**Требования безопасности:**

- Пользователь должен иметь права на запуск пайплайнов в downstream-проекте
- При использовании публичного проекта для запуска private проверьте конфиденциальность

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

**Сценарии использования:**

- Управление зависимостями между микросервисами
- Разделение обязанностей и безопасности
- Централизация шаблонов и инфраструктуры
- Декомпозиция сложного `.gitlab-ci.yml`
- Монорепозитории

---

**Связанные документы:**

- [Parent-child Pipelines](./parent_child_pipelines.md)
- [Multi-project Pipelines](./multi_project_pipelines.md)
- [Стратегии выполнения](./strategies.md)
- [Динамическая генерация](./dynamic_generation.md)
- [Наследование переменных](./variable_inheritance.md)
- [Практические сценарии](./practical_scenarios.md)
- [Best Practices](./best_practices.md)
