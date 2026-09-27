# Ansible: Модули управления сетевой конфигурацией Linux

## Определения

**Модули управления сетевой конфигурацией** — это группа специализированных инструментов Ansible (из `ansible.builtin`, `community.general`, `ansible.posix` и других коллекций), предназначенных для автоматизации настройки сетевых интерфейсов, мостов, VLAN, bonding, маршрутизации и DNS-резолверов на управляемых Linux-хостах.

**NetworkManager** — демон и утилиты для автоматического и ручного управления сетевыми соединениями на Linux. Ansible управляет NetworkManager через модуль `community.general.nmcli`.

**Netplan** — конфигурационный инструмент для сетевых интерфейсов в Ubuntu 17.10+. Использует YAML-файлы в `/etc/netplan/`. Ansible управляет Netplan через `ansible.builtin.template` + `netplan apply`.

**Bonding** — объединение нескольких сетевых интерфейсов в один логический для повышения пропускной способности или отказоустойчивости (mode 0/1/4/5/6).

**VLAN (Virtual LAN)** — технология разделения одной физической сети на несколько изолированных логических сетей.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля (например, `community.general.nmcli`). Использование FQCN является обязательным стандартом.

**sysctl** — механизм настройки параметров ядра Linux в runtime через `/proc/sys/`. Ansible управляет sysctl через `ansible.posix.sysctl`.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21.4+ | 2.21.4 — актуальный стабильный релиз (Sep 2026) |
| **community.general** | 6.0+ | 13.3.0+ | 13.3.0 — актуальный релиз (Sep 2026) |
| **ansible.posix** | 1.3+ | Актуальная | Для `ansible.posix.sysctl` |
| **Python** (target) | 3.9+ | 3.12+ | На управляемом хосте |
| **NetworkManager** (target) | 1.18+ | 1.58.1+ | 1.58.1 — актуальный релиз (Aug 2026) |
| **iproute2** (target) | 5.0+ | 7.2+ | 7.2 — актуальный релиз (Aug 2026) |
| **Netplan** (target) | 0.99+ | 1.2.1+ | 1.2.1 — актуальный релиз (Jun 2026) |
| **sudo** (target) | 1.8+ | Актуальная LTS | Для привилегированных операций |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible all -m ping
# → pong: web01
# → pong: db01

ansible all -m ansible.builtin.service_facts -a "filter=NetworkManager"
# → {"ansible_facts.services": {"NetworkManager": {"state": "running", "status": "enabled"}}}
```

**Установка коллекций:**
```bash
ansible-galaxy collection install community.general
ansible-galaxy collection install ansible.posix
```

## Архитектура и принципы работы

### Жизненный цикл модуля сетевой конфигурации

```
Задача Ansible (task)
    ↓
Модуль (community.general.nmcli / ansible.posix.sysctl / template)
    ↓
Локальное выполнение на control node (nmcli CLI / sysctl / file copy)
    ↓
SSH / become: yes → привилегированный доступ на target
    ↓
Изменение состояния системы (NetworkManager / /proc/sys / /etc/netplan/)
    ↓
Идемпотентная проверка (state: present / merged)
    ↓
Результат: changed / ok / failed
```

### Модель идемпотентности

Все модули сетевой конфигурации следуют модели идемпотентности Ansible:

1. **Сбор фактов** — модуль получает текущее состояние системы (список соединений nmcli, текущие sysctl-параметры, содержимое /etc/netplan/)
2. **Сравнение** — желаемое состояние сравнивается с текущим
3. **Применение** — изменения применяются только если текущее состояние не соответствует желаемому
4. **Результат** — `changed: true` при применении изменений, `changed: false` при повторном запуске

Пример: повторный запуск задачи с `state: present` и теми же параметрами не вызывает ошибок и не изменяет систему.

### Привилегированный доступ

Все операции с сетевыми интерфейсами, маршрутами и параметрами ядра требуют root-доступа. Используйте `become: yes` на уровне задачи или плейбука.

```yaml
- name: "Настройка Ethernet через nmcli"
  community.general.nmcli:
    conn_name: eth0
    type: ethernet
    ifname: eth0
    ip4: 192.168.1.10/24
    gw4: 192.168.1.1
    state: present
  become: yes
