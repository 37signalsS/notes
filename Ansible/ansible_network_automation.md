# Ansible — автоматизация сетевого оборудования

## Определения

**Сетевой модуль (Network Module)** — специализированный модуль Ansible для управления сетевыми устройствами (коммутаторами, маршрутизаторами, FW). Выполняется всегда на **узле управления (Control Node)** через API или CLI, так как на сетевом оборудовании обычно отсутствует среда выполнения Python.

**Сетевая ОС (Network OS)** — операционная система сетевого устройства (Cisco IOS, Juniper JunOS, Arista EOS). В Ansible указывается через переменную `ansible_network_os`.

**Ресурсный модуль (Resource Module)** — современный тип модулей для управления конкретными компонентами сети (интерфейсы, VLAN, L3). Имеют общую структуру данных и единую логику состояний (`state`) для разных вендоров.

**Идемпотентность в сетях** — способность модуля приводить устройство к целевому состоянию без повторного выполнения команд, если конфигурация уже соответствует описанной. Для сетевых модулей это реализуется через сравнение текущего `running-config` с желаемым состоянием.

**SSoT (Single Source of Truth) в сетях** — внешний источник (NetBox, Nautobot, Git), содержащий эталонное состояние инфраструктуры. Автоматизация должна брать данные из SSoT, а не с самих устройств.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля в формате `vendor.collection.module`. Пример: `cisco.ios.ios_vlans`.

## Основные концепции

### Плагины подключения и Network OS

Сетевое оборудование использует специализированные плагины для поддержания постоянных соединений:

*   `ansible.netcommon.network_cli` — основное подключение через SSH к CLI. Оптимизировано для сетевых устройств (обработка приветствий, отключение пагинации).
*   `ansible.netcommon.netconf` — работа через протокол NETCONF (XML-базированный API). Рекомендуется для Juniper и современных Cisco (IOS-XE/XR).
*   `ansible.netcommon.httpapi` — работа через REST API (Arista eAPI, Cisco NX-API, FortiOS). Самый производительный метод для современных DC.

Для работы плагина обязательно должна быть задана переменная `ansible_network_os` (например, `cisco.ios.ios`, `junipernetworks.junos.junos`).

### Управление привилегиями

Многие устройства требуют перехода в режим суперпользователя (Enable Mode).
*   `ansible_become: yes`
*   `ansible_become_method: enable`
*   `ansible_become_password: "{{ enable_password }}"` (хранить в [Ansible Vault](../Vault/basics.md)).

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
```

## Практические сценарии

### Управление VLAN на Cisco IOS

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

### Сбор сетевых фактов

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

### Отключение постраничного вывода (Pagination)

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

### Настройка интерфейсов на Juniper Junos

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

### Управление BGP на Arista EOS

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

### Сбор сетевых фактов и инвентаризация (Discovery)

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

### Валидация данных (Data Validation)

Перед применением конфигурации на продакшен-устройствах необходимо проверить данные из SSoT на соответствие схеме.

```yaml
- name: Проверка структуры данных VLAN
  ansible.utils.validate:
    data: "{{ network_data }}"
    criteria:
      - "{{ lookup('file', 'vlan_schema.json') }}"
    engine: ansible.utils.jsonschema
```

## Дополнительная информация

### Рекомендации

1.  **Интеграция с SSoT:** Используйте [NetBox](../Networking/NetBox/netbox-automation.md) как единственный источник правды. Плагин `netbox.netbox.nb_inventory` позволяет строить динамический инвентарь на основе актуальных данных DCIM.
2.  **Тестирование и аудит:**
    *   **Check mode (`--check`):** Всегда запускайте плейбуки в этом режиме перед реальными изменениями.
    *   **Batfish / pyATS:** Используйте внешние инструменты для верификации конфигурации до и после деплоя.
3.  **CI/CD Pipeline:** Храните конфигурацию в Git. Любое изменение должно проходить через Pull Request с автоматическим запуском `ansible-lint` и `ansible --check`.
4.  **Резервное копирование:** Включайте `backup: yes`. Это создает моментальный снимок конфига перед внесением изменений.
5.  **Идемпотентность:** Избегайте использования модулей `ios_command` или `ios_config` для внесения изменений, если существуют соответствующие ресурсные модули.

### Смотрите также

*   [Установка и настройка Ansible](./ansible_setup_and_config.md) — базовые параметры инвентаря.
*   [Ansible Vault](../Vault/basics.md) — защита паролей сетевого оборудования.
*   [Динамический инвентарь (NetBox)](./dynamic_inventory.md) — интеграция с SSoT.
*   [Официальная документация: Network Automation](https://docs.ansible.com/ansible/latest/network/index.html) (EN).
