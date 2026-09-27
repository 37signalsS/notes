# Sysctl tuning для production Policy-Based Routing (PBR)

## Определения

**Sysctl tuning для PBR** — настройка параметров ядра Linux, критичных для корректной работы и производительности маршрутизации на основе политик. Включает параметры маршрутизации (`ip_forward`, `rp_filter`, `fib_multipath_hash_policy`), conntrack (`nf_conntrack_max`, таймауты), сетевые буферы (`netdev_max_backlog`, `rmem_max/wmem_max`) и sécurité (`accept_redirects`, `accept_source_route`).

Базовые параметры sysctl описаны в **[sysctl: сетевые параметры ядра](../../Networking/Settings/sysctl_network.md)**. В этом файле — специфичные для PBR и production-нагрузки параметры.

---

## Предпосылки

### Проверка текущих значений

```bash
# Быстрая проверка всех критичных параметров
for param in \
  net.ipv4.ip_forward \
  net.ipv4.conf.all.rp_filter \
  net.ipv4.conf.default.rp_filter \
  net.ipv4.fib_multipath_hash_policy \
  net.ipv4.conf.all.accept_redirects \
  net.ipv4.conf.all.accept_source_route \
  net.netfilter.nf_conntrack_max \
  net.netfilter.nf_conntrack_buckets \
  net.core.netdev_max_backlog \
  net.core.rmem_max \
  net.core.wmem_max \
  net.ipv4.ip_local_port_range; do
  echo "$param = $(sysctl -n $param 2>/dev/null || echo 'N/A')"
done
```

---

## Основные концепции

### Группы параметров для PBR

| Группа | Назначение | Ключевые параметры |
| :--- | :--- | :--- |
| **Маршрутизация** | Включение forwarding, управление RPDB | `ip_forward`, `rp_filter`, `fib_multipath_hash_policy` |
| **Conntrack** | Отслеживание соединений, размер таблицы, таймауты | `nf_conntrack_max`, `nf_conntrack_buckets`, `tcp_timeout_*` |
| **Сетевые буферы** | Обработка высоких packet rates | `netdev_max_backlog`, `rmem_max`, `wmem_max` |
| **Sécurité** | Защита от атак | `accept_redirects`, `accept_source_route`, `log_martians` |
| **Производительность** | Оптимизация для multi-ISP | `tcp_max_syn_backlog`, `somaxconn`, `ip_local_port_range` |

---

## Практические сценарии

### Сценарий 1: Полный sysctl-профиль для PBR-шлюза (2 ISP)

```bash
# /etc/sysctl.d/99-pbr-production.conf

# ============================================
# Маршрутизация
# ============================================

# Включение IP forwarding (обязательно для PBR)
net.ipv4.ip_forward = 1

# Loose mode rp_filter (совместимо с PBR и асимметрией)
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2

# Hash policy для ECMP (5-tuple для стабильности сессий)
net.ipv4.fib_multipath_hash_policy = 1

# Отключение ICMP Redirect (PBR не генерирует Redirect)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0

# Защита от source routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0

# Логирование невалидных пакетов (для диагностики)
net.ipv4.conf.all.log_martians = 1

# ============================================
# Conntrack
# ============================================

# Размер таблицы: ожидаемые соединения × 4 × число ISP
# 50K соединений × 4 × 2 ISP = 400K → 524288
net.netfilter.nf_conntrack_max = 524288

# Хеш-таблица: nf_conntrack_max / 4
net.netfilter.nf_conntrack_buckets = 131072

# Таймауты TCP (снижены для быстрой очистки)
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 30

# Таймауты UDP
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 120

# Таймаут ICMP
net.netfilter.nf_conntrack_icmp_timeout = 30

# ============================================
# Сетевые буферы
# ============================================

# Максимальное число пакетов в очереди (высокий packet rate)
net.core.netdev_max_backlog = 16384

# Размер буферов приёма/отправки (16 МБ)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Размер буферов TCP (min, default, max)
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# ============================================
# Sécurité
# ============================================

# ARP-защита
net.ipv4.conf.all.arp_ignore = 1
net.ipv4.conf.all.arp_announce = 2

# Защита от SYN flood
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 8192

# ============================================
# Производительность
# ============================================

# Диапазон локальных портов (для масштабирования)
net.ipv4.ip_local_port_range = 1024 65535

# Максимальное числоinyin-сокетов
net.core.somaxconn = 8192

# Размер очереди входящих соединений
net.ipv4.tcp_max_syn_backlog = 8192
```

