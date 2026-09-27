# Практические сценарии Policy-Based Routing (PBR)

## Определения

**Практические сценарии PBR** — это набор типовых конфигураций и методов применения маршрутизации на основе политик для решения задач разделения интернет-каналов, обеспечения отказоустойчивости и изоляции сетевого трафика.

Подробное теоретическое описание механизмов PBR и базы данных правил RPDB приведено в **[главном разделе (SSoT)](./index.md)**.

---

## Основные концепции

### Компоненты реализации сценариев

Любой практический сценарий PBR базируется на взаимодействии трех уровней:

1.  **Таблицы маршрутизации**: Создание независимых наборов маршрутов. Рекомендуется использовать осмысленные имена таблиц в `/etc/iproute2/rt_tables`.
2.  **Правила маршрутизации (`ip rule`)**: Логика выбора таблицы на основе селекторов (адрес источника, метка пакета, входящий интерфейс, UID).
3.  **Маркировка трафика**: Использование `iptables` или `nftables` для классификации пакетов, когда стандартных селекторов L3 (`ip rule`) недостаточно.

---

## Предварительные требования для всех сценариев

Перед применением любого сценария убедитесь, что:

1.  **Пакет `iproute2` установлен:**
    ```bash
    # Debian/Ubuntu
    sudo apt install -y iproute2

    # RHEL/CentOS/Rocky/Alma
    sudo dnf install -y iproute
    ```

2.  **Ядро поддерживает множественные таблицы:**
    ```bash
    grep -E "CONFIG_IP_MULTIPLE_TABLES|CONFIG_IPV6_MULTIPLE_TABLES" /boot/config-$(uname -r)
    # → CONFIG_IP_MULTIPLE_TABLES=y
    # → CONFIG_IPV6_MULTIPLE_TABLES=y
    ```

3.  **Установлен `nftables` (для сценариев с маркировкой):**
    ```bash
    # Debian/Ubuntu
    sudo apt install -y nftables

    # RHEL/CentOS/Rocky/Alma
    sudo dnf install -y nftables
    ```

4.  **Созданы таблицы в `/etc/iproute2/rt_tables` (если используются имена):**
    ```bash
    echo "100 isp1_table" | sudo tee -a /etc/iproute2/rt_tables
    echo "200 vpn_user_table" | sudo tee -a /etc/iproute2/rt_tables
    ```

5.  **Валидация перед началом:**
    ```bash
    ip rule show
    # → Должны остаться только системные правила: local (0), main (32766), default (32767)

    ip route show table all
    # → Проверка отсутствия конфликтующих маршрутов
    ```

---

## Практические сценарии

### Сценарий 1: Разделение трафика по приложениям и портам

**Задача:** Направить HTTPS-трафик через быстрый канал (ISP1), а весь остальной трафик — через резервный (ISP2).

**Реализация (L4 PBR, ядро 4.17+):**
В современных ядрах это можно сделать без использования фаервола.

```bash
# 1. Создание таблицы для ISP1
sudo ip route add default via 192.168.1.1 dev eth0 table isp1_table

# 2. Правило для TCP/443 (HTTPS)
sudo ip rule add ipproto tcp dport 443 table isp1_table priority 500

# 3. Правило для IPv6 (если применимо)
sudo ip -6 rule add ipproto tcp dport 443 table isp1_table priority 500
```

**Валидация:**
```bash
# Проверка выбора маршрута для HTTPS-трафика
ip route get 8.8.8.8 ipproto tcp dport 443
# → 8.8.8.8 via 192.168.1.1 dev eth0 table isp1_table src <IP_eth0>

# Проверка обычного трафика (должен идти через main)
ip route get 8.8.8.8
# → 8.8.8.8 via <default_gw_main> dev eth1 src <IP_eth1>

# Проверка правил
ip rule show | grep "500:"
# → 500:	from all ipproto tcp dport 443 lookup isp1_table
```

**Ограничения и edge cases:**
- **Ядро < 4.17:** Селекторы `ipproto`, `sport`, `dport` не поддерживаются. Используйте `nftables` для маркировки и `fwmark` в `ip rule`.
- **Множество портов:** Для нескольких портов используйте `nftables` или несколько правил `ip rule` с одинаковым приоритетом.
- **IPv6:** Не забудьте добавить отдельные правила через `ip -6 rule`.

**Очистка:**
```bash
# Удаление правил
sudo ip rule del ipproto tcp dport 443 table isp1_table priority 500
sudo ip -6 rule del ipproto tcp dport 443 table isp1_table priority 500

# Удаление таблицы
sudo ip route flush table isp1_table

# Проверка
ip rule show
ip route show table isp1_table
```

---

### Сценарий 2: Изоляция трафика пользователя (UID-routing)

**Задача:** Запустить процесс от имени конкретного системного пользователя (например, `vpn-user`) так, чтобы весь его трафик уходил строго в VPN-туннель.

