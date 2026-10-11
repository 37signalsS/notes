# GitHub Codespaces: Воспроизводимые контейнеризированные среды разработки

**Актуально для:** GitHub Codespaces (спецификация Development Containers 2026, devcontainer CLI, prebuilds, lifecycle hooks, gh CLI >= 2.50)

GitHub Codespaces — это управляемая платформа предоставления изолированных сред разработки на базе Linux-контейнеров, стандартизированная открытой спецификацией `devcontainer.json` (Development Containers). Конфигурация окружения (базовый образ, системные пакеты, утилиты администрирования, расширения редактора, порты и хуки жизненного цикла) хранится непосредственно в Git-репозитории как код. Это гарантирует детерминированность среды для всех участников команды, устраняет проблему дрейфа локальных конфигураций и упрощает онбординг инженеров.

## Определения

- **Codespace**: Запущенный изолированный экземпляр среды разработки (виртуальная машина Linux с запущенным контейнером devcontainer и агентом удаленного подключения).
- **devcontainer.json**: Декларативный манифест спецификации Development Containers (`containers.dev`), описывающий состав контейнера, подключаемые фичи (Features), переменные окружения, проброс портов и команды инициализации.
- **Dev Container Features**: Переиспользуемые самодостаточные модули установки инструментов и пакетов (например, Docker-in-Docker, Git, утилиты системного мониторинга), подключаемые в `devcontainer.json`.
- **Lifecycle Hooks**: Хуки жизненного цикла контейнера (`initializeCommand`, `onCreateCommand`, `updateContentCommand`, `postCreateCommand`, `postStartCommand`, `postAttachCommand`), управляющие сборкой и подготовкой рабочего места.
- **Prebuild**: Механизм предварительной сборки devcontainer-образа и выполнения тяжелых зависимостей по триггеру (push в ветку) для сокращения времени старта codespace до нескольких секунд.
- **Codespace Secrets**: Изолированные зашифрованные переменные окружения, настраиваемые специально для сред Codespaces на уровне пользователя или организации/репозитория (не путать с GitHub Actions Secrets).
- **Port Forwarding**: Механизм туннелирования сетевых портов из контейнера на локальную рабочую станцию через SSH-туннель или защищенный HTTPS-прокси.
- **Dotfiles**: Механизм автоматической персонализации рабочего окружения (bashrc, zshrc, tmux, gitconfig) инженера путем клонирования персонального репозитория при старте сессии.
- **Recovery Container**: Аварийный режим запуска Codespaces с базовым минимальным контейнером, активируемый при фатальных ошибках сборки основного `devcontainer.json` для устранения сбоев конфигурации.

## Архитектура и devcontainer

### Архитектурная модель

```text
[Клиент: Браузер / VS Code Desktop / SSH-клиент]
                      │ (Зашифрованный туннель / WebSocket / SSH)
                      ▼
[Хостовая VM (Linux KVM)]
  ├── Docker Engine / Containerd
  │     │
  │     ▼
  │   [Dev Container (изолированное окружение разработчика)]
  │     ├── VS Code Server / OpenSSH Daemon
  │     ├── Системные утилиты, CLI, рантаймы
  │     └── Монтирование: /workspaces/<repo-name> (персистентный том)
  │
  ├── Хранилище:
  │     ├── /workspaces (сохраняется между перезапусками)
  │     └── /workspaces/.codespaces/.persistedshare (персистентный системный кэш)
  └── Служебный агент Codespaces (управление жизненным циклом, секреты, токены)
```

### Порядок выполнения Lifecycle Hooks

Спецификация `devcontainer.json` определяет строгую последовательность исполнения команд инициализации:

```text
1. initializeCommand     → Выполняется на ХОСТЕ до создания контейнера
2. onCreateCommand       → Выполняется ВНУТРИ контейнера сразу после его создания
3. updateContentCommand   → Выполняется ВНУТРИ контейнера при скачивании/обновлении репозитория
4. postCreateCommand     → Выполняется ВНУТРИ контейнера после завершения сборки и монтирования
5. postStartCommand      → Выполняется ВНУТРИ контейнера при КАЖДОМ запуске/пробуждении
6. postAttachCommand     → Выполняется ВНУТРИ контейнера при подключении клиентской сессии
```

