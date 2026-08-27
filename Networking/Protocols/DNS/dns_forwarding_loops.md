# Петли перенаправления DNS (DNS Forwarding Loops)

## Определения

**Петля перенаправления DNS (DNS Forwarding Loop)** — критическая ошибка конфигурации, при которой DNS-запрос бесконечно циркулирует между серверами или возвращается к исходному серверу, не получая окончательного ответа. Это приводит к исчерпанию ресурсов (CPU, RAM, дескрипторы файлов) и резкому росту задержек (Latency) или полному отказу в обслуживании.

**Форвардер (Forwarder)** — DNS-сервер, которому делегируется выполнение рекурсивного поиска для зон, за которые локальный сервер не является авторитетным. Обычно это публичные резолверы (1.1.1.1, 9.9.9.9) или внутренние инфраструктурные серверы.

**tsuNAME** — уязвимость и тип циклической зависимости на уровне DNS-зон (authoritative level), возникающий из-за взаимных ссылок в записях NS (Name Server) между разными зонами (например, `.com` ссылается на сервер в `.nl`, который, в свою очередь, ссылается на сервер в `.com`). В 2026 году остается актуальной для частных DNS-инфраструктур. Резолверы могут генерировать в 10–20 раз больше трафика к корневым серверам, пытаясь разрешить зависимость.

**Бесконечная рекурсия (Infinite Recursion)** — состояние, при котором резолвер не может завершить поиск из-за циклической цепочки CNAME или NS-записей, превышая лимит глубины запроса (обычно 20–50 шагов).

**systemd-resolved** — системная служба Linux для разрешения имен, использующая локальные заглушки (stub-resolvers) на адресах `127.0.0.53` (стандарт) и `127.0.0.54` (расширенные функции в современных дистрибутивах). Автоматически управляет `/etc/resolv.conf` через симлинк и перехватывает все DNS-запросы хоста.

**forward only vs forward first** — два режима перенаправления в BIND. В режиме `forward only` сервер только пересылает запросы и возвращает SERVFAIL при недоступности форвардеров. В режиме `forward first` сервер сначала пытается переслать, при неудаче выполняет итеративную рекурсию самостоятельно. Петли проявляются по-разному: в `forward only` — мгновенный SERVFAIL; в `forward first` — скрытая задержка перед fallback.

**DNS Stub Resolver** — локальный резолвер-посредник (обычно `127.0.0.53`), который принимает запросы от приложений и пересылает их в «настоящий» рекурсивный резолвер. Находится в критической точке отказа, так как является промежуточным звеном между приложением и внешним DNS.

---

## Базовые концепции

### Механизм возникновения петли

В классической конфигурации (BIND, CoreDNS, Unbound) сервер, не найдя ответа в локальном кэше или авторитетных зонах, обращается к списку `forwarders`. Цикл возникает, если один из адресов указывает на сам сервер (напрямую или косвенно).

```text
┌─────────────┐     1. Запрос A     ┌─────────────┐
│  Клиент      │ ─────────────────> │  Resolver A  │
└─────────────┘                     │  (forward    │
                                    │   first)     │
                                    └──────┬──────┘
                                           │
                                    2. Forwarder не отвечает
                                           │
                                    ┌──────▼──────┐
                                    │  Resolver B  │ <─── 3. B пересылает обратно в A
                                    │  (forwarder) │
                                    └──────┬──────┘
                                           │
                                    4. A снова пересылает в B
                                           │
                                    ┌──────▼──────┐
                                    │  Resolver A  │ ──── бесконечный цикл
                                    └─────────────┘
```

### Типовые причины петель (2026)

**1. Прямое зацикливание:**
```text
forwarders { 127.0.0.1; };  // Сервер шлет запрос сам себе
```
Наиболее очевидная ошибка. Сервер пересылает запрос на loopback-интерфейс и получает его снова.

**2. Симбиотическая петля с systemd-resolved:**
```text
Хост: /etc/resolv.conf → 127.0.0.53 (systemd-resolved)
CoreDNS: forward . /etc/resolv.conf → 127.0.0.53
systemd-resolved: upstream → CoreDNS (через DNAT или настройку)
→ Цикл завершён
```
Наиболее распространённый сценарий в Kubernetes. CoreDNS наследует `/etc/resolv.conf` узла, где прописан `127.0.0.53`. Если `systemd-resolved` пересылает запросы обратно в CoreDNS (через DNAT в iptables или конфигурацию), возникает петля.

