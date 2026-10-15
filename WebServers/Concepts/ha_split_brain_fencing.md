# HA веб-серверов: Split-Brain, Fencing, Keepalived и VRRP

**Актуально для:** Keepalived 2.3.x / 2.4.x, Pacemaker 2.1.x, Corosync 3.1.x, Linux Kernel 5.15+ / 6.x

В отказоустойчивых кластерах веб-серверов и обратных прокси (Nginx, Angie, HAProxy, Envoy, Traefik, Apache) ключевой задачей является непрерывная доступность виртуального IP-адреса (VIP). Однако при нарушении связности между узлами возникает риск **Split-Brain** (расщепления кластера), приводящий к коллизиям IP, дребезгу MAC-адресов на коммутаторах и деградации клиентских сессий. Настоящий документ является единым источником правды (SSoT) по архитектуре защиты от Split-Brain, механизмам изоляции узлов (Fencing/STONITH) и надежной реализации высокой доступности на базе Keepalived и Pacemaker в корпоративной инфраструктуре.

---

## Определения

- **HA веб-серверов (High Availability Web Tier)** — архитектура пула веб-серверов и обратных прокси, исключающая единую точку отказа (SPOF) при приеме и маршрутизации входящего HTTP(S)/L4-трафика.
- **Split-Brain (Расщепление кластера)** — аварийное состояние распределенной системы, при котором из-за потери сетевой связности между серверами либо зависания процессов координации два или более узла одновременно объявляют себя активными (`MASTER`), пытаясь параллельно владеть одним и тем же виртуальным IP-адресом.
- **VIP (Virtual IP Address / Floating IP)** — плавающий IP-адрес, логически ассоциированный с веб-сервисом. В штатном режиме адрес привязан к активному мастер-узлу и мигрирует на резервный сервер при аварии.
- **VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол без установления соединения (RFC 3768 для v2, RFC 5798 для v3, протокол IP 112), обеспечивающий автоматическое назначение VIP активному узлу на основе периодической рассылки объявлений (`advertisements`).
- **Keepalived** — системный демон для Linux, реализующий протокол VRRP для управления отказоустойчивыми VIP, а также мониторинг состояния сервисов и L4-балансировку LVS. Детальная архитектура демона — в **[обзоре Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)**.
- **Fencing (Изоляция узла)** — детерминированный процесс принудительного отстранения или физического отключения сбойного/неотвечающего узла от кластера для предотвращения разделения ресурсов и коллизий данных.
- **STONITH (Shoot The Other Node In The Head)** — жесткий метод изоляции (Hard Fencing), при котором сбойный узел принудительно перезагружается или обесточивается через независимый канал управления (IPMI, iLO, iDRAC, BMC, сетевой PDU).
- **SBD (Storage-Based Death / Software Watchdog)** — механизм ограждения узла, использующий аппаратный сторожевой таймер Linux Watchdog (`/dev/watchdog` или драйвер `softdog`) и обмен метками через общий блочный накопитель или демоны отсечки.
- **Арбитр / Свидетель кворума (Arbitrator / Quorum Witness / QDevice)** — независимый третий узел, сетевой шлюз или легковесная служба, участвующая в голосовании для преодоления паритета голосов (Split-Brain) в двухнодовых кластерах.
- **MAC Flapping (Дребезг MAC-адреса)** — аномалия на L2-коммутаторах, при которой запись в CAM-таблице (MAC address table) непрерывно переключается между двумя физическими портами из-за получения пакетов с одинаковым MAC или конфликтным VIP от двух разных серверов.
- **Gratuitous ARP (GARP)** — широковещательный ARP-анонс, рассылаемый новым мастером для принудительного обновления ARP-кэша соседних хостов и CAM-таблиц L2-коммутаторов при смене владельца VIP. Подробности работы протокола — в **[документации по ARP](../../Networking/Protocols/arp.md)**.
- **BFD (Bidirectional Forwarding Detection)** — легковесный протокол (RFC 5880 / RFC 5881) для субсекундного (десятки миллисекунд) обнаружения обрыва каналов связи между узлами.

---

## Основные концепции и архитектура

### Анатомия Split-Brain в стеке веб-серверов

