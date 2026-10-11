# Docker логирование: Вопросы на собеседованиях

**Актуально для:** Docker Engine 29.x; ответы верифицированы по документации Docker и исходникам

## Определения

**Задачи этого файла** — краткие, точные ответы на типичные вопросы DevOps/SRE-собеседований по логированию в Docker. Каждый ответ содержит ключевой факт и, где нужно, команду для проверки. Теория и практика — в смежных файлах (ссылки в конце).

## Базовые концепции

### Лог-драйверы и конфигурация

**Q: Какой лог-драйвер используется по умолчанию в Docker?**
A: `json-file`. Записывает каждую строку stdout/stderr как JSON-объект `{"log": "...", "stream": "stdout", "time": "..."}` в `/var/lib/docker/containers/<id>/<id>-json.log`. Ротация **по умолчанию отключена** (`max-size=-1`, `max-file=1`) — без явной настройки файлы растут неограниченно.

**Q: Чем `local` драйвер отличается от `json-file`? Когда его использовать?**
A: `local` использует компактный бинарный формат (protobuf), имеет встроенную ротацию (`max-size=20m`, `max-file=5`, итого 100 МБ на контейнер) и сжатие (`compress=true` по умолчанию). Файлы не читаются внешними утилитами — только через `docker logs`/API. Рекомендуется для новых развёртываний как защита от переполнения диска; `json-file` нужен, когда агенты читают файлы напрямую (tail) или в Kubernetes (ротация на уровне kubelet).

**Q: Как настроить ротацию логов?**
A: Глобально (`/etc/docker/daemon.json`) или per-container:
```json
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5", "compress": "true" } }
```
Все значения `log-opts` — строки. Изменения применяются только к **новым** контейнерам (нужен `--force-recreate`).

**Q: Можно ли сменить лог-драйвер у запущенного контейнера?**
A: Нет. Драйвер и `log-opts` фиксируются при создании контейнера — требуется пересоздание.

**Q: Что такое Dual Logging?**
A: Механизм Docker 20.10+ (в Enterprise — с 18.03.1-ee): при использовании сетевого драйвера (gelf, fluentd, splunk, loki, syslog) Engine параллельно пишет логи в локальный кэш (драйвер `local`), поэтому `docker logs` продолжает работать. Кэш по умолчанию: 5 файлов × 20 МБ, настраивается опциями `cache-max-size`, `cache-max-file`, `cache-compress`, `cache-disabled`. Для драйверов, читающих логи нативно (`json-file`, `local`, `journald`), dual logging не используется.

**Q: Что такое blocking и non-blocking режимы доставки?**
A: Blocking (по умолчанию): Docker ждёт подтверждения от приёмника; при недоступности хранилища контейнер может «замерзнуть» на записи в лог. Non-blocking (`mode=non-blocking`): логи пишутся в кольцевой буфер в RAM (`max-buffer-size`, **по умолчанию 1 МБ**); при переполнении старые записи отбрасываются (FIFO) — приложение стабильно, но часть логов теряется. Потребление RAM: `max-buffer-size` × число контейнеров с сетевым драйвером.

### Чтение логов

**Q: Какие флаги у `docker logs`?**
A: `--details` (метаданные: labels/env из `--log-opt`), `-f/--follow`, `--since` (RFC3339, UNIX-timestamp или Go-duration, например `42m`), `-n/--tail` (по умолчанию `all`), `-t/--timestamps` (RFC3339Nano), `--until` (API 1.35+). Форматы времени: RFC3339Nano, `2006-01-02T15:04:05`, `2006-01-02`, UNIX-секунды, Go-duration.

**Q: Есть ли у `docker logs` флаг `--previous`, как у `kubectl logs`?**
A: **Нет.** В Docker логи контейнера хранятся всё время его существования (включая остановленные) и удаляются только с `docker rm`. Поэтому «логи предыдущей инстанции» не нужны — не удаляйте контейнер до анализа (`docker ps -a`).

**Q: Логи остановленного контейнера доступны?**
A: Да, пока контейнер не удалён. `docker rm` уничтожает и лог-файл. Перед `docker compose up --force-recreate` сделайте дамп: `docker logs --timestamps <c> > backup.log`.

