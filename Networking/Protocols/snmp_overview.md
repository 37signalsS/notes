# SNMP — протокол сетевого управления

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
- **161 UDP:** Стандартные запросы (Poll) — агент слушает.
- **162 UDP:** Прием уведомлений (Traps/Informs) — NMS слушает.

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

# 5. Включение Trap-отправки
trapsink 192.168.10.100 public
trapcommunity public
trap2sink 192.168.10.100 public

# 6. Мониторинг интерфейсов (для Prometheus/Telegraf)
view systemonly included .1.3.6.1.2.1.2      # interfaces
view systemonly included .1.3.6.1.2.1.31.1  # ifXTable (64-bit counters)
```

### Установка и запуск snmpd

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install snmpd snmp snmp-mibs-downloader

# Fedora/RHEL
sudo dnf install net-snmp net-snmp-utils

# Включение и запуск
sudo systemctl enable --now snmpd

# Проверка статуса
sudo systemctl status snmpd

# Проверка, что порт слушается
ss -ulnp | grep 161
# → UNCONN  0  0  0.0.0.0:161  0.0.0.0:*
```

### Диагностика из командной строки

```bash
# Проверка доступности (v2c)
snmpget -v2c -c public 192.168.1.1 .1.3.6.1.2.1.1.3.0
# → SNMPv2-MIB::sysUpTime.0 = Timeticks: (123456) 1:02:00:56.00

# Рекурсивный обход (v3)
snmpwalk -v3 -l authPriv -u myuser -a SHA -A AuthPassword -x AES -X PrivPassword 192.168.1.1 .1.3.6

# Быстрое получение всех интерфейсов
snmpwalk -v2c -c public 192.168.1.1 .1.3.6.1.2.1.2.1

# Получение MAC-адреса интерфейса
snmpget -v2c -c public 192.168.1.1 .1.3.6.1.2.1.2.2.1.6.1
# → SNMPv2-MIB::ifPhysAddress.1 = Hex-STRING: 00 11 22 33 44 55

# Получение скорости интерфейса
snmpget -v2c -c public 192.168.1.1 .1.3.6.1.2.1.2.2.1.5.1
# → SNMPv2-MIB::ifSpeed.1 = Gauge32: 1000000000

# Получение объема трафика (64-bit)
snmpwalk -v2c -c public 192.168.1.1 .1.3.6.1.2.1.31.1.1.1.6
# → IF-MIB::ifHCInOctets.1 = Counter64: 1234567890
```

### Мониторинг через Prometheus (snmp_exporter)

**Установка snmp_exporter:**
```bash
# Скачать бинарник
wget https://github.com/prometheus/snmp_exporter/releases/download/v0.24.0/snmp_exporter-0.24.0.linux-amd64.tar.gz
tar xzf snmp_exporter-0.24.0.linux-amd64.tar.gz
cd snmp_exporter-0.24.0.linux-amd64

# Запуск (по умолчанию слушает :9116)
./snmp_exporter --config.file=snmp.yml
```

**Конфигурация Prometheus:**
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'snmp'
    static_configs:
      - targets:
        - 192.168.1.1    # Сетевое устройство
        - 192.168.1.2
    metrics_path: /snmp
    params:
      module: [if_mib]
      auth: [public_v2]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9116  # Адрес snmp_exporter
```

**Примеры метрик Prometheus:**
```
# Скорость интерфейса
ifSpeed{instance="192.168.1.1",interface="eth0"} 1e+09

# Объем входящего трафика (64-bit)
ifHCInOctets{instance="192.168.1.1",interface="eth0"} 1.23456789e+09

# Ошибки на интерфейсе
ifInErrors{instance="192.168.1.1",interface="eth0"} 0

