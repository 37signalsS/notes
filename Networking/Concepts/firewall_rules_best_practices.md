# Лучшие практики настройки межсетевых экранов

## Определения

- **Default Deny (Запрет по умолчанию):** Базовая стратегия безопасности, при которой весь трафик, не разрешенный явным образом, блокируется. Реализуется через политику `DROP` или `REJECT` в конце набора правил.
- **Принцип минимальных привилегий (POLP):** Предоставление сервису или пользователю только тех сетевых доступов, которые минимально необходимы для их работы.
- **Микросегментация:** Разделение сети на мелкие изолированные зоны (сегменты) для ограничения «бокового перемещения» (Lateral Movement) злоумышленника внутри периметра.
- **Bogon Filtering (Фильтрация богон-пакетов):** Блокировка пакетов с IP-адресами, которые не должны появляться в публичном Интернете (приватные сети RFC 1918, зарезервированные адреса, невыделенные диапазоны IANA).
- **Egress Filtering (Исходящая фильтрация):** Контроль трафика, покидающего внутреннюю сеть. Критически важен для предотвращения утечек данных и связи с C2-серверами.
- **Rate Limiting (Ограничение частоты):** Механизм контроля количества пакетов или соединений в единицу времени для защиты от DDoS и брутфорс-атак.
- **IP Set:** Эффективная структура данных для хранения множеств IP-адресов, сетей или портов. Позволяет выполнять проверку принадлежности за $O(1)$ вместо линейного перебора правил.
- **Fail2ban:** Сервис для автоматической блокировки IP-адресов на основе анализа логов. Интегрируется с файрволом через ipset или nftables sets.

## Базовые концепции

### Модель нулевого доверия (Zero Trust)

В современной инфраструктуре сетевой контроль строится на отказе от концепции «доверенного внутреннего периметра»:

*   **Верификация каждого запроса:** Местоположение в сети не является фактором доверия.
*   **Явное разрешение:** Каждое взаимодействие (даже внутри одного дата-центра) должно быть описано правилом.
*   **Атрибутивный доступ:** Правила основываются на идентификаторах сервисов (Spiffe/SPIRE), метках (Kubernetes Labels) или ролях.
*   **Непрерывный мониторинг:** Все соединения логируются и анализируются на аномалии.

### Иерархия и порядок правил

*   **Архитектура First-match (Первое совпадение):** В большинстве современных файрволов (iptables, nftables, ACL сетевого оборудования) обработка пакета идет **сверху вниз**. Первое правило, условия которого совпали с параметрами пакета, выполняет свое действие (`ACCEPT`, `DROP`, `REJECT`) и **завершает** дальнейшую проверку в этой цепочке.
*   **Влияние порядка на логику:** Размещение слишком общего правила (например, `DROP all to 0.0.0.0/0`) в начале списка сделает все нижележащие правила `ACCEPT` бесполезными. Это основная причина, по которой добавление «правильного» правила в конец списка не решает проблему, если выше стоит блокирующее условие.
*   **Специфичность против общности:**
    *   Сначала идут максимально точные правила (конкретные IP, порты, типы трафика).
    *   Наиболее часто используемые правила (разрешение `ESTABLISHED` соединений) должны быть в топе для минимизации нагрузки на CPU.
    *   Общие запрещающие правила или политики по умолчанию размещаются в самом конце.
*   **Риски модификации:** При добавлении новых правил необходимо проверять их положение относительно существующих блокировок. В `iptables` для этого используется вставка (`-I`) вместо добавления в конец (`-A`), если требуется приоритет.
*   **Сброс в конце:** Финальное правило `DROP ALL` (или политика цепочки) гарантирует, что неучтенный трафик не попадет в сеть.

### Стратегии обработки пакетов: DROP vs REJECT vs LOG

| Действие | Поведение | Скрытность | Применение |
| :--- | :--- | :--- | :--- |
| **DROP** | Молча отбрасывает пакет | Максимальная | Внешние интерфейсы (WAN) |
| **REJECT** | Отправляет ICMP Port Unreachable или TCP RST | Минимальная | Внутренние сети (LAN) |
| **LOG** | Записывает информацию в журнал, пакет проходит дальше | Нет | Отладка и аудит |

