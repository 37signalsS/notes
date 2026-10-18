# Secrets Management Overview

**Актуально для:** HashiCorp Vault 2.x, SOPS 3.10+, Kubernetes 1.31+, Docker Engine 29.x

## Определения

**Secrets Management** — процесс безопасного хранения, контроля доступа, аудита и ротации чувствительных данных: паролей, API-ключей, токенов, TLS-сертификатов, SSH-ключей.

**Секрет** — любые данные, компрометация которых нарушает конфиденциальность, целостность или доступность системы.

**Ключевая задача:** исключить хранение секретов в открытом виде в коде, Git, логах, конфигурационных файлах.

## Основные концепции

### Стратегии управления секретами

| Стратегия | Описание | Применение |
|-----------|----------|------------|
| **Централизованное хранилище** | Единое защищённое место (Vault) | Крупные проекты, production |
| **Шифрование в Git (GitOps)** | Секреты шифруются, хранятся в Git рядом с кодом | GitOps-пайплайны |
| **Нативные решения платформы** | Встроенные средства (Kubernetes Secrets, Docker Secrets) | Среды с ограниченными требованиями |
| **Переменные окружения CI/CD** | Секреты управляются CI/CD-системой | Small projects, CI/CD-стадии |

### Принципы безопасности

- **Шифрование на rest:** секреты шифруются при хранении (KMS, PGP, age)
- **Минимальные привилегии:** доступ только для необходимых сервисов/пользователей
- **Ротация:** периодическая смена секретов без простоя систем
- **Аудит:** логирование всех операций чтения/записи/удаления
- **Никогда в логах:** секрет не должен попадать в stdout/stderr, логи, метрики

### Типы секретов

| Тип | Примеры | Особенности управления |
|-----|---------|----------------------|
| **Учётные данные** | Пароли БД, API-ключи, токены | Краткосрочные, подлежат ротации |
| **Криптографические ключи** | SSH-ключи, TLS-сертификаты, JWT-ключи | Долгосрочные, требуют защиты от утечки |
| **Сервисные идентификаторы** | ServiceAccount, AppRole, machine identities | Создаются автоматически, имеют ограниченный TTL |
| **Секреты сборки** | Токены реестра, GPG-ключи подписи | Существуют только во время пайплайна |

### Non-Human Identities (NHI)

**NHI (Non-Human Identities)** — нечелеческие сущности (сервисные аккаунты, robot-accounts, workload identities), управляющие доступом к инфраструктуре. В 2026 году NHI составляют до 95% всех цифровых сущностей и являются основной целью атак.

| Тип NHI | Пример | Жизненный цикл |
| :--- | :--- | :--- |
| **Service Account** | Kubernetes ServiceAccount, AWS IAM Role | Постоянный, с ротацией токенов |
| **AppRole** | Vault AppRole | С ограниченным SecretID TTL |
| **Machine-to-Machine** | CI/CD пайплайн → Vault | Через OIDC Workload Identity Federation |
| **Workload Identity** | GitHub Actions OIDC → Vault | Временные JWT-токены (1–15 мин) |

**Secret-Zero:** классическая проблема — для получения секретов из хранилища приложению изначально требуется статический идентификатор. Современное решение — Workload Identity Federation через OIDC, исключающее статические ключи. Подробнее — в **[CI/CD Secrets Management](../../CI-CD/DevSecOps/secrets_management.md)**.

### Сравнение подходов

| Критерий | CI/CD Variables | SOPS | HashiCorp Vault | K8s Secrets (с шифрованием) |
| :--- | :--- | :--- | :--- | :--- |
| **Простота** | Высокая | Средняя | Низкая | Средняя |
| **Безопасность** | Средняя | Высокая | Очень высокая | Высокая |
| **Централизация** | Низкая | Средняя (репозиторий) | Высокая | Средняя (кластер) |
| **GitOps** | Нет | Да | Частично | Да (Sealed Secrets / SOPS) |
| **Динамические секреты** | Нет | Нет | Да | Нет |
| **Аудит** | Ограниченный | Через Git | Детальный | Через K8s audit / Git |

