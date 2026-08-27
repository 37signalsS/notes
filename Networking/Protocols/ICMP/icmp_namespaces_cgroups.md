# ICMP: Сетевые пространства имён и cgroups

## Определения

**Network Namespace (netns)** — изоляция сетевого стека (интерфейсы, маршруты, iptables, conntrack, sysctl) на уровне ядра Linux. Каждый netns имеет собственное состояние ICMP, независимое от других netns и хост-системы.

**cgroup (Control Group)** — механизм ядра Linux для ограничения, учёта и приоритизации ресурсов (CPU, память, сеть). Для сетевых ограничений используются `net_cls` (классификация трафика) и `net_prio` (приоритизация).

**Container** — изолированный userspace-процесс, обычно с собственным netns. ICMP-поведение внутри контейнера определяется capabilities, sysctl и политиками хоста.

## Основные концепции

### ICMP в network namespace

Каждый netns имеет:
- Собственный `/proc/net/snmp` и `/proc/net/snmp6` с раздельными счетчиками ICMP.
- Собственные sysctl-параметры (`net.ipv4.icmp_ratelimit` и др.).
- Собственные iptables/nftables правила.
- Собственный ARP-кэш и neighbour table.

**Изоляция ICMP:** ICMP-сообщения из одного netns не видны в другом netns. Трассировка `traceroute` из контейнера покажет только путь внутри контейнера до шлюза netns.

### Capabilities и ICMP в контейнерах

Для работы `ping` в контейнере требуется одна из двух вещей:
1. **Capability `CAP_NET_RAW`** — позволяет создавать raw sockets для ICMP.
2. **Настройка `net.ipv4.ping_group_range`** — разрешает обычным пользователям использовать `SOCK_DGRAM` для ICMP.

По умолчанию Docker устанавливает `cap_net_raw` на контейнер, но безопасные образы (distroless, Chainguard) могут его не иметь.

### cgroup net_cls и ICMP

`net_cls` помечает пакеты classid, что позволяет tc (traffic control) классифицировать и ограничивать ICMP-трафик на уровне хоста.

## Практические сценарии

### 1. ICMP в отдельном network namespace

```bash
# Создание netns
sudo ip netns add test_ns

# Создание veth-пары
sudo ip link add veth_host type veth peer name veth_ns

# Подключение к netns
sudo ip link set veth_ns netns test_ns

# Настройка хостовой стороны
sudo ip addr add 10.200.1.1/24 dev veth_host
sudo ip link set veth_host up

# Настройка в netns
sudo ip netns exec test_ns ip addr add 10.200.1.2/24 dev veth_ns
sudo ip netns exec test_ns ip link set veth_ns up
sudo ip netns exec test_ns ip route add default via 10.200.1.1

# Включение forwarding на хосте
sudo sysctl -w net.ipv4.ip_forward=1

# ICMP ping из netns
sudo ip netns exec test_ns ping -c 3 10.200.1.1
# → работает

# Проверка изоляции ICMP-статистики
sudo ip netns exec test_ns cat /proc/net/snmp | grep Icmp
# → счетчики относятся только к test_ns

# Проверка sysctl ICMP внутри netns
sudo ip netns exec test_ns sysctl net.ipv4.icmp_ratelimit
# → 1000
```

### 2. ICMP в Docker контейнере

```bash
# Запуск контейнера с ICMP
docker run --rm -it alpine ping -c 3 8.8.8.8

# Проверка capabilities
docker inspect <container_id> | grep -i cap_net_raw
# → должен присутствовать cap_net_raw

# Если ping не работает — добавить capability
docker run --rm -it --cap-add=NET_RAW alpine ping -c 3 8.8.8.8

# Просмотр sysctl внутри контейнера
docker exec <container_id> sysctl net.ipv4.icmp_ratelimit
docker exec <container_id> sysctl net.ipv4.icmp_echo_ignore_broadcasts

# ICMP статистика в контейнере (если установлен iputils)
docker exec <container_id> cat /proc/net/snmp | grep Icmp
```

### 3. Отключение ICMP для контейнера через sysctl

```bash
# Отключение ping для конкретного netns
sudo ip netns exec test_ns sysctl -w net.ipv4.icmp_echo_ignore_all=1

# Проверка
sudo ip netns exec test_ns ping -c 1 10.200.1.1
# → Connect: Network is unreachable

# Возврат
sudo ip netns exec test_ns sysctl -w net.ipv4.icmp_echo_ignore_all=0
```

### 4. cgroup net_cls для ICMP

```bash
# Создание cgroup
sudo mkdir -p /sys/fs/cgroup/net_cls/icmp_limit

# Помещение процесса в cgroup (classid = 0x00110011)
echo 0x00110011 | sudo tee /sys/fs/cgroup/net_cls/icmp_limit/net_cls.classid

# Запуск процесса в cgroup
sudo cgexec -g net_cls:icmp_limit ping 8.8.8.8

# Или через Docker
docker run --rm -it \
  --device-cgroup-rule='c 10:200 rwm' \
  --net-cls=0x00110011 \
  alpine ping 8.8.8.8
```

### 5. Traffic Control (tc) для ограничения ICMP

```bash
# Создание hierarchy queueing discipline
sudo tc qdisc add dev eth0 root handle 1: htb default 30

# Создание класса для ICMP (ограничение 1Mbit)
sudo tc class add dev eth0 parent 1: classid 1:1 htb rate 1mbit ceil 1mbit
sudo tc class add dev eth0 parent 1:1 classid 1:10 htb rate 1mbit ceil 1mbit

# Фильтр: ICMP (protocol 1) → класс 1:10
sudo tc filter add dev eth0 protocol ip parent 1:0 prio 1 u32 match ip protocol 1 0xff flowid 1:10

# Проверка статистики
sudo tc -s class show dev eth0 classid 1:10
```

### 6. Kubernetes: ICMP политики для pod

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-icmp-monitoring
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: web
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: ICMP
          port: 8
```

### 7. Проверка ICMP в netns через tcpdump

```bash
# Захват ICMP в конкретном netns
sudo ip netns exec test_ns tcpdump -i veth_ns icmp

# Или с хоста по интерфейсу, подключенному к netns
sudo tcpdump -i veth_host icmp
```

## Дополнительная информация

*   **[ICMP в Docker и контейнерах](../../icmp_echo_ping.md)** — диагностика доступности из контейнеров.
*   **[ICMP в Kubernetes](../../icmp_diagnostics_security.md)** — NetworkPolicy и CNI.
*   **[Маршрутизация в Linux](../../../Linux/SystemAdministration/routing.md)** — ip netns.
*   **[Linux network namespaces](../../../Linux/SystemAdministration/network_namespaces.md)** — общая документация.
