# nftables — моделирование угроз и схемы защиты

## Определения

**Моделирование угроз** — систематический процесс выявления, анализа и оценки потенциальных угроз безопасности для определения оптимальных мер противодействия на уровне сетевого фильтра. В контексте nftables threat modeling включает классификацию векторов атак, выбор приоритетов цепочек и построение правил, минимизирующих поверхность атаки.

**DoS/DDoS (Denial of Service)** — атака, направленная на исчерпание ресурсов узла (CPU, RAM, пропускная способность) или сетевого стека ядра, что приводит к отказу в обслуживании легитимных пользователей.

**IP-спуфинг (IP Spoofing)** — подмена IP-адреса источника для обхода фильтрации по адресу или организации атак типа «отражение» (reflection).

**SYN-флуд** — атака на транспортном уровне (L4), использующая механизм трехэтапного рукопожатия TCP для переполнения очереди полуоткрытых соединений (backlog).

**UDP-амплификация** — атака, использующая протоколы без установления соединения (DNS, NTP, Memcached) для отправки запроса с поддельным IP жертвы, что вызывает многократно больший ответ в сторону цели.

**Conntrack exhaustion** — атака, заключающаяся в исчерпании таблицы отслеживания соединений ядра Linux (`nf_conntrack`) путем создания большого количества полуоткрытых или быстро меняющихся соединений, что приводит к отказу в обслуживании любых новых соединений.

**TCP-флаг-аномалии** — пакеты с невалидными комбинациями TCP-флагов (например, XMAS: FIN+URG+PSH, NULL: все флаги сброшены), используемые для разведки и обхода простых файрволов.

**IP-фрагментация** — механизм разбиения крупных пакетов на фрагменты. Используется в атаках типа Teardrop или для обхода фильтров, анализирующих только первый фрагмент.

**Динамические списки (Dynamic Sets)** — именованные наборы элементов в nftables с поддержкой автоматического истечения (`timeout`), используемые для временной блокировки агрессивных IP без перезагрузки правил.

## Основные концепции

### Алгоритм разработки политики безопасности (Zero Trust подход)

При проектировании правил nftables рекомендуется следовать принципу «запрещено все, что не разрешено явно»:

1.  **Идентификация активов:** список критических сервисов (порты, протоколы) и легитимных потребителей.
2.  **Анализ рисков:** оценка уязвимости каждого сервиса к сканированию, брутфорсу или флуду.
3.  **Модель «Диода»:** четкое разделение на Ingress (входящий) и Egress (исходящий) фильтры.
4.  **Техническая реализация:** использование атомарных наборов (sets), словарей (maps) и конкатенаций для оптимизации производительности.
5.  **Непрерывный мониторинг:** логирование аномалий и интеграция с системами анализа (Wazuh, Suricata, Prometheus).

### Принципы построения политик

- **Default Deny (Запрет по умолчанию):** каждая базовая цепочь (`input`, `forward`, `output`) должна иметь политику `drop`. Разрешения добавляются явно.
- **Stateful Inspection:** правило `ct state established,related accept` размещается в верхней части цепочки для минимизации нагрузки.
- **Explicit Allow:** любой трафик, не описанный правилом, блокируется. Нельзя полагаться на «неявные» разрешения.
- **Order Matters:** правила обрабатываются сверху вниз. Первое совпадение определяет вердикт. Специфичные правила размещаются выше общих.

### Типовые угрозы и меры нейтрализации

| Угроза | Вектор атаки | Реализация в nftables |
| :--- | :--- | :--- |
| **SYN-флуд** | L4 (TCP) | Использование `synproxy` в таблице `raw` или ограничение частоты через `limit rate`. |
| **Conntrack exhaustion** | L4 (TCP/UDP) | Ограничение `limit rate` на новые соединения, `synproxy`, увеличение `nf_conntrack_max`. |
| **Сканирование портов** | Reconnaissance | Сброс пакетов в состоянии `invalid`, блокировка сканеров через динамические сеты. |
| **IP-спуфинг** | L3 (IP) | Проверка обратного пути (uRPF) через `rp_filter` и фильтрация **Bogon/Martians** адресов. |
| **Брутфорс** | L7 (App) | Динамические списки с флагом `timeout` для временной блокировки агрессивных IP. |
| **UDP-амплификация** | L4 (UDP) | Жесткое ограничение частоты ответов и фильтрация исходящих запросов. |
| **IPv6 NDP Spoofing** | L2/L3 (IPv6) | Фильтрация ICMPv6 сообщений Neighbor Discovery (только доверенные типы). |
| **TCP-флаг-атаки** | L4 (TCP) | Блокировка пакетов с невалидными комбинациями флагов. |
| **IP-фрагментация** | L3 (IP) | Сброс фрагментированных пакетов или проверка `ip frag-off & 0x3fff != 0`. |
| **ICMP-флуд** | L3/L4 | Ограничение `icmp type echo-request limit rate`. |
| **Некорректные пакеты** | Стек ядра | Глубокая проверка TCP-флагов (например, `tcp flags & (fin|syn|rst|psh|ack|urg) == 0`). |

