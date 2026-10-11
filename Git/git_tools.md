# Инструменты Git TUI и CLI

**Актуально для:** Git 2.35+

## Определения

**TUI (Terminal User Interface)** — текстовый пользовательский интерфейс, работающий внутри терминала. Предоставляет интерактивные элементы управления (меню, списки, панели) без необходимости использования графического сервера (X11/Wayland).

**Git TUI-инструменты** — утилиты для визуализации истории Git, интерактивного стейджинга и управления репозиторием непосредственно в терминале.

**CLI-расширения (Pagers)** — инструменты, улучшающие стандартный вывод команд Git (например, `git diff` или `git log`), добавляя синтаксическую подсветку, выравнивание и интерактивность.

**Forge CLI** — официальные инструменты командной строки от провайдеров хостинга Git (GitHub, GitLab), позволяющие управлять Pull/Merge Requests, Issue и CI/CD прямо из терминала.

**Jujutsa (jj)** — современная система контроля версий, полностью совместимая с Git, но предлагающая иную архитектуру (отсутствие индекса, автоматический rebase, безопасность операций).

**fzf** — универсальный нечёткий поиск (fuzzy finder) для терминала. Интегрируется с Git и любыми другими утилитами, предоставляя интерактивный выбор из списков (веток, коммитов, файлов и т.д.).

**forgit** — набор обёрток над Git-командами на базе `fzf`. Делает интерактивными такие операции, как `git add`, `git log`, `git checkout`, `git rebase -i` и многие другие, предоставляя непрерывный просмотр изменений в окне fzf.

**jjui** — TUI-клиент для Jujutsa (jj), предоставляющий интерактивный интерфейс для управления ветками, коммитами и операциями rebase в стиле lazygit, но для системы Jujutsa.

**difftastic** — структурный дифф-инструмент, который анализирует синтаксис кода (через tree-sitter парсеры) и сравнивает логические блоки (функции, циклы), а не строки. Понимает более 30 языков программирования.

**tig** — классическая ncurses-интерфейс для Git на языке C. Функционирует как браузер репозитория, помощник для построчного стейджинга (chunk-level) и пейджер для вывода команд Git.

**diff-so-fancy** — устаревшая альтернатива git-delta, улучшающая читаемость diff, но менее функциональная и неактивно развивается.

---

## Базовые концепции

### Категории инструментов

| Категория | Инструменты | Назначение |
| :--- | :--- | :--- |
| **Полноценные клиенты** | `lazygit`, `gitui`, `jjui` | Управление всем жизненным циклом (add, commit, rebase, push) |
| **Визуализация и Diff** | `git-delta`, `tig`, `difftastic` | Улучшение читаемости изменений и графа коммитов |
| **Интерактивный CLI** | `forgit`, `fzf`, `git-absorb` | Быстрый поиск, нечеткий выбор и автоматизация рутины |
| **Forge (GitHub/GitLab)** | `gh`, `glab` | Управление PR/MR, Issue и пайплайнами CI/CD |
| **Альтернативный VCS** | `jj` (Jujutsu) | Совместимая с Git система с автоматическим rebase и отменой действий |

### Основные TUI-клиенты

*   **lazygit** (v0.66.0): Самый популярный и функциональный TUI-клиент (Go). Поддерживает сложные интерактивные перебазирования (rebase), построчное индексирование (staging) и визуализацию графа. Начиная с v0.66.0 стейджинг hunks выполняется непосредственно из основного представления — отдельная панель стейджинга удалена.

*   **gitui** (v0.28.1): Клиент на Rust для максимальной производительности на огромных монорепозиториях. Имеет строгий панельный интерфейс. Наиболее эффективен при работе с репозиториями >100GB или миллионами файлов.

*   **tig** (v2.6.1): Классический инструмент на C (ncurses). В основном используется для быстрого просмотра истории, стейджинга отдельных строк (hunks) и как пейджер для вывода команд Git.

### Современные CLI-улучшения

*   **git-delta** (0.20.1): Современный пейджер (замена `less`). Добавляет подсветку синтаксиса (через bat-темы), нумерацию строк, боковой (side-by-side) просмотр diff, улучшенное отображение merge-конфликтов, улучшенный `git blame` и автоматическее определение светлой/тёмной темы терминала.

