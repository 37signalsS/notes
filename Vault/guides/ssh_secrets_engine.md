# SSH Secrets Engine в Vault

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**SSH Secrets Engine** — движек секретов HashiCorp Vault для управления SSH-аутентификацией. Поддерживает два режима: OTP (одноразовые пароли) и SSH CA (подписанные сертификаты).

**OTP (One-Time Password)** — одноразовый пароль, генерируемый Vault для SSH-аутентификации. Действителен для одной сессии, отзывается после использования или истечения TTL.

**SSH CA (Certificate Authority)** — режим, при котором Vault выступает как CA для SSH-сертификатов. Подписывает публичные ключи пользователей/хостов; целевой сервер проверяет подпись через `TrustedUserCAKeys`.

**vault-ssh-helper** — утилита HashiCorp, устанавливаемая на целевой SSH-сервер. Работает как PAM- илиAuthorizedKeysCommand-модуль для проверки OTP или сертификата через Vault API.

**Principals (Принципалы)** — список пользователей/хостов, которым разрешён доступ по сертификату. Проверяются при выдаче сертификата.

**Key Type (key_type)** — тип ключа для CA: `ca` (CA mode) или `otp` (OTP mode). Для CA-генерации ключа используется `ssh/config/ca` с `generate_signing_key`.

**cert_type** — тип сертификата при подписи: `user` (по умолчанию) или `host`.

**default_user** — пользователь на целевом хосте, к которому разрешено подключаться.

**allowed_users** — явный список разрешённых пользователей (через запятую).

**allowed_cidrs / cidr_list** — IP-адреса, с которых разрешено запрашивать credentials.

**default_extensions** — расширения SSH-сертификата (например, `permit-pty`).

**TTL / max_ttl** — срок жизни выписанного сертификата и его максимальный предел.

**Lease** — запись в Vault, связанная с OTP (отзывается после использования) или сертификатом.

**KRL (Key Revocation List)** — файл с отозванными SSH-ключами/сертификатами.

## Архитектура и принцип работы

### Режимы работы

| Режим | Назначение | Подходит для |
| :--- | :--- | :--- |
| **OTP** | Одноразовые пароли | Временный/нерегулярный доступ |
| **SSH CA** | Подписанные сертификаты | Постоянный доступ, масштабирование |

### Жизненный цикл OTP

1. Пользователь запрашивает OTP: `vault write ssh/creds/role ip=10.0.1.50`
2. Vault возвращает пароль с lease_id и TTL (по умолчанию 600s)
3. Пользователь подключается и вводит пароль
4. SSH-сервер через PAM вызывает `vault-ssh-helper`
5. Helper проверяет пароль через Vault API
6. Vault отзывает пароль (одноразовое использование)
7. SSH-сессия устанавливается

### Жизненный цикл SSH CA

1. Пользователь генерирует ключевую пару: `ssh-keygen -t ed25519`
2. Публичный ключ отправляется в Vault: `vault write -f ssh/sign/role public_key=@key.pub`
3. Vault возвращает подписанный сертификат с TTL и principals
4. Пользователь подключается: `ssh -i key -i key-cert.pub user@host`
5. SSH-сервер проверяет подпись CA через `TrustedUserCAKeys` и principals

### Параметры роли (Vault 1.16+)

| Параметр | OTP-роль | CA-роль | Описание |
| :--- | :--- | :--- | :--- |
| `key_type` | `otp` (required) | `ca` (required) | Тип credentials |
| `default_user` | да | да | Пользователь на хосте |
| `allowed_users` | да | да | Список разрешённых пользователей |
| `cidr_list` | да | — | IP-адреса для запроса OTP |
| `allowed_cidrs` | — | да | IP-адреса для выдачи сертификата |
| `allowed_users_template` | опц | опц | Шаблонизация allowed_users (Identity) |
| `default_user_template` | опц | опц | Шаблонизация default_user |
| `default_extensions` | — | да | Extensions: `permit-pty`, `permit-port-forwarding` |
| `default_extensions_template` | — | опц | Шаблонизация default_extensions |
| `ttl` | опц | да | TTL сертификата (например, `8h`) |
| `max_ttl` | опц | да | Максимальный TTL |
| `max_remotes` | опц | да | Количество хостов в сертификате (0 = неограниченно) |
| `allow_user_certificates` | — | да | Разрешить user-сертификаты |
| `allow_host_certificates` | — | да | Разрешить host-сертификаты |
| `key_type` (CA keygen) | — | — | В `ssh/config/ca`: `rsa`, `ec`, `ed25519` |

