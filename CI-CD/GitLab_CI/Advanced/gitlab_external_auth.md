# Внешняя аутентификация GitLab

**Актуально для:** GitLab 17.x–19.x (Omnibus, Docker, Helm)

## Определения

* **LDAP (Lightweight Directory Access Protocol)** — протокол доступа к каталогам пользователей. Позволяет использовать корпоративный Active Directory или OpenLDAP для аутентификации в GitLab.
* **SAML 2.0 (Security Assertion Markup Language)** — стандарт для обмена данными аутентификации между identity provider (IdP) и service provider (SP). GitLab выступает как SP.
* **OIDC (OpenID Connect)** — слой идентичности поверх OAuth 2.0. Позволяет federate аутентификацию через внешние IdP (Keycloak, Authelia, Dex).
* **SCIM (System for Cross-domain Identity Management)** — протокол для автоматизации provisioning/deprovisioning пользователей между IdP и GitLab.
* **Group Sync** — автоматическая синхронизация групп и memberships из LDAP/SAML/OIDC в GitLab.
* **Kerberos/GSSAPI** — метод аутентификации, использующий tickets Kerberos для single sign-on.
* **SAML NameID** — идентификатор пользователя в SAML-assertion. Форматы: `transient`, `persistent`, `email`.
* **Auto-discovery** — автоматическое обнаружение metadata endpoints IdP по email-домену пользователя.

## Основные концепции

### Архитектура аутентификации GitLab

GitLab поддерживает несколько методов аутентификации, которые могут работать параллельно:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Standard  │     │    LDAP     │     │   SAML/OIDC │
│  (Database) │     │   Server    │     │    IdP      │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────▼──────┐
                    │   GitLab    │
                    │   Server    │
                    └─────────────┘
```

### Сравнение методов аутентификации

| Метод | SSO | Provisioning | Group Sync | SCIM | Рекомендация |
|:---|:---|:---|:---|:---|:---|
| **Database** | Нет | Ручное | Нет | Нет | Только для тестирования |
| **LDAP** | Да (Kerberos) | Полное | Да | Нет | Корпоративные сети с AD/LDAP |
| **SAML** | Да | Полное | Да | Опционально | Enterprise IdP (ADFS, Keycloak) |
| **OIDC** | Да | Полное | Да | Опционально | Современные корпоративные IdP |
| **Kerberos** | Да | Нет | Нет | Нет | Корпоративные сети с Kerberos |

### Сценарии использования

| Сценарий | Рекомендуемый метод | Причина |
|:---|:---|:---|
| Корпоративная сеть с Active Directory | LDAP | Нативная интеграция, group sync |
| Enterprise IdP (ADFS, Keycloak) | SAML | SSO, SCIM provisioning, federation |
| Современные корпоративные IdP | OIDC | Гибкость, multiple IdP, group-based access |
| Legacy-инфраструктура с Kerberos | Kerberos/GSSAPI | Существующая инфраструктура |
| Мульти-tenant окружение | OIDC | Поддержка нескольких независимых IdP |

## Практические сценарии

### Сценарий 1: Настройка LDAP (Omnibus)

```ruby
# /etc/gitlab/gitlab.rb

# Включение LDAP
gitlab_rails['ldap_enabled'] = true

# Настройка сервера LDAP
gitlab_rails['ldap_servers'] = {
  'main' => {
    'label' => 'Corporate LDAP',
    'host' => 'ldap.corp.example.com',
    'port' => 636,
    'encryption' => 'simple_tls',
    'verify_certificates' => true,
    'ca_cert' => '/etc/gitlab/ldap/ca.crt',
    'bind_dn' => 'CN=gitlab,OU=Service Accounts,DC=corp,DC=example,DC=com',
    'password' => 'secure_password',
    'active_directory' => true,
    'allow_username_or_email_login' => true,
    'uid' => 'sAMAccountName',
    'base' => 'DC=corp,DC=example,DC=com',
    'user_filter' => '(&(objectClass=user)(objectCategory=person))',
    'group_base' => 'OU=GitLab Groups,DC=corp,DC=example,DC=com',
    'group_member_attribute' => 'member',
    'sync_ssh_keys' => true,
    'sync_email' => true,
    'sync_name' => true,
    'block_auto_created_users' => false,
    'attributes' => {
      'email' => ['mail', 'email', 'userPrincipalName'],
      'name' => 'displayName',
      'first_name' => 'givenName',
      'last_name' => 'sn',
      'username' => 'sAMAccountName'
    }
  }
}

