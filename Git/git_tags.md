# Git Tags — разметка версий

## Определения

**Git Tag (Тег)** — неизменяемая ссылка (ref), указывающая на конкретный коммит в истории Git. Теги используются для фиксации точек релиза, версий и значимых событий в жизненном цикле проекта.

**Annotated tag (Аннотированный тег)** — полноценный объект Git, содержащий: имя автора, email, дату, сообщение и необязательное сообщение (message). Может быть подписана (GPG/SSH). Хранится в `refs/tags/<name>`.

**Lightweight tag (Лёгкий тег)** — простая ссылка на коммит, аналогичная ветке, но без автоматического перемещения. Не создаёт отдельного объекта в базе Git. Хранится в `refs/tags/<name>`.

**Semantic Versioning (SemVer)** — стандарт версионирования `MAJOR.MINOR.PATCH`, где MAJOR — ломающие изменения, MINOR — обратно совместимые, PATCH — исправления.

---

## Базовые концепции

### Когда использовать теги

| Сценарий | Тег | Комментарий |
| :--- | :--- | :--- |
| Релиз версии 1.0.0 | `git tag -a v1.0.0 -m "Release 1.0.0"` | Аннотированный — для SemVer и CI/CD |
| Быстрая закладка точки | `git tag checkpoint-1` | Лёгкий — для личных целей |
| Обозначение.breaking change | `git tag -a v2.0.0 -m "BREAKING: API v2"` | Аннотированный — для Changelog |
| Маркировка bad commit | `git tag bad-com` | Лёгкий — для bisect |

### Разница между annotated и lightweight

| Критерий | Annotated | Lightweight |
| :--- | :--- | :--- |
| Создаёт объект Git | Да (tag object) | Нет (только ref) |
| Хранит сообщение | Да (author, date, message) | Нет |
| Поддерживает подпись | Да (GPG/SSH) | Нет |
| Доступен через `git tag -n` | Да | Нет (покажет коммит) |
| Рекомендуется для релизов | Да | Нет |

### Физическая реализация

```
refs/tags/v1.0.0 → SHA-1 коммита (lightweight)
                или → SHA-1 объекта tag (annotated)

.git/refs/tags/
├── v1.0.0          → a1b2c3d...  (lightweight)
└── v2.0.0          → e4f5g6h...  (annotated)

.git/objects/
├── e4/...  → tag object (v2.0.0, содержит message, author, date)
```

---

## Практические сценарии

### Сценарий 1: Создание аннотированного тега для релиза

```bash
# Создать аннотированный тег на текущем коммите
git tag -a v1.0.0 -m "Release 1.0.0: first stable version"

# Указать конкретный коммит
git tag -a v1.0.0 abc1234 -m "Release 1.0.0"
```

**Валидация:**
```bash
# Просмотреть тег и его сообщение
git tag -n1 v1.0.0
# → v1.0.0            Release 1.0.0: first stable version

# Проверить, что это annotated tag
git cat-file -t v1.0.0
# → tag
```

**Edge cases:**
- Тег с уже существующим именем будет отклонён (`fatal: tag 'v1.0.0' already exists`).
- Для перезаписи используйте `git tag -f -a v1.0.0 -m "..."` (опасно: перезаписывает ссылку).

### Сценарий 2: Отправка тегов в удалённый репозиторий

По умолчанию `git push` **не отправляет** теги — это的安全ое поведение.

```bash
# Отправить один конкретный тег
git push origin v1.0.0

# Отправить ВСЕ локальные теги
git push origin --tags

# Отправить тегы через --follow-tags (только annotated, на текущем HEAD)
git push --follow-tags
```

**Валидация:**
```bash
# Проверить удалённые теги
git ls-remote --tags origin
# → a1b2c3d4e5f6...  refs/tags/v1.0.0
```

**Edge cases:**
- Если тег уже существует на сервере, push будет отклонён. Используйте `--force` для перезаписи (опасно).

### Сценарий 3: Удаление тегов

```bash
# Удалить локальный тег
git tag -d v1.0.0

# Удалить с сервера
git push origin --delete v1.0.0
# или
git push origin :refs/tags/v1.0.0
```

**Валидация:**
```bash
# Убедиться, что тег удалён
git tag -l | grep v1.0.0
# → (пусто)
```

