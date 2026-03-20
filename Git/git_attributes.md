# Git Attributes — обработка файлов

## Определения

**`.gitattributes`:** Файл, определяющий, как Git обрабатывает конкретные файлы (фильтры, драйверы diff/merge, нормализация окончаний строк).

---

## .gitattributes

### Назначение

Файл `.gitattributes` указывает Git, как обрабатывать конкретные файлы: фильтры, драйверы diff/merge, нормализация окончаний строк, переопределения для определения языка.

### Основные атрибуты

```gitattributes
# Фильтры clean/smudge (Git LFS)
*.psd filter=lfs diff=lfs merge=lfs

# Нормализация окончаний строк
*.sh text eol=lf
*.bat text eol=crlf

# Обработка как бинарных
*.png binary
*.jpg binary

# Кастомный драйвер diff
*.json diff=json

# Стратегия слияния
package-lock.json merge=ours

# GitHub Linguist — переопределение определения языка
vendor/* linguist-vendored
*.gen.go linguist-generated
docs/* linguist-documentation
```

### Описание атрибутов

| Атрибут | Описание |
| :--- | :--- |
| `text` | Нормализовать окончания строк (CRLF ↔ LF) |
| `binary` | Не делать diff/merge, просто выбрать одну версию |
| `eol=lf` / `eol=crlf` | Принудительная нормализация к LF или CRLF |
| `merge=ours` | Всегда сохранять вашу версию при конфликтах слияния |
| `filter=lfs` | Использовать Git LFS для обработки файла |
| `linguist-vendored` | Исключить из статистики языков GitHub |
| `linguist-generated` | Сворачивать в diffs на GitHub |
| `linguist-documentation` | Исключить из статистики языков |

### Порядок проверки

Git проверяет `.gitattributes` в каждой директории и `.git/info/attributes` для локальных атрибутов.

---

## Связанные документы

- **Обзор**: [git_special_files_overview.md](./git_special_files_overview.md)
- **Git LFS Config**: [git_lfs_config.md](./git_lfs_config.md)
- **Git Ignore**: [git_ignore.md](./git_ignore.md)
