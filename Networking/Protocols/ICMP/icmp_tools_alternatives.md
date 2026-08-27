# ICMP: Инструменты диагностики (альтернативы и расширения)

## Определения

**ping** — базовая утилита для проверки L3-связности через ICMP Echo Request/Reply.

**arping** — утилита для проверки связности на канальном уровне (L2) через ARP-запросы. Работает в обход файрволов, блокирующих ICMP.

**fping** — утилита для массового параллельного пинга подсетей. Предназначена для мониторинга множества хостов.

**nping** — часть набора Nmap, утилита для генерации кастомных пакетов (TCP, UDP, ICMP) и измерения отклика.

**hping3** — «комбайн» для сборки произвольных пакетов на любом уровне стека. Позволяет тестировать файрволы, имитировать трафик, выполнять flood-тесты.

**tcping** — утилита для проверки доступности TCP-портов, имитирующая TCP SYN. Используется, когда ICMP заблокирован.

## Основные концепции

### Матрица выбора инструмента

| Инструмент | Уровень | Протокол | Когда использовать |
| :--- | :--- | :--- | :--- |
| **ping** | L3 | ICMP | Стандартная проверка доступности хоста |
| **arping** | L2 | ARP | Проверка доступности в локальном сегменте, когда ICMP заблокирован |
| **fping** | L3 | ICMP | Массовый пинг подсети, мониторинг пулов хостов |
| **nping** | L3/L4 | TCP/UDP/ICMP | Точный контроль флагов, тестирование firewall |
| **hping3** | L2/L3/L4 | TCP/UDP/ICMP | Penetration testing, фрагментация, flood |
| **tcping** | L4 | TCP | Проверка порта, когда ICMP и hping3 недоступны |

### arping (L2 Reachability)

ARP работает на канальном уровне и не маршрутизируется. `arping` отправляет ARP-request и ждет ARP-reply, подтверждающего, что хост жив в локальном сегменте.

**Ключевые особенности:**
- Не зависит от ICMP-блокировки
- Работает только в локальном L2-сегменте (не через роутер)
- Использует для проверки конфликтов IP (DAD — Duplicate Address Detection)
- Требует указания интерфейса (`-I eth0`)

**Практические сценарии:**

```bash
# Базовая проверка доступности хоста в LAN
arping -c 3 -I eth0 192.168.1.10
# → ARPING 192.168.1.10 from 192.168.1.5 on eth0
# → Unicast reply from 192.168.1.10 [AA:BB:CC:DD:EE:FF]  1.234ms
# → Unicast reply from 192.168.1.10 [AA:BB:CC:DD:EE:FF]  1.123ms

# Проверка конфликта IP (Duplicate Address Detection)
arping -D -I eth0 -c 3 192.168.1.50
# → ARPING 192.168.1.50 from 0.0.0.0 on eth0
# → Unicast reply from 192.168.1.50 [AA:BB:CC:DD:EE:FF]  [DUPLICATE!]
# exit code 1 — конфликт обнаружен

# Получение MAC-адреса без ICMP
arping -c 1 -I eth0 192.168.1.1 | grep -oE '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}'
```

### fping (Mass ICMP Ping)

`fping` специализирован на массовом пинге. В отличие от `ping`, работает в параллельном режиме и принимает список целей из файла или аргументов.

**Ключевые особенности:**
- Параллельная отправка запросов (не последовательная как в `ping`)
- Принимает список хостов через stdin или файл (`-f`)
- Подходит для интеграции с Nagios/Zabbix
- Тихий режим (`-q`) для скриптов

**Практические сценарии:**

```bash
# Пинг списка хостов из файла
fping -a -f /etc/hosts.d/webservers
# → 10.0.0.10
# → 10.0.0.11
# → 10.0.0.12

# Пинг подсети
fping -a -g 192.168.1.0/24 2>/dev/null
# → 192.168.1.1
# → 192.168.1.10
# → 192.168.1.100

# Тихий режим с количеством попыток
fping -q -c 3 -b 20 10.0.0.10 10.0.0.11
# → 10.0.0.10 : xmt/rcv/%loss = 3/3/0%, min/avg/max = 1.2/1.5/1.8
# → 10.0.0.11 : xmt/rcv/%loss = 3/0/100%, min/avg/max = -/-/-

# Мониторинг в реальном времени
fping -l -i 100 -c 1000 google.com
# → 1000 bytes from 142.250.80.46: seq=995 ttl=117 time=10.2 ms
# → 1000 bytes from 142.250.80.46: seq=996 ttl=117 time=10.1 ms
```

