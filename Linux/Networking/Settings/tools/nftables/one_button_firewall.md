# nftables — паттерн OneButtonFirewall (прозрачный мост)

## Определения

**OneButtonFirewall (OBF)** — паттерн конфигурации межсетевого экрана, минимизирующий ручную настройку за счет использования топологической изоляции и принципа «диода». Основная идея заключается в создании барьера, который прозрачен для исходящего трафика и блокирует любой неинициированный входящий трафик.

**IP-диод (IP Diode)** — архитектурный принцип сетевой безопасности, при котором трафик может безусловно проходить только в одном направлении (из защищаемого сегмента во внешний), а в обратном разрешаются только пакеты, принадлежащие уже установленным (ESTABLISHED) или связанным (RELATED) соединениям.

**Прозрачный мост (Transparent Bridge)** — режим работы сетевого устройства, при котором оно пересылает кадры на уровне L2 (Ethernet), не имея собственного IP-адреса в сегменте и не требуя изменения настроек маршрутизации (Default Gateway) на защищаемых узлах.

## Основные концепции

### Принцип работы OBF

Паттерн реализуется на уровне L2 в семействе `bridge`. Межсетевой экран физически помещается в разрыв сети между защищаемыми узлами и остальной инфраструктурой.

1.  **Зонирование интерфейсов:** порты моста делятся на `internal` (доверенные) и `external` (недоверенные).
2.  **Stateful-фильтрация на L2:** используется механизм отслеживания состояний (`conntrack`) для автоматического разрешения ответов из внешней сети на запросы из внутренней.
3.  **Обработка служебного трафика:**
    *   **ARP:** безусловное разрешение для работы резолвинга MAC-адресов.
    *   **DHCP:** разрешение для автоматического получения IP-адресов.
    *   **IPv6 NDP:** разрешение Multicast-сообщений (Neighbor Discovery) для работы IPv6.
4.  **Broadcast/Multicast:** ограниченное разрешение для обеспечения работы сетевого окружения (например, mDNS или LLMNR, если требуется).

### Почему L2, а не L3

Использование семейства `bridge` вместо `inet`/`ip` критично для паттерна OBF по нескольким причинам:

1.  **Прозрачность:** на L2 мост не требует изменения IP-адресов, шлюзов или DHCP-серверов на защищаемых узлах. Физически он является «умным разъемом» в кабеле.
2.  **Нет L3-адреса у моста:** отсутствие IP на интерфейсах моста исключает возможность прямого сканирования или атаки на сам файрвол.
3.  **Stateful на кадровом уровне:** в современных ядрах (5.3+) `conntrack` поддерживается нативно в семействе `bridge`, что позволяет применять `ct state established,related accept` к L2-трафику.
4.  **EtherType-фильтрация:** помимо IP, можно фильтровать нестандартные протоколы (AppleTalk, IPX) по полю `ether type`.

### Системные требования

Для корректной работы Stateful-фильтрации в режиме моста в современных дистрибутивах (ядра 5.x+) поддержка `conntrack` в семействе `bridge` является нативной. 

**Важное замечание (br_netfilter):**
Исторически для фильтрации трафика моста средствами `iptables` требовался модуль `br_netfilter`, который «пробрасывал» L2-пакеты в цепочки L3. В 2026 году при использовании нативного семейства `bridge` в `nftables` этот модуль **не рекомендуется** использовать без необходимости, так как он может вызвать побочные эффекты в маршрутизации и двойную обработку пакетов.

```bash
# Проверка поддержки conntrack в bridge
nft list hooks | grep bridge
```

## Предварительные требования

### Аппаратные требования

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| ** NIC** | 2 порта (1x external, 1x internal) | 3+ порта для сегментации внутренней сети |
| ** CPU** | 2 ядра (Intel/AMD) | 4+ ядра при нагрузке >1Gbps с stateful-фильтрацией |
| ** RAM** | 512 MB | 2 GB+ для больших таблиц conntrack |
| ** Порты** | Минимум 2 активных NIC | Поддержка VLAN-aware bridge (опционально) |

