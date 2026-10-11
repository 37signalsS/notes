# Стек высокой доступности: Pacemaker + Corosync + DRBD

**Актуально для:** Pacemaker 2.1.x, Corosync 3.x, DRBD 9.x

Данный технологический стек является индустриальным стандартом для построения отказоустойчивых кластеров в архитектуре **Shared-Nothing**, где каждый узел обладает собственным локальным хранилищем, синхронизируемым по сети. Это позволяет избежать единой точки отказа (SPOF) в виде общего дискового массива (SAN).

## Определения

**Pacemaker** — высокоуровневый менеджер ресурсов кластера (Cluster Resource Manager, CRM).
*   **Зачем нужен:** Он управляет логикой кластера. На основе текущего состояния узлов и заданных правил (constraints) Pacemaker принимает решение о том, где именно должен быть запущен ресурс (VIP, СУБД, файловая система), и обеспечивает автоматическое восстановление при сбоях.

**Corosync** — низкоуровневая инфраструктура обмена сообщениями (Cluster Executive).
*   **Зачем нужен:** Обеспечивает механизмы членства в кластере (Membership) и детектирование сбоев узлов. В современных версиях использует транспорт **Kronosnet (knet)**, который позволяет объединять до 8 сетевых линков в один отказоустойчивый канал с поддержкой шифрования и автоматического MTU.

**DRBD (Distributed Replicated Block Device)** — программное решение для репликации блочных устройств по сети (часто называемое «сетевым RAID 1»).
*   **Зачем нужен:** Обеспечивает идентичность данных на дисках разных узлов. Начиная с версии 9.x, поддерживает репликацию на множество узлов (до 31) и управление через **LINSTOR**.

**STONITH (Shoot The Other Node In The Head)** — механизм изоляции (Fencing), позволяющий принудительно выключить или перезагрузить сбойный узел.
*   **Зачем нужен:** Это критически важный компонент для предотвращения **Split-Brain**. Он гарантирует, что узел, который перестал отвечать, действительно выключен и не начнет одновременно с новым мастером писать в реплицируемый диск, что привело бы к безвозвратной порче данных.

## Основные концепции

### Трехуровневая архитектура кластера

1.  **Информационный уровень (Corosync + knet):** «Сердцебиение» кластера. Узлы обмениваются статусами. knet v3 обеспечивает автоматическое переключение между сетевыми интерфейсами при обрыве кабеля или сбое коммутатора.
2.  **Уровень репликации данных (DRBD):** Работает на уровне ядра (модуль `drbd.ko`). Все операции записи на локальный диск перехватываются и дублируются на удаленные узлы.
3.  **Уровень управления ресурсами (Pacemaker):** Мозг системы. На основе данных от Corosync и агентов ресурсов (Resource Agents, OCF) управляет жизненным циклом сервисов.

### Протоколы репликации DRBD

| Протокол | Тип | Принцип работы | Применение |
| :--- | :--- | :--- | :--- |
| **Протокол A** | Асинхронный | Запись подтверждается локально, когда данные попали в локальный сетевой буфер. | Гео-удаленные площадки (DR), где RTT > 10 мс. |
| **Протокол B** | Полусинхронный | Запись подтверждается, когда данные достигли оперативной памяти (RAM) удаленного узла. | Защита от сбоя питания одного узла при сохранении высокой скорости записи. |
| **Протокол C** | **Синхронный** | Запись подтверждается только после записи на физические диски **обоих** узлов. | **Стандарт для локальных сетей**. Гарантирует нулевой RPO (без потери данных). |

### Механизмы кворума и защиты

- **Кворум Corosync:** Решение о легитимности кластера принимается большинством нод (`votequorum`). В кластерах из 2 нод используется флаг `two_node: 1` или внешнее устройство-арбитр **QDevice**.
- **DRBD Native Quorum:** Начиная с версии 9.x, DRBD умеет самостоятельно блокировать операции ввода-вывода (I/O) на ресурсе, если не видит большинства реплик. Это защищает данные даже при сбое Pacemaker.
- **Интеграция SBD (Storage Based Death):** Альтернатива IPMI, использующая маленькое общее блочное устройство (или зарезервированное место на DRBD) для обмена командами выключения («poison pill»).

