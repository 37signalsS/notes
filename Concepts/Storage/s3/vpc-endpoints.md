# S3: изоляция трафика и сетевая безопасность RGW

**Актуально для:** S3 API, AWS CLI 2.x, Ceph RGW (Squid 19.x / Tentacle 20.x)

---

## 1. Определения

**Private access** — доступ к RGW без выхода в публичный интернет. В on-prem среде реализуется через изоляцию сети (VLAN, firewall, internal DNS).

**Data exfiltration** — несанкционированная утечка данных из S3 bucket в публичный интернет. Private access patterns предотвращают exfiltration даже при компрометации credentials.

**VLAN segmentation** — разделение сети на изолированные сегменты (VLAN) для ограничения broadcast domain и контроля трафика.

**Firewall rules** — правила фильтрации трафика на сетевом уровне (iptables/nftables, hardware firewall).

**Internal DNS** — DNS-резолвинг endpoint'ов через внутренние DNS серверы. Критично для изоляции трафика.

**HTTPS/TLS** — шифрование трафика между клиентом и RGW. Обязательно для production.

**Network topology documentation** — документация сети: VLAN, subnet, firewall rules, DNS zones, RGW endpoints.

**Subnet isolation** — размещение RGW daemons в отдельном subnet с контролируемым доступом.

**Zero-trust network** — модель, при которой каждый запрос к RGW аутентифицируется и авторизуется, независимо от источника в сети.

---

## 2. Базовые концепции

### 2.1 Почему network isolation критичен

Public access к RGW — частая причина утечек данных. Даже если bucket не публичный, route через internet exposes traffic к:

- **Man-in-the-middle:** Перехват credentials/объектов при неверной проверке SSL.
- **Data exfiltration:** Злоумышленник с compromised credentials может выгрузить данные через internet.
- **Latency:** Public internet = higher latency, variable throughput.
- **Cost:** Data transfer out через internet = платно.

**Важно для self-hosted:** В отличие от AWS S3, где VPC endpoints предоставляются как managed service, в Ceph RGW network isolation строится на стандартных сетевых технологиях (VLAN, firewall, DNS). Это даёт полный контроль, но требует соответствующей экспертизы.

### 2.2 Архитектура private access

```
┌─────────────────────────────────────────────────────────┐
│                    Datacenter Network                    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │ Private     │    │ Private     │    │  RGW        │ │
│  │ Subnet      │    │ Subnet      │    │  Cluster    │ │
│  │ (app servers│    │ (bastion)   │    │             │ │
│  │  + K8s)     │    │             │    │             │ │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘ │
│         │                  │                  │         │
│         │   Firewall       │                  │         │
│         │   Rules          │                  │         │
│         └──────────────────┴──────────────────┘         │
│                                                         │
│  VLAN 100: App Servers                                  │
│  VLAN 200: RGW Cluster                                  │
│  VLAN 300: Bastion / Jump Host                          │
└─────────────────────────────────────────────────────────┘
```

**RGW endpoint** — это IP/URL вашего RGW кластера внутри дата-центра. Все запросы к RGW идут через внутреннюю сеть, минуя internet.

### 2.3 Сравнение подходов к изоляции

| Подход | Изоляция | Сложность | Latency | Use case |
|--------|----------|-----------|---------|----------|
| **VLAN + Firewall** | Высокая | Средняя | Низкая | Production on-prem |
| **Internal DNS + firewall** | Средняя | Низкая | Низкая | Small deployments |
| **VPN** | Высокая | Высокая | Средняя | Remote access |
| **Dedicated subnet** | Высокая | Средняя | Низкая | Large deployments |

### 2.4 Network layers для RGW traffic

RGW traffic проходит через несколько сетевых слоёв:

```
Client → [Application] → [TCP/IP] → [VLAN/Subnet] → [Firewall] → [RGW Interface] → [RGW Daemon] → [OSD Network]
```

Каждый слой может быть источником проблем:

| Layer | Типичные проблемы | Диагностика |
|-------|------------------|-------------|
| **Application** | DNS timeout, connection pool exhaustion | `nslookup`, `ss -tnp` |
| **TCP/IP** | MTU mismatch, packet loss | `ping -M do`, `traceroute` |
| **VLAN/Subnet** | Wrong VLAN, IP conflict | `ip addr show`, `vconfig` |
| **Firewall** | Rules mismatch, conntrack exhaustion | `iptables -L -n`, `conntrack -L` |
| **RGW Interface** | Interface down, IP change | `ip link show`, `ss -tnp` |
| **OSD Network** | Backend congestion, OSD down | `ceph osd perf`, `ceph health` |

