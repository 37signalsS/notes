## Определения

- **Network Automation**: Процесс управления сетевыми устройствами через программные инструменты,替代 ручного CLI SSH. Включает declarative configuration (Git), idempotent operations, CI/CD pipeline для network changes.
- **Infrastructure as Code (IaC)**: Подход, при котором сетевая инфраструктура описывается в коде (YAML, JSON, HCL), версионируется в Git и развертывается автоматически. Примеры: Ansible playbooks, Terraform configs, Nornir tasks.
- **Ansible**: Инструмент IaC от Red Hat. Использует declarative YAML playbooks и SSH для управления сетевыми устройствами. Имеет модули для Cisco (ios_config, nxos_config), Juniper (junos_config), Linux (nmcli, sysctl).
- **Nornir**: Python-based network automation framework. Комбинирует конфигурационные файлы (inventory) с Python-скриптами для управления. Высокая гибкость, parallel execution, поддержка Netmiko/NAPALM/SSH.
- **NAPALM (Network Automation and Programmability Abstraction Layer with Multivendor support)**: Библиотека Python для единообразного управления сетевыми устройствами (Cisco, Juniper, Arista, OS). Provide get_facts(), get_config(), load_merge_candidate().
- **Netmiko**: Библиотека Python для SSH-управления сетевыми устройствами. Поддерживает ~80 платформ (Cisco IOS, NX-OS, Juniper, Arista, Linux). Использует paramiko для SSH.
- **Terraform**: Инструмент IaC от HashiCorp. Использует declarative HCL для провижининга infrastructure (cloud, SDN controllers, network devices). State file хранит текущее состояние infrastructure.
- **SDN Controller as API**: Современные SDN-контроллеры (ONOS, ODL, Apstra, Cisco DNA Center) предоставляют REST/gRPC API для программного управления сетью. Это основа для network automation.
- **GitOps для сетей**: Подход, при котором Git является source of truth для network configuration. Изменения применяются через pull request → CI/CD pipeline → автоматическое развертывание на устройства.
- **Source of Truth (SoT)**: Единая база данных для network configuration (NetBox, IPFabric, Batfish). Все изменения проходят через SoT, что исключает configuration drift.

---

## Основные концепции

### Архитектура network automation pipeline

```
┌─────────────────────────────────────────────────────────────┐
│ Developer / Network Engineer                                 │
│  → Редактирует конфигурацию в Git (YAML/JSON/Jinja2)       │
├─────────────────────────────────────────────────────────────┤
│ Git Repository (GitHub, GitLab)                              │
│  → Version control, pull request, code review               │
│  → Source of Truth (SoT) для configuration                  │
├─────────────────────────────────────────────────────────────┤
│ CI/CD Pipeline (GitHub Actions, GitLab CI, Jenkins)         │
│  → Linting (yaml lint, ansible-lint)                        │
│  → Validation (syntax check, dry-run)                       │
│  → Testing (containerlab, GNS3)                             │
│  → Deployment (ansible-playbook, nornir run)                │
├─────────────────────────────────────────────────────────────┤
│ Automation Engine                                            │
│  → Ansible / Nornir / Terraform                             │
│  → Templates (Jinja2) → device-specific configs             │
│  → Idempotent operations (no duplicate changes)             │
├─────────────────────────────────────────────────────────────┤
│ Network Devices                                              │
│  → Cisco IOS/NX-OS, Juniper Junos, Arista EOS              │
│  → OVS/OVN, Linux (VPP, FRR)                               │
│  → SDN Controllers (ONOS, Apstra)                           │
└─────────────────────────────────────────────────────────────┘
```

### Сравнение инструментов

| Критерий | **Ansible** | **Nornir** | **NAPALM** | **Terraform** |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | YAML (playbooks) | Python | Python | HCL |
| **Транспорт** | SSH, NETCONF, REST | SSH, NETCONF, REST | SSH, NETCONF, REST | REST API, gRPC |
| **Inventory** | Static file / dynamic | Python dict / file | N/A (библиотека) | State file |
| **Idempotency** | Да (модули) | Зависит от кода | Да | Да |
| **Learning curve** | Низкая (YAML) | Высокая (Python) | Средняя | Средняя |
| **Parallel execution** | Да (forks) | Да (native) | Да (threading) | Да |
| **Multivendor** | Да (modules) | Да (Netmiko/NAPALM) | Да | Ограниченная |
| **SDN integration** | Да (REST modules) | Да (HTTP tasks) | Нет | Да (providers) |
| **Production-ready** | Да | Да | Да | Да |
| **Когда использовать** | Простые задачи; legacy среды | Сложная логика; Python required | Multivendor config management | Cloud/SDN provisioning |

### Модели управления (push vs pull)

| Модель | Описание | Инструменты | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Push** | Automation engine подключается к устройствам и отправляет конфигурацию | Ansible, Nornir, NAPALM | Ежедневные изменения, compliance checks |
| **Pull (agent-based)** | Агент на устройстве запрашивает конфигурацию из controller | NETCONF/YANG, gNMI, OVN | SDN controllers, large scale |
| **GitOps** | Git → CI/CD → push (auto) или pull (agent) | ArgoCD + Ansible/Terraform | Kubernetes, cloud-native |

