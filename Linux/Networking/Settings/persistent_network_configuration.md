# Постоянная настройка сети в Linux

## Определения

* **Постоянная настройка сети** — конфигурация сетевых параметров (IP-адресов, шлюзов, DNS-серверов), сохраняющаяся после перезагрузки. В отличие от временных настроек через [iproute2](../Tools/iproute2/overview.md), достигается редактированием системных файлов.

## Базовые концепции

Настройки через команду `ip` временны. Для постоянной конфигурации используются следующие подходы (зависят от дистрибутива):

| Система | Дистрибутивы | Тип конфигурации | Управление |
| :--- | :--- | :--- | :--- |
| **`/etc/network/interfaces`** | Debian/Ubuntu (старые) | Императивная | `ifupdown` |
| **NetworkManager** | RHEL/CentOS/Fedora, Ubuntu Desktop | Императивная | `nmcli`, `nmtui` |
| **Netplan** | Ubuntu 17.10+ | Декларативная (YAML) | `netplan` |
| **`systemd-networkd`** | Минималистичные/серверные сборки | Декларативная | `networkctl` |

**Выбор системы:**
- **Серверы без GUI**: `systemd-networkd` или `netplan` (Ubuntu), `NetworkManager` (RHEL)
- **Десктопы**: `NetworkManager` (универсально)
- **Контейнеры/minimal**: `systemd-networkd`

**См. также:**
- [Сетевые интерфейсы](../Concepts/linux_network_interfaces.md) — типы интерфейсов
- [Настройка DNS-клиента](../Concepts/dns_client.md) — DNS-резолвинг
- [Агрегация каналов](../../../Networking/Concepts/link_aggregation.md) — bonding
- [VLAN](../../../Networking/Concepts/vlan_and_L2_switching.md) — VLAN-конфигурация

## Практические сценарии

### 1. Debian/Ubuntu (классический способ, `/etc/network/interfaces`)

В системах, где не используется `NetworkManager` или `netplan`, сеть настраивается через этот файл.

**Пример статической конфигурации:**

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

* **Применение изменений:** `sudo systemctl restart networking`

### 2. CentOS/RHEL и другие (NetworkManager и `nmcli`)

`nmcli` является предпочтительным инструментом для управления NetworkManager. Также доступен псевдографический интерфейс `nmtui` для удобной настройки без запоминания команд.

* **Псевдографический интерфейс (nmtui):**
    ```bash
    nmtui
    ```
    Позволяет интерактивно редактировать соединения, включая настройку статических IP-адресов, шлюзов и DNS-серверов.

* **Посмотреть устройства и соединения:**

    ```bash
    nmcli device status
    nmcli connection show
    ```

* **Изменить соединение на статическое:**

    ```bash
    # Устанавливаем статический IP, маску и шлюз для соединения 'enp0s3'
    sudo nmcli connection modify 'enp0s3' ipv4.method manual ipv4.addresses 10.10.10.10/24 gw4 10.10.10.1

    # Добавляем DNS-серверы (через пробел)
    sudo nmcli connection modify 'enp0s3' ipv4.dns "8.8.8.8 1.1.1.1"

    # Применяем изменения (деактивируем и активируем соединение)
    sudo nmcli connection down 'enp0s3' && sudo nmcli connection up 'enp0s3'
    ```

* **Традиционный способ (файлы `ifcfg-*`):**
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

* **Применение изменений:** `sudo systemctl restart NetworkManager`

### 3. Ubuntu 17.10+ (Netplan)

В современных версиях Ubuntu для управления сетью используется `netplan`. Это утилита, которая использует декларативные YAML-файлы, а затем генерирует на их основе настройки для `systemd-networkd` (на серверах) или `NetworkManager` (на десктопах).

Конфигурационные файлы находятся в `/etc/netplan/`.

**Пример статической конфигурации:**

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

* **`renderer: networkd`**: Указывает, что `netplan` должен генерировать конфигурацию для `systemd-networkd`.
* **`enp0s3`**: Имя вашего интерфейса. Узнать можно командой `ip a`.

