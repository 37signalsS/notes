# Agent Groups: централизованное управление агентами в Wazuh

## Определения

**Agent Group** — логическая группировка агентов в Wazuh, позволяющая aplicar общие конфигурации, правила и политики к группе агентов одновременно. В **Wazuh 5.0** группы поддерживают иерархическое наследование и автоматическую синхронизацию конфигураций.

**agent.conf** — файл конфигурации группы, размещаемый на менеджере в `/var/wazuh-manager/etc/groups/{group_name}/agent.conf`. Передаётся агентам группы при подключении и переопределяет локальные настройки `ossec.conf`.

**Group Configuration** — набор правил, wodle, декодеров и скриптов, применяемых к агентам группы. Конфигурация группы имеет приоритет над локальной конфигурацией агента.

**Multi-group** — возможность назначить агенту несколько групп. Конфигурации всех групп объединяются (merge). Приоритет: последняя назначенная группа.

**Centralized Configuration** — модель управления, при которой конфигурации хранятся централизованно на менеджере и автоматически распространяются на агенты.

## Основные концепции

### Архитектура управления группами

```
Менеджер Wazuh
├── /var/wazuh-manager/etc/groups/
│   ├── default/
│   │   └── agent.conf          ← дефолтная конфигурация
│   ├── web-servers/
│   │   └── agent.conf          ← для веб-серверов
│   ├── db-servers/
│   │   └── agent.conf          ← для баз данных
│   └── windows-workstations/
│       └── agent.conf          ← для Windows
│
├── Агент "web-01" (группа: web-servers)
├── Агент "web-02" (группа: web-servers)
├── Агент "db-01" (группа: db-servers)
└── Агент "ws-01" (группа: windows-workstations)
```

### Приоритет конфигураций

```
1. System ruleset       (низкий приоритет)
2. default group        (средний приоритет)
3. custom group         (высокий приоритет)
4. local_rules.xml      (максимальный приоритет)
```

При multi-group наследование идёт последовательно: `group1` → `group2` → `group3`. Последняя группа перезаписывает конфликты.

### Структура agent.conf

Файл `agent.conf` использует тот же синтаксис, что и `ossec.conf`:

```xml
<ossec_config>
  <!-- Лог-коллекция -->
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/auth.log</location>
  </localfile>

  <!-- FIM -->
  <syscheck>
    <directories check_all="yes" whodata="yes">/etc,/usr/bin</directories>
  </syscheck>

  <!-- SCA -->
  <policy>
    <enabled>yes</enabled>
    <interval>12h</interval>
    <scan_on_start>yes</scan_on_start>
  </policy>

  <!-- Внешние скрипты -->
  <wodle name="command">
    <disabled>no</disabled>
    <command>/var/ossec/etc/scripts/custom-check.sh</command>
    <interval>1h</interval>
    <run_on_start>yes</run_on_start>
  </wodle>
</ossec_config>
```

## Практические сценарии

### 1. Создание группы через API

```bash
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Создание группы
curl -sk -X PUT "$API/groups/web-servers" \
  -H "Authorization: Bearer $TOKEN"
```

### 2. agent.conf для веб-серверов (Nginx + Apache)

```xml
<!-- /var/wazuh-manager/etc/groups/web-servers/agent.conf -->
<ossec_config>
  <!-- Логи Nginx -->
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/nginx/access.log</location>
  </localfile>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/nginx/error.log</location>
  </localfile>

  <!-- Логи Apache -->
  <localfile>
    <log_format>apache</log_format>
    <location>/var/log/apache2/access.log</location>
  </localfile>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/apache2/error.log</location>
  </localfile>

  <!-- FIM для Nginx конфигов -->
  <syscheck>
    <directories check_all="yes" whodata="yes">/etc/nginx</directories>
    <directories check_all="yes" whodata="yes">/etc/apache2</directories>
  </syscheck>

  <!-- SCA: CIS Nginx Benchmark -->
  <policy>
    <enabled>yes</enabled>
    <interval>24h</interval>
    <scan_on_start>yes</scan_on_start>
  </policy>

  <!-- Vulnerability Detection -->
  <wodle name="syscollector">
    <disabled>no</disabled>
    <interval>1h</interval>
    <scan_all>yes</scan_all>
  </wodle>
</ossec_config>
```

