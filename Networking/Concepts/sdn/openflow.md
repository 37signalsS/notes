## Определения

- **OpenFlow**: Стандартизированный протокол связи между уровнем управления (**Control Plane** — SDN-контроллер) и уровнем инфраструктуры (**Data Plane** — сетевой коммутатор). Позволяет контроллеру удаленно программировать логику обработки пакетов через абстракцию таблиц потоков.
- **Southbound API**: Интерфейс "южного направления", через который контроллер взаимодействует с сетевым оборудованием. OpenFlow является наиболее известным примером этого интерфейса.
- **Flow Table (Таблица потоков)**: Набор правил (Flow Entries) на коммутаторе. Современные спецификации поддерживают конвейерную обработку (Pipeline) через множество таблиц.
- **Match Fields (Поля сопоставления)**: Набор заголовков пакета (L2-L4, метаданные, входной порт), по которым происходит поиск правила в таблице.
- **Instructions & Actions**: Инструкции определяют, что делать с пакетом (изменить заголовки, отправить в порт, перейти к другой таблице или отбросить).
- **TCAM (Ternary Content-Addressable Memory)**: Специализированная высокоскоростная память в аппаратных коммутаторах, используемая для хранения таблиц потоков OpenFlow. Позволяет выполнять поиск по шаблонам с масками (wildcards).
- **Controller (Контроллер)**: Централизованное управление, принимающее решения о маршрутизации и сетевой политике. Отправляет команды коммутатору через OpenFlow-канал.
- **Switch (Коммутатор)**: Устройство или программа (например, OVS), реализующая Data Plane и обрабатывающая пакеты согласно таблицам потоков, установленным контроллером.
- **Packet-In**: Сообщение, отправляемое коммутатором контроллеру, когда пакет не нашел подходящего правила в таблице (table-miss) или когда правило предписывает отправить пакет на контроллер. Используется для принятия решений в **реактивном** режиме.
- **Packet-Out**: Сообщение, отправляемое контроллером коммутатору для передачи конкретного пакета через указанный порт. Используется совместно с Packet-In для ответа на нерешенные потоки.
- **Flow-Mod**: Сообщение контроллера для управления таблицами потоков: добавление (`ADD`), изменение (`MODIFY`) или удаление (`DELETE`) правил. Основной механизм программирования Data Plane.
- **Group-Mod**: Сообщение для управления таблицами групп (Group Table). Позволяет реализовывать multicast, load-balancing (ECMP) и fast failover.
- **Meter-Mod**: Сообщение для управления таблицами метров (Meter Table). Реализует QoS: ограничение скорости (rate-limiting) и перекрашивание меток (DSCP remarking).
- **Barrier**: Сообщение для синхронизации: коммутатор подтверждает, что все предыдущие команды применены. Критично для атомарных транзакций.
- **Role**: Роль контроллера на коммутаторе — `MASTER` (полный контроль), `SLAVE` (только чтение) или `EQUAL` (равноправие). Используется для отказоустойчивости (HA).
- **Bundle**: Механизм атомарного применения нескольких команд (Flow-Mod + Group-Mod) одновременно. Предотвращает "петли" и дыры в безопасности при обновлении топологии.

---

## Основные концепции

### История версий OpenFlow

| Версия | Год | Ключевые изменения | Статус (2026) |
| :--- | :--- | :--- | :--- |
| **1.0** | 2009 | Базовая спецификация: 1 таблица, фиксированные match fields, простые actions. | Legacy (не рекомендуется). |
| **1.1** | 2011 | Мульти-таблицы (.pipeline), Groups, Meters. Улучшенная поддержка VLAN/MPLS. | Редко используется. |
| **1.2** | 2011 | IPv6, расширенные match fields (tunnel ID, metadata). | Редко используется. |
| **1.3** | 2012 | **Стандарт de facto**: Bundles, controller reputations, eviction, виртуальные порты, extensible match (OXM). | **Рекомендуется для нового оборудования.** |
| **1.4** | 2013 | Bundle Conditions, логические порты, auxiliary connections (TLS). | Поддерживается современными контроллерами. |
| **1.5** | 1.5 | Hierarchical Flow Tables, виртуальные порты (进一步扩展),ichtet bundles. | Редко используется в продакшене. |

