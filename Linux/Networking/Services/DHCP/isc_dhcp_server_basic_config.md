# ISC DHCP-сервер: Базовая настройка

> **Важно:** ISC DHCP устарел. Для новых развертываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Конфигурация требует конвертации в JSON.

В данном руководстве описаны шаги по установке и базовой настройке ISC DHCP-сервера.

> **См. также:** [Протокол DHCP: теория и концепции](../../../../Networking/Protocols/DHCP/dhcp_overview.md) — базовые понятия, процесс DORA, время аренды.

## 1. Установка

- **Debian/Ubuntu:**

    ```bash
    sudo apt update
    sudo apt install isc-dhcp-server
    ```

- **RHEL/Rocky Linux/AlmaLinux:**

    ```bash
    sudo dnf install dhcp-server
    ```

## 2. Настройка интерфейса прослушивания

Укажите, на каких сетевых интерфейсах DHCP-сервер должен принимать запросы.

- **Debian/Ubuntu (`/etc/default/isc-dhcp-server`):**

    ```ini
    INTERFACESv4="eth0"
    ```

- **RHEL/CentOS (`/etc/sysconfig/dhcpd`):**

    ```ini
    DHCPDARGS="eth0"
    ```

## 3. Основная конфигурация (`/etc/dhcp/dhcpd.conf`)

Файл состоит из глобальных параметров и секций `subnet` для каждой сети. Всегда делайте резервную копию перед редактированием.

### Пример базового файла конфигурации

```ini
# ГЛОБАЛЬНЫЕ ПАРАМЕТРЫ (ДЕЙСТВУЮТ ДЛЯ ВСЕХ ПОДСЕТЕЙ)

# Если этот сервер является основным в сети, он должен быть авторитативным.
# Это позволяет ему отправлять DHCPNAK для принудительного обновления
# некорректных адресов у клиентов.
authoritative;

# Имя домена и DNS-серверы, передаваемые клиентам.
# Можно использовать публичные DNS или адреса внутренних серверов.
option domain-name "work.example.com";
option domain-name-servers 8.8.8.8, 1.1.1.1;

# Настройки времени аренды по умолчанию (в секундах).
# default: будет использоваться, если клиент не запросил иное.
# max: ограничивает максимальный срок, который может запросить клиент.
default-lease-time 86400;   # 1 день
max-lease-time 604800;      # 7 дней

# Настройка логирования через syslog. Local7 - стандартный facility.
log-facility local7;

# --- СЕКЦИИ ДЛЯ КАЖДОЙ ПОДСЕТИ ---

# Пример 1: Сеть для серверов (VLAN 10)
subnet 10.0.10.0 netmask 255.255.255.0 {
    # Диапазон выдаваемых IP-адресов
    range 10.0.10.100 10.0.10.200;

    # Шлюз для этой подсети
    option routers 10.0.10.1;

    # Переопределение времени аренды для этой конкретной сети
    # Серверы меняются редко, поэтому аренда может быть долгой.
    default-lease-time 2592000; # 30 дней
    max-lease-time 5184000;   # 60 дней
}

# Пример 2: Сеть для пользователей (VLAN 20)
subnet 10.0.20.0 netmask 255.255.255.0 {
    range 10.0.20.50 10.0.20.250;
    option routers 10.0.20.1;
    # Для пользовательской сети можно оставить аренду по умолчанию или сделать короче
}
```

## Распространённые опции DHCP

| Опция | Описание | Пример |
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

---

## Навигация по документации DHCP

| Тема | Файл |
| :--- | :--- |
| **[Обзор и архитектура](./isc_dhcp_server_overview.md)** | Точка входа, Kea DHCP |
| **[Базовая настройка](./isc_dhcp_server_basic_config.md)** | Установка, конфигурация |
| **[Резервирование IP](./isc_dhcp_server_reservations.md)** | Static allocation, маршруты |
| **[Failover](./isc_dhcp_server_failover.md)** | Отказоустойчивость |
| **[DHCP Relay](./isc_dhcp_server_relay.md)** | Ретрансляция между подсетями |
| **[Проверка и мониторинг](./isc_dhcp_server_verification.md)** | Верификация, логи |
| **[Протокол DHCP](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** | Теория, DORA, безопасность |
