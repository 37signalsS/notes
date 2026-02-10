# Events, Jobs, Steps: ключевые компоненты

## Роль компонентов workflow

GitHub Actions описывает автоматизацию через три уровня:

*   **Events (события)** — условия запуска workflow из репозитория.
*   **Jobs (задачи)** — независимые блоки выполнения внутри workflow, могут идти параллельно или по зависимостям.
*   **Steps (шаги)** — последовательные действия внутри job, выполняемые на одном раннере и разделяющие файловую систему и переменные окружения.

Три уровня формируют «когда запускается» → «на каких раннерах и в каком порядке» → «что именно выполняется».

## Сопоставление уровней

| Компонент | Назначение | Где объявляется | Ключевые поля | Особенности |
| :--- | :--- | :--- | :--- | :--- |
| Event | Триггер запуска | root: on | branches, paths, types, schedule, inputs | Фильтры веток/путей, ручной запуск |
| Job | Единица параллельного выполнения | jobs. | runs-on, needs, strategy, services, env, permissions | Параллель/ордеринг, контейнеры, таймауты |
| Step | Последовательное действие в job | jobs..steps | name, run/uses, if, env, shell, with, id | Общая среда job, может публиковать outputs |

## Events: типы и фильтры

Частые события:

*   `push`, `pull_request` — автоматический запуск по изменениям.
*   `workflow_dispatch` — ручной запуск с параметрами.
*   `schedule` — cron-планировщик.
*   `release`, `tags`, `issue_comment`, `repository_dispatch` — для специфических сценариев.

Фильтры позволяют сузить запуск:

*   `branches/branches-ignore`: ветки.
*   `tags/tags-ignore`: теги.
*   `paths/paths-ignore`: изменённые файлы.
*   `types`: виды событий (например, opened, synchronize для pull_request).

## Jobs: исполнение и зависимость

*   `runs-on`: выбор среды (например, ubuntu-latest, windows-latest, self-hosted).
*   `needs`: зависимость между задачами для оркестрации графа.
*   `strategy`: матрица (matrix) для многовариантных прогонов.
*   `services`: побочные контейнеры (БД, кэш) для интеграционных тестов.
*   `env` и `permissions`: окружение и права на уровне job.
*   `concurrency`, `timeout-minutes`: защита от гонок и зависаний.

## Steps: действия внутри job

*   `uses`: готовые действия из Marketplace или локальные composite actions.
*   `run`: произвольные команды shell.
*   `if`: условное выполнение по контекстам/выражениям.
*   `id` и `outputs`: именование шага и экспорт данных для следующих шагов.
*   `continue-on-error`: не прерывать job при сбое шага.
*   `working-directory`, `shell`, `env`: настройка исполнения.

## Пример целостного workflow

```yaml
name: CI

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
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: [ "3.10", "3.11" ]
    steps:
      - name: Checkout
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
        run: |
          echo "version=$(python scripts/version.py)" >> $GITHUB_OUTPUT

      - name: Build wheel
        run: python -m build
        env:
          APP_VERSION: ${{ steps.meta.outputs.version }}

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

В этом примере события ограничены веткой и путями; один job собирает пакет с матрицей версий Python, второй зависит от первого и поднимает сервис Redis для интеграционных тестов. Шаг с id публикует версию через GITHUB_OUTPUT, которую используют следующие шаги.
