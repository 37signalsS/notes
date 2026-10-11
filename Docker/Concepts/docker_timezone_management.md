# Управление часовыми поясами в контейнерах

**Актуально для:** Docker 20.10+ (рекомендуется 29.x), Podman 4.0+ (рекомендуется 6.x), Cgroups v2 (Kernel 5.6+, в production 2026 года преобладают ядра 6.x)

## Определения

**UTC (Coordinated Universal Time)** — всемирное координированное время. Является промышленным стандартом для серверов, баз данных и контейнерных сред. По умолчанию почти все базовые образы (Alpine, Debian, Ubuntu) используют UTC.

**tzdata (Time Zone Database)** — база данных IANA, содержащая информацию о смещениях времени, правилах перехода на летнее/зимнее время (DST) и исторических изменениях для всех регионов мира.

**Переменная окружения `TZ`** — стандарт POSIX для указания часового пояса процессу. Значение переменной (например, `Europe/Moscow`) заставляет системные библиотеки (glibc, musl) динамически вычислять локальное время без изменения системных файлов.

## Требования и предпосылки

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **Docker Engine** | 20.10+ (рекомендуется 29.x) | Поддержка переменной `TZ` работает со всеми версиями; 29.x обеспечивает стабильную работу cgroups v2 и `--cgroupns`. |
| **Docker Compose** | v2.0+ | Compose V2 интегрирован в Docker CLI как `docker compose` (с пробелом). |
| **Kubernetes** | 1.27+ (GA для `timeZone` в CronJob) | Поле `timeZone` в CronJob стало стабильным в 1.27; в актуальных релизах 2026 года (1.31+) поведение не изменилось. |
| **Базовый образ** | — | Alpine 3.21+, Debian 13+, Ubuntu 24.04+ для актуального `tzdata`. |
| **Хостовая ОС** | Linux kernel 5.6+ (рекомендуется 6.x) | Для поддержки Time Namespace (`CLONE_NEWTIME`) в OCI-рънтайме. |

**Исходное состояние окружения:**
- Хост-машина с установленным Docker Engine и синхронизированными системными часами (см. [Синхронизация времени в systemd](../../Linux/Core/systemd/time_synchronization.md)).
- Доступ к терминалу хоста для выполнения `docker` и `docker exec` команд.
- Базовый образ содержит минимум один из механизмов определения часового пояса (переменная `TZ`, файл `/etc/localtime` или установленный пакет `tzdata`).

## Базовые концепции

### Разделение времени: Ядро против Пользовательского пространства

В контейнеризации время разделено на два уровня:
1.  **Системное время (Ядро):** Ядро Linux хранит время в формате Unix Timestamp (секунды с 01.01.1970). Это время **едино для хоста и всех контейнеров**. Контейнер не может изменить системные часы ядра (требуется `CAP_SYS_TIME`, что небезопасно).
2.  **Отображаемое время (User Space):** То, как приложение "видит" время, зависит от настроек внутри контейнера. Смена часового пояса — это не изменение времени, а изменение **правил его интерпретации** библиотеками (glibc, musl).

### Механизмы определения часового пояса

Приложения и библиотеки ищут настройки в следующем приоритете:
1.  **Переменная `TZ`:** Самый быстрый и надежный способ. Если задана, файлы конфигурации игнорируются.
2.  **Файл `/etc/localtime`:** Обычно это файл или символическая ссылка на базу данных в `/usr/share/zoneinfo/`.
3.  **Файл `/etc/timezone`:** Текстовый файл с названием пояса (используется в некоторых Debian-based дистрибутивах).

### Особенности базовых и минималистичных образов

| Образ | Библиотека | Наличие `tzdata` | Особенности |
| :--- | :--- | :--- | :--- |
| **Alpine** | `musl` | Нет | Требуется `apk add --no-cache tzdata`. |
| **Debian/Ubuntu** | `glibc` | Обычно есть | В `slim` версиях может отсутствовать. |
| **Distroless** | Зависит | Нет | Требуется копирование через Multi-stage билд. |
| **Scratch/Static** | Нет | Нет | Приложение должно самостоятельно обрабатывать TZ (например, через встроенный в Go пакет `time`). |

## Практические сценарии

### 1. Использование переменной окружения `TZ` (Рекомендуемый метод)

