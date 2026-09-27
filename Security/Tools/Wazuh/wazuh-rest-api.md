# REST API Wazuh: автоматизация и управление

## Определения

**Wazuh REST API** — HTTP-интерфейс менеджера Wazuh (порт 55000, HTTPS), предоставляющий программный доступ к управлению агентами, конфигурациями, правилами, индексами и алертами. В **Wazuh 5.0+** API унифицирован и поддерживает JWT-аутентификацию через Bearer-токены.

**JWT (JSON Web Token)** — токен аутентификации, выдаваемый API после успешного входа (login). Содержит имя пользователя, права доступа и TTL. Используется во всех последующих запросах через заголовок `Authorization: Bearer <token>`.

**API Controller** — внутренний компонент Wazuh Manager, обрабатывающий REST-запросы и маршрутизирующий их к подсистемам (агенты, правила, конфигурация, индексы). В 5.0+ работает асинхронно с поддержкой pagination.

**Pagination** — механизм постраничной выборки данных. API возвращает до 500 элементов за запрос. Для получения полного набора данных используйте параметры `offset` и `limit`.

## Основные концепции

### Архитектура API

```
Клиент (curl/python/Ansible)
  │
  ▼ HTTPS (порт 55000)
Wazuh Manager
  │
  ├── JWT Auth ──→ /security/user/authenticate
  ├── Agents ────→ /agents, /agents-group, /agents/upgrade
  ├── Rules ─────→ /rules, /rules/files, /rules/ggroups
  ├── Decoders ──→ /decoders, /decoders/files
  ├── Manager ───→ /manager, /manager/configuration
  ├── Cluster ───→ /cluster, /cluster/nodes
  ├── Indexer ───→ /indexer, /indexer/stats
  └── Security ──→ /security, /security/roles, /security/policies
```

### Аутентификация

В Wazuh 5.0 аутентификация обязательна для всех запросов (кроме health-check на порту 55000):

```bash
# Получение JWT-токена
TOKEN=$(curl -k -X POST "https://localhost:55000/security/user/authenticate" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"SecretPassword"}' | jq -r '.data.token')
```

**Создание API-пользователей (Wazuh 5.0):**
```bash
# Через wazuh-security
/var/wazuh-manager/bin/wazuh-security api-user add -n automation -r admin -p "StrongPassword123"
```

### Основные эндпоинты

| Категория | Эндпоинт | Метод | Назначение |
|:---|:---|:---|:---|
| **Агенты** | `/agents` | GET | Список агентов |
| | `/agents?status=active` | GET | Фильтрация по статусу |
| | `/agents?offset=0&limit=100` | GET | Pagination |
| | `/agents/001` | GET | Данные конкретного агента |
| | `/agents/insert` | POST | Регистрация агента |
| | `/agents/001/group/web-servers` | PUT | Добавление в группу |
| | `/agents/001/upgrade` | PUT | Обновление агента |
| **Правила** | `/rules` | GET | Список правил |
| | `/rules?level=10-16` | GET | Фильтрация по уровню |
| | `/rules?group=sshd` | GET | Фильтрация по группе |
| | `/rules/files` | GET | Файлы правил |
| **Конфигурация** | `/manager/configuration` | GET | Текущая конфигурация |
| | `/manager/configuration/file?section=global` | GET | Конкретный раздел |
| **Кластер** | `/cluster/status` | GET | Статус кластера |
| | `/cluster/nodes` | GET | Узлы кластера |
| **Индексы** | `/indexer/stats` | GET | Статистика индексатора |
| | `/indexer/clear` | DELETE | Очистка индексов |
| **SCA** | `/sca/001` | GET | Результаты SCA для агента |
| **Vulnerability** | `/vulnerability/001` | GET | Уязвимости агента |
| **Модули** | `/manager/status` | GET | Статус модулей |
| **Security** | `/security/roles` | GET | RBAC роли |
| | `/security/policies` | GET | RBAC политики |

### Коды ответов

