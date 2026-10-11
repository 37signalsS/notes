# Безопасность: TLS и SSO (OpenSearch)

**Актуально для:** OpenSearch 3.9.x (текущая ветка, релиз 29 сентября 2026) / 2.19.x (ветка поддержки, патчи). Security plugin входит в дистрибутив и включён в production-конфигурациях по умолчанию.

> TLS-шифрование слоёв transport/HTTP, аутентификация и авторизация через `config.yml`, подключение LDAP/Active Directory и SAML, маппинг ролей. Общая теория DLS/FLS и разграничение прав — в [Elasticsearch Security Advanced](../Elasticsearch/elasticsearch_security_advanced.md); применение security-конфигурации — в [OpenSearch Administration](./opensearch_administration.md).

## Определения

* **Security plugin** — встроенный в OpenSearch Security plugin: TLS, аутентификация, авторизация, DLS/FLS, audit log, API keys. Конфигурация — YAML-файлы в `config/opensearch-security/` + настройки в `opensearch.yml`.
* **Authentication domain** — блок в секции `authc` файла `config.yml`: комбинация `http_authenticator` (как принимать credentials) и `authentication_backend` (против чего проверять).
* **`authc` / `authz`** — секции `config.yml`: аутентификация и извлечение backend-ролей соответственно.
* **Super admin certificate** — клиентский сертификат, DN которого прописан в `plugins.security.authcz.admin_dn`; единственный, кто может менять security-конфигурацию (включая защищённый системный индекс `.opendistro_security`).
* **Backend role** — роль, полученная из внешнего бэкенда (LDAP-группа, SAML-атрибут); через role mapping сопоставляется с ролями OpenSearch.
* **Role mapping** — правило «backend role → роли OpenSearch»; хранится в security-конфигурации, управляется API.
* **`.opendistro_security`** — защищённый системный индекс, где хранятся users/roles/role mappings/конфигурация Security plugin (имя настраивается `plugins.security.config_index_name`).

## TLS: сертификаты и слои

OpenSearch шифрует два слоя:

| Слой | Что защищает | Настройки |
|---|---|---|
| Transport | inter-node коммуникация (9300) | `plugins.security.ssl.transport.*` |
| HTTP (REST) | клиентские запросы (9200) | `plugins.security.ssl.http.*` |

```yaml
# opensearch.yml — минимальная продакшен-конфигурация TLS
plugins.security.ssl.transport.enabled: true
plugins.security.ssl.transport.pemcert_filepath: certs/node.pem
plugins.security.ssl.transport.pemkey_filepath: certs/node-key.pem
plugins.security.ssl.transport.pemtrustedcas_filepath: certs/root-ca.pem
plugins.security.ssl.transport.enforce_hostname_verification: true

plugins.security.ssl.http.enabled: true
plugins.security.ssl.http.pemcert_filepath: certs/node-http.pem
plugins.security.ssl.http.pemkey_filepath: certs/node-http-key.pem
plugins.security.ssl.http.pemtrustedcas_filepath: certs/root-ca.pem

plugins.security.nodes_dn:
  - "CN=node1,OU=ops,O=example,L=MSK,ST=MSK,C=RU"
  - "CN=node2,OU=ops,O=example,L=MSK,ST=MSK,C=RU"
plugins.security.authcz.admin_dn:
  - "CN=admin,OU=ops,O=example,L=MSK,ST=MSK,C=RU"
```

Ключевые моменты:

* Пути к PEM-файлам — **относительно каталога `config/`**.
* `plugins.security.nodes_dn` — DN сертификатов нод; взаимная аутентификация transport-слоя только между этими нодами.
* `plugins.security.authcz.admin_dn` — DN super admin сертификата (без wildcards и regex). **Ранее использовавшийся в заметках ключ `plugins.security.admin_dn` не существует** — правильное имя `plugins.security.authcz.admin_dn`.
* `enforce_hostname_verification: true` по умолчанию: CN каждого сертификата ноды должен совпадать с её DNS A-записью; отключать только осознанно.
* Hot reload: `plugins.security.ssl.certificates_hot_reload.enabled: true` — ноды подхватывают заменённые сертификаты без рестарта; альтернатива — Reload Certificates API (`plugins.security.ssl_cert_reload_enabled: true`, по умолчанию `false`).

