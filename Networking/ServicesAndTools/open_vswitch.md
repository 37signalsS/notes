# Open vSwitch (OVS) и OVN — сетевая виртуализация и SDN

## Определения

**Open vSwitch (OVS)** — это высокопроизводительный многоуровневый программный коммутатор с открытым исходным кодом, оптимизированный для работы в виртуализированных и динамических средах. В отличие от стандартного Linux Bridge, OVS спроектирован для поддержки программно-определяемых сетей (SDN) и расширенных протоколов управления (OpenFlow). Текущая стабильная версия — 3.7.1 (Feb 2026), LTS-ветка — 3.3.9.

**OVN (Open Virtual Network)** — система управления сетевой виртуализацией, построенная на базе OVS. Она обеспечивает абстракцию логических сетей (L2/L3, ACL, балансировщики), отделяя логическую топологию от физической инфраструктуры. Текущая версия — 26.03 (Mar 2026).

**Datapath** — уровень пересылки пакетов (уровень данных). Реализуется либо в ядре Linux (Kernel), либо в пространстве пользователя (Userspace/DPDK).

## Базовые концепции

### Архитектура OVS

Система разделена на три функциональных блока для обеспечения гибкости и производительности:

1.  **ovs-vswitchd**: Основной демон (userspace). «Мозг» системы. Управляет пересылкой пакетов, обрабатывает логику OpenFlow, управляет таблицами потоков и взаимодействует с внешними контроллерами.
2.  **ovsdb-server**: База данных конфигурации (JSON-RPC). Хранит информацию о мостах, портах, очередях QoS и настройках туннелей. Обладает транзакционностью и сохраняет состояние после перезагрузки.
3.  **Forwarding Plane (Datapath)**:
    *   **Kernel Datapath (`openvswitch.ko`)**: Стандартный режим. Первые пакеты потока отправляются в userspace (`ovs-vswitchd`) для принятия решения, после чего в ядро устанавливается «быстрое» правило (flow) для последующих пакетов этого потока.
    *   **Userspace Datapath (OVS-DPDK)**: Использует библиотеку DPDK для обработки пакетов полностью в обход ядра (kernel bypass), исключая накладные расходы на прерывания и копирование данных.

### Ключевые сущности

*   **Bridge (Мост)**: Виртуальный коммутатор. Один экземпляр OVS может поддерживать множество независимых мостов.
*   **Port (Порт)**: Точка входа/выхода трафика. Типы:
    *   `Physical`: Привязка к физическому сетевому адаптеру (NIC).
    *   `Internal`: Виртуальный интерфейс для связи с хостом (например, для назначения IP мосту).
    *   `Tunnel`: Инкапсуляция (VXLAN, Geneve, GRE).
    *   `Patch`: Сверхбыстрое соединение двух мостов внутри одного экземпляра OVS (patch ports).
    *   `Mirror`: Зеркалирование трафика для анализа (на основе `ovs-vsctl -- --id=@m create Mirror ...`).
*   **Flow (Поток)**: Набор правил в таблице OpenFlow. Состоит из условий сопоставления (Match: L2-L4 заголовки) и действий (Actions: отправить в порт, изменить заголовок, отбросить). OVS поддерживает до 32 OpenFlow-регистров (с v3.7.0).
*   **Queue**: Логическая очередь для организации QoS. Привязывается к порту через `ovs-vsctl set port <port> qos=@qos -- --id=@qos create QoS type=linux-htb other-config:max-rate=<bps> -- --id=@q create Queue other-config:min-rate=<bps> other-config:max-rate=<bps>`.
*   **Bond**: Агрегация нескольких физических портов в логический канал для отказоустойчивости и увеличения пропускной способности. Режимы: `active-backup`, `balance-slb`, `balance-tcp` (требует LACP).

### Архитектура OVN