### Модель угроз (Threat Model)

| Вектор | Как секрет попадает наружу | Контрмера |
| :--- | :--- | :--- |
| **Переменные окружения** | видны в `ps auxe`, `/proc/<pid>/environ`, дампах при падении | JIT/OIDC, инъекция в память, маскирование |
| **Логи CI/build** | печать переменной, трассировки, архивы логов job'а | маскирование, запрет `set -x` для секретных шагов |
| **Слои образа** | `ENV`/`COPY` ключей остаются в истории слоёв | BuildKit `--secret`, multi-stage без ключей |
| **Кэш CI / shared runners** | секрет попадает в кэш зависимостей или workspace другого джоба | эфемерные раннеры, изолированный кэш |
| **Swap / pagefile / core dump** | секрет из памяти сбрасывается на диск | `swap off`/`encrypted swap`, `ulimit -c 0`, `IPC_LOCK` |
| **Process listing / IPC** | `ps`, `/proc`, shared memory | наименьшие привилегии, read-only rootfs |
| **История Git** | случайный коммит | pre-commit сканирование, push protection, `git filter-repo` |
| **Физический доступ к носителям** | несанкционированное чтение бэкапов, дисков | шифрование дисков, защищённые хранилища |
| **Утечка через каналы связи** | перехват трафика при передаче | TLS/mTLS, изоляция сетей |

### Локальные инструменты для работы с секретами

Для системных администраторов и SRE ключевыми инструментами являются:

- **age** — современный инструмент для шифрования файлов (альтернатива GPG). Простой в управлении, быстрый. Рекомендуется для локальной разработки и командной работы.
- **GnuPG (GPG)** — классическая реализация OpenPGP. Подходит для подписей Git-коммитов, шифрования почты и файлов. Подробнее — [GPG и OpenPGP](../../Linux/Security/Tools/gpg_and_openpgp.md).
- **OpenSSL** — универсальная криптографическая библиотека и CLI. Используется для генерации ключей, сертификатов, шифрования файлов и отладочных целей.
- **systemd-creds** — встроенный механизм systemd (v247+) для шифрования секретов с привязкой к конкретной машине. Секреты шифруются ключом TPM или machine-id, что исключает их чтение на другом хосте.
- **ssh-agent / keychain** — безопасное хранение SSH-ключей в памяти с кэшированием фразы-пароля. `keychain` добавляет персистентность между сессиями.

### Жизненный цикл секрета (Secret Lifecycle)

Секрет проходит через несколько стадий, и безопасность определяется тем, насколько коротко и контролируемо он существует на каждой из них:

1.  **Генерация (Generation):** высокоэнтропийные значения (CSPRNG, `openssl rand`, встроенные генераторы хранилища), без ручного ввода.
2.  **Хранение (Storage):** шифрование при хранении (encryption at rest), доступ строго по политике, разделение на окружения.
3.  **Доставка (Distribution):** только в память процесса или временный `tmpfs`/файл, поверх TLS; никогда — в `ENV` навсегда или в образ.
4.  **Использование (Usage):** минимальное время жизни, маскирование в логах.
5.  **Ротация (Rotation):** плановая или по событию (см. ниже).
6.  **Отзыв (Revocation):** немедленный отзыв при компрометации.
7.  **Уничтожение (Destruction):** безопасное удаление из памяти/диска и из истории Git.
8.  **Аудит (Audit):** логирование каждого обращения.

Общий принцип: секрет должен существовать *ровно столько и только там*, где он нужен.

### Сканирование и обнаружение секретов

Первая линия обороны — не допустить попадания секретов в систему контроля версий:

- **Shift Left (Pre-commit хуки):** [Betterleaks](../Tools/betterleaks.md) (наследник `gitleaks`), `gitleaks`, `trufflehog`, `detect-secrets` локально у разработчиков.
- **Push Protection:** встроенные механизмы GitLab/GitHub, блокирующие коммиты с обнаруженными ключами.
- **История коммитов:** сканирование всей истории (не только текущего состояния) для обнаружения старых утечек.
- **Непрерывное сканирование:** регулярный запуск сканеров в CI-пайплайнах и регламентный аудит артефактов.

