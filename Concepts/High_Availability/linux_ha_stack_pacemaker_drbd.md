# Стек High Availability: Pacemaker + Corosync + DRBD

Данный технологический стек является стандартом индустрии (актуально на 2026 год) для построения отказоустойчивых кластеров в архитектуре **Shared-Nothing**, где каждый узел обладает собственным хранилищем, синхронизируемым по сети.

## Определения

**Pacemaker** — высокоуровневый менеджер ресурсов кластера (Cluster Resource Manager, CRM). Отвечает за логику управления: запуск, остановку и перемещение ресурсов (VIP, файловые системы, СУБД) между узлами на основе заданных ограничений (constraints) и текущего состояния инфраструктуры.

**Corosync** — низкоуровневая инфраструктура обмена сообщениями (Cluster Executive). Обеспечивает механизмы членства в кластере (Membership) и детектирование сбоев. В современных версиях (Corosync 3.x) использует транспорт **Kronosnet (knet)** для надежной передачи пульса (heartbeat) через несколько сетевых каналов.

**DRBD (Distributed Replicated Block Device)** — программное решение для репликации блочных устройств по сети. В версии 9.x поддерживает репликацию на множество узлов (до 31) и встроенные механизмы предотвращения Split-Brain. Часто управляется через **LINSTOR** в крупных инсталляциях.

**STONITH (Shoot The Other Node In The Head)** — механизм Fencing (изоляции), позволяющий Pacemaker принудительно выключить или перезагрузить сбойный узел (через IPMI, Redfish, SBD или Cloud API), гарантируя, что он не будет одновременно обращаться к общим ресурсам.

## Основные концепции

### Трехуровневая архитектура кластера

1.  **Информационный уровень (Corosync + knet):** Узлы обмениваются статусами по нескольким линкам. knet v3 обеспечивает автоматическое определение MTU и шифрование трафика управления.
2.  **Уровень репликации данных (DRBD):** Обеспечивает идентичность данных на блочном уровне. DRBD 9.3+ использует **Streaming I/O** (потоковый ввод-вывод) для снижения задержек и нагрузки на CPU.
3.  **Уровень управления ресурсами (Pacemaker):** На основе данных от Corosync и агентов ресурсов (OCF) принимает решение о миграции сервисов.

### Протоколы репликации DRBD

| Протокол | Тип | Принцип работы | Применение |
| :--- | :--- | :--- | :--- |
| **Протокол A** | Асинхронный | Запись завершена после попадания в локальный сетевой буфер. | Удаленные площадки (DR), высокая задержка сети. |
| **Протокол B** | Полусинхронный | Запись завершена после достижения данными RAM удаленного узла. | Защита от сбоя питания одного узла при хорошей сети. |
| **Протокол C** | **Синхронный** | Запись завершена только после подтверждения записи на физические диски **обоих** узлов. | **Стандарт для LAN**. Максимальная целостность. |

### Механизмы кворума и защиты

- **Кворум Corosync:** Решение о легитимности кластера принимается большинством нод (`votequorum`). В кластерах из 2 нод используется `wait_for_all` или внешнее устройство `QDevice`.
- **DRBD Native Quorum:** Начиная с версии 9.x, DRBD умеет самостоятельно блокировать I/O на ресурсе, если не видит большинства реплик, предотвращая расхождение данных независимо от Pacemaker.
- **Split-Brain Recovery:** Автоматические политики (например, `after-sb-0pri discard-younger-primary`) позволяют минимизировать ручное вмешательство, но требуют осторожности.

## Практические сценарии

### Настройка Corosync с резервированием (knet)

Пример конфигурации `/etc/corosync/corosync.conf` с двумя независимыми линками для предотвращения изоляции нод:

```conf
totem {
    version: 2
    cluster_name: my_ha_cluster
    transport: knet
    crypto_cipher: aes256
    crypto_hash: sha256
    
    interface {
        linknumber: 0
        knet_link_priority: 10 # Основной линк (например, 10GbE)
    }
    interface {
        linknumber: 1
        knet_link_priority: 5  # Резервный линк
    }
}
quorum {
    provider: corosync_votequorum
    two_node: 1 # Только для кластеров из 2 нод
}
```

### Настройка DRBD 9 с кворумом

Фрагмент описания ресурса в `/etc/drbd.d/r0.res`:

```drbd
resource r0 {
    options {
        quorum majority;
        on-no-quorum io-error; # Блокировать I/O при потере кворума
    }
    net {
        protocol C;
        after-sb-0pri discard-zero-changes;
        after-sb-1pri discard-secondary;
    }
    on node1 { address 10.0.0.1:7788; volume 0 { device /dev/drbd0; disk /dev/sdb; meta-disk internal; } }
    on node2 { address 10.0.0.2:7788; volume 0 { device /dev/drbd0; disk /dev/sdb; meta-disk internal; } }
}
```

### Управление ресурсами через Pacemaker (pcs)

Основные команды для создания связки DRBD + ФС + VIP:

1.  **Настройка STONITH:**
    ```bash
    pcs property set stonith-enabled=true
    pcs stonith create my_fence fence_ipmilan ipaddr=192.168.1.50 login=admin passwd=password
    ```

2.  **Создание ресурса DRBD (Promotable):**
    ```bash
    pcs resource create drbd_res ocf:linbit:drbd drbd_resource=r0 promotable
    ```

3.  **Создание группы ресурсов (VIP + Mount):**
    ```bash
    pcs resource create virtual_ip ocf:heartbeat:IPaddr2 ip=192.168.1.100 cidr_netmask=24
    pcs resource create fs_res ocf:heartbeat:Filesystem device="/dev/drbd0" directory="/mnt/data" fstype="xfs"
    pcs constraint colocation add fs_res with master drbd_res-clone INFINITY
    pcs constraint order promote drbd_res-clone then start fs_res
    ```

## Практические рекомендации

1.  **LVM и DRBD:** При использовании LVM поверх DRBD обязательно настройте фильтр в `/etc/lvm/lvm.conf`, чтобы LVM сканировал только `/dev/drbd*` и игнорировал нижележащие физические устройства (`/dev/sdb`), иначе возникнут конфликты метаданных.
    - `filter = [ "a|/dev/drbd.*|", "r|.*|" ]`
2.  **Bitmap Block Size:** Для разделов более 10 ТБ увеличивайте размер блока битмапа при инициализации (`drbdadm create-metadata --bitmap-block-size 65536`), чтобы сэкономить RAM.
3.  **Мониторинг:** Используйте **DRBD Reactor** для передачи метрик в Prometheus. Это современная альтернатива старым bash-скриптам.
4.  **Сетевой тюнинг:** Для репликации 10Gbps+ настройте `sndbuf-size` и `rcvbuf-size` в конфиге DRBD для достижения максимальной пропускной способности.

## Дополнительная информация

- **[Механизмы Failover и Heartbeat](./ha_failover_mechanisms.md)** — глубокое погружение в кворум и STONITH.
- **[Кластеризация и балансировка нагрузки](./ha_clustering_and_load_balancing.md)** — выбор между Active-Passive и Active-Active.
- **[Диагностика системы (sosreport)](../../Linux/Diagnostics/sos_report.md)** — сбор логов кластера для техподдержки.
- **[Кластеризация в Proxmox](../../Proxmox/proxmox_cluster.md)** — реализация HA на базе Corosync в среде виртуализации.
