# Rosenpass: Постквантовая защита для WireGuard VPN

**Актуально для:** Rosenpass 0.2.3 (`rosenpass` + frontend `rp`, `wireguard-tools` 1.0+)

**Rosenpass** — открытый протокол постквантового обмена ключами, разработанный для защиты VPN-туннелей от атак квантовых компьютеров. Работает в связке с WireGuard: добавляет к штатному обмену (Curve25519) постквантовые примитивы, устойчивые к алгоритму Шора, и передаёт полученный секрет WireGuard в качестве pre-shared key (PSK).

## Определения

**Rosenpass** — протокол обмена ключами (key exchange), реализованный как набор из двух утилит: `rosenpass` (низкоуровневый обмен ключами) и `rp` (frontend, который поднимает VPN на WireGuard). Разработан по мотивам [Post-quantum WireGuard (PQWG)](https://eprint.iacr.org/2020/379) и дополнен защитой от state disruption атак через cookie-механизм.

**PSK (Pre-Shared Key)** — симметричный ключ, который WireGuard подмешивает к своему handshake. Rosenpass вычисляет этот ключ из постквантового обмена и передаёт его WireGuard (через `wg` при использовании `rp exchange` или в файл при использовании `outfile`).

**Постквантовая безопасность (post-quantum security)** — устойчивость криптографических алгоритмов к атакам квантовых компьютеров, способных эффективно решать задачи факторизации и дискретного логарифмирования, лежащие в основе RSA и ECDH/ECDSA.

**Гибридная безопасность (hybrid security)** — комбинация классического и постквантового обмена ключами. Расшифровка становится возможной только при компрометации обоих примитивов одновременно. Rosenpass сохраняет безопасность WireGuard и добавляет защиту от квантовых компьютеров: если что-то окажется не так с Rosenpass, стойкость не станет ниже, чем у чистого WireGuard.

**Harvest Now, Decrypt Later (HNDL)** — класс атак, при которых противник записывает зашифрованный трафик сегодня и расшифровывает его позже, когда появятся квантовые компьютеры. Rosenpass защищает от таких атак за счёт постквантового обмена ключами.

**KEM (Key Encapsulation Mechanism)** — механизм инкапсуляции ключа: из открытого ключа получателя генерируется общий секрет и шифртекст (ciphertext), из которого получатель восстанавливает тот же секрет. Rosenpass использует два KEM-алгоритма (см. ниже).

**State disruption attack** — атака, при которой противник манипулирует состоянием протокола (например, временем системы через небезопасный NTP), чтобы вывести из строя будущие handshake. Актуальна для WireGuard (CVE-2021-46873) и PQWG; Rosenpass устраняет её stateless-респондером и cookie-механизмом.

## Назначение

Rosenpass решает проблему уязвимости WireGuard к будущим квантовым компьютерам. Поскольку WireGuard использует Curve25519 для обмена эфемерными ключами, он уязвим к алгоритму Шора на квантовом компьютере достаточной мощности. Rosenpass добавляет постквантовый обмен ключами, после чего полученный секрет передаётся в WireGuard через интерфейс PSK.

Для использования Rosenpass не нужно отказываться от WireGuard — они работают в связке: **Rosenpass отвечает за постквантовую безопасность, WireGuard — за доквантовую (классическую) и высокоскоростную передачу данных**. При этом Rosenpass можно использовать и standalone — как генератор ключей для любого протокола, принимающего PSK (продемонстрирована интеграция с TLS через OpenSSL).

Важная оговорка самого проекта: квантовые компьютеры, по текущим оценкам, не станут практичными ранее чем через десять лет. Ранняя постквантовая защита нужна прежде всего там, где данные должны оставаться конфиденциальными десятилетиями (защита от HNDL).

## Основные концепции

### Архитектура и принцип работы

Rosenpass реализован как процесс на Rust, использующий библиотеки libsodium и liboqs (обе — C). Он не изменяет модуль ядра WireGuard, а взаимодействует с ним либо через утилиту `wg` (задавая PSK), либо через `rp`, который сам создаёт и настраивает интерфейс WireGuard.

**Ключевые свойства архитектуры:**
- **Не требует модификации ядра:** Rosenpass работает как отдельный процесс в userspace
- **Интеграция через PSK:** постквантовый секрет передаётся WireGuard как `PresharedKey`
- **Параллельная работа:** Rosenpass и WireGuard работают одновременно
- **Один интерфейс на экземпляр:** один запущенный `rp exchange` обслуживает один интерфейс WireGuard; для нескольких интерфейсов запускается несколько экземпляров
- **Гибридная безопасность:** используются оба обмена ключами (классический + постквантовый)

**Принцип работы:**
1. Стороны имеют статическую пару ключей Rosenpass (секретный + публичный ключи), которыми заранее обменялись
2. При установлении соединения выполняется аутентифицированный постквантовый обмен ключами (KEM): статический KEM защищает долговременные ключи, эфемерный — сессию
3. Из общего секрета выводится 256-битный ключ, который передаётся WireGuard как PSK
4. WireGuard выполняет свой стандартный Noise_IK handshake, подмешивая PSK
5. Весь трафик шифруется штатными средствами WireGuard (ChaCha20-Poly1305)
6. Rosenpass повторяет обмен примерно каждые две минуты, обновляя PSK

### Криптографические примитивы

Rosenpass использует два постквантовых KEM-алгоритма, обеспечивая гибридную безопасность (состав строки-идентификатора протокола: `Rosenpass v1 mceliece460896 Kyber512 ChaChaPoly1305 BLAKE2s`):

| Алгоритм | Роль | Тип | Параметр | Открытый ключ | Шифртекст |
|----------|------|-----|----------|---------------|-----------|
| **Classic McEliece (mceliece460896)** | Статические ключи | Code-based KEM | NIST Level 3 | 524 160 Б (~512 КиБ) | 156 Б |
| **CRYSTALS-Kyber (Kyber512)** | Эфемерные ключи | Lattice-based KEM | NIST Level 1 (~ML-KEM-512, FIPS 203) | 800 Б | 768 Б |

Симметричная часть: AEAD **ChaCha20-Poly1305**, хеш **BLAKE2s** — те же примитивы, что и в WireGuard.

**Почему два алгоритма?**
- Classic McEliece (кодовая криптография) считается наиболее консервативным постквантовым KEM, но имеет очень большой открытый ключ (~512 КиБ)
- Kyber (решёточная криптография) компактен и стандартизирован (ML-KEM, FIPS 203), поэтому его берут для эфемерных ключей, генерируемых на каждую сессию
- Их комбинация обеспечивает разнообразие: если один алгоритм окажется уязвимым, второй остаётся защитой

**Примечание:** реализация использует Kyber512 (liboqs). Переход на ML-KEM-768 обсуждается в проекте ([issue #701](https://github.com/rosenpass/rosenpass/issues/701)), но на момент 0.2.3 в коде именно Kyber512; реализация Classic McEliece в liboqs основана на более ранней ревизии спецификации (Round 3).

### Жизненный цикл обмена ключами

**Этап 1 — Генерация ключей:**
- Каждая сторона генерирует статическую пару ключей Rosenpass (`rp genkey`)
- Публичные ключи обмениваются между сторонами (`rp pubkey` + передача каталога `-public`)

**Этап 2 — Установление соединения:**
- Стороны выполняют аутентифицированный обмен: эфемерные Kyber512-ключи + статические McEliece-ключи
- Вычисляется общий секрет, из которого выводится ключ для WireGuard PSK

**Этап 3 — Интеграция с WireGuard:**
- `rp` задаёт PSK непосредственно в интерфейсе WireGuard
- WireGuard подмешивает PSK к стандартному handshake
- После этого трафик защищён как Curve25519 + PSK (гибридно)

**Этап 4 — Периодическая ротация:**
- Примерно каждые 120 секунд Rosenpass повторяет обмен ключами
- Новый PSK обновляется в WireGuard без разрыва соединения
- Это ограничивает окно компрометации: даже при утечке текущего PSK прошлый трафик (защищённый предыдущими ключами) не раскрывается

### Защита от state disruption (cookie-механизм)

PQWG и WireGuard защищаются от повторного воспроизведения первого сообщения handshake с помощью таймстампа. Противник, изменивший системное время на будущую дату, может заставить инициатора сгенерировать «kill-packet» и надолго вывести его статический ключ из строя (класс атак state disruption; см. CVE-2021-46873 — небезопасный NTP на многих системах).

Rosenpass вместо защиты от replay первого сообщения использует **stateless-респондер**: состояние респондера вынесено в зашифрованную cookie, которую респондер возвращает в своём ответе. Инициатор присылает cookie обратно, и респондер восстанавливает состояние перед обработкой. Таким образом, повтор первого сообщения не приводит к атаке.

### Почему Rosenpass, а не WireGuard-alone?

**Угрозы:**
- **Quantum Computing:** квантовые компьютеры достаточной мощности взламывают Curve25519 алгоритмом Шора
- **HNDL-атаки:** запись зашифрованного трафика сегодня для расшифровки через 10–20 лет
- **Срок хранения данных:** системы, хранящие данные 10+ лет, уязвимы к будущей расшифровке

**Ограничения WireGuard:**
- Нет встроенного постквантового обмена ключами
- Curve25519 устойчив только к классическим компьютерам
- Требуется внешнее решение для постквантовой безопасности

**Rosenpass дополняет без переделки:**
- Не меняя архитектуру и модуль ядра WireGuard
- Через стандартный интерфейс PSK
- С открытыми и проверяемыми алгоритмами

## Практические сценарии

### Предварительные требования

| Компонент | Минимальная версия | Примечание |
|-----------|-------------------|------------|
| **Ядро Linux** | 5.6 (встроенный WireGuard) | или модуль wireguard для более старых ядер |
| **wireguard-tools** | 1.0 | утилита `wg` |
| **Rust toolchain** | 1.64.0 (только для сборки из исходников) | ставится через [Rustup](https://rustup.rs/) |
| **libsodium / libclang / cmake / pkg-config / build-essential** | — | зависимости сборки |

Проверка окружения:

```bash
# Ядро
uname -r
# → 6.1.0-... (>= 5.6 предпочтительно)

# Модуль WireGuard
lsmod | grep wireguard
# → wireguard  ...

# Утилиты WireGuard
wg --version
# → wireguard-tools v1.0.20210914
```

### Установка

**Способ 1 — Готовые бинарники (рекомендуется):**

Бинарники публикуются в [GitHub Releases](https://github.com/rosenpass/rosenpass/releases) (сборки x86_64). Архив содержит каталог `bin` с двумя исполняемыми файлами: `rosenpass` и `rp`.

```bash
# Зависимость для запуска — только WireGuard
sudo apt --yes install wireguard

# Скачать последний релиз (пример: 0.2.3)
wget https://github.com/rosenpass/rosenpass/releases/download/v0.2.3/rosenpass-x86_64-linux-0.2.3.tar
tar xf rosenpass-x86_64-linux-0.2.3.tar

# Установка в /usr/local/bin
sudo install bin/rosenpass /usr/local/bin
sudo install bin/rp /usr/local/bin

# Проверка
rosenpass help
rp help
```

**Способ 2 — Сборка из исходников:**

```bash
# Зависимости сборки и рантайма (Debian/Ubuntu)
sudo apt --yes install libsodium-dev libclang-dev cmake pkg-config git build-essential curl wireguard

# Rust >= 1.64.0 через Rustup: https://rustup.rs/
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Исходники
git clone https://github.com/rosenpass/rosenpass.git
cd rosenpass
git checkout v0.2.3       # без checkout соберётся dev-версия из main

# Сборка
cargo build --release

# Установка
sudo install target/release/rosenpass /usr/local/bin
sudo install rp /usr/local/bin
```

**Способ 3 — Пакеты дистрибутивов:**

```bash
# Arch Linux (официальный репозиторий)
sudo pacman -S rosenpass

# Alpine Linux
apk add rosenpass

# Nix
nix profile install github:rosenpass/rosenpass#rosenpass
```

**Примечание:** на момент 0.2.x в Debian и Ubuntu `.deb`-пакет ещё не поставляется официально — для них используется установка из бинарников или из исходников. В Debian заведён запрос на упаковку (RFP #1118522). Для `rp` на некоторых версиях возможна безвредная ошибка при отсутствии Git — `rp` работает и без него.

### Генерация ключей

Ключи хранятся в виде каталогов (секретный и публичный). Генерируйте на **обеих** сторонах.

```bash
# Секретные ключи (создаётся каталог с правами только для владельца)
rp genkey server.rosenpass-secret
rp genkey client.rosenpass-secret

# Извлечение публичных ключей
rp pubkey server.rosenpass-secret server.rosenpass-public
rp pubkey client.rosenpass-secret client.rosenpass-public

# Передать публичный каталог противоположной стороне
scp -r server.rosenpass-public user@client:/path/to/dir
scp -r client.rosenpass-public user@server:/path/to/dir
```

После обмена у сервера должны лежать рядом `server.rosenpass-secret` и `client.rosenpass-public`, у клиента — `client.rosenpass-secret` и `server.rosenpass-public`.

### Запуск VPN (frontend rp)

`rp exchange` сам создаёт и настраивает интерфейс WireGuard (`dev rosenpass0`), сам управляет пирами и непрерывно обновляет PSK. Порт WireGuard `rp` выставляет как **порт Rosenpass + 1** (в примере `9999` → `10000`).

**На сервере:**

```bash
sudo rp exchange server.rosenpass-secret \
  dev rosenpass0 \
  listen 0.0.0.0:9999 \
  peer client.rosenpass-public \
  allowed-ips 10.0.0.2/32
```

**На клиенте:**

```bash
sudo rp exchange client.rosenpass-secret \
  dev rosenpass0 \
  peer server.rosenpass-public \
  endpoint <server_ip>:9999 \
  allowed-ips 10.0.0.1/32
```

**Присвоение адресов и маршрутов** (интерфейс создаётся `rp`, адреса задаются отдельно):

```bash
# Server
sudo ip addr add 10.0.0.1/24 dev rosenpass0

# Client
sudo ip addr add 10.0.0.2/24 dev rosenpass0

# Маршрут до удалённой подсети (если нужно)
sudo ip route add 10.0.0.0/24 dev rosenpass0
```

### Firewall

На сервере должны быть открыты **два** UDP-порта: порт Rosenpass (`9999`) и порт WireGuard (`10000`).

```bash
# nftables (имена таблицы/цепочки из стандартной конфигурации)
sudo nft add rule inet filter input iif $DEVICE udp dport { 9999, 10000 } ip daddr $SERVERIP accept

# ufw
sudo ufw allow in on $DEVICE from any to $SERVERIP port 9999 proto udp comment 'Rosenpass'
sudo ufw allow in on $DEVICE from any to $SERVERIP port 10000 proto udp comment 'WireGuard'
```

### Проверка работы

```bash
# Интерфейс WireGuard с PSK, управляемый Rosenpass
sudo wg show rosenpass0
# → interface: rosenpass0
#     public key: <server_pubkey>
#     listening port: 10000
#   peer: <client_pubkey>
#     preshared key: (hidden)
#     allowed ips: 10.0.0.2/32

# Текущий PSK (вторая строка из двух base64-строк — сам ключ)
sudo wg show rosenpass0 preshared-keys
# → <pubkey>  <base64_psk>

# Непрерывное наблюдение за сменой PSK каждые ~2 секунды
sudo watch 'wg show all; wg show all preshared-keys'

# Проверка связности
ping 10.0.0.2
```

PSK на обеих сторонах должен совпадать и меняться примерно каждые две минуты.

### Интеграция с существующим WireGuard

Если интерфейс WireGuard уже поднят и управляется `wg-quick`, используется низкоуровневый `rosenpass` с выводом ключа в файл, после чего ключ подаётся в готовый интерфейс утилитой `wg`:

```bash
# Низкоуровневый обмен: результат (PSK) пишется в файл каждые ~2 минуты
sudo rosenpass exchange \
  private-key server-secret public-key server-public \
  listen 0.0.0.0:9999 \
  peer public-key client-public endpoint <client_ip>:9999 \
  outfile /run/rosenpass/wg0.psk

# Подача PSK в существующий peer интерфейса wg0
wg set wg0 peer <client_pubkey> preshared-key /run/rosenpass/wg0.psk
```

Альтернативно `rosenpass` умеет сам применять ключ к указанному интерфейсу через параметр `wireguard <dev> <peer> <extra_params>` — тогда ручной `wg set` не нужен.

### Systemd-сервис

```ini
# /etc/systemd/system/rosenpass.service
[Unit]
Description=Rosenpass post-quantum key exchange (WireGuard interface rosenpass0)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# rp exchange сам создаёт интерфейс и управляет PSK
ExecStart=/usr/local/bin/rp exchange /etc/rosenpass/server.rosenpass-secret \
  dev rosenpass0 \
  listen 0.0.0.0:9999 \
  peer /etc/rosenpass/client.rosenpass-public \
  endpoint <client_ip>:9999 \
  allowed-ips 10.0.0.2/32
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rosenpass.service
sudo systemctl status rosenpass.service
# → active (running)

sudo journalctl -u rosenpass.service -f
```

**Примечание:** адрес на интерфейс (`ip addr add ... dev rosenpass0`) нужно назначать отдельно — либо вручную, либо через `ExecStartPost`. Для нескольких интерфейсов/пиров запускается несколько сервисов (или используются несколько `peer` в одной команде).

### Docker

Rosenpass публикует официальные образы:

- `ghcr.io/rosenpass/rosenpass` — точка входа `rosenpass` (standalone обмен ключами)
- `ghcr.io/rosenpass/rp` — точка входа `rp` (VPN с WireGuard)

**Пример: VPN из двух контейнеров с образом `rp`.** Образ `rp` сам создаёт интерфейс WireGuard, поэтому контейнеру нужен `NET_ADMIN`, а на хосте должен быть загружен модуль `wireguard`.

```bash
# Сеть для контейнеров
docker network create -d bridge rp
export NET=rp

# Ключи на обеих сторонах
mkdir -p ./srv ./cli
docker run -it --rm -v ./srv:/workdir ghcr.io/rosenpass/rp genkey workdir/server.rosenpass-secret
docker run -it --rm -v ./srv:/workdir ghcr.io/rosenpass/rp pubkey workdir/server.rosenpass-secret workdir/server.rosenpass-public
docker run -it --rm -v ./cli:/workdir ghcr.io/rosenpass/rp genkey workdir/client.rosenpass-secret
docker run -it --rm -v ./cli:/workdir ghcr.io/rosenpass/rp pubkey workdir/client.rosenpass-secret workdir/client.rosenpass-public

# Обмен публичными ключами
cp -r ./cli/client.rosenpass-public ./srv/
cp -r ./srv/server.rosenpass-public ./cli/

# Сервер (обратите внимание на --cap-add=NET_ADMIN)
docker run --name rpserver --network ${NET} -d --rm -v ./srv:/workdir --cap-add=NET_ADMIN \
  ghcr.io/rosenpass/rp \
  exchange workdir/server.rosenpass-secret dev rosenpass0 \
  listen 0.0.0.0:9999 peer workdir/client.rosenpass-public allowed-ips 10.0.0.0/8

# IP сервера в сети docker
EP=$(docker inspect --format '{{ .NetworkSettings.Networks.rp.IPAddress }}' rpserver)

# Клиент
docker run --name rpclient --network ${NET} -d --rm -v ./cli:/workdir --cap-add=NET_ADMIN \
  ghcr.io/rosenpass/rp \
  exchange workdir/client.rosenpass-secret dev rosenpass0 \
  peer workdir/server.rosenpass-public endpoint ${EP}:9999 allowed-ips 10.0.0.0/8

# Адреса внутри контейнеров
docker exec rpserver ip a add 10.0.0.1/24 dev rosenpass0
docker exec rpclient ip a add 10.0.0.2/24 dev rosenpass0
```

### Ротация ключей

**Автоматическая (встроенная):** `rp exchange` (и низкоуровневый `rosenpass`) обновляют PSK примерно каждые две минуты без разрыва соединения. Дополнительных действий не требуется.

**Принудительное обновление PSK** — перезапуск процесса:

```bash
sudo systemctl restart rosenpass.service

# Проверка, что PSK снова меняется
sudo wg show rosenpass0 preshared-keys
```

**Полная ротация (смена статической пары ключей):**

```bash
# 1. Остановить
sudo systemctl stop rosenpass.service

# 2. Новые ключи
rp genkey /etc/rosenpass/server.rosenpass-secret.new
rp pubkey /etc/rosenpass/server.rosenpass-secret.new /etc/rosenpass/server.rosenpass-public.new

# 3. Заменить старые (после того как новый публичный ключ передан пирам)
sudo mv /etc/rosenpass/server.rosenpass-secret.new /etc/rosenpass/server.rosenpass-secret
sudo mv /etc/rosenpass/server.rosenpass-public.new /etc/rosenpass/server.rosenpass-public

# 4. Перезапустить
sudo systemctl start rosenpass.service
```

### Мониторинг и диагностика

```bash
# Состояние процесса/сервиса
sudo systemctl status rosenpass.service
ps aux | grep '[r]p '

# Состояние интерфейса и handshake
sudo wg show rosenpass0
sudo wg show rosenpass0 latest-handshakes   # время последнего handshake

# Текущий PSK (должен совпадать на обеих сторонах)
sudo wg show rosenpass0 preshared-keys

# Трафик порта Rosenpass
sudo tcpdump -i eth0 udp port 9999 -n
```

### Troubleshooting

**Проблема 1 — `rp`/`rosenpass` не стартует:**

```bash
# Права на ключи (каталоги секретных ключей должны быть недоступны посторонним)
sudo ls -la /etc/rosenpass/
# → drwx------ ... server.rosenpass-secret

# Занят ли порт
sudo ss -ulpn | grep -E '9999|10000'

# Логи
sudo journalctl -u rosenpass.service -n 50
```

**Проблема 2 — PSK не появляется в WireGuard:**

```bash
# PSK виден только если rp действительно запущен и обменялся с пиром
sudo wg show rosenpass0 preshared-keys
# → пусто: проверьте, что публичный ключ пира передан и endpoint доступен

# Интерфейс существует?
ip link show rosenpass0

# Порт Rosenpass доступен при наличии firewall?
sudo ss -ulpn | grep 9999
```

**Проблема 3 — Соединение не поднимается после обновления:**

```bash
# Проверка публичных ключей пиров
rp pubkey /etc/rosenpass/server.rosenpass-secret /tmp/check-pub

# Проверка, что на интерфейсе есть адрес и маршрут
ip addr show rosenpass0
ip route
```

**Проблема 4 — Нет связи при наличии firewall:** открыты ли оба UDP-порта (Rosenpass и WireGuard = Rosenpass+1) на сервере.

## Best Practices

- **Запускайте через systemd** (или менеджер контейнеров) — `rp exchange` не демонизируется сам и должен постоянно работать для ротации PSK.
- **Храните секретные ключи строго локально:** каталог `*-secret` — права `700`, владелец root; публичные каталоги можно передавать открыто.
- **Ограничивайте `allowed-ips`** минимально необходимыми подсетями, как в WireGuard.
- **Открывайте только два UDP-порта** (Rosenpass и WireGuard) и делайте это явно в firewall.
- **Не заменяйте гигиену WireGuard:** `PersistentKeepalive` при NAT, разумный MTU, проверка handshake остаются актуальными.
- **Проверяйте ротацию PSK** (`wg show ... preshared-keys`) — это индикатор живости обмена.
- **Пинуйте версию** Rosenpass и обновляйтесь осознанно: протокол и зависимости (`liboqs`) развиваются.
- **Помните о границах применимости:** большинству задач постквантовая защита сейчас не критична; она оправдана для данных с длительным сроком конфиденциальности (HNDL).
- **Резервируйте ключи:** потеря каталога `*-secret` требует полной повторной генерации и обмена публичными ключами.

## Очистка

```bash
# Остановить сервис
sudo systemctl disable --now rosenpass.service

# Удалить интерфейс, созданный rp (если он остался)
sudo ip link del rosenpass0

# Удалить ключи и конфиги
sudo rm -rf /etc/rosenpass
sudo rm -f /etc/systemd/system/rosenpass.service
sudo systemctl daemon-reload
```

## Граничные случаи и ограничения

1. **Размер открытого ключа Classic McEliece:** ~512 КиБ на статический ключ. При большом числе пиров хранение и передача публичных ключей заметно дороже, чем у классических схем.
2. **Накладные расходы:** постквантовые KEM добавляют к handshake сумму шифртекстов (McEliece 156 Б + Kyber512 768 Б плюс служебные поля) и повторяются ~каждые две минуты. Для современных каналов объём незначителен, но на metered-соединениях его стоит учитывать.
3. **Зависимость от WireGuard:** в основном сценарии Rosenpass не работает без WireGuard. Это не самостоятельный VPN, а дополнение (standalone-режим существует, но требует, чтобы потребитель умел использовать PSK).
4. **Один интерфейс на экземпляр:** `rp exchange` обслуживает один интерфейс; несколько интерфейсов — несколько экземпляров.
5. **Root-привилегии:** создание и настройка сетевого интерфейса и модуль WireGuard требуют root (или `CAP_NET_ADMIN`).
6. **Ревизия алгоритмов:** реализация использует Kyber512 и Classic McEliece на базе более ранней ревизии спецификации (liboqs). Переход на ML-KEM-768 обсуждается, но не завершён — при аудите это следует фиксировать.
7. **Зрелость:** проект позиционируется как research-ориентированный; криптографическое доказательство безопасности находится в работе, на текущий момент есть символьный анализ (ProVerif). Для критичных систем это надо учитывать.
8. **Совместимость с ядром:** требуется WireGuard (ядро 5.6+ или внешний модуль). Старые ядра 4.x без модуля не поддерживаются.

## Дополнительная информация

### См. также

- **[WireGuard — обзор и теория](./wireguard.md)** — архитектура, криптография, практическое использование WireGuard
- **[GitHub Rosenpass](https://github.com/rosenpass/rosenpass)** — исходный код, релизы, документация, Docker-образы
- **[Официальный сайт](https://rosenpass.eu/)** — описание проекта, научные публикации, руководства по установке
- **[Post-quantum WireGuard (PQWG)](https://eprint.iacr.org/2020/379)** — научная основа протокола (Hülsing, Ning, Schwabe, Weber, Zimmermann)
