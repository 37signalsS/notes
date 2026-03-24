# IP-адресация (Internet Protocol Addressing)

> **Примечание:** Этот файл был декомпозирован на тематические заметки. Актуальная информация находится в директории **[IP_addressing/](./IP_addressing/)**.

## Навигация

- **[IP_addressing/ip_overview.md](./IP_addressing/ip_overview.md)** — определения, версии, структура IPv4
- **[IP_addressing/subnetting_calculation.md](./IP_addressing/subnetting_calculation.md)** — расчет подсетей, маска, адрес сети, broadcast
- **[IP_addressing/special_addresses.md](./IP_addressing/special_addresses.md)** — специальные и частные IP-адреса
- **[IP_addressing/special_masks.md](./IP_addressing/special_masks.md)** — маски /32, /31, классовая адресация, CIDR

## Краткое описание

**IP-адрес (Internet Protocol Address)** — уникальный числовой идентификатор устройства в компьютерной сети, используемый для маршрутизации пакетов на сетевом уровне (L3).

**Ключевые особенности:**
- Логический адрес (в отличие от MAC-адреса)
- Может назначаться динамически
- Два основных стандарта: IPv4 (32 бита) и IPv6 (128 бит)

**Типы адресов в подсети:**
- **Адрес сети** — идентификатор подсети (нельзя назначать устройствам)
- **Адрес хоста** — уникальный адрес устройства
- **Broadcast** — адрес для рассылки всем устройствам в подсети

## Связанные документы

- **[DHCP](../dhcp.md)** — динамическое назначение IP-адресов
- **[ARP](../arp.md)** — разрешение IP-адресов в MAC-адреса
- **[NAT](../Concepts/nat.md)** — трансляция сетевых адресов

## RFC

- **RFC 791** — IPv4 спецификация
- **RFC 2460** — IPv6 спецификация
- **RFC 1918** — частные IP-адреса
- **RFC 3021** — Using 31-Bit Prefixes on IPv4 Point-to-Point Links
- **RFC 4632** — CIDR (Classless Inter-Domain Routing)
