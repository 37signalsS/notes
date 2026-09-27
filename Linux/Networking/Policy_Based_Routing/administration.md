# Администрирование Policy-Based Routing (PBR)

## Определения

**Администрирование PBR** — это процесс мониторинга, отладки и обеспечения долгосрочного сохранения (персистентности) правил маршрутизации на основе политик в операционной системе.

Основные задачи администратора включают верификацию прохождения трафика через нужные таблицы, диагностику блокировок фаерволом и настройку параметров ядра для корректной работы асимметричных путей.

Теоретические основы описаны в **[главном разделе (SSoT)](./index.md)**.

---

## Предпосылки

### Требования к ядру

Для функционирования PBR ядро Linux должно быть собрано с поддержкой следующих опций:

- `CONFIG_IP_ADVANCED_ROUTER` — расширенные возможности маршрутизации.
- `CONFIG_IP_MULTIPLE_TABLES` — поддержка множественных таблиц маршрутизации для IPv4.
- `CONFIG_IPV6_MULTIPLE_TABLES` — поддержка множественных таблиц маршрутизации для IPv6.

Путь в конфигурации ядра: `Networking support → Networking options → TCP/IP networking`.

```bash
# Проверка опций ядра
grep -E "CONFIG_IP_MULTIPLE_TABLES|CONFIG_IPV6_MULTIPLE_TABLES" /boot/config-$(uname -r)
# → CONFIG_IP_MULTIPLE_TABLES=y
# → CONFIG_IPV6_MULTIPLE_TABLES=y

# Проверка версии ядра (для L4-селекторов)
uname -r
# → 5.15.0-xx (ядро 4.17+ требуется для ipproto, dport, sport)
```

### Требования к пакетам

Пакет `iproute2` должен быть установлен в системе:

```bash
# Debian/Ubuntu
sudo apt install -y iproute2

# RHEL/CentOS/Rocky/Alma
sudo dnf install -y iproute
```

Для сценариев с маркировкой трафика требуется `nftables`:

```bash
# Debian/Ubuntu
sudo apt install -y nftables

# RHEL/CentOS/Rocky/Alma
sudo dnf install -y nftables
```

### Права доступа

Все команды `ip rule` (кроме `ip rule show`) требуют привилегий суперпользователя (`sudo`).

### Проверка начального состояния

Перед началом работы убедитесь, что система находится в ожидаемом состоянии:

```bash
# Просмотр текущих правил RPDB
ip rule show
# → 0:    from all lookup local
# → 32766: from all lookup main
# → 32767: from all lookup default

# Проверка таблиц маршрутизации
ip route show table all

# Проверка sysctl
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.default.rp_filter
```

---

## Основные концепции

### Инструментарий администратора

Для управления PBR в Linux используется стандартный стек утилит:

| Инструмент | Назначение |
| :--- | :--- |
| **`ip rule`** | Просмотр и изменение базы данных правил (RPDB). |
| **`ip route`** | Работа с таблицами маршрутизации (ID 1–255). |
| **`sysctl`** | Управление параметрами сетевого стека (`rp_filter`). |
| **`nft / iptables`** | Трассировка и диагностика маркировки трафика. |
| **`tcpdump`** | Захват трафика на конкретных интерфейсах для проверки симметрии. |
| **`conntrack`** | Просмотр и управление таблицей отслеживания соединений (для CONNMARK). |
| **`ss` / `netstat`** | Диагностика активных соединений и портов. |

### Взаимодействие с подсистемами ядра

#### Netfilter и маркировка трафика

Правила `ip rule` срабатывают **после** цепочки `PREROUTING` и **после** цепочки `OUTPUT` в Netfilter. Это означает:

- Маркировка (`fwmark`) должна устанавливаться в `PREROUTING` (для входящего трафика) или `OUTPUT` (для исходящего).
- Маркировка в `POSTROUTING` **не работает** для PBR (пакет уже прошел этап маршрутизации).

```bash
# Правильно: маркировка в PREROUTING
nft add rule inet filter prerouting tcp dport 443 meta mark set 0x1

# Неправильно: маркировка в POSTROUTING (не работает для PBR)
# nft add rule inet filter postrouting tcp dport 443 meta mark set 0x1
```

#### Reverse Path Filtering (rp_filter)

При использовании PBR критически важно перевести интерфейсы в режим **Loose (2)**:

