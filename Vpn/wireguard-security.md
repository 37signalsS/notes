# WireGuard: защита концентратора (anti-DDoS и hardening)

**Актуально для:** WireGuard (модуль ядра Linux 1.0.x, `wireguard-tools` 1.0.x); нативная поддержка в ядре Linux 5.6+. Протокол WireGuard v1.

## Определения

**Флуд handshake-initiation** — поток невалидных/поддельных пакетов первого сообщения рукопожатия, расходующих CPU при попытке ECDH/расшифровки. **UDP amplification** — атака с использованием чужих source-адресов (направленный ответ). **Rate limiting** — ограничение частоты/всплеска пакетов на сервисе (nftables `limit`/`meter`, iptables `hashlimit`). **Allowlist по source IP** — допуск трафика на UDP 51820 только от известных адресов.

**MAC1 (`msg.mac1`)** — обязательный первый код аутентификации сообщения рукопожатия, вычисляемый ключом, производным от статического публичного ключа получателя. Проверяется всегда; при неверном — сервер молчит. **MAC2 (`msg.mac2`)** — второй код, вычисляемый ключом-cookie; проверяется только когда узел «под нагрузкой». **Cookie** — MAC от IP:порта инициатора, вычисленный секретом сервера, который меняется каждые две минуты; служит доказательством владения IP-адресом.

**PFS (Perfect Forward Secrecy)** — свойство, при котором компрометация долговременного ключа не раскрывает прошлые сессии: сессионные ключи выводятся из эфемерных Diffie-Hellman. **Identity hiding** — свойство не раскрывать статический публичный ключ инициатора пассивному наблюдателю. **uRPF (Unicast Reverse Path Forwarding)** — проверка обратного пути; в Linux реализуется через `rp_filter`. **Reflection** — перенаправление ответа на поддельный source-адрес.

## Основные концепции

### Модель угроз для UDP-сервиса

- **Сканирование.** Порт 51820 легко обнаруживается; цель — не дать легитимным пирам «светиться» и не тратить ресурсы на мусор.
- **Флуд.** WireGuard сам по себе быстрый: пакеты от неизвестных ключей отбрасываются «дёшево», но полноценный handshake-initiation на легитимный ключ пира стоит ECDH — массовая отправка таких пакетов нагружает CPU. Полный расход на поддельные handshake при 1-2 ядрах заметен.
- **Amplification** для WireGuard **ограничен**: ответ на handshake roughly того же размера (не лавина, как в DNS/NTP). Но spoofed source способен создавать непрямую нагрузку.
- **Проба легитимности source.** WireGuard отвечает на handshake-init только пирам, чей публичный ключ есть в конфигурации, — но чтобы это понять, нужно расшифровать/узнать ключ, что уже стоит CPU. Поэтому желателен слой защиты до WireGuard (firewall).

### Встроенные механизмы защиты протокола

Часть защиты заложена в сам WireGuard — её не нужно настраивать, но важно понимать, чтобы не дублировать её бессмысленно и правильно диагностировать атаки.

- **Stealth (тишина для чужих).** Сервер не отвечает на пакеты от неизвестного ключа. Проверка `msg.mac1` (ключ производен от статического публичного ключа получателя) выполняется всегда: не зная публичного ключа, нельзя ни обнаружить сервис сканированием, ни вызвать вычисление ECDH. Это отличается от открытых UDP-сервисов, отвечающих на любой пакет.
- **Cookie-механизм под нагрузкой (`msg.mac2`).** Curve25519-умножение дорого, поэтому при большой нагрузке сервер может не обрабатывать handshake, а ответить cookie-reply (тип сообщения 3). Cookie = MAC от IP:порта инициатора секретом сервера, меняющимся каждые 2 минуты. Инициатор повторяет сообщение с корректным `msg.mac2` (MAC от сообщения, где ключ — cookie); под нагрузкой сервер принимает только сообщения с валидным `msg.mac2`. Это доказывает владение IP и позволяет применять обычный per-IP token bucket. Cookie-reply меньше handshake-сообщений (не даёт amplification) и привязан к исходному через AEAD associated data.
- **Защита от replay.** В первое сообщение закладывается метка времени TAI64N; сервер помнит наибольшую полученную метку для каждого пира и отбрасывает повторы с меткой ≤ сохранённой. Это не даёт переигранному handshake разорвать текущую сессию.
- **Криптография.** Handshake построен на Noise_IKpsk2, 1-RTT; примитивы — Curve25519, ChaCha20-Poly1305, BLAKE2s, HKDF. Сессионные ключи выводятся из эфемерных DH → **PFS**. Есть опциональный Preshared Key (PSK), добавляющий постквантовую стойкость (см. [rosenpass_overview.md](./rosenpass_overview.md)).
- **Отсутствие согласования шифров.** Набор примитивов фиксирован — нет downgrade-атак вида «выбор слабого шифра», типичных для TLS-подобного согласования.

