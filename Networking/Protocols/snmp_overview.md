# SNMP — протокол сетевого управления

> **Reliability Score: 10** (SSoT + Verified RFCs + Industry Standard)

## Определения

**SNMP (Simple Mail Management Protocol — простой протокол сетевого управления)** — стандартный протокол прикладного уровня (L7) стека TCP/IP, предназначенный для обмена информацией между сетевыми устройствами и системами мониторинга (NMS). Описан в серии RFC (основные актуальные — **RFC 3411-3418**).

**MIB (Management Information Base)** — иерархическая база данных, структурированная в виде дерева, где каждый узел описывает параметр управления или статистики.
**SMI (Structure of Management Information)** — стандарт, определяющий типы данных и синтаксис для описания объектов в MIB.
**OID (Object Identifier)** — уникальный числовой идентификатор объекта в дереве MIB (например, `.1.3.6.1.2.1.1.5.0` — SysName).

> **См. также:** **[Протокол UDP](./udp.md)**, **[Модель OSI](../OSI_TCP_IP_Model/osi_model.md)**

## Основные концепции

### Типы данных SMI (SMIv2)

Для корректной интерпретации метрик необходимо понимать базовые типы данных:
- **Counter32 / Counter64:** счетчики, которые только увеличиваются (например, объем трафика). При достижении максимума сбрасываются в 0 (Roll-over).
- **Gauge32:** значение, которое может увеличиваться и уменьшаться (загрузка CPU, количество сессий).
- **Integer32:** целое число (например, индекс интерфейса).
- **TimeTicks:** время в сотых долях секунды с момента события (например, SysUpTime).
- **Octet String:** текстовые или бинарные данные (MAC-адреса, описания).
- **IpAddress:** 32-битный адрес IPv4.

### Структура пакета (PDU)

Запросы SNMP упаковываются в **PDU (Protocol Data Unit)**, который включает:
1. **Request ID:** уникальный номер для сопоставления запроса и ответа.
2. **Error Status:** код ошибки (0 — NoError, 2 — NoSuchName, 5 — GenErr).
3. **Error Index:** индекс переменной в списке, вызвавшей ошибку.
4. **Varbind List:** список пар «OID — Значение».

### Эволюция и безопасность версий

| Характеристика | SNMPv1 | SNMPv2c | SNMPv3 |
| :--- | :--- | :--- | :--- |
| **Безопасность** | Community String (Open text) | Community String (Open text) | USM (Auth + Privacy) |
| **Счетчики** | Только 32-бит | 32 и 64-бит | 32 и 64-бит |
| **Производительность** | Get/GetNext | GetBulk (пакеты) | GetBulk + Шифрование |
| **Надежность уведомлений** | Trap (UDP) | Trap / Inform (ACK) | Trap / Inform (ACK) |

#### SNMPv3: Безопасность и EngineID
SNMPv3 вводит **USM (User-based Security Model)** и **VACM (View-based Access Control Model)**:
- **EngineID:** уникальный идентификатор SNMP-сущности. Используется как соль для хэширования паролей, предотвращая атаки воспроизведения (Replay attacks).
- **authPriv:** данные хешируются (SHA/HMAC-SHA2) и шифруются (AES-128/256).

### Уведомления: Trap vs Inform

- **Trap (Ненадежно):** Агент отправляет уведомление и не ждет подтверждения. Если пакет потерян в UDP, NMS о нем не узнает.
- **Inform (Надежно):** Менеджер (NMS) обязан отправить подтверждение (Response). Если агент не получает подтверждения, он повторяет отправку (Retransmission). Рекомендуется для критических событий.

## Практическая реализация

### Порты
- **161 UDP:** Стандартные запросы (Poll).
- **162 UDP:** Прием уведомлений (Traps/Informs).

### Настройка snmpd в Linux (Эталон 2026)

Файл `/etc/snmp/snmpd.conf` должен быть настроен по принципу минимальных привилегий.

```bash
# 1. Доступ для SNMPv2c (только доверенная сеть)
acl my_network src 192.168.10.0/24
rocommunity secure_string 192.168.10.5

# 2. Настройка SNMPv3 (authPriv - MD5/SHA + AES)
# Создание пользователя (через net-snmp-config или напрямую в файл)
createUser myuser SHA "AuthPassword" AES "PrivPassword"
rouser myuser authPriv

# 3. Системная информация
sysLocation DataCenter-01
sysContact admin@example.com

# 4. Ограничение видимости MIB (VACM)
# Видеть только системную информацию и интерфейсы
view systemonly included .1.3.6.1.2.1.1
view systemonly included .1.3.6.1.2.1.2
```

### Диагностика из командной строки

```bash
# Установка (Debian/Ubuntu)
sudo apt update && sudo apt install snmp snmp-mibs-downloader

# Проверка доступности (v2c)
snmpget -v2c -c public 192.168.1.1 .1.3.6.1.2.1.1.3.0

# Рекурсивный обход (v3)
snmpwalk -v3 -l authPriv -u myuser -a SHA -A AuthPassword -x AES -X PrivPassword 192.168.1.1 .1.3.6
```

## Безопасность и современные альтернативы

### Рекомендации по Hardening
1. **Отключение v1/v2c:** Если инфраструктура позволяет, используйте только v3.
2. **Сложные Community:** Не используйте `public` / `private`.
3. **ACL на уровне OS:** Ограничивайте UDP 161 через `nftables` / `iptables`.

### SNMP vs Streaming Telemetry
Для современных высоконагруженных систем (Spine-Leaf топологии) SNMP становится бутылочным горлышком:
- **SNMP:** Pull-модель, нагрузка на CPU при парсинге больших таблиц MIB.
- **gNMI / Streaming Telemetry:** Push-модель поверх HTTP/2 (gRPC). Данные передаются непрерывно, в бинарном формате (Protobuf), с минимальной нагрузкой.

## Дополнительная информация

### Связанные документы
- **[Настройка SNMP в Zabbix](../../Zabbix/installation.md#настройка-snmp-мониторинга)** — интеграция с NMS.
- **[snmp_exporter для Prometheus](../../Prometheus/Exporters/other_exporters.md)** — современный стек.
- **[Справочник сетевых портов](../Concepts/network_ports.md)** — 161, 162 UDP.

### Спецификации
- **RFC 1157:** Simple Network Management Protocol (SNMPv1).
- **RFC 1901:** Community-based SNMPv2 (SNMPv2c).
- **RFC 3411:** Architecture for Describing SNMP Management Frameworks.