OVN реализует логический уровень сети поверх физических узлов (chassis):
- **Northbound DB (NB)**: Описывает логическую топологию (логические мосты, роутеры, ACL). Управляется через `ovn-nbctl`.
- **Southbound DB (SB)**: Связывает логические сущности с физическими хостами. Хранит логические потоки (`lflow`). Управляется через `ovn-sbctl`.
- **ovn-northd**: Транслирует логическую конфигурацию из NB в SB.
- **ovn-controller**: Агент на каждом гипервизоре, который транслирует логические правила SB в конкретные потоки OpenFlow для локального OVS.

### Производительность и ускорение (DPDK и Offload)

1.  **OVS-DPDK**:
    *   **HugePages**: Использование страниц памяти по 2 МБ или 1 ГБ для минимизации промахов TLB (Translation Lookaside Buffer).
    *   **PMD (Poll Mode Drivers)**: Выделенные ядра CPU постоянно опрашивают сетевую карту (Polling), исключая прерывания и контекстные переключения.
    *   **Zero-copy**: Прямое чтение из памяти NIC в буферы userspace.
    *   **Address Prefix Tracking** (с v3.5.0): Автоматическое отслеживание префиксов IP-адресов (nw_dst, nw_src, ipv6_dst, ipv6_src) для значительного уменьшения количества потоков datapath в смешанных IPv4+IPv6 сценариях.
    *   **TSO Software Fallback** (с v3.5.0): Программная поддержка TSO для инкапсулированных пакетов (VXLAN, Geneve, GRE) в userspace datapath.
    *   **AVX512-оптимизации** (депrecated с v3.7.0): Ускоренные DPCLS lookups, action handling, miniflow extraction и DPIF input processing.
2.  **Hardware Offload (TC Flower)**: Перенос обработки потоков (Flow Offloading) на аппаратный уровень сетевой карты (ASIC/SmartNIC). Это позволяет OVS работать на скоростях 100G/200G без существенной нагрузки на CPU хоста. С v3.5.0 добавлена поддержка сопоставления tunnel flags и DF-флага в encap action (при поддержке ядром).
3.  **Geneve и TLV**: OVN по умолчанию использует протокол Geneve для туннелирования, так как он поддерживает передачу дополнительных метаданных через TLV (Type-Length-Value), что необходимо для сложной логики виртуальных сетей.

### Соединения и фильтрация (Conntrack)

OVS интегрирован с механизмом **Connection Tracking** (conntrack) ядра Linux. Это позволяет реализовывать **Stateful Firewalls** (например, NetworkPolicies в Kubernetes через Antrea или OVN-Kubernetes). Пакет отправляется в модуль conntrack (`action:ct`), который помечает его состоянием (`new`, `established`, `related`, `invalid`), после чего OVS принимает решение на основе этих меток. В userspace datapath conntrack поддерживает FTP-команды EPSV/EPRT для IPv4 (с v3.7.0), а также произвольные ограничения зон (zone limits) с наследованием.

### Установка и управление сервисами

**Предусловия:**
- Linux-дистрибутив с поддержкой ядра >= 3.10 (для kernel datapath) или >= 5.4 (для AF_XDP в userspace).
- Для DPDK: HugePages,🎻️ vfio-pci绑定 NIC, DPDK 25.11 (для OVS 3.7.x).
- Для OVN: PostgreSQL >= 9.4 (для NB/SB БД), Open vSwitch >= 2.12.

**Установка из пакетов (Debian/Ubuntu):**
```bash
sudo apt update
sudo apt install -y openvswitch-switch openvswitch-common ovn-central ovn-host ovn-common
```

**Управление сервисами:**
```bash
# OVS (systemd)
sudo systemctl enable --now openvswitch-switch
sudo systemctl status openvswitch-switch

# OVN Central (NB + SB + northd — на выделенном узле)
sudo systemctl enable --now ovn-northd ovn-nb-server ovn-sb-server

# OVN Controller (на каждом гипервизоре)
sudo systemctl enable --now ovn-controller
```

