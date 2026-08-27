## Определения

- **SD-WAN (Software-Defined Wide Area Network)**: Подход к управлению WAN-связностью, при котором маршрутизация трафика централизованно управляется через SDN-контроллер. Позволяет использовать混合ные link types (MPLS, broadband, LTE/5G) и автоматически выбирать оптимальный путь для каждого приложения.
- **WAN Edge Router**: Устройство (physical или virtual) на сайте клиента, выполняющее функции маршрутизации, инкапсуляции и policy enforcement. Примеры: Cisco Viptela vEdge, VMware VeloCloud Edge, Fortinet FortiGate.
- **Orchestrator (SD-WAN Controller)**: Централизованная платформа управления, определяющая маршруты, policies и overlay tunnels для всех WAN Edge routers. Примеры: Cisco vManage, VMware VeloCloud Orchestrator, Fortinet Manager.
- **Overlay Tunnel**: Виртуальный туннель (IPsec/GRE) между WAN Edge routers, поверх которого маршрутизируется пользовательский трафик. Автоматически создается и поддерживается.
- **Underlay**: Физическая WAN-инфраструктура (MPLS, Internet, LTE). SD-WAN не зависит от конкретного underlay.
- **Application-Aware Routing**: Механизм, при котором SD-WAN классифицирует приложения (по IP/port, DPI, DNS) и маршрутизирует их через оптимальный link на основе SLA (latency, jitter, packet loss).
- **SASE (Secure Access Service Edge)**: Архитектура, объединяющая SD-WAN с cloud-based security (SWG, CASB, ZTNA, FWaaS). Позволяет обеспечить безопасность для remote users без backhauling traffic.
- **ZTNA (Zero Trust Network Access)**: Подход к безопасности, при котором доступ к ресурсам предоставляется на основе identity и context, а не network location. Используется в SASE.
- **Direct Internet Access (DIA)**: Режим, при котором интернет-трафик маршрутизируется напрямую из сайта (без backhauling через HQ). Снижает latency для cloud apps.
- **Brownfield vs Greenfield SD-WAN**: Brownfield — миграция существующей WAN с MPLS на SD-WAN. Greenfield — новый deployment без legacy infrastructure.

---

## Основные концепции

### Архитектура SD-WAN

```
┌─────────────────────────────────────────────────────────────────┐
│                     SD-WAN Orchestrator                          │
│  (Cisco vManage, VMware VCO, Fortinet Manager)                  │
│  → Централизованное управление политиками                      │
│  → Мониторинг и analytics                                       │
│  → Автоматическое развертывание overlay tunnels                │
├─────────────────────────────────────────────────────────────────┤
│                        Control Plane                             │
│  → Белый список control connections (DTLS/TLS)                 │
│  → Протоколы: OMP (Cisco Viptela), BFD (keepalive)             │
├─────────────────────────────────────────────────────────────────┤
│                        Data Plane (Overlay)                     │
│  ┌──────────┐  IPsec Tunnel  ┌──────────┐                      │
│  │ Site A   │◄──────────────►│ Site B   │                      │
│  │ vEdge    │  (MPLS/Internet)│ vEdge    │                      │
│  └──────────┘                 └──────────┘                      │
│       │                          │                              │
│       ▼                          ▼                              │
│   MPLS + Internet + LTE (混合ные links)                         │
└─────────────────────────────────────────────────────────────────┘
```

### SD-WAN vs传统 WAN

| Критерий | Traditional WAN (MPLS) | SD-WAN |
| :--- | :--- | :--- |
| **Управление** | CLI на каждом device | Централизованный orchestrator |
| **Overlay** | MPLS L3VPN | IPsec tunnels over any link |
| **Link types** | Только MPLS (или专线) | MPLS + Internet + LTE/5G |
| **Application routing** | По IP/.prefix (static policy) | По application identity (dynamic SLA) |
| **Security** | Backhauling через HQ/DC | DIA + cloud security (SASE) |
| **Cost** | Высокая (MPLS circuits) | Низкая (broadband + LTE) |
| **Provisioning** | Недели/месяцы ( circuits) | Часы/дни (zero-touch) |
| **Visibility** | Ограниченная (SNMP, NetFlow) | Полная (DPI, app analytics) |
| **Resilience** | Manual failover | Automatic failover (BFD, SLA probes) |

### Application-Aware Routing

