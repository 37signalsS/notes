# Git Shortlog — отчёты по авторам

## Определения

**git shortlog** — команда для суммаризации вывода `git log` по авторам. Подсчитывает количество коммитов каждого автора и группирует их. Часто используется для аудита, отчётности и генерации CHANGELOG.

**.mailmap** — файл, содержащий правила канонизации имён и email-адресов авторов. Позволяет объединять историю одного человека под разными именами в `git shortlog` и `git blame`.

---

## Базовые концепции

### Флаги shortlog

| Флаг | Описание |
| :--- | :--- |
| `-s` / `summary` | Только количество коммитов (без сообщений) |
| `-n` / `numbered` | Сортировка по количеству коммитов (убывание) |
| `-e` / `email` | Показывать email-адреса авторов |
| `-c` / `committer` | Использовать committer вместо author |
| `--no-merges` | Исключить merge-коммиты |
| `--since="..."` | Фильтр по дате начала |
| `--until="..."` | Фильтр по дате окончания |
| `--author="..."` | Фильтр по автору |
| `--all` | Все ветки |

### shortlog vs log

| Критерий | git shortlog | git log |
| :--- | :--- | :--- |
| Формат | Сводный отчёт | Детальный список |
| Группировка | По авторам | Хронологическая |
| Назначение | Аудит, отчётность | Просмотр истории |

---

## Практические сценарии

### Сценарий 1: Количество коммитов по авторам

```bash
# Простой подсчёт
git shortlog -sn
# → 42  Developer 1
# → 15  Developer 2
# → 8   Developer 3
```

**Валидация:**
```bash
# Суммарное количество
git shortlog -sn | awk '{sum+=$1} END {print sum}'
# → 65
```

### Сценарий 2: С email-адресами

```bash
git shortlog -sne
# → 42  Developer 1 <dev1@company.com>
# → 15  Developer 2 <dev2@company.com>
```

### Сценарий 3: Только за период

```bash
# За последний месяц
git shortlog -sn --since="1 month ago"

# За конкретный квартал
git shortlog -sn --since="2024-01-01" --until="2024-04-01"

# Без merge-коммитов
git shortlog -sn --no-merges
```

### Сценарий 4: Отчёт по конкретной ветке

```bash
# Все коммиты в feature от main
git shortlog -sn main..feature

# Все коммиты в main от feature
git shortlog -sn feature..main
```

### Сценарий 5: Интеграция с mailmap

```bash
# Создать .mailmap
echo "Ivan Ivanov <ivan@company.com> <ivan.old@company.com> <ivan@personal.me>" > .mailmap

# Теперь shortlog объединяет записи
git shortlog -sne
# → 42  Ivan Ivanov <ivan@company.com>  (вместо двух отдельных записей)
```

### Сценарий 6: Генерация CHANGELOG

```bash
# Список коммитов по авторам за версию
git shortlog -sne v1.0.0..v2.0.0

# Только notable commits
git shortlog --no-merges --since="2024-01-01" | grep -E "^    [a-f0-9]"
```

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: ambiguous argument` | Некорректный диапазон | Указать корректный ref или тег |
| Дублирующиеся авторы | Разные email у одного человека | Настроить `.mailmap` |
| Merge-коммиты искажают статистику | Они计入 автора мержа | Использовать `--no-merges` |

### Best Practices

1. **Используйте `--no-merges`** для точной статистики.
2. **Настройте `.mailmap`** для объединения дублей авторов.
3. **Комбинируйте с `--since`/`--until`** для периодических отчётов.
4. **Используйте `-n`** для сортировки по количеству коммитов.

---

## Дополнительная информация

### Связанные темы

- [Git Mailmap](./git_mailmap.md) — канонизация имён авторов для объединения дублей.
- [Git Blame Ignore](./git_blame_ignore.md) — исключение шумных коммитов из статистики.
- [Git Tags](./git_tags.md) — отчёты между релизами (shortlog -sn v1.0.0..v2.0.0).
- [Конфигурация Git](./git_configuration.md) — mailmap.file, mailmap.blob настройки.

### Официальные ресурсы

- **Git Shortlog Documentation:** [git-scm.com/docs/git-shortlog](https://git-scm.com/docs/git-shortlog)
