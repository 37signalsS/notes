# Самостоятельные раннеры (Self-hosted Runners): Настройка и управление

**Актуально для:** Self-hosted runners, октябрь 2026 (runner app v2.338.x, ephemeral registration, runner update policies); для GitHub Enterprise Server — 3.14+

Self-hosted runners — это выделенные физические серверы, виртуальные машины или контейнеры в локальной инфраструктуре (on-premise / bare-metal), администрируемые инженерами и используемые для выполнения задач GitHub Actions. В отличие от стандартных управляемых раннеров GitHub, собственные раннеры позволяют изолировать выполнение задач внутри закрытого сетевого периметра, задействовать специализированное аппаратное обеспечение (локальные GPU, специфичные архитектуры CPU, аппаратные ключи), кэшировать тяжелые сборочные артефакты и обращаться к внутренним ресурсам без публичных шлюзов.

По умолчанию классические self-hosted раннеры являются **stateful** (сохраняют состояние файловой системы, процессы и переменные окружения между запусками воркфлоу). Это создает критические риски безопасности и стабильности при повторном использовании сред. Для производственной эксплуатации применяются эфемерные раннеры с ключом `--ephemeral`, одноразовая JIT-конфигурация либо оркестрация через [Actions Runner Controller](./actions_runner_controller.md).

## Определения

- **Self-hosted Runner**: Агент GitHub Actions, развернутый на подконтрольном сервере и поддерживающий постоянное исходящее соединение с GitHub Actions Service.
- **Runner Application**: Кроссплатформенное приложение на базе .NET (с внутренним рантаймом Node.js 24), управляющее выполнением шагов воркфлоу, получением задач и отправкой логов.
- **Runner Registration Token**: Краткоживущий токен (время жизни — 60 минут), генерируемый через GitHub API для первоначальной регистрации и привязки агента к репозиторию, организации или предприятию.
- **Runner Group**: Логический пул раннеров на уровне организации или предприятия с разграничением прав доступа (RBAC), определяющий, какие репозитории и воркфлоу имеют право отправлять задачи в данный пул.
- **Ephemeral Runner**: Раннер, сконфигурированный с флагом `--ephemeral`. Принимает ровно одну задачу (`job`), выполняет ее, дерегистрируется на стороне GitHub Actions и очищает локальную конфигурацию сессии.
- **JIT (Just-In-Time) Configuration**: Механизм динамической генерации зашифрованного конфигурационного пакета (`encoded_jit_config`) через REST API, позволяющий запустить раннер без сохранения долгоживущих учетных данных и без предварительного вызова `config.sh`.
- **Runner Hooks**: Механизм запуска системных скриптов (`ACTIONS_RUNNER_HOOK_JOB_STARTED` и `ACTIONS_RUNNER_HOOK_JOB_COMPLETED`), выполняемых перед началом задачи и сразу после ее завершения.
- **Runner Update Policy**: Политика обновления бинарных файлов агента. Флаг `--disableupdate` блокирует автоматическое обновление приложения при появлении новых версий на серверах GitHub.

## Архитектура и модель работы

### Модель сетевого взаимодействия

Раннер взаимодействует с управляющим сервисом GitHub Actions исключительно по модели **исходящего опроса (outbound long-polling / WebSockets)**. Открытие входящих сетевых портов на сервере или в корпоративном файрволе **не требуется**.

```text
Локальный сервер (On-premise / DMZ)          GitHub Actions Service (Control Plane)
┌─────────────────────────────────┐                 ┌─────────────────────────────────┐
│ Actions Runner Service          │                 │ GitHub Orchestrator / API       │
│                                 │                 │                                 │
│  1. Long-polling / WebSockets   │                 │                                 │
│     HTTPS (TCP 443, outbound)   ├────────────────►│ Очередь задач (Job Queue)       │
│                                 │                 │                                 │
│  2. Прием задачи (Job dispatch) │◄────────────────┤ Назначение задачи по runs-on    │
│                                 │                 │                                 │
│  3. Выполнение шагов сборки     │                 │                                 │
│     (step -> step -> step)      │                 │                                 │
│                                 │                 │                                 │
│  4. Стриминг логов и артефактов │────────────────►│ Отображение в UI и Audit Log    │
└─────────────────────────────────┘                 └─────────────────────────────────┘
```

