# nftables — практические сценарии настройки

## Определения

**NAT (Network Address Translation)** — механизм преобразования IP-адресов и портов в заголовках пакетов. В nftables реализуется через типы `snat`, `dnat`, `masquerade` и `redirect`.

**Masquerading** — динамический вид SNAT, автоматически подставляющий IP-адрес исходящего интерфейса. Идеален для каналов с DHCP (PPPoE, LTE).

**Сеты (Sets)** — именованные наборы элементов (адреса, порты, интерфейсы), позволяющие обрабатывать тысячи объектов за один проход за счет использования хэш-таблиц.

**Мапы (Maps)** — структуры «ключ-значение», позволяющие сопоставлять данные (например, IP-адрес источника → вердикт или IP → порт).

**Flowtable** — технология Fastpath в ядре Linux, позволяющая передавать пакеты установленных соединений (L4) напрямую между сетевыми интерфейсами, минуя классический стек фильтрации, что снижает нагрузку на CPU.

## Основные концепции

Конфигурация nftables полностью модульная. Для построения эффективного файрвола необходимо понимать иерархию объектов:

1.  **Таблицы (Tables):** контейнеры для цепочек, привязанные к семейству протоколов (`ip`, `ip6`, `inet`, `bridge`, `netdev`).
2.  **Цепочки (Chains):** группы правил, привязанные к системным хукам (точки прохождения пакета).
3.  **Выражения (Expressions):** условия сопоставления данных пакета.
4.  **Действия (Verdicts):** решение по пакету (`accept`, `drop`, `reject`, `jump`, `goto`).

### Атомарность применений

Все изменения правил через `nft -f <файл>` применяются атомарно. Либо весь набор правил загружается успешно, либо ни одно изменение не вступает в силу. Это исключает «разрывные» состояния, когда часть правил применена, а часть — нет.

### Отслеживание соединений (conntrack)

Механизм `conntrack` отслеживает состояния TCP/UDP соединений. Жизненный цикл:
- `new` — первый пакет нового соединения.
- `established` — соединение установлено (получен ответ).
- `related` — пакет связан с существующим соединением (ICMP error, FTP data).
- `invalid` — пакет не принадлежит ни одному известному соединению.

Правило `ct state established,related accept` размещается в верхней части цепочки для минимизации нагрузки.

### Встроенные счетчики

Каждое правило nftables имеет встроенные счетчики пакетов и байт. Просмотр:
```bash
nft list ruleset -a
# → tcp dport 22 accept # packets 1542 bytes 98720
```

### Трассировка пакетов (nftrace)

Для отладки можно включить трассировку на отдельное правило:
```bash
nft add rule inet filter input ether saddr 00:11:22:33:44:55 meta nftrace set 1
nft monitor trace
```

## Предварительные требования

### Аппаратные требования

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| ** NIC** | 1 порт | 2+ порта для маршрутизации/NAT |
| ** CPU** | 2 ядра | 4+ ядра при нагрузке >1Gbps |
| ** RAM** | 512 MB | 2 GB+ для больших таблиц conntrack |

### Программные требования

| Компонент | Версия / Требование |
| :--- | :--- |
| **Ядро Linux** | 5.3+ (нативный `bridge` conntrack), 5.15+ рекомендуется |
| **nftables** | 1.0.0+ |
| **iproute2** | 5.x+ |
| **conntrack-tools** | для диагностики (`conntrack`, `conntrackd`) |
| **Права** | root (sudo) |
| **Служба** | `nftables` (systemd) для персистентности |

### Проверка окружения

```bash
# Версия ядра
uname -r
# → 5.15.0-78-generic

# Наличие nftables
which nft && nft --version
# → nft v1.0.9

# Проверка загруженных модулей ядра
lsmod | grep -E 'nf_conntrack|nf_defrag_ipv4|nf_nat'
# → nf_conntrack          163840  1 bridge
# → nf_nat                245760  1 nf_conntrack

# Размер таблицы conntrack
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 262144
```

## Пошаговая установка

### Шаг 1: Создание таблиц и цепочек

