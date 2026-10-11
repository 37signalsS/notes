# Усиление безопасности CI/CD

## Определения

- **CI/CD Security Hardening** — процесс укрепления безопасности пайплайнов, Runner'ов и инфраструктуры CI/CD от угроз: утечки секретов, компрометации зависимостей, несанкционированного доступа и supply chain атак.
- **Наименьшие привилегии (Least Privilege)** — раннер/реестр имеют только права, необходимые для задачи.
- **RBAC** — ролевое управление доступом к проектам, секретам и окружениям.
- **mTLS** — взаимное TLS-шифрование с проверкой сертификатов обеих сторон.
- **OIDC-федерация** — выдача временных токенов внешним системам без долгоживущих ключей (см. [OIDC в глоссарии](./pipeline_glossary.md)).
- **Ротация секретов** — регулярная смена ключей/паролей с отзывом старых.
- **SSH-hardening** — настройка доступа по ключам, запрет паролей и root-логина (см. [SSH hardening](../../Linux/Security/ssh/server/ssh_hardening_best_practices.md)).
- **Цепочка поставок (Supply Chain)** — SBOM, SLSA, подписание артефактов (см. [Глоссарий: SBOM/SLSA](./pipeline_glossary.md)).

## Основные концепции

### Принцип наименьших привилегий

Раннеры не должны работать от `root` и не должны иметь доступа ко всем окружениям сразу. Разделяйте раннеры по проектам/окружениям и выдавайте токены с минимальным scope. Управление доступом на уровне ОС — в [Механизмах безопасности Linux](../../Linux/Security/Linux_Security_Mechanisms_Overview.md).

| Площадка | Роль | Ответственность |
| :--- | :--- | :--- |
| **DevOps** | Проектирование пайплайнов | Разделение стадий, scoped переменные, approval-гейты |
| **SRE** | Надежность и мониторинг | SLO на пайплайны, алерты на компрометацию раннеров, incident response |
| **Sysadmin** | Инфраструктура и доступ | ОС-хостинг раннеров, firewall, SSH, локальный УЦ |

### Управление секретами

- Секреты **никогда** не в переменных репозитория в открытом виде и не в логах. Используйте менеджер (Vault) с OIDC-федерацией для временных credential (пример в [Глоссарии: Secrets Management](./pipeline_glossary.md)).
- Ротация: токены CI, ключи подписи, credentials реестра обновляются по графику, старые отзываются.

### SSH и бастион

Доступ к узлам контура — только по ключам, через прыжковый хост (bastion) с `ProxyJump`, без паролей и без `PermitRootLogin`. Проброс портов и туннели — в [SSH туннели](../../Linux/Security/ssh/ssh_usage_and_tunnels.md).

### Сеть: firewall и mTLS

На бастионе/реестре — минимальный набор правил (nftables/iptables): только нужные порты с нужных адресов. Между компонентами (раннер → реестр → оркестратор) — mTLS через локальный УЦ (см. [Изолированные среды](./air_gapped_environments.md), раздел Private CA).

### Целостность цепочки поставок

Подписывайте образы/артефакты (cosign) и проверяйте перед импортом; ведите SBOM для аудита уязвимостей. См. [Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md).

## Практические сценарии

### Сценарий 1: SSHD hardening (бастион)

```sshdconfig
# /etc/ssh/sshd_config — базовый набор усиления
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
AllowUsers deploy@10.0.0.0/24
```

**Validation:** `sshd -t` возвращает пустой вывод; подключение по паролю отклоняется, по ключу — разрешено.

### Сценарий 2: OIDC-федерация в GitLab CI (без долгоживущих ключей)

```yaml
# Получение временного токена Vault через OIDC (self-hosted)
vault_oidc:
  script:
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login role=ci jwt=$CI_JOB_JWT)
    - ansible-playbook deploy.yml   # токен живёт минуты, не хранится в репо
```

**Validation:** в логах `VAULT_TOKEN` маскирован; в Vault audit-логе виден обмен JWT на токен с TTL.

### Сценарий 3: nftables на реестре (минимум)

```bash
nft add table inet filter
nft add rule inet filter input tcp dport 22 ip saddr 10.0.0.0/24 accept
nft add rule inet filter input tcp dport 443 accept
nft add rule inet filter input drop
```

**Validation:** `nft list ruleset` выводит три правила; с хоста за пределами `10.0.0.0/24` порт 22 закрыт.

### Сценарий 4: Подписание и проверка образа (cosign)

```bash
cosign generate-key-pair            # или использовать локальный УЦ
cosign sign --key cosign.key registry.internal/library/app:1.2
# Перед импортом в контур:
cosign verify --key cosign.pub registry.internal/library/app:1.2
```

**Validation:** `cosign verify` возвращает `Verified`; при подмене манифеста верификация падает с ненулевым кодом.

