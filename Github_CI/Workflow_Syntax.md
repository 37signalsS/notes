# Workflow-файлы: синтаксис и размещение

## Где хранятся workflow-файлы

Файлы GitHub Actions размещаются в репозитории по пути .github/workflows. Допустимы расширения .yml или .yaml. Имена произвольные, лучше без пробелов и с кратким описанием назначения (например, ci.yml, release.yaml). В одном репозитории может быть несколько файлов workflow; они независимы и могут запускаться параллельно.

Workflow должен находиться в ветке, из которой выполняется событие. Для переиспользуемых workflow допускается хранение в любом репозитории; подключение выполняется через uses с указанием owner/repo и пути .github/workflows/.yml на определённой версии или теге.

## Структура и ключи верхнего уровня

YAML чувствителен к отступам и использует пробелы (табуляции недопустимы). Порядок ключей не критичен, но распространённая структура выглядит так:

| Ключ | Назначение |
| :--- | :--- |
| name | Человекочитаемое имя workflow. |
| on | События-триггеры (push, pull_request, schedule, workflow_dispatch и др.). |
| env | Глобальные переменные окружения. |
| permissions | Права GITHUB_TOKEN по умолчанию для workflow. |
| defaults | Значения по умолчанию для run (shell, working-directory). |
| concurrency | Группировка и отмена конкурирующих запусков. |
| jobs | Набор заданий, выполняемых на раннерах. |

## Минимальный пример

```yaml
name: CI
on:
  push:
    branches: [ main ]
    paths:
      - "src/**"
      - "!docs/**"
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

env:
  NODE_ENV: test

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [18, 20]
    steps:
      - uses: actions/checkout@v4
      - name: Установка Node.js
        uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
      - name: Установка зависимостей
        run: npm ci
      - name: Сборка
        run: npm run build

  tests:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm test
        env:
          CI: "true"
```

## Ключевые элементы синтаксиса

*   `on` поддерживает список событий или объект с фильтрами: branches, tags, paths, types. Для ручного запуска используется workflow_dispatch с inputs. Для расписания — schedule с cron.
*   `jobs` — словарь заданий. Каждое задание имеет runs-on (ubuntu-latest, windows-latest, macos-latest или self-hosted) и steps.
*   `steps` бывают двух типов:
*   `uses` — подключение готового действия: owner/repo@версия, Docker-образ или локальный путь ./path.
*   `run` — выполнение команд в шелле; можно задать shell или использовать defaults.run.
*   Стратегии выполнения: `strategy.matrix` позволяет варьировать параметры (версии ОС, интерпретаторов, флагов сборки), а также include/exclude для точной настройки.
*   Условные выражения задаются в `if`: на уровнях job/step, например: `if: github.ref == 'refs/heads/main'`. Внутри значений часто применяются выражения ${{ ... }} и контексты (github, env, secrets, matrix).
*   Переменные окружения можно объявлять глобально (env на уровне workflow), для job или step; переопределение происходит по месту.
*   `permissions` ограничивает доступ GITHUB_TOKEN; рекомендуется явно задавать только необходимые права (например, contents: read, id-token: write).
*   `concurrency` предотвращает одновременные конфликты: group задаёт ключ группировки, cancel-in-progress отменяет более старые запуски при новых коммитах.
*   Переиспользуемые workflow подключаются через `uses: owner/repo/.github/workflows/file.yml@ref` в job, а целевой файл должен иметь триггер `workflow_call`.