В кластерах обратных прокси и веб-серверов Split-Brain возникает по следующим инфраструктурным причинам:
1. **Обрыв канала синхронизации (Inter-node Heartbeat Link):** физическое повреждение кабеля, зависание порта промежуточного коммутатора или перестроение топологии Spanning Tree (STP), из-за которого прямая связь между Node1 и Node2 пропадает, хотя обе ноды продолжают иметь доступ в клиентскую сеть.
2. **Блокировка управляющего трафика:** ошибки в правилах межсетевых экранов (`iptables`, `nftables`), блокирующие протокол IP 112 (VRRP), либо сбои механизма IGMP Snooping на L2-коммутаторах, отсекающие мультикаст-группу `224.0.0.18`.
3. **Зависание управляющего процесса или перегрузка CPU:** высокая утилизация процессора (100% CPU starvation), исчерпание дескрипторов или задержки в планировщике ядра Linux, приводящие к тому, что Keepalived не успевает отправить VRRP advertisement вовремя. Резервный узел считает мастера мертвым и поднимает второй VIP.

```
                  ┌─────────────────────────────────────┐
                  │    Клиенты / Внешний L3-маршрутизатор│
                  └──────────────────┬──────────────────┘
                                     │
                        Виртуальный IP: 192.168.1.100
                                     │
           ┌─────────────────────────┴─────────────────────────┐
           │                                                   │
           ▼                                                   ▼
 ┌───────────────────┐                               ┌───────────────────┐
 │   Node 1 (MASTER) │                               │   Node 2 (MASTER) │
 │   192.168.1.101   │                               │   192.168.1.102   │
 │   VIP: назначен   │                               │   VIP: назначен   │
 │   [Nginx/Angie]   │                               │   [Nginx/Angie]   │
 └─────────┬─────────┘                               └─────────┬─────────┘
           │                                                   │
           │           X --- Обрыв Heartbeat (VRRP) --- X      │
           └───────────────────────────────────────────────────┘
```

#### Последствия для сетевого и прикладного уровней

| Уровень модели OSI | Проявление аномалии | Влияние на инфраструктуру и пользователей |
| :--- | :--- | :--- |
| **L2 (Канальный)** | **MAC Flapping на портах коммутатора** | Коммутатор получает кадры с одинаковым VIP от портов Eth1/1 и Eth1/2. Защитные механизмы (MAC flap damping / port-security) блокируют оба порта, вызывая полный отказ сегмента сети. |
| **L3 (Сетевой)** | **ARP-коллизии и асимметрия** | Часть клиентских шлюзов кэширует MAC-адрес Node1, часть — Node2. Пакеты одного и того же клиента направляются в разные узлы. |
| **L4 (Транспортный)** | **Сброс TCP-соединений (TCP RST)** | Клиент отправляет `TCP SYN` на Node1, устанавливает соединение. Следующий пакет `ACK` или `PSH-ACK` попадает на Node2, который не знает об этой сессии в таблице `conntrack` и отправляет клиенту `TCP RST`. |
| **L7 (Прикладной)** | **Срыв TLS и потеря сессий** | Срывается повторное использование сессий (TLS Session Resumption). Если веб-серверы используют локальный кэш (Nginx `proxy_cache`), клиенты получают неконсистентные ответы. При работе с разделяемым хранилищем сессий (NFS/GFS2) возможна параллельная несогласованная запись и порча файлов. |

---

### Фундаментальное ограничение VRRP vs кворумные системы

Спецификация VRRP (RFC 3768 / RFC 5798) создавалась для резервирования шлюзов по умолчанию в сетевых маршрутизаторах. **В стандартном VRRP отсутствует концепция кворума.**

1. Резервный узел (`BACKUP`) принимает решение об объявлении себя мастером исключительно на основе **отсутствия** входящих пакетов от текущего мастера.
2. Формула таймера перехода в `MASTER`:
   $$\text{Master\_Down\_Interval} = (3 \times \text{advert\_int}) + \text{skew\_time}$$
   где $\text{skew\_time} = \frac{256 - \text{priority}}{256}$ секунд.
3. При изоляции двух узлов оба обязаны стать `MASTER` согласно RFC.

