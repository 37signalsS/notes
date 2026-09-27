# Ansible: Модули управления сетевым оборудованием

## Определения

**Сетевые модули (Network Modules)** — специализированные инструменты Ansible из коллекций `cisco.*`, `juniperdevices.*`, `arista.*`, `ansible.netcommon`, предназначенные для управления конфигурацией сетевого оборудования (коммутаторы, маршрутизаторы, firewalls) через API или CLI без необходимости ручного входа на устройства.

**Network OS** — операционная система сетевого оборудования (Cisco IOS/IOS-XR/NX-OS, Juniper Junos, Arista EOS). В отличие от Linux/Windows, на сетевых устройствах обычно отсутствует среда выполнения Python, поэтому модули выполняются на контрольном узле через специализированные connection plugins.

**Resource module** — декларативный модуль Ansible, который управляет конфигурацией через операторы `merged`/`replaced`/`overridden`/`deleted`, аналогично `ansible.builtin.copy` для файлов. Это современный стандарт для сетевой автоматизации.

**Connection plugin** — механизм подключения Ansible к целевому хосту. Подробное описание плагинов `network_cli`, `httpapi`, `netconf` и параметров см. в [Ansible: Плагины подключения](./ansible_connection_plugins.md).

**Idempotency (идемпотентность)** — способность модуля приводить устройство к целевому состоянию без повторного выполнения команд, если конфигурация уже соответствует описанной. Для сетевых модулей это реализуется через сравнение текущего `running-config` с желаемым состоянием.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля в формате `vendor.collection.module`. Пример: `cisco.ios.ios_vlans`.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.16+ | 2.21+ |
| **cisco.ios** | 9.0+ | 11.5+ |
| **cisco.iosxr** | 10.0+ | 12.4+ |
| **cisco.nxos** | 8.0+ | 12.0+ |
| **juniperdevices.junos** | 1.0+ | Актуальная (redirect → `juniper.device`) |
| **arista.eos** | 9.0+ | 12.1+ |
| **ansible.netcommon** | 5.0+ | 8.6+ |
| **Python** (control node) | 3.9+ | 3.12+ |

**Установка коллекций:**
```bash
ansible-galaxy collection install cisco.ios
ansible-galaxy collection install cisco.iosxr
ansible-galaxy collection install cisco.nxos
ansible-galaxy collection install juniperdevices.junos
ansible-galaxy collection install arista.eos
ansible-galaxy collection install ansible.netcommon
```

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.x]