Это наиболее чистый способ, так как он не создает зависимостей от файловой системы хоста и корректно работает в **Rootless Docker**.

**Docker CLI:**
```bash
docker run -d --name app -e TZ=Europe/Moscow nginx
# → <container_id>
```

**Docker Compose (v2):** Поддерживается как через `environment`, так и через `profiles` для условного применения:
```yaml
services:
  app:
    image: nginx:1.30-alpine
    environment:
      - TZ=Europe/Moscow
    # Альтернатива: использовать deploy.resources для prod-окружений
    # с отдельной переменной через profiles
    profiles: ["local"]
```

**Проверка в контейнере, созданном через Compose:**
```bash
docker compose exec app date
# → Mon Aug 21 12:10:19 MSK 2026
docker compose exec app printenv TZ
# → Europe/Moscow
```

### 2. Kubernetes и Helm

В Kubernetes управление временем осуществляется через переменные окружения или специфические поля ресурсов.

**Pod Manifest:**
```yaml
spec:
  containers:
  - name: app
    env:
    - name: TZ
      value: "Europe/Moscow"
```

**CronJob (K8s 1.27+):**
С версии 1.27 появилось нативное поле `timeZone`, которое влияет на расписание запуска.
```yaml
spec:
  schedule: "0 0 * * *"
  timeZone: "Europe/Moscow" # Расписание будет учитывать DST
```

**Helm Chart Pattern:**
Рекомендуется использовать глобальную переменную для синхронизации всех компонентов стека.
```yaml
# values.yaml
global:
  timezone: "Europe/Moscow"

# templates/deployment.yaml
env:
  - name: TZ
    value: {{ .Values.global.timezone | quote }}
```

### 3. Ansible

Настройка часового пояса при деплое контейнеров через Ansible:

```yaml
- name: Run container with specific timezone
  community.docker.docker_container:
    name: my_app
    image: nginx
    env:
      TZ: "Europe/Moscow"
```

### 4. Многоэтапная сборка (Multi-stage)

Для образов без пакетного менеджера (Distroless, Scratch) необходимо подготовить базу данных в промежуточном слое.

#### Глубокий разбор для Distroless:
```dockerfile
# Stage 1: Подготовка
FROM alpine:latest AS builder
RUN apk add --no-cache tzdata

# Stage 2: Финальный образ (Go)
FROM gcr.io/distroless/static-debian12
# Копируем всю базу данных зон
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo
# Или только конкретную зону для уменьшения размера
# COPY --from=builder /usr/share/zoneinfo/Europe/Moscow /etc/localtime
ENV TZ=Europe/Moscow
COPY myapp /myapp
ENTRYPOINT ["/myapp"]
```

#### Особенности Scratch:
Для статических бинарников (Go, Rust) в образе `scratch` недостаточно просто скопировать `zoneinfo`. Приложение должно знать путь к базе. В Go это настраивается через переменную `ZONEINFO`:
```dockerfile
COPY --from=builder /usr/share/zoneinfo /zoneinfo
ENV ZONEINFO=/zoneinfo
```

### 5. Монтирование файлов часового пояса (Host Mirroring)

Метод позволяет контейнеру автоматически использовать настройки хоста. **Не рекомендуется** для распределенных систем.

```bash
docker run -d \
  -v /etc/localtime:/etc/localtime:ro \
  -v /etc/timezone:/etc/timezone:ro \
  nginx
```

**Критическая проблема симлинков:**
На многих дистрибутивах `/etc/localtime` — это симлинк. Если вы монтируете только его, а внутри контейнера нет директории `/usr/share/zoneinfo/`, симлинк окажется "битым".
*Решение:* Монтируйте целевой файл напрямую (`/usr/share/zoneinfo/Europe/Moscow:/etc/localtime:ro`) или используйте `TZ`.

### 6. Настройка через Dockerfile (жесткая привязка в образ)

Метод подходит, когда часовой пояс должен быть **неизменяемо зашит** в образ (immutable infrastructure). Подходит для образов, где переменная `TZ` недостаточна (например, приложения, которые читают `/etc/localtime` напрямую, минуя `TZ`).

**Debian/Ubuntu (glibc):**
```dockerfile
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      tzdata \
    && ln -fs /usr/share/zoneinfo/Europe/Moscow /etc/localtime \
    && echo "Europe/Moscow" > /etc/timezone \
    && dpkg-reconfigure --frontend noninteractive tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Moscow
```

