# Chrony — NTP-сервер

## Определения

**Chrony** — полноценный NTP-демон для Linux, оптимизированный для работы в условиях нестабильного сетевого соединения, виртуализации и необходимости микросекундной точности. Состоит из двух компонентов: `chronyd` (фоновый демон) и `chronyc` (утилита управления).

**NTP (Network Time Protocol)** — протокол синхронизации часов компьютеров через сети. Работает по иерархической модели stratum (0–15), где stratum 0 — атомные часы/GPS, stratum 1 — серверы, подключённые напрямую к stratum 0. Детали протокола (формат пакета, режимы работы, алгоритм расчёта offset/delay) описаны в [NTP — Network Time Protocol](../../../Networking/Protocols/ntp.md).

**NTS (Network Time Security)** — расширение NTP (RFC 8915), обеспечивающее аутентификацию и целостность данных с использованием TLS 1.3 и AEAD, предотвращая атаки типа Man-in-the-Middle (MitM).

**PTP (Precision Time Protocol)** — протокол сверхточной синхронизации (IEEE 1588). Chrony может использовать аппаратные метки времени (Hardware Timestamping) сетевых карт для достижения наносекундной точности.

> Базовая синхронизация через `systemd-timesyncd` описана в [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md).

## Базовые концепции

### Архитектура NTP и модель stratum

NTP использует иерархическую модель stratum для минимизации задержки и повышения точности:

| Stratum | Описание | Пример |
| :--- | :--- | :--- |
| **0** | Аппаратные референсы (атомные часы, GPS, PPS) | Цезиевые часы, GPS-приёмники |
| **1** | Серверы, подключённые к Stratum 0 напрямую | Серверы с GPS/PPS-картой |
| **2–14** | Клиенты, синхронизирующиеся через NTP | Ваши серверы, настроенные через chrony |
| **15** | Максимально удалённый сервер | Не используется в production |
| **16** | Ошибка синхронизации (unsynchronized) | Промежуточное состояние при старте |

**Правило:** Чем ниже stratum, тем выше точность. При потере связи с внешними источниками chrony с директивой `local stratum` продолжает раздавать время, увеличивая stratum для клиентов на +1.

### Режимы работы NTP

Chrony поддерживает все основные режимы NTP:

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Client/Server** | Клиент опрашивает сервер (по умолчанию) | Стандартная конфигурация |
| **Symmetric Active/Passive** | Два пира обмениваются временем | mesh-топологии, избырные пути |
| **Broadcast/Multicast** | Сервер рассылает время в сегменте | Локальная сеть с многими клиентами |

### Алгоритм выбора источника (Marzullo)

Chrony использует алгоритм Марцулло для выбора наилучшего источника среди нескольких серверов:

1. Для каждого источника вычисляется интервал `offset ± dispersion`.
2. Все интервалы пересекаются (intersection).
3. Находится наименьший интервал, содержащий пересечение большинства источников.
4. Источник с наименьшим `root dispersion` считается основным (`*`), остальные пригодные источники помечаются `+`.

Источники, не попадающие в intersection, помечаются как `x` (falseticker — время не совпадает с большинством). Это защищает от атак подмены времени через компрометацию одного сервера.

### Внутренняя архитектура chronyd

`chronyd` работает в userspace и взаимодействует с ядром через системные вызовы `adjtime()` / `clock_adjtime()`:

- **Главный поток (Main thread)** — принимает входящие соединения на Unix-domain сокете `/var/run/nscd/socket`, распределяет запросы по рабочим потокам.
- **Рабочие потоки (Worker threads)** — опрашивают источники, вычисляют статистику, применяют коррекцию.
- **Shared memory сегмент** — содержит актуальное состояние синхронизации (offset, drift, stratum), к которому имеют доступ `chronyd` и `chronyc` без IPC-задержек.
- **Коррекция часов:** `slewing` (плавная подстройка частоты) применяется при небольшом расхождении; `stepping` (скачок) — при большом расхождении, определяемом `makestep`.

### Справочные часы (refclock) и драйверы

Для систем, требующих максимальной точности, chrony поддерживает аппаратные источники:

| Драйвер | Тип | Пример |
| :--- | :--- | :--- |
| **SHM** | Разделяемая память (от `gpsd`) | `refclock SHM 0 refid GPS precision 1e-1` |
| **SOCK** | Unix-сокет (PPS) | `refclock SOCK /var/run/chrony.ttyS0.sock refid PPS lock GPS` |
| **PHC** | Аппаратные часы (PTP) | `refclock PHC /dev/ptp0 poll 2 dp4` |
| **PPS** | Импульс точного времени | `refclock PPS /dev/pps0 lock GPS` |

`lock GPS` указывает chrony игнорировать источник GPS, если он несинхронизирован, и использовать только PPS.

### Аутентификация NTP

Chrony поддерживает два режима аутентификации:

| Режим | Описание |
| :--- | :--- |
| **Symmetric Key** | Предварительно общий секретный ключ (MD5, SHA1, SHA256, SHA384, SHA512). Указывается в `keyfile`, активируется через `trustedkey` и `require`. |
| **NTS (RFC 8915)** | Аутентификация через TLS 1.3 + AEAD. Требует отдельного соединения TCP/4460 для обмена ключами (NTS-KE). Подробнее в разделе практических сценариев. |

Симметричные ключи используются в изолированных сетях или для защиты от внутренних атак. NTS рекомендуется для интернет-синхронизации.

### Сравнение: Chrony vs systemd-timesyncd vs ntpd

| Характеристика | systemd-timesyncd | Chrony (v4.5+) | ntpd |
| :--- | :--- | :--- | :--- |
| Тип | SNTP-клиент | Полный NTP-клиент/сервер | Полный NTP-клиент/сервер |
| Серверный режим | Нет | Да | Да |
| Точность | Средняя (секунды) | **Сверхвысокая** (мкс/нс) | Высокая (миллисекунды) |
| Работа без сети | Нет | Да (`local stratum`) | Частично |
| Быстрая синхронизация | Нет | Да (`iburst`) | Нет |
| Коррекция дрейфа | Нет | Да (файл drift) | Да (файл drift) |
| Безопасность (NTS) | Нет | Да (v4.0+) | Нет |
| Аппаратное ускорение | Нет | **Да (HW Timestamping)** | Да |
| Zero-downtime | Нет | **Да (Socket Activation)** | Нет |
| Рекомендуемое применение | Рабочие станции, простые серверы | Все серверы, виртуальные машины, высокоточные сети | Устаревший, не рекомендуется |

> Chrony заменил `ntpd` как NTP-демон по умолчанию в RHEL 8+, Fedora, Alpine Linux.

### Установка и расположение файлов

**Установка:**

```bash
# Debian/Ubuntu
sudo apt install chrony

# RHEL/CentOS/Rocky/Alma
sudo dnf install chrony
```

**Управление службой и сокетами (Chrony 4.5+):**

```bash
sudo systemctl enable --now chrony
# Проверка активации через сокет (позволяет перезапускать демон без потери пакетов)
systemctl status chrony.socket
```

**Файлы конфигурации:**

| Дистрибутив | Путь конфига | Демон |
| :--- | :--- | :--- |
| Debian/Ubuntu | `/etc/chrony/chrony.conf` | `chrony` |
| RHEL/CentOS | `/etc/chrony.conf` | `chronyd` |

### Systemd-юниты и socket-activation

Chrony 4.5+ использует socket-activation для zero-downtime перезапусков:

- **`chronyd.service`** — основной юнит, запускается при получении запроса на сокете.
- **`chronyd.socket`** — слушает Unix-сокет `/var/run/chrony/chronyd.sock` и NTP UDP/123.
- **`chrony-wait.service`** — блокирует загрузку до завершения синхронизации. Используется для сервисов, критичных к точному времени (etcd, базы данных).

```bash
# Проверка socket-activation
systemctl status chronyd.socket
# → Active: active (listening) since ...

# Включение chrony-wait для критичных сервисов
sudo systemctl enable chrony-wait.service
```

