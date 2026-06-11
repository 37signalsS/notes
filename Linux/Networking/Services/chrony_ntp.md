# Chrony — NTP-сервер

## Определения

**Chrony** — полноценный NTP-демон для Linux. Состоит из двух компонентов: `chronyd` (фоновый демон) и `chronyc` (утилита управления). Предпочтительный выбор для серверов, требующих высокой точности времени и стабильной работы в нестабильных сетях.

**NTP (Network Time Protocol)** — протокол синхронизации часов компьютеров через сети. Работает по иерархической модели stratum (0–15), где stratum 0 — атомные часы/GPS, stratum 1 — серверы, подключённые напрямую к stratum 0.

> Базовая синхронизация через `systemd-timesyncd` описана в [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md).

## Базовые концепции

### Сравнение: Chrony vs systemd-timesyncd vs ntpd

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

### Настройка Chrony в качестве клиента

Базовая настройка для синхронизации с внешними серверами.

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

### Настройка Chrony в качестве сервера

Конфигурация для раздачи времени клиентам в локальной сети.

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

> `local stratum 10` — chrony продолжит раздавать время даже в изолированной сети. Клиенты получат stratum 11.

### Работа в виртуальной среде

В виртуальных машинах рекомендуется использовать гипервизор как источник времени (если поддерживается) или разрешить более агрессивную коррекцию.

```ini
# Для KVM/QEMU (через PTP, если настроено)
# refclock PHC /dev/ptp0 poll 2 dp4

# Или использование гипервизора как NTP-сервера
server hypervisor.local iburst
```

Если сеть нестабильна, увеличьте порог коррекции:

```ini
# Разрешить резкие скачки при загрузке
makestep 10.0 5
```

### Утилита управления chronyc

Основные команды для диагностики и управления демоном.

```bash
# Источники времени и их статус
chronyc sources
# → MS Name/IP address         Stratum Poll Reach LastRx Last sample
# → ===============================================================================
# → ^* ntp1.example.com              1  6   377    45  -1.2ms[ -2.1ms] +/-  15ms

# Детальная информация о каждом источнике
chronyc sources -v

# Текущий статус синхронизации
chronyc tracking
# → Reference ID    : 185.209.136.132 (ntp1.example.com)
# → Stratum         : 2

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

# Разрешить клиентам из локальной сети
allow 192.168.0.0/16

# Объявить себя сервером с низким stratum
local stratum 1

driftfile /var/lib/chrony/drift
```

## Дополнительная информация

### Конфликт с systemd-timesyncd

При установке Chrony автоматически отключает `systemd-timesyncd`. Проверка:

```bash
systemctl is-active systemd-timesyncd  # → inactive
systemctl is-active chrony             # → active
```

Подробности управления временем через systemd: [time_synchronization.md](../../../Linux/Core/systemd/time_synchronization.md).

### Поддержка IPv6

Настройка прослушивания и доступа по протоколу IPv6.

```ini
# /etc/chrony/chrony.conf

# Серверы IPv6
server 2001:db8::1 iburst

# Разрешить IPv6-клиентам
allow fc00::/64

# Слушать все интерфейсы (IPv4 и IPv6)
bindaddress ::
```

```bash
sudo systemctl restart chrony
ss -6 -unap | grep chrony
# → udp  UNCONN  0  0  [::]:123  [::]:*  users:(("chronyd",pid=123,fd=5))
```

### См. также

* [IPv6: настройка сервисов](../Settings/ipv6_configuration/services_configuration.md)
* [Samba: решение проблем](./samba/samba_troubleshooting.md)
* [Kerberos: основы и настройка](../../../Security/Concepts/kerberos.md)
