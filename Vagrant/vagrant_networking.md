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

### Взаимодействие с сетевым стеком гипервизора

Vagrant описывает сеть декларативно, но underneath использует механизмы конкретного гипервизора. Понимание этой трансляции критично для диагностики.

**VirtualBox:**
- `private_network` → Host-only адаптер (`vboxnet0`). VirtualBox автоматически создает интерфейс на хосте и работает как L2-коммутатор между хостом и всеми ВМ в этой сети.
- `public_network` → Bridged адаптер. ВМ получает собственный MAC-адрес и подключается к тому же сегменту L2, что и физический интерфейс хоста.
- `forwarded_port` → Встроенный NAT-движок VirtualBox или правила `iptables` на хосте (если используется `natpf1`).

**Libvirt:**
- `private_network` → Виртуальная сеть, управляемая через `virsh net-*`. По умолчанию создается сеть `vagrant-libvirt` с NAT и DHCP (dnsmasq). ВМ получает IP из подсети (обычно `192.168.121.0/24`).
- `public_network` → Прямой мост (`br0`, `virbr0` и т.д.). ВМ появляется в физической сети как отдельное устройство со своим MAC.
- `forwarded_port` → Правила DNAT в `iptables`/`nftables` на хосте или через XML-определение сети Libvirt.

**Hyper-V:**
- `private_network` → Внутренний виртуальный коммутатор (Private Switch). Доступна только для ВМ на том же хосте, хост не имеет IP в этой сети по умолчанию.
- `public_network` → Внешний виртуальный коммутатор (External Switch), привязанный к физическому адаптеру. Несколько ВМ могут shares one External Switch.
- `forwarded_port` → Правила портов на коммутаторе или через PowerShell `netsh interface portproxy`.

**QEMU (Apple Silicon):**
- `forwarded_port` → SLIRP (User-mode networking). По умолчанию SSH пробрасывается на порт **50022** (вместо стандартного 2222) для избежания конфликтов. Не требует прав root.
- `private_network` → Виртуальный коммутатор `virtio-net-pci`. На macOS создание настоящего bridge без root затруднительно, поэтому чаще используется SLIRP или пользовательские туннели.
- `qemu.net_device = "virtio-net-pci"` — самый быстрый доступный драйвер для ARM64.

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

**Валидация:**
```bash
# Проверить, что порт слушается только на localhost
sudo lsof -iTCP:8080 -sTCP:LISTEN
# → vagrant  1234  vb   TCP 127.0.0.1:8080 (LISTEN)
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

**Валидация:**
```bash
vagrant ssh -c "ip -brief addr show"
# → eth0  UP  10.0.2.15/24 (NAT)
# → eth1  UP  192.168.56.10/24 (private)
# → eth2  UP  fde4:8dba:82e1:ffff::10/128 (private IPv6)
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

### Сценарий 4: Кластер из нескольких ВМ с автоматическим DNS

При работе с мульти-машинными окружениями (web, db, cache) необходимо, чтобы машины могли обращаться друг к другу по именам. Используйте плагин `vagrant-hostmanager` для автоматического управления `/etc/hosts`.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # Автоматическая установка hostmanager при отсутствии
  required_plugins = %w(vagrant-hostmanager)
  missing = required_plugins.reject { |p| Vagrant.has_plugin?(p) }
  unless missing.empty?
    puts "Установите плагин: vagrant plugin install #{missing.join(' ')}"
    exit 1
  end

  config.hostmanager.enabled = true
  config.hostmanager.manage_host = true       # Обновлять /etc/hosts на хосте
  config.hostmanager.manage_guest = true      # Обновлять /etc/hosts внутри ВМ
  config.hostmanager.ignore_private_ip = false

  config.vm.define "web" do |web|
    web.vm.hostname = "web.local"
    web.vm.network "private_network", ip: "192.168.56.10"
  end

  config.vm.define "db" do |db|
    db.vm.hostname = "db.local"
    db.vm.network "private_network", ip: "192.168.56.11"
  end

  config.vm.define "cache" do |cache|
    cache.vm.hostname = "cache.local"
    cache.vm.network "private_network", ip: "192.168.56.12"
  end