### Фильтрация Bogon и Martians

Bogon-адреса — это IP-пространства, которые еще не распределены IANA или зарезервированы для специальных целей. Пакеты с такими адресами в качестве источника не должны приходить из внешнего интернета.

```bash
define bogons = { 
    0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 
    169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 
    192.0.2.0/24, 192.168.0.0/16, 198.18.0.0/15, 
    198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/3 
}

# В цепочке input:
ip saddr $bogons drop
```

**Сопутствующая защита — martian logging:**
В файле `/etc/sysctl.d/99-hardening.conf` включите логирование подозрительных пакетов:
```bash
net.ipv4.conf.all.log_martians=1
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.all.secure_redirects=0
net.ipv4.conf.all.send_redirects=0
```

Примените: `sudo sysctl -p /etc/sysctl.d/99-hardening.conf`

### uRPF и защита от спуфинга на хосте

В Linux uRPF реализован на уровне ядра через параметр `rp_filter`. В связке с nftables это создает двухуровневую защиту: ядро отбрасывает явный спуфинг, а nftables обрабатывает оставшийся трафик.

```bash
# Проверка текущих значений
sysctl net.ipv4.conf.all.rp_filter
# → net.ipv4.conf.all.rp_filter = 1

# Рекомендуемые значения:
# 0 — отключено (не рекомендуется для внешних интерфейсов)
# 1 — Strict (только для простых топологий)
# 2 — Loose (для multihoming, ECMP, асимметричной маршрутизации)

sudo sysctl -w net.ipv4.conf.all.rp_filter=2
```

**Важно:** итоговый режим для интерфейса — это **максимум** из `conf.all.rp_filter` и `conf.<iface>.rp_filter`. Выставить `all=0` не отключит strict на интерфейсе со значением `1`. Всегда проверяйте оба параметра.

### Механизмы защиты в nftables

| Механизм | Назначение | Пример применения |
| :--- | :--- | :--- |
| **Sets (динамические)** | Хранение IP/порт с `timeout` для временных блокировок | Брутфорс, сканеры |
| **Maps** | Сопоставление ключ→значение (IP → verdict) | GeoIP, reputation lists |
| **limit rate** | Ограничение количества пакетов/соединений в секунду | ICMP, новые SYN, log flood |
| **synproxy** | Перехват трехэтапного рукопожатия в таблице `raw` | SYN-флуд |
| **notrack** | Отключение отслеживания соединения для доверенного трафика | `ct helper` bypass, performance |
| **log** | Аудит с ограничением частоты | Forensics, incident response |

---

## Практические сценарии

### 1. Защита от SYN-флуда через Synproxy

Механизм `synproxy` перехватывает TCP-рукопожатие и подтверждает владение IP-адресом до того, как пакет попадет в стек приложения.

```bash
table inet raw {
    chain prerouting {
        type filter hook prerouting priority -300;
        
        # Направляем новые SYN пакеты на веб-порты в untracked состояние
        tcp dport { 80, 443 } tcp flags syn notrack
    }
}

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        
        # Обработка пакетов через synproxy (MSS и Sack обязательны)
        tcp dport { 80, 443 } ct state { invalid, untracked } synproxy mss 1460 wscale 7 sack-perm accept
        
        ct state established,related accept
    }
}
```

**Валидация:**
```bash
# Проверка счетчика synproxy
sudo nft list ruleset | grep synproxy
# → tcp dport { 80, 443 } ct state { invalid, untracked } synproxy mss 1460 wscale 7 sack-perm accept
```

