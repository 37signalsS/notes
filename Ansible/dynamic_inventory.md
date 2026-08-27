# Динамический инвентарь в Ansible

## Определения

- **Динамический инвентарь** — это механизм Ansible, который формирует список управляемых узлов (хостов) и их переменные «на лету», обращаясь к внешнему источнику правды (Single Source of Truth, SSoT). В отличие от статического файла, он всегда отражает актуальное состояние инфраструктуры, что критично для облачных и эфемерных сред.
- **Плагин инвентаря (Inventory Plugin)** — современный, нативный и рекомендуемый способ реализации (Ansible 2.4+), использующий YAML-конфигурации и поддерживающий кэширование. Файл конфигурации плагина должен заканчиваться на `.yml` или `.yaml`.
- **Исполняемый скрипт (Executable Script)** — legacy-способ: исполняемый файл (Python, Bash, Go), который при вызове с флагами `--list` или `--host <hostname>` возвращает JSON. Уступает место плагинам, но используется для кастомных систем.
- **Directory Inventory (Комбинированный инвентарь)** — директория, содержащая несколько источников инвентаря (статические `hosts.yml` + динамические плагины `.yml`), которые Ansible объединяет в один логический инвентарь. Сканируется рекурсивно, по алфавиту.

---

## Предварительные требования

### Установка коллекций

Для работы с облачными провайдерами необходимы соответствующие коллекции:

```bash
# AWS EC2
ansible-galaxy collection install amazon.aws

# Yandex Cloud
ansible-galaxy collection install yandex.cloud

# Google Cloud
ansible-galaxy collection install google.cloud

# Azure
ansible-galaxy collection install azure.azcollection

# VMware (новый плагин)
ansible-galaxy collection install vmware.vmware

# OpenStack
ansible-galaxy collection install openstack.cloud

# Kubernetes
ansible-galaxy collection install kubernetes.core

# NetBox
ansible-galaxy collection install netbox.netbox

# Consul / Etcd
ansible-galaxy collection install community.general
```

### Проверка доступных плагинов

```bash
# Список всех плагинов инвентаря
ansible-doc -t inventory -l

# Документация конкретного плагина
ansible-doc -t inventory amazon.aws.aws_ec2
ansible-doc -t inventory yandex.cloud.yandex_cloud
ansible-doc -t inventory google.cloud.gcp_compute
```

### Python-зависимости

```bash
# AWS
pip install boto3 botocore

# Google Cloud
pip install google-auth requests

# Azure
pip install azure-identity azure-mgmt-compute

# OpenStack
pip install openstacksdk

# VMware
pip install pyvmomi requests
```

---

## Основные концепции

### Когда это необходимо

- **Эфемерные среды и автоскейлинг**: Облачные экземпляры создаются и удаляются автоматически, статический список моментально устаревает.
- **Мультиоблако и мультиаккаунты**: Необходимо объединять ресурсы из нескольких провайдеров (AWS, GCP, Azure) и учетных записей.
- **Теги и метки как источник групп**: Возможность формировать группы по метаданным (`Role`, `Environment`, `Stage`, `Owner`) без ручной правки инвентаря.
- **Контейнерные платформы**: Получение актуального списка узлов и сервисов через API кластеров (Kubernetes, Nomad).
- **Синхронизация с CMDB**: Автоматическое получение данных из корпоративных систем учета (NetBox, iTop).

### Способы реализации

1. **Плагины инвентаря (Inventory plugins)**: Предпочтительный, нативный способ. Ansible предоставляет плагины для большинства облаков и сервисов (например, `yandex.cloud.yandex_cloud`, `amazon.aws.aws_ec2`, `vmware.vmware.vms_inventory`, `kubernetes.core.k8s`, `google.cloud.gcp_compute`, `azure.azcollection.azure_rm`). Конфигурируются через YAML-файлы.
2. **Исполняемые скрипты**: Любой исполняемый файл (на Python, Bash и др.), который при запуске с флагом `--list` возвращает **JSON** в специальном формате. Этот способ считается legacy и уступает место плагинам, но все еще используется для специфических самописных систем.
3. **Комбинированный подход (Directory Inventory)**: Директория `inventories/` может содержать несколько источников (статические файлы `hosts.ini` и динамические конфигурации `.yml`), которые Ansible объединяет в один логический инвентарь.

