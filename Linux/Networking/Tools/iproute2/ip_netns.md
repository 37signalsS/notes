# ip netns: Управление сетевыми пространствами имён

## Определения

*   **Network namespace (сетевое пространство имён)** — механизм изоляции сетевого стека в ядре Linux. Он позволяет процессам иметь независимые экземпляры сетевого оборудования, таблиц маршрутизации, правил фильтрации (iptables/nftables) и сокетов.
*   **`ip netns`** — специализированная утилита из пакета `iproute2`, предназначенная для манипуляции именованными сетевыми пространствами имён.

> **Применение:** Сетевые пространства имён являются фундаментом контейнеризации. Каждый под в Kubernetes и каждый контейнер в Docker (кроме режима `host`) изолирован в собственном сетевом пространстве.

## Основные концепции

### Изоляция ресурсов

Внутри каждого пространства имён полностью изолированы:
*   **Интерфейсы:** включая виртуальную петлю (`lo`), физические адаптеры (перемещенные из хоста) и виртуальные устройства (`veth`, `bridge`, `vxlan`).
*   **Маршрутизация:** уникальная таблица маршрутов (RIB) и кэш маршрутов.
*   **Сетевые фильтры:** независимые наборы правил Netfilter (iptables) и nftables.
*   **Порты и сокеты:** возможность запуска нескольких экземпляров сервисов, слушающих один и тот же порт (например, 80) на одном физическом хосте.
*   **Настройки ядра:** параметры сетевого стека в `/proc/sys/net/*` (каждый netns имеет собственную копию sysctl).
*   **ARP-таблица и Neighbor Table:** изолированные записи каждого netns.

> **Важно:** Интерфейс `lo` в каждом новом netns по умолчанию находится в состоянии DOWN. Необходимо явно активировать его через `ip link set lo up`.

### Механизм реализации и персистентность

Ядро Linux автоматически удаляет сетевое пространство имён, когда последний процесс в нем завершается. Утилита `ip netns` обеспечивает **персистентность** (сохранение) пространств имён даже без запущенных процессов с помощью следующих механизмов:
1.  **Создание дескриптора:** создается пустой файл в директории `/var/run/netns/`.
2.  **Bind Mount:** выполняется монтирование (`mount --bind`) дескриптора текущего сетевого пространства процесса к этому файлу. Это удерживает ссылку на namespace в структурах ядра.

```bash
# Ручная персистентность (аналог того, что делает ip netns add)
mkdir -p /var/run/netns
touch /var/run/netns/myns
# Предположим, что PID процесса уже находится в нужном netns:
mount --bind /proc/<PID>/ns/net /var/run/netns/myns
# Теперь namespace сохраняется даже после завершения процесса
```

### Конфигурационные переопределения

Хотя пространства имён не изолируют файловую систему, команда `ip netns exec` поддерживает механизм переопределения файлов конфигурации. Если существуют файлы в директории `/etc/netns/<имя_ns>/`, они будут видны процессам внутри этого пространства вместо оригинальных файлов из `/etc/`.

| Файл переопределения | Назначение | Пример |
| :--- | :--- | :--- |
| `/etc/netns/<ns>/resolv.conf` | DNS-серверы для пространства | Уникальные DNS для каждого ns |
| `/etc/netns/<ns>/hostname` | Имя хоста | Эмуляция разных хостов |
| `/etc/netns/<ns>/hosts` | Локальная таблица хостов | Изолированный DNS |
| `/etc/netns/<ns>/nsswitch.conf` | Порядок разрешения имён | Кастомный NSS |

```bash
# Пример: уникальные DNS для пространстваимён production
sudo mkdir -p /etc/netns/production
echo "nameserver 10.0.0.53" | sudo tee /etc/netns/production/resolv.conf
# Теперь процессы в production_ns увидят этот resolv.conf вместо системного
```

### Взаимодействие с другими пространствами имён

Network namespace работает в связке с другими типами namespaces. Наиболее частые комбинации:

| Комбинация | Сценарий | Где используется |
| :--- | :--- | :--- |
| **net + pid** | Полная изоляция контейнера | Docker, Podman, Kubernetes |
| **net + mnt** | Своя ФС + своя сеть | Контейнеры с собственным rootfs |
| **net + user** | Rootless-контейнеры | Podman rootless, Docker rootless |
| **net + uts** | Уникальный hostname в netns | Тестовые стенды |

> **Важно:** `ip netns` создаёт ТОЛЬКО network namespace. Для полной изоляции контейнера требуются дополнительные флаги (`--pid`, `--mount`, `--uts`) через `unshare` или `clone`.

## Справочник команд

### Жизненный цикл

| Команда | Описание |
| :--- | :--- |
| `ip netns add <имя>` | Создать новое пространство имён |
| `ip netns list` | Вывести список всех пространств имён |
| `ip netns delete <имя>` | Удалить пространство имён |
| `ip netns identify <PID>` | Определить имя netns для указанного PID |
| `ip netns pids <имя>` | Вывести PIDы всех процессов в указанном netns |
| `ip netns monitor` | Мониторинг событий создания/удаления netns в реальном времени |

### Выполнение команд

| Команда | Описание |
| :--- | :--- |
| `ip netns exec <имя> <команда>` | Выполнить команду в контексте пространства имён |
| `ip -n <имя> <команда>` | Сокращённый синтаксис (аналог `ip netns exec`) |

> **Флаг `-n`:** Сокращённый синтаксис доступен не для всех подкоманд `ip`. Для надёжности в скриптах рекомендуется полный `ip netns exec`.

## Практические сценарии

### Жизненный цикл пространств имён

```bash
# Создать новое именованное пространство имён
sudo ip netns add mgmt_ns

# Просмотреть список существующих пространств имён
ip netns list
# → mgmt_ns

# Определить, в каком netns находится процесс (по PID)
ip netns identify <PID>
# → mgmt_ns

# Найти PID процессов, работающих в конкретном netns
ip netns pids mgmt_ns

# Удалить пространство имён
# Все виртуальные интерфейсы внутри будут удалены, физические - вернутся в 'default'
sudo ip netns delete mgmt_ns
```

### Выполнение команд (exec и флаг -n)

```bash
# Выполнение команды в контексте пространства имён
sudo ip netns exec mgmt_ns ip address show

# Быстрая проверка: создать netns и сразу посмотреть адреса
ip netns add test && ip netns exec test ip -br a

# Современный сокращенный способ (доступен в новых версиях iproute2)
sudo ip -n mgmt_ns address show

# Запуск интерактивной оболочки (bash) для глубокой диагностики
sudo ip netns exec mgmt_ns bash

# Мониторинг событий (создание/удаление netns) в реальном времени
# Полезно для отладки скриптов, автоматизирующих управление netns
sudo ip netns monitor
# → create: mgmt_ns
# → destroy: mgmt_ns
```

### Идентификация и внешнее управление

```bash
# Идентификация текущего пространства имён процесса
ls -l /proc/self/ns/net
# → net:[4026531992] (уникальный ID в ядре)

# Сравнение netns двух процессов (одинаковый ID = один namespace)
readlink /proc/<PID1>/ns/net
readlink /proc/<PID2>/ns/net

# Вход в пространство имен процесса без использования 'ip netns' (по PID)
# Удобно для отладки контейнеров Docker/K8s
sudo nsenter -t <PID> -n ip link

# Вход через bind-mount (для персистентных netns)
sudo nsenter --net=/var/run/netns/myns ip addr show
```

### Связь между пространствами имён (veth-пары)

Сценарий имитирует работу двух изолированных хостов, соединенных виртуальным кабелем.

**Шаг 1: Создание сетевых пространств имён**
```bash
sudo ip netns add ns1
sudo ip netns add ns2
```

**Шаг 2: Создание виртуальной пары Ethernet (veth)**
```bash
sudo ip link add veth1 type veth peer name veth2
# veth-пара работает как виртуальный патч-корд: что входит в один конец, выходит из другого.
```

**Шаг 3: Перемещение интерфейсов в пространства имён**
```bash
sudo ip link set veth1 netns ns1
sudo ip link set veth2 netns ns2
# Теперь интерфейсы исчезли из вывода 'ip link' на основном хосте.
```