**Edge cases:**
- Удаление тега не удаляет коммит — он остаётся в истории.
- Если тег был запушен и его удалили, коллеги увидят ошибку при `fetch`. Им нужно выполнить `git fetch --prune origin "+refs/tags/v1.0.0:refs/tags/v1.0.0"`.

### Сценарий 4: Переименование тега

Git не поддерживает переименование тегов напрямую. Нужно удалить и создать заново:

```bash
# Удалить старый тег
git tag -d v1.0.0

# Создать новый на том же коммите
git tag -a v1.0.1 -m "Release 1.0.1"

# Обновить на сервере
git push origin :refs/tags/v1.0.0
git push origin v1.0.1
```

### Сценарий 5: Просмотр тегов

```bash
# Список всех тегов
git tag -l

# Теги по паттерну
git tag -l "v1.*"
# → v1.0.0
# → v1.1.0

# Подробная информация
git show v1.0.0
# → tag v1.0.0
# → Tagger: Developer <dev@company.com>
# → Date: Mon Jan 1 12:00:00 2024 +0300
# → Release 1.0.0

# Сортировка по дате создания
git tag --sort=-creatordate | head -5
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
- Работа в detached HEAD может привести к потере коммитов. Всегда создавайте ветку.

### Сценарий 7: Сравнение тегов

```bash
# Разница между двумя релизами
git diff v1.0.0..v2.0.0 --stat

# Список коммитов между релизами
git log v1.0.0..v2.0.0 --oneline

# Только коммиты, затрагивающие определённый каталог
git log v1.0.0..v2.0.0 --oneline -- src/
```

### Сценарий 8: Интеграция с CI/CD

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
      - name: Create Release
        run: |
          VERSION=${GITHUB_REF#refs/tags/}
          echo "Building version $VERSION"
          # Сборка, тесты, публикация
```

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: tag 'v1.0.0' already exists` | Тег с таким именем уже существует | Удалить (`git tag -d`) или использовать `-f` для перезаписи |
| Тег не отправляется при push | `git push` не отправляет теги по умолчанию | Использовать `git push origin <tag>` или `--tags` |
| Коллеги не видят удалённый тег | Кэш удалённых ссылок не обновлён | `git fetch --prune origin "+refs/tags/*:refs/tags/*"` |
| `git describe` не находит тег | Нет тегов в истории | Создать тег на ближайшем релизном коммите |
| Тег указывает на несуществующий коммит | Коммит был удалён через `filter-repo` или `rebase` | Пересоздать тег на актуальном коммите |

### Best Practices

1. **Используйте annotated теги для релизов** — они содержат метаданные и поддерживают подпись.
2. **Следуйте SemVer** — `vMAJOR.MINOR.PATCH` для предсказуемости.
3. **Не используйте `-f` без необходимости** — перезапись тегов ломает ссылки у коллег.
4. **Отправляйте теги отдельно** — `git push --tags` только когда готовы к релизу.
5. **Подписывайте теги** — `git tag -s` для аутентификации релизов.
6. **Документируйте теги** — используйте `-m` для аннотированных тегов.
7. **Удаляйте старые теги** — не держите экспериментальные теги вечно.

---

## Дополнительная информация

### Связанные темы

- [Ветвление в Git](./git_branching.md) — разница между ветками и тегами, когда использовать каждый.
- [Conventional Commits](./git_conventional_commits.md) — формат сообщений для автоматических тегов и changelog.
- [Современные команды](./git_commands_modern.md) — `git describe` для генерации версий на основе тегов.
- [Git Hooks](./git_hooks.md) — автоматизация при создании тегов и пуше.
- [Синхронизация репозиториев](./git_synchronization.md) — push/fetch тегов, --follow-tags.
- [Внутреннее устройство Git](./git_internals.md) — как Git хранит теги (annotated vs lightweight объекты).

### Официальные ресурсы

- **Git Tag Documentation:** [git-scm.com/docs/git-tag](https://git-scm.com/docs/git-tag)
- **Pro Git Book — Tagging:** [git-scm.com/book/ru/v2/Git-инструменты-Разметка-версий](https://git-scm.com/book/ru/v2/Git-инструменты-Разметка-версий)
- **Semantic Versioning:** [semver.org](https://semver.org/)