### Производительность и кэширование

Обращения к внешним API могут значительно замедлять генерацию инвентаря, особенно в крупных инфраструктурах. Для решения этой проблемы рекомендуется:

- **Включать кэширование** на уровне инвентарного плагина или глобально в `ansible.cfg`.
- **Использовать фильтры** в конфигурации плагина, чтобы ограничивать область поиска на стороне API (например, только `running` инстансы).
- **Использовать `compose`** для формирования хостовых переменных (**hostvars**) только из необходимых данных.
- **«Прогревать» кэш** в пайплайнах **CI/CD**, запуская `ansible-inventory` перед основным плейбуком.

**Пример настройки кэширования в `ansible.cfg`:**

```ini
[inventory]
# Включение нужных плагинов (порядок имеет значение)
enable_plugins = amazon.aws.aws_ec2, yandex.cloud.yandex_cloud, vmware.vmware.vms_inventory, google.cloud.gcp_compute, yaml, ini, script
cache = True
cache_plugin = jsonfile
cache_timeout = 3600
cache_connection = ~/.ansible/cache/inventory
```

**Кэширование на уровне плагина:**

```yaml
# demo.aws_ec2.yml
plugin: amazon.aws.aws_ec2
regions:
  - us-east-1
cache: true
cache_plugin: ansible.builtin.jsonfile
cache_timeout: 7200
cache_connection: /tmp/aws_inventory
cache_prefix: aws_ec2
```

---

## Механизмы keyed_groups, compose, groups и hostnames

Это мощные инструменты плагинов для динамического формирования структуры инвентаря:

### hostnames

Определяет имя хоста в инвентаре (inventory_hostname). Принимает список шаблонов — Ansible использует первый успешный результат.

```yaml
hostnames:
  - "{{ labels.role }}-{{ name }}"        # Yandex Cloud: "web-myvm"
  - public_ip_address                      # AWS: публичный IP
  - private_ip_address                     # AWS: приватный IP
  - config.name + "_" + config.uuid       # VMware
  - "public_ip", "private_ip", "name"     # GCP: приоритет
```

### keyed_groups

Создает группы на основе значений атрибутов хоста. Каждый элемент списка определяет одну группу.

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **key** | Jinja2-выражение для получения значения | `tags.Role`, `labels.env` |
| **prefix** | Префикс имени группы | `role`, `env` |
| **separator** | Разделитель между префиксом и значением | `_`, `` (пустая строка) |
| **parent_group** | Родительская группа | `webservers` |
| **default_value** | Значение по умолчанию, если key = None | `unknown` |
| **trailing_separator** | Добавлять ли разделитель после значения | `true`/`false` |
| **leading_separator** | Добавлять ли разделитель перед префиксом | `true`/`false` |

```yaml
keyed_groups:
  # По тегу Role: группа "role_webserver"
  - key: tags.Role
    prefix: role

  # По Availability Zone: группа "az_eu-central-1"
  - key: placement.availability_zone
    prefix: az

  # По статусу питания: группа "power_on" / "power_off"
  - key: summary.runtime.powerState
    prefix: power
    separator: "_"

  # По labels Kubernetes: группа "label_app_nginx"
  - key: metadata.labels
    prefix: label

  # С parent_group: все подгруппы внутри "production"
  - key: labels.env
    prefix: env
    parent_group: production

  # С default_value: если labels.role не задан, используется "unknown"
  - key: labels.role
    prefix: role
    default_value: "unknown"
```

### compose

Создает или переопределяет переменные хоста через Jinja2-выражения. Часто используется для установки `ansible_host` из конкретного IP-адреса.

```yaml
compose:
  # Использовать публичный IP, если нет приватного
  ansible_host: public_ip_address | default(private_ip_address)

  # VMware: IP для подключения
  ansible_host: guest.ipAddress

  # GCP: NAT IP из networkInterfaces
  ansible_host: networkInterfaces[0].accessConfigs[0].natIP

  # NetBox: первичный IP без CIDR-маски
  ansible_host: primary_ip4.address | regex_replace('/.*$', '')

  # Произвольные переменные
  is_production: "'prod' in (labels | default({}))"
  cpu_count: config.hardware.numCPU
```