### Инвентаризация и обнаружение секретов (Secret Discovery)

Операционная задача SRE/Sysadmin — поддерживать актуальный **инвентарь секретов**: знать, где каждый секрет используется, кто владелец, когда ротировался, используется ли он вообще (stale secrets = риск).

| Инструмент | Для чего | Особенности |
| :--- | :--- | :--- |
| **Vault API** | `vault list sys/leases/lookup/...` | Перечисление активных leases, TTL. |
| **GitLab/GitHub Secret Scanning** | Поиск в репозиториях | CI-level обнаружение; push protection. |
| **trufflehog / gitleaks** | Сканирование истории Git | Полный offline-обход, `--no-update` в CI. |
| **detect-secrets** | Pre-commit baseline | Инкрементальное, минимум ложных срабатываний. |
| **kube-no-trouble / popeye** | K8s аудит | Проверка устаревших Secret, RBAC. |
| **Ansible Vault / Ansible lookup** | Инвентарь в Ansible | Поиск зашифрованных блоков в ролях. |

**Automation:** инвентаризацию можно автоматизировать через nightly-сканеры с записью в CMDB/инвентарь. Stale secrets (>90 дней без ротации) автоматически попадают в тикет в Jira/Linear.

### Роутение и доставка секретов (Operational Pattern)

Для on-prem и гибридных инфраструктур (без cloud-зависимости) характерны следующие паттерны доставки секретов в runtime:

| Паттерн | Инструмент | Когда |
| :--- | :--- | :--- |
| **Init Container → tmpfs** | Vault + K8s | K8s-приложения |
| **systemd-creds** | systemd v247+ | Linux-сервисы |
| **BuildKit --mount=type=secret** | Docker BuildKit | Этапы сборки образов |
| **Docker secrets / tmpfs** | Docker Swarm/Compose | Контейнеры в standalone |
| **OpenSSH certificates** | ssh-ca + Vault SSH | SSH-доступ на хосты |

### Автоматизация ротации секретов

Ротация — ключевая операция в жизненном цикле. Детальное описание механизмов ротации в HashiCorp Vault — в **[Ротация секретов в Vault](../../Vault/guides/secret_rotation.md)**.

| Тип ротации | Стратегия | TTL | Автоматизация |
| :--- | :--- | :--- | :--- |
| **Dynamic Secrets** | Vault Database Secrets Engine | 1–24h | Автоматически |
| **Static Secrets** | KV v2 с versioning | 90–180 дней | `cron` + Vault API |
| **Root Credentials** | Database rotate-root | после onboarding | Vault Enterprise |
| **Transit Keys** | `/transit/keys/:name/rotate` | 24h | `auto_rotate_period` |
| **SSH CA** | Overlapping CA keys | 90 дней | Ansible + Vault |
| **TLS Certificates** | cert-manager / certbot | 90 дней | ACME + webhook |

**SRE принцип:** ротация должна быть **бесшовной (zero-downtime)**. Приложения поддерживают graceful reload при смене пароля; для legacy-систем — sidecar-паттерн с Vault Agent.

### Мониторинг и алертинг секретов

Для наблюдаемости SRE критически важно отслеживать:

- **Состояние хранилища:** Vault unsealed? Резервные копии актуальны?
- **Активность:** anomalous access patterns, рост количества проблемных токенов, orphaned leases.
- **Ротация:** `last_vault_rotation` / `next_vault_rotation` для dynamic и static roles.
- **Аудит:** все read/write операции с секретами логируются (Vault Audit Device, K8s audit, CI/CD audit).

Подробнее — в **[Мониторинг и алертинг Vault](../../Vault/guides/monitoring_and_alerting.md)** и **[Анализ audit логов](../../Vault/guides/audit_log_analysis.md)**.