---

## 3. Предварительные требования

Для настройки изоляции трафика и сетевой безопасности RGW необходимы:

- **Ceph RGW кластер** (Squid 19.x / Tentacle 20.x) с включённым S3 API (`rgw_enable_apis = s3`).
- **Сетевой доступ** до RGW endpoint — порт 7480 (HTTP) или 443 (HTTPS).
- **Firewall** — iptables/nftables или hardware firewall с поддержкой stateful inspection.
- **DNS-сервер** — BIND9, CoreDNS или внутренний DNS для resolve internal hostnames.
- **Управление VLAN** — поддержка VLAN на коммутаторах и сетевых интерфейсах серверов.
- **NTP-синхронизация** на всех клиентах и RGW узлах — разница времени > 15 минут вызывает `403 RequestTimeTooSkewed`.
- **Valid credentials** — Access Key ID / Secret Key с правами `s3:*` на целевые bucket'ы.

```bash
# Проверка доступности RGW endpoint
curl -s -o /dev/null -w "%{http_code}" http://rgw.internal:7480
# → 403 или 200 (любой HTTP-ответ, кроме timeout/connection refused)

# Проверка DNS resolution
nslookup rgw.internal
# → 192.168.200.10

# Проверка firewall rules
iptables -L -n | grep 7480
# или
nft list ruleset | grep 7480

# Проверка VLAN interface
ip addr show eth0.200
# → inet 192.168.200.10/24

# Проверка маршрута до RGW
ip route get 192.168.200.10
# → via 192.168.200.1 dev eth0.200

# Проверка MTU
ip link show eth0.200 | grep mtu
# → mtu 1500 (или 9000 для jumbo frames)
```

---

## 4. Практические сценарии

### 4.1 VLAN segmentation

```bash
# Создание VLAN для RGW traffic (Linux bridge)
ip link add link eth0 name eth0.200 type vlan id 200
ip addr add 192.168.200.1/24 dev eth0.200
ip link set eth0.200 up

# На RGW nodes:
ip link add link eth0 name eth0.200 type vlan id 200
ip addr add 192.168.200.10/24 dev eth0.200
ip link set eth0.200 up
```

**Рекомендация:** Выделите отдельный VLAN для RGW traffic. Это изолирует S3 трафик от остального дата-центра.

### 4.2 Firewall rules

```bash
# iptables: разрешить только доверенные сети к RGW
iptables -A INPUT -p tcp -s 10.0.0.0/8 --dport 7480 -j ACCEPT
iptables -A INPUT -p tcp -s 192.168.0.0/16 --dport 7480 -j ACCEPT
iptables -A INPUT -p tcp --dport 7480 -j DROP

# Или nftables:
nft add rule inet filter input ip saddr 10.0.0.0/8 tcp dport 7480 accept
nft add rule inet filter input ip saddr 192.168.0.0/16 tcp dport 7480 accept
nft add rule inet filter input tcp dport 7480 drop
```

### 4.3 Internal DNS

```bash
# /etc/hosts (простое решение)
192.168.200.10  rgw.internal rgw

# Или BIND9 zone:
$TTL 3600
@ IN SOA ns1.internal. admin.internal. (
  2025010101 3600 1800 604800 3600
)
@ IN NS ns1.internal.
rgw.internal. IN A 192.168.200.10
```

**Важно:** Используйте внутренний DNS вместо `--endpoint-url` с IP-адресом. Это позволяет менять IP RGW nodes без обновления конфигурации клиентов.

### 4.4 HTTPS/TLS для RGW endpoint

```bash
# Настройка SSL в Ceph RGW
ceph config set rgw rgw_ssl true
ceph config set rgw rgw_ssl_certificate /etc/ceph/ssl/rgw.crt
ceph config set rgw rgw_ssl_private_key /etc/ceph/ssl/rgw.key

# Или через cephadm:
ceph orch apply rgw myrgw \
  --placement="3 ceph-rgw1 ceph-rgw2 ceph-rgw3" \
  --ssl-certificate /etc/ceph/ssl/rgw.crt \
  --ssl-private-key /etc/ceph/ssl/rgw.key
```

### 4.5 AWS CLI конфигурация для внутреннего endpoint

