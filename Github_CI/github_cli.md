# GitHub CLI (gh): Управление GitHub из терминала

**Актуально для:** GitHub CLI (gh) 2.102.x

GitHub CLI (`gh`) — официальный инструмент командной строки для взаимодействия с GitHub.com и локальными серверами GitHub Enterprise Server (GHES). Утилита предоставляет прямой доступ к операциям платформы (Pull Requests, Issues, Releases, Actions, Secrets, Variables, Actions Cache, Attestations) без необходимости использования веб-интерфейса, а также выступает в роли клиента к REST API (v3) и GraphQL API (v4). В инфраструктурной практике DevOps, SRE и системного администрирования `gh` применяется для автоматизации пайплайнов, headless-аутентификации на раннерах, аудита состояния воркфлоу, администрирования репозиториев и проверки цепочки поставок ПО.

## Определения

- **GitHub CLI (`gh`)**: Консольный клиент от GitHub, скомпилированный на Go. Предоставляет высокоуровневые интерфейсы к объектам платформы и низкоуровневый доступ к API через подкоманду `gh api`.
- **Authentication Token**: Токен доступа (Fine-grained Personal Access Token, Classic PAT или GitHub App Installation Token), применяемый для авторизации запросов к API.
- **`gh api`**: Универсальная подкоманда для отправки произвольных REST и GraphQL запросов к GitHub API с поддержкой встроенной пагинации, кэширования заголовков и обработки статус-кодов.
- **Extension**: Модуль расширения базовой функциональности `gh`, оформленный как отдельный Git-репозиторий с исполняемым файлом `gh-<name>` и запускаемый CLI как дочерний процесс.
- **Alias**: Пользовательский псевдоним подкоманды или цепочки флагов, сохраняемый в конфигурации CLI для сокращения стандартных операций.
- **GitHub Enterprise Server (GHES)**: On-premises инсталляция платформы GitHub, доступ к которой настраивается через указание хоста (`--hostname`) или переменной окружения `GH_HOST`.
- **`gh repo read-file` / `gh repo read-dir`**: Встроенные подкоманды для удалённого чтения содержимого файлов и листинга директорий в репозитории без выполнения операции `git clone`.
- **Git Worktree Support**: Встроенная поддержка механизма `git worktree` в командах `gh pr checkout --worktree` и `gh issue develop --worktree`, позволяющая изолировать проверку ветки в отдельном каталоге без переключения текущего рабочего дерева.
- **Attestation (`gh attestation`)**: Криптографически подписанное свидетельство о сборке и происхождении артефакта (SLSA provenance на базе Sigstore), проверяемое утилитой `gh` перед деплоем или установкой пакета.
- **Actions Cache (`gh cache`)**: Механизм управления сохранёнными кэшами GitHub Actions на уровне репозитория для мониторинга квот и очистки устаревших данных.

## Архитектура и принципы работы

### Движок CLI и абстракция над API

GitHub CLI выполняет роль интеллектуального интерфейса между пользователем/скриптом и HTTP API GitHub:

```text
+--------------------------------------------------------------------------+
|                     Пользовательский ввод / CI Скрипт                    |
+--------------------------------------------------------------------------+
                                     |
               +---------------------+---------------------+
               |                                           |
               v                                           v
    Высокоуровневые подкоманды                 Низкоуровневый клиент
    (gh pr, gh run, gh secret, ...)                  (gh api)
               |                                           |
               +---------------------+---------------------+
                                     |
                                     v
                       Движок авторизации и контекста
              (Разрешение токена: Env -> Keyring -> hosts.yml)
                                     |
                                     v
                       HTTP Transport / TLS Клиент
                  (Поддержка GHES, прокси, CA-сертификатов)
                                     |
               +---------------------+---------------------+
               |                                           |
               v                                           v
     GitHub REST API (v3)                        GitHub GraphQL API (v4)
   (https://api.github.com или                (https://api.github.com/graphql
    https://ghes.corp/api/v3)                  или https://ghes.corp/api/graphql)
```

