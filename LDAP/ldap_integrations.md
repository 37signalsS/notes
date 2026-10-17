# LDAP: интеграция с внешними системами

## Определения

**LDAP Federation** -- механизм интеграции внешних систем аутентификации с LDAP-каталогом, позволяющий использовать единый каталог пользователей для всех сервисов организации.

**Team Sync** -- автоматическая синхронизация членства в командах/группах на основе групп из внешних провайдеров (LDAP, AD).

**LDAP Backend** -- конфигурация приложения, указывающая на LDAP-сервер для аутентификации и поиска пользователей/групп.

**Bind DN** -- учётная запись для подключения LDAP-сервера от имени приления. Должен иметь минимальные права.

---

## Базовые концепции

### Общая архитектура интеграции

```text
                        +------------------+
                        |   LDAP-сервер    |
                        | (OpenLDAP/389DS) |
                        +--------+---------+
                                 |
              +------------------+------------------+
              |                  |                   |
     +--------+------+ +--------+------+ +---------+-------+
     |  Grafana      | |  GitLab CI    | |  Vault          |
     |  (Dashboard)  | |  (CI/CD)      | |  (Secrets)      |
     +---------------+ +---------------+ +-----------------+
              |                  |                   |
     +--------+------+ +--------+------+ +---------+-------+
     |  Keycloak     | |  Nginx/Angie  | |  Databases      |
     |  (SSO/IdP)    | |  (Web Server) | |  (Redis/MySQL)  |
     +---------------+ +---------------+ +-----------------+
```

---

## Практические сценарии

### 1. Grafana + LDAP

Конфигурация `/etc/grafana/ldap.toml`:

```toml
[[servers]]
host = "ldap.example.com"
port = 389
use_ssl = false
start_tls = true
ssl_skip_verify = false
root_ca_cert = "/etc/grafana/ca.crt"

bind_dn = "cn=grafana,ou=services,dc=example,dc=com"
bind_password = "$GF_AUTH_LDAP_BIND_PASSWORD"

search_filter = "(uid=%s)"
search_base_dns = ["ou=people,dc=example,dc=com"]

[servers.attributes]
name = "cn"
surname = "sn"
username = "uid"
member_of = "memberOf"
email = "mail"

[[servers.group_search_filter = "(objectClass=groupOfNames)"]]
[[servers.group_search_base_dns = ["ou=groups,dc=example,dc=com"]]]
```

```bash
# /etc/grafana/grafana.ini
[auth.ldap]
enabled = true
config_file = /etc/grafana/ldap.toml
allow_sign_up = true
```

```bash
# Включение (переменная окружения)
export GF_AUTH_LDAP_BIND_PASSWORD="SecretPassword"
sudo systemctl restart grafana-server
```

Подробности: **[Grafana: управление пользователями](../Grafana/grafana_user_management_and_authentication.md)**

### 2. GitLab CI + LDAP

```ruby
# /etc/gitlab/gitlab.rb
gitlab_rails['ldap_enabled'] = true
gitlab_rails['ldap_servers'] = {
  'main' => {
    'label' => 'Corporate LDAP',
    'host' => 'ldap.example.com',
    'port' => 636,
    'uid' => 'uid',
    'encryption' => 'simple_tls',
    'bind_dn' => 'cn=gitlab,ou=services,dc=example,dc=com',
    'password' => 'ldapservicepassword',
    'active_directory' => false,
    'base' => 'ou=people,dc=example,dc=com',
    'group_base' => 'ou=groups,dc=example,dc=com',
    'verify_certificates' => true,
    'allow_username_or_email_login' => true
  }
}

gitlab_rails['ldap_group_sync_cron'] = '0 2 * * *'
```

```bash
sudo gitlab-ctl reconfigure
```

Подробности: **[GitLab: установка](../CI-CD/GitLab_CI/Tutorials/self_hosted_installation.md)**

### 3. Vault + LDAP Auth

Включение и конфигурация LDAP auth method, фильтры (`group_filter`, `user_filter`), назначение политик через `policies` в записях ролей/групп/пользователей, user lockout и разбор типовых ошибок — в отдельном руководстве: **[Vault: аутентификация через LDAP](../Vault/guides/vault-auth-ldap.md)**.

Подробнее о Vault: **[Vault: концепции](../Vault/concepts.md)**

### 4. Keycloak + LDAP Federation

```yaml
# keycloak.yaml (Realm Configuration)
components:
  STORAGE:
    - name: "ldap"
      config:
        vendor:
          - "other"
        connectionUrl:
          - "ldaps://ldap.example.com:636"
        bindDn:
          - "cn=keycloak,ou=services,dc=example,dc=com"
        bindCredential:
          - "SecretPassword"
        usersDn:
          - "ou=people,dc=example,dc=com"
        usernameLDAPAttribute:
          - "uid"
        rdnLDAPAttribute:
          - "uid"
        uuidLDAPAttribute:
          - "entryUUID"
        userObjectClasses:
          - "inetOrgPerson, posixAccount"
        editMode:
          - "READ_ONLY"
        syncRegistrations:
          - "false"
        fullSyncPeriod:
          - "-1"
        changedSyncPeriod:
          - "60"
        searchScope:
          - "1"
        batchSizeForSync:
          - "1000"
```

