# ZeroTier: Виртуальные сети поверх интернета

ZeroTier — платформа для создания защищенных виртуальных L2-сетей между устройствами независимо от их местоположения. Она обеспечивает NAT-траверсал, позволяя узлам взаимодействовать напрямую по принципу P2P, как если бы они находились в одной физической локальной сети.

- **Сайт:** [zerotier.com](https://www.zerotier.com/)
- **Исходный код:** [github.com/zerotier/ZeroTierOne](https://github.com/zerotier/ZeroTierOne)

## Определения

- **ZeroTier** — платформа виртуального сетевого оборудования, создающая overlay-сети на уровне L2.
- **Виртуальная сеть (Network)** — логический контейнер, объединяющий авторизованные узлы в единый сегмент с уникальным **Network ID**.
- **Узел (Node)** — устройство, запустившее клиент ZeroTier и присоединившееся к виртуальной сети. Каждому узлу присваивается **Node ID** (на основе открытого ключа Curve25519).
- **Контроллер сети (Network Controller)** — компонент, отвечающий за выделение IP-адресов, аутентификацию узлов и распределение метаданных сети. В стандартной поставке управление осуществляется через официальный портал **ZeroTier Central**. При самостоятельном хостинге используются [ztncui](https://github.com/key-networks/ztncui), [ZTNET](https://github.com/asvspb/zerotier-via-docker) или собственный контроллер на базе открытого API.
- **Корневой сервер (Root / Planet Server)** — инфраструктура, обеспечивающая регистрацию узлов и установку P2P-соединений. При невозможности прямого соединения трафик ретранслируется через эти серверы. Все соединения остаются end-to-end зашифрованными.
- **MOON (Self-hosted Root)** — самостоятельно размещенный корневой сервер, позволяющий организовывать соединения внутри закрытой инфраструктуры без использования публичных корневых серверов ZeroTier.
- **Managed IP** — статический IP-адрес, зарезервированный за узлом в конфигурации контроллера.
- **Виртуальный сетевой интерфейс (vni)** — программный адаптер (обычно `zt+` или `ztt0` в Linux), через который узел подключается к виртуальной сети.

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
2. **Статический relay через корневые серверы** — если прямой P2P-проход невозможен (симметричный NAT, строгие файрволы), трафик ретранслируется через корневые серверы ZeroTier. При этом payload остается end-to-end зашифированным.

Для продакшн-сред с высокой нагрузкой и низкой толерантностью к задержкам рекомендуется размещать собственные MOON-серверы для минимизации зависимости от публических relay.

### Шифрование и аутентификация

Все соединения шифруются end-to-end:
- **Обмен ключами:** эллиптическая кривая **Curve25519**.
- **Шифрование трафика:** потоковый шифр **Salsa20**.
- **Аутентификация пакетов:** код аутентификации сообщений **Poly1305**.
- **Идентификация узлов:** Node ID формируется как хэш открытого ключа Curve25519, что исключает спуфинг.

Корневые серверы и контроллер видят только метаданные (Node ID, IP-адреса, статус соединения), но **не могут расшифровать пользовательский трафик**.

### Жизненный цикл узла

1. **Установка клиента** (`zerotier-one`) и запуск службы.
2. **Join** — узел отправляет запрос на присоединение к сети (`zerotier-cli join <NWID>`).
3. **Регистрация** — узел появляется в списке ожидающих авторизации в управляющем портале.
4. **Auth** — администратор авторизует узел.
5. **Выделение IP** — контроллер присваивает Managed IP (через DHCP или статическую резервацию).
6. **P2P negotiation** — узел договаривается о прямом соединении с другими узлами через корневые серверы.
7. **Traffic flow** — после установки P2P-сессии трафик идет напрямую; при разрыве — повторная negotiation через корневые серверы.

### Модели развертывания контроллера

- **Официальный управляющий портал (ZeroTier Central)** — управление сетью через веб-интерфейс от ZeroTier, Inc. Подходит для большинства сценариев, не требует обслуживания инфраструктуры.
- **Самостоятельный хостинг с ztncui** — веб-интерфейс с открытым исходным кодом для управления встроенным контроллером ZeroTier One. Примечание: начиная с версии **1.16.0** (август 2025), контроллер в стандартных сборках не включается по умолчанию и переведен на коммерческую лицензию (source-available). Для сборки с включенным контроллером требуется флаг `ZT_NONFREE=1`, что изменяет лицензию результирующего бинарника. Проект ztncui-aio переведен в архив и больше не поддерживается.
- **ZTNET** — современная альтернатива для самостоятельного хостинга на базе Next.js и PostgreSQL.

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

Подробнее: [WireGuard](./wireguard.md), [Tailscale](./tailscale.md)

## Практические сценарии

### Предварительные требования

**Аппаратные/программные требования:**
- **ОС:** Linux (ядро 3.10+), Windows 7+, macOS 10.14+, iOS 12+, Android 5+.
- **Порты:** UDP 9993 (входящий) — рекомендуется открыть для улучшения P2P-проходимости; при недоступности используется relay через корневые серверы.
- **Сеть:** Интернет-соединение без блокировки UDP. Для симметричного NAT или строгого файрвола требуется проброс порта 9993 или использование MOON.

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
# → <node_id> <version> <browser>
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

**Задача:** объединить локальную сеть офиса A (`192.168.10.0/24`) и офиса B (`192.168.20.0/24`) в единый адресное пространство через ZeroTier.

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

На клиенте через управляющий портал включите опцию **Allow Default Route** для соответствующего узла.

### Сценарий 6: Файрвол и сегментация

По умолчанию ZeroTier разрешает весь L2-трафик между авторизованными узлами. Для ограничения доступа настраивается `iptables` или `nftables`.

#### Принцип безопасности

- **Внешний интерфейс** (`eth0`, `ens3` и т.д.): открываются только необходимые порты.
- **Интерфейс ZeroTier** (`zt+` / `ztt0`): доступ регулируется правилами на каждом узле независимо.
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

# Детальная информация о пирах
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

Используйте экспортер [zerotier-exporter](https://github.com/zerotier/zerotier-exporter) или собирайте метрики из `zerotier-cli info` через `node_exporter` с `textfile collector`.

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

Для удаленного управления через REST API используйте [ZeroTier Central API](https://docs.zerotier.com/central-api/).

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

## Дополнительная информация

### Особенности и ограничения

- **MTU:** ZeroTier добавляет overhead (~40–60 байт). Стандартный MTU интерфейса — 2800. Если используется VPN поверх ZeroTier или большие фреймы, снизьте MTU:
  ```bash
  sudo ip link set zt+ mtu 1500
  ```
  При проблемах с фрагментацией используйте MSS Clamping. Подробнее: [MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md).

- **Производительность:** При невозможности P2P-соединения трафик ретранслируется через корневые серверы, что увеличивает задержку и снижает пропускную способность. Для продакшн-сред рекомендуется размещать собственные MOON-серверы.

- **Безопасность:** Авторизация устройств происходит вручную в управляющем портале. Неавторизованные устройства не получают доступ к сети. Для автоматизации авторизации используйте API или переместите управление в self-hosted контроллер.

- **Лицензирование (с версии 1.16.0):** Стандартные сборки ZeroTier One больше не включают контроллер сети. Компонент контроллера переведен на коммерческую source-available лицензию. Для некоммерческого использования или оценки (до 30 дней) требуется сборка с флагом `ZT_NONFREE=1`. С 1 января 2026 года лицензия планируется к переходу на Apache License 2.0.

- **Самостоятельный хостинг корневых серверов (MOON):** Mobile приложения (iOS, Android) на текущий момент не поддерживают кастомные корневые серверы. Только устройства с явно настроенными MOON будут видеть друг друга.

### Самостоятельный хостинг контроллера

Для инфраструктур, требующих полной независимости от официального портала:

1. **ztncui (legacy):** веб-интерфейс для встроенного контроллера ZeroTier One. Требует Node.js и сопутствующих зависимостей. Проект переведен в архив; актуальные Docker-образы доступны у сообщества (например, `oupula/ztncui`).
2. **ZTNET:** современная альтернатива на Next.js с PostgreSQL и NextAuth. Пример сборки: [asvspb/zerotier-via-docker](https://github.com/asvspb/zerotier-via-docker).

### Типичные проблемы и решения

| Проблема | Причина | Решение |
|----------|---------|---------|
| Узел не получает IP | Не авторизован в управляющем портале | Авторизуйте узел, проверьте диапазон подсети |
| `zerotier-cli info` не отвечает | Демон не запущен | `sudo systemctl restart zerotier-one` |
| `200 join OK`, но нет connectivity | Интерфейс не поднят или конфликт IP | `ip link show zt*`, проверьте `zerotier-cli listnetworks` |
| P2P не устанавливается, только relay | Symmetric NAT, закрытый порт 9993 | Откройте UDP 9993 или разверните MOON |
| Высокая задержка | Трафик идет через relay | Убедитесь, что порт 9993 открыт, проверьте `zerotier-cli peers` |
| Пакеты теряются после повышения MTU | Фрагментация в пути | Установите `net.ipv4.ip_no_pmtu_disc=0` или снизьте MTU |
| `ztncui` не подключается к контроллеру | Неверный `authtoken.secret` | Проверьте права `chmod 400 .env`, сравните токен |
| Конфликт подсетей с VPN/Docker | Пересечение диапазонов `10.0.0.0/24` | Измените подсеть ZeroTier на `10.255.0.0/24` |

### Лучшие практики

- **Резервирование адресов:** Всегда назначайте Managed IP для серверов, чтобы избежать изменения адреса после перезагрузки.
- **Разделение сетей:** Используйте отдельные виртуальные сети для production, staging и management-доступа.
- **Мониторинг:** Включите логирование (`journalctl -u zerotier-one`) и настройте алерты на статус `UNSECURED` или `REKEYING`.
- **Автоматизация:** Для массового развертывания используйте `curl` к локальному API или интеграцию с Ansible/Terraform через `zerotier-cli`.
- **Резервное копирование:** Сохраняйте конфигурацию контроллера (`/var/lib/zerotier-one/controller.d/`) и `authtoken.secret`.

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

- **[iptables и Docker: интеграция и DOCKER-USER](../Docker/Docker_network/troubleshooting/iptables_integration.md)** — управление правилами фильтрации для контейнеров.
- **[Сетевые политики Docker](../Docker/Docker_network/docker_network_policies.md)** — Defense-in-Depth, `--internal` сети, отключение ICC.
- **[WireGuard](./wireguard.md)** — альтернативный VPN-протокол для site-to-site сценариев.
- **[Tailscale](./tailscale.md)** — аналогичный сервис mesh-VPN с упрощенным управлением.
- **[MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — диагностика проблем фрагментации и MSS Clamping.