1. **Инициализация**: При запуске приложение устанавливает защищенное соединение по HTTPS (порт 443) с `https://github.com` (или локальным инстансом GitHub Enterprise Server) и открывает сессию ожидания задач.
2. **Диспетчеризация**: GitHub Orchestrator сопоставляет требования задачи воркфлоу (`runs-on: [self-hosted, ...]`) с зарегистрированными метками агента и правами группы раннеров.
3. **Исполнение**: Агент принимает контекст задачи, секреты и параметры, клонирует репозиторий в локальный рабочий каталог `_work` и исполняет инструкции.
4. **Телеметрия**: Логи шагов и результаты передаются обратно в управляющий сервис в реальном времени.

### Иерархия уровней раннеров

Раннеры могут регистрироваться на трех уровнях иерархии доступа:

```text
Enterprise Level (Только GitHub Enterprise)
    ↓ Доступен всем организациям предприятия
Organization Level
    ↓ Доступен репозиториям организации в соответствии с Runner Group
Repository Level
    ↓ Изолирован в рамках конкретного репозитория
```

- **Repository-level**: Привязан к одному конкретному репозиторию. Применяется для узкоспециализированных задач (например, физический стенд с редким контроллером).
- **Organization-level**: Централизованный пул на уровне организации. Позволяет разделять раннеры между проектами с помощью Runner Groups и централизованно контролировать безопасность.
- **Enterprise-level**: Пул общекорпоративного уровня с гранулярным делегированием организациям.

### Файловая структура каталога раннера

После распаковки и конфигурации каталог раннера содержит следующие ключевые компоненты:

```text
/opt/actions-runner/
├── bin/                          # Системные бинарники рантайма (.NET, Node.js 24)
│   └── installdependencies.sh    # Скрипт установки библиотек ОС
├── config.sh                     # Скрипт регистрации и первичной настройки
├── run.sh                        # Запуск агента в консольном режиме (foreground)
├── runsvc.sh                     # Обертка для запуска под управлением systemd
├── svc.sh                        # Скрипт управления службой systemd
├── .credentials                  # Локальные ключи сессии и RSA-сертификат (создается при регистрации)
├── .runner                       # JSON-конфигурация (ID агента, имя пула, сервер)
├── .env                          # Локальные переменные окружения и прокси для службы
├── .path                         # Дополнительные пути к системным утилитам в PATH
├── _diag/                        # Диагностические логи (Runner_*.log, Worker_*.log)
└── _work/                        # Рабочие каталоги воркфлоу и клонированные репозитории
```

### Безопасность и модель изоляции

> [!WARNING]
> **Категорический запрет для публичных репозиториев:** Никогда не используйте self-hosted раннеры для публичных репозиториев. Любой внешний пользователь может отправить Pull Request с вредоносным workflow-файлом и получить неограниченное исполнение кода внутри вашей локальной сети, доступ к сокету Docker и внутренним сервисам.

- **Stateful против Ephemeral**: В режиме stateful компрометация одного воркфлоу оставляет следы на диске (трояны, модифицированные кэши, фоновые процессы). В режиме `--ephemeral` агент завершает работу после первой задачи, что предотвращает персистентность угроз.
- **Разделение прав**: Служба раннера обязана работать от имени выделенного непривилегированного пользователя операционной системы (например, `runner`), без членства в `sudoers`.

## Практические сценарии

### Сценарий 1: Установка зависимостей и регистрация раннера в репозитории под отдельным пользователем

Развертывание production-агента на выделенном сервере Linux (Ubuntu 22.04/24.04, Debian 12 или Rocky Linux 9).

**Предварительные требования**: Логический доступ по SSH с правами root/sudo, исходящий доступ к GitHub по порту 443, утилита `gh` (GitHub CLI) с правами администратора репозитория.

