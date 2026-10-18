# Масштабирование кластера Nginx через BGP Anycast и ECMP (Bare-Metal High Availability)

**Актуально для:** Nginx 1.26+ (OSS/Plus), Angie 1.6+, Bird 2.15+ / FRR 9.1+, Linux Kernel 5.15+ / 6.x+

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) по горизонтальному масштабированию и отказоустойчивости кластеров Nginx на основе протокола BGP Anycast и технологии ECMP в локальных дата-центрах (Bare-Metal / On-Prem):
- [additional_info_and_comparisons.md](./additional_info_and_comparisons.md) — рассматривает классический отказоустойчивый кластер Nginx на базе Keepalived (VRRP), работающий по схеме Active-Passive с единым плавающим VIP.
- [Networking/Protocols/bgp.md](../../../../Networking/Protocols/bgp.md) — описывает теоретические основы протокола BGP (типы сообщений, атрибуты, выбор пути), не касаясь интеграции с веб-серверами.
- [Networking/ServicesAndTools/keepalived_overview.md](../../../../Networking/ServicesAndTools/keepalived_overview.md) — описывает работу демона Keepalived и протокола VRRP на L2/L3.

---

## 1. Определения

- **BGP Anycast** — сетевая архитектура, при которой несколько физических или виртуальных серверов Nginx анонсируют один и тот же IP-адрес (Anycast VIP) по протоколу BGP вышестоящим сетевым коммутаторам (Top-of-Rack, ToR).
- **ECMP (Equal-Cost Multi-Path)** — механизм маршрутизации сетевых коммутаторов L3, распределяющий входящий сетевой трафик между несколькими равнозначными путями к серверам Nginx на основе хэш-функции от сетевого 5-tuple (IP источника/назначения, порт источника/назначения, протокол).
- **Отзыв маршрута (Route Withdrawal)** — процедура, при которой локальный BGP-демон (Bird, FRR, ExaBGP) прекращает анонсировать Anycast VIP коммутаторам в случае сбоя Nginx, мгновенно исключая узел из схемы балансировки.
- **BFD (Bidirectional Forwarding Detection)** — легковесный низкоуровневый сетевой протокол обнаружения сбоев каналов за десятки миллисекунд (sub-second failover), работающий в связке с BGP.
- **Плавающий адрес на Loopback (VIP on `lo` / `dummy`)** — Anycast IP-адрес, назначаемый на виртуальный локальный интерфейс сервера Nginx с маской `/32` (IPv4) или `/128` (IPv6), чтобы сервер мог принимать пакеты, не отвечая на ARP-запросы во внешнюю сеть.

---

## 2. Архитектура: Keepalived (Active-Passive) vs BGP Anycast + ECMP (Active-Active)

### 2.1 Предел масштабирования Keepalived

Классическая схема с **Keepalived (VRRP)** является стандартом начального уровня, однако обладает жесткими архитектурными ограничениями:
1. **Схема Active-Passive:** Трафик принимает только Master-узел. Backup-сервер простаивает и не утилизирует выделенное оборудование.
2. **Ограничение полосы одного сервера:** Максимальная пропускная способность кластера ограничена сетевой картой и шиной одной ноды (например, 10–40 Gbps).
3. **Привязка к L2-домену:** Протокол VRRP требует нахождения серверов в одном широковещательном сегменте (VLAN/L2), что создает единую точку отказа на уровне L2-коммутатора.

### 2.2 Архитектура BGP Anycast + ECMP

В архитектуре BGP Anycast все ноды Nginx работают в режиме **Active-Active**:

```text
                     Входящий интернет/клиентский трафик
                                      │
                                      ▼
                        [ Граничные L3-маршрутизаторы ]
                                      │
                 ┌────────────────────┴────────────────────┐
                 │                                         │
        [ ToR Switch 01 ]                         [ ToR Switch 02 ]
         (ECMP Hashing)                            (ECMP Hashing)
                 │                                         │
        ┌────────┴────────────────────┬────────────────────┴────────┐
        │ eBGP / BFD                  │ eBGP / BFD                  │ eBGP / BFD
        ▼                             ▼                             ▼
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│  Nginx Node 01   │          │  Nginx Node 02   │          │  Nginx Node 03   │
│ - VIP: 198.51.100.10/32    │ - VIP: 198.51.100.10/32    │ - VIP: 198.51.100.10/32    │
│ - Bird 2 (BGP)   │          │ - Bird 2 (BGP)   │          │ - Bird 2 (BGP)   │
│ - Nginx (L7)     │          │ - Nginx (L7)     │          │ - Nginx (L7)     │
└──────────────────┘          └──────────────────┘          └──────────────────┘
```

1. **Балансировка коммутатором (ECMP):** Входящие TCP-сессии хэшируются микросхемой коммутатора (ASIC) и распределяются по серверам Nginx.
2. **Линейная масштабируемость:** Добавление 4-й, 5-й или 10-й ноды Nginx пропорционально увеличивает пропускную способность (до сотен Gbps и миллионов RPS).
3. **Маршрутизация L3:** Серверы Nginx могут размещаться в разных стойках, разных VLAN и даже разных дата-центрах (Geo-Anycast).

---

## 3. Практическая реализация на базе Linux, Nginx и Bird 2

### Шаг 1: Настройка виртуального интерфейса на серверах Nginx

Anycast VIP назначается на виртуальный интерфейс `dummy` или алиас `lo:1`. Это исключает конфликты ARP-таблиц коммутаторов.

Временное назначение для проверки:
```bash
sudo ip link add dev dummy0 type dummy
sudo ip address add 198.51.100.10/32 dev dummy0
sudo ip link set dummy0 up
```

Постоянная конфигурация в systemd-networkd (`/etc/systemd/network/10-anycast-dummy.netdev`):
```ini
[NetDev]
Name=dummy0
Kind=dummy
```

`/etc/systemd/network/10-anycast-dummy.network`:
```ini
[Match]
Name=dummy0

[Network]
Address=198.51.100.10/32
```

Применение:
```bash
sudo networkctl reload
ip addr show dummy0
# → inet 198.51.100.10/32 scope global dummy0
```

---

### Шаг 2: Настройка эндпоинта Health Check в Nginx

Nginx должен отдавать статус работоспособности демону BGP на локальном интерфейсе (`127.0.0.1`):

```nginx
# /etc/nginx/conf.d/healthcheck.conf
server {
    listen 127.0.0.1:8080 default_server;
    server_name localhost;

    access_log off;

    location = /healthz {
        # Проверка работоспособности: возвращает 200 OK
        return 200 "OK\n";
    }

    # Для сложных контуров: проверка доступности бэкендов
    location = /ready {
        # Если локальный пул бэкендов мертв, возвращаем 503
        # Маршрутизатор снимет анонс и уведет трафик на соседние ноды
        proxy_pass http://internal_backend_status;
        proxy_intercept_errors on;
        error_page 502 503 504 =503 /fail;
    }

    location = /fail {
        return 503 "DEGRADED\n";
    }
}
```

Конфигурация боевого виртуального хоста Nginx на Anycast VIP:
```nginx
# /etc/nginx/conf.d/anycast_service.conf
server {
    listen 198.51.100.10:80;
    listen 198.51.100.10:443 ssl reuseport;
    server_name api.company.com;

    ssl_certificate     /etc/ssl/certs/company.crt;
    ssl_certificate_key /etc/ssl/private/company.key;

    location / {
        proxy_pass http://backend_pool;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

### Шаг 3: Скрипт проверки здоровья для Bird (`/usr/local/bin/check-nginx-health.sh`)

Скрипт проверяет ответ Nginx и управляет наличием статического маршрута в таблице ядра, на который завязан BGP-анонс:

```bash
#!/usr/bin/env bash
set -euo pipefail

VIP="198.51.100.10/32"
HEALTH_URL="http://127.0.0.1:8080/healthz"
ROUTE_TABLE=100

# Опрос Nginx с коротким таймаутом
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 1 --max-time 2 "$HEALTH_URL" || echo "000")

