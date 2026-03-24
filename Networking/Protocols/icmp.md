# Протокол ICMP (Internet Control Message Protocol)

> **Примечание:** Этот файл был декомпозирован на тематические заметки. Актуальная информация находится в директории **[ICMP/](./ICMP/)**.

## Навигация

- **[ICMP/icmp_overview.md](./ICMP/icmp_overview.md)** — определения, назначение, структура ICMP-сообщений
- **[ICMP/icmp_echo_ping.md](./ICMP/icmp_echo_ping.md)** — Echo Request/Reply, утилита ping, broadcast
- **[ICMP/icmp_destination_unreachable.md](./ICMP/icmp_destination_unreachable.md)** — Type 3, коды 0-4
- **[ICMP/icmp_redirect.md](./ICMP/icmp_redirect.md)** — Type 5 (Redirect), Type 4 (Source Quench)
- **[ICMP/icmp_time_exceeded.md](./ICMP/icmp_time_exceeded.md)** — Type 11, TTL, traceroute
- **[ICMP/icmp_diagnostics_security.md](./ICMP/icmp_diagnostics_security.md)** — диагностика, безопасность, ICMPv6

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

- **[IP](./ip.md)** — сетевой уровень
- **[TCP](./TCP/overview.md)** — транспортный уровень
- **[ARP](./arp.md)** — разрешение адресов
- **[ping](../../Linux/Diagnostics/Networking/ping.md)** — проверка доступности
- **[traceroute](../../Linux/Diagnostics/Networking/traceroute_mtr.md)** — трассировка маршрута

## RFC

- **RFC 792** — спецификация ICMP для IPv4
- **RFC 4443** — ICMPv6 для IPv6
- **RFC 4884** — Extended ICMP
