# ISC DHCP: Базовая настройка

> **Важно:** Программный стек ISC DHCP официально достиг стадии **EOL (End of Life)**. Для новых инсталляций в 2026 году **настоятельно рекомендуется** использовать **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Данный файл актуален для эксплуатации существующих систем и подготовки к миграции.

---

## Определения

**ISC DHCP (Internet Systems Consortium DHCP)** — классическая программная реализация сервера автоматической настройки узлов. Основным компонентом является демон `dhcpd`.

**Raw Sockets (Сырые сокеты)** — механизм, используемый `dhcpd` для прямого взаимодействия с сетевыми интерфейсами на канальном уровне (L2). Это необходимо для отправки ответов клиентам, которые еще не имеют IP-адреса и не могут быть достигнуты через стандартный стек маршрутизации ОС.

---

## Основные концепции

### Архитектурные требования

1.  **Права доступа:** Из-за работы с сырыми сокетами демон должен запускаться от имени суперпользователя (**root**).
2.  **Целостность данных (Lease Persistence):** `/var/lib/dhcp/dhcpd.leases` является критически важным файлом. Сервер гарантирует, что запись об аренде зафиксирована на диске перед отправкой подтверждения клиенту.
3.  **Авторитарность (Authoritative):** Директива `authoritative;` указывает серверу, что он является основным в данной подсети. Это заставляет его активно исправлять неверные настройки клиентов (отправлять `DHCPNAK`), если те запрашивают адрес из чужой или неактуальной подсети.

### Структура конфигурации

| Путь | Назначение |
| :--- | :--- |
| `/etc/dhcp/dhcpd.conf` | Основная иерархическая конфигурация. |
| `/etc/default/isc-dhcp-server` | Настройка интерфейсов и параметров запуска (Debian/Ubuntu). |
| `/etc/sysconfig/dhcpd` | Настройка интерфейсов и аргументов (RHEL/Rocky). |

---

## Практические сценарии

### Установка пакетов

**Debian / Ubuntu:**
```bash
sudo apt update && sudo apt install isc-dhcp-server -y
# → success
```

**RHEL / Rocky Linux / AlmaLinux:**
```bash
sudo dnf install dhcp-server -y
# → success
```

### Настройка сетевых интерфейсов

Серверу необходимо явно указать, на каких физических или виртуальных интерфейсах ожидать запросы.

**Debian/Ubuntu (`/etc/default/isc-dhcp-server`):**
```ini
INTERFACESv4="eth0 vlan10"
```

**RHEL/Rocky (`/etc/sysconfig/dhcpd`):**
```ini
DHCPDARGS="eth0"
```

### Основная конфигурация (`dhcpd.conf`)

Пример типовой конфигурации с разделением на глобальные параметры и описание подсетей.

```conf
# ГЛОБАЛЬНЫЕ ПАРАМЕТРЫ

# Отключение динамического обновления DNS (обязательно в простых конфигах)
ddns-update-style none;

# Сервер является главным в обслуживаемых сегментах
authoritative;

# Параметры DNS
option domain-name "corp.internal";
option domain-name-servers 10.0.1.10, 8.8.8.8;

# Таймеры аренды (в секундах)
default-lease-time 86400;   # 24 часа
max-lease-time 604800;      # 7 дней

# Настройка логирования (использует syslog facility local7)
log-facility local7;

# ОПРЕДЕЛЕНИЕ КЛАССОВ (Группировка клиентов)
class "voip-phones" {
    match if substring (option vendor-class-identifier, 0, 4) = "Cisco";
}

# ОПРЕДЕЛЕНИЕ ПОДСЕТЕЙ

# Сегмент для обычных рабочих станций
subnet 10.0.10.0 netmask 255.255.255.0 {
    range 10.0.10.100 10.0.10.250;
    option routers 10.0.10.1;
    option broadcast-address 10.0.10.255;
    
    # Пул с дополнительными опциями для конкретного класса
    pool {
        allow members of "voip-phones";
        range 10.0.10.50 10.0.10.99;
        option tftp-server-name "10.0.10.5";
    }
}
```

### Валидация и запуск

Перед перезапуском службы **обязательно** проверяйте синтаксис:

```bash
# Проверка синтаксиса (флаг -t)
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
# → Internet Systems Consortium DHCP Server ...
# → Configuration file errors encountered -- exiting [если есть ошибки]
# → success (no errors)

# Перезапуск сервиса
sudo systemctl restart isc-dhcp-server
# → active (running)
```

---

## Справочник DHCP-опций

| Опция | Описание | Пример значения |
| :--- | :--- | :--- |
| `option routers` | IP шлюза по умолчанию. | `10.0.10.1` |
| `option domain-name-servers` | Список DNS-резолверов. | `1.1.1.1, 8.8.8.8` |
| `option domain-name` | Домен поиска для коротких имен. | `"example.com"` |
| `option ntp-servers` | Список серверов времени. | `ntp1.pool.org` |
| `option tftp-server-name` | Адрес сервера для загрузки (**PXE**). | `"10.0.10.5"` |
| `option bootfile-name` | Имя загрузочного файла (**iPXE/GRUB**). | `"ipxe.efi"` |

---

## Дополнительная информация

### Логирование и отладка

По умолчанию `dhcpd` пишет логи в `syslog` (обычно в `/var/log/syslog` или `/var/log/messages`). Для выделения логов DHCP в отдельный файл:
1.  Установите `log-facility local7;` в `dhcpd.conf`.
2.  Добавьте в конфигурацию `/etc/rsyslog.conf`:
    `local7.* /var/log/dhcpd.log`
3.  Перезапустите `rsyslog`.

### Связанные разделы

*   **[Обзор ISC DHCP](./isc_dhcp_server_overview.md)** — архитектура и компоненты системы.
*   **[Протокол DHCP — Теория](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** — детальный разбор процесса DORA.
*   **[Резервирование IP-адресов](./isc_dhcp_server_reservations.md)** — статическая привязка к MAC.
*   **[Отказоустойчивость (Failover)](./isc_dhcp_server_failover.md)** — создание HA-пары серверов.
*   **[Диагностика и проверка](./isc_dhcp_server_verification.md)** — глубокий анализ трафика и логов.
*   **[Настройка DHCP Relay](./isc_dhcp_server_relay.md)** — работа в сегментированных сетях.
