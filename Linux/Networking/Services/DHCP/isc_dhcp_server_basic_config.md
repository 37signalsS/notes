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

### Предварительные требования и подготовка окружения

Перед установкой и запуском `dhcpd` проверьте окружение:

1.  **Сетевой интерфейс:** Интерфейс, указанный в конфигурации запуска, должен находиться в состоянии `UP` и иметь статический IP-адрес из обслуживаемой подсети. DHCP-сервер не может обслуживать сегмент, если сам находится в нём через динамический адрес от другого сервера.
2.  **Права суперпользователя:** Все операции установки, редактирования конфигурации и управления службой требуют `sudo` или прямого доступа `root`.
3.  **Порты:** UDP 67 (сервер) и UDP 68 (клиент) должны быть доступны на интерфейсах обслуживания. На хосте, где установлен `dhcpd`, порт 67 обычно слушается только на указанных интерфейсах.
4.  **Хранилище:** Раздел, на котором находится `/var/lib/dhcp/`, должен быть достаточно надёжным. На SSD/NVMe влияние задержки `fsync` минимально; на устаревших HDD при большой частоте аренд (например, `default-lease-time 60`) возможны задержки в десятки миллисекунд на каждую запись.

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

### Проверка готовности интерфейсов

Перед запуском службы убедитесь, что интерфейсы активны и имеют корректные адреса:

```bash
# Проверка состояния всех интерфейсов
ip -brief addr show

# Проверка, что интерфейс UP и имеет IP из обслуживаемой подсети
ip -4 addr show eth0 | grep inet
# → inet 10.0.10.1/24 brd 10.0.10.255 scope global dynamic eth0

# Если интерфейс DOWN — служба dhcpd не запустится или будет слушать на всех интерфейсах
ip link set eth0 up
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

### Динамическое обновление DNS (DDNS)

Для автоматического создания записей A/PTR в DNS-сервере (например, BIND9) используйте `ddns-update-style interim` с TSIG-ключом:

```bash
# 1. Создание секретного ключа для nsupdate/BIND
dnssec-keygen -a HMAC-SHA512 -b 512 -n HOST dhcp-update-key
# → Kdhcp-update-key.+165.+9999999999.key

# 2. Извлечение секрета
cat Kdhcp-update-key.+165.+9999999999.private | grep "^Key"
# → Key "XXXXX..."

# 3. Добавление ключа в dhcpd.conf (глобально)
key dhcp-update-key {
    algorithm HMAC-SHA512;
    secret "XXXXX...";
}
ddns-update-style interim;
ddns-domainname "corp.internal";
zone corp.internal. {
    primary 10.0.1.10; # IP DNS-сервера
    key dhcp-update-key;
}

# 4. Разрешение обновлений в BIND (allow-update)
# В named.conf.local:
zone "corp.internal" IN {
    type master;
    file "/etc/bind/db.corp.internal";
    allow-update { key dhcp-update-key; };
};
```

### Классификация клиентов

Классы позволяют применять политики к группам устройств:

```conf
# Классификация по Vendor Class Identifier (VCI)
class "printers" {
    match if substring (option vendor-class-identifier, 0, 6) = "HP Jet";
}

# Классификация по MAC-префиксу (OUI)
class "apple-devices" {
    match if binary-to-ascii (16, 8, ":", substring(hardware, 1, 3)) = "ac:de:48";
}

# Применение класса к пулу
subnet 10.0.20.0 netmask 255.255.255.0 {
    pool {
        allow members of "printers";
        range 10.0.20.50 10.0.20.100;
        option printers 10.0.20.10; # Пример специфичной опции
    }
}
```

### Маршрутизация (Classless Static Routes — Option 121)

Для передачи маршрутов, отличных от шлюза по умолчанию, используйте опцию 121 (RFC 3442):

```conf
subnet 10.0.30.0 netmask 255.255.255.0 {
    range 10.0.30.100 10.0.30.200;
    
    # Стандартный шлюз (для клиентов, не поддерживающих опцию 121)
    option routers 10.0.30.1;

    # RFC 3442: список маршрутов в формате <бит_маски>, <байты_сети>, <шлюз>
    # Пример: сеть 172.16.0.0/16 через 10.0.30.254 + маршрут по умолчанию
    option rfc3442-classless-static-routes 
        16, 172, 16, 10, 0, 30, 254, 
        0, 10, 0, 30, 1;
}
```

### Интеграция с PXE Boot

Для загрузки по сети добавьте опции 66 (TFTP-сервер) и 67 (загрузочный файл):

```conf
subnet 10.0.40.0 netmask 255.255.255.0 {
    range 10.0.40.100 10.0.40.200;
    option routers 10.0.40.1;

    # Для BIOS-клиентов
    class "pxe-clients" {
        match if substring (option vendor-class-identifier, 0, 9) = "PXEClient";
        filename "pxelinux.0";
        next-server 10.0.40.10;
    }

    # Для UEFI-клиентов
    class "uefi-pxe" {
        match if substring (option vendor-class-identifier, 0, 10) = "HTTPClient";
        filename "grubx64.efi";
        next-server 10.0.40.10;
    }
}
```

### Режим «Белого списка» (unknown-clients)

Чтобы запретить выдачу адресов клиентам, не указанным явно:

```conf
# Глобально запретить неизвестных клиентов
authoritative;
deny unknown-clients;

