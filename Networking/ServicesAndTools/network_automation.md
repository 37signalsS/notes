# Network Automation: NAPALM, Netmiko, Nornir

## Определения

**Network Automation** — автоматизация конфигурации, мониторинга и управления сетевым оборудованием через API и скрипты вместо ручного CLI-ввода. Основные цели: воспроизводимость (reproducibility), масштабируемость, уменьшение human error, Network as Code (NaC).

**NAPALM (Network Automation and Programmability Abstraction Layer with Multivendor support)** — Python-библиотека для агрегации API сетевого оборудования разных вендоров (Cisco IOS/NX-OS, Juniper JunOS, Arista EOS, Nokia IOS-XR). Предоставляет единый интерфейс для get/set операций (get_facts, get_config, load_config, rollback).

**Netmiko** — Python-библиотека для SSH-подключения к сетевому оборудованию. Обрабатывает認証, промпты, buffering,上下文. Поддерживает 100+ платформ (Cisco, Juniper, Arista, MikroTik, Huawei). Используется для send_command, send_config_set.

**Nornir** — Python-фреймворк для параллельного выполнения задач на сетевом оборудовании. Комбинация inventory (хранилище устройств) + task runner (запуск задач) + прулинг (connection management). Заменяет Ansible для сетевых сценариев, где нужен контроль на уровне Python.

## Основные концепции

### Архитектура сетевой автоматизации

```text
┌─────────────────────────────────────────────────┐
│                   Source of Truth                │
│            (NetBox, CMDB, Git repo)              │
└──────────────────────┬──────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
    ┌────▼────┐  ┌─────▼─────┐  ┌───▼───┐
    │ Ansible │  │  Nornir   │  │ Terraform│
    │ (YAML)  │  │ (Python)  │  │ (HCL)   │
    └────┬────┘  └─────┬─────┘  └───┬───┘
         │             │             │
         └─────────────┼─────────────┘
                       │
              ┌────────┼────────┐
              │        │        │
         ┌────▼───┐ ┌──▼──┐ ┌──▼────┐
         │Netmiko │ │NAPALM│ │ REST  │
         │ (SSH)  │ │(API) │ │ API   │
         └────┬───┘ └──┬──┘ └──┬────┘
              │        │        │
         ┌────▼────────▼────────▼────┐
         │    Сетевое оборудование    │
         │  (Router, Switch, Firewall)│
         └───────────────────────────┘
```

### Сравнение инструментов

| Характеристика | Netmiko | NAPALM | Nornir |
| :--- | :--- | :--- | :--- |
| **Уровень** | SSH-клиент | Мультивендорный API | Фреймворк |
| **Протокол** | SSH | SSH/NETCONF/gNMI | SSH/NETCONF/HTTP |
| **Inventory** | Список словарей | Список словарей | YAML/JSON inventory |
| **Параллелизм** | Нет (синхронный) | Нет | Да (threading/async) |
| **Плагины** | Платформы | Платформы + drivers | Tasks, processors |
| **Когда использовать** | Простые задачи | Мультивендор конфигурация | Масштабные операции |
| **Пример** | `send_command("show ip int br")` | `get_facts()`, `load_config()` | `nr.run(task=show_ip)` |

### NAPALM: базовые операции

```python
from napalm import get_network_driver

# Подключение
driver = get_network_driver("ios")
device = driver(hostname="10.0.0.1", username="admin", password="secret")
device.open()

# Получение facts
facts = device.get_facts()
print(f"Hostname: {facts['hostname']}, Model: {facts['model']}")
print(f"OS Version: {facts['os_version']}")

# Получение конфигурации
config = device.get_config(retrieve="running")
print(config["running"])

# Загрузка конфигурации
device.load_config("""
interface GigabitEthernet0/1
 description UPLINK_TO_CORE
 ip address 10.0.1.1 255.255.255.0
 no shutdown
""")

# Сохранение
device.commit_config()
# device.discard_config()  # отмена
# device.rollback()        # откат к предыдущему

# Получение таблицы маршрутизации
routes = device.get_routing_table()
for route in routes:
    print(f"{route['network']} → {route['next_hop']}")

# Получение ARP
arp = device.get_arp_table()
for entry in arp:
    print(f"{entry['ip']} → {entry['mac']} ({entry['interface']})")

device.close()
```

### Netmiko: базовые операции

