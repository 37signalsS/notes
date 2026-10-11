# Сетевой драйвер macvlan

**Актуально для:** Docker Engine 29.x

## Определения

- **Драйвер macvlan** — высокопроизводительный сетевой драйвер Docker, позволяющий назначать каждому контейнеру уникальный MAC-адрес. Контейнер становится полноценным узлом физической сети, видимым для коммутаторов и роутеров как отдельное устройство.
- **Parent Interface (Родительский интерфейс)** — физический или виртуальный сетевой интерфейс хоста (например, `eth0`, `bond0`, `ens192`), на базе которого создаются macvlan-интерфейсы для контейнеров.
- **Promiscuous Mode (Смешанный режим)** — режим работы сетевой карты, при котором она принимает все пакеты независимо от адресата. Требуется для корректной работы `macvlan` на виртуальных машинах и некоторых коммутаторах.
- **IPAM (IP Address Management)** — механизм распределения IP-адресов в Docker-сетях. Для macvlan требуется статическое назначение или внешний IPAM-контроллер.
- **Mode L2/L3/L3S** — режимы работы macvlan: L2 (bridge — программный коммутатор), VEPA (hairpin на физическом коммутаторе), private (полная изоляция), passthru (весь интерфейс контейнеру).
- **nftables** — современный фреймворк фильтрации пакетов в Linux, заменяющий iptables. Docker Engine 29.x использует nftables по умолчанию.

## Основные концепции

### Архитектура и принцип работы

Драйвер `macvlan` создает виртуальные интерфейсы с уникальными MAC-адресами на базе родительского интерфейса хоста. Каждый контейнер получает свой MAC, что делает его видимым в сети как отдельное устройство.

**Что происходит при запуске:**
1. Docker создает пару `macvlan` (родительский + дочерний интерфейс) на хосте через `ip link add`.
2. Контейнер подключается к дочернему интерфейсу и получает MAC и IP из заданной подсети.
3. Трафик контейнера выходит в сеть с уникальным MAC и собственным IP-адресом контейнера.
4. В режиме `bridge` контейнеры на одном хосте обмениваются данными через программный коммутатор, минуя физический NIC.

**Поток пакета в режиме bridge (по умолчанию):**
```
Контейнер A (MAC=A, IP=A) → macvlan-интерфейс → Программный коммутатор → Контейнер B (MAC=B, IP=B)
```
- Трафик между контейнерами на одном хосте не покидает хост.
- Внешний трафик выходит через родительский интерфейс с уникальным MAC контейнера.

### Режимы работы

При создании сети можно указать режим через `-o macvlan_mode=`:

1. **`bridge` (по умолчанию)**:
   - Контейнеры на одном хосте обмениваются данными через внутренний программный коммутатор.
   - **Преимущество**: Минимальная задержка для локального трафика.
   - **Применение**: Стандартный режим для L2-сетей с высокой плотностью контейнеров.

2. **`vepa` (Virtual Ethernet Port Aggregator)**:
   - Весь трафик отправляется на физический коммутатор, даже между контейнерами одного хоста.
   - **Требование**: Коммутатор должен поддерживать "hairpin" (отражение трафика от порта к порту).
   - **Применение**: Среды с централизованной политикой безопасности на коммутаторе.

3. **`private`**:
   - Контейнеры на одном хосте полностью изолированы друг от друга, даже если находятся в одной подсети.
   - **Преимущество**: Максимальная изоляция без дополнительных правил iptables/nftables.
   - **Применение**: Многоквантовые (multi-tenant) среды, где изоляция критична.

4. **`passthru`**:
   - Весь физический интерфейс отдается одному контейнеру.
   - **Преимущество**: Максимальная производительность, прямой доступ к NIC.
   - **Ограничение**: Интерфейс недоступен хосту и другим контейнерам.
   - **Применение**: Сетевые appliances (VPN, шлюзы), VNF с требованием к низкой задержке.

### Производительность и технологии

В современных ядрах Linux (6.x+) и Docker Engine 29.x `macvlan` поддерживает:

