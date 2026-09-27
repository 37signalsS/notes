# Управление секретами в CI/CD

## Определения

**Управление секретами в CI/CD (Continuous Integration / Continuous Deployment)** — совокупность практик и инструментов для безопасного хранения, доставки, аудита и ротации конфиденциальных данных на всех этапах жизненного цикла разработки.

**Секрет** — любая чувствительная информация (пароли, API-ключи, токены, TLS-сертификаты, SSH-ключи), компрометация которой дает несанкционированный доступ к ресурсам.

**NHI (Non-Human Identities)** — цифровые сущности (пайплайны, микросервисы, оркестраторы), которым требуются права доступа. В 2026 году защита NHI является приоритетной из-за их превалирующего количества над человеческими аккаунтами.

**Secret-Zero (Проблема первого секрета)** — дилемма аутентификации, когда для получения секретов из хранилища приложению изначально требуется какой-то статический идентификатор или пароль.

**OIDC (OpenID Connect) / Workload Identity** — современный стандарт «безсекретной» (secretless) аутентификации, позволяющий CI-системе подтверждать свою идентичность провайдеру идентификации или менеджеру секретов через временные JWT-токены.

**Динамические секреты (Just-in-Time)** — учетные данные, которые создаются по запросу с коротким временем жизни (TTL) и автоматически отзываются после использования.

## Базовые концепции

### Принцип минимальных привилегий (Least Privilege)

Украденный секрет опасен ровно настолько, насколько широки его права доступа. Секреты должны быть гранулированы по ролям и этапам пайплайна:

- **Задача сборки (build):** доступ только к приватным реестрам зависимостей (NPM, PyPI). Продовые ключи здесь запрещены.
- **Задача тестирования (test):** доступ только к тестовым базам данных и мок-сервисам.
- **Задача развертывания (deploy):** единственный этап, которому нужны продовые секреты, строго ограниченные конкретным окружением (`environment`).

### Модели получения секретов

Хранение секретов в переменных окружения CI/CD (даже маскированных) является антипаттерном. См. **[Антипаттерны управления секретами](../../Vault/common_antipatterns.md)** и **[обзор архитектуры HashiCorp Vault](../../Vault/overview.md)** для понимания того, как устроено централизованное хранилище.

1. **Модель Push (Injection):** секреты извлекаются один раз при старте задачи и записываются в `env` или временный файл (`tmpfs`). Высокий риск утечки в логи.
2. **Модель Pull (Just-in-Time):** задача сама запрашивает секреты через API хранилища в момент использования. Секрет живет только в памяти процесса.
3. **Workload Identity (Identity Federation):** CI-задача использует временный OIDC-токен для обмена на временные права доступа. Это «золотой стандарт» 2024–2026 гг.

### Решение Secret-Zero через JWT/OIDC

Современная архитектура исключает статические пароли для доступа к хранилищу:

1. CI-система подписывает для каждой задачи временный **JWT-токен**.
2. Задача отправляет этот токен в менеджер секретов (например, Vault).
3. Провайдер проверяет подпись и **Bound Claims** (соответствие `project_id`, `branch`, `environment`).
4. При совпадении критериев выдаются временные права доступа.

### Разделение хранения для разных окружений

- **Конфигурационные переменные:** флаги, URL, названия окружений хранятся открыто в Git или переменных CI/CD.
- **Секретные переменные:** пароли, токены хранятся исключительно во внешнем менеджере. Доступ жестко ограничен через политики, чтобы пайплайн `dev` физически не мог прочитать секреты `prod`.

### Жизненный цикл секрета (Secret Lifecycle)

Секрет проходит через несколько стадий, и безопасность определяется тем, насколько коротко и контролируемо он существует на каждой из них:

1. **Генерация (Generation):** высокоэнтропийные значения (CSPRNG, `openssl rand`, встроенные генераторы хранилища), без ручного ввода.
2. **Хранение (Storage):** шифрование при хранении (encryption at rest), доступ строго по политике, разделение на окружения.
3. **Доставка (Distribution):** только в память процесса или временный `tmpfs`/файл, поверх TLS; никогда — в `ENV` навсегда или в образ.
4. **Использование (Usage):** минимальное время жизни, маскирование в логах.
5. **Ротация (Rotation):** плановая или по событию (см. ниже).
6. **Отзыв (Revocation):** немедленный отзыв при компрометации.
7. **Уничтожение (Destruction):** безопасное удаление из памяти/диска и из истории Git.
8. **Аудит (Audit):** логирование каждого обращения.

