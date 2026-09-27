# iSCSI: Эксплуатация и диагностика

Руководство по обслуживанию, мониторингу и решению проблем в работе iSCSI-стека в ОС Linux.

## Определения и инструментарий

| Инструмент | Описание |
| :--- | :--- |
| **iscsiadm** | Основная утилита командной строки для управления базами данных discovery, узлов и активными сессиями. |
| **iscsid** | Фоновый демон, отвечающий за поддержание соединений, восстановление сессий и обработку событий протокола. |
| **targetcli** | Оболочка управления для ядерного таргета LIO (на стороне сервера). |
| **_netdev** | Опция монтирования в `/etc/fstab`, указывающая системе на необходимость дождаться инициализации сети. |

## Теоретическая база для диагностики

### Уровни восстановления ошибок (Error Recovery Levels, ERL)

Протокол iSCSI определяет три уровня восстановления ошибок, Negotiate-ся в фазе Login. Уровень определяет, кто — инициатор или таргет — отвечает за восстановление после сбоя:

| Уровень | Название | Кто восстанавливает | Описание |
| :--- | :--- | :--- | :--- |
| **ERL 0** | Default | Таргет | Нет восстановления на стороне инициатора. Любая ошибка приводит к потере сессии. Это уровень по умолчанию для большинства реализаций. |
| **ERL 1** | Session Recovery | Инициатор | Инициатор может восстанавливать потерянные команды в пределах одной сессии. Таргет хранит незавершённые задачи и позволяет инициатору запросить повторную передачу. |
| **ERL 2** | Full | Инициатор + Таргет | Полное восстановление на уровне_Connection_. Инициатор может переподключиться к другому порталу в пределах той же сессии и продолжить с того же LBA (Logical Block Address). Требует поддержки на обеих сторонах. |

**Почему это важно для диагностики:**
- При ERL 0 любая сетевая проблема (DROP, RST, таймаут) = потеря сессии + возможный переход ФС в RO
- При ERL 1 таргет буферизует команды, инициатор может восстановить сессию без потери данных (но с задержкой)
- При ERL 2 возможно переключение на другой путь без прерывания I/O (аналог Multipath на уровне протокола)

Проверка текущего уровня:
```bash
# На инициаторе (после Login)
sudo iscsiadm -m session -P 3 | grep -i "error recovery"
# → Error Recovery Level: 0 (или 1, 2)
```

### Обработка ошибок SCSI поверх iSCSI

iSCSI инкапсулирует SCSI-команды. Когда SCSI-устройство возвращает ошибку, она передаётся через iSCSI PDU и интерпретируется ядром Linux:

```text
Приложение (read/write)
    ↓
Block layer (I/O scheduler)
    ↓
SCSI subsystem (sd driver)
    ↓  ← SCSI errors здесь
iSCSI Initiator (open-iscsi)
    ↓  ← iSCSI errors здесь
TCP/IP stack
    ↓
Сеть
```

**Ключевые SCSI-понятия для диагностики:**

| Понятие | Описание | Пример в iSCSI |
| :--- | :--- | :--- |
| **SCSI Sense Key** | Код ошибки SCSI-устройства. Определяет тип проблемы:硬件 (Hardware), протокол, или программная. | `Medium Error` (повреждённые сектора), `Hardware Error` (target недоступен) |
| **ASC/ASCQ** | Additional Sense Code / Additional Sense Code Qualifier — уточнение Sense Key. Два байта, определяют конкретную ошибку. | `0x04/0x01` = Logical Unit Not Ready, `0x04/0x04` = LUN Not Available |
| **Task Set Full** | Таргет не может принять новую команду — очередь заполнена. Ядро Linux повторит попытку через einige мс. | Высокая нагрузка на target, исчерпание queue depth |
| **Unit Attention** | Таргет был перезагружен или LUN изменился. Сигнал для инициатора: обновить информацию о устройствах. | Перезагрузка target-сервера, изменение размера LUN |
| **Reservation Conflict** | Два инициатора пытаются одновременно записать в LUN без SCSI-3 Persistent Reservations. | Ошибка конфигурации Multi-Initiator |
| **CHECK CONDITION** | Таргет вернул ошибочное состояние. Инициатор должен выполнить REQUEST SENSE для получения Sense Data. | Любая ошибка на стороне target |

### Связка iSCSI ошибок с ядром Linux

Ядро Linux отображает ошибки iSCSI/SCSI в `dmesg` с префиксом `scsi hostX`:

```bash
# Просмотр всех ошибок SCSI/iSCSI
sudo dmesg | grep -E "scsi host[0-9]+" | grep -iE "error|fail|timeout|abort|reset"

# Типичные сообщения и их значение:
# "scsi host0: iSCSI login failed"              → Ошибка аутентификации/связности
# "scsi host0: iSCSI: session recovery timed out" → ERL 0, сессия потеряна
# "sd 0:0:0:0: [sda] tag#0 FAILED Result: hostbyte=DID_OK" → Ошибка блочного устройства
# "Buffer I/O error on dev sda, logical block 0" → ФС не может читать данные
```

**PID SCSI (Protocol Identifier):**
iSCSI использует PID = 0 для SCSI over TCP/IP. В `dmesg` это отображается как:
```text
scsi host0: iSCSI Initiator over TCP/IP
```

## Основные команды диагностики

### Управление сессиями и узлами
```bash
# Список активных сессий (кратко)
sudo iscsiadm -m session

# Подробная информация о сессиях (LUN, пути, таймауты, состояние TCP)
sudo iscsiadm -m session -P 3

# Просмотр базы данных обнаруженных узлов
sudo iscsiadm -m node

# Вывод параметров конкретного узла
sudo iscsiadm -m node -T <IQN> -p <IP>

# Rescan: обнаружение новых/изменённых LUN на существующих сессиях
sudo iscsiadm -m session --rescan

# Принудительный logout (без сохранения параметров)
sudo iscsiadm -m node -T <IQN> -p <IP> --logout

# Logout со всех порталов данного target
sudo iscsiadm -m node -T <IQN> --logout

# Logout отовсюду (все сессии)
sudo iscsiadm -m node --logoutall=all

# Удаление записи о target из базы данных (после logout)
sudo iscsiadm -m node -T <IQN> -p <IP> -o delete

# Удаление discovery-записи
sudo iscsiadm -m discoverydb -t st -p <IP> -o delete
```

### Управление CHAP-учетными данными
```bash
# Установка CHAP-аутентификации для узла
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.authmethod -v CHAP

# Установка логина/пароля инициатора (для взаимного CHAP)
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.username -v <USER>
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.password -v <PASS>

# Установка логина/пароля таргета (для взаимного CHAP —.target проверяет инициатор)
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.username_in -v <TARGET_USER>
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.password_in -v <TARGET_PASS>

# Отключение CHAP (возврат к None)
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.authmethod -v None
```

### Управление iface (привязка к интерфейсу)
```bash
# Создание iface-профиля для конкретного NIC
sudo iscsiadm -m iface -I iscsi_eth1 --op=new -n iface.net_ifacename -v eth1

# Просмотр всех iface-профилей
sudo iscsiadm -m iface

# Привязка iface к target (при discovery)
sudo iscsiadm -m discovery -t sendtargets -p <IP> -I iscsi_eth1

# Удаление iface-профиля
sudo iscsiadm -m iface -I iscsi_eth1 --op=delete
```

### Discovery database
```bash
# Ручное добавление discovery-записи
sudo iscsiadm -m discoverydb -o new -t st -p <IP> -I default
sudo iscsiadm -m discoverydb -o update -t st -p <IP> \
  -n discovery.sendtargets.auth.authmethod -v CHAP
sudo iscsiadm -m discoverydb -o update -t st -p <IP> \
  -n discovery.sendtargets.auth.username -v <USER>
sudo iscsiadm -m discoverydb -o update -t st -p <IP> \
  -n discovery.sendtargets.auth.password -v <PASS>

# Запуск discovery через discoverydb
sudo iscsiadm -m discoverydb -t st -p <IP> --discover
```

### Мониторинг системных событий
iSCSI активно взаимодействует с подсистемой SCSI ядра, поэтому большинство критических событий отражается в `dmesg`.
```bash
# Просмотр ошибок iSCSI и SCSI в реальном времени
sudo journalctl -k -f | grep -E "iscsi|scsi"

# Проверка статуса демона
sudo systemctl status iscsid
```

## Справочник ошибок iSCSI

### Коды ошибок iscsiadm (initiator reported error)