- `0`: Без фильтрации.
- `1` (Strict): Проверка, является ли входящий интерфейс оптимальным путем для обратного маршрута. **Несовместимо с PBR.**
- `2` (Loose): Проверка наличия любого маршрута к адресу источника через любой интерфейс. **Рекомендуемый режим для PBR.**

```bash
# Рекомендуемая настройка в /etc/sysctl.d/99-pbr.conf
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2

# Применение без перезагрузки
sudo sysctl -p /etc/sysctl.d/99-pbr.conf
```

#### Conntrack и CONNMARK

Для симметричной маршрутизации долгих соединений используется механизм сохранения меток в таблице conntrack. Важные параметры:

```bash
# Текущие лимиты conntrack
sysctl net.netfilter.nf_conntrack_count
sysctl net.netfilter.nf_conntrack_max

# Таймаут для установленных соединений (по умолчанию 5 дней)
sysctl net.netfilter.nf_conntrack_tcp_timeout_established

# Рекомендация для систем с высокой нагрузкой: уменьшить таймаут
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600
```

### Персистентность конфигурации

По умолчанию изменения, внесенные через команды `ip`, являются эфемерными и сохраняются только до перезагрузки системы. Настройка персистентности зависит от используемого в дистрибутиве сетевого менеджера.

---

## Практические сценарии администрирования

### Диагностика и верификация (Troubleshooting)

#### 1. Проверка выбора маршрута (ip route get)

Это самый важный инструмент для проверки PBR. Он позволяет увидеть, какую таблицу и шлюз выберет ядро для конкретного пакета без его реальной отправки.

```bash
# Эмуляция входящего пакета (проверка асимметрии)
ip route get 1.1.1.1 from 2.2.2.2 iif eth1

# Эмуляция исходящего пакета с меткой
ip route get 8.8.8.8 mark 0x1

# Проверка с указанием таблицы (явный запрос)
ip route get 8.8.8.8 table 100
```

#### 2. Трассировка меток в nftables

Если пакет "уходит не туда", нужно проверить, устанавливается ли метка и на каком этапе.

```bash
# Включение мониторинга событий nftables
nft monitor

# Добавление временного правила логирования для отладки
nft add rule inet filter output ip daddr 8.8.8.8 log prefix "PBR-DEBUG: "
```

#### 3. Детальный просмотр правил

Использование флага `-d` (details) позволяет увидеть дополнительные параметры, такие как подавление префиксов или принадлежность к VRF.

```bash
ip -d rule show
```

### Сохранение настроек (Persistence)

#### NetworkManager (nmcli) {#networkmanager}

Для систем с NetworkManager (Desktop, RHEL/CentOS/Alma):

```bash
# Добавление правила и маршрута к соединению
nmcli connection modify "ISP1" +ipv4.routing-rules "from 192.168.1.100 table 101"
nmcli connection modify "ISP1" +ipv4.routes "0.0.0.0/0 192.168.1.1 101"
nmcli connection up "ISP1"
```

#### Netplan (Ubuntu/Debian) {#netplan}

Файл `/etc/netplan/50-cloud-init.yaml`:

```yaml
network:
  ethernets:
    eth0:
      routing-policy:
        - from: 10.0.0.10
          table: 100
          priority: 1000
```

#### Systemd-networkd {#systemd-networkd}

Файл `/etc/systemd/network/eth0.network`:

```ini
[RoutingPolicyRule]
From=10.0.0.10
Table=100
Priority=1000
```

### Мониторинг и алертинг

В Linux нет встроенного счетчика попаданий (hit count) для правил `ip rule`. Для мониторинга активности правил рекомендуется использовать `nftables` со счетчиками для тех же критериев, что и в PBR.

```bash
# Создание счетчика для мониторинга трафика, подпадающего под PBR (метка 0x1)
nft add rule inet filter output meta mark 0x1 counter

# Просмотр счетчиков
nft list ruleset | grep counter
# → counter packets 42 bytes 3014
```

Для сбора метрик в production-средах используйте `nftables` в связке с `prometheus-node-exporter` или кастомным скриптом, опрашивающим `nft list ruleset`.

---

## Персистентность конфигурации

По умолчанию изменения, внесенные через команды `ip`, являются эфемерными и сохраняются только до перезагрузки системы. Ниже приведены все основные методы обеспечения персистентности.

### Сводная таблица методов