## Требования (Prerequisites)

Перед развертыванием кластера необходимо обеспечить выполнение следующих условий:

1.  **ОС и пакеты:** Установленные пакеты `pacemaker`, `pcs`, `corosync`, `drbd-utils` на всех узлах.
2.  **Сеть:**
    *   Минимум два независимых сетевых интерфейса для Corosync (рекомендуется задержка < 2 мс).
    *   Открытые порты: UDP 5404-5405 (Corosync), TCP 7788-7799 (DRBD), TCP 2224 (pcsd).
3.  **Диски:** Наличие выделенных неразмеченных дисков или разделов (например, `/dev/sdb`) одинакового размера на обоих узлах для DRBD.
4.  **Синхронизация времени:** Настроенный `chrony` или `ntp`. Разница во времени между узлами кластера недопустима.

## Практические сценарии

### Шаг 1: Инициализация DRBD 9

На обоих узлах создаем описание ресурса в `/etc/drbd.d/r0.res`:

```drbd
resource r0 {
    options {
        quorum majority;        # Защита на уровне DRBD
        on-no-quorum io-error; # Блокировать запись при потере связи
    }
    net {
        protocol C;            # Синхронная репликация
        after-sb-0pri discard-zero-changes;
        after-sb-1pri discard-secondary;
    }
    on node1 { address 10.0.0.1:7788; volume 0 { device /dev/drbd0; disk /dev/sdb; meta-disk internal; } }
    on node2 { address 10.0.0.2:7788; volume 0 { device /dev/drbd0; disk /dev/sdb; meta-disk internal; } }
}
```

**Инициализация (выполнить на обоих узлах):**
```bash
drbdadm create-md r0
drbdadm up r0
# На первом узле (только один раз!) принудительно сделать его первичным для начала синхронизации:
drbdadm primary --force r0
```

### Шаг 2: Настройка Corosync с резервированием

Пример конфигурации `/etc/corosync/corosync.conf` с использованием knet:

```conf
totem {
    version: 2
    cluster_name: ha_cluster_prod
    transport: knet
    interface {
        linknumber: 0
        knet_link_priority: 10 # Линк 1 (например, выделенная сеть HA)
    }
    interface {
        linknumber: 1
        knet_link_priority: 5  # Линк 2 (общая сеть предприятия)
    }
}
quorum {
    provider: corosync_votequorum
    two_node: 1
}
```

### Шаг 3: Управление ресурсами через pcs

После запуска сервисов (`systemctl start pcsd corosync pacemaker`) выполняем настройку:

1.  **Создание кластера:**
    ```bash
    pcs cluster auth node1 node2 -u hacluster -p <HACLUSTER_PASSWORD>
    pcs cluster setup ha_cluster node1 node2
    pcs cluster start --all
    ```

2.  **Настройка Fencing (STONITH):**
    ```bash
    # Обязательно для продакшена! Пример для IPMI:
    pcs stonith create fence_node1 fence_ipmilan ipaddr=192.168.1.51 login=admin passwd=<FENCING_PASSWORD> pcmk_host_list=node1
    pcs stonith create fence_node2 fence_ipmilan ipaddr=192.168.1.52 login=admin passwd=<FENCING_PASSWORD> pcmk_host_list=node2
    ```