```

## Основные концепции

### Архитектура сетевой конфигурации Linux

```
Сетевой интерфейс (eth0, ens3, enp1s0)
    ↓
IP-адрес / netmask / gateway
    ↓
DNS-резолвер (systemd-resolved, NetworkManager, /etc/resolv.conf)
    ↓
Маршрутизация (таблица маршрутов, политическая маршрутизация)
```

### Модули управления сетевой конфигурацией

1.  **`community.general.nmcli`**: Управление NetworkManager через CLI. Создание, изменение, удаление соединений. Поддерживает `type` (ethernet, wifi, vpn, bond, bridge, vlan, vrf, wireguard), `conn_name`, `ifname`, `ip4`, `gw4`, `state`. Требует установленного `nmcli` на целевом хосте.
2.  **`ansible.builtin.template` + Netplan**: Управление сетевыми интерфейсами в Ubuntu через Netplan YAML-файлы. Применяется через `netplan apply`. Поддерживает ethernet, bonds, bridges, VLAN, VRFs.
3.  **`ansible.posix.sysctl`**: Управление параметрами ядра сети (`net.ipv4.ip_forward`, `net.core.somaxconn`, `net.ipv4.tcp_syncookies`, `net.ipv6.conf.all.forwarding`). Сохраняет настройки в `/etc/sysctl.d/`.
4.  **`ansible.builtin.lineinfile`**: Редактирование `/etc/hosts`, `/etc/resolv.conf` (осторожно, может быть перезаписан NetworkManager/systemd-resolved).
5.  **`ansible.builtin.template`**: Управление `/etc/resolv.conf` через шаблон, статическими маршрутами через `/etc/sysconfig/network-scripts/route-eth0` (RHEL) или `/etc/netplan/`.
6.  **`ansible.posix.firewalld` / `community.general.ufw`**: Управление файрволами. Открытие/закрытие портов, сервисов, зон.

### Типы сетевых интерфейсов

| Тип | Описание | Пример |
| :--- | :--- | :--- |
| **ethernet** | Физический интерфейс | `eth0`, `ens3`, `enp1s0` |
| **bond** | Агрегирование интерфейсов | `bond0` (mode 1/4/5/6) |
| **bridge** | Виртуальный коммутатор | `br0` (для VM/контейнеров) |
| **vlan** | Виртуальная LAN | `eth0.10` (VLAN 10) |
| **vrf** | Virtual Routing and Forwarding | `vrf0` (изоляция маршрутизации) |
| **wireguard** | VPN-туннель | `wg0` |
| **dummy** | Виртуальный интерфейс | `dummy0` (для testing) |
| **tun/tap** | Туннель | `tun0` (VPN) |

### Привилегированный доступ (become)

Все операции с сетевыми интерфейсами требуют root-доступа. Используйте `become: yes`.

```yaml
- name: "Настройка Ethernet через nmcli"
  community.general.nmcli:
    conn_name: eth0
    type: ethernet
    ifname: eth0
    ip4: 192.168.1.10/24
    gw4: 192.168.1.1
    state: present
  become: yes
```

## Практические сценарии

### Сценарий 1: Настройка статического IP через NetworkManager

```yaml
- name: "Создание соединения eth0"
  community.general.nmcli:
    conn_name: eth0
    type: ethernet
    ifname: eth0
    ip4: 192.168.1.10/24
    gw4: 192.168.1.1
    dns4:
      - 8.8.8.8
      - 8.8.4.4
    state: present
  become: yes

- name: "Активация соединения"
  community.general.nmcli:
    conn_name: eth0
    state: activated
  become: yes