**Alpine (musl):**
```dockerfile
FROM alpine:3.21

RUN apk add --no-cache tzdata \
    && cp /usr/share/zoneinfo/Europe/Moscow /etc/localtime \
    && echo "Europe/Moscow" > /etc/timezone

ENV TZ=Europe/Moscow
```

**Оптимизация:** Чтобы уменьшить размер образа, можно удалить `tzdata` после создания ссылки — данные зоны уже скопированы в `/etc/localtime`:
```dockerfile
RUN apk add --no-cache --virtual .tz-build tzdata \
    && cp /usr/share/zoneinfo/Europe/Moscow /etc/localtime \
    && echo "Europe/Moscow" > /etc/timezone \
    && apk del .tz-build
```

**Kubernetes (Rootless / OpenShift):**
В OpenShift наложенные политики SCC (Security Context Constraints) могут блокировать запись в `/etc/`. Обходной путь — использовать `TZ` через `env` (см. сценарий 2) или multi-stage сборку с копированием `zoneinfo` (см. сценарий 4).

### 7. Сброс часового пояса в работающем контейнере

Если необходимо сменить часовой пояс без пересоздания контейнера (например, во время отладки):

```bash
# Смена переменной TZ в runtime (работает только если приложение читает TZ динамически)
docker exec <id> sh -c "TZ=Europe/Moscow date"
# → Mon Aug 21 12:10:19 MSK 2026

# Для приложений, требующих /etc/localtime, монтируем изнутри через nsenter
docker cp /usr/share/zoneinfo/Europe/Moscow <id>:/tmp/localtime
# → (без вывода, успешное выполнение)
docker exec <id> sh -c "cp /tmp/localtime /etc/localtime"
# → (без вывода, успешное выполнение)
```

*Примечание:* переменная `TZ`, установленная через `docker exec`, действует только на новые процессы, запущенные в этой сессии. Перезапустите процесс или используйте `docker restart`.

### 8. Podman

В Podman часовой пояс можно задать через флаг `--tz` (начиная с версии 4.0), что эквивалентно переменной `TZ`. Это особенно удобно в rootless-режиме:

```bash
podman run -d --name app --tz Europe/Moscow nginx
# → <container_id>
```

Или через `containers.conf`:
```ini
[containers]
tz = "Europe/Moscow"
```

*Podman использует тот же механизм `TZ`/`/etc/localtime`, поэтому все описанные выше принципы применимы. Подробнее: [Изоляция в Podman](../../Podman/linux_isolation.md).*

## Специфика операционных систем

### Windows-контейнеры
В Windows используется иная логика. Контейнеры по умолчанию наследуют время хоста, но поддерживают виртуализацию часового пояса (Windows Server 2019 2105B+).

**Настройка через PowerShell:**
```powershell
# В Dockerfile
USER ContainerAdministrator
RUN powershell -Command "Set-TimeZone -Id 'Russian Standard Time'"
```
*Для минималистичных образов без PowerShell используется `tzutil /s "Russian Standard Time"`.*

### MacOS (Docker Desktop)
Контейнеры работают внутри Linux-ВМ. Синхронизация времени между macOS и ВМ происходит через гипервизор (Apple Virtualization Framework).
- **Time Drift:** При выходе Mac из режима сна время в ВМ может отставать. Docker Desktop корректирует его автоматически, но в случае сбоя помогает перезапуск демона.
- **VirtioFS:** Использование VirtioFS вместо gRPC FUSE повышает стабильность системы при интенсивных операциях с файлами, что косвенно снижает нагрузку на процессы синхронизации.

### Rootless Режим
В Rootless Docker мапинг пользователей (`User Namespace`) может создавать проблемы с правами доступа при монтировании `/etc/localtime`.
- **Рекомендация:** Всегда использовать переменную `TZ`, так как она не требует доступа к системным файлам хоста и работает полностью в пользовательском пространстве.

## Глубокая техническая детализация

### Проблема "двойных временных меток"
При анализе логов часто возникает путаница между временем, которое пишет приложение, и временем, которое добавляет Docker-демон.

