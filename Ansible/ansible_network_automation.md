# Ansible — автоматизация сетевого оборудования

## Определения

**Сетевой модуль (Network Module)** — специализированный модуль Ansible для управления сетевыми устройствами (коммутаторами, маршрутизаторами, FW). Выполняется всегда на **узле управления (Control Node)** через API или CLI, так как на сетевом оборудовании обычно отсутствует среда выполнения Python.

**Сетевая ОС (Network OS)** — операционная система сетевого устройства (Cisco IOS, Juniper JunOS, Arista EOS). В Ansible указывается через переменную `ansible_network_os`.

**Ресурсный модуль (Resource Module)** — современный тип модулей для управления конкретными компонентами сети (интерфейсы, VLAN, L3). Имеют общую структуру данных и единую логику состояний (`state`) для разных вендоров.

**Идемпотентность в сетях** — способность модуля приводить устройство к целевому состоянию без повторного выполнения команд, если конфигурация уже соответствует описанной. Для сетевых модулей это реализуется через сравнение текущего `running-config` с желаемым состоянием.

**SSoT (Single Source of Truth) в сетях** — внешний источник (NetBox, Nautobot, Git), содержащий эталонное состояние инфраструктуры. Автоматизация должна брать данные из SSoT, а не с самих устройств.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля в формате `vendor.collection.module`. Пример: `cisco.ios.ios_vlans`.

**NETCONF (RFC 6241)** — XML-based протокол управления сетевыми устройствами, заменяющий CLI для конфигурирования. Поддерживает транзакционность (commit/rollback) и валидацию конфигурации перед применением.

**eAPI (Arista)** — REST API в Arista EOS, позволяющий отправлять команды в JSON-формате. Более надежен, чем CLI-парсинг, и обеспечивает структурированный возврат данных.

**NX-API (Cisco)** — REST API в Cisco NX-OS (数据中心 коммутаторы). Поддерживает как CLI-команды, так и XML/JSON ответы.

**HTTP API (httpapi)** — плагин Ansible, реализующий взаимодействие через REST/HTTP API вместо SSH. Используется для Arista eAPI, Cisco NX-API, FortiOS, и других платформ с REST API.

## Основные концепции

### Предварительные требования

Для автоматизации сетевого оборудования необходимы:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | Ядро Ansible (рекомендуется 2.17+) |
| **Python** | 3.8+ | Совместимость с ansible-core |
| **cisco.ios** | latest | Коллекция модулей Cisco IOS |
| **junipernetworks.junos** | latest | Коллекция модулей Juniper JunOS |
| **arista.eos** | latest | Коллекция модулей Arista EOS |
| **ansible.netcommon** | latest | Общие сетевые модули (network_cli, netconf, httpapi) |
| **ansible.utils** | latest | Утилиты (валидация, парсинг, URL) |
| **Paramiko** | 2.7+ | SSH-клиент для network_cli (рекомендуется) |

**Установка коллекций:**
```bash
# Все коллекции за раз
ansible-galaxy collection install cisco.ios junipernetworks.junos arista.eos ansible.netcommon ansible.utils

# Или через requirements.yml
cat > requirements.yml << 'EOF'
collections:
  - name: cisco.ios
  - name: junipernetworks.junos
  - name: arista.eos
  - name: ansible.netcommon
  - name: ansible.utils
EOF

ansible-galaxy collection install -r requirements.yml
```

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.17.x]

