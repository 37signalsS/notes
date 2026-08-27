# DHCP в Docker и виртуализации

---

## Определения

**DHCP в контейнерах** — запуск DHCP-сервера (Kea, dnsmasq, ISC) внутри Docker-контейнера для лабораторных, development и production-сред, где DHCP должен работать изолированно от хоста.

**libvirt DHCP** — встроенный DHCP-сервер в libvirt, автоматически выдающий IP-адреса виртуальным машинам в NAT или bridge-сетях.

**Docker macvlan/bridge** — сетевые драйверы Docker, определяющие, как контейнеры взаимодействуют с физической сетью и DHCP-серверами.

**dnsmasq** — легковесный DNS/DHCP-сервер, часто используемый в Docker-контейнерах для простых DHCP-сценариев.

---

## Основные концепции

### Сетевые режимы Docker и DHCP

| Режим | DHCP-клиент | DHCP-сервер | Использование |
| :--- | :--- | :--- | :--- |
| **bridge** (по умолчанию) | Контейнер получает IP от Docker daemon | Внутри bridge-сети | Development, тесты |
| **host** | Контейнер использует сеть хоста | DHCP-сервер хоста | Высокая производительность |
| **macvlan** | Контейнер как отдельный хост в VLAN | Физический DHCP-сервер | Production, полная изоляция |
| **none** | Нет сети | Нет | Безопасность, изоляция |

**Проблема:** Docker bridge-сеть НЕ использует DHCP (контейнеры получают IP статически от Docker daemon). Для DHCP-сервера внутри контейнера нужен **macvlan** или **host** режим.

### libvirt DHCP vs Kea/dnsmasq

| Параметр | libvirt DHCP | Kea / dnsmasq |
| :--- | :--- | :--- |
| **Управление** | `virsh net-*`, XML-конфиг | REST API / CLI |
| **Производительность** | Низкая (test/dev) | Высокая (production) |
| **Опции DHCP** | Базовые (router, DNS) | Полные (15+ опций) |
| **Relay** | Нет | Да (Kea hooks) |
| **Failover** | Нет | Да (Kea HA) |
| **DDNS** | Через virsh | Через hooks / BIND |

---

## Практические сценарии

### Kea DHCP в Docker

**Dockerfile:**

```dockerfile
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    kea-dhcp4-server \
    kea-ctrl-agent \
    curl jq \
    && rm -rf /var/lib/apt/lists/*

COPY kea-dhcp4.conf /etc/kea/kea-dhcp4.conf
COPY kea-ctrl-agent.conf /etc/kea/kea-ctrl-agent.conf

EXPOSE 67/udp 8000/tcp

CMD ["kea-dhcp4", "-c", "/etc/kea/kea-dhcp4.conf"]
```

**docker-compose.yml:**

```yaml
version: "3.8"
services:
  kea-dhcp:
    build: .
    container_name: kea-dhcp
    network_mode: macvlan   # Или host
    cap_add:
      - NET_ADMIN           # Для raw sockets
      - NET_RAW             # Для DHCP
    ports:
      - "8000:8000"         # REST API
    volumes:
      - ./kea-dhcp4.conf:/etc/kea/kea-dhcp4.conf
      - ./kea-leases:/var/lib/kea
    restart: unless-stopped
    sysctls:
      - net.ipv4.ip_forward=1
```

**Запуск:**

```bash
# Сборка и запуск
docker compose up -d

# Проверка REST API
curl -s http://localhost:8000/ | jq

# Логи
docker logs -f kea-dhcp

# Проверка портов
docker exec kea-dhcp ss -nlup | grep :67
```

### dnsmasq в Docker (простой DHCP)

**docker-compose.yml:**

```yaml
version: "3.8"
services:
  dnsmasq-dhcp:
    image: jpillora/dnsmasq:latest
    container_name: dnsmasq-dhcp
    network_mode: macvlan
    cap_add:
      - NET_ADMIN
    ports:
      - "53:53/tcp"
      - "53:53/udp"
      - "67:67/udp"
    volumes:
      - ./dnsmasq.conf:/etc/dnsmasq.conf
    restart: unless-stopped
```