### groups

Добавляет хосты в группы на основе Jinja2-условий (boolean). В отличие от `keyed_groups`, здесь можно задать сложные условия.

```yaml
groups:
  # Если тег Environment содержит "devel"
  development: "'devel' in (tags | list)"

  # Если нет публичного IP
  private_only: "public_ip_address is not defined"

  # Если статус = Active И платформа = Linux
  active_linux: "status == 'Active' and platform.name == 'Linux'"

  # Если имя хоста начинается с "web"
  webservers: "inventory_hostname.startswith('web')"
```

### Полный пример: комбинация всех механизмов

```yaml
# aws_ec2_full.yml
plugin: amazon.aws.aws_ec2
regions:
  - eu-central-1
  - us-east-1

hostnames:
  - "tag:Name"
  - private-ip-address

keyed_groups:
  - key: tags.Role
    prefix: role
  - key: tags.Environment
    prefix: env
  - key: placement.availability_zone
    prefix: az
  - key: instance_type
    prefix: type

groups:
  webservers: "'web' in (tags.Role | default(''))"
  databases: "'db' in (tags.Role | default(''))"
  production: "tags.Environment == 'production'"

compose:
  ansible_host: private_ip_address
  ansible_user: "'ubuntu' if tags.Role == 'web' else 'admin'"
```

---

## Практические сценарии

### Сравнение статического и динамического подходов

| Критерий | Статический инвентарь | Динамический инвентарь |
| :--- | :--- | :--- |
| **Актуальность** | Требует ручного обновления | Вытягивается из источника правды |
| **Масштабируемость** | Ограничена размером файла | Горизонтально масштабируется |
| **Человеческий фактор**| Высокий риск ошибок | Снижается за счет автоматизации |
| **Группировка** | Ручные группы | Автоматически, по тегам/фильтрам |
| **Производительность**| Быстро локально | Требует кэширования для API |
| **Зависимости** | Нет | Требует коллекции, Python-пакетов |
| **Отладка** | Просмотр файла | `ansible-inventory --graph/--list` |

### Инвентарь на основе состояния Terraform

Распространенным паттерном является использование данных Terraform как источника правды.

#### 1. Использование плагинов для Terraform State (Современный метод)
Использование специализированных плагинов (например, из коллекции `cloud.terraform`), которые читают файл состояния (`terraform.tfstate`) напрямую.

```yaml
plugin: cloud.terraform.terraform_provider
project_path: /path/to/terraform/project
# Плагин автоматически найдет ресурсы и создаст хосты на основе state-файла
```

#### 2. Генерация через `terraform output` (Универсальный метод)

Подход с ручной генерацией на основе вывода `terraform output`, полезен при отсутствии подходящего плагина:

1. Terraform описывает данные (**IP-адреса**, имена хостов) в блоках `output`.

    ```hcl
    output "instance_ips" {
      value = {
        for vm in yandex_compute_instance.my_vms:
        vm.name => vm.network_interface.0.nat_ip_address
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

### Настройка динамического инвентаря AWS (EC2)

Для работы с AWS используется плагин `aws_ec2` из коллекции `amazon.aws`. Файл инвентаря должен заканчиваться на `aws_ec2.yml` или `aws_ec2.yaml`.

```yaml
plugin: amazon.aws.aws_ec2
regions:
  - eu-central-1
  - us-east-1
# Использование профиля AWS CLI для авторизации
profile: production_admin
# Фильтрация только запущенных инстансов с определенным тегом
filters:
  instance-state-name: running
  "tag:Environment": production
# Группировка хостов по тегам и зонам доступности
keyed_groups:
  - key: tags.Role
    prefix: role
  - key: placement.availability_zone
    prefix: az
# Динамическое определение IP для подключения
compose:
  ansible_host: public_ip_address | default(private_ip_address)
```

**Продвинутый пример с группами и фильтрами:**

```yaml
# aws_ec2_advanced.yml
plugin: amazon.aws.aws_ec2
regions:
  - eu-central-1
  - us-west-2