Практический вывод: cookie-механизм защищает ядро **при уже начавшейся** нагрузке, но до его включения каждый пакет всё равно доходит до проверки `msg.mac1`. Поэтому внешний firewall (allowlist / rate limit) остаётся первым и самым дешёвым рубежом.

### Ключевые защитные приёмы

1. **IP-allowlist** на входе (для site-to-site) — лучший вариант, убивает флуд и сканирование почти полностью.
2. **Rate limiting** без allowlist (для роумингового remote access) — ограничение всплесков на UDP 51820.
3. **Минимизация поверхности**: ключи 600, закрыть debug/метрики, актуальные патчи ядра.
4. **Наблюдение**: счётчики и логи фильтра, чтобы видеть атаки.

Базовые правила firewall для WG (nftables/iptables/pf) уже описаны в [VPN Firewall Templates](../Networking/Tunnels/vpn_firewall_templates.md) — здесь только «обогащение» под DDoS/rate-limit.

### Чего WireGuard не защищает

Важно для корректной модели защиты — этих свойств у протокола нет:

- **Метаданные и трафик-анализ.** Провайдер/наблюдатель видит IP:порт обеих сторон, объём, тайминги и размеры пакетов. Шифрование скрывает содержимое, но не факт и паттерн общения. WireGuard детектируется как «равномерный шум без текста» — [vpn-dpi-obfuscation.md](./vpn-dpi-obfuscation.md).
- **Компрометация статического ключа.** Кража приватного ключа пира даёт атакующему полный доступ под этой личностью, пока ключ не отозван. Отзыв и ротация — [wireguard-key-management.md](./wireguard-key-management.md).
- **Пользовательский слой и MFA.** В WireGuard нет пользователей и второго фактора — аутентификация только по ключу. SSO/MFA реализуются внешним контроллером (Headscale/Netbird) — [vpn-authentication.md](./vpn-authentication.md).
- **Obfuscation / маскировка под TLS.** Протокол не притворяется HTTPS; для обхода DPI нужны обёртки.
- **Защита хоста.** Харденинг ядра и процесса — отдельная задача ([Kernel Hardening](../Linux/Security/Mechanisms/Kernel/hardening.md)).

## Практические сценарии

### 1. Allowlist по source IP (самый эффективный)

Подходит для site-to-site и фиксированных remote endpoints:

```bash
# nftables: только известные IP → ACCEPT, остальное → DROP
nft add rule inet filter input udp dport 51820 ip saddr { 198.51.100.0/24, 203.0.113.0/24 } accept
nft add rule inet filter input udp dport 51820 drop
```

Недостаток: роуминговые клиенты (домашние IP) ломаются — для них оставляем rate limiting (см. ниже).

### 2. Rate limiting handshake (без allowlist)

**nftables (`limit` — общий бюджет на весь сервис):**

```bash
nft add table inet filter
nft add chain inet filter input { type filter hook input priority 0 \; }
# В среднем ≤ 5 pkt/s, всплеск ≤ 10
nft add rule inet filter input udp dport 51820 limit rate 5/second burst 10 accept
nft add rule inet filter input udp dport 51820 drop
```

**nftables (`meter` — динамическая норма per-source).** В nftables нет матча `hashlimit` (это модуль iptables); его заменяет `meter` — именованный динамический set с rate limit на каждый ключ:

```bash
# per-source: у каждого источника свой token bucket (аналог iptables hashlimit)
nft add rule inet filter input udp dport 51820 \
    meter wg_src4 { ip saddr limit rate 5/second burst 10 packets } accept
nft add rule inet filter input udp dport 51820 drop
```

`meter` создаёт неявный динамический set; чтобы контролировать срок жизни и размер (защита от исчерпания памяти ротацией адресов), set задают явно с `flags dynamic, timeout`. Тело set передавайте в кавычках — иначе shell трактует `;` и `,`:

```bash
# Явный ограниченный set: элементы «остывают», размер ограничен
# (тело в одинарных кавычках — иначе shell съедает ; и ,)
nft add set inet filter wg_src4 '{ type ipv4_addr; flags dynamic, timeout; timeout 5m; size 65535; }'
nft add rule inet filter input udp dport 51820 \
    update @wg_src4 { ip saddr limit rate 5/second burst 10 packets } accept
nft add rule inet filter input udp dport 51820 drop
```

**iptables-аналог (`limit` — общий бюджет; `hashlimit` — per-source):**

```bash
# iptables: общий предел
iptables -A INPUT -p udp --dport 51820 -m limit --limit 5/s --limit-burst 10 -j ACCEPT
iptables -A INPUT -p udp --dport 51820 -j DROP

# iptables: per-source (аналог nftables meter)
iptables -A INPUT -p udp --dport 51820 -m hashlimit \
    --hashlimit-above 5/s --hashlimit-burst 10 --hashlimit-mode srcip \
    --hashlimit-name wg_src -j DROP
```

Норма подбирается так, чтобы пропускать легитимный Periodic keepalive (25 c) и handshake при переподключении (rekey каждые ~120 c), но отсекать флуд. Слишком жёсткий лимит ломает переподключение роуминговых клиентов — начинайте с заведомо мягкого и снижайте по метрикам.

### 3. Параметры ядра и hardening процесса

```bash
# Защита от spoofed source при включённом форвардинге
sudo sysctl -w net.ipv4.conf.all.rp_filter=1
sudo sysctl -w net.ipv4.conf.wg0.accept_redirects=0
sudo sysctl -w net.ipv4.conf.wg0.send_redirects=0

# Права на ключи — только root
sudo chmod 600 /etc/wireguard/private.key
sudo chattr +i /etc/wireguard/private.key   # защита от удаления/перезаписи
```

`rp_filter=1` — строгий режим (отбрасывает пакет, если обратный маршрут не через тот же интерфейс). При асимметричной маршрутизации или policy routing на концентраторе строгий режим **ломает** легитимный трафик — тогда ставят `rp_filter=2` (loose). Детали и общий набор sysctl — [network hardening](../Linux/Networking/Security/network_hardening.md).

`chattr +i` делает файл неизменяемым, что мешает ротации ключей и пересборке конфигурации через `wg-quick` (см. граничные случаи ниже) — применять там, где ротация выполняется явным снятием атрибута.

Общий hardening ядра (KASLR, защиты) — [Kernel Hardening](../Linux/Security/Mechanisms/Kernel/hardening.md).

### 4. Наблюдение и логирование атак

```bash
# Счётчики, сбрасываются при показе
nft list ruleset | grep 51820
# → ... counter packets 12345 bytes 123456 drop

# iptables-лог (после DROP-правил): запись в dmesg
iptables -A INPUT -p udp --dport 51820 -j LOG --log-prefix "WG:drop " --log-level 4

# Проверка слушающих сокетов и «хвост» ядра
ss -lun 'sport = :51820'
dmesg -T | grep -i "WG:drop" | tail

# Сводка по UDP-ошибкам (в т.ч. переполнение буфера сокета)
nstat -az | grep -i udp
# → UdpInErrors / UdpRcvbufErrors растут при флуде

# Возраст handshake у пиров (epoch; если не обновляется — связи нет)
wg show all latest-handshakes
```

Для алертинга важнее не «сырой» счётчик дропов, а **рост CPU в softirq** на пассивном узле и **прогресс handshake**: всплеск дропов при стабильных handshake — фон/сканер, рост дропов вместе с деградацией handshake — реальная атака. Полный набор метрик и экспорт в Prometheus — [vpn-monitoring.md](./vpn-monitoring.md); аудит вошедших сессий — [vpn-session-audit.md](./vpn-session-audit.md).

### 5. Защита от спуфинга и исчерпания ресурсов

```bash
# Отбрасывать «марсианские» source-адреса (bogon) на внешнем интерфейсе
# и включать форвардинг только при необходимости
sudo sysctl -w net.ipv4.ip_forward=1

# nftables: пример отсечения приватных source с публичного интерфейса
nft add rule inet filter input iifname "eth0" ip saddr 10.0.0.0/8 drop
nft add rule inet filter input iifname "eth0" ip saddr 192.168.0.0/16 drop

# Одновременное отслеживание UDP-потоков: следить за таблицей conntrack
sudo sysctl -w net.netfilter.nf_conntrack_max=262144
conntrack -C            # текущее число записей
```

WireGuard не зависит от conntrack для работы, но при использовании stateful-правил (`ct state`) таблица может заполниться под флудом — тогда sysctl и мониторинг `nf_conntrack_count` обязательны.

### 6. Что НЕ работает и почему

- **fail2ban** для UDP bidirectionless не имеет смысла: stateless UDP без установки сессий, фильтрация по `--reject` здесь не применима; DROP+rate limit решают задачу проще.
- **Port knocking** — добавление сложности без серьёзного выигрыша для скрытого UDP-сервиса; лучше закрыть за allowlist/VPN-to-VPN.
- **Ограничение «до 51820 только с интерфейса WAN»** — верное, но не защищает от spoof source → сочетать с rate limit.

### 7. Чек-лист для продакшена

- [ ] UDP 51820 доступен только с доверенных подсетей либо rate-limited
- [ ] allowlist для site-to-site, rate limit для remote access
- [ ] правила продублированы для IPv6, если используется dual-stack ([vpn-ipv6.md](./vpn-ipv6.md))
- [ ] ключи: 600, `chattr +i`, бэкап в [Vault](../Vault/overview.md)
- [ ] rp_filter выставлен под маршрутизацию (1 — строгая, 2 — при асимметрии)
- [ ] мониторинг дропов и handshake-возраст (см. [Vpn/vpn-monitoring.md](./vpn-monitoring.md))
- [ ] HA-шлюз защищён так же (VIP не открывается наружу без тех же правил)

## Диагностика и типичные ошибки

| Симптом | Причина | Диагностика / решение |
|---------|---------|-----------------------|
| Клиенты не подключаются после включения allowlist | Роуминговый клиент со сменой IP не попал в allowlist | Для таких клиентов убрать allowlist, оставить rate limiting |
| Легитимные переподключения отбиваются | Слишком жёсткий rate limit (ниже keepalive/rekey) | Поднять `rate`/`burst`; ориентир — keepalive 25 c |
| Пакеты от клиента не доходят, в `dmesg` — дропы | Строгий `rp_filter=1` при асимметричной маршрутизации | Переключить на `rp_filter=2` (loose) или исправить маршруты |
| `wg show` handshake не обновляется, CPU в softirq высок | Флуд поддельных handshake-init | Смотреть счётчики nftables, `nstat -az` (UdpInErrors); включить rate limit/allowlist |
| Пакеты теряются на крупных передачах | MTU/MSS, а не security-фильтр | Проверить MTU 1420 и MSS clamping ([wireguard.md](./wireguard.md)) |
| Ротация ключа «не работает», ошибка записи | Ключ под `chattr +i` | Снять атрибут: `chattr -i /etc/wireguard/private.key` |
| conntrack переполняется, дропы «established» | `nf_conntrack_max` исчерпан под флудом | Поднять лимит, сократить таймауты, не использовать `ct` без нужды |
| Нормальный трафик дропается «марсианскими» правилами | bogon-фильтр ловит легитимный RFC1918 source | Уточнить, с какого интерфейса приходит трафик; правило — только на WAN |

## Лучшие практики

1. **Порядок рубежей:** внешний firewall (allowlist/rate limit) → встроенная криптозащита WireGuard (stealth/cookie) → харденинг ядра и процесса → мониторинг. Не полагайтесь только на cookie-механизм: он включается под нагрузкой, то есть уже после того, как трафик дошёл до узла.
2. **Allowlist для фиксированных пиров, rate limit для роуминга** — не смешивайте их вслепую, иначе сломаете мобильные клиенты.
3. **Stealth по умолчанию:** не публикуйте порт и endpoint; смена порта с 51820 снижает шум сканеров (но это обфускация, а не безопасность).
4. **Минимальные `AllowedIPs`.** На сервере не задавайте `0.0.0.0/0` для site-to-site — это риск перехвата маршрутов, а не только производительности.
5. **Мониторинг handshake и дропов**, а не только номинальный «порт закрыт» — детектируйте деградацию до того, как упадёт сервис.
6. **Ротация и резервное хранение ключей**: 600, бэкап в [Vault](../Vault/overview.md), регламент ротации ([wireguard-key-management.md](./wireguard-key-management.md)).
7. **Держите ядро и wireguard-tools в актуальном состоянии**; предпочитайте ядерный модуль userspace-реализации (меньше CPU → устойчивее к флуду, [wireguard-performance.md](./wireguard-performance.md)).
8. **Применяйте одинаковые правила на всех узлах контура**, включая резервный шлюз HA ([wireguard-ha.md](./wireguard-ha.md)).

## Граничные случаи и ограничения

- **`chattr +i` и ротация.** Неизменяемый файл ключа блокирует легитимную ротацию и `wg-quick` с `SaveConfig`; снимайте атрибут явной процедурой.
- **`rp_filter` vs асимметрия.** Строгий режим безопаснее, но несовместим с policy routing и асимметричными путями; для концентратора чаще корректнее loose (2).
- **userspace-реализация слабее к выгоранию CPU.** `wireguard-go`/`wireguard-nt` медленнее ядерного модуля — при флуде деградирует раньше; там важнее внешний rate limit.
- **Cookie-механизм автоматический.** В ядерном модуле нет «ручки» для принудительного включения cookie-reply; он активируется под нагрузкой сам.
- **Amplification ограничен, но не нулевой.** Ответ на handshake сравним по размеру; полной защиты от reflection нет.
- **IPv6 фильтруется отдельно.** Allowlist/rate-limit на IPv4 не покрывает IPv6; при dual-stack продублируйте правила ([vpn-ipv6.md](./vpn-ipv6.md)).
- **Метрики атаки косвенны.** Ядерный WireGuard не отдаёт счётчик cookie-reply; о флуде судят по счётчикам firewall, `nstat` и загрузке softirq.

## Дополнительная информация

- **[WireGuard — основное руководство](./wireguard.md)** — конфигурация, AllowedIPs, MTU, базовые меры безопасности
- **[VPN Firewall Templates](../Networking/Tunnels/vpn_firewall_templates.md)** — базовые правила входа/форвардинга/NAT для WireGuard
- **[WireGuard — управление ключами](./wireguard-key-management.md)** — ротация, отзыв, флот клиентов, хранение в Vault
- **[Rosenpass](./rosenpass_overview.md)** — постквантовый обмен ключами поверх WireGuard
- **[VPN под DPI](./vpn-dpi-obfuscation.md)** — детектируемость и обфускация трафика
- **[Vpn/vpn-monitoring.md](./vpn-monitoring.md)** — алерты по флуду/падению пиров, счётчики дропов в Grafana
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — аудит подключений и сессий
- **[Vpn/vpn-authentication.md](./vpn-authentication.md)** — SSO/MFA и пользовательский слой поверх WireGuard
- **[WireGuard — производительность](./wireguard-performance.md)** — kernel vs userspace, RSS/RPS, тюнинг под нагрузкой
- **[WireGuard — HA](./wireguard-ha.md)** — высокая доступность концентратора
- **[Kernel Hardening](../Linux/Security/Mechanisms/Kernel/hardening.md)** — системные меры защиты хоста концентратора
- **[network hardening](../Linux/Networking/Security/network_hardening.md)** — sysctl, rp_filter, conntrack