### Ключевые директивы chrony.conf

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `pool` | DNS-имя, разрешаемое в несколько серверов | `pool pool.ntp.org iburst` |
| `server` | Конкретный NTP-сервер | `server 10.0.0.1 iburst` |
| `iburst` | Ускорение начальной синхронизации | `pool pool.ntp.org iburst` |
| `makestep` | Пошаговая коррекция при большом расхождении | `makestep 1.0 3` |
| `initstepslew` | Быстрая начальная синхронизация при старте | `initstepslew 10 pool.ntp.org` |
| `rtcsync` | Синхронизация RTC (аппаратных часов) | `rtcsync` |
| `driftfile` | Файл хранения дрейфа частоты | `driftfile /var/lib/chrony/drift` |
| `maxslewrate` | Ограничение скорости подстройки частоты | `maxslewrate 100` |
| `hwtimestamp` | Включить аппаратные метки времени на интерфейсе | `hwtimestamp eth0` |
| `extfield F324` | Использовать поле коррекции PTP (Chrony 4.5+) | `server ntp.local extfield F324` |
| `leapsecmode` | Метод обработки високосной секунды | `leapsecmode slew` |
| `smoothtime` | Плавное размытие (smearing) времени | `smoothtime 3600 0.001` |
| `allow` | Разрешить клиентам из сети | `allow 192.168.10.0/24` |
| `local stratum` | Режим автономного сервера | `local stratum 10` |
| `nts` | Включить Network Time Security | `server time.cloudflare.com nts iburst` |
| `ntsdumpdir` | Хранение сессионных данных NTS | `ntsdumpdir /var/lib/chrony` |
| `keyfile` | Файл с ключами симметричной аутентификации | `keyfile /etc/chrony/chrony.keys` |
| `trustedkey` | Список доверенных ключей | `trustedkey 1` |
| `require` | Требовать аутентификацию от сервера | `require` |

### Символы источников в `chronyc sources`

| Символ | Значение |
| :--- | :--- |
| `*` | Текущий активный источник (синхронизация) |
| `+` | Пригодный источник (может использоваться в комбинации) |
| `-` | Непригодный источник (отброшен алгоритмом) |
| `?` | Недоступный или непроверенный источник |
| `x` | Ошибочный источник (falserticker — время не совпадает с большинством) |
| `~` | Источник с слишком переменным временем отклика |

## Практические сценарии

### Настройка Chrony в качестве клиента

Базовая настройка для синхронизации с внешними серверами.

```ini
# /etc/chrony/chrony.conf

# Пул серверов (рекомендуется)
pool pool.ntp.org iburst

# Пошаговая коррекция: если расхождение > 1 сек, исправить за 3 обновления
makestep 1.0 3

# Быстрая начальная синхронизация при старте
initstepslew 10 pool.ntp.org

# Синхронизировать RTC
rtcsync

# Файл дрейфа (сохраняет расхождение частоты)
driftfile /var/lib/chrony/drift

# Логирование
logdir /var/log/chrony
log measurements statistics tracking
```

### Настройка высокоточного клиента (PTP + HW)

Для сред, где требуется точность выше миллисекунд (финансовые системы, распределённые базы данных).

```ini
# /etc/chrony/chrony.conf

# Включаем аппаратные метки времени
hwtimestamp eth0

# Использование расширенных полей коррекции (Chrony 4.5+)
# F324 учитывает задержки на коммутаторах (Transparent Clocks)
server ntp.local iburst minpoll -4 maxpoll -4 extfield F324

# Ограничение скорости подстройки частоты
maxslewrate 100

# Синхронизировать аппаратные часы
rtcsync

driftfile /var/lib/chrony/drift
makestep 1.0 3
```

### Настройка безопасной синхронизации (NTS)

Использование NTS для защиты от подмены времени.

```ini
# /etc/chrony/chrony.conf

# Серверы с поддержкой NTS
server time.cloudflare.com nts iburst
server nts.netnod.se nts iburst
server ptbtime1.ptb.de nts iburst

# Хранилище для NTS-ключей (важно для ускорения старта)
ntsdumpdir /var/lib/chrony
```

**Проверка NTS:**

```bash
chronyc ntsstats
# → NTS Statistics:
# →   NTP servers: 3
# →   Active NTS cookies: 6
# →   NTS-KE connections: 3 successful, 0 failed
```

### Настройка обработки високосных секунд (Leap Seconds)

**Вариант А: Размытие (Leap Smearing)**
Рекомендуется для баз данных, чтобы избежать прыжков времени.

```ini
# Размытие в течение 12 часов (43200 сек)
leapsecmode slew
smoothtime 43200 0.001
```

**Вариант Б: Внешний список**
Для точного определения момента наступления секунды.

```ini
leapseclist /usr/share/zoneinfo/leap-seconds.list
```

### Настройка Chrony в качестве сервера

Конфигурация для раздачи времени клиентам в локальной сети.