| Код | Сообщение | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **4** | `iscsiadm: initiator reported error (4 - could not create session)` | Не удалось создать сессию. Нехватка ресурсов или неверный параметр. | Проверить `iscsid.conf`, перезапустить `iscsid`, проверить память (`free -m`) |
| **5** | `iscsiadm: initiator reported error (5 - authorization failure)` | CHAP-аутентификация не прошла. Неверный логин/пароль. | `iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.username -v <USER>` |
| **6** | `iscsiadm: initiator reported error (6 - not authorized)` | IQN инициатора не в ACL на таргете. | Добавить IQN в ACL через `targetcli /iscsi/<iqn>/tpg1/acls create <initiator_iqn>` |
| **10** | `iscsiadm: initiator reported error (10 - timout)` | Таймаут подключения к порталу. Target недоступен или firewall блокирует порт 3260. | `nc -zv <TARGET_IP> 3260`, проверить firewall, `ping -M do -s 1472 <TARGET_IP>` |
| **12** | `iscsiadm: initiator reported error (12 - session already exists)` | Сессия с этим таргетом уже активна. | `iscsiadm -m session` для проверки, `iscsiadm -m session -o delete -r <sid>` для удаления |
| **15** | `iscsiadm: initiator reported error (15 - session not found)` | Попытка عملа с несуществующей сессией. | `iscsiadm -m session` для списка активных |
| **17** | `iscsiadm: initiator reported error (17 - could not create connection)` | TCP-соединение не установлено. Target не слушает порт или сеть недоступна. | `nc -zv <TARGET_IP> 3260`, `ss -tpln | grep 3260`, `mtr <TARGET_IP>` |
| **20** | `iscsiadm: initiator reported error (20 - discovery error)` | SendTargets discovery не удался. | Проверить portal, target IQN, firewall |
| **24** | `iscsiadm: initiator reported error (24 - iSCSI login failed due to authorization failure)` | См. код 5. Детализированная версия ошибки аутентификации. | Проверить CHAP credentials, ACL на target |

### Ключевые SCSI Sense Codes

| Sense Key | ASC/ASCQ | Описание | Типичная причина в iSCSI |
| :--- | :--- | :--- | :--- |
| **Not Ready (0x02)** | `0x04/0x01` | LUN Not Ready, Logical Unit Not Ready, Cause Not Reportable | LUN не экспортируется таргетом, target перезагружается |
| **Not Ready (0x02)** | `0x04/0x04` | LUN Not Available (Offline) | Target-offline, multipath degradation |
| **Medium Error (0x03)** | `0x11/0x00` | Unrecovered Read Error | Проблемы с диском на стороне target (_checksum не совпал) |
| **Hardware Error (0x04)** | `0x00/0x00` | No Sense / No Additional Sense Information | Target недоступен, сетевой сбой, Hardware Failure на target |
| **Illegal Request (0x05)** | `0x20/0x00` | Invalid Command Operation Code | Неподдерживаемая SCSI-команда (редко) |
| **Unit Attention (0x06)** | `0x29/0x00` | Power On, Reset, or Bus Reset | Target был перезагружен или LUN изменён |
| **Unit Attention (0x06)** | `0x29/0x02` | Reset (SCSI Bus Reset) | Target сбросил SCSI-шину |
| **Unit Attention (0x06)** | `0x2A/0x01` | Mode Parameters Changed | Конфигурация LUN изменилась |
| **Copy Aborted (0x0B)** | `0x2C/0x00` | Sequence Error | Нарушен порядок команд |
| **Aborted Command (0x0B)** | `0x0B/0x00` | Async Notification | Target отправил asynchronous event |
| **Aborted Command (0x0B)** | `0x0B/0x02` | Aborted Task Set | Таргет отменил все команды в очереди |

### Сообщения ядра (dmesg) и их значение

| Сообщение | Уровень | Описание | Действие |
| :--- | :--- | :--- | :--- |
| `iSCSI login failed` | ERROR | Сессия не установлена | Коды 5/6/10/17 выше |
| `session recovery timed out` | WARNING | ERL 0: восстановление не удалось | Увеличить `replacement_timeout`, проверить сеть |
| `Connection reset` | INFO | TCP RST от target | Проверить target, firewall |
| `Buffer I/O error` | ERROR | ФС не может прочитать блок | Проверить target, disk, multipath |
| `critical target error` | ERROR | SCSI Critical Target Error | Проблемы Hardware на target |
| `host busy` | WARNING | SCSI host перегружен | Уменьшить нагрузку, увеличить `nr_io_slots` |
| `target port login timeout` | ERROR | Таймаут входа на target portal | `nc -zv <IP> 3260`, проверить target |

## Диагностическое дерево решений

Используйте следующую последовательность для быстрой идентификации проблемы:

```text
Симптом
├── Не могу подключиться (Discovery/Login)
│   ├── nc -zv <IP> 3260 → FAILED
│   │   ├── Target выключен? → Проверить power/target-сервис
│   │   ├── Firewall? → sudo iptables -L -n | grep 3260
│   │   └── Маршрутизация? → mtr <IP>, ip route get <IP>
│   └── nc -zv <IP> 3260 → OK
│       ├── Ошибка аутентификации (error 5/6/24) → Проверить CHAP/ACL
│       ├── Ошибка таймаута (error 10/17) → Увеличить timeout, проверить MTU
│       └── Session exists (error 12) → iscsiadm -m session
├── Сессия есть, но ФС в RO
│   ├── dmesg: "session recovery timed out" → Проверить replacement_timeout
│   ├── nstat -az | grep Retrans → Высокое значение → Проблема сети
│   └── multipath -ll → faulty paths → Проблема Multipath
├── Зависание при shutdown/reboot
│   ├── /etc/fstab: нет _netdev → Добавить _netdev
│   └── /etc/fstab: есть _netdev → Проверить order systemd units
├── Медленная работа
│   ├── iostat -xy 2: r_await > 10ms → Проблема диска/очереди
│   ├── nstat: Retransmissions растут → Проблема сети
│   ├── multipath -ll: path switching → Проблема Multipath
│   └── Всё нормально → Проверить Application layer
├── ЛУН не виден после rescan
│   ├── iscsiadm -m session --rescan → OK, но LUN нет → Target не экспортирует
│   ├── lsblk → sda есть, но нет раздела → fdisk -l /dev/sda
│   └── lsblk → sda нет → Проблема SCSI discovery
└── Reservation Conflict
    ├── Два инициатора на один LUN без PR → Настроить SCSI-3 PR
    └── Один инициатор → Проверить target-side PR
```

## Параметры iscsid.conf для диагностики

Файл `/etc/iscsi/iscsid.conf` содержит ключевые параметры, влияющие на поведение восстановления и диагностику:

### Таймауты восстановления

| Параметр | Значение по умолч. | Описание | Рекомендация |
| :--- | :--- | :--- | :--- |
| `node.session.timeo.replacement_timeout` | 120 | Время ожидания (сек) восстановления сессии при потере связи. По истечении — сессия считается потерянной, устройство OFFLINE. | Увеличить до 180-300 при нестабильной сети |
| `node.conn[0].timeo.noop_out_interval` | 15 | Интервал (сек) отправки NOP-Out (keepalive) пакетов. | Уменьшить до 5-10 для более быстрого обнаружения потери связи |
| `node.conn[0].timeo.noop_out_timeout` | 15 | Таймаут (сек) ожидания ответа на NOP-Out. | Уменьшить до 5-10, если сеть стабильна |
| `node.session.initial_login_retry_max` | 8 | Максимальное количество попыток повторного Login при первичном подключении. | Увеличить до 12-16 для медленных target'ов |
| `node.session.cmds_max` | 32 | Максимальное количество одновременных SCSI-команд в сессии. | Увеличить до 64-128 для высоконагруженных систем |
| `node.session.queue_depth` | 32 | Глубина очереди I/O на уровне сессии. | Увеличить до 64-256 для баз данных |

### Диагностические параметры

| Параметр | Значение по умолч. | Описание |
| :--- | :--- | :--- |
| `iscsi.disc_max` | 1 | Количество discovery-попыток при старте. |
| `node.startup` | manual | Автоматическое подключение при загрузке (`automatic`) или ручное (`manual`). |
| `node.session.auth.authmethod` | None | Метод аутентификации: `None` или `CHAP`. |
| `node.session.err_timeout` | — | Таймаут (сек) для ошибок сессии (если поддерживается реализацией). |
| `node.session.iscsi.InitialR2T` | No | Если `Yes`, инициатор ждёт R2T (Ready To Transfer) перед отправкой данных. `No` — данные отправляются сразу (инициативный режим). |
| `node.session.iscsi.ImmediateData` | Yes | Разрешить передачу данных в Login-фазе (снижает latency для маленьких запросов). |
| `node.session.iscsi.FirstBurstLength` | 262144 | Максимальный объём данных (байт), которые инициатор может отправить без R2T. |
| `node.session.iscsi.MaxBurstLength` | 16776192 | Максимальный объём данных в одном SCSI-ответе (байт). |

### Пример конфигурации для диагностики

```ini
# /etc/iscsi/iscsid.conf (диагностический профиль)

# Более агрессивный keepalive для быстрого обнаружения потери связи
node.conn[0].timeo.noop_out_interval = 5
node.conn[0].timeo.noop_out_timeout = 5

# Увеличенный таймаут восстановления для нестабильных сетей
node.session.timeo.replacement_timeout = 180

# Увеличенная очередь для высоконагруженных систем
node.session.cmds_max = 64
node.session.queue_depth = 64

# Автологин при старте
node.startup = automatic
```

## Debug-логирование iscsid

### Включение детального логирования

