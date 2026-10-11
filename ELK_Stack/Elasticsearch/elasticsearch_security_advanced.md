# Security Advanced: DLS, FLS, Audit Logging

**Актуально для:** Elasticsearch 8.x / 9.x

> Продвинутое руководство по безопасности Elasticsearch. Рассматриваются Document-Level Security, Field-Level Security, Audit Logging, SAML/OIDC интеграция и Kibana Spaces.
>
> Связанные темы: базовая безопасность — [Elasticsearch Overview](./elasticsearch_overview.md); CCR/CCS — [Cross-Cluster](./elasticsearch_ccr_ccs.md).

## Определения

* **Document-Level Security (DLS)** — ограничение доступа к документам внутри индекса на основе условия запроса (role query).
* **Field-Level Security (FLS)** — ограничение доступа к отдельным полям документа.
* **Role** — набор привилегий на уровне кластера, индексов, документов и полей.
* **User** — учетная запись с назначенными ролями.
* **Realm** — источник аутентификации (native, LDAP, SAML, OIDC, PKI, Kerberos).
* **Audit Logging** — запись действий пользователей и событий безопасности для compliance.
* **Kibana Spaces** — изолированные рабочие пространства в Kibana для разных команд/проектов.
* **API Key** — ключ для программного доступа без использования пароля.
* **Run as (impersonation)** — выполнение запроса от имени другого пользователя; требует cluster-привилегии `run_as` у impersonator'а.

## Предварительные требования

* **Лицензия**: DLS, FLS и audit logging доступны на уровне Platinum и выше (в trial-режиме работают все функции).
* **Security включён**: `xpack.security.enabled: true` (в 8.x включён по умолчанию при auto-configuration).
* **DLS/FLS разрешены**: `xpack.security.dls_fls.enabled: true` (static, default true) — при `false` настройка DLS/FLS запрещена на кластере.
* **Аудит**: `xpack.security.audit.enabled: false` по умолчанию. До 9.4 — static setting (elasticsearch.yml на каждом узле + rolling restart); начиная с 9.5 — dynamic setting (cluster settings API).

## Document-Level Security (DLS)

### Принцип работы

DLS добавляет фильтр к каждому запросу пользователя, ограничивая видимые документы.

```
User Query: { "match_all": {} }
    │
    ▼
DLS Filter Applied
    │
    ▼
Effective Query: {
  "bool": {
    "must": { "match_all": {} },
    "filter": { "term": { "department": "engineering" } }
  }
}
```

### Создание роли с DLS

```bash
POST /_security/role/engineering-viewer
{
  "indices": [
    {
      "names": ["logs-*"],
      "privileges": ["read"],
      "query": {
        "template": {
          "source": {
            "term": {
              "department": "{{_user.metadata.department}}"
            }
          }
        }
      }
    }
  ]
}
```

Role query поддерживает Mustache-шаблоны. Доступные переменные `_user`:

| Переменная | Описание |
|---|---|
| `_user.username` | Имя аутентифицированного пользователя |
| `_user.full_name` | Полное имя (если задано) |
| `_user.email` | Email (если задан) |
| `_user.roles` | Список ролей пользователя |
| `_user.metadata` | Произвольные метаданные пользователя |

Query допустимо задавать строкой или вложенным JSON — формы эквивалентны. Если `query` опущен, DLS для этой записи индекса отключён.

### DLS с использованием user metadata

```bash
# Создание пользователя с метаданными
POST /_security/user/john
{
  "password": "secure-password",
  "roles": ["engineering-viewer"],
  "full_name": "John Doe",
  "email": "john@company.com",
  "metadata": {
    "department": "engineering",
    "team": "backend"
  }
}
```

Проверка применения роли и метаданных:

```bash
GET /_security/role/engineering-viewer
# → {"engineering-viewer":{"indices":[{"names":["logs-*"],"privileges":["read"],"query":{...}}]}}

GET /_security/user/john
# → metadata: {"department":"engineering","team":"backend"}
```

Для объектов и массивов в metadata используется функция `{{#toJson}}`:

```bash
POST /_security/role/example3
{
  "indices": [
    {
      "names": ["my-index-000001"],
      "privileges": ["read"],
      "query": {
        "template": {
          "source": "{ \"terms\": { \"group.statuses\": {{#toJson}}_user.metadata.statuses{{/toJson}} }}"
        }
      }
    }
  ]
}
```

