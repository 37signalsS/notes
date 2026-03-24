# Parent-child Pipelines

## Определения

**Parent-child pipeline** — downstream пайплайн, выполняемый в том же проекте, что и родительский. Используется для декомпозиции сложных конфигураций `.gitlab-ci.yml`.

## Основные концепции

### Характеристики

- Выполняются в том же проекте, ref и commit SHA
- Не отображаются в общем списке пайплайнов (только на странице родителя)
- Автоматически отменяются при настройке `interruptible`
- **Максимальная глубина: 2 уровня** child pipelines
- Общий раннер между parent и child
- Общие настройки: runner, tags, variables (с ограничениями)

### Ограничения

- Максимум 2 уровня вложенности
- Child pipeline не отображается в общем списке pipeline проекта
- Нельзя запустить child pipeline вручную
- Все jobs должны использовать тот же ref и commit SHA, что и parent

## Практические сценарии

### Базовый пример

```yaml
# Родительский .gitlab-ci.yml
stages:
  - test
  - deploy

child-pipeline:
  stage: test
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

### Child pipeline конфигурация

```yaml
# path/to/child-pipeline.yml
stages:
  - test

run_tests:
  stage: test
  script:
    - npm install
    - npm test
  tags:
    - docker
```

### Динамическая генерация

Генерация конфигурации child pipeline во время выполнения родительского пайплайна. Используется для монорепозиториев и сложных сценариев.

Подробный пример с Python и Jinja2: [Динамическая генерация](./dynamic_generation.md).

## Дополнительная информация

### Варианты использования

- Декомпозиция монолитного `.gitlab-ci.yml` на логические блоки
- Изоляция expensive jobs в отдельный pipeline
- Улучшение читаемости конфигурации
- Повторное использование через `include`