```

**Валидация:**
```bash
# Проверка статуса соединения
ansible web01 -m community.general.nmcli -a "conn_name=eth0 state=activated"
# → {"conn_name": "eth0", "type": "ethernet", "state": "activated"}

# Проверка IP-адреса
ansible web01 -m ansible.builtin.command -a "ip addr show eth0"
# → inet 192.168.1.10/24 brd 192.168.1.255 scope global eth0

# Проверка маршрута по умолчанию
ansible web01 -m ansible.builtin.command -a "ip route show default"
# → default via 192.168.1.1 dev eth0
```

### Сценарий 2: Настройка bonding (mode 4 LACP)

```yaml
- name: "Создание bond0"
  community.general.nmcli:
    conn_name: bond0
    type: bond
    ifname: bond0
    bond_options:
      mode: 4
      miimon: 100
    ip4: 10.0.0.10/24
    gw4: 10.0.0.1
    state: present
  become: yes

- name: "Добавление slave интерфейсов"
  community.general.nmcli:
    conn_name: "{{ item }}"
    master: bond0
    slave_type: bond
    state: present
  become: yes
  loop:
    - eth1
    - eth2
```

**Валидация:**
```bash
# Проверка статуса bond0
ansible web01 -m ansible.builtin.command -a "cat /sys/class/net/bond0/bonding/mode"
# → 802.3ad 4

# Проверка slave-портов
ansible web01 -m ansible.builtin.command -a "cat /sys/class/net/bond0/bonding/slaves"
# → eth1 eth2

# Проверка LACP статуса
ansible web01 -m ansible.builtin.command -a "cat /sys/class/net/bond0/bonding/ad_aggregator"
# → 1
```

### Сценарий 3: Настройка VLAN

```yaml
- name: "Создание VLAN 10 на eth0"
  community.general.nmcli:
    conn_name: eth0.10
    type: vlan
    ifname: eth0.10
    vlan_parent: eth0
    vlan_id: 10
    ip4: 192.168.10.10/24
    state: present
  become: yes
```

**Валидация:**
```bash
# Проверка VLAN интерфейса
ansible web01 -m ansible.builtin.command -a "ip addr show eth0.10"
# → inet 192.168.10.10/24 brd 192.168.10.255 scope global eth0.10

# Проверка VLAN тегирования
ansible web01 -m ansible.builtin.command -a "ip -d link show eth0.10"
# → vlan protocol 802.1Q id 10 <REORDER_HDR>
```

### Сценарий 4: Настройка моста (bridge) для KVM

```yaml
- name: "Создание bridge br0"
  community.general.nmcli:
    conn_name: br0
    type: bridge
    ifname: br0
    ip4: 192.168.1.20/24
    state: present
  become: yes

- name: "Добавление slave в bridge"
  community.general.nmcli:
    conn_name: eth1
    master: br0
    slave_type: bridge
    state: present
  become: yes
```

**Валидация:**
```bash
# Проверка bridge
ansible web01 -m ansible.builtin.command -a "ip addr show br0"
# → inet 192.168.1.20/24 brd 192.168.1.255 scope global br0

# Проверка STP
ansible web01 -m ansible.builtin.command -a "cat /sys/class/net/br0/bridge/stp_state"
# → 1 (STP enabled)
```

### Сценарий 5: Настройка статических маршрутов

```yaml
- name: "Добавление статического маршрута"
  ansible.builtin.template:
    src: templates/static_route.j2
    dest: /etc/sysconfig/network-scripts/route-eth0
  become: yes
  notify: "Restart NetworkManager"

# Шаблон /etc/sysconfig/network-scripts/route-eth0
# 10.0.0.0/8 via 192.168.1.254 dev eth0
```

**Валидация:**
```bash
# Проверка таблицы маршрутов
ansible web01 -m ansible.builtin.command -a "ip route show"
# → default via 192.168.1.1 dev eth0
# → 10.0.0.0/8 via 192.168.1.254 dev eth0

