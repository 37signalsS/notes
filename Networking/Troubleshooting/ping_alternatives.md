# Альтернативы ping: диагностика доступности без ICMP

## Определения

**Пинг без ICMP (TCP/UDP-пинг)** — метод проверки доступности удалённого хоста без использования протокола **ICMP (Internet Control Message Protocol — протокол межсетевых управляющих сообщений)**. Вместо стандартных пакетов Echo Request/Reply, которые отправляет утилита `ping`, используются пакеты **TCP (Transmission Control Protocol — протокол управления передачей)** или **UDP (User Datagram Protocol — протокол пользовательских датаграмм)** на определённые порты.

Этот подход необходим, когда ICMP-трафик блокируется сетевыми устройствами (брандмауэры, маршрутизаторы), что делает невозможным использование традиционного `ping`. Подробности об ICMP и работе `ping` — в заметке **[ping](../../Linux/Diagnostics/Networking/ping.md)**.

## Предварительные требования

### Установка инструментов

| Инструмент | Установка (Debian/Ubuntu) | Установка (RHEL/CentOS) | Установка (macOS) |
| :--- | :--- | :--- | :--- |
| `nc` (netcat-openbsd) | `sudo apt install netcat-openbsd` | `sudo dnf install nmap-ncat` | Встроен (`/usr/bin/nc`) |
| `nping` | `sudo apt install nping` | Входит в `nmap` | `brew install nmap` |
| `hping3` | `sudo apt install hping3` | `sudo dnf install hping3` | `brew install hping3` |
| `tcping` | `sudo apt install tcping` | из EPEL или исходников | `brew install tcping` |
| `mtr` | `sudo apt install mtr-tiny` | `sudo dnf install mtr` | `brew install mtr` |
| `gping` | `cargo install gping` или бинарник | `cargo install gping` | `brew install gping` |
| `curl` | Встроен | Встроен | Встроен |
| `nmap` | `sudo apt install nmap` | `sudo dnf install nmap` | `brew install nmap` |

### Права доступа

Многие инструменты требуют root-привилегий для отправки raw-пакетов:

| Инструмент | Требуется root | Причина |
| :--- | :--- | :--- |
| `bash /dev/tcp` | Нет | Использует стандартные сокеты ОС |
| `nc -zv` | Нет | Обычные TCP/UDP-сокеты |
| `nping` | Да (для ICMP/RAW) | Raw sockets для кастомных пакетов |
| `nping --tcp` | Нет (в большинстве случаев) | Обычные TCP-сокеты |
| `hping3` | Да | Raw sockets на любом уровне |
| `tcping` | Нет (в большинстве реализаций) | Обычные TCP-сокеты |
| `mtr -T` | Да (для TCP/UDP) | Raw sockets для маршрутизации |
| `curl` | Нет | HTTP/HTTPS через стандартные сокеты |

### Примечание по `/dev/tcp`

Механизм `/dev/tcp` — не стандартный POSIX, а расширение Bash. Он работает только если Bash скомпилирован с поддержкой опции `--enable-net-redirections`. В большинстве серверных дистрибутивов (Debian, Ubuntu, RHEL) эта поддержка включена по умолчанию. В Alpine/Busybox — отсутствует (Busybox `ash` не поддерживает). Проверить:

```bash
# Проверка: поддерживает ли ваш Bash /dev/tcp
echo "test" > /dev/tcp/127.0.0.1/22 2>/dev/null && echo "Supported" || echo "Not supported"
```

## Основные концепции

### Принцип работы TCP-пинга

Принцип заключается в имитации установления соединения (3-way handshake) с сервисом на удальном хосте на **Транспортном уровне (L4)**. Отправляется TCP-пакет (чаще всего с флагом `SYN`) на известный порт (например, 80 для HTTP или 22 для SSH).

#### Возможные исходы TCP-проверки

| Ответ хоста | Значение | Состояние | Доступность |
| :--- | :--- | :--- | :--- |
| **SYN/ACK** | Порт открыт, сервис активен | `Listen` | Хост доступен |
| **RST (Reset)** | Порт закрыт, сервис не запущен | `Closed` | Хост доступен |
| **Нет ответа** | Хост выключен или трафик отброшен | `Filtered` | Недоступен / Блокировка |

