# Keepalived — обзор и настройка высокой доступности (HA)

## Определения

**Keepalived** — системный демон для Linux, обеспечивающий высокую доступность (HA — High Availability) и отказоустойчивость через управление виртуальным IP-адресом (VIP) на базе протокола **VRRP (Virtual Router Redundancy Protocol)**.

**Актуальность (2025–2026):** Keepalived остается стандартом де-факто для обеспечения высокой доступности в bare-metal и VM-окружениях. Стабильная ветка 2.3.x+ поддерживает VRRPv3, нативную интеграцию с BFD (Bidirectional Forwarding Detection) для сверхбыстрого переключения, расширенные механизмы мониторинга процессов через `track_process` и интеграцию с SNMP/DBus.

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
6.  **Failback (Preemption):** По умолчанию, если оригинальный `MASTER` восстанавливается, он забирает роль обратно. Для предотвращения "флаппинга" (постоянных переключений) используют опцию `nopreempt`.

### Защита от Split-Brain

**Split-Brain** — ситуация, когда из-за проблем в сети узлы перестают видеть друг друга и оба становятся `MASTER`, вызывая конфликт IP и риск повреждения данных (особенно в БД).

#### Рекомендации по минимизации рисков:
- **Выделенный канал (Heartbeat Link):** Использование отдельного физического интерфейса или выделенного VLAN для трафика VRRP.
- **Режим Unicast (рекомендуется):** В отличие от Multicast, который часто блокируется в облаках или фильтруется коммутаторами, Unicast (`unicast_peer`) явно определяет адреса соседей.
- **Кворум:** Для кластеров 3+ узлов Keepalived поддерживает механизмы отслеживания кворума.
- **Безопасность:** В VRRPv3 аутентификация упразднена. Безопасность должна обеспечиваться на уровне L2 (Port Security) или через IPsec/Firewall.

### Версии VRRP и BFD

| Механизм | Описание |
| :--- | :--- |
| **VRRPv2** | Стандарт для IPv4 (RFC 3768). Целочисленные интервалы анонсов (секунды). |
| **VRRPv3** | Поддержка IPv4/IPv6 (RFC 5798), таймеры в миллисекундах (sub-second), отсутствие встроенной аутентификации. |
| **BFD** | Bidirectional Forwarding Detection. Позволяет Keepalived реагировать на разрыв связи за 50–100 мс, интегрируясь с демонами маршрутизации (например, FRR). |

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

## Практические сценарии

### Механизмы отслеживания (Tracking)

Keepalived динамически снижает приоритет узла (`weight`), если проверка не проходит:

1.  **vrrp_script**: Вызов внешнего скрипта. Код возврата `0` — успех.
2.  **track_process**: (с версии 2.0) Нативный мониторинг процесса (например, `nginx`, `haproxy`) без вызова shell. Это экономит ресурсы и быстрее реагирует на падение службы.
3.  **track_interface**: Мониторинг линка. Если интерфейс `eth1` упал, узел должен отдать роль мастера.
4.  **track_file**: Отслеживание состояния по содержимому файла.

**Пример скрипта проверки (`/etc/keepalived/check_haproxy.sh`):**
```bash
#!/bin/bash
# Проверка доступности локального эндпоинта статистики
if curl -sf http://localhost:8404/status > /dev/null 2>&1; then
    exit 0
fi
exit 1
```

### Пример конфигурации с VRRPv3 и track_process

Файл: `/etc/keepalived/keepalived.conf`

```keepalived
global_defs {
   router_id LB_NODE_1
   vrrp_garp_master_delay 5 # Задержка повторных GARP
   enable_snmp_vrrp         # Включить поддержку SNMP
}

# Нативный мониторинг процесса (без скрипта)
vrrp_track_process check_haproxy {
    process haproxy
    weight -20
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
}
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

### Диагностика

```bash
# Проверка наличия VIP (будет помечен как secondary)
ip addr show eth0
# → inet 192.168.1.100/24 scope global secondary eth0:vip

# Просмотр логов в реальном времени
journalctl -u keepalived -f

# Сброс текущей статистики в файл /tmp/keepalived.stats
kill -SIGUSR1 $(cat /var/run/keepalived.pid)

# Анализ VRRP-трафика
tcpdump -i eth0 -nn proto 112
```

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

### См. также
- **[Обзор High Availability](../../Concepts/High_Availability/ha_overview.md)** — основы проектирования отказоустойчивых систем.
- **[Split-Brain и кворум](](../../Databases/Concepts/replication.md#проблема-split-brain-и-кворум)** — детальный разбор рисков.
- **[Руководство по tcpdump](../../Linux/Diagnostics/Networking/tcpdump.md)** — отладка сетевых протоколов.