```bash
# Запуск iscsid с максимальным уровнем логирования (отладка)
sudo iscsiadm -d 8 -f

# Уровни логирования (от 0 до 8):
# 0 - Minimal (только ошибки)
# 1 - Normal
# 2 - Informational
# 4 - Debug
# 8 - Maximum (все сообщения, включая.hex дампы PDU)

# Просмотр логов в реальном времени
sudo journalctl -u iscsid -f

# Фильтрация только ошибок iSCSI
sudo journalctl -u iscsid -p err

# Просмотр логов за последний час
sudo journalctl -u iscsid --since "1 hour ago"
```

### Централизованная фильтрация через rsyslog

```bash
# /etc/rsyslog.d/30-iscsi.conf
# Все сообщения iscsid в отдельный файл
:programname, isequal, "iscsid" /var/log/iscsid.log

# Сообщения ядра, связанные с iSCSI/SCSI
:msg, contains, "iSCSI" /var/log/iscsi_kernel.log
:msg, contains, "scsi host" /var/log/iscsi_kernel.log & stop
```

```bash
# Перезапуск rsyslog
sudo systemctl restart rsyslog
```

### Просмотр hex-дампов PDU

Если включен уровень логирования 8, iscsid записывает hex-дампы всех iSCSI PDU. Это полезно для анализа на уровне протокола:

```bash
# Просмотр последних PDU-дампов
sudo journalctl -u iscsid | grep -A 20 "PDU" | tail -60

# Поиск конкретных opcode'ов в дампах
# Login Request: 0x03, Login Response: 0x04
# SCSI Command: 0x01, SCSI Response: 0x21
# Data-Out: 0x02, Data-In: 0x22
```

## Практические сценарии решения проблем

### 1. Ошибки авторизации и ACL
**Симптом:** `iscsiadm: initiator reported error (24 - iSCSI login failed due to authorization failure)`
- **Диагностика:** Проверьте соответствие IQN в `/etc/iscsi/initiatorname.iscsi` тому, что прописано в ACL на таргете.
- **Решение:** Если используется CHAP, убедитесь, что логин/пароль установлены для узла:
  ```bash
  sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.username -v <USER>
  ```

### 2. Таймауты и переход устройства в Read-Only
**Симптом:** Сообщения `scsi hostX: iSCSI: session recovery timed out` и перемонтирование ФС в RO.
- **Причина:** Временная потеря сетевой связности превысила `replacement_timeout`.
- **Диагностика:** Проверьте счетчики TCP-ретрансмиссий: `nstat -az TcpExtTcpRetransSegs`.
- **Решение:** 
    1. Проверьте стабильность сети и Flow Control на коммутаторах.
    2. При необходимости увеличьте время ожидания восстановления в `/etc/iscsi/iscsid.conf`:
       ```ini
       node.session.timeo.replacement_timeout = 120
       ```
    3. После стабилизации сети следуйте пошаговому плану восстановления: [Устранение неполадок: ФС в режиме read-only](../../FileSystems/read_only_filesystem_troubleshooting.md).

### 3. Зависание при выгрузке или выключении
**Симптом:** Система "виснет" на этапе Stop Jobs для iSCSI.
- **Причина:** Попытка закрыть сетевой интерфейс до того, как iSCSI-сессии были корректно завершены.
- **Решение:** Проверьте `/etc/fstab`. Убедитесь, что для iSCSI-устройств указана опция `_netdev`.

### 4. Ошибки Discovery (Connection Refused/Timeout)
**Симптом:** `iscsiadm: can not connect to iSCSI portal`
- **Диагностика:**
  ```bash
  # Проверка доступности порта с инициатора
  nc -zv <TARGET_IP> 3260
  # Проверка прослушивания порта на таргете
  ss -tpln | grep 3260
  ```

### 5. LUN не виден после Rescan (Rescan без результата)
**Симптом:** `iscsiadm -m session --rescan` выполнен успешно, но `lsblk` не показывает новый диск.
- **Диагностика:**
  ```bash
  # Проверка текущих LUN на сессии
  sudo iscsiadm -m session -P 3 | grep "iSCSI Session"

  # Проверка SCSI-устройств ядра
  sudo lsscsi

  # Проверка целевых LUN на target (с.target-сервера)
  sudo targetcli /iscsi/<iqn>/tpg1/luns ls
  ```
- **Решение:**
  1. Убедитесь, что LUN экспортируется таргетом: `sudo targetcli /iscsi/<iqn>/tpg1/luns ls`
  2. Выполните полный rescan SCSI-шину: `sudo iscsiadm -m session --rescan`
  3. Если LUN есть, но не отображается, выполните ручной rescan: `echo 1 | sudo tee /sys/class/scsi_host/host0/scan`
  4. Проверьте логи: `sudo dmesg | grep -i "scsi host" | tail -20`

