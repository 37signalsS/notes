# Синхронизация времени в systemd

## Определения

* **`systemd-timesyncd`** — встроенный в `systemd` легковесный клиент протокола SNTP (Simple Network Time Protocol), предназначенный для синхронизации системных часов с удаленными серверами времени. Является стандартом для большинства современных Linux-дистрибутивов в роли клиента.
* **`timedatectl`** — центральный интерфейс командной строки для управления временем, датой, часовыми поясами и состоянием службы синхронизации.
* **Stratum (Слой)** — иерархический показатель удаленности от эталонного источника времени (атомных часов). Чем меньше число (например, Stratum 1), тем выше точность источника.
* **SNTP (Simple Network Time Protocol)** — упрощенная версия NTP, описанная в RFC 4330. В отличие от полноценного NTP, SNTP не выполняет сложную фильтрацию и регулирование дрейфа, но достаточна для большинства серверов и рабочих станций.
* **time-sync.target** — специальный systemd-таргет, который гарантирует, что синхронизация времени завершена до запуска сервисов, критичных к точному времени (базы данных, кластерные менеджеры).
* **RTC (Real Time Clock)** — аппаратные часы на материнской плате, питающиеся от батарейки (CMOS). Позволяют сохранять время при выключении питания.
* **System Clock (Программные часы)** — часы, поддерживаемые ядром Linux. Все системные события, приложения и утилиты (`date`, `timedatectl`) используют именно их.

## Основные концепции

### Архитектура синхронизации времени в Linux

В Linux время поддерживается на двух уровнях:

1. **Ядро (Kernel)** — отвечает за программные часы (CLOCK_REALTIME). При загрузке ядро инициализирует системные часы значением из RTC или 1970-01-01 (если RTC отсутствует или нечитаема).
2. **Userspace NTP-демон** — корректирует системные часы через системный вызов `adjtime()` или `clock_adjtime()`. Это позволяет ядру плавно подстраивать частоту (slewing) или делать скачкообразную коррекцию (stepping).

`systemd-timesyncd` работает в userspace и выполняет только **клиентские** функции: опрашивает внешние NTP-серверы, вычисляет offset и delay, и передает коррекцию ядру. Демон **не** выступает NTP-сервером для других узлов.

### Системные и аппаратные часы (RTC)

Linux оперирует двумя типами часов:
1. **System Clock (Программные часы):** Поддерживаются ядром Linux. Все системные события и приложения используют именно их.
2. **RTC (Real Time Clock):** Аппаратные часы на материнской плате, питающиеся от батарейки. Позволяют сохранять время при выключении питания.

> **Лучшая практика:** Храните время в RTC в формате **UTC**. Это избавляет от проблем с переходом на летнее/зимнее время и конфликтов часовых поясов. `timedatectl set-local-rtc 0` устанавливает этот режим.

### Системы без аппаратных часов (Raspberry Pi и др.)

На устройствах без RTC (или с севшей батарейкой) `systemd-timesyncd` использует механизм сохранения последнего известного времени на диск.
*   **`SaveIntervalSec=`** — интервал записи текущего времени в файл `/var/lib/systemd/timesync/clock`.
*   При загрузке время восстанавливается из этого файла. Это предотвращает установку времени в 1970 год, что критично для проверки валидности SSL-сертификатов при установке NTP-соединения.

### Жизненный цикл systemd-timesyncd

Демон использует **socket-activation** и **timer-based polling**:
1. **`systemd-timesyncd.service`** — основной юнит, который запускается при необходимости.
2. **`systemd-timesyncd.socket`** — активирует демон для обработки D-Bus запросов от `timedatectl`.
3. **Внутренний таймер** — опрашивает NTP-серверы с интервалом, определяемым алгоритмом с адаптивным poll interval (обычно от 32 секунд до 1024 секунд в зависимости от качества соединения).

### Взаимодействие с Networkd и DHCP

`systemd-timesyncd` тесно интегрирован с `systemd-networkd`. Если в настройках сети включено получение NTP-серверов по DHCP (`NTP=yes` в `.network` файле), демон автоматически добавит их в список используемых источников. При этом серверы из DHCP имеют меньший приоритет, чем статически указанные в `timesyncd.conf`.

### Високосные секунды (Leap Seconds)

