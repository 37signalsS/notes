# GitHub CLI (gh): Управление GitHub из терминала

**Актуально для:** GitHub CLI (gh) v2.99+, октябрь 2026 (API v3/v4, Extensions, Aliases, `gh repo read-file/read-dir`, `--attach` для PR/Issue, `gh issue develop --worktree`, `gh pr checkout --worktree`, Semantic search, `gh project` / `gh discussion` / `gh skill`)

GitHub CLI (`gh`) — официальный клиент командной строки от GitHub. Позволяет управлять Pull Requests, Issues, Releases, Actions, Projects, Discussions и многими другими функциями GitHub прямо из терминала, минуя веб-интерфейс. CLI работает с REST API (через `gh api`) и встроенными подкомандами, которые являются thin wrapper над API.

## Определения

- **GitHub CLI (gh)**: Официальный CLI-клиент для взаимодействия с GitHub. Устанавливается отдельно (`brew install gh` / `apt install gh` / `winget install --id GitHub.cli`) и аутентифицируется через `gh auth login`.
- **Authentication token**: Персональный токен (Fine-grained PAT — рекомендуется) или OAuth App token, сохраняемый в `~/.config/gh/hosts.yml`. CLI использует его для всех запросов к API.
- **`gh api`**: Универсальная подкоманда для прямого вызова любого REST или GraphQL endpoint. Используется, когда нет встроенной подкоманды.
- **Extension**: Плагин для gh, написанный на любом языке. Устанавливается через `gh extension install`. Запускается как подпроцесс.
- **Alias**: Псевдоним (alias) для подкоманд, сокращающий длинные цепочки флагов. Создаётся через `gh alias set`. Хранится в `~/.config/gh/aliases.yml`.
- **Enterprise Server**: CLI поддерживает github.com и локальные GitHub Enterprise Server (GHE) через `--hostname` и отдельные профили аутентификации.
- **`gh repo read-file` / `gh repo read-dir`** (preview, v2.95+): Чтение файлов и листинг директорий удалённого репозитория без клонирования. Поддерживают `--ref` (branch/tag/commit), `--json`, `--jq`, `--template`, `--output` (write to file).
- **`--attach` flag** (v2.99+): Загрузка вложений (изображения, видео) в Issues, PRs, комментарии. Повторяемый флаг, батчи до 50 файлов.
- **Worktree support** (v2.99+): `gh issue develop --checkout --worktree <path>` и `gh pr checkout --worktree <path>` — создание linked branch в отдельном git worktree, не затрагивая текущую рабочую копию.
- **Semantic search** (v2.99+): `gh search issues --search-type semantic|hybrid` — семантический поиск по issue/PR (требует GitHub.com или GHEC).
- **Projects v2 CLI** (`gh project`): Управление Projects (v2) — создание, поля, items, views.
- **Discussions CLI** (`gh discussion`): Управление GitHub Discussions — list, view, create, comment, category.
- **Skills CLI** (`gh skill`): Управление GitHub Copilot skills для агентов (preview).

## Предварительные требования

- **GitHub CLI (gh) v2.95+** для `gh repo read-file/read-dir`, v2.99+ для `--attach`, worktree, semantic search, `gh project` / `gh discussion` / `gh skill`
- **curl** + **jq** для raw HTTP запросов (альтернатива `gh api`)
- **Аутентификация**: Fine-grained PAT (рекомендуется), classic PAT (legacy), OAuth App token, или GitHub App Installation Token
- **Сеть**: доступ к `api.github.com` (или вашему GES endpoint)
- **Git** v2.38+ для worktree поддержки (`git worktree` команда)
- **Для Actions**: `GITHUB_TOKEN` автоматически доступен в workflow (1,000 req/hr, 15,000 для GHE Cloud)

## Архитектура и аутентификация

### Модель аутентификации

```text
gh auth login
    ↓
Fine-grained PAT (ghp_...) или OAuth App token
    ↓
Saved to ~/.config/gh/hosts.yml (encrypted или в plaintext)
    ↓
Все подкоманды используют токен для API-вызовов
```

- **Fine-grained PAT** (рекомендуется): настраивается с минимальными правами на конкретные репозитории/организации. Жизненный цикл токена можно ограничить (30/60/90 дней или custom).
- **Classic PAT** (устаревает): широкие права, жизненный цикл до 30 дней (или never для enterprise).
- **OAuth App**: для enterprise-окружений, когда нужен SSO. CLI запускает браузер для OAuth flow.

