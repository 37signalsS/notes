# Keepalived — обзор и настройка высокой доступности (HA)

## Определения

**Keepalived** — системный демон для Linux, обеспечивающий высокую доступность (HA — High Availability) и отказоустойчивость через управление виртуальным IP-адресом (VIP) на базе протокола **VRRP (Virtual Router Redundancy Protocol)**. Также включает подсистему **LVS (Linux Virtual Server)** для балансировки нагрузки на.setLevel с проверками здоровья.

**Актуальность (2025–2026):** Keepalived остаётся стандартом де-факто для обеспечения высокой доступности в bare-metal и VM-окружениях. Версия **2.4.x** (June 2026) включает расширение `auth_hmac` (HMAC-SHA256 подпись VRRP-анонсов), масштабную проверку безопасности (parser, netlink, checker, notify, DBus) и поддержку VRRPv3 субсекундных таймеров.

**VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол (RFC 5798), позволяющий группе серверов совместно владеть виртуальным IP-адресом. Один узел становится `MASTER`, остальные — `BACKUP`.

**Виртуальный IP (Virtual IP, VIP / Floating IP)** — IP-адрес, не привязанный жёстко к одному физическому серверу. В рамках кластера он перемещается на активный узел (`MASTER`).

**Высокая доступность (HA)** vs **Отказоустойчивость (FT):**
- **HA (High Availability)** — минимизация времени простоя. При сбое допустим краткий перерыв (секунды) на переключение. Общие принципы — в **[обзоре High Availability](../../Concepts/High_Availability/ha_overview.md)**.
- **FT (Fault Tolerance)** — система продолжает работать без видимых перебоев (например, агрегация каналов LACP или зеркалирование трафика).

## Основные концепции

### Принцип работы (Active-Passive)

1.  **Настройка:** На узлах устанавливается Keepalived. Одному назначается более высокий приоритет (`priority`). Плавающий IP **не должен** быть прописан статически в системных конфигах сети (`/etc/network/interfaces`, `netplan`).
2.  **Heartbeat (VRRP advertisements):** `MASTER` периодически отправляет VRRP-сообщения (Multicast 224.0.0.18 или Unicast).
3.  **Ожидание:** `BACKUP` серверы слушают анонсы. Переключение инициируется, если сообщения отсутствуют в течение `3 * advert_int + skew_time`.
4.  **Failover:** Если мастер недоступен, бэкап с наивысшим приоритетом переходит в состояние `MASTER`.
5.  **Gratuitous ARP (GARP):** Новый `MASTER` отправляет GARP-запрос. Это критический этап: коммутаторы обновляют таблицу MAC-адресов, и трафик мгновенно направляется на новый физический порт (L2).
6.  **Failback (Preemption):** По умолчанию, если оригинальный `MASTER` восстанавливается, он забирает роль обратно. Для предотвращения «флаппинга» (постоянных переключений) используют опцию `nopreempt`.

### Виртуальные IP-адреса

**Синтаксис в конфигурации:**
```keepalived
virtual_ipaddress {
    # Базовый формат
    192.168.1.100/24 dev eth0

    # С label (для отладки)
    192.168.1.101/24 dev eth0 label eth0:vip1

    # Базовый формат (broadcast, scope)
    10.0.0.100/24 dev eth1 brd 10.0.0.255 scope global
}
```

**Ограничение:** Максимум 20 VIP на `vrrp_instance` (через `virtual_ipaddress`). Для неограниченного числа VIP (не участвующих в VRRP) используйте `virtual_ipaddress_excluded`.

**GARP-параметры (настройка частоты и задержек):**
```keepalived
vrrp_instance VI_1 {
    # ...
    # Задержка перед первым GARP после перехода в MASTER (сек)
    garp_master_delay 5

    # Количество повторных GARP после transition
    garp_master_repeat 1

    # Задержка перед GARP от узла с более низким приоритетом (сек)
    garp_lower_prio_delay 10

    # Повторные GARP от lower-prio узла
    garp_lower_prio_repeat 1

    # Интервал повторных GARP в MASTER (сек, 0 = отключено)
    garp_master_refresh 0

    # Количество повторных garp_master_refresh
    garp_master_refresh_repeat 1
}
```

### Защита от Split-Brain

