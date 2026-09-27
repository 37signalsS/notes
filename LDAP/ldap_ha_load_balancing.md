# LDAP: высокая доступность и балансировка нагрузки

## Определения

**High Availability (HA)** — архитектурный подход, обеспечивающий непрерывность работы LDAP-сервера за счёт устранения единственной точки отказа (Single Point of Failure, SPOF). Измеряется в процентах доступности (99.9% = 8.76 ч простоя/год, 99.99% = 52.6 мин/год).

**Active-Passive (Master-Standby)** — топология, в которой один LDAP-сервер обрабатывает все операции чтения и записи, а второй находится в режиме горячего резерва и синхронизирует данные через репликацию. При отказе активного сервера происходит автоматическое переключение (failover).

**Active-Active (Multi-Master)** — топология, в которой несколько LDAP-серверов одновременно обрабатывают операции. Все серверы принимают записи и реплицируют изменения между собой. Позволяет масштабировать пропускную способность чтения и записи.

**VIP (Virtual IP Address)** — виртуальный IP-адрес, который может мигрировать между узлами кластера. Клиенты подключаются к VIP, а механизм failover перемещает VIP на здоровый узел при отказе текущего.

**HAProxy** — высокопроизводительный TCP/HTTP-прокси-сервер и балансировщик нагрузки. Для LDAP используется в режиме `mode tcp` (Layer 4) для балансировки TCP-соединений на порту 389/636.

**keepalived** — демон, реализующий протокол VRRP (Virtual Router Redundancy Protocol) для организации отказоустойчивого VIP между двумя или более узлами.

**Health Check (Проверка работоспособности)** — периодическая проверка состояния LDAP-сервера. Для LDAP-серверов используется `ldapsearch` или `ldapwhoami` с bind от имени health-check учётной записи.

**Connection Draining (Слейка соединений)** — механизм плавного завершения существующих соединений перед выводом узла из балансировки (при плановом обслуживании).

---

## Базовые концепции

### Архитектура HA LDAP

```text
                          VIP (10.0.0.100)
                               │
                    ┌──────────┴──────────┐
                    │                     │
              ┌─────┴─────┐        ┌─────┴─────┐
              │  keepalived│        │  keepalived│
              │  (MASTER)  │        │ (BACKUP)   │
              └─────┬─────┘        └─────┬─────┘
                    │                     │
              ┌─────┴─────┐        ┌─────┴─────┐
              │  HAProxy   │        │  HAProxy   │
              │  (active)  │        │  (standby) │
              └─────┬─────┘        └─────┬─────┘
                    │                     │
           ┌────────┴────────┐   ┌───────┴────────┐
           │                 │   │                │
     ┌─────┴─────┐    ┌─────┴──┐│   ┌─────┴─────┐
     │  ldap-01   │    │ldap-02 ││   │  ldap-03   │
     │  (master)  │    │(replica)│   │  (replica) │
     └───────────┘    └────────┘   └───────────┘
```

### Сравнение топологий

| Топология | Пропускная способность | Сложность | Split-Brain | Рекомендация |
|:---|:---|:---|:---|:---|
| **Active-Passive** | Один сервер | Низкая | Нет | До 10k пользователей |
| **Active-Active (2 узла)** | 2x чтение, 1x запись | Средняя | Возможен | 10k–50k пользователей |
| **Active-Active (3+ узлов)** | Nx чтение, Nx запись | Высокая | Возможен | 50k+ пользователей |
| **Cascading Replication** | Масштабирование чтения | Средняя | Нет | Географическое разнесение |

### Выбор балансировщика

| Балансировщик | Тип | LDAP-поддержка | Failover | Рекомендация |
|:---|:---|:---|:---|:---|
| **HAProxy + keepalived** | L4 TCP | Health check через ldapwhoami | VIP через VRRP | Рекомендуется для bare-metal |
| **DNS Round-Robin** | L3 | DNS SRV записи | Клиентская выборка | Простой вариант, без health check |
| **硬件 LB (F5, Citrix)** | L4/L7 | Настройка monitors | Встроенный | Enterprise-среда |
| **Kubernetes Service** | L4 | Headless Service + StatefulSet | kube-proxy | K8s-среда |

---

## Практические сценарии

### 1. HAProxy + keepalived для LDAP (Active-Passive)

#### Шаг 1: Установка HAProxy на обоих узлах

```bash
# RHEL/Rocky/AlmaLinux
sudo dnf install haproxy keepalived -y

# Debian/Ubuntu
sudo apt install haproxy keepalived -y
```

