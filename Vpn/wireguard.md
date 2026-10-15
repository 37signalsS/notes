# WireGuard

**Актуально для:** WireGuard (модуль ядра Linux 1.0.x, `wireguard-tools` 1.0.x); нативная поддержка в ядре Linux 5.6+. Протокол WireGuard v1.

## Определения

**WireGuard** — протокол VPN-туннелирования уровня L3, работающий поверх UDP (порт по умолчанию — `51820`). На Linux реализован как модуль ядра (`wireguard.ko`), что даёт производительность уровня GRE при нативном шифровании; для платформ без модуля существуют userspace-реализации (`wireguard-go`, Cloudflare BoringTun).

**Cryptokey routing** (криптографическая маршрутизация) — базовая модель WireGuard: список `AllowedIPs` каждого пира одновременно является и таблицей маршрутизации на отправку, и списком разрешённых источников на приём. Именно связка «публичный ключ ↔ AllowedIPs» заменяет в WireGuard и таблицу маршрутизации, и ACL.

**Пир (peer)** — участник VPN, идентифицируемый парой статических ключей Curve25519. Один пир = один публичный ключ; владение приватным ключом доказывает принадлежность пира.

**Интерфейс** — виртуальный сетевой интерфейс (`wg0`), создаваемый как обычный netdevice; IP-адреса, маршруты и MTU назначаются штатными средствами Linux (`ip addr`, `ip route`, `ip link`).

**Endpoint** — адрес и UDP-порт удалённого пира (`host:port`), куда отправляются инкапсулированные пакеты.

**PresharedKey** — необязательный симметричный ключ, добавляемый в рукопожатие для дополнительного слоя защиты (см. раздел о PSK).

**Noise_IKpsk2** — конкретный шаблон рукопожатия из протокола Noise, лежащий в основе WireGuard.

## Архитектура и модель безопасности

### Cryptokey routing

Модель WireGuard отличается от классических VPN тем, что маршрутизация и контроль доступа объединены в одну сущность — связку ключа и адресов:

- **На отправку.** Когда пакет попадает в интерфейс `wg0`, WireGuard смотрит адрес назначения и ищет пир, в чьих `AllowedIPs` содержится этот адрес. Найденному пиру пакет шифруется его публичным ключом и уходит на его `Endpoint`. Если ни один пир не подходит — пакет отбрасывается с ошибкой «no valid peer».
- **На приём.** Пришедший по UDP зашифрованный пакет расшифровывается приватным ключом, определяется пир-отправитель, и исходный адрес внутри пакета проверяется на принадлежность `AllowedIPs` этого пира. Пакет с несогласованным источником отбрасывается.

Отсюда простое правило: **`AllowedIPs` — это одновременно «куда маршрутизировать» и «откуда разрешено принимать»**. Именно поэтому `AllowedIPs` на сторонах одного туннеля должны быть взаимно согласованы, а несимметричные списки — частая причина «handshake есть, а трафика нет».

### Модель доверия и ключи

- **Нет центра сертификации.** Аутентификация основана на **статических публичных ключах**: обе стороны заранее знают публичный ключ друг друга, приватные ключи никогда не покидают узлы.
- **Identity = пара ключей.** Публичный ключ — это идентификатор пира; в отличие от IP-адреса, он не привязан к местоположению (роуминг).
- **Нет согласования алгоритмов.** Набор криптографических примитивов фиксирован протоколом — «downgrade»-атак через переговоры нет.
- **Нет рукопожатия уровня IKE.** WireGuard не использует отдельный демон переговоров, как IPsec/IKE или TLS: рукопожатие встроено в сам протокол (см. ниже) и не требует внешних сертификатов или сложных конфигураций.
- **Отзыв доступа** = удаление `[Peer]` на сервере. Уже установленная сессия не разрывается мгновенно — клиент с удалённым ключом не сможет переподключиться после истечения сессии.

### Реализация: модуль ядра и userspace

| Аспект | Kernel (модуль) | Userspace (`wireguard-go`, BoringTun) |
|--------|-----------------|----------------------------------------|
| Скорость | Максимальная | Обычно ниже (syscall/копирование) |
| Потребление CPU | Ниже | Выше |
| Когда | Linux 5.6+ / DKMS | Платформы без модуля (macOS, Windows, старые ядра) |

На Linux в проде применяется модуль ядра. Метрики, тюнинг очередей (RSS/RPS/XPS) и выбор реализации — [wireguard-performance.md](./wireguard-performance.md).

### Сравнение с другими VPN

| Параметр | WireGuard | IPsec (IKEv2) | OpenVPN | GRE+IPsec |
|----------|-----------|---------------|---------|-----------|
| **Уровень** | L3 | L3 | L2/L3 | L3 |
| **Транспорт** | UDP 51820 | UDP 500/4500, ESP | TCP/UDP | IP 47 + ESP |
| **Шифрование** | ChaCha20-Poly1305 | AES-GCM/CBC | OpenSSL | AES-GCM |
| **Overhead** | 60 байт | 50-73 байт | 57-73 байт | 74-101 байт |
| **MTU** | 1420 | 1400-1420 | 1390-1420 | 1360-1400 |
| **Производительность** | ~7.8 Gbps | ~5.2 Gbps | ~1 Gbps | ~5.2 Gbps |
| **NAT Traversal** | Нативно (UDP) | NAT-T (ESP in UDP) | TCP bypass | Требует FOU |
| **Конфигурация** | 1 файл, 2 ключа | swanctl.conf + сертификаты | server.conf + ca/keys | strongSwan + GRE |
| **Мультикаст** | Нет | Route-based (да) | Нет | Да |