### Генерация сертификатов

```bash
# 1. Root CA
openssl req -x509 -newkey rsa:2048 -keyout root-ca-key.pem -out root-ca.pem \
  -days 3650 -nodes -subj "/CN=OpenSearch Root CA"

# 2. Сертификат ноды (CN должен совпадать с hostname — для enforce_hostname_verification)
openssl req -newkey rsa:2048 -keyout node-key.pem -out node.csr -nodes \
  -subj "/CN=node1.example.com,OU=ops,O=example"
openssl x509 -req -in node.csr -CA root-ca.pem -CAkey root-ca-key.pem \
  -out node.pem -days 825

# 3. Admin-сертификат (клиентский; DN попадёт в authcz.admin_dn)
openssl req -newkey rsa:2048 -keyout admin-key.pem -out admin.csr -nodes \
  -subj "/CN=admin,OU=ops,O=example"
openssl x509 -req -in admin.csr -CA root-ca.pem -CAkey root-ca-key.pem \
  -out admin.pem -days 825
```

Права: ключи `600`, сертификаты `644`, владелец — пользователь OpenSearch. Демо-сертификаты (`install_demo_configuration.sh`) — только для dev: заменяются своими, `plugins.security.allow_unsafe_democertificates` остаётся `false` в production.

## config.yml: аутентификация и авторизация

Структура `config/opensearch-security/config.yml`:

```yaml
_meta:
  type: "config"
  config_version: 2

config:
  dynamic:
    http: ...
    authc:            # authentication domains, порядок по order
      <domain_name>:
        http_enabled: true
        transport_enabled: false
        order: 1
        http_authenticator:
          type: basic        # basic | saml | openid_connect | jwt | kerberos | client_cert | proxy
          challenge: true
        authentication_backend:
          type: internal      # internal | ldap | noop
          config: ...
    authz:            # извлечение backend-ролей
      <domain_name>:
        authorization_backend:
          type: ldap          # ldap | noop
```

Правила:

* Домены обрабатываются по возрастанию `order`; первый домен с `challenge: true`, отвечающий на запрос, «перехватывает» его.
* `http_authenticator` определяет формат входа (basic, SAML redirect, JWT header...), `authentication_backend` — где проверять пользователя: `internal` (внутренняя БД пользователей), `ldap`, `noop` (проверка уже выполнена, например SAML/OIDC).
* `challenge: true` — домен отвечает 401 при неавторизованном запросе; для API-доступа и внутреннего пользователя Dashboards нужен домен `basic` **первым в цепочке** с `challenge: false`.
* Изменения в YAML применяются через `securityadmin.sh` (см. [Administration](./opensearch_administration.md)) либо динамический Security REST API.

### Несколько доменов (рекомендуемая схема)

```yaml
config:
  dynamic:
    authc:
      basic_internal_auth_domain:
        http_enabled: true
        transport_enabled: false
        order: 0
        http_authenticator:
          type: basic
          challenge: false
        authentication_backend:
          type: internal
      saml_auth_domain:
        http_enabled: true
        transport_enabled: false
        order: 1
        http_authenticator:
          type: saml
          challenge: true
          config: ...
        authentication_backend:
          type: noop
```

`basic` с `challenge: false` и нулевым порядком — для API-клиентов и OpenSearch Dashboards server; пользователи через браузер попадают в SAML-домен с `challenge: true`.

## SAML

```yaml
saml_auth_domain:
  http_enabled: true
  transport_enabled: false
  order: 1
  http_authenticator:
    type: saml
    challenge: true
    config:
      idp:
        metadata_file: okta.xml       # или metadata_url: https://idp.example.com/metadata
        entity_id: http://idp.example.com/
      sp:
        entity_id: https://opensearch.example.com
  authentication_backend:
    type: noop                         # SAML работает только на HTTP-слое — backend не нужен
```