## Практические сценарии

### HashiCorp Vault — централизованное управление

Авторитетный источник: [Vault overview](../../Vault/overview.md)

Для масштабных и зрелых проектов. Обеспечивает хранение, аудит, динамическую генерацию и ротацию секретов.

```bash
# Записать секрет
vault kv put secret/db password="SuperSecret123"

# Прочитать секрет
vault kv get secret/db

# Динамический секрет (PostgreSQL)
vault write database/creds/readonly
```

Интеграции: [Vault + Docker](../../Vault/guides/vault_docker_integration.md), [Vault + ArgoCD](../../GitOps/ArgoCD/argocd_vault_integration.md).

### Kubernetes Secrets — нативный подход

Авторитетный источник: [Kubernetes Secrets](../../Kubernetes/Base/secrets/secrets_basics.md)

Ресурс `Secret` хранит данные в base64 в etcd — **по умолчанию не шифруется**. Требуется включение [EncryptionConfiguration](../../Kubernetes/Base/secrets/security.md) или внешнее шифрование.

**Инструменты шифрования для Git:**

- **[Sealed Secrets](../../Kubernetes/Security/sealed_secrets_overview.md)** — шифрует так, что расшифровать может только контроллер в кластере
- **[SOPS](../Tools/sops_overview.md)** — шифрование файлов через PGP, age
- **[External Secrets Operator](../../Kubernetes/Base/secrets/external_managers.md)** — синхронизация из Vault, локальных KMS

### SOPS + GitOps

Авторитетный источник: [SOPS overview](../Tools/sops_overview.md), [GitOps Secrets](../../GitOps/secrets_encryption.md)

Шифрование значений (не ключей) в YAML/JSON/ENV-файлах. Ключи шифрования — в KMS, PGP, age, Vault. Файлы коммитятся в Git в зашифрованном виде.

```bash
# Шифрование файла
sops --encrypt --age age1... secret.yaml > secret.enc.yaml

# Расшифровка
sops --decrypt secret.enc.yaml
```

### Переменные окружения в CI/CD

Авторитетный источник: [CI/CD Secrets Management](../../CI-CD/DevSecOps/secrets_management.md)

Секреты хранятся в настройках CI/CD (GitLab CI Variables, GitHub Secrets), передаются в пайплайн как env vars. Подходит для токенов деплоя, credentials registry, SSH-ключей.

**Ограничения:** нет динамической генерации, ограниченный аудит, сложная ротация без прерывания пайплайна.

### Docker Secrets

Авторитетный источник: [Docker Secrets Management](../../Docker/Docker_security/secrets_management.md)

Для Docker Swarm и Docker Compose. Секреты монтируются в `/run/secrets/` внутри контейнера, не хранятся в image.

### Паттерн доставки секретов в K8s-приложения

Авторитетный источник: [Application Secrets Management](../../Kubernetes/Security/application_secrets_management.md)

InitContainer читает секреты из внешнего хранилища → записывает в shared emptyDir volume → приложение читает из volume (tmpfs).

### systemd-creds — секреты для systemd-сервисов

Для сервисов, запускаемых через systemd, используется встроенный механизм `systemd-creds`, который шифрует секреты ключом, привязанным к machine-id или TPM:

```bash
# Зашифровать секрет для текущей машины
echo "SuperSecret123" | systemd-creds encrypt db_password.cred -

# Использование в unit-файле
[Service]
LoadCredential=db_password:db_password.cred
ExecStart=/usr/bin/myapp --password-from-credential db_password
```

Секреты расшифровываются только на той машине, где они были зашифрованы. При копировании на другой хост расшифровка завершится ошибкой. Подходит для хранения паролей БД, токенов и ключей, необходимых локальным сервисам.

### SSH-ключи как секреты

Авторитетный источник: [SSH Key Management at Scale](../../Linux/Security/ssh/server/ssh_key_management_at_scale.md)

SSH-ключи требуют того же подхода к жизненному циклу, что и любые другие секреты:

- **Генерация:** использование алгоритмов Ed25519 (предпочтительно) или RSA 4096. Фраза-пароль (passphrase) обязательна для всех интерактивных ключей.
- **Хранение:** приватные ключи только на работающих станциях с шифрованным диском. Никогда — в Git или общих сетевых ресурсах.
- **Доставка:** `ssh-agent` + `keychain` для кэширования; AuthorizedKeysCommand для централизованного управления.
- **Ротация:** плановая (90/180 дней) и по событию (увольнение, подозрение на компрометацию).
- **Отзыв:** KRL (Key Revocation List) для централизованного отзыва без обхода по серверам.

### Управление TLS-сертификатами

Сертификаты являются секретами с ограниченным сроком действия. Для внутренней инфраструктуры целесообразно развёртывание локального CA:

- **Генерация:** Intermediate CA с ограниченным сроком жизни (1–2 года), корневой CA хранится офлайн.
- **Выдача:** automation через cert-manager (Kubernetes) или скрипты на базе OpenSSL для физических/виртуальных серверов.
- **Ротация:** автоматическая через ACME-клиенты (certbot) или cert-manager с напоминанием за 30 дней до истечения.
- **Отзыв:** CRL (Certificate Revocation List) или OCSP-responder для проверки статуса в реальном времени.

## Операции и команды

### Команды аудита (Sysadmin)

```bash
# Последние входы и использование sudo
lastlog
sudo sudoreplay -l

# Аудит доступа к файлам секретов
ausearch -k secrets -ts recent
auditctl -w /run/secrets/ -p rwxa -k secret_access

# Поиск секретов в истории Git
trufflehog git file:///path/to/repo --json
gitleaks detect --source /path/to/repo --verbose

# Проверка устаревших секретов Vault
vault list --format=json kv/metadata/production/ | jq '.[] | select(.data.ttl < 720h)'
```

### Инвентаризация и обнаружение (Operational Commands)

```bash
# Список всех активных leases в Vault (dynamic secrets)
vault list sys/leases/lookup/database/creds/

# Проверка, что K8s Secret смонтирован как tmpfs
kubectl exec <pod-name> -- mount | grep /etc/secrets
# → tmpfs on /etc/secrets type tmpfs (rw,relatime)

# Проверка переменных окружения контейнера на секреты
docker inspect --format='{{json .Config.Env}}' <container> | jq -r '.[]' | grep -iE 'pass|secret|key|token'

# Аудит RBAC для Secret: можно ли ServiceAccount читать все секреты в Namespace?
kubectl auth can-i list secrets --namespace=my-namespace --as=system:serviceaccount:my-namespace:my-sa
# → должно быть "no" — иначе over-provisioned SA

# Сканирование образа на секреты в слоях
docker save <image> > /tmp/image.tar && tar -xf /tmp/image.tar && grep -rn "secret\|password\|token" .
```

## Устранение неполадок

### Типичные ошибки и устранение неполадок

| Симптом | Причина | Решение |
|---------|---------|---------|
| `vault: permission denied` | Политика запрещает путь или метод аутентификации | `vault policy read <policy>`; проверить `path` и `capabilities` |
| `sops: no key found` | Отсутствует master key (age, PGP) в окружении | Указать `SOPS_AGE_KEY_FILE` или `--age` флаг |
| `kubectl get secret` возвращает base64 | Это ожидаемое поведение; секрет не расшифрован | Использовать `kubectl get secret <name> -o jsonpath='{.data.<key>}' \| base64 -d` |
| Secret не обновляется в Pod | Используется `subPath` или immutable Secret | Удалить Pod или отключить `immutable` |
| `podman secret inspect` пустой | Секрет создан из env-переменной, но переменная пуста | Проверить переменную окружения при создании |
| Динамический секрет не отзывается | Истёк TTL, но приложение кэширует connection | Перезапустить приложение или настроить connection refresh |
| Утечка в Git-истории | Секрет был закоммичен ранее | `git filter-repo` + принудительная ротация секрета |
| `sshd: refused connect from ...` | Отсутствует соответствующий ключ в authorized_keys или KRL | Проверить `~/.ssh/authorized_keys`, `/etc/ssh/sshd_config`, `krl.pub` |
| `trufflehog` не находит находки | Сканирование только текущего состояния, а не истории | Добавить `git file:///path/to/repo` для полного сканирования |
| Pre-commit hook не срабатывает | Нет прав на выполнение или symlink сбит | `ls -l .git/hooks/pre-commit` → должен указывать на `pre-commit` |

