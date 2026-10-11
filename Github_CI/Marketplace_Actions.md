# GitHub Actions: Готовые действия и Marketplace

**Актуально для:** GitHub Actions, октябрь 2026 (actions/checkout v7, actions/cache v6; JavaScript-экшены — runtime Node.js 24; `@actions/core` v3, ESM-only; Node 20 удалён из Actions, сентябрь 2026)

Готовые действия (`actions`) — это переиспользуемые блоки автоматизации, составляющие основу экосистемы GitHub Actions. Они позволяют использовать проверенные решения для типовых задач, сокращая время на разработку и поддержку процессов CI/CD (Continuous Integration / Continuous Deployment).

## Определения

- **Action (Действие)**: Автономный программный компонент, выполняющий конкретную задачу. Встраивается как отдельный шаг (`step`) в задачу (`job`). Не путать с Reusable Workflow: экшен — это шаг внутри задачи, а не самостоятельная задача (см. [Переиспользуемые процессы](./Reusable_Workflows.md)).
- **`action.yml`**: Манифест действия, описывающий его входы (`inputs`), выходы (`outputs`) и среду выполнения (`runs`). Альтернативное имя `action.yaml` также допустимо, но `action.yml` предпочтителен; смена имени файла между релизами скрывает старые версии из Marketplace.
- **GitHub Marketplace**: Публичный реестр для поиска и публикации действий. Публикация мгновенная и не требует ревью со стороны GitHub, если выполнены формальные требования (публичный репозиторий, манифест в корне, уникальное имя).
- **Verified Creator**: Отметка (синяя галочка) для официальных действий GitHub или проверенных партнеров. Означает только проверку владельца, а не аудит кода — код всё равно следует читать перед использованием.
- **Actions Toolkit**: Набор официальных библиотек (`@actions/core`, `@actions/github`, `@actions/exec`, `@actions/io`, `@actions/cache`, `@actions/artifact`) для разработки JavaScript-экшенов. `core.getInput()`, `core.setOutput()` и `core.setFailed()` — стандартные точки входа для работы с интерфейсом экшена. С `@actions/core` v3 (январь 2026) пакеты Toolkit переведены на ESM-only: `require()` заменяется на `import` (см. Сценарий 5).
- **Branding**: Раздел манифеста (`branding.icon`, `branding.color`) — иконка из набора Feather и цвет бейджа, отображаемые на странице экшена в Marketplace.

## Основные концепции

### Типы реализации действий

Выбор типа действия зависит от требуемой производительности и переносимости.

1.  **JavaScript Actions**:
    - **Реализация**: Написаны на Node.js (стандарт 2026 — Node.js 24; в манифесте указывается `using: 'node24'`). Рантайм `node20` удалён с GitHub-hosted раннеров в сентябре 2026 — JS-экшены на `node20` и мажорах `@v4`-линеек (`actions/checkout@v4` и старше) там больше не запускаются.
    - **Плюсы**: Самый быстрый запуск (выполняются непосредственно в среде раннера). Кросс-платформенность (Linux, Windows, macOS).
    - **Нюансы**: Требуют упаковки зависимостей (через `@vercel/ncc` или `esbuild` в `dist/index.js`) или наличия `node_modules` в репозитории. Раннер запускает файл, указанный в `runs.main`.
    - **Механика входов**: Значения из `with:` попадают в переменные окружения вида `INPUT_<ИМЯ>` (верхний регистр, пробелы заменяются на `_`), читаются через `core.getInput('имя')`.
2.  **Docker Actions**:
    - **Реализация**: Используют `Dockerfile` для сборки среды (`runs.image: 'Dockerfile'`) либо публичный образ реестра (`runs.image: 'docker://alpine:3.24'`).
    - **Плюсы**: Гарантируют идентичность окружения. Позволяют использовать любые языки (Python, Go, Rust) и системные утилиты.
    - **Нюансы**: Работают только на Linux-раннерах (запуск на `windows-latest`/`macos-latest` завершится ошибкой выполнения контейнера). Имеют накладные расходы на сборку/скачивание контейнера. Входы передаются как аргументы `ENTRYPOINT` (через `runs.args`) и как переменные `INPUT_*`; переменная подставляется буквально, поэтому shell-подстановки требуют явного `sh -c`.
    - **Жизненный цикл**: `pre-entrypoint` и `post-entrypoint` выполняются в отдельных контейнерах того же образа — состояние между ними передаётся только через рабочую директорию, `$HOME` или переменные `STATE_`.
