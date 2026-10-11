# Самостоятельные раннеры (Self-hosted Runners): Настройка и управление

**Актуально для:** Self-hosted runners, октябрь 2026 (runner app v2.320+, ephemeral registration, runner update policies); для GitHub Enterprise Server — 3.14+

Self-hosted runners — это серверы (физические, виртуальные или контейнеры), которые вы управляете сами и используете для выполнения задач GitHub Actions. В отличие от GitHub-hosted раннеров (upcoming, ephemeral by default), self-hosted раннеры сохраняют состояние между задачами, что позволяет кэшировать зависимости и использовать кастомное оборудование. Тем не менее, по умолчанию self-hosted раннеры **stateful** (не эфемерны), что создаёт security-риски — для production используйте флаг `--ephemeral` или [Actions Runner Controller](./actions_runner_controller.md).

## Определения

- **Self-hosted Runner**: Сервер в вашей инфраструктуре, зарегистрированный в GitHub Actions для выполнения workflow task-ов. Управляется владельцем (не GitHub).
- **Runner Registration Token**: Одноразовый токен (жизнь ~1 час), выдающийся API для регистрации нового раннера в репозитории или организации.
- **Runner Application**: Бинарник (`run.sh` / `runsvc.sh` на Linux, `run.cmd` на Windows), который регистрируется и поддерживает long-polling со службой GitHub Actions.
- **Runner Group**: Группа раннеров с общими правилами доступа (кто может использовать раннеры группы). Поддерживается на уровне organization.
- **Ephemeral Runner**: Раннер, зарегистрированный с флагом `--ephemeral`, который автоматически удаляется после выполнения **одной** задачи. Обеспечивает чистую среду.
- **Runner Update Policy**: Настройка, определяющая, как раннер обновляется (автоматически, вручную, или запрещено обновление).
- **JIT (Just-In-Time) Registration**: Способ регистрации раннера с токеном, живущим ровно до первого job — используется в GHE для минимизации токен-риска.

## Архитектура и модель работы

### Как раннер взаимодействует с GitHub Actions

```text
Runner Application (на вашем сервере)
    │
    │ long-polling HTTPS (outbound, ports 443/80)
    │
    │ 1. Polls: GET /actions/runner/register
    │ 2. Receives: job to execute
    │ 3. Runs: step → step → step
    │ 4. Reports: logs, artifacts, result
    │
GitHub Actions Orchestrator
```

- Раннер инициализирует исходящее HTTPS-соединение (outbound 443) — **входящих портов не требуется**.
- Job dispatch принимает решение оркестратор GitHub (какой раннер получит задачу) на основе меток (`runs-on`).
- Stateful по умолчанию: файловая система, переменные окружения и кэш сохраняются между job-ами.

### Иерархия раннеров

```text
Enterprise (Enterprise runners)
    ↓ (наследуется org-ами)
Organization (Org-level runners, Runner Groups)
    ↓ (наследуется репозиториями)
Repository (Repo-level runners)
```

- **Repository-level**: доступны только в этом репозитории.
- **Organization-level**: доступны во всех репозиториях org (или в selected). Группы раннеров управляют dostupom.
- **Enterprise-level**: доступны во всех org Enterprise (только для GHE / Enterprise Cloud).

## Практические сценарии

### Сценарий 1: Регистрация self-hosted раннера в репозитории

**Предварительные требования**: Linux-сервер (RHEL 9, Ubuntu 22.04/24.04, Debian 12), доступ к GitHub с правами администратора репозитория, outbound HTTPS (443).

```bash
# 1. Получить токен регистрации (1-hour TTL)
gh api -X POST /repos/{owner}/{repo}/actions/runners/registration-token \
  --jq '.token' > reg-token

# 2. Скачать и распаковать runner
mkdir /opt/actions-runner
cd /opt/actions-runner
curl -o actions-runner-linux-x64.tar.gz \
  -L https://github.com/actions/runner/releases/download/v2.320.0/actions-runner-linux-x64-2.320.0.tar.gz
tar xzf actions-runner-linux-x64-2.320.0.tar.gz

# 3. Создать сервис и зарегистрировать раннер (ephemeral)
TOKEN=$(cat reg-token)
./config.sh --url https://github.com/{owner}/{repo} \
  --token "$TOKEN" \
  --name "runner-01" \
  --labels "self-hosted,linux,arm64" \
  --work "/tmp/runner-work" \
  --ephemeral \
  --unattended

# 4. Запустить как systemd-сервис
sudo ./svc.sh install
sudo ./svc.sh start

# Проверить статус
sudo systemctl status actions.runner.{owner}-{repo}.runner-01.service
```