```bash
# 1. Создание выделенного системного пользователя без пароля
sudo useradd -m -d /opt/actions-runner -s /bin/bash runner

# 2. Переход в каталог и загрузка официального пакета агента v2.338.0
cd /opt/actions-runner
sudo -u runner curl -o actions-runner-linux-x64-2.338.0.tar.gz \
  -L https://github.com/actions/runner/releases/download/v2.338.0/actions-runner-linux-x64-2.338.0.tar.gz

# Проверка контрольной суммы SHA-256
echo "af4b794c1bc41d73d40535e3fe092a39f9679cd8d965954c2aca25a05ca41d32  actions-runner-linux-x64-2.338.0.tar.gz" | sha256sum -c
# → actions-runner-linux-x64-2.338.0.tar.gz: OK

# Распаковка от имени пользователя runner
sudo -u runner tar xzf actions-runner-linux-x64-2.338.0.tar.gz
sudo -u runner rm -f actions-runner-linux-x64-2.338.0.tar.gz

# 3. Установка системных зависимостей ОС (libicu, libssl, curl)
sudo ./bin/installdependencies.sh

# 4. Получение токена регистрации репозитория (время жизни 60 минут)
REG_TOKEN=$(gh api -X POST /repos/{owner}/{repo}/actions/runners/registration-token --jq '.token')

# 5. Регистрация раннера с фиксированными метками
sudo -u runner ./config.sh \
  --url https://github.com/{owner}/{repo} \
  --token "$REG_TOKEN" \
  --name "srv-ci-runner-01" \
  --labels "self-hosted,linux,x64,baremetal" \
  --work "/opt/actions-runner/_work" \
  --unattended \
  --replace

# → √ Runner successfully added
# → √ Runner connection test completed successfully

# 6. Установка и запуск системной службы systemd
sudo ./svc.sh install runner
sudo ./svc.sh start

# 7. Проверка статуса службы
sudo ./svc.sh status
# → ● actions.runner.{owner}-{repo}.srv-ci-runner-01.service - GitHub Actions Runner
# →    Active: active (running)
```

**Валидация через GitHub API:**

```bash
gh api /repos/{owner}/{repo}/actions/runners --jq '.runners[] | {name: .name, status: .status, os: .os}'
# → { "name": "srv-ci-runner-01", "status": "online", "os": "linux" }
```

### Сценарий 2: Регистрация раннера в организации и ограничение через Runner Group

Изоляция инфраструктуры сборки с разделением на пулы окружений (например, `production-runners` с доступом только для утвержденных защищенных репозиториев).

```bash
# 1. Создание закрытой группы раннеров на уровне организации
GROUP_ID=$(gh api -X POST /orgs/{org}/actions/runner-groups \
  -f name="production-runners" \
  -f visibility="selected" \
  --jq '.id')

# Назначение репозиториев, которым разрешено использовать эту группу
gh api -X PUT /orgs/{org}/actions/runner-groups/"$GROUP_ID"/repositories \
  -f "selected_repository_ids[]=[12345678, 87654321]"

# 2. Получение токена регистрации уровня организации (требуются права admin:org)
ORG_TOKEN=$(gh api -X POST /orgs/{org}/actions/runners/registration-token --jq '.token')

# 3. Регистрация агента с привязкой к созданной группе
cd /opt/actions-runner
sudo -u runner ./config.sh \
  --url https://github.com/{org} \
  --token "$ORG_TOKEN" \
  --name "srv-prod-worker-01" \
  --runnergroup "production-runners" \
  --labels "self-hosted,linux,x64,prod-secure" \
  --unattended \
  --replace

# 4. Установка службы и запуск
sudo ./svc.sh install runner
sudo ./svc.sh start

# 5. Проверка принадлежности раннера к группе
gh api /orgs/{org}/actions/runner-groups/"$GROUP_ID"/runners --jq '.runners[].name'
# → srv-prod-worker-01
```

### Сценарий 3: Настройка работы через корпоративный HTTP/HTTPS-прокси

В изолированных дата-центрах прямой доступ к интернету заблокирован, трафик выпускается только через инспектирующий форвард-прокси.

Настройка переменных прокси выполняется через файл `.env` в корневом каталоге приложения агента:

```bash
# Создание конфигурации прокси для службы
sudo tee /opt/actions-runner/.env <<'EOF'
https_proxy=http://proxy.corp.internal:8080
http_proxy=http://proxy.corp.internal:8080
no_proxy=corp.internal,gitlab.corp.internal,registry.corp.internal
EOF

sudo chown runner:runner /opt/actions-runner/.env
sudo chmod 600 /opt/actions-runner/.env
```