### 3. agent.conf для PostgreSQL серверов

```xml
<!-- /var/wazuh-manager/etc/groups/db-servers/agent.conf -->
<ossec_config>
  <!-- PostgreSQL логи -->
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/postgresql/postgresql-16-main.log</location>
  </localfile>

  <!-- FIM для postgresql.conf -->
  <syscheck>
    <directories check_all="yes" whodata="yes">/etc/postgresql</directories>
    <directories check_all="yes" whodata="yes">/var/lib/postgresql</directories>
    <ignore type="sregex">/var/lib/postgresql/16/main/pg_wal/*</ignore>
  </syscheck>

  <!-- Мониторинг процесса PostgreSQL -->
  <wodle name="command">
    <disabled>no</disabled>
    <command>psql -U postgres -c "SELECT version();"</command>
    <interval>5m</interval>
    <run_on_start>yes</run_on_start>
    <timeout>10</timeout>
  </wodle>
</ossec_config>
```

### 4. agent.conf для Windows Workstations

```xml
<!-- /var/wazuh-manager/etc/groups/windows-workstations/agent.conf -->
<ossec_config>
  <!-- Windows Event Channels -->
  <localfile>
    <location>Security</location>
    <log_format>eventchannel</log_format>
  </localfile>
  <localfile>
    <location>System</location>
    <log_format>eventchannel</log_format>
  </localfile>
  <localfile>
    <location>Application</location>
    <log_format>eventchannel</log_format>
  </localfile>
  <localfile>
    <location>Microsoft-Windows-PowerShell/Operational</location>
    <log_format>eventchannel</log_format>
  </localfile>

  <!-- FIM для критических путей -->
  <syscheck>
    <directories check_all="yes" whodata="yes">C:\Windows\System32\config</directories>
    <directories check_all="yes" whodata="yes">C:\Users\*\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup</directories>
    <directories check_all="yes">C:\Windows\System32\drivers\etc</directories>
  </syscheck>

  <!-- Syscollector -->
  <wodle name="syscollector">
    <disabled>no</disabled>
    <interval>1h</interval>
    <scan_all>yes</scan_all>
  </wodle>
</ossec_config>
```

### 5. Назначение агентов группам через API

```bash
#!/bin/bash
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Назначение одного агента
curl -sk -X PUT "$API/agents/001/group/web-servers" \
  -H "Authorization: Bearer $TOKEN"

# Bulk-назначение: все агенты с определённым именем
for AGENT in $(curl -sk "$API/agents?select=id,name" \
  -H "Authorization: Bearer $TOKEN" | \
  jq -r '.data.affected_items[] | select(.name | test("^web-")) | .id'); do
  curl -sk -X PUT "$API/agents/$AGENT/group/web-servers" \
    -H "Authorization: Bearer $TOKEN" && echo "Agent $AGENT → web-servers"
done
```

### 6. Автоматическая группировка по IP-диапазону