**Рекомендация:** Используйте `DROP` для внешнего периметра (злоумышленник не получает обратную связь), `REJECT` для внутренних сетей (ускоряет диагностику на клиенте). Всегда добавляйте `LOG` перед `DROP` для критичных правил с ограничением частоты (`--limit`).

### Динамические наборы (Sets) и автоматизация блокировок

Для эффективной работы с большими списками IP-адресов используются динамические наборы:

*   **ipset (для iptables):** Позволяет создавать именованные наборы IP-адресов, сетей или портов. Проверка принадлежности выполняется за $O(1)$.
*   **nftables sets:** Нативная поддержка динамических наборов с автоматическим обновлением.
*   **Fail2ban:** Автоматически добавляет IP-адреса в наборы на основе анализа логов.

**Преимущества динамических наборов:**
*   Одно правило вместо тысяч.
*   Автоматическое истечение записей по таймауту.
*   Не требуется перезагрузка файрвола для добавления новых адресов.

### Логирование и мониторинг

Эффективное логирование критично для аудита и расследования инцидентов:

*   **Rate-limited logging:** Всегда ограничивайте частоту логирования (`--limit 5/min`), чтобы избежать переполнения журнала при DDoS.
*   **Префиксы логов:** Используйте уникальные префиксы для идентификации источника события (`--log-prefix "SSH_DENY: "`).
*   **Уровни логирования:** Выбирайте соответствующий уровень (`--log-level 4` для warning).

## Практические сценарии

### Общие предварительные требования

Для всех сценариев ниже:
*   Доступ root или sudo на целевом сервере.
*   Установленный файрвол (iptables, nftables или firewalld).
*   Резервный доступ к серверу (IPMI, консоль) на случай блокировки.
*   План отката изменений.

### Чек-лист проектирования набора правил

1.  **Политика DROP по умолчанию:** Установите для всех цепочек (`INPUT`, `FORWARD`, `OUTPUT`).
2.  **Использование комментариев:** Всегда добавляйте комментарии с указанием задачи или номера тикета (`-m comment --comment "..."`).
3.  **Защита интерфейсов управления:** Доступ к SSH/Web-панелям только из Management VLAN или через VPN.
4.  **Ограничение частоты (Rate Limiting):** Применяйте ограничения на новые соединения для защиты от брутфорса.
5.  **Контроль IPv6:** Не блокируйте ICMPv6 полностью (нужен для NDP и PMTUD).
6.  **Логирование:** Добавляйте LOG перед DROP для диагностики.
7.  **Тестирование:** Всегда тестируйте на staging перед применением в production.

### Сценарий 1: Защищенный веб-сервер (iptables)

Классический пример для Linux-сервера.

**Предварительные требования:** сервер с iptables, сеть администраторов `192.168.10.0/24`.

```bash
# Установка политики запрета по умолчанию
iptables -P INPUT   DROP
iptables -P FORWARD DROP
iptables -P OUTPUT  DROP

# 1. Разрешить loopback (внутренние процессы сервера)
iptables -A INPUT  -i lo -j ACCEPT -m comment --comment "Allow local loopback"
iptables -A OUTPUT -o lo -j ACCEPT -m comment --comment "Allow local loopback"

# 2. Разрешить установленные и связанные соединения (Stateful)
iptables -A INPUT  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 3. Блокировать невалидные пакеты
iptables -A INPUT -m conntrack --ctstate INVALID -j DROP

# 4. Входящий трафик (Ingress)
# Разрешить SSH только из сети администраторов + Rate Limit
iptables -A INPUT -p tcp --dport 22 -s 192.168.10.0/24 -m state --state NEW -m recent --set --name SSH
iptables -A INPUT -p tcp --dport 22 -s 192.168.10.0/24 -m state --state NEW -m recent --update --seconds 60 --hitcount 4 --name SSH -j DROP
iptables -A INPUT -p tcp --dport 22 -s 192.168.10.0/24 -j ACCEPT -m comment --comment "Admin SSH with brute-force protection"

# Разрешить HTTP/HTTPS для всех
iptables -A INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT -m comment --comment "Public web traffic"

# 5. Исходящий трафик (Egress)
# Разрешить DNS запросы только к конкретным серверам
iptables -A OUTPUT -p udp --dport 53 -d 8.8.8.8 -j ACCEPT -m comment --comment "Allow DNS to Google"
iptables -A OUTPUT -p tcp --dport 53 -d 8.8.8.8 -j ACCEPT -m comment --comment "Allow DNS TCP to Google"
# Разрешить HTTPS для обновлений ОС
iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT -m comment --comment "Allow HTTPS egress for updates"

# 6. Логирование отброшенных пакетов (с ограничением частоты)
iptables -A INPUT -m limit --limit 5/min -j LOG --log-prefix "iptables_INPUT_denied: " --log-level 4
iptables -A OUTPUT -m limit --limit 5/min -j LOG --log-prefix "iptables_OUTPUT_denied: " --log-level 4
```

