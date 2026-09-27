# Graceful Reload и Binary Upgrade в Angie

## Определения

**Graceful reload** — перезагрузка конфигурации без разрыва обработки запросов: старые worker-процессы дообслуживают активные соединения и завершаются, новые стартуют с новой конфигурацией.

**Graceful shutdown** — корректная остановка: worker не закрывает соединение, пока не завершит обслуживание клиента; управляется временем `worker_shutdown_timeout`.

**Binary upgrade** — замена исполняемого файла Angie на лету, без остановки сервиса и без потери соединений: запускается новый мастер-процесс с новым бинарником, старый передаёт ему слушающие сокеты.

**`.oldbin`** — файл с PID старого мастера при бинарном обновлении (`/run/angie.pid.oldbin`).

## Теоретический блок

### Какие сигналы понимает Angie

| Сигнал | Действие |
|:---|:---|
| `TERM`, `INT` | Быстрое завершение (fast shutdown) |
| `QUIT` | Graceful shutdown |
| `HUP` | Перезагрузка конфигурации (reload) |
| `USR1` | Переоткрытие лог-файлов (ротация) |
| `USR2` | Upgrade исполняемого файла (binary upgrade) |
| `WINCH` | Graceful shutdown воркеров (используется при обновлении; с `debug_points` — аварийное завершение для дебага) |

### Как работает reload (HUP)

1. Мастер проверяет синтаксис новой конфигурации и пытается применить её (открывает логи, listen-сокеты).
2. Если применить не удаётся — **откат**: мастер продолжает работать со старой конфигурацией (нит: `angie -t` лучше выполнять до HUP).
3. При успехе мастер запускает новых воркеров, а старым шлёт команду graceful shutdown.
4. Старые воркеры закрывают listen-сокеты, но дообслуживают текущие соединения и завершаются сами.
5. Номер поколения конфигурации (generation) увеличивается и виден в `ps aux` (например, `angie: worker process #2`) и в Status API.

### Два этапа обслуживания соединений при перезагрузке

*   **Listen-сокеты:** новые воркеры сразу принимают новые соединения.
*   **Ранensы соединения:** старые воркеры продолжают обслуживать; если соединение "зависает" дольше `worker_shutdown_timeout`, Angie принудительно завершает его обслуживание.

## Практический блок

### Сценарий 1: Корректный reload вручную

```bash
# Проверка синтаксиса перед reload
sudo angie -t
# → syntax is ok / test is successful

# Reload конфигурации
sudo kill -HUP $(cat /run/angie.pid)
# либо: sudo systemctl reload angie  (то же самое)

# Проверка, что смена поколения прошла
ps aux | grep "angie: worker process"
# → angie: worker process #3   (новый номер поколения)
```

### Сценарий 2: Reload с системой управления (systemd)

```bash
# Применение изменений конфигурации штатным способом
sudo systemctl reload angie
# → reload выполнен без остановки сервиса

# Если конфиг сломан — service не упадёт: reload вернёт ошибку, сервис продолжит
sudo systemctl reload angie
# → Job for angie.service failed (статический отказ), сервис жив
```

### Сценарий 3: Binary upgrade без простоя

Процедура "на лету" (замена бинарника):

```bash
# 1. Замените исполняемый файл (например, dpkg/rpm-установка новой версии)
# 2. Проверьте новый бинарник
sudo angie -t
# → syntax is ok

# 3. Запустите новый мастер (USR2): старый переименует pid-файл в .oldbin и стартует новый
sudo kill -USR2 $(cat /run/angie.pid)
sleep 1
sudo cat /run/angie.pid.oldbin   # pid старого мастера
sudo cat /run/angie.pid          # pid нового мастера

# 4. Переведите старый мастер в состояние graceful (WINCH): новые воркеры уже с новым бинарником
sudo kill -WINCH $(cat /run/angie.pid.oldbin)

# 5. Убедиться в работе: проверка версии работающих процессов
sudo angie -v            # новая версия
curl -s https://example.com/ -o /dev/null -w "%{http_code}\n"
# → 200

# 6. При успехе — завершить старый мастер (QUIT)
sudo kill -QUIT $(cat /run/angie.pid.oldbin)

# --- Откат при проблеме ---
# Если новое не завелось: HUP старому мастеру поднимает его воркеры
sudo kill -HUP $(cat /run/angie.pid.oldbin)
sudo kill -TERM $(cat /run/angie.pid)   # погасить новый мастер
# → старый мастер снова обслуживает трафик на старой версии
```

При бинарном обновлении Angie дополнительно **флешит** некоторые shared memory зоны (сейчас — `keys_zone` в `proxy_cache_path`) на диск, чтобы новый мастер восстановил индекс кэша и не "холодить" кэш после upgrade.

### Полезные проверки после reload/upgrade

```bash
# Открытые соединения не рвутся: count of established
ss -tan | grep -c ESTAB

# Поколение конфигурации через Status API (./angie_monitoring/angie_monitoring_api.md)
curl -s http://127.0.0.1:8888/api/status/angie/ | jq .generation
```

### Решение проблем (Troubleshooting)

| Симптом | Причина | Решение |
|:---|:---|:---|
| Reload не применяется | Ошибка в конфиге | `angie -t` до HUP; исправить и повторить |
| Старые воркеры не умирают | Долгие соединения (WebSocket, streaming) | Увеличить `worker_shutdown_timeout` |
| `USR2` ничего не делает | PID файл необходим для чтения `.oldbin` | Использовать один pid-файл, не править вручную |
| После upgrade работает старая версия | Старый мастер не получил QUIT/WINCH | Проверить `ps aux \| grep master`, `kill -WINCH`/`-QUIT` старому |
| Соединения рвутся при reload | Неверная `worker_shutdown_timeout` = 0 | Выставить `worker_shutdown_timeout 10s;` и проверить |

## Дополнительная информация

*   Graceful reload/upgrade потеряет соединения, если воркер не успевает завершиться в `worker_shutdown_timeout`; для WebSocket/gRPC-стримов значение увеличивают.
*   При использовании Keepalived/HA отключение мастера может переключить VIP: выполняйте reload/upgrade на каждом узле последовательно, в off-peak.
*   Схожую (но самостоятельную) тему graceful shutdown при завершении соединений смотрите в [Управлении соединениями (HTTP)](../../Networking/Protocols/HTTP/http_connection_management.md).

## См. также

*   **[Сигналы в Linux (SIGHUP/USR2)](../../Linux/Core/processes/signals.md)** — базовый механизм сигналов для демонов.
*   **[Управление HTTP-соединениями](../../Networking/Protocols/HTTP/http_connection_management.md)** — таймауты соединений, keepalive, graceful shutdown.
*   **[Статус API и поколение конфигурации](./angie_monitoring/angie_monitoring_api.md)** — мониторинг версии/поколения через API.