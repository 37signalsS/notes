# Настройка отказоустойчивого кластера Angie с Keepalived (VRRP)

**Актуально для:** Angie 1.12.x / Keepalived 2.4.x

## Определения

- **HA (High Availability):** архитектурный подход, обеспечивающий непрерывность предоставления сервиса и минимальное время простоя при отказе отдельных аппаратных или программных компонентов. Подробности — в **[обзоре High Availability](../../Concepts/High_Availability/ha_overview.md)**.
- **Angie:** высокопроизводительный веб-сервер и обратный прокси, отечественный форк Nginx с расширенными возможностями динамического конфигурирования, продвинутого мониторинга и кластерной синхронизации. Подробнее — в **[общем обзоре Angie](./angie_overview.md)**.
- **Keepalived:** системный демон для Linux, реализующий механизмы высокой доступности через управление виртуальным IP-адресом (VIP) на базе протокола VRRP, а также L4-балансировку LVS и мониторинг состояния сервисов. Детали — в **[обзоре Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)**.
- **VRRP (Virtual Router Redundancy Protocol):** сетевой протокол (RFC 5798 / RFC 3768), позволяющий группе хостов в одном L2-сегменте распределять владение виртуальным IP-адресом между активным узлом (`MASTER`) и резервными (`BACKUP`).
- **BFD (Bidirectional Forwarding Detection):** легковесный сетевой протокол (RFC 5880 / RFC 5881) для высокоскоростного обнаружения разрывов связи между соседними маршрутизаторами/узлами с субсекундным временем реакции (от 50–100 мс).
- **VIP (Virtual IP / Floating IP):** виртуальный IP-адрес, логически ассоциированный с кластером серверов. Адрес привязан к активному мастер-узлу и автоматически мигрирует на резервный узел при обнаружении сбоя.
- **Active-Passive:** архитектурная модель высокой доступности, при которой активный узел (`MASTER`) обрабатывает весь входящий трафик, а резервный (`BACKUP`) находится в состоянии ожидания и непрерывно отслеживает доступность мастера.
- **Active-Active (Multi-VIP):** топология, при которой оба узла одновременно обслуживают трафик (каждый узел является `MASTER` для своего VIP и `BACKUP` для соседнего).
- **Failover:** автоматический процесс переключения клиентской нагрузки на резервный узел при сбое активного сервиса, сети или хоста.
- **Failback (Preemption):** процесс возврата роли `MASTER` исходному основному узлу после восстановления его работоспособности. При выключенном режиме вытеснения (`nopreempt`) возврат блокируется во избежание лишних переключений.
- **Split-Brain:** аварийное состояние кластера, при котором из-за потери сетевой связности между узлами оба сервера одновременно объявляют себя `MASTER`, вызывая конфликт IP-адресов и нарушение маршрутизации.
- **Gratuitous ARP (GARP):** специальный широковещательный ARP-анонс, с помощью которого новый `MASTER` принудительно обновляет таблицы соответствия MAC/IP (ARP-кэш) на сетевых коммутаторах и клиентских машинах L2-домена.
- **`ip_nonlocal_bind`:** параметр ядра Linux (`net.ipv4.ip_nonlocal_bind`), разрешающий процессам открывать слушающие сокеты (`bind()`) на адреса, которые физически ещё не назначены интерфейсам хоста.
- **`conntrack`:** подсистема ядра Linux (Netfilter), отслеживающая состояния активных сетевых соединений (stateful inspection).
- **RTO (Recovery Time Objective):** целевое время восстановления сервиса после аварии.
- **RPO (Recovery Point Objective):** максимально допустимый объем потерь данных при сбое.

## Архитектура и основные концепции

### Топология и принцип работы кластера

Кластер высокой доступности на базе Angie и Keepalived развертывается в рамках единого широковещательного L2-сегмента (VLAN) локального дата-центра или серверной стойки:

```
                      Клиенты (LAN / Интранет / Периметр L3)
                                      │
                                      ▼
                      Шлюз по умолчанию / L2-коммутатор
                                      │
                  ┌───────────────────┴───────────────────┐
                  │          Виртуальный IP (VIP)         │
                  │             192.168.1.100             │
                  ▼                                       ▼
        ┌──────────────────┐                    ┌──────────────────┐
        │   Узел 1 (Node1) │                    │   Узел 2 (Node2) │
        │    192.168.1.101 │                    │    192.168.1.102 │
        │                  │   VRRP (Unicast)   │                  │
        │ ┌──────────────┐ │ ◄────────────────► │ ┌──────────────┐ │
        │ │  Keepalived  │ │     BFD (UDP 3784) │ │  Keepalived  │ │
        │ └──────┬───────┘ │                    │ └──────┬───────┘ │
        │        │ Health  │                    │        │ Health  │
        │ ┌──────▼───────┐ │  angie-ha-sync/SSH │ ┌──────▼───────┐ │
        │ │     Angie    │ │ ◄────────────────► │ ┌     Angie    │ │
        │ └──────┬───────┘ │   stream zone_sync │ └──────┬───────┘ │
        └────────┼─────────┘                    └────────┼─────────┘
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     ▼
                     Пул бэкендов (Upstream Servers)
```

1. **Роли и приоритеты:** Каждому узлу в файле `keepalived.conf` задается базовый приоритет (`priority`, от 1 до 254). Узел с наибольшим эффективным приоритетом переходит в состояние `MASTER` и назначает VIP на физический интерфейс. Узлы с меньшим приоритетом переходят в состояние `BACKUP`.
2. **Обмен анонсами (VRRP Advertisements):** `MASTER` узел периодически (интервал `advert_int`, обычно 1 сек или sub-second при VRRPv3) отправляет пакеты VRRP (протокол IP 112). Если `BACKUP` не получает анонсы в течение времени обнаружения `(3 * advert_int) + skew_time`, где `skew_time = (256 - priority) / 256`, он инициирует процедуру выборов нового мастера.
3. **Обновление L2-таблиц (Gratuitous ARP):** Как только узел становится `MASTER`, демон Keepalived выполняет сброс серии широковещательных пакетов Gratuitous ARP. Это заставляет L2-коммутаторы перезаписать свои CAM-таблицы (MAC address table) и направить фреймы с адресом VIP на новый физический порт коммутатора.
4. **Транспорт VRRP — Unicast vs Multicast:**
   - **Multicast (`224.0.0.18`):** стандартный режим VRRP. В корпоративных сетях коммутаторы с включенным IGMP Snooping без настроенного Querier, фильтрами Storm Control или межсетевыми экранами могут блокировать широковещательный multicast.
   - **Unicast (`unicast_peer`):** прямое взаимодействие между реальными IP-адресами серверов кластера. Исключает проблемы фильтрации мультикаста, предотвращает пересечения с другими VRRP-кластерами в общем VLAN и является промышленным стандартом надежности.