| Метод | Файл / Команда | Поддерживаемые дистрибутивы |
| :--- | :--- | :--- |
| **NetworkManager** | `nmcli connection modify <name> +ipv4.routing-rules "from ... table ..."` | RHEL, CentOS, Alma, Rocky, Fedora |
| **Netplan** | `routing-policy:` в YAML-файле | Ubuntu 18.04+, Debian |
| **systemd-networkd** | Секция `[RoutingPolicyRule]` в `.network` файле | RHEL, Ubuntu, Debian, Arch |
| **/etc/network/interfaces** | `post-up` хуки | Debian legacy, Ubuntu legacy |
| **Скрипт в rc.local** | `ip rule restore < /etc/ip_rules.conf` | Универсальный метод |
| **Systemd-сервис** | ExecStart=`/usr/local/bin/pbr-restore.sh` | Любой systemd-дистрибутив |

### Подробные примеры

#### NetworkManager {#networkmanager}

```bash
# Добавление правила и маршрута к соединению
nmcli connection modify "ISP1" +ipv4.routing-rules "from 192.168.1.100 table 101"
nmcli connection modify "ISP1" +ipv4.routes "0.0.0.0/0 192.168.1.1 101"
nmcli connection up "ISP1"
```

#### Netplan {#netplan}

```yaml
# /etc/netplan/50-cloud-init.yaml
network:
  version: 2
  ethernets:
    eth0:
      routing-policy:
        - from: 10.0.0.10
          table: 100
          priority: 1000
      routes:
        - to: 0.0.0.0/0
          via: 192.168.1.1
          table: 100
```

```bash
# Применение конфигурации
sudo netplan apply
```

#### Systemd-networkd {#systemd-networkd}

```ini
# /etc/systemd/network/eth0.network
[Match]
Name=eth0

[Network]
Address=192.168.1.100/24
Gateway=192.168.1.1

[RoutingPolicyRule]
From=10.0.0.10
Table=100
Priority=1000

[Route]
Table=100
Destination=0.0.0.0/0
Gateway=192.168.1.1
```

```bash
# Применение конфигурации
sudo systemctl restart systemd-networkd
```

#### Systemd-сервис (универсальный метод)

Для дистрибутивов, где сетевой менеджер не поддерживает PBR напрямую, создайте systemd-сервис:

```bash
# /usr/local/bin/pbr-restore.sh
#!/bin/bash
set -euo pipefail

# Ожидание готовности сети
sleep 5

# Восстановление правил
ip rule restore < /etc/ip_rules_v4.conf
ip -6 rule restore < /etc/ip_rules_v6.conf 2>/dev/null || true

# Восстановление маршрутов в таблицах
ip route restore < /etc/ip_routes_v4.conf 2>/dev/null || true
```

```ini
# /etc/systemd/system/pbr-restore.service
[Unit]
Description=PBR Rules Restore
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/pbr-restore.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
# Активация сервиса
sudo chmod +x /usr/local/bin/pbr-restore.sh
sudo systemctl daemon-reload
sudo systemctl enable --now pbr-restore.service
```

#### Резервный метод: rc.local

```bash
# /etc/rc.local
#!/bin/bash
sleep 10
ip rule add from 10.0.0.0/8 table 100 priority 100
ip route add default via 192.168.1.1 dev eth0 table 100
exit 0
```

```bash
sudo chmod +x /etc/rc.local
sudo systemctl enable rc-local
```

### Бэкап и восстановление правил

Для ручного сохранения и восстановления правил используйте встроенные команды `ip`:

```bash
# Сохранение текущих правил IPv4
ip rule save > /etc/ip_rules_v4.conf

# Восстановление правил
sudo ip rule restore < /etc/ip_rules_v4.conf

# Для IPv6
ip -6 rule save > /etc/ip_rules_v6.conf
sudo ip -6 rule restore < /etc/ip_rules_v6.conf
```

### Валидация персистентности

После настройки персистентности проверьте корректность:

```bash
# 1. Проверка применения правил
ip rule show
# → Должны присутствовать все добавленные правила

# 2. Проверка маршрутов в таблицах
ip route show table 100
# → Должен присутствовать default via ...

# 3. Перезагрузка и проверка
sudo reboot
# После перезагрузки:
ip rule show
ip route show table 100
# → Правила и маршруты должны сохраниться
```

---

## Диагностика и устранение неисправностей

