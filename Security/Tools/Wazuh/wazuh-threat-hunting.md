# Threat Hunting в Wazuh: ретроспективный анализ и поиск угроз

## Определения

**Threat Hunting** — процесс активного поиска угроз в инфраструктуре, предполагающий ретроспективный анализ данных без заранее заданного алерта. В отличие от реактивного мониторинга, hunting начинается с гипотезы и проверяет данные за прошлые периоды.

**KQL (Kibana Query Language)** — язык запросов OpenSearch Dashboards для фильтрации событий по полям. Поддерживает wildcard, диапазоны, булевы операторы. Основной инструмент threat hunting в Wazuh Dashboard.

**PPL (Piped Processing Language)** — язык обработки данных OpenSearch, похожий на管道. Используется для агрегаций, подсчётов, сортировок и сложных вычислений поверх KQL-фильтров.

**IOC (Indicator of Compromise)** — индикатор компрометации: IP-адрес, домен, хеш файла, URL, имённик, который указывает на вредоносную активность. IOC загружаются из Wazuh CTI Feed или внешних источников (OTX, MISP).

**MITRE ATT&CK** — глобальная база тактик и техник кибератак. Wazuh 5.0 нативно маппит правила на MITRE v16+ с автоматическим обновлением.

**Sigma Rule** — открытый формат описания правил обнаружения угроз в YAML. Позволяет переиспользовать правила между SIEM-системами.

## Основные концепции

### Модель Threat Hunting

```
┌─────────────────────────────────────────────────┐
│  1. ГИПОТЕЗА                                     │
│  "Lateral movement через SMB из компрометированного хоста" │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│  2. ПОИСК ДАННЫХ (Wazuh API / Dashboard)         │
│  KQL: event_channel:"Microsoft-Windows-SMB*"     │
│  AND srcip:10.0.1.50 NOT dstip:10.0.1.0/24      │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│  3. АНАЛИЗ                                      │
│  Визуализация топологии, подсчёт частоты,       │
│  сопоставление с MITRE                          │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│  4. РЕШЕНИЕ                                     │
│  Новый规则 / обновление CDB / эскалация IR      │
└─────────────────────────────────────────────────┘
```

### Источники данных для hunting

| Источник | Что даёт | Где искать |
|:---|:---|:---|
| **wazuh-events** | Все события (Full Visibility) | OpenSearch Index |
| **SCA results** | Конфигурация хостов | `/sca/{agent_id}` |
| **Vulnerability findings** | Уязвимости | `/vulnerability/{agent_id}` |
| **FIM changes** | Изменения файлов | `syscheck` events |
| **Sysmon** | Windows-события (процессы, сеть, реестр) | `eventchannel` |
| **Audit (Linux)** | Syscalls, open, execve | `audit` logs |

### Типичные hunting-запросы (KQL)

| Цель | KQL-запрос |
|:---|:---|
| PowerShell от нестандартного пользователя | `data.win.eventdata.scriptBlockText:* AND NOT data.win.system.user:*System*` |
| SSH с нового IP | `rule.group:sshd AND srcip:* NOT srcip:10.0.0.0/8` |
| Новые процессы | `data.win.eventdata.originalFileName:* AND NOT data.win.eventdata.image:*System32*` |
| Outbound SMB | `event_channel:"Microsoft-Windows-SmbClient*" AND data.win.eventdata.shareName:\\*` |
| Scheduled Task создан | `data.win.eventdata.eventID:4698` |
| WMI-запрос | `data.win.eventdata.eventID:4688 AND data.win.eventdata.parentImage:*WmiPrvSE*` |
| DNS-запрос на подозрительный домен | `data.win.eventdata.queryName:*.*.top OR data.win.eventdata.queryName:*.*.xyz` |
| Массовый outbound трафик | `data.network.bytes:>10000000 AND NOT dstip:10.0.0.0/8` |

## Практические сценарии

### 1. Поиск Lateral Movement через SSH

**Гипотеза**: атакующий перемещается между хостами через SSH после компрометации одного сервера.