Общий принцип: секрет должен существовать *ровно столько и только там*, где он нужен. Общее описание стратегий управления секретами — в **[обзоре управления секретами](../../Security/Concepts/secrets_management_overview.md)**.

### Модель угроз для секретов (Threat Model)

Понимание того, *где* секреты реально утекают, определяет выбор контрмер. Основные векторы:

| Вектор | Как секрет попадает наружу | Контрмера |
| :--- | :--- | :--- |
| **Переменные окружения** | видны в `ps auxe`, `/proc/<pid>/environ`, дампах при падении, дочерних процессах | JIT/OIDC, инъекция в память, маскирование |
| **Логи CI/build** | печать переменной, трассировки, архивы логов job'а | маскирование, запрет `set -x` для секретных шагов |
| **Слои образа Docker** | `ENV`/`COPY` ключей остаются в истории слоёв даже после `rm` | BuildKit `--secret`, multi-stage без ключей |
| **Кэш CI / shared runners** | секрет попадает в кэш зависимостей или workspace другого джоба | эфемерные раннеры, изолированный кэш |
| **Swap / pagefile / core dump** | секрет из памяти сбрасывается на диск | `swap off`/`encrypted swap`, `ulimit -c 0`, `IPC_LOCK` |
| **Process listing / IPC** | `ps`, `/proc`, shared memory | наименьшие привилегии, read-only rootfs |
| **История Git** | случайный коммит | pre-commit сканирование, push protection, `git filter-repo` |

### Стратегии ротации (Rotation)

- **Плановая (Scheduled):** по календарю (30/90/180 дней) — снижает окно компрометации.
- **По событию (Event-driven / JIT):** при увольнении, подозрении, после инцидента.
- **Динамические секреты:** хранилище (например, Vault Database Secrets Engine) генерирует пароль на время сессии с авто-отзывом по TTL.
- **Бесшовная ротация (Zero-downtime Dual-write):** новый и старый секреты действуют *одновременно* в течение периода переключения; приложение переходит на новый, старый отзывается только после истечения его TTL. Критично для stateful-сервисов (СУБД, очереди).
- **Автоматизация:** ротация через CI schedule / `systemd timer` / `cron` + API хранилища (см. Практические сценарии, Пример 4).

### Аудит и соответствие (Audit & Compliance)

- **Логирование доступа:** каждое чтение секрета фиксируется (аудит CI-системы, системные логи, Vault Audit Devices). Без аудита невозможно расследовать инцидент.
- **Инвентаризация:** что является секретом, где используется, кто владелец, когда ротировался, используется ли он вообще (stale secrets = риск).
- **Соответствие:** PCI DSS (требует ротации и ограничения доступа к ключам), DORA (управление доступом и операционная устойчивость), российские регуляторные требования (152-ФЗ для персональных данных, ФСТЭК/ФСБ для ключей).
- **Регулярный review:** пересмотр политик доступа и вывод из эксплуатации неиспользуемых секретов.

## Практические сценарии

### Инструменты сканирования: Gitleaks и Trufflehog

```bash
# Пример использования Gitleaks локально
gitleaks detect --source . --verbose

# Пример использования Trufflehog для сканирования всей истории Git
docker run --rm -it -v "$PWD:/pwd" trufflesecurity/trufflehog:latest git file:///pwd
```

### Сценарий 1: GitLab + Workload Identity (OIDC)

Исключает использование статических паролей доступа к хранилищу секретов.

```yaml
deploy:
  image: alpine:latest
  id_tokens:
    MY_OIDC_TOKEN:
      aud: https://gitlab.example.com
  script:
    - >
      export $(printf "VAULT_TOKEN=%s"
      $(curl -s -H "Authorization: Bearer $MY_OIDC_TOKEN"
      https://vault.internal.corp/v1/auth/jwt/login
      -d '{"role":"ci-role"}' | jq -r '.auth.client_token'))
    - vault kv get secret/ci/db
```

### Сценарий 2: GitHub Actions + Vault (JWT аутентификация)