ansible-galaxy collection list | grep -E "cisco|juniper|arista"
# → cisco.ios    4.x.x
# → arista.eos   4.x.x
```

### Плагины подключения и Network OS

Сетевое оборудование использует специализированные плагины для поддержания постоянных соединений:

*   `ansible.netcommon.network_cli` — основное подключение через SSH к CLI. Оптимизировано для сетевых устройств (обработка приветствий, отключение пагинации).
*   `ansible.netcommon.netconf` — работа через протокол NETCONF (XML-базированный API). Рекомендуется для Juniper и современных Cisco (IOS-XE/XR).
*   `ansible.netcommon.httpapi` — работа через REST API (Arista eAPI, Cisco NX-API, FortiOS). Самый производительный метод для современных DC.

Для работы плагина обязательно должна быть задана переменная `ansible_network_os` (например, `cisco.ios.ios`, `junipernetworks.junos.junos`).

### Параметры подключения network_cli

Плагин `network_cli` поддерживает расширенную настройку через `ansible.cfg` или переменные инвентаря:

```ini
# ansible.cfg
[persistent_connection]
connect_timeout = 30          # Таймаут подключения (сек)
command_timeout = 30          # Таймаут выполнения команды (сек)
persistent_connect_timeout = 60  # Таймаут persistent-соединения (сек)

[ssh_connection]
pipelining = true             # Включить pipelining для производительности
# ssh_args = -o ControlMaster=auto -o ControlPersist=60s
```

**Переменные инвентаря для network_cli:**
```yaml
# inventory.yml
routers:
  vars:
    ansible_connection: ansible.netcommon.network_cli
    ansible_network_os: cisco.ios.ios
    ansible_user: admin
    ansible_password: "{{ vault_enable_password }}"
    ansible_become: true
    ansible_become_method: enable
    ansible_become_password: "{{ vault_enable_password }}"
    # Параметры network_cli
    ansible_command_timeout: 30
    ansible_connect_timeout: 30
    # Persistent-соединение (переиспользует SSH-сессию)
    ansible_persistent_connect_timeout: 60
```

### Параметры подключения NETCONF

NETCONF обеспечивает транзакционность (commit/rollback) и XML-структурированные данные:

```yaml
# inventory.yml
junos_routers:
  vars:
    ansible_connection: ansible.netcommon.netconf
    ansible_network_os: junipernetworks.junos.junos
    ansible_user: admin
    ansible_password: "{{ vault_junos_password }}"
    # NETCONF-специфичные параметры
    ansible_netconf_ssh_args: "-o ControlMaster=auto"
    # Включить XML-формат ответа (по умолчанию true)
    # ansible_netconf_xml_mode: true
```

### Параметры подключения HTTP API (Arista eAPI)

Для Arista EOS используется REST API вместо SSH:

```yaml
# inventory.yml
arista_switches:
  vars:
    ansible_connection: ansible.netcommon.httpapi
    ansible_network_os: arista.eos.eos
    ansible_httpapi_host: "{{ inventory_hostname }}"
    ansible_httpapi_port: 443
    ansible_httpapi_use_ssl: true
    ansible_httpapi_validate_certs: false  # В production: true
    ansible_user: admin
    ansible_password: "{{ vault_arista_password }}"
    # Для NX-API (Cisco DC):
    # ansible_httpapi_use_ssl: true
    # ansible_httpapi_port: 443
```

### Управление привилегиями

Многие устройства требуют перехода в режим суперпользователя (Enable Mode).
*   `ansible_become: yes`
*   `ansible_become_method: enable`
*   `ansible_become_password: "{{ enable_password }}"` (хранить в [Ansible Vault](../Vault/basics.md)).

**Отличие от Linux become:** В сетевых устройствах `enable` — это повышение привилегий на CLI, а не переключение пользователя. Метод `enable` не требует `sudo` или `su`.

### Ресурсные модули и управление состоянием

Ресурсные модули позволяют декларативно описывать состояние сети. Параметр `state` определяет логику изменений:

*   `merged` — добавление/обновление настроек без удаления существующих (безопасно, режим по умолчанию).
*   `replaced` — замена настроек только для указанных объектов. Если в конфигурации интерфейса есть лишние команды, они будут удалены.
*   `overridden` — полная перезапись всех настроек ресурса. Удаляет все объекты (например, VLAN или интерфейсы), не описанные в плейбуке.
*   `deleted` — удаление указанных объектов.
*   `gathered` — сбор текущей конфигурации с устройства и её преобразование в структурированный YAML/JSON формат.
*   `parsed` — локальный парсинг текстового конфига (файла) в структурированные данные без подключения к устройству.
*   `rendered` — генерация CLI-команд на основе входных данных без отправки их на устройство (удобно для аудита).

### Мультиплатформенная абстракция

Для управления гетерогенными сетями (Cisco + Juniper + Arista) используется подход с общими переменными. Данные хранятся в вендоро-независимом формате, а модули выбираются динамически:

```yaml
- name: Настройка VLAN на разных вендорах
  include_tasks: "{{ ansible_network_os }}_vlans.yml"
