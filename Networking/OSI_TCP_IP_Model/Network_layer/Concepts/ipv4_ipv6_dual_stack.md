# Сосуществование IPv4 и IPv6 (Dual Stack)

## Определения

**Dual Stack (Двойной стек)** — сетевая архитектура, при которой узлы и сетевое оборудование одновременно поддерживают и используют оба стека протоколов: IPv4 и IPv6. Это основной и наиболее предпочтительный метод миграции на IPv6, обеспечивающий плавный переход без прерывания связи.

**IPv4-mapped IPv6 addresses** — механизм (RFC 4291), позволяющий представлять IPv4-адреса внутри адресного пространства IPv6 (префикс `::ffff:0:0/96`). Это позволяет Dual-stack приложениям слушать один IPv6-сокет и принимать соединения от клиентов обоих протоколов.

**NAT64** — Stateless (SIIT) или Stateful трансляция IPv6→IPv4 на шлюзе. Позволяет IPv6-only клиентам обращаться к IPv4-ресурсам. Работает в паре с DNS64 (RFC 6147). Well-Known Prefix: `64:ff9b::/96` (RFC 6052).

**DNS64** — механизм синтеза AAAA-записей из A-записей (RFC 6147). DNS-сервер подставляет NAT64-префикс перед IPv4-адресом, создаваяseudo-IPv6-адрес для маршрутизации трафика через NAT64-шлюз.

**464XLAT** — двойная трансляция (RFC 6877): **CLAT** (Customer-side translator) на устройстве транслирует IPv4→IPv6, а **PLAT** (Provider-side translator, NAT64) — обратно. Стандарт в Android/iOS. Позволяет IPv4-only приложениям работать в IPv6-only сетях.

**MAP-E (Mapping of Address and Port - Encapsulation, RFC 7597)** — туннельная технология для масштабируемой трансляции IPv4↔IPv6. Инкапсулирует IPv4-пакеты в IPv6-туннели с распределением портов и адресов между пользователями через PSID (Port-Set ID). Используется провайдерами (Japan NTT, KDDI) для экономии IPv4-адресов.

**MAP-T (Mapping of Address and Port - Translation, RFC 7599)** — вариант MAP-E с трансляцией (а не инкапсуляцией). IPv6-пакеты с данными IPv4 проходят трансляцию заголовков без инкапсуляции, что снижает Overhead.

**Dual-Stack Lite (DS-Lite, RFC 6333)** — инкапсуляция IPv4 в IPv6-туннель (6in4) с провайдерским NAT (AFTR). Экономит публичные IPv4-адреса за счёт CGNAT. Менее эффективен, чем MAP-E/T из-за централизованного NAT.

## Связь с соседними уровнями

```text
L4 (Транспортный) ← TCP/UDP: порты одинаковы для IPv4 и IPv6; Happy Eyeballs выбирает семейство
       ↕
L3 (Сетевой)      ← IPv4 / IPv6: два независимых стека, RIB/FIB для каждого
       ↕
L2 (Канальный)    ← ARP (IPv4) vs NDP (IPv6): разные механизмы L2-револвинга
       ↕
L1 (Физический)   ← Кабель/эфир не различает IPv4/IPv6; MTU = 1500 (IPv4), 1280 min (IPv6)
```

| Уровень | IPv4 | IPv6 | Dual Stack влияние |
| :--- | :--- | :--- | :--- |
| **L4 → L3** | TCP/UDP через IPv4-сокет | TCP/UDP через IPv6-сокет | Happy Eyeballs: L4 выбирает最快ший |
| **L3** | Заголовок 20-60 байт | Заголовок 40 байт (фикс.) | Два RIB/FIB; LPM в каждом отдельно |
| **L3 → L2** | ARP-запрос → MAC | NDP (NS/NA) → MAC | Два протокола резолвинга на одном интерфейсе |
| **L2** | Ethernet Frame (Type 0x0800) | Ethernet Frame (Type 0x86DD) | Коммутатор не различает; фильтрация по Type |

### Инкапсуляция (Dual Stack)

```text
IPv4 Packet:
[Ethernet][IP4(20-60B)][TCP/UDP][Data]  ← Type 0x0800

IPv6 Packet:
[Ethernet][IP6(40B)][TCP/UDP][Data]     ← Type 0x86DD

IPv4-mapped IPv6:
[Ethernet][IP6(40B)][TCP/UDP][Data]     ← Dst: ::ffff:192.0.2.1
```

