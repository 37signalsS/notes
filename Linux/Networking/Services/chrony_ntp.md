# Chrony NTP Server

## Определения

**Chrony** — полноценный NTP-демон для Linux. Состоит из двух компонентов: `chronyd` (фоновый демон) и `chronyc` (утилита управления). Предпочтительный выбор для серверов, требующих высокой точности времени и стабильной работы в нестабильных сетях.

**NTP (Network Time Protocol)** — протокол синхронизации часов компьютеров через сети. Работает по иерархической модели stratum (0–15), где stratum 0 — атомные часы/GPS, stratum 1 — серверы, подключённые напрямую к stratum 0.

> Базовая синхронизация через `systemd-timesyncd` описана в [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md).

## Базовые концепции

### Chrony vs systemd-timesyncd vs ntpd

| Характеристика | systemd-timesyncd | Chrony | ntpd |
| :--- | :--- | :--- | :--- |
| Тип | SNTP-клиент | Полный NTP-клиент/сервер | Полный NTP-клиент/сервер |
| Серверный режим | Нет | Да | Да |
| Точность | Средняя (секунды) | Высокая (миллисекунды) | Высокая (миллисекунды) |
| Работа без сети | Нет | Да (`local stratum`) | Частично |
| Быстрая синхронизация | Нет | Да (`iburst`) | Нет |
| Коррекция дрейфа | Нет | Да (файл drift) | Да (файл drift) |
| Рекомендуемое применение | Рабочие станции, простые серверы | Все серверы, виртуальные машины, изолированные сети | Устаревший, не рекомендуется |

> Chrony заменил `ntpd` как NTP-демон по умолчанию в RHEL 8+, Fedora, Alpine Linux.

### Установка и расположение файлов

**Установка:**

```bash
# Debian/Ubuntu
sudo apt install chrony

# RHEL/CentOS/Rocky/Alma
sudo dnf install chrony
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
| `iburst` | Ускорение начальной синхронизации (несколько запросов вместо одного) | `pool pool.ntp.org iburst` |
| `makestep` | Пошаговая коррекция при большом расхождении | `makestep 1.0 3` |
| `rtcsync` | Синхронизация RTC (аппаратных часов) | `rtcsync` |
| `driftfile` | Файл хранения дрейфа частоты | `driftfile /var/lib/chrony/drift` |
| `logdir` | Каталог логов | `logdir /var/log/chrony` |
| `allow` | Разрешить клиентам из сети | `allow 192.168.10.0/24` |
| `local stratum` | Объявить себя сервером при потере связи с upstream | `local stratum 10` |
| `bindaddress` | Привязка к конкретному интерфейсу | `bindaddress 10.0.0.1` |
| `cmdallow` | Разрешить команды chronyc | `cmdallow 127.0.0.1` |

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

### Chrony в качестве клиента (базовая настройка)

```ini
# /etc/chrony/chrony.conf

# Пул серверов (рекомендуется)
pool pool.ntp.org iburst

# Или конкретные серверы
# server 0.pool.ntp.org iburst
# server 1.pool.ntp.org iburst

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

```bash
sudo systemctl enable --now chrony
```

### Chrony в качестве NTP-сервера для локальной сети

```ini
# /etc/chrony/chrony.conf

# Источники времени
pool pool.ntp.org iburst

# Разрешить клиентам
allow 192.168.10.0/24
allow 192.168.31.0/24

# Работать как сервер при потере интернета
local stratum 10

makestep 1.0 3
rtcsync
driftfile /var/lib/chrony/drift
```

> `local stratum 10` — chrony продолжит раздавать время даже в изолированной сети. Клиенты получат stratum 10, что ниже приоритет, чем у внешних серверов.

### Chrony в виртуальной машине (гипервизор как источник)

Для VM рекомендуется использовать гипервизор как локальный источник времени:

```ini
# Для KVM/QEMU
chronyc addserver hypervisor.local iburst

# Для VMware
# VMware Tools синхронизируют время автоматически
```

Если сеть нестабильна, увеличьте порог коррекции:

```ini
# Разрешить резкие скачки при загрузке
makestep 10.0 5
```

