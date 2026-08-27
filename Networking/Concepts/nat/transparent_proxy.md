# Прозрачный прокси (Transparent Proxy) через NAT

## Определения

**Прозрачный прокси (Transparent Proxy)** — прокси-сервер, настройка которого не требуется на клиентах. Трафик перехватывается на сетевом уровне шлюза и направляется прокси-серверу без ведома клиента. Клиент обращается к целевому серверу напрямую (по его IP), но пакеты проходят через прокси.

**Основные механизмы перехвата:**

| Механизм | Уровень | Сохраняет оригинальный IP | Сложность настройки |
| :--- | :--- | :--- | :--- |
| **REDIRECT** (iptables/nftables) | NAT (L3/L4) | Нет (клиент виден как `127.0.0.1`) | Низкая |
| **TPROXY** (iptables/nftables) | Mangle (L3) | Да (оригинальный IP сохраняется) | Средняя (нужен policy routing) |

**Где используется:**
- Корпоративная фильтрация трафика (блокировка сайтов, категоризация)
- Кэширование (Squid, Varnish)
- Мониторинг и аудит (mitmproxy, tcpdump)
- SSL/TLS inspection (Decryption proxy)
- Контент-фильтрация на образовательных/государственных сетях

## Теоретический блок

### Как работает REDIRECT

```
Клиент (192.168.1.5)
    │
    │  Пакет: src=192.168.1.5, dst=93.184.216.34:80
    ▼
Шлюз (PREROUTING, nat)
    │  REDIRECT: dst заменяется на 127.0.0.1:3128
    │  Пакет: src=192.168.1.5, dst=127.0.0.1:3128
    ▼
Прокси (Squid,nginx) слушает на 127.0.0.1:3128
    │  Получает запрос, видит оригинальный src=192.168.1.5
    │  (если включено add_x_forwarded_for)
    │  Устанавливает новое соединение с 93.184.216.34:80
    ▼
Целевой сервер
    │  Видит запрос от IP шлюза (SNAT)
    ▼
Ответ: 93.184.216.34 → Шлюз → Прокси → Клиент
```

**Проблема REDIRECT:** Прокси-сервер видит все запросы как обращённые к `127.0.0.1`. Оригинальный destination IP клиента **теряется**. Для HTTP это решается заголовком `X-Forwarded-For`, но для protocols без application-layer заголовков (LDAP, RTSP) — это проблема.

### Как работает TPROXY

```
Клиент (192.168.1.5)
    │
    │  Пакет: src=192.168.1.5, dst=93.184.216.34:80
    ▼
Шлюз (PREROUTING, mangle)
    │  TPROXY: пакет помечается маркером 0x1
    │  Policy routing: маркер 0x1 → route local (lo, table 100)
    │  Пакет доставляется прокси ЛОКАЛЬНО, но С СОХРАНЕНИЕМ оригинального dst
    ▼
Прокси (Squid/nginx) слушает на 0.0.0.0:3128
    │  Видит оригинальный src=192.168.1.5 И dst=93.184.216.34:80
    │  Устанавливает новое соединение с 93.184.216.34:80
    ▼
Целевой сервер
    │  Видит запрос от IP шлюза (SNAT)
    ▼
Ответ: 93.184.216.34 → Шлюз → Прокси → Клиент
```

**Преимущество TPROXY:** Прокси-сервер видит **оригинальный destination IP** клиента. Это критично для:
- Кэширования (URL-зависимая маршрутизация)
- DNS-based маршрутизации (один прокси для разных доменов)
- SSL/TLS inspection (нужен SNI из ClientHello)

### Сравнение REDIRECT и TPROXY

| Критерий | REDIRECT | TPROXY |
| :--- | :--- | :--- |
| **Оригинальный dst IP** | Теряется ( substitute `127.0.0.1`) | Сохраняется |
| **Оригинальный src IP** | Сохраняется (в conntrack) | Сохраняется |
| **Настройка клиента** | Не требуется | Не требуется |
| **Поддержка UDP** | Ограничена | Да |
| **Policy routing** | Не требуется | Требуется (`ip rule`, `ip route`) |
| **Производительность** | Выше (одно правило nat) | Средняя (mangle + policy routing) |
| **Прозрачность для приложений** | Полная | Полная |

## Практический блок

### Настройка прозрачного прокси через REDIRECT