| Код | Значение | Действие |
|:---|:---|:---|
| `200` | Успех | Обработать JSON |
| `400` | Неверный запрос | Проверить параметры |
| `401` | Не авторизован | Обновить JWT-токен |
| `403` | Доступ запрещён | Проверить роль пользователя |
| `429` | Rate limit | Подождать, добавить retry |
| `500` | Внутренняя ошибка | Проверить логи менеджера |

### Rate Limiting

Wazuh API 5.0 имеет встроенный rate limiter:
- **Лимит**: 300 запросов в минуту на пользователя
- **Превышение**: HTTP 429 с заголовком `Retry-After`
- **Обход**: создайте отдельного API-пользователя для каждого сервиса

## Практические сценарии

### 1. Bash-скрипт: мониторинг отключённых агентов

```bash
#!/bin/bash
set -euo pipefail

API_URL="https://localhost:55000"
USER="monitor"
PASS="MonitorPass123"

# Авторизация
TOKEN=$(curl -sk -X POST "$API_URL/security/user/authenticate" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" | jq -r '.data.token')

# Получение отключённых агентов
DISCONNECTED=$(curl -sk -X GET "$API_URL/agents?status=disconnected&select=id,name,ip,last_keepalive" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json")

COUNT=$(echo "$DISCONNECTED" | jq '.data.total_affected_items')
echo "Отключённых агентов: $COUNT"

if [ "$COUNT" -gt 0 ]; then
  echo "$DISCONNECTED" | jq -r '.data.affected_items[] | "\(.name) (\(.ip)) — last keepalive: \(.last_keepalive)"'

  # Отправка в Telegram (опционально)
  curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
    -d chat_id="$CHAT_ID" \
    -d text="⚠️ Wazuh: $COUNT отключённых агентов"
fi
```

### 2. Python-скрипт: автоматическая регистрация агентов

```python
#!/usr/bin/env python3
import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_URL = "https://localhost:55000"
USERNAME = "admin"
PASSWORD = "AdminPass123"

class WazuhAPI:
    def __init__(self, url, username, password):
        self.url = url
        self.session = requests.Session()
        self.session.verify = False
        self.token = self._authenticate(username, password)

    def _authenticate(self, username, password):
        resp = self.session.post(
            f"{self.url}/security/user/authenticate",
            json={"username": username, "password": password}
        )
        resp.raise_for_status()
        return resp.json()["data"]["token"]

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def get_agents(self, status=None, offset=0, limit=500):
        params = {"offset": offset, "limit": limit}
        if status:
            params["status"] = status
        resp = self.session.get(f"{self.url}/agents", headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json()["data"]

    def register_agent(self, name, ip, group="default"):
        resp = self.session.post(
            f"{self.url}/agents/insert",
            headers=self._headers(),
            json={"name": name, "ip": ip, "group": group}
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def get_agent_key(self, agent_id):
        resp = self.session.get(
            f"{self.url}/agents/{agent_id}/key",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def assign_group(self, agent_id, group_name):
        resp = self.session.put(
            f"{self.url}/agents/{agent_id}/group/{group_name}",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def get_sca_results(self, agent_id):
        resp = self.session.get(
            f"{self.url}/sca/{agent_id}",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def get_vulnerabilities(self, agent_id):
        resp = self.session.get(
            f"{self.url}/vulnerability/{agent_id}",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()["data"]

# Использование
api = WazuhAPI(API_URL, USERNAME, PASSWORD)

# Список всех агентов
agents = api.get_agents(status="active")
print(f"Активных агентов: {agents['total_affected_items']}")

# Регистрация нового агента
result = api.register_agent("web-05", "10.0.1.15", group="web-servers")
print(f"Агент зарегистрирован: {result}")
```

### 3. Ansible: автоматизация через URI-модуль

