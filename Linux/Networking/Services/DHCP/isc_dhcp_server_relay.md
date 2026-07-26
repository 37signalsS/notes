# ISC DHCP Relay — настройка утилиты dhcrelay

> **Важно:** ISC (Internet Systems Consortium) DHCP устарел (EOL — End of Life). Для новых развёртываний рекомендуется использовать **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Утилита `dhcrelay` всё ещё поддерживается для обслуживания существующих инфраструктур.

## Определения

**DHCP Relay Agent (Ретранслятор DHCP)** — компонент (обычно на маршрутизаторе или Linux-хосте), который пересылает сообщения **DHCP (Dynamic Host Configuration Protocol — протокол динамической настройки узла)** между подсетями, когда клиент и сервер находятся в разных широковещательных доменах.

**dhcrelay** — специализированный демон из состава пакета ISC DHCP для выполнения функций ретранслятора в ОС (операционных системах) семейства Linux.

**giaddr (Gateway IP Address)** — поле в заголовке DHCP-пакета, в которое ретранслятор записывает свой **IP-адрес (Internet Protocol — межсетевой протокол)** интерфейса, принявшего запрос от клиента. На основе этого адреса сервер определяет, из какой подсети выделить IP.

> **Основной документ:** [Концепция DHCP Relay](../../../../Networking/Protocols/DHCP/dhcp_relay.md) — принцип работы, поля `giaddr`/`hops`, RFC (Request for Comments).

## Основные концепции

### Принцип работы в Linux

В Linux-системах `dhcrelay` работает на прикладном уровне модели **OSI (Open Systems Interconnection)**. Он прослушивает интерфейсы на наличие широковещательных запросов (broadcast) на порт **UDP (User Datagram Protocol)** 67.

**Процесс обработки:**
1. Принимает `DHCPDISCOVER` от клиента.
2. Подставляет свой IP в поле `giaddr`.
3. Пересылает пакет в виде направленной передачи (unicast) на настроенные IP-адреса DHCP-серверов.
4. Принимает ответ от сервера и пересылает его обратно клиенту в соответствующую **VLAN (Virtual Local Area Network)** или подсеть.

**Ключевые особенности:**
- **Замена аппаратных решений:** Позволяет Linux-маршрутизатору заменять функционал Cisco `ip helper-address`.
- **Поддержка Option 82:** Может добавлять информацию о порте и интерфейсе (`Agent Information Option`), что полезно для безопасности и детальной идентификации клиентов.

## Практические сценарии

### Debian / Ubuntu

1. **Установка:**
    ```bash
    sudo apt update
    sudo apt install isc-dhcp-relay
    ```

2. **Настройка** (`/etc/default/isc-dhcp-relay`):
    В процессе установки часто открывается интерактивное окно. Для ручной правки используйте:
    ```bash
    # Укажите IP-адреса DHCP-серверов через пробел
    SERVERS="10.0.4.4 10.0.4.5"
    # Укажите интерфейсы (клиентские и серверный)
    INTERFACES="eth0 eth1"
    # Дополнительные опции (например, -A для Option 82)
    OPTIONS=""
    ```

3. **Управление сервисом:**
    ```bash
    sudo systemctl restart isc-dhcp-relay
    sudo systemctl enable isc-dhcp-relay
    ```

### RHEL / Rocky Linux / AlmaLinux

1. **Установка:**
    ```bash
    sudo dnf install dhcp-server
    ```

2. **Настройка** (`/etc/sysconfig/dhcrelay`):
    Отредактируйте файл конфигурации для передачи аргументов демону:
    ```bash
    # Интерфейсы, на которых слушать запросы
    INTERFACES="eth0 eth1"
    # IP-адреса DHCP-серверов
    SERVERS="10.0.4.4"
    # Дополнительные аргументы
    DHCRELAY_ARGS=""
    ```

3. **Управление сервисом:**
    ```bash
    sudo systemctl start dhcrelay
    sudo systemctl enable dhcrelay
    ```

### Настройка Firewall

Для работы ретранслятора необходимо разрешить трафик по протоколу UDP на портах 67 (server) и 68 (client).

**Пример для `ufw` (Ubuntu):**
```bash
sudo ufw allow in on eth0 to any port 67 proto udp
sudo ufw allow in on eth1 to any port 67 proto udp
```

**Пример для `firewalld` (RHEL):**
```bash
sudo firewall-cmd --add-service=dhcp --permanent
sudo firewall-cmd --reload
```

## Дополнительная информация

### Диагностика

* **Проверка портов:**
    ```bash
    ss -nlup | grep dhcrelay
    # Ожидаемый результат: *:67
    ```
* **Просмотр логов:**
    - Debian/Ubuntu: `journalctl -u isc-dhcp-relay -f`
    - RHEL: `journalctl -u dhcrelay -f`
* **Анализ трафика:**
    ```bash
    # Захват DHCP пакетов на конкретном интерфейсе
    sudo tcpdump -i eth0 port 67 or port 68 -vv -n
    ```

### Связанные документы

- [Концепция DHCP Relay Agent](../../../../Networking/Protocols/DHCP/dhcp_relay.md) — теоретическая база и RFC.
- [Обзор ISC DHCP](./isc_dhcp_server_overview.md) — архитектура и сравнение с Kea.
- [Базовая настройка ISC DHCP](./isc_dhcp_server_basic_config.md) — настройка основного сервера.
- [Настройка Failover](./isc_dhcp_server_failover.md) — обеспечение отказоустойчивости.
- [Диагностика DHCP](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md) — общие методы устранения неполадок.
