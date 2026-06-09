# EditorConfig — конфигурация редакторов

## Определения

**EditorConfig** — кроссплатформенный стандарт для согласования настроек редакторов кода между разработчиками и инструментами.

**`.editorconfig`** — декларативный конфигурационный файл, определяющий стили форматирования (отступы, кодировку, окончания строк, пробелы).

---

## Базовые концепции

### Принцип работы

EditorConfig работает через иерархию файлов `.editorconfig`:

1. **Поиск файла:** Редактор ищет `.editorconfig` от текущего файла до корня диска
2. **`root = true`:** Останавливает поиск вышележащих файлов
3. **Наследование:** Параметры суммируются, более специфичные секции переопределяют общие

### Основные директивы

| Директива | Значения | Описание |
| :--- | :--- | :--- |
| `indent_style` | `space`, `tab` | Тип отступа |
| `indent_size` | число, `tab` | Размер отступа |
| `end_of_line` | `lf`, `crlf`, `cr` | Символ окончания строки |
| `charset` | `utf-8`, `utf-16le`, `utf-16be`, `latin1` | Кодировка файла |
| `trim_trailing_whitespace` | `true`, `false` | Удаление концевых пробелов |
| `insert_final_newline` | `true`, `false` | Добавление newline в конец файла |
| `max_line_length` | число | Максимальная длина строки |

### Синтаксис секций

```ini
# Глобальные настройки для всех файлов
[*]
indent_style = space
indent_size = 2

# Настройки для конкретных расширений
[*.{js,ts,jsx,tsx}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false

[{package.json,.travis.yml}]
indent_size = 2
```

---

## Практические сценарии

### Сценарий 1: Базовая настройка проекта

```editorconfig
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2
```

### Сценарий 2: Смешанный проект (код + конфиги)

```editorconfig
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true

[*.{js,ts,py,go}]
indent_style = space
indent_size = 2
trim_trailing_whitespace = true

[*.{yaml,yml,json}]
indent_style = space
indent_size = 2

[Makefile]
indent_style = tab

[*.md]
trim_trailing_whitespace = false
```

### Сценарий 3: Командная разработка

Для консистентности в команде:

1. Разместить `.editorconfig` в корне репозитория
2. Установить `root = true` для предотвращения наследования
3. Настроить CI-проверку через [editorconfig-checker](https://github.com/editorconfig-checker/editorconfig-checker)

---

## Дополнительная информация

### Поддержка инструментов

| Инструмент | Поддержка |
| :--- | :--- |
| VS Code | Нативная (требуется перезагрузка) |
| Vim / Neovim | Нативная (v8.0+) |
| Emacs | Через пакет `editorconfig` |
| Sublime Text | Через плагин |
| IntelliJ IDEA | Нативная |
| WebStorm, PyCharm | Нативная |

### Официальные ресурсы

- **Спецификация:** [editorconfig.org](https://editorconfig.org/)
- **Репозиторий:** [github.com/editorconfig/editorconfig](https://github.com/editorconfig/editorconfig)

### Связанные документы

Обзор специальных файлов Git в [git_special_files_overview.md](./git_special_files_overview.md). Файлы версий инструментов описаны в [version_files.md](./version_files.md).