| Хук | Контекст выполнения | Назначение для SRE / DevOps | Поведение при ненулевом коде возврата |
|---|---|---|---|
| `initializeCommand` | Хост-система | Локальные подготовительные скрипты, проверка переменных окружения | Остановка сборки с ошибкой |
| `onCreateCommand` | Внутри контейнера | Установка низкоуровневых системных пакетов (`apt-get install`), создание служебных каталогов | Остановка сборки с ошибкой |
| `updateContentCommand` | Внутри контейнера | Загрузка зависимостей проекта (кэшируется в prebuilds) | Остановка сборки с ошибкой |
| `postCreateCommand` | Внутри контейнера | Установка git-хуков (`pre-commit install`), первичная сборка проекта, настройка локальных БД | Остановка сборки с ошибкой |
| `postStartCommand` | Внутри контейнера | Запуск фоновых сервисов, демонов, прогрев кэшей при старте сессии | Логируется предупреждение, codespace запускается |
| `postAttachCommand` | Внутри контейнера | Вывод диагностического приветствия в терминал, проверка статуса сервисов | Логируется предупреждение |

### Файловая система и персистентность данных

1. **Рабочая директория (`/workspaces/<repo-name>`)**:
   - Смонтирована на выделенный блочный том.
   - Все изменения файлов репозитория, неотслеживаемые файлы и untracked ветки Git сохраняются между перезапусками и пересборками (`Rebuild Container`).
2. **Корневая ФС контейнера (`/`, `/tmp`, `/var`, `/home/vscode`)**:
   - При обычной остановке (`Stop`) и запуске (`Start`) состояние контейнера сохраняется.
   - При полной пересборке (`Full Rebuild`) контейнер уничтожается и пересоздается с нуля. Любые пакеты, установленные вручную вне `devcontainer.json`, удаляются.
3. **Персистентный системный каталог**:
   - Каталог `/workspaces/.codespaces/.persistedshare` сохраняется даже при полной пересборке контейнера. Используется для сохранения истории bash/zsh, кэша расширений и служебных логов.

## Практические сценарии

### Сценарий 1: Конфигурация devcontainer.json для системного администрирования и SRE

Конфигурация включает поддержку Docker-in-Docker, утилиты управления инфраструктурой, безопасность от непривилегированного пользователя и проверку синтаксиса.

```json
// .devcontainer/devcontainer.json
{
  "name": "DevOps & SRE Workstation",
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu-24.04",
  "features": {
    "ghcr.io/devcontainers/features/common-utils:2": {
      "installZsh": true,
      "configureZshAsDefaultShell": true,
      "upgradePackages": true,
      "username": "vscode"
    },
    "ghcr.io/devcontainers/features/docker-in-docker:2": {
      "version": "latest",
      "enableDockerDind": true
    },
    "ghcr.io/devcontainers/features/git:1": {
      "version": "latest"
    }
  },
  "remoteUser": "vscode",
  "runArgs": [
    "--init",
    "--cap-add=SYS_PTRACE",
    "--security-opt", "seccomp=unconfined"
  ],
  "containerEnv": {
    "HISTFILE": "/workspaces/.codespaces/.persistedshare/bash_history",
    "SHELL": "/usr/bin/zsh"
  },
  "forwardPorts": [8080, 9090],
  "portsAttributes": {
    "8080": {
      "label": "Application Service",
      "onAutoForward": "notify",
      "visibility": "private"
    },
    "9090": {
      "label": "Metrics Endpoint",
      "onAutoForward": "silent",
      "visibility": "private"
    }
  },
  "onCreateCommand": "sudo apt-get update && sudo apt-get install -y jq curl iputils-ping dnsutils net-tools",
  "postCreateCommand": "docker --version && echo 'DevOps workstation ready'",
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-azuretools.vscode-docker",
        "redhat.vscode-yaml",
        "tamasfe.even-better-toml",
        "eamodio.gitlens"
      ],
      "settings": {
        "terminal.integrated.defaultProfile.linux": "zsh",
        "files.trimTrailingWhitespace": true,
        "files.insertFinalNewline": true
      }
    }
  }
}
```

### Сценарий 2: Управление и автоматизация через GitHub CLI (`gh codespace`)

Управление Codespaces без открытия браузера через официальный CLI `gh`.