**dnsmasq.conf:**

```text
# DHCP
interface=eth0
dhcp-range=10.0.10.100,10.0.10.200,255.255.255.0,12h
dhcp-option=option:router,10.0.10.1
dhcp-option=option:dns-server,10.0.0.10,10.0.0.11
dhcp-option=option:domain-name,corp.example.com

# Статические привязки
dhcp-host=00:50:56:b1:22:33,10.0.10.50,srv-db-01

# Логирование
log-queries
log-dhcp
```

**Проверка:**

```bash
# Клиент из другой сети
sudo dhclient -v eth0

# Логи dnsmasq
docker logs dnsmasq-dhcp | grep -E "DHCP|OFFER|ACK"
```

### libvirt DHCP: настройка виртуальных сетей

**NAT-сеть с DHCP:**

```bash
# Создание виртуальной сети
cat > /tmp/vm-net.xml << 'EOF'
<network>
  <name>vm-dhcp-net</name>
  <bridge name virbr1"/>
  <forward mode="nat"/>
  <ip address="10.0.100.1" netmask="255.255.255.0">
    <dhcp>
      <range start="10.0.100.100" end="10.0.100.200"/>
      <host mac="52:54:00:12:34:56" ip="10.0.100.10"/>
      <host mac="52:54:00:65:43:21" ip="10.0.100.11"/>
    </dhcp>
  </ip>
</network>
EOF

virsh net-define /tmp/vm-net.xml
virsh net-start vm-dhcp-net
virsh net-autostart vm-dhcp-net

# Проверка
virsh net-dhcp-leases vm-dhcp-net

# Запуск VM с этой сетью
virt-install --network network=vm-dhcp-net ...
```

**Bridge-сеть (VM получает IP от физического DHCP):**

```bash
cat > /tmp/vm-bridge.xml << 'EOF'
<network>
  <name>vm-bridge-net</name>
  <bridge name="br0"/>
  <forward mode="bridge"/>
</network>
EOF

virsh net-define /tmp/vm-bridge.xml
virsh net-start vm-bridge-net
```

### DHCP Relay в Docker-сети

```bash
# Запуск Kea DHCP Relay в Docker
docker run -d --name kea-relay \
  --network macvlan_net \
  --cap-add NET_ADMIN \
  kea/kea-dhcp-relay:latest \
  kea-dhcp4 -c /etc/kea/kea-dhcp4.conf \
  --interfaces eth0 \
  --server 10.0.0.10:67
```

---

## Дополнительная информация

### Типичные проблемы Docker + DHCP

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Docker bridge не пропускает DHCP** | Bridge не forward broadcast | Используйте `macvlan` или `host` |
| **Kea не запускается в контейнере** | Нет прав на raw sockets | Добавьте `cap_add: NET_RAW` |
| **DHCP-клиент не видит сервер** | Разные broadcast-домены | Используйте `macvlan` с VLAN |
| **Порт 67 уже занят** | Другой DHCP на хосте | Остановите `isc-dhcp-server` на хосте |
| **leases не сохраняются** | Volume не примонтирован | Добавьте `volumes:` в compose |

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](../../../Linux/Networking/Services/DHCP/kea_dhcp_overview.md)** — полная конфигурация Kea.
- **[Обзор DHCP](./dhcp_overview.md)** — теория DORA/SARR.
- **[DHCP Relay](./dhcp_relay.md)** — теория и практика ретрансляции.
- **[Безопасность DHCP](./dhcp_security.md)** — защита в виртуализированных средах.
- **[Docker Networking Documentation](https://docs.docker.com/engine/network/)** — сетевые драйверы Docker.
- **[libvirt Networking](https://libvirt.org/docs.html)** —official documentation.
- **[Kea DHCP Docker](https://hub.docker.com/r/isc/kea-dhcp4)** — official Docker image.