### Конфигурация для Enterprise Server

```bash
# Аутентификация на локальном GHE
gh auth login --hostname ghe.example.com --with-token < token.txt

# Переключение между хостами
gh auth status --hostname ghe.example.com
gh api --hostname ghe.example.com /user
```

### Файлы конфигурации CLI

| Файл | Назначение |
|---|---|
| `~/.config/gh/hosts.yml` | Аутентификация (токены, hostname, user, git_protocol) |
| `~/.config/gh/aliases.yml` | Пользовательские aliases |
| `~/.config/gh/config.yml` | Настройки: editor, pager, prompt, git_protocol, extensions |
| `~/.local/share/gh/extensions/` | Установленные extensions (или `GH_EXTENSION_DIR`) |

## Практические сценарии

### Сценарий 1: Базовая аутентификация и проверка статуса

**Предварительные требования**: Установленный `gh` (v2.70+).

```bash
# Аутентификация в GitHub (OAuth flow через браузер)
gh auth login
# → Выбираем: GitHub.com / GitHub Enterprise Server
# → Аутентификация: HTTPS / SSH
# → Настроить как default? Yes

# Проверить статус аутентификации
gh auth status
# → github.com
# →   ✓ Logged in to github.com as <username> (GitHub.com)
# →   ✓ GITHUB_TOKEN (персональный токен)

# Для скриптов — аутентификация через токен
echo $GH_TOKEN | gh auth login --with-token

# Список репозиториев
gh repo list
# → owner/repo1   Description    public
# → owner/repo2   Description    private
```

- **Валидация**: `gh auth status` показывает `Logged in to github.com`; `gh repo list` возвращает репозитории с доступом токена.

### Сценарий 2: Работа с Pull Requests из терминала

```bash
# Создание PR с автоматическим заполнением из коммита и открытием в браузере
gh pr create --fill --web
# → Creating pull request for feature/auth from main
# → https://github.com/owner/repo/pull/42

# Создание PR с указанием заголовка и описания
gh pr create --title "feat: add auth module" \
  --body "Implements OAuth2 authentication with PKCE" \
  --reviewer "@org/team-backend" \
  --assignee "@me" \
  --label "feature,auth"

# Просмотр статуса CI/CD проверок
gh pr checks
# → ✓ test (2m) — passed
# → ✓ lint (45s) — passed

# Просмотр диффа PR
gh pr diff
# → diff --git a/src/auth.js b/src/auth.js
# → + export function login() { ... }

# Одобрение PR
gh pr review 42 --approve --body "LGTM"

# Squash + удаление ветки
gh pr merge 42 --squash --delete-branch
# → ✓ Squashed and merged pull request #42

# Список открытых PR с фильтром
gh pr list --state open --author "@me" --label "priority: high"

# Просмотр PR по номеру
gh pr view 42 --web
# → Открывает PR в браузере
```

```bash
# Просмотр последних смёрженных PR
gh pr list --state merged --limit 3
# → #142  feat: add caching      Merged  2 hours ago
# → #141  fix: auth timeout      Merged  3 days ago
# → #139  chore: deps update     Merged  1 week ago
```

### Сценарий 3: Управление Issues и Releases

```bash
# Список открытых issue с меткой "bug"
gh issue list --label "bug" --state open
# → #41   Login fails after password reset   Open    2 days ago

# Создать issue из шаблона
gh issue create --template "Bug_report" --title "Cache miss on cold start" --body "Steps to reproduce..."

# Просмотр последних 3 закрытых issue
gh issue list --state closed --limit 3

# Создание релиза
gh release create "v1.4.2" \
  --title "Release 1.4.2" \
  --notes "Patch release with auth fixes" \
  dist/app-1.4.2.tar.gz checksums.txt

# Генерация заметок релиза из PR
gh release create "v1.4.2" --generate-notes

# Список релизов
gh release list
# → v1.4.2   Latest  Published  2 days ago
# → v1.4.1           Published  1 week ago

# Просмотр релиза
gh release view v1.4.2 --web
```

### Сценарий 4: Управление Actions и CI/CD из CLI