```yaml
jobs:
  get-secrets:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - name: Import Secrets from Vault
        uses: hashicorp/vault-action@v3
        with:
          url: https://vault.internal.corp
          role: ci-role
          method: jwt
          secrets: |
            kv/data/production/db password | DB_PASSWORD
```

### Сценарий 3: Self-hosted раннер + локальный Vault

Для максимальной изоляции CI-инфраструктура разворачивается внутри закрытого периметра:

- **Self-hosted Runners:** запуск агентов внутри периметра без выхода в интернет.
- **Network Policies:** исходящий трафик только к внутреннему registry и Vault API.
- **Reverse Proxy:** публикация Vault API через шлюз с фильтрацией по IP-адресам (Bound CIDRs) и проверкой OIDC-токенов.

### Сценарий 4: Автоматизация ротации без простоя (Dual-write, systemd timer)

Для stateful-сервисов (СУБД, брокеры) недопустима ротация «выключить — сменить — включить». Применяется dual-write: старый и новый пароли валидны одновременно, затем старый отзывается по TTL.

**Предусловия:** Vault KV v2 (версионирование) или Database Secrets Engine; права администратора на сервис.

```ini
# /etc/systemd/system/vault-rotate-db.timer
[Timer]
OnCalendar=weekly
Persistent=true
[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/vault-rotate-db.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/rotate_db.sh
```

```bash
#!/usr/bin/env bash
# /usr/local/bin/rotate_db.sh
set -euo pipefail
# 1. Vault выдаёт новый динамический пароль БД
NEW=$(vault read -field=password database/creds/app-role)
# 2. Применяем NEW, оставляя СТАРЫЙ валидным (dual-write)
psql "$ADMIN_DSN" -c "ALTER USER app WITH PASSWORD '$NEW';"
# 3. Перечитываем пул соединений приложения без даунтайма
systemctl reload app
# 4. Старый пароль отзовётся автоматически по TTL движка БД
```

**Validation:** `vault read database/creds/app-role` возвращает новый пароль; приложение продолжает работать; старый недоступен после истечения TTL.

**Troubleshooting:**
- *Приложение не видит новый пароль:* убедитесь, что пул соединений действительно перечитывается (`reload`, webhook или `SIGUSR`); иначе используйте KV v2 и храните обе версии, удаляя старую через `vault kv metadata delete -versions=N kv/ci/db` только после подтверждения.
- *Гонка при параллельной ротации:* ставьте блокировку (`flock`) в скрипте.

### Что делать при утечке секрета

1. **Немедленный отзыв (Revoke):** отозвать скомпрометированный ключ в панели управления провайдера.
2. **Ротация (Rotate):** сгенерировать новые учетные данные.
3. **Очистка истории (Clean):** использовать **BFG Repo-Cleaner** или `git filter-repo` для удаления следов секрета.
4. **Аудит:** проверить логи доступа (Vault Audit Logs, аудит CI-системы) на предмет подозрительной активности в период утечки.

### Секреты на этапе сборки (Build-time Secrets)

Отдельный класс секретов — учетные данные, необходимые именно в процессе сборки CI-пайплайна (не в runtime приложения):

| Тип секрета | Пример | Способ доставки |
| :--- | :--- | :--- |
| **Учетные данные реестра зависимостей** | PyPI token, npm registry login | Переменные CI/CD или Vault через OIDC |
| **Ключи подписи артефактов** | GPG-ключ, Cosign key | Vault Secret Engine или HSM |
| **Учетные данные тестовых сред** | Test DB credentials | Динамические секреты Vault (JIT) |
| **Токены доступа к внутренним сервисам** | Artifactory, Nexus password | Маскированные переменные CI/CD |

**Принципы работы с build-time секретами:**
1. **Изоляция этапов:** Секреты для сборки недоступны на этапе деплоя и наоборот.
2. **Минимальное время жизни:** Секрет должен существовать только в момент выполнения конкретного шага.
3. **Исключение из логов:** Все build-time секреты должны маскироваться в выводе CI-системы.
4. **Запрет передачи между шагами:** Каждый шаг запрашивает свои секреты независимо.

### Базовые практики: маскирование и переменные типа File

- **Masking:** если внешний Vault недоступен, всегда включайте маскирование в GitLab/GitHub.
- **Variables типа `File`:** используйте для многострочных данных (SSH-ключи, сертификаты). GitLab запишет их во временный файл и удалит после завершения задачи.