**Ключевой принцип:** любой ответ от хоста (включая `RST`) подтверждает его сетевую доступность. Отсутствие ответа — единственный индикатор недоступности или полной блокировки трафика (DROP).

### Принцип работы UDP-пинга

UDP — протокол без установления соединения. Проверка доступности через UDP сложнее, так как отсутствие ответа может означать как открытый порт, так и потерю пакета.

- **Порт открыт:** Сервис может ответить (зависит от приложения) или ничего не прислать.
- **Порт закрыт:** Узел (стек ОС) должен вернуть ICMP-сообщение **Destination Unreachable (Type 3, Code 3 — Port Unreachable)**. Получение такого сообщения подтверждает доступность хоста.

### Когда использовать альтернативы ping

- **ICMP заблокирован** файрволом — стандартная практика в публичных облаках (AWS, Azure) и корпоративных сетях.
- **Проверка прикладного уровня (L7)** — `ping` не покажет, что веб-сервер «упал» при живой ОС.
- **Измерение RTT для конкретного пути** — TCP-трафик может маршрутизироваться иначе, чем ICMP.

## Практические сценарии

### 1. Встроенные возможности Bash (/dev/tcp)

Самый быстрый способ в Linux без установки стороннего ПО. Использует встроенный механизм Bash для работы с сокетами.

```bash
# Проверка доступности порта 80 на google.com (timeout 2 сек)
(timeout 2 bash -c "</dev/tcp/google.com/80") &>/dev/null && echo "Open" || echo "Closed/Timeout"
# → Open
```

```bash
# Альтернативный синтаксис (с explicit fd-операцией)
(echo > /dev/tcp/google.com/443) 2>/dev/null && echo "Port open" || echo "Port closed"
# → Port open
```

```bash
# Проверка с указанием таймаута через опцию ConnectTimeout
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/10.0.0.1/22' 2>/dev/null && echo "SSH开放" || echo "SSH закрыт/таймаут"
```

**Валидация:** Код возврата `0` — порт открыт и хост доступен. Ненулевой код — порт закрыт, таймаут или хост недоступен. Различить «порт закрыт» и «таймаут» сложно без дополнительных инструментов.

**Особенности:**
- Работает только с TCP (не с UDP).
- Не предоставляет информации о времени отклика (RTT).
- В скриптах полезно оборачивать в `timeout N`, чтобы избежать бесконечного ожидания при полностью отброшенном трафике (DROP).

### 2. Проверка через nc, nmap, telnet

**Использование `nc` (netcat):**
Универсальный инструмент для работы с TCP/UDP. Существует несколько реализаций: `netcat-openbsd` ( deb-based), `nmap-ncat` (Red Hat), `ncat` (от Nmap).

```bash
# TCP-проверка (-z — сканирование, -v — подробно)
nc -zv 192.168.0.1 22
# → Connection to 192.168.0.1 22 port [tcp/ssh] succeeded!

# UDP-проверка (флаг -u)
nc -zuv 192.168.0.1 53
# → Connection to 192.168.0.1 53 port [udp/domain] succeeded!

# Проверка с таймаутом (-w, в секундах)
nc -zv -w 3 10.0.0.50 443

# Проверка нескольких портов
nc -zv 192.168.0.1 22 80 443

# Проверка диапазона портов
nc -zv 192.168.0.1 20-25
```

*Примечание: в версиях `ncat` (от Nmap) и некоторых дистрибутивах флаг `-z` может не поддерживаться — используйте `nmap` или `nping`.*

**Интерпретация результатов:**
- `succeeded` — порт открыт, TCP-соединение установлено (SYN/ACK получен).
- `Connection refused` — порт закрыт на стороне хоста (RST получен). Хост доступен, но сервис не запущен.
- `timed out` — нет ответа. Возможные причины: хост недоступен, файрвол блокирует трафик (DROP), неправильный маршрут.
- `No route to host` — проблема маршрутизации на уровне ОС.

```bash
# Использование nmap для быстрой проверки портов
nmap -Pn -p 22,80,443 192.168.0.1
# → PORT    STATE    SERVICE
# → 22/tcp  open     ssh
# → 80/tcp  open     http
# → 443/tcp filtered https
```