### 6. Изменение размера LUN (Resize) на целевой стороне
**Симптом:** Размер LUN на target увеличен, но `lsblk` показывает старый размер.
- **Диагностика:**
  ```bash
  # Текущий размер на целевом устройстве
  lsblk /dev/sda

  # Размер LUN на target (с.target-сервера)
  sudo targetcli /iscsi/<iqn>/tpg1/luns ls /backstores/block/<backstore>
  ```
- **Решение:**
  ```bash
  # 1. Обновить размер LUN на target (если это LVM, расширить LV)
  sudo lvextend -L +10G /dev/vg0/lun0

  # 2. На инициаторе: обнаружить изменение размера
  sudo iscsiadm -m session --rescan

  # 3. Проверить новый размер
  lsblk /dev/sda

  # 4. Расширить ФС (ext4)
  sudo resize2fs /dev/sda1

  # 5. Расширить ФС (XFS)
  sudo xfs_growfs /mount/point
  ```

### 7. Reservation Conflict (Конфликт резервирования)
**Симптом:** `sg_persist` или приложение reports `Reservation Conflict` или `Device or resource busy`.
- **Причина:** Два или более инициатора пытаются одновременно записать в LUN без настроенных SCSI-3 Persistent Reservations (PR). Без PR доступ к LUN из нескольких хостов приводит к повреждению данных.
- **Диагностика:**
  ```bash
  # Проверка текущих PR (с.target-сервера)
  sudo targetcli /iscsi/<iqn>/tpg1/luns ls

  # Проверка PR-списка на инициаторе
  sudo sg_persist -r /dev/sda

  # Проверка всех инициаторов, подключённых к LUN (с.target-сервера)
  sudo targetcli /iscsi/<iqn>/tpg1/acls ls
  ```
- **Решение:**
  - **Вариант 1 (рекомендуется):** Используйте Multipath для доступа к LUN с одного хоста, а остальные хосты подключайте через другой LUN или используйте кластерную ФС (GFS2, OCFS2).
  - **Вариант 2:** Настройте SCSI-3 PR на target для координации доступа:
    ```bash
    # На target: резервирование LUN для конкретного инициатора
    sudo targetcli /iscsi/<iqn>/tpg1/luns/lun0 set attribute reservation_type=pr
    ```
  - **Вариант 3:** Используйте `sg_persist` для ручного управления PR:
    ```bash
    # Регистрация инициатора
    sudo sg_persist -s -I <service_action_range> /dev/sda

    # Резервирование LUN
    sudo sg_persist -W -T 5 -K <pr_key> /dev/sda
    ```

### 8.iscsid: session not found (Сессия не найдена)
**Симптом:** `iscsiadm: can not rescan session [session = 1, target = ...]: session not found`
- **Причина:** Сессия была автоматически закрыта демоном iscsid (таймаут, ошибка).
- **Диагностика:**
  ```bash
  # Проверка активных сессий
  sudo iscsiadm -m session

  # Проверка логов iscsid
  sudo journalctl -u iscsid --since "5 min ago" | grep -i "session"
  ```
- **Решение:**
  ```bash
  # Переподключение к target
  sudo iscsiadm -m node -T <IQN> -p <IP> --login

  # Если сессия "зависла" — удалить и пересоздать
  sudo iscsiadm -m node -T <IQN> -p <IP> -o delete
  sudo iscsiadm -m discovery -t sendtargets -p <IP>
  sudo iscsiadm -m node -T <IQN> -p <IP> --login
  ```

## Мониторинг производительности

### Анализ задержек ввода-вывода (Latency)
Используйте `iostat` для выявления узких мест в дисковой подсистеме:
```bash
# r_await и w_await показывают задержку в мс
iostat -xy 2
```

### Глубокий сетевой анализ (tcpdump)

Для анализа проблем на уровне протокола iSCSI можно захватить трафик и проанализировать его в Wireshark:

```bash
# Захват iSCSI трафика на интерфейсе eth1
sudo tcpdump -i eth1 port 3260 -w iscsi_debug.pcap

# Ограничение размера файла (1000 пакетов)
sudo tcpdump -i eth1 port 3260 -w /tmp/iscsi_debug.pcap -c 1000

# Захват только SYN-пакетов (проверка TCP Handshake)
sudo tcpdump -i eth1 port 3260 -nn 'tcp[tcpflags] & tcp-syn != 0' -c 20

# Захват только RST-пакетов (сброс соединений — индикатор проблем)
sudo tcpdump -i eth1 port 3260 -nn 'tcp[tcpflags] & tcp-rst != 0'

# Фильтрация по конкретному хосту
sudo tcpdump -i eth1 host 192.168.200.20 and port 3260 -w /tmp/iscsi_host.pcap

# Анализ без записи в файл (консольный вывод)
sudo tcpdump -i eth1 port 3260 -v 2>&1 | grep -iE "login|read|write|reject|reset"
```