> [!IMPORTANT]
> **Ограничение `no_proxy` в Actions Runner:** Раннер **не поддерживает** указание диапазонов CIDR (например, `192.168.0.0/16`) и числовых IP-адресов в переменной `no_proxy`. В список исключений вносятся исключительно доменные имена и FQDN-хосты.

После создания `.env` служба перезапускается:

```bash
sudo ./svc.sh stop
sudo ./svc.sh start
# → Проверка подключения в журнале:
tail -n 20 /opt/actions-runner/_diag/Runner_*.log | grep -i "proxy"
# → Using proxy server: http://proxy.corp.internal:8080
```

### Сценарий 4: Непрерывный цикл эфемерных раннеров с автоматической перерегистрацией

Флаг `--ephemeral` обеспечивает удаление регистрации агента и очистку сессии после выполнения ровно одной задачи. Однако после завершения работы бинарника повторный запуск `run.sh` невозможен без повторной регистрации в GitHub.

Для организации непрерывного пула эфемерных раннеров на базе systemd без Kubernetes создается системный воркер-скрипт, запрашивающий свежий токен перед каждым вызовом:

```bash
# 1. Создание скрипта цикла перерегистрации
sudo tee /opt/actions-runner/run-ephemeral.sh <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

RUNNER_DIR="/opt/actions-runner"
REPO_URL="https://github.com/my-org/my-repo"
API_PATH="repos/my-org/my-repo/actions/runners/registration-token"
HOSTNAME_PREFIX=$(hostname -s)

cd "$RUNNER_DIR"

while true; do
  RUNNER_NAME="${HOSTNAME_PREFIX}-eph-$(date +%s)"
  echo "==> [$(date -Iseconds)] Запрос нового токена регистрации..."
  
  # Получение токена через GitHub CLI или локально сохраненный App Token
  TOKEN=$(gh api -X POST "$API_PATH" --jq '.token')
  
  echo "==> Регистрация эфемерного агента: $RUNNER_NAME"
  ./config.sh \
    --url "$REPO_URL" \
    --token "$TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "self-hosted,linux,ephemeral" \
    --ephemeral \
    --unattended \
    --replace

  echo "==> Ожидание и выполнение одной задачи..."
  ./run.sh

  echo "==> Задача завершена. Очистка локального рабочего каталога..."
  rm -rf "$RUNNER_DIR/_work/"*
  sleep 2
done
EOF

sudo chmod +x /opt/actions-runner/run-ephemeral.sh
sudo chown runner:runner /opt/actions-runner/run-ephemeral.sh

# 2. Настройка systemd-юнита
sudo tee /etc/systemd/system/github-ephemeral-runner.service <<'EOF'
[Unit]
Description=GitHub Actions Continuous Ephemeral Runner Worker
After=network.target

[Service]
Type=simple
User=runner
WorkingDirectory=/opt/actions-runner
ExecStart=/opt/actions-runner/run-ephemeral.sh
Restart=always
RestartSec=5
TimeoutStopSec=300
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now github-ephemeral-runner.service
```

### Сценарий 5: Безопасный запуск по Just-In-Time (JIT) конфигурации через REST API

JIT-конфигурация устраняет необходимость передачи регистрационных токенов на сервер. GitHub API генерирует единый зашифрованный блоб конфигурации, с которым агент запускается сразу на выполнение.

```bash
# 1. Генерация JIT-конфигурации для разовой сборки
JIT_RESPONSE=$(gh api -X POST /repos/{owner}/{repo}/actions/runners/generate-jitconfig \
  -f name="jit-worker-01" \
  -f runner_group_id=1 \
  -f "labels[]=['self-hosted','linux','x64']" \
  -F work_folder="_work")

ENCODED_JIT=$(echo "$JIT_RESPONSE" | jq -r '.encoded_jit_config')

# 2. Запуск распакованного агента напрямую с JIT-параметром (без предварительного ./config.sh)
cd /opt/actions-runner
sudo -u runner ./run.sh --jitconfig "$ENCODED_JIT"
# → √ Connected to GitHub
# → 2026-10-11 17:20:00Z: Listening for Jobs
# → Running job: build-and-test
# → Job build-and-test completed with result: Succeeded
# → Runner listener exited with code 0
```

После завершения задачи раннер автоматически удаляется из репозитория на серверах GitHub.