**Реализация:**
```bash
# 1. Определение UID пользователя
id -u vpn-user
# → 1001

# 2. Настройка маршрута в таблице VPN
sudo ip route add default via 10.8.0.1 dev tun0 table vpn_user_table

# 3. Правило по диапазону UID
sudo ip rule add uidrange 1001-1001 table vpn_user_table priority 1000

# 4. Запрет выхода через основной канал (Kill Switch)
sudo ip route add prohibit default table vpn_user_table metric 100
```

**Валидация:**
```bash
# Проверка правила
ip rule show | grep "1000:"
# → 1000:	from all uidrange 1001-1001 lookup vpn_user_table

# Проверка маршрута в таблице
ip route show table vpn_user_table
# → default via 10.8.0.1 dev tun0
# → prohibit default

# Проверка из-под пользователя (создаем тестовое соединение)
sudo -u vpn-user curl -s ifconfig.me
# → Должен вернуть IP VPN-туннеля (10.8.0.x), а не внешний IP

# Проверка Kill Switch (отключите VPN-интерфейс)
sudo ip link set tun0 down
sudo -u vpn-user curl -s ifconfig.me
# → Должен вернуть ошибку (Network unreachable) из-за prohibit
```

**Ограничения и edge cases:**
- **Несколько UID:** Если у пользователя есть supplementary группы с другими UID, `uidrange` покрывает только основной UID. Для полной изоляции используйте `su`/`sudo` с сохранением окружения или `setpriv`.
- **Root-процессы:** Процессы, запущенные от root (UID 0), не попадают под правило `uidrange`. Используйте `fwmark` для маркировки процессов.
- **Systemd-сервисы:** Для сервисов используйте `DynamicUser=` или `User=` в unit-файле и соответствующий `uidrange`.

**Очистка:**
```bash
# Удаление правил
sudo ip rule del uidrange 1001-1001 table vpn_user_table priority 1000

# Удаление маршрутов
sudo ip route flush table vpn_user_table

# Проверка
ip rule show
sudo -u vpn-user curl -s ifconfig.me
# → Должен вернуться внешний IP основного канала
```

---

### Сценарий 3: Решение проблемы асимметричной маршрутизации (Reply-to / Source-Based Routing)

**Проблема:** Сервер имеет два интерфейса (`eth0` — 1.1.1.2, `eth1` — 2.2.2.2). Пакет приходит на `eth1`, но сервер пытается ответить через шлюз по умолчанию в таблице `main` (который указывает на `eth0`). Удаленный хост отбрасывает такой пакет.

**Решение (Source-Based Routing):** Принудительно отвечать через тот интерфейс, которому принадлежит IP-адрес источника ответа.

```bash
# 1. Создание специфичных таблиц для каждого интерфейса
echo "101 table_eth0" | sudo tee -a /etc/iproute2/rt_tables
echo "102 table_eth1" | sudo tee -a /etc/iproute2/rt_tables

# 2. Настройка маршрутов
ip route add default via 1.1.1.1 dev eth0 table table_eth0
ip route add default via 2.2.2.1 dev eth1 table table_eth1

# 3. Привязка ответов к интерфейсам по Source IP
ip rule add from 1.1.1.2 table table_eth0
ip rule add from 2.2.2.2 table table_eth1
```

**Валидация:**
```bash
# Проверка правил
ip rule show
# → 0:	from all lookup local
# → 100:	from 1.1.1.2 lookup table_eth0
# → 200:	from 2.2.2.2 lookup table_eth1
# → 32766:	from all lookup main

# Проверка маршрута для IP, привязанного к eth1
ip route get 8.8.8.8 from 2.2.2.2
# → 8.8.8.8 via 2.2.2.1 dev eth1 table table_eth1 src 2.2.2.2

# Проверка с указанием входящего интерфейса (эмуляция входящего пакета)
ip route get 8.8.8.8 from 2.2.2.2 iif eth1
# → 8.8.8.8 via 2.2.2.1 dev eth1 table table_eth1 src 2.2.2.2

# Проверка связности с удаленного хоста (с обеих сторон)
tcpdump -i eth0 -n host <remote_ip> &
tcpdump -i eth1 -n host <remote_ip> &
ping -c 3 <remote_ip> -I 2.2.2.2
```

**Ограничения и edge cases:**
- **Несколько IP на интерфейсе:** Если на `eth1` несколько IP, добавьте правило для каждого: `ip rule add from <IP2> table table_eth1`.
- **Ответы на локальные адреса:** Локальные адреса (127.0.0.0/8) не попадают под эти правила — обрабатываются таблицей `local`.
- **rp_filter:** При асимметричной маршрутизации может сработать `rp_filter=1` (Strict). Установите `rp_filter=2` (Loose) на проблемных интерфейсах.
- **ICMP Redirect:** При использовании PBR ICMP Redirect не генерируется (ядро не знает о "правильном" шлюзе для источника).