```bash
# Создание таблицы filter
sudo nft add table inet filter

# Создание базовых цепочек
sudo nft add chain inet filter input { type filter hook input priority 0; policy drop; }
sudo nft add chain inet filter forward { type filter hook forward priority 0; policy drop; }
sudo nft add chain inet filter output { type filter hook output priority 0; policy accept; }

# Создание таблицы nat (для DNAT/SNAT)
sudo nft add table ip nat
sudo nft add chain ip nat prerouting { type nat hook prerouting priority -100; policy accept; }
sudo nft add chain ip nat postrouting { type nat hook postrouting priority 100; policy accept; }
```

### Шаг 2: Добавление базовых правил

```bash
# Разрешить loopback
sudo nft add rule inet filter input iifname "lo" accept

# Разрешить установленные соединения
sudo nft add rule inet filter input ct state established,related accept

# Отбрасывать некорректные пакеты
sudo nft add rule inet filter input ct state invalid drop

# Разрешить SSH
sudo nft add rule inet filter input tcp dport 22 accept
```

### Шаг 3: Включение персистентности

```bash
# Сохранение правил
sudo nft list ruleset > /etc/nftables.conf

# Включение systemd-сервиса
sudo systemctl enable --now nftables
```

## Практические сценарии

### 1. Эталонный Stateful-файрвол (IPv4 + IPv6)

Базовая защита сервера, использующая семейство `inet` для атомарного управления обоими стеками.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Разрешить установленные и связанные соединения
        ct state established,related accept
        
        # 2. Сброс некорректных пакетов (INVALID)
        ct state invalid drop

        # 3. Разрешить Loopback
        iif "lo" accept

        # 4. Разрешить ICMP и ICMPv6 (необходимы для диагностики и IPv6)
        icmp type echo-request limit rate 5/second accept
        icmpv6 type { 
            destination-unreachable, packet-too-big, time-exceeded, 
            parameter-problem, echo-request, echo-reply, 
            nd-neighbor-solicit, nd-neighbor-advert, 
            nd-router-solicit, nd-router-advert 
        } accept

        # 5. Открытие портов сервисов
        tcp dport { 22, 80, 443 } accept
    }
}
```

**Валидация:**
```bash
# Проверка правил
sudo nft list ruleset

# Проверка счетчиков
sudo nft list chain inet filter input
# → tcp dport 22 accept # packets 1542 bytes 98720
```

### 2. Защита от DDoS на раннем этапе (Netdev Ingress)

Семейство `netdev` позволяет отбрасывать пакеты сразу после их получения драйвером сетевой карты, что значительно экономит ресурсы CPU при атаках.

```bash
table netdev filter {
    chain ingress {
        type filter hook ingress device "eth0" priority -500;
        
        # Сброс фрагментированных пакетов
        ip frag-off & 0x3fff != 0 drop

        # Лимит на общее количество входящих пакетов
        limit rate over 50000/second drop
    }
}
```

**Валидация:**
```bash
# Проверка счетчиков
sudo nft list chain netdev filter ingress

# Проверка дропнутого трафика
watch -n 1 'sudo nft list chain netdev filter ingress'
```

### 3. Балансировка нагрузки (Load Balancing)

Nftables поддерживает нативную балансировку трафика без использования сторонних инструментов.

```bash
table ip nat {
    chain prerouting {
        type nat hook prerouting priority -100; policy accept;
        
        # Балансировка HTTP трафика между двумя серверами (Round-robin)
        tcp dport 80 dnat to numgen inc mod 2 map { 0 : 192.168.1.10, 1 : 192.168.1.11 }
    }
}
```

**Валидация:**
```bash
# Проверка DNAT-правила
sudo nft list chain ip nat prerouting

# Проверка conntrack
sudo conntrack -L -p tcp --dport 80
```

### 4. Поддержка HA-кластеров (VRRP/Keepalived)

При использовании Keepalived необходимо разрешить специфичный VRRP трафик (протокол 112).

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        
        ct state established,related accept
        iif "lo" accept
        tcp dport 22 accept

        # Разрешить VRRP пакеты от партнеров по кластеру
        ip protocol vrrp accept
        # Для IPv6
        ip6 nexthdr vrrp accept
    }
}
```