| Application Class | SLA Requirements | Preferred Link | Fallback |
| :--- | :--- | :--- | :--- |
| **Voice/Video (RTP)** | Latency <50ms, Jitter <30ms, Loss <1% | MPLS (low latency) | Internet (with QoS) |
| **Business Critical (ERP, CRM)** | Latency <100ms, Loss <0.1% | MPLS or DIA | LTE |
| **General Internet (SaaS)** | Latency <200ms | DIA (Direct Internet Access) | MPLS backhaul |
| **Bulk Transfer (backup)** | Best effort | Cheapest link (Broadband) | LTE |

### Failover mechanisms

| Механизм | Описание | Recovery time |
| :--- | :--- | :--- |
| **BFD (Bidirectional Forwarding Detection)** | Hardware-accelerated liveness check (300ms intervals) | <1 sec |
| **SLA Probes** | Application-level health checks (HTTP, DNS, VoIP) | 5-10 sec |
| **Dynamic Path Selection** | Real-time SLA monitoring → automatic link switching | <5 sec |
| **IPsec SA Rekeying** | Автоматическое переключение при потере tunnel | <1 sec |

### SASE (Secure Access Service Edge)

```
Traditional SD-WAN:
  User → Site (SD-WAN Edge) → DC (Security stack) → Internet

SASE (SD-WAN + Cloud Security):
  User → SD-WAN Edge → Cloud Security (SWG/CASB/ZTNA) → Internet
       ↓
  Remote User → ZTNA Agent → Cloud Security → Application

SASE Components:
  - SD-WAN (WAN connectivity)
  - SWG (Secure Web Gateway)
  - CASB (Cloud Access Security Broker)
  - ZTNA (Zero Trust Network Access)
  - FWaaS (Firewall as a Service)
  - DLP (Data Loss Prevention)
```

---

## Практические сценарии

### Сценарий 1: Cisco Viptela (vEdge) - базовая конфигурация

```cisco
! Настройка WAN Edge router
system
  host-name site01-edger1
  system-ip 10.0.0.1
  site-id 100
  organization-name "MY-COMPANY"
  vbond 203.0.113.10

! Настройка интерфейсов
interface ge0/0
  ip address 10.0.1.1/24
  tunnel-interface
    encapsulation ipsec
    color biz-internet
    restrict
    no-border
  !
  ip dhcp-client

interface ge0/1
  ip address 192.168.1.1/24
  tunnel-interface
    encapsulation ipsec
    color mpls
  !
  ip dhcp-client

! VPN (VRF) definition
vpn 0
  interface ge0/0
    ip address dhcp
    ip dhcp-client gateway default
  !
  interface ge0/1
    ip address dhcp
    ip dhcp-client gateway default

vpn 512
  interface eth0
    ip address 10.0.0.1/24
    ip dhcp-client

! OMP (Overlay Management Protocol)
omp
  no shutdown
  send-path-limit 4
  bestpath region sub-region

! Settings
certificate ompliance
  organization "MY-COMPANY"

! Verification
show omp peers
show omp routes
show tunnel statistics
show bfd sessions
show app-route statistics
```

### Сценарий 2: VMware VeloCloud Edge

```bash
# VeloCloud Edge - zero-touch provisioning
# 1. Edge подключается к VeloCloud Orchestrator (VCO)
# 2. Автоматически скачивает конфигурацию
# 3. Создает IPsec tunnels

# Просмотр состояния Edge
show edge status
# → Edge: site01-edge
# → Status: Connected
# → WAN Links: ge0/0 (MPLS), ge0/1 (Internet), ge0/2 (LTE)
# → Tunnels: 2 active

# Просмотр overlay tunnels
show tunnel stats
# → Tunnel to site02-edge via biz-internet: UP, latency=12ms, loss=0%
# → Tunnel to site02-edge via mpls: UP, latency=8ms, loss=0%

# Просмотр application routing
show app-route statistics
# → Application: SIP (VoIP), Profile: realtime
# →   Path: mpls (primary), latency=8ms, jitter=5ms, loss=0%
# →   Failover: biz-internet (backup)

# Просмотр BFD sessions
show bfd peers
# → Peer: site02-edge, State: UP, Mode: echo, Tx=300ms
```

### Сценарий 3: Fortinet SD-WAN

