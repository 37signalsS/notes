# Hardening сетевого стека Linux

## Определения

**Network Hardening** — процесс ужесточения конфигурации сетевого стека Linux путём отключения ненужных сервисов, ограничения параметров ядра (sysctl) и настройки файрвола для минимизации поверхности атаки и защиты от сетевых атак.

**Defense in Depth** — многоуровневая стратегия безопасности, когда каждый слой сети (IP, TCP, ICMP, Conntrack, Firewall) защищается независимо от других.

**Attack Surface Reduction** — минимизация доступных сервисов, протоколов и параметров, которые злоумышленник может использовать для reconnaissance или exploitation.

## Предусловия

- Понимание работы TCP/IP-стека Linux.
- Знание основ sysctl (`sysctl -w`, `/etc/sysctl.d/`).
- Права root для изменения параметров ядра.

## Основные концепции

### Уровни hardening

```
┌───────────────────────────────────────────────────────┐
│ Level 4: Firewall (nftables/iptables)                │
├───────────────────────────────────────────────────────┤
│ Level 3: Conntrack (timeouts, limits)                │
├───────────────────────────────────────────────────────┤
│ Level 2: TCP/UDP (syncookies, backlog, buffers)      │
├───────────────────────────────────────────────────────┤
│ Level 1: ICMP (redirects, floods, rate limiting)     │
├───────────────────────────────────────────────────────┤
│ Level 0: IP (rp_filter, source routing, forwarding)  │
└───────────────────────────────────────────────────────┘
```

## Практические сценарии

### Сценарий 1: Базовый набор sysctl для production-сервера

Минимальный hardening для любого Linux-сервера в продакшене. Сохраните в `/etc/sysctl.d/99-network-hardening.conf`.

```bash
# === /etc/sysctl.d/99-network-hardening.conf ===

# --- Level 0: IP ---
# Защита от IP Spoofing (Strict Reverse Path Filtering)
# 1 = Strict (отбрасывает пакеты с «неправильного» интерфейса)
# 2 = Loose (отбрасывает только при отсутствии маршрута)
# При асимметричной маршрутизации используйте 2
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# Запрет приёма Source Routed пакетов (защита от route manipulation)
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0

# Включение IP Forwarding ТОЛЬКО для роутеров/VPN/контейнеров
# На обычном сервере — 0
net.ipv4.ip_forward = 0

# --- Level 1: ICMP ---
# Запрет ICMP Redirect (защита от MITM и route manipulation)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0

# Запрет отправки ICMP Redirect (хост не является роутером)
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0

# Защита от ICMP Broadcast Flood / Smurf Attack
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Rate limiting ICMP Echo Request (мс между ответами)
# 100 = строгий (web), 1000 = мягкий (внутренний сервер)
net.ipv4.icmp_ratelimit = 100
# Маска: 880 = только Echo Request/Reply
net.ipv4.icmp_ratelimit_mask = 880

# Запрет ICMP隧нелирования (ограничение размера)
# Отключение ненужных ICMP-типов
net.ipv4.icmp_ignore_bogus_error_responses = 1

# --- Level 2: TCP ---
# Защита от SYN Flood
net.ipv4.tcp_syncookies = 1

# Увеличение backlog для SYN-пакетов
net.ipv4.tcp_max_syn_backlog = 8192

# Увеличение accept backlog
net.core.somaxconn = 65535

# Защита от TCP_RST атаки
net.ipv4.tcp_rfc1337 = 1

# Отключение_TIMESTAMP для снижения surface
net.ipv4.tcp_timestamps = 0

# --- Level 3: Conntrack ---
# Увеличение лимита таблицы conntrack
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144

# Сокращение таймаутов для освобождения ресурсов
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 15
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 60
```

**Применение:**
```bash
sudo sysctl --system
# Проверка:
sysctl net.ipv4.tcp_syncookies net.ipv4.conf.all.rp_filter net.core.somaxconn
```

### Сценарий 2: Сервер с включённым Forwarding (VPN/контейнеры)