### Пример 1: Локальный pre-commit с detect-secrets (альтернатива gitleaks)

`detect-secrets` от Yelp строит *бейзлайн* известных секретов и ловит только новые, что снижает ложные срабатывания по сравнению с простым регекс-поиском.

**Предусловия:** `python3` (>=3.8) и `pip`/`pipx`.

**1. Установить и создать бейзлайн:**

```bash
pipx install detect-secrets
detect-secrets scan > .secrets.baseline
```

**2. Подключить pre-commit хук:**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

```bash
pre-commit install
```

**Validation:** при попытке закоммитить файл с новым секретом хук блокирует коммит; `detect-secrets scan` сравнивает результат с бейзлайном.

**Troubleshooting:**
- *Ложное срабатывание:* добавьте исключение в бейзлайн (`detect-secrets addnewsecret <file>:<line>:<col>`) либо инлайн-комментарий `# pragma: allowlist secret`.
- *Бейзлайн неактуален:* после обоснованных изменений обновляйте `detect-secrets scan --update .secrets.baseline` и коммитьте его.

### Пример 2: Настройка Vault со стороны сервера для self-hosted раннера (JWT-auth)

В сценариях выше показано, как CI-задача *получает* секрет через OIDC. Здесь — как SRE/Sysadmin **настроить сам Vault**, чтобы выдавать токены self-hosted раннеру без статического Secret-Zero. Применимо к локальному GitLab/Jenkins внутри периметра.

**Предусловия:** административный доступ к Vault, раннер умеет выпускать OIDC-токен (GitLab `id_tokens`, Jenkins с плагином OIDC).

```bash
# 1. Включить метод аутентификации JWT
vault auth enable jwt

# 2. Политика: только чтение пути kv/data/ci/*
cat > ci-policy.hcl <<'EOF'
path "kv/data/ci/*"    { capabilities = ["read"] }
path "kv/metadata/ci/*" { capabilities = ["list", "read"] }
EOF
vault policy write ci-policy ci-policy.hcl

# 3. Роль, привязанная к claims раннера (project + branch + audience)
vault write auth/jwt/role/ci-role \
  bound_audiences="https://gitlab.internal.corp" \
  bound_claims="project_id=123,ref=main" \
  user_claim="user_email" \
  policies="ci-policy" \
  ttl=15m
```

**Validation:** `vault read auth/jwt/role/ci-role` выводит конфигурацию; CI-джоб успешно обменивает свой JWT на Vault-токен и читает `kv/data/ci/*`.

**Troubleshooting:**
- *403 / permission denied:* проверьте, что `bound_claims` точно совпадают с выпущенным JWT (декодируйте через `jwt.io`); частая ошибка — несовпадение `audience`.
- *Политика не даёт доступ:* убедитесь, что путь в политике (`kv/data/ci/*`) совпадает с запрашиваемым.
- *Токен истёк слишком быстро:* увеличьте `ttl`, либо настройте auto-renew через Vault Agent.

### Пример 3: Jenkins + Vault через AppRole (M2M, self-hosted)

AppRole — классический machine-to-machine метод для self-hosted CI без OIDC. Секрет доступа к хранилищу never лежит в репозитории, а выдаётся через одноразовую обёртку.

**Предусловия:** Jenkins с плагином HashiCorp Vault (или `curl`); Vault с включённым `approle`.

```bash
# На стороне Vault: включить метод и создать роль
vault auth enable approle
vault write auth/approle/role/jenkins \
  token_policies="ci-policy" \
  token_ttl=10m bind_secret_id=true

# RoleID — стабильный идентификатор; SecretID выдаётся через wrapping (одноразовый)
vault read auth/approle/role/jenkins/role-id
vault write -wrap-ttl=60s auth/approle/role/jenkins/secret-id
```

```groovy
// Jenkinsfile (через плагин HashiCorp Vault)
pipeline {
  agent any
  environment { VAULT_ADDR = 'https://vault.internal.corp' }
  stages {
    stage('Get secret') {
      steps {
        withVault([vaultSecrets: [
          [path: 'kv/data/ci/db', secretKey: 'password', envVar: 'DB_PASSWORD']
        ]]) {
          sh 'echo "используем $DB_PASSWORD (маскируется Jenkins)"'
        }
      }
    }
  }
}
```