`systemd-timesyncd` поддерживает два режима обработки високосных секунд:
* **`leapsecmode slew`** — размазывает коррекцию в течение дня (по умолчанию).
* **`leapsecmode step`** — делает скачкообразную коррекцию в момент наступления секунды.
* **`leapsecmode ignore`** — игнорирует високосную секунду (может привести к расхождению в 1 секунду).

Режим задается глобально через `/etc/systemd/timesyncd.conf` или файл `/etc/adjtime`.

### Ограничения безопасности

`systemd-timesyncd` **не поддерживает**:
* **NTS (Network Time Security)** — аутентификацию и целостность NTP-пакетов.
* **Symmetric Key Authentication** — традиционную аутентификацию NTP.
* **Серверный режим** — демон может только получать время, но не раздавать его.

Для сред, требующих защиты от атак типа Man-in-the-Middle (MitM) или подмены времени, используйте **Chrony** с поддержкой NTS. Подробнее: [Chrony — NTP-сервер](../../../Linux/Networking/Services/chrony_ntp.md).

### Сравнение: systemd-timesyncd vs Chrony vs ntpd

| Характеристика | systemd-timesyncd | Chrony (v4.5+) | ntpd |
| :--- | :--- | :--- | :--- |
| Тип | SNTP-клиент | Полный NTP-клиент/сервер | Полный NTP-клиент/сервер |
| Серверный режим | Нет | Да | Да |
| Точность | Средняя (секунды) | **Сверхвысокая** (мкс/нс) | Высокая (миллисекунды) |
| Работа без сети | Нет | Да (`local stratum`) | Частично |
| Быстрая синхронизация | Нет | Да (`iburst`) | Нет |
| Коррекция дрейфа | Нет | Да (файл drift) | Да (файл drift) |
| Безопасность (NTS) | Нет | Да (v4.0+) | Нет |
| Аппаратное ускорение | Нет | Да (HW Timestamping) | Да |
| Zero-downtime | Нет | Да (Socket Activation) | Нет |
| Рекомендуемое применение | Рабочие станции, простые серверы | Все серверы, виртуальные машины, высокоточные сети | Устаревший, не рекомендуется |

> `systemd-timesyncd` идеален для систем, где требуется только получение точного времени из интернета без дополнительных зависимостей. Chrony предпочтительнее для production-серверов, кластеров и сред с высокими требованиями к безопасности.

## Практические сценарии

### 1. Проверка текущего статуса

```bash
timedatectl status
# →                Local time: Пн 2024-06-10 15:30:00 MSK
# →            Universal time: Пн 2024-06-10 12:30:00 UTC
# →                  RTC time: Пн 2024-06-10 12:30:00
# →                 Time zone: Europe/Moscow (MSK, +0300)
# → System clock synchronized: yes
# →               NTP service: active
# →           RTC in local TZ: no
```

**Валидация:**
* `System clock synchronized: yes` — подтверждает, что демон успешно синхронизировался хотя бы один раз.
* `NTP service: active` — сервис запущен и работает.

### 2. Глубокая диагностика синхронизации

Команда позволяет оценить качество соединения с сервером времени.

```bash
timedatectl timesync-status
# →        Server: 162.159.200.1 (0.pool.ntp.org)
# → Poll interval: 34min 8s (интервал опроса)
# →        Leap: normal (секунда координации)
# →     Version: 4
# →     Stratum: 3
# →      Offset: -1.234ms (разница с эталоном)
# →       Delay: 45.678ms (задержка пакета)
# →      Jitter: 0.567ms (нестабильность задержки)
```

**Пояснение полей:**
* **Offset** — текущее смещение локальных часов относительно сервера. Значение < 10 ms считается хорошим для большинства задач.
* **Delay** — время прохождения пакета туда-обратно. Высокий delay (> 100 ms) указывает на проблемы с сетью.
* **Jitter** — разброс задержки. Высокий jitter (> 5 ms) означает нестабильность соединения.
* **Stratum** — уровень удаленности источника. Stratum 1 — эталонные часы, Stratum 2 — серверы, синхронизирующиеся с Stratum 1.

### 3. Проверка статуса службы и юнитов

```bash
systemctl status systemd-timesyncd
# → Active: active (running) since ...
# →    Main PID: 1234 (systemd-timesyncd)

systemctl status systemd-timesyncd.socket
# → Active: active (listening) since ...
```

