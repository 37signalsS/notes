# nftables — миграция и справочник синтаксиса

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
| **Вставить в начало** | `iptables -I INPUT 1 ...` | `nft insert rule inet filter input ...` |
| **Удалить правило** | `iptables -D INPUT 5` | `nft delete rule inet filter input handle 5` |
| **Просмотр правил** | `iptables -L -n -v` | `nft list ruleset` |
| **Очистка (Flush)** | `iptables -F` | `nft flush ruleset` |
| **Использование сетов** | `ipset add myset 1.1.1.1` | `nft add element inet filter myset { 1.1.1.1 }` |
| **Переменные** | Нет (только через Bash) | `define ext_if = "eth0"` |
| **NAT (Masquerade)** | `-t nat -A POSTROUTING -o eth0 -j MASQUERADE` | `add rule nat postrouting oif eth0 masquerade` |
| **Порты (Множеств.)** | `-m multiport --dports 80,443` | `tcp dport { 80, 443 }` |

### Идентификаторы правил (Handles)

В отличие от `iptables`, где правила идентифицируются порядковым номером (индексом), в `nftables` каждое правило имеет уникальный и неизменный **handle** (хэндл) в рамках таблицы.

- **Зачем нужны**: Удаление правила по индексу в `iptables` опасно в многопоточной среде (индексы сдвигаются). Хэндлы в `nftables` гарантируют, что вы удаляете именно то правило, которое планировали.
- **Просмотр**: `nft list ruleset -a` (флаг `-a` или `--handle` показывает идентификаторы).
- **Удаление**: `nft delete rule <family> <table> <chain> handle <id>`.

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

### Эквиваленты расширений (Match Extensions)

Многие функции, которые в `iptables` требовали внешних модулей (`-m`), в `nftables` являются встроенными выражениями.

| Модуль iptables | Эквивалент nftables | Пример |
| :--- | :--- | :--- |
| `limit` | `limit` | `limit rate 10/second` |
| `quota` | `quota` | `quota over 100 mbytes drop` |
| `state / conntrack` | `ct state` | `ct state { established, related } accept` |
| `recent` | `meter` / `set` | `update @blackhole { ip saddr timeout 1m }` |
| `comment` | `comment` | `... comment "Allow SSH"` |
| `addrtype` | `fib` | `fib saddr type local accept` |

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

### Архитектурные различия бэкендов iptables

В современных дистрибутивах `iptables` может быть либо legacy-бинарником, работающим напрямую с Netfilter, либо shim-обёрткой над nftables. Это критически важно при миграции, так как правила, добавленные через `iptables-nft`, coexistent с нативными nftables-таблицами.

| Бэкенд | Путь | Характеристики |
| :--- | :--- | :--- |
| `iptables-legacy` | `/sbin/iptables-legacy` | Работает напрямую с Netfilter; несовместим с nftables. |
| `iptables-nft` | `/sbin/iptables-nft` | Транслирует в байт-код nftables; правила видны в `nft list ruleset`. |
| `nft` (native) | `/sbin/nft` | Нативный инструмент; атомарные транзакции через Netlink. |

**Определение активного бэкенда:**
```bash
# Проверка alternatives
update-alternatives --list iptables
# → /usr/sbin/iptables-nft

# Или через iptables
iptables -V
# → iptables v1.8.7 (nf_tables)
```

**Важно:** если система использует `iptables-nft`, добавление правил через `iptables` создаёт таблицы с префиксом `ip filter`, которые отображаются в `nft list ruleset` с комментарием `# managed by iptables-nft`. При переходе на нативный nftables эти таблицы нужно удалять или игнорировать.

### Инструменты трансляции правил

| Утилита | Назначение | Пример |
| :--- | :--- | :--- |
| `iptables-translate` | Трансляция одной команды iptables в эквивалент nft | `iptables-translate -A INPUT -p tcp --dport 22 -j ACCEPT` |
| `iptables-restore-translate` | Пакетная конвертация файла правил iptables в nft-синтаксис | `iptables-restore-translate -f rules.ipt > rules.nft` |
| `ip6tables-translate` | То же для IPv6 | `ip6tables-translate -A INPUT -p icmpv6 -j ACCEPT` |

