# Настройка отказоустойчивого кластера Angie с Keepalived (VRRP)

## Определения

- **HA (High Availability — высокая доступность):** характеристика системы, направленная на минимизацию времени простоя за счет дублирования компонентов и механизмов автоматического переключения.
- **Цель:** обеспечить непрерывную доступность сервиса (например, веб-сайта или API (Application Programming Interface)), размещенного на двух или более серверах Angie. При отказе одного из серверов трафик должен автоматически перенаправляться на рабочий.
- **Компоненты:**
  - **Angie:** высокопроизводительный веб-сервер, основной сервис, доступность которого мы обеспечиваем. Подробнее в [общем обзоре Angie](./angie_overview.md).
  - **Keepalived:** сервис, реализующий протокол VRRP для управления виртуальным IP-адресом. Детали в [обзоре Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md).
  - **VRRP (Virtual Router Redundancy Protocol — протокол резервирования виртуальных маршрутизаторов):** сетевой протокол, позволяющий нескольким узлам разделять один виртуальный IP-адрес.
  - **VIP (Virtual IP — виртуальный IP-адрес):** единый IP-адрес, который назначается активному серверу в кластере и мигрирует на резервный в случае сбоя.

## Основные концепции

### Принцип работы кластера

Схема состоит из двух или более серверов с Angie и Keepalived.

1. **Роли:** один сервер назначается `MASTER` (основной), остальные — `BACKUP` (резервные). `MASTER` обладает более высоким приоритетом.
2. **Обмен состоянием:** `MASTER` сервер периодически отправляет в сеть мультикаст-сообщения (**VRRP advertisements**), объявляя о своем состоянии и владении VIP.
3. **Владение VIP:** пока `MASTER` активен, VIP-адрес принадлежит ему, и весь клиентский трафик поступает на этот узел.
4. **Проверка сервиса (Health Check):** Keepalived на каждом узле постоянно проверяет работоспособность локального сервиса Angie с помощью скрипта. Если сервис Angie не отвечает, Keepalived на этом узле добровольно понижает свой приоритет, давая возможность другому узлу стать `MASTER`.
5. **Отказ (Failover):**
    - **Отказ сервиса:** если скрипт проверки на `MASTER` узле завершается с ошибкой, его приоритет падает. `BACKUP`-сервер, видя, что его собственный приоритет стал выше, захватывает роль `MASTER` и VIP-адрес.
    - **Полный отказ узла:** если `MASTER` прекращает отправлять VRRP-сообщения, `BACKUP`-сервер с наивысшим приоритетом после короткого тайм-аута также становится `MASTER`. Для уведомления сети используется **ARP (Address Resolution Protocol — протокол определения адреса)**, в частности **Gratuitous ARP**, чтобы обновить таблицы коммутаторов.
6. **Восстановление (Failback):** когда оригинальный `MASTER` восстанавливается, он снова начинает отправлять VRRP-анонсы с более высоким приоритетом и по умолчанию забирает VIP-адрес обратно.

## Практический сценарий

### Шаг 1: Подготовка

Предположим, у нас два сервера в одном сегменте сети L2 (Layer 2 — канальный уровень модели OSI (Open Systems Interconnection)):

- `node1` (Master): `192.168.1.101`
- `node2` (Backup): `192.168.1.102`
- Виртуальный IP (VIP): `192.168.1.100`

### Шаг 2: Конфигурация Keepalived

#### Скрипт проверки Angie (`/etc/keepalived/check_angie.sh`)

Скрипт проверяет, что Angie отдает код 200 на специальный эндпоинт. Создайте этот файл на обоих узлах.

```bash
#!/bin/bash
# Проверка доступности Angie через HTTP-эндпоинт
# -f: exit code != 0 при HTTP-ошибках (4xx, 5xx)
# -s: тихий режим, без прогресс-бара
# -o /dev/null: тело ответа не сохранять
# -w "%{http_code}": вывести только HTTP-код
STATUS_CODE=$(/usr/bin/curl -f -s -o /dev/null -w "%{http_code}" http://127.0.0.1/health_check)
if [ "$STATUS_CODE" -eq 200 ]; then
  exit 0
else
  exit 1
fi
```

Сделайте скрипт исполняемым: `chmod +x /etc/keepalived/check_angie.sh`.

#### Конфигурация для MASTER (`node1`)

Файл: `/etc/keepalived/keepalived.conf`

```keepalived
global_defs {
   router_id angie_node_1
}

vrrp_script chk_angie {
    script "/etc/keepalived/check_angie.sh"
    interval 1   # Проверять каждую 1 секунду
    timeout 1    # Таймаут выполнения скрипта
    weight 20    # Если скрипт успешен, повысить приоритет на 20
    fall 2       # Считать сервис упавшим после 2 неудачных проверок
    rise 2       # Считать сервис поднявшимся после 2 удачных проверок
}

vrrp_instance VI_1 {
    state MASTER            # Изначальное состояние - MASTER
    interface enp1s0        # Сетевой интерфейс для VRRP
    virtual_router_id 51    # Уникальный ID для кластера, должен быть одинаковым на всех узлах
    priority 101            # Приоритет. У MASTER он должен быть выше.

    advert_int 1            # Интервал отправки VRRP-анонсов (в секундах)

    # Аутентификация для VRRP-пакетов. Пароль должен совпадать на всех узлах.
    authentication {
        auth_type PASS
        auth_pass your_secret_password
    }

    # Виртуальный IP-адрес, который будет мигрировать
    virtual_ipaddress {
        192.168.1.100/24
    }

    # Применение скрипта проверки
    track_script {
        chk_angie
    }
}
```

