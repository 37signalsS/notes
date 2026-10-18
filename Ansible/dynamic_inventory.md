# Динамический инвентарь в Ansible

## Определения

- **Динамический инвентарь** — механизм Ansible, который формирует список управляемых узлов и их переменные «на лету», обращаясь к внешнему источнику правды. В отличие от статического файла, он всегда отражает актуальное состояние инфраструктуры в условиях постоянно меняющегося парка серверов, виртуальных машин и сетевых устройств.
- **Плагин инвентаря (Inventory Plugin)** — современный, нативный и рекомендуемый способ реализации (Ansible 2.4+), использующий YAML-конфигурации и поддерживающий кэширование. Файл конфигурации плагина должен заканчиваться на `.yml` или `.yaml`.
- **Исполняемый скрипт (Executable Script)** — legacy-способ: исполняемый файл (Python, Bash, Go), который при вызове с флагами `--list` или `--host <hostname>` возвращает JSON. Уступает место плагинам, но используется для кастомных систем.
- **Directory Inventory (Комбинированный инвентарь)** — директория, содержащая несколько источников инвентаря (статические `hosts.yml` + динамические плагины `.yml`), которые Ansible объединяет в один логический инвентарь. Сканируется рекурсивно, по алфавиту.
- **CMDB-based Inventory** — инвентарь, источником правды для которого служит система управления конфигурацией и изменениями (Configuration Management Database), например NetBox, Foreman.
- **Service Discovery Inventory** — инвентарь, построенный на системах обнаружения сервисов, например Consul, которые автоматически регистрируют активные узлы и их метаданные.
- **Keyed Groups** — механизм автоматического создания групп Ansible на основе значений атрибутов хоста с использованием префиксов и разделителей.
- **Compose** — механизм создания или переопределения переменных хоста через Jinja2-выражения.
- **Hostnames** — механизм определения имени хоста в инвентаре (`inventory_hostname`) с приоритетом шаблонов.

---

## Предварительные требования

### Установка коллекций

Для работы с локальными и self-hosted системами необходимы соответствующие коллекции:

```bash
# NetBox (CMDB)
ansible-galaxy collection install netbox.netbox

# Consul (Service Discovery)
ansible-galaxy collection install community.general

# Etcd (KV-хранилище)
ansible-galaxy collection install community.general

# Foreman (CMDB)
ansible-galaxy collection install theforeman.foreman

# Proxmox VE
ansible-galaxy collection install community.proxmox

# Общие утилиты
ansible-galaxy collection install community.general
```

### Проверка доступных плагинов

```bash
# Список всех плагинов инвентаря
ansible-doc -t inventory -l

# Документация конкретного плагина
ansible-doc -t inventory netbox.netbox.nb_inventory
ansible-doc -t inventory community.general.consul
ansible-doc -t inventory theforeman.foreman.foreman
ansible-doc -t inventory community.proxmox.proxmox
ansible-doc -t inventory community.general.etcd3
```

### Python-зависимости

```bash
# NetBox
pip install pynetbox requests

# Consul
pip install python-consul requests

# Etcd
pip install etcd3 requests

# Foreman
pip install requests

# Proxmox
pip install requests proxmoxer

# Общее
pip install requests
```

---

## Основные концепции

### Когда это необходимо

- **Гетерогенная инфраструктура**: Парк включает серверы разных платформ (bare metal, виртуальные машины Proxmox, VMware ESXi), сетевые устройства и специализированное оборудование, размещенное в собственных датацентрах или филиалах.
- **Мультиаккаунтность и мультитенантность**: Необходимо объединять ресурсы из нескольких локальных систем учета (NetBox, Foreman) и сред (development, staging, production) в единый инвентарь.
- **Теги и метки как источник групп**: Возможность формировать группы по бизнес-метаданным (Role, Environment, Stage, Owner, Site, Rack) без ручной правки инвентаря.
- **Синхронизация с CMDB**: Автоматическое получение актуальных данных из корпоративных систем учета (NetBox, Foreman, iTop) для исключения рассогласований между документацией и реальным парком.
- **Служебные и эфемерные среды**: Автоматическое обновление инвентаря при добавлении/удалении виртуальных машин, контейнеров или сервисов внутри self-hosted платформ (Proxmox, Kubernetes на bare metal).
- **Network Automation**: Получение актуального списка сетевых устройств и их ролей из DCIM для выполнения автоматизированных изменений конфигурации.

### Способы реализации