**Рекомендация 2026:** Используйте **OpenFlow 1.3** как минимально поддерживаемую версию. Все современные контроллеры (ONOS, OpenDaylight, Floodlight) и коммутаторы (OVS, Cisco Nexus) поддерживают 1.3. Версия 1.0 считается устаревшей из-за отсутствия Groups, Meters и мульти-таблиц.

### Жизненный цикл соединения (Handshake)

Связь между коммутатором и контроллером обычно устанавливается по TCP (порт 6653) или TLS.

1.  **OFPT_HELLO**: Обмен версиями протокола. Выбирается наивысшая общая версия.
2.  **OFPT_FEATURES_REQUEST**: Контроллер запрашивает возможности коммутатора (количество таблиц, поддерживаемые действия).
3.  **OFPT_FEATURES_REPLY**: Коммутатор отвечает: DPID (datapath ID), число таблиц, capabilities (flow statistics, port statistics, table statistics), supported actions.
4.  **Config**: Контроллер устанавливает параметры (например, фрагментация, размер сообщений Packet-In).
5.  **Keep-alive**: Регулярный обмен сообщениями `Echo Request/Reply` для проверки жизнеспособности канала. Таймаут по умолчанию: 60 секунд.
6.  **Barrier Request/Reply**: Синхронизация после инициализации. Контроллер убеждается, что коммутатор готов к приему команд.

**Примечание:** С openflow 1.3+ поддерживается **Role Request** для HA: контроллер может запросить роль `MASTER` или `SLAVE`. При падении MASTER-контроллера SLAVE автоматически переключается (если настроен).

### Таблицы сообщений OpenFlow

**Controller-to-Switch (управление):**

| Сообщение | Назначение | Пример использования |
| :--- | :--- | :--- |
| **OFPT_FEATURES_REQUEST** | Запрос возможностей коммутатора | Инициализация соединения. |
| **OFPT_CONFIG** | Установка параметров | Максимальный размер Packet-In, фрагментация. |
| **OFPT_FLOW_MOD** | Управление таблицами потоков | Добавление, изменение, удаление правил. |
| **OFPT_GROUP_MOD** | Управление таблицами групп | Создание multicast-группы или failover. |
| **OFPT_METER_MOD** | Управление таблицами метров | Настройка rate-limiting. |
| **OFPT_PORT_MOD** | Изменение состояния порта | Включение/отключение порта, изменение speed. |
| **OFPT_BARRIER_REQUEST** | Запрос подтверждения | Синхронизация перед критическими операциями. |
| **OFPT_ROLE_REQUEST** | Запрос роли контроллера | Переключение MASTER→SLAVE при отказе. |
| **OFPT_MULTIPART_REQUEST** | Запрос статистики/состояния | Сбор flow stats, port stats, table stats. |

**Async (асинхронные, от коммутатора):**

| Сообщение | Назначение | Пример использования |
| :--- | :--- | :--- |
| **OFPT_PACKET_IN** | Пакет не обработан | Table-miss, или правило `controller`. |
| **OFPT_FLOW_REMOVED** | Поток удален из таблицы | Таймаут неактивности, удаление контроллером. |
| **OFPT_PORT_STATUS** | Изменение состояния порта | Link down/up, speed change. |
| **OFPT_ERROR** | Ошибка обработки | Bad version, bad command, flow mod failed. |

**Multipart (статистика):**

| Тип | Назначение | Данные |
| :--- | :--- | :--- |
| **OFPMP_FLOW** | Статистика по потокам | Packets, bytes, duration, priority, timeout. |
| **OFPMP_AGGREGATE** | Агрегированная статистика | Суммарные packets/bytes/flows для набора правил. |
| **OFPMP_TABLE** | Статистика по таблицам** | Количество потоков, lookup/overflow counters. |
| **OFPMP_PORT** | Статистика по портам** | TX/RX packets/bytes, errors, drops. |
| **OFPMP_QUEUE** | Статистика по очередям** | Очереди QoS: bytes/packets в очереди. |