**Валидация:**
```bash
# Проверка правил
sudo iptables -L -n -v
# → Должны отображаться все правила с счетчиками пакетов

# Проверка SSH доступа (с админской машины)
ssh user@server
# → result: Успешное подключение

# Проверка веб-доступа
curl -I http://server
# → result: HTTP/1.1 200 OK

# Проверка логов блокировок
sudo dmesg | grep iptables_INPUT_denied
# → result: ... iptables_INPUT_denied: IN=eth0 OUT= ...
```

### Сценарий 2: Сегментация в Kubernetes (NetworkPolicy)

Изоляция микросервисов внутри кластера.

**Предварительные требования:** кластер с CNI, поддерживающим NetworkPolicy (Calico, Cilium), `kubectl` настроен.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-server-security
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: ingress-controller
    ports:
    - protocol: TCP
      port: 8080
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: postgres-db
    ports:
    - protocol: TCP
      port: 5432
  - to:  # Разрешить DNS
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

**Валидация:**
```bash
# Проверка применения политики
kubectl get networkpolicy -n production
# → result: NAME                POD-SELECTOR   AGE
#          api-server-security  app=api-server  5m

# Проверка доступа из ingress-controller (должно работать)
kubectl exec -it ingress-pod -n production -- curl -m 5 http://api-server:8080
# → result: ответ от API

# Проверка изоляки (доступ из другого пода должен быть заблокирован)
kubectl run test --rm -i --tty --image=curlimages/curl -- curl -m 5 http://api-server.production:8080
# → result: curl: (28) Failed to connect ... Timeout
```

### Сценарий 3: Современный Stateful-файрвол (nftables)

Использование одной таблицы `inet` для IPv4 и IPv6.

**Предварительные требования:** ядро Linux 5.4+, установленный nftables.

```bash
# Создание конфигурации
cat > /etc/nftables.conf <<'EOF'
table inet filter {
    # Динамический набор для fail2ban
    set flood-guard {
        type ipv4_addr
        flags timeout
        timeout 1h
    }

    chain input {
        type filter hook input priority 0; policy drop;
        
        # Разрешить loopback
        iif lo accept
        
        # Разрешить установленные соединения
        ct state established,related accept
        ct state invalid drop
        
        # Разрешить ICMPv6 (необходимо для работы IPv6)
        icmpv6 type { echo-request, nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, nd-router-advert, mld-listener-query, mld-listener-report } accept
        
        # Rate limiting для SSH (защита от брутфорса)
        tcp dport 22 ct state new limit rate 3/minute accept
        
        # Веб-трафик
        tcp dport { 80, 443 } accept
        
        # Логирование и блокировка
        counter log prefix "nft_DROP: " drop
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        ct state established,related accept
        counter log prefix "nft_FWD_DROP: " drop
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
EOF

# Применение конфигурации
sudo nft -f /etc/nftables.conf

# Включение автозагрузки
sudo systemctl enable --now nftables
```

**Валидация:**
```bash
# Проверка конфигурации
sudo nft list ruleset
# → result: table inet filter { ... }

# Проверка работы SSH (должно быть доступно)
ssh user@server
# → result: Успешное подключение

# Проверка rate limiting (5 попыток подряд)
for i in {1..5}; do ssh -o ConnectTimeout=2 user@server; done
# → result: После 3 попытки — Connection timed out

# Проверка логов
sudo journalctl -kf | grep nft_DROP
```

### Сценарий 4: Использование ipset для динамической блокировки