**Split-Brain** — ситуация, когда из-за проблем в сети узлы перестают видеть друг друга и оба становятся `MASTER`, вызывая конфликт IP и риск повреждения данных (особенно в БД).

#### Рекомендации по минимизации рисков:
- **Выделенный канал (Heartbeat Link):** Использование отдельного физического интерфейса или выделенного VLAN для трафика VRRP.
- **Режим Unicast (рекомендуется):** В отличие от Multicast, который часто блокируется в облаках или фильтруется коммутаторами, Unicast (`unicast_peer`) явно определяет адреса соседей.
- **Кворум:** Для кластеров 3+ узлов Keepalived поддерживает механизмы отслеживания кворума.
- **Безопасность:** В VRRPv3 аутентификация упразднена. Начиная с версии 2.4.0 доступно расширение `auth_hmac` (HMAC-SHA256 подпись анонсов).
- **`vrrp_sync_group`:** Группировка нескольких `vrrp_instance` для синхронного переключения. Все экземпляры в группе переходят в `MASTER`/`BACKUP` одновременно, что критично при наличии нескольких VIP на разных интерфейсах.

### Версии VRRP и BFD

| Механизм | Описание |
| :--- | :--- |
| **VRRPv2** | Стандарт для IPv4 (RFC 3768). Целочисленные интервалы анонсов (секунды). Встроенная аутентификация (PASS/AH). |
| **VRRPv3** | Поддержка IPv4/IPv6 (RFC 5798), таймеры в миллисекундах (sub-second), отсутствие встроенной аутентификации. |
| **BFD** | Bidirectional Forwarding Detection (RFC 5880). Позволяет Keepalived реагировать на разрыв связи за 50–100 мс, интегрируясь с демонами маршрутизации (например, FRR). |
| **auth_hmac** | (v2.4.0+) HMAC-SHA256 подпись VRRP-анонсов. Закрывает уязвимость unicast-деплоев, где анонсы проходят через маршрутизаторы и TTL-guard не защищает от spoofing/replay. |

### IPv6 и VRRPv3

VRRPv3 (RFC 5798) — единственная версия протокола, поддерживающая IPv6. В отличие от VRRPv2, аутентификация в VRRPv3 отсутствует (используется `auth_hmac` v2.4.0+).

**Особенности VRRPv3 для IPv6:**
- МульICAST-адрес: `ff02::12` (вместо `224.0.0.18` для IPv4)
- Протокол: IPv6 (Next Header 112)
- Таймеры: миллисекунды (sub-second)
- Адрес VIP: IPv6-адрес с префиксом `/128` или `Link-Local`

**Конфигурация Keepalived для IPv6 (Dual-Stack VIP):**

```keepalived
vrrp_instance VI_INET6 {
    state MASTER
    interface eth0
    virtual_router_id 52   # Отдельный VRID для IPv6 (не совпадать с IPv4!)
    priority 101
    advert_int 1

    # VRRPv3 обязателен для IPv6
    vrrp_version 3

    # Unicast (рекомендуется для production)
    unicast_src_ip fd00::1
    unicast_peer {
        fd00::2
    }

    # IPv6 Virtual IP
    virtual_ipaddress {
        fd00::100/128 dev eth0 label eth0:vip6
    }

    # Notify-скрипты (те же, что и для IPv4)
    notify_master "/etc/keepalived/notify_master.sh"
    notify_backup "/etc/keepalived/notify_backup.sh"
    notify_fault  "/etc/keepalived/notify_fault.sh"
}
```

**Dual-Stack конфигурация (IPv4 + IPv6 VIP):**

```keepalived
# IPv4 VRRPv2 instance
vrrp_instance VI_INET4 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1

    unicast_src_ip 10.0.0.1
    unicast_peer {
        10.0.0.2
    }

    virtual_ipaddress {
        10.0.0.100/24 dev eth0 label eth0:vip4
    }
}

# IPv6 VRRPv3 instance
vrrp_instance VI_INET6 {
    state MASTER
    interface eth0
    virtual_router_id 52   # VRID должен отличаться!
    priority 101
    advert_int 1

    vrrp_version 3

    unicast_src_ip fd00::1
    unicast_peer {
        fd00::2
    }

    virtual_ipaddress {
        fd00::100/128 dev eth0 label eth0:vip6
    }
}

# Синхронизация переключения IPv4 и IPv6
vrrp_sync_group SG_INET {
    group {
        VI_INET4
        VI_INET6
    }
    notify_master "/etc/keepalived/notify_all_master.sh"
    notify_backup "/etc/keepalived/notify_all_backup.sh"
}
```