**Пример (json-file driver):**
```json
{
  "log": "2026-10-27 15:00:00 [INFO] Приложение запустилось\\n",
  "stream": "stdout",
  "time": "2026-10-27T12:00:00.123456789Z"
}
```
- `"log"`: Время приложения (зависит от `TZ` внутри контейнера, здесь MSK).
- `"time"`: Время Docker (всегда UTC, генерируется демоном хоста).

**Best Practice:** Приложение должно писать логи в **UTC/ISO 8601**. Локализация должна происходить только на уровне UI (Grafana/Kibana).

### Лог-драйверы и время
| Драйвер | Обработка времени |
| :--- | :--- |
| **json-file** | Всегда пишет метаданные в UTC. Не подлежит изменению. |
| **journald** | Передает лог в системный журнал хоста. Время отображения зависит от настроек `journalctl` на хосте. |
| **fluentd / gelf** | Отправляет Unix Timestamp (секунды с эпохи). Таймзона определяется на стороне приемника. |

### OCI Runtime Spec и Time Namespace
Спецификация OCI (используемая `runc`) поддерживает **Time Namespace** (Kernel 5.6+). Это позволяет изолировать `CLOCK_MONOTONIC` и `CLOCK_BOOTTIME`.
- **CLOCK_REALTIME:** (реальное время) **не изолируется**. Оно всегда общее с хостом.
- **Offsets:** Рантайм может задавать смещения (`timeOffsets`) для таймеров, что полезно для приложений, чувствительных к времени работы системы (uptime).
- **Docker 29.5.0+:** private time namespace создаётся **по умолчанию** для контейнеров на ядрах ≥ 5.6 (с нулевыми смещениями); отключается feature-флагом `{"features": {"time-namespaces": false}}` в `daemon.json`. Диагностика и побочные эффекты (в т.ч. регрессия socket-passthrough в 29.5.0–29.5.1) — в **[container_time_sync.md](../Docker_troubleshooting/container_time_sync.md)** (Сценарий 8).

### Синхронизация времени (NTP/Chrony)
Контейнеры **никогда не должны** запускать NTP-клиенты.
- **Причина:** Синхронизация системных часов — задача ядра. У контейнера нет прав изменять время ядра (без `--privileged`).
- **Механизм:** Хост-система должна быть синхронизирована (через `chrony` или `systemd-timesyncd`). Все контейнеры автоматически получают это скорректированное время через системные вызовы ядра.

## Сравнительная таблица методов

| Метод | Изоляция | Переносимость | Сложность | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Переменная `TZ`** | Высокая | Отличная | Низкая | **Золотой стандарт** |
| **Mount `/etc/localtime`** | Низкая | Плохая | Низкая | Только для локальной отработки |
| **Dockerfile `RUN ln...`** | Высокая | Хорошая | Средняя | Для неизменяемых образов |
| **Multi-stage + `tzdata`** | Высокая | Отличная | Высокая | Для Distroless/Scratch |
| **Podman `--tz`** | Высокая | Отличная | Низкая | Для rootless-сред, аналог `TZ` |

## Специфические настройки приложений

| Технология | Настройка | Описание |
| :--- | :--- | :--- |
| **Java (JVM)** | `-Duser.timezone=Europe/Moscow` | Явное указание пояса для виртуальной машины Java. |
| **Python** | `pytz` или `zoneinfo` (3.9+) | Библиотеки используют базу `tzdata` из образа. |
| **PostgreSQL** | `timezone` в `postgresql.conf` | Можно также использовать переменную `PGTZ`. |
| **MySQL / MariaDB** | `default-time-zone` в `my.cnf` или переменная `TZ` | MySQL использует системный TZ или `tzdata`, если установлена. |
| **Node.js** | `Intl.DateTimeFormat` или переменная `TZ` | Node.js (v14+) использует ICU. При отсутствии ICU использует системный `TZ`. |
| **Go** | Переменная `ZONEINFO` или `time.LoadLocation` | Go ищет zoneinfo в пути, указанном в `ZONEINFO`, либо в `/usr/share/zoneinfo`. |
| **.NET** | `TZ` или `TimeZoneInfo` | .NET 6+ корректно читает `TZ` на Linux. Для Windows-контейнеров используйте `Set-Thread-Info`. |
| **Ruby** | `TZ` переменная | Ruby (с `tzinfo` gem) использует `TZ` и `tzdata` из образа. |
| **Cron** | Перезапуск демона | Демон `cron` считывает `TZ` только при старте. Для гибкой настройки используйте `CRON_TZ` в crontab (поддерживается в `cronie` 2.0+). |
| **PHP** | `date.timezone` в `php.ini` | Также можно задать через `ENV` в пуле FPM. |

