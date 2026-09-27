# SSH Secrets Engine в Vault

## Определения

**SSH Secrets Engine** — движок секретов HashiCorp Vault, который управляет жизненным циклом SSH-ключей и сертификатов. Он позволяет выдавать краткоживущие SSH-credentials (пароли или сертификаты) без хранения долгоживущих приватных ключей на серверах.

**OTP (One-Time Password)** — одноразовый пароль, генерируемый Vault для SSH-аутентификации. Пароль действителен только для одной сессии и автоматически отзывается после использования или истечения TTL.

**SSH CA (Certificate Authority)** — режим работы SSH Secrets Engine, при котором Vault выступает как центр сертификации для SSH-сертификатов. Vault подписывает публичные ключи пользователей/хостов, и целевой сервер проверяет подпись через доверенный CA-ключ.

**vault-ssh-helper** — утилита от HashiCorp, которая устанавливается на целевой SSH-сервер. Она работает как PAM-модуль и обращается к Vault API для проверки подлинности OTP-пароля или валидации сертификата.

**Principals** — список идентификаторов (пользователей, групп), которым разрешён доступ по SSH-сертификату. При выдаче сертификата Vault проверяет, что запрашиваемый principal указан в роли.

## Основные концепции

### Архитектура SSH Secrets Engine

SSH Secrets Engine имеет два режима работы:

1. **OTP (One-Time Password):** Vault генерирует одноразовый пароль для конкретного хоста. Пользователь вводит пароль при SSH-подключении. На целевом хосте PAM вызывает `vault-ssh-helper`, который проверяет пароль через Vault API и отзывает его после успешной аутентификации.

2. **SSH CA (Certificate Authority):** Vault подписывает публичный ключ пользователя, создавая SSH-сертификат с ограниченным TTL. Пользователь подключается по сертификату (`ssh -i cert.pub user@host`). На хосте настроен `TrustedUserCAKeys`, указывающий на CA-ключ Vault.

### Жизненный цикл OTP

1. Пользователь запрашивает OTP: `vault write ssh/creds/one-time-role ip=10.0.1.50`
2. Vault возвращает одноразовый пароль и lease_id
3. Пользователь подключается: `ssh user@10.0.1.50` и вводит пароль
4. SSH-сервер через PAM вызывает `vault-ssh-helper`
5. `vault-ssh-helper` отправляет запрос в Vault для проверки пароля
6. Vault подтверждает подлинность и отзывает пароль
7. Сессия SSH устанавливается

### Жизненный цикл SSH CA

1. Пользователь генерирует ключевую пару: `ssh-keygen -t ed25519`
2. Публичный ключ отправляется в Vault: `vault write -f ssh/sign/user-role public_key=@/path/to/id_ed25519.pub`
3. Vault возвращает подписанный сертификат с указанным TTL и principals
4. Пользователь подключается: `ssh -i cert.pub user@host`
5. SSH-сервер проверяет подпись CA-ключа Vault и principals в сертификате

### Сравнение режимов

| Критерий | OTP | SSH CA |
| :--- | :--- | :--- |
| **Аутентификация** | Пароль (ввод вручную) | Сертификат (автоматическая) |
| **Требования к клиенту** | Любой SSH-клиент | Поддержка сертификатов (`ssh -i`) |
| **Требования к серверу** | PAM + vault-ssh-helper | `TrustedUserCAKeys` в sshd_config |
| **Аудит** | Каждая аутентификация логируется | Сертификат содержит identity, срок действия |
| **Масштабирование** | Медленнее (запрос к Vault на каждое подключение) | Быстрее (проверка локальная, после выдачи) |
| **Отзыв** | Автоматический (OTP одноразовый) | Требует CRL/Delta-CRL или короткий TTL |

## Практические сценарии

### Сценарий 1: Настройка OTP для временного доступа

#### Шаг 1: Включение SSH Secrets Engine

```bash
# Включение движка на стандартном пути
vault secrets enable ssh

# Или на кастомном пути
vault auth enable -path=ssh-otp ssh
```

