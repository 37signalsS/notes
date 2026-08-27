# Сравнение Proxy и VPN

## Определения

Для обеспечения анонимности, безопасности и управления трафиком используются две основные технологии-посредника, работающие на разных уровнях сетевого стека:

*   **Прокси-сервер (Proxy):** Промежуточный узел, выступающий посредником между клиентом и целевым ресурсом. Работает преимущественно на **прикладном уровне (L7)** (HTTP/HTTPS) или **транспортном уровне (L4)** (SOCKS). Прокси подменяет IP-адрес только для конкретных приложений или протоколов, не затрагивая остальной трафик системы. Клиент явно знает о существовании прокси и настраивает приложение на работу через него.
*   **VPN (Virtual Private Network):** Технология создания защищенного виртуального туннеля поверх существующей сети. Работает на **сетевом уровне (L3)**, виртуализируя сетевой интерфейс (через драйверы **TUN/TAP**). VPN шифрует и инкапсулирует *весь* исходящий и входящий трафик устройства, направляя его через удаленный сервер. Для приложений туннель прозрачен — они отправляют трафик как обычно, не зная о существовании VPN.

## Основные различия

### Сравнительная таблица

| Критерий | Proxy (Прокси) | VPN (Виртуальная сеть) |
| :--- | :--- | :--- |
| **Уровень OSI** | L4 (SOCKS) / L7 (HTTP/FTP) | L3 (Сетевой) / L4 (Транспортный) |
| **Область действия** | Конкретное приложение / браузер | Вся операционная система (весь трафик) |
| **Шифрование** | Зависит от протокола (в SOCKS5/HTTP — нет) | Обязательное (AES-256, ChaCha20) |
| **Приватность** | Скрывает IP от сервера назначения | Скрывает IP и трафик от провайдера (ISP) |
| **Производительность** | Высокая (низкий overhead) | Ниже (издержки на шифрование и инкапсуляцию) |
| **Протоколы** | HTTP(H), SOCKS4/5, Shadowsocks, Trojan | WireGuard, OpenVPN, IPsec, IKEv2 |
| **Обход DPI** | Эффективен (Shadowsocks, Trojan) | Часто блокируется по сигнатурам (OpenVPN) |
| **Настройка** | Требует настройки в каждом приложении | Единообразная настройка на уровне ОС |
| **Обратный прокси** | Да (Reverse Proxy для защиты серверов) | Нет (VPN только для клиентского трафика) |

### Механика работы и протоколы

#### Прокси-сервер

Прокси работает как "передатчик" на уровне потоков или сообщений. Клиент устанавливает соединение с прокси и передает запрос, прокси устанавливает отдельное соединение с целевым сервером.

*   **HTTP-прокси:** Анализирует и может модифицировать заголовки HTTP. Используется для фильтрации и кэширования. Для HTTPS используется метод `CONNECT` (туннелирование) или SSL Termination (перехват).
*   **SOCKS5:** Более универсален, поддерживает TCP/UDP и аутентификацию. Не анализирует содержимое (L4), просто пересылает пакеты. Поддерживает привязку к порту (BIND) для входящих соединений.
*   **Прозрачный прокси (Transparent):** Перехватывает трафик без настройки клиента (часто на шлюзах). Реализуется через `iptables`/`nftables` (REDIRECT, TPROXY) или WCCP. Подробнее: **[Прозрачный прокси через NAT](./nat/transparent_proxy.md)**.
*   **Обратный прокси (Reverse Proxy):** Защищает и балансирует серверную часть. Подробнее: **[Reverse Proxy](../../WebServers/Nginx/Proxy/Load_Balancing/overview_concepts.md)**.
*   **Современные протоколы обхода блокировок:**
    *   **Shadowsocks:** Обфусцированный SOCKS5-прокси с шифрованием трафика. Разработан для обхода DPI, не имеет характерных сигнатур.
    *   **Trojan:** Маскирует трафик под обычный HTTPS (TLS), используя настоящий сертификат. Невозможно отличить от обычного веб-трафика без расшифровки.
    *   **VLESS/VMess (V2Ray/Xray):** Протоколы с мультиплексированием и маскировкой под WebSocket или gRPC.

#### VPN

VPN создает виртуальный сетевой адаптер. Пакеты приложения проходят через стек ОС, попадают в виртуальный интерфейс, где шифруются и упаковываются в "несущий" протокол (например, UDP для WireGuard).

