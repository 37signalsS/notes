# Отказоустойчивость Angie с BGP Anycast и ECMP

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x, BIRD 2.15+/3.x, FRRouting 10.x, Linux Kernel 5.15+/6.x

## Определения

* **BGP Anycast** — сетевая архитектура маршрутизации, при которой один и тот же публичный или корпоративный IP-адрес (Anycast VIP) анонсируется несколькими независимыми серверами Angie через протокол граничного шлюза (BGP) на сетевые коммутаторы (Top-of-Rack / Spine). Сеть автоматически направляет клиентский трафик к ближайшему или равноудаленным серверам.
* **ECMP (Equal-Cost Multi-Path)** — механизм сетевого оборудования и ядра Linux, распределяющий пакеты между несколькими маршрутами с одинаковой стоимостью. При использовании с BGP Anycast превращает группу серверов в горизонтально масштабируемый кластер **Active-Active** без узких мест.
* **Loopback VIP (Интерфейс-заглушка)** — привязка Anycast IP-адреса к виртуальному локальному интерфейсу (`lo:1` или `dummy0`) сервера. Поскольку несколько серверов имеют один IP, на физических сетевых интерфейсах ARP-ответы для этого IP строго подавляются ядром Linux во избежание сетевого шторма и конфликтов MAC-адресов.
* **Поляризация потоков (Flow Polarization)** — неравномерное распределение сетевого трафика алгоритмами хэширования ECMP на каскадах коммутаторов, приводящее к перегрузке одних узлов Angie и простою других.
* **Сброс соединений при перебалансировке (Connection Resets on Route Flap)** — разрыв длительных TCP-сессий при падении или вводе новой ноды Anycast из-за смены пути хэширования 5-tuple (`src_ip`, `src_port`, `dst_ip`, `dst_port`, `proto`). Решается настройкой тайм-аутов, Consistent Hashing на L4 или BPF/DSR.
* **BFD (Bidirectional Forwarding Detection)** — легковесный низкоуровневый протокол субсекундного обнаружения обрывов линка (50–300 мс), интегрируемый с BGP для мгновенного снятия анонсов маршрута до истечения медленных таймеров BGP Keepalive/Holdtime.

---

## Базовые концепции и архитектура

### Сравнение архитектур высокой доступности: VRRP (Keepalived) vs BGP Anycast

В руководстве [Отказоустойчивость Angie с Keepalived](./angie_ha_with_keepalived.md) описана классическая схема VRRP. Однако с ростом трафика свыше 10 Гбит/с или 100 000 RPS архитектура VRRP сталкивается с непреодолимыми физическими ограничениями:

| Параметр сравнения | VRRP (Keepalived) | BGP Anycast + ECMP |
| :--- | :--- | :--- |
| **Режим работы узлов** | **Active-Passive** (трафик идет только на Master; Backup простаивает) | **Active-Active** (100% серверов одновременно обрабатывают трафик) |
| **Предел масштабирования** | Пропускная способность одного сервера / сетевой карты (NIC) | **Линейное масштабирование:** $N \times \text{Bandwidth}$ (суммирование полосы) |
| **Единая точка отказа (SPOF)** | Виртуальный IP привязан к одному L2-домену | Нет привязки к L2; балансировка выполняется сетевой фабрикой на L3 |
| **Влияние отказа узла** | Переключение VIP за 1–3 секунды с кратковременным всплеском ARP | **Мгновенный обход отказавшего узла** на базе аппаратных таблиц коммутатора |
| **Сложность инфраструктуры** | Низкая (работает в любом плоском L2 сегменте) | Требует поддержки BGP/ECMP на сетевых коммутаторах (ToR/Leaf) |

### Топология сети и движение пакетов