**Валидация:**
```bash
# Проверка, что VRRP-пакеты проходят
sudo tcpdump -i eth0 proto 112 -n
# → Должны видны пакеты между VIP-адресами
```

### 5. Сложная фильтрация через конкатенацию (Concatenation)

Объединение нескольких критериев в один сет для повышения производительности.

```bash
table inet filter {
    # Сет, содержащий пары IP-адрес и порт назначения
    set whitelist {
        type ipv4_addr . inet_service
        elements = { 1.2.3.4 . 22, 5.6.7.8 . 443 }
    }

    chain input {
        # Разрешить только если IP и порт совпадают с парой в сете
        ip saddr . tcp dport @whitelist accept
    }
}
```

**Валидация:**
```bash
# Проверка сета
sudo nft list set inet filter whitelist
# → elements = { 1.2.3.4 . 22, 5.6.7.8 . 443 }
```

### 6. Проброс портов (DNAT) и Маскарадинг

```bash
table ip nat {
    chain prerouting {
        type nat hook prerouting priority -100; policy accept;
        
        # Внешний порт 8080 -> Внутренний IP 10.0.0.5:80
        tcp dport 8080 dnat to 10.0.0.5:80
    }

    chain postrouting {
        type nat hook postrouting priority 100; policy accept;
        
        # Маскарадинг для трафика, уходящего через eth0
        oifname "eth0" masquerade
    }
}
```

**Валидация:**
```bash
# Проверка DNAT
sudo conntrack -L -p tcp --dport 80
# → Должна показать трансляцию dst: 10.0.0.5:80

# Проверка MASQUERADE
sudo nft list chain ip nat postrouting
```

### 7. Безопасная настройка nftables на удалённом сервере

Настройка файрвола на удалённой машине через SSH — рискованная операция. Одно неверное движение, и доступ потерян.

#### Почему nftables и при чём тут iptables

Nftables — современный фреймворк пакетной фильтрации, доступный начиная с ядра Linux 3.13. Он предлагает:
*   Единый синтаксис для IPv4, IPv6, ARP и других семейств протоколов.
*   Атомарную загрузку правил — замена всего набора правил одной транзакцией.
*   Более читаемый синтаксис и удобные наборы (sets).

Важный нюанс: во многих дистрибутивах утилита `iptables` является прослойкой, транслирующей команды в nftables. Убедиться в этом можно так:

```bash
nft list ruleset
# → Если есть таблицы с предупреждением `managed by iptables-nft`,
#   вы уже работаете поверх nftables.
```

#### Политика DROP и порядок правил

Самый частый способ потерять доступ — установить политику `drop` для цепочки `input` до того, как было добавлено правило, разрешающее SSH.

Опасный сценарий:

```bash
# Применяем цепочку с policy drop — ВСЕ соединения обрываются
nft add chain inet filter input { type filter hook input priority 0; policy drop; }
```

В отличие от политики `accept` (разрешает всё, что не запрещено), политика `drop` запрещает всё, что не разрешено явно.

**Безопасный подход:** сначала добавить правило для SSH, и только потом устанавливать политику `drop`.

#### Метод 1: Атомарная загрузка правил

Главное преимущество nftables — возможность атомарной замены всего набора правил одной командой. В рамках одной транзакции `flush ruleset` и `policy drop` срабатывают одновременно, поэтому разрыва соединения не происходит, если правило для SSH уже находится в том же файле.

```bash
cat > /etc/nftables.conf <<'EOF'
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешаем loopback
        iif lo accept

        # Разрешаем установленные соединения (критично для сохранения SSH!)
        ct state established,related accept

        # Отбрасываем некорректные пакеты
        ct state invalid drop

        # Разрешаем SSH
        tcp dport 22 accept

        # Разрешаем HTTP/HTTPS при необходимости
        tcp dport { 80, 443 } accept

        # Разрешаем ICMP (ping)
        ip protocol icmp accept
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
EOF

# Применяем атомарно
sudo nft -f /etc/nftables.conf
```