**Использование `nping` (часть Nmap):**
Позволяет проводить детальный пинг на разных уровнях. Более гибкий, чем `nc`, но требует understanding протоколов.

```bash
# TCP SYN-пинг на порт 443 (базовый)
sudo nping --tcp -p 443 8.8.8.8
# → Starting Nping 0.7.95
# → SENT (0.0120s) TCP 192.168.1.5:54321 > 8.8.8.8:443 S
# → RCVD (0.0230s) TCP 8.8.8.8:443 > 192.168.1.5:54321 SA
# → Max rtt: 11.00ms | Min rtt: 11.00ms | Avg rtt: 11.00ms

# TCP SYN-пинг с количеством пакетов
sudo nping --tcp -p 443 -c 5 8.8.8.8

# Эмуляция ICMP через UDP (ожидание Port Unreachable)
sudo nping --udp -p 53 8.8.8.8

# TCP-пинг с конкретным интервалом (100ms между пакетами)
sudo nping --tcp -p 443 --delay 100ms 8.8.8.8

# Проверка с указанием MTU (полезно для обнаружения фрагментации)
sudo nping --tcp -p 80 --mtu 1400 example.com
```

**Использование `telnet`:**
Старый, но надежный метод проверки TCP. Для выхода: `Ctrl+]`, затем `quit`.

```bash
telnet example.com 80
# → Connected to example.com.
```

*Примечание: `telnet` передаёт данные в открытом виде (без шифрования). Используйте только для быстрой проверки доступности, не для передачи конфиденциальных данных. В многих современных дистрибутивах `telnet` не установлен по умолчанию.*

### 3. Проверка веб-сервисов (curl, wget)

Используется для проверки доступности на **Прикладном уровне (L7)**. Помимо проверки порта, позволяет оценить работоспособность приложения.

```bash
# Проверка HTTP-кода ответа (без скачивания тела)
curl -Is http://example.com | head -n 1
# → HTTP/1.1 200 OK

# Проверка HTTPS с выводом кода ответа
curl -s -o /dev/null -w "%{http_code}" https://example.com
# → 200

# Проверка с таймаутом (connect-timeout 3 сек, max-time 5 сек)
curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 https://example.com
# → 200

# Проверка конкретного health-check эндпоинта
curl -sf http://app.internal:8080/health || echo "Service unhealthy"

# Детальная информация о подключении (DNS, TCP, TLS, TTFB)
curl -w "@curl-format.txt" -s -o /dev/null https://example.com
```

Формат-файл `curl-format.txt` для измерения фаз соединения:

```
    time_namelookup:  %{time_namelookup}\n
       time_connect:  %{time_connect}\n
    time_appconnect:  %{time_appconnect}\n
   time_pretransfer:  %{time_pretransfer}\n
      time_redirect:  %{time_redirect}\n
 time_starttransfer:  %{time_starttransfer}\n
                     ----------\n
          time_total:  %{time_total}\n
```

**Интерпретация результатов HTTP-кодов:**
- `200` — сервис работает нормально.
- `301/302` — перенаправление (может означать проблему с конфигурацией).
- `403` — доступ запрещён (проблема авторизации/firewall на L7).
- `404` — ресурс не найден (сервис работает, но путь изменён).
- `500/502/503` — внутренняя ошибка сервера, бэкенд недоступен или перегружен.
- `000` — не удалось установить соединение (проблема на L3/L4 или DNS).

Подробнее: **[Диагностика с curl](../../Linux/Diagnostics/Networking/curl_network_diagnostics.md)**.

### 4. Расширенная диагностика (hping3, mtr)

**`hping3`** — «комбайн» для сборки произвольных пакетов. Позволяет обходить правила файрволов, имитируя легитимный трафик. Требует root-доступа для большинства операций.