**Шаг 4: Назначение IP-адресов**
```bash
sudo ip -n ns1 addr add 10.0.0.1/24 dev veth1
sudo ip -n ns2 addr add 10.0.0.2/24 dev veth2
```

**Шаг 5: Активация интерфейсов**
```bash
# Важно: lo должен быть UP для работы локальных сокетов внутри ns
sudo ip -n ns1 link set lo up
sudo ip -n ns1 link set veth1 up

sudo ip -n ns2 link set lo up
sudo ip -n ns2 link set veth2 up
```

**Шаг 6: Проверка связности и маршрутов**
```bash
# Просмотр маршрутов внутри ns1
sudo ip -n ns1 route

# Проверка пингом: ns1 -> ns2
sudo ip netns exec ns1 ping -c 3 10.0.0.2
```

### Мост (bridge) между несколькими netns

Расширенный сценарий: три пространства имён, объединённые через bridge. Имитирует типичную архитектуру Docker-хоста.

```bash
# 1. Создание пространств имён
sudo ip netns add web
sudo ip netns add app
sudo ip netns add db

# 2. Создание bridge-интерфейса на хосте
sudo ip link add br0 type bridge
sudo ip addr add 172.17.0.1/24 dev br0
sudo ip link set br0 up

# 3. Создание veth-пар для каждого netns
for ns in web app db; do
    sudo ip link add veth-${ns}-host type veth peer name veth-${ns}-ns
    sudo ip link set veth-${ns}-ns netns ${ns}
    sudo ip -n ${ns} addr add 172.17.0.${id}/24 dev veth-${ns}-ns
    sudo ip -n ${ns} link set veth-${ns}-ns up
    sudo ip -n ${ns} link set lo up
    # Подключение хостового конца к bridge
    sudo ip link set veth-${ns}-host master br0
    sudo ip link set veth-${ns}-host up
done

# 4. Проверка: все netns видят друг друга через bridge
sudo ip netns exec web ping -c 1 172.17.0.2  # → app
sudo ip netns exec web ping -c 1 172.17.0.3  # → db
```

> **Примечание:** В реальных скриптах присваивание IP (`172.17.0.X`) лучше делать динамически (через счётчик или DHCP-эмуляцию).

### Настройка NAT для выхода в интернет

Чтобы процессы внутри `my_ns` могли обращаться к внешним ресурсам через интерфейс хоста `eth0`.

```bash
# 1. Включить IP Forwarding на хосте
sudo sysctl -w net.ipv4.ip_forward=1

# 2. Настроить NAT (MASQUERADE) на внешнем интерфейсе хоста
sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o eth0 -j MASQUERADE

# 3. Добавить маршрут по умолчанию внутри пространства имён
# В качестве шлюза используется IP интерфейса veth на стороне хоста
sudo ip -n my_ns route add default via 10.0.0.1
```

### Настройка sysctl внутри netns

Каждое сетевое пространство имён имеет собственную копию sysctl-параметров. Это позволяет настраивать сетевой стек независимо от хоста.

```bash
# Просмотр текущих значений в netns
sudo ip netns exec my_ns sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 0

# Включение IP forwarding только внутри netns (без влияния на хост)
sudo ip netns exec my_ns sysctl -w net.ipv4.ip_forward=1

# Типичные параметры для настройки в netns
sudo ip netns exec my_ns sysctl -w net.ipv4.conf.all.rp_filter=0
sudo ip netns exec my_ns sysctl -w net.ipv4.icmp_echo_ignore_all=0
sudo ip netns exec my_ns sysctl -w net.core.somaxconn=4096

# Просмотр всех доступных sysctl в netns
sudo ip netns exec my_ns sysctl -a | grep net.ipv4
```

> **Изоляция:** Изменение sysctl внутри netns НЕ влияет на хост. Это ключевое отличие от работы с `/proc/sys/net/` на хосте.

### Комбинированная изоляция (netns + mountns + pidns)

Полноценная изоляция сервиса, приближенная к контейнеру:

```bash
# Создание изолированной среды через unshare
sudo unshare --net --mount --pid --fork --mount-proc bash

# Внутри нового пространства:
ip link          # Только lo
ip link set lo up
ps aux           # Только процессы внутри ns
```

