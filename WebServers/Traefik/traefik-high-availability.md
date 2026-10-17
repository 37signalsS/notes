# High Availability Traefik: масштабирование, отказоустойчивость и zero-downtime

**Актуально для:** Traefik v3.x (протестировано на v3.4–v3.6) / Linux systemd / Keepalived 2.2+ / HAProxy 2.8+ / FRRouting 9.x+

## Определения

**High Availability (HA, высокая доступность)** — архитектурный подход к проектированию инфраструктуры, гарантирующий непрерывную доступность сервиса при аппаратном или программном сбое одного или нескольких узлов за счет избыточности (redundancy), мониторинга состояния и автоматического переключения (failover).

**Zero-Downtime Deployment (развертывание без простоя)** — методология обновления программного обеспечения или конфигурации, при которой обслуживание входящих пользовательских запросов не прерывается ни на секунду, а все активные соединения завершаются штатно.

**Stateless Ingress Proxy** — архитектурная модель, в которой прокси-сервер не хранит изменяемое разделяемое состояние сессий или пользователей в локальной памяти, делегируя хранение сессий бэкендам или распределенным хранилищам, что позволяет масштабировать прокси горизонтально добавлением одинаковых инстансов.

**VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол (RFC 5798), объединяющий группу физических или виртуальных серверов в один виртуальный маршрутизатор с единым плавающим IP-адресом (Virtual IP, VIP), автоматически мигрирующим на резервный узел при падении основного.

**L4 Load Balancing (балансировка транспортного уровня)** — распределение сетевых пакетов на уровне TCP/UDP без дешифрования TLS и разбора HTTP-заголовков (Keepalived IPVS, HAProxy в режиме `mode tcp`), обеспечивающее минимальные накладные расходы по CPU и передающее трафик на пул инстансов Traefik.

**BGP Anycast** — сетевая маршрутизация, при которой несколько географически распределенных или локальных серверов анонсируют один и тот же IP-адрес по протоколу Border Gateway Protocol (BGP). Сетевые маршрутизаторы распределяют трафик между ними с помощью механизма Equal-Cost Multi-Path (ECMP).

**ECMP (Equal-Cost Multi-Path)** — стратегия сетевой маршрутизации, позволяющая сетевым коммутаторам и маршрутизаторам распределять сетевые потоки (flow) по нескольким путям с одинаковой метрикой на основе хэша заголовков пакета (IP источника/назначения, порты TCP/UDP).

**Connection Draining (дренаж соединений)** — контролируемый перевод узла в режим обслуживания: прекращение регистрации новых входящих TCP-соединений с сохранением возможности дообработать уже принятые запросы в течение заданного интервала (`graceTimeout`).

**Split-Brain (расщепление кластера)** — аварийное состояние распределенной системы или пары узлов высокой доступности, при котором из-за потери сетевой связности между нодами обе стороны ошибочно считают соседа упавшим и одновременно захватывают один и тот же сетевой ресурс (например, Virtual IP), вызывая коллизию ARP и повреждение трафика.

---

## Базовые концепции и архитектура

### Stateless-природа Traefik OSS vs Traefik Enterprise

В открытой версии Traefik (OSS) **полностью отсутствуют** встроенные механизмы межузлового взаимодействия: распределенный консенсус (Raft), кластерная синхронизация таблиц соединений и общее распределенное хранилище сертификатов ACME (данные возможности доступны исключительно в коммерческом Traefik Hub Enterprise).

В архитектуре Traefik OSS каждый экземпляр является автономным, независимым и бессостоятельным (stateless) прокси-сервером:

```
                  ┌────────────────────────────────────────┐
                  │    Входящий клиентский трафик (L4)     │
                  └───────────────────┬────────────────────┘
                                      │
               ┌──────────────────────┴──────────────────────┐
               ▼                                             ▼
   ┌───────────────────────┐                     ┌───────────────────────┐
   │  Traefik Instance 1   │                     │  Traefik Instance 2   │
   │  (Stateless Node A)   │                     │  (Stateless Node B)   │
   │  - /ping :8082        │                     │  - /ping :8082        │
   │  - acme.json (local)  │                     │  - acme.json (local)  │
   └───────────┬───────────┘                     └───────────┬───────────┘
               │                                             │
               └──────────────────────┬──────────────────────┘
                                      │
               ┌──────────────────────┴──────────────────────┐
               ▼                                             ▼
    ┌────────────────────┐                        ┌────────────────────┐
    │  Backend Cluster   │                        │  Централизованная  │
    │  (App 1, 2, 3)     │                        │  конфигурация (KV) │
    └────────────────────┘                        └────────────────────┘
```

Фундаментальные следствия для проектирования отказоустойчивости (HA):
1. **Горизонтальное масштабирование:** Развертывание кластера сводится к запуску $N$ идентичных инстансов Traefik с одинаковой статической и динамической конфигурацией.
2. **Синхронизация конфигурации:** Инстансы должны получать динамические маршруты из единого централизованного источника (Consul Catalog, etcd, Redis KV) либо через систему управления конфигурациями (Ansible, GitOps) с локальным файловым провайдером (`providers.file`).
3. **Изоляция хранилища ACME:** Файл `acme.json` не поддерживает параллельную запись. Монтирование одного `acme.json` через сетевые файловые системы (NFS, SMB, GlusterFS) приводит к блокировкам, повреждению JSON-структуры и отзыву сертификатов.
4. **Метрики и мониторинг:** Каждая нода генерирует собственные независимые счетчики. Агрегация метрик и расчет SLO/SLA выполняются централизованно в Prometheus по лейблу `instance`.

