# Git Mailmap — маппинг авторов

## Определения

**`.mailmap`:** Файл для маппинга имён и email авторов на канонические идентичности.

---

## .mailmap

### Назначение

Файл `.mailmap` маппит имена и email авторов на канонические идентичности. Git использует его для вывода `git log`, `git shortlog`, `git blame`.

### Формат

```mailmap
# Маппинг старого email на новый
Jane Developer <jane@company.com> <jane@oldcompany.com>

# Стандартизация написания имени
Jane Developer <jane@company.com> Jane Dev <jane@company.com>

# Исправление обоих
Jane Developer <jane@company.com> <janed@personal.com>
Jane Developer <jane@company.com> J Developer <janed@personal.com>
```

Формат: `Proper Name <proper@email.com> Commit Name <commit@email.com>`

### Особенности

* **Инструменты:** `git shortlog -sn`, `git log`, `git blame` используют mailmap для агрегации коммитов.
* **GitHub:** Графики контрибьюторов GitHub **не используют** `.mailmap`, дубликаты сохраняются в веб-интерфейсе.
* **Расположение:** По умолчанию `.mailmap` в корне репозитория или путь настраивается через `mailmap.file`.

---

## Связанные документы

- **Обзор**: [git_special_files_overview.md](./git_special_files_overview.md)
