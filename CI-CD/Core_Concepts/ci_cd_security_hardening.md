# Усиление безопасности CI/CD (DevSecOps)

## Определения

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

### Сценарий 2: OIDC-федерация в GitLab CI (без долгоживущих ключей)

```yaml
# Получение временного токена Vault через OIDC (self-hosted)
vault_oidc:
  script:
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login role=ci jwt=$CI_JOB_JWT)
    - ansible-playbook deploy.yml   # токен живёт минуты, не хранится в репо
```

### Сценарий 3: nftables на реестре (минимум)

```bash
nft add table inet filter
nft add rule inet filter input tcp dport 22 ip saddr 10.0.0.0/24 accept
nft add rule inet filter input tcp dport 443 accept
nft add rule inet filter input drop
```

### Сценарий 4: Подписание и проверка образа (cosign)

```bash
cosign generate-key-pair            # или использовать локальный УЦ
cosign sign --key cosign.key registry.internal/library/app:1.2
# Перед импортом в контур:
cosign verify --key cosign.pub registry.internal/library/app:1.2
```

## Дополнительная информация

### Типичные ошибки

- **Секреты в переменных CI** в открытом виде — утечка при экспорте логов/форков.
- **Раннер с правами root** — компрометация репо = root на узле.
- **Нет ротации** — утекший токен живёт вечно.
- **Открытый бастион** (пароли, root-логин) — прямая точка входа атакующего.

### См. также

- [Глоссарий пайплайнов](./pipeline_glossary.md) — Secrets Management, OIDC, SLSA.
- [Изолированные среды](./air_gapped_environments.md) — Private CA, прыжковый хост, подписи.
- [Механизмы безопасности Linux](../../Linux/Security/Linux_Security_Mechanisms_Overview.md) — RBAC/PAM/контроль доступа.