После успешной загрузки проверьте, что SSH-соединение всё ещё живо. Если в конфигурации синтаксическая ошибка, nftables не применит её.

#### Метод 2: Автоматический откат при потере соединения

Атомарная загрузка не гарантирует отсутствие ошибок (например, неверный номер порта SSH или забытый `ct state established,related`). Для защиты используется автоматический откат.

**Вариант А: Таймер с подтверждением**

Идея: после применения правил запускается таймер. Если вы не подтвердите, что соединение работает, правила автоматически откатываются.

```bash
#!/bin/bash
RULES_FILE="/etc/nftables.conf"
BACKUP_FILE="/tmp/nftables-backup-$(date +%s).conf"

# 1. Сохраняем текущие правила
nft list ruleset > "$BACKUP_FILE"

# 2. Применяем новые правила
nft -f "$RULES_FILE"

# 3. Запускаем таймер отката (5 минут)
(
    sleep 300
    echo "Timeout! Rolling back..."
    nft flush ruleset
    nft -f "$BACKUP_FILE"
) &
ROLLBACK_PID=$!

# 4. Ждём подтверждения от администратора
echo "Does SSH still work? (yes/no)"
read answer

if [[ "$answer" == "yes" ]]; then
    kill "$ROLLBACK_PID" 2>/dev/null
    echo "Configuration confirmed."
else
    echo "Rolling back..."
    nft flush ruleset
    nft -f "$BACKUP_FILE"
fi
```

**Вариант Б: Специализированные утилиты**

Существуют инструменты, автоматизирующие процесс безопасного применения:

*   `nftables-apply` — утилита для Fedora, RHEL, Ubuntu и других дистрибутивов:

```bash
# Установка (Ubuntu)
sudo add-apt-repository ppa:setenforce1/nftables-apply
sudo apt install nftables-apply

# Применение с таймаутом 15 секунд
sudo nftables-apply -s /etc/nftables/candidate.nft -t 15
```

Утилита применяет правила, ожидает подтверждения и автоматически откатывает изменения при потере соединения.

#### Особый случай: проблемы с conntrack

При первой загрузке правил SSH-соединение может оборваться, хотя правила корректны. Причина: conntrack не был активен до загрузки правил, и для текущего SSH-соединения не было записи в таблице состояний, поэтому `ct state established,related accept` не сработало.

Решение — добавить на этапе загрузки системы правило, активирующее conntrack заранее:

```bash
table inet filter {
    chain input {
        type filter hook input priority filter;
        ct state { established, related } accept
    }
}
```

#### Проверка существующих правил

Прежде чем вносить изменения, всегда полезно посмотреть, что уже настроено:

```bash
# Весь текущий набор правил
sudo nft list ruleset

# Конкретная таблица
sudo nft list table inet filter

# Конкретная цепочка
sudo nft list chain inet filter input
```

Если вы переходите с iptables, можно преобразовать существующие правила в формат nftables:

```bash
iptables-translate -A INPUT -p tcp --dport 22 -j ACCEPT
# → nft add rule ip filter INPUT tcp dport 22 accept
```

Подробнее о миграции: [nftables — миграция и справочник синтаксиса](./migration_and_reference.md).

#### Чего делать НЕ стоит

*   Не выполняйте команды по одной через SSH без страховки — между `nft add chain... policy drop` и добавлением разрешающего правила.
*   Не используйте `nft flush ruleset` в интерактивном режиме на удалённом сервере — если у вас не было явного разрешающего правила для SSH, вы останетесь без защиты (и без доступа). Вместо этого используйте `nft -f` с полным набором правил.
*   Не забывайте про правило для установленных соединений — без `ct state established,related accept` даже правильно настроенный SSH может оборваться, если таблица conntrack была очищена.

#### Чек-лист безопасной настройки

