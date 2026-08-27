# Отказ в установке TCP-соединения

## Определения

**Отказ в установке TCP-соединения (TCP Connection Refusal)** — ситуация, при которой логическое соединение между двумя узлами не может быть установлено на этапе трехстороннего рукопожатия (three-way handshake). Отказ может быть явным (через управляющие сегменты или сообщения протокола ICMP) или неявным (через игнорирование запросов и последующее истечение тайм-аута).

**Основные типы отказа:**

| Тип отказа | Механизм | Ошибка приложения | Вероятная причина |
| :--- | :--- | :--- | :--- |
| **RST (Reset)** | Отправитель получает сегмент с флагом `RST`. | `Connection refused` | Порт закрыт, либо правило REJECT на сетевом экране. |
| **SYN Timeout** | Отсутствие ответа на пакеты `SYN`. | `Connection timed out` | Хост выключен, либо правило DROP на сетевом экране. |
| **ICMP Error** | Приходит сообщение ICMP Type 3 (Unreachable). | `No route to host` / `Refused` | Ошибки маршрутизации или фильтрация (Admin Prohibited). |

**Отличие от разрыва установленного соединения:** Отказ при установке (RST в ответ на SYN) порождает ошибку `Connection refused`, тогда как разрыв уже существующего соединения (RST в состоянии `ESTABLISHED`) приводит к ошибке `Connection reset by peer`. Механизм один и тот же (флаг RST), но момент возникновения и контекст состояния TCP-автомата различаются.

---

## Основные концепции

### Механизм RST (Reset)

Сегмент с флагом **RST** генерируется стеком TCP ядра в ответ на пакет `SYN`, если порт не находится в состоянии `LISTEN` на данном интерфейсе. Флаг RST является одним из шести флагов TCP (SYN, ACK, FIN, RST, PSH, URG) и служит для немедленного принудительного завершения соединения.

- **Скорость:** Отказ происходит мгновенно (в течение одного RTT).
- **Синхронизация:** Флаг RST сообщает клиенту, что хост «живой», сетевой стек функционирует, но конкретный сервис недоступен.
- **Обработка в FSM:** Сегмент RST вызывает немедленный переход сокета в состояние `CLOSED` из любого текущего состояния, минуя стандартную процедуру 4-way handshake. В состоянии `SYN_SENT` получение RST означает, что порт закрыт на сервере или заблокирован Firewall.

**Таблица обработки RST в разных состояниях:**

| Состояние в момент RST | Типичная причина | Эффект для приложения |
| :--- | :--- | :--- |
| **SYN_SENT** | Порт закрыт на сервере или Firewall сбросил пакет. | Ошибка `Connection refused`. |
| **ESTABLISHED** | Сбой процесса, перезагрузка узла, NAT таймаут. | Ошибка `Connection reset by peer`. |
| **FIN_WAIT / TIME_WAIT** | Удаленная сторона уже удалила сокет из памяти. | Сокет немедленно уничтожается. |

**SO_LINGER и генерация RST:**

Опция сокета `SO_LINGER` управляет поведением `close()`. Если установить `SO_LINGER` с `l_onoff = 1` и `l_linger = 0`, ядро немедленно отправит пакет RST вместо стандартного завершения через FIN-сегменты. Это полезно для принудительного освобождения порта, но может приводить к ошибкам `Connection reset by peer` на стороне клиента.

```c
// Пример: немедленный RST при close()
struct linger sl;
sl.l_onoff = 1;
sl.l_linger = 0;
setsockopt(fd, SOL_SOCKET, SO_LINGER, &sl, sizeof(sl));
close(fd); // → отправит RST вместо FIN
```

**Генерация RST сетевым экраном (netfilter/nftables):**