При выполнении высокоуровневых команд (`gh pr create`, `gh run watch`, `gh release upload`) утилита транслирует аргументы в соответствующие REST или GraphQL вызовы:
1. GraphQL применяется по умолчанию там, где требуется выборка комплексных связанных данных (детали PR со статусами проверок, комментариями и рецензентами) за один сетевой запрос, что минимизирует расход лимитов API (Rate Limits).
2. REST API используется для бинарных загрузок, потоковой передачи логов и стандартных операций над ресурсами.
3. Команды автоматически отслеживают заголовки ответа `X-RateLimit-Remaining` и `Retry-After`, выводя понятные предупреждения при исчерпании квот.

### Модель хранения учетных данных и порядок их разрешения

При выполнении любого сетевого запроса CLI ищет токен авторизации по строгой иерархии приоритетов:

1. **`GH_TOKEN`**: Переменная окружения наивысшего приоритета. Если задана, CLI использует её значение и полностью игнорирует сохранённые файлы конфигурации.
2. **`GITHUB_TOKEN`**: Вторичная переменная окружения (стандартно экспортируемая внутри сред GitHub Actions runner).
3. **`GH_ENTERPRISE_TOKEN`**: Специальная переменная окружения для обращений к хостам GitHub Enterprise Server.
4. **Системный менеджер паролей (OS Keyring)**: На Linux — Secret Service API (`libsecret`), на macOS — Keychain, на Windows — Credential Manager.
5. **Файл конфигурации хостов (`~/.config/gh/hosts.yml`)**: Применяется, если системный менеджер паролей недоступен или отключен в настройках.

### Структура каталогов и конфигурационные файлы

Все параметры работы CLI сохраняются в пользовательском профиле:

| Путь к файлу / каталогу | Назначение |
|---|---|
| `~/.config/gh/config.yml` | Глобальные настройки: редактор (`editor`), протокол Git (`git_protocol`), пейджер (`pager`), поведение подсказок (`prompt`). |
| `~/.config/gh/hosts.yml` | Профили авторизации: сопоставление хостов (`github.com`, домены GHES), логинов, токенов и протоколов передачи. |
| `~/.config/gh/aliases.yml` | Зарегистрированные пользовательские псевдонимы (aliases). |
| `~/.local/share/gh/extensions/` | Каталог установленных расширений (`GH_EXTENSION_DIR`). |

Пример содержимого `~/.config/gh/hosts.yml`:

```yaml
github.com:
    user: devops-lead
    oauth_token: ghp_xxxxxxxxxxxxxxxxxxxx
    git_protocol: ssh
ghes.corp.local:
    user: sre-admin
    oauth_token: ghp_yyyyyyyyyyyyyyyyyyyy
    git_protocol: https
```

### Модель неинтерактивного исполнения (Headless Automation)

В автоматизированных средах (cron, bash-скрипты развертывания, systemd unit, CI/CD раннеры) интерактивные запросы ввода приводят к зависанию процесса. Для обеспечения детерминированного headless-исполнения:
- Переменная `GH_PROMPT_DISABLED=1` гарантирует немедленное завершение с ошибкой вместо попытки интерактивного запроса в TTY.
- Флаг `-R <owner>/<repo>` или переменная `GH_REPO` исключает необходимость нахождения процесса внутри клонированного репозитория Git.
- Флаг `--hostname` или переменная `GH_HOST` явно адресует запросы на нужный сервер GHES.

## Практические сценарии

### Сценарий 1: Установка и неинтерактивная настройка в Linux

Установка пакета и настройка авторизации на сервере управления без использования веб-браузера.

**Предварительные требования**:
- Дистрибутив Linux (Debian/Ubuntu, RHEL/Rocky, Alpine) с правами суперпользователя.
- Сгенерированный Fine-grained PAT или Classic PAT с правами `repo`, `read:org`.

```bash
# Установка в Debian / Ubuntu
sudo mkdir -p -m 755 /etc/apt/keyrings
wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install -y gh

# Проверка версии
gh --version
# → gh version 2.102.0 (2026-09-30)

# Неинтерактивная авторизация через токен из переменной окружения
export GH_TOKEN="ghp_v4l1dt0k3nEx4mpl3Str1ng000000000000"
echo "$GH_TOKEN" | gh auth login --with-token

# Настройка git credential helper для автоматической авторизации git через gh
gh auth setup-git

# Проверка статуса авторизации
gh auth status
# → github.com
# →   ✓ Logged in to github.com account devops-bot (hosts.yml)
# →   - Active account: true
# →   - Git operations protocol: https
# →   - Token: ghp_************************************
# →   - Token scopes: 'repo', 'read:org'
```