#### Конфигурация для BACKUP (`node2`)

Конфигурация почти идентична, но с `state BACKUP` и `priority 100`.

```keepalived
global_defs {
   router_id angie_node_2
}

vrrp_script chk_angie {
    script "/etc/keepalived/check_angie.sh"
    interval 1
    timeout 1
    weight 20
    fall 2
    rise 2
}

vrrp_instance VI_1 {
    state BACKUP            # Изначальное состояние - BACKUP
    interface enp1s0
    virtual_router_id 51    # Тот же ID
    priority 100            # Приоритет ниже, чем у MASTER

    advert_int 1

    authentication {
        auth_type PASS
        auth_pass your_secret_password # Тот же пароль
    }

    virtual_ipaddress {
        192.168.1.100/24
    }

    track_script {
        chk_angie
    }
}
```

### Шаг 3: Конфигурация Angie

На обоих серверах Angie должен быть настроен легковесный эндпоинт для проверок.

```nginx
server {
    listen 80;
    server_name example.com;

    # (Опционально) Заголовок для отладки
    # Позволяет видеть, какой сервер реально ответил.
    add_header X-Front-Node "master" always;

    location / {
        # Ваша основная конфигурация, например, отдача статики или проксирование
        root /usr/share/nginx/html;
        index index.html index.htm;
    }

    # Health check для Keepalived
    location /health_check {
        # Разрешаем доступ только с локального хоста (для скрипта Keepalived)
        allow 127.0.0.1;
        deny all;

        # Возвращаем простой и быстрый ответ.
        return 200 "OK";
        
        # Указываем, что логи для этих запросов не нужны, чтобы не засорять access.log
        access_log off;
    }
}
```

### Шаг 4: Диагностика и проверка

1. **Проверка VIP:**
    На активном узле (MASTER) команда `ip a` или `ip addr show <interface>` покажет виртуальный IP на указанном интерфейсе. На `BACKUP` узле его быть не должно.

    ```bash
    ip addr show enp1s0
    # → inet 192.168.1.101/24 brd 192.168.1.255 scope global enp1s0
    # → inet 192.168.1.100/24 scope global secondary enp1s0
    ```

2. **Проверка логов Keepalived:**
    Изучите статус и логи сервиса, чтобы увидеть переходы состояний (`Entering MASTER STATE`, `Entering BACKUP STATE`).

    ```bash
    sudo systemctl status keepalived
    journalctl -u keepalived -f
    ```

3. **Проверка ответа от VIP:**
    С любой машины в той же сети выполните `curl` к виртуальному IP.

    ```bash
    curl -I http://192.168.1.100
    # → HTTP/1.1 200 OK
    # → X-Front-Node: master
    ```

4. **Тестирование переключения:**
    Остановите сервис Angie на `MASTER` узле: `sudo systemctl stop angie`. Через несколько секунд `curl -I http://192.168.1.100` должен показать заголовок от `BACKUP` узла.

## Дополнительная информация

### Важные моменты и ограничения

- **Требования к сети:** все узлы кластера должны находиться в одном L2-сегменте сети.
- **Split-Brain (разделение мозга):** ситуация, когда узлы теряют связь и оба решают, что они `MASTER`. Это приводит к конфликту IP-адресов.
- **Preemption (вытеснение):** по умолчанию восстановленный `MASTER` забирает VIP обратно. Чтобы избежать лишнего переключения, на `BACKUP` узлах можно добавить директиву `nopreempt`. В этом случае `BACKUP`, ставший мастером, останется им до собственного отказа.
- **Версии VRRP:** конфигурация использует VRRPv2. Для поддержки IPv6 следует использовать VRRPv3.

### Синхронизация конфигураций и состояния

Keepalived отвечает только за миграцию VIP и не синхронизирует данные между узлами.

- **Конфигурация Angie:** конфигурационные файлы Angie, включая SSL (Secure Sockets Layer) сертификаты, на всех узлах кластера должны быть идентичны. Для их синхронизации используйте внешние инструменты (Ansible, `rsync`).
- **Состояние сессий:** при переключении все активные TCP (Transmission Control Protocol) соединения с бывшим `MASTER` разрываются. Для трафика HTTP (HyperText Transfer Protocol) это обычно не является проблемой, так как клиенты автоматически переподключаются к VIP, попадая уже на новый `MASTER`.

## См. также

- [Обзор Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md) — общие принципы работы Keepalived, VRRPv3, unicast-режим
- [Обзор Angie](./angie_overview.md) — возможности и архитектура Angie
- [HA для Kubernetes с Keepalived и HAProxy](../../Kubernetes/Installation/kubeadm/keepalived_haproxy_setup.md) — аналогичный паттерн для kube-apiserver