### Конвейерная обработка (Pipeline Processing)

Пакет всегда начинает обработку с Таблицы 0.
- **Table-miss**: Если ни одно правило не подошло, срабатывает `table-miss entry`. По умолчанию она может:
    - Отбросить пакет (Drop).
    - Передать пакет следующей таблице.
    - Отправить пакет на контроллер (`OFPT_PACKET_IN`).
- **Goto-Table**: Инструкция для перехода к таблице с большим номером (движение по конвейеру только вперед). Нельзя вернуться в предыдущую таблицу.
- **Metadata**: 64-битный регистр, который пакет "несет" с собой между таблицами, позволяя сохранять результат промежуточных проверок.
- **Write Metadata**: Инструкция для записи значения в metadata-регистр (используется для передачи результатов между таблицами, например, результат ACL-проверки).

**Пример конвейера (3 таблицы):**
```
Пакет → Таблица 0 (MAC Learning) → Write Metadata → Таблица 1 (L3 Routing) → Goto-Table 2 → Таблица 2 (ACL/QoS) → Output
```

### Группы и Метры (v1.1+)

- **Group Table**: Позволяет применять одно действие к набору потоков или реализовывать сложную логику:
    - `All`: Мультикаст/Зеркалирование (replicate пакет на несколько портов).
    - `Select`: Балансировка нагрузки (ECMP) — хэш выбирает один из bucket'ов.
    - `Fast Failover`: Мгновенное переключение на резервный порт при падении линка. Каждый bucket привязан к порту; если порт down, выбирается следующий live bucket.
    - `Indirect`: Общая action группа (одна bucket), используется для application-level load balancing.
- **Meter Table**: Ограничение скорости (QoS). Позволяет "резать" трафик (Drop) или перекрашивать (Remark DSCP) при превышении заданных лимитов (Bands):
    - **Rate bands**: Каждый meter может иметь несколько bands с разными rate/burst. При превышении rate трафик попадает в соответствующий band (например, "drop" или "remark DSCP down").
    - **Controller band**: При превышении rate пакет отправляется на контроллер (для динамической обработки).
    - **Burst**: Краткосрочное превышение rate без Drop (для bursty traffic). Важно настраивать burst=rate/10 для стабильности.

### Атомарность и Bundles (v1.3)

Механизм **Bundles** позволяет контроллеру группировать несколько изменений (`Flow-Mod`, `Group-Mod`, `Meter-Mod`) в одну транзакцию. Коммутатор применяет их все сразу или не применяет вовсе, что критично для предотвращения "петель" или дыр в безопасности во время обновления топологии.

**Этапы Bundle:**
1. `OFPT_BUNDLE_ADD_MESSAGE` (одно или несколько) — добавление команд в bundle.
2. `OFPT_BUNDLE_REQUEST` (commit) — коммутатор применяет все команды атомарно.
3. `OFPT_BUNDLE_REPLY` — подтверждение успеха или ошибки.

**Edge case:** Если bundle содержит конфликтующие команды (например, два `Flow-Mod` с одинаковым match, но разными actions), коммутатор откатывает все изменения.

### Proactive vs Reactive Flow Installation

| Модель | Описание | Преимущество | Недостаток |
| :--- | :--- | :--- | :--- |
| **Reactive** | Контроллер устанавливает правила только после Packet-In (пакет не найден в таблице). | Простота, экономия TCAM. | Латентность 1-5 мс на каждый новый поток; Packet-In storm при большом числе новых flow. |
| **Proactive** | Контроллер устанавливает правила заранее (до появления трафика). | Нулевая задержка для первого пакета; нет Packet-In. | Расход TCAM на все возможные потоки; сложно поддерживать. |
| **Hybrid** | Базовые правила proactive (routing, ACL), динамические — reactive (new flows). | Баланс производительности и гибкости. | Сложнее в реализации. |

**Когда использовать reactive:**
- Динамические среды (Kubernetes, cloud), где поды постоянно появляются/исчезают.
- Discovery новых сервисов (controller автоматически определяет маршруты).
- Небольшое количество TCAM (ограниченные ресурсы).

