# Настройка сети в Vagrant

## Определения

**Сетевые интерфейсы Vagrant** — программные механизмы, обеспечивающие сетевое взаимодействие между хост-системой, виртуальными машинами (ВМ) и внешними сетями. Vagrant абстрагирует настройки различных провайдеров (VirtualBox, Libvirt, VMware), предоставляя унифицированный декларативный синтаксис.

**Forwarded Port (проброс портов)** — механизм трансляции сетевого трафика (NAT), сопоставляющий порт на хост-машине с портом в гостевой системе. Позволяет обращаться к сервисам внутри ВМ через IP-адреса хоста (обычно `127.0.0.1`).

**Private Network (приватная сеть)** — сетевой сегмент, изолированный от внешней сети и доступный только хосту и ВМ. В контексте VirtualBox это `Host-only network`, в Libvirt — изолированный виртуальный мост.

**Public Network (публичная сеть)** — интерфейс типа «сетевой мост» (Bridge), подключающий ВМ напрямую к физической или виртуальной сети хоста. ВМ получает статус полноценного узла в этой сети.

## Базовые концепции

### Основные типы сетей

| Тип | Провайдер (Термин) | Назначение | Доступность |
| :--- | :--- | :--- | :--- |
| **Forwarded Port** | NAT Port Forwarding | Быстрый доступ к API/UI | Только хост (localhost) |
| **Private Network** | Host-only / Isolated | Кластеры, базы данных | Хост + ВМ |
| **Public Network** | Bridged Adapter | Публичные сервисы, PXE | Вся локальная сеть |

### 1. Проброс портов (Forwarded Port)

Позволяет перенаправлять TCP/UDP трафик. По умолчанию Vagrant создает правило для SSH (порт 22), остальные порты описываются явно.

**Расширенные параметры:**
- `guest`: Порт внутри ВМ (обязателен).
- `host`: Порт на хост-машине (обязателен).
- `guest_ip`: Привязка к конкретному IP внутри ВМ.
- `host_ip`: Привязка к конкретному IP на хосте (например, `127.0.0.1` для безопасности).
- `protocol`: `tcp` (по умолчанию) или `udp`.
- `auto_correct`: `true` позволяет Vagrant автоматически выбрать другой порт на хосте, если указанный занят.
- `id`: Уникальное имя правила (полезно для переопределения в мульти-машинных конфигурациях).

### 2. Приватная сеть (Private Network)

Используется для создания защищенных каналов связи между машинами.

**Параметры и возможности:**
- **Статический IP:** `ip: "192.168.56.10"`.
- **DHCP:** `type: "dhcp"`.
- **IPv6:** Поддерживается через параметр `ip: "fde4:8dba:82e1:ffff::c0"`.
- **Внутренние сети (VirtualBox):** `virtualbox__intnet: "my-internal-net"` создает сеть, к которой хост не имеет доступа (только ВМ).
- **Управление именами:** `hostname: true` — автоматическое обновление `/etc/hosts` (требует плагин).

### 3. Публичная сеть (Public Network)

ВМ подключается к физическому интерфейсу хоста.

**Параметры:**
- `bridge`: Имя интерфейса хоста (например, `eth0`, `wlan0`). Если не указано, Vagrant предложит выбор при запуске.
- `use_dhcp_assigned_default_route`: Если `true`, ВМ будет использовать шлюз, полученный по DHCP в этой сети, как основной.

## Практические сценарии

### Сценарий 1: Безопасный доступ и оптимизация Virtio

Проброс портов с ограничением доступа только локальным хостом и использованием паравиртуализированного драйвера для производительности.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  config.vm.network "forwarded_port", 
    guest: 80, host: 8080, 
    host_ip: "127.0.0.1",
    auto_correct: true,
    id: "web-server"

  # Оптимизация сетевого драйвера
  config.vm.provider "virtualbox" do |vb|
    vb.customize ["modifyvm", :id, "--nictype1", "virtio"]
  end
end
```

### Сценарий 2: Мульти-стек сеть (IPv4 + IPv6) и кастомный MAC

Настройка приватной сети с поддержкой обоих протоколов и фиксированным MAC-адресом для Libvirt.

```ruby
Vagrant.configure("2") do |config|
  config.vm.define "node" do |node|
    node.vm.box = "bento/ubuntu-24.04"
    
    # IPv4 + IPv6
    node.vm.network "private_network", ip: "192.168.56.10"
    node.vm.network "private_network", ip: "fde4:8dba:82e1:ffff::10"
    
    # Специфично для Libvirt
    node.vm.network "private_network", 
      ip: "192.168.121.10",
      libvirt__mac: "52:54:00:12:34:56"
  end
end
```

### Сценарий 3: Динамический выбор моста и UDP-туннели

Автоматический выбор интерфейса в зависимости от ОС хоста и настройка туннеля между разными физическими хостами в Libvirt.

```ruby
Vagrant.configure("2") do |config|
  if Vagrant::Util::Platform.windows?
    bridge_if = "Intel(R) Ethernet Connection"
  elsif Vagrant::Util::Platform.darwin?
    bridge_if = "en0"
  else
    bridge_if = "eth0"
  end

  config.vm.network "public_network", bridge: bridge_if

  # UDP туннель для связи между разными ПК (Libvirt)
  config.vm.network "private_network",
    libvirt__tunnel_type: "udp",
    libvirt__tunnel_local_port: 11111,
    libvirt__tunnel_remote_host: "10.0.0.2",
    libvirt__tunnel_remote_port: 11111
end
```

## Дополнительная информация

### Провайдер-специфичные настройки

**VirtualBox:**
- Изменение типа адаптера: `vb.customize ["modifyvm", :id, "--nictype1", "virtio"]`.
- Внутренняя сеть (без хоста): `virtualbox__intnet: "cluster-internal"`.

**Libvirt:**
- Имя сети: `libvirt__network_name: "vagrant-private-net"`.
- Адрес управляющей сети: `lv.management_network_address = "10.10.10.0/24"`.

### Диагностика сетевых соединений

Команды внутри ВМ:
```bash
# Список интерфейсов и маршрутов
ip -brief addr show
ip route show

# Проверка MTU (критично для VPN/туннелей)
ip link show eth1 | grep mtu

# Проверка трафика и портов
sudo tcpdump -i eth1 -n icmp
ss -tulnp
```

### Решение типичных проблем

1.  **Порядок интерфейсов:** `eth0` всегда NAT для SSH. Дополнительные сети — `eth1`, `eth2` и т.д.
2.  **Конфликты с VPN:** Если VPN перекрывает управляющую подсеть (`10.0.2.0/24` или `192.168.121.0/24`), SSH-соединение зависнет.
3.  **Медленный DNS:** Попробуйте включить нативный резолвер хоста:
    `vb.customize ["modifyvm", :id, "--natdnshostresolver1", "on"]`.
4.  **Конфликт подсетей:** Проверьте `docker network ls` на предмет пересечения IP-диапазонов с `private_network`.

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — структура конфигурации.
- [Vagrant Providers](./vagrant_providers.md) — специфические настройки адаптеров.
- [Linux Networking: Команды и инструменты](../Linux/Networking/Tools/iproute2/overview.md) — глубокое погружение.
- [Проблемы MTU и фрагментация](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — диагностика сложных сетей.