3.  **Создание ресурсов DRBD и ФС:**
    ```bash
    # Ресурс DRBD (promotable позволяет назначать роли Master/Slave)
    pcs resource create drbd_res ocf:linbit:drbd drbd_resource=r0 promotable
    
    # Файловая система (должна запускаться только там, где DRBD в роли Master)
    pcs resource create fs_res ocf:heartbeat:Filesystem device="/dev/drbd0" directory="/mnt/data" fstype="xfs"
    
    # Виртуальный IP
    pcs resource create virtual_ip ocf:heartbeat:IPaddr2 ip=192.168.1.100 cidr_netmask=24
    
    # Ограничения (Constraints):
    # 1. Запускать VIP и ФС вместе
    pcs constraint colocation add virtual_ip with fs_res INFINITY
    # 2. Запускать ФС только там, где DRBD повышен до Master
    pcs constraint colocation add fs_res with master drbd_res-clone INFINITY
    # 3. Порядок: сначала Master DRBD, потом ФС, потом VIP
    pcs constraint order promote drbd_res-clone then start fs_res
    pcs constraint order fs_res then virtual_ip
    ```

### Шаг 4: Безопасность и сетевое уплотнение

Firewall должен разрешать только необходимые порты между узлами кластера. На каждом узле:

```bash
# Corosync (UDP 5404-5405 — membership/ messaging)
firewall-cmd --add-service=high-availability --permanent
# или явно:
firewall-cmd --permanent --add-port=5404-5405/udp
# DRBD репликация (TCP 7788-7799)
firewall-cmd --permanent --add-port=7788-7799/tcp
# pcsd (TCP 2224 — управление кластером)
firewall-cmd --permanent --add-port=2224/tcp
# pacemaker-remoted (TCP 3121 — OCF-агенты ресурсов)
firewall-cmd --permanent --add-port=3121/tcp
firewall-cmd --reload
```

**SELinux/AppArmor:** Включите enforcing для `pcsd_t` и `corosync_t`. При необходимости разрешите сетевые соединения DRBD:

```bash
# Проверка SELinux статуса
getenforce
# Разрешение порта DRBD (если blocked)
semanage port -a -t drbd_port_t -p tcp 7788
```

**pcsd аутентификация:** Используйте ключи SSH вместо паролей для межузлового управления. Настройте `hacluster` пользователя с ограниченными правами.

### Шаг 5: Тюнинг DRBD 9

**Торможение синхронизации (resync throttling):** После разрыва связи DRBD проводит полную синхронизацию (resync). Без ограничений это может парализовать диск и сеть:

```drbd
resource r0 {
    net {
        protocol C;
        # Ограничение resync: 30 МБ/с (подбирайте под пропускную способность)
        resync-rate 30M;
        # Размер блока битмапа для больших объемов (>10 ТБ)
        al-extents 257;
        # Использовать block bitmap для ускорения initial sync
        use-bmbx yes;
        # Размер буфера для send/recv
        sndbuf-size 2M;
        rcvbuf-size 2M;
        # Таймауты соединения
        timeout 60;
        # Поведение при disc-my-data (защита от случайного split-brain)
        on-disconnect reconnect;
    }
    options {
        quorum majority;
        on-no-quorum io-error;
    }
}
```

**Валидация параметров:**

```bash
# Проверка текущих параметров
drbdadm dump r0
# Мониторинг resync в реальном времени
watch -n1 'cat /proc/drbd'
# Проверка utilization bitmap
drbdadm status r0 --verbose
```

**Применение изменений без перезагрузки ресурса:**

```bash
drbdadm adjust r0
```

### Шаг 6: Тюнинг Corosync и knet

**Таймауты членства:** Для сетей с высокой задержкой увеличьте `token` и `join` таймауты:

```conf
totem {
    version: 2
    cluster_name: ha_cluster_prod
    transport: knet
    # Таймаут потери token (мс). По умолчанию 1000.
    token: 5000
    # Таймаут ожидания joining (мс)
    join: 3000
    # Максимальное количество сообщений за token
    max_messages: 20
    interface {
        linknumber: 0
        knet_link_priority: 10
        # Опционально: указание конкретного интерфейса
        bindnetaddr: 10.0.0.0
    }
    interface {
        linknumber: 1
        knet_link_priority: 5
        bindnetaddr: 192.168.1.0
    }
}
```

**Шифрование knet:** Включите шифрование для трафика Corosync:

```conf
totem {
    transport: knet
    crypto_model: libcrypto
    # или: crypto_model: kernel
    crypto_cipher: aes256
}
```

**Валидация:**

```bash
# Статус линков knet
corosync-cfgtool -s
# Статистика quorum
corosync-quorumtool
# Проверка MTU
ip link show eth0
```

### Шаг 7: Режим обслуживания (Maintenance Mode)

Перед плановым обслуживанием переведите кластер в maintenance mode. Это предотвращает автоматическое переключение ресурсов:

```bash
# Перевести весь кластер в maintenance
pcs cluster maintenance --all
# Или только конкретный узел
pcs cluster maintenance node1
# Запрет запуска ресурсов на узле
pcs standby node1
# Проверка
pcs status --full
```

**Возврат в работу:**

```bash
pcs cluster unmaintenance --all
pcs unstandby node1
```

### Шаг 8: Бэкап и восстановление состояния кластера

CIB (Cluster Information Base) хранится в XML. Регулярно экспортируйте его:

```bash
# Экспорт текущей конфигурации
pcs cluster cib > /root/cluster-backup.xml
# Бэкап конфигурационных файлов
tar czf /root/ha-config-$(date +%F).tar.gz \
  /etc/corosync/corosync.conf \
  /etc/drbd.d/ \
  /etc/pacemaker/ \
  /etc/sysconfig/pacemaker \
  /etc/sysconfig/corosync
```

**Восстановление:**

```bash
# Остановить кластер
pcs cluster stop --all
# Восстановить файлы
tar xzf /root/ha-config-<YYYY-MM-DD>.tar.gz -C /
# Загрузить CIB
pcs cluster cib-push config.xml
# Запустить
pcs cluster start --all
```

## Проверка и валидация

1.  **Статус кластера:** `pcs status` — должен показывать все ресурсы в состоянии `Started` или `Master`.
2.  **Статус репликации:** `drbdadm status` — состояние должно быть `UpToDate/UpToDate`.
3.  **Quorum:** `corosync-quorumtool` — ожидается `Expected to vote` и `Quorate` для всех узлов.
4.  **Сеть:** `corosync-cfgtool -s` — оба линка в состоянии `active`. `ss -tnp | grep 7788` — порт DRBD слушается.
5.  **Fencing:** `stonith_admin -H node1` — тест fencing на active узле. Должен завершиться успешно.
6.  **Тест переключения:** Перезагрузите активный узел через `reboot` или `echo c > /proc/sysrq-trigger`. Ресурсы должны автоматически переместиться на второй узел в течение 10-30 секунд (зависит от настроенных таймаутов).
7.  **Валидация конфигурации:** `crm_verify -L -V` — проверка CIB на ошибки. `pcs config show` — просмотр текущей конфигурации.
8.  **LVM фильтр:** `pvs` — не должно показывать физические диски (`/dev/sdb`), только `/dev/drbd*`.

## Диагностика и устранение неисправностей