### Типичные проблемы и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Пакет дропается при входе** | Strict RPF (`rp_filter=1`) | Установить `net.ipv4.conf.<iface>.rp_filter = 2` (Loose mode). |
| **Маршрут игнорируется** | Конфликт приоритетов | Проверить `ip rule show`, переместить правило выше (меньший номер приоритета). |
| **Не работает SBR для IPv6** | Отсутствие `CONFIG_IPV6_MULTIPLE_TABLES` | Проверить конфиг ядра или использовать `ip -6 rule`. |
| **Метка не видна в PBR** | Маркировка в `POSTROUTING` | Перенести маркировку в `PREROUTING` или `MANGLE/OUTPUT` (до этапа маршрутизации). |
| **Таблица пуста** | Маршрут не добавлен в таблицу | Проверить `ip route show table <ID>`. |
| **"RTNETLINK answers: Invalid argument"** | Неверный синтаксис или неподдерживаемый селектор | Проверить версию ядра и синтаксис команды. |
| **"RTNETLINK answers: File exists"** | Правило с таким же селектором и приоритетом уже существует | Удалить существующее правило или изменить приоритет. |
| **Правило пропадает после перезагрузки** | Команды `ip rule` эфемерны | Настроить персистентность (см. раздел выше). |
| **Правило добавлено, но не работает** | Селектор не соответствует атрибутам пакета | Использовать `ip route get` с теми же параметрами (from, iif, fwmark). |
| **Асимметрия ответного трафика** | Отсутствует PBR для ответов | Добавить правило `from <source_ip> table <table>` или настроить `rp_filter=2`. |
| **DNS не работает через VPN** | DNS-запросы уходят не через VPN | Добавить правило для UDP/53 или использовать VPN-серверы как DNS. |
| **Long SSH session drops on failover** | Переключение ISP разрывает соединения | Использовать CONNMARK для сохранения симметрии сессий. |

### Детальные процедуры диагностики

#### Проблема: Правило добавлено, но не работает

```bash
# 1. Проверка наличия правила
ip rule show | grep "priority_500"
# → Если пусто — правило не добавлено

# 2. Проверка таблицы
ip route show table 150
# → Если пусто — нет маршрутов в целевой таблице

# 3. Эмуляция выбора маршрута
ip route get 8.8.8.8 from 192.168.1.50
# → Если показывает таблицу main — правило не совпало

# 4. Проверка приоритета
ip rule show | grep -E "^ *[0-9]+:"
# → Правило с меньшим приоритетом может перехватить пакет
```

**Решение:** Убедитесь, что селектор правила соответствует атрибутам пакета. Используйте `ip route get` с теми же параметрами (from, iif, fwmark), что и в правиле.

#### Проблема: Конфликт правил

```bash
# Просмотр правил в порядке приоритета
ip rule show
# → 100:    from 10.0.0.0/8 lookup table_A
# → 200:    from 10.0.0.0/8 lookup table_B
# → ↑ Правило с приоритетом 100 сработает первым

# Эмуляция для конкретного пакета
ip route get 8.8.8.8 from 10.0.0.5
# → Покажет, какую таблицу выбрало ядро
```

**Решение:** Измените приоритет конфликтующего правила или уточните селектор.

#### Проблема: Асимметрия и rp_filter

```bash
# Проверка текущего значения rp_filter
sysctl net.ipv4.conf.eth0.rp_filter
# → 1 (Strict) — несовместимо с PBR

# Временное включение Loose mode
sudo sysctl -w net.ipv4.conf.all.rp_filter=2
sudo sysctl -w net.ipv4.conf.default.rp_filter=2

# Постоянное включение в /etc/sysctl.d/99-pbr.conf
cat <<EOF | sudo tee /etc/sysctl.d/99-pbr.conf
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2
EOF

sudo sysctl -p /etc/sysctl.d/99-pbr.conf
```

#### Проблема: Правило пропадает после перезагрузки

```bash
# Проверка персистентности
sudo reboot
ip rule show
# → Если пользовательских правил нет — персистентность не настроена

# Настройка через systemd-сервис (универсальный метод)
# См. раздел "Персистентность конфигурации" выше
```

#### Проблема: "RTNETLINK answers: Invalid argument"

