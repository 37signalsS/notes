# Сетевой драйвер overlay

**Актуально для:** Docker Engine 29.x

## Определения

- **Драйвер overlay** — сетевой драйвер Docker, создающий виртуальные сети, охватывающие несколько хостов. Позволяет контейнерам на разных узлах взаимодействовать в едином L2-сегменте, абстрагируясь от физической топологии.
- **VXLAN (Virtual Extensible LAN)** — технология инкапсуляции, упаковывающая Ethernet-кадры в UDP-пакеты (порт 4789) для передачи через L3-сеть. Глубокое изучение: [VXLAN](../../../Networking/Tunnels/vxlan.md).
- **VTEP (VXLAN Tunnel End Point)** — логическая точка инкапсуляции/декапсуляции трафика. В Docker создаётся автоматически драйвером.
- **Data Path Port** — UDP-порт для плоскости данных VXLAN (по умолчанию 4789). При конфликтах изменяется через `docker swarm init --data-path-port`.
- **Attachable** — режим overlay-сети, permitting подключение standalone-контейнеров (не сервисов Swarm).
- **Internal** — режим overlay-сети без маршрута во внешние сети; контейнеры общаются только между собой.
- **Encrypted** — режим шифрования трафика между узлами через IPsec (протокол 50 ESP).
- **Secure by Default** — политика Docker Engine 28.x+, блокирующая трафик к неопубликованным портам на уровне ядра.
- **nftables** — фреймворк файревола, используемый Docker Engine 29.x для фильтрации трафика.
- **IPVS (IP Virtual Server)** — механизм балансировки L4 в ядре Linux, используемый Swarm Routing Mesh для VIP. Подробнее: [IPVS](../../../Kubernetes/Networking/Network/CNI/ipvs.md).

## Архитектура и принцип работы

### Уровни взаимодействия

Драйвер `overlay` работает на трёх уровнях:

1. **Уровень хоста (Host Level):** Docker Daemon управляет локальными VXLAN-интерфейсами через `ip link add type vxlan`. На каждом узле создаётся пара интерфейсов: `vxlan<id>` (данные) и виртуальный мост для overlay-сети.
2. **Уровень кластера (Cluster Level):** SwarmKit координирует состояние overlay-сетей через gossip-протокол (UDP 7946). Конфигурация сети реплицируется на все менеджеры.
3. **Уровень инкапсуляции (Encapsulation Level):** Трафик между узлами упаковывается в VXLAN (UDP 4789) и передаётся через underlay-сеть.

### Поток пакета

```
Контейнер A (узел 1) → veth → OVS/docker bridge → VTEP (VXLAN инкапсуляция) → UDP 4789 → Underlay L3 → VTEP (декапсуляция) → Контейнер B (узел 2)
```

**Что происходит при создании overlay-сети:**
1. Docker создаёт VXLAN-интерфейс на каждом узле кластера через `ip link add type vxlan`.
2. Интерфейс добавляется в локальный мост overlay-сети.
3. Для каждого контейнера создаётся `veth`-пара, один конец попадает в namespace контейнера, другой — в мост.
4. При передаче трафика между узлами драйвер инкапсулирует кадр в VXLAN и отправляет через UDP 4789.

### Параметры создания overlay-сети

| Параметр | Описание | По умолчанию |
|:---|:---|:---|
| `--driver overlay` | Создаёт overlay-сеть | — |
| `--attachable` | Разрешает подключение standalone-контейнеров | `false` |
| `--internal` | Блокирует выход во внешнюю сеть | `false` |
| `--opt encrypted` | Шифрует трафик между узлами (IPsec) | `false` |
| `--opt com.docker.network.driver.mtu=<N>` | MTU overlay-сети | `1450` при физическом MTU 1500 |
| `--opt encrypted` | Включает IPsec шифрование | `false` |

**Важно:** Overlay-сеть требует активированного Swarm-режима (`docker swarm init` или `docker swarm join`). Без Swarm создание завершится ошибкой.

## Практические сценарии

### Сценарий 1: Создание базовой overlay-сети

Используется для связи сервисов на разных узлах Swarm.

```bash
docker network create \
  --driver overlay \
  --attachable \
  backend-net
```

Валидация:
```bash
docker network ls --filter driver=overlay
# → NAME        DRIVER   SCOPE
# → backend-net overlay  swarm

docker network inspect backend-net -f '{{.Driver}}'
# → overlay
```