Если сервер является роутером, VPN-шлюзом или хостом для контейнеров:

```bash
# === /etc/sysctl.d/99-network-hardening-forward.conf ===

# Forwarding ВКЛЮЧЁН
net.ipv4.ip_forward = 1

# Loose mode для асимметричной маршрутизации
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2

# Redirect НЕ отключаем (роутер должен отправлять Redirect)
# net.ipv4.conf.all.send_redirects = 0  ← НЕ ставим

# Остальные параметры — аналогично базовому набору
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 8192
net.core.somaxconn = 65535
```

### Сценарий 3: Защита от DDoS (SYN Flood)

```bash
# SYN cookies + увеличение SYN backlog + tcp_abort_on_overflow
sysctl -w net.ipv4.tcp_syncookies=1
sysctl -w net.ipv4.tcp_max_syn_backlog=16384
sysctl -w net.ipv4.tcp_abort_on_overflow=1
sysctl -w net.core.somaxconn=65535

# Сокращение TIME_WAIT для быстрого освобождения портов
sysctl -w net.ipv4.tcp_tw_reuse=1
sysctl -w net.ipv4.tcp_fin_timeout=15

# Conntrack tuning
sysctl -w net.netfilter.nf_conntrack_max=1048576
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
```

### Сценарий 4: ICMP Rate Limiting для web-сервера

```bash
# Строгий rate limiting только для Echo Request/Reply
sysctl -w net.ipv4.icmp_ratelimit=100
sysctl -w net.ipv4.icmp_ratelimit_mask=880
sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1

# Проверка:
cat /proc/net/snmp | grep Icmp
```

### Сценарий 5: Полный отказ от ICMP (максимальная защита)

```bash
# Блокировка ВСЕХ входящих ICMP через nftables
nft add rule ip filter input icmp type any drop

# Или через sysctl (ограниченно):
sysctl -w net.ipv4.icmp_echo_ignore_all=1
sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1
sysctl -w net.ipv4.icmp_ratelimit=1
sysctl -w net.ipv4.icmp_ratelimit_mask=0
sysctl -w net.ipv4.conf.all.accept_redirects=0
sysctl -w net.ipv4.conf.all.accept_source_route=0

# ВНИМАНИЕ: Это может сломать PMTUD и диагностику!
# Для production рекомендуется разрешить ICMP Type 3 (Dest Unreachable)
# и ICMP Type 11 (Time Exceeded) для корректной работы PMTUD.
```

## Сводная таблица sysctl для hardening

| Параметр | Значение | Назначение | Interview |
|:---|:---:|:---|:---:|
| `net.ipv4.tcp_syncookies` | 1 | Защита от SYN Flood | +++ |
| `net.ipv4.conf.all.rp_filter` | 1 (или 2) | Защита от IP Spoofing | +++ |
| `net.ipv4.conf.all.accept_redirects` | 0 | Защита от ICMP Redirect MITM | ++ |
| `net.ipv4.conf.all.send_redirects` | 0 | Запрет отправки Redirect | ++ |
| `net.ipv4.conf.all.accept_source_route` | 0 | Запрет Source Routing | ++ |
| `net.ipv4.icmp_echo_ignore_broadcasts` | 1 | Защита от Smurf/Broadcast Flood | ++ |
| `net.ipv4.icmp_ratelimit` | 100 | Rate Limiting ICMP | + |
| `net.ipv4.tcp_rfc1337` | 1 | Защита от RST атак | + |
| `net.ipv4.tcp_timestamps` | 0 | Снижение surface (опционально) | + |
| `net.core.somaxconn` | 65535 | Accept backlog | +++ |
| `net.ipv4.tcp_max_syn_backlog` | 8192+ | SYN backlog | ++ |
| `net.ipv4.tcp_abort_on_overflow` | 1 | Быстрый reject при переполнении | + |
| `net.ipv4.tcp_tw_reuse` | 1 | Повторное использование TIME_WAIT | ++ |
| `net.ipv4.tcp_fin_timeout` | 15 | Сокращение FIN_WAIT2 | + |
| `net.netfilter.nf_conntrack_max` | 1048576 | Лимит conntrack | +++ |
| `net.netfilter.nf_conntrack_tcp_timeout_established` | 600 | Таймаут established | ++ |
| `net.netfilter.nf_conntrack_tcp_timeout_time_wait` | 30 | Таймаут TIME_WAIT | + |
| `net.ipv4.ip_forward` | 0 (или 1) | IP Forwarding | +++ |

