# ISC DHCP Relay — настройка утилиты dhcrelay

> **Важно:** ISC DHCP официально признан устаревшим (EOL). Для новых систем рекомендуется использовать **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Утилита `dhcrelay` продолжает использоваться для поддержки существующих сетевых инфраструктур.

---

## Определения

**DHCP Relay Agent (Ретранслятор DHCP)** — промежуточный узел (обычно маршрутизатор или Linux-сервер), пересылающий широковещательные сообщения **DHCP** между клиентами и серверами, находящимися в разных широковещательных доменах (подсетях).

**dhcrelay** — системная служба (демон) из состава пакета ISC DHCP, реализующая функции ретранслятора в Linux.

**giaddr (Gateway IP Address)** — поле в заголовке DHCP-пакета. Ретранслятор записывает в него IP-адрес своего интерфейса, принявшего запрос. Сервер использует этот адрес для определения подсети (subnet), из которой нужно выделить свободный IP-адрес.

---

## Основные концепции

### Принцип работы и механизм hops

В Linux-системах `dhcrelay` перехватывает широковещательные UDP-пакеты на порту **67**.

1.  **Hops (Прыжки):** При пересылке пакета ретранслятор увеличивает значение поля `hops`. Если оно превышает установленный лимит (по умолчанию 10), пакет отбрасывается для предотвращения бесконечных циклов в сети.
2.  **Option 82 (Agent Information Option):** Ретранслятор может добавлять в пакет информацию о физическом порте или VLAN, через который пришел запрос. Это позволяет серверу применять более тонкие политики (например, привязку IP к порту коммутатора).
3.  **Broadcast bit:** Если в исходном запросе клиента установлен флаг broadcast (клиент ещё не может принимать unicast-ответы), ретранслятор обязан отправить ответ от сервера широковещательно в локальную подсеть. Если флаг сброшен — ответ может быть отправлен как unicast на MAC-адрес клиента.
4.  **Несколько серверов:** При указании нескольких IP-адресов в параметре `SERVERS` ретранслятор дублирует запрос **всем** указанным серверам. Ответ первым пришедшего сервера направляется клиенту. Это обеспечивает отказоустойчивость, но не балансировку нагрузки в строгом смысле.

### DHCPv6 Relay (RFC 3315)

В отличие от IPv4, где пакет модифицируется «на лету», в IPv6 ретранслятор использует механизм **инкапсуляции**:
- Сообщение клиента упаковывается в пакет `Relay-Forward`.
- Сервер отвечает пакетом `Relay-Reply`, который ретранслятор распаковывает и отдает клиенту.

### Цепочка ретрансляторов (Relay Chaining)

В сложных топологиях между клиентом и сервером может находиться несколько ретрансляторов. Каждый ретранслятор:
- Увеличивает `hops` (IPv4) или добавляет свой блок `Relay-Forward` (IPv6).
- Может добавлять свою Option 82 (IPv4) или Interface-ID (Option 18, IPv6).
- Предельное число прыжков защищает от бесконечных циклов.

### Справочник флагов dhcrelay

| Флаг | Описание |
| :--- | :--- |
| `-4` | Режим IPv4 (по умолчанию) |
| `-6` | Режим IPv6 |
| `-i <iface>` | Интерфейс, на котором принимаются запросы от клиентов (можно указать несколько) |
| `-s <server>` | IP-адрес DHCP-сервера (можно указать несколько для отказоустойчивости) |
| `-p <port>` | Порт сервера (по умолчанию 67) |
| `-A` | Всегда добавлять Option 82, даже если она уже присутствует |
| `-a` | Добавлять Option 82 только если её нет в запросе |
| `-m <mode>` | Режим обработки существующей Option 82: `append`, `replace`, `drop` |
| `-c <format>` | Формат Circuit ID (sub-option 1): `string:<value>` или `ifname` |
| `-i <format>` | Формат Interface ID (Option 18 для IPv6): `string:<value>` или `ifindex` |
| `-r <format>` | Формат Remote ID (sub-option 2) |
| `-g <giaddr>` | Переопределить IP-адрес для поля giaddr (вместо IP интерфейса) |
| `-l <iface>` | Интерфейс к клиенту (режим `-6`) |
| `-u <iface>` | Интерфейс к серверу (режим `-6`) |
| `-d` | Режим отладки (не демонизировать, вывод в stdout) |
| `--no-pid` | Не создавать PID-файл (полезно в контейнерах) |
| `-q` | Тихий режим (только критические ошибки) |