**Важные замечания:**
- `virtual_router_id` для IPv4 и IPv6 **должен** отличаться (VRID — это scope на L2-сегменте).
- VRRPv2-пакеты отправляются на `224.0.0.18`, VRRPv3 для IPv6 — на `ff02::12`. Это разные multicast-группы, конфликта нет.
- При использовании `vrrp_sync_group` переключение IPv4 и IPv6 VIP происходит одновременно.
- Для обнаружения отказа за <100 мс используйте BFD (RFC 5880) поверх IPv6.

### Аутентификация

**VRRPv2 — встроенная аутентификация:**
```keepalived
vrrp_instance VI_1 {
    authentication {
        auth_type PASS    # Простой пароль (макс. 8 символов)
        auth_pass S3cret
    }
    # auth_type AH — IPsec Authentication Header (редко используется)
}
```

**VRRPv2+ — auth_hmac (v2.4.0+):**
```keepalived
vrrp_instance VI_1 {
    # HMAC-SHA256 подпись каждого VRRP-анонса
    # Закрывает spoofing/replay для unicast-деплоев
    auth_hmac

    # Опционально: ключ шифрования (автоматически генерируется, если не указан)
    # auth_hmac_key /etc/keepalived/hmac.key
}
```

**Важно:** При использовании `auth_hmac` все узлы виртуального роутера **обязаны** работать на одной версии Keepalived (2.4.1+), так как формат trailer изменился между 2.4.0 и 2.4.1.

### Сетевой экран

VRRP работает поверх IP (протокол **112**).

**firewalld:**
```bash
sudo firewall-cmd --add-protocol=vrrp --permanent
# Если используется Unicast, разрешить пакеты от соседа
sudo firewall-cmd --add-rich-rule='rule family="ipv4" source address="10.0.0.2" protocol value="vrrp" accept' --permanent
sudo firewall-cmd --reload
```

**iptables:**
```bash
# Разрешить VRRP от соседа 10.0.0.2
sudo iptables -A INPUT -p vrrp -s 10.0.0.2 -j ACCEPT
sudo iptables -A INPUT -p vrrp -j DROP
```

**nftables:**
```nftables
table inet filter {
    chain input {
        ip protocol vrrp accept
    }
}
```

### Механизмы отслеживания (Tracking)

Keepalived динамически снижает приоритет узла (`weight`), если проверка не проходит:

1.  **vrrp_script**: Вызов внешнего скрипта. Код возврата `0` — успех.
2.  **track_process**: (с версии 2.0) Нативный мониторинг процесса (например, `nginx`, `haproxy`) без вызова shell. Это экономит ресурсы и быстрее реагирует на падение службы.
3.  **track_interface**: Мониторинг линка. Если интерфейс `eth1` упал, узел должен отдать роль мастера.
4.  **track_file**: Отслеживание состояния по содержимому файла (с версии 2.0). Файл отслеживается через `inotify`.
5.  **track_bfd**: Отслеживание сессии BFD. Если BFD-сессия падает, приоритет снижается.

#### vrrp_script — детальная настройка

```keepalived
# Определение скрипта проверки
vrrp_script check_haproxy {
    script "/etc/keepalived/check_haproxy.sh"  # Путь к скрипту
    interval 2           # Интервал проверки (сек)
    fall 3               # Количество неудачных проверок до снижения приоритета
    rise 2               # Количество успешных проверок до восстановления
    weight -20           # Снижение приоритета при провале (-253..253)
    timeout 10           # Таймаут выполнения скрипта (сек)
    user root            # Пользователь для запуска (или keepalived_script)
    init_fail            # Считать начальное состояние как «не прошло»
}
```

#### track_file — мониторинг файла

```keepalived
# Отслеживание файла
vrrp_track_file check_disk {
    file /etc/keepalived/disk_state.txt
    weight -30           # Снижение приоритета (-254..254)
    # Файл содержит: 0 = OK, не 0 = FAIL
}
```

