# ISC DHCP Failover: Отказоустойчивая пара серверов

> **Важно:** ISC DHCP устарел. Для новых развёртываний используйте [Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива) с HA через hook modules.
> См. также: [Защита от rogue DHCP](../../../../Networking/Protocols/DHCP/dhcp_security.md).

## Definitions

**DHCP Failover** — механизм высокой доступности (HA), при котором два DHCP-сервера синхронизируют информацию об арендах и подменяют друг друга при сбое.

**Primary/Secondary** — роли серверов в паре. Оба способны выдавать адреса, но primary имеет приоритет при управлении пулом.

**MCLT (Max Client Lead Time)** — максимальное время, на которое сервер может продлить аренду без согласования с партнёром.

**Split** — параметр распределения пула адресов между серверами (0–256, где 128 = 50/50).

## Basic Concepts

### Принцип работы

1. **Два сервера:** один настраивается как `primary`, другой как `secondary`.
2. **Синхронизация:** обмен информацией об арендах по TCP-порту 647.
3. **Разделение нагрузки:** пул адресов делится параметром `split`, что позволяет обоим серверам отвечать на запросы клиентов.

### Состояния failover-пары

| Состояние | Описание |
| :--- | :--- |
| `normal` / `balanced` | Оба сервера работают, синхронизация активна |
| `communications-interrupted` | Потеря связи между серверами |
| `partner-down` | Партёр считается неработающим |
| `potentially-down` | Требуется подтверждение состояния партнёра |
| `reboot` | Сервер перезапускается после сбоя |
| `shutdown` | Сервер остановлен администратором |
| `paused` | Временная приостановка обработки запросов |

## Practical Scenarios

### Сценарий 1: Настройка failover-пары

**Шаг 1: Организация конфигурационных файлов**

Рекомендуется вынести общие части в отдельные файлы и подключать через `include`:

- `/etc/dhcp/dhcpd.conf` — уникальные failover-параметры каждого сервера.
- `/etc/dhcp/dhcpd.conf.d/subnets.conf` — общие определения `subnet`.
- `/etc/dhcp/dhcpd.conf.d/reservations.conf` — общие определения `host` (резервации).

**Шаг 2: Конфигурация `dhcpd.conf`**

Primary сервер (10.0.4.4):

```ini
failover peer "dhcp-failover" {
    primary;
    address 10.0.4.4;
    port 647;
    peer address 10.0.4.5;
    peer port 647;

    max-response-delay 60;
    max-unacked-updates 10;
    mclt 3600;
    split 128;
    load balance max seconds 3;
}

include "/etc/dhcp/dhcpd.conf.d/subnets.conf";
include "/etc/dhcp/dhcpd.conf.d/reservations.conf";
```

Secondary сервер (10.0.4.5):

```ini
failover peer "dhcp-failover" {
    secondary;
    address 10.0.4.5;
    port 647;
    peer address 10.0.4.4;
    peer port 647;

    max-response-delay 60;
    max-unacked-updates 10;
    load balance max seconds 3;
}

include "/etc/dhcp/dhcpd.conf.d/subnets.conf";
include "/etc/dhcp/dhcpd.conf.d/reservations.conf";
```

**Шаг 3: Модификация `subnets.conf`**

В каждой подсети указать имя failover-пары внутри блока `pool`:

```ini
subnet 10.0.10.0 netmask 255.255.255.0 {
    option routers 10.0.10.1;

    pool {
        failover peer "dhcp-failover";
        range 10.0.10.100 10.0.10.200;
    }
}
```

**Шаг 4: Настройка файрвола**

На обоих серверах разрешить входящие подключения на **TCP/647**.

### Сценарий 2: Troubleshooting

**Проблема: Серверы не синхронизируются**

```bash
# Проверка логов
sudo journalctl -u isc-dhcp-server -f | grep failover

# Проверка подключения к порту партнёра
telnet 10.0.4.5 647

# Поиск событий failover в логах
grep "failover peer" /var/log/syslog
```

**Проблема: Конфликты IP-адресов**

```bash
# Проверка файлов аренды на обоих серверах
cat /var/lib/dhcp/dhcpd.leases

# Принудительная синхронизация (на secondary)
sudo systemctl stop isc-dhcp-server
sudo rm /var/lib/dhcp/dhcpd.leases~
sudo systemctl start isc-dhcp-server
```

## Additional Information

- [Обзор ISC DHCP и Kea](./isc_dhcp_server_overview.md)
- [Базовая настройка](./isc_dhcp_server_basic_config.md)
- [Резервирование IP](./isc_dhcp_server_reservations.md)
- [DHCP Relay](./isc_dhcp_server_relay.md)
- [Проверка и мониторинг](./isc_dhcp_server_verification.md)
- [Протокол DHCP: теория](../../../../Networking/Protocols/DHCP/dhcp_overview.md)
