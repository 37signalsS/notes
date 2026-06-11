# nftables — сегментирование сети

## Определения

**Сегментирование сети** — разделение сетевой инфраструктуры на изолированные сегменты для ограничения распространения атак (Lateral Movement) и упрощения контроля доступа.

**Маршрутизатор (Router)** — устройство, работающее на L3 (Network Layer — сетевой уровень) модели OSI (Open Systems Interconnection), обеспечивающее передачу пакетов между разными IP-подсетями.

**Прозрачный межсетевой экран (Transparent Firewall)** — устройство, работающее на L2 (Data Link Layer — канальный уровень) модели OSI, фильтрующее трафик внутри одного сегмента (одной IP-подсети) без необходимости изменения маршрутизации узлов.

**ARP (Address Resolution Protocol — протокол разрешения адресов)** — протокол, используемый для определения MAC-адреса (Media Access Control) узла по его IP-адресу (Internet Protocol).

## Основные концепции

Сегментирование в nftables может быть реализовано двумя основными способами в зависимости от сетевой топологии:

1. **L3-сегментация (через маршрутизацию)**: Сеть делится на разные IP-подсети (например, `User` и `Server`). Межсетевой экран выступает шлюзом по умолчанию (Default Gateway) и фильтрует трафик в цепочке `forward` таблицы семейства `ip` или `inet`.
2. **L2-сегментация (через мост)**: Узлы остаются в одной IP-подсети, но физически или логически разделяются мостом (Bridge). Фильтрация происходит в цепочке `forward` таблицы семейства `bridge`.

Для управления доступом рекомендуется использовать **матрицу доступа**, которая затем транслируется в именованные наборы (sets) nftables. Это делает конфигурацию читаемой и упрощает её масштабирование.

---

## Практические сценарии

### Сценарий 1. Сегментирование на уровне маршрутизатора (L3)

**Задача**: Разделить сеть на пользовательский и серверный сегменты с жестким разграничением прав.

#### Архитектура

- **Пользовательский сегмент**: `192.168.0.0/24`
- **Серверный сегмент**: `172.30.0.0/24`
- **Файрвол-маршрутизатор**: имеет интерфейсы в обоих сегментах.

#### Матрица доступа (пример)

| Объект (Источник) | Субъект (Назначение) | Протокол / Порт | Описание роли |
| :--- | :--- | :--- | :--- |
| User1 (`192.168.0.101`) | Server1-2 (`172.30.0.101-102`) | TCP 80 | Доступ к Web-сервисам |
| User2 (`192.168.0.102`) | Server1-2 (`172.30.0.101-102`) | TCP 22 | Доступ по SSH (Secure Shell) |
| Все пользователи | DNS-сервер (`172.30.0.2`) | UDP 53 | Доступ к DNS (Domain Name System) |

#### Конфигурация nftables

```bash
#!/usr/sbin/nft -f

flush ruleset

table ip firewall {
    # Роль: Доступ к Web
    set web_users {
        type ipv4_addr
        elements = { 192.168.0.101 }
    }
    set web_servers {
        type ipv4_addr . inet_proto . inet_service
        elements = { 172.30.0.101 . tcp . 80, 172.30.0.102 . tcp . 80 }
    }

    # Роль: Доступ по SSH
    set ssh_users {
        type ipv4_addr
        elements = { 192.168.0.102 }
    }
    set ssh_servers {
        type ipv4_addr . inet_proto . inet_service
        elements = { 172.30.0.101 . tcp . 22, 172.30.0.102 . tcp . 22 }
    }

    # Роль: Доступ к DNS
    set dns_users {
        type ipv4_addr
        elements = { 192.168.0.0/24 }
    }
    set dns_servers {
        type ipv4_addr . inet_proto . inet_service
        elements = { 172.30.0.2 . udp . 53 }
    }

    chain fw_forward {
        type filter hook forward priority filter; policy drop;

        # Разрешить уже установленные соединения
        ct state established,related accept

        # Применение политик на основе наборов
        ip saddr @web_users ip daddr . meta l4proto . th dport @web_servers accept
        ip saddr @ssh_users ip daddr . meta l4proto . th dport @ssh_servers accept
        ip saddr @dns_users ip daddr . meta l4proto . th dport @dns_servers accept
    }
}
```

#### Активация маршрутизации в Linux

```bash
# Включить пересылку пакетов в ядре
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/95-ipv4-forward.conf
sysctl -p /etc/sysctl.d/95-ipv4-forward.conf
```

---

### Сценарий 2. Прозрачный межсетевой экран (L2 Bridge)

**Задача**: Внедрить фильтрацию трафика между группами узлов в одной подсети без изменения их настроек IP.

#### Особенности

- Все узлы находятся в подсети `172.30.0.0/24`.
- Межсетевой экран работает как "умный коммутатор" (Bridge).
- Не требует настройки Default Gateway на узлах для фильтрации внутри сегмента.

#### Конфигурация моста (Bridge)

```bash
# Установка необходимых утилит
apt update && apt install bridge-utils -y

# Пример настройки в /etc/network/interfaces
auto br0
iface br0 inet manual
    bridge_ports ens33 ens36
```

#### Конфигурация nftables (семейство bridge)

```bash
#!/usr/sbin/nft -f

flush ruleset

table bridge firewall {
    chain fw_forward {
        type filter hook forward priority filter; policy drop;

        # Критически важно для работы L2: разрешить ARP
        ether type arp accept

        # Разрешить установленные соединения
        ct state established,related accept

        # Пример фильтрации по IP внутри моста
        # (nftables в семействе bridge умеет заглядывать в IP-заголовки)
        ip saddr 172.30.0.11 ip daddr 172.30.0.101 tcp dport 80 accept
    }
}
```

> **Примечание**: Упрощенная реализация прозрачного файрвола, работающая по принципу "IP-диода", описана в заметке **[nftables — паттерн OneButtonFirewall](./one_button_firewall.md)**.

## Дополнительная информация

### См. также

- **[Сетевая сегментация и микросегментация](../../../../../Networking/Concepts/network_segmentation_and_microsegmentation.md)** — теоретические основы.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — устройство таблиц и цепочек.
- **[nftables — практические сценарии](./practical_scenarios.md)** — базовые настройки и NAT (Network Address Translation).
- **[nftables — моделирование угроз](./threat_modeling.md)** — алгоритм проектирования правил.
