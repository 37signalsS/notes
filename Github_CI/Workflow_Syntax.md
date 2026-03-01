# GitHub Actions: Синтаксис Workflow

Файлы workflow в GitHub Actions используют синтаксис YAML и имеют специальную структуру с набором ключей верхнего уровня, контекстов и выражений для управления автоматизированными процессами.

## Определения

- **Workflow-файл**: YAML-файл (с расширением `.yml` или `.yaml`), расположенный в директории `.github/workflows/` репозитория.
- **Синтаксис выражений (`${{...}}`)**: Специальный синтаксис, который позволяет использовать контекстную информацию, выполнять условную логику и работать с переменными.

## Основные концепции

### Ключи верхнего уровня

Это основные блоки, из которых строится workflow:

- **`name`** (опционально): Имя рабочего процесса, которое отображается в UI GitHub.
  ```yaml
  name: CI Pipeline
  ```
- **`on`** (обязательно): Определяет [события (events)](./Events_Jobs_Steps.md), которые запускают workflow. Может быть строкой, списком событий или сложной структурой с фильтрами.
  ```yaml
  on: [push, pull_request]
  # или
  on:
    push:
      branches: [ main ]
      paths: [ 'src/**' ]
  ```
- **`jobs`** (обязательно): Содержит одну или несколько [задач (jobs)](./Events_Jobs_Steps.md), которые нужно выполнить.
- **`env`** (опционально): Позволяет определить переменные окружения, доступные для всех задач и шагов в workflow.
  ```yaml
  env:
    PROJECT_NAME: "My App"
  ```
- **`permissions`** (опционально): Управляет правами доступа, которые предоставляются `GITHUB_TOKEN`. Рекомендуется задавать минимально необходимые права для повышения безопасности.
  ```yaml
  permissions:
    contents: read
    packages: write
  ```
- **`concurrency`** (опционально): Предотвращает одновременный запуск нескольких экземпляров workflow, позволяя отменять устаревшие запуски. Это полезно для экономии ресурсов, особенно в pull requests.
  ```yaml
  concurrency:
    # Группа, в рамках которой запуски будут считаться одновременными
    group: ${{ github.workflow }}-${{ github.ref }}
    # Отменять ли уже идущий запуск в той же группе
    cancel-in-progress: true
  ```

### Контексты

Контексты — это наборы переменных, которые доступны в большинстве частей workflow. К ним обращаются через синтаксис выражений.

- **`github`**: Информация о запуске workflow (имя репозитория, хеш коммита, данные о событии).
- **`secrets`**: Доступ к секретам, настроенным в репозитории или организации.
- **`env`**: Доступ к переменным окружения.
- **`steps`**: Доступ к `outputs` (выходным данным) предыдущих шагов в рамках одной задачи.
- **`matrix`**: Содержит значения текущей комбинации в [матричной сборке](./Matrix_Builds.md).
- **`inputs`**: Доступ к входным параметрам в [переиспользуемых воркфлоу](./Reusable_Workflows.md).

## Практический сценарий: Демонстрация синтаксиса

Этот пример показывает использование большинства ключевых элементов синтаксиса.

```yaml
name: Syntax Demo

on:
  push:
    branches: [ main ]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-demo-${{ github.ref }}
  cancel-in-progress: true

env:
  PROJECT_NAME: "My Awesome App"

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Use global env
        run: echo "Building ${{ env.PROJECT_NAME }}..."

      - name: Use github context
        if: github.event_name == 'push'
        run: echo "This step runs only on push events."
        
      - name: Set output
        id: my-step
        run: echo "output_value=hello" >> $GITHUB_OUTPUT

      - name: Use step context
        run: echo "The output was ${{ steps.my-step.outputs.output_value }}"
```

## Дополнительная информация

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)**: Общее описание платформы.
- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)**: Концептуальное описание `on`, `jobs` и `steps`.
- **[Оптимизация воркфлоу](./Optimization.md)**: Как `concurrency` помогает в оптимизации.
- **Официальная документация**: [Workflow syntax for GitHub Actions](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)