1.  Подготовьте файл правил с `flush ruleset`, правилом для SSH и политикой `drop`.
2.  Проверьте синтаксис: `sudo nft --check --file /etc/nftables.conf`.
3.  Примените атомарно: `sudo nft -f /etc/nftables.conf`.
4.  Сохраните правила для загрузки при старте: `sudo nft list ruleset | sudo tee /etc/nftables.conf`.
5.  Настройте автоматический запуск: `sudo systemctl enable --now nftables`.
6.  Оставьте себе запасное окно — не закрывайте текущую SSH-сессию, пока не проверите, что новое подключение работает.

### 8. Оптимизация через Flowtables

Для маршрутизаторов с высокой нагрузкой (L3 Forwarding).

```bash
table ip filter {
    flowtable f {
        hook ingress priority 0
        devices = { eth0, eth1 }
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        
        # Передача установленных соединений в Fastpath
        ct state established flow add @f
        
        ct state established,related accept
    }
}
```

**Валидация:**
```bash
# Проверка flowtable
sudo nft list flowtable
# → table ip filter {
# →     flowtable f {
# →         hook ingress priority 0; devices = { eth0, eth1 };
# →     }
# → }

# Проверка, что пакеты проходят через Fastpath
sudo nft monitor trace
```

### 9. Ограничение частоты соединений (Rate Limiting)

Защита сервисов от brute-force и flood-атак через `limit rate`.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        
        ct state established,related accept
        iif "lo" accept

        # Ограничение SSH: не более 6 новых соединений в минуту
        tcp dport 22 ct state new limit rate 6/minute accept

        # Ограничение ICMP ping
        icmp type echo-request limit rate 5/second burst 10 accept

        # Ограничение DNS-запросов
        udp dport 53 limit rate 100/second accept
    }
}
```

**Валидация:**
```bash
# Имитация brute-force
sudo hping3 -S -p 22 --flood <Target_IP>

# Проверка счетчиков
sudo nft list chain inet filter input
# → tcp dport 22 ct state new limit rate 6/minute accept # packets 12 bytes 960
```

### 10. Фильтрация TCP-флагов (Защита от сканирования)

Nmap и другие сканеры используют невалидные комбинации флагов для обхода файрволов.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        
        ct state established,related accept
        ct state invalid drop
        iif "lo" accept

        # Блокировка пакетов с нулевым набором флагов (NULL scan)
        tcp flags & (fin|syn|rst|psh|ack|urg) == 0 drop

        # Блокировка XMAS (FIN, URG, PSH)
        tcp flags & (fin|syn|rst|psh|ack|urg) == (fin|urg|psh) drop

        # Блокировка FIN-only сканирования
        tcp flags & (fin|syn|rst|psh|ack|urg) == fin drop

        tcp dport 22 accept
        tcp dport { 80, 443 } accept
    }
}
```

**Валидация:**
```bash
# Имитация XMAS-скана
sudo hping3 -F -P -U -p 22 <Target_IP>
# → Должен получить нет ответа (drop)

# Проверка счетчиков
sudo nft list chain inet filter input
```

### 11. Ограничение ICMP и ICMPv6