#### Шаг 1: Установка и настройка прокси (Squid)

```bash
# Установка Squid
sudo apt install squid

# Базовая конфигурация /etc/squid/squid.conf
http_port 3128
acl localnet src 192.168.1.0/24
http_access allow localnet
http_access deny all
```

#### Шаг 2: Перенаправление HTTP-трафика на прокси

```bash
# Iptables: перенаправить HTTP (80) и HTTPS (443) на Squid (3128)
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 80 \
  -j REDIRECT --to-ports 3128

iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 443 \
  -j REDIRECT --to-ports 3128

# Исключить сам прокси от перенаправления (иначе — петля)
iptables -t nat -A PREROUTING -p tcp --dport 3128 -j ACCEPT

# Включить IP-forwarding
sysctl -w net.ipv4.ip_forward=1
```

**Nftables-эквивалент:**
```bash
nft add table ip nat
nft add chain ip nat prerouting { type nat hook prerouting priority -100 \; }

nft add rule ip nat prerouting iifname "eth0" tcp dport { 80, 443 } \
  redir to :3128
```

#### Шаг 3: Проверка

```bash
# С клиента (192.168.1.5):
curl -v http://example.com
# → Должен получить ответ (через прокси)

# На шлюзе: проверить, что порт 3128 слушается
ss -tlnp | grep 3128
# → LISTEN 0 128 0.0.0.0:3128 0.0.0.0:* users:(("squid",pid=1234,fd=6))

# Логи Squid:
tail -f /var/log/squid/access.log
# → Должны появиться записи о запросах клиентов
```

### Настройка прозрачного прокси через TPROXY

#### Шаг 1: Настройка прокси (Squid с TPROXY)

```bash
# Конфигурация /etc/squid/squid.conf
http_port 3128 tproxy
```

#### Шаг 2: Настройка iptables + policy routing

```bash
# Маркировка пакетов в таблице mangle
iptables -t mangle -A PREROUTING -p tcp --dport 80 \
  -j TPROXY --tproxy-mark 0x1/0x1 --on-port 3128

iptables -t mangle -A PREROUTING -p tcp --dport 443 \
  -j TPROXY --tproxy-mark 0x1/0x1 --on-port 3128

# Создание таблицы маршрутизации (100)
echo "100 tproxy" >> /etc/iproute2/rt_tables

# Policy routing: пакеты с маркером 0x1 доставляются локально
ip rule add fwmark 0x1 lookup tproxy
ip route add local 0.0.0.0/0 dev lo table tproxy

# Включить IP-forwarding
sysctl -w net.ipv4.ip_forward=1
```

**Nftables-эквивалент:**
```bash
nft add table ip mangle
nft add chain ip mangle prerouting { type filter hook prerouting priority -150 \; }

nft add rule ip mangle prerouting meta l4proto tcp th dport { 80, 443 } \
  tproxy to :3128 mark set 0x1

# Policy routing
ip rule add fwmark 0x1 lookup 100
ip route add local 0.0.0.0/0 dev lo table 100
```

#### Шаг 3: Проверка

```bash
# На шлюзе: проверить, что TPROXY работает
conntrack -L -p tcp --dport 80
# → Должны показать оригинальный dst IP (не 127.0.0.1)

# С клиента:
curl -v http://example.com
# → Ответ от example.com (через прокси с оригинальным dst)
```

### Прозрачный прокси с сохранением src IP (для логирования)

```bash
# REDIRECT + добавление X-Forwarded-For (в Squid):
# В squid.log видно оригинальный IP клиента

# TPROXY + add_x_forwarded_for (в Squid):
# Аналогично, но dst IP также сохраняется

# Проверка: что видит прокси
# В access.log Squid:
# 192.168.1.5 - - [25/Aug/2026:10:00:00 +0300] "GET http://example.com/ HTTP/1.1" 200 1234
```

## Дополнительная информация

- **[Теория NAT](./overview.md)** — DNAT, REDIRECT, conntrack.
- **[Практические сценарии NAT](./practical_scenarios.md)** — DNAT, Hairpin NAT, диагностика.
- **[Прокси-сервер](../../../Networking/Concepts/proxy.md)** — общие принципы работы прокси.
- **[Nftables: Threat Modeling](../../../Linux/Networking/Settings/tools/nftables/threat_modeling.md)** — TPROXY в контексте защиты.