---

### Топологии высокой доступности на Bare-Metal

Для обеспечения непрерывности обслуживания при отказе физического сервера или процесса Traefik применяются три базовые топологии:

| Топология | Механизм распределения | Утилизация ресурсов | Время реакции на отказ | Сложность внедрения |
| :--- | :--- | :--- | :--- | :--- |
| **Active-Passive (VRRP VIP)** | Keepalived с плавающим виртуальным IP | 50% (резервный узел простаивает) | 1–3 секунды | Низкая (требуется 2 сервера в одном L2-домене) |
| **Active-Active (Внешний L4 LB)** | Пара HAProxy / Keepalived IPVS + PROXY v2 | 100% (все ноды Traefik принимают трафик) | Мгновенно (на уровне пула L4) | Средняя (требуется выделенный L4-уровень) |
| **Active-Active (BGP Anycast)** | Маршрутизаторы ToR + ECMP + BIRD/FRR | 100% (балансировка на уровне сети) | Сотни миллисекунд | Высокая (требуется поддержка BGP в сетевой фабрике) |

---

### Жизненный цикл инстанса и механизм `/ping`

Встроенный эндпоинт `/ping` служит индикатором готовности инстанса обрабатывать клиентские запросы. Он связывает внутренний конвейер Traefik с внешними системами мониторинга и балансировки (Keepalived, HAProxy, F5):

```yaml
# Статическая конфигурация: /etc/traefik/traefik.yml
entryPoints:
  ping:
    address: "127.0.0.1:8082" # Рекомендуется изолировать на loopback или management IP

ping:
  entryPoint: "ping"

lifeCycle:
  requestAcceptGraceTimeout: 5s # Удержание приема новых соединений после SIGTERM
  graceTimeOut: 30s             # Предельное время дообработки активных in-flight запросов
```

Поведение эндпоинта `/ping` в зависимости от состояния:
- **HTTP 200 OK:** Инстанс полностью инициализирован, слушатели портов активны, процесс готов принимать трафик.
- **HTTP 503 Service Unavailable:** Процесс получил сигнал `SIGTERM` или `SIGINT` и перешел в фазу дренажа соединений (drain). Внешний L4/L7 балансировщик, фиксируя статус 503, немедленно исключает узел из пула маршрутизации, пока Traefik штатно дорабатывает текущие клиентские сессии.

---

### Стратегии управления TLS и ACME в HA-кластере

Поскольку параллельная запись в один `acme.json` недопустима, в production-контурах применяются три архитектурных подхода:

```
Подход 1: DNS-01 на каждой ноде        Подход 2: Внешний PKI / Certbot / Vault
┌──────────────────────────────┐        ┌──────────────────────────────────────┐
│ Traefik 1      Traefik 2     │        │ Certbot / HashiCorp Vault / step-ca  │
│ (DNS API)      (DNS API)     │        └──────────────────┬───────────────────┘
└──────┬─────────────┬─────────┘                           │ rsync / ansible / push
       ▼             ▼                                     ▼
 ┌───────────────────────────┐          ┌──────────────────────────────────────┐
 │    DNS Provider Zone      │          │ Traefik 1 & 2: Local cert files      │
 │    (_acme-challenge)      │          │ tls.certificates + providers.file    │
 └───────────────────────────┘          └──────────────────────────────────────┘
```

1. **DNS-01 Challenge с раздельными `acme.json` (децентрализованный выпуск):**
   Каждый узел Traefik настраивается на выпуск сертификатов через верификацию DNS TXT-записей по API DNS-провайдера. Каждый узел хранит свой изолированный локальный `acme.json`.
   - *Ограничение:* При количестве реплик более 3–5 существует риск превышения лимитов Let's Encrypt (Duplicate Certificate limit: 5 сертификатов в неделю на точный набор доменных имен).
2. **Внешний выпуск через Certbot / Lego / Vault (рекомендуемый SRE-паттерн):**
   Сертификаты выпускаются выделенным служебным демоном (Certbot, Lego или HashiCorp Vault) и раскладываются в формате PEM-файлов (`fullchain.pem`, `privkey.pem`) на все серверы Traefik с помощью Ansible, rsync или сетевых секретов.
   - Traefik подключает их через динамический файловый провайдер:
     ```yaml
     tls:
       certificates:
         - certFile: "/etc/ssl/traefik/app.example.com.crt"
           keyFile: "/etc/ssl/traefik/app.example.com.key"
     ```
   - При обновлении файлов Traefik автоматически перезагружает TLS-контекст без перезапуска процесса (`providers.file.watch: true`).
3. **Traefik Hub / Enterprise:**
   Использование коммерческого расширения с сервером консенсуса Raft, где один узел назначается ACME-лидером и централизованно передает сертификаты подписчикам по защищенному gRPC-каналу.