- **XDP (eXpress Data Path)**: Обработка пакетов на раннем этапе сетевого стека с минимальной задержкой. Доступно через eBPF-программы. [eBPF в Linux](../../../Linux/Core/kernel/ebpf.md)
- **BIG TCP (Linux 6.8+)**: Поддержка пакетов до 512 КБ, снижающая нагрузку на CPU при передаче больших объемов данных.
- **Hardware GRO (Generic Receive Offload)**: Агрегация приходящих пакетов на уровне NIC, позволяет достигать скорости 100+ Гбит/с.
- **Zero-copy**: Минимальное копирование данных между пространствами ядра, снижающее задержку.

### Сравнение с [ipvlan](./ipvlan.md)

| Характеристика | macvlan | [ipvlan](./ipvlan.md) |
| :--- | :--- | :--- |
| **MAC-адрес** | Уникальный для каждого контейнера | Общий (MAC-адрес хоста) |
| **Уровень OSI** | L2 (Ethernet) | L2 или L3 (IP) |
| **Совместимость** | Низкая (блокируется Wi-Fi и Port Security) | Высокая (Wi-Fi, on-prem) |
| **Связь Хост-Контейнер** | Требует sub-interface (shim) | Нативная в L3/L3S |
| **Масштабируемость** | Ограничена CAM-таблицей коммутатора | Экстремальная (тысячи узлов) |
| **Promiscuous Mode** | Требуется на гипервизорах | Обычно не требуется |
| **DHCP** | Полноценная поддержка | Ограничен (требует Relay) |

**Рекомендация**: Используйте `macvlan`, если вашим приложениям критически важны уникальные MAC-адреса (лицензирование, DHCP-резервации, легаси-мониторинг). В остальных случаях, особенно при высокой плотности контейнеров или использовании Wi-Fi, используйте **[ipvlan](./ipvlan.md)**.

### Взаимодействие со Swarm и Compose

- **Docker Compose**: Драйвер `macvlan` поддерживается через `driver: macvlan` и `driver_opts`.
- **Docker Swarm**: Для многохостовых конфигураций используйте config-only сети с `--config-from` для избежания дублирования IPAM-параметров.
- **Важно**: В Swarm macvlan требует предварительного создания родительского интерфейса на каждом узле кластера и настройки promiscuous mode.

## Практические сценарии

### Сценарий 1: Создание сети и запуск контейнера

Используется для legacy-приложений, требующих уникального MAC.

```bash
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  -o macvlan_mode=bridge \
  my_macvlan_net
```

```bash
docker run -d --name legacy-app \
  --network my_macvlan_net \
  --ip 192.168.1.55 \
  nginx:alpine
```

Валидация:
```bash
docker network inspect my_macvlan_net -f '{{.Driver}}'
# → macvlan

docker network inspect my_macvlan_net -f '{{.Options.macvlan_mode}}'
# → bridge

# Проверка MAC контейнера
docker exec legacy-app cat /sys/class/net/eth0/address
# → Должен показать уникальный MAC, отличный от MAC хоста
```

Очистка:
```bash
docker rm -f legacy-app
docker network rm my_macvlan_net
```

### Сценарий 2: Конфигурация через Docker Compose

Пример развертывания сервиса с прямым доступом в сеть.

```yaml
services:
  app:
    image: my-legacy-app:latest
    networks:
      public_net:
        ipv4_address: 192.168.1.55

networks:
  public_net:
    driver: macvlan
    driver_opts:
      parent: eth0
      macvlan_mode: bridge
    ipam:
      config:
        - subnet: 192.168.1.0/24
          gateway: 192.168.1.1
```

Валидация:
```bash
docker compose up -d
# → Создан сервис app

docker compose ps
# → app running

# Проверка IP и MAC контейнера
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container>
# → 192.168.1.55
```

Очистка:
```bash
docker compose down
```

### Сценарий 3: Режим `private` для изоляции контейнеров

Контейнеры на одном хосте не могут общаться напрямую.

```bash
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  -o macvlan_mode=private \
  private_net
```

