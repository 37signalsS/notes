# ansible-lint: проверка качества плейбуков и ролей

## Определения

- **ansible-lint** — статический анализатор кода, проверяющий плейбуки, роли и коллекции на соответствие best practices
- **Rule** — правило проверки (например, `yaml[line-length]`, `no-free-form`, `name[missing]`)
- **Profile** — набор правил, сгруппированных по назначению (min, safety, shared, production, moderation, security)
- **Skip tag** — тег для пропуска конкретного правила в задаче или файле
- **Mock role** — заглушка для тестирования ansible-lint без реальных зависимостей
- **Exclude path** — путь, исключённый из проверки
- **Parseable output** — формат вывода, пригодный для парсинга CI/CD
- **`.ansible-lint-ignore`** — файл для игнорирования конкретных нарушений без изменения кода
- **`--write`** — опция автоматического исправления нарушений (заменяет устаревшую `--fix`)

## Основные концепции и архитектура

### Принцип работы

ansible-lint выполняет статический анализ без запуска плейбуков. Жизненный цикл проверки:

1. **Поиск конфигурации**: ansible-lint ищет `.ansible-lint`, `.config/ansible-lint.yml`, `.config/ansible-lint.yaml` или раздел `[tool.ansible-lint]` в `pyproject.toml`
2. **Обнаружение файлов**: рекурсивный обход каталогов с плейбуками и ролями
3. **Загрузка правил**: внутренние правила + кастомные из `rulesdir`
4. **Парсинг YAML**: валидация синтаксиса и структуры
5. **Применение правил**: проверка по выбранному профилю
6. **Отчёт**: вывод в текстовом, parseable или JSON формате
7. **Автоисправление** (опционально): исправление поддерживаемых нарушений через `--write`

### Установка и требования

- **Версия ansible-lint:** 26.x (последняя стабильная версия — v26.8.0)
- **Версия ansible-core:** 2.16+
- **Python:** 3.11+ (рекомендуется 3.14)
- **Установка:** `pip install ansible-lint`
- **Проверка версии:** `ansible-lint --version`
- **Зависимости:** `ansible-core`, `pyyaml`, `rich` (устанавливаются автоматически)

### Конфигурационные файлы

Ansible-lint ищет конфигурацию в следующем порядке приоритета:
1. `.ansible-lint` (YAML, в корне проекта)
2. `.config/ansible-lint.yml` (YAML)
3. `.config/ansible-lint.yaml` (YAML)
4. `pyproject.toml` (раздел `[tool.ansible-lint]`)

### Профили

Профили группируют правила по уровню строгости:

| Профиль | Описание | Кол-во правил | Использование |
| :--- | :--- | :--- | :--- |
| **min** | Минимальный набор — только синтаксические ошибки | ~15 | Быстрая проверка в CI, локальная разработка |
| **safety** | Проверки безопасности — no-log, хардкод паролей | ~30 | Pre-commit, security review |
| **shared** | Базовые проверки для шаред-контента (роли, коллекции) | ~40 | Публикация ролей в Galaxy |
| **moderation** | Базовые проверки + рекомендации | ~50 | Pull request review |
| **production** | Полный набор для production-качества | ~80+ | CI/CD pipeline, gate для деплоя |
| **security** | Специализированный набор для проверки безопасности | ~30+ | Аудит безопасности, compliance |

### Ключевые правила

- `yaml[line-length]` — максимальная длина строки YAML
- `no-free-form` — запрет свободной формы `shell: cmd`
- `name[missing]` — отсутствие описания задачи
- `fqcn[action-core]` — требование полных имён модулей (FQCN)
- `no-changed-when` — задачи с `command`/`shell` должны иметь `changed_when`
- `yaml[truthy]` — использование `true`/`false` вместо `yes`/`no`
- `no-log-password` — отсутствие `no_log` в задачах с секретами
- `name[casing]` — стилистика имён задач

### Основные опции CLI

