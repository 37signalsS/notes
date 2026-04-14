# ISC DHCP — резервирование IP и передача маршрутов

> **Важно:** ISC DHCP устарел. Для новых развёртываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Синтаксис резервирования в Kea использует JSON.

## Definitions

**DHCP Reservation (Static Allocation)** — привязка конкретного IP-адреса к MAC-адресу устройства. Клиент всегда получает один и тот же IP из пула DHCP-сервера.

**Classless Static Routes (RFC 3442)** — механизм передачи клиентам произвольных маршрутов через DHCP-опцию `rfc3442-classless-static-routes`. Позволяет клиентам узнавать пути к удалённым сетям без ручной настройки.

> **Концепция:** [Статическое назначение DHCP](../../../../Networking/Protocols/DHCP/dhcp_lease_time.md#статическое-назначение-static-allocation--dhcp-reservation) — теория, сравнение с dynamic/automatic allocation.

## Basic Concepts

### Когда использовать резервирование

- Серверы, принтеры, IP-камеры — устройствам нужен постоянный IP, но ручная настройка нежелательна.
- Централизованное управление: все адреса контролируются из одной точки (DHCP-сервер).

### Когда использовать передачу маршрутов

- Клиенты в специфической подсети (DMZ, гостевой VLAN) должны иметь доступ к внутренним сетям через нестандартный шлюз.
- Исключение необходимости настраивать статические маршруты вручную на каждом клиенте.

### Формат RFC 3442

Опция `rfc3442-classless-static-routes` использует бинарный формат:

```
<префикс-маски>, <байты-сети>, <байты-шлюза>
```

- Маска `16` → сеть `/16`, за ней 2 байта сети.
- Шлюз указывается полностью (4 байта для IPv4).

## Practical Scenarios

### Резервирование IP-адреса

```ini
host fileserver {
    hardware ethernet 08:00:27:1A:2B:3C;  # MAC-адрес устройства
    fixed-address 10.0.10.5;              # Постоянный IP
}
```

Блок `host` размещается внутри `subnet` или глобально в `/etc/dhcp/dhcpd.conf`.

### Передача статических маршрутов (DMZ → внутренняя сеть)

Сценарий: хосты в DMZ (VLAN 30, `10.0.30.0/24`) должны добираться до внутренней сети `172.16.0.0/16` через роутер `10.0.30.254`.

```ini
subnet 10.0.30.0 netmask 255.255.255.0 {
    range 10.0.30.10 10.0.30.20;
    option routers 10.0.30.1;

    # RFC 3442: 16.172.16 = 172.16.0.0/16, шлюз = 10.0.30.254
    option rfc3442-classless-static-routes 16, 172, 16, 10, 0, 30, 254;
}
```

### Несколько маршрутов в одной опции

```ini
# Маршрут 1: 172.16.0.0/16 через 10.0.30.254
# Маршрут 2: 192.168.0.0/24 через 10.0.30.253
option rfc3442-classless-static-routes
    16, 172, 16, 10, 0, 30, 254,
    24, 192, 168, 0, 10, 0, 30, 253;
```

## Additional Information

### Диагностика

- `ip route` на клиенте — проверить, что маршруты применились.
- `journalctl -u isc-dhcp-server` — логи сервера, ошибки парсинга `dhcpd.conf`.
- `tcpdump -i eth0 port 67 or port 68` — убедиться, что DHCP-ответ содержит опцию 121 (RFC 3442).

### Примечания

- Опция RFC 3442 — это DHCP option **121** (classless static routes).
- Устаревшая опция **33** (static routes) не поддерживает classless-формат и не рекомендуется.
- Не все ОС поддерживают option 121 (Windows — да, Linux через dhclient — да, embedded-устройства — зависит от клиента).

### Связанные документы

- Концепция: [Статическое назначение](../../../../Networking/Protocols/DHCP/dhcp_lease_time.md#статическое-назначение-static-allocation--dhcp-reservation)
- Обзор ISC DHCP: [isc_dhcp_server_overview.md](./isc_dhcp_server_overview.md)
- Базовая настройка: [isc_dhcp_server_basic_config.md](./isc_dhcp_server_basic_config.md)
- DHCP Relay: [isc_dhcp_server_relay.md](./isc_dhcp_server_relay.md)
