# Настройка отказоустойчивого кластера Angie с Keepalived (VRRP)

## Определения

- **HA (High Availability — высокая доступность):** архитектурный подход, обеспечивающий минимальное время простоя сервиса за счет дублирования компонентов. Подробности — в **[обзоре High Availability](../../Concepts/High_Availability/ha_overview.md)**.
- **Angie:** современный веб-сервер, форк Nginx с расширенными возможностями. Подробнее в **[общем обзоре Angie](./angie_overview.md)**.
- **Keepalived:** сервис для управления виртуальным IP-адресом (VIP) на базе протокола VRRP. Является стандартом для Linux-окружений. В 2026 году рекомендуется использовать версию 2.x с поддержкой BFD. Детали в **[обзоре Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)**.
- **VRRP (Virtual Router Redundancy Protocol):** сетевой протокол, позволяющий группе серверов совместно владеть одним виртуальным IP-адресом.
- **BFD (Bidirectional Forwarding Detection):** протокол быстрого обнаружения разрыва сетевого соединения (время реакции — от 100 мс).
- **VIP (Virtual IP — виртуальный IP-адрес):** плавающий адрес, который назначается активному узлу (`MASTER`) и мигрирует на резервный (`BACKUP`) при сбое.

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

### Защита от Split-Brain

**Split-Brain** — состояние, при котором из-за проблем в сети узлы перестают видеть друг друга и оба становятся `MASTER`, вызывая конфликт IP.
**Методы защиты в 2026 году:**
- **Unicast Mode:** использование прямой адресации партнеров исключает влияние стороннего VRRP-трафика в сегменте.
- **Quorum Script:** использование `vrrp_script` для проверки связи с внешним шлюзом (например, `ping` шлюза провайдера). Если связи нет — узел переходит в состояние `FAULT`.
- **Witness Node:** использование третьего легковесного узла (арбитра) для подтверждения статуса MASTER.

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

Установка ПО:
```bash
sudo apt update && sudo apt install keepalived angie-ha-sync curl -y
```

### Шаг 2: Настройка Angie (Health Check & API)

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

### Шаг 3: Конфигурация Keepalived

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

#### Вариант Б: Продвинутая настройка (BFD + API + Process)

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

#### Конфигурация BACKUP

Отличия: `priority 100`, `unicast_src_ip` и `unicast_peer`.

### Шаг 4: Синхронизация данных и конфигураций

Keepalived перемещает только IP. В 2026 году для Angie рекомендуется:
1.  **`angie-ha-sync`**: официальный инструмент для синхронизации `/etc/angie/` между узлами.
    - Установите пакет: `apt install angie-ha-sync`.
    - Настройте SSH-ключи между узлами.
    - Демон отслеживает изменения и делает `reload` на втором узле только после `angie -t`.
2.  **Shared Storage**: NFS или Ceph для контента (статические файлы).
3.  **Ansible/Terraform**: предпочтительный метод для управления конфигурацией в production.

### Шаг 5: Сетевой экран (Firewall)

Необходимо разрешить VRRP и BFD трафик.

**ufw:**
```bash
# VRRP (протокол 112)
sudo ufw allow in proto vrrp
# BFD (UDP 3784)
sudo ufw allow in proto udp from 192.168.1.0/24 to any port 3784
```

### Шаг 6: Диагностика

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

## Дополнительная информация

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

## См. также

- **[Обзор Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)** — подробная теория, VRRPv3, BFD.
- **[Обзор Angie](./angie_overview.md)** — возможности и отличия от Nginx.
- **[HA для Kubernetes с Keepalived и HAProxy](../../Kubernetes/Installation/kubeadm/keepalived_haproxy_setup.md)**.