```ini
# /etc/chrony/chrony.conf

# Источники времени (внешние)
pool pool.ntp.org iburst

# Разрешить клиентам
allow 192.168.10.0/24
allow 192.168.31.0/24

# Аутентификация по симметричным ключам (для старых клиентов или изоляции)
keyfile /etc/chrony/chrony.keys
trustedkey 1
require

# Работать как сервер при потере интернета
local stratum 10

makestep 1.0 3
rtcsync
driftfile /var/lib/chrony/drift
```

**Пример `chrony.keys`:**
```text
1 SHA1 HEX:45A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6E7F8A9
```

> `local stratum 10` — chrony продолжит раздавать время даже в изолированной сети. Клиенты получат stratum 11.

### Безопасность и жёсткое ужесточение (Hardening)

Рекомендации по защите демона `chronyd`.

```ini
# /etc/chrony/chrony.conf

# Отключить прослушивание порта управления по сети
cmdport 0

# Ограничить доступ к управлению (только localhost)
bindcmdaddress 127.0.0.1
bindcmdaddress ::1

# Запуск от непривилегированного пользователя
user _chrony

# Отключить неиспользуемые функции
noclientlog
```

**Проверка запуска от непривилегированного пользователя:**

```bash
ps -eo user,pid,comm | grep chronyd
# → _chrony   1234 chronyd
```

### Миграция с ntpd

Пошаговая миграция с `ntpd` на `chrony` без потери синхронизации.

```bash
# 1. Остановить ntpd
sudo systemctl stop ntpd
sudo systemctl disable ntpd

# 2. Перенести конфигурацию (если нужно)
# ntpd.conf → chrony.conf (синтаксис отличается!)

# 3. Включить и запустить chrony
sudo systemctl enable --now chronyd

# 4. Проверить синхронизацию
chronyc tracking
# → Leap status: Normal

# 5. Проверить, что systemd-timesyncd не конфликтует
systemctl is-active systemd-timesyncd
# → inactive
```

### Настройка симметричной аутентификации

Конфигурация аутентификации между сервером и клиентами в изолированной сети.

```ini
# /etc/chrony/chrony.conf
keyfile /etc/chrony/chrony.keys
trustedkey 1
require

# На сервере
allow 192.168.10.0/24

# На клиенте
server 192.168.10.1 iburst key 1
```

**Генерация ключей:**

```bash
# Генерация SHA256 ключа
sudo chronyc keygen 1 SHA256
# → Key 1 generated

# Или вручную в chrony.keys
echo "1 SHA256 $(openssl rand -hex 32)" | sudo tee -a /etc/chrony/chrony.keys
sudo chmod 600 /etc/chrony/chrony.keys
```

### Настройка фаервола (nftables / iptables)

NTP использует UDP порт 123. В серверном режиме нужно разрешить входящий трафик:

```bash
# nftables
sudo nft add rule inet filter input udp dport 123 accept

# iptables
sudo iptables -A INPUT -p udp --dport 123 -j ACCEPT

# Проверка
sudo nft list ruleset | grep 123
sudo iptables -L -n | grep 123
```

### SELinux / AppArmor

**RHEL/CentOS (SELinux):**

```bash
# Проверка контекста chronyd
ls -Z /usr/sbin/chronyd
# → system_u:object_r:chronyd_exec_t:s0 /usr/sbin/chronyd

# Разрешить chronyd запись в кастомный driftfile
sudo semanage fcontext -a -t chronyd_var_lib_t "/var/lib/chrony(/.*)?"
sudo restorecon -Rv /var/lib/chrony

# Разрешить сетевой порт управления (если не отключён)
sudo semanage port -a -t chronyd_port_t -p udp 123
```

**Ubuntu/Debian (AppArmor):**

```bash
# Проверка профиля
sudo aa-status | grep chronyd
# → chronyd    (enforced)

# Добавить запись для кастомного driftfile
sudo nano /etc/apparmor.d/usr.sbin.chronyd
#   /var/lib/chrony/drift rw,
sudo systemctl reload apparmor
```

### Управление driftfile

Файл дрейфа (`/var/lib/chrony/drift`) содержит текущее расхождение частоты системных часов. При повреждении или отсутствии chrony начинает синхронизацию с нуля, что увеличивает время конвергенции.

**Ротация driftfile:**

```bash
# Проверка содержимого
cat /var/lib/chrony/drift
# → -0.123456789

# Ручное резервное копирование
sudo cp /var/lib/chrony/drift /var/lib/chrony/drift.bak

# Восстановление после повреждения
sudo systemctl stop chronyd
sudo cp /var/lib/chrony/drift.bak /var/lib/chrony/drift
sudo systemctl start chronyd
```

