## Определения

- **Network Verification**: Процесс проверки корректности сетевой конфигурации и相关政策 (ACL, routing, firewall) до применения изменений в production. Используется в CI/CD pipeline для предотвращения ошибок.
- **Batfish**: Open-source инструмент для offline analysis и verification сетевых конфигураций. Загружает конфигурации (Cisco, Juniper, Arista, FRR) и выполняет формальные проверки (reachability, ACL correctness, routing compliance).
- **IPFabric**: Платформа для automated network assurance. Discovery-ает топологию, проверяет intent, обнаруживает отклонения от designed state. Коммерческий продукт.
- **NetBox**: Open-source IPAM/DCIM платформа. Используется как Source of Truth для network devices, IP addresses, circuits, power. Интегрируется с automation tools (Ansible, Nornir).
- **Network Source of Truth (SoT)**: Единая база данных для network state (devices, configs, IPs, VLANs, circuits). Все изменения проходят через SoT, что исключает configuration drift.
- **Intent Verification**: Проверка, что фактическое поведение сети соответствует ожидаемому (intent). Пример: "все хосты в VLAN 100 не должны иметь доступ к VLAN 200".
- **Configuration Drift**: Отклонение текущей конфигурации устройства от Source of Truth. Возникает при ручных изменениях или failed automation.
- **Formal Verification**: Метод проверки сетевой конфигурации с помощью формальной логики (model checking). Batfish использует это для reachability и ACL verification.

---

## Основные концепции

### Network Verification Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│ Developer/Engineer                                           │
│  → Изменение конфигурации в Git (YAML, templates)          │
├─────────────────────────────────────────────────────────────┤
│ Git Repository                                               │
│  → Network configs (Ansible, Jinja2, device configs)        │
│  → Source of Truth (NetBox export)                          │
├─────────────────────────────────────────────────────────────┤
│ CI/CD Pipeline                                               │
│  1. Lint: yaml-lint, ansible-lint, batfish-lint             │
│  2. Syntax: device config syntax check                      │
│  3. Batfish: offline verification                           │
│     → Reachability test (can A reach B?)                    │
│     → ACL test (is traffic allowed?)                        │
│     → Routing test (is route present?)                      │
│  4. Containerlab: integration test (optional)               │
├─────────────────────────────────────────────────────────────┤
│ Deployment                                                    │
│  → Ansible/Nornir push to devices                           │
│  → Post-deployment verification (Batfish, SNMP, API)        │
└─────────────────────────────────────────────────────────────┘
```

### Сравнение инструментов

| Инструмент | Тип | Функции | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Batfish** | Open-source, offline | Config analysis, formal verification, reachability | CI/CD pipeline, pre-deployment validation |
| **IPFabric** | Commercial, online | Automated topology discovery, intent verification, assurance | Large DC, production monitoring |
| **NetBox** | Open-source, SoT | IPAM, DCIM, config management, API | Source of Truth, inventory management |
| **Batfish + NetBox** | Combination | SoT + verification | Production automation pipeline |

### Типы проверок Batfish

| Проверка | Описание | Пример |
| :--- | :--- | :--- |
| **Reachability** | Проверка connectivity between two points | "Can host A in VLAN 100 reach server B on port 443?" |
| **ACL denies** | Проверка, что ACL блокирует определенный трафик | "Is traffic from 10.0.0.0/8 to 192.168.0.0/16 denied?" |
| **Routing** | Проверка наличия маршрутов | "Is there a route to 10.0.2.0/24 via next-hop 10.0.1.1?" |
| **BGP** | Проверка BGP peering и route advertisement | "Is BGP session to peer 10.0.0.2 established?" |
| **Failure impact** | Анализ отказа устройства/link | "If link X goes down, which hosts lose connectivity?" |
| **Differential** | Сравнение двух snapshots | "What changed between yesterday's and today's configs?" |

---

## Практические сценарии

### Сценарий 1: Batfish установка и запуск

```bash
# 1. Установка Batfish (Docker)
docker pull batfish/batfish
docker run -d -p 9996:9996 -p 9997:9997 -p 9993:9993 \
    -v batfish-data:/data \
    --name batfish batfish/batfish

# 2. Установка Python client
pip install pybatfish

# 3. Загрузка конфигураций
python3 << 'EOF'
from pybatfish.client.session import Session

bf = Session(host="localhost")

# Инициализация network
bf.set_network("my-network")

# Загрузка configs (указать путь к папке с конфигами)
bf.init_snapshot("path/to/configs/", name="pre-change")

# Список загруженных device configs
print(bf.get_node_status())
# → {'node': 'router01', 'status': 'alive', ...}
# → {'node': 'switch01', 'status': 'alive', ...}
EOF
```

### Сценарий 2: Batfish reachability test

```python
from pybatfish.client.session import Session
from pybatfish.datamodel import HeaderConstraints, PathConstraints

bf = Session(host="localhost")
bf.set_network("my-network")
bf.init_snapshot("path/to/configs/", name="current")

# Проверка: может ли host 10.0.0.5 (VLAN 100) достучаться до 10.0.1.80:443?
result = bf.q.reachability(
    pathConstraints=PathConstraints(startLocation="router01"),
    headers=HeaderConstraints(
        srcIps="10.0.0.5",
        dstIps="10.0.1.80",
        applications="TCP/443",
        ipProtocols="TCP"
    )
).answer()

