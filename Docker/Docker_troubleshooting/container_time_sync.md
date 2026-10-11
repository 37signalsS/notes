# Время и часовые пояса в контейнерах (Time Sync)

**Актуально для:** Docker Engine 29.x (минимум 20.10+); private time namespace — по умолчанию с Docker 29.5.0 (ядро ≥ 5.6); Alpine (musl) и slim-образы — особенности `tzdata`

Файл — справочник по **диагностике и устранению** проблем времени. Все методы **настройки** часового пояса (`TZ`, `/etc/localtime`, рецепты Dockerfile, Compose, Ansible, Podman, мониторинг drift, CI-валидация) — в **[Управление часовыми поясами в контейнерах](../Concepts/docker_timezone_management.md)**.

## Определения

**Общие часы хоста** — контейнеры разделяют `CLOCK_REALTIME` ядра хоста: время внутри контейнера (`date`, `time.time()`, `System.currentTimeMillis()`) всегда равно времени хоста. Docker не предоставляет механизма смещения `CLOCK_REALTIME` per-container.

**Time namespace (`CLONE_NEWTIME`)** — изоляция монотонных часов (`CLOCK_MONOTONIC`, `CLOCK_BOOTTIME`), появившаяся в Linux 5.6 и поддерживаемая OCI runtime spec 1.1+. Docker 29.5.0+ создаёт private time namespace по умолчанию с нулевым смещением: `CLOCK_REALTIME` остаётся общим с хостом, монотонные часы виртуализируются per-container. Отключается feature-флагом `{"features": {"time-namespaces": false}}` в `daemon.json` (аналогично `dockerd --feature time-namespaces=false`).

**Часовой пояс отображения** — локальное время (`date`, `ls -l`, метки приложения) определяется переменной `TZ`, `/etc/localtime` и базой `tzdata` **внутри образа**. В минималистичных образах (Alpine, `*-slim`, distroless) `tzdata` часто отсутствует — контейнер показывает UTC.

**Clock skew** — рассинхронизация часов между хостами кластера. Ломает корреляцию логов, валидацию TLS-сертификатов и работу распределённых систем.

## Основные концепции

### Что контейнер наследует, а что нет

| Аспект | Источник | Можно ли изменить из контейнера |
| :--- | :--- | :--- |
| Абсолютное время (epoch, `CLOCK_REALTIME`) | Ядро хоста | Нет (нужны `CAP_SYS_TIME`, Docker не даёт по умолчанию) |
| Монотонные часы (`CLOCK_MONOTONIC`/`BOOTTIME`) | Time namespace (Docker 29.5+, смещение 0) | Нет (смещение задаётся только при создании namespace) |
| Часовой пояс | `TZ` / `/etc/localtime` + `tzdata` образа | Да (настройка образа или маунт) |
| NTP-синхронизация | Хост (chrony/systemd-timesyncd) | Нет — настраивается на хосте |

**Следствие:** «неправильное время» в контейнере — это либо проблема хоста (NTP), либо проблема образа (нет `tzdata`/`TZ`), либо проблема клиентской машины, откуда запущен `docker`. Лечится по-разному.

### Дерево диагностики

```bash
# Шаг 1. Epoch в контейнере == epoch на хосте?
docker exec my-app date +%s; date +%s
```
- **Не совпадают** → проблема хоста (NTP): Сценарий 4.
- **Совпадают** → время правильное; проверяем отображение и метки:

```bash
# Шаг 2. date в контейнере показывает UTC вместо локального пояса?
docker exec my-app date
```
- **UTC вместо ожидаемого пояса** → проблема образа (`tzdata`/`TZ`): Сценарии 1–2.

```bash
# Шаг 3. docker logs --since 10m пустой или смещённый при нормальном date?
docker logs --since 10m my-app | tail -1
```
- **Да** → часы клиентской машины рассинхронизированы с хостом: Сценарий 5.
- **Ошибки ingestion в Loki** при корректных часах на одном узле → межузловой skew: Сценарий 6.
- **Сбои TLS при заведомо живом сертификате** → skew между пиром и хостом: Сценарий 7.

### Почему логи «прыгают» по времени

- `docker logs` ставит метки по часам **хоста** (демон).
- `--since`/`--until` с относительными длительностями (`10m`) вычисляются по часам **клиентской** машины (см. **[docker logs CLI](../Docker_logs/docker_logs_cli.md)**).
- Приложение может писать свои метки (зависят от `TZ` внутри контейнера): в записях json-file это поле `log`, а метка демона (UTC) — поле `time`. Две метки в одной строке — норма, не ошибка (см. «двойные временные метки» в **[Concepts](../Concepts/docker_timezone_management.md)**).

## Практические сценарии

