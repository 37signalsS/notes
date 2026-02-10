# Matrix builds: параллелизм тестирования

Матрица в GitHub Actions — это способ описать набор параметров, по комбинациям которых автоматически порождаются независимые, параллельно исполняемые задания. Это позволяет одновременно проверять проект на разных операционных системах, версиях языка/зависимостей, архитектурах и даже разбивать общий набор тестов на «шарды» для ускорения обратной связи.

## Базовая матрица: среды и версии

В рамках одного job можно задать оси матрицы (например, os и python), а также управлять исключениями, особыми случаями и параллелизмом. Пример:

```yaml
name: ci
on: [push, pull_request]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      max-parallel: 6
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ['3.9', '3.11', '3.12']
        exclude:
          - os: windows-latest
            python: '3.12'
        include:
          - os: ubuntu-latest
            python: '3.12'
            experimental: true
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -r requirements.txt
      - name: Run tests
        run: pytest -q
      - name: Do not fail build for experimental combo
        if: ${{ matrix.experimental == true }}
        run: echo "Experimental"
        continue-on-error: true
```

Ключевые моменты:

*   Каждая комбинация значений формирует отдельный изолированный запуск.
*   `exclude` убирает конфликтующие пары, `include` добавляет «точечные» случаи и может вводить дополнительные поля (например, experimental).
*   `fail-fast: false` предотвращает остановку остальных прогонов при первом падении.
*   `max-parallel` ограничивает одновременное количество исполнений, что полезно при лимитах раннеров.

## Шардинг тестов внутри матрицы

Помимо проверки разных сред, ось матрицы можно использовать для параллельного деления одной и той же среды на сегменты тестов. Например, добавим ось shard и распределим файлы тестов по остаткам от деления номера строки:

```bash
jobs:
  test-sharded:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [0, 1, 2, 3]
    env:
      SHARDS: 4
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - name: Run shard
        env:
          SHARD: ${{ matrix.shard }}
        shell: bash
        run: |
          files=$(git ls-files 'tests/test_*.py' | sort)
          list=$(printf "%s
" $files | awk "NR%$SHARDS==$((SHARD+1))")
          if [ -z "$list" ]; then echo "No tests for shard $SHARD"; exit 0; fi
          pytest -q $list
```

Такой подход не требует внешних сервисов распределения и улучшает время прохождения, особенно при больших наборах тестов. Альтернативой может быть использование плагинов или генерация списка тестов по историческим метрикам, но архитектурно ось матрицы остаётся механизмом параллелизма.

## Параметры стратегии: краткая памятка

| Параметр | Назначение |
| :--- | :--- |
| strategy.matrix | Описание осей и значений для комбинаций |
| include/exclude | Точечное добавление/исключение комбинаций |
| fail-fast | Прерывать ли оставшиеся при первом падении |
| max-parallel | Верхний предел одновременных запусков |
| continue-on-error| Разрешить негативный исход для части матрицы |

Грамотное применение матрицы позволяет масштабировать покрытие и удерживать быстрый цикл обратной связи без ручного дублирования конфигураций.
