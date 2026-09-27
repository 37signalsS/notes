# Динамический инвентарь в Ansible

## Определения

**Inventory (инвентарь)** — список управляемых хостов, сгруппированных по логическим группам, с переменными хостов и групп. Может быть статическим (INI/YAML) или динамическим, генерируемым автоматически из внешних источников.

**Static inventory** — статический файл с перечислением хостов и групп, который не меняется автоматически. Подходит для небольших инфраструктур с фиксированным набором хостов.

**Dynamic inventory** — скрипт или плагин, который запрашивает внешний источник (CMDB, service discovery, KV-хранилище) и возвращает список хостов в формате, понятном Ansible.

**Inventory plugin** — современный нативный способ реализации динамического инвентаря (Ansible 2.4+), использующий YAML-конфигурации и поддерживающий кэширование. Предпочтительнее устаревших исполняемых скриптов.

**CMDB (Configuration Management Database)** — база данных, хранящая информацию о конфигурации инфраструктуры: хосты, их статус, расположение, параметры. Примеры: NetBox, Foreman, iTop.

**Service Discovery** — система автоматического обнаружения активных узлов и их метаданных. Пример: Consul.

**KV-хранилище (Key-Value)** — хранилище данных по принципу "ключ-значение". Используется для хранения конфигураций и метаданных хостов. Пример: Etcd.

**Directory Inventory (комбинированный инвентарь)** — директория, содержащая несколько источников инвентаря (статические `hosts.yml` + динамические плагины `.yml`), которые Ansible объединяет в один логический инвентарь.

**Keyed Groups** — механизм автоматического создания групп Ansible на основе значений атрибутов хоста с использованием префиксов и разделителей.

**Compose** — механизм создания или переопределения переменных хоста через Jinja2-выражения.

**Hostvars** — переменные, доступные для каждого хоста в инвентаре, включая IP-адрес, операционную систему, теги и другие метаданные.

**Fact Caching** — механизм сохранения фактов хостов во внешнее хранилище (jsonfile, Redis, memcached) для ускорения повторных запусков.

**Constructed plugin** — встроенный плагин, создающий переменные и группы на основе Jinja2-выражений. Особенно полезен для модификации статического инвентаря без изменения исходных файлов.

---

## Базовые концепции

### Статический vs динамический инвентарь

| Аспект | Static inventory | Dynamic inventory |
|---|---|---|
| **Источник** | Файл `inventory.ini` или `hosts.yml` | Внешний источник (CMDB, service discovery) |
| **Обновление** | Ручное | Автоматическое |
| **Масштабируемость** | Ограничена | Высокая |
| **Гибкость** | Низкая | Высокая |
| **Сложность** | Низкая | Средняя/Высокая |
| **Подходит для** | Малых инфраструктур, тестовых сред | Production, гетерогенные парки |

### Архитектура динамического инвентаря

```
External Sources
    ├── NetBox (CMDB)
    ├── Foreman (CMDB)
    ├── Consul (Service Discovery)
    ├── Etcd (KV-хранилище)
    ├── Proxmox VE (виртуализация)
    ├── Git (статические хосты)
    └── Custom API/CMDB
            ↓
    [Dynamic Inventory Plugin/script]
            ↓
    [Ansible Control Node]
    ├── hostvars (IP, OS, tags)
    ├── groupvars (окружение, приложение)
    ├── Fact Cache (jsonfile/Redis)
    └── Playbooks
            ↓
    [Managed Nodes]
```

### Предварительные требования

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible Core | 2.21+ | `ansible --version` |
| Python | 3.12+ | `python3 --version` |
| netbox.netbox | 3.0+ | `ansible-galaxy collection list netbox.netbox` |
| community.general | 10.0+ | `ansible-galaxy collection list community.general` |
| theforeman.foreman | 3.0+ | `ansible-galaxy collection list theforeman.foreman` |
| community.proxmox | 1.0+ | `ansible-galaxy collection list community.proxmox` |
| pynetbox | 7.0+ | `python3 -c "import pynetbox; print(pynetbox.__version__)"` |
| requests | 2.32+ | `python3 -c "import requests; print(requests.__version__)"` |