```bash
# Применение
sudo sysctl --system

# Проверка
sysctl net.ipv4.fib_multipath_hash_policy
# → net.ipv4.fib_multipath_hash_policy = 1
```

---

### Сценарий 2: Sysctl для PBR-шлюза с высокой нагрузкой (>100K соединений)

```bash
# /etc/sysctl.d/99-pbr-highload.conf

# Conntrack: увеличенный размер
net.netfilter.nf_conntrack_max = 2097152
net.netfilter.nf_conntrack_buckets = 524288

# Таймауты: агрессивная очистка
net.netfilter.nf_conntrack_tcp_timeout_established = 1800
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 10
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 15

# Сетевые буферы: максимум
net.core.netdev_max_backlog = 32768
net.core.rmem_max = 33554432
net.core.wmem_max = 33554432
net.ipv4.tcp_rmem = 4096 87380 33554432
net.ipv4.tcp_wmem = 4096 65536 33554432

# Размер FIB
net.ipv4.fib_max_size = 1048576

# Порты
net.ipv4.ip_local_port_range = 1024 65535

# SYN backlog
net.ipv4.tcp_max_syn_backlog = 16384
net.core.somaxconn = 16384
```

---

### Сценарий 3: Sysctl для контейнерного хоста с PBR

```bash
# /etc/sysctl.d/99-pbr-docker.conf

# IP forwarding (обязательно для Docker)
net.ipv4.ip_forward = 1

# Loose mode (совместимо с Docker bridge)
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2

# bridge-nf-call (пакеты bridge через Netfilter)
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1

# Conntrack: увеличенный для контейнеров
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144

# Таймауты
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30

# Сетевые буферы
net.core.netdev_max_backlog = 16384
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
```

**Примечание:** Модуль `bridge` должен быть загружен до применения:

```bash
sudo modprobe bridge
echo "bridge" | sudo tee -a /etc/modules
```

---

### Сценарий 4: Мониторинг sysctl в production

```bash
# Скрипт проверки критичных параметров
#!/bin/bash
# /usr/local/bin/check-pbr-sysctl.sh

echo "=== PBR Sysctl Health Check ==="

# rp_filter
RP_ALL=$(sysctl -n net.ipv4.conf.all.rp_filter)
RP_DEFAULT=$(sysctl -n net.ipv4.conf.default.rp_filter)
if [ "$RP_ALL" -ne 2 ] || [ "$RP_DEFAULT" -ne 2 ]; then
    echo "[WARN] rp_filter не в Loose mode: all=$RP_ALL, default=$RP_DEFAULT"
fi

# ip_forward
IP_FWD=$(sysctl -n net.ipv4.ip_forward)
if [ "$IP_FWD" -ne 1 ]; then
    echo "[CRIT] ip_forward=0 — маршрутизация отключена!"
fi

# conntrack满溢
COUNT=$(cat /proc/sys/net/netfilter/nf_conntrack_count)
MAX=$(cat /proc/sys/net/netfilter/nf_conntrack_max)
PERCENT=$((COUNT * 100 / MAX))
if [ "$PERCENT" -gt 80 ]; then
    echo "[WARN] conntrack заполнен на ${PERCENT}% ($COUNT/$MAX)"
fi

# insert_failed
INSERT_FAIL=$(conntrack -S 2>/dev/null | awk '/insert_failed/ {print $NF}')
if [ "${INSERT_FAIL:-0}" -gt 0 ]; then
    echo "[WARN] conntrack insert_failed=$INSERT_FAIL — увеличить hashsize"
fi

# fib_multipath_hash_policy
HASH=$(sysctl -n net.ipv4.fib_multipath_hash_policy)
if [ "$HASH" -ne 1 ]; then
    echo "[INFO] fib_multipath_hash_policy=$HASH (рекомендуется 1 для ECMP)"
fi
```