* `idp.metadata_file` (файл в каталоге `config/`) **или** `idp.metadata_url` — обязательно одно из двух; `idp.entity_id`, `sp.entity_id` — идентификаторы сторон.
* Дополнительные ключи `config`: `sp.signature_private_key`, `sp.signature_algorithm`, `sp.forceAuthn`, TLS к IdP (`idp.enable_ssl`, `idp.verify_hostnames`, `idp.pemtrustedcas_filepath`, клиентский `idp.pemcert_filepath`/`idp.pemkey_filepath`).
* `authentication_backend: type: noop` обязателен — SAML не имеет backend-проверки паролем.
* После config.yml — активация в OpenSearch Dashboards (security-настройки `opensearch_dashboards.yml`), иначе вход из UI не заработает.
* Роли из атрибутов SAML маппятся на роли OpenSearch через Role mapping API:

```bash
POST _plugins/_security/api/rolesmapping/all_access
{
  "backend_roles": ["admin-group"],
  "users": []
}
```

## LDAP / Active Directory

```yaml
authc:
  ldap:
    http_enabled: true
    transport_enabled: true
    order: 2
    http_authenticator:
      type: basic
      challenge: true
    authentication_backend:
      type: ldap
      config:
        enable_ssl: true
        enable_start_tls: false
        enable_ssl_client_auth: false
        verify_hostnames: true
        hosts:
          - ldap.example.com:636
        bind_dn: "cn=admin,dc=example,dc=com"
        password: "bind-password"
        userbase: "ou=people,dc=example,dc=com"
        usersearch: "(sAMAccountName={0})"
        username_attribute: uid
authz:
  roles_from_myldap:
    description: "Authorize via LDAP"
    http_enabled: true
    transport_enabled: true
    authorization_backend:
      type: ldap
      config:
        hosts: ["ldap.example.com:636"]
        bind_dn: "cn=admin,dc=example,dc=com"
        password: "bind-password"
        userbase: "ou=people,dc=example,dc=com"
        usersearch: "(sAMAccountName={0})"
        username_attribute: uid
        rolebase: "ou=groups,dc=example,dc=com"
        resolve_nested_roles: true
```

* Аутентификация (`authc`) — поиск пользователя под `userbase` фильтром `usersearch` (`{0}` подставляется вводимое имя).
* Авторизация (`authz`) — извлечение backend-ролей из поддерева `rolebase`; `{0}` — DN пользователя, `{1}` — username; `resolve_nested_roles: true` разворачивает вложенные группы.
* `authz` также требует `userbase`/`usersearch`/`username_attribute` — Security plugin всегда перепроверяет существование пользователя.
* Анонимный bind — `bind_dn`/`password` в `null`.

## API keys (SRE-контекст)

С 3.7 OpenSearch поддерживает долгоживущие **API keys** со scoped permissions — альтернатива выдачи пользовательских ролей для service-to-service и CI/CD:

```bash
# Создать API-ключ для service-счета (ограничен по действиям и индексам)
POST _plugins/_security/api/key
{
  "name": "log-writer-key",
  "roles": ["log-reader"],
  "expiration": "30d",
  "expire_at_use": false
}
# → {"id":"...","key":"...","expires":"..."}
```

* `roles` — результирующие роли (не backend_roles — маппинг не применяется).
* `expiration` — относительное время жизни (например `30d`); при отсутствии — бесконечный.
* `expire_at_use: true` — ключ одноразовый (подходит для прокидывания в CI/CD-пайплайнах).
* Отзыв: `DELETE _plugins/_security/api/key/<id>` — синхронно по всему кластеру.
* API keys не работают в transport-слое — только HTTP. Для межузлового трафика используйте TLS-сертификаты.

## Типы `http_authenticator`