### Сценарий 6: Pre- и Post-job хуки для очистки среды и Docker-кэшей

Для предотвращения накопления зависших процессов, временных файлов и «мусорных» Docker-контейнеров на хосте используются встроенные системные хуки.

```bash
# 1. Создание каталога для системных скриптов очистки
sudo mkdir -p /opt/actions-runner/hooks

# 2. Pre-job скрипт (подготовка изоляции перед стартом)
sudo tee /opt/actions-runner/hooks/pre-job.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "==> [Pre-Job Hook] Старт задачи: $GITHUB_JOB в воркфлоу $GITHUB_WORKFLOW"
# Очистка возможных зависших пользовательских процессов от предыдущих сборок
pkill -u runner -f "node|python|java" || true
EOF

# 3. Post-job скрипт (гарантированная очистка после завершения)
sudo tee /opt/actions-runner/hooks/post-job.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "==> [Post-Job Hook] Завершение задачи. Очистка ресурсов..."
# Принудительная остановка и удаление всех запущенных сборкой контейнеров Docker
if command -v docker &> /dev/null; then
  docker ps -q --filter "label=com.github.actions.runner=true" | xargs -r docker stop || true
  docker system prune -f --volumes --filter "until=12h" || true
fi
# Удаление временных файлов из /tmp
find /tmp -maxdepth 1 -user runner -mmin +60 -exec rm -rf {} + || true
EOF

sudo chmod +x /opt/actions-runner/hooks/*.sh
sudo chown -R runner:runner /opt/actions-runner/hooks

# 4. Подключение хуков в конфигурационный файл .env
sudo tee -a /opt/actions-runner/.env <<'EOF'
ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/actions-runner/hooks/pre-job.sh
ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/opt/actions-runner/hooks/post-job.sh
EOF

# Перезапуск службы
sudo ./svc.sh stop && sudo ./svc.sh start
```

### Сценарий 7: Фиксация версий и отключение автообновления (`--disableupdate`)

В закрытых периметрах (air-gapped) или при строгом контроле релизов внезапное автоматическое обновление бинарников раннера может сломать пайплайны сборки.

```bash
# Регистрация агента с запретом автообновления бинарных файлов
cd /opt/actions-runner
sudo -u runner ./config.sh \
  --url https://github.com/{owner}/{repo} \
  --token "$REG_TOKEN" \
  --name "srv-pinned-runner" \
  --disableupdate \
  --unattended \
  --replace

# Регламент планового ручного обновления раннера админом:
# 1. Остановка службы
sudo ./svc.sh stop

# 2. Загрузка новой проверенной версии (например, v2.338.0)
curl -o new-runner.tar.gz -L https://github.com/actions/runner/releases/download/v2.338.0/actions-runner-linux-x64-2.338.0.tar.gz
tar xzf new-runner.tar.gz
rm -f new-runner.tar.gz

# 3. Проверка зависимостей и запуск
sudo ./bin/installdependencies.sh
sudo ./svc.sh start
```

## Команды и API-операции

### Управление через GitHub CLI и REST API

| Операция | Команда / Эндпоинт | Назначение |
|---|---|---|
| Список раннеров репозитория | `gh api /repos/{owner}/{repo}/actions/runners --jq '.runners[] \| {id, name, status, busy}'` | Получение статуса агентов (online/offline) и флага занятости |
| Список раннеров организации | `gh api /orgs/{org}/actions/runners --jq '.runners[] \| {id, name, status, runner_group_id}'` | Мониторинг всех раннеров организации |
| Список Runner Groups | `gh api /orgs/{org}/actions/runner-groups --jq '.runner_groups[] \| {id, name, visibility}'` | Аудит групп доступа и видимости |
| Токен регистрации (repo) | `gh api -X POST /repos/{owner}/{repo}/actions/runners/registration-token --jq '.token'` | Генерация одноразового токена (TTL 60 мин) |
| Токен регистрации (org) | `gh api -X POST /orgs/{org}/actions/runners/registration-token --jq '.token'` | Токен для регистрации на уровне организации |
| Генерация JIT-конфигурации | `gh api -X POST /repos/{owner}/{repo}/actions/runners/generate-jitconfig -f name="r1"` | Создание разового пакета запуска для ephemeral-раннера |
| Добавление меток (labels) | `gh api -X POST /repos/{owner}/{repo}/actions/runners/{id}/labels -f 'labels[]=gpu'` | Добавление кастомных меток к раннеру |
| Замена всех меток | `gh api -X PUT /repos/{owner}/{repo}/actions/runners/{id}/labels -f 'labels[]=prod'` | Полная перезапись набора меток агента |
| График вывода из эксплуатации | `gh api /orgs/{org}/actions/runners/deprecations/{version}` | Проверка даты EOL для используемой версии раннера |
| Удаление раннера через API | `gh api -X DELETE /repos/{owner}/{repo}/actions/runners/{runner_id}` | Принудительное удаление упавшего или мертвого агента |