### Ротация логов

```bash
# /etc/logrotate.d/chrony
/var/log/chrony/*.log {
    weekly
    rotate 4
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload chronyd > /dev/null 2>/dev/null || true
    endscript
}
```

### Мониторинг и диагностика

#### Prometheus Exporter

Для мониторинга состояния синхронизации можно использовать `node_exporter` (включается флагом `--collector.ntp`) или специализированный `chrony-exporter`.

Метрики для отслеживания:
- `node_ntp_offset_seconds`: отклонение от сервера (порог: > 0.05 секунд — warning, > 0.5 секунд — critical).
- `chrony_stratum`: уровень стратума (порог: 16 — critical).
- `chrony_source_reachable`: доступность источника (1 = reachable, 0 = критично).
- `node_timex_offset_seconds`: общее отклонение часов (порог: > 0.1 сек — warning, > 1 сек — critical).

#### Утилита управления chronyc

Основные команды для диагностики.

```bash
# Источники времени и их статус
chronyc sources
# → MS Name/IP address         Stratum Poll Reach LastRx Last sample
# → ===============================================================================
# → ^* ntp1.example.com              1  6   377    45  -1.2ms[ -2.1ms] +/-  15ms

# Детальная информация о каждом источнике
chronyc sources -v

# Текущий статус синхронизации (оффсет, дрейф, стратум)
chronyc tracking
# → Reference ID    : B9D18884 (ntp1.example.com)
# → Stratum         : 2
# → System time     : 0.000000005 seconds slow of NTP time
# → Last offset     : -0.000001234 seconds
# → RMS offset      : 0.000012345 seconds
# → Leap status     : Normal

# Статистика источников (за историю)
chronyc sourcestats

# Статистика сервера (запросы от клиентов)
chronyc serverstats

# Проверить статус NTS соединений
chronyc ntsstats

# Активные клиентские соединения
chronyc clients

# Немедленная пошаговая коррекция
chronyc makestep
```

#### Ожидание синхронизации при загрузке

Используйте `chrony-wait.service` для сервисов, критичных к точному времени (например, etcd, базы данных).

```bash
sudo systemctl enable chrony-wait.service
```

Настройка параметров в `/etc/default/chrony-wait` (MAXWAIT, MAXALLOWACC).

### Работа в виртуальной среде

В виртуальных машинах рекомендуется использовать гипервизор как источник времени.

```ini
# Для KVM/QEMU (через PTP)
# refclock PHC /dev/ptp0 poll 2 dp4

# Или использование гипервизора как NTP-сервера
server hypervisor.local iburst
```

### Конфигурация для изолированной сети

Настройка сервера в среде без доступа к внешним NTP-источникам.

```ini
# /etc/chrony/chrony.conf

# Только локальный сервер (объявляет себя источником)
local stratum 5

# Разрешить клиентам
allow 10.0.0.0/8

driftfile /var/lib/chrony/drift
```

### Использование аппаратных источников (GPS/PPS)

Для систем, требующих максимальной точности.

**Необходимое ПО:**

```bash
sudo apt install chrony gpsd gpsd-clients
```

**Конфигурация:**

```ini
# /etc/chrony/chrony.conf

# GPS через разделяемую память (SHM от gpsd)
refclock SHM 0 refid GPS precision 1e-1

# PPS через сокет (ttyS0 — пример порта)
refclock SOCK /var/run/chrony.ttyS0.sock refid PPS lock GPS

# Объявить себя сервером с низким stratum
local stratum 1
```

### Ansible-автоматизация

Пример роли для настройки chrony на нескольких серверах.

```yaml
# tasks/main.yml
- name: Установить chrony
  apt:
    name: chrony
    state: present
  when: ansible_os_family == "Debian"

- name: Установить chrony (RHEL)
  dnf:
    name: chrony
    state: present
  when: ansible_os_family == "RedHat"

- name: Развернуть конфигурацию chrony
  template:
    src: chrony.conf.j2
    dest: /etc/chrony/chrony.conf
  notify: restart chrony

- name: Включить и запустить chrony
  systemd:
    name: chronyd
    enabled: yes
    state: started

# handlers/main.yml
- name: restart chrony
  systemd:
    name: chronyd
    state: restarted
```