**Ограничения трансляции:**
- Модуль `-m recent` не имеет прямого однострочного эквивалента; требуется перестройка через `set` с `timeout`.
- Модуль `-m string` (сопоставление с payload) требует ручного переписывания на `payload` выражения.
- ALG-помощники (FTP, SIP) не мигрируют автоматически; требуется `ct helper` или отключение через `notrack`.
- Политики chains в iptables задаются через отдельные команды; в nftables указываются в определении chain.

## Предварительные требования

### Аппаратные требования

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| ** NIC** | 1 порт | 2+ порта для маршрутизации/NAT |
| ** CPU** | 2 ядра | 4+ ядер при нагрузке >1Gbps |
| ** RAM** | 512 MB | 2 GB+ для больших таблиц conntrack |

### Программные требования

| Компонент | Версия / Требование |
| :--- | :--- |
| **Ядро Linux** | 5.3+ (нативный `bridge` conntrack), 5.15+ рекомендуется |
| **nftables** | 1.0.0+ |
| **iproute2** | 5.x+ |
| **conntrack-tools** | для диагностики (`conntrack`, `conntrackd`) |
| **Права** | root (sudo) |
| **Служба** | `nftables` (systemd) для персистентности |

### Проверка окружения

```bash
# Версия ядра
uname -r
# → 5.15.0-78-generic

# Наличие nftables
which nft && nft --version
# → nft v1.0.9

# Проверка загруженных модулей ядра
lsmod | grep -E 'nf_conntrack|nf_defrag_ipv4|nf_nat'
# → nf_conntrack          163840  1 bridge
# → nf_nat                245760  1 nf_conntrack

# Размер таблицы conntrack
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 262144

# Определение активного бэкенда iptables
iptables -V
# → iptables v1.8.7 (nf_tables)

# Проверка, есть ли таблицы, управляемые iptables-nft
nft list ruleset | grep "managed by iptables-nft"
# → table ip filter { # managed by iptables-nft
```

## Практические сценарии

### 1. Предмиграционный аудит и резервное копирование

Перед любым изменением файрвола необходимо получить полный инвентарь текущих правил и убедиться, что откат возможен.

**Аудит текущего состояния:**
```bash
# Экспорт правил iptables (IPv4 + IPv6)
sudo iptables-save > /tmp/iptables-backup-$(date +%F).rules
sudo ip6tables-save > /tmp/ip6tables-backup-$(date +%F).rules

# Экспорт текущих nftables (если уже используются)
sudo nft list ruleset > /tmp/nftables-backup-$(date +%F).nft

# Анализ правил iptables
wc -l /tmp/iptables-backup-*.rules
# → 142 /tmp/iptables-backup-2026-09-12.rules

# Проверка активных соединений (чтобы не обрывать легитимный трафик)
sudo conntrack -L -o extended | head -20
# → tcp      6 431999 ESTABLISHED src=10.0.0.5 dst=203.0.113.10 sport=52182 dport=443 ...
```

**Создание контрольной точки systemd-networkd / firewalld:**
```bash
# Для firewalld
sudo firewall-cmd --runtime-to-permanent
sudo cp /etc/firewalld/zones/*.xml /tmp/firewalld-backup/

# Для ufw
sudo cp /etc/ufw/*.rules /tmp/ufw-backup/
```

### 2. Стратегии миграции с iptables

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

### 3. Полная конвертация через iptables-restore-translate

**Шаг 1: Экспорт и конвертация**
```bash
# Экспорт правил
sudo iptables-save > /tmp/iptables-backup.rules
sudo ip6tables-save > /tmp/ip6tables-backup.rules

# Конвертация в nftables
sudo iptables-restore-translate -f /tmp/iptables-backup.rules > /tmp/nftables-translated.nft
sudo ip6tables-restore-translate -f /tmp/ip6tables-backup.rules >> /tmp/nftables-translated.nft
```

