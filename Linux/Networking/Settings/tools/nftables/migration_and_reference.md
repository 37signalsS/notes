# nftables — миграция и справочник синтаксиса

## Определения

**Миграция на nftables** — процесс перехода от использования классического набора утилит `iptables` к современной подсистеме `nftables`, включающий конвертацию правил и адаптацию скриптов управления.

**Трансляция правил** — автоматизированное или ручное преобразование синтаксиса правил `iptables` в эквивалентные выражения `nftables`.

**Payload expressions (Выражения содержимого)** — механизмы nftables для извлечения и проверки данных непосредственно из заголовков пакетов различных уровней (сетевого, транспортного и др.).

**Meta expressions (Метавыражения)** — параметры правил, относящиеся к метаданным пакета, которые не содержатся в его заголовках (например, индекс входящего интерфейса, время получения пакета, идентификатор пользователя процесса).

## Основные концепции

### Сравнение синтаксиса iptables и nftables

| Задача | iptables (устаревший) | nftables (современный) |
| :--- | :--- | :--- |
| Добавить правило | `iptables -A INPUT -p tcp --dport 22 -j ACCEPT` | `nft add rule inet filter input tcp dport 22 accept` |
| Очистить все правила | `iptables -F` | `nft flush ruleset` |
| Просмотреть правила | `iptables -L -n -v` | `nft list ruleset` |
| Настройка NAT | `iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE` | `nft add rule nat postrouting oif eth0 masquerade` |

### Инструменты управления (CLI — Command Line Interface)

Утилита `nft` является единой точкой управления всеми семействами протоколов.

| Команда | Описание |
| :--- | :--- |
| `nft list ruleset` | Вывод всех текущих правил и таблиц |
| `nft list ruleset -a` | Вывод с хэндлами (уникальными идентификаторами правил) |
| `nft flush ruleset` | Полная очистка текущей конфигурации в памяти |
| `nft -c -f <файл>` | Проверка синтаксиса конфигурационного файла без применения |
| `nft -j list ruleset` | Экспорт конфигурации в формате **JSON (JavaScript Object Notation)** |
| `nft describe <объект>` | Получение подробной справки о полях и типах данных объекта |

## Практические сценарии

### 1. Миграция с iptables

В состав пакета `iptables` входят утилиты для автоматизации перехода.

**Инструменты конвертации:**

- `iptables-translate`: конвертирует одну команду `iptables` в формат `nft`.
- `iptables-restore-translate`: принимает на вход файл в формате `iptables-save` и выводит готовый набор правил для `nftables`.

**Пример использования `iptables-translate`:**

```bash
# Исходная команда iptables
iptables -A INPUT -i eth0 -p tcp --dport 80 -j DROP

# Результат трансляции
nft add rule ip filter INPUT iifname "eth0" tcp dport 80 counter drop
```

**Важно:** В nftables отсутствуют предопределенные таблицы (такие как `filter` или `nat`). Сгенерированные правила не будут работать, пока в системе не созданы соответствующие таблицы и цепочки. Подробнее об этом: **[nftables: архитектура и основные концепции](./architecture_and_concepts.md)**.

**Алгоритм миграции:**

1. Выполните экспорт старых правил: `iptables-save > rules.ipt`.
2. Проведите трансляцию: `iptables-restore-translate -f rules.ipt > rules.nft`.
3. Отредактируйте `rules.nft`, добавив определения таблиц и цепочек (Hooks).
4. Проверьте синтаксис: `nft -c -f rules.nft`.
5. Примените правила: `nft -f rules.nft`.

### 2. Справочник выражений для заголовков пакетов

nftables позволяет гибко фильтровать трафик по полям различных протоколов.

**Сетевые и транспортные протоколы:**

- **Ethernet**: `ether { daddr | saddr | type }`
- **VLAN (Virtual Local Area Network)**: `vlan { id | dei | pcp | type }`
- **ARP (Address Resolution Protocol)**: `arp { htype | ptype | hlen | plen | operation | saddr { ip | ether } | daddr { ip | ether } }`
- **IPv4 (Internet Protocol v4)**: `ip { version | hdrlength | dscp | ecn | length | id | frag-off | ttl | protocol | checksum | saddr | daddr }`
- **IPv6**: `ip6 { version | dscp | ecn | flowlabel | length | nexthdr | hoplimit | saddr | daddr }`
- **TCP (Transmission Control Protocol)**: `tcp { sport | dport | sequence | ackseq | flags | window | checksum }`
- **UDP (User Datagram Protocol)**: `udp { sport | dport | length | checksum }`
- **ICMP (Internet Control Message Protocol)**: `icmp { type | code | id | sequence }`

**Пример RAW-выражения (для данных по смещению):**

```bash
# Синтаксис: @base,offset,length (base: ll - link, nh - network, th - transport)
# Проверка первых двух байтов транспортного заголовка (обычно sport)
nft add rule filter input @th,0,16 53
```

### 3. Использование метаданных (Meta expressions)

Метаданные позволяют строить правила на основе контекста прохождения пакета.

**Часто используемые мета-поля:**

- `iifname`, `oifname`: имена входящего и исходящего интерфейсов.
- `skuid`, `skgid`: идентификаторы пользователя и группы владельца сокета (только для локального трафика).
- `time`, `day`, `hour`: фильтрация по времени.
- `protocol`: сетевой протокол (например, `ip`, `ip6`).

**Пример: Ограничение доступа по времени:**

```bash
# Разрешить входящий трафик только в рабочее время
nft add rule inet filter input meta hour "09:00-18:00" accept
```

**Пример: Балансировка на основе случайного числа:**

```bash
# Перенаправлять 30% трафика в другую цепочку
nft add rule nat prerouting numgen random mod 100 vmap { 0-29 : jump chain1, 30-99 : accept }
```

## Дополнительная информация

### Ссылки по теме

- **[nftables: архитектура и основные концепции](./architecture_and_concepts.md)** — основы иерархии (таблицы, цепочки).
- **[nftables: практические сценарии](./practical_scenarios.md)** — готовые примеры настройки NAT и защиты от атак.
- **[Сохранение правил файрвола](../firewall_common.md#сохранение-правил-между-перезагрузками)** — обеспечение персистентности конфигурации.
- **[Рекомендации по проектированию правил](../../../../../Networking/Concepts/firewall_rules_best_practices.md)** — общие принципы безопасности.
- **[Интеграция с Docker](../../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — особенности работы в контейнеризированных средах.
