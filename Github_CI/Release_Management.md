# GitHub Actions: Управление релизами

Автоматизация релизного цикла — одна из самых частых продакшен-задач GitHub Actions. Тематический блок охватывает путь от тега в Git до опубликованного релиза с артефактами и changelog, включая публикацию пакетов и образов в реестры.

## Определения

- **GitHub Release**: Публикуемый снимок состояния репозитория, привязанный к git-тегу: release notes, бинарные артефакты (assets), статус (draft/prerelease/stable). Отличается от тега: тег — только указатель на коммит, релиз — объект с метаданными.
- **Tag Trigger**: Запуск воркфлоу по событию push тега (`on: push: tags`). Канонический вход в релизный пайплайн.
- **Changelog**: Список изменений между версиями. Источники: автоматически генерируемые notes из заголовков PR, Conventional Commits или ручное ведение файла.
- **Release Asset**: Файл, прикреплённый к релизу (архивы сборки, чексуммы, подписи). Хранится вне истории Git.
- **Prerelease**: Релиз с флагом предверсии (альфа/бета/RC); не участвует в выборе «последнего стабильного» (`latest`).
- **Semantic Release**: Инструмент автоматизации версионирования на основе Conventional Commits (разбор формата коммитов — в [Conventional Commits](../Git/git_conventional_commits.md)).

## Основные концепции

### Триггер по тегам (`on: push: tags`)

```yaml
on:
  push:
    tags:
      - 'v*.*.*'        # семверные теги
      - 'v*'            # при необходимости включить v1-стиль
```

- Фильтры `tags`/`tags-ignore` независимы от `branches`: если заданы оба, воркфлоу запускается при совпадении любого из них. Задание только `tags` отключает реакцию на веточные push.
- Воркфлоу для тегового push берётся из коммита, на который указывает тег: если файл `.github/workflows/release.yml` отсутствует в этом коммите, прогон не создастся (частая ошибка после переименования файлов).
- Контекст: `github.ref_name` = имя тега (`v1.4.2`), `github.ref` = `refs/tags/v1.4.2`.
- Защита от гонки повторного пуша того же тега — `concurrency` с группой по имени тега.

### Извлечение версии из тега

```bash
VERSION="${GITHUB_REF_NAME#v}"   # v1.4.2 → 1.4.2
echo "VERSION=$VERSION" >> "$GITHUB_ENV"
```

Продакшен-практика — сверка версии тега с версией в манифесте пакета (`package.json`, `pyproject.toml`, `Cargo.toml`) до сборки: рассинхрон тега и кода должен падать красным, а не публиковать неверную версию.

### Создание релиза: `gh release create`

GitHub CLI предустановлен на всех hosted-раннерах:

```bash
gh release create "v$VERSION" \
  --title "Release $VERSION" \
  --generate-notes \
  dist/app-$VERSION.tar.gz \
  checksums.txt.sha256
```

- `--generate-notes` строит заметки из merged PR с момента предыдущего тега (`--notes-start-tag` задаёт стартовую точку вручную).
- `--draft` создаёт черновик (не виден пользователям, удобен для двухфазного релиза), `--prerelease` помечает предверсию.
- Альтернатива декларативно — экшен `softprops/action-gh-release@v2` (тот же API, YAML-параметры вместо CLI).
- Права: задача должна иметь `permissions: contents: write`; без этого API вернёт 403.

### Конфигурация автозаметок `.github/release.yml`

Категоризация PR в генерируемых notes по лейблам:

```yaml
# .github/release.yml
changelog:
  exclude:
    labels: [skip-changelog]
  categories:
    - title: Breaking Changes
      labels: [breaking]
    - title: Features
      labels: [feat, enhancement]
    - title: Bug Fixes
      labels: [fix, bug]
    - title: Other Changes
      labels: ['*']
```

Для полноценной семантической нумерации версий и генерации CHANGELOG.md используется semantic-release поверх Conventional Commits (готовый пример конфигурации — в [Conventional Commits](../Git/git_conventional_commits.md)); в этой заметке рассматривается нативный слой GitHub.

### Публикация в реестры как часть релиза

Релизная задача — каноническое место публикации образов и пакетов:
- **GHCR (образы)**: аутентификация `docker/login-action` под встроенным `GITHUB_TOKEN` (scope `packages: write`), стратегия тегов через `docker/metadata-action` (`type=semver,pattern={{version}}` + `latest`). Теория реестров — в [Реестрах Docker](../Docker/docker_registries.md).
- **npm**: токен публикации хранится в секретах (`NODE_AUTH_TOKEN`), команда `npm publish` выполняется один раз в release-воркфлоу; для публичных пакетов доступна provenance-подпись через OIDC.

Публикация выносится в отдельную задачу после сборки и тестов, чтобы невалидная сборка физически не могла попасть в реестр.

### Пререлизы и промоция

Двухфазная модель: публикация как prerelease → проверка на канареечной группе → промоция до стабильной. Промоция — это правка существующего релиза (`gh release edit vX --latest --prerelease=false`), а не создание нового: тег остаётся неизменным, что критично для воспроизводимости.

---

## Практические сценарии

### Сценарий 1: Полный релизный конвейер (тег → сборка → релиз с артефактами)

**Предварительные требования**: защищённые теги (Ruleset на паттерн `v*`), права `contents: write`.

