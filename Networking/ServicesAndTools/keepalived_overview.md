# Keepalived — обзор и настройка высокой доступности (HA)

## Определения

**Keepalived** — системный демон для Linux, обеспечивающий высокую доступность (HA — High Availability) и отказоустойчивость через управление виртуальным IP-адресом (VIP) на базе протокола **VRRP (Virtual Router Redundancy Protocol)**.

**Актуальность (2025–2026):** Keepalived остается стандартом де-факто для обеспечения высокой доступности в bare-metal и VM-окружениях. Стабильная ветка 2.3.x поддерживает VRRPv3, интеграцию с BFD (Bidirectional Forwarding Detection) для сверхбыстрого переключения и расширенные механизмы мониторинга процессов.

**VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол (RFC 5798), позволяющий группе серверов совместно владеть виртуальным IP-адресом. Один узел становится `MASTER`, остальные — `BACKUP`.

**Виртуальный IP (Virtual IP, VIP / Floating IP)** — IP-адрес, не привязанный жёстко к одному физическому серверу. В рамках кластера он перемещается на активный узел (`MASTER`).

**Высокая доступность (HA)** vs **Отказоустойчивость (FT):**
- **HA (High Availability)** — минимизация времени простоя. При сбое допустим краткий перерыв (секунды) на переключение. Общие принципы — в **[обзоре High Availability](../../Concepts/High_Availability/ha_overview.md)**.
- **FT (Fault Tolerance)** — система продолжает работать без видимых перебоев. Пример — агрегация каналов (LACP), где трафик мгновенно перераспределяется при обрыве одной из линий.

## Основные концепции

### Принцип работы (Active-Passive)

1.  **Настройка:** На узлах устанавливается Keepalived. Одному назначается более высокий приоритет (`priority`). Плавающий IP **не должен** быть прописан статически в `/etc/network/interfaces` или `netplan`.
2.  **Heartbeat (VRRP advertisements):** `MASTER` периодически отправляет VRRP-сообщения (по умолчанию раз в секунду).
3.  **Ожидание:** `BACKUP` серверы слушают анонсы. Переключение инициируется, если сообщения отсутствуют в течение `3 * advert_int + skew_time`.
4.  **Failover:** Если мастер недоступен, бэкап с наивысшим приоритетом переходит в состояние `MASTER`.
5.  **Gratuitous ARP:** Новый `MASTER` отправляет GARP-запрос. Это критический этап: коммутаторы обновляют таблицу MAC-адресов, и трафик мгновенно направляется на новый физический порт.
6.  **Failback (Preemption):** По умолчанию, если оригинальный `MASTER` восстанавливается, он забирает роль обратно. Для предотвращения "флаппинга" (постоянных переключений) используют опцию `nopreempt`.

### Защита от Split-Brain

**Split-Brain** — ситуация, когда из-за проблем в сети узлы перестают видеть друг друга и оба становятся `MASTER`, вызывая конфликт IP и порчу данных.

#### Рекомендации по минимизации рисков:
- **Выделенный канал (Heartbeat Link):** Использование отдельного физического интерфейса или выделенного VLAN для трафика VRRP.
- **Режим Unicast (рекомендуется):** В отличие от Multicast (224.0.0.18), который часто блокируется в облаках или фильтруется коммутаторами, Unicast (`unicast_peer`) явно определяет адреса соседей. Это повышает безопасность и надежность.
- **Кворум:** Для кластеров 3+ узлов Keepalived поддерживает механизмы отслеживания кворума.
- **Безопасность:** В VRRPv3 аутентификация упразднена. Безопасность должна обеспечиваться на уровне L2 (порт-секьюрити) или через IPsec/Firewall.

### Версии VRRP и BFD

| Механизм | Описание |
| :--- | :--- |
| **VRRPv2** | Стандарт для IPv4. Целочисленные интервалы (секунды). |
| **VRRPv3** | Поддержка IPv4/IPv6, таймеры в миллисекундах, отсутствие встроенной аутентификации. |
| **BFD** | Двунаправленное обнаружение сбоев. Позволяет Keepalived реагировать на разрыв связи за 50–100 мс. |

### Сетевой экран

VRRP работает поверх IP (протокол **112**).