### Сценарий 1: Контейнер показывает UTC вместо локального времени

```bash
docker exec my-app date
# → Tue Oct  5 12:34:56 UTC 2026    ← ожидалось MSK

# 1. Часы хоста в норме?
date
# → Tue Oct  5 15:34:56 MSK 2026    ← хост в порядке

# 2. tzdata в образе?
docker exec my-app ls /usr/share/zoneinfo
# → ls: cannot access ...: No such file or directory   ← tzdata нет

# 3. /etc/localtime в образе?
docker exec my-app ls -l /etc/localtime
# → ls: cannot access ...: No such file or directory
```

**Быстрое решение** (полные рецепты — в **[Concepts](../Concepts/docker_timezone_management.md)**):

```dockerfile
# Debian/Ubuntu slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*
ENV TZ=Europe/Moscow

# Alpine
RUN apk add --no-cache tzdata
ENV TZ=Europe/Moscow
```

**Переменная `TZ` с IANA-именем (`Europe/Moscow`) работает только при наличии `tzdata`** — без базы часовых поясов glibc/musl молчаливо откатывается на UTC (см. `tzset(3)`).

### Сценарий 2: `TZ` задана, но время не изменилось

```bash
docker exec my-app printenv TZ
# → Europe/Moscow
docker exec my-app date
# → Tue Oct  5 12:34:56 UTC 2026    ← TZ проигнорирована
```

**Причины:**

1. **Нет `tzdata`** — IANA-имя не резолвится, откат на UTC (Сценарий 1).
2. **`TZ` — POSIX-строка** (`TZ=MSK-3`): работает **без** `tzdata`, но не учитывает DST и исторические изменения поясов; для постоянного пояса предпочтительнее IANA-имя.
3. **Приложение читает `/etc/localtime` напрямую**, минуя `TZ` — создайте ссылку в образе или смонтируйте файл (рецепты — в **[Concepts](../Concepts/docker_timezone_management.md)**).
4. **Приложение имеет собственную настройку пояса** и игнорирует системный `TZ`: JVM (`-Duser.timezone=Europe/Moscow`), PostgreSQL (`timezone`/`PGTZ`), PHP (`date.timezone`) — полный список в **[Concepts](../Concepts/docker_timezone_management.md)**.
5. **`TZDIR`** переопределяет каталог с базой зон — если задан неверно, `tzdata` не находится.

### Сценарий 3: Попытка изменить время внутри контейнера

```bash
docker exec my-app date -s "2026-10-05 15:00:00"
# → date: cannot set date: Operation not permitted

docker exec my-app timedatectl
# → System has not been booted with systemd ... (в контейнере нет systemd/D-Bus;
#    slim-образы часто не содержат и сам timedatectl)

docker exec my-app hwclock --show
# → hwclock: Permission denied
```

**Вывод:** время — зона ответственности хоста. `CAP_SYS_TIME` Docker не даёт (и не давайте его: с этим capability контейнер может сдвинуть часы всего хоста). Для тестирования «другого времени» — time namespace (Сценарий 8) или `libfaketime` внутри приложения.

### Сценарий 4: Рассинхрон часов между хостами

**Симптом:** логи разных узлов противоречат друг другу; `docker logs --since 10m` показывает «будущие» или пустые результаты; TLS-handshake падает без видимой причины.

```bash
# 1. Сравнение часов узлов
ssh node1 date; ssh node2 date
# → разница > 1 с

# 2. NTP-статус на каждом узле
timedatectl
# → System clock synchronized: yes
# → NTP service: active

# 3. Точность синхронизации
timedatectl timesync-status
# → Offset: -1.234ms
chronyc tracking    # для chrony: System time, Last offset
chronyc sources -v  # источники и их статус
```

**Решение:** chrony или systemd-timesyncd на **всех** узлах (см. **[Chrony — NTP](../../Linux/Networking/Services/chrony_ntp.md)** и **[Синхронизация времени в systemd](../../Linux/Core/systemd/time_synchronization.md)**). Алерт на `NTPSynchronized=no` и на `node_timex_offset_seconds` (node_exporter).

### Сценарий 5: Выборка логов по времени смещена

```bash
# Относительная длительность считается по часам КЛИЕНТА
docker logs --since 10m my-app
# → (пусто)   ← клиент отстаёт от хоста

# Абсолютная метка — без влияния часов клиента
docker logs --since 2026-10-05T10:00:00Z my-app | tail -1
# → последняя строка с актуальной меткой
```

**Причина:** `--since`/`--until` с `10m`/`1h` CLI преобразует в абсолютную метку на своей машине; при рассинхроне клиент/хост выборка смещена. Форматы и детали — в **[docker logs CLI](../Docker_logs/docker_logs_cli.md)**.