### DLS с несколькими условиями

```bash
POST /_security/role/multi-tenant-viewer
{
  "indices": [
    {
      "names": ["logs-*"],
      "privileges": ["read"],
      "query": {
        "bool": {
          "must": [
            { "term": { "tenant_id": "{{_user.metadata.tenant_id}}" } },
            { "range": { "@timestamp": { "gte": "now-7d" } } }
          ]
        }
      }
    }
  ]
}
```

### Взаимодействие нескольких ролей

DLS-запросы ролей пользователя комбинируются по OR: достаточно совпадения с запросом любой из ролей. Если хотя бы одна роль даёт доступ к индексу без DLS, пользователь видит все документы индекса. Перед выводом в production проверяйте полный набор ролей пользователя (`GET /_security/user/<username>`).

### Ограничения DLS

- DLS применяется только к document-based read API (search, get, mget). **Write API не фильтруются**: пользователь с write-привилегиями может индексировать документы вне области DLS. Используйте уникальные `_id` на пользователя и ingest-процессор `set_security_user` для маркировки документов.
- Агрегации могут возвращать сводную информацию по всему индексу: пользователь с DLS может узнать имена полей и термины, существующие только в недоступных документах, и количество документов с данным термином.
- DLS не влияет на глобальную статистику индекса, используемую для relevance scoring: scores вычисляются без учёта role query, но документы вне запроса не возвращаются.
- Не поддерживаются в role query: `has_child`/`has_parent` (допустимы в search API), date math с `now` в range-запросах по date-полям, запросы с удалёнными вызовами (terms lookup, geo_shape с indexed shapes, percolate).
- Suggesters игнорируются при включённом DLS; search-запрос нельзя профилировать; terms enum API не возвращает термины; `multi_match` не поддерживает wildcards для полей.
- DLS/FLS отключает shard request cache для затронутых запросов — учитывайте это при capacity planning.
- DLS добавляет фильтр на каждом шарде и может влиять на производительность поиска.

## Field-Level Security (FLS)

### Принцип работы

FLS исключает поля из ответа или запрещает запросы к ним.

```
Document: {
  "name": "John",
  "email": "john@company.com",
  "salary": 100000,
  "ssn": "123-45-6789"
}

With FLS (exclude: salary, ssn):
Response: {
  "name": "John",
  "email": "john@company.com"
}
```

### Создание роли с FLS

```bash
# Исключение полей (exclude)
POST /_security/role/hr-viewer
{
  "indices": [
    {
      "names": ["employees"],
      "privileges": ["read"],
      "field_security": {
        "grant": ["*"],
        "except": ["salary", "ssn", "bank_account"]
      }
    }
  ]
}
```

```bash
# Явное разрешение полей (include)
POST /_security/role/public-viewer
{
  "indices": [
    {
      "names": ["employees"],
      "privileges": ["read"],
      "field_security": {
        "grant": ["name", "department", "title"]
      }
    }
  ]
}
```

### Multi-fields

Multi-fields хранятся в индексе как независимые поля: исключение родительского поля не исключает автоматически его multi-fields. Чтобы закрыть поле и все его multi-fields, укажите и само поле, и wildcard:

```json
"field_security": {
  "grant": ["*"],
  "except": ["salary", "salary.*"]
}
```

### Комбинация DLS + FLS

```bash
POST /_security/role/limited-access
{
  "indices": [
    {
      "names": ["logs-*"],
      "privileges": ["read"],
      "field_security": {
        "grant": ["*"],
        "except": ["ip_address", "user_email"]
      },
      "query": {
        "term": {
          "department": "{{_user.metadata.department}}"
        }
      }
    }
  ]
}
```

### Ограничения FLS

- FLS применяется к document-based read API: поля фильтруются из хитов поиска и из `_source` в ответе.
- Пользователь с FLS не может выполнять write-операции: update API, update-запросы внутри bulk, а также операции, делающие содержимое доступным под другим именем (clone, shrink, split index API, aliases API).
- Метаданные всегда доступны: `_id`, `_type`, `_parent`, `_routing`, `_timestamp`, `_ttl`, `_size`, `_index`. При пустом списке полей доступны только они.
- Если `field_security` опущен, роль даёт доступ ко всем полям.
- При нескольких ролях поля объединяются в единый набор: если одна из ролей даёт доступ ко всем полям, FLS для индекса не применяется.
- Shard request cache отключается для search-запросов, если role query использует stored script или индексы смешанные local/remote.