```bash
# Проверка версии ядра
uname -r
# → 5.15.0-xx (должно быть 4.17+ для L4-селекторов)

# Проверка таблицы
ip route show table 150
# → Если пусто — создайте маршрут
sudo ip route add default via 192.168.1.1 dev eth0 table 150
```

#### Проблема: "RTNETLINK answers: File exists"

```bash
# Просмотр существующего правила
ip rule show | grep "from 10.0.0.0/8"
# → 100:    from 10.0.0.0/8 lookup isp1_table

# Удаление перед добавлением
sudo ip rule del from 10.0.0.0/8 table isp1_table priority 100
sudo ip rule add from 10.0.0.0/8 table isp2_table priority 100

# Или использование другого приоритета
sudo ip rule add from 10.0.0.0/8 table isp2_table priority 101
```

#### Проблема: Не работает IPv6 PBR

```bash
# Проверка IPv6-правил
ip -6 rule show
# → Если пусто — нет IPv6-правил

# Проверка поддержки ядра
grep CONFIG_IPV6_MULTIPLE_TABLES /boot/config-$(uname -r)
# → CONFIG_IPV6_MULTIPLE_TABLES=y

# Эмуляция IPv6-маршрута
ip -6 route get 2001:db8::1 from 2001:db8::100
```

#### Проблема: Трафик локально генерируемых пакетов не маршрутизируется по PBR

```bash
# Проверка правила для локального трафика
ip rule show | grep "iif lo"
# → Если пусто — добавьте правило

# Правило для локального трафика
sudo ip rule add iif lo ipproto tcp sport 8080 table proxy_table priority 200

# Проверка
ip route get 8.8.8.8 from 127.0.0.1 iif lo sport 8080
```

---

## Валидация после изменений

После добавления или изменения правил всегда проверяйте корректность:

```bash
# 1. Проверка наличия правила
ip rule show | grep "1000:"
# → 1000:    from 192.168.1.0/24 lookup vpn_table

# 2. Эмуляция выбора маршрута (без реальной отправки)
ip route get 8.8.8.8 from 192.168.1.50
# → 8.8.8.8 via 10.0.0.1 dev tun0 table vpn_table src 192.168.1.50

# 3. Проверка маршрута в целевой таблице
ip route show table vpn_table
# → default via 10.0.0.1 dev tun0

# 4. Проверка связи (если возможно)
ping -c 3 -I 192.168.1.50 8.8.8.8

# 5. Проверка с конкретными атрибутами (fwmark, iif)
ip route get 8.8.8.8 mark 0x1
ip route get 8.8.8.8 from 2.2.2.2 iif eth1

# 6. Проверка IPv6 (если настроено)
ip -6 rule show
ip -6 route get 2001:db8::1 from 2001:db8::100
```

### Чек-лист валидации

| Этап | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| **Правила** | `ip rule show` | Все добавленные правила присутствуют с правильными приоритетами |
| **Таблицы** | `ip route show table <ID>` | В каждой таблице присутствуют необходимые маршруты |
| **Выбор маршрута** | `ip route get <dst> from <src>` | Выбранная таблица и шлюз соответствуют ожиданиям |
| **Симметрия** | `tcpdump -i <iface>` на обоих интерфейсах | Ответный трафик уходит через тот же интерфейс |
| **Связность** | `ping -c 3 -I <src_ip> <dst>` | Ping проходит успешно через правильный интерфейс |
| **IPv6** | `ip -6 rule show` и `ip -6 route get` | Аналогичные проверки для IPv6 |

---

## Производительность и оптимизация

### Влияние на производительность

Поскольку проверка RPDB происходит последовательно, большое количество правил (сотни и тысячи) может увеличить задержку обработки пакетов.

**Рекомендации:**
1. **Минимизируйте количество правил:** Используйте агрегированные префиксы (`from 10.0.0.0/8` вместо множества `/24`).
2. **Группируйте по приоритетам:** Чем меньше диапазон приоритетов, тем быстрее поиск.
3. **Избегайте избыточных селекторов:** Если `from` достаточно, не добавляйте `iif`.
4. **Используйте VRF для массовой изоляции:** Для сотен интерфейсов VRF производительнее, чем тысячи правил `ip rule`.
5. **Мониторьте задержку:** Используйте `tc` для измерения задержки на интерфейсах до и после включения PBR.

### Ядерные параметры для tuning