ICMP-флуд может исчерпать ресурсы или скрыть сканирование. Ограничение частоты снижает риск, сохраняя диагностическую функциональность.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        
        ct state established,related accept
        iif "lo" accept

        # Ограничение ping с внешних сетей
        icmp type echo-request limit rate 5/second burst 10 accept
        
        # Блокировка остальных ICMP из внешних сетей
        icmp type echo-request ip saddr 0.0.0.0/0 drop
    }
}
```

**Важно:** для корректной работы PMTUD (Path MTU Discovery) и диагностики не блокируйте ICMPv6 целиком.

### 12. Динамические блокировки с таймаутом (конкатенация IP+порт)

Использование конкатенации позволяет создавать контекстно-зависимые блокировки. Запись автоматически удаляется из набора после истечения таймаута.

```bash
table inet filter {
    set banned_pairs {
        type ipv4_addr . inet_service
        flags dynamic, timeout
        timeout 30m
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Проверка перед обработкой
        ip saddr . tcp dport @banned_pairs drop

        ct state established,related accept
        ct state invalid drop
        iif "lo" accept

        # Автоблокировка при превышении лимита
        tcp dport 22 ct state new \
            limit rate over 3/1minute \
            add @banned_pairs { ip saddr . tcp dport } \
            drop

        tcp dport 22 accept
    }
}
```

**Валидация:**
```bash
# Просмотр активных записей
sudo nft list set inet filter banned_pairs
# → elements = { 203.0.113.100 . 22 timeout 28m 45s left }
```

### 13. Защита от IP-фрагментации

Фрагментированные пакеты могут использоваться для обхода фильтров или атак типа Teardrop. В `netdev`-семействе фильтрация работает на раннем этапе, экономя ресурсы.

```bash
table netdev filter {
    chain ingress {
        type filter hook ingress device "eth0" priority -500;
        
        # Сброс всех фрагментированных пакетов (кроме фрагмента 0 с MF=0)
        ip frag-off & 0x3fff != 0 drop

        # Общий лимит на пакеты
        limit rate over 100000/second drop
    }
}
```

Для семейства `inet` фрагментация проверяется в `prerouting`:
```bash
table inet filter {
    chain prerouting {
        type filter hook prerouting priority -300; policy accept;
        
        ip frag-off & 0x3fff != 0 drop
    }
}
```

### 14. Безопасная эксплуатация и развертывание

Применение правил на удаленном сервере рискованно. Ошибка в синтаксисе или логике может привести к потере доступа.

**Методология безопасного обновления:**

1.  **Синтаксическая проверка:** перед загрузкой выполните `nft --check`.
2.  **Атомарная загрузка:** используйте `nft -f` для применения всего файла сразу.
3.  **Резервное копирование:** сохраняйте текущий ruleset перед изменениями.
4.  **Таймаут-защита:** применяйте правила через `at` или `systemd-run` с откатом.

```bash
# 1. Проверка синтаксиса
sudo nft --check -f /etc/nftables.conf
# → (пустой вывод = ошибок нет)

# 2. Бэкап текущего состояния
sudo nft list ruleset > /tmp/nftables-backup-$(date +%F).nft

# 3. Применение с откатом через 5 минут (через at)
echo "sudo nft -f /tmp/nftables-backup-$(date +%F).nft" | at now + 5 minutes
sudo systemctl restart nftables

# Если соединение не потеряно — отмените откат
atrm <job-id>
```

**Валидация:**
```bash
# Проверка статуса
sudo nft list ruleset
sudo systemctl status nftables
```

### 15. Интеграция с Fail2ban

Fail2ban автоматически добавляет IP-адреса в блокировочные списки на основе анализа логов. В nftables используется `nftables`-экшен (требуется `fail2ban >= 0.11`).

В файле `/etc/fail2ban/jail.local`:
```ini
[DEFAULT]
banaction = nftables
banaction_allports = nftables

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
findtime = 600
bantime = 3600
```

Проверка:
```bash
# Симулируйте неудачные попытки
sudo fail2ban-client status sshd
# → Status for the jail: sshd
# → |- Filter
# → |  |- Currently failed: 0
# → |  |- Total failed:     0
# → |  `- Journal matches:  _SYSTEMD_UNIT=sshd.service + _COMM=sshd
# → `- Actions
# →    |- Currently banned: 0
# →    |- Total banned:     0
# →    `- Banned IP list:
```

### 16. Мониторинг и алертинг

Эффективный мониторинг требует видимости в реальном времени. nftables предоставляет счетчики и журналы, которые можно экспортировать в системы мониторинга.

**Счетчики пакетов:**
```bash
# Просмотр правил со счетчиками
sudo nft list ruleset

# Просмотр только счетчиков input цепочки
sudo nft list chain inet filter input
```

**Ключевые метрики для мониторинга:**
- Количество dropped пакетов на интерфейсе (резкий рост = атака).
- Количество записей в динамических наборах (анализ трендов).
- Счетчик `invalid` пакетов (проблемы с conntrack или аномалии).
- Размер лог-файла `/var/log/syslog` или `journald`.

**Интеграция с Prometheus (node_exporter):**
```bash
# Метрики conntrack
curl -s http://localhost:9100/metrics | grep conntrack
# → node_nf_conntrack_entries 128
# → node_nf_conntrack_max 262144
```

**Валидация:**
```bash
# Проверка текущего использования conntrack
sudo conntrack -C
# → 128