## Проверка и верификация

Для подтверждения корректности настроек используйте следующие команды:

```bash
# 1. Проверка текущего времени и пояса (строковый формат)
docker exec <id> date
# → Mon Aug 21 12:10:19 MSK 2026

# 2. Проверка значения переменной TZ
docker exec <id> printenv TZ
# → Europe/Moscow

# 3. Детальная проверка через zdump (только для glibc, требует пакет tzdata)
docker exec <id> zdump /etc/localtime
# → /etc/localtime  Europe/Moscow  2026  DST offset 3:00:00

# 4. Проверка изнутри приложения (пример Python, требует установленный tzdata)
docker exec <id> python3 -c "import time; print(time.strftime('%Z %z'))"
# → MSK +0300

# 5. Проверка смещения относительно UTC (универсальный метод)
docker exec <id> date -u
# → Mon Aug 21 09:10:19 UTC 2026
```

**Верификация в Kubernetes:**
```bash
kubectl exec <pod-name> -- date
# → Mon Aug 21 12:10:19 MSK 2026
```

**Верификация в Podman:**
```bash
podman exec <id> date
# → Mon Aug 21 12:10:19 MSK 2026
```

## Валидация в CI/CD пайплайнах

Для SRE и DevOps-инженеров важно автоматизировать проверку настроек часового пояса при деплое. Ниже приведены проверки, которые можно интегрировать в GitLab CI, GitHub Actions или Jenkins:

```bash
#!/usr/bin/env bash
# validate-timezone.sh — базовый набор проверок для CI
set -euo pipefail

IMAGE="${1:-myapp:latest}"
CONTAINER_NAME="tz-validation-$$"

# 1. Проверка: образ должен содержать tzdata или поддерживать TZ
docker run --rm -d --name "$CONTAINER_NAME" "$IMAGE" sleep 3600
PID=$(docker inspect -f '{{.State.Pid}}' "$CONTAINER_NAME")

# 2. Проверка наличия зоны (общая)
if docker exec "$CONTAINER_NAME" test -f /usr/share/zoneinfo/Europe/Moscow 2>/dev/null; then
  echo "OK: zoneinfo доступен"
else
  echo "WARN: zoneinfo отсутствует, проверка через TZ"
fi

# 3. Проверка переменной TZ (если задана)
if docker exec "$CONTAINER_NAME" printenv TZ >/dev/null 2>&1; then
  echo "TZ=$(docker exec "$CONTAINER_NAME" printenv TZ)"
else
  echo "INFO: TZ не задана, будет использован часовой пояс по умолчанию"
fi

# 4. Проверка /etc/localtime
if docker exec "$CONTAINER_NAME" test -L /etc/localtime 2>/dev/null; then
  echo "OK: /etc/localtime является symlink"
elif docker exec "$CONTAINER_NAME" test -f /etc/localtime 2>/dev/null; then
  echo "OK: /etc/localtime существует"
else
  echo "WARN: /etc/localtime отсутствует"
fi

# 5. Проверка согласованности: TZ vs /etc/localtime
TZ_VAL=$(docker exec "$CONTAINER_NAME" printenv TZ 2>/dev/null || echo "")
LOCAL_VAL=$(docker exec "$CONTAINER_NAME" readlink /etc/localtime 2>/dev/null || echo "")
if [ -n "$TZ_VAL" ] && [ -n "$LOCAL_VAL" ]; then
  if echo "$LOCAL_VAL" | grep -q "$TZ_VAL"; then
    echo "OK: TZ и /etc/localtime согласованы"
  else
    echo "WARN: TZ ($TZ_VAL) и /etc/localtime ($LOCAL_VAL) не согласованы"
  fi
fi

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1
echo "Валидация часового пояса завершена"
```

## Лучшие практики

Сводка рекомендаций по управлению временем в контейнерах для DevOps/SRE:

**Безопасность и стабильность:**
1. **Используйте переменную `TZ`** — это золотой стандарт (golden standard). Она не зависит от файловой системы хоста, работает в rootless-режиме и не требует привилегий.
2. **Пишите логи в UTC / ISO 8601** — локализация должна происходить только на уровне UI (Grafana, Kibana, Loki). Это устраняет проблему "двойных временных меток" (см. ниже).
3. **Указывайте IANA-имена зон** (например, `Europe/Moscow`, `America/New_York`), а не смещения (`+03:00`). IANA-имена учитывают исторические изменения и DST.
4. **Не монтируйте `/etc/localtime` из хоста** в продакшене — это создает жёсткую связь с хостом и нарушает переносимость. Исключение: локальная отладка.
5. **В Multi-stage сборках копируйте только нужную зону** из `tzdata`, а не всю директорию `/usr/share/zoneinfo/`, чтобы уменьшить размер образа:
   ```dockerfile
   COPY --from=builder /usr/share/zoneinfo/Europe/Moscow /etc/localtime
   ```
6. **Синхронизируйте время на хосте** через `systemd-timesyncd` или `chrony` — контейнеры наследуют системные часы ядра.
7. **Не запускайте NTP-клиенты внутри контейнеров** — это бесполезно и опасно (требует `--privileged`).

**Для Kubernetes и оркестрации:**
8. **В Kubernetes** используйте глобальную переменную `TZ` через Helm (`global.timezone`) для согласованности всех компонентов стека.
9. **В CronJob** (K8s 1.27+) используйте поле `timeZone`, а не переменную `TZ` — `timeZone` влияет на расписание, а `TZ` — только на приложение внутри пода.
10. **Для Distroless/Scratch** убеждайтесь, что `tzdata` или `zoneinfo` включены — иначе приложения (особенно Go) не смогут разрешить часовой пояс.

**Мониторинг и валидация:**
11. **Автоматизируйте проверку в CI/CD** — используйте скрипт валидации (см. раздел «Валидация в CI/CD пайплайнах») для контроля настроек timezone при деплое.
12. **Мониторьте дрейф времени** — интеграция с Prometheus через `node_timex_offset_seconds` и кастомные проверки для контейнеров.
13. **Аудит образов** — регулярно проверяйте наличие актуального `tzdata` в базовых образах через Trivy или Grype.
14. **Ведите runbook** — документируйте процедуры расследования инцидентов, связанных с временем (см. раздел «Производственный мониторинг и инцидент-респонс»).

## Мониторинг и алертинг

### Метрики для сбора

| Метрика | Источник | Порог алерта |
| :--- | :--- | :--- |
| `node_timex_offset_seconds` | node_exporter | > 5s (критично), > 1s (предупреждение) |
| `node_timex_sync_status` | node_exporter | 0 = синхронизирован, 1 = нет |
| Дрейф времени контейнера | Кастомный скрипт | > 5s относительно хоста |
| Версия `tzdata` в образе | Trivy/Grype | < текущей версии дистрибутива |

### Пример алерта (Prometheus + Alertmanager)

```yaml
groups:
  - name: time_sync
    rules:
      - alert: HostTimeDriftHigh
        expr: node_timex_offset_seconds > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Высокий дрейф времени на {{ $labels.instance }}"
          description: "Offset {{ $value }}s превышает порог 5s"

      - alert: ContainerTimezoneMismatch
        expr: time_drift_seconds > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Расхождение времени в контейнере {{ $labels.container }}"
```

### Проверка в production

```bash
# Ежедневная проверка всех контейнеров
for c in $(docker ps --format '{{.Names}}'); do
  drift=$(docker exec "$c" date +%s 2>/dev/null || echo "0")
  host=$(date +%s)
  diff=$((host - drift))
  if [ "$diff" -gt 5 ] || [ "$diff" -lt -5 ]; then
    echo "ALERT: $c drift=${diff}s"
  fi
done
```

## Очистка и откат

Инструкции по отмене изменений, если настройки часового пояса вызвали проблемы:

```bash
# 1. Остановка и удаление контейнера с настройками TZ
docker stop <id> && docker rm <id>
# → <id>

# 2. Пересоздание контейнера без TZ (будет использовать UTC)
docker run -d --name app nginx
# → <container_id>

# 3. Проверка, что контейнер вернулся в UTC
docker exec <id> date
# → Mon Aug 21 09:10:19 UTC 2026
```