*   **difftastic** (0.71.0): Дифференциальный инструмент, понимающий структуру кода (AST). Сравнивает не строки, а логические блоки (функции, циклы). Поддерживает более 30 языков программирования через tree-sitter парсеры.

*   **git-absorb** (0.9.0): Утилита для автоматического разнесения изменений по коммитам (`commit --fixup`) на основе затронутых строк. Поддерживает флаг `--and-rebase` для автоматического выполнения `git rebase -i --autosquash` после создания fixup-коммитов.

*   **forgit**: Набор интерактивных обёрток над Git на базе `fzf`. Делает интерактивными: `git add`, `git log`, `git diff`, `git show`, `git checkout`, `git rebase -i`, `git stash`, `git cherry-pick`, `git blame`, `git worktree` и многие другие команды.

*   **fzf**: Универсальный нечёткий поиск для терминала. Является фундаментом для `forgit` и может использоваться для собственных интерактивных Git-скриптов.

*   **gh / glab**: Официальные CLI для взаимодействия с GitHub и GitLab. Позволяют создавать PR, проверять статус CI/CD и управлять секретами.

### Альтернативный VCS: Jujutsu (jj) + jjui

*   **Jujutsa (jj)** (v0.46.0): Современная распределяемая система контроля версий с полной совместимостью с Git. Ключевые особенности: отсутствие обязательного индекса (staging area), автоматический rebase, операции отменяемые (undo/redo), работа с "стеками" веток и т. д. Требует Git 2.42+ для полной функциональности.

*   **jjui** (idursun/jjui): TUI-клиент для Jujutsa в стиле lazygit. Предоставляет панельный интерфейс для просмотра коммитов, управления ветками, выполнения rebase и других операций.

---

## Предварительные требования

*   **Git 2.35+** — для конфигурационных примеров, использующих `conflictStyle = zdiff3` (улучшенный diff3 с whitespace-нормализацией). Для использования `git switch`/`git restore` требуется Git 2.23+.
*   **fzf 0.60.0+** — для forgit (меньшие версии могут работать, но рекомендуется 0.60.0+).
*   **jq** — для некоторых функций forgit (например, `forgit ignore` для генерации `.gitignore`).
*   **bat** — для синтаксического highlighting-а в `git-delta` и `forgit`.
*   **Точки доступа (Forge):** `gh` требует аутентификации через `gh auth login`; `glab` — через `glab auth login`.

---

## Практические сценарии

### Сценарий 1: Настройка git-delta (рекомендуемый diff-пейджер)

`git-delta` значительно улучшает читаемость `git diff` и `git show`, добавляя подсветку синтаксиса, боковой просмотр и улучшенное отображение merge-конфликтов.

**Установка:**

```bash
# macOS
brew install git-delta

# Debian / Ubuntu
sudo apt install git-delta

# Fedora
sudo dnf install git-delta

# Arch Linux
sudo pacman -S git-delta

# Cargo (Rust)
cargo install git-delta
```

**Настройка в `~/.gitconfig`:**

```ini
[core]
    pager = delta

[interactive]
    diffFilter = delta --color-only

[delta]
    navigate = true          # переход между чанками по n/N
    dark = true              # использовать темную тему (auto-detection при отсутствии)
    side-by-side = true      # включить боковой просмотр по умолчанию
    line-numbers = true

[merge]
    conflictStyle = zdiff3   # улучшенный diff3 (требует Git 2.35+)
```

**Валидация:**

```bash
# Проверить, что delta используется как пейджер
git diff | head -5
# → вывод с подсветкой синтаксиса и нумерацией строк

# Проверить версию
delta --version
# → git-delta 0.20.1
```

> **Примечание:** В официальной документации git-delta используется `dark = true` вместо `light = false`. Оба параметра эквивалентны, но `dark = true` является рекомендуемым в текущей документации.

**Дополнительные возможности:**

```ini
[delta]
    # Тема подсветки (все темы bat доступны)
    syntax-theme = "GitHub"

    # Гиперссылки на коммиты и файлы (для терминалов, поддерживающих OSC 8)
    hyperlinks = true

    # Только изменённые строки (без контекста)
    # используется в сочетании с --no-context

    # Эмуляция diff-so-fancy
    diff-so-fancy = true      # вместо side-by-side
```