### Жизненный цикл плагина

1. **Discovery** — Ansible сканирует директорию инвентаря и загружает доступные плагины.
2. **Parsing** — Плагин читает YAML-конфигурацию и подключается к внешнему источнику.
3. **Query** — Выполняется запрос к API с учетом фильтров (`query_filters`, `filter`).
4. **Transformation** — Данные преобразуются в формат инвентаря: хосты, группы, `hostvars`.
5. **Grouping** — `keyed_groups`, `groups`, `group_by` формируют логическую структуру.
6. **Caching** — Результат кэшируется для последующих запусков.
7. **Delivery** — Ansible получает готовый инвентарь и передает его плейбукам.

### Приоритет разрешения инвентаря

При использовании Directory Inventory или нескольких источников `-i`:

1. Статические файлы (`hosts.yml`, `hosts.ini`)
2. Динамические плагины (по алфавитному порядку файлов)
3. Переменные окружения (`ANSIBLE_INVENTORY`)
4. `constructed` plugin (если указан последним)

### Ключевые принципы

1. **Source of truth** — динамический инвентарь должен быть единственным источником истины о хостах. Подробнее о принципах SSoT: [Динамический инвентарь в Ansible](../dynamic_inventory.md).
2. **Idempotency** — повторный запуск инвентаря должен возвращать тот же результат при неизменном источнике.
3. **Caching** — кешируйте инвентарь, чтобы уменьшить нагрузку на внешний источник и сократить время генерации.
4. **Filter at source** — фильтруйте запросы на стороне API, возвращая только нужные хосты.
5. **Security** — защищайте credentials для доступа к внешним источникам (Vault, переменные окружения).
6. **Blast radius minimization** — ограничивайте `--limit` и фильтры, чтобы случайно не затронуть непредназначенные хосты.
7. **Observability** — логируйте генерацию инвентаря и изменения в группах для отслеживания инцидентов.

### Интеграция с SSoT-файлами

| Тема | SSoT-файл | Что покрыто |
|---|---|---|
| Полная теория и примеры | [Динамический инвентарь в Ansible](../dynamic_inventory.md) | NetBox, Consul, Foreman, Proxmox, Etcd, Terraform, Git, constructed plugin, кэширование, безопасность, CI/CD |
| Кроссплатформенные факты и группы | [Кроссплатформенный инвентарь и факты](../CrossPlatform/ansible_cross_platform_inventory_and_facts.md) | `hostvars`, `group_by`, fact caching, `delegate_facts`, host patterns |
| Кастомные плагины инвентаря | [Разработка кастомных плагинов](./ansible_custom_plugins.md) | Создание собственных inventory plugins |
| Производительность и кэширование | [Оптимизация производительности](../ansible_performance_tuning.md) | `fact_caching`, `forks`, `pipelining`, стратегии |

---

## Практические сценарии

### Сценарий 1: Внутренний CMDB через кастомный скрипт

Создание кастомного скрипта на Python для генерации динамического инвентаря из внутреннего CMDB API. Этот подход подходит, когда нет готового плагина для вашей системы учета.