**Для Docker Compose:**
```bash
docker compose stop
docker compose up -d
# Проверка:
docker compose exec app printenv TZ
# → (пустой вывод, если переменная удалена)
```

**Для Dockerfile:** Уберите строки `ln -s`, `COPY` зоны и `ENV TZ=...` из Dockerfile, пересоберите образ.

## Устранение неполадок

### Проблема: `TZ` задана, но время не меняется

**Признак:** `docker exec <id> date` возвращает UTC, хотя `TZ=Europe/Moscow` установлена.

**Причины и решения:**

1. **`tzdata` не установлен в образе** — библиотека `glibc`/`musl` не может разрешить зону.
    ```bash
    # Проверка:
    docker exec <id> ls /usr/share/zoneinfo/Europe/Moscow
    # → ls: /usr/share/zoneinfo/Europe/Moscow: No such file or directory

    # Решение для Debian/Ubuntu:
    docker exec <id> apt-get update && apt-get install -y tzdata
    # → Reading package lists... Done / Setting up tzdata (2024a-0+deb12u1) ...

    # Решение для Alpine:
    docker exec <id> apk add --no-cache tzdata
    # → OK: Downloading tzdata-2024a-r0.apk
    ```

2. **`/etc/localtime` не обновлен** — приложение читает файл, а не переменную.
    ```bash
    # Проверка:
    docker exec <id> ls -la /etc/localtime
    # → (может быть битой симлинкой)

    # Решение:
    docker exec <id> ln -snf /usr/share/zoneinfo/Europe/Moscow /etc/localtime
    # → (без вывода, успешное выполнение)
    ```

3. **Приложение имеет собственную конфигурацию TZ** (например, JVM, PostgreSQL) и игнорирует системную переменную.
   - Добавьте `-Duser.timezone=Europe/Moscow` (Java) или `timezone = 'Europe/Moscow'` (PostgreSQL).
   - См. таблицу «Специфические настройки приложений».

### Проблема: "Битая" симлинк `/etc/localtime` при монтировании

**Признак:** `date` внутри контейнера возвращает UTC, хотя `/etc/localtime` смонтирован.

**Причина:** На хосте `/etc/localtime` — символическая ссылка на `/usr/share/zoneinfo/...`, но в контейнере этот путь отсутствует.

**Решение:** Монтируйте конечный файл напрямую:
```bash
docker run -d -v /usr/share/zoneinfo/Europe/Moscow:/etc/localtime:ro nginx
# → <container_id>
```

### Проблема: Cron не учитывает `TZ`

**Причина:** Демон `cron` считывает переменную `TZ` только при старте. Если `TZ` была изменена после запуска контейнера — перезапустите:
```bash
docker restart <id>
# → <id>
```

Для более гибкой настройки используйте `CRON_TZ` в crontab (поддерживается в `cronie`):
```crontab
CRON_TZ=Europe/Moscow
0 * * * * /usr/local/bin/backup.sh
```

### Проблема: В Windows-контейнерах `TZ` игнорируется

**Причина:** Windows использует имена часовых поясов в формате Windows (например, `Russian Standard Time`), а не IANA.

**Решение:** Используйте PowerShell или `tzutil` (см. раздел «Специфика операционных систем»).

## Производственный мониторинг и инцидент-респонс

### Мониторинг расхождений времени (Time Drift)

В production-средах критично отслеживать расхождение между временем контейнера и эталоном:

```bash
# Скрипт для мониторинга дрейфа времени в контейнерах
#!/usr/bin/env bash
# check-time-drift.sh — интеграция с Prometheus node exporter или cron
set -euo pipefail

CONTAINER="${1:-}"
if [ -z "$CONTAINER" ]; then
  echo "Usage: $0 <container_name>"
  exit 1
fi

# Получаем время хоста (UTC)
HOST_TIME=$(date -u +%s)

# Получаем время контейнера (UTC)
CONT_TIME=$(docker exec "$CONTAINER" date -u +%s 2>/dev/null || echo "0")

# Считаем drift в секундах
DRIFT=$((HOST_TIME - CONT_TIME))

# Порог предупреждения: 5 секунд
if [ "$DRIFT" -gt 5 ] || [ "$DRIFT" -lt -5 ]; then
  echo "WARNING: Time drift detected for $CONTAINER: ${DRIFT}s"
  # Здесь можно отправить алерт в Slack/Telegram/PagerDuty
else
  echo "OK: Time drift for $CONTAINER: ${DRIFT}s"
fi
```