**Валидация дополнительной конфигурации:**

```bash
# Проверить доступные темы синтаксиса
delta --show-syntax-themes --dark
# → отображает превью всех доступных тем
```

### Сценарий 2: Использование difftastic как внешнего diff-инструмента Git

`difftastic` сравнивает файлы на основе их синтаксиса (AST), а не построчно. Это особенно ценно при рефакторинге, где код перенесён или изменена структура без изменения логики.

> **Важно:** Git ≤ 2.43.1 может зависнуть при использовании `diff.external` при изменении прав файлов. Если используется Git < 2.44, используйте `difftool` вместо `diff.external`.

**Установка:**

```bash
# macOS
brew install difftastic

# Debian / Ubuntu
sudo apt install difftastic

# Fedora
sudo dnf install difftastic

# Arch Linux (AUR)
yay -S difftastic

# Cargo (Rust)
cargo install difftastic
```

**Настройка через alias (рекомендуемый способ):**

```ini
[alias]
    # difftastic для git log, git show, git diff
    dlog = -c diff.external=difft log --ext-diff
    dshow = -c diff.external=difft show --ext-diff
    ddiff = -c diff.external=difft diff
```

**Настройка как difftool:**

```ini
[difftool "difftastic"]
    cmd = difft "$MERGED" "$LOCAL" "abcdef1" "100644" "$REMOTE" "abcdef2" "100644"

[difftool]
    prompt = false

[pager]
    difftool = true

[diff]
    tool = difftastic
```

**Использование:**

```bash
# Однократный запуск difftastic для любой команды
git -c diff.external=difft diff

# Через alias
git ddiff
# → структурный diff с подсветкой синтаксиса

# Для просмотра конфликтов слияния
difft file_with_conflicts.py
```

**Валидация:**

```bash
# Проверить версию и поддерживаемые языки
difft --version
# → difftastic 0.71.0

# Список поддерживаемых языков
difft --list-languages
# → показывает 30+ языков

# Быстрая проверка: если вывод содержит "Python" вместо "text", значит парсер работает
```

> **Ограничения:** Difftastic масштабируется плохо на файлы с большим количеством изменений и может использовать много памяти. Также не поддерживает генерацию патчей и AST-слияния.

### Сценарий 3: Автоматический fixup с git-absorb

Когда нужно внести правки в старые коммиты по результатам ревью, `git-absorb` делает это автоматически, создавая `fixup!`-коммиты на основе затронутых строк.

**Установка:**

```bash
# macOS
brew install git-absorb

# Debian / Ubuntu
sudo apt install git-absorb

# Fedora
sudo dnf install git-absorb

# Arch Linux
sudo pacman -S git-absorb

# Cargo (Rust)
cargo install git-absorb
```

**Алгоритм работы:**

1.  Внесите изменения в файлы.
2.  Добавьте изменения в индекс:
    ```bash
    git add $FILES_YOU_FIXED
    git add .
    ```
3.  Запустите:
    ```bash
    git absorb --and-rebase
    ```
4.  Инструмент найдет коммиты, которые меняли эти же строки, создаст для них `fixup!`-коммиты и автоматически выполнит `git rebase -i --autosquash`.

> **Флаг `--and-rebase`:** Автоматически применяет fixup-коммиты через интерактивный rebase. Если флаг не указан, fixup-коммиты создаются, но rebase нужно запустить вручную.

**Альтернативный подход (без автоматического rebase):**

```bash
git add .
git absorb
# → созданы fixup! коммиты

# Проверить созданные коммиты
git log --oneline -5
# → fixup! <original-commit-message>

# Вручную выполнить rebase
GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash main
# → GIT_SEQUENCE_EDITOR=true позволяет выполнить rebase без открытия редактора
```

**Валидация:**

```bash
# Проверить, что fixup-коммиты созданы
git log --oneline -3 --grep="fixup"

# После rebase проверить чистоту истории
git log --oneline -5 main
# → история должна быть линейной без fixup-коммитов
```

> **Важно:** `git-absorb` работает только с коммитами в диапазоне `HEAD~10` по умолчанию. Используйте `--base <ref>` для изменения диапазона. Также инструмент рассчитан на локальную историю — не используйте его с уже запушенными коммитами.

### Сценарий 4: Полноценное управление через lazygit

