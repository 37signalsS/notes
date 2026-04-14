# GitHub Actions: События, Задачи и Шаги (Events, Jobs, Steps)

Автоматизация в GitHub Actions строится на трёх иерархических компонентах: **Событие** → **Workflow** → **Jobs** → **Steps**. Они определяют, *когда*, *где* и *что* должно выполняться.

## Определения

- **Event (Событие)**: Триггер, инициирующий запуск workflow. Определяет условие «когда».
- **Job (Задача)**: Изолированная среда выполнения (`runner`), выполняющая набор шагов. Определяет «где» и обеспечивает параллелизм.
- **Step (Шаг)**: Отдельная команда или `action` внутри задачи. Определяет «что» конкретно нужно сделать.

## Основные концепции

### Events: Условия Запуска

События объявляются в секции `on` и служат триггерами для воркфлоу.

**Основные типы событий:**

| Событие | Описание | Default Branch Required |
| :--- | :--- | :--- |
| `push` | Коммит, тег, создание репозитория из шаблона | Нет |
| `pull_request` | Активность PR (открыт, обновлён, закрыт, merged) | Нет |
| `workflow_dispatch` | Ручной запуск через UI/API/CLI | Да |
| `schedule` | Запуск по расписанию (cron) | Да |
| `repository_dispatch` | Webhook API для внешних событий | Да |

**Workflow dispatch (2025–2026):**

- Максимум **25 входных параметров** (с декабря 2025, ранее 10)
- Типы inputs: `string`, `choice`, `boolean`, `environment`
- Использование: деплои, миграции, ручные подтверждения

**Фильтры событий:**

- `branches` / `branches-ignore`: фильтрация по веткам
- `tags` / `tags-ignore`: фильтрация по тегам
- `paths` / `paths-ignore`: фильтрация по изменённым файлам
- `types`: типы активности (для `pull_request`, `issues` и др.)

Подробный синтаксис — в **[Синтаксис Workflow](./Workflow_Syntax.md)**.

### Jobs: Единицы Выполнения

Задачи — основные блоки параллелизма. Каждая задача выполняется в свежем изолированном окружении.

- **`runs-on`**: Тип [runner'а](./Environment_Limitations.md) (`ubuntu-latest`, `self-hosted`, `macos-latest`).
- **`needs`**: Зависимости — выстраивает задачи в граф для последовательного выполнения.
- **`strategy.matrix`**: **[Матричные сборки](./Matrix_Builds.md)** — запуск одной задачи с разными параметрами.
- **`services`**: Побочные контейнеры (БД, кэш), доступные всем шагам задачи.
- **`outputs`**: Выходные данные job для передачи в зависимые задачи.
- **`if`**: Условное выполнение всей задачи.

### Steps: Последовательные Действия

Шаги выполняются строго последовательно в рамках одной задачи.

**Типы шагов:**

- `uses`: Готовая **[action](./Marketplace_Actions.md)** (например, `actions/checkout@v4`).
- `run`: Команды оболочки (`shell`).

**Условное выполнение (`if`):**

- Пропуск шага при невыполненном условии
- Условия строятся на **[контекстах и выражениях](./Workflow_Syntax.md)**
- Пример: `if: ${{ github.event.inputs.run_tests != false }}`

**Обмен данными:**

- `id` шага + `GITHUB_OUTPUT`: передача данных между шагами
- `outputs` job: передача данных между задачами через `needs.<job>.outputs`
- Контекст `steps.<id>.outputs`: доступ к данным предыдущих шагов

## Практический сценарий: CI с тестами и сборкой

Этот workflow демонстрирует все три компонента:

- **Event**: Запускается на `push` в `main` или по ручному триггеру с фильтрами по путям.
- **Jobs**: Содержит две задачи, `test` зависит от `build` (`needs: build`). `build` использует матрицу.
- **Steps**: Включают `uses` для настройки среды, `run` для команд и `if` для условного выполнения.

```yaml
name: CI with dependent jobs

on:
  push:
    branches: [ main ]
    paths: [ 'app/**', '!.github/**' ]
  workflow_dispatch:
    inputs:
      run_tests:
        type: boolean
        default: true

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [ '3.10', '3.11' ]
    outputs:
      version: ${{ steps.meta.outputs.version }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - id: meta
        run: echo "version=$(python scripts/version.py)" >> $GITHUB_OUTPUT
      - run: python -m build

  test:
    runs-on: ubuntu-latest
    needs: build
    if: ${{ github.event.inputs.run_tests != false }}
    services:
      redis:
        image: redis:7
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements-test.txt
      - name: Run tests
        env:
          APP_VERSION: ${{ needs.build.outputs.version }}
        run: pytest
```

## Дополнительная информация

Общее описание платформы в **[Ключевые концепции GitHub Actions](./Core_Concept.md)**, полный справочник по синтаксису и контекстам в **[Синтаксис Workflow](./Workflow_Syntax.md)**, матричные сборки в **[Матричные сборки](./Matrix_Builds.md)**. Официальная документация: [Events that trigger workflows](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows).