**Очистка:**
```bash
# Удаление правил
sudo ip rule del from 1.1.1.2 table table_eth0
sudo ip rule del from 2.2.2.2 table table_eth1

# Удаление таблиц
sudo ip route flush table table_eth0
sudo ip route flush table table_eth1

# Удаление записей из rt_tables (опционально)
sudo sed -i '/table_eth0/d; /table_eth1/d' /etc/iproute2/rt_tables
```

---

### Сценарий 4: Сохранение меток соединений (CONNMARK)

**Задача:** Для входящих соединений через несколько провайдеров гарантировать симметричность трафика на протяжении всей сессии.

**Реализация через nftables:**
```bash
# 1. Маркировка входящих пакетов и сохранение метки в соединение (ct mark)
nft add rule inet filter prerouting iifname "eth1" ct mark set 0x1
nft add rule inet filter prerouting iifname "eth2" ct mark set 0x2

# 2. Восстановление метки из соединения для исходящих пакетов
nft add rule inet filter output ct mark 0x1 meta mark set 0x1
nft add rule inet filter output ct mark 0x2 meta mark set 0x2

# 3. Применение правил PBR на основе восстановленных меток
ip rule add fwmark 0x1 table table_eth1
ip rule add fwmark 0x2 table table_eth2
```

**Валидация:**
```bash
# Проверка правил
ip rule show | grep "fwmark"
# → 1000:	from all fwmark 0x1 lookup table_eth1
# → 1001:	from all fwmark 0x2 lookup table_eth2

# Мониторинг событий nftables
nft monitor
# → При установке соединения будет видно событие ct mark

# Проверка конкретного потока
ip route get 8.8.8.8 mark 0x1
# → 8.8.8.8 via <gateway_eth1> dev eth1 table table_eth1 src <IP_eth1>

# Проверка счетчиков
nft list ruleset | grep counter
# → counter packets 42 bytes 3014
```

**Ограничения и edge cases:**
- **Соединения без SYN:** Для ужеestablished соединений ct mark может не установиться. Убедитесь, что правила срабатывают на `prerouting`.
- **Таймаут conntrack:** По умолчанию conntrack хранит соединения 5 дней. Для коротких соединений это обычно не критично, но для долгих SSH-сессий может привести к накоплению записей. Настройте `nf_conntrack_tcp_timeout_established` при необходимости.
- **Производительность:** При >100k активных соединений мониторинг `nf_conntrack_count` и `nf_conntrack_max` обязателен.
- **Виртуальные машины:** Если трафик проходит через bridge, убедитесь, что правила применяются на физическом интерфейсе (`prerouting`), а не на `vnetX`.

**Очистка:**
```bash
# Удаление правил nftables
nft delete rule inet filter prerouting iifname "eth1" ct mark set 0x1
nft delete rule inet filter prerouting iifname "eth2" ct mark set 0x2
nft delete rule inet filter output ct mark 0x1 meta mark set 0x1
nft delete rule inet filter output ct mark 0x2 meta mark set 0x2

# Удаление правил ip rule
sudo ip rule del fwmark 0x1 table table_eth1
sudo ip rule del fwmark 0x2 table table_eth2

# Очистка счетчиков conntrack (если нужно сбросить статистику)
sudo conntrack -F
```

---

### Сценарий 5: Балансировка трафика (ECMP) с PBR

**Задача:** Использовать два интернет-канала одновременно для исходящего трафика, сохраняя "липкость" (stickiness) сессий и исключая критический трафик из балансировки.

**Реализация:**
```bash
# 1. Настройка ECMP в таблице main
sudo ip route replace default \
    nexthop via 192.168.1.1 dev eth0 weight 1 \
    nexthop via 192.168.2.1 dev eth1 weight 1

# 2. Использование PBR для исключения критического трафика (например, SSH) из балансировки
sudo ip rule add ipproto tcp dport 22 table direct_isp1 priority 100
```

**Валидация:**
```bash
# Проверка ECMP
ip route show
# → default proto static
# → nexthop via 192.168.1.1 dev eth0 weight 1
# → nexthop via 192.168.2.1 dev eth1 weight 1

# Детали FIB (multipath hash)
ip -d route get 8.8.8.8
# → Покажет выбранный nexthop и хеш

# Проверка, что SSH идет через прямой путь
ip route get 8.8.8.8 ipproto tcp dport 22
# → Должен показать маршрут из таблицы direct_isp1

# Проверка балансировки обычного трафика
for i in $(seq 1 10); do ip route get 8.8.8.8 | grep "nexthop"; done
# → Должны появляться оба nexthop (в разном порядке)
```

**Ограничения и edge cases:**
- **Out-of-Order пакеты:** ECMP может вызывать переупорядочивание пакетов в TCP-соединениях. Используйте `sysctl net.ipv4.fib_multipath_hash_policy=1` для фиксации хеша по 5-tuple.
- **Неравномерное распределение:** Если веса разные (например, 1:3), распределение будет пропорциональным, но не гарантированно точным.
- **Nexthop unreachable:** Если один из uplinks падает, ECMP автоматически перестает использовать его. Проверьте `ip route get` после отключения интерфейса.
- **Совместимость с VRF:** ECMP внутри VRF работает аналогично, но используйте `ip route show vrf <name>`.