# Проверка конкретного маршрута
ansible web01 -m ansible.builtin.command -a "ip route get 10.1.1.1"
# → 10.1.1.1 via 192.168.1.254 dev eth0
```

### Сценарий 6: Включение IP forwarding и tuning ядра

```yaml
- name: "Включение IP forwarding"
  ansible.posix.sysctl:
    name: net.ipv4.ip_forward
    value: '1'
    state: present
    reload: yes
    sysctl_file: /etc/sysctl.d/99-network.conf
  become: yes

- name: "Тюнинг сетевых параметров ядра"
  ansible.posix.sysctl:
    name: "{{ item.name }}"
    value: "{{ item.value }}"
    state: present
    reload: yes
    sysctl_file: /etc/sysctl.d/99-network.conf
  become: yes
  loop:
    - { name: 'net.core.somaxconn', value: '65535' }
    - { name: 'net.ipv4.tcp_syncookies', value: '1' }
    - { name: 'net.ipv4.conf.all.accept_redirects', value: '0' }
    - { name: 'net.ipv4.conf.all.send_redirects', value: '0' }
    - { name: 'net.ipv4.conf.all.rp_filter', value: '1' }
    - { name: 'net.ipv6.conf.all.forwarding', value: '1' }
```

**Валидация:**
```bash
# Проверка IP forwarding
ansible web01 -m ansible.posix.sysctl -a "name=net.ipv4.ip_forward"
# → net.ipv4.ip_forward = 1

# Проверка всех примененных параметров
ansible web01 -m ansible.builtin.command -a "sysctl -a | grep -E 'net\\.(ipv4|ipv6|core)'"
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_syncookies = 1
# → net.ipv4.ip_forward = 1

# Проверка persistent storage
ansible web01 -m ansible.builtin.command -a "cat /etc/sysctl.d/99-network.conf"
# → net.ipv4.ip_forward = 1
# → net.core.somaxconn = 65535
```

### Сценарий 7: Настройка статического IP через Netplan (Ubuntu)

```yaml
- name: "Развертывание Netplan конфигурации"
  ansible.builtin.template:
    src: templates/netplan/50-static.yaml.j2
    dest: /etc/netplan/50-static.yaml
    owner: root
    group: root
    mode: '0600'
  become: yes
  notify: "Apply netplan"

# Шаблон /etc/netplan/50-static.yaml
# network:
#   version: 2
#   ethernets:
#     eth0:
#       addresses:
#         - 192.168.1.10/24
#       routes:
#         - to: default
#           via: 192.168.1.1
#       nameservers:
#         addresses:
#           - 8.8.8.8
#           - 8.8.4.4
```

**Валидация:**
```bash
# Проверка конфигурации
ansible web01 -m ansible.builtin.command -a "netplan get ethernets.eth0"
# → addresses: [192.168.1.10/24]
# → nameservers.addresses: [8.8.8.8, 8.8.4.4]

# Проверка статуса
ansible web01 -m ansible.builtin.command -a "netplan status"
# → eth0: ethernet (link: yes, managed: yes)
```

### Сценарий 8: Настройка файрвола (firewalld)

```yaml
- name: "Открытие портов SSH и HTTP"
  ansible.posix.firewalld:
    service: "{{ item }}"
    permanent: yes
    immediate: yes
    state: enabled
  become: yes
  loop:
    - ssh
    - http

- name: "Открытие порта 9100 для node_exporter"
  ansible.posix.firewalld:
    port: 9100/tcp
    permanent: yes
    immediate: yes
    state: enabled
  become: yes
```

**Валидация:**
```bash
# Проверка активных зон
ansible web01 -m ansible.posix.firewalld -a "zone=public state=enabled"
# → {"zone": "public", "state": "enabled", "permanent": true}

# Проверка открытых портов
ansible web01 -m ansible.builtin.command -a "firewall-cmd --list-ports"
# → 9100/tcp