```yaml
---
- name: Wazuh API Automation
  hosts: localhost
  gather_facts: no
  vars:
    wazuh_api: "https://localhost:55000"
    wazuh_user: "admin"
    wazuh_pass: "AdminPass123"
  tasks:
    - name: Authenticate
      uri:
        url: "{{ wazuh_api }}/security/user/authenticate"
        method: POST
        body_format: json
        body:
          username: "{{ wazuh_user }}"
          password: "{{ wazuh_pass }}"
        validate_certs: no
        status_code: 200
      register: auth_result

    - name: Get token
      set_fact:
        wazuh_token: "{{ auth_result.json.data.token }}"

    - name: Get all agents
      uri:
        url: "{{ wazuh_api }}/agents?status=active&select=id,name,ip"
        method: GET
        headers:
          Authorization: "Bearer {{ wazuh_token }}"
        validate_certs: no
      register: agents_list

    - name: Print agent count
      debug:
        msg: "Active agents: {{ agents_list.json.data.total_affected_items }}"

    - name: Register new agent
      uri:
        url: "{{ wazuh_api }}/agents/insert"
        method: POST
        body_format: json
        body:
          name: "ansible-test-01"
          ip: "10.0.2.50"
          group: "default"
        headers:
          Authorization: "Bearer {{ wazuh_token }}"
        validate_certs: no
        status_code: 200
      register: new_agent

    - name: Assign to group
      uri:
        url: "{{ wazuh_api }}/agents/{{ new_agent.json.data.id }}/group/ansible-managed"
        method: PUT
        headers:
          Authorization: "Bearer {{ wazuh_token }}"
        validate_certs: no
        status_code: 200
```

### 4. Получение алертов и создание тикетов

```python
#!/usr/bin/env python3
"""Получение критических алертов и экспорт в CSV для тикет-системы."""
import requests
import csv
import json
from datetime import datetime, timedelta

API = "https://localhost:55000"
USER = "analyst"
PASS = "AnalystPass123"

# Авторизация
token = requests.post(
    f"{API}/security/user/authenticate",
    json={"username": USER, "password": PASS},
    verify=False
).json()["data"]["token"]

headers = {"Authorization": f"Bearer {token}"}

# Алерты за последние 24 часа (level >= 10)
yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
alerts = requests.get(
    f"{API}/alerts",
    headers=headers,
    params={
        "level": "10-16",
        "sort": "-timestamp",
        "limit": 500,
        "q": f"timestamp>{yesterday}"
    },
    verify=False
).json()["data"]

# Экспорт в CSV
with open(f"/tmp/wazuh_alerts_{datetime.now().strftime('%Y%m%d')}.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["ID", "Timestamp", "Rule", "Level", "Agent", "Description"])
    for alert in alerts.get("affected_items", []):
        writer.writerow([
            alert.get("id"),
            alert.get("timestamp"),
            alert.get("rule", {}).get("id"),
            alert.get("rule", {}).get("level"),
            alert.get("agent", {}).get("name"),
            alert.get("rule", {}).get("description")
        ])

print(f"Экспортировано {alerts.get('total_affected_items', 0)} алертов")
```

### 5. БULK-обновление агентов

```bash
#!/bin/bash
# Массовое добавление агентов в группу
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Список агентов для добавления в группу "production"
AGENT_IDS=$(curl -sk "$API/agents?status=active&select=id,ip" \
  -H "Authorization: Bearer $TOKEN" | \
  jq -r '.data.affected_items[] | select(.ip | startswith("10.0.1.")) | .id')

for ID in $AGENT_IDS; do
  curl -sk -X PUT "$API/agents/$ID/group/production" \
    -H "Authorization: Bearer $TOKEN" && \
    echo "Agent $ID added to production" || \
    echo "Failed to add agent $ID"
done
```

### 6. Экспорт инвентаря агентов

