## Определения

- **Containerlab**: Open-source инструмент для создания lab environments с помощью Docker containers. Позволяет эмулировать сетевые устройства (Cisco, Juniper, Arista, Linux, OVS, FRR) в изолированной среде для testing и development.
- **Lab Topology**: Описание lab environment (devices, links, addresses) в YAML-формате (containerlab format). Определяет topology, connectivity,配置 management.
- **Network Emulator**: Инструмент для эмуляции сетевого оборудования (EVE-NG, GNS3, Containerlab). Использует Docker containers или VM для запуска реальных NOS.
- **Docker Container**: Изолированный процесс с собственным network namespace. В Containerlab используется для эмуляции network devices.
- **cFMD (Container Fabric Management Daemon)**: Демон в Containerlab, управляющий lifecycle containers (start, stop, restart) и их network connectivity.
- **bind mount**: Механизм Docker для монтирования host files/directories в container. Используется для загрузки конфигов в lab devices.
- **clab**: CLI command для Containerlab. Основные операции: `clab deploy`, `clab destroy`, `clab inspect`, `clab graph`.
- **Linux bridge**: Виртуальный L2 bridge в Linux. Используется в Containerlab для connecting containers.
- **veth pair**: Виртуальная пара интерфейсов (аналог crossover cable). Соединяет containers в Containerlab.
- **EXABGP**: BGP daemon, используемый в Containerlab для BGP testing (lightweight, Python-based).

---

## Основные концепции

### Архитектура Containerlab

```
┌─────────────────────────────────────────────────────────────┐
│ Host (Linux/Mac/Windows)                                     │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Docker Engine                                           ││
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐              ││
│  │  │ FRR-1    │  │ OVS-1    │  │ Cisco-1  │              ││
│  │  │ (FRR)    │  │ (OVS)    │  │ (cEOS)   │              ││
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘              ││
│  │       │             │             │                      ││
│  │       └──── veth ───┴──── veth ───┘                      ││
│  │              Linux bridge / Containerlab fabric          ││
│  └─────────────────────────────────────────────────────────┘│
│                                                              │
│  clab CLI → Docker API → Container lifecycle                 │
└─────────────────────────────────────────────────────────────┘
```

### Типы lab environments

| Тип | Инструмент | Описание | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Container-based** | Containerlab, GNS3 (Docker) | Fast, lightweight, Docker containers | Network automation testing, CNI validation |
| **VM-based** | EVE-NG, GNS3 (QEMU) | Full NOS emulation (Cisco IOS, Junos) | Complex topologies, production-like testing |
| **Cloud-based** | CML (Cisco), Juniper vLabs | Vendor-provided lab environments | Certification training, vendor-specific testing |
| **Kubernetes-based** | Kind, Minikube | K8s cluster in Docker | Kubernetes CNI testing, K8s development |

### Сравнение Containerlab vs EVE-NG vs GNS3

| Критерий | Containerlab | EVE-NG | GNS3 |
| :--- | :--- | :--- | :--- |
| **Тип** | Docker containers | VMs (QEMU/Docker) | VMs (QEMU/Docker) |
| **Скорость запуска** | Очень быстрая (секунды) | Медленная (минуты) | Медленная (минуты) |
| **Ресурсы** | Низкие (CPU, RAM) | Высокие (CPU, RAM) | Средние |
| **Поддержка NOS** | Ограниченная (FRR, OVS, cEOS, SROS) | Полная (Cisco IOS, Junos, NX-OS) | Полная |
| **Topology description** | YAML (clab.yml) | Web GUI | GUI + CLI |
| **Automation-friendly** | Да (API, CLI) | Ограниченная | Ограниченная |
| **CI/CD integration** | Да (Docker, GitHub Actions) | Нет | Нет |
| **Free tier** | Полностью free | Community edition | Community edition |
| **Назначение** | Network automation testing, CNI, SDN | Enterprise lab, certification | Legacy testing |

### Типы devices в Containerlab