`lazygit` (v0.66.0) — TUI-клиент для полного управления Git-репозиторием с клавиатурными комбинациями и визуализацией графа коммитов.

**Установка:**

```bash
# macOS
brew install lazygit

# Debian / Ubuntu (25.10+)
sudo apt install lazygit

# Debian / Ubuntu (старые версии)
LAZYGIT_VERSION=$(curl -s https://api.github.com/repos/jesseduffield/lazygit/releases/latest | grep -o '"tag_name": *"v[^"]*"' | cut -d'"' -f4 | sed 's/^v//')
curl -Lo lazygit.tar.gz "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_$(uname -m | sed -e 's/aarch64/arm64/').tar.gz"
tar xf lazygit.tar.gz lazygit
sudo install lazygit -D -t /usr/local/bin/

# Fedora
sudo dnf install lazygit

# Arch Linux
sudo pacman -S lazygit

# Go
go install github.com/jesseduffield/lazygit@latest
```

**Ключевые возможности (v0.66.0):**

1.  **Стейджинг hunks и строк:** Нажмите `0` на изменённом файле, чтобы сфокусировать его diff в основном окне. `space` для добавления hunk в индекс, `a` для перехода в режим построчного выбора, `v` для выбора диапазона строк.

2.  **Интерактивный Rebase:** Нажмите `i` на коммите для начала rebase. `s` — squash, `f` — fixup, `d` — drop, `e` — edit. `m` — меню опций rebase (continue, skip, abort).

3.  **Worktree:** Нажмите `w` в представлении веток для создания worktree и переключения на него.

4.  **Undo/Redo:** `z` — отмена, `Shift+z` — повтор. Работает через reflog, отменяет действия с ветками и коммитами.

5.  **Commit graph:** Увеличение окна (`+`/`_`) показывает граф коммитов с цветовой кодировкой по авторам.

6.  **Сравнение коммитов:** `Shift+w` на коммите для пометки, затем выбор второго коммита для сравнения.

7.  **Bisect:** Нажмите `b` в представлении коммитов для начала `git bisect`.

**Алиас и настройка цвета терминала:**

```bash
# Добавить алиас в ~/.zshrc или ~/.bashrc
alias lg='lazygit'
```

Конфиг lazygit находится в `~/.config/lazygit/config.yml`.

**Валидация:**

```bash
lazygit --version
# → commit=v0.66.0

# Запустить в репозитории
lazygit
# → открывается TUI с панелями: ветки, коммиты, файлы, diff
```

> **Важно:** Начиная с v0.66.0 отдельная панель стейджинга удалена. Стейджинг hunks теперь выполняется непосредственно из основного представления (main view), что упрощает навигацию.

### Сценарий 5: Работа с Pull Requests через GitHub/GitLab CLI

> **Ссылка**: Комплексная документация GitHub CLI (`gh`) — управление PR, Releases, Actions, API-вызовы, aliases, extensions — в **[dedicated файле](../Github_CI/github_cli.md)**.

**GitHub CLI (gh):**

```bash
# Создать PR с заполнением из заголовка коммита и открытием в браузере
gh pr create --fill --web

# Просмотреть статус текущих проверок CI/CD
gh pr checks

# Просмотреть дифф текущего PR
gh pr diff

# Список открытых issue с фильтром по метке
gh issue list --label "bug"

# Одобрение и слияние PR
gh pr review <number> --approve
gh pr merge <number> --squash --delete-branch
```

**GitLab CLI (glab):**

```bash
# Создать Merge Request
glab mr create -f -w

# Список MR
glab mr list

# Одобрение MR
glab mr approve <number>

# Слияние MR
glab mr merge <number> --squash --yes
```

**Валидация:**

```bash
gh auth status
# → аутентификация подтверждена

gh pr list --state merged --limit 3
# → список последних смёрженных PR
```

> Подробно о воркфлоу и CI/CD интеграции через `gh`/`glab` — в файле **[Рабочие процессы в Git](./git_workflows.md)**.

### Сценарий 6: Быстрый просмотр истории через tig

`tig` — классический ncurses-интерфейс для просмотра истории Git и стейджинга изменений на уровне hunks.

**Установка:**

```bash
# macOS
brew install tig

# Debian / Ubuntu
sudo apt install tig

# Fedora
sudo dnf install tig

# Arch Linux
sudo pacman -S tig
```

