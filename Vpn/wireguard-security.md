# WireGuard: защита концентратора (anti-DDoS и hardening)

## Определения

**Флуд handshake-initiation** — поток невалидных/поддельных пакетов первого сообщения рукопожатия, расходующих CPU при попытке ECDH/расшифровки. **UDP amplification** — атака с использованием чужих source-адресов (направленный ответ). **Rate limiting** — ограничение частоты/всплеска пакетов на сервисе (nftables `limit`/`hashlimit`, iptables `limit`). **Allowlist по source IP** — допуск трафика на UDP 51820 только от известных адресов.

## Основные концепции

### Модель угроз для UDP-сервиса

- **Сканирование.** Порт 51820 легко обнаруживается; цель — не дать легитимным пирам «светиться» и не тратить ресурсы на мусор.
- **Флуд.** WireGuard сам по себе быстрый: пакеты от неизвестных ключей отбрасываются «дёшево», но полноценный handshake-initiation на легитимный ключ пира стоит ECDH — массовая отправка таких пакетов нагружает CPU. Полный расход на поддельные handshake при 1-2 ядрах заметен.
- **Amplification** для WireGuard **ограничен**: ответ на handshake roughly того же размера (не лавина, как в DNS/NTP). Но spoofed source способен создавать непрямую нагрузку.
- **Проба легитимности source.** WireGuard отвечает на handshake-init только пирам, чей публичный ключ есть в конфигурации, — но чтобы это понять, нужно расшифровать/узнать ключ, что уже стоит CPU. Поэтому желателен слой защиты до WireGuard (firewall).

### Ключевые защитные приёмы

1. **IP-allowlist** на входе (для site-to-site) — лучший вариант, убивает флуд и сканирование почти полностью.
2. **Rate limiting** без allowlist (для роумингового remote access) — ограничение всплесков на UDP 51820.
3. **Минимизация поверхности**: ключи 600, закрыть debug/метрики, актуальные патчи ядра.
4. **Наблюдение**: счётчики и логи фильтра, чтобы видеть атаки.

Базовые правила firewall для WG (nftables/iptables/pf) уже описаны в [VPN Firewall Templates](../Networking/Tunnels/vpn_firewall_templates.md) — здесь только «обогащение» под DDoS/rate-limit.

## Практические сценарии

### 1. Allowlist по source IP (самый эффективный)

Подходит для site-to-site и фиксированных remote endpoints:

```bash
# nftables: только известные IP → ACCEPT, остальное → DROP
nft add rule inet filter input udp dport 51820 ip saddr { 198.51.100.0/24, 203.113.0.0/24 } accept
nft add rule inet filter input udp dport 51820 drop
```

Недостаток: роуминговые клиенты (домашние IP) ломаются — для них оставляем rate limiting (см. ниже).

### 2. Rate limiting handshake (без allowlist)

**nftables (`limit` — общий бюджет):**

```bash
nft add table inet filter
nft add chain inet filter input { type filter hook input priority 0 \; }
# В среднем ≤ 5 pkt/s, всплеск ≤ 10
nft add rule inet filter udp dport 51820 limit rate 5/second burst 10 accept
nft add rule inet filter udp dport 51820 drop
```

**nftables (`hashlimit` — per-source динамическая норма):**

```bash
# Новая цепочка для отслеживания по установленным пирам
nft add chain inet filter wg_ratelimit { type filter hook input priority -10 \; }
nft add rule inet filter wg_ratelimit udp dport 51820 \
    ct state new accept comment "established traffic is asymmetric, allow new"
nft add rule inet filter wg_ratelimit udp dport 51820 \
    hashlimit name wg_new hashlimit 5/second per-src burst 10 accept
nft add rule inet filter wg_ratelimit udp dport 51820 counter drop
```

**iptables-аналог (`limit`):**

```bash
iptables -A INPUT -p udp --dport 51820 -m limit --limit 5/s --limit-burst 10 -j ACCEPT
iptables -A INPUT -p udp --dport 51820 -j DROP
```

Такая норма пропускает легитимный Periodic keepalive (25 c) и handshake при переподключении, но отсекает флуд.

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

Общий hardening ядра (KASLR, защиты) — [Kernel Hardening](../Linux/Security/Mechanisms/Kernel/hardening.md), [network hardening](../Linux/Networking/Security/network_hardening.md).

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
```

### 5. Что НЕ работает и почему

- **fail2ban** для UDP bidirectionless не имеет смысла: stateless UDP без установки сессий, фильтрация по `--reject` здесь не применима; DROP+rate limit решают задачу проще.
- **Port knocking** — добавление сложности без серьёзного выигрыша для скрытого UDP-сервиса; лучше закрыть за allowlist/VPN-to-VPN.
- **Ограничение «до 51820 только с интерфейса WAN»** — верное, но не защищает от spoof source → сочетать с rate limit.

### 6. Чек-лист для продакшена

- [ ] UDP 51820 доступен только с доверенных подсетей либо rate-limited
- [ ] allowlist для site-to-site, rate limit для remote access
- [ ] ключи: 600, `chattr +i`, бэкап в [Vault](../Vault/overview.md)
- [ ] rp_filter включён, конфиденциальные sysctl применены
- [ ] мониторинг дропов и handshake-возраст (см. [Vpn/vpn-monitoring.md](./vpn-monitoring.md))
- [ ] HA-шлюз защищён так же (VIP не открывается наружу без тех же правил)

## Дополнительная информация

- **[VPN Firewall Templates](../Networking/Tunnels/vpn_firewall_templates.md)** — базовые правила входа/форвардинга/NAT для WireGuard
- **[Kernel Hardening](../Linux/Security/Mechanisms/Kernel/hardening.md)** — системные меры защиты хоста концентратора
- **[Vpn/vpn-monitoring.md](./vpn-monitoring.md)** — алерты по флуду/падению пиров, счётчики дропов в Grafana