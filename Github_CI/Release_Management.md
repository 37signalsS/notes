# GitHub Actions: Управление релизами

**Актуально для:** GitHub Actions, октябрь 2026 (actions/checkout v7, docker/login-action v4, docker/metadata-action v6, docker/build-push-action v7, softprops/action-gh-release v3; immutable releases — generally available с 28 октября 2025)

Автоматизация релизного цикла — одна из самых частых продакшен-задач GitHub Actions. Тематический блок охватывает путь от тега в Git до опубликованного релиза с артефактами и changelog, включая публикацию пакетов и образов в реестры.

## Определения

- **GitHub Release**: Публикуемый снимок состояния репозитория, привязанный к git-тегу: release notes, бинарные артефакты (assets), статус (draft/prerelease/stable). Отличается от тега: тег — только указатель на коммит, релиз — объект с метаданными.
- **Tag Trigger**: Запуск воркфлоу по событию push тега (`on: push: tags`). Канонический вход в релизный пайплайн.
- **Changelog**: Список изменений между версиями. Источники: автоматически генерируемые notes из заголовков PR, Conventional Commits или ручное ведение файла.
- **Release Asset**: Файл, прикреплённый к релизу (архивы сборки, чексуммы, подписи). Хранится вне истории Git. Лимиты платформы: до 1000 ассетов на релиз, каждый файл меньше 2 GiB; суммарный размер и трафик не ограничены.
- **Prerelease**: Релиз с флагом предверсии (альфа/бета/RC); не участвует в выборе «последнего стабильного» (`latest`).
- **Immutable Release**: Релиз, у которого после публикации заблокированы ассеты и связанный git-тег. Включается на уровне репозитория или организации; защищает поставку от подмены артефактов и перезаписи тега.
- **Release Attestation**: Криптографически проверяемая запись о релизе (тег, SHA коммита, ассеты) в формате Sigstore bundle, автоматически создаваемая при публикации immutable-релиза. Проверяется через GitHub CLI и совместимые с Sigstore инструменты.
- **Trusted Publishing**: Публикация пакета из CI по OIDC без долгоживущего токена: провайдер (GitHub Actions) выдаёт короткоживущий ID-токен, реестр обменивает его на право публикации. Заменяет классический `NPM_TOKEN`.
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

### Триггер по событию `release` (второй вход в пайплайн)

Тег и релиз — разные объекты, и события у них независимы. `on: push: tags` срабатывает на появление тега (сборка, публикация), а `on: release` — на создание/изменение самого релиза. Второе событие полезно, когда публикацию во внешние системы нужно запускать **после** ручного оформления релиза, а не в момент сборки:

```yaml
on:
  release:
    types: [published]      # стабильный релиз и пререлиз
```

- Типы активности: `published` (любой опубликованный релиз — стабильный или пререлиз), `prereleased` (только пререлиз), `released` (только стабильный, не пререлиз), а также `created`/`edited`/`deleted`/`unpublished` (полный список — в [Событиях](./Events_Jobs_Steps.md)).
- Событие **не срабатывает для draft-релизов**: черновик становится источником события только в момент публикации. Это естественная точка отсечения «релиз ещё не выпущен».
- `release.target_commitish` и `GITHUB_REF` для события `release` указывают на тег (`refs/tags/<tag>`), `github.event.release.tag_name` — имя тега в чистом виде.
- Разделение: сборка и загрузка ассетов идут по `push: tags` (артефакт привязан к коммиту), а уведомления, деплой и публикация в сторонние реестры — по `release: types: [published]`. Если всё делать по тегу, релиз публикуется раньше, чем ассеты готовы.

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
- Альтернатива декларативно — экшен `softprops/action-gh-release@v3` (тот же API, YAML-параметры вместо CLI; v3 работает на runtime Node 24, ветка v2 заморожена на 2.6.2 и не поддерживается).
- Права: задача должна иметь `permissions: contents: write`; без этого API вернёт 403.
- Ассеты загружаются отдельно от текста релиза: `gh release upload <tag> <file> --clobber`. Лимиты платформы — до 1000 ассетов на релиз, каждый файл меньше 2 GiB. На immutable-релизе повторная загрузка отклоняется (см. ниже).

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
- **GHCR (образы)**: аутентификация `docker/login-action@v4` под встроенным `GITHUB_TOKEN` (scope `packages: write`), стратегия тегов через `docker/metadata-action@v6` (`type=semver,pattern={{version}}` + `latest`). Теория реестров — в [Реестрах Docker](../Docker/docker_registries.md).
- **npm**: предпочтительный способ — trusted publishing по OIDC (право `id-token: write`, без долгоживущего токена); команда `npm publish` выполняется один раз в release-воркфлоу. Для публичных репозиториев npm автоматически прикладывает provenance-аттестацию. Классический `NODE_AUTH_TOKEN` из секретов остаётся как запасной путь там, где OIDC недоступен (self-hosted раннеры).