**Проверка работоспособности:**
```bash
ovs-vsctl show                    # Состояние мостов и портов
ovs-vswitchd --version            # Версия OVS
ovn-nbctl show                    # Состояние OVN NB
ovn-sbctl show                    # Состояние OVN SB
```

## Практические сценарии

### Управление мостами и портами (ovs-vsctl)

```bash
# Просмотр всей иерархии (мосты, порты, интерфейсы)
ovs-vsctl show

# Создание моста и добавление физического интерфейса
ovs-vsctl add-br br-int
ovs-vsctl add-port br-int eth0

# Настройка внутреннего интерфейса для управления хостом
ovs-vsctl add-port br-int mgmt0 -- set Interface mgmt0 type=internal
ip addr add 192.168.1.10/24 dev mgmt0
ip link set mgmt0 up

# Работа с VLAN: порт в режиме Access (VLAN 10)
ovs-vsctl add-port br-int vnet0 tag=10

# Работа с VLAN: порт в режиме Trunk (разрешить VLAN 10, 20, 30)
ovs-vsctl set port eth0 trunks=10,20,30

# Настройка VXLAN туннеля к удаленному гипервизору
ovs-vsctl add-port br-int vxlan0 -- set interface vxlan0 type=vxlan options:remote_ip=172.16.1.5

# Просмотр моста с фильтрацией (с v3.6.0)
ovs-vsctl show --filter Bridge
```

### Bonding (LACP) для отказоустойчивости

```bash
# Создание bond из двух физических портов (active-backup)
ovs-vsctl add-bond br-int bond0 eth0 eth1 \
  -- set port bond0 lacp=off bond_mode=active-backup

# LACP-режим (balance-tcp) — требует поддержки LACP на коммутаторе
ovs-vsctl add-bond br-int bond0 eth0 eth1 \
  -- set port bond0 lacp=active bond_mode=balance-tcp

# Просмотр состояния bond
ovs-appctl bond/show bond0

# Принудительный failover
ovs-appctl bond/set-active-slave bond0 eth1
```

### Очереди и QoS (Linux HTB)

```bash
# Создание QoS-политики на порту (HTB, max 10 Gbps)
ovs-vsctl -- --id=@qos create QoS type=linux-htb \
  other-config:max-rate=10000000000 \
  -- set port eth0 qos=@qos

# Создание очереди: min 1 Gbps, max 5 Gbps (VLAN 100)
ovs-vsctl -- --id=@q create Queue \
  other-config:min-rate=1000000000 \
  other-config:max-rate=5000000000 \
  -- set QoS @qus queues:100=@q

# Привязка очереди к потоку OpenFlow
ovs-ofctl add-flow br-int "priority=100,dl_vlan=100,actions=set_queue:100,output:eth0"

# Мониторинг статистики очередей
ovs-vsctl list QoS
ovs-vsctl list Queue
```

### Настройка OVS-DPDK

```bash
# 1. Выделение HugePages (пример: 1024 страницы по 2МБ)
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

# 2. Привязка NIC к vfio-pci
sudo modprobe vfio-pci
sudo dpdk-devbind.py --bind=vfio-pci 0000:04:00.0

# 3. Инициализация DPDK в OVS
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="1024,1024"
# Ядра 0-1 для EAL, ядра 2-3 для PMD
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-lcore-mask=0x3
ovs-vsctl --no-wait set Open_vSwitch . other_config:pmd-cpu-mask=0xc

# 4. Создание моста и порта DPDK (тип netdev)
ovs-vsctl add-br br-dpdk -- set bridge br-dpdk datapath_type=netdev
ovs-vsctl add-port br-dpdk dpdk0 -- set Interface dpdk0 type=dpdk options:dpdk-devargs=0000:04:00.0

# 5. Проверка PMD-потоков
ovs-appctl dpif-netdev/pmd-rxq-show

# 6. Динамическая перенастройка PMD
ovs-vsctl set Open_vSwitch . other_config:pmd-cpu-mask=0xf
```

### IPsec туннели

