# Конфигурация редакторов (EditorConfig)

**Актуально для:** EditorConfig спецификация 1.0 (стабильна с 2014 года, изменения только в рекомендованных свойствах).

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

Mega-Linter включает `editorconfig-checker` **по умолчанию** во всех флейворах (включая `all`, `python`, `javascript`, `devops`). Дополнительная настройка не требуется — проверка запускается при каждом коммите/PR.

Для использования только `editorconfig-checker` без 70+ других линтеров:

```yaml
# .mega-linter.yml
ENABLE:
  - EDITORCONFIG
```

Пример workflow:

```yaml
# .github/workflows/lint.yml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Mega-Linter
        uses: oxsecurity/megalinter@v9
        env:
          # EDITORCONFIG_EDITORCONFIG_CHECKER включён по умолчанию
          FILTER_REGEX_EXCLUDE: "(test|examples|docs)/.*"
```

**Валидация:**
```bash
# Проверить локально при наличии act
act -j build
# → (успешное выполнение или описание ошибок)

# Проверить логи Mega-Linter на наличие ошибок EditorConfig
# → EDITORCONFIG_EDITORCONFIG_CHECKER: PASSED
# или
# → EDITORCONFIG_EDITORCONFIG_CHECKER: FAILED - 3 errors found
```

**Edge cases:**
* Mega-Linter по умолчанию включает все линтеры, включая `editorconfig-checker`. Если нужна только проверка форматирования — используйте `ENABLE: [EDITORCONFIG]` в `.mega-linter.yml`.
* Для больших репозиториев используйте `FILTER_REGEX_EXCLUDE` или `EDITORCONFIG_EDITORCONFIG_CHECKER_ARGUMENTS` для ограничения проверяемых файлов.
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