```bash
# Настройка профиля для RGW
aws configure set default.s3.endpoint_url http://rgw.internal:7480 --profile rgw
aws configure set default.s3.addressing_style path --profile rgw
aws configure set default.s3.use_dualstack_endpoint false --profile rgw

# Проверка
aws s3 ls --profile rgw --endpoint-url http://rgw.internal:7480
```

### 4.6 Network topology documentation

```markdown
# RGW Network Topology

## VLANs
- VLAN 100: App Servers (10.0.100.0/24)
- VLAN 200: RGW Cluster (192.168.200.0/24)
- VLAN 300: Bastion (192.168.300.0/24)

## Firewall Rules
| Source | Destination | Port | Protocol | Action |
|--------|-------------|------|----------|--------|
| 10.0.100.0/24 | 192.168.200.0/24 | 7480 | TCP | ALLOW |
| 192.168.300.0/24 | 192.168.200.0/24 | 7480 | TCP | ALLOW |
| Any | 192.168.200.0/24 | 7480 | TCP | DENY |

## RGW Endpoints
- rgw1.internal: 192.168.200.10:7480
- rgw2.internal: 192.168.200.11:7480
- rgw3.internal: 192.168.200.12:7480

## DNS
- rgw.internal → 192.168.200.10 (round-robin)
```

### 4.7 Валидация конфигурации

После настройки network isolation выполните проверку:

```bash
# 1. Проверка firewall rules
iptables -L -n | grep 7480
# Должны быть правила ACCEPT для trusted networks и DROP для остального

# 2. Проверка DNS resolution
nslookup rgw.internal
dig rgw.internal +short

# 3. Проверка доступности из доверенной сети
curl -s -o /dev/null -w "%{http_code}" http://rgw.internal:7480
# → 200 или 403 (любой HTTP-ответ)

# 4. Проверка блокировки из недоверенной сети
# (выполните с хоста вне trusted subnet)
telnet rgw.internal 7480
# → Connection refused / timeout

# 5. Проверка TLS (если включён HTTPS)
openssl s_client -connect rgw.internal:7480 -servername rgw.internal
# → Должен показать валидный сертификат

# 6. Проверка metrics endpoint
curl -s http://rgw.internal:9283/metrics | head -5
# → Prometheus metrics text

# 7. Проверка network path
mtr --tcp --port 7480 rgw.internal
# → Все пакеты должны доходить до RGW без потерь
```

### 4.8 Edge Cases

#### 4.8.1 MTU mismatch на VLAN interface

**Симптомы:** Загрузка больших объектов (>1 MB) зависает или прерывается, маленькие объекты загружаются нормально.

**Причина:** MTU на VLAN interface (обычно 1500) не совпадает с MTU на upstream коммутаторе или физическом интерфейсе. Jumbo frames (9000) требуют согласования на всех hops пути.

**Решение:**
```bash
# Проверка MTU
ip link show eth0.200 | grep mtu
ip link show eth0 | grep mtu

# Установка MTU 9000 для jumbo frames (если поддержано everywhere)
ip link set eth0.200 mtu 9000

# Проверка фрагментации
ping -M do -s 8972 192.168.200.10
# → Должен пройти без фрагментации

# Если фрагментация нужна — проверьте PMTUD
sysctl net.ipv4.ip_no_pmtu_disc
# → 0 (PMTUD включён)
```

#### 4.8.2 Firewall conntrack exhaustion

**Симптомы:** При высокой нагрузке (>1000 req/s) firewall начинает отбрасывать established соединения, клиенты получают `Connection reset`.

**Причина:** С exhaustion entries в conntrack table. По умолчанию лимит ~65536 entries на connection tracking zone.

**Решение:**
```bash
# Проверка текущего использования
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max

# Увеличение лимита
sysctl -w net.netfilter.nf_conntrack_max=262144
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=7200

# Постоянное сохранение
echo "net.netfilter.nf_conntrack_max=262144" >> /etc/sysctl.d/99-conntrack.conf
```

#### 4.8.3 DNS round-robin с unhealthy endpoint

**Симптомы:** Клиенты иногда получают `Connection refused`, хотя RGW кластер работает. Проблема исчезает после повторной попытки.

**Причина:** Internal DNS возвращает round-robin список IP, включая упавший RGW node. Клиент подключается к unhealthy IP.