**PDU L3:** Пакет (Packet). IPv4: 20-60 байт заголовок. IPv6: фиксированный 40-байтный заголовок + extension headers (опционально).

**Сравнение заголовков IPv4 vs IPv6:**

| Поле | IPv4 | IPv6 |
| :--- | :--- | :--- |
| Длина заголовка | 20-60 байт (переменная) | 40 байт (фиксированная) |
| Поляustainability | 12 полей | 8 полей |
| Опции | Внутри заголовка (до 40 байт) | Extension Headers (цепочка) |
| Фрагментация | На промежуточных маршрутизаторах | Только на источнике |
| Checksum | Есть (L3) | Нет (доверие L2/L4) |
| TTL / Hop Limit | TTL (8 бит) | Hop Limit (8 бит, то же поле) |
| Class / Traffic Class | TOS (8 бит) | Traffic Class (8 бит) + Flow Label (20 бит) |
| Адрес назначения | 32 бита | 128 бит |

## Базовые концепции

### Зачем нужен Dual Stack

1.  **Постепенная миграция:** Глобальный переход на IPv6 занимает десятилетия. Dual Stack позволяет узлам беспрепятственно взаимодействовать как с современными, так и с устаревшими сегментами интернета.
2.  **Обратная совместимость:** Существует огромное количество legacy-оборудования и ПО, которое никогда не получит поддержку IPv6.
3.  **Гибкость управления:** Позволяет администраторам внедрять IPv6 поэтапно (например, сначала во внутренней сети ЦОД, затем на внешних периметрах), сохраняя IPv4 как гарантированный канал связи.

### Уровни реализации

-   **Уровень ОС (Host):** Ядро поддерживает два независимых стека. Каждому интерфейсу назначаются адреса обоих типов.
-   **Уровень приложений:** Современные библиотеки (Go, Rust, Python) абстрагируют выбор протокола, используя системные вызовы и алгоритмы приоритезации.
-   **Сетевой уровень (Router):** Поддержка двух независимых таблиц маршрутизации (RIB/FIB) и протоколов динамической маршрутизации (OSPFv3 для IPv6, OSPFv2 для IPv4).

### Этапы миграции (Transition States)

| Этап | Описание | Пример | RFC |
| :--- | :--- | :--- | :--- |
| **Dual Stack** | Узлы поддерживают IPv4+IPv6 одновременно | Сервер с `eth0: 192.0.2.1/24` и `2001:db8::1/64` | RFC 4213 |
| **IPv6-only (с NAT64)** | IPv6-only сеть + NAT64/DNS64 для доступа к IPv4 | Мобильные сети операторов | RFC 6146 |
| **IPv6-only (чистый)** | Полный отказ от IPv4; все ресурсы доступны по IPv6 | Google, Facebook, Cloudflare (внутренне) | — |
| **IPv4 as Service** | IPv4 эмулируется через 464XLAT для legacy-приложений | Android/iOS в IPv6-only сетях | RFC 6877 |

> **Статус 2026:** Глобально Dual Stack остаётся основным режимом. Мобильные операторы (T-Mobile, Rakuten) переходят на IPv6-only + 464XLAT. ЦОДы крупных игроков (Google, Meta) — чистый IPv6.

## Алгоритмы выбора протокола

### Happy Eyeballs (v2 и v3)

Основная проблема Dual Stack: если IPv6 настроен некорректно (пакеты дропаются на пути), пользователь может столкнуться с длительным ожиданием (таймаутами) перед тем, как ОС переключится на IPv4.
**Happy Eyeballs** (RFC 8305) решает это путем параллельного инициирования соединений:

1.  **Параллельный резолвинг:** ОС одновременно запрашивает DNS-записи типов `A` и `AAAA`.
2.  **Задержка старта (Resolution Delay):** Система отдает предпочтение IPv6, но запускает таймер (~150-250 мс). Если за это время соединение по IPv6 не установилось, начинается попытка по IPv4.
3.  **Побеждает быстрейший:** Используется то соединение, которое первым завершило рукопожатие. Второе соединение закрывается.