### Диагностика и управление (`chronyc`)

```bash
# Источники времени и их статус
chronyc sources

# Детальная информация о каждом источнике
chronyc sources -v

# Текущий статус синхронизации
chronyc tracking

# Статистика источников (за историю)
chronyc sourcestats

# Проверить, синхронизировано ли время
chronyc activity

# Ручная синхронизация (немедленно)
chronyc makestep

# Добавить сервер на лету
chronyc addserver 10.0.0.1

# Удалить сервер
chronyc delete 10.0.0.1
```

**Пример вывода `chronyc sources`:**

```
MS Name/IP address         Stratum Poll Reach LastRx Last sample
===============================================================================
^* ntp1.example.com              1  6   377    45  -1.2ms[ -2.1ms] +/-  15ms
^+ ntp2.example.com              2  6   377    38  +0.5ms[ +0.5ms] +/-  22ms
^- ntp3.example.com              2  6   377    42  +3.1ms[ +3.1ms] +/-  45ms
```

Колонки: `MS` (режим/символ), `Stratum`, `Poll` (интервал опроса), `Reach` (достижимость, 8-ричное), `LastRx` (время последнего ответа), `Last sample` (смещение).

### Изолированная сеть (без интернета)

```ini
# /etc/chrony/chrony.conf

# Только локальный сервер
local stratum 5

# Разрешить клиентам
allow 10.0.0.0/8

driftfile /var/lib/chrony/drift
```

> Все клиенты в сети получат stratum 6. Для повышения точности добавьте аппаратный источник (GPS/PPS — см. ниже).

### Настройка Chrony с аппаратным источником (GPS/PPS)

Для систем, требующих максимальной точности (финансовые транзакции, биллинг, Kerberos):

**Необходимое ПО:**

```bash
sudo apt install chrony gpsd gpsd-clients
```

**Конфигурация:**

```ini
# /etc/chrony/chrony.conf

# Закомментировать стандартные пулы
# pool pool.ntp.org iburst

# GPS через разделяемую память (SHM от gpsd)
refclock SHM 0 refid GPS precision 1e-1

# PPS через сокет (ttyS0 — пример порта)
refclock SOCK /var/run/chrony.ttyS0.sock refid PPS lock GPS

# Разрешить клиентам из локальной сети
allow 192.168.0.0/16

# Объявить себя сервером с низким stratum
local stratum 10

driftfile /var/lib/chrony/drift
```

**Проверка:**

```bash
chronyc sources -v
```

Пример вывода:

```
MS Name/IP address         Stratum Poll Reach LastRx Last sample
===============================================================================
#* GPS                           0   4   377    11   -263ns[ -379ns] +/-  104ms
#? PPS                           0   4   377    10   -501ns[ -617ns] +/- 1598ns
```

`*` у GPS означает активный источник. `PPS` с `?` может быть недоступен — это нормально для некоторых конфигураций.

**Префиксы в `chronyc sources`:**

| Префикс | Тип источника |
| :--- | :--- |
| `^` | NTP-сервер |
| `#` | Аппаратный источник (GPS, PPS, DCF77) |
| `=` | PPS-источник (альтернативное обозначение) |
| `~` | Исходный источник (режим) |

## Дополнительная информация

### Конфликт с systemd-timesyncd

При установке Chrony автоматически отключает `systemd-timesyncd`. Проверка:

```bash
systemctl is-active systemd-timesyncd  # должен быть inactive
systemctl is-active chrony             # должен быть active
```

Подробности управления временем через systemd: [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md).

### IPv6-поддержка

```ini
# /etc/chrony/chrony.conf

# Серверы IPv6
server 2001:db8::1 iburst

# Разрешить IPv6-клиентам
allow fc00::/64

# Слушать все интерфейсы
bindaddress ::
```

```bash
sudo systemctl restart chrony
ss -6 -unap | grep chrony
```

Подробнее об IPv6-настройке сервисов: [services_configuration.md](../Settings/ipv6_configuration/services_configuration.md). Troubleshooting SAMBA (зависит от NTP): [samba_troubleshooting.md](../Services/samba/samba_troubleshooting.md).