### Сетевой стек Linux и параметры sysctl

Для стабильной работы HA-кластера необходима точечная настройка сетевого стека ядра Linux:

1. **`net.ipv4.ip_nonlocal_bind = 1`:**
   В штатном режиме веб-сервер Angie запускается и привязывается (`bind()`) ко всем настроенным адресам, включая VIP (`listen 192.168.1.100:80`). На узле `BACKUP` адрес VIP физически отсутствует на сетевой карте. Без этого флага ядро вернет ошибку `bind(): Cannot assign requested address`, и процесс Angie упадет при старте, сделав резервирование невозможным.
2. **`net.ipv4.conf.all.arp_ignore = 1` и `net.ipv4.conf.all.arp_announce = 2`:**
   По умолчанию ядро Linux отвечает на ARP-запросы к любому локальному адресу хоста с любого интерфейса (модель слабых хостов — weak host model). В кластерах с несколькими физическими интерфейсами или VIP это приводит к состоянию ARP-race, когда резервный узел отвечает на ARP-запрос к VIP своим MAC-адресом, нарушая передачу пакетов. Указанные флаги заставляют ядро отвечать на ARP только в том случае, если запрошенный IP назначен интерфейсу, на который пришел запрос.
3. **`net.ipv4.ip_forward = 1`:**
   Необходим, если Angie выполняет функции прозрачного проксирования (Transparent Proxying) или узел выполняет маршрутизацию между сегментами.

### Механизмы отслеживания работоспособности (Health Tracking)

Keepalived рассчитывает динамический приоритет узла: $EffectivePriority = BasePriority \pm Weight$. Если проверка завершается сбоем, приоритет узла падает ниже приоритета соседа, вызывая штатный failover:

1. **`vrrp_track_process` (нативный трекинг процесса):**
   Появился в Keepalived 2.0+. Демон опрашивает существование процесса `angie` через интерфейс ядра (netlink/proc) без порождения дочерних процессов оболочки (`fork/exec`). Не создает нагрузки на процессор и мгновенно регистрирует падение сервиса.
2. **`track_bfd` (аппаратно-независимый быстрый детектор):**
   Обнаруживает отказ сетевого линка или зависание соседней ноды за 150–300 мс (интервал 100 мс $\times$ 3 множителя). Избавляет от необходимости ожидать стандартный трехсекундный тайм-аут VRRP.
3. **`vrrp_script` (L7-проверка веб-сервера):**
   Выполняет внешний сценарий или вызов `curl` к локальному эндпоинту Angie (`/health_check` или `/api/status/`). Проверяет реальную способность воркеров Angie отдавать контент и состояние бэкендов.
4. **`track_interface`:**
   Контролирует состояние физического линка сетевого адаптера (например, `enp1s0`). При падении кабеля или интерфейса узел немедленно переходит в состояние `FAULT`.
5. **`track_file`:**
   Отслеживает состояние служебного файла-триггера через механизм `inotify`. Позволяет администратору инициировать вывод сервера на техобслуживание созданием или изменением файла.

### Поведение активных сессий (L4 vs L7) и модуль zone_sync

- **Разрыв TCP-сессий при Failover:** При переключении VIP сетевой адаптер нового мастера начинает принимать входящие пакеты. Однако таблицы отслеживания соединений Netfilter (`conntrack`) и сокеты пользовательского пространства на новом узле не содержат состояния прерванных TCP-сессий старого узла. Активные соединения (длительные загрузки файлов, WebSocket, gRPC) сбрасываются (клиент получает TCP RST) и должны переподключиться. Короткие HTTP-запросы обрабатываются прозрачно за счет встроенных механизмов повтора в HTTP-клиентах и браузерах.
- **Кластерная синхронизация состояния в Angie (модуль `zone_sync`):**
  В базовом веб-сервере счетчики rate limiting (`limit_req`), лимиты соединений (`limit_conn`) и сессионные привязки (`sticky learn`) хранятся в локальной разделяемой памяти процесса. Модуль `zone_sync` (в блоке `stream` Angie PRO) позволяет организовать полносеточную (full-mesh) синхронизацию общих зон памяти между всеми узлами кластера по выделенному TCP-порту. Благодаря этому клиент, исчерпавший лимит запросов на первом узле, остается ограниченным и после миграции VIP на второй узел.

### Сравнение RTO и RPO

| Компонент / Сценарий | RTO (Время восстановления) | RPO (Потеря состояния) | Примечания |
| :--- | :--- | :--- | :--- |
| **VRRP по умолчанию (advert_int 1s)** | 3–4 секунды | 0 (конфигурация) | Разрыв активных TCP-сессий, повтор запросов клиентами |
| **VRRP + BFD (100ms $\times$ 3)** | 250–400 миллисекунд | 0 (конфигурация) | Практически незаметно для пользователей браузеров |
| **Синхронизация конфигураций (`angie-ha-sync`)** | 1–2 секунды | $\approx 0$ | Автоматическая передача `.conf` и валидация через `angie -t` |
| **Сессии и Rate Limiting без `zone_sync`** | Сброс при переключении | Потеря счетчиков лимитов | Накопленная статистика обнуляется |
| **Сессии и Rate Limiting с `zone_sync`** | Непрерывно | $\approx 0$ | Память синхронизируется в реальном времени по сети |

## Практические сценарии