### Source of Truth (SoT) для сетей

| Инструмент | Описание | Когда использовать |
| :--- | :--- | :--- |
| **NetBox** | IPAM + DCIM + Configuration management. Включает devices, interfaces, IPs, circuits, power. | Enterprise DC, telco |
| **IPFabric** | Network assurance platform с automated topology discovery и intent verification. | Крупные DC, multi-vendor |
| **Batfish** | Offline network analysis (config validation, verification, change impact analysis). | CI/CD pipeline для сетей |
| **Boxue / Nautobot** | Fork NetBox с дополнительными features. | Niche use cases |

**Рекомендация 2026:** NetBox + Batfish в CI/CD pipeline. NetBox как SoT, Batfish для validation.

---

## Практические сценарии

### Сценарий 1: Ansible для управления Cisco IOS

```yaml
# inventory/hosts.yml
all:
  children:
    switches:
      hosts:
        sw01:
          ansible_host: 10.0.0.1
          ansible_network_os: cisco.ios.ios
        sw02:
          ansible_host: 10.0.0.2
          ansible_network_os: cisco.ios.ios
      vars:
        ansible_user: admin
        ansible_password: "{{ vault_cisco_pass }}"
        ansible_connection: paramiko
        ansible_python_interpreter: auto_silent
```

```yaml
# playbooks/configure_vlans.yml
---
- name: Configure VLANs on Cisco switches
  hosts: switches
  gather_facts: false
  vars:
    vlans:
      - id: 100
        name: PRODUCTION
      - id: 200
        name: MANAGEMENT
      - id: 999
        name: NATIVE

  tasks:
    - name: Ensure VLANs exist
      cisco.ios.ios_vlans:
        config:
          - vlan_id: "{{ item.id }}"
            name: "{{ item.name }}"
            state: active
        state: merged
      loop: "{{ vlans }}"
      register: vlan_result

    - name: Save configuration
      cisco.ios.ios_config:
        save_when: modified

    - name: Backup current configuration
      cisco.ios.ios_config:
        backup: true
        backup_options:
          dir_path: "/backups/ios/{{ inventory_hostname }}"
          filename: "{{ inventory_hostname }}_{{ ansible_date_time.date }}.cfg"
```

```bash
# Запуск
ansible-playbook -i inventory/hosts.yml playbooks/configure_vlans.yml --diff

# Dry-run (check mode)
ansible-playbook -i inventory/hosts.yml playbooks/configure_vlans.yml --check --diff

# Применить к конкретному хосту
ansible-playbook -i inventory/hosts.yml playbooks/configure_vlans.yml --limit sw01
```

### Сценарий 2: Nornir для bulk operations

```python
# nornir_inventory/config.yml
---
inventory:
  plugin: SimpleInventory
  options:
    host_file: "inventory/hosts.yaml"
    group_file: "inventory/groups.yaml"
    defaults_file: "inventory/defaults.yaml"

runner:
  plugin: threaded
  options:
    num_workers: 20
```

```python
# tasks/backup_configs.py
from nornir import InitNornir
from nornir_netmiko import NetmikoSendConfig, NetmikoCommands
from nornir_jinja2.functions import template_file
from nornir_utils.plugins.functions import print_result

nr = InitNornir(config_file="nornir_inventory/config.yml")

def backup_configs(task):
    """Бэкап конфигурации со всех устройств"""
    result = task.run(
        task=NetmikoCommands,
        commands=["show running-config"]
    )
    # Сохранение в файл
    with open(f"backups/{task.host.name}.cfg", "w") as f:
        f.write(result.result[0])
    return result

def configure_vlans(task, vlans):
    """Массовая настройка VLAN на всех устройствах"""
    # Генерация конфигурации из шаблона
    rendered = task.run(
        task=template_file,
        template="vlans.j2",
        vlans=vlans
    )
    # Применение конфигурации
    task.run(
        task=NetmikoSendConfig,
        config_commands=rendered.result.splitlines()
    )

# Запуск backup
result = nr.run(task=backup_configs)
print_result(result)

# Запуск настройки VLAN
vlans = [
    {"id": 100, "name": "PRODUCTION"},
    {"id": 200, "name": "MANAGEMENT"},
]
result = nr.run(task=configure_vlans, vlans=vlans)
print_result(result)
```

### Сценарий 3: NAPALM для multivendor management