**Легенда Interview:** +++ — спрашивается часто, ++ — встречается, + — иногда.

## Типичные ошибки

| Ошибка | Последствие | Решение |
|:---|:---|:---|
| `rp_filter=1` при асимметричной маршрутизации | Легитимные пакеты отбрасываются | Установить `rp_filter=2` (Loose) |
| `ip_forward=0` на контейнерном хосте | Контейнеры не имеют сетевой связи | Установить `ip_forward=1` |
| `tcp_syncookies=0` в production | Уязвимость к SYN Flood | Включить `tcp_syncookies=1` |
| Отключение ICMP полностью | Ломает PMTUD и traceroute | Разрешить ICMP Type 3, 11 |
| `nf_conntrack_max` слишком мал | Новые соединения отбрасываются | Увеличить до 1M+ для high-load |
| Не сохранение в `/etc/sysctl.d/` | Настройки теряются после ребута | Всегда сохранять в файлы `/etc/sysctl.d/` |

## Edge Cases

- **Контейнеры (Docker/Kubernetes):** Многие sysctl переопределяются на уровне Pod security context. Проверяйте `kubectl exec <pod> -- sysctl net.ipv4.ip_forward`.
- **VPN-серверы (WireGuard/OpenVPN):** Требуют `ip_forward=1` и `rp_filter=2`. Не применяйте строгий hardening к этим параметрам.
- **eBPF-мониторинг (Cilium, Falco):** Требуют `kernel.unprivileged_bpf_disabled=1` и `kernel.kptr_restrict` — проверяйте совместимость.
- **Асимметричная маршрутизация:** `rp_filter=1` отбрасывает легитимные пакеты. Используйте `rp_filter=2`.
- **Conntrack и VRF:** По умолчанию conntrack не разделяет соединения по VRF. При overlapping IP возможны коллизии.

## Дополнительная информация

### Blacklisting ненужных модулей ядра

Отключение модулей ядра, которые не используются, снижает поверхность атаки.

```bash
# Просмотр загруженных сетевых модулей
lsmod | grep -E "^(ip_|nf_|ipt_|xt_|sctp|rds|dccp)"

# Создание blacklist для ненужных модулей
cat > /etc/modprobe.d/network-hardening.conf <<'EOF'
# Disable DCCP (Datagram Congestion Control Protocol) — редко используется
install dccp /bin/true
install dccp_v4 /bin/true
install dccp_v6 /bin/true

# Disable SCTP (Stream Control Transmission Protocol) — используется в电信
install sctp /bin/true
install sctp_v4 /bin/true
install sctp_v6 /bin/true

# Disable RDS (Reliable Datagram Sockets) — Oracle Cluster
install rds /bin/true
install rds_rdma /bin/true

# Disable TIPC (Transparent Inter-Process Communication)
install tipc /bin/true

# Disable IP Tunnel protocols (если не используются)
install ip_gre /bin/true
install ipip /bin/true
install sit /bin/true

# Disable AppleTalk, IPX, NetBEUI (legacy protocols)
install appletalk /bin/true
install ipx /bin/true
install netbeui /bin/true
EOF

# Проверка (после ребута)
modprobe -n -v dccp
# → install /bin/true — модуль заблокирован
```

### Auditd для сетевых событий

Auditd позволяет отслеживать изменения сетевой конфигурации и запуск подозрительных команд.