```bash
# FortiGate - SD-WAN configuration
# 1. Настройка SD-WAN zones
config system sdwan
    set status enable
    config members
        edit 1
            set interface "wan1"
            set gateway 10.0.1.1
            set source 10.0.0.1
        next
        edit 2
            set interface "wan2"
            set gateway 192.168.1.1
            set source 10.0.0.1
        next
    end
    config health-check
        edit "dns-health"
            set server "8.8.8.8"
            set protocol dns
            set interval 1000
            set probe-timeout 1000
            set threshold 5
        next
    end
end

# 2. SD-WAN rules (application-aware routing)
config firewall policy
    edit 1
        set name "voice-mpls"
        set src "all"
        set dst "all"
        set service "SIP" "RTP"
        set sdwan-zone "mpls"
        set action accept
    next
    edit 2
        set name "internet-dia"
        set src "all"
        set dst "all"
        set service "HTTP" "HTTPS"
        set sdwan-zone "internet"
        set action accept
    next
end

# 3. IPsec tunnel (auto-provisioned)
config vpn ipsec phase1-interface
    edit "overlay-to-site02"
        set remote-gw 203.0.113.20
        set psksecret "shared-secret"
        set ike-version 2
    next
end

# Verification
diagnose sys sdwan health-check
diagnose sys sdwan tunnel-stats
diagnose vpn ike gateway list
```

### Сценарий 4: Мониторинг SD-WAN (API)

```python
# Пример: мониторинг через Cisco vManage API
import requests

vmanage_url = "https://vmanage.example.com"
username = "admin"
password = "secret"

# Аутентификация
auth = requests.post(
    f"{vmanage_url}/j/security/login",
    data={"j_username": username, "j_password": password}
)
cookies = {"JSESSIONID": auth.cookies["JSESSIONID"]}

# Получение списка devices
devices = requests.get(
    f"{vmanage_url}/dataservice/device",
    cookies=cookies
).json()

for device in devices["data"]:
    print(f"Device: {device['host-name']}, Status: {device['reachability']}")

# Получение SD-WAN statistics
stats = requests.get(
    f"{vmanage_url}/dataservice/device/tunnel/statistics",
    cookies=cookies
).json()

for tunnel in stats["data"]:
    print(f"Tunnel: {tunnel['source-system-ip']} → {tunnel['dest-system-ip']}")
    print(f"  Latency: {tunnel['latency']}ms, Loss: {tunnel['loss']}%")
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Tunnel down** | No overlay connectivity between sites | `show tunnel stats` - tunnel down | Проверить underlay connectivity; проверить IPsec SA; проверить防火айр (UDP 500/4500) |
| **Application not meeting SLA** | VoIP quality poor, video choppy | `show app-route statistics` - high latency/loss | Переключить на другой link; увеличить priority для realtime traffic |
| **Control connection lost** | Edge not receiving policies from orchestrator | `show omp peers` - no peers | Проверить DTLS connection to vManage; проверить certificates |
| **BFD flapping** | Frequent failovers, traffic drops | `show bfd sessions` - flapping state | Проверить link quality; увеличить BFD interval; проверить MTU |
| **Zero-touch provisioning failure** | Edge not registering with orchestrator | `show system status` - not registered | Проверить DNS resolution; проверить serial number; проверить vManage whitelist |
| **IPsec rekey failure** | Tunnel drops periodically | `show crypto isakmp sa` - rekey failed | Проверить NTP synchronization; проверить IKE version compatibility |

### Команды отладки

```bash
# Cisco Viptela
show omp peers                      # OMP peers status
show omp routes                     # OMP routes (overlay)
show tunnel statistics              # Tunnel health
show bfd sessions                   # BFD (liveness check)
show app-route statistics           # Application SLA
show certificate installed          # Certificates status

# VMware VeloCloud
show edge status                    # Edge status
show tunnel stats                   # Tunnel health
show app-route statistics           # Application routing
show interface usage                # Interface utilization

# Fortinet FortiGate
diagnose sys sdwan health-check     # SD-WAN health check
diagnose sys sdwan tunnel-stats     # Tunnel statistics
diagnose vpn ike gateway list       # IKE gateways
diagnose net link interface list    # Interface status
```

---

## Дополнительная информация

**Производственные рекомендации:**
- Начинайте с brownfield deployment (добавление SD-WAN к existing MPLS).
- Используйте application-aware routing для realtime traffic (VoIP, video).
- Внедряйте SASE для remote users (замена VPN backhauling).
- Мониторьте SLA metrics для proactive failover.
- Используйте zero-touch provisioning для ускорения deployment.

**Связанные темы:**
- **[SDN Overview](./sdn_overview.md)** — SD-WAN как application SDN.
- **[Zero Trust](./sdn_overview.md#ограничения-и-угрозы)** — Zero Trust в SASE.
- **[Network Automation](./network_automation.md)** — автоматизация SD-WAN deployment.
- **[IPsec](../../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md)** — IPsec tunnels в SD-WAN.
- **[NetFlow/IPFIX](./netflow.md)** — мониторинг SD-WAN traffic.