**3. Cross-Loop между серверами:**
```text
Resolver A → forwarder → Resolver B → forwarder → Resolver A → ...
```
Каждый сервер указан как forwarder другого. Часто возникает при миграции или слиянии инфраструктур.

**4. Петли в VPN/SD-WAN-сетях:**
VPN-клиент (Tailscale, AWS VPN) добавляет свой виртуальный интерфейс в список апстримов `systemd-resolved`, создавая конфликт маршрутизации для DNS-трафика между физическим и туннельным интерфейсом. Запрос уходит через туннель, а ответ не возвращается или возвращается через другой маршрут.

**5. Evasion через NAT/DNAT:**
Современные серверы сравнивают адрес запроса и форвардера. Однако, если запрос уходит с одного интерфейса, а принимается на другом (или через NAT/DNAT), стандартный Loop Detection может не сработать. Пример: DNAT-правило перенаправляет DNS с `10.0.0.1:53` на `127.0.0.1:53`, и сервер не распознаёт自身的地址.

### Влияние на производительность

Петля вызывает каскадную деградацию системы:

- **Экспоненциальный рост Latency:** Запрос проходит через цикл, пока не сработает таймаут (обычно 2–5 сек) или лимит шагов рекурсии. Каждый виток добавляет network RTT + processing time.
- **Исчерпание файловых дескрипторов:** Каждый виток петли занимает сокет/дескриптор. Приводит к ошибке `too many open files` и отказу в обслуживании других сервисов. Стандартный лимит — 1024; петля может исчерпать его за секунды.
- **CPU/RAM Spikes:** Непрерывная обработка одних и тех же пакетов потребляет 100% ресурсов процессора. В контейнеризированных средах это приводит кOOMKill.
- **Маскировка ошибки (Fallback Latency):** В режиме `forward first` сервер после таймаута в петле может попытаться выполнить рекурсию самостоятельно, что дает правильный ответ, но с огромной задержкой (5–15 сек).
- **DDoS-эффект (tsuNAME):** В случае циклов на авторитативном уровне резолверы могут генерировать в 10–20 раз больше трафика к корневым серверам.

### Сравнение поведения в forward only vs forward first

| Режим | Проявление петли | Время до отказа | Диагностика |
| :--- | :--- | :--- | :--- |
| `forward only` | Мгновенный SERVFAIL | <1 сек | Логи: `SERVFAIL`, dig: `status: SERVFAIL` |
| `forward first` | Скрытая задержка перед fallback | 5–15 сек | Логи: таймауты, dig: RTT >2 сек, ответ приходит |

---

## Практические сценарии

### Предусловия

Для диагностики петель необходимы следующие инструменты:

```bash
# Debian/Ubuntu
sudo apt install dnsutils tcpdump ngrep net-tools

# RHEL/CentOS
sudo yum install bind-utils tcpdump-ng net-tools

# Проверка наличия инструментов
dig -v && tcpdump --version | head -1 && resolvectl --version
```

### 1. Петля в BIND (named.conf)

**Симптомы:** В логах сообщения `maximum number of recursions exceeded` или `too many open files`.

**Ошибочная конфигурация:**
```conf
options {
    recursion yes;
    forward first;
    forwarders {
        127.0.0.1; // ОШИБКА: Сервер шлет запрос сам себе
    };
};
```

**Валидация и исправление:**
```bash
# 1. Проверка текущей конфигурации
sudo named-checkconf
# → если есть forwarders на 127.0.0.1 или ::1 — ошибка

# 2. Анализ логов на наличие петли
sudo journalctl -u named -n 50 | grep -E "recursion|loop|SERVFAIL"
# → named[1234]:Maximum recursion level reached for query from ...
# → named[1234]:too many open files

# 3. Исправление: удалить 127.0.0.1 из forwarders
sudo vim /etc/bind/named.conf.options
# → Заменить forwarders на публичные серверы:
#    forwarders { 9.9.9.9; 1.1.1.1; };

# 4. Применение изменений
sudo rndc reconfig
# → server reload successful

# 5. Проверка
dig @127.0.0.1 google.com +noall +header
# → flags: qr rd ra; status: NOERROR;  (вместо SERVFAIL)
```

### 2. Петля CoreDNS и systemd-resolved (Kubernetes / Ubuntu)

Наиболее распространенный сценарий в современных облачных средах.

**Цепочка:**
1. **Хост:** `/etc/resolv.conf` содержит `nameserver 127.0.0.53`.
2. **CoreDNS:** Плагин `forward . /etc/resolv.conf` отправляет внешние запросы на `127.0.0.53`.
3. **systemd-resolved:** Принимает запрос и, если upstream настроен обратно на CoreDNS (или через DNAT в iptables), возникает цикл.