```yaml
name: Release
on:
  push:
    tags: ['v*']

permissions:
  contents: write

concurrency:
  group: release-${{ github.ref_name }}

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0          # полная история нужна для generate-notes и версии
      - name: Verify version consistency
        run: |
          VERSION="${GITHUB_REF_NAME#v}"
          PKG_VERSION=$(jq -r .version package.json)
          if [ "$VERSION" != "$PKG_VERSION" ]; then
            echo "::error::Тег $GITHUB_REF_NAME != версия пакета $PKG_VERSION"
            exit 1                 # → рассинхрон ловится ДО публикации
          fi
      - run: npm ci && npm test && npm run build
      - uses: actions/upload-artifact@v7
        with:
          name: dist
          path: dist/

  publish:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/download-artifact@v8
        with:
          name: dist
          path: dist/
      - name: Checksums
        run: |
          cd dist && sha256sum * > ../checksums.txt && cd ..
      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" \
            --generate-notes \
            dist/* checksums.txt
```

- Каждый параметр: `fetch-depth: 0` даёт полный лог для заметок и корректную версию; сверка версий останавливает конвейер при рассинхроне; чексуммы публикуются рядом с артефактами (стандарт безопасности поставки); `concurrency` исключает параллельные релизы одного тега.
- **Валидация**: `gh release view v1.4.2` показывает assets и заметки с категориями из `.github/release.yml`; вкладка Releases отображает релиз с тегом.
- **Очистка**: черновики незавершённых релизов удаляются `gh release delete <tag> --yes && git push origin :refs/tags/<tag>`.

### Сценарий 2: Публикация Docker-образа в GHCR по релизному тегу

```yaml
jobs:
  image:
    runs-on: ubuntu-latest
    permissions:
      packages: write
      contents: read
    steps:
      - uses: actions/checkout@v7
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ github.token }}       # GITHUB_TOKEN, не PAT
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}    # 1.4.2
            type=semver,pattern={{major}}.{{minor}}   # 1.4 — обновляемый тег линейки
      - uses: docker/build-push-action@v7
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

- **Валидация**: `docker pull ghcr.io/<owner>/<repo>:1.4.2` на локальной машине проходит; в Packages видны теги версии и линейки.
- Приватность образа наследует видимость репозитория; переключение публичности делается в настройках пакета однократно.

### Сценарий 3: Пререлиз и его промоция до стабильной версии

```bash
# фаза 1: публикация пререлиза (в workflow по тегу v*-rc*)
gh release create "$GITHUB_REF_NAME" --prerelease --generate-notes dist/*

# фаза 2 (отдельный воркфлоу с environment approval): промоция
gh release edit "$TAG" --latest --prerelease=false
gh release upload "$TAG" docs/user-guide.pdf --clobber
```

- Промоция выносится в отдельный ручной воркфлоу (`workflow_dispatch` c инпутом тега) с привязкой задачи к окружению `production` — ручное одобрение становится гейтом стабилизации (механика approvals — в [Ключевых концепциях](./Core_Concept.md)).
- **Валидация**: `gh release list` показывает один стабильный `Latest`; `gh api repos/{owner}/{repo}/releases/latest` возвращает промоутнутый тег.

### Сценарий 4: Публикация npm-пакета из релиза

```yaml
  npm:
    needs: publish
    runs-on: ubuntu-latest
    environment: production           # гейт перед внешней публикацией
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v5
        with:
          node-version: 24
          registry-url: https://registry.npmjs.org
      - run: npm ci && npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

- `registry-url` обязателен: setup-node пишет `//registry.npmjs.org/:_authToken=` в `.npmrc`; без него токен не подхватится.
- **Валидация**: `npm view <pkg> version` возвращает новую версию через минуту после прогона; в логе есть строка `+ <pkg>@<version>`.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Пуш тега не запускает воркфлоу | Файла воркфлоу нет в коммите, на который указывает тег | Убедиться, что `release.yml` закоммичен до создания тега; пересоздать тег на актуальный коммит |
| HTTP 403 при `gh release create` | Нет `permissions: contents: write` у задачи | Добавить блок permissions (минимально необходимый) |
| `release already exists` | Тег был force-push или релиз создавался ранее | Идемпотентность: `gh release view "$TAG" \|\| gh release create ...` либо явное удаление черновика |
| Загружен пустой набор assets | Glob артефактов ничего не совпал (сборка в другой директории) | Проверять наличие файлов: `[ -e dist/* ] \|\| exit 1` перед загрузкой |
| Двойной релиз при параллельных пушех | Нет concurrency-группы | Группа `release-${{ github.ref_name }}` |
| npm publish падает E409/EOTP | Пакет уже опубликован или требуется 2FA-токен автоматизации | Использовать automation-токен; публикацию делать строго из релизного воркфлоу |

## Лучшие практики

1. Защищайте паттерн тегов Ruleset'ом: создание тега — такое же привилегированное действие, как запись в ветку.
2. Никогда не перезаписывайте опубликованный тег (`--force`); исправления — новый patch-релиз.
3. Публикуйте чексуммы артефактов; для повышенных требований — attestations (`actions/attest-build-provenance`).
4. Внешние публикации (реестры, npm) — всегда за environment approval.
5. Draft-first flow: сначала черновик, ручная проверка заметок, затем publish.
6. Версию извлекайте из тега, а не из даты/раннера — тег единственный источник правды о версии.

## Дополнительная информация

- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)** — триггер `release` и типы активности.
- **[Готовые действия](./Marketplace_Actions.md)** — версионирование собственных экшенов (та же семверная схема).
- **[Git-автоматизация](./Git_Automation.md)** — бот-коммиты bump'а версии перед релизом.
- **[Conventional Commits](../Git/git_conventional_commits.md)** — формат коммитов и пример semantic-release.
- **[Реестры Docker](../Docker/docker_registries.md)** — теория хранения и продвижения образов.