# Состояние интерфейса (1 = up, 2 = down)
ifOperStatus{instance="192.168.1.1",interface="eth0"} 1
```

**Примеры алертов Prometheus:**
```yaml
# alerts.yml
groups:
  - name: snmp_alerts
    rules:
      - alert: InterfaceDown
        expr: ifOperStatus != 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Interface {{ $labels.interface }} is down on {{ $labels.instance }}"

      - alert: HighInterfaceErrors
        expr: rate(ifInErrors[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate on {{ $labels.interface }} ({{ $labels.instance }})"

      - alert: InterfaceBandwidthHigh
        expr: rate(ifHCInOctets[5m]) / ifSpeed > 0.8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Interface {{ $labels.interface }} bandwidth >80% ({{ $labels.instance }})"
```

### Настройка Trap-отправки (snmptrapd)

```bash
# Установка snmptrapd
sudo apt install snmptrapd

# Конфигурация (/etc/snmp/snmptrapd.conf)
# Прием Trap от любых устройств в доверенной сети
authCommunity log,execute,net public
disableAuthenticationExits

# Запуск
sudo systemctl enable --now snmptrapd

# Просмотр Trap в логах
sudo tail -f /var/log/syslog | grep snmptrapd
```

### SNMP over TLS (RFC 5953) и DTLS

Для защищенной передачи SNMP-данных используются:
- **SNMP over DTLS:** Датаграммное шифрование поверх UDP. Поддерживается в Net-SNMP 5.4+.
- **SNMP over TLS:** Потоковое шифрование поверх TCP. Более надежно, но требует установки соединения.

```bash
# Пример snmpget через TLS (Net-SNMP)
snmpget -l authPriv -u myuser -a SHA -A AuthPassword -x AES -X PrivPassword \
  -t 10 -r 3 192.168.1.1 .1.3.6.1.2.1.1.3.0
```

## Безопасность и современные альтернативы

### Рекомендации по Hardening
1. **Отключение v1/v2c:** Если инфраструктура позволяет, используйте только v3.
2. **Сложные Community:** Не используйте `public` / `private`.
3. **ACL на уровне OS:** Ограничивайте UDP 161 через `nftables` / `iptables`.
4. **VACM:** Ограничьте видимость MIB только необходимыми OID.
5. **Отключение ненужных сервисов:** Отключите写入-доступ (set) если он не используется.

### SNMP vs Streaming Telemetry
Для современных высоконагруженных систем (Spine-Leaf топологии) SNMP становится бутылочным горлышком:
- **SNMP:** Pull-модель, нагрузка на CPU при парсинге больших таблиц MIB.
- **gNMI / Streaming Telemetry:** Push-модель поверх HTTP/2 (gRPC). Данные передаются непрерывно, в бинарном формате (Protobuf), с минимальной нагрузкой.

### Типичные ошибки и решения

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `snmpget` не отвечает | UDP 161 заблокирован | `ss -ulnp \| grep 161` — проверить порт | Открыть UDP 161 в firewall |
| `snmpget` возвращает `No such object` | OID не существует в MIB | `snmpwalk .1.3.6` — проверить доступные OID | Установить нужную MIB или использовать numeric OID |
| Trap не приходят | UDP 162 заблокирован или nms down | `snmptrapd -f -Lo` — запустить в foreground | Открыть UDP 162; проверить `trapsink` в snmpd.conf |
| Высокий CPU при snmpwalk | Огромная таблица MIB | `top -p $(pgrep snmpd)` — проверить нагрузку | Используйте `snmpbulkwalk` (GetBulk) вместо `snmpwalk` |
| Авторизация не работает (v3) | Неправильный пароль или EngineID | `snmpwalk -v3 -l authPriv ...` — проверить | Удалите `engineID` из snmpd.conf; перезапустите snmpd |

## Дополнительная информация

### Связанные документы
- **[Автоматизация заполнения NetBox через SNMP](../NetBox/netbox-automation-python.md)** — использование snmpwalk для сбора данных об устройствах.
- **[Настройка SNMP в Zabbix](../../Zabbix/zabbix_snmp_monitoring.md)** — интеграция с NMS.
- **[snmp_exporter для Prometheus](../../Prometheus/Exporters/other_exporters.md)** — современный стек.
- **[Справочник сетевых портов](../Concepts/network_ports.md)** — 161, 162 UDP.
- **[UDP — протокол транспортного уровня](./udp.md)** — транспорт для SNMP.
- **[Ethernet — диагностика NIC](./ethernet.md#оптимизация-производительности-nic-в-linux)** — мониторинг интерфейсов через SNMP.

### Спецификации
- **RFC 1157:** Simple Network Management Protocol (SNMPv1).
- **RFC 1901:** Community-based SNMPv2 (SNMPv2c).
- **RFC 3411:** Architecture for Describing SNMP Management Frameworks.