ansible-galaxy collection list | grep -E "cisco|juniper|arista"
# → cisco.ios        11.5.0
# → arista.eos       12.1.1
# → ansible.netcommon 8.6.1
```

## Архитектура и принципы работы

### Жизненный цикл модуля сетевого оборудования

1. **Сбор фактов (optional):** Модуль `_facts` опрашивает устройство через connection plugin и собирает текущее состояние (`running-config`, `interfaces`, `VLAN`, маршруты).
2. **Построение желаемого состояния:** Пользователь описывает target config в declarative-формате (YAML).
3. **Сравнение (diff):** Модуль вычисляет разницу между текущим и желаемым состоянием.
4. **Генерация команд:** На основе diff генерируются vendor-specific CLI/XML/JSON команды.
5. **Применение (commit):** Команды отправляются на устройство. Для NETCONF/RESTCONF выполняется атомарный commit; для CLI — последовательная отправка с возможностью отката.
6. **Верификация:** Модуль повторно опрашивает устройство для подтверждения применения конфигурации.
7. **Регистрация результата:** Возвращаются `changed`, `commands`, `failed`, `msg`.

### Модель идемпотентности

Сетевые модули обеспечивают идемпотентность через:
- **Парсинг running-config:** Модуль анализирует текущую конфигурацию устройства, а не просто запоминает, что был выполнен.
- **Структурированные данные:** Resource модули работают с нормализованными данными (VLAN ID, IP address), а не сырыми строками CLI.
- **Ключевые поля:** Используются `vlan_id`, `name`, `address` как уникальные идентификаторы. При повторном запуске с теми же значениями `changed: false`.
- **Compare- before-apply:** Перед отправкой команды модуль может проверить, что устройство еще не в desired state.

### Connection plugins

Сетевое оборудование требует специализированных connection plugins:

| Plugin | Транспорт | Использование |
| :--- | :--- | :--- |
| **`ansible.netcommon.network_cli`** | SSH + CLI парсинг | Cisco IOS, IOS-XR, NX-OS legacy |
| **`ansible.netcommon.httpapi`** | HTTPS REST API | Arista eAPI, Cisco NX-API |
| **`ansible.netcommon.netconf`** | NETCONF (RFC 6241) | Juniper Junos, Cisco IOS-XR |
| **`ansible.netcommon.grpc`** | gRPC | Cisco IOS-XE, NX-OS 9.3+ |

Для работы плагина обязательно задается переменная `ansible_network_os`, например `cisco.ios.ios`, `juniperdevices.junos.junos`, `arista.eos.eos`.

### Привилегированный доступ

На сетевых устройствах требуется escalation для изменения конфигурации:
- **Cisco IOS/NX-OS:** `ansible_become: yes`, `ansible_become_method: enable`, пароль в Vault
- **Juniper Junos:** `ansible_become: yes`, `ansible_become_method: sudo`
- **Arista EOS:** `ansible_become: yes`, `ansible_become_method: enable`

## Основные концепции

### Архитектура сетевой автоматизации

```
┌─────────────────┐     SSH/API/NETCONF      ┌─────────────────────┐
│  Control Node   │ ◄──────────────────────► │  Network Device     │
│  (Ansible)      │   connection plugin      │  (Switch/Router/FW) │
│                 │                           │                     │
│  - modules      │   persistent socket       │  - running-config   │
│  - collections  │   или direct transport    │  - candidate config │
│  - inventory    │                           │  - facts            │
└─────────────────┘                           └─────────────────────┘
        │
        ▼
  ┌─────────────┐
  │ Vault       │
  │ (creds)     │
  └─────────────┘
```

### Resource модули vs legacy команды

| Подход | Модуль | Преимущества |
| :--- | :--- | :--- |
| **Resource** | `cisco.ios.ios_vlans`, `juniperdevices.junos.junos_l3_interfaces` | Декларативный, идемпотентный, валидация |
| **Legacy command** | `cisco.ios.ios_command`, `ansible.netcommon.cli_command` | Сырые команды, нет идемпотентности |
| **Legacy config** | `cisco.ios.ios_config`, `juniperdevices.junos.junos_config` | Текстовая конфигурация, риск расхождений |

**Рекомендация:** Используйте resource модули везде, где возможно. Legacy `_config` модули — только для сложных или vendor-specific сценариев, не покрытых resource модулями.

### Supported connection plugins для network OS

| Vendor | Network OS | Рекомендуемый plugin | Альтернативы |
| :--- | :--- | :--- | :--- |
| **Cisco IOS** | `cisco.ios.ios` | `network_cli` | `httpapi` (NX-API) |
| **Cisco IOS-XR** | `cisco.iosxr.iosxr` | `netconf` | `network_cli` |
| **Cisco NX-OS** | `cisco.nxos.nxos` | `httpapi` | `network_cli` |
| **Juniper Junos** | `juniperdevices.junos.junos` | `netconf` | `network_cli` |
| **Arista EOS** | `arista.eos.eos` | `httpapi` | `network_cli` |

### Типы сетевых интерфейсов

- **L2 (access/trunk):** Управляются через `*_l2_interfaces` или `*_interfaces` с параметрами `mode`, `access.vlan`, `trunk.allowed_vlans`
- **L3 (routed):** Управляются через `*_l3_interfaces` с параметрами `ipv4`/`ipv6`
- **LAG/Port-channel:** Управляются через `*_lag_interfaces` с конфигурацией `members`, `mode` (`active`/`on`/`passive`)
- **VLAN:** Управляются через `*_vlans` (не путать с интерфейсами)

## Практические сценарии

### Сценарий 1: Настройка VLAN на Cisco IOS

```yaml
- name: "Настройка VLAN на коммутаторах Cisco"
  hosts: cisco_switches
  connection: ansible.netcommon.network_cli
  gather_facts: no
  vars:
    ansible_network_os: cisco.ios.ios
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
    ansible_become: yes
    ansible_become_method: enable
    ansible_become_password: "{{ vault_enable_password }}"
  tasks:
    - name: "Создание VLAN 100-200"
      cisco.ios.ios_vlans:
        config:
          - vlan_id: 100
            name: USERS_VLAN
          - vlan_id: 200
            name: SERVERS_VLAN
        state: merged
      register: vlan_result

    - name: "Настройка портов коммутатора"
      cisco.ios.ios_interfaces:
        config:
          - name: GigabitEthernet0/1
            description: "Uplink to core"
            mode: trunk
            trunk:
              allowed_vlans: "100,200"
          - name: GigabitEthernet0/2
            description: "Server port"
            mode: access
            access:
              vlan: 200
        state: merged

    - name: "Проверка конфигурации"
      ansible.builtin.assert:
        that:
          - vlan_result is changed
        fail_msg: "VLAN не были созданы"