**Шаг 2: Ручная оптимизация**

Автоматическая конвертация создаёт отдельные таблицы `ip filter` и `ip6 filter`. Для dual-stack environments их следует объединить в `inet filter`:

```bash
# Пример оптимизированной конфигурации
sudo tee /etc/nftables.conf << 'EOF'
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        iif lo accept
        ct state established,related accept
        ct state invalid drop
        tcp dport { 22, 80, 443 } accept
        icmp type echo-request limit rate 5/second accept
        icmpv6 type { nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert, echo-request, echo-reply } accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
EOF
```

**Шаг 3: Проверка и применение**
```bash
# Синтаксическая проверка
sudo nft --check -f /etc/nftables.conf
# → (пустой вывод = ошибок нет)

# Применение
sudo nft -f /etc/nftables.conf

# Проверка
sudo nft list ruleset
```

### 4. Замена специфичных модулей iptables

Некоторые модули iptables не имеют прямого однострочного эквивалента и требуют перепроектирования логики.

| Модуль iptables | Ограничение | Рекомендуемый подход nftables |
| :--- | :--- | :--- |
| `-m recent` | Нет прямого аналога | `set` с флагами `dynamic, timeout` + `update`/`add` в правиле |
| `-m string` | Сложные выражения | `payload` выражения с явным указанием смещения |
| `-m conntrack --ctstate` | Устарел в пользу `-m state` | `ct state { established, related }` |
| `-m set` (ipset) | Отдельный демон | Именованные `set` в nftables с `timeout` |
| `-m multiport` | Устарел | `{ 80, 443 }` анонимный или именованный сет |
| `-m addrtype` | Ограниченный | `fib` выражения для проверки маршрута |

**Пример замены `-m recent`:**
```bash
# iptables (legacy)
iptables -A INPUT -p tcp --dport 22 -m recent --name ssh_brut --set
iptables -A INPUT -p tcp --dport 22 -m recent --name ssh_brut --update --seconds 60 --hitcount 5 -j DROP

# nftables (set с timeout)
table inet filter {
    set ssh_brut {
        type ipv4_addr
        flags dynamic, timeout
        timeout 60s
    }

    chain input {
        type filter hook input priority 0; policy drop;
        ct state established,related accept
        iif lo accept

        # Блокировка при >5 соединений за 60s
        tcp dport 22 ct state new \
            limit rate over 5/60s \
            add @ssh_brut { ip saddr } \
            drop

        tcp dport 22 accept
    }
}
```

**Пример замены `-m string`:**
```bash
# iptables (legacy) — поиск строки в payload
iptables -A OUTPUT -p tcp --dport 80 -m string --string "malware.exe" --algo bm -j DROP

# nftables — payload выражение
nft add rule inet filter output tcp dport 80 payload "61 6c 6c 6f 77 6f 72 6c 64" @th,0,8 0x0000000000000000 drop
```

### 5. Миграция dual-stack (IPv4 + IPv6)

Семейство `inet` позволяет создавать единые правила для обеих версий протокола, что значительно упрощает конфигурацию по сравнению с дублированием в `iptables` и `ip6tables`.

**Конвертация IPv6-правил:**
```bash
# Экспорт IPv6 правил
sudo ip6tables-save > /tmp/ip6tables-backup.rules

# Конвертация
sudo ip6tables-restore-translate -f /tmp/ip6tables-backup.rules > /tmp/nftables-ipv6.nft
```

**Объединение в `inet`-семейство:**
```bash
# Вместо отдельных таблиц ip filter и ip6 filter
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        ct state established,related accept
        iif lo accept
        tcp dport { 22, 80, 443 } accept
        icmp type echo-request limit rate 5/second accept
        icmpv6 type { nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert, echo-request, echo-reply } accept
    }
}
```

**Важно:** если в старых правилах были различия между IPv4 и IPv6 (разные порты, разные политики), их нужно сохранить явно:
```bash
# Правило только для IPv6
nft add rule inet filter input ip6 daddr fe80::/10 icmpv6 type nd-router-advert accept

# Правило только для IPv4
nft add rule inet filter input ip saddr 10.0.0.0/8 tcp dport 22 accept
```