Публикация выносится в отдельную задачу после сборки и тестов, чтобы невалидная сборка физически не могла попасть в реестр.

### Пререлизы и промоция

Двухфазная модель: публикация как prerelease → проверка на канареечной группе → промоция до стабильной. Промоция — это правка существующего релиза (`gh release edit vX --latest --prerelease=false`), а не создание нового: тег остаётся неизменным, что критично для воспроизводимости.

### Immutable releases и аттестации

С 28 октября 2025 неизменяемость релизов (release immutability) вышла в общий доступ (GA). Это функция уровня репозитория или организации: соответствующая настройка делает **все новые** релизы неизменяемыми, уже опубликованные остаются изменяемыми, пока их не переопубликуют.

Что именно защищается после публикации:

- **Ассеты нельзя добавить, изменить или удалить** — подмена бинарника в уже выпущенном релизе становится невозможной. Это прямой барьер для supply-chain-атак через компрометацию аккаунта сопровождающего.
- **Тег закреплён за конкретным коммитом** — его нельзя переместить (force-push) или удалить, пока существует релиз. После удаления immutable-релиза имя тега повторно использовать нельзя (защита и от «resurrection»-атак с пересозданием репозитория).
- Изменяемыми остаются только **заголовок и текст заметок** и статус (prerelease/latest) — `gh release edit --notes` продолжает работать.

Публикация immutable-релиза автоматически создаёт **release attestation** — подписанную запись (Sigstore bundle), связывающую тег, SHA коммита и дайджесты ассетов. Проверка на стороне потребителя:

```bash
gh release verify <tag>              # проверить релиз как единое целое
gh release verify-asset <tag> <file> # проверить отдельный ассет
```

Рекомендуемый порядок именно для immutable-режима — draft-first: создать черновик, приложить **все** ассеты, и только затем опубликовать. Как только релиз опубликован, добавить забытый файл уже нельзя, а обходной путь (удалить и пересоздать) сжигает имя тега.

Ограничение совместимости: включение неизменяемости меняет поведение существующих конвейеров, которые привыкли перезаписывать тег (`--force`) или докладывать ассеты после публикации. Для таких потоков без неё действует только дисциплина «никогда не перезаписывать опубликованный тег» (см. «Лучшие практики»). Подписи и аттестации бинарных артефактов вне GitHub-релизов (cosign, SLSA provenance) — в [Безопасности цепочки поставок](../Security/Supply_Chain_Security/overview.md).

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
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ github.token }}       # GITHUB_TOKEN, не PAT
      - uses: docker/metadata-action@v6
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
- **Нюанс (immutable releases)**: смена флага `--prerelease=false` и правка заметок разрешены, но `gh release upload --clobber` на неизменяемом релизе завершится ошибкой — ассеты после публикации дозагрузить нельзя. Если в модели нужна догрузка (например, финальный PDF-гайд), добавьте его в черновик до публикации либо не делайте релиз неизменяемым.

### Сценарий 4: Публикация npm-пакета из релиза (trusted publishing)

```yaml
  npm:
    needs: publish
    runs-on: ubuntu-latest
    environment: production           # гейт перед внешней публикацией
    permissions:
      contents: read
      id-token: write                  # OIDC-токен для trusted publishing
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          registry-url: https://registry.npmjs.org
      - run: npm ci && npm publish
```

- **Предварительные требования**: на npmjs.com в настройках пакета добавлен Trusted Publisher типа GitHub Actions с указанием репозитория и имени воркфлоу (опционально — окружения). Право `id-token: write` обязательно: без него npm CLI не запросит OIDC-токен.
- Токен-секрет не нужен: `NPM_TOKEN`/`NODE_AUTH_TOKEN` в trusted-publishing потоке не создаётся и не хранится. `registry-url` у setup-node всё ещё указывается — он задаёт реестр и формат `.npmrc`, но авторизация проходит по OIDC.
- Для публичных репозиториев npm **автоматически** прикладывает provenance-аттестацию — отдельный флаг `--provenance` не требуется (для приватных репозиториев provenance не генерируется).
- **Ограничение**: trusted publishing работает из GitHub Actions, GitLab CI/CD и CircleCI; self-hosted раннеры пока не поддерживаются — там остаётся классический `NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}` (плюс `registry-url`).
- **Валидация**: `npm view <pkg> version` возвращает новую версию через минуту после прогона; в логе есть строка `+ <pkg>@<version>` и отметка о provenance.

### Сценарий 5: Аттестация релизных артефактов