### Локальные утилиты раннера

| Утилита / Команда | Описание и ключевые параметры |
|---|---|
| `./config.sh` | Первичная регистрация агента (`--url`, `--token`, `--name`, `--runnergroup`, `--labels`, `--work`, `--ephemeral`, `--disableupdate`, `--unattended`, `--replace`) |
| `./config.sh remove --token <T>` | Корректная дерегистрация раннера на стороне GitHub и очистка локальной сессии |
| `./run.sh` | Интерактивный запуск в текущей консоли (foreground) для отладки |
| `./run.sh --jitconfig <BLOB>` | Запуск раннера с использованием строки Just-In-Time конфигурации |
| `./bin/installdependencies.sh` | Системный скрипт установки недостающих пакетов дистрибутива Linux |
| `sudo ./svc.sh install [user]` | Регистрация системного сервиса systemd от имени указанного пользователя |
| `sudo ./svc.sh start` | Запуск сервиса systemd |
| `sudo ./svc.sh stop` | Корректная остановка сервиса |
| `sudo ./svc.sh status` | Проверка текущего статуса демона systemd |
| `sudo ./svc.sh uninstall` | Удаление сервиса systemd из `/etc/systemd/system` |

## Устранение неполадок

| Проблема / Ошибка | Первопричина | Диагностика и метод устранения |
|---|---|---|
| Раннер отображается в статусе `Offline` | Служба остановлена, упал процесс или заблокирован исходящий сетевой трафик | Проверить статус службы: `sudo ./svc.sh status`. Проверить журнал systemd: `journalctl -u actions.runner.* -n 50 --no-pager`. Проверить сетевую доступность: `curl -Iv https://github.com` и `openssl s_client -connect github.com:443`. |
| `Registration token has expired` | Токен регистрации действителен только 60 минут с момента генерации | Получить свежий токен через `gh api -X POST .../registration-token` и повторить запуск `./config.sh`. |
| `Job timeout / Runner did not pick up job` | Несовпадение меток в воркфлоу (`runs-on`) с метками раннера или ограничения группы | Проверить требования в workflow (`runs-on: [self-hosted, ...]`). Проверить метки агента: `gh api .../actions/runners`. Убедиться, что репозиторий добавлен в список разрешенных для Runner Group. |
| `403 Forbidden` при вызове API регистрации | Недостаточно прав у используемого токена PAT или GitHub App | Для уровня репозитория токен обязан иметь права `repo` или `actions:write`; для уровня организации — `admin:org`. |
| `No space left on device` в каталоге `_work` | Накопление артефактов старых сборок, тяжелых Docker layers или кэшей пакетов | Вынести `_work` на отдельную файловую систему или диск. Настроить post-job хук (Сценарий 6) либо периодический systemd timer для запуска `docker system prune -af` и очистки `_work`. |
| `permission denied` при обращении к `/var/run/docker.sock` | Пользователь `runner` не состоит в группе `docker` | Добавить пользователя в группу: `sudo usermod -aG docker runner`. Перезапустить службу: `sudo ./svc.sh stop && sudo ./svc.sh start`. Проверить через `sudo -u runner docker ps`. |
| Ошибка запуска: `libicuuc.so cannot open shared object file` | Отсутствуют системные библиотеки .NET Core в операционной системе | Выполнить скрипт установки зависимостей: `sudo /opt/actions-runner/bin/installdependencies.sh`. Для RHEL/Rocky: `sudo dnf install -y libicu krb5-libs zlib`. |
| Раннер не подключается через прокси-сервер | Прокси настроен с IP-адресами в `no_proxy` или переменные не попали в сервис | Actions Runner игнорирует IP/CIDR в `no_proxy`. Переписать `no_proxy` только на доменные имена (Сценарий 3). Задать параметры в `/opt/actions-runner/.env`, а не только в `.bashrc`. |
| Ephemeral runner падает с ошибкой `Runner is not configured` | Служба пытается повторно вызвать `run.sh` без перерегистрации | Эфемерный раннер после 1 задачи уничтожает свою конфигурацию. Использовать скрипт-обертку цикла перерегистрации (Сценарий 4) либо JIT-режим. |
| Принудительное отключение раннера: `Runner version is deprecated` | Версия раннера устарела более чем на 30 дней и заблокирована платформой | Обновить агент до актуальной версии (v2.338.x) либо проверить график EOL через API: `GET /orgs/{org}/actions/runners/deprecations/{version}`. |