---

### Sticky Sessions (сессионная привязка) в горизонтальном кластере

Traefik поддерживает сессионную привязку клиентов к серверам бэкенда на основе cookie (`loadBalancer.sticky.cookie`). 

> **Критическое архитектурное ограничение:**
> В Traefik OSS таблица сопоставления хэшей cookie конкретным IP-адресам серверов хранится **в локальной оперативной памяти инстанса**. Между узлами Traefik синхронизация отсутвует.
> Если клиент с выставленной cookie при следующем запросе попадает через L4-балансировщик на другой узел Traefik:
> 1. Другой узел Traefik не сможет гарантировать попадание на тот же самый экземпляр бэкенда, если состав пула серверов изменялся или алгоритмы хэширования дали расхождение.
> 2. Возникает сброс сессии пользователя (unauthorized / разлогин).

**Инженерные способы решения:**
- **Consistent IP Hashing на внешнем L4:** Настройка внешнего балансировщика (HAProxy / IPVS) на распределение входящего трафика по хэшу IP-адреса клиента (`hash-type consistent`). В этом случае один и тот же клиент всегда попадает на один и тот же инстанс Traefik.
- **Stateless-архитектура бэкенда (Best Practice):** Вынос сессионного состояния из памяти бэкендов в распределенный кэш (Redis, Valkey) или переход на криптографические токены (JWT / OAuth2 / OIDC). В этом случае отпадает зависимость от sticky sessions на уровне прокси.

---

## Практические сценарии

### Сценарий 1: Active-Passive кластер с Keepalived VRRP и проверкой `/ping`

Классический сценарий высокой доступности для двух серверов Traefik на Bare-Metal в рамках одного L2-сегмента сети.

#### Топология стенда
- **Узел 1 (MASTER):** Hostname `traefik-01`, IP `192.168.10.21`, интерфейс `eth0`
- **Узел 2 (BACKUP):** Hostname `traefik-02`, IP `192.168.10.22`, интерфейс `eth0`
- **Виртуальный IP (VIP):** `192.168.10.100`
- **Порт проверки /ping:** `127.0.0.1:8082`

```
                      Клиенты (Входящий трафик)
                                 │
                                 ▼
                    Virtual IP: 192.168.10.100
                                 │
                 ┌───────────────┴───────────────┐
                 │ (VRRP Traffic redirection)    │
                 ▼                               ▼
       ┌───────────────────┐           ┌───────────────────┐
       │   traefik-01      │           │   traefik-02      │
       │   State: MASTER   │   VRRP    │   State: BACKUP   │
       │   Priority: 101   │◄─────────►│   Priority: 100   │
       │   VIP активен     │  Unicast  │   VIP в резерве   │
       │   /ping :8082     │           │   /ping :8082     │
       └───────────────────┘           └───────────────────┘
```

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`) на обоих узлах
```yaml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

entryPoints:
  ping:
    address: "127.0.0.1:8082"
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
  websecure:
    address: ":443"

ping:
  entryPoint: "ping"

lifeCycle:
  requestAcceptGraceTimeout: 5s
  graceTimeOut: 30s

providers:
  file:
    directory: "/etc/traefik/dynamic"
    watch: true

log:
  level: INFO
  format: json

accessLog:
  format: json
```

#### 2. Разрешение привязки к нелокальному IP в ядре Linux
Чтобы Traefik мог запуститься и слушать сокеты на интерфейсах до того, как Keepalived назначит виртуальный IP, активируем параметр `net.ipv4.ip_nonlocal_bind`:

```bash
echo "net.ipv4.ip_nonlocal_bind = 1" | sudo tee /etc/sysctl.d/50-keepalived-traefik.conf
sudo sysctl --system
# → net.ipv4.ip_nonlocal_bind = 1
```

#### 3. Скрипт проверки состояния Traefik (`/usr/local/bin/check_traefik.sh`)
Создаем скрипт проверки на обоих серверах:

```bash
sudo tee /usr/local/bin/check_traefik.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Опрос эндпоинта /ping Traefik.
# Возвращает код 0 только при HTTP 200.
# При коде 503 (дренаж при graceful shutdown) или сетевой ошибке завершается с кодом 1.
exec /usr/bin/curl --silent --fail --max-time 2 http://127.0.0.1:8082/ping >/dev/null 2>&1
EOF

sudo chmod +x /usr/local/bin/check_traefik.sh
```

#### 4. Конфигурация Keepalived на Узле 1 (`/etc/keepalived/keepalived.conf`)
```ini
global_defs {
    router_id traefik-01
    enable_script_security
    script_user root
}

vrrp_script chk_traefik {
    script "/usr/local/bin/check_traefik.sh"
    interval 2
    timeout 2
    weight -20
    fall 2
    rise 2
}

vrrp_instance VI_TRAEFIK {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass Tr@ef1kHAP@ss
    }

    unicast_src_ip 192.168.10.21
    unicast_peer {
        192.168.10.22
    }

    virtual_ipaddress {
        192.168.10.100/24 dev eth0 label eth0:vip
    }

    track_script {
        chk_traefik
    }
}
```

#### 5. Конфигурация Keepalived на Узле 2 (`/etc/keepalived/keepalived.conf`)
```ini
global_defs {
    router_id traefik-02
    enable_script_security
    script_user root
}