Валидация:
```bash
# Запуск двух контейнеров
docker run -d --name container1 --network private_net alpine sleep 3600
docker run -d --name container2 --network private_net alpine sleep 3600

# Проверка изоляции
docker exec container1 ping -c 3 192.168.1.2
# → Должен получить 100% packet loss (контейнеры изолированы)
```

Очистка:
```bash
docker rm -f container1 container2
docker network rm private_net
```

### Сценарий 4: Режим `passthru` для сетевого appliance

Весь физический интерфейс отдается одному контейнеру.

```bash
docker network create -d macvlan \
  -o parent=eth0 \
  -o macvlan_mode=passthru \
  passthru_net
```

```bash
docker run -d --name vpn-gateway \
  --network passthru_net \
  --cap-add NET_ADMIN \
  my-vpn-image:latest
```

Валидация:
```bash
# Проверка, что контейнер видит физический интерфейс
docker exec vpn-gateway ip link show eth0
# → Должен показать, что eth0 принадлежит контейнеру
```

Очистка:
```bash
docker rm -f vpn-gateway
docker network rm passthru_net
```

### Сценарий 5: Диагностика производительности

Замер latency и throughput между контейнерами.

```bash
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  -o macvlan_mode=bridge \
  perf_net
```

```bash
docker run -d --name container1 --network perf_net alpine sleep 3600
docker run -d --name container2 --network perf_net alpine sleep 3600
```

Валидация:
```bash
# Замер latency
docker exec container1 ping -c 10 192.168.1.3
# → Должен показать минимальную задержку (<1 мс)

# Замер throughput с iperf3
docker run -d --name iperf-server --network perf_net \
  netstatic/iperf3 -s
docker run --rm --network perf_net netstatic/iperf3 -c <server-ip>
# → Должен показать высокую скорость (>10 Гбит/с в зависимости от NIC)
```

Очистка:
```bash
docker rm -f container1 container2 iperf-server
docker network rm perf_net
```

### Сценарий 6: Захват трафика на macvlan-интерфейсе

Диагностика с использованием tcpdump.

```bash
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  -o macvlan_mode=bridge \
  capture_net
```

```bash
docker run -d --name web --network capture_net nginx:alpine
```

Валидация:
```bash
# Захват трафика на хосте
sudo tcpdump -i macvlan0 -c 20
# → Захватит 20 пакетов с macvlan-интерфейса

# Или через nsenter
PID=$(docker inspect -f '{{.State.Pid}}' web)
sudo nsenter -t $PID -n tcpdump -i any -c 10
# → Захватит 10 пакетов из namespace контейнера
```

Очистка:
```bash
docker rm -f web
docker network rm capture_net
```

