# ZeroTier: Виртуальные сети поверх интернета

**Актуально для:** ZeroTier One 1.16.x

ZeroTier — платформа для создания защищенных виртуальных L2-сетей между устройствами независимо от их местоположения. Она обеспечивает NAT-траверсал, позволяя узлам взаимодействовать напрямую по принципу P2P, как если бы они находились в одной физической локальной сети.

- **Сайт:** [zerotier.com](https://www.zerotier.com/)
- **Исходный код:** [github.com/zerotier/ZeroTierOne](https://github.com/zerotier/ZeroTierOne)
- **Документация:** [docs.zerotier.com](https://docs.zerotier.com/)

## Определения

- **ZeroTier** — платформа виртуального сетевого оборудования, создающая overlay-сети на уровне L2. Архитектурно состоит из двух слоев: **VL1** (криптографически адресуемая P2P-сеть, аналог транспорта) и **VL2** (эмуляция Ethernet с SDN-функциями — правилами, тегами, capabilities).
- **Виртуальная сеть (Network)** — логический контейнер, объединяющий авторизованные узлы в единый сегмент с уникальным **Network ID** (16-значный hex).
- **Узел (Node)** — устройство, запустившее клиент ZeroTier и присоединившееся к виртуальной сети. Каждому узлу присваивается **Node ID** — 10-значный (40-битный) address, производный от открытого ключа Curve25519.
- **Контроллер сети (Network Controller)** — компонент, отвечающий за выделение IP-адресов, аутентификацию узлов и распределение метаданных сети. В стандартной поставке управление осуществляется через официальный портал **ZeroTier Central**. При самостоятельном хостинге используются [ZTNET](https://github.com/sinamics/ztnet) или собственный контроллер на базе открытого API.
- **Корневой сервер (Root / Planet)** — инфраструктура, обеспечивающая регистрацию узлов и установку P2P-соединений. При невозможности прямого соединения трафик ретранслируется через эти серверы. Все соединения остаются end-to-end зашифрованными.
- **MOON (Self-hosted Root)** — самостоятельно размещенный корневой сервер, позволяющий организовывать соединения внутри закрытой инфраструктуры без использования публичных корневых серверов ZeroTier. В настоящее время **признан устаревшим** и не поддерживается по SLA (см. [Особенности и ограничения](#особенности-и-ограничения)).
- **Managed IP** — статический IP-адрес, зарезервированный за узлом в конфигурации контроллера.
- **Виртуальный сетевой интерфейс (vni)** — программный адаптер (обычно `zt+` в Linux), через который узел подключается к виртуальной сети.
- **Flow Rules (Rules Engine)** — распределенный механизм фильтрации трафика внутри виртуальной сети, встроенный в агент на каждом узле (см. [Правила трафика](#правила-трафика-flow-rules--rules-engine)).

## Основные концепции

### Архитектура и принцип работы

ZeroTier создает виртуальный Ethernet-свитч. Каждый узел получает уникальный адрес в виртуальной сети и может связываться с другими узлами напрямую.

**Компоненты:**
- **Контроллер** — выделяет IP-адреса (Managed IPs), аутентифицирует устройства, хранит метаданные сети. Контроллер **не обрабатывает пользовательский трафик**; он только управляет control plane.
- **Корневые серверы (Planet)** — обеспечивают введение узлов в сеть и помощь в установке P2P-соединений.
- **Узлы** — клиентские устройства с установленным демоном `zerotier-one`.

**NAT-траверсал:**
ZeroTier использует комбинацию техник для обхода NAT:
1. **UDP hole punching** — оба узла отправляют UDP-пакеты друг другу через свои NAT-устройства, создавая отображение в таблицах NAT.
2. **Статический relay через корневые серверы** — если прямой P2P-проход невозможен (симметричный NAT, строгие файрволы), трафик ретранслируется через корневые серверы ZeroTier. При этом payload остается end-to-end зашифрованным. Помимо UDP существует fallback-relay по TCP (`allowTcpFallbackRelay`, по умолчанию включен) — самый медленный вариант, следует избегать на постоянной основе.

> **Важно:** ранее для продакшн-сред рекомендовалось разворачивать собственные MOON-серверы для минимизации зависимости от публичных relay. Сейчас ZeroTier помечает private moons как устаревшие и не поддерживаемые по SLA; проектным решением стало ускорение P2P-соединений и TCP-fallback, а не собственные корни. Для инфраструктур, которым требуется автономная корневая инфраструктура, вендор предлагает связаться с отделом продаж (Enterprise-решение).

### Шифрование и аутентификация

Все соединения шифруются end-to-end:
- **Обмен ключами:** эллиптическая кривая **Curve25519**.
- **Шифрование трафика:** потоковый шифр **Salsa20**.
- **Аутентификация пакетов:** код аутентификации сообщений **Poly1305**.
- **Идентификация узлов:** Node ID формируется как хэш открытого ключа Curve25519, что исключает спуфинг. Адрес узла 40-битный; сеть идентифицируется 64-битным (16-hex) Network ID.

Корневые серверы и контроллер видят только метаданные (Node ID, IP-адреса, статус соединения), но **не могут расшифровать пользовательский трафик**.

### Жизненный цикл узла

1. **Установка клиента** (`zerotier-one`) и запуск службы.
2. **Join** — узел отправляет запрос на присоединение к сети (`zerotier-cli join <NWID>`).
3. **Регистрация** — узел появляется в списке ожидающих авторизации в управляющем портале.
4. **Auth** — администратор авторизует узел.
5. **Выделение IP** — контроллер присваивает Managed IP (через DHCP или статическую резервацию).
6. **P2P negotiation** — узел договаривается о прямом соединении с другими узлами через корневые серверы.
7. **Traffic flow** — после установки P2P-сессии трафик идет напрямую; при разрыве — повторная negotiation через корневые серверы.

### Правила трафика (Flow Rules / Rules Engine)

ZeroTier реализует распределенный механизм фильтрации `Rules Engine`, работающий внутри агента на каждом узле. Политики задаются централизованно (в ZeroTier Central или через API контроллера), подписываются и рассылаются узлам, где применяются локально **двусторонне** — и отправителем, и получателем. Это дает micro-segmentation на уровне L2/L3 виртуальной сети, которую не видит внешний файрвол, поскольку тот работает с уже зашифрованным ZeroTier-трафиком.

**Ключевая особенность — правила stateless:** движок не ведет таблицу соединений (connection tracking). Поэтому «разрешить ответные пакеты» не работает — обе стороны потока нужно описать явно (типовой прием для TCP — whitelist нужных портов и отсечение новых соединений по флагу `tcp_syn` без `tcp_ack`).

**Состояние по умолчанию:** flow rules **отключены**, весь трафик между узлами разрешен. При этом базовый **Layer 2 Protocol Filter** пропускает только IPv4, IPv6 и ARP, отбрасывая прочие типы Ethernet-кадров.

**Язык правил** (rule definition language) компилируется в бинарный набор, исполняемый агентом. Базовый набор сети ограничен 1024 записями, набор capability — 64. Доступность в интерфейсе зависит от тарифа: на **New Central** шаблонные (templated) правила доступны с тарифа Essential, произвольные (custom) — Scale и Enterprise; на **Legacy Central** полный движок доступен всем.

Действия (actions):

| Действие | Назначение |
|----------|-----------|
| `accept` | Принять пакет, завершить вычисление правил |
| `drop` | Отбросить пакет, завершить вычисление (в т.ч. capabilities) |
| `break` | Завершить текущий набор правил, но продолжить проверку capabilities |
| `tee` | Отправить копию первых N байт пакета на ZeroTier-адрес наблюдателя |
| `watch` | Как `tee`, но отбрасывает пакет, если наблюдатель не подтвердил прием |
| `redirect` | Прозрачно перенаправить пакет на ZeroTier-адрес без изменения заголовков |

Основные условия совпадения (matches): `ztsrc`/`ztdest` (ZeroTier-адреса), `macsrc`/`macdest`, `ipsrc`/`ipdest` (IPv4/IPv6, с префиксами), `ipprotocol`, `ethertype`, `sport`/`dport`, `icmp`, `framesize`, `chr` (битовые характеристики: `tcp_syn`, `tcp_ack`, `tcp_rst`, `ipauth`, `inbound`, `multicast` и др.), а также теги (`tdiff`, `tand`, `tor`, `txor`, `teq`, `tseq`, `treq`).

Два механизма управляют сложностью больших сетей:
- **Capabilities** — небольшие именованные наборы правил, которые выдаются конкретным узлам как credential. Позволяют давать отдельным устройствам исключения (например, администраторам) без раздувания базового набора.
- **Tags** — 32-битные пары ключ-значение, раздаваемые узлам. Позволяют строить правила по классификации (отдел, среда, роль) без комбинаторного взрыва числа правил.

Пример правила: разрешить только SSH и веб, отсекая прочие новые TCP-соединения:

```
# Разрешить SSH
accept ipprotocol tcp and dport 22;
# Разрешить HTTP и HTTPS
accept ipprotocol tcp and dport 80 or dport 443;
# Отбросить новые TCP-соединения (SYN без ACK), не разрешенные выше
break chr tcp_syn and not chr tcp_ack;
# Пропустить остальное (ответные пакеты, UDP)
accept;
```

Проверка применяемых правил на узле: `zerotier-cli dump` (или JSON-вывод `zerotier-cli -j dump`).

### Модели развертывания контроллера

- **Официальный управляющий портал (ZeroTier Central)** — управление сетью через веб-интерфейс от ZeroTier, Inc. С ноября 2025 года действует новая версия панели (New Central) с иерархией организаций и RBAC. Подходит для большинства сценариев, не требует обслуживания инфраструктуры.
- **Самостоятельный хостинг с ZTNET** — современная альтернатива управления контроллером на базе Next.js и PostgreSQL, распространяется отдельно от ZeroTier One.
- **Встроенный контроллер ZeroTier One (`nonfree/controller`)** — контроллер, встроенный в сам демон. С версии 1.16.0 стандартные сборки его не включают, а исходный код компонента переведен на коммерческую source-available лицензию (см. [Лицензирование](#особенности-и-ограничения)).
- **ZeroTier One Enterprise** — коммерческое решение вендора для self-hosted контроллеров и air-gapped-развертываний.

### Сравнение с mesh-VPN решениями

| Параметр | ZeroTier | WireGuard | Tailscale |
|----------|----------|-----------|-----------|
| **Уровень** | L2 (Ethernet) | L3 (IP) | L3 (IP) |
| **Топология** | Полносвязная mesh | Полносвязная mesh (full mesh требует ручного конфига) | Full mesh через координационный сервер |
| **NAT Traversal** | Автоматический (UDP hole punching + relay) | Нативный UDP, требуется PersistentKeepalive | Автоматический |
| **Развертывание контроллера** | Self-hosted или официальный портал | Не требует контроллера | Официальный сервис или Headscale |
| **L2-протоколы** | Да (ARP, DHCP broadcast) | Нет | Ограниченно (MAC addresses via magic DNS) |
| **Overhead** | ~40–60 байт | 60 байт | ~40–60 байт (заголовки WireGuard + Tailscale metadata) |
| **Масштабируемость** | До ~16.7 млн устройств на сеть | Ограничена ручной конфигурацией | ~100 устройств на сеть (free tier) |

Подробнее: [WireGuard](./wireguard.md), [Tailscale](./tailscale.md), [обзор mesh-VPN решений](./mesh-vpn-overview.md)

## Практические сценарии

### Предварительные требования

**Аппаратные/программные требования:**
- **ОС (Tier 1, полностью поддерживаются):** Windows 10/11, macOS 10.13+, Linux, iOS, Android, Docker, Mikrotik.
- **ОС (Tier 2, официальные сборки):** FreeBSD, OpenWRT, Ubiquiti, OPNsense, Teltonika.
- **Устаревшие платформы (Tier 3, не тестируются):** Windows 7, Windows Server 2008/2012, QNAP, Synology (Docker), NAS. Для них рекомендуется миграция или Docker. Обратите внимание: Windows 7 не поддерживается начиная с версии 1.8.0 — на таких системах последняя работоспособная версия 1.6.6.
- **Порты:** UDP 9993 (основной, входящий) — рекомендуется открыть для улучшения P2P-проходимости; при недоступности используется relay через корневые серверы. Вторичный/третичный порты выбираются случайно, если не заданы в `local.conf`.
- **Ресурсы:** клиент крайне неприхотлив — обычно менее 16 МБ ОЗУ и ~1 МБ диска (есть low-bandwidth режим для IoT).
- **Сеть:** Интернет-соединение без блокировки UDP. Для симметричного NAT или строгого файрвола требуется проброс порта 9993.

**Проверка поддержки TUN/TAP (Linux):**
```bash
lsmod | grep tun
# → tun                    45056  0

# Если модуль не загружен
sudo modprobe tun
```

### Сценарий 1: Базовая настройка сети и подключение Linux-сервера

#### Шаг 1: Создание сети

1. Откройте управляющий портал ZeroTier Central.
2. Создайте новую сеть. Сохраните **Network ID** (16-символьный hex-идентификатор).
3. При необходимости измените диапазон адресов (по умолчанию `10.0.0.0/24`).

#### Шаг 2: Установка клиента

```bash
# Установка клиента ZeroTier
curl -s https://install.zerotier.com | sudo bash

# Проверка установки
zerotier-cli info
# → 200 info <node_id> <version> ONLINE
```

#### Шаг 3: Подключение к сети

```bash
# Join в сеть (замените <NETWORK_ID> на ваш идентификатор)
sudo zerotier-cli join <NETWORK_ID>
# → 200 join OK
```

#### Шаг 4: Авторизация устройства

В управляющем портале найдите узел в списке ожидающих и нажмите **Auth**. После авторизации узел получит IP-адрес из диапазона сети.

#### Шаг 5: Проверка статуса

```bash
# Статус всех сетей
sudo zerotier-cli listnetworks

# Пример вывода:
# → <nwid> <name> <status> <type> <dev> <ZT-IP> <via> <routes>
# → 8056c2e21c123456 MyNetwork OK PRIVATE zt5kx6mxtu 10.0.0.5/24 - 10.0.0.0/24 via zt5kx6mxtu

# Детальная информация о интерфейсе
ip addr show zt5kx6mxtu
# → 3: zt5kx6mxtu: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 2800 qdisc noqueue state UNKNOWN group default qlen 1000
# →    link/none
# →    inet 10.0.0.5/24 scope global zt5kx6mxtu
# →      valid_lft forever preferred_lft forever
```

### Сценарий 2: Подключение клиентского устройства (Windows/macOS/мобильные)

1. Скачайте клиент с [zerotier.com/download](https://www.zerotier.com/download).
2. Установите и запустите приложение.
3. Введите **Network ID** для подключения.
4. Подтвердите подключение в управляющем портале.

### Сценарий 3: Назначение статических адресов (Managed IPs)

Для серверов рекомендуется резервировать адреса вручную:

1. В управляющем портале откройте устройство.
2. В поле **Managed IPs** пропишите желаемый статический адрес из диапазона сети.
3. На клиенте выполните переподключение:

```bash
sudo zerotier-cli leave <NETWORK_ID>
sudo zerotier-cli join <NETWORK_ID>
```

### Сценарий 4: Site-to-site: соединение двух офисов

**Задача:** объединить локальную сеть офиса A (`192.168.10.0/24`) и офиса B (`192.168.20.0/24`) в единое адресное пространство через ZeroTier.

**Топология:**
- Офис A: шлюз `192.168.10.1`, сервер ZeroTier `10.0.0.1`
- Офис B: шлюз `192.168.20.1`, сервер ZeroTier `10.0.0.2`

**Настройка на сервере офиса A:**

```bash
# Включение форвардинга
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-zerotier-forward.conf
sudo sysctl -p /etc/sysctl.d/99-zerotier-forward.conf

# Добавление маршрута в управляющий портал (через UI или API)
# Маршрут: 192.168.10.0/24 via 10.0.0.1
```

**Настройка на сервере офиса B:**

```bash
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-zerotier-forward.conf
sudo sysctl -p /etc/sysctl.d/99-zerotier-forward.conf

# Маршрут: 192.168.20.0/24 via 10.0.0.2
```

**Проверка:**
```bash
# С офиса A
ping 192.168.20.10
# → OK

# Traceroute
traceroute 192.168.20.10
# → hop1: 10.0.0.2 (шлюз ZeroTier офиса B)
# → hop2: 192.168.20.10
```

### Сценарий 5: Настройка Exit Node (NAT-шлюз)

**Задача:** весь трафик устройства через ZeroTier-узел с выходом в интернет.

На exit-ноде включите masquerading:

```bash
# Включение IP forward
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-zerotier-exit.conf
sudo sysctl -p /etc/sysctl.d/99-zerotier-exit.conf

# Правило masquerade для трафика из ZeroTier
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
sudo iptables -A FORWARD -i zt+ -o eth0 -j ACCEPT
sudo iptables -A FORWARD -i eth0 -o zt+ -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

На клиенте через управляющий портал включите опцию **Allow Default Route** для соответствующего узла, а на самом узле-выходе добавьте managed route `0.0.0.0/0`. На клиенте локально это соответствует установке `allowDefault`:

```bash
zerotier-cli set <NETWORK_ID> allowDefault true
```

### Сценарий 6: Файрвол и сегментация

По умолчанию ZeroTier разрешает весь L2-трафик между авторизованными узлами. Внутри самой виртуальной сети сегментация задается движком правил (см. [Правила трафика](#правила-трафика-flow-rules--rules-engine)); на хосте — средствами ОС (`iptables`/`nftables`).

#### Принцип безопасности

- **Внешний интерфейс** (`eth0`, `ens3` и т.д.): открываются только необходимые порты.
- **Интерфейс ZeroTier** (`zt+`): доступ регулируется правилами на каждом узле независимо.
- **Docker-контейнеры:** доступ из ZeroTier-сети разрешается через цепочку `DOCKER-USER`.

> **Важно:** Имена интерфейсов (`eth0`, `zt+`) зависят от дистрибутива и версии ZeroTier. Уточните актуальные имена через `ip link show`.

#### Пример правил iptables

```bash
# Резервное копирование текущих правил
sudo iptables-save > /root/iptables.backup.$(date +%F_%H%M).rules

# Базовый allow (добавляем в начало)
sudo iptables -I INPUT 1 -i zt+ -j ACCEPT
sudo iptables -I INPUT 2 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -I INPUT 3 -i lo -j ACCEPT

# Публичные порты через внешний интерфейс
sudo iptables -I INPUT 4 -i eth0 -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 5 -i eth0 -p tcp --dport 443 -j ACCEPT

# Политика по умолчанию: DROP для всего остального входящего трафика
sudo iptables -P INPUT DROP
```

#### Правила для Docker

```bash
# Очистка цепочки DOCKER-USER
sudo iptables -F DOCKER-USER

# Разрешение установленных соединений
sudo iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# Полный доступ через ZeroTier
sudo iptables -A DOCKER-USER -i zt+ -j ACCEPT
sudo iptables -A DOCKER-USER -o zt+ -j ACCEPT

# Контейнерам разрешено инициировать соединения наружу
sudo iptables -A DOCKER-USER -i docker0 -j ACCEPT

# Из внешней сети (eth0) только 80 и 443
sudo iptables -A DOCKER-USER -i eth0 -p tcp --dport 80 -j ACCEPT
sudo iptables -A DOCKER-USER -i eth0 -p tcp --dport 443 -j ACCEPT

# Остальной трафик из внешней сети в Docker — DROP
sudo iptables -A DOCKER-USER -i eth0 -j DROP

# Возврат обработки остальных пакетов
sudo iptables -A DOCKER-USER -j RETURN
```

#### Сохранение правил

```bash
# Установка утилиты для персистентности (Debian/Ubuntu)
sudo apt-get update
sudo apt-get install -y iptables-persistent

# Сохранение текущих правил
sudo netfilter-persistent save
```

### Сценарий 7: Автоматическое подключение через systemd

Создайте сервис для автоматического join при загрузке системы:

```ini
# /etc/systemd/system/zerotier-join.service
[Unit]
Description=Join ZeroTier Network
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/zerotier-cli join <NETWORK_ID>
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zerotier-join.service
```

### Сценарий 8: Мониторинг и валидация

#### Проверка состояния сети

```bash
# Список сетей
sudo zerotier-cli listnetworks

# Детальная информация о пирах (роль LEAF/PLANET/MOON, путь direct/relay)
sudo zerotier-cli peers

# Проверка маршрутов
ip route show table all | grep zt
```

#### Диагностика P2P-соединений

```bash
# Журнал ZeroTier
sudo journalctl -u zerotier-one -f

# Проверка связности
ping 10.0.0.2

# Проверка открытых портов
ss -u -n | grep 9993
# → UNCONN  0  0  *:9993  *:*
```

#### Мониторинг через Prometheus

ZeroTier One отдает метрики в формате Prometheus на том же порту, что и локальный JSON API: `http://localhost:9993/metrics`. Аутентификация — по токену из файла `metricstoken.secret` (отдельный от `authtoken.secret`); поддерживаются заголовок `X-ZT1-Auth` и Bearer-токен. Метрики также дублируются в файл `metrics.prom` в рабочем каталоге ZeroTier, что позволяет собирать их через `node_exporter` textfile collector без HTTP-скрейпа.

> **Важно (начиная с 1.16.1):** сбор метрик отключен по умолчанию. В версиях 1.14.0–1.16.0 он был включен. Для включения создайте `local.conf` в рабочем каталоге (`/var/lib/zerotier-one/local.conf` в Linux):

```json
{ "settings": { "enableMetrics": true } }
```

После правки файла перезапустите службу. Ключевые метрики: `zt_packet` (пакеты с метками направления rx/tx, peer и network ID), `zt_peer_path` (активные пути до пиров); контроллер отдает `controller_network_count`, `controller_member_count`, `controller_*_change_count`, `controller_member_auth_count`, `controller_member_deauth_count`. Для сетей с большим числом пиров метрики на пир можно отключить на этапе сборки флагом `ZT_NO_PEER_METRICS`, чтобы снизить кардинальность.

Пример конфигурации Prometheus:

```yaml
scrape_configs:
  - job_name: zerotier
    static_configs:
      - targets: ['localhost:9993']
    bearer_token_file: /var/lib/zerotier-one/metricstoken.secret
```

Официальный пример стека Prometheus + Grafana с развернутым контроллером — [zerotier/metrics-tutorial](https://github.com/zerotier/metrics-tutorial). Подходы к мониторингу VPN и пороги алертов — в [vpn-monitoring.md](./vpn-monitoring.md).

### Сценарий 9: Управление сетью через API (автоматизация)

ZeroTier предоставляет локальный JSON API на порту 9993:

```bash
# Получение токена авторизации
TOKEN=$(sudo cat /var/lib/zerotier-one/authtoken.secret)

# Создание сети (на контроллере)
NODEID=$(zerotier-cli info | cut -d ' ' -f 3)
NWID=$(curl -s -X POST "http://localhost:9993/controller/network/${NODEID}______" \
  -H "X-ZT1-AUTH: ${TOKEN}" \
  -d '{}' | jq -r '.id')

echo $NWID
# → 8056c2e21c123456
```

Для удаленного управления через REST API используйте [ZeroTier Central API](https://docs.zerotier.com/central-api/). Для реального self-hosted контроллера требуется сборка демона с включенным контроллером (см. [Самостоятельный хостинг контроллера](#самостоятельный-хостинг-контроллера)); приведенный пример работает только на сборке со встроенным контроллером.

### Сценарий 10: Развертывание собственного корневого сервера (MOON)

> **Статус:** private moons признаны устаревшими и **не покрываются SLA**. Вендор не рекомендует разворачивать новые moons; для автономной корневой инфраструктуры предлагается Enterprise-решение. Сценарий приведен для сопровождения уже существующих развертываний.

MOON — пользовательский набор корневых серверов («планета» = глобальные корни, «moon» = свои). Узел, «орбитящий» moon, добавляет его корни к своему набору: планетарные корни продолжают использоваться, moon используется, когда выглядит быстрее или недоступно остальное. Рекомендуется развертывать два moon-сервера со статическими IP (не на одной физической машине), не совмещая их с ролью контроллера.

**Создание мира (world definition):**

```bash
# На любом узле с zerotier-idtool, используя identity.public одного из moon-серверов
zerotier-idtool initmoon /var/lib/zerotier-one/identity.public >> moon.json

# Отредактируйте moon.json: в roots[].stableEndpoints укажите реальные
# IP:порт каждого moon-сервера, например "10.0.0.2/9993"

# Сгенерировать подписанный файл мира (создаст 000000<worldid>.moon)
zerotier-idtool genmoon moon.json
```

Файл `moon.json` содержит `signingKey_SECRET` — храните его в безопасном месте: он нужен для обновления мира.

**Конфигурация moon-серверов:** скопируйте полученный `*.moon` в подкаталог `moons.d` рабочего каталога (`/var/lib/zerotier-one/moons.d/`) и перезапустите службу на каждом moon-сервере.

**Подключение клиентов (desktop/server):** либо положите тот же `*.moon` в `moons.d` клиента, либо «орбитите» moon по world ID и адресу любого его корня:

```bash
sudo zerotier-cli orbit <worldID> <address>
# → 200 orbit OK

sudo zerotier-cli listmoons   # список известных moons
sudo zerotier-cli peers       # moon-серверы будут показаны с ролью MOON, а не LEAF
sudo zerotier-cli deorbit <worldID>   # покинуть moon
```

**Мобильные клиенты (iOS/Android):** начиная с версии 1.16.0 поддерживается загрузка planet-файла через URL вида `https://joinzt.com/addplanet?v=1&planet=<base64>`, либо в приложении через «Settings → Add Planet File».

### Сценарий 11: Подключение физической L2-сети (bridging)

ZeroTier эмулирует настоящий Ethernet-коммутатор, поэтому физическую сеть можно смостовать в виртуальную на L2 (нужно для протоколов, использующих broadcast/multicast: auto-discovery устройств, Wake-on-LAN, промышленное оборудование). Узел-мост должен быть явно назначен мостом в контроллере; он получает повышенный объем multicast-трафика (контроллер агрессивнее запрашивает у него подписки).

```bash
# На Linux: создать мост и включить в него физический и ZeroTier-интерфейсы
sudo ip link add name br0 type bridge
sudo ip link set br0 up
sudo ip link set eth0 master br0
sudo ip link set zt5kx6mxtu master br0

# Назначить IP мосту (сам интерфейс ZeroTier при этом остается без адреса)
sudo ip addr add 192.168.100.10/24 dev br0
```

Bridging существенно сложнее routing и обычно не требуется: для доступа к физическому LAN предпочтительнее маршрутизация (см. [Сценарий 4](#сценарий-4-site-to-site-соединение-двух-офисов)). DHCP через мост лучше фильтровать, чтобы не отдавать адреса из физической сети виртуальным узлам. Мост протестирован на Linux с нативным bridge-модулем ядра.

## Валидация

После применения правил проверьте корректность:

1. **Внутренняя связность:**
```bash
# С устройства в сети ZeroTier
ping <zerotier-ip>
# → 64 bytes from <ip>: icmp_seq=1 ttl=64 time=0.045 ms
```

2. **Публичные порты доступны извне:**
```bash
# С внешнего хоста
curl -I http://<external-ip>
# → HTTP/1.1 200 OK
```

3. **Защита Docker-портов:**
```bash
# С внешнего хоста
nmap <external-ip> -p 6379 -PN
# → PORT     STATE  SERVICE
# → 6379/tcp filtered

# С устройства в сети ZeroTier
nmap <zerotier-ip> -p 6379
# → PORT     STATE SERVICE
# → 6379/tcp open  redis
```

4. **Проверка правил и путей:**
```bash
# Действующие правила и состояние на узле
zerotier-cli -j dump | jq '.config.settings, .network'

# Убедиться, что соединение прямое (DIRECT), а не через relay
sudo zerotier-cli peers
# → <id> <version> ... <role> <path> ...   # в столбце path — DIRECT или RELAY
```

## Дополнительная информация

### Справочник команд zerotier-cli

Основные подкоманды (`sudo` требуется для управления службой; `-j` — вывод в JSON):

| Команда | Назначение |
|---------|-----------|
| `zerotier-cli info` | Node ID, версия, статус ONLINE/OFFLINE |
| `zerotier-cli status` | Краткий статус сервиса |
| `zerotier-cli listnetworks` | Список сетей узла, статус, адреса, маршруты |
| `zerotier-cli join <NWID>` / `leave <NWID>` | Присоединиться к сети / покинуть сеть |
| `zerotier-cli peers` | Пиры, роли (LEAF/PLANET/MOON), путь (DIRECT/RELAY) |
| `zerotier-cli set <NWID> <setting>` | Локальная настройка сети: `allowManaged`, `allowGlobal`, `allowDefault`, `allowDNS` |
| `zerotier-cli get <NWID> <setting>` | Прочитать локальную настройку сети |
| `zerotier-cli listmoons` / `orbit` / `deorbit` | Работа с moons (federated roots) |
| `zerotier-cli dump` | Полный дамп состояния для диагностики |

### Особенности и ограничения

- **MTU:** ZeroTier добавляет overhead (~40–60 байт). Стандартный MTU интерфейса — 2800. При использовании VPN поверх ZeroTier или для нестандартных путей (мобильные сети) MTU можно снизить. MTU задается на стороне контроллера и применяется после leave/rejoin:
  ```bash
  # Через Central API или локальный API контроллера; требуется leave + join
  curl -X POST "http://localhost:9993/controller/network/${NWID}" \
    -H "X-ZT1-AUTH: ${TOKEN}" -d '{"config": {"mtu": 1388}}'
  sudo zerotier-cli leave ${NWID} && sudo zerotier-cli join ${NWID}
  ```
  На Windows смена MTU носит «визуальный» характер: `netsh` показывает 2800, но фактический MTU применяется. При проблемах с фрагментацией используйте MSS Clamping. Подробнее: [MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md).

- **Производительность:** При невозможности P2P-соединения трафик ретранслируется через корневые серверы или TCP-fallback, что увеличивает задержку и снижает пропускную способность. Диагностика пути — `zerotier-cli peers`. Собственные moons для новых развертываний не рекомендуются (см. выше).

- **Безопасность:** Авторизация устройств происходит вручную в управляющем портале. Неавторизованные устройства не получают доступ к сети. Для сегментации внутри сети используйте Flow Rules; для автоматизации авторизации — API или self-hosted контроллер.

- **IPv6:** ZeroTier поддерживает IPv6 по аналогии с IPv4 — узлам можно выдавать адреса из `fd00::/8` или глобальные, включать managed routes. Общие принципы VPN и IPv6 — в [vpn-ipv6.md](./vpn-ipv6.md).

- **Лицензирование (начиная с линии 1.16.x):** ядро и сервис (`node/`, `include/`, `service/`, `osdep/`) распространяются под MPL-2.0; сетевой контроллер (`controller/` / каталог `nonfree/`) — под коммерческой source-available лицензией (не Open Source по определению OSI). Стандартные сборки контроллер не включают. Для сборки с контроллером используется `make ZT_NONFREE=1`, что переводит лицензию бинарника на проприетарную коммерческую. Коммерческое использование контроллера требует отдельного соглашения; некоммерческое/оценочное — до 30 дней.

- **Самостоятельный хостинг корневых серверов (MOON):** мобильные приложения поддерживают кастомные корневые серверы начиная с версии 1.16.0 (через planet-файл). Устаревшая оговорка: старые версии мобильных клиентов не поддерживали кастомные roots, из-за чего устройства без настроенного moon не видели друг друга.

### Самостоятельный хостинг контроллера

Для инфраструктур, требующих независимости от официального портала:

1. **Сборка ZeroTier One с контроллером:** демон собирается с флагом `ZT_NONFREE=1` (контроллер в каталоге `nonfree/controller`). Конфигурация сети хранится в `controller.d` рабочего каталога, идентичность контроллера — в `identity.secret`. Network ID контроллера привязан к Node ID.
2. **ZTNET** — веб-панель управления self-hosted контроллером на Next.js + PostgreSQL.
3. **ztncui (legacy)** — исторический веб-интерфейс к встроенному контроллеру. Проект переведен в архив и не поддерживается; актуальные Docker-образы поддерживает сообщество (например, `oupula/ztncui`). Применяется только для сопровождения существующих развертываний.
4. **ZeroTier One Enterprise** — официальное коммерческое решение вендора.

При резервном копировании контроллера критичны `identity.secret`, каталог `controller.d` и `authtoken.secret`.

### Типичные проблемы и решения

| Проблема | Причина | Решение |
|----------|---------|---------|
| Узел не получает IP | Не авторизован в управляющем портале | Авторизуйте узел, проверьте диапазон подсети |
| `zerotier-cli info` не отвечает | Демон не запущен | `sudo systemctl restart zerotier-one` |
| `200 join OK`, но нет connectivity | Интерфейс не поднят или конфликт IP | `ip link show zt*`, проверьте `zerotier-cli listnetworks` |
| P2P не устанавливается, только relay | Symmetric NAT, закрытый порт 9993 | Откройте UDP 9993; проверьте `zerotier-cli peers` |
| Высокая задержка | Трафик идет через relay | Убедитесь, что порт 9993 открыт, проверьте `zerotier-cli peers` |
| Метрик нет на `/metrics` | В 1.16.1+ сбор отключен по умолчанию | Включите `enableMetrics` в `local.conf`, перезапустите службу |
| Пакеты теряются после повышения MTU | Фрагментация в пути | Снизьте MTU сети на контроллере (leave/rejoin) или включите MSS Clamping |
| Конфликт подсетей с VPN/Docker | Пересечение диапазонов `10.0.0.0/24` | Измените подсеть ZeroTier на `10.255.0.0/24` |
| `orbit` возвращает `404` | Ошибка формата world ID (лишние ведущие нули) | Уберите ведущие нули: `zerotier-cli orbit <10hex> <10hex>` |

### Лучшие практики

- **Резервирование адресов:** Всегда назначайте Managed IP для серверов, чтобы избежать изменения адреса после перезагрузки.
- **Разделение сетей:** Используйте отдельные виртуальные сети для production, staging и management-доступа.
- **Сегментация:** Для ограничения доступа между узлами применяйте Flow Rules (tags/capabilities) вместо того, чтобы полагаться только на host-файрволы.
- **Мониторинг:** Включите `enableMetrics`, собирайте `/metrics` через Prometheus, настройте алерты на статус `UNSECURED`/`REKEYING` и на рост доли relay-трафика.
- **Автоматизация:** Для массового развертывания используйте `curl` к локальному API, Terraform-провайдер [terraform-provider-zerotier](https://github.com/zerotier/terraform-provider-zerotier) или Ansible.
- **Резервное копирование:** Сохраняйте конфигурацию контроллера (`controller.d/`), `identity.secret` и `authtoken.secret`.

### Очистка и удаление

```bash
# Выход из сети
sudo zerotier-cli leave <NETWORK_ID>

# Остановка и отключение службы
sudo systemctl stop zerotier-one
sudo systemctl disable zerotier-one

# Удаление пакета (Debian/Ubuntu)
sudo apt-get remove --purge zerotier-one

# Удаление данных
sudo rm -rf /var/lib/zerotier-one
sudo rm -rf /etc/zerotier-one

# Очистка правил iptables (если добавляли)
sudo iptables -D INPUT -i zt+ -j ACCEPT
# ... и другие удаленные правила
```

## См. также

- **[Обзор mesh-VPN решений](./mesh-vpn-overview.md)** — Nebula, Netbird, Netmaker и критерии выбора.
- **[Мониторинг VPN](./vpn-monitoring.md)** — метрики, textfile collector, SLI/SLO и алертинг.
- **[Аутентификация и SSO/MFA для VPN](./vpn-authentication.md)** — OIDC/SSO для mesh-контроллеров.
- **[IPv6 в VPN](./vpn-ipv6.md)** — особенности IPv6-адресации в туннелях и overlay-сетях.
- **[iptables и Docker: интеграция и DOCKER-USER](../Docker/Docker_network/troubleshooting/iptables_integration.md)** — управление правилами фильтрации для контейнеров.
- **[Сетевые политики Docker](../Docker/Docker_network/docker_network_policies.md)** — Defense-in-Depth, `--internal` сети, отключение ICC.
- **[WireGuard](./wireguard.md)** — альтернативный VPN-протокол для site-to-site сценариев.
- **[Tailscale](./tailscale.md)** — аналогичный сервис mesh-VPN с упрощенным управлением.
- **[MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — диагностика проблем фрагментации и MSS Clamping.