```

**Валидация:**
```bash
ansible-playbook playbook.yml --check --diff
# → PLAY [Настройка VLAN на коммутаторах Cisco] *********************
# → TASK [Создание VLAN 100-200] *************************************
# → changed: [switch01]

ssh admin@switch01 "show vlan brief"
# → 100  USERS_VLAN          active    Gi0/2
# → 200  SERVERS_VLAN        active    Gi0/1, Gi0/3
```

### Сценарий 2: Настройка L3 интерфейсов на Juniper Junos

```yaml
- name: "Настройка L3 интерфейсов Juniper"
  hosts: juniper_routers
  connection: ansible.netcommon.netconf
  gather_facts: no
  vars:
    ansible_network_os: juniperdevices.junos.junos
    ansible_user: admin
    ansible_password: "{{ vault_juniper_password }}"
  tasks:
    - name: "Настройка интерфейсов"
      juniperdevices.junos.junos_l3_interfaces:
        config:
          - name: ge-0/0/0
            ipv4:
              - address: 192.168.1.1/24
            state: present
          - name: ge-0/0/1
            ipv4:
              - address: 10.0.0.1/24
            state: present
        state: merged

    - name: "Проверка IP-адресов"
      ansible.builtin.command: show interfaces terse
      register: iface_output
```

**Валидация:**
```bash
ansible-playbook playbook.yml
# → changed: [mx-core-01]

ssh admin@mx-core-01 "show interfaces terse"
# → ge-0/0/0.0    up    up    inet 192.168.1.1/24
# → ge-0/0/1.0    up    up    inet 10.0.0.1/24
```

### Сценарий 3: Статические маршруты на Arista EOS

```yaml
- name: "Настройка статических маршрутов"
  hosts: arista_switches
  connection: ansible.netcommon.httpapi
  gather_facts: no
  vars:
    ansible_network_os: arista.eos.eos
    ansible_httpapi_use_ssl: yes
    ansible_httpapi_validate_certs: no
    ansible_httpapi_host: "{{ inventory_hostname }}"
    ansible_httpapi_port: 443
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
  tasks:
    - name: "Добавление маршрутов"
      arista.eos.eos_static_routes:
        config:
          - vrf: default
            address_family: ipv4
            routes:
              - dest: 0.0.0.0/0
                next_hops:
                  - forward_router_address: 10.0.0.1
                    admin_distance: 1
              - dest: 172.16.0.0/16
                next_hops:
                  - forward_router_address: 10.0.0.2
        state: merged

    - name: "Проверка маршрутов"
      ansible.builtin.command: show ip route
      register: route_output
```

**Валидация:**
```bash
ansible-playbook playbook.yml
# → changed: [leaf01]