**Предварительные требования:** установленный ipset, iptables.

```bash
# Создание набора для заблокированных IP
sudo ipset create blocked_ips hash:ip timeout 3600

# Добавление IP в черный список
sudo ipset add blocked_ips 192.0.2.100

# Создание набора для белого списка
sudo ipset create whitelist hash:ip
sudo ipset add whitelist 10.0.0.0/8
sudo ipset add whitelist 192.168.0.0/16

# Правила iptables с использованием наборов
iptables -A INPUT -m set --match-set whitelist src -j ACCEPT
iptables -A INPUT -m set --match-set blocked_ips src -j DROP

# Интеграция с fail2ban (в /etc/fail2ban/jail.local)
# banaction = iptables-ipset-protoall
```

**Валидация:**
```bash
# Проверка содержимого набора
sudo ipset list blocked_ips
# → result: Name: blocked_ips
#          Type: hash:ip
#          Members:
#          192.0.2.100 timeout 3595

# Проверка блокировки (с заблокированного IP)
curl http://server
# → result: Connection timed out

# Проверка автоматического удаления по таймауту (через 1 час)
sudo ipset list blocked_ips
# → result: Members: (пусто)
```

### Сценарий 5: Egress Filtering с использованием ipset

Контроль исходящего трафика для предотвращения утечек.

**Предварительные требования:** определен список разрешенных внешних сервисов.

```bash
# Создание набора разрешенных внешних сетей
sudo ipset create allowed_egress hash:net
sudo ipset add allowed_egress 198.51.100.0/24  # Процессинг
sudo ipset add allowed_egress 203.0.113.0/24     # API партнера

# Правила egress filtering
iptables -A OUTPUT -m set --match-set allowed_egress dst -j ACCEPT
iptables -A OUTPUT -p tcp --dport 443 -m set --match-set allowed_egress dst -j ACCEPT
iptables -A OUTPUT -p tcp --dport 80 -j DROP
iptables -A OUTPUT -p tcp --dport 443 -j DROP
```

**Валидация:**
```bash
# Проверка доступа к разрешенному сервису
curl https://198.51.100.10/api
# → result: Успешное подключение

# Проверка блокировки к неразрешенному сервису
curl https://example.com
# → result: Connection timed out
```

### Сценарий 6: Автоматизация блокировок с Fail2ban

**Предварительные требования:** установленные fail2ban и ipset.

```bash
# Установка
sudo apt install fail2ban ipset  # Debian/Ubuntu
# или
sudo dnf install fail2ban fail2ban-firewalld  # RHEL

# Конфигурация /etc/fail2ban/jail.local
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1 10.0.0.0/8
bantime = 1h
findtime = 10m
maxretry = 3
banaction = iptables-ipset-protoall
backend = systemd

[sshd]
enabled = true
port = ssh
maxretry = 3

[nginx-limit-req]
enabled = true
port = http,https
filter = nginx-limit-req
logpath = /var/log/nginx/error.log
maxretry = 10
EOF

# Запуск
sudo systemctl enable --now fail2ban
```

**Валидация:**
```bash
# Проверка статуса
sudo fail2ban-client status
# → result: Number of jail: 2
#          Jail list: nginx-limit-req, sshd

# Проверка заблокированных IP
sudo fail2ban-client status sshd
# → result: Total banned: 5
#          Banned IP list: 1.2.3.4 5.6.7.8 ...

# Проверка ipset
sudo ipset list
# → result: Содержит наборы, созданные fail2ban
```

## Валидация и диагностика

### Проверка состояния файрвола

```bash
# Проверка загруженных правил (iptables)
sudo iptables -L -n -v --line-numbers
# → Отображает все правила с номерами и счетчиками

# Проверка загруженных правил (nftables)
sudo nft list ruleset
# → Отображает полную конфигурацию

# Проверка политик по умолчанию
sudo iptables -L | grep policy
# → result: Chain INPUT (policy DROP)

# Проверка статистики conntrack
sudo conntrack -S
# → result: entries 42, ...
```

### Проверка связности