### Предварительная подготовка операционной системы

Настройка выполняется на обоих серверах кластера под управлением Debian / Ubuntu или RHEL / Rocky Linux.

#### Шаг 1: Тюнинг ядра через sysctl

Создайте файл `/etc/sysctl.d/99-angie-ha.conf`:

```ini
# Разрешить привязку к несуществующим IP (для запуска Angie на BACKUP узле)
net.ipv4.ip_nonlocal_bind = 1

# Изоляция ARP-ответов для исключения ARP-флаппинга в L2
net.ipv4.conf.all.arp_ignore = 1
net.ipv4.conf.default.arp_ignore = 1
net.ipv4.conf.all.arp_announce = 2
net.ipv4.conf.default.arp_announce = 2

# При необходимости работы с IPv6 VIP
net.ipv6.ip_nonlocal_bind = 1
```

Примените параметры:

```bash
sudo sysctl --system
# → Applying /etc/sysctl.d/99-angie-ha.conf ...
# → net.ipv4.ip_nonlocal_bind = 1
# → net.ipv4.conf.all.arp_ignore = 1
# → net.ipv4.conf.all.arp_announce = 2
```

#### Шаг 2: Создание непривилегированного пользователя для проверок

В целях соблюдения стандартов безопасности SRE запуск внешних проверочных скриптов Keepalived должен осуществляться от выделенного пользователя, а не от `root`:

```bash
sudo useradd -r -s /usr/sbin/nologin -c "Keepalived script runner" keepalived_script
```

#### Шаг 3: Настройка межсетевого экрана (Firewall)

Для корректной работы кластера необходимо открыть:
- Протокол **VRRP** (IP protocol 112) между узлами кластера.
- Протокол **BFD** (UDP-порт 3784) для одношагового контроля связности.
- Порты веб-трафика (TCP 80, 443).
- Порт межсерверной синхронизации памяти `zone_sync` (TCP 9000), если используется.

**Настройка через nftables (`/etc/nftables.conf`):**

```nftables
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить loopback и установленные сессии
        iif "lo" accept
        ct state established,related accept

        # VRRP протокол от соседа по кластеру
        ip saddr 192.168.1.102 ip protocol vrrp accept
        ip saddr 192.168.1.101 ip protocol vrrp accept

        # BFD (порт 3784 UDP)
        ip saddr { 192.168.1.101, 192.168.1.102 } udp dport 3784 accept

        # Трафик zone_sync Angie (только между нодами)
        ip saddr { 192.168.1.101, 192.168.1.102 } tcp dport 9000 accept

        # Входящий HTTP/HTTPS трафик на VIP и локальные IP
        tcp dport { 80, 443 } accept

        # ICMP для диагностики
        ip protocol icmp accept
    }
}
```

**Настройка через iptables:**

```bash
sudo iptables -A INPUT -s 192.168.1.102 -p 112 -j ACCEPT
sudo iptables -A INPUT -s 192.168.1.102 -p udp --dport 3784 -j ACCEPT
sudo iptables -A INPUT -s 192.168.1.102 -p tcp --dport 9000 -j ACCEPT
```

---

### Сценарий 1: Базовая конфигурация Active-Passive с BFD и API-трекингом

Параметры схемы:
- **Узел 1 (`node1`, MASTER):** `192.168.1.101`, интерфейс `enp1s0`.
- **Узел 2 (`node2`, BACKUP):** `192.168.1.102`, интерфейс `enp1s0`.
- **Виртуальный адрес (VIP):** `192.168.1.100`.

#### Шаг 1: Установка пакетов

```bash
sudo apt-get update && sudo apt-get install -y keepalived curl jq
```

#### Шаг 2: Настройка эндпоинтов здоровья в Angie

На обоих узлах создается служебный виртуальный хост в `/etc/angie/http.d/health.conf`:

```nginx
server {
    listen 127.0.0.1:8080;
    server_name 127.0.0.1;

    # Базовая L7-проверка
    location /health_check {
        access_log off;
        return 200 "healthy\n";
    }

    # REST API статус Angie для мониторинга
    location /api/ {
        api /status/;
        allow 127.0.0.1;
        deny all;
        access_log off;
    }
}
```

Проверьте синтаксис и перезагрузите веб-сервер:

```bash
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

sudo systemctl reload angie
```

#### Шаг 3: Скрипт проверки состояния Angie

Создайте файл `/etc/keepalived/check_angie.sh`:

```bash
#!/bin/bash
set -eo pipefail

# 1. Быстрая проверка ответа локального эндпоинта
if ! /usr/bin/curl -sf --max-time 2 http://127.0.0.1:8080/health_check > /dev/null 2>&1; then
    exit 1
fi

# 2. Проверка доступности воркеров через статус REST API
READY=$(/usr/bin/curl -sf --max-time 2 http://127.0.0.1:8080/api/status/ | /usr/bin/jq -r '.ready // true' 2>/dev/null || echo "false")
if [ "$READY" != "true" ]; then
    exit 1
fi

exit 0
```

Установите права доступа (владелец `root`, группа `keepalived_script`):

```bash
sudo chown root:keepalived_script /etc/keepalived/check_angie.sh
sudo chmod 0750 /etc/keepalived/check_angie.sh
```

#### Шаг 4: Конфигурация Keepalived на MASTER (`node1`)

Файл `/etc/keepalived/keepalived.conf`:

```keepalived
global_defs {
    router_id node1_angie_gw
    enable_script_security
    script_user keepalived_script

    # Параметры GARP для ускоренного обновления коммутаторов
    vrrp_garp_master_delay 1
    vrrp_garp_master_repeat 2
    vrrp_garp_master_refresh 60
    vrrp_garp_master_refresh_repeat 2
}

# Сессия BFD для субсекундного обнаружения падения линка/узла
bfd_instance bfd_angie_peer {
    neighbor_ip 192.168.1.102
    source_ip 192.168.1.101
    interval 100     # Интервал опроса: 100 мс
    multiplier 3     # Падение фиксируется через 300 мс
}

# Нативный мониторинг процесса Angie без вызова fork
vrrp_track_process track_angie_proc {
    process angie
    weight -30       # Штраф при отсутствии процесса в ОС
}

# L7-проверка через HTTP-эндпоинт
vrrp_script chk_angie_l7 {
    script "/etc/keepalived/check_angie.sh"
    interval 2
    timeout 2
    weight -20       # Дополнительный штраф при сбое логики
    fall 2
    rise 2
}

vrrp_instance VI_ANGIE_MAIN {
    state BACKUP     # Всегда BACKUP в связке с nopreempt для исключения флаппинга
    interface enp1s0
    virtual_router_id 51
    priority 110      # Базовый приоритет выше, чем у node2 (100)
    advert_int 1
    nopreempt        # Не перехватывать VIP автоматически при восстановлении ноды

    unicast_src_ip 192.168.1.101
    unicast_peer {
        192.168.1.102
    }

    authentication {
        auth_type PASS
        auth_pass A9eKpV24
    }

    virtual_ipaddress {
        192.168.1.100/24 dev enp1s0 label enp1s0:vip
    }

    track_bfd {
        bfd_angie_peer weight 40
    }

    track_process {
        track_angie_proc
    }

    track_script {
        chk_angie_l7
    }

    notify_master "/etc/keepalived/notify.sh MASTER VI_ANGIE_MAIN"
    notify_backup "/etc/keepalived/notify.sh BACKUP VI_ANGIE_MAIN"
    notify_fault  "/etc/keepalived/notify.sh FAULT VI_ANGIE_MAIN"
}
```

#### Шаг 5: Конфигурация Keepalived на BACKUP (`node2`)

Файл `/etc/keepalived/keepalived.conf`:

```keepalived
global_defs {
    router_id node2_angie_gw
    enable_script_security
    script_user keepalived_script

    vrrp_garp_master_delay 1
    vrrp_garp_master_repeat 2
    vrrp_garp_master_refresh 60
    vrrp_garp_master_refresh_repeat 2
}

bfd_instance bfd_angie_peer {
    neighbor_ip 192.168.1.101
    source_ip 192.168.1.102
    interval 100
    multiplier 3
}

vrrp_track_process track_angie_proc {
    process angie
    weight -30
}

vrrp_script chk_angie_l7 {
    script "/etc/keepalived/check_angie.sh"
    interval 2
    timeout 2
    weight -20
    fall 2
    rise 2
}

vrrp_instance VI_ANGIE_MAIN {
    state BACKUP
    interface enp1s0
    virtual_router_id 51
    priority 100      # Базовый приоритет ниже, чем у node1 (110)
    advert_int 1
    nopreempt

    unicast_src_ip 192.168.1.102
    unicast_peer {
        192.168.1.101
    }

    authentication {
        auth_type PASS
        auth_pass A9eKpV24
    }

    virtual_ipaddress {
        192.168.1.100/24 dev enp1s0 label enp1s0:vip
    }

    track_bfd {
        bfd_angie_peer weight 40
    }

    track_process {
        track_angie_proc
    }

    track_script {
        chk_angie_l7
    }

    notify_master "/etc/keepalived/notify.sh MASTER VI_ANGIE_MAIN"
    notify_backup "/etc/keepalived/notify.sh BACKUP VI_ANGIE_MAIN"
    notify_fault  "/etc/keepalived/notify.sh FAULT VI_ANGIE_MAIN"
}
```

#### Шаг 6: Скрипт уведомлений и запуск кластера

Создайте файл `/etc/keepalived/notify.sh`:

```bash
#!/bin/bash
STATE=$1
NAME=$2

logger -t keepalived-notify "Instance $NAME transitioned to state $STATE"

case $STATE in
    "MASTER")
        # Действия при захвате VIP: принудительный сброс ARP, алерт в систему мониторинга
        /usr/sbin/arping -c 2 -I enp1s0 192.168.1.100 || true
        ;;
    "BACKUP"|"FAULT")
        # Очистка локальных временных данных при необходимости
        ;;
esac
exit 0
```

Установите права и запустите службу:

```bash
sudo chown root:keepalived_script /etc/keepalived/notify.sh
sudo chmod 0750 /etc/keepalived/notify.sh

sudo chmod 0600 /etc/keepalived/keepalived.conf
sudo systemctl enable --now keepalived

# Проверка распределения VIP на node1
ip -4 addr show dev enp1s0
# → inet 192.168.1.101/24 brd 192.168.1.255 scope global enp1s0
# → inet 192.168.1.100/24 scope global secondary enp1s0:vip
```

---

### Сценарий 2: Dual Active-Active (Multi-VIP) и синхронизация через vrrp_sync_group

В продакшн-окружениях режим Active-Passive приводит к простою половины вычислительных мощностей. Модель Active-Active позволяет распределить трафик между двумя VIP:
- **VIP 1 (`192.168.1.100`):** `node1` является `MASTER`, `node2` — `BACKUP`. На него направлен публичный DNS-домен `app1.internal`.
- **VIP 2 (`192.168.1.200`):** `node2` является `MASTER`, `node1` — `BACKUP`. На него направлен DNS-домен `app2.internal`.
- Если у серверов два физических интерфейса (внешний VLAN 10 и внутренний DMZ VLAN 20), директива `vrrp_sync_group` гарантирует синхронный перенос обоих адресов при отказе любого из интерфейсов.

Конфигурация `node1` (`/etc/keepalived/keepalived.conf`):

