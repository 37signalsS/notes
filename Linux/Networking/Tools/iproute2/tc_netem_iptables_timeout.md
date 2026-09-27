# Эмуляция сетевых таймаутов через сетевые экраны

## Определения

* **Сетевой таймаут (Network Timeout)** — состояние, при котором сетевое взаимодействие прерывается из-за отсутствия ответа в течение ожидаемого периода.
* **Connection Timeout** — отказ в установке TCP-соединения на этапе трехстороннего рукопожатия (отсутствие ответа на пакет `SYN`).
* **Request/Read Timeout** — обрыв связи в уже установленном соединении (ESTABLISHED), когда данные отправлены, но подтверждение (ACK) или ответ не приходят.
* **DROP** — действие файрвола по молчаливому уничтожению пакета. Вызывает повторные попытки (ретрансмиссии) со стороны отправителя.
* **REJECT** — явное отклонение пакета с уведомлением отправителя (через ICMP или TCP RST). Не вызывает таймаута, а приводит к немедленной ошибке.

## Предпосылки

### Требования к пакетам

| Компонент | Дистрибутив | Команда установки |
| :--- | :--- | :--- |
| **iptables** | Debian / Ubuntu | `sudo apt install iptables` |
| | RHEL / Fedora / CentOS | `sudo dnf install iptables` |
| **nftables** | Debian / Ubuntu | `sudo apt install nftables` |
| | RHEL / Fedora / CentOS | `sudo dnf install nftables` |
| **tcpdump** (для валидации) | Debian / Ubuntu | `sudo apt install tcpdump` |
| | RHEL / Fedora / CentOS | `sudo dnf install tcpdump` |

**Статус (2026):** `iptables` находится в режиме ограниченной поддержки (Legacy Maintenance Mode). В современных дистрибутивах (Debian 12+, Ubuntu 24.04+, RHEL 9+) рекомендуется использовать `nftables`. Однако `iptables-nft` (совместимость) по-прежнему широко распространен.

### Права root

Все команды `iptables`/`nft` требуют привилегий суперпользователя (`sudo`).

### Проверка текущего состояния

```bash
# Просмотр текущих правил iptables
sudo iptables -L INPUT -v -n --line-numbers

# Просмотр текущих правил nftables
sudo nft list ruleset
```

## Основные концепции

### Преимущества файрволов перед tc netem

В отличие от `tc netem` (см. **[tc netem: Эмуляция сети](./tc_netem.md)**), работающего на уровне интерфейса (L2), сетевые экраны (`iptables`, `nftables`) позволяют эмулировать проблемы более селективно:

1. **L4-селективность:** возможность блокировать только специфические порты, протоколы или комбинации TCP-флагов.
2. **Имитация "Черных дыр":** `DROP` идеально моделирует падение удаленного хоста или блокировку на промежуточном узле, заставляя стек TCP использовать экспоненциальный рост интервалов между ретрансмиссиями.
3. **Асимметричные сбои:** блокировка только входящего (`INPUT`) или только исходящего (`OUTPUT`) трафика, что часто встречается в реальных сетях.
4. **Фильтрация по процессам:** использование модуля `owner` для эмуляции проблем только для конкретного приложения (по UID/GID).

### Сравнение tc netem и iptables/nftables

| Критерий | `tc netem` | `iptables`/`nftables` |
| :--- | :--- | :--- |
| **Уровень** | L2 (интерфейс) | L3-L4 (IP/порт) |
| **Селективность** | Весь трафик интерфейса | По IP, порту, протоколу, процессу |
| **Задержка (latency)** | Да (`delay`) | Ограниченно (`ip rule` + `ip route` + `tc`) |
| **Джиттер** | Да (`delay ... distribution`) | Нет |
| **Потери** | Да (`loss`) | Да (`statistic --mode random`) |
| **Блокировка** | Нет | Да (`DROP`, `REJECT`) |
| **Асимметрия** | Ограниченно (via `ingress`) | Полная (INPUT/OUTPUT/FORWARD) |
| **Фильтрация по процессу** | Нет | Да (`owner --uid-owner`) |

### Поведение TCP при DROP и REJECT

Понимание поведения TCP-стека критично для корректного тестирования:

**DROP (молчаливое отбрасывание):**
* Клиент отправляет `SYN` и ждет `SYN-ACK`.
* Не получая ответа, стек TCP запускает **Binary Exponential Backoff** — удвоение интервала между повторными попытками.
* По умолчанию: 1с → 2с → 4с → 8с → 16с → 32с → 64с (после чего — ошибка).
* Общее время до ошибки: **~127 секунд** (7 попыток).
* Типичная ошибка приложения: `Connection timed out`.

**REJECT (явное отклонение):**
* Клиент получает `RST` (TCP Reset) или `ICMP Unreachable`.
* Ошибка возникает немедленно (в течение 1 RTT).
* Типичные ошибки приложения: `Connection refused` (RST) или `No route to host` (ICMP).

**Поведение при Established-соединении:**
* Если `DROP` применяется к пакетам `ESTABLISHED`-соединения, TCP-стек будет повторять отправку данных с тем же экспоненциальным ростом интервалов.
* Если `DROP` применяется только к `SYN` — новые соединения не устанавливаются, но существующие продолжают работу.

## Практические сценарии

### Сценарий 1: Эмуляция таймаута соединения (Connection Timeout)

Имитация полной недоступности порта для новых клиентов.

#### Через iptables
```bash
# Игнорировать попытки установки соединения на порт 8080
sudo iptables -A INPUT -p tcp --syn --dport 8080 -j DROP
```

#### Через nftables
```bash
sudo nft add rule inet filter input tcp dport 8080 tcp flags syn drop
```

**Ожидаемый результат:**
```bash
# Клиент:
curl -v http://server:8080
# → * connect to server port 8080 failed: Connection timed out
# → * Failed to connect to server port 8080: Connection timed out

# На сервере (tcpdump):
sudo tcpdump -ni any 'tcp port 8080 and (tcp[tcpflags] & tcp-syn != 0)'
# → SYN пакеты уходят, но SYN-ACK не возвращается
```

### Сценарий 2: Эмуляция таймаута чтения (Read Timeout)

Соединение устанавливается успешно, но передача данных блокируется. Это позволяет проверить, как приложение обрабатывает частичные отказы.

#### Через iptables
```bash
# Блокировка пакетов, несущих данные (флаг PSH)
sudo iptables -A INPUT -p tcp --tcp-flags PSH PSH --dport 8080 -j DROP
```

#### Через nftables
```bash
sudo nft add rule inet filter input tcp dport 8080 tcp flags psh drop
```

**Ожидаемый результат:**
```bash
# TCP-соединение устанавливается (3-way handshake завершается),
# но при попытке чтения данных клиент зависает.

# На сервере (tcpdump):
sudo tcpdump -ni any 'tcp port 8080'
# → SYN → SYN-ACK → ACK → PSH (данные) → [nothing] → PSH (повтор) → ...
```

### Сценарий 3: Эмуляция случайных и периодических потерь

Имитация "шумного" или перегруженного канала связи.

#### Через iptables (модуль statistic)
```bash
# Каждое 5-е соединение (или пакет) будет отброшено
sudo iptables -A INPUT -p tcp --dport 8080 -m statistic --mode nth --every 5 -j DROP

# Случайная потеря 15% входящего трафика
sudo iptables -A INPUT -p tcp --dport 8080 -m statistic --mode random --probability 0.15 -j DROP
```

#### Через nftables (модуль numgen)
```bash
# Циклическое отбрасывание каждого 10-го пакета
sudo nft add rule inet filter input tcp dport 8080 numgen inc mod 10 0 drop

# Случайная потеря 10% пакетов (через random expression)
sudo nft add rule inet filter input tcp dport 8080 random drop 10%
```

**Ожидаемый результат:**
```bash
# Статистика ретрансмиссий (должны появиться повторы):
nstat -az | grep TcpRetrans
# → TcpRetransSegs    123    0.0    # tăng

# Мониторинг в реальном времени:
watch -n 1 'ss -ti dst server:8080 | grep -E "retrans|cwnd"'
# → retrans 3/8  rto 4000  rtt 250/100  cwnd 5
```

### Сценарий 4: Эмуляция латентности (задержки) через iptables

Блокировка через `iptables` не добавляет задержку — пакеты отбрасываются мгновенно. Для эмуляции задержки на уровне файрвола комбинируют `iptables` (для фильтрации) и `tc netem` (для задержки).