---

## Практические сценарии

### Настройка в Debian / Ubuntu

1.  **Установка пакета:**
    ```bash
    sudo apt update && sudo apt install isc-dhcp-relay -y
    # → success
    ```

2.  **Конфигурация (`/etc/default/isc-dhcp-relay`):**
    ```ini
    # IP-адреса DHCP-серверов (через пробел)
    SERVERS="10.0.4.4 10.0.4.5"

    # Интерфейсы: клиентские и тот, через который доступен сервер
    INTERFACES="eth0 eth1"

    # Дополнительные опции:
    # -A : Включить поддержку Option 82
    # -m append : Добавлять инфо Option 82, если она уже есть
    OPTIONS="-A"
    ```

3.  **Запуск службы:**
    ```bash
    sudo systemctl enable --now isc-dhcp-relay
    # → active (running)
    ```

    **Drop-in override для дополнительных аргументов:**
    Если стандартный файл `/etc/default/isc-dhcp-relay` не позволяет передать нужные флаги (например, `-c`, `-r`), создайте override:
    ```bash
    sudo systemctl edit isc-dhcp-relay
    # → открывает editor для drop-in
    ```

    ```ini
    [Service]
    ExecStart=
    ExecStart=/usr/sbin/dhcrelay -4 -i eth0 -i eth1 -s 10.0.4.4 -A -m append -c "string:vlan%ifname"
    ```

4.  **Проверка:**
    ```bash
    systemctl status isc-dhcp-relay
    # → active (running)
    journalctl -u isc-dhcp-relay --since "5 min ago"
    ```

### Настройка в RHEL / Rocky / AlmaLinux

1.  **Установка:**
    Пакет ретранслятора входит в состав основного пакета сервера.
    ```bash
    sudo dnf install dhcp-server -y
    # → success
    ```

2.  **Конфигурация (`/etc/sysconfig/dhcrelay`):**
    ```ini
    INTERFACES="eth0 eth1"
    SERVERS="10.0.4.4"
    # Для Option 82 добавьте -A в аргументы
    DHCRELAY_ARGS="-A"
    ```

    Для нескольких серверов:
    ```ini
    DHCRELAY_ARGS="-A -s 10.0.4.4 -s 10.0.4.5"
    ```

3.  **Запуск:**
    ```bash
    sudo systemctl enable --now dhcrelay
    # → active (running)
    ```

    **Drop-in override (если DHCRELAY_ARGS недостаточно):**
    ```bash
    sudo systemctl edit dhcrelay
    ```

    ```ini
    [Service]
    ExecStart=
    ExecStart=/usr/sbin/dhcrelay -4 -i eth0 -i eth1 -s 10.0.4.4 -A -m append -c "string:vlan%ifname"
    ```

### Отказоустойчивость: несколько серверов через один relay

При указании нескольких IP-адресов dhcrelay пересылает каждый запрос всем указанным серверам. Это обеспечивает:
- **Отказоустойчивость:** Если один сервер недоступен, другой ответит.
- **Нет балансировки:** dhcrelay не распределяет запросы между серверами (все получают копию).
- **Клиент получает первый ответ:** Сервер, ответивший быстрее, «выигрывает» (race condition). Для ISC DHCP это нормально; для Kea требуется HA backend для согласованности.

**Пример для прода:** два ISC-сервера 10.0.4.4 и 10.0.4.5:
```ini
SERVERS="10.0.4.4 10.0.4.5"
OPTIONS="-A"
```

На стороне серверов убедитесь, что оба имеют одинаковую конфигурацию subnet/pool, чтобы клиент получил корректный адрес независимо от того, какой сервер ответил.

