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

---

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

### 4. Поддержка HA-кластеров (VRRP/Keepalived)

При использовании Keepalived необходимо разрешить специфичный VRRP трафик (протокол 112).

```bash
table inet filter {
    chain input {
        ...
        # Разрешить VRRP пакеты от партнеров по кластеру
        ip protocol vrrp accept
        # Для IPv6
        ip6 nexthdr vrrp accept
    }
}
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

### 6. Проброс портов (DNAT) и Маскарадинг

```bash
table ip nat {
    chain prerouting {
        type nat hook prerouting priority -100;
        
        # Внешний порт 8080 -> Внутренний IP 10.0.0.5:80
        tcp dport 8080 dnat to 10.0.0.5:80
    }

    chain postrouting {
        type nat hook postrouting priority 100;
        
        # Маскарадинг для трафика, уходящего через eth0
        oifname "eth0" masquerade
    }
}
```

### 7. Безопасная настройка nftables на удалённом сервере

Настройка файрвола на удалённой машине через SSH — рискованная операция. Одно неверное движение, и доступ потерян. В этом разделе разобраны методики безопасного применения правил nftables без риска потерять SSH-соединение.

#### Почему nftables и при чём тут iptables

Nftables — современный фреймворк пакетной фильтрации, доступный начиная с ядра Linux 3.13. Он предлагает:
*   Единый синтаксис для IPv4, IPv6, ARP и других семейств протоколов (не нужно отдельно писать правила для `iptables` и `ip6tables`).
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

---

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

---

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

- **[nftables — моделирование угроз](./threat_modeling.md):** стратегии проектирования правил безопасности.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md):** детальный разбор хуков и приоритетов.
- **[Тестирование правил nftables](./firewall_testing.md):** верификация настроек (nmap, ss, nc).
- **[NAT — Теория и общие сценарии](../../../../../Networking/Concepts/nat/overview.md):** глубокий разбор механизмов трансляции.
- **[Интеграция Fail2ban с nftables](../../../../Security/Tools/fail2ban.md):** автоматизация блокировок.
