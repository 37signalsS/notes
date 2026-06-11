# ISC DHCP Failover — отказоустойчивая пара серверов

> **Важно:** ISC DHCP устарел (EOL, End of Life). Для новых развёртываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)** с поддержкой HA (High Availability) через hook-модули.
> См. также: [Защита от rogue DHCP](../../../../Networking/Protocols/DHCP/dhcp_security.md).

## Определения

**DHCP Failover** — механизм высокой доступности (HA, High Availability), при котором два DHCP-сервера синхронизируют информацию об арендах и подменяют друг друга при сбое.

**Primary / Secondary** — роли серверов в паре. Оба способны выдавать адреса, но primary (основной) имеет приоритет при управлении пулом.

**MCLT (Max Client Lead Time)** — максимальное время, на которое сервер может продлить аренду без согласования с партнёром.

**Split** — параметр распределения пула адресов между серверами (от 0 до 256, где 128 соответствует 50/50).

## Основные концепции

### Принцип работы

1. **Два сервера:** один настраивается как `primary`, другой как `secondary`.
2. **Синхронизация:** обмен информацией об арендах происходит по протоколу TCP (Transmission Control Protocol) через порт 647.
3. **Разделение нагрузки:** пул IP-адресов (Internet Protocol) делится параметром `split`, что позволяет обоим серверам отвечать на запросы клиентов.

> **См. также:** [Механизмы Failover](../../../../Concepts/High_Availability/ha_failover_mechanisms.md) — общие принципы Heartbeat, Quorum и Split-Brain.

### Состояния отказоустойчивой пары

| Состояние | Описание |
| :--- | :--- |
| `normal` / `balanced` | Оба сервера работают, синхронизация активна |
| `communications-interrupted` | Потеря связи между серверами |
| `partner-down` | Партнёр считается неработающим |
| `potentially-down` | Требуется подтверждение состояния партнёра |
| `reboot` | Сервер перезапускается после сбоя |
| `shutdown` | Сервер остановлен администратором |
| `paused` | Временная приостановка обработки запросов |

## Практические сценарии

### Настройка отказоустойчивой пары

#### Шаг 1: Организация конфигурационных файлов

Рекомендуется вынести общие части в отдельные файлы и подключать их через директиву `include`:

- `/etc/dhcp/dhcpd.conf` — уникальные параметры отказоустойчивости каждого сервера.
- `/etc/dhcp/dhcpd.conf.d/subnets.conf` — общие определения подсетей (`subnet`).
- `/etc/dhcp/dhcpd.conf.d/reservations.conf` — общие определения резерваций (`host`).

#### Шаг 2: Конфигурация dhcpd.conf

**Primary сервер (10.0.4.4):**

```bash
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

**Secondary сервер (10.0.4.5):**

```bash
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

#### Шаг 3: Модификация subnets.conf

В каждой подсети необходимо указать имя отказоустойчивой пары внутри блока `pool`:

```bash
subnet 10.0.10.0 netmask 255.255.255.0 {
    option routers 10.0.10.1;

    pool {
        failover peer "dhcp-failover";
        range 10.0.10.100 10.0.10.200;
    }
}
```

#### Шаг 4: Настройка межсетевого экрана

На обоих серверах необходимо разрешить входящие подключения на порт **TCP/647**.

### Решение проблем

**Проблема: Серверы не синхронизируются**

```bash
# Проверка логов
sudo journalctl -u isc-dhcp-server -f | grep failover

# Проверка подключения к порту партнёра
telnet 10.0.4.5 647

# Поиск событий failover в системных логах
grep "failover peer" /var/log/syslog
```

**Проблема: Конфликты IP-адресов**

```bash
# Проверка файлов аренды на обоих серверах
cat /var/lib/dhcp/dhcpd.leases

# Принудительная синхронизация (на стороне secondary)
sudo systemctl stop isc-dhcp-server
sudo rm /var/lib/dhcp/dhcpd.leases~
sudo systemctl start isc-dhcp-server
```

## Дополнительная информация

- [Обзор ISC DHCP и архитектура](./isc_dhcp_server_overview.md)
- [Протокол DHCP: теория и концепции](../../../../Networking/Protocols/DHCP/dhcp_overview.md)
- [Механизмы Failover и Heartbeat](../../../../Concepts/High_Availability/ha_failover_mechanisms.md)
