# Сетевая архитектура Ceph: настройка и оптимизация

Документ охватывает сетевую конфигурацию кластера Ceph: разделение трафика, тюнинг, диагностику и лучшие практики. Сеть является первопричиной большинства проблем производительности (Slow Ops, latency) в Ceph-кластерах. Актуально для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

---

## Определения

**Public Network (`public_network`)** — сеть для клиентского трафика и взаимодействия мониторов (MON). Доступна всем компонентам кластера и клиентам. Клиенты подключаются к OSD через эту сеть для операций чтения/записи.

**Cluster Network (`cluster_network`)** — изолированная сеть для внутреннего трафика: репликация OSD, восстановление данных (recovery/backfill), heartbeat между OSD. **Недоступна клиентам.** Используется только для внутренних операций кластера.

**Messenger v2 (msgr2)** — актуальный протокол сетевого взаимодействия Ceph. Поддерживает шифрование (AES-GCM) и сжатие трафика. Использует порты **3300** (msgr2) и **6789** (msgr2 v1 fallback).

**Heartbeat** — механизм проверки доступности OSD. Каждый OSD периодически отправляет ping другим OSD в своей Failure Domain. Потеря heartbeat приводит к пометке OSD как `down`.

**Recovery** — процесс восстановления данных после выхода OSD из строя. Использует cluster_network для передачи данных между OSD.

**Backfill** — процесс заполнения данных на новый/восстановленный OSD. Более тяжёлая операция, чем recovery (полное копирование PG).

---

## Базовые концепции

### Разделение сетей (Topology)

Рекомендуемая архитектура для production:

```
┌─────────────────────────────────────────────┐
│              Public Network                 │
│         (клиенты ↔ MON ↔ OSD)              │
│         10.0.0.0/24 (1 Гбит/с+)           │
├─────────────────────────────────────────────┤
│             Cluster Network                 │
│          (OSD ↔ OSD, репликация)           │
│         10.0.1.0/24 (10/25/40 Гбит/с)     │
├─────────────────────────────────────────────┤
│              Management Network             │
│          (cephadm, SSH, мониторинг)        │
│         10.0.2.0/24 (1 Гбит/с)            │
└─────────────────────────────────────────────┘
```

**Почему разделение критично:**
- Recovery/backfill генерирует значительный трафик (десятки Гбит/с)
- Клиентский трафик не должен конкурировать с внутренним
- Heartbeat не должен теряться из-за перегрузки сети

### Порты Ceph

| Порт | Протокол | Назначение |
|------|----------|------------|
| **3300** | TCP | Messenger v2 (основной, modern) |
| **6789** | TCP | Messenger v2 v1 fallback |
| **6800–7300** | TCP | OSD (данные, heartbeat, replication) |
| **9283** | TCP | Prometheus metrics (MGR) |
| **8443** | TCP | Dashboard HTTPS |
| **7480** | TCP | RGW HTTP |
| **7443** | TCP | RGW HTTPS |

### Требования к сети

| Параметр | Минимум | Рекомендация |
|----------|---------|--------------|
| **Public Network** | 1 Гбит/с | 10 Гбит/с |
| **Cluster Network** | 10 Гбит/с | 25/40 Гбит/с |
| **MTU** | 1500 | 9000 (jumbo frames) |
| **Latency (DC)** | < 1 мс | < 0.5 мс |
| **Latency (跨DC)** | < 10 мс | < 5 мс |
| **Packet Loss** | 0% | 0% |

### MTU (Maximum Transmission Unit)

**Критически важно:** MTU должен быть одинаков на **всех** интерфейсах в цепочке клиент → OSD.

```bash
# Проверка MTU на интерфейсе
ip link show eth0 | grep mtu
# → mtu 9000  (jumbo frames)

# Если MTU не совпадает, возможны:
# - Фрагментация пакетов → рост latency
# - Таймауты маппинга RBD
# - Slow Ops на OSD

# Установка MTU (persistent)
cat <<EOF | sudo tee /etc/networkd-dispatcher/routable.d/99-mtu
#!/bin/bash
ip link set eth0 mtu 9000
EOF
sudo chmod +x /etc/networkd-dispatcher/routable.d/99-mtu
```

### Bonded Interfaces (LACP)

Для production рекомендуется агрегация интерфейсов:

```bash
# Пример LACP (mode 4) для cluster network
cat <<EOF | sudo tee /etc/network/interfaces.d/bond0
auto bond0
iface bond0 inet static
    address 10.0.1.10
    netmask 255.255.255.0
    bond-slaves eth2 eth3
    bond-mode 802.3ad
    bond-xmit-hash-policy layer3+4
    bond-miimon 100
    bond-lacp-rate fast
    mtu 9000
EOF
```

---

## Практические сценарии

### 1. Проверка сетевой связности

```bash
# Проверка доступности MON (public network)
for mon in 10.0.0.10 10.0.0.11 10.0.0.12; do
  echo -n "$mon:3300 → "
  nc -zv -w2 $mon 3300 2>&1 | grep -o "succeeded\|timed out\|refused"
done

# Проверка доступности OSD (cluster network)
for osd in 10.0.1.10 10.0.1.11 10.0.1.12; do
  echo -n "$osd:6800 → "
  nc -zv -w2 $osd 6800 2>&1 | grep -o "succeeded\|timed out\|refused"
done

# Проверка MTU между хостами
ping -c 3 -M do -s 8972 10.0.1.11  # 9000 - 28 (headers) = 8972
# → Если получает ответы — MTU 9000 работает
# → Если "message too long" — MTU не совпадает
```

### 2. Диагностика Slow Ops

