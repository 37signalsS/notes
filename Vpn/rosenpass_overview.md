# Rosenpass: Постквантовая защита для WireGuard VPN

**Rosenpass** — это протокол обмена ключами, использующий методы, защищенные от атак квантовых компьютеров.

## Определения

**Rosenpass** — открытый протокол постквантового обмена ключами, разработанный для защиты VPN-туннелей от атак квантовых компьютеров. Он работает в связке с WireGuard, добавляя к стандартному обмену ключами (Curve25519) постквантовые примитивы, устойчивые к алгоритму Шора.

**PSK (Pre-Shared Key)** — симметричный ключ, заранее распределённый между пирами. В WireGuard задаётся через параметр `PresharedKey` в конфигурации `wg0.conf` и добавляется к стандартному handshake.

**Постквантовая безопасность (post-quantum security)** — устойчивость криптографических алгоритмов к атакам квантовых компьютеров, способных эффективно решать задачи факторизации и дискретного логарифмирования, лежащие в основе RSA и ECDH.

**Гибридная безопасность (hybrid security)** — комбинация доквантового и постквантового обмена ключами, обеспечивающая защиту как против современных, так и против будущих квантовых угроз. Rosenpass+WireGuard сохраняет безопасность WireGuard и добавляет защиту от квантовых компьютеров.

**Harvest Now, Decrypt Later (HNDL)** — класс атак, при которых противник записывает зашифрованный трафик сегодня и расшифровывает его позже, когда у него появятся квантовые компьютеры. Rosenpass защищает от таких атак за счёт постквантовой безопасности обмена ключами.

## Назначение

Он добавляет эти методы к VPN WireGuard, превращая ваш VPN в защищенный протокол от атак квантовых компьютеров. Rosenpass обеспечивает **постквантовую безопасность**, в то время как WireGuard — **доквантовую безопасность** и высокоскоростную передачу данных. Для использования Rosenpass нет необходимости отказываться от WireGuard, они работают в связке.

Rosenpass решает проблему уязвимости WireGuard к будущим квантовым компьютерам. Поскольку WireGuard использует Curve25519 для обмена ephemeral-ключами, он остаётся уязвимым к алгоритму Шора на квантовых компьютерах достаточной мощности. Rosenpass добавляет постквантовый обмен ключами, после чего полученный секрет передаётся в WireGuard через интерфейс PSK.

## Основные концепции

### Архитектура и принцип работы

Rosenpass реализован как userspace-демон, написанный на Rust. Он не изменяет модуль ядра WireGuard, а взаимодействует с ним через стандартный интерфейс `wg` (netlink) и утилиту `wg`.

**Ключевые свойства архитектуры:**
- **Не требует модификации ядра:** Rosenpass работает как отдельный процесс в userspace
- **Интеграция через PSK:** Полученный постквантовый секрет передаётся WireGuard через параметр `PresharedKey`
- **Параллельная работа:** Rosenpass и WireGuard работают одновременно, не мешая друг другу
- **Один интерфейс:** Демон `rp` управляет ровно одним интерфейсом WireGuard
- **Гибридная безопасность:** Используются оба обмена ключами (классический + постквантовый)

**Принцип работы:**
1. Rosenpass генерирует пару ключей (классический + постквантовый, например Classic McEliece + Kyber)
2. При установлении соединения с пиром выполняется постквантовый обмен ключами (KEM)
3. Полученный общий секрет хешируется и передаётся WireGuard как PSK
4. WireGuard выполняет стандартный Noise_IK handshake + использует PSK
5. После handshake весь трафик шифруется стандартными методами WireGuard (ChaCha20-Poly1305)
6. Rosenpass периодически (каждые 120 секунд) обновляет PSK, обеспечивая perfect forward secrecy

### Криптографические примитивы

Rosenpass использует два постквантовых алгоритма обмена ключами, обеспечивая гибридную безопасность:

| Алгоритм | Тип | Назначение | Параметр |
|----------|-----|------------|----------|
| **Classic McEliece** | Кодовая криптография | Post-quantum KEM | ~1 MB публичный ключ |
| **CRYSTALS-Kyber (ML-KEM)** | Решёточная криптография | Post-quantum KEM | ML-KEM-768 |

**Почему два алгоритма?**
- Classic McEliece устойчив к известным атакам, но имеет большой размер открытого ключа (~1 МБ)
- Kyber (ML-KEM) компактнее, но является новым алгоритмом
- Их комбинация обеспечивает разнообразие: если один алгоритм окажется уязвимым, второй остаётся защитой

