# Editorconfig — конфигурация редакторов

## Определения

**`.editorconfig`:** Файл для стандартизации поведения редакторов (indent style, line endings, trailing whitespace, encoding).

---

## .editorconfig

**Назначение:** Стандартизация поведения редакторов (indent style, line endings, trailing whitespace, encoding).

**Пример:**
```editorconfig
root = true

[*]
indent_style = space
indent_size = 2
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true

[*.md]
trim_trailing_whitespace = false
```

**Поддержка:** VS Code, Vim, Emacs, Sublime — нативно или через плагины.

---

## Связанные документы

- **Обзор**: [git_special_files_overview.md](./git_special_files_overview.md)
- **Version Files**: [version_files.md](./version_files.md)