```

**Пример вендоро-независимого group_vars (common.yml):**
```yaml
# group_vars/all/network.yml
---
network_servers:
  - name: dns-primary
    ip: 10.0.0.53
  - name: dns-secondary
    ip: 10.0.0.54
  - name: ntp-primary
    ip: 10.0.0.123

network_ntp_servers: "{{ network_servers | selectattr('name', 'search', 'ntp') | list }}"
network_dns_servers: "{{ network_servers | selectattr('name', 'search', 'dns') | list }}"
```

**Пример шаблона для мультиплатформенной конфигурации:**
```yaml
# group_vars/all/ntp_config.yml
---
ntp_servers:
  cisco.ios.ios:
    commands:
      - "ntp server {{ item.ip }}"
    loop: "{{ network_ntp_servers }}"
  junipernetworks.junos.junos:
    config:
      servers:
        - server: "{{ item.ip }}"
    loop: "{{ network_ntp_servers }}"
```

### Event-Driven Ansible (EDA) для сетей

Современный подход, позволяющий автоматически реагировать на события сетевой инфраструктуры (syslog, SNMP traps, Netflow). EDA сокращает время реакции на инциденты и минимизирует простои (Downtime).

**Примеры использования в сетях:**
- Автоматическая перемаршрутизация трафика при падении интерфейса.
- Мгновенный сбор диагностических данных (show commands) в момент возникновения проблемы.
- Блокировка подозрительного трафика на основе алертов от IDS/IPS.

Подробное описание архитектуры и настройки: **[Event-Driven Ansible (EDA)](./event-driven-ansible.md)**.

### Настройка инвентаря для сетевых устройств

Сетевые устройства не могут выполнять Python-код локально. Поэтому в инвентаре необходимо явно указать параметры подключения.

**Пример `inventory.yml`:**
```yaml
routers:
  hosts:
    core-rtr-01.example.com:
  vars:
    ansible_connection: ansible.netcommon.network_cli
    ansible_network_os: cisco.ios.ios
    ansible_user: admin
    # Отключение сбора фактов по умолчанию (делается модулями _facts)
    ansible_facts_gathering: no

switches:
  hosts:
    access-sw-01.example.com:
    access-sw-02.example.com:
  vars:
    ansible_connection: ansible.netcommon.network_cli
    ansible_network_os: cisco.ios.ios
    ansible_user: admin
    ansible_become: true
    ansible_become_method: enable
    ansible_become_password: "{{ vault_enable_password }}"

# Juniper-устройства в том же инвентаре
junos_routers:
  hosts:
    mx-core-01.example.com:
    srx-fw-01.example.com:
  vars:
    ansible_connection: ansible.netcommon.netconf
    ansible_network_os: junipernetworks.junos.junos
    ansible_user: admin
    ansible_become: true
    ansible_become_method: sudo
    ansible_become_password: "{{ vault_junos_sudo_password }}"
```

### Backup и откат конфигурации

Все ресурсные модули Cisco IOS поддерживают резервное копирование перед изменениями:

```yaml
- name: Backup перед изменением конфигурации
  cisco.ios.ios_config:
    backup: true
    backup_options:
      dir_path: "/backups/cisco/{{ inventory_hostname }}"
      filename: "{{ inventory_hostname }}_{{ ansible_date_time.date }}.cfg"