Сетевые экраны в Linux (iptables/nftables) могут генерировать RST-пакеты двумя способами:
- **Модуль REJECT:** Правило `-j REJECT --reject-with tcp-reset` явно генерирует RST-пакет. Приложение получает `Connection refused` мгновенно.
- **Коннекттрак (conntrack):** При переполнении таблицы соединений (`nf_conntrack_max`) или истечении таймаута conntrack может генерировать RST для неизвестных соединений.

### Механизм SYN Timeout и Backoff

Если промежуточный узел или целевой хост игнорирует (DROP) пакет `SYN`, клиент не получает обратной связи и переходит в режим повторных попыток с экспоненциальным ожиданием (**Binary Exponential Backoff**).

**Стандартный цикл в Linux (при `tcp_syn_retries = 6`):**
1. Отправка SYN #1 → ожидание 1 сек.
2. Отправка SYN #2 → ожидание 2 сек.
3. Отправка SYN #3 → ожидание 4 сек.
4. Отправка SYN #4 → ожидание 8 сек.
5. Отправка SYN #5 → ожидание 16 сек.
6. Отправка SYN #6 → ожидание 32 сек.
7. **Итоговый тайм-аут:** через ~63 секунды приложение получает ошибку `ETIMEDOUT`.

**Влияние tcp_syn_retries на задержку:**

| Значение `tcp_syn_retries` | Общее время до ETIMEDOUT | Примечание |
| :--- | :--- | :--- |
| **1** | ~3 сек | Агрессивный (для внутри-ЦОД соединений) |
| **2** | ~7 сек | Рекомендуется для VLAN/local |
| **3** | ~15 сек | Значение по умолчанию в некоторых дистрибутивах |
| **6** | ~63 сек | Значение по умолчанию в Linux |

**TCP_DEFER_ACCEPT и отказ:**

Параметр `TCP_DEFER_ACCEPT` (устанавливается через `setsockopt`) заставляет сервер оставаться в состоянии `SYN_RECV` до тех пор, пока от клиента не поступят первые данные. Если клиент отправляет только SYN-ACK и не передает данные, соединение будет отброшено по таймауту вместо немедленного перехода в Accept Queue. Это экономит ресурсы приложения, но может приводить к задержкам при «пустых» соединениях.

**Взаимодействие с TCP Fast Open (TFO):**

При использовании TCP Fast Open клиент может отправить данные вместе с SYN-пакетом. Если сервер поддерживает TFO, соединение может попасть в Accept Queue сразу с данными, минуя стандартную фазу ожидания ACK. В случае отказа TFO (старый клиент или отключенный TFO) процесс установки идентичен стандартному three-way handshake.

### Сообщения ICMP Destination Unreachable

Маршрутизаторы или файрволы могут отправлять сообщения **ICMP Type 3** для детализации причины отказа:
- **Code 3 (Port Unreachable):** Целевой порт недоступен. Для TCP обычно сопровождается отправкой RST-пакета.
- **Code 10/13 (Admin Prohibited):** Прямое указание на блокировку правилами ACL или Firewall. Клиент получает `No route to host`.
- **Code 1 (Host Unreachable):** Отсутствует маршрут к конкретному узлу или узел не отвечает на ARP-запросы.

**Важно:** Для UDP-трафика ICMP Port Unreachable является стандартным механизмом уведомления о недоступности порта. Для TCP ситуация специфична: основной механизм отказа — RST, а ICMP используется как дополнительная информация от промежуточных маршрутизаторов.

### Взаимодействие с Firewall (iptables/nftables)

Поведение сетевого экрана определяет тип получаемой ошибки:

| Действие | Реакция стека TCP | Ошибка приложения | Сценарий |
| :--- | :--- | :--- | :--- |
| **ACCEPT** | Пакет проходит, сервер обрабатывает | Зависит от состояния порта | Нормальная работа |
| **DROP** | Пакет молча отбрасывается | `Connection timed out` | Эмуляция недоступности хоста |
| **REJECT (tcp-reset)** | Сервер/экран отправляет RST | `Connection refused` | Эмуляция падения сервиса |
| **REJECT (icmp-port-unreachable)** | Отправляется ICMP Type 3 Code 3 | `No route to host` / `Connection refused` | Менее распространено для TCP |