# Применение конфигурации
sudo gitlab-ctl reconfigure
```

### Сценарий 2: Настройка SAML 2.0 (Omnibus)

```ruby
# /etc/gitlab/gitlab.rb

# Включение SAML
gitlab_rails['omniauth_enabled'] = true
gitlab_rails['omniauth_allow_single_sign_on'] = ['saml']
gitlab_rails['omniauth_block_auto_created_users'] = false

# SAML провайдер
gitlab_rails['omniauth_providers'] = [
  {
    name: 'saml',
    label: 'Corporate SSO',
    args: {
      assertion_consumer_service_url: 'https://gitlab.example.com/users/auth/saml/callback',
      idp_cert_fingerprint: 'AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12',
      idp_sso_target_url: 'https://idp.corp.example.com/sso',
      idp_slo_target_url: 'https://idp.corp.example.com/slo',
      issuer: 'https://gitlab.example.com',
      name_identifier_format: 'urn:oasis:names:tc:SAML:2.0:nameid-format:persistent',
      attributes: {
        'email' => ['email', 'mail'],
        'name' => 'displayName',
        'first_name' => 'givenName',
        'last_name' => 'sn',
        'username' => 'uid'
      },
      group_attribute: 'groups',
      external_groups: ['gitlab-users', 'gitlab-admins']
    }
  }
]

# SCIM provisioning
gitlab_rails['saml_scim_enabled'] = true
gitlab_rails['saml_scim_url'] = 'https://gitlab.example.com/api/scim/v2/'

# Применение конфигурации
sudo gitlab-ctl reconfigure
```

### Сценарий 3: Настройка OIDC (Omnibus)

```ruby
# /etc/gitlab/gitlab.rb

# Включение OIDC
gitlab_rails['omniauth_enabled'] = true
gitlab_rails['omniauth_allow_single_sign_on'] = ['openid_connect']
gitlab_rails['omniauth_block_auto_created_users'] = false

# Generic OIDC provider (Keycloak / Dex / Authelia / др. self-hosted IdP)
gitlab_rails['omniauth_providers'] = [
  {
    name: 'openid_connect',
    label: 'Corporate SSO',
    args: {
      name: 'openid_connect',
      scope: ['openid', 'profile', 'email'],
      response_type: 'code',
      issuer: 'https://idp.corp.example.com',
      client_options: {
        identifier: 'CLIENT_ID',
        secret: 'CLIENT_SECRET',
        redirect_uri: 'https://gitlab.example.com/users/auth/openid_connect/callback'
      },
      user_attributes: {
        email: 'email',
        name: 'name',
        first_name: 'given_name',
        last_name: 'family_name',
        username: 'preferred_username'
      }
    }
  }
]

# Применение конфигурации
sudo gitlab-ctl reconfigure
```

### Сценарий 3a: Настройка OIDC (Helm)

```yaml
# provider.yaml — конфигурация OIDC провайдера
# Этот файл создаёт Kubernetes Secret для провайдера OIDC

name: 'openid_connect'
label: 'Corporate SSO'
args:
  name: 'openid_connect'
  scope: ['openid', 'profile', 'email']
  response_type: 'code'
  issuer: 'https://idp.corp.example.com'
  client_options:
    identifier: 'CLIENT_ID'
    secret: 'CLIENT_SECRET'
    redirect_uri: 'https://gitlab.example.com/users/auth/openid_connect/callback'
  user_attributes:
    email: 'email'
    name: 'name'
    first_name: 'given_name'
    last_name: 'family_name'
    username: 'preferred_username'
```

```bash
# Создание Secret из конфигурации провайдера
kubectl create secret generic gitlab-oidc-provider \
  --from-file=provider=provider.yaml \
  --namespace gitlab
```

```yaml
# values.yaml для GitLab Helm chart

global:
  appConfig:
    omniauth:
      enabled: true
      allowSingleSignOn: ['openid_connect']
      blockAutoCreatedUsers: false
      providers:
        - secret: gitlab-oidc-provider
          key: provider
```

```bash
# Применение конфигурации
helm upgrade --install gitlab gitlab/gitlab \
  -f values.yaml \
  --namespace gitlab --create-namespace