```bash
# Размер таблицы маршрутизации (если много маршрутов)
sudo sysctl -w net.ipv4.route.max_size=65536

# Размер FIB (Forwarding Information Base)
sudo sysctl -w net.ipv4.fib_multipath_hash_policy=1

# Политика хеширования ECMP (по 5-tuple для стабильности)
sudo sysctl -w net.ipv4.fib_multipath_hash_policy=1
```

### ECMP и PBR

При использовании ECMP с PBR учитывайте:
- ECMP распределяет трафик по хешу. Если PBR направляет часть трафика в отдельную таблицу, ECMP не применяется к этому трафику.
- Для стабильности сессий используйте `fib_multipath_hash_policy=1` (5-tuple hash).
- Проверяйте Nexthop после отключения интерфейса: `ip route get 8.8.8.8`.

---

## Автоматизация и управление изменениями

### Идемпотентные скрипты

Все административные скрипты должны быть идемпотентными (повторяемый запуск не ломает конфигурацию):

```bash
#!/bin/bash
# /usr/local/bin/pbr-setup.sh
set -euo pipefail

TABLE_ID=100
TABLE_NAME=isp1_table
PRIORITY=100
GATEWAY=192.168.1.1
DEVICE=eth0

# Создание таблицы (идемпотентно)
grep -q "^${TABLE_ID}.*${TABLE_NAME}" /etc/iproute2/rt_tables || \
  echo "${TABLE_ID} ${TABLE_NAME}" | sudo tee -a /etc/iproute2/rt_tables

# Удаление старого правила (если есть)
sudo ip rule del priority ${PRIORITY} 2>/dev/null || true

# Добавление правила
sudo ip rule add from all table ${TABLE_NAME} priority ${PRIORITY}

# Добавление маршрута (идемпотентно)
sudo ip route replace default via ${GATEWAY} dev ${DEVICE} table ${TABLE_NAME}

echo "PBR configured: table=${TABLE_NAME}, priority=${PRIORITY}"
```

### Тестирование изменений

Перед применением PBR-изменений в production протестируйте их в lab-среде:

```bash
# 1. Проверка синтаксиса
ip route add default via 192.168.1.1 dev eth0 table 100 2>&1 || true

# 2. Валидация правил
ip rule show
ip route show table 100

# 3. Тестирование с test-хоста
ip route get 8.8.8.8 from 192.168.1.50

# 4. Мониторинг в течение 5 минут
watch -n 1 'ip rule show; echo "---"; ip route show table 100'
```

### Управление конфигурацией

Храните PBR-конфигурацию в системе управления версиями:

```
/etc/pbr/
├── rules/
│   ├── v4.rules
│   └── v6.rules
├── routes/
│   ├── v4.routes
│   └── v6.routes
└── scripts/
    └── apply.sh
```

```bash
# Применение конфигурации из Git
cd /etc/pbr
git pull origin main
./scripts/apply.sh
```

---

## Очистка среды и откат изменений

### Удаление конкретного правила

```bash
# Удаление по атрибутам (необходимо полное совпадение параметров)
sudo ip rule del from 10.0.0.0/8 table isp1_table priority 100

# Удаление по приоритету (наиболее надежный способ)
sudo ip rule del priority 1000

# Удаление IPv6-правила
sudo ip -6 rule del priority 500

# Проверка после удаления
ip rule show
```

### Массовая очистка правил

```bash
# Удаление всех правил с определенным приоритетом
for pri in $(seq 1000 1099); do
  sudo ip rule del priority $pri 2>/dev/null
done

# Очистка всех пользовательских правил (оставляет только системные)
sudo ip rule flush

# Проверка после очистки
ip rule show
# → 0:    from all lookup local
# → 32766: from all lookup main
# → 32767: from all lookup default
```

### Очистка таблиц маршрутизации

```bash
# Очистка конкретной таблицы
sudo ip route flush table 100

# Очистка всех таблиц кроме main, local, default
sudo ip route flush table 1-252

# Проверка после очистки
ip route show table all
```

### Удаление правил nftables

```bash
# Просмотр правил с handles
nft -a list ruleset | grep "meta mark set 0x1"

# Удаление по handle
nft delete rule inet filter prerouting handle 123

# Или удаление всего таблицы (осторожно!)
nft delete table inet filter
```

### Экстренный откат