- **Валидация**: в Settings → Actions → Runners репозитория раннер статуса `Online`; `gh api /repos/{owner}/{repo}/actions/runners --jq '.runners[].name'` возвращает имя.
- **`--ephemeral`**: раннер удаляется после одного job. Для production обязательно используйте этот флаг или [ARC](./actions_runner_controller.md) для Kubernetes.

### Сценарий 2: Регистрация раннера на уровне организации

```bash
# 1. Получить токен (org-level, требует admin:org)
gh api -X POST /orgs/{org}/actions/runners/registration-token \
  --jq '.token' > reg-token-org

# 2. Зарегистрировать в организации
cd /opt/actions-runner
TOKEN=$(cat reg-token-org)
./config.sh --url https://github.com/{org} \
  --token "$TOKEN" \
  --name "runner-org-01" \
  --labels "self-hosted,linux,x64" \
  --runnergroup "linux-pool" \
  --ephemeral \
  --unattended

sudo ./svc.sh install
sudo ./svc.sh start

# 3. Проверить через API
gh api /orgs/{org}/actions/runners --jq '.runner_groups[] | .name'
```

**Важно**: раннер на уровне организации доступен во всех репозиториях org (или в selected). Используйте `--runnergroup` для ограничения доступа.

### Сценарий 3: Runner Group с ограниченным доступом

```bash
# Создать runner group (org-level)
gh api -X POST /orgs/{org}/actions/runner-groups \
  -f name="production-pool" \
  -f visibility="selected" \
  -f "selected_repository_ids[]=12345678" \
  -f "runners[]=[runner-org-01]"

# Добавить раннер в группу
gh api -X PUT /orgs/{org}/actions/runner-groups/99/runners \
  -f "runner_ids[]=[12345]"

# Обновить группу: разрешить только определённые репозитории
gh api -X PUT /orgs/{org}/action/runner-groups/99/repositories \
  -f "selected_repository_ids[]=[12345678, 87654321]"
```

### Сценарий 4: Ephemeral раннер с auto-re-registration

Для автоматического перерегистрации ephemeral раннера после каждого job:

```bash
# 1. Создать systemd сервис с Restart=always
sudo tee /etc/systemd/system/actions-runner-restart.service <<'EOF'
[Unit]
Description=GitHub Actions Ephemeral Runner Auto-Relaunch
After=network.target

[Service]
Type=simple
User=runner
WorkingDirectory=/opt/actions-runner
ExecStart=/opt/actions-runner/runsvc.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now actions-runner-restart.service
```

### Сценарий 5: JIT (Just-In-Time) Registration для GHE

Для GitHub Enterprise Server используется JIT — токен, живущий ровно до первого job:

```bash
# 1. Получить JIT-конфиг (GHE only)
gh api -X POST /repos/{owner}/{repo}/actions/runners/generate-jitconfig \
  -f name="jit-runner-01" \
  -f "labels[]=['self-hosted','linux']" \
  --jq '.runner.jit_client_bootstrap_config_url'

# 2. Зарегистрировать раннер с JIT
./config.sh --url https://github.example.com/{owner}/{repo} \
  --token <JIT_TOKEN> \
  --ephemeral \
  --unattended

./run.sh --startdelay 5
```

## Команды и API-операции

### Управление через CLI и API