```

### Сценарий 4: Group Sync из LDAP

```ruby
# /etc/gitlab/gitlab.rb

# Настройка синхронизации групп LDAP → GitLab
gitlab_rails['ldap_servers'] = {
  'main' => {
    'label' => 'Corporate LDAP',
    'host' => 'ldap.corp.example.com',
    'port' => 636,
    'encryption' => 'simple_tls',
    'bind_dn' => 'CN=gitlab,OU=Service Accounts,DC=corp,DC=example,DC=com',
    'password' => 'secure_password',
    'active_directory' => true,
    'uid' => 'sAMAccountName',
    'base' => 'DC=corp,DC=example,DC=com',
    'group_base' => 'OU=GitLab Groups,DC=corp,DC=example,DC=com',
    'group_member_attribute' => 'member',
    'admin_group' => 'GitLab-Admins',
    'sync_group' => {
      'base' => 'OU=GitLab Groups,DC=corp,DC=example,DC=com',
      'filter' => '(objectClass=group)'
    }
  }
}

# Запуск синхронизации групп
sudo gitlab-rake gitlab:ldap:group_sync

# Проверка синхронизации
sudo gitlab-rake gitlab:ldap:check
```

### Сценарий 5: SCIM Provisioning (SAML/OIDC)

```bash
# Включение SCIM через API

# Для SAML
curl --header "PRIVATE-TOKEN: <your_access_token>" \
  --request PUT \
  --header "Content-Type: application/json" \
  --data '{"enabled": true}' \
  "https://gitlab.example.com/admin/application_settings/saml_scim"

# Для OIDC
curl --header "PRIVATE-TOKEN: <your_access_token>" \
  --request PUT \
  --header "Content-Type: application/json" \
  --data '{"enabled": true}' \
  "https://gitlab.example.com/admin/application_settings/oidc_scim"

# Проверка SCIM endpoint
curl -X GET \
  "https://gitlab.example.com/api/scim/v2/Users" \
  -H "Authorization: Bearer <admin_token>"
```

### Сценарий 6: Multi-factor Authentication (MFA)

```ruby
# /etc/gitlab/gitlab.rb

# Включение обязательного MFA для всех пользователей
gitlab_rails['password_authentication_enabled_for_web'] = true
gitlab_rails['password_authentication_enabled_for_git'] = true

# Политика MFA
gitlab_rails['mfa_required_for_all_users'] = true
gitlab_rails['mfa_allowed_remember_device_duration'] = 30.days.to_i

# Двухфакторная аутентификация через TOTP
gitlab_rails['totp_enabled'] = true

# Двухфакторная аутентификация через WebAuthn
gitlab_rails['webauthn_enabled'] = true
gitlab_rails['webauthn_verification_method'] = 'direct'

# SSO enforcement
gitlab_rails['enforce_2fa_for_all_users'] = true
gitlab_rails['allow_bypass_two_factor'] = false
```

## Валидация выбора метода аутентификации

### Проверка работоспособности

```bash
# 1. Проверка подключения к LDAP
sudo gitlab-rake gitlab:ldap:check

# 2. Проверка синхронизации групп LDAP
sudo gitlab-rake gitlab:ldap:group_sync

# 3. Проверка SAML metadata
sudo gitlab-rake gitlab:saml:metadata

# 4. Проверка OIDC провайдеров
sudo gitlab-rake gitlab:oidc:check

# 5. Проверка SCIM endpoint
curl -X GET "https://gitlab.example.com/api/scim/v2/Users" \
  -H "Authorization: Bearer <admin_token>"

# 6. Проверка статуса OmniAuth
sudo gitlab-rake gitlab:omniauth:check
```

### Критерии готовности

| Критерий | Значение |
|:---|:---|
| LDAP bind latency | < 100ms при нормальной нагрузке |
| SAML assertion processing | < 2s |
| OIDC token validation | < 500ms |
| Group sync interval | 6–12 часов (не real-time) |
| SCIM provisioning | < 30s на пользователя |
| Failed auth rate | < 0.1% от общего числа попыток |

### Миграция между методами аутентификации

При переходе с одного метода на другой:

1. **Parallel run:** Включите новый метод параллельно с существующим.
2. **Dry-run:** Протестируйте на группе pilot-пользователей.
3. **Attribute mapping:** Ведите документацию маппинга атрибутов между старым и новым методом.
4. **Cutover:** Переключите основную аутентификацию после валидации.
5. **Cleanup:** Отключите старый метод только после полного cutover.

## Операции и команды

### Управление LDAP

```bash
# Проверка соединения с LDAP
sudo gitlab-rake gitlab:ldap:check