### Wireshark: display-фильтры для анализа iSCSI

| Фильтр | Описание |
| :--- | :--- |
| `iscsi` | Все iSCSI-пакеты |
| `iscsi.opcode == 0x01` | Login Request |
| `iscsi.opcode == 0x02` | Login Response |
| `iscsi.opcode == 0x03` | SCSI Read (Data-In) |
| `iscsi.opcode == 0x04` | SCSI Write (Data-Out) |
| `iscsi.opcode == 0x21` | SCSI Response |
| `iscsi.status != 0x00` | Все ошибки протокола (non-Success) |
| `iscsi.status == 0x02` | SCSI Check Condition (Sense Key) |
| `iscsi.status == 0x03` | SCSI Task Set Full |
| `iscsi.status == 0x04` | SCSI Task Aborted |
| `tcp.flags.reset == 1` | TCP RST (сброс соединения) |
| `tcp.analysis.retransmission` | TCP-ретрансмиссии |
| `tcp.analysis.zero_window` | TCP Zero Window (переполнение буфера接收ителя) |
| `tcp.analysis.duplicate_ack` | Дублирующие ACK (потеря пакетов) |

### Типичные паттерны ошибок в tcpdump

| Паттерн | Значение | Диагностика |
| :--- | :--- | :--- |
| Login Response с `0x01` (Authorization Failure) | Ошибка CHAP/ACL | Проверить credentials |
| Повторяющиеся Login Request без Response | Target не отвечает | Target недоступен, firewall |
| TCP RST после SCSI Command | Target сбросил соединение | Проблема на target |
| TCP Retransmissions > 5 за 10 сек | Потеря пакетов в сети | Проверить коммутатор, MTU |
| Data-In с SCSI Error Status | Ошибка чтения на target | Проверить диск на target |

## Скрипт автоматизации диагностики

### Health-check скрипт

```bash
#!/bin/bash
# /usr/local/bin/iscsi_health_check.sh
# Быстрая проверка состояния iSCSI-стека
# Использование: iscsi_health_check.sh [portal_ip]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0

echo "=== iSCSI Health Check ==="
echo "Дата: $(date)"
echo "Хост: $(hostname)"
echo ""

# 1. Проверка демона iscsid
echo -n "1. iscsid: "
if systemctl is-active --quiet iscsid; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED (is not running)${NC}"
    ((ERRORS++))
fi

# 2. Количество активных сессий
echo -n "2. Активные сессии: "
SESSION_COUNT=$(iscsiadm -m session 2>/dev/null | grep -c "tcp:" || echo 0)
if [ "$SESSION_COUNT" -gt 0 ]; then
    echo -e "${GREEN}$SESSION_COUNT${NC}"
else
    echo -e "${RED}0 (нет сессий)${NC}"
    ((ERRORS++))
fi

# 3. Статус каждой сессии
echo ""
echo "3. Детали сессий:"
iscsiadm -m session 2>/dev/null | while read -r line; do
    PORTAL=$(echo "$line" | awk '{print $2}')
    IQN=$(echo "$line" | awk '{print $3}')
    echo "   Portal: $PORTAL | IQN: $IQN"

    # Проверка состояния
    STATE=$(iscsiadm -m session -P 1 2>/dev/null | grep -A1 "$PORTAL" | grep "State" | awk '{print $NF}')
    if [ "$STATE" = "LOGGED" ]; then
        echo -e "   Состояние: ${GREEN}LOGGED IN${NC}"
    else
        echo -e "   Состояние: ${RED}$STATE${NC}"
        ((ERRORS++))
    fi
done

# 4. Проверка multipath
echo ""
echo -n "4. Multipath: "
if command -v multipath &>/dev/null; then
    FAULTY=$(multipath -ll 2>/dev/null | grep -c "faulty" || echo 0)
    if [ "$FAULTY" -eq 0 ]; then
        echo -e "${GREEN}OK (0 faulty paths)${NC}"
    else
        echo -e "${RED}$FAULTY faulty paths${NC}"
        ((ERRORS++))
    fi
else
    echo -e "${YELLOW}multipath не установлен${NC}"
fi

# 5. TCP-ретрансмиссии
echo -n "5. TCP Retransmissions: "
RETRANS=$(nstat -az TcpExtTcpRetransSegs 2>/dev/null | awk '/TcpExtTcpRetransSegs/ {print $2}' || echo 0)
if [ "$RETRANS" -lt 100 ]; then
    echo -e "${GREEN}$RETRANS${NC}"
else
    echo -e "${YELLOW}$RETRANS (высокое значение)${NC}"
fi

# 6. Доступность портала (если указан)
if [ -n "${1:-}" ]; then
    echo -n "6. Портал $1:3260: "
    if timeout 3 bash -c "echo >/dev/tcp/$1/3260" 2>/dev/null; then
        echo -e "${GREEN}доступен${NC}"
    else
        echo -e "${RED}недоступен${NC}"
        ((ERRORS++))
    fi
fi

echo ""
if [ "$ERRORS" -eq 0 ]; then
    echo -e "Итог: ${GREEN}OK${NC}"
    exit 0
else
    echo -e "Итог: ${RED}$ERRORS ошибок${NC}"
    exit 1
fi
```