if [ "$HTTP_STATUS" -eq 200 ]; then
    # Nginx жив: добавляем маршрут в таблицу ядра, если его нет
    if ! ip route show table $ROUTE_TABLE | grep -q "$VIP"; then
        ip route add $VIP dev dummy0 table $ROUTE_TABLE
        logger -t nginx-anycast "Nginx is healthy. Route $VIP added to table $ROUTE_TABLE."
    fi
    exit 0
else
    # Nginx упал: удаляем маршрут. Bird снимет BGP-анонс!
    if ip route show table $ROUTE_TABLE | grep -q "$VIP"; then
        ip route del $VIP dev dummy0 table $ROUTE_TABLE
        logger -t nginx-anycast "CRITICAL: Nginx healthcheck failed (HTTP $HTTP_STATUS). Route $VIP withdrawn!"
    fi
    exit 1
fi
```

Скрипт запускается по systemd-таймеру каждые 1–2 секунды либо управляется демоном **bfdd** / **ExaBGP**.

---

### Шаг 4: Конфигурация BGP-демона Bird 2 (`/etc/bird/bird.conf`)

Конфигурация ноды Nginx для пиринга с ToR-коммутаторами по BGP:

```bird
log syslog all;
router id 10.0.1.11; # Уникальный IP ноды Nginx

# Проверка ядра и сетевых интерфейсов
protocol device {
    scan time 10;
}

# Отслеживание маршрутов таблицы 100 ядра (куда скрипт кладет VIP)
protocol kernel kernel_anycast {
    kernel table 100;
    learn;
    scan time 2;
    export none;
    import all;
}

# Протокол BFD для субсекундного обнаружения обрывов линка
protocol bfd {
    interface "eth0" {
        interval 300 ms;
        multiplier 3;
    };
}

# Фильтр: разрешаем анонсировать ТОЛЬКО наш Anycast VIP
filter anycast_vip_filter {
    if net = 198.51.100.10/32 then accept;
    reject;
}

# BGP-сессия к первому ToR-коммутатору
protocol bgp tor1 {
    local 10.0.1.11 as 65001;
    neighbor 10.0.1.1 as 65000;
    bfd on;

    ipv4 {
        import none;
        export filter anycast_vip_filter;
    };
}

# BGP-сессия ко второму ToR-коммутатору (отказоустойчивость коммутации)
protocol bgp tor2 {
    local 10.0.1.11 as 65001;
    neighbor 10.0.1.2 as 65000;
    bfd on;

    ipv4 {
        import none;
        export filter anycast_vip_filter;
    };
}
```

---

## 4. Эксплуатация и управление трафиком

### 4.1 Проверка состояния BGP-анонсов

```bash
# Проверка статуса BGP сессий в Bird
birdc show protocols
# → Name       Proto      Table      State  Since         Info
# → device1    Device     master4    up     10:00:00      
# → kernel_any Kernel     master4    up     10:00:00      
# → bfd1       BFD        master4    up     10:00:00      
# → tor1       BGP        master4    up     10:00:05      Established   
# → tor2       BGP        master4    up     10:00:05      Established