### 2. Защита от брутфорса и сканирования (Конкатенация)

Использование конкатенации IP и порта позволяет создавать более точные правила блокировки.

```bash
table inet filter {
    # Сет для блокировки пары IP + Порт
    set banned_pairs {
        type ipv4_addr . inet_service
        flags dynamic, timeout
        timeout 1h
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Проверка по списку блокировки
        ip saddr . tcp dport @banned_pairs drop

        ct state established,related accept
        ct state invalid drop

        # Защита SSH: более 5 попыток за 2 минуты -> бан на час
        tcp dport 22 ct state new \
            limit rate over 5/2minute \
            add @banned_pairs { ip saddr . tcp dport } \
            drop
        
        tcp dport 22 accept
    }
}
```

**Валидация:**
```bash
# Имитация брутфорса
sudo hping3 -S -p 22 --flood <Target_IP>

# Проверка сета
sudo nft list set inet filter banned_pairs
# → table inet filter {
# →     set banned_pairs {
# →         type ipv4_addr . inet_service
# →         elements = { 203.0.113.5 . 22 }
# →     }
# → }
```

### 3. Защита IPv6: Neighbor Discovery и ICMPv6

IPv6 критически зависит от ICMPv6. Бездумное блокирование всех типов ICMPv6 приведет к неработоспособности сети.

```bash
table ip6 filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить необходимые типы Neighbor Discovery
        icmpv6 type { 
            destination-unreachable, packet-too-big, 
            time-exceeded, parameter-problem, 
            echo-request, echo-reply,
            nd-router-solicit, nd-router-advert,
            nd-neighbor-solicit, nd-neighbor-advert 
        } accept

        # Ограничение частоты для предотвращения ICMPv6-флуда
        icmpv6 type echo-request limit rate 10/second accept
    }
}
```

### 4. Фильтрация Egress (Защита от утечек и C2)

Ограничение исходящего трафика только доверенными направлениями.

```bash
table inet filter {
    chain output {
        type filter hook output priority 0; policy drop;

        # Разрешить ответы на установленные входящие соединения
        ct state established,related accept

        # Разрешить DNS (только к внутренним или доверенным серверам)
        udp dport 53 ip daddr 8.8.8.8 accept

        # Разрешить HTTP/HTTPS только к зеркалам обновлений
        tcp dport { 80, 443 } ip daddr @update_servers accept

        # Разрешить логирование во внешний SIEM
        udp dport 514 ip daddr 10.0.5.5 accept
    }
}
```

### 5. Фильтрация TCP-флагов (Защита от сканирования)

Nmap и другие сканеры используют невалидные комбинации флагов для обхода файрволов. Правило `tcp flags & (fin|syn|rst|psh|ack|urg) == 0` блокирует NULL-сканирование, а комбинация FIN+URG+PSH — XMAS-сканирование.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        ct state invalid drop
        iif lo accept

        # Блокировка пакетов с нулевым набором флагов (NULL scan)
        tcp flags & (fin|syn|rst|psh|ack|urg) == 0 drop

        # Блокировка XMAS (FIN, URG, PSH)
        tcp flags & (fin|syn|rst|psh|ack|urg) == (fin|urg|psh) drop

        # Блокировка FIN-only сканирования (не валидно для нового соединения)
        tcp flags & (fin|syn|rst|psh|ack|urg) == fin drop

        tcp dport 22 accept
    }
}
```

**Валидация:**
```bash
# Имитация XMAS-скана
sudo hping3 -F -P -U -p 22 <Target_IP>
# → Должен получить нет ответа (drop)
```

### 6. Ограничение ICMP и ICMPv6

ICMP-флуд может исчерпать ресурсы или скрыть сканирование. Ограничение частоты снижает риск, сохраняя диагностическую функциональность.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif lo accept

        # Ограничение ping с внешних сетей
        icmp type echo-request limit rate 5/second burst 10 accept
        
        # Блокировка остальных ICMP из внешних сетей
        icmp type echo-quest ip saddr 0.0.0.0/0 drop
    }
}
```

**Важно:** для корректной работы PMTUD (Path MTU Discovery) и диагностики не блокируйте ICMPv6 целиком.

### 7. Динамические блокировки с таймаутом (конкатенация IP+порт)

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
        iif lo accept

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