### Сценарий 5: Сканирование секретов в коммитах (gitleaks)

```bash
gitleaks detect --source=. --report-format=json --report-path=gitleaks-report.json
```

**Validation:** при наличии секрета в истории команда завершается с ненулевым кодом и формирует `gitleaks-report.json`; на чистом репо — пустой отчет или `0 findings`.

### Сценарий 6: Харденинг Runner'а (docker executor)

```toml
# /etc/gitlab-runner/config.toml — hardened
[[runners]]
  name = "hardened-runner"
  executor = "docker"

  [runners.docker]
    privileged = false
    cap_add = ["NET_ADMIN"]
    cap_drop = ["ALL"]
    security_opt = ["no-new-privileges:true"]
    readonly_rootfs = true
    network_mode = "gitlab-isolated"
    shutdown_timeout = 30

  metrics_server = ":9252"
```

**Validation:** `gitlab-runner run` запускает джоб без root в контейнере; `docker inspect` показывает `SecurityOpt` и `ReadonlyRootfs`.

## Операции и команды

### Харденинг и проверка инфраструктуры

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `sshd -t` | Проверка конфигурации SSH | # → пустой вывод (ошибки в stderr) |
| `nft list ruleset` | Просмотр активных правил firewall | # → текущий набор правил inet filter |
| `gitlab-runner verify` | Проверка конфигурации Runner'а | # → Runner=... verified |
| `gitleaks detect --source=.` | Поиск секретов в репозитории | # → `0 findings` или JSON-отчет |
| `cosign verify --key cosign.pub registry/...` | Верификация подписи образа | # → `Verified` или ошибка верификации |
| `cosign sign --key cosign.key registry/...` | Подписание образа | # → запись в реестр, attestation прикреплена |
| `vault write -field=token auth/jwt/login ...` | Получение временного токена через OIDC | # → токен с TTL (например, 15m) |
| `vault read auth/jwt/role/<role>` | Проверка конфигурации JWT-роли | # → параметры bound_claims, policies, ttl |

### Диагностика и аудит

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `journalctl -u gitlab-runner -f` | Просмотр логов Runner'а в реальном времени | # → поток логов, ошибки инициализации |
| `docker ps -a --filter ancestor=...` | Поиск остановленных контейнеров раннера | # → список контейнеров или пустой вывод |
| `curl -vk https://vault.internal/v1/sys/health` | Проверка доступности Vault | # → `{"initialized":true,"sealed":false,...}` |
| `vault audit enable file file_path=/var/log/vault/audit.log` | Включение аудит-логирования Vault | # → подтверждение включения |
| `kubectl get pods -n <ns> -o wide` | Проверка подов пайплайна в K8s | # → таблица подов с IP и node |
| `iptables -L -n -v` или `nft list ruleset` | Проверка firewall на узле | # → таблица chains и counters |

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Секреты в переменных CI в открытом виде | Утечка при экспорте логов/форков | Переместить в Vault, включить masking, использовать OIDC |
| Раннер с правами root | Компрометация репо = root на узле | Запускать под выделенным пользователем, `privileged=false`, `no-new-privileges` |
| Нет ротации секретов | Утекший токен живёт вечно | Автоматизация через Vault/CI schedule, TTL и JIT |
| Открытый бастион (пароли, root-логин) | Прямая точка входа атакующего | `PasswordAuthentication no`, `PermitRootLogin no`, ключи |
| `sshd -t` выводит ошибки | Синтаксическая ошибка в `sshd_config` | Исправить параметр, повторная проверка |
| cosign verify падает | Неверный публичный ключ или подпись | Проверить `cosign.pub`, целостность манифеста |
| gitleaks false positive | Тестовые данные совпали с паттерном | Добавить хэш в `.gitleaksignore` или обновить бейзлайн |
| Vault недоступен из пайплайна | Сеть, DNS, политика firewall | Проверить egress, разрешение `vault.internal`, порт 8200 |
| Runner не поднимается | Неверный `config.toml` или нет прав | `gitlab-runner verify`, проверка `docker` socket/`kubectl` контекста |

## Лучшие практики

### GitHub Actions: специфика безопасности

Для GitHub Actions есть ряд платформо-специфичных мер безопасности, которых нет в GitLab CI или Jenkins.

**1. `permissions` ключ (самая важная мера):**
```yaml
# По умолчанию GITHUB_TOKEN имеет широкие права.
# Явно ограничивайте:
permissions:
  contents: read       # только чтение кода
  pull-requests: read  # доступ к PR
  id-token: write      # только для OIDC-аутентификации
  # packages: write   # только если нужно push образов
  # actions: read      # доступ к кэшу и артефактам
```

**2. Ограничение `GITHUB_TOKEN` по умолчанию:**
- По умолчанию токен имеет права `contents: write`, `issues: write`, `pull_requests: write` и др. Для production-деплоя обязательно ограничивайте `permissions` на уровне workflow или job.
- `GITHUB_TOKEN` автоматически маскируется в логах (как и `secrets.*`).