```

**Откат черезrollback (Juniper):**
```yaml
- name: Откат к предыдущей конфигурации
  junipernetworks.junos.junos_config:
    rollback: 1  # Откат на 1 коммит назад
```

**Откат через replace (Cisco IOS):**
```yaml
- name: Полная замена конфигурации
  cisco.ios.ios_config:
    src: configs/{{ inventory_hostname }}_baseline.cfg
    replace: config  # Полная замена running-config
```

## Практические сценарии

### 1. Управление VLAN на Cisco IOS

Использование современного ресурсного модуля обеспечивает идемпотентность и читаемость. В отличие от сырых команд, модуль сам решит, нужно ли создавать VLAN.

```yaml
- name: Настройка VLAN через ресурсный модуль
  cisco.ios.ios_vlans:
    config:
      - name: Management
        vlan_id: 10
      - name: Users
        vlan_id: 20
    state: merged
# → core-rtr-01 | CHANGED => { "commands": ["vlan 10", "name Management", "vlan 20", "name Users"] }
```

### 2. Сбор сетевых фактов

Ansible позволяет собирать факты в структурированном виде, что упрощает генерацию отчетов и анализ инфраструктуры.

```yaml
- name: Сбор фактов об интерфейсах
  cisco.ios.ios_facts:
    gather_subset: min
    gather_network_resources:
      - interfaces
      - l2_interfaces
  register: network_facts

- name: Вывод состояния интерфейса GigabitEthernet0/1
  ansible.builtin.debug:
    msg: "Статус: {{ ansible_facts.net_interfaces['GigabitEthernet0/1'].operstatus }}"
# → core-rtr-01 | SUCCESS => { "msg": "Статус: up" }
```

**Сбор фактов для мониторинга ( расширенный):**
```yaml
- name: Сбор всех доступных фактов
  cisco.ios.ios_facts:
    gather_subset:
      - config    # Текущая конфигурация
      - hardware  # Версия ПО, серийный номер
      - interfaces  # Статус интерфейсов
      - lag       # LAG/Port-Channel
      - vlans     # VLAN-данные
    gather_network_resources:
      - l3_interfaces
      - l2_interfaces
      - vlans
      - acl_interfaces
      - bgp_global
      - ospf_interfaces
  register: all_facts

- name: Сохранение фактов в файл
  ansible.builtin.copy:
    content: "{{ all_facts.ansible_facts | to_nice_yaml }}"
    dest: "./facts/{{ inventory_hostname }}.yml"
```

### 3. Отключение постраничного вывода (Pagination)

При использовании низкоуровневых модулей (`ios_command`) для парсинга вывода, пагинация (паузы "More") может "подвесить" сессию. Плагин `network_cli` обычно отключает её автоматически, но для специфического оборудования или старых ОС может потребоваться ручной вызов:

```yaml
- name: Выполнение команды без пагинации
  cisco.ios.ios_command:
    commands:
      - terminal length 0
      - show running-config
  register: run_conf
# → Результат будет сохранен в run_conf.stdout_lines
```

### 4. Настройка интерфейсов на Juniper Junos

Ресурсные модули для Juniper работают по той же логике, что и для Cisco, обеспечивая единообразие кода.

```yaml
- name: Настройка L3 интерфейсов Juniper
  junipernetworks.junos.junos_l3_interfaces:
    config:
      - name: ge-0/0/0
        ipv4:
          - address: 192.168.1.1/24
    state: merged
```

### 5. Управление BGP на Arista EOS

Arista eAPI позволяет эффективно управлять сложными протоколами маршрутизации.

```yaml
- name: Настройка BGP Global на Arista
  arista.eos.eos_bgp_global:
    config:
      as_number: 65001
      router_id: 1.1.1.1
      neighbors:
        - address: 10.0.0.2
          remote_as: 65002
    state: merged