Для превращения связки Keepalived + VRRP в промышленное отказоустойчивое решение применяются три обязательных архитектурных дополнения:
- **Двухканальный пульс (Dual Heartbeat Links):** основной интерфейс передачи трафика плюс выделенный физический линк синхронизации (cross-over или выделенный VLAN).
- **Взвешенный трекинг внешнего шлюза (Weighted Quorum Tracking):** проверка доступности вышестоящего L3-коммутатора/шлюза. Если узел потерял связь со шлюзом, его приоритет принудительно снижается, переводя его в подчиненное состояние.
- **Ограждение через STONITH (Node Fencing):** гарантированное аппаратное отключение питания соседа через Out-of-Band интерфейс при фиксации неконсистентности.

Для сценариев со строгими требованиями к разделяемым дискам и консенсусу используется стек **Pacemaker + Corosync**, где кворум обеспечивается математическим большинством голосов (`votequorum`) и внешним свидетелем `corosync-qdevice`.

---

### Таксономия Fencing (Уровни и механизмы изоляции)

```
                              Уровни Fencing
                                    │
         ┌──────────────────────────┴──────────────────────────┐
         ▼                                                     ▼
   Hard Fencing (Node Level)                             Soft Fencing (Resource/Net)
         │                                                     │
 ┌───────┴───────┐                                     ┌───────┴───────┐
 │ Аппаратное    │                                     │ Сетевая       │
 │ выключение    │                                     │ изоляция      │
 │ (IPMI, iLO,   │                                     │ (ACL, Port    │
 │  PDU, KVM)    │                                     │  Shutdown)    │
 └───────────────┘                                     └───────────────┘
         │                                                     │
 ┌───────┴───────┐                                     ┌───────┴───────┐
 │ Сторожевой    │                                     │ Принудительный│
 │ таймер        │                                     │ останов       │
 │ (Watchdog/SBD)│                                     │ сервиса       │
 └───────────────┘                                     └───────────────┘
```

| Уровень изоляции | Механизм | Используемые инструменты | Плюсы | Минусы |
| :--- | :--- | :--- | :--- | :--- |
| **Node Fencing (Hard)** | Отключение питания узла через аппаратный контроллер | `ipmitool` (IPMI/BMC), HPE iLO, Dell iDRAC, сетевой управляемый PDU (APC, Raritan), `virsh destroy` (KVM), Proxmox API | 100% гарантия невозможности продолжения работы узла и отправки пакетов | Требует отдельной физической сети Out-of-Band (IPMI) |
| **Watchdog / SBD** | Аппаратный таймер сбрасывает питание, если ОС не подтверждает жизнеспособность | Ядро Linux (`/dev/watchdog`), модуль `softdog` / `iTCO_wdt`, демон `sbd` | Не зависит от внешней сети управления; узел сам совершает суицид при зависании | Требует строгой калибровки таймеров во избежание ложных перезагрузок |
| **Network Fencing** | Блокировка сетевых портов сбойного узла на управляемом коммутаторе | SNMP `ifAdminStatus down`, REST API коммутаторов (Cisco/Arista), `iptables/nftables` аварийные правила | Изолирует узел от внешней сети без отключения сервера | Не спасает от внутренних дефектов, если узел продолжит писать в общее хранилище |
| **Application Fencing (Soft)** | Принудительная остановка процесса веб-сервера | `systemctl stop`, `kill -9`, cgroups freeze | Мгновенно освобождает сетевые порты (80, 443) | Если ОС или ядро зависли в D-state (uninterruptible sleep), мягкий останов не сработает |

---

### Сравнение архитектур: Keepalived vs Pacemaker/Corosync

| Критерий | Keepalived (VRRP-ориентированный) | Pacemaker + Corosync (Кворумно-ориентированный) |
| :--- | :--- | :--- |
| **Сложность развертывания** | Минимальная (один конфигурационный файл) | Средняя / Высокая (управление ресурсами, CIB, ограничения) |
| **Наличие встроенного кворума** | Нет (требуется имитация через скрипты трекинга шлюза) | Да (математический кворум `votequorum` + QDevice/QNet) |
| **Поддержка STONITH** | Через внешние пользовательские `notify`-скрипты | Нативная (встроенные агенты `fence_ipmilan`, `fence_pdu`, `fence_sbd`) |
| **Скорость переключения VIP** | 1–3 секунды (до 100 мс при интеграции с BFD) | 2–5 секунд (с учетом подтверждения изоляции узла) |
| **Поведение при Split-Brain** | Высокий риск без специальных мер защиты | Исключено: узел без кворума изолируется и не запускает ресурсы |
| **Рекомендуемая сфера** | Stateless обратные прокси (Nginx, Angie, HAProxy) | Базы данных (PostgreSQL, MariaDB), кластерные хранилища (DRBD, OCFS2, Ceph) |