| Проблема | Вероятная причина | Диагностические команды | Решение |
| :--- | :--- | :--- | :--- |
| **Split-Brain в DRBD** | Потеря сети при обоих узлах в Primary. | `drbdadm status r0` — проверка состояния реплики; `dmesg \| grep drbd` — ошибки DRBD в kernel log | На одном узле: `drbdadm disconnect r0`, затем `drbdadm connect --discard-my-data r0`. |
| **Fencing Loop** | Узел перезагружается циклически; не успевает загрузиться. | `pcs stonith history` — история фенсинга; `stonith_admin -H` — статус STONITH агентов; `journalctl -u pacemaker -f` — логи Pacemaker в реальном времени | Проверьте `stonith-timeout`. Увеличьте значение: `pcs stonith update fence_node1 op timeout=60s`. |
| **Resource Unmanaged** | Ошибка агента или ручное вмешательство. | `pcs resource status` — состояние ресурсов; `pcs resource failcount show <resource_id>` — счетчик ошибок | Сбросьте состояние: `pcs resource cleanup <resource_id>`. |
| **Corosync Knet errors** | Проблемы с MTU или Firewall. | `corosync-cfgtool -s` — статус линков; `corosync-cfgtool -r` — перезапуск; `journalctl -u corosync -f` — логи | Убедитесь, что MTU везде одинаковый. Проверьте: `ip link show <interface>`. |
| **DRBD отстает (WFConnection)** | Сеть между узлами недоступна или DRBD не запущен на одном из узлов. | `drbdadm status r0` — состояние; `ss -tnp \| grep 7788` — проверка порта DRBD; `ping -c 5 <remote_ip>` — сетевая связность | Проверьте firewall: `firewall-cmd --list-ports`. Проверьте конфиг: `drbdadm dump r0`. |
| **Pacemaker не запускает ресурсы** | Корректность конфигурации ресурса; ошибки OCF-агента. | `pcs resource debug-start <resource_id>` — отладочный запуск; `crm_resource -r <resource_id> -V` — подробный вывод; `pcs config show` — текущая конфигурация | Исправьте конфигурацию и выполните `pcs resource cleanup <resource_id>`. |
| **Высокий Offset DRBD (постоянная синхронизация)** | Большое количество данных для синхронизации после разрыва связи. | `drbdadm status r0` — проверка offset; `cat /proc/drbd` — детали синхронизации; `iostat -x 1` — нагрузка на диск | Нормально для больших объемов. Для ускорения: увеличьте `max-buffers` и `sndbuf-size` в конфиге DRBD. |
| **Pacemaker: ресурс в promoted не переходит на standby** | Неправильные colocation/order constraints. | `pcs constraint show --full` — все ограничения; `pcs resource show <resource>` — параметры ресурса | Проверьте `promotable` и `master` constraints. Убедитесь, что `fs_res` colocated с `master drbd_res-clone`. |
| **DRBD: write-ordering не поддерживается** | Устаревший драйвер DRBD или неправильный protocol. | `drbdadm dump r0` — проверка protocol; `modinfo drbd` — версия модуля | Обновите DRBD до 9.x. Protocol C требует kernel >= 3.10 с поддержкой DRBD 9. |
| **QDevice: не удается подключиться** | Проблемы с TLS/сертификатами или сетью. | `corosync-qnetd-tool show` — статус на сервере; `journalctl -u corosync-qnetd` — логи | Убедитесь, что порт 5403/tcp открыт. Проверьте сертификаты в `/etc/corosync/qnetd/`. |
| **DRBD resync занимает весь I/O** | Отсутствует `resync-rate` или значение слишком высокое. | `iostat -x 1` — нагрузка на диск; `cat /proc/drbd` — скорость resync | Добавьте `resync-rate` в секцию `net`. Рекомендуется 20-30% от пропускной способности диска. |
| **Corosync: потеря сообщений (knet rx drops)** | Перегрузка сети или неправильный MTU. | `ethtool -S <iface> \| grep rx_dropped`; `journalctl -u corosync -f` | Убедитесь, что MTU совпадает на всех интерфейсах. Проверьте `knet_link_priority` и балансировку. |
| **Pacemaker: ресурс стартует на двух узлах** | Отсутствует colocation constraint или `promotable` не настроен. | `pcs status` — ресурсы на двух нодах; `pcs constraint show` | Добавьте colocation constraint. Для DRBD используйте `promotable` и `master` clone. |
| **STONITH: fence агент возвращает "Unknown"** | Агент не установлен или неправильный `pcmk_host_list`. | `stonith_admin -L` — список агентов; `pcs stonith show` — конфигурация | Установите `fence-agents-<vendor>` пакет. Проверьте `pcmk_host_list` и connectivity к BMC. |
| **DRBD: устройство не появляется после создания** | Модуль ядра не загружен или metadata не создана. | `lsmod | grep drbd`; `cat /proc/drbd`; `dmesg | grep drbd` | Загрузите модуль: `modprobe drbd`. Выполните `drbdadm create-md r0` на обоих узлах. |
| **Corosync: узел постоянно leaving/joining** | Проблемы с сетевым интерфейсом или watchdog. | `journalctl -u corosync -f`; `ip link show <iface>`; `systemctl status watchdog` | Проверьте стабильность сетевого линка. Убедитесь, что watchdog service активен. |

