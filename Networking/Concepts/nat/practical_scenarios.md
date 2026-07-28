---
reliability: 10
updated: 2026-07-27
---

# NAT — Практические сценарии

## Настройка NAT (Masquerading) в Linux

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
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
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

---

## Настройка Hairpin NAT (Loopback NAT)

**Проблема:** Внутренний клиент обращается к внутреннему серверу по **публичному** IP-адресу.

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

Сценарий: Доступ к серверу B (внутренний) через сервер A (шлюз) без использования SSH-туннелей (ProxyJump).

**На сервере A:**

1. **DNAT:**
   ```bash
   iptables -t nat -A PREROUTING -p tcp --dport 2222 -j DNAT --to-destination 192.168.1.20:22
   ```

2. **SNAT (для корректного обратного пути):**
   ```bash
   iptables -t nat -A POSTROUTING -d 192.168.1.20 -o eth1 -j MASQUERADE
   ```

---

## NAT в облачных инфраструктурах

В облаках (Yandex Cloud, AWS) классический NAT на ВМ заменяется управляемыми шлюзами.

*   **Yandex Cloud:** Используется **NAT Gateway**. Маршрутизация настраивается через таблицу маршрутов: `0.0.0.0/0 -> NAT Gateway`. Подробнее: **[VPC и NAT в Yandex Cloud](../../../Yandex/VPC.md#nat-gateway-шлюз-nat)**.
*   **Kubernetes:** NAT используется для маскировки трафика подов при выходе за пределы узла (`IP Masquerade Agent`).

---

## Технологии перехода на IPv6 (NAT64)

В средах IPv6-only используется NAT64 для доступа к IPv4-интернету.

**Пример конфигурации Tayga (Linux):**
```ini
# /etc/tayga.conf
tun-device nat64
ipv4-addr 192.168.255.1
prefix 64:ff9b::/96
```

---

## Диагностика и отладка NAT

### Проверка таблицы трансляций (Conntrack)
```bash
# Просмотр всех активных трансляций
sudo conntrack -L

# Статистика conntrack (количество сессий, лимиты)
sudo conntrack -S

# Топ-10 IP по количеству соединений
sudo conntrack -L | awk '{print $4}' | cut -d= -f2 | sort | uniq -c | sort -nr | head -n 10
```

### Оптимизация Conntrack (SRE Best Practices)
При высокой нагрузке (тысячи соединений) стандартные лимиты могут быть исчерпаны.

```bash
# Просмотр текущего лимита
sysctl net.netfilter.nf_conntrack_max

# Увеличение лимита (например, до 1 млн)
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576
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

# Проверка типа NAT
stun stun.l.google.com:19302
# → result: Primary: Independent, Secondary: Port Restricted
```

## Связанные документы

- **[Теория NAT](./overview.md)** — глубокий разбор механизмов, типов и теории.
- **[Специальные IP-адреса](../../Protocols/IP_addressing/special_addresses.md)** — RFC 1918 и CGNAT.
- **[Nftables — Практика](../../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md)** — примеры фильтрации и NAT.
- **[Firewalld — Команды](../../../Linux/Networking/Settings/tools/firewalld.md)** — справочник команд.
- **[Netfilter в Linux](../../../Linux/Networking/Settings/tools/iptables_basics.md)** — архитектура цепочек.