- `-p`, `--parseable` — машинночитаемый формат вывода
- `-L`, `--list-rules` — список доступных правил
- `-T`, `--list-tags` — список доступных тегов
- `--profile=NAME` — выбор профиля
- `-x RULE`, `--skip-list RULE` — исключить правило
- `-t TAG`, `--tags TAG` — включить только теги
- `--skip-tags TAG` — исключить теги
- `--severity=LEVEL` — минимальный уровень серьёзности (warning, error)
- `--write` — автоматически исправить нарушения
- `--write LIST` — исправить только указанные правила
- `--dry-run` — показать изменения без применения
- `--offline` — работать без интернета (не обновлять схемы)
- `--generate-ignore` — создать `.ansible-lint-ignore` для текущих нарушений
- `--cache-dir DIR` — директория для кэширования
- `--exclude PATH` — исключить путь из проверки
- `-c FILE`, `--config-file FILE` — указать конфигурационный файл
- `-i FILE`, `--ignore-file FILE` — файл с игнорируемыми нарушениями
- `--strict` — возвращать ненулевой код для предупреждений

### Выходные коды

- `0` — нарушений не найдено
- `2` — найдены нарушения (ошибки)
- `4` — ошибка конфигурации
- `6` — непредвиденная ошибка

## Практические сценарии

### Запуск ansible-lint в корне проекта

```bash
# Базовая проверка
ansible-lint
# → 0 issues found

# Parseable формат для CI
ansible-lint -p
# → path/to/playbook.yml:5: [yaml[line-length]] Line too long (162 > 120)

# Строгий профиль
ansible-lint --profile=production

# Пропустить правило
ansible-lint -x yaml[line-length]

# Только ошибки (без предупреждений)
ansible-lint --severity=error

# Исключить каталог
ansible-lint --exclude vendor/ --exclude .git/
```

### Настройка конфигурации

```yaml
# .ansible-lint
---
profile: production

exclude_paths:
  - .git/
  - .github/
  - molecule/
  - vendor/
  - tests/

skip_list:
  - yaml[line-length]
  - no-free-form

warn_list:
  - experimental
  - name[missing]

enable_list:
  - fqcn

# Профили можно переопределять для подкаталогов
# В roles/.ansible-lint:
# ---
# profile: shared

# Или через переменную окружения
# ANSIBLE_LINT_PROFILE=shared ansible-lint
```

```yaml
# pyproject.toml
[tool.ansible-lint]
profile = "production"
exclude_paths = [".git/", "vendor/"]
skip_list = ["yaml[line-length]"]
```

### Использование `.ansible-lint-ignore`

```bash
# Сгенерировать файл с текущими нарушениями
ansible-lint --generate-ignore
# → .ansible-lint-ignore создан

# Файл .ansible-lint-ignore (формат: путь правило)
# playbooks/legacy.yml yaml[line-length]
# roles/old_role/tasks/main.yml no-free-form
```

### Типичные ошибки и исправление

```yaml
# Ошибка: no-free-form
- name: example
  shell: echo "hello"

# Исправлено
- name: example
  ansible.builtin.shell:
    cmd: echo "hello"

# Ошибка: name[missing]
- name: example
  ansible.builtin.debug:
    msg: "test"

# Исправлено
- name: Print debug message
  ansible.builtin.debug:
    msg: "test"

# Ошибка: fqcn[action-core]
- name: example
  debug:
    msg: "test"

# Исправлено
- name: Print debug message
  ansible.builtin.debug:
    msg: "test"

# Ошибка: no-changed-when
- name: Run migration
  ansible.builtin.command: django_manage migrate

# Исправлено
- name: Run migration
  ansible.builtin.command: django_manage migrate
  changed_when: false
```

### Использование skip-list для исключения правил

```yaml
# В файле плейбука
---
# ansible-lint: skip yaml[truthy]
- name: Enable feature flag
  hosts: all
  tasks:
    - name: Set variable
      ansible.builtin.set_fact:
        my_var: true
```

### Профили: выбор и настройка