**Интеграция с Nagios:**

```bash
#!/bin/bash
# check_fping.sh
TARGETS="10.0.0.10 10.0.0.11 10.0.0.12"
LOSS_THRESHOLD=20

if fping -q -c 3 -b 20 $TARGETS 2>&1 | grep -q "[0-9]\+% packet loss"; then
    LOSS=$(fping -q -c 3 -b 20 $TARGETS 2>&1 | grep -oP '\d+% packet loss' | grep -oP '\d+')
    if [ "$LOSS" -gt "$LOSS_THRESHOLD" ]; then
        echo "CRITICAL: packet loss ${LOSS}%"
        exit 2
    fi
fi
echo "OK: all hosts reachable"
exit 0
```

### nping (Nmap Packet Generator)

`nping` часть пакета Nmap. Позволяет генерировать кастомные пакеты TCP, UDP, ICMP и анализировать ответы.

**Ключевые особенности:**
- Генерация произвольных TCP/UDP/ICMP пакетов
- Измерение RTT
- Поддержка raw sockets
- Входит в состав Nmap

**Практические сценарии:**

```bash
# TCP SYN на порт 443 (аналог tcping)
sudo nping --tcp -p 443 google.com
# → Starting Nping 0.7.80 at 2024-01-01 00:00:00
# → SENT (0.0123s) TCP 192.168.1.5:54321 > 142.250.80.46:443 S
# → RCVD (0.0234s) TCP 142.250.80.46:443 > 192.168.1.5:54321 SA

# UDP пинг на DNS порт
sudo nping --udp -p 53 8.8.8.8

# ICMP Echo Request (как ping)
sudo nping --icmp google.com

# TCP-режим с повторениями
sudo nping --tcp -p 443 --count 10 --rate 100 google.com

# Отправка с конкретного источника
sudo nping --tcp -p 443 --source-port 12345 --interface eth0 10.0.0.1
```

### hping3 (Advanced Packet Assembler)

`hping3` — самый мощный инструмент для генерации кастомных пакетов. Позволяет тестировать файрволы, имитировать DoS-трафик, выполнять fragment-тесты.

**Ключевые особенности:**
- Любой протокол: TCP, UDP, ICMP, RAW
- Фрагментация пакетов
- Spoofing IP-адреса
- Flood-режим
- Traceroute через любой протокол

**Практические сценарии:**

```bash
# TCP SYN на порт 80 (обход ICMP-блокировки)
sudo hping3 -S -p 80 google.com
# → HPING google.com (eth0 142.250.80.46): S set, 40 headers + 0 data bytes
# → len=44 ip=142.250.80.46 ttl=117 id=12345 sport=80 flags=SA seq=0 win=29200 rtt=10.2 ms

# TCP SYN flood (стресс-тест файрвола/IDS)
sudo hping3 -S -p 80 --flood --rand-source 10.0.0.20

# Трассировка через TCP (обход firewall)
sudo hping3 --traceroute -T -p 443 google.com

# Фрагментированный пакет (тест на reassembly)
sudo hping3 -f -S -p 80 10.0.0.1

# ICMP flood (тест rate limiting)
sudo hping3 -1 --flood 10.0.0.1

# UDP пинг на кастомный порт
sudo hping3 -2 -p 1234 10.0.0.1

# Spoofing source IP (тест anti-spoofing)
sudo hping3 -S -p 80 -a 1.2.3.4 10.0.0.1

# Точное время RTT с высоким разрешением
sudo hping3 -S -p 443 -c 100 --fast google.com | awk '/rtt=/ {print $7}' | sort -t'=' -k2 -n
```

### tcping (TCP Port Check)