## Диагностика и мониторинг

Внутри пространства имён доступны все стандартные инструменты диагностики.

```bash
# Просмотр ARP-таблицы (соседних устройств)
sudo ip -n my_ns neighbour show

# Просмотр детальной статистики интерфейсов (ошибки, дропы)
sudo ip -n my_ns -s link show

# Мониторинг сетевых событий (link up/down, маршруты) в реальном времени
sudo ip -n my_ns monitor

# Диагностика сокетов внутри netns
sudo ip netns exec my_ns ss -tulpn

# Трассировка маршрута внутри netns
sudo ip netns exec my_ns traceroute 8.8.8.8

# Захват пакетов внутри netns
sudo ip netns exec my_ns tcpdump -i any -n icmp
```

### Типичные ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `RTNETLINK answers: File exists` | Интерфейс с таким именем уже существует | `ip link show type veth` для поиска дубликата |
| `RTNETLINK answers: No such device` | Интерфейс не найден в текущем netns | Проверьте `ip link -n <ns> show`; интерфейс мог быть удалён или перемещён |
| `connect: Network is unreachable` | Отсутствует маршрут или интерфейс DOWN | `ip -n <ns> link set lo up`; проверьте `ip -n <ns> route` |
| `ip netns exec` завершается молча | Имя netns не найдено | `ip netns list` для проверки имени |
| `Permission denied` | Команда выполнена без root | Используйте `sudo` |
| `No route to host` (между netns) | Не настроены маршруты или bridge | Убедитесь, что IP назначены корректно и интерфейсы UP |
| `ip netns pids` возвращает пустоту | В netns нет процессов | Это нормально для персистентных netns без запущенных сервисов |

## Безопасность и ограничения

### Аспекты безопасности

*   **Привилегии:** Для создания, удаления и управления netns требуются права root (или `CAP_SYS_ADMIN` в User Namespace).
*   **Утечки:** При перемещении физического NIC в netns он становится недоступен другим netns и хосту. Это может привести к потере сетевого доступа к хосту.
*   **Персистентные netns:** Bind-mount в `/var/run/netns/` сохраняет netns даже без процессов. Забытые netns потребляют kernel memory.
*   **Audit trail:** Мониторинг создания namespace: `auditctl -a exit,always -F arch=b64 -S clone -S unshare -S setns -k netns`.

### Ограничения

*   **Performance overhead:** Минимальный (< 10 мкс на переключение). veth и bridge добавляют небольшую задержку. Для требований к сверхнизкой задержке (HFT, real-time) рекомендуются alternatives (SR-IOV, DPDK).
*   **Максимальное количество:** Ограничено ядром (`/proc/sys/user/max_net_namespaces`, по умолчанию充足ное для большинства сценариев).
*   **Удаление при busy:** `ip netns delete` не сработает, если в netns есть активные процессы. Сначала завершите все процессы или используйте `kill`.
*   **Интерфейс lo:** В каждом новом netns `lo` по умолчанию DOWN. Это частый источник ошибок при первичной настройке.

## Дополнительная информация

### Сравнение с альтернативами

| Метод | Уровень изоляции | Привилегии | Сценарий |
| :--- | :--- | :--- | :--- |
| **ip netns** | Полный L2-L7 | root | Тестирование, контейнеры, туннели |
| **VRF** | Только L3 (маршрутизация) | root | Изоляция таблиц маршрутизации |
| **unshare -n** | Полный L2-L7 | root или User NS | Одноразовые изоляции |
| **systemd PrivateNetwork** | Полный L2-L7 | root | Сервисы systemd |

### Связанные темы

*   **[`ip link`](./ip_link.md)** — управление сетевыми интерфейсами.
*   **[Сетевые интерфейсы Linux](../../Concepts/linux_network_interfaces.md)** — типы и применение (veth, bridge).
*   **[Пространства имён (namespaces)](../../../Core/namespaces.md)** — общая концепция изоляции в Linux.
*   **[Сетевая модель Docker](../../../Docker/Docker_network/docker_network.md)** — практическое применение NetNS.
*   **[VRF](../../vrf.md)** — альтернативный (L3) метод сетевой изоляции.