1. **Плагины инвентаря (Inventory plugins)**: Предпочтительный, нативный способ. Ansible предоставляет плагины для большинства локальных систем (например, `netbox.netbox.nb_inventory`, `community.general.consul`, `theforeman.foreman.foreman`, `community.proxmox.proxmox`). Конфигурируются через YAML-файлы.
2. **Встроенные плагины**: Нативные плагины, поставляемые с Ansible: `yaml`, `ini`, `script`, `host_list`, `advanced_host_list`, `regex`, `constructed`, `templar`, `file`. Не требуют установки дополнительных коллекций.
3. **Исполняемые скрипты**: Любой исполняемый файл (на Python, Bash и др.), который при запуске с флагом `--list` возвращает **JSON** в специальном формате. Этот способ считается legacy и уступает место плагинам, но все еще используется для специфических самописных систем.
4. **Комбинированный подход (Directory Inventory)**: Директория `inventories/` может содержать несколько источников (статические файлы `hosts.yml` и динамические конфигурации `.yml`), которые Ansible объединяет в один логический инвентарь.

### Производительность и кэширование

Обращения к локальным API (NetBox, Consul, Foreman) могут замедлять генерацию инвентаря при частом выполнении. Для решения этой проблемы рекомендуется:

- **Включать кэширование** на уровне инвентарного плагина или глобально в `ansible.cfg`.
- **Использовать фильтры** в конфигурации плагина, чтобы ограничивать область поиска на стороне API (например, только активные устройства или определенные организации).
- **Использовать `compose`** для формирования переменных хоста только из необходимых данных, снижая объем передаваемых JSON.
- **«Прогревать» кэш** в пайплайнах **CI/CD**, запуская `ansible-inventory` перед основным плейбуком.

**Пример настройки кэширования в `ansible.cfg`:**

```ini
[inventory]
# Включение нужных плагинов (порядок имеет значение)
enable_plugins = host_list, script, yaml, ini, netbox.netbox.nb_inventory, community.general.consul, theforeman.foreman.foreman, community.proxmox.proxmox, constructed, advanced_host_list
cache = True
cache_plugin = jsonfile
cache_timeout = 3600
cache_connection = ~/.ansible/cache/inventory
```

**Кэширование на уровне плагина (NetBox):**

```yaml
# inventories/netbox.yml
plugin: netbox.netbox.nb_inventory
api_endpoint: https://netbox.internal
token: "{{ vault_netbox_token }}"
validate_certs: true

cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 3600
cache_connection: /tmp/netbox_inventory_cache
```

**Кэширование на уровне плагина (Consul):**

```yaml
# inventories/consul.yml
plugin: community.general.consul
consul_url: http://consul.internal:8500
token: "{{ vault_consul_token }}"
filter: "Service.Status == 'passing'"

cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 600
cache_connection: /tmp/consul_inventory_cache
```

---

## Механизмы keyed_groups, compose, groups и hostnames

Это мощные инструменты плагинов для динамического формирования структуры инвентаря:

### hostnames

Определяет имя хоста в инвентаре (`inventory_hostname`). Принимает список шаблонов — Ansible использует первый успешный результат.

```yaml
hostnames:
  - "{{ primary_ip4.address | regex_replace('/.*$', '') }}"  # NetBox: IP из CMDB или имя
  - "{{ labels.role }}-{{ name }}"                           # Proxmox: "web-vm01"
  - private_ip_address                                        # Локальный IP
  - config.name + "_" + config.uuid                           # VMware/Proxmox
  - "public_ip", "private_ip", "name"                         # Приоритет
```

### keyed_groups

Создает группы на основе значений атрибутов хоста. Каждый элемент списка определяет одну группу.

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **key** | Jinja2-выражение для получения значения | `device_roles.name`, `labels.env`, `site.name` |
| **prefix** | Префикс имени группы | `role`, `env`, `site` |
| **separator** | Разделитель между префиксом и значением | `_`, `` (пустая строка) |
| **parent_group** | Родительская группа | `production` |
| **default_value** | Значение по умолчанию, если key = None | `unknown` |
| **trailing_separator** | Добавлять ли разделитель после значения | `true`/`false` |
| **leading_separator** | Добавлять ли разделитель перед префиксом | `true`/``false` |

```yaml
keyed_groups:
  # По роли устройства в NetBox: группа "role_web-server"
  - key: device_roles.name
    prefix: role
    separator: "_"

  # По сайту: группа "site_office"
  - key: site.name
    prefix: site
    separator: "_"

  # По платформе ОС: группа "os_centos"
  - key: platforms.name
    prefix: os

  # По статусу в Foreman: группа "active"
  - key: foreman_status
    prefix: status

  # С parent_group: все подгруппы внутри "production"
  - key: site.name
    prefix: site
    parent_group: production

  # С default_value: если роль не задана, используется "unknown"
  - key: device_roles.name
    prefix: role
    default_value: "unknown"