end
```

**Валидация:**
```bash
vagrant up
vagrant ssh web -c "ping -c1 db.local"
# → db.local (192.168.56.11) отвечает
```

### Сценарий 5: NFS + private_network для общей файловой системы

Для высокопроизводительной синхронизации исходного кода между хостом и ВМ используйте NFS. Требует статического IP в приватной сети для стабильного монтирования.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # Приватная сеть обязательна для NFS
  config.vm.network "private_network", ip: "192.168.56.10"

  config.vm.synced_folder ".", "/vagrant",
    type: "nfs",
    nfs_version: 4,
    nfs_udp: false,
    mount_options: ["actimeo=1", "nolock"]
end
```

**Валидация:**
```bash
vagrant ssh -c "findmnt -t nfs4"
# → /vagrant  192.168.56.1:/Users/mac/project  nfs4  rw,relatime,vers=4.2...
```

### Сценарий 6: Docker-провайдер и сетевые режимы

При использовании Docker как провайдера Vagrant работает с сетевыми пространствами имен Docker. Контейнеры получают доступ к сети через bridge Docker по умолчанию.

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "docker" do |d|
    d.image = "docker:24.0-dind"
    d.has_ssh = false
    d.remains_running = false
  end

  # Проброс портов работает через Docker port publishing
  config.vm.network "forwarded_port",
    guest: 8080,
    host: 8080,
    auto_correct: true
end
```

**Валидация:**
```bash
docker ps
# → CONTAINER ID   IMAGE          PORTS
# → abc12345       docker:24.0-dind   0.0.0.0:32768->8080/tcp
```

### Сценарий 7: Брандмауэр хоста для проброшенных портов

По умолчанию проброс портов привязывается к `127.0.0.1`. Для доступа из локальной подсети нужно изменить `host_ip` и открыть порт в фаерволе хоста.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # Доступ к API из локальной сети (192.168.1.0/24)
  config.vm.network "forwarded_port",
    guest: 8443,
    host: 8443,
    host_ip: "0.0.0.0",
    auto_correct: true,
    id: "secure-api"
end
```

**Настройка фаервола на хосте (Linux/nftables):**
```bash
# Открыть порт 8443 только для локальной подсети
sudo nft add rule inet filter input ip saddr 192.168.1.0/24 tcp dport 8443 accept

# Или через iptables
sudo iptables -A INPUT -p tcp -s 192.168.1.0/24 --dport 8443 -j ACCEPT
```

**Валидация:**
```bash
# С хоста
nc -zv 192.168.1.50 8443
# → Connection succeeded

# Из локальной сети (другой компьютер)
curl -k https://192.168.1.50:8443/health
```

### Сценарий 8: Тонкая настройка производительности сети

Для гостевых ОС с высокой сетевой нагрузкой (базы данных, файловые хранилища) настройте MTU, multiqueue и размеры кольцевых буферов.

**VirtualBox:**
```ruby
config.vm.provider "virtualbox" do |vb|
  # Мультиплексные очереди для виртуальной карты
  vb.customize ["modifyvm", :id, "--nicqueues1", "4"]
  # MTU 9000 (Jumbo Frames) для iSCSI/NFS
  vb.customize ["modifyvm", :id, "--mtu", "9000"]
end
```

**Libvirt:**
```ruby
config.vm.provider "libvirt" do |lv|
  # Многопоточная обработка сети (требует guest поддержки)
  lv.nic_model_type = "virtio"
  lv.management_network_name = "vagrant-libvirt"
  
  # В XML сети можно задать MTU:
  # <mtu size="9000"/>
end
```