### 8. Защита от IP-фрагментации

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

### 9. Безопасная эксплуатация и развертывание

Применение правил на удаленном сервере рискованно. Ошибка в синтаксисе или логике может привести к потере доступа.

**Методология безопасного обновления:**

1. **Синтаксическая проверка:** перед загрузкой выполните `nft --check`.
2. **Атомарная загрузка:** используйте `nft -f` для применения всего файла сразу.
3. **Резервное копирование:** сохраняйте текущий ruleset перед изменениями.
4. **Таймаут-защита:** применяйте правила через `at` или `systemd-run` с откатом.

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

### 10. Интеграция с Fail2ban

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

### 11. Мониторинг и алертинг

Эффективный threat modeling требует видимости в реальном времени. nftables предоставляет счетчики и журналы, которые можно экспортировать в системы мониторинга.

**Счетчики пакетов:**
```bash
# Просмотр правил со счетчиками
sudo nft list ruleset

# Просмотр только счетчиков input цепочки
sudo nft list chain inet filter input
```

**Ключевые метрики для мониторинга:**
- Количество dropped пакетов на интерфейсе (резкий рост = атака).
- Количество записей в динамических сетах (анализ трендов).
- Счетчик `invalid` пакетов (проблемы с conntrack или аномалии).
- Размер лог-файла `/var/log/syslog` или `journald`.

