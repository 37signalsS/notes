# Git Attributes — обработка файлов

## Определения

**`.gitattributes`** — декларативный конфигурационный файл Git, определяющий правила обработки файлов: нормализацию окончаний строк, фильтры, драйверы diff/merge, атрибуты для GitHub Linguist.

---

## Базовые концепции

### Принцип работы

Git проверяет `.gitattributes` в иерархии директорий:

1. **Корень репозитория** — базовые правила для всего проекта
2. **Вложенные директории** — переопределяют правила для подкаталогов
3. **`.git/info/attributes`** — локальные атрибуты, не коммитятся

Правила применяются к файлам при добавлении в индекс (`git add`).

### Основные атрибуты

| Атрибут | Описание |
| :--- | :--- |
| `text` | Нормализовать окончания строк (CRLF ↔ LF при checkout/commit) |
| `binary` | Не делать diff/merge, обрабатывать как бинарные |
| `eol=lf` / `eol=crlf` | Принудительная нормализация к LF или CRLF |
| `merge=ours` | Автоматически разрешать конфликты в пользу текущей ветки |
| `merge=union` | Объединять все изменения при конфликте |
| `filter=<name>` | Применить фильтр (например, `lfs`, `git-crypt`) |
| `diff=<name>` | Использовать кастомный драйвер diff |
| `linguist-vendored` | Исключить из статистики языков GitHub |
| `linguist-generated` | Сворачивать в diffs на GitHub |
| `linguist-documentation` | Исключить из статистики языков GitHub |

### Синтаксис паттернов

```gitattributes
# Паттерн с расширением
*.json diff=json

# Паттерн по пути
vendor/* linguist-vendored

# Отрицание
!important.config

# Комбинация паттернов
*.{png,jpg,gif} binary
```

---

## Практические сценарии

### Сценарий 1: Нормализация окончаний строк

Для кроссплатформенной разработки:

```gitattributes
# Все текстовые файлы нормализуются к LF
* text=auto

# Скрипты всегда с LF
*.sh text eol=lf
*.bash text eol=lf

# Windows-файлы с CRLF
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
```

### Сценарий 2: Git LFS для бинарных файлов

```gitattributes
# Графические ресурсы через LFS
*.psd filter=lfs diff=lfs merge=lfs
*.ai filter=lfs diff=lfs merge=lfs
*.sketch filter=lfs diff=lfs merge=lfs

# Видео и аудио
*.mp4 filter=lfs diff=lfs merge=lfs
*.mov filter=lfs diff=lfs merge=lfs
*.mp3 filter=lfs diff=lfs merge=lfs

# Датасеты
*.csv filter=lfs diff=lfs merge=lfs
*.parquet filter=lfs diff=lfs merge=lfs
```

Требуется установка [Git LFS](https://git-lfs.com/) и инициализация: `git lfs install`.

### Сценарий 3: GitHub Linguist — точная статистика языков

```gitattributes
# Исключить vendor-библиотеки
vendor/* linguist-vendored
third_party/* linguist-vendored

# Сгенерированные файлы
*.gen.go linguist-generated
*.pb.go linguist-generated
dist/* linguist-generated

# Документация
docs/* linguist-documentation
README.* linguist-documentation

# Конфигурационные файлы
*.lock linguist-vendored
package-lock.json linguist-vendored
```

### Сценарий 4: Кастомный diff для JSON

```gitattributes
*.json diff=json
```

```ini
# .git/config
[diff "json"]
    textconv = jq '.'
```

### Сценарий 5: Автоматическое разрешение конфликтов

```gitattributes
# Файлы зависимостей — всегда принимать локальную версию
package-lock.json merge=ours
yarn.lock merge=ours
pnpm-lock.yaml merge=ours

# Файлы проектов IDE — объединять
*.iml merge=union
```

### Сценарий 6: Шифрование через git-crypt

```gitattributes
# Шифровать чувствительные файлы
secrets/*.yml filter=git-crypt diff=git-crypt
*.env filter=git-crypt diff=git-crypt
```

Требуется установка [git-crypt](https://github.com/AGWA/git-crypt) и инициализация: `git-crypt init`.

---

## Дополнительная информация

### Отладка атрибутов

```bash
# Проверить атрибуты для файла
git check-attr -a -- <файл>

# Проверить атрибуты для всех файлов
git check-attr -a -- '*'
```

### Официальные ресурсы

- **Спецификация:** [git-scm.com/docs/gitattributes](https://git-scm.com/docs/gitattributes)
- **GitHub Linguist:** [github.com/github-linguist/linguist](https://github.com/github-linguist/linguist)

### Связанные документы

Обзор специальных файлов в [git_special_files_overview.md](./git_special_files_overview.md). Конфигурация LFS описана в [git_lfs_config.md](./git_lfs_config.md), игнорирование файлов — в [git_ignore.md](./git_ignore.md).
