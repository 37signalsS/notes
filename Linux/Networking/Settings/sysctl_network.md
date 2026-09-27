# sysctl: сетевые параметры ядра для persistent-конфигурации

**sysctl** — интерфейс для чтения и изменения параметров ядра Linux в runtime и permanently. Сетевые параметры sysctl критичны для работы persistent-конфигурации сети: многие менеджеры (NetworkManager, systemd-networkd, Netplan)依赖ят от значений этих параметров, а неправильные значения могут полностью заблокировать сетевую функциональность.

## Определения

- **sysctl** — утилита и файловая система (`/proc/sys/`) для управления параметрами ядра. Изменения в runtime через `sysctl -w` не переживают reboot; для persistent-применения используют файлы `/etc/sysctl.d/*.conf`.
- **sysctl.d** — директория для drop-in файлов с параметрами ядра. Файлы обрабатываются в лексикографическом порядке; переопределяют значения из `/etc/sysctl.conf`.
- **rp_filter (Reverse Path Filtering)** — механизм ядра, проверяющий, что входящий пакет приходит с интерфейса, через который ядро маршрутизировало бы ответ. Защита от IP spoofing; критичен для асимметричной маршрутизации.
- **IP Forwarding** — параметр `net.ipv4.ip_forward`, разрешающий ядру маршрутизировать пакеты между интерфейсами. Обязателен для NAT, маршрутизаторов, контейнерных хостов.
- **conntrack (Connection Tracking)** — подсистема Netfilter, отслеживающая состояния всех соединений. Параметры `net.netfilter.nf_conntrack_*` определяют размер таблицы и таймауты.

## Базовые концепции

### Механизм persistent-применения

```
Загрузка системы
  → systemd-sysctl.service
    → /etc/sysctl.conf (deprecated)
    → /etc/sysctl.d/*.conf (рекомендуется)
      → /proc/sys/net/... (применение к ядру)
```

Приоритет: файлы `/etc/sysctl.d/` переопределяют `/etc/sysctl.conf`. Параметры применяются в порядке обработки файлов. Для немедленного применения: `sysctl --system`.

### Когда sysctl критичен для persistent-конфигурации

| Сценарий | Параметр | Последствие при неверном значении |
| :--- | :--- | :--- |
| **Маршрутизатор / NAT** | `net.ipv4.ip_forward=0` | Трафик между интерфейсами не маршрутизируется |
| **Асимметричная маршрутизация** | `net.ipv4.conf.all.rp_filter=1` | Ответные пакеты отбрасываются ядром |
| **Docker / Kubernetes хост** | `net.bridge.bridge-nf-call-iptables=0` | Service IP не работает, CNI ломается |
| **NAT-шлюз с высокой нагрузкой** | `nf_conntrack_max=262144` (дефолт) | `nf_conntrack: table full, dropping packet` |
| **VPN-туннель** | `net.ipv4.ip_forward=0` | Трафик через туннель не проходит |
| **Bridge с фильтрацией** | `net.bridge.bridge-nf-call-ip6tables=0` | IPv6-трафик не фильтруется через bridge |

## Практические сценарии

### 1. IP Forwarding — обязательный параметр для маршрутизации

```bash
# Проверка текущего значения
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 0

# Включение (runtime)
sudo sysctl -w net.ipv4.ip_forward=1

# Persistent (переживает reboot)
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-ip-forward.conf
sudo sysctl --system
```

**Где это критично:**
- NAT / маскарад (`iptables -t nat -j MASQUERADE`)
- Маршрутизатор Linux (два NIC в разных подсетях)
- Docker-хост (контейнеры маршрутизируют трафик через хост)
- Kubernetes-нода (CNI требует `ip_forward=1`)
- VPN-шлюз (WireGuard, IPsec)

### 2. Reverse Path Filtering — защита от spoofing и проблема с асимметрией

```bash
# Значения rp_filter:
# 0 — отключено (без проверки)
# 1 — Strict (проверка по основной таблице маршрутизации)
# 2 — Loose (проверка по любому интерфейсу с known route)

# Проверка
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.default.rp_filter
sysctl net.ipv4.conf.eth0.rp_filter

# Отключение (если асимметрия — осознанное решение)
sudo sysctl -w net.ipv4.conf.all.rp_filter=0
sudo sysctl -w net.ipv4.conf.default.rp_filter=0

# Persistent
cat <<EOF | sudo tee /etc/sysctl.d/99-rp-filter.conf
net.ipv4.conf.all.rp_filter = 0
net.ipv4.conf.default.rp_filter = 0
EOF
sudo sysctl --system
```

**Важно:** Семантика `rp_filter` уникальна — `all` работает как **максимум** из `all` и интерфейсного значения. Установка `all=0` НЕ отключает проверку, если на интерфейсе `rp_filter=1`.

### 3. Bridge + Netfilter — интеграция для Docker/Kubernetes

```bash
# Проверка
sysctl net.bridge.bridge-nf-call-iptables
sysctl net.bridge.bridge-nf-call-ip6tables

# Включение (обязательно для Docker и Kubernetes)
cat <<EOF | sudo tee /etc/sysctl.d/99-bridge.conf
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
EOF
sudo sysctl --system
```

