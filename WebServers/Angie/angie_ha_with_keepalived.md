# Настройка отказоустойчивого кластера Angie с Keepalived (VRRP)

## Определения

- **HA (High Availability — высокая доступность):** архитектурный подход, обеспечивающий минимальное время простоя сервиса за счет дублирования компонентов. Подробности — в **[обзоре High Availability](../../Concepts/High_Availability/ha_overview.md)**.
- **Angie:** современный веб-сервер, форк Nginx с расширенными возможностями. Подробнее в **[общем обзоре Angie](./angie_overview.md)**.
- **Keepalived:** сервис для управления виртуальным IP-адресом (VIP) на базе протокола VRRP. Является стандартом для Linux-окружений. В 2026 году рекомендуется использовать версию 2.x с поддержкой BFD. Детали в **[обзоре Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)**.
- **VRRP (Virtual Router Redundancy Protocol):** сетевой протокол, позволяющий группе серверов совместно владеть одним виртуальным IP-адресом.
- **BFD (Bidirectional Forwarding Detection):** протокол быстрого обнаружения разрыва сетевого соединения (время реакции — от 100 мс).
- **VIP (Virtual IP — виртуальный IP-адрес):** плавающий адрес, который назначается активному узлу (`MASTER`) и мигрирует на резервный (`BACKUP`) при сбое.
- **Active-Passive:** архитектурная модель, при которой один узел обрабатывает нагрузку, а второй находится в горячем резерве.
- **Failover:** автоматическое переключение на резервный узел при отказе активного.
- **Failback:** возврат роли `MASTER` на восстановившийся узел.
- **Split-Brain:** состояние, при котором оба узла считают себя активными из-за потери связи.
- **Gratuitous ARP (GARP):** broadcast-запрос, с помощью которого новый `MASTER` обновляет ARP-таблицы коммутаторов.
- **RTO (Recovery Time Objective):** максимальное допустимое время простоя сервиса.
- **RPO (Recovery Point Objective):** максимально допустимая потеря данных при сбое.

## Основные концепции

### Принцип работы кластера

Кластер состоит из двух или более узлов с установленными Angie и Keepalived.

1.  **Роли и приоритеты:** Один узел назначается `MASTER` (высокий приоритет), остальные — `BACKUP`.
2.  **Обмен состоянием (Advertisements):** `MASTER` периодически отправляет VRRP-пакеты. Если `BACKUP` не получает анонсы в течение заданного времени, он инициирует перехват роли.
3.  **Мониторинг (Health Checks):**
    - **BFD (Fast Failover):** мгновенное обнаружение падения соседа (failover < 1 сек).
    - **vrrp_script:** выполнение внешнего скрипта (проверка порта или API).
    - **track_process:** встроенный мониторинг состояния процесса `angie` (эффективнее скриптов).
4.  **Переключение (Failover):** При сбое VIP перемещается на исправный сервер. Для обновления таблиц коммутаторов используется **Gratuitous ARP**.
5.  **Режимы вещания:**
    - **Multicast:** классический режим (224.0.0.18), может блокироваться в облаках.
    - **Unicast:** прямая передача пакетов между IP узлов (рекомендуется для публичных облаков и защиты от split-brain).

### RTO и RPO для Angie + Keepalived

Для кластера Angie с Keepalived характерны следующие показатели:

- **RTO:** 1–3 секунды (при использовании BFD — < 1 секунды). Это время включает обнаружение сбоя, переключение VRRP и применение GARP.
- **RPO:** ≈ 0 для статической конфигурации. При использовании `angie-ha-sync` или shared storage данные синхронизируются предварительно, поэтому резервный узел имеет актуальную конфигурацию.

### Жизненный цикл соединения

1.  Клиент отправляет запрос на VIP.
2.  Активный узел (`MASTER`) принимает запрос и обрабатывает его через Angie.
3.  При падении Angie или узла Keepalived снижает приоритет.
4.  Резервный узел (`BACKUP`) получает более высокий приоритет и переходит в `MASTER`.
5.  Новый `MASTER` отправляет GARP-пакеты для обновления ARP-таблиц.
6.  Трафик перенаправляется на новый узел.