#### track_bfd — мониторинг BFD-сессии

```keepalived
vrrp_track_bfd bfd_down {
    bfd_down             # Имя BFD-экземпляра
    weight -50           # Снижение приоритета при потере BFD-сессии
}
```

### Уведомления (Notify Scripts)

Keepalived позволяет выполнять пользовательские скрипты при смене состояний. Это критически важно для активации сервисов, обновления DNS, отправки алертов.

**Доступные хуки:**
| Хук | Описание |
| :--- | :--- |
| `notify_master` | Вызывается при переходе в `MASTER` |
| `notify_backup` | Вызывается при переходе в `BACKUP` |
| `notify_fault` | Вызывается при переходе в `FAULT` |
| `notify_stop` | Вызывается при остановке Keepalived |
| `notify` | Вызывается при **любом** переходе |

**Аргументы, передаваемые скрипту (`$1`–`$4`):**
```bash
#!/bin/bash
# $1 = "GROUP"|"INSTANCE"
# $2 = имя группы или экземпляра
# $3 = целевое состояние ("MASTER"|"BACKUP"|"FAULT"|"STOP")
# $4 = приоритет узла
```

**Пример скрипта notify_master:**
```bash
#!/bin/bash
# /etc/keepalived/notify_master.sh
# Обновление DNS-записи при переходе в MASTER

DOMAIN="ha.example.com"
TTL=60

case "$3" in
    MASTER)
        # Обновить DNS A-запись на VIP
        curl -s "https://dns-api.example.com/update?domain=${DOMAIN}&ip=${VIP}&ttl=${TTL}"
        # Отправить алерт
        curl -s -X POST https://hooks.slack.com/services/XXX \
            -d "{\"text\": \"MASTER activated on $(hostname) with VIP ${VIP}\"}"
        ;;
    BACKUP)
        curl -s -X POST https://hooks.slack.com/services/XXX \
            -d "{\"text\": \"BACKUP mode on $(hostname)\"}"
        ;;
esac
```

**Пример скрипта notify_backup:**
```bash
#!/bin/bash
# /etc/keepalived/notify_backup.sh
# Деактивация сервисов при уходе в BACKUP

case "$3" in
    BACKUP)
        # Остановить запись в БД (если это реплика)
        systemctl stop postgresql
        # Обновить DNS
        curl -s "https://dns-api.example.com/remove?domain=${DOMAIN}"
        ;;
esac
```

### vrrp_sync_group — группировка экземпляров

Группа синхронизирует состояние нескольких `vrrp_instance`. Все экземпляры в группе переходят в `MASTER`/`BACKUP` одновременно. Критично, когда VIP на разных интерфейсах должны переключаться вместе.

```keepalived
vrrp_sync_group VG_WEB {
    group {
        VI_VLAN100      # VIP в VLAN 100
        VI_VLAN200      # VIP в VLAN 200
    }

    # Уведомления на уровне группы (приоритетнее, чем в instance)
    notify_master "/etc/keepalived/notify_master.sh"
    notify_backup "/etc/keepalived/notify_backup.sh"
    notify_fault  "/etc/keepalived/notify_fault.sh"
    notify_stop   "/etc/keepalived/notify_stop.sh"

    # SMTP-уведомление
    smtp_alert
}

vrrp_instance VI_VLAN100 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1
    # ...
}

vrrp_instance VI_VLAN200 {
    state MASTER
    interface eth1
    virtual_router_id 52
    priority 101
    advert_int 1
    # ...
}
```

### Preemption и nopreempt

**Preemption (по умолчанию включён):** Восстановившийся `MASTER` забирает роль обратно у `BACKUP`.

**nopreempt:** Отключение принудительного перехвата. Рекомендуется для стабильности.

```keepalived
vrrp_instance VI_1 {
    state BACKUP          # Оба узла — BACKUP (рекомендовано для nopreempt)
    nopreempt             # Отключить принудительный перехват
    preempt_delay 300     # Задержка перед перехватом (сек, 0–1000)
    # ...
}
```

**Важно:** При использовании `nopreempt` оба узла должны иметь `state BACKUP`. Узел с более высоким приоритетом автоматически станет `MASTER` при старте.

### BFD — Bidirectional Forwarding Detection