### 6. Сосуществование с Docker

Docker автоматически управляет правилами iptables/nftables для проброса портов и изоляции сетей. При миграции важно понимать, как Docker взаимодействует с nftables.

**Вариант А: Docker через iptables-nft (прозрачный)**
```bash
# Docker 20.10—28.x: создаёт таблицы в nftables через iptables-nft
nft list ruleset | grep DOCKER
# → table ip filter { # managed by iptables-nft-chain-DOCKER
```

В этом режиме пользовательские nftables-таблицы coexist с Docker-таблицами. Для фильтрации доступа к контейнерам используйте цепочку `DOCKER-USER` (если доступна) или создайте правила в `forward`-цепочке с приоритетом после Docker.

**Вариант Б: Docker 29.0+ с нативным nftables**
```json
// /etc/docker/daemon.json
{
  "iptables": false
}
```

При отключении iptables Docker создаёт собственную nftables-таблицу `ip filter` с цепочкой `DOCKER` и `DOCKER-user`. Пользовательские правила следует размещать в отдельных таблицах с учётом приоритетов.

**Фильтрация доступа к контейнерам:**
```bash
# Разрешить доступ к порту 8080 только из доверенной подсети
table inet filter {
    chain forward {
        type filter hook forward priority 0; policy drop;
        ct state established,related accept

        # Docker-трафик разрешён по умолчанию
        iifname "docker0" accept

        # Ограничение доступа к конкретному контейнеру
        ip daddr 172.17.0.2 tcp dport 8080 ip saddr != 192.168.1.0/24 drop
    }
}
```

### 7. Откат и восстановление iptables

В случае проблем с миграцией необходимо быстро восстановить рабочую конфигурацию.

**Процедура отката:**
```bash
# 1. Остановка nftables-сервиса
sudo systemctl stop nftables

# 2. Очистка nftables
sudo nft flush ruleset

# 3. Восстановление iptables
sudo iptables-restore < /tmp/iptables-backup.rules
sudo ip6tables-restore < /tmp/ip6tables-backup.rules

# 4. Перезапуск firewalld/ufw (если использовался)
sudo systemctl start firewalld
# или
sudo systemctl start ufw

# 5. Проверка
sudo iptables -L -n -v
sudo ping -c 3 8.8.8.8
```

**Автоматический откат через systemd-run:**
```bash
# Применение с автоматическим откатом через 5 минут
sudo systemctl restart nftables && \
  echo "sudo nft flush ruleset && sudo iptables-restore < /tmp/iptables-backup.rules" | \
  sudo at now + 5 minutes
```

### 8. Справочник выражений для заголовков пакетов

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

### 9. Использование метаданных (Meta expressions)

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

### 10. Работа с состояниями (Connection Tracking)

В `nftables` вместо `-m state` или `-m conntrack` используется объект `ct` (conntrack). Это базовый механизм для Stateful Firewall.

**Типовые состояния:**
- `new`: первый пакет соединения.
- `established`: пакеты установленного соединения.
- `related`: пакеты, связанные с существующим соединением (например, ICMP error или FTP data).
- `invalid`: пакеты, не принадлежащие ни одному известному соединению.

**Пример базовой цепочки с conntrack:**
```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить уже установленные соединения (самое частое правило — в начало)
        ct state { established, related } accept

        # Отбрасывать некорректные пакеты
        ct state invalid drop

        # Разрешить loopback
        iifname "lo" accept

        # Разрешить SSH для новых соединений
        tcp dport 22 ct state new accept
    }
}
```

### 11. Использование наборов (Sets) и карт (Verdict Maps)

Наборы и карты позволяют объединять множество правил в одно, значительно повышая производительность.

**Типы наборов:**
1.  **Анонимные**: определяются прямо в правиле `{ 80, 443 }`. Не могут быть изменены без удаления правила.
2.  **Именованные**: определяются отдельно, могут быть динамическими.