```bash
# 1. Сохранение текущих правил (перед очисткой)
ip rule save > /tmp/ip_rules_backup_$(date +%F_%H%M).rules

# 2. Откат к стандартным правилам
sudo ip rule flush

# 3. Восстановление маршрутов по умолчанию
sudo ip route flush table main
sudo ip route add default via <PRIMARY_GW> dev eth0

# 4. Проверка
ip rule show
ip route get 8.8.8.8
ping -c 3 8.8.8.8
```

---

## Лучшие практики

1. **Всегда указывайте `priority`:** Без него правила добавляются с уменьшающимся приоритетом относительно последнего добавленного, что может нарушить логику PBR.
2. **Используйте осмысленные имена таблиц:** Записывайте их в `/etc/iproute2/rt_tables` и используйте в командах вместо числовых ID.
3. **Группируйте правила по диапазонам приоритетов:**
   | Диапазон | Назначение |
   | :--- | :--- |
   | **1–99** | Критичные системные правила (VPN-шлюзы, маршруты по умолчанию для специфических подсетей). |
   | **100–999** | Основные PBR-правила (разделение трафика по портам, протоколам, пользователям). |
   | **1000–32765** | Правила общего назначения, временные правила, отладка. |
4. **Валидируйте после каждого изменения:** Используйте `ip route get` с теми же параметрами, что и в правиле.
5. **Не используйте `flush` в продакшене без бэкапа:** Сохраняйте правила перед очисткой: `ip rule save > /tmp/backup.rules`.
6. **Мониторьте conntrack:** При использовании CONNMARK отслеживайте `nf_conntrack_count` и `nf_conntrack_max`.
7. **Избегайте `rp_filter=1` (Strict) при PBR:** Используйте `rp_filter=2` (Loose) или отключите на проблемных интерфейсах.
8. **Документируйте изменения:** Ведите журнал изменений PBR-конфигурации.
9. **Используйте `ip -d rule show`:** Детальный вывод помогает обнаружить suppress_prefixlength и VRF-привязки.
10. **Маркируйте трафик до маршрутизации:** Помните, что `ip rule` срабатывает после `PREROUTING` и `OUTPUT`; маркировка в `POSTROUTING` не работает.

### Резервное копирование

```bash
# Полный бэкап PBR-конфигурации
{
  echo "# Резервная копия PBR от $(date)"
  echo "# Правила IPv4"
  ip rule save
  echo "# Маршруты IPv4"
  ip route show table all
  echo "# Правила IPv6"
  ip -6 rule save
  echo "# Маршруты IPv6"
  ip -6 route show table all
  echo "# Sysctl"
  sysctl -a | grep rp_filter
  echo "# nftables"
  nft list ruleset
} > /tmp/pbr_backup_$(date +%F_%H%M).conf
```

### Версионирование и откат PBR-конфигурации

#### Структура хранения

```
/etc/pbr/
├── rules/
│   ├── v4.rules          # ip rule save
│   └── v6.rules          # ip -6 rule save
├── routes/
│   ├── v4.routes          # ip route show table all
│   └── v6.routes
├── sysctl/
│   └── 99-pbr.conf       # sysctl-параметры
├── nftables/
│   └── pbr-marking.nft   # правила маркировки
├── scripts/
│   ├── apply.sh          # применение конфигурации
│   ├── rollback.sh       # откат к предыдущей версии
│   └── backup.sh         # резервное копирование
└── versions/
    └── 2026-01-15_v2/    # архивные версии
```

#### Скрипт бэкапа

```bash
#!/bin/bash
# /etc/pbr/scripts/backup.sh
set -euo pipefail

PBR_DIR="/etc/pbr"
VERSION_DIR="${PBR_DIR}/versions/$(date +%F_%H%M)"
mkdir -p "$VERSION_DIR"

# Сохранение текущего состояния
ip rule save > "${VERSION_DIR}/v4.rules"
ip -6 rule save > "${VERSION_DIR}/v6.rules" 2>/dev/null || true
ip route show table all > "${VERSION_DIR}/v4.routes"
ip -6 route show table all > "${VERSION_DIR}/v6.routes" 2>/dev/null || true
sysctl -a | grep -E "rp_filter|ip_forward|conntrack" > "${VERSION_DIR}/sysctl.txt"
nft list ruleset > "${VERSION_DIR}/nftables.nft" 2>/dev/null || true

echo "Backup created: ${VERSION_DIR}"
```

#### Скрипт отката

