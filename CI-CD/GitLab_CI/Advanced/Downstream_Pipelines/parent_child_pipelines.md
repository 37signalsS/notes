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

### Динамическая генерация с переменными

```yaml
# Родительский пайплайн
generate-config:
  stage: build
  script:
    - python generate_ci_config.py > generated-config.yml
  artifacts:
    paths:
      - generated-config.yml

child-pipeline:
  stage: test
  trigger:
    include:
      - artifact: generated-config.yml
        job: generate-config
```

## Дополнительная информация

### Варианты использования

- Декомпозиция монолитного `.gitlab-ci.yml` на логические блоки
- Изоляция expensive jobs в отдельный pipeline
- Улучшение читаемости конфигурации
- Повторное использование через `include`

### Ограничения динамических child pipelines

- Артефакт должен быть в пределах лимитов инстанса
- Нельзя использовать CI/CD переменные в `include` секции динамического child pipeline
- Нельзя передать все типы переменных

---

**Связанные документы:**

- [Определения](./definitions.md)
- [Стратегии выполнения](./strategies.md)
- [Наследование переменных](./variable_inheritance.md)
