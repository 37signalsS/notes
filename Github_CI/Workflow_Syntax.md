# GitHub Actions: Синтаксис рабочего процесса (Workflow)

Файлы рабочих процессов (workflows) в GitHub Actions описываются с использованием языка разметки YAML. Они обладают строго определенной структурой, включающей ключи верхнего уровня, контексты и выражения для управления логикой автоматизации.

## Определения

- **Workflow-файл**: Конфигурационный файл в формате YAML (с расширением `.yml` или `.yaml`), расположенный в директории `.github/workflows/` репозитория.
- **Синтаксис выражений (`${{...}}`)**: Механизм, позволяющий динамически подставлять значения переменных, обращаться к контекстной информации и выполнять условную логику.
- **Интерполяция**: Процесс замены плейсхолдеров в строках на их фактические значения во время выполнения.
- **Командные файлы (Workflow Commands)**: Специальный синтаксис строк (через `echo`), позволяющий шагам взаимодействовать с раннером (установка переменных, маскирование секретов, создание выводов).

## Основные концепции

### Ключи верхнего уровня

Данные ключи определяют общую структуру и поведение рабочего процесса:

- **`name`**: Имя рабочего процесса, отображаемое в UI GitHub.
- **`on`**: Определяет триггеры запуска. Поддерживает списки событий, фильтры веток (`branches`), путей (`paths`) и тегов (`tags`).
- **`permissions`**: Настройка прав доступа для `GITHUB_TOKEN` на уровне всего воркфлоу или конкретной задачи.
- **`env`**: Переменные окружения, доступные всем задачам.
- **`defaults`**: Настройки по умолчанию для всех задач (например, `shell: bash` или `working-directory: ./src`).
- **`concurrency`**: Управляет очередями выполнения, позволяя отменять старые запуски при поступлении новых коммитов.

### Иерархия переменных окружения

Переменные могут быть определены на трех уровнях (приоритет от нижнего к верхнему):
1. **Workflow уровень**: Ключ `env` на верхнем уровне файла.
2. **Job уровень**: Ключ `env` внутри конкретной задачи.
3. **Step уровень**: Ключ `env` внутри конкретного шага.

Для динамической установки переменных во время выполнения используется запись в файл `$GITHUB_ENV`:
```bash
run: echo "VERSION=1.0.0" >> $GITHUB_ENV
```

### Контексты

Контексты — это объекты, содержащие данные о выполнении. К ним можно обращаться в любой части YAML, где поддерживаются выражения.

- **`github`**: Метаданные о событии (репозиторий, ветка, SHA коммита, автор).
- **`env`**: Значения переменных окружения, определенных в YAML.
- **`vars`**: Переменные конфигурации (не чувствительные), заданные в настройках репозитория/организации.
- **`secrets`**: Зашифрованные данные. Автоматически маскируются в логах.
- **`steps`**: Содержит `outputs` и статус выполнения (`outcome`, `conclusion`) каждого шага в текущей задаче.
- **`needs`**: Выходы (`outputs`) задач, от которых зависит текущая задача.
- **`inputs`**: Входные параметры для событий `workflow_dispatch` и `workflow_call`.

### Функции и выражения

Выражения `${{ <expression> }}` позволяют использовать программную логику:

- **Логические**: `success()`, `failure()`, `always()`, `cancelled()`.
- **Строковые**: `contains(search, item)`, `startsWith(str, prefix)`, `format(string, ...args)`, `join(array, separator)`.
- **Работа с данными**: `toJSON(value)`, `fromJSON(value)`, `hashFiles(path_pattern)`.
- **Операторы**: Сравнение (`==`, `!=`, `>`, `<`), логические (`&&`, `||`, `!`).

### Взаимодействие между шагами и задачами

1. ** outputs шага**:
   ```yaml
   - id: generate
     run: echo "val=hello" >> $GITHUB_OUTPUT
   - run: echo "${{ steps.generate.outputs.val }}"
   ```
2. ** outputs задачи**:
   Определяются в ключе `outputs` на уровне задачи и ссылаются на `outputs` шагов.
3. **Файл путей (`$GITHUB_PATH`)**:
   Позволяет добавить директорию в `PATH` для последующих шагов:
   ```bash
   run: echo "$HOME/.local/bin" >> $GITHUB_PATH
   ```

## Практические сценарии

### Динамический воркфлоу с условной логикой и фильтрами

Пример демонстрирует использование фильтров путей, условий на уровне шагов и динамических переменных.

```yaml
name: Advanced Syntax Demo

on:
  push:
    branches: [ main ]
    paths: [ 'src/**', 'package.json' ]
  workflow_dispatch:
    inputs:
      logLevel:
        description: 'Log level'
        required: true
        default: 'info'
        type: choice
        options: [info, warning, debug]

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    env:
      BUILD_MODE: ${{ github.event_name == 'workflow_dispatch' && 'manual' || 'auto' }}
    
    outputs:
      artifact_id: ${{ steps.upload.outputs.id }}

    steps:
      - uses: actions/checkout@v7
      
      - name: Dynamic Env Setup
        run: |
          echo "TIMESTAMP=$(date +'%Y-%m-%d_%H-%M')" >> $GITHUB_ENV
          echo "::add-mask::${{ secrets.INTERNAL_ID }}"
          
      - name: Conditional Build
        if: github.event.inputs.logLevel != 'debug'
        run: npm run build --mode=${{ env.BUILD_MODE }}
        
      - name: Generate Output
        id: meta
        run: echo "sha_short=$(git rev-parse --short HEAD)" >> $GITHUB_OUTPUT

      - name: Summary
        if: always()
        run: |
          echo "Build finished at ${{ env.TIMESTAMP }}"
          echo "Git SHA: ${{ steps.meta.outputs.sha_short }}"
```

## Дополнительная информация

- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)** — иерархия выполнения и триггеры.
- **[Матричные сборки](./Matrix_Builds.md)** — использование контекста `matrix`.
- **[Управление секретами](./secrets_management.md)** — безопасность и контекст `secrets`.
- **[Оптимизация воркфлоу](./Optimization.md)** — использование `concurrency` и кеширования.
- **[Официальная документация GitHub](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)** — актуальный полный справочник.
