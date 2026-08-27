# GRE vs WireGuard: сравнение и выбор протокола туннелирования

## Определения и назначение

**GRE (Generic Routing Encapsulation)** — протокол туннелирования L3/L2 без нативного шифрования. Разработан Cisco (RFC 2784/2890). Используется для инкапсуляции любых протоколов поверх IP-сети.

**WireGuard** — современный протокол VPN L3 с нативным шифрованием (ChaCha20-Poly1305). Разработан Jason Donenfeld (RFC 9443). Работает поверх UDP (порт 51820).

**Когда возникает вопрос выбора:**
- Site-to-Site VPN между двумя дата-центрами
- Remote access VPN для сотрудников
- Туннелирование динамической маршрутизации (OSPF/BGP)
- Растягивание L2-сегментов (VLAN) между площадками

---

## Теоретический блок

### Сравнительная таблица

| Критерий | GRE | WireGuard | Победитель |
|----------|-----|-----------|------------|
| **Уровень OSI** | L3 / L2 (GRETAP) | L3 | GRE (L2) |
| **Шифрование** | Нет (требует IPsec) | Да (нативно, ChaCha20-Poly1305) | WireGuard |
| **Аутентификация** | Key (некриптографический) | Curve25519 (криптографическая) | WireGuard |
| **Транспорт** | IP (протокол 47) | UDP (порт 51820) | WireGuard (NAT-friendly) |
| **NAT Traversal** | Плохо (требует FOU) | Отлично (нативно UDP) | WireGuard |
| **Keepalive** | Нативно не поддерживается (Linux) | Да (нативно) | WireGuard |
| **Динамическая маршрутизация** | Да (mGRE + NHRP + OSPF/BGP) | Нет (Point-to-Point только) | GRE |
| **Мультикаст** | Да (через GRE) | Нет | GRE |
| **L2-туннелирование** | Да (GRETAP) | Нет | GRE |
| **Зеркалирование трафика** | Да (ERSPAN) | Нет | GRE |
| **Количество пиров** | Неограниченное (mGRE) | 2 (Point-to-Point) | GRE |
| **Overhead** | 24-28 байт (L3), ~42 байт (L2) | ~60 байт | GRE |
| **Производительность (CPU)** | Средняя (без шифрования) | Высокая (硬件 AES-NI, ChaCha20) | WireGuard |
| **Установка** | Встроено в ядро Linux | Модуль ядра (wg) | GRE |
| **Сложность настройки** | Низкая | Очень низкая | WireGuard |
| **Аудит кода** | Зрелый, десятилетиями | Современный, ~4000 строк | — |

### Когда GRE предпочтительнее WireGuard

**GRE выигрывает в сценариях:**

1. **Динамическая маршрутизация** — OSPF, BGP, IS-IS требуют multicast/broadcast. GRE пропускает multicast «из коробки». WireGuard — чистый L3 unicast.

2. **L2-туннелирование** — GRETAP растягивает VLAN между площадками. WireGuard не поддерживает L2.

3. **ERSPAN** — зеркалирование трафика для анализа. WireGuard не может.

4. **Мультиплексирование** — один mGRE-интерфейс терминирует туннели от множества Spoke-узлов. WireGuard — строго 1:1.

5. **Миграция Cisco** — DMVPN (mGRE + NHRP) — стандарт в enterprise. WireGuard не имеет аналога.

6. **Интеграция с IPsec** — GRE-over-IPsec — проверенная комбинация для site-to-site VPN. WireGuard заменяет оба протокола.

**Пример: OSPF over GRE (реализуемо), OSPF over WireGuard (нереализуемо):**
```bash
# GRE: multicast OSPF hello проходит через туннель
ip link add gre0 type gre remote 203.0.113.2 local 198.51.100.1
ip addr add 10.0.0.1/30 dev gre0
ip link set gre0 up
# OSPF автоматически видит соседей через multicast

# WireGuard: multicast НЕ проходит
# WireGuard — это чистый L3 unicast tunnel
# OSPF не может обнаружить соседей
# Решение: статические маршруты или BGP (не OSPF)
```