```bash
# Отправка TCP SYN на порт 80 (режим пинга)
hping3 -S -p 80 example.com
# → len=46 ip=93.184.216.34 flags=SA seq=0 ttl=56 rtt=10.5 ms

# Проверка с количеством пакетов (-c)
sudo hping3 -S -p 443 -c 5 example.com

# Traceroute через TCP (обход файрволов блокирующих UDP/ICMP)
sudo hping3 --traceroute -T -p 443 example.com

# Тест фрагментации пакетов (-f)
sudo hping3 -f -S -p 80 10.0.0.1

# Спуфинг IP-адреса для тестирования anti-spoofing правил
sudo hping3 -S -p 80 -a 1.2.3.4 10.0.0.1
```

**`mtr` (My Traceroute)** в режиме TCP/UDP:
Позволяет увидеть потери на каждом узле маршрута для конкретного порта. Часто используется для выявления межзонных задержек (cross-zone latency).

```bash
# Трассировка по TCP порту 443 (требует root)
sudo mtr -T -P 443 8.8.8.8

# Трассировка по ICMP (базовый режим)
mtr -c 10 8.8.8.8

# Неоконсольный режим (reports) — для логов и скриптов
mtr -T -P 443 -c 10 --report 8.8.8.8
# → Start: 2026-01-01T00:00:00+0000
# → HOST: router.local       Loss%   Snt   Last   Avg  Best  Wrst StDev
# →   1. 192.168.1.1         0.0%    10    1.2   1.5   1.1   2.0   0.3
# →   2. 10.0.0.1            0.0%    10    5.3   5.8   5.0   7.2   0.7
# →   3. 8.8.8.8             0.0%    10   10.2  10.5   9.8  12.1   0.6
```

**Интерпретация mtr:**
- `Loss%` > 0 на конкретном хосте указывает на проблему на этом сегменте маршрута.
- Резкий рост `Avg` на определённом хосте — узкое место по пропускной способности или очереди.
- `StDev` > 50% от `Avg` — высокая вариативность задержек (джиттер), проблема с QoS или перегрузкой.

*Подробнее о применении mtr для AZ-диагностики: **[Cross-zone traffic и задержки](./cross-zone-latency.md)**.*

### 5. Визуализация и мониторинг (gping)

**`gping`** строит графики задержек (RTT) в терминале, поддерживая TCP. Полезен для визуального сравнения задержек до нескольких хостов одновременно.

```bash
# Визуальный TCP-пинг
gping --tcp -p 443 google.com

# Сравнение задержек до нескольких хостов
gping --tcp -p 443 google.com cloudflare.com 1.1.1.1

# ICMP-пинг (по умолчанию)
gping 8.8.8.8 ya.ru

# С указанием интервала (100ms)
gping --tcp -p 443 --interval 100ms google.com
```

**Применение:**
- Сравнение задержек до разных CDN-точек для выбора оптимального региона.
- Визуализация «дребезга» (jitter) — нестабильности задержек.
- Мониторинг в реальном времени во время инцидента.

### 6. Специализированные утилиты (tcping)

**`tcping`** имитирует поведение классического `ping`, но работает по TCP. Показывает время отклика TCP-соединения, что полезно когда ICMP заблокирован.

```bash
# Установка в Linux
sudo apt install tcping

# Базовая проверка порта
tcping example.com 80
# → Connected to example.com:80, time=12.45ms
# → Connected to example.com:80, time=11.23ms
# → Connected to example.com:80, time=13.01ms
# → Send echo probing to example.com:80 3 times over 3 seconds
# → Success rate: 100%

# Проверка с таймаутом (-t, в секундах)
tcping -t 3 example.com 443

# Проверка нескольких портов
tcping example.com 80 443 22

# IPv6-проверка
tcping -6 example.com 443

# Вывод в формате, аналогичном ping (для piping)
tcping -i 1 -c 5 example.com 443 | grep -E "seq=|Success"
```

**Windows (PowerShell):**
Встроенная альтернатива `tcping` — командлет `Test-NetConnection`. Не требует установки дополнительного ПО.

```powershell
# Проверка порта 443
Test-NetConnection -ComputerName google.com -Port 443
# → ComputerName     : google.com
# → RemotePort       : 443
# → InterfaceAlias   : Ethernet
# → SourceAddress    : 192.168.1.5
# → TcpTestSucceeded : True

# Проверка с информацией о маршруте
Test-NetConnection -ComputerName google.com -Port 443 -InformationLevel Detailed

# Проверка ICMP-связности одновременно с TCP
Test-NetConnection -ComputerName google.com -Port 443 -DiagnoseRouting
```