**Когда использовать proactive:**
- Production сети с известными service patterns.
- Критические сервиси (VoIP, video) где latency критична.
- Крупные сети (>1000 узлов) где Packet-In storm невозможен.

**В modern SDN (OVN, Cilium):** Используется **proactive flow installation** для baseline rules (routing, ACL) + reactive для dynamic adjustments (new pods, service changes). OVN транслирует логические правила в thousands of OpenFlow flows proactive.

**Пример reactive flow (OVN):**
```bash
# OVN устанавливает rules reactive для нового pod
ovn-nbctl lsp-add ls-web pod1
# → OVN NB controller транслирует логические правила в OpenFlow
# → OVS получает new flows через OpenFlow channel

# Просмотр reactive flows
ovs-ofctl dump-flows br-int | grep "cookie=0x0"
# → cookie=0x0, table=0, priority=100,... actions=...
```

**Пример proactive flow (manual):**
```bash
# Ручная установка proactive rules
ovs-ofctl add-flow br-int "priority=100,ip,nw_dst=10.0.0.0/24,actions=output:1"
# → Правило установлено ДО появления трафика
# → Первый пакет обрабатывается без Packet-In
```

---

## Практические сценарии

### Сценарий 1: Управление потоками через `ovs-ofctl`

Утилита `ovs-ofctl` — основной инструмент для ручного управления и отладки OpenFlow на OVS.

```bash
# Просмотр возможностей коммутатора
ovs-ofctl -O OpenFlow13 show br-int
# → features reply: datapath-id=..., n_tables=255, n_buffers=256
# → capabilities: flow_statistics port_statistics table_statistics

# Добавление правила: перенаправить трафик с порта 1 на порт 2 (L2)
ovs-ofctl add-flow br-int "priority=100,in_port=1,actions=output:2"

# Добавление правила для конкретного IP (L3) с изменением заголовка
ovs-ofctl add-flow br-int "priority=200,ip,nw_dst=10.0.0.1,actions=mod_dl_dst:00:11:22:33:44:55,output:3"

# Добавление правила с VLAN tag (802.1Q)
ovs-ofctl add-flow br-int "priority=150,dl_vlan=100,actions=strip_vlan,output:2"

# Добавление правила с MPLS label
ovs-ofctl add-flow br-int "priority=150,mpls,actions=pop_mpls:0x0800,output:2"

# Удаление всех правил
ovs-ofctl del-flows br-int

# Удаление правил, соответствующих конкретному match
ovs-ofctl del-flows br-int "ip,nw_dst=10.0.0.1"

# Просмотр установленных правил
ovs-ofctl dump-flows br-int
# → cookie=0x0, duration=12.5s, table=0, n_packets=450, n_bytes=67500, priority=100,in_port=1 actions=output:2
```

### Сценарий 2: Управление портами

```bash
# Просмотр портов коммутатора
ovs-ofctl show br-int
# → port 1: eth0 (addr=00:11:22:33:44:55)
# → port 2: veth0 (addr=aa:bb:cc:dd:ee:ff)
# → port LOCAL: br-int (addr=00:11:22:33:44:55)

# Добавление виртуального порта (patch port для OVN/Antrea)
ovs-vsctl add-port br-int patch-ovn -- set interface patch-ovn type=patch options:peer=patch-host

# Включение/отключение порта (аналог shutdown/no shutdown)
ovs-ofctl mod-port br-int eth0 down
ovs-ofctl mod-port br-int eth0 up

# Установка скорости порта (для корректной работы QoS)
ovs-vsctl set interface eth0 options:link_speed=10000

# Просмотр статистики портов
ovs-ofctl dump-ports br-int
# → port 1: rx pkts=12345 bytes=1851750 tx pkts=12000 bytes=1800000
# → port 2: rx pkts=12000 bytes=1800000 tx pkts=12345 bytes=1851750
```

### Сценарий 3: Управление группами (Groups)

