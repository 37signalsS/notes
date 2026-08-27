# Conntrack Bypass (raw NOTRACK)

## Определения

**Conntrack Bypass (NOTRACK)** — механизм исключения сетевых соединений из таблицы отслеживания состояний (`conntrack`) ядра Linux. Реализуется через таблицу `raw` в Netfilter, которая обрабатывается раньше всех остальных таблиц и позволяет пометить пакеты меткой `NOTRACK` (iptables) или `notrack` (nftables).

**Зачем нужно:** Conntrack — ресурсоёмкий модуль. Каждая запись в таблице занимает ~300 байт RAM, а поиск по хеш-таблице добавляет задержку (~1–3 мкс на пакет). На балансировщиках, reverse-proxy и высоконагруженных NAT-шлюзах conntrack становится узким местом. NOTRACK позволяет обойти его для 특정ных потоков, снижая CPU и latency.

**Ключевой момент:** Пакеты с NOTRACK **не отслеживаются** — для них не работают stateful-правила (`-m conntrack --ctstate`), автоматический обратный DNAT/SNAT, и другие механизмы, зависящие от conntrack. Это trade-off: производительность vs функциональность.

## Теоретический блок

### Порядок обработки таблиц Netfilter

```
Входящий пакет
    │
    ▼
  raw (PREROUTING)  ← NOTRACK здесь, ПЕРВЫМ делом
    │
    ▼
  conntrack (если не NOTRACK)
    │
    ▼
  nat (PREROUTING)  ← DNAT здесь
    │
    ▼
  Маршрутизация
    │
    ▼
  filter            ← Фильтрация
    │
    ▼
  nat (POSTROUTING) ← SNAT здесь
    │
    ▼
  Исходящий пакет
```

**Важно:** Таблица `raw` обрабатывается **до** conntrack. Если пакет помечен как NOTRACK в `raw`, он полностью пропускает модуль conntrack — для него не создаётся запись, не проверяются stateful-правила, и не выполняется автоматическая обратная трансляция.

### Когда использовать NOTRACK

| Сценарий | Причина | Эффект |
| :--- | :--- | :--- |
| **Балансировщик нагрузки (L4)** | Conntrack не нужен — балансировщик просто перенаправляет пакеты | Снижение CPU на 10–30%, уменьшение задержки |
| **Reverse-proxy (nginx/haproxy)** | Прокси сам отслеживает соединения, conntrack дублирует | Снижение потребления RAM, ускорение обработки |
| **Высоконагруженный NAT-шлюз** | conntrack не успевает обрабатывать Millions pps | Увеличение пропускной способности |
| **Диагностика и тестирование** | Изоляция конкретного трафика от conntrack | Упрощение отладки |

### Когда НЕ использовать NOTRACK

| Сценарий | Почему нельзя |
| :--- | :--- |
| **SNAT/DNAT** | NAT зависит от conntrack — без него трансляция не работает |
| **Stateful firewall** | Правила `ESTABLISHED,RELATED` требуют conntrack |
| **Hairpin NAT** | Обратная трансляция невозможна без conntrack-записи |
| **FTP/SIP ALG** | Conntrack helpers не работают для NOTRACK-пакетов |
| **VPN (IPsec, WireGuard)** | Туннельные протоколы используют conntrack для NAT-T |

### Влияние на производительность

| Параметр | С conntrack | Без conntrack (NOTRACK) |
| :--- | :--- | :--- |
| **Задержка (latency)** | +1–3 мкс на пакет | Нет накладных расходов |
| **Потребление RAM** | ~300 байт на запись | 0 |
| **CPU (softirq)** | Поиск по хеш-таблице | Прямая обработка |
| **Максимум pps** | ~1–2M pps (зависит от CPU) | ~5–10M pps |

## Практический блок

### Настройка через iptables

