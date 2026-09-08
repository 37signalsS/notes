# Пространства имён (namespaces)

## Определения

**Пространства имён (Namespaces)** — фундаментальный механизм ядра Linux, обеспечивающий изоляцию и виртуализацию системных ресурсов для группы процессов. Он позволяет процессам иметь собственные независимые экземпляры системных ресурсов, создавая иллюзию работы в отдельной операционной системе.

**Различие между Namespaces и Cgroups:**
- **Namespaces** отвечают за **изоляцию видимости** (что процесс *видит*): дерево процессов, сетевые интерфейсы, точки монтирования.
- **[Контрольные группы (cgroups)](./cgroups.md)** отвечают за **ограничение потребления** (что процесс *использует*): лимиты CPU, памяти, количество процессов.

Вместе эти технологии образуют основу современной контейнеризации (Docker, Podman, Kubernetes).

### Файловая система /proc/PID/ns

Каждое пространство имён представлено в `/proc/<PID>/ns/` как виртуальный файл. Эти файлы не содержат данных в привычном смысле; вместо этого их inode-номера служат **уникальными идентификаторами** пространств имён.

```bash
# Просмотр пространств имён текущего shell
ls -l /proc/self/ns/

# Пример вывода:
# lrwxrwxrwx 1 root root 0 Sep  6 12:00 net -> 'net:[4026531840]'
# lrwxrwxrwx 1 root root 0 Sep  6 12:00 pid -> 'pid:[4026531839]'
```

Сравнение inode-номеров позволяет определить, разделяют ли процессы одно пространство имён:
```bash
# Два процесса в одном net-namespace имеют одинаковый inode
readlink /proc/$PID1/ns/net
readlink /proc/$PID2/ns/net
```

### Жизненный цикл и отсчёт ссылок

Пространство имён существует до тех пор, пока на него существует хотя бы одна ссылка:
- **Процессы**, находящиеся в пространстве имён.
- **Bind-mounts** файлов дескрипторов из `/proc/PID/ns/` (используется для персистентности, например в `ip netns`).
- **Дочерние пространства имён**, если родительское не уничтожено.

Когда счётчик ссылок достигает нуля, ядро освобождает пространство имён.

### Системный вызов setns(2)

В отличие от `clone(2)`, создающего новый namespace, `setns(2)` позволяет **присоединиться** к уже существующему пространству имён через его файловый дескриптор:

```bash
# Открытие fd сетевого пространства контейнера
ns_fd=$(sudo ls /proc/$PID/ns/net -l | awk '{print $9}')

# Вход в пространство через setns
sudo nsenter --net=/proc/$PID/ns/net -- ip addr show
```

Этот вызов лежит в основе работы `nsenter`, `docker exec` и `kubectl exec`.

---

## Основные концепции

### Типы пространств имён

| Тип (Namespace) | Флаг `clone(2)` | Изолируемые ресурсы |
| :--- | :--- | :--- |
| **Mount (mnt)** | `CLONE_NEWNS` | Таблица монтирования, корень ФС, Propagation. |
| **Process ID (pid)** | `CLONE_NEWPID` | Дерево процессов, PID 1, сигналы. |
| **Network (net)** | `CLONE_NEWNET` | Сетевой стек (интерфейсы, маршруты, iptables). |
| **User** | `CLONE_NEWUSER` | Идентификаторы пользователей (UID/GID), Capabilities. |
| **IPC** | `CLONE_NEWIPC` | Межпроцессное взаимодействие (Shared Memory, Semaphores). |
| **UTS** | `CLONE_NEWUTS` | Идентификаторы хоста (Hostname, Domainname). |
| **Cgroup** | `CLONE_NEWCGROUP` | Видимость иерархии cgroups в `/proc/self/cgroup`. |
| **Time (5.6+)** | `CLONE_NEWTIME` | Системные часы (Boottime, Monotonic). |

### Иерархия и вложенность (Nesting)

Пространства имён могут быть вложенными. При создании нового пространства имён дочерний процесс получает **копию** родительского пространства (или совершенно новое, если флаг указан). 