*   **Split Tunneling:** Позволяет направлять часть трафика (например, рабочие ресурсы) через VPN, а остальной (интернет) — напрямую. Реализуется через маршрутизацию: в таблицу маршрутов добавляются только нужные подсети через VPN-интерфейс.
*   **Kill Switch:** Механизм, блокирующий доступ в сеть при разрыве VPN-соединения, предотвращающий утечку реального IP. Реализуется через `iptables`/`nftables`: разрешается трафик только через VPN-интерфейс и на VPN-сервер.
*   **Жизненный цикл запроса:** Подробная схема инкапсуляции описана в **[Жизненном цикле веб-запроса](./web_request_lifecycle.md)**.
*   **Туннельные интерфейсы:** Подробнее о TUN/TAP и виртуальных интерфейсах: **[Сетевые интерфейсы Linux](../../Linux/Networking/Concepts/linux_network_interfaces.md)**.

## Практические сценарии

### Когда использовать Proxy

*   **DevOps:** Организация доступа к внутренним API через `kubectl proxy` или балансировка трафика в Kubernetes через **[Ingress Nginx](../../WebServers/Nginx/Proxy/Load_Balancing/overview_concepts.md)**.
*   **Скрапинг:** Использование пула IP-адресов для обхода лимитов (Rate Limiting) без необходимости шифрования.
*   **Jump Host:** Доступ к ресурсам в закрытом контуре через SSH-туннель (который по сути является SOCKS-прокси). Подробнее: **[SSH-туннелирование](../../Linux/Security/ssh/ssh_usage_and_tunnels.md)**.
*   **Кэширование:** Ускорение доступа к часто запрашиваемым ресурсам через кэширующий прокси (Squid, Nginx).
*   **Фильтрация:** Блокировка нежелательного контента на уровне сети (корпоративные прокси).

### Когда использовать VPN

*   **Безопасность сотрудников:** Защита трафика при работе через незащищенные каналы связи (публичные Wi-Fi).
*   **Site-to-Site:** Объединение двух изолированных сегментов сети (например, On-premise и Cloud) в единое адресное пространство.
*   **Администрирование:** Доступ к управляющей сети (Management Network) для настройки оборудования и серверов.
*   **Защита от перехвата:** Полное скрытие структуры трафика от провайдера (ISP), включая DNS-запросы.

---

### Сценарий 1: Настройка прямого прокси с авторизацией (Squid)

**Предварительные требования:**
- Ubuntu/Debian сервер с публичным IP
- Порт 3128 открыт для клиентов (192.168.1.0/24)
- Доступ root или sudo

**Шаг 1: Установка Squid**

```bash
sudo apt update && sudo apt install -y squid apache2-utils
```

**Шаг 2: Создание пользователя**

```bash
# Создание пароля для прокси-пользователя
sudo htpasswd -c /etc/squid/passwords proxyuser
# → New password: ****
# → Re-type new password: ****
# → Adding password for user proxyuser
```

**Шаг 3: Конфигурация `/etc/squid/squid.conf`**

```bash
# Порт прокси
http_port 3128

# Локальная сеть
acl localnet src 192.168.1.0/24

# Настройка авторизации
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwords
auth_param basic children 5
auth_param basic realm Squid proxy-caching web server
auth_param basic credentialsttl 2 hours

acl authenticated proxy_auth REQUIRED
http_access allow authenticated localnet
http_access deny all

# Кэширование
cache_dir ufs /var/spool/squid 10000 16 256
maximum_object_size 4096 KB
minimum_object_size 0 KB
cache_swap_low 90
cache_swap_high 95

# Логирование
access_log /var/log/squid/access.log squid
```

**Шаг 4: Запуск и проверка**

```bash
sudo systemctl enable --now squid

# Проверка порта
ss -tlnp | grep 3128
# → LISTEN 0 128 0.0.0.0:3128 0.0.0.0:* users:(("squid",pid=1234,fd=6))

# Тест с клиента
curl -x http://proxyuser:password@proxy.example.com:3128 http://example.com
# → Должен получить контент example.com
```

**Шаг 5: Настройка клиента**

```bash
# Переменные окружения (Linux/macOS)
export http_proxy="http://proxyuser:password@proxy.example.com:3128"
export https_proxy="http://proxyuser:password@proxy.example.com:3128"
export no_proxy="localhost,127.0.0.1,.localdomain"
```