```keepalived
global_defs {
    router_id node1_active_active
    enable_script_security
    script_user keepalived_script
}

vrrp_track_process track_angie {
    process angie
    weight -30
}

# Синхронизация состояний двух интерфейсов (External + DMZ) для Сервиса 1
vrrp_sync_group VG_SERVICE_1 {
    group {
        VI_SRV1_EXT
        VI_SRV1_DMZ
    }
}

# Сервис 1 — Мастер на Node 1
vrrp_instance VI_SRV1_EXT {
    state MASTER
    interface enp1s0.10
    virtual_router_id 61
    priority 110
    advert_int 1
    unicast_src_ip 192.168.10.101
    unicast_peer { 192.168.10.102 }

    virtual_ipaddress {
        192.168.10.100/24 dev enp1s0.10 label enp1s0.10:vip1
    }
    track_process { track_angie }
}

vrrp_instance VI_SRV1_DMZ {
    state MASTER
    interface enp1s0.20
    virtual_router_id 62
    priority 110
    advert_int 1
    unicast_src_ip 192.168.20.101
    unicast_peer { 192.168.20.102 }

    virtual_ipaddress {
        192.168.20.100/24 dev enp1s0.20 label enp1s0.20:vip1
    }
    track_process { track_angie }
}

# Сервис 2 — Бэкап на Node 1 (Мастер находится на Node 2)
vrrp_instance VI_SRV2_EXT {
    state BACKUP
    interface enp1s0.10
    virtual_router_id 71
    priority 100
    advert_int 1
    unicast_src_ip 192.168.10.101
    unicast_peer { 192.168.10.102 }

    virtual_ipaddress {
        192.168.10.200/24 dev enp1s0.10 label enp1s0.10:vip2
    }
    track_process { track_angie }
}
```

---

### Сценарий 3: Глубокий L7 Health Check состояния Upstream через REST API

Стандартный `vrrp_script` проверяет только факт того, что порт веб-сервера слушает подключения. Если бэкенды упали, веб-сервер продолжает отдавать ошибку 502 Bad Gateway, но Keepalived считает его здоровым.

Использование REST API Angie позволяет отслеживать здоровье группы `upstream` и вычислять процент живых бэкендов:

Скрипт `/usr/local/bin/check_upstream_health.sh`:

```bash
#!/bin/bash
set -eo pipefail

API_URL="http://127.0.0.1:8080/api/http/upstreams/backend_app/peers"

# Получение списка бэкендов в формате JSON
STATUS_JSON=$(/usr/bin/curl -sf --max-time 2 "$API_URL" || exit 1)

# Подсчет общего количества бэкендов и количества упавших (state != "up")
TOTAL=$(echo "$STATUS_JSON" | /usr/bin/jq 'length')
UP_COUNT=$(echo "$STATUS_JSON" | /usr/bin/jq '[.[] | select(.state == "up")] | length')

if [ "$TOTAL" -eq 0 ]; then
    # Апстримы не сконфигурированы
    exit 1
fi

# Если более 50% бэкендов недоступно — инициировать понижение приоритета
HEALTHY_RATIO=$(( UP_COUNT * 100 / TOTAL ))
if [ "$HEALTHY_RATIO" -lt 50 ]; then
    logger -t keepalived-check "Critical: Only $UP_COUNT of $TOTAL upstream peers are UP ($HEALTHY_RATIO%). Failing health check."
    exit 1
fi

exit 0
```

Подключение в `keepalived.conf`:

```keepalived
vrrp_script chk_upstream_pool {
    script "/usr/local/bin/check_upstream_health.sh"
    interval 3
    timeout 2
    weight -25
    fall 2
    rise 3
}
```

---

### Сценарий 4: Синхронизация SSL/TLS сертификатов и ACME

При автоматическом получении бесплатных сертификатов через ACME-модуль Angie или Certbot возникает проблема: проверка владения доменом (HTTP-01 Challenge) всегда приходит на текущий `MASTER`, владеющий VIP. Если второй узел попробует запросить сертификат, входящий запрос не дойдет до него.

#### Архитектурное решение для On-Premises:
1. **DNS-01 Challenge:** предпочтительный метод. Валидация домена происходит через TXT-запись во внутреннем DNS-сервере (Bind9 / PowerDNS), не завися от VIP.
2. **Централизованная синхронизация хранилища сертификатов:**
   Директория сертификатов `/var/lib/angie/acme/` или `/etc/angie/ssl/` синхронизируется между узлами с помощью демона `angie-ha-sync` или скрипта на базе `rsync` по SSH через системный таймер systemd.

Скрипт синхронизации `/usr/local/bin/sync_certificates.sh`:

```bash
#!/bin/bash
PEER_IP="192.168.1.102"
SSL_DIR="/etc/angie/ssl/"

# Запуск только на активном мастере
if ip addr show | grep -q "192.168.1.100"; then
    rsync -avz --delete -e "ssh -i /etc/angie/id_ha_sync -o StrictHostKeyChecking=no" \
        "$SSL_DIR" "angie-sync@$PEER_IP:$SSL_DIR"
    
    # Graceful reload на удаленном узле
    ssh -i /etc/angie/id_ha_sync "angie-sync@$PEER_IP" "sudo /usr/sbin/angie -t && sudo /bin/systemctl reload angie"
fi
```

---

### Сценарий 5: Кластерная синхронизация состояния сессий через stream zone_sync

В инфраструктурах с высокой нагрузкой потеря счетчиков ограничений частоты (`limit_req`) при переключении серверов позволяет атакующим беспрепятственно отправлять всплески запросов. Angie PRO поддерживает директиву `zone_sync`, синхронизирующую состояние разделяемой памяти по протоколу TCP.

#### Конфигурация Angie на Узле 1 (`/etc/angie/angie.conf`):

```nginx
# Модуль stream: синхронизация состояния зон
stream {
    zone_sync;

    server {
        listen 192.168.1.101:9000;
        zone_sync_server 192.168.1.101:9000;
        zone_sync_server 192.168.1.102:9000;

        # Тайм-ауты и буферы синхронизации
        zone_sync_buffers 256 4k;
        zone_sync_connect_timeout 1s;
    }
}

http {
    # Объявление кластерной зоны с параметром sync
    limit_req_zone $binary_remote_addr zone=ip_rate_limit:10m rate=20r/s sync;
    limit_conn_zone $binary_remote_addr zone=ip_conn_limit:10m sync;

    upstream backend_nodes {
        zone backend_nodes 256k;
        # Синхронизация sticky-сессий между мастером и бэкапом
        sticky learn create=1h lookup=1h zone=client_sessions:1m sync;
        server 10.0.0.11:8080;
        server 10.0.0.12:8080;
    }

    server {
        listen 192.168.1.100:80;
        server_name api.internal;

        limit_req zone=ip_rate_limit burst=10 nodelay;
        limit_conn ip_conn_limit 10;

        location / {
            proxy_pass http://backend_nodes;
        }
    }
}
```

