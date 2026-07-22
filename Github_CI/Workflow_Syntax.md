# GitHub Actions: Синтаксис рабочего процесса (Workflow)

Файлы рабочих процессов (workflows) в GitHub Actions описываются с использованием языка разметки YAML (Yet Another Markup Language). Они обладают строго определенной структурой, включающей ключи верхнего уровня, контексты и выражения для управления логикой автоматизации.

## Определения

- **Workflow-файл (Рабочий процесс)**: Конфигурационный файл в формате YAML (с расширением `.yml` или `.yaml`), расположенный в директории `.github/workflows/` репозитория.
- **Синтаксис выражений (`${{...}}`)**: Специальный механизм, позволяющий динамически подставлять значения переменных, обращаться к контекстной информации и выполнять условную логику непосредственно в YAML-файле.

## Основные концепции

### Ключи верхнего уровня

Данные ключи определяют общую структуру и поведение рабочего процесса:

- **`name`**: Имя рабочего процесса, отображаемое в интерфейсе (User Interface — UI) GitHub.
- **`on`**: Определяет триггеры — события, которые инициируют запуск процесса. Подробнее в разделе **[События, Задачи и Шаги](./Events_Jobs_Steps.md)**.
- **`jobs`**: Группирует одну или несколько задач, которые будут выполняться.
- **`env`**: Глобальные переменные окружения.
- **`defaults`**: Позволяет задать настройки по умолчанию для всех задач (например, `shell` или `working-directory`).
- **`permissions`**: Настраивает права доступа для временного токена безопасности `GITHUB_TOKEN`.
- **`concurrency`**: Управляет конкурентностью, предотвращая одновременное выполнение нескольких экземпляров одного процесса. Подробнее в разделе **[Оптимизация воркфлоу](./Optimization.md)**.

### Контексты

Контексты — это объекты, содержащие данные о выполнении воркфлоу.

- **`github`**: Метаданные о запуске (ветка, событие, инициатор).
- **`env`**: Переменные окружения.
- **`vars`**: Переменные конфигурации репозитория или организации (не чувствительные).
- **`secrets`**: Зашифрованные секреты. Описано в **[Управлении секретами](./secrets_management.md)**.
- **`steps`**: Выходные данные предыдущих шагов.
- **`matrix`**: Текущие значения итерации матрицы. Описано в **[Матричных сборках](./Matrix_Builds.md)**.
- **`runner`**: Информация об исполнителе (ОС, архитектура).

### Функции и выражения

GitHub Actions поддерживает набор функций для использования в выражениях `${{...}}`:

- **Логические**: `success()`, `failure()`, `always()`, `cancelled()` — используются для проверки статуса предыдущих шагов/задач.
- **Проверки**: `contains(search, item)`, `startsWith(string, prefix)`, `endsWith(string, suffix)`.
- **Данные**: `toJSON(value)`, `fromJSON(value)`, `hashFiles(path)`.

## Практические сценарии

### Комплексная демонстрация синтаксиса

Пример файла, объединяющего основные элементы управления:

```yaml
name: Syntax Overview

on:
  push:
    branches: [ main ]
  workflow_dispatch: # Позволяет запускать вручную из UI

permissions:
  contents: read

concurrency:
  group: syntax-check-${{ github.ref }}
  cancel-in-progress: true

env:
  APPLICATION_TARGET: "Production"

jobs:
  validate-and-report:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
      
      - name: Global environment access
        run: echo "Target environment is ${{ env.APPLICATION_TARGET }}"

      - name: Conditional execution based on context
        if: github.event_name == 'push'
        run: echo "This step was triggered by a code push."
        
      - name: Generating step output
        id: producer
        run: echo "status=success" >> $GITHUB_OUTPUT

      - name: Consuming step output
        run: echo "Previous status was ${{ steps.producer.outputs.status }}"
```

## Дополнительная информация

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)** — архитектурный обзор платформы.
- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)** — детальный разбор иерархии выполнения.
- **[Официальная документация GitHub](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)** — полный справочник по всем директивам.