```bash
# Добавление в cron
echo "*/5 * * * * root /usr/local/bin/check-pbr-sysctl.sh | logger -t pbr-sysctl" | \
    sudo tee /etc/cron.d/pbr-sysctl-check
```

---

## Диагностика и устранение неисправностей

### Типичные проблемы

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`rp_filter` сбрасывается после reboot** | Docker или systemd-networkd переопределяет | Использовать dispatcher-скрипт или systemd-override |
| **conntrack满溢 после увеличения max** | `hashsize` не увеличен | `echo $((max/4)) > /sys/module/nf_conntrack/parameters/hashsize` |
| **Высокий drop на高负载** | `netdev_max_backlog` слишком мал | Увеличить до 16384–32768 |
| **SYN flood при PBR** | `tcp_syncookies` отключен | Включить `net.ipv4.tcp_syncookies=1` |
| **ECMP не работает** | `fib_multipath_hash_policy=0` | Установить `fib_multipath_hash_policy=1` |
| **Пакеты отбрасываются ядром** | `log_martians` включён | Проверить `dmesg` для диагностики |

### Проверка применения

```bash
# Все параметры PBR
sysctl -a | grep -E "rp_filter|ip_forward|fib_multipath|conntrack_max|netdev_max_backlog"

# Конкретный параметр
sysctl net.ipv4.conf.all.rp_filter
# → net.ipv4.conf.all.rp_filter = 2

# Persistent-файлы
ls -la /etc/sysctl.d/*pbr*
# → /etc/sysctl.d/99-pbr-production.conf
```

---

## Лучшие практики

1. **Используйте drop-in файлы (`/etc/sysctl.d/*.conf`)** вместо `/etc/sysctl.conf` — это modern подход.
2. **Именуйте файлы с префиксом:** `99-pbr-*.conf` для guarantees обработки в последнюю очередь.
3. **Применяйте через `sysctl --system`** после изменений — это перечитает все файлы.
4. **Рассчитывайте `nf_conntrack_max`:** Ожидаемые соединения × 4 × число ISP. Не используйте дефолт (262144) для production.
5. **Увеличивайте `hashsize`:** `nf_conntrack_max / 4` — баланс между памятью и скоростью.
6. **Мониторьте `insert_failed`:** Если > 0 — хеш-таблица переполнена.
7. **Включайте `log_martians`:** Для диагностики аномальных пакетов.
8. **Используйте `fib_multipath_hash_policy=1`:** Для стабильности ECMP-сессий (5-tuple hash).
9. **Не забывайте про bridge-nf-call:** Без него Docker/K8s-трафик не попадает в PBR.

---

## Дополнительная информация

### Влияние systemd-networkd на sysctl

Systemd-networkd может переопределять sysctl-значения:

```ini
# /etc/systemd/network/eth0.network
[Network]
IPForward=yes  # Устанавливает ip_forward=1 для eth0
```

Для PBR убедитесь, что `IPForward=yes` не конфликтует с вашими настройками.

### Связанные документы

- **[sysctl: сетевые параметры ядра](../../Networking/Settings/sysctl_network.md)** — общий обзор параметров.
- **[Policy-Based Routing (PBR) — Обзор](./index.md)** — архитектура PBR.
- **[Conntrack и PBR](./conntrack_pbr.md)** — детали conntrack tuning.
- **[Автоматизация PBR](./automation.md)** — управление sysctl через Ansible.
- **[Docker: Performance Tuning](../../../Docker/Docker_performance_tuning.md)** — conntrack для Docker.
- **[Reverse Path Filtering (RPF/uRPF)](../../../Networking/Protocols/rpf_urpf.md)** — rp_filter и PBR.