# Авторизация через IAM-роль (рекомендуется для EC2)
# Или через профиль:
# profile: production

# Фильтрация на стороне API (серверная)
filters:
  instance-state-name: running
  "tag:Team": platform
  instance-type: ["t3.medium", "t3.large", "t3.xlarge"]

# Приоритет именования хостов
hostnames:
  - "tag:Name"
  - private-ip-address

# Группировка
keyed_groups:
  - key: tags.Role
    prefix: role
    separator: "_"
  - key: tags.Environment
    prefix: env
  - key: placement.availability_zone
    prefix: az
  - key: instance_type
    prefix: type

# Сложные группы
groups:
  webservers: "'web' in (tags.Role | default(''))"
  databases: "'db' in (tags.Role | default(''))"
  production: "tags.Environment == 'production'"
  large_instances: "instance_type in ['t3.xlarge', 'm5.large']"

compose:
  ansible_host: private_ip_address
  ansible_user: "'ec2-user' if tags.OS == 'amazon' else 'ubuntu'"
  instance_id: instance_id
```

**Авторизация в AWS:**

```bash
# 1. Профиль AWS CLI (~/.aws/credentials)
export AWS_PROFILE=production

# 2. Переменные окружения
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=eu-central-1

# 3. IAM-роль (на EC2-инстансах — самый безопасный способ)
# Роль привязывается к инстансу, ключи не нужны

# 4. Assume Role (для мультиаккаунтов)
export AWS_PROFILE=assume-role
# В ~/.aws/config:
# [profile assume-role]
# role_arn = arn:aws:iam::123456789012:role/CrossAccountRole
# source_profile = production
```

### Настройка динамического инвентаря Yandex Cloud

Необходимо установить коллекцию: `ansible-galaxy collection install yandex.cloud`. Файл инвентаря с расширением `.yc.yml`.

```yaml
plugin: yandex.cloud.yandex_cloud
folder_id: "b1g..." # ID каталога в Yandex Cloud
service_account_key_file: "./key.json" # Путь к JSON-ключу сервисного аккаунта
# Настройка имен хостов в инвентаре
hostnames:
  - "{{ labels.role }}-{{ name }}"
# Группировка хостов по метке 'role'
keyed_groups:
  - key: labels.role
    prefix: role
# Настройка IP-адреса для подключения
compose:
  ansible_host: network_interfaces[0].primary_v4_address.one_to_one_nat.address
```

**Сервисный аккаунт (IAM):**

```bash
# Создание сервисного аккаунта
yc iam service-account create --name ansible-inventory

# Назначение роли (Viewer для чтения,compute.admin для управления)
yc resource-manager folder add-access-binding <folder_id> \
  --role viewer \
  --subject service-account:<sa_id>

# Создание ключа
yc iam service-account key create --service-account-id <sa_id> \
  --output key.json --format authorized_key
```

### Настройка динамического инвентаря Google Cloud (GCP)

Плагин `gcp_compute` из коллекции `google.cloud`. Файл с расширением `gcp_compute.yml` или `gcp.yml`.

```yaml
# gcp_compute.yml
plugin: google.cloud.gcp_compute
zones:
  - europe-west1-b
  - europe-west1-c
projects:
  - my-gcp-project-id
filters:
  - status = RUNNING
  - scheduling.automaticRestart = true AND status = RUNNING
service_account_file: /path/to/service_account.json
auth_kind: serviceaccount
scopes:
  - 'https://www.googleapis.com/auth/compute'
  - 'https://www.googleapis.com/auth/compute.readonly'
hostnames:
  - name
  - public_ip
  - private_ip
keyed_groups:
  - key: labels
    prefix: label
  - key: zone
    prefix: zone
compose:
  ansible_host: networkInterfaces[0].accessConfigs[0].natIP
```

**Сервисный аккаунт GCP:**

```bash
# Создание сервисного аккаунта
gcloud iam service-accounts create ansible-inventory \
  --display-name="Ansible Dynamic Inventory"

# Назначение роли
gcloud projects add-iam-policy-binding my-project \
  --member="serviceAccount:ansible-inventory@my-project.iam.gserviceaccount.com" \
  --role="roles/compute.viewer"

