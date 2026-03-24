# ICMP (Internet Control Message Protocol)

## Навигация

**Основная информация:**
- **[icmp_overview.md](./icmp_overview.md)** — определения, назначение, структура ICMP-сообщений
- **[icmp_echo_ping.md](./icmp_echo_ping.md)** — Echo Request/Reply, утилита ping, broadcast
- **[icmp_destination_unreachable.md](./icmp_destination_unreachable.md)** — Type 3, коды 0-4
- **[icmp_redirect.md](./icmp_redirect.md)** — Type 5 (Redirect), Type 4 (Source Quench)
- **[icmp_time_exceeded.md](./icmp_time_exceeded.md)** — Type 11, TTL, traceroute
- **[icmp_diagnostics_security.md](./icmp_diagnostics_security.md)** — диагностика, безопасность, ICMPv6

## Краткое описание

**ICMP (Internet Control Message Protocol)** — служебный протокол сетевого уровня (L3), используемый для передачи сообщений об ошибках, управления и диагностики в IP-сетях.

**Ключевые особенности:**
- Не передаёт пользовательские данные
- Работает поверх IP (RFC 792)
- Относится к сетевому уровню модели ISO/OSI

**Основные типы сообщений:**
- **Type 8/0** — Echo Request/Reply (ping)
- **Type 3** — Destination Unreachable (ошибки доставки)
- **Type 5** — Redirect (управление маршрутизацией)
- **Type 11** — Time Exceeded (TTL, traceroute)

## Связанные документы

**Протоколы:**
- **[IP](../ip.md)** — сетевой уровень
- **[TCP](../TCP/overview.md)** — транспортный уровень
- **[ARP](../arp.md)** — разрешение адресов

**Диагностика:**
- **[ping](../../Linux/Diagnostics/Networking/ping.md)** — проверка доступности
- **[traceroute](../../Linux/Diagnostics/Networking/traceroute_mtr.md)** — трассировка маршрута

## RFC

- **RFC 792** — спецификация ICMP для IPv4
- **RFC 4443** — ICMPv6 для IPv6
- **RFC 4884** — Extended ICMP