Очистка:
```bash
docker network rm backend-net
```

### Сценарий 2: Создание overlay-сети с шифрованием и оптимизированным MTU

Для передачи чувствительных данных между узлами.

```bash
docker network create \
  --driver overlay \
  --opt com.docker.network.driver.mtu=1450 \
  --opt encrypted \
  --attachable \
  secure-net
```

Валидация:
```bash
docker network inspect secure-net
# → Ищите "MTU": 1450 и "Options": {"encrypted": "true"}

# Проверка шифрования на уровне ядра
sudo ip xfrm state
# → Должны отображаться IPsec SA (Security Associations)
```

Очистка:
```bash
docker network rm secure-net
```

### Сценарий 3: Внутренняя overlay-сеть (без выхода в интернет)

Для изоляции баз данных и внутренних сервисов.

```bash
docker network create \
  --driver overlay \
  --internal \
  db-net
```

Валидация:
```bash
docker run --rm --network db-net alpine wget -O- http://example.com
# → Таймаут (нет маршрута в интернет)

docker run --rm --network db-net alpine nslookup redis
# → Должен резолвить имя сервиса внутри кластера
```

Очистка:
```bash
docker network rm db-net
```

### Сценарий 4: Подключение standalone-контейнера к overlay-сети

Для отладки или одноразовых задач.

```bash
docker network create \
  --driver overlay \
  --attachable \
  debug-net
```

```bash
docker run --rm -it --network debug-net alpine sh
```

Валидация:
```bash
# Внутри контейнера:
nslookup <service-name>
# → Должен резолвить VIP сервиса Swarm

ping <container-ip>
# → Должен проходить
```

Очистка:
```bash
docker network rm debug-net
```

### Сценарий 5: Захват трафика на VXLAN-интерфейсе

Диагностика overlay-сети с использованием tcpdump.

```bash
# Создание overlay-сети
docker network create --driver overlay --attachable capture-net
```

Валидация:
```bash
# Поиск VXLAN-интерфейса на узле
ip -brief link show type vxlan
# → vxlan100 ...

# Захват трафика на VXLAN-интерфейсе
sudo tcpdump -i vxlan100 -c 20 -nn port 4789
# → Захватит VXLAN-пакеты между узлами

# Или через namespace контейнера
PID=$(docker inspect -f '{{.State.Pid}}' <container>)
sudo nsenter -t $PID -n tcpdump -i any -c 10
# → Захватит трафик из namespace контейнера
```

Очистка:
```bash
docker network rm capture-net
```

### Сценарий 6: Диагностика производительности overlay-сети

Замер latency и throughput между узлами.

```bash
docker network create --driver overlay --attachable perf-net
```

```bash
# Запуск iperf3-сервера как сервис Swarm
docker service create --name iperf-server --network perf-net \
  --publish published=5201,target=5201,protocol=udp \
  netstatic/iperf3 -s
```

Валидация:
```bash
# Замер throughput с другого узла
docker run --rm --network perf-net netstatic/iperf3 -c <server-ip> -u -b 0
# → Должен показать высокую скорость (>10 Гбит/с в зависимости от underlay)

# Замер latency
docker exec <container> ping -c 10 <remote-container-ip>
# → Должен показать минимальную задержку (<1 мс в пределах дата-центра)
```

Очистка:
```bash
docker service rm iperf-server
docker network rm perf-net
```

## Устранение неисправностей

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `network overlay is not compatible with network host` | Попытка использования overlay без Swarm | Активируйте Swarm: `docker swarm init` |
| `no VIP available` | Отсутствие свободных VIP в подсети | Увеличьте подсеть или очистите неиспользуемые сети |
| `service not reachable from other nodes` | VXLAN-трафик блокируется файреволом | Откройте UDP 4789 между узлами |
| `MTU is too large` | MTU overlay > underlay MTU | Установите MTU 1450 на overlay-сети |
| `gossip: conflict` | Конфликт версий конфигурации между менеджерами | Проверьте синхронность часов (NTP) и доступность менеджеров |
| `encryption: protocol 50 blocked` | ESP (IPsec) блокируется файреволом | Откройте protocol 50 между VTEP |
| `cannot connect to service` | DNS не резолvit имя сервиса | Проверьте встроенный DNS: `docker run --rm alpine nslookup <service>` |
| `overhead: tcpdump shows no VXLAN traffic` | VXLAN offloading на NIC | Отключите offload: `ethtool -K eth0 tx-udp-tnl-segmentation off` |