### Troubleshooting Vault Secret Rotation

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `vault kv undo: command not found` | Команда `kv undo` не существует | Использовать `vault kv get -version=N` + `vault kv put` для отката |
| `last_rotation` не возвращается | Поле называется `last_vault_rotation` | `vault read database/static-creds/<name>` — смотреть `last_vault_rotation` |
| `rotation_period must be at least 5 seconds` | `rotation_period` меньше минимума | Установить минимум 5s или использовать `rotation_schedule` |
| `orphaned rotation entry detected` | Ротация превысила лимит retries | Check `sys/rotation/orphans`; resolve error; re-register |
| `database plugin: connection refused during rotation` | БД недоступна | Проверить `connection_url`, сеть; увеличить `rotation_window` |
| `lease not renewable` при dynamic secret rotation | Lease просрочен | Увеличить `max_ttl`; проверить политику lease |

Подробнее — в **[Ротация секретов в Vault](../../Vault/guides/secret_rotation.md)**.

## Лучшие практики

### Рекомендации по выбору инструмента

| Масштаб | Рекомендация |
|---------|-------------|
| **Small project / pet-project** | CI/CD Variables (GitLab CI, GitHub Actions) |
| **GitOps-команда** | SOPS + age/PGP, хранение в Git |
| **Kubernetes-кластер (без внешнего хранилища)** | Sealed Secrets или SOPS + EncryptionConfiguration |
| **Enterprise / production** | HashiCorp Vault + динамические секреты + аудит |
| **Локальная инфраструктура (on-prem)** | Vault + SSH CA + systemd-creds |

### Политика ротации

- **Динамические секреты:** предпочтительнее статических. Настраивайте dynamic roles с коротким TTL (1–4 часа).
- **Static Secrets (KV v2):** ротация каждые 90–180 дней; используйте версионирование для отката.
- **Root credentials:** ротация после onboarding Database Secrets Engine.
- **Transit keys:** используйте `auto_rotate_period` (минимум 1 час).
- **SSH CA:** overlapping CA keys during rotation; удаляйте старые роли после истечения TTL.
- **TLS certificates:** автоматическая ротация через ACME (certbot) или cert-manager с напоминанием за 30 дней.
- **Секреты сборки (build-time):** существуют только во время пайплайна; не переиспользуйте для runtime.

Подробнее — в **[Ротация секретов в Vault](../../Vault/guides/secret_rotation.md)**.

### Аудит и соответствие (Audit & Compliance)

- **Логирование доступа:** каждое чтение секрета фиксируется (Vault Audit Devices, аудит CI-системы, системные логи). Без аудита невозможно расследовать инцидент.
- **Инвентаризация:** что является секретом, где используется, кто владелец, когда ротировался, используется ли он вообще (stale secrets = риск).
- **Соответствие:** PCI DSS (требует ротации и ограничения доступа к ключам), российские регуляторные требования (152-ФЗ для персональных данных, ФСТЭК/ФСБ для ключей).
- **Регулярный review:** пересмотр политик доступа и вывод из эксплуатации неиспользуемых секретов.

### Антипаттерны

Подробный разбор распространённых ошибок: [Антипаттерны управления секретами](../../Vault/common_antipatterns.md).

Ключевые антипаттерны:
- **Secret Zero:** хранение статического master-ключа в Git/переменной окружения.
- **ENV-секреты в production:** секреты в `ENV` видны в `docker inspect`, `/proc/*/environ`, дампах памяти.
- **Отсутствие ротации:** статические секреты действуют бессрочно.
- **Shared secrets:** один и тот же секрет для всех сред/сервисов.