```

### 6. Сбор сетевых фактов и инвентаризация (Discovery)

Использование `state: gathered` позволяет быстро импортировать конфигурацию из существующей сети ("brownfield") в Git или NetBox.

```yaml
- name: Сбор текущей конфигурации интерфейсов
  cisco.ios.ios_interfaces:
    state: gathered
  register: current_interfaces

- name: Сохранение фактов в файл для анализа
  ansible.builtin.copy:
    content: "{{ current_interfaces.gathered | to_nice_yaml }}"
    dest: "./discovered/{{ inventory_hostname }}_interfaces.yml"
```

### 7. Валидация данных (Data Validation)

Перед применением конфигурации на продакшен-устройствах необходимо проверить данные из SSoT на соответствие схеме.

```yaml
- name: Проверка структуры данных VLAN
  ansible.utils.validate:
    data: "{{ network_data }}"
    criteria:
      - "{{ lookup('file', 'vlan_schema.json') }}"
    engine: ansible.utils.jsonschema
```

### 8. Настройка OSPF на Cisco IOS

```yaml
---
- name: Настройка OSPF на Cisco IOS
  hosts: cisco_routers
  gather_facts: false
  vars:
    ospf_process_id: 1
    ospf_router_id: "{{ loopback0_ip }}"
    ospf_networks:
      - network: 10.0.0.0
        wildcard: 0.0.255.255
        area: 0
      - network: 192.168.0.0
        wildcard: 0.0.255.255
        area: 1

  tasks:
    - name: Настройка Loopback интерфейса
      cisco.ios.ios_l3_interfaces:
        config:
          - name: Loopback0
            ipv4:
              - address: "{{ ospf_router_id }}/32"
        state: merged

    - name: Настройка OSPF через ресурсный модуль
      cisco.ios.ios_ospf_interfaces:
        config:
          - name: Loopback0
            process:
              id: "{{ ospf_process_id }}"
                area_id: 0
        state: merged

    - name: Настройка OSPF network statements
      cisco.ios.ios_config:
        lines:
          - "router ospf {{ ospf_process_id }}"
          - "router-id {{ ospf_router_id }}"
          - "network {{ item.network }} {{ item.wildcard }} area {{ item.area }}"
        # Не идемпотентно — используется как fallback для старых IOS
      loop: "{{ ospf_networks }}"
      when: ansible_facts.version_major is version('15', '<')

    - name: Верификация OSPF
      cisco.ios.ios_command:
        commands:
          - show ip ospf neighbor
          - show ip ospf interface brief
      register: ospf_verify

    - name: Проверка邻居ских связей OSPF
      ansible.builtin.assert:
        that:
          - "'FULL' in ospf_verify.stdout[0]"
        fail_msg: "OSPF-соседи не в состоянии FULL"
        success_msg: "OSPF-соседи корректно установлены"
```

### 9. Настройка ACL на Cisco IOS

```yaml
---
- name: Управление ACL на Cisco IOS
  hosts: cisco_switches
  gather_facts: false
  vars:
    acl_rules:
      - name: RESTRICT_SSH
        aces:
          - sequence: 10
            grant: permit
            protocol_options:
              tcp:
                syn: true
            source:
              host: 10.0.0.0/8
            destination:
              host: "{{ ansible_host }}"
              port_protocol:
                eq: 22
          - sequence: 20
            grant: deny
            protocol_options:
              tcp:
                syn: true
            source:
              any: true
            destination:
              host: "{{ ansible_host }}"
              port_protocol:
                eq: 22
          - sequence: 1000
            grant: permit
            protocol_options:
              ip:
                - fragments: true
            source:
              any: true
            destination:
              any: true

  tasks:
    - name: Применение ACL
      cisco.ios.ios_acls:
        config:
          - afi: ipv4
            acls:
              - name: "{{ item.name }}"
                aces: "{{ item.aces }}"
        state: merged
      loop: "{{ acl_rules }}"

    - name: Проверка примененных ACL
      cisco.ios.ios_command:
        commands:
          - show access-lists
      register: acl_verify

    - name: Верификация ACL
      ansible.builtin.debug:
        msg: "Примененные ACL: {{ acl_verify.stdout[0] }}"