# Экспорт ключа
gcloud iam service-accounts keys create key.json \
  --iam-account=ansible-inventory@my-project.iam.gserviceaccount.com
```

### Настройка динамического инвентаря Azure

Плагин `azure_rm` из коллекции `azure.azcollection`. Файл с расширением `azure_rm.yml`.

```yaml
# azure_rm.yml
plugin: azure.azcollection.azure_rm

# Авторизация через Service Principal
subscription_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
client_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
secret: "{{ lookup('env', 'AZURE_CLIENT_SECRET') }}"
tenant: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Фильтрация
resource_groups:
  - production-rg
  - staging-rg
tags:
  Environment: production

# Группировка
keyed_groups:
  - key: tags.Role
    prefix: role
  - key: location
    prefix: location
  - key: resource_group
    prefix: rg
  - key: properties.hardwareProfile.vmSize
    prefix: vm_size

# Именование хостов
hostnames:
  - name
  - public_ip

compose:
  ansible_host: public_ip_address | default(private_ip_address)
```

**Авторизация в Azure:**

```bash
# 1. Service Principal
export AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export AZURE_CLIENT_SECRET=your_secret
export AZURE_TENANT=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export AZURE_SUBSCRIPTION_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# 2. Managed Identity (на Azure VM)
# Не требует ключей — Managed Identity предоставляет токен автоматически

# 3. Azure CLI (для разработки)
az login
```

### Настройка динамического инвентаря VMware vSphere

Плагин `vmware.vmware.vms_inventory` из коллекции `vmware.vmware` (новый, рекомендуемый). Файл с расширением `vmware.yml`.

```yaml
# vmware_inventory.yml
plugin: vmware.vmware.vms_inventory

hostname: vcenter.example.com
username: administrator@vsphere.local
password: "{{ lookup('env', 'VMWARE_PASSWORD') }}"
validate_certs: false

# Фильтрация VM
resources:
  - resource_type: VirtualMachine
    properties:
      - name
      - config.hardware.numCPU
      - config.hardware.memoryMB
      - guest.ipAddress
      - summary.runtime.powerState
      - config.guestId
    filters:
      - name: '{{ config.name }}'
        value: '{{ "web-" in config.name }}'

# Группировка
keyed_groups:
  - key: summary.runtime.powerState
    prefix: power
  - key: config.guestId
    prefix: guest
  - key: config.hardware.numCPU
    prefix: cpu

# Именование хостов
hostnames:
  - config.name

compose:
  ansible_host: guest.ipAddress
  ansible_user: "'administrator' if 'windows' in config.guestId else 'root'"
```

**Авторизация в VMware:**

```bash
# Переменные окружения (рекомендуется)
export VMWARE_HOST=vcenter.example.com
export VMWARE_USERNAME=administrator@vsphere.local
export VMWARE_PASSWORD=your_password
export VMWARE_VALIDATE_CERTS=false
```

### Настройка динамического инвентаря OpenStack

Плагин `openstack.cloud.openstack` из коллекции `openstack.cloud`. Файл с расширением `openstack.yml` или `clouds.yml`.

```yaml
# openstack_inventory.yml
plugin: openstack.cloud.openstack

clouds:
  - mycloud

# Фильтрация
filters:
  status: "ACTIVE"
  "OS-EXT-STS:vm_state": "active"

# Группировка
keyed_groups:
  - key: metadata.role
    prefix: role
  - key: availability_zone
    prefix: az
  - key: "OS-EXT-AZ:availability_zone"
    prefix: zone

# Группы на основе условий
groups:
  webservers: "'web' in (metadata.role | default(''))"
  databases: "'db' in (metadata.role | default(''))"

compose:
  ansible_host: public_v4_address | default(private_v4_address)
```

**Файл `clouds.yaml`:**

```yaml
clouds:
  mycloud:
    auth:
      auth_url: https://cloud.example.com:5000/v3
      username: ansible
      password: your_password
      project_name: myproject
      project_domain_name: Default
      user_domain_name: Default
    region_name: RegionOne
