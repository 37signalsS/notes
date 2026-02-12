# SDN, OpenFlow и NetFlow

## Определения

**SDN (Software Defined Networking)** — это архитектурный подход к построению сетей, при котором плоскость управления (control plane) отделяется от плоскости передачи данных (data plane) и реализуется программно через централизованный контроллер.

**OpenFlow** — это протокол связи между плоскостью управления и передачи данных в SDN, позволяющий контроллеру управлять forwarding-таблицами сетевых устройств.

**NetFlow** — это технология сбора и анализа статистики IP-трафика, разработанная Cisco. Позволяет мониторить сетевой трафик для анализа, биллинга и безопасности.

## SDN (Software Defined Networking)

### Традиционная сетевая архитектура vs SDN

```
ТРАДИЦИОННАЯ АРХИТЕКТУРА:

┌─────────────────────────────────────────────────────────────┐
│                    МАРШРУТИЗАТОР 1                          │
│  ┌─────────────────────┐  ┌─────────────────────────────┐   │
│  │   Control Plane     │  │       Data Plane            │   │
│  │  - Routing protocols│  │  - Forwarding tables        │   │
│  │  - Forwarding logic │  │  - Packet processing        │   │
│  └─────────────────────┘  └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            
┌─────────────────────────────────────────────────────────────┐
│                    МАРШРУТИЗАТОР 2                          │
│  ┌─────────────────────┐  ┌─────────────────────────────┐   │
│  │   Control Plane     │  │       Data Plane            │   │
│  │  - Routing protocols│  │  - Forwarding tables        │   │
│  │  - Forwarding logic │  │  - Packet processing        │   │
│  └─────────────────────┘  └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

Проблемы:
- Распределенное управление
- Vendor-specific CLI
- Сложность автоматизации
- Медленное внедрение изменений
```

```
SDN АРХИТЕКТУРА:

┌─────────────────────────────────────────────────────────────┐
│              SDN CONTROLLER (Control Plane)                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  - Network-wide view                                  │
│  │  - Centralized control logic                          │
│  │  - Northbound API (REST/Python)                       │
│  │  - Southbound API (OpenFlow/NETCONF)                  │
│  └─────────────────────────────────────────────────────┘    │
└───────────────────────┬─────────────────────────────────────┘
                        │ OpenFlow / NETCONF / BGP-LS
        ┌───────────────┼───────────────┐
        │               │               │
┌───────▼───────┐ ┌─────▼─────┐ ┌───────▼───────┐
│    SWITCH 1   │ │  SWITCH 2 │ │    SWITCH 3   │
│  (Data Plane) │ │(Data Plane│ │  (Data Plane) │
│               │ │           │ │               │
│ - Flow tables │ │- Flow tbl │ │ - Flow tables │
│ - Forwarding  │ │- Forward  │ │ - Forwarding  │
└───────────────┘ └───────────┘ └───────────────┘

Преимущества:
- Централизованное управление
- Программируемость
- Vendor-agnostic
- Быстрая автоматизация
```

### Три уровня SDN архитектуры

**1. Application Layer (Слой приложений):**
- Network applications (firewall, load balancer, traffic engineering)
- Взаимодействуют с контроллером через Northbound API
- Примеры: ONOS applications, OpenDaylight apps

**2. Control Layer (Слой управления):**
- SDN Controller (мозг сети)
- Поддерживает глобальную топологию
- Рассчитывает маршруты
- Управляет политиками

**3. Infrastructure Layer (Слой инфраструктуры):**
- Сетевые устройства (switches, routers)
- Data plane — только forwarding
- Взаимодействуют с контроллером через Southbound API

### Southbound vs Northbound APIs

| API | Направление | Примеры | Назначение |
|-----|-------------|---------|------------|
| **Southbound** | Controller → Device | OpenFlow, NETCONF, PCEP, BGP-LS | Управление устройствами |
| **Northbound** | Application → Controller | REST API, Java/Python APIs | Разработка приложений |

## OpenFlow

### Принцип работы

