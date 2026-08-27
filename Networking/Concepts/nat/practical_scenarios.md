# NAT — Практические сценарии

## Предварительные требования

Для работы с NAT в Linux необходимы:

*   **Root-доступ** или права `sudo` для изменения правил netfilter.
*   **Два сетевых интерфейса** (или более): внутренний (LAN) и внешний (WAN). Сценарии ниже используют `eth0` (внешний) и `eth1` (внутренний) — подставьте свои интерфейсы.
*   **Пакеты управления:** `iptables` / `nftables`, `conntrack-tools` (для диагностики), `ip` (для управления интерфейсами).
    ```bash
    # Debian/Ubuntu
    sudo apt install iptables nftables conntrack iproute2

    # RHEL/CentOS/Fedora
    sudo dnf install iptables nftables conntrack-tools iproute
    ```
*   **Включенный IP-forwarding:** Все сценарии NAT требуют `net.ipv4.ip_forward=1`. См. шаг 1 в разделе [Настройка NAT (Маскарадинг) в Linux](#настройка-nat-маскарадинг-в-linux).

## MASQUERADE vs SNAT: когда что использовать

| Критерий | MASQUERADE | SNAT (--to-source) |
| :--- | :--- | :--- |
| **IP-адрес интерфейса** | Динамический (DHCP, PPPoE) | Статический публичный IP |
| **Производительность** | Чуть ниже (проверка IP интерфейса на каждый пакет) | Выше (IP зашит в правило) |
| **Сценарий** | Домашний роутер, мобильный интернет | Сервер с несколькими статическими IP |
| **Conntrack** | Запись обновляется при смене IP интерфейса | Статичная запись |

**Правило:** Если IP-адрес внешнего интерфейса статический — используйте `SNAT`. Если динамический — `MASQUERADE`.

## Настройка NAT (Маскарадинг) в Linux

### Вариант 1: Firewalld (CentOS/RHEL/Fedora)

1. **Включить IP Forwarding:**

    ```bash
    # Постоянно через sysctl
    echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-router.conf
    sudo sysctl --system
    ```

2. **Настроить Masquerading:**

    ```bash
    # Перевести внешний интерфейс в зону external (маскарадинг включен по умолчанию)
    firewall-cmd --zone=external --change-interface=eth0 --permanent

    # Или включить маскарадинг в текущей зоне
    firewall-cmd --zone=public --add-masquerade --permanent

    firewall-cmd --reload
    ```

### Вариант 2: Nftables (Современный стандарт)

```bash
# Создание таблицы nat
nft add table ip nat

# Добавление цепочки POSTROUTING
nft add chain ip nat postrouting { type nat hook postrouting priority 100 \; }

# Включение маскарадинга для интерфейса eth0
nft add rule ip nat postrouting oifname "eth0" masquerade
```

### Вариант 3: Iptables (Legacy)

```bash
# Включение маскарадинга для всех исходящих через eth0
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
```

### Вариант 4: Netplan (Ubuntu/Debian)

Для настройки NAT через Netplan (используя `systemd-networkd`) необходимо разрешить форвардинг на интерфейсе:

```yaml
network:
  version: 2
  ethernets:
    eth1: # Внутренний интерфейс
      addresses: [192.168.1.1/24]
    eth0: # Внешний интерфейс
      dhcp4: true
      routing-policy:
        - from: 192.168.1.0/24
          table: 100
```
*Примечание: Netplan сам не настраивает правила iptables/nftables для NAT, это нужно делать через `nftables` или `iptables` отдельно.*

### Вариант 5: systemd-networkd

Настройка IP-маскарадинга на уровне юнита интерфейса (требует `IPMasquerade=yes`):

```ini
# /etc/systemd/network/eth0.network
[Match]
Name=eth0

[Network]
DHCP=yes
IPForward=yes
IPMasquerade=yes
```

---

## Статический Source NAT (SNAT)

Используется, когда у сервера есть несколько статических публичных IP и нужно, чтобы определенный внутренний хост выходил в интернет с конкретного адреса.

### Базовый SNAT

```bash
# Iptables: все из локальной сети 192.168.1.0/24 выходят через IP 203.0.113.10
iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -o eth0 -j SNAT --to-source 203.0.113.10

# Nftables:
nft add rule ip nat postrouting ip saddr 192.168.1.0/24 oifname "eth0" snat to 203.0.113.10
```

### SNAT с диапазоном портов (Port-Dependent SNAT)

При большом количестве одновременных соединений за одним NAT-шлюзом может возникнуть Port Exhaustion. SNAT с диапазоном портов распределяет соединения по нескольким портам:

```bash
# Iptables: трафик от 192.168.1.0/24 транслируется в 203.0.113.10 с портов 10000-20000
iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -o eth0 -j SNAT \
  --to-source 203.0.113.10:10000-20000

# Nftables:
nft add rule ip nat postrouting ip saddr 192.168.1.0/24 oifname "eth0" \
  snat to 203.0.113.10:10000-20000
```

**Порядок назначения портов:** Conntrack пытается сохранить один и тот же порт для одной и той же пары src:dst (pnat pinning). Если порт уже занят — выбирается следующий свободный из диапазона. Это обеспечивает предсказуемость для сервисов, которые запоминают порт источника (некоторые протоколы и файрволы).

### Multi-NAT: несколько внешних IP

Для распределения трафика по нескольким внешним IP используется цепочка правил:

```bash
# Группа A (серверы) — через 203.0.113.10
iptables -t nat -A POSTROUTING -s 192.168.1.10/32 -o eth0 -j SNAT --to-source 203.0.113.10

# Группа B (рабочие станции) — через 203.0.113.11
iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -o eth0 -j SNAT --to-source 203.0.113.11

# Все остальные — через 203.0.113.12 (MASQUERADE как fallback)
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
```

**Важно:** Порядок правил имеет значение — более специфичные правила (с `/32`) должны идти раньше общих.

### Проверка SNAT

```bash
# Снаружи: проверить, с какого IP идёт трафик от внутреннего хоста
# (выполнить с внешнего сервера)
sudo tcpdump -i eth0 src host 192.168.1.10
# → Должен показать source IP = 203.0.113.10 (транслированный)

# На шлюзе: убедиться, что conntrack-запись существует
conntrack -L -s 192.168.1.10
# → tcp  6 431999 ESTABLISHED src=192.168.1.10 dst=8.8.8.8 sport=54321 dport=443 src=8.8.8.8 dst=203.0.113.10 sport=443 dport=54321 [ASSURED]
```

### Сохранение правил (перезагрузка)

Правила iptables/nftables не сохраняются автоматически при перезагрузке:

```bash
# Iptables (Debian/Ubuntu):
sudo apt install iptables-persistent
sudo netfilter-persistent save

# Iptables (RHEL/CentOS):
sudo service iptables save

# Nftables:
sudo nft list ruleset | sudo tee /etc/nftables.conf
# При загрузке: nft -f /etc/nftables.conf
```

---

## Проброс портов (Destination NAT / DNAT)

**DNAT** используется для предоставления доступа к внутренним сервисам из внешней сети. Механизм DNAT заменяет адрес назначения в заголовке пакета до того, как ядро примет решение о маршрутизации.

**Важно:** DNAT применяется в цепочке `PREROUTING` (до маршрутизации), что означает правило должно сработать до того, как пакет будет доставлен на локальный интерфейс. Если DNAT нацелен на сервис, работающий на самом NAT-шлюзе — используется `REDIRECT` (в таблице nat) или `DNAT` на `127.0.0.1`.

### Пример: Веб-сервер за NAT
Внешний порт `8080` -> Внутренний IP `192.168.1.10:80`.

**Через firewalld:**
```bash
firewall-cmd --permanent --zone=external --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=192.168.1.10
firewall-cmd --reload
```

**Через nftables:**
```bash
nft add rule ip nat prerouting iifname "eth0" tcp dport 8080 dnat to 192.168.1.10:80
```

**Через iptables:**
```bash
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 8080 -j DNAT --to-destination 192.168.1.10:80
```

### DNAT для нескольких бэкендов (Round-Robin балансировка)

При наличии нескольких серверов одного сервиса можно реализовать простую балансировку на уровне NAT. Правила обрабатываются последовательно, поэтому реализуется round-robin (без учёта нагрузки):

```bash
# Пример: три backend-сервера для HTTPS
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 443 \
  -m statistic --mode nth --every 3 --packet 0 \
  -j DNAT --to-destination 192.168.1.11:443

iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 443 \
  -m statistic --mode nth --every 2 --packet 0 \
  -j DNAT --to-destination 192.168.1.12:443

iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 443 \
  -j DNAT --to-destination 192.168.1.13:443
```

**Nftables-эквивалент:**
```bash
table ip nat {
    set backends {
        type ipv4_addr
        flags interval
        elements = { 192.168.1.11, 192.168.1.12, 192.168.1.13 }
    }
}
nft add rule ip nat prerouting iifname "eth0" tcp dport 443 \
  dnat to numgen inc mod 3 map @backends
```

**Примечание:** Это балансировка уровня 4 (по IP:port), без учёта состояния здоровья бэкендов. Для production-использования рекомендуется NGINX/HAProxy или MetalLB в Kubernetes.

### DNAT с сохранением original destination (только iptables)

При DNAT часто необходимо знать реальный IP-адрес, с которого пришёл клиент (для логирования, анализа). В conntrack это поле доступно через `--original-destination`:

```bash
# Логирование DNAT-трансляций
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 443 \
  -j DNAT --to-destination 192.168.1.10:443

# Логирование (в таблице nat, до DNAT):
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 443 \
  -j LOG --log-prefix "DNAT-443: " --log-level 4
```

### Проверка DNAT

```bash
# Снаружи: проверить, что порт 8080 доступен и перенаправляется
curl -v http://<публичный_IP_шлюза>:8080
# → Должен получить ответ от веб-сервера 192.168.1.10:80

# На шлюзе: проверить conntrack-запись
conntrack -L -p tcp --dport 80
# → Должна показать трансляцию dst: 192.168.1.10:80

# Через tcpdump на внутреннем интерфейсе:
sudo tcpdump -i eth1 port 80
# → Пакеты должны приходить с destination IP = 192.168.1.10 (транслированный)
```

### Типичные ошибки DNAT

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Соединение устанавливается, но данные не приходят | Сервер отвечает напрямую клиенту, минуя NAT-шлюз | Добавить SNAT (Hairpin NAT) или `rp_filter=0` на сервере |
| Timeout при обращении к порту | DNAT-правило не совпадает (неправильный интерфейс, протокол) | `iptables -t nat -L -v -n` — проверить счётчики |
| Работает через 1-2 минуты после добавления правила | Conntrack кэширует старое состояние | `conntrack -D -p tcp --dport 80` — сбросить запись |
| Сервис работает изнутри, но не снаружи | Не включён IP-forwarding | `sysctl net.ipv4.ip_forward` должен быть `1` |

**См. также:** Детальный разбор прохождения пакета с DNAT/SNAT в инфраструктуре Docker — **[Packet Flow в Docker Bridge](../../../Docker/Docker_network/drivers/bridge.md#жизненный-цикл-пакета-packet-flow)**.

---

## Настройка Hairpin NAT (Loopback NAT)

**Проблема:** Внутренний клиент обращается к внутреннему серверу по **публичному** IP-адресу маршрутизатора. Без Hairpin NAT пакет уйдет на сервер, но сервер ответит клиенту напрямую (так как они в одной подсети), и клиент сбросит соединение, так как ждал ответа от публичного IP.

**Как это работает:**
1. Клиент (192.168.1.5) отправляет пакет на публичный IP (203.0.113.1) — DNAT цепочка.
2. DNAT меняет destination на 192.168.1.10:80.
3. Пакет попадает на сервер 192.168.1.10.
4. Сервер отвечает клиенту (192.168.1.5) напрямую — **без SNAT** клиент отбрасывает пакет (ждал ответа от 203.0.113.1).
5. **SNAT (Hairpin)** заставляет ответ сервера пройти через NAT-шлюз, чтобы был выполнен обратный DNAT.

### Полная настройка Hairpin NAT (Iptables)

```bash
# 1. DNAT для публичного IP (обычный проброс порта)
iptables -t nat -A PREROUTING -i eth0 -p tcp -d 203.0.113.1 --dport 80 \
  -j DNAT --to-destination 192.168.1.10:80

# 2. SNAT (Hairpin) для внутренних клиентов, обращающихся к серверу по LAN
iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -d 192.168.1.10 -p tcp --dport 80 \
  -j MASQUERADE
```

### Полная настройка Hairpin NAT (Nftables)

```bash
table ip nat {
    chain prerouting {
        type nat hook prerouting priority -100;
        # DNAT для публичного IP
        iifname "eth0" tcp dport 80 dnat to 192.168.1.10:80
    }

    chain postrouting {
        type nat hook postrouting priority 100;
        # Hairpin SNAT для внутренних клиентов
        ip saddr 192.168.1.0/24 ip daddr 192.168.1.10 tcp dport 80 masquerade
    }
}
```

### Проверка Hairpin NAT

```bash
# С внутреннего хоста:
curl http://203.0.113.1
# → Должен получить ответ от 192.168.1.10:80

# На шлюзе: проверить conntrack-запись (должны быть и DNAT, и SNAT)
conntrack -L -p tcp -d 192.168.1.10
# → Должен показать ответный пакет с source = 203.0.113.1 (SNAT)
```

---

## Проброс SSH через сетевой уровень (NAT-L3)

Сценарий: Доступ к серверу B (внутренний) через сервер A (шлюз) без использования SSH-туннелей (ProxyJump) или VPN.

**На сервере A (шлюз):**

1. **DNAT (проброс порта):**
   ```bash
   iptables -t nat -A PREROUTING -p tcp --dport 2222 -j DNAT --to-destination 192.168.1.20:22
   ```

2. **SNAT (маскировка источника, чтобы ответ шел через шлюз):**
   ```bash
   iptables -t nat -A POSTROUTING -d 192.168.1.20 -p tcp --dport 22 -j MASQUERADE
   ```

**Подключение:**
```bash
ssh -p 2222 user@203.0.113.1
# → Подключается к серверу B (192.168.1.20) через NAT-шлюз
```

**Важно:** SNAT здесь необходим, иначе сервер B ответит клиенту напрямую (минуя шлюз), и SSH-соединение разорвётся.

---

## NAT в облачных инфраструктурах

### Yandex Cloud: NAT Gateway

В Yandex Cloud классический NAT на ВМ (Egress NAT) считается устаревшим. Рекомендуется использовать **NAT Gateway**.

```bash
# Создание шлюза
yc vpc gateway create --name nat-gw

# Создание таблицы маршрутов
yc vpc route-table create --name rt-nat --network-name main-net

# Добавление статического маршрута через NAT Gateway
yc vpc route-table static-route create \
  --route-table-name rt-nat \
  --destination 0.0.0.0/0 \
  --gateway-name nat-gw

# Привязка таблицы к подсети
yc vpc subnet update --name private-subnet --route-table-name rt-nat
```

### AWS: NAT Gateway

В AWS NAT Gateway создается в публичной подсети для обеспечения выхода приватных подсетей в интернет.

```bash
# Пример через AWS CLI (упрощенно)
aws ec2 create-nat-gateway --subnet-id subnet-12345 --allocation-id eipalloc-12345
```

### Kubernetes: IP Masquerade Agent

В K8s используется для маскировки трафика подов при выходе за пределы кластера или в специфичные CIDR.

```yaml
# Пример ConfigMap для ip-masq-agent
apiVersion: v1
kind: ConfigMap
metadata:
  name: ip-masq-agent
  namespace: kube-system
data:
  config: |
    nonMasqueradeCIDRs:
      - 10.0.0.0/8
    masqLinkLocal: false
```

---

## Технологии перехода на IPv6 (NAT64)

В средах IPv6-only используется NAT64 для доступа к IPv4-интернету. Популярное решение — **Tayga**.

**Алгоритм работы:**
1. DNS64 синтезирует AAAA-запись из A-записи, используя префикс (например, `64:ff9b::/96`).
2. Клиент отправляет IPv6 пакет на этот адрес.
3. Tayga перехватывает пакет и транслирует его в IPv4.

**Пример конфигурации Tayga (`/etc/tayga.conf`):**
```ini
tun-device nat64
ipv4-addr 192.168.255.1
prefix 64:ff9b::/96
dynamic-pool 192.168.255.0/24
```

---

## Диагностика и отладка NAT

### Проверка таблицы трансляций (Conntrack)

`conntrack` — основной инструмент для анализа состояния NAT.

```bash
# Просмотр всех активных трансляций
sudo conntrack -L
# → Example output:
# tcp  6 431999 ESTABLISHED src=192.168.1.10 dst=8.8.8.8 sport=54321 dport=443 src=8.8.8.8 dst=203.0.113.1 sport=443 dport=33456 [ASSURED] mark=0 use=2

# Просмотр трансляций только для конкретного протокола
sudo conntrack -L -p tcp

# Просмотр трансляций для конкретного внутреннего IP
sudo conntrack -L -s 192.168.1.10

# Просмотр трансляций с NAT-полями (показывает destination/original address)
sudo conntrack -L -p tcp --any-nat

# Удаление всех трансляций для конкретного IP (полезно при смене правил)
sudo conntrack -D -s 192.168.1.10

# Удаление всех трансляций для конкретного порта (после изменения DNAT-правила)
sudo conntrack -D -p tcp --dport 80

# Статистика conntrack (количество сессий, лимиты, ошибки)
sudo conntrack -S
# → entries 456, ignore 0, insert_failed 12, drop 0, early_drop 0, error 0, search_restart 2345
```

**Важные поля вывода conntrack:**
- `ASSURED` — соединение полностью установлено (получен ответ). Записи без `ASSURED` удаляются первыми при переполнении таблицы.
- `[ASSURED]` и `mark=0` — метка (mark) используется для идентификации соединений в iptables/nftables.

### Мониторинг трансляций в реальном времени

`conntrack -E` показывает события NAT в реальном времени — полезно для отладки проблемных соединений:

```bash
# Мониторинг всех событий NAT
sudo conntrack -E

# Мониторинг только для TCP-портов 80/443
sudo conntrack -E -p tcp --dport 80
# → [NEW]    tcp  6 30 SYN_SENT src=192.168.1.10 dst=93.184.216.34 sport=43210 dport=80
# → [UPDATE] tcp  6 60 SYN_RECV src=192.168.1.10 dst=93.184.216.34 sport=43210 dport=80
# → [UPDATE] tcp  6 432000 ESTABLISHED src=192.168.1.10 dst=93.184.216.34 sport=43210 dport=80
# → [DESTROY] tcp  6 30 TIME_WAIT src=192.168.1.10 dst=93.184.216.34 sport=43210 dport=80
```

### Логирование NAT-трансляций

Для диагностики проблемных соединений можно включить логирование правил NAT:

```bash
# Iptables: логирование DNAT-правил
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 80 \
  -j LOG --log-prefix "NAT-DNAT-80: " --log-level 4

# Nftables: логирование через nft log
nft add rule ip nat prerouting iifname "eth0" tcp dport 80 \
  log prefix "NAT-DNAT-80: " level info

# Просмотр логов
sudo journalctl -f | grep "NAT-DNAT-80"
# или
sudo tail -f /var/log/kern.log | grep "NAT-DNAT-80"
```

**Важно:** Логирование каждого пакета создаёт значительную нагрузку на диск. Используйте только для кратковременной диагностики.

### Оптимизация Conntrack (SRE Best Practices)

При переполнении таблицы в логах `dmesg` появляется ошибка `nf_conntrack: table full, dropping packet`.

```bash
# Просмотр текущего лимита
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 262144

# Просмотр текущего количества записей
cat /proc/sys/net/netfilter/nf_conntrack_count
# → 187234

# Тюнинг таймаутов для TCP ESTABLISHED (стандартно 5 дней, часто снижают до 1 часа)
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600

# Увеличение максимального размера таблицы (пример: 1M записей)
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576

# Увеличение размера хеш-таблицы (рекомендуется NF_CONNTRACK_MAX / 4)
echo 262144 | sudo tee /sys/module/nf_conntrack/parameters/hashsize
```

**Постоянная настройка:**
```bash
# /etc/sysctl.d/99-conntrack.conf
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 60
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 120

# Применить:
sudo sysctl --system
```

### Обнаружение двойного NAT (Double NAT)

Если `traceroute` показывает два и более частных (RFC 1918) IP-адреса в первых прыжках — вы за двойным NAT.

```bash
traceroute -n 8.8.8.8
# 1. 192.168.1.1  (Ваш роутер)
# 2. 10.100.0.1   (NAT провайдера / CGNAT)  <-- Двойной NAT
# 3. * * *        (публичная сеть)
```

**Дополнительная проверка:**
```bash
# Сравнение внешнего IP с адресом интерфейса
ip addr show | grep "inet " | grep -v 127.0.0.1
curl -s ifconfig.me
# Если адреса отличаются — вы за NAT (возможно, за CGNAT)
```

### Верификация NAT Traversal (STUN)

```bash
# Установка клиента
sudo apt install stun-client

# Проверка типа NAT (важно для VoIP/WebRTC)
stun stun.l.google.com:19302
# → NAT Type: Restricted Cone NAT (или Full Cone, Symmetric и т.д.)
```

**interpretation результатов STUN:**
- **Full Cone NAT** — лучший для P2P (VoIP, игры, WebRTC). Любой внешний хост может ответить.
- **Restricted Cone** — ограничение по IP. Подходит для большинства приложений.
- **Port Restricted** — ограничение по IP и порту. Требует TURN для P2P.
- **Symmetric NAT** — для каждого destination создаётся новый mapping. TURN обязателен.

### Сохранение и восстановление правил NAT

```bash
# Сохранение текущих правил
sudo iptables-save > /tmp/iptables-rules-backup.txt
sudo nft list ruleset > /tmp/nftables-rules-backup.conf

# Восстановление правил
sudo iptables-restore < /tmp/iptables-rules-backup.txt
sudo nft -f /tmp/nftables-rules-backup.conf

# Автоматическое восстановление при загрузке (systemd)
# Создать юнит /etc/systemd/system/iptables-restore.service:
# [Unit]
# Description=Restore iptables rules
# Before=network-pre.target
#
# [Service]
# Type=oneshot
# ExecStart=/sbin/iptables-restore /etc/iptables/rules.v4
#
# [Install]
# WantedBy=multi-user.target
```

### Удаление правил NAT (откат изменений)

```bash
# Просмотр правил с номерами
sudo iptables -t nat -L --line-numbers

# Удаление конкретного правила по номеру
sudo iptables -t nat -D POSTROUTING 3

# Удаление конкретного правила (по содержимому)
sudo iptables -t nat -D POSTROUTING -s 192.168.1.0/24 -o eth0 -j MASQUERADE

# Очистка всей таблицы NAT (ОСТОРОЖНО!)
sudo iptables -t nat -F
sudo iptables -t nat -X
```

## Асимметричная маршрутизация и NAT

**Проблема:** Если трафик наружу идёт через один NAT-шлюз (A), а ответ возвращается через другой (B), шлюз B не найдёт conntrack-запись для ответного пакета. Результат — пакеты отбрасываются или транслируются некорректно.

```
Клиент (192.168.1.5) ──► Шлюз A (SNAT) ──► Интернет
                              │
                          conntrack запись:
                          192.168.1.5 → 203.0.113.10

Интернет ──► Шлюз B (без conntrack!) ──► Клиент
              │
              Пакет отбрасывается — нет conntrack-записи
              для 203.0.113.10 → 192.168.1.5
```

### Диагностика

```bash
# На шлюзе B: проверить, отбрасываются ли пакеты
conntrack -S | grep drop
# → drop 12345 (если > 0 — возможна асимметрия)

# Проверить rp_filter (должен быть 2 = Loose)
sysctl net.ipv4.conf.all.rp_filter
# → 1 (Strict) — проблема! Пакеты с другого интерфейса отбрасываются

# Проверить, что conntrack не видит ответные пакеты
conntrack -E -p tcp --dport 443
# → Должны быть NEW/UPDATE для исходящих; если нет — асимметрия
```

### Решения

```bash
# Решение 1: rp_filter=2 (Loose) на ВСЕХ интерфейсах
sysctl -w net.ipv4.conf.all.rp_filter=2
sysctl -w net.ipv4.conf.default.rp_filter=2

# Решение 2: Симметричная маршрутизация через policy routing
# (确保 трафик наружу и ответ идут через один шлюз)
ip rule add from 192.168.1.0/24 lookup 100
ip route add default via 10.0.0.1 table 100

# Решение 3: Conntrack bypass для асимметричного трафика
# (если симметричная маршрутизация невозможна)
iptables -t raw -A PREROUTING -p tcp --dport 443 -j NOTRACK
iptables -t raw -A OUTPUT -p tcp --sport 443 -j NOTRACK
```

**Важно:** `rp_filter=1` (Strict) — самый частый источник проблем с асимметрией. При двух NAT-шлюзах или multi-path routing всегда выставляйте `rp_filter=2`.

---

## Защита DNAT-сервисов от DDoS

При DDoS-атаке на DNAT-сервис атакующий может исчерпать ресурсы conntrack-таблицы, что приведёт к отказу в обслуживании легитимных клиентов.

### Механизмы атаки

| Тип атаки | Цель | Эффект |
| :--- | :--- | :--- |
| **SYN-флуд на DNAT-порт** | Conntrack table exhaustion | Новые соединения отбрасываются (`table full`) |
| **UDP-флуд** | Conntrack UDP timeout exhaustion | Записи UDP занимают слоты, новые TCP-сессии не помещаются |
| **Slowloris** | Conntrack ESTABLISHED timeout | Медленные соединения удерживают записи长时间 |

### Rate limiting через NAT (iptables)

```bash
# Ограничение новых соединений в секунду на DNAT-порт
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 443 \
  -m conntrack --ctstate NEW \
  -m limit --limit 100/sec --limit-burst 200 \
  -j DNAT --to-destination 192.168.1.10:443

# Ограничение по IP (не более 10 соединений с одного IP)
iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 443 \
  -m conntrack --ctstate NEW \
  -m connlimit --connlimit-above 10 --connlimit-mask 32 \
  -j DROP
```

### Rate limiting через NAT (nftables)

```bash
# Ограничение новых соединений
nft add rule ip nat prerouting iifname "eth0" tcp dport 443 \
  ct state new limit rate 100/second \
  dnat to 192.168.1.10:443

# Ограничение по IP (не более 10 соединений)
nft add rule ip nat prerouting iifname "eth0" tcp dport 443 \
  ct state new \
  ct count over 10 \
  drop
```

### SYN proxy (полная проверка handshake)

SYN proxy перехватывает TCP-рукопожатие и подтверждает владение IP-адресом до того, как пакет попадёт в стек приложения. Это защищает от SYN-флуда на DNAT-сервисе.

```bash
# Nftables: SYN proxy в таблице raw
nft add table ip raw
nft add chain ip raw prerouting { type filter hook prerouting priority -300 \; }

nft add rule ip raw prerouting tcp dport 443 \
  ct state { invalid, untracked } \
  synproxy mss 1460 wscale 7 sack-perm

# Conntrack bypass для SYN-пакетов (SYN proxy обрабатывает handshake)
nft add rule ip raw prerouting tcp dport 443 \
  tcp flags syn notrack
```

### Защита conntrack-таблицы

```bash
# Увеличение размера таблицы (первый уровень защиты)
sysctl -w net.netfilter.nf_conntrack_max=2097152

# Снижение таймаутов (быстрое освобождение слотов)
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=600
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
sysctl -w net.netfilter.nf_conntrack_udp_timeout=10
sysctl -w net.netfilter.nf_conntrack_udp_timeout_stream=30

# Мониторинг заполнения таблицы
watch -n 1 'echo "$(cat /proc/sys/net/netfilter/nf_conntrack_count)/$(cat /proc/sys/net/netfilter/nf_conntrack_max)" | bc -l'
```

---

## fail2ban на NAT-шлюзе

fail2ban на NAT-шлюзе защищает DNAT-сервисы, анализируя логи и банируя IP-адреса атакующих через iptables/nftables-правила.

### Установка и базовая настройка

```bash
sudo apt install fail2ban

# /etc/fail2ban/jail.local
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
banaction = iptables-multiport

[sshd]
enabled = true
port = ssh
logpath = /var/log/auth.log

[nginx-http-auth]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log
```

### fail2ban для DNAT-сервиса

```bash
# Фильтр для nginx (определение атакующих по IP)
# /etc/fail2ban/filter.d/nginx-limit-req.conf
[Definition]
failregex = limiting requests, excess: .* by zone .*, client: <HOST>
ignoreregex =

# Jail для DNAT-сервиса
# /etc/fail2ban/jail.d/nginx-dnat.conf
[nginx-limit-req]
enabled = true
port = http,https
filter = nginx-limit-req
logpath = /var/log/nginx/error.log
maxretry = 10
findtime = 60
bantime = 600
# Banaction: добавить правило в NAT таблицу
banaction = iptables-multiport
```

### Проверка и мониторинг

```bash
# Статус fail2ban
sudo fail2ban-client status
# →|- Filter
# │  |- Currently failed: 3
# │  |- Total failed: 1234
# │  `- File list: /var/log/auth.log
# `- Actions
#    |- Currently banned: 5
#    |- Total banned: 67
#    `- Banned IP list: 1.2.3.4 5.6.7.8 ...

# Просмотр забаненных IP
sudo iptables -L f2b-nginx-limit-req -n
# → REJECT all -- 1.2.3.4 0.0.0.0/0 reject-with icmp-port-unreachable

# Разбан вручную
sudo fail2ban-client set nginx-limit-req unbanip 1.2.3.4
```

## NAT для сетевых пространств имён (ip netns)

Сетевые пространства имён (`ip netns`) позволяют создавать изолированные сетевые стеки. NAT используется для обеспечения доступа процессов в `netns` наружу.

### Пример: NAT для контейнера в netns

```bash
# Создание сетевого пространства
sudo ip netns add isolated_ns

# Создание veth-пары для связи netns с хостом
sudo ip link add veth-host type veth peer name veth-ns

# Перемещение одного конца в netns
sudo ip link set veth-ns netns isolated_ns

# Настройка IP-адресов
sudo ip addr add 10.0.0.1/24 dev veth-host
sudo ip link set veth-host up
sudo ip netns exec isolated_ns ip addr add 10.0.0.2/24 dev veth-ns
sudo ip netns exec isolated_ns ip link set veth-ns up
sudo ip netns exec isolated_ns ip link set lo up

# Включение IP-forwarding на хосте
sudo sysctl -w net.ipv4.ip_forward=1

# Настройка NAT для трафика из netns
sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o eth0 -j MASQUERADE

# Маршрутизация по умолчанию в netns
sudo ip netns exec isolated_ns ip route add default via 10.0.0.1

# Проверка: DNS из netns должен работать
sudo ip netns exec isolated_ns ping -c 2 8.8.8.8
```

**Типичное применение:** Изолированные тестовые среды, контейнеры без Docker (LXC, чистые netns), прозрачные прокси для анализа трафика.

## Дополнительная информация

- **[Теория NAT](./overview.md)** — глубокий разбор механизмов, типов и теории (Conntrack, CGNAT, NAT64).
- **[Conntrack Bypass (raw NOTRACK)](./conntrack_bypass.md)** — обход conntrack для high-performance сценариев.
- **[Прозрачный прокси (REDIRECT vs TPROXY)](./transparent_proxy.md)** — прозрачное проксирование через NAT.
- **[Conntrack Helpers (ALG-модули)](./conntrack_helpers.md)** — обработка FTP, SIP, TFTP за NAT.
- **[Proxy ARP](./proxy_arp.md)** — прозрачная маршрутизация через ARP.
- **[NAT и VPN](./nat_and_vpn.md)** — IPsec NAT-T, WireGuard, OpenVPN за NAT.
- **[Netfilter в Linux](../../../Linux/Networking/Settings/tools/iptables_basics.md)** — архитектура цепочек и таблиц.