### Ограничения и лимиты

| Лимит | Значение | Файл/параметр |
| :--- | :--- | :--- |
| max_request_size | 32 MiB | listener.tcp |  |
| max_request_duration | 90s | listener.tcp |
| Certificate TTL | по умолчанию 600s (OTP), 7200s (CA) | role config |
| max_remotes | 0 (unlimited) или N | role `max_remotes` |
| CA key types | rsa, ec, ed25519 | `ssh/config/ca` generate_signing_key |
| Vault API | /v1/ssh/* | — | [SSH API](https://developer.hashicorp.com/vault/api-docs/secret/ssh) |

## Предварительные требования

- Vault 1.16+
- SSH-клиент/сервер с поддержкой сертификатов (OpenSSH 6.2+; рекомендуется 9.8+ для PQC)
- `vault-ssh-helper` установлен на целевых хостах
- Network ACL: доступ к Vault API (порт 8200) с хостов и клиентов
- File audit device с ротацией логов (см. [audit_log_analysis.md](./audit_log_analysis.md))

## Настройка и развертывание

### Сценарий 1: OTP-режим для временного доступа

#### Шаг 1: Включение SSH Secrets Engine

```bash
vault secrets enable ssh
# → Success! Enabled the ssh secrets engine at: ssh/
```

#### Шаг 2: Создание OTP-роли

```bash
vault write ssh/roles/one-time-role \
    key_type=otp \
    default_user=ubuntu \
    cidr_list="10.0.0.0/16,192.168.1.0/24"
# → Success! Data written to: ssh/roles/one-time-role
```

Параметры:
- `key_type=otp` — режим одноразовых паролей
- `default_user=ubuntu` — пользователь на хосте
- `cidr_list` — разрешённые IP для запроса OTP

#### Шаг 3: Получение OTP

```bash
vault write ssh/creds/one-time-role ip=10.0.1.50
# → Key             Value
# → lease_id        ssh/creds/one-time-role/abc123...
# → lease_duration  600
# → password        7d92b1c4e6
# → username        ubuntu
```

#### Шаг 4: Настройка целевого SSH-сервера (OTP via PAM)

Установка `vault-ssh-helper`:

```bash
# Linux (amd64)
curl -L -o vault-ssh-helper.zip "https://releases.hashicorp.com/vault-ssh-helper/0.2.4/vault-ssh-helper_0.2.4_linux_amd64.zip"
unzip vault-ssh-helper.zip
sudo mv vault-ssh-helper /usr/local/bin/
sudo chmod +x /usr/local/bin/vault-ssh-helper
```

Настройка PAM (`/etc/pam.d/sshd`):

```
auth requisite pam_exec.so quiet /usr/local/bin/vault-ssh-helper -config=/etc/vault-ssh-helper/config.hcl
auth optional pam_unix.so not_set_pass
```

Конфиг `vault-ssh-helper` (`/etc/vault-ssh-helper/config.hcl`):

```hcl
vault_addr = "https://vault.example.com:8200"
ssh_mount_point = "ssh"
tls_skip_verify = false
ca_cert = "/etc/vault-ssh-helper/ca.crt"
```

Настройка `sshd_config`:

```
ChallengeResponseAuthentication yes
UsePAM yes
PasswordAuthentication no
```

```bash
sudo systemctl restart sshd
```

### Сценарий 2: SSH CA для сертификатной аутентификации

#### Шаг 1: Включение SSH Secrets Engine

```bash
vault secrets enable ssh
```

#### Шаг 2: Генерация CA-ключа в Vault

```bash
# Автоматическая генерация CA-ключа (RSA по умолчанию)
vault write -f ssh/config/ca
# → Key             Value
# → generate_signing_key  true
# → public_key      ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC...

# Или импорт существующего CA-ключа
# vault write ssh/config/ca public_key=@ca.pub private_key=@ca.key
```

Параметры CA:
- `generate_signing_key` (bool: true) — если true, Vault генерирует RSA-ключ; если false, требуется `public_key` и `private_key`
- `key_type` — `ssh-rsa` (default), или другой OpenSSH key type identifier для `generate_signing_key=true`
- `key_bits` — размер ключа (2048 default для RSA)

#### Шаг 3: Создание роли CA

```bash
vault write ssh/roles/user-role \
    key_type=ca \
    default_user=ubuntu \
    allowed_users="ubuntu,admin,deploy" \
    default_extensions={"permit-pty":""} \
    ttl=8h \
    max_ttl=24h \
    allowed_cidrs="10.0.0.0/16,192.168.1.0/24"
# → Success! Data written to: ssh/roles/user-role
```

Параметры CA-роли:
- `key_type=ca` — режим центра сертификации (обязательно!)
- `allowed_users` — список разрешённых пользователей
- `default_extensions` — extensions SSH-сертификата (например, `permit-pty` для PTY)
- `ttl` / `max_ttl` — срок действия сертификата
- `allowed_cidrs` — IP-ограничения
- `max_remotes` — количество хостов (0 = без ограничений)
- `allow_user_certificates` — разрешить user-сертификаты (default true)
- `allow_host_certificates` — разрешить host-сертификаты (default false)

#### Шаг 4: Подпись публичного ключа

```bash
# Генерация ключевой пары на клиенте
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_vault

# Подпись публичного ключа через Vault
vault write -f ssh/sign/user-role \
    public_key=@/path/to/id_ed25519_vault.pub \
    valid_principals="ubuntu,admin" \
    ttl=8h
# → Key             Value
# → signed_key      ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC...
# → serial_number   0123456789
# → valid_principals ["ubuntu" "admin"]
# → lease_id        ssh/sign/user-role/abc123...
# → lease_duration  28800
```

#### Шаг 5: Настройка SSH-сервера для доверия CA

```bash
# Получение CA-ключа из Vault
vault read -field=public_key ssh/config/ca > /etc/ssh/trusted-user-ca-keys.pub
```

Настройка `sshd_config`:

```
TrustedUserCAKeys /etc/ssh/trusted-user-ca-keys.pub
```

Для host certificates (опционально):

```
# Host certificate CA (отдельный файл)
TrustedHostCAKeys /etc/ssh/vault_host_ca.pub
```

```bash
sudo systemctl restart sshd
```

#### Шаг 6: Подключение с сертификатом

```bash
# Сохранить сертификат рядом с ключом
vault write -f ssh/sign/user-role public_key=@/path/to/id_ed25519_vault.pub > id_ed25519_vault-cert.pub

# Подключение с использованием cert
ssh -i ~/.ssh/id_ed25519_vault -i ~/.ssh/id_ed25519_vault-cert.pub ubuntu@host
```

### Сценарий 3: Динамические SSH-сертификаты для CI/CD

CI/CD-раннеру нужен временный доступ к production-серверам. Используется SSH CA с коротким TTL:

```bash
# В пайплайне: запрос сертификата через JWT
vault write -f ssh/sign/ci-runner \
    public_key=@/tmp/id_rsa.pub \
    valid_principals="deploy" \
    ttl=1h
```

```yaml
# .gitlab-ci.yml
stages:
  - deploy

deploy:
  stage: deploy
  script:
    - |
      # Генерация ключевой пары
      ssh-keygen -t rsa -b 4096 -f /tmp/id_rsa -N ""
      # Запрос подписанного сертификата
      CERT=$(vault write -f ssh/sign/ci-runner public_key=@/tmp/id_rsa.pub -format=json | jq -r '.data.signed_key')
      echo "$CERT" > /tmp/id_rsa-cert.pub
      # Деплой через SSH с сертификатом
      ssh -i /tmp/id_rsa -i /tmp/id_rsa-cert.pub deploy@prod-server "systemctl reload myapp"
```

### Сценарий 4: Управление хостовыми ключами (Host Keys)

Vault может выступать как CA для хостовых SSH-ключей, обеспечивая единую инфраструктуру доверия:

```bash
# Создание роли для хостов
vault write ssh/roles/host-role \
    key_type=ca \
    default_user=root \
    allowed_users="root,ubuntu" \
    ttl=720h \
    max_ttl=8760h \
    allow_host_certificates=true

# Подпись хостового ключа
vault write -f ssh/sign/host-role \
    public_key=@/etc/ssh/ssh_host_ed25519_key.pub \
    cert_type=host \
    valid_principals="prod-server-01,prod-server-01.example.com"
```

На клиенте (`~/.ssh/known_hosts`):

```
@cert-authority *.example.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC...
```

### Сценарий 5: Ротация CA-ключа

Периодическая ротация CA-ключа снижает риск при компрометации:

```bash
# 1. Генерация нового CA-ключа в Vault
vault write -f ssh/config/ca
# → public_key <new_ca_pub_key>

# 2. Распространение нового CA-ключа на все серверы
vault read -field=public_key ssh/config/ca > /etc/ssh/trusted-user-ca-keys-v2.pub
ansible all -m copy -a "src=/etc/ssh/trusted-user-ca-keys-v2.pub dest=/etc/ssh/trusted-user-ca-keys-v2.pub mode=0644" ansible all -m copy -a "src=/etc/ssh/trusted-user-ca-keys-v2.pub dest=/etc/ssh/trusted-user-ca-keys-v2.pub mode=0644"

# 3. Добавление второго CA-ключа в sshd_config (dual CA period)
# TrustedUserCAKeys /etc/ssh/trusted-user-ca-keys.pub /etc/ssh/trusted-user-ca-keys-v2.pub
ansible all -m lineinfile -a "path=/etc/ssh/sshd_config dest=/etc/ssh/sshd_config regexp='^TrustedUserCAKeys' line='TrustedUserCAKeys /etc/ssh/trusted-user-ca-keys.pub /etc/ssh/trusted-user-ca-keys-v2.pub' mode=0644"

# 4. Перезапуск SSH на всех серверах
ansible all -m systemd -a "name=sshd state=restarted"

# 5. После истечения TTL старых сертификатов — удаление старого CA-ключа
# (отдельный playbook для финального cleanup)
```

### Сценарий 6: Ограничение доступа по principals

Принцип наименьших привилегий — разные пользователи/сервисы получают доступ только к разрешённым хостам:

```bash
# Роль для deploy-пользователя (только prod-хосты)
vault write ssh/roles/deploy-role \
    key_type=ca \
    default_user=deploy \
    allowed_users="deploy" \
    default_extensions={"permit-pty":""} \
    ttl=4h \
    max_ttl=8h \
    allowed_cidrs="10.0.1.0/24"

# Роль для admin (все хосты)
vault write ssh/roles/admin-role \
    key_type=ca \
    default_user=admin \
    allowed_users="admin" \
    ttl=1h \
    max_ttl=4h
```

Политика Vault для ограничения principals:

```hcl
path "ssh/sign/deploy-role" {
  capabilities = ["update"]
  allowed_parameters = {
    "valid_principals" = ["deploy"]
  }
}
```

## Операции и команды

### CLI команды для управления SSH Secrets Engine

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `vault secrets enable ssh` | Включить движок | `vault secrets enable ssh` |
| `vault write ssh/roles/<role> ...` | Создать роль | `vault write ssh/roles/otp-role key_type=otp ...` |
| `vault write ssh/creds/<role> ip=...` | Получить OTP | `vault write ssh/creds/role ip=10.0.1.50` |
| `vault write -f ssh/config/ca` | Создать CA-ключ | `vault write -f ssh/config/ca` |
| `vault read -field=public_key ssh/config/ca` | Получить CA-ключ | `vault read -field=public_key ssh/config/ca` |
| `vault write -f ssh/sign/<role> ...` | Подписать ключ | `vault write -f ssh/sign/role public_key=@key.pub` |
| `vault write ssh/config/ca ...` | Импорт CA-ключа | `vault write ssh/config/ca public_key=@ca.pub private_key=@ca.key` |
| `vault list ssh/roles` | Список ролей | `vault list ssh/roles` |
| `vault read ssh/roles/<role>` | Параметры роли | `vault read ssh/roles/user-role` |
| `vault delete ssh/roles/<role>` | Удалить роль | `vault delete ssh/roles/old-role` |
| `vault lease lookup ssh/creds/...` | Инфо о lease | `vault lease lookup ssh/creds/role/abc123` |
| `vault lease revoke ssh/creds/...` | Отозвать lease | `vault lease revoke ssh/creds/role/abc123` |

### API эндпоинты

| Метод | Путь | Описание | auth |
| :--- | :--- | :--- | :--- |
| `POST` | `/ssh/config/ca` | Генерация/импорт CA-ключа | `root` |
| `GET` | `/ssh/config/ca` | Просмотр CA-ключа | `root` |
| `POST` | `/ssh/roles/:role` | Создать роль | `root` |
| `GET` | `/ssh/roles/:role` | Просмотр роли | `root` |
| `LIST` | `/ssh/roles` | Список ролей | `root` |
| `DELETE` | `/ssh/roles/:role` | Удалить роль | `root` |
| `POST` | `/ssh/creds/:role` | Получить OTP (OTP-роль) | `update` |
| `POST` | `/ssh/sign/:role` | Подписать ключ (CA-роль) | `update` |
| `GET` | `/ssh/lookup` | Поиск сертификата по serial | `root` |
| `POST` | `/ssh/revoke` | Отозвать сертификат | `root` |
| `GET` | `/ssh/tsr` | Public key + CA configuration | — |

### Мониторинг и аудит

```bash
# Проверка смонтированных движков
vault secrets list
# → ssh/  ssh

# Просмотр выданных сертификатов (audit log)
sudo tail -f /var/log/vault/audit.log | jq 'select(.path=="ssh/sign/user-role")'

# Проверка активных OTP-сессий
vault lease lookup ssh/creds/one-time-role/abc123...

# Отзыв lease
vault lease revoke ssh/creds/one-time-role/abc123...

# Поиск сертификата по serial number
vault write ssh/lookup serial_number=0123456789

# Отзыв сертификата
vault write ssh/revoke serial_number=0123456789
```

### Аудиторские метрики (audit log)

```bash
# Операции с CA-ключами
jq 'select(.path=="ssh/config/ca")' /var/log/vault/audit.log

# Выдача сертификатов
jq 'select(.path=="ssh/sign/")' /var/log/vault/audit.log

# OTP-запросы
jq 'select(.path=="ssh/creds/")' /var/log/vault/audit.log

# Медленные операции подписи (> 100ms)
jq 'select(.type=="response" and (.response.duration > 100) and (.request.path | startswith("ssh/sign")))' /var/log/vault/audit.log
```

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `vault-ssh-helper not found` | Бинарник не в PATH для PAM | Проверить `/usr/local/bin/vault-ssh-helper`, `pam_exec.so` path |
| `OTP verification failed` | Vault недоступен или helper misconfiguration | Проверить `vault_addr`, `ssh_mount_point`, TLS сертификаты; логи `/var/log/vault-ssh-helper.log` |
| `Bad permissions` на TrustedUserCAKeys | Файл слишком открыт | `chmod 644 /etc/ssh/trusted-user-ca-keys.pub`, `chown root:root` |
| `Error: role not found` | Роль не создана или неверный путь | `vault list ssh/roles`, проверить mount path |
| `Principal not authorized` | Пользователь не в `allowed_users` | Добавить пользователя в `allowed_users` или `valid_principals` |
| `Certificate expired` | TTL истёк | Увеличить TTL (`ttl=24h`) или запросить новый сертификат |
| `sign: public key required` | Не передан `public_key` | `vault write -f ssh/sign/role public_key=@key.pub` |
| `max_remotes exceeded` | Превышено количество хостов в сертификате | Установить `max_remotes=0` или увеличить лимит |
| `OCSP/CRL check failed` | KRL не обновляется или revoked key | Обновить KRL, настроить `RevokedKeys` в sshd_config |
| `audit device blocking requests` | File audit device медленно пишет | Использовать выделенный том, настроить logrotate; [см. аудит](./audit_log_analysis.md) |
| `vault write ssh/config/ca` возвращает error | `generate_signing_key=true` с неверным `key_type` CA-ключа | Использовать `ssh-rsa` (default, поддерживается) для `generate_signing_key=true`, или импортировать существующий CA-ключ через `public_key`/`private_key` |
| `key_type=ed25519 in role` | `key_type=ed25519` недопустим для ролей; роли SSH используют только `ca` или `otp` | Использовать `key_type=ca` для CA-ролей |
| `Permission denied (publickey)` | cert_type mismatch | Для host-сертификатов: `cert_type=host`, `TrustedHostCAKeys` |
| `connection refused` к Vault | Network/ACL между хостом и Vault | Проверить firewall, DNS, TLS endpoint |
| `vault-ssh-helper cert verification failed` | wrong ca_cert or tls_skip_verify | Убедиться что `ca_cert` указывает на корневой CA Vault, `tls_skip_verify=false` |

### Отладка vault-ssh-helper

```bash
# Запуск в debug-режиме
/usr/local/bin/vault-ssh-helper -config=/etc/vault-ssh-helper/config.hcl -log-level=debug 1>&1

# Проверка connectivity к Vault
curl -k https://vault.example.com:8200/v1/sys/health

# Проверка PAM конфигурации
sudo pamtester sshd <username> authenticate
```

## Лучшие практики

1. **Короткий TTL:** Настраивайте TTL сертификатов 1–24 часа (4–8h для пользователей, 1h для CI/CD). [Vault best practices](https://developer.hashicorp.com/vault/docs/internals/recommended-patterns#adjust-the-default-lease-time)
2. **Principals по умолчанию:** Всегда указывайте `default_user` и `allowed_users`. Избегайте ролей с открытым доступом (`*`).
3. **CA-ключ:** Генерируйте CA-ключ внутри Vault (`generate_signing_key=true`). Приватный ключ CA никогда не покидает Vault.
4. **Ротация CA:** Планируйте ротацию CA-ключа раз в 6–12 месяцев с overlapping периодом (dual CA).
5. **CIDR-ограничения:** Ограничивайте `cidr_list` (OTP) и `allowed_cidrs` (CA).
6. **Audit:** Включите audit device для отслеживания всех операций выдачи SSH-сертификатов. [Audit log analysis](./audit_log_analysis.md)
7. **vault-ssh-helper:** В production используйте `tls_skip_verify=false` и явный `ca_cert`.
8. **Systemd hardening:** Настройте `LimitNOFILE`, `LimitMEMLOCK`, `OOMScoreAdjust` для `vault-ssh-helper`. [Installation guide](./vault_installation.md)
9. **Host certificates:** Используйте `cert_type=host` для host-сертификатов и `TrustedHostCAKeys` на клиентах.
10. **max_remotes=0:** Для больших кластеров установите `max_remotes=0` (unlimited hosts in cert).
11. **CRL/KRL:** Настройте `RevokedKeys` в sshd_config для отзыва скомпрометированных сертификатов.
12. **Vault Agent:** Используйте [Vault Agent](./vault_agent/basics.md) для авто-аутентификации и кэширования в CI/CD пайплайнах.
13. **Network isolation:** Изолируйте CA-ключ: Vault HA с performance standby для чтения. [Performance](./performance_tuning.md)
14. **SSH-конфигурация клиента:** Настройте `~/.ssh/config` с `CertificateFile` и `IdentityAgent` для удобства.

## Ограничения и известные проблемы

- **OTP и HA:** OTP-запросы обслуживает только active-узел. Standby-узлы возвращают 307 redirect. [Performance & replication](./performance_and_replication.md)
- **vault-ssh-helper и systemd:** Бинарник должен быть в PATH для PAM. Частая ошибка — `pam_exec.so` не находит вспомогательную утилиту.
- **SSH-клиенты:** Некоторые клиенты (старые OpenSSH < 6.2) не поддерживают сертификаты.
- **CRL/KRL:** Vault автоматически генерирует CRL, но клиенты должны периодически обновлять KRL (`ssh -o UpdateHostKeys=yes`).
- **OTP нагрузка:** OTP-режим создаёт нагрузку на Vault при каждом подключении (запрос API + audit запись). Для high-load — используйте CA-режим.
- **Certificate TTL:** Максимальный TTL для CA-сертификатов ограничен `max_ttl` роли.
- **max_remotes:** По умолчанию 0 (без ограничений), но некоторые клиенты могут иметь проблемы с большим количеством principals.
- **Dynamic keys removed:** Функция динамических ключей SSH удалена в Vault 1.12. Используйте CA-режим вместо этого.  |
- **Audit device overhead:** Каждая операция выдачи сертификата/ OTP создаёт audit запись. Используйте выделенный том для audit логов с logrotate. [Audit log analysis](./audit_log_analysis.md)
- **Network dependency:** `vault-ssh-helper` требует доступа к Vault API для каждой OTP-аутентификации. CA-режим требует доступа только при выдаче сертификата.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[Основные концепции Vault](../concepts.md)** — движки секретов, токены, lease.
*   **[PKI/CA продвинутые сценарии](./pki_ca_advanced.md)** — Intermediate CA, ACME, CRL/OCSP (для сравнения с SSH CA).
*   **[Ротация секретов](./secret_rotation.md)** — стратегии ротации SSH-ключей и CA.
*   **[Zero Trust](../zero_trust.md)** — роль SSH CA в архитектуре нулевого доверия.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему статические SSH-ключи — антипаттерн.
*   **[Анализ audit логов](./audit_log_analysis.md)** — log rotation, SIEM integration, forensic analysis.
*   **[Производительность и тюнинг](./performance_tuning.md)** — мониторинг, TTL, нагрузка.
*   [SSH Secrets Engine (Vault docs)](https://developer.hashicorp.com/vault/docs/secrets/ssh)
*   [SSH Secrets Engine API (Vault docs)](https://developer.hashicorp.com/vault/api-docs/secret/ssh)
*   [vault-ssh-helper releases](https://releases.hashicorp.com/vault-ssh-helper/)
*   [SSH Certificate Authentication](../Linux/Security/ssh/server/ssh_certificate_authentication.md) — инфраструктура SSH CA