# Проверка максимального значения
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 262144
```

## Валидация результатов

### Проверка правил

```bash
# Синтаксическая проверка файла
sudo nft --check -f /etc/nftables.conf
# → (пустой вывод = ошибок нет)

# Просмотр всех правил
sudo nft list ruleset

# Просмотр с хэндлами
sudo nft -a list ruleset
```

### Проверка состояния conntrack

```bash
# Текущее количество записей
sudo sysctl net.netfilter.nf_conntrack_count
# → 12

# Максимальное значение
sudo sysctl net.netfilter.nf_conntrack_max
# → 262144

# Статистика по состояниям
sudo conntrack -L -o extended | awk '{print $4}' | sort | uniq -c
# → 12 ESTABLISHED
# → 3 TIME_WAIT
```

### Проверка счетчиков правил

```bash
# Просмотр конкретной цепочки
sudo nft list chain inet filter input

# Ожидаемый вывод:
# → tcp dport 22 accept # packets 1542 bytes 98720
# → ct state established,related accept # packets 12450 bytes 8765432
```

## Диагностика и устранение неполадок

| Проблема | Признак | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Правила не применяются** | `nft list ruleset` пуст | Проверить синтаксис: `nft --check -f` | Исправить ошибку в файле |
| **Порт недоступен** | nmap показывает filtered | `nft list chain` — правило есть? | Проверить порядок правил, policy drop |
| **Потеря SSH при применении** | Соединение обрывается | Локальная консоль | Использовать атомарную загрузку |
| **Conntrack переполнен** | `dmesg` показывает `table full` | `conntrack -S` — `drop > 0` | Увеличить `nf_conntrack_max` |
| **IPv6 не работает** | Узлы не получают SLAAC | `nft list chain` — есть ICMPv6? | Добавить `icmpv6 type` accept |
| **DHCP не работает** | Узлы не получают IP | `tcpdump -i br0 port 67` | Проверить `udp dport 67-68 accept` |
| **Высокая нагрузка CPU** | `top` показывает high softirq | `cat /proc/softirqs` | Уменьшить правила, добавить limit rate |
| **Дублирующиеся правила** | Один и тот же трафик обрабатывается несколько раз | `nft -a list ruleset` — повторяющиеся handles? | Удалить дубликаты |

## Краевые случаи и ограничения

1.  **Атомарность:** nftables применяет изменения атомарно. Ошибка в синтаксисе halfway не частично активирует правила.
2.  **IPv6:** Если семейство `inet` используется, правило `tcp dport 80 accept` создаст записи и для IPv6. Для IPv6-only используйте `ip6` семейство.
3.  **Логирование `full`:** Записывает полные дампы пакетов, что может создать нагрузку на диск. Используйте только для диагностики.
4.  **Rate limit:** В nftables `limit rate` работает для любых протоколов. Для тонкой настройки UDP используйте Fail2ban.
5.  **Per-interface правила:** `iif "eth1"` требует точного имени интерфейса (проверьте через `ip link`).
6.  **Conntrack:** nftables использует `nf_conntrack`. При высокой нагрузке увеличьте `net.netfilter.nf_conntrack_max`.
7.  **notrack и helpers:** Использование `notrack` отключает отслеживание соединения, что может сломать FTP ALG и другие helpers. Используйте осторожно.
8.  **Flowtables:** При использовании flowtables пакеты попадают в цепочки `ingress`/`egress` семейства `netdev` и обходят классические `filter`-цепочки. Убедитесь, что политики согласованы.
9.  **Hairpin mode:** по умолчанию мост не рефлексирует кадр обратно в порт-источник. Если внутренние узлы должны общаться друг с другом через мост (например, при избыточной топологии), включите hairpin: `bridge link set dev <iface> hairpin on`.
10. **MTU:** MTU моста автоматически падает до минимального среди портов. Если к мосту подключен интерфейс с MTU 1500, весь мост будет ограничен 1500 байт, даже если остальные порты поддерживают 9000.
11. **Асимметричная маршрутизация:** если ответный трафик возвращается через другой интерфейс, stateful firewall дропает пакеты. Решение: `rp_filter=2` или единый шлюз для входящего/исходящего трафика.
12. **Conntrack helpers (ALG):** для протоколов с вспомогательными данными (FTP, SIP, TFTP) модули `nf_conntrack_*` автоматически открывают дополнительные порты. При строгой политике может потребоваться отключение helpers.

## Best Practices

1.  **Минимизация поверхности атаки:** используйте `policy drop` по умолчанию, разрешайте только необходимые типы трафика.
2.  **Состояние Established в первой позиции:** размещайте `ct state established,related accept` сразу после проверки `invalid`, чтобы минимизировать нагрузку на CPU.
3.  **Ограничение логирования:** всегда используйте `limit rate` с выражением `log`, чтобы избежать переполнения журнала при DDoS.
4.  **Проверка синтаксиса перед загрузкой:** `nft --check -f /etc/nftables.conf`.
5.  **Резервное копирование:** сохраняйте предыдущий ruleset перед каждым изменением.
6.  **Атомарность:** используйте `nft -f` вместо пошагового добавления правил через `nft add`.
7.  **Мониторинг:** настроите алерты на рост dropped-пакетов в цепочках.
8.  **Документация:** комментируйте каждое правило в конфигурационном файле, особенно исключения.
9.  **Тестирование в lab:** перед внедрением в production протестируйте конфигурацию в изолированной среде с `tcpdump`.
10. **Персистентность:** используйте `systemd`-сервис `nftables` для автоматической загрузки правил при загрузке системы.
11. **Использование сетов для производительности:** для списков из 100+ элементов используйте именованные наборы (sets) вместо последовательных проверок.
12. **Верификация после применения:** всегда проверяйте `nft list ruleset` и тестовые соединения после применения правил.

## Очистка окружения

```bash
# 1. Удаление всех правил
sudo nft flush ruleset

