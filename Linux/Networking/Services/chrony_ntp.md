# Chrony — NTP-сервер

## Определения

**Chrony** — полноценный NTP-демон для Linux, оптимизированный для работы в условиях нестабильного сетевого соединения, виртуализации и необходимости микросекундной точности. Состоит из двух компонентов: `chronyd` (фоновый демон) и `chronyc` (утилита управления).

**NTP (Network Time Protocol)** — протокол синхронизации часов компьютеров через сети. Работает по иерархической модели stratum (0–15), где stratum 0 — атомные часы/GPS, stratum 1 — серверы, подключённые напрямую к stratum 0.

**NTS (Network Time Security)** — расширение NTP (RFC 8915), обеспечивающее аутентификацию и целостность данных с использованием TLS 1.3 и AEAD, предотвращая атаки типа Man-in-the-Middle (MitM).

**PTP (Precision Time Protocol)** — протокол сверхточной синхронизации (IEEE 1588). Chrony может использовать аппаратные метки времени (Hardware Timestamping) сетевых карт для достижения наносекундной точности.

> Базовая синхронизация через `systemd-timesyncd` описана в [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md).

## Базовые концепции

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

### Ключевые директивы chrony.conf

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `pool` | DNS-имя, разрешаемое в несколько серверов | `pool pool.ntp.org iburst` |
| `server` | Конкретный NTP-сервер | `server 10.0.0.1 iburst` |
| `iburst` | Ускорение начальной синхронизации | `pool pool.ntp.org iburst` |
| `makestep` | Пошаговая коррекция при большом расхождении | `makestep 1.0 3` |
| `rtcsync` | Синхронизация RTC (аппаратных часов) | `rtcsync` |
| `driftfile` | Файл хранения дрейфа частоты | `driftfile /var/lib/chrony/drift` |
| `hwtimestamp` | Включить аппаратные метки времени на интерфейсе | `hwtimestamp eth0` |
| `extfield F324` | Использовать поле коррекции PTP (Chrony 4.5+) | `server ntp.local extfield F324` |
| `leapsecmode` | Метод обработки високосной секунды | `leapsecmode slew` |
| `smoothtime` | Плавное размытие (smearing) времени | `smoothtime 3600 0.001` |
| `allow` | Разрешить клиентам из сети | `allow 192.168.10.0/24` |
| `local stratum` | Режим автономного сервера | `local stratum 10` |
| `nts` | Включить Network Time Security | `server time.cloudflare.com nts iburst` |
| `ntsdumpdir` | Хранение сессионных данных NTS | `ntsdumpdir /var/lib/chrony` |

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

# Синхронизировать RTC
rtcsync

# Файл дрейфа (сохраняет расхождение частоты)
driftfile /var/lib/chrony/drift

# Логирование
logdir /var/log/chrony
log measurements statistics tracking
```

### Настройка высокоточного клиента (PTP + HW)

Для сред, где требуется точность выше миллисекунд (финансовые системы, распределенные БД).

```ini
# /etc/chrony/chrony.conf

# Включаем аппаратные метки времени
hwtimestamp *

# Использование расширенных полей коррекции (Chrony 4.5+)
# F324 учитывает задержки на коммутаторах (Transparent Clocks)
server ntp.local iburst minpoll -4 maxpoll -4 extfield F324

# Ограничение скорости подстройки частоты
maxslewrate 100
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

### Настройка в облачных средах (Cloud)

Облачные провайдеры предоставляют локальные высокоточные источники времени.

```ini
# AWS (Link-local IP)
server 169.254.169.123 iburst prefer

# Google Cloud (GCP)
server metadata.google.internal iburst prefer

# Azure
server time.windows.com iburst
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

### Безопасность и ужесточение (Hardening)

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

### Мониторинг и диагностика

#### Prometheus Exporter

Для мониторинга состояния синхронизации можно использовать `node_exporter` (включается флагом `--collector.ntp`) или специализированный `chrony-exporter`.

Метрики для отслеживания:
- `node_ntp_offset_seconds`: отклонение от сервера.
- `chrony_stratum`: уровень стратума.
- `chrony_source_reachable`: доступность источника.

#### Ожидание синхронизации при загрузке

Используйте `chrony-wait.service` для сервисов, критичных к точному времени (например, etcd, базы данных).

```bash
sudo systemctl enable chrony-wait.service
```
Настройка параметров в `/etc/default/chrony-wait` (MAXWAIT, MAXALLOWACC).

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

# Статистика источников (за историю)
chronyc sourcestats

# Статистика сервера (запросы от клиентов)
chronyc serverstats

# Проверить статус NTS соединений
chronyc ntsstats

# Немедленная пошаговая коррекция
chronyc makestep
```

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

## Дополнительная информация

### Конфликт с systemd-timesyncd

При установке Chrony автоматически отключает `systemd-timesyncd`. Проверка:

```bash
systemctl is-active systemd-timesyncd  # → inactive
systemctl is-active chrony             # → active
```

Подробности управления временем через systemd: [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md).

### Работа в контейнерах (Docker/K8s)

**Важно:** Внутри контейнера Chrony запускать **нельзя**.
- Контейнеры используют системные часы хоста.
- Попытка смены времени в контейнере требует прав `--privileged` и влияет на весь хост.
- Настраивайте Chrony только на уровне хост-системы.

### Поддержка IPv6

```ini
# /etc/chrony/chrony.conf

# Серверы IPv6
server 2001:db8::1 iburst

# Разрешить IPv6-клиентам
allow fc00::/64

# Слушать все интерфейсы (IPv4 и IPv6)
bindaddress ::
```

### См. также

* [IPv6: настройка сервисов](../Settings/ipv6_configuration/services_configuration.md)
* [Samba: решение проблем](./samba/samba_troubleshooting.md)
* [Kerberos: основы и настройка](../../../Security/Concepts/kerberos.md)
* [Механизмы безопасности Linux](../../Security/Linux_Security_Mechanisms_Overview.md)