Если сервис не активен, проверьте:
```bash
systemctl is-active systemd-timesyncd
# → active / inactive / failed
```

### 4. Конфигурация источников времени

Файл: `/etc/systemd/timesyncd.conf`

```ini
[Time]
# Основные серверы (разделяются пробелом)
NTP=0.pool.ntp.org 1.pool.ntp.org
# Резервные серверы
FallbackNTP=ntp.ubuntu.com time.google.com
# Порог точности (отклонение пакета)
RootDistanceMaxSec=5
# Интервал опроса (секунды)
PollIntervalMinSec=32
PollIntervalMaxSec=1024
# Интервал записи на диск (для систем без RTC)
SaveIntervalSec=60
```

**Применение изменений:**
```bash
sudo systemctl restart systemd-timesyncd
```

### 5. Валидация конфигурации

Проверьте синтаксис конфигурации без перезапуска службы:

```bash
timedatectl show-timesync
# → LinkNTPServers=...
# → NTPServers=0.pool.ntp.org 1.pool.ntp.org
# → ServerName=0.pool.ntp.org
# → ServerAddress=162.159.200.1
# → ...
```

### 6. Интеграция с systemd-networkd

В файле `.network` (например, `/etc/systemd/network/20-wired.network`):

```ini
[Network]
NTP=10.0.0.1 10.0.0.2
```

`systemd-networkd` передаст эти серверы `systemd-timesyncd`. Проверка:

```bash
networkctl status eth0
# → NTP: 10.0.0.1, 10.0.0.2

timedatectl show-timesync
# → LinkNTPServers=10.0.0.1 10.0.0.2
```

### 7. Мониторинг через journalctl

```bash
# Все сообщения демона
journalctl -u systemd-timesyncd -f

# Только сообщения об ошибках
journalctl -u systemd-timesyncd -p err

# Проверка успешной синхронизации
journalctl -u systemd-timesyncd | grep "Synchronized to"
# → Synchronized to 162.159.200.1 (0.pool.ntp.org), ...
```

### 8. Проверка time-sync.target

Убедитесь, что сервисы, критичные к времени, зависят от `time-sync.target`:

```bash
systemctl list-dependencies time-sync.target
# → systemd-timesyncd.service
# → systemd-networkd-wait-online.service (опционально)

# Проверка статуса таргета
systemctl status time-sync.target
# → Active: active (elapsed) since ...
```

### 9. Управление часовыми поясами

```bash
# Список доступных поясов
timedatectl list-timezones

# Установка часового пояса
sudo timedatectl set-timezone Europe/Moscow
```

### 10. Ручная корректировка времени (Emergency)

Если автоматическая синхронизация не работает, используйте `date` для ручной установки:

```bash
# Установка времени (формат: MMDDhhmmYYYY)
sudo date 061015302026

# Проверка
date
```

> **Внимание:** Ручная установка времени (`timedatectl set-time`) может быть опасна в production, если сервисы уже запущены. Предпочтительнее использовать `chronyc makestep` или временно отключить `systemd-timesyncd`, исправить время, и перезапустить демона.

### 11. Перенос с chrony/ntpd на systemd-timesyncd

```bash
# 1. Остановка и отключение старого демона
sudo systemctl stop chrony
sudo systemctl disable chrony

# 2. Включение systemd-timesyncd
sudo systemctl enable --now systemd-timesyncd

# 3. Проверка
timedatectl status
timedatectl timesync-status
```

### 12. Работа в изолированной сети (локальный stratum)

`systemd-timesyncd` не поддерживает режим локального сервера (`local stratum`). Для изолированных сетей используйте **Chrony**:

```ini
# /etc/chrony/chrony.conf
local stratum 10
allow 10.0.0.0/8
driftfile /var/lib/chrony/drift
```

### 13. Контейнеры и виртуальные машины

В контейнерах `systemd-timesyncd` запускать **нельзя** — контейнер не имеет прав на изменение системных часов хоста.

```bash
# На хосте (правильно)
sudo systemctl enable --now systemd-timesyncd

# В контейнере (неправильно, без --privileged)
# systemctl start systemd-timesyncd  # Ошибка: Operation not permitted
```

В Docker-контейнерах настройте синхронизацию на уровне узла (хоста). Контейнеры автоматически используют системные часы хоста.

### 14. Аудит и верификация