```
                          [ Клиенты сети / Интернет ]
                                      │
                                      ▼
                        [ L3 Spine / Core Switches ]
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
         [ Leaf / ToR Switch A ]               [ Leaf / ToR Switch B ]
                   │      \                         /      │
                   │       \       ECMP Hashing    /       │
                   │        └──────────┬──────────┘        │
                   │                   │                   │
                   ▼                   ▼                   ▼
          ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
          │  Angie Node 01  │ │  Angie Node 02  │ │  Angie Node 03  │
          │ 192.168.10.21   │ │ 192.168.10.22   │ │ 192.168.10.23   │
          │ lo: 198.51.100.1│ │ lo: 198.51.100.1│ │ lo: 198.51.100.1│
          │ BIRD / FRR BGP  │ │ BIRD / FRR BGP  │ │ BIRD / FRR BGP  │
          └─────────────────┘ └─────────────────┘ └─────────────────┘
                   │                   │                   │
                   └───────────────────┼───────────────────┘
                                       ▼
                          [ Upstream Backend Servers ]
```

1. **Anycast IP (198.51.100.1):** настраивается на loopback-интерфейсе каждого сервера.
2. **Маршрутизация:** каждый сервер устанавливает eBGP-сессию со своим ToR-коммутатором и анонсирует префикс `198.51.100.1/32`.
3. **ECMP:** коммутаторы видят три равноценных маршрута к `198.51.100.1/32` через разные Next-Hop и равномерно распределяют клиентские TCP-потоки по хэшу 5-tuple.
4. **Health Check:** локальный фоновый скрипт или агент опрашивает Status API Angie (`http://127.0.0.1:8888/status/`). Если Angie деградирует или падает, демон маршрутизации отзывает анонс маршрута, и ToR-коммутатор исключает узел из ECMP-группы за доли секунды.

---

## Практические сценарии

### Сценарий 1: Подготовка сетевого стека Linux (ARP Flux Suppression)

Поскольку IP-адрес `198.51.100.1` поднят на loopback-интерфейсах всех нод, необходимо запретить ядру Linux отвечать на ARP-запросы для этого адреса через физические сетевые интерфейсы (`eth0` / `bond0`).

#### 1. Тюнинг sysctl (`/etc/sysctl.d/90-anycast-arp.conf`)

```ini
# Игнорировать ARP-запросы, если целевой IP не настроен на входящем интерфейсе
net.ipv4.conf.all.arp_ignore = 1
net.ipv4.conf.default.arp_ignore = 1

# Использовать только адрес исходящего интерфейса при генерации ARP-ответов
net.ipv4.conf.all.arp_announce = 2
net.ipv4.conf.default.arp_announce = 2

# Разрешить привязку сокетов к нелокальным адресам (на случай задержки поднятия интерфейса)
net.ipv4.ip_nonlocal_bind = 1
```

Применение настроек ядра:

```bash
sudo sysctl --system
# → * Applying /etc/sysctl.d/90-anycast-arp.conf ...
# → net.ipv4.conf.all.arp_ignore = 1
# → net.ipv4.conf.all.arp_announce = 2
# → net.ipv4.ip_nonlocal_bind = 1
```

#### 2. Создание виртуального Anycast интерфейса

Создайте unit-файл `/etc/systemd/network/10-dummy-anycast.netdev`:

```ini
[NetDev]
Name=dummy0
Kind=dummy
```

Создайте конфигурацию IP-адреса `/etc/systemd/network/20-dummy-anycast.network`:

```ini
[Match]
Name=dummy0

[Network]
Address=198.51.100.1/32
```

Применение конфигурации:

```bash
sudo systemctl restart systemd-networkd
ip addr show dummy0
# → dummy0: <BROADCAST,NOARP,UP,LOWER_UP> mtu 1500 qdisc noqueue state UNKNOWN group default
# → inet 198.51.100.1/32 scope global dummy0
```

---

### Сценарий 2: Автоматическое управление анонсами через BIRD 2