- **Валидация**: Команда `gh auth status` возвращает код `0` и подтверждает статус `Logged in to github.com account <username>`.

### Сценарий 2: Интеграция с локальным GitHub Enterprise Server (GHES) и корпоративным CA

Подключение системного администратора к внутреннему корпоративному серверу GHES, использующему приватный корневой центр сертификации.

**Предварительные требования**:
- Доступность инсталляции GHES по адресу `https://ghes.corp.local`.
- Файл корневого сертификата компании `/etc/ssl/certs/corp-ca.pem`.
- PAT для пользователя на сервере GHES.

```bash
# Авторизация на конкретном сервере GHES с передачей токена через stdin
echo "$GHES_TOKEN" | gh auth login --hostname ghes.corp.local --with-token

# Передача пути к корпоративному CA-сертификату для корректной валидации TLS
export SSL_CERT_FILE=/etc/ssl/certs/corp-ca.pem

# Проверка соединения и метаданных инсталляции GHES через REST API
gh api --hostname ghes.corp.local /api/v3/meta --jq '{installed_version: .installed_version, ver: .ver}'
# → {
# →   "installed_version": "3.16.2",
# →   "ver": "3.16.2"
# → }

# Настройка хоста по умолчанию для текущей сессии
export GH_HOST="ghes.corp.local"

# Список репозиториев на сервере GHES
gh repo list internal-infra --limit 2
# → internal-infra/ansible-playbooks  Private  2026-10-01T08:12:00Z
# → internal-infra/terraform-modules  Private  2026-09-28T14:22:15Z
```

- **Валидация**: Запрос `gh api --hostname ghes.corp.local /api/v3/meta` возвращает JSON с ключом `installed_version`, подтверждая успешное прохождение TLS-хэндшейка и авторизации.

### Сценарий 3: Автоматизация секретов и переменных окружения

Управление переменными и зашифрованными секретами CI/CD без использования веб-интерфейса и без оставления паролей в командной строке.

**Предварительные требования**:
- Права администратора или право записи в репозиторий `org/backend-service`.
- Локальный конфигурационный файл с переменными окружения `.env.secrets`.

```bash
# Создание репозиторного секрета из переменной окружения
export DB_PASSWORD="SuperSecretPassword123!"
echo "$DB_PASSWORD" | gh secret set DB_PASSWORD -R org/backend-service

# Установка секрета для конкретного окружения (Environment)
echo "prod-db-token-xyz" | gh secret set DB_AUTH_TOKEN \
  --repo org/backend-service \
  --env production

# Пакетная загрузка секретов из файла key=value
cat << 'EOF' > /tmp/deploy.secrets
REGISTRY_USER=ci-builder
REGISTRY_PASSWORD=TokenSecretHashValue999
EOF

gh secret set -f /tmp/deploy.secrets -R org/backend-service
rm -f /tmp/deploy.secrets
# → ✓ Set secrets for org/backend-service

# Установка незашифрованной переменной окружения Actions (Variables)
gh variable set LOG_LEVEL --body "debug" -R org/backend-service --env staging
# → ✓ Created variable LOG_LEVEL for org/backend-service

# Просмотр списка настроенных секретов репозитория
gh secret list -R org/backend-service
# → NAME               UPDATED
# → DB_PASSWORD        2026-10-11T12:00:00Z
# → REGISTRY_PASSWORD  2026-10-11T12:00:02Z
# → REGISTRY_USER      2026-10-11T12:00:02Z

# Просмотр переменных окружения
gh variable list -R org/backend-service --env staging
# → NAME       VALUE   UPDATED
# → LOG_LEVEL  debug   2026-10-11T12:01:10Z
```

- **Валидация**: Вызовы `gh secret list` и `gh variable list` отображают добавленные ключи без вывода их закрытых значений.

### Сценарий 4: Диагностика, управление и мониторинг CI/CD пайплайнов (SRE Runbook)

Оперативное реагирование на сбои пайплайнов, анализ логов упавших шагов и неинтерактивный перезапуск.

**Предварительные требования**:
- Доступ к репозиторию `org/backend-service` с настроенными GitHub Actions.

