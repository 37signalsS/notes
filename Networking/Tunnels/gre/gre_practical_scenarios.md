# Практические сценарии настройки GRE

## Определения и типы сценариев

В практической деятельности GRE используется в нескольких основных режимах, каждый из которых предназначен для решения специфических задач сетевой связности:

*   **Point-to-Point GRE (Точка-точка):** Классический L3-туннель между двумя узлами со статическими адресами. Используется для объединения офисов или подключения к провайдерам защиты от DDoS.
*   **Multipoint GRE (mGRE):** Позволяет одному интерфейсу терминировать множество туннелей. Является фундаментом для построения **DMVPN** (Dynamic Multipoint VPN).
*   **GRETAP (L2 GRE):** Инкапсулирует Ethernet-кадры вместо IP-пакетов. Позволяет "растягивать" L2-сегменты (VLAN) между удаленными площадками.
*   **ERSPAN (Encapsulated Remote SPAN):** Специализированная версия GRE для зеркалирования трафика L2 через маршрутизируемые IP-сети.

**Сводная таблица режимов:**

| Режим | Уровень OSI | Назначение | Особенности |
|-------|-------------|------------|-------------|
| **Point-to-Point** | L3 | Site-to-Site VPN | Требует статических эндпоинтов |
| **mGRE** | L3 | Hub-and-Spoke / Mesh | Требует протоколов разрешения (NHRP) |
| **GRETAP** | L2 | Растягивание VLAN | Высокий оверхед (~42 байта) |
| **ERSPAN** | L2 | Мониторинг трафика | Зависит от аппаратной поддержки |

---

## Настройка в Linux (iproute2)

Все настройки выполняются через утилиту `ip`. В современных системах рекомендуется использовать `ip link` вместо устаревшего `ip tunnel`.

### Базовая настройка Point-to-Point

```bash
# Создание интерфейса туннеля
# local/remote — внешние IP-адреса узлов
# key 100 — идентификатор туннеля (должен совпадать на обоих концах)
sudo ip link add gre0 type gre remote 203.0.113.2 local 198.51.100.1 ttl inherit key 100

# Активация интерфейса
sudo ip link set gre0 up

# Назначение IP-адреса внутри туннеля
sudo ip address add 10.0.0.1/30 dev gre0
```

### Настройка GRETAP (L2 туннель)

Используется для объединения двух удаленных сегментов в один программный мост (Bridge):

```bash
# Создание туннеля GRETAP
sudo ip link add tap0 type gretap remote 203.0.113.2 local 198.51.100.1

# Добавление интерфейса в существующий мост br0
sudo ip link set tap0 master br0
sudo ip link set tap0 up
```

### Настройка ERSPAN

Зеркалирование трафика с удаленного коммутатора на сервер анализа:

```bash
# erspan_ver 1 (для Cisco) или 2 (Modern Linux/стандарт)
# erspan 10 — идентификатор сессии
sudo ip link add dev erspan0 type erspan \
    local 198.51.100.1 remote 203.0.113.2 \
    erspan_ver 1 erspan 10
sudo ip link set erspan0 up
```

---

## Настройка на сетевом оборудовании

### Cisco IOS/XE (Point-to-Point)

```cisco
interface Tunnel0
 ip address 10.0.0.1 255.255.255.252
 tunnel source 198.51.100.1
 tunnel destination 203.0.113.2
 tunnel key 100
 ! Рекомендуется для stateless туннелей
 keepalive 10 3
```

### MikroTik (RouterOS)

```routeros
/interface gre
add local-address=198.51.100.1 remote-address=203.0.113.2 name=gre-tunnel1 \
    dscp=inherit mtu=1476 tunnel-id=100
/ip address
add address=10.0.0.1/30 interface=gre-tunnel1
```

---

## Постоянная конфигурация (Persistence)

### Netplan (Ubuntu/Debian)

Файл `/etc/netplan/60-tunnel.yaml`:

```yaml
network:
  version: 2
  tunnels:
    gre0:
      mode: gre
      local: 198.51.100.1
      remote: 203.0.113.2
      addresses:
        - 10.0.0.1/30
      keys:
        input: 100
        output: 100
      routes:
        - to: 172.16.0.0/24
          via: 10.0.0.2
```

### systemd-networkd

Файл `/etc/systemd/network/25-gre.netdev`:
```ini
[NetDev]
Name=gre0
Kind=gre

[Tunnel]
Local=198.51.100.1
Remote=203.0.113.2
Key=100
```