**Примеры правил iptables:**
```bash
# DROP — молчаливое отбрасывание (тайм-аут на клиенте)
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP

# REJECT с TCP RST — мгновенный отказ
sudo iptables -A INPUT -p tcp --dport 8080 -j REJECT --reject-with tcp-reset

# REJECT с ICMP port unreachable
sudo iptables -A INPUT -p tcp --dport 8080 -j REJECT --reject-with icmp-port-unreachable
```

**Примеры правил nftables:**
```bash
# DROP
sudo nft add rule inet filter input tcp dport 8080 drop

# REJECT с TCP RST
sudo nft add rule inet filter input tcp dport 8080 reject with tcp reset

# REJECT с ICMP
sudo nft add rule inet filter input tcp dport 8080 reject with icmp type port-unreachable
```

### Backlog Overflow и RST

В некоторых конфигурациях Linux (при `net.ipv4.tcp_abort_on_overflow = 1`), если очередь `backlog` сервера переполнена, ядро также ответит `RST` вместо игнорирования пакета.

**Механизм переполнения Accept Queue:**
1. Клиент отправляет SYN, сервер отвечает SYN-ACK.
2. Клиент отправляет ACK — соединение готово.
3. Если Accept Queue переполнена, ядро по умолчанию (`tcp_abort_on_overflow = 0`) молча игнорирует ACK. Клиент думает, что ACK потерян, и выполняет ретрансмиссию.
4. При `tcp_abort_on_overflow = 1` ядро немедленно отправляет RST. Клиент получает `Connection refused`.

**Диагностика переполнения:**
```bash
# Проверка текущего лимита accept queue
sysctl net.core.somaxconn
# → net.core.somaxconn = 128

# Мониторинг переполнений
nstat -az | grep -E 'ListenOverflows|ListenDrops'
# → TcpExtTCPListenOverflows   15    0.0
# → TcpExtTCPListenDrops       15    0.0
```

**Рекомендации по настройке backlog для предотвращения отказов:**
- **Edge Proxy (Nginx/Envoy):** `somaxconn = 65535`, `listen 80 backlog=16384;`
- **Database (PostgreSQL):** `somaxconn = 4096`
- **Internal Microservice (Kubernetes):** `somaxconn = 8192`

**Примечание:** Взаимодействие с приложениями: лимит `somaxconn` является глобальным верхним пределом. Приложение при вызове `listen(fd, backlog)` задает своё значение. Эффективный лимит = **min(somaxconn, backlog_приложения)**.

---

## Практические сценарии

### Сценарий 1: Диагностика мгновенного отказа (Connection refused)

**Симптом:** Ошибка `Connection refused` возникает без задержки.

**Причины:**
- Сервис не запущен или слушает другой порт/интерфейс.
- Правило `REJECT` на сетевом экране.
- Переполнение Accept Queue при `tcp_abort_on_overflow = 1`.

**Диагностика:**
1.  **Проверка сокетов:** Убедиться, что процесс слушает правильный IP и порт.
    ```bash
    ss -tlnp | grep :80
    # → LISTEN 0 128 127.0.0.1:80 ...  (ОШИБКА: слушает только localhost)

    # Проверка всех интерфейсов
    ss -tlnp | grep :80
    # → LISTEN 0 128 0.0.0.0:80 ...    (Нормально: слушает на всех интерфейсах)
    ```
2.  **Проверка правил Firewall:** Искать правила с действием `REJECT`.
    ```bash
    sudo iptables -S | grep REJECT
    # → -A INPUT -p tcp --dport 80 -j REJECT --reject-with tcp-reset

    sudo nft list ruleset | grep reject
    # → tcp dport 80 reject with tcp reset
    ```
