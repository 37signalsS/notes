# nftables: миграция, инструменты и справочная информация

## Сравнение синтаксиса iptables и nftables

| iptables | nftables |
| :--- | :--- |
| `iptables -A INPUT -p tcp --dport 22 -j ACCEPT` | `nft add rule inet filter input tcp dport 22 accept` |
| `iptables -F` | `nft flush ruleset` |
| `iptables -L -n -v` | `nft list ruleset` |
| `iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE` | `nft add rule nat postrouting oif eth0 masquerade` |

---

## Миграция с iptables

### Утилиты для конвертации (пакет `iptables`)

- `iptables-translate` — конвертация отдельных команд
- `iptables-restore-translate` — конвертация файлов restore
- `iptables-nft-restore` — прямое восстановление в nftables

### Пример конвертации

```bash
# Исходная команда iptables
iptables -A INPUT -i eth0 -p tcp --dport 80 -j DROP

# После iptables-translate
nft add rule ip filter INPUT iifname "eth0" tcp dport 80 counter drop
```

**Важно:** Сконвертированные правила могут не работать, если не созданы соответствующие таблицы и цепочки. В nftables **нет предопределённых таблиц** — их нужно создавать явно.

### Порядок миграции

1. Проверить поддержку: `nft list ruleset`
2. Экспортировать правила: `iptables-save > iptables-rules.txt`
3. Конвертировать: `iptables-restore-translate < iptables-rules.txt`
4. Отредактировать, добавить таблицы и цепочки
5. Протестировать перед применением

---

## Инструменты управления

| Инструмент | Описание |
| :--- | :--- |
| `nft` | Основная утилита управления |
| `nft list ruleset` | Просмотр всех правил |
| `nft list ruleset -a` | Просмотр с хэндлами (для удаления) |
| `nft flush ruleset` | Очистка всех правил |
| `nft -c -f <file>` | Проверка синтаксиса файла |
| `nft -j list ruleset` | Экспорт в JSON |
| `nft describe <object>` | Подробная информация об объекте |

---

## Payload expressions (отбор по содержимому пакетов)

### Основные поля заголовков

```
# Ethernet
ether { daddr | saddr | type }

# VLAN
vlan { id | dei | pcp | type }

# ARP
arp { htype | ptype | hlen | plen | operation | saddr { ip | ether } | daddr { ip | ether } }

# IPv4
ip { version | hdrlength | dscp | ecn | length | id | frag-off | ttl | protocol | checksum | saddr | daddr }

# ICMP
icmp { type | code | checksum | id | sequence | gateway | mtu }

# IPv6
ip6 { version | dscp | ecn | flowlabel | length | nexthdr | hoplimit | saddr | daddr }

# ICMPv6
icmpv6 { type | code | checksum | parameter-problem | packet-too-big | id | sequence | max-delay }

# TCP
tcp { sport | dport | sequence | ackseq | doff | reserved | flags | window | checksum | urgptr }

# UDP
udp { sport | dport | length | checksum }
```

### RAW payload expression (для протоколов без шаблона)

```bash
# Синтаксис: @base,offset,length
# base: ll (link), nh (network), th (transport)

# Выбрать TCP/UDP пакеты на порты 53, 80
nft add rule filter input meta l4proto { tcp, udp } @th,16,16 { 53, 80 }

# То же с готовым шаблоном (проще)
nft add rule filter input meta l4proto { tcp, udp } th dport { 53, 80 } accept
```

---

## Метаусловия (meta expression)

### С обязательным `meta`

```
meta { length | nfproto | l4proto | protocol | priority }
```

### С опциональным `meta`

```
[meta] { mark | iif | iifname | iiftype | oif | oifname | oiftype |
         skuid | skgid | nftrace | rtclassid | ibrname | obrname |
         pkttype | cpu | iifgroup | oifgroup | cgroup | random |
         ipsec | iifkind | oifkind | time | hour | day }
```

### Примеры

```bash
# Фильтрация по времени
nft add rule filter input meta hour "09:00-18:00" accept

# По CPU
nft add rule filter input meta cpu 0-3 accept

# Случайное число (для балансировки)
nft add rule nat prerouting numgen random mod 100 vmap { 0-69 : jump chain1 }
```

---

## Ссылки по теме

- **[Сохранение правил](../firewall_common.md#сохранение-правил-между-перезагрузками)** — общие вопросы
- **[Лучшие практики правил](../../../../../Networking/Concepts/firewall_rules_best_practices.md)** — принципы проектирования
- **[Концепции сетевых файрволов](../../../../../Networking/Concepts/firewall_concepts.md)** — теория Netfilter
- **[Docker интеграция](../../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — взаимодействие с Docker