```bash
# Тестирование порта (nc)
nc -zv server 22
# → result: Connection to server 22 port [tcp/ssh] succeeded!

nc -zv server 80
# → result: Connection to server 80 port [tcp/http] succeeded!

# Тестирование с указанием интерфейса
nc -zv -s 192.168.10.5 server 22
# → result: Connection to server 22 port [tcp/ssh] succeeded!

# Проверка маршрута
traceroute -n server
# → result: 1  gateway (10.0.0.1)  1.234 ms
```

### Аудит правил

```bash
# Поиск правил с нулевым счетчиком (неиспользуемые)
sudo iptables -L -n -v | grep "0     0"
# → Потенциально "мертвые" правила

# Поиск any-any правил
sudo iptables -L -n | grep "0.0.0.0/0.*0.0.0.0/0"
# → Потенциально опасные правила

# Проверка логирования
sudo iptables -L -n | grep LOG
# → Убедитесь, что критичные правила логируются
```

### Мониторинг логов

```bash
# Просмотр событий блокировки в реальном времени
sudo journalctl -kf | grep -E "(iptables|nft)_DROP"
# → result: ... iptables_INPUT_denied: IN=eth0 OUT= SRC=1.2.3.4 ...

# Анализ частоты блокировок
sudo grep "iptables_INPUT_denied" /var/log/kern.log | awk '{print $10}' | sort | uniq -c | sort -rn | head
# → result: 42 1.2.3.4
#          28 5.6.7.8

# Просмотр активных соединений
sudo conntrack -L | head -20
# → result: tcp      6 431999 ESTABLISHED src=10.0.0.5 dst=10.0.0.1 sport=22 ...
```

## Устранение неполадок

### Типичные проблемы и решения

#### Проблема 1: Потеря доступности после применения правил

**Симптомы:** После применения правил файрвола теряется SSH-соединение.