```

### compose

Создает или переопределяет переменные хоста через Jinja2-выражения. Часто используется для установки `ansible_host` из конкретного IP-адреса.

```yaml
compose:
  # NetBox: первичный IP без CIDR-маски
  ansible_host: primary_ip4.address | regex_replace('/.*$', '')

  # Foreman: IP-адрес для управления
  ansible_host: foreman_ip

  # Proxmox: IP для подключения к ВМ
  ansible_host: proxmox_net0_ip | default(proxmox_ip)

  # Consul: адрес сервиса
  ansible_host: Address
  consul_node_name: Node
  consul_service_meta: ServiceMeta

  # Etcd: произвольные метаданные хоста
  dc: datacenter
  rack: rack

  # Произвольные переменные
  is_production: "'prod' in (site.name | default(''))"
  cpu_count: config.hardware.numCPU
```

### groups

Добавляет хосты в группы на основе Jinja2-условий (boolean). В отличие от `keyed_groups`, здесь можно задать сложные условия.

```yaml
groups:
  # Если сайт содержит "office"
  branch_office: "'office' in (site.name | default(''))"

  # Если нет публичного IP
  private_only: "ansible_host is not defined"

  # Если статус = Active И платформа = Linux
  active_linux: "status == 'Active' and platforms.name is search('linux')"

  # Если роль устройства = сервер
  servers: "device_roles.name == 'server'"

  # Если Foreman environment = production
  production: "foreman_environment == 'production'"

  # Если Proxmox status = running
  running: "proxmox_status == 'running'"
```

### Полный пример: комбинация всех механизмов (NetBox)

```yaml
# inventories/production/netbox.yml
plugin: netbox.netbox.nb_inventory
api_endpoint: https://netbox.internal
token: "{{ vault_netbox_token }}"
validate_certs: true

# Приоритет именования хостов
hostnames:
  - "{{ primary_ip4.address | regex_replace('/.*$', '') }}"
  - name

# Автоматическая группировка по ролям, сайтам и платформам
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

# Сложные условия группировки
groups:
  branch_office: "'office' in (site.name | default(''))"
  servers: "device_roles.name == 'server'"
  production: "status == 'Active'"

# Сопоставление переменных хоста
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

---

## Практические сценарии

### Сравнение статического и динамического подходов

| Критерий | Статический инвентарь | Динамический инвентарь |
| :--- | :--- | :--- |
| **Актуальность** | Требует ручного обновления | Вытягивается из CMDB/Service Discovery |
| **Масштабируемость** | Ограничена размером файла | Горизонтально масштабируется |
| **Человеческий фактор** | Высокий риск ошибок | Снижается за счет автоматизации |
| **Группировка** | Ручные группы | Автоматически, по метаданным/фильтрам |
| **Производительность** | Быстро локально | Требует кэширования для API |
| **Зависимости** | Нет | Требует коллекции, Python-пакетов |
| **Отладка** | Просмотр файла | `ansible-inventory --graph/--list` |

### Инвентарь на основе CMDB (NetBox)

NetBox выступает единым источником правды для всей инфраструктуры. Плагин `nb_inventory` из коллекции `netbox.netbox`.

См. также: [Автоматизация заполнения NetBox через API](../Networking/NetBox/netbox-automation-python.md).

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

### Инвентарь на основе Service Discovery (Consul)

Consul используется как источник инвентаря для динамических сред вне Kubernetes (классические ВМ с установленным Consul Agent). Плагин `consul` из коллекции `community.general` позволяет автоматически получать список хостов на основе зарегистрированных сервисов и их тегов.

```yaml
plugin: community.general.consul
consul_url: http://consul.internal:8500
# Авторизация (рекомендуется использовать ACL токены)
token: "{{ vault_consul_token }}"

# Фильтрация хостов: только те, что прошли Health Checks
filter: "Service.Status == 'passing'"

# Группировка хостов
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

**Особенности:**
- **Health-aware**: Исключаются хосты, помеченные как `critical` или `warning`.
- **Гибкость**: Позволяет использовать метаданные сервисов (`ServiceMeta`) для формирования переменных Ansible.

### Инвентарь на основе KV-хранилищ (Etcd)

Etcd (версии 3) может использоваться как низкоуровневое хранилище данных об инвентаре для кастомных систем оркестрации, где список хостов и их параметры хранятся в виде иерархии ключей. Плагин `etcd3` из коллекции `community.general`.

```yaml
plugin: community.general.etcd3
host: "etcd-cluster.internal"
port: 2379
user: "ansible"
password: "{{ vault_etcd_password }}"

# Префикс ключей, под которыми хранится инвентарь
key_prefix: "/ansible/inventory/hosts/"

# Использование сертификатов (рекомендуется)
cert_file: "/path/to/cert.pem"
key_file: "/path/to/key.pem"
ca_cert: "/path/to/ca.pem"

# Кэширование
cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 1800
cache_connection: /tmp/etcd_inventory_cache
```

**Особенности:**
- **Структура ключей**: Плагин ожидает, что данные в etcd хранятся в формате JSON или YAML.
- **Производительность**: Хорошо подходит для очень больших, но стабильных списков хостов, где Consul может быть избыточен.

### Инвентарь на основе Foreman

Foreman — локальная CMDB для управления bare metal и виртуальными машинами. Плагин `foreman` из коллекции `theforeman.foreman`.

```yaml
# inventories/foreman.yml
plugin: theforeman.foreman.foreman
url: "https://foreman.internal"
user: "automation"
password: "{{ vault_foreman_password }}"
validate_certs: true
want_facts: true
want_hostgroups: true
plain_host_names: true

# Группировка по ОС, организации и местоположению
keyed_groups:
  - key: foreman_operatingsystem_name
    prefix: os
  - key: foreman_organization_name
    prefix: org
  - key: foreman_location_name
    prefix: location

# Условия группировки
groups:
  production: "foreman_environment == 'production'"
  development: "foreman_environment == 'development'"
  vm_hosts: "'virtual' in (foreman_is_virtual | default('false'))"

# Сопоставление переменных хоста
compose:
  ansible_host: foreman_ip
  foreman_params: foreman_params
  foreman_facts: foreman_facts

# Кэширование
cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 1800
cache_connection: /tmp/foreman_inventory_cache
```

**Запуск:**
```bash
ansible-playbook -i inventories/foreman.yml playbooks/site.yml --limit "os_centos"
```

### Инвентарь на основе Proxmox VE

Proxmox VE — self-hosted платформа виртуализации. Плагин `proxmox` из коллекции `community.proxmox` автоматически получает список всех VM, LXC и узлов. Имя файла **обязано** заканчиваться на `.proxmox.yml`/`.proxmox.yaml` — иначе Ansible не распознает источник. Профильные примеры (теги, фильтры, connection plugins) — в [Автоматизация Proxmox VE через Ansible](../Proxmox/proxmox_ansible.md).

```yaml
# inventories/pve.proxmox.yml
plugin: community.proxmox.proxmox
url: https://pve1.internal:8006
user: "automation@pam!ansible"
password: "{{ vault_proxmox_password }}"
want_facts: true
want_proxmox_nodes_ansible_host: false
validate_certs: false

# Сопоставление IP для подключения (факты want_facts)
compose:
  ansible_host: >-
    proxmox_ipconfig0.ip | default(proxmox_net0.ip)
    | default(proxmox_ip) | ipaddr('address')

# Группировка по статусу, узлу, тегам и типу гостя
keyed_groups:
  - key: proxmox_status
    prefix: status
  - key: proxmox_node
    prefix: node
  - key: proxmox_tags_parsed
    separator: ""
    prefix: tag
  - key: proxmox_vmtype
    prefix: type

# Условия группировки
groups:
  running: "proxmox_status == 'running'"
  stopped: "proxmox_status == 'stopped'"
  lxc_containers: "proxmox_vmtype == 'lxc'"
  virtual_machines: "proxmox_vmtype == 'qemu'"

# Кэширование
cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 300
cache_connection: /tmp/proxmox_inventory_cache
```

**Запуск:**
```bash
ansible-playbook -i inventories/pve.proxmox.yml playbooks/site.yml \
  --limit "node_pve1"
```

### Инвентарь на основе Terraform State

Распространенный паттерн — использование данных Terraform как источника правды для инфраструктуры, описанной кодом (IaC).

#### 1. Использование плагинов для Terraform State

Использование специализированных плагинов, которые читают файл состояния (`terraform.tfstate`) напрямую.

```yaml
# inventories/terraform.yml
plugin: cloud.terraform.terraform_provider
project_path: /path/to/terraform/project
# Плагин автоматически найдет ресурсы и создаст хосты на основе state-файла
```

#### 2. Генерация через `terraform output`

Подход с ручной генерацией на основе вывода `terraform output`, полезен при отсутствии подходящего плагина:

1. Terraform описывает данные (IP-адреса, имена хостов) в блоках `output`.

    ```hcl
    output "instance_ips" {
      value = {
        for vm in proxmox_vm_qemu.my_vms:
        vm.name => vm.default_ipv4_address
      }
    }
    ```

2. Вывод сохраняется в JSON-файл после применения (`terraform apply`).

    ```bash
    terraform output -json > tf_output.json
    ```

3. Кастомный скрипт (или плагин `file`) парсит этот JSON и генерирует инвентарь.

#### 3. Цепочка: Terraform → Dynamic Inventory → Ansible Playbook

```bash
# 1. Применение Terraform
cd terraform/ && terraform apply -auto-approve

# 2. Генерация инвентаря
terraform output -json > /tmp/tf_output.json
python3 scripts/tf_to_inventory.py --input /tmp/tf_output.json --output /tmp/inventory.json

# 3. Запуск Ansible с динамическим инвентарем
ansible-playbook playbooks/site.yml -i /tmp/inventory.json

# Или комбинированный инвентарь
ansible-playbook playbooks/site.yml -i inventories/production/
```

#### 4. Скрипт конвертации Terraform → JSON Inventory

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

    # Извлекаем хосты из output
    hosts = tf_output.get("instance_ips", {}).get("value", {})

    # Группируем по префиксу имени
    groups = {}
    for hostname, ip in hosts.items():
        # Определяем группу по имени (web-01 → web, db-01 → db)
        group = hostname.split("-")[0] if "-" in hostname else "ungrouped"
        groups.setdefault(group, []).append(hostname)

        # Добавляем hostvars
        inventory["_meta"]["hostvars"][hostname] = {
            "ansible_host": ip,
            "tf_name": hostname,
        }

    # Формируем группы
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

### Инвентарь на основе Git

Git может выступать источником правды для списка хостов, особенно в комбинации с CMDB. Подход — хранить статичные `hosts.yml` и `host_vars` в Git, а динамические изменения подмешивать через Directory Inventory.

```yaml
# inventories/production/host_vars/web01.yml
ansible_host: 10.0.0.10
ansible_port: 22
ansible_user: deploy
environment: production
role: web-server
site: office

# inventories/production/group_vars/webservers.yml
ansible_port: 22
ntp_servers:
  - 10.0.0.1
  - 10.0.0.2
```

**Комбинирование статического Git-инвентаря с динамическим CMDB:**

```bash
# Использование нескольких источников (порядок имеет значение)
ansible-playbook playbooks/site.yml \
  -i inventories/production/hosts.yml \
  -i inventories/production/netbox.yml
```

### Инвентарь с использованием constructed plugin

Встроенный плагин `constructed` позволяет создавать и изменять переменные инвентаря, а также формировать группы на основе Jinja2-выражений. Особенно полезен для модификации статического инвентаря без изменения исходных файлов.

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

**Запуск с комбинированием статического и constructed инвентаря:**

```bash
ansible-playbook playbooks/site.yml \
  -i inventories/production/hosts.yml \
  -i inventories/constructed.yml
```

### Исполняемые скрипты (Legacy)

Несмотря на то, что плагины предпочтительнее, скрипты остаются вариантом для кастомных систем.

#### Python-скрипт

```python
#!/usr/bin/env python3
# scripts/dynamic_inventory.py
"""Динамический инвентарь из базы данных / API."""
import json
import argparse
import sys
import os
import requests

def get_inventory():
    """Получение инвентаря из внешнего источника."""
    api_url = os.environ.get("INVENTORY_API_URL", "http://cmdb.internal/api/hosts")
    token = os.environ.get("INVENTORY_API_TOKEN")

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(api_url, headers=headers)
    response.raise_for_status()

    hosts_data = response.json()

    inventory = {
        "_meta": {"hostvars": {}},
        "all": {"children": []},
    }

    groups = {}
    for host in hosts_data:
        hostname = host["name"]
        group = host.get("group", "ungrouped")
        groups.setdefault(group, []).append(hostname)

        inventory["_meta"]["hostvars"][hostname] = {
            "ansible_host": host["ip"],
            "ansible_port": host.get("port", 22),
            "environment": host.get("env", "unknown"),
        }

    for group_name, group_hosts in groups.items():
        inventory[group_name] = {"hosts": group_hosts}
        inventory["all"]["children"].append(group_name)

    return inventory

def get_host_vars(hostname):
    """Получение переменных для конкретного хоста."""
    api_url = os.environ.get("INVENTORY_API_URL", "http://cmdb.internal/api/hosts")
    token = os.environ.get("INVENTORY_API_TOKEN")

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(f"{api_url}/{hostname}", headers=headers)
    response.raise_for_status()

    host_data = response.json()
    return {
        "ansible_host": host_data["ip"],
        "ansible_port": host_data.get("port", 22),
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dynamic Inventory Script")
    parser.add_argument("--list", action="store_true", help="List all hosts and groups")
    parser.add_argument("--host", type=str, help="Get host variables")
    args = parser.parse_args()

    if args.list:
        print(json.dumps(get_inventory(), indent=2))
    elif args.host:
        print(json.dumps(get_host_vars(args.host), indent=2))
    else:
        print(json.dumps({"_meta": {"hostvars": {}}}, indent=2))
```

#### Bash-скрипт

```bash
#!/bin/bash
# scripts/dynamic_inventory.sh
# Динамический инвентарь из CSV-файла

INVENTORY_FILE="${INVENTORY_FILE:-/etc/ansible/inventory.csv}"

if [ "$1" == "--list" ]; then
    echo '{"_meta": {"hostvars": {}}, "all": {"children": []}}' | python3 -c "
import json, csv, sys

inventory = json.load(sys.stdin)
groups = {}

with open('${INVENTORY_FILE}') as f:
    reader = csv.DictReader(f)
    for row in reader:
        host = row['hostname']
        group = row.get('group', 'ungrouped')
        groups.setdefault(group, []).append(host)
        inventory['_meta']['hostvars'][host] = {
            'ansible_host': row['ip'],
            'ansible_port': int(row.get('port', 22)),
        }

for group, hosts in groups.items():
    inventory[group] = {'hosts': hosts}
    inventory['all']['children'].append(group)

print(json.dumps(inventory, indent=2))
"
elif [ "$1" == "--host" ]; then
    echo '{}' | python3 -c "
import json, csv, sys

hostname = '$2'
inventory = json.load(sys.stdin)

with open('${INVENTORY_FILE}') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['hostname'] == hostname:
            print(json.dumps({
                'ansible_host': row['ip'],
                'ansible_port': int(row.get('port', 22)),
            }, indent=2))
            sys.exit(0)

print('{}')
"
else
    echo '{"_meta": {"hostvars": {}}}'
fi
```

```bash
# Сделать скрипт исполняемым
chmod +x scripts/dynamic_inventory.sh

# Использование
ansible-playbook site.yml -i scripts/dynamic_inventory.sh
```

### Directory Inventory (Комбинированный подход)

Директория `inventories/` может содержать несколько источников инвентаря. Ansible рекурсивно сканирует её по алфавиту.

```
inventories/
├── production/
│   ├── hosts.yml                  # Статический инвентарь
│   ├── netbox.yml                 # Динамический: CMDB
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
    ├── consul.yml                 # Service Discovery
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

### Сценарий: CMDB/NetBox как Dynamic Inventory (полный цикл)

#### Архитектура: CMDB → Dynamic Inventory → Ansible → CMDB обратная связь

```
┌─────────────┐     Pull      ┌─────────────────┐     Apply     ┌─────────────────┐
│   NetBox    │◄──────────────│  Ansible        │──────────────►│  Managed Hosts  │
│  (source)   │  Inventory    │  Control Node   │  Playbooks    │  (500+ servers) │
└──────┬──────┘               └─────────────────┘               └─────────────────┘
        │                             │
        │  Push facts back            │  Update CMDB
        └─────────────────────────────┘
```

#### NetBox Dynamic Inventory Plugin

```yaml
# inventories/netbox.yml
plugin: netbox.netbox.nb_inventory
api_endpoint: "https://netbox.internal"
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

#### NetBox как источник правды: полный цикл обратной связи

```yaml
---
- name: Sync Ansible facts back to NetBox
  hosts: all
  connection: local
  gather_facts: true
  vars:
    netbox_url: "https://netbox.internal"
    netbox_token: "{{ vault_netbox_token }}"
  tasks:
    - name: Update NetBox with current facts
      netbox.netbox.netbox_device:
        netbox_url: "{{ netbox_url }}"
        token: "{{ netbox_token }}"
        data:
          name: "{{ inventory_hostname }}"
          serial: "{{ ansible_facts.product_serial }}"
          platform: "{{ ansible_facts.distribution }} {{ ansible_facts.distribution_version }}"
          primary_ip4: "{{ ansible_facts.default_ipv4.address }}/32"
          status: active
          site: "{{ netbox_site | default('default') }}"
          device_role: "{{ netbox_role | default('server') }}"
        state: present

    - name: Update NetBox with interfaces
      netbox.netbox.netbox_interface:
        netbox_url: "{{ netbox_url }}"
        token: "{{ netbox_token }}"
        data:
          device: "{{ inventory_hostname }}"
          name: "{{ item.key }}"
          type: "1000base-t"
          enabled: true
        state: present
      loop: "{{ ansible_facts.interfaces | dict2items }}"
      when: item.value.active | default(true)

    - name: Update NetBox with IP addresses
      netbox.netbox.netbox_ip_address:
        netbox_url: "{{ netbox_url }}"
        token: "{{ netbox_token }}"
        data:
          address: "{{ ansible_facts.default_ipv4.address }}/32"
          status: active
          assigned_object:
            device: "{{ inventory_hostname }}"
            name: "{{ ansible_facts.default_ipv4.interface }}"
        state: present
```

#### Автоматическая синхронизация через Scheduled Job

```yaml
---
- name: Scheduled NetBox sync
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Pull inventory from NetBox
      ansible.builtin.command:
        cmd: ansible-inventory -i inventories/netbox.yml --list --yaml
      register: netbox_inventory

    - name: Compare with previous snapshot
      ansible.builtin.copy:
        content: "{{ netbox_inventory.stdout }}"
        dest: /tmp/netbox_inventory_current.yml
        mode: "0644"

    - name: Detect changes
      ansible.builtin.command:
        cmd: diff /tmp/netbox_inventory_previous.yml /tmp/netbox_inventory_current.yml
      register: diff_result
      ignore_errors: true
      changed_when: diff_result.rc != 0

    - name: Alert on inventory changes
      ansible.builtin.uri:
        url: "{{ slack_webhook_url }}"
        method: POST
        body_format: json
        body:
          text: "CMDB drift detected! Inventory changes:\n{{ diff_result.stdout }}"
      when: diff_result.rc != 0

    - name: Update snapshot
      ansible.builtin.copy:
        content: "{{ netbox_inventory.stdout }}"
        dest: /tmp/netbox_inventory_previous.yml
        mode: "0644"
```

### Интеграция с CI/CD

#### GitHub Actions

```yaml
# .github/workflows/ansible-inventory.yml
---
name: Validate Ansible Inventory
on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install ansible
          ansible-galaxy collection install netbox.netbox community.general theforeman.foreman community.proxmox

      - name: Validate inventory
        run: |
          ansible-inventory -i inventories/production/ --graph
          ansible-inventory -i inventories/production/ --list | python3 -m json.tool > /dev/null
```

#### GitLab CI

```yaml
# .gitlab-ci.yml
---
stages:
  - inventory
  - deploy

validate_inventory:
  stage: inventory
  image: python:3.11
  before_script:
    - pip install ansible
    - ansible-galaxy collection install netbox.netbox
  script:
    - ansible-inventory -i inventories/production/netbox.yml --graph
    - ansible-inventory -i inventories/production/netbox.yml --list > /dev/null
  only:
    - changes:
        - inventories/**

deploy:
  stage: deploy
  script:
    - ansible-playbook playbooks/site.yml -i inventories/production/
  only:
    - main
```

---

## Безопасность и управление секретами

### Токены и ключи доступа

Конфигурации динамического инвентаря содержат токены и ключи доступа. **Никогда не коммитьте их в Git в открытом виде.**

1. **Переменные окружения**: Плагины по умолчанию поддерживают переменные типа `NETBOX_TOKEN`, `CONSUL_HTTP_TOKEN`, `FOREMAN_PASSWORD`, `PROXMOX_PASSWORD`, `ETCD_PASSWORD`. Это наиболее безопасный способ для CI/CD.

    ```bash
    # NetBox
    export NETBOX_TOKEN=$(vault read -field=token secret/netbox)

    # Consul
    export CONSUL_HTTP_TOKEN=$(vault read -field=token secret/consul)

    # Foreman
    export FOREMAN_PASSWORD=$(vault read -field=password secret/foreman)

    # Proxmox
    export PROXMOX_PASSWORD=$(vault read -field=password secret/proxmox)

    # Etcd
    export ETCD_PASSWORD=$(vault read -field=password secret/etcd)
    ```

2. **Ansible Vault**: Если ключи хранятся в `.yml` файле инвентаря, его необходимо зашифровать:
    ```bash
    ansible-vault encrypt inventories/prod.netbox.yml
    ansible-playbook site.yml -i inventories/prod.netbox.yml --ask-vault-pass
    ```

3.  **Сторонние хранилища секретов**: Интеграция с HashiCorp Vault, Git-crypt:
    ```yaml
    # Чтение токена из HashiCorp Vault
    token: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/ansible/netbox:token') }}"
    ```

4. **No Log**: При написании кастомных скриптов убедитесь, что они не выводят чувствительные данные в `stderr` или логи:
    ```yaml
    - name: Сбор инвентаря
      command: ./dynamic_inventory.py --list
      no_log: true
    ```

### Шифрование файлов инвентаря

```bash
# Шифрование
ansible-vault encrypt inventories/production/netbox.yml

# Редактирование
ansible-vault edit inventories/production/netbox.yml

# Дешифрование (для проверки)
ansible-vault view inventories/production/netbox.yml

# Запуск с Vault-паролем
ansible-playbook site.yml -i inventories/production/ --ask-vault-pass

# Или через файл пароля
ansible-playbook site.yml -i inventories/production/ --vault-password-file=~/.vault_pass
```

---

## Проверка и отладка динамического инвентаря

### Базовые команды

```bash
# 1. Вывести инвентарь в виде дерева групп (быстрая проверка структуры)
ansible-inventory -i <файл_инвентаря> --graph

# 2. Вывести полный JSON-объект со всеми хостовыми переменными (проверка hostvars)
ansible-inventory -i <файл_инвентаря> --list

# 3. Отладка конкретного хоста
ansible-inventory -i <файл_инвентаря> --host <имя_хоста>

# 4. Проверка с очисткой кэша
ansible-inventory -i <файл_инвентаря> --list --flush-cache

# 5. Режим отладки (показывает ошибки подключения к API)
ansible-inventory -i <файл_инвентаря> --list -vvvv
```

### Практические примеры отладки

```bash
# Проверка NetBox инвентаря
ansible-inventory -i netbox.yml --graph
ansible-inventory -i netbox.yml --list | jq '._meta.hostvars'

# Проверка Foreman
ansible-inventory -i foreman.yml --graph
ansible-inventory -i foreman.yml --host web-server-01

# Проверка Consul
ansible-inventory -i consul.yml --graph
ansible-inventory -i consul.yml --list | jq '.all.children'

# Проверка Proxmox
ansible-inventory -i proxmox.yml --graph
ansible-inventory -i proxmox.yml --list | jq '.all.children'

# Проверка Etcd
ansible-inventory -i etcd.yml --graph
ansible-inventory -i etcd.yml --host etcd-node-01
```

### Устранение типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `No module named 'pynetbox'` | Нет Python-пакета для NetBox | `pip install pynetbox requests` |
| `No module named 'consul'` | Нет Python-пакета для Consul | `pip install python-consul requests` |
| `No module named 'etcd3'` | Нет Python-пакета для Etcd | `pip install etcd3 requests` |
| `Authentication failed` | Неверные учетные данные | Проверьте переменные окружения, Vault |
| `Unable to parse inventory` | Синтаксическая ошибка в YAML/INI | Проверьте формат файла, используйте `yaml` линтер |
| `Plugin not found` | Коллекция не установлена | `ansible-galaxy collection install <collection>` |
| `KeyError: 'ansible_host'` | Не задан `compose: ansible_host` | Добавьте `compose: ansible_host: <ip_expression>` |
| `Cache is stale` | Устаревший кэш инвентаря | `ansible-inventory -i file.yml --list --flush-cache` |
| `Permission denied` | Нет прав на чтение ключа | Проверьте права доступа к файлу ключа |
| `Connection timeout` | API недоступен | Проверьте сеть, firewall, endpoint URL |

### Валидация конфигурации плагина

```bash
# Проверка синтаксиса YAML
python3 -c "import yaml; yaml.safe_load(open('netbox.yml'))"

# Проверка плагина через ansible-doc
ansible-doc -t inventory netbox.netbox.nb_inventory

# Проверка доступных опций плагина
ansible-doc -t inventory -s netbox.netbox.nb_inventory
```

---

## Лучшие практики

1. **Храните конфигурации плагинов в Git** — versioning обеспечивает воспроизводимость.
2. **Используйте переменные окружения** для токенов — не храните их в файлах.
3. **Включайте кэширование** — особенно в CI/CD, чтобы не нагружать локальные API.
4. **Фильтруйте на стороне API** — ограничивайте область поиска (только нужные организации/статусы/теги).
5. **Используйте `keyed_groups`** для автоматической группировки — вместо ручного создания групп.
6. **Используйте `compose`** для `ansible_host` — плагин не всегда может определить IP автоматически.
7. **Проверяйте инвентарь перед запуском** — `ansible-inventory --graph` перед `ansible-playbook`.
8. **Шифруйте файлы с секретами** — `ansible-vault encrypt` для любых токенов/паролей.
9. **Комбинируйте источники** — Directory Inventory для мультиаккаунта и мультисредности.
10. **Настройте `no_log`** для скриптов, работающих с секретами.

---

## Дополнительная информация

- [Установка и настройка Ansible](ansible_setup_and_config.md) — базовые концепции инвентаря.
- [Официальная документация по плагинам инвентаря](https://docs.ansible.com/ansible/latest/plugins/inventory.html)
- [Официальная документация: NetBox](https://docs.ansible.com/ansible/latest/collections/netbox/netbox/nb_inventory_inventory.html)
- [Официальная документация: Consul](https://docs.ansible.com/ansible/latest/collections/community/general/consul_inventory.html)
- [Официальная документация: Foreman](https://docs.ansible.com/ansible/latest/collections/theforeman/foreman/foreman_inventory.html)
- [Официальная документация: Proxmox](https://docs.ansible.com/ansible/latest/collections/community/proxmox/proxmox_inventory.html)
- [Структура проекта](examples/example_project_layout.md) — организация файлов и каталогов.
- [Ansible Vault: Лучшие практики](Vault/best_practices.md) — шифрование конфигураций инвентаря.
- [Оптимизация производительности](ansible_performance_tuning.md) — тюнинг SSH и кэширования.
- [Динамический инвентарь для сетевого оборудования](ansible_network_automation.md) — NetBox + Network Automation.