| Device | Image | Описание | Когда использовать |
| :--- | :--- | :--- | :--- |
| **FRRouting (FRR)** | `frrouting/frr` | Полноценный router (BGP, OSPF, IS-IS, MPLS, SRv6) | BGP/IGP testing, EVPN, SRv6 |
| **Open vSwitch (OVS)** | `openvswitch/ovs` | L2/L3 switch с OpenFlow | SDN testing, OpenFlow, VXLAN |
| **Linux (Alpine)** | `alpine:latest` | Базовый Linux с networking tools | Simple testing, traffic generation |
| **Cisco cEOS** | `ceos:latest` | Cisco IOS-XR (container version) | Cisco-specific testing |
| **Juniper vSRX** | `vSRX:latest` | Juniper firewall/router | Juniper-specific testing |
| **Arista cEOS** | `ceos:latest` | Arista EOS (container version) | Arista-specific testing |
| **Nokia SR OS** | `sros:latest` | Nokia service router | Telco testing |
| **EXABGP** | `exabgp/exabgp` | BGP daemon (lightweight) | BGP speaker for testing |
| **Microsoft SONiC** | `sonic:latest` | Software for Open Networking in the Cloud | White-box switch testing |

---

## Практические сценарии

### Сценарий 1: Установка Containerlab

```bash
# Установка (Linux)
curl -sL https://get.containerlab.dev | sudo bash

# Установка (macOS через Docker)
brew install containerlab   # Нет официального brew
# Альтернатива: использовать Docker directly
docker pull ghcr.io/srl-labs/containerlab:latest

# Проверка
clab version
# → clab version 0.58.0

# Установка Docker images для lab devices
docker pull frrouting/frr:9.1
docker pull openvswitch/ovs:latest
docker pull alpine:3.19
```

### Сценарий 2: Простой lab - 2 routers с BGP

```yaml
# lab-topology.yml
name: bgp-lab

topology:
  nodes:
    r1:
      kind: frr
      image: frrouting/frr:9.1
      binds:
        - ./configs/r1/frr.conf:/etc/frr/frr.conf:ro
      cmd: /usr/lib/frr/docker-start

    r2:
      kind: frr
      image: frrouting/frr:9.1
      binds:
        - ./configs/r2/frr.conf:/etc/frr/frr.conf:ro
      cmd: /usr/lib/frr/docker-start

  links:
    - endpoints:
        - r1:eth0
        - r2:eth0
      address:
        left: 10.0.0.1/30
        right: 10.0.0.2/30
```

```bash
# Конфигурация FRR (configs/r1/frr.conf)
cat > configs/r1/frr.conf << 'EOF'
frr defaults traditional
hostname r1
log syslog informational
no ipv6 forwarding

router bgp 65001
 bgp router-id 10.0.0.1
 neighbor 10.0.0.2 remote-as 65002
 address-family ipv4 unicast
  network 10.0.1.0/24
  neighbor 10.0.0.2 activate
 exit-address-family
EOF

cat > configs/r2/frr.conf << 'EOF'
frr defaults traditional
hostname r2
log syslog informational
no ipv6 forwarding

router bgp 65002
 bgp router-id 10.0.0.2
 neighbor 10.0.0.1 remote-as 65001
 address-family ipv4 unicast
  network 10.0.2.0/24
  neighbor 10.0.0.1 activate
 exit-address-family
EOF

# Развертывание lab
clab deploy -t lab-topology.yml
# → Applying topology...
# → Creating lab directory: clab-bgp-lab
# → Creating docker network: clab
# → Creating node: r1
# → Creating node: r2
# → Creating link: r1:eth0 <--> r2:0/eth0
# → Lab deployed successfully!

# Просмотр состояния
clab inspect -t lab-topology.yml
# → +-------+------+----------------------------------+--------+-------+---------+
# → | Name  | Kind | Image                            | State  | IPv4  | IPv6    |
# → +-------+------+----------------------------------+--------+-------+---------+
# → | r1    | frr  | frrouting/frr:9.1                | running| 172...| ...     |
# → | r2    | frr  | frrouting/frr:9.1                | running| 172...| ...     |
# → +-------+------+----------------------------------+--------+-------+---------+

# Подключение к device
docker exec -it clab-bgp-lab-r1 vtysh
# → r1# show bgp summary
# → BGP router identifier 10.0.0.1, local AS number 65001
# → Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
# → 10.0.0.2        4  65002     123     125        0    0    0 00:10:23   1

# Уничтожение lab
clab destroy -t lab-topology.yml
```

### Сценарий 3: Lab с VXLAN overlay

