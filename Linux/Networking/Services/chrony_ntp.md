---
Надёжность: 10 (SSoT + Практический опыт 2026)
Свежесть: Актуально на июль 2026
---

# Chrony — NTP-сервер

## Определения

**Chrony** — полноценный NTP-демон для Linux. Состоит из двух компонентов: `chronyd` (фоновый демон) и `chronyc` (утилита управления). Предпочтительный выбор для серверов, требующих высокой точности времени и стабильной работы в нестабильных сетях.

**NTP (Network Time Protocol)** — протокол синхронизации часов компьютеров через сети. Работает по иерархической модели stratum (0–15), где stratum 0 — атомные часы/GPS, stratum 1 — серверы, подключённые напрямую к stratum 0.

**NTS (Network Time Security)** — расширение NTP, обеспечивающее аутентификацию и целостность данных с использованием TLS и AEAD, предотвращая атаки типа Man-in-the-Middle (MitM).

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
| Безопасность (NTS) | Нет | Да (v4.0+) | Нет |
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
| `local stratum` | Объявить себя основным источником при потере связи с вышестоящими серверами | `local stratum 10` |
| `bindaddress` | Привязка к конкретному интерфейсу | `bindaddress 10.0.0.1` |
| `cmdallow` | Разрешить команды chronyc | `cmdallow 127.0.0.1` |
| `nts` | Включить Network Time Security (требует поддержки сервером) | `server time.cloudflare.com nts iburst` |
| `cmdport` | Порт управления (0 для отключения сети) | `cmdport 0` |

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

### Настройка безопасной синхронизации (NTS)

Использование NTS для защиты от подмены времени.

```ini
# /etc/chrony/chrony.conf

# Серверы с поддержкой NTS
server time.cloudflare.com nts iburst
server nts.netnod.se nts iburst
server ptbtime1.ptb.de nts iburst

# Хранилище для NTS-ключей
ntsdumpdir /var/lib/chrony
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
# Или через виртуальный IP, если доступен (зависит от региона)
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

# Работать как сервер при потере интернета
local stratum 10

makestep 1.0 3
rtcsync
driftfile /var/lib/chrony/drift
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

# Запуск от непривилегированного пользователя (обычно по умолчанию)
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

# Проверить статус NTS соединений
chronyc ntsstats

# Немедленная пошаговая коррекция
chronyc makestep
```

### Работа в виртуальной среде

В виртуальных машинах рекомендуется использовать гипервизор как источник времени или разрешить более агрессивную коррекцию.

```ini
# Для KVM/QEMU (через PTP)
# refclock PHC /dev/ptp0 poll 2 dp4

# Или использование гипервизора как NTP-сервера
server hypervisor.local iburst
```

Если сеть нестабильна, увеличьте порог коррекции:

```ini
# Разрешить резкие скачки при загрузке
makestep 10.0 5
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
* [Механизмы безопасности Linux](../../Security/Linux_Security_Mechanisms_Overview.md)