| Операция | Команда |
|---|---|
| Список раннеров (repo) | `gh api /repos/{owner}/{repo}/actions/runners --jq '.[].name'` |
| Список раннеров (org) | `gh api /orgs/{org}/actions/runners --jq '.[].name'` |
| Список runner groups | `gh api /orgs/{org}/actions/runner-groups --jq '.runner_groups[].name'` |
| Токен регистрации (repo) | `gh api -X POST /repos/{owner}/{repo}/actions/runners/registration-token --jq '.token'` |
| Токен регистрации (org) | `gh api -X POST /orgs/{org}/actions/runners/registration-token --jq '.token'` |
| Удалить раннер | `gh api -X POST /repos/{owner}/{repo}/actions/runners/{runner_id}/remove` |
| Обновить labels | `gh api -X PATCH /repos/{owner}/{repo}/actions/runners/{runner_id} -f 'labels[]=new-label'` |

### Локальные команды раннера

| Команда | Описание |
|---|---|
| `./config.sh` | Регистрация раннера |
| `./run.sh` | Запуск раннера в foreground |
| `./runsvc.sh` | Запуск с auto-restart |
| `./svc.sh install` | Установка systemd-сервиса |
| `./svc.sh start` | Старт сервиса |
| `./svc.sh stop` | Остановка сервиса |
| `./svc.sh status` | Статус сервиса |
| `./remove.sh` | Удаление раннера из GitHub |

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `runner: offline` в UI | Сервис не запущен или нет outbound 443 | `sudo systemctl status actions.runner...`; проверить firewall egress |
| `Registration token expired` | Токен живёт 1 час | Получить новый и перерегистрировать |
| `Job failed: runner not found` | Метка `runs-on` не совпадает с раннером | Добавить `--labels` при конфигурации или обновить метки через API |
| `Job timeout` после запуска | Runner app устарел (старше 30 дней) | `curl -sL https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64.tar.gz \| tar -xz -C .` + restart |
| `disk full` на раннере | /tmp/runner-work нарастает | `./run.sh remove` (удаляет work-dir); настройте cleanup; используйте `--work /ephemeral` |
| `permission denied` на docker | Пользователь не в группе docker | `sudo usermod -aG docker runner`; перелогиниться |
| Ephemeral runner не перерегистрируется | systemd service `Restart=always` не настроен | Настроить auto-restart (Сценарий 4) |
| `403 Forbidden` при регистрации | Токен не имеет прав `actions: write` | Использовать fine-grained PAT или App с нужными правами |

## Лучшие практики

1. **Эфемерные раннеры в production**: всегда `--ephemeral` или [ARC](./actions_runner_controller.md). Stateful self-hosted раннеры создают security-риски (накопление состояния, компрометация кода).
2. **Отдельный service account**: создавайте Linux-пользователя `runner` с минимальными правами (не root); вход только через SSH с ключом.
3. **Обновление runner app**: следите за обновлениями; старые версии (старше 30 дней) принудительно отключаются GitHub. Используйте `--disableupdate` и обновляйте вручную, если нужен контроль.
4. **Runner groups**: используйте для IAM-изоляции (production vs dev), ограничьте доступ по репозиториям через `visibility=selected`.
5. **Network egress**: открывайте только HTTPS (443) на `*.github.com`, `objects.githubusercontent.com`, `pipelinesghubeat.s3.amazonaws.com`; блокируйте весь ingress.
6. **Disk cleanup**: `/tmp/runner-work` растёт — добавляйте cron `tmpreaper` или используйте `--work` на отдельном volume с ttl-очисткой.
7. **Для Windows**: используйте `run.cmd` и `svc-noop.sh` (Windows service); лучше — containerd+runc для изоляции.
8. **Мониторинг**: используйте `systemd` логи, GitHub audit log для `actions.runner` событий, настройте metrics endpoint в ARC.

## Дополнительная информация

- **[Actions Runner Controller](./actions_runner_controller.md)** — эфемерные раннеры в Kubernetes (современный подход для production).
- **[Ключевые концепции](./Core_Concept.md)** — архитектура GitHub Actions, изоляция и эфемерность, модель правил.
- **[Ограничения среды выполнения](./Environment_Limitations.md)** — спецификации GitHub-hosted vs self-hosted, лимиты.
- **[GitHub Apps](./github_apps.md)** — аутентификация App для авто-регистрации и push в protected ветки.
- **[GitHub Packages и GHCR](./github_packages_ghcr.md)** — pull-образов из ghcr.io в self-hosted раннеры.
- **Официальная документация**: [Self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners), [Configuring a self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners).