Связывает опубликованный артефакт с конкретным воркфлоу-прогоном и SHA коммита. Дополняет встроенные release attestations прозрачной проверкой на стороне потребителя:

```yaml
  attest:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write          # запрос Sigstore-сертификата
      attestations: write      # сохранение аттестации в GitHub
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: dist
          path: dist/
      - name: Attest build provenance
        uses: actions/attest@v4
        with:
          subject-path: 'dist/*'
```

- `actions/attest@v4` — актуальная форма; `actions/attest-build-provenance` с v4 стал тонкой обёрткой над ним, и для новых конвейеров рекомендуется сам `actions/attest`.
- **Валидация**: `gh attestation verify dist/app.tar.gz --repo <owner>/<repo>` подтверждает происхождение файла; в разделе Security → Attestations видна запись с прогоном-источником.
- Теоретическая база механизма (SLSA-предикаты, cosign/Sigstore, проверка цепочки поставок) — в [Безопасности цепочки поставок](../Security/Supply_Chain_Security/overview.md).

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Пуш тега не запускает воркфлоу | Файла воркфлоу нет в коммите, на который указывает тег | Убедиться, что `release.yml` закоммичен до создания тега; пересоздать тег на актуальный коммит |
| HTTP 403 при `gh release create` | Нет `permissions: contents: write` у задачи | Добавить блок permissions (минимально необходимый) |
| `release already exists` | Тег был force-push или релиз создавался ранее | Идемпотентность: `gh release view "$TAG" \|\| gh release create ...` либо явное удаление черновика |
| Загружен пустой набор assets | Glob артефактов ничего не совпал (сборка в другой директории) | Проверять наличие файлов: `[ -e dist/* ] \|\| exit 1` перед загрузкой |
| Двойной релиз при параллельных пушех | Нет concurrency-группы | Группа `release-${{ github.ref_name }}` |
| npm publish падает E409/EOTP | Пакет уже опубликован или требуется 2FA-токен автоматизации | Использовать automation-токен; публикацию делать строго из релизного воркфлоу |
| npm publish: `ENEEDAUTH` / `Unable to authenticate` при OIDC | Нет права `id-token: write` либо Trusted Publisher не настроен для репозитория и имени воркфлоу | Добавить `permissions: id-token: write`; сверить в настройках пакета репозиторий, имя воркфлоу и (если задано) окружение |
| Аттестация падает с `Resource not accessible by integration` | Нет прав `attestations: write` / `id-token: write` | Выдать оба права на задачу `attest` |
| `gh release upload` / изменение ассета отклонено | Релиз объявлен immutable — ассеты зафиксированы после публикации | Заранее приложить все ассеты к черновику; либо отключить immutability (для будущих релизов) |
| Тег не удаляется после удаления релиза | Имя тега immutable-релиза заблокировано от повторного использования | Выбрать новое имя тега (patch-релиз), а не восстанавливать старое |

## Лучшие практики

1. Защищайте паттерн тегов Ruleset'ом: создание тега — такое же привилегированное действие, как запись в ветку.
2. Никогда не перезаписывайте опубликованный тег (`--force`); исправления — новый patch-релиз.
3. Публикуйте чексуммы артефактов; для повышенных требований прикладывайте build provenance через `actions/attest@v4` (или встроенные release attestations неизменяемого релиза).
4. Внешние публикации (реестры, npm) — всегда за environment approval.
5. Draft-first flow: сначала черновик, ручная проверка заметок, затем publish. В режиме immutable-релизов это не рекомендация, а требование — после публикации ассеты уже не добавить.
6. Версию извлекайте из тега, а не из даты/раннера — тег единственный источник правды о версии.
7. Для публикации в npm предпочитайте trusted publishing (OIDC) вместо долгоживущего `NPM_TOKEN`: меньше поверхности для утечки и автоматическая provenance-аттестация для публичных пакетов.
8. Включайте неизменяемость релизов (immutable releases) для критичных проектов — это аппаратная защита от подмены ассетов и перезаписи тега, недоступная при обычной дисциплине.

## Дополнительная информация

- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)** — триггер `release` и типы активности.
- **[Готовые действия](./Marketplace_Actions.md)** — версионирование собственных экшенов (та же семверная схема).
- **[Git-автоматизация](./Git_Automation.md)** — бот-коммиты bump'а версии перед релизом.
- **[Управление секретами](./secrets_management.md)** — OIDC и право `id-token: write`.
- **[Conventional Commits](../Git/git_conventional_commits.md)** — формат коммитов и пример semantic-release.
- **[Реестры Docker](../Docker/docker_registries.md)** — теория хранения и продвижения образов.
- **[Безопасность цепочки поставок](../Security/Supply_Chain_Security/overview.md)** — SLSA provenance, cosign/Sigstore, проверка артефактов.