## Практические рекомендации

1.  **LVM и DRBD:** Если вы используете LVM поверх DRBD, **обязательно** настройте фильтр в `/etc/lvm/lvm.conf`. LVM должен сканировать только `/dev/drbd*` и игнорировать физические диски (например, `/dev/sdb`), иначе возникнут конфликты метаданных:
    *   `filter = [ "a|/dev/drbd.*|", "r|.*|" ]`
2.  **Bitmap Block Size:** При инициализации ресурсов > 10 ТБ используйте увеличенный размер блока битмапа: `drbdadm create-metadata --bitmap-block-size 65536 r0`. Это существенно снизит потребление памяти.
3.  **Мониторинг:** Используйте современный **DRBD Reactor** для сбора метрик в Prometheus. Старые скрипты на bash медленны и могут вызывать тайм-ауты в Pacemaker.
4.  **Тюнинг сети:** Для каналов 10 Гбит/с и выше в секции `net` файла конфига DRBD добавьте:
    *   `sndbuf-size 2M;`
    *   `rcvbuf-size 2M;`
    *   `max-buffers 8000;`
5.  **Торможение resync:** Всегда настраивайте `resync-rate` для DRBD ресурсов. Без ограничений синхронизация после разрыва связи парализует диск и сеть.
6.  **knet шифрование:** Включите `crypto_cipher aes256` в секции `totem` для Corosync 3.x. Это защищает трафик кластера от перехвата.
7.  **pcsd аутентификация:** Используйте SSH-ключи для `hacluster` пользователя. Отключите парольную аутентификацию в `/etc/sysconfig/pcsd`.
8.  **Журналирование:** Настройте `journalctl` для ротации логов Pacemaker и Corosync. Логи fencing-событий критичны для расследования инцидентов.
9.  **Watchdog:** Убедитесь, что watchdog сервис активен (`systemctl status watchdog`). Он требуется для SBD и помогает детектировать зависания ядра.
10. **Тестирование STONITH:** После настройки выполните тестовый fencing: `stonith_admin -H <node>`. Убедитесь, что узел действительно отключается и возвращается в кластер.

## Лучшие практики (Best Practices)