```bash
# Создание группы All (зеркалирование на 2 порта)
ovs-ofctl add-group br-int "group_id=1,type=all,bucket=output:2,bucket=output:3"

# Создание группы Select (ECMP между 3 путями)
ovs-ofctl add-group br-int "group_id=2,type=select,bucket=output:2,weight:50,bucket=output:3,weight:30,bucket=output:4,weight:20"

# Создание группы Fast Failover (основной + резервный порт)
ovs-ofctl add-group br-int "group_id=3,type=fast_failover,bucket=watch_port:2,output:2,bucket=watch_port:3,output:3"

# Просмотр групп
ovs-ofctl dump-groups br-int

# Привязка потока к группе
ovs-ofctl add-flow br-int "priority=100,ip,actions=group:2"
```

### Сценарий 4: Управление метрами (QoS)

```bash
# Создание метра с двумя bands: rate-limit 100Mbps + remark DSCP
ovs-ofctl meter br-int "meter_id=1,band=type=drop,rate=100000,band=type=dscp_remark,rate=80000,prec=1"

# Привязка метра к порту (ограничение исходящего трафика)
ovs-ofctl add-flow br-int "priority=100,in_port=1,actions=meter:1,output:2"

# Просмотр статистики метров
ovs-ofctl dump-meters br-int

# Просмотр band counters
ovs-ofctl meter-stats br-int
```

### Сценарий 5: Глубокая трассировка (`ofproto/trace`)

Команда эмулирует прохождение пакета через конвейер таблиц OpenFlow. Критически важна для отладки OVN или Antrea.

```bash
# Эмуляция прохождения TCP-пакета
ovs-appctl ofproto/trace br-int in_port=1,dl_type=0x0800,nw_src=10.0.0.1,nw_dst=10.0.0.2,nw_proto=6,tp_dst=80

# → Flow: tcp,in_port=1,vlan_tci=0x0000,dl_src=00:00:00:00:00:00,dl_dst=00:00:00:00:00:00,nw_src=10.0.0.1,nw_dst=10.0.0.2,nw_tos=0,nw_ecn=0,nw_ttl=64,tp_src=0,tp_dst=80,tcp_flags=0x002
# → Rule: table=0, priority=200,ip,nw_dst=10.0.0.1 actions=mod_dl_dst:00:11:22:33:44:55,output:3
# → Resubmit: table=1, in_port=1
# → Final: output:3

# Эмуляция с MPLS (проверка pop/push)
ovs-appctl ofproto/trace br-int in_port=1,dl_type=0x8847,mpls_label=100,mpls_ttl=64

# Эмуляция table-miss (проверка, что table-miss entry работает)
ovs-appctl ofproto/trace br-int in_port=1,dl_type=0x0800,nw_src=10.99.99.1,nw_dst=10.99.99.2
# → Rule: table=0, priority=0 actions=controller
```

### Сценарий 6: Мультиверендорные команды

**Cisco NX-OS (Nexus 9000):**
```cisco
! Настройка OpenFlow-контроллера
feature openflow

openflow
  switch global
    openflow-switch feature-set f1
    controller <CONTROLLER_IP> local-port 6653
    no shutdown

! Просмотр состояния
show openflow switch
show openflow flow-table summary
show openflow group-table summary
```

**Cisco IOS-XE (Catalyst 9000):**
```cisco
! Включение SD-Access и OpenFlow
sdaccess fabric control-plane auto
openflow
  switch 1
    controller <CONTROLLER_IP> 6653
    no shutdown

! Просмотр
show openflow switch 1
show openflow switch 1 flow-table
```

**Juniper Junos:**
```junos
# Настройка OpenFlow на Juniper
set protocols openflow switch switch1 bridge bridge1
set protocols openflow switch switch1 controller <CONTROLLER_IP> port 6653
set protocols openflow switch switch1 controller <CONTROLLER_IP> protocol tcp
set protocols openflow switch switch1 datapath-id 00:00:00:00:00:01

# Просмотр
show openflow switch
show openflow flow-table
show openflow group-table
```

### Сценарий 7: Интеграция с OVN (Kubernetes)

В OVN/Kubernetes OpenFlow используется трансляцией логических правил в физические:

```bash
# Просмотр OpenFlow-правил OVN
ovn-nbctl show
# → switch sw0 (UUID: ...)
# →   port sw0-port1 ... (logical port: pod1)

# Просмотр соответствующих OpenFlow-правил в OVS
ovs-ofctl dump-flows br-int | grep "cookie=0x0"
# → cookie=0x0, table=0, priority=100,ip,in_port=patch-ovn ...
# → cookie=0x0, table=0, priority=0,actions=NORMAL

# Эмуляция прохождения пакета через OVN-конвейер
ovn-trace sw0 'inport == "pod1" && ip.dst == 10.244.1.5 && tcp.dst_port == 80'
# → table=0 (ls_in_port_sec_l2): inport == "pod1" => accept;
# → table=8 (ls_in_acl): ip && tcp => verdict=allow;
# → table=10 (ls_in_l2_lkup): eth.dst == 00:11:22:33:44:55 => output;

# Проверка OpenFlow-правил, соответствующих OVN-трасе
ovs-appctl ofproto/trace br-int in_port=patch-ovn,dl_type=0x0800,nw_src=10.244.0.5,nw_dst=10.244.1.5,nw_proto=6,tp_dst=80
```

---

## Безопасность и ограничения

### Риски Control Plane

1.  **Насыщение канала (Packet-In Flooding)**: Злоумышленник генерирует трафик, не попадающий под правила, заставляя коммутатор бомбардировать контроллер запросами. Решение: `Rate-limiting` на коммутаторе (например, `set interface eth0 ingress_policing_rate=100000` в OVS) или `max_backoff` в конфигурации контроллера.
2.  **Переполнение таблиц (Flow Table Overflow)**: Ресурс TCAM ограничен (обычно несколько тысяч правил). Заполнение таблиц "мусорными" правилами блокирует установку легитимных соединений. Решение: `idle-timeout` на правилах, мониторинг через `OFPMP_TABLE`, rate-limiting Packet-In.
3.  **Атаки на канал**: Без использования TLS (порт 6653 вместо 6633) злоумышленник может перехватить управление коммутатором. Решение: всегда используйте TLS с сертификатами (OVS поддерживает `pssl:` в `ovsdb-server`).
4.  **Replay-атаки**: Злоумышленник перехватывает и повторно отправляет легитимные Flow-Mod команды. Решение: использовать Role Request (master/slave) и мониторить `OFPT_ERROR` на контроллере.
5.  **Controller impersonation**: Злоумышленник подключается к коммутатору как "второй контроллер". Решение: TLS + проверка certificate CN (Common Name) на коммутаторе.

### Проблемы производительности

- **Flow Setup Latency**: Реактивная модель (запрос контроллера на каждый новый поток) вносит задержку (обычно 1-5 мс на запрос Packet-In → Packet-Out). В современных сетях чаще используется **Proactive Flow Entry** (установка правил заранее) для критических сервисов.
- **TCAM exhaustion**: На аппаратных коммутаторах TCAM ограничен (обычно 1K-100K записей). При использовании wildcards каждое правило может занимать несколько TCAM-слотов. Решение: агрессивное использование `priority` и `idle-timeout`, мониторинг через `table features`.
- **CPU overhead в программных коммутаторах (OVS)**: При большом количестве правил (>100K) search time увеличивается. Решение: hardware offload на SmartNIC (DPDK/TC offload).

### Troubleshooting

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Нет связи с контроллером** | `ovs-vsctl show` → "not connected", потоки table-miss | `ovs-vsctl get controller br-int target`; `tcpdump -i any port 6653` | Проверить IP контроллера, firewall (6653/tcp), TLS certificates. |
| **Table-miss flood** | Все пакеты отправляются на контроллер, CPU на контроллере 100% | `ovs-ofctl dump-flows br-int \| grep "priority=0"` | Добавить `table-miss` entry с `actions=drop` или `actions=NORMAL`. |
| **Flow-Mod rejected** | `OFPT_ERROR` в логах контроллера | `ovs-appctl vlog/set ofproto:dbg` | Проверить версию протокола, доступные capabilities, корректность match fields. |
| **Slow convergence при failover** | После падения контроллера сетевые сессии зависают на 30-60 сек | Проверить `Role Request` и `Fast Failover` groups | Настроить `idle-timeout` короче (например, 10 сек) или использовать `proactive` rules. |
| **Bundles не применяются** | Часть правил работает, часть нет (нет атомарности) | `ovs-appctl bundle/show` | Убедиться, что все команды в bundle отправлены до `BUNDLE_REQUEST`. |

