# Настройка High Availability API-сервера с помощью Keepalived и HAProxy

## Определения

- **Высокая доступность Control Plane (HA Control Plane):** Архитектура кластера Kubernetes, в которой компоненты управляющей плоскости (в частности, `kube-apiserver`) развернуты на нескольких узлах для устранения единой точки отказа (SPOF).
- **Виртуальный IP-адрес (Virtual IP, VIP):** Стабильный IP-адрес, который не привязан к одному физическому серверу, а может "перемещаться" между узлами кластера. В данной схеме он служит единой точкой входа для доступа к API-серверу.
- **`--control-plane-endpoint`:** Флаг `kubeadm`, который указывает на общий адрес (VIP:PORT или DNS-имя) для всех API-серверов в HA-кластере. Все компоненты кластера (`kubelet`, другие control-plane узлы) и внешние клиенты (`kubectl`) будут использовать этот адрес.

## Основные концепции

### Проблема

В кластере Kubernetes с несколькими master-узлами каждый из них запускает собственный экземпляр `kube-apiserver` на порту `6443`. Если внешние инструменты (`kubectl`, Lens) или присоединяемые узлы (`kubeadm join`) настроить на IP-адрес одного конкретного master-узла, то при его отказе доступ к кластеру будет потерян. Потребуется ручное переключение на другой работающий узел, что неудобно и нарушает принцип высокой доступности.

### Решение: VIP и L4-балансировщик

Классическим решением для bare-metal серверов является создание "плавающего" виртуального IP-адреса (VIP), который всегда будет указывать на рабочую точку входа, и использование L4-балансировщика для распределения нагрузки между всеми доступными master-узлами.

Эта задача решается с помощью связки двух проверенных инструментов: **Keepalived** и **HAProxy**.