Подробный разбор архитектуры Pacemaker и Corosync представлен в **[руководстве по стеку Pacemaker + Corosync + DRBD](../../Concepts/High_Availability/linux_ha_stack_pacemaker_drbd.md)**.

---

## Практические сценарии и настройка

### Сценарий 1: Двухнодовый веб-кластер Keepalived с трекингом шлюза и защитой от Split-Brain

**Задача:** Обеспечить работу плавающего VIP `192.168.10.100` для двух веб-серверов Nginx. Предотвратить Split-Brain при обрыве линка между узлами путем трекинга доступности вышестоящего шлюза `192.168.10.1` и процесса веб-сервера.

#### Сетевая топология
- **Узел 1 (web-node1):** IP `192.168.10.11/24`, интерфейс `eth0`
- **Узел 2 (web-node2):** IP `192.168.10.12/24`, интерфейс `eth0`
- **Виртуальный IP (VIP):** `192.168.10.100/24`
- **Шлюз по умолчанию:** `192.168.10.1`

#### Предварительная настройка ядра Linux (на обоих узлах)

Для корректной работы сервисов на резервном узле до момента назначения VIP необходимо разрешить связывание сокетов с непривязанным адресом (`ip_nonlocal_bind`), а также настроить реакцию на ARP-запросы.

```bash
cat << 'EOF' > /etc/sysctl.d/90-keepalived-ha.conf
# Разрешить процессам слушать VIP до его назначения на интерфейс
net.ipv4.ip_nonlocal_bind = 1

# Предотвратить ответ на ARP с несоответствующих интерфейсов
net.ipv4.conf.all.arp_ignore = 1
net.ipv4.conf.all.arp_announce = 2
net.ipv4.conf.default.arp_ignore = 1
net.ipv4.conf.default.arp_announce = 2
EOF

sysctl -p /etc/sysctl.d/90-keepalived-ha.conf
# → net.ipv4.ip_nonlocal_bind = 1
# → net.ipv4.conf.all.arp_ignore = 1
# → net.ipv4.conf.all.arp_announce = 2
```

#### Настройка скрипта проверки здоровья (`/usr/local/bin/check_web_gateway.sh`)

Скрипт проверяет активность Nginx и доступность внешнего шлюза. Если шлюз недоступен, скрипт завершается с ошибкой, что снижает приоритет узла.

```bash
cat << 'EOF' > /usr/local/bin/check_web_gateway.sh
#!/usr/bin/env bash
set -euo pipefail

# 1. Проверка работоспособности локального веб-сервера
if ! systemctl is-active --quiet nginx; then
    exit 1
fi

# 2. Проверка доступности внешнего L3-шлюза (свидетель кворума)
# 1 пакет, таймаут ожидания 1 секунда
if ! ping -c 1 -W 1 192.168.10.1 > /dev/null 2>&1; then
    exit 2
fi

exit 0
EOF

chmod 755 /usr/local/bin/check_web_gateway.sh
```

#### Конфигурация Узла 1 (`/etc/keepalived/keepalived.conf`)

> [!IMPORTANT]
> Обратите внимание на использование `nopreempt` и весов `weight -60`. Базовый приоритет Node 1 равен 140, Node 2 — 100. Если у Node 1 падает скрипт проверки, его эффективный приоритет падает до $140 - 60 = 80$, что ниже 100. Роль переходит к Node 2 без Split-Brain.

