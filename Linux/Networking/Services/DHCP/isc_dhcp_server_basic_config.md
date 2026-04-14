# ISC DHCP-сервер: Базовая настройка

> **Важно:** ISC DHCP достиг EOL в 2022 году ([подтверждение](https://endoflife.date/isc-dhcp)). Для новых развёртываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp--современная-альтернатива)**. Данный файл актуален для поддержки существующих систем и миграции.

## Определения

**ISC DHCP-сервер** — демон `dhcpd` (или `isc-dhcp-server`), реализация DHCP-протокола от Internet Systems Consortium для автоматической выдачи IP-адресов и сетевых параметров клиентам.

> **См. также:** [Обзор ISC DHCP и архитектура](./isc_dhcp_server_overview.md) — точка входа в документацию, сравнение с Kea.  
> **См. также:** [Протокол DHCP: теория и концепции](../../../../Networking/Protocols/DHCP/dhcp_overview.md) — базовые понятия, процесс DORA, время аренды.

## Базовые концепции

### Структура конфигурации

- `/etc/dhcp/dhcpd.conf` — основной файл конфигурации (иерархическая структура: глобальные параметры → переопределения в `subnet`)
- `/etc/default/isc-dhcp-server` (Debian/Ubuntu) — указание интерфейсов прослушивания
- `/etc/sysconfig/dhcpd` (RHEL/CentOS) — аналогичный файл для RPM-дистрибутивов
- Резервное копирование обязательно перед редактированием

### Принцип работы

- Сервер читает конфигурацию при старте
- Глобальные параметры действуют для всех подсетей, если не переопределены в `subnet`
- Файл аренды: `/var/lib/dhcp/dhcpd.leases` (Debian) или `/var/lib/dhcpd/dhcpd.leases` (RHEL)

## Практические сценарии

### Установка

**Debian/Ubuntu:**

```bash
sudo apt update
sudo apt install isc-dhcp-server
```

**RHEL/Rocky Linux/AlmaLinux:**

```bash
sudo dnf install dhcp-server
```

### Настройка интерфейса прослушивания

Указание сетевого интерфейса для приёма DHCP-запросов:

**Debian/Ubuntu** (`/etc/default/isc-dhcp-server`):

```ini
INTERFACESv4="eth0"
```

**RHEL/CentOS** (`/etc/sysconfig/dhcpd`):

```ini
DHCPDARGS="eth0"
```

### Основная конфигурация (`/etc/dhcp/dhcpd.conf`)

Пример минимального рабочего конфига для двух подсетей:

```ini
# ГЛОБАЛЬНЫЕ ПАРАМЕТРЫ

# Авторитетный сервер (отправка DHCPNAK для некорректных адресов)
authoritative;

# Домен и DNS-серверы для клиентов
option domain-name "work.example.com";
option domain-name-servers 8.8.8.8, 1.1.1.1;

# Время аренды (секунды)
default-lease-time 86400;   # 1 день
max-lease-time 604800;      # 7 дней

# Логирование через syslog
log-facility local7;

# Сеть для серверов (VLAN 10)
subnet 10.0.10.0 netmask 255.255.255.0 {
    range 10.0.10.100 10.0.10.200;
    option routers 10.0.10.1;
    default-lease-time 2592000; # 30 дней (серверы редко меняются)
    max-lease-time 5184000;     # 60 дней
}

# Сеть для пользователей (VLAN 20)
subnet 10.0.20.0 netmask 255.255.255.0 {
    range 10.0.20.50 10.0.20.250;
    option routers 10.0.20.1;
    # Время аренды — глобальные значения (1 день)
}
```

### Распространённые DHCP-опции

| Опция | Назначение | Пример |
| :--- | :--- | :--- |
| `option domain-name` | Доменное имя | `"example.com"` |
| `option domain-name-servers` | DNS-серверы | `8.8.8.8, 1.1.1.1` |
| `option routers` | Шлюз по умолчанию | `10.0.10.1` |
| `option subnet-mask` | Маска подсети | `255.255.255.0` |
| `option broadcast-address` | Broadcast-адрес | `10.0.10.255` |
| `option ntp-servers` | NTP-серверы | `pool.ntp.org` |
| `option netbios-name-servers` | WINS-серверы | `10.0.10.5` |
| `option tftp-server-name` | TFTP-сервер (PXE) | `"tftp.example.com"` |
| `option bootfile-name` | Файл загрузки (PXE) | `"undionly.kpxe"` |

## Дополнительная информация

### Связанные темы

- [Резервирование IP-адресов](./isc_dhcp_server_reservations.md) — static allocation для конкретных клиентов
- [Failover-конфигурация](./isc_dhcp_server_failover.md) — отказоустойчивость DHCP-сервера
- [DHCP Relay](./isc_dhcp_server_relay.md) — ретрансляция запросов между VLAN
- [Проверка и мониторинг](./isc_dhcp_server_verification.md) — валидация конфига, логи, troubleshooting