# Проверка сервисов
ansible web01 -m ansible.builtin.command -a "firewall-cmd --list-services"
# → ssh http
```

## Операции и команды

### Управление соединениями (nmcli)

| Операция | Команда |
| :--- | :--- |
| Создание соединения | `nmcli connection add type ethernet ifname eth0 conname eth0 ip4 192.168.1.10/24 gw4 192.168.1.1` |
| Активация | `nmcli connection up eth0` |
| Деактивация | `nmcli connection down eth0` |
| Удаление | `nmcli connection delete eth0` |
| Список | `nmcli connection show` |

### Управление маршрутизацией

| Операция | Команда |
| :--- | :--- |
| Добавить маршрут | `ip route add 10.0.0.0/8 via 192.168.1.254 dev eth0` |
| Удалить маршрут | `ip route del 10.0.0.0/8 via 192.168.1.254 dev eth0` |
| Показать таблицу | `ip route show` |

### Управление VLAN

| Операция | Команда |
| :--- | :--- |
| Создать VLAN | `ip link add link eth0 name eth0.10 type vlan id 10` |
| Активировать | `ip link set dev eth0.10 up` |
| Назначить IP | `ip addr add 192.168.10.10/24 dev eth0.10` |

### Управление sysctl

| Операция | Команда |
| :--- | :--- |
| Показать параметр | `sysctl net.ipv4.ip_forward` |
| Установить временно | `sysctl -w net.ipv4.ip_forward=1` |
| Сохранить persistently | `echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.d/99-network.conf && sysctl --system` |
| Применить все | `sysctl --system` |

### Управление firewalld

| Операция | Команда |
| :--- | :--- |
| Открыть порт | `firewall-cmd --add-port=9100/tcp --permanent` |
| Открыть сервис | `firewall-cmd --add-service=http --permanent` |
| Применить | `firewall-cmd --reload` |
| Список | `firewall-cmd --list-ports --list-services` |

## Устранение неполадок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Connection activation failed` | Неверные параметры или отсутствие устройства | Проверьте `nmcli device status`, убедитесь что интерфейс существует |
| `Device is not managed` | NetworkManager не управляет интерфейсом | Добавьте интерфейс в `/etc/NetworkManager/conf.d/` или используйте `keyfile` |
| `IP address already in use` | Конфликт IP | Проверьте `arping`, измените IP |
| `Route already exists` | Маршрут уже добавлен | Используйте `state: present` (идемпотентно) или проверьте существующий маршрут |
| `DNS not resolving` | Неверные DNS или блокировка | Проверьте `/etc/resolv.conf`, `systemd-resolve --status` |
| `nmcli: command not found` | NetworkManager не установлен | Установите `NetworkManager` через пакетный менеджер |
| `sysctl: permission denied` | Недостаточно прав | Используйте `become: yes` |
| `netplan apply failed` | Ошибка в YAML-синтаксисе | Проверьте `netplan try` или `netplan generate` перед apply |

### Диагностические команды

```bash
# Статус NetworkManager
nmcli general status
# → networking is enabled

# Список устройств
nmcli device status
# → DEVICE   TYPE      STATE      CONNECTION
# → eth0     ethernet  connected  eth0

# Детали соединения
nmcli connection show eth0
# → connection.id:                          eth0
# → connection.type:                        802-3-ethernet
# → ipv4.addresses:                         192.168.1.10/24
# → ipv4.gateway:                           192.168.1.1

# Проверка маршрутов
ip route show
# → default via 192.168.1.1 dev eth0
# → 10.0.0.0/8 via 192.168.1.254 dev eth0

# Проверка DNS
resolvectl status
# → Link 2 (eth0)
# →       DNS Servers: 8.8.8.8

# Проверка sysctl параметров
sysctl -a | grep -E '^net\.(ipv4|ipv6|core)'
# → net.core.somaxconn = 65535
# → net.ipv4.ip_forward = 1

# Проверка firewalld
firewall-cmd --list-all
# → public (active)
# →   services: ssh http
# →   ports: 9100/tcp
```

