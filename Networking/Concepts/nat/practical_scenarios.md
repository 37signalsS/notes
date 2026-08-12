# NAT — Практические сценарии

## Настройка NAT (Маскарадинг) в Linux

### Вариант 1: Firewalld (CentOS/RHEL/Fedora)

1. **Включить IP Forwarding:**

    ```bash
    # Постоянно через sysctl
    echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-router.conf
    sudo sysctl --system
    ```

2. **Настроить Masquerading:**

    ```bash
    # Перевести внешний интерфейс в зону external (маскарадинг включен по умолчанию)
    firewall-cmd --zone=external --change-interface=eth0 --permanent

    # Или включить маскарадинг в текущей зоне
    firewall-cmd --zone=public --add-masquerade --permanent

    firewall-cmd --reload
    ```

### Вариант 2: Nftables (Современный стандарт)

```bash
# Создание таблицы nat
nft add table ip nat

# Добавление цепочки POSTROUTING
nft add chain ip nat postrouting { type nat hook postrouting priority 100 \; }

# Включение маскарадинга для интерфейса eth0
nft add rule ip nat postrouting oifname "eth0" masquerade
```

### Вариант 3: Iptables (Legacy)

```bash
# Включение маскарадинга для всех исходящих через eth0
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
```

### Вариант 4: Netplan (Ubuntu/Debian)

Для настройки NAT через Netplan (используя `systemd-networkd`) необходимо разрешить форвардинг на интерфейсе:

```yaml
network:
  version: 2
  ethernets:
    eth1: # Внутренний интерфейс
      addresses: [192.168.1.1/24]
    eth0: # Внешний интерфейс
      dhcp4: true
      routing-policy:
        - from: 192.168.1.0/24
          table: 100
```
*Примечание: Netplan сам не настраивает правила iptables/nftables для NAT, это нужно делать через `nftables` или `iptables` отдельно.*

### Вариант 5: systemd-networkd

Настройка IP-маскарадинга на уровне юнита интерфейса (требует `IPMasquerade=yes`):

```ini
# /etc/systemd/network/eth0.network
[Match]
Name=eth0

[Network]
DHCP=yes
IPForward=yes
IPMasquerade=yes
```

---

## Статический Source NAT (SNAT)

Используется, когда у сервера есть несколько статических публичных IP и нужно, чтобы определенный внутренний хост выходил в интернет с конкретного адреса.

```bash
# Iptables: все из локальной сети 192.168.1.0/24 выходят через IP 203.0.113.10
iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -o eth0 -j SNAT --to-source 203.0.113.10

# Nftables:
nft add rule ip nat postrouting ip saddr 192.168.1.0/24 oifname "eth0" snat to 203.0.113.10
```

---

## Проброс портов (Destination NAT / DNAT)

**DNAT** используется для предоставления доступа к внутренним сервисам из внешней сети.

### Пример: Веб-сервер за NAT
Внешний порт `8080` -> Внутренний IP `192.168.1.10:80`.

**Через firewalld:**
```bash
firewall-cmd --permanent --zone=external --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=192.168.1.10
firewall-cmd --reload
```

**Через nftables:**
```bash
nft add rule ip nat prerouting iifname "eth0" tcp dport 8080 dnat to 192.168.1.10:80
```

**Через iptables:**
```bash
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 8080 -j DNAT --to-destination 192.168.1.10:80
```

