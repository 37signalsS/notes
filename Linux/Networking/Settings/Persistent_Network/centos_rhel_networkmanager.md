# CentOS/RHEL: настройка сети через NetworkManager и nmcli

## NetworkManager и nmcli

`nmcli` является предпочтительным инструментом для управления NetworkManager. Также доступен псевдографический интерфейс `nmtui` для удобной настройки без запоминания команд.

---

## Псевдографический интерфейс (nmtui)

```bash
nmtui
```

Позволяет интерактивно редактировать соединения, включая настройку статических IP-адресов, шлюзов и DNS-серверов.

---

## Командная строка (nmcli)

### Посмотреть устройства и соединения

```bash
nmcli device status
nmcli connection show
```

### Изменить соединение на статическое

```bash
# Устанавливаем статический IP, маску и шлюз для соединения 'enp0s3'
sudo nmcli connection modify 'enp0s3' ipv4.method manual ipv4.addresses 10.10.10.10/24 gw4 10.10.10.1

# Добавляем DNS-серверы (через пробел)
sudo nmcli connection modify 'enp0s3' ipv4.dns "8.8.8.8 1.1.1.1"

# Применяем изменения (деактивируем и активируем соединение)
sudo nmcli connection down 'enp0s3' && sudo nmcli connection up 'enp0s3'
```

---

## Традиционный способ (файлы ifcfg-*)

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

### Применение изменений

```bash
sudo systemctl restart NetworkManager
```