**Пример:** При запуске контейнера создаётся новаяMount-иерархия, но процессы внутри могут видеть только часть исходного дерева процессов (если создан и PID-нэймспейс).

**Важность для DevOps/SRE:**
- Вложенные пространства позволяют реализовывать многоуровневую изоляцию (например, пода внутри узла Kubernetes).
- Но при удалении родительского namespace все дочерние уничтожаются автоматически. Это критично при отладке "висячих" контейнеров.

### Пользовательское пространство имён (User) как корневое

**User Namespace** — единственный тип, который можно создать **без привилегий root**. Он служит "корнем" для всех остальных:

1. Процесс в новом User Namespace может создавать другие namespace (Mount, PID, Network), даже если у него нет `CAP_SYS_ADMIN` на хосте.
2. Внутри User Namespace процесс может быть mapped на **любой** UID хоста (например, обычный пользователь UID 1000 может стать UID 0 внутри namespace).
3. **Безопасность:** Ядро Linux (с версии 3.8) допускает создание User Namespace только если включён `CONFIG_USER_NS`. На некоторых дистрибутивах (RHEL, CentOS) по умолчанию он отключён из-за security concerns.

### Взаимодействие с Capabilities и SELinux/AppArmor

- **Capabilities:** Внутри User Namespace процесс может получить полный набор capabilities (включая `CAP_SYS_ADMIN`), но эти capabilities действуют **только внутри namespace**. На хосте они не распространяются.
- **SELinux/AppArmor:** Эти MAC-системы работают на уровне хоста и не изолируются namespace. Процесс в новом namespace наследует политику хоста. При контейнеризации требуется явная маркировка (SELinux label) или отключение (AppArmor unconfined).

### Детальный разбор механизмов

#### Пространство имён монтирования (Mount)
Первый тип пространства имён в Linux (2002 год).
- Позволяет процессу иметь собственное дерево каталогов.
- Взаимодействие с хостом управляется через **Propagation** (Shared, Private, Slave, Unbindable).
- **Подробно:** [Пространства имён монтирования (mount namespaces)](../Virtualization/mount_namespaces.md).

#### Пространство имён процессов (PID)
Создает иерархию процессов.
- Первый процесс в новом пространстве получает **PID 1** (init).
- Процессы видят только своих потомков.
- При смерти PID 1 все процессы в данном пространстве уничтожаются (`SIGKILL`).
- **Важно для SRE:** Systemd требует, чтобы PID 1 был systemd или совместимым init. Попытка запустить systemd в новом PID namespace без соответствующих флагов приведёт к падению.

#### Сетевое пространство имён (Network)
Виртуализирует весь сетевой стек.
- У каждого пространства свои интерфейсы (включая `lo`), правила маршрутизации и сокеты.
- Для связи между пространствами используются **veth-пары** (virtual ethernet).
- **Подробно:** [Утилита ip netns](../Networking/Tools/iproute2/ip_netns.md).

#### Пользовательское пространство имён (User)
Ключевой механизм безопасности и **Rootless** режимов.
- Позволяет сопоставлять UID внутри пространства (например, root с UID 0) с обычным UID на хосте.
- Настройка выполняется через файлы `/proc/[pid]/uid_map` и `/proc/[pid]/gid_map`.
- Формат записи: `ID-внутри-ns ID-снаружи-ns длина`.
- Процесс с `CAP_SYS_ADMIN` в своем User Namespace может создавать другие пространства имён (Mount, Network) без привилегий root на хосте.

#### Пространство имён IPC
Изолирует объекты межпроцессного взаимодействия:
- Очереди сообщений System V (msgget, msgctl).
- Shared Memory сегменты POSIX и SysV (shmget, shmat).
- Семафоры (semget, semctl).
- **Важно:** Если два процесса не разделяют IPC namespace, они не могут взаимодействовать через эти механизмы, даже если находятся в одном PID namespace.

#### Пространство имён UTS
Изолирует только два параметра:
- `hostname`
- `domainname` (NIS domain name, редко используется)
- Не изолирует версию ядра, uname или другие параметры системы.