**Q: `docker logs` не показывает логи при сетевом драйвере. Почему?**
A: Docker < 20.10 без Dual Logging: сетевые драйверы не поддерживают локальное чтение. Решение: обновить Docker (20.10+), либо читать из хранилища, либо агентный сбор.

**Q: Чем `docker compose logs` отличается от `docker service logs`?**
A: `docker compose logs` — логи сервисов Compose-проекта (флаги `--index`, `--no-log-prefix`, `--no-color`). `docker service logs` — Swarm; работает **только** для сервисов с драйверами `json-file` или `journald`, выполняется на manager-узле; дополнительные флаги `--no-resolve`, `--no-task-ids`, `--no-trunc`, `--raw`.

**Q: Как читать логи контейнера с TTY?**
A: `docker logs` работает, но поток «сырой»: stdout и stderr не разделяются, ANSI-escape-последовательности приложения попадают в лог как есть (мешают чтению и могут быть вектором инъекции — см. log injection).

### Архитектура сбора

**Q: Агентный сбор vs лог-драйвер — что выбрать для production?**
A: Агентный (json-file/local на диске + Alloy/Vector/Fluent Bit/Filebeat): буферизация на диске (логи переживают сбой сети), полные трансформации (парсинг, маскирование, multiline), минимальная нагрузка на Docker daemon. Драйверы: простота (одна строка в `daemon.json`), но буфер только в RAM, минимальная обработка, риск фриза контейнера в blocking-режиме. Для production и compliance — агентный сбор.

**Q: Почему контейнер «зависает» при недоступности Loki/Elasticsearch?**
A: Сетевой лог-драйвер в blocking-режиме ждёт ACK от приёмника; при сбое сети запись в лог блокирует процесс. Решение: `mode=non-blocking` с адекватным `max-buffer-size` или переход на агентный сбор с disk-backed буфером.

**Q: Как собирать логи, если приложение пишет в файл, а не stdout?**
A: Три паттерна: (1) symlink файла лога на `/dev/stdout` в образе; (2) log-streaming sidecar в Compose (`tail -F` файла в stdout sidecar'а через shared volume); (3) host volume + `logrotate` на хосте. Docker API и лог-драйверы файлы внутри контейнера не читают.

**Q: Как склеиваются многострочные логи (Java stack traces)?**
A: Лог-драйверы не поддерживают multiline — каждая строка становится отдельной JSON-записью. Склейка делается агентом: `stage.multiline` (Alloy), `concat` filter (Fluentd), `multiline` (Vector), встроенный parser (Filebeat/Fluent Bit) — по regex первой строки (обычно дата).

**Q: Что такое log injection и как его предотвратить?**
A: Внедрение управляющих символов (CRLF, ANSI-escape) в лог для подделки записей (CAPEC-93, CWE-93/117). Предотвращение: санация/allowlist пользовательского ввода в приложении, structured logging (JSON-сериализация полей), санация в агенте (Vector VRL), просмотр через `cat -v`, контроль доступа к лог-файлам.

### Диагностика и эксплуатация

**Q: Диск заполнен логами контейнеров. Действия?**
A: 1) Найти виновников: `du -hs /var/lib/docker/containers/*/*-json.log | sort -rh | head`. 2) Экстренно: `truncate -s 0 /var/lib/docker/containers/*/*-json.log` (логи контейнера обнулятся). 3) Настроить ротацию (`max-size`/`max-file`) и пересоздать контейнеры. 4) Мониторинг: алерт на заполнение раздела >85%.

**Q: `docker logs -f` «зависает» при ротации. Почему?**
A: Исторический баг moby#39235 (исправлен PR #39969, 2019): при `max-file=1` писатель закрывает файл и открывает с `O_TRUNC`, а consumer inotify ждёт событий `write`/`rename`/`remove`. На старых версиях — `max-file >= 2` или драйвер `local`; на актуальных — обновление.

**Q: Контейнер упал с OOM. Как проверить и где логи?**
A: `docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}' <c>` → `true 137` (SIGKILL). Логи: `docker logs <c>` (работает для остановленного контейнера). Причина: превышен memory-limit; диагностика — `docker stats`, `docker events --filter event=oom`.

