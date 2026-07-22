# GitHub Actions: Матричные сборки

Матрица сборок — это механизм в GitHub Actions для параллельного выполнения одной и той же задачи (`job`) с различными параметрами. Это основной инструмент для кросс-платформенного и мультивёрсионного тестирования, а также один из ключевых способов оптимизации пайплайнов за счет распараллеливания.

## Определения

- **Матрица сборок (Build Matrix)**: Конфигурация в секции `strategy`, позволяющая определить набор переменных (осей). GitHub Actions автоматически создает и запускает отдельную задачу для каждой возможной комбинации значений этих переменных.

## Основные концепции

### Механизм работы

При определении "осей" матрицы (например, `os` и `node-version`) GitHub Actions генерирует декартово произведение всех указанных значений.

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest]
    node: [18, 20]
```

Данная конфигурация инициирует 4 независимые задачи. Внутри шагов (`steps`) к значениям матрицы можно обращаться через контекст `${{ matrix.os }}` и `${{ matrix.node }}`. Подробнее о контекстах см. в **[Синтаксис Workflow](./Workflow_Syntax.md)**.

### Управление стратегией выполнения

- **`fail-fast`**: По умолчанию установлено значение `true`, что заставляет GitHub отменять все незавершенные задачи в матрице, если хотя бы одна из них завершилась ошибкой. Установка `false` позволяет дождаться завершения всех задач независимо от их результата.
- **`max-parallel`**: Параметр для ограничения количества одновременно выполняемых задач в рамках одной матрицы. Полезно при работе с ограниченными ресурсами или внешними API (Application Programming Interface), имеющими лимиты на количество запросов.

### Изменение состава матрицы

- **`exclude`**: Позволяет исключить конкретные комбинации из набора (например, если определенная версия библиотеки не поддерживается в конкретной операционной системе).
- **`include`**: Самый мощный инструмент расширения матрицы. Позволяет:
    1. Добавить абсолютно новую комбинацию, которая не вписывается в декартово произведение осей.
    2. Дополнить существующие комбинации уникальными метаданными (например, добавить флаг `experimental: true` только для определенной версии ОС).

**Ограничения матрицы**:
- Максимальное количество задач, которые может сгенерировать одна матрица — **256**.
- Общий лимит на количество одновременных задач в рамках всего воркфлоу зависит от тарифного плана GitHub.

## Практические сценарии

### Сценарий 1: Кросс-платформенное тестирование

Проверка проекта на разных ОС (Operating System) и версиях языка с учетом исключений.

```yaml
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ['3.9', '3.11']
        exclude:
          - os: macos-latest
            python-version: '3.9'
        include:
          - os: ubuntu-latest
            python-version: '3.12'
            experimental: true
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python-version }}
      - run: pytest
      - name: Обработка экспериментальных сборок
        if: matrix.experimental
        continue-on-error: true
```

### Сценарий 2: Разделение тестов на части (Sharding)

Использование матрицы для распределения большого набора тестов между несколькими исполнителями (runners) для сокращения общего времени выполнения CI/CD (Continuous Integration / Continuous Deployment).

```yaml
jobs:
  test-sharded:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4] # Создание 4 параллельных задач
    steps:
      - uses: actions/checkout@v4
      - name: Запуск тестов для шарда ${{ matrix.shard }}
        run: pytest --shard-id ${{ matrix.shard }} --shard-total 4

```

### Сценарий 3: Динамическая матрица

Иногда состав матрицы заранее неизвестен и должен определяться "на лету" (например, на основе списка измененных модулей в монорепозитории). Для этого используется связка выхода задачи в формате JSON (JavaScript Object Notation) и функции `fromJSON`.

```yaml
jobs:
  setup:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.set-matrix.outputs.matrix }}
    steps:
      - id: set-matrix
        run: echo "matrix=[\"module-a\", \"module-b\"]" >> $GITHUB_OUTPUT

  test:
    needs: setup
    runs-on: ubuntu-latest
    strategy:
      matrix:
        module: ${{ fromJSON(needs.setup.outputs.matrix) }}
    steps:
      - name: Testing ${{ matrix.module }}
        run: ./test.sh --module ${{ matrix.module }}
```

## Дополнительная информация

- **[Синтаксис Workflow](./Workflow_Syntax.md)** — детальный справочник по контекстам и директивам.
- **[Оптимизация воркфлоу](./Optimization.md)** — методы ускорения пайплайнов через параллелизм.
- **[Официальная документация GitHub](https://docs.github.com/en/actions/using-jobs/using-a-matrix-for-your-jobs)** — детальное руководство по матрицам.
