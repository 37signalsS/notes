# Механизмы Failover и Heartbeat

## Определения

**Failover (Переключение при отказе)** — автоматический процесс передачи функций от сбойного компонента к резервному. Ключевой механизм обеспечения [высокой доступности](./ha_overview.md).

**Heartbeat (Сигнал жизнеспособности)** — регулярный сигнал, демонстрирующий работоспособность компонента. Отсутствие сигнала в течение заданного времени инициирует failover.

**Split-Brain (Расщепление мозга)** — критическая ситуация, при которой несколько узлов кластера одновременно считают себя активными (master) из-за потери связи. Приводит к рассинхронизации данных.

## Основные концепции

### Процесс Failover

1. **Обнаружение сбоя** — система мониторинга фиксирует отказ через heartbeat или health check.
2. **Выбор резерва** — кластерный менеджер определяет целевой узел для активации.
3. **Переконфигурация** — перенос ресурсов (VIP, сервисы) на новый активный узел, перенаправление трафика.

### Механизмы защиты от Split-Brain

**Кворум (Quorum)** — решение принимается только при согласии большинства узлов (`floor(N/2) + 1`). Узел без кворума переходит в пассивный режим. Принцип работы описан в [алгоритме Raft](../../etcd/raft_consensus.md).

**Fencing (Изоляция)** — принудительное отключение сбойного узла от общих ресурсов:
- **STONITH (Shoot The Other Node In The Head)** — физическое отключение питания или перезагрузка через контроллер (IPMI, BMC).

## Практические сценарии

### IP Failover с Keepalived (VRRP)

Failover для виртуального IP-адреса (VIP) на основе протокола VRRP.

**Конфигурация `keepalived.conf`:**

```keepalived
vrrp_script check_app {
  script "/usr/local/bin/check_app.sh"  # Проверка приложения
  interval 2                            # Интервал проверки (сек)
  fall 3                                # Неудач до объявления отказа
  rise 2                                # Успехов до восстановления
}

vrrp_instance VI_WEB {
  state MASTER                          # MASTER или BACKUP
  interface eth0                        # Сетевой интерфейс
  virtual_router_id 51                  # Уникальный ID VRRP-группы
  priority 150                          # Приоритет (выше = активнее)
  advert_int 1                          # Интервал анонсов (сек)

  virtual_ipaddress {
    192.168.1.100/24                    # Виртуальный IP
  }

  track_script {
    check_app                           # Привязка проверки
  }
}
```

Скрипт `check_app.sh` проверяет доступность приложения (`curl`, `systemctl status`).

### Управление кластером с Pacemaker/Corosync

Комплексное решение для управления ресурсами с зависимостями и изоляцией.

**Настройка кластера:**

```bash
# 1. Инициализация кластера
pcs cluster setup my_cluster node1 node2
pcs cluster start --all
pcs property set stonith-enabled=true

# 2. Настройка STONITH (обязательно)
pcs stonith create fence_node1 fence_ipmilan pcmk_host_list=node1 ...
pcs stonith create fence_node2 fence_ipmilan pcmk_host_list=node2 ...

# 3. Создание ресурсов
pcs resource create vip IPaddr2 ip=192.168.1.100
pcs resource create web_server apache

# 4. Ограничения: colocation и order
pcs constraint colocation add web_server with vip INFINITY
pcs constraint order vip then web_server
```

## Дополнительная информация

**Тайминги heartbeat** — баланс между чувствительностью и стабильностью:
- Короткие интервалы → ложные failover при сетевых задержках.
- Длинные интервалы → увеличение времени восстановления (MTTR).

**Тестирование failover** — регулярная имитация отказов:
- Отключение сети (`tc netem`, `iptables DROP`).
- Остановка сервисов (`systemctl stop`, `kill`).
- Отключение питания (IPMI power off).

**Связанные документы:**
- Общие принципы HA — в [обзоре высокой доступности](./ha_overview.md).
- Модели кластеризации — в [кластеризации и балансировке](./ha_clustering_and_load_balancing.md).
- Проблема Split-Brain в БД — в [репликации](../../Databases/Concepts/replication.md).
- Кворум и consensus — в [Raft](../../etcd/raft_consensus.md) и [Consul](../../Consul/consul_consensus.md).