ssh admin@leaf01 "show ip route"
# → S   0.0.0.0/0 [1/0] via 10.0.0.1
# → S   172.16.0.0/16 [1/0] via 10.0.0.2
```

### Сценарий 4: Настройка BGP на Cisco IOS-XR

```yaml
- name: "Настройка BGP на Cisco IOS-XR"
  hosts: cisco_xr_routers
  connection: ansible.netcommon.netconf
  gather_facts: no
  vars:
    ansible_network_os: cisco.iosxr.iosxr
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
  tasks:
    - name: "Конфигурация BGP"
      cisco.iosxr.iosxr_bgp:
        config:
          - as_number: 65001
            router_id: 1.1.1.1
            neighbors:
              - neighbor_address: 10.0.0.2
                remote_as: 65002
                update_source: GigabitEthernet0/0/0/0
        state: merged

    - name: "Проверка BGP соседей"
      ansible.builtin.command: show bgp summary
      register: bgp_output
```

**Валидация:**
```bash
ansible-playbook playbook.yml
# → changed: [xr-core-01]

ssh admin@xr-core-01 "show bgp summary"
# → Neighbor        AS    Up/Down  St/PfxRcd
# → 10.0.0.2        65002 00:03:22 5
```

### Сценарий 5: Конфигурация интерфейсов и VLAN на Cisco NX-OS

```yaml
- name: "Настройка NX-OS"
  hosts: nxos_switches
  connection: ansible.netcommon.httpapi
  gather_facts: no
  vars:
    ansible_network_os: cisco.nxos.nxos
    ansible_httpapi_use_ssl: yes
    ansible_httpapi_validate_certs: no
    ansible_httpapi_host: "{{ inventory_hostname }}"
    ansible_httpapi_port: 443
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
  tasks:
    - name: "Настройка VLAN"
      cisco.nxos.nxos_vlans:
        config:
          - vlan_id: 100
            name: DATA_VLAN
            enabled: true
        state: merged

    - name: "Настройка интерфейсов"
      cisco.nxos.nxos_interfaces:
        config:
          - name: Ethernet1/1
            description: "Uplink"
            mode: trunk
            trunk:
              allowed_vlans: "100,200"
        state: merged
```

**Валидация:**
```bash
ansible-playbook playbook.yml
# → changed: [nxos-leaf01]

ssh admin@nxos-leaf01 "show vlan brief"
# → 100  DATA_VLAN          active    Eth1/1
```

### Сценарий 6: Бэкап и восстановление конфигурации

```yaml
- name: "Бэкап конфигурации Cisco"
  hosts: cisco_switches
  connection: ansible.netcommon.network_cli
  gather_facts: no
  vars:
    ansible_network_os: cisco.ios.ios
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
    ansible_become: yes
    ansible_become_method: enable
    ansible_become_password: "{{ vault_enable_password }}"
  tasks:
    - name: "Бэкап running-config"
      cisco.ios.ios_config:
        backup: yes
        backup_options:
          dir_path: "/backups/{{ inventory_hostname }}"
          filename: "{{ inventory_hostname }}_{{ ansible_date_time.iso8601_basic_short }}.cfg"
```

**Валидация:**
```bash
ls /backups/switch01/
# → switch01_20260926162200.cfg
```

## Операции и команды

### Проверка статуса устройства

```bash
# Доступность
ansible -i inventory.yml cisco_switches -m ansible.builtin.ping -o
# → switch01 | SUCCESS => {"ping": "pong"}

# Сбор facts
ansible -i inventory.yml cisco_switches -m cisco.ios.ios_facts
# → "ansible_facts": {"net_model": "C9300-24P", "net_serialnum": "FCW1234A1B2"}

# Проверка конфигурации
ansible -i inventory.yml cisco_switches -m cisco.ios.ios_config -a "commands=show running-config"
```

### Работа с inventory

```yaml
# inventory/hosts.yml
all:
  hosts:
    switch01:
      ansible_host: 10.0.1.10
      ansible_connection: ansible.netcommon.network_cli
      ansible_network_os: cisco.ios.ios
      ansible_user: admin
      ansible_password: "{{ vault_network_password }}"
      ansible_become: yes
      ansible_become_method: enable
      ansible_become_password: "{{ vault_enable_password }}"
      ansible_persistent_connect_timeout: 60
      ansible_persistent_command_timeout: 60