**Очистка:**
```bash
# Удаление PBR-правила
sudo ip rule del ipproto tcp dport 22 table direct_isp1 priority 100

# Удаление ECMP (замена на одиночный маршрут)
sudo ip route replace default via 192.168.1.1 dev eth0

# Или полная очистка ECMP
sudo ip route flush table main
```

---

### Сценарий 6: Локально генерируемый трафик (iif lo)

**Задача:** Маршрутизировать трафик, созданный локальными службами самого сервера, по особым правилам.

**Особенность:** Для локального трафика в `ip rule` используется селектор `iif lo`.

```bash
# Направить трафик локального прокси-сервера (порт 8080) в специальную таблицу
sudo ip rule add iif lo ipproto tcp sport 8080 table proxy_table priority 200
```

**Валидация:**
```bash
# Проверка правила
ip rule show | grep "200:"
# → 200:	from all iif lo ipproto tcp sport 8080 lookup proxy_table

# Проверка маршрута для локально генерируемого трафика
ip route get 8.8.8.8 from 127.0.0.1 iif lo sport 8080
# → 8.8.8.8 via <gateway_proxy> dev <iface> table proxy_table src 127.0.0.1

# Тест: запуск локального соединения через прокси-порт
curl -x http://127.0.0.1:8080 https://example.com -I
# → Должен использовать маршрут из proxy_table
```

**Ограничения и edge cases:**
- **Только для локального трафика:** Селектор `iif lo` работает только для пакетов, созданных самим хостом. Входящий трафик с внешних источников не попадает под это правило.
- **Порт источника vs порт назначения:** `sport` — это порт источника (откуда исходит пакет), `dport` — порт назначения (куда идет пакет). При тестировании убедитесь, что используете правильный селектор.
- **Несколько локальных служб:** Если нужно разделить трафик нескольких локальных служб, добавьте отдельное правило для каждой комбинации `sport`/`ipproto`.

**Очистка:**
```bash
# Удаление правила
sudo ip rule del iif lo ipproto tcp sport 8080 table proxy_table priority 200

# Очистка таблицы
sudo ip route flush table proxy_table
```

---

### Сценарий 7: Dual-ISP с резервированием (failover)

**Задача:** Обеспечить автоматическое переключение на резервный провайдер при отказе основного, с возможностью ручного управления.

**Реализация:**
```bash
# 1. Создание таблиц для каждого ISP
echo "100 isp1_table" | sudo tee -a /etc/iproute2/rt_tables
echo "200 isp2_table" | sudo tee -a /etc/iproute2/rt_tables

# 2. Основной маршрут через ISP1
sudo ip route add default via 192.168.1.1 dev eth0 table isp1_table

# 3. Резервный маршрут через ISP2
sudo ip route add default via 192.168.2.1 dev eth1 table isp2_table

# 4. Правило: весь трафик по умолчанию идет через ISP1
sudo ip rule add from all table isp1_table priority 100

# 5. Резервное правило: если ISP1 недоступен, используем ISP2
sudo ip rule add from all table isp2_table priority 200

# 6. Проверка доступности ISP1 (скрипт)
cat <<'EOF' | sudo tee /usr/local/bin/check_isp1.sh
#!/bin/bash
ISP_GW="192.168.1.1"
if ping -c 2 -W 2 "$ISP_GW" >/dev/null 2>&1; then
    # ISP1 доступен — поднимаем основной маршрут
    ip route add default via "$ISP_GW" dev eth0 table isp1_table 2>/dev/null
else
    # ISP1 недоступен — поднимаем резервный маршрут
    ip route add default via 192.168.2.1 dev eth1 table isp2_table priority 200 2>/dev/null
fi
EOF
sudo chmod +x /usr/local/bin/check_isp1.sh

# 7. Добавление в cron для периодической проверки
echo "* * * * * root /usr/local/bin/check_isp1.sh" | sudo tee /etc/cron.d/pbr-failover
```

**Валидация:**
```bash
# Проверка правил
ip rule show
# → 100:	from all lookup isp1_table
# → 200:	from all lookup isp2_table
# → 32766:	from all lookup main

# Проверка маршрута по умолчанию
ip route get 8.8.8.8
# → Должен показывать шлюз 192.168.1.1 (ISP1)

# Имитация отказа ISP1
sudo ip route del default via 192.168.1.1 dev eth0 table isp1_table
ip route get 8.8.8.8
# → Должен показать шлюз 192.168.2.1 (ISP2) из таблицы isp2_table

# Возврат ISP1
sudo ip route add default via 192.168.1.1 dev eth0 table isp1_table
ip route get 8.8.8.8
# → Снова шлюз 192.168.1.1
```