**Расширенные возможности наборов (Flags):**
- `timeout`: элементы набора удаляются по истечении времени (замена `ipset` с таймаутами).
- `interval`: поддержка подсетей и диапазонов портов.
- `size`: ограничение максимального количества элементов.

**Пример именованного динамического набора (Blacklist):**
```bash
table inet filter {
    set denylist {
        type ipv4_addr
        flags dynamic, timeout
        timeout 1h
    }

    chain input {
        # Блокировать всех из списка
        ip saddr @denylist drop

        # Добавить в список при попытке доступа к закрытому порту (Port Scanning)
        tcp dport 1234 update @denylist { ip saddr }
    }
}
```

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

### 12. Логирование и мониторинг

В `nftables` логирование гибко настраивается и может быть направлено в `syslog`, `nflog` (для пользовательских утилит типа `tcpdump`) или в журналы ядра.

**Пример логирования с префиксом и ограничением скорости:**
```bash
# Логировать новые SSH-соединения (не более 2 в минуту)
nft add rule inet filter input tcp dport 22 ct state new limit rate 2/minute log prefix "SSH-ACCESS: " accept
```

**Мониторинг событий (Runtime):**
Утилита `nft` позволяет подписываться на изменения правил или появление новых соединений в реальном времени.
```bash
# Просмотр изменений правил в реальном времени
nft monitor

# Просмотр только добавления элементов в наборы
nft monitor sets
```

## Валидация результатов миграции

После применения nftables-конфигурации необходимо проверить, что все сервисы доступны, а политики безопасности соответствуют ожиданиям.

**Синтаксическая проверка:**
```bash
# Проверка конфигурационного файла
sudo nft --check -f /etc/nftables.conf
# → (пустой вывод = ошибок нет)
```

**Проверка загруженных правил:**
```bash
# Просмотр всех таблиц и цепочек
sudo nft list ruleset

# Просмотр конкретной таблицы
sudo nft list table inet filter

# Просмотр с handle (для удаления)
sudo nft -a list chain inet filter forward
```

**Проверка работоспособности сервисов:**
```bash
# Проверка SSH
sudo ss -tlnp | grep :22
# → LISTEN 0 128 0.0.0.0:22 0.0.0.0:*

# Проверка DNS
dig @127.0.0.1 example.com
# → connection timed out; no servers could be reached

# Проверка HTTP
curl -I http://localhost
# → HTTP/1.1 200 OK
```

**Проверка маршрутизации:**
```bash
# Таблица маршрутизации
ip route show

# Проверка forwarding
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1

# Проверка conntrack
sudo conntrack -L -o extended | grep ESTABLISHED
```

**Сравнение с исходным iptables:**
```bash
# Количество правил до и после
wc -l /tmp/iptables-backup.rules
# → 142 /tmp/iptables-backup.rules

nft list ruleset | wc -l
# → 85

# Проверка, что критичные порты открыты
sudo nmap -p 22,80,443 localhost
# → 22/tcp open ssh
# → 80/tcp open http
# → 443/tcp open https
```

## Диагностика и устранение неполадок

| Проблема | Признак | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Правила не применяются** | `nft list ruleset` пуст | Проверить синтаксис: `nft --check -f` | Исправить ошибку в файле |
| **Порт недоступен** | nmap показывает filtered | `nft list chain` — правило есть? | Проверить порядок правил, policy drop |
| **Потеря SSH при применении** | Соединение обрывается | Локальная консоль | Использовать атомарную загрузку |
| **Conntrack переполнен** | `dmesg` показывает `table full` | `conntrack -S` — `drop > 0` | Увеличить `nf_conntrack_max` |
| **IPv6 не работает** | Узлы не получают SLAAC | `nft list chain` — есть ICMPv6? | Добавить `icmpv6 type` accept |
| **DHCP не работает** | Узлы не получают IP | `tcpdump -i br0 port 67` | Проверить `udp dport 67-68 accept` |
| **Высокая нагрузка CPU** | `top` показывает high softirq | `cat /proc/softirqs` | Уменьшить правила, добавить limit rate |
| **Дублирующиеся правила** | Один и тот же трафик обрабатывается несколько раз | `nft -a list ruleset` — повторяющиеся handles? | Удалить дубликаты |
| **Транслированные правила не работают** | Семантика отличается от iptables | Сравнить `iptables-save` и `nft list ruleset` | Ручная адаптация логики |
| **Docker теряет связность** | Контейнеры не общаются | `nft list ruleset | grep DOCKER` | Проверить приоритеты цепочек forward |
| **Ошибка `managed by iptables-nft`** | Дублирование таблиц | `nft list ruleset | grep managed` | Очистить iptables-таблицы, перезагрузить nftables |