### Диагностика

- **Проверка VXLAN-интерфейсов**: `ip -brief link show type vxlan` — список созданных туннелей.
- **Проверка VTEP**: `bridge fdb show dev vxlan<id>` — таблица MAC-адресов удалённых узлов.
- **Проверка маршрутов**: `ip route show table 0` — наличие маршрутов до подсетей overlay.
- **Проверка MTU**: `ip link show vxlan<id>` — MTU должен быть 1450 (при физическом 1500).
- **Захват VXLAN-трафика**: `tcpdump -i eth0 udp port 4789 -nn` — трафик между узлами.
- **Проверка gossip**: `docker node ls` — все узлы должны быть в статусе `Ready`.
- **Проверка IPVS**: `nsenter --net=/var/run/docker/netns/ingress_sbox ipvsadm -Ln` — балансировщик Routing Mesh.
- **Логи демона**: `journalctl -u docker` — ошибки инициализации overlay-интерфейсов.
- **Проверка DNS**: `docker run --rm alpine nslookup <service-name>` — резолвинг имён сервисов.
- **Проверка encryption**: `sudo ip xfrm state` — активные IPsec Security Associations.

## Рекомендации

### Безопасность

- **Шифрование**: Используйте `--opt encrypted` для передачи чувствительных данных между узлами. Шифрование добавляет ~5% overhead благодаря AES-NI.
- **Firewall**: Открывайте только необходимые порты между узлами: 2377/TCP, 7946/TCP+UDP, 4789/UDP, 50 (ESP при шифровании).
- **Изоляция**: Используйте `--internal` для backend-сетей без выхода в интернет. Разделяйте фронтенд и бэкенд на разные overlay-сети.
- **Secure by Default**: Docker Engine 28.x+ блокирует неопубликованные порты автоматически. Не отключайте это поведение без необходимости.
- **MAC flapping**: При проблемах с MAC-адресами проверьте FDB: `bridge fdb show`.

### Производительность