#### Шаг 2: Конфигурация HAProxy (ldap-ha-01 и ldap-ha-02)

```bash
# /etc/haproxy/haproxy.cfg

global
    log /dev/log local0
    maxconn 4096
    daemon

defaults
    log     global
    mode    tcp
    option  tcplog
    timeout connect 5s
    timeout client  300s
    timeout server  300s
    retries 3

# Frontend: принимает клиентские соединения на VIP
frontend ldap_front
    bind *:389
    bind *:636 ssl crt /etc/haproxy/certs/ldap.pem
    default_backend ldap_servers

# Backend: LDAP-серверы
backend ldap_servers
    option tcp-check
    # Health check: bind от имени health-check DN
    tcp-check send-binary 300c020101610302010304008000
    tcp-check expect string errorResultSize

    server ldap-01 10.0.0.1:389 check inter 5s fall 3 rise 2
    server ldap-02 10.0.0.2:389 check inter 5s fall 3 rise 2 backup

# Statistics socket
listen stats
    bind 127.0.0.1:8404
    mode http
    stats enable
    stats uri /haproxy-stats
```

#### Шаг 3: Health check через ldapwhoami (альтернатива)

```bash
# Скрипт проверки работоспособности LDAP
#!/bin/bash
# /etc/haproxy/check_ldap.sh

LDAP_URI="ldap://10.0.0.1:389"
BIND_DN="cn=healthcheck,ou=services,dc=example,dc=com"
BIND_PW="HealthCheckPassword"

ldapwhoami -x -H "$LDAP_URI" \
  -D "$BIND_DN" -w "$BIND_PW" \
  -o timeout=3 > /dev/null 2>&1
exit $?
```

```bash
# В haproxy.cfg
backend ldap_servers
    option external-check
    external-check path "/usr/bin:/bin"
    external-check command /etc/haproxy/check_ldap.sh
    server ldap-01 10.0.0.1:389 check inter 5s fall 3 rise 2
    server ldap-02 10.0.0.2:389 check inter 5s fall 3 rise 2 backup
```

#### Шаг 4: Конфигурация keepalived

```bash
# /etc/keepalived/keepalived.conf (ldap-ha-01 — MASTER)

vrrp_script chk_haproxy {
    script "/usr/bin/killall -0 haproxy"
    interval 2
    weight -20
    fall 3
    rise 2
}

vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass LDAPSecret123
    }

    virtual_ipaddress {
        10.0.0.100/24 dev eth0
    }

    track_script {
        chk_haproxy
    }

    notify_master "/etc/keepalived/notify-master.sh"
    notify_backup "/etc/keepalived/notify-backup.sh"
    notify_fault  "/etc/keepalived/notify-fault.sh"
}
```

```bash
# /etc/keepalived/keepalived.conf (ldap-ha-02 — BACKUP)

vrrp_script chk_haproxy {
    script "/usr/bin/killall -0 haproxy"
    interval 2
    weight -20
    fall 3
    rise 2
}

vrrp_instance VI_1 {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass LDAPSecret123
    }

    virtual_ipaddress {
        10.0.0.100/24 dev eth0
    }

    track_script {
        chk_haproxy
    }
}
```

#### Шаг 5: Скрипты уведомлений

```bash
#!/bin/bash
# /etc/keepalived/notify-master.sh
echo "$(date) - LDAP HA: transition to MASTER" >> /var/log/ldap-ha.log
# Опционально: уведомление в Slack/PagerDuty
# curl -X POST -H 'Content-type: application/json' \
#   --data '{"text":"LDAP HA: node became MASTER"}' \
#   $SLACK_WEBHOOK_URL
```

```bash
#!/bin/bash
# /etc/keepalived/notify-backup.sh
echo "$(date) - LDAP HA: transition to BACKUP" >> /var/log/ldap-ha.log
```

```bash
#!/bin/bash
# /etc/keepalived/notify-fault.sh
echo "$(date) - LDAP HA: FAULT detected" >> /var/log/ldap-ha.log
# Критическое уведомление
```

#### Шаг 6: Запуск

```bash
# На обоих узлах
sudo systemctl enable --now haproxy keepalived

# Проверка VIP
ip addr show eth0 | grep 10.0.0.100

# Проверкаhaproxy stats
curl http://127.0.0.1:8404/haproxy-stats
```

### 2. DNS Round-Robin (простой LB без HAProxy)

```bash
# DNS Zone
ldap-ha  IN  A  10.0.0.1
ldap-ha  IN  A  10.0.0.2
ldap-ha  IN  A  10.0.0.3
ldap-ha  IN  SRV 0 0 389 ldap-01.example.com.
ldap-ha  IN  SRV 0 0 389 ldap-02.example.com.
ldap-ha  IN  SRV 0 0 389 ldap-03.example.com.
```