**firewalld:**
```bash
sudo firewall-cmd --add-protocol=vrrp --permanent
sudo firewall-cmd --reload
```

**iptables:**
```bash
# Разрешить VRRP от соседа 10.0.0.2
sudo iptables -A INPUT -p vrrp -s 10.0.0.2 -j ACCEPT
sudo iptables -A INPUT -p vrrp -j DROP
```

## Практические сценарии

### Механизмы отслеживания (Tracking)

1.  **vrrp_script**: Вызов внешнего скрипта. Код возврата `0` — успех, иначе — ошибка (снижение приоритета).
2.  **track_process**: (с версии 2.x) Нативный мониторинг процесса (например, `nginx`) без вызова shell.
3.  **track_interface**: Мониторинг линка (например, если упал внешний интерфейс, нужно отдать роль мастера).

**Пример скрипта проверки (`/etc/keepalived/check_haproxy.sh`):**
```bash
#!/bin/bash
# Проверка доступности локального эндпоинта
if curl -sf http://localhost:8404/status > /dev/null 2>&1; then
    exit 0
fi
exit 1
```

### Пример конфигурации (`keepalived.conf`)

```keepalived
global_defs {
   router_id LB_NODE_1
   vrrp_garp_master_delay 5 # Задержка повторных GARP
}

vrrp_script chk_haproxy {
   script "/etc/keepalived/check_haproxy.sh"
   interval 2
   weight -20 # Уменьшить приоритет на 20 при сбое
}

vrrp_instance VI_1 {
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
        192.168.1.100/24 dev eth0 label eth0:vip
    }

    track_script {
        chk_haproxy
    }
}
```

### Сценарии использования

- **HA для OpenSearch:** Плавающий VIP перед узлами. См. **[Отказоустойчивость OpenSearch с помощью Keepalived](../../ELK_Stack/OpenSearch/opensearch_high_availability_keepalived.md)**.
- **HA для балансировщика Kubernetes (Bare-metal):** VIP "плавает" между двумя HAProxy, обеспечивая единую точку входа для `kubectl` и Ingress.
- **HA для API-сервера Kubernetes:** Использование VIP для `kube-apiserver`. См. **[Настройка HA API-сервера](../../Kubernetes/Installation/kubeadm/ha_concepts.md)**.
- **HA для MySQL:** Переключение между мастером и репликой. См. **[Отказоустойчивость MySQL](../../Databases/MySQL/replication/multi-source.md#обеспечение-высокой-доступности-keepalived)**.

### Диагностика

```bash
# Проверка наличия VIP
ip addr show eth0
# → inet 192.168.1.100/24 scope global secondary eth0:vip

# Просмотр логов
journalctl -u keepalived -f

# Анализ VRRP-трафика
tcpdump -i eth0 -nn vrrp
```

## Дополнительная информация

### Тайминги failover

`failover_timeout = 3 × advert_int + skew_time`.

| `advert_int` | Время переключения | Сценарий |
|:---|:---|:---|
| 1 с | ~3 с | Стандарт (VRRPv2) |
| 0,3 с | ~0,9 с | Агрессивный VRRPv3 |
| BFD | < 0,1 с | Критичные финансовые/Real-time системы |

### Ограничение L2 и альтернативы

VIP **обязан** находиться в той же L2-подсети, что и реальные IP узлов. VRRP не маршрутизируется.
Если узлы в разных ЦОД (L3):
- Используйте **BGP (Anycast)**.
- Или **DNS-балансировку** (GSLB), учитывая задержки TTL.

### TLS на VIP: DNS-01 challenge

При использовании Let's Encrypt (HTTP-01) возникнет проблема: VIP есть только на одной ноде, а сертификат нужен обеим.
**Решение:** Использовать **DNS-01 challenge** через API DNS-провайдера. Это позволяет обеим нодам независимо получать и обновлять сертификаты. См. **[acme.sh](../../WebServers/Concepts/acme_sh.md)**.

### См. также
- **[Обзор High Availability](../../Concepts/High_Availability/ha_overview.md)** — основы проектирования.
- **[Split-Brain и кворум](](../../Databases/Concepts/replication.md#проблема-split-brain-и-кворум)** — разбор рисков.
- **[Руководство по tcpdump](../../Linux/Diagnostics/Networking/tcpdump.md)** — отладка VRRP.