### Программные требования

| Компонент | Версия / Требование |
| :--- | :--- |
| **Ядро Linux** | 5.3+ (нативный `bridge` conntrack), 5.15+ рекомендуется |
| **nftables** | 1.0.0+ (поставлен в большинстве современных дистрибутивов) |
| **iproute2** | 5.x+ (команды `ip link`, `bridge`) |
| **Права** | root (sudo) |
| **Служба** | `nftables` (systemd) для персистентности |

### Проверка окружения

```bash
# Версия ядра
uname -r
# → 5.15.0-78-generic

# Наличие nftables
which nft && nft --version
# → nft v1.0.9

# Проверка загруженных модулей ядра
lsmod | grep -E 'bridge|nf_conntrack|nf_defrag_ipv4'
# → bridge                 327680  0
# → nf_conntrack          163840  1 bridge

# Статус службы nftables
systemctl status nftables
# → Active: inactive (dead) — ожидается для правил, загружаемых вручную
```

## Пошаговая установка

### Шаг 1: Подготовка интерфейсов

Все интерфейсы, участвующие в мосте, должны быть подняты и настроены без IP-адресов. Мост возьмет на себя пересылку кадров.

```bash
# Очистка IP-адресов с физических интерфейсов (если есть)
sudo ip addr flush dev enp2s0
sudo ip addr flush dev enp3s0
sudo ip addr flush dev enp1s0

# Поднятие интерфейсов
sudo ip link set enp1s0 up   # External
sudo ip link set enp2s0 up   # Internal 1
sudo ip link set enp3s0 up   # Internal 2
```

### Шаг 2: Создание моста

```bash
# Создание моста без STP (для мгновенного включения портов)
sudo ip link add name br0 type bridge
sudo ip link set br0 up

# Добавление портов в мост
sudo ip link set enp1s0 master br0  # External
sudo ip link set enp2s0 master br0  # Internal
sudo ip link set enp3s0 master br0  # Internal

# Проверка
ip link show master br0
# → 2: enp1s0: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
```

### Шаг 3: Применение правил nftables

```bash
sudo nft -f /etc/nftables-obf.conf
```

### Шаг 4: Включение персистентности

```bash
# Сохранение правил (если используется systemd-сервис nftables)
sudo nft list ruleset > /etc/nftables.conf
sudo systemctl enable --now nftables
```

### Шаг 5: Верификация

```bash
# Проверка, что мост пересылает трафик
sudo tcpdump -i br0 -e -n -c 10

# Проверка правил nftables
sudo nft list ruleset
```

## Практические сценарии

### 1. Эталонная конфигурация nftables (L2 Bridge)

Данный набор правил создает «невидимый» барьер. Предполагается, что интерфейс `external` смотрит во внешнюю сеть, а остальные порты моста — во внутреннюю.

```bash
#!/usr/sbin/nft -f

flush ruleset

table bridge firewall {
    # Сет для интерфейсов внутренней сети
    set internal_interfaces {
        type ifname
        elements = { "enp2s0", "enp3s0" }
    }

    chain fw_forward {
        type filter hook forward priority filter; policy drop;

        # 1. Разрешить ARP (Address Resolution Protocol)
        ether type arp accept

        # 2. Разрешить весь трафик из внутренней сети наружу (IP-диод)
        iifname @internal_interfaces accept

        # 3. Разрешить ответы на установленные соединения (Stateful)
        # Обрабатывает IPv4 и IPv6 атомарно
        ct state established,related accept

        # 4. Разрешить IPv6 Neighbor Discovery (NDP) и SLAAC
        # Необходимы для того, чтобы узлы видели шлюз и получали адреса
        ip6 nexthdr icmpv6 icmpv6 type { 
            nd-neighbor-solicit,  # Поиск соседа
            nd-neighbor-advert,   # Ответ соседа
            nd-router-solicit,    # Поиск роутера
            nd-router-advert,     # Объявление роутера
            mld-listener-query    # Групповая подписка (IPv6 Multicast)
        } accept

        # 5. Разрешить DHCP (IPv4)
        udp dport 67-68 accept

        # 6. Разрешить широковещательный трафик (Broadcast IPv4)
        # Для работы сетевого обнаружения (NetBIOS/LLMNR)
        pkttype broadcast ip daddr 255.255.255.255 accept
    }
}
```