```bash
# /etc/sssd/sssd.conf — клиентские URI
[domain/example.com]
ldap_uri = ldaps://ldap-ha.example.com:636
# SSSD автоматически попробует все A-записи
```

**Ограничение:** DNS Round-Robin не имеет health check — если один сервер упадёт, часть запросов будет уходить на него до истечения TTL.

### 3. Multi-Master без внешнего LB (native replication)

Для 389DS и OpenLDAP multi-master клиенты подключаются ко всем мастерам напрямую:

```bash
# /etc/sssd/sssd.conf
[domain/example.com]
ldap_uri = ldaps://ldap-01.example.com:636, ldaps://ldap-02.example.com:636
ldap_backup_uri = ldaps://ldap-03.example.com:636
```

**Преимущества:** Нет дополнительного компонента (HAProxy).
**Недостатки:** Клиент отвечает за failover; при записи на обоих мастерах возможны конфликты.

### 4. Connection Draining для планового обслуживания

```bash
# Вывод узла из балансировки
# 1. Пометить сервер как backup (не принимает новые соединения)
# В haproxy.cfg: server ldap-01 10.0.0.1:389 check backup

# 2. Перезагрузить HAProxy
sudo systemctl reload haproxy

# 3. Дождаться завершения текущих соединений
watch -n 5 "ss -tnp | grep ':389' | wc -l"

# 4. Остановить slapd для обслуживания
sudo systemctl stop slapd

# 5. После обслуживания — вернуть в кластер
sudo systemctl start slapd
# Убрать backup из haproxy.cfg
sudo systemctl reload haproxy
```

### 5. Проверка HA-кластера

```bash
# Проверка доступности VIP
ldapwhoami -x -H ldap://10.0.0.100 -D "cn=admin,dc=example,dc=com" -W

# Имитация отказа мастер-сервера
sudo systemctl stop keepalived на ldap-01

# Проверка: VIP переключился на ldap-02
ip addr show eth0 | grep 10.0.0.100  # Должен отображаться на ldap-02

# Проверка: клиентские соединения работают
ldapwhoami -x -H ldap://10.0.0.100 -D "cn=admin,dc=example,dc=com" -W

# Восстановление
sudo systemctl start keepalived на ldap-01
```

---

## Дополнительная информация

### Метрики для мониторинга HA

| Метрика | Источник | Алерт |
|:---|:---|:---|
| `keepalived_state` | keepalived | Смена состояния MASTER/BACKUP |
| `haproxy_backend_active_servers` | haproxy stats | < 2 активных серверов |
| `haproxy_backend_errors_total` | haproxy stats | Рост ошибок |
| `ldap_replication_lag_seconds` | cn=monitor | > 60 секунд |
| `ldap_connections_current` | cn=monitor | > 80% от max |

### Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| Split-brain | Сетевой partition между узлами кластера | Настроить仲裁 (quorum), увеличить advert_int |
| VIP не мигрирует | keepalived не видит проблем с HAProxy | Проверьте track_script и权重 (weight) |
| Конфликты записи в multi-master | Одновременная модификация одной записи | Используйте CSN-разрешение конфликтов, или Master-Slave для записей |
| HAProxy health check fail | LDAP-сервер не отвечает health-check DN | Проверьте existence health-check DN в LDAP |

### Рекомендации по production

1. **Минимум 2 узла** для Active-Passive, минимум 3 для Active-Active (с кворумом)
2. **Выделенный VLAN** для репликации между LDAP-серверами
3. **NTP** — обязательная синхронизация, иначе CSN-конфликты репликации
4. **Разные физические узлы** — HAProxy и keepalived на одном сервере с LDAP не дают защиты от аппаратного сбоя
5. **Мониторинг VIP** — алерт на потерю VIP или смену keepalived state

### См. также

- **[LDAP: основы протокола](./ldap_fundamentals.md)** — терминология и архитектура
- **[389DS: Репликация](./389ds/replication.md)** — Multi-Master, RUV, CleanAllRUV
- **[OpenLDAP в Kubernetes](./openldap_kubernetes.md)** — HA в контейнерной среде
- **[LDAP Мониторинг](./ldap_monitoring.md)** — метрики и алерты
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
- **[LDAP + SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/configuration.md)** — клиентский failover через ldap_uri
- **[LDAP Backup и Restore](./ldap_backup_restore.md)** — стратегии бэкапов