```bash
# Разработка (локально)
ansible-lint --profile=min

# Pre-commit hook
ansible-lint --profile=safety

# Pull Request
ansible-lint --profile=shared

# CI/CD pipeline
ansible-lint --profile=production

# Ansible Galaxy publish
ansible-lint --profile=shared

# Аудит безопасности
ansible-lint --profile=security
```

```yaml
# .ansible-lint
---
profile: production

# Переопределение для подкаталогов
# В roles/.ansible-lint:
# profile: shared
```

### Кастомные правила

#### Создание собственного правила

```python
# custom_rules/require_handler_notify.py
"""Кастомное правило: все задачи, изменяющие состояние, должны иметь notify."""
from ansiblelint import AnsibleLintRule


class RequireHandlerNotifyRule(AnsibleLintRule):
    id = "custom-9001"
    shortdesc = "Tasks that change state must have notify"
    description = (
        "All tasks that may change system state should have a notify "
        "handler to ensure idempotency verification."
    )
    severity = "WARNING"
    tags = ["custom", "best-practice"]

    def matchtask(self, task):
        action = task.get("action", {})
        module_name = action.get("module_name", "")

        state_changing_modules = {
            "ansible.builtin.service",
            "ansible.builtin.systemd",
            "ansible.builtin.package",
            "ansible.builtin.apt",
            "ansible.builtin.yum",
            "ansible.builtin.copy",
            "ansible.builtin.template",
            "ansible.builtin.file",
            "ansible.builtin.lineinfile",
            "ansible.builtin.blockinfile",
        }

        if module_name in state_changing_modules:
            has_notify = "notify" in task
            if not has_notify:
                return True
        return False
```

#### Регистрация кастомного правила

```yaml
# .ansible-lint
---
rulesdir:
  - ./custom_rules

# Или через environment variable
# ANSIBLE_LINT_RULES_DIR=./custom_rules ansible-lint
```

#### Кастомный профиль

```yaml
# .ansible-lint
---
profiles:
  custom:
    min: false
    mode: all
    skip-list:
      - yaml[line-length]
      - no-free-form
    enable-list:
      - custom-9001
      - custom-9002
```

### Интеграция с CI/CD

#### Pre-commit hook

```yaml
# .pre-commit-config.yaml
---
repos:
  - repo: https://github.com/ansible/ansible-lint
    rev: v26.8.0
    hooks:
      - id: ansible-lint
        args:
          - --profile=production
          - -x yaml[line-length]
          - --force-color
        additional_dependencies:
          - ansible-core>=2.16
        always_run: true

  - repo: local
    hooks:
      - id: ansible-lint-custom
        name: Ansible Lint (custom rules)
        entry: ansible-lint --profile=custom --rulesdir ./custom_rules
        language: system
        files: \.(yml|yaml)$
        pass_filenames: false
        always_run: true
```

#### GitHub Actions

```yaml
# .github/workflows/ansible-lint.yml
---
name: Ansible Lint
on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - name: Install dependencies
        run: |
          pip install ansible-lint ansible-core
      - name: Run ansible-lint
        run: ansible-lint --profile=production -p
```

```yaml
# .github/workflows/ansible-lint.yml (matrix)
---
name: Ansible Lint
on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        profile: [min, safety, production]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - name: Install dependencies
        run: pip install ansible-lint ansible-core
      - name: Run ansible-lint
        run: ansible-lint --profile=${{ matrix.profile }} -p
```

#### GitLab CI

```yaml
# .gitlab-ci.yml
---
stages:
  - lint
  - deploy

ansible-lint:
  stage: lint
  image: python:3.14
  cache:
    key: ansible-lint
    paths:
      - .cache/ansible-lint
  before_script:
    - pip install ansible-lint ansible-core
    - mkdir -p .cache/ansible-lint
  script:
    - ansible-lint --profile=production
      --cache-dir .cache/ansible-lint
      -p --parseable-severity
  rules:
    - if: $CI_MERGE_REQUEST_ID
    - if: $CI_COMMIT_BRANCH == "main"
```

