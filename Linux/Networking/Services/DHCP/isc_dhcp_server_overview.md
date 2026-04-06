# ISC DHCP: Обзор и архитектура

> **Важно:** ISC прекратила поддержку DHCP-сервера в 2022 году. Для новых развёртываний используйте [Kea DHCP](#kea-dhcp). Данный файл — точка входа в документацию ISC DHCP для существующих развёртываний и миграции.

## Definitions

**DHCP (Dynamic Host Configuration Protocol)** — протокол для автоматической конфигурации сетевых параметров (IP-адрес, маска, шлюз, DNS) в IP-сетях. Подробнее: [Протокол DHCP: теория](../../../../Networking/Protocols/DHCP/dhcp_overview.md).

**ISC DHCP** — классическая реализация DHCP-сервера от Internet Systems Consortium. Пакет: `isc-dhcp-server` (Debian/Ubuntu), `dhcp-server` (RHEL/CentOS).

## Basic Concepts

### Назначение

- Автоматическая выдача IP-адресов из пула клиентам.
- Передача дополнительных параметров: маска подсети, шлюз по умолчанию, DNS-серверы, опции.

### Требования к серверу

- Статический IP-адрес для обеспечения доступности.
- Открытый **UDP/67** для запросов клиентов.
- При failover — открытый **TCP/647** для обмена между серверами.

### Структура файлов конфигурации

| Файл | Назначение |
| :--- | :--- |
| `/etc/dhcp/dhcpd.conf` | Основная конфигурация (иерархическая: глобальные параметры переопределяются в `subnet`) |
| `/etc/dhcp/dhcpd6.conf` | Конфигурация для IPv6 |
| `/etc/default/isc-dhcp-server` (Debian) | Указание интерфейсов для прослушивания |
| `/etc/sysconfig/dhcpd` (RHEL) | Указание интерфейсов для прослушивания |
| `/var/lib/dhcp/dhcpd.leases` (Debian) | Файл аренды |
| `/var/lib/dhcpd/dhcpd.leases` (RHEL) | Файл аренды |

### DHCP-клиент

В современных Linux-системах за DHCP-клиент отвечает **NetworkManager**, вызывающий `dhclient` или использующий встроенные механизмы. Настройки — через профили NetworkManager (`nmcli`).

## Practical Scenarios

### Сценарий 1: Выбор подхода

| Задача | Решение |
| :--- | :--- |
| Базовая установка и настройка | [Базовая настройка](./isc_dhcp_server_basic_config.md) |
| Фиксация IP за конкретным устройством | [Резервирование IP](./isc_dhcp_server_reservations.md) |
| Отказоустойчивая пара серверов | [Failover](./isc_dhcp_server_failover.md) |
| Ретрансляция между VLAN/подсетями | [DHCP Relay](./isc_dhcp_server_relay.md) |
| Проверка работы, логи, диагностика | [Проверка и мониторинг](./isc_dhcp_server_verification.md) |

## Additional Information

### Kea DHCP

**Kea DHCP** — современный DHCP-сервер от ISC, замена устаревшему ISC DHCP. Активно поддерживается, рекомендуется для новых развёртываний.

**Ключевые отличия:**

- Пакет: `kea-dhcp-server`
- Конфигурация: JSON-формат (обратная совместимость с ISC DHCP)
- Демон: `kead` вместо `dhcpd`
- REST API для онлайн-конфигурации без перезагрузки
- Активные обновления безопасности

**Миграция:** требуется конвертация конфигурации ISC DHCP в JSON-формат Kea.

### Связанные документы

- [Теория протокола DHCP](../../../../Networking/Protocols/DHCP/dhcp_overview.md)
- [Защита от rogue DHCP](../../../../Networking/Protocols/DHCP/dhcp_security.md)
- [Время аренды DHCP](../../../../Networking/Protocols/DHCP/dhcp_lease_time.md)
