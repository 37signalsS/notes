# GitHub Actions: Оптимизация воркфлоу

Оптимизация воркфлоу в GitHub Actions направлена на сокращение времени выполнения, экономию ресурсов и улучшение поддерживаемости CI/CD процессов.

## Определения

- **Оптимизация воркфлоу**: Практика применения техник (кеширование, параллелизация, фильтрация) для минимизации времени и стоимости выполнения CI/CD пайплайнов.

## Основные концепции

### 1. Кеширование зависимостей

Сохранение зависимостей (`node_modules`, `~/.cache/pip`) между запусками для предотвращения их повторного скачивания. Одна из самых эффективных техник ускорения сборок.

Детальное описание: **[Кеширование](./Caching.md)**.

### 2. Параллелизация через Matrix Strategy

Выполнение одной задачи параллельно для разных конфигураций (версии языка, ОС). Сокращает общее время тестирования.

Детальное описание: **[Матричные сборки](./Matrix_Builds.md)**.

### 3. Переиспользование воркфлоу

Вынос повторяющихся шагов в отдельные переиспользуемые воркфлоу. Уменьшает дублирование кода, упрощает поддержку.

Детальное описание: **[Переиспользуемые воркфлоу](./Reusable_Workflows.md)**.

### 4. Контроль одновременных запусков (Concurrency)

Отмена устаревших запусков в той же ветке через `concurrency`. Экономит ресурсы на промежуточных коммитах в PR.

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

Синтаксис: **[Синтаксис Workflow](./Workflow_Syntax.md#concurrency)**.

### 5. Условные триггеры (Paths Filter)

Запуск воркфлоу только при изменении определенных файлов через `paths`. Предотвращает ненужные запуски.

```yaml
on:
  push:
    paths:
      - 'src/**'
      - '!**.md' # Исключить markdown-файлы
```

Фильтры событий: **[События, Задачи и Шаги](./Events_Jobs_Steps.md)**.

### 6. Оптимизация Docker-слоев

При сборке Docker-образов правильная организация слоев в Dockerfile ускоряет процесс за счет кеширования. Ключевые практики:

- Размещение редко меняющихся инструкций в начале
- Использование многоэтапной сборки (multi-stage builds)
- Минимизация количества слоев через объединение команд

Детальное описание: **[Оптимизация сборки Docker-образов](../Docker/Dockerfile/Docker_best_practices/build_optimization.md)**.

## Практический сценарий: Оптимизированный CI-пайплайн

Комбинированный пример с применением нескольких техник оптимизации:

```yaml
name: Optimized CI

on:
  push:
    branches: [ main ]
    paths: [ 'src/**', 'package*.json' ]
  pull_request:
    paths: [ 'src/**', 'package*.json' ]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        node-version: [18, 20, 22]
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
          cache: 'npm' # Встроенное кеширование

      - name: Install dependencies
        run: npm ci

      - name: Run tests
        run: npm test
```

Примененные техники:

- `paths` — запуск только при изменениях в `src/`
- `concurrency` — отмена устаревших запусков
- `matrix` — параллельное тестирование на 3 версиях Node.js
- `cache: 'npm'` — кеширование зависимостей через setup-node

## Дополнительная информация

Детальное описание техник: **[Кеширование](./Caching.md)**, **[Матричные сборки](./Matrix_Builds.md)**, **[Переиспользуемые воркфлоу](./Reusable_Workflows.md)**, синтаксис `concurrency` и `paths` в **[Синтаксис Workflow](./Workflow_Syntax.md)**, фильтры событий в **[События, Задачи и Шаги](./Events_Jobs_Steps.md)**, оптимизация Docker в **[Оптимизация сборки Docker-образов](../Docker/Dockerfile/Docker_best_practices/build_optimization.md)**. Официальная документация: [Workflow syntax](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions).