**Validation:** джоб печатает маскированный пароль; в Vault audit-логе видно чтение под сущностью `jenkins`.

**Troubleshooting:**
- *SecretID истёл:* wrap-токен живёт `wrap-ttl` секунд — перевыпустите; для долгоживущих агентов используйте Vault Agent с `auto-auth`.
- *RoleID неверен:* перепроверьте `vault read auth/approle/role/jenkins/role-id`.
- *Политика не покрывает путь:* добавьте нужный `path` в `ci-policy`.

### Пример 4: Разбор аудит-логов Vault при инциденте (jq)

После подозрения на утечку SRE/Sysadmin должен локализовать, кто и когда читал секрет, используя audit device.

**Предусловия:** включён `file` audit device в JSON-формате; утилита `jq`.

```bash
# Включить аудит (если ещё не включён)
vault audit enable file file_path=/var/log/vault/audit.log

# Найти все обращения к конкретному секрету за окно инцидента
jq -r 'select(.request.path=="kv/data/ci/db") |
       "\(.time) \(.auth.display_name) \(.request.operation)"' \
   /var/log/vault/audit.log

# Сгруппировать по сущности-клиенту: кто сколько раз читал
jq -r '.auth.display_name' /var/log/vault/audit.log | sort | uniq -c
```

**Validation:** вывод содержит метки времени и имена сущностей — это позволяет локализовать инцидент и передать IOC в «Что делать при утечке».

**Troubleshooting:**
- *Лог пустой:* audit device не включён — проверьте `vault audit list`.
- *Формат не JSON:* убедитесь, что `file` device настроен с `format=json` (по умолчанию JSON для file).

**Платформо-специфичные механизмы** (профильные разделы, здесь не дублируются): [GitLab CI Variables/Secrets](../GitLab_CI/Concepts/gitlab_ci_variables_secrets.md), [GitHub Actions Secrets](../../Github_CI/secrets_management.md), [Docker Secrets](../../Docker/Docker_security/secrets_management.md), [Kubernetes Application Secrets](../../Kubernetes/Security/application_secrets_management.md).

## Оперативные команды

### Команды для работы с секретами

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `gitleaks detect --source=. --report-path=gitleaks.json` | Поиск секретов в Git-репозитории | # → JSON с находками или пустой файл |
| `trufflehog git file:///path/to/repo --json` | Сканирование всей истории Git | # → JSON с находками или пустой |
| `vault kv get secret/<path>` | Чтение секрета из Vault | # → вывод ключ-значение |
| `vault kv put secret/<path> key=value` | Запись секрета в Vault | # → подтверждение успешной записи |
| `vault read database/creds/<role>` | Получение динамических учетных данных БД | # → username/password с TTL |
| `vault audit enable file file_path=/var/log/vault/audit.log` | Включение аудит-логирования Vault | # → подтверждение включения |
| `detect-secrets scan > .secrets.baseline` | Создание бейзлайна секретов | # → файл .secrets.baseline с находками |
| `pre-commit run --all-files` | Запуск pre-commit хуков | # → PASS или список нарушений |

### Реагирование на инцидент (Incident Response Runbook)

При обнаружении утечки секрета:

1. **Остановить:** отозвать скомпрометированный ключ в панели управления провайдера.
2. **Ротировать:** сгенерировать новые учетные данные.
3. **Очистить:** использовать BFG Repo-Cleaner или `git filter-repo` для удаления следов секрета из истории.
4. **Аудит:** проверить логи доступа на предмет подозрительной активности в период утечки.
5. **Уроки:** blameless postmortem, обновление политик доступа и правил сканеров.