```bash
# 1. Просмотр доступных конфигураций машин для репозитория
gh codespace machines --repo my-org/sre-infra
# → NAME                 DISPLAY NAME  CORES  RAM (GiB)  STORAGE (GiB)
# → standardLinux32gb   4 cores       4      16         32
# → basicLinux           2 cores       2      8          32

# 2. Создание codespace с явным указанием ветки и конфигурации машины
gh codespace create \
  --repo my-org/sre-infra \
  --branch main \
  --machine standardLinux32gb \
  --idle-timeout 30m
# → Creating codespace...
# → Codespace 'verbose-space-invention-abc123' created.

# 3. Получение списка активных сред в формате JSON для автоматизации
gh codespace list --json name,state,repository,gitStatus
# → [
# →   {
# →     "gitStatus": {"ahead": 0, "behind": 0, "hasUncommittedChanges": false},
# →     "name": "verbose-space-invention-abc123",
# →     "repository": "my-org/sre-infra",
# →     "state": "Available"
# →   }
# → ]

# 4. Выполнение одиночной команды внутри запущенного codespace через SSH
gh codespace ssh -c verbose-space-invention-abc123 -- "uptime && df -h /workspaces"
# → 20:05:30 up 12 min,  0 users,  load average: 0.12, 0.08, 0.05
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/root        30G  4.2G   26G  14% /workspaces

# 5. Остановка codespace
gh codespace stop -c verbose-space-invention-abc123
# → Stopping codespace...
# → Codespace 'verbose-space-invention-abc123' stopped.
```

### Сценарий 3: Нативная настройка OpenSSH и передача файлов

Интеграция с локальным SSH-клиентом для использования стандартных утилит (`ssh`, `scp`, `rsync`, Ansible).

```bash
# 1. Генерация конфигурационного файла OpenSSH для подключения к Codespaces
gh codespace ssh --config > ~/.ssh/codespaces_config

# 2. Подключение конфигурации в ~/.ssh/config:
# Добавить строку:
# Include ~/.ssh/codespaces_config

# 3. Прямое подключение по стандартному SSH-протоколу:
ssh cs-verbose-space-invention-abc123.my-org-sre-infra
# → Welcome to Ubuntu 24.04 LTS (GNU/Linux 6.5.0 x86_64)
# → vscode@codespaces-abc123:/workspaces/sre-infra$

# 4. Копирование файлов и директорий между локальной машиной и codespace
# Копирование локального файла в codespace:
gh codespace cp ./deploy.sh remote:/workspaces/sre-infra/deploy.sh -c verbose-space-invention-abc123
# → deploy.sh: 100% |████████████████████████████████████████| (4.2 KB/s)

# Копирование сгенерированного артефакта из codespace на локальную машину:
gh codespace cp remote:/workspaces/sre-infra/output.log ./output.log -c verbose-space-invention-abc123
# → output.log: 100% |████████████████████████████████████████| (18.1 KB/s)
```

### Сценарий 4: Port Forwarding и сетевая изоляция

Проброс локальных портов сетевых сервисов и управление доступом к ним.

```bash
# 1. Просмотр проброшенных портов запущенного окружения
gh codespace ports -c verbose-space-invention-abc123
# → SRC PORT  DST PORT  VISIBILITY  LABEL
# → 8080      8080      private     Application Service
# → 9090      9090      private     Metrics Endpoint

# 2. Локальный проброс удаленного порта (туннелирование на локальный порт 18080)
gh codespace ports forward 8080:18080 -c verbose-space-invention-abc123
# → Forwarding port 8080 to localhost:18080...

# 3. Изменение политики видимости порта:
# Доступные значения: private (только текущий пользователь), org (участники организации), public (все)
gh codespace ports visibility 8080:org -c verbose-space-invention-abc123
# → Port 8080 visibility set to org
```

> [!WARNING]
> Для проброса портов приложение внутри devcontainer обязано слушать адрес `0.0.0.0`, а не `127.0.0.1` (loopback). Процессы, привязанные к `127.0.0.1`, недоступны прокси-демону Codespaces и не туннелируются.

### Сценарий 5: Секреты окружения (Codespace Secrets)

Codespaces использует отдельное изолированное хранилище секретов. Секреты репозитория GitHub Actions **не передаются** в Codespaces автоматически по соображениям безопасности.