```bash
# Установка
sudo install -m 755 /dev/stdin /usr/local/bin/iscsi_health_check.sh << 'SCRIPT'
#!/bin/bash
# ... (содержимое выше)
SCRIPT

# Запуск
sudo /usr/local/bin/iscsi_health_check.sh 192.168.200.20
```

## Аварийное восстановление

### iscsid не запускается

```bash
# Проверка ошибок запуска
sudo systemctl status iscsid
sudo journalctl -u iscsid --since "5 min ago"

# Перезапуск с очисткой состояния
sudo systemctl stop iscsid
sudo rm -f /run/lock/iscsi/iscsid.lock
sudo systemctl start iscsid

# Если iscsid не запускается из-за повреждённых данных
sudo systemctl stop iscsid
sudo rm -rf /var/lib/iscsi/nodes/*
sudo rm -rf /var/lib/iscsi/send_targets/*
sudo systemctl start iscsid
# Затем выполнить discovery заново
sudo iscsiadm -m discovery -t sendtargets -p <TARGET_IP>
```

### Принудительный logout (если iscsiadm hang)

```bash
# Если iscsiadm завис и не отвечает
sudo kill -9 $(pgrep iscsiadm)

# Удаление сессии напрямую через sysfs
sudo rm -rf /sys/class/iscsi_session/session*

# Перезапуск iscsid
sudo systemctl restart iscsid
```

### Экстренное размонтирование iSCSI-устройств

```bash
# 1. Остановка всех процессов, использующих iSCSI-устройства
sudo fuser -km /dev/sdX

# 2. Синхронизация буферов
sudo sync

# 3. Размонтирование
sudo umount -f /mount/point

# 4. Если umount не помогает — принудительное размонтирование
sudo umount -f -l /mount/point

# 5. Отключение iSCSI-сессии
sudo iscsiadm -m node -T <IQN> -p <IP> --logout

# 6. Если ничего не помогает — emergency reboot
sudo reboot -f
```

### Восстановление после потери target-сервера

```bash
# 1. Проверить, что target действительно недоступен
nc -zv <TARGET_IP> 3260

# 2. Проверить доступность альтернативных порталов
sudo iscsiadm -m session -P 3 | grep "Portal"

# 3. Если target вернулся — переподключение
sudo iscsiadm -m node -T <IQN> -p <IP> --login

# 4. Проверка, что устройства снова доступны
lsblk
sudo multipath -ll

# 5. Если ФС была в RO — перемонтировать в RW
sudo mount -o remount,rw /mount/point
```

## Дополнительная информация

### Влияние Multipath
Если используется Multipath, диагностику следует начинать с проверки путей:
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — команды `multipath -ll` и управление группами.

### Оптимизация
Многие проблемы "медленной работы" решаются тюнингом параметров сессии и сетевого стека:
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — Jumbo Frames, MTU и таймауты.

### Мониторинг
Для централизованного мониторинга и настройки алертинга:
- **[Мониторинг iSCSI](./iscsi_monitoring.md)** — метрики, Prometheus, Grafana.

### Безопасность
Проблемы аутентификации и доступа:
- **[Безопасность iSCSI](./iscsi_security.md)** — CHAP, ACL, сетевая изоляция.

### Резервное копирование
Стратегии обеспечения целостности данных:
- **[Резервное копирование iSCSI](./iscsi_backup.md)** — снапшоты, консистентность, бэкап.

### Теоретическая база
- **[Основные концепции iSCSI](./iscsi_concepts.md)** — архитектура PDU, фазы сессий и IQN.
- **[Настройка Firewall](../Settings/tools/firewalld.md)** — открытие порта 3260.