### Сценарий 6: Loki отклоняет записи (timestamp too old / too far behind / too new)

Ошибки Loki (HTTP 400 от Distributor) — три разных порога, а не «30 секунд»:

| Ошибка | Порог (default) | Смысл |
| :--- | :--- | :--- |
| `entry ... has timestamp too old` | `reject_old_samples_max_age` = **168h** (7 суток) | Метка старше порога относительно текущего времени |
| `entry ... too far behind, oldest acceptable timestamp is: ...` | `max_chunk_age/2` ≈ **1ч** | Метка старше половины `max_chunk_age` (2ч) относительно **последней записи в потоке** |
| `entry ... has timestamp too new` | `creation_grace_period` = **10 мин** | Метка в будущем дальше grace-периода |

```bash
# Диагностика: сравнить метку записи с порогом из сообщения об ошибке
# и проверить часы источника и сервера Loki
timedatectl timesync-status                 # на Docker-хосте
ssh loki-server timedatectl timesync-status
```

**Решение:** NTP на всех узлах (Сценарий 4); для отложенной доставки — поднять `reject_old_samples_max_age`; для ретро-загрузки логов — отправлять записи в хронологическом порядке (см. **[Loki driver setup](../Docker_logs/loki_logging_driver_setup.md)**).

### Сценарий 7: Сбои TLS/сертификатов из-за рассинхрона

**Симптом:** `x509: certificate has expired or is not yet valid`, `certificate verify failed` или handshake-ошибки при заведомо живом сертификате.

```bash
# 1. Часы обеих сторон (UTC)
date -u
# → 2026-10-05 12:34:56 UTC

# 2. Сроки сертификата
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null \
  | openssl x509 -noout -dates
# → notBefore=Oct  1 00:00:00 2026 GMT
# → notAfter=Jan  1 00:00:00 2027 GMT
```

**Причина:** валидация «notBefore/notAfter» выполняется по **локальным часам** пира; skew в минуты уже ломает проверку (отставание → «not yet valid», упреждение → «expired»). **Решение:** NTP (Сценарий 4).

### Сценарий 8: Docker 29.5+: таймеры и сокеты ведут себя иначе (time namespace)

**Факт:** с Docker 29.5.0 контейнеры на ядре ≥ 5.6 получают private time namespace: `CLOCK_MONOTONIC`/`CLOCK_BOOTTIME` виртуализированы per-container (смещение 0), `CLOCK_REALTIME` — общий с хостом.

```bash
# Проверка: иноды time-namespace контейнера и хоста различаются?
docker exec my-app readlink /proc/self/ns/time
# → time:[4026532891]
readlink /proc/1/ns/time
# → time:[4026531841]    ← разные значения = private namespace
```

**Симптом (регрессия 29.5.0–29.5.1):** паттерны с Docker-socket passthrough (Cloud Native Buildpacks: `pack`, Spring Boot `bootBuildImage`) фиксировались с `connection reset by peer` — смена семантики монотонных часов ломает keepalive-повторное использование единственного соединения к `/var/run/docker.sock`.

**Решение:**
- обновиться до 29.5.2+ и обновить проблемное ПО;
- или отключить feature-флаг: `{"features": {"time-namespaces": false}}` в `daemon.json` (аналогично `dockerd --feature time-namespaces=false`) — глобально для демона.

### Сценарий 9: Docker Desktop: дрейф после сна (macOS)

