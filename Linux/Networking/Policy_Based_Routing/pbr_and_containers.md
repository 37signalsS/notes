# Policy-Based Routing (PBR) и контейнеры

## Определения

**PBR и контейнеры** — взаимодействие маршрутизации на основе политик с сетевыми стеками Docker и Kubernetes. Контейнеры создают собственные сетевые пространства (netns) и bridge-интерфейсы, которые модифицируют поведение `rp_filter`, conntrack и маршрутизации, что требует специальных PBR-конфигураций.

**bridge-nf-call-iptables** — параметр ядра (`net.bridge.bridge-nf-call-iptables`), определяющий, проходят ли пакеты bridge-интерфейса через Netfilter (iptables/nftables). При включении (`1`) контейнерный трафик обрабатывается PBR-правилами на уровне хоста.

**CNI (Container Network Interface)** — плагинная архитектура сетевых плагинов для Kubernetes. Плагины (Calico, Cilium, Flannel) создают маршруты, правила `ip rule` и veth-интерфейсы для маршрутизации трафика между подами и наружу.

Теоретические основы PBR описаны в **[главном разделе (SSoT)](./index.md)**. Сетевая стек Docker — в **[Container Networking](../../../Networking/OSI_TCP_IP_Model/container_networking.md)**.

---

## Предпосылки

### Влияние Docker на PBR

Docker по умолчанию:

1. Создаёт bridge `docker0` с подсетью `172.17.0.0/16`.
2. Включает `net.bridge.bridge-nf-call-iptables=1` (пакеты bridge проходят через iptables).
3. Включает `net.ipv4.ip_forward=1`.
4. Создаёт NAT-правила (MASQUERADE) для исходящего трафика контейнеров.
5. **Сбрасывает `rp_filter`** на `docker0` в значение `0` при каждом запуске контейнера.

Последний пункт критичен для PBR: `rp_filter=0` на `docker0` может конфликтовать с настройкой `rp_filter=2` на основных интерфейсах.

### Проверка текущего состояния

```bash
# Проверка bridge-nf-call
sysctl net.bridge.bridge-nf-call-iptables
# → net.bridge.bridge-nf-call-iptables = 1

# Проверка ip_forward
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1

# Проверка rp_filter на docker0
sysctl net.ipv4.conf.docker0.rp_filter
# → net.ipv4.conf.docker0.rp_filter = 0 (сброшен Docker!)
```

---

## Основные концепции

### Поток пакета контейнера при PBR

```
Контейнер (172.17.0.2)
    │
    ▼
veth容器侧 (172.17.0.2)
    │
    ▼
docker0 bridge (172.17.0.1)
    │  ← bridge-nf-call-iptables: пакет попадает в Netfilter
    ▼
PREROUTING (nftables)
    │  ← fwmark устанавливается ЗДЕСЬ (если bridge-nf-call=1)
    ▼
rp_filter проверка на docker0
    │  ← rp_filter=0 (Docker сбросил) → проверка отключена
    ▼
ip rule → PBR-таблица → выход на eth0/eth1
    │
    ▼
POSTROUTING (MASQUERADE/SNAT)
    │
    ▼
Физический интерфейс (eth0/eth1)
```

### Проблема rp_filter в Docker

Docker при каждом запуске контейнера выполняет:

```bash
sysctl -w net.ipv4.conf.docker0.rp_filter=0
```

Это конфликтует с PBR-конфигурацией, где рекомендуется `rp_filter=2` (Loose).

**Решение:** Использовать Dispatcher-скрипт NetworkManager или systemd-networkd, который восстанавливает `rp_filter` после запуска Docker:

```bash
#!/bin/bash
# /etc/NetworkManager/dispatcher.d/99-restore-rp-filter
# Восстановление rp_filter после запуска Docker

IFACE="$1"
ACTION="$2"

if [ "$ACTION" = "up" ] && [ "$IFACE" = "docker0" ]; then
    sysctl -w net.ipv4.conf.docker0.rp_filter=2
fi
```

```bash
sudo chmod +x /etc/NetworkManager/dispatcher.d/99-restore-rp-filter
```

### PBR для Docker-сетей

Для маршрутизации трафика конкретного контейнера через определённый ISP:

```bash
# Способ 1: UID-маршрутизация (если контейнер запускается от конкретного UID)
sudo ip rule add uidrange 1000-1000 table isp1_table priority 1000

# Способ 2: Маркировка по подсети контейнера
nft add rule inet filter prerouting ip saddr 172.17.0.0/16 meta mark set 0x1
sudo ip rule add fwmark 0x1 table isp1_table priority 1001

# Способ 3: Отдельная сеть Docker через PBR
docker network create --driver bridge \
    --subnet 172.18.0.0/16 \
    -o "com.docker.network.bridge.name)=br_isp1" \
    isp1_network
```