**Основные режимы работы:**

```bash
# Просмотр истории в интерактивном интерфейсе
tig
# → основной режим: дерево файлов и журнал коммитов

# Просмотр diff конкретного коммита
tig show

# Просмотр состояния (status) с возможностью стейджинга
tig status

# Просмотр изменений в рабочем каталоге
tig diff

# Просмотр рефлога
tig reflog
```

**Настройка через `~/.tigrc`:**

```bash
# Пример: добавить собственную команду
bind generic <Ctrl-P> = :!git push
```

**Валидация:**

```bash
tig --version
# → tig 2.6.1

# Запустить в репозитории — интерфейс должен отобразиться корректно
```

> **Ограничение:** `tig` не поддерживает все функции современных TUI-клиентов (cherry-pick, rebase, worktree). Для полноценного управления используйте `lazygit` или `gitui`.

### Сценарий 7: Интерактивные Git-команды через forgit + fzf

`forgit` — набор интерактивных обёрток над Git на базе `fzf`, который делает быстрый поиск и нечёткий выбор доступными для типовых Git-операций.

**Установка (fzf):**

```bash
# macOS
brew install fzf

# Debian / Ubuntu
sudo apt install fzf

# Fedora
sudo dnf install fzf

# Arch Linux
sudo pacman -S fzf

# Самостоятельная установка (для систем с устаревшей версией)
git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf
~/.fzf/install
```

**Установка (forgit):**

```bash
# macOS
brew install forgit

# Debian / Ubuntu
sudo apt install forgit

# Arch Linux (AUR)
yay -S forgit

# Остальные системы — ручная установка через плагины
# Zsh (oh-my-zsh):
git clone https://github.com/wfxr/forgit ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/forgit

# Zsh (zinit):
zinit load wfxr/forgit

# Bash:
git clone https://github.com/wfxr/forgit ~/.config/forgit
echo 'source ~/.config/forgit/forgit.plugin.sh' >> ~/.bashrc
```

**Ключевые команды forgit:**

| Команда | Описание |
| :--- | :--- |
| `ga` | Интерактивный `git add` selector |
| `gd` | Интерактивный `git diff` viewer |
| `gi` | Интерактивный `.gitignore` генератор |
| `glo` | Интерактивный `git log` viewer |
| `gcb` / `gsw` | Интерактивный `git checkout/switch <branch>` |
| `grb` | Интерактивный `git rebase -i` selector |
| `gss` | Интерактивный `git stash` viewer |
| `gcp` | Интерактивный `git cherry-pick` selector |
| `gbl` | Интерактивный `git blame` selector |
| `gfu` | Интерактивный `git commit --fixup && git rebase -i --autosquash` |

**Алиасы Git:**

```bash
# Использовать forgit как git-подкоманду
git forgit log
git forgit add
git forgit diff

# Или через git alias
git config --global alias.cf 'forgit checkout_file'
```

**Валидация:**

```bash
# Проверить, что forgit загружен
type forgit::add
# → forgit::add: function

# Или проверить наличие обёрток
which git-forgit
```

> **Требование:** forgit требует `fzf` 0.60.0+. Для интеграции с `git-delta` в preview panes установите `FORGIT_PREVIEW_PAGER=delta`.

### Сценарий 8: Jujutsu (jj) + jjui

`Jujutsa (jj)` — современная система контроля версий с полной совместимостью с Git. `jjui` предоставляет TUI-интерфейс в стиле lazygit.

**Установка jj:**

```bash
# macOS
brew install jujutsu

# Debian / Ubuntu
sudo apt install jujutsu

# Fedora
sudo dnf install jujutsu

# Arch Linux (AUR)
yay -S jujutsu

# Cargo (Rust)
cargo install jujutsu
```

**Базовые команды jj:**

```bash
# Инициализация репозитория (автоматически создаёт Git-репозиторий)
jj git init

# Создание коммита
jj commit -m "feat: add new feature"

# Просмотр статуса
jj status

# Интерактивный rebase
jj rebase -i

# Отмена последнего действия
jj undo

# Работа с ветками
jj branch list
jj branch create feature/new

# Вставить коммит перед/после указанного revset
jj commit -m "fix: patch" --insert-before HEAD
jj commit -m "fix: patch" --insert-after HEAD
```