```keepalived
global_defs {
    router_id web_node1
    enable_script_security
    script_user root
    max_auto_priority 0
}

# Отслеживание состояния веб-сервера и шлюза
vrrp_script chk_web {
    script "/usr/local/bin/check_web_gateway.sh"
    interval 2       # Проверка каждые 2 секунды
    timeout 2        # Таймаут выполнения
    fall 2           # 2 ошибки подряд для фиксации сбоя
    rise 2           # 2 успеха подряд для восстановления
    weight -60       # Вычитание 60 из приоритета при ошибке (140 - 60 = 80)
}

vrrp_instance VI_WEB {
    state BACKUP              # Рекомендуется BACKUP на всех узлах при nopreempt
    interface eth0
    virtual_router_id 42
    priority 140
    advert_int 1
    nopreempt                 # Запрет автоматического возврата роли во избежание дребезга

    # Использование Unicast предотвращает проблемы с Multicast/IGMP Snooping
    unicast_src_ip 192.168.10.11
    unicast_peer {
        192.168.10.12
    }

    virtual_ipaddress {
        192.168.10.100/24 dev eth0
    }

    track_script {
        chk_web
    }

    # Настройка Gratuitous ARP для мгновенного обновления CAM-таблиц
    garp_master_delay 1
    garp_master_repeat 3
    garp_master_refresh 5
    garp_master_refresh_repeat 2
}
```

#### Конфигурация Узла 2 (`/etc/keepalived/keepalived.conf`)

```keepalived
global_defs {
    router_id web_node2
    enable_script_security
    script_user root
    max_auto_priority 0
}

vrrp_script chk_web {
    script "/usr/local/bin/check_web_gateway.sh"
    interval 2
    timeout 2
    fall 2
    rise 2
    weight -60       # При ошибке приоритет падает со 100 до 40
}

vrrp_instance VI_WEB {
    state BACKUP
    interface eth0
    virtual_router_id 42
    priority 100
    advert_int 1
    nopreempt

    unicast_src_ip 192.168.10.12
    unicast_peer {
        192.168.10.11
    }

    virtual_ipaddress {
        192.168.10.100/24 dev eth0
    }

    track_script {
        chk_web
    }

    garp_master_delay 1
    garp_master_repeat 3
    garp_master_refresh 5
    garp_master_refresh_repeat 2
}
```

---

### Сценарий 2: Детерминированный STONITH / IPMI Fencing в Keepalived

**Задача:** Если узел переходит в состояние `MASTER` в результате аварии соседа, гарантированно убедиться в выключении второго сервера через интерфейс управления IPMI/BMC, предотвращая параллельное владение VIP.

#### Архитектура Out-of-Band управления
- Node 1 BMC IP: `10.0.0.11` (порт IPMI LAN)
- Node 2 BMC IP: `10.0.0.12`
- Учетные данные IPMI хранятся в защищенном конфигурационном файле `/etc/keepalived/ipmi.conf` с правами `0400`.

#### Конфигурационный файл учетных данных `/etc/keepalived/ipmi.conf`

```ini
IPMI_USER="fence_admin"
IPMI_PASS="K33pAliveDFencePass!"
```

#### Скрипт изоляции соседа `/usr/local/bin/fence_peer_ipmi.sh`

```bash
cat << 'EOF' > /usr/local/bin/fence_peer_ipmi.sh
#!/usr/bin/env bash
set -euo pipefail

# Аргументы, передаваемые Keepalived: $1 = тип группы/инстанса, $2 = имя, $3 = новое состояние
STATE="${3:-}"

if [[ "$STATE" != "MASTER" ]]; then
    # Изоляция требуется только при входе в состояние MASTER
    exit 0
fi

# Подключение учетных данных
source /etc/keepalived/ipmi.conf

# Определение целевого BMC IP
HOSTNAME=$(hostname -s)
if [[ "$HOSTNAME" == "web-node1" ]]; then
    TARGET_BMC="10.0.0.12"
    TARGET_HOST="web-node2"
elif [[ "$HOSTNAME" == "web-node2" ]]; then
    TARGET_BMC="10.0.0.11"
    TARGET_HOST="web-node1"
else
    logger -t keepalived-fence -p user.err "Неизвестный хост: $HOSTNAME"
    exit 1
fi

logger -t keepalived-fence -p user.warn "Переход в MASTER! Инициирую STONITH для $TARGET_HOST ($TARGET_BMC)..."

# Проверка текущего статуса питания
POWER_STATUS=$(ipmitool -I lanplus -H "$TARGET_BMC" -U "$IPMI_USER" -P "$IPMI_PASS" chassis power status 2>/dev/null || echo "error")

if [[ "$POWER_STATUS" == *"on"* ]]; then
    logger -t keepalived-fence -p user.warn "Целевой узел $TARGET_HOST включен. Посылаю команду принудительного выключения (power off)..."
    
    # Жесткое отключение питания (hard power off)
    ipmitool -I lanplus -H "$TARGET_BMC" -U "$IPMI_USER" -P "$IPMI_PASS" chassis power off
    
    # Ожидание подтверждения отключения (максимум 5 секунд)
    for i in {1..5}; do
        sleep 1
        CURRENT_STATUS=$(ipmitool -I lanplus -H "$TARGET_BMC" -U "$IPMI_USER" -P "$IPMI_PASS" chassis power status 2>/dev/null || echo "")
        if [[ "$CURRENT_STATUS" == *"off"* ]]; then
            logger -t keepalived-fence -p user.notice "STONITH успешно выполнен: узел $TARGET_HOST обесточен."
            exit 0
        fi
    done
    
    logger -t keepalived-fence -p user.err "ВНИМАНИЕ: Узел $TARGET_HOST не отключился за 5 секунд!"
    exit 2
else
    logger -t keepalived-fence -p user.info "Узел $TARGET_HOST уже выключен ($POWER_STATUS). Вмешательство не требуется."
    exit 0
fi
EOF

chmod 700 /usr/local/bin/fence_peer_ipmi.sh
chmod 400 /etc/keepalived/ipmi.conf
```