Демон BIRD 2 — де-факто отраслевой стандарт программной маршрутизации в Linux для Anycast-инфраструктур.

#### 1. Скрипт проверки жизнеспособности Angie (`/usr/local/bin/angie-healthcheck.sh`)

Скрипт проверяет отклик локального Status API Angie. Если сервер отвечает кодом 200 и не находится в состоянии перегрузки, создается маркерный маршрут.

```bash
#!/usr/bin/env bash
set -euo pipefail

STATUS_URL="http://127.0.0.1:8888/status/angie"
CHECK_TIMEOUT=2

# Проверка доступности процесса и Status API
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${CHECK_TIMEOUT}" "${STATUS_URL}" || echo "000")

if [ "${HTTP_CODE}" -eq 200 ]; then
    # Проверка, что воркеры запущены
    WORKERS=$(curl -s --max-time "${CHECK_TIMEOUT}" "${STATUS_URL}" | grep -o '"processes":{"respawned":' || true)
    if [ -n "${WORKERS}" ]; then
        exit 0
    fi
fi

exit 1
```

Сделайте скрипт исполняемым:

```bash
sudo chmod +x /usr/local/bin/angie-healthcheck.sh
```

#### 2. Конфигурация BIRD 2 (`/etc/bird/bird.conf`)

BIRD анонсирует маршрут `198.51.100.1/32` на коммутаторы ToR только тогда, когда статический маршрут присутствует в протоколе проверки.

```text
log syslog all;
router id 192.168.10.21;

# Таблица синхронизации с ядром
protocol device {
    scan time 10;
}

# Отслеживание доступности Angie через периодический опрос
protocol static check_angie {
    ipv4;
    # Маршрут анонсируется только при наличии интерфейса dummy0
    route 198.51.100.1/32 via "dummy0";
}

# BGP-сессия к первому ToR-коммутатору
protocol bgp tor1 {
    description "ToR-Switch-01";
    local 192.168.10.21 as 65001;
    neighbor 192.168.10.1 as 65000;
    
    # Использование BFD для субсекундной реакции
    bfd graceful;

    ipv4 {
        import none;
        export filter {
            # Анонсировать только Anycast VIP
            if net = 198.51.100.1/32 then accept;
            reject;
        };
    };
}

# BGP-сессия ко второму ToR-коммутатору (отказоустойчивость линков)
protocol bgp tor2 {
    description "ToR-Switch-02";
    local 192.168.10.21 as 65001;
    neighbor 192.168.10.2 as 65000;
    bfd graceful;

    ipv4 {
        import none;
        export filter {
            if net = 198.51.100.1/32 then accept;
            reject;
        };
    };
}
```

Проверка и запуск сервиса:

```bash
sudo bird -p
# → Configuration OK

sudo systemctl enable --now bird
sudo birdc show protocols
# → name     proto      table  state  since         info
# → device1  Device     master up     17:00:00.000
# → check_a* Static     master up     17:00:00.000
# → tor1     BGP        master up     17:00:02.112  Established
# → tor2     BGP        master up     17:00:02.115  Established
```

---

### Сценарий 3: Конфигурация виртуального сервера Angie под Anycast VIP

Файл `/etc/angie/conf.d/anycast_edge.conf`:

```nginx
# Мониторинг для локального BIRD health-check
server {
    listen 127.0.0.1:8888;
    server_name localhost;

    location /status/ {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }
}

# Публичный Anycast виртуальный сервер
server {
    # Привязка к Anycast VIP с опцией SO_REUSEPORT для параллельной обработки воркерами
    listen 198.51.100.1:80 reuseport;
    listen 198.51.100.1:443 ssl reuseport;
    server_name edge.example.internal;

    status_zone anycast_edge_zone;

    ssl_certificate /etc/angie/ssl/edge.crt;
    ssl_certificate_key /etc/angie/ssl/edge.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Защита от DoS и ограничение сессий
    limit_conn_zone $binary_remote_addr zone=anycast_conn:20m;
    limit_conn anycast_conn 50;

    location / {
        proxy_pass http://backend_anycast_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # Минимизация влияния перебалансировки ECMP
        proxy_next_upstream error timeout invalid_header http_502 http_503;
        proxy_next_upstream_tries 3;
    }
}

upstream backend_anycast_cluster {
    zone backend_zone 256k;
    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;
    keepalive 64;
}
```

