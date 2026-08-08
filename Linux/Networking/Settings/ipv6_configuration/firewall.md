# Настройка файрвола для IPv6 в Linux

## Определения

**IPv6 Firewall** — механизм фильтрации сетевого трафика для адресов длиной 128 бит. В Linux реализуется через фреймворк **Netfilter**.

**ICMPv6 (Internet Control Message Protocol for IPv6)** — фундаментальный протокол, обеспечивающий работу базовых функций IPv6 (обнаружение соседей, согласование MTU, многоадресная рассылка). В отличие от IPv4, полное блокирование ICMPv6 делает работу сети невозможной.

## Основные концепции

### Эволюция инструментов

1.  **nftables (Рекомендуется)**: современный стандарт. Использует семейство `inet` для управления правилами IPv4 и IPv6 в рамках единой таблицы. Позволяет эффективно фильтровать трафик по специфичным для IPv6 полям (например, Extension Headers).
2.  **firewalld / UFW**: высокоуровневые оболочки (front-ends), использующие `nftables` в качестве бэкенда в современных дистрибутивах.
3.  **ip6tables (Legacy)**: классический инструмент. Управляет правилами IPv6 отдельно от IPv4. Требует ручного дублирования политик безопасности и менее эффективен при работе с наборами данных (sets).

### Критическая роль ICMPv6

Для корректной работы стека IPv6 **необходимо** разрешать следующие типы сообщений:

| Тип | Название | Функция | Последствия блокировки |
| :--- | :--- | :--- | :--- |
| **1-4** | Error Messages | Сообщения об ошибках | Невозможность диагностики и работы протоколов |
| **2** | Packet Too Big | **PMTUD** | "Зависание" сессий при передаче больших пакетов |
| **133-136** | NDP Messages | **Neighbor Discovery** | Хосты не видят друг друга и шлюз (аналог ARP) |
| **130-132** | MLD Messages | Multicast Discovery | Нарушение работы Multicast и IPv6-групп |
| **128-129** | Echo Req/Reply | Ping | Невозможность базовой проверки связности |

## Практические сценарии

### 1. nftables (Современный стандарт)

Использование семейства `inet` позволяет создать универсальный файрвол.

```bash
# /etc/nftables.conf

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Разрешить Loopback
        iif lo accept

        # 2. Разрешить установленные и связанные соединения
        ct state established,related accept

        # 3. Разрешить критический ICMPv6
        icmpv6 type {
            destination-unreachable, packet-too-big, time-exceeded,
            parameter-problem, echo-request, echo-reply,
            nd-router-solicit, nd-router-advert,
            nd-neighbor-solicit, nd-neighbor-advert,
            mld-listener-query, mld-listener-report, mld-listener-done
        } accept

        # 4. Ограничение входящих Router Advertisements (защита от ложных роутеров)
        # Принимать RA только от доверенного Link-Local адреса шлюза (пример)
        # ip6 saddr fe80::1 icmpv6 type nd-router-advert accept

        # 5. Разрешить стандартные сервисы
        tcp dport { 22, 80, 443 } accept
    }
}
```

### 2. UFW (Ubuntu / Debian)

UFW автоматически настраивает базовые правила для IPv6, если в `/etc/default/ufw` параметр `IPV6=yes`.

```bash
# Проверка статуса IPv6 в UFW
grep "IPV6=" /etc/default/ufw

# Разрешить порт для обоих протоколов (IPv4 и IPv6)
sudo ufw allow 22/tcp

# Разрешить конкретную сеть IPv6
sudo ufw allow from 2001:db8:1::/64
```

### 3. firewalld (RHEL / Fedora)

Управление через зоны. Команды без флага `--ipv6` применяются к обоим стекам.

```bash
# Разрешить сервис (IPv4 + IPv6)
sudo firewall-cmd --permanent --add-service=http

# Разрешить специфический порт только для IPv6 через Rich Rules
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv6" port port="8080" protocol="tcp" accept'

sudo firewall-cmd --reload
```

## Безопасность и защита

### Фильтрация по Scope ID и Link-Local

Пакеты с адресами Link-Local (`fe80::/10`) не должны покидать пределы L2-сегмента. На маршрутизаторах рекомендуется блокировать такие адреса на внешних интерфейсах в цепочке `forward`.

### Проверка обратного пути (uRPF) для IPv6

В отличие от IPv4, где есть `sysctl net.ipv4.conf.all.rp_filter`, для IPv6 в Linux uRPF настраивается через файрвол:

```bash
# Пример для nftables
table inet filter {
    chain prerouting {
        type filter hook prerouting priority -150;
        # Проверка, что адрес отправителя доступен через тот же интерфейс, с которого пришел пакет
        fib saddr . iif oif exists accept
        drop
    }
}
```

### Обработка Extension Headers

Злоумышленники могут использовать Extension Headers для обхода файрволов или DoS-атак. `nftables` позволяет фильтровать пакеты с избыточными заголовками:

```bash
# Пример: ограничение длины Hop-by-Hop или фильтрация специфичных заголовков
ip6 extension header hop-by-hop drop
```

## Диагностика и проверка

### Проверка активных правил

```bash
# nftables (показать весь набор)
sudo nft list ruleset

# firewalld (показать настройки текущей зоны)
sudo firewall-cmd --list-all

# ufw (статус и пронумерованные правила)
sudo ufw status numbered
```

### Тестирование связности

```bash
# Использование netcat (флаг -6 для IPv6)
nc -6 -zv 2001:db8::1 80

# Сканирование через nmap с указанием интерфейса для Link-Local
nmap -6 -p 22 fe80::215:5dff:fe1e:81e%eth0
```

## Дополнительная информация

### Типичные ошибки

- **Блокировка ICMPv6 Type 2 (Packet Too Big)**: разрушает механизм Path MTU Discovery. Симптом: мелкие пакеты проходят, большие сессии (например, передача файлов) "зависают".
- **Асимметрия правил**: ситуация, когда `iptables` настроен, а `ip6tables` оставлен с политикой `ACCEPT` по умолчанию (или наоборот, всё закрыто, включая NDP).
- **NDP на мостах (Bridges)**: при использовании `ebtables` или `nftables bridge` случайная блокировка Multicast-адресов приводит к потере связи между узлами в одном сегменте.

### См. также

- **[Общие вопросы сохранения правил](../tools/firewall_common.md)** — персистентность конфигурации.
- **[Настройка адресов IPv6](./address_configuration.md)** — подготовка сетевых интерфейсов.
- **[Диагностика сети](./diagnostics.md)** — инструменты проверки связности и поиска ошибок NDP.
- **[nftables: практические сценарии](../tools/nftables/practical_scenarios.md)** — глубокое погружение в синтаксис `nft`.