```

### Интеграция с CMDB (NetBox)

NetBox часто выступает единым источником правды (SSoT) для всей инфраструктуры. Плагин `nb_inventory` из коллекции `netbox.netbox`.

См. также: [Автоматизация заполнения NetBox через API](../Networking/NetBox/netbox-automation-python.md).

```yaml
plugin: netbox.netbox.nb_inventory
api_endpoint: https://netbox.example.com
token: "YOUR_NETBOX_API_TOKEN" # Рекомендуется через env: {{ lookup('env', 'NETBOX_TOKEN') }}
validate_certs: true
# Фильтрация по статусу устройства
status:
  - Active
# Группировка устройств по ролям, сайтам и платформам
group_by:
  - device_roles
  - sites
  - platforms
# Формирование ansible_host из первичного IP-адреса в NetBox
compose:
  ansible_host: primary_ip4.address | regex_replace('/.*$', '')
```

### Интеграция с Service Discovery (Consul)

Использование Consul как источника инвентаря идеально подходит для динамических сред вне Kubernetes (например, классические ВМ с установленным Consul Agent). Плагин `consul` из коллекции `community.general` позволяет автоматически получать список хостов на основе зарегистрированных сервисов и их тегов.

```yaml
plugin: community.general.consul
consul_url: http://consul.example.com:8500
# Авторизация (рекомендуется использовать ACL токены)
token: "{{ lookup('env', 'CONSUL_HTTP_TOKEN') }}"

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
```

**Особенности:**
- **Health-aware**: Можно исключать хосты, которые помечены как `critical` или `warning` в Consul.
- **Гибкость**: Позволяет использовать метаданные сервисов (`ServiceMeta`) для формирования переменных Ansible.

### Интеграция с KV-хранилищами (Etcd)

Etcd (версии 3) может использоваться как низкоуровневое хранилище данных об инвентаре. Это полезно для кастомных систем оркестрации, где список хостов и их параметры хранятся в виде иерархии ключей. Используется плагин `etcd3` из коллекции `community.general`.

```yaml
plugin: community.general.etcd3
host: "etcd-cluster.example.com"
port: 2379
user: "ansible"
password: "password"

# Префикс ключей, под которыми хранится инвентарь
key_prefix: "/ansible/inventory/hosts/"

# Использование сертификатов (рекомендуется)
cert_file: "/path/to/cert.pem"
key_file: "/path/to/key.pem"
ca_cert: "/path/to/ca.pem"
```

**Особенности:**
- **Структура ключей**: Плагин ожидает, что данные в etcd хранятся в формате JSON или YAML.
- **Производительность**: Хорошо подходит для очень больших, но стабильных списков хостов, где Consul может быть избыточен.

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
    api_url = os.environ.get("INVENTORY_API_URL", "https://api.example.com/hosts")
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
    api_url = os.environ.get("INVENTORY_API_URL", "https://api.example.com/hosts")
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
│   ├── aws_ec2.yml                # Динамический: AWS
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
    ├── netbox.yml                 # CMDB-инвентарь
    ├── consul.yml                 # Service Discovery
    └── vmware.yml                 # vSphere
```

```bash
# Использование Directory Inventory
ansible-playbook site.yml -i inventories/production/

# Или несколько источников (с сохранением порядка)
ansible-playbook site.yml -i inventories/production/hosts.yml -i inventories/production/aws_ec2.yml
```

**Важно:** Порядок файлов определяется алфавитом. Если вам нужен определённый порядок обработки, используйте несколько `-i` или группируйте файлы с префиксами (например, `01_hosts.yml`, `02_aws.yml`).

---

## Безопасность и управление секретами

### Токены и ключи доступа

Конфигурации динамического инвентаря содержат токены и ключи доступа. **Никогда не коммитьте их в Git в открытом виде.**