```python
from napalm import get_network_driver

# Cisco IOS
driver_ios = get_network_driver("ios")
ios = driver_ios(
    hostname="10.0.0.1",
    username="admin",
    password="secret",
    optional_args={"secret": "enable_pass"}
)
ios.open()

# Получение facts
facts = ios.get_facts()
print(f"Platform: {facts['platform']}, OS: {facts['os_version']}")
print(f"Interfaces: {list(facts['interface_list'])}")

# Получение текущей конфигурации
config = ios.get_config()
print(config["running"])

# Загрузка новой конфигурации (merge)
ios.load_merge_candidate(filename="configs/new_config.txt")
diff = ios.compare_config()
print(diff)

if diff:
    ios.commit_config()
else:
    ios.discard_config()

ios.close()

# Juniper Junos (тот же API!)
driver_junos = get_network_driver("junos")
junos = driver_junos(
    hostname="10.0.0.2",
    username="admin",
    password="secret"
)
junos.open()

# Универсальный вызов (multivendor!)
facts = junos.get_facts()
print(f"Platform: {facts['platform']}")
junos.close()
```

### Сценарий 4: Terraform для SDN controller

```hcl
# provider.tf
terraform {
  required_providers {
    sdwan = {
      source  = "CiscoDevNet/sdwan"
      version = "~> 0.1"
    }
  }
}

provider "sdwan" {
  url      = "https://sdwan-controller.example.com"
  username = var.username
  password = var.password
}

# main.tf - Создание site template
resource "sdwan_feature_template" "site" {
  name        = "Branch-Site-Template"
  description = "Template for branch offices"
  type        = "cisco_device"

  variables {
    name  = "SYSTEM_HOSTNAME"
    value = "{{hostname}}"
  }

  variables {
    name  = "VPN0_GIGE0_0_IP"
    value = "{{wan_ip}}"
  }
}

resource "sdwan_device_template" "branch" {
  name            = "Branch-Template"
  description     = "Branch office template"
  feature_templates = [sdwan_feature_template.site.id]
}

# Создание device attachment
resource "sdwan_attach_device" "branch1" {
  device_template_id = sdwan_device_template.branch.id
  devices {
    chassis_id = "BRANCH01"
    variables = {
      hostname = "branch01.example.com"
      wan_ip   = "198.51.100.10/24"
    }
  }
}
```

### Сценарий 5: GitOps pipeline для сети

```yaml
# .github/workflows/network-automation.yml
name: Network Automation

on:
  push:
    branches: [main]
    paths:
      - 'network-configs/**'
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint Ansible playbooks
        run: |
          pip install ansible-lint yamllint
          yamllint network-configs/
          ansible-lint playbooks/

  validate:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - name: Batfish validation
        run: |
          # Загрузка конфигов в Batfish
          python scripts/batfish_validate.py

  deploy-staging:
    needs: validate
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    environment: staging
    steps:
      - name: Deploy to staging
        run: |
          ansible-playbook -i staging playbooks/deploy.yml --check --diff

  deploy-production:
    needs: deploy-staging
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    environment: production
    steps:
      - name: Deploy to production
        run: |
          ansible-playbook -i production playbooks/deploy.yml --diff
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ansible: "Unreachable"** | SSH timeout, incorrect credentials, firewall | Проверить `ansible ping -m ping`; увеличить timeout; проверить firewall (22/tcp) |
| **Ansible: "Module failed"** | NETCONF/YANG не поддерживается; invalid config | Включить NETCONF на устройстве; проверить syntax конфига |
| **Nornir: Task exception** | Python error в task function | Отладка через `nornir --raise-on-error`; проверить Python logs |
| **NAPALM: Merge conflict** | Конфигурация конфликтует с existing config | Использовать `compare_config()` перед `commit_config()` |
| **Terraform: State drift** | Фактическое состояние ≠ state file | `terraform refresh`; `terraform plan` для обнаружения drift |
| **Git merge conflict** | Два инженера изменили одну конфигурацию | Branch strategy; Code review через pull request |

### Полезные команды

```bash
# Ansible
ansible all -m ping                         # Проверка connectivity
ansible all -m cisco.ios.ios_facts          # Сбор facts
ansible-playbook playbooks/test.yml -v      # Verbose mode
ansible-playbook playbooks/test.yml --diff  # Показать изменения

# Nornir
python -c "from nornir import InitNornir; nr = InitNornir(...); print(nr.inventory.hosts)"
nr.run(task=my_task)                        # Запуск задачи

# NAPALM
python -c "from napalm import get_network_driver; ..."
driver = get_network_driver("ios")
device = driver(hostname, username, password)
device.open()
print(device.get_facts())
```

---

## Дополнительная информация

**Производственные рекомендации:**
- Всегда делайте backup перед изменением конфигурации.
- Используйте check mode / dry-run перед реальным deploy.
- Версионируйте все конфиги в Git (включая secrets в vault).
- Внедряйте CI/CD pipeline для автоматической validation.
- Используйте Source of Truth (NetBox) для inventory management.

**Связанные темы:**
- **[SDN Overview](./sdn_overview.md)** — SDN-контроллеры и their APIs.
- **[NETCONF/YANG](./sdn_overview.md#southbound-api-детали)** — протокол для автоматизации.
- **[OpenFlow (ovs-ofctl)](./openflow.md#управление-потоками-через-ovs-ofctl)** — ручное управление OVS.
- **[Containerlab](./containerlab.md)** — lab environment для testing.
- **[Network Verification](./network_verification.md)** — Batfish, IPFabric.
