# Конфигурация редакторов (EditorConfig)

## Определения

**EditorConfig** — кроссплатформенный стандарт для определения и поддержания единого стиля форматирования кода в различных редакторах и IDE. Он позволяет избежать конфликтов форматирования в командах, использующих разные инструменты разработки.

**`.editorconfig`** — конфигурационный файл в формате INI, содержащий правила форматирования (отступы, кодировки, переносы строк), которые автоматически применяются поддерживаемыми редакторами при открытии файла.

---

## Базовые концепции

### Иерархия и наследование

EditorConfig использует систему поиска "снизу вверх" по дереву директорий:

1.  **Поиск:** При открытии файла редактор ищет файл `.editorconfig` в текущей директории и во всех родительских директориях до корня файловой системы.
2.  **`root = true`:** Эта директива в начале файла останавливает поиск выше по дереву. Рекомендуется устанавливать её в корне репозитория проекта, чтобы локальные настройки пользователя не влияли на проект.
3.  **Наследование:** Правила из файлов, находящихся ближе к открытому файлу, переопределяют правила из файлов в вышележащих директориях.
4.  **Специфичность:** Внутри одного файла секции, расположенные ниже, переопределяют вышележащие при совпадении паттернов имен файлов.

### Синтаксис Glob-паттернов

EditorConfig поддерживает расширенный синтаксис выбора файлов:

| Паттерн | Описание | Пример |
| :--- | :--- | :--- |
| `*` | Любая последовательность символов, кроме разделителей пути. | `[*.js]` |
| `**` | Любая последовательность символов, включая разделители пути. | `[**/docs/*.md]` |
| `?` | Любой одиночный символ. | `[file?.txt]` |
| `[seq]` | Любой одиночный символ из указанной последовательности. | `[*.{c,h}]` |
| `[!seq]` | Любой одиночный символ, НЕ входящий в последовательность. | `[*.{[!j]s}]` |
| `{s1,s2,s3}` | Любая из указанных строк (разделенных запятой). | `[*.{js,ts,jsx}]` |
| `{num1..num2}` | Любое целое число в диапазоне от `num1` до `num2`. | `[file{1..10}.log]` |

### Основные директивы

| Директива | Значения | Описание |
| :--- | :--- | :--- |
| `indent_style` | `space`, `tab` | Стиль отступа. |
| `indent_size` | число, `tab` | Количество пробелов в отступе. Если `tab`, используется `tab_width`. |
| `tab_width` | число | Ширина табуляции. По умолчанию совпадает с `indent_size`. |
| `end_of_line` | `lf`, `crlf` | Символ конца строки. Рекомендуется `lf`. |
| `charset` | `utf-8`, `utf-8-bom`, `latin1` | Кодировка файла. |
| `trim_trailing_whitespace` | `true`, `false` | Удаление пробелов в конце строк. |
| `insert_final_newline` | `true`, `false` | Пустая строка в конце файла. |
| `max_line_length` | число, `off` | Ограничение длины строки (мягкое или жесткое в зависимости от IDE). |