```bash
# Получение списка последних 5 прогонов с фильтром по упавшим (failure)
gh run list -R org/backend-service --status failure --limit 3
# → STATUS  TITLE                WORKFLOW  BRANCH  EVENT  ID          ELAPSED  AGE
# → ✗       fix: payment engine  CI        main    push   1122334455  4m12s    15m
# → ✗       feat: add cache      CI        dev     push   1122334410  2m10s    1h
# → ✗       chore: deps bump     Nightly   main    sched  1122333890  1m05s    6h

# Просмотр логов только упавших шагов (failed jobs) без выгрузки полного архива
gh run view 1122334455 -R org/backend-service --log-failed
# → CI / test (job 3344556677):
# → Error: Process completed with exit code 1.
# → FAIL tests/unit/payment_test.py::test_card_charge

# Перезапуск исключительно упавших задач прогона
gh run rerun 1122334455 -R org/backend-service --failed-jobs
# → ✓ Requested re-run of failed jobs in run 1122334455

# Мониторинг прогона в реальном времени с кодом возврата пайплайна (--exit-status)
# Флаг --exit-status вернёт ненулевой код (код 1), если воркфлоу завершится ошибкой
gh run watch 1122334455 -R org/backend-service --exit-status
# → ✓ main · CI · 1122334455: Succeeded 2s ago  (job test ✓ 1m30s)
echo "Статус выполнения: $?"
# → Статус выполнения: 0

# Аварийная отмена зависшего или дублирующегося прогона
gh run cancel 1122334410 -R org/backend-service
# → ✓ Request to cancel run 1122334410 was submitted
```

- **Валидация**: `echo $?` после `gh run watch --exit-status` возвращает `0` при успешном прогоне и `1` при падении, что позволяет использовать команду в bash-скриптах деплоя: `gh run watch "$RUN_ID" --exit-status || exit 1`.

### Сценарий 5: Публикация релизов и проверка цепочки поставок (Supply Chain Attestation)

Сборка, публикация бинарного релиза с контрольными суммами и криптографическая проверка происхождения артефакта через Sigstore attestations.

**Предварительные требования**:
- Собранный дистрибутив `dist/app-v1.5.0.tar.gz`.
- Сгенерированный файл контрольных сумм `dist/checksums.sha256`.

```bash
# Генерация файла контрольных сумм SHA-256
cd dist
sha256sum app-v1.5.0.tar.gz > checksums.sha256
cd ..

# Создание релиза с автоматической генерацией Release Notes из коммитов и PR
gh release create "v1.5.0" \
  -R org/backend-service \
  --title "Release v1.5.0" \
  --generate-notes \
  dist/app-v1.5.0.tar.gz dist/checksums.sha256
# → https://github.com/org/backend-service/releases/tag/v1.5.0

# Скачивание ассета на целевом сервере для установки
gh release download "v1.5.0" \
  -R org/backend-service \
  -p "app-v1.5.0.tar.gz" \
  -p "checksums.sha256" \
  -D /tmp/deploy
# → Downloaded app-v1.5.0.tar.gz
# → Downloaded checksums.sha256

# Валидация контрольной суммы
cd /tmp/deploy
sha256sum -c checksums.sha256
# → app-v1.5.0.tar.gz: OK

# Проверка криптографической аттестации артефакта (SLSA build provenance)
gh attestation verify /tmp/deploy/app-v1.5.0.tar.gz \
  --owner org
# → ✓ Loaded digest sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 for app-v1.5.0.tar.gz
# → ✓ Initialized verification material from public Good Health Ledger
# → ✓ The attestation was signed by repository org/backend-service on commit 8a1f4b3
```

- **Валидация**: Вывод `gh attestation verify` подтверждает подлинность сборщика и совпадение хеша артефакта с записью в реестре подписей.

### Сценарий 6: Управление Pull Requests и изолированные Git Worktrees

Рецензирование и тестирование изменений PR без переключения веток в текущем репозитории разработчика или администратора.

**Предварительные требования**:
- Git версии 2.38+ с поддержкой `git worktree`.
- Локальный клон репозитория.