**Ограничения и edge cases:**
- **DNS:** При переключении ISP убедитесь, что DNS-серверы доступны через текущий провайдер. Используйте внутренние DNS (например, 8.8.8.8 через VPN) или настройте split-horizon DNS.
- **Маркировка соединений:** Для длинных соединений (SSH, VPN) переключение ISP приведет к разрыву. Используйте CONNMARK (Сценарий 4) для сохранения симметрии.
- **Одновременный доступ:** Оба ISP должны иметь доступ к целевым ресурсам. Если один из провайдеров блокирует某些 трафик, учитывайте это в правилах.
- **Мониторинг:** Для продакшена используйте `systemd` или `monit` вместо cron. Пример:
    ```ini
    # /etc/systemd/system/isp-monitor.service
    [Unit]
    Description=ISP Failover Monitor

    [Service]
    Type=oneshot
    ExecStart=/usr/local/bin/check_isp1.sh
    ```

**Очистка:**
```bash
# Удаление правил
sudo ip rule del from all table isp1_table priority 100
sudo ip rule del from all table isp2_table priority 200

# Удаление таблиц
sudo ip route flush table isp1_table
sudo ip route flush table isp2_table

# Удаление скрипта и cron
sudo rm /usr/local/bin/check_isp1.sh
sudo rm /etc/cron.d/pbr-failover
```

---

### Сценарий 8: Маршрутизация по DSCP/TOS

**Задача:** Направлять приоритизированный трафик (например, VoIP с DSCP EF=46) через отдельный канал с гарантированной полосой.

**Реализация через nftables + ip rule:**
```bash
# 1. Маркировка трафика по DSCP (если не установлена источником)
# Примечание: если трафик уже помечен источником (IP-телефон), этот шаг можно пропустить
nft add rule inet filter mangle prerouting ip dscp 46 meta mark set 0x1

# 2. Создание таблицы для приоритетного трафика
echo "300 voice_table" | sudo tee -a /etc/iproute2/rt_tables
sudo ip route add default via 192.168.10.1 dev eth1 table voice_table

# 3. Правило PBR для помеченного трафика
sudo ip rule add fwmark 0x1 table voice_table priority 50
```

**Валидация:**
```bash
# Проверка правила
ip rule show | grep "50:"
# → 50:	from all fwmark 0x1 lookup voice_table

# Проверка маршрута
ip route get 8.8.8.8 mark 0x1
# → 8.8.8.8 via 192.168.10.1 dev eth1 table voice_table src <IP_eth1>

# Проверка DSCP на исходящем трафике
tcpdump -i eth1 -n -v ip dscp 46
# → Должен видеть пакеты с DSCP=46

# Проверка счетчика nftables
nft list ruleset | grep counter
# → counter packets 15 bytes 1020
```

**Ограничения и edge cases:**
- **DSCP на хосте:** Поле DSCP в IP-заголовке может быть установлено приложением (RTP, SIP) или маркировано `tc`/`nftables`. Убедитесь, что источники трафика правильно маркируют пакеты.
- **Прозрачность на пути:** Провайдеры часто сбрасывают DSCP на границе своей сети. Для E2E QoS используйте MPLS или VPN с сохранением DSCP.
- **Взаимодействие с tc:** Если на интерфейсе уже настроены `tc`-фильтры по DSCP, убедитесь, что они не конфликтуют с `nftables`-маркировкой.
- **IPv6:** Для IPv6 используется поле Traffic Class (аналог DSCP). Используйте `nft add rule inet filter mangle prerouting ip6 dscp 46 ...`.

**Очистка:**
```bash
# Удаление правил
sudo ip rule del fwmark 0x1 table voice_table priority 50

# Удаление маршрутов
sudo ip route flush table voice_table

# Удаление правил nftables
nft delete rule inet filter mangle prerouting ip dscp 46 meta mark set 0x1

# Удаление из rt_tables
sudo sed -i '/voice_table/d' /etc/iproute2/rt_tables
```

---

### Сценарий 9: Изоляция management/SSH-трафика

**Задача:** Обеспечить доступ к management-интерфейсу через выделенный uplink, не зависящий от состояния основного канала.

**Реализация:**
```bash
# 1. Создание таблицы для management-трафика
echo "400 mgmt_table" | sudo tee -a /etc/iproute2/rt_tables
sudo ip route add default via 192.168.100.1 dev mgmt0 table mgmt_table

# 2. Правило для SSH-трафика (TCP/22) с любого IP
sudo ip rule add ipproto tcp dport 22 table mgmt_table priority 10

# 3. Правило для ICMP (ping) с management-подсети
sudo ip rule add from 192.168.100.0/24 table mgmt_table priority 20

# 4. (Опционально) Ограничение по входящему интерфейсу
sudo ip rule add iif eth0 ipproto tcp dport 22 table mgmt_table priority 30
```