```python
from netmiko import ConnectHandler

# Подключение
device = {
    "device_type": "cisco_ios",
    "host": "10.0.0.1",
    "username": "admin",
    "password": "secret",
    "secret": "enable_password",
}
ssh = ConnectHandler(**device)

# Включение привилегированного режима
ssh.enable()

# Выполнение команды
output = ssh.send_command("show ip int brief")
print(output)

# Выполнение команд с ожиданием промпта
output = ssh.send_command("terminal length 0")

# Загрузка конфигурации
config_commands = [
    "interface GigabitEthernet0/1",
    "description UPLINK_TO_CORE",
    "ip address 10.0.1.1 255.255.255.0",
    "no shutdown",
]
output = ssh.send_config_set(config_commands)
print(output)

# Сохранение конфигурации
ssh.send_command("write memory")

# Отключение
ssh.disconnect()
```

### Nornir: параллельное выполнение

```python
from nornir import InitNornir
from nornir_netmiko import Netmiko
from nornir_utils.plugins.functions import print_result

# Инициализация
nr = InitNornir(
    inventory={
        "plugin": "SimpleInventory",
        "options": {
            "host_file": "inventory/hosts.yaml",
            "group_file": "inventory/groups.yaml",
        },
    }
)

# Задача: собрать facts со всех устройств
def collect_facts(task):
    """Собираемfacts со всех устройств параллельно."""
    result = task.run(task=Netmiko, command="show version")
    return result

# Запуск на всех устройствах
results = nr.run(task=collect_facts)

# Обработка результатов
for host, result in results.items():
    if result.failed:
        print(f"[FAIL] {host}: {result.exception}")
    else:
        print(f"[OK] {host}: собрали версию")

# Задача: развернуть конфигурацию на всех устройствах
def deploy_config(task):
    """Загружаем конфигурацию из файла."""
    config_file = f"configs/{task.host.name}.cfg"
    task.run(
        task=Netmiko,
        name="Load config",
        config_file=config_file,
    )
    task.run(
        task=Netmiko,
        name="Save config",
        command="write memory",
    )

# Запуск с фильтрацией по группе
results = nr.filter(group="access_switches").run(task=deploy_config)
```

## Практические сценарии

### Сбор информации со всех устройств (show commands)

```python
from nornir import InitNornir
from nornir_netmiko import Netmiko
from nornir_utils.plugins.functions import print_result
import json

nr = InitNornir(config_file="config.yaml")

def collect_show_version(task):
    result = task.run(
        task=Netmiko,
        command="show version | include IOS|NXOS|Model",
    )
    # Сохраняем результат
    task.host["show_version"] = result.result

# Запуск
nr.run(task=collect_show_version)

# Экспорт в JSON
output = {}
for host, result in nr.inventory.hosts.items():
    output[host] = {
        "hostname": host,
        "platform": result["platform"],
        "show_version": result.get("show_version", ""),
    }

with open("inventory_report.json", "w") as f:
    json.dump(output, f, indent=2)
```

### Массовая настройка VLAN

```python
from nornir import InitNornir
from nornir_netmiko import Netmiko

nr = InitNornir(config_file="config.yaml")

# Группа устройств: access switches
access_sw = nr.filter(group="access_switches")

def configure_vlans(task):
    """Настраиваем VLANы на всех access-коммутаторах."""
    vlans = [
        {"id": 100, "name": "USERS"},
        {"id": 200, "name": "SERVERS"},
        {"id": 300, "name": "MANAGEMENT"},
    ]

    commands = []
    for vlan in vlans:
        commands.append(f"vlan {vlan['id']}")
        commands.append(f" name {vlan['name']}")

    # Загрузка конфигурации
    task.run(
        task=Netmiko,
        name="Configure VLANs",
        config_commands=commands,
    )

    # Сохранение
    task.run(
        task=Netmiko,
        name="Save",
        command="write memory",
    )

# Запуск
results = access_sw.run(task=configure_vlans)
for host, result in results.items():
    status = "OK" if not result.failed else "FAIL"
    print(f"{host}: {status}")
```

### Проверка compliance (соответствие эталону)

```python
from nornir import InitNornir
from nornir_netmiko import Netmiko
from nornir_napalm import NapalmGeneric

nr = InitNornir(config_file="config.yaml")

def check_compliance(task):
    """Проверяем, что конфигурация соответствует эталону."""
    # Получаем текущую конфигурацию
    device = NapalmGeneric(task)
    current_config = device.get_config(retrieve="running")
    running = current_config["running"]

    # Эталонная конфигурация
    with open(f"configs/standard/{task.host.name}.cfg") as f:
        standard_config = f.read()

    # Сравнение
    if running.strip() == standard_config.strip():
        print(f"[COMPLIANT] {task.host.name}")
    else:
        print(f"[NON-COMPLIANT] {task.host.name}")
        # Генерация diff
        diff = set(running.splitlines()) - set(standard_config.splitlines())
        for line in diff:
            print(f"  + {line}")

results = nr.run(task=check_compliance)
```