**Валидация внутри ВМ:**
```bash
# Проверка MTU
ip link show eth1 | grep mtu
# → mtu 9000 qdisc ...

# Проверка количества очередей
ethtool -l eth1
# → Combined: 4
```

### Сценарий 9: Сеть поверх VPN/WireGuard (Overlay)

Создание защищенного overlay-сети между ВМ на разных хостах через WireGuard. Подходит для распределенных лабораторных сред.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.network "private_network", ip: "192.168.56.10"

  config.vm.provision "shell", inline: <<-SHELL
    apt-get update
    apt-get install -y wireguard

    # Генерация ключей
    wg genkey | tee /etc/wg0.key | wg pubkey > /etc/wg0.pub

    # Конфигурация интерфейса
    cat > /etc/wireguard/wg0.conf << EOF
[Interface]
PrivateKey = $(cat /etc/wg0.key)
Address = 10.200.200.10/24
ListenPort = 51820

[Peer]
PublicKey = <PUBLIC_KEY_REMOTE_HOST>
Endpoint = 203.0.113.5:51820
AllowedIPs = 10.200.200.0/24
PersistentKeepalive = 25
EOF

    systemctl enable --now wg-quick@wg0
  SHELL
end
```

**Валидация:**
```bash
vagrant ssh -c "wg show"
# → interface: wg0
# → peer: <public_key>  endpoint: 203.0.113.5:51820  allowed ips: 10.200.200.0/24
```

### Сценарий 10: Изолированная сеть для CI/CD

В CI/CD пайплайнах важно использовать изолированные подсети, не пересекающиеся с инфраструктурой оркестратора.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # Изолированная подсеть, далеко от стандартных диапазонов Docker/K8s
  config.vm.network "private_network",
    ip: "10.250.250.10",
    libvirt__network_name: "ci-isolated"

  config.vm.network "forwarded_port",
    guest: 3000,
    host: 3000,
    host_ip: "127.0.0.1",
    auto_correct: true

  config.vm.provider "libvirt" do |lv|
    lv.management_network_address = "10.250.250.0/24"
    lv.memory = 2048
    lv.cpus = 2
  end
end
```

**Запуск в CI:**
```bash
export VAGRANT_DEFAULT_PROVIDER=libvirt
export VAGRANT_NO_TTY=1
vagrant up --no-provision
vagrant provision
vagrant ssh -c "curl -s http://localhost:3000/health"
vagrant destroy -f
```

## Дополнительная информация

### Провайдер-специфичные настройки

**VirtualBox:**
- Изменение типа адаптера: `vb.customize ["modifyvm", :id, "--nictype1", "virtio"]`.
- Внутренняя сеть (без хоста): `virtualbox__intnet: "cluster-internal"`.
- NAT DNS резолвер: `vb.customize ["modifyvm", :id, "--natdnshostresolver1", "on"]`.

**Libvirt:**
- Имя сети: `libvirt__network_name: "vagrant-private-net"`.
- Адрес управляющей сети: `lv.management_network_address = "10.10.10.0/24"`.
- MAC-адрес: `libvirt__mac: "52:54:00:12:34:56"`.

**QEMU (Apple Silicon):**
- Сетевой адаптер: `qemu.net_device = "virtio-net-pci"`.
- Порт SSH по умолчанию: **50022**.
- Режим: SLIRP (user-mode networking), не требует root.

### Диагностика сетевых соединений

**На хосте:**
```bash
# VirtualBox: список host-only интерфейсов
VBoxManage list hostonlyifs

# Libvirt: список виртуальных сетей
virsh --connect qemu:///system net-list --all

# Проверка iptables/nftables для NAT
sudo iptables -t nat -L -n -v
sudo nft list ruleset | grep dnat

# Проверка слушающих портов на хосте
sudo ss -tulnp | grep -E '2222|8080|8443'
```