BFD (RFC 5880) обеспечивает сверхбыстрое обнаружение отказов (50–100 мс). Работает в паре с VRRP.

```keepalived
# Определение BFD-сессии
bfd_instance BFD_NODE2 {
    neighbor_ip 10.0.0.2       # IP-адрес соседа
    source_ip 10.0.0.1         # Локальный IP (опционально)
    min_rx 300                  # Минимальный RX-интервал (мс, по умолчанию 10)
    min_tx 300                  # Минимальный TX-интервал (мс, по умолчанию 10)
    idle_tx 1000               # TX-интервал в idle (мс)
    multiplier 3               # Множитель dead-детекции
    # dead = max(min_rx * multiplier, min_tx * multiplier + detect_mult * min_tx)
}

# Привязка BFD к VRRP
vrrp_instance VI_1 {
    # ...
    track_bfd {
        BFD_NODE2              # Мониторинг BFD-сессии
        BFD_NODE2 weight -50   # С понижением приоритета
    }
}
```

## Практические сценарии

### Пример конфигурации с VRRPv3 и track_process

Файл: `/etc/keepalived/keepalived.conf`

```keepalived
global_defs {
   router_id LB_NODE_1
   vrrp_garp_master_delay 5
   enable_snmp_vrrp
   # Отправка email при смене состояния
   smtp_server 127.0.0.1
   smtp_connect_timeout 30
   router_email "admin@example.com"
   notification_email_from "keepalived@example.com"
}

# Нативный мониторинг процесса (без скрипта)
vrrp_track_process check_haproxy {
    process haproxy
    weight -20
}

# Мониторинг файла
vrrp_track_file check_config {
    file /etc/keepalived/config_state.txt
    weight -10
}

vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101

    # Использование VRRPv3 для быстрой детекции
    vrrp_version 3
    advert_int 0.5 # 500 миллисекунд

    unicast_src_ip 10.0.0.1
    unicast_peer {
        10.0.0.2
    }

    virtual_ipaddress {
        192.168.1.100/24 dev eth0 label eth0:vip
    }

    track_process {
        check_haproxy
    }

    track_file {
        check_config
    }

    # GARP-параметры
    garp_master_delay 5
    garp_master_repeat 2

    # Notify-скрипты
    notify_master "/etc/keepalived/notify_master.sh"
    notify_backup "/etc/keepalived/notify_backup.sh"
    notify_fault  "/etc/keepalived/notify_fault.sh"
}
```

### Скрипты проверки здоровья

**Пример скрипта проверки HAProxy (`/etc/keepalived/check_haproxy.sh`):**
```bash
#!/bin/bash
# Проверка доступности локального эндпоинта статистики
if curl -sf http://localhost:8404/status > /dev/null 2>&1; then
    exit 0
fi
exit 1
```

**Пример скрипта проверки HTTP (`/etc/keepalived/check_http.sh`):**
```bash
#!/bin/bash
# Проверка HTTP 200 OK от конкретного URL
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:80/health)
if [ "$HTTP_CODE" = "200" ]; then
    exit 0
fi
exit 1
```

**Пример скрипта проверки TCP (`/etc/keepalived/check_tcp.sh`):**
```bash
#!/bin/bash
# Проверка TCP-подключения на порту 5432 (PostgreSQL)
timeout 2 bash -c 'cat < /dev/null > /dev/tcp/localhost/5432' 2>/dev/null
exit $?
```

**Настройка прав (keepalived 2.x+):**
```bash
# Создание пользователя для скриптов
sudo useradd -r -s /sbin/nologin -M keepalived_script

# Настройка прав доступа
sudo chown root:keepalived_script /etc/keepalived/check_*.sh
sudo chmod 750 /etc/keepalived/check_*.sh
```

### Сценарии использования

- **HA для балансировщиков (Angie/Nginx/HAProxy):** Отказоустойчивый вход с плавающим VIP. См. **[Настройка Angie с Keepalived](../../WebServers/Angie/angie_ha_with_keepalived.md)**.
- **Паттерн Warmspare (Active-Passive с отложенной синхронизацией):** Подход, при котором VIP управляется Keepalived, но данные между узлами синхронизируются периодически (например, через `rsync` или восстановление бэкапов по расписанию).
    *   **Особенности:** Узлы имеют независимые файловые системы. При сбое мастера VIP переходит на бэкап, где сервис запускается с последней сохраненной конфигурацией.
    *   **Плюсы:** Изоляция файловых систем (сбой диска или ФС на одном узле не аффектит другой), простота настройки и администрирования.
    *   **Минусы:** Данные на бэкапе могут быть неактуальны (лаг синхронизации). Требует логики активации ресурсов (транков, сервисов) через скрипты `notify_master`.
