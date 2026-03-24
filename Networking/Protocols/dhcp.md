# DHCP (Dynamic Host Configuration Protocol)

> **Примечание:** Этот файл был декомпозирован на тематические заметки. Актуальная информация находится в директории **[DHCP/](./DHCP/)**.

## Навигация

- **[DHCP/dhcp_overview.md](./DHCP/dhcp_overview.md)** — определения, принцип работы DORA
- **[DHCP/dhcp_lease_time.md](./DHCP/dhcp_lease_time.md)** — время аренды, продление, типы назначения
- **[DHCP/dhcp_relay.md](./DHCP/dhcp_relay.md)** — DHCP Relay, ретрансляция между подсетями
- **[DHCP/dhcp_analysis_troubleshooting.md](./DHCP/dhcp_analysis_troubleshooting.md)** — анализ в Wireshark, troubleshooting
- **[DHCP/dhcp_security.md](./DHCP/dhcp_security.md)** — атаки (Starvation, Rogue), защита

## Краткое описание

**DHCP (Dynamic Host Configuration Protocol)** — протокол прикладного уровня (L7), предназначенный для автоматической конфигурации сетевых параметров устройств в IP-сетях (RFC 2131).

**Ключевые особенности:**
- Автоматическая выдача IP-адресов, масок, шлюзов, DNS
- Поддержка динамического, автоматического и статического назначения
- Использование UDP портов 67 (сервер) и 68 (клиент)

**Процесс DORA:**
1. **Discover** — обнаружение серверов
2. **Offer** — предложение адреса
3. **Request** — запрос выбранного предложения
4. **Acknowledge** — подтверждение выдачи

## Связанные документы

- **[IP](../ip.md)** — сетевой уровень
- **[ARP](../arp.md)** — разрешение адресов
- **[BOOTP](https://www.rfc-editor.org/rfc/rfc951)** — предшественник DHCP

## RFC

- **RFC 2131** — спецификация DHCP
- **RFC 2132** — DHCP опции
- **RFC 3046** — DHCP Relay Agent Information Option