```python
#!/usr/bin/env python3
"""Экспорт полного инвентаря агентов для аудита."""
import requests, json, csv

API = "https://localhost:55000"
token = requests.post(
    f"{API}/security/user/authenticate",
    json={"username": "admin", "password": "AdminPass123"},
    verify=False
).json()["data"]["token"]

headers = {"Authorization": f"Bearer {token}"}
all_agents = []
offset = 0

while True:
    resp = requests.get(
        f"{API}/agents",
        headers=headers,
        params={"offset": offset, "limit": 500, "select": "id,name,ip,os,version,group,status"},
        verify=False
    ).json()["data"]
    all_agents.extend(resp["affected_items"])
    if len(resp["affected_items"]) < 500:
        break
    offset += 500

# CSV
with open("/tmp/wazuh_inventory.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ID", "Name", "IP", "OS", "Version", "Group", "Status"])
    for a in all_agents:
        w.writerow([a.get("id"), a.get("name"), a.get("ip"),
                     a.get("os",{}).get("name","N/A"), a.get("version"),
                     a.get("group","default"), a.get("status")])

print(f"Total agents: {len(all_agents)}")
```

### 7. Health check через API (для LB)

```bash
#!/bin/bash
# Проверка здоровья Wazuh Manager для HAProxy/Nginx health check
HEALTH=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost:55000/health)

if [ "$HEALTH" = "200" ]; then
  exit 0
else
  exit 1
fi
```

### 8. Получение результатов SCA для compliance-отчёта

```bash
#!/bin/bash
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Все агенты с failed checks
for AGENT_ID in $(curl -sk "$API/agents?status=active&select=id" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.data.affected_items[].id'); do

  FAILED=$(curl -sk "$API/sca/$AGENT_ID?select=pass,fail" \
    -H "Authorization: Bearer $TOKEN" | \
    jq '.data.affected_items[0] | {pass: .pass, fail: .fail}')

  FAIL_COUNT=$(echo "$FAILED" | jq -r '.fail')
  if [ "$FAIL_COUNT" -gt 0 ]; then
    AGENT_NAME=$(curl -sk "$API/agents/$AGENT_ID?select=name" \
      -H "Authorization: Bearer $TOKEN" | jq -r '.data.affected_items[0].name')
    echo "Agent $AGENT_NAME (ID:$AGENT_ID): $FAIL_COUNT failed checks"
  fi
done
```

## Дополнительная информация

### Безопасность API

1. **HTTPS обязателен**: отключите HTTP на порту 55000.
2. **Отдельные пользователи**: не используйте `admin` для автоматизации; создайте API-пользователя с ограниченными правами.
3. **IP-whitelist**: ограничьте доступ к API через firewall (iptables/ufw).
4. **Ротация токенов**: JWT имеет TTL (по умолчанию 900 секунд). Для долгоживущих скриптов обновляйте токен.
5. **Audit log**: все API-запросы логируются в `/var/wazuh-manager/logs/api.log`.

### Производительность

- **Pagination**: всегда используйте `limit` и `offset` для больших наборов данных.
- **Select**: используйте `select` для выборки только нужных полей (снижает нагрузку).
- **Batch operations**: группируйте операции (bulk group assignment) вместо одиночных запросов.
- **Connection pooling**: в Python используйте `requests.Session()` для повторного использования TCP-соединений.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **401 Unauthorized** | Токен истёк | Получите новый через `/security/user/authenticate` |
| **403 Forbidden** | Недостаточно прав | Проверьте роль пользователя: `/security/roles` |
| **429 Too Many Requests** | Rate limit | Уменьшите частоту запросов или создайте отдельного пользователя |
| **SSL certificate verify failed** | Самоподписанный сертификат | Используйте `-k` (curl) или `verify=False` (Python) |
| **Connection refused** | API не запущен | Проверьте `systemctl status wazuh-manager` |
| **Empty response** | Нет данных по фильтру | Проверьте параметры фильтрации |

### См. также
- [Развертывание Wazuh](./deployment.md) — настройка API-порта и сертификатов.
- [Мониторинг здоровья](./wazuh-health-monitoring.md) — health endpoint и метрики.
- [Автоматизация через Ansible](./ansible-automation-per-agent.md) — mass deployment.