vrrp_script chk_traefik {
    script "/usr/local/bin/check_traefik.sh"
    interval 2
    timeout 2
    weight -20
    fall 2
    rise 2
}

vrrp_instance VI_TRAEFIK {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass Tr@ef1kHAP@ss
    }

    unicast_src_ip 192.168.10.22
    unicast_peer {
        192.168.10.21
    }

    virtual_ipaddress {
        192.168.10.100/24 dev eth0 label eth0:vip
    }

    track_script {
        chk_traefik
    }
}
```

#### 6. Запуск и верификация переключения при сбое (Failover Test)
```bash
# Запуск служб на обоих узлах
sudo systemctl enable --now traefik keepalived

# Проверка наличия VIP на traefik-01 (MASTER)
ip addr show dev eth0
# → inet 192.168.10.21/24 brd 192.168.10.255 scope global eth0
# → inet 192.168.10.100/24 scope global secondary eth0:vip

# Эмуляция сбоя: плавная остановка Traefik на traefik-01
sudo systemctl stop traefik

# Проверка логов Keepalived на traefik-01
sudo journalctl -u keepalived -n 5 --no-pager
# → Keepalived_vrrp[1420]: Script `chk_traefik` failed with status 1
# → Keepalived_vrrp[1420]: VRRP_Instance(VI_TRAEFIK) Changing effective priority from 101 to 81
# → Keepalived_vrrp[1420]: (VI_TRAEFIK) Entering BACKUP STATE
# → Keepalived_vrrp[1420]: (VI_TRAEFIK) removing VIPs.

# Проверка миграции VIP на traefik-02
ip addr show dev eth0
# → inet 192.168.10.100/24 scope global secondary eth0:vip
```

---

### Сценарий 2: Горизонтальный Active-Active кластер за HAProxy (L4) с PROXY Protocol v2

Для максимальной производительности входящий трафик распределяется парой балансировщиков HAProxy (работающих на 4 уровне OSI в режиме TCP passthrough), которые передают соединения на пул серверов Traefik с сохранением клиентских IP-адресов через PROXY Protocol v2.

```
                           Клиенты
                              │
                              ▼
                   HAProxy L4 Cluster (VIP)
                   (mode tcp, send-proxy-v2)
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
    ┌─────────────────────┐       ┌─────────────────────┐
    │  Traefik 01         │       │  Traefik 02         │
    │  proxyProtocol      │       │  proxyProtocol      │
    │  trustedIPs: L4 LB  │       │  trustedIPs: L4 LB  │
    └─────────────────────┘       └─────────────────────┘
```

#### 1. Конфигурация HAProxy (`/etc/haproxy/haproxy.cfg`)
```haproxy
global
    log /dev/log local0
    maxconn 100000
    user haproxy
    group haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners

defaults
    log     global
    mode    tcp
    option  tcplog
    timeout connect 5s
    timeout client  50s
    timeout server  50s

frontend fe_https_in
    bind 192.168.10.100:443
    mode tcp
    default_backend be_traefik_cluster_https

backend be_traefik_cluster_https
    mode tcp
    balance roundrobin
    # Проверка доступности инстансов по HTTP /ping эндпоинту
    option httpchk GET /ping
    http-check expect status 200
    default-server inter 2s fall 2 rise 2 send-proxy-v2

    server traefik-01 192.168.10.21:443 check port 8082
    server traefik-02 192.168.10.22:443 check port 8082
```

#### 2. Конфигурация входной точки Traefik (`/etc/traefik/traefik.yml`)
Traefik обязан доверять заголовку PROXY Protocol исключительно от адресов вышестоящих серверов HAProxy:

```yaml
entryPoints:
  ping:
    address: ":8082"
  websecure:
    address: ":443"
    proxyProtocol:
      trustedIPs:
        - "127.0.0.1/32"
        - "192.168.10.11/32" # HAProxy 01
        - "192.168.10.12/32" # HAProxy 02
    forwardedHeaders:
      trustedIPs:
        - "127.0.0.1/32"
        - "192.168.10.11/32"
        - "192.168.10.12/32"
```

---

### Сценарий 3: Active-Active кластер на базе BGP Anycast и ECMP (Data Center Edge)

В крупных локальных ЦОД балансировка между серверами Traefik реализуется на уровне сетевой фабрики без единой точки отказа (SPOF). Каждый сервер Traefik анонсирует общий Anycast IP маршрутизаторам стойки (Top-of-Rack, ToR) через демон FRRouting (FRR).

```
                   Сетевой коммутатор ToR (ECMP)
                   (BGP Peer, AS 65000)
                              │
               ┌──────────────┴──────────────┐
       BGP     │                             │ BGP
    10.10.10.1 │                             │ 10.10.10.1
               ▼                             ▼
    ┌─────────────────────┐       ┌─────────────────────┐
    │  Host traefik-01    │       │  Host traefik-02    │
    │  FRRouting (BGP)    │       │  FRRouting (BGP)    │
    │  lo: 10.10.10.1/32  │       │  lo: 10.10.10.1/32  │
    │  Traefik Ingress    │       │  Traefik Ingress    │
    └─────────────────────┘       └─────────────────────┘