#### Пространство имён Cgroup
Скрывает иерархию cgroups от процесса:
- Процесс видит только свою ветку cgroups, а не полную иерархию хоста.
- Используется для безопасности: контейнер не может анализировать cgroup-пути других контейнеров.

#### Пространство имён Time (Kernel 5.6+)
Позволяет изолировать и смещать системные часы:
- `CLOCK_BOOTTIME` и `CLOCK_BOOTTIME_ALARM` могут быть смещены независимо в каждом namespace.
- `CLOCK_MONOTONIC` и `CLOCK_MONOTONIC_COARSE` остаются неизменными (общие для всей системы).
- **Использование:** Отладка таймаутов, тестирование приложений с разным "временем жизни" системы.

---

### Персистентность и время жизни

По умолчанию пространство имён уничтожается, когда последний процесс в нем завершается. Однако его можно «закрепить» (**persist**), создав **bind mount** файла дескриптора из `/proc/[pid]/ns/[тип]` в другой файл в системе.

Пример (как это делает `ip netns`):
```bash
# Создание папки для закрепления
mkdir -p /run/netns
touch /run/netns/test_netns

# Закрепление пространства имен процесса PID
mount --bind /proc/$PID/ns/net /run/netns/test_netns
```
После этого пространство имён будет существовать, даже если все его процессы завершатся, пока не будет выполнен `umount`.

### Интроспекция и связи (ioctl)

Для анализа иерархий и связей между пространствами имён используются специфические вызовы `ioctl(2)` на файловых дескрипторах из `/proc/[pid]/ns/`:
- **`NS_GET_USERNS`**: Возвращает дескриптор пользовательского пространства имён, которому принадлежит данное пространство.
- **`NS_GET_PARENT`**: Возвращает дескриптор родительского пространства имён (для PID и User).
- **`NS_GET_NSTYPE`**: Возвращает тип пространства имён.

### Современные изменения (2024–2026)

#### Технология Pidfs (Kernel 6.8+)
Превращает дескрипторы процессов (pidfds) в полноценные объекты ФС, позволяя атомарно извлекать метаданные процессов и их пространства имён без гонок (race conditions).

#### Системный вызов listns(2) (Kernel 6.19+)
Обеспечивает быстрый и атомарный способ получения списка всех пространств имён в системе, заменяя ресурсоемкое сканирование `/proc`.

---

## Практические сценарии

### 1. Создание изолированной среды через unshare

```bash
# Изоляция сети, PID и монтирования с маппингом текущего пользователя в root
# -r эквивалентно --map-root-user
unshare -n -p -m -r --fork bash

# Внутри:
ip link # Только lo
ps -ef  # Список пуст (нужно перемонировать /proc)
mount -t proc proc /proc
```

### 2. Вход в существующее пространство через nsenter

```bash
# Вход в сетевой стек контейнера по его PID
sudo nsenter -t $PID -n ip addr show
```

### 3. Анализ пространств имён (lsns)

Утилита **lsns** предоставляет наиболее полный и удобный обзор всех активных пространств имен в системе.

```bash
# Просмотр всех пространств имен с указанием количества процессов (NPROCS)
sudo lsns

# Вывод только сетевых пространств имен (Network)
lsns -t net

# Узнать, к каким пространствам принадлежит конкретный PID
lsns -p <PID>
```

**Подробно:** [Утилита lsns](../Diagnostics/Processes/lsns.md).

### 4. Интеграция с systemd (Namespace Flags)

Systemd поддерживает изоляцию через namespace-флаги в юнитах. Это стандартный способ для SRE обеспечить изоляцию сервисов без контейнеризации.

```ini
# /etc/systemd/system/my-service.service
[Service]
ExecStart=/usr/bin/my-app
# Изоляция PID, Mount, Network, IPC, UTS
PrivatePID=true
PrivateMounts=true
PrivateNetwork=true
PrivateIPC=true
PrivateUTS=true
# Создание нового User Namespace с маппингом
PrivateUsers=true
```

Проверка:
```bash
systemctl daemon-reload
systemctl start my-service
# Проверка пространств имён сервиса
sudo lsns -p $(systemctl show --property=MainPID --value my-service)
```

### 5. Rootless-контейнеры (Podman/Docker)