```bash
# Исключение HTTPS-трафика из conntrack (для балансировщика)
iptables -t raw -A PREROUTING -p tcp --dport 443 -j NOTRACK
iptables -t raw -A OUTPUT -p tcp --sport 443 -j NOTRACK

# Исключение трафика к конкретному серверу
iptables -t raw -A PREROUTING -d 192.168.1.100 -j NOTRACK
iptables -t raw -A OUTPUT -s 192.168.1.100 -j NOTRACK

# Просмотр правил raw
iptables -t raw -L -v -n
```

### Настройка через nftables

```bash
# Создание таблицы raw
nft add table ip raw

# Цепочка PREROUTING
nft add chain ip raw prerouting { type filter hook prerouting priority -300 \; }

# Исключение HTTPS из conntrack
nft add rule ip raw prerouting tcp dport 443 notrack

# Исключение трафика к серверу
nft add rule ip raw prerouting ip daddr 192.168.1.100 notrack

# Просмотр таблицы
nft list table ip raw
```

### Сочетание NOTRACK с stateless-фильтрацией

При использовании NOTRACK нельзя применять stateful-правила. Вместо них используются stateless-правила с явным указанием направления:

```bash
# Пример: балансировщик с NOTRACK + stateless-фильтрация
# Входящий трафик на 443 — разрешаем
iptables -t raw -A PREROUTING -p tcp --dport 443 -j NOTRACK
iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# Исходящий трафик с 443 — разрешаем
iptables -t raw -A OUTPUT -p tcp --sport 443 -j NOTRACK
iptables -A OUTPUT -p tcp --sport 443 -j ACCEPT
```

**Nftables-эквивалент:**
```bash
nft add rule ip raw prerouting tcp dport 443 notrack
nft add rule ip filter input tcp dport 443 accept
nft add rule ip raw output tcp sport 443 notrack
nft add rule ip filter output tcp sport 443 accept
```

### Мониторинг: сколько пакетов обходит conntrack

```bash
# Через conntrack -S: проверить количество "ignore"
conntrack -S
# → ignore 1234567 (количество пакетов, пропущенных через NOTRACK)

# Через nstat: детальная статистика
nstat -az | grep -i "raw\|notrack\|conntrack"
# → TcpExtRawPacketsFiltered — пакеты, обработанные в raw
```

### Проверка, что NOTRACK работает

```bash
# 1. Добавить правило NOTRACK
iptables -t raw -A PREROUTING -p tcp --dport 8080 -j NOTRACK

# 2. Установить соединение к порту 8080
curl http://192.168.1.10:8080

# 3. Проверить: conntrack НЕ должен показывать эту сессию
conntrack -L -p tcp --dport 8080
# → Пустой вывод (записи нет)

# 4. Без NOTRACK: conntrack покажет запись
conntrack -L -p tcp --dport 8080
# → tcp 6 120 ESTABLISHED src=... dst=...
```

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| NAT перестал работать после добавления NOTRACK | NOTRACK отключает conntrack, от которого зависит NAT | Убрать NOTRACK для NAT-трафика |
| Правила `ESTABLISHED` не совпадают | NOTRACK-пакеты не попадают в conntrack | Использовать stateless-правила |
| conntrack -L не показывает соединение | Пакет помечен NOTRACK | Это нормально — проверяйте через tcpdump |
| Высокий CPU после включения NOTRACK | NOTRACK-пакеты обрабатываются без оптимизаций conntrack | Проверьте, действительно ли$conntrack был узким местом |

## Дополнительная информация

- **[Теория NAT](./overview.md)** — архитектура conntrack, таймауты, рекомендации SRE.
- **[Практические сценарии NAT](./practical_scenarios.md)** — диагностика, оптимизация conntrack.
- **[Netfilter в Linux](../../../Linux/Networking/Settings/tools/iptables_basics.md)** — таблицы и цепочки Netfilter.
- **[Nftables: Threat Modeling](../../../Linux/Networking/Settings/tools/nftables/threat_modeling.md)** — SYN proxy через raw + notrack.