# 2. Удаление таблиц
sudo nft delete table inet filter
sudo nft delete table ip nat
sudo nft delete table netdev filter

# 3. Отключение службы
sudo systemctl disable --now nftables
```

## Дополнительная информация

### Управление и диагностика

```bash
# Проверка текущих счетчиков правил
nft list ruleset

# Мониторинг новых соединений в реальном времени
sudo nft monitor

# Очистка конкретной таблицы
nft flush table inet filter
```

### Сохранение персистентности

Стандартный метод для большинства дистрибутивов (Systemd-based):
1.  Выгрузить текущие правила: `nft list ruleset > /etc/nftables.conf`
2.  Активировать службу: `systemctl enable --now nftables`

### См. также

-   **[nftables — моделирование угроз](./threat_modeling.md):** стратегии проектирования правил безопасности.
-   **[nftables — архитектура и основные концепции](./architecture_and_concepts.md):** детальный разбор хуков и приоритетов.
-   **[nftables — мониторинг и алертинг](./monitoring_and_alerting.md):** Prometheus, nflog, Grafana.
-   **[nftables — настройка производительности](./performance_tuning.md):** 10G+, flowtable, XDP.
-   **[Тестирование правил nftables](./firewall_testing.md):** верификация настроек (nmap, ss, nc).
-   **[NAT — Теория и общие сценарии](../../../../../Networking/Concepts/nat/overview.md):** глубокий разбор механизмов трансляции.
-   **[Интеграция Fail2ban с nftables](../../../../Security/Tools/fail2ban.md):** автоматизация блокировок.
-   **[nftables — миграция и справочник синтаксиса](./migration_and_reference.md):** перевод правил с iptables и быстрый поиск по полям заголовков.
-   **[nftables — сегментирование сети](./network_segmentation.md):** создание нескольких изолированных мостов.