## Устранение неисправностей

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `gitleaks` false positive на тестовом ключе | Шаблон совпал с тестовыми данными | Добавить хэш находки в `.gitleaksignore` или пометить файл через комментарий |
| `vault: permission denied` | Политика запрещает путь или метод аутентификации | `vault policy read <policy>`; проверить `path` и `capabilities` |
| `vault read auth/jwt/role/ci-role` — 403 | Несовпадение `bound_claims` или `bound_audiences` | Декодировать JWT через `jwt.io`; проверить audience |
| `trufflehog` не находит находки в истории | Сканирование только текущего состояния | Добавить флаг `git file:///path/to/repo` для полной истории |
| Секрет не обновляется в Pod | Используется `subPath` или immutable Secret | Удалить Pod или отключить `immutable` |
| Pre-commit hook не срабатывает | Нет прав на выполнение или symlink сбит | `ls -l .git/hooks/pre-commit` → должен указывать на `pre-commit` |
| Динамический секрет не отзывается | Истёк TTL, но приложение кэширует connection | Перезапустить приложение или настроить connection refresh |
| `detect-secrets` — ложное срабатывание | Бейзлайн включает тестовые данные | Обновить бейзлайн через `detect-secrets scan --update .secrets.baseline` |
| SecretID в AppRole истёк | Wrap-токен живёт `wrap-ttl` секунд | Перевыпустить через `vault write -wrap-ttl=60s auth/approle/role/jenkins/secret-id` |
| Утечка в Git-истории | Секрет был закоммичен ранее | `git filter-repo` + принудительная ротация секрета |

## Рекомендации

### Хост-харднинг раннеров (Runner Hardening)

- **Эфемерные раннеры:** каждый джоб выполняется на свежем экземпляре, уничтожаемом после. GitLab: флаг `--ephemeral` у `gitlab-runner`; GitHub Actions: `runs-on: [self-hosted, ephemeral]`.
- **Наименьшие привилегии:** раннер работает под выделенным пользователем без широких прав; нет SSH-ключей к проду.

```bash
id gitlab-runner                 # → проверить, что раннер не в группе sudo/wheel
sudo -l -U gitlab-runner         # → должен выдавать только необходимые NOPASSWD-команды
```

- **Сетевая изоляция:** раннеры в отдельном VLAN; исходящий трафик — только к внутреннему registry/mirror и необходимым хостам (egress allowlist). Недоверенные зависимости тянутся через внутреннее зеркало, а не напрямую из интернета.
- **Очистка диска и workspace:** шифрование диска (LUKS), `clear_readonly` / очистка workspace между джобами; для контейнерных раннеров — read-only rootfs и `--rm`.
- **Секреты в рантайме:** инъекция через Vault/секрет-менеджер в память, никогда не пишутся на диск; маскировка в логах (`--mask` / settings).
- **Ограничение ядра:** seccomp/AppArmor-профили, запрет `privileged` контейнеров.

### Сетевая сегментация и управление доступом

- **Zero Trust на уровне раннеров:** каждый раннер обслуживает только определённый набор проектов/групп; нет общего раннера на всю организацию без network policies.
- **Egress-фильтрация:** исходящие соединения только к registry, artifact store и необходимым внешним API; всё остальное через proxy с DLP.
- **Segregation of Duties:** раннеры для PR/build отдельно от deploy/release; разные секреты, разные уровни доступа.

### Жизненный цикл и ротация

- **Ротация автоматизирована** (плановая + по событию), ведётся инвентаризация.
- **Ретенционные политики:** секреты ротируются каждые 90 дней; аудит-логи хранятся 30–90 дней в зависимости от compliance требований.
- **Stale secrets:** регулярный аудит на предмет неиспользуемых секретов с последующим выводом из эксплуатации.

### Резервное копирование и восстановление

- **Vault:** снапшоты Raft-хранилища + внешнее хранилище ключей (KEK). Восстановление — развёртывание нового кластера из снапшота и ввод unseal-ключей.
- **Конфигурация CI/CD:** версионируется в Git; потеря CI-конфигурации = потеря reproducibility.
- **Восстановление:** tested restore procedure для Vault и artifact store; runbook на случай компрометации хранилища.

### Политики и метрики

- **Quality gate для секретов:** блокировка коммитов при обнаружении критичных секретов (gitleaks/detect-secrets + push protection).
- **Метрики программы:** количество утечек в Git, среднее время ротации (MTTR), доля секретов с автоматической ротацией.
- **Аудит:** Vault audit device включён, логи собираются и ревьюируются; настраиваются алерты на аномальное число выдач токенов или чтений секретов.

### Чек-лист минимальной защищённости (Quick Reference)