**Q: Почему важна синхронизация времени (NTP) для логов?**
A: Метки `time` в записях ставятся демоном по часам хоста; `--since`/`--until` с относительными длительностями считаются по часам **клиента**. Рассинхрон ломает корреляцию событий между узлами и выборку по времени (в Loki — `Entry timestamp too old` при записи старше `reject_old_samples_max_age`, default 7 суток; `too far behind` — старше `max_chunk_age/2`, default ~1ч). Настройка: chrony/systemd-timesyncd на всех узлах.

**Q: Как оценить объём логов для планирования?**
A: `Объём/день ≈ контейнеры × строк/сек × средний размер строки × 86400`. Пример: 50 контейнеров × 10 строк/с × 200 Б × 86400 ≈ 8,6 ГБ/день (до сжатия). Буфер non-blocking: `max-buffer-size` × контейнеров. Диск: объём/день × retention / коэффициент сжатия (~10% для текста при `compress=true`).

**Q: Как мониторить здоровье системы логирования?**
A: Метрики: заполнение диска (`df -h /var/lib/docker`), размер лог-файлов (`du`), ошибки доставки (логи агента/демона: `journalctl -u docker`), `docker events --filter event=die --filter event=oom`. Для агентов — их эндпоинты метрик (Alloy `:12345`, Vector `:9598`).

**Q: Где логи самого Docker daemon?**
A: На systemd: `journalctl -u docker` (или `journalctl -u docker.service -f`). На syslog-системах без systemd: `/var/log/docker.log`. Уровень детализации: `log-level` в `daemon.json` (`debug` для диагностики), запуск `dockerd --debug`.

**Q: Что нужно знать про PID 1 в контейнере применительно к логам?**
A: Docker отправляет `SIGTERM` только PID 1; если PID 1 — shell или приложение без обработки сигналов, graceful shutdown не работает (через 10с — `SIGKILL`, exit 143/137), и буферы логов могут не сброситься. Решения: Exec Form в Dockerfile (`CMD ["app"]`), `tini`/`--init`, s6-overlay для multi-process. Приложение должно писать логи в stdout/stderr **без буферизации** (для Python — `PYTHONUNBUFFERED=1`), иначе логи «задерживаются» в буфере приложения.

**Q: Какие есть подводные камни при масштабировании логирования?**
A: (1) Высокая кардинальность меток (unique label на контейнер) — взрыв числа серий в Loki/ES; используйте стабильные service-level теги. (2) Сетевые драйверы на >200 контейнеров/хост нагружают dockerd — переходите на агентный сбор. (3) Non-blocking буфер в RAM: при массовом истечении/сбое сети логи теряются молча. (4) Позиционные файлы агентов (checkpoints) должны жить на персистентном volume, иначе — массовые дубликаты после пересоздания.

## Дополнительная информация

### Ссылки на смежные темы

* **[Обзор системы логирования](./docker_logging_drivers_overview.md)** — драйверы, Dual Logging, режимы доставки.
* **[Команда docker logs: справочник](./docker_logs_cli.md)** — флаги, форматы времени, API.
* **[Управление ротацией логов](./docker_log_rotation.md)** — `max-size`/`max-file`, `truncate`.
* **[Агентный сбор логов](./docker_agent_based_logging.md)** — Alloy, Vector, Fluent Bit, Filebeat.
* **[Файловые логи приложений](./docker_file_based_logging.md)** — symlink/sidecar/volume паттерны.
* **[Log Injection и безопасность логов](./docker_log_injection_security.md)** — CAPEC-93, CRLF/ANSI.
* **[Multi-Process паттерн](./docker_multi_process_logging.md)** — PID 1, сигналы, tini, s6-overlay.
* **[Настройка лог-драйвера Loki](./loki_logging_driver_setup.md)** — pipeline stages, relabeling.
* **[Docker daemon.json — полный референс](../docker_daemon_config.md)** — глобальная конфигурация.
* **[Chrony — NTP](../../Linux/Networking/Services/chrony_ntp.md)** — синхронизация времени.