**Валидация:**
```bash
# Проверка правил
ip rule show | grep -E "10:|20:|30:"
# → 10:	from all ipproto tcp dport 22 lookup mgmt_table
# → 20:	from 192.168.100.0/24 lookup mgmt_table
# → 30:	from all iif eth0 ipproto tcp dport 22 lookup mgmt_table

# Проверка маршрута для SSH
ip route get 192.168.100.50 ipproto tcp dport 22
# → Должен показывать шлюз 192.168.100.1 через mgmt0

# Проверка связности SSH
ssh -o ConnectTimeout=5 admin@server "echo 'SSH OK'"

# Проверка, что обычный трафик НЕ идет через mgmt
ip route get 8.8.8.8
# → Должен показывать основной шлюз (не 192.168.100.1)
```

**Ограничения и edge cases:**
- **Порт 22:** Если SSH слушает не на стандартном порту, замените `dport 22` на актуальный номер.
- **Management VLAN:** Если management-доступ идет через VLAN, укажите VLAN-интерфейс в `dev` (например, `dev eth0.100`).
- **Failover:** Для критичных систем добавьте резервное правило с более низким приоритетом (большим номером) через второй management-интерфейс.
- **Локальный доступ:** Убедитесь, что `mgmt0` имеет IP и поднят (`ip link show mgmt0`). Локальный SSH (с самого сервера) требует дополнительного правила `iif lo` (см. Сценарий 6).

**Очистка:**
```bash
# Удаление правил
sudo ip rule del ipproto tcp dport 22 table mgmt_table priority 10
sudo ip rule del from 192.168.100.0/24 table mgmt_table priority 20
sudo ip rule del iif eth0 ipproto tcp dport 22 table mgmt_table priority 30

# Удаление таблицы
sudo ip route flush table mgmt_table

# Удаление из rt_tables
sudo sed -i '/mgmt_table/d' /etc/iproute2/rt_tables
```

---

## Диагностика и устранение неисправностей

### Типичные проблемы

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Правило добавлено, но не работает** | Неверный селектор или приоритет | `ip rule show` — проверка наличия и порядка правил | Убедитесь, что атрибуты пакета совпадают с селектором; используйте `ip route get` с теми же параметрами |
| **Трафик идет не в ту таблицу** | Конфликт приоритетов | `ip rule show` — проверка порядка применения | Перенесите правило выше (меньший номер приоритета) или уточните селектор |
| **Трафик дропается при входе** | Strict RPF (`rp_filter=1`) | `sysctl net.ipv4.conf.<iface>.rp_filter` | Установите `rp_filter=2` (Loose) на проблемном интерфейсе |
| **Метка fwmark не работает** | Маркировка в POSTROUTING | `nft monitor` — проверка этапа срабатывания | Перенесите маркировку в `PREROUTING` или `MANGLE/OUTPUT` |
| **Таблица пуста** | Маршрут не добавлен в таблицу | `ip route show table <ID>` | Добавьте маршрут: `ip route add default via <gw> dev <iface> table <ID>` |
| **"RTNETLINK answers: Invalid argument"** | Неверный синтаксис или неподдерживаемый селектор | `uname -r` — проверка версии ядра | Для ядер < 4.17 используйте `fwmark` вместо `ipproto`/`sport`/`dport` |
| **"RTNETLINK answers: File exists"** | Правило с таким же приоритетом уже существует | `ip rule show | grep <priority>` | Удалите старое правило или используйте другой приоритет |
| **Не работает IPv6 PBR** | Отсутствует `CONFIG_IPV6_MULTIPLE_TABLES` | `grep CONFIG_IPV6_MULTIPLE_TABLES /boot/config-$(uname -r)` | Пересоберите ядро с поддержкой или используйте `ip -6 rule` |
| **Перестает работать после перезагрузки** | Правила не сохранены | `ip rule show` после перезагрузки | Настройте персистентность (см. **[Администрирование PBR](./administration.md)**) |

### Диагностические команды

```bash
# Просмотр всех правил с таблицами
ip rule show table all

# Детальный просмотр (suppress_prefixlength, VRF)
ip -d rule show

# Эмуляция выбора маршрута (без реальной отправки)
ip route get <dst> from <src> iif <iface> mark <fwmark>

# Проверка конкретной таблицы
ip route show table <ID>

# Мониторинг событий nftables
nft monitor

# Логирование маркировки
nft add rule inet filter output meta mark 0x1 log prefix "PBR-DEBUG: "

# Проверка sysctl
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.<iface>.rp_filter
```

---

## Лучшие практики и очистка

### Рекомендации

1.  **Всегда указывайте `priority`:** Без него правила добавляются с уменьшающимся приоритетом относительно последнего добавленного, что может нарушить логику.
2.  **Используйте осмысленные имена таблиц:** Записывайте их в `/etc/iproute2/rt_tables` и используйте в командах вместо числовых ID.
3.  **Группируйте правила по диапазонам приоритетов:**
    | Диапазон | Назначение |
    | :--- | :--- |
    | **1–99** | Критичные системные правила (VPN-шлюзы, маршруты по умолчанию для специфических подсетей). |
    | **100–999** | Основные PBR-правила (разделение трафика по портам, протоколам, пользователям). |
    | **1000–32765** | Правила общего назначения, временные правила, отладка. |
