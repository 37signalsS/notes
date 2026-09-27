# Multi-Tenancy и RBAC в Wazuh

## Определения

**Multi-Tenancy** — архитектура, при которой один экземпляр Wazuh обслуживает несколько независимых организаций (тенантов). Каждый тенант видит только свои агенты, алерты и конфигурации.

**RBAC (Role-Based Access Control)** — модель управления доступом, при которой права назначаются ролям (admin, analyst, readonly), а роли — пользователям. В Wazuh 5.0 RBAC интегрирован с OpenSearch Security.

**Tenant** — логическое изолированное пространство в Wazuh. Каждый тенант имеет собственные: агентов, правила, конфигурации, dashboards, индексы.

**Security Role** — роль OpenSearch Security, определяющая доступ к индексам, API-эндпоинтам и операциям. Wazuh 5.0 использует встроенные роли и позволяет создавать кастомные.

**Policy** — набор разрешений (index, cluster, application) для конкретной роли в RBAC-модели Wazuh.

## Основные концепции

### Архитектура RBAC

```
┌──────────────────────────────────────────────────────┐
│                  Wazuh Manager                        │
│                                                       │
│  ┌──────────────────────────────────────────────────┐│
│  │ OpenSearch Security RBAC                         ││
│  │  Roles: admin, analyst, readonly, custom         ││
│  │  Policies: index_access, cluster_access          ││
│  │  Users: local + SSO (Authentik, Keycloak)        ││
│  └──────────────────────────────────────────────────┘│
│                                                       │
│  ┌──────────────────────────────────────────────────┐│
│  │ Wazuh API Roles                                  ││
│  │  /security/roles → assigns API permissions       ││
│  │  /security/policies → defines allowed actions    ││
│  └──────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
         │
         ├── Tenant A: agents-001..050, rules-a, dashboards-a
         ├── Tenant B: agents-051..100, rules-b, dashboards-b
         └── Tenant C: agents-101..150, rules-c, dashboards-c
```

### Встроенные роли Wazuh 5.0

| Роль | Описание | Доступ |
|:---|:---|:---|
| `admin` | Полный доступ | Все API, все индексы, все операции |
| `analyst` | Аналитик | Чтение алертов, agents, rules; ограниченная запись |
| `readonly` | Только чтение | Dashboard, API GET-запросы |
| `custom` | Кастомная роль | Определяется политиками |

## Практические сценарии

### 1. Создание кастомной роли через API

```bash
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Создание политики: доступ только к агентам группы "web-servers"
curl -sk -X POST "$API/security/policies" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "web-servers-policy",
    "policy": {
      "actions": ["agents:read", "agents:read_config"],
      "resources": ["agent:group:web-servers"],
      "effect": "allow"
    }
  }'

# Создание роли分析师 для веб-серверов
curl -sk -X POST "$API/security/roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "web-analyst",
    "policies": ["web-servers-policy"],
    "rules": []
  }'
```

### 2. Создание пользователя с ограниченными правами

```bash
# Создание пользователя
curl -sk -X POST "$API/security/users" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "web-analyst-01",
    "password": "AnalystPass123",
    "roles": ["web-analyst"]
  }'
```

### 3. Multi-Tenant через OpenSearch Security

```yaml
# /etc/wazuh-indexer/opensearch-security/roles.yml
wazuh_web_analyst:
  index_permissions:
    - index_patterns:
        - "wazuh-events-web-*"
      allowed_actions:
        - "read"
        - "view_index_metadata"
  cluster_permissions:
    - "cluster:monitor/health"

wazuh_db_analyst:
  index_permissions:
    - index_patterns:
        - "wazuh-events-db-*"
      allowed_actions:
        - "read"
        - "view_index_metadata"
  cluster_permissions:
    - "cluster:monitor/health"
```

### 4. Разделение агентов по тенантам