subnet 10.0.50.0 netmask 255.255.255.0 {
    # Без range — адреса выдаются только через host declarations
    option routers 10.0.50.1;
}

host known-server {
    hardware ethernet 00:11:22:33:44:55;
    fixed-address 10.0.50.10;
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

### Служба systemd и безопасность

#### Пакетный hardening через override

Создайте override-файл для ограничения возможностей демона:

```bash
sudo systemctl edit isc-dhcp-server
```

Добавьте в редакторе:

```ini
[Service]
# Ограничение доступа к файловой системе
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=yes
NoNewPrivileges=yes

# Capabilities: только NET_RAW и NET_ADMIN (для raw сокетов)
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN

# Ограничение доступа к сети
RestrictAddressFamilies=AF_INET AF_INET6 AF_NETLINK

# Запрет на изменение системных настроек
ProtectControlGroups=yes
ProtectKernelModules=yes
ProtectKernelTunables=yes
```

Примените изменения:

```bash
sudo systemctl daemon-reload
sudo systemctl restart isc-dhcp-server
# → active (running)
```

> **Примечание:** На RHEL/Rocky имя службы — `dhcpd`. Используйте `sudo systemctl edit dhcpd`.

### Межсетевые экраны

Откройте порты DHCP на интерфейсах обслуживания.

**Debian / Ubuntu (UFW):**
```bash
sudo ufw allow in on eth0 to any port 67 proto udp comment "DHCP Server"
sudo ufw allow in on eth0 to any port 68 proto udp comment "DHCP Client"
```

**RHEL / Rocky / Alma (firewalld):**
```bash
sudo firewall-cmd --add-service=dhcp --permanent
sudo firewall-cmd --reload
# → success
```

**Универсально (nftables):**
```bash
sudo nft add rule inet filter input udp dport 67 accept
sudo nft add rule inet filter input udp dport 68 accept
```

### SELinux и AppArmor

#### RHEL / Rocky / AlmaLinux (SELinux)

При ошибках доступа к файлам leases или сокетам проверьте контекст:

```bash
# Разрешить dhcpd доступ к сети и файлам
sudo setsebool -P dhcpd_run_roothw 1
sudo setsebool -P dhcpd_use_nfs 1 # Если leases на NFS

# Проверка AVC-отказов
sudo ausearch -m avc -ts recent | grep dhcpd
```

#### Debian / Ubuntu (AppArmor)

Проверьте статус профиля:

```bash
sudo aa-status | grep dhcp
# → /usr/sbin/dhcpd confined by profile ... (enforced)

# Если возникают ошибки доступа — переключите в complain-режим
sudo aa-complain /usr/sbin/dhcpd
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
| `option rfc3442-classless-static-routes` | Статические маршруты (RFC 3442). | `16, 172, 16, 10, 0, 30, 254` |
| `option wpad-url` | URL конфигурации WPAD (Proxy Auto-Config). | `"http://wpad.corp.internal/wpad.dat"` |
| `option vendor-class-identifier` | Идентификатор класса клиента (PXE, VoIP). | `"PXEClient:Arch:00000"` |
| `option dhcp-client-identifier` | Client Identifier (RFC 2132). | `1:00:11:22:33:44:55` |
| `option dhcp-server-identifier` | IP-адрес DHCP-сервера (принудительно). | `10.0.10.1` |
| `option subnet-mask` | Маска подсети (обычно определяется автоматически). | `255.255.255.0` |
| `option broadcast-address` | Широковещательный адрес. | `10.0.10.255` |

---

## Управление базой аренд

### Ротация и очистка

Файл аренды дополняется новыми записями в конец. При большой нагрузке файл может разрастаться. Для ротации без потери данных:

```bash
# 1. Остановка сервиса (только для полной ротации)
sudo systemctl stop isc-dhcp-server

# 2. Ротация
sudo mv /var/lib/dhcp/dhcpd.leases /var/lib/dhcp/dhcpd.leases.1
sudo cp /var/lib/dhcp/dhcpd.leases.1 /var/lib/dhcp/dhcpd.leases

# 3. Запуск
sudo systemctl start isc-dhcp-server
```

### Очистка заброшенных адресов (Abandoned)

Адреса помечаются как `abandoned` при получении `DHCPDECLINE`. Для освобождения:

```bash
# 1. Просмотр заброшенных адресов
sudo grep -i "abandoning" /var/lib/dhcp/dhcpd.leases
# → DHCPDECLINE of 10.0.10.50 from 00:11:22:33:44:55 via eth0: address in use!

# 2. Проверка наличия адреса в сети
sudo arping -D -I eth0 10.0.10.50 -c 3
# → Sent 3 probes (0 duplicates) — адрес свободен

# 3. Ручное освобождение через omshell (или редактирование файла)
omshell
> server localhost
> port 7911
> key omapi-key "..."
> connect
> new lease
> set ip-address = 10.0.10.50
> open
> set binding-state = free
> update
> exit
```

### Восстановление после повреждения

Если файл `dhcpd.leases` повреждён, восстановите его из резервной копии:

```bash
# 1. Остановка сервиса
sudo systemctl stop isc-dhcp-server

# 2. Восстановление
sudo cp /backup/dhcpd.leases.$(date +%Y%m%d) /var/lib/dhcp/dhcpd.leases

# 3. Проверка формата (последняя запись должна заканчиваться на '}')
tail -5 /var/lib/dhcp/dhcpd.leases

# 4. Запуск
sudo systemctl start isc-dhcp-server
```

---

## Дополнительная информация

### Логирование и отладка

По умолчанию `dhcpd` пишет логи в `syslog` (обычно в `/var/log/syslog` или `/var/log/messages`). Для выделения логов DHCP в отдельный файл:
1.  Установите `log-facility local7;` в `dhcpd.conf`.
2.  Добавьте в конфигурацию `/etc/rsyslog.conf`:
    `local7.* /var/log/dhcpd.log`
3.  Перезапустите `rsyslog`.

### Эксплуатация и бэкап

```bash
# Проверка активных аренд
sudo cat /var/lib/dhcp/dhcpd.leases | grep "binding state active" | wc -l

# Поиск аренды по MAC
sudo grep "00:11:22:33:44:55" /var/lib/dhcp/dhcpd.leases -A 10

# Мониторинг логов в реальном времени
sudo journalctl -u isc-dhcp-server -f

# Поиск ошибок за последний час
sudo journalctl -u isc-dhcp-server --since "1 hour ago" | grep -iE "error|fail|abandon"
```

### Частые проблемы базовой настройки

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Служба не запускается | Интерфейс не указан или DOWN | `journalctl -u isc-dhcp-server -n 20` | Указать интерфейс в `/etc/default/isc-dhcp-server` или `/etc/sysconfig/dhcpd` |
| Клиенты не получают адрес | Синтаксическая ошибка в `dhcpd.conf` | `sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf` | Исправить ошибку (пропущена `;`, незакрыта `}`) |
| Нет адресов (no free leases) | Пулы исчерпаны | `grep "no free leases" /var/log/syslog` | Увеличить `range` или сократить `default-lease-time` |
| Клиент получает 169.254.x.x | Ответ не доходит до клиента | `tcpdump -i eth0 port 67 or port 68` | Проверить VLAN, Relay, фаерволл |
| Permission denied на leases | Неправильные права на файл | `ls -la /var/lib/dhcp/dhcpd.leases` | `sudo chown dhcpd:dhcpd /var/lib/dhcp/dhcpd.leases` |
| Дублирующиеся IP | Два сервера в одной подсети | `grep "duplicate" /var/log/syslog` | Использовать `authoritative;` или настроить Failover |

### Связанные разделы

*   **[Обзор ISC DHCP](./isc_dhcp_server_overview.md)** — архитектура и компоненты системы.
*   **[Протокол DHCP — Теория](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** — детальный разбор процесса DORA.
*   **[Резервирование IP-адресов](./isc_dhcp_server_reservations.md)** — статическая привязка к MAC.
*   **[Отказоустойчивость (Failover)](./isc_dhcp_server_failover.md)** — создание HA-пары серверов.
*   **[Диагностика и проверка](./isc_dhcp_server_verification.md)** — глубокий анализ трафика и логов.
*   **[Настройка DHCP Relay](./isc_dhcp_server_relay.md)** — работа в сегментированных сетях.