### Option 82: детальная конфигурация

Для включения Option 82 с конкретными форматами:

```bash
# -A: всегда добавлять (даже если уже есть)
# -m append: режим добавления (append | replace | drop)
# -c "string:VLAN%ifname": Circuit ID = "VLANeth0.10"
# -r "string:%[hmac:md5,secret]": Remote ID = HMAC-MD5(secret, src MAC)

sudo dhcrelay -4 \
  -i eth0 \
  -i eth1 \
  -s 10.0.4.4 \
  -A \
  -m append \
  -c "string:VLAN%ifname" \
  -r "string:%[hmac:md5,mysecret]"
```

**Форматы Circuit ID / Interface ID / Remote ID:**
- `ifname` — имя интерфейса (eth0)
- `ifindex` — числовой индекс интерфейса (2)
- `string:<value>` — произвольная строка
- `%[hmac:<algo>,<secret>]` — HMAC-хэш от MAC-адреса источника (защита от подмены)

### Ручной запуск для отладки (foreground)

```bash
# Запуск без демонизации, с выводом отладочной информации
sudo dhcrelay -4 -i eth0 -i eth1 -s 10.0.4.4 -A -d

# Без создания PID-файла (для контейнеров/systemd с Type=simple)
sudo dhcrelay -4 -i eth0 -i eth1 -s 10.0.4.4 -A --no-pid

# Тихий режим (только критические ошибки)
sudo dhcrelay -4 -i eth0 -i eth1 -s 10.0.4.4 -q
```

### systemd-networkd (альтернатива dhcrelay)

В современных дистрибутивах (systemd v255+) можно настроить DHCP Relay без отдельного пакета, через `systemd-networkd`:

```ini
# /etc/systemd/network/relay.network
[Match]
Name=eth1

[Network]
DHCPRelay=yes

[DHCPRelay]
ServerAddress=10.0.4.4
ServerAddress=10.0.4.5
```

> **Примечание:** Подробная теория и протокольные детали — в разделе **[DHCP Relay — Ретранслятор DHCP](../../../../Networking/Protocols/DHCP/dhcp_relay.md)**. Сравнение ISC vs Kea relay — в том же документе.

### Ретрансляция DHCPv6

Для работы с IPv6 используется тот же демон, но с флагом `-6`.

```bash
# Пример ручного запуска для IPv6
# -l (lower) - интерфейс к клиенту, -u (upper) - интерфейс к серверу
sudo dhcrelay -6 -l eth0 -u eth1
```

Для IPv6 можно также указать несколько серверов:
```bash
sudo dhcrelay -6 -l eth0 -u eth1 -s 2001:db8::4 -s 2001:db8::5
```

### Контейнеризированный relay для лабораторий

Для тестовых сред можно запустить dhcrelay в Docker/Podman без установки пакета в хост-ОС:

```bash
# Требует --net=host для прослушивания порта 67
docker run --rm --net=host \
  --cap-add=NET_ADMIN \
  isc-dhcp-server \
  dhcrelay -4 -i eth0 -i eth1 -s 10.0.4.4 -A -d
```

---

## Безопасность

### Атаки через DHCP Relay

Ретранслятор расширяет поверхность атаки DHCP:
- **Rogue DHCP Relay:** Несанкционированный relay в сети перехватывает запросы и подменяет ответы.
- **Option 82 Spoofing:** Подмена Circuit ID / Remote ID для получения IP с неавторизованного порта.
- **DHCP Starvation через relay:** Злоумышленник генерирует массу запросов через relay, исчерпывая пул сервера.

### Защита на стороне relay

1.  **Rate Limiting:** Ограничьте количество DHCP-пакетов в секунду на клиентских интерфейсах с помощью `tc` или фаервола.
    ```bash
    # Пример: лимит 10 пакетов/сек на eth0
    sudo tc qdisc add dev eth0 root tbf rate 1kbit burst 32 latency 400ms
    ```