> **Статус 2026:** Внедряется **Happy Eyeballs v3**. Ключевое отличие — использование истории успеха соединений к конкретным префиксам и поддержка **HTTPS RR** (RFC 9460) для ускорения TLS и QUIC (HTTP/3).

## Технологии перехода и интеграции

Когда полноценный Dual Stack невозможен (например, в IPv6-only инфраструктуре), используются механизмы трансляции.

| Технология | Механизм | Применение | Статус (2026) |
| :--- | :--- | :--- | :--- |
| **NAT64 / DNS64** | Трансляция IPv6 пакетов в IPv4 на шлюзе. DNS64 синтезирует AAAA-записи. | Доступ из IPv6-only облаков к IPv4-интернету. | **Активно** (мобильные сети) |
| **464XLAT** | Двойная трансляция: **CLAT** (на устройстве) → **PLAT** (NAT64 провайдера). | Стандарт в Android/iOS. Позволяет IPv4-only приложениям работать в IPv6-сетях. | **Активно** (стандарт Android) |
| **Dual-Stack Lite** | Инкапсуляция IPv4 в IPv6 туннель + CGNAT у провайдера. | Магистральные сети провайдеров. | **Устаревает** ( заменяется MAP-E/T) |
| **MAP-E** | IPv4-in-IPv6 инкапсуляция + распределение портов (PSID). | Провайдеры (Japan NTT, KDDI): масштабная трансляция IPv4↔IPv6. | **Активно** |
| **MAP-T** | Трансляция заголовков IPv4↔IPv6 (без инкапсуляции). | Альтернатива MAP-E с меньшим Overhead. | **Активно** |
| **6to4 / 6rd** | Инкапсуляция IPv6 в IPv4 пакеты. | Устаревшие методы доставки IPv6 через IPv4-инфраструктуру. | **Устаревшие** (RFC 7526 deprecated) |
| **ISATAP** | Инкапсуляция IPv6 в IPv4 с автоматическим туннелем. | Корпоративные сети (transition only). | **Устаревает** |
| **Teredo** | IPv6 через UDP через IPv4 (NAT-traversal). | Крайний случай: IPv6 через строгий NAT. | **Устаревает** (RFC 8431 deprecated) |

### Подробнее о NAT64/DNS64

**NAT64** работает в режимах:
- **Stateless (SIIT, RFC 7915):** Маппинг 1:1, без состояния. Подходит для CDN и серверов.
- **Stateful (RFC 6146):** Сессионная трансляция. Подходит для клиентов (больше конечностей).

**DNS64 (RFC 6147):** DNS-сервер подставляет Well-Known Prefix `64:ff9b::/96` перед IPv4-адресом:
```
А-запись: example.com → 192.0.2.1
DNS64: example.com → 64:ff9b::192.0.2.1
```

**Инструменты:** Tayga (stateful NAT64), Jool (stateless + stateful), wallabagnode/nat64.

### Подробнее о MAP-E/MAP-T

**MAP-E (RFC 7597):**
- Каждый пользователь получает набор портов (PSID) в рамках общего IPv4-адреса.
- IPv4-пакет инкапсулируется в IPv6-туннель (Proto 41) с заголовком MAP-E.
- Шлюз (BR - Border Relay) декапсулирует и маршрутизирует в IPv4-интернет.
- **Преимущество:** Stateless (нет single point of failure), масштабируемость.

**MAP-T (RFC 7599):**
- Как MAP-E, но вместо инкапсуляции — трансляция заголовков (аналог NAT64, но распределённый).
- IPv6-пакеты с данными IPv4 транслируются напрямую.
- **Преимущество:** Меньший Overhead (нет инкапсуляции), проще MTU.

## Практическая реализация и диагностика

### Настройка сокетов в Linux
Параметр `net.ipv6.bindv6only` определяет, как приложение будет слушать адрес `::` (все адреса).

-   **`bindv6only = 0` (Default):** Сокет `[::]` принимает трафик обоих протоколов. IPv4-клиенты видны как `::ffff:192.168.1.1`.
-   **`bindv6only = 1`:** Сокет принимает **только** IPv6. Для поддержки IPv4 приложение должно открыть второй сокет на `0.0.0.0`. Это более безопасный режим, упрощающий логирование и аудит.

### Инструменты диагностики (Linux)