```python
#!/usr/bin/env python3
"""Разделение агентов по тенантам на основе IP-диапазонов."""
import requests

API = "https://localhost:55000"
token = requests.post(
    f"{API}/security/user/authenticate",
    json={"username": "admin", "password": "AdminPass123"},
    verify=False
).json()["data"]["token"]
headers = {"Authorization": f"Bearer {token}"}

# Тенанты и их IP-диапазоны
TENANTS = {
    "tenant-a": {"prefix": "10.0.1.", "group": "tenant-a"},
    "tenant-b": {"prefix": "10.0.2.", "group": "tenant-b"},
    "tenant-c": {"prefix": "10.0.3.", "group": "tenant-c"},
}

# Назначение агентов по тенантам
offset = 0
while True:
    agents = requests.get(
        f"{API}/agents",
        headers=headers,
        params={"offset": offset, "limit": 500, "select": "id,name,ip,group"},
        verify=False
    ).json()["data"]

    for agent in agents["affected_items"]:
        ip = agent.get("ip", "")
        for tenant, config in TENANTS.items():
            if ip.startswith(config["prefix"]):
                current_group = agent.get("group", "default")
                if current_group != config["group"]:
                    requests.put(
                        f"{API}/agents/{agent['id']}/group/{config['group']}",
                        headers=headers, verify=False
                    )
                    print(f"Agent {agent['name']} ({ip}) → {tenant}")
                break

    if len(agents["affected_items"]) < 500:
        break
    offset += 500
```

### 5. Кастомные правила для тенантов

```xml
<!-- rules для tenant-a: только SSH-события -->
<group name="tenant-a,">
  <rule id="100001" level="5">
    <decoded_as>json</decoded_as>
    <field name="agent.group">tenant-a</field>
    <field name="rule.group">sshd</field>
    <description>SSH event from tenant-a</description>
  </rule>
</group>

<!-- rules для tenant-b: только database-события -->
<group name="tenant-b,">
  <rule id="100002" level="5">
    <decoded_as>json</decoded_as>
    <field name="agent.group">tenant-b</field>
    <field name="rule.group">mysql,postgresql</field>
    <description>Database event from tenant-b</description>
  </rule>
</group>
```

### 6. API: получение данных только для тенанта

```bash
#!/bin/bash
# Запрос алертов только для tenant-a
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"web-analyst-01","password":"AnalystPass123"}' | jq -r '.data.token')

# Алерты только от агентов группы tenant-a
curl -sk "$API/alerts?group=tenant-a&limit=100" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.affected_items[] | {rule: .rule.description, agent: .agent.name}'
```

### 7. Настройка SSO для Multi-Tenant

```yaml
# Authentik: маппинг тенантов через SAML
# custom_property_mapping.py
def get_tenant_from_user(user):
    """Определяет тенант на основе атрибутов пользователя."""
    groups = user.groups.all()
    for group in groups:
        if group.name.startswith("wazuh-tenant-"):
            return group.name.replace("wazuh-tenant-", "")
    return "default"

# SAML attribute mapping
SAML_ATTRIBUTES = {
    "wazuh_tenant": "get_tenant_from_user",
    "wazuh_role": "get_wazuh_role",
}
```

## Дополнительная информация

### Best Practices

1. **Изоляция**: каждый тенант = отдельная группа агентов + отдельные правила.
2. **RBAC**:最小权限 principle — давайте только необходимые права.
3. **SSO**: используйте SAML/OIDC для централизованного управления пользователями.
4. **Audit**: логируйте все API-запросы для аудита доступа.
5. **Именование**: `tenant-{name}`, `{role}-{scope}` для ясности.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **User can't see agents** | RBAC restrictions | Проверьте роль пользователя |
| **API returns 403** | Insufficient permissions | Проверьте policies для роли |
| **Tenant data leak** | Misconfigured group filter | Проверьте group-based rules |
| **SSO login fails** | SAML attribute mapping | Проверьте property mappings |

### См. также
- [Authentik SSO](./authentik-sso-integration.md) — SAML-интеграция.
- [Agent Groups](./wazuh-agent-groups.md) — группировка агентов.
- [REST API](./wazuh-rest-api.md) — управление через API.