```bash
# 1. Создание персонального секрета Codespaces через CLI
gh codespace secrets set SRE_VAULT_TOKEN --body "s.abcdef1234567890"
# → Set secret SRE_VAULT_TOKEN for your codespaces

# 2. Создание секрета на уровне репозитория с явным назначением репозиториев
gh codespace secrets set INTERNAL_REGISTRY_TOKEN \
  --repo my-org/sre-infra \
  --body "token-value-xyz"
# → Set secret INTERNAL_REGISTRY_TOKEN for repository my-org/sre-infra

# 3. Просмотр существующих секретов
gh codespace secrets list
# → NAME                     UPDATED
# → SRE_VAULT_TOKEN          2026-10-11
# → INTERNAL_REGISTRY_TOKEN  2026-10-11

# 4. Использование секрета в devcontainer.json через подстановку локального окружения:
# {
#   "containerEnv": {
#     "VAULT_TOKEN": "${localEnv:SRE_VAULT_TOKEN}"
#   }
# }

# 5. Удаление секрета
gh codespace secrets unset SRE_VAULT_TOKEN
# → Removed secret SRE_VAULT_TOKEN
```

### Сценарий 6: Ускорение запуска через Prebuilds

Prebuilds компилируют devcontainer, выкачивают Docker-слои и выполняют `onCreateCommand` и `updateContentCommand` заранее. Когда инженер запрашивает создание Codespace, развертывание занимает 5–10 секунд вместо ожидания длительной сборки контейнера.

1. **Создание конфигурации предварительной сборки**:
   - Настройка осуществляется через интерфейс репозитория: `Settings` → `Codespaces` → `Set up prebuild`.
   - Либо через вызов REST API GitHub:
     ```bash
     gh api -X POST /repos/my-org/sre-infra/codespaces/prebuilds \
       -f branch="main" \
       -f location="WestEurope"
     # → { "id": 142857, "branch": "main", "status": "queued" }
     ```
2. **Просмотр состояния и журналов Prebuilds**:
   ```bash
   gh api /repos/my-org/sre-infra/codespaces/prebuilds
   # → [
   # →   {
   # →     "id": 142857,
   # →     "branch": "main",
   # →     "status": "completed",
   # →     "updated_at": "2026-10-11T12:00:00Z"
   # →   }
   # → ]
   ```

### Сценарий 7: Персонализация окружения через Dotfiles

Codespaces поддерживает автоматическую инъекцию персональных утилит и конфигураций каждого инженера:

1. Создается публичный репозиторий `dotfiles` в личном профиле GitHub (например, `github.com/username/dotfiles`).
2. В репозиторий помещаются конфигурационные файлы (`.zshrc`, `.tmux.conf`, `.gitconfig`) и скрипт установки `install.sh` (или `bootstrap.sh`).
3. Пример `install.sh`:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail

   # Создание симлинков на конфигурации
   ln -sf "$(pwd)/.zshrc" "$HOME/.zshrc"
   ln -sf "$(pwd)/.tmux.conf" "$HOME/.tmux.conf"

   # Настройка Git aliases
   git config --global alias.co checkout
   git config --global alias.br branch
   git config --global alias.ci commit
   git config --global alias.st status

   echo "Dotfiles successfully initialized"
   ```
4. В персональных настройках GitHub (`Settings` → `Codespaces` → `Dotfiles`) включается чекбокс `Automatically install dotfiles` и выбирается репозиторий `dotfiles`. При каждом старте любого Codespace скрипт исполняется автоматически.

## Операции и команды

### Справочник команд `gh codespace`

| Команда | Аргументы / Флаги | Назначение |
|---|---|---|
| `gh codespace list` | `--json <fields>`, `-q <query>` | Вывод списка codespaces в табличном или машиночитаемом формате |
| `gh codespace create` | `-r <repo>`, `-b <branch>`, `-m <machine>`, `--idle-timeout <dur>` | Создание нового codespace с заданными параметрами |
| `gh codespace code` | `-c <name>`, `--web`, `--editor <ide>` | Открытие сессии в браузере или локальном редакторе |
| `gh codespace ssh` | `-c <name>`, `--config`, `-- <cmd>` | Подключение по SSH или выполнение удаленной команды |
| `gh codespace cp` | `-c <name>`, `-r`, `<src> <dst>` | Копирование файлов между локальной системой и codespace |
| `gh codespace ports` | `-c <name>` | Список проброшенных сетевых портов |
| `gh codespace ports forward` | `<remote>:<local>`, `-c <name>` | Туннелирование удаленного порта на локальный хост |
| `gh codespace ports visibility` | `<port>:{private\|org\|public}`, `-c <name>` | Управление правами доступа к сетевому порту |
| `gh codespace stop` | `-c <name>` | Остановка работающего codespace |
| `gh codespace delete` | `-c <name>`, `--all`, `--days <N>` | Удаление указанного или всех неиспользуемых codespaces |
| `gh codespace rebuild` | `-c <name>`, `--full` | Пересборка devcontainer (с флагом `--full` с очисткой кэша) |
| `gh codespace logs` | `-c <name>`, `-b` (bundle) | Просмотр или выгрузка архива логов сборки и работы |

### Автоматизация системного администратора

```bash
# 1. Массовая остановка всех работающих codespaces пользователя для экономии квот
gh codespace list --json name,state -q '.[] | select(.state == "Available") | .name' | while read -r cs; do
  echo "Stopping $cs..."
  gh codespace stop -c "$cs"
