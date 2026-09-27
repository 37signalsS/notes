# Диагностика проблем с брандмауэрами (Firewall)

## Определения

**Диагностика firewall** — процесс идентификации того, что трафик блокируется на уровне Netfilter (iptables/nftables) или пользовательского фронтенда (ufw/firewalld), и определения конкретного правила-виновника.

**Stateful firewall** — файрвол, отслеживающий состояние соединений через conntrack. Правила применяются не к отдельным пакетам, а к целым сессиям (ESTABLISHED, RELATED, NEW).

**Verdict (приговор)** — решение, принимаемое Netfilter по отношению к пакету: `ACCEPT` (пропустить), `DROP` (молча отбросить), `REJECT` (отбросить с ICMP-ответом), `LOG` (записать в лог).

## Основные концепции

### Алгоритм диагностики "Firewall или не Firewall"

```
Трафик не проходит
    │
    ├── 1. nc -zv <host> <port> ── Timeout?
    │       │
    │       ├── Timeout ──→ Файрвол DROP или хост недоступен
    │       └── Connection refused ──→ Сервис не слушает (не firewall)
    │
    ├── 2. Проверка iptables/nftables
    │       sudo iptables -L -v -n | grep <port>
    │       sudo nft list ruleset | grep <port>
    │
    ├── 3. Проверка conntrack
    │       conntrack -L -p tcp --dport <port>
    │
    └── 4. Захват через tcpdump
            sudo tcpdump -i eth0 host <ip> and port <port>
            # Если SYN уходит, но нет SYN/ACK → firewall блокирует
```

### Порядок обработки пакетов в Netfilter

```
Входящий пакет
    │
    ▼
raw (PREROUTING)     ← NOTRACK (исключение из conntrack)
    │
    ▼
conntrack            ← поиск/создание записи
    │
    ▼
mangle (PREROUTING)  ← изменение заголовков
    │
    ▼
nat (PREROUTING)     ← DNAT
    │
    ▼
Маршрутизация        ← ip route get
    │
    ├── INPUT         ← фильтрация для локальных процессов
    │   │
    │   ▼
    │   mangle (INPUT)
    │   filter (INPUT)  ← основные правила INPUT
    │   nat (INPUT)
    │
    └── FORWARD       ← фильтрация для транзитного трафика
        │
        ▼
        mangle (FORWARD)
        filter (FORWARD)
        nat (FORWARD)
        │
        ▼
    nat (POSTROUTING) ← SNAT / MASQUERADE
        │
        ▼
    Исходящий пакет
```

**Ключевое правило:** если пакет идёт на локальный процесс (INPUT), он НЕ проходит через FORWARD. Многие ошибки возникают из-за непонимания этого разделения.

### Разница между DROP и REJECT

| Действие | Поведение | Когда использовать |
|:---|:---|:---|
| **DROP** | Молча отбрасывает пакет. Отправитель ждёт таймаут. | Внешний firewall, DDoS-защита |
| **REJECT** | Отправляет ICMP Port Unreachable (TCP RST). | Внутренний firewall, быстрая диагностика |

**Влияние на диагностику:**
- `REJECT` → `nc` сразу получит `Connection refused` → понятно, что firewall блокирует.
- `DROP` → `nc` будет ждать таймаут (по умолчанию ~20 сек) → выглядит как "хост недоступен".

## Практические сценарии

### 1. Быстрая проверка: какой firewall активен

```bash
# Определение используемого backend
sudo iptables --version
# → iptables v1.8.7 (nf_tables)    ← nftables backend
# → iptables v1.8.7 (legacy)       ← legacy iptables

# Проверка nftables
sudo nft list ruleset | head -20

# Проверка ufw
sudo ufw status verbose

# Проверка firewalld
sudo firewall-cmd --state
sudo firewall-cmd --list-all

# Все таблицы iptables
sudo iptables -L -v -n -t filter
sudo iptables -L -v -n -t nat
sudo iptables -L -v -n -t mangle
sudo iptables -L -v -n -t raw
```

### 2. Поиск правила, блокирующего трафик

```bash
# Шаг 1: Определить, на какой цепочке (chain) ищем
# Для входящего трафика к сервису → INPUT
# Для транзитного трафика → FORWARD

# Шаг 2: Поиск правил с計чиками
sudo iptables -L INPUT -v -n --line-numbers
# → chain INPUT has 15 references
# → pkts bytes target   prot opt in     out     source      destination
#     0     0 DROP      tcp  --  *      *       0.0.0.0/0   0.0.0.0/0  tcp dpt:80

# Шаг 3: Если counter = 0, правило НЕ срабатывает
# Если counter > 0, пакеты попадают в это правило

# Шаг 4: Для nftables
sudo nft list ruleset -a
# → table ip filter { chain input { ... # handle 5 } }
```