```

### 10. Конфигурация интерфейсов (Cisco IOS)

```yaml
---
- name: Настройка интерфейсов Cisco IOS
  hosts: cisco_switches
  gather_facts: false
  vars:
    interfaces_config:
      - name: GigabitEthernet0/1
        description: "Uplink to Core Switch"
        mode: trunk
        trunk:
          allowed_vlans: "10,20,30"
          native_vlan: 999
        enabled: true
      - name: GigabitEthernet0/2
        description: "Access Port - VLAN 10"
        mode: access
        access:
          vlan: 10
        enabled: true
      - name: GigabitEthernet0/3
        description: "Unused - Shutdown"
        enabled: false

  tasks:
    - name: Конфигурация L2 интерфейсов
      cisco.ios.ios_l2_interfaces:
        config:
          - name: "{{ item.name }}"
            mode: "{{ item.mode }}"
            trunk:
              allowed_vlans: "{{ item.trunk.allowed_vlans | default(omit) }}"
              native_vlan: "{{ item.trunk.native_vlan | default(omit) }}"
            access:
              vlan: "{{ item.access.vlan | default(omit) }}"
        state: merged
      loop: "{{ interfaces_config }}"

    - name: Настройка описаний и состояния
      cisco.ios.ios_interfaces:
        config:
          - name: "{{ item.name }}"
            description: "{{ item.description }}"
            enabled: "{{ item.enabled }}"
        state: merged
      loop: "{{ interfaces_config }}"

    - name: Сохранение конфигурации
      cisco.ios.ios_config:
        save_when: modified
```

### 11. Настройка Netconf на Juniper JunOS

```yaml
---
- name: Конфигурация Juniper через NETCONF
  hosts: junos_routers
  gather_facts: false
  vars:
    loopback_ip: 10.255.0.1/32
    interfaces_config:
      - name: ge-0/0/0
        unit: 0
        family: inet
        address: 192.168.1.1/24

  tasks:
    - name: Настройка Loopback
      junipernetworks.junos.junos_config:
        lines:
          - set interfaces lo0 unit 0 family inet address {{ loopback_ip }}
        commit: true

    - name: Настройка интерфейсов через NETCONF
      junipernetworks.junos.junos_l3_interfaces:
        config:
          - name: "{{ item.name }}"
            unit: "{{ item.unit }}"
            family:
              inet:
                - address: "{{ item.family.address }}"
        state: merged

    - name: Фиксация конфигурации (commit)
      junipernetworks.junos.junos_config:
        commit: true
        # Автоматический commit после каждого изменения

    - name: Верификация конфигурации
      junipernetworks.junos.junos_command:
        commands:
          - show configuration interfaces
          - show route
      register: junos_verify

    - name: Вывод конфигурации
      ansible.builtin.debug:
        msg: "Конфигурация: {{ junos_verify.stdout[0] }}"