```bash
# Проверка, что демон синхронизировался хотя бы один раз
journalctl -u systemd-timesyncd --grep="Synchronized to"

# Проверка корректности времени после загрузки
timedatectl show -p TimeUSec -p NTPSynchronized

# Верификация unit-файлов
systemd-analyze verify systemd-timesyncd.service systemd-timesyncd.socket
```

## Диагностика

### Диагностические команды

| Команда | Контекст | Описание |
| :--- | :--- | :--- |
| `timedatectl status` | Общая | Текущее состояние времени, часового пояса и NTP |
| `timedatectl timesync-status` | Детальная | Статистика по каждому NTP-серверу |
| `timedatectl show-timesync` | Конфигурация | Активные параметры демона |
| `systemctl status systemd-timesyncd` | Служба | Статус основного юнита |
| `systemctl status systemd-timesyncd.socket` | Сокет | Статус socket-активации |
| `journalctl -u systemd-timesyncd` | Логи | Журнал работы демона |
| `systemd-analyze critical-chain time-sync.target` | Загрузка | Зависимости таргета синхронизации |
| `systemd-analyze time` | Производительность | Общее время загрузки |
| `timedatectl set-ntp true/false` | Управление | Включение/выключение NTP |

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `NTP service: inactive` | Демон не запущен | `sudo systemctl enable --now systemd-timesyncd` |
| `System clock synchronized: no` | Нет доступа к серверам или неверный конфиг | Проверьте `timedatectl timesync-status`, сетевую доступность (UDP/123) |
| `Failed to start systemd-timesyncd.service` | Конфликт с chrony/ntpd | Остановите конкурирующий демон: `sudo systemctl stop chrony` |
| **Clock Skew** (расхождение > 5 мин) | Долгий простой без синхронизации | Перезагрузите демон или используйте `chrony` для быстрой коррекции |
| `Poll interval: 0s` | Демон только запустился, еще не опросил сервер | Подождите 1-2 минуты |
| `Stratum: 16` | Источник недоступен | Проверьте DNS, firewall (UDP 123), маршрутизацию |
| Время отстает/опережает после загрузки | Проблема с RTC или часовым поясом | Проверьте `timedatectl`, убедитесь что RTC в UTC |
| `SaveIntervalSec` не работает | Нет прав на запись в `/var/lib/systemd/timesync/` | Проверьте права: `sudo chown systemd-timesync:systemd-timesync /var/lib/systemd/timesync/` |
| DHCP не передает NTP-серверы | Отключено `NTP=yes` в `.network` | Добавьте `NTP=yes` в секцию `[Network]` файла `.network` |
| Синхронизация работает, но время сдвигается после boot | Аппаратные часы (RTC) идут в local TZ | `sudo timedatectl set-local-rtc 0` |

## Best Practices

1. **Храните RTC в UTC.** Это стандарт для всех Linux-систем. Избегает проблем с переходом на летнее/зимнее время.
2. **Настраивайте резервные серверы (FallbackNTP).** Если основные пулы недоступны, демон автоматически переключится на запасные.
3. **Устанавливайте `RootDistanceMaxSec`.** Порог 5 секунд подходит для большинства задач. Для высокоточных сред уменьшите до 1-2 секунд.
4. **Используйте `systemd-networkd` для автоматического получения NTP через DHCP.** Это избавляет от ручного поддержания списка серверов в конфигурации.
5. **Мониторьте журнал `systemd-timesyncd`.** Регулярно проверяйте `journalctl -u systemd-timesyncd -p warning` на наличие ошибок.
6. **Не запускайте несколько NTP-демонов одновременно.** При установке Chrony или ntpd `systemd-timesyncd` автоматически отключается, но при откате проверьте статус.
7. **Используйте `time-sync.target` для критичных сервисов.** Если у вас база данных или кластерный менеджер, добавьте `After=time-sync.target` в их unit-файлы.
8. **Настраивайте `SaveIntervalSec` для систем без RTC.** Это предотвращает потерю времени при перезагрузке.
9. **Для production с высокими требованиями к точности используйте Chrony.** `systemd-timesyncd` подходит для стандартных задач, но не обеспечивает микросекундной точности.
10. **Регулярно проверяйте `timedatectl timesync-status`.** Offset > 100 ms или Stratum 16 требуют внимания.

## Ограничения и крайние случаи