```bash
# Установка
apt install auditd  # Debian/Ubuntu
dnf install audit   # RHEL/Rocky

# Правила для мониторинга сетевых изменений
cat > /etc/audit/rules.d/network.rules <<'EOF'
# Мониторинг изменений sysctl
-w /etc/sysctl.conf -p wa -k sysctl_change
-w /etc/sysctl.d/ -p wa -k sysctl_change

# Мониторинг изменений firewall
-w /etc/iptables/ -p wa -k firewall_change
-w /etc/nftables.conf -p wa -k firewall_change

# Мониторинг загрузки/выгрузки модулей ядра
-w /sbin/modprobe -p x -k kernel_module
-w /sbin/insmod -p x -k kernel_module
-w /sbin/rmmod -p x -k kernel_module

# Мониторинг команд iptables/nftables
-a always,exit -F arch=b64 -S execve -F path=/usr/sbin/iptables -k iptables_cmd
-a always,exit -F arch=b64 -S execove -F path=/usr/sbin/nft -k nftables_cmd

# Мониторинг изменений routing table
-a always,exit -F arch=b64 -S sethostname -S setdomainname -k hostname_change
EOF

# Применение
augenrules --load
auditctl -l
# → -w /etc/sysctl.conf -p wa -k sysctl_change
# → -w /etc/iptables/ -p wa -k firewall_change

# Поиск событий
ausearch -k firewall_change --start today
ausearch -k sysctl_change --start today

# Алертинг через audispd (syslog)
cat >> /etc/audisp/plugins.d/syslog.conf <<'EOF'
active = yes
direction = out
path = builtin_af_syslog
type = builtin
args = LOG_LOCAL6
EOF
```

### Связанные темы

- **[ICMP: Диагностика и безопасность](../../../Networking/Protocols/ICMP/icmp_diagnostics_security.md)** — полный набор sysctl для ICMP, Rate Limiting, Conntrack interaction.
- **[ICMP Redirect](../../../Networking/Protocols/ICMP/icmp_redirect.md)** — подробный разбор Redirect-атак и защита.
- **[Харденинг ядра Linux](../../Security/Mechanisms/Kernel/hardening.md)** — kernel-level hardening (Lockdown, SMEP/SMAP, CFI).
- **[DDoS: Обзор](../../../Security/ApplicationSecurity/ddos_overview.md)** — защита от распределённых атак.
- **[Production Hardening Kubernetes](../../../Kubernetes/Networking/Network/production_network_hardening.md)** — hardening на уровне K8s.
- **[TCP: Connection Refusal](../../../Networking/Protocols/TCP/connection/tcp_connection_refusal.md)** — sysctl для защиты TCP.
- **[iSCSI: Security](../iSCSI/iscsi_security.md)** — hardening для iSCSI-серверов.
- **[Diagnosing Network Packet Loss](../network_stack_packet_loss.md)** —.conntrack tuning для предотвращения потерь.
- **[QoS](../../../Networking/Concepts/qos.md)** — Traffic shaping для защиты от flood-атак.

### Best Practices

1. **Версионирование:** Храните sysctl-файлы в Git (`/etc/sysctl.d/` можно версионировать).
2. **Постепенное применение:** Не применяйте все параметры сразу. Внедряйте по одному и мониторьте влияние.
3. **Валидация:** После изменений проверяйте `sysctl -a | grep <param>` и `nstat -az` на наличие ошибок.
4. **Откат:** Всегда имейте скрипт отката: `sysctl --system` восстанавливает дефолты из файлов.
5. **Не отключайте ICMP полностью:** Разрешите ICMP Type 3 (Dest Unreachable) и Type 11 (Time Exceeded) для PMTUD.
6. **Контейнеры:** На контейнерных хостах `ip_forward=1` обязателен. Не применяйте `rp_filter=1` без анализа топологии.
7. **Мониторинг:** Настройте алерты на `ListenOverflows`, `conntrack table full`, `UdpInErrors` (см. **[Диагностика потерь](../network_stack_packet_loss.md)**).