## Audit Logging

### Включение Audit Logging

```yaml
# elasticsearch.yml (до 9.4 — static, требуется rolling restart)
xpack.security.audit.enabled: true

# Выходы аудита. logfile — default и единственный по умолчанию; index добавляет запросимые индексы
xpack.security.audit.outputs: [ index, logfile ]
```

Начиная с 9.5 `xpack.security.audit.enabled` — dynamic setting:

```bash
PUT /_cluster/settings
{
  "persistent": {
    "xpack.security.audit.enabled": true,
    "xpack.security.audit.outputs": ["index", "logfile"]
  }
}
```

### Настройки событий

```yaml
xpack.security.audit.logfile.events.include:
  - access_denied
  - access_granted
  - anonymous_access_denied
  - authentication_failed
  - connection_denied
  - tampered_request
  - run_as_denied
  - run_as_granted
  - security_config_change

xpack.security.audit.logfile.events.exclude: []

xpack.security.audit.logfile.events.emit_request_body: true
```

Default-список `include`: `access_denied, access_granted, anonymous_access_denied, authentication_failed, connection_denied, tampered_request, run_as_denied, run_as_granted, security_config_change`. Настройка `exclude` имеет приоритет над `include`. События `access_granted` пишутся только для не-system пользователей. Настройки events — dynamic, применяются через `PUT /_cluster/settings` без рестарта.

### Структура audit события

Logfile-выход пишет события в `<cluster_name>_audit.json` в каталоге logs (`ES_HOME/logs`) — по одной JSON-документу на строку, поля в dotted-нотации:

```json
{"type":"audit", "timestamp":"2020-12-30T22:30:06,949+0200", "node.id":"0RMNyghkQYCc_gVd1G6tZQ", "event.type":"transport", "event.action":"access_denied", "authentication.type":"REALM", "user.name":"user1", "user.realm":"default_native", "user.roles":["test_role"], "origin.type":"rest", "origin.address":"[::1]:51504", "url.path":"/logs-*/_search", "url.query":"size=100", "request.method":"GET", "request.id":"POv8p_qeTl2tb5xoFl0HIg"}
```

Ключевые поля:

| Поле | Описание |
|---|---|
| `event.type` | Слой, сгенерировавший событие: `rest` или `transport` |
| `event.action` | Тип события (см. таблицу ниже) |
| `authentication.type` | Способ аутентификации (например, `REALM`) |
| `user.name` / `user.realm` / `user.roles` | Effective user; при run as — целевой пользователь |
| `user.run_by.name` / `user.run_by.realm` | Impersonator; присутствуют только при run as |
| `origin.type` / `origin.address` | Источник запроса (REST-клиент, transport-узел) |
| `url.path` / `url.query` / `request.method` | REST-запрос |
| `request.body` | Тело запроса (только при `emit_request_body: true`) |
| `request.id` | Идентификатор запроса для корреляции событий одного запроса на разных узлах |

Index-выход сохраняет те же события в индексы `.security-audit-*`, где время хранится в поле `@timestamp`, а события доступны через search API.

### Типы событий

| Событие | Описание |
|---------|----------|
| `access_granted` | Успешный доступ (только для не-system пользователей) |
| `access_denied` | Отказано в доступе |
| `anonymous_access_denied` | Отклонён запрос без токена аутентификации |
| `authentication_success` | Успешная аутентификация |
| `authentication_failed` | Учётные данные не сопоставлены с пользователем |
| `realm_authentication_failed` | Ошибка конкретного realm |
| `connection_granted` | Входящее TCP-соединение прошло IP filter |
| `connection_denied` | Соединение отклонено IP filter |
| `tampered_request` | Обнаружен подменённый запрос (обычно scroll ID) |
| `run_as_granted` / `run_as_denied` | Impersonation разрешён / запрещён |
| `security_config_change` | Изменение конфигурации безопасности (пользователи, роли, role mapping, API keys, service account tokens); требуется включить для аудита соответствующих API. По умолчанию не содержит полей автора (`user.name`, `user.realm`) |

### Анализ Audit Logs