### Фильтрация по severity и тегам

```bash
# Только ошибки (error)
ansible-lint --severity=error

# Только warnings и выше
ansible-lint --severity=warning

# Фильтрация по тегам
ansible-lint --tags yaml,no-free-form
ansible-lint --skip-tags experimental

# Список правил
ansible-lint -L

# Список тегов
ansible-lint -T
```

### Автоисправление

```bash
# Исправить все автоматически исправимые ошибки
ansible-lint --write

# Исправить только определённые правила
ansible-lint --write yaml[line-length],name[casing]

# Dry-run: показать что будет исправлено
ansible-lint --write --dry-run
```

#### Правила, поддерживаемые автоисправлением

| Правило | Описание | Автоисправление |
| :--- | :--- | :--- |
| `yaml[truthy]` | Использование `true`/`false` вместо `yes`/`no` | Да |
| `yaml[line-length]` | Длинные строки | Да |
| `no-free-form` | Синтаксис `shell: echo` | Да |
| `fqcn[action-core]` | Полные имена модулей | Да |
| `name[casing]` | Капитализация имён задач | Да |
| `schema[meta]` | Валидация meta/main.yml | Да |

### Проверка ролей

```bash
# Проверить всю роль
ansible-lint roles/nginx/

# Проверить конкретные файлы
ansible-lint roles/*/tasks/main.yml

# Проверить роль с профилем
ansible-lint --role roles/common --profile production

# Проверить с указанием конфигурации
ansible-lint -c .ansible-lint roles/
```

### Автономный режим (offline)

```bash
# Без доступа к сети (не обновлять схемы)
ansible-lint --offline

# Использовать с кэшем
ansible-lint --offline --cache-dir .cache/ansible-lint
```

## Операции и команды

### Справочник по командам

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `ansible-lint` | Базовая проверка текущего каталога | `ansible-lint` |
| `ansible-lint <путь>` | Проверка конкретного файла или каталога | `ansible-lint playbooks/` |
| `ansible-lint -p` | Parseable формат для CI | `ansible-lint -p` |
| `ansible-lint --profile=<имя>` | Выбор профиля | `ansible-lint --profile=production` |
| `ansible-lint -x <правило>` | Исключить правило | `ansible-lint -x yaml[line-length]` |
| `ansible-lint --tags <тег>` | Включить только теги | `ansible-lint --tags yaml` |
| `ansible-lint --skip-tags <тег>` | Исключить теги | `ansible-lint --skip-tags experimental` |
| `ansible-lint --severity=<уровень>` | Минимальный severity | `ansible-lint --severity=error` |
| `ansible-lint --write` | Автоисправление | `ansible-lint --write` |
| `ansible-lint --write --dry-run` | Dry-run автоисправления | `ansible-lint --write --dry-run` |
| `ansible-lint --offline` | Автономный режим | `ansible-lint --offline` |
| `ansible-lint --generate-ignore` | Генерация `.ansible-lint-ignore` | `ansible-lint --generate-ignore` |
| `ansible-lint --cache-dir <путь>` | Указать кэш | `ansible-lint --cache-dir .cache/ansible-lint` |
| `ansible-lint --exclude <путь>` | Исключить путь | `ansible-lint --exclude vendor/` |
| `ansible-lint -c <файл>` | Указать конфиг | `ansible-lint -c .ansible-lint` |
| `ansible-lint -L` | Список правил | `ansible-lint -L` |
| `ansible-lint -T` | Список тегов | `ansible-lint -T` |
| `ansible-lint --strict` | Ненулевой код для warnings | `ansible-lint --strict` |
| `ansible-lint --version` | Проверка версии | `ansible-lint --version` |

### Распространённые конфигурации

#### Минимальная конфигурация для локальной разработки

```yaml
# .ansible-lint
---
profile: min

warn_list:
  - name[missing]
```

#### Production-конфигурация для CI/CD