3.  **Проверка состояния сервиса:**
    ```bash
    systemctl status nginx
    # → Active: active (running) — сервис работает

    # Проверка PID и порта
    ss -tlnp | grep :80
    # → LISTEN 0 128 *:80 users:(("nginx",pid=1234,fd=5))
    ```
4.  **Проверка переполнения Accept Queue:**
    ```bash
    nstat -az | grep -E 'ListenOverflows|ListenDrops'
    # Если ListenOverflows > 0 — увеличить somaxconn или backlog в приложении
    ```

### Сценарий 2: Поиск причин SYN-тайм-аута (Silent Drop)

**Симптом:** Приложение долго «висит» перед выдачей ошибки `Connection timed out`.

**Причины:**
- Хост выключен или не доступен по сети.
- Правило `DROP` на сетевом экране.
- Проблемы с маршрутизацией (отсутствует маршрут).
- Переполнение conntrack таблицы.

**Диагностика через tcpdump:**
```bash
# Отслеживание только SYN-пакетов для порта 443
sudo tcpdump -i eth0 -nn 'port 443 and (tcp[tcpflags] & tcp-syn != 0)'
# → 12:00:01 IP 1.1.1.1.54321 > 2.2.2.2.443: Flags [S], seq 1000
# → 12:00:02 IP 1.1.1.1.54321 > 2.2.2.2.443: Flags [S], seq 1000 (retrans)
```
Если вы видите повторные SYN, но нет входящих `SYN-ACK` или `RST`, пакеты отбрасываются (DROP) где-то на пути или на самом сервере.

**Проверка маршрутизации:**
```bash
# Маршрут до целевого хоста
ip route get 2.2.2.2
# → 2.2.2.2 via 10.0.0.1 dev eth0 src 1.1.1.1

# Проверка可达性
ping -c 3 2.2.2.2
# → 3 packets transmitted, 3 received, 0% packet loss
```

**Проверка conntrack:**
```bash
# Текущее количество записей в conntrack
sysctl net.netfilter.nf_conntrack_count
# → net.netfilter.nf_conntrack_count = 65535

# Лимит
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 65535

# Если count близок к max — переполнение, пакеты DROPаются
```

**Эмуляция DROP для тестирования:**
```bash
# iptables: молчаливое отбрасывание SYN
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP

# nftables: аналогичное правило
sudo nft add rule inet filter input tcp dport 8080 drop
```

### Сценарий 3: Трассировка сбросов через eBPF (2026)

Современные инструменты позволяют увидеть причину сброса пакета внутри ядра Linux (например, из-за неверной контрольной суммы или переполнения очередей):

```bash
# Использование tcpdrop (из bcc-tools) для анализа отброшенных пакетов
sudo tcpdrop
# → TIME     PID     IP  SADDR:SPORT          > DADDR:DPORT          STATE
# → 12:01:00 0       4   1.1.1.1:54321        > 2.2.2.2:443          SYN_SENT
```

**Дополнительные инструменты eBPF:**
```bash
# Анализ задержки handshake (от SYN до SYN-ACK)
sudo tcpconnlat -p 80
# → PID    COMM         IP  LADDR          LPORT  RADDR          RPORT  USECS
# → 1234   curl         4   1.1.1.1        54321  2.2.2.2        80     15234

# Мониторинг всех переходов состояний TCP
sudo tcpstates
# → TIME     PID     COMM             IP  PROTO  OLD        NEW
# → 12:01:00 1234    curl             4   TCP    SYN_SENT   SYN_RECV
```

### Сценарий 4: Диагностика отказа через ICMP

**Симптом:** Ошибка `No route to host` или `Connection refused` с указанием ICMP.

**Диагностика:**
```bash
# Просмотр ICMP-сообщений через tcpdump
sudo tcpdump -i eth0 -nn 'icmp and host 2.2.2.2'
# → 12:00:01 IP 10.0.0.1 > 1.1.1.1: ICMP 2.2.2.2 unreachable (admin prohibited), length 68

# Проверка маршрута до хоста
ip route get 2.2.2.2
# → 2.2.2.2 via 10.0.0.1 dev eth0 src 1.1.1.1

# Проверка правил Firewall на промежуточных узлах
sudo iptables -L -v -n | grep -E "REJECT|DROP"
```

