# ansible-lint: проверка качества плейбуков и ролей

## Определения

- **ansible-lint** — статический анализатор кода, проверяющий плейбуки, роли и коллекции на соответствие best practices
- **Rule** — правило проверки (например, `yaml[line-length]`, `no-free-form`, `name[missing]`)
- **Profile** — набор правил, сгруппированных по назначению (production, safety, min)
- **Skip tag** — тег для пропуска конкретного правила в задаче или файле
- **Mock role** — заглушка для тестирования ansible-lint без реальных зависимостей
- **Exclude path** — путь, исключённый из проверки
- **Parseable output** — формат вывода, пригодный для парсинга CI/CD

## Основные концепции

1. Установка: `pip install ansible-lint`, `ansible-lint --version`
2. Профили: `min`, `safety`, `shared`, `production`, `moderation`
3. Конфигурация: `.ansible-lint`, `ansible-lint.yml`, `pyproject.toml`
4. Правила: `yaml`, `no-free-form`, `name[missing]`, `fqcn`, `no-changed-when`, `command-instead-of-module`
5. Интеграция с CI/CD: GitHub Actions, GitLab CI, pre-commit hooks
6. Исправление ошибок: auto-fix через `ansible-lint --fix`

## Практические сценарии

### Запуск ansible-lint в корне проекта

```bash
ansible-lint
ansible-lint -p                # parseable формат для CI
ansible-lint --profile=production  # строгий профиль
ansible-lint -x yaml[line-length]  # пропустить правило
```

### Настройка `.ansible-lint` конфигурации

```yaml
# .ansible-lint
exclude_paths:
  - .git/
  - .github/
  - molecule/
  - vendor/

skip_list:
  - yaml[line-length]
  - no-free-form

warn_list:
  - experimental
  - name[missing]

enable_list:
  - fqcn

profiles:
  min:
    # включает минимальный набор
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

# Ошибка: fqcn
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

### Интеграция с pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/ansible/ansible-lint
    rev: v24.2.0
    hooks:
      - id: ansible-lint
        args:
          - --profile=production
          - -x yaml[line-length]
```

### Настройка в GitHub Actions workflow

```yaml
# .github/workflows/ansible-lint.yml
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
          python-version: "3.11"
      - name: Install dependencies
        run: |
          pip install ansible-lint ansible-core
      - name: Run ansible-lint
        run: ansible-lint --profile=production -p
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

### Проверка ролей

```bash
ansible-lint roles/nginx/
ansible-lint roles/*/tasks/main.yml
ansible-lint --role roles/common
```

## Дополнительная информация

- [ansible_testing_with_molecule.md](ansible_testing_with_molecule.md)
- [ansible_bad_practices.md](ansible_bad_practices.md)
- [ansible_test.md](ansible_test.md)

---

## Профили: min, safety, shared, production, moderation

### Различия профилей

| Профиль | Описание | Кол-во правил | Использование |
| :--- | :--- | :--- | :--- |
| **min** | Минимальный набор — только синтаксические ошибки | ~15 | Быстрая проверка в CI, локальная разработка |
| **safety** | Проверки безопасности — no-log, хардкод паролей | ~30 | Pre-commit, security review |
| **shared** | Базовые проверки для шаред-контента (роли, коллекции) | ~40 | Публикация ролей в Galaxy |
| **moderation** | Базовые проверки + рекомендации | ~50 | Pull request review |
| **production** | Полный набор для production-качества | ~80+ | CI/CD pipeline, gate для деплоя |

### Как выбрать профиль

```
Разработка (локально):     ansible-lint --profile=min
Pre-commit hook:           ansible-lint --profile=safety
Pull Request:              ansible-lint --profile=shared
CI/CD pipeline:            ansible-lint --profile=production
Ansible Galaxy publish:    ansible-lint --profile=shared
```

### Настройка профиля в конфигурации

```yaml
# .ansible-lint
profile: production  # Глобальный профиль по умолчанию

# Можно переопределить для отдельных каталогов
# В roles/.ansible-lint:
# profile: shared
```

---

## Кастомные правила

### Создание собственного правила

```python
# custom_rules/require_handler_notify.py
"""Кастомное правило: все.tasks с变更状态 должны иметь notify."""
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

        # Модули, которые изменяют состояние
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

### Регистрация кастомного правила

```yaml
# .ansible-lint
rulesdir:
  - ./custom_rules

# Или через environment variable
# ANSIBLE_LINT_RULES_DIR=./custom_rules ansible-lint
```

### Кастомный профиль

```yaml
# .ansible-lint
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

---

## Интеграция с CI/CD: продвинутые сценарии

### GitLab CI с кэшированием

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - deploy

ansible-lint:
  stage: lint
  image: python:3.11
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

### Pre-commit с опциями

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/ansible/ansible-lint
    rev: v24.12.0
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

### GitHub Actions с matrix

```yaml
# .github/workflows/ansible-lint.yml
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
          python-version: "3.11"
      - name: Install dependencies
        run: pip install ansible-lint ansible-core
      - name: Run ansible-lint
        run: ansible-lint --profile=${{ matrix.profile }} -p
```

---

## Синтаксис фильтрации по severity

```bash
# Только ошибки (error)
ansible-lint -L | grep -E "^ID.*error"

# Только warnings и выше
ansible-lint --severity=warning

# Игнорировать info
ansible-lint --severity=warning

# Фильтрация по тегам
ansible-lint --tags yaml,no-free-form
ansible-lint --skip-tags experimental
```

---

## Автоисправление (ansible-lint --fix)

```bash
# Исправить все автоматически исправимые ошибки
ansible-lint --fix

# Исправить только определённые правила
ansible-lint --fix -t yaml

# Dry-run: показать что будет исправлено
ansible-lint --fix --dry-run
```

### Правила, поддерживаваемые автоисправлением

| Правило | Описание | Автоисправление |
| :--- | :--- | :--- |
| `yaml[truthy]` | Использование `true`/`false` вместо `yes`/`no` | Да |
| `yaml[line-length]` | Длинные строки | Да |
| `no-free-form` | Синтаксис `shell: echo` | Да |
| `fqcn[action-core]` | Полные имена модулей | Да |
| `name[casing]` | Капитализация имен задач | Да |
| `schema[meta]` | Валидация meta/main.yml | Да |
