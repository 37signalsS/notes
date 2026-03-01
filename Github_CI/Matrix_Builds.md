# GitHub Actions: Матричные Сборки (Matrix Builds)

Матрица сборок — это мощный механизм в GitHub Actions для параллельного выполнения одной и той же задачи (`job`) с различными параметрами. Это основной инструмент для кросс-платформенного, мультивёрсионного тестирования и один из ключевых способов **[оптимизации](./Optimization.md)** за счет распараллеливания.

## Определения

- **Матрица сборок (Build Matrix)**: Конфигурация в секции `strategy`, которая позволяет определить набор переменных (осей). GitHub Actions автоматически создает и запускает отдельную задачу для каждой возможной комбинации значений этих переменных.

## Основные концепции

### Принцип работы

Вы определяете "оси" матрицы (например, `os`, `node-version`). GitHub Actions генерирует декартово произведение этих наборов.

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest]
    node: [18, 20]
```

Эта конфигурация создаст 4 независимые задачи. Внутри шагов (`steps`) к значениям матрицы можно обращаться через **[контекст](./Workflow_Syntax.md#контексты)** `${{ matrix.os }}`.

### Управление стратегией

- **`fail-fast: false`**: По умолчанию GitHub отменяет все задачи в матрице, как только одна из них завершается с ошибкой. Установка `false` заставляет GitHub дождаться завершения всех задач.
- **`max-parallel`**: Ограничивает количество одновременно выполняемых задач в матрице.

### Расширение матрицы

- **`exclude`**: Позволяет удалить определенные комбинации из матрицы (например, несовместимые).
- **`include`**: Позволяет добавить в матрицу новые, кастомные комбинации, в том числе с дополнительными переменными.

## Практические сценарии

### Сценарий 1: Кросс-платформенное тестирование

Тестирование Python-проекта на разных ОС и версиях Python, с исключениями и специальными случаями.

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
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pytest
      - name: Experimental builds may fail
        if: matrix.experimental
        continue-on-error: true
```

### Сценарий 2: Распараллеливание тестов (Sharding)

Матрицу можно использовать для разделения большого набора тестов на части (шарды) для ускорения CI.

```yaml
jobs:
  test-sharded:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4] # Создаем 4 шарда
    steps:
      - uses: actions/checkout@v4
      - name: Run tests for shard ${{ matrix.shard }}
        run: pytest --shard-id ${{ matrix.shard }} --shard-total 4
```

## Дополнительная информация

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)**: Общее описание платформы.
- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)**: Как матрица встраивается в `job` через `strategy`.
- **[Синтаксис Workflow](./Workflow_Syntax.md)**: Описание контекста `matrix`.
- **[Оптимизация воркфлоу](./Optimization.md)**: Как матрица помогает ускорять CI.