Файл `/etc/systemd/network/25-gre.network`:
```ini
[Match]
Name=gre0

[Network]
Address=10.0.0.1/30

[Route]
Destination=172.16.0.0/24
Gateway=10.0.0.2
```

### NetworkManager (nmcli)

```bash
# Создание туннеля с ключом
sudo nmcli connection add type ip-tunnel ifname gre0 con-name gre0-tunnel \
    mode gre remote 203.0.113.2 local 198.51.100.1 \
    ip-tunnel.input-key 100 ip-tunnel.output-key 100

# Настройка адресации
sudo nmcli connection modify gre0-tunnel ipv4.addresses 10.0.0.1/30 ipv4.method manual
sudo nmcli connection modify gre0-tunnel +ipv4.routes "172.16.0.0/24 10.0.0.2"
sudo nmcli connection up gre0-tunnel
```

---

## Решение проблем MTU и MSS

Самая частая причина проблем в GRE — превышение размера пакета, так как заголовок GRE (4-12 байт) + внешний IP (20 байт) уменьшают полезную нагрузку.

### MSS Clamping (iptables/nftables)

Применяется на шлюзах для предотвращения зависания сессий (PMTUD Black Hole).

**Через iptables:**
```bash
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre0 -j TCPMSS --clamp-mss-to-pmtu
```

**Через nftables:**
```bash
nft add rule inet filter forward oifname "gre0" tcp flags syn tcp option maxseg size set rt mtu
```

---

## Продвинутые сценарии

### mGRE и DMVPN

В режиме mGRE интерфейс не имеет фиксированного `remote`. Для работы требуется протокол **NHRP** (Next Hop Resolution Protocol). В Linux это реализуется через **FRRouting (FRR)**.

**Конфигурация интерфейса (Hub):**
```bash
# Создание mGRE интерфейса
sudo ip link add dev mgre0 type gre local 198.51.100.1 key 1 ttl 64
sudo ip addr add 10.255.255.1/24 dev mgre0
sudo ip link set mgre0 up
```
*Настройка NHRP выполняется в `/etc/frr/frr.conf` внутри демона nhrpd.*

### GRE через UDP (FOU — Foo Over UDP)

Используется для обхода проблемных NAT и брандмауэров, а также для балансировки трафика (ECMP) на основе UDP-портов.

```bash
# 1. Создание UDP-слушателя для GRE (порт 6666)
sudo ip fou add port 6666 ipproto 47

# 2. Создание туннеля, упакованного в UDP
sudo ip link add name gre_fou type gre \
    remote 203.0.113.2 local 198.51.100.1 \
    encap fou encap-sport auto encap-dport 6666
```

---

## Диагностика и отладка

### Чек-лист при неисправности

1.  **Связанность Endpoint:** Пингуется ли `remote` IP с хоста? Если нет — проблема в маршрутизации Underlay.
2.  **Firewall:** Разрешен ли протокол **IP 47 (GRE)** или UDP-порт (для FOU) в правилах `INPUT`?
3.  **Key mismatch:** Совпадают ли `key` (идентификаторы туннеля) на обоих концах?
4.  **MTU/MSS:** Проходит ли `ping -M do -s 1472 <remote_tunnel_ip>`? Если нет — уменьшайте MSS.

### Инструментарий

| Задача | Команда |
|--------|---------|
| Просмотр параметров и счетчиков | `ip -d -s link show gre0` |
| Анализ прохождения протокола 47 | `tcpdump -i any proto 47 -nn` |
| Проверка маршрута к эндпоинту | `ip route get 203.0.113.2` |
| Просмотр NHRP кеша (для mGRE) | `vtysh -c "show ip nhrp"` |

### Таблица устранения неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Интерфейс UP, пинга нет** | Firewall блокирует ICMP внутри туннеля или сам GRE снаружи | Проверить правила `iptables/nftables`. |
| **Мелкие пакеты проходят, крупные — нет** | Проблема MTU/MSS | Настроить MSS Clamping до 1360-1400 байт. |
| **Трафик идет только в одну сторону** | NAT/PAT без поддержки GRE | Использовать FOU (GRE-over-UDP). |

---

## Дополнительная информация

### Связанные документы

*   [Протокол GRE](./gre.md) — фундаментальный обзор архитектуры и заголовков.
*   [Интеграция с IPsec](./gre_ipsec_integration.md) — настройка защищенных каналов (GRE-over-IPsec).
*   [ip tunnel vs ip link](../../../Linux/Networking/Tools/iproute2/ip_tunnel.md) — детальное сравнение методов управления в Linux.
*   [MTU и VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — глубокая теория фрагментации и диагностики.