На Узле 2 директива `listen` заменяется на `listen 192.168.1.102:9000;`, список серверов кластера `zone_sync_server` остается идентичным.

Проверка связности синхронизации:

```bash
sudo ss -tlnp | grep 9000
# → LISTEN 0 128 192.168.1.101:9000 ... users:(("angie",pid=1234,fd=7))

sudo journalctl -u angie --since "5m ago" | grep -i "zone_sync"
# → [info] ... zone_sync: connected to 192.168.1.102:9000
```

---

### Сценарий 6: Автоматизация развертывания через Ansible

Для повторяемого развертывания в корпоративной инфраструктуре применяется роль Ansible:

Структура плейбука `deploy_angie_ha.yml`:

```yaml
---
- name: Deploy Angie HA Cluster with Keepalived
  hosts: angie_ha_nodes
  become: true
  vars:
    vip_address: "192.168.1.100/24"
    vip_interface: "enp1s0"
    vrrp_router_id: 51
    vrrp_auth_password: "{{ vault_vrrp_password }}"

  tasks:
    - name: Configure sysctl parameters
      ansible.posix.sysctl:
        name: "{{ item.key }}"
        value: "{{ item.value }}"
        state: present
        reload: true
        sysctl_file: /etc/sysctl.d/99-angie-ha.conf
      loop:
        - { key: 'net.ipv4.ip_nonlocal_bind', value: '1' }
        - { key: 'net.ipv4.conf.all.arp_ignore', value: '1' }
        - { key: 'net.ipv4.conf.all.arp_announce', value: '2' }

    - name: Install required packages
      ansible.builtin.package:
        name:
          - keepalived
          - angie
          - curl
          - jq
          - arping
        state: present

    - name: Create unprivileged keepalived script user
      ansible.builtin.user:
        name: keepalived_script
        system: true
        shell: /usr/sbin/nologin
        create_home: false

    - name: Deploy healthcheck script
      ansible.builtin.template:
        src: check_angie.sh.j2
        dest: /etc/keepalived/check_angie.sh
        owner: root
        group: keepalived_script
        mode: '0750'

    - name: Deploy Keepalived configuration
      ansible.builtin.template:
        src: keepalived.conf.j2
        dest: /etc/keepalived/keepalived.conf
        owner: root
        group: root
        mode: '0600'
      notify: restart keepalived

    - name: Ensure services are enabled and started
      ansible.builtin.systemd:
        name: "{{ item }}"
        state: started
        enabled: true
      loop:
        - angie
        - keepalived

  handlers:
    - name: restart keepalived
      ansible.builtin.systemd:
        name: keepalived
        state: restarted
```

Шаблон `keepalived.conf.j2`:

```keepalived
global_defs {
    router_id {{ inventory_hostname }}
    enable_script_security
    script_user keepalived_script
    vrrp_garp_master_delay 1
    vrrp_garp_master_repeat 2
}

bfd_instance bfd_peer {
    neighbor_ip {{ peer_ip }}
    source_ip {{ ansible_default_ipv4.address }}
    interval 100
    multiplier 3
}

vrrp_track_process track_angie {
    process angie
    weight -30
}

vrrp_script chk_angie {
    script "/etc/keepalived/check_angie.sh"
    interval 2
    timeout 2
    weight -20
}

vrrp_instance VI_ANGIE {
    state BACKUP
    interface {{ vip_interface }}
    virtual_router_id {{ vrrp_router_id }}
    priority {{ host_priority }}
    advert_int 1
    nopreempt

    unicast_src_ip {{ ansible_default_ipv4.address }}
    unicast_peer {
        {{ peer_ip }}
    }

    authentication {
        auth_type PASS
        auth_pass {{ vrrp_auth_password }}
    }

    virtual_ipaddress {
        {{ vip_address }} dev {{ vip_interface }} label {{ vip_interface }}:vip
    }

    track_bfd { bfd_peer weight 40 }
    track_process { track_angie }
    track_script { chk_angie }
}
```

---

### Сценарий 7: Тестирование Failover и регламент планового обслуживания

#### Автоматизированный сценарий проверки переключения

Скрипт `test_cluster_failover.sh`:

```bash
#!/bin/bash
set -eo pipefail

VIP="192.168.1.100"
NODE1="192.168.1.101"
NODE2="192.168.1.102"

echo "=== 1. Проверка доступности VIP ==="
curl -sf -o /dev/null -w "%{http_code}\n" http://$VIP/health_check
# → 200

echo "=== 2. Определение текущего MASTER ==="
if ssh -o StrictHostKeyChecking=no root@$NODE1 "ip a | grep -q $VIP"; then
    CURRENT_MASTER=$NODE1
    STANDBY=$NODE2
else
    CURRENT_MASTER=$NODE2
    STANDBY=$NODE1
fi
echo "Текущий активный узел: $CURRENT_MASTER"

echo "=== 3. Эмуляция отказа Angie на $CURRENT_MASTER ==="
ssh root@$CURRENT_MASTER "systemctl stop angie"

echo "Ожидание срабатывания переключения (1.5 сек)..."
sleep 1.5

echo "=== 4. Проверка миграции VIP на $STANDBY ==="
ssh root@$STANDBY "ip a show dev enp1s0 | grep -q $VIP"
echo "Успешно: VIP мигрировал на $STANDBY"

echo "=== 5. Проверка ответа веб-сервера через VIP ==="
RESPONSE=$(curl -sf http://$VIP/health_check)
echo "Ответ сервиса: $RESPONSE"

echo "=== 6. Восстановление исходного узла ==="
ssh root@$CURRENT_MASTER "systemctl start angie"
sleep 2

# Проверка, что благодаря nopreempt узел остался на STANDBY без флаппинга
ssh root@$STANDBY "ip a show dev enp1s0 | grep -q $VIP"
echo "Флаппинг предотвращен: VIP стабильно удерживается резервным узлом."
```