### 2. Настройка сетевого моста (Netplan — Ubuntu/Debian)

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp1s0: { dhcp4: no } # External
    enp2s0: { dhcp4: no } # Internal 1
    enp3s0: { dhcp4: no } # Internal 2
  bridges:
    br0:
      interfaces: [enp1s0, enp2s0, enp3s0]
      parameters:
        stp: false # Отключить STP для мгновенного включения портов
      dhcp4: no
      accept-ra: no
```

### 3. Диагностика и отладка (nft monitor)

Поскольку мост прозрачен, стандартные методы диагностики (например, `ping` самого устройства) не работают.

```bash
# Включение трассировки для пакета с конкретным MAC-адресом
nft add rule bridge firewall fw_forward ether saddr 00:11:22:33:44:55 meta nftrace set 1

# Просмотр прохождения правил в реальном времени
sudo nft monitor trace
```

### 4. Безопасное атомарное обновление правил с откатом

При применении правил на production-оборудовании важно иметь механизм отката. Используйте комбинацию резервного копирования и `at`/`systemd-run`.

```bash
#!/bin/bash
set -euo pipefail

RULES_FILE="/etc/nftables-obf.conf"
BACKUP_FILE="/tmp/nftables-obf-backup-$(date +%Y%m%d-%H%M%S).nft"
ROLLBACK_DELAY=300  # 5 минут

# 1. Резервное копирование текущего состояния
nft list ruleset > "$BACKUP_FILE"

# 2. Проверка синтаксиса новых правил
sudo nft --check -f "$RULES_FILE"

# 3. Применение атомарно
sudo nft -f "$RULES_FILE"

# 4. Планирование автоматического отката
echo "sudo nft flush ruleset && sudo nft -f $BACKUP_FILE" | at now + "$ROLLBACK_DELAY" seconds

# 5. Инструкция для администратора
echo "Правила применены. Откат запланирован через $ROLLBACK_DELAY секунд."
echo "Если всё работает — отмените откат: atrm <job-id>"
```

**Валидация:**
```bash
# После применения проверьте целостность conntrack
sudo sysctl net.netfilter.nf_conntrack_count
# → 12 (количество активных соединений)

# Проверка счетчиков правил
sudo nft list chain bridge firewall fw_forward
# → ct state established,related accept # packets 1542 bytes 98720
```

### 5. Мониторинг счетчиков и алертинг

Для оперативного выявления аномалий используйте встроенные счетчики nftables и `nft monitor`.

```bash
# Просмотр счетчиков в реальном времени (каждые 2 сек)
watch -n 2 'sudo nft list chain bridge firewall fw_forward'

# Мониторинг новых соединений
sudo nft monitor
# → [meta nftrace set 1] bridge firewall fw_forward ether saddr ... accept

# Экспорт метрик в Prometheus (через node_exporter)
# Метрики conntrack уже доступны по умолчанию:
curl -s http://localhost:9100/metrics | grep conntrack
# → node_nf_conntrack_entries 128
# → node_nf_conntrack_max 262144
```

### 6. Ограничение broadcast/multicast трафика (Storm Control)

Без ограничений broadcast-шторм может насытить порты внутреннего сегмента. Используйте `tc` для policing на портах моста.

```bash
# Создание qdisc clsact на внутренних портах
sudo tc qdisc replace dev enp2s0 clsact
sudo tc qdisc replace dev enp3s0 clsact

# Ограничение broadcast до 10 Mbit/s
sudo tc filter add dev enp2s0 ingress protocol all flower \
  dst_mac ff:ff:ff:ff:ff:ff police rate 10mbit burst 100k drop