**Установка jjui:**

```bash
# jjui доступен через Cargo
cargo install jjui

# Или через GitHub релизы
# https://github.com/idursun/jjui/releases
```

**Валидация:**

```bash
jj --version
# → jj 0.46.0

# Проверить, что jj синхронизируется с Git
jj git sync
```

> **Требование:** jj требует Git 2.42+ для полной функциональности (особенно для `jj workspace add`).

---

## Сравнение инструментов

| Критерий | lazygit | gitui | jj (Jujutsa) | git-delta | difftastic | git-absorb |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Язык** | Go | Rust | Rust | Rust | Rust | Rust |
| **Тип** | Full TUI | Full TUI | CLI / VCS | CLI Pager | CLI Diff | CLI Utility |
| **Индекс (Staging)** | Да | Да | Нет (авто) | Н/Д | Н/Д | Нет (авто) |
| **Производительность** | Высокая | Экстремальная | Высокая | Высокая | Средняя | Высокая |
| **Сложный Rebase** | Отлично | Базово | Автоматически | Н/Д | Н/Д | Автоматически (fixup) |
| **Side-by-side Diff** | Да (через пейджер) | Да | Через пейджер | Да (лучший) | Нет | Н/Д |
| **AST-анализ** | Нет | Нет | Нет | Нет | Да | Нет |
| **Undo/Redo** | Да (reflog) | Ограниченно | Да (встроенный) | Н/Д | Н/Д | Н/Д |

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `delta: command not found` | git-delta не установлен или не в `$PATH` | Проверить `which delta`; добавить `~/.cargo/bin` или `$(brew --prefix)/bin` в `$PATH` |
| Цвета в `delta` не отображаются | Терминал не поддерживает 256 цветов или `NO_COLOR` установлен | Убедиться, что `TERM` не `dumb`; проверить `echo $NO_COLOR` |
| `difft: command not found` при `diff.external` | difftastic установлен, но исполняемый файл называется `difft`, а не `difftastic` | Использовать `difft` в конфигурации, а не `difftastic` |
| `forgit: command not found` | Плагин не загружен в shell | Проверить, что `forgit.plugin.zsh` (или `.sh`) source-ится в `.zshrc` (или `.bashrc`); перезапустить shell |
| `fzf: command not found` | fzf не установлен или не в `$PATH` | Установить fzf: `brew install fzf` или ручная установка через `~/.fzf/install` |
| `git absorb` создаёт fixup для неправильного коммита | Диапазон по умолчанию — 10 коммитов; целевой коммит дальше | Указать базу: `git absorb --base <ref>`; проверить, что изменённые строки принадлежат нужному коммиту |
| `git absorb` не находит изменений для распределения | Изменения не добавлены в индекс (staging area) | `git absorb` работает только с содержимым индекса. Выполните `git add .` или `git add <files>` перед запуском |
| `lazygit` не запускается / падает | Конфигурация повреждена или конфликт с терминалом | Удалить/переименовать `~/.config/lazygit/config.yml`; проверить `TERM` |
| `jj: command not found` после установки | `~/.cargo/bin` не в `$PATH` | Добавить `export PATH="$HOME/.cargo/bin:$PATH"` в `.zshrc` |
| `warning: not replacing stale url` при `jj git clone` | URL удалённого репозитория переопределён | Проверить `jj config get git.url-overrides` |
| Difftastic работает медленно на больших файлах | AST-парсинг потребляет много памяти | Установить `DFT_BYTE_LIMIT=100000` для ограничения размера файла; использовать `--check-only` для проверки без diff |

---

## Лучшие практики

*   **Комбинируйте git-delta и lazygit:** Настройте `lazygit` для использования `delta` в качестве diff-рендерера через `git.delta: true` в конфигурации lazygit.

*   **Используйте git-delta как пейджер по умолчанию:** Это единственное изменение в `~/.gitconfig`, которое сразу улучшает читаемость всех `git diff`, `git log -p` и `git show`.

*   **git-absorb для review-правок:** Вместо ручного `git commit --fixup <hash>` используйте `git absorb --and-rebase` — это экономит время и устраняет человеческий фактор при распределении правок по коммитам.