### Когда WireGuard предпочтительнее GRE

**WireGuard выигрывает в сценариях:**

1. **Remote Access VPN** — простая настройка, современный клиент (Windows, macOS, Linux, iOS, Android).

2. **Site-to-Site без динамической маршрутизации** — если достаточно статических маршрутов.

3. **NAT Traversal** — WireGuard работает через NAT «из коробки». GRE требует FOU или статического NAT.

4. **Безопасность** — WireGuard шифрует по умолчанию. GRE+IPsec = два протокола, два конфига, два.places для ошибок.

5. **Простота** — WireGuard: один конфиг, один ключ. GRE+IPsec: strongSwan + GRE + firewall + MSS clamping.

6. **Производительность** — WireGuard имеет меньший overhead (~60 байт vs GRE+IPsec ~80+ байт) и аппаратное ускорение.

**Пример: WireGuard site-to-site (простейшая конфигурация):**
```ini
# /etc/wireguard/wg0.conf (Host A)
[Interface]
Address = 10.0.0.1/30
ListenPort = 51820
PrivateKey = <private_key_A>

[Peer]
PublicKey = <public_key_B>
Endpoint = 203.0.113.2:51820
AllowedIPs = 172.16.0.0/24
PersistentKeepalive = 25
```

---

## Практическая реализация

### Миграция GRE → WireGuard

**Сценарий:** Замена GRE+IPsec на WireGuard для site-to-site VPN без динамической маршрутизации.

**Шаг 1 — Установка WireGuard:**
```bash
# Debian/Ubuntu
sudo apt install wireguard

# Проверка модуля
sudo modprobe wireguard
lsmod | grep wireguard
```

**Шаг 2 — Генерация ключей (оба узла):**
```bash
# Host A
wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key

# Host B
wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key
```

**Шаг 3 — Конфигурация Host A (198.51.100.1):**
```ini
# /etc/wireguard/wg0.conf
[Interface]
Address = 10.0.0.1/30
ListenPort = 51820
PrivateKey = <private_key_A>

# FW правила (автоматически при старте)
PostUp = nft add rule inet filter input iifname eth0 udp dport 51820 accept
PostDown = nft delete rule inet filter input iifname eth0 udp dport 51820

[Peer]
PublicKey = <public_key_B>
Endpoint = 203.0.113.2:51820
AllowedIPs = 10.0.0.2/32, 172.16.0.0/24
PersistentKeepalive = 25
```

**Шаг 4 — Конфигурация Host B (203.0.113.2):**
```ini
# /etc/wireguard/wg0.conf
[Interface]
Address = 10.0.0.2/30
ListenPort = 51820
PrivateKey = <private_key_B>

PostUp = nft add rule inet filter input iifname eth0 udp dport 51820 accept
PostDown = nft delete rule inet filter input iifname eth0 udp dport 51820

[Peer]
PublicKey = <public_key_A>
Endpoint = 198.51.100.1:51820
AllowedIPs = 10.0.0.1/32, 192.168.0.0/24
PersistentKeepalive = 25
```

**Шаг 5 — Активация и проверка:**
```bash
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0

# Статус
sudo wg show

# Проверка связи
ping 10.0.0.2

# Проверка handshake
sudo wg show wg0 latest-handshakes
```

**Шаг 6 — Миграция маршрутизации:**
```bash
# Удаление старого GRE-маршрута
sudo ip route del 172.16.0.0/24 via 10.0.0.2 dev gre0

# Добавление нового маршрута через WireGuard
sudo ip route add 172.16.0.0/24 via 10.0.0.2 dev wg0

# Или статический маршрут
sudo ip route add 172.16.0.0/24 dev wg0
```