done
# → Stopping verbose-space-invention-abc123...
# → Codespace 'verbose-space-invention-abc123' stopped.

# 2. Выгрузка полного диагностического архива логов при ошибке создания
gh codespace logs -c verbose-space-invention-abc123 -b ./codespace-logs.zip
# → Bundle saved to ./codespace-logs.zip

# 3. Аудит запущенных сред организации через REST API
gh api /orgs/my-org/codespaces --paginate --jq '.codespaces[] | {name: .name, user: .owner.login, state: .state, machine: .machine.display_name}'
# → {"machine":"4 cores","name":"cs-101","state":"Available","user":"developer1"}
```

### GitHub REST API для Codespaces

| Операция | HTTP метод и эндпоинт | Описание |
|---|---|---|
| Список сред пользователя | `GET /user/codespaces` | Возвращает все активные и остановленные codespaces текущего пользователя |
| Список сред репозитория | `GET /repos/{owner}/{repo}/codespaces` | Возвращает codespaces в рамках конкретного репозитория |
| Создать среду в репозитории | `POST /repos/{owner}/{repo}/codespaces` | Создание codespace с передачей `branch`, `machine`, `devcontainer_path` |
| Остановка среды | `POST /user/codespaces/{codespace_name}/stop` | Принудительная остановка машины |
| Старт остановленной среды | `POST /user/codespaces/{codespace_name}/start` | Запуск остановленной машины |
| Удаление среды | `DELETE /user/codespaces/{codespace_name}` | Безвозвратное удаление codespace и связанных томов |
| Управление секретами репозитория | `GET, PUT, DELETE /repos/{owner}/{repo}/codespaces/secrets` | Чтение метаданных, запись и удаление шифрованных секретов |
| Управление Prebuilds | `GET, POST /repos/{owner}/{repo}/codespaces/prebuilds` | Конфигурирование автоматической предсборки |

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
|---|---|---|---|
| Сбой сборки devcontainer при старте (`Creation failed`) | Синтаксическая ошибка в `devcontainer.json`, невалидный базовый образ или сбой хука | Запустить `gh codespace logs -c <name>` или открыть codespace в аварийном режиме Recovery Container | Исправить ошибку в `devcontainer.json` в окне Recovery Container и выполнить команду `Codespaces: Rebuild Container` |
| Служба запущена, но порт не доступен через Forwarding | Приложение слушает сетевой интерфейс `127.0.0.1` (loopback) вместо `0.0.0.0` | В терминале codespace выполнить `ss -tulpn` или `netstat -tlpn` | Переконфигурировать приложение для прослушивания адреса `0.0.0.0` |
| Команда `docker` выдает ошибку `Cannot connect to Docker daemon` | В `devcontainer.json` не подключена фича Docker-in-Docker или не запущен демон dockerd | Проверить наличие сокета `ls -la /var/run/docker.sock` и статус `sudo service docker status` | Подключить фичу `ghcr.io/devcontainers/features/docker-in-docker:2` и добавить флаг `--init` в `runArgs` |
| Ошибка `Permission denied` при записи в `/workspaces/<repo>` | Несоответствие UID/GID между пользователем контейнера и владельцем смонтированного тома | Выполнить `id` и `ls -ld /workspaces/<repo-name>` | Указать `remoteUser: "vscode"` (UID 1000) либо добавить `sudo chown -R vscode:vscode /workspaces` в `postCreateCommand` |
| Переменные из Codespace Secrets отсутствуют в сессии | Секрет был создан после старта codespace, либо секрет не привязан к данному репозиторию | Проверить вывод `env \| grep SECRET` и `gh codespace secrets list` | Добавить доступ к репозиторию в настройках секрета и перезапустить codespace (`gh codespace stop` + старт) |
| SSH-подключение отклоняется (`Permission denied / connection reset`) | Не сгенерирован или устарел ключ подключения `gh` | Проверить локальный конфиг `~/.ssh/codespaces_config` | Перегенерировать конфиг через `gh codespace ssh --config > ~/.ssh/codespaces_config` |

### Восстановление через Recovery Container

Если контейнер падает при инициализации из-за критической ошибки в Dockerfile или хуках жизненного цикла:

1. Codespaces автоматически определяет невозможность поднятия целевого devcontainer и предлагает опцию: **«Open in recovery container»**.
2. В режиме восстановления запускается стандартный изолированный контейнер с установленным Git и редактором. Вся директория `/workspaces/<repo-name>` остается смонтированной.
3. Администратор или разработчик редактирует `.devcontainer/devcontainer.json` прямо в редакторе, исправляя опечатки или удаляя сбойный хук.
4. В командной палитре (`Ctrl+Shift+P` / `F1`) вызывается команда: `Codespaces: Rebuild Container`.
5. Среда пересобирается с исправленной конфигурацией.

## Лучшие практики

1. **Хранение конфигурации в Git**:
   - Конфигурация `.devcontainer/devcontainer.json` и сопутствующие файлы должны находиться в репозитории проекта и проходить обязательный код-ревью.
2. **Фиксация версий базовых образов и Features**:
   - Никогда не используйте тег `:latest` для системных образов в промышленной разработке. Явно фиксируйте мажорные и минорные версии (`ubuntu:24.04`, `docker-in-docker:2`).
3. **Разделение задач между Lifecycle Hooks**:
   - Системные бинарные зависимости ставьте в `onCreateCommand` (чтобы они попали в prebuild кэш).
   - Зависимости проекта устанавливайте в `updateContentCommand`.
   - В `postCreateCommand` оставляйте только легкие финальные операции (установка git-хуков, генерация локальных конфигов). Это минимизирует время старта.
4. **Безопасность сетевых портов**:
   - Оставляйте видимость проброшенных портов в значении `private` по умолчанию.
   - Никогда не переключайте служебные порты баз данных, redis или метрик в режим `public`.
5. **Настройка политик организации (Policies)**:
   - Администраторам организации рекомендуется задавать политики:
     - Ограничение максимального размера виртуальных машин (например, запрет машин более 4 cores без одобрения).
     - Принудительный таймаут простоя (`idle timeout` не более 30 минут) для предотвращения списания квот в нерабочее время.
     - Ограничение времени хранения неактивных сред (`retention period` не более 7 дней).
6. **Непривилегированный пользователь**:
   - Всегда настраивайте `remoteUser: "vscode"` вместо работы под `root`. Для команд, требующих повышенных привилегий, используйте беспарольный `sudo` внутри контейнера.
7. **Персонализация через Dotfiles**:
   - Выносите пользовательские предпочтения (zsh-темы, алиасы, плагины) в персональные репозитории `dotfiles`, сохраняя `devcontainer.json` максимально чистым и командным.

## Дополнительная информация

- **[GitHub CLI](./github_cli.md)** — консольный клиент `gh` для управления репозиториями, секретами и прямых вызовов API.
- **[GitHub API](./github_api.md)** — справочник эндпоинтов REST и GraphQL для автоматизации инфраструктуры GitHub.
- **[Сетевая безопасность](./network-security.md)** — сетевая изоляция, egress-фильтрация и политики IP allow list.
- **[Управление секретами](./secrets_management.md)** — архитектура безопасного хранения и ротации секретов.
- **Официальная спецификация Development Containers**: [containers.dev](https://containers.dev/).
- **Официальная документация GitHub**: [GitHub Codespaces Documentation](https://docs.github.com/en/codespaces).