```bash
# Неинтерактивное создание PR из текущей ветки в main
gh pr create \
  --title "fix(db): increase connection pool timeout" \
  --body "Resolves SRE-1042 connection starvation under high load." \
  --reviewer "org/sre-team" \
  --label "bug,database"
# → Creating pull request for fix/db-timeout into main in org/backend-service
# → https://github.com/org/backend-service/pull/154

# Просмотр результатов CI-проверок для созданного PR
gh pr checks 154
# → ✓ test (unit)         passed  2m10s
# → ✓ lint (flake8)       passed  45s
# → ✓ security (codeql)   passed  3m15s

# Выкатка PR в отдельное git worktree без затрагивания текущей рабочей копии
gh pr checkout 154 --worktree /tmp/review-pr-154
# → Preparing worktree (new branch 'fix/db-timeout')
# → HEAD is now at 8b43f11 fix(db): increase connection pool timeout

# Проверка файлов в изолированном каталоге
ls -la /tmp/review-pr-154/config/database.yml
# → -rw-r--r-- 1 devops devops 1042 Oct 11 12:15 /tmp/review-pr-154/config/database.yml

# Завершение проверки и удаление временного worktree
git worktree remove /tmp/review-pr-154
# → Removed worktree /tmp/review-pr-154

# Слияние PR методом squash с удалением исходной ветки
gh pr merge 154 --squash --delete-branch --subject "fix(db): increase connection pool timeout (#154)"
# → ✓ Squashed and merged pull request #154
# → ✓ Deleted branch fix/db-timeout
```

- **Валидация**: `gh pr view 154 --json state --jq .state` возвращает `MERGED`.

### Сценарий 7: Инспекция файлов и каталогов удаленного репозитория без клонирования

Чтение конфигурационных файлов, манифестов или скриптов из удалённого репозитория на сервере, где не требуется клонировать весь репозиторий.

**Предварительные требования**:
- `gh` версии 2.95+.
- Права на чтение репозитория `org/infra-configs`.

```bash
# Чтение структуры каталога на ветке main
gh repo read-dir systemd/ -R org/infra-configs --ref main
# → .
# → ├── node-exporter.service (642 B)
# → ├── prometheus.service    (814 B)
# → └── vector.service        (920 B)

# Чтение содержимого файла конфигурации непосредственно в stdout
gh repo read-file systemd/vector.service -R org/infra-configs --ref main
# → [Unit]
# → Description=Vector Log Agent
# → After=network.target
# →
# → [Service]
# → ExecStart=/usr/bin/vector --config /etc/vector/vector.yaml
# → Restart=always
# →
# → [Install]
# → WantedBy=multi-user.target

# Выгрузка файла в локальную файловую систему (--output)
gh repo read-file systemd/vector.service -R org/infra-configs --ref v2.4.0 --output /etc/systemd/system/vector.service
# → Wrote 920 bytes to /etc/systemd/system/vector.service
```

- **Валидация**: Проверка целостности файла `head -n 2 /etc/systemd/system/vector.service` показывает корректный заголовок `[Unit]`.

### Сценарий 8: Прямые REST и GraphQL API-вызовы через `gh api`

Извлечение инфраструктурных данных, информации о раннерах и управление вебхуками через прямой HTTP-мост CLI с пагинацией и фильтрацией.

**Предварительные требования**:
- Токен с правами `admin:org` или `repo`.

```bash
# REST: получение списка активных self-hosted раннеров организации с пагинацией
gh api --paginate /orgs/my-org/actions/runners \
  --jq '.runners[] | {id: .id, name: .name, os: .os, status: .status, busy: .busy}'
# → {
# →   "busy": false,
# →   "id": 142,
# →   "name": "srv-runner-01",
# →   "os": "Linux",
# →   "status": "online"
# → }

# REST: отправка тестового ping на существующий webhook
gh api -X POST /repos/org/backend-service/hooks/98765432/pings
# → HTTP/2.0 204 No Content

# GraphQL: запрос последних 2 упавших воркфлоу с деталями шагов
gh api graphql -f query='
query {
  repository(owner: "org", name: "backend-service") {
    checkRuns(last: 2, filterBy: {checkConclusion: FAILURE}) {
      nodes {
        name
        status
        conclusion
        title
      }
    }
  }
}' --jq '.data.repository.checkRuns.nodes[]'
# → {
# →   "conclusion": "FAILURE",
# →   "name": "test-matrix (3.11)",
# →   "status": "COMPLETED",
# →   "title": "Tests failed on Python 3.11"
# → }
```

- **Валидация**: Запрос возвращает валидный структурированный JSON без HTTP-ошибок (статусы 200/204).

### Сценарий 9: Управление кэшем Actions и дисковым пространством