## Лучшие практики

1. **Строгий запрет для публичных репозиториев**: Никогда не подключайте self-hosted раннеры к публичным репозиториям или репозиториям, принимающим внешние форки. Любой Pull Request может выполнить произвольный код на хосте с доступом к внутренней сети.
2. **Использование эфемерных раннеров в production**: Вся производственная CI/CD инфраструктура должна строиться на базе эфемерных агентов (`--ephemeral`, JIT-токены или [Actions Runner Controller](./actions_runner_controller.md)). Это гарантирует чистую среду для каждой задачи и исключает утечку секретов между сборками.
3. **Принцип наименьших привилегий ОС**: Запускайте службу исключительно от имени выделенного непривилегированного пользователя `runner`. Запретите пользователю `sudo` без пароля. При необходимости используйте rootless Docker или Podman.
4. **Харденинг службы через systemd**: Добавляйте директивы изоляции в unit-файл службы systemd:
   ```ini
   ProtectSystem=full
   ProtectHome=read-only
   PrivateTmp=true
   NoNewPrivileges=true
   LimitNOFILE=65536
   ```
5. **Контроль исходящего сетевого трафика (Egress Filtering)**: Блокируйте весь входящий сетевой трафик на уровне файрвола (iptables/nftables). Для исходящего трафика разрешайте только TCP 443 к эндпоинтам GitHub (`github.com`, `api.github.com`, `*.actions.githubusercontent.com`) и внутренним реестрам артефактов / Nexus / Harbor.
6. **Автоматизация очистки диска через хуки**: Подключайте `ACTIONS_RUNNER_HOOK_JOB_COMPLETED` для гарантированного удаления временных контейнеров Docker, dangling images и временных каталогов после каждого выполнения воркфлоу.
7. **Изоляция сред через Runner Groups**: Разделяйте раннеры по пулам безопасности (`prod-secure`, `staging`, `dev`). Для production-пула устанавливайте `visibility: selected` и выдавайте доступ только защищенным репозиториям с ограниченным кругом мейнтейнеров.
8. **Управление обновлениями в критичных контурах**: Если обновление агента требует предварительного тестирования, регистрируйте раннеры с флагом `--disableupdate` и ведите плановые обновления бинарников по регламенту.

## Дополнительная информация

- **[Actions Runner Controller (ARC)](./actions_runner_controller.md)** — Масштабирование эфемерных раннеров GitHub Actions в Kubernetes.
- **[Сетевая безопасность и харденинг](./network-security.md)** — Защита сетевого периметра, настройка прокси и предотвращение утечек данных из CI/CD.
- **[Ограничения среды выполнения](./Environment_Limitations.md)** — Технические лимиты, спецификации и отличия GitHub-hosted от self-hosted раннеров.
- **[Ключевые концепции GitHub Actions](./Core_Concept.md)** — Архитектура воркфлоу, модель выполнения задач и жизненный цикл пайплайнов.
- **[GitHub CLI: Справочник по автоматизации](./github_cli.md)** — Управление раннерами и воркфлоу через консольную утилиту `gh`.
- **Официальная документация GitHub**:
  - [About self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners)
  - [Adding self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners)
  - [Running scripts before or after a job](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/running-scripts-before-or-after-a-job)
  - [Using a proxy server with self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/using-a-proxy-server-with-self-hosted-runners)
  - [REST API endpoints for self-hosted runners](https://docs.github.com/en/rest/actions/self-hosted-runners)
