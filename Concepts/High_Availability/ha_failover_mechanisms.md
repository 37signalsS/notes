# Механизмы переключения при отказе (Failover) и пульс (Heartbeat)

## Предварительные требования

Для полноценного понимания данного раздела предполагается знакомство с:
- Протоколами VRRP, BFD, ARP и базовыми концепциями сетевого взаимодействия (TCP/IP)
- Принципами **[высокой доступности](./ha_overview.md)**: RTO, RPO, MTTR, SPOF
- Основами **[кластеризации и балансировки нагрузки](./ha_clustering_and_load_balancing.md)**: Active-Active, Active-Passive, кворум
- Концепциями **[консенсуса (Raft/Paxos)](../../etcd/raft_consensus.md)** и кворума
- Инструментами мониторинга (Prometheus, Zabbix) и средствами диагностики сети (tcpdump, ip, ss)

---

## Определения

**Failover (Переключение при отказе)** — автоматизированный процесс передачи функций от отказавшего компонента (сервера, сервиса, сетевого интерфейса или целого региона) к резервному. Это фундамент **[высокой доступности](./ha_overview.md)**, задача которого — минимизация **MTTR** (Mean Time To Repair) и обеспечение непрерывности бизнеса в рамках заданного **RTO** (Recovery Time Objective).

**Методы контроля состояния (Health Monitoring):**
- **Heartbeat (Пульс):** пассивный механизм, при котором узел («агент») периодически отправляет пакеты по сети, сигнализируя о своей жизнеспособности. Отсутствие пакетов в течение заданного интервала интерпретируется как сбой.
- **Health Checks (Проверки здоровья):** активный механизм, при котором внешняя система (балансировщик, оркестратор) имитирует реальный запрос к сервису (HTTP GET, TCP connect, gRPC health) для проверки его функциональности на прикладном уровне.

**Split-Brain (Расщепление мозга)** — катастрофическое состояние распределенной системы, возникающее при потере связи между узлами (Network Partition). Узлы перестают видеть друг друга, каждый считает себя единственным выжившим и пытается захватить ресурсы (VIP, диски, право на запись в БД). Это неизбежно ведет к порче данных (Data Corruption).

## Основные концепции

### Жизненный цикл переключения (Failover Lifecycle)

Процесс переключения — это не просто смена IP, а сложная последовательность действий, направленная на сохранение целостности данных:

1.  **Обнаружение (Detection):** Фиксация сбоя. Стандартом де-факто для критичных систем стал протокол **BFD (Bidirectional Forwarding Detection)**, позволяющий обнаруживать обрывы линков на миллисекундном уровне.
2.  **Изоляция (Fencing):** Гарантированное отстранение сбойного узла от ресурсов. Если мы не уверены, что старый мастер «мертв» (он может просто зависнуть), мы обязаны его изолировать перед запуском нового.
3.  **Выбор лидера (Leader Election):** Процесс консенсуса. В простых системах (Keepalived) используется статический приоритет. В сложных (etcd, Consul, Kubernetes) — алгоритмы консенсуса (**Raft**, **Paxos**), требующие кворума.
4.  **Активация (Promotion):** Перенос ресурсов на новый узел. Включает в себя Gratuitous ARP (для VIP), монтирование файловых систем и уведомление соседних сервисов.

### Типы переключений

| Тип | Контекст | Влияние на систему |
| :--- | :--- | :--- |
| **Switchover (Плавное)** | Плановые работы, обновление ядра. | Минимальное. Сессии завершаются штатно, данные синхронизированы. |
| **Failover (Аварийное)** | Hardware failure, Kernel panic, сбой питания. | Агрессивное. TCP-соединения рвутся, возможна потеря данных (если репликация асинхронная). |

### Проблема чувствительности и дребезг (Flapping)