1. **STONITH обязателен для продакшена:** Каждый узел кластера должен иметь настроенный и протестированный STONITH-агент. Без фенсинга Split-Brain приведет к безвозвратной порче данных.
2. **Два независимых сетевых линка для Corosync:** Используйте knet с двумя интерфейсами в разных сетях (например, выделенная сеть HA + общая сеть). Это защитит от одиночного отказа коммутатора.
3. **DRBD Protocol C для продакшена:** Протоколы A и B допустимы только для DR-площадок с высоким RTT. Для локальных сетей используйте Protocol C (синхронную репликацию) — это гарантирует нулевой RPO.
4. **LVM-фильтр обязателен:** Если используется LVM поверх DRBD, настройте фильтр в `/etc/lvm/lvm.conf`: `filter = [ "a|/dev/drbd.*|", "r|.*|" ]`. Без этого LVM сканирует физические диски и создает конфликты метаданных.
5. **DRBD Reactor вместо bash-скриптов:** Используйте **DRBD Reactor** для мониторинга и управления DRBD. Старые bash-скрипты могут вызывать тайм-ауты в Pacemaker и медленно реагировать на изменения.
6. **Автозапуск кластера:** Убедитесь, что `pcs cluster enable --all` выполнен и сервисы `corosync`/`pacemaker` добавлены в автозапуск (`systemctl enable`). После ребута кластер должен восстанавливаться автоматически.
7. **Регулярное тестирование failover:** Минимум раз в квартал выполняйте контролируемый failover (перезагрузка активного узла). Проверяйте время переключения (RTO < 30 сек для стандартной конфигурации).
8. **Резервирование корзины конфигов:** Храните резервные копии `/etc/corosync/corosync.conf` и `/etc/drbd.d/` вне кластера (например, в Git). При тяжелых сбоях восстановление из резервной копии быстрее, чем перенастройка.
9. **Мониторинг через Prometheus:** Используйте **DRBD Reactor** (экспозиция метрик на :9941) и **pacemaker-exporter** для сбора метрик кластера. Настройте alerting на `drbd_replication_state != "UpToDate"` и `pacemaker_nodes_online < 2`.
10. **Таймауты по умолчанию — проверять:** Значения таймаутов по умолчанию в Pacemaker (inkle, timeout для STONITH) могут быть слишком агрессивными для вашего оборудования. Протестируйте и при необходимости увеличьте.
11. **Пароли и секреты:** Не храните пароли fencing в открытом виде в конфигах. Используйте vault (HashiCorp Vault, Ansible Vault) или переменные окружения. `pcs` поддерживает `--passwd-file` для чтения пароля из файла с ограниченными правами (0600).
12. **Журналирование:** Включите детальное журналирование для Pacemaker и Corosync при расследовании инцидентов: `pcs property set pe-verbose=true` (временно, не для продакшена). Ротация логов через `logrotate` или `journald`.
13. **Watchdog:** Убедитесь, что watchdog модуль загружен (`lsmod | grep softdog`) и сервис активен. SBD требует watchdog для работы.
14. **Тестирование STONITH:** После настройки выполните тестовый fencing: `stonith_admin -H <node>`. Убедитесь, что узел действительно отключается и возвращается в кластер без ручного вмешательства.
15. **CIB валидация:** Перед применением конфигурации проверяйте её: `crm_verify -L -V`. Автоматизируйте это в CI/CD pipeline для инфраструктурного кода.

## Граничные случаи и ограничения (Edge Cases)

- **Два узла без QDevice:** В кластере из 2 нод кворум требует `two_node: 1`. Если оба узла теряют связь, каждый считает себя легитимным → Split-Brain. Решение: добавить третий узел как QDevice (`corosync-qdevice`) или использовать SBD на общем диске.
- **Дрейф времени и fencing:** Если часы на узлах рассинхронизированы > 500мс, Corosync может неверно детектировать сбои. Всегда настраивайте `chrony` с низким offset.
- **DRBD + LVM без фильтра:** Без фильтра LVM сканирует физические диски (`/dev/sdb`) и может создать VG на физическом диске, конфликтуя с DRBD. Фильтр обязателен.
- **SBD без резервного устройства:** SBD требует как минимум 1 МБ общего блочного устройства. Если устройство недоступно, SBD не работает → кластер не запустится. Проверяйте доступность устройства перед запуском.
- **Resource stickiness по умолчанию:** По умолчанию `resource-stickiness=0` — ресурсы могут «прыгать» между узлами при малейших колебаниях нагрузки. Для критичных ресурсов (БД) установите `pcs resource defaults update resource-stickiness=100`.
- **DRBD + виртуальные машины:** Если кластер управляет VM через Pacemaker, необходимо учитывать время остановки VM при fencing. VM может не успеть корректно завершить работу → потенциальная потеря данных. Используйте `shutdown-timeout` в конфиге VM.
- **Ресурсы с тяжелыми зависимостями:** Цепочка из 5+ constraints (DRBD → LVM → FS → DB → VIP) увеличивает время failover. Разбивайте на группы с `pcs resource group add`.
- **DRBD initial sync на больших объемах:** Первоначальная синхронизация при создании ресурса > 10 ТБ может занимать часы. Используйте `--bitmap-block-size 65536` и `use-bmbx yes` для ускорения. Мониторьте через `watch -n1 'cat /proc/drbd'`.
- **Corosync knet: разный MTU на линках:** Если MTU различается на двух сетевых интерфейсах, knet может падать с ошибкой `rx drops`. Проверяйте MTU на обоих линках: `ip link show`.
- **Pacemaker fencing timeout слишком короткий:** По умолчанию `stonith-timeout=60s`. Если BMC отвечает медленно, fencing завершится ошибкой и узел останется в кластере. Увеличьте: `pcs property set stonith-timeout=120s`.
- **DRBD после hard reset (power loss):** При аварийном отключении питания оба узла могут считаться Primary. DRBD 9.x с `quorum majority` заблокирует I/O до ручного вмешательства. Решение: определите authoritative узел по логам или данным, выполните `discard-zero-changes` на втором.
- **Corosync quorum при потери одного линка:** При потере linknumber:0 (priority 10) knet автоматически переключится на linknumber:1 (priority 5), но кластер останется работоспособен только если оставшийся линк обеспечивает связность между всеми узлами.
- **DRBD + Pacemaker: race condition при старте:** Если Pacemaker стартует раньше Corosync, ресурсы не запустятся. Убедитесь в порядке загрузки systemd: `systemctl show pacemaker -p After`.