> Цифры производительности — ориентировочные (порядок величины на одном ядре современного CPU); реальные значения зависят от CPU, наличия SIMD-ускорения и размера пакета.
>
> **Подробное сравнение:** [GRE vs WireGuard](../Networking/Tunnels/gre/gre_vs_wireguard.md), [Расширенное сравнение VPN](../Networking/Tunnels/ipsec/ipsec.md#расширенное-сравнение-vpn)

## Протокол рукопожатия (Noise_IKpsk2)

Рукопожатие WireGuard основано на шаблоне `Noise_IKpsk2` (полная строка-идентификатор — `Noise_IKpsk2_25519_ChaChaPoly_BLAKE2s`). Оно устанавливает пару симметричных сессионных ключей за **один круговой обход (1-RTT)**: инициатор отправляет первое сообщение, получатель отвечает вторым, после чего инициатор может передавать зашифрованные данные. `0-RTT` в WireGuard нет — каждая сессия начинается с полного 1-RTT-рукопожатия.

### Сообщения рукопожатия

WireGuard различает четыре типа сообщений (поле `message_type`):

| Тип | Сообщение | Назначение |
|-----|-----------|------------|
| 1 | Handshake Initiation | инициатор → получатель: ephemeral-ключ, зашифрованный статический ключ, зашифрованная метка времени, MAC1/MAC2 |
| 2 | Handshake Response | получатель → инициатор: свой ephemeral-ключ, подтверждение сессии |
| 3 | Cookie Reply | ответ на рукопожатие под нагрузкой: зашифрованный cookie для защиты от подделки источника |
| 4 | Transport Data | зашифрованные пользовательские данные с счётчиком (nonce) |

**Первое сообщение** (initiation) содержит:
- `unencrypted_ephemeral` — публичный эфемерный ключ инициатора;
- `encrypted_static` — статический публичный ключ инициатора, зашифрованный на общем секрете `es`;
- `encrypted_timestamp` — метка времени TAI64N (защита от повторов), зашифрованная на общем секрете;
- `mac1` — MAC на публичном ключе получателя (отсеивает пакеты для «не тех» получателей);
- `mac2` — MAC на cookie (заполняется, только если получатель под нагрузкой уже прислал cookie reply).

**Второе сообщение** (response) подтверждает сессию и содержит эфемерный ключ получателя. В выработку ключей примешивается `PresharedKey` (этап `psk` шаблона `IKpsk2`); при отсутствии явного PSK используется значение по умолчанию (все нули).

**Порядок DH-операций** в шаблоне `IK`: `es`, `ss` (в initiation) и `ee`, `se` (в response). Асимметричная криптография (Curve25519) применяется только на этапе рукопожатия; весь дальнейший трафик шифруется симметрично (ChaCha20-Poly1305) — поэтому рукопожатие дорогое, а передача данных дешёвая.

### Таймеры, рекеинг и keepalive

Все константы протокола зафиксированы и одинаковы во всех реализациях (значения — из заголовков модуля ядра Linux):

| Константа | Значение | Смысл |
|-----------|----------|-------|
| `REKEY_TIMEOUT` | 5 с | минимальный интервал между повторными попытками рукопожатия (плюс случайный jitter до 333 мс) |
| `REKEY_AFTER_TIME` | 120 с | инициатор начинает новое рукопожатие, когда текущей сессии столько секунд |
| `REJECT_AFTER_TIME` | 180 с | сессия считается недействительной; пакеты старше — отбрасываются |
| `REKEY_ATTEMPT_TIME` | 90 с | после стольких секунд безуспешных попыток рукопожатие прекращается |
| `KEEPALIVE_TIMEOUT` | 10 с | если от пира что-то получено, но ответа не было, отправляется пустой keepalive-пакет |
| `REKEY_AFTER_MESSAGES` | 2^60 | по числу переданных пакетов инициируется новый сеанс |
| `REJECT_AFTER_MESSAGES` | ~2^64 | предел счётчика nonce |
| `INITIATIONS_PER_SECOND` | 50 | жёсткое ограничение частоты рукопожатий на пир |
| `MAX_PEERS_PER_DEVICE` | 2^20 | максимум пиров на один интерфейс (ядро) |

Ключи сессии ротируются примерно каждые `REKEY_AFTER_TIME` секунд, что обеспечивает постоянную смену эфемерных ключей и Perfect Forward Secrecy.

### Cookie-механизм и защита от флуда

`mac1` вычисляется для каждого сообщения рукопожатия и позволяет дешёво отбросить пакеты, отправленные не тому получателю. При перегрузке (много валидных, но дорогих в обработке рукопожатий) получатель отвечает сообщением **Cookie Reply** (тип 3) с зашифрованным cookie; после этого инициатор обязан добавлять корректный `mac2`, а «слепой» флуд с поддельных source-адресов отсекается. Дополнительно на каждый пир действует ограничение `INITIATIONS_PER_SECOND = 50`.

Практические правила фильтрации UDP 51820 (allowlist, rate limiting, rp_filter) — [wireguard-security.md](./wireguard-security.md).

### Роуминг и работа через NAT

WireGuard не привязывает пир к адресу: он запоминает последний достоверно полученный `Endpoint` конкретного публичного ключа и отвечает на него. Это даёт встроенный роуминг — когда клиент меняет публичный IP, сервер естественным образом «переориентирует» пир при следующем валидном пакете, без перезапуска интерфейса.

Из-за отсутствия активных keepalive по умолчанию для работы за NAT на клиенте задают `PersistentKeepalive = 25` (интервал в секундах), чтобы удерживать состояние в таблице NAT. Подробнее — [NAT и VPN](../Networking/Concepts/nat/nat_and_vpn.md).

Отдельный случай — **динамический публичный IP сервера** (не клиента): тогда на стороне сервера требуется принудительная перепривязка сокета (см. ниже), так как клиенты не смогут достучаться до старого адреса.

### Perfect Forward Secrecy

Каждый сеанс использует независимые эфемерные ключи, уничтожаемые после завершения. Компрометация долговременного статического ключа не раскрывает прошлый трафик. Однако обмен ключами построен на Curve25519, который уязвим к алгоритму Шора на квантовом компьютере — для защиты от этой угрозы применяют [Rosenpass](./rosenpass_overview.md) (постквантовый обмен ключами поверх WireGuard).

## Криптографические примитивы

WireGuard использует фиксированный минималистичный набор современных примитивов:

| Назначение | Алгоритм |
|------------|----------|
| Ключевой обмен (ECDH) | Curve25519 |
| Шифрование и аутентификация | ChaCha20-Poly1305 (AEAD) |
| Аутентификация пакетов | Poly1305 |
| Хеширование | BLAKE2s |
| KDF (вывод ключей) | HKDF на основе BLAKE2s |

AEAD-конструкция ChaCha20-Poly1305 аутентифицирует и шифрует одновременно: отдельной подписи пакета нет, MAC встроен в контейнер.

## PresharedKey (PSK) — дополнительный слой

`PresharedKey` — необязательный 32-байтовый симметричный ключ, добавляемый в рукопожатие (этап `psk` шаблона `Noise_IKpsk2`). Он не заменяет ключи Curve25519, а примешивается к ним, давая дополнительные свойства:

- защита от «запиши сейчас — расшифруй потом» на квантовом компьютере (постквантовый вклад), поскольку PSK — заранее распределённый секрет;
- дополнительный фактор: для установления сессии нужно владеть и статическим ключом, и PSK.

PSK задаётся одинаково на обоих концах одной строкой:

```ini
[Peer]
PublicKey = <peer_public_key>
PresharedKey = <base64_psk>
```

Сгенерировать ключ: `wg genpsk`. При использовании [Rosenpass](./rosenpass_overview.md) PSK обновляется автоматически.

## Формат конфигурации

WireGuard использует простой INI-подобный формат (`wg0.conf`). Драйвер (`wg`) понимает только ядровые параметры; `wg-quick` дополнительно распознаёт «сахар» для настройки сети.

```ini
[Interface]
# Локальные параметры (приватный ключ, адрес, iptables)
PrivateKey = <client_private_key>
Address = 10.0.0.2/32
DNS = 1.1.1.1
MTU = 1420

[Peer]
# Параметры удалённого узла (публичный ключ, endpoint, allowed-ips)
PublicKey = <server_public_key>
Endpoint = 203.0.113.1:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
```

### Параметры `[Interface]`

| Ключ | Источник | Назначение |
|------|----------|------------|
| `PrivateKey` | `wg` | приватный ключ узла |
| `Address` | `wg-quick` | один или несколько IP-адресов (можно повторять) |
| `ListenPort` | `wg` | UDP-порт прослушивания (по умолчанию — случайный) |
| `DNS` | `wg-quick` | DNS-серверы, подставляемые при подъёме (`resolvconf`/`systemd-resolved`) |
| `MTU` | `wg-quick` | MTU интерфейса; если не задан — вычисляется автоматически |
| `Table` | `wg-quick` | таблица маршрутизации: `auto` (по умолчанию), `off` или номер таблицы |
| `PreUp`/`PostUp`/`PreDown`/`PostDown` | `wg-quick` | команды при подъёме/опускании; `%i` подставляется именем интерфейса |
| `SaveConfig` | `wg-quick` | при `true` сохраняет текущее состояние интерфейса в файл при остановке |
| `FwMark` | `wg` | метка (fwmark) для исходящих инкапсулированных UDP-пакетов |

### Параметры `[Peer]`

| Ключ | Назначение |
|------|------------|
| `PublicKey` | публичный ключ удалённого пира |
| `PresharedKey` | необязательный PSK (см. выше) |
| `AllowedIPs` | префиксы маршрутов + разрешённые источники (cryptokey routing) |
| `Endpoint` | адрес:порт пира; для сервера обычно опускается |
| `PersistentKeepalive` | интервал keepalive в секундах (для NAT) |

### MTU, маршруты и приоритет команд

- **Автоматический MTU.** Если `MTU` не задан, `wg-quick` определяет его из маршрута до `Endpoint` (или из default-маршрута) и **вычитает 80 байт** — резерв под внешний IP (IPv4 или IPv6) + UDP (8) + заголовок WireGuard (32) + тег (16). Для типового пути с MTU 1500 итог — **1420**.
- **Маршруты из `AllowedIPs`.** `wg-quick` добавляет маршрут до каждой сети из `AllowedIPs`. Для default-маршрута (`0.0.0.0/0`) задействуется `ip rule`/fwmark, чтобы не терять связность с самим сервером. При значении `Table = off` маршруты не создаются (для PBR/динамической маршрутизации — [wireguard-routing.md](./wireguard-routing.md)).
- **`SaveConfig = true`** перезаписывает файл конфигурации при остановке интерфейса — изменения, внесённые в файл «на лету», будут потеряны. По умолчанию выключено.
- **Приоритет.** Настройки, применённые через `wg set` к «живому» интерфейсу, действуют до переприменения конфига; `wg-quick save` переносит их в файл. Команды из разных ключей `PreUp`/`PostUp` выполняются в порядке следования.

## Практические сценарии

### Предварительные требования и установка

#### Версии ядра и пакетов

| Компонент | Минимальная версия | Рекомендуемая |
|-----------|-------------------|---------------|
| **Ядро Linux** | 5.6 (нативная поддержка) | 5.15+ |
| **wireguard-tools** | 1.0 | 1.0.x |
| **iproute2** | 5.10 | 5.15+ |

#### Проверка наличия модуля ядра

```bash
# Проверка модуля wireguard
modinfo wireguard | head -3
# → filename:       /lib/modules/$(uname -r)/kernel/drivers/net/wireguard.ko
# → license:        GPL v2

# Проверка загруженности
lsmod | grep wireguard
# → wireguard           110592  0

# Если модуль не загружен
sudo modprobe wireguard
```

Для старых ядер (< 5.6) или вендорских ядер без обратного порта модуль ставят как DKMS-пакет (`wireguard-dkms` в Debian/Ubuntu, `kmod-wireguard` из EPEL для RHEL-семейства). Автозагрузку при старте системы можно закрепить:

```bash
echo wireguard | sudo tee /etc/modules-load.d/wireguard.conf
```

#### Установка

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install wireguard wireguard-tools

# RHEL/CentOS/Rocky 8+
sudo dnf install kmod-wireguard wireguard-tools

# Arch Linux
sudo pacman -S wireguard-tools
```

#### Включение IP-форвардинга

Форвардинг нужен, если узел работает как шлюз (site-to-site, remote access со шлюзом по умолчанию).

```bash
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/90-wireguard.conf

# Если в туннеле используется IPv6
sudo sysctl -w net.ipv6.conf.all.forwarding=1
echo "net.ipv6.conf.all.forwarding = 1" | sudo tee -a /etc/sysctl.d/90-wireguard.conf

sudo sysctl -p /etc/sysctl.d/90-wireguard.conf
```

### Генерация ключей

- **Приватный ключ** (private key) — хранится в секрете, используется для дешифрования и аутентификации.
- **Публичный ключ** (public key) — может быть передан другим участникам, идентифицирует пир.

```bash
# Пара ключей
wg genkey | tee privatekey | wg pubkey > publickey

# PresharedKey (необязательно, для дополнительного слоя)
wg genpsk > preshared.key

# Публичный ключ из готового приватного
wg pubkey < privatekey
```

Права на приватные ключи — только для владельца:

```bash
chmod 600 privatekey
```

Каждый узел хранит свой приватный ключ и обменивается с пирами только публичными. Управление флотом ключей (инвентарь, ротация, отзыв) — [wireguard-key-management.md](./wireguard-key-management.md).

### Управление интерфейсом

#### `wg-quick` и systemd

Штатный способ на Linux — файл `/etc/wireguard/wg0.conf` и сервис-шаблон `wg-quick@`:

```bash
sudo wg-quick up wg0          # поднять интерфейс по /etc/wireguard/wg0.conf
sudo wg-quick down wg0        # опустить (снимает маршруты/правила из PostUp)
sudo wg-quick save wg0        # сохранить текущее состояние в конфиг

# Автозапуск при загрузке
sudo systemctl enable --now wg-quick@wg0
sudo systemctl status wg-quick@wg0
```

Проверка состояния соединения:

```bash
sudo wg show
```

#### `wg` без `wg-quick`

Для ручного управления или когда маршрутизацией правит внешний инструмент:

```bash
# Создание интерфейса и применение ядровых параметров
sudo ip link add wg0 type wireguard
sudo wg setconf wg0 wg0.conf        # только key/peer-параметры
sudo ip addr add 10.0.0.2/32 dev wg0
sudo ip link set wg0 up

# Изменения на живом интерфейсе (без перезапуска)
sudo wg set wg0 peer <pubkey> allowed-ips 10.0.0.4/32
sudo wg set wg0 listen-port 51820

# Применить конфиг без разрыва активных сессий (вносит только изменения)
sudo wg syncconf wg0 <(wg-quick strip wg0)   # strip убирает wg-quick-параметры

# Добавить пиров, не трогая существующих
sudo wg addconf wg0 extra-peers.conf
```

#### `systemd-networkd`

Альтернатива `wg-quick` с более тонким контролем и лучшей интеграцией в systemd. Требуется systemd ≥ 237.

**`/etc/systemd/network/wg0.netdev`:**

```ini
[NetDev]
Name=wg0
Kind=wireguard

[WireGuard]
PrivateKey = <server_private_key>
ListenPort = 51820

[WireGuardPeer]
PublicKey = <client_public_key>
AllowedIPs = 10.0.0.2/32
Endpoint = 203.0.113.2:51820
PersistentKeepalive = 25
```

**`/etc/systemd/network/wg0.network`:**

```ini
[Match]
Name=wg0

[Network]
Address=10.0.0.1/24
IPForward=yes
```

Активация:

```bash
sudo systemctl restart systemd-networkd
sudo networkctl status wg0
# → 3: wg0
# →     Type: wireguard
# →     State: routable (configuring)
# →   Address: 10.0.0.1/24
```

#### NetworkManager (`nmcli`)

NetworkManager с версии 1.16 имеет нативную поддержку WireGuard (нужен модуль ядра). Она даёт профили, интеграцию с DNS и firewalld — удобно на RHEL/Fedora, десктопах и в системах централизованного управления.

```bash
# Импорт готового wg0.conf как профиля
sudo nmcli connection import type wireguard file wg0.conf

# Создание профиля вручную
sudo nmcli connection add type wireguard con-name wg0 ifname wg0
sudo nmcli connection modify wg0 ipv4.method manual ipv4.addresses 10.0.0.2/24
sudo nmcli connection modify wg0 wireguard.private-key "$(cat privatekey)"
sudo nmcli connection modify wg0 wireguard.peers \
  '<server_pubkey> endpoint=vpn.example.com:51820 allowed-ips=0.0.0.0/0;::/0'
sudo nmcli connection up wg0

# Применить изменения профиля к активному интерфейсу без разрыва
sudo nmcli device reapply wg0
```

Особенности:
- свойство `wireguard.peer-routes` (по умолчанию включено) автоматически добавляет маршруты по `AllowedIPs`;
- `Endpoint`, заданный DNS-именем, NetworkManager переразрешает (в том числе при смене DNS), что упрощает работу с плавающим адресом сервера.

### Firewalld (RHEL/Fedora)

На хостах с firewalld открывают порт и, при необходимости, включают masquerade для транзитного трафика:

```bash
# Порт WireGuard (есть готовый сервис wireguard, но можно и портом)
sudo firewall-cmd --permanent --zone=public --add-port=51820/udp
# или: firewall-cmd --permanent --zone=public --add-service=wireguard

# Если сервер раздаёт клиентам выход в интернет
sudo firewall-cmd --permanent --zone=public --add-masquerade

sudo firewall-cmd --reload
```

Для `nftables`/`iptables`-шаблонов правил — [VPN Firewall Templates](../Networking/Tunnels/vpn_firewall_templates.md); hardening и rate limiting — [wireguard-security.md](./wireguard-security.md).

### Обновление Endpoint при динамическом IP сервера

Если публичный IP-адрес сервера WireGuard меняется, клиенты теряют к нему доступ: сервер продолжает ожидать подключения на старом адресе. Решение — периодическая принудительная перепривязка слушающего сокета без полного перезапуска службы.

**Предупреждение:** метод решает проблему только на стороне сервера. Если используется файрвол (`ufw`, `iptables`, firewalld) или облачные правила безопасности, правила для нового IP нужно обновлять отдельно.

#### Скрипт перепривязки сокета

Создайте файл `/usr/local/bin/wg-rebind.sh`:

```bash
#!/bin/bash
#
# Скрипт для принудительной перепривязки слушающего сокета WireGuard.
# Это необходимо для серверов, работающих с динамическим IP-адресом.

# --- Переменные ---
readonly IFACE="wg0"
readonly PORT="51820"
# --- Конец переменных ---

set -o nounset
set -o errexit
set -o pipefail

echo "Rebinding WireGuard interface '$IFACE' to port $PORT..."

# Команда `wg set ... listen-port` заставляет WireGuard перепривязать сокет,
# что позволяет ему определить новый публичный IP-адрес сервера.
wg set "$IFACE" listen-port "$PORT"

echo "Successfully rebound."
```

```bash
sudo chown root:root /usr/local/bin/wg-rebind.sh
sudo chmod 755 /usr/local/bin/wg-rebind.sh
```

#### Юниты systemd

`/etc/systemd/system/wg-rebind.service`:

```ini
[Unit]
Description=Rebind WireGuard listening port to its dynamic IP
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/wg-rebind.sh
```

`/etc/systemd/system/wg-rebind.timer` (запуск каждые 3 минуты):

```ini
[Unit]
Description=Run wg-rebind.service every 3 minutes

[Timer]
# Запустить через 1 минуту после загрузки
OnBootSec=1min
# Запускать каждые 3 минуты после активации
OnUnitActiveSec=3min

[Install]
WantedBy=timers.target
```

#### Активация

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wg-rebind.timer

# Проверка
systemctl list-timers | grep wg-rebind
journalctl -u wg-rebind.service -f
```

### PostUp/PostDown

`PostUp`/`PostDown` выполняются при подъёме/опускании интерфейса и используются для автоматизации firewall и маршрутизации. `%i` подставляется именем интерфейса.

**Пример с iptables (shuttle-шлюз):**

```ini
[Interface]
PrivateKey = <server_private_key>
Address = 10.0.0.1/24
ListenPort = 51820

PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -i %i -j ACCEPT
```

**Пример с nftables:**

```ini
[Interface]
PrivateKey = <server_private_key>
Address = 10.0.0.1/24
ListenPort = 51820

PostUp = nft add rule inet filter input iifname eth0 udp dport 51820 accept
PostDown = nft delete rule inet filter input iifname eth0 udp dport 51820 accept
PostUp = nft add rule inet filter forward iifname wg0 oifname eth0 accept
PostDown = nft delete rule inet filter forward iifname wg0 oifname eth0 accept
```

Per-peer правила `wg-quick` не поддерживает — их выносят во внешний скрипт или отдельные интерфейсы (сегментация — [wireguard-routing.md](./wireguard-routing.md)).

### Kill Switch (защита от утечки IP)

Kill Switch блокирует весь трафик при разрыве VPN-соединения, предотвращая утечку реального IP.

**Предупреждение:** скрипт ниже вызывает `iptables -F`, то есть сбрасывает существующие правила filter/nat. На хосте с Docker, wireguard-маршрутизацией (`fwmark`) или другими NAT-правилами это недопустимо — применяйте Kill Switch только на выделенном клиенте либо адаптируйте откат под свой ruleset.

```bash
#!/bin/bash
#
# Kill Switch для WireGuard (клиент)

IFACE="wg0"
# Публичный IP VPN-сервера (разрешается всегда, чтобы держать туннель)
WG_SERVER_IP="203.0.113.1"
# Порт WireGuard на сервере
WG_SERVER_PORT="51820"
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
    iptables -A OUTPUT -o "$IFACE" -j ACCEPT

    # Разрешение трафика к VPN-серверу (для поддержания туннеля)
    iptables -A OUTPUT -o "$PHYS_IFACE" -d "$WG_SERVER_IP" -p udp --dport "$WG_SERVER_PORT" -j ACCEPT

    # Разрешение DHCP (иначе клиент потеряет адрес и шлюз)
    iptables -A OUTPUT -o "$PHYS_IFACE" -p udp --dport 67 -j ACCEPT
    iptables -A OUTPUT -o "$PHYS_IFACE" -p udp --dport 68 -j ACCEPT

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
sudo nano /etc/wireguard/killswitch.sh
sudo chmod +x /etc/wireguard/killswitch.sh
```

Привязка к интерфейсу — в `wg0.conf`:

```ini
[Interface]
...
PostUp = /etc/wireguard/killswitch.sh enable
PostDown = /etc/wireguard/killswitch.sh disable
```

Проверка:

```bash
sudo wg-quick up wg0
sudo iptables -L -n

# После остановки VPN трафик наружу должен блокироваться
sudo wg-quick down wg0
curl --max-time 5 ifconfig.me
# → curl: (28) Connection timed out
```

> На RHEL/Fedora эквивалент Kill Switch строится на firewalld-политике (ingress-zone `HOST`, egress-zone с target `DROP` и исключением адреса VPN-сервера) — см. [Firewalld](#firewalld-rhelfedora).

### Развёртывание клиентов на десктопах и мобильных устройствах

WireGuard поднимается вручную (`wg-quick`) либо через официальные клиенты. Для массового развёртывания удобен импорт конфига.

**Windows:**
- Клиент с [wireguard.com/install](https://www.wireguard.com/install/), импорт `wg0.conf` (кнопка Import Tunnel). GUI создаёт сетевой адаптер.
- Если в конфиге не задан `DNS`, после подключения внешние имена могут перестать резолвиться — указывайте `DNS` явно.

**macOS:**
- Официальный клиент из App Store, аналогичный импорт конфига.
- При проблемах с DNS проверьте порядок серверов в `scutil --dns` (см. [vpn-dns.md](./vpn-dns.md)).

**iOS / Android:**
- Официальные приложения WireGuard (на Android без root). Конфиг передаётся QR-кодом (Scan from QR) — этим пользуются панели вроде wg-easy (см. [wireguard-key-management.md](./wireguard-key-management.md)).
- Мобильные клиенты не выполняют `PostUp`/`PostDown`: правила firewall/NAT на клиенте задаются статически либо не используются.

**Практическая проверка клиента:**

```bash
# Linux-клиент: статус пира
sudo wg show wg0
# → peer: <server_pubkey>
# →   endpoint: 203.0.113.1:51820
# →   allowed ips: 10.0.0.0/24
# →   latest handshake: 2 seconds ago
# →   transfer: 12.3 MiB received, 4.5 MiB sent
```

Массовое развёртывание конфигов на флот (Ansible, GitOps) — [VPN Automation](../Networking/Tunnels/vpn_automation.md); корпоративный выкат на Windows/macOS (GPO, MDM, тихая установка, `.mobileconfig`) — [wireguard-client-deployment.md](./wireguard-client-deployment.md).

### Резервное копирование и восстановление

```bash
# Бэкап ключей и конфигов
sudo tar czf /backup/wireguard-$(date +%F).tar.gz /etc/wireguard/

# Восстановление
sudo tar xzf /backup/wireguard-2025-01-15.tar.gz -C /
sudo systemctl restart wg-quick@wg0
```

## Диагностика

Полный универсальный чек-лист — [VPN Troubleshooting](../Networking/Tunnels/vpn_troubleshooting_universal.md).

### Состояние и рукопожатия

```bash
# Полное состояние всех интерфейсов
sudo wg show

# Ключевые срезы по конкретному интерфейсу
sudo wg show wg0 latest-handshakes   # метка времени последнего рукопожатия на пир
sudo wg show wg0 transfer            # счётчики rx/tx на пир
sudo wg show wg0 endpoints           # текущий endpoint пира
sudo wg show wg0 allowed-ips         # префиксы пира
sudo wg show wg0 dump                # машиночитаемый формат одной строкой

# Если latest-handshakes пуст — нет связи на уровне ключей/сети
```

Признак проблем: отсутствие рукопожатия → не доходит UDP 51820 (firewall/NAT/неверный Endpoint); рукопожатие есть, но нет трафика → рассогласованы `AllowedIPs` или MTU.

### Маршруты и статистика

```bash
# Детали интерфейса и статистика
ip -d link show wg0
ip -s link show wg0
# → RX: bytes=... packets=... errors=0 dropped=0
# → TX: bytes=... packets=... errors=0 dropped=0

# Фактический путь до ресурса
ip route get 10.0.0.2
ip route show dev wg0

# IP-форвардинг и фильтрация поддельных source
sysctl net.ipv4.ip_forward
sysctl net.ipv4.conf.all.rp_filter

# conntrack инкапсулированного трафика
conntrack -L -p udp --dport 51820 2>/dev/null

# Слушающий сокет и логи ядра
ss -lun 'sport = :51820'
dmesg -T | grep -i wireguard
```

Анализ инкапсулированного трафика (`tcpdump`/Wireshark) — [Wireshark и анализ сетевого трафика](../Networking/ServicesAndTools/Wireshark/definitions.md):

```bash
sudo tcpdump -i any udp port 51820     # внешний инкапсулированный трафик
sudo tcpdump -i wg0 port 22            # расшифрованный трафик внутри туннеля
```

### Типичные ошибки

| Симптом | Вероятная причина | Диагностика | Решение |
|---------|-------------------|-------------|---------|
| `Unable to modify interface: Operation not permitted` | Нет прав root | `whoami` | `sudo wg-quick up wg0` |
| Нет рукопожатий | Firewall блокирует UDP 51820 | `sudo wg show latest-handshakes` пуст | Разрешить UDP 51820 на обоих концах |
| `No such device` | Модуль wireguard не загружен | `lsmod \| grep wireguard` | `sudo modprobe wireguard` |
| Handshake есть, но пинга нет | `AllowedIPs` не покрывают нужные сети | `sudo wg show allowed-ips` | Добавить подсеть в `AllowedIPs` |
| Пинг идёт, TCP зависает | MTU слишком велик | `ping -M do -s 1400 <remote>` | Уменьшить MTU (`ip link set wg0 mtu 1420`) |
| DNS не работает через VPN | DNS не задан или утечка | `resolvectl status wg0` | Добавить `DNS = ...` в `[Interface]` |
| Туннель рвётся при смене IP клиента | Нет keepalive / сервер не видит роуминг | `sudo wg show` — endpoint не обновляется | `PersistentKeepalive = 25` на клиенте |
| `Handshake for peer did not complete after 5 seconds` | Неверный ключ или Endpoint | Сверить ключи и endpoint на обоих концах | `PublicKey` = публичный ключ другого узла |
| Двойной NAT, туннель не поднимается | CGNAT | `traceroute <server>` — приватный хоп | UDP hole punching или relay |

## Граничные случаи и ограничения

1. **Нет мультикаста.** WireGuard — point-to-point unicast-L3 туннель и не рассылает broadcast/multicast по сегменту. Для multicast-задач применяют GRE или VXLAN; динамическая маршрутизация поверх WG — через unicast-протоколы (BGP; OSPF требует явного соседа, т.к. multicast-Hello не доставляется), см. [wireguard-routing.md](./wireguard-routing.md).
2. **Нет keepalive по умолчанию.** За NAT требуется `PersistentKeepalive = 25` (секунды).
3. **Одна сессия на пару ключей.** Для одной пары публичных ключей поддерживается одна активная сессия; при роуминге `Endpoint` обновляется автоматически.
4. **Нет встроенного PKI/CA.** Отзыв = удаление `[Peer]`. Для масштабных флотов нужен внешний инвентарь/автоматизация — [wireguard-key-management.md](./wireguard-key-management.md).
5. **Overhead и MTU.** Заголовок WireGuard добавляет 60 байт (IPv4-транспорт) или 80 байт (IPv6-транспорт); при вложенных туннелях (например, VXLAN/GRE внутри WG) MTU нужно уменьшать каскадно.
6. **Контейнеры.** В Docker/Kubernetes нужны `NET_ADMIN` (и `SYS_MODULE` для загрузки модуля) и доступ к `/dev/net/tun` — [vpn_in_containers.md](../Networking/Tunnels/vpn_in_containers.md).
7. **Кроссплатформенные клиенты.** Конфигурация на Windows/macOS/iOS/Android отличается (GUI или `wg-quick` в WSL); на мобильных недоступны `PostUp`/`PostDown`.
8. **Лимит пиров.** Ядровый модуль допускает до **2^20 (~1 048 576)** пиров на интерфейс (`MAX_PEERS_PER_DEVICE = 1U << 20`), userspace-реализация `wireguard-go` — до **2^16 (65 536)**. Практический предел задают память под index-хеш-таблицу и удобство управления, а не «256» (частая ошибка). Большие флоты удобнее делить между несколькими интерфейсами/концентраторами — [wireguard-ha.md](./wireguard-ha.md).
9. **Публичный адрес сервера.** Статический `Endpoint` клиента делает DNS/IP сервера точкой отказа — HA строится внешними средствами (Keepalived/Anycast) — [wireguard-ha.md](./wireguard-ha.md).
10. **Roaming Mischief.** Обновление `Endpoint` при роуминге происходит без дополнительной аутентификации (проверяется только подлинность самого пакета), поэтому активный MITM может подменить source IP и ретранслировать трафик — расшифровать его он не способен, но «прибить» адрес-привязку сможет. Для статических site-to-site пиров endpoint можно закрепить firewall-правилом на конкретный адрес; для мобильных клиентов (Wi-Fi→LTE) привязка неприменима — от roaming-атак защищают общие меры периметра. Подробно — [Known Limitations: Roaming Mischief](https://www.wireguard.com/known-limitations/).
11. **Нет встроенного failover между Endpoint у клиента.** У одного пира поддерживается только один endpoint (два `[Peer]` с одним `PublicKey` невозможны — записи ключатся по публичному ключу). Практические паттерны отказоустойчивости клиента: (1) DNS-имя шлюза с низким TTL и периодический `reresolve-dns.sh`; (2) серверный VIP/Anycast — клиентский конфиг не меняется ([wireguard-ha.md](./wireguard-ha.md)); (3) два туннеля (основной и резервный концентратор) с разными `Endpoint` и разными метриками маршрутов по умолчанию — переключение ручное или скриптом, встроенного механизма нет.

## Лучшие практики

### Безопасность

```bash
# Приватные ключи — только владельцу
sudo chmod 600 /etc/wireguard/private.key

# Ограничивать AllowedIPs по назначению (не 0.0.0.0/0 там, где не нужен полный туннель)
# Хорошо:       AllowedIPs = 192.168.2.0/24, 10.0.0.2/32
# Плохо:        AllowedIPs = 0.0.0.0/0        (на сервере для site-to-site)

# Порт UDP 51820 — только от доверенных адресов либо с rate limiting
```

Развёрнутый hardening концентратора, rate limiting рукопожатий и анти-DDoS — [wireguard-security.md](./wireguard-security.md).

### MTU

| Сценарий | Рекомендуемый MTU | Пояснение |
|----------|-------------------|-----------|
| **WireGuard (чистый, IPv4-транспорт)** | 1420 | 1500 − 20 (IP) − 8 (UDP) − 32 (WG) − 20 (запас); совпадает с авто-расчётом `wg-quick` (1500 − 80) |
| **WireGuard + PPPoE** | 1400 | 1500 − 8 (PPPoE) − 60 (WG) − 32 (запас) |
| **WireGuard через IPsec** | 1360 | 1500 − 60 (IPsec) − 60 (WG) − 20 (запас) |

```bash
# Установка MTU
sudo ip link set wg0 mtu 1420

# MSS Clamping для TCP внутри туннеля
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -o wg0 -j TCPMSS --clamp-mss-to-pmtu
```

Расчёт overhead и MSS для всех стеков — [MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md); тюнинг под нагрузкой — [wireguard-performance.md](./wireguard-performance.md).

### Мониторинг

WireGuard не отдаёт метрик по сети. Состояние снимают из `wg show` (`latest-handshakes`, `transfer`) и экспортируют в Prometheus через node-exporter textfile collector или отдельный exporter (собственного WireGuard-коллектора у node_exporter нет). Полный набор метрик, SLI/SLO и алертинг — [vpn-monitoring.md](./vpn-monitoring.md); аудит подключений — [vpn-session-audit.md](./vpn-session-audit.md).

## Дополнительная информация

### Продолжения по WireGuard

- **[WireGuard — практическое руководство](../Networking/Tunnels/wireguard_practical.md)** — пошаговые сценарии site-to-site, remote access, Double Tunnel
- **[WireGuard — производительность и тюнинг](./wireguard-performance.md)** — kernel vs userspace, MTU/MSS, RSS/RPS/XPS
- **[WireGuard — управление ключами](./wireguard-key-management.md)** — инвентарь, ротация, флот клиентов, Vault, web-панели
- **[WireGuard — расширенная маршрутизация](./wireguard-routing.md)** — PBR, fwmark, Table, BGP/OSPF поверх туннеля
- **[WireGuard — защита концентратора](./wireguard-security.md)** — rate limiting handshake, anti-DDoS, hardening
- **[WireGuard — высокая доступность](./wireguard-ha.md)** — Active/Passive, Keepalived, ECMP/Anycast
- **[WireGuard — совместимость с оборудованием](./wireguard-interop.md)** — site-to-site с MikroTik RouterOS 7, pfSense, OPNsense
- **[WireGuard — массовое развёртывание клиентов](./wireguard-client-deployment.md)** — GPO/MSI для Windows, `.mobileconfig`/MDM для macOS и iOS
- **[Rosenpass: постквантовая защита WireGuard](./rosenpass_overview.md)** — гибридный обмен ключами, PSK

### Сравнение и выбор

- **[GRE vs WireGuard](../Networking/Tunnels/gre/gre_vs_wireguard.md)** — сравнение протоколов, критерии выбора, миграция GRE→WireGuard
- **[IPsec (IKEv2)](../Networking/Tunnels/ipsec/ipsec.md)** — альтернатива для enterprise с EAP-RADIUS
- **[OpenVPN](../Networking/Tunnels/openvpn.md)** — классический VPN на базе TLS/PKI
- **[Remote Access VPN — выбор](../Networking/Tunnels/remote_access_vpn.md)** — WireGuard vs OpenVPN vs IPsec: когда что брать
- **[Mesh-VPN решения](./mesh-vpn-overview.md)** — Netbird, Netmaker и другие self-hosted координаторы
- **[VPN под DPI](./vpn-dpi-obfuscation.md)** — работа в ограничивающих сетях
- **[Proxy vs VPN](../Networking/Concepts/proxy-vs-vpn.md)** — когда туннель, а когда прокси

### Инфраструктура и эксплуатация

- **[VPN в контейнерах](../Networking/Tunnels/vpn_in_containers.md)** — Docker и Kubernetes, включая Cilium/Calico WireGuard
- **[VPN Automation — Ansible и Terraform](../Networking/Tunnels/vpn_automation.md)** — управление конфигурацией через IaC
- **[NAT и VPN](../Networking/Concepts/nat/nat_and_vpn.md)** — работа за NAT, PersistentKeepalive, CGNAT
- **[MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead и MSS Clamping
- **[VPN Troubleshooting](../Networking/Tunnels/vpn_troubleshooting_universal.md)** — универсальный чек-лист диагностики
- **[VPN: чек-лист приёмки развёртывания](./vpn-acceptance-checklist.md)** — smoke, HA-drill, soak, критерии отката
- **[Документация WireGuard](https://www.wireguard.com/protocol/)** — спецификация протокола

### Смежные темы

- **[IPv6 внутри VPN](./vpn-ipv6.md)** — адресация, dual-stack, IPv6 firewall
- **[DNS внутри VPN](./vpn-dns.md)** — split DNS, DNS over tunnel
- **[Аутентификация и SSO/MFA для VPN](./vpn-authentication.md)** — OIDC, LDAP/RADIUS, TOTP
- **[Аудит сессий VPN](./vpn-session-audit.md)** — журналирование подключений, NFLOG, RADIUS accounting
- **[Zero Trust](../Networking/Concepts/zero_trust_overview.md)** — модель доступа, при которой VPN не единственный слой
- **[SSH-туннели и bastion](../Linux/Security/ssh/ssh_usage_and_tunnels.md)** — доступ и выход через промежуточные узлы
- **[iptables и Docker: DOCKER-USER](../Docker/Docker_network/troubleshooting/iptables_integration.md)** — фильтрация трафика к контейнерам
- **[Сетевые политики Docker](../Docker/Docker_network/docker_network_policies.md)** — Defense-in-Depth, `--internal` сети