```bash
# Просмотр текущих запусков workflow
gh run list --limit 5
# → 234567890  CI   ✓ Succeeded  1m ago  main
# → 234567889  CI   ✗ Failed     3m ago  feature/auth

# Просмотр деталей запуска
gh run view 234567890
# → Name:          CI (main)
# → Status:        Succeeded
# →   build  ✓  3m  ubuntu-latest
# →   test   ✓  2m  ubuntu-latest

# Ожидание завершения запуска
gh run watch
# → ✓ main · CI · 234567890: Succeeded 12s ago  (job build ✓ 5s)

# Просмотр логов конкретного шага
gh run view 234567890 --job build --log

# Повторный запуск проваленного пайплайна
gh run rerun 234567889 --failed-jobs

# Отмена запущенного пайплайна
gh run cancel 234567891
```

### Сценарий 5: Прямые API-вызовы через `gh api`

`gh api` — универсальный клиент. Работает с REST и GraphQL:

```bash
# REST: информация о репозитории
gh api repos/{owner}/{repo} --jq '.stargazer_count'

# REST: список установок GitHub App
gh api /app/installations --jq '.[].id'

# REST: создание токена установки с суженными правами
gh api /app/installations/12345/access_tokens -X POST \
  -f permissions='{"contents":"write","issues":"read"}'

# GraphQL: информация о текущем пользователе
gh api graphql -f query='query { viewer { login name email } }'

# GraphQL: список последних 5 PR с их статусом
gh api graphql -f query='
query {
  repository(owner: "owner", name: "repo") {
    pullRequests(last: 5, states: OPEN) {
      nodes { title author { login } commits { totalCount } }
    }
  }
}'

# REST: обновление settings репозитория (branch protection через rulesets)
gh api -X PUT /repos/{owner}/{repo}/branches/main/protection \
  -f "required_status_checks[strict]"=true \
  -f "required_pull_request_reviews[required_approving_review_count]"=1
```

### Сценарий 6: Управление секретами через CLI

```bash
# Список секретов репозитория
gh secret list
# → NAME          UPDATED
# → NPM_TOKEN     2026-10-10
# → AWS_ACCESS_KEY  2026-09-15

# Установить секрет
gh secret set AWS_ACCESS_KEY_ID --body "$AWS_ACCESS_KEY_ID"

# Установить секрет из файла
gh secret set APP_PRIVATE_KEY --body "$(cat private-key.pem)"

# Удалить секрет
gh secret remove NPM_TOKEN

# Аналогично для organization
gh secret list --type organization
gh secret set ORG_TOKEN --body "$TOKEN" --type organization --org {org}
```

### Сценарий 7: Aliases и Extensions

**Aliases** — сокращения для часто используемых команд:

```bash
# Создать alias для часто используемого паттерна
gh alias set create-pr 'pr create --fill --web'
# Теперь: gh create-pr

# Alias с шаблоном и переменными
gh alias set cleanup-merged '
  pr list --state merged --limit 50 --json number,headRefName \
  --template "{{range .}}{{if eq .HeadRefName \"feature/\"}}{{.Number}} {{end}}{{end}}"'

# Список aliases
gh alias list
```

**Extensions** — плагины, написанные сообществом:

```bash
# Установить extension
gh extension install actions/cache-cleanup
gh extension install seachicken/repo-dependency-graph

# Список extensions
gh extension list
# → actions/cache-cleanup
# → seachicken/repo-dependency-graph

# Вызов extension
gh cache-cleanup --repo {owner}/{repo}
```

### Сценарий 8: Управление Codespaces из CLI

```bash
# Список codespaces
gh codespace list
# → name          state     branch
# → repo-main     Running   main

# Создать codespace
gh codespace create --repo {owner}/{repo} --branch main --machine "M (8 cores)"

# Подключиться к codespace
gh codespace code --repo {owner}/{repo}

# Остановить/удалить codespace
gh codespace stop --octal-repo {owner}/{repo}
gh codespace delete --octal-repo {owner}/{repo}
```

## Команды и справочник

### Основные подкоманды

| Подкоманда | Назначение |
|---|---|
| `gh auth login` / `gh auth logout` | Аутентификация |
| `gh auth status` | Проверка статуса |
| `gh repo` | Управление репозиториями (clone, create, view, list) |
| `gh pr` | Pull Requests (create, view, merge, diff, checks, list) |
| `gh issue` | Issues (create, list, view, close, comment) |
| `gh run` | Workflow runs (list, view, watch, rerun, cancel) |
| `gh release` | Releases (create, view, list, upload, delete) |
| `gh secret` | Secrets (list, set, remove) |
| `gh api` | Прямые API-вызовы (REST, GraphQL) |
| `gh extension` | Управление extensions |
| `gh alias` | Управление aliases |
| `gh codespace` | Управление Codespaces |
| `gh cache` | Управление кэшем Actions |
| `gh label` | Управление метками (labels) |
| `gh gist` | Управление gists |
| `gh search` | Поиск по репозиториям, issues, PRs |