---

### Сценарий 2: Настройка VPN-сервера (WireGuard)

**Предварительные требования:**
- Ubuntu/Debian сервер с публичным IP
- Порт 51820/UDP открыт на firewall
- Доступ root или sudo
- Клиентская ОС: Linux, macOS, Windows, iOS, android

**Шаг 1: Установка WireGuard**

```bash
# Linux (Ubuntu/Debian)
sudo apt update && sudo apt install -y wireguard

# Проверка установки
wg --version
# → wireguard-tools v1.0.20210914
```

**Шаг 2: Генерация ключей**

```bash
# Создание директории для ключей
sudo mkdir -p /etc/wireguard
cd /etc/wireguard

# Генерация ключей сервера
wg genkey | tee server_private.key | wg pubkey > server_public.key

# Генерация ключей клиента
wg genkey | tee client_private.key | wg pubkey > client_public.key

# Установка прав
sudo chmod 600 /etc/wireguard/*.key
```

**Шаг 3: Конфигурация сервера `/etc/wireguard/wg0.conf`**

```ini
[Interface]
# Приватный ключ сервера
PrivateKey = <server_private_key>
# Внутренний IP сервера в VPN-сети
Address = 10.0.0.1/24
# Порт слушания
ListenPort = 51820
# Включение IP forwarding (выполняется после старта)
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
# Сохранение правил при остановке
SaveConfig = true

[Peer]
# Публичный ключ клиента
PublicKey = <client_public_key>
# Разрешенные IP (внутренний IP клиента)
AllowedIPs = 10.0.0.2/32
```

**Шаг 4: Включение IP forwarding**

```bash
# Временное включение
sudo sysctl -w net.ipv4.ip_forward=1

# Постоянное включение
echo "net.ipv4.ip_forward = 1" | sudo tee -a /etc/sysctl.d/99-wireguard.conf
sudo sysctl -p /etc/sysctl.d/99-wireguard.conf
```

**Шаг 5: Запуск WireGuard**

```bash
# Запуск
sudo wg-quick up wg0
# → [#] ip link add wg0 type wireguard
# → [#] wg setconf wg0 /dev/fd/63
# → [#] ip -4 address add 10.0.0.1/24 dev wg0
# → [#] ip link set mtu 1420 up dev wg0

# Включение автозапуска
sudo systemctl enable wg-quick@wg0

# Проверка статуса
sudo wg show
# → interface: wg0
# →   public key: <server_public_key>
# →   private key: (hidden)
# →   listening port: 51820
```

**Шаг 6: Конфигурация клиента `/etc/wireguard/wg0.conf`**

```ini
[Interface]
# Приватный ключ клиента
PrivateKey = <client_private_key>
# Внутренний IP клиента
Address = 10.0.0.2/24
# DNS через VPN (опционально, предотвращает DNS-leak)
DNS = 1.1.1.1, 8.8.8.8

[Peer]
# Публичный ключ сервера
PublicKey = <server_public_key>
# Публичный IP и порт сервера
Endpoint = <server_public_ip>:51820
# Маршрутизация всего трафика через VPN (0.0.0.0/0 = весь IPv4)
AllowedIPs = 0.0.0.0/0
# Поддержание соединения через NAT
PersistentKeepalive = 25
```

**Шаг 7: Подключение клиента**

```bash
# Linux/macOS
sudo wg-quick up wg0

# Проверка
ping 10.0.0.1
# → PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.
# → 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=15.2 ms

# Проверка маршрутизации
curl ifconfig.me
# → Должен показать публичный IP сервера WireGuard
```

---

### Сценарий 3: Настройка Kill Switch (защита от утечки IP)

Kill Switch блокирует весь трафик при разрыве VPN-соединения, предотвращая утечку реального IP.

**Предварительные требования:**
- WireGuard настроен и работает
- Доступ root

**Шаг 1: Создание скрипта Kill Switch**

```bash
sudo nano /etc/wireguard/killswitch.sh
```