```python
#!/usr/bin/env python3
"""
Кастомный динамический инвентарь для Ansible.
Генерирует инвентарь из внутреннего CMDB API.
"""

import json
import os
import sys
from urllib.request import urlopen, Request

CMDB_API_URL = os.environ.get('CMDB_API_URL', 'https://cmdb.internal/api/v1/hosts')
CMDB_API_TOKEN = os.environ.get('CMDB_API_TOKEN', '')


def get_cmdb_hosts():
    """Получение хостов из CMDB."""
    headers = {'Authorization': f'Bearer {CMDB_API_TOKEN}'}
    req = Request(CMDB_API_URL, headers=headers)
    with urlopen(req) as response:
        return json.loads(response.read().decode())


def generate_inventory():
    """Генерация динамического инвентаря."""
    hosts = get_cmdb_hosts()
    inventory = {
        '_meta': {
            'hostvars': {}
        },
        'all': {
            'hosts': [],
            'children': []
        }
    }

    groups = {}

    for host in hosts:
        host_id = host['id']
        hostname = host['hostname']
        ip_address = host['ip_address']
        environment = host['environment']
        application = host['application']
        tier = host['tier']
        ssh_user = host.get('ssh_user', 'ubuntu')
        ssh_key = host.get('ssh_key', '~/.ssh/id_rsa')

        inventory['all']['hosts'].append(hostname)

        inventory['_meta']['hostvars'][hostname] = {
            'ansible_host': ip_address,
            'ansible_user': ssh_user,
            'ansible_ssh_private_key_file': ssh_key,
            'environment': environment,
            'application': application,
            'tier': tier,
            'cmdb_id': host_id
        }

        env_group = f'env_{environment}'
        groups.setdefault(env_group, []).append(hostname)

        app_group = f'app_{application}'
        groups.setdefault(app_group, []).append(hostname)

        tier_group = f'tier_{tier}'
        groups.setdefault(tier_group, []).append(hostname)

    for group_name, hosts_list in groups.items():
        inventory[group_name] = {'hosts': hosts_list}
        inventory['all']['children'].append(group_name)

    return inventory


if __name__ == '__main__':
    inventory = generate_inventory()
    if '--list' in sys.argv:
        print(json.dumps(inventory))
    elif '--host' in sys.argv:
        hostname = sys.argv[sys.argv.index('--host') + 1]
        hostvars = inventory.get('_meta', {}).get('hostvars', {}).get(hostname, {})
        print(json.dumps(hostvars))
    else:
        print(json.dumps(inventory))
```

**Использование:**

```bash
# Сделать скрипт исполняемым
chmod +x dynamic_inventory.py

# Проверка инвентаря
./dynamic_inventory.py --list
# → JSON с хостами, группами и переменными

# Использование в Ansible
ansible-inventory -i dynamic_inventory.py --list
# → показывает инвентарь из CMDB

# Запуск плейбука
ansible-playbook -i dynamic_inventory.py deploy.yml --limit env_production
```

**Валидация:**

```bash
# Проверка формата
./dynamic_inventory.py --list | jq .
# → проверяет, что JSON валиден

# Проверка хоста
./dynamic_inventory.py --host web1
# → показывает переменные для хоста web1

# Проверка интеграции с Ansible
ansible all -i dynamic_inventory.py -m ping
# → пингует все хосты из CMDB
```

### Сценарий 2: Динамический инвентарь NetBox (self-hosted CMDB)

