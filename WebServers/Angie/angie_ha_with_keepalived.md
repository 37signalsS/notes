# Настройка отказоустойчивого кластера Angie с Keepalived (VRRP)

## Определения

- **HA (High Availability — высокая доступность):** архитектурный подход, обеспечивающий минимальное время простоя сервиса за счет дублирования компонентов. Подробности — в **[обзоре High Availability](../../Concepts/High_Availability/ha_overview.md)**.
- **Angie:** современный веб-сервер, форк Nginx с расширенными возможностями. Подробнее в **[общем обзоре Angie](./angie_overview.md)**.
- **Keepalived:** сервис для управления виртуальным IP-адресом (VIP) на базе протокола VRRP. Является стандартом для Linux-окружений. Детали в **[обзоре Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)**.
- **VRRP (Virtual Router Redundancy Protocol):** сетевой протокол, позволяющий группе серверов совместно владеть одним виртуальным IP-адресом.
- **VIP (Virtual IP — виртуальный IP-адрес):** плавающий адрес, который назначается активному узлу (`MASTER`) и мигрирует на резервный (`BACKUP`) при сбое.

## Основные концепции

### Принцип работы кластера

Кластер состоит из двух или более узлов с установленными Angie и Keepalived.

1.  **Роли и приоритеты:** Один узел назначается `MASTER` (высокий приоритет), остальные — `BACKUP`.
2.  **Обмен состоянием (Advertisements):** `MASTER` периодически отправляет VRRP-пакеты. Если `BACKUP` не получает анонсы в течение заданного времени, он инициирует перехват роли.
3.  **Мониторинг (Health Checks):**
    - **vrrp_script:** выполнение внешнего скрипта (например, `curl` к эндпоинту).
    - **track_process:** встроенный мониторинг состояния процесса (рекомендуется для Keepalived 2.x+).
4.  **Переключение (Failover):** При сбое Angie или всего узла VIP перемещается на исправный сервер. Для обновления таблиц коммутаторов используется **Gratuitous ARP**.
5.  **Режимы вещания:**
    - **Multicast:** классический режим (224.0.0.18), может блокироваться в облаках.
    - **Unicast:** прямая передача пакетов между IP узлов (рекомендуется для публичных облаков и современных ЦОД).

### Системные требования

Для корректной работы VIP и Angie необходимо разрешить привязку IP-адресов, которые еще не назначены интерфейсу (нелокальные адреса):

```bash
echo "net.ipv4.ip_nonlocal_bind=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

## Практический сценарий

### Шаг 1: Подготовка инфраструктуры

Схема для примера (L2-сегмент):

- `node1` (Master): `192.168.1.101`
- `node2` (Backup): `192.168.1.102`
- Виртуальный IP (VIP): `192.168.1.100`

Установка Keepalived:
```bash
sudo apt update && sudo apt install keepalived curl -y
```

### Шаг 2: Конфигурация Keepalived

#### Вариант А: Проверка через скрипт (`vrrp_script`)

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

#### Вариант Б: Мониторинг процесса (`track_process`)

Более легкий способ (без вызова bash), доступен в Keepalived 2.x+. В этом случае `vrrp_script` не требуется.

```keepalived
vrrp_instance VI_1 {
    # ...
    track_process {
        nm_angie {
            process angie
            weight 20
        }
    }
}
```

#### Конфигурация MASTER (Unicast)

Файл: `/etc/keepalived/keepalived.conf`

```keepalived
global_defs {
   router_id angie_node_1
   vrrp_garp_master_delay 5
}

# Используется для Варианта А
vrrp_script chk_angie {
    script "/etc/keepalived/check_angie.sh"
    interval 2
    weight 20
    fall 2
    rise 2
}

vrrp_instance VI_1 {
    state MASTER
    interface enp1s0        # Уточните имя интерфейса: ip a
    virtual_router_id 51
    priority 101
    advert_int 1

    # Рекомендуемый режим Unicast
    unicast_src_ip 192.168.1.101
    unicast_peer {
        192.168.1.102
    }

    authentication {
        auth_type PASS
        auth_pass Secr3tPass    # Максимум 8 символов (ограничение VRRPv2)
    }

    virtual_ipaddress {
        192.168.1.100/24 dev enp1s0 label enp1s0:vip
    }

    # Для Варианта А расскомментируйте:
    # track_script {
    #     chk_angie
    # }

    # Для Варианта Б (Keepalived 2.x+) расскомментируйте:
    # track_process {
    #     nm_angie {
    #         process angie
    #         weight 20
    #     }
    # }
}
```

#### Конфигурация BACKUP

Отличия: `priority 100`, `unicast_src_ip` и `unicast_peer`.

```keepalived
vrrp_instance VI_1 {
    state BACKUP
    interface enp1s0
    virtual_router_id 51
    priority 100
    
    unicast_src_ip 192.168.1.102
    unicast_peer {
        192.168.1.101
    }
    # ... остальные параметры идентичны MASTER ...
}
```

### Шаг 3: Настройка Angie

На обоих серверах добавьте блок для проверки состояния:

```nginx
server {
    listen 80;
    
    # Добавление заголовка для идентификации узла (отладка)
    add_header X-Backend-Server $hostname always;

    location /health_check {
        allow 127.0.0.1;
        deny all;
        return 200 "OK";
        access_log off;
    }

    location / {
        root /usr/share/angie/html;
        index index.html;
    }
}
```

### Шаг 4: Сетевой экран (Firewall)

Необходимо разрешить VRRP-трафик.

**ufw:**
```bash
# Для Multicast
sudo ufw allow in proto vrrp
# Для Unicast (между узлами)
sudo ufw allow in from 192.168.1.0/24 proto vrrp
```

### Шаг 5: Диагностика

1.  **Проверка VIP:**
    ```bash
    ip addr show enp1s0
    # → inet 192.168.1.100/24 scope global secondary enp1s0:vip
    ```
2.  **Логи перехода состояний:**
    ```bash
    journalctl -u keepalived -f
    ```
3.  **Тест переключения:**
    Остановите Angie на мастере (`systemctl stop angie`) и убедитесь, что VIP переместился на backup.

## Дополнительная информация

### Вытеснение (Preemption)

По умолчанию восстановленный `MASTER` сразу забирает роль обратно. Если это нежелательно (лишнее мигание VIP), добавьте в конфиг:
```keepalived
vrrp_instance VI_1 {
    state BACKUP
    nopreempt
    # ...
}
```
*Важно: `nopreempt` работает только если изначальное состояние `BACKUP`.*

### Синхронизация данных

Keepalived перемещает только IP. Синхронизация конфигурации Angie и контента должна выполняться внешними средствами:
- **CI/CD / Ansible:** предпочтительный метод для production.
- **Shared Storage:** NFS/Ceph для контента.
- **rsync + lsyncd:** для простых инсталляций.

### Мониторинг HA-статуса

Для алертинга о переключении ролей рекомендуется использовать:
- **keepalived-exporter:** для сбора метрик в Prometheus.
- **SNMP:** классический метод мониторинга Keepalived.

## См. также

- **[Обзор Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)** — теория, VRRPv3, BFD.
- **[Обзор Angie](./angie_overview.md)** — возможности и отличия от Nginx.
- **[HA для Kubernetes с Keepalived и HAProxy](../../Kubernetes/Installation/kubeadm/keepalived_haproxy_setup.md)** — пример с балансировщиком.