**Примечание:** Параметры `bridge-nf-call-*` доступны только после загрузки модуля `bridge`. Если значение показывает `permission denied` или `No such file`, выполните `sudo modprobe bridge`.

### 4. Conntrack — sizing и таймауты для production

```bash
# Текущее состояние
sysctl net.netfilter.nf_conntrack_max        # максимальный размер таблицы
cat /proc/sys/net/netfilter/nf_conntrack_count  # текущее количество записей
sysctl net.netfilter.nf_conntrack_tcp_timeout_established  # таймаут TCP (сек)

# Production-рекомендации для NAT-шлюза
cat <<EOF | sudo tee /etc/sysctl.d/99-conntrack.conf
# Размер таблицы conntrack (по умолчанию 262144)
# Для высоконагруженных серверов: 524288-2097152
net.netfilter.nf_conntrack_max = 1048576

# Размер хеш-таблицы (рекомендуется nf_conntrack_max / 4)
net.netfilter.nf_conntrack_buckets = 262144

# Таймауты (по умолчанию TCP ESTABLISHED = 432000 сек = 5 дней)
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 60
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 120
net.netfilter.nf_conntrack_icmp_timeout = 30
EOF
sudo sysctl --system
```

**Мониторинг:**
```bash
# Проверка заполнения таблицы
watch -n 1 'echo "$(cat /proc/sys/net/netfilter/nf_conntrack_count)/$(cat /proc/sys/net/netfilter/nf_conntrack_max)" | bc -l'

# Логирование переполнения
dmesg | grep "nf_conntrack: table full"
```

### 5. Маршрутизация и метрики

```bash
cat <<EOF | sudo tee /etc/sysctl.d/99-routing.conf
# Включение IP forwarding (для маршрутизаторов)
net.ipv4.ip_forward = 1

# Защита от source routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0

# ICMP redirect (отключить на маршрутизаторах)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0

# Reverse Path Filtering (отключить при асимметрии)
net.ipv4.conf.all.rp_filter = 0
net.ipv4.conf.default.rp_filter = 0

# ARP-защита
net.ipv4.conf.all.arp_ignore = 1
net.ipv4.conf.all.arp_announce = 2
EOF
sudo sysctl --system
```

### 6. Связь sysctl с сетевыми менеджерами

| Менеджер | Зависимые sysctl-параметры | Где настраивать |
| :--- | :--- | :--- |
| **NetworkManager** | `rp_filter`, `accept_redirects`, `arp_ignore` | Управляет через sysctl plugin или dispatcher-скрипты |
| **systemd-networkd** | `IPv6AcceptRA`, `IPForward` (в `.network` файлах) | Секция `[Network]` `.network` файла |
| **Netplan** | `parameters.ipv4.rp-filter` (в YAML) | Параметры интерфейса |
| **ifupdown2** | Через `post-up` хуки | `post-up sysctl -w net.ipv4.ip_forward=1` |

**Важно:** Некоторые менеджеры (systemd-networkd) переопределяют sysctl-значения при применении конфигурации. Например, `IPForward=yes` в `.network` файле устанавливает `net.ipv4.ip_forward=1` для управляемых интерфейсов.

### 7. Диагностика: sysctl как источник проблем

```bash
# Быстрая проверка критичных параметров
for param in \
  net.ipv4.ip_forward \
  net.ipv4.conf.all.rp_filter \
  net.bridge.bridge-nf-call-iptables \
  net.netfilter.nf_conntrack_max \
  net.core.somaxconn \
  net.ipv4.tcp_max_syn_backlog; do
  echo "$param = $(sysctl -n $param 2>/dev/null || echo 'N/A')"
done
```

## Дополнительная информация

### Типичные ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `sysctl: permission denied` | Нет root-привилегий или параметр read-only | `sudo sysctl -w` или `sudo sysctl --system` |
| Bridge-nf-call = 0 после reboot | Модуль `bridge` не загружен | Добавить `bridge` в `/etc/modules` или `modprobe bridge` |
| Параметр не применяется после reboot | Файл в `/etc/sysctl.d/` имеет неверный синтаксис | Проверить формат: `key = value` (пробелы обязательны) |
| `rp_filter` не отключается | Интерфейсное значение выше `all` | Установить `rp_filter=0` и на интерфейсе: `sysctl -w net.ipv4.conf.eth0.rp_filter=0` |
| conntrack table full после увеличения max | `hashsize` не увеличен | `echo $((max/4)) > /sys/module/nf_conntrack/parameters/hashsize` |

### См. также

- **[Постоянная настройка сети](./Persistent_Network/index.md)** — выбор менеджера и интеграция с systemd.
- **[iptables: основы](./tools/iptables_basics.md)** — Netfilter, conntrack и NAT.
- **[nftables: архитектура](./tools/nftables/architecture_and_concepts.md)** — современный стек файрвола.
- **[Асимметричная маршрутизация](../../../Networking/Concepts/asymmetric_routing.md)** — rp_filter и сценарии использования.
- **[Reverse Path Filtering (rp_filter)](../../../Networking/Protocols/rpf_urpf.md)** — глубокий обзор параметра.
