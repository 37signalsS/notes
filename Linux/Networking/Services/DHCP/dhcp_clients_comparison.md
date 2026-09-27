# DHCP-клиенты Linux: dhclient vs NetworkManager vs systemd-networkd

---

## Определения

**DHCP-клиент** — программный компонент, реализующий клиентскую сторону протокола DHCP. Отвечает за отправку DHCPDISCOVER, обработку DHCPOFFER, отправку DHCPREQUEST и настройку сетевого интерфейса на основе полученных параметров (IP, шлюз, DNS).

**dhclient** — классический DHCP-клиент ISC, используемый по умолчанию во многих дистрибутивах. Работает как отдельный демон, управляет аренодами через файлы `/var/lib/dhcp/dhclient.leases`.

**NetworkManager (NM)** — демон управления сетью, включающий встроенный DHCP-клиент. Используется в десктопных средах и RHEL/CentOS/Fedora. Поддерживает несколько backends DHCP (internal, dhclient).

**systemd-networkd** — легковесный демон управления сетью от systemd. Встроенный DHCP-клиент работает асинхронно через `systemd-networkd`. Используется в серверных средах, контейнерах и Ubuntu Server.

---

## Основные концепции

### Сравнение DHCP-клиентов

| Параметр | dhclient | NetworkManager | systemd-networkd |
|:--- |:--- |:--- |:--- |
| **Пакет** | `isc-dhcp-client` | `network-manager` | `systemd` (встроен) |
| **Файл конфигурации** | `/etc/dhcp/dhclient.conf` | `/etc/NetworkManager/system-connections/*.nmconnection` | `/etc/systemd/network/*.network` |
| **Файл аренды** | `/var/lib/dhcp/dhclient.leases` | `/var/lib/NetworkManager/internal-*.lease` | `/run/systemd/netif/leases/` |
| **Демон** | `dhclient` (отдельный процесс) | `NetworkManager` | `systemd-networkd` |
| **Управление** | `dhclient` CLI | `nmcli`, `nmtui` | `networkctl`, `networkd` |
| **IPv6** | DHCPv6 (через `dhclient -6`) | Полная поддержка | SLAAC + DHCPv6 |
| **DDNS** | ISC DDNS | Встроенный | Нет (через `networkd-resolved`) |
| **Multi-interface** | По одному на интерфейс | Централизованно | Централизованно |
| **Идемпотентность** | Нет | Да | Да |
| **Окружение** | Универсальный | Desktop, RHEL, Fedora | Server, containers, Ubuntu |

### Когда использовать каждого клиента

| Сценарий | Рекомендуемый клиент | Обоснование |
|:--- |:--- |:--- |
| **Серверы RHEL/Rocky/Alma** | NetworkManager | Стандарт RHEL 9+, полная поддержка |
| **Серверы Ubuntu/Debian** | systemd-networkd | Минимальные зависимости, быстрый старт |
| **Desktop (GNOME/KDE)** | NetworkManager | GUI-интеграция, Wi-Fi, roaming |
| **Контейнеры** | systemd-networkd | Минимальный footprint |
| **Лабораторные среды** | dhclient | Гибкость, ручная настройка |
| **Встраиваемые системы** | systemd-networkd | Минимальные зависимости |

### Жизненный цикл DHCP-клиента

```
Клиент                          DHCP-сервер (Kea)
  │                                   │
  │── DHCPDISCOVER (Broadcast) ──────>│  t=0
  │                                   │
  │<── DHCPOFFER (Unicast/Broadcast) ─│  t=50-200ms
  │                                   │
  │── DHCPREQUEST (Broadcast) ───────>│  t=200ms
  │                                   │  (fsync в lease)
  │<── DHCPACK (Unicast) ────────────│  t=250-500ms
  │                                   │
  │  [Настройка IP]                    │
  │  ip addr add <IP>/<mask> dev eth0 │
  │  ip route add default via <GW>    │
  │                                   │
  │  [T1 = 50% lease]                 │
  │── DHCPREQUEST (Unicast) ─────────>│  Продление
  │<── DHCPACK ───────────────────────│
  │                                   │
  │  [T2 = 87.5% lease]               │
  │── DHCPREQUEST (Broadcast) ───────>│  Повторное связывание
  │<── DHCPACK ───────────────────────│
```

---

## Практические сценарии

### 1. dhclient: конфигурация и управление

**Файл конфигурации (`/etc/dhcp/dhclient.conf`):**