`tcping` — простой инструмент для проверки TCP-портов, аналогичный `ping` но для L4.

**Ключевые особенности:**
- Проверяет доступность конкретного TCP-порта
- Не требует root (в большинстве реализаций)
- Работает там, где ICMP заблокирован

**Практические сценарии:**

```bash
# Установка (Debian/Ubuntu)
sudo apt install tcping

# Базовая проверка порта
tcping google.com 443
# → Connection timeout!
# → Connection timeout!
# → Connected to google.com:443, time=12.34ms

# Проверка с таймаутом
tcping -t 2 google.com 443

# Проверка списка портов
tcping google.com 80 443 22

# IPv6
tcping -6 google.com 443
```

## Практические сценарии

### Сценарий 1: ICMP заблокирован, нужна L2/L4 диагностика

```bash
# 1. Проверка L2 (arping) — работает только в локальном сегменте
arping -c 3 -I eth0 192.168.1.1

# 2. Проверка L4 (nping/tcping)
sudo nping --tcp -p 443 192.168.1.1
tcping 192.168.1.1 443

# 3. Обход firewall через hping3 (если TCP 443 разрешен)
sudo hping3 -S -p 443 192.168.1.1
```

### Сценарий 2: Массовый мониторинг датацентра

```bash
# Генерация списка хостов
seq -f "10.0.0.%g" 1 254 > /tmp/hosts.txt

# Пинг всех хостов (параллельно, 2 секунды)
fping -a -f /tmp/hosts.txt -q -c 1 -b 20

# Доступные хосты
fping -a -f /tmp/hosts.txt -q
# → 10.0.0.1
# → 10.0.0.5
# → 10.0.0.10

# Недоступные хосты
fping -u -f /tmp/hosts.txt -q
# → 10.0.0.2
# → 10.0.0.3

# Интеграция с Ansible inventory
fping -a -f /etc/ansible/hosts 2>/dev/null | xargs -I{} ansible {} -m ping
```

### Сценарий 3: Тестирование файрвола на утечку/spoofing

```bash
# Проверка: блокирует ли firewall IP spoofing?
sudo hping3 -S -p 80 -a 1.2.3.4 10.0.0.1
# Если получаете ответ — spoofing разрешен (опасно)

# Проверка: блокирует ли firewall fragment-пакеты?
sudo hping3 -f -S -p 80 10.0.0.1
# Если получаете ответ — фрагментация разрешена (возможна атака Teardrop)

# Проверка: SYN rate limit
sudo hping3 -S -p 443 --rate 1000 10.0.0.1 -c 1000
# Анализ потерь: если > 10% потерь — есть rate limit
```

### Сценарий 4: TCP traceroute через файрвол

```bash
# Стандартный traceroute (UDP) — блокируется
traceroute 10.0.0.1
# → * * *

# ICMP traceroute — может быть разрешен
sudo traceroute -I -n 10.0.0.1

# TCP traceroute — лучший обход
sudo traceroute -T -p 443 -n 10.0.0.1

# hping3 traceroute (если traceroute не установлен)
sudo hping3 --traceroute -T -p 443 10.0.0.1
```

### Сценарий 5: Stress-test ICMP rate limiting

```bash
# Тест: сколько ICMP/сек выдерживает целевой хост?
sudo hping3 -1 -i u100 -c 10000 10.0.0.1

# Анализ на целевом хосте:
watch -n 1 'cat /proc/net/snmp | grep Icmp'
# Следите за ростом IcmpInErrors или отсутствием роста IcmpInMsgs
```

## Дополнительная информация

*   **[ping — подробное руководство](../../../Linux/Diagnostics/Networking/ping.md)** — стандартная утилита.
*   **[traceroute и mtr](../../../Linux/Diagnostics/Networking/traceroute_mtr.md)** — трассировка пути.
*   **[Альтернативы ping](../../Troubleshooting/ping_alternatives.md)** — TCP/UDP пинг.
*   **[ICMP: Диагностика и безопасность](./icmp_diagnostics_security.md)** — firewall-правила.
*   **[ICMP Echo и ping](./icmp_echo_ping.md)** — детали ICMP Echo Request/Reply.
