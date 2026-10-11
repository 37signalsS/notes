# GitHub Codespaces: Cloud-разработка в браузере

**Актуально для:** GitHub Codespaces, октябрь 2026 (Codespaces with GPU, prebuilds, devcontainer CLI, codespace secrets, lifecycle hooks); для GitHub Enterprise Server — пока не поддерживается (только Cloud)

GitHub Codespaces — это полностью управляемая cloud-среда разработки (VS Code в браузере или в Desktop), запускаемая на виртуальной машине GitHub. Codespaces интегрирован с `devcontainer.json` спецификацией: конфигурация окружения (образ, зависимости, расширения, секреты) хранится в репозитории — разработчик получает готовую среду "одним кликом" из любого устройства.

## Определения

- **Codespace**: Запущенная виртуальная машина с готовой dev-средой. Хранится в облаке, имеет свою файловую систему и туннель к `github.com`.
- **devcontainer.json**: Манифест конфигурации codespace (или локального dev-контейнера). Описывает: базовый образ/Dockerfile, features, VS Code extensions, postCreateCommand, forwarding ports.
- **Prebuild**: Заранее собранная среда (image + dependencies) на основе `devcontainer.json`, чтобы при создании codespace не ждать `postCreateCommand`.
- **Codespace Secrets**: Секреты, доступные внутри codespace (настраиваются в Settings → Codespaces). Шифруются для конкретного codespace.
- **Port Forwarding**: Автоматическое проброс портов из VM на публичный URL (https://{port}-{codespace}-{owner}.githubpreview.dev) или локальный туннель.
- **Lifecycle Hooks**: Хуки `postCreateCommand`, `onCreateCommand`, `updateContentCommand` — выполняются на разных этапах создания/обновления codespace.
- **Machine Types**: Размеры VM (Small: 2-core/4GB, Medium: 4-core/8GB, Large: 8-core/16GB, Premium: 16-core/32GB + GPU).

## Архитектура и devcontainer

### Жизненный цикл codespace

```text
GitHub → VM (Linux) → devcontainer.json → Dockerfile/features → VS Code
    │
    1. Create codespace (из репо + branch)
    2. Build devcontainer (из image + features)
    3. Run lifecycle hooks (onCreateCommand → postCreateCommand)
    4. User gets VS Code в браузере или Desktop
    5. Idle timeout (30 min default) → авто-остановка
    6. Auto-delete (after configured TTL: 1 day / 3 days / 1 week)
```

### Минимальная конфигурация devcontainer

```json
{
  "name": "Python dev",
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "features": {
    "ghcr.io/devcontainers/features/docker-in-docker:2": {},
    "ghcr.io/devcontainers/features/aws-cli:1": {}
  },
  "postCreateCommand": "pip install -r requirements.txt && pre-commit install",
  "onCreateCommand": "echo 'Codespace ready!'",
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "github.copilot"
      ],
      "settings": {
        "python.pythonPath": "/usr/local/bin/python"
      }
    }
  }
}
```

## Практические сценарии

### Сценарий 1: Создание codespace из репозитория

```bash
# 1. Создать codespace через CLI (gh CLI >= 2.0)
gh codespace create \
  --repo {owner}/{repo} \
  --branch main \
  --machine "M (4 cores)" \
  --devcontainer-path .devcontainer/devcontainer.json

# → Creating codespace "fragrant-fish-sticks-xyz"...
# → https://github.com/features/codespaces/codespaces/fragrant-fish-sticks-xyz

# 2. Открыть codespace в браузере
gh codespace code --repo {owner}/{repo}

# 3. Или открыть в VS Code Desktop
gh codespace code --repo {owner}/{repo} --editor vscode

# 4. Список codespaces
gh codespace list
# → NAME                    STATE     BRANCH  CREATED AT
# → fragile-fish-sticks-abc  Running   main    2026-10-11T10:00:00Z

# 5. Остановить/удалить
gh codespace stop --repo {owner}/{repo}
gh codespace delete --repo {owner}/{repo}
```

- **Валидация**: codespace в статусе `Running`, в браузере открывается VS Code, `postCreateCommand` выполнен (см. в терминале output).

### Сценарий 2: Prebuild для ускорения создания

Prebuild собирает образ и зависимости заранее — создание codespace занимает секунды, а не минуты.

```json
// .devcontainer/devcontainer.json
{
  "name": "Fast Node.js dev",
  "image": "mcr.microsoft.com/devcontainers/typescript-node:20",
  "postCreateCommand": "npm ci",
  "customizations": {
    "codespaces": {
      "openFiles": [
        "README.md",
        "src/index.ts"
      ],
      "openPreview": "http://localhost:3000"
    }
  }
}
```

Через UI: Settings → Code and automation → Codespaces → Prebuilds → Create prebuild.

```bash
# Принудительный запуск prebuild через workflow
# .github/workflows/codespaces-prebuild.yml
name: "Codespaces Prebuild"
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  prebuild:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Trigger prebuild
        run: gh api -X POST /repos/{owner}/{repo}/dispatches \
          -f event_type="codespaces:prebuild"
```

### Сценарий 3: Port forwarding и проброс портов

```bash
# 1. В codespace: запустить сервер на порту 3000
# → VS Code автоматически обнаружит и создаст туннель
# → URL: https://3000-fragrant-fish-sticks-xyz.githubpreview.dev

# 2. Вручную пробросить порт через CLI
gh codespace ports forward 3000 --repo {owner}/{repo}

# 3. Пример devcontainer.json с forwardPorts
{
  "name": "Node dev",
  "image": "mcr.microsoft.com/devcontainers/node:20",
  "forwardPorts": [3000, 5173],
  "postCreateCommand": "npm install && npm run dev"
}
```

- **Auto-forward**: VS Code автоматически пробрасывает порт, когда приложение слушает на `0.0.0.0:<port>`.
- **Port visibility**: `public` (всем) или `private` (только владельцу/команде) — настраивается в VS Code UI или через devcontainer.

### Сценарий 4: Codespace Secrets

```bash
# 1. Установить кодовспейс secret
gh codespace secrets set DATABASE_URL --body "postgres://user:pass@db:5432"

# 2. Список secrets
gh codespace secrets list
# → NAME          UPDATED
# → DATABASE_URL   2026-10-11

# 3. Использовать в devcontainer.json
{
  "env": {
    "DATABASE_URL": "${localEnv:DATABASE_URL}"
  },
  "postCreateCommand": "echo \"DB_URL=$DATABASE_URL\" >> .env"
}

# 4. Удалить secret
gh codespace secrets unset DATABASE_URL
```

### Сценарий 5: Жизненный цикл и hooks

```json
// .devcontainer/devcontainer.json — lifecycle
{
  "name": "Full-stack dev",
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "onCreateCommand": "apt-get update && apt-get install -y postgresql-client",  // один раз при создании
  "updateContentCommand": "pip install -r requirements.txt --upgrade",  // при checkout изменился
  "postCreateCommand": "pre-commit install --hook-dir .pre-commit-config.yaml && echo 'Ready!'"  // после каждого создания/перезапуска
}
```

| Hook | Выполняется | Когда использовать |
|---|---|---|
| `onCreateCommand` | Один раз при создании VM | Установка системных утилит |
| `updateContentCommand` | При изменении контента репо | Обновление зависимостей |
| `postCreateCommand` | После каждого создания/перезапуска | npm install, pre-commit install |

## Команды и API-операции

### CLI (`gh codespace`)

| Команда | Описание |
|---|---|
| `gh codespace create` | Создать codespace |
| `gh codespace code` | Открыть в браузере/VS Code |
| `gh codespace list` | Список codespaces |
| `gh codespace stop` | Остановить codespace |
| `gh codespace delete` | Удалить codespace |
| `gh codespace ports` | Управление port forwarding |
| `gh codespace secrets` | Управление secrets |
| `gh codespace ssh` | SSH в codespace |
| `gh codespace logs` | Логи codespace |

### API

| Операция | Endpoint |
|---|---|
| Список codespaces | `GET /repos/{owner}/{repo}/codespaces` |
| Создать codespace | `POST /repos/{owner}/{repo}/codespaces` |
| Удалить codespace | `DELETE /repos/{owner}/{repo}/codespaces/{codespace_name}` |
| Codespace secrets | `GET/POST/PUT /repos/{owner}/{repo}/codespaces/secrets` |
| Ports | `GET /repos/{owner}/{repo}/codespaces/{name}/ports` |

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `postCreateCommand` fails | Нет зависимостей в образе, или network error | Проверить `image` и `features` в devcontainer.json; использовать `--retry` |
| Port не пробрасывается | Приложение слушает `localhost`, а не `0.0.0.0` | В devcontainer: `listen on 0.0.0.0:port` |
| `403` при создании codespace | Нет лицензии на codespace | Проверить тариф; org-level billing |
| Codespace stuck в `Creating` | Prebuild не готов или image слишком большой | Проверить prebuild status в UI; уменьшить image |
| `codespace secrets` не работают | Secret не синхронизирован с VM | `gh codespace secrets set` + перезапуск codespace |
| SSH в codespace не работает | SSH keys не настроены | `gh codespace ssh --repo {owner}/{repo} --keygen` |

## Лучшие практики

1. **devcontainer.json в repo**: всегда храните dev-конфигурацию в репозитории — любой contributor получает одинаковую среду.
2. **Prebuilds для больших проектов**: включайте prebuilds для Node.js/Python проектов с тяжёлыми зависимостями — создание codespace занимает 5–10 секунд вместо 5–10 минут.
3. **Machine types**: используйте Small для легких задач, Medium/Large для компиляции и тестов, Premium + GPU для ML.
4. **Port visibility**: `private` по умолчанию — не делайте публичными debug-интерфейсы.
5. **postCreateCommand быстрый**: выносите тяжёлые сборки в prebuild; `postCreateCommand` должен быть <2 мин.
6. **Очистка**: настраивайте TTL (auto-delete через 1 день/3 дня/неделю); остановка через 30 мин неактивности.
7. **Codespace Secrets**: используйте `${localEnv:VAR}` в devcontainer для проброса secrets — не hardcode.
8. **VS Code extensions**: перечисляйте в `customizations.vscode.extensions` только нужные — лишние extensions замедляют запуск.

## Дополнительная информация

- **[GitHub CLI](./github_cli.md)** — `gh codespace` и `gh api` для управления codespaces из терминала.
- **[GitHub API](./github_api.md)** — REST API для управления codespaces, secrets, ports.
- **[Сетевая безопасность](./network-security.md)** — egress для codespace VM.
- **Официальная документация**: [Codespaces](https://docs.github.com/en/codespaces), [devcontainer.json](https://containers.dev/), [Prebuilds](https://docs.github.com/en/codespaces/prebuilding-your-codespace).