#### Регламент планового техобслуживания (Zero-Downtime Maintenance)

Для проведения работ (обновление ОС, обновление ядра, апгрейд версии Angie) на активном мастере:

1. **Мягкий перенос трафика на соседний узел:**
   На активном узле временно остановите службу Keepalived:
   ```bash
   sudo systemctl stop keepalived
   ```
   VIP мгновенно мигрирует на второй узел через протокол VRRP.
2. **Проверка работоспособности сервиса:**
   Убедитесь через внешнюю систему мониторинга, что резервный узел принял нагрузку и отдает корректные ответы.
3. **Проведение технических работ:**
   Выполните регламентные работы на выведенном сервере (например, `apt update && apt upgrade -y`).
4. **Валидация конфигурации Angie:**
   ```bash
   sudo angie -t
   # → angie: the configuration file /etc/angie/angie.conf syntax is ok
   sudo systemctl start angie
   ```
5. **Возврат узла в кластер:**
   ```bash
   sudo systemctl start keepalived
   ```
   Благодаря директиве `nopreempt` узел войдет в состояние `BACKUP`, не забирая VIP обратно и не создавая лишних разрывов клиентских соединений.

## Операции и команды

### Управление и диагностика Keepalived

| Команда | Описание |
| :--- | :--- |
| `sudo systemctl status keepalived` | Проверка текущего статуса демона и журнала |
| `sudo systemctl reload keepalived` | Перечитывание конфигурационного файла без сброса VIP |
| `sudo keepalived --dump` | Дамп полной внутренней конфигурации в системный лог |
| `sudo kill -SIGUSR1 $(cat /run/keepalived.pid)` | Запись текущей статистики в файл `/tmp/keepalived.stats` |
| `sudo kill -SIGUSR2 $(cat /run/keepalived.pid)` | Запись текущих значений VRRP в `/tmp/keepalived.data` |
| `keepalived -v` | Вывод версии Keepalived и поддерживаемых модулей сборки |

Пример вывода проверки версии:

```bash
keepalived -v
# → Keepalived v2.4.0 (07/19/2026)
# → Copyright(C) 2001-2026 Alexandre Cassen, <acassen@gmail.com>
# → Built with kernel headers for Linux 6.8.0
# → System options: BFD VRRP VRRP_AUTH JSON LIBNL3 RUPT_SECURITY
```

### Диагностика сетевого трафика и состояния VIP

```bash
# Проверка наличия назначенного VIP на интерфейсе
ip -4 addr show dev enp1s0 label enp1s0:vip
# → inet 192.168.1.100/24 scope global secondary enp1s0:vip

# Отслеживание трафика протокола VRRP (IP protocol 112) в реальном времени
sudo tcpdump -i enp1s0 -nn -vv proto 112
# → IP 192.168.1.101 > 192.168.1.102: VRRPv2, Advertisement, vrid 51, prio 110, authtype simple, intvl 1s, length 20

# Отслеживание пакетов BFD (UDP порт 3784)
sudo tcpdump -i enp1s0 -nn port 3784
# → IP 192.168.1.101.3784 > 192.168.1.102.3784: BFDv1, Control, State Up, Diagnostic None

# Принудительная отправка Gratuitous ARP вручную
sudo arping -c 3 -I enp1s0 192.168.1.100
# → ARPING 192.168.1.100 from 192.168.1.100 enp1s0
# → Sent 3 probes (3 broadcast(s))
# → Received 0 response(s)
```

### Управление Angie и angie-ha-sync

```bash
# Валидация синтаксиса конфигурации Angie
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Безопасная горячая перезагрузка воркеров без потери соединений
sudo systemctl reload angie

# Проверка статуса службы синхронизации конфигураций
sudo systemctl status angie-ha-sync
# → Active: active (running) since Wed 2026-10-14 10:00:00 UTC; 4h ago

# Принудительная синхронизация директории /etc/angie/
sudo angie-ha-sync --force
# → [INFO] Configuration validation passed on peer 192.168.1.102. Reload executed successfully.
```

## Устранение неисправностей

### 1. Состояние Split-Brain (VIP поднят на обоих узлах)

**Симптомы:** Оба сервера находятся в состоянии `MASTER`. Трафик периодически пропадает или клиенты получают разные ответы.
**Диагностика:**
```bash
# На обоих узлах:
ip addr show | grep 192.168.1.100
# → На обоих серверах виден активный адрес!

# Проверка приема пакетов VRRP от соседа:
sudo tcpdump -i enp1s0 -nn proto 112
```
**Причины и устранение:**
- Межсетевой экран блокирует трафик протокола IP 112 между серверами. Разрешите входящие пакеты от IP соседа (`iptables -A INPUT -p 112 -s <peer_ip> -j ACCEPT`).
- Опечатка в адресах директив `unicast_src_ip` или `unicast_peer`. Проверьте соответствие физических IP.
- Несовпадение идентификатора роутера `virtual_router_id` или пароля `auth_pass` в блоке `authentication`.
- Разрыв прямого сетевого линка между серверами. Настройте `bfd_instance` для контроля кабеля.

### 2. VIP не мигрирует при сбое или падении Angie

**Симптомы:** Процесс Angie остановлен (`systemctl stop angie`), но узел остается `MASTER`, а трафик уходит в никуда.
**Диагностика:**
```bash
# Проверка текущего приоритета в Keepalived:
sudo journalctl -u keepalived -n 50 --no-pager | grep -i priority
```
**Причины и устранение:**
- Недостаточный штрафной вес (`weight`). Если базовый приоритет на мастере равен `110`, на резервном узле — `100`, а вес проверки процесса `weight -5`, то при падении процесса эффективный приоритет мастера составит `105`, что по-прежнему выше `100`. Резервный узел не сможет перехватить роль. Увеличьте отрицательный вес проверки до `-20` или `-30`.
- Ошибки прав доступа к скрипту `vrrp_script`. Скрипт не имеет флага исполнения (`chmod +x`) либо пользователь `script_user` не имеет прав чтения/запуска директории.
- Неправильное имя процесса в `vrrp_track_process` (убедитесь, что процесс в системе называется именно `angie`, а не `nginx`).

### 3. Ошибки SELinux / AppArmor при вызове скриптов

**Симптомы:** В системном логе появляются сообщения `keepalived: Fork-exec of script ... failed` или статус скрипта завершается с кодом 13 (Permission Denied).
**Диагностика:**
```bash
sudo ausearch -m avc -ts recent
# → type=AVC msg=audit(...): avc: denied { execute } for pid=... comm="keepalived" ...
```
**Причины и устранение:**
- В системах RHEL / Rocky Linux демон Keepalived запущен в изолированном контексте `keepalived_t`.
- Переместите скрипты проверки в `/usr/libexec/keepalived/` и восстановите контекст безопасности:
  ```bash
  sudo restorecon -Rv /usr/libexec/keepalived/
  ```
- Либо разрешите запуск пользовательских скриптов через SELinux boolean:
  ```bash
  sudo setsebool -P keepalived_connect_any 1
  ```

### 4. Веб-сервер не запускается при старте ОС с ошибкой "Cannot assign requested address"

**Симптомы:** После перезагрузки узел находится в состоянии `BACKUP`, а служба `angie.service` падает с ошибкой:
`bind() to 192.168.1.100:80 failed (99: Cannot assign requested address)`.
**Причины и устранение:**
- Не применен параметр ядра Linux `net.ipv4.ip_nonlocal_bind`.
- Выполните:
  ```bash
  sudo sysctl -w net.ipv4.ip_nonlocal_bind=1
  ```
- Убедитесь, что запись зафиксирована в `/etc/sysctl.d/99-angie-ha.conf`.

### 5. Флаппинг VIP (Flapping)

**Симптомы:** В системных журналах каждую секунду регистрируются переходы:
`Entering MASTER STATE` $\rightarrow$ `Entering BACKUP STATE`.
**Причины и устранение:**
- На обоих узлах задан режим `state MASTER` с одинаковым приоритетом. Настройте на резервном сервере `priority` ниже и переведите оба узла в `state BACKUP` в сочетании с `nopreempt`.
- Время выполнения внешнего скрипта превышает интервал опроса (`timeout > interval`). Увеличьте интервал опроса `interval 3` и уменьшите таймаут `curl --max-time 1`.
- Сетевая задержка (jitter) в L2-сегменте приводит к потере VRRP-анонсов. Увеличьте пороги `fall 3` и `rise 3` в блоке `vrrp_script`.

## Лучшие практики

### Безопасность и разграничение прав

- **Отказ от root для скриптов:** Всегда используйте директивы `enable_script_security` и `script_user keepalived_script` в `global_defs`. Никогда не исполняйте внешние проверки от суперпользователя.
- **Права на конфигурационные файлы:** Файл `/etc/keepalived/keepalived.conf` содержит пароли аутентификации VRRP. Установите права:
  ```bash
  sudo chmod 0600 /etc/keepalived/keepalived.conf
  sudo chown root:root /etc/keepalived/keepalived.conf
  ```
- **Использование auth_hmac в Keepalived 2.4.x:** Для предотвращения атак типа Spoofing и Replay в сегментах сети используйте криптографическую подпись анонсов `auth_hmac`.
- **Защита API Angie:** Эндпоинты `/api/` и `/health_check` должны быть строго ограничены доступом только с интерфейса локальной петли (`allow 127.0.0.1; deny all;`).

### Надежность и сетевая устойчивость

- **Обязательное использование `nopreempt`:** Предотвращает нежелательный обратный возврат роли `MASTER` на восстановившийся сервер (failback). Любое переключение — это кратковременный сброс TCP-сессий; переключаться обратно следует только вручную в запланированное окно обслуживания.
- **Комбинированный трекинг:** Совмещайте `vrrp_track_process` (для мгновенной реакции на крах бинарника) и `vrrp_script` с L7 API проверкой (для обнаружения зависших воркеров или недоступности пулов бэкендов).
- **Использование Unicast:** Исключите использование мультикаста (`224.0.0.18`) в корпоративных сетях с несколькими коммутаторами. Прямой `unicast_peer` изолирует кластер от влияния чужого трафика.
- **Тюнинг ARP-ответов:** Параметры `arp_ignore = 1` и `arp_announce = 2` обязательны во избежание загрязнения ARP-кэша коммутаторов.

### Мониторинг и Observability (SRE)

- **Метрики Keepalived в Prometheus:** Используйте `keepalived-exporter` для экспорта состояния ноды (`keepalived_vrrp_state`), счетчиков перехода (`keepalived_vrrp_transitions_total`) и доступности соседа.
- **Оповещения (Alerting Rules):** Настройте алерты в Alertmanager:
  - *KeepalivedSplitBrainDetected:* сумма узлов в состоянии `MASTER` для одного `vrid` превышает 1.
  - *KeepalivedNodeInFaultState:* узел кластера перешел в состояние `FAULT`.
  - *KeepalivedFrequentFlapping:* количество переходов ролей превышает 3 за 5 минут.
- **Логирование через systemd:** Запускайте Keepalived с ключом детального вывода в системный журнал (`-D -S 0`), что упрощает разбор инцидентов через `journalctl -u keepalived`.

## Дополнительная информация

- **[Обзор Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)** — архитектура протокола VRRP, RFC стандарты, LVS и субсекундные таймеры.
- **[Обзор веб-сервера Angie](./angie_overview.md)** — архитектурные отличия, процессная модель и модули.
- **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — методы балансировки, активные health checks и параметры upstream.
- **[Высокая доступность (HA): Обзор концепций](../../Concepts/High_Availability/ha_overview.md)** — модели надежности, кворум, расчет RTO/RPO.
- **[Защита от DoS и Cluster Zone Sync в Angie](./High_Load/dos_protection.md)** — детальная настройка модуля `zone_sync` для разделяемой памяти.
- **[Плавная перезагрузка Angie без простоя](./angie-graceful-reload.md)** — механизм смены бинарника и обновления конфигурации на лету.