### Механизмы отслеживания (Tracking)

Keepalived динамически снижает приоритет узла (`weight`), если проверка не проходит:

1.  **vrrp_script**: Вызов внешнего скрипта. Код возврата `0` — успех.
2.  **track_process**: (с версии 2.0) Нативный мониторинг процесса (например, `angie`) без вызова shell. Это экономит ресурсы и быстрее реагирует на падение службы.
3.  **track_interface**: Мониторинг линка. Если интерфейс `eth1` упал, узел должен отдать роль мастера.
4.  **track_file**: Отслеживание состояния по содержимому файла (с версии 2.0). Файл отслеживается через `inotify`.
5.  **track_bfd**: Отслеживание сессии BFD. Если BFD-сессия падает, приоритет снижается.

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
```

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

### Защита от Split-Brain

**Split-Brain** — состояние, при котором из-за проблем в сети узлы перестают видеть друг друга и оба становятся `MASTER`, вызывая конфликт IP.
**Методы защиты в 2026 году:**
- **Unicast Mode:** использование прямой адресации партнеров исключает влияние стороннего VRRP-трафика в сегменте.
- **Quorum Script:** использование `vrrp_script` для проверки связи с внешним шлюзом (например, `ping` шлюза провайдера). Если связи нет — узел переходит в состояние `FAULT`.
- **Witness Node:** использование третьего легковесного узла (арбитра) для подтверждения статуса MASTER.
- **auth_hmac:** HMAC-SHA256 подпись VRRP-анонсов (Keepalived 2.4.0+) защищает от spoofing и replay-атак в unicast-деплоях.

### Системные требования

Для корректной работы VIP и Angie необходимо разрешить привязку IP-адресов, которые еще не назначены интерфейсу (нелокальные адреса):

```bash
echo "net.ipv4.ip_nonlocal_bind=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

## Практические сценарии

### Сценарий 1: Базовая конфигурация Active-Passive

#### Шаг 1: Подготовка инфраструктуры

Схема для примера (L2-сегмент):
- `node1` (Master): `192.168.1.101`
- `node2` (Backup): `192.168.1.102`
- Виртуальный IP (VIP): `192.168.1.100`

Установка ПО:
```bash
sudo apt update && sudo apt install keepalived angie-ha-sync curl -y
```

#### Шаг 2: Настройка Angie (Health Check & API)

На обоих серверах настройте блок для проверки состояния. В 2026 году рекомендуется использовать REST API для более точной диагностики.

```nginx
server {
    listen 127.0.0.1:80;
    
    # Традиционный эндпоинт (Вариант А)
    location /health_check {
        allow 127.0.0.1;
        deny all;
        return 200 "OK";
        access_log off;
    }

    # REST API Angie (Вариант Б — рекомендуется)
    location /api/ {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }
}
```

#### Шаг 3: Конфигурация Keepalived

##### Вариант А: Проверка через скрипт (`vrrp_script`)

Создайте `/etc/keepalived/check_angie.sh`:
```bash
#!/bin/bash
# Проверка доступности локального эндпоинта
if curl -sf http://127.0.0.1/health_check > /dev/null 2>&1; then
  exit 0
else
  exit 1
fi
```
`chmod +x /etc/keepalived/check_angie.sh`

##### Вариант Б: Продвинутая настройка (BFD + API + Process)

Файл: `/etc/keepalived/keepalived.conf` (для MASTER)