```bash
# 1. Создать класс для целевого трафика через tc
sudo tc qdisc add dev eth0 root handle 1: prio
sudo tc qdisc add dev eth0 parent 1:3 handle 30: netem delay 500ms

# 2. Направить трафик на порт 8080 в этот класс через tc filter
sudo tc filter add dev eth0 protocol ip parent 1:0 prio 3 u32 \
    match ip dport 8080 0xffff flowid 1:3

# 3. Ограничить эмуляцию конкретным источником через iptables + MARK
sudo iptables -t mangle -A INPUT -s 10.0.0.0/24 -p tcp --dport 8080 \
    -j MARK --set-mark 1

sudo tc filter add dev eth0 parent 1:0 protocol ip handle 1 fw flowid 1:3
```

**Примечание:** `iptables` не имеет встроенного модуля задержки. Для чистой эмуляции латентности используйте `tc netem delay` (см. **[tc netem](./tc_netem.md)**).

### Сценарий 5: Эмуляция ограничения скорости соединений (Rate Limiting)

Ограничение количества новых соединений в секунду — типичная защита от DDoS, которую нужно тестировать.

#### Через iptables (модуль limit)
```bash
# Ограничение до 10 новых соединений в секунду на порт 8080
sudo iptables -A INPUT -p tcp --syn --dport 8080 -m limit \
    --limit 10/sec --limit-burst 20 -j ACCEPT

# Все, что превышает лимит — DROP
sudo iptables -A INPUT -p tcp --syn --dport 8080 -j DROP
```

#### Через iptables (модуль connlimit)
```bash
# Максимум 50 одновременных соединений на порт 8080
sudo iptables -A INPUT -p tcp --dport 8080 -m connlimit \
    --connlimit-above 50 -j DROP

# Максимум 10 соединений с одного IP
sudo iptables -A INPUT -p tcp --dport 8080 -m connlimit \
    --connlimit-above 10 --connlimit-mask 32 -j DROP
```

#### Через nftables
```bash
# Лимит 10 соединений/сек
sudo nft add rule inet filter input tcp dport 8080 tcp flags syn limit rate 10/second accept
sudo nft add rule inet filter input tcp dport 8080 tcp flags syn drop

# Максимум 50 одновременных соединений
sudo nft add rule inet filter input tcp dport 8080 ct count over 50 drop
```

**Ожидаемый результат:**
```bash
# При превышении лимита — новые соединения отбрасываются:
ab -n 200 -c 50 http://server:8080/
# → Complete requests: 150  (остальные 50 — timeout/DROP)

# Проверка счетчиков:
sudo iptables -L INPUT -v -n | grep -E "limit|connlimit"
# → pkts 200  bytes 12000  limit: 10/sec  ACCEPT  tcp  *  *  0.0.0.0/0  0.0.0.0/0  tcp dpt:8080
```

### Сценарий 6: Изоляция приложения (по пользователю)

Эмуляция проблем с API только для одного системного сервиса, не затрагивая остальную систему.

```bash
# Блокировка доступа к внешней базе данных для пользователя 'app-worker' (UID 1001)
sudo iptables -A OUTPUT -m owner --uid-owner 1001 -p tcp --dport 5432 -j DROP
```

**Примечание:** Модуль `owner` работает только для пакетов, генерируемых локальными процессами (цепочка `OUTPUT`). Для входящего трафика фильтрация по UID невозможна.

### Сценарий 7: Блокировка ICMP (влияние на PMTUD и診断)

Блокировка ICMP может привести к проблемам с Path MTU Discovery и診断ом.

```bash
# Блокировка ICMP echo (ping) — НЕ рекомендуется для production
sudo iptables -A INPUT -p icmp --icmp-type echo-request -j DROP

# Блокировка ICMP Destination Unreachable — КРИТИЧНО: нарушает PMTUD
sudo iptables -A INPUT -p icmp --icmp-type destination-unreachable -j DROP

# Правильная настройка: разрешить критический ICMP
sudo iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 1/s -j ACCEPT
sudo iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT
sudo iptables -A INPUT -p icmp --icmp-type time-exceeded -j ACCEPT
```

**Важно:** Блокировка `ICMP Destination Unreachable (Type 3)` с кодом `4 (Fragmentation Needed)` нарушает Path MTU Discovery. TCP-соединения будут зависать при попытке отправить пакет, превышающий MTU маршрута.