**Решение и профилактика:** подробно описаны в [nftables — безопасная настройка на удалённом сервере](../../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md#безопасная-настройка-nftables-на-удалённом-сервере).

#### Проблема 2: Не работает доступ после перезагрузки

**Симптомы:** Правила работают после ручного применения, но сбрасываются после перезагрузки.

**Причины:**
- Правила не сохранены в персистентную конфигурацию
- Не включен сервис автозагрузки

**Решение:**
```bash
# Debian/Ubuntu с iptables
sudo apt install iptables-persistent
sudo netfilter-persistent save

# Debian/Ubuntu с nftables
sudo nft list ruleset | sudo tee /etc/nftables.conf
sudo systemctl enable --now nftables

# RHEL с firewalld
sudo firewall-cmd --runtime-to-permanent
```

#### Проблема 3: Медленная работа файрвола

**Симптомы:** Высокие задержки, низкая пропускная способность.

**Причины:**
- Слишком много правил (линейный перебор в iptables)
- Отсутствие оптимизации порядка правил

**Решение:**
```bash
# Анализ производительности
sudo iptables -L -n -v | head -20
# → Перенесите правила с высокими счетчиками в начало

# Использование ipset вместо множества правил
sudo ipset create whitelist hash:ip
sudo ipset add whitelist 10.0.0.0/8
iptables -A INPUT -m set --match-set whitelist src -j ACCEPT

# Миграция на nftables для лучшей производительности
```

#### Проблема 4: Конфликт с Docker

**Симптомы:** Правила файрвола не применяются к трафику контейнеров.

**Причины:**
- Docker добавляет свои правила в цепочки, обрабатываемые до INPUT
- Правила DOCKER-USER не настроены

**Решение:**
```bash
# Использование цепочки DOCKER-USER
sudo iptables -I DOCKER-USER -i eth0 ! -s trusted_ip -j DROP

# Или отключение автоматических правил Docker
# /etc/docker/daemon.json: {"iptables": false}
```

#### Проблема 5: Не работает IPv6

**Симпомы:** Трафик IPv6 блокируется, хотя IPv4 работает.

**Причины:**
- Настроены правила только для IPv4
- Заблокирован ICMPv6 (необходим для NDP и PMTUD)

**Решение:**
```bash
# Проверка правил IPv6
sudo ip6tables -L -n

# Разрешение необходимых ICMPv6 типов
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type echo-request -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-neighbor-solicit -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-neighbor-advert -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-router-solicit -j ACCEPT
sudo ip6tables -A INPUT -p icmpv6 --icmpv6-type nd-router-advert -j ACCEPT

# Или используйте nftables с семейством inet
```

## Дополнительная информация

### Предотвращение туннелирования и эксфильтрации

*   **Инспекция DNS:** Разрешайте DNS только к доверенным внутренним рекурсорам. Это блокирует использование DNS-туннелей (например, `iodine`).
*   **Блокировка QUIC/HTTP3:** Если фильтрация L7 не умеет инспектировать UDP 443, блокируйте его, принуждая браузеры переходить на инспектируемый HTTPS (TCP 443).
*   **Ограничение ICMP:** Разрешайте только необходимые типы ICMP (echo-request с rate limit, destination-unreachable, time-exceeded).

### Типичные ошибки (Anti-patterns)

*   **Any-Any правила:** Открытие доступа ко всей подсети «на время отладки» и забвение этого правила.
*   **Игнорирование IPv6:** Настройка защиты только для IPv4, оставляя IPv6-стек полностью открытым.
*   **Использование имен хостов:** Файрволы резолвят DNS в момент загрузки правил. Если IP хоста изменится, правило станет невалидным. Используйте IP или динамические IP Sets.
*   **Ручное управление:** Настройка без IaC (Ansible, Terraform), ведущая к рассинхрону конфигураций.
*   **Отсутствие логирования:** Без логов невозможно диагностировать проблемы и расследовать инциденты.

### Чек-лист аудита (Firewall Hygiene)

*   **Поиск "мертвых" правил:** Удаляйте правила с нулевым счетчиком пакетов за последние 3 месяца.
*   **Анализ теневых правил (Shadowing):** Поиск правил, которые никогда не сработают из-за более широких правил выше по списку.
*   **Проверка политик по умолчанию:** Убедитесь, что INPUT и FORWARD имеют политику DROP.
*   **Проверка логирования:** Критичные правила должны логироваться.
*   **Проверка IPv6:** Убедитесь, что IPv6 настроен или явно отключен.

## Рекомендации по внедрению

### Порядок применения правил

1.  **Начните с monitoring mode:** Сначала добавьте только LOG, не DROP, чтобы понять трафик.
2.  **Применяйте поэтапно:** Сначала loopback, затем ESTABLISHED, затем разрешающие правила, затем DROP.
3.  **Используйте таймер:** При удаленном доступе всегда имейте план отката.
4.  **Документируйте:** Каждое правило должно иметь комментарий с назначением.
5.  **Тестируйте:** Проверяйте на staging-среде перед production.

### Интеграция с IaC

```yaml
# Пример Ansible задачи
- name: Configure firewall
  ansible.builtin.template:
    src: nftables.conf.j2
    dest: /etc/nftables.conf
  notify: reload nftables

- name: Enable nftables service
  ansible.builtin.systemd:
    name: nftables
    enabled: true
    state: started
```

## Ограничения и граничные случая

### Ограничения iptables

1.  **Линейный поиск:** Каждый пакет последовательно проверяется против всех правил. При большом количестве правил производительность деградирует.
2.  **Отсутствие атомарности:** Изменения применяются по одному правилу, что может создавать окна уязвимости.
3.  **Раздельные инструменты:** IPv4 (iptables) и IPv6 (ip6tables) требуют дублирования конфигурации.

### Ограничения nftables

1.  **Поддержка ядра:** Требует ядро 3.13+ (рекомендуется 5.4+ для полной функциональности).
2.  **Обучение:** Синтаксис отличается от iptables, требует времени на освоение.

### Граничные случаи

*   **Asymmetric routing:** Если ответный трафик идет другим путем, stateful файрвол блокирует его.
*   **FTP и другие протоколы с несколькими соединениями:** Требуют специальных модулей conntrack (nf_conntrack_ftp).
*   **NAT и файрвол:** NAT выполняется до фильтрации, учитывайте это при проектировании правил.

**См. также:**
*   **[Межсетевые экраны: Концепции и механизмы](./firewall_concepts.md)** — теоретическая база.
*   **[Сетевые зоны безопасности](./network_security_zones.md)** — архитектурное разделение.
*   **[Модель нулевого доверия (Zero Trust)](./zero_trust_overview.md)** — стратегия безопасности.