Подробности: **[Keycloak: LDAP Federation](../Security/Tools/keycloak_ldap_federation.md)**

### 5. Nginx + LDAP Authentication

```nginx
# /etc/nginx/conf.d/ldap-auth.conf

# Upstream для LDAP-аутентификации
upstream ldap-backend {
    server ldap.example.com:389;
}

server {
    listen 443 ssl;
    server_name app.example.com;

    # Альтернатива: auth_request к внешнему сервису
    location /protected/ {
        auth_request /auth;
        auth_request_set $remote_user $upstream_http_remote_user;

        proxy_pass http://app-backend;
    }

    location = /auth {
        internal;
        proxy_pass http://ldap-auth-backend/verify;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
    }
}
```

Для прямой LDAP-аутентификации в Nginx используйте модуль `ngx_http_auth_ldap_module` или внешний сервис (e.g., `ldap-auth` от lbryio).

Подробности: **[Angie: Access Control](../WebServers/Angie/angie_access_control.md)**

### 6. NetBox + LDAP

```python
# /opt/netbox/netbox/netbox/configuration.py
import ldap
from django_auth_ldap.config import LDAPSearch, GroupOfNamesType

AUTHENTICATION_BACKENDS = [
    'django_auth_ldap.backend.LDAPBackend',
    'netbox.authentication.RemoteUserBackend',
]

AUTH_LDAP_SERVER_URI = 'ldap://ldap.example.com:389'
AUTH_LDAP_BIND_DN = 'cn=netbox,ou=services,dc=example,dc=com'
AUTH_LDAP_BIND_PASSWORD = 'LDAP_BIND_PASSWORD'
AUTH_LDAP_USER_SEARCH = LDAPSearch(
    'ou=people,dc=example,dc=com',
    ldap.SCOPE_SUBTREE,
    '(uid=%(user)s)'
)

AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
    'ou=groups,dc=example,dc=com',
    ldap.SCOPE_SUBTREE,
    '(objectClass=groupOfNames)'
)
AUTH_LDAP_GROUP_TYPE = GroupOfNamesType()

AUTH_LDAP_REQUIRE_GROUP = 'cn=netbox-users,ou=groups,dc=example,dc=com'
AUTH_LDAP_MIRROR_GROUPS = True
AUTH_LDAP_CACHE_TIMEOUT = 3600
```

Подробности: **[NetBox: установка](../Networking/NetBox/netbox_debian_installation_guide.md)**

### 7. OpenSearch/Elasticsearch + LDAP Realm

```yaml
# opensearch-security/config.yml
plugins.security.authc:
  ldap:
    http_enabled: true
    transport_enabled: true
    order: 1
    http_authenticator:
      type: basic
      challenge: true
    authentication_backend:
      type: ldap
      config:
        enable_ssl: true
        enable_start_tls: false
        enable_ssl_client_auth: false
        trusted_ca_filepath: /etc/opensearch/root-ca.pem
        pemkey_filepath: /etc/opensearch/kirk.pem
        pemcert_filepath: /etc/opensearch/kirk.pem
        pemkey_password: keystore-password
        pemcert_password: keystore-password
        verify_hostnames: true
        hosts:
          - "ldap.example.com:636"
        bind_dn: "cn=opensearch,ou=services,dc=example,dc=com"
        password: "SecretPassword"
        userbase: "ou=people,dc=example,dc=com"
        usersearch: "(uid={0})"
        username_attribute: uid
        rolesbase: "ou=groups,dc=example,dc=com"
        rolesearch: "(member={0})"
        userroleattribute: null
        rolesync_enabled: true
        rolesyncinterval: 30
```

---

## Дополнительная информация

### Чеклист интеграции

```text
[ ] Для каждого сервиса создан отдельный Bind DN (read-only)
[ ] Bind DN имеет минимальные права (только search на нужных subtree)
[ ] TLS включен для всех LDAP-соединений
[ ] Пароли Bind DN хранятся в Vault / переменных окружения
[ ] Группы LDAP сопоставлены с ролями сервиса
[ ] Синхронизация групп включена и протестирована
[ ] Offline-режим (SSSD кэш) работает корректно
[ ] Логирование LDAP-запросов включено
```

### Частые ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Invalid credentials` при bind | Неверный Bind DN или пароль | Проверьте `ldapsearch -D ... -W` |
| Пользователь не найден | Неверный search_filter | Проверьте атрибуты через `ldapsearch` |
| Группы не синхронизируются | Неверный group_search_filter | Проверьте `memberOf` или `member` атрибуты |
| TLS handshake failed | Сертификат CA не добавлен | Добавьте CA в trusted certificates |

### См. также

- **[LDAP + SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/index.md)** -- клиентская интеграция с Linux
- **[LDAP Security Hardening](./ldap_security.md)** -- TLS, ACL
- **[LDAP: основы протокола](./ldap_fundamentals.md)** -- Bind операции
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** -- диагностика