#### Интеграция в `keepalived.conf`

```keepalived
vrrp_instance VI_WEB {
    # ... параметры из Сценария 1 ...

    # Скрипт вызывается при любой смене состояния
    notify "/usr/local/bin/fence_peer_ipmi.sh"
}
```

---

### Сценарий 3: Кластер веб-серверов Pacemaker + Corosync с третьим узлом-арбитром (QNet) и STONITH

Когда веб-серверы обслуживают разделяемое дисковое хранилище (NFS-экспорт, OCFS2, реплицируемый кэш) или требуют безусловного кворума, стек **Corosync + Pacemaker** с третьим узлом-свидетелем (`corosync-qnetd`) является отраслевым эталоном.

```
            ┌──────────────────┐               ┌──────────────────┐
            │   web-node1      │               │   web-node2      │
            │  192.168.10.11   │◄─────────────►│  192.168.10.12   │
            │  [Pacemaker]     │    Corosync   │  [Pacemaker]     │
            │  IPMI: 10.0.0.11 │    Knet UDP   │  IPMI: 10.0.0.12 │
            └─────────┬────────┘               └─────────┬────────┘
                      │                                  │
                      │       QNet Protocol (TCP 5403)   │
                      │      ┌────────────────────┐      │
                      └─────►│  witness-node3     │◄─────┘
                             │  192.168.10.13     │
                             │  [corosync-qnetd]  │
                             └────────────────────┘
```

#### Шаг 1: Развертывание службы QNet на третьем легковесном узле (`witness-node3`)

На узле `witness-node3` не запускаются веб-серверы и Pacemaker; устанавливается только служба свидетеля:

```bash
apt-get update && apt-get install -y corosync-qnetd
systemctl enable --now corosync-qnetd
# → Created symlink /etc/systemd/system/multi-user.target.wants/corosync-qnetd.service
```

#### Шаг 2: Настройка кластера и QDevice на веб-нодах через `pcs`

Выполняется с узла `web-node1`:

```bash
# 1. Аутентификация нод кластера
pcs host auth web-node1 web-node2 -u hacluster -p 'SecureClusterPass!'
# → web-node1: Authorized
# → web-node2: Authorized

# 2. Создание кластера из двух нод
pcs cluster setup web-ha-cluster web-node1 web-node2
pcs cluster start --all
pcs cluster enable --all

# 3. Подключение свидетеля кворума (QDevice)
pcs quorum device add model net host=192.168.10.13 algorithm=ffsplit
# → Setting up QNet certificate on 192.168.10.13...
# → Corosync QDevice successfully configured.
```

#### Шаг 3: Настройка STONITH-агентов IPMI

В кластерах Pacemaker изоляция узлов обязательна. Отключение STONITH (`stonith-enabled=false`) в производственных средах категорически запрещено.