### Сценарий 8: Тестирование в Docker-окружении

Docker использует собственные цепочки. Для корректной работы вставляйте правила в `DOCKER-USER`.

```bash
# Блокировка трафика к конкретному контейнеру по его внутреннему IP
sudo iptables -I DOCKER-USER -p tcp -d 172.17.0.5 --dport 80 -j DROP

# Блокировка трафика от конкретного контейнера
sudo iptables -I DOCKER-USER -s 172.17.0.5 -p tcp --dport 5432 -j DROP

# Случайная потеря трафика к контейнеру
sudo iptables -I DOCKER-USER -p tcp -d 172.17.0.5 --dport 80 \
    -m statistic --mode random --probability 0.10 -j DROP
```

**Важно:** Правила `DOCKER-USER` сохраняются при `docker network disconnect/connect`, но могут быть перезаписаны при мажорном обновлении Docker. Сохраняйте правила отдельно.

## Диагностика и мониторинг

### Наблюдение за сбоями

Для подтверждения того, что сбои вызваны именно вашими правилами, используйте:

**1. Проверка счетчиков правил:**

```bash
# Для iptables (ищите строки с -j DROP и ненулевым счетчиком pkts)
sudo iptables -L INPUT -v -n
# → pkts  bytes target  prot  opt  in  out  source  destination
# →   42  2520 DROP    tcp   --   *   *    0.0.0.0/0  0.0.0.0/0  tcp dpt:8080

# Для nftables
sudo nft list ruleset -a
# → tcp dport 8080 drop  # handle 5  [counter pkts 42 bytes 2520]
```

**2. Анализ TCP-ретрансмиссий:**

```bash
# Мониторинг счетчиков ретрансмиссий через ss
watch -n 1 'ss -ti | grep -E "retrans|cwnd"'

# Глобальная статистика (ищите TcpRetransSegs)
nstat -az | grep TcpRetrans
# → TcpRetransSegs    123    0.0
```

**3. Захват трафика:**

```bash
# Наблюдение за SYN-пакетами без ответов
sudo tcpdump -ni any 'tcp[tcpflags] & (tcp-syn) != 0' and port 8080

# Наблюдение за всем трафиком на порту (включая повторы)
sudo tcpdump -ni any 'tcp port 8080' -c 50

# Фильтрация только ретрансмиссий (SYN без ответа)
sudo tcpdump -ni any 'tcp port 8080 and (tcp[tcpflags] & tcp-syn != 0) and (tcp[tcpflags] & tcp-ack == 0)' -c 20
```

**4. Проверка состояния соединений:**

```bash
# Все соединения на целевой порт с таймерами
ss -ti dst server:8080
# → State  Recv-Q  Send-Q  Local Address:Port  Peer Address:Port
# → SYN-SENT  0  1  10.0.0.1:45678  10.0.0.2:8080
# →     cubic wscale:7,7 rto:4000 rtt:250/100 ato:40 mss:1448 pmtu:1500
# →     retrans 2/8 rcv_space:14600 tcp_segs_out:5 tcp_segs_in:0
```

## Типичные ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Правило не работает | Правило добавлено в неправильную цепочку или после `ACCEPT`-правила. | Проверьте порядок правил: `sudo iptables -L INPUT -v -n --line-numbers`. Правила обрабатываются последовательно, первое совпадение — последнее. |
| DROP не вызывает таймаут | Существующее `ACCEPT`-правило пропускает пакеты до DROP. | Убедитесь, что DROP-правило стоит **выше** (раньше) ACCEPT-правил для того же трафика. |
| REJECT возвращает ICMP | По умолчанию `REJECT` отправляет `icmp-port-unreachable`. | Используйте `--reject-with tcp-reset` для эмуляции `Connection refused`. |
| Правила пропадают после reboot | Правила не сохранены. | Для iptables: `sudo iptables-save > /etc/iptables/rules.v4`. Для nftables: `sudo nft list ruleset > /etc/nftables.conf`. |
| nftables правило не применяется | Опечатка в синтаксисе или неправильное семейство (`ip` vs `inet`). | Используйте `inet` для IPv4+IPv6: `nft add rule inet filter input ...`. |
| Docker не применяет правило | Правило добавлено в `INPUT` вместо `DOCKER-USER`. | Для Docker-трафика всегда используйте `DOCKER-USER`: `sudo iptables -I DOCKER-USER ...`. |
| Пакеты отбрасываются, но	conntrack не видит | Пакет отброшен до conntrack (в `raw` таблице или `NOTRACK`). | Проверьте `sudo iptables -t raw -L -v -n`. |