Аудит и очистка дискового кэша GitHub Actions на уровне репозитория для предотвращения превышения квоты хранения (10 ГБ на репозиторий).

**Предварительные требования**:
- Права записи в репозиторий `org/backend-service`.

```bash
# Вывод списка сохранённых ключей кэша с размером в МБ
gh cache list -R org/backend-service --limit 10
# → ID       KEY                                   SIZE (MB)  CREATED AT
# → 8899001  Linux-poetry-3.11-hash-abc12345       342.15     2026-10-10T14:00:00Z
# → 8899002  Linux-npm-cache-hash-def67890         128.40     2026-10-10T14:15:00Z
# → 8899003  Linux-go-build-hash-ghi99999          850.10     2026-10-09T08:30:00Z

# Удаление устаревшего кэша по конкретному ключу
gh cache delete "Linux-go-build-hash-ghi99999" -R org/backend-service
# → ✓ Deleted cache key Linux-go-build-hash-ghi99999

# Полная очистка всего кэша репозитория (например, при отравлении кэша зависимостей)
gh cache delete --all -R org/backend-service
# → ✓ Deleted 2 caches
```

- **Валидация**: Повторный вызов `gh cache list -R org/backend-service` возвращает пустой список (`No caches found`).

### Сценарий 10: Пользовательские псевдонимы (Aliases) для автоматизации рутины DevOps

Создание постоянных сокращений и макросов команд CLI для локальной консоли инженера.

```bash
# Создание alias для быстрого создания PR с немедленным заполнением и назначением на себя
gh alias set quick-pr 'pr create --fill --assignee "@me"'

# Проверка вызова alias
gh quick-pr
# → Creating pull request for feature/cache into main...

# Создание параметризованного alias для просмотра упавших задач воркфлоу
gh alias set failed-run 'run view "$1" --log-failed'

# Вызов с параметром run ID
gh failed-run 1122334455
# → Выводит лог падения задачи

# Просмотр зарегистрированных aliases
gh alias list
# → failed-run: run view "$1" --log-failed
# → quick-pr:   pr create --fill --assignee "@me"

# Удаление alias
gh alias delete quick-pr
# → ✓ Deleted alias quick-pr
```

- **Валидация**: `gh alias list` выводит актуальный перечень сохранённых псевдонимов из файла `~/.config/gh/aliases.yml`.

## Команды и справочник

### Основные подкоманды

| Подкоманда | Назначение |
|---|---|
| `gh auth login` / `logout` | Интерактивная или headless-авторизация в GitHub.com или GHES. |
| `gh auth status` | Проверка токенов, активных учетных записей и доступных областей (scopes). |
| `gh auth setup-git` | Интеграция `gh` в качестве git credential helper в `~/.gitconfig`. |
| `gh repo` | Управление репозиториями: `clone`, `create`, `list`, `view`, `read-file`, `read-dir`. |
| `gh pr` | Управление Pull Requests: `create`, `list`, `view`, `diff`, `checks`, `merge`, `checkout`. |
| `gh issue` | Управление Issues: `create`, `list`, `view`, `close`, `comment`, `develop`. |
| `gh run` | Управление прогонами Actions: `list`, `view`, `watch`, `rerun`, `cancel`, `download`. |
| `gh workflow` | Управление файлами workflow: `list`, `view`, `enable`, `disable`, `run`. |
| `gh release` | Управление релизами: `create`, `list`, `view`, `download`, `upload`, `delete`. |
| `gh secret` | Управление зашифрованными секретами: `list`, `set`, `remove`. |
| `gh variable` | Управление переменными окружения Actions: `list`, `set`, `get`, `delete`. |
| `gh cache` | Управление кэшем Actions: `list`, `delete`. |
| `gh attestation` | Криптографическая проверка происхождения артефактов: `verify`, `download`. |
| `gh api` | Прямые сетевые запросы к REST и GraphQL API с пагинацией и JSON-фильтрацией. |
| `gh alias` | Управление пользовательскими псевдонимами команд: `set`, `list`, `delete`. |
| `gh extension` | Управление модулями расширения: `install`, `list`, `upgrade`, `remove`. |

### Флаги форматирования и контекста