```

### 12. Jinja2 шаблон для мультиплатформенной конфигурации

```jinja2
{# templates/base_config.j2 #}
{# Базовая конфигурация для мультиплатформенной сети #}

{# Cisco IOS #}
{% if ansible_network_os == 'cisco.ios.ios' %}
hostname {{ inventory_hostname }}
!
{% for ntp in network_ntp_servers %}
ntp server {{ ntp.ip }}
{% endfor %}
!
{% for dns in network_dns_servers %}
ip name-server {{ dns.ip }}
{% endfor %}
!
{% for acl in acl_rules %}
ip access-list extended {{ acl.name }}
{% for ace in acl.aces %}
  {{ ace.sequence }} {{ ace.grant }} {{ ace.protocol }} {{ ace.source }} {{ ace.destination }}
{% endfor %}
{% endfor %}

{# Juniper JunOS #}
{% elif ansible_network_os == 'junipernetworks.junos.junos' %}
system {
    host-name {{ inventory_hostname }};
{% for ntp in network_ntp_servers %}
    ntp {
        server {{ ntp.ip }};
    }
{% endfor %}
{% for dns in network_dns_servers %}
    name-server {
        {{ dns.ip }};
    }
{% endfor %}
}
{% for iface in interfaces %}
interfaces {{ iface.name }} {
    unit 0 {
        family inet {
            address {{ iface.address }};
        }
    }
}
{% endfor %}

{# Arista EOS #}
{% elif ansible_network_os == 'arista.eos.eos' %}
hostname {{ inventory_hostname }}
{% for ntp in network_ntp_servers %}
ntp server {{ ntp.ip }}
{% endfor %}
{% for dns in network_dns_servers %}
ip name-server {{ dns.ip }}
{% endfor %}
{% for iface in interfaces %}
interface {{ iface.name }}
  description {{ iface.description | default('') }}
  no shutdown
{% if iface.vlan is defined %}
  switchport access vlan {{ iface.vlan }}
{% endif %}
{% endfor %}
{% endif %}
```

### 13. Резервное копирование конфигурации всех устройств

```yaml
---
- name: Ежедневный backup конфигураций
  hosts: all_network
  gather_facts: false
  tasks:
    - name: Backup Cisco IOS
      cisco.ios.ios_config:
        backup: true
        backup_options:
          dir_path: "/backups/{{ inventory_hostname }}"
          filename: "{{ inventory_hostname }}_{{ ansible_date_time.iso8601_basic_short }}.cfg"
      when: ansible_network_os == 'cisco.ios.ios'

    - name: Backup Juniper JunOS
      junipernetworks.junos.junos_config:
        backup: true
        backup_options:
          dir_path: "/backups/{{ inventory_hostname }}"
          filename: "{{ inventory_hostname }}_{{ ansible_date_time.iso8601_basic_short }}.cfg"
      when: ansible_network_os == 'junipernetworks.junos.junos'

    - name: Backup Arista EOS
      arista.eos.eos_config:
        backup: true
        backup_options:
          dir_path: "/backups/{{ inventory_hostname }}"
          filename: "{{ inventory_hostname }}_{{ ansible_date_time.iso8601_basic_short }}.cfg"
      when: ansible_network_os == 'arista.eos.eos'

    - name: Удаление бэкапов старше 30 дней
      ansible.builtin.find:
        paths: "/backups/{{ inventory_hostname }}"
        patterns: "*.cfg"
        age: 30d
        recurse: false
      register: old_backups

    - name: Очистка старых бэкапов
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"
      when: old_backups.files | length > 0
```

## Устранение типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `No matching group exception` | Устаревшая версия коллекции | `ansible-galaxy collection install --upgrade cisco.ios` |
| `Timeout waiting for persistent connection` | Таймаут SSH-соединения | Увеличьте `persistent_connect_timeout` в `ansible.cfg` |
| `Invalid input detected` | Неподдерживаемая версия IOS | Проверьте `ansible_facts.version` и используйте `when:` для условий |
| `Could not connect to host` | Неверный IP/ hostname или Firewall | Проверьте `ansible_host`, порт 22/830, Firewall |
| `Permission denied (publickey,password)` | Неверные credentials | Проверьте `ansible_user`, `ansible_password` или SSH-ключ |
| `Unrecognized argument` | Модуль не поддерживает параметр | Проверьте документацию модуля: `ansible-doc cisco.ios.ios_config` |
| `MODULE FAILURE` | Python отсутствует на устройстве | Убедитесь, что `ansible_connection` = `network_cli`/`netconf`/`httpapi` |
| `Unable to enter configuration mode` | `become_method: enable` не работает | Проверьте `ansible_become_password` или отключите `enable` пароль |
| `netconf` XML parsing error | Неподдерживаемый YANG-модуль | Проверьте `yangdump` на устройстве или используйте `network_cli` |
| `Commit failed` (Juniper) | Конфликт конфигураций | Используйте `check: true` перед `commit: true` |
| `Invalid ACL entry` | Неверный синтаксис ACL | Проверьте формат: `grant protocol source destination port` |

**Диагностика:**
```bash
# Проверка подключения к устройству
ansible cisco_switches -m ping -vvv

# Просмотр собираемых фактов
ansible cisco_switches -m cisco.ios.ios_facts -a "gather_subset=all" -vvv

# Проверка синтаксиса плейбука
ansible-playbook network.yml --syntax-check

# Проверка в check_mode (без изменений)
ansible-playbook network.yml --check --diff

# Просмотр команд, которые будут выполнены
ansible-playbook network.yml --check --diff -vvv

# Выполнение на конкретном хосте
ansible-playbook network.yml --limit core-rtr-01
```

## Контрольный список: лучшие практики

- [ ] **Инвентарь:** `ansible_network_os` указан для каждого устройства, `ansible_connection` настроен
- [ ] **Become:** `ansible_become_method: enable` для Cisco, `sudo` для Juniper, пароли в Vault
- [ ] **Бэкапы:** `backup: true` перед каждым изменением конфигурации
- [ ] **Ресурсные модули:** Используйте `cisco.ios.ios_vlans` вместо `ios_config` с `lines`
- [ ] **Check mode:** Всегда проверяйте `--check --diff` перед реальными изменениями
- [ ] **Верификация:** Используйте `assert` для проверки ожидаемого состояния после изменений
- [ ] **FQCN:** Всегда полное имя модуля: `cisco.ios.ios_config`, не `ios_config`
- [ ] **Idempotency:** Избегайте `ios_command` для настройки — используйте ресурсные модули
- [ ] **Linting:** `ansible-lint --profile security` проходит без ошибок
- [ ] **Версионирование:** Все плейбуки и инвентарь хранятся в Git, изменения через Pull Request
- [ ] **Тестирование:** Используйте **[Containerlab](../Networking/Concepts/sdn/containerlab.md)** для лабораторных тестов перед деплоем
- [ ] **Documentation:** Описывайте назначение каждого интерфейса через `description`

## Дополнительная информация

### Рекомендации

1.  **Интеграция с SSoT:** Используйте **[Dynamic Inventory (NetBox)](./dynamic_inventory.md)** как единственный источник правды. Плагин `netbox.netbox.nb_inventory` позволяет строить динамический инвентарь на основе актуальных данных DCIM.
2.  **Тестирование и аудит:**
    *   **Check mode (`--check`):** Всегда запускайте плейбуки в этом режиме перед реальными изменениями.
    *   **Batfish / pyATS:** Используйте внешние инструменты для верификации конфигурации до и после деплоя (см. **[Network Verification](../Networking/Concepts/sdn/network_verification.md)**).
3.  **CI/CD Pipeline:** Храните конфигурацию в Git. Любое изменение должно проходить через Pull Request с автоматическим запуском `ansible-lint` и `ansible --check`.
4.  **Резервное копирование:** Включайте `backup: yes`. Это создает моментальный снимок конфига перед внесением изменений.
5.  **Идемпотентность:** Избегайте использования модулей `ios_command` или `ios_config` для внесения изменений, если существуют соответствующие ресурсные модули.
6.  **Тестирование:** Используйте **[Containerlab](../Networking/Concepts/sdn/containerlab.md)** для создания лабораторных сред с виртуальными устройствами перед продакшен-деплоем.

### Смотрите также

*   **[Ansible: Основные концепции](./ansible_core_concepts.md)** — архитектура Ansible, модули и плагины.
*   **[Динамический инвентарь](./dynamic_inventory.md)** — интеграция с NetBox и другие SSoT-источники.