```bash
# === Просмотр адресов ===
ip addr show eth0                       # оба семейства на интерфейсе
ip -6 addr show eth0                    # только IPv6
ip -4 addr show eth0                    # только IPv4
ip -6 route show                        # таблица маршрутизации IPv6
ip -6 route get 2001:4860:4860::8888    # FIB-решение для Google DNS (IPv6)

# === Проверка связности ===
ping google.com                         # Инициализирует Happy Eyeballs
ping -4 google.com                      # Принудительно IPv4
ping -6 google.com                      # Принудительно IPv6
ping -6 -I eth0 fe80::1                 # ping link-local адреса (обязательно -I)

# === DNS и трансляция ===
dig A example.com                       # IPv4-адреса
dig AAAA example.com                    # IPv6-адреса
dig AAAA example.com @2001:4860:4860::8888  # через IPv6 DNS
nslookup example.com                    # Resolv.conf проверяет A и AAAA

# === Проверка слушающих сокетов ===
ss -ntlp | grep -E '0.0.0.0|::'        # все TCP-сокеты
ss -6 -ntlp                             # только IPv6 сокеты
ss -4 -ntlp                             # только IPv4 сокеты

# === Трассировка ===
traceroute -6 target.com                # IPv6 traceroute
traceroute -4 target.com                # IPv4 traceroute
mtr -6 target.com                       # IPv6 mtr

# === Проверка Happy Eyeballs и Happy Eyeballs v3 ===
# На macOS:
networksetup -getinfo Wi-Fi             # IPv6 status
scutil --dns | grep nameserver          # DNS-серверы

# На Linux (systemd-resolved):
resolvectl status                       # статус DNS и Happy Eyeballs

# === Проверка sysctl ===
sysctl net.ipv6.conf.all.accept_ra     # автоконфигурация
sysctl net.ipv6.conf.all.forwarding     # включение IPv6 forwarding
sysctl net.ipv6.conf.all.disable_ipv6   # отключение IPv6
sysctl net.ipv6.bindv6only              # dual-stack socket behavior

# === Проверка NAT64/DNS64 (если есть) ===
dig AAAA ipv4only.arpa                  # Well-known DNS64 test (RFC 7050)
# → Ожидается: 64:ff9b::192.0.2.x (если DNS64 настроен)
```

### Диагностика Dual Stack

```bash
# === Проверка Happy Eyeballs ===
# Принудительный выбор протокола:
curl -4 https://example.com             # только IPv4
curl -6 https://example.com             # только IPv6

# Логирование DNS-резолвинга:
curl -v https://example.com 2>&1 | grep -E "Trying|Connected"

# === Проверка ARP vs NDP ===
ip neigh show                           # ARP-таблица (IPv4)
ip -6 neigh show                        # NDP-таблица (IPv6)

# === Отладка инкапсуляции (6in4, MAP-E) ===
ip -6 tunnel show                       # IPv6-туннели
ip tunnel show                          # IPv4-туннели
ip -d link show sit0                    # детали SIT (6to4)

# === Проверка MTU ===
ping -4 -M do -s 1472 target.com        # IPv4 MTU test (1472+28=1500)
ping -6 -M do -s 1432 target.com        # IPv6 MTU test (1432+40+8=1480)
# IPv6 min MTU = 1280; если пакет не проходит, он будет фрагментирован или отброшен

# === Мониторинг статистики ===
cat /proc/net/snmp | grep -E "Ip:|Ip6:"  # счётчики пакетов
nstat -az | grep -E "Ip6|Icmp6"           # расширенная статистика
ip -s -6 link show eth0                    # счётчики на интерфейсе (IPv6)
```

### Инструменты диагностики

| Инструмент | Назначение | Пример команды |
| :--- | :--- | :--- |
| `ip addr/route` | Просмотр адресов и маршрутов | `ip -6 addr show eth0` |
| `dig` / `nslookup` | Проверка DNS-резолвинга A/AAAA | `dig AAAA example.com` |
| `ping -4/-6` | Проверка связности по конкретному протоколу | `ping -6 2001:4860:4860::8888` |
| `traceroute -6` | IPv6-трассировка пути | `traceroute -6 example.com` |
| `ss` | Просмотр слушающих сокетов (IPv4/IPv6) | `ss -6 -ntlp` |
| `tcpdump` | Захват пакетов с фильтрацией по семейству | `tcpdump -i eth0 ip6` |
| `nftables` | Фильтрация/логирование трафика по протоколу | `nft add rule inet filter input ip6 saddr ...` |
| `resolvectl` | Статус DNS и Happy Eyeballs (systemd) | `resolvectl status` |
| `curl -4/-6` | Тест HTTP по конкретному семейству | `curl -6 https://example.com` |

