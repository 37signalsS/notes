# Настройка файрвола для IPv6 в Linux

## Определения

**IPv6 Firewall** — механизм фильтрации трафика, работающий с адресами длиной 128 бит. В Linux фильтрация IPv6 реализована как часть фреймворка Netfilter, но управляется отдельно от IPv4 в классических утилитах.

**ICMPv6 (Internet Control Message Protocol for IPv6)** — критически важный протокол для функционирования IPv6. В отличие от IPv4, где ICMP часто блокируют в целях безопасности, полное блокирование ICMPv6 нарушает работу сети (NDP, PMTUD).

## Основные концепции

### Разделение стеков

В классических инструментах фильтрации (iptables) правила для IPv4 и IPv6 хранятся в разных таблицах и управляются разными утилитами:

- `iptables` — только для IPv4.
- `ip6tables` — только для IPv6.

Современные инструменты (`nftables`, `firewalld`) позволяют управлять обоими протоколами в рамках единых правил или зон, но внутренне всё равно разделяют обработку пакетов.

### Критическая важность ICMPv6

Для корректной работы IPv6 необходимо разрешать следующие типы ICMPv6 сообщений:

1. **Neighbor Discovery Protocol (NDP)**: сообщения `Neighbor Solicitation` и `Neighbor Advertisement` (аналог ARP). Без них хосты не найдут друг друга в локальном сегменте.
2. **Path MTU Discovery (PMTUD)**: сообщения `Packet Too Big`. В IPv6 нет фрагментации на маршрутизаторах, поэтому хост должен знать реальный MTU на всем пути.
3. **Multicast Listener Discovery (MLD)**: необходимо для работы групп рассылки.

## Практические сценарии

### Настройка через firewalld (RHEL/CentOS/Fedora)

`firewalld` поддерживает IPv6 "из коробки" через концепцию зон.

**Разрешение ICMPv6 (обычно разрешено в стандартных зонах):**

```bash
firewall-cmd --permanent --add-protocol=icmpv6
firewall-cmd --reload
```

**Открытие портов для IPv6:**
Команды без флага `--ipv6` применяются к обоим протоколам, если не указано иное.

```bash
# Разрешить HTTP/HTTPS для всех протоколов
firewall-cmd --permanent --add-service=http
firewall-cmd --permanent --add-service=https

# Разрешить порт только для IPv6
firewall-cmd --permanent --add-port=8080/tcp --ipv6
```

### Настройка через ip6tables (классический подход)

Базовый набор правил для защищенного узла:

```bash
# 1. Разрешить установленные соединения
sudo ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 2. Разрешить loopback (важно для локальных сервисов)
sudo ip6tables -A INPUT -i lo -j ACCEPT

# 3. Разрешить ICMPv6 (обязательно!)
sudo ip6tables -A INPUT -p icmpv6 -j ACCEPT

# 4. Разрешить входящий SSH
sudo ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT

# 5. Установить политику DROP по умолчанию
sudo ip6tables -P INPUT DROP
sudo ip6tables -P FORWARD DROP
```

### Настройка через nftables (современный подход)

В `nftables` рекомендуется использовать семейство `inet` для общих правил или `ip6` для специфичных.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить loopback и установленные соединения
        iif lo accept
        ct state established,related accept

        # Разрешить ICMPv6
        ip6 nexthdr icmpv6 accept

        # Разрешить порты
        tcp dport { 22, 80, 443 } accept
    }
}
```

### Диагностика и проверка

Проверка доступности порта по IPv6:

```bash
# Использование netcat
nc -6 -zv <ipv6_address> 80

# Использование nmap
nmap -6 -p 80,443 <ipv6_address>
```

## Дополнительная информация

### Типичные ошибки

- **Блокировка всех ICMPv6**: приводит к "зависанию" соединений из-за невозможности согласовать MTU.
- **Отсутствие правил в ip6tables**: если настроен только `iptables`, IPv6 остается полностью открытым или полностью закрытым в зависимости от политики ядра по умолчанию.

### См. также

- **[Общие вопросы сохранения правил](../tools/firewall_common.md)** — персистентность конфигурации в разных дистрибутивах.
- **[Настройка адресов IPv6](./address_configuration.md)** — подготовка сетевых интерфейсов.
- **[Диагностика сети](./diagnostics.md)** — инструменты проверки связности.