```bash
# Генерация ключей и сертификатов
sudo ovs-pki req+cert --subject="/CN=ovs-host1" --days=3650
sudo ovs-pki req+cert --subject="/CN=ovs-host2" --days=3650

# Настройка SSL для ovsdb-server (на обоих хостах)
sudo ovs-vsctl set-ssl /etc/ovs/ovs-host1-privkey.pem \
  /etc/ovs/ovs-host1-cert.pem /etc/ovs/ovn-ca.cert
sudo ovsdb-server pssl:6641 --remote=db:Open_vSwitch,Open_vSwitch,manager_options

# Настройка IPsec-туннеля (ESP)
ovs-vsctl add-port br-int ipsec0 \
  -- set Interface ipsec0 type=ipsec \
  options:remote_ip=172.16.1.5 \
  options:local_cert=/etc/ovs/ovs-host1-cert.pem \
  options:peer_cert=/etc/ovs/ovs-host2-cert.pem \
  options:remote_name=ovs-host2

# Мониторинг IPsec
sudo ovs-monitor-ipsec --detach
sudo systemctl status ovs-monitor-ipsec
```

### Управление в OVN (ovn-nbctl)

```bash
# Создание логического коммутатора sw0
ovn-nbctl ls-add sw0

# Добавление логического порта lsp1 и привязка адреса
ovn-nbctl lsp-add sw0 lsp1
ovn-nbctl lsp-set-addresses lsp1 "00:00:00:00:00:01 192.168.1.10"

# Настройка логического роутера
ovn-nbctl lr-add lr0
ovn-nbctl lrp-add lr0 lr0-sw0 00:00:00:00:ff:01 192.168.1.1/24
ovn-nbctl lsp-add sw0 sw0-lr0 -- set logical_switch_port sw0-lr0 type=router \
  options:router-port=lr0-sw0

# ACL: разрешить HTTP-трафик к порту 80
ovn-nbctl acl-add sw0 to-lport 100 "ip4.tcp.dst_port=80" allow

# ACL: запретить весь исходящий трафик (deny по умолчанию)
ovn-nbctl acl-add sw0 to-lport 10 "ip4" deny

# Балансировка нагрузки (DNAT)
ovn-nbctl lb-add tcp_lb "10.0.0.100:80" "192.168.1.10:80,192.168.1.11:80"
ovn-nbctl ls-lb-add sw0 tcp_lb

# DHCP-опция для логического коммутатора
ovn-nbctl dhcp-options-create 192.168.1.0/24 192.168.1.1
ovn-nbctl dhcp-options-set-options <dhcp_uuid> \
  lease_time=3600 router=192.168.1.1 dns_server=8.8.8.8

# Просмотр логических потоков (Southbound)
ovn-sbctl lflow-list sw0
```

### Динамические маршруты и EVPN (OVN 25.03+)

```bash
# Включение динамической маршрутизации на логическом роутере
ovn-nbctl set logical_router lr0 options:dynamic-routing=true

# Фильтрация advertisments: только connected и static
ovn-nbctl set logical_router lr0 \
  options:dynamic-routing-redistribute="connected,static"

# EVPN-интеграция: привязка к L2-домену
ovn-nbctl set logical_switch sw0 \
  other_config:dynamic-routing-vni=10000

# Transit Router для междоменной маршрутизации (OVN 26.03+)
ovn-ic-nbctl tr-add tr0
ovn-ic-nbctl trp-add tr0 tr0-port1 00:00:00:00:ff:01
```

### Сетевые функции (Network Functions, OVN 26.03+)

```bash
# Создание entity сетевой функции (inline-режим)
ovn-nbctl -- --id=@nf create Network_Function \
  inport=nf-in outport=nf-out \
  -- lsp-add sw0 nf-in -- lsp-add sw0 nf-out \
  -- set logical_switch_port nf-in options:is-nf=true \
  -- set logical_switch_port nf-out options:is-nf=true

# Группа с health-check для отказоустойчивости
ovn-nbctl -- --id=@nfg create Network_Function_Group \
  members:0=@nf \
  -- --id=@hc create Network_Function_Health_Check \
  interval=5 timeout=3 success_count=3 failure_count=3

# Привязка ACL к группе NF
ovn-nbctl acl-add sw0 from-lport 100 "ip4.tcp.dst_port=443" \
  allow-reload network_function_group=@nfg
```