## Связанные концепции

- **[Механизмы Failover и Heartbeat](./ha_failover_mechanisms.md)** — теория кворума, STONITH, BFD, Keepalived.
- **[Кластеризация и балансировка нагрузки](./ha_clustering_and_load_balancing.md)** — архитектурные модели кластеров, N+M, Active-Passive.
- **[Обзор HA](./ha_overview.md)** — метрики доступности, RTO/RPO, Split-Brain prevention.
- **[Пакеты Linux HA Stack](../../Linux/Diagnostics/sos_report.md)** — сбор дампов кластера для анализа.
- **[Кластеризация в Proxmox](../../Proxmox/proxmox_cluster.md)** — специфика использования Corosync в PVE.
- **[Load Shedding](../../CI-CD/Core_Concepts/load_shedding.md)** — паттерн сброса нагрузки при отказе узла кластера.

---

## Контрольный список проектирования Linux HA Stack (Pacemaker + Corosync + DRBD)

- [ ] Установлены пакеты `pacemaker`, `pcs`, `corosync`, `drbd-utils`, `fence-agents` на всех узлах
- [ ] Два независимых сетевых интерфейса для Corosync (разные сети, задержка < 2 мс)
- [ ] Открыты порты: UDP 5404-5405 (Corosync), TCP 7788-7799 (DRBD), TCP 2224 (pcsd), TCP 3121 (pacemaker-remoted)
- [ ] Выделенные диски одинакового размера для DRBD на каждом узле
- [ ] Настроен `chrony` (разница < 100мс, `makestep` настроен)
- [ ] DRBD настроен с Protocol C (синхронная репликация)
- [ ] DRBD quorum: `quorum majority` + `on-no-quorum io-error`
- [ ] DRBD tuning: `resync-rate`, `al-extents`, `use-bmbx` (для >10 ТБ)
- [ ] STONITH настроен, протестирован (`stonith_admin -H`) и документирован для каждого узла
- [ ] LVM-фильтр настроен (если используется LVM поверх DRBD)
- [ ] SELinux в enforcing, порты DRBD разрешены (`semanage port`)
- [ ] pcsd аутентификация по SSH-ключам, пароли отключены
- [ ] Watchdog сервис активен (`systemctl status watchdog`)
- [ ] Corosync knet: два линка с разным `knet_link_priority`, опционально шифрование
- [ ] `pcs cluster enable --all` выполнен (автозапуск)
- [ ] Тест failover выполнен (перезагрузка активного узла, RTO < 30 сек)
- [ ] Регулярное тестирование STONITH (ежеквартально)
- [ ] Мониторинг настроен: DRBD Reactor (:9941) + pacemaker-exporter + alerting
- [ ] Резервные копии конфигов хранятся вне кластера
- [ ] CIB экспортирован: `pcs cluster cib > cluster-backup.xml`
- [ ] `crm_verify -L -V` проходит без ошибок