```yaml
# lab-topology-vxlan.yml
name: vxlan-lab

topology:
  nodes:
    spine1:
      kind: frr
      image: frrouting/frr:9.1
      binds:
        - ./configs/spine1/frr.conf:/etc/frr/frr.conf:ro

    leaf1:
      kind: frr
      image: frrouting/frr:9.1
      binds:
        - ./configs/leaf1/frr.conf:/etc/frr/frr.conf:ro

    leaf2:
      kind: frr
      image: frrouting/frr:9.1
      binds:
        - ./configs/leaf2/frr.conf:/etc/frr/frr.conf:ro

    server1:
      kind: linux
      image: alpine:3.19
      binds:
        - ./configs/server1/startup.sh:/startup.sh:ro
      cmd: sh /startup.sh

    server2:
      kind: linux
      image: alpine:3.19
      binds:
        - ./configs/server2/startup.sh:/startup.sh:ro
      cmd: sh /startup.sh

  links:
    - endpoints:
        - spine1:eth0
        - leaf1:eth0
    - endpoints:
        - spine1:eth1
        - leaf2:eth0
    - endpoints:
        - leaf1:eth1
        - server1:eth0
    - endpoints:
        - leaf2:eth1
        - server2:eth0
```

```bash
# Подключение к leaf1 и проверка VXLAN
docker exec -it clab-vxlan-lab-leaf1 vtysh
# → leaf1# show vxlan vni
# → VNI      Type    Endpoint_ip    MAC
# → 10100    L2      10.0.0.2       aa:bb:cc:dd:ee:ff

# Проверка BGP EVPN routes
# → leaf1# show bgp l2vpn evpn
# → Route Distinguisher: 10.0.0.1:100
# → *> [2]:[0]:[0]:[48]:[aa:bb:cc:dd:ee:ff]:[32]:[10.0.1.10]/224

# Ping от server1 до server2 (через VXLAN)
docker exec -it clab-vxlan-lab-server1 ping 10.0.2.10
# → PING 10.0.2.10 (10.0.2.10): 56 data bytes
# → 64 bytes from 10.0.2.10: seq=0 ttl=64 time=1.234 ms
```

### Сценарий 4: CI/CD integration с Containerlab

```yaml
# .github/workflows/lab-test.yml
name: Lab Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lab-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Containerlab
        run: |
          curl -sL https://get.containerlab.dev | sudo bash

      - name: Deploy lab
        run: |
          sudo clab deploy -t lab-topology.yml

      - name: Run tests
        run: |
          # BGP convergence test
          docker exec clab-bgp-lab-r1 vtysh -c "show bgp summary" | grep -q "Estab"
          echo "BGP convergence: OK"

          # Connectivity test
          docker exec clab-bgp-lab-r1 ping -c 3 10.0.0.2
          echo "Connectivity: OK"

      - name: Destroy lab
        if: always()
        run: |
          sudo clab destroy -t lab-topology.yml
```

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Container fails to start** | Image not found, port conflict, insufficient resources | `docker pull` image; check port availability; increase Docker resources |
| **No connectivity between containers** | veth not created, bridge not configured | Check `docker network inspect`; verify endpoints in topology |
| **FRR not starting** | Config file syntax error, permissions | Check config syntax; verify bind mount permissions |
| **Lab performance slow** | Too many containers, insufficient CPU/RAM | Reduce lab size; increase Docker resource limits |
| **Docker network issues** | Docker daemon not running, network conflict | Restart Docker; check `docker network ls` for conflicts |
| **clab deploy fails** | Invalid topology YAML, missing dependencies | Validate YAML; install required Docker images |

### Полезные команды

```bash
# Containerlab
clab deploy -t topology.yml        # Развернуть lab
clab destroy -t topology.yml       # Уничтожить lab
clab inspect -t topology.yml       # Просмотр состояния
clab graph -t topology.yml         # Визуализация topology
clab exec -t topology.yml -- cmd   # Выполнить command на всех nodes

# Docker
docker ps                          # Просмотр containers
docker exec -it <container> bash   # Подключение к container
docker logs <container>            # Просмотр логов
docker network inspect clab        # Просмотр lab network
```

---

## Дополнительная информация

**Производственные рекомендации:**
- Используйте Containerlab для CI/CD pipeline (автоматическое тестирование сетевых изменений).
- Комбинируйте Containerlab + Ansible/Nornir для automated lab testing.
- Используйте FRRouting для BGP/IGP testing (бесплатно, lightweight).
- Избегайте EVE-NG/GNS3 для CI/CD (медленные, resource-intensive).

**Связанные темы:**
- **[Network Automation](./network_automation.md)** — Ansible/Nornir + Containerlab.
- **[Network Verification](./network_verification.md)** — Batfish + Containerlab.
- **[FRRouting](./bgp_evpn.md)** — FRR для BGP/EVPN testing.
- **[OpenFlow/OVS](./openflow.md)** — OVS для SDN testing.
- **[Kubernetes CNI](./kubernetes_cni.md)** — Containerlab для CNI testing.
