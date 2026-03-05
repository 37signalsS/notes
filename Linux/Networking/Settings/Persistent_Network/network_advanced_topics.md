# Постоянная настройка сети: Дополнительные темы

## 1. IPv6

Настройка IPv6 выполняется аналогично IPv4 с использованием соответствующих параметров.

**Подробно см.:** [Настройка IPv6 в Linux](./ipv6_configuration.md)

## 2. Фиксация имен сетевых интерфейсов

Для предотвращения смены имен интерфейсов (например, `eth0` → `eth1`) после перезагрузки используется `systemd.link`.

### Процедура

**1. Узнать MAC-адрес интерфейса:**

```bash
ip link show eth0
```

**2. Создать файл `/etc/systemd/network/10-persistent-net.link`:**

```ini
[Match]
MACAddress=52:54:00:ab:cd:ef

[Link]
Name=net0
```

- `[Match]`: Условие поиска устройства (MAC-адрес — надежнейший способ).
- `[Link]`: Действие — `Name=net0` задает постоянное имя.

**3. Применить изменения:**

```bash
# Перезагрузить систему
sudo reboot
# Или без перезагрузки (требует осторожности)
sudo udevadm trigger
```

**См. также:** [Управление правилами udev](../../Core/udev.md#Управление-правилами-udev).

## 3. Диагностика проблем

### Общие команды

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

### Типичные проблемы

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Конфликт DNS | Несколько служб управляют `/etc/resolv.conf` | Проверить `systemd-resolved`, NetworkManager |
| Интерфейс не поднимается | Ошибка в конфигурации | `networkctl status`, `journalctl -u systemd-networkd` |
| Нет маршрута по умолчанию | Не указан gateway | Проверить файл конфигурации |
| DNS не работает | Неправильные nameservers | Проверить `resolvectl status` |

**См. также:**

- **[Диагностика DNS](../../Concepts/dns_client.md#Диагностика-проблем)**
- **[Сетевая диагностика](../../network_diagnostics_tools.md)**

## Связанные документы

- **[Основные концепции](./network_configuration_concepts.md)** — определения и сравнение систем
- **[Настройка статических IP](./persistent_network_setup.md)** — практические сценарии
- **[Настройка DNS-клиента](../../Concepts/dns_client.md)** — DNS-резолвинг
- **[Сетевая диагностика](../../network_diagnostics_tools.md)** — инструменты диагностики
