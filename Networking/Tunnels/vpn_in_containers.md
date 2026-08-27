# VPN в контейнерах — Docker и Kubernetes

## Определения

Запуск VPN-серверов в контейнерах (Docker, Kubernetes) требует особого внимания к сетевым ограничениям: контейнеры не имеют нативного доступа к модулям ядра (TUN/TAP, WireGuard, IPsec XFRM) и сетевым пространствам имён. Данный документ описывает practical-подходы к развертыванию VPN в контейнеризированных средах.

> **См. также:** [WireGuard](./wireguard_practical.md), [OpenVPN](./openvpn.md), [Cilium WireGuard](../../Kubernetes/Networking/Network/CNI/cilium.md), [Calico WireGuard](../../Kubernetes/Security/network_policies/Calico/index.md)

---

## Docker

### WireGuard в Docker

#### Проблема

WireGuard требует:
- Модуль ядра `wireguard`
- Доступ к `/dev/net/tun`
- Сетевое пространство хоста (для маршрутизации)

#### Решение: Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  wireguard:
    image: linuxserver/wireguard
    container_name: wireguard
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/Moscow
      - SERVERURL=vpn.example.com
      - SERVERPORT=51820
      - PEERS=3  # Количество клиентов
      - PEERDNS=1.1.1.1
    volumes:
      - ./wg0-config:/config
      - /lib/modules:/lib/modules:ro
    ports:
      - 51820:51820/udp
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
      - net.ipv4.ip_forward=1
    restart: unless-stopped
```

```bash
# Запуск
docker compose up -d

# Просмотр конфигурации клиентов
docker exec wireguard cat /config/peer1/peer1.conf

# Просмотр состояния
docker exec wireguard wg show
```

#### Проблема: маршрутизация

Docker по умолчанию создает изолированную сеть. Для маршрутизации VPN-трафика:

```bash
# Добавление маршрута до VPN-подсети через Docker-сеть
sudo ip route add 10.0.0.0/24 via $(docker inspect wireguard -f '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')
```

### OpenVPN в Docker

```yaml
# docker-compose.yml
version: '3.8'

services:
  openvpn:
    image: kylemanna/openvpn
    container_name: openvpn
    cap_add:
      - NET_ADMIN
    environment:
      - OVPN_DATA=/etc/openvpn
      - OVPN_SERVER=192.168.255.0/24
      - OVPN_PROTO=udp
      - OVPN_PORT=1194
    volumes:
      - ./ovpn-data:/etc/openvpn
    ports:
      - 1194:1194/udp
    restart: unless-stopped
```

```bash
# Инициализация PKI
docker compose run --rm openvpn ovpn_genconfig -u udp://vpn.example.com -p 192.168.255.0/24
docker compose run --rm openvpn ovpn_initpki

# Запуск сервера
docker compose up -d

# Создание клиента
docker compose run --rm openvpn easyrsa build-client-full client1 nopass
docker compose run --rm openvpn ovpn_getclient client1 > client1.ovpn
```

### IPsec в Docker

```yaml
# docker-compose.yml
version: '3.8'

services:
  ipsec:
    image: hwdsl2/ipsec-vpn-server
    container_name: ipsec
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    environment:
      - VPN_IPSEC_PSK=your_pre_shared_key
      - VPN_USER=vpnuser
      - VPN_PASSWORD=your_password
      - VPN_DNS1=8.8.8.8
      - VPN_DNS2=8.8.4.4
    volumes:
      - /lib/modules:/lib/modules:ro
    ports:
      - 500:500/udp
      - 4500:4500/udp
    sysctls:
      - net.ipv4.ip_forward=1
    restart: unless-stopped
```

---

## Kubernetes

### WireGuard в Kubernetes

#### Вариант 1: Cilium с WireGuard шифрованием (рекомендуется)

Cilium поддерживает нативное шифрование WireGuard между узлами:

```bash
# Включение WireGuard шифрования в Cilium
cilium encryption enable --type wireguard

# Проверка статуса
cilium status --encryption
# → Encryption: WireGuard
# →   Node    Public Key                              ...
# →   node1   aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789=  ...
# →   node2   xYzAbCdEfGhIjKlMnOpQrStUvWxYz123456=
```

Требования:
- Ядро Linux 5.6+
- Cilium 1.10+
- WireGuard модуль загружен на всех узлах

#### Вариант 2: Calico с WireGuard шифрованием

```bash
# Включение WireGuard шифрования в Calico
calicoctl patch felixconfiguration default --type merge -p '{"spec":{"wireguardEnabled":true}}'

# Проверка
calicoctl node status
```

#### Вариант 3: Самостоятельный WireGuard DaemonSet

```yaml
# wireguard-daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: wireguard
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: wireguard
  template:
    metadata:
      labels:
        app: wireguard
    spec:
      hostNetwork: true
      tolerations:
        - operator: Exists
      containers:
        - name: wireguard
          image: linuxserver/wireguard
          securityContext:
            privileged: true
          volumeMounts:
            - name: lib-modules
              mountPath: /lib/modules
              readOnly: true
            - name: wg-config
              mountPath: /config
          env:
            - name: SERVERURL
              value: "auto"
            - name: SERVERPORT
              value: "51820"
            - name: PEERS
              value: "10"
      volumes:
        - name: lib-modules
          hostPath:
            path: /lib/modules
        - name: wg-config
          hostPath:
            path: /etc/wireguard
```

### OpenVPN в Kubernetes

```yaml
# openvpn-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openvpn
spec:
  replicas: 1
  selector:
    matchLabels:
      app: openvpn
  template:
    metadata:
      labels:
        app: openvpn
    spec:
      containers:
        - name: openvpn
          image: kylemanna/openvpn
          ports:
            - containerPort: 1194
              protocol: UDP
          securityContext:
            capabilities:
              add:
                - NET_ADMIN
          volumeMounts:
            - name: ovpn-data
              mountPath: /etc/openvpn
      volumes:
        - name: ovpn-data
          persistentVolumeClaim:
            claimName: openvpn-data
---
apiVersion: v1
kind: Service
metadata:
  name: openvpn
spec:
  type: LoadBalancer
  ports:
    - port: 1194
      targetPort: 1194
      protocol: UDP
  selector:
    app: openvpn
```

---

## Ограничения и особенности

### Docker

| Ограничение | Решение |
|-------------|---------|
| **Нет доступа к /dev/net/tun** | `--device /dev/net/tun` или `cap_add: NET_ADMIN` |
| **Изоляция сети** | `network_mode: host` или port mapping |
| **Модули ядра** | Volume mount `/lib/modules:ro` |
| **sysctl** | `sysctls` в docker-compose.yml |

### Kubernetes

| Ограничение | Решение |
|-------------|---------|
| **NetworkPolicy** | Разрешить трафик к VPN-порту |
| **Service type** | LoadBalancer или NodePort для внешнего доступа |
| **RBAC** | ServiceAccount с правами управления сетью |
| **Host networking** | `hostNetwork: true` для маршрутизации |

---

## Дополнительная информация

### Связанные документы

- **[WireGuard](./wireguard_practical.md)** — настройка WireGuard
- **[OpenVPN](./openvpn.md)** — настройка OpenVPN
- **[IPsec](./ipsec/ipsec.md)** — настройка IPsec
- **[Cilium WireGuard](../../Kubernetes/Networking/Network/CNI/cilium.md)** — шифрование в Kubernetes
- **[Calico WireGuard](../../Kubernetes/Security/network_policies/Calico/index.md)** — шифрование в Kubernetes
- **[Docker networking](../../Docker/Docker_network/)** — сетевые драйверы Docker
