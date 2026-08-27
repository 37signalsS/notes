# IPsec: динамическая маршрутизация (BGP/OSPF поверх IPsec)

> **Основной документ:** [IPsec (основной документ)](./ipsec.md).

Данный файл описывает построение динамической маршрутизации (BGP, OSPF) поверх Route-based IPsec с использованием XFRM-интерфейсов и FRRouting.

---

## Определения

**Route-based IPsec** — подход, при котором IPsec-туннель представлен виртуальным интерфейсом (XFRM/VTI), а маршрутизация определяется стандартной таблицей ядра (routing table). В отличие от Policy-based, позволяет использовать динамические протоколы маршрутизации.

**FRRouting (FRR)** — современный набор демонов маршрутизации для Linux (BGP, OSPF, IS-IS, RIP, EIGRP). Заменил Quagga/Zebra. Дефолтный маршрутизатор в большинстве дистрибутивов.

**OSPF (Open Shortest Path First)** — протокол динамической маршрутизации с открытым состоянием. Использует стоимость (cost) как метрику. Два основных сценария: Area 0 (backbone) и NSSA.

**BGP (Border Gateway Protocol)** — протокол маршрутизации между автономными системами (AS). De facto standard для маршрутизации в крупных сетях и между провайдерами.

** redistribute ** — механизм обмена маршрутами между протоколами (например, статические маршруты → OSPF, OSPF → BGP).

---

## Основные концепции

### Архитектура: Route-based IPsec + FRR

```
+-------------------+     +-------------------+     +-------------------+
|   Приложение      |     |   FRRouting       |     |   strongSwan      |
|   (клиент)        |     |   (BGP/OSPF)      |     |   (IPsec)         |
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                         |
         v                         v                         v
+-------------------+     +-------------------+     +-------------------+
|   Routing table   |     |   XFRM interface  |     |   Физический      |
|   (ip route)      |     |   (xfrm0)         |     |   интерфейс       |
+-------------------+     +-------------------+     +-------------------+
         |                         |                         |
         +------------+------------+------------+------------+
                      |
                      v
              +-------------------+
              |   IPsec tunnel    |
              |   (ESP)           |
              +-------------------+
```

### Почему Route-based лучше Policy-based для динамической маршрутизации

| Критерий | Policy-based | Route-based |
|----------|-------------|-------------|
| Маршрутизация | Статические политики SPD | Таблица маршрутизации ядра |
| Динамические протоколы | Невозможно | OSPF, BGP, IS-IS |
| Мультикаст | Не поддерживается | Поддерживается |
| Управление маршрутами | Вручную через setkey/ip xfrm | Автоматически через FRR |
| Failover | Вручную | Автоматически через протокол |

---

## Практические сценарии

### Site-to-Site с OSPF

#### Топология

```
[Сеть A] --- [Шлюз A] === IPsec === [Шлюз B] --- [Сеть B]
192.168.1.0/24   xfrm0           xfrm0   192.168.2.0/24
              169.254.1.1/30  169.254.1.2/30
```

#### Шлюз A — strongSwan + FRR

```bash
# 1. Конфигурация XFRM интерфейса
# /etc/swanctl/conf.d/ospf-site.conf
connections {
    site-b {
        version = 2
        local_addrs = 198.51.100.1
        remote_addrs = 203.0.113.2

        proposals = aes256gcm128-sha384-ecp384

        local {
            auth = pubkey
            certs = gwA.crt
        }
        remote {
            auth = pubkey
            cacerts = ca.crt
        }

        children {
            lan-to-lan {
                local_ts = 0.0.0.0/0
                remote_ts = 0.0.0.0/0
                esp_proposals = aes256gcm128-ecp384
                start_action = trap
                if_id = 1
            }
        }
    }
}
```

```bash
# 2. Настройка XFRM интерфейса
sudo ip link add xfrm0 type xfrm if_id 1
sudo ip addr add 169.254.1.1/30 dev xfrm0
sudo ip link set xfrm0 up

# 3. Конфигурация FRRouting (OSPF)
# /etc/frr/frr.conf
frr defaults traditional
hostname gwA
log file /var/log/frr/frr.log debugging

router ospf
 ospf router-id 198.51.100.1
 # Объявление локальных сетей
 network 192.168.1.0/24 area 0
 network 169.254.1.0/30 area 0
 # Redistribute статических маршрутов (если есть)
 redistribute static
 ! passive-interface для физических интерфейсов
 passive-interface eth0
```

```bash
# 4. Настройка FRRouting (BGP) — альтернатива OSPF
# /etc/frr/frr.conf
router bgp 65001
 bgp router-id 198.51.100.1
 neighbor 169.254.1.2 remote-as 65002
 !
 address-family ipv4 unicast
  network 192.168.1.0/24
  neighbor 169.254.1.2 activate
 exit-address-family
```

```bash
# 5. Применение и проверка
sudo systemctl restart frr
sudo vtysh -c "show ip ospf neighbor"
sudo vtysh -c "show ip route ospf"
sudo vtysh -c "show ip bgp summary"
```

#### Шлюз B — зеркальная конфигурация

```bash
# XFRM интерфейс
sudo ip link add xfrm0 type xfrm if_id 1
sudo ip addr add 169.254.1.2/30 dev xfrm0
sudo ip link set xfrm0 up

# /etc/frr/frr.conf
frr defaults traditional
hostname gwB
log file /var/log/frr/frr.log debugging

router ospf
 ospf router-id 203.0.113.2
 network 192.168.2.0/24 area 0
 network 169.254.1.0/30 area 0
 redistribute static
 passive-interface eth0

# BGP альтернатива
router bgp 65002
 bgp router-id 203.0.113.2
 neighbor 169.254.1.1 remote-as 65001
 !
 address-family ipv4 unicast
  network 192.168.2.0/24
  neighbor 169.254.1.1 activate
 exit-address-family
```