User Namespace позволяет запускать контейнеры без root-привилегий. Для Podman это нативный режим:

```bash
# Создание subuid/subgid mappings (одноразово)
echo "$USER:100000:65536" | sudo tee -a /etc/subuid
echo "$USER:100000:65536" | sudo tee -a /etc/subgid

# Запуск контейнера без root
podman run --rm -it alpine sh

# Или через Docker rootless mode
dockerd-rootless-setuptool.sh install
```

**Примечание:** Rootless-режим имеет ограничения (нет доступа к портам <1024, ограниченный доступ к устройствам).

### 6. Изоляция пакетных задач (Batch Jobs)

Для фоновых задач (бэкапы, парсинг логов) можно создать изолированное окружение с собственным PID namespace:

```bash
# Запуск бэкапа в изолированном namespace с лимитами cgroups
systemd-run --unit=backup-job \
  --scope -p PIDNamespace=private \
  -p MemoryMax=2G -p CPUQuota=50% \
  /usr/local/bin/backup.sh

# Проверка статуса
systemctl status backup-job
```

### 7. Отладка сетевых проблем в контейнере

```bash
# Получение PID контейнера
PID=$(docker inspect -f '{{.State.Pid}}' my-app)

# Анализ через nsenter
sudo nsenter -t $PID -n -- tcpdump -i eth0 -w /tmp/container.pcap &
sudo nsenter -t $PID -n -- ss -tulnp

# Проверка маршрутизации
sudo nsenter -t $PID -n -- ip route show
sudo nsenter -t $PID -n -- ip addr show
```

### 8. Изоляция UTS для тестовых сред

```bash
# Создание изолированного хоста с уникальным hostname
sudo unshare --uts --fork bash
hostname test-container-01
# Выход из namespace возвращает исходный hostname
exit
hostname # Исходное имя хоста
```

### 9. Взаимодействие с cgroup Namespace

```bash
# Создание процесса с изолированным cgroup namespace
sudo unshare --cgroup --fork bash

# Внутри namespace видна только своя ветка cgroups
cat /proc/self/cgroup
# → 0::/
# На хосте видна полная иерархия
```

### 10. Time Namespace для отладки таймаутов

```bash
# Запуск приложения со смещённым Boottime (+3600 секунд)
sudo unshare --time --fork bash
# Внутри namespace clock_gettime(CLOCK_BOOTTIME) вернёт значение,
# смещённое на указанное количество секунд
```

---

## Безопасность и ограничения

### Взаимодействие с Capabilities

- Процесс в **User Namespace** может получить полный набор `capabilities`, но они действуют только внутри namespace.
- На хосте такие процессы остаются непривилегированными.
- **Security exception:** Некоторые операции (например, `mount` без `MS_BIND`) требуют, чтобы процесс в User Namespace имел `CAP_SYS_ADMIN` **и** был неназначен как "no_new_privs".

### Взаимодействие с SELinux и AppArmor

- **SELinux:** Работает на уровне хоста. Контейнеры должны быть маркированы соответствующими labels (`svirt_lxc_net_t` для Docker).
- **AppArmor:** По умолчанию контейнеры Docker/Podman запускаются в профиле `docker-default`. При создании собственного namespace вручную AppArmor не срабатывает автоматически.

### Ограничения и известные проблемы

1. **Thread-based namespace:** В Linux namespace привязаны к процессу, а не к потоку. Если один поток вызвал `unshare`, новые потоки, созданные через `clone(CLONE_THREAD)`, не попадают в новый namespace автоматически.
2. **Nested namespaces:** Глубина вложенности ограничена `kernel.pid_max` и реализацией. На практике более 32 уровней нестабильны.
3. **Mount namespace + pivot_root:** При использовании `pivot_root` в Mount Namespace требуется, чтобы новый корень и старый корень были разными mount points.
4. **User Namespace + YAMA LSM:** Если включён `YAMA` (ptrace scope), создание User Namespace может быть запрещено для непривилегированных процессов.
5. **Network Namespace + iptables:** В новом net-namespace нет правил iptables. Необходимо настроить filter/nat/route таблицы заново.