**Нестандартные (Domain-Specific) свойства:**
Некоторые инструменты (JetBrains, Prettier, C#) поддерживают расширенные свойства, такие как `quote_type` или `ij_java_use_single_class_import`. Они игнорируются стандартными плагинами EditorConfig, но могут учитываться специфичными форматтерами.

### Предварительные требования

* **Редактор/IDE:** Поддержка EditorConfig встроена в JetBrains IDE, Visual Studio, GitHub/GitLab веб-редакторы. Для VS Code требуется расширение [EditorConfig for VS Code](https://marketplace.visualstudio.com/items?itemName=EditorConfig.EditorConfig).
* **Базовые знания:** Понимание различий между окончаниями строк (LF vs CRLF), понятие отступов в форматировании кода.
* **Связанные инструменты:** Для проверки соответствия файлов правилам EditorConfig потребуется CLI-утилита `editorconfig-checker` (опционально).

---

## Практические сценарии

### Сценарий 1: Универсальный шаблон проекта

```ini
# Остановить поиск в родительских папках
root = true

# Глобальные настройки для всех файлов
[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = 2
insert_final_newline = true
trim_trailing_whitespace = true
max_line_length = 120

# Настройки для языков с отступом 4 пробела
[*.{py,java,cs}]
indent_size = 4

# Makefile всегда требует табуляцию
[Makefile]
indent_style = tab

# Markdown допускает пробелы в конце строки для переноса
[*.md]
trim_trailing_whitespace = false
```

**Валидация:**
```bash
# Проверить, что файл .editorconfig распознается
cat .editorconfig
# → (содержимое файла без ошибок синтаксиса)

# Проверить через editorconfig-checker (если установлен)
editorconfig-checker
# → (вывод без ошибок или список файлов, нарушающих правила)

# Проверить конкретный файл
editorconfig-checker path/to/file.js
# → (OK или описание нарушения)
```

**Edge cases:**
* Если `.editorconfig` не в корне репозитория, поиск может остановиться на системных настройках пользователя.
* Паттерн `*` не 匹配ит файлы в поддиректориях — используйте `**` для рекурсивного поиска.
* Некоторые IDE требуют перезапуска для применения изменений `.editorconfig`.

### Сценарий 2: Взаимодействие с .gitattributes

EditorConfig управляет тем, как редактор **пишет** файл, а `.gitattributes` — тем, как Git **хранит** его и обрабатывает при коммите/чекауте.

Для предотвращения конфликтов (например, когда Git меняет `LF` на `CRLF` при чекауте, а EditorConfig требует `LF` при сохранении), рекомендуется синхронизировать их:

*   **EditorConfig:** `end_of_line = lf`
*   **.gitattributes:** `* text eol=lf`

**Валидация:**
```bash
# Проверить текущие окончания строк в файле
file script.sh
# → script.sh: Bourne-Again shell script, ASCII text

# Для Windows-файлов
file script.bat
# → script.bat: ASCII text, with CRLF line terminators

# Проверить атрибуты Git для файла
git check-attr text eol path/to/file
# → path/to/file: text: set
# → path/to/file: eol: lf

# Проверить через git diff (не должно быть изменений после чекаута)
git checkout -- path/to/file
git diff --stat
# → (пусто — файл не изменился)
```

**Edge cases:**
* Если `.gitattributes` не настроен, Git может автоматически конвертировать LF в CRLF на Windows (зависит от `core.autocrlf`).
* EditorConfig не изменяет файлы автоматически — он влияет только на новое редактирование.
* Для принудительной нормализации всех файлов в репозитории используйте `git add --renormalize .`.

### Сценарий 3: Интеграция с Mega-Linter в CI/CD

В современных проектах (2026+) вместо отдельных проверок часто используется **Mega-Linter**, который включает `editorconfig-checker` «из коробки».

```yaml
# .github/workflows/lint.yml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Mega-Linter
        uses: oxsecurity/megalinter@v7
        env:
          ENABLE_LINTERS: EDITORCONFIG_EDITORCONFIG_CHECKER
```

**Валидация:**
```bash
# Проверить workflow локально (при наличии act)
act -j build
# → (успешное выполнение или описание ошибок)

# Проверить логи Mega-Linter на наличие ошибок EditorConfig
# → EDITORCONFIG_EDITORCONFIG_CHECKER: PASSED
# или
# → EDITORCONFIG_EDITORCONFIG_CHECKER: FAILED - 3 errors found
```

**Edge cases:**
* Mega-Linter может быть медленным для больших репозиториев — используйте `FILTER_REGEX_INCLUDE` для ограничения проверяемых файлов.
* Для локальной проверки перед пушем используйте `pre-commit` хук с `editorconfig-checker`.

### Сценарий 4: Проверка через CLI

Использование легковесной утилиты на Go для быстрой проверки:

```bash
# Установка и запуск
go install github.com/editorconfig-checker/editorconfig-checker/v2/cmd/editorconfig-checker@latest
editorconfig-checker -exclude .git
```

**Валидация:**
```bash
# Проверить установку
editorconfig-checker --version
# → editorconfig-checker v2.x.x

# Запуск проверки
editorconfig-checker
# → (пусто — ошибок нет)
# или
# → path/to/file.js:10: trailing whitespace
# → path/to/file.py:5: wrong indentation width (expected 4, got 2)

# Проверить с исключением директорий
editorconfig-checker -exclude "node_modules|.git|vendor"
# → (проверка без указанных директорий)

# Проверить только конкретные файлы
editorconfig-checker path/to/file1.js path/to/file2.py
# → (результат проверки)
```

**Edge cases:**
* `editorconfig-checker` не проверяет файлы, игнорируемые `.gitignore` — используйте `-ignore-defaults` для проверки всех файлов.
* Для интеграции с `pre-commit` добавьте в `.pre-commit-config.yaml`:
  ```yaml
  - repo: https://github.com/editorconfig-checker/editorconfig-checker.python
    hooks:
      - id: editorconfig-checker
  ```

### Сценарий 5: Настройка для мультиязычного проекта

Проект с несколькими языками программирования требует разных настроек форматирования:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

# JavaScript/TypeScript — 2 пробела
[*.{js,ts,jsx,tsx,mjs,cjs}]
indent_style = space
indent_size = 2

# Python — 4 пробела
[*.py]
indent_style = space
indent_size = 4

# Go — табуляция
[*.go]
indent_style = tab
tab_width = 4

# YAML — 2 пробела
[*.{yml,yaml}]
indent_style = space
indent_size = 2

# JSON — 2 пробела
[*.json]
indent_style = space
indent_size = 2

# Markdown — без удаления пробелов (для переносов)
[*.md]
trim_trailing_whitespace = false
max_line_length = off

# Shell-скрипты — 2 пробела
[*.sh]
indent_style = space
indent_size = 2

# Makefile — обязательная табуляция
[Makefile]
indent_style = tab
```

**Валидация:**
```bash
# Проверить все типы файлов
editorconfig-checker
# → (OK или список нарушений)

# Проверить конкретный тип
editorconfig-checker src/*.py
# → (результат для Python-файлов)

# Проверить через IDE (JetBrains/VS Code)
# Открыть файл → нажать Tab → убедиться, что отступ соответствует настройкам
```

**Edge cases:**
* Паттерн `[*.{js,ts}]` применяется к файлам с расширением `.js` и `.ts`, но не к `.jsx` — добавьте явно.
* Для файлов без расширения (например, `Makefile`) используйте точное имя в паттерне.

### Сценарий 6: Интеграция с Prettier

EditorConfig и Prettier могут работать вместе — Prettier читает настройки из `.editorconfig` при наличии плагина:

```ini
# .editorconfig
root = true

[*.{js,ts,jsx,tsx}]
indent_style = space
indent_size = 2
end_of_line = lf
max_line_length = 100
```

```json
// .prettierrc.json (опционально — Prettier возьмет настройки из .editorconfig)
{
  "editorconfig": true
}
```

**Валидация:**
```bash
# Проверить, что Prettier использует настройки из .editorconfig
npx prettier --check "src/**/*.js"
# → (OK или список файлов, требующих форматирования)

# Форматировать с учетом .editorconfig
npx prettier --write "src/**/*.js"
# → (файлы отформатированы согласно правилам)

# Проверить конкретный файл
npx prettier --check src/app.js
# → src/app.js — OK
```

**Edge cases:**
* Prettier поддерживает `.editorconfig` начиная с версии 1.15+.
* Если настройки в `.prettierrc` конфликтуют с `.editorconfig`, приоритет зависит от версии Prettier (обычно `.editorconfig` имеет приоритет при `"editorconfig": true`).
* Для принудительного использования `.editorconfig` без `.prettierrc` достаточно только `.editorconfig` с `"editorconfig": true` в конфиге.

### Сценарий 7: Миграция с ручного форматирования на EditorConfig

Пошаговый процесс внедрения EditorConfig в существующий проект:

```bash
# 1. Создать .editorconfig в корне репозитория
cat > .editorconfig << 'EOF'
root = true

[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = 2
insert_final_newline = true
trim_trailing_whitespace = true
EOF

# 2. Проверить текущее состояние файлов
editorconfig-checker
# → (список файлов, нарушающих правила)

# 3. Нормализовать окончания строк
git add --renormalize .
git commit -m "chore: normalize line endings"

# 4. Закоммитить .editorconfig
git add .editorconfig
git commit -m "chore: add editorconfig"
```

**Валидация:**
```bash
# Проверить, что все файлы соответствуют правилам
editorconfig-checker
# → (пусто — ошибок нет)

# Проверить окончания строк в проблемных файлах
file src/legacy-file.js
# → src/legacy-file.js: ASCII text (без "CRLF")

# Проверить через git diff после нормализации
git diff --stat HEAD~1
# → (список измененных файлов)
```

**Edge cases:**
* Миграция может вызвать массовые изменения в `git diff` — рекомендуется выделять в отдельный коммит.
* Для исключения legacy-файлов из проверки используйте `editorconfig-checker -exclude "legacy/"`.
* Команда `git add --renormalize .` требует Git 2.16+.

---

## Troubleshooting

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| EditorConfig не применяется | Файл не в корне или нет `root = true`. | Убедитесь, что `.editorconfig` в корне репозитория и содержит `root = true`. |
| VS Code игнорирует настройки | Не установлено расширение. | Установите [EditorConfig for VS Code](https://marketplace.visualstudio.com/items?itemName=EditorConfig.EditorConfig). |
| Конфликт с Prettier | Разные настройки в `.prettierrc` и `.editorconfig`. | Установите `"editorconfig": true` в `.prettierrc` или удалите дублирующие настройки. |
| Ошибки в CI | Файлы не проходят проверку `editorconfig-checker`. | Запустите `editorconfig-checker` локально и исправьте нарушения. |
| Неправильные окончания строк | Нет синхронизации с `.gitattributes`. | Добавьте `* text eol=lf` в `.gitattributes`. |

### Диагностика

```bash
# Проверить, что .editorconfig распознается
editorconfig-checker --verbose
# → (подробный вывод с информацией о примененных правилах)

# Проверить настройки для конкретного файла
editorconfig-checker --verbose path/to/file.js
# → (какие правила применены к файлу)

# Проверить окончания строк
file path/to/file
# → (с указанием CRLF или LF)

# Проверить через hexdump (для отладки)
hexdump -C path/to/file | head -5
# → (0d 0a = CRLF, 0a = LF)
```

---

## Best Practices

1.  **Создайте `.editorconfig` в начале проекта** — это предотвратит конфликты форматирования в будущем.
2.  **Всегда используйте `root = true`** — останавливает поиск выше корня репозитория.
3.  **Синхронизируйте с `.gitattributes`** — избегайте конфликтов между окончаниями строк в редакторе и Git.
4.  **Добавьте проверку в CI/CD** — используйте `editorconfig-checker` или Mega-Linter для автоматической проверки.
5.  **Используйте `pre-commit` хук** — для локальной проверки перед коммитом.
6.  **Документируйте нестандартные настройки** — добавляйте комментарии в `.editorconfig` для пояснения специфичных правил.
7.  **Нормализуйте существующие файлы** — при внедрении в legacy-проект используйте `git add --renormalize .`.
8.  **Проверяйте поддержку в IDE команды** — убедитесь, что все разработчики используют редакторы с поддержкой EditorConfig.

---

## Дополнительная информация

### Поддержка в редакторах

*   **JetBrains (IntelliJ, PyCharm, WebStorm):** Встроенная поддержка, самая полная реализация (включая кастомные префиксы `ij_`).
*   **Visual Studio:** Встроенная поддержка, акцент на свойствах `.NET`.
*   **VS Code:** По состоянию на середину 2026 года все еще **требуется расширение** [EditorConfig for VS Code](https://marketplace.visualstudio.com/items?itemName=EditorConfig.EditorConfig) для полной поддержки.
*   **GitHub/GitLab:** Веб-редакторы учитывают `.editorconfig` при правках в браузере.

### Официальные ресурсы

*   **[Официальный сайт EditorConfig](https://editorconfig.org/)** — спецификация и примеры.
*   **[Wiki свойств (GitHub)](https://github.com/editorconfig/editorconfig/wiki/EditorConfig-Properties)** — полный список стандартных и предложенных свойств.

### Связанные темы

*   [Обзор специальных файлов Git](./git_special_files_overview.md)
*   [Управление атрибутами файлов (.gitattributes)](./git_attributes.md)
*   [Конфигурация Git](./git_configuration.md)