OpenFlow — это первый стандартный протокол для SDN, разработанный ONF (Open Networking Foundation).

```
┌─────────────────────────────────────────────────────────────┐
│                    OPENFLOW SWITCH                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Flow Table (0)                         │    │
│  │  ┌───────────────────────────────────────────────┐  │    │
│  │  │ Match                    │ Action             │  │    │
│  │  ├──────────────────────────┼────────────────────┤  │    │
│  │  │ src_ip=10.0.0.0/24       │ output:port2       │  │    │
│  │  │ dst_port=80              │ output:controller  │  │    │
│  │  │ vlan=100                 │ set_field:vlan=200 │  │    │
│  │  └──────────────────────────┴────────────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
│                         ↓                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Flow Table (1)                         │    │
│  └─────────────────────────────────────────────────────┘    │
│                         ↓                                   │
│                    ...                                      │
└─────────────────────────────────────────────────────────────┘
```

### Flow Table Entry

```
┌─────────────────────────────────────────────────────────────┐
│                    FLOW ENTRY                               │
├─────────────────────────────────────────────────────────────┤
│ MATCH FIELDS (L2/L3/L4)          │ PRIORITY │ COUNTERS      │
│ - Ingress port                   │          │ - Byte count  │
│ - Packet headers (MAC/IP/TCP)    │          │ - Packet cnt  │
│ - Metadata                       │          │               │
├─────────────────────────────────────────────────────────────┤
│ INSTRUCTIONS                                                │
│ - Apply Actions: (output port, modify header, drop)         │
│ - Goto Table: (переход к следующей таблице)                 │
│ - Write Metadata                                            │
├─────────────────────────────────────────────────────────────┤
│ TIMEOUTS                                                    │
│ - Idle timeout (удалить если неактивен)                     │
│ - Hard timeout (удалить по истечении времени)               │
├─────────────────────────────────────────────────────────────┤
│ COOKIE (идентификатор для фильтрации)                       │
│ FLAGS                                                       │
└─────────────────────────────────────────────────────────────┘
```

### OpenFlow Actions

| Action | Описание |
|--------|----------|
| `output:port` | Отправить пакет на указанный порт |
| `drop` | Отбросить пакет |
| `set_field` | Изменить поле заголовка (MAC, IP, VLAN) |
| `push_vlan` | Добавить VLAN tag |
| `pop_vlan` | Удалить VLAN tag |
| `group` | Отправить в группу (для ECMP, multicast) |
| `meter` | Применить политику QoS |

### OpenFlow Messages

**Controller-to-Switch:**
- `Features` — получение возможностей switch
- `Config` — конфигурация switch
- `Modify-State` — добавление/удаление flow entries
- `Read-State` — чтение статистики
- `Send-Packet` — отправка пакета через switch
- `Barrier` — синхронизация

**Asynchronous (Switch-to-Controller):**
- `Packet-In` — неизвестный пакет (требуется решение)
- `Flow-Removed` — flow entry удален
- `Port-Status` — изменение статуса порта

### Пример работы OpenFlow

```
1. Первый пакет от Host A к Host B:
   
   Host A ──► OpenFlow Switch ──► Controller (Packet-In)
                                       │
                                       ▼
                              Controller изучает топологию
                              Устанавливает flow rules
                                       │
   Host A ◄────────────────────────────┘
         (Flow Mod: если dst=Host B → output port 2)

2. Последующие пакеты:
   
   Host A ──► OpenFlow Switch ──► Host B
              (совпадение flow rule,
               hardware forwarding)
```

## SDN Контроллеры

### Сравнение контроллеров

| Контроллер | Язык | Архитектура | Кластеризация | Лицензия | Примеры использования |
|------------|------|-------------|---------------|----------|---------------------|
| **ONOS** | Java | Модульная | Да (Raft) | Apache 2.0 | Телеком, крупные сети |
| **OpenDaylight** | Java | MD-SAL | Да | EPL 1.0 | Enterprise, NFV |
| **Ryu** | Python | Простая | Нет | Apache 2.0 | Исследования, небольшие сети |
| **Floodlight** | Java | Монолит | Нет | Apache 2.0 | Образование, PoC |
| **POX** | Python | Простая | Нет | Apache 2.0 | Образование, прототипы |
| **Tungsten Fabric** | Java | Масштабируемая | Да | Apache 2.0 | Cloud, OpenStack |