```python
#!/usr/bin/env python3
"""Автоматическое назначение групп на основе IP-диапазонов."""
import requests
import ipaddress

API = "https://localhost:55000"
token = requests.post(
    f"{API}/security/user/authenticate",
    json={"username": "admin", "password": "AdminPass123"},
    verify=False
).json()["data"]["token"]
headers = {"Authorization": f"Bearer {token}"}

# Определение групп по IP
GROUP_MAP = {
    "10.0.1.0/24": "web-servers",
    "10.0.2.0/24": "db-servers",
    "10.0.3.0/24": "monitoring",
    "192.168.1.0/24": "windows-workstations",
}

# Получение всех агентов
offset = 0
all_agents = []
while True:
    resp = requests.get(
        f"{API}/agents",
        headers=headers,
        params={"offset": offset, "limit": 500, "select": "id,name,ip,group"},
        verify=False
    ).json()["data"]
    all_agents.extend(resp["affected_items"])
    if len(resp["affected_items"]) < 500:
        break
    offset += 500

# Назначение групп
for agent in all_agents:
    agent_ip = agent.get("ip", "")
    current_group = agent.get("group", "default")

    for network, group_name in GROUP_MAP.items():
        if ipaddress.ip_address(agent_ip) in ipaddress.ip_network(network):
            if current_group != group_name:
                requests.put(
                    f"{API}/agents/{agent['id']}/group/{group_name}",
                    headers=headers, verify=False
                )
                print(f"Agent {agent['name']} ({agent_ip}) → {group_name}")
            break
```

### 7. Массовая загрузка agent.conf на все группы

```yaml
---
- name: Deploy agent.conf for all groups
  hosts: wazuh_manager
  become: yes
  vars:
    groups:
      - name: web-servers
        src: files/groups/web-servers/agent.conf
      - name: db-servers
        src: files/groups/db-servers/agent.conf
      - name: windows-workstations
        src: files/groups/windows-workstations/agent.conf
  tasks:
    - name: Create group directories
      file:
        path: "/var/wazuh-manager/etc/groups/{{ item.name }}"
        state: directory
        owner: root
        group: wazuh
        mode: '0750'
      loop: "{{ groups }}"

    - name: Deploy agent.conf
      copy:
        src: "{{ item.src }}"
        dest: "/var/wazuh-manager/etc/groups/{{ item.name }}/agent.conf"
        owner: root
        group: wazuh
        mode: '0640'
      loop: "{{ groups }}"
      notify: restart wazuh-manager

  handlers:
    - name: restart wazuh-manager
      systemd:
        name: wazuh-manager
        state: restarted
```

### 8. Мониторинг распределения агентов по группам

```bash
#!/bin/bash
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Статистика по группам
curl -sk "$API/groups?select=name,total_agents" \
  -H "Authorization: Bearer $TOKEN" | \
  jq -r '.data.affected_items[] | "\(.name): \(.total_agents) agents"'

# Агенты без группы
curl -sk "$API/agents?select=id,name,ip,group&group=default" \
  -H "Authorization: Bearer $TOKEN" | \
  jq '.data.affected_items | length' | \
  xargs -I {} echo "Агентов в default: {}"
```

## Дополнительная информация

### Best Practices

1. **Именование**: используйте осмысленные имена: `web-servers`, `db-postgres`, `windows-ws`, `linux-monitoring`.
2. **Default group**: всегда настраивайте `default` с базовыми правилами (FIM, syscollector).
3. **Multi-group**: используйте для комбинирования политик (например: `web-servers` + `pci-dss`).
4. **agent.conf в Git**: храните все `agent.conf` в Git-репозитории, деплойте через Ansible/CI/CD.
5. **Канареечный деплой**: сначала применяйте новые конфигурации к 1–5% агентов группы.
6. **Имена агентов**: используйте осмысленные имена (hostname, role, environment) для автоматической группировки.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Агент не получает конфигурацию группы** | Синхронизация не завершена | Подождите 10 минут или перезапустите агента |
| **Конфликт конфигураций** | Multi-group с конфликтующими параметрами | Проверьте порядок групп, последняя имеет приоритет |
| **agent.conf не применяется** | Ошибка XML-синтаксиса | Проверьте `wazuh-logtest -t` на менеджере |
| **Группа не создаётся через API** | Дублирование имени | Проверьте существование: `/groups?select=name` |
| **Массовое назначение падает** | Rate limit API | Добавьте `sleep 1` между запросами |

### См. также
- [Развертывание Wazuh](./deployment.md) — установка агентов.
- [Автоматизация через Ansible](./ansible-automation-per-agent.md) — массовое управление.
- [SCA](./wazuh-sca.md) — политики через группы.