| Флаг | Контекст | Описание |
|---|---|---|
| `-R, --repo <[HOST/]OWNER/REPO>` | Глобальный | Явный выбор репозитория вне зависимости от текущего каталога Git. |
| `--hostname <HOST>` | `gh auth`, `gh api` | Адресация конкретного сервера GitHub Enterprise Server. |
| `--json <fields>` | Большинство команд | Вывод структурированного JSON вместо форматированной таблицы (например, `--json number,title,state`). |
| `-q, --jq <expression>` | При `--json` или `gh api` | Фильтрация вывода встроенным синтаксисом jq (например, `-q '.[].name'`). |
| `-t, --template <string>` | Большинство команд | Форматирование вывода через шаблоны Go template (например, `-t '{{range .}}{{.title}}{{"\n"}}{{end}}'`). |
| `--paginate` | `gh api` | Автоматический последовательный обход всех страниц выдачи по заголовкам `Link`. |
| `--exit-status` | `gh run watch` | Возврат ненулевого кода ошибки при завершении прогона в статусе `failure`. |

### Переменные окружения

| Переменная | Назначение |
|---|---|
| `GH_TOKEN` / `GITHUB_TOKEN` | Токен авторизации (переопределяет системные хранилища и файлы конфигурации). |
| `GH_ENTERPRISE_TOKEN` | Токен авторизации для запросов к хостам GHES. |
| `GH_HOST` | Хост по умолчанию (например, `ghes.corp.local`). |
| `GH_REPO` | Репозиторий по умолчанию для команд, запущенных вне дерева Git. |
| `GH_CONFIG_DIR` | Каталог файлов конфигурации (по умолчанию `~/.config/gh`). |
| `GH_PROMPT_DISABLED` | Запрет интерактивных запросов ввода (`1` — немедленная ошибка при отсутствии параметров). |
| `GH_DEBUG` | Режим отладки сетевых вызовов (`api` выводит полные HTTP заголовки и тело ответов). |
| `SSL_CERT_FILE` / `SSL_CERT_DIR` | Путь к корпоративному CA-сертификату для TLS-проверок. |
| `NO_COLOR` | Отключение ANSI-цветов в выводе для чистоты логов автоматизации. |

### Коды возврата (Exit Codes)

| Код | Значение | Диагностика / Решение |
|---|---|---|
| `0` | Успешное выполнение команды | Стандартный код успеха. |
| `1` | Общая ошибка выполнения или сбой процесса | Ошибка валидации API, сбой воркфлоу при `--exit-status`, ошибка аргументов. |
| `2` | Ошибка парсинга командной строки | Неверный синтаксис флагов или неизвестная подкоманда. |
| `4` | Ошибка авторизации (Authentication required) | Токен отсутствует, истёк или не имеет достаточных прав доступа. |

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
|---|---|---|---|
| Процесс в CI/CD зависает без вывода логов | Команда ожидает интерактивного ввода подтверждения в TTY (например, `gh pr create` без всех флагов) | Проверить процесс: висит в состоянии ожидания `stdin` | Экспортировать `export GH_PROMPT_DISABLED=1` и передавать все обязательные флаги (`--title`, `--body`, `--fill`) явно. |
| `HTTP 401: Bad credentials` | Истёк срок действия токена или токен отозван | `gh auth status` | Обновить токен: перевыпустить PAT и обновить значение переменной `GH_TOKEN` или выполнить `echo "$TOKEN" \| gh auth login --with-token`. |
| `HTTP 403: Resource not accessible by integration` | Токену не хватает прав (scopes) на выполнение операции или в workflow не заданы `permissions` | Проверить scopes через `gh auth status` или блок `permissions:` в файле YAML | Для PAT: добавить необходимые разрешения (`repo`, `actions:write`, `attestations:write`). В Actions: явно объявить требуемый scope в секции `permissions`. |
| `HTTP 403: API rate limit exceeded` | Превышен лимит запросов к API (5000 req/h для PAT, 60 req/h для unauthenticated) | `gh api rate_limit` | Использовать аутентифицированные запросы; переписать массовые REST-вызовы на GraphQL; настроить экспоненциальную задержку (backoff). |
| `x509: certificate signed by unknown authority` | Сервер GHES использует самоподписанный сертификат или внутренний корпоративный CA | Запустить команду с отладкой: `GH_DEBUG=api gh api /api/v3/meta` | Указать доверенный сертификат: `export SSL_CERT_FILE=/etc/ssl/certs/corp-ca.pem`. |
| Ошибка Git: `fatal: could not read Username` после настройки `gh auth setup-git` | Устаревший helper или отсутствие доступа к credential helper в headless среде | `git config -l \| grep credential` | Проверить наличие `gh auth setup-git`; в headless скриптах явно передавать токен через URL: `https://x-access-token:${GH_TOKEN}@github.com/org/repo.git`. |
| `fatal: '<path>' already exists` при `gh pr checkout --worktree` | Каталог для worktree уже существует в файловой системе | `git worktree list` | Удалить старое дерево: `git worktree remove <path>` или указать новый путь. |
| `attestation verification failed: signature does not match` | Артефакт был модифицирован после сборки или указан неверный репозиторий сборщика | Вычислить SHA-256 артефакта вручную: `sha256sum <file>` | Убедиться в неизменности файла; проверить параметр `--owner` и точное соответствие ревизии коммита. |