```

#### 1. Настройка сетевого интерфейса Dummy/Loopback
На каждом сервере Traefik настраивается Anycast IP:

```bash
# Создание постоянного интерфейса dummy0 для Anycast IP
sudo tee /etc/systemd/network/10-dummy0.netdev << 'EOF'
[NetDev]
Name=dummy0
Kind=dummy
EOF

sudo tee /etc/systemd/network/20-dummy0.network << 'EOF'
[Match]
Name=dummy0

[Network]
Address=10.10.10.1/32
EOF

sudo systemctl restart systemd-networkd
```

#### 2. Настройка демона FRRouting (`/etc/frr/frr.conf`)
Сервер анонсирует маршрут `10.10.10.1/32` на ToR-коммутатор (IP `192.168.10.1`):

```frr
frr version 9.1
frr defaults traditional
hostname traefik-01
log syslog informational
no ip forwarding
no ipv6 forwarding
service integrated-vtysh-config

router bgp 65001
 bgp router-id 192.168.10.21
 no bgp ebgp-requires-policy
 neighbor 192.168.10.1 remote-as 65000
 neighbor 192.168.10.1 description "ToR-Switch-01"
 
 address-family ipv4 unicast
  network 10.10.10.1/32
  neighbor 192.168.10.1 activate
 exit-address-family
```

#### 3. BGP Healthcheck демон (отзыв маршрута при отказе Traefik)
Служба мониторинга отзывает анонс маршрута, если Traefik не отвечает на `/ping`:

```bash
sudo tee /usr/local/bin/bgp-traefik-check.sh << 'EOF'
#!/usr/bin/env bash
# Периодическая проверка готовности Traefik
if curl --silent --fail --max-time 1 http://127.0.0.1:8082/ping >/dev/null 2>&1; then
    # Traefik здоров: анонсируем маршрут в BGP
    vtysh -c "configure terminal" -c "router bgp 65001" -c "address-family ipv4 unicast" -c "network 10.10.10.1/32" >/dev/null 2>&1 || true
else
    # Traefik не отвечает или в drain: отзываем маршрут
    vtysh -c "configure terminal" -c "router bgp 65001" -c "address-family ipv4 unicast" -c "no network 10.10.10.1/32" >/dev/null 2>&1 || true
fi
EOF

sudo chmod +x /usr/local/bin/bgp-traefik-check.sh
```

---

### Сценарий 4: Оркестрация Zero-Downtime Rolling Update

Поэтапное обновление бинарного файла или конфигурации Traefik на группе серверов с гарантией непрерывности обработки трафика.

#### Порядок выполнения шагов:
1. Исключение целевого узла из пула балансировщика (или перевод в drain).
2. Ожидание интервала `requestAcceptGraceTimeout` (прекращение приема новых подключений).
3. Ожидание завершения активных клиентских соединений (`graceTimeOut`).
4. Остановка службы, обновление бинарника/файлов, запуск новой версии.
5. Ожидание ответа HTTP 200 на `/ping`.
6. Возврат узла в пул балансировщика.
7. Переход к следующему узлу кластера.

#### Скрипт автоматизации обновления (`traefik-rolling-update.sh`)
```bash
#!/usr/bin/env bash
set -euo pipefail

NODES=("192.168.10.21" "192.168.10.22")
HAPROXY_SOCKET="/run/haproxy/admin.sock"
BACKEND_NAME="be_traefik_cluster_https"

echo "=== Запуск Rolling Update кластера Traefik ==="

for NODE in "${NODES[@]}"; do
    echo "--- Обработка узла ${NODE} ---"

    # 1. Вывод узла из пула HAProxy через runtime сокет
    echo "disable server ${BACKEND_NAME}/${NODE}" | sudo socat stdio "${HAPROXY_SOCKET}"
    echo "Узел ${NODE} переведен в MAINTENANCE. Ожидание дренажа соединений (35 сек)..."

    # 2. Пауза на время requestAcceptGraceTimeout (5s) + graceTimeOut (30s)
    sleep 35

    # 3. Остановка службы Traefik на целевом узле
    ssh -o StrictHostKeyChecking=no "admin@${NODE}" "sudo systemctl stop traefik"

    # 4. Выполнение обновления (установка нового бинарника / замена конфигурации)
    ssh -o StrictHostKeyChecking=no "admin@${NODE}" "sudo apt-get install --only-upgrade traefik -y || true"

    # 5. Запуск обновленного сервиса
    ssh -o StrictHostKeyChecking=no "admin@${NODE}" "sudo systemctl start traefik"

    # 6. Ожидание прохождения проверки здоровья
    echo "Ожидание готовности /ping на узле ${NODE}..."
    RETRIES=0
    MAX_RETRIES=15
    until ssh -o StrictHostKeyChecking=no "admin@${NODE}" "curl -s -f http://127.0.0.1:8082/ping | grep -q 'OK'"; do
        sleep 2
        RETRIES=$((RETRIES + 1))
        if [[ ${RETRIES} -ge ${MAX_RETRIES} ]]; then
            echo "ОШИБКА: Узел ${NODE} не прошел проверку здоровья за отведенное время!"
            exit 1
        fi
    done

    # 7. Возврат узла в балансировку
    echo "enable server ${BACKEND_NAME}/${NODE}" | sudo socat stdio "${HAPROXY_SOCKET}"
    echo "Узел ${NODE} успешно обновлен и вернулся в строй."