#### Шаг 2: Создание роли OTP

```bash
vault write ssh/roles/one-time-role \
    key_type=otp \
    default_user=ubuntu \
    cidr_list="10.0.0.0/16,192.168.1.0/24"
```

Параметры роли:
- `key_type=otp` — режим одноразовых паролей
- `default_user` — пользователь на целевом хосте
- `cidr_list` — IP-адреса, с которых разрешено запрашивать OTP

#### Шаг 3: Получение OTP для подключения

```bash
vault write ssh/creds/one-time-role ip=10.0.1.50
# → Key             Value
# → lease_id        ssh/creds/one-time-role/abc123...
# → lease_duration  600
# → password        7d92b1c4e6
# → username        ubuntu
```

#### Шаг 4: Настройка целевого SSH-сервера

Установка `vault-ssh-helper` на целевой хост:

```bash
# Ubuntu/Debian
wget https://releases.hashicorp.com/vault/2.0.0/vault_2.0.0_linux_amd64.zip
unzip vault_2.0.0_linux_amd64.zip
sudo mv vault /usr/local/bin/
sudo chmod +x /usr/local/bin/vault
```

Настройка PAM (`/etc/pam.d/sshd`):

```
auth requisite pam_exec.so quiet /usr/local/bin/vault-ssh-helper -config=/etc/vault-ssh-helper/config.hcl
auth optional pam_unix.so not_set_pass
```

Настройка `vault-ssh-helper` (`/etc/vault-ssh-helper/config.hcl`):

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
PasswordAuthentication no  # Отключить обычные пароли
```

Перезапуск SSH:

```bash
sudo systemctl restart sshd
```

### Сценарий 2: Настройка SSH CA для сертификатной аутентификации

#### Шаг 1: Включение SSH Secrets Engine в режиме CA

```bash
vault secrets enable ssh
```

#### Шаг 2: Создание роли CA

```bash
vault write ssh/roles/user-role \
    key_type=ca \
    default_user=ubuntu \
    allowed_users="ubuntu,admin,deploy" \
    default_extensions={"permit-pty":""} \
    ttl=8h \
    max_ttl=24h \
    allowed_cidrs="10.0.0.0/16,192.168.1.0/24"
```

Параметры роли:
- `key_type=ca` — режим центра сертификации
- `default_user` — пользователь по умолчанию
- `allowed_users` — список разрешённых пользователей
- `default_extensions` — расширения сертификата (например, `permit-pty` для PTY)
- `ttl` / `max_ttl` — срок действия сертификата
- `allowed_cidrs` — IP-ограничения

#### Шаг 3: Подпись публичного ключа

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

Сертификат сохраняется в `signed_key`. Добавьте его в `~/.ssh/`:

```bash
vault write -f ssh/sign/user-role public_key=@/path/to/id_ed25519_vault.pub > cert.pub
cat cert.pub >> ~/.ssh/authorized_keys
```

#### Шаг 4: Настройка SSH-сервера

Получение CA-ключа Vault:

```bash
vault read -field=public_key ssh/config/ca > /etc/ssh/trusted-user-ca-keys.pub
```

Настройка `sshd_config`:

```
TrustedUserCAKeys /etc/ssh/trusted-user-ca-keys.pub
AuthorizedKeysFile /etc/ssh/authorized_keys/%u
```

Перезапуск SSH:

```bash
sudo systemctl restart sshd
```

Подключение с сертификатом:

```bash
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

### Сценарий 4: Управление SSH-ключами хостов (Host Keys)

Vault может выступать как CA для хостовых SSH-ключей, обеспечивая единую инфраструктуру trust:

```bash
# Создание роли для хостов
vault write ssh/roles/host-role \
    key_type=ca \
    default_user=root \
    allowed_users="root,ubuntu" \
    ttl=720h \
    max_ttl=8760h

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

### Сценарий 5: Rotating CA-ключа

Периодическая ротация CA-ключа снижает риск при компрометации:

```bash
# 1. Создание новой CA-роли с новым ключом
vault write ssh/roles/user-role-v2 \
    key_type=ca \
    default_user=ubuntu \
    allowed_users="ubuntu,admin" \
    ttl=8h \
    max_ttl=24h