![HA for Kube-API with Keepalived and HAProxy](https://user-images.githubusercontent.com/1357597/154887326-68a864d4-6e3e-4b73-98f9-158f01b1e367.png)

1.  **Keepalived**: Запускается на всех master-узлах. Его задача — обеспечить, чтобы VIP-адрес всегда был назначен одному из *живых* узлов. Узлы обмениваются VRRP-сообщениями. Если узел, владеющий VIP (`MASTER`), выходит из строя, один из резервных узлов (`BACKUP`) "захватывает" VIP.
2.  **HAProxy**: Также запускается на всех master-узлах. Его задача — принимать TCP-трафик, приходящий на VIP, и распределять его между всеми доступными экземплярами `kube-apiserver`.
    -   HAProxy слушает на VIP-адресе, но на **другом порту** (например, `7443`), так как порт `6443` уже занят локальным `kube-apiserver`.
    -   Он работает в режиме **`mode tcp`** (L4-балансировка), просто пробрасывая зашифрованный HTTPS-трафик до API-сервера. Терминирование SSL/TLS происходит на самом `kube-apiserver`, а не на балансировщике.
    -   HAProxy выполняет собственные проверки работоспособности (`health checks`) и не будет отправлять трафик на отказавшие master-узлы.

В итоге все клиенты обращаются по одному стабильному адресу (`<VIP>:<HAProxy_Port>`), а связка Keepalived и HAProxy прозрачно обеспечивает отказоустойчивость и балансировку.

## Практические сценарии

Предполагается, что настройка выполняется на всех узлах, выделенных под Control Plane (например, 3 узла).

### Шаг 1: Установка и настройка Keepalived

1.  **Установка на всех master-узлах:**
    ```bash
    # Для Red Hat / CentOS
    sudo dnf install -y keepalived

    # Для Debian / Ubuntu
    sudo apt-get install -y keepalived
    ```

2.  **Конфигурация на первом (Master) узле Keepalived (`/etc/keepalived/keepalived.conf`):**
    Этот узел будет главным (MASTER) в кластере Keepalived благодаря более высокому приоритету.

    ```keepalived
    global_defs {
       router_id kube_api_master
    }

    vrrp_instance VI_1 {
        state MASTER
        interface ens192  # !!! Замените на ваш сетевой интерфейс
        virtual_router_id 51
        priority 101

        advert_int 1
        authentication {
            auth_type PASS
            auth_pass "supersecret"
        }

        virtual_ipaddress {
            192.168.122.189/24  # !!! Замените на ваш желаемый VIP
        }
    }
    ```

3.  **Конфигурация на остальных (Backup) узлах Keepalived:**
    Конфигурация идентична, за исключением `state` и `priority`.

    ```keepalived
    global_defs {
       router_id kube_api_backup
    }

    vrrp_instance VI_1 {
        state BACKUP
        interface ens192  # !!! Замените на ваш сетевой интерфейс
        virtual_router_id 51
        priority 100     # Приоритет ниже, чем у MASTER

        advert_int 1
        authentication {
            auth_type PASS
            auth_pass "supersecret"
        }

        virtual_ipaddress {
            192.168.122.189/24  # !!! Тот же самый VIP
        }
    }
    ```
4. **Запуск и включение автозагрузки**
    ```bash
    sudo systemctl enable --now keepalived
    ```
### Шаг 2: Установка и настройка HAProxy

1.  **Установка на всех master-узлах:**
    ```bash
    # Для Red Hat / CentOS
    sudo dnf install -y haproxy

    # Для Debian / Ubuntu
    sudo apt-get install -y haproxy
    ```

2.  **Конфигурация на всех master-узлах (`/etc/haproxy/haproxy.cfg`):**
    Конфигурационный файл HAProxy **одинаков** для всех узлов.

    ```haproxy
    global
        log /dev/log    local0
        log /dev/log    local1 notice
        chroot /var/lib/haproxy
        stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
        stats timeout 30s
        user haproxy
        group haproxy
        daemon

    defaults
        log     global
        mode    http
        option  httplog
        option  dontlognull
        timeout connect 5000
        timeout client  50000
        timeout server  50000

    frontend kubernetes-api
        bind 192.168.122.189:7443  # !!! Используйте ваш VIP и выбранный порт
        mode tcp
        option tcplog
        default_backend kubernetes-api-masters

    backend kubernetes-api-masters
        mode tcp
        balance roundrobin
        server master1 192.168.122.171:6443 check  # !!! IP первого master-узла
        server master2 192.168.122.172:6443 check  # !!! IP второго master-узла
        server master3 192.168.122.173:6443 check  # !!! IP третьего master-узла
    
    # (Опционально) Статистика HAProxy
    listen stats
        bind *:8404
        stats enable
        stats uri /stats
        stats refresh 10s
        stats admin if LOCALHOST
    ```
3. **Разрешение HAProxy биндиться на "чужой" IP (VIP)**
   ```bash
   sudo sysctl -w net.ipv4.ip_nonlocal_bind=1
   # Для сохранения после перезагрузки:
   echo "net.ipv4.ip_nonlocal_bind=1" | sudo tee -a /etc/sysctl.conf
   ```

4. **Запуск и включение автозагрузки**
    ```bash
    sudo systemctl enable --now haproxy
    ```
### Шаг 3: Инициализация кластера `kubeadm`

Теперь, когда у вас есть стабильная точка входа, вы можете инициализировать кластер, указав ее `kubeadm`.

1.  **На первом master-узле:**
    Используйте VIP и порт HAProxy в флаге `--control-plane-endpoint`. Флаг `--upload-certs` необходим для последующего присоединения других master-узлов.

    ```bash
    sudo kubeadm init --control-plane-endpoint "192.168.122.189:7443" --upload-certs
    ```

2.  **На других master-узлах:**
    Используйте команду `kubeadm join`, выданную на предыдущем шаге, которая будет содержать тот же `--control-plane-endpoint`.

3.  **На worker-узлах:**
    Команда `kubeadm join` для worker-узлов также будет использовать общий endpoint.

## Проверка

1.  **Проверка VIP:**
    На одном из master-узлов (вероятнее всего на том, у которого `priority` выше) должен появиться VIP.
    ```bash
    ip a | grep 192.168.122.189  # Замените на ваш VIP
    ```
    Попробуйте остановить `keepalived` на этом узле. VIP должен "переехать" на другой узел.

2.  **Проверка HAProxy:**
    После того как `kube-apiserver` будет запущен, вы можете проверить страницу статистики HAProxy по адресу `http://<любой_master_IP>:8404/stats`. Бэкенды `kubernetes-api-masters` должны быть в статусе UP (зеленые). До запуска API они будут в статусе DOWN (красные).

## Дополнительная информация

Эта связка является классическим и надежным решением, однако требует ручной настройки.

- **Альтернативы**: В облачных средах эту роль выполняет облачный балансировщик нагрузки (ELB, NLB).
- **Размещение в Kubernetes**: Теоретически, Keepalived и HAProxy можно запустить и внутри самого Kubernetes (например, как DaemonSet), но это усложняет начальную загрузку кластера и создает проблему "курицы и яйца". Размещение их на хост-системе для обеспечения доступности API является более простым и надежным подходом.

### Связанные темы

- [Обзор Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md)
- [Обзор HAProxy](../../WebServers/Haproxy/haproxy_overview.md)
- [Высокая доступность в Kubernetes](../Base/high_availability.md)
- [Быстрый старт с kubeadm](./kubeadm_quickstart.md)