# Просмотр результатов
for flow in result.frame().iloc:
    print(f"Path: {flow['Path']}")
    print(f"Disposition: {flow['Disposition']}")
    # → Disposition: SUCCESS (traffic allowed)
    # → Disposition: DENIED (ACL blocked)

# Проверка: заблокирован ли трафик между VLAN 100 и VLAN 200?
result = bf.q.reachability(
    headers=HeaderConstraints(
        srcIps="10.0.100.0/24",
        dstIps="10.0.200.0/24"
    )
).answer()

# Ожидаемый результат: DENIED (все пакеты должны быть заблокированы)
print(f"Total flows: {len(result.frame())}")
print(f"Denied: {len(result.frame()[result.frame()['Disposition'] == 'DENIED_INBOUND')}")
```

### Сценарий 3: Batfish ACL verification

```python
from pybatfish.client.session import Session

bf = Session(host="localhost")
bf.set_network("my-network")
bf.init_snapshot("path/to/configs/", name="current")

# Проверка ACL на интерфейсе
acl_result = bf.q.searchAcls(
    nodes="router01",
    interfaces="GigabitEthernet0/0"
).answer()

for row in acl_result.frame().iloc:
    print(f"ACL Name: {row['ACL_Name']}")
    print(f"  Line: {row['Line_Number']}")
    print(f"  Action: {row['Action']}")
    print(f"  Match: {row['Match_Conditions']}")
    print(f"  Space: {row['Space']}")
```

### Сценарий 4: Batfish differential analysis (before/after)

```python
from pybatfish.client.session import Session

bf = Session(host="localhost")
bf.set_network("my-network")

# Загрузка двух snapshots (before и after)
bf.init_snapshot("path/to/configs-before/", name="before")
bf.init_snapshot("path/to/configs-after/", name="after")

# Сравнение двух snapshots
diff = bf.q.compareSnapshots(
    snapshot1="before",
    snapshot2="after"
).answer()

for change in diff.frame().iloc:
    print(f"Node: {change['Node']}")
    print(f"  Change Type: {change['Type']}")
    print(f"  Details: {change['Details']}")
    # → Node: router01
    # →   Change Type: INTERFACE_PROPERTY
    # →   Details: Gi0/0 description changed from "uplink-to-spine" to "uplink-to-spine-new"

# Проверка reachability в новых конфигах
new_result = bf.q.reachability(
    snapshotName="after",
    headers=HeaderConstraints(
        srcIps="10.0.0.5",
        dstIps="10.0.1.80",
        applications="TCP/443"
    )
).answer()

print(f"Reachability after change: {new_result.frame().iloc[0]['Disposition']}")
```

### Сценарий 5: IPFabric (commercial)

```python
# IPFabric API - автоматическое обнаружение топологии
import requests

ipfabric_url = "https://ipfabric.example.com"
token = "your-api-token"

headers = {"Authorization": f"Token {token}"}

# Получение топологии
topology = requests.get(
    f"{ipfabric_url}/api/topology",
    headers=headers
).json()

# Проверка intent-based policies
intent = requests.get(
    f"{ipfabric_url}/api/intent/verification",
    headers=headers
).json()

# Просмотр verification results
for check in intent["results"]:
    print(f"Intent: {check['intent']}")
    print(f"  Status: {check['status']}")
    print(f"  Details: {check['details']}")
    # → Intent: "No unauthorized access from VLAN 100 to VLAN 200"
    # →   Status: PASS
    # →   Details: "All ACLs correctly deny traffic"
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Batfish: Node not found** | Device config not loaded correctly | Check file format (Cisco: `show running-config` output); check snapshot path |
| **Batfish: Reachability undefined** | No route or ACL not parsed | Check routing protocol config; check ACL syntax |
| **Batfish: Slow analysis** | Large network, many devices | Optimize snapshot (exclude unused devices); increase Docker resources |
| **NetBox: Configuration drift** | Manual changes not synced | Run `ansible` sync from NetBox; use `napalm-merge` for config management |
| **IPFabric: Discovery failed** | SNMP/SSH access not working | Check SNMP community/SSH credentials; check firewall rules |

### Полезные команды

```bash
# Batfish
docker logs batfish                    # Просмотр логов
docker exec batfish bf-session-info    # Информация о сессии

# NetBox
python manage.py investigate  # Investigation commands
python manage.py sync_from_device  # Sync from device

# PyBatfish
bf.q.get_facts()                # Получение facts
bf.q.get_ospf_neighbors()       # OSPF neighbors
bf.q.get_bgp_neighbors()        # BGP neighbors
bf.q.get_interfaces()           # Interfaces
```

---

## Дополнительная информация

**Производственные рекомендации:**
- Внедряйте Batfish в CI/CD pipeline (pre-deployment verification).
- Используйте NetBox как Source of Truth для network inventory.
- Комбинируйте Batfish (offline) + IPFabric (online) для полного assurance.
- Версионируйте все конфиги в Git (для differential analysis).

**Связанные темы:**
- **[Network Automation](./network_automation.md)** — Ansible/Nornir + Batfish.
- **[NetBox](./network_automation.md#source-of-truth-sot)** — NetBox как SoT.
- **[Containerlab](./containerlab.md)** — lab environment для testing.
- **[SDN Overview](./sdn_overview.md)** — network verification в SDN.
