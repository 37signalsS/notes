# Постоянная настройка сети: практические сценарии

Навигация по методам настройки сети в различных дистрибутивах Linux.

## Навигация

### Дистрибутивы

- **[Debian/Ubuntu: /etc/network/interfaces](./debian_ubuntu_interfaces.md)** — классический способ с hook-скриптами
- **[CentOS/RHEL: NetworkManager](./centos_rhel_networkmanager.md)** — nmcli, nmtui, файлы ifcfg-*
- **[Ubuntu: Netplan](./ubuntu_netplan.md)** — декларативная настройка (YAML), bonding, VLAN
- **[systemd-networkd](./systemd_networkd.md)** — встроенный менеджер для серверов

### Связанные документы

- **[Настройка DNS-клиента](../../Concepts/dns_client.md)** — DNS-резолвинг
- **[Policy-Based Routing](./index.md)** — маршрутизация на основе политик
- **[Агрегация каналов](../../../../Networking/Concepts/link_aggregation.md)** — теория bonding
- **[VLAN](../../../../Networking/Protocols/VLAN/vlan_overview.md)** — теория VLAN