---

## Практические сценарии

### Сценарий 1: PBR для Docker-хоста с двумя ISP

#### Задача

Docker-хост с двумя ISP. Контейнеры с веб-сервисами должны использовать ISP1, а контейнеры с базами данных — ISP2.

#### Конфигурация

```bash
# 1. Таблицы
echo "100 isp1_table" | sudo tee -a /etc/iproute2/rt_tables
echo "200 isp2_table" | sudo tee -a /etc/iproute2/rt_tables

# 2. Маршруты
ip route add default via 192.168.1.1 dev eth0 table isp1_table
ip route add default via 192.168.2.1 dev eth1 table isp2_table

# 3. Маркировка по подсетям Docker-сетей
nft add rule inet filter prerouting ip saddr 172.17.0.0/16 meta mark set 0x1  # web
nft add rule inet filter prerouting ip saddr 172.18.0.0/16 meta mark set 0x2  # db

# 4. PBR-правила
ip rule add fwmark 0x1 table isp1_table priority 1000
ip rule add fwmark 0x2 table isp2_table priority 1001

# 5. Восстановление rp_filter после Docker
cat <<'EOF' | sudo tee /etc/NetworkManager/dispatcher.d/99-restore-rp-filter
#!/bin/bash
IFACE="$1"; ACTION="$2"
if [ "$ACTION" = "up" ] && [ "$IFACE" = "docker0" ]; then
    sysctl -w net.ipv4.conf.docker0.rp_filter=2
fi
EOF
sudo chmod +x /etc/NetworkManager/dispatcher.d/99-restore-rp-filter
```

#### Валидация

```bash
# Проверка правил
ip rule show | grep "fwmark"
# → 1000:	from all fwmark 0x1 lookup isp1_table
# → 1001:	from all fwmark 0x2 lookup isp2_table

# Проверка из контейнера (web)
docker run --rm alpine ping -c 2 8.8.8.8
# → Ответы приходят, трафик идти через eth0 (ISP1)

# Проверка из контейнера (db)
docker run --rm --net=isp2_network alpine ping -c 2 8.8.8.8
# → Ответы приходят, трафик идти через eth1 (ISP2)
```

---

### Сценарий 2: Kubernetes CNI и PBR

#### Влияние CNI на PBR

Разные CNI-плагины по-разному взаимодействуют с PBR:

| CNI | Механизм маршрутизации | Взаимодействие с PBR |
| :--- | :--- | :--- |
| **Calico** | `ip rule` + routing tables (BGP или static) | Конфликтует с пользовательскими PBR-правилами ( Calico управляет RPDB) |
| **Cilium** | eBPF (без kube-proxy, без iptables) | PBR через eBPF-программы, не через `ip rule` |
| **Flannel** | VXLAN + static routes | Минимальное взаимодействие (только宿主机routing) |
| **kube-proxy (iptables)** | DNAT через iptables | PBR работает до/после DNAT |

#### Calico + PBR

Calico создаёт свои `ip rule` и таблицы маршрутизации. Для PBR поверх Calico:

```bash
# Calico использует таблицу 200 (по умолчанию)
# PBR-правила должны иметь приоритет выше (меньший номер)

# Calico-правила (автоматические)
ip rule show | grep "lookup 200"
# → 32765: from all lookup 200

# PBR-правило (выше Calico)
ip rule add from 10.0.0.0/8 table isp1_table priority 100
# → PBR сработает ПЕРЕД Calico
```

#### Cilium + PBR

Cilium использует eBPF для маршрутизации. PBR через `ip rule` может не работать, так как Cilium обходит Netfilter:

```bash
# Включение kube-proxy replacement в Cilium
cilium install --set kubeProxyReplacement=true

# PBR в Cilium через eBPF
# Используйте CiliumNetworkPolicy вместо ip rule
```

---

### Сценарий 3: PBR для Kubernetes Node с двумя uplinks

#### Задача

Kubernetes-нода с двумя NIC (eth0 — prod, eth1 — management). Трафик подов идёт через prod, kube-apiserver и node SSH — через management.

#### Конфигурация

```bash
# 1. Маркировка SSH-трафика
nft add rule inet filter prerouting ipproto tcp dport 22 meta mark set 0x2

# 2. PBR для management
ip rule add fwmark 0x2 table mgmt_table priority 10
ip rule add from 10.0.100.0/24 table mgmt_table priority 20

# 3. Маршрут management
ip route add default via 10.0.100.1 dev eth1 table mgmt_table

# 4. Conntrack zones для изолирования
nft add rule ip nat prerouting iifname "eth0" ct zone set 1
nft add rule ip nat prerouting iifname "eth1" ct zone set 2
```