После пробуждения Mac время в Linux-ВМ может отставать; Docker Desktop обычно корректирует его автоматически, при сбое — перезапуск демона. Детали — в **[Concepts, раздел MacOS](../Concepts/docker_timezone_management.md)**.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `date` в контейнере = UTC | Нет `tzdata`/`/etc/localtime` в образе | `apk add tzdata` / `apt-get install tzdata` + `ENV TZ` (Сценарий 1; рецепты — в **[Concepts](../Concepts/docker_timezone_management.md)**) |
| `TZ` задана, но `date` = UTC | Нет `tzdata` для IANA-имени; приложение читает `/etc/localtime` или имеет свою настройку пояса | Сценарий 2 |
| `date -s` → `Operation not permitted` | Нет `CAP_SYS_TIME` (Docker не даёт) | Время — на хосте (Сценарий 3) |
| `timedatectl` в контейнере → «not been booted with systemd» | В контейнере нет systemd/D-Bus | Диагностика NTP — на хосте (Сценарий 4) |
| Epoch в контейнере ≠ epoch на хосте | Проблема хоста (NTP off) | `timedatectl`; chrony/systemd-timesyncd (Сценарий 4) |
| `docker logs --since 10m` пустой/смещённый | Часы клиента рассинхронизированы с хостом | NTP на клиенте; абсолютные RFC3339-метки (Сценарий 5, **[docker logs CLI](../Docker_logs/docker_logs_cli.md)**) |
| Loki: `timestamp too old` | Запись старше `reject_old_samples_max_age` (default 7 суток) | NTP на всех узлах; поднять порог (Сценарий 6, **[Loki driver](../Docker_logs/loki_logging_driver_setup.md)**) |
| Loki: `too far behind` | Запись старше `max_chunk_age/2` (default ~1ч) от последней в потоке | Хронологическая доставка; NTP (Сценарий 6) |
| Loki: `timestamp too new` | Метка в будущем дальше `creation_grace_period` (default 10 мин) | NTP на источнике (Сценарий 6) |
| TLS: `not yet valid` / `expired` при живом сертификате | Clock skew между пиром и хостом | NTP (Сценарий 7) |
| `connection reset by peer` при socket passthrough (Docker 29.5) | Private time namespace меняет семантику монотонных таймеров | 29.5.2+ / `time-namespaces: false` (Сценарий 8) |
| `setlocale: LC_ALL: cannot change locale` | Нет скомпилированных локалей (Alpine/musl) | `LANG=C.UTF-8` или `musl-locales` (см. **[alpine_glibc_compatibility.md](./alpine_glibc_compatibility.md)**) |

## Валидация

```bash
# 1. Epoch совпадает с хостом
docker exec my-app date +%s; date +%s
# → одинаковые значения (±1 с)

# 2. Локальный часовой пояс применён
docker exec my-app date
# → Tue Oct  5 15:34:56 MSK 2026

# 3. NTP активен на хосте
timedatectl show --property=NTP --property=NTPSynchronized
# → NTP=yes  NTPSynchronized=yes

# 4. Выборка логов по времени корректна
docker logs --since 10m my-app | tail -1
# → последняя строка с актуальной меткой

# 5. Сертификат валиден при текущих часах
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null \
  | openssl x509 -noout -checkend 86400
# → Certificate will not expire   (проверка оставшегося срока > 24ч)
```

## Лучшие практики

1. **Логируйте в UTC** — приложения и `docker logs` дают UTC-метки; локальный пояс — только для `date`/отображения. Это устраняет класс ошибок при переезде между регионами.
2. **`tzdata` + IANA-имя в образе, если приложению нужен локальный пояс** — `ENV TZ=Europe/Moscow` + пакет; не монтируйте `/etc/localtime` в переносимых образах.
3. **NTP на всех хостах кластера** — chrony/systemd-timesyncd; алерт на `NTPSynchronized=no` и `node_timex_offset_seconds > 1s`.
4. **Абсолютные метки в скриптах** — `--since 2026-10-05T10:00:00Z` вместо `--since 10m` при рассинхроне клиент/хост.
5. **Не пытайтесь менять время внутри контейнера** — `date -s` требует `CAP_SYS_TIME`, которого Docker не даёт; время — всегда зона ответственности хоста.
6. **Обновляйте `tzdata` при обновлении образов** — устаревшая база даёт неверные DST-переходы и исторические смещения.

## Дополнительная информация

### См. также

- **[Управление часовыми поясами в контейнерах](../Concepts/docker_timezone_management.md)** — полный справочник по настройке: все методы `TZ`, рецепты Dockerfile, Compose/Ansible/Podman, мониторинг drift, CI-валидация.
- **[docker logs CLI](../Docker_logs/docker_logs_cli.md)** — `--since`/`--until` и часы клиента.
- **[Loki driver setup](../Docker_logs/loki_logging_driver_setup.md)** — пороги ingestion (`too old`/`too far behind`/`too new`).
- **[Chrony — NTP](../../Linux/Networking/Services/chrony_ntp.md)** — синхронизация хостов.
- **[Синхронизация времени в systemd](../../Linux/Core/systemd/time_synchronization.md)** — systemd-timesyncd.
- **[Alpine: локали и часовые пояса](./alpine_glibc_compatibility.md)** — `tzdata`, `musl-locales`.
- **[Коды завершения](./docker_exit_codes.md)** — таймауты и временные метки событий.

**Глубокое изучение:**
- **[tzset(3)](https://man7.org/linux/man-pages/man3/tzset.3.html)** — приоритет `TZ`: POSIX-строка или имя зоны из `tzdata`; откат на UTC; `TZDIR`.
- **[time(7)](https://man7.org/linux/man-pages/man7/time.7.html)** — time namespaces в Linux 5.6+.
- **[Docker Engine 29 release notes](https://docs.docker.com/engine/release-notes/29/)** — private time namespace по умолчанию с 29.5.0 и feature-флаг `time-namespaces`.