```

### Check mode и diff

```bash
ansible-playbook playbook.yml --check --diff
# → changed: [switch01] (dry-run)
# → --- running-config
# → +++ candidate-config
# → @@ -1,5 +1,6 @@
# →  interface GigabitEthernet0/2
# → +  description Server port
```

## Устранение неполадок

### Проблема: `ansible_network_os` не задан

```bash
# Ошибка
fatal: [switch01]: FAILED! => {"msg": "Unable to find connection plugin for ansible.netcommon.network_cli"}
```

**Решение:** Задайте `ansible_network_os` в inventory или playbook vars.

### Проблема: Timeout при подключении

```bash
# Ошибка
ssh time out: Timeout (61s) connecting to 10.0.1.10
```

**Решение:** Увеличьте `ansible_persistent_connect_timeout` и `ansible_persistent_command_timeout` до 60–120 секунд. Проверьте доступность порта 22 и сетевую маршрутизацию.

### Проблема: `show` команды парсятся некорректно

**Решение:** Проверьте, что paging отключен (`terminal length 0`). Connection plugin `network_cli` делает это автоматически. Для кастомных prompt используйте `ansible_network_cli_prompt` и `ansible_network_cli_answers`.

### Проблема: NETCONF session не открывается

**Решение:** Убедитесь, что NETCONF включен на устройстве (`netconf-yang` в Cisco, `set system services netconf ssh` в Juniper). Проверьте, что порт 830 доступен.

### Диагностика connection plugin

```bash
# Включение отладки
export ANSIBLE_DEBUG=1
ansible-playbook playbook.yml -vvv
# → <10.0.1.10> ESTABLISH SSH CONNECTION FOR USER: admin
# → <10.0.1.10> SSH: EXEC ssh -C -o ControlMaster=auto ...
```

## Рекомендации и оптимизация

### Выбор инструмента

| Сценарий | Рекомендация |
| :--- | :--- |
| **Современная автоматизация** | Resource модули (`merged`/`replaced`) |
| **Сложная конфигурация** | `_config` модули с `backup: true` |
| **Быстрый опрос** | `_facts` модули или `cli_command` |
| **API-устройства** | `httpapi` (Arista eAPI, Cisco NX-API) |
| **Junos** | `netconf` (предпочтительно) |

### Оптимизация производительности

- **Persistent connection:** Используйте `ansible.netcommon.persistent` для сокращения overhead SSH-соединений при批量ных изменениях.
- **Параллелизм:** Настройте `forks = 20–50` в `ansible.cfg` для парков >10 устройств.
- **Таймауты:** `ansible_persistent_connect_timeout: 60`, `ansible_persistent_command_timeout: 60` для production-сетей с высоким latency.
- **Check mode:** Всегда проверяйте `--check --diff` перед применением.

### Безопасность

- **Vault:** Храните все credentials в Ansible Vault. Никогда не хардкодьте пароли в инвентаре.
- **Certificate validation:** `ansible_httpapi_validate_certs: true` в production.
- **SSH keys:** Предпочитайте ключи паролям. Используйте `ansible_ssh_private_key_file`.
- **Become:** `ansible_become_method: enable` для Cisco, `sudo` для Juniper. Пароли escalate в Vault.

### Мониторинг и логирование

- **Статус изменений:** Используйте `register` + `ansible.builtin.assert` для валидации.
- **Аудит:** Включите `log_path` в `ansible.cfg` для журналирования всех runs.
- **Сбор фактов:** Регулярно собирайте `_facts` для инвентаризации.

## Дополнительная информация

- **[Cisco IOS Collection](https://docs.ansible.com/ansible/latest/collections/cisco/ios/)** — документация модулей Cisco IOS.
- **[Juniper Junos Collection](https://docs.ansible.com/ansible/latest/collections/juniperdevices/junos/)** — документация модулей Junos.
- **[Arista EOS Collection](https://docs.ansible.com/ansible/latest/collections/arista/eos/)** — документация модулей Arista EOS.
- **[Ansible Network Automation](https://docs.ansible.com/ansible/latest/network/getting_started/network_automation.html)** — руководство по сетевой автоматизации.
- **[Ansible: Плагины подключения](./ansible_connection_plugins.md)** — документация по `network_cli`, `httpapi`, `netconf` и другим плагинам.