**Команды внутри ВМ:**
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

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Call to virNetworkCreate failed: network is already active` | Подсеть занята Docker, VPN или другим Vagrant | Смените подсеть в `private_network` или перезапустите сеть: `virsh net-destroy vagrant-libvirt && virsh net-start vagrant-libvirt` |
| `VT-x is not available` | Hyper-V захватил аппаратную виртуализацию | Отключите Hyper-V или используйте `vagrant up --provider=hyperv` |
| `No matching downloader for provider` | Плагин провайдера не установлен | `vagrant plugin install vagrant-libvirt` или `vagrant plugin install vagrant-vmware-desktop` |
| `Box format mismatch` | Попытка запуска qcow2-образа в VirtualBox | Используйте `vagrant up --provider=libvirt` или скачайте box для нужного провайдера |
| `Permission denied` (NFS) | Firewall блокирует 2049/nfs или нет записи в `/etc/exports` | Разрешите NFS в фаерволе и проверьте `/etc/exports` |
| `The box '...' could not be found` | Неверное имя box или отсутствует провайдер | `vagrant box add bento/ubuntu-24.04 --provider virtualbox` |
| `SSH timeout` после `vagrant up` | VPN перекрывает управляющую подсеть (`10.0.2.0/24` или `192.168.121.0/24`) | Отключите VPN или измените подсеть `private_network` |
| `Port already in use` | Порт на хосте занят другим процессом | Укажите другой `host` порт или `auto_correct: true` |

### Лучшие практики

1.  **Привязка к localhost:** Для внутренних сервисов всегда указывайте `host_ip: "127.0.0.1"`. Это предотвращает доступ из внешней сети без дополнительных правил фаервола.
2.  **Статические IP в известных диапазонах:** Используйте подсети, не пересекающиеся с корпоративными сетями (например, `10.250.250.0/24` для CI, `192.168.56.0/24` для локальной разработки).
3.  **Версионирование:** Фиксируйте версию box (`config.vm.box_version`), так как обновление образа может изменить сетевые параметры по умолчанию.
4.  **Документирование подсетей:** В команде храните карту подсетей (`docs/networking.md`), чтобы избежать конфликтов при добавлении новых проектов.
5.  **Очистка после destroy:** Проверяйте, что `vagrant destroy` удаляет все созданные сети и правила iptables. При State Desync используйте `virsh net-destroy` или `VBoxManage hostonlyif remove`.

### Безопасность

- **Ограничение доступа:** Избегайте `host_ip: "0.0.0.0"` без необходимости. Если сервис должен быть доступен из локальной сети, укажите конкретную подсеть через фаервол хоста.
- **Публичные сети:** При использовании `public_network` ВМ получает доступ к той же сети, что и хост. Убедитесь, что внутри гостевой ОС настроен фаервол (`ufw`, `nftables`).
- **SSH-ключи:** Vagrant по умолчанию внедряет уникальный insecure public key. Для production-образов замените его на собственный ключ через `config.ssh.private_key_path`.

### Очистка ресурсов

**VirtualBox:**
```bash
# Удалить неиспользуемые host-only интерфейсы
VBoxManage list hostonlyifs
VBoxManage hostonlyif remove vboxnet1
```

**Libvirt:**
```bash
# Удалить неиспользуемые сети
virsh --connect qemu:///system net-list --all
virsh --connect qemu:///system net-undefine vagrant-libvirt-old
```

**Глобальная очистка Vagrant:**
```bash
# Удалить ВМ, оставшиеся в метаданных после ручного удаления в гипервизоре
vagrant global-status --prune

# Удалить неиспользуемые образы
vagrant box prune
```

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — структура конфигурации.
- [Vagrant Providers](./vagrant_providers.md) — специфические настройки адаптеров.
- [Linux Networking: Команды и инструменты](../Linux/Networking/Tools/iproute2/overview.md) — глубокое погружение.
- [Проблемы MTU и фрагментация](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — диагностика сложных сетей.
