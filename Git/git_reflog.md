# Git Reflog — журнал ссылок

**Актуально для:** Git 2.46+

## Определения

**Reflog (Reference log)** — журнал всех перемещений указателя HEAD и веток в локальном репозитории. Каждое изменение HEAD (коммит, checkout, reset, merge, rebase, cherry-pick) записывается в reflog.

**HEAD reflog** — лог перемещений HEAD (самый используемый). Хранится в `.git/logs/HEAD` (формат files) или в `.git/reftable/` (формат reftable, Git 2.45+).

**Branch reflog** — лог перемещений конкретной ветки. Хранится в `.git/logs/refs/heads/<branch>` (files) или в reftable.

**`@{n}`** — синтаксис ссылки на n-ю запись reflog (от HEAD). `HEAD@{0}` — текущее состояние, `HEAD@{1}` — предыдущее.

**`@{time}`** — синтаксис времени: HEAD в указанный момент (`HEAD@{yesterday}`, `HEAD@{2.weeks.ago}`, `HEAD@{2024-01-15 12:00}`).

**Reftable** — новый бинарный формат хранения ссылок и reflog (интегрирован в Git 2.45, выбирается конфигом `init.defaultRefFormat` с 2.47, не экспериментален; станет default в Git 3.0). Обеспечивает атомарные обновления, prefix compression и O(log n) поиск. Включается: `git init --ref-format=reftable`.

---

## Базовые концепции

### Зачем нужен reflog

Reflog — это «страховка» Git. Он записывает каждое движение HEAD и позволяет восстановить:

- Коммиты после `git reset --hard`
- Ветки после `git branch -D`
- Stash после `git stash drop`
- Состояние после неудачного `rebase`, `merge`, `cherry-pick`
- История detached HEAD

### Формат записи reflog

```
<old-sha> <new-sha> <автор> <дата> <действие>: <сообщение>
```

Пример:
```
a1b2c3d e5f6g7h Developer <dev@co.com> 2024-01-15 12:00:00 +0300 checkout: moving from main to feature
```

| Поле | Описание |
|------|----------|
| `old-sha` | SHA до изменения (или `0000...` для создания) |
| `new-sha` | SHA после изменения (или `0000...` для удаления) |
| `автор` | Имя и email из `user.name`/`user.email` |
| `дата` | RFC2822 timestamp с timezone |
| `действие` | `commit`, `checkout`, `reset`, `merge`, `rebase`, `cherry-pick`, `pull`, `clone`, `branch` |
| `сообщение` | Текст коммита или описание операции |

### Срок жизни reflog (garbage collection)

По умолчанию (`gc.reflogExpire`, `gc.reflogExpireUnreachable`):

| Тип записей | Хранение | Настройка |
|-------------|----------|-----------|
| **Reachable** (доступные из текущих веток/тегов) | 90 дней | `gc.reflogExpire` |
| **Unreachable** (висячие коммиты: amend, rebase, reset) | 30 дней | `gc.reflogExpireUnreachable` |
| **Stash** (refs/stash) | 90 дней | `gc.reflogExpire` (под ключом `refs/stash`) |

> **Важно:** Настройки можно переопределить для конкретных refs: `git config gc.reflogExpire.refs/heads/main "180 days"`

### Синтаксис ссылок

| Ссылка | Значение |
|--------|----------|
| `HEAD@{0}` | Текущее состояние HEAD |
| `HEAD@{n}` | n записей назад |
| `HEAD@{yesterday}` | HEAD вчера в это время |
| `HEAD@{2.weeks.ago}` | HEAD 2 недели назад |
| `HEAD@{2024-01-15 12:00}` | HEAD в точный момент |
| `main@{0}` | Текущий коммит ветки main |
| `main@{upstream}` | Коммит отслеживаемой ветки (upstream) |
| `stash@{0}` | Текущий stash |
| `stash@{n}` | n-й stash в стеке |

---

## Операции и команды

| Задача | Команда | Пример |
|--------|---------|--------|
| Просмотр HEAD reflog | `git reflog` | `git reflog -10` |
| Просмотр ветки | `git reflog show <ref>` | `git reflog show main` |
| Просмотр stash | `git reflog show stash` | `git reflog show stash` |
| По времени | `git reflog <ref>@{time}` | `git reflog HEAD@{3.days.ago}` |
| Поиск по сообщению | `git reflog --grep=<pattern>` | `git reflog --grep="reset"` |
| Формат вывода | `git reflog --format=<fmt>` | `git reflog --format="%h %gs"` |
| Удаление записей | `git reflog expire` | `git reflog expire --expire=30.days.ago` |
| Удаление unreachable | `git reflog expire --expire-unreachable=now` | `git reflog expire --expire-unreachable=now --all` |
| Полная очистка | `git reflog expire --expire=now --all` | **ОСТОРОЖНО: необратимо** |
| Список reflogов (reftable) | `git reflog list` | `git reflog list` |
| Проверка существования | `git reflog exists <ref>` | `git reflog exists main` |