```bash
# Установка tcping в Windows (через chocolatey)
choco install tcping
# Или скачать бинарник с GitHub: https://github.com/tiwin16/tcping
```

### 7. Скриптинг и автоматизация (Scapy)

Для сложных случаев, когда нужно анализировать ответы программно. Scapy позволяет конструировать произвольные пакеты и обрабатывать ответы в Python.

```python
# Пример на Python + Scapy для TCP SYN проверки
from scapy.all import IP, TCP, sr1, conf
import sys

conf.verb = 0  # Отключить вывод Scapy

def check_port(host, port, timeout=2):
    """Проверка TCP-порта через SYN-пинг."""
    packet = IP(dst=host)/TCP(dport=port, flags="S")
    response = sr1(packet, timeout=timeout, verbose=0)

    if response is None:
        return "filtered/no-response"
    elif response.haslayer(TCP):
        flags = response.getlayer(TCP).flags
        if flags == 0x12:  # SYN/ACK
            return "open"
        elif flags == 0x14:  # RST/ACK
            return "closed"
    return "unknown"

# Проверка портов
for port in [22, 80, 443]:
    result = check_port("192.168.1.1", port)
    print(f"Port {port}: {result}")
# → Port 22: open
# → Port 80: open
# → Port 443: closed
```

**Установка Scapy:**

```bash
pip3 install scapy
# Или в виртуальном окружении
python3 -m venv .venv && source .venv/bin/activate && pip install scapy
```

*Примечание: для использования Scapy требуются root-привилегии (raw sockets). Запускайте скрипты через `sudo` или настройте `cap_net_raw`.*

## Дополнительная информация

### Сравнительная таблица инструментов

| Утилита | Протокол | Уровень | Root-требуется | RTT | Особенности |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `bash /dev/tcp` | TCP | L4 | Нет | Нет | Не требует установки ПО. Минимальная информация. |
| `nc` | TCP/UDP | L4 | Нет | Нет | Самый быстрый способ проверки одного порта. |
| `nping` | TCP/UDP/ICMP | L3/L4 | Да (для ICMP/RAW) | Да | Гибкая настройка флагов, входит в Nmap. |
| `curl` | HTTP/HTTPS | L7 | Нет | Да | Проверяет работоспособность веб-приложения. |
| `hping3` | TCP/UDP/ICMP | L2-L4 | Да | Да | Мощный инструмент для тестов безопасности, flood. |
| `mtr` | TCP/UDP/ICMP | L3/L4 | Да (для TCP/UDP) | Да | Локализация проблем на каждом узле маршрута. |
| `gping` | TCP/ICMP | L3/L4 | Нет (для TCP) | Да | Визуализация и сравнение RTT в реальном времени. |
| `tcping` | TCP | L4 | Нет | Да | Аналог ping для TCP, есть PowerShell-версия. |
| `Test-NetConnection` | TCP | L4 | Нет | Нет | Нативный инструмент для Windows/PowerShell. |
| `Scapy` | Любые | L2-L7 | Да | Да | Программируемая генерация любых пакетов. |

### Граничные случаи и особенности

**IPv6:**
- `nc -zv -6 host 443` — проверка по IPv6.
- `nping --tcp -6 -p 443 host` — IPv6-режим в nping.
- `tcping -6 host 443` — IPv6 в tcping.
- `curl -6 https://host` — IPv6 в curl.
- При проверке IPv6 убедитесь, что маршрут до IPv6-адреса существует: `ip -6 route get <ipv6_addr>`.

**Файрволы и NAT:**
- Файрвол может отвечать RST на закрытые порты или молча отбрасывать пакеты (DROP). Оба варианта означают «ответ от хоста» — но только RST подтверждает доступность хоста.
- За NAT-ом хост может быть недоступен напрямую — используйте port-forwarding или VPN.
- При проверке через файрвол учитывайте, что SYN-флаг может обрабатываться иначе, чем ACK или FIN.

