# systemd Time Synchronization

## Определения

**`systemd-timesyncd`** — легковесный SNTP-клиент, встроенный в `systemd`. Синхронизирует системные часы с NTP-серверами. Не является полноценным NTP-демоном — не поддерживает серверный режим, работает только как клиент.

**`timedatectl`** — утилита управления системным временем, датой, часовым поясом и статусом NTP-синхронизации.

> Продвинутая NTP-синхронизация (Chrony, ntpd) выходит за рамки systemd. Подробности: [chrony_ntp.md](../../../Linux/Networking/Services/chrony_ntp.md).

## Базовые концепции

### Компоненты управления временем

| Компонент | Назначение | Серверный режим |
| :--- | :--- | :--- |
| `timedatectl` | Настройка часового пояса, RTC, статуса NTP | Нет (утилита) |
| `systemd-timesyncd` | Клиент SNTP для базовой синхронизации | Нет (только клиент) |
| `hwclock` | Синхронизация с аппаратными часами (RTC) | Нет |
| `date` | Просмотр/установка системного времени | Нет |

### NTP и Stratum

| Stratum | Описание | Пример |
| :--- | :--- | :--- |
| 0 | Атомные часы, GPS, радиосигналы | Цезиевые часы |
| 1 | Синхронизируются напрямую со Stratum 0 | NTP-серверы провайдеров |
| 2 | Синхронизируются со Stratum 1 | Публичные пулы (`pool.ntp.org`) |
| 2–15 | Иерархия NTP-серверов | Корпоративные NTP-серверы |
| 16 | Несинхронизировано | — |

> Максимальный рабочий stratum — 15. Stratum 16 означает отсутствие синхронизации.

### RTC (Real Time Clock) и часовой пояс

Linux по умолчанию считает, что RTC хранит время в **UTC**. Для dual-boot с Windows (которая использует локальное время в RTC):

```bash
sudo timedatectl set-local-rtc 1
```

> **Рекомендация:** Не используйте `set-local-rtc 1` без необходимости. Хранение RTC в UTC — более надёжный вариант (избегание проблем с DST).

## Практические сценарии

### Просмотр статуса времени

```bash
timedatectl status
```

Пример вывода:

```
               Local time: Сб 2026-04-04 15:30:00 MSK
           Universal time: Сб 2026-04-04 12:30:00 UTC
                 RTC time: Сб 2026-04-04 12:30:00
                Time zone: Europe/Moscow (MSK, +0300)
System clock synchronized: yes
              NTP service: active
          RTC in local TZ: no
```

**Ключевые поля:** `System clock synchronized: yes` означает успешную NTP-синхронизацию. `NTP service: active` — timesyncd запущен.

### Включение/выключение NTP-синхронизации

```bash
# Включить (запустит systemd-timesyncd)
sudo timedatectl set-ntp true

# Выключить
sudo timedatectl set-ntp false
```

### Настройка NTP-серверов

Конфигурационный файл: `/etc/systemd/timesyncd.conf`.

```ini
[Time]
# NTP-серверы (через пробел, fallback по порядку)
NTP=0.pool.ntp.org 1.pool.ntp.org
# Fallback-серверы (используются, если основные недоступны)
FallbackNTP=2.pool.ntp.org 3.pool.ntp.org
# Максимальное расхождение времени до коррекции
RootDistanceMaxSec=5
# Интервал опроса (по умолчанию 32s–2048s)
PollIntervalMinSec=64
PollIntervalMaxSec=128
```

После изменения:

```bash
sudo systemctl restart systemd-timesyncd
```

### Установка часового пояса

```bash
# Список доступных часовых поясов
timedatectl list-timezones

# Установка
sudo timedatectl set-timezone Europe/Moscow

# Проверка
timedatectl | grep "Time zone"
```

### Диагностика timesyncd

```bash
# Статус сервиса
systemctl status systemd-timesyncd

# Логи синхронизации
journalctl -u systemd-timesyncd -e

# Подробный статус (включая текущий NTP-сервер)
timedatectl timesync-status
```

Пример `timesync-status`:

```
Server: 185.209.136.132 (0.pool.ntp.org)
Poll interval: 1min 4s (min: 32s; max 34min 8s)
Leap: 0
Stratum: 2
Reference: 58C44B70
Frequency: +12.345ms
```

### Ручная установка времени (при отключённом NTP)

```bash
# Отключить NTP
sudo timedatectl set-ntp false

# Установить время
sudo date -s "2026-04-04 15:30:00"

# Синхронизировать RTC
sudo hwclock --systohc

# Вернуть NTP (опционально)
sudo timedatectl set-ntp true
```

> Ручная установка при активном NTP будет перезаписана timesyncd при следующей синхронизации.

### Проверка и синхронизация RTC

```bash
# Просмотр времени RTC
sudo hwclock --show

# Системное → RTC
sudo hwclock --systohc

# RTC → системное
sudo hwclock --hctosys
```

## Дополнительная информация

### Конфликт с другими NTP-демонами

`systemd-timesyncd` автоматически отключается при обнаружении работающих `chronyd` или `ntpd`. Проверка:

```bash
systemctl is-active systemd-timesyncd
```

Если `inactive` — возможно, активен другой NTP-демон:

```bash
systemctl is-active chronyd
systemctl is-active ntpd
```

Для принудительного возврата к timesyncd:

```bash
sudo systemctl stop chronyd && sudo systemctl disable chronyd
sudo systemctl enable --now systemd-timesyncd
```

### Связанные файлы

Управление службами: [service_management.md](./service_management.md). Логи journald: [journald.md](../../SystemAdministration/Logging/journald.md). Обзор systemd: [overview.md](./overview.md). Таймеры и расписание: [timers.md](./timers.md). NTP на уровне сети: раздел сетевых сервисов.