# Проверка
tc filter show dev enp2s0 ingress
# → filter ingress 8000: flower police rate 10Mbit burst 100Kb
```

## Валидация результатов

### Проверка работоспособности моста

```bash
# 1. Таблица MAC-адресов (FDB) должна пополняться
sudo bridge fdb show dev br0
# → 52:54:00:12:34:56 dev enp2s0 master br0

# 2. Статистика по портам
ip -s link show master br0
# → RX: bytes packets errors dropped ...
# → TX: bytes packets errors dropped ...

# 3. Проверка, что внешний сканирование не видит внутренние узлы
sudo nmap -sP 172.30.0.0/24
# → Внутренние узлы должны отвечать (трафик прошел через мост)

# 4. Проверка, что с внешней стороны нельзя инициировать соединение
sudo nmap -p 22,80,443 <внешний_IP_внутреннего_узла>
# → filtered (drop) — правил
```

### Проверка состояния conntrack

```bash
# Текущее количество записей
sudo sysctl net.netfilter.nf_conntrack_count
# → 12

# Максимальное значение
sudo sysctl net.netfilter.nf_conntrack_max
# → 262144

# Статистика по состояниям
sudo conntrack -L -o extended | awk '{print $4}' | sort | uniq -c
# → 12 ESTABLISHED
# → 3 TIME_WAIT
```

## Диагностика и устранение неполадок

| Проблема | Признак | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Нет связи между внутренними узлами** | `ping` таймаутит | `ip link show br0` — состояние UP? | Поднять интерфейсы: `sudo ip link set eth0 up` |
| **MAC не появляется в FDB** | `bridge fdb show` пуст | `tcpdump -i enp2s0 -e` — кадры доходят? | Проверить режим promiscuous, MTU, VLAN tag mismatch |
| **Трафик не фильтруется** | Внешний узел видит внутренние порты | `sudo nft list ruleset` — правила загружены? | Проверить hook `forward` и priority; убедиться что `policy drop` активна |
| **Conntrack не срабатывает** | Внешние ответы блокируются | `sudo conntrack -L` — есть запись для соединения? | Проверить `nf_conntrack` модуль загружен; для SSH добавьте правило на этапе загрузки |
| **IPv6 не работает** | Узлы не получают SLAAC-адреса | `sudo nft list chain bridge firewall fw_forward` — есть ICMPv6 правила? | Добавить `ip6 nexthdr icmpv6` accept для NDP-типов |
| **DHCP не работает** | Узлы не получают IP | `tcpdump -i br0 -n port 67 or port 68` — DHCP-пакеты проходят? | Убедиться что `udp dport 67-68 accept` присутствует |
| **Потеря доступа при применении правил** | SSH обрывается | Проверка через локальную консоль | Использовать атомарную загрузку с `nft -f` или `nftables-apply` |
| **Высокая нагрузка на CPU** | `top` показывает высокий софтвир interrupt | `watch -d 'cat /proc/softirqs'` — рост NET_RX? | Уменьшить количество правил; использовать `limit rate` для логирования |

## Краевые случаи и ограничения

1.  **Атомарность:** nftables применяет изменения атомарно. Ошибка в синтаксисе halfway не частично активирует правила.
2.  **IPv6:** Если семейство `inet` используется, правило `tcp dport 80 accept` создаст записи и для IPv6. Для IPv6-only используйте `ip6` семейство.
3.  **Логирование `full`:** Записывает полные дампы пакетов, что может создать нагрузку на диск. Используйте только для диагностики.
4.  **Rate limit:** В nftables `limit rate` работает для любых протоколов. Для тонкой настройки UDP используйте Fail2ban.
5.  **Per-interface правила:** `iif "eth1"` требует точного имени интерфейса (проверьте через `ip link`).
6.  **Conntrack:** nftables использует `nf_conntrack`. При высокой нагрузке увеличьте `net.netfilter.nf_conntrack_max`.
7.  **notrack и helpers:** Использование `notrack` отключает отслеживание соединения, что может сломать FTP ALG и другие helpers. Используйте осторожно.
8.  **Flowtables:** При использовании flowtables пакеты попадают в цепочки `ingress`/`egress` семейства `netdev` и обходят классические `filter`-цепочки. Убедитесь, что политики согласованы.
9.  **Hairpin mode:** по умолчанию мост не рефлексирует кадр обратно в порт-источник. Если внутренние узлы должны общаться друг с другом через мост (например, при избыточной топологии), включите hairpin: `bridge link set dev <iface> hairpin on`.
10. **MTU:** MTU моста автоматически падает до минимального среди портов. Если к мосту подключен интерфейс с MTU 1500, весь мост будет ограничен 1500 байт, даже если остальные порты поддерживают 9000.

## Best Practices

1.  **Минимизация поверхности атаки:** используйте `policy drop` по умолчанию, разрешайте только необходимые типы трафика.
2.  **Состояние Established в первой позиции:** размещайте `ct state established,related accept` сразу после проверки `invalid`, чтобы минимизировать нагрузку на CPU.
3.  **Ограничение логирования:** всегда используйте `limit rate` с выражением `log`, чтобы избежать переполнения журнала при DDoS.
4.  **Проверка синтаксиса перед загрузкой:** `nft --check -f /etc/nftables-obf.conf`.
5.  **Резервное копирование:** сохраняйте предыдущий ruleset перед каждым изменением.
6.  **Атомарность:** используйте `nft -f` вместо пошагового добавления правил через `nft add`.
7.  **Мониторинг:** настроите алерты на рост dropped-пакетов в цепочке `fw_forward`.
8.  **Документация:** комментируйте каждое правило в конфигурационном файле, особенно исключения.
9.  **Тестирование в lab:** перед внедрением в production протестируйте конфигурацию в изолированной среде с `tcpdump`.
10. **Персистентность:** используйте `systemd`-сервис `nftables` для автоматической загрузки правил при загрузке системы.

## Очистка окружения

```bash
# 1. Удаление правил nftables
sudo nft delete table bridge firewall

