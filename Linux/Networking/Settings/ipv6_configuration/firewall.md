# Настройка файрвола для IPv6 в Linux

---

**Reliability Score: 10** (SSoT + Современные стандарты 2026 года)  
**Freshness: Актуально на июль 2026**

---

## Определения

**IPv6 Firewall** — механизм фильтрации сетевого трафика для адресов длиной 128 бит. В Linux реализуется через фреймворк **Netfilter**.

**ICMPv6 (Internet Control Message Protocol for IPv6)** — фундаментальный протокол, обеспечивающий работу базовых функций IPv6 (обнаружение соседей, согласование MTU, многоадресная рассылка). В отличие от IPv4, полное блокирование ICMPv6 делает работу сети невозможной.

## Основные концепции

### Эволюция инструментов

1.  **nftables (Рекомендуется)**: современный стандарт. Использует семейство `inet` для управления правилами IPv4 и IPv6 в рамках единой таблицы.
2.  **firewalld / UFW**: высокоуровневые оболочки (front-ends), использующие `nftables` в качестве бэкенда в современных дистрибутивах.
3.  **ip6tables (Legacy)**: классический инструмент. Управляет правилами IPv6 отдельно от IPv4. Требует ручного дублирования политик безопасности.

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

        # 4. Разрешить SSH (пример для конкретных портов)
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

# Разрешить конкретный адрес IPv6
sudo ufw allow from 2001:db8::/32
```

### 3. firewalld (RHEL / Fedora / Alma / Rocky)

Управление через зоны. Команды без флага `--ipv6` применяются к обоим стекам.

```bash
# Разрешить сервис (IPv4 + IPv6)
sudo firewall-cmd --permanent --add-service=http

# Разрешить специфический порт только для IPv6
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv6" port port="8080" protocol="tcp" accept'

sudo firewall-cmd --reload
```

### 4. ip6tables (Legacy подход)

Используется в старых системах или специфических контейнерных окружениях.

```bash
# Базовая политика безопасности
sudo ip6tables -P INPUT DROP
sudo ip6tables -P FORWARD DROP

# Разрешить established и loopback
sudo ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo ip6tables -A INPUT -i lo -j ACCEPT

# Разрешить ICMPv6 (упрощенно)
sudo ip6tables -A INPUT -p icmpv6 -j ACCEPT

# Разрешить SSH
sudo ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT
```

## Диагностика и проверка

### Проверка правил

```bash
# nftables
sudo nft list ruleset

# firewalld
sudo firewall-cmd --list-all

# ufw
sudo ufw status verbose
```

### Тестирование портов

```bash
# Использование netcat (флаг -6 обязателен для адресов)
nc -6 -zv 2001:db8::1 80

# Сканирование через nmap
nmap -6 -p 80,443 2001:db8::1
```

## Дополнительная информация

### Типичные ошибки

- **Блокировка ICMPv6 Type 2 (Packet Too Big)**: приводит к тому, что маленькие пакеты проходят (например, SSH логин), а большие (вывод `ls -l` или HTTP-ответ) блокируются. Это классический симптом проблемы PMTUD.
- **Отсутствие правил в ip6tables**: часто администраторы настраивают только `iptables` (IPv4), оставляя IPv6 либо полностью закрытым (policy DROP), либо полностью открытым (policy ACCEPT по умолчанию).
- **Использование NAT для IPv6**: в IPv6 не рекомендуется использовать NAT (NAT66). Вместо него следует использовать прямую маршрутизацию и фильтрацию на уровне GUA (Global Unicast Address).

### См. также

- **[Общие вопросы сохранения правил](../tools/firewall_common.md)** — персистентность конфигурации.
- **[Настройка адресов IPv6](./address_configuration.md)** — подготовка сетевых интерфейсов.
- **[Диагностика сети](./diagnostics.md)** — инструменты проверки связности и поиска ошибок NDP.
- **[nftables: практические сценарии](../tools/nftables/practical_scenarios.md)** — глубокое погружение в синтаксис `nft`.
