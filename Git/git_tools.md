# Git TUI and CLI Tools

## Определения

**TUI (Terminal User Interface)** — текстовый пользовательский интерфейс, работающий внутри терминала, предоставляющий интерактивные элементы управления (меню, кнопки, списки) без графического сервера.

**Git TUI-инструменты** — утилиты для визуализации истории Git, управления ветками и коммитами непосредственно в терминале.

---

## Базовые концепции

### Категории инструментов

| Категория | Инструменты | Назначение |
| :--- | :--- | :--- |
| **Визуализация истории** | `git-igitt`, `tig`, `gitui` | Просмотр графа коммитов и веток |
| **Полноценные клиенты** | `lazygit`, `gitui` | Управление репозиторием (add, commit, push, merge) |
| **Просмотр diff** | `tig`, `git-igitt` | Быстрый просмотр изменений |
| **Разрешение конфликтов** | `lazygit`, `git mergetool` | Интерактивное разрешение конфликтов слияния |

### Основные инструменты

**git-igitt** — специализированный инструмент для визуализации истории Git с акцентом на читаемые графы веток. Написан на Go.

**lazygit** — один из самых популярных TUI-клиентов для Git, предоставляющий полный спектр возможностей управления репозиторием. Написан на Go.

**tig** — классический TUI-инструмент для просмотра истории и diff-ов. Написан на C.

**gitui** — быстрый TUI-клиент, написанный на Rust, с акцентом на производительность.

---

## Практические сценарии

### Сценарий 1: Установка и запуск git-igitt

```bash
# Установка через cargo (требуется Rust)
cargo install git-igitt

# Запуск в корне Git-репозитория
git-igitt
```

**Навигация:**

| Клавиша | Действие |
| :--- | :--- |
| Стрелки вверх/вниз | Перемещение по списку коммитов |
| Стрелки влево/вправо | Переключение между списком коммитов и панелью diff |
| Esc / Q | Выход |

### Сценарий 2: Установка и запуск lazygit

```bash
# macOS (Homebrew)
brew install lazygit

# Linux (Ubuntu/Debian)
sudo add-apt-repository ppa:lazygit-team/release
sudo apt-get update && sudo apt-get install lazygit

# Через Go
go install github.com/jesseduffield/lazygit@latest
```

```bash
# Запуск в корне репозитория
lazygit

# Запуск с указанием директории
lazygit -p /path/to/repo
```

**Основные панели:**

| Панель | Описание |
| :--- | :--- |
| Files | Добавление файлов в индекс (пробел), просмотр diff |
| Worktrees | Управление рабочими деревьями |
| Local branches | Создание, переключение, удаление веток |
| Remotes | Управление удалёнными репозиториями |
| Tags | Создание и просмотр тегов |
| Stash | Управление stash |

### Сценарий 3: Установка и использование tig

```bash
# macOS
brew install tig

# Ubuntu/Debian
sudo apt-get install tig

# CentOS/RHEL
sudo yum install tig
```

```bash
# Просмотр всей истории
tig

# История конкретного файла
tig <файл>

# Статус репозитория
tig status

# Список веток
tig branch

# Поиск по коммитам (внутри tig)
/
```

### Сценарий 4: Установка и запуск gitui

```bash
# macOS (Homebrew)
brew install gitui

# Ubuntu/Debian (через apt, если доступен)
sudo apt install gitui

# Через cargo (Rust)
cargo install gitui
```

```bash
# Запуск в корне репозитория
gitui
```

**Клавиши по умолчанию:**

| Клавиша | Действие |
| :--- | :--- |
| j / k | Навигация вверх/вниз |
| h / l | Навигация влево/вправо |
| s | Stage файл |
| c | Commit |
| p | Push |
| q | Quit / Back |

### Сценарий 5: Сравнение инструментов

| Критерий | lazygit | tig | gitui | git-igitt |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | Go | C | Rust | Go |
| **Полное управление** | Да | Нет | Да | Нет |
| **Визуализация графа** | Да | Да | Да | Да (лучшая) |
| **Разрешение конфликтов** | Да | Нет | Да | Нет |
| **Производительность** | Высокая | Очень высокая | Очень высокая | Высокая |
| **Лучше для** | Повседневной работы | Быстрого просмотра | Скорости | Анализа истории |

---

## Дополнительная информация

### Официальные ресурсы

* **git-igitt:** [github.com/mlange-42/git-igitt](https://github.com/mlange-42/git-igitt)
* **lazygit:** [github.com/jesseduffield/lazygit](https://github.com/jesseduffield/lazygit)
* **tig:** [jonas.github.io/tig](https://jonas.github.io/tig/)
* **gitui:** [github.com/extrawurst/gitui](https://github.com/extrawurst/gitui)

### Связанные темы

Визуализация истории в [git_basics.md](./git_basics.md). Манипуляции с историей в [git_history_manipulation.md](./git_history_manipulation.md). Шифрование файлов в репозитории — в [git_configuration.md](./git_configuration.md) и [git_attributes.md](./git_attributes.md).