```bash
# Поиск отказов в доступе (требуется index output)
GET .security-audit-*/_search
{
  "query": {
    "term": { "event.action": "access_denied" }
  },
  "sort": [{ "@timestamp": "desc" }]
}

# Топ пользователей по отказам
GET .security-audit-*/_search
{
  "size": 0,
  "query": {
    "term": { "event.action": "access_denied" }
  },
  "aggs": {
    "by_user": {
      "terms": { "field": "user.name", "size": 10 }
    }
  }
}

# Подозрительная активность: много отказов с одного IP
GET .security-audit-*/_search
{
  "size": 0,
  "query": {
    "term": { "event.action": "authentication_failed" }
  },
  "aggs": {
    "by_ip": {
      "terms": { "field": "origin.address", "size": 10 }
    }
  }
}

# Изменения конфигурации безопасности за неделю
GET .security-audit-*/_search
{
  "query": {
    "bool": {
      "filter": [
        { "term": { "event.action": "security_config_change" } },
        { "range": { "@timestamp": { "gte": "now-7d" } } }
      ]
    }
  },
  "sort": [{ "@timestamp": "desc" }],
  "size": 50
}
```

### Фильтрация шумных событий (ignore_filters)

Политики игнорирования исключают события по пользователям, realm'ам, ролям, индексам и действиям:

```yaml
xpack.security.audit.logfile.events.ignore_filters:
  exclude_monitoring:
    users: ["kibana_system", "beats_system"]
    indices: [".monitoring-*"]
  exclude_health_reads:
    actions: ["indices:data/read/*"]
    users: ["monitoring_user"]
```

Политика срабатывает, когда все указанные в ней условия совпадают с событием. Пустой список `indices` матчит события без атрибута `indices` (например, `authentication_success`).

### Хранение Audit Logs

* **Logfile**: `<cluster_name>_audit.json` ротируется ежедневно или при достижении размера 1 ГБ.
* **Index output**: индексы `.security-audit-*` создаются ежедневно. Управление retention через ILM-политику, применённую к audit-индексам, не подтверждено документацией в этой сессии — перед применением проверьте поддержку ILM для системных индексов `.security-audit-*` в вашей версии.

```bash
# Проверка текущих настроек аудита
GET /_cluster/settings?include_defaults=true&flat_settings=true
# → отфильтруйте ключи xpack.security.audit.*
```

## SAML/OIDC интеграция

### Настройка SAML Realm

```yaml
# elasticsearch.yml
xpack.security.authc.realms.saml.saml1:
  order: 2
  idp.metadata.path: "/path/to/idp-metadata.xml"
  idp.entity_id: "https://idp.company.com/entity"
  sp.entity_id: "https://kibana.company.com"
  sp.acs: "https://kibana.company.com/api/security/v1/saml"
  sp.logout: "https://kibana.company.com/logout"
  attributes.principal: "nameid"
  attributes.groups: "groups"
  attributes.email: "email"
  attributes.name: "name"
```

### Настройка OIDC Realm

```yaml
# elasticsearch.yml
xpack.security.authc.realms.oidc.oidc1:
  order: 3
  rp.client_id: "elasticsearch"
  rp.response_type: "code"
  rp.redirect_uri: "https://kibana.company.com/api/security/v1/oidc"
  op.issuer: "https://auth.company.com"
  op.authorization_endpoint: "https://auth.company.com/authorize"
  op.token_endpoint: "https://auth.company.com/token"
  op.userinfo_endpoint: "https://auth.company.com/userinfo"
  op.jwks_endpoint: "https://auth.company.com/.well-known/jwks.json"
  claims.principal: "sub"
  claims.groups: "groups"
```

### Role Mapping для SAML/OIDC

```bash
# Маппинг групп SAML на роли Elasticsearch
POST /_security/role_mapping/saml-engineering
{
  "roles": ["engineering-viewer", "kibana-user"],
  "rules": {
    "all": [
      { "field": { "groups": "engineering" } },
      { "field": { "groups": "elasticsearch-users" } }
    ]
  },
  "enabled": true
}
```

### SSO на стороне Kibana (xpack.security.authc.providers)

Realm в Elasticsearch даёт Kibana возможность аутентифицировать пользователя, но порядок и способ входа в сам UI задаются провайдерами в `kibana.yml`. Провайдер привязывается к realm по имени (`realm`), тип и имя указываются в ключе вида `type.name`:

```yaml
# kibana.yml
xpack.security.authc:
  providers:
    basic.basic1:
      order: 0                 # обязательное поле: порядок в цепочке и на Login Selector
    saml.saml1:
      order: 1
      realm: "saml1"           # имя SAML-realm из elasticsearch.yml
      description: "Вход через корпоративный IdP"
      hint: "SSO для сотрудников"
      icon: "logoElastic"
```

* Типы провайдеров: `basic`, `token`, `saml`, `oidc`, `kerberos`, `pki`, анонимный `anonymous` (не более одного на инстанс). Ключ `providers.<type>.<name>` и поле `order` — **обязательны**.
* `showInSelector: false` убирает запись из Login Selector, не удаляя провайдер из цепочки аутентификации; для `basic` и `token` этот флаг установить в `false` нельзя.
* **Login Selector** — экран выбора способа входа; включается автоматически, когда настроено более одного провайдера (`xpack.security.authc.selector.enabled`, дефолт — `true` при нескольких провайдерах). Тексты/иконки записей задаются `description`, `hint`, `icon`.
* `origin` (GA с 9.3) — ограничивает, с каких origin'ов (URI) провайдер показывается в Login Selector; по умолчанию ограничений нет. Полезно, когда один Kibana доступен по нескольким именам.
* **Сессии провайдера**: `session.idleTimeout` / `session.lifespan` переопределяют глобальные `xpack.security.session.*` для конкретного провайдера (формат — `<count>[ms|s|m|h|d|w|M|Y]`).
* `accessAgreement.message` — текст пользовательского соглашения (Markdown) до входа; глобальный аналог — `xpack.security.accessAgreement.message`.
* Для OIDC провайдер ссылается на realm так же: `oidc.oidc1.realm: "oidc1"`.

**Порядок настройки:** realm (Elasticsearch, раздел выше) → role mapping → провайдер (Kibana, `kibana.yml`) → перезапуск Kibana. URL `sp.acs`/`sp.logout` в realm должен указывать на адрес, под которым Kibana доступна пользователям (учитывая basePath и reverse proxy — [Эксплуатация Kibana](../Kibana/kibana_production_operations.md)).

## LDAP и Active Directory

LDAP и AD — внешние realm'ы корпоративной идентичности: аутентификация (bind/search в каталоге) и авторизация по группам через role mapping. Другие внешние realm'ы этого файла (SAML/OIDC) решают задачу SSO в браузере; LDAP/PKI — задачу служебных и корпоративных пользователей без IdP-протокола.

**Realm chain.** Realms консультируются по возрастанию `order` (уникален для каждого realm). Важно: при настройке realm'ов в `elasticsearch.yml` в цепочку попадают только перечисленные realms — если после добавления LDAP-реалма нужен вход по паролю (native) или через file, их нужно явно указать в chain. Отключить realm без удаления конфига можно через `enabled: false`.

### LDAP realm: режим user search (основной)

Самый распространённый режим: служебный аккаунт (`bind_dn`) ищет DN пользователя по атрибуту. Минимум настроек — `url`, `order` и `user_search.base_dn`:

```yaml
# elasticsearch.yml
xpack.security.authc.realms:
  ldap:
    ldap1:
      order: 2
      url: "ldap://ldap.example.com:389"   # либо ldaps://...:636; допустим список URL
      bind_dn: "cn=ldapuser,ou=users,dc=example,dc=com"
      user_search:
        base_dn: "ou=users,dc=example,dc=com"
        filter: "(uid={0})"                # дефолт: (uid={0}); {0} — введённый username
      group_search:
        base_dn: "ou=groups,dc=example,dc=com"
      follow_referrals: true               # дефолт true
```

| Настройка | Default | Назначение |
|-----------|---------|------------|
| `url` | (обязательно) | `ldap://`/`ldaps://` адрес(а) сервера; список через YAML-массив или запятую |
| `user_search.base_dn` | (обязательно в этом режиме) | Контейнер DN для поиска пользователей; mutually exclusive с `user_dn_templates` |
| `user_search.filter` | `(uid={0})` | Фильтр поиска; `{0}` подставляется введённый username |
| `user_search.scope` | `sub_tree` | `sub_tree` / `one_level` / `base` |
| `bind_dn` / `secure_bind_password` | — | Служебный аккаунт для поиска; пароль **только** в keystore: `bin/elasticsearch-keystore add xpack.security.authc.realms.ldap.ldap1.secure_bind_password` |
| `group_search.base_dn` | — | Контейнер DN для поиска групп; ищутся `group`/`groupOfNames`/`groupOfUniqueNames`/`posixGroup` с `member`/`memberOf`/`memberUid` |
| `follow_referrals` | `true` | Следовать LDAP-referrals (рекомендация — `false` для AD, чтобы не ходить на недоступные DC) |
| `user_full_name_attribute` / `user_email_attribute` | `cn` / `mail` | Атрибуты для full name и email пользователя |
| `load_balance.type` | — | Балансировка/фейловер между несколькими LDAP-серверами |