## Очистка среды

### Пошаговая очистка

```bash
# 1. Просмотр правил перед удалением (зафиксируйте номера)
sudo iptables -L INPUT -v -n --line-numbers

# 2. Удаление конкретного правила по номеру
sudo iptables -D INPUT 3  # удалить правило с номером 3

# 3. Удаление правила по точному совпадению
sudo iptables -D INPUT -p tcp --dport 8080 -m statistic --mode random --probability 0.15 -j DROP

# 4. Полная очистка цепочки (ОПАСНО: удалит ВСЕ правила INPUT)
sudo iptables -F INPUT

# 5. Сброс счетчиков
sudo iptables -Z
```

### Для nftables

```bash
# Просмотр правил с handle (идентификаторами)
sudo nft list ruleset -a
# → tcp dport 8080 drop  # handle 5

# Удаление по handle
sudo nft delete rule inet filter input handle 5

# Удаление всей таблицы (ОПАСНО)
sudo nft delete table inet filter
```

### Сохранение и восстановление

```bash
# Сохранение текущих правил iptables
sudo iptables-save | sudo tee /etc/iptables/rules.v4
sudo ip6tables-save | sudo tee /etc/iptables/rules.v6

# Восстановление
sudo iptables-restore < /etc/iptables/rules.v4

# Сохранение nftables
sudo nft list ruleset | sudo tee /etc/nftables.conf

# Восстановление nftables
sudo nft -f /etc/nftables.conf
```

### Проверка после очистки

```bash
# Убедитесь, что правила удалены
sudo iptables -L INPUT -v -n
# → Chain INPUT (policy ACCEPT 0 packets, 0 bytes)

# Проверка, что сервис работает без эмуляции
curl -v http://server:8080
# → HTTP/1.1 200 OK  (нормальный ответ)
```

## Best Practices

### Безопасность при тестировании

1. **Используйте метки в комментариях:** Добавляйте `--comment "TEST: emulation timeout"` к каждому правилу для легкого поиска.
2. **Ограничивайте scope:** Всегда указывайте конкретный порт и источник (`-s 10.0.0.0/24`), а не блокируйте весь трафик.
3. **Сохраняйте правила до теста:** Перед эмуляцией сделайте `sudo iptables-save > /tmp/iptables-backup.rules`.
4. **Установите таймер:** Используйте `at` или `timeout` для автоматического удаления правил:
   ```bash
   # Удалить правило через 5 минут
   echo "iptables -D INPUT -p tcp --dport 8080 -j DROP" | at now + 5 minutes
   ```
5. **Тестируйте в staging:** Не выполняйте эмуляцию на production без согласования.

### Согласование с другими инструментами

| Инструмент | Взаимодействие |
| :--- | :--- |
| **tc netem** | Комбинируйте: `tc netem` для задержки/джиттера + `iptables` для DROP/REJECT. Не конфликтуют. |
| **conntrack** | `DROP` не проходит через conntrack (пакет не устанавливает соединение). `REJECT` — да. |
| **fail2ban** | Не используйте одновременно с `iptables`-эмуляцией: fail2ban может заблокировать ваш тестовый IP. |
| **UFW / firewalld** | Управляют iptables напрямую. Для тестов отключайте: `sudo ufw disable` / `sudo systemctl stop firewalld`. |
| **Docker** | Всегда используйте `DOCKER-USER` для правил, затрагивающих контейнеры. |

## Связанные темы

* **[tc netem: Эмуляция сети](./tc_netem.md)** — эмуляция задержек и джиттера на уровне L2.
* **[Основы iptables](../../Settings/tools/iptables_basics.md)** — глубокое погружение в цепочки и таблицы.
* **[Диагностика TCP-соединений](../../../../Networking/Protocols/TCP/connection/tcp_connection_diagnostics.md)** — методы поиска проблем с соединениями.
* **[Chaos Engineering](../../../../Chaos_Engineering/chaos_engineering_overview.md)** — методология системного внедрения отказов.