## Рекомендации и оптимизация

### Выбор инструмента конфигурации

| Инструмент | ОС | Когда использовать |
| :--- | :--- | :--- |
| **NetworkManager / nmcli** | RHEL 8+, Fedora, Ubuntu Server | Современные дистрибутивы с NetworkManager по умолчанию |
| **Netplan** | Ubuntu 17.10+ | Ubuntu Server, автоматизированный деплой |
| **sysctl** | Все Linux | Параметры ядра, IP forwarding, tuning |
| **template** | Все Linux | Статические маршруты, resolv.conf в legacy-средах |

### Оптимизация производительности

- **Ring buffer**: Увеличивайте `rx`/`tx` ring buffer для высоконагруженных интерфейсов: `ethtool -G eth0 rx 4096 tx 4096`.
- **Offloading**: Включайте `tso`, `gso`, `gro` для снижения CPU: `ethtool -K eth0 tso on gso on gro on`.
- **Multiqueue**: Для многоядерных систем используйте `multiqueue`: `ip link set dev eth0 type multififo`.
- **CPU affinity**: Привязывайте прерывания NIC к конкретным ядрам: `irqbalance` или `set_irq_affinity`.
- **TCP tuning**: Настройте `net.core.somaxconn`, `net.ipv4.tcp_max_syn_backlog`, `net.ipv4.tcp_synack_retries` для высоконагруженных сервисов.

### Безопасность

- **Firewall**: Всегда настраивайте файрвол (`firewalld`/`ufw`) вместе с сетью.
- **MAC flooding protection**: Включайте `port-security` на коммутаторах, ограничивайте MAC-адреса.
- **IPv6**: Не отключайте IPv6 без необходимости. Используйте `sysctl` для тонкой настройки (`net.ipv6.conf.all.forwarding`).
- **ARP protection**: Включайте `arp_ignore` и `arp_announce` для защиты от ARP-spoofing.
- **Accept redirects**: Отключайте `accept_redirects` и `send_redirects` на маршрутизаторах.
- **Reverse Path Filtering**: Включайте `rp_filter=1` для защиты от-spoofing.

### Мониторинг

- **Статус интерфейсов**: Используйте `node_exporter` textfile collector или `ansible.builtin.service_facts` для проверки.
- **Алертинг**: Настраивайте алерты на `ip link show` (DOWN интерфейсы), `ping` (доступность шлюза).
- **Сбор фактов**: Используйте `ansible.builtin.setup` с `filter: ansible_eth*` для сбора фактов о сетевых интерфейсах.
- **Сетевые метрики**: Экспортируйте `node_network_*` метрики в Prometheus через `node_exporter`.

## Дополнительная информация

- **[NetworkManager: управление соединениями](../../Networking/ServicesAndTools/NetworkManager/)** — теория и практика NetworkManager.
- **[Netplan](../../Networking/ServicesAndTools/Netplan/)** — конфигурация сети в Ubuntu.
- **[Сетевое ядро Linux](../../Linux/Networking/Concepts/)** — стек TCP/IP, sockets, netfilter.
- **[Системный администратор: маршрутизация](../../Linux/SystemAdministration/routing.md)** — статические и динамические маршруты.
- **[Модули управления файрволами](./ansible_security_and_user_management_modules.md)** — `firewalld`, `ufw`, `nftables`.
- **[Модули управления системой](./ansible_service_and_system_config_modules.md)** — `sysctl`, `modprobe`.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Кроссплатформенные концепции](../CrossPlatform/concepts.md)** — различия между ОС.
- **[Официальная документация nmcli](https://docs.ansible.com/ansible/latest/collections/community/general/nmcli_module.html)** — параметры модуля.
- **[Официальная документация Netplan](https://netplan.io/reference)** — синтаксис YAML.