**Критическая уязвимость (Март 2026):**
В плагине `loop` обнаружена уязвимость к DoS-атакам. Злоумышленник может предугадать проверочный запрос (HINFO) из-за слабого PRNG и отправить 3+ аналогичных пакета. CoreDNS воспримет это как петлю и немедленно завершит процесс (`log.Fatalf`), вызывая отказ сервиса.

**Диагностика:**
```bash
# 1. Проверка статуса подов CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns
# → coredns-xxxx   CrashLoopBackOff

# 2. Анализ логов
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
# → plugin/loop: Loop detected: loop { ... }
# → 2026/03/15 12:00:00 log.Fatalf: Exiting loop

# 3. Проверка текущего resolv.conf на узле
cat /etc/resolv.conf
# → nameserver 127.0.0.53    ← проблемный адрес

# 4. Проверка actual upstream для systemd-resolved
resolvectl status | grep "DNS Servers"
# → 127.0.0.53
```

**Исправление:**
```bash
# Вариант 1: Указать kubelet использовать чистый resolv.conf (без заглушки)
# В /var/lib/kubelet/config.yaml:
#   resolverConfig: /run/systemd/resolve/resolv.conf

# Вариант 2: Использовать NodeLocal DNSCache (рекомендуется для production)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dns/master/docs/specs/1.22.0/nodelocaldns.yaml

# Вариант 3: Указать явный upstream в Corefile
# → forward . 8.8.8.8 { health_check 5s; }
```

### 3. Петли в Unbound (OpenBSD / Linux)

Unbound — популярный рекурсивный резолвер, поддерживающий `forward-zone`. Петля возникает при указании `forward-addr` на `127.0.0.1`.

**Ошибочная конфигурация:**
```yaml
# /etc/unbound/unbound.conf
server:
    interface: 0.0.0.0
    access-control: 0.0.0.0/0 allow

forward-zone:
    name: "."
    forward-addr: 127.0.0.1  # ОШИБКА
```

**Исправление и валидация:**
```bash
# 1. Проверка конфигурации
sudo unbound-checkconf /etc/unbound/unbound.conf
# → unbound-checkconf: no errors in /etc/unbound/unbound.conf

# 2. Исправление: заменить forward-addr на публичный DNS
sudo sed -i 's/forward-addr: 127.0.0.1/forward-addr: 9.9.9.9/' /etc/unbound/unbound.conf

# 3. Перезапуск
sudo systemctl restart unbound

# 4. Проверка
dig @127.0.0.1 google.com +noall +stats
# → Query time: 23 msec (вместо таймаута >2 сек)
```

### 4. Петли в гибридных и VPN-сетях (Amazon Linux 2023 / Tailscale)

На Amazon Linux 2023 и Fedora 43+ часто возникает петля при использовании VPN-туннелей. `systemd-resolved` может автоматически добавить DNS-адрес VPN-интерфейса в список глобальных резолверов, создавая конфликт маршрутизации для DNS-трафика.

**Диагностика:**
```bash
# 1. Проверка текущих апстримов
resolvectl status
# → Global: DNS Servers: 100.64.0.2  (Tailscale) + 192.168.1.1 (Router)
# →	iface tun0: DNS Servers: 100.64.0.2
# →	iface eth0: DNS Servers: 192.168.1.1

# 2. Мониторинг DNS-трафика (поиск циклов)
sudo tcpdump -i any -n port 53 -c 20 -nn
# → Признак петли: одни и те же имена с уменьшающимся TTL

# 3. Проверка маршрутизации DNS-трафика
ip route get 100.64.0.2
# → 100.64.0.2 dev tun0 src 100.64.0.1

# 4. Выявление конфликта
resolvectl query --service example.com
# → Если результат через tun0 — проверьте, не пересылает ли Tailscale обратно в хостовый DNS
```

**Исправление:**
```bash
# Отключить автоматическое управление DNS через systemd-resolved для VPN-интерфейса
sudo systemctl mask systemd-resolved@tun0.service

# Или настроить Tailscale использовать свой DNS без перехвата системного
sudo tailscale set --accept-dns=false

# Или явно указать DNS для VPN-интерфейса (без конфликта с хостовым)
resolvectl dns tun0 100.64.0.2
resolvectl domain tun0 "~tailscale.com"
```

### 5. Диагностика через tcpdump и ngrep