### Жизненный цикл обмена ключами

**Этап 1 — Генерация ключей:**
- Rosenpass генерирует пару ключей Classic McEliece и пару ключей ML-KEM
- Публичные ключи обмениваются с пирами (через конфигурационный файл или signalling channel)

**Этап 2 — Установление соединения:**
- При запуске или по триггеру происходит обмен постквантовыми ключами с каждым пиром
- Вычисляется общий секрет на основе обоих KEM-алгоритмов
- Секрет хешируется через HKDF и преобразуется в 256-битный ключ для WireGuard PSK

**Этап 3 — Интеграция с WireGuard:**
- Rosenpass вызывает `wg set <interface> peer <pubkey> preshared-key <pskfile>`
- WireGuard добавляет PSK к стандартному handshake
- После этого трафик защищён как Curve25519 + PSK

**Этап 4 — Периодическая ротация:**
- Каждые 120 секунд Rosenpass повторяет обмен ключами
- Новый PSK автоматически обновляется в WireGuard без разрыва соединения
- Это обеспечивает perfect forward secrecy: компрометация текущего ключа не даёт доступ к прошлому трафику

### Интеграция с WireGuard

**WireGuard остаётся неизменным:**
- Модуль ядра не требует модификаций
- Стандартный конфигурационный формат (`wg0.conf`)
- Обычные утилиты (`wg`, `wg-quick`)
- Нативная производительность (модуль ядра)

**Rosenpass расширяет безопасность:**
- Добавляет PSK через `wg` netlink interface
- PSK используется в Noise_IK handshake в дополнение к Curve25519
- Это не ослабляет WireGuard: комбинация Curve25519 + PSK не менее безопасна, чем Curve25519 alone

**Преимущества связки:**
- WireGuard остаётся быстрым (ядро, ChaCha20-Poly1305)
- Добавляется защита от квантовых компьютеров
- Автоматическая ротация ключей
- Открытый исходный код, проверяемость

### Почему Rosenpass, а не WireGuard-alone?

**Угрозы:**
- **Quantum Computing:** Квантовые компьютеры с ~4000 стабильными кубитами могут взломать Curve25519 за часы
- **HNDL-атаки:** Запись зашифрованного трафика сегодня для расшифровки через 10–20 лет
- **Срок хранения данных:** Многие системы хранят данные 10+ лет, что делает их уязвимыми в будущем

**Ограничения WireGuard:**
- Нет встроенного постквантового обмена ключами
- Curve25519 устойчив только к классическим компьютерам
- Требуется внешнее решение для постквантовой безопасности

**Rosenpass решает это:**
- Не меняя архитектуру WireGuard
- Через стандартный интерфейс PSK
- С открытыми и проверяемыми алгоритмами

## Практические сценарии

### Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая |
|-----------|-------------------|---------------|
| **Ядро Linux** | 5.6 (WireGuard) | 5.15+ |
| **wireguard-tools** | 1.0 | 1.1+ |
| **Rust toolchain** | 1.70+ (для сборки из исходников) | latest stable |
| **liboqs** | optional (если используется через crate) | bundled |

```bash
# Проверка версии ядра
uname -r
# → 5.15.0-78-generic

# Проверка модуля WireGuard
lsmod | grep wireguard
# → wireguard 110592 0

# Проверка утилит WireGuard
wg --version
# → wireguard-tools v1.0.20210914
```

### Установка

**Способ 1 — Сборка из исходников (актуальный):**

```bash
# Установка зависимостей
sudo apt update && sudo apt install -y \
  wireguard wireguard-tools \
  build-essential pkg-config libssl-dev \
  git

# Клонирование репозитория
git clone https://github.com/rosenpass/rosenpass.git
cd rosenpass

# Сборка
cargo build --release

# Установка бинарников
sudo cp target/release/rosenpass /usr/local/bin/
sudo cp target/release/rp /usr/local/bin/

# Проверка
rosenpass --version
rp --version
```

**Способ 2 — Пакетный менеджер (если доступен):**

```bash
# Debian/Ubuntu (начиная с Debian 13 Trixie)
sudo apt install rosenpass

# Arch Linux (AUR)
yay -S rosenpass
```

### Генерация ключей

```bash
# Генерация ключевой пары Rosenpass
rosenpass genkeys > /etc/rosenpass/server.keys

# Или через rp frontend (рекомендуется)
rp genkeys /etc/rosenpass/server.keys

# Структура файла ключей:
# === rosenpass secret key ===
# <base64-encoded secret key>
# === rosenpass public key ===
# <base64-encoded public key>
```