2.  **Фильтрация источника:** Разрешайте отправлять пакеты на порт 67 только с доверенных MAC-адресов (если инфраструктура позволяет).
3.  **Option 82 защита:** Используйте HMAC-формат для Remote ID, чтобы сервер мог верифицировать подлинность relay-агента.
    ```bash
    # На relay:
    -r "string:%[hmac:md5,shared_secret]"

    # На сервере (dhcpd.conf):
    option relay-agent-information code 82 = string;
    ```
4.  **Сетевой доступ:** Разрешайте исходящие соединения только к доверенным DHCP-серверам.

### Trusted Relay на стороне сервера

На ISC DHCP-сервере настройте список доверенных relay-агентов:

```text
# /etc/dhcp/dhcpd.conf
option relay-agent-information code 82 = string;

# Принимать Option 82 только от доверенных relay
subnet 10.0.10.0 netmask 255.255.255.0 {
    option routers 10.0.10.1;
    pool {
        range 10.0.10.50 10.0.10.200;
    }
}
```

Для Kea используйте `libdhcp_flex_id` или `libdhcp_class_cmds` для проверки Option 82.

---

## Высокая доступность

### VRRP на relay-хосте

Если relay работает на Linux-сервере, который сам является шлюзом для клиентской подсети, настройте VRRP (Keepalived) для отказоустойчивости самого relay:

```bash
# /etc/keepalived/keepalived.conf (фрагмент)
vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 50
    priority 150
    virtual_ipaddress 10.0.1.1/24
}
```

При падении основного сервера виртуальный IP (и, соответственно, giaddr) переключается на резервный relay.

### Dual-homed relay

Для критичных сегментов можно настроить relay с двумя uplink-интерфейсами к разным серверам:

```bash
# eth0 — клиентская подсеть
# eth1 — путь к серверу A (10.0.4.4)
# eth2 — путь к серверу B (10.0.4.5)
sudo dhcrelay -4 \
  -i eth0 \
  -s 10.0.4.4 \
  -s 10.0.4.5 \
  -A -m append
```

---

## Логирование

### Rsyslog для dhcrelay

По умолчанию dhcrelay пишет в syslog через Facility `daemon` (или `local7` в некоторых дистрибутивах). Для централизованного сбора логов настройте rsyslog:

```bash
# /etc/rsyslog.d/30-dhcrelay.conf
if $programname == 'dhcrelay' then {
    action(type="omfile" file="/var/log/dhcrelay.log")
    stop
}
```

```bash
sudo systemctl restart rsyslog
```

Для дебага в foreground-режиме:
```bash
sudo dhcrelay -4 -i eth0 -i eth1 -s 10.0.4.4 -d 2>&1 | tee /var/log/dhcrelay-debug.log
```

---

## Мониторинг и проверка работоспособности

### Проверка прослушиваемых портов

```bash
sudo ss -nlup | grep 67
# → UNCONN 0 0 *:67 *:* users:(("dhcrelay",pid=123,fd=5))
```

### Systemd health check

```bash
systemctl is-active isc-dhcp-relay
# → active

systemctl status isc-dhcp-relay --no-pager
```

### Проверка forwarding

```bash
# На relay-хосте: убедитесь, что ip-forwarding не требуется для UDP/67
# (dhcrelay сам пересылает пакеты приложениями, не используя ядерный forwarding)
# Но для IPv6 relay forwarding может потребоваться:
sysctl net.ipv6.conf.all.forwarding
# → 1 (если используется -6 без явного указания интерфейсов)
```

---

## Настройка Сетевого экрана (Firewall)

Ретранслятору необходимо разрешить прием широковещательных запросов от клиентов и обмен данными с сервером.

**UFW (Ubuntu):**
```bash
# Разрешить DHCP запросы на клиентских интерфейсах
sudo ufw allow in on eth0 to any port 67 proto udp
```

**Firewalld (RHEL):**
```bash
sudo firewall-cmd --permanent --add-service=dhcp
sudo firewall-cmd --reload
# → success
```

**nftables (современная замена iptables):**
```bash
# Разрешить UDP 67 на uplink-интерфейсе
sudo nft add rule inet filter input udp dport 67 accept
sudo nft add rule inet filter forward udp dport 67 accept
```