Для выявления петли анализируйте трафик на всех интерфейсах. Признак петли — повторяющиеся запросы с одним Transaction ID и уменьшающимся TTL.

```bash
# Захват трафика DNS на всех интерфейсах
sudo tcpdump -i any -n -vvv port 53 -w dns-debug.pcap
# → Сохраняет в pcap для анализа в Wireshark

# Анализ в реальном времени через ngrep (ищите шторм одинаковых имен)
sudo ngrep -d any . port 53
# → Пример вывода при петле:
#   T 192.168.1.100:54321 -> 8.8.8.8:53 [AP]
#   ......example.com........................................
#   T 192.168.1.100:54322 -> 8.8.8.8:53 [AP]
#   ......example.com........................................
#   (одно и то же имя десятки раз подряд)

# Проверка текущих апстримов systemd-resolved
resolvectl status
```

```bash
# Детальный анализ TCP-дампа для выявления петли
# Ищите повторяющиеся query с одним и тем же именем и убывающим TTL
sudo tcpdump -r dns-debug.pcap -nn port 53 | awk '{print $NF}' | sort | uniq -c | sort -rn | head -10
# → Пример:
#   50 example.com.    A?    ← 50 запросов одного имени = петля
#    2 google.com.     A?
```

### 6. Проверка через dig и анализ таймаутов

В режиме `forward only` петля проявляется мгновенно как ошибка `SERVFAIL`. В `forward first` — как увеличенное время ответа.

```bash
# Базовая проверка
dig @127.0.0.1 google.com
# → Если время > 2-5 секунд, это признак fallback после таймаута в петле.

# Проверка времени ответа и статуса
dig @127.0.0.1 google.com +noall +stats +header
# → Query time: 5023 msec    ← 5 сек = таймаут + fallback
# → flags: qr rd ra; status: NOERROR;

# Проверка через diferentes серверы для сравнения
dig @8.8.8.8 google.com +noall +stats
# → Query time: 12 msec     ← эталонный RTT
# Разница (5023 vs 12) указывает на проблему в локальном резолвере

# Проверка наличия SERVFAIL (forward only с недоступным форвардером)
dig @127.0.0.1 nonexistent12345.example.com +noall +header
# → flags: qr rd ra; status: SERVFAIL;  ← петля или недоступность

# Проверка chain of trust для циклических CNAME
dig @127.0.0.1 www.example.com CNAME +noall +answer
# → www.example.com. CNAME example.com.
# → example.com.     CNAME www.example.com.  ← цикл CNAME!
```

### 7. Логирование петли в BIND

```bash
# Включение расширенного логирования в named.conf
logging {
    channel default_log {
        file "/var/log/named/query.log" versions 3 size 5m;
        severity debug;
        print-time yes;
        print-severity yes;
        print-category yes;
    };
    category recursion { default_log; };
    category rate-limit { default_log; };
};

# Мониторинг логов в реальном времени
sudo tail -f /var/log/named/query.log | grep -E "recursion|loop|exceeded"
# → 15-Aug-2026 12:00:00.000 client @0x7f... 192.168.1.100#54321 (example.com): recursion limit 15 reached for query
# → 15-Aug-2026 12:00:00.001 client @0x7f... 192.168.1.100#54322 (example.com): recursion limit 15 reached for query
```

### 8. Диагностика с помощью dig +tcpdump (комбинированная)

```bash
# Шаг 1: dig с замером времени
dig @127.0.0.1 example.com A +noall +stats
# → Query time: 5012 msec

# Шаг 2: одновременный tcpdump для подтверждения
# Терминал 1:
sudo tcpdump -i any -n port 53 -nn

# Терминал 2:
dig @127.0.0.1 example.com A

# Шаг 3: анализ вывода tcpdump
# → 12:00:00.001 IP 192.168.1.100.54321 > 127.0.0.1.53: A example.com? (28)
# → 12:00:00.002 IP 127.0.0.1.53 > 192.168.1.100.54321: A example.com? (28)  ← запрос вернулся!
# → 12:00:00.003 IP 192.168.1.100.54321 > 127.0.0.1.53: A example.com? (28)  ← повторный запрос
# → 12:00:05.004 IP 192.168.1.100.54322 > 8.8.8.8.53: A example.com? (28)     ← fallback
```

---

## Типичные ошибки и их решение