```bash
# Шаг 1: Определение проблемных OSD
ceph osd perf | sort -k2 -n | head -10
# → OSD с высоким commit/apply latency

# Шаг 2: Проверка сетевой статистики
# На хосте с проблемным OSD:
ethtool -S eth0 | grep -i "error\|drop\|miss"
# → Ищите errors, drops, missed interrupts

# Шаг 3: Проверка tcp-соединений
ss -s
# → TCP: total, timewait, established

# Шаг 4: Проверка queue на интерфейсе
ip -s link show eth0
# → RX/TX errors, dropped, overruns

# Шаг 5: Проверка ARP-таблицы
arp -n | grep "10.0.1"
# → Убедитесь, что MAC-адреса правильные

# Шаг 6: Тест пропускной способности
iperf3 -s  # на одном OSD-хосте
iperf3 -c 10.0.1.11 -P 4 -t 30  # на другом
# → Должно быть ~линейная пропускная способность
```

### 3. Настройка firewall

```bash
# Основные порты для Ceph (на каждом хосте)
iptables -A INPUT -p tcp --dport 3300 -j ACCEPT   # Messenger v2
iptables -A INPUT -p tcp --dport 6789 -j ACCEPT   # Messenger v1
iptables -A INPUT -p tcp --dport 6800:7300 -j ACCEPT  # OSD
iptables -A INPUT -p tcp --dport 9283 -j ACCEPT   # Prometheus
iptables -A INPUT -p tcp --dport 8443 -j ACCEPT   # Dashboard

# Для cluster network (только между OSD)
iptables -A INPUT -i bond0 -s 10.0.1.0/24 -p tcp --dport 6800:7300 -j ACCEPT

# Сохранение правил
iptables-save > /etc/iptables/rules.v4
```

### 4. Проверка производительности сети

```bash
# Тест latency между MON и OSD
for osd in 10.0.1.10 10.0.1.11 10.0.1.12; do
  echo -n "$osd: "
  ping -c 10 $osd | tail -1
done

# Тест пропускной способности (cluster network)
iperf3 -c 10.0.1.11 -P 8 -t 30 -J | python3 -c "
import json, sys
data = json.load(sys.stdin)
for end in data['end']['streams']:
    print(f\"Stream {end['sender']['port']}: {end['sender']['bits_per_second']/1e9:.2f} Gbps\")
"

# Тест tcp-retransmissions
ss -ti dst 10.0.1.10
# → Ищите retransmits, rtt, cwnd
```

### 5. Мониторинг сети

```bash
# Prometheus метрики сети Ceph
# Включите модуль prometheus в MGR
ceph mgr module enable prometheus

# Основные метрики для алертов:
# ceph_osd_op_r_latency - латентность чтения
# ceph_osd_op_w_latency - латентность записи
# ceph_osd_op_r - количество операций чтения
# ceph_osd_op_w - количество операций записи

# Проверка tcp-соединений OSD
ceph daemon osd.0 dump_ops_in_flight 2>/dev/null | head
```

### 6. Настройка для跨DC кластеров

```bash
# Если кластер растянут между дата-центрами:

# 1. Увеличьте таймауты
ceph config set global osd_op_timeout 60
ceph config set global osd_heartbeat_grace 20

# 2. Ограничьте recovery
ceph config set osd osd_max_backfills 1
ceph config set osd osd_recovery_max_active 2

# 3. Настройте failure domain
ceph osd crush set-device-class dc1 osd.{0..5}
ceph osd crush set-device-class dc2 osd.{6..11}

# 4. Используйте rules с failure-domain=rack или host
ceph osd crush rule create-replicated multi-dc default rack
```

---

## Диагностика

| Проблема | Симптом | Причина | Решение |
|----------|---------|---------|---------|
| Slow Ops | `ceph osd perf`: latency > 50ms | Перегрузка сети, MTU mismatch | Проверить MTU, `ethtool -S`, `iperf3` |
| OSD down | `ceph osd tree`: OSD down | Heartbeat timeout, сеть недоступна | Проверить `ping`, firewall, `systemctl status ceph-osd@*` |
| Таймаут маппинга | `rbd map` зависает | Порт 3300/6789 закрыт, MTU | `nc -zv`, проверить MTU |
| Recovery медленное | Recovery > 30 мин | Мало bandwidth в cluster network | Расширить канал, `osd_max_backfills=1` |
| `CLOCK_SKEW` | `ceph health detail` | NTP рассинхронизирован | `chronyc tracking`, `chronyd makestep` |
| Packet drops | `ethtool -S`: drops > 0 | Перегрузка NIC, buffer overflow | Bond interfaces, increase ring buffer |

---

## Лучшие практики

- **Разделяйте public и cluster сети** — это критично для производительности
- **MTU 9000 (jumbo frames)** — одинаков на всех интерфейсах в цепочке
- **Cluster Network: 25/40 Гбит/с** — минимум для production с recovery
- **Bond interfaces (LACP)** — для отказоустойчивости и пропускной способности
- **Мониторьте `ethtool -S`** — ищите errors, drops, misses
- **Тестируйте `iperf3`** перед развертыванием — убедитесь в реальной пропускной способности
- **NTP обязателен** — `chronyd` на всех узлах, иначе `CLOCK_SKEW` ломает кворум
- **Firewall: минимум портов** — только необходимые для Ceph

### См. также

- [Обзор Ceph](./ceph_overview.md) — архитектура компонентов
- [Администрирование Ceph](./Administration/index.md) — управление кластером
- [Операции Ceph](./Administration/operations.md) — настройка конфигурации
- [Мониторинг Ceph](./Administration/monitoring.md) — метрики и алерты
- [ceph_ansible_installation.md](./ceph_ansible_installation.md) — сетевые требования при установке