---

## Современный ландшафт (2025–2026)

### OpenFlow в Kubernetes: Antrea и OVN

В Cloud Native средах OpenFlow переживает "второе дыхание":
- **Antrea**: Использует OpenFlow для реализации сетевых политик, маршрутизации и балансировки (Service Load Balancing) внутри узла K8s через OVS.
- **OVN-Kubernetes**: Транслирует высокоуровневые логические правила в тысячи потоков OpenFlow, обеспечивая виртуализацию сети для огромных кластеров.

**Ключевое отличие OVN от Antrea:** OVN строит двухуровневую модель (logical → physical), где тысячи логических правил транслируются в сотни OpenFlow-правил на каждом узле. Antrea работает напрямую с OpenFlow без промежуточного слоя.

### OpenFlow vs P4Runtime

- **OpenFlow**: Работает с "фиксированным" набором полей (Ethernet, IP, TCP и т.д.). Сложно расширять для новых протоколов.
- **P4/P4Runtime**: Позволяет программисту самому определять формат пакета. OpenFlow все чаще рассматривается как высокоуровневый агент поверх P4-оборудования (**Stratum**).

**Гибридный подход (2026):** P4Runtime используется на低уровне (SmartNIC/DPU), а OpenFlow — на уровнеOverlay (VXLAN, Geneve) для управления логикой маршрутизации и политик.

### Аппаратное ускорение (SmartNICs)

Для снижения нагрузки на CPU хоста потоки OpenFlow переносятся (offload) на сетевые карты с поддержкой **eBPF** или **FPGA/ASIC**. Это позволяет программным решениям (OVS) работать на скоростях 100G/200G.

**Механизмы offload:**
- **TC Flower Offload:** Ядро Linux передает match+action из OVS в аппаратуру через `tc flower`.
- **DPDK Tested:** OVS с DPDK может использовать hardware offload через `ovsdpdk` для NIC с поддержкой DPDK.
- **eBPF Offload:** Для динамических правил (Kubernetes NetworkPolicy) eBPF-программы загружаются в ядро без перекомпиляции.

**Ограничения offload:**
- Wildcard-правила (например, `nw_dst=10.0.0.0/8`) могут не поддерживаться аппаратно (TCAM limited).
- Actions `mod_dl_src/dst` и `push_vlan` могут не offload'иться на все NIC.

---

## Дополнительная информация

**Порты OpenFlow:**
- **6633**: Исторический порт (OpenFlow 1.0-1.2). Устарел.
- **6653**: Текущий стандартный порт (OpenFlow 1.3+).
- **6640**: OVSDB management (не OpenFlow).

**Связанные темы:**
- **[Обзор SDN](./sdn_overview.md)** — архитектурный контекст.
- **[eBPF/XDP](./ebpf_xdp.md)** — современная альтернатива OpenFlow (eBPF-based Data Plane).
- **[VXLAN/Geneve (Overlay Networks)](./vxlan_geneve.md)** — VXLAN/Geneve overlay с OpenFlow.
- **[BGP EVPN](./bgp_evpn.md)** — control-plane learning для VXLAN (замена flood-and-learn).
- **[Open vSwitch (OVS)](../../ServicesAndTools/open_vswitch.md)** — программная реализация OpenFlow-коммутатора и OVN.
- **[NetFlow/IPFIX](./netflow.md)** — мониторинг потоков (в отличие от OpenFlow, который ими управляет).
- **[P4 и программируемость данных](./sdn_overview.md#программируемость-данных-ebpf-и-p4)** — следующий этап эволюции SDN.
- **[Kubernetes CNI](./kubernetes_cni.md)** — CNI-плагины на базе OpenFlow (Antrea, OVN).
- **[eBPF и Cilium](../../../Kubernetes/Networking/Network/CNI/cilium.md)** — современная альтернатива OpenFlow для управления сетевыми политиками в Kubernetes.