| Симптом | Вероятная причина | Шаги диагностики | Решение |
| :--- | :--- | :--- | :--- |
| `SERVFAIL` на все запросы | `forward only` + недоступный форвардер или петля | `dig @127.0.0.1 <any> +noall +header` → `status: SERVFAIL` | Заменить `forward only` на `forward first` или исправить список `forwarders` |
| Задержка 5+ сек на ответ | `forward first` + петлирующий форвардер | `dig @127.0.0.1 google.com +stats` → RTT >2 сек; `tcpdump` покажет повторы | Удалить проблемный форвардер, проверить NAT/DNAT |
| `too many open files` в логах BIND | Петля на 127.0.0.1 в `forwarders` | `journalctl -u named \| grep "too many open"` | Удалить `127.0.0.1`/`::1` из `forwarders` |
| CoreDNS `CrashLoopBackOff` | `forward . /etc/resolv.conf` указывает на `127.0.0.53` | `kubectl logs -n kube-system -l k8s-app=kube-dns \| grep loop` | Использовать `--resolv-conf /run/systemd/resolve/resolv.conf` или NodeLocal DNSCache |
| Медленный DNS через VPN | Конфликт апстримов systemd-resolved | `resolvectl status` → проверить пересечение DNS-серверов | `resolvectl dns <vpn-iface> <vpn-dns>`, отключить `accept-dns` |
| Циклические CNAME | Взаимные CNAME-записи в разных зонах | `dig @<ns> <name> CNAME +noall +answer` → проверить chain | Исправить DNS-записи, удалить взаимные CNAME |
| `loop detected` в CoreDNS | DoS-атака через PRNG-уязвимость (март 2026) | `kubectl logs \| grep "Loop detected"` + анализ source IP | Обновить CoreDNS до исправленной версии, ограничить source IP |

---

## Лучшие практики

*   **Никогда не указывайте `127.0.0.1`, `::1` или собственные IP сервера** в списке `forwarders`. Это прямой путь к петле.
*   **Используйте минимум два независимых форвардера** (например, `9.9.9.9` и `1.1.1.1`) для отказоустойчивости. Если один недоступен — другой обработает запрос.
*   **Для критических сред используйте `forward only;`** — это делает ошибки конфигурации явными и предотвращает скрытые задержки от fallback-рекурсии.
*   **В Kubernetes используйте NodeLocal DNSCache** — он радикально снижает вероятость петель за счёт жёстко заданной иерархии апстримов и кэширования на каждом узле.
*   **Для VPN-туннелей настройте `resolvectl domain`** с matcher-ом, чтобы DNS-запросы к внутренним доменам шли через туннель, а внешние — через хостовый резолвер.
*   **Валидируйте конфигурацию перед применением:** `named-checkconf` (BIND), `unbound-checkconf` (Unbound), `coredns -conf /etc/coredns/Corefile -validate` (CoreDNS).
*   **Мониторьте петли через метрики:** `coredns_forward_requests_total` (CoreDNS), `named_recursions_total` (BIND), `unbound_num_queries` (Unbound).
*   **Регулярно проверяйте tsuNAME-зависимости** инструментами типа CycleHunter или `dnsviz` для зон с перекрестными NS-ссылками.

---

## Дополнительная информация

### Инструментарий

- **named-checkconf:** Валидация синтаксиса BIND.
- **resolvectl:** Управление и диагностика резолвера в современных Linux-системах.
- **Colasoft Capsa (2026 Edition):** Анализатор трафика с автоматическим обнаружением DNS Loop.
- **Prometheus + Grafana:** Отслеживание метрик `coredns_loop_hits_total`, `forward_rcode_count`.
- **Wireshark / tshark:** Детальный анализ DNS-трафика из pcap-файлов.
- **CycleHunter / dnsviz:** Обнаружение циклических зависимостей tsuNAME в зонах.

### Предусловия для воспроизведения

Для работы с данными сценариями необходимы:
- Linux-система с BIND, CoreDNS или Unbound
- `dig`, `tcpdump`, `ngrep` (или `tshark`)
- Для Kubernetes: `kubectl` с доступом к кластеру
- Для VPN: Tailscale, WireGuard или AWS VPN

### См. также

- **[BIND: Перенаправляющий сервер](../../../Linux/Networking/Services/BIND/forwarding_server.md)** — настройка `forward only`/`forward first`.
- **[Диагностика DNS в контейнерах](../../../Linux/Diagnostics/Networking/dns/container_diagnostics.md)** — Docker и Kubernetes DNS.
- **[Unbound — рекурсивный резолвер](./unbound_resolver.md)** — альтернативный рекурсивный резолвер без петель.
- **[dnsmasq — локальный DNS/DHCP](./dnsmasq.md)** — лёгкий DNS/DHCP для локальных сетей.