```conf
# Основные параметры
timeout 30;
retry 60;
reboot 10;
select-timeout 5;
initial-interval 2;

# Опции, запрашиваемые у сервера
request subnet-mask, broadcast-address, routers,
       domain-name, domain-name-servers, host-name,
       ntp-servers;

# Отправка пользовательских опций
option classless-static-routes code 121 = array of unsigned integer 8;
send dhcp-classless-static-routes 16, 172, 16, 10, 0, 30, 254;

# Предпочтительный интерфейс
interface "eth0";

# Скрипт при получении/потере аренды
script "/etc/dhcp/dhclient-exit-hooks.d/logging";
```

**Управление через CLI:**

```bash
# Принудительное обновление аренды
sudo dhclient -r eth0  # Release
sudo dhclient -v eth0  # Принудительный DORA

# Просмотр текущей аренды
cat /var/lib/dhcp/dhclient.leases

# Пример вывода:
# lease {
#   interface "eth0";
#   fixed-address 10.0.10.100;
#   option subnet-mask 255.255.255.0;
#   option routers 10.0.10.1;
#   option dhcp-lease-time 86400;
#   option dhcp-message-type 5;
#   option dhcp-server-identifier 10.0.0.1;
#   renew 4 2026/08/26 12:00:00;
#   rebind 4 2026/08/26 18:48:00;
#   expire 4 2026/08/27 00:00:00;
# }

# Остановка dhclient
sudo killall dhclient

# Запуск в фоновом режиме
sudo dhclient -nw eth0
```

**Exit hooks (событийные скрипты):**

```bash
#!/bin/bash
# /etc/dhcp/dhclient-exit-hooks.d/logging

case "$reason" in
  BOUND|RENEW|REBIND|REBOOT)
    logger "DHCP: $reason - IP=$new_ip_address GW=$new_routers"
    ;;
  EXPIRE|FAIL|RELEASE)
    logger "DHCP: $reason - потеря адреса"
    ;;
esac
```

### 2. NetworkManager: управление DHCP

**Настройка через nmcli:**

```bash
# Просмотр DHCP-параметров соединения
nmcli connection show eth0 | grep -E "ipv4\.(method|addresses|gateway|dns)"

# Установка DHCP
nmcli connection modify eth0 ipv4.method auto
nmcli connection modify eth0 ipv4.dhcp-send-hostname yes
nmcli connection modify eth0 ipv4.dhcp-hostname "srv-web-01"

# Принудительное обновление DHCP
nmcli connection up eth0

# Просмотр текущей аренды
nmcli device show eth0 | grep -E "IP4\.(ADDRESS|GATEWAY|DNS)"

# Просмотр DHCP-аренд NetworkManager
cat /var/lib/NetworkManager/internal-*.lease

# Настройка таймаутов DHCP
nmcli connection modify eth0 ipv4.dhcp-timeout 60
nmcli connection modify eth0 ipv4.dhcp-retry 3
```

**Конфигурация через keyfile:**

```ini
# /etc/NetworkManager/system-connections/eth0.nmconnection
[connection]
id=eth0
type=ethernet
autoconnect=yes

[ipv4]
method=auto
dhcp-send-hostname=yes
dhcp-hostname=srv-web-01
dns-search=corp.example.com;

[ipv6]
method=auto
dhcp-send-hostname=yes
```

**Dispatcher-скрипт для DHCP-событий:**

```bash
#!/bin/bash
# /etc/NetworkManager/dispatcher.d/99-dhcp-logging

INTERFACE=$1
ACTION=$2

case "$ACTION" in
  up)
    if nmcli -t -f TYPE con show --active | grep -q ethernet; then
      IP=$(nmcli -t -f IP4.ADDRESS device show "$INTERFACE" | cut -d: -f2)
      logger "NM: $INTERFACEUP - IP=$IP"
    fi
    ;;
  down)
    logger "NM: $INTERFACEDOWN"
    ;;
esac
```

### 3. systemd-networkd: конфигурация DHCP

**Базовая конфигурация:**

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
DHCP=yes
# Или более детально:
# DHCP=ipv4

[DHCPv4]
# Таймауты
TimeoutSec=30
# Опции
SendHostname=srv-web-01
SendHostnameRoute=no
UseDNS=yes
UseNTP=yes
UseDomains=corp.example.com
# Безопасность
Anonymize=no

[Route]
Gateway=onlink
```

**DHCPv6 + SLAAC:**

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
DHCP=ipv6
IPv6AcceptRA=yes

[DHCPv6]
SendHostname=yes
UseDNS=yes
UseNTP=yes

[IPv6AcceptRA]
DHCPv6Client=always
```

**Управление через CLI:**