### Резервное копирование и аварийное восстановление

- **Ключевой принцип:** секреты должны восстанавливаться быстрее, чем истекают их TTL.
- **Vault:** снапшоты Raft-хранилища + внешнее хранилище ключей (KEK). Восстановление — развёртывание нового кластера из снапшота и ввод unseal-ключей.
- **SSH CA:** резервная копия корневого ключа в зашифрованном виде (offline HSM или зашифрованный носитель). При компрометации — перевыпуск всех сертификатов.
- **Локальные секреты:** systemd-creds привязаны к machine-id; при восстановлении системы на новый хост требуется повторное шифрование. Для переноса используйте мастер-ключ и инструмент `systemd-creds decrypt`.

### Процедуры аварийного доступа (Break-glass)

При отказе основных механизмов доставки секретов:

1.  **Официальный канал:** письменный запрос в команду безопасности/DevOps с указанием причины, времени и объёма требуемого доступа.
2.  **Временный доступ:** выдача секрета через защищённый канал (Signal/Keybase, личная встреча, encrypted email) с фиксацией в журнале инцидентов.
3.  **Автоматическое оповещение:** триггер в SIEM/мониторинг на факт аварийного доступа.
4.  **Ограничение по времени:** доступ выдаётся на минимальный срок (1–4 часа) с автоматическим отзывом.
5.  **Пост-анализ:** после восстановления штатного режима — полная ротация всех секретов, к которым был получен доступ, и аудит действий.

## Дополнительная информация

### Динамические секреты (Vault)

Vault генерирует временные credentials по запросу (БД, RabbitMQ и др.). После истечения TTL — автоматический отзыв. Преимущества:

- Уникальные credentials на каждый запрос
- Автоматическая ротация и отзыв
- Минимизация blast radius при компрометации

Примеры: [динамические секреты PostgreSQL](../../Vault/concepts.md), [динамические секреты RabbitMQ](../../Vault/concepts.md).

Подробнее о механизмах ротации — в **[Ротация секретов в Vault](../../Vault/guides/secret_rotation.md)**.

### Жизненный цикл и управление Key Escrow

Для криптографических ключей (TLS CA, JWT signing, SSH CA) применяется **Key Escrow** — механизм доверенного хранения копий ключей третьей стороной. Используется Shamir's Secret Sharing (разделение на N частей, достаточно K):

- **Root CA:** хранится офлайн; passphrase разделяется через `ssss` (2-of-3) на USB-носителях в разных локациях.
- **Service keys:** хранятся в Vault Transit Engine с `auto_rotate_period`; резервные копии — в encrypted offline storage.

Подробнее — в **[Key Escrow Policy](./key_escrow_policy.md)**.

### Связанные концепции

- **[Антипаттерны управления секретами](../../Vault/common_antipatterns.md)** — подробный разбор распространенных ошибок.
- [CI/CD Secrets Management](../../CI-CD/DevSecOps/secrets_management.md) — секреты в пайплайнах
- [Docker Secrets Management](../../Docker/Docker_security/secrets_management.md) — секреты в контейнерах
- [GitOps Secrets Encryption](../../GitOps/secrets_encryption.md) — SOPS, Sealed Secrets, Vault, External Secrets
- **[Key Escrow Policy](./key_escrow_policy.md)** — политика хранения копий ключей, Shamir's Secret Sharing.
- [Kubernetes Secrets](../../Kubernetes/Base/secrets/secrets_basics.md) — создание, хранение, безопасность
- [Vault overview](../../Vault/overview.md) — централизованное управление секретами
- [Zero Trust к управлению секретами](../../Vault/zero_trust.md) — подход Zero Trust
- [GPG и OpenPGP](../../Linux/Security/Tools/gpg_and_openpgp.md) — криптография и подписи
- [Управление SSH-ключами](../../Linux/Security/ssh/server/ssh_key_management_at_scale.md) — жизненный цикл SSH-ключей
