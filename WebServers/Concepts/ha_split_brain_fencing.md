# HA веб-серверов: split-brain, fencing, keepalived, VRRP

## Определения

**HA (High Availability)** — отказоустойчивость, при котором сервис продолжает работать при отказе одного или нескольких компонентов.

**VIP (Virtual IP Address)** — виртуальный IP-адрес, который мигрирует между узлами кластера. Клиенты подключаются к VIP, а не к физическим IP.

**VRRP (Virtual Router Redundancy Protocol)** — протокол (RFC 3768) для организации отказоустойчивого VIP между несколькими узлами. Реализуется через keepalived.

**Keepalived** — демон, реализующий VRRP для миграции VIP между узлами. Мониторит состояние узлов и переключает VIP при отказе.

**Split-brain (Два головы)** — ситуация, при которой оба узла кластера считают себя активным (MASTER) и владеют VIP одновременно. Возникает из-за потери связности между узлами.

**Fencing (Ограждение)** — механизм принудительного отключения отказавшего узла из кластера, чтобы предотвратить split-brain. Реализуется через STONITH (Shoot The Other Node In The Head).

**STONITH** — тип fencing, при котором отказной узел физически отключается (перезагрузка, выключение, изоляция сети).

**Arbitrator (Арбитр)** — третий узел или сервис, который голосует за один из узлов при split-brain, предотвращая двойное лидерство.

## Основные концепции

### Состояния VRRP

| Состояние | Описание |
| :--- | :--- |
| **MASTER** | Активный узел, владеющий VIP |
| **BACKUP** | Резервный узел, ожидающий failover |
| **FAULT** | Узел не может выполнять обязанности (сеть упала) |

### Приоритеты VRRP

| Приоритет | Роль |
| :--- | :--- |
| **255** | Автоматический MASTER (если нет другого узла с 255) |
| **254** | Резервный с высоким приоритетом |
| **100** | Резервный (по умолчанию) |
| **0** | Отказной узел, не участвует в выборах |

### Алгоритм выбора MASTER

1. Узел с highest priority становится MASTER.
2. При равенстве приоритетов побеждает узел с higher IP.
3. MASTER отправляет VRRP advertisement каждые `advert_int` секунд.
4. Если BACKUP не получает advertisement за `3 × advert_int`, он становится MASTER.

### Типы fencing

| Тип | Механизм | Инструмент |
| :--- | :--- | :--- |
| **STONITH** | Перезагрузка/выключение отказавшего узла | `ipmitool`, `ilo`, `virsh destroy` |
| **Network fencing** | Изоляция узла от сети | `iptables`, `ebtables`, `vconfig` |
| **Storage fencing** | Отключение доступа к разделяему хранилищу | `lvm`, `mdadm`, `multipath` |
| **Application fencing** | Принудительный останов сервиса на отказавшем узле | `systemctl stop`, `kill` |

## Практические сценарии

### Сценарий 1: Два узла Nginx за keepalived

Базовый шаблон: MASTER с priority 150, BACKUP с priority 100, `track_script` проверяет `systemctl is-active nginx`. Полные рабочие конфигурации и валидация см. в готовых файлах:
- **[HA Traefik](../Traefik/traefik-high-availability.md)** — сценарий с двумя репликами за keepalived.
- **[Disaster Recovery Traefik](../Traefik/traefik-disaster-recovery.md)** — проверка failover и RTO.

### Сценарий 2: Третий узел-арбитр

Добавьте третий узел с `priority 50` и `state BACKUP`. При split-brain арбитр голосует за узел с higher priority. Подробности и отладка (`keepalived -D`) — в **[keepalived overview](../../Networking/ServicesAndTools/keepalived_overview.md)**.

### Сценарий 3: Unicast для предотвращения split-brain

Используйте `unicast_src_ip` и `unicast_peer` вместо multicast. Проверка: `tcpdump -i eth0 vrrp` — advertisement идут только между узлами. Пример конфигурации — в **[VRRP/HSRP/GLBP](../../Networking/Protocols/vrrp_hsrp_glbp.md)**.

### Сценарий 4: Fencing через STONITH

Используйте `notify_fault` для принудительного отключения отказавшего узла. Пример: `ip link set eth0 down` имитирует потерю сети, узел перезагружается. Полный сценарий — в **[HA Traefik](../Traefik/traefik-high-availability.md)**.

## Лучшие практики

1. **Unicast вместо multicast:** multicast может блокироваться firewall'ом. Используйте unicast для надёжности.
2. **Фиксированные приоритеты:** MASTER = 150, BACKUP = 100, ARBITER = 50. Никогда не используйте auto.
3. **Authentication:** всегда используйте `auth_type PASS` или `AH` (V3) для VRRP.
4. **Track script:** мониторьте не только сеть, но и состояние Nginx/Apache.
5. **Preemption:** включите `nopreempt` только если MASTER не должен возвращаться автоматически.
6. **Fencing:** настройте notify scripts для принудительного отключения отказавшего узла.
7. **L2-segment:** узлы VRRP должны быть в одном L2-сегменте. Раздельные сети управления и VIP-интерфейс не работают.
8. **Monitoring:** экспортируйте состояние keepalived в Prometheus (`keepalived_state`).

## Граничные случаи и ограничения

1. **Split-brain при partition:** если оба узла не видят друг друга, оба считают себя MASTER. Fencing и arbiter решают эту проблему.
2. **Multicast блокировка:** в облачных окружениях multicast часто блокируется. Используйте unicast.
3. **VRRPv3 и AH:** VRRPv3 поддерживает HMAC-Auth (RFC 5798). Используйте вместо plain PASS.
4. **Network partition:** при разделении сети арбитр решает, какой узел остаётся MASTER.
5. **Keepalived не реплицирует конфиг:** конфигурация должна быть идентичной на всех узлах. Используйте Ansible/Puppet.

## Дополнительная информация

- **[HA Traefik](../Traefik/traefik-high-availability.md)** — keepalived, rolling update.
- **[Disaster Recovery Traefik](../Traefik/traefik-disaster-recovery.md)** — RTO, RPO, keepalived.
- **[keepalived overview](../../Networking/ServicesAndTools/keepalived_overview.md)** — общая конфигурация.
- **[VRRP/HSRP/GLBP](../../Networking/Protocols/vrrp_hsrp_glbp.md)** — протоколы резервирования.