## Лучшие практики

1. **Принцип наименьших привилегий (Least Privilege)**:
   - Откажитесь от Classic PAT с глобальным правом `repo`. Используйте Fine-grained PAT с доступом только к конкретным репозиториям и изолированным операциям (например, только чтение Issues или только запись Releases).
   - В автоматизированных пайплайнах отдавайте предпочтение кратковременным токенам GitHub App (Installation Access Token) с периодом жизни 1 час.

2. **Стандарты неинтерактивного скриптинга в CI/CD**:
   - Всегда объявляйте `GH_PROMPT_DISABLED=1` в начале скриптов автоматизации, чтобы предотвратить зависания при возникновении непредвиденных диалоговых запросов.
   - Никогда не парсите текстовые ASCII-таблицы стандартного вывода `gh` через `awk` или `sed`. Используйте флаги `--json <fields>` в сочетании с встроенным фильтром `--jq` (`-q`).

3. **Отказоустойчивость и обработка ошибок**:
   - При мониторинге пайплайнов всегда указывайте флаг `--exit-status`: `gh run watch "$RUN_ID" --exit-status`. Это гарантирует прерывание вызывающего скрипта при падении задачи.
   - Проверяйте код завершения команд `$?`: код `4` сигнализирует о деградации токена авторизации, требующей ротации секрета, а не повтора сетевого запроса.

4. **Оптимизация квот API**:
   - Для выборки связанных данных используйте `gh api graphql`, объединяющий несколько вызовов к сущностям в единый сетевой пакет.
   - Для массового чтения коллекций в REST API применяйте встроенный флаг `--paginate` вместо ручного цикла по номерам страниц `?page=N`.

5. **Гигиена дискового пространства и кэшей**:
   - На регулярной основе очищайте старые Actions кэши через `gh cache delete`, предотвращая вытеснение актуальных слоев сборки при достижении лимита репозитория.
   - Удаляйте временные рабочие деревья (`git worktree remove`) после завершения локальных проверок PR.

## Дополнительная информация

- **[Управление релизами](./Release_Management.md)** — публикация артефактов, неизменяемые релизы и генерация Attestations в GitHub Actions.
- **[Работа с GitHub API](./github_api.md)** — подробная спецификация REST и GraphQL API, архитектура первичных и вторичных Rate Limits, ETag-кэширование.
- **[Управление секретами в GitHub Actions](./secrets_management.md)** — уровни видимости секретов (Organization, Repository, Environment) и политики маскирования.
- **[Self-hosted раннеры GitHub Actions](./self_hosted_runners.md)** — администрирование собственных раннеров, регистрация через токены и мониторинг состояния.
- **[Правила защиты веток и Rulesets](./rulesets.md)** — управление политиками слияния PR, bypass-списками и защитой веток через API.
- **[Git автоматизация](./Git_Automation.md)** — автоматизация коммитов, тегов и проверок в CI/CD.
- **[Рабочие процессы в Git](../Git/git_workflows.md)** — совместная работа с ветками и слияниями.
- **[Инструменты Git TUI и CLI](../Git/git_tools.md)** — альтернативные утилиты командной строки и визуальные TUI-клиенты.
- **Официальная документация GitHub CLI**: [Руководство по GitHub CLI](https://cli.github.com/manual/), [Справочник подкоманд gh api](https://cli.github.com/manual/gh_api), [Управление расширениями gh extension](https://cli.github.com/manual/gh_extension).