```yaml
# .ansible-lint
---
profile: production

exclude_paths:
  - .git/
  - .github/
  - molecule/
  - vendor/
  - tests/

skip_list:
  - yaml[line-length]
  - name[missing]

cache-dir: .cache/ansible-lint
```

#### Air-gapped конфигурация (изолированная среда)

```yaml
# .ansible-lint
---
profile: production

offline: true

cache-dir: /opt/ansible-lint/cache

exclude_paths:
  - vendor/
```

## Устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Failed to download schema` | Нет доступа к сети | Используйте `--offline` или проверьте подключение |
| `No config file found` | Отсутствует `.ansible-lint` | Создайте конфигурационный файл или используйте `-c` |
| `rule not found` | Неправильный ID правила | Проверьте ID через `ansible-lint -L` |
| `Permission denied` | Нет прав на чтение файлов | Проверьте права доступа к плейбукам и ролям |
| `yaml[line-length]` | Строка превышает лимит | Увеличьте `max` в конфигурации или разбейте строку |
| `no-free-form` | Использован свободный синтаксис | Перейдите на декларативный формат с `cmd:` |
| `fqcn[action-core]` | Короткое имя модуля | Укажите полное имя, например `ansible.builtin.apt` |
| `no-changed-when` | `command`/`shell` без `changed_when` | Добавьте `changed_when: false` или `creates`/`removes` |
| `name[missing]` | Отсутствует описание задачи | Добавьте поле `name` с описанием действия |
| `no-log-password` | Секрет без `no_log: true` | Добавьте `no_log: true` к задаче |

## Лучшие практики

### Разработка

1. **Начинайте с минимального профиля**: используйте `--profile=min` локально для быстрой обратной связи, переключайтесь на `production` перед коммитом
2. **Интегрируйте в pre-commit**: блокируйте коммит при наличии ошибок — дешевле исправить сразу, чем в CI
3. **Не игнорируйте warnings без анализа**: используйте `warn_list` только для заведомо ложных срабатываний, документируйте причину
4. **Используйте `--dry-run` перед `--write`**: проверяйте, какие изменения будут применены
5. **Кэшируйте в CI**: укажите `--cache-dir` и используйте артефакты CI для ускорения проверок

### CI/CD

1. **Запускайте на всех изменениях**: плейбуки, роли, коллекции — всё, что касается Ansible, должно проходить линтинг
2. **Используйте parseable output**: `-p` или `-f json` для парсинга в CI-системах
3. **Гейт для деплоя**: `ansible-lint --profile=production` должен проходить без ошибок перед слиянием
4. **Matrix-запуски**: проверяйте разные профили (`min`, `safety`, `production`) для покрытия разных аспектов
5. **Артефакты**: сохраняйте вывод ansible-lint как артефакт сборки для аудита

### Безопасность

1. **Используйте `security` профиль для аудита**: он включает правила, проверяющие утечки секретов
2. **Never commit secrets**: ansible-lint с `no-log-password` найдет отсутствие `no_log`, но не найдет открытый секрет в коде — используйте `pre-commit` с `gitleaks` или `truffleHog`
3. **Проверяйте кастомные правила**: кастомные правила сами по себе могут содержать уязвимости — подвергайте их ревью
4. **Обновляйте ansible-lint**: новые версии включают обновлённые схемы и правила безопасности

### Производительность

1. **Исключайте тестовые каталоги**: `molecule/`, `tests/`, `vendor/` — они не относятся к production-коду
2. **Используйте кэш**: `--cache-dir` ускоряет повторные проверки в CI
3. **Offline-режим в air-gapped средах**: `--offline` не обновляет схемы, работает с локальным кэшем
4. **Ограничивайте scope**: проверяйте только изменённые файлы в PR, полную проверку оставляйте для коммита в main

## Дополнительная информация

- [ansible_testing_with_molecule.md](ansible_testing_with_molecule.md)
- [ansible_bad_practices.md](ansible_bad_practices.md)