# Синхронизация групп
sudo gitlab-rake gitlab:ldap:group_sync

# Просмотр пользователей LDAP
sudo gitlab-rake gitlab:ldap:list

# Импорт пользователей
sudo gitlab-rake gitlab:ldap:import
```

### Управление SAML

```bash
# Проверка SAML метаданных
sudo gitlab-rake gitlab:saml:metadata

# Тестирование SAML аутентификации
# Откройте в браузере: https://gitlab.example.com/users/auth/saml
```

### Управление OIDC

```bash
# Проверка OIDC провайдеров
sudo gitlab-rake gitlab:oidc:check

# Просмотр настроек OIDC
sudo gitlab-rake gitlab:oidc:list
```

### User management

```bash
# Просмотр внешних пользователей
sudo gitlab-rake gitlab:user:list_external

# Блокировка внешнего пользователя
sudo gitlab-rake gitlab:user:block[user@example.com]

# Разблокировка внешнего пользователя
sudo gitlab-rake gitlab:user:unblock[user@example.com]

# Удаление внешнего пользователя
sudo gitlab-rake gitlab:user:delete[user@example.com]
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `LDAP connection failed` | Неверные credentials или сеть | Проверьте `bind_dn`, `password`, доступность LDAP-сервера |
| `Invalid credentials` при входе | Неверный `user_filter` | Проверьте фильтр, убедитесь что пользователь проходит фильтр |
| `SAML authentication failed` | Неверный fingerprint или URL | Проверьте `idp_sso_target_url` и `idp_cert_fingerprint` |
| `SCIM provisioning not working` | SCIM не включен | Включите SCIM в application settings |
| `Group sync не работает` | Неверный `group_base` | Проверьте `group_base` и `group_member_attribute` |
| `User not found in LDAP` | Неверный `base` или `filter` | Проверьте `base` DN и `user_filter` |
| `OIDC callback failed` | Неверный `redirect_uri` | Убедитесь что `redirect_uri` совпадает в IdP и GitLab |
| `MFA required but not configured` | Пользователь не настроил MFA | Запросите у пользователя настроить TOTP/WebAuthn |

## Лучшие практики

### Безопасность

* **TLS/SSL:** всегда используйте `simple_tls` или `start_tls` для LDAP. Никогда не передавайте credentials в открытом виде.
* **Service Account:** создайте отдельный service account для GitLab в LDAP с минимальными правами (read-only на users и groups).
* **Password rotation:** регулярно меняйте пароль service account.
* **Certificate validation:** включите `verify_certificates` для LDAP и SAML.
* **MFA enforcement:** включайте обязательный MFA для всех пользователей, особенно для admin-групп.
* **SCIM:** используйте SCIM для автоматического provisioning/deprovisioning.
* **Session timeout:** настройте `SessionNotOnOrAfter` в SAML-assertion для принудительного разрыва сессий (по умолчанию 24 часа).
* **Bypass 2FA:** отключите `allow_bypass_two_factor` для production-инстансов.

### Производительность

* **Connection pooling:** настройте пул соединений LDAP для больших инстансов.
* **Caching:** включите кэширование LDAP-запросов для снижения нагрузки на сервер.
* **Group sync schedule:** синхронизируйте группы по расписанию (каждые 6–12 часов), а не в реальном времени.
* **Filter optimization:** оптимизируйте `user_filter` и `group_filter` для снижения нагрузки на LDAP.

### Организация

* **Group structure:** выносите GitLab-группы в отдельный OU в LDAP для упрощения управления.
* **Naming convention:** используйте единое соглашение об именовании групп (например, `gl-<project>-<role>`).
* **Documentation:** документируйте маппинг атрибутов LDAP/SAML/OIDC → GitLab.
* **Monitoring:** мониторьте ошибки аутентификации и latency LDAP/SAML/OIDC.

### Мониторинг и наблюдаемость