| Тип | Назначение | SRE-контекст |
|---|---|---|
| `basic` | HTTP Basic (login/password) | основной для API-клиентов и Dashboards server; в цепочке — первым, `challenge: false` |
| `saml` | SAML 2.0 (редирект на IdP) | SSO для браузера; backend — `noop` |
| `openid_connect` | OpenID Connect | SSO + bearer-token для API; конфигурация аналогична SAML |
| `jwt` | JWT из заголовка `Authorization: Bearer` | service-to-service: короткоживущие токены без паролей |
| `kerberos` | Kerberos (SPNEGO) | интеграция с доменными службами (AD); требует keytab и настроенный principal |
| `client_cert` | client certificate (mTLS) | machine-to-machine: аутентификация по DN сертификата, без паролей |
| `proxy` | извлекает username из заголовка (например, `X-Forwarded-User`) | прокси/балансировщик уже проверил пользователя; backend — `noop` |

## Роли, пользователи и маппинг

```bash
# Роль с правами
POST _plugins/_security/api/roles/log-reader
{
  "cluster_permissions": ["cluster_composite_ops_search"],
  "index_permissions": [
    { "index_patterns": ["logs-*"], "allowed_actions": ["read", "view_index_metadata"] }
  ]
}

# Внутренний пользователь
POST _plugins/_security/api/internalusers/alice
{ "password": "StrongPassw0rd!", "opendistro_security_roles": ["log-reader"] }

# Backend-роль (из LDAP/SAML) → роли OpenSearch
POST _plugins/_security/api/rolesmapping/log-reader
{ "backend_roles": ["ldap-log-readers"] }

# Проверка
GET _plugins/_security/api/roles/log-reader
GET _plugins/_security/api/rolesmapping
GET _plugins/_security/api/validate
```

Разграничение прав (DLS — фильтрация документов, FLS — полей, field masking) описано в [Elasticsearch Security Advanced](../Elasticsearch/elasticsearch_security_advanced.md): механизмы идентичны, security-конфигурация OpenSearch управляется теми же концепциями ролей. Режим оценки DLS — `plugins.security.dls.mode` (по умолчанию `adaptive`).

## Troubleshooting

### 401 на все запросы после правки config.yml

1. Проверить порядок доменов и `challenge`: домен `basic` для API должен стоять первым с `challenge: false`.
2. Убедиться, что изменения применены (`securityadmin.sh` или dynamic API), а не только сохранены в YAML — файлы не подхватываются автоматически.
3. Логи ноды: `opensearch.log`, `plugins/security-audit/` — там видно, какой домен отклонил запрос.

### securityadmin.sh: «... is not an admin user»

1. DN сертификата не совпадает с `plugins.security.authcz.admin_dn` в `opensearch.yml` — сравнить символ в символ (`openssl x509 -in admin.pem -noout -subject`).
2. `plugins.security.ssl.http.enabled: true` — обязательное условие работы скрипта; запускать с `-icl`/настроенном HTTPS.
3. Wildcards в `authcz.admin_dn` запрещены.

### SAML-вход не работает / redirect loop

1. `idp.metadata_file` лежит именно в `config/`, путь указывать относительно него.
2. `authentication_backend: noop` — иначе домен пытается искать пользователя в БД.
3. Активировать SAML в `opensearch_dashboards.yml` (Base URL, openid Connect/SAML-настройки Dashboards).
4. `sp.entity_id` на стороне IdP и OpenSearch должен совпадать.

### LDAP: пользователь найден, но прав нет

1. Проверить секцию `authz`: `rolebase`, `usersearch`, `username_attribute` (часто задают только в `authc`).
2. `GET _plugins/_security/api/rolesmapping` — назначены ли backend-роли на роли OpenSearch.
3. `resolve_nested_roles` — нужны ли вложенные группы.

### DN ноды не проходит transport-аутентификацию

1. `plugins.security.nodes_dn` должен содержать DN сертификатов **всех** нод.
2. Transport-TLS включён (`plugins.security.ssl.transport.enabled: true`), CA общий.
3. При `enforce_hostname_verification: true` CN = hostname ноды.

## Best Practices

