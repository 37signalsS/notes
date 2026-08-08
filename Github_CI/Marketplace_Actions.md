# GitHub Actions: Готовые действия и Marketplace

Готовые действия (`actions`) — это переиспользуемые блоки автоматизации, составляющие основу экосистемы GitHub Actions. Они позволяют использовать проверенные решения для типовых задач, сокращая время на разработку и поддержку процессов CI/CD (Continuous Integration / Continuous Deployment).

## Определения

- **Action (Действие)**: Автономный программный компонент, выполняющий конкретную задачу. Встраивается как отдельный шаг (`step`) в задачу (`job`).
- **`action.yml`**: Манифест действия, описывающий его входы (`inputs`), выходы (`outputs`) и среду выполнения (`runs`).
- **GitHub Marketplace**: Публичный реестр для поиска и публикации действий.
- **Verified Creator**: Отметка (синяя галочка) для официальных действий GitHub или проверенных партнеров.

## Основные концепции

### Типы реализации действий

Выбор типа действия зависит от требуемой производительности и переносимости.

1.  **JavaScript Actions**:
    - **Реализация**: Написаны на Node.js (стандарт 2026 — Node.js 24).
    - **Плюсы**: Самый быстрый запуск (выполняются непосредственно в среде раннера). Кросс-платформенность (Linux, Windows, macOS).
    - **Нюансы**: Требуют упаковки зависимостей (через `@vercel/ncc` в `dist/index.js`) или наличия `node_modules` в репозитории.
2.  **Docker Actions**:
    - **Реализация**: Используют `Dockerfile` для сборки среды.
    - **Плюсы**: Гарантируют идентичность окружения. Позволяют использовать любые языки (Python, Go, Rust) и системные утилиты.
    - **Нюансы**: Работают только на Linux. Имеют накладные расходы на сборку/скачивание контейнера.
3.  **Composite Actions**:
    - **Реализация**: Объединяют несколько шагов (`run` или другие `uses`) в одном YAML-файле.
    - **Плюсы**: Не требуют написания кода. Идеальны для группировки часто повторяющихся команд shell.
    - **Нюансы**: Все шаги выполняются в контексте вызывающей задачи (общий `GITHUB_TOKEN`, общая ФС).

### Местоположение и доступность

- **Публичные**: Доступны всем через Marketplace. Формат: `{owner}/{repo}@{ref}`.
- **Локальные**: Лежат в том же репозитории (обычно `.github/actions/`). Вызываются через путь: `uses: ./.github/actions/my-action`.
- **Внутренние (Internal)**: Доступны только внутри организации или Enterprise. Позволяют делиться кодом между приватными репозиториями.

### Безопасность цепочки поставок (Supply Chain)

Использование стороннего кода требует строгого контроля безопасности.

1.  **SHA Pinning**: Фиксация действия по хешу коммита (например, `@5a4ac90...`) вместо тега (`@v7`). Теги мутабельны (автор может их переставить на вредоносный код), SHA — нет.
2.  **Permissions**: Всегда ограничивайте права `GITHUB_TOKEN` на уровне задачи. Большинству экшенов достаточно `contents: read`.
3.  **Harden-Runner**: Используйте [Harden-Runner](./network-security.md) для мониторинга сетевых вызовов экшена в реальном времени.

## Практические сценарии

### Сценарий 1: Настройка Dependabot для обновлений экшенов

Автоматическое обновление версий экшенов (поддерживает обновление SHA до новых версий).

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

### Сценарий 2: Создание локального Composite Action

Используется для стандартизации установки специфического инструментария проекта.

```yaml
# .github/actions/setup-tools/action.yml
name: 'Setup Project Tools'
description: 'Install custom CLI and warm cache'
inputs:
  cli-version:
    description: 'Version to install'
    required: true
    default: '1.2.0'
runs:
  using: "composite"
  steps:
    - shell: bash
      run: |
        curl -L https://tool.com/install.sh | bash -s -- ${{ inputs.cli-version }}
    - uses: actions/cache@v4
      with:
        path: ~/.tool-cache
        key: tools-${{ inputs.cli-version }}
```

### Сценарий 3: Безопасное использование Marketplace-экшена (SHA Pinning)

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - name: Checkout
        # v4.2.2 fixed at SHA
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
      
      - name: Lint Code
        uses: github/super-linter@45c405a18b48671602330a1f05786194b5952f44
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Дополнительная информация

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)** — архитектура и базовые понятия.
- **[Синтаксис Workflow](./Workflow_Syntax.md)** — описание директив `uses`, `with` и `outputs`.
- **[Сетевая безопасность](./network-security.md)** — аудит трафика сторонних экшенов через Harden-Runner.
- **[Переиспользуемые процессы](./Reusable_Workflows.md)** — сравнение с Reusable Workflows (когда что выбирать).
- **[Официальная документация по созданию действий](https://docs.github.com/en/actions/creating-actions)** — технические детали реализации для разработчиков.
