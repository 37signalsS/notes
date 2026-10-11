# Git Shortlog — отчёты по авторам

**Актуально для:** Git 2.54 (2025). Флаги `--group=month`/`--group=year` доступны с Git 2.55+, на локальных системах с Git 2.54 они отсутствуют.

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
| `--group=<type>` | Группировка по author / committer / trailer:FIELD / format:STRING (по умолчанию author) |
| `--group=trailer:FIELD` | Группировка по заголовку commit-трейлера (например, `Reviewed-by`) |
| `--format[=<format>]` | Вместо subject использовать шаблон `git log --pretty` (например, `[%h] %s`) |
| `--date=<format>` | Формат даты (актуально с `--group=format:`) |
| `--wrap=<width>[,<indent1>[,<indent2>]] | Перенос строк с заданной шириной и отступами |
| `--stdin` | Читать ревизии из stdin (не совместимо с `--group=trailer`, `--group=year`, `--group=month`) |
| `-w[<width>[,<indent1>[,<indent2>]]]` | Аналог `--wrap` |

**Совет:** `--group` можно указывать несколько раз — коммиты учитываться в каждой группе по одному разу. Например, `git shortlog --group=author --group=trailer:co-authored-by` учитывает как авторов, так и соавторов.

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
# Создать .mailmap: объединить два старых email под одним каноническим именем
echo "Ivan Ivanov <ivan@company.com> <ivan.old@company.com>" > .mailmap
echo "Ivan Ivanov <ivan@company.com> <ivan@personal.me>" >> .mailmap

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

### Сценарий 7: Группировка по commit-трейлерам (co-authored-by, Reviewed-by)

Позволяет видеть вклад по ролям, а не только по primary author:

```bash
# Кто оставлял Reviewed-by в коммитах
git shortlog -ns --group=trailer:reviewed-by

# Учитывать и авторов, и соавторов (каждый коммит засчитывается в обеих группах)
git shortlog -ns --group=author --group=trailer:co-authored-by

# Группировка по коммиттеру вместо автора
git shortlog -nsc
```

**Валидация:**
```bash
# Проверить, какие трейлеры есть в последних коммитах
git log -1 --format="%B" | grep -E "^[A-Z][a-z-]+-by:"
# → Reviewed-by: Developer <dev@company.com>
```

**Edge cases:**
* `--group=trailer:FIELD` чувствителен к регистру — используйте точное имя заголовка.
* Трейлеры не добавлены в коммит — группа будет пустой.
* `--stdin` не совместим с `--group=trailer`.

### Сценарий 8: Группировка по времени (день, месяц, год)

```bash
# Коммиты по дням за последний месяц
git shortlog -s --date='format:%Y-%m-%d' --group='format:%cd' --since='1 month ago'
# → 3  2024-08-03
# → 5  2024-08-05

# День недели (1 = понедельник)
git shortlog -s --date='format:%u' --group='format:%cd'

# Час дня
git shortlog -s --date='format:%H' --group='format:%cd'

# По месяцам (требует Git 2.55+)
git shortlog -ns --group=month --group=author
# → 12  2024/08  Developer 1
```

**Валидация:**
```bash
# Проверить, что формат даты поддерживается
git log -1 --date='format:%Y-%m-%d' --format="%ad"
# → 2024-08-05
```

**Edge cases:**
* `--group=format:` требует `--date` для интерпретации даты.
* `--group=month`/`--group=year` доступны с Git 2.55+ (на момент написания — RFC, в main с 2.55). На Git ≤2.54 используйте `--group=format:%Y` / `--group=format:%Y/%m`.
* `--group=year`/`--group=month` не работают с `--stdin`.

### Сценарий 9: Форматирование и перенос строк (--wrap)

```bash
# Перенос строк на 80 символов, отступ 4 и 8
git shortlog -w80,4,8 --no-merges

# С кастомным форматом коммита
git shortlog --format='[%h] %s' -w100
```

**Валидация:**
```bash
# Проверить ширину вывода
git shortlog -w80,4,8 -sn | awk '{print length}'
# → (максимум 80 символов на строку)
```

### Сценарий 10: Работа через stdin/pipeline (SRE/DevOps)

```bash
# Обработка output других команд
git log --author="bot" --format="%H" | git shortlog -sne --stdin

# Интеграция с shell-пайплайном
git log --since="1 week ago" --format="%aN <%aE>" | sort | uniq -c | sort -rn
# → 3 bot@company.com
# → 2 developer@company.com
```

**Валидация:**
```bash
# Проверить, что stdin читается корректно
echo "HEAD" | git shortlog -sne --stdin
# → 42  Developer 1 <dev1@company.com>
```

**Edge cases:**
* `--stdin` не совместим с `--group=trailer`, `--group=year`, `--group=month`.
* При pipe'инге теряется цвет и интерактивное поведение — это нормально для CI/CD.

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: ambiguous argument` | Некорректный диапазон | Указать корректный ref или тег |
| Дублирующиеся авторы | Разные email у одного человека | Настроить `.mailmap` |
| Merge-коммиты искажают статистику | Они засчитаются автору мержа | Использовать `--no-merges` |

### Best Practices

1. **Используйте `--no-merges`** для точной статистики.
2. **Настройте `.mailmap`** для объединения дублей авторов.
3. **Комбинируйте с `--since`/`--until`** для периодических отчётов.
4. **Используйте `-n`** для сортировки по количеству коммитов.

### DevOps / SRE / Sysadmin контекст

**Аудит безопасности (SRE):**
```bash
# Кто делал коммиты в sensitive-файлы за последний год
git shortlog -sne --no-merges --since="1 year ago" -- config/ secrets/ infra/

# Выявить "одиночных" авторов (подозрительные аккаунты)
git shortlog -sn | awk '$1 == 1'
# → 1  service-account-123
```

**CI/CD и pipeline-интеграция:**
```bash
# Генерация release notes в pipeline
git shortlog -sne "$LAST_TAG..$CURRENT_TAG" > release_notes.txt

# Проверка активности разработчиков (SRE-мониторинг)
git shortlog -sn --since="7 days ago" | wc -l
# → 5 (активных разработчика за неделю)
```

**Интеграция с Ansible/Terraform (sysadmin):**
```bash
# Отчёт по изменениям инфраструктуры (только коммиты в инфра-каталоги)
git shortlog -sn --no-merges -- infra/ansible/ terraform/

# Сравнение активности между средами
git shortlog -sn --since="2024-01-01" --until="2024-03-31" -- production/ > q1_prod.txt
git shortlog -sn --since="2024-04-01" --until="2024-06-30" -- production/ > q2_prod.txt
```

**Edge cases (SRE):**
* При аудите всегда используйте `--no-merges` — merge-коммиты могут маскировать реальных авторов.
* Для репозиториев с ботами (GitHub Actions, Dependabot) добавьте `--author="!bot"` или фильтр по email.
* `git shortlog` не учитывает `co-authored-by` по умолчанию — для полного учёта вклада используйте `--group=trailer:co-authored-by`.

---

## Дополнительная информация

### Связанные темы

- [Git Mailmap](./git_mailmap.md) — канонизация имён авторов для объединения дублей.
- [Git Blame Ignore](./git_blame_ignore.md) — исключение шумных коммитов из статистики.
- [Git Tags](./git_tags.md) — отчёты между релизами (shortlog -sn v1.0.0..v2.0.0).
- [Конфигурация Git](./git_configuration.md) — mailmap.file, mailmap.blob настройки.

### Официальные ресурсы

- **Git Shortlog Documentation:** [git-scm.com/docs/git-shortlog](https://git-scm.com/docs/git-shortlog)