```bash
#!/bin/bash
#
# Kill Switch для WireGuard
# Блокирует трафик при разрыве VPN

IFACE="wg0"
# IP сервера WireGuard (разрешен всегда для поддержания туннеля)
WG_SERVER_IP="10.0.0.1"
# Интерфейс физической сети
PHYS_IFACE="eth0"

set -o nounset
set -o errexit
set -o pipefail

enable_killswitch() {
    echo "Enabling Kill Switch..."

    # Очистка правил
    iptables -F
    iptables -t nat -F

    # Разрешение loopback
    iptables -A INPUT -i lo -j ACCEPT
    iptables -A OUTPUT -o lo -j ACCEPT

    # Разрешение установленных соединений
    iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

    # Разрешение трафика только через VPN-интерфейс
    iptables -A OUTPUT -o $IFACE -j ACCEPT

    # Разрешение трафика к VPN-серверу (для поддержания туннеля)
    iptables -A OUTPUT -o $PHYS_IFACE -d $WG_SERVER_IP -p udp --dport 51820 -j ACCEPT

    # Блокировка всего остального
    iptables -A OUTPUT -j DROP

    echo "Kill Switch enabled."
}

disable_killswitch() {
    echo "Disabling Kill Switch..."
    iptables -F
    iptables -t nat -F
    iptables -P INPUT ACCEPT
    iptables -P OUTPUT ACCEPT
    iptables -P FORWARD ACCEPT
    echo "Kill Switch disabled."
}

case "$1" in
    enable)
        enable_killswitch
        ;;
    disable)
        disable_killswitch
        ;;
    *)
        echo "Usage: $0 {enable|disable}"
        exit 1
        ;;
esac
```

```bash
sudo chmod +x /etc/wireguard/killswitch.sh
```

**Шаг 2: Интеграция с WireGuard**

Добавьте в `/etc/wireguard/wg0.conf`:

```ini
[Interface]
...
PostUp = /etc/wireguard/killswitch.sh enable
PostDown = /etc/wireguard/killswitch.sh disable
```

**Шаг 3: Проверка**

```bash
# Запуск VPN с Kill Switch
sudo wg-quick up wg0

# Проверка правил
sudo iptables -L -n
# → Chain OUTPUT (policy ACCEPT)
# → target     prot opt source               destination
# → ACCEPT     all  --  0.0.0.0/0            0.0.0.0/0            state ESTABLISHED,RELATED
# → ACCEPT     all  --  0.0.0.0/0            0.0.0.0/0            out-interface wg0
# → DROP       all  --  0.0.0.0/0            0.0.0.0/0

# Тест: остановите VPN и проверьте, что трафик не идет
sudo wg-quick down wg0
curl --max-time 5 ifconfig.me
# → curl: (28) Connection timed out
```

---

### Сценарий 4: Настройка Split Tunneling (раздельная маршрутизация)

Split Tunneling позволяет направлять только часть трафика через VPN, а остальной — напрямую.

**Предварительные требования:**
- WireGuard настроен
- Знание подсетей, которые нужно пускать через VPN

**Шаг 1: Конфигурация клиента с Split Tunneling**

```ini
[Interface]
PrivateKey = <client_private_key>
Address = 10.0.0.2/24
DNS = 1.1.1.1

[Peer]
PublicKey = <server_public_key>
Endpoint = <server_public_ip>:51820
# Только корпоративные подсети через VPN
AllowedIPs = 10.0.0.0/24, 192.168.100.0/24, 172.16.0.0/12
PersistentKeepalive = 25
```

**Шаг 2: Проверка маршрутизации**

```bash
# Запуск VPN
sudo wg-quick up wg0

# Проверка маршрутов
ip route show
# → 10.0.0.0/24 dev wg0 proto kernel scope link src 10.0.0.2
# → 192.168.100.0/24 dev wg0 scope link
# → 172.16.0.0/12 dev wg0 scope link
# → default via 192.168.1.1 dev eth0  (основной шлюз)

# Тест: трафик к корпоративному ресурсу идет через VPN
traceroute 192.168.100.50
# → 1  10.0.0.1  15.2ms  (через VPN)

# Тест: трафик в интернет идет напрямую
traceroute 8.8.8.8
# → 1  192.168.1.1  2.1ms  (напрямую)
```

---

### Сценарий 5: Настройка MTU и MSS Clamping для VPN

Проблема: VPN добавляет заголовки, уменьшая эффективный MTU. Без настройки возникает фрагментация или "черная дыра".

**Предварительные требования:**
- WireGuard настроен
- Доступ root на сервере

**Шаг 1: Определение оптимального MTU**