**Шаг 7 — Удаление GRE (после верификации):**
```bash
# Остановка и удаление GRE
sudo ip link set gre0 down
sudo ip link del gre0

# Удаление правил firewall
sudo nft delete rule inet filter input handle <GRE_RULE_HANDLE>
```

### Параллельная работа (GRE + WireGuard)

Для безопасной миграции:

```bash
# WireGuard уже активен
# GRE пока не удаляем
# Маршруты переключаем постепенно

# Шаг 1: Проверяем WireGuard
ping -I wg0 10.0.0.2
iperf3 -c 10.0.0.2

# Шаг 2: Меняем приоритет маршрута (metric)
sudo ip route add 172.16.0.0/24 via 10.0.0.2 dev wg0 metric 100
sudo ip route del 172.16.0.0/24 via 10.0.0.2 dev gre0

# Шаг 3: Мониторим, если всё OK — удаляем GRE
```

### Когда НЕЛЬЗЯ мигрировать на WireGuard

**Не заменяйте GRE на WireGuard если:**

1. **Используется динамическая маршрутизация (OSPF/BGP)** — WireGuard не поддерживает multicast. Решение: статические маршруты или BGP через WireGuard (но без OSPF).

2. **Требуется GRETAP (L2-туннели)** — WireGuard не поддерживает L2. Решение: туннелирование L2 через VXLAN поверх WireGuard.

3. **Используется DMVPN (mGRE + NHRP)** — WireGuard не имеет Hub-and-Spoke с динамическим обнаружением. Решение: WireGuard с `AllowedIPs` для каждого Spoke (статическая конфигурация).

4. **Требуется ERSPAN** — зеркалирование трафика невозможно через WireGuard.

5. **Cisco/Juniper equipment** — не все коммутаторы поддерживают WireGuard. GRE — стандарт на оборудовании.

### Benchmark: GRE vs GRE+IPsec vs WireGuard

```bash
# Тест пропускной способности (iperf3)
# GRE only
iperf3 -c 10.0.0.2 -t 30 -P 4

# GRE + IPsec (strongSwan)
iperf3 -c 10.0.0.2 -t 30 -P 4

# WireGuard
iperf3 -c 10.0.0.2 -t 30 -P 4
```

**Типичные результаты (10G NIC, AES-NI):**

| Протокол | Throughput | CPU (1 flow) | Latency |
|----------|------------|---------------|---------|
| **GRE** | ~9.5 Gbps | 1 core | <0.1ms |
| **GRE + IPsec (AES-GCM)** | ~5.2 Gbps | 2 cores | <0.5ms |
| **WireGuard (ChaCha20)** | ~7.8 Gbps | 1 core | <0.2ms |

*Результаты зависят от CPU, NIC offloading, MTU.*

---

## Дополнительная информация

### Чек-лист для выбора

```
Нужен multicast/dynamic routing?  → GRE
Нужен L2-туннель (VLAN)?         → GRE
Есть Cisco DMVPN?                 → GRE
NAT traversal критичен?           → WireGuard
Нужно шифрование «из коробки»?   → WireGuard
Remote access VPN?                → WireGuard
Простота настройки?               → WireGuard
Site-to-site + IPsec?             → GRE+IPsec или WireGuard
```

### Связанные документы

*   [Протокол GRE](./gre.md) — архитектура и настройка GRE.
*   [GRE: практические сценарии](./gre_practical_scenarios.md) — настройка GRE-туннелей.
*   [GRE с IPsec](./gre_ipsec_integration.md) — защищённые GRE-туннели.
*   [IPsec](../ipsec/ipsec.md) — архитектура IKEv2/IPsec.
*   [Remote Access VPN — сравнение](../remote_access_vpn.md) — WireGuard vs OpenVPN vs IPsec vs L2TP/IPsec.
*   [Мониторинг GRE](./gre_monitoring.md) — наблюдаемость GRE-туннелей.