### Multi-site с BGP (Hub-and-Spoke)

#### Топология

```
              [Hub / РЕ #1]
             AS 65000
            198.51.100.1
           /       |       \
          /        |        \
   [Spoke 1]  [Spoke 2]  [Spoke 3]
   AS 65001   AS 65002   AS 65003
   203.0.113.2  203.0.113.3  203.0.113.4
```

```bash
# Hub — BGP конфигурация
# /etc/frr/frr.conf
router bgp 65000
 bgp router-id 198.51.100.1
 !
 # Spoke 1
 neighbor 169.254.1.2 remote-as 65001
 neighbor 169.254.1.2 description Spoke1
 !
 # Spoke 2
 neighbor 169.254.2.2 remote-as 65002
 neighbor 169.254.2.2 description Spoke2
 !
 # Spoke 3
 neighbor 169.254.3.2 remote-as 65003
 neighbor 169.254.3.2 description Spoke3
 !
 address-family ipv4 unicast
  neighbor 169.254.1.2 activate
  neighbor 169.254.2.2 activate
  neighbor 169.254.3.2 activate
  # Redistribute OSPF → BGP
  redistribute ospf
 exit-address-family
```

```bash
# Spoke 1 — BGP конфигурация
router bgp 65001
 bgp router-id 203.0.113.2
 neighbor 169.254.1.1 remote-as 65000
 !
 address-family ipv4 unicast
  network 192.168.1.0/24
  neighbor 169.254.1.1 activate
  # Redistribute локальных маршрутов
  redistribute connected
 exit-address-family
```

### Firewall для динамической маршрутизации через IPsec

```bash
# Hub — разрешить BGP/OSPF от Spoke
# nftables
sudo nft add rule inet filter input ip saddr 203.0.113.0/24 tcp dport 179 accept
sudo nft add rule inet filter input ip saddr 203.0.113.0/24 proto ospf accept

# iptables
sudo iptables -A INPUT -s 203.0.113.0/24 -p tcp --dport 179 -j ACCEPT
sudo iptables -A INPUT -s 203.0.113.0/24 -p ospf -j ACCEPT
```

---

## Управление и диагностика

### Команды FRRouting

```bash
# Вход в интерфейс vtysh
sudo vtysh

# Или одноразовые команды
sudo vtysh -c "show ip ospf neighbor"
sudo vtysh -c "show ip ospf route"
sudo vtysh -c "show ip bgp summary"
sudo vtysh -c "show ip bgp"
sudo vtysh -c "show ip route"
sudo vtysh -c "show ip route ospf"
sudo vtysh -c "show ip route bgp"
sudo vtysh -c "show interface"
```

### Диагностика

```bash
# 1. Проверка XFRM интерфейса
ip link show xfrm0
ip addr show xfrm0
ip xfrm state

# 2. Проверка邻居 OSPF
sudo vtysh -c "show ip ospf neighbor"
# Ожидаемый вывод: State = FULL/DR или FULL/BDR

# 3. Проверка маршрутов
ip route | grep -E "192.168|169.254"
sudo vtysh -c "show ip route ospf"

# 4. Проверка BGP peer
sudo vtysh -c "show ip bgp summary"
# Ожидаемый вывод: State/PfxRcd = числовое значение (не "Idle" или "Active")

# 5. Traceroute через туннель
traceroute -n 192.168.2.1

# 6. Анализ трафика
sudo tcpdump -n -i xfrm0
sudo tcpdump -n -i any proto ospf
sudo tcpdump -n -i any port 179
```

---

## Типовые проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| OSPF neighbor не поднимается | Несовпадение area, hello/dead timers | Проверить `show ip ospf neighbor`, синхронизировать таймеры |
| BGP peer в состоянии Idle | Firewall блокирует TCP 179 | Разрешить TCP 179 от пира |
| Маршруты не обучаются | Redistribute не настроен | Добавить `redistribute` в конфигурацию протокола |
| Packet loss через туннель | MTU/фрагментация | Настроить MSS Clamping, проверить `ip link show xfrm0 mtu` |
| Конфликт маршрутов | OSPF и BGP конфликтуют | Настроить administrative distance (BGP=20, OSPF=110) |
| Loop маршрутов | Hub advertises spoke routes back | Настроить `distance` или `route-map` для фильтрации |

---

## Дополнительная информация

### Administrative Distance (по умолчанию)

| Протокол | AD | Приоритет |
|----------|----|-----------|
| Connected | 0 | Наивысший |
| Static | 1 | Высокий |
| OSPF | 110 | Средний |
| BGP (eBGP) | 20 | Высокий |
| BGP (iBGP) | 200 | Низкий |

### Связанные документы

- **[IPsec (основной документ)](./ipsec.md)** — настройка strongSwan, XFRM-интерфейсы.
- **[Интеграция GRE с IPsec](../gre/gre_ipsec_integration.md)** — альтернативный подход (GRE + IPsec).
- **[Высокая доступность IPsec](./ipsec_ha.md)** — failover для маршрутизации.
- **[Производительность IPsec](./ipsec_performance.md)** — оптимизация для динамических маршрутов.