**Очереди и rate-limiting:**
- Многие файрволы имеют ограничения на количество SYN-пакетов в секунду (SYN rate limit). При превышении порога пакеты отбрасываются.
- В облачных средах (AWS, Azure) security groups могут иметь неявные ограничения — если вы получаете чередование success/timeout, проверьте лимиты.

**Особенности работы в контейнерах:**
- В контейнерах на базе Alpine/Busybox нет `bash` с поддержкой `/dev/tcp`. Используйте `nc` или `curl`.
- В distroless-образах отсутствуют сетевые утилиты — для healthcheck используйте `grpc_health_probe` или кастомный бинарник.
- `kubectl exec` в Kubernetes позволяет запускать диагностику внутри пода: `kubectl exec <pod> -- nc -zv <service> <port>`.

### Практические рекомендации

1. **Минимализм:** В bash-скриптах используйте `/dev/tcp` для проверки зависимостей перед запуском.
2. **Траблшутинг сервиса:** Если `ping` работает, а сервис нет — используйте `nc` или `telnet`.
3. **Облачные среды:** В AWS/GCP всегда начинайте диагностику с TCP-проверок (80/443/22), так как ICMP часто выключен в Security Groups по умолчанию.
4. **Анализ задержек:** Для мониторинга "дребезга" сети (jitter) используйте `gping --tcp`.
5. **Автоматизация:** Используйте `nc -zv -w 3` с кодом возврата в скриптах. `0` = успех, `1` = ошибка.
6. **Быстрая эскалация:** Начинайте с простых инструментов (`nc`, `curl`) и переходите к сложным (`mtr`, `tcpdump`, `pwru`) только при необходимости.

### Диагностика типичных проблем

| Симптом | Вероятная причина | Инструмент диагностики | Команда |
| :--- | :--- | :--- | :--- |
| `ping` работает, `nc` нет | Файрвол блокирует TCP-порты | `nping --tcp -p 80` | `sudo nping --tcp -p 80 <host>` |
| `nc` работает, `curl` нет | Проблема на L7 (HTTP) | `curl -v` | `curl -v https://host` |
| `Connection refused` | Сервис не запущен | `ss -tlnp` | `ss -tlnp \| grep :80` |
| `timed out` | Хост недоступен или DROP | `mtr -T -P 443` | `sudo mtr -T -P 443 <host>` |
| `No route to host` | Проблема маршрутизации | `ip route get` | `ip route get <host>` |
| UDP-проверка не отвечает | Сервис не генерирует ответ | `hping3 -2 -p 53` | `sudo hping3 -2 -p 53 <host>` |
| Регулярные timeout | Packet loss, jitter | `ping -c 20` + `mtr` | `mtr -rwzc 100 <host>` |

**Алгоритм диагностики (Bottom-up):**

1. Проверьте базовую связность: `ping -c 3 <gateway>` (L3).
2. Проверьте DNS: `dig example.com` или `resolvectl query example.com`.
3. Проверьте TCP-порт: `nc -zv <host> <port>` или `timeout 3 bash -c '</dev/tcp/host/port'`.
4. Если порт закрыт — проверьте сервис: `ss -tlnp | grep :<port>`.
5. Если порт.filtered — проверьте маршрутизацию и файрвол: `mtr -T -P <port> <host>`.
6. Если проблема сохраняется — захватите пакеты: `tcpdump -i any host <host> and port <port>`.

### Безопасность

- Использование `hping3`, `nping` и агрессивное сканирование `nmap` может быть расценено системами **IDS/IPS (Intrusion Detection/Prevention System)** как попытка атаки.
- При сканировании внешних ресурсов используйте минимальную частоту запросов.
- Не используйте `hping3 --flood` на боевых системах без явного разрешения — это может вызвать DoS-состояние.
- При спуфинге IP-адресов (`-a`) убедитесь, что это разрешено политикой безопасности вашей организации.

### См. также

- **[ping](../../Linux/Diagnostics/Networking/ping.md)** — база работы ICMP.
- **[Диагностика с curl](../../Linux/Diagnostics/Networking/curl_network_diagnostics.md)** — HTTP/HTTPS-диагностика.
- **[Инструменты диагностики сети](../../Linux/Networking/network_diagnostics_tools.md)** — общий обзор.
