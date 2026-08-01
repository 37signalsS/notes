# Ansible — автоматизация сетевого оборудования

## Определения

**Сетевой модуль (Network Module)** — специализированный модуль Ansible, предназначенный для управления сетевыми устройствами (коммутаторами, маршрутизаторами, межсетевыми экранами). Выполняется всегда на **узле управления (Control Node)** через API или CLI, так как на сетевом оборудовании обычно нет Python.

**Сетевая ОС (Network OS)** — операционная система сетевого устройства (Cisco IOS, Juniper JunOS, Arista EOS). В Ansible указывается через переменную `ansible_network_os`.

**Ресурсный модуль (Resource Module)** — современный тип модулей для управления конкретными компонентами сети (интерфейсы, VLAN, статические маршруты). Имеют общую структуру данных и единую логику состояний (`state`).

**FQCN (Fully Qualified Collection Name)** — полное имя модуля в формате `vendor.collection.module`. Пример: `cisco.ios.ios_vlans`.

## Основные концепции

### Плагины подключения и Network OS

Сетевое оборудование использует специализированные плагины для поддержания постоянных соединений:

*   `ansible.netcommon.network_cli` — основное подключение через SSH к интерфейсу командной строки.
*   `ansible.netcommon.netconf` — работа через протокол NETCONF (обычно используется для Juniper и современных Cisco).
*   `ansible.netcommon.httpapi` — работа через REST API (например, Arista eAPI или Cisco NX-API).

Для корректной работы плагина обязательно должна быть задана переменная `ansible_network_os` (например, `cisco.ios.ios`).

### Управление привилегиями

Многие устройства требуют перехода в режим суперпользователя (Enable Mode).
*   `ansible_become: yes`
*   `ansible_become_method: enable`
*   `ansible_become_password: "{{ enable_password }}"` (хранить в [Ansible Vault](../Vault/basics.md)).

### Ресурсные модули и управление состоянием

Ресурсные модули позволяют декларативно описывать состояние сети. Параметр `state` определяет логику изменений:

*   `merged` — добавление/обновление настроек без удаления существующих (безопасно).
*   `replaced` — замена настроек только для указанных объектов.
*   `overridden` — полная перезапись всех настроек ресурса (может привести к удалению неуказанных VLAN/интерфейсов).
*   `deleted` — удаление указанных объектов.
*   `gathered` / `parsed` — сбор и парсинг текущей конфигурации в структурированный JSON.
*   `rendered` — генерация CLI-команд без отправки на устройство (для отладки).

### Настройка инвентаря для сетевых устройств

Сетевые устройства не могут выполнять Python-код локально. Поэтому в инвентаре необходимо явно указать параметры подключения, чтобы Ansible исполнял модули локально (на Control Node), транслируя команды через CLI или API.

**Пример `inventory.yml`:**
```yaml
routers:
  hosts:
    core-rtr-01.example.com:
  vars:
    # Использовать плагин CLI вместо стандартного SSH
    ansible_connection: ansible.netcommon.network_cli
    # Указать ОС для правильного парсинга команд
    ansible_network_os: cisco.ios.ios
    ansible_user: admin
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

## Дополнительная информация

### Рекомендации

1.  **Резервное копирование:** Всегда используйте параметр `backup: yes` в конфигурационных модулях. Файлы будут сохранены в `backup/` относительно плейбука.
2.  **Идемпотентность:** Предпочитайте ресурсные модули (`ios_vlans`, `ios_l3_interfaces`) модулям выполнения команд (`ios_config`, `ios_command`).
3.  **Безопасность:** Используйте SSH-ключи везде, где это поддерживает оборудование.

### Смотрите также

*   [Установка и настройка Ansible](./ansible_setup_and_config.md) — базовые параметры инвентаря.
*   [Ansible Vault](../Vault/basics.md) — защита паролей сетевого оборудования.
*   [Официальная документация по сетевым коллекциям](https://docs.ansible.com/ansible/latest/network/index.html) (EN).