## Устранение неисправностей

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Cannot find device "eth0"` | Родительский интерфейс не существует на хосте | Проверьте `ip link show` и укажите корректный интерфейс |
| `network macvlan_net is not compatible with network host` | Попытка подключения host-сети к macvlan | Используйте `--network macvlan_net` или создайте отдельный контейнер |
| `Address already in use` | IP-адрес конфликтует с существующим интерфейсом | Проверьте `ip addr show` и используйте свободный IP |
| `RTNETLINK answers: File exists` | Интерфейс уже создан | Удалите старый интерфейс: `sudo ip link delete <iface>` |
| `operation not permitted` | Недостаточно прав для создания интерфейса | Запустите Docker с необходимыми capabilities или проверьте SELinux/AppArmor |
| `No DHCP offered` | DHCP работает только в режиме bridge | Используйте статический IP или режим `bridge` |
| `ping: bad address` | Неверный формат IP или подсети | Проверьте CIDR в `docker network create` |
| `Container cannot reach gateway` | Отсутствует маршрут до шлюза | Добавьте маршрут: `sudo ip route add <subnet> via <gateway> dev <parent>` |

### Диагностика

- **Проверка родительского интерфейса**: `ip link show <parent>` — интерфейс должен существовать и быть UP.
- **Проверка macvlan-интерфейсов**: `ip -brief link show type macvlan` — список созданных интерфейсов.
- **Проверка MAC-адресов**: `ip -brief link show` — убедитесь, что у каждого контейнера уникальный MAC.
- **Проверка маршрутов**: `ip route show` — убедитесь, что есть маршрут до подсети контейнеров.
- **Проверка ARP**: В режиме `bridge` ARP-запросы между контейнерами работают. `arp -a` должен показывать контейнеры.
- **Проверка nftables**: `sudo nft list ruleset` — убедитесь, что нет блокирующих правил для трафика контейнеров.
- **Логи демона**: `journalctl -u docker` — ошибки инициализации сети.
- **Capturing трафика**: `tcpdump -i <parent>` или `tcpdump -i <macvlan_iface>` для захвата трафика.

## Рекомендации

### Безопасность

- **Изоляция**: В режиме `bridge` контейнеры на одном хосте могут общаться напрямую. Используйте режим `private`, если изоляция критична.
- **Политики**: В Docker Swarm используйте Network Policies для ограничения коммуникации между сервисами. Для на-prem сред Cilium может обеспечивать L7-политики. [Cilium](../../../Kubernetes/Networking/Network/CNI/cilium.md)
- **MAC-адрес**: Уникальные MAC-адреса позволяют использовать MAC-based аутентификацию, но требуют настройки Port Security на коммутаторах.
- **ARP Spoofing**: В режиме `bridge` контейнеры могут атаковать друг друга через ARP. Настраивайте `nftables` для фильтрации ARP-трафика.
- **MAC Exhaustion**: Злоумышленник может попытаться занять все MAC-адреса на порту коммутатора. Настраивайте `Port Security` на физическом оборудовании.
- **SELinux/AppArmor**: Профили безопасности применяются, но не compensate за отсутствие L2-изоляции между контейнерами.

### Производительность

- **XDP/eBPF**: Для максимальной производительности рассмотрите XDP-программы для обработки пакетов на раннем этапе. [eBPF в Linux](../../../Linux/Core/kernel/ebpf.md)
- **Выбор режима**: `bridge` исключает лишний трафик с NIC; используйте `private` для максимальной изоляции без потерь производительности.
- **NIC Offload**: Убедитесь, что Hardware GRO/GSO включены на NIC: `ethtool -k <parent>`.
- **Для высоконагруженных сервисов** macvlan обеспечивает производительность, близкую к нативной, минуя bridge и NAT.

### Управление жизненным циклом

- **Проверяйте родительский интерфейс** перед созданием сети: `ip link show <parent>`.
- **Не переименовывайте** родительский интерфейс без обновления конфигурации сети Docker.
- **Используйте `--config-from`** в Swarm для macvlan/ipvlan вместо дублирования параметров IPAM.
- **Удаление сети** возможно только если к ней не подключены контейнеры. Принудительное отключение: `docker network disconnect -f <network> <container>`.
- **Promiscuous Mode на гипервизорах**: Для VMware ESXi, VirtualBox, Proxmox/KVM требуется отдельная настройка (см. раздел "Настройка Promiscuous Mode").

### Отладка

- **Используйте Go-шаблоны** для `docker inspect`: `docker inspect -f '{{.NetworkSettings.Networks}}' <container>`.
- **Для захвата трафика** используйте `tcpdump` или `tshark` на родительском интерфейсе. [tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)
- **Проверяйте DNS**: В режиме `bridge` встроенный DNS работает как в пользовательских bridge-сетях.
- **Мониторинг throughput**: Используйте `iperf3` для замера скорости между хостами. [iperf3](../../../Linux/Diagnostics/Networking/iperf3.md)
- **Проверка MAC-адресов**: Убедитесь, что у каждого контейнера уникальный MAC, отличный от MAC хоста.

## Особенности и ограничения

### Драйверы

- **macvlan**: Флаги `--ip` и `--alias` работают только если IP находится в пределах подсети сети.
- **ipvlan**: Для сравнения и ограничений см. [ipvlan.md](./ipvlan.md).

### Переименование и удаление

- Docker CLI **не поддерживает** команду `rename` для сетей. Для изменения имени удалите сеть (`docker network rm`) и создайте новую.
- Удаление сети (`docker network rm`) возможно только если к ней **не подключены контейнеры**.

### Конфликты и пересечения

- Docker проверяет пересечение подсетей **только внутри своего демона**. Он не знает о внешних маршрутах хоста, существующих VLAN или маршрутах, добавленных вручную.
- В режиме `bridge` убедитесь, что подсеть macvlan не конфликтует с существующими сетями хоста.

### Ограничения режимов

- **bridge**: Зависит от ARP; подходит для большинства сценариев, но не обеспечивает изоляцию между контейнерами.
- **vepa**: Требует поддержки hairpin на коммутаторе; не все коммутаторы поддерживают.
- **private**: Полная изоляция между контейнерами на хосте; нет локального трафика.
- **passthru**: Весь интерфейс отдан контейнеру; хост теряет доступ к NIC.

### Wi-Fi адаптеры

- **macvlan** практически не работает с Wi-Fi (ограничение IEEE 802.11 на количество MAC на одну ассоциацию).
- Для Wi-Fi сетей используйте **[ipvlan](./ipvlan.md)** или стандартный `bridge`.

### Имена сетей

- Имя сети может содержать только буквы (a-z, A-Z), цифры (0-9), знаки подчёркивания (`_`), точки (`.`) и дефисы (`-`).
- Имена чувствительны к регистру.
- Длина имени: от 1 до 63 символов.

### Публичные сети

- macvlan не является драйвером `host` или `none`. Контейнеры получают изолированное сетевое пространство, но с доступом к физической сети через родительский интерфейс.
- В отличие от `bridge`, macvlan не выполняет NAT. Контейнеры видны в сети напрямую.

## Дополнительная информация

### Настройка Promiscuous Mode на гипервизорах

Если Docker запущен внутри виртуальной машины, необходимо разрешить смешанный режим на уровне гипервизора:
- **VMware ESXi**: Настройки vSwitch или Port Group → Security → Promiscuous Mode: **Accept**.
- **VirtualBox**: Settings → Network → Advanced → Promiscuous Mode: **Allow All**.
- **Proxmox/KVM**: По умолчанию мосты Linux поддерживают это, но для специфичных карт может потребоваться `ip link set eth0 promisc on`.

### Производительность и MTU

- **MTU**: macvlan наследует MTU родительского интерфейса. При использовании инкапсуляции (VXLAN, GRE) убедитесь, что MTU уменьшен соответствующим образом.
- **BIG TCP**: Для пакетов > 4096 байт требуется поддержка ядром Linux 6.8+ и включенный BIG TCP на родительском интерфейсе.
- **Анализ интерфейса**: `ethtool -S <macvlan_iface>` — статистика пакетов и ошибок.

### Интеграция с CNI и orchestrators

- **Kubernetes**: Docker не является стандартным runtime для Kubernetes, но macvlan может использоваться в Cilium в режиме `--macvlan`. [Cilium](../../../Kubernetes/Networking/Network/CNI/cilium.md)
- **IPVS**: В Docker Swarm Routing Mesh использует IPVS для балансировки. Для macvlan-сетей VIP балансировка работает через IPVS. [IPVS](../../../Kubernetes/Networking/Network/CNI/ipvs.md)
- **Rootless Docker**: macvlan поддерживается, но требует настройки `netlink` capabilities в rootless-режиме.

**Смотрите также:**
- [Обзор сетевых моделей Docker](../docker_network.md)
- [Сетевой драйвер ipvlan](./ipvlan.md)
- [Диагностика сетевых проблем](../../Docker_troubleshooting/network_connectivity_issues.md)
- [Сетевая политика Docker (Docker Network Policies)](../docker_network_policies.md)
- [Настройка демона Docker](../../../Docker/docker_daemon_config.md)
- [Docker Swarm: Сетевое взаимодействие](../../../Docker_swarm/swarm_networking.md)
- [eBPF в Linux](../../../Linux/Core/kernel/ebpf.md)
- [Cilium](../../../Kubernetes/Networking/Network/CNI/cilium.md)
- [IPVS](../../../Kubernetes/Networking/Network/CNI/ipvs.md)
- [iperf3](../../../Linux/Diagnostics/Networking/iperf3.md)
- [tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)