4.  **Валидируйте после каждого изменения:** Используйте `ip route get` с теми же параметрами, что и в правиле.
5.  **Не используйте `flush` в продакшене без бэкапа:** Сохраняйте правила перед очисткой: `ip rule save > /tmp/backup.rules`.
6.  **Мониторьте conntrack:** При использовании CONNMARK отслеживайте `nf_conntrack_count` и `nf_conntrack_max`.
7.  **Избегайте `rp_filter=1` (Strict) при PBR:** Используйте `rp_filter=2` (Loose) или отключите на проблемных интерфейсах.

### Очистка среды

```bash
# 1. Сохранение текущих правил (перед очисткой)
ip rule save > /tmp/ip_rules_backup_$(date +%F_%H%M).rules

# 2. Удаление конкретного правила
sudo ip rule del priority <N>

# 3. Очистка таблиц
sudo ip route flush table <ID>

# 4. Удаление правил nftables
nft delete rule <table> <chain> <handle>

# 5. Проверка после очистки
ip rule show
# → Должны остаться только: local (0), main (32766), default (32767)
ip route get 8.8.8.8
# → Должен показывать маршрут через основной интерфейс
```

### Персистентность

Команды `ip rule` являются эфемерными и не сохраняются после перезагрузки. Настройте персистентность через:

- **systemd-networkd:** секция `[RoutingPolicyRule]` в `.network` файлах
- **Netplan:** секция `routing-policy:` в YAML-файлах
- **NetworkManager:** `nmcli connection modify <name> +ipv4.routing-rules "from ... table ..."`
- **Скрипт systemd:** сервис, выполняющий `ip rule restore` при старте

Подробнее см. в **[Администрирование PBR](./administration.md)**.

---

### Сценарий 10: Blackhole routing для DDoS-защиты через PBR

**Задача:** Блокировать трафик от атакующих подсетей на уровне маршрутизации, не нагружая фаервол. При DDoS-атаке на конкретный ISP — направлять атакующий трафик в blackhole через PBR-таблицу.

**Реализация:**

```bash
# 1. Таблица для blackhole-трафика
echo "666 blackhole_table" | sudo tee -a /etc/iproute2/rt_tables

# 2. Blackhole-маршрут по умолчанию в таблице
sudo ip route add blackhole default table blackhole_table

# 3. PBR-правило: атакующие подсети → blackhole
sudo ip rule add from 203.0.113.0/24 table blackhole_table priority 50
sudo ip rule add from 198.51.100.0/24 table blackhole_table priority 51

# 4. (Опционально) Blackhole для конкретного ISP при атаке
# Если атака идёт через ISP2 (eth1), блокируем весь вход через ISP2
sudo ip rule add iif eth1 table blackhole_table priority 10
```

**Валидация:**

```bash
# Проверка правил
ip rule show | grep "50:\|51:\|10:"
# → 10:    from all iif eth1 lookup blackhole_table
# → 50:    from 203.0.113.0/24 lookup blackhole_table
# → 51:    from 198.51.100.0/24 lookup blackhole_table

# Проверка маршрута
ip route show table blackhole_table
# → default blackhole

# Проверка: пакет от атакующего дропается молча
ip route get 8.8.8.8 from 203.0.113.50
# → RTN_BLACKHOLE via ... (пакет отброшен без ICMP)
```

**Ограничения и edge cases:**

- **Чёрный список vs white-list:** Blackhole блокирует ВСЁ от указанного источника. Для избирательной блокировки используйте nftables.
- **BGP RTBH:** В ISP-средах blackhole маршрутизируется через BGP RTBH (Remote Triggered Black Hole) с использованием blackhole community (`666`). См. [BGP](../../../Networking/Protocols/bgp.md).
- **Автоматизация:** Для автоматического добавления атакующих IP используйте скрипты с Fail2Ban или кастомные агенты.
- **Откат:** Удаление blackhole-правила восстанавливает трафик:

```bash
sudo ip rule del from 203.0.113.0/24 table blackhole_table priority 50
```

**Очистка:**

```bash
sudo ip rule del from 203.0.113.0/24 table blackhole_table priority 50
sudo ip rule del from 198.51.100.0/24 table blackhole_table priority 51
sudo ip rule del iif eth1 table blackhole_table priority 10
sudo ip route flush table blackhole_table
sudo sed -i '/blackhole_table/d' /etc/iproute2/rt_tables
```

---

### Сценарий 11: Взаимодействие PBR с NAT (SNAT/DNAT)

**Задача:** Настроить PBR на NAT-шлюзе с двумя ISP, где внутренние хосты (10.0.0.0/24) выходят наружу через разные провайдеры в зависимости от назначения.

**Проблема:** SNAT/MASQUERADE меняет source IP пакета. Если SNAT применяется до PBR, правило `from <source>` не сработает, потому что адрес источника уже изменён.

**Правильный порядок:**

```
1. PREROUTING → PBR (ip rule проверяет ОРИГИНАЛЬНЫЙ source)
2. ROUTING → выбор таблицы
3. POSTROUTING → SNAT/MASQUERADE (source заменяется на IP интерфейса)
```