```bash
#!/bin/bash
# /etc/pbr/scripts/rollback.sh
set -euo pipefail

PBR_DIR="/etc/pbr"

# Поиск последней версии
LAST_VERSION=$(ls -1d "${PBR_DIR}/versions/"* 2>/dev/null | sort -r | head -1)

if [ -z "$LAST_VERSION" ]; then
    echo "No backup versions found"
    exit 1
fi

echo "Rolling back to: ${LAST_VERSION}"

# Бэкап текущего состояния (перед откатом)
bash "${PBR_DIR}/scripts/backup.sh"

# Восстановление правил
ip rule flush
ip rule restore < "${LAST_VERSION}/v4.rules"
ip -6 rule restore < "${LAST_VERSION}/v6.rules" 2>/dev/null || true

# Восстановление маршрутов
ip route restore < "${LAST_VERSION}/v4.routes" 2>/dev/null || true

# Восстановление sysctl
sysctl -p "${LAST_VERSION}/sysctl.txt" 2>/dev/null || true

echo "Rollback completed. Verify with: ip rule show && ip route get 8.8.8.8"
```

#### Версионирование в Git

```bash
# Инициализация Git-репозитория
cd /etc/pbr
git init
git add .
git commit -m "Initial PBR configuration"

# После изменений
bash /etc/pbr/scripts/backup.sh
git add -A
git commit -m "PBR: add ISP2 failover rules"

# Откат через Git
git log --oneline
# → a1b2c3d PBR: add ISP2 failover rules
# → e4f5g6h Initial PBR configuration

git checkout e4f5g6h -- .
bash /etc/pbr/scripts/apply.sh
```

#### Применение конфигурации

```bash
#!/bin/bash
# /etc/pbr/scripts/apply.sh
set -euo pipefail

PBR_DIR="/etc/pbr"

echo "Applying PBR configuration..."

# Бэкап перед применением
bash "${PBR_DIR}/scripts/backup.sh"

# Восстановление правил
ip rule restore < "${PBR_DIR}/rules/v4.rules"
ip -6 rule restore < "${PBR_DIR}/rules/v6.rules" 2>/dev/null || true

# Восстановление маршрутов
ip route restore < "${PBR_DIR}/routes/v4.routes" 2>/dev/null || true

# Применение sysctl
sysctl -p "${PBR_DIR}/sysctl/99-pbr.conf" 2>/dev/null || true

# Валидация
echo "Validating..."
ip rule show > /dev/null || { echo "FAILED: ip rule"; exit 1; }
ip route get 8.8.8.8 > /dev/null || { echo "FAILED: route check"; exit 1; }
ping -c 1 -W 2 8.8.8.8 > /dev/null || { echo "WARNING: ping failed"; }

echo "PBR configuration applied successfully"
```

---

## Дополнительная информация

### Влияние на производительность

Поскольку проверка RPDB происходит последовательно, большое количество правил (сотни и тысячи) может увеличить задержку обработки пакетов. Для массовой изоляции трафика предпочтительнее использовать VRF.

### Ссылки и связанные документы

- **[Policy-Based Routing (PBR) — Обзор](./index.md)** — архитектура и база данных правил RPDB.
- **[Практические сценарии PBR](./scenarios.md)** — типовые конфигурации (Dual-ISP, VPN-split, ECMP).
- **[ip rule & PBR](../Tools/iproute2/ip_rule_pbr.md)** — подробный справочник синтаксиса, селекторов и приоритетов.
- **[RPF и uRPF](../../../Networking/Protocols/rpf_urpf.md)** — глубокое погружение в механизмы фильтрации обратного пути.
- **[Маршрутизация в Linux](../../../Linux/SystemAdministration/routing.md)** — команды и диагностика (`ip rule`, `nexthop`).
- **[VRF в Linux](../../../Linux/Networking/vrf.md)** — альтернативный подход к изоляции таблиц.
- **[Автоматизация PBR](./automation.md)** — Ansible для управления PBR-конфигурацией.
- **[Conntrack и PBR](./conntrack_pbr.md)** — CONNMARK, conntrack zones, tuning.
- **[Продвинутая диагностика PBR](./advanced_diagnostics.md)** — eBPF, tcpdump BPF, nft log.
- **[PBR и контейнеры](./pbr_and_containers.md)** — Docker, Kubernetes, rp_filter.
- **[Sysctl tuning для PBR](./sysctl_pbr.md)** — production-профили sysctl.