**Частые ошибки при миграции:**

1. **Неудаление legacy-таблиц:** после перехода на nftables старые таблицы `ip filter`, созданные через `iptables-nft`, остаются в ядре. Удаляйте их явно: `nft delete table ip filter`.
2. **Потеря `ct state established,related`:** без этого правила SSH может обрываться при любом изменении conntrack-таблицы.
3. **Некорректный приоритет chain:** при ручном создании базовых цепочек используйте стандартные приоритеты (`filter` = 0, `nat` = -100/100, `raw` = -300).
4. **Дублирование NAT:** если `iptables-nft` и нативные nftables-правила NAT активны одновременно, может возникнуть двойная трансляция.

## Краевые случаи и ограничения

1.  **Атомарность:** nftables применяет изменения атомарно. Ошибка в синтаксисе halfway не частично активирует правила.
2.  **IPv6:** Если семейство `inet` используется, правило `tcp dport 80 accept` создаст записи и для IPv6. Для IPv6-only используйте `ip6` семейство.
3.  **Логирование `full`:** Записывает полные дампы пакетов, что может создать нагрузку на диск. Используйте только для диагностики.
4.  **Rate limit:** В nftables `limit rate` работает для любых протоколов. Для тонкой настройки UDP используйте Fail2ban.
5.  **Per-interface правила:** `iif "eth1"` требует точного имени интерфейса (проверьте через `ip link`).
6.  **Conntrack:** nftables использует `nf_conntrack`. При высокой нагрузке увеличьте `net.netfilter.nf_conntrack_max`.
7.  **notrack и helpers:** Использование `notrack` отключает отслеживание соединения, что может сломать FTP ALG и другие helpers. Используйте осторожно.
8.  **Flowtables:** При использовании flowtables пакеты попадают в цепочки `ingress`/`egress` семейства `netdev` и обходят классические `filter`-цепочки. Убедитесь, что политики согласованы.
9.  **Hairpin mode:** по умолчанию мост не рефлексирует кадр обратно в порт-источник. Если внутренние узлы должны общаться друг с другом через мост (например, при избыточной топологии), включите hairpin: `bridge link set dev <iface> hairpin on`.
10. **MTU:** MTU моста автоматически падает до минимального среди портов. Если к мосту подключен интерфейс с MTU 1500, весь мост будет ограничен 1500 байт, даже если остальные порты поддерживают 9000.
11. **Асимметричная маршрутизация:** если ответный трафик возвращается через другой интерфейс, stateful firewall дропает пакеты. Решение: `rp_filter=2` или единый шлюз для входящего/исходящего трафика.
12. **Conntrack helpers (ALG):** для протоколов с вспомогательными данными (FTP, SIP, TFTP) модули `nf_conntrack_*` автоматически открывают дополнительные порты. При строгой политике может потребоваться отключение helpers.
13. **Устаревшие модули:** модули `-m conntrack` в старых скриптах могут конфликтовать с `-m state` после миграции. Проверяйте, что используется единый механизм `ct state`.
14. **Совместное использование iptables и nftables:** при наличии одновременно `iptables-nft` и нативных nftables правил порядок обработки может отличаться от ожидаемого. Избегайте смешивания двух подходов на одном хосте.
15. **Модуль `nf_tables` не загружен:**在某些 минимальных образах ядра модуль `nf_tables` может быть откомпилирован статически или отсутствовать. Проверяйте: `grep -i nf_tables /boot/config-$(uname -r)`.