```keepalived
global_defs {
   router_id angie_node_1
   enable_script_security
   script_user root
   vrrp_garp_master_delay 5
}

# Настройка BFD для сверхбыстрого обнаружения отказа (100мс * 3)
bfd_instance angie_bfd {
    neighbor_ip 192.168.1.102
    source_ip 192.168.1.101
    interval 100
    multiplier 3
}

# Проверка готовности через REST API Angie
vrrp_script chk_angie_api {
    script "/usr/bin/curl -sf http://127.0.0.1/api/status/ | grep -q '\"ready\":true'"
    interval 2
    weight -20  # Снижаем приоритет при провале
}

vrrp_instance VI_1 {
    state MASTER
    interface enp1s0
    virtual_router_id 51
    priority 105
    advert_int 1

    # Режим Unicast (обязательно для защиты от split-brain)
    unicast_src_ip 192.168.1.101
    unicast_peer {
        192.168.1.102
    }

    authentication {
        auth_type PASS
        auth_pass Secr3t12    # Максимум 8 символов (VRRPv2)
    }

    virtual_ipaddress {
        192.168.1.100/24 dev enp1s0 label enp1s0:vip
    }

    # Комбинированный мониторинг (BFD + API + Процесс)
    track_bfd {
        angie_bfd weight 30
    }
    
    track_script {
        chk_angie_api
    }

    track_process {
        nm_angie {
            process angie
            weight 10
        }
    }
}
```

##### Конфигурация BACKUP

Отличия: `priority 100`, `unicast_src_ip` и `unicast_peer`.

#### Шаг 4: Синхронизация данных и конфигураций

Keepalived перемещает только IP. В 2026 году для Angie рекомендуется:
1.  **`angie-ha-sync`**: официальный инструмент для синхронизации `/etc/angie/` между узлами.
    - Установите пакет: `apt install angie-ha-sync`.
    - Настройте SSH-ключи между узлами.
    - Демон отслеживает изменения и делает `reload` на втором узле только после `angie -t`.
2.  **Shared Storage**: NFS или Ceph для контента (статические файлы).
3.  **Ansible/Terraform**: предпочтительный метод для управления конфигурацией в production.

#### Шаг 5: Сетевой экран (Firewall)

Необходимо разрешить VRRP и BFD трафик.

**ufw:**
```bash
# VRRP (протокол 112)
sudo ufw allow in proto vrrp
# BFD (UDP 3784)
sudo ufw allow in proto udp from 192.168.1.0/24 to any port 3784
```

#### Шаг 6: Диагностика

1.  **Проверка VIP:**
    ```bash
    ip addr show enp1s0 | grep vip
    # → inet 192.168.1.100/24 scope global secondary enp1s0:vip
    ```
2.  **Логи и статус BFD:**
    ```bash
    journalctl -u keepalived -f
    keepalived --status
    ```
3.  **Тест переключения:**
    Остановите Angie на мастере (`systemctl stop angie`) и убедитесь, что VIP мигрировал на backup менее чем за 1 секунду.

### Сценарий 2: Multi-VIP с vrrp_sync_group

При наличии нескольких VIP на разных интерфейсах (например, отдельный VIP для HTTP и HTTPS, или VIP для разных VLAN) используйте `vrrp_sync_group` для синхронного переключения.

```keepalived
vrrp_sync_group VG_WEB {
    group {
        VI_HTTP
        VI_HTTPS
    }
    notify_master "/etc/keepalived/notify_master.sh"
    notify_backup "/etc/keepalived/notify_backup.sh"
}

vrrp_instance VI_HTTP {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 105
    advert_int 1
    unicast_src_ip 192.168.1.101
    unicast_peer { 192.168.1.102 }
    virtual_ipaddress {
        192.168.1.100/24 dev eth0 label eth0:vip-http
    }
    track_process { nm_angie { process angie; weight 10; } }
}

vrrp_instance VI_HTTPS {
    state MASTER
    interface eth0
    virtual_router_id 52
    priority 105
    advert_int 1
    unicast_src_ip 192.168.1.101
    unicast_peer { 192.168.1.102 }
    virtual_ipaddress {
        192.168.1.200/24 dev eth0 label eth0:vip-https
    }
    track_process { nm_angie { process angie; weight 10; } }
}
```

