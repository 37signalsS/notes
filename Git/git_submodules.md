# Git Submodules — подмодули

## Определения

**`.gitmodules`** — файл конфигурации для Git submodules, хранящий пути, URL и ветки подмодулей.

**Git Submodule** — механизм Git, позволяющий встраивать один Git-репозиторий в другой как подкаталог, сохраняя их независимые истории.

---

## Базовые концепции

### Назначение .gitmodules

Файл конфигурации для Git submodules. Git записывает в него информацию при выполнении `git submodule add` и читает при `git submodule update`.

### Формат файла

```ini
[submodule "vendor/lib"]
    path = vendor/lib
    url = https://github.com/example/lib.git
    branch = main

[submodule "themes/default"]
    path = themes/default
    url = https://github.com/example/theme.git
```

### Основные директивы

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `path` | Путь к подмодулю в основном репозитории | `vendor/lib` |
| `url` | URL удалённого репозитория подмодуля | `https://github.com/example/lib.git` |
| `branch` | Ветка подмодуля для отслеживания | `main` |
| `update` | Стратегия обновления | `checkout`, `rebase`, `merge` |
| `shallow` | Поверхностное клонирование подмодуля | `true` |

### Особенности submodules

- **Расположение:** Файл находится в корне репозитория
- **Автоматическая инициализация:** `git clone` не загружает содержимое подмодулей автоматически
- **Версионирование:** Подмодули отслеживают конкретный коммит, а не диапазон версий
- **Проблемы:** Вложенные `.git` директории, забывчивость обновления создают запутанные состояния
- **Применение:** Вендоринг контролируемого кода, монорепозитории с частичной выгрузкой

---

## Практические сценарии

### Сценарий 1: Добавление подмодуля

```bash
# Добавить подмодуль
git submodule add https://github.com/example/lib.git vendor/lib

# Закоммитить изменения
git add .gitmodules vendor/lib
git commit -m "Add lib submodule"
```

### Сценарий 2: Клонирование репозитория с подмодулями

```bash
# Клонировать с подмодулями
git clone --recurse-submodules <url_репозитория>

# Или инициализировать после клонирования
git clone <url_репозитория>
cd <репозиторий>
git submodule update --init --recursive
```

### Сценарий 3: Обновление подмодулей

```bash
# Обновить все подмодули до закоммиченных версий
git submodule update

# Обновить с инициализацией новых
git submodule update --init

# Обновить с рекурсией (вложенные подмодули)
git submodule update --init --recursive

# Обновить до последних коммитов ветки
git submodule update --remote
```

### Сценарий 4: Проверка статуса подмодулей

```bash
# Показать статус всех подмодулей
git submodule status

# Показать подробную информацию
git submodule foreach --recursive git status

# Проверить, какие подмодули изменены
git diff --submodule
```

### Сценарий 5: Удаление подмодуля

```bash
# Деинициализировать подмодуль
git submodule deinit vendor/lib

# Удалить из .git/modules
rm -rf .git/modules/vendor/lib

# Удалить из working tree
git rm vendor/lib

# Удалить запись из .gitmodules (вручную или через config)
git config -f .gitmodules --remove-section submodule.vendor/lib
git add .gitmodules

# Закоммитить изменения
git commit -m "Remove lib submodule"
```

---

## Дополнительная информация

### Официальные ресурсы

- **Документация Git по submodules:** [git-scm.com/book/en/v2/Git-Tools-Submodules](https://git-scm.com/book/en/v2/Git-Tools-Submodules)
- **Submodule Tips:** [git-scm.com/docs/git-submodule](https://git-scm.com/docs/git-submodule)

### Связанные темы

Обзор специальных файлов в [git_special_files_overview.md](./git_special_files_overview.md). Сравнение submodules и subtree в [git_submodules_and_subtree.md](./git_submodules_and_subtree.md).