**Интерпретация ICMP-кодов:**
- **ICMP Type 3 Code 3 (Port Unreachable):** Целевой порт закрыт. Для TCP обычно сопровождается RST.
- **ICMP Type 3 Code 10 (Admin Prohibited):** Правило Firewall блокирует доступ. Приложение получает `No route to host`.
- **ICMP Type 3 Code 13 (Communication Administratively Prohibited):** Административная блокировка (аналогично Code 10).

### Сценарий 5: Диагностика переполнения Accept Queue (Backlog)

**Симптом:** При высокой нагрузке клиенты получают `Connection refused`, хотя сервис запущен.

**Диагностика:**
```bash
# Проверка текущего лимита
sysctl net.core.somaxconn
# → net.core.somaxconn = 128  (слишком мало для highload!)

# Мониторинг переполнений в реальном времени
watch -n 1 'nstat -az | grep -E "ListenOverflows|ListenDrops"'
# → TcpExtTCPListenOverflows   15    0.0
# → TcpExtTCPListenDrops       15    0.0

# Проверка Backlog конкретного порта
ss -lnt
# → State  Recv-Q  Send-Q  Local Address:Port  Peer Address:Port
# → LISTEN 0       128     0.0.0.0:80          0.0.0.0:*
#    Send-Q = текущий лимит (min(somaxconn, backlog_приложения))
#    Recv-Q = количество соединений в очереди accept()
```

**Решение:**
```bash
# Увеличение somaxconn
sudo sysctl -w net.core.somaxconn=65535

# Включение отправки RST при переполнении (для балансировщиков)
sudo sysctl -w net.ipv4.tcp_abort_on_overflow=1

# Настройка backlog в Nginx
# /etc/nginx/nginx.conf
# listen 80 backlog=16384;

# Сохранение настроек
echo "net.core.somaxconn = 65535" | sudo tee /etc/sysctl.d/99-somaxconn.conf
echo "net.ipv4.tcp_abort_on_overflow = 1" | sudo tee -a /etc/sysctl.d/99-somaxconn.conf
sudo sysctl -p /etc/sysctl.d/99-somaxconn.conf
```

### Сценарий 6: Тестирование отказа с помощью chaos engineering

**Эмуляция различных типов отказов для проверки отказоустойчивости приложений:**

```bash
# 1. Эмуляция падения сервиса (Connection refused)
sudo iptables -A INPUT -p tcp --dport 8080 -j REJECT --reject-with tcp-reset

# 2. Эмуляция недоступности хоста (Connection timed out)
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP

# 3. Случайные потери (для тестирования retry-логики)
sudo iptables -A INPUT -p tcp --dport 8080 -m statistic --mode random --probability 0.15 -j DROP

# 4. Тестирование для конкретного процесса
sudo iptables -A OUTPUT -m owner --uid-owner 1001 -p tcp --dport 5432 -j DROP

# 5. Тестирование в Docker (использовать цепочку DOCKER-USER)
sudo iptables -I DOCKER-USER -p tcp -d 172.17.0.5 --dport 80 -j DROP
```

**Очистка после тестов:**
```bash
# Удаление правила из iptables
sudo iptables -D INPUT -p tcp --dport 8080 -j REJECT --reject-with tcp-reset

# Полная очистка (осторожно!)
sudo iptables -F
```

---

## Дополнительная информация

### Сравнение ошибок приложения

