# Git Tags — разметка версий

**Актуально для:** Git 2.56.0

---

## Определения

**Git Tag (Тег)** — неизменяемая ссылка (ref), указывающая на конкретный коммит в истории Git. Теги используются для фиксации точек релиза, версий и значимых событий в жизненном цикле проекта. Поскольку ветки движутся при новых коммитах, а теги — нет, они гарантируют неизменяемую точку привязки к истории.

**Annotated tag (Аннотированный тег)** — полноценный объект Git типа `tag`, содержащий: имя автора (tagger), email, дату создания, сообщение и SHA-1 объекта, на который указывает (обычно коммит, но может быть другим объектом). Может быть подписан (GPG или SSH). Сериализуется в `.git/objects/<sha>/`. Ссылка хранится в `refs/tags/<name>`.

**Lightweight tag (Лёгкий тег)** — простая ссылка в `refs/tags/<name>`, указывающая прямо на SHA-1 коммита. Не создаёт отдельный объект `tag` в базе данных. Не поддерживает подпись и метаданные.

**Semantic Versioning (SemVer)** — стандарт версионирования `MAJOR.MINOR.PATCH`, где `MAJOR` — ломающие изменения, `MINOR` — обратно совместимые добавления, `PATCH` — исправления багов. Спецификация: [semver.org](https://semver.org/).

**Detached HEAD** — состояние, когда `HEAD` указывает не на ветку, а прямо на коммит (или тег). Коммиты, сделанные в этом состоянии, не принадлежат ни одной ветке и теряются при смене ветки без явного создания ветки.

---

## Базовые концепции

### Когда использовать теги

| Сценарий | Тег | Комментарий |
| :--- | :--- | :--- |
| Релиз версии 1.0.0 | `git tag -a v1.0.0 -m "Release 1.0.0"` | Аннотированный — для SemVer и CI/CD |
| Быстрая закладка точки | `git tag checkpoint-1` | Лёгкий — для личных целей |
| Обозначение breaking change | `git tag -a v2.0.0 -m "BREAKING: API v2"` | Аннотированный — для changelog |
| Маркировка bad commit | `git tag bad-commit-abc` | Лёгкий — для bisect |

### Разница между annotated и lightweight

| Критерий | Annotated | Lightweight |
| :--- | :--- | :--- |
| Создаёт объект Git | Да (tag object) | Нет (только ref) |
| Хранит сообщение | Да (tagger, date, message) | Нет |
| Поддерживает подпись | Да (GPG/SSH) | Нет |
| Доступен через `git tag -n` | Да | Нет (покажет коммит) |
| Поддерживается `--follow-tags` | Да | Нет |
| Рекомендуется для релизов | Да | Нет |

### Физическая реализация

```
refs/tags/v1.0.0 → SHA-1 коммита (lightweight)
                 или → SHA-1 объекта tag (annotated)

.git/refs/tags/
├── v1.0.0          → a1b2c3d4e5f6...  (lightweight)
└── v2.0.0          → e4f5e6a7b8c9...  (annotated, tag object)

.git/objects/
├── e4f5e6a7b8c9...  → tag object
│     object e4f5e6a7b8c9...  (commit SHA)
│     type commit
│     tag v2.0.0
│     tagger Developer <dev@company.com> 1718000000 +0300
│
└── a1b2c3d4e5f6...  → commit object
```

**Механизм создания:** при выполнении `git tag -a v2.0.0` Git создаёт объект `tag` в объектном хранилище, затем запись `v2.0.0` в `.git/refs/tags/v2.0.0` указывает на SHA-1 этого объекта. Для lightweight-тега ссылка пишется напрямую на SHA-1 коммита — объект `tag` не создаётся.

**Цепочка deref:** `refs/tags/v2.0.0` → tag object → commit object → tree object. Команда `git rev-parse v2.0.0` автоматически следует по этой цепочке и возвращает SHA-1 конечного коммита.

### Правила именования тегов

Имена тегов в Git 2.56.0 должны соответствовать следующим правилам:

- Могут содержать: буквы (a-z, A-Z), цифры (0-9), `-`, `_`, `.`, `/`
- Не должны начинаться с `-` или `.`
- Не должны содержать: `..`, `~`, `^`, `:`, `?`, `*`, `[`, `\`, пробель, `@{`, управляющие символы
- Не должны оканчиваться на `.lock`
- Чувствительны к регистру: `V1.0.0` ≠ `v1.0.0`
- Должны быть уникальны в пределах репозитория

**Рекомендация:** используйте префикс `v` для версий: `v1.0.0`, `v2.1.3-rc1`.

---

## Операции и команды

| Команда | Назначение | Пример вывода |
| :--- | :--- | :--- |
| `git tag -a v1.0.0 -m "msg"` | Создать аннотированный тег | *(пусто)* |
| `git tag v1.0.0` | Создать лёгкий тег | *(пусто)* |
| `git tag -a v1.0.0 <commit>` | Тег на конкретном коммите | *(пусто)* |
| `git tag -s v1.0.0 -m "msg"` | Подписанный GPG тег | *(пусто)* |
| `git tag -v v1.0.0` | Проверить подпись | `Good signature from "Name <email>"` |
| `git tag -l` | Список всех тегов | `v1.0.0\nv1.1.0\nv2.0.0` |
| `git tag -l "v1.*"` | Фильтр по паттерну | `v1.0.0\nv1.1.0` |
| `git tag -n1 v1.0.0` | Показать 1 строку сообщения | `v1.0.0            Release 1.0.0` |
| `git tag --sort=-creatordate` | Сортировка по дате создания | `v2.0.0\nv1.1.0\nv1.0.0` |
| `git tag --sort=-v:refname` | Сортировка по семантической версии | `v2.0.0\nv1.1.0\nv1.0.0` |
| `git cat-file -t v1.0.0` | Тип объекта тега | `tag` (annotated) / `commit` (lightweight) |
| `git cat-file -p v1.0.0` | Содержимое tag object | `object <sha>\n type commit\n tag v1.0.0\n tagger ...` |
| `git show v1.0.0` | Полная информация о теге | `tag v1.0.0\nTagger: ...\nDate: ...\n\nmsg\n\ncommit ...` |
| `git tag -d v1.0.0` | Удалить локальный тег | `Deleted tag 'v1.0.0'` |
| `git push origin v1.0.0` | Отправить один тег | *(стандартный push output)* |
| `git push origin --tags` | Отправить все теги | *(стандартный push output)* |
| `git push --follow-tags` | Отправить annotated теги на текущей ветке | *(стандартный push output)* |
| `git push origin --delete v1.0.0` | Удалить удалённый тег | `delete  ref: refs/tags/v1.0.0` |
| `git ls-remote --tags origin` | Список удалённых тегов | `<sha> refs/tags/v1.0.0` |
| `git describe --tags --abbrev=0` | Ближайший тег к HEAD | `v1.0.0` |
| `git for-each-ref --tags` | Список тегов для скриптов | `<sha>\trefs/tags/v1.0.0\tv1.0.0` |
| `git checkout v1.0.0` | Переключиться на тег (detached HEAD) | `HEAD detached at v1.0.0` |

---

## Практические сценарии

### Сценарий 1: Создание аннотированного тега для релиза

```bash
# Создать аннотированный тег на текущем коммите
git tag -a v1.0.0 -m "Release 1.0.0: first stable version"
# → (без вывода при успехе)

# Указать конкретный коммит
git tag -a v1.0.0 abc1234 -m "Release 1.0.0"
# → (без вывода при успеха)
```

**Валидация:**
```bash
# Просмотреть тег и его сообщение
git tag -n1 v1.0.0
# → v1.0.0            Release 1.0.0: first stable version

# Проверить, что это annotated tag
git cat-file -t v1.0.0
# → tag

# Просмотреть содержимое tag object
git cat-file -p v1.0.0
# → object e4f5e6a7b8c9d012...
# → type commit
# → tag v1.0.0
# → tagger Developer <dev@company.com> 1718000000 +0300
# →
# → Release 1.0.0: first stable version
```

**Edge cases:**
- Тег с уже существующим именем будет отклонён: `fatal: tag 'v1.0.0' already exists`.
- Для перезаписи используйте `git tag -f -a v1.0.0 -m "..."` (осторожно: перезаписывает ссылку, коллеги могут сломать свои ветки).

### Сценарий 2: Отправка тегов в удалённый репозиторий

По умолчанию `git push` не отправляет теги — это намеренно безопасное поведение, предотвращающее случайные публичные релизы.

```bash
# Отправить один конкретный тег
git push origin v1.0.0

# Отправить ВСЕ локальные тега
git push origin --tags

# Отправить только annotated теги, достижимые из текущей ветки
git push --follow-tags

# Отправить тег по шаблону
git push origin "v1.*"
```

**Валидация:**
```bash
# Проверить удалённые теги
git ls-remote --tags origin
# → e4f5e6a7b8c9d012...  refs/tags/v1.0.0
```

**Версия для CI/CD pipeline:**
```yaml
# GitHub Actions: запуск при пуше тега
on:
  push:
    tags:
      - "v*"

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Get version
        run: |
          VERSION=${GITHUB_REF#refs/tags/}
          echo "Building version $VERSION"
```

**Edge cases:**
- Если тег уже существует на сервере, `git push` будет отклонён. Используйте `--force` ТОЛЬКО если уверены, что никто не завязался на существующий тег.
- `--follow-tags` отправляет только annotated теги (не lightweight), достижимые из коммитов, которые вы отправляете в данный push.

### Сценарий 3: Удаление тегов

```bash
# Удалить локальный тег
git tag -d v1.0.0
# → Deleted tag 'v1.0.0'

# Удалить локальный тег (альтернативный синтаксис)
git tag -d v1.0.0 v1.0.1

# Удалить с сервера
git push origin --delete v1.0.0
# или
git push origin :refs/tags/v1.0.0
```

**Валидация:**
```bash
# Убедиться, что тег удалён локально
git tag -l | grep v1.0.0
# → (пусто)

# Убедиться, что тег удалён на сервере
git ls-remote --tags origin v1.0.0
# → (пусто)
```

**Edge cases:**
- Удаление тега не удаляет коммит — он остаётся в истории и доступен через SHA-1.
- Если тег был запушен и его удалили, коллеги увидят ошибку при `git fetch`. Им нужно выполнить:
  ```bash
  git fetch --prune origin "+refs/tags/v1.0.0:refs/tags/v1.0.0"
  ```
- Для удаления всех удалённых тегов локально: `git fetch --prune origin`
- **Важно:** если тег уже использован в пайплайне (артефакты, докер-образы), удаление тега сломает воспроизводимость сборок. Всегда проверяйте, что тег не используется, прежде чать удалять.

### Сценарий 4: Переименование тега

Git не поддерживает переименование тегов напрямую. Нужно удалить и создать заново:

```bash
# Удалить старый тег локально и на сервере
git tag -d v1.0.0
git push origin --delete v1.0.0

# Создать новый на том же коммите
git tag -a v1.0.1 $(git rev-parse v1.0.0 2>/dev/null || echo HEAD) -m "Release 1.0.1"

# Обновить на сервере
git push origin v1.0.1
```

> **Предупреждение:** если старый тег уже был опубликован и использован, переименование создаст "dead" ссылку. Лучше создавайте новый тег и явно помечайте старый как устаревший.

### Сценарий 5: Просмотр и поиск тегов

```bash
# Список всех тегов
git tag -l

# Теги по паттерну (glob)
git tag -l "v1.*"
# → v1.0.0
# → v1.1.0

# Подробная информация о теге
git show v1.0.0
# → tag v1.0.0
# → Tagger: Developer <dev@company.com>
# → Date: Mon Jan 1 12:00:00 2024 +0300
# → Release 1.0.0
# → commit e4f5e6a7b8c9... (Release 1.0.0)
# →  ...

# Сортировка по дате создания (новые сначала)
git tag --sort=-creatordate | head -5

# Сортировка по семантической версии (Git 2.56.0)
git tag --sort=-v:refname
# → v2.0.0
# → v1.10.0
# → v1.9.0

# Список удалённых тегов без локального клона
git ls-remote --tags origin

# Список тегов для скриптов (формат: <sha>\t<ref>\t<shortname>)
git for-each-ref --format='%(objectname:short) %(refname:short)' --tags
# → a1b2c3d v1.0.0
# → e4f5e6a v2.0.0
```

### Сценарий 6: Переход на тег (detached HEAD)

```bash
# Переключиться на тег (в detached HEAD)
git checkout v1.0.0

# Создать ветку из тега (безопаснее)
git switch -c hotfix-from-v1 v1.0.0
```

**Валидация:**
```bash
git status
# → HEAD detached at v1.0.0

git log --oneline -1
# → a1b2c3d Release 1.0.0
```

**Edge cases:**
- Работа в detached HEAD может привести к потере коммитов. Всегда создавайте ветку перед внесением изменений.
- `git checkout <tag>` deprecated-совместим с `git switch --detach <tag>` в Git 2.56.0. Предпочтительнее `git switch` для новых workflow.

### Сценарий 7: Сравнение тегов

```bash
# Разница между двумя релизами (статистика)
git diff v1.0.0..v2.0.0 --stat

# Список коммитов между релизами
git log v1.0.0..v2.0.0 --oneline

# Только коммиты, затрагивающие определённый каталог
git log v1.0.0..v2.0.0 --oneline -- src/

# Сгенерировать changelog между тегами
git log v1.0.0..v2.0.0 --pretty=format:"- %s (%an)"
```

### Сценарий 8: Генерация версий для сборок (git describe)

```bash
# Получить ближайший тег к текущему коммиту
git describe --tags
# → v1.0.0-3-ga1b2c3d

# Только имя тега без суффикса
git describe --tags --abbrev=0
# → v1.0.0

# В CI/CD для генерации номера сборки
VERSION=$(git describe --tags)
BUILD_VERSION="${VERSION/-g/+g}"
echo "Build version: $BUILD_VERSION"
```

**Механизм:** `git describe` ищет ближайший достижимый тег, затем считает количество коммитов после него и добавляет суффикс `-<N>-g<short-sha>`. Если текущий коммит является тегом, выводит только имя тега без суффикса.

### Сценарий 9: Подпись и проверка тегов (GPG/SSH)

```bash
# Создать подписанный тег (требует настройки GPG или SSH signing)
git tag -s v1.0.0 -m "Release 1.0.0"

# Проверить подпись тега
git tag -v v1.0.0
# → gpg: Signature made ...
# → gpg:                using RSA key ...
# → gpg: Good signature from "Developer <dev@company.com>"
```

**Требования:**
- GPG: настройте `user.signingkey` и `pinentry` в git config
- SSH: установите `gpg.format=ssh`, `user.signingkey=~/.ssh/id_ed25519.pub`
- **DevOps/SRE:** в CI/CD добавляйте шаг `git tag -v` перед публикацией артефактов, чтобы гарантировать подлинность релиза

### Сценарий 10: Интеграция с CI/CD — автоматизация релизов

```yaml
# GitHub Actions: автоматический release при пуше тега
on:
  push:
    tags:
      - "v*"

jobs:
  build-and-release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Extract version
        run: echo "VERSION=${GITHUB_REF#refs/tags/}" >> $GITHUB_ENV

      - name: Verify tag signature
        run: git tag -v "$VERSION"

      - name: Build
        run: |
          echo "Building $VERSION"
          # ... сборка ...

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ env.VERSION }}
          generate_release_notes: true
```

**Лучшие практики для CI/CD:**
- Используйте `fetch-depth: 0` для полной истории (нужно для changelog)
- Добавляйте шаг `git tag -v` для проверки подписи перед релизом
- Используйте `--sort=-v:refname` для выбора последнего тега в пайплайне
- Автоматически генерируйте changelog через `git log $(git describe --tags --abbrev=0)..HEAD`

---

## Операции и администрирование (DevOps / SRE)

### Управление тегами на сервере (GitLab / GitHub)

Теги — это не только локальная концепция. Серверы Git-хостинга поддерживают защиту тегов:

**GitLab — Protected Tags:**
```
Settings → Repository → Protected tags
```
- Теги, попадающие в паттерн (например, `v*`), можно защитить от удаления и перезаписи
- Только пользователи с ролью Maintainer или Owner могут пушить/удалять такие теги
- Настраивается на уровне проекта

**GitHub — Tag protection:**
```
Settings → Code and automation → Tags → Tag protection rules
```
- Аналогичная защита: блокирует force-push и удаление тегов по паттерну
- Требует GitHub Enterprise или репозитория с поддержкой правил

> **SRE принцип:** production-релизные теги (`v*` в production-репозиториях) должны быть защищены на сервере, даже если локальная политика допускает `--force`.

### Очистка старых и экспериментальных тегов

Накопление экспериментальных и отменённых тегов увеличивает время `git fetch` и загрязняет историю.

```bash
# Найти все локальные теги, отсутствующие на удалённом
git tag -l | while read tag; do
  echo "$tag: $(git rev-parse "$tag" 2>/dev/null || echo 'broken')"
done

# Удалить все локальные теги, отсутствующие на origin
comm -23 \
  <(git tag -l | sort) \
  <(git ls-remote --tags origin | sed 's/.*refs\/tags\///' | grep -v '{}' | sort -u) \
  | xargs -r git tag -d
# → Deleted tag 'exp-experiment'
# → ...

# Полностью синхронизировать удалённые теги
git fetch --prune origin
```

**CI/CD cleanup job (GitHub Actions):**
```yaml
name: Cleanup stale local tags
on:
  schedule:
    - cron: '0 2 * * 1'  # каждое понедельник в 02:00
  workflow_dispatch:

jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Prune stale local tags
        run: |
          git fetch --prune origin
          # удалить только local, синхронизация через fetch --prune
```

### Мониторинг и аудит тегов

```bash
# Найти теги, указывающие на удалённые (dangling) коммиты
git for-each-ref --format='%(refname:short) %(objectname:short)' refs/tags | while read tag sha; do
  if ! git cat-file -e "$sha" 2>/dev/null; then
    echo "DANGLING: $tag → $sha"
  fi
done

# Аудит подписей: найти неподписанные release-теги
git for-each-ref --format='%(refname:short) %(contents:signature)' refs/tags/v* | grep -v 'BEGIN PGP'

# Проверить целостность тегов после filter-branch / filter-repo
git tag -l | xargs -I{} git cat-file -t {} 2>&1 | grep -v "^{tag\|commit}"
```

**SRE alert rule (GitLab/GitHub webhook → alerting):**
> Alert: `tag_deleted` event on protected pattern `v*` — possible accidental deletion of production release tag.

---

## Управление проблемами

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: tag 'v1.0.0' already exists` | Тег с таким именем уже существует | Удалить (`git tag -d`) или использовать `-f` для перезаписи |
| Тег не отправляется при push | `git push` не отправляет теги по умолчанию | Использовать `git push origin <tag>` или `--tags` |
| Коллеги не видят удалённый тег | Кэш удалённых ссылок не обновлён | `git fetch --prune origin "+refs/tags/*:refs/tags/*"` |
| `git describe` не находит тег | Нет тегов в истории до HEAD | Создать тег на ближайшем релизном коммите |
| Тег указывает на несуществующий коммит | Коммит был удалён через `filter-repo` или `filter-branch` | Пересоздать тег на актуальном коммите |
| `error: failed to push some refs` | Тег уже существует на сервере с другим SHA | Удалить на сервере (`git push --delete`) или использовать `--force` |
| `gpg: Signature made ...` + `BAD signature` | Тег подписан с истекшим или неверным ключом | Переэкспортировать ключ, проверить дату, переподписать |

### Диагностика

```bash
# Проверить, что тег существует и какого типа
git cat-file -t v1.0.0
# → tag (annotated) или commit (lightweight)

# Проверить SHA, на который указывает тег
git rev-parse v1.0.0

# Проверить, является ли тег annotated и подписан ли
git for-each-ref --format='%(refname:short) %(objecttype) %(contents:signature)' refs/tags/v1.0.0

# Проверить удалённые теги без локального клона
git ls-remote --tags origin "v*"

# Проверить целостность: тег указывает на существующий объект?
git cat-file -e "$(git rev-parse v1.0.0)" && echo "OK" || echo "BROKEN"
```

---

## Best Practices

1. **Используйте annotated теги для релизов** — они содержат метаданные (tagger, date) и поддерживают подпись.
2. **Следуйте SemVer** — `vMAJOR.MINOR.PATCH` для предсказуемости (`v1.2.3`, `v2.0.0-rc1`).
3. **Не используйте `-f` без необходимости** — перезапись тегов ломает ссылки у коллег и CI/CD.
4. **Отправляйте теги отдельно** — `git push origin <tag>`, а не `--tags`, чтобы не публиковать экспериментальные теги.
5. **Подписывайте теги** — `git tag -s` для аутентификации релизов; проверяйте подписи в CI/CD (`git tag -v`).
6. **Документируйте теги** — используйте `-m` для аннотированных тегов с понятным сообщением.
7. **Удаляйте старые теги** — не держите экспериментальные теги; используйте `git fetch --prune` для синхронизации.
8. **Защищайте релизные теги на сервере** — настройте protected tags (GitLab/GitHub) для паттерна `v*`.
9. **Используйте `git describe` для версий сборок** — `git describe --tags --abbrev=0` в CI для получения текущей версии.
10. **Проверяйте целостность тегов после операций переписывания истории** — `git cat-file -e <sha>` после `filter-repo`.

---

## Очистка и обслуживание

```bash
# Удалить все локальные теги, которых нет на origin
git tag -l | while read tag; do
  git ls-remote --tags origin "$tag" >/dev/null 2>&1 || git tag -d "$tag"
done

# Синхронизировать удалённые теги (удалить отсутствующие локально)
git fetch --prune origin

# Очистить "мёртвые" теги (dangling refs) после filter-repo
git for-each-ref --format='%(refname)' refs/tags | \
  xargs -I{} git cat-file -e "$(git rev-parse {} 2>/dev/null)" 2>/dev/null || \
  git tag -d "$(basename {})"
```

---

## Дополнительная информация

### Связанные темы

- [Ветвление в Git](./git_branching.md) — разница между ветками и тегами, когда использовать каждый.
- [Conventional Commits](./git_conventional_commits.md) — формат сообщений для автоматических тегов и changelog.
- [Современные команды](./git_commands_modern.md) — `git describe` для генерации версий на основе тегов.
- [Git Hooks](./git_hooks.md) — автоматизация при создании тегов и пуше.
- [Синхронизация репозиториев](./git_synchronization.md) — push/fetch тегов, --follow-tags.
- [Внутреннее устройство Git](./git_internals.md) — как Git хранит теги (annotated vs lightweight объекты).
- [Основы Git](./git_basics.md) — вводный раздел по тегам (Сценарий 8: Работа с тегами).

### Официальные ресурсы

- **Git Tag Documentation:** [git-scm.com/docs/git-tag](https://git-scm.com/docs/git-tag)
- **Pro Git Book — Tagging:** [git-scm.com/book/ru/v2/Git-инструменты-Разметка-версий](https://git-scm.com/book/ru/v2/Git-инструменты-Разметка-версий)
- **Semantic Versioning:** [semver.org](https://semver.org/)