### Лимиты ядра

```bash
# Максимальное количество namespace в системе
cat /proc/sys/kernel/ns_last_pid

# Максимальное количество user namespaces на пользователя
cat /proc/sys/user/max_user_namespaces

# Максимальное количество pid namespaces
cat /proc/sys/kernel/pid_max
```

---

## Производительность и накладные расходы

- **CPU:** Практически нулевые. Переключение namespace происходит на уровне дескрипторов задач (task_struct) и не требует TLB flush.
- **Memory:** Минимальные. Основные накладные — это копирование структур данных при создании.
- **Network:** Зависит от конфигурации. veth-пары и bridges добавляют задержку <10 мкс на хоп.
- **Disk:** Mount namespace с большим количеством bind-mount может замедлить монтирование/размонтирование.

---

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Operation not permitted** | Попытка создания без root или без User Namespace. | Используйте `unshare -U` или убедитесь, что `user.max_user_namespaces > 0`. |
| **ps не видит процессов** | В новом PID namespace не обновлен `/proc`. | Выполните `mount -t proc proc /proc` внутри пространства. |
| **Утечки namespaces** | Остались активные bind-mounts. | Проверьте `mount | grep ns` и выполните `umount`. |
| **Коллизии IP** | Плохая изоляция netns в скриптах. | Убедитесь, что каждый `ip netns` имеет уникальное имя в `/run/netns`. |
| **Hostname не меняется** | UTS namespace не создан или не применён. | Проверьте `hostname` внутри namespace, убедитесь в использовании `--uts`. |
| **Container sees host processes** | PID namespace не изолирован или не смонтирован /proc. | Проверьте флаг `--pid` и монтирование proc. |
| **Permission denied на mount** | Попытка монтирования без CAP_SYS_ADMIN в User Namespace. | Добавьте флаг `--mount` при создании User Namespace или используйте bind-mount. |
| **No space left on device (shm)** | IPC shared memory переполнен. | Увеличьте `--shm-size` в Docker или создайте новый tmpfs mount. |
| **nsenter: cannot open /proc/…/ns/net: No such file** | Процесс завершился, bind-mount удалён. | Используйте PID процесса, который ещё существует, или закрепите namespace через bind-mount. |

---

## Best Practices

1. **Используйте User Namespace для непrivileged workloads:** Это baseline для безопасности контейнеров. Настройте `/etc/subuid` и `/etc/subgid` для всех service-аккаунтов.
2. **Крепите персистентные namespace:** Если namespace должен пережить перезапуск процесса, создайте bind-mount в `/run/netns/`.
3. **Не смешивайте Mount и PID namespace без необходимости:** Это увеличивает сложность отладки. Для обычных контейнеров достаточно стандартного набора (PID, Mount, UTS, IPC, Net).
4. **Мониторьте утечки namespace:** Регулярно проверяйте `lsns` и `/proc/*/ns/*`. Утечки могут привести к исчерпанию kernel memory.
5. **Ограничивайте nested namespaces:** Избегайте более 2 уровней вложенности. Это упрощает отладку и снижает риски.
6. **Используйте setns вместо nsenter для автоматизации:** `nsenter` удобен для ручной отладки, но в скриптах лучше использовать прямой `setns` через Python/Go или утилиту `nsenter` с явными путями.
7. **Настройте auditd для отслеживания namespace:** Добавьте правило `auditctl -a exit,always -F arch=b64 -S clone -S unshare -S setns` для отслеживания создания namespace в production.
8. **Тестируйте User Namespace в staging:** Перед включением в production проверьте совместимость приложений с remapped UIDs/GIDs.

---

## Граничные случаи и ограничения