| Ошибка | Описание | Типичная причина | Время возникновения |
| :--- | :--- | :--- | :--- |
| **`Connection refused`** | Сервер явно отклонил соединение | Порт закрыт, REJECT规则 | Мгновенно (1 RTT) |
| **`Connection reset by peer`** | Установленное соединение сброшено | RST от удаленного хоста | В процессе передачи |
| **`Connection timed out`** | Нет ответа в течение тайм-аута | DROP规则, хост недоступен | Через ~63 сек (по умолчанию) |
| **`No route to host`** | Маршрут не найден или ICMP admin prohibited | ICMP Type 3 Code 10/13 | Мгновенно |

### Sysctl-параметры для управления отказами

| Параметр | Значение по умолчанию | Описание | Рекомендация |
| :--- | :--- | :--- | :--- |
| **`net.ipv4.tcp_syn_retries`** | 6 | Количество повторных SYN перед ETIMEDOUT | 2–3 для локальных сетей |
| **`net.ipv4.tcp_abort_on_overflow`** | 0 | Отправка RST при переполнении Accept Queue | 1 для балансировщиков |
| **`net.core.somaxconn`** | 128 | Максимальный размер Accept Queue | 65535 для highload |
| **`net.ipv4.tcp_max_syn_backlog`** | 1024 | Размер SYN backlog | 16384 для proxy |
| **`net.ipv4.tcp_syncookies`** | 1 | Защита от SYN-флуда через SYN Cookies | 1 (включать всегда) |

**Пример конфигурации для highload (2026):**
```ini
# /etc/sysctl.d/99-network-tuning.conf

# Очередь установленных соединений
net.core.somaxconn = 65535

# Очередь полуоткрытых соединений
net.ipv4.tcp_max_syn_backlog = 16384

# Защита от SYN-флуда
net.ipv4.tcp_syncookies = 1

# Отправка RST при переполнении backlog (для балансировщиков)
net.ipv4.tcp_abort_on_overflow = 1

# Уменьшение retry для быстрого отказа
net.ipv4.tcp_syn_retries = 2
```

### Диагностические команды

```bash
# Просмотр всех TCP-соединений по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c

# Просмотр слушающих портов с указанием процессов
ss -tlnp

# Глобальная статистика переполнений
nstat -az | grep -E 'ListenOverflows|ListenDrops|ReqQFullDrop'

# Мониторинг SYN-пакетов без ответов
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & (tcp-syn) != 0' and port 8080

# Проверка маршрута
ip route get <destination_ip>

# Проверка conntrack
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
```

### IPv6 и отказ в установке соединения

Поведение отказа для IPv6 идентично IPv4 за следующими исключениями:
- Используется заголовок ICMPv6 вместо ICMP.
- ICMPv6 Type 1 (Destination Unreachable) с Code 4 (Port unreachable) вместо ICMP Type 3 Code 3.
- Параметры sysctl аналогичны, но используют префикс `net.ipv6.*`:
  - `net.ipv6.conf.all.accept_redirects`
  - `net.ipv6.icmp.ratelimit`

**Пример диагностики для IPv6:**
```bash
# Проверка слушающих портов на IPv6
ss -tln6 | grep :80

# Правила nftables для IPv6
sudo nft add rule inet filter input tcp dport 8080 reject with tcp reset
```

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (актуальные правила обработки RST и общая спецификация).
- **RFC 1122:** Requirements for Internet Hosts (требования к генерации ICMP и обработке ошибок).
- **RFC 6298:** Computing TCP's Retransmission Timer (алгоритм экспоненциального отката и расчет RTO).
- **RFC 793:** Transmission Control Protocol (классический стандарт, описывающий three-way handshake).
- **RFC 4987:** TCP SYN Flooding and SYN Cookies (защита от SYN-флуда через SYN Cookies).

### См. также

- **[Установка TCP-соединения (Handshake)](./tcp_connection_overview.md)** — описание успешного процесса из трех шагов.
- **[Состояния TCP-соединений](./tcp_connection_states.md)** — подробности состояний `SYN_SENT` и `SYN_RECV`.
- **[Диагностика соединений через ss](./tcp_connection_diagnostics.md)** — практические приемы анализа сокетов.
