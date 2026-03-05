# Постоянная настройка сети: Практические сценарии

## 1. Debian/Ubuntu (классический способ, `/etc/network/interfaces`)

В системах, где не используется `NetworkManager` или `netplan`, сеть настраивается через этот файл.

### Пример статической конфигурации

```ini
# /etc/network/interfaces
auto lo
iface lo inet loopback

# Основной сетевой интерфейс
auto eth0
iface eth0 inet static
    address 10.10.10.10/24    # IP-адрес и маска
    gateway 10.10.10.1        # Шлюз по умолчанию
    dns-nameservers 8.8.8.8 1.1.1.1
```

**Применение изменений:**

```bash
sudo systemctl restart networking
```

## 2. CentOS/RHEL и другие (NetworkManager и `nmcli`)

`nmcli` является предпочтительным инструментом для управления NetworkManager. Также доступен псевдографический интерфейс `nmtui` для удобной настройки без запоминания команд.

### Псевдографический интерфейс (nmtui)

```bash
nmtui
```

Позволяет интерактивно редактировать соединения, включая настройку статических IP-адресов, шлюзов и DNS-серверов.

### Командная строка (nmcli)

**Посмотреть устройства и соединения:**

```bash
nmcli device status
nmcli connection show
```

**Изменить соединение на статическое:**

```bash
# Устанавливаем статический IP, маску и шлюз для соединения 'enp0s3'
sudo nmcli connection modify 'enp0s3' ipv4.method manual ipv4.addresses 10.10.10.10/24 gw4 10.10.10.1

# Добавляем DNS-серверы (через пробел)
sudo nmcli connection modify 'enp0s3' ipv4.dns "8.8.8.8 1.1.1.1"

# Применяем изменения (деактивируем и активируем соединение)
sudo nmcli connection down 'enp0s3' && sudo nmcli connection up 'enp0s3'
```

### Традиционный способ (файлы `ifcfg-*`)

Файлы в `/etc/sysconfig/network-scripts/ifcfg-<имя>`.

```ini
# /etc/sysconfig/network-scripts/ifcfg-eth0
DEVICE="eth0"
BOOTPROTO="none"
ONBOOT="yes"
IPADDR="10.10.10.10"
PREFIX="24"
GATEWAY="10.10.10.1"
DNS1="8.8.8.8"
```

**Применение изменений:**

```bash
sudo systemctl restart NetworkManager
```

## 3. Ubuntu 17.10+ (Netplan)

В современных версиях Ubuntu для управления сетью используется `netplan`. Это утилита, которая использует декларативные YAML-файлы, а затем генерирует на их основе настройки для `systemd-networkd` (на серверах) или `NetworkManager` (на десктопах).

Конфигурационные файлы находятся в `/etc/netplan/`.

### Пример статической конфигурации

```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: no
      addresses:
        - 10.10.10.10/24
      routes:
        - to: default
          via: 10.10.10.1
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
```

- **`renderer: networkd`**: Указывает, что `netplan` должен генерировать конфигурацию для `systemd-networkd`.
- **`enp0s3`**: Имя вашего интерфейса. Узнать можно командой `ip a`.

### Применение конфигурации

```bash
# 1. Проверить синтаксис
sudo netplan generate
# 2. Применить конфигурацию
sudo netplan apply
```

## 4. systemd-networkd

`systemd-networkd` — встроенный менеджер сети в systemd. Работает без дополнительных зависимостей, идеален для серверов и минималистичных систем.

Конфигурационные файлы: `/etc/systemd/network/*.network`

### Пример статической конфигурации

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
Address=10.10.10.10/24
Gateway=10.10.10.1
DNS=8.8.8.8
DNS=1.1.1.1

# DHCP (альтернатива)
# [Network]
# DHCP=yes
```

### Пример с несколькими адресами и маршрутами

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
# Основной адрес
Address=10.10.10.10/24
# Дополнительный адрес (VIP)
Address=10.10.10.20/24
Gateway=10.10.10.1
DNS=8.8.8.8
DNS=1.1.1.1

# Статический маршрут
[Route]
Destination=192.168.100.0/24
Gateway=10.10.10.254

# Маршрут по умолчанию с метрикой
[Route]
Gateway=10.10.10.1
Metric=100
```

### Пример DHCP-клиента

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
DHCP=yes

[DHCP]
# Использовать DNS от DHCP
UseDNS=yes
# Использовать NTP от DHCP
UseNTP=yes
```

### Управление и диагностика

```bash
# Включить службу
sudo systemctl enable --now systemd-networkd

# Перезапустить службу
sudo systemctl restart systemd-networkd

# Показать состояние интерфейсов
networkctl status

# Показать список интерфейсов
networkctl list

# Перечитать конфигурацию
sudo networkctl reload

# Журнал событий
journalctl -u systemd-networkd -f
```

### Интеграция с systemd-resolved (DNS)

`systemd-networkd` автоматически передает DNS-серверы в `systemd-resolved`. Проверка:

```bash
# Показать текущие DNS-серверы
resolvectl status

# Показать кэш DNS
resolvectl statistics
```

### Преимущества systemd-networkd

- Минимальные зависимости (часть systemd)
- Декларативная конфигурация
- Встроенная поддержка DHCP, DNS-over-TLS (через systemd-resolved)
- Хорошая интеграция с другими компонентами systemd

### Недостатки systemd-networkd

- Меньше возможностей для сложных сценариев (по сравнению с NetworkManager)
- Нет GUI-инструментов

## Связанные документы

- **[Основные концепции](./network_configuration_concepts.md)** — определения и сравнение систем
- **[Дополнительные темы](./network_advanced_topics.md)** — IPv6, фиксация имен, диагностика
- **[Настройка DNS-клиента](../../Concepts/dns_client.md)** — DNS-резолвинг