```bash
# STONITH-агент для изоляции web-node1 (управляется через IPMI web-node1)
pcs stonith create fence_node1 fence_ipmilan \
    ip="10.0.0.11" \
    username="fence_admin" \
    password="K33pAliveDFencePass!" \
    method="onoff" \
    power_timeout="20" \
    pcmk_host_list="web-node1"

# STONITH-агент для изоляции web-node2
pcs stonith create fence_node2 fence_ipmilan \
    ip="10.0.0.12" \
    username="fence_admin" \
    password="K33pAliveDFencePass!" \
    method="onoff" \
    power_timeout="20" \
    pcmk_host_list="web-node2"
```

#### Шаг 4: Создание ресурсов VIP и Nginx

```bash
# Создание плавающего IP-адреса
pcs resource create ClusterVIP ocf:heartbeat:IPaddr2 \
    ip=192.168.10.100 \
    cidr_netmask=24 \
    nic=eth0 \
    op monitor interval=10s timeout=20s

# Создание ресурса веб-сервера
pcs resource create WebServer systemd:nginx \
    op monitor interval=10s timeout=20s

# Связывание: Nginx должен работать на том же узле, где находится VIP
pcs constraint colocation add WebServer with ClusterVIP INFINITY

# Порядок запуска: сначала поднимается VIP, затем стартует Nginx
pcs constraint order ClusterVIP then WebServer
```

---

## Операции и команды

Сводка эксплуатационных команд администратора для мониторинга, отладки и ручного тестирования механизмов отказоустойчивости и изоляции:

| Задача | Команда | Ожидаемый результат / Пояснение |
| :--- | :--- | :--- |
| **Инспекция VRRP-пакетов** | `tcpdump -nnvvv -i eth0 proto 112` | Отображение входящих/исходящих пакетов VRRP, текущего приоритета (`prio 140/100`) и интервала анонсов. |
| **Проверка статуса VIP** | `ip -brief address show dev eth0` | Вывод назначенного IP. На MASTER: `eth0 UP 192.168.10.11/24 192.168.10.100/24`. На BACKUP: только локальный IP. |
| **Тест ARP-конфликта в L2** | `arping -I eth0 -c 3 -D 192.168.10.100` | Детектирование дублирования адреса (DAD). Если возвращается `exit code 1` — в сети обнаружен узел с таким же IP. |
| **Просмотр соседей в ARP** | `ip neighbor show 192.168.10.100` | Отображение сопоставления VIP и физического MAC-адреса. |
| **Проверка статуса BMC питания** | `ipmitool -I lanplus -H 10.0.0.12 -U user -P pass chassis power status` | `# → Chassis Power is on` |
| **Проверка кворума Corosync** | `corosync-quorumtool -s` | `# → Quorum: 2 (expected 3), Nodes: 2, Qdevice: 1, Activity: Yes` |
| **Тестовая изоляция ноды** | `pcs stonith fence web-node2` | Принудительная перезагрузка узла через STONITH-агент для валидации цепи изоляции. |
| **Имитация аварии линка** | `iptables -I INPUT -p 112 -j DROP` | Искусственный разрыв связи по протоколу VRRP для проверки сценария Split-Brain. |
| **Восстановление после теста** | `iptables -D INPUT -p 112 -j DROP` | Снятие блокировки и проверка штатного перехода ролей. |

---

## Диагностика и устранение неполадок

| Проблема / Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Состояние Dual-MASTER (Оба узла держат VIP)** | 1. Firewall блокирует VRRP (IP proto 112).<br>2. Разные `virtual_router_id`.<br>3. Блокировка Multicast коммутатором. | `tcpdump -i eth0 proto 112`<br>`grep -i vrrp /var/log/syslog` | 1. Разрешить протокол 112: `iptables -A INPUT -p 112 -j ACCEPT`.<br>2. Синхронизировать `virtual_router_id`.<br>3. Перевести Keepalived на `unicast_peer`. |
| **Бесконечный дребезг ролей (Flapping MASTER/BACKUP)** | 1. `track_script` падает и поднимается.<br>2. Время выполнения скрипта превышает `timeout`.<br>3. Включен preemption без задержки. | `journalctl -u keepalived -e`<br>`time /usr/local/bin/check_script.sh` | 1. Оптимизировать скрипт, увеличить `interval` и `timeout`.<br>2. Включить `nopreempt` во `vrrp_instance`. |
| **Клиенты не видят VIP после переключения** | Коммутатор L2 не обновил CAM-таблицу или шлюз держит старый ARP-кэш. | `ip neigh show` на шлюзе.<br>`tcpdump -i eth0 arp` | Настроить агрессивную отправку GARP: `garp_master_repeat 5`, `garp_master_refresh 10`. |
| **Скрипт STONITH зависает или завершается ошибкой** | Недоступность IPMI-интерфейса из рабочей сети или неверные учетные данные. | `ipmitool -I lanplus ... chassis power status` вручную. | Проверить маршрутизацию в OOB-сеть (VLAN управления) и корректность пароля в `/etc/keepalived/ipmi.conf`. |
| **`Keepalived_vrrp: Script ... execution timed out`** | Скрипт проверки веб-сервера завис на сетевом вызове (curl/ping). | Проверить наличие внешних таймаутов у команд (`curl --max-time 1`, `ping -W 1`). | Добавить жесткие таймауты внутри скрипта и флаг `timeout` в секции `vrrp_script`. |