3.  **Composite Actions**:
    - **Реализация**: Объединяют несколько шагов (`run` или другие `uses`) в одном YAML-файле (`runs.using: 'composite'`).
    - **Плюсы**: Не требуют написания кода. Идеальны для группировки часто повторяющихся команд shell.
    - **Нюансы**: Все шаги выполняются в контексте вызывающей задачи (общий `GITHUB_TOKEN`, общая ФС). Поддерживают вложенность: один composite-экшен может вызывать другой через `uses`. Контекст `secrets` внутри composite-экшена недоступен напрямую — секреты передаются вызывающим через `env` или `inputs`. Для `run`-шагов обязателен ключ `shell`. В отличие от JS/Docker, значения входов доступны только через контекст `${{ inputs.* }}` (автоматические переменные `INPUT_*` не создаются).
    - **Поддерживаемые ключи шагов**: `name`, `id`, `if`, `env`, `working-directory`, `run` + `shell`, `uses`, `with`, `continue-on-error`. Ключ `timeout-minutes` для отдельных шагов composite-экшена не поддерживается.

Сравнение типов:

| Критерий | JavaScript | Docker | Composite |
| :--- | :--- | :--- | :--- |
| Скорость старта | Минимальная | Ниже (pull/build образа) | Минимальная |
| Кросс-платформенность | Linux, Windows, macOS | Только Linux | Зависит от шагов |
| Изоляция окружения | Нет (раннер) | Полная (контейнер) | Нет (раннер) |
| Языки | Node.js | Любые | Shell + любые через `uses` |
| Сложность поддержки | Средняя (сборка dist/) | Средняя/высокая | Низкая |
| `secrets` внутри экшена | Через `core.getInput`/env | Через env/args | Недоступен напрямую |

### Способы подключения (`uses`)

| Формат | Пример | Откуда берётся |
| :--- | :--- | :--- |
| `{owner}/{repo}@{ref}` | `actions/checkout@v7` | Корень публичного/доступного репозитория |
| `{owner}/{repo}/{path}@{ref}` | `actions/aws/ec2@main` | Подкаталог репозитория |
| `./{path}` | `./.github/actions/my-action` | Локальный экшен того же репозитория (без `@ref`) |
| `docker://{image}:{tag}` | `docker://alpine:3.24` | Образ из Docker Hub или другого реестра |

Рекомендации по `ref`: полный SHA — максимальная безопасность; тег конкретной версии (`@v6.2.0`) или мажорный тег (`@v6`) — баланс между безопасностью и автоматическим получением патчей; ветка (`@main`) — удобна для разработки, но ломается при выходе breaking changes.

### Анатомия манифеста `action.yml`

Полный пример composite-экшена со всеми ключевыми секциями:

```yaml
# .github/actions/deploy-report/action.yml
name: 'Deploy Report'                     # обязательное, уникальное имя (для Marketplace)
description: 'Collects deploy info and reports status'  # обязательное
author: 'platform-team'

branding:                                 # опционально, только для Marketplace
  icon: 'send'                            # имя иконки из набора Feather
  color: 'blue'                           # white|black|yellow|blue|green|orange|red|purple|gray-dark

inputs:
  environment:
    description: 'Target environment name'
    required: true                        # required: true НЕ вызывает автопроверку — проверять в коде/скрипте
  notify-channel:
    description: 'Slack channel override'
    required: false
    default: '#deploys'
  legacy-flag:
    description: 'Deprecated input, use environment instead'
    required: false
    deprecationMessage: 'Use "environment" instead'  # предупреждение в логе при использовании

outputs:
  report-url:
    description: 'URL of generated report'
    value: ${{ steps.build-url.outputs.url }}   # value обязателен только для composite

runs:
  using: 'composite'
  steps:
    - id: build-url                       # id нужен для ссылки в outputs
      shell: bash                         # shell обязателен для каждого run-шага
      run: |
        if [ -z "${{ inputs.environment }}" ]; then
          echo "::error::Input 'environment' is required"
          exit 1
        fi
        echo "url=https://report.example/${{ inputs.environment }}" >> "$GITHUB_OUTPUT"

    - name: Notify
      if: ${{ failure() }}                # условия if поддерживаются
      uses: slackapi/slack-github-action@91efab103c0de0a537f72a35f6b8cda0ee76bf0a  # v2
      with:
        method: chat.postMessage          # v2 требует явный метод API
        token: ${{ env.SLACK_BOT_TOKEN }}
        payload: |
          channel: ${{ inputs.notify-channel }}
          text: "Deploy of ${{ inputs.environment }} failed"
```