done

echo "=== Rolling Update успешно завершен для всех узлов ==="
```

---

### Сценарий 5: Централизованное хранилище сертификатов без ACME-конфликтов

Для исключения гонок записи в `acme.json` выпуск wildcard-сертификатов делегируется автономному процессу Certbot на выделенном хосте управления, а сертификаты синхронизируются на узлы Traefik.

#### 1. Выпуск сертификата на хосте управления
```bash
sudo certbot certonly \
  --manual \
  --preferred-challenges dns \
  -d "*.example.com" \
  -d "example.com" \
  --config-dir /etc/letsencrypt
```

#### 2. Распространение сертификатов на ноды Traefik
Синхронизация через `rsync` с последующим сохранением прав доступа:

```bash
rsync -avzL /etc/letsencrypt/live/example.com/fullchain.pem admin@192.168.10.21:/etc/ssl/traefik/example.com.crt
rsync -avzL /etc/letsencrypt/live/example.com/privkey.pem admin@192.168.10.21:/etc/ssl/traefik/example.com.key
ssh admin@192.168.10.21 "sudo chmod 600 /etc/ssl/traefik/example.com.key && sudo chown -R traefik:traefik /etc/ssl/traefik"
```

#### 3. Динамическая конфигурация Traefik (`/etc/traefik/dynamic/tls-certificates.yml`)
```yaml
tls:
  certificates:
    - certFile: "/etc/ssl/traefik/example.com.crt"
      keyFile: "/etc/ssl/traefik/example.com.key"
      stores:
        - default

  stores:
    default:
      defaultCertificate:
        certFile: "/etc/ssl/traefik/example.com.crt"
        keyFile: "/etc/ssl/traefik/example.com.key"
```
Благодаря опции `providers.file.watch: true`, Traefik мгновенно применяет обновленный сертификат без сброса активных соединений и перезапуска процесса.

---

### Сценарий 6: Capacity Planning, сайзинг и системный тюнинг Linux ядра

#### Формула расчета пропускной способности (Throughput)
Для Go-рантайма на современной архитектуре x86_64 с аппаратным ускорением AES-NI эмпирическая формула предельного RPS на один узел составляет:

$$\text{RPS}_{\text{instance}} = \frac{N_{\text{vCPU}} \times 2200}{1 + \left(\frac{T_{\text{latency\_ms}}}{100}\right)}$$

Где:
- $N_{\text{vCPU}}$ — количество физических ядер / vCPU, выделенных процессору Traefik.
- $T_{\text{latency\_ms}}$ — среднее время задержки ответа бэкенда.
- Константа $2200$ — базовое количество операций диспетчеризации горутин на ядро.

*Пример расчета:*
- Сервер с 4 vCPU, средняя латентность приложения 30 мс:
  $$\text{RPS} \approx \frac{4 \times 2200}{1 + 0.3} = \frac{8800}{1.3} \approx 6769 \text{ req/s}$$
- Для нагрузки 20 000 req/s с учетом коэффициента запаса $N+1$ потребуется минимум 4 аналогичных сервера.

#### Память (RAM Sizing)
- Базовый RSS-размер процесса Traefik: ~40–60 МБ (зависит от объема динамических роутеров).
- Оверхед на активное открытое TCP-клиентское соединение: ~25–35 КБ (буферы сокетов Go netpoll).
- На 100 000 одновременных подключений (concurrent connections):
  $$\text{RAM} \approx 60\text{ MB} + (100\,000 \times 30\text{ KB}) \approx 3.06\text{ GB}$$

#### Системный тюнинг ядра Linux (`/etc/sysctl.d/99-traefik-ha.conf`)
Для предотвращения переполнения очереди соединений и исчерпания эфемерных портов при взаимодействии с бэкендами:

```ini
# Максимальный размер очереди входящих соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# Расширение пула эфемерных портов для исходящих соединений к бэкендам
net.ipv4.ip_local_port_range = 10240 65535

# Повторное использование TIME_WAIT сокетов для исходящих подключений
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# Увеличение буферов сокетов TCP
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Защита от SYN-flood атак
net.ipv4.tcp_syncookies = 1

