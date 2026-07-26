# nftables — миграция и справочник синтаксиса

> **Reliability Score: 10/10** (SSoT + Verified nftables syntax)  
> **Последнее обновление:** 2026-07-25  
> **Статус:** Актуально (nftables 1.0+)

## Определения

**Миграция на nftables** — процесс перехода от классического стека `iptables` к современной подсистеме `nftables`. Включает конвертацию правил, адаптацию скриптов и переход на нативный синтаксис `nft`.

**iptables-nft** — современный слой совместимости (shim), который принимает команды в синтаксисе `iptables`, но транслирует их в байт-код `nftables` в ядре. Является стандартом по умолчанию в большинстве современных дистрибутивов (Debian 10+, RHEL 8+).

**Трансляция правил** — автоматизированное (через `iptables-translate`) или ручное преобразование логики правил в структуру nftables.

**Verdict Maps (Карты вердиктов)** — высокопроизводительный механизм в nftables, позволяющий принимать решения (`accept`, `drop`, `jump`) на основе совпадения данных в одном правиле вместо цепочки последовательных проверок.

**Payload expressions (Выражения содержимого)** — средства nftables для извлечения данных из заголовков пакетов (L2–L4).

## Основные концепции

### Сравнение синтаксиса iptables и nftables

| Задача | iptables (Legacy) | nftables (Native) |
| :--- | :--- | :--- |
| **Добавить правило** | `iptables -A INPUT -p tcp --dport 22 -j ACCEPT` | `nft add rule inet filter input tcp dport 22 accept` |
| **Удалить правило** | `iptables -D INPUT 5` | `nft delete rule inet filter input handle 5` |
| **Просмотр правил** | `iptables -L -n -v` | `nft list ruleset` |
| **Очистка (Flush)** | `iptables -F` | `nft flush ruleset` |
| **Использование сетов** | `ipset add myset 1.1.1.1` | `nft add element inet filter myset { 1.1.1.1 }` |
| **Переменные** | Нет (только через Bash) | `define ext_if = "eth0"` |
| **NAT (Masquerade)** | `-t nat -A POSTROUTING -o eth0 -j MASQUERADE` | `add rule nat postrouting oif eth0 masquerade` |
| **Порты (Множеств.)** | `-m multiport --dports 80,443` | `tcp dport { 80, 443 }` |

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

### Переменные и модульность

В отличие от iptables, nftables поддерживает нативные переменные и включение файлов, что позволяет строить иерархические конфигурации.

**Использование переменных (`define`):**
```bash
define ext_if = "eth0"
define trusted_hosts = { 192.168.1.10, 192.168.1.20 }

# Использование в правилах
nft add rule inet filter input iifname $ext_if ip saddr $trusted_hosts accept
```

**Включение файлов (`include`):**
```bash
# /etc/nftables.conf
include "/etc/nftables/vars.nft"
include "/etc/nftables/sets.nft"

table inet filter {
    include "/etc/nftables/input_chain.nft"
}
```

## Практические сценарии

### 1. Стратегии миграции с iptables

Современный подход предполагает либо использование слоя совместимости, либо полную конвертацию в нативный синтаксис.

#### А. Использование `iptables-nft` (Shim-подход)
В большинстве современных дистрибутивов `iptables` уже является ссылкой на `iptables-nft`. Это позволяет использовать старые скрипты, в то время как ядро выполняет их через nftables.
```bash
# Проверка текущего бэкенда
iptables -V
# → iptables v1.8.7 (nf_tables)
```

#### Б. Полная конвертация (Native-подход)
Использование `iptables-restore-translate` для пакетного переноса всей конфигурации.

**Алгоритм миграции:**

1.  **Экспорт**: `iptables-save > rules.ipt`
2.  **Трансляция**: `iptables-restore-translate -f rules.ipt > rules.nft`
3.  **Оптимизация**: Вручную объедините таблицы `ip` и `ip6` в одну таблицу `inet`.
4.  **Атомарное применение**:
    ```bash
    nft -f rules.nft
    ```

**Важно:** nftables применяет правила из файла **атомарно**. Если в файле есть ошибка, ни одно правило не будет применено, и текущая конфигурация останется нетронутой.

### 2. Справочник выражений для заголовков пакетов

nftables позволяет гибко фильтровать трафик по полям различных протоколов.

**Сетевые и транспортные протоколы:**

-   **Ethernet**: `ether { daddr | saddr | type }`
-   **VLAN**: `vlan { id | dei | pcp | type }`
-   **ARP**: `arp { htype | ptype | hlen | plen | operation | saddr { ip | ether } | daddr { ip | ether } }`
-   **IPv4**: `ip { version | hdrlength | dscp | length | id | frag-off | ttl | protocol | saddr | daddr }`
-   **IPv6**: `ip6 { version | dscp | flowlabel | length | nexthdr | hoplimit | saddr | daddr }`
-   **TCP**: `tcp { sport | dport | sequence | ackseq | flags | window | checksum }`
-   **UDP**: `udp { sport | dport | length | checksum }`

**Протоколы управления (ICMP):**

-   **ICMP (IPv4)**: `icmp { type | code | id | sequence | gateway | mtu }`
-   **ICMPv6 (IPv6)**: `icmpv6 { type | code | id | sequence | mtu }`

**Типовые типы ICMPv6 для Neighbor Discovery (критично для IPv6):**
```bash
# Разрешить Neighbor Discovery (аналог ARP для IPv6)
nft add rule inet filter input icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-advert } accept
```

**Пример RAW-выражения (фильтрация по смещению):**
```bash
# Проверка первых двух байтов транспортного заголовка (обычно sport)
# Синтаксис: @base,offset,length
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

### 4. Использование наборов (Sets) и карт (Verdict Maps)

Наборы и карты позволяют объединять множество правил в одно, значительно повышая производительность.

**Конкатенация (Concatenation):**
Позволяет проверять несколько полей одновременно.
```bash
# Разрешить SSH и HTTP только для конкретных пар IP
nft add rule inet filter input ip saddr . tcp dport { 192.168.1.10 . 22, 192.168.1.20 . 80 } accept
```

**Карты вердиктов (Verdict Maps):**
Направляют пакет в разные цепочки в зависимости от условия.
```bash
# Разделение трафика по интерфейсам
nft add rule inet filter input iifname vmap { "eth0" : jump external_chain, "eth1" : jump internal_chain }
```

## Дополнительная информация

### См. также

-   **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — основы иерархии (таблицы, цепочки).
-   **[nftables — практические сценарии](./practical_scenarios.md)** — готовые примеры настройки NAT и защиты от атак.
-   **[nftables — сегментирование сети](./network_segmentation.md)** — использование наборов для микросегментации.
-   **[Сохранение правил файрвола](../firewall_common.md#сохранение-правил-между-перезагрузками)** — обеспечение персистентности конфигурации.
-   **[Интеграция с Docker](../../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — особенности работы `iptables-nft` в контейнерах.