1. Production — только свои сертификаты (свой CA), demo-конфигурация и `allow_unsafe_democertificates` запрещены.
2. Отдельные сертификаты для transport и HTTP; ключи `600`, владелец — пользователь OpenSearch.
3. `authcz.admin_dn` — минимальный набор DN, отдельный admin-сертификат не для повседневных операций.
4. Схема доменов: `basic` (internal, challenge false, order 0) + внешний SSO (challenge true) — обеспечивает и UI-вход, и API-доступ.
5. Роли выдавать через backend-роли (LDAP-группы/SAML-группы), а не назначать права внутренним пользователям по одному.
6. Security-конфигурацию версионировать в Git и применять как артефакт (securityadmin.sh / CI), а не править руками на нодах.
7. DLS/FLS — для multi-tenancy; audit log включать (`plugins.security.audit.type`) для трассировки доступа.
8. Смену сертификатов планировать с hot reload либо кратковременным рестартом нод; DN в `nodes_dn`/`authcz.admin_dn` обновлять синхронно.

## Граничные случаи

| Ситуация | Поведение / ограничение |
|---|---|
| `securityadmin.sh` переписывает изменения из API | скрипт загружает YAML из `-cd`/`-f` и затирает всё в индексе безопасности; перед запуском — `-backup <dir>` или точечное `-f <file> -t <type>` |
| `basic` с `challenge: true` на первом месте | браузер получит 401 + Basic-диалог; API-клиенты без `Authorization` — отклонены. Для API — `challenge: false` |
| SAML без `authentication_backend: noop` | домен пытается найти пользователя в internal LDAP/БД — ошибка. SAML работает только на HTTP-слое |
| `idp.metadata_file` не в `config/` | путь указывается относительно `config/`; ошибка при старте домена |
| `authz` без `userbase`/`usersearch` | Security plugin всегда перепроверяет существование пользователя; без этих полей авторизация возвращается `[]` |
| `bind_dn`/`password` в `null` | анонимный bind — работает только если LDAP-сервер допускает анонимные запросы |
| DN с wildcards в `authcz.admin_dn` | не поддерживается — сравнение по точному DN. Используйте отдельные DN или regex-синтаксис плагина |
| `enforce_hostname_verification: true` + самоподписанный сертификат | CN сертификата должен совпадать с hostname ноды; для dev — `-nhnv` у securityadmin.sh или отключите проверку осознанно |
| Меняете cert, но не обновили `nodes_dn` | inter-node transport-аутентификация отклонит ноду — кластер не соберётся |
| Audit log пишет, но индекс не создаётся | `plugins.security.audit.type` в `opensearch.yml` не задан — по умолчанию storage нет, плагин предупреждает при старте |
| `PUT _plugins/_security/api/securityconfig` | официально не рекомендуется — «can easily break your existing configuration»; используйте securityadmin.sh или точечные API |
| API keys в transport-слое | не работают — только HTTP. Для межузлового трафика только TLS-сертификаты |
| `allow_default_init_securityindex: true` | плагин сам инициализирует индекс при первом старте; удобно для автоматизации, но не заменяет securityadmin.sh при последующих изменениях |

## Дополнительная информация

* [OpenSearch Administration](./opensearch_administration.md) — securityadmin.sh, статус кластера, ключевые настройки.
* [Elasticsearch Security Advanced](../Elasticsearch/elasticsearch_security_advanced.md) — SSoT по DLS/FLS/masking и модели прав.
* [OpenSearch: Обзор](./opensearch_overview.md) — security по умолчанию, демо-конфигурация.
* [OpenSearch Ansible Deployment](./opensearch_ansible_deployment.md) — готовый TLS-блок для автоматизации развёртывания.

### Перекрытие с существующими файлами (§0.10)

* `OpenSearch/opensearch_administration.md` — операции (запуск securityadmin.sh, применение конфигурации); настоящий файл — содержимое конфигурации (TLS-ключи, домены, SAML/LDAP). Связаны ссылками.
* `Elasticsearch/elasticsearch_security_advanced.md` — SSoT по DLS/FLS/модели прав; здесь они только упоминаются.
* Пробел «security: TLS/LDAP/SAML» в OpenSearch-разделе закрыт.

### Обнаруженный дефект в связанном файле (§0.4.1)

`opensearch_administration.md` указывал `plugins.security.admin_dn` (дважды) — такого ключа нет, правильное имя `plugins.security.authcz.admin_dn` (проверено по docs.opensearch.org, Security settings). Обе правки внесены отдельно.