**См. также:** Детальный разбор прохождения пакета с DNAT/SNAT в инфраструктуре Docker — **[Packet Flow в Docker Bridge](../../../Docker/Docker_network/drivers/bridge.md#жизненный-цикл-пакета-packet-flow)**.

---

## Настройка Hairpin NAT (Loopback NAT)

**Проблема:** Внутренний клиент обращается к внутреннему серверу по **публичному** IP-адресу маршрутизатора. Без Hairpin NAT пакет уйдет на сервер, но сервер ответит клиенту напрямую (так как они в одной подсети), и клиент сбросит соединение, так как ждал ответа от публичного IP.

**Решение (на Iptables):**
```bash
# SNAT для внутреннего трафика, чтобы сервер отвечал через роутер
iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -d 192.168.1.10 -p tcp --dport 80 -j MASQUERADE
```

**Решение (на Nftables):**
```bash
nft add rule ip nat postrouting ip saddr 192.168.1.0/24 ip daddr 192.168.1.10 tcp dport 80 masquerade
```

---

## Проброс SSH через сетевой уровень (NAT-L3)

Сценарий: Доступ к серверу B (внутренний) через сервер A (шлюз) без использования SSH-туннелей (ProxyJump) или VPN.

**На сервере A (шлюз):**

1. **DNAT (проброс порта):**
   ```bash
   iptables -t nat -A PREROUTING -p tcp --dport 2222 -j DNAT --to-destination 192.168.1.20:22
   ```

2. **SNAT (маскировка источника, чтобы ответ шел через шлюз):**
   ```bash
   iptables -t nat -A POSTROUTING -d 192.168.1.20 -p tcp --dport 22 -j MASQUERADE
   ```

---

## NAT в облачных инфраструктурах

### Yandex Cloud: NAT Gateway

В Yandex Cloud классический NAT на ВМ (Egress NAT) считается устаревшим. Рекомендуется использовать **NAT Gateway**.

```bash
# Создание шлюза
yc vpc gateway create --name nat-gw

# Создание таблицы маршрутов
yc vpc route-table create --name rt-nat --network-name main-net

# Добавление статического маршрута через NAT Gateway
yc vpc route-table static-route create \
  --route-table-name rt-nat \
  --destination 0.0.0.0/0 \
  --gateway-name nat-gw

# Привязка таблицы к подсети
yc vpc subnet update --name private-subnet --route-table-name rt-nat
```

### AWS: NAT Gateway

В AWS NAT Gateway создается в публичной подсети для обеспечения выхода приватных подсетей в интернет.

```bash
# Пример через AWS CLI (упрощенно)
aws ec2 create-nat-gateway --subnet-id subnet-12345 --allocation-id eipalloc-12345
```

### Kubernetes: IP Masquerade Agent

В K8s используется для маскировки трафика подов при выходе за пределы кластера или в специфичные CIDR.

```yaml
# Пример ConfigMap для ip-masq-agent
apiVersion: v1
kind: ConfigMap
metadata:
  name: ip-masq-agent
  namespace: kube-system
data:
  config: |
    nonMasqueradeCIDRs:
      - 10.0.0.0/8
    masqLinkLocal: false
```

---

## Технологии перехода на IPv6 (NAT64)

В средах IPv6-only используется NAT64 для доступа к IPv4-интернету. Популярное решение — **Tayga**.

**Алгоритм работы:**
1. DNS64 синтезирует AAAA-запись из A-записи, используя префикс (например, `64:ff9b::/96`).
2. Клиент отправляет IPv6 пакет на этот адрес.
3. Tayga перехватывает пакет и транслирует его в IPv4.

**Пример конфигурации Tayga (`/etc/tayga.conf`):**
```ini
tun-device nat64
ipv4-addr 192.168.255.1
prefix 64:ff9b::/96
dynamic-pool 192.168.255.0/24
```

---

## Диагностика и отладка NAT

### Проверка таблицы трансляций (Conntrack)

`conntrack` — основной инструмент для анализа состояния NAT.

```bash
# Просмотр всех активных трансляций
sudo conntrack -L

# Просмотр трансляций только для конкретного протокола
sudo conntrack -L -p tcp

# Удаление всех трансляций для конкретного IP (полезно при смене правил)
sudo conntrack -D -s 192.168.1.10

# Статистика conntrack (количество сессий, лимиты, ошибки)
sudo conntrack -S
# → result: entries 456, searching 0, found 12345, new 789...
```

### Оптимизация Conntrack (SRE Best Practices)

При переполнении таблицы в логах `dmesg` появляется ошибка `nf_conntrack: table full, dropping packet`.

```bash
# Просмотр текущего лимита
sysctl net.netfilter.nf_conntrack_max

# Тюнинг таймаутов для TCP ESTABLISHED (стандартно 5 дней, часто снижают до 1 часа)
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600

# Увеличение размера хеш-таблицы (рекомендуется NF_CONNTRACK_MAX / 8)
echo 131072 | sudo tee /sys/module/nf_conntrack/parameters/hashsize
```

### Обнаружение двойного NAT (Double NAT)

Если `traceroute` показывает два и более частных (RFC 1918) IP-адреса в первых прыжках — вы за двойным NAT.

```bash
traceroute -n 8.8.8.8
# 1. 192.168.1.1  (Ваш роутер)
# 2. 10.100.0.1   (NAT провайдера / CGNAT)  <-- Двойной NAT
```

### Верификация NAT Traversal (STUN)

```bash
# Установка клиента
sudo apt install stun-client

# Проверка типа NAT (важно для VoIP/WebRTC)
stun stun.l.google.com:19302
```

## Дополнительная информация

### См. также

- **[Теория NAT](./overview.md)** — глубокий разбор механизмов, типов и теории.
- **[Специальные IP-адреса](../../Protocols/IP_addressing/special_addresses.md)** — RFC 1918 и CGNAT.
- **[Nftables — Практика](../../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md)** — примеры фильтрации и NAT.
- **[Firewalld — Команды](../../../Linux/Networking/Settings/tools/firewalld.md)** — справочник команд.
- **[Netfilter в Linux](../../../Linux/Networking/Settings/tools/iptables_basics.md)** — архитектура цепочек.
