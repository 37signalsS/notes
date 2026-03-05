# GitHub Actions: События, Задачи и Шаги (Events, Jobs, Steps)

Автоматизация в GitHub Actions строится на трёх иерархических компонентах, которые определяют, *когда*, *где* и *что* должно выполняться.

## Определения

- **Event (Событие)**: Триггер, инициирующий запуск всего рабочего процесса (`workflow`). Определяет условие "когда".
- **Job (Задача)**: Изолированная среда выполнения (`runner`), которая выполняет набор шагов. Определяет условие "где" и обеспечивает параллелизм.
- **Step (Шаг)**: Отдельная команда или `action` внутри задачи. Определяет "что" конкретно нужно сделать.

Иерархия выглядит так: **Событие** запускает **Workflow** → **Workflow** содержит одну или несколько **Задач** → Каждая **Задача** состоит из последовательности **Шагов**.

## Основные концепции

### Events: Условия Запуска

События объявляются в секции `on` и служат триггерами для воркфлоу.

- **Типы событий**:
  - `push`, `pull_request`: Реакция на изменения в коде.
  - `workflow_dispatch`: Ручной запуск через UI GitHub, может принимать `inputs`.
  - `schedule`: Запуск по расписанию (cron).
- **Фильтры**: Позволяют ограничить запуск по веткам (`branches`), тегам (`tags`) или измененным файлам (`paths`).

Подробный синтаксис определения событий и фильтров описан в **[Синтаксисе Workflow](./Workflow_Syntax.md)**.

### Jobs: Единицы Выполнения

Задачи — это основные блоки параллелизма. Каждая задача по умолчанию выполняется в свежем, изолированном окружении.

- **Среда выполнения (`runs-on`)**: Указывает тип [runner'а](./Environment_Limitations.md) (`ubuntu-latest`, `self-hosted`).
- **Зависимости (`needs`)**: Позволяет выстраивать задачи в граф, запуская их последовательно.
- **Стратегия (`strategy`)**: Используется для создания **[матричных сборок](./Matrix_Builds.md)**, чтобы запустить одну и ту же задачу с разными параметрами.
- **Сервисы (`services`)**: Позволяет запустить "побочные" контейнеры (например, базу данных), которые будут доступны для всех шагов задачи.

### Steps: Последовательные Действия

Шаги — это "рабочие лошадки" workflow. Они выполняются строго последовательно в рамках одной задачи.

- **Типы шагов**:
  - `uses`: Подключает готовую **[action](./Marketplace_Actions.md)** (например, `actions/checkout@v4`).
  - `run`: Выполняет одну или несколько команд в оболочке (`shell`).
- **Условное выполнение (`if`)**: Позволяет пропустить шаг, если условие не выполнено. Условия строятся на основе **[контекстов и выражений](./Workflow_Syntax.md)**.
- **Обмен данными (`outputs`)**: Шаг может объявить `id` и записать данные в `GITHUB_OUTPUT`. Следующие шаги могут получить доступ к этим данным через контекст `steps`.

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

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)**: Общее описание платформы.
- **[Синтаксис Workflow](./Workflow_Syntax.md)**: Полный справочник по синтаксису и доступным контекстам.
- **[Матричные сборки](./Matrix_Builds.md)**: Глубокое погружение в `strategy: matrix`.
