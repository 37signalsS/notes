# iptables: основы и практические сценарии

## Определения

**Netfilter** — это встроенный в ядро Linux фреймворк для перехвата и манипуляции сетевыми пакетами. Он обеспечивает фильтрацию, трансляцию адресов (NAT) и модификацию пакетов.

**iptables** — классическая утилита командной строки для управления правилами Netfilter. 
**Статус (2026):** Находится в режиме ограниченной поддержки (Legacy Maintenance Mode). В современных дистрибутивах (Debian 12+, Ubuntu 24.04+, RHEL 9+) заменена на **[nftables](./nftables/architecture_and_concepts.md)**, но продолжает использоваться в устаревших системах и через слой совместимости `iptables-nft`.

**Conntrack (Connection Tracking)** — подсистема Netfilter, отслеживающая состояние сетевых соединений. Она позволяет создавать правила на основе контекста сессии, что делает файрвол «умным» (Stateful).

См. также:
- **[Общие вопросы настройки файрволов](./firewall_common.md)** — сохранение правил, выбор DROP против REJECT.
- **[nftables: архитектура](./nftables/architecture_and_concepts.md)** — современная замена iptables.
- **[Интеграция Docker с iptables](../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — глубокий разбор цепочек Docker.

## Предварительные требования

### Ядро и модули

iptables требует поддержки Netfilter в ядре. Минимальная версия для production — 3.10+ (современные дистрибутивы используют 5.x/6.x). Проверка:

```bash
# Версия ядра
uname -r

# Проверка загруженных модулей Netfilter
lsmod | grep -E "nf_conntrack|iptable_"
# → nf_conntrack
# → nf_conntrack_netlink
# → iptable_filter
# → iptable_nat
# → nf_nat
# → nf_nat_masquerade

# Если модули не загружены
sudo modprobe nf_conntrack
sudo modprobe iptable_filter
sudo modprobe iptable_nat
```

### Программное обеспечение

- **`iptables`** — утилита управления правилами.
- **`ip6tables`** — аналогичная утилита для IPv6.
- **`conntrack`** — инструмент диагностики подсистемы отслеживания соединений.
- **`iptables-save` / `iptables-restore`** — сериализация и восстановление правил.

### Конфигурация окружения

```bash
# Лимит таблицы отслеживания соединений
sysctl net.netfilter.nf_conntrack_max
# → 262144 (значение по умолчанию может быть недостаточным под высоконагруженный сервис)

# Текущее количество отслеживаемых соединений
sysctl net.netfilter.nf_conntrack_count
```

### Проверка активного бэкенда

```bash
update-alternatives --display iptables
# → iptables - auto mode
# →   link best version is /usr/sbin/iptables-nft
# →   link currently points to /usr/sbin/iptables-nft
```

## Основные концепции

### Структура: Таблицы и цепочки

iptables организует правила в **таблицы** (по назначению) и **цепочки** (по этапу прохождения пакета). Пакет проходит через таблицы и цепочки в строго определенном порядке.

**Основные таблицы:**
- `filter`: Основная таблица для принятия решений о допуске пакета (`ACCEPT`, `DROP`, `REJECT`).
- `nat`: Используется для трансляции адресов. Включает `PREROUTING` (для DNAT), `POSTROUTING` (для SNAT/MASQUERADE) и `OUTPUT`.
- `mangle`: Для модификации заголовков пакетов (изменение TTL, TOS, маркировка пакетов для маршрутизации).
- `raw`: Используется для исключения пакетов из отслеживания состояний (`NOTRACK`).

**Стандартные цепочки:**
- `INPUT`: Пакеты, предназначенные самому хосту.
- `OUTPUT`: Пакеты, генерируемые локальными процессами.
- `FORWARD`: Пакеты, проходящие сквозь хост (роутинг).
- `PREROUTING`: Пакеты, только что пришедшие на сетевой интерфейс, до принятия решения о маршрутизации.
- `POSTROUTING`: Пакеты, покидающие сетевой интерфейс, после маршрутизации.

### Анатомия правила

Правило состоит из **критериев** (match) и **цели** (target). Пакет проверяется правилами цепочки последовательно.

**Основные цели (Targets):**
- `ACCEPT`: Пропустить пакет.
- `DROP`: Молча отбросить (клиент ждет таймаута).
- `REJECT`: Отклонить и отправить уведомление (ICMP Unreachable).
- `LOG`: Записать в системный журнал и продолжить проверку следующими правилами.
- `MASQUERADE`: Динамический SNAT (для внешних интерфейсов с динамическим IP).
- `REDIRECT`: Перенаправление пакета на локальный порт (проксирование).
- `NOTRACK` (raw): Исключить пакет из отслеживания состояний. Используется в таблице `raw`.

### Состояния соединений (Conntrack)

Подсистема отслеживания соединений позволяет применять правила на основе контекста сессии. Основные состояния:

| Состояние | Описание | Где возникает |
| :--- | :--- | :--- |
| `NEW` | Первый пакет нового соединения (SYN для TCP, первый запрос для UDP) | Правила с `-m conntrack --ctstate NEW` |
| `ESTABLISHED` | Соединение активно: был двусторонний обмен пакетами | Правила с `ESTABLISHED,RELATED` |
| `RELATED` | Пакет относится к уже существующему соединению (например, FTP data connection, ICMP error для TCP) | Часто разрешают вместе с ESTABLISHED |
| `INVALID` | Пакет не может быть сопоставлен ни с одним известным соединением (битый фрагмент, неверный чексумма) | Лучше явно отбрасывать `DROP` |
| `UNTRACKED` | Пакет исключен из отслеживания через `NOTRACK` (таблица `raw`) | Используется для производительности |

**Важно:** ICMP-сообщения (кроме ICMP-error, связанных с TCP/UDP) не отслеживаются как stateful. Для разрешения ping внутри `ESTABLISHED,RELATED` недостаточно — требуется отдельное правило `--icmp-type echo-request`.

### DROP vs REJECT: разница поведения

Цели `DROP` и `REJECT` обе блокируют пакет, но клиент получает абсолютно разный результат — это критично для диагностики и влияет на поведение приложения.

**DROP** — пакет просто выбрасывается, без отправки какого-либо ответа:

```bash
iptables -A INPUT -p tcp --dport 22 -j DROP
```

Клиент отправляет SYN, но в ответ ничего не приходит:

```
client → SYN → server
client ← ... ← timeout
```

TCP-стек клиента будет повторять попытки (с ретрансмиссиями) до истечения таймаута (по умолчанию ~20 с для `connect()`). На уровне приложения это выглядит как **«сервер молчит»** / `Connection timed out`.

**REJECT** — блокирует соединение и отправляет ответ, позволяя клиенту сразу понять причину:

```bash
iptables -A INPUT -p tcp --dport 22 -j REJECT --reject-with tcp-reset
```

Теперь клиент получает RST и сразу понимает: соединение отвергнуто:

```
client → SYN → server
client ← RST ← server
```

Приложение увидит **«сервер отказал»** / `Connection refused` — ошибка возникает мгновенно, без ожидания таймаута.

**Почему это важно для диагностики:** если всё дропать, ошибка часто выглядит как timeout, хотя проблема на самом деле в firewall. Сканирование (nmap) при `DROP` показывает порт как `filtered`, при `REJECT` — как `closed`.

**Параметры `--reject-with`:**

| Значение | Отправляемый ответ | Применение |
| :--- | :--- | :--- |
| (по умолчанию) | ICMP `port-unreachable` | TCP и UDP, стандартное поведение |
| `tcp-reset` | TCP RST | Требуется для TCP, чтобы избежать long timeout на клиенте |
| `icmp-host-prohibited` | ICMP Host Prohibited | Скрытие хоста от сканеров |
| `icmp-net-prohibited` | ICMP Net Prohibited | Блокировка по сети |
| `icmp-admin-prohibited` | ICMP Admin Prohibited | Явное указание на администраторную блокировку (на ядрах без поддержки → plain DROP) |

Для ICMP-трафика `REJECT` отправляет ICMP unreachable вместо TCP RST (по умолчанию `icmp-port-unreachable`).

**Когда что использовать:**
- **DROP** — внешние интерфейсы (WAN), DDoS-защита, скрытие конфигурации от сканеров. Меньше трафика и нагрузки на хост (не отправляется доп. пакет).
- **REJECT** — внутренние сети (LAN), отладка, services, где важно быстро получить ошибку. Ускоряет диагностику на клиенте.

**Ограничения REJECT:** в ядре есть `icmp_ratelimit` (`/proc/sys/net/ipv4/icmp_ratelimit`) — при превышении лимита ICMP-ошибки перестают отправляться, и поведение сближается с DROP. Также REJECT не отправляет ответ, если отбрасываемый пакет — сам по себе ICMP-ошибка, невыделенный фрагмент или превышен лимит ошибок на одного получателя.

## Практические сценарии

### 1. Базовая защита узла (Stateful)

```bash
# 1. Разрешить трафик для уже установленных соединений
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 2. Разрешить loopback-интерфейс
sudo iptables -A INPUT -i lo -j ACCEPT

# 3. Разрешить SSH (порт 22) и стандартный веб (80, 443)
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT

# 4. Установка политик по умолчанию (сначала разрешите SSH, чтобы не потерять доступ!)
sudo iptables -P INPUT DROP
sudo iptables -P FORWARD DROP
sudo iptables -P OUTPUT ACCEPT
```

### 2. Трансляция адресов (NAT)

```bash
# Настройка Masquerading для выхода локальной сети в интернет через eth0
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

# Проброс порта (DNAT): внешний порт 8080 -> внутренний IP 192.168.1.10:80
sudo iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 192.168.1.10:80

# Перенаправление трафика с порта 80 на локальный 3128 (Transparent Proxy)
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-ports 3128
```

### 3. Защита от перебора (Module Recent)

Модуль `recent` позволяет создавать динамические списки IP-адресов прямо в памяти файрвола.

```bash
# Блокировка IP на 60 секунд, если совершено более 3 попыток подключения к SSH за минуту
sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -m recent --set --name SSH_BRUTE
sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -m recent --update --seconds 60 --hitcount 4 --name SSH_BRUTE -j DROP
```

### 4. Ограничение скорости (Module Limit)

Защита от DoS-атак и флуда.

```bash
# Ограничение входящих ICMP (ping) - 1 пакет в секунду
sudo iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 1/s --limit-burst 5 -j ACCEPT
```

### 5. Оптимизация TCP (Mangle)

Исправление проблем с MTU в туннелях (VPN, GRE).

```bash
# Корректировка MSS для всех пересылаемых пакетов
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1360
```

### 6. Базовый файрвол для IPv6

IPv6 требует отдельной таблицы правил. Критично разрешить ICMPv6 (Neighbor Discovery, Packet Too Big), иначе работа IPv6 нарушается.

```bash
# Разрешить loopback
sudo ip6tables -A INPUT -i lo -j ACCEPT

# Разрешить установленные соединения
sudo ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Разрешить критический ICMPv6
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type echo-request -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type packet-too-big -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type neighbor-solicitation -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type neighbor-advertisement -j ACCEPT

# Разрешить SSH и HTTPS
sudo ip6tables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo ip6tables -A INPUT -p tcp --dport 443 -j ACCEPT

# Политика по умолчанию
sudo ip6tables -P INPUT DROP
sudo ip6tables -P FORWARD DROP
sudo ip6tables -P OUTPUT ACCEPT
```

### 7. Логирование с rate-limit

Цель `LOG` записывает пакет в системный журнал (`/var/log/kern.log`, `journalctl -k`). Без `limit` журнал может быть переполнен при атаке.

```bash
# Логирование отброшенных пакетов, не более 10 в минуту
sudo iptables -A INPUT -m limit --limit 10/min --limit-burst 20 -j LOG --log-prefix "IPTABLES_DROP: " --log-level 4

# Отбрасываемые пакеты (правило после LOG)
sudo iptables -A INPUT -j DROP
```

**Примечание:** Для асинхронного логирования в файл используйте `ulogd` — это снижает нагрузку на ядро при высокоскоростном трафике.

### 8. Ограничение по источнику (hashlimit)

Модуль `hashlimit` ограничивает количество соединений с каждого уникального IP-адреса, в отличие от `limit` (общий лимит на интерфейс).

```bash
# Не более 10 новых соединений в секунду с одного IP к порту 80
sudo iptables -A INPUT -p tcp --dport 80 -m conntrack --ctstate NEW -m hashlimit \
  --hashlimit-name http --hashlimit-above 10/sec --hashlimit-mode srcip -j DROP
```

## Диагностика и отладка

```bash
# Просмотр всех правил с номерами, счетчиками и детализацией
sudo iptables -nvL --line-numbers

# Просмотр конкретной таблицы (например, nat)
sudo iptables -t nat -nvL

# Сериализация всех правил в файл (бэкап)
sudo iptables-save > /root/iptables-backup-$(date +%F).rules

# Мониторинг отброшенных пакетов (если включен LOG)
sudo journalctl -kf | grep "IN="

# Анализ активных соединений через conntrack
sudo conntrack -L
# → tcp 6 431999 ESTABLISHED src=192.168.1.10 dst=8.8.8.8 sport=54321 dport=443 ...

# Проверка текущего заполнения таблицы conntrack
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → 45000 262144

# Поиск конкретного соединения
sudo conntrack -L -d 203.0.113.1

# Удаление конкретного соединения (при необходимости)
sudo conntrack -D -d 203.0.113.1 --dport 443

# Сопоставление правил с активными сокетами
sudo ss -tulnp | grep :80
```

### Валидация перед применением

```bash
# 1. Сохраните текущие правила
sudo iptables-save > /root/iptables-previous.rules

# 2. Примените правила через iptables-restore (лучше для атомарности)
sudo iptables-restore < /tmp/new-rules.rules

# 3. Проверьте результат
sudo iptables -nvL --line-numbers

# 4. При проблемах — восстановите
sudo iptables-restore < /root/iptables-previous.rules
```

## Дополнительная информация

### NAT: Production-паттерны

Таблица `nat` используется для трансляции адресов. Три основных типа:

| Тип | Цепочка | Назначение | Пример |
|:---|:---|:---|:---|
| **SNAT** | `POSTROUTING` | Замена исходного IP на IP сервера | Выход в интернет из приватной сети |
| **DNAT** | `PREROUTING` | Замена IP назначения | Проброс порта, балансировка |
| **MASQUERADE** | `POSTROUTING` | SNAT с динамическим IP | Интернет через PPPoE, VPN |

**Сценарий 1: Проброс порта (DNAT)**
```bash
# Внешний трафик на порту 8080 → внутренний сервер 10.0.0.10:80
sudo iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 10.0.0.10:80
sudo iptables -A FORWARD -p tcp -d 10.0.0.10 --dport 80 -j ACCEPT

# Проверка
sudo iptables -t nat -L PREROUTING -n -v
```

**Сценарий 2: Маскарадинг (MASQUERADE) для выхода в интернет**
```bash
# Все из 10.0.0.0/24 выходят через eth0 с IP хоста
sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o eth0 -j MASQUERADE

# Включить forwarding
sysctl -w net.ipv4.ip_forward=1
```

**Сценарий 3: Round-robin балансировка через DNAT**
```bash
# Трафик на VIP распределяется по 3 бэкендам (маскарадинг скрывает обратный путь)
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -m statistic --mode nth --every 3 --packet 0 -j DNAT --to-destination 10.0.0.1:80
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -m statistic --mode nth --every 2 --packet 0 -j DNAT --to-destination 10.0.0.2:80
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j DNAT --to-destination 10.0.0.3:80
```

**Сценарий 4: Hairpin NAT (loopback DNAT)**
```bash
# Доступ к VIP изнутри сети (если DNAT работает только снаружи)
sudo iptables -t nat -A PREROUTING -d 192.168.1.100 -p tcp --dport 80 -j DNAT --to-destination 10.0.0.10:80
sudo iptables -t nat -A POSTROUTING -d 10.0.0.10 -p tcp --dport 80 -j MASQUERADE
```

### Rate Limiting и flood protection

```bash
# Limit: общий лимит на интерфейс (100 пакетов/сек, burst 200)
sudo iptables -A INPUT -m limit --limit 100/sec --limit-burst 200 -j ACCEPT

# Hashlimit: лимит с каждого IP (10 новых TCP/сек на порт 80)
sudo iptables -A INPUT -p tcp --dport 80 -m conntrack --ctstate NEW \
  -m hashlimit --hashlimit-name http_flood \
  --hashlimit-above 10/sec --hashlimit-mode srcip \
  --hashlimit-burst 50 --hashlimit-htable-expire 30000 \
  -j DROP

# SSH brute-force protection (с модулем recent)
sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW \
  -m recent --set --name SSH
sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW \
  -m recent --update --seconds 60 --hitcount 4 --name SSH -j DROP
```

### Пользовательские цепочки (User-defined chains)

Для структурирования сложных наборов правил рекомендуется создавать свои цепочки.
```bash
# Создание цепочки для фильтрации трафика конкретного приложения
sudo iptables -N APP_FILTER
sudo iptables -A INPUT -p tcp --dport 8080 -j APP_FILTER
sudo iptables -A APP_FILTER -s 10.0.0.0/24 -j ACCEPT
sudo iptables -A APP_FILTER -j DROP
```

### Взаимодействие с Docker

Docker автоматически создаёт правила в таблицах `nat` и `filter`. Для пользовательской фильтрации трафика контейнеров используйте цепочку **`DOCKER-USER`** — она обрабатывается перед стандартными цепочками `DOCKER`.

```bash
# Разрешить только доверенные подсети к опубликованным портам
sudo iptables -A DOCKER-USER -i eth0 -s 10.0.0.0/8 -j ACCEPT
sudo iptables -A DOCKER-USER -i eth0 -j DROP

# Блокировка исходящего трафика из bridge-сети (кроме DNS)
sudo iptables -I DOCKER-USER -i br-+ -o eth0 -j DROP
sudo iptables -I DOCKER-USER -i br-+ -o eth0 -p udp --dport 53 -j ACCEPT
sudo iptables -I DOCKER-USER -i br-+ -o eth0 -p tcp --dport 53 -j ACCEPT
```

**Важно:** Порядок правил в `DOCKER-USER` имеет значение — первое совпадение применяется. Для детального анализа используйте `iptables-save | grep DOCKER`.

### Персистентность и восстановление

Правила iptables (в режиме legacy) хранятся в памяти и сбрасываются при перезагрузке.

**Debian/Ubuntu:**
```bash
sudo apt install iptables-persistent
# Правила автоматически загружаются из /etc/iptables/rules.v4 и rules.v6
sudo netfilter-persistent save
```

**RHEL/Rocky/Alma:**
```bash
sudo dnf install iptables-services
sudo systemctl enable --now iptables
sudo service iptables save
# Правила хранятся в /etc/sysconfig/iptables
```

**Универсальный метод (systemd unit):**
```ini
# /etc/systemd/system/iptables-restore.service
[Unit]
Description=Restore iptables rules
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/iptables-restore /etc/iptables.rules
ExecReload=/usr/sbin/iptables-restore /etc/iptables.rules
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now iptables-restore
```

**Внимание:** При использовании `iptables-nft` бэкенда персистентность может работать некорректно. В этом случае рассмотрите переход на `nftables`.

### Пограничные случаи и ограничения

1. **Атомарность скриптов:** iptables применяет каждую команду атомарно, но скрипт с `&&` при сбое в середине частично меняет конфигурацию. Используйте `iptables-restore < <(iptables-save && ...)` или применяйте правила из файла одним вызовом.
2. **IPv6 и ICMPv6:** Без правил для `icmpv6` работа IPv6 может прекратиться. См. сценарий 6.
3. **NOTRACK и производительность:** Исключение трафика из conntrack (`-t raw -j NOTRACK`) снижает нагрузку на CPU, но отключает stateful-защиту для этого трафика. Используйте только для хорошо известных потоков (балансировщики).
4. **DOCKER-USER и порядок:** Правила в `DOCKER-USER` должны быть добавлены до правил Docker. Проверяйте порядок через `iptables-save | grep -A1 DOCKER-USER`.
5. **Асимметричная маршрутизация:** Если `rp_filter=1` (strict), пакеты с асимметричными маршрутами отбрасываются. Для gateway-хостов используйте `rp_filter=2` (loose) или `0` (off).
6. **MTU и TCPMSS:** В туннелях (IPsec, WireGuard) всегда корректируйте MSS, иначе TCP-соединения будут зависать на больших пакетах.
7. **ICMP-error и conntrack:** ICMP-error сообщения автоматически сопоставляются с соединением через conntrack. Блокировка ICMP-error (`icmp destination-unreachable`) может ломать TCP-соединения.
8. **Совместный iptables и nftables:** При использовании `iptables-nft` правила видны в `nft list ruleset`. Не редактируйте их напрямую через `nft` — это может привести к конфликтам.

### Best practices

1. **Default deny:** Устанавливайте политики `INPUT DROP` и `FORWARD DROP` после настройки правил для SSH.
2. **Stateful первым:** Разрешайте `ESTABLISHED,RELATED` в самом начале цепочки `INPUT`.
3. **Однострочные правила:** Избегайте длинных цепочек `&&` в shell — используйте `iptables-restore`.
4. **Комментируйте:** Используйте `--comment "description"` для каждого правила. Это упрощает аудит.
5. **Версионирование:** Храните правила в git (`iptables-save > rules.v4`) и применяйте через CI/CD.
6. **Ограничивайте inbound, разрешайте outbound:** Политика `OUTPUT ACCEPT` уязвима для скомпрометированных сервисов. В high-security средах разрешайте только необходимые порты.
7. **Тестируйте в staging:** Всегда проверяйте правила на тестовом хосте перед применением в production.
8. **Не блокируйте ICMP полностью:** ICMP необходим для PMTUD (`fragmentation-needed`), traceroute и диагностики.
9. **Отключайте неиспользуемые helpers:** ALG-помощники (ftp, sip, h323) могут создавать дыры в conntrack. Отключайте их через `/etc/modprobe.d/`.
10. **Мониторьте счетчики:** Регулярно проверяйте счетчики правил (`iptables -L -v -n`). Рост `DROP` счетчика указывает на аномалии.

### Очистка и откат

```bash
# Безопасная очистка: восстановить политики ACCEPT перед flush
sudo iptables -P INPUT ACCEPT
sudo iptables -P FORWARD ACCEPT
sudo iptables -P OUTPUT ACCEPT
sudo iptables -t nat -F
sudo iptables -t mangle -F
sudo iptables -F
sudo iptables -X

# Для IPv6
sudo ip6tables -P INPUT ACCEPT
sudo ip6tables -F
sudo ip6tables -X

# Удаление пользовательских цепочек
sudo iptables -X APP_FILTER
```

**Переключение на iptables-legacy (если требуется):**
```bash
sudo update-alternatives --set iptables /usr/sbin/iptables-legacy
sudo update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy
```

### Полезные ссылки

- **[Общие вопросы настройки файрволов](./firewall_common.md):** сохранение правил, выбор DROP против REJECT, conntrack.
- **[nftables — архитектура и концепции](./nftables/architecture_and_concepts.md):** современный стандарт настройки.
- **[Политики сетевой фильтрации Docker](../../../../Docker/Docker_network/docker_network_policies.md):** DOCKER-USER и изоляция контейнеров.