### Автоматизация с Ansible (сравнение)

```yaml
# Ansible playbook (YAML)
---
- name: Configure VLANs on access switches
  hosts: access_switches
  gather_facts: no
  tasks:
    - name: Configure VLANs
      cisco.ios.ios_vlans:
        config:
          - vlan_id: 100
            name: USERS
          - vlan_id: 200
            name: SERVERS
        state: merged

    - name: Save configuration
      cisco.ios.ios_command:
        commands:
          - write memory
```

```python
# Nornir + Netmiko (Python)
def configure_vlans(task):
    commands = [
        "vlan 100", " name USERS",
        "vlan 200", " name SERVERS",
    ]
    task.run(task=Netmiko, config_commands=commands)
    task.run(task=Netmiko, command="write memory")

nr.filter(group="access_switches").run(task=configure_vlans)
```

| Критерий | Ansible | Nornir |
| :--- | :--- | :--- |
| **Язык** | YAML | Python |
| **Inventory** | INI/YAML | YAML/JSON + plugins |
| **Параллелизм** | Встроенный (forks) | threading/async |
| **Гибкость** | Ограниченная (модули) | Полная (Python) |
| **Debugging** | verbose, -vvv | Python debugger |
| **Community** | Огромный | Растущий |
| **Когда использовать** | Простые, повторяющиеся задачи | Сложная логика, интеграция |

## Дополнительная информация

### Network as Code (NaC)

```text
                    Git Repository
                    (source of truth)
                         │
            ┌────────────┼────────────┐
            │            │            │
     ┌──────▼──────┐ ┌───▼────┐ ┌────▼────┐
     │  Ansible    │ │ Nornir │ │Terraform│
     │  playbooks  │ │ tasks  │ │ configs │
     └──────┬──────┘ └───┬────┘ └────┬────┘
            │            │            │
            └────────────┼────────────┘
                         │
              CI/CD Pipeline (GitLab CI, GitHub Actions)
                         │
              ┌──────────┼──────────┐
              │          │          │
         ┌────▼───┐ ┌───▼────┐ ┌───▼───┐
         │Validate│ │ Deploy │ │Rollback│
         │ Lint   │ │        │ │       │
         └────────┘ └────────┘ └───────┘
```

### Шаблоны для Jinja2 (Napalm-宝tools)

```jinja2
{# templates/cisco_ios_interface.j2 #}
interface {{ interface }}
 description {{ description }}
{% if ip_address %}
 ip address {{ ip_address }} {{ subnet_mask }}
{% endif %}
{% if shutdown %}
 shutdown
{% else %}
 no shutdown
{% endif %}
```

### Интеграция с NetBox (Source of Truth)

```python
import pynetbox

nb = pynetbox.api("http://netbox.example.com", token="YOUR_TOKEN")

# Получение устройств
devices = nb.devices.filter(site="DC1")
for device in devices:
    print(f"{device.name} → {device.primary_ip}")

# Генерация конфигурации из NetBox
interfaces = nb.ipam.interfaces.filter(device=device.name)
for iface in interfaces:
    print(f"{iface.name}: {iface.ip_addresses}")
```

### Безопасность сетевой автоматизации

| Практика | Описание |
| :--- | :--- |
| **Ansible Vault** | Шифрование паролей, ключей в playbooks |
| **SSH keys** | Аутентификация по ключам вместо паролей |
| **RBAC** | Ограничение прав по ролям (Ansible Tower/AAP) |
| **Change control** | Git + PR перед применением изменений |
| **Dry-run** | `--check` (Ansible), `--dry-run` (Nornir) перед deploy |
| **Rollback** | NAPALM `rollback()`, Git revert |

Подробнее: **[Ansible Security](../../Ansible/ansible_security_best_practices.md)**, **[Ansible Vault](../../Ansible/Vault/basics.md)**.

### Смотрите также

- **[NetBox](../NetBox/overview.md)** — IPAM/DCIM как Source of Truth.
- **[NetBox + Python](../NetBox/netbox-automation-python.md)** — автоматизация с pynetbox.
- **[Ansible](../../Ansible/ansible_introduction.md)** — основы Ansible.
- **[Terraform vs Crossplane](../../GitOps/Crossplane/terraform_comparison.md)** — IaC для инфраструктуры.
- **[NAPALM](https://napalm.readthedocs.io/)** — официальная документация.
- **[Netmiko](https://ktbyers.github.io/netmiko/)** — официальная документация.
- **[Nornir](https://nornir.readthedocs.io/)** — официальная документация.