### LDAP realm: режим user DN templates

Когда DN пользователя известен по шаблону и поиск не нужен (маленькие каталоги, несколько OU). Минимум — `url`, `order` и хотя бы один шаблон; `user_search` в этом режиме недопустим:

```yaml
xpack.security.authc.realms:
  ldap:
    ldap1:
      order: 2
      url: "ldaps://ldap.example.com:636"
      user_dn_templates:
        - "uid={0},ou=users,dc=example,dc=com"
        - "uid={0},ou=contractors,dc=example,dc=com"
      group_search:
        base_dn: "ou=groups,dc=example,dc=com"
```

### Active Directory realm

Для AD предпочтителен отдельный тип realm `active_directory`: он использует `tokenGroups` (в отличие от generic-ldap, который ищет группы через `group_search`):

```yaml
xpack.security.authc.realms:
  active_directory:
    ad1:
      order: 3
      domain_name: ad.example.com
      url: "ldaps://dc1.ad.example.com:636, dc2.ad.example.com:636"
      load_balance:
        type: "round_robin"
      bind_dn: "es_svc_user@ad.example.com"
```

`domain_name` — корневой домен леса; `url` обязателен (для Global Catalog — порт 3269). Пароль bind-аккаунта — в keystore (`...secure_bind_password`), как у LDAP.

### Role Mapping для LDAP/AD

Группы каталога (DN или `cn` в зависимости от `group_search`) маппятся на роли Elasticsearch; проверка — `GET /_security/_authenticate` (поле `roles`):

```bash
POST /_security/role_mapping/ldap-engineering
{
  "roles": ["engineering-viewer", "kibana-user"],
  "rules": {
    "all": [
      { "field": { "groups": "cn=engineering,ou=groups,dc=example,dc=com" } },
      { "field": { "realm.name": "ldap1" } }
    ]
  },
  "enabled": true
}
```

Полезные операторы rules: `field.dn` (DN пользователя, шаблоны с `*` допустимы), `field.realm.name` (ограничить маппинг конкретным realm'ом — иначе правило применится к пользователям всех realm'ов с совпавшим значением).

## PKI: аутентификация по клиентским сертификатам

PKI-realm идентифицирует пользователя по DN из Subject клиентского X.509-сертификата — для машинных клиентов, CI и администраторов без паролей. Работает только в паре с TLS: интерфейс должен запрашивать клиентский сертификат, а слой TLS — доверять ему. На Elastic Cloud Hosted PKI недоступна (self-managed/ECK).

```yaml
# elasticsearch.yml
xpack.security.authc.realms:
  pki:
    pki1:
      order: 4
      certificate_authorities: ["ES_PATH_CONF/certs/ca.pem"]   # PEM; либо truststore.path (mutually exclusive)
      username_rdn_name: "CN"                                  # GA с 9.1; иначе username_pattern

xpack.security.http.ssl:
  enabled: true
  client_authentication: "optional"   # или required; optional — клиенты без сертификата идут другими realm'ами
```

* **Имя пользователя** по умолчанию — CN из Subject DN; извлечение задаётся либо `username_pattern` (regex, дефолт `CN=(.*?)(?:,|$)`), либо `username_rdn_name`/`username_rdn_oid` (RDN-атрибут имеет приоритет над pattern).
* **Доверие сертификату**: `truststore.path` (JKS/PKCS12, пароль — `...truststore.secure_password` в keystore) **или** `certificate_authorities` (список PEM) — одновременно нельзя; либо `verification_mode: none` (доверять всем, что проходит TLS-слой).
* **Минимум для работы**: `client_authentication: required|optional` на HTTP/transport + доверие сертификату. Генерация CA и клиентских сертификатов — `elasticsearch-certutil` ([Практическое развёртывание Docker Compose](../Tutorials/practical_setup_with_docker.md)).
* **Role mapping**: по `field.dn` (с шаблонами `*`) или через делегирование авторизации (ниже).