1. **Thread placement:** Namespace привязан к процессу, а не к потоку. При `clone(CLONE_THREAD)` новые потоки наследуют namespace родителя.
2. **User namespace + no_new_privs:** Если у процесса установлен `no_new_privs` (бинарный hardening), он не сможет получить новые privileges даже внутри User Namespace.
3. **PID namespace + threading:** Многопоточные приложения в новом PID namespace видят только initiating thread как "main thread". Остальные потоки "исчезают" из `/proc`.
4. **Mount namespace + shared subtrees:** Если родительский mount использует `MS_SHARED`, изменения в дочернем namespace могут "просачиваться" обратно.
5. **Cgroup namespace + cgroup v2:** В cgroup v2 cgroup namespace скрывает только версии контроллеров, но не файлы ресурсов.
6. **Network namespace + lo:** В каждом net namespace интерфейс `lo` по умолчанию выключен (`state DOWN`). Необходимо явно `ip link set lo up`.
7. **IPC namespace + message queues:** Очереди сообщений POSIX (`mq_open`) не изолируются IPC namespace в ядрах до 5.10.
8. **UTS namespace + kernel logs:** `dmesg` показывает информацию хоста, даже в изолированном UTS namespace.
9. **Time namespace + adjtimex:** Системный вызов `adjtimex` игнорирует смещения Time Namespace и работает с глобальными часами.
10. **Nested user namespaces:** Вложенные user namespaces могут создавать "UID mapping loops", приводящие к indefinite recursion в kernel (CVE-2023-3266-ish классы багов).

---

## Дополнительная информация

### Инструменты мониторинга

| Инструмент | Назначение | Пример использования |
| :--- | :--- | :--- |
| `lsns` | Просмотр всех namespace. | `lsns -p <PID>` |
| `nsenter` | Вход в namespace процесса. | `nsenter -t $PID -n -- ip link` |
| `unshare` | Создание нового namespace. | `unshare -n -- ip link add veth0 type veth` |
| `ls /proc/*/ns/` | Ручной обзор namespace. | `ls -l /proc/1/ns/` |
| `cat /proc/self/cgroup` | Проверка cgroup namespace. | `cat /proc/self/cgroup` |

### Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Operation not permitted** | Попытка создания без root или без User Namespace. | Используйте `unshare -U` или убедитесь, что `user.max_user_namespaces > 0`. |
| **ps не видит процессов** | В новом PID namespace не обновлен `/proc`. | Выполните `mount -t proc proc /proc` внутри пространства. |
| **Утечки namespaces** | Остались активные bind-mounts. | Проверьте `mount | grep ns` и выполните `umount`. |
| **Коллизии IP** | Плохая изоляция netns в скриптах. | Убедитесь, что каждый `ip netns` имеет уникальное имя в `/run/netns`. |
| **Hostname не меняется** | UTS namespace не создан или не применён. | Проверьте `hostname` внутри namespace, убедитесь в использовании `--uts`. |
| **Container sees host processes** | PID namespace не изолирован или не смонтирован /proc. | Проверьте флаг `--pid` и монтирование proc. |
| **Permission denied на mount** | Попытка монтирования без CAP_SYS_ADMIN в User Namespace. | Добавьте флаг `--mount` при создании User Namespace или используйте bind-mount. |
| **No space left on device (shm)** | IPC shared memory переполнен. | Увеличьте `--shm-size` в Docker или создайте новый tmpfs mount. |
| **nsenter: cannot open /proc/…/ns/net: No such file** | Процесс завершился, bind-mount удалён. | Используйте PID процесса, который ещё существует, или закрепите namespace через bind-mount. |

### Связанные темы

- **[Утилита lsns](../Diagnostics/Processes/lsns.md)** — глубокая диагностика и инспекция пространств имен.
- **[Контрольные группы (cgroups)](./cgroups.md)** — управление лимитами ресурсов.
- **[Mount Namespaces](../Virtualization/mount_namespaces.md)** — детальное описание Propagation.
- **[Утилита ip netns](../Networking/Tools/iproute2/ip_netns.md)** — администрирование сетевой изоляции.
- **[systemd-nspawn](./systemd/nspawn.md)** — запуск изолированных окружений через systemd.
- **[Изоляция в Linux: Namespaces и Cgroups](../../Docker/Concepts/linux_isolation.md)** — роль в архитектуре Docker.
- **[Утилита nsenter](../Diagnostics/Processes/nsenter.md)** — вход в существующие пространства имён.
- **[Виртуализация и изоляция в Linux](../Virtualization/virtualization_overview.md)** — обзор механизмов изоляции.
