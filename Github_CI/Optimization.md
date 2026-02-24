# Оптимизация в GitHub Actions

## Определения

| Термин | Описание |
|---|---|
| **Concurrency** | Механизм контроля одновременных запусков одного и того же воркфлоу. |
| **Cache** | Хранилище для зависимостей и промежуточных артефактов для ускорения последующих запусков. |
| **Matrix Strategy** | Способ параллельного выполнения задач (jobs) с различными конфигурациями (версии языка, ОС). |
| **Reusable Workflow** | Воркфлоу, который можно вызывать из других воркфлоу для переиспользования логики. |

## Основные концепции и практические сценарии

### 1. Контроль одновременных запусков

Использование `concurrency` с `cancel-in-progress: true` отменяет устаревшие запуски воркфлоу в той же ветке. Это особенно полезно для pull requests, куда часто отправляются коммиты, и позволяет экономить ресурсы, не выполняя задачи для промежуточных состояний кода.

**Пример:**

```yaml
# .github/workflows/ci.yml
name: CI Pipeline

on:
  push:
    branches:
      - main
      - 'feature/**'

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      # ... остальные шаги
```

- **См. также:** [Синтаксис воркфлоу](./Workflow_Syntax.md)

### 2. Кеширование зависимостей

Кеширование (`actions/cache`) позволяет сохранять зависимости (например, `node_modules`, `~/.cache/pip`, `.m2`, `~/.gradle`) между запусками. Это значительно сокращает время на скачивание пакетов при каждом выполнении. Ключ кеша должен быть уникальным для набора зависимостей.

**Пример для Python:**

```yaml
- name: Cache pip packages
  uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
    restore-keys: |
      ${{ runner.os }}-pip-
```

- **См. также:** [Готовые Actions из Marketplace](./Marketplace_Actions.md)

### 3. Параллелизация с помощью Matrix Strategy

Матричная стратегия позволяет запускать одну и ту же задачу параллельно для разных конфигураций (например, тесты на разных версиях языка или ОС). Параметр `fail-fast: false` гарантирует, что падение одной задачи из матрицы не отменит остальные.

**Пример:**

```yaml
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.10', '3.11']
        os: [ubuntu-latest, macos-latest]
    steps:
      # ... шаги для тестирования
```

- **См. также:** [Матричные сборки](./Matrix_Builds.md)

### 4. Переиспользование воркфлоу

Повторяющиеся шаги (например, сборка, деплой в staging) следует выносить в переиспользуемые воркфлоу (`workflow_call`). Это упрощает поддержку, уменьшает дублирование кода и количество ошибок.

**Пример вызова:**

```yaml
# .github/workflows/main-deploy.yml
jobs:
  deploy-production:
    uses: ./.github/workflows/reusable-deploy.yml
    with:
      environment: 'production'
    secrets: inherit
```

### 5. Условные триггеры запуска

Запускайте воркфлоу только тогда, когда это действительно необходимо, используя фильтры по веткам, тегам или измененным файлам (`paths`). Это предотвращает ненужные запуски, например, при изменении документации.

**Пример:**

```yaml
on:
  push:
    branches: [main]
    paths:
      - 'src/**'
      - '.github/workflows/**'
      - 'package.json'
```

- **См. также:** [События, Задачи и Шаги](./Events_Jobs_Steps.md)