*   **forgit для git-интерактива:** Если вы уже используете `fzf`, добавьте `forgit` как плагин. Команды `ga`, `glo`, `gcb`, `grb` заменяют несколько шагов интерактивного режима.

*   **difftastic для рефакторинга:** Используйте `git ddiff` (alias) вместо `git diff` при работе с рефакторингом, когда структура кода меняется, а логика — нет.

*   **lazygit для сложных операций:** Для interactive rebase, cherry-pick и bisect предпочитайте `lazygit` — визуальная обратная связь снижает риск ошибок.

*   **Не используйте tig для новых проектов:** `tig` — отличный классический инструмент, но его возможности ограничены. Для новых проектов предпочтительнее `lazygit` или `gitui`.

*   **Jujutsa для новых команд:** Если команда начинает новый проект, рассмотрите `jj` + `jjui` — архитектура без индекса и встроенный undo/redo устраняют типичные источники ошибок в Git.

*   **Очистка после работы:** Удаляйте слитые ветки (`git branch --merged main | grep -v '^main$' | xargs git branch -d`), очищайте удалённые ссылки (`git fetch --prune`) и worktree metadata (`git worktree prune`).

### Отмена настроек (Cleanup)

```bash
# Отключить git-delta как пейджер
git config --global --unset core.pager
git config --global --unset interactive.diffFilter
git config --global --remove-section delta 2>/dev/null || true

# Отключить difftastic как внешний diff — удалить только конкретные alias
git config --global --unset alias.ddiff
git config --global --unset alias.dlog
git config --global --unset alias.dshow
git config --global --unset diff.external

# Удалить forgit
rm -rf ~/.config/forgit
# Удалить строку source из .zshrc/.bashrc
```

---

## Дополнительная информация

### Выбор инструмента

1.  Если нужен **основной интерфейс** вместо командной строки — выбирайте **lazygit**.
2.  Для **огромных монорепозиториев** (>100GB или миллионы файлов) — используйте **gitui**.
3.  Для **улучшения вывода** `git diff` обязательно установите **git-delta**.
4.  Для **автоматизации чистки истории** — используйте **git-absorb**.
5.  Для **интерактивного поиска** и навигации — установите **fzf** + **forgit**.
6.  Для **структурного сравнения** кода при рефакторинге — используйте **difftastic**.
7.  Для **интеграции с Forge (GitHub/GitLab)** — установите **gh** или **glab**.
8.  Для **новых проектов** с современной архитектурой VCS — рассмотрите **jj** + **jjui**.

### Официальные ресурсы

*   **lazygit**: [github.com/jesseduffield/lazygit](https://github.com/jesseduffield/lazygit)
*   **git-delta**: [github.com/dandavison/delta](https://github.com/dandavison/delta) | [документация](https://dandavison.github.io/delta/)
*   **git-absorb**: [github.com/tummychow/git-absorb](https://github.com/tummychow/git-absorb)
*   **gitui**: [github.com/gitui-org/gitui](https://github.com/gitui-org/gitui)
*   **tig**: [github.com/jonas/tig](https://github.com/jonas/tig) | [документация](https://jonas.github.io/tig/)
*   **difftastic**: [github.com/Wilfred/difftastic](https://github.com/Wilfred/difftastic) | [документация](https://difftastic.wilfred.me.uk/)
*   **forgit**: [github.com/wfxr/forgit](https://github.com/wfxr/forgit)
*   **fzf**: [github.com/junegunn/fzf](https://github.com/junegunn/fzf)
*   **Jujutsa (jj)**: [github.com/jj-vcs/jj](https://github.com/jj-vcs/jj) | [документация](https://docs.jj-vcs.dev/)
*   **jjui**: [github.com/idursun/jjui](https://github.com/idursun/jjui)
*   **gh (GitHub CLI)**: [cli.github.com](https://cli.github.com)
*   **glab (GitLab CLI)**: [gitlab.com/gitlab-org/cli](https://gitlab.com/gitlab-org/cli)

### См. также

*   [Основы визуализации истории](./git_basics.md)
*   [Манипуляции с историей Git](./git_history_manipulation.md)
*   [Специальные файлы конфигурации](./git_special_files_overview.md)
*   [Рабочие процессы в Git (gh/glab)](./git_workflows.md)
*   [Git Configuration](./git_configuration.md)