EditorConfig и Prettier работают вместе: Prettier читает `.editorconfig` **по умолчанию** в CLI (отключить можно через `--no-editorconfig`). Поддержка появилась в Prettier 1.9 (декабрь 2017 года).

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
// .prettierrc.json — editorconfig НЕ является допустимым ключом
// (ошибка "Ignored unknown option"). CLI читает .editorconfig автоматически.
{
  "singleQuote": true
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

# Отключить чтение .editorconfig
npx prettier --no-editorconfig --check "src/**/*.js"

# Проверить конкретный файл
npx prettier --check src/app.js
# → src/app.js — OK
```

**Edge cases:**
* Prettier поддерживает `.editorconfig` с версии **1.9** (2017), а не 1.15+.
* `editorconfig: true` — опция **API** (`prettier.resolveConfig({ editorconfig: true })`), а не ключ в `.prettierrc`. В `.prettierrc` она вызывает предупреждение "Ignored unknown option".
* Если настройки в `.prettierrc` конфликтуют с `.editorconfig`, `.prettierrc` имеет **приоритет** (переопределяет `.editorconfig`).
* Prettier читает из `.editorconfig` только: `indent_style`, `indent_size`/`tab_width`, `max_line_length`, `end_of_line`, `charset`, `insert_final_newline`, `trim_trailing_whitespace`. Остальные свойства игнорируются.

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

### Сценарий 8: Инфраструктурные файлы (Dockerfile, YAML, Ansible)

DevOps/SRE-инженеры работают с конфигурациями, где форматирование критично для читаемости и совместимости:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

# YAML-файлы (CI/CD, docker-compose, helm)
[*.{yml,yaml}]
indent_style = space
indent_size = 2
max_line_length = 120

# Dockerfile — без расширения, табуляция не требуется (пробелы)
[Dockerfile]
indent_style = space
indent_size = 4

# Ansible — 2 пробела (стандарт Ansible)
[*.{yml,yaml}]
indent_style = space
indent_size = 2

# Shell-скрипты
[*.sh]
indent_style = space
indent_size = 2

# Makefile — обязательная табуляция
[Makefile]
indent_style = tab
```

**Валидация:**
```bash
# Проверить инфраструктурные файлы
editorconfig-checker docker-compose.yml Dockerfile deploy/ansible/
# → (список нарушений или OK)

# Проверить YAML через yamllint (дополнительно)
yamllint docker-compose.yml
# → (оформление согласно Ansible/CI-стандартам)
```

**Edge cases:**
* Dockerfile не имеет расширения — используйте точное имя `[Dockerfile]`.
* YAML-файлы в Ansible требуют `---` в начале; `insert_final_newline = true` гарантирует корректную обработку.
* Для Helm-чартов (`templates/*.yaml`) используйте паттерн `templates/*.yaml`.

### Сценарий 9: Проверка в CI/CD pipeline (SRE контекст)

Для SRE и DevOps-инженеров проверка `.editorconfig` в pipeline предотвращает "шумные" коммиты с форматированием:

```yaml
# .github/workflows/lint.yml
jobs:
  editorconfig:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: EditorConfig check
        run: |
          wget -qO- https://github.com/editorconfig-checker/editorconfig-checker/releases/download/v3.0.0/editorconfig-checker_Linux_x86_64.tar.gz \
          | tar -xz -C /usr/local/bin
          editorconfig-checker -exclude ".git"
```

Или через `pre-commit`:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/editorconfig-checker/editorconfig-checker.python
    rev: v3.0.0
    hooks:
      - id: editorconfig-checker
        args: ["-exclude", ".git"]
```

**Валидация:**
```bash
# Локальная проверка перед пушем
pre-commit run --all-files
# → (список файлов, нарушающих правила)

# Проверка через GitHub Actions
# → editorconfig-checker: PASSED (в UI Actions)
```

**Edge cases:**
* В CI/CD убедитесь, что `editorconfig-checker` установлен как dependency (Go, pip, или binary download).
* Для корпоративных прокси настройте `HTTP_PROXY`/`HTTPS_PROXY` при загрузке бинаря.
* Если `.editorconfig` находится не в корне — укажите путь через `-config` флаг.

---

## Troubleshooting

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| EditorConfig не применяется | Файл не в корне или нет `root = true`. | Убедитесь, что `.editorconfig` в корне репозитория и содержит `root = true`. |
| VS Code игнорирует настройки | Не установлено расширение. | Установите [EditorConfig for VS Code](https://marketplace.visualstudio.com/items?itemName=EditorConfig.EditorConfig). |
| Конфликт с Prettier | Разные настройки в `.prettierrc` и `.editorconfig`. | Удалите дублирующие настройки из `.prettierrc` — Prettier читает `.editorconfig` автоматически (CLI). |
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

### Очистка и откат

*   **Удаление устаревших правил:** Регулярно проверяйте `.editorconfig` на ненужные секции (например, паттерны для удалённых языков). Удалите секцию и перезапустите редакторы для применения изменений.
*   **Откат изменений без переписывания:** Если `.editorconfig` вызвал массовые изменения, откатите коммит через `git revert` или `git reset`. Редакторы вернут предыдущие настройки при следующем открытии файлов (требует перезапуска IDE).
*   **Очистка дублей:** Проверяйте, что секции не перекрываются — более специфичные паттерны (например, `src/*.py`) должны быть ниже общих (например, `*.py`), чтобы переопределять их.
*   **Комментирование:** Добавляйте `#` комментарии для объяснения нетипичных настроек (например, `# Dockerfile требует табуляции`).
*   **Версионирование:** Коммитите `.editorconfig` отдельно от форматирования кода, чтобы можно было легко откатить только настройки или только код.

### Особые случаи и ограничения

*   **Платформы:** Поддержка EditorConfig встроена в JetBrains IDE, Visual Studio, Xcode, Vim, Emacs, BBEdit, GitHub/GitLab/Gitea/Gogs веб-редакторы. Для VS Code, Atom, Sublime Text, CLion, Eclipse требуется плагин.
*   **Символические ссылки:** Редакторы могут не искать `.editorconfig` через символические ссылки на директории — поведение зависит от реализации.
*   **Shallow clone:** `.editorconfig` в корне репозитория доступен при shallow clone, но если он находится выше точки клонирования, редакторы не найдут его.
*   **Bare-репозитории:** EditorConfig не применяется — это формат для редакторов, а не для Git. Для проверки в CI используйте `editorconfig-checker` с явно указанным путём к `.editorconfig`.
*   **Большие `.editorconfig`:** Файлы с десятками секций могут замедлять запуск редактора. Группируйте по темам и избегайте избыточных паттернов.
*   **Отсутствие email/конфигурации:** EditorConfig не требует учётной записи и не взаимодействует с облачными сервисами — работает полностью локально.
*   **Спецсимволы в паттернах:** Паттерны с `[]`, `{}` и `?` могут быть неправильно интерпретированы некоторыми редакторами. Проверяйте поддержку конкретного IDE.

---

## Дополнительная информация

### Поддержка в редакторах

**Встроенная поддержка (без плагинов):**

*   **JetBrains (IntelliJ, PyCharm, WebStorm, Rider, RubyMine, PHPStorm):** Самая полная реализация, включая кастомные префиксы `ij_`.
*   **Visual Studio Professional:** Встроенная поддержка, акцент на `.NET`-свойствах. Visual Studio 2022+ имеет визуальный редактор `.editorconfig`.
*   **Xcode:** Встроенная поддержка.
*   **Vim, Emacs:** Поддержка через плагины (встроенные в дистрибутивы последних версий).
*   **GitHub/GitLab/Gitea/Gogs:** Веб-редакторы учитывают `.editorconfig` при правках в браузере.
*   **BBEdit, Helix, Kakoune, Nova, SourceLair:** Встроенная поддержка.

**Требует плагина:**

*   **VS Code:** По состоянию на 2026 год встроенной поддержки по-прежнему нет. Используйте расширение [EditorConfig for VS Code](https://marketplace.visualstudio.com/items?itemName=EditorConfig.EditorConfig) (12 млн установок, последнее обновление 2026-04-08).
*   **Atom, Sublime Text, CLion, Eclipse, NetBeans, Notepad++, Far Manager:** Требуют плагины.

### Официальные ресурсы

*   **[Официальный сайт EditorConfig](https://editorconfig.org/)** — спецификация, примеры, список поддерживаемых редакторов.
*   **[Wiki свойств (GitHub)](https://github.com/editorconfig/editorconfig/wiki/EditorConfig-Properties)** — полный список стандартных и предложенных свойств.
*   **[editorconfig-checker (GitHub)](https://github.com/editorconfig-checker/editorconfig-checker)** — CLI-утилита для проверки.
*   **[Mega-Linter](https://megalinter.io/)** — интеграция в CI/CD.

### Связанные темы

*   [Обзор специальных файлов Git](./git_special_files_overview.md)
*   [Управление атрибутами файлов (.gitattributes)](./git_attributes.md)
*   [Конфигурация Git](./git_configuration.md)
