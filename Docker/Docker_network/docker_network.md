# Docker: Обзор сетевых моделей

## Определения

- **Docker Networking**: Система, обеспечивающая сетевое взаимодействие контейнеров между собой, с хост-системой и внешними сетями.
- **Container Network Model (CNM)** — архитектурная спецификация Docker для организации сетевого стека. Состоит из трёх компонентов:
  - **Sandbox (Песочница)**: Изолированное сетевое окружение контейнера (интерфейсы, таблицы маршрутизации, DNS). Реализуется через **Network Namespaces** в ядре Linux.
  - **Endpoint (Конечная точка)**: Виртуальный интерфейс (обычно **veth-пара**), соединяющий Sandbox с конкретной сетью. Один эндпоинт принадлежит ровно одной сети.
  - **Network (Сеть)**: Группа эндпоинтов, которые могут взаимодействовать напрямую. Реализуется через программные коммутаторы (Linux Bridge), VXLAN-туннели или прямую маршрутизацию.
- **Service Discovery**: Механизм автоматического обнаружения сервисов в сети по их именам, реализованный через встроенный DNS-сервер Docker (127.0.0.11).

## Основные концепции

### Обзор сетевых драйверов

Выбор драйвера определяет уровень изоляции, производительность и топологию сети.

| Драйвер | Изоляция | Производительность | Сценарий использования |
| :--- | :--- | :--- | :--- |
| **[`bridge`](./drivers/bridge.md)** | Высокая | Хорошая (NAT) | Стандарт для одиночных хостов. |
| **[`host`](./drivers/host.md)** | Отсутствует | Максимальная | Высоконагруженные сервисы, отсутствие NAT. |
| **[`overlay`](./drivers/overlay.md)** | Высокая | Средняя (VXLAN) | **Docker Swarm.** Связь между разными хостами. |
| **[`macvlan`](./drivers/macvlan.md)**| Высокая (L2) | Нативная | Контейнер как физический узел (уникальный MAC). |
| **[`ipvlan`](./drivers/ipvlan.md)**| Высокая (L3) | Нативная | Альтернатива macvlan (общий MAC, разные IP). |
| **[`none`](./drivers/none.md)** | Полная | Н/Д | Отключение сети для максимальной безопасности. |

### Механизмы балансировки и Routing Mesh

В кластерном режиме (Docker Swarm) используется **Routing Mesh** — система, позволяющая любому узлу кластера принимать трафик для любого сервиса.
- **Ingress Network**: Специальная overlay-сеть для входящего трафика.
- **IPVS (IP Virtual Server)**: Технология ядра Linux, используемая Docker для балансировки нагрузки между репликами сервиса на уровне L4.

### Поддержка IPv6 (v27/v28+)

В 2026 году IPv6 в Docker работает "из коробки" при поддержке хостом.
- **Dual-Stack**: Контейнеры могут одновременно иметь IPv4 и IPv6 адреса.
- **Routed Mode**: Предпочтительный режим без NAT66, где трафик маршрутизируется напрямую, что критично для современных облачных архитектур.

### Rootless Docker и сетевой стек

В режиме без root-прав (Rootless) сетевой стек работает через **User-mode networking**.
- **slirp4netns**: Классический вариант (медленный, высокий CPU оверхед).
- **pasta / passt (v28+)**: Рекомендуемая технология. Обеспечивает почти нативную скорость (до 15-20 Гбит/с) и корректное сохранение IP-адресов отправителя без использования NAT внутри контейнера.

## Практические сценарии

### Сценарий 1: Проектирование многослойной изоляции

Разделение фронтенда и бэкенда на разные сети.

```bash
# Создание изолированных сетей
docker network create frontend-net
docker network create backend-net

# БД доступна только в backend-net
docker run -d --name pg-db --network backend-net postgres:17-alpine

# API имеет доступ к обоим слоям
docker run -d --name app-api --network frontend-net my-api:latest
docker network connect backend-net app-api

# Web видит только API
docker run -d --name web-ui --network frontend-net -p 80:80 nginx:alpine
```

### Сценарий 2: Трассировка пути пакета

Для понимания работы сети в Docker важно знать путь прохождения трафика через виртуальные интерфейсы и механизмы NAT.

1. Пакет проходит через **veth-пару**, соединяющую Network Namespace контейнера с хостом.
2. Внутри хоста пакет попадает на мост (`docker0` или кастомный).
3. Механизмы **DNAT/SNAT** в iptables/nftables обеспечивают проброс портов и выход во внешние сети.

Подробная пошаговая схема прохождения пакета (Packet Flow) с описанием всех уровней изоляции приведена в заметке **[Сетевой драйвер bridge](./drivers/bridge.md#жизненный-цикл-пакета-packet-flow)**.

## Дополнительная информация

### Безопасность: Inter-Container Connectivity (ICC)

По умолчанию все контейнеры в одной сети могут общаться (`--icc=true`). В высокозащищенных средах это рекомендуется отключать:
```bash
docker network create -o "com.docker.network.bridge.enable_icc=false" secure-bridge
```

### Взаимодействие с системным файерволом

Docker управляет правилами **iptables/nftables** автоматически.
- **Проблема**: Правила Docker часто идут ПЕРЕД правилами пользователя (например, UFW).
- **Решение**: Используйте цепочку `DOCKER-USER` для добавления своих правил фильтрации, которые Docker не затронет при обновлении.

**Смотрите также:**
- [Справочник CLI по сетям](./cli.md)
- [DNS и Service Discovery](./dns_and_service_discovery.md)
- [Устранение сетевых проблем](../Docker_troubleshooting/network_connectivity_issues.md)
- [Docker Swarm: Сетевое взаимодействие](../../../Docker_swarm/swarm_networking.md)
- **[Сетевые политики Docker](./docker_network_policies.md)** — правила фильтрации трафика, DOCKER-USER chain, нативные политики.

**Глубокое изучение:**
- **[eBPF в Linux](../../Linux/Core/kernel/ebpf.md)** — технология для XDP, TC, Cilium. В Docker: eBPF заменяет iptables для фильтрации, Cilium как CNI для Docker Swarm.
- **[Cilium](../../Kubernetes/Networking/Network/CNI/cilium.md)** — eBPF CNI, kube-proxy replacement. В Docker: microsegmentation через eBPF, L7/FQDN policies, Hubble для наблюдаемости.
- **[Traefik](../../WebServers/Traefik/traefik_overview.md)** — reverse proxy с автодискавери. В Docker: Traefik читает Docker API для маршрутизации, TLS Let's Encrypt, labels для конфигурации.
- **[IPVS](../../Kubernetes/Networking/Network/CNI/ipvs.md)** — L4 балансировка. В Docker Swarm: Routing Mesh через IPVS, VIP balancing между репликами.
- **[iperf3](../../Linux/Diagnostics/Networking/iperf3.md)** — benchmarking throughput. В Docker: `docker run netstatic/iperf3` для замера скорости между контейнерами.
- **[tcpdump](../../Linux/Diagnostics/Networking/tcpdump.md)** — захват пакетов. В Docker: `nsenter -t <PID> -n tcpdump` или `--net=host` для захвата трафика контейнера.
- **[MTU и VPN](../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — jumbo frames. В Docker: VXLAN overhead = 50 байт, MTU overlay сети = 1450 при физическом MTU 1500.