**Интеграция с Prometheus:**
- Используйте `node_exporter` метрику `node_timex_offset_seconds` для контроля дрейфа на хосте
- Для контейнеров добавьте проверку в виде sidecar-скрипта или blackbox-exporter probe

### Типичные инциденты и реагирование

| Инцидент | Причина | Действия SRE |
| :--- | :--- | :--- |
| **Логи с неправильным временем** | `TZ` не задан или устарел `tzdata` | 1. Проверьте `docker exec <id> date` и `printenv TZ` 2. Обновите `tzdata` в образе 3. Перезапустите контейнер |
| **CronJob сбивает расписание** | Переход на DST без `timeZone` в K8s 1.27+ | 1. Добавьте поле `timeZone` в манифест CronJob 2. Проверьте актуальность `tzdata` в образе |
| **Дублирование/пропуск логов** | Leap second или рассинхронизация часов | 1. Проверьте `timedatectl status` на хосте 2. Убедитесь, что `systemd-timesyncd` активен 3. Для Java-приложений обновите JVM |
| **Ошибки сертификатов** | Системное время ушло вперед/назад | 1. Проверьте время на хосте: `timedatectl status` 2. Принудительно синхронизируйте: `chronyc makestep` 3. Проверьте RTC: `timedatectl` |
| **Расхождение временных меток в Grafana** | Разные TZ в сервисах стека | 1. Убедитесь, что все сервисы используют `TZ=UTC` 2. Настройка временной зоны только на уровне UI Grafana 3. Проверьте `/etc/localtime` в контейнерах Prometheus/Grafana |

### Чек-лист для наряда (Runbook)

При расследовании инцидента, связанного с временем:

```bash
# 1. Проверка времени на хосте
timedatectl status
# → System clock synchronized: yes
# → NTP service: active

# 2. Проверка дрейфа
timedatectl timesync-status
# → Offset: -1.234ms

# 3. Проверка контейнера
docker exec <id> date -u
docker exec <id> printenv TZ

# 4. Проверка tzdata
docker exec <id> ls -la /usr/share/zoneinfo/Europe/Moscow
docker exec <id> zdump /etc/localtime

# 5. Проверка логов systemd-timesyncd
journalctl -u systemd-timesyncd --since "1 hour ago"
```

## Граничные случаи

### Переход на летнее/зимнее время (DST)

- Переменная `TZ` автоматически учитывает переходы на DST, если `tzdata` установлен и актуален.
- **Важно:** `tzdata` в старых образах может содержать устаревшие правила DST. Регулярно обновляйте образы.
- При переходе на летнее время (весна) час **пропускается** (например, 02:00 → 03:00). При осени час **повторяется** (02:00 → 03:00 → 02:00). Приложения должны корректно обрабатывать эти граничные случаи.
- **CronJob в Kubernetes:** поле `timeZone` (K8s 1.27+) учитывает DST. Переменная `TZ` внутри пода не влияет на расписание CronJob.

### Високосные секунды (Leap Seconds)

- Linux-ядро использует «вращающиеся» високосные секунды (leap seconds), которые не удаляются из UTC-счётчика.
- **Проблема:** Некоторые приложения (особенно Java) могут дублировать или пропускать секунду 23:59:60.
- **Решение:** Используйте `tzdata` из последнего обновления и следите за обновлениями дистрибутива. Для критичных систем рассмотрите метод **leap smear** (смещение вместо вставки секунды).

### Исторические изменения часовых поясов

- IANA tzdata хранит историю изменений часовых поясов. Например, Россия отменила переход на летнее время в 2014 году.
- Приложения, обрабатывающие исторические временные метки (например, анализ логов за годы), должны использовать актуальную версию `tzdata`.
- В Docker это значит: не используйте `--virtual .tz-build` с удалением `tzdata` в продакшене, если приложение работает с историческими датами.

## Дополнительная информация

### См. также
- [Безопасность Docker](../Docker_security/overview.md) — риски привилегированного доступа.
- [Логирование в Docker](../Docker_logs/docker_logging_drivers_overview.md) — глубокий разбор драйверов.
- [Настройка времени в Linux](../../Linux/Core/systemd/time_synchronization.md) — база по NTP и Chrony.