1. **Переменные окружения**: Плагины по умолчанию поддерживают переменные типа `AWS_ACCESS_KEY_ID`, `YC_TOKEN`, `GCP_SERVICE_ACCOUNT_FILE`, `VMWARE_PASSWORD`, `AZURE_CLIENT_SECRET`. Это наиболее безопасный способ для CI/CD.

    ```bash
    # AWS
    export AWS_ACCESS_KEY_ID=AKIA...
    export AWS_SECRET_ACCESS_KEY=...

    # Yandex Cloud
    export YC_TOKEN=$(yc iam create-token)

    # GCP
    export GCP_SERVICE_ACCOUNT_FILE=/path/to/key.json

    # VMware
    export VMWARE_PASSWORD=your_password

    # Azure
    export AZURE_CLIENT_SECRET=your_secret
    ```

2. **Ansible Vault**: Если ключи хранятся в `.yml` файле инвентаря, его необходимо зашифровать:
   ```bash
   ansible-vault encrypt inventories/prod.aws_ec2.yml
   ansible-playbook site.yml -i inventories/prod.aws_ec2.yml --ask-vault-pass
   ```

3. **Сторонние хранилища секретов**: Интеграция с HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager:
   ```yaml
   # Чтение токена из HashiCorp Vault
   token: "{{ lookup('hashi_vault', 'secret=secret/ansible/aws:token') }}"
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
ansible-vault encrypt inventories/production/aws_ec2.yml

# Редактирование
ansible-vault edit inventories/production/aws_ec2.yml

# Дешифрование (для проверки)
ansible-vault view inventories/production/aws_ec2.yml

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

# 2. Вывести полный JSON-объект со всеми хост-переменными (проверка hostvars)
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
# Проверка AWS инвентаря
ansible-inventory -i aws_ec2.yml --graph
ansible-inventory -i aws_ec2.yml --list | jq '.all.children'

# Проверка Yandex Cloud
ansible-inventory -i yandex_cloud.yml --graph

# Проверка NetBox
ansible-inventory -i netbox.yml --graph
ansible-inventory -i netbox.yml --host webserver-01

# Проверка Kubernetes
ansible-inventory -i k8s.yml --graph
ansible-inventory -i k8s.yml --list | jq '._meta.hostvars'

# Проверка VMware
ansible-inventory -i vmware.yml --graph
ansible-inventory -i vmware.yml --list | jq '.all.children'
```

### Устранение типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `No module named 'boto3'` | Нет Python-пакета для AWS | `pip install boto3 botocore` |
| `No module named 'google.auth'` | Нет Python-пакета для GCP | `pip install google-auth requests` |
| `No module named 'azure'` | Нет Python-пакета для Azure | `pip install azure-identity azure-mgmt-compute` |
| `Authentication failed` | Неверныеcredentials | Проверьте переменные окружения, профили |
| `Unable to parse inventory` | Синтаксическая ошибка в YAML/INI | Проверьте формат файла, используйте `yaml` линтер |
| `Plugin not found` | Коллекция не установлена | `ansible-galaxy collection install <collection>` |
| `KeyError: 'ansible_host'` | Не задан `compose: ansible_host` | Добавьте `compose: ansible_host: <ip_expression>` |
| `Cache is stale` | Устаревший кэш инвентаря | `ansible-inventory -i file.yml --list --flush-cache` |
| `Permission denied` | Нет прав на чтение ключа | Проверьте права доступа к файлу ключа |
| `Connection timeout` | API недоступен | Проверьте сеть, firewall, endpoint URL |

### Валидация конфигурации плагина

```bash
# Проверка синтаксиса YAML
python3 -c "import yaml; yaml.safe_load(open('aws_ec2.yml'))"

# Проверка плагина через ansible-doc
ansible-doc -t inventory amazon.aws.aws_ec2

# Проверка доступных опций плагина
ansible-doc -t inventory -s amazon.aws.aws_ec2
```

---

## Интеграция с CI/CD

### GitHub Actions

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
          ansible-galaxy collection install amazon.aws yandex.cloud

      - name: Validate inventory
        run: |
          ansible-inventory -i inventories/production/ --graph
          ansible-inventory -i inventories/production/ --list | python3 -m json.tool > /dev/null
```

### GitLab CI

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
    - ansible-galaxy collection install amazon.aws
  script:
    - ansible-inventory -i inventories/production/aws_ec2.yml --graph
    - ansible-inventory -i inventories/production/aws_ec2.yml --list > /dev/null
  only:
    - changes:
        - inventories/**/*

deploy:
  stage: deploy
  script:
    - ansible-playbook playbooks/site.yml -i inventories/production/
  only:
    - main
```