---

## Диагностика и отладка

### Проверка прослушиваемых портов

```bash
sudo ss -nlup | grep 67
# → UNCONN 0 0 *:67 *:* users:(("dhcrelay",pid=123,fd=5))
```

### Анализ прохождения пакетов (tcpdump)

Самый эффективный способ проверить, подставляется ли `giaddr`:

```bash
# На relay-хосте: запросы от клиентов и ответы от сервера
sudo tcpdump -i eth0 port 67 or port 68 -vv -n

# Ожидаемое поле в выводе:
# giaddr 10.0.1.1       ← IP интерфейса relay, принявшего запрос
```

**Диагностика на стороне сервера:**
```bash
# Убедитесь, что giaddr заполнен (если relay настроен)
sudo tcpdump -i any -n "udp port 67" -vv | grep "giaddr"

# Ожидаемый вывод:
# giaddr 10.0.1.1       ← корректный relay
# giaddr 0.0.0.0        ← relay не настроен или пакет не прошёл через него
```

### Проверка Option 82

```bash
# Фильтр Wireshark/tcpdump для опции 82
sudo tcpdump -i eth0 port 67 -vv -n | grep -i "agent"

# Ожидаемый вывод (пример):
# Agent Sub Option 1, length 4: "eth0.10"
# Agent Sub Option 2, length 6: 0x000000000000
```

### Просмотр логов

```bash
# Debian/Ubuntu
journalctl -u isc-dhcp-relay -f

# RHEL
journalctl -u dhcrelay -f
```

### Диагностика: клиент не получает адрес

| Шаг | Действие | Ожидаемый результат |
| :--- | :--- | :--- |
| 1 | `ss -nlup \| grep 67` | dhcrelay слушает порт 67 |
| 2 | `tcpdump -i eth0 port 67` | Видны DHCPDISCOVER от клиента |
| 3 | `tcpdump -i eth1 host 10.0.4.4 and udp port 67` | Видны пересылаемые запросы на сервер |
| 4 | `journalctl -u isc-dhcp-relay -n 50` | Нет ошибок forwarding |
| 5 | `tcpdump -i any port 67 -vv \| grep giaddr` | giaddr заполнен IP relay-интерфейса |
| 6 | На сервере: `tcpdump -i any port 67 -vv` | Сервер получает запрос с корректным giaddr |

### Типичные ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| dhcrelay не запускается | Интерфейс не существует или поднят | `ip link show` — проверить интерфейсы |
| giaddr = 0.0.0.0 | Relay не настроен на интерфейсе клиента | Проверить `INTERFACES` / `-i` |
| Клиент не получает адрес | Нет маршрута от сервера к giaddr | На сервере: `ip route add <giaddr_network>/<mask> via <gateway>` |
| Option 82 не добавляется | Флаг `-A` не указан или конфликт с коммутатором | Проверить `OPTIONS` / `DHCRELAY_ARGS`, режим `-m` |
| Дублированные адреса | Два relay в одной подсети без настройки | Выделить один ответственный relay или настроить priority |
| DHCP Snooping падает | Неправильный формат Option 82 | Использовать стандартные форматы, проверить `-c` |
| Пакеты теряются | MTU меньше, чем пакет с Option 82 | Увеличить MTU или отключить ненужные опции |

---

## Связанные разделы

- **[Концепция DHCP Relay](../../../../Networking/Protocols/DHCP/dhcp_relay.md)** — глубокая теория, RFC и форматы пакетов.
- **[Обзор ISC DHCP](./isc_dhcp_server_overview.md)** — сравнение с современным Kea DHCP.
- **[Базовая настройка сервера](./isc_dhcp_server_basic_config.md)** — как настроить сервер для работы с ретранслятором.
- **[Failover ISC DHCP](./isc_dhcp_server_failover.md)** — отказоустойчивость на стороне сервера.
- **[Проверка и диагностика ISC DHCP](./isc_dhcp_server_verification.md)** — общие методы поиска неисправностей.
- **[Диагностика DHCP](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)** — анализ трафика.