# 2. Подписание нового CA-ключа
vault read -field=public_key ssh/roles/user-role-v2 > /etc/ssh/trusted-user-ca-keys-v2.pub

# 3. Распространение нового CA-ключа на все серверы
ansible all -m copy -a "src=/etc/ssh/trusted-user-ca-keys-v2.pub dest=/etc/ssh/trusted-user-ca-keys-v2.pub mode=0644"

# 4. Добавление второго CA-ключа в sshd_config
# TrustedUserCAKeys /etc/ssh/trusted-user-ca-keys.pub /etc/ssh/trusted-user-ca-keys-v2.pub

# 5. Перезапуск SSH на всех серверах
ansible all -m systemd -a "name=sshd state=restarted"

# 6. После исхода TTL старых сертификатов — удаление старого CA-ключа
```

### Сценарий 6: Ограничение доступа по principals

Принцип наименьших привилегий: разные пользователи/сервисы получают доступ только к разрешённым хостам:

```bash
# Роль для deploy-пользователя (только продакшен)
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

## Практические команды

### Управление ролями

```bash
# Список ролей
vault list ssh/roles

# Чтение параметров роли
vault read ssh/roles/one-time-role

# Удаление роли
vault delete ssh/roles/one-time-role
```

### Управление ключами CA

```bash
# Просмотр CA-ключа
vault read -field=public_key ssh/config/ca

# Генерация нового CA-ключа (создаёт новую внутреннюю ключевую пару)
vault write -f ssh/config/ca

# Импорт внешнего CA-ключа
vault write ssh/config/ca \
    public_key=@/path/to/ca.pub \
    private_key=@/path/to/ca.key
```

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
```

## Лучшие практики

1. **Короткий TTL:** Настраивайте минимально возможный TTL для сертификатов (4–8 часов для пользователей, 1 час для CI/CD).
2. **Principals по умолчанию:** Всегда указывайте `default_user` и `allowed_users` в роли. Избегайте ролей с открытым доступом.
3. **CA-ключ:** Храните CA-ключ в Vault. Никогда не распространяйте приватный ключ CA на хосты.
4. **Ротация CA:** Планируйте ротацию CA-ключа раз в 6–12 месяцев. Используйте overlapping период для плавного перехода.
5. **CRL/Delta-CRL:** Включите CRL для возможности отзыва скомпрометированных сертификатов до истечения TTL.
6. **CIDR-ограничения:** Ограничивайте `cidr_list` в OTP-ролях и `allowed_cidrs` в CA-ролях.
7. **Audit:** Включите audit device для отслеживания всех операций выдачи SSH-сертификатов.
8. **vault-ssh-helper:** В production используйте `tls_skip_verify=false` и явный `ca_cert`.

## Ограничения и известные проблемы

- **OTP и кластеры:** В HA-кластере OTP-запросы обслуживает только активный узел. Standby-узлы возвращают 307 redirect.
- **vault-ssh-helper и systemd:** Убедитесь, что `vault-ssh-helper` доступен в PATH для PAM (частая ошибка — отсутствие бинарника).
- **SSH-клиенты:** Некоторые клиенты (старые OpenSSH) не поддерживают сертификаты. Проверяйте совместимость.
- **CRL:** Vault автоматически генерирует CRL, но клиенты должны периодически обновлять её (`ssh -o UpdateHostKeys=yes`).
- **Performance:** OTP-режим создаёт нагрузку на Vault при каждом подключении. Для high-load сред используйте CA-режим.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[Основные концепции Vault](../concepts.md)** — движки секретов, токены, lease.
*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — для CI/CD пайплайнов.
*   **[Zero Trust](../zero_trust.md)** — роль SSH CA в архитектуре нулевого доверия.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему статические SSH-ключи — антипаттерн.
*   [Официальная документация SSH Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/ssh)