### Делегирование: PKI аутентифицирует, LDAP авторизует

Типовой паттерн «сертификат для входа, роли из каталога»: PKI-realm извлекает username, но за роли отвечает LDAP-realm:

```yaml
xpack.security.authc.realms:
  pki:
    pki1:
      order: 4
      authorization_realms: ["ldap1"]   # авторизация делегируется; роль по DN ищет LDAP
      certificate_authorities: ["ES_PATH_CONF/certs/ca.pem"]
```

### PKI через прокси (delegate_pki)

Если TLS terminates прокси (например, Kibana), а не клиент — Elasticsearch предоставляет API `POST /_security/delegate_pki`: доверенный прокси передаёт цепочку сертификатов и получает access token. Для этого у realm'а включается `delegation.enabled: true`, а также должны быть заданы `truststore.path` или `certificate_authorities`. Проверка цепочки идёт по `username_pattern` каждого PKI-realm'а с включённой делегацией.

## Kibana Spaces и Security

### Что такое Spaces

Spaces — изолированные рабочие пространства в Kibana:

```
Default Space
├── Index Patterns: *
├── Saved Objects: *
└── Users: all

Engineering Space
├── Index Patterns: logs-*, metrics-*
├── Saved Objects: engineering dashboards
└── Users: engineering team

Finance Space
├── Index Patterns: finance-*
├── Saved Objects: finance dashboards
└── Users: finance team
```

### Создание Space

```bash
POST kibana/api/spaces/space
{
  "id": "engineering",
  "name": "Engineering",
  "description": "Engineering team workspace",
  "color": "#00BFB3",
  "disabledFeatures": ["enterpriseSearch", "graph"]
}
```

### Назначение ролей на Space

```bash
POST /_security/role/engineering-kibana
{
  "kibana": [
    {
      "spaces": ["engineering"],
      "feature": {
        "discover": ["read"],
        "dashboard": ["read"],
        "visualize": ["read"],
        "indexPatterns": ["all"]
      }
    }
  ],
  "indices": [
    {
      "names": ["logs-*", "metrics-*"],
      "privileges": ["read"]
    }
  ]
}
```

### Space-specific Index Patterns

```bash
# Создание index pattern в конкретном space
POST kibana/s/engineering/api/saved_objects/index-pattern
{
  "attributes": {
    "title": "logs-*",
    "timeFieldName": "@timestamp"
  }
}
```

## API Keys

### Создание API Key

```bash
POST /_security/api_key
{
  "name": "filebeat-production",
  "expiration": "30d",
  "role_descriptors": {
    "filebeat_writer": {
      "cluster": ["monitor", "manage_ilm", "manage_index_templates"],
      "index": [
        {
          "names": ["filebeat-*"],
          "privileges": ["create_index", "auto_configure", "write", "view_index_metadata"]
        }
      ]
    }
  },
  "metadata": {
    "purpose": "filebeat data shipping",
    "environment": "production"
  }
}
```

Секрет ключа (`api_key` в ответе) показывается только один раз — при создании; сохраните его в секрет-хранилище сразу.

### API Key с DLS

```bash
POST /_security/api_key
{
  "name": "limited-api-key",
  "role_descriptors": {
    "limited_reader": {
      "indices": [
        {
          "names": ["logs-*"],
          "privileges": ["read"],
          "query": {
            "term": { "tenant_id": "tenant-123" }
          }
        }
      ]
    }
  }
}
```

### Query и обновление API Keys

```bash
# Поиск ключей (query API)
GET /_security/api_key
{
  "query": {
    "term": { "name": "filebeat-production" }
  }
}

# Информация о конкретном ключе
GET /_security/api_key/<api_key_id>

# Обновление metadata и expiration (8.x+)
PUT /_security/api_key/<api_key_id>
{
  "metadata": {
    "environment": "staging"
  },
  "expiration": "90d"
}
```

### Отзыв API Key

```bash
# По имени
POST /_security/api_key/_invalidate
{
  "name": "filebeat-production"
}

# По realm
POST /_security/api_key/_invalidate
{
  "realm_name": "saml1"
}
```

## Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| DLS не применяется — видны все документы | Другая роль пользователя даёт доступ к индексу без DLS (OR-комбинация) | `GET /_security/user/<name>` — проверьте все роли; уберите доступ без DLS |
| FLS: поле всё ещё видно в ответе | Multi-field родительского поля не исключён; или другая роль даёт доступ ко всем полям | Исключите поле и wildcard (`salary`, `salary.*`); проверьте полный набор ролей |
| Агрегация возвращает данные по недоступным документам | Документированное ограничение DLS — агрегации могут давать сводку по всему индексу | Учитывайте при проектировании multi-tenant доступа |
| Audit-события не появляются в `.security-audit-*` | Не включён index output (`xpack.security.audit.outputs`) | Добавьте `index` в outputs; до 9.4 — rolling restart |
| `access_granted` не пишется | Событие логируется только для не-system пользователей | Ожидаемое поведение; мониторьте `access_denied`/`authentication_failed` |
| Настройки events не применяются | `exclude` перекрывает `include` | Проверьте обе настройки через cluster settings API |
| SAML: ошибка при входе | `sp.acs`/`sp.entity_id` не совпадают с конфигурацией IdP | Сверьте URL в elasticsearch.yml и metadata IdP |
| OIDC: redirect не работает | `rp.redirect_uri` не зарегистрирован в OP | Зарегистрируйте redirect URI в провайдере |
| API key отклонён | Истёк `expiration` или ключ отозван; секрет доступен только при создании | Создайте новый ключ; проверьте `GET /_security/api_key/<id>` |

## Граничные случаи

- Один клиентский запрос может генерировать несколько audit-событий на разных узлах кластера — корреляция по `request.id`.
- Wildcard `_all` и другие wildcards при включённом security применяются только к индексам, на которые у пользователя есть привилегии, а не ко всему кластеру.
- DLS-запрос с date math `now` в range по date-полю отклоняется — используйте фиксированные даты или диапазоны без `now`.
- FLS и update API: пользователь с FLS не может обновлять документы — разделяйте read-only и write роли.
- Run as: impersonator должен иметь cluster-привилегию `run_as`; в audit-событии `user.name` — целевой пользователь, `user.run_by.name` — impersonator.
- API key с DLS в `role_descriptors`: ограничение применяется к ключу независимо от ролей владельца.
- Kibana default space: пользователи без назначения на конкретный space видят default space.

## Best Practices

### Принцип наименьших привилегий

1. **Не используйте `superuser`** для сервисных аккаунтов
2. **Создавайте отдельные роли** для каждой функции (read, write, manage)
3. **Используйте DLS/FLS** для multi-tenant сред
4. **Регулярно ревьюйте роли** — удаляйте неиспользуемые

### Безопасность API Keys

1. **Короткий expiration** — 30 дней для сервисных ключей
2. **Metadata** — добавляйте информацию о назначении
3. **Ротация** — автоматизируйте обновление ключей
4. **Мониторинг** — алертите на использование отозванных ключей

### Audit Logging

1. **Включите для production** — compliance requirement
2. **Храните отдельно** — выделенный индекс или кластер
3. **Мониторьте аномалии** — частые отказы, подозрительные IP
4. **Настройте фильтрацию** — `ignore_filters` для системных пользователей и мониторинговых индексов

### Kibana Spaces

1. **Одна команда = один Space** — изоляция данных и дашбордов
2. **Ограничьте features** — отключите неиспользуемые возможности
3. **Space-specific roles** — не используйте all-spaces роли без необходимости

## Cleanup

```bash
# Удаление тестовых пользователей, ролей и role mapping
DELETE /_security/user/john
DELETE /_security/role/engineering-viewer
DELETE /_security/role_mapping/saml-engineering

# Отзыв тестовых API keys
POST /_security/api_key/_invalidate
{
  "name": "filebeat-production"
}

# Отключение аудита (до 9.4 — удаление настроек из elasticsearch.yml + rolling restart)
PUT /_cluster/settings
{
  "persistent": {
    "xpack.security.audit.enabled": null
  }
}
```

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — базовая безопасность, TLS, RBAC.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — Spaces, RBAC в Kibana.
* **[Alerting](./elasticsearch_alerting.md)** — алертинг на события безопасности.
* **[Cross-Cluster Replication](./elasticsearch_ccr_ccs.md)** — API Keys для CCR/CCS.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — TLS конфигурация.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — ILM для audit logs.