## Best Practices

1.  **Минимизация поверхности атаки:** используйте `policy drop` по умолчанию, разрешайте только необходимые типы трафика.
2.  **Состояние Established в первой позиции:** размещайте `ct state established,related accept` сразу после проверки `invalid`, чтобы минимизировать нагрузку на CPU.
3.  **Ограничение логирования:** всегда используйте `limit rate` с выражением `log`, чтобы избежать переполнения журнала при DDoS.
4.  **Проверка синтаксиса перед загрузкой:** `nft --check -f /etc/nftables.conf`.
5.  **Резервное копирование:** сохраняйте предыдущий ruleset перед каждым изменением.
6.  **Атомарность:** используйте `nft -f` вместо пошагового добавления правил через `nft add`.
7.  **Мониторинг:** настроите алерты на рост dropped-пакетов в цепочках.
8.  **Документация:** комментируйте каждое правило в конфигурационном файле, особенно исключения.
9.  **Тестирование в lab:** перед внедрением в production протестируйте конфигурацию в изолированной среде с `tcpdump`.
10. **Персистентность:** используйте `systemd`-сервис `nftables` для автоматической загрузки правил при загрузке системы.
11. **Использование сетов для производительности:** для списков из 100+ элементов используйте именованные наборы (sets) вместо последовательных проверок.
12. **Верификация после применения:** всегда проверяйте `nft list ruleset` и тестовые соединения после применения правил.
13. **Отделение миграции от production:** проводите миграцию в maintenance window с заранее подготовленным планом отката.
14. **Удаление legacy-таблиц:** после перехода на нативный nftables удаляйте таблицы, созданные `iptables-nft`, чтобы избежать конфликтов: `nft delete table ip filter`.
15. **Версионирование конфигурации:** храните `nftables.conf` в Git или иной системе контроля версий для отслеживания изменений.

## Очистка окружения

```bash
# 1. Удаление всех правил nftables
sudo nft flush ruleset

# 2. Удаление таблиц
sudo nft delete table inet filter
sudo nft delete table ip nat
sudo nft delete table netdev filter

# 3. Удаление legacy-таблиц iptables-nft (если существуют)
sudo iptables-nft -F
sudo iptables-nft -X
sudo ip6tables-nft -F
sudo ip6tables-nft -X

# 4. Отключение службы
sudo systemctl disable --now nftables

# 5. Удаление файла конфигурации (опционально)
sudo rm /etc/nftables.conf
```

## Дополнительная информация

### Управление и диагностика

```bash
# Проверка текущих счетчиков правил
nft list ruleset

# Мониторинг новых соединений в реальном времени
sudo nft monitor

# Очистка конкретной таблицы
nft flush table inet filter
```

### Сохранение персистентности

Стандартный метод для большинства дистрибутивов (Systemd-based):
1.  Выгрузить текущие правила: `nft list ruleset > /etc/nftables.conf`
2.  Активировать службу: `systemctl enable --now nftables`

### См. также

-   **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — основы иерархии (таблицы, цепочки).
-   **[nftables — практические сценарии](./practical_scenarios.md)** — готовые примеры настройки NAT и защиты от атак.
-   **[nftables — сегментирование сети](./network_segmentation.md)** — использование наборов для микросегментации.
-   **[nftables — моделирование угроз](./threat_modeling.md)** — стратегии проектирования правил безопасности.
-   **[Тестирование правил nftables](./firewall_testing.md)** — верификация настроек (nmap, ss, nc).
-   **[Общие вопросы межсетевых экранов](../firewall_common.md#сохранение-правил-между-перезагрузками)** — персистентность конфигурации.
-   **[Интеграция с Docker](../../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — особенности работы `iptables-nft` в контейнерах.
-   **[Межсетевые экраны: концепции](../../../../../Networking/Concepts/firewall_concepts.md)** — теоретическая база Netfilter и модели OSI.
