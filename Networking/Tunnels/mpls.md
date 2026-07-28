# MPLS (Multiprotocol Label Switching) — коммутация по меткам

## Определения

**MPLS (Multiprotocol Label Switching)** — технология высокопроизводительной передачи данных, работающая на уровне L2.5 (между канальным и сетевым уровнями). Вместо анализа IP-заголовков на каждом узле, MPLS использует короткие фиксированные метки (labels) для принятия решений о пересылке.

**LSR (Label Switching Router)** — маршрутизатор, поддерживающий MPLS.
- **Ingress LER (Label Edge Router):** Входной узел, который классифицирует IP-пакет и накладывает (Push) MPLS-метку.
- **Transit LSR (P-Router):** Промежуточный узел, который выполняет замену (Swap) входящей метки на исходящую.
- **Egress LER:** Выходной узел, который снимает (Pop) последнюю метку и передает IP-пакет получателю.

**LSP (Label Switched Path)** — однонаправленный виртуальный путь через MPLS-сеть.

**FEC (Forwarding Equivalence Class)** — группа пакетов (например, с общим IP-префиксом или QoS-параметрами), которые обрабатываются одинаково и получают одну и ту же метку.

**PHP (Penultimate Hop Popping)** — оптимизация, при которой предпоследний LSR снимает метку, чтобы выходной LER (Egress) не выполнял двойной поиск (в таблице меток и таблице маршрутизации).

**Shim Header** — заголовок MPLS размером 4 байта, вставляемый между заголовками L2 и L3. Содержит 20-битную метку, 3 бита Traffic Class (QoS), 1 бит S (Bottom of Stack) и 8 бит TTL.

> **См. также:** [VXLAN](./vxlan.md) — оверлейная сеть L3, [Туннели: обзор](./tunneling_overview.md)

## Основные концепции

### Архитектура MPLS

1.  **Control Plane (Плоскость управления):** Отвечает за обмен информацией о маршрутах и распределение меток.
    - **LDP (Label Distribution Protocol):** Основной протокол для автоматического распределения меток на основе IGP (OSPF/IS-IS).
    - **RSVP-TE:** Используется для управления трафиком (Traffic Engineering) и резервирования ресурсов.
    - **BGP-LU (Labeled Unicast):** Передача меток внутри BGP (RFC 3107).
2.  **Data Plane (Плоскость данных):** Выполняет коммутацию пакетов на основе таблицы LFIB (Label Forwarding Information Base).

### Стек меток (Label Stack)

MPLS поддерживает наложение нескольких меток. Это позволяет строить иерархические сервисы:
- **Верхняя метка:** Транспортная (доставка до нужного PE-маршрутизатора).
- **Нижняя метка:** Сервисная (идентификация конкретного VPN или интерфейса на выходе).

### Современные подходы: Segment Routing (SR-MPLS)

Segment Routing упрощает Control Plane, отказываясь от LDP/RSVP-TE в пользу расширений IGP. Путь (LSP) кодируется в виде списка сегментов (меток) непосредственно в заголовке пакета на входе в сеть. Это обеспечивает нативную поддержку Traffic Engineering и SDN.

### MPLS vs VXLAN

| Характеристика | MPLS | VXLAN |
| :--- | :--- | :--- |
| **Уровень** | L2.5 | L3 (Overlay поверх UDP/IP) |
| **Идентификатор** | Label (20 бит) | VNI (24 бита) |
| **Инкапсуляция** | Shim Header (4 байта) | UDP + VXLAN (~50 байт) |
| **Сложность** | Высокая (требует LDP/RSVP/BGP) | Средняя (стандартный IP-андерлей) |
| **Применение** | Магистрали провайдеров, L3VPN/L2VPN | Дата-центры, облака, SD-WAN |

## Практические сценарии

### Настройка MPLS в Linux (iproute2)

Актуально для ядер 4.x–6.x+.

#### 1. Подготовка системы

```bash
# Загрузка модулей
sudo modprobe mpls_router
sudo modprobe mpls_iptunnel

# Лимит меток и включение MPLS на интерфейсе
sudo sysctl -w net.mpls.platform_labels=1000
sudo sysctl -w net.mpls.conf.eth0.input=1
# → net.mpls.conf.eth0.input = 1
```

#### 2. Операции с метками

**Наложение метки (Push) на Ingress:**
```bash
# Направить трафик к 10.10.10.0/24 через шлюз с меткой 100
sudo ip route add 10.10.10.0/24 encap mpls 100 via inet 192.168.1.2 dev eth0
```

**Замена метки (Swap) на Transit LSR:**
```bash
# Если пришел пакет с меткой 100, заменить на 200 и отправить дальше
sudo ip -f mpls route add 100 as 200 via inet 192.168.2.2 dev eth1
```

**Снятие метки (Pop) на Egress:**
```bash
# Снять метку 200 и передать пакет локальному стеку
sudo ip -f mpls route add 200 dev lo
```

#### 3. Проверка

```bash
# Просмотр MPLS-маршрутов
ip -f mpls route show
# → 100 as 200 via inet 192.168.2.2 dev eth1

# Проверка статистики (счетчики MPLS)
ip -s link show eth0
```

### L3VPN (BGP/MPLS VPN)

Для изоляции трафика клиентов используются VRF (Virtual Routing and Forwarding).
1. Пакет клиента попадает в VRF на PE-маршрутизаторе.
2. PE накладывает две метки: нижнюю (VPN label, выученную по MP-BGP) и верхнюю (транспортную, выученную по LDP).
3. Пакет проходит через ядро (P-routers) только по верхней метке.

## Дополнительная информация

- [BGP и MPLS](../Protocols/bgp.md) — использование MP-BGP для VPNv4.
- [VRF в Linux](../../Linux/Networking/vrf.md) — изоляция маршрутизации.
- [Segment Routing](../OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md) — обзор технологии SR.
- [FRRouting (FRR)](https://frrouting.org/) — свободный стек протоколов (LDP, BGP) для Linux.