# 2. Удаление портов из моста
sudo ip link set enp1s0 nomaster
sudo ip link set enp2s0 nomaster
sudo ip link set enp3s0 nomaster

# 3. Удаление моста
sudo ip link set br0 down
sudo ip link delete br0 type bridge

# 4. Удаление tc-фильтров
sudo tc qdisc del dev enp2s0 clsact
sudo tc qdisc del dev enp3s0 clsact

# 5. Возврат IP-адресов (при необходимости)
sudo dhclient enp1s0
sudo dhclient enp2s0
sudo dhclient enp3s0
```

## Дополнительная информация

### Преимущества паттерна

*   **Нулевая конфигурация узлов:** не нужно менять настройки IP или шлюзов на серверах.
*   **Скрытность (Stealth):** устройство защиты не имеет собственного IP, его невозможно обнаружить сканерами портов или атаковать напрямую.
*   **Универсальность:** фильтрация любых типов трафика (IP, IPX, AppleTalk и др.) на основе EtherType.

### Ограничения и риски

*   **Отсутствие L3-изоляции:** все узлы внутри моста находятся в одном L2-домене. Паттерн не защищает от атак «узел-узел» (Lateral Movement) внутри доверенного сегмента.
*   **Сложность отладки:** при ошибках в конфигурации пакеты пропадают «бесследно» для сетевых утилит L3.
*   **Нагрузка на CPU:** Stateful-фильтрация на уровне моста требует больше ресурсов, чем простая L2-коммутация. Для сверхвысоких нагрузок (10Gbps+) рекомендуется рассмотреть альтернативы на базе **XDP (eXpress Data Path)**.

### См. также

- **[nftables — сегментирование сети](./network_segmentation.md):** создание нескольких изолированных мостов.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md):** база хуков семейства bridge.
- **[Моделирование угроз и схемы защиты](./threat_modeling.md):** проектирование правил для публичных сегментов.
- **[Linux Bridge — основные концепции](../../../Concepts/linux_bridge.md):** как работает программный коммутатор.