```bash
# Мониторинг LDAP подключений
sudo gitlab-rake gitlab:ldap:check | grep -E "error|timeout|latency"

# Мониторинг SAML метаданных
sudo gitlab-rake gitlab:saml:metadata

# Проверка OIDC провайдеров
sudo gitlab-rake gitlab:oidc:check

# Просмотр логов аутентификации
sudo gitlab-ctl tail gitlab-rails/production.log | grep -E "LDAP|SAML|OIDC|SCIM"

# Prometheus метрики для аутентификации
curl -s http://localhost:9090/api/v1/query?query=gitlab_ldap_bind_total | jq .
```

Рекомендуемые алерты:
- `gitlab_ldap_bind_errors_total` > 0 в течение 5 минут
- `gitlab_saml_auth_failures_total` > 0 в течение 5 минут
- `gitlab_omniauth_failure_total` > 0 в течение 5 минут
- Latency аутентификации > 2s (p95)

### Disaster Recovery

Для аутентификационной инфраструктуры:
- **LDAP:** репликация между primary и secondary серверами.
- **SAML/OIDC:** метаданные IdP должны быть доступны в DR-среде.
- **Certificates:** ротация сертификатов должна быть протестирована в DR.
- **Failover:** автоматический перебор LDAP-серверов при отказе primary.

### Compliance

- **SOX/PCI:** все изменения в конфигурации аутентификации должны быть audit-logged.
- **GDPR:** обеспечьте право на удаление аккаунта (deprovisioning через SCIM).
- **ISO 27001:** документируйте процесс управления доступом и ротации credentials.

## Граничные случаи и ограничения

### Расхождения между Self-Managed и SaaS

| Функция | Self-Managed | GitLab SaaS |
|:---|:---|:---|
| LDAP integration | Полная поддержка | Нет (только SAML/OIDC) |
| Kerberos/GSSAPI | Да | Нет |
| Multiple SAML IdP | Да | Нет (только 1 на группу) |
| SCIM | Полная поддержка | Ограниченная (только группы) |
| Group Sync (LDAP) | Да | Нет |
| Smartcard/PIV | Да | Нет |

### Рост beyond текущей редакции

| Текущий метод | Рекомендуемый переход | Причина |
|:---|:---|:---|
| Database | → LDAP | Масштабирование, централизованное управление |
| LDAP | → SAML | SSO, federation, MFA на уровне IdP |
| SAML | → OIDC | Современные протоколы, group-based access |
| SAML без SCIM | → SAML + SCIM | Автоматическое provisioning |

### Смешанные окружения

В крупных организациях могут сосуществовать:
- LDAP для внутренних сотрудников.
- SAML/OIDC для партнёров и подрядчиков.
- Изолированные инстансы для air-gapped проектов.

Рекомендации:
- Единый стандарт на метод аутентификации внутри одной команды.
- Документирование причин отклонений от стандарта.
- Централизованное управление политиками через IAM team.

### Air-gapped окружения

Для air-gapped развёртываний:
- SAML metadata и certificates хранятся локально.
- OIDC discovery endpoint должен быть доступен внутри сети.
- SCIM provisioning работает только внутри perimetra.

### Ограничения лицензирования

| Функция | Free | Premium | Ultimate |
|:---|:---|:---|:---|
| LDAP Group Sync | Нет | Да | Да |
| SAML Group Sync | Нет | Да | Да |
| OIDC Group Sync | Нет | Да | Да |
| SCIM Provisioning | Нет | Да | Да |
| Multiple SAML IdP | Нет | Да | Да |

## Дополнительная информация

### Связанные темы

* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)** — бэкап, восстановление, обновление
* **[Безопасность и закрепление GitLab Server](../Advanced/gitlab_server_security_hardening.md)** — закрепление ОС, SSL/TLS
*   **[LDAP и Active Directory](../../../LDAP/ldap_fundamentals.md)** — администрирование LDAP и Active Directory
* **[Vault: аутентификация](../../Vault/)** — аутентификация Vault через LDAP/OIDC

### Внешние ресурсы

* [GitLab LDAP Documentation](https://docs.gitlab.com/ee/administration/auth/ldap/)
* [GitLab SAML Documentation](https://docs.gitlab.com/ee/administration/auth/saml/)
* [GitLab OIDC Documentation](https://docs.gitlab.com/ee/administration/auth/oidc/)
* [GitLab SCIM Documentation](https://docs.gitlab.com/ee/administration/auth/scim/)