## Dual Stack в Kubernetes

Современные кластеры (v1.23+) поддерживают полноценный Dual Stack.

**Настройка кластера (kubeadm):**

```yaml
# kubeadm-config.yaml
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
networking:
  podSubnet: "10.244.0.0/16,2001:db8:1::/48"  # dual-stack pod CIDR
  serviceSubnet: "10.96.0.0/16,2001:db8:2::/112"  # dual-stack service CIDR
```

**Спецификация Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  ipFamilyPolicy: PreferDualStack   # или RequireDualStack
  ipFamilies:
    - IPv4
    - IPv6
  type: LoadBalancer
  ports:
    - port: 80
      targetPort: 8080
```

**Поведение:**

| Режим | Описание |
| :--- | :--- |
| `PreferDualStack` | Пытается выделить оба ClusterIP; работает и с одним протоколом |
| `RequireDualStack` | Ошибка, если один из протоколов недоступен |
| `SingleStack` | Только один протокол (IPv4 или IPv6) |

**Проверка на узле:**

```bash
# Проверка Pod CIDR
kubectl get nodes -o jsonpath='{.items[*].spec.podCIDRs}'

# Проверка Service
kubectl get svc my-service -o jsonpath='{.spec.clusterIPs}'

# DNS: CoreDNS возвращает A и AAAA
dig +short my-service.default.svc.cluster.local  # IPv4
dig AAAA +short my-service.default.svc.cluster.local  # IPv6

# Проверка Dual Stack в NodePort
kubectl get svc -o wide  # →看看 EXTERNAL-IP/PORT для обоих семейств
```

**Pod с dual-stack:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: dual-stack-pod
spec:
  containers:
    - name: nginx
      image: nginx:latest
      ports:
        - containerPort: 80
  # K8s автоматически назначит IPv4 + IPv6 адреса, если кластер dual-stack
```

## Проблемы и риски безопасности

### Типичные атаки в Dual Stack

| Атака | Описание | Защита |
| :--- | :--- | :--- |
| **RA Spoofing** | Злоумышленник отправляет фальшивые Router Advertisement, перехватывая IPv6-трафик. Аналог ARP Spoofing в IPv4. | RA Guard (RFC 6105), IPv6 ND Inspection, `accept_ra=0` на серверах |
| **NDP Poisoning** | Фальсификация NS/NA-сообщений для перехвата трафика (аналог ARP Spoofing). | SEND (RFC 3971), RA Guard, Static NDP Entries |
| **SLAAC Attack** | Автоматическая конфигурация через RA; злоумышленник может назначить fake SLAAC-адрес. | RA Guard, `accept_ra=0`, DAI (Dynamic ARP/ND Inspection) |
| **IPv6 Extension Header Evasion** | Злоумышленник скрывает данные в Extension Headers, обходя DPI и firewalls. | Ограничение Extension Headers в firewall (nftables: `meta frag-off`), mtu-probe |
| **Happy Eyeballs Downgrade** | Принудительное отключение IPv6 заставляет OE переключиться на IPv4, где更容易 перехватить трафик (MitM). | Регулярная проверка IPv6-соединений, HSTS |
| **Туннель Hijacking (6in4, 6to4)** | Перехват туннельных соединений для перенаправления/перехвата IPv6-трафика. | IPSec для туннелей,放弃 6to4/ISATAP |
| **Dual Firewall Bypass** | Раздельные политики для iptables/ip6tables; одна из сторон может быть незащищена. | nftables с семейством `inet` (единые правила для IPv4+IPv6) |

### Рекомендуемые sysctl для Dual Stack безопасности

