# Отказоустойчивость OpenSearch с помощью Keepalived (Floating VIP)

## Описание сценария

Для обеспечения высокой доступности (HA) кластера OpenSearch используется плавающий виртуальный IP-адрес (VIP). Клиенты подключаются к VIP:9200, который автоматически перемещается на исправный узел кластера при сбое текущего мастера.

**Инфраструктура:**
- Кластер из 3 узлов (версия Ubuntu 24.04).
- OpenSearch слушает на порту 9200.
- Виртуальный IP (VIP): `10.0.1.10/24`.

| Имя узла | Физический IP | Роль Keepalived (исходная) | Приоритет |
| :--- | :--- | :--- | :--- |
| **os-node-1** | 10.0.1.1 | MASTER | 103 |
| **os-node-2** | 10.0.1.2 | BACKUP | 102 |
| **os-node-3** | 10.0.1.3 | BACKUP | 101 |

## Подготовка OpenSearch

На всех узлах необходимо настроить OpenSearch так, чтобы он слушал на всех интерфейсах (0.0.0.0), иначе он не сможет принимать трафик через виртуальный IP.

1. Отредактируйте конфигурацию:
   ```bash
   sudo nano /etc/opensearch/opensearch.yml
   ```
2. Установите параметр:
   ```yaml
   network.host: "0.0.0.0"
   ```
3. Перезапустите сервис:
   ```bash
   sudo systemctl restart opensearch
   ```

## Настройка Keepalived

### 1. Установка

Выполните на всех трех узлах:
```bash
sudo apt update && sudo apt install keepalived netcat-openbsd -y
```

### 2. Конфигурация узлов

Создайте файл конфигурации `/etc/keepalived/keepalived.conf` на каждом узле.

#### Узел 1 (MASTER)
```keepalived
vrrp_script chk_opensearch {
    script "nc -zv localhost 9200"
    interval 3
    timeout 4
    weight 2
    rise 2
    fall 2
}

vrrp_instance VI_1 {
    state MASTER
    interface ens160          # Замените на имя вашего интерфейса
    priority 103
    virtual_router_id 53
    advert_int 1
    unicast_src_ip 10.0.1.1   # IP этого узла
    unicast_peer {
        10.0.1.2
        10.0.1.3
    }
    virtual_ipaddress {
        10.0.1.10/24
    }
    track_script {
        chk_opensearch
    }
}
```

#### Узел 2 (BACKUP)
```keepalived
vrrp_script chk_opensearch {
    script "nc -zv localhost 9200"
    interval 3
    timeout 4
    weight 2
    rise 2
    fall 2
}

vrrp_instance VI_1 {
    state BACKUP
    interface ens160
    priority 102
    virtual_router_id 53
    advert_int 1
    unicast_src_ip 10.0.1.2   # IP этого узла
    unicast_peer {
        10.0.1.1
        10.0.1.3
    }
    virtual_ipaddress {
        10.0.1.10/24
    }
    track_script {
        chk_opensearch
    }
}
```

#### Узел 3 (BACKUP)
```keepalived
vrrp_script chk_opensearch {
    script "nc -zv localhost 9200"
    interval 3
    timeout 4
    weight 2
    rise 2
    fall 2
}

vrrp_instance VI_1 {
    state BACKUP
    interface ens160
    priority 101
    virtual_router_id 53
    advert_int 1
    unicast_src_ip 10.0.1.3   # IP этого узла
    unicast_peer {
        10.0.1.1
        10.0.1.2
    }
    virtual_ipaddress {
        10.0.1.10/24
    }
    track_script {
        chk_opensearch
    }
}
```

### 3. Разбор параметров

| Параметр | Описание |
| :--- | :--- |
| **vrrp_script** | Блок проверки состояния сервиса. |
| **script "nc -zv ..."** | Проверка доступности порта 9200 через утилиту `nc`. |
| **interval 3** | Частота запуска проверки (секунды). |
| **fall 2 / rise 2** | Количество провалов/успехов подряд для смены статуса. |
| **virtual_router_id** | Уникальный ID группы (должен совпадать на всех узлах). |
| **priority** | Приоритет узла (узел с максимальным значением становится MASTER). |
| **unicast_peer** | Список IP-адресов других участников кластера (режим Unicast). |
| **virtual_ipaddress** | Виртуальный IP-адрес, который будет "плавать" между узлами. |
| **track_script** | Привязка проверки состояния к инстансу VRRP. |

### 4. Запуск и проверка

Запустите службу на всех узлах:
```bash
sudo systemctl enable --now keepalived
```

Проверьте наличие VIP на мастере:
```bash
ip addr show ens160
```
В выводе должен появиться вторичный адрес `10.0.1.10`.

## Тестирование отказоустойчивости

1. **Остановка OpenSearch:** Остановите сервис на MASTER-узле (`sudo systemctl stop opensearch`). Через 6-10 секунд VIP должен переместиться на узел с приоритетом 102.
2. **Отключение сети:** При потере связи с MASTER, BACKUP-узлы инициируют выборы и перехватят VIP.
3. **Восстановление:** По умолчанию Keepalived работает в режиме `preempt` (вытеснение). Если восстановится узел с более высоким приоритетом, он заберет роль MASTER обратно.

## См. также

- **[Keepalived: Обзор и настройка HA](../../Networking/ServicesAndTools/keepalived_overview.md)** — общие принципы и теория.
- **[Администрирование OpenSearch](./opensearch_administration.md)** — управление индексами и кластером.
