# Синхронизация времени в systemd

## Определения

* **`systemd-timesyncd`** — встроенный в `systemd` легковесный клиент протокола SNTP (Simple Network Time Protocol), предназначенный для синхронизации системных часов с удаленными серверами времени. Работает исключительно в режиме клиента и не может выступать в роли сервера времени для других узлов сети.
* **`timedatectl`** — утилита командной строки CLI (Command Line Interface) для управления системным временем, датой, часовыми поясами и состоянием службы синхронизации.

## Основные концепции

### Иерархия источников (Stratum)

Точность времени в протоколе NTP (Network Time Protocol) определяется понятием Stratum (слой):

* **Stratum 0**: первичные эталонные часы (атомные, GPS (Global Positioning System)).
* **Stratum 1**: серверы, подключенные напрямую к Stratum 0.
* **Stratum 2**: серверы, синхронизирующиеся со Stratum 1 (публичные пулы времени).
* ... и так далее до Stratum 15. Значение 16 означает отсутствие синхронизации.

### Системные и аппаратные часы

В ОС (Операционная Система) Linux различают:

1. **Системные часы (System Clock)**: время, поддерживаемое ядром. Именно его используют все приложения.
2. **Аппаратные часы (Real Time Clock, RTC)**: часы на материнской плате, питающиеся от батарейки. Используются для сохранения времени при выключении питания.

По стандарту Linux аппаратные часы рекомендуется хранить в формате UTC (Coordinated Universal Time).

## Практические сценарии

### Просмотр текущего статуса времени

```bash
timedatectl status
# →                Local time: Сб 2026-04-04 15:30:00 MSK
# →            Universal time: Сб 2026-04-04 12:30:00 UTC
# →                  RTC time: Сб 2026-04-04 12:30:00
# →                 Time zone: Europe/Moscow (MSK, +0300)
# → System clock synchronized: yes
# →               NTP service: active
```

# → `System clock synchronized: yes` подтверждает успешную работу синхронизации

### Управление синхронизацией

```bash
# Включить автоматическую синхронизацию (запускает timesyncd)
sudo timedatectl set-ntp true

# Отключить синхронизацию
sudo timedatectl set-ntp false
```

### Настройка часового пояса

```bash
# Поиск нужного пояса в списке
timedatectl list-timezones | grep Moscow

# Установка нового часового пояса
sudo timedatectl set-timezone Europe/Moscow
# → обновление системного времени и симлинка /etc/localtime
```

### Тонкая настройка timesyncd

Конфигурационный файл: `/etc/systemd/timesyncd.conf`.

```ini
[Time]
# Основные серверы через пробел
NTP=0.pool.ntp.org 1.pool.ntp.org
# Резервные серверы
FallbackNTP=ntp.ubuntu.com
```

# → После внесения правок: sudo systemctl restart systemd-timesyncd

### Диагностика процесса синхронизации

```bash
# Детальный отчет о текущем сервере и задержках
timedatectl timesync-status
# → Server: 185.209.136.132 (0.pool.ntp.org)
# → Poll interval: 1min 4s
# → Stratum: 2

# Просмотр логов службы
journalctl -u systemd-timesyncd -e
```

## Дополнительная информация

### Совместимость с Chrony и NTPd

Если в системе установлен более мощный сервер времени (например, `chrony` или `ntpd`), служба `systemd-timesyncd` автоматически переходит в состояние ожидания или отключается, чтобы избежать конфликтов.

### См. также

* [Chrony: расширенная настройка NTP](../../Linux/Networking/Services/chrony_ntp.md)
* [Управление службами (systemctl)](./service_management.md)
* [Journald: системные логи](../../SystemAdministration/Logging/journald.md)