```bash
#!/bin/bash
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Поиск SSH-сессий с необычных IP (не из корпоративного диапазона)
curl -sk -X GET "$API/alerts" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-urlencode "q=rule.group:sshd" \
  --data-urlencode "q=NOT srcip:10.0.0.0/8" \
  --data-urlencode "q=NOT srcip:192.168.0.0/16" \
  --data-urlencode "select=srcip,agent.name,timestamp,rule.description" \
  --data-urlencode "limit=100" | jq '.data.affected_items[] | {ip: .srcip, host: .agent.name, time: .timestamp}'
```

### 2. Обнаружение PowerShell-обфускации

**Гипотеза**: атакующий использует обфусцированный PowerShell для обхода EDR.

```kql
# В OpenSearch Dashboards (KQL)
data.win.eventdata.scriptBlockText:(*FromBase64String* OR *Invoke-Expression* OR *IEX* OR *DownloadString* OR *Net.WebClient*)
AND NOT data.win.system.user:*SYSTEM*
AND NOT data.win.eventdata.parentImage:*powershell.exe
```

```bash
# Через API
curl -sk -X GET "https://localhost:9200/wazuh-events-*/_search" \
  -u admin:admin \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "bool": {
        "must": [
          {"match": {"data.win.eventdata.scriptBlockText": "FromBase64String"}},
          {"match": {"data.win.eventdata.scriptBlockText": "Invoke-Expression"}}
        ],
        "must_not": [
          {"wildcard": {"data.win.system.user": "*SYSTEM*"}}
        ]
      }
    },
    "_source": ["agent.name", "data.win.eventdata.scriptBlockText", "timestamp"],
    "size": 50
  }' | jq '.hits.hits[]._source'
```

### 3. Поиск DNS-туннелинга

**Гипотеза**: атакующий использует DNS для exfiltration данных.

```kql
data.win.eventdata.queryName:(*.*.*.*.*.*.*) OR data.win.eventdata.queryName.length:>50
AND data.win.eventdata.queryType:1
```

```python
#!/usr/bin/env python3
"""Поиск подозрительных DNS-запросов (длина домена > 50 символов, множественные субдомены)."""
import requests
import json

API = "https://localhost:9200"
token = requests.post(
    "https://localhost:55000/security/user/authenticate",
    json={"username": "admin", "password": "AdminPass123"},
    verify=False
).json()["data"]["token"]

# Поиск DNS-запросов с длинными именами
query = {
    "size": 100,
    "query": {
        "bool": {
            "must": [
                {"term": {"data.win.eventdata.queryType": "1"}},
                {"script": {
                    "script": {
                        "source": "doc['data.win.eventdata.queryName.keyword'].value.length() > 50"
                    }
                }}
            ]
        }
    },
    "aggs": {
        "by_agent": {
            "terms": {"field": "agent.name.keyword", "size": 20}
        }
    }
}

results = requests.post(
    f"{API}/wazuh-events-*/_search",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    json=query,
    verify=False
).json()

print(f"Найдено: {results['hits']['total']['value']} подозрительных DNS-запросов")
for hit in results["hits"]["hits"][:10]:
    src = hit["_source"]
    print(f"  [{src['timestamp']}] {src['agent']['name']} → {src['data']['win']['eventdata']['queryName']}")
```

### 4. Обнаружение CreateProcess из необычного父ителя

**Гипотеза**: атакующий запускает процессы из необычных родительских процессов (например, Word запускает cmd.exe).

```kql
data.win.eventdata.eventID:4688
AND data.win.eventdata.parentImage:(*WINWORD.EXE* OR *EXCEL.EXE* OR *OUTLOOK.EXE* OR *POWERPNT.EXE*)
AND data.win.eventdata.newProcessImage:(*cmd.exe* OR *powershell.exe* OR *wscript.exe* OR *cscript.exe*)
```

### 5. Поиск lateral movement через WMI

```kql
data.win.eventdata.eventID:4688
AND data.win.eventdata.parentImage:*WmiPrvSE.exe
AND data.win.eventdata.newProcessImage:(*cmd.exe* OR *powershell.exe*)
```

### 6. Обнаружение persistence через Scheduled Tasks

```kql
data.win.eventdata.eventID:4698
AND NOT data.win.eventdata.taskName:*Microsoft*
AND NOT data.win.eventdata.taskName:*Google*
```