```bash
# Просмотр статуса
networkctl status eth0

# Просмотр DHCP-аренд
networkctl status eth0 | grep -A5 "DHCP"

# Просмотр lease-файла
cat /run/systemd/netif/leases/$(networkctl list eth0 | grep -oP '\d+')

# Перезапуск DHCP для интерфейса
sudo networkctl reconfigure eth0

# Принудительное обновление
sudo networkctl renew eth0

# Остановка DHCP
sudo networkctl forget eth0
```

### 4. Диагностика проблем с DHCP-клиентами

**Таблица проблем и решений:**

| Проблема | dhclient | NetworkManager | systemd-networkd |
|:--- |:--- |:--- |:--- |
| **Не получает IP** | `dhclient -v eth0` (VERBOSE) | `nmcli device status` | `networkctl status eth0` |
| **Получает APIPA** | Проверить `/var/log/syslog` | `journalctl -u NetworkManager` | `journalctl -u systemd-networkd` |
| **Теряет IP** | Проверить lease-файл | `nmcli connection show` | `networkctl status eth0` |
| **DNS не работает** | Проверить `/etc/resolv.conf` | `nmcli device show eth0` | `resolvectl status eth0` |
| **Не продлевает аренду** | Проверить T1/T2 в lease | `journalctl -u NetworkManager` | `journalctl -u systemd-networkd` |
| **Конфликт IP (NAK)** | `dhclient -r` + `dhclient` | `nmcli connection down/up` | `networkctl reconfigure eth0` |

**Сравнение логов:**

```bash
# dhclient
journalctl -u dhclient -f
# Или
tail -f /var/log/syslog | grep dhclient

# NetworkManager
journalctl -u NetworkManager -f | grep -i dhcp

# systemd-networkd
journalctl -u systemd-networkd -f | grep -i dhcp
```

### 5. Выбор клиента для серверов с Kea DHCP

**Рекомендации:**

| ОС | Клиент по умолчанию | Рекомендация |
|:--- |:--- |:--- |
| **RHEL/Rocky 9+** | NetworkManager | Используйте NM (стандарт) |
| **Ubuntu 22.04+ Server** | systemd-networkd | Используйте systemd-networkd |
| **Debian 12** | dhclient | Рассмотрите systemd-networkd |
| **CentOS 7/8** | dhclient / NM | NM (если установлен) |
| **Arch Linux** | dhclient | systemd-networkd |

**Интеграция с Kea:**

Kea DHCP совместим со всеми клиентами. Особенности:
- **dhclient:** Классический, надёжный. Отправляет Option 60 (Vendor Class) по умолчанию.
- **NetworkManager:** Отправляет hostname через Option 12. Поддерживает DHCPv6+SLAAC.
- **systemd-networkd:** Минимальный footprint. Отправляет Option 55 (Parameter Request List) с базовым набором опций.

### 6. Оптимизация DHCP-клиентов для production

**Быстрое восстановление связи:**

```bash
# dhclient: уменьшение таймаутов
# /etc/dhcp/dhclient.conf
timeout 10;
retry 5;
initial-interval 1;

# NetworkManager: оптимизация
nmcli connection modify eth0 ipv4.dhcp-timeout 30
nmcli connection modify eth0 ipv4.dhcp-retry 3

# systemd-networkd: оптимизация
# [DHCPv4]
# TimeoutSec=30
# Retries=3
```

**Сохранение IP при перезагрузке:**

```bash
# dhclient: без изменений (хранит lease в файле)
# NetworkManager: по умолчанию сохраняет
# systemd-networkd: по умолчанию сохраняет в /run/systemd/netif/leases/
```

---

## Дополнительная информация

### Сравнение форматов lease-файлов

| Параметр | dhclient | NetworkManager | systemd-networkd |
|:--- |:--- |:--- |:--- |
| **Расширение** | `.leases` | `.lease` | Нет (внутренний) |
| **Формат** | Текстовый (ISC) | JSON | JSON |
| **Путь** | `/var/lib/dhcp/` | `/var/lib/NetworkManager/` | `/run/systemd/netif/leases/` |
| **Ротация** | Автоматическая | Автоматическая | Автоматическая |

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — серверная сторона Kea.
- **[Время аренды](../../../Networking/Protocols/DHCP/dhcp_lease_time.md)** — таймеры T1/T2 и типы сообщений.
- **[Диагностика DHCP](../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)** — анализ трафика.
- **[Настройка сети в RHEL](../../Settings/Persistent_Network/centos_rhel_networkmanager.md)** — NetworkManager в RHEL.
- **[Настройка сети в Ubuntu](../../Settings/Persistent_Network/ubuntu_netplan.md)** — Netplan + systemd-networkd.
- **[systemd-networkd](../../Settings/Persistent_Network/systemd_networkd.md)** — полная конфигурация.