- **HA для OpenSearch:** Плавающий VIP перед узлами API. См. **[Отказоустойчивость OpenSearch с помощью Keepalived](../../ELK_Stack/OpenSearch/opensearch_high_availability_keepalived.md)**.
- **HA для балансировщика Kubernetes (Bare-metal):** VIP между двумя HAProxy для `kubectl` и Ingress. См. **[Настройка HA API-сервера](../../Kubernetes/Installation/kubeadm/ha_concepts.md)**.
- **HA для MySQL/PostgreSQL:** Переключение VIP между мастером и репликой (в связке с инструментами типа Patroni). См. **[Отказоустойчивость MySQL](../../Databases/MySQL/replication/multi-source.md)** и **[HA PostgreSQL](../../Databases/PostgreSQL/Concepts/high_availability.md)**.
- **LVS (IPVS) балансировка:** Keepalived может работать как L4-балансировщик через Linux Virtual Server. См. **[ICMP: Высокая доступность](../../Networking/Protocols/ICMP/icmp_high_availability.md)** для примера LVS NAT конфигурации.

### Диагностика

```bash
# Проверка наличия VIP (будет помечен как secondary)
ip addr show eth0
# → inet 192.168.1.100/24 scope global secondary eth0:vip

# Просмотр логов в реальном времени
journalctl -u keepalived -f

# Просмотр текущего состояния VRRP-экземпляров
keepalived --show-config

# Просмотр статистики (счётчики переходов)
keepalived --dump

# Сброс текущей статистики в файл /tmp/keepalived.stats
kill -SIGUSR2 $(cat /var/run/keepalived.pid)

# Проверка версии и доступных опций
keepalived -v

# Анализ VRRP-трафика
tcpdump -i eth0 -nn proto 112

# Проверка BFD-сессий
tcpdump -i eth0 -nn port 3784 or port 3785

# Мониторинг логов VRRP-переходов
journalctl -u keepalived | grep -E "MASTER|BACKUP|FAULT"
```

### Мониторинг Keepalived

**keepalived-exporter (Prometheus):**
```bash
# Установка
wget https://github.com/mehdy/keepalived-exporter/releases/latest/download/keepalived-exporter_linux_amd64
chmod +x keepalived-exporter_linux_amd64
sudo mv keepalived-exporter_linux_amd64 /usr/local/bin/keepalived-exporter

# Systemd unit
cat > /etc/systemd/system/keepalived-exporter.service << 'EOF'
[Unit]
Description=Keepalived Exporter
After=network.target

[Service]
ExecStart=/usr/local/bin/keepalived-exporter --keepalived.pid-path=/var/run/keepalived.pid
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now keepalived-exporter
```

**Экспортируемые метрики:**
- `keepalived_vrrp_state` — текущее состояние экземпляра (0=BACKUP, 1=MASTER, 2=FAULT)
- `keepalived_total_transitions` — количество переходов между состояниями
- `keepalived_advert_rcvd` — полученные VRRP-анонсы
- `keepalived_advert_sent` — отправленные VRRP-анонсы
- `keepalived_lower_prio_rcvd` — полученные анонсы с более низким приоритетом

### Конфигурационные директивы (справочник)