### Полезные флаги для `gh` и `gh api`

| Флаг | Описание |
|---|---|
| `--jq '.field'` | JSON-парсинг вывода (на основе jq) |
| `--template '{{.}}'` | Go-шаблоны для кастомного вывода |
| `--json field1,field2` | Вывод только указанных полей JSON |
| `--limit N` | Ограничение количества результатов |
| `--state open` / `--state merged` | Фильтр по статусу |
| `-R {owner}/{repo}` | Явное указание репозитория (для скриптов) |

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `error: failed to login: api already in use` | Токен уже используется другим процессом | `gh auth logout --hostname github.com` и повторить `gh auth login` |
| `403 Resource not accessible by integration` | Fine-grained PAT не имеет нужных прав | Проверить scopes в Settings → Developer settings → Fine-grained PAT |
| `401 Bad credentials` на `gh api` | Токен истёк или неверный | Обновить токен через `gh auth login`; `echo $GH_TOKEN \| gh auth login --with-token` |
| `rate limit exceeded` | Превышен лимит API (5000/hr для PAT) | Дождаться сброса лимита; для интенсивных скриптов — использовать GraphQL (менее избыточный) |
| `gh: command not found` | CLI не установлен или не в PATH | `brew install gh` (macOS), `sudo apt install gh` (Linux), `winget install --id GitHub.cli` (Windows) |
| `pull_request_target` не работает в workflow | Workflow запущен в fork, а не в upstream | `pull_request_target` работает только для upstream-воркфлоу; для fork используйте `pull_request` с `gh` |
| Alias не работает | Синтаксическая ошибка в alias | `gh alias list` для проверки; `gh alias delete <name>` для исправления |
| Extension "command not found" | Extension не установлен правильно | `gh extension install <owner>/<name>`; проверить, что extension добавлен в PATH |

## Лучшие практики

1. **Fine-grained PAT с минимальными правами**: не используйте classic PAT; создавайте fine-grained PAT с нужными scopes ровно на те репозитории/организации, которые нужно.
2. **`--jq` и `--template` для парсинга**: используйте эти флаги, чтобы не парсить JSON вручную в bash-скриптах.
3. **Aliases для повторяющихся паттернов**: `gh alias set` экономит время на длинных цепочках команд.
4. **GraphQL для bulk-операций**: если нужно получить связанные данные из нескольких endpoint-ов, используйте `gh api graphql` — один запрос вместо нескольких REST-вызовов (экономия rate limit).
5. **Extensions для расширения функционала**: `actions/cache-cleanup`, `seachicken/repo-dependency-graph` и другие extension-ы покрывают громоздкие manual сценарии.
6. **Для CI/CD**: используйте `gh run watch` в локальном dev для мониторинга прогонов в реальном времени; `gh run view --log` для отладки.
7. **Для безопасности**: храните токен в `~/.config/gh/hosts.yml` (CLI шифрует), а не в env-переменных в CI.

## Дополнительная информация

- **[Рабочие процессы в Git](../Git/git_workflows.md#инструменты-командной-строки)** — использование `gh` для PR создания, слияния и CI-мониторинга. (Исходный контент о `gh` переехал сюда.)
- **[Инструменты Git TUI и CLI](../Git/git_tools.md)** — TUI-клиенты (lazygit, gitui, tig) и прочие CLI-улучшения.
- **[Release Management](./Release_Management.md)** — `gh release create`/`gh release upload` для публикации релизов.
- **[Git автоматизация](./Git_Automation.md)** — `gh api` для branch protection, `git push` через GITHUB_TOKEN/App-токен.
- **[GitHub API](./github_api.md)** — REST и GraphQL endpoint-ы, rate limits, pagination.
- **Официальная документация**: [GitHub CLI](https://cli.github.com/manual/), [gh api](https://cli.github.com/manual/gh_api), [gh extensions](https://cli.github.com/manual/gh_extension).
