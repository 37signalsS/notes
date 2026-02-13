# GitHub Actions: Синтаксис Workflow

Файлы workflow в GitHub Actions используют синтаксис YAML и имеют специальную структуру с набором ключей верхнего уровня, контекстов и выражений.

## Определения

- **Workflow-файл**: YAML-файл (с расширением `.yml` или `.yaml`), расположенный в директории `.github/workflows/` репозитория. Он определяет автоматизированный процесс (`workflow`).
- **Синтаксис выражений (`${{...}}`)**: Специальный синтаксис, который позволяет использовать контекстную информацию, выполнять условную логику и работать с переменными внутри workflow-файла.

## Основные концепции

### Структура и размещение

- **Расположение**: Все workflow-файлы должны находиться в директории `.github/workflows/`.
- **Формат**: Используется YAML. Отступы имеют значение (используйте пробелы, а не табы).

### Ключи верхнего уровня

Это основные блоки, из которых строится workflow:

- `name`: (Опционально) Имя рабочего процесса, которое отображается в UI GitHub.
- `on`: (Обязательно) Определяет [события (events)](./Events_Jobs_Steps.md), которые запускают workflow.
- `jobs`: (Обязательно) Содержит одну или несколько [задач (jobs)](./Events_Jobs_Steps.md), которые нужно выполнить.
- `env`: (Опционально) Позволяет определить переменные окружения, доступные для всех задач в workflow.
- `permissions`: (Опционально) Управляет правами доступа, которые предоставляются `GITHUB_TOKEN`. Рекомендуется задавать минимально необходимые права.
- `concurrency`: (Опционально) Предотвращает одновременный запуск нескольких экземпляров workflow, позволяя отменять устаревшие запуски.

### Контексты

Контексты — это наборы переменных, которые доступны в большинстве частей workflow. К ним обращаются через синтаксис выражений.

- `github`: Информация о запуске workflow (имя репозитория, хеш коммита, имя ветки, данные о событии и т.д.).
- `secrets`: Доступ к секретам, настроенным в репозитории или организации.
- `env`: Доступ к переменным окружения (глобальным, на уровне задачи или шага).
- `steps`: Доступ к `outputs` (выходным данным) предыдущих шагов в рамках одной задачи.
- `matrix`: Содержит значения текущей комбинации в [матричной сборке](./Matrix_Builds.md).

## Практический сценарий: Демонстрация синтаксиса

Этот пример показывает использование большинства ключевых элементов синтаксиса.

```yaml
# Ключ 'name': Имя workflow
name: Syntax Demo

# Ключ 'on': запуск на push в main или по кнопке
on:
  push:
    branches: [ main ]
  workflow_dispatch:

# Ключ 'permissions': Ограничиваем права токена
permissions:
  contents: read

# Ключ 'concurrency': отменяем предыдущие запуски для этой ветки
concurrency:
  group: ci-demo-${{ github.ref }}
  cancel-in-progress: true

# Ключ 'env': глобальная переменная
env:
  PROJECT_NAME: "My Awesome App"

# Ключ 'jobs': секция с задачами
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Use global env
        # Используем выражение и контекст env
        run: echo "Building ${{ env.PROJECT_NAME }}..."

      - name: Use github context
        # Используем условное выполнение и контекст github
        if: github.event_name == 'push'
        run: echo "This step runs only on push events."
        
      - name: Set output
        id: my-step
        run: echo "output_value=hello" >> $GITHUB_OUTPUT

      - name: Use step context
        # Используем контекст steps для доступа к output
        run: echo "The output was ${{ steps.my-step.outputs.output_value }}"
```

## Дополнительная информация

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)**: Общее описание платформы.
- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)**: Детальное описание ключей `on`, `jobs` и `steps`.
- **Официальная документация**: [Workflow syntax for GitHub Actions](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)