Ключевые механики:

- **Входы**: хранятся как переменные окружения `INPUT_<ИМЯ>` (JS/Docker) либо доступны через контекст `inputs` (все типы). Для Docker-экшенов входы дополнительно передаются аргументами из `runs.args` в `ENTRYPOINT`.
- **Выходы**: шаг записывает значение в `$GITHUB_OUTPUT` (`echo "name=value" >> "$GITHUB_OUTPUT"`), потребитель читает его через `steps.<id>.outputs.<name>`. Лимиты: 1 MB на задачу, 50 MB на весь прогон воркфлоу (UTF-16).
- **Объявление необязательно**: можно записать output без объявления в манифесте, но объявление документирует контракт экшена.
- **`deprecationMessage`** позволяет мягко выводить входы из эксплуатации, предупреждая пользователей в логе.

### Жизненный цикл: pre / main / post

JavaScript- и Docker-экшены поддерживают три фазы выполнения (composite — нет):

```yaml
runs:
  using: 'node24'
  pre: 'setup.js'            # старт задачи, до main (например, подготовка окружения)
  pre-if: 'runner.os == linux'
  main: 'index.js'           # основная логика
  post: 'cleanup.js'         # конец задачи, после всех шагов (например, сохранение кэша)
  post-if: 'success()'       # по умолчанию always()
```

- `pre:` и `post:` выполняются по умолчанию всегда (`always()`), независимо от статуса задачи; отдельные экшены могут задать более строгое условие явно — например, `actions/cache` регистрирует post-шаг с `post-if: success()`, поэтому кэш сохраняется только при успешном завершении задачи.
- В `pre-if`/`post-if` статусные функции оцениваются относительно статуса всей задачи; контекст `step` в `pre-if` недоступен.
- Ограничение: `pre:` не поддерживается для локальных (path-based) экшенов.

### Местоположение и доступность

- **Публичные**: Доступны всем через Marketplace. Формат: `{owner}/{repo}@{ref}`.
- **Локальные**: Лежат в том же репозитории (обычно `.github/actions/`). Вызываются через путь: `uses: ./.github/actions/my-action`. Работают на коммите, где запускается воркфлоу, и не требуют `checkout` самих себя. Доступны только воркфлоу этого репозитория.
- **Внутренние (Internal)**: Доступны только внутри организации или Enterprise. Позволяют делиться кодом между приватными репозиториями. Требуется разрешить доступ в настройках: Organization/Repository → Settings → Actions → General → политика доступа к экшенам (`Allow enterprise select actions` / `Allow organization actions`). На GitHub Enterprise Server синтаксис само-ссылки `$/` недоступен.
- **Приватные сторонние**: Экшен из чужого приватного репозитория по умолчанию недоступен — доступ выдаётся политикой выше, а `GITHUB_TOKEN` при этом остаётся ограничен исходным репозиторием.
- **Образы реестров**: `docker://` работает с любым OCI-реестром (Docker Hub, GHCR, gcr.io); фиксируйте образ по digest (`docker://alpine@sha256:...`) по тем же причинам, что и SHA-pinning.

### Версионирование и релизы экшенов

Экосистема использует три уровня фиксации версии, каждый со своим trade-off:

1.  **Semver-теги** (`v1.4.2`): точка восстановления конкретной функциональности; создаются при каждом релизе.
2.  **Мажорные теги** (`v1`): подвижный указатель на последний стабильный релиз мажорной линии; потребители на `@v1` получают патчи автоматически.

    ```bash
    git tag v1.4.2 && git push origin v1.4.2
    # переместить мажорный тег на новый релиз
    git tag -fa v1 -m "Update v1 to v1.4.2" && git push origin v1 --force
    ```

3.  **SHA коммита**: иммутабелен; единственный вариант, защищающий от подмены содержимого тега (см. «Безопасность цепочки поставок»).

Практическая схема сопровождения собственного экшена: публиковать semver-релиз, двигать мажорный тег, а потребителям рекомендовать Dependabot (обновляет и SHA-pinned зависимости). Breaking change — повод выпустить новую мажорную версию (`v2`), а не переписывать `v1`.

### Безопасность цепочки поставок (Supply Chain)

Использование стороннего кода требует строгого контроля безопасности.

1.  **SHA Pinning**: Фиксация действия по хешу коммита (например, `@5a4ac90...`) вместо тега (`@v7`). Теги мутабельны (автор может их переставить на вредоносный код), SHA — нет. Читаемость сохраняют комментарии с номером версии рядом с SHA.
2.  **Permissions**: Всегда ограничивайте права `GITHUB_TOKEN` на уровне задачи. Большинству экшенов достаточно `contents: read`.
3.  **Harden-Runner**: Используйте [Harden-Runner](./network-security.md) для мониторинга сетевых вызовов экшена в реальном времени.
4.  **Ревью перед внедрением**: проверяйте активность репозитория, совпадение издателя и исходного кода, наличие подписей/attestations. Verified-бейдж подтверждает владельца, но не аудит кода.
5.  **Изоляция секретов**: никогда не передавайте секреты непроверенным экшенам даже через промежуточные переменные — произвольный код шага может их прочитать и отправить наружу. Маскирование секретов в логах не защищает от целевой эксфильтрации.
6.  **Фиксация образов**: `docker://`-ссылки закрепляйте по digest, а не по тегу — тег реестра тоже мутабелен.
7.  **Уведомления об уязвимостях**: Dependabot учитывает advisory-базы GitHub, включая уязвимые Actions, и открывает PR с исправлением; включите алерты для репозитория.

## Практические сценарии

### Сценарий 1: Настройка Dependabot для обновлений экшенов

> **Перенесено**: полная конфигурация Dependabot для GitHub Actions ecosystem (security updates, version updates, grouping, auto-merge) — в **[dedicated файле](./dependabot.md)**, Сценарий 2. Здесь — кратко:

Конфигурация `.github/dependabot.yml` для `package-ecosystem: "github-actions"` обеспечивает автоматическое обновление `uses:`-ссылок в workflow на новые версии экшенов. Для SHA-pinned экшенов Dependabot создаёт PR с обновлённым хешом и комментарием с версией.

### Сценарий 2: Создание локального Composite Action

Используется для стандартизации установки специфического инструментария проекта.

**Предварительные требования**: каталог `.github/actions/setup-tools/` в репозитории; экшен используется только воркфлоу этого же репозитория.

```yaml
# .github/actions/setup-tools/action.yml
name: 'Setup Project Tools'
description: 'Install custom CLI and warm cache'
inputs:
  cli-version:
    description: 'Version to install'
    required: true
    default: '1.2.0'
outputs:
  tool-path:
    description: 'Path to installed CLI binary'
    value: ${{ steps.install.outputs.path }}
runs:
  using: "composite"
  steps:
    - id: install
      shell: bash
      run: |
        curl -L https://tool.com/install.sh | bash -s -- "${{ inputs.cli-version }}"
        echo "path=$HOME/.local/bin/tool" >> "$GITHUB_OUTPUT"
    - uses: actions/cache@v6
      with:
        path: ~/.tool-cache
        key: tools-${{ inputs.cli-version }}
```

Использование в воркфлоу и чтение выхода:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
      - id: tools
        uses: ./.github/actions/setup-tools
        with:
          cli-version: '1.3.0'
      - run: tool --version          # → tool 1.3.0
      - run: echo "installed at ${{ steps.tools.outputs.tool-path }}"