**Применение конфигурации:**

```bash
# 1. Проверить синтаксис
sudo netplan generate
# 2. Применить конфигурацию
sudo netplan apply
```

### 4. systemd-networkd

`systemd-networkd` — встроенный менеджер сети в systemd. Работает без дополнительных зависимостей, идеален для серверов и минималистичных систем.

**Конфигурационные файлы:** `/etc/systemd/network/*.network`

**Пример статической конфигурации:**

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

**Пример с несколькими адресами и маршрутами:**

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

**Пример DHCP-клиента:**

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

**Управление и диагностика:**

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

**Интеграция с systemd-resolved (DNS):**

`systemd-networkd` автоматически передает DNS-серверы в `systemd-resolved`. Проверка:

```bash
# Показать текущие DNS-серверы
resolvectl status

# Показать кэш DNS
resolvectl statistics
```

**Преимущества systemd-networkd:**
- Минимальные зависимости (часть systemd)
- Декларативная конфигурация
- Встроенная поддержка DHCP, DNS-over-TLS (через systemd-resolved)
- Хорошая интеграция с другими компонентами systemd

**Недостатки:**
- Меньше возможностей для сложных сценариев (по сравнению с NetworkManager)
- Нет GUI-инструментов

---

## Дополнительная информация

### IPv6

Настройка IPv6 выполняется аналогично IPv4 с использованием соответствующих параметров. Подробно см. [Настройка IPv6 в Linux](./ipv6_configuration.md).

### Фиксация имен сетевых интерфейсов

Для предотвращения смены имен интерфейсов (например, `eth0` → `eth1`) после перезагрузки используется `systemd.link`.

**Процедура:**

1. **Узнать MAC-адрес интерфейса:**
   ```bash
   ip link show eth0
   ```

2. **Создать файл `/etc/systemd/network/10-persistent-net.link`:**
   ```ini
   [Match]
   MACAddress=52:54:00:ab:cd:ef

   [Link]
   Name=net0
   ```
   - `[Match]`: Условие поиска устройства (MAC-адрес — надежнейший способ).
   - `[Link]`: Действие — `Name=net0` задает постоянное имя.

3. **Применить изменения:**
   ```bash
   # Перезагрузить систему
   sudo reboot
   # Или без перезагрузки (требует осторожности)
   sudo udevadm trigger
   ```

**См. также:** [Управление правилами udev](../Core/udev.md#Управление-правилами-udev).

### Сравнение методов настройки

| Метод | Сложность | Гибкость | GUI | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| `/etc/network/interfaces` | Низкая | Средняя | Нет | Устарел, только legacy-системы |
| `NetworkManager` (nmcli) | Средняя | Высокая | Есть (`nmtui`) | Десктопы, RHEL/CentOS серверы |
| `Netplan` | Низкая | Средняя | Нет | Ubuntu Server 17.10+ |
| `systemd-networkd` | Средняя | Высокая | Нет | Минималистичные системы, контейнеры |

### Диагностика проблем

**Общие команды:**
```bash
# Проверка состояния сети
systemctl status NetworkManager
systemctl status systemd-networkd
systemctl status netplan

# Журналы
journalctl -u NetworkManager -f
journalctl -u systemd-networkd -f

# Проверка конфигурации
networkctl status
nmcli device status
```

**Типичные проблемы:**

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Конфликт DNS | Несколько служб управляют `/etc/resolv.conf` | Проверить `systemd-resolved`, NetworkManager |
| Интерфейс не поднимается | Ошибка в конфигурации | `networkctl status`, `journalctl -u systemd-networkd` |
| Нет маршрута по умолчанию | Не указан gateway | Проверить файл конфигурации |
| DNS не работает | Неправильные nameservers | Проверить `resolvectl status` |

**См. также:**
- [Диагностика DNS](../Concepts/dns_client.md#Диагностика-проблем)
- [Сетевая диагностика](../network_diagnostics_tools.md)