### ONOS (Open Network Operating System)

```java
// Пример приложения ONOS
@Component(immediate = true)
public class MyApp {
    
    @Reference(cardinality = ReferenceCardinality.MANDATORY)
    protected FlowRuleService flowRuleService;
    
    @Activate
    protected void activate() {
        // Создание flow rule
        TrafficSelector selector = DefaultTrafficSelector.builder()
            .matchEthType(Ethernet.TYPE_IPV4)
            .matchIPDst(IpPrefix.valueOf("10.0.0.0/24"))
            .build();
        
        TrafficTreatment treatment = DefaultTrafficTreatment.builder()
            .setOutput(PortNumber.portNumber(2))
            .build();
        
        FlowRule flowRule = DefaultFlowRule.builder()
            .forDevice(deviceId)
            .withSelector(selector)
            .withTreatment(treatment)
            .withPriority(50000)
            .makeTemporary(60)
            .build();
        
        flowRuleService.applyFlowRules(flowRule);
    }
}
```

### Ryu (Python)

```python
# Простой SDN контроллер на Ryu
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3

class SimpleHub(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Установить flow: flood все пакеты
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        
        self.add_flow(datapath, 0, match, actions)
    
    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority,
            match=match, instructions=inst)
        
        datapath.send_msg(mod)
```

## NetFlow

### Версии NetFlow

| Версия | Характеристики | Статус |
|--------|----------------|--------|
| **v1** | Первоначальная версия | Устарела |
| **v5** | Добавлены BGP AS, SNMP ifIndex | Широко используется |
| **v7** | Добавлена поддержка Catalyst | Cisco-specific |
| **v8** | Агрегация flow | Редко используется |
| **v9** | Шаблонная структура, flexible | Стандарт |
| **IPFIX** | IETF стандарт (v10) | Современный стандарт |

### NetFlow v5 Record

```
┌─────────────────────────────────────────────────────────────┐
│                  NETFLOW v5 RECORD                          │
├─────────────────────────────────────────────────────────────┤
│ src_ip          │ IP-адрес источника          │ 4 bytes     │
│ dst_ip          │ IP-адрес назначения         │ 4 bytes     │
│ next_hop        │ IP следующего хопа          │ 4 bytes     │
│ input           │ SNMP index input interface  │ 2 bytes     │
│ output          │ SNMP index output interface │ 2 bytes     │
│ dPkts           │ Количество пакетов          │ 4 bytes     │
│ dOctets         │ Количество байт             │ 4 bytes     │
│ First           │ SysUptime первого пакета    │ 4 bytes     │
│ Last            │ SysUptime последнего пакета │ 4 bytes     │
│ src_port        │ Порт источника              │ 2 bytes     │
│ dst_port        │ Порт назначения             │ 2 bytes     │
│ tcp_flags       │ TCP флаги                   │ 1 byte      │
│ prot            │ Протокол (TCP=6, UDP=17)    │ 1 byte      │
│ tos             │ Type of Service             │ 1 byte      │
│ src_as          │ AS источника                │ 2 bytes     │
│ dst_as          │ AS назначения               │ 2 bytes     │
│ src_mask        │ Маска сети источника        │ 1 byte      │
│ dst_mask        │ Маска сети назначения       │ 1 byte      │
└─────────────────────────────────────────────────────────────┘
```

### Как работает NetFlow