Критически важный баланс для инженера:
*   **Слишком высокая чувствительность:** кластер будет переключаться при малейшей задержке в сети, создавая нестабильность («дребезг»).
*   **Слишком низкая чувствительность:** система будет простаивать минуты, пока мониторинг не поймет, что сервер мертв.

**Решение:** Использование Hold-off таймеров и экспоненциальных задержек для возврата роли (Preemption Delay), чтобы предотвратить циклические переключения.

**Практическая настройка anti-flapping в Keepalived:**

```keepalived
vrrp_instance VI_1 {
  state MASTER
  interface eth0
  virtual_router_id 51
  priority 150
  advert_int 1

  # Защита от дребезга: 3 провала (3 сек) для исключения, 5 успехов (5 сек) для возврата
  # + nopreempt предотвращает возврат роли без подтверждения стабильности
  nopreempt

  # Увеличение advert_int до 2-3 сек для сред с нестабильной сетью
  # advert_int 2

  authentication {
    auth_type PASS
    auth_pass <секрет_32_символа>
  }

  virtual_ipaddress {
    192.168.1.100/24
  }

  track_script {
    check_service
  }
}

vrrp_script check_service {
  script "/usr/bin/curl -sf http://localhost/health || exit 1"
  interval 2
  fall 3      # 3 неудачи = переход в BACKUP (6 сек при interval=2)
  rise 5      # 5 успехов = возврат в строй (10 сек) — медленнее чем fall
  weight -20  # Снижение приоритета при провале (для плавного переключения)
}
```

**Параметры anti-flapping для разных сценариев:**

| Сценарий | `interval` | `fall` | `rise` | `nopreempt` | Пояснение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Критичный сервис (мгновенный)** | 1 | 3 | 2 | No | Быстрое переключение (3 сек), возврат через 2 сек |
| **Веб-сервис** | 2 | 3 | 5 | Yes | Сбалансированное (6 сек detection, 10 сек recovery) |
| **База данных** | 2 | 5 | 5 | Yes | Медленное (10 сек), чтобы не терять соединения |
| **Нестабильная сеть** | 3 | 5 | 10 | Yes | Максимальная устойчивость к ложным срабатываниям |

**Валидация anti-flapping конфигурации:**

```bash
# Проверка синтаксиса keepalived.conf
keepalived --dont-fork --log-console --check

# Проверка текущего состояния VRRP
ip addr show eth0 | grep 192.168.1.100

# Мониторинг переключений в реальном времени
journalctl -u keepalived -f

# Проверка multicast-группы
ip maddr show dev eth0

# Тест: принудительная смена состояния (только для тестовых сред!)
# echo "master" > /proc/self/fd/2  # симуляция перехода в BACKUP
```

## Механизмы реализации на разных уровнях

#### Сетевой уровень (L2/L3)
- **Virtual IP (VIP) через VRRP:** Keepalived остается основным инструментом для управления плавающим IP. Работает быстро, но ограничен пределами одной подсети (L2).
- **Anycast (BGP):** Позволяет анонсировать один IP из разных дата-центров. При падении узла BGP-маршрут отзывается, и трафик перенаправляется провайдером на ближайший живой узел.

#### Глобальный уровень (DNS/GSLB)
Переключение между регионами.
*   **Метод:** Балансировщик DNS отдает IP живого региона на основе Health Checks.
*   **Ограничение:** TTL (кеширование на стороне клиента). Используются значения TTL 10-30 сек.

#### Клиентский уровень (Client-side Failover)
Логика «умного клиента» (например, драйверы PostgreSQL или MongoDB). Клиент сам пробует следующий IP из списка при ошибке. Это самый дешевый, но сложный в управлении способ.

#### Уровень Service Mesh
**Outlier Detection (Istio/Linkerd):** Динамическое исключение «плохих» подов из балансировки без полной остановки сервиса.

### Сравнение архитектурных подходов к резервированию

Выбор метода зависит от критичности данных и допустимого времени простоя:

| Подход | Механизм | Синхронизация данных | Управление | Плюсы / Минусы |
| :--- | :--- | :--- | :--- | :--- |
| **DNS-based** | A/SRV записи | Нет (независимые узлы) | TTL в DNS | (+) Простота. (-) Задержки кэширования DNS, нет контроля состояния. |
| **Keepalived + Warmspare** | VIP (VRRP) | Отложенная (Backup/Rsync) | Скрипты `notify` | (+) Простота, независимые ФС. (-) Потеря данных между синхронизациями. |
| **Pacemaker + DRBD** | VIP + Resources | Реальное время (Блочная) | CRM (Pacemaker) | (+) Актуальные данные, полный контроль. (-) Сложность, риск Split-Brain. |

### Механизмы защиты от Split-Brain

**Кворум (Quorum)** — математический принцип принятия решений большинством голосов (`floor(N/2) + 1`). Сегмент кластера, оставшийся в меньшинстве (Minority), обязан прекратить обслуживание запросов на запись и освободить ресурсы.

*   **Кластеры из 2 узлов:** Являются проблемными, так как падение одного узла лишает оставшийся кворума.
    *   *Решение:* Использование **QDevice (Quorum Device)** или **QDisk**. Это внешний легковесный свидетель (Witness), который не хранит данные, но дает дополнительный голос («арбитраж») для достижения большинства.
*   **Реализации консенсуса:** **[Алгоритм Raft](../../etcd/raft_consensus.md)** (etcd), **[Paxos](../../Consul/consul_consensus.md)** (Consul).

**Fencing (Изоляция ресурсов)** — гарантированное лишение узла возможности влиять на общую инфраструктуру. Различают два уровня:

1.  **Soft Fencing (Resource-level):** Попытка остановить узел через системные команды (SSH `systemctl stop`, API облачного провайдера). Риск: узел может не ответить из-за зависания ядра.
2.  **Hard Fencing (Node-level / STONITH):** Принудительное воздействие на «железо».
    *   **STONITH (Shoot The Other Node In The Head):** Отключение питания через IPMI, BMC, iDRAC или управляемые PDU.
    *   **Fabric Fencing:** Блокировка порта на FC/Ethernet коммутаторе, лишающая узел доступа к сети или хранилищу.
     *   **Storage Fencing:** Использование SCSI-3 Persistent Reservations для монопольного захвата диска новым лидером.

### Целостность данных при Failover

Failover — это не только смена IP или роли, но и гарантия того, что данные не повредились в процессе переключения. Без проверки целостности существует риск "тихого" повреждения данных, которое проявится позже.

#### Проверка целостности данных

Перед и после failover необходимо убедиться, что данные на новом мастере актуальны и неповреждены:

1.  **Контрольные суммы (Checksums):**
    - **Для файлов:** `sha256sum /path/to/file`, `md5sum` (для быстрой проверки)
    - **Для баз данных:** `pg_checksums` (PostgreSQL), `CHECKSUM TABLE` (MySQL), `db.hash()` (MongoDB)
    - **Для блочных устройств:** `md5sum /dev/sdX`, `zfs scrub`

2.  **Сравнение реплик:**
    - **PostgreSQL:** `pg_rewind` (проверка и исправление расхождений), `pg_comparator`
    - **MySQL:** `pt-table-checksum` (Percona Toolkit), `replica_parallel_workers`
    - **MongoDB:** `rs.printSecondaryReplicationInfo()`, сравнение `db.hash()`

3.  **Валидация после failover:**
    - Проверка `read_only` флага на новом мастере (должен быть OFF)
    - Проверка репликации: `SHOW SLAVE STATUS` (MySQL), `rs.status()` (MongoDB)
    - Тест записи: вставка тестовой записи и её удаление

#### Data Drift и его последствия

**Data Drift** — расхождение данных между Primary и Secondary после failover. Причины:
- Асинхронная репликация с задержкой
- Сетевые разрывы во время репликации
- Ошибки при применении транзакций

**Последствия:**
- Потеря данных (если новый мастер не имеет последних изменений)
- Некорректная работа приложения (ошибки целостности)
- Каскадные сбои при попытке отката (rollback)

#### Процедуры проверки

| Этап | Действие | Команды |
| :--- | :--- | :--- |
| **До failover** | Проверка репликации | `SHOW SLAVE STATUS`, `rs.printSecondaryReplicationInfo()` |
| **Во время failover** | Мониторинг логов | `journalctl -u pacemaker -f`, `watch -n1 'cat /proc/drbd'` |
| **После failover** | Проверка целостности | `pg_checksums`, `pt-table-checksum`, `db.hash()` |
| **Пост-фактум** | Аудит данных | Сравнение контрольных сумм, проверка репликации |

## Практические сценарии

### Настройка IP Failover с Keepalived (VRRP)

Пример конфигурации `/etc/keepalived/keepalived.conf` для обеспечения отказоустойчивости балансировщика с проверкой состояния сервиса.

```keepalived
vrrp_script check_service {
  script "/usr/bin/pgrep nginx"       # Проверка наличия процесса nginx
  interval 2                          # Каждые 2 секунды
  fall 3                              # 3 неудачи = переход в BACKUP
  rise 2                              # 2 успеха = возврат в строй
}

vrrp_instance VI_1 {
  state MASTER                        # Узел-лидер
  interface eth0                      # Сетевой интерфейс для VIP
  virtual_router_id 51                # ID группы (одинаковый в паре)
  priority 150                        # Приоритет (на BACKUP должен быть ниже, например 100)
  advert_int 1                        # Интервал анонсов (Heartbeat)

  authentication {
    auth_type PASS
    auth_pass <секрет_32_символа>         # Пароль для VRRP-трафика
  }

  virtual_ipaddress {
    192.168.1.100/24                  # Плавающий виртуальный IP
  }

  track_script {
    check_service
  }
}
```

**Системная настройка (оба узла):**

```bash
# Разрешить привязку VIP до его назначения интерфейсу
echo "net.ipv4.ip_nonlocal_bind=1" | sudo tee -a /etc/sysctl.d/99-ha.conf
sudo sysctl -p /etc/sysctl.d/99-ha.conf

# Параметры ARP для корректного переключения VIP
sudo sysctl -w net.ipv4.conf.all.arp_ignore=0
sudo sysctl -w net.ipv4.conf.all.arp_announce=1
sudo sysctl -w net.ipv4.conf.all.rp_filter=2

# Включить persistently
cat <<EOF | sudo tee /etc/sysctl.d/99-ha.conf
net.ipv4.ip_nonlocal_bind=1
net.ipv4.conf.all.arp_ignore=0
net.ipv4.conf.all.arp_announce=1
net.ipv4.conf.all.rp_filter=2
EOF
sudo sysctl -p /etc/sysctl.d/99-ha.conf
```

**Проверка параметров:**
```bash
sysctl net.ipv4.ip_nonlocal_bind net.ipv4.conf.all.arp_ignore net.ipv4.conf.all.arp_announce net.ipv4.conf.all.rp_filter
```

**Валидация IP Failover:**

```bash
# Проверка состояния VRRP
sudo ip addr show eth0 | grep 192.168.1.100

# Тест failover: остановка сервиса на MASTER
sudo systemctl stop nginx
# → VIP должен мигрировать на BACKUP в течение 1-3 сек

# Проверка логов VRRP
sudo journalctl -u keepalived -f

# Проверка ARP-таблицы на соседнем хосте
arp -a | grep 192.168.1.100
```

### Кластерное управление ресурсами (Pacemaker + Corosync)

Стек для управления сложными Stateful-сервисами (PostgreSQL, NFS, iSCSI). Pacemaker выступает оркестратором ресурсов, Corosync обеспечивает обнаружение узлов и межпроцессное общение (messaging layer).

**Шаг 1: Подготовка узлов (оба узла)**

```bash
# Установка пакетов (RHEL/Debian)
sudo yum install -y pacemaker corosync pcs fence-agents ipmilan
# или
sudo apt install -y pacemaker corosync pcs fence-agents

# Настройка пароля для pcs-директора (одинаковый на обоих узлах)
sudo passwd hacluster

# Запуск и автозапуск pcsd
sudo systemctl enable --now pcsd
```

**Шаг 2: Инициализация кластера**

```bash
# Авторизация узлов (выполняется с любого узла)
sudo pcs host auth node1 node2 -u hacluster -p <пароль_hacluster>

# Создание кластера
sudo pcs cluster setup my_ha_cluster node1 node2
sudo pcs cluster start --all
sudo pcs cluster enable --all
```

**Шаг 3: Настройка STONITH (Критически важно для защиты от Split-Brain)**

```bash
# Включение STONITH
sudo pcs property set stonith-enabled=true

# Пример: fencing через IPMI
sudo pcs stonith create fence_node1 fence_ipmilan \
  ipaddr="10.0.0.1" login="admin" passwd="ipmi_password" \
  pcmk_host_list="node1" lanplus=1

sudo pcs stonith create fence_node2 fence_ipmilan \
  ipaddr="10.0.0.2" login="admin" passwd="ipmi_password" \
  pcmk_host_list="node2" lanplus=1

# Разрешить запуск ресурсов на любом узле (после настройки STONITH)
sudo pcs property set no-quorum-policy=ignore
```

**Шаг 4: Создание ресурсов и ограничений**

```bash
# VIP
sudo pcs resource create virtual_ip IPaddr2 ip=192.168.1.100 cidr_netmask=24

# Сервис (пример: Apache)
sudo pcs resource create web_app ocf:heartbeat:apache \
  configfile="/etc/httpd/conf/httpd.conf"

# Colocation: web_app всегда там же, где virtual_ip
sudo pcs constraint colocation add web_app with virtual_ip INFINITY

# Order: virtual_ip запускается ДО web_app
sudo pcs constraint order virtual_ip then web_app

# Таймаут: если web_app не запустится за 60 сек, перезапуск на другом узле
sudo pcs resource op defaults timeout=60s
```

**Валидация:**

```bash
# Состояние кластера
sudo pcs status
# → Online: [ node1 node1 ]
# → Full list of resources:
#   virtual_ip    (ocf::heartbeat:IPaddr2):   Started node1
#   web_app       (ocf::heartbeat:apache):    Started node1

# Детали ресурсов
sudo pcs resource status

# Проверка STONITH
sudo pcs stonith status
# → fence_node1 (fence_ipmilan): Started node2
# → fence_node2 (fence_ipmilan): Started node1

# Проверка ограничений
sudo pcs constraint show
```

**Тестирование failover:**

```bash
# Имитация отказа: остановка.cluster на node1
sudo pcs cluster stop node1
# → Ресурсы должны перенестись на node2 в течение 30-60 сек
# → Проверьте: sudo pcs status на node2

# Имитация kernel panic (для проверки STONITH)
sudo echo c > /proc/sysrq-trigger
# → fence_ipmilan должен выключить/перезагрузить node1
# → Ресурсы запустятся на node2

# Восстановление node1
sudo pcs cluster start node1
# → Ресурсы НЕ должны вернутся на node1 (если nopreempt или default-behavior)
```

### DNS-level Failover (GSLB для on-premise)

Для географически распределенных кластеров без облачных провайдеров:

- **DNS-based failover:** Балансировщик DNS (PowerDNS, BIND с health-check плагинами) отдает A/SRV-записи только живых узлов.
- **Ограничение TTL:** Минимальные значения TTL 10-30 сек для быстрого переключения, но клиенты могут кешировать старые записи.
- **Альтернатива:** Anycast через BGP (требует собственного AS и IP-пространства) — маршрут BGP автоматически переключается на ближайший живой узел при отказе.

## Диагностика и устранение неисправностей

| Проблема | Вероятная причина | Первые шаги | Диагностические команды |
| :--- | :--- | :--- | :--- |
| **Flapping (Дребезг)** | Нестабильный линк или малый таймаут Heartbeat. | Увеличить `advert_int` или `fall` count. Проверить загрузку CPU (планировщик может задерживать пакеты). | `journalctl -u keepalived -f` — мониторинг VRRP-событий; `tcpdump -i eth0 vrrp` — перехват VRRP-пакетов; `ping -c 100 -i 0.1 <VIP>` — проверка доступности VIP |
| **Оба узла MASTER** | Split-Brain (заблокирован UDP/VRRP трафик). | Проверить правила Firewall (iptables/nftables). Проверить Unicast/Multicast настройки. | `iptables -L -n -v \| grep 112` — проверка правил для VRRP (протокол 112); `ip maddr show dev eth0` — проверка multicast-группы; `sudo pcs status` — состояние кластера Pacemaker |
| **Узел не отдает MASTER** | Hold-off таймер или `nopreempt`. | Проверить флаг `nopreempt` в конфиге. Проверить логи на наличие ошибок `vrrp_script`. | `sudo crm_verify -L -V` — проверка конфигурации CIB; `sudo pcs resource failcount show` — счетчики отказов ресурсов |
| **Fencing Loop** | Циклическая перезагрузка узла по STONITH. | Проверить связь с QDevice. Убедиться, что узел успевает загрузиться и войти в кластер до таймаута. | `sudo pcs stonith history` — история fencing-событий; `ipmitool -H <BMC_IP> -U admin -P pass power status` — проверка доступности BMC; `sudo journalctl -u corosync` — логи Corosync |
| **VIP не мигрирует** | Проблема с track_script или сетью. | Проверить, что скрипт проверки возвращает exit 0 на BACKUP. Проверить доступность VIP через `ip addr`. | `ip addr show <iface> \| grep <VIP>` — проверка привязки VIP; `sudo keepalived --dont-fork --log-console` — отладочный запуск Keepalived; `sudo pcs constraint show -a` — проверка ограничений |
| **VRRP аутентификация не работает** | Несовпадение паролей или `auth_type` между узлами. | Сравнить `auth_type` и `auth_pass` в конфигах MASTER и BACKUP. | `grep -E "auth_type|auth_pass" /etc/keepalived/keepalived.conf` — проверка конфигурации; `tcpdump -i eth0 vrrp -A` — перехват VRRP-пакетов для проверки аутентификации |
| **Corosync: узел не joining** | Проблемы с firewall, MTU или knet. | Проверить открытые порты UDP 5404-5405, MTU на интерфейсах. | `corosync-cfgtool -s` — статус линков; `ss -u -lpn \| grep 540` — проверка портов; `ip link show <iface>` — проверка MTU |
| **STONITH не срабатывает** | Неправильный агент fencing или нет доступа к BMC. | Проверить connectivity к BMC: `ping <BMC_IP>`, `ipmitool -H <BMC_IP> -U admin -P pass power status`. | `sudo pcs stonith show` — список агентов; `stonith_admin -H` — тест fencing; `sudo pcs stonith history` — история |
| **Дребезг после ребута** | Все узлы стартуют одновременно и борются за MASTER. | Проверить задержки запуска systemd для keepalived/pacemaker. | `systemctl show -p FragmentPath,After keepalived` — зависимости сервиса; `timedatectl` — синхронизация часов; `sudo journalctl -u keepalived` — логи старта |
| **Потеря кворума при 2 узлах** | Отсутствует QDevice или `two_node: 1`. | Проверить настройку quorum в corosync.conf. | `cat /etc/corosync/corosync.conf \| grep -A5 quorum`; `corosync-quorumtool` — текущее состояние кворума; `sudo pcs quorum show` |
| **pcs: ресурс не запускается** | OCF-агент возвращает ошибку или не хватает зависимостей. | Проверить логи CRM: `sudo pcs resource debug-start <resource>`. | `pcs resource config <resource>` — конфигурация; `crm_resource -r <resource> -V` — детали; `pcs resource cleanup <resource>` |

## Лучшие практики (Best Practices)

1. **STONITH обязателен для кластеров:** Без fencing любой failover ненадежен — «мертвый» узел может продолжать писать в общее хранилище. Для on-premise: IPMI/BMC; для виртуальных машин: `fence_virt` / `fence_xvm`.
2. **nopreempt для production-сред:** Предотвращает возврат роли восстановившимся узлом до полной стабильности. Исключение — среды с строгими требованиями к производительности, где master-узел значительно мощнее.
3. **Мониторинг health-check скриптов:** Убедитесь, что скрипт проверки возвращает корректный exit code на обоих узлах. Тестируйте: `sudo /path/to/check_script && echo "OK" || echo "FAIL"`.
4. **Регулярное тестирование failover:** Минимум 1 раз в квартал выполняйте плановый failover. Используйте Chaos Engineering-подходы: `iptables -A INPUT -p vrrp -j DROP`, `kill -9 <pid>`, `echo c > /proc/sysrq-trigger`.
5. **Разделение VLAN для кластерного трафика:** Выделите отдельный VLAN (или L3-сеть) для VRRP/Corosync/Pacemaker, чтобы обнаружение узлов не зависело от общего сетевого трафика.
6. **Логирование и алертинг:** Настройте алерты на:
   - Смену ролей VRRP (`journalctl -u keepalived | grep "Transition to MASTER"`)
   - Fencing-события (`pcs stonith history`)
   - Кворум кластера (`pcs status | grep "Current DC"`)
7. **Автозапуск кластера после ребута:** Убедитесь, что `pcs cluster enable --all` выполнен и сервисы `corosync`/`pacemaker`/`keepalived` добавлены в автозапуск (`systemctl enable`).
8. **Документирование IPMI/BMC:** Ведите реестр IP-адресов, логинов и паролей BMC для всех узлов. fencing-устройства — критическая инфраструктура, их недоступность блокирует failover.

## Граничные случаи и ограничения (Edge Cases)

- **Кластер из 2 узлов без QDevice:** При падении одного узла второй теряет кворум и не может обслуживать запросы на запись. Решение: добавить QDevice ( witness) или перейти на 3+ узла.
- **Сеть с высокой задержкой (cross-datacenter):** Если RTT между узлами > 100 мс, стандартные интервалы VRRP (1 сек) будут вызывать ложные failover. Увеличьте `advert_int` до 3-5 сек и `fall` до 5-10.
- **Split-Brain при асимметричной сети:** Если узлы видят друг друга, но один из маршрутов однонаправленный (асимметрия), VRRP-пакеты могут не доходить. Проверяйте однонаправленную связь: `ping` в обе стороны + `tcpdump` на обоих узлах.
- **Fencing через IPMI с задержкой:** Если BMC-интерфейс отвечает медленно (> 5 сек), fencing может завершиться до фактического отключения узла. Увеличьте `pcmk_delay_max` в конфигурации stonith.
- **Приоритет VRRP и preempt:** Если MASTER-узел имеет приоритет 200, а BACKUP — 100, и на BACKUP установлен `nopreempt`, BACKUP никогда не вернет роль MASTER после восстановления. Используйте `preempt_delay` вместо полного `nopreempt`, если нужен возврат с задержкой.
- **Дребезг при восстановлении питания:** Если в стойке отключалось питание и все узлы включились одновременно, они могут начать борьбу за MASTER. Решение: `vrrp_script` с `weight` + `nopreempt` или рандомизация задержки запуска Keepalived.
- **NTP дрейф > 500 мс:** Corosync/Pacemaker используют время для детекции сбоев. Дрейф часов приводит к ложным fencing-событиям. Настройте `chrony` с `makestep` и мониторьте `chronyc tracking`.
- **ARP кеширование на соседних хостах:** После failover соседние хосты могут еще держать старый MAC-адрес в ARP-таблице. Решение: `garp_interval` в Keepalived или `arping` после подъема VIP.
- **Firewall блокирует VRRP/Corosync:** Порт UDP 112 (VRRP) и UDP 5404-5405 (Corosync) должны быть открыты между узлами кластера.
- **Конфликт VIP с существующим адресом:** Если VIP уже занят другим устройством в сети, VRRP-переключение не произойдет. Проверяйте: `arping -D -I eth0 192.168.1.100`.
- **Fencing при недоступном BMC:** Если BMC недоступен, STONITH завершится таймаутом. Добавьте redundant BMC-интерфейсы или используйте Fabric Fencing (блокировка порта на коммутаторе).
- **Долгий запуск PostgreSQL Patroni:** При холодном старте Patroni может не успеть запуститься за таймаут `start timeout`. Увеличьте `pcs resource op defaults timeout=120s` для stateful-сервисов.

## Дополнительная информация

### Настройка таймингов и предотвращение Flapping

Тайминги Heartbeat определяют баланс между скоростью обнаружения отказа и стабильностью системы:
- **Интервал (Interval):** Частота отправки сигналов (обычно 1 секунда). Для критичных систем используется **BFD** с интервалом 50-100 мс.
- **Таймаут (Dead interval):** Время, после которого узел считается мертвым. Обычно `3 * Interval`.
- **Hold-off (Preemption Delay):** Задержка перед возвратом роли MASTER восстановившемуся узлу. Рекомендуется ставить 30-300 секунд, чтобы убедиться в стабильности узла после загрузки.

### Методы тестирования Failover (Chaos Engineering)

Механизмы переключения должны регулярно проверяться:
1. **Сетевая изоляция:** Блокировка UDP-порта 5405 (Corosync) или VRRP-пакетов через `iptables -A INPUT -p vrrp -j DROP`. Проверка перехода ролей.
2. **Hard Reboot:** Принудительная перезагрузка мастера через `echo c > /proc/sysrq-trigger` (Kernel Panic). Проверка срабатывания STONITH и корректного захвата ресурсов резервом.
3. **Ресурсный сбой:** Остановка процесса через `kill -9`. Проверка способности Pacemaker/Kubernetes перезапустить сервис локально перед выполнением Failover.

**См. также:**
- **[Обзор High Availability](./ha_overview.md)** — базовые метрики (RTO, RPO) и архитектурные принципы HA.
- **[Кластеризация и балансировка нагрузки](./ha_clustering_and_load_balancing.md)** — сравнение моделей Active-Passive и Active-Active, алгоритмы балансировки.
- **[Управление задержками (Tail Latency)](./tail_latency_mitigation.md)** — паттерны Circuit Breaker, Retry Budget и их связь с failover.

---

## Контрольный список проектирования Failover

- [ ] Определены критичные сервисы и их RTO/RPO
- [ ] Выбран механизм обнаружения отказа (BFD / VRRP / Health Check)
- [ ] Настроен fencing (STONITH или equivalent) для всех узлов
- [ ] Кворум обеспечен (3+ узла или QDevice для 2-узловых кластеров)
- [ ] Настроены anti-flapping параметры (fall/rise/nopreempt)
- [ ] Протестирован failover вручную (kill процесса, остановка кластера, iptables-блокировка)
- [ ] Настроен мониторинг fencing-событий и смены ролей
- [ ] Документированы IPMI/BMC-данные для всех узлов
- [ ] Автозапуск кластерных сервисов после ребута проверен