---

## Лучшие практики (SRE и системное администрирование)

1. **Изоляция сети управления (Out-of-Band):** Интерфейсы IPMI, iLO, iDRAC и сетевые PDU должны находиться в отдельном физическом или изолированном L2 VLAN, недоступном из публичной сети и изолированном от клиентского трафика.
2. **Отказ от Multicast в пользу Unicast:** В корпоративных дата-центрах мультикаст-трафик часто отсекается коммутаторами с включенным IGMP Snooping или политиками безопасности. Всегда используйте `unicast_src_ip` и `unicast_peer`.
3. **Обязательное применение `nopreempt`:** Автоматический возврат роли мастера при восстановлении узла («вытеснение») приводит к повторному разрыву клиентских TCP-сессий. Возврат должен производиться администратором вручную в регламентное окно.
4. **Безопасность выполнения внешних скриптов:** В Keepalived всегда активируйте директивы `enable_script_security` и указывайте непривилегированного системного пользователя (`script_user`) для минимизации вектора атак при компрометации веб-сервера.
5. **Настройка `ip_nonlocal_bind`:** Всегда активируйте параметр ядра `net.ipv4.ip_nonlocal_bind = 1`. Это гарантирует, что Nginx, Angie или HAProxy смогут запуститься и слушать порт на резервном сервере еще до того, как VIP физически перейдет на его интерфейс.
6. **Двойной контроль состояния (Процесс + Шлюз):** Скрипт проверки должен контролировать не только локальный процесс (`systemctl is-active nginx`), но и возможность доставки трафика во внешнюю сеть (ping L3-шлюза). Узел, потерявший внешний линк, не должен оставаться мастером.
7. **Калибровка таймеров BFD и VRRP:** Не устанавливайте субсекундные таймеры VRRP (`advert_int < 1`) без протокола BFD или выделенной прямой оптической линии между серверами. Кратковременный всплеск нагрузки CPU может спровоцировать ложное переключение.

---

## Дополнительная информация

- **[Keepalived: обзор и настройка высокой доступности](../../Networking/ServicesAndTools/keepalived_overview.md)** — полный справочник параметров директив `vrrp_instance`, `virtual_server` и синхронизации LVS.
- **[Настройка отказоустойчивого кластера Angie с Keepalived](../Angie/angie_ha_with_keepalived.md)** — пример построения HA-кластера обратных прокси с интеграцией BFD и кластерной синхронизацией сессий `zone_sync`.
- **[Стек высокой доступности: Pacemaker + Corosync + DRBD](../../Concepts/High_Availability/linux_ha_stack_pacemaker_drbd.md)** — реализация кворумных кластеров с синхронной репликацией блочных устройств.
- **[Механизмы переключения при отказе (Failover) и пульс (Heartbeat)](../../Concepts/High_Availability/ha_failover_mechanisms.md)** — концептуальные основы RTO, RPO, детектирования сбоев и hold-off таймеров.
- **[VRRP / HSRP / GLBP — First Hop Redundancy Protocols](../../Networking/Protocols/vrrp_hsrp_glbp.md)** — спецификации протоколов сетевого резервирования.
- **[Протокол разрешения адресов ARP и Gratuitous ARP](../../Networking/Protocols/arp.md)** — детали работы кэширования ARP, формата пакетов и обновления таблиц коммутации.