```

- **Валидация**: запуск воркфлоу; шаг установки зелёный, в логе виден вывод `install.sh`, команда `tool --version` печатает ожидаемую версию.
- **Очистка/откат**: удалить каталог экшена и шаги `uses: ./.github/actions/...` из воркфлоу — внешних следов нет.

### Сценарий 3: Безопасное использование Marketplace-экшена (SHA Pinning)

**Предварительные требования**: известен нужный тег релиза; SHA берётся из истории репозитория экшена.

```bash
# узнать SHA тега перед пиннингом
git ls-remote https://github.com/super-linter/super-linter.git refs/tags/v9.0.0
# → 2da136927bd4a73596db63044b504547c62cb854	refs/tags/v9.0.0
```

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      statuses: write                        # super-linter сообщает статус-чек PR
    steps:
      - name: Checkout
        # v7.0.1 fixed at SHA
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          fetch-depth: 0                     # super-linter сопоставляет изменения по git-истории
          persist-credentials: false

      - name: Lint Code
        uses: super-linter/super-linter@2da136927bd4a73596db63044b504547c62cb854  # v9.0.0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- Комментарий с версией рядом с SHA обязателен — без него обновление Dependabot теряет читаемость, а человек не понимает, что зафиксировано.
- **Валидация**: соответствие SHA тегу уже проверено `git ls-remote`; после прогона сравните версию в логах шага с ожидаемой.

### Сценарий 4: Собственный Docker-экшен

Когда логика требует системных утилит или языка, которого нет на раннере.

**Структура репозитория**:

```text
.
├── action.yml
├── Dockerfile
└── entrypoint.sh
```

```yaml
# action.yml
name: 'YAML Validator'
description: 'Validate YAML files against a schema'
inputs:
  schema:
    description: 'Path to JSON schema'
    required: true
  files:
    description: 'Space-separated list of files'
    required: true
runs:
  using: 'docker'
  image: 'Dockerfile'                 # собрать из локального Dockerfile
  args:
    - ${{ inputs.schema }}
    - ${{ inputs.files }}
```

```dockerfile
# Dockerfile — базовый образ зафиксирован по digest
FROM python:3.13-slim@sha256:<digest>

RUN pip install --no-cache-dir check-jsonschema

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

```bash
#!/bin/sh -l
# entrypoint.sh — входы приходят как аргументы ($1, $2) из runs.args
set -e
check-jsonschema --schemafile "$1" $2
echo "::notice::Validated $(echo $2 | wc -w) files against $1"
```

Использование:

```yaml
steps:
  - uses: <owner>/<repo>@<sha>
    with:
      schema: schemas/config.schema.json
      files: "config.yml k8s/*.yaml"
```

- **Валидация**: локально повторите поведение контейнера: `docker build -t val . && docker run -v "$PWD":/ws -w /ws val schemas/config.schema.json "config.yml"` — вывод должен совпасть с выводом шага в CI.
- **Edge cases**: на `windows-latest`/`macos-latest` такой шаг упадёт — либо явно используйте `runs-on: ubuntu-latest`, либо перенесите логику в JavaScript-экшен (см. Сценарий 5).

### Сценарий 5: Собственный JavaScript-экшен (Actions Toolkit)

Самый быстрый по запуску тип экшена: раннер исполняет `main`-файл напрямую в среде раннера, без pull/build контейнера.

**Предварительные требования**: Node.js 24 и npm в среде разработки; репозиторий экшена (публичный — для Marketplace, приватный — для внутреннего использования).

**Структура репозитория**:

```text
.
├── action.yml
├── package.json
├── src/
│   └── index.js
└── dist/
    └── index.js        # собранный самодостаточный бандл — коммитится
```

**Манифест** (`action.yml`):

```yaml
name: 'Deploy Reporter'
description: 'Report deploy status and expose a report URL'
inputs:
  environment:
    description: 'Target environment'
    required: true
outputs:
  report-url:
    description: 'URL of the generated report'
runs:
  using: 'node24'
  main: 'dist/index.js'
```

**Логика** (`src/index.js`) — интерфейс экшена строится через Actions Toolkit:

```javascript
import * as core from '@actions/core';

try {
  const environment = core.getInput('environment', { required: true });
  const url = `https://report.example/${environment}`;
  core.setOutput('report-url', url);
  core.info(`Report for ${environment}: ${url}`);
} catch (error) {
  core.setFailed(error.message);
}
```

**Сборка бандла**:

```bash
npm init -y
npm install @actions/core
npm pkg set type=module engines.node=">=24"
# раннер не выполняет npm install — код и зависимости собираются в один файл
npx esbuild src/index.js --bundle --platform=node --format=esm --target=node24 --outfile=dist/index.js
```

- **Зачем бандл**: раннер скачивает репозиторий экшена и сразу исполняет файл из `runs.main` — отдельного шага установки зависимостей нет. Поэтому собранный `dist/` коммитится (либо собирается в релизном воркфлоу и попадает только в тег), а `node_modules` в репозиторий не коммитится.
- **ESM**: с `@actions/core` v3 пакет ESM-only, поэтому проект переводится в ESM (`"type": "module"`), а `require()` заменяется на `import`. `@vercel/ncc` и `rollup` (формат `es`) дают тот же результат — важно, чтобы итоговый `dist/index.js` был самодостаточным.

**Использование**:

```yaml
steps:
  - uses: <owner>/<repo>@<sha>       # или @v1
    id: deploy
    with:
      environment: staging
  - run: echo "${{ steps.deploy.outputs.report-url }}"
```

- **Валидация**: заведите в репозитории экшена отдельный тестовый воркфлоу, который вызывает экшен локально (`uses: ./`) и проверяет выполнение шага и значение выхода — успешный прогон служит критерием готовности релиза.
- **Edge cases**: рантайм фиксируется ключом `runs.using: 'node24'`; локальные (path-based) экшены не поддерживают фазу `pre` (см. «Жизненный цикл: pre / main / post»).

### Сценарий 6: Публикация собственного экшена в GitHub Marketplace

**Предварительные требования**:

- экшен находится в публичном репозитории;
- `action.yml` лежит в корне репозитория (один публикуемый манифест на репозиторий; экшены в подпапках автоматически не листятся);
- имя в `name` уникально в Marketplace и не совпадает с именами пользователей/организаций/категорий;
- владелец аккаунта принял GitHub Marketplace Developer Agreement (иначе чекбокс публикации будет заблокирован);
- включена двухфакторная аутентификация.

**Шаги публикации**:

1. Добавьте в манифест секцию `branding` (иконка и цвет) — без неё страница экшена выглядит обезличенно, а валидатор выдаёт предупреждение.
2. Откройте `action.yml` в веб-интерфейсе — над файлом появится баннер; нажмите **Draft a release**.
3. В блоке «Release Action» отметьте **Publish this Action to the GitHub Marketplace**.
4. Исправьте все ошибки/предупреждения метаданных до сообщения **Everything looks good!**.
5. Выберите Primary Category (опционально вторую категорию).
6. Укажите тег версии (semver, например `v1.0.0`), заголовок релиза, описание; нажмите **Publish release**.
7. Создайте/перекиньте мажорный тег (`git tag -fa v1 ... && git push origin v1 --force`) — см. «Версионирование и релизы экшенов».

**Валидация**: страница `https://github.com/marketplace/actions/<slug>` доступна; поиск по названию находит экшен; установка `uses: <owner>/<repo>@v1` из другого репозитория проходит успешно.

**Сопровождение и откат**:

