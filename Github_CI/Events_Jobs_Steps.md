# GitHub Actions: События, Задачи и Шаги (Events, Jobs, Steps)

Автоматизация в GitHub Actions строится на трёх иерархических компонентах, которые определяют, *когда*, *где* и *что* должно выполняться.

## Определения

- **Event (Событие)**: Триггер, инициирующий запуск всего рабочего процесса (`workflow`). Определяет условие "когда".
- **Job (Задача)**: Изолированная среда выполнения (`runner`), которая выполняет набор шагов. Определяет условие "где" и обеспечивает параллелизм.
- **Step (Шаг)**: Отдельная команда или `action` внутри задачи. Определяет "что" конкретно нужно сделать. Шаги внутри одной задачи выполняются последовательно.

Иерархия выглядит так: **Событие** запускает **Workflow** → **Workflow** содержит одну или несколько **Задач** → Каждая **Задача** состоит из последовательности **Шагов**.

## Основные концепции

### Events: Условия Запуска

События объявляются в секции `on`. Они могут быть как простыми, так и сложными, с фильтрами для точного контроля.

- **Типы событий**:
  - `push`, `pull_request`: Реакция на изменения в коде.
  - `workflow_dispatch`: Ручной запуск через UI GitHub, может принимать `inputs`.
  - `schedule`: Запуск по расписанию (cron).
  - `release`, `issues`, `discussion`: Реакция на события в репозитории.
- **Фильтры**: Позволяют ограничить запуск:
  - `branches` / `tags`: по имени ветки или тега.
  - `paths`: если изменения затронули определенные файлы или директории.
  - `types`: для `pull_request` можно указать `opened`, `synchronize`, `reopened`.

### Jobs: Единицы Выполнения

Задачи — это основные блоки параллелизма. Каждая задача по умолчанию выполняется в свежем, изолированном окружении.

- **Среда выполнения (`runs-on`)**: Указывает тип runner'а (`ubuntu-latest`, `windows-latest`, `self-hosted`).
- **Зависимости (`needs`)**: Позволяет выстраивать задачи в граф, запуская их последовательно. Задача с `needs: another-job` начнется только после успешного завершения `another-job`.
- **Стратегия (`strategy`)**: Используется для создания [матричных сборок](./Matrix_Builds.md), чтобы запустить одну и ту же задачу с разными параметрами.
- **Сервисы (`services`)**: Позволяет запустить "побочные" контейнеры, например, базу данных или кэш, которые будут доступны для всех шагов задачи.

### Steps: Последовательные Действия

Шаги — это "рабочие лошадки" workflow. Они выполняются строго последовательно и разделяют файловую систему и переменные окружения в рамках одной задачи.

- **Типы шагов**:
  - `uses`: Подключает готовую [action](./Marketplace_Actions.md) (например, `actions/checkout@v4`).
  - `run`: Выполняет одну или несколько команд в оболочке (`shell`).
- **Условное выполнение (`if`)**: Позволяет пропустить шаг, если условие не выполнено. Условия строятся на основе [контекстов и выражений](./Workflow_Syntax.md).
- **Обмен данными (`outputs`)**: Шаг может объявить `id` и записать данные в `GITHUB_OUTPUT`. Следующие шаги могут получить доступ к этим данным через контекст `steps`.

## Практический сценарий: CI с тестами и сборкой

Этот workflow демонстрирует все три компонента:

- **Event**: Запускается на `push` в `main` или по ручному триггеру.
- **Jobs**: Содержит две задачи, `build` и `test`. `test` зависит от `build` (`needs: build`).
- **Steps**: Включают `uses` для настройки среды и `run` для выполнения команд. Шаг "Compute version" экспортирует `outputs`.

```yaml
name: CI with dependent jobs

on:
  push:
    branches: [ main ]
    paths:
      - "app/**"
      - "!docs/**"
  pull_request:
    branches: [ main ]
  workflow_dispatch:
    inputs:
      run_tests:
        description: "Запустить тесты"
        required: false
        default: "true"

jobs:
  # Первая задача: сборка
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: [ "3.10", "3.11" ]
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Compute version
        id: meta
        run: echo "version=$(python scripts/version.py)" >> $GITHUB_OUTPUT

      - name: Build artifact
        run: python -m build
        env:
          APP_VERSION: ${{ steps.meta.outputs.version }}

  # Вторая задача: тестирование, зависит от первой
  test:
    runs-on: ubuntu-latest
    needs: build
    if: ${{ github.event_name != 'workflow_dispatch' || inputs.run_tests == 'true' }}
    services:
      redis:
        image: redis:7
        ports: [ "6379:6379" ]
        options: --health-cmd "redis-cli ping" --health-interval=5s --health-retries=5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements-test.txt
      - name: Run tests
        run: pytest -q --maxfail=1 --disable-warnings
```

## Дополнительная информация

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)**: Общее описание платформы.
- **[Синтаксис Workflow](./Workflow_Syntax.md)**: Полный справочник по синтаксису и доступным контекстам.