## Дополнительная информация

### Диагностика и отладка (Экспертный уровень)

*   **Глубокая трассировка (`ofproto/trace`)**: Команда эмулирует прохождение пакета через конвейер таблиц OpenFlow. Критически важна для отладки OVN или Antrea.
    ```bash
    ovs-appctl ofproto/trace br-int in_port=1,dl_src=52:54:00:11:22:33,dl_dst=52:54:00:44:55:66
    ```
    **Вывод показывает:**
    - **Flow/Rule**: Конкретное правило, сработавшее в каждой таблице OpenFlow.
    - **OpenFlow actions**: Логические действия (resubmit в другую таблицу, изменение полей).
    - **Datapath actions**: Итоговое действие, переданное в ядро (например, `pop_vlan,output:3`).

*   **Анализ путей данных (`dpif/show`)**: Статистика интерфейсов и хитов кэша datapath (взаимодействие демона с ядром/DPDK).
    ```bash
    ovs-appctl dpif/show
    ```

*   **Управление маршрутами OVS (с v3.7.0)**:
    ```bash
    ovs-appctl ovs/route/show                    # Все маршруты
    ovs-appctl ovs/route/show table=10           # Маршруты из конкретной таблицы
    ovs-appctl ovs/route/lookup 10.0.0.1         # Lookup по IP
    ovs-appctl ovs/route/rule/show               # Правила маршрутизации
    ovs-appctl ovs/route/add 10.0.0.0/24 192.168.1.1 table=10  # Добавление
    ```

*   **Другие полезные команды**:
    ```bash
    ovs-appctl fdb/show br-int      # Просмотр таблицы MAC-адресов (FDB)
    ovs-ofctl dump-flows br-int     # Просмотр установленных правил OpenFlow
    ovs-dpctl dump-flows            # Просмотр реальных потоков в ядре (Datapath flows)
    ovs-appctl bond/show            # Состояние агрегированных каналов
    ovs-appctl coverage/show        # Счётчики покрытия (для отладки производительности)
    ```

*   **Визуализация потоков (`ovs-flowviz`, с v3.5.0)**:
    ```bash
    # Парсинг и визуализация OpenFlow-потоков
    ovs-ofctl dump-flows br-int | ovs-flowviz --format openflow
    ovs-dpctl dump-flows | ovs-flowviz --format datapath

    # Вывод в JSON
    ovs-ofctl dump-flows br-int | ovs-flowviz --format openflow --output json
    ```

### Типичные ошибки и решения

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| OVS не стартует | `ovs-vswitchd: dpdk_init failed` | `cat /proc/meminfo \| grep HugePages` | Проверьте HugePages; NIC должна быть на `vfio-pci` |
| Низкий throughput DPDK | < 50 Gbps на 100G-канале | `ovs-appctl dpif-netdev/pmd-rxq-show` | Увеличьте PMD-потоки; проверьте NUMA-локальность NIC и HugePages |
| PMD не видит порт | `dpdk-devargs` не распознаётся | `lspci \| grep Ethernet` | Убедитесь что драйвер — `vfio-pci`, а не `ixgbe`/`i40e` |
| Table-miss flood | Все пакеты на контроллере, CPU 100% | `ovs-ofctl dump-flows br-int \| grep "priority=0"` | Добавить `table-miss` entry с `actions=drop` или `actions=NORMAL` |
| Нет связи с контроллером | `ovs-vsctl show` → "not connected" | `ovs-vsctl get controller br-int target` | Проверить IP, firewall (6653/tcp), TLS-сертификаты |
| MAC flapping | Постоянные предупреждения в логах | `ovs-appctl fdb/show br-int` | Проверьте дублирование BR0/Bond0 или loopback через OVS |
| Conntrack丢了 пакеты | `ct_zone` промахи, latency | `ovs-appctl dpctl/ct-stats-show` | Увеличьте zone limit; проверьте `options:ct-commit-all` для LR |
| OVN-IC не учит маршруты | Interconnect-роутер не学习 | `ovn-ic-sbctl route-list` | Проверьте `ic-route-filter-adv/learn`, `ic-route-deny-adv/learn` (26.03+) |