- Новый релиз = новый тег + повторная отметка чекбокса; листинг связан с уникальным `name`, поэтому релизы продолжают появляться в том же листинге даже после transfer репозитория (редиректы URL создаются автоматически).
- Удаление из Marketplace: снять чекбокс **Publish this Action to the GitHub Marketplace** у каждого опубликованного релиза (Releases → Edit release → Update release). Исходный репозиторий продолжает работать как источник экшена.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Can't find 'action.yml', 'action.yaml' or 'Dockerfile'` | Неверный путь в `uses` или манифест отсутствует | Проверить существование `action.yml` по указанному пути; для локальных экшенов путь начинается с `./` |
| `Missing 'shell'. Provided: run` | `run`-шаг composite-экшена без ключа `shell` | Добавить `shell: bash` (или другой поддерживаемый shell) каждому `run`-шагу |
| `Input required and not supplied: X` | `required: true` в манифесте, значение не передано и не задано `default` | Передать через `with:`; помнить, что платформа не проверяет `required` автоматически — строгие проверки делает код экшена (`core.getInput(..., { required: true })` выбрасывает исключение) |
| `Resource not accessible by integration` (HTTP 403) | `GITHUB_TOKEN` без нужного permission | Расширить `permissions` задачи ровно до необходимого минимума (например, `pull-requests: write`) |
| `unable to resolve action ... unable to find version` | Несуществующий тег/ветка или удалённый ref | Проверить ref в исходном репозитории; при SHA-пиннинге убедиться, что хеш принадлежит этому репозиторию |
| Предупреждение `node20` deprecation или отказ запуска | Экшен собран под рантайм `node20`, удалённый с hosted-раннеров в сентябре 2026 | Обновить экшен до версии на `node24`; свой экшен перевести на `runs.using: 'node24'` |
| Docker-экшен падает на Windows/macOS | Контейнерные экшены работают только на Linux | Закрепить задачу за `ubuntu-latest` либо переписать на JS/composite |
| Секреты пустые внутри composite-экшена | Контекст `secrets` не пробрасывается в composite | Передать секрет параметром или через `env:` на уровне шага вызова |
| Чекбокс публикации в Marketplace заблокирован | Developer Agreement не принят владельцем аккаунта | Принять соглашение под владельцем репозитория/организации, затем вернуться к черновику релиза |

## Лучшие практики

1. **Одна задача на экшен**: держите экшен узкоспециализированным (Unix-принцип). Разросшуюся логику выгоднее вынести в отдельный экшен или переиспользуемый процесс, чем превращать composite в монолит.
2. **Контракт в манифесте и README**: обязательно заполняйте `inputs`/`outputs` с описаниями — страница Marketplace и подсказки `uses` строятся из `action.yml`, а примеры использования и ограничения читатель ищет в README репозитория.
3. **Сборка JS-экшенов**: коммитьте самодостаточный `dist/` (или собирайте его в релизном воркфлоу и включайте только в тег) — раннер не выполняет установку зависимостей. `node_modules` в репозиторий не коммитится; зависимости сборки фиксируются `package-lock.json`.
4. **Тестирование до публикации**: заведите в репозитории экшена воркфлоу, вызывающий сам экшен локально (`uses: ./`), и прогоняйте его на каждый релиз — это ловит сломанный `dist/` и неверные входы до того, как их увидит потребитель.
5. **Маскирование секретов**: производные значения (токены, URL с credentials) регистрируйте через `core.setSecret()` перед выводом в лог; в composite-экшенах секреты не логируйте вовсе — контекст `secrets` им недоступен.
6. **Версионирование и обновления**: публикуйте semver-релиз, двигайте мажорный тег, а потребителям рекомендуйте Dependabot (обновляет и SHA-pinned зависимости). Саму фиксацию версий выполняйте по правилам «Безопасность цепочки поставок» — SHA для критичных путей, тег с комментарием версии для остальных.
7. **Единый манифест на репозиторий**: публикуется только `action.yml` из корня; экшены в подпапках автоматически не листятся — не рассчитывайте на их появление в Marketplace.

## Дополнительная информация

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)** — архитектура и базовые понятия.
- **[Синтаксис Workflow](./Workflow_Syntax.md)** — описание директив `uses`, `with` и `outputs`.
- **[Сетевая безопасность](./network-security.md)** — аудит трафика сторонних экшенов через Harden-Runner.
- **[Переиспользуемые процессы](./Reusable_Workflows.md)** — сравнение с Reusable Workflows (когда что выбирать).
- **[Официальная документация по созданию действий](https://docs.github.com/en/actions/creating-actions)** — технические детали реализации для разработчиков.

Справочные материалы по затронутым темам: [Metadata syntax reference](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax) — исчерпывающий список ключей манифеста; [Publishing actions in GitHub Marketplace](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/publish-in-github-marketplace) — актуальные требования публикации.