# Максимальное число файловых дескрипторов в системе
fs.file-max = 2097152
```

Применение параметров:
```bash
sudo sysctl --system
```

#### Настройка лимитов дескрипторов в systemd (`/etc/systemd/system/traefik.service.d/limits.conf`)
```ini
[Service]
LimitNOFILE=1048576
LimitNPROC=512000
TasksMax=infinity
```

---

## Операции и команды

Сводная таблица инженерных команд обслуживания и диагностики HA-кластера Traefik:

| Операция | Команда | Назначение и ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка статуса Traefik** | `curl -i http://127.0.0.1:8082/ping` | Проверка готовности инстанса.<br>`# → HTTP/1.1 200 OK`<br>`# → OK` |
| **CLI проверка здоровья** | `traefik healthcheck --ping` | Проверка без curl через внутренний бинарник.<br>`# → код возврата 0 (OK)` |
| **Инспекция VIP-адреса** | `ip -brief addr show dev eth0` | Проверка наличия активного виртуального адреса на сетевой карте.<br>`# → eth0 UP 192.168.10.21/24 192.168.10.100/24` |
| **Проверка статуса Keepalived** | `systemctl status keepalived` | Проверка работы демона VRRP.<br>`# → Active: active (running)` |
| **Журнал событий VRRP** | `journalctl -u keepalived -n 20 --no-pager` | Отслеживание переходов состояний MASTER/BACKUP.<br>`# → (VI_TRAEFIK) Entering MASTER STATE` |
| **Сокеты и активные соединения** | `ss -s` | Сводная статистика сокетов Linux ядра.<br>`# → TCP: 14200 (estab 8540, closed 230, orphaned 0, timewait 120)` |
| **Проверка открытых FD процесса** | `ls -1 /proc/$(pgrep -o traefik)/fd \| wc -l` | Количество дескрипторов, удерживаемых процессом Traefik.<br>`# → 438` |
| **Инспекция лимита NOFILE** | `cat /proc/$(pgrep -o traefik)/limits \| grep 'open files'` | Проверка фактических ограничений процесса.<br>`# → Max open files 1048576 1048576 files` |
| **Метрики запросов по инстансу** | `curl -s http://127.0.0.1:8082/metrics \| grep 'traefik_entrypoint_requests_total'` | Проверка сбора метрик Prometheus на локальном инстансе.<br>`# → traefik_entrypoint_requests_total{code="200",entrypoint="websecure"} 84210` |
| **Принудительный дренаж узла** | `kill -15 $(pgrep -o traefik)` | Инициация процедуры мягкого вывода из строя (SIGTERM).<br>`# → Traefik переходит в 503 на /ping и завершается через graceTimeOut` |

---

## Устранение неисправностей

| Неисправность | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Keepalived Split-Brain (оба узла держат VIP)** | Межсетевой экран блокирует VRRP-пакеты (протокол IP 112) или несовпадение `virtual_router_id` / `auth_pass`. | `tcpdump -nn -i eth0 proto 112`<br>`arping -D -I eth0 -c 2 192.168.10.100` выявляет дублирование MAC-адресов. | 1. Разрешить протокол 112 в iptables: `iptables -A INPUT -p vrrp -j ACCEPT`.<br>2. Перевести Keepalived в режим strict unicast (`unicast_peer`).<br>3. Синхронизировать `auth_pass` в конфигурациях. |
| **Let's Encrypt Error 429 Too Many Certificates** | Множество инстансов независимо выпускают одинаковые сертификаты через ACME. | Логи Traefik:<br>`acme: error: 429 :: urn:ietf:params:acme:error:rateLimited` | Исключить локальный ACME. Настроить внешний централизованный выпуск (Certbot/Vault) и подключать сертификаты через `tls.certificates` файлового провайдера. |
| **Сброс сессий и авторизации пользователей** | Клиент попадает на разные инстансы Traefik, где sticky-cookie не согласованы. | В логах браузера частая смена значений session cookie; бэкенд возвращает 401 Unauthorized. | 1. Настроить на внешнем L4 балансировщике привязку по хэшу клиентского IP.<br>2. Перенести сессионные данные приложения в распределенный кэш (Redis/Valkey). |
| **Обрыв соединений (`502` / `RST`) при rolling update** | Внешний LB отправляет трафик на узел, который уже начал процедуру остановки, но еще не исключен из пула. | В логах клиентов всплеск `connection reset by peer` точно в момент перезапуска Traefik. | 1. Увеличить `lifeCycle.requestAcceptGraceTimeout` до 5–10 секунд.<br>2. Убедиться, что внешний балансировщик опрашивает `/ping` с коротким интервалом (`interval 1s`, `fall 2`). |
| **Исчерпание портов (`cannot assign requested address`)** | Дефицит локальных TCP-портов при высоком RPS соединений от Traefik к бэкендам. | В логах Traefik:<br>`dial tcp 10.0.0.5:8080: connect: cannot assign requested address` | 1. Расширить `net.ipv4.ip_local_port_range = 10240 65535`.<br>2. Включить `net.ipv4.tcp_tw_reuse = 1`.<br>3. Настроить HTTP keep-alive между Traefik и серверами приложений (`serversTransport.maxIdleConnsPerHost`). |
| **Повреждение хранилища `acme.json`** | Файл `acme.json` смонтирован с сетевого хранилища (NFS/CIFS) нескольким узлам. | В логах Traefik:<br>`unable to parse acme.json: unexpected end of JSON input` | Немедленно размонтировать NFS. Хранить `acme.json` исключительно на локальной файловой системе узла (ext4, XFS). |
| **Ошибки PROXY Protocol v2 (сброс TCP / HTTP 400)** | Traefik получает бинарный заголовок PROXY v2 от адреса, не входящего в `trustedIPs`. | В логах Traefik:<br>`command is not a PROXY command` или мгновенный сброс TCP-хэндшейка. | Проверить IP-адреса балансировщиков L4 и внести их в секцию `entryPoints.<name>.proxyProtocol.trustedIPs`. |
| **BGP Anycast Route Blackholing** | Узел Traefik упал или находится в дренаже, но BGP-демон продолжает анонсировать IP ToR-коммутатору. | Часть клиентского трафика попадает в «черную дыру» (пакеты приходят на хост без слушающего сокета). | Настроить скрипт проверки жизнеспособности (healthcheck daemon), отзывающий BGP-анонс `no network <IP>` при отсутствии HTTP 200 от `/ping`. |