**Решение:**
```bash
# Используйте DNS с health check (CoreDNS, HAProxy, or keepalived)
# Или используйте load balancer с health checks перед RGW

# Проверка DNS records
dig rgw.internal +short
# → Должен возвращать только healthy IPs

# Проверка состояния RGW daemons
ceph orch ls --service_type rgw
ceph orch ps --service_name rgw.myrgw
```

#### 4.8.4 TLS certificate renewal

**Симптомы:** После истечения срока действия сертификата клиенты получают `SSL: CERTIFICATE_VERIFY_FAILED`.

**Решение:**
```bash
# Проверка срока действия
openssl s_client -connect rgw.internal:7480 -servername rgw.internal 2>/dev/null | openssl x509 -noout -dates

# Автоматический renewal через certbot (если используется Let's Encrypt)
certbot renew --post-hook "ceph config set rgw rgw_ssl_certificate /etc/letsencrypt/live/rgw.internal/fullchain.pem"

# Или hand-rolled скрипт для internal CA
```

#### 4.8.5 Network partition (split-brain)

**Симптомы:** Часть клиентов может достигать RGW, другая часть — нет. RGW nodes могут потерять связь друг с другом.

**Причина:** Network partition между VLAN или subnet'ами. Может быть вызвана сбоем коммутатора, ошибкой конфигурации VLAN, или кабельным проблемами.

**Решение:**
```bash
# Проверка связности между RGW nodes
ceph health detail
ceph tell rgw.myrgw.rzb.* ping

# Проверка network partition
ceph tell mon.* tree
ceph quorum_status

# Мониторинг в Prometheus
curl -s http://rgw:9283/metrics | grep rgw_connections
```

---

## 5. Troubleshooting

| Проблема | Причина | Диагностика | Решение |
|----------|---------|-------------|---------|
| `AccessDenied` из внутренней сети | Firewall rules блокируют порт | `iptables -L -n \| grep 7480` | Добавьте правило ALLOW |
| DNS не резолвит rgw.internal | Internal DNS не настроен | `nslookup rgw.internal` | Добавьте запись в DNS или /etc/hosts |
| Slow upload/download | NAT Gateway bottleneck или MTU mismatch | `mtr --tcp --port 7480 rgw.internal`, `ip link show` | Убедитесь, что RGW traffic не идёт через NAT; проверьте MTU |
| `403` из on-prem | Брандмауэр блокирует порт 443/7480 | `telnet rgw.internal 7480` | Откройте порт в firewall |
| SSL ошибки | Self-signed сертификат или expired | `openssl s_client -connect rgw.internal:7480` | Добавьте CA bundle или обновите сертификат |
| Connection reset при высокой нагрузке | Firewall conntrack exhaustion | `cat /proc/sys/net/netfilter/nf_conntrack_count` | Увеличьте `nf_conntrack_max` |
| MTU mismatch | Неправильный MTU на VLAN interface | `ping -M do -s 8972 192.168.200.10` | Установите согласованный MTU на всех interfaces |

---

## 6. Best Practices

1. **Выделите отдельный VLAN** для RGW traffic. Это базовая изоляция.
2. **Настройте firewall rules** — разрешайте только доверенные сети к порту 7480/443.
3. **Используйте internal DNS** вместо IP-адресов в конфигурации клиентов.
4. **Включите HTTPS/TLS** на всех RGW endpoints. Никогда не используйте HTTP в production.
5. **Document network topology** — ведите runbook с VLAN, firewall rules, DNS zones.
6. **Monitor firewall logs** — отслеживайте denied connections для выявления misconfigurations.
7. **Test access from outside** — убедитесь, что firewall действительно блокирует доступ извне.
8. **Use separate RGW endpoints** для разных окружений (prod, staging, dr).
9. **Regularly audit firewall rules** — удаляйте устаревшие правила.
10. **Combine с Object Lock** — network isolation + Object Lock = максимальная защита.
11. **Настройте MTU согласованно** — если используете jumbo frames, убедитесь что MTU совпадает на всех hops пути.
12. **Увеличьте conntrack limit** при высокой нагрузке — иначе firewall начнёт сбрасывать established соединения.
13. **Используйте DNS с health checks** — избегайте round-robin с unhealthy endpoints.
14. **Настройте автоматический renewal TLS** — сертификаты не должны истекать в production.
15. **Test network partition scenarios** — регулярно проверяйте поведение RGW при разрыве связности между nodes.

---

## 7. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: error codes и troubleshooting runbook](./error-codes.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [S3: disaster recovery runbook](./dr-runbook.md)