### Конфигурация WireGuard с Rosenpass

**Пример конфигурации сервера (`/etc/wireguard/wg0.conf`):**

```ini
[Interface]
PrivateKey = <server_wg_private_key>
Address = 10.0.0.1/24
ListenPort = 51820
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT

# Rosenpass PSK (генерируется автоматически)
PresharedKey = /etc/rosenpass/psk.key

[Peer]
PublicKey = <client_wg_public_key>
AllowedIPs = 10.0.0.2/32
Endpoint = <client_public_ip>:51820
PersistentKeepalive = 25
```

**Важно:** Rosenpass автоматически управляет PSK через `wg` netlink. В конфигурации можно указать путь к файлу PSK, который будет обновляться демоном.

### Запуск Rosenpass

**Способ 1 — Демон `rosenpass` (ручной):**

```bash
# Формат команды:
rosenpass \
  --secret-key /etc/rosenpass/server.keys \
  --peer <client_public_key>:<client_endpoint>:51820 \
  --wireguard-interface wg0 \
  --psk-file /etc/rosenpass/psk.key
```

**Способ 2 — Frontend `rp` (автоматический):**

```bash
# Генерация конфигурации для интерфейса
rp init wg0 /etc/rosenpass/server.keys

# Запуск
rp run wg0 /etc/rosenpass/server.keys \
  --peer <client_pubkey>@<client_endpoint>:51820
```

### Systemd-сервис

**Создание файла `/etc/systemd/system/rosenpass.service`:**

```ini
[Unit]
Description=Rosenpass Post-Quantum Key Exchange for WireGuard
After=network.target wg-quick@wg0.service
Wants=wg-quick@wg0.service

[Service]
Type=simple
ExecStart=/usr/local/bin/rp run wg0 /etc/rosenpass/server.keys \
  --peer <peer1_pubkey>@<peer1_endpoint>:51820 \
  --peer <peer2_pubkey>@<peer2_endpoint>:51820
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Активация и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now rosenpass.service

# Проверка статуса
sudo systemctl status rosenpass.service
# → active (running) since ...

# Просмотр логов
sudo journalctl -u rosenpass.service -f
```

### Docker

**Запуск Rosenpass в контейнере:**

```yaml
# docker-compose.yml
version: '3.8'

services:
  rosenpass:
    image: ghcr.io/rosenpass/rosenpass:latest
    container_name: rosenpass
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    volumes:
      - ./rosenpass-keys:/keys:ro
      - /lib/modules:/lib/modules:ro
    command: >
      rp run wg0 /keys/server.keys
      --peer <client_pubkey>@<client_endpoint>:51820
    network_mode: host
    restart: unless-stopped

  wireguard:
    image: linuxserver/wireguard
    container_name: wireguard
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    volumes:
      - ./wg-config:/config
      - /lib/modules:/lib/modules:ro
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
      - net.ipv4.ip_forward=1
    ports:
      - 51820:51820/udp
    restart: unless-stopped
```

```bash
# Запуск
docker compose up -d

# Проверка PSK в контейнере WireGuard
docker exec wireguard wg show wg0
# → preshared key: <base64-encoded key>
```

### Ротация ключей

**Автоматическая ротация (встроенная):**
- Rosenpass автоматически обновляет PSK каждые 120 секунд
- Никаких дополнительных действий не требуется
- Ключи never leave the kernel space after injection

**Принудительная ротация:**

```bash
# Перезапуск демона Rosenpass
sudo systemctl restart rosenpass.service

# Или через сигнал SIGHUP (если поддерживается)
sudo kill -HUP $(pgrep rosenpass)

# Проверка нового PSK
sudo wg show wg0 | grep preshared
# → preshared key: (updated)
```

**Полная ротация (смена ключевой пары):**

```bash
# 1. Остановка демона
sudo systemctl stop rosenpass.service

# 2. Генерация новых ключей
rosenpass genkeys > /etc/rosenpass/server.keys.new
sudo mv /etc/rosenpass/server.keys.new /etc/rosenpass/server.keys
sudo chmod 600 /etc/rosenpass/server.keys

# 3. Обновление публичного ключа на всех пирах
rosenpass pubkey /etc/rosenpass/server.keys

# 4. Перезапуск
sudo systemctl start rosenpass.service
```