---

## Лучшие практики

### 1. Архитектурный SRE-стандарт резервирования $N+1$ / $N+2$
- В production-среде запрещено использование одиночного инстанса Traefik. Минимальная конфигурация — 2 узла в режиме Active-Passive или Active-Active.
- Расчет емкости кластера должен учитывать падение как минимум одного узла без деградации времени отклика (SLA p99 latency) для пользователей.

### 2. Мониторинг, алерты и SLO
Рекомендуемые правила алертинга для Prometheus Alertmanager:

```yaml
groups:
  - name: traefik_ha_alerts
    rules:
      - alert: TraefikInstanceDown
        expr: up{job="traefik"} == 0
        for: 15s
        labels:
          severity: critical
        annotations:
          summary: "Экземпляр Traefik недоступен (узел {{ $labels.instance }})"
          description: "Эндпоинт метрик не отвечает более 15 секунд. Возможен отказ процесса."

      - alert: TraefikHigh5xxRate
        expr: sum(rate(traefik_entrypoint_requests_total{code=~"5.."}[2m])) by (entrypoint) 
              / sum(rate(traefik_entrypoint_requests_total[2m])) by (entrypoint) * 100 > 1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Высокая доля ошибок 5xx на точке входа {{ $labels.entrypoint }}"
          description: "Доля ошибок 5xx превышает 1% за последние 2 минуты."

      - alert: TraefikOpenConnectionsCritical
        expr: traefik_open_connections > 50000
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Критическое количество открытых соединений на {{ $labels.instance }}"
          description: "Число соединений приблизилось к порогу дескрипторов."
```

### 3. Изоляция управляющего контура
- Никогда не выставляйте эндпоинты `/ping`, `/metrics` и Traefik Dashboard на публичные IP-адреса и порты `80`/`443`.
- Назначайте для них отдельный изолированный `entryPoint` на `127.0.0.1` или внутренний management VLAN (`10.x.x.x`).

### 4. Конфигурация таймаутов Graceful Shutdown
- Обязательно настраивайте `requestAcceptGraceTimeout` (минимум 3–5 секунд), чтобы компенсировать задержку распространения информации об исключении узла во внешних балансировщиках и DNS.
- Значение `graceTimeOut` должно быть не меньше самого долгого ожидаемого клиентского HTTP-запроса (обычно 30–60 секунд).

---

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — архитектура entrypoints, провайдеров и конвейера обработки запросов.
- [Traefik на bare-metal](./traefik-bare-metal.md) — развертывание под управлением Linux systemd, тюнинг дескрипторов и запуск.
- [Graceful Shutdown и Zero-Downtime Deploy в Traefik](./traefik-graceful-shutdown.md) — детальный разбор жизненного цикла остановки, системных сигналов и таймаутов.
- [Health Checks в Traefik](./traefik-health-checks.md) — активные и пассивные проверки бэкенд-сервисов, gRPC и failover.
- [Аварийное восстановление Traefik](./traefik-disaster-recovery.md) — стратегии резервного копирования, восстановление при сбоях и изоляция Split-Brain.
- [Провайдеры конфигурации](./traefik-providers-advanced.md) — интеграция с Consul Catalog, Nomad и локальными файлами.
- [KV-хранилища в Traefik](./traefik-providers-kv-stores.md) — настройка динамической конфигурации через Consul, etcd и Redis.
- [Наблюдаемость Traefik](./traefik-observability.md) — метрики Prometheus, OpenTelemetry трейсинг и журналы доступа.
- [Keepalived — обзор и настройка высокой доступности (HA)](../../Networking/ServicesAndTools/keepalived_overview.md) — глубокое руководство по настройке VRRP и плавающего IP на серверах Linux.
- [Паттерн keepalived (OpenSearch)](../../ELK_Stack/OpenSearch/opensearch_high_availability_keepalived.md) — практический опыт построения отказоустойчивых кластеров с VIP.
- [HAProxy: архитектура и балансировка](../../WebServers/haproxy_overview.md) — развертывание высокопроизводительных L4/L7 балансировщиков.
- [Динамическая маршрутизация BGP](../../Networking/Protocols/bgp.md) — основы построения Anycast и отказоустойчивых сетей.
- [Развертывание в традиционной инфраструктуре](../../CI-CD/Deployment_Strategies/traditional_infrastructure.md) — паттерны автоматизации bare-metal серверов.
- [Rolling Update — поэтапное обновление](../../CI-CD/Deployment_Strategies/rolling_update.md) — общие принципы и практики zero-downtime развертывания.