```bash
# IPv6: отключение автоконфигурации на серверах
net.ipv6.conf.all.accept_ra=0
net.ipv6.conf.default.accept_ra=0

# Отключение избыточных Extension Headers
net.ipv6.conf.all.accept_source_route=0
net.ipv6.conf.all.accept_redirects=0

# Защита от NDP-атак (SEND, если поддерживается)
net.ipv6.conf.all.accept_dad=1          # Duplicate Address Detection
net.ipv6.conf.all.dad_transmits=1

# Отключение IPv6 на интерфейсах, где он не нужен
net.ipv6.conf.eth1.disable_ipv6=1

# Включение forwarding (только на роутерах!)
net.ipv6.conf.all.forwarding=0

# MTU Discovery
net.ipv6.conf.all.mtu_discover=1
net.ipv6.route.mtu_expires=600
```

### Единые правила nftables (Dual Stack)

```bash
# nftables: inet-семейство для IPv4+IPv6
nft add table inet filter
nft add chain inet filter input '{ type filter hook input priority 0; policy drop; }'

# Разрешить Established/Related
nft add rule inet filter input ct state established,related accept

# Разрешить SSH (оба протокола)
nft add rule inet filter input tcp dport 22 accept

# Разрешить HTTP/HTTPS (оба протокола)
nft add rule inet filter input tcp dport {80,443} accept

# Логирование новых IPv6-соединений
nft add rule inet filter input ct state new meta nftrace set 1
```

## Дополнительная информация

### См. также

- **[Протокол IPv6: Обзор](../../../Protocols/ipv6_overview.md)** — основы адресации и ключевые отличия от IPv4.
- **[Механизмы перехода на IPv6](../../../../Linux/Networking/Settings/ipv6_configuration/concepts.md)** — NAT64/DNS64, SIT, туннелирование.
- **[Туннелирование IPv6](../../../../Linux/Networking/Settings/ipv6_configuration/tunneling.md)** — WireGuard, 6in4, MAP-E/T, DS-Lite.
- **[Firewall для IPv6](../../../../Linux/Networking/Settings/ipv6_configuration/firewall.md)** — nftables/iptables для IPv6.
- **[IPv6-поддержка в сервисах](../../../../Linux/Networking/Settings/ipv6_configuration/services_configuration.md)** — Dual Stack в приложениях и systemd.
- **[Диагностика IPv6](../../../../Linux/Networking/Settings/ipv6_configuration/diagnostics.md)** — глубокая отладка в Linux.
- **[NAT64 в практических сценариях](../../../Concepts/nat/practical_scenarios.md#технологии-перехода-на-ipv6-nat64)** — настройка Tayga/Jool.
- **[Теория NAT](../../../Concepts/nat/overview.md)** — NAT64, NPTv6, CGNAT.
- **[ICMPv6 и диагностика](../../../Protocols/ICMP/icmp_diagnostics_security.md)** — NDP, NS/NA, MLD.
- **[IPIP и SIT туннели](../../../Tunnels/ipip_and_sit.md)** — инкапсуляция IPv6-in-IPv4.
- **[SRv6](../../../Concepts/sdn/srv6.md)** — Segment Routing в IPv6.
- **[Специальные IP-адреса](../../../Protocols/IP_addressing/special_addresses.md)** — Well-Known Prefix `64:ff9b::/96` для NAT64.

### RFC

- [RFC 4291: IPv6 Addressing](https://datatracker.ietf.org/doc/html/rfc4291) — IPv4-mapped IPv6 addresses.
- [RFC 6146: Stateful NAT64](https://datatracker.ietf.org/doc/html/rfc6146) — NAT64.
- [RFC 6147: DNS64](https://datatracker.ietf.org/doc/html/rfc6147) — Синтез AAAA-записей.
- [RFC 6877: 464XLAT](https://datatracker.ietf.org/doc/html/rfc6877) — CLAT + PLAT.
- [RFC 7597: MAP-E](https://datatracker.ietf.org/doc/html/rfc7597) — Mapping of Address and Port (Encapsulation).
- [RFC 7599: MAP-T](https://datatracker.ietf.org/doc/html/rfc7599) — Mapping of Address and Port (Translation).
- [RFC 8305: Happy Eyeballs v2](https://datatracker.ietf.org/doc/html/rfc8305) — параллельный dual-stack.
- [RFC 9460: HTTPS RR](https://datatracker.ietf.org/doc/html/rfc9460) — Service Binding DNS для Happy Eyeballs v3.