### 1. Отсутствие серверного режима
`systemd-timesyncd` не может выступать NTP-сервером для других узлов. Если вам нужно раздавать время в локальной сети, используйте Chrony с директивой `allow`.

### 2. Отсутствие NTS и аутентификации
Демон не поддерживает Network Time Security (NTS) или традиционную аутентификацию NTP. В средах с риском MitM-атак это критичное ограничение.

### 3. Ограниченная точность
Точность `systemd-timesyncd` — секунды. Для задач, требующих миллисекундной или микросекундной точности (финансы, HPC), используйте Chrony с аппаратным timestamping.

### 4. Нет коррекции дрейфа частоты
Демон не сохраняет файл дрейфа (driftfile). При каждой перезагрузке он начиная с нуля. Для систем с нестабильной температурой или виртуальных машин это может приводить к большему initial offset.

### 5. Зависимость от systemd-networkd
DHCP NTP-серверы автоматически добавляются только при использовании `systemd-networkd`. Если используется NetworkManager или netplan с NetworkManager бэкендом, демон не получит NTP-серверы автоматически.

### 6. Конфликт с chrony/ntpd
Установка Chrony или ntpd автоматически отключает `systemd-timesyncd`, но при откате (удалении chrony) демон может остаться отключенным. Всегда проверяйте статус после изменений:

```bash
sudo systemctl enable --now systemd-timesyncd
```

### 7. Високосные секунды
По умолчанию `systemd-timesyncd` использует `leapsecmode slew`, что размазывает коррекцию в течение дня. Для баз данных, чувствительных к скачкам времени, это приемлемо. Для других систем может потребоваться `step`.

### 8. Долгий простой без питания
При простее > нескольких недель системные часы могут значительно уйти. `systemd-timesyncd` исправит это постепенно, но если нужно быстрое восстановление, используйте `chronyc makestep`.

### 9. Контейнеры
Внутри контейнера (Docker, LXC без `--privileged`) демон не может изменять системные часы. Настраивайте синхронизацию только на хосте.

### 10. Аппаратные часы с севшей батарейкой
Если RTC работает от севшей батарейки, демон будет полагаться на сохраненное время на диск (`SaveIntervalSec`). При длительном простое (> месяц) время может быть потеряно.

### 11. Boot ordering и time-sync.target
Некоторые дистрибутивы не включают `time-sync.target` в boot-critical цепочку. Если сервисы зависят от точного времени, проверьте:

```bash
systemd-analyze critical-chain time-sync.target
# Убедитесь, что target активируется до ваших критичных сервисов
```

### 12. UDP/123 блокировка
Фаерволы часто блокируют UDP порт 123. Убедитесь, что правило разрешает исходящий NTP:

```bash
# nftables
nft list ruleset | grep 123

# iptables
sudo iptables -L -n | grep 123
```

## Очистка и обслуживание

### Отключение systemd-timesyncd

```bash
sudo systemctl disable --now systemd-timesyncd
sudo systemctl mask systemd-timesyncd
```

### Включение systemd-timesyncd

```bash
sudo systemctl unmask systemd-timesyncd
sudo systemctl enable --now systemd-timesyncd
```

### Удаление конфигурации

```bash
sudo rm /etc/systemd/timesyncd.conf
sudo rm /var/lib/systemd/timesync/clock
```

### Восстановление конфигурации по умолчанию

```bash
sudo cp /usr/lib/systemd/timesyncd.conf /etc/systemd/timesyncd.conf
sudo systemctl restart systemd-timesyncd
```

### Проверка после изменений

```bash
# Проверка статуса
timedatectl status

# Проверка синхронизации
timedatectl timesync-status

# Проверка журнала
journalctl -u systemd-timesyncd -p warning --since "5 minutes ago"
```

## См. также

* [Chrony — NTP-сервер](../../../Linux/Networking/Services/chrony_ntp.md) — для production-серверов с высокими требованиями к точности.
* [Управление службами (systemctl)](./service_management.md) — базовые команды управления юнитами.
* [systemd-analyze: Анализ производительности](./performance.md) — диагностика времени загрузки и critical-chain.
* [Журналирование через journald](../../../Linux/SystemAdministration/Logging/journald.md) — анализ ошибок подключения к серверам времени.
* [systemd-networkd](../../../Linux/Networking/Settings/Persistent_Network/systemd_networkd.md) — автоматизация получения NTP через DHCP.
