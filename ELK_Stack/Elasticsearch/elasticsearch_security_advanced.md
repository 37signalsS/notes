# Security Advanced: DLS, FLS, Audit Logging

> Продвинутое руководство по безопасности Elasticsearch. Рассматриваются Document-Level Security, Field-Level Security, Audit Logging, SAML/OIDC интеграция и Kibana Spaces.
>
> Связанные темы: базовая безопасность — [Elasticsearch Overview](./elasticsearch_overview.md); CCR/CCS — [Cross-Cluster](./elasticsearch_ccr_ccs.md).

## Определения

* **Document-Level Security (DLS)** — ограничение доступа к документам внутри индекса на основе условий запроса.
* **Field-Level Security (FLS)** — ограничение доступа к отдельным полям документа.
* **Role** — набор привилегий на уровне кластера, индексов, документов и полей.
* **User** — учетная запись с назначенными ролями.
* **Realm** — источник аутентификации (native, LDAP, SAML, OIDC, PKI, Kerberos).
* **Audit Logging** — запись всех действий пользователей и системных событий для compliance.
* **Kibana Spaces** — изолированные рабочие пространства в Kibana для разных команд/проектов.
* **API Key** — ключ для программного доступа без использования пароля.

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

### Ограничения DLS

- DLS применяется ко всем запросам (search, aggregation, get)
- Агрегации считаются только по видимым документам
- DLS может влиять на производительность (дополнительный фильтр)
- Нельзя использовать DLS с `write` привилегиями

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

- FLS не защищает от aggregation по excluded полям (используйте DLS)
- `_source` фильтрация работает на уровне ответа
- FLS не применяется к system fields (_id, _index, _score)
- Нельзя использовать FLS с `write` привилегиями

## Audit Logging

### Включение Audit Logging

```yaml
# elasticsearch.yml
xpack.security.audit.enabled: true

# Дополнительные настройки
xpack.security.audit.logfile.events.include:
  - access_denied
  - access_granted
  - authentication_failed
  - connection_denied
  - tampered_request
  - run_as_denied
  - run_as_granted

xpack.security.audit.logfile.events.exclude:
  - access_allowed  # Может быть слишком шумным

xpack.security.audit.logfile.events.emit_request_body: true
```

### Структура audit события

```json
{
  "@timestamp": "2026-08-23T10:30:00.000Z",
  "node.id": "abc123",
  "node.name": "es-node-1",
  "event.type": "transport",
  "event.action": "access_granted",
  "authentication.type": "REALM",
  "user.name": "john",
  "user.run_by.name": "elastic",
  "user.run_as.name": "john",
  "user.realm": "native",
  "user.roles": ["engineering-viewer"],
  "origin.type": "REST",
  "origin.address": "10.0.0.1:54321",
  "realm": "native",
  "url.path": "/logs-*/_search",
  "url.query": "size=100",
  "request.method": "GET",
  "request.body": "{...}",
  "request.id": "abc-def-123"
}
```

### Типы событий

| Событие | Описание |
|---------|----------|
| `access_granted` | Успешный доступ |
| `access_denied` | Отказано в доступе |
| `authentication_failed` | Ошибка аутентификации |
| `authentication_success` | Успешная аутентификация |
| `connection_denied` | Отказано в соединении |
| `tampered_request` | Подмененный запрос |
| `run_as_denied` | Отказано в impersonation |
| `run_as_granted` | Разрешен impersonation |
| `realm_authentication_failed` | Ошибка realm |

### Анализ Audit Logs

```bash
# Поиск отказов в доступе
GET .security-audit-log-*/_search
{
  "query": {
    "term": { "event.action": "access_denied" }
  },
  "sort": [{ "@timestamp": "desc" }]
}

# Топ пользователей по отказам
GET .security-audit-log-*/_search
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
GET .security-audit-log-*/_search
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
```

### Хранение Audit Logs

```yaml
# ILM для audit logs
PUT _ilm/policy/audit-logs
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "50GB",
            "max_age": "30d"
          }
        }
      },
      "delete": {
        "min_age": "365d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

## SAML/OIDC интеграция

### Настройка SAML Realm

```yaml
# elasticsearch.yml
xpack.security.authc.realms.saml.saml1:
  order: 2
  idp.metadata.path: "/path/to/idp-metadata.xml"
  idp.entity_id": "https://idp.company.com/entity"
  sp.entity_id": "https://kibana.company.com"
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
4. **Настройте ILM** — автоматическое удаление старых логов

### Kibana Spaces

1. **Одна команда = один Space** — изоляция данных и дашбордов
2. **Ограничьте features** — отключите неиспользуемые возможности
3. **Space-specific roles** — не используйте all-spaces роли без необходимости

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — базовая безопасность, TLS, RBAC.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — Spaces, RBAC в Kibana.
* **[Alerting](./elasticsearch_alerting.md)** — алертинг на события безопасности.
* **[Cross-Cluster Replication](./elasticsearch_ccr_ccs.md)** — API Keys для CCR/CCS.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — TLS конфигурация.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — ILM для audit logs.