| Директива | Описание | Значения |
| :--- | :--- | :--- |
| `state` | Начальное состояние экземпляра | `MASTER`, `BACKUP` |
| `interface` | Сетевой интерфейс для VRRP | `eth0`, `ens160` и т.д. |
| `virtual_router_id` | Уникальный ID группы (1–255) | Одинаковый на MASTER/BACKUP |
| `priority` | Приоритет выборов (1–255) | Чем выше, тем выше шанс стать MASTER |
| `advert_int` | Интервал анонсов (сек) | `1` (VRRPv2), `0.5` (VRRPv3) |
| `nopreempt` | Отключение принудительного перехвата | `nopreempt` (без значения) |
| `preempt_delay` | Задержка перед перехватом (сек) | `0`–`1000` |
| `track_interface` | Монитеринг интерфейсов | `eth0`, `eth1` |
| `track_script` | Монитеринг скриптов | Имя `vrrp_script` |
| `track_file` | Мониторинг файлов | Имя `vrrp_track_file` |
| `track_bfd` | Мониторинг BFD-сессий | Имя BFD-экземпляра |
| `vrrp_version` | Версия VRRP | `2` (RFC 3768), `3` (RFC 5798) |
| `unicast_src_ip` | Source IP для unicast | IP-адрес локального узла |
| `unicast_peer` | Список邻居 для unicast | IP-адреса соседей |
| `virtual_ipaddress` | VIP (до 20 адресов) | `IP/Маска dev интерфейс` |
| `notify_master` | Скрипт при переходе в MASTER | Путь к скрипту |
| `notify_backup` | Скрипт при переходе в BACKUP | Путь к скрипту |
| `notify_fault` | Скрипт при переходе в FAULT | Путь к скрипту |
| `notify_stop` | Скрипт при остановке Keepalived | Путь к скрипту |
| `notify` | Скрипт при любом переходе | Путь к скрипту |
| `smtp_alert` | Email-уведомление при переходе | `true`/`false` |
| `auth_hmac` | HMAC-SHA256 подпись (v2.4.0+) | `auth_hmac` (без значения) |

## Дополнительная информация

### Тайминги failover

Расчет времени обнаружения сбоя: `failover_timeout = 3 × advert_int + skew_time`.
Где `skew_time = (256 - priority) / 256`.

| `advert_int` | Время переключения | Сценарий |
|:---|:---|:---|
| 1 с | ~3.5 с | Стандарт (VRRPv2), минимальный риск ложных срабатываний |
| 0.3 с | ~1 с | Агрессивный VRRPv3 (требует стабильной сети) |
| BFD | < 0.1 с | Критичные финансовые/Real-time системы |

### Ограничение L2 и альтернативы

VIP **обязан** находиться в той же L2-подсети, что и физические IP узлов. VRRP не маршрутизируется.
Если узлы в разных ЦОД (L3-связность):
- **BGP Anycast:** Узлы анонсируют один и тот же IP по BGP (через Bird или FRR).
- **DNS Failover:** Балансировка на уровне DNS (например, через Consul или GSLB), учитывая задержки TTL.

### TLS на VIP: DNS-01 challenge

При использовании Let's Encrypt (HTTP-01) проверка провалится на `BACKUP` узле, так как VIP (и трафик) находится на `MASTER`.
**Решение:** Использовать **DNS-01 challenge** (проверка через TXT-запись в DNS). Это позволяет обоим узлам независимо получать сертификаты для одного и того же доменного имени. См. **[Использование acme.sh](../../WebServers/Concepts/acme_sh.md)**.

### Типичные ошибки и решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **VIP не перемещается** | Firewall блокирует VRRP (протокол 112) | Разрешить VRRP: `firewall-cmd --add-protocol=vrrp` |
| **Split-Brain** | Multicast заблокирован в облаке | Использовать `unicast_peer` |
| **Флаппинг VIP** | Слишком агрессивный `advert_int` | Увеличить `advert_int` до 1 сек или использовать `nopreempt` |
| **track_process не реагирует** | Процесс не запущен или нет прав | Проверить `ps aux | grep <process>`, права доступа к `/proc` |
| **BFD-сессия не устанавливается** | Порт 3784/3785 заблокирован | Разрешить UDP 3784/3785 между узлами |
| **auth_hmac ошибка** | Разные версии Keepalived в кластере | Обновить все узлы до 2.4.1+ одновременно |
| **notify-скрипт не выполняется** | Неверные права или путь | Проверить права (750), владелец `root:keepalived_script` |

### См. также

- **[Обзор High Availability](../../Concepts/High_Availability/ha_overview.md)** — основы проектирования отказоустойчивых систем.
- **[Split-Brain и кворум](../../Databases/Concepts/replication.md#проблема-split-brain-и-кворум)** — детальный разбор рисков.
- **[Руководство по tcpdump](../../Linux/Diagnostics/Networking/tcpdump.md)** — отладка сетевых протоколов.