**Валидация:**
```bash
# Проверка что оба VIP на master
ip addr show eth0 | grep vip
# → inet 192.168.1.100/24 scope global secondary eth0:vip-http
# → inet 192.168.1.200/24 scope global secondary eth0:vip-https

# Остановка Angie — оба VIP должны мигрировать одновременно
sudo systemctl stop angie
ip addr show eth0 | grep vip
# → VIP исчезли с master
```

### Сценарий 3: L7 Health Checks через REST API Angie

Вместо простого `curl` используйте встроенный REST API Angie для проверки состояния бэкендов и готовности сервера.

```nginx
server {
    listen 127.0.0.1:8080;
    
    location /api/status/ {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }

    location /api/http/upstreams/ {
        api /http/upstreams/;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Настройка Keepalived с проверкой API:**
```keepalived
vrrp_script chk_angie_api {
    script "/usr/bin/curl -sf http://127.0.0.1:8080/api/status/ | grep -q '\"ready\":true'"
    interval 2
    weight -20
    timeout 5
    fall 2
    rise 2
}
```

**Преимущества:**
- Проверяет не только процесс Angie, но и состояние upstream-серверов.
- Можно проверять конкретные эндпоинты (`/api/http/upstreams/app_servers/`).
- Возвращает детальную информацию о состоянии бэкендов.

### Сценарий 4: ACME + Keepalived (DNS-01 Challenge)

При использовании Let's Encrypt HTTP-01 проверка может провалиться на `BACKUP` узле, так как VIP (и трафик) находится на `MASTER`. Используйте DNS-01 challenge.

```nginx
server {
    listen 127.0.0.1:8080;
    
    location /api/acme/ {
        api /acme/;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Проверка через API:**
```bash
# Проверка статуса ACME
curl -s http://127.0.0.1:8080/api/acme/ | jq .
# → {"certificates":[{"domain":"example.com","status":"issued",...}]}

# Принудительное обновление сертификата
curl -X POST http://127.0.0.1:8080/api/acme/renew
```

**Синхронизация сертификатов:**
- Синхронизируйте `/var/lib/angie/acme/` между узлами через `angie-ha-sync` или shared storage.
- Оба узла должны иметь возможность получать сертификаты независимо.

### Сценарий 5: Ansible автоматизация конфигурации

Для управления конфигурацией в production используйте Ansible:

```yaml
# tasks/main.yml
- name: Install keepalived and angie-ha-sync
  apt:
    name:
      - keepalived
      - angie-ha-sync
      - curl
    state: present

- name: Deploy keepalived.conf
  template:
    src: keepalived.conf.j2
    dest: /etc/keepalived/keepalived.conf
    mode: '0644'
  notify: reload keepalived

- name: Deploy check_angie.sh
  template:
    src: check_angie.sh.j2
    dest: /etc/keepalived/check_angie.sh
    mode: '0755'

- name: Enable and start keepalived
  systemd:
    name: keepalived
    state: started
    enabled: yes
```

**Шаблон `keepalived.conf.j2`:**
```keepalived
global_defs {
   router_id {{ inventory_hostname }}
   enable_script_security
   script_user root
}

bfd_instance angie_bfd {
    neighbor_ip {{ keepalived_peer }}
    source_ip {{ ansible_host }}
    interval 100
    multiplier 3
}

vrrp_script chk_angie_api {
    script "/usr/bin/curl -sf http://127.0.0.1:8080/api/status/ | grep -q '\"ready\":true'"
    interval 2
    weight -20
}

vrrp_instance VI_1 {
    state {{ keepalived_state }}
    interface {{ ansible_default_ipv4.interface }}
    virtual_router_id 51
    priority {{ keepalived_priority }}
    advert_int 1
    unicast_src_ip {{ ansible_host }}
    unicast_peer { {{ keepalived_peer }} }
    authentication {
        auth_type PASS
        auth_pass {{ keepalived_auth_pass }}
    }
    virtual_ipaddress {
        {{ keepalived_vip }}/24 dev {{ ansible_default_ipv4.interface }}
    }
    track_bfd { angie_bfd weight 30 }
    track_script { chk_angie_api }
    track_process {
        nm_angie { process angie; weight 10; }
    }
}
```

### Сценарий 6: Тестирование failover

Автоматизированный тест переключения:

```bash
#!/bin/bash
# test_failover.sh
MASTER_IP="192.168.1.101"
BACKUP_IP="192.168.1.102"
VIP="192.168.1.100"

echo "1. Проверка VIP на master..."
ping -c 1 -W 1 $VIP
# → 1 packets transmitted, 1 received, 0% packet loss

echo "2. Имтация отказа Angie..."
ssh root@$MASTER_IP "systemctl stop angie"
sleep 2

echo "3. Проверка миграции VIP..."
ping -c 1 -W 1 $VIP
# → 1 packets transmitted, 1 received, 0% packet loss

echo "4. Проверка что VIP на backup..."
ssh root@$BACKUP_IP "ip addr show | grep $VIP"
# → inet 192.168.1.100/24 scope global secondary eth0:vip

echo "5. Проверка работоспособности через VIP..."
curl -s http://$VIP/health_check
# → OK

echo "6. Восстановление..."
ssh root@$MASTER_IP "systemctl start angie"
sleep 5

echo "Failover тест пройден"
```

### Сценарий 7: Кластерная синхронизация состояния (zone_sync)

Keepalived отвечает за **передвижение VIP**, но по умолчанию состояние Angie (лимиты `limit_req`/`limit_conn`, sticky-сессии, динамические upstream-зоны) живёт **в памяти каждого узла отдельно**. После failover новый master начинает с «пустого» состояния — rate limits не помнят нарушителей, а sticky-привязки теряются. Для согласованного состояния между нодами используется модуль `zone_sync` в блоке `stream` (доступен в сборках с поддержкой; для production-кластера требуется PRO-версия).

```nginx
# /etc/angie/angie.conf — блок stream (на каждом узле кластера)
stream {
    zone_sync;

    server {
        listen 10.0.0.1:9000;             # локальный IP узла — порт обмена состоянием
        zone_sync_server 10.0.0.1:9000;   # соседи кластера
        zone_sync_server 10.0.0.2:9000;
    }
}
```

На втором узле блок `server` слушает на `10.0.0.2:9000` и направляет `zone_sync_server` на оба адреса. Каждый узел должен знать всех соседей по приватной сети. После этого синхронизируются зоны разделяемой памяти, объявленные с параметром `sync`:

```nginx
http {
    # Ограничение частоты — общий счётчик на кластер
    limit_req_zone $binary_remote_addr zone=api_limit:64k rate=10r/s sync;

    # Sticky-сессии с синхронизацией между нодами
    upstream app {
        zone app 64k;
        sticky learn create=1h lookup=1h zone=app_sticky:64k sync;
        server 10.0.0.21:8080;
        server 10.0.0.22:8080;
    }
}
```

**Что именно даёт `sync`:**

*   **Глобальные rate limits** — нарушитель, исчерпавший `burst` на node1, не «получит прощение» на node2 после failover.
*   **Sticky-привязки** — клиент после переключения ноды продолжит попадать на свой бэкенд.
*   **Динамические upstream-зоны** (при `zone` + `sync`) — согласованный состав группы на всех нодах.

**Ограничения:**

*   `zone_sync` требует дополнительный TCP-порт (например, 9000) — откройте его в firewall только для адресов кластера.
*   Трафик синхронизации должен проходить между нодами по приватной сети; включите TLS (`zone_sync_ssl`), если сеть не изолирована.
*   При изменении конфигурации на одном узле не забывайте синхронизировать файлы конфигов между нодами (см. [Сценарий 5: Ansible автоматизация](#5-ansible-автоматизация-конфигурации) и `angie-ha-sync`).

**Проверка:**

```bash
# Порты zone_sync слушаются на обоих узлах
ss -tlnp | grep 9000
# → LISTEN 0 128 10.0.0.1:9000 ... angie

# В логах Angie должны появляться события синхронизации без ошибок
journalctl -u angie --since "10 min ago" | grep -i zsync
# → [info] ... zone_sync: connected to 10.0.0.2:9000

# После failover на backup: счетчик limit_req сохранен (эффект sync)
curl -s http://127.0.0.1:8888/status/http/limit_conns/perip | jq '.keys'
```

Подробная конфигурация `sync` для лимитов в контексте защиты от атак — [Защита от DoS в Angie: Cluster Zone Sync](./High_Load/dos_protection.md).

## Операции и команды

### Управление Keepalived

```bash
# Проверка статуса
sudo systemctl status keepalived
# → Active: active (running) since Mon 2026-09-21 10:00:00 UTC; 2h ago

# Запуск и включение автозагрузки
sudo systemctl enable --now keepalived

# Перезагрузка конфигурации
sudo systemctl reload keepalived

# Просмотр логов в реальном времени
sudo journalctl -u keepalived -f
```

### Управление Angie

```bash
# Проверка конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok

# Применение конфигурации (graceful reload)
sudo systemctl reload angie

# Проверка статуса
sudo systemctl status angie
# → Active: active (running) since ...
```

### Управление VIP и VRRP

```bash
# Проверка наличия VIP
ip addr show enp1s0 | grep vip
# → inet 192.168.1.100/24 scope global secondary enp1s0:vip

# Ручное отключение инстанса (для тестирования)
sudo systemctl stop keepalived

# Просмотр текущего состояния VRRP-экземпляров
keepalived --show-config

# Просмотр статистики (счётчики переходов)
keepalived --dump

# Сброс текущей статистики в файл /tmp/keepalived.stats
kill -SIGUSR1 $(cat /var/run/keepalived.pid)

# Проверка версии и доступных опций
keepalived -v
# → Keepalived v2.4.0 (07/19/2026)

# Анализ VRRP-трафика
tcpdump -i enp1s0 -nn proto 112
```

### Управление BFD

```bash
# Проверка BFD-сессий
tcpdump -i enp1s0 -nn port 3784 or port 3785
# → IP 192.168.1.101.3784 > 192.168.1.102.3784: BFDv1, State Up, Flags: none

# Проверка статуса BFD в keepalived
keepalived --status
```

### Управление angie-ha-sync

```bash
# Проверка статуса сервиса
sudo systemctl status angie-ha-sync
# → Active: active (running) since ...

# Просмотр логов
sudo journalctl -u angie-ha-sync -f
# → [INFO] Synchronized /etc/angie/conf.d/default.conf to node2

# Принудительная синхронизация
sudo angie-ha-sync --force
```

### Управление уведомлениями

```bash
# Тест notify-скрипта вручную
sudo /etc/keepalived/notify_master.sh INSTANCE VI_1 MASTER 105
# → должен отправить алерт/обновить DNS

# Проверка прав на скрипты
ls -la /etc/keepalived/notify_*.sh
# → -rwxr-x--- 1 root keepalived_script ... notify_master.sh
```

## Устранение неисправностей

### VIP не перемещается при падении MASTER

**Симптомы:** После остановки Angie/Keepalived на мастере VIP остается на нем, или backup не поднимает VIP.

**Диагностика:**
```bash
# 1. Проверка что VRRP работает
sudo tcpdump -i enp1s0 -nn proto 112
# → Должны быть видны VRRP-пакеты между узлами

# 2. Проверка логов Keepalived
sudo journalctl -u keepalived -f
# → Переходы MASTER/BACKUP/FAULT

# 3. Проверка firewall
sudo iptables -L -n | grep vrrp
# → Должен быть ACCEPT для протокола 112

# 4. Проверка sysctl
sysctl net.ipv4.ip_nonlocal_bind
# → net.ipv4.ip_nonlocal_bind = 1
```

**Решение:**
*   Убедитесь что `virtual_router_id` одинаковый на обеих нодах.
*   Убедитесь что `unicast_peer` содержит правильные IP соседей.
*   Проверьте что `priority` на backup ниже, чем на master.
*   Проверьте что интерфейс указан верно (`interface enp1s0`).

### Флаппинг VIP (частое переключение)

**Симптомы:** VIP постоянно переключается между узлами без видимой причины.

**Диагностика:**
```bash
sudo journalctl -u keepalived | grep -E "MASTER|BACKUP|FAULT"
# → Частые переходы
```

**Решение:**
*   Увеличьте `advert_int` до 1 секунды (или выше).
*   Используйте `nopreempt` на обоих узлах для предотвращения автоматического возврата.
*   Увеличьте `multiplier` в BFD.
*   Проверьте стабильность сети (потерю пакетов через `mtr`).

### BFD-сессия не устанавливается

**Симптомы:** В логах `BFD session not established` или `peer down`.

**Диагностика:**
```bash
# Проверка доступности порта 3784
sudo nc -zvu 192.168.1.102 3784
# → Connection succeeded

# Проверка firewall
sudo iptables -L -n | grep 3784
```

**Решение:**
*   Разрешите UDP 3784/3785 между узлами в firewall.
*   Убедитесь что `source_ip` и `neighbor_ip` указаны верно.
*   Проверьте что `interval` и `multiplier` совместимы на обеих сторонах.

### Angie не проходит health check

**Симптомы:** Keepalived считает Angie нерабочим, хотя сервис доступен.

**Диагностика:**
```bash
# Проверка эндпоинта вручную
curl -v http://127.0.0.1/health_check
# → HTTP/1.1 200 OK

# Проверка что скрипт работает
sudo /etc/keepalived/check_angie.sh
echo $?
# → 0
```

**Решение:**
*   Убедитесь что `script` в `vrrp_script` указывает на правильный путь.
*   Проверьте что пользователь `keepalived` имеет права на выполнение скрипта.
*   Проверьте `enable_script_security` и `script_user` в `global_defs`.

### angie-ha-sync не синхронизирует конфигурацию

**Симптомы:** После изменения конфигурации на мастере бэкап не обновляется.

**Диагностика:**
```bash
# Проверка SSH-ключа
ssh root@192.168.1.102 "echo OK"
# → OK

# Проверка прав на директорию
ls -la /etc/angie/
# → angie:angie права

# Просмотр логов
sudo journalctl -u angie-ha-sync -f
```

**Решение:**
*   Настройте SSH-ключи без пароля между узлами.
*   Убедитесь что пользователь `angie` имеет права на запись в `/etc/angie/` на обоих узлах.
*   Проверьте что `angie-ha-sync` запущен на обоих узлах.

### VIP дублируется на обоих узлах (Split-Brain)

**Симптомы:** На обоих узлах отображается один и тот же VIP.

**Диагностика:**
```bash
# Проверка что узел видит соседа
sudo tcpdump -i enp1s0 -nn proto 112
# → Должны быть двусторонние VRRP-пакеты

# Проверка priority
sudo keepalived --show-config | grep priority
```

**Решение:**
*   Используйте `unicast_peer` вместо multicast.
*   Настройте `auth_hmac` для защиты от spoofing.
*   Используйте `track_bfd` для быстрого обнаружения потери связи.
*   Добавьте третий узел (Witness) для кворума.

## Лучшие практики

### Безопасность

*   Используйте `auth_hmac` (Keepalived 2.4.0+) вместо простого `auth_pass` для защиты от spoofing и replay-атак.
*   Ограничьте доступ к REST API Angie (`allow 127.0.0.1; deny all;`).
*   Используйте отдельного пользователя для `script_user` в Keepalived (не root в production).
*   Настройте `enable_script_security` для ограничения прав скриптов.
*   Никогда не храните пароли и ключи в конфигурационных файлах в открытом виде. Используйте Ansible Vault или HashiCorp Vault.

### Жизненный цикл сертификатов

*   Используйте DNS-01 challenge для ACME при работе с VIP.
*   Синхронизируйте `/var/lib/angie/acme/` между узлами.
*   Настройте алерты на истечение срока действия сертификатов.

### Производительность

*   Используйте BFD для обнаружения отказов за < 1 секунды.
*   Настройте `vrrp_garp_master_delay` и `garp_master_repeat` для минимизации задержек при переключении.
*   Используйте `track_process` вместо `vrrp_script` для мониторинга Angie (меньше накладных расходов).
*   Настройте `advert_int` с учетом задержек в сети (0.5–1 секунда).

### Эксплуатация

*   Всегда тестируйте failover в стейджинг-среде перед production.
*   Настройте `notify_master`/`notify_backup` скрипты для обновления DNS и отправки алертов.
*   Используйте `angie-ha-sync` или Ansible для синхронизации конфигурации.
*   Храните конфигурацию в Git, исключая секреты.
*   Настройте мониторинг в Prometheus + Grafana с алертами на изменение состояния VRRP.
*   Документируйте все изменения конфигурации.
*   Создавайте резервные копии перед каждым изменением:
    ```bash
    cp /etc/keepalived/keepalived.conf /etc/keepalived/keepalived.conf.bak.$(date +%Y%m%d%H%M%S)
    ```

### Откат и восстановление

*   При проблемах с VIP временно отключите Keepalived (`systemctl stop keepalived`) и вернитесь к статическому IP.
*   Используйте `nopreempt` в тестовой среде для предотвращения постоянных переключений.
*   При откате конфигурации Angie используйте `angie -t` перед `reload`.

### Вытеснение (Preemption)

По умолчанию восстановленный `MASTER` сразу забирает роль обратно. Чтобы избежать лишнего «мигания» VIP (flapping), рекомендуется:
```keepalived
vrrp_instance VI_1 {
    state BACKUP
    nopreempt
    # ...
}
```

### Мониторинг в Prometheus и Grafana

Для алертинга и визуализации:
- **Встроенный модуль Angie**: `/metrics` (Prometheus format).
- **keepalived-exporter**: для сбора данных о состоянии VRRP.
- **Grafana Dashboard ID 20719**: официальный дашборд для Angie.

### Версии Keepalived

**Актуальность (2025–2026):** Keepalived остаётся стандартом де-факто для обеспечения высокой доступности в bare-metal и VM-окружениях. Версия **2.4.x** (June 2026) включает расширение `auth_hmac` (HMAC-SHA256 подпись VRRP-анонсов), масштабную проверку безопасности (parser, netlink, checker, notify, DBus) и поддержку VRRPv3 субсекундных таймеров.

### Ограничения

*   VIP обязан находиться в той же L2-подсети, что и физические IP узлов. VRRP не маршрутизируется. Для L3-связности используйте BGP Anycast или DNS Failover.
*   Максимум 20 VIP на `vrrp_instance` (через `virtual_ipaddress`). Для неограниченного числа VIP используйте `virtual_ipaddress_excluded`.
*   `auth_pass` в VRRPv2 ограничен 8 символами. Для более длинных ключей используйте `auth_hmac` (Keepalived 2.4.0+).

## См. также

- **[Обзор Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)** — подробная теория, VRRPv3, BFD, auth_hmac.
- **[Обзор Angie](./angie_overview.md)** — возможности и отличия от Nginx.
- **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — health checks, алгоритмы, sticky sessions.
- **[Динамические апстримы и Service Discovery](./dynamic_upstreams.md)** — DNS, Docker, API управление upstream.
- **[HA для Kubernetes с Keepalived и HAProxy](../../Kubernetes/Installation/kubeadm/keepalived_haproxy_setup.md)**.