- **MTU**: Устанавливайте MTU 1450 при стандартном физическом MTU 1500. При Jumbo Frames (9000) overlay может использовать 1500 или выше.
- **VXLAN Offloading**: Включайте `tx-udp-tnl-segmentation` на NIC для аппаратной инкапсуляции: `ethtool -K eth0 tx-udp-tnl-segmentation on`.
- **Data Path Address**: Для кластеров >10 узлов настраивайте `docker swarm init --data-path-addr` для отделения VXLAN-трафика от gossip.
- **Количество сетей**: При >500 overlay-сетях gossip создаёт нагрузку на Control Plane. Группируйте сервисы в общие сети.
- **Rootless Docker**: сетевой доступ в rootless-режиме обеспечивается драйвером RootlessKit, а не самим overlay. С 29.5 дефолтом является `gvisor-tap-vsock`. Подробно — «[Rootless: сетевой стек](../docker_network.md#rootless-сетевой-стек)».

### Управление жизненным циклом

- **Проверяйте порты** перед созданием кластера: `nc -zvu <node-ip> 4789`.
- **Не переименовывайте** VXLAN-интерфейсы вручную — Docker управляет ими автоматически.
- **Config-from**: Используйте `--config-from` в Swarm для macvlan/ipvlan вместо дублирования IPAM.
- **Очистка**: Overlay-сети не удаляются автоматически. Используйте `docker network prune --filter "until=24h"` с осторожностью.

### Отладка

- **Используйте Go-шаблоны** для `docker inspect`: `docker inspect -f '{{.NetworkSettings.Networks}}' <container>`.
- **Для захвата трафика** используйте `tcpdump` на VXLAN-интерфейсе или родительском NIC. [tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)
- **Мониторинг throughput**: Используйте `iperf3` для замера скорости между узлами. [iperf3](../../../Linux/Diagnostics/Networking/iperf3.md)
- **Проверяйте MAC-адреса**: `bridge fdb show dev vxlan<id>` — убедитесь, что MAC-адреса удалённых узлов присутствуют.

## Особенности и ограничения

### Драйверы

- **overlay**: Требует активированного Swarm-режима. Без Swarm создание сети завершится ошибкой.
- **bridge**: Для сравнения см. [bridge.md](./bridge.md).

### Переименование и удаление

- Docker CLI **не поддерживает** команду `rename` для overlay-сетей. Для изменения имени удалите сеть (`docker network rm`) и создайте новую.
- Удаление overlay-сети (`docker network rm`) возможно только если к ней **не подключены сервисы**.

### Конфликты и пересечения

- Docker проверяет пересечение подсетей **только внутри своего демона**. Он не знает о внешних маршрутах хоста, существующих VLAN или маршрутах, добавленных вручную.
- Убедитесь, что подсеть overlay-сети не конфликтует с существующими сетями хоста.

### Ограничения режимов

- **encrypted**: Не поддерживается на Windows-узлах до версии Server 2025.
- **attachable**: Каждый attachable контейнер увеличивает нагрузку на VXLAN. Используйте только для отладки.
- **internal**: Нет маршрута во внешние сети. Подходит только для изолированных backend-компонентов.

### Windows-узлы

- Overlay-сети работают, но с ограничениями производительности.
- Шифрование `--opt encrypted` не поддерживается.
- Для Windows используйте `mode: host` для критически важных сервисов.

### Имена сетей

- Имя сети может содержать только буквы (a-z, A-Z), цифры (0-9), знаки подчёркивания (`_`), точки (`.`) и дефисы (`-`).
- Имена чувствительны к регистру.
- Длина имени: от 1 до 63 символов.

### Публичные сети

- Overlay не является драйвером `host` или `none`. Контейнеры получают изолированное сетевое пространство, но с доступом к физической сети через VXLAN.
- Routing Mesh выполняет SNAT, из-за чего приложение видит IP `docker_gwbridge` вместо реального IP клиента.

## Дополнительная информация

### Производительность и MTU

- **MTU**: VXLAN добавляет 50 байт оверхеда. При физическом MTU 1500 используйте MTU 1450. При Jumbo Frames (9000) overlay может использовать 1500 или выше.
- **BIG TCP (Linux 6.8+)**: Для пакетов > 4096 байт требуется поддержка ядром и включенный BIG TCP.
- **Анализ интерфейса**: `ethtool -S <vxlan_iface>` — статистика пакетов и ошибок.

### Интеграция с CNI и orchestrators

- **Kubernetes**: Docker не является стандартным runtime для Kubernetes, но overlay-механизм аналогичен CNI. Для production Kubernetes используйте Cilium с eBPF вместо VXLAN. [Cilium](../../../Kubernetes/Networking/Network/CNI/cilium.md)
- **IPVS**: В Docker Swarm Routing Mesh использует IPVS для балансировки. Для overlay-сетей VIP балансировка работает через IPVS. [IPVS](../../../Kubernetes/Networking/Network/CNI/ipvs.md)
- **Rootless Docker**: overlay работает в rootless-режиме, но весь сетевой стек остаётся userspace. С 29.5 дефолтный драйвер — `gvisor-tap-vsock`. Подробно — «[Rootless: сетевой стек](../docker_network.md#rootless-сетевой-стек)».
- **eBPF**: Для максимальной производительности рассмотрите XDP-программы для обработки пакетов на раннем этапе. [eBPF в Linux](../../../Linux/Core/kernel/ebpf.md)

**Смотрите также:**
- [Обзор сетевых моделей Docker](../docker_network.md)
- [Docker Swarm: Сетевое взаимодействие](../../../Docker_swarm/swarm_networking.md)
- [VXLAN (Virtual Extensible LAN)](../../../Networking/Tunnels/vxlan.md)
- [Диагностика сетевых проблем](../../Docker_troubleshooting/network_connectivity_issues.md)
- [Сетевая политика Docker (Docker Network Policies)](../docker_network_policies.md)
- [Настройка демона Docker](../../../Docker/docker_daemon_config.md)
- [eBPF в Linux](../../../Linux/Core/kernel/ebpf.md)
- [Cilium](../../../Kubernetes/Networking/Network/CNI/cilium.md)
- [IPVS](../../../Kubernetes/Networking/Network/CNI/ipvs.md)
- [iperf3](../../../Linux/Diagnostics/Networking/iperf3.md)
- [tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)