### 3. Диагностика Docker + ufw/firewalld

**Проблема:** Docker создаёт свои правила в DOCKER-CHAIN, которые выполняются ДО правил ufw. UFW бесполезен для контейнеров.

```bash
# Шаг 1: Проверка цепочки DOCKER-USER
sudo iptables -L DOCKER-USER -v -n
# → Всё, что добавлено через "docker publish -p", проходит ПЕРЕД ufw

# Шаг 2: Решение — добавить правила в DOCKER-USER chain
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -j DROP
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -s 10.0.0.0/8 -j ACCEPT

# Шаг 3: Проверка
sudo iptables -L DOCKER-USER -v -n
```

### 4. Диагностика через tcpdump

```bash
# Захват трафика на целевом интерфейсе
sudo tcpdump -i eth0 -nn host <client_ip> and port <port>

# Если видно:
# [S] → нет ответа → firewall блокирует на INPUT (или сервис не слушает)
# [S.] → [R] → сервис слушает, но сразу сбрасывает (ошибка в конфиге)

# Проверка, отвечает ли сервер на ICMP (иконка жизни)
sudo tcpdump -i eth0 -nn icmp and host <client_ip>

# Захват конкретного пакета и проверка, где он остановился
sudo tcpdump -i eth0 -nn tcp port 443 -c 10
```

### 5. Быстрое правило для разрешения конкретного порта

```bash
# iptables: разрешить TCP 443 из конкретной подсети
sudo iptables -I INPUT -p tcp --dport 443 -s 10.0.0.0/8 -j ACCEPT

# nftables: аналогичное правило
sudo nft add rule ip filter input tcp dport 443 ip saddr 10.0.0.0/8 accept

# ufw: разрешить порт
sudo ufw allow from 10.0.0.0/8 to any port 443 proto tcp

# firewalld: разрешить порт в зоне public
sudo firewall-cmd --zone=public --add-port=443/tcp --permanent
sudo firewall-cmd --reload
```

### 6. Мониторинг DROP в реальном времени

```bash
# iptables: просмотр правил сreatest counters
sudo iptables -L INPUT -v -n | awk '$1 > 0 {print}'

# Непрерывный мониторинг
watch -n 1 'sudo iptables -L INPUT -v -n -t filter | awk "NR>2 && \$1>0 {print}"'

# nftables: мониторинг через monitor
sudo nft monitor | grep -E "drop|reject"

# Быстрый поиск правил с最高的计数器
sudo iptables -L -v -n | sort -k1 -rn | head -10
```

### 7. Проверка, есть ли вообще правила

```bash
# iptables: все цепочки пусты?
sudo iptables -L -v -n | grep -c -v "^Chain\|^target\|^$"
# → 0 = нет правил (ACCEPT all by default)

# nftables
sudo nft list ruleset | wc -l
# → 0 = нет правил

# ufw
sudo ufw status
# → Status: inactive
```

## Дополнительная информация

### Типичные ошибки

| Проблема | Причина | Решение |
|:---|:---|:---|
| Порт открыт, но не доступен извне | Правило в INPUT или отсутствует DNAT | `iptables -L INPUT -v -n`, `iptables -t nat -L -v -n` |
| Docker-порты не блокируются ufw | DOCKER-USER цепочка выполняется до ufw | Добавить правила в DOCKER-USER |
| Правило добавлено, но не работает | Порядок правил (first-match) | Проверить `-I` (insert) vs `-A` (append) |
| `iptables: No chain/target/match by that name` | Модуль не загружен | `modprobe ipt_<модуль>` или `modprobe nft_<модуль>` |
| Соединения сбрасываются после idle | TCP keepalive не настроен | Увеличить `net.ipv4.tcp_keepalive_time` |

### Связанные инструменты

- **[iptables basics](../../Networking/Settings/tools/iptables_basics.md)** — основы iptables (SSoT).
- **[nftables architecture](../../Networking/Settings/tools/nftables/architecture_and_concepts.md)** — архитектура nftables (SSoT).
- **[nftables practical scenarios](../../Networking/Settings/tools/nftables/practical_scenarios.md)** — практические сценарии nftables.
- **[ufw](../../Networking/Settings/tools/ufw.md)** — полная справка по ufw.
- **[firewalld](../../Networking/Settings/tools/firewalld.md)** — полная справка по firewalld.
- **[conntrack](../../Networking/Concepts/conntrack_production_tuning.md)** — диагностика таблицы соединений.
- **[Docker + iptables](../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — интеграция Docker с firewall.
