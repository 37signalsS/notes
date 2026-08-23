# Git Reflog — журнал ссылок

## Определения

**Reflog (Reference log)** — журнал всех перемещений указателя HEAD и веток в локальном репозитории. Каждое изменение HEAD (коммит, checkout, reset, merge, rebase) записывается в reflog.

**HEAD reflog** — лог перемещений HEAD (самый используемый). Хранится в `.git/logs/HEAD`.

**Branch reflog** — лог перемещений конкретной ветки. Хранится в `.git/logs/refs/heads/<branch>`.

**`@{n}`** — синтаксис ссылки на n-ю запись reflog (от HEAD). `HEAD@{0}` — текущее состояние, `HEAD@{1}` — предыдущее.

**`@{yesterday}`** — синтаксис времени: HEAD в指定的时间点.

---

## Базовые концепции

### Зачем нужен reflog

Reflog — это «страховка» Git. Он записывает каждое движение HEAD и позволяет восстановить:

- Коммиты после `git reset --hard`
- Ветки после `git branch -D`
- Stash после `git stash drop`
- Состояние после неудачного rebase

### Формат записи reflog

```
<old-sha> <new-sha> <автор> <дата> <сообщение>
```

Пример:
```
a1b2c3d e5f6g7h Developer <dev@co.com> 2024-01-15 12:00:00 +0300 checkout: moving from main to feature
```

### Срок жизни reflog

| Тип | Хранение | По умолчанию |
| :--- | :--- | :--- |
| Reachable (доступные из веток) | 90 дней | `gc.reflogExpire` |
| Unreachable (висячие коммиты) | 30 дней | `gc.reflogExpireUnreachable` |
| Stash | 90 дней | `gc.reflogExpire` |

### Синтаксис ссылок

| Ссылка | Значение |
| :--- | :--- |
| `HEAD@{0}` | Текущее состояние HEAD |
| `HEAD@{1}` | Предыдущее состояние HEAD |
| `HEAD@{5}` | 5 записей назад |
| `HEAD@{yesterday}` | HEAD вчера в это время |
| `HEAD@{2.weeks.ago}` | HEAD 2 недели назад |
| `main@{0}` | Текущий коммит ветки main |
| `main@{upstream}` | Коммит отслеживаемой ветки |
| `stash@{0}` | Текущий stash |

---

## Практические сценарии

### Сценарий 1: Просмотр reflog

```bash
# Просмотреть reflog HEAD
git reflog
# → e5f6g7h HEAD@{0}: merge: Resolve conflict
# → a1b2c3d HEAD@{1}: checkout: moving from feature to main
# → abc1234 HEAD@{2}: commit: add feature

# Ограниченный вывод
git reflog -5

# Только определённая ветка
git reflog show main
```

### Сценарий 2: Восстановление после `git reset --hard`

```bash
# Ой, мы сбросили ветку и потеряли коммиты!
git reset --hard HEAD~3
# → HEAD is now at def5678 last good commit

# Посмотреть reflog, чтобы найти потерянный коммит
git reflog
# → e5f6g7h HEAD@{3}: reset: moving to HEAD~3
# → a1b2c3d HEAD@{4}: commit: feature: add module (ПОТЕРЯННЫЙ КОММИТ!)

# Восстановить
git reset --hard HEAD@{4}
# или
git reset --hard a1b2c3d
```

**Edge cases:**
- Reflog хранит SHA-1 коммитов, поэтому даже после `reset --hard` коммит доступен через reflog.
- Если прошло больше 30 дней, `gc` может удалить unreachable коммиты.

### Сценарий 3: Восстановление удалённой ветки

```bash
# Удалили ветку
git branch -D feature-important

# Найти последний коммит ветки через reflog
git reflog | grep "checkout: moving from feature-important"
# → abc1234 HEAD@{12}: checkout: moving from feature-important to main

# Пересоздать ветку
git branch feature-important abc1234
```

### Сценарий 4: Восстановление stash

```bash
# Удалили stash
git stash drop stash@{0}

# Найти через reflog
git reflog | grep stash
# → или через fsck
git fsck --unreachable 2>/dev/null | grep commit

# Восстановить
git stash store -m "Recovered stash" <sha>
```

### Сценарий 5: Навигация по времени

```bash
# Где был HEAD 3 дня назад?
git reflog show HEAD@{3.days.ago}

# Где была ветка main вчера?
git reflog show main@{yesterday}

# Как выглядел проект 2 недели назад?
git checkout HEAD@{2.weeks.ago}
# → Детached HEAD — можно осмотреться
git switch main  # Вернуться обратно
```

### Сценарий 6: Сравнение состояний

```bash
# Что изменилось с прошлого состояния HEAD?
git diff HEAD@{1} HEAD

# Какие коммиты были добавлены?
git log HEAD@{1}..HEAD --oneline
```

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: ambiguous argument 'HEAD@{n}'` | reflog пуст или запись не найдена | Проверить `git reflog` — возможно, записей меньше |
| Не могу найти коммит | reflog очищен gc | Коммит недоступен; проверить `git fsck --lost-found` |
| `reflog` не показывает squash-коммиты | squash не создаёт отдельных записей | Squash коммиты не отслеживаются отдельно |
| Reflog растёт бесконечно | Очистка не настроена | `git config gc.reflogExpire "30 days"` |

### Best Practices

1. **Reflog — локальный** — он не передаётся при push/clone и не виден другим.
2. **Не полагайтесь на reflog для долгосрочного хранения** — gc удаляет записи.
3. **Используйте reflog как страховку** — перед `reset --hard` проверьте `git reflog`.
4. **Настройте `gc.reflogExpire`** — сократите срок хранения для экономии места.
5. **Комбинируйте с `git fsck`** — для поиска висячих объектов после reflog.

---

## Дополнительная информация

### Связанные темы

- [Внутреннее устройство Git](./git_internals.md) — структура `.git/logs/` и объектная модель.
- [Git Basics](./git_basics.md) — архитектура трёх деревьев для понимания состояний HEAD.
- [Git History Manipulation](./git_history_manipulation.md) — reset, revert, recover и работа с потерянными коммитами.
- [Git Troubleshooting](./git_troubleshooting.md) — восстановление после `reset --hard` и удаления веток.

### Официальные ресурсы

- **Git Reflog Documentation:** [git-scm.com/docs/git-reflog](https://git-scm.com/docs/git-reflog)
- **Pro Git Book:** [git-scm.com/book/ru/v2/Внутреннее-устройство-Git](https://git-scm.com/book/ru/v2/Внутреннее-устройство-Git)