---

## Практические сценарии

### Сценарий 1: Просмотр и фильтрация reflog

```bash
# Полный reflog HEAD
git reflog

# Последние 5 записей
git reflog -5

# Только для ветки main
git reflog show main

# Поиск операций reset
git reflog --grep="reset"

# Кастомный формат (хеш + краткое сообщение)
git reflog --format="%h %gs" --date=short

# Все reflog-ы в репозитории (Git 2.45+)
git reflog list
```

### Сценарий 2: Восстановление после `git reset --hard`

```bash
# Ошибка: сбросили ветку и потеряли коммиты
git reset --hard HEAD~3
# → HEAD is now at def5678 last good commit

# Найти потерянный коммит в reflog
git reflog
# → e5f6g7h HEAD@{3}: reset: moving to HEAD~3
# → a1b2c3d HEAD@{4}: commit: feature: add module (ПОТЕРЯННЫЙ!)

# Восстановить ветку на потерянный коммит
git reset --hard HEAD@{4}
# или
git reset --hard a1b2c3d

# ПРОВЕРКА: убедиться, что коммит восстановлен
git log --oneline -5
```

**Edge cases:**
- Reflog хранит SHA-1 коммитов, поэтому даже после `reset --hard` коммит доступен.
- Если прошло >30 дней, `gc` может удалить unreachable коммиты.
- `reset --soft` / `--mixed` не теряют коммиты — они остаются в истории ветки.

### Сценарий 3: Восстановление удалённой ветки

```bash
# Удалили ветку
git branch -D feature-important

# Найти последний коммит ветки через reflog
git reflog | grep "checkout: moving from feature-important"
# → abc1234 HEAD@{12}: checkout: moving from feature-important to main

# Пересоздать ветку на найденном коммите
git branch feature-important abc1234

# АЛЬТЕРНАТИВА: если помните примерное время
git reflog show main@{2.days.ago} | grep feature-important
```

### Сценарий 4: Восстановление stash

```bash
# Удалили stash по ошибке
git stash drop stash@{0}

# Найти через reflog stash
git reflog show stash
# → a1b2c3d stash@{0}: WIP on main: abc1234 feat: new module

# Восстановить как stash
git stash store -m "Recovered stash" a1b2c3d

# Или создать ветку из stash
git branch recovered-stash a1b2c3d
```

### Сценарий 5: Навигация по времени

```bash
# Где был HEAD 3 дня назад?
git reflog show HEAD@{3.days.ago}

# Где была ветка main вчера?
git reflog show main@{yesterday}

# Осмотр проекта 2 недели назад (detached HEAD)
git checkout HEAD@{2.weeks.ago}
# → В состоянии detached HEAD — можно осмотреть файлы
git switch main  # Вернуться обратно
```

### Сценарий 6: Сравнение состояний

```bash
# Что изменилось с прошлого состояния HEAD?
git diff HEAD@{1} HEAD

# Какие коммиты были добавлены?
git log HEAD@{1}..HEAD --oneline

# Диагностика: что сломалось после rebase?
git diff HEAD@{1}..HEAD --stat
```

### Сценарий 7: Восстановление после неудачного rebase

```bash
# Rebase пошёл не так, ветка в плохом состоянии
git rebase main
# → CONFLICT... (решили неверно)

# Найти состояние ПЕРЕД rebase
git reflog
# → a1b2c3d HEAD@{2}: rebase: checkout main
# → e5f6g7h HEAD@{1}: rebase: picking feat: commit 1

# Откатить к pre-rebase состоянию
git reset --hard HEAD@{2}

# АЛЬТЕРНАТИВА: использовать ORIG_HEAD (устанавливается перед rebase/merge)
git reset --hard ORIG_HEAD
```

### Сценарий 8: Откат force-push (локально)

```bash
# Коллега сделал force-push, локальная история расхожилась
git pull --rebase
# → или
git fetch origin
git reset --hard origin/main

# Найти локальное состояние ДО force-push
git reflog
# → a1b2c3d HEAD@{1}: pull: fast-forward
# → e5f6g7h HEAD@{2}: commit: my local work

# Восстановить свою работу
git reset --hard HEAD@{2}
# Затем: git rebase origin/main (или merge)
```

---

## Troubleshooting