---

## Сценарий: CMDB/NetBox как Dynamic Inventory (полный цикл)

### Архитектура: CMDB → Dynamic Inventory → Ansible → CMDB обратная связь

```
┌─────────────┐     Pull      ┌─────────────────┐     Apply     ┌─────────────────┐
│   NetBox    │◄──────────────│  Ansible        │──────────────►│  Managed Hosts  │
│  (SSoT)     │  Inventory    │  Control Node   │  Playbooks    │  (500+ servers) │
└──────┬──────┘               └─────────────────┘               └─────────────────┘
       │                             │
       │  Push facts back            │  Update CMDB
       └─────────────────────────────┘
```

### NetBox Dynamic Inventory Plugin

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
  - key: device_role.name
    prefix: role
    separator: "_"
  - key: site.name
    prefix: site
    separator: "_"
  - key: platform.name
    prefix: platform
    separator: "_"
  - key: status
    prefix: status

# Хостовые переменные
compose:
  ansible_host: primary_ip4.address | regex_replace('/.*$', '')
  ansible_network_os: platform.name | default('linux')
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

### NetBox как SSoT: полный цикл обратной связи

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

### Автоматическая синхронизация через Scheduled Job

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

---

## Лучшие практики

1. **Храните конфигурации плагинов в Git** —-versioning обеспечивает воспроизводимость.
2. **Используйте переменные окружения** для токенов — не храните их в файлах.
3. **Включайте кэширование** — особенно в CI/CD, чтобы не нагружать API.
4. **Фильтруйте на стороне API** — ограничивайте область поиска (только нужные регионы/проекты/теги).
5. **Используйте `keyed_groups`** для автоматической группировки — вместо ручного создания групп.
6. **Используйте `compose`** для `ansible_host` — плагин не всегда может определить IP автоматически.
7. **Проверяйте инвентарь перед запуском** — `ansible-inventory --graph` перед `ansible-playbook`.
8. **Шифруйте файлы с секретами** — `ansible-vault encrypt` для любых токенов/паролей.
9. **Комбинируйте источники** — Directory Inventory для мультиоблака и мультиаккаунта.
10. **Настройте `no_log`** для скриптов, работающих с секретами.

---

## Дополнительная информация

- [Установка и настройка Ansible](ansible_setup_and_config.md) — базовые концепции инвентаря.
- [Официальная документация по плагинам инвентаря](https://docs.ansible.com/ansible/latest/plugins/inventory.html)
- [Официальная документация: Amazon AWS EC2](https://docs.ansible.com/ansible/latest/collections/amazon/aws/aws_ec2_inventory.html)
- [Официальная документация: Yandex Cloud](https://docs.ansible.com/ansible/latest/collections/yandex/cloud/yandex_cloud_inventory.html)
- [Официальная документация: Google Cloud GCP](https://docs.ansible.com/ansible/latest/collections/google/cloud/gcp_compute_inventory.html)
- [Официальная документация: VMware vSphere](https://docs.ansible.com/ansible/latest/collections/vmware/vmware/vms_inventory_inventory.html)
- [Официальная документация: Azure](https://docs.ansible.com/ansible/latest/collections/azure/azcollection/azure_rm_inventory.html)
- [Официальная документация: NetBox](https://docs.ansible.com/ansible/latest/collections/netbox/netbox/nb_inventory_inventory.html)
- [Официальная документация: Kubernetes](https://docs.ansible.com/ansible/latest/collections/kubernetes/core/k8s_inventory.html)
- [Структура проекта](examples/example_project_layout.md) — организация файлов и каталогов.
- [Ansible Vault: Лучшие практики](Vault/best_practices.md) — шифрование конфигураций инвентаря.
- [Оптимизация производительности](ansible_performance_tuning.md) — тюнинг SSH и кэширования.
- [Динамический инвентарь для сетевого оборудования](ansible_network_automation.md) — NetBox + Network Automation.
- [Автоматизация Kubernetes](./ansible-kubernetes-automation.md) — инвентарь подов и сервисов.