1. **Pre-commit:** gitleaks + detect-secrets + semgrep установлены у разработчиков.
2. **CI gate:** secret scan на PR; push protection включён.
3. **Хранилище:** Vault или аналогичный менеджер с политиками минимальных привилегий.
4. **Доступ:** Secretless/JIT (OIDC/AppRole) — нет статических ключей доступа к хранилищу.
5. **Раннеры:** эфемерные, изолированные, без широких прав.
6. **Ротация:** автоматизирована для всех долгоживущих секретов.
7. **Аудит:** audit device включён, логи собираются и ревьюируются.
8. **Runbook:** реагирования на утечку задокументирован и проверен на учениях.

## Дополнительная информация

### Вызовы (2026)

1. **Identity Sprawl:** Управление жизненным циклом миллионов кратковременных секретов и прав доступа (NHI).
2. **Secret-Zero Elimination:** Полный отказ от статических паролей для доступа к хранилищам секретов.
3. **Compliance Burden:** Соответствие PCI DSS, 152-ФЗ, ФСТЭК/ФСБ при минимальных операционных издержках.

### Операционный контекст: DevOps / SRE / Sysadmin

Управление секретами — это надстройка над инфраструктурой, поэтому инженер обязан владеть операционной частью: релизами, наблюдаемостью, инцидентами, Linux и сетью. Ниже — навигатор по уже существующим заметкам vault (без cloud/AI, ориентир — продакшен и собеседования). Дублировать их содержимое здесь не нужно; это точки входа под конкретный угол.

#### Теория (interview-уровень)
- **SRE: SLO/SLI/error budgets, four golden signals, burn rate** — [Concepts/sre_concepts_main.md](../../Concepts/sre_concepts_main.md).
- **DORA-метрики** — [CI-CD/Core_Concepts/dora_metrics.md](../../CI-CD/Core_Concepts/dora_metrics.md).
- **CI/CD паттерны** — [CI-CD/ci_cd_patterns.md](../../CI-CD/ci_cd_patterns.md), [CI-CD/Core_Concepts/pipeline_glossary.md](../../CI-CD/Core_Concepts/pipeline_glossary.md).

#### Практика — Linux/sysadmin, сеть, контейнеры
- **Linux sysadmin (systemd / cgroups / namespaces / пользователи)** — [systemd/overview](../../Linux/Core/systemd/overview.md), [cgroups](../../Linux/Core/cgroups.md), [namespaces](../../Linux/Core/namespaces.md).
- **Харденинг / CIS / аудит Linux** — [Security/Tools/lynis.md](../../Security/Tools/lynis.md), [Linux/Security/Mechanisms/Kernel/hardening.md](../../Linux/Security/Mechanisms/Kernel/hardening.md).
- **Сеть (iptables / nftables / firewall)** — [iptables_basics](../../Linux/Networking/Settings/tools/iptables_basics.md), [nftables/practical_scenarios](../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md).
- **SSH / bastion (cert-auth, fail2ban)** — [ssh_certificate_authentication](../../Linux/Security/ssh/server/ssh_certificate_authentication.md), [fail2ban](../../Linux/Security/Tools/fail2ban.md).
- **Backup / DR** — [Kubernetes/Operations/backup-strategies.md](../../Kubernetes/Operations/backup-strategies.md), [Databases/Concepts/backups.md](../../Databases/Concepts/backups.md).
- **Compliance / аудит** — [Audit and compliance overview](../../Security/audit_and_compliance_overview.md), [Ansible OS hardening](../../Ansible/ansible-os-hardening.md).
- **Vulnerability management / triage** — [CVE triage workflow](../../Security/Supply_Chain_Security/cve_triage_workflow.md), [Vulnerability management](../../Linux/Security/vulnerability_management.md).

## См. также

- [Обзор методологии DevSecOps](./devsecops_overview.md)
- [Обзор HashiCorp Vault](../../Vault/overview.md)
- [Антипаттерны управления секретами](../../Vault/common_antipatterns.md)
- [SCA и анализ зависимостей](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)
- [Сравнение SCA-инструментов](../../Security/Supply_Chain_Security/sca_tools_comparison.md)
- [Безопасность контейнеров](../../Docker/Docker_security/vulnerability_scanning.md)
- [Compliance и аудит](../../Security/audit_and_compliance_overview.md)
- [Vulnerability management и CVE triage](../../Security/Supply_Chain_Security/cve_triage_workflow.md)
- [Incident response для CI/CD](../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md)
