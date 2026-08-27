# VXLAN (Virtual Extensible LAN) — виртуальная расширяемая локальная сеть

## Определения

**VXLAN (Virtual Extensible LAN)** — протокол туннелирования, предназначенный для создания оверлейных сетей (Overlay) поверх существующей L3-инфраструктуры ([RFC 7348](https://datatracker.ietf.org/doc/html/rfc7348)). Он позволяет «растягивать» L2-сегменты через границы маршрутизации, решая проблему ограниченности VLAN (4094 ID) и необходимости L2-связности для миграции виртуальных машин и работы подов в Kubernetes.

**Ключевые характеристики:**
- **Уровень:** L2-over-UDP (инкапсуляция Ethernet-кадров в UDP-пакеты).
- **Транспорт:** UDP порт `4789` (стандарт IANA). В ядрах Linux до стандартизации (до v3.12) часто использовался порт `8472`.
- **Идентификатор (VNI):** VXLAN Network Identifier. 24-битное поле, позволяющее создать до 16,777,216 изолированных сетей.
- **Шифрование:** Нативно отсутствует. Для защиты трафика используется в связке с [IPsec](./ipsec/ipsec.md) или MACsec.

**VTEP (VXLAN Tunnel End Point):** Логический интерфейс (точка), выполняющий инкапсуляцию (ingress) и декапсуляцию (egress) трафика. VTEP может быть реализован программно (стек ядра Linux, OVS) или аппаратно (коммутаторы с поддержкой VXLAN).

---

## Предварительные требования

### Версии ядра и пакетов

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **Ядро Linux** | 3.7 (базовая поддержка VXLAN) | 5.10+ (Geneve, offload, полный набор фич) |
| **iproute2** | 3.12 | 5.15+ |
| **FRRouting** (для EVPN) | 7.0 | 9.1+ |
| **Open vSwitch** (опционально) | 2.5 | 3.0+ |

### Установка зависимостей

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install iproute2 bridge-utils ethtool tcpdump

# RHEL/CentOS/Rocky
sudo dnf install iproute bridge-utils ethtool tcpdump

# Для BGP EVPN (опционально)
sudo apt install frr  # или dnf install frr
```

### Проверка поддержки ядра

```bash
# Проверка наличия модуля vxlan
modinfo vxlan | head -5
# → filename:       /lib/modules/$(uname -r)/kernel/drivers/net/vxlan.ko
# → description:    VXLAN tunneling driver
# → license:        GPL

# Проверка загруженного модуля
lsmod | grep vxlan
# → vxlan                 53248  0

# Проверка поддержки geneve (для сравнения)
modinfo geneve | head -3
# → filename:       /lib/modules/$(uname -r)/kernel/drivers/net/geneve.ko
```

### Включение IP-форвардинга

```bash
# Обязательно для работы VTEP
sudo sysctl -w net.ipv4.ip_forward=1

# Сохранение
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/90-vxlan.conf
sudo sysctl -p /etc/sysctl.d/90-vxlan.conf
```

---

## Основные концепции

### Формат заголовка VXLAN (8 байт)

Заголовок вставляется между внешним UDP-заголовком и внутренним Ethernet-кадром.

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|R|R|R|R|I|R|R|R|            Reserved (24 bits)                 |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                VXLAN Network Identifier (VNI) |   Reserved    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **I-бит (Flags):** Должен быть установлен в 1 для указания наличия валидного VNI. Остальные биты (R) зарезервированы.
- **VNI (24 бита):** Уникальный идентификатор виртуальной сети.
- **Reserved:** Используются в расширениях, таких как **VXLAN-GPE** (Generic Protocol Extension) для инкапсуляции не-Ethernet пакетов или в Cisco-специфичных GBP (Group Based Policy).

### Инкапсуляция и накладные расходы (Overhead)

Структура результирующего пакета:
`[Внешний Ethernet][Внешний IP][UDP][VXLAN Header][Внутренний Ethernet Frame]`

**Расчет оверхеда (IPv4):** ~50 байт.
- Внешний Ethernet: 14 байт
- IPv4 Header: 20 байт
- UDP Header: 8 байт
- VXLAN Header: 8 байт
- *Итого:* 50 байт. Если используется IPv6, оверхед возрастает до 70 байт из-за большего размера IP-заголовка.

### Типы VNI и маршрутизация (IRB)

1.  **L2-VNI (Bridging):** Прямое расширение L2-домена. Пакеты внутри VNI коммутируются на основе MAC-адресов.
2.  **L3-VNI (Routing):** Используется в архитектуре **IRB (Integrated Routing and Bridging)** для связи разных подсетей. 
    - **Symmetric IRB:** Трафик между узлами передается через специальный транзитный VNI, что упрощает масштабирование.
    - **Asymmetric IRB:** Маршрутизация выполняется только на входном VTEP, на выходе — только бриджинг.

### Механизмы обучения (Control Plane)

Control Plane определяет, как VTEP узнают о расположении удаленных хостов.

| Метод | Описание | Масштабируемость | Использование |
| :--- | :--- | :--- | :--- |
| **Flood-and-learn** | BUM-трафик (Broadcast, Unknown Unicast, Multicast) рассылается на все VTEP в VNI. VTEP изучают MAC-адреса из входящих пакетов. | Ограниченная (broadcast storm) | Legacy, небольшие сети |
| **Multicast** | VXLAN-инкапсулированный multicast через IP-multicast в underlay. VTEP подписываются на multicast-группу. | Средняя | Cisco Nexus, OVN (multicast mode) |
| **BGP EVPN (RFC 7432)** | Control-plane learning через BGP. VTEP анонсируют MAC/IP через BGP Route Type 2/5. **ARP Suppression:** VTEP кэширует ARP-ответы и отвечает локально. **Anycast Gateway:** Шлюз по умолчанию имеет одинаковый IP/MAC на всех узлах. | Высокая | Production DC (EVPN-VXLAN) |
| **Static (HER)** | Head-End Replication: VTEP отправляет копии пакета на каждый VTEP в VNI (вместо multicast). | Низкая (<50 VTEP) | OVN default, Kubernetes |
| **OVN southbound DB** | OVN-контроллер программит правила forwarding в OVS. Нет flooding — всё через control plane. | Высокая | OVN-Kubernetes |

### BGP EVPN: Route Types

| Route Type | Назначение | Пример использования |
| :--- | :--- | :--- |
| **Type 2 (MAC/IP Advertisement)** | Анонсирование MAC-адреса и IP-адреса хоста | VTEP сообщает о MAC/IP пода |
| **Type 3 (Inclusive Multicast)** | Групповая подписка на VNI (аналог multicast group) | VTEP входит в L2-VNI |
| **Type 5 (IP Prefix)** | Маршрутизация между VNI (L3-VNI) | Межсегментная маршрутизация |

### Стек меток и инкапсуляция

VXLAN может использоваться в связке с другими протоколами инкапсуляции:
- **VXLAN over GRE:** Двойная инкапсуляция для сред с ограничениями по UDP.
- **VXLAN over IPsec:** Шифрование трафика overlay (см. [IPsec](./ipsec/ipsec.md)).
- **VXLAN over WireGuard:** Шифрование + простота настройки (см. [GRE vs WireGuard](./gre/gre_vs_wireguard.md)).

---

## Практические сценарии в Linux

Для управления используется пакет `iproute2`.

### 1. Режим Unicast (точка-точка)
Применяется для соединения двух хостов без настройки мультикаста.

```bash
# Хост A (192.168.1.10)
ip link add vxlan10 type vxlan id 10 remote 192.168.1.20 local 192.168.1.10 dev eth0 dstport 4789
ip addr add 10.0.0.1/24 dev vxlan10
ip link set vxlan10 up

# Хост B (192.168.1.20)
ip link add vxlan10 type vxlan id 10 remote 192.168.1.10 local 192.168.1.20 dev eth0 dstport 4789
ip addr add 10.0.0.2/24 dev vxlan10
ip link set vxlan10 up
```

**Ожидаемый результат:**
```bash
ping 10.0.0.2
# → PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
# → 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.123 ms
```

### 2. Режим Multicast (динамический)
Позволяет множеству VTEP общаться через одну мультикаст-группу.

```bash
# На всех узлах
ip link add vxlan10 type vxlan id 10 group 239.1.1.1 dev eth0 dstport 4789
ip link set vxlan10 up
```

### 3. VXLAN + Bridge (L2-сегмент)
Обычно VXLAN-интерфейс добавляется в мост для объединения с виртуальными машинами.

```bash
ip link add br-vxlan type bridge
ip link set vxlan10 master br-vxlan
ip link set veth-container master br-vxlan
ip link set br-vxlan up
```

### 4. VXLAN с Head-End Replication (HER)
Для небольших кластеров без multicast — каждый VTEP отправляет копии на все остальные.

```bash
# На VTEP1 (10.0.0.1) — отправляет на VTEP2 (10.0.0.2) и VTEP3 (10.0.0.3)
ip link add vxlan100 type vxlan id 100 \
    local 10.0.0.1 \
    dstport 4789 \
    nolearning

ip link set vxlan100 up

# Добавление remote VTEP в FDB (ручное)
bridge fdb append 00:00:00:00:00:00 dst 10.0.0.2 dev vxlan100 self permanent
bridge fdb append 00:00:00:00:00:00 dst 10.0.0.3 dev vxlan100 self permanent

# Проверка
bridge fdb show dev vxlan100
# → 00:00:00:00:00:00 dst 10.0.0.2 dev vxlan100 self permanent
# → 00:00:00:00:00:00 dst 10.0.0.3 dev vxlan100 self permanent
```

### 5. Тестирование в лаборатории (Network Namespaces)

Для полного тестирования VXLAN не требуются физические устройства:

```bash
# Создание двух изолированных VTEP в network namespaces
ip netns add vtep1
ip netns add vtep2

# Underlay: veth-пара между VTEP
ip link add underlay1 netns vtep1 type veth peer name underlay2 netns vtep2
ip netns exec vtep1 ip addr add 10.0.0.1/24 dev underlay1
ip netns exec vtep1 ip link set underlay1 up
ip netns exec vtep1 ip link set lo up
ip netns exec vtep1 sysctl -w net.ipv4.ip_forward=1

ip netns exec vtep2 ip addr add 10.0.0.2/24 dev underlay2
ip netns exec vtep2 ip link set underlay2 up
ip netns exec vtep2 ip link set lo up
ip netns exec vtep2 sysctl -w net.ipv4.ip_forward=1

# Overlay: VXLAN-интерфейсы
ip netns exec vtep1 ip link add vxlan10 type vxlan id 10 \
    remote 10.0.0.2 local 10.0.0.1 dev underlay1 dstport 4789
ip netns exec vtep1 ip addr add 192.168.10.1/24 dev vxlan10
ip netns exec vtep1 ip link set vxlan10 up

ip netns exec vtep2 ip link add vxlan10 type vxlan id 10 \
    remote 10.0.0.1 local 10.0.0.2 dev underlay2 dstport 4789
ip netns exec vtep2 ip addr add 192.168.10.2/24 dev vxlan10
ip netns exec vtep2 ip link set vxlan10 up

# Тест
ip netns exec vtep1 ping -c 2 192.168.10.2
# → PING 192.168.10.2 (192.168.10.2) 56(84) bytes of data.
# → 64 bytes from 192.168.10.2: icmp_seq=1 ttl=64 time=0.089 ms

# Просмотр VXLAN-трафика
ip netns exec vtep1 tcpdump -i underlay1 -nn port 4789 &
ip netns exec vtep1 ping -c 1 192.168.10.2
# → 12:34:56.789012 IP 10.0.0.1.54321 > 10.0.0.2.4789: UDP, length 90
# →   VXLAN vni=10

# Очистка
ip netns del vtep1
ip netns del vtep2
```

### 6. VXLAN + BGP EVPN (упрощённый пример)

Для production-среды используется BGP EVPN вместо flood-and-learn. Полный пример с OVN и Kubernetes см. в [VXLAN и Geneve](../Concepts/sdn/vxlan_geneve.md).

```text
# Конфигурация FRR для VXLAN EVPN (vtysh)
conf t
 !
 router bgp 65001
  bgp router-id 10.0.0.1
  bgp log-neighbor-changes
  !
  address-family l2vpn evpn
   neighbor 10.0.0.2 activate
   advertise-all-vni
  exit-address-family
 !
end
write memory
```

---

## Эксплуатация и тюнинг

### Аппаратное ускорение (Offload)

Современные NIC (Intel, Mellanox) поддерживают разгрузку инкапсуляции:
- **VXLAN Checksum Offload:** Расчет контрольных сумм внешнего UDP.
- **RSS Over VXLAN:** Распределение входящего трафика по ядрам CPU на основе хеша внутреннего IP/Port (предотвращает перегрузку одного ядра туннелированным трафиком).
- **VXLAN Segmentation Offload:** аппаратная инкапсуляция/деинкапсуляция.

**Проверка:**
```bash
# Проверка поддержки offload
ethtool -k eth0 | grep vxlan
# → tx-vxlan-segmentation: on
# → tx-checksum-vxlan-non-generic: on
# → rx-vxlan-port-specific-hash: on

# Проверка RSS
ethtool -k eth0 | grep rx-hash
# → rx-hashing: on
```

### Тонкая настройка MTU

Неправильный MTU — основная причина проблем в VXLAN (обрывы TLS, медленная работа HTTP).

1.  **Jumbo Frames в Underlay (Рекомендуется):** Установить MTU 9000-9216 на физической сети. Это позволит оверлею работать со стандартными 1500 байтами.
2.  **MTU 1450 в Overlay:** Если физическая сеть ограничена 1500 байтами, на VXLAN-интерфейсах MTU должен быть **1450** (для IPv4) или **1430** (для IPv6).
3.  **Облачные спецификации:** 
    - GCP/AWS VPC часто имеют свои ограничения. При использовании VXLAN поверх VPC может потребоваться MTU **1442** или даже **1400**.

**Проверка Path MTU:**
```bash
# Проверка MTU на VXLAN-интерфейсе
ip link show vxlan10
# → vxlan10: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...

# Проверка Path MTU (с флагом DF)
ping -M do -s 1422 -c 1 <remote-ip>
# → 1422 + 28 (IP+ICMP headers) = 1450 = MTU overlay
```

### Диагностика

```bash
# Просмотр таблицы FDB (Forwarding Database)
bridge fdb show dev vxlan10
# → 00:00:00:00:00:00 dst 10.0.0.2 dev vxlan10 self permanent
# → aa:bb:cc:dd:ee:ff dst 10.0.0.2 dev vxlan10 self

# Просмотр всех FDB-записей
bridge fdb show | grep vxlan

# Проверка параметров интерфейса (VNI, порт, эндпоинты)
ip -d link show vxlan10
# → vxlan10: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450 ...
# →     vxlan id 10 local 10.0.0.1 srcport 0 0 dstport 4789 ...

# Анализ внешнего трафика (порт 4789)
sudo tcpdump -ni eth0 udp port 4789 -vvv
# → 12:34:56.789012 IP 10.0.0.1.12345 > 10.0.0.2.4789: UDP, length 1450
# →   VXLAN vni=10

# Анализ трафика внутри оверлея
sudo tcpdump -ni vxlan10 icmp

# Просмотр статистики VXLAN
ip -s link show vxlan10
# → RX:  bytes=... packets=... errors=... dropped=...
# → TX:  bytes=... packets=... errors=... dropped=...

# Просмотр ARP-таблицы на VXLAN-интерфейсе
ip neigh show dev vxlan10
# → 10.0.0.2 lladdr aa:bb:cc:dd:ee:ff REACHABLE
```

---

## Типичные ошибки и их устранение

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Фрагментация TCP, обрывы TLS** | MTU overlay > underlay MTU | `ping -M do -s 1472 <remote>` — fail | Установить MTU=1450 на VXLAN-интерфейсе |
| **VXLAN-трафика нет** | Underlay между VTEP недоступен | `tcpdump -i eth0 port 4789` — пусто | Проверить маршрутизацию между VTEP; `ip route get <remote-vtep-ip>` |
| **ARP storm (broadcast flooding)** | Нет ARP Suppression, много хостов в VNI | `tcpdump -i vxlan10 arp` — множество ARP request | Включить ARP Suppression (BGP EVPN / OVN); уменьшить количество VNI |
| **MAC flapping** | MAC «прыгает» между VTEP | `bridge fdb show` — MAC на нескольких VTEP | Проверить duplicate VNI; исключить loop в underlay |
| **FDB переполнена** | Количество MAC > hardware limit | `bridge fdb show \| wc -l` > platform limit | Использовать BGP EVPN вместо flood-and-learn |
| **VTEP не видит удалённых хостов** | Flood-and-learn не работает (multicast отключён) | `bridge fdb show dev vxlan10` — нет записей | Настроить multicast-группу или использовать HER/BGP EVPN |
| **Пакеты дропаются на兽ходе** | Отсутствует route к remote VTEP | `ip route get <remote-vtep-ip>` — no route | Добавить маршрут в underlay |

---

## Безопасность

VXLAN не имеет встроенных механизмов шифрования и аутентификации. Любой узел в underlay-сети может:
- Прослушивать трафик overlay (читать внутренние MAC/IP)
- Подменять трафик (forging VXLAN-пакеты)
- Атаковать через UDP-порт 4789

### Рекомендации

1. **Шифрование overlay:** Используйте [IPsec](./ipsec/ipsec.md) или WireGuard для шифрования трафика между VTEP.
2. **Firewall на underlay:** Ограничьте доступ к UDP 4789 только между VTEP:
   ```bash
   sudo iptables -A INPUT -p udp --dport 4789 -s 10.0.0.0/24 -j ACCEPT
   sudo iptables -A INPUT -p udp --dport 4789 -j DROP
   ```
3. **Изоляция VNI:** Не смешивайте трафик разных tenant-сетей (tenant networks) в одном VNI без ACL.
4. **Мониторинг:** Отслеживайте аномалии в FDB (MAC flapping, неизвестные MAC).

---

## Сравнение технологий

| Протокол | Overhead | Масштаб | Транспорт | Control Plane |
| :--- | :--- | :--- | :--- | :--- |
| **VXLAN** | 50 B | 16M VNI | UDP 4789 | Flood-n-Learn / BGP EVPN |
| **Geneve** | 50+ B | 16M VNI | UDP 6081 | Гибкий (TLV), стандарт в OVN |
| **NVGRE** | 42 B | 16M VSID | GRE (IP 47) | Используется в средах Hyper-V |
| **GRETAP** | 42 B | < 4096 | GRE (47) | Статическое L2-туннелирование |

---

## Ограничения и особенности

- **Фрагментация:** При некорректном MTU пакеты фрагментируются, что резко снижает производительность. VXLAN не поддерживает фрагментацию — oversized-пакеты отбрасываются.
- **CPU Overhead:** Инкапсуляция без аппаратной разгрузки может потреблять до 15-20% ресурсов CPU при высоком трафике. Для 40+ Гбит/с требуется DPDK или NIC с VXLAN offload.
- **Размер стека меток:** В ядре Linux поддерживается до 3 меток в стеке (ограничение ядра, не протокола). При использовании VXLAN + MPLS + IPsec стек может исчерпаться.
- **MTU:** VXLAN добавляет 50 байт оверхеда (IPv4). При стеке из N протоколов инкапсуляции оверхед суммируется (VXLAN + WireGuard = 110 байт).
- **FDB Limits:** Количество MAC-адресов в FDB ограничено аппаратно. На простых коммутаторах — до 16K записей. Для масштабирования используйте BGP EVPN.
- **Convergence Time:** При failover VTEP время сходимости flood-and-learn может составлять 30-60 секунд (ожидание старения FDB). BGP EVPN обеспечивает сходимость за 1-3 секунды.
- **Мультикаст:** В облачных средах (AWS, GCP) IP-multicast часто заблокирован. Используйте HER или BGP EVPN.

---

## Дополнительная информация

- **[Обзор туннелирования](./tunneling_overview.md)** — сравнение с другими протоколами.
- **[BGP и EVPN](../Protocols/bgp.md)** — глубокое погружение в современный сетевой дизайн ЦОД.
- **[MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — детальный разбор проблем фрагментации и MSS Clamping.
- **[VXLAN и Geneve](../Concepts/sdn/vxlan_geneve.md)** — сравнение VXLAN с Geneve, OVN-интеграция, трассировка пакетов.
- **[Сетевой драйвер Overlay в Docker](../../Docker/Docker_network/drivers/overlay.md)** — реализация VXLAN в Swarm и контейнерах.
- **[GRE vs WireGuard](./gre/gre_vs_wireguard.md)** — шифрование overlay: VXLAN поверх WireGuard.