### Типичные ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `fatal: ambiguous argument 'HEAD@{n}'` | reflog пуст или запись n не существует | Проверить `git reflog` — записей может быть меньше |
| `fatal: bad revision 'HEAD@{time}'` | Неверный формат времени | Использовать `yesterday`, `2.weeks.ago`, `YYYY-MM-DD HH:MM` |
| Не могу найти коммит | reflog очищен `gc` (прошло >30/90 дней) | Проверить `git fsck --lost-found` / `git fsck --unreachable` |
| `reflog` не показывает squash-коммиты | `squash` не создаёт отдельных записей reflog | Squash коммиты объединяются в один — reflog показывает только результат |
| Reflog растёт бесконечно | Очистка не настроена / `gc.auto=0` | Настроить `git config gc.reflogExpire "30 days"` |
| `git reflog list` не работает | Репозиторий использует формат `files` | Команда доступна только для `reftable` (Git 2.45+) |
| Reflog не синхронизируется между worktrees | Reflog — строго локальный для каждого worktree | Используйте общую конфигурацию (`extensions.worktreeConfig`) или `.git/info/exclude` (расположенный в `$GIT_COMMON_DIR`) для общих настроек |

### Диагностика

```bash
# Проверить настройки gc
git config --get gc.reflogExpire
git config --get gc.reflogExpireUnreachable

# Найти висячие объекты (если reflog не помог)
git fsck --unreachable --no-reflogs 2>/dev/null | grep commit

# Показать все reflog-файлы (формат files)
ls -la .git/logs/refs/heads/
ls -la .git/logs/HEAD

# Проверить формат репозитория
git config --get core.repositoryFormatVersion
# 1 = files, 2 = reftable (experimental)
```

---

## Best Practices для DevOps/SRE/SysAdmin

### 1. Настройка сроков хранения для CI/CD

```bash
# Для CI-окружений: сократить хранение (экономия диска)
git config gc.reflogExpire "7 days"
git config gc.reflogExpireUnreachable "1 day"

# Для production-репозиториев: увеличить для аудита
git config gc.reflogExpire "180 days"
git config gc.reflogExpireUnreachable "30 days"
```

### 2. Автоматизация очистки в cron/systemd

```bash
# /etc/cron.daily/git-gc-reflog
#!/bin/bash
for repo in /var/git/repos/*; do
    [ -d "$repo/.git" ] || continue
    git -C "$repo" reflog expire --expire=30.days.ago --all
    git -C "$repo" gc --auto
done
```

### 3. Мониторинг размера reflog

```bash
# Размер reflog директории
du -sh .git/logs/

# Количество записей
git reflog --format="%h" | wc -l

# Топ-10 самых больших reflog файлов (format=files)
find .git/logs -type f -exec wc -l {} + | sort -rn | head -10
```

### 4. Интеграция с backup/DR

```bash
# Backup reflog перед опасными операциями
cp -r .git/logs /backup/git-reflog-$(date +%F-%H%M)

# Восстановление из backup
cp -r /backup/git-reflog-2024-01-15-1200/.git/logs .git/
```

### 5. Reftable для больших репозиториев (Git 2.45+)

```bash
# Новый репозиторий с reftable
git init --ref-format=reftable my-repo

# Миграция (экспериментально, ТРЕБУЕТ БЭКАПА)
# git refs migrate --ref-format=reftable
# ⚠️ НЕ работает с reflog и worktrees — см. git-refs(1)
```

### 6. Безопасность и аудит

- Reflog содержит **имена авторов и email** — учитывайте при передаче репозитория третьим лицам
- `git reflog` показывает **всю локальную историю** включая отменённые коммиты с секретами
- После утечки секретов: `git reflog expire --expire=now --all` + `git gc --prune=now` (но лучше `git-filter-repo`)

---

## Дополнительная информация

### Связанные темы

- [Внутреннее устройство Git](./git_internals.md) — структура `.git/logs/` и reftable, объектная модель
- [Git Basics](./git_basics.md) — архитектура трёх деревьев для понимания состояний HEAD
- [Git History Manipulation](./git_history_manipulation.md) — reset, revert, recover и работа с потерянными коммитами
- [Git Troubleshooting](./git_troubleshooting.md) — восстановление после `reset --hard` и удаления веток
- [Git Stash](./git_stash.md) — работа со stash и его reflog
- [Git Branching](./git_branching.md) — восстановление удалённых веток через reflog

### Официальные ресурсы

- **Git Reflog Documentation:** [git-scm.com/docs/git-reflog](https://git-scm.com/docs/git-reflog)
- **Git GC Configuration:** [git-scm.com/docs/git-config#Documentation/git-config.txt-gcreflogExpire](https://git-scm.com/docs/git-config#Documentation/git-config.txt-gcreflogExpire)
- **Reftable Format:** [git-scm.com/docs/reftable](https://git-scm.com/docs/reftable)
- **Pro Git Book — Maintenance:** [git-scm.com/book/ru/v2/Инструменты-Git-Обслуживание-и-восстановление-данных](https://git-scm.com/book/ru/v2/Инструменты-Git-Обслуживание-и-восстановление-данных)

### Версионные изменения

| Версия | Изменение |
|--------|-----------|
| Git 2.45 | Введён формат **reftable** (экспериментально), команда `git reflog list` |
| Git 2.46 | Стабилизация reftable, `git refs migrate` (без reflog/worktrees) |
| Git 2.50+ | Улучшения производительности reftable, патчи по хранению expiry опций |