```bash
# Тест с DF-битом (Don't Fragment)
ping -s 1472 -M do 10.0.0.2
# → Если не проходит, уменьшайте размер

# Для WireGuard обычно MTU = 1420 (1500 - 80 байт заголовков)
ping -s 1392 -M do 10.0.0.2
# → 1392 + 28 (ICMP заголовок) = 1420
```

**Шаг 2: Установка MTU на интерфейсе**

```bash
# Временная установка
sudo ip link set dev wg0 mtu 1420

# Постоянная установка в конфиге WireGuard
# /etc/wireguard/wg0.conf
[Interface]
...
# Добавьте строку:
MTU = 1420
```

**Шаг 3: Настройка TCP MSS Clamping**

```bash
# Для iptables
sudo iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# Для nftables
sudo nft add rule inet filter forward oifname "wg0" tcp flags & (syn|rst) == syn tcp option maxseg size set rt mtu
```

**Шаг 4: Проверка**

```bash
# Захват SYN-пакетов для проверки MSS
sudo tcpdump -i wg0 'tcp[tcpflags] & tcp-syn != 0' -v
# → mss 1380  (1420 - 40 байт заголовков TCP/IP)

# Тест передачи больших данных
dd if=/dev/urandom bs=1M count=10 | ssh user@10.0.0.2 "cat > /dev/null"
# → Должно передаваться без зависаний
```

Подробнее о MTU и диагностике: **[MTU, PMTUD и диагностика в VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)**.

---

## Технические нюансы и диагностика

### Производительность (Overhead)

VPN добавляет заголовки (IP + UDP/TCP + VPN Header), что уменьшает **MTU** (Maximum Transmission Unit). Это может приводить к фрагментации пакетов, если не настроен MSS Clamping.

| Технология | Оверхед (байт) | MTU (при физическом 1500) |
| :--- | :--- | :--- |
| **WireGuard** | 60–80 | 1420 |
| **OpenVPN (UDP)** | 50–73 | 1420–1450 |
| **IPsec (ESP)** | 56–73 | ~1420 |
| **Shadowsocks** | Минимальный | 1500 (работает как обычный TCP) |

### Двойное шифрование

Использование HTTPS поверх VPN (TLS-in-TLS) создает дополнительную нагрузку на CPU, но обеспечивает максимальную безопасность:
- VPN скрывает метаданные (IP назначения, время подключения) от ISP
- TLS защищает содержимое даже от VPN-провайдера (end-to-end шифрование)

### Идентификация и аутентификация

VPN чаще интегрируется с корпоративными системами аутентификации (**[LDAP/AD](../../LDAP/openldap_kubernetes.md)**, SAML), в то время как прокси часто ограничиваются базовой аутентификацией или проверкой по IP.

### Сетевой уровень

VPN позволяет использовать протоколы, отличные от TCP/UDP (ICMP, OSPF), так как работает на уровне L3. Прокси (кроме SOCKS5) обычно ограничены TCP.

### DNS Leak Protection

При использовании VPN критически важно предотвратить утечку DNS-запросов вне туннеля:

```bash
# Проверка DNS leak
# Используйте онлайн-тесты или:
dig +short whoami.akamai.net
# → Должен показать IP VPN-сервера, а не ваш реальный

# Настройка DNS в WireGuard
[Interface]
DNS = 1.1.1.1, 1.0.0.1
```

---

## Валидация и диагностика

### Проверка работы прокси

```bash
# 1. Проверка доступности порта
nc -zv proxy.example.com 3128
# → Connection to proxy.example.com 3128 port [tcp/*] succeeded!

# 2. Проверка через curl с заголовками
curl -v -x http://proxy.example.com:3128 http://example.com 2>&1 | grep -E "< HTTP|Via|X-Forwarded"

# 3. Проверка анонимности
curl -x http://proxy.example.com:3128 http://ifconfig.me
# → Должен показать IP прокси-сервера

# 4. Проверка логов
tail -f /var/log/squid/access.log
# → 1638297600.123    125 192.168.1.5 TCP_MISS/200 1234 GET http://example.com/ - HIER_DIRECT/93.184.216.34 text/html
```

### Проверка работы VPN

```bash
# 1. Проверка статуса WireGuard
sudo wg show
# → interface: wg0
# →   public key: <key>
# →   private key: (hidden)
# →   listening port: 51820
# →
# → peer: <client_public_key>
# →   endpoint: <client_ip>:51820
# →   allowed ips: 10.0.0.2/32
# →   latest handshake: 30 seconds ago  (должно быть недавним)
# →   transfer: 1.5 MiB received, 10 MiB sent

# 2. Проверка интерфейса
ip addr show wg0
# → 3: wg0: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1420 qdisc noqueue state UNKNOWN
# →    inet 10.0.0.1/24 scope global wg0

# 3. Проверка пинга через VPN
ping 10.0.0.2
# → 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=15.2 ms

# 4. Проверка маршрутизации
ip route show dev wg0
# → 10.0.0.0/24 proto kernel scope link src 10.0.0.1

# 5. Проверка публичного IP
curl ifconfig.me
# → Должен показать IP VPN-сервера

# 6. Проверка DNS leak
dig +short whoami.akamai.net
# → Должен показать IP VPN-сервера
```

### Анализ трафика

```bash
# Перехват трафика на порту прокси
sudo tcpdump -i any port 3128 -w proxy.pcap

# Перехват VPN-трафика (WireGuard использует UDP 51820)
sudo tcpdump -i any udp port 51820 -w wireguard.pcap

# Анализ в Wireshark: фильтр "udp.port == 51820"

# Проверка соединений через VPN
ss -tnp | grep wg0
# → ESTAB 0 0 10.0.0.1:22 10.0.0.2:12345 users:(("sshd",pid=1234,fd=3))
```

---

## Устранение неполадок

### Проблема: VPN не подключается

**Причины:**
- Неправильный ключ
- Блокировка порта файрволом
- Неправильный Endpoint

**Диагностика:**
```bash
# Проверка порта на сервере
nc -zv <server_ip> 51820
# → Connection to <server_ip> 51820 port [tcp/*] succeeded!

# Проверка firewall
sudo iptables -L -n | grep 51820
# → ACCEPT     udp  --  0.0.0.0/0            0.0.0.0/0            udp dpt:51820

# Проверка логов WireGuard
sudo journalctl -u wg-quick@wg0 -f
# → wg0: Handshake for peer 1 (<client_public_key>) did not complete after 5 seconds
```

**Решение:**
- Проверьте ключи: `echo "<private_key>" | wg pubkey` — должен совпадать с публичным ключом
- Откройте порт: `sudo ufw allow 51820/udp`
- Проверьте Endpoint: должен быть публичный IP и порт

### Проблема: VPN подключен, но нет интернета

**Причины:**
- Не включен IP forwarding
- Не настроен NAT/MASQUERADE
- Неправильная маршрутизация

**Диагностика:**
```bash
# Проверка IP forwarding
cat /proc/sys/net/ipv4/ip_forward
# → 1 (должно быть 1)

# Проверка NAT
sudo iptables -t nat -L -n | grep MASQUERADE
# → MASQUERADE  all  --  10.0.0.0/24          0.0.0.0/0

# Проверка маршрута
ip route show default
# → default via 10.0.0.1 dev wg0  (должен быть через VPN)
```

**Решение:**
```bash
# Включение IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1

# Добавление NAT
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
```

### Проблема: Медленная скорость через VPN

**Причины:**
- Высокий overhead шифрования
- Неправильный MTU
- Перегрузка VPN-сервера

**Диагностика:**
```bash
# Тест скорости без VPN
curl -o /dev/null -s -w "%{speed_download}\n" http://speedtest.tele2.net/10MB.zip
# → 12500000 (100 Mbps)

# Тест скорости через VPN
curl -o /dev/null -s -w "%{speed_download}\n" http://speedtest.tele2.net/10MB.zip
# → 3125000 (25 Mbps)

# Проверка CPU на сервере
top -bn1 | grep -E "wireguard|openvpn"
# → Если CPU 100% — узкое место в шифровании
```

**Решение:**
- Используйте WireGuard вместо OpenVPN (меньше overhead)
- Настройте MTU: `ip link set dev wg0 mtu 1420`
- Включите аппаратное ускорение (AES-NI для AES, или ChaCha20 для ARM)

### Проблема: DNS Leak

**Причины:**
- DNS-запросы идут вне VPN-туннеля
- Неправильная настройка DNS в VPN-клиенте

**Диагностика:**
```bash
# Проверка через онлайн-тест
# https://www.dnsleaktest.com/

# Проверка локального DNS
systemd-resolve --status | grep "DNS Servers"
# → DNS Servers: 1.1.1.1  (должен быть DNS VPN-провайдера)
```

**Решение:**
```bash
# В конфигурации WireGuard
[Interface]
DNS = 1.1.1.1, 1.0.0.1

# Принудительная маршрутизация DNS через VPN
sudo iptables -t nat -A PREROUTING -i wg0 -p udp --dport 53 -j DNAT --to-destination 1.1.1.1:53
```

### Проблема: Прокси не отвечает

**Причины:**
- Сервис не запущен
- Блокировка файрволом
- Неправильная конфигурация

**Диагностика:**
```bash
# Проверка статуса
sudo systemctl status squid
# → Active: active (running)

# Проверка порта
ss -tlnp | grep 3128
# → LISTEN 0 128 0.0.0.0:3128

# Проверка логов
tail -f /var/log/squid/cache.log
# → 2024/01/15 10:30:00| Squid Parent: will start 1 kids
```

**Решение:**
```bash
# Перезапуск сервиса
sudo systemctl restart squid

# Проверка конфигурации
sudo squid -k parse
# → Должно быть без ошибок
```

---

## Безопасность и лучшие практики

### Безопасность VPN

1. **Используйте современные протоколы:** WireGuard или IKEv2 вместо PPTP/L2TP.
2. **Минимальные привилегии:** Не запускайте VPN-сервер от root.
3. **Ротация ключей:** Периодически генерируйте новые ключи.
4. **Kill Switch:** Всегда включайте для предотвращения утечки IP.
5. **DNS Leak Protection:** Настройте DNS через VPN-туннель.
6. **Аудит:** Логируйте подключения и объем трафика.

### Безопасность прокси

1. **Аутентификация:** Всегда используйте аутентификацию для прямого прокси.
2. **Ограничение доступа:** Разрешайте доступ только доверенным подсетям (ACL).
3. **Шифрование:** Используйте HTTPS-прокси для защиты трафика между клиентом и прокси.
4. **Логирование:** Включите аудит для отслеживания активности.
5. **Обновление:** Регулярно обновляйте ПО прокси-сервера.

### Сравнение с другими технологиями

| Критерий | Proxy | VPN | SSH Tunnel |
| :--- | :--- | :--- | :--- |
| **Уровень** | L4/L7 | L3/L4 | L4 (TCP) |
| **Шифрование** | Опционально | Обязательное | Обязательное |
| **Область действия** | Приложение | Вся ОС | Конкретный порт |
| **Сложность настройки** | Низкая | Средняя | Средняя |
| **Производительность** | Высокая | Средняя | Средняя (TCP-in-TCP) |

Подробнее о SSH-туннелях: **[SSH-туннелирование](../../Linux/Security/ssh/ssh_usage_and_tunnels.md)**.

---

## Резюме

| Характеристика | Proxy | VPN |
| :--- | :--- | :--- |
| **Безопасность** | Низкая (только подмена IP) | Высокая (шифрование всего канала) |
| **Универсальность** | Требует настройки в каждом приложении | Работает для всех приложений прозрачно |
| **Скорость** | Максимально близка к каналу | Зависит от CPU и протокола |
| **Надежность** | Средняя (зависит от приложения) | Высокая (системный уровень) |
| **Лучшее применение** | Скрапинг, кэширование, фильтрация | Защита трафика, удаленный доступ, Site-to-Site |

---

## Дополнительная информация

*   **[Прокси-сервер — подробный обзор](./proxy.md)** — типы, анонимность и заголовки.
*   **[WireGuard](../../Vpn/wireguard.md)** — современный стандарт быстрых VPN.
*   **[Сетевые интерфейсы Linux](../../Linux/Networking/Concepts/linux_network_interfaces.md)** — подробнее про TUN/TAP и виртуальные мосты.
*   **[Модель OSI](../OSI_TCP_IP_Model/osi_model.md)** — понимание уровней L3, L4 и L7.
*   **[Сравнение VPN и Service Mesh](./vpn_vs_service_mesh.md)** — когда VPN недостаточно для микросервисов.
*   **[MTU, PMTUD и диагностика в VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — решение проблем фрагментации.
*   **[SSH-туннелирование](../../Linux/Security/ssh/ssh_usage_and_tunnels.md)** — альтернатива прокси и VPN.
*   **[Прозрачный прокси через NAT](./nat/transparent_proxy.md)** — перехват трафика без настройки клиента. 