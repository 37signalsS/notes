# Постоянная настройка сети в Linux

## Определения

* **Постоянная настройка сети** — это конфигурация сетевых параметров (IP-адресов, шлюзов, DNS-серверов), которая сохраняется после перезагрузки. В отличие от временных настроек, применяемых утилитой [[iproute2|../Tools/iproute2.md]], она достигается редактированием системных файлов.

## Базовые концепции

Настройки, сделанные с помощью команды `ip`, являются временными. Для постоянной конфигурации сети в Linux необходимо использовать один из следующих подходов, зависящих от дистрибутива и его версии.

Основные системы управления сетью:

* **`/etc/network/interfaces`**: Классический метод в Debian/Ubuntu.
* **NetworkManager**: Стандарт де-факто в десктопных и многих серверных дистрибутивах (CentOS/RHEL, Fedora, Ubuntu Desktop). Управляется через `nmcli`.
* **Netplan**: Декларативная система на основе YAML в современных версиях Ubuntu Server, которая генерирует конфигурацию для NetworkManager или `systemd-networkd`.
* **`systemd-networkd`**: Современный системный менеджер сети, часто используется в минималистичных и серверных сборках.

Концепции работы DNS-клиента подробно описаны в заметке [[Настройка и диагностика DNS-клиента в Linux|../Concepts/dns_client.md]].

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

- **Применение изменений:** `sudo systemctl restart networking`

### 2. CentOS/RHEL и другие (NetworkManager и `nmcli`)

`nmcli` является предпочтительным инструментом для управления NetworkManager.

* **Посмотреть устройства и соединения:**

    ```bash
    nmcli device status
    nmcli connection show
    ```

* **Изменить соединение на статическое:**

    ```bash
    # Устанавливаем статический IP, маску и шлюз для соединения 'enp0s3'
    sudo nmcli connection modify 'enp0s3' ipv4.method manual ipv4.addresses 10.10.10.10/24 gw4 10.10.10.1

    # Добавляем DNS-серверы
    sudo nmcli connection modify 'enp0s3' ipv4.dns "8.8.8.8 1.1.1.1"

    # Применяем изменения
    sudo nmcli connection up 'enp0s3'
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

- **Применение изменений:** `sudo systemctl restart NetworkManager`

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

## Дополнительная информация

### 1. Фиксация имен сетевых интерфейсов

Чтобы имя интерфейса (например, `eth0`) не менялось после перезагрузки, можно использовать `systemd.link`.

1. **Узнайте MAC-адрес интерфейса:** `ip link show eth0`
2. **Создайте файл `/etc/systemd/network/10-persistent-net.link`:**

    ```ini
    [Match]
    MACAddress=52:54:00:ab:cd:ef

    [Link]
    Name=net0
    ```

    * `[Match]`: Условие, по которому `systemd` найдет устройство. `MACAddress` — самый надежный способ.
    * `[Link]`: Действие. `Name=net0` задает новое, постоянное имя `net0`.

3. **Перезагрузите систему** или выполните `sudo udevadm trigger` (подробнее об этой команде см. в разделе [Управление правилами `udev`](../Core/udev.md#Управление-правилами-udev)), чтобы применить изменения.

Теперь ваш сетевой интерфейс всегда будет называться `net0`.