**Интеграция с Prometheus (node_exporter):**
```bash
# Метрики conntrack
curl -s http://localhost:9100/metrics | grep conntrack
# → node_nf_conntrack_entries 128
# → node_nf_conntrack_max 262144
# → node_nf_conntrack_limit 262144
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

---

## Дополнительная информация

### Конфигурационные файлы

- `/etc/nftables.conf`: основной файл конфигурации (подключается через `/usr/etc/nftables.conf` в systemd-сервисе).
- `/etc/sysctl.d/*.conf`: параметры ядра (`rp_filter`, `icmp_echo_ignore_broadcasts`, `log_martians`).
- `/etc/fail2ban/jail.local`: конфигурация Fail2ban для автоматической блокировки.
- `/etc/fail2ban/action.d/nftables-*.conf`: экшены Fail2ban для работы с nftables.

### Логирование

nftables поддерживает логирование через выражение `log`. В системном журнале (`journald`) события записываются с меткой `nftables`.

```bash
# Пример правила с логированием
tcp dport 23 log prefix "NFT_TELNET_DENY: " drop

# Просмотр логов
sudo journalctl -t nftables -f
# → NFT_TELNET_DENY: IN=eth0 OUT= MAC=... SRC=203.0.113.5 DST=...
```

**Рекомендации:**
- Используйте `limit rate` с `log`, чтобы избежать переполнения журнала при DDoS.
- Префиксы должны быть информативными: `NFT_DROP: <service> <src_ip>`.
- Для production настройте ротацию логов (`logrotate` или `journald` retention).

### IPv6

IPv6 требует отдельного подхода к threat modeling из-за фундаментальных различий в архитектуре:
- Отсутствие NAT => каждый хост имеет глобальный адрес => все порты напрямую доступны из интернета.
- Зависимость от ICMPv6 (NDP, PMTUD, RA). Блокировка ICMPv6 разрывает сеть.
- L2-атаки (NDP Spoofing, RA flooding) возможны без маршрутизатора.

Рекомендации:
```bash
# Используйте семейство inet для единых правил IPv4+IPv6
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        # Правила применяются к обоим протоколам
        ct state established,related accept
        iif lo accept
        tcp dport { 22, 80, 443 } accept
        icmpv6 type { nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } accept
        icmpv6 type echo-request limit rate 5/second accept
    }
}
```

**Валидация:**
```bash
# Сканирование IPv6
sudo nmap -6 -p 22,80,443 <IPv6_Address>
# → filtered (drop) или open (accept)
```

### Безопасность: Hardening

1.  **Минимизация поверхности атаки:** Используйте `policy drop` по умолчанию, разрешайте только необходимые порты.
2.  **Rate limiting:** Защита SSH и других сервисов от brute-force через `limit rate`.
3.  **Отключение ненужных протоколов:** Закройте IPv6, если он не используется (`IPV6=no` в sysctl).
4.  **Логирование:** Включите `log prefix` с ограничением частоты для аудита.
5.  **Регулярный аудит:** Проверяйте правила ежеквартально через `nft list ruleset`.
6.  **ICMP:** Ограничьте ICMP (ping) из внешних сетей.

```bash
# Блокировка ICMP echo-request из внешних сетей
sudo nft add rule inet filter input icmp type echo-request ip saddr 0.0.0.0/0 drop
```

### Диагностика и устранение неполадок

**Правила не применяются после reload:**
```bash
# Очистка и перезагрузка
sudo nft flush ruleset
sudo systemctl restart nftables
```

**Порт недоступен несмотря на правило:**
```bash
# 1. Проверка статуса nftables
sudo nft list ruleset

# 2. Проверка конкретного правила и счетчиков
sudo nft list chain inet filter input

# 3. Проверка слушающего сокета
sudo ss -tlnp | grep <port>

# 4. Проверка внешнего доступа
sudo nmap -p <port> localhost
```

**Случайная блокировка собственного IP:**
```bash
# Проверка текущих правил
sudo nft list ruleset

# Экстренный сброс (если есть консольный доступ)
sudo nft flush ruleset
```

### Краевые случаи и ограничения

1.  **Атомарность:** nftables применяет изменения атомарно. Ошибка в синтаксисе halfway не частично активирует правила.
2.  **IPv6:** Если семейство `inet` используется, правило `tcp dport 80 accept` создаст записи и для IPv6. Для IPv6-only используйте `ip6` семейство.
3.  **Логирование `full`:** Записывает полные дампы пакетов, что может создать нагрузку на диск. Используйте только для диагностики.
4.  **Rate limit:** В nftables `limit rate` работает для любых протоколов. Для тонкой настройки UDP используйте Fail2ban.
5.  **Per-interface правила:** `iif "eth1"` требует точного имени интерфейса (проверьте через `ip link`).
6.  **Conntrack:** nftables использует `nf_conntrack`. При высокой нагрузке увеличьте `net.netfilter.nf_conntrack_max`.
7.  **notrack и helpers:** Использование `notrack` отключает отслеживание соединения, что может сломать FTP ALG и другие helpers. Используйте осторожно.
8.  **Flowtables:** При использовании flowtables пакеты попадают в цепочки `ingress`/`egress` семейства `netdev` и обходят классические `filter`-цепочки. Убедитесь, что политики согласованы.

### Compliance и аудит (PCI DSS, SOC2, HIPAA)

Файрволы — ключевой компонент compliance-рамок. nftables обеспечивает механизмы, необходимые для соответствия основным стандартам.

#### PCI DSS (Payment Card Industry Data Security Standard)

Требования PCI DSS к файрволам:

| Требование | Описание | Реализация в nftables |
|:---|:---|:---|
| **Req 1.2.1** | Разрешить только необходимые протоколы и порты | `policy drop` + явные `accept` |
| **Req 1.2.2** | Запретить прямой доступ из интернета к cardholder data | Сегментация через `forward` chains |
| **Req 1.3.1** | Запретить входящий трафик из интернета | `iifname "eth0" drop` для внутренних сетей |
| **Req 1.3.2** | Запретить исходящий трафик из cardholder data environment | `policy drop` на `output` |
| **Req 1.3.4** | Разрешить только necessary outbound | Единый whitelist через sets |
| **Req 10.1** | Логировать все доступы к cardholder data | `log prefix "PCI_"` с nflog |
| **Req 11.4** | Регулярно тестировать правила | Автоматизированные smoke-тесты |

**Шаблон для PCI DSS (cardholder data environment):**
```bash
#!/usr/sbin/nft -f
flush ruleset

table inet pci_cde {
    # Whitelist разрешенных IP для доступа к CDE
    set cde_access {
        type ipv4_addr
        flags interval
        elements = {
            10.0.0.0/8,    # Корпоративная сеть
            192.168.1.0/24  # Jump hosts
        }
    }

    # Сервисы CDE (только необходимые)
    set cde_services {
        type inet_service
        elements = { 22, 443, 5432 }  # SSH, HTTPS, PostgreSQL
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Established
        ct state established,related accept

        # Loopback
        iif "lo" accept

        # Доступ к CDE только из доверенных IP
        ip saddr @cde_services tcp dport @cde_services accept

        # Логирование всех попыток доступа
        log prefix "PCI_ACCESS_ATTEMPT: " drop
    }

    chain forward {
        type filter hook forward priority 0; policy drop;

        # Запрет прямого доступа из интернета в CDE
        iifname "eth0" oifname "eth1" drop

        # Разрешить только из jump hosts
        ip saddr @cde_access tcp dport @cde_services accept
    }

    chain output {
        type filter hook output priority 0; policy drop;

        # Established
        ct state established,related accept

        # Только необходимые исходящие подключения
        tcp dport { 53, 443 } accept  # DNS, HTTPS
        udp dport 53 accept
    }
}
```

#### SOC 2 (Service Organization Control 2)

SOC 2 требует контроля доступа и мониторинга. Ключевые паттерны:

```bash
table inet soc2_filter {
    # Логирование для аудита
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept

        # SSH с логированием
        tcp dport 22 ct state new log prefix "SOC2_SSH: " accept

        # HTTPS
        tcp dport { 80, 443 } accept

        # Финальное логирование
        log prefix "SOC2_DROP: " limit rate 10/minute
    }
}
```

#### HIPAA (Health Insurance Portability and Accountability Act)

HIPAA требует шифрования и контроля доступа к PHI (Protected Health Information):

```bash
table inet hipaa_filter {
    set phi_access {
        type ipv4_addr
        flags interval
        elements = {
            10.0.1.0/24,  # Medical staff
            10.0.2.0/24   # Admin staff
        }
    }

    chain forward {
        type filter hook forward priority 0; policy drop;

        # PHI-сервисы доступны только из доверенных сетей
        ip saddr @phi_access tcp dport { 443, 5432 } accept

        # Запрет прямого доступа к PHI из internet
        log prefix "HIPAA_PHI_BLOCK: "
    }
}
```

#### Автоматический аудит правил

**Скрипт проверки compliance:**
```bash
#!/usr/bin/env bash
# compliance_check.sh — проверка правил nftables на соответствие стандартам

set -euo pipefail

REPORT="/tmp/nftables_compliance_$(date +%F).txt"
echo "=== nftables Compliance Check ===" > "$REPORT"
echo "Date: $(date)" >> "$REPORT"

# Проверка Default Deny
echo -e "\n--- Default Deny ---" >> "$REPORT"
POLICIES=$(nft list ruleset | grep "policy")
if echo "$POLICIES" | grep -q "policy accept"; then
    echo "FAIL: Found 'policy accept' (should be 'policy drop')" >> "$REPORT"
else
    echo "PASS: All chains use 'policy drop'" >> "$REPORT"
fi

# Проверка SSH
echo -e "\n--- SSH Access ---" >> "$REPORT"
if nft list ruleset | grep -q "tcp dport 22"; then
    echo "INFO: SSH port open" >> "$REPORT"
    nft list ruleset | grep "tcp dport 22" >> "$REPORT"
else
    echo "PASS: SSH not exposed" >> "$REPORT"
fi

# Проверка логирования
echo -e "\n--- Logging ---" >> "$REPORT"
LOG_RULES=$(nft list ruleset | grep -c "log prefix")
if [ "$LOG_RULES" -gt 0 ]; then
    echo "PASS: $LOG_RULES log rules found" >> "$REPORT"
else
    echo "FAIL: No log rules found" >> "$REPORT"
fi

# Проверка rate limiting
echo -e "\n--- Rate Limiting ---" >> "$REPORT"
RATE_RULES=$(nft list ruleset | grep -c "limit rate")
if [ "$RATE_RULES" -gt 0 ]; then
    echo "PASS: $RATE_RULES rate limit rules found" >> "$REPORT"
else
    echo "WARN: No rate limiting configured" >> "$REPORT"
fi

cat "$REPORT"
```

### Связанные темы

- **[nftables: архитектура и концепции](./architecture_and_concepts.md)** — базовые компоненты, хуки, приоритеты, verdicts.
- **[nftables: практические сценарии](./practical_scenarios.md)** — готовые шаблоны stateful-файрвола, NAT, балансировки.
- **[nftables: мониторинг и алертинг](./monitoring_and_alerting.md)** — Prometheus, nflog, Grafana.
- **[Лучшие практики настройки межсетевых экранов](../../../../../Networking/Concepts/firewall_rules_best_practices.md)** — общие принципы Default Deny, динамические наборы, логирование.