#### Валидация

```bash
# SSH-сессия идёт через eth1
ip route get 8.8.8.8 ipproto tcp dport 22
# → 8.8.8.8 via 10.0.100.1 dev eth1 table mgmt_table

# Трафик подов идёт через eth0
ip route get 8.8.8.8 from 10.244.0.5
# → 8.8.8.8 via 192.168.1.1 dev eth0 table main
```

---

## Диагностика и устранение неисправностей

### Типичные проблемы

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **rp_filter сбрасывается после restart Docker** | Docker устанавливает `rp_filter=0` на docker0 | Dispatcher-скрипт для восстановления `rp_filter=2` |
| **bridge-nf-call-iptables=0** | Модуль `bridge` не загружен | `modprobe bridge` + persistent через `/etc/modules` |
| **Контейнер не видит PBR-правила** | `ip rule` работает на хосте, не в netns контейнера | PBR настраивается на хосте; контейнер следует через bridge |
| **Calico перезаписывает PBR-правила** | Calico управляет RPDB | PBR-правила с приоритетом < 32765 (выше Calico) |
| **conntrack满溢 в контейнерах** | Много коротких соединений | Увеличить `nf_conntrack_max`, снизить таймауты |
| **Контейнер не может выйти наружу** | `ip_forward=0` или нет MASQUERADE | `sysctl -w net.ipv4.ip_forward=1` + NAT-правила |

### Диагностические команды

```bash
# Проверка сетевого контекста контейнера
docker inspect <container> | grep -i "networkmode"
# → bridge / host / none

# Просмотр network namespace контейнера
PID=$(docker inspect --format '{{.State.Pid}}' <container>)
nsenter -t $PID -n ip rule show
# → Правила RPDB внутри контейнера (обычно стандартные)

# Просмотр маршрутов внутри контейнера
nsenter -t $PID -n ip route show

# Проверка veth-интерфейса
ip link show | grep veth
# → vethXXXX@if2: <BROADCAST,MULTICAST,UP> ...

# Проверка conntrack для контейнера
conntrack -L -s 172.17.0.2 | head -5

# Проверка NAT-правил
nft list chain ip nat POSTROUTING
# → masquerade
```

---

## Лучшие практики

1. **Восстанавливайте `rp_filter` после Docker:** Используйте dispatcher-скрипт или systemd-override.
2. **Используйте `rp_filter=2` (Loose) на хосте:** Strict mode (`1`) несовместим с Docker bridge.
3. **Настройте `bridge-nf-call-iptables=1`:** Без этого PBR-правила не видят контейнерный трафик.
4. **Увеличивайте `nf_conntrack_max` для контейнеров:** Каждый контейнер создаёт десятки соединений.
5. **Для Kubernetes: проверяйте CNI-плагин:** Calico, Cilium и Flannel по-разному взаимодействуют с PBR.
6. **Используйте conntrack zones:** При multi-ISP и перекрытии RFC1918-адресов между контейнерами.
7. **Изолируйте management-трафик:** SSH/kube-apiserver через отдельный ISP с помощью PBR.
8. **Не настраивайте PBR внутри контейнера:** PBR работает на уровне хоста; контейнер следует через bridge.

---

## Дополнительная информация

### Влияние Docker на rp_filter

При запуске каждого контейнера Docker выполняет:

```bash
sysctl -w net.ipv4.conf.docker0.rp_filter=0
```

Это затрагивает не только `docker0`, но и все `vethXXXX`-интерфейсы. Для PBR это критично:

- `rp_filter=0` на `docker0` → пакеты из контейнеров не фильтруются по обратному маршруту.
- Конфликт с `rp_filter=2` на `eth0` → семантика `max(all, per-interface)`.

**Решения:**

1. Dispatcher-скрипт (показан выше).
2. Systemd override для Docker:

```ini
# /etc/systemd/system/docker.service.d/override.conf
[Service]
ExecStartPost=/bin/bash -c 'sleep 2 && sysctl -w net.ipv4.conf.docker0.rp_filter=2'
```

### Связанные документы

- **[Policy-Based Routing (PBR) — Обзор](./index.md)** — архитектура и база данных правил RPDB.
- **[Практические сценарии PBR](./scenarios.md)** — сценарии с валидацией.
- **[Container Networking](../../../Networking/OSI_TCP_IP_Model/container_networking.md)** — сетевая стек Docker/Kubernetes.
- **[Reverse Path Filtering (RPF/uRPF)](../../../Networking/Protocols/rpf_urpf.md)** — rp_filter и Docker.
- **[Docker: Performance Tuning](../../../Docker/Docker_performance_tuning.md)** — conntrack tuning для Docker.
- **[VRF в Linux](../vrf.md)** — альтернатива PBR для изоляции контейнеров.