```
1. PACKET SAMPLING (опционально)
   ┌─────────────┐
   │   1:100     │  ← Не все пакеты анализируются
   │  sampling   │
   └──────┬──────┘
          │
2. FLOW CACHE
   ┌──────▼──────┐
   │  Flow 1:    │
   │ 192.168.1.1:443 → 10.0.0.5:12345
   │  Packets: 100, Bytes: 150000
   │  Start: 10:00:00, End: 10:00:15
   └─────────────┘
          │
3. ACTIVE/INACTIVE TIMEOUT
   ┌──────▼──────┐
   │ Flow expired│  (по времени или FIN/RST)
   └──────┬──────┘
          │
4. EXPORT TO COLLECTOR
   ┌──────▼──────┐
   │ NetFlow     │  ──► Collector (nfdump, Flowmon)
   │ Exporter    │      Анализ и визуализация
   └─────────────┘
```

### Настройка NetFlow на Cisco

```cisco
! Включение NetFlow на интерфейсе
interface GigabitEthernet0/0
 ip flow ingress
 ip flow egress

! Настройка экспорта
ip flow-export version 5
ip flow-export destination 192.168.1.100 2055
ip flow-export source Loopback0

! Настройка таймаутов
ip flow-cache timeout active 1
ip flow-cache timeout inactive 15

! Проверка
show ip cache flow
show ip flow export
```

### NetFlow Collector

```bash
# nfdump - популярный open-source collector

# Прослушивание NetFlow
nfcapd -w -D -l /var/log/nfdump -p 2055

# Анализ собранных данных
nfdump -r /var/log/nfdump/nfcapd.202401011200 \
    -s srcip/bytes \
    -o "fmt:%ts %sa %da %sp %dp %pkt %byt"

# Фильтрация
nfdump -r nfcapd.current -s record \
    'proto tcp and dst port 443 and bytes > 1000000'
```

## Практические сценарии

### Сценарий 1: Простой SDN коммутатор

```python
# Mininet + Ryu: создание SDN сети
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI

net = Mininet(controller=RemoteController)
net.addController('c0', ip='127.0.0.1', port=6633)

# Добавление хостов и свитчей
h1 = net.addHost('h1')
h2 = net.addHost('h2')
s1 = net.addSwitch('s1')

# Соединения
net.addLink(h1, s1)
net.addLink(h2, s1)

net.start()
CLI(net)
net.stop()
```

### Сценарий 2: Load Balancer с OpenFlow

```python
# Ryu app: простой L4 load balancer
class LoadBalancer(app_manager.RyuApp):
    virtual_ip = '10.0.0.100'
    servers = ['10.0.0.1', '10.0.0.2', '10.0.0.3']
    
    @set_ev_cls(ofp_event.EventOFPPacketIn)
    def packet_in_handler(self, ev):
        pkt = packet.Packet(ev.msg.data)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        
        if ip_pkt and ip_pkt.dst == self.virtual_ip:
            # Выбор сервера (round-robin)
            server = self.select_server()
            
            # Установить flow для forwarding
            self.install_lb_flow(ev.msg.datapath, 
                               ip_pkt.src, server)
```

### Сценарий 3: NetFlow для мониторинга DDoS

```bash
# Обнаружение аномалий с помощью nfdump
nfdump -r nfcapd.current -s srcip/packets \
    -n 20 -o csv | awk -F',' '
    NR>1 {if ($3 > 100000) print $1, $3}'

# Автоматическая блокировка при превышении порога
#!/bin/bash
THRESHOLD=1000000
TOP_TALKERS=$(nfdump -r nfcapd.current -s srcip/bytes -n 5)

while read -r line; do
    BYTES=$(echo $line | awk '{print $NF}')
    IP=$(echo $line | awk '{print $1}')
    
    if [ "$BYTES" -gt "$THRESHOLD" ]; then
        iptables -A INPUT -s $IP -j DROP
        echo "Blocked $IP: $BYTES bytes"
    fi
done <<< "$TOP_TALKERS"
```

## Дополнительная информация

- [Open Networking Foundation (ONF)](https://opennetworking.org/)
- [OpenFlow Specification](https://opennetworking.org/software-defined-standards/specifications/)
- [ONOS Documentation](https://wiki.onosproject.org/)
- [Ryu SDN Framework](https://ryu-sdn.org/)
- [nfdump Documentation](https://github.com/phaag/nfdump)