**Шаблон `chrony.conf.j2`:**

```ini
# Конфигурация, сгенерированная Ansible
{% for server in ntp_servers %}
pool {{ server }} iburst
{% endfor %}

makestep 1.0 3
rtcsync
driftfile /var/lib/chrony/drift

{% if chrony_server_mode %}
allow {{ chrony_allow_network }}
local stratum 10
{% endif %}

{% if chrony_nts_enabled %}
ntsdumpdir /var/lib/chrony
{% endif %}
```

### Резервное копирование и восстановление

**Что备份ить:**

```bash
# Конфигурация
sudo cp /etc/chrony/chrony.conf /backup/chrony.conf

# Driftfile
sudo cp /var/lib/chrony/drift /backup/chrony.drift

# Ключи аутентификации (если используются)
sudo cp /etc/chrony/chrony.keys /backup/chrony.keys

# NTS сессионные данные
sudo cp -r /var/lib/chrony /backup/chrony_data
```

**Восстановление:**

```bash
# 1. Остановить chrony
sudo systemctl stop chronyd

# 2. Восстановить файлы
sudo cp /backup/chrony.conf /etc/chrony/chrony.conf
sudo cp /backup/chrony.drift /var/lib/chrony/drift
sudo cp /backup/chrony.keys /etc/chrony/chrony.keys

# 3. Запустить
sudo systemctl start chronyd

# 4. Проверить
chronyc tracking
```

### Аварийное восстановление

Если chrony не может синхронизироваться из-за повреждённого driftfile или неверной конфигурации:

```bash
# 1. Перезапустить с отключённым driftfile
sudo systemctl stop chronyd
sudo mv /var/lib/chrony/drift /var/lib/chrony/drift.corrupted
sudo systemctl start chronyd

# 2. Принудительная синхронизация
sudo chronyc makestep

# 3. Проверить
chronyc tracking | grep "Leap status"

# 4. Если driftfile не создался автоматически — проверить права
sudo ls -la /var/lib/chrony/drift
# → -rw-r--r-- 1 _chrony _chrony 16 ...
```

## Дополнительная информация

### Конфликт с systemd-timesyncd

При установке Chrony автоматически отключает `systemd-timesyncd`. Проверка:

```bash
systemctl is-active systemd-timesyncd  # → inactive
systemctl is-active chrony             # → active
```

Подробности управления временем через systemd: [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md).

### Ограничения и крайние случаи

#### Работа в гостевых ОС и контейнерах

Внутри виртуальной машины или контейнера (Docker, LXC без `--privileged`) Chrony запускать **нельзя** без специальных прав:
- Контейнеры используют системные часы хоста.
- Попытка смены времени в контейнере требует прав `--privileged` и влияет на весь хост.
- Настраивайте Chrony только на уровне хостовой ОС или гипервизора.

#### Отсутствие серверного режима у systemd-timesyncd

`systemd-timesyncd` не может выступать NTP-сервером для других узлов. Для раздачи времени в локальной сети используйте Chrony с директивой `allow`.

#### Ограниченная точность systemd-timesyncd

Точность `systemd-timesyncd` — секунды. Для задач, требующих миллисекундной или микросекундной точности (финансы, HPC), используйте Chrony с аппаратным timestamping.

#### Долгий простой без питания

При простое > нескольких недель системные часы могут значительно уйти. Chrony исправит это постепенно, но если нужно быстрое восстановление, используйте `chronyc makestep`.

#### UDP/123 блокировка

Фаерволы часто блокируют UDP порт 123. Убедитесь, что правило разрешает исходящий и входящий NTP:

```bash
# nftables
nft list ruleset | grep 123

# iptables
sudo iptables -L -n | grep 123
```

#### Boot ordering и time-sync.target

Некоторые дистрибутивы не включают `time-sync.target` в boot-critical цепочку. Если сервисы зависят от точного времени, проверьте:

```bash
systemd-analyze critical-chain time-sync.target
# Убедитесь, что target активируется до ваших критичных сервисов
```

### См. также

* [NTP — Network Time Protocol](../../../Networking/Protocols/ntp.md) — теория протокола, формат пакетов, алгоритм Marzullo.
* [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md) — управление временем через systemd-timesyncd и timedatectl.
* [Kerberos: основы и настройка](../../../Security/Concepts/kerberos.md) — Kerberos требует синхронизации времени между узлами (расхождение < 5 минут).