Проверка конфигурации:

```bash
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

sudo systemctl reload angie
```

---

## Диагностика и устранение неисправностей

| Симптом | Вероятная причина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **BGP-соседство в состоянии `Connect` или `Active`** | Блокировка TCP-порта 179 файрволом (`nftables`) или несовпадение ASN | `birdc show protocols all tor1`<br>`sudo ss -tulpn \| grep 179` | Открыть TCP 179 в nftables; сверить номера автономных систем (`local as` и `neighbor as`). |
| **Сетевые коллизии и потеря пакетов (MAC Flapping на ToR)** | Нарушены директивы `arp_ignore` и `arp_announce` (сервер отвечает на ARP Anycast адреса) | `tcpdump -env -i eth0 arp` | Установить `net.ipv4.conf.all.arp_ignore=1` и `arp_announce=2` через sysctl. |
| **BGP-сессия Established, но трафик не поступает** | Маршрут отклоняется фильтром экспорта коммутатора или BIRD | `birdc show route export tor1` | Проверить фильтр `export filter` в BIRD; убедиться, что длина маски строго совпадает с правилом на коммутаторе (`/32`). |
| **Сброс соединений у клиентов (TCP RST)** | Разрыв BGP-сессии из-за таймаута при 100% нагрузке на CPU | `dmesg \| grep BFD`<br>`birdc show bfd sessions` | Выделить изолированные CPU-ядра для BIRD/FRR; настроить BFD с запасом `multiplier 3` и таймером `300ms`. |

---

## Рекомендации (Best Practices)

1. **Использование BFD:** Для промышленных сред всегда включайте BFD между серверами Angie и ToR-коммутаторами. Стандартный BGP Hold Timer (обычно 90–180 секунд) слишком медленный: при физическом сбое сервера клиенты будут испытывать 100% потерю пакетов до полутора минут. С BFD время обнаружения составляет 150–300 миллисекунд.
2. **Graceful Route Withdrawal (Дренирование узла):** Перед проведением регламентных работ (обновление ядра, замена железа) сначала остановите процесс BIRD (`systemctl stop bird`). ToR-коммутатор плавно снимет маршрут, и только через 30–60 секунд выполняйте остановку самого Angie.
3. **Разделение подсетей управления и Anycast:** Никогда не используйте Anycast VIP для SSH-доступа, системных обновлений или сбора метрик Prometheus. Служебные операции должны выполняться строго через реальные уникальные физические IP-адреса серверов (`Unicast IP`).
4. **Хэширование на коммутаторах:** Убедитесь, что на коммутаторах ToR включен режим симметричного хэширования ECMP (Symmetric Hashing), учитывающий оба направления потока, чтобы прямой и обратный трафик сессии не разрывался при асимметрии.

---

## Дополнительная информация

* **[Отказоустойчивость Angie с Keepalived](./angie_ha_with_keepalived.md)** — архитектура высокой доступности на базе VRRP (Active-Passive).
* **[Оптимизация производительности Angie](./High_Load/performance_optimization.md)** — тюнинг параметров ядра Linux, сокетов и сетевых очередей.
* **[Продвинутые сетевые технологии высокой доступности](../Concepts/High_Availability/ha_networking_advanced.md)** — BFD, MLAG, EVPN и принципы ECMP.
* **[Протокол BGP](../Networking/Protocols/bgp.md)** — основы протокола граничного шлюза, типы сообщений и алгоритмы выбора пути.