### Полезные советы и хитрости

- **MTU и туннели**: При использовании VXLAN/Geneve всегда уменьшайте MTU на виртуальных интерфейсах ВМ (до **1450**), чтобы избежать фрагментации из-за 50-байтового оверхеда инкапсуляции.
- **Patch Ports**: Используйте `type=patch` для соединения двух мостов внутри одного OVS. Это работает быстрее, чем создание veth-пар.
- **Безопасность Control Plane**: При использовании внешних контроллеров или федерации OVN всегда настраивайте SSL/TLS для портов 6653 (OpenFlow) и 6641/6642 (OVSDB/OVN). TLSv1.0/1.1 deprecated с v3.5.0, удалены с v3.6.0. Используйте TLSv1.2+ (рекомендуется TLSv1.3). ovs-pki генерирует 3072-битные ключи по умолчанию (с v3.5.0).
- **Мониторинг БД**: `ovsdb-client monitor Open_vSwitch Bridge` позволяет в реальном времени следить за изменениями конфигурации.
- **Address Prefix Tracking**: Включено по умолчанию для IPv4+IPv6 (с v3.5.0). Значительно уменьшает количество datapath-потоков в смесянных средах.
- **Удалённые туннели**: LISP и STT удалены в v3.6.0. Используйте VXLAN (кастомный, порт 4789), Geneve (порты 6081) или GRE (порт 4789).
- **Очистка**: `ovs-vsctl del-br <bridge>` удалит мост со всеми портами. Для DPDK-моста верните NIC к стандартному драйверу: `dpdk-devbind.py --bind=<driver> <pci-addr>`.

### Сравнение с Linux Bridge

| Характеристика | Linux Bridge | Open vSwitch |
| :--- | :--- | :--- |
| **Реализация** | Целиком в ядре Linux | Гибридная (Kernel + Userspace) |
| **Управление** | `ip link`, `bridge` | `ovs-vsctl`, `ovs-ofctl`, `ovs-appctl` |
| **Поддержка SDN** | Нет | Полная (OpenFlow, OVN) |
| **Туннелирование** | Внешние устройства ОС | Встроенное в логику портов (VXLAN, Geneve, GRE) |
| **Производительность** | Высокая (kernel-only) | Экстремальная (с DPDK) |
| **QoS** | Ограничено `tc` | HTB, Rate Limiting через очереди OVS |
| **Bonding** | `mode=active-backup/balance-*` | `active-backup`, `balance-slb`, `balance-tcp` (LACP) |
| **Conntrack** | Ограниченная интеграция | Полная (stateful ACL, Zone limits) |
| **IPsec** | Ручная настройка `ip xfrm` | Встроенный IPsec-туннель (`type=ipsec`) |
| **Диагностика** | `bridge`, `tc`, `ip` | `ofproto/trace`, `dpif-show`, `flowviz` |
| **Сложность** | Низкая | Высокая |

### См. также

- **[Протокол OpenFlow](../Concepts/sdn/openflow.md)** — детальный разбор управления потоками.
- **[Обзор DPDK](../Concepts/dpdk/dpdk_overview.md)** — технология ускорения обработки пакетов.
- **[Linux Bridge: концепции](../../Linux/Networking/Concepts/linux_bridge.md)** — глубокое погружение в нативные мосты ядра.
- **[SDN Обзор](../Concepts/sdn/sdn_overview.md)** — архитектурная роль виртуальных коммутаторов.