**3. OIDC вместо статических секретов:**
```yaml
jobs:
  deploy:
    permissions:
      id-token: write
      contents: read
    steps:
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123456789012:role/github-actions-deploy
          aws-region: us-east-1
      - name: Deploy
        run: ./deploy.sh
```

**Настройка OIDC-identity provider (однократно):**
- AWS: IAM → Identity providers → Create provider (`https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`).
- Настраивайте trust policy с ограничением `sub` на конкретный репозиторий и ветку:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Federated": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:my-org/my-repo:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

**4. Self-hosted runner hardening:**
- Используйте `--ephemeral` при регистрации или ARC с `ephemeral: true` — каждый job на чистом pod.
- Запускайте runner под непривилегированным пользователем; не используйте root.
- Регулярно обновляйте приложение runner'а (устаревшие версии принудительно отключаются).
- Для публичных репозиториев self-hosted runner'ы запрещены по умолчанию (настройте `allowed_runners` в organization settings).

**5. Supply Chain Security:**
- Используйте только проверенные действия из Marketplace; проверяйте `uses` на ввод данных извне.
- Пинуйте действия по версии (`actions/checkout@v7`), а не по `@main`/`@master`.
- Генерируйте SBOM и подписывайте образы (cosign) в пайплайне.
- Включите GitHub Advanced Security (GHAS) для сканирования уязвимостей и секретов, если доступно.

**6. Branch Protection Rules:**
- Требуйте review перед merge.
- Требуйте статус-чеков (required status checks) перед merge.
- Запрещайте force-push в production-ветки.
- Используйте CODEOWNERS для назначения ревьюеров.

**7. Environment Protection Rules:**
- Для production-environment: настройте `deployment review` (требование approval).
- Используйте `deployment_branch_policy` для ограничения веток, которые могут деплоить в environment.

**8. Audit Trail:**
- Включите audit log (доступно в Enterprise).
- Критические действия: создание/удаление секретов, изменение runner'ов, изменение branch protection.

**9. Сетевая изоляция:**
- Self-hosted runner'ы должны иметь исходящий трафик только к необходимым хостам (egress allowlist).
- Используйте внутренние зеркала для зависимостей (Nexus, Artifactory, pull-through cache).
- Для недоверённого кода (PR из forks) используйте `pull_request` триггер (не `pull_request_target`) или изолируйте выполнение.

- **Наименьшие привилегии:** раннер работает под выделенным пользователем без широких прав; нет SSH-ключей к проду.
- **Эфемерные раннеры:** каждый джоб выполняется на свежем экземпляре, уничтожаемом после. Для GitLab — флаг `--ephemeral`; для Jenkins — облачные агенты с discard.
- **Сетевая изоляция:** раннеры в отдельном VLAN; исходящий трафик — только к внутреннему registry/mirror и необходимым хостам (egress allowlist). Недоверенные зависимости тянутся через внутреннее зеркало, а не напрямую из интернета.
- **Очистка диска и workspace:** шифрование диска (LUKS), `clear_readonly` / очистка workspace между джобами; для контейнерных раннеров — read-only rootfs и `--rm`.
- **Секреты в рантайме:** инъекция через Vault/секрет-менеджер в память, никогда не пишутся на диск; маскировка в логах.
- **Ограничение ядра:** seccomp/AppArmor-профили, запрет `privileged` контейнеров.
- **Zero Trust на уровне раннеров:** каждый раннер обслуживает только определённый набор проектов/групп; нет общего раннера на всю организацию без network policies.
- **Segregation of Duties:** раннеры для PR/build отдельно от deploy/release; разные секреты, разные уровни доступа.
- **Аудит:** логирование каждого обращения к секретам, изменений в пайплайне и запусков раннеров; без аудита невозможно расследовать инцидент.
- **Резервное копирование и восстановление:** конфигурация CI/CD версионируется в Git; Vault — снапшоты Raft-хранилища + внешнее KEK; tested restore procedure.

## Дополнительная информация

### См. также

- [Управление секретами в CI/CD](../DevSecOps/secrets_management.md) — OIDC, Vault, ротация и инциденты.
- [Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md) — SLSA, SBOM, подписание артефактов.
- [CI/CD Security Hardening (GitLab Advanced)](../GitLab_CI/Advanced/cicd_security_hardening.md) — платформо-специфичные сценарии для GitLab CI.

### Смежные практики

Смежные практики (инлайн-ссылки): **[SSH туннели](../../Linux/Security/ssh/ssh_usage_and_tunnels.md)** — прыжковые хосты и проброс портов; **[Изолированные среды](./air_gapped_environments.md)** — Private CA, зеркала, подписи в закрытом контуре.