Настройка плагина `netbox.netbox.nb_inventory` для автоматического обнаружения хостов в NetBox. Полное руководство по настройке, фильтрации, группировке и кэшированию: [Динамический инвентарь в Ansible](../dynamic_inventory.md#инвентарь-на-основе-cmdb-netbox).

```yaml
# inventories/netbox.yml
plugin: netbox.netbox.nb_inventory
api_endpoint: https://netbox.internal
token: "{{ vault_netbox_token }}"
validate_certs: true

# Фильтрация устройств
query_filters:
  - status: active
  - role__in: ["web-server", "app-server", "db-server"]

# Группировка по ролям и сайтам
group_by:
  - device_roles
  - sites
  - platforms

# Ключевые группы
keyed_groups:
  - key: device_roles.name
    prefix: role
    separator: "_"
  - key: site.name
    prefix: site
    separator: "_"
  - key: platforms.name
    prefix: platform
    separator: "_"
  - key: status
    prefix: status

# Хостовые переменные
compose:
  ansible_host: primary_ip4.address | regex_replace('/.*$', '')
  ansible_network_os: platforms.name | default('linux')
  netbox_id: id
  netbox_url: url
  rack: rack.name | default('N/A')
  tenant: tenant.name | default('N/A')

# Кэширование
cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 3600
cache_connection: /tmp/netbox_inventory_cache
```

**Использование:**

```bash
# Проверка динамического инвентаря
ansible-inventory --list -i inventories/netbox.yml
# → показывает все активные устройства из NetBox

# Запуск плейбука с фильтром
ansible-playbook -i inventories/netbox.yml deploy.yml --limit role_web-server
# → запускает только веб-серверы

# Проверка групп
ansible-inventory --graph -i inventories/netbox.yml
# → дерево групп с сайтами и ролями
```

**Валидация:**

```bash
# Проверка количества устройств
ansible-inventory --list -i inventories/netbox.yml | jq '._meta.hostkeys | length'
# → показывает количество активных устройств

# Проверка переменных хоста
ansible-inventory --host web01 -i inventories/netbox.yml | jq .
# → переменные для конкретного хоста
```

### Сценарий 3: Динамический инвентарь Consul (Service Discovery)

Consul используется как источник инвентаря для динамических сред. Полное руководство: [Динамический инвентарь в Ansible](../dynamic_inventory.md#инвентарь-на-основе-service-discovery-consul).

```yaml
# inventories/consul.yml
plugin: community.general.consul
consul_url: http://consul.internal:8500
token: "{{ vault_consul_token }}"

# Фильтрация: только прошедшие health checks
filter: "Service.Status == 'passing'"

# Группировка по сервисам и датацентрам
keyed_groups:
  - key: Service
    prefix: svc
  - key: Tags
    prefix: tag
  - key: Datacenter
    prefix: dc

# Сопоставление переменных хоста
compose:
  ansible_host: Address
  consul_node_name: Node
  consul_service_meta: ServiceMeta

# Кэширование
cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 600
cache_connection: /tmp/consul_inventory_cache
```

**Использование:**

```bash
# Проверка инвентаря из Consul
ansible-inventory --list -i inventories/consul.yml
# → показывает все зарегистрированные сервисы

# Запуск плейбука для конкретного сервиса
ansible-playbook -i inventories/consul.yml deploy.yml --limit svc_web
# → запускает только хосты сервиса web

# Проверка готовых сервисов
ansible-inventory --list -i inventories/consul.yml | jq '.all.children'
# → показывает все группы сервисов
```

### Сценарий 4: Динамический инвентарь Proxmox VE (self-hosted виртуализация)

Proxmox VE — self-hosted платформа виртуализации. Полное руководство: [Динамический инвентарь в Ansible](../dynamic_inventory.md#инвентарь-на-основе-proxmox-ve).

```yaml
# inventories/proxmox.yml
plugin: community.proxmox.proxmox
url: https://pve1.internal:8006
user: "automation@pam!ansible"
password: "{{ vault_proxmox_password }}"
want_proxmox_nodes_enabled: true
want_proxmox_nodes_availabe_only: true
validate_certs: false

# Сопоставление IP для подключения
compose:
  ansible_host: proxmox_net0_ip | default(proxmox_ip)
  proxmox_status: proxmox_status
  proxmox_node: proxmox_node
  proxmox_tags: proxmox_tags
  proxmox_vmid: proxmox_vmid

# Группировка по статусу, узлу и типу
keyed_groups:
  - key: proxmox_status
    prefix: status
  - key: proxmox_node
    prefix: node
  - key: proxmox_tags
    separator: "_"
  - key: proxmox_type
    prefix: type

# Условия группировки
groups:
  running: "proxmox_status == 'running'"
  stopped: "proxmox_status == 'stopped'"
  lxc_containers: "proxmox_type == 'lxc'"
  virtual_machines: "proxmox_type == 'qemu'"
  nodes: "proxmox_type == 'node'"

# Кэширование
cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 300
cache_connection: /tmp/proxmox_inventory_cache
```

**Использование:**

```bash
# Проверка инвентаря Proxmox
ansible-inventory --list -i inventories/proxmox.yml
# → показывает все VM, LXC и узлы

# Запуск для запущенных VM
ansible-playbook -i inventories/proxmox.yml deploy.yml --limit running
# → запускает только запущенные VM
```

### Сценарий 5: Directory Inventory (комбинированный подход)

Директория `inventories/` может содержать несколько источников инвентаря. Ansible рекурсивно сканирует её по алфавиту.

```
inventories/
├── production/
│   ├── hosts.yml                  # Статический инвентарь
│   ├── netbox.yml                 # Динамический: CMDB
│   ├── consul.yml                 # Динамический: Service Discovery
│   ├── group_vars/
│   │   ├── all.yml
│   │   ├── webservers.yml
│   │   └── dbservers.yml
│   └── host_vars/
│       └── db01.yml
├── staging/
│   ├── hosts.yml
│   └── group_vars/
│       └── all.yml
└── dynamic/
    ├── proxmox.yml                # Виртуализация
    └── foreman.yml                # CMDB
```

```bash
# Использование Directory Inventory
ansible-playbook site.yml -i inventories/production/

# Или несколько источников (с сохранением порядка)
ansible-playbook site.yml -i inventories/production/hosts.yml -i inventories/production/netbox.yml
```

**Важно:** Порядок файлов определяется алфавитом. Если вам нужен определённый порядок обработки, используйте несколько `-i` или группируйте файлы с префиксами (например, `01_hosts.yml`, `02_netbox.yml`).

### Сценарий 6: Constructed plugin для OS-специфичных групп

Встроенный плагин `constructed` позволяет создавать переменные и группы на основе Jinja2-выражений без изменения исходного инвентаря. Полное руководство: [Динамический инвентарь в Ansible](../dynamic_inventory.md#инвентарь-с-использованием-constructed-plugin).

```yaml
# inventories/constructed.yml
plugin: constructed
strict: false
compose:
  # Сопоставление local_ip из переменных хоста
  ansible_host: hostvars[inventory_hostname].get('local_ip', hostvars[inventory_hostname].get('ansible_host'))
  dc: hostvars[inventory_hostname].get('dc', 'unknown')
groups:
  # Группировка по префиксу имени хоста
  production: inventory_hostname.startswith('prod')
  web: "'web' in inventory_hostname"
  db: "'db' in inventory_hostname"
  branch_office: "'office' in (hostvars[inventory_hostname].get('site', '') | default(''))"
```

```bash
# Запуск с комбинированием статического и constructed инвентаря
ansible-playbook site.yml -i inventories/production/hosts.yml -i inventories/constructed.yml
```

### Сценарий 7: Terraform State как источник инвентаря

Распространенный паттерн — использование данных Terraform как источника правды для инфраструктуры, описанной кодом (IaC). Подходит для self-hosted платформ (Proxmox, VMware ESXi).

```bash
# 1. Применение Terraform
cd terraform/ && terraform apply -auto-approve

# 2. Генерация инвентаря
terraform output -json > /tmp/tf_output.json
python3 scripts/tf_to_inventory.py --input /tmp/tf_output.json --output /tmp/inventory.json

# 3. Запуск Ansible с динамическим инвентарем
ansible-playbook playbooks/site.yml -i /tmp/inventory.json
```

```python
#!/usr/bin/env python3
# scripts/tf_to_inventory.py
"""Конвертер Terraform output в Ansible inventory JSON."""
import json
import argparse
import sys

def convert(tf_output: dict) -> dict:
    """Конвертирует terraform output в формат Ansible inventory."""
    inventory = {"_meta": {"hostvars": {}}}

    hosts = tf_output.get("instance_ips", {}).get("value", {})

    groups = {}
    for hostname, ip in hosts.items():
        group = hostname.split("-")[0] if "-" in hostname else "ungrouped"
        groups.setdefault(group, []).append(hostname)

        inventory["_meta"]["hostvars"][hostname] = {
            "ansible_host": ip,
            "tf_name": hostname,
        }

    for group, group_hosts in groups.items():
        inventory[group] = {"hosts": group_hosts}

    return inventory

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()

    with open(args.input) as f:
        tf_output = json.load(f)

    inventory = convert(tf_output)

    if args.output == "-":
        json.dump(inventory, sys.stdout, indent=2)
    else:
        with open(args.output, "w") as f:
            json.dump(inventory, f, indent=2)
```

---

## Операции и команды

### Основные команды для работы с динамическим инвентарем

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-inventory --list -i <inventory>` | Показать весь инвентарь | `ansible-inventory --list -i inventories/netbox.yml` |
| `ansible-inventory --graph` | Показать граф групп | `ansible-inventory --graph -i inventories/netbox.yml` |
| `ansible-inventory --host <host>` | Показать переменные хоста | `ansible-inventory --host web01 -i inventories/netbox.yml` |
| `ansible-inventory --list --flush-cache` | Показать инвентарь с очисткой кэша | `ansible-inventory --list --flush-cache -i inventories/consul.yml` |
| `ansible all -i <inventory> -m ping` | Проверить подключение ко всем хостам | `ansible all -i inventories/proxmox.yml -m ping` |

### Команды для проверки и отладки

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-doc -t inventory -l` | Список всех плагинов инвентаря | `ansible-doc -t inventory -l` |
| `ansible-doc -t inventory <plugin>` | Документация плагина | `ansible-doc -t inventory netbox.netbox.nb_inventory` |
| `ansible-inventory --list \| jq '._meta.hostvars'` | Показать все переменные | `ansible-inventory --list \| jq '._meta.hostvars'` |
| `ansible-inventory --list \| jq 'keys'` | Показать все группы | `ansible-inventory --list \| jq 'keys'` |
| `ansible-inventory --list \| jq '.group_name.hosts'` | Показать хосты в группе | `ansible-inventory --list \| jq '.role_web-server.hosts'` |

### Установка коллекций и зависимостей

```bash
# NetBox (CMDB)
ansible-galaxy collection install netbox.netbox
pip install pynetbox requests

# Consul (Service Discovery)
ansible-galaxy collection install community.general
pip install python-consul requests

# Foreman (CMDB)
ansible-galaxy collection install theforeman.foreman
pip install requests

# Proxmox VE
ansible-galaxy collection install community.proxmox
pip install requests proxmoxer

# Etcd (KV-хранилище)
ansible-galaxy collection install community.general
pip install etcd3 requests
```

---

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `No hosts matched` | Хосты не найдены в динамическом инвентаре | Проверьте фильтры, теги, доступ к источнику |
| `Authentication failed` | Неверные credentials для доступа к источнику | Проверьте API ключи, токены, переменные окружения |
| `Cache is stale` | Кеш устарел | Очистите кеш: `rm -rf /tmp/*_cache` или `ansible-inventory --flush-cache` |
| `Plugin not found` | Плагин не установлен | Установите коллекцию: `ansible-galaxy collection install <collection>` |
| `Invalid JSON output` | Динамический инвентарь возвращает невалидный JSON | Проверьте скрипт, используйте `--list` для диагностики |
| `Slow inventory generation` | Большой объем хостов или медленный источник | Используйте кеширование, увеличьте `cache_timeout`, фильтруйте запросы |
| `Missing variables in hostvars` | Переменные не извлекаются из источника | Проверьте маппинг полей в конфигурации плагина |
| `KeyError: 'ansible_host'` | Не задан `compose: ansible_host` | Добавьте `compose: ansible_host: <ip_expression>` |
| `Permission denied` | Нет прав на чтение ключа | Проверьте права доступа к файлу ключа |
| `Connection timeout` | API недоступен | Проверьте сеть, firewall, endpoint URL |

---

## Рекомендации

### Best Practices

1. **Source of truth** — используйте CMDB (NetBox, Foreman) как единый источник истины о хостах. Избегайте дублирования данных в статических файлах.
2. **Cache inventory** — всегда включайте кеширование (`cache: true`) для уменьшения нагрузки на источник и сокращения времени генерации.
3. **Filter at source** — используйте `query_filters` или `filter` для ограничения количества возвращаемых хостов на стороне API.
4. **Security** — защищайте credentials через Ansible Vault или переменные окружения. Никогда не коммитьте токены в Git.
5. **Validation** — проверяйте инвентарь перед использованием: `ansible-inventory --graph` и `ansible-inventory --list`.
6. **Versioning** — фиксируйте версии коллекций в `requirements.yml` для воспроизводимости.
7. **Blast radius minimization** — используйте `--limit` для ограничения целевых хостов. В production-средах применяйте канареечный деплой.
8. **Observability** — логируйте генерацию инвентаря и изменения в группах. Используйте callback-плагины для интеграции с системами мониторинга.
9. **Change management** — внесение изменений в конфигурацию инвентаря должно проходить через code review и CI/CD.
10. **MTTR reduction** — кешируйте инвентарь и факты, чтобы сократить время запуска плейбуков при инцидентах.

### Чек-лист валидации после настройки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Плагин установлен | `ansible-doc -t inventory <plugin>` | Документация плагина отображается |
| Инвентарь генерируется | `ansible-inventory --list -i <inventory>` | JSON с хостами и группами |
| Количество хостов | `ansible-inventory --list \| jq '._meta.hostkeys \| length'` | Ожидаемое количество |
| Группы созданы | `ansible-inventory --graph -i <inventory>` | Дерево групп корректно |
| Переменные хоста | `ansible-inventory --host <host> -i <inventory>` | Переменные populated |
| Подключение | `ansible all -i <inventory> -m ping` | Все хосты доступны |
| Кеширование | `ls -la /tmp/*_cache` | Кеш-файлы созданы |
| Секреты защищены | `grep -r "token\|password" <inventory>` | Нет plaintext секретов |

---

## Дополнительная информация

### Смотрите также

- **[Динамический инвентарь в Ansible](../dynamic_inventory.md)** — полное руководство по плагинам NetBox, Consul, Foreman, Proxmox, Etcd, Terraform, кэшированию, безопасности и CI/CD.
- **[Кроссплатформенный инвентарь и факты](../CrossPlatform/ansible_cross_platform_inventory_and_facts.md)** — `hostvars`, `group_by`, fact caching, `delegate_facts`, host patterns для mixed-парков.
- **[Ansible: Безопасность](../ansible_security_best_practices.md)** — защита credentials, Ansible Vault, `no_log`.

### Интеграция с внешними системами

| Система | Назначение | Интеграция |
|---|---|---|
| **NetBox** | CMDB | `netbox.netbox.nb_inventory` plugin |
| **Foreman** | CMDB | `theforeman.foreman.foreman` plugin |
| **Consul** | Service Discovery | `community.general.consul` plugin |
| **Etcd** | KV-хранилище | `community.general.etcd3` plugin |
| **Proxmox VE** | Виртуализация | `community.proxmox.proxmox` plugin |
| **Git** | Версионирование хостов | Directory Inventory + статические файлы |
| **Terraform** | IaC | `terraform output` + кастомный скрипт |

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Большое количество хостов | Генерация инвентаря занимает много времени | Используйте кеширование, фильтруйте запросы на стороне API |
| Источник недоступен | Ansible не может получить инвентарь | Используйте fallback к статическому инвентарю |
| Частые изменения хостов | Инвентарь устаревает быстро | Уменьшите `cache_timeout`, используйте webhooks |
| Утечка credentials | API ключи в открытом виде | Используйте Ansible Vault, переменные окружения |
| Нестабильная группировка | Группы меняются слишком часто | Используйте стабильные идентификаторы (ID вместо имен) |
| Кэш + Vault | Зашифрованные переменные сохраняются в кэш как литералы | Используйте раздельные кэши или отключайте кэширование для инвентарей с `!vault` |