```bash
# Через API: все созданные scheduled tasks за последние 24ч
curl -sk "https://localhost:9200/wazuh-events-*/_search" \
  -u admin:admin -H "Content-Type: application/json" \
  -d '{
    "query": {
      "bool": {
        "must": [
          {"term": {"data.win.eventdata.eventID": "4698"}},
          {"range": {"timestamp": {"gte": "now-24h"}}}
        ]
      }
    },
    "_source": ["agent.name", "data.win.eventdata.taskName", "timestamp"],
    "size": 200
  }' | jq '.hits.hits[]._source'
```

### 7.狩猎 через Sigma-правила

**Создание custom Sigma-правила для hunting:**

```yaml
# /var/wazuh-manager/etc/rules/sigma/hunting_suspicious_dnscat.yml
title: DNS Tunneling - dnscat2
id: 900001
status: experimental
description: Detects DNS queries associated with dnscat2 tunnel
references:
  - https://github.com/iagox86/dnscat2
logsource:
    product: windows
    service: sysmon
detection:
    selection:
        EventID: 22
        QueryName|endswith:
            - '.dnscat.com'
            - '.cmd.cat.com'
            - '.r.jina.ai'
    condition: selection
falsepositives:
    - Legitimate DNS tunneling tools
level: high
tags:
    - attack.command_and_control
    - attack.t1071.004
```

### 8. Hunting playbook: компрометация учётной записи

```
Шаг 1: Поиск brute-force алертов за 7 дней
  KQL: rule.id:(5720 OR 5716) AND rule.level:>=10
  → Источники атак, целевые аккаунты

Шаг 2: Поиск успешных входов после brute-force
  KQL: rule.group:authentication AND data.action:success
  AND srcip:<attacker_ip>
  → Учётные записи, которые были скомпрометированы

Шаг 3: Поиск активности от скомпрометированных аккаунтов
  KQL: data.win.system.user:<compromised_user>
  ИЛИ data.ssh.user:<compromised_user>
  → Скоуп компрометации

Шаг 4: Поиск persistence
  KQL: data.win.eventdata.eventID:(4698 OR 4697 OR 4720)
  AND data.win.system.user:<compromised_user>

Шаг 5: Поиск exfiltration
  KQL: data.network.bytes:>10000000
  AND (srcip:<compromised_host> ИЛИ dstip:<compromised_host>)
```

## Дополнительная информация

### Автоматизация Threat Hunting

1. **Scheduled reports**: настройте еженедельные отчёты через API + cron
2. **Sigma-правила как гипотезы**: создавайте hunting-правила с `noalert="1"` для сбора данных
3. **ML-интеграция**: Wazuh 5.0 поддерживает anomaly detection через OpenSearch ML

### Hunting-стратегии

| Стратегия | Описание | Когда использовать |
|:---|:---|:---|
| **IOC-based** | Поиск конкретных IP/хешей/доменов | После получения threat intel |
| **TTP-based** | Поиск поведения по MITRE тактикам | Проактивный hunting |
| **Anomaly-based** | Поиск отклонений от baseline | Регулярный мониторинг |
| **Hypothesis-based** | Проверка конкретной гипотезы | По request от IR-команды |

### Интеграция с CTI

Wazuh 5.0 автоматически загружает IOC из Wazuh CTI Feed:
- IP-адреса тактических серверов
- Хеши вредоносных файлов
- Домены C2-серверов

IOC обновляются в реальном времени через внутренний коннектор.

### Best Practices

1. **Базeline**: сначала постройте baseline нормальной активности, затем ищите отклонения.
2. **Time window**: начинайте с 24ч, расширяйте до 7–30 дней.
3. **Documentation**: записывайте каждую гипотезу, найденные данные и выводы.
4. **Feedback loop**: результаты hunting → новые правила → автоматическое обнаружение.
5. **Тюнинг**: после hunting обновляйте CDB-списки и правила для снижения FP.

### См. также
- [Правила корреляции](./wazuh-rules.md) — создание правил по результатам hunting.
- [SCA](./wazuh-sca.md) — проверка конфигурации как source of truth.
- [Vulnerability Detection](./wazuh-vulnerability-detector.md) — уязвимости как hunting input.
