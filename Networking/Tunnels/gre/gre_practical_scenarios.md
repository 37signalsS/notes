# Практические сценарии настройки GRE

## Определения и типы сценариев

В практической деятельности GRE используется в трех основных режимах, каждый из которых предназначен для решения специфических задач сетевой связности:

*   **Point-to-Point GRE (Точка-точка):** классический L3-туннель между двумя узлами со статическими адресами. Используется для объединения офисов или подключения к провайдерам защиты от DDoS.
*   **Multipoint GRE (mGRE):** позволяет одному интерфейсу терминировать множество туннелей. Является фундаментом для построения **DMVPN** (Dynamic Multipoint VPN).
*   **GRETAP (L2 GRE):** инкапсулирует Ethernet-кадры вместо IP-пакетов. Позволяет "растягивать" L2-сегменты (VLAN) между удаленными площадками.

**Сводная таблица режимов:**

| Режим | Уровень OSI | Назначение | Особенности |
|-------|-------------|------------|-------------|
| **Point-to-Point** | L3 | Site-to-Site VPN | Требует статических эндпоинтов |
| **mGRE** | L3 | Hub-and-Spoke / Mesh | Требует протоколов разрешения (NHRP) |
| **GRETAP** | L2 | Растягивание VLAN | Высокий overhead (~42 байта) |

---

## Настройка в Linux (iproute2)

Все временные настройки выполняются через утилиту `ip` из пакета `iproute2`. В современных системах рекомендуется использовать `ip link` вместо устаревшего `ip tunnel`.

### Базовая настройка Point-to-Point

```bash
# Создание интерфейса туннеля
# key 100 — идентификатор, позволяющий различать туннели между одними и теми же IP
sudo ip link add gre0 type gre remote 203.0.113.2 local 198.51.100.1 ttl inherit key 100

# Активация интерфейса
sudo ip link set gre0 up

# Назначение IP-адреса внутри туннеля
sudo ip address add 10.0.0.1/30 dev gre0
```

### Настройка GRETAP (L2 туннель)

Сценарий объединения двух площадок в один мост (Bridge):

```bash
# Создание туннеля GRETAP
sudo ip link add tap0 type gretap remote 203.0.113.2 local 198.51.100.1

# Добавление в существующий мост br0
sudo ip link set tap0 master br0
sudo ip link set tap0 up
```

---

## Постоянная конфигурация (Persistence)

Команды `ip link` не сохраняются после перезагрузки. Для промышленной эксплуатации используйте системные менеджеры сети.

### NetworkManager (nmcli)

```bash
# Создание туннеля
sudo nmcli connection add type ip-tunnel ifname gre0 con-name gre0-tunnel \
    mode gre remote 203.0.113.2 local 198.51.100.1

# Настройка адресации и маршрутов
sudo nmcli connection modify gre0-tunnel ipv4.addresses 10.0.0.1/30 ipv4.method manual
sudo nmcli connection modify gre0-tunnel +ipv4.routes "172.16.0.0/24 10.0.0.2"
sudo nmcli connection up gre0-tunnel
```

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

---

## Решение проблем MTU и MSS

Самая частая причина проблем в GRE — превышение размера пакета.

### MSS Clamping (iptables/nftables)

Если вы не можете контролировать MTU на всем пути следования пакета, принудительно ограничивайте TCP MSS.

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

Для работы mGRE без явного указания `remote` требуется протокол **NHRP**. В современном Linux для этого используется **FRRouting (FRR)**.

**Конфигурация интерфейса:**
```bash
sudo ip link add dev mgre0 type gre local 198.51.100.1 key 1 ttl 64
sudo ip addr add 10.255.255.1/24 dev mgre0
sudo ip link set mgre0 up
```
*Дальнейшая настройка (NHRP/BGP) выполняется внутри демона FRR.*

### GRE через UDP (FOU — Foo Over UDP)

Используется для обхода ограничений NAT и брандмауэров, которые плохо работают с чистым протоколом 47 (IP).

```bash
# Создание UDP-слушателя для GRE (порт 6666)
sudo ip fou add port 6666 ipproto 47

# Создание туннеля с инкапсуляцией в UDP
sudo ip link add name gre_fou type gre \
    remote 203.0.113.2 local 198.51.100.1 \
    encap fou encap-sport auto encap-dport 6666
```

---

## Диагностика и отладка

### Основные команды

| Задача | Команда |
|--------|---------|
| Просмотр параметров и Key | `ip -d link show gre0` |
| Проверка счетчиков (дропы) | `ip -s link show gre0` |
| Проверка MTU в реальном времени | `ping -M do -s 1472 10.0.0.2` |
| Перехват трафика | `tcpdump -i any proto 47 -nn` |

### Чек-лист при неисправности

1.  **Связанность эндпоинтов:** Пингуется ли `remote` IP с `local` IP?
2.  **Firewall:** Разрешен ли входящий протокол 47 (GRE) или UDP-порт (для FOU)?
3.  **Маршрутизация:** Есть ли маршрут в целевую сеть через туннельный интерфейс?
4.  **MTU:** Проходят ли мелкие пакеты (ping) при зависании крупных (SSH/HTTP)? Если да — проверьте MSS Clamping.

---

## Дополнительная информация

### Связанные документы

*   [GRE: базовый обзор](./gre.md) — теория, форматы заголовков и накладные расходы.
*   [Интеграция с IPsec](./gre_ipsec_integration.md) — построение защищенных каналов.
*   [Обзор туннелирования](../tunneling_overview.md) — сравнение GRE, IPIP, VXLAN и WireGuard.
*   [iproute2: ip link](../../../Linux/Networking/Tools/iproute2/ip_link.md) — детальное описание параметров интерфейсов.