**Реализация:**

```bash
# 1. Таблицы
echo "100 isp1_table" | sudo tee -a /etc/iproute2/rt_tables
echo "200 isp2_table" | sudo tee -a /etc/iproute2/rt_tables

# 2. Маршруты
ip route add default via 192.168.1.1 dev eth1 table isp1_table
ip route add default via 192.168.2.1 dev eth2 table isp2_table

# 3. PBR-правила (по ВНУТРЕННИМ адресам)
ip rule add from 10.0.0.0/24 table isp1_table priority 100

# 4. SNAT для каждого ISP
nft add rule ip nat postrouting oifname "eth1" ip saddr 10.0.0.0/24 masquerade
nft add rule ip nat postrouting oifname "eth2" ip saddr 10.0.0.0/24 masquerade

# 5. (Опционально) DNAT для входящих через ISP1
nft add rule ip nat prerouting iifname "eth1" tcp dport 80 dnat to 10.0.0.10:80
```

**Валидация:**

```bash
# Проверка: внутренний хост выходит через ISP1
ip route get 8.8.8.8 from 10.0.0.5
# → 8.8.8.8 via 192.168.1.1 dev eth1 table isp1_table

# Проверка NAT
conntrack -L -s 10.0.0.5 | head -3
# → tcp 6 120 SYN_SENT src=10.0.0.5 dst=8.8.8.8 sport=43210 dport=443
#     src=192.168.1.100 dst=8.8.8.8 sport=33456 dport=443 [ASSURED]

# Проверка: внешний IP = IP eth1 (ISP1)
sudo -u nobody curl -s ifconfig.me
# → 192.168.1.100
```

**Ограничения и edge cases:**

- **SNAT до PBR:** Если SNAT применяется в `PREROUTING` (до PBR), правило `from <source>` не найдёт внутренний IP. Убедитесь, что SNAT в `POSTROUTING`.
- **DNAT и PBR:** DNAT в `PREROUTING` меняет адрес назначения до PBR. PBR-правило `to <internal_IP>` может не сработать, если DNAT ещё не применён.
- **Conntrack:** SNAT создаёт conntrack-запись. Ответный пакет проходит через обратный NAT автоматически.
- **Multiple internal networks:** Если за NAT несколько подсетей, добавьте PBR-правило для каждой:

```bash
ip rule add from 10.0.0.0/24 table isp1_table priority 100
ip rule add from 10.0.1.0/24 table isp2_table priority 101
```

**Очистка:**

```bash
sudo ip rule del from 10.0.0.0/24 table isp1_table priority 100
sudo ip route flush table isp1_table
sudo ip route flush table isp2_table
nft delete rule ip nat postrouting handle <N>
nft delete rule ip nat postrouting handle <M>
```

---

## Дополнительная информация

### Тонкие моменты и ограничения

1.  **Порядок правил:** Всегда указывайте `priority`. Без него правила добавляются с уменьшающимся приоритетом относительно последнего добавленного, что может нарушить логику.
2.  **Подавление маршрутов:** Используйте `suppress_prefixlength 0` в правилах `ip rule`, если хотите, чтобы таблица игнорировалась при отсутствии в ней специфичного маршрута (кроме default).
3.  **Взаимодействие с фаерволом:** Помните, что `ip rule` срабатывает *после* цепочки `PREROUTING` и *после* цепочки `OUTPUT` в Netfilter.
4.  **ICMP Redirect:** При использовании PBR ICMP Redirect не генерируется, так как ядро не знает о "правильном" шлюзе для источника.
5.  **Локальный трафик:** Для трафика, генерируемого самим хостом, используйте селектор `iif lo`.

### Ссылки и связанные документы

- **[Policy-Based Routing (PBR) — Обзор](./index.md)** — архитектура и база данных правил RPDB.
- **[ip rule & PBR](../Tools/iproute2/ip_rule_pbr.md)** — подробный справочник синтаксиса, селекторов и приоритетов.
- **[Администрирование PBR](./administration.md)** — методы отладки (ip route get), мониторинг и способы сохранения конфигурации (Netplan, systemd-networkd).
- **[RPF и uRPF](../../../Networking/Protocols/rpf_urpf.md)** — глубокое погружение в механизмы фильтрации обратного пути.
- **[Маршрутизация в Linux](../../../Linux/SystemAdministration/routing.md)** — команды и диагностика (`ip route`, `ip rule`, `nexthop`).
- **[VRF в Linux](../../../Linux/Networking/vrf.md)** — альтернативный подход к изоляции таблиц.
- **[Conntrack и PBR](./conntrack_pbr.md)** — CONNMARK, conntrack zones, tuning для PBR.
- **[PBR и контейнеры](./pbr_and_containers.md)** — Docker, Kubernetes, rp_filter.
- **[Sysctl tuning для PBR](./sysctl_pbr.md)** — production-профили sysctl.