### Мониторинг и диагностика

**Статус демона Rosenpass:**

```bash
# Проверка процесса
ps aux | grep rosenpass
# → root 12345 /usr/local/bin/rosenpass ...

# Проверка systemd
sudo systemctl status rosenpass.service
```

**Статус WireGuard с PSK:**

```bash
# Просмотр интерфейса
sudo wg show wg0

# Пример вывода:
# interface: wg0
#   public key: <server_pubkey>
#   private key: (hidden)
#   listening port: 51820
#   preshared key: (updated 2m ago)
#
# peer: <client_pubkey>
#   preshared key: (updated 2m ago)
#   endpoint: <client_ip>:51820
#   allowed ips: 10.0.0.2/32
#   latest handshake: 12 seconds ago
#   transfer: 1.23 GiB received, 456.78 MiB sent
```

**Логирование:**

```bash
# Логи systemd
sudo journalctl -u rosenpass.service --since "1 hour ago"

# Логи демона (если запущен вручную)
rosenpass --log-level debug ...
```

**Диагностика обмена ключами:**

```bash
# Проверка, что PSK обновляется
watch -n 5 'sudo wg show wg0 | grep "preshared key"'

# Проверка handshake (должен быть свежим, <2 минут)
sudo wg show wg0 latest-handshakes

# Проверка TCPdump на UDP 51820
sudo tcpdump -i eth0 udp port 51820 -n
# Должны быть входящие/исходящие пакеты каждые 2 минуты
```

### Troubleshooting

**Проблема 1 — Rosenpass не стартует:**

```bash
# Проверка прав на ключи
sudo ls -la /etc/rosenpass/server.keys
# → -rw------- 1 root root ...

# Проверка, занят ли порт 51820
sudo ss -ulpn | grep 51820

# Проверка логов
sudo journalctl -u rosenpass.service -n 50
```

**Проблема 2 — PSK не применяется:**

```bash
# Проверка конфигурации WireGuard
sudo wg showconf wg0 | grep -i psk

# Если PSK не отображается — Rosenpass не запущен или не настроен
sudo systemctl restart rosenpass.service

# Проверка, что WireGuard интерфейс существует
ip link show wg0
```

**Проблема 3 — Потеря соединения после обновления Rosenpass:**

```bash
# При обновлении Rosenpass может измениться формат конфигурации
# Проверка синтаксиса конфигурации
sudo wg syncconf wg0 <(wg-quick strip wg0)

# Если ошибка — проверка формата ключей
rosenpass pubkey /etc/rosenpass/server.keys
```

**Проблема 4 — Высокий overhead трафика:**

```bash
# Rosenpass добавляет ~2-3 КБ на каждый обмен ключами (McEliece + Kyber)
# При обновлении каждые 2 минуты на 1 пир: ~1.5 КБ/мин = ~90 КБ/час
# Это negligible для современных каналов, но важно для metered-соединений

# Мониторинг трафика Rosenpass
sudo iftop -i wg0 -f "port 51820"
```

## Граничные случаи и ограничения

1. **Размер публичного ключа Classic McEliece:** ~1 МБ. При большом количестве пиров (>100) требуется значительная память на сервере для хранения публичных ключей.

2. **Overhead трафика:** Post-quantum KEM добавляет 2–3 КБ к каждому обмену ключами. При обновлении каждые 2 минуты это ~90 КБ/час на пир.

3. **Зависимость от WireGuard:** Rosenpass не работает без WireGuard. Это не самостоятельный VPN, а дополнение к существующему.

4. **Один интерфейс:** Frontend `rp` управляет ровно одним интерфейсом WireGuard. Для нескольких интерфейсов требуется несколько экземпляров демона.

5. **Root-привилегии:** Демон требует root для доступа к WireGuard netlink и управления сетевым интерфейсом.

6. **Алгоритмы Classic McEliece:** Хотя McEliece стандартизирован NIST, его Adoption в production среде ограничена по сравнению с Kyber.

7. **Совместимость с ядром:** Требуется WireGuard модуль ядра 5.6+. Старые ядра (4.x) не поддерживаются.

## Дополнительная информация

### См. также

- **[WireGuard — обзор и теория](../Vpn/wireguard.md)** — архитектура, криптография, практическое использование WireGuard
- **[GitHub Rosenpass](https://github.com/rosenpass/rosenpass)** — исходный код, документация, бинарные релизы
- **[Официальный сайт](https://rosenpass.eu/)** — описание проекта, научные публикации