# Проверка экспортируемых маршрутов (анонсируется ли VIP)
birdc show route export tor1
# → 198.51.100.10/32   unicast [kernel_anycast 10:00:02] * (100)
```

### 4.2 Плавный вывод ноды из ротации (Graceful Drain)

При проведении регламентных работ узел выводится из балансировки без разрыва текущих сессий:

1. **Снятие BGP-анонса:**
   ```bash
   birdc disable tor1
   birdc disable tor2
   ```
   Коммутаторы исключают узел из ECMP-группы. Новые TCP SYN-пакеты уходят на соседние серверы.
2. **Ожидание завершения активных соединений (Drain Time):**
   ```bash
   # Мониторинг активных соединений через stub_status
   curl -s http://127.0.0.1:8080/stub_status
   # Ждем 30–60 секунд до завершения фоновых Keepalive-сессий
   ```
3. **Обслуживание и возврат в ротацию:**
   ```bash
   birdc enable tor1
   birdc enable tor2
   ```

---

## 5. Типичные проблемы и траблшутинг

| Проблема / Симптом | Причина | Диагностика | Решение |
|---|---|---|---|
| **Разрывы TCP-соединений (`Connection reset by peer`) при смене путей** | На коммутаторах настроен динамический ECMP без Resilient Hashing. При выводе одной ноды хэш пересчитывается для ВСЕХ клиентов, и активные TCP-пакеты попадают на соседнюю ноду без состояния сессии. | Всплеск сбросов TCP на клиентах при выводе ноды. | Включить на коммутаторах **Resilient Hashing** (Consistent Hashing) для ECMP-групп. |
| **Blackholing: Nginx упал, но трафик продолжает идти** | Скрипт проверки не удалил маршрут из ядра или BGP-демон завис, продолжая анонсировать VIP. | Коммутатор шлет пакеты на ноду, порт 80/443 не слушается. | Включить субсекундный BFD (`bfd on;`), завязать анонс на скрипт с `timeout` и мониторить ответ через `curl`. |
| **Сервер отвечает на ARP-запросы Anycast IP из физической сети** | VIP ошибочно повешен на физический интерфейс (`eth0`), а не на виртуальный `dummy0`/`lo`. | ARP-конфликт в локальной сети, трафик начинает идти только на один сервер. | Перенести VIP строго на `dummy0`. Включить `sysctl -w net.ipv4.conf.all.arp_ignore=1` и `net.ipv4.conf.all.arp_announce=2`. |
| **Несимметричная нагрузка между серверами Anycast (Polarization)** | Крупный корпоративный NAT генерирует миллионы запросов с одного IP/порта, перегружая одну ноду по хэшу 5-tuple. | Дисбаланс CPU на серверах кластера. | Проверить алгоритм хэширования на коммутаторах: использовать симметричный 5-tuple хэш с учетом TCP/UDP портов. |

---

## 6. Лучшие практики (Best Practices)

1. **Всегда используйте BFD совместно с BGP.** Без BFD время обнаружения недоступности соседа в BGP по умолчанию составляет до 90–180 секунд (`Hold Time`), что вызовет простой сервиса при падении интерфейса. BFD сокращает время переключения до 300–900 мс.
2. **Изолируйте ARP через параметры ядра Linux:**
   Добавьте в `/etc/sysctl.d/99-anycast-arp.conf`:
   ```ini
   net.ipv4.conf.all.arp_ignore = 1
   net.ipv4.conf.all.arp_announce = 2
   net.ipv4.conf.default.arp_ignore = 1
   net.ipv4.conf.default.arp_announce = 2
   ```
3. **Синхронизируйте сессионные TLS-тикеты (STEK):** Поскольку разные запросы одного клиента могут при определенных условиях попасть на разные ноды кластера (например, при флапе линка ECMP), все серверы Nginx в Anycast-группе должны иметь идентичный синхронизированный файл ключей `ssl_session_ticket_key` (см. [nginx_tls_global_parameters.md](../../Security/TLS_SSL/nginx_tls_global_parameters.md)).
4. **Контролируйте максимальное число путей ECMP на коммутаторах:** Убедитесь, что настройка `max-paths` в BGP на ToR-коммутаторах равна или превышает количество серверов в Anycast-кластере (обычно 8, 16 или 32 пути).

---

## 7. Дополнительная информация

- [Балансировка нагрузки: сравнение решений и HA на Keepalived](./additional_info_and_comparisons.md) — классический Active-Passive кластер с VRRP.
- [Глобальные параметры TLS и ротация сессионных тикетов STEK](../../Security/TLS_SSL/nginx_tls_global_parameters.md) — обеспечение бесшовного TLS-резума между нодами кластера.
- [Теория и практика протокола BGP](../../../../Networking/Protocols/bgp.md) — сетевые атрибуты, пиринг и фильтрация маршрутов.
- [Обзор и настройка Keepalived](../../../../Networking/ServicesAndTools/keepalived_overview.md) — альтернативный подход к резервированию VIP.
