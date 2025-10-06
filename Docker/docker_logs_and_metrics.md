# Основы: docker logs

Основной инструмент для просмотра логов, которые приложение внутри контейнера выводит в стандартные потоки `STDOUT` и `STDERR`.

| Команда | Описание |
| :--- | :--- |
| `docker logs <id_контейнера>` | Показать все логи для контейнера. |
| `docker logs -f <id_контейнера>` | Выводить логи в реальном времени (режим follow). |
| `docker logs --tail 30 <id_контейнера>` | Показать последние 30 строк логов. |
| `docker logs --since 10m <id_контейнера>` | Показать логи за последние 10 минут. |

## Логирование Nginx в Docker

Чтобы `docker logs` мог собирать логи вашего приложения, приложение должно писать их в `STDOUT` и `STDERR`. Многие приложения по умолчанию пишут логи в файлы.

Классический пример — Nginx. Чтобы его логи стали доступны Docker, необходимо в `Dockerfile` перенаправить стандартные файлы логов на потоки вывода с помощью символических ссылок.

```dockerfile
RUN set -ex && \
    ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log
```

Эта команда заменяет файлы `access.log` и `error.log` ссылками на стандартные потоки, делая их видимыми для Docker.

## Как работает логирование

Docker не просто выводит текст в консоль. Он использует **лог-драйверы (logging drivers)** для перехвата потоков `STDOUT` и `STDERR` и их последующей обработки.

- **Драйвер по умолчанию: `json-file`**
  - **Принцип работы:** Сохраняет логи в JSON-файлы на хост-машине.
  - **Расположение:** `/var/lib/docker/containers/<id_контейнера>/<id_контейнера>-json.log`
  - **Недостатки:**
    - **Локальное хранение:** Не подходит для многохостовых окружений и облаков.
    - **Размер:** Без настройки ротации может быстро занять все дисковое пространство.
    - **Сложность анализа:** Поиск по множеству файлов затруднителен.

> **Вывод:** Драйвер `json-file` удобен для разработки, но **не рекомендуется для производственных сред.**

> **Важное замечание о `docker logs`:**
> Команда `docker logs` работает только с теми драйверами, которые предоставляют доступ к логам локально.
> - **Работает:** `json-file`, `local`, `journald`.
> - **Не работает:** Драйверы-экспортеры, такие как `fluentd`, `syslog`, `gelf`, `awslogs` и другие. Они отправляют логи во внешние системы, и Docker daemon больше не имеет к ним доступа. При использовании этих драйверов `docker logs` вернет ошибку.


## Централизованное логирование в Production

В реальных системах логи необходимо собирать в одном месте. Для этого используются другие драйверы, которые настраиваются в файле `/etc/docker/daemon.json` или при запуске контейнера.

Популярные драйверы для production:
- **`journald`**: Интегрируется с `systemd-journald`, позволяя использовать `journalctl` для просмотра логов.

  > **Тюнинг `journald` для Docker**
  > По умолчанию `journald` имеет встроенные ограничения на количество принимаемых логов (`RateLimitIntervalSec` и `RateLimitBurst`). Контейнеры могут генерировать огромное количество логов, что приводит к превышению этих лимитов и **потере части сообщений**.
  >
  > **Симптом:** В логах `journald` появляется сообщение вида `systemd-journald[...]: Suppressed ... messages from ...`
  >
  > **Решение:** Отредактируйте файл `/etc/systemd/journald.conf` и увеличьте или отключите лимиты:
  > ```ini
  > [Journal]
  > # Увеличить лимит до 50000 сообщений в 30 секунд (значения по умолчанию ~10000)
  > RateLimitBurst=50000
  >
  > # Или полностью отключить ограничение (не рекомендуется для всех систем)
  > # RateLimitIntervalSec=0
  > # RateLimitBurst=0
  > ```
  >
  > После изменения файла перезапустите службу:
  > ```bash
  > sudo systemctl restart systemd-journald
  > ```

- **`fluentd`**: Отправляет логи на сервер-агрегатор Fluentd. Это один из самых гибких вариантов для сложных систем. Существует два основных подхода к его использованию.

### Альтернативный подход: Fluentd как лог-драйвер

Этот метод заключается в настройке Docker для прямой отправки логов в Fluentd. Он прост в настройке, но менее надежен, так как при недоступности Fluentd-сервера логи могут быть утеряны.

**1. Настройка Docker-демона (`/etc/docker/daemon.json`):**
```json
{
  "log-driver": "fluentd",
  "log-opts": {
    "fluentd-address": "localhost:24224",
    "tag": "docker.{{.Name}}"
  }
}
```
После изменения необходимо перезапустить Docker-демон.

**2. Настройка для отдельного контейнера:**
```bash
docker run \
  --log-driver=fluentd \
  --log-opt fluentd-address=localhost:24224 \
  --log-opt tag="docker.my_app.{{.Name}}" \
  your/application_image
```

**3. Базовая конфигурация Fluentd (`fluent.conf`):**
Для приема логов от драйвера используется источник `@type forward`.
```conf
# Источник: Принимает логи от Docker logging driver
<source>
  @type forward
  port 24224
  bind 0.0.0.0
</source>

# Назначение: Вывод логов в stdout (для демонстрации)
<match docker.**>
  @type stdout
</match>
```

### Обработка многострочных логов (например, стектрейсов)

Многострочные логи требуют специальной обработки. Для этого в `fluent.conf` используется плагин-парсер `multiline`.

```conf
<filter docker.**>
  @type parser
  key_name log
  <parse>
    @type multiline
    # Указывает, что новая запись начинается, например, с даты
    format_firstline /^\d{4}-\d{2}-\d{2}/ 
    # Описывает формат первой строки для извлечения полей
    format1 /^(?<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) (?<level>\w+) (?<message>.*)/
  </parse>
</filter>
```

> **Важно:** Далее в этом документе описан **рекомендуемый для production** подход с использованием Fluentd в качестве агента-сборщика, который является более надежным.

**Пример конфигурации `daemon.json` для `journald`:**
```json
{
  "log-driver": "journald",
  "log-opts": {
    "tag": "{{.ImageName}}/{{.Name}}/{{.ID}}"
  }
}
```

## Рекомендуемая архитектура: `json-file` + Fluentd Agent

Вместо использования `fluentd` как лог-драйвера, более надежный и гибкий подход — использовать его как **агент-сборщик**, который читает стандартные `json-file` логи, создаваемые Docker по умолчанию.

**Схема:** `Приложение -> STDOUT/STDERR -> Docker (json-file) -> Fluentd (агент) -> Elasticsearch/etc.`

**Преимущества:**
- **Надежность и буферизация:** Docker стабильно пишет логи на локальный диск. Если Fluentd или сеть до ELK-стека недоступны, логи не теряются. Fluentd-агент продолжит чтение с места, на котором остановился, после восстановления связи.
- **Разделение ответственности (Decoupling):** Контейнеры и Docker-демон работают в штатном режиме, не зная о системе логирования. Сбор и отправка логов — полностью задача агента Fluentd.
- **Простота конфигурации Docker:** Не нужно менять `daemon.json` или указывать `--log-driver` для каждого контейнера.

**Реализация:**

1.  **Docker:** Продолжает использовать драйвер `json-file` (настройка по умолчанию).
2.  **Fluentd Agent:** Запускается как отдельный контейнер на каждом Docker-хосте.

**Пример `docker-compose.yml` для агента Fluentd:**

```yaml
services:
  fluentd-agent:
    image: fluent/fluentd:v1.19.0-debian-1.0
    container_name: fluentd-agent
    volumes:
      # Монтируем директорию с логами Docker и позиционные файлы fluentd
      - /var/lib/docker/containers:/fluentd/log/containers:ro
      - ./fluentd/pos:/fluentd/pos
      - ./fluentd/conf:/fluentd/etc:ro
    restart: unless-stopped
```

**Пример `fluent.conf` для чтения `json-file` логов:**

```conf
# Источник: читаем все *-json.log файлы из директории с логами Docker
<source>
  @type tail
  path /fluentd/log/containers/*/*-json.log
  pos_file /fluentd/pos/docker-logs.pos
  tag docker.*
  <parse>
    @type json
    time_format %Y-%m-%dT%H:%M:%S.%NZ
  </parse>
</source>

# Фильтр: обогащаем логи метаданными из имени файла
# Пример: /fluentd/log/containers/CONTAINER_ID/CONTAINER_ID-json.log
<filter docker.**>
  @type record_transformer
  <record>
    container_id ${tag_parts[1]}
  </record>
</filter>

# Назначение: отправляем в Elasticsearch
<match docker.**>
  @type elasticsearch
  host elasticsearch.example.com
  port 9200
  # ... другие настройки ...
</match>
```
- **`@type tail`**: Плагин для чтения файлов "на лету", как `tail -f`.
- **`pos_file`**: Fluentd запоминает в этом файле, на какой строке он остановил чтение, чтобы не отправлять дубликаты после перезапуска.
- **`@type record_transformer`**: Мощный фильтр для добавления/изменения полей. Здесь мы извлекаем ID контейнера из тега, который `in_tail` формирует из имени файла.

---

## Мониторинг ресурсов

## Быстрая диагностика: `docker stats` и `docker system df`

Предоставляет информацию об использовании ресурсов всеми запущенными контейнерами в реальном времени.

| Команда | Описание |
| :--- | :--- |
| `docker stats` | Показать динамическую статистику по CPU, памяти, сети и I/O для всех контейнеров. |
| `docker stats <id_контейнера>` | Показать статистику только для указанного контейнера. |
| `docker stats --no-stream` | Показать однократный снимок статистики и выйти. |

Данные для `docker stats` собираются из **[cgroups](./docker_components.md#cgroups-управление-ресурсами)** — механизма ядра Linux. Вы можете найти сырые метрики в псевдофайловой системе cgroups, например:
- **Память:** `/sys/fs/cgroup/memory/docker/<long_id>/memory.stat`
- **CPU:** `/sys/fs/cgroup/cpu/docker/<long_id>/cpuacct.stat`

## Команда `docker system df`

Показывает, сколько дискового пространства занимают компоненты Docker.

```bash
# Вывод команды покажет размер, занимаемый образами, контейнерами и томами
docker system df
```

---

## Сбор метрик для Prometheus

Для полноценного мониторинга используются специализированные инструменты, такие как Prometheus. Существует три основных источника метрик:

**Метрики Docker Engine**

Сам Docker может отдавать метрики о своей работе (количество контейнеров, образов и т.д.).

- **Настройка:** Включите `metrics-addr` в файле `/etc/docker/daemon.json`.
  ```json
  {
    "metrics-addr": "0.0.0.0:9323",
    "experimental": true
  }
  ```
- **Назначение:** Мониторинг состояния самого Docker демона.

**Метрики контейнеров (cAdvisor)**

Для сбора детальных метрик производительности *каждого* контейнера используется **cAdvisor (Container Advisor)** от Google. Это стандарт де-факто.

- **Назначение:** Собирает, агрегирует и отдает в формате Prometheus детальную информацию о потреблении CPU, памяти, сети и диска для всех контейнеров на хосте.
- **Запуск:** cAdvisor запускается как еще один Docker-контейнер.

  ```yaml
  # Пример запуска cAdvisor в docker-compose.yml
  services:
    cadvisor:
      image: gcr.io/cadvisor/cadvisor:v0.53.0
      container_name: cadvisor
      ports:
        - "8080:8080"
      volumes:
        - /:/rootfs:ro
        - /var/run:/var/run:rw
        - /sys:/sys:ro
        - /var/lib/docker/:/var/lib/docker:ro
      restart: unless-stopped
  ```
> **Примечание:** Для получения полной картины мониторинга хоста, `cAdvisor` обычно используется в связке с **`node-exporter`**, который собирает метрики самой хост-системы (CPU, диск, сеть и т.д.).

**Метрики приложений**

Метрики, специфичные для вашего приложения (например, количество обработанных запросов, время ответа API).

- **Принцип работы:** Приложение само отдает метрики по эндпоинту `/metrics` с помощью клиентских библиотек Prometheus.
- **Настройка:** Вам нужно лишь убедиться, что порт для метрик доступен для скрейпера Prometheus.

*   [draganm/missing-container-metrics](https://github.com/draganm/missing-container-metrics)
*   [google/cadvisor](https://github.com/google/cadvisor)

---

## Полезные утилиты

- **[`ctop`](https://github.com/bcicen/ctop)**: Утилита в стиле `top` для удобного мониторинга метрик контейнеров в реальном времени прямо в терминале.

## Логирование в контейнерах с несколькими процессами

По умолчанию `docker logs` отслеживает только стандартные потоки (`STDOUT`, `STDERR`) процесса с **PID 1** внутри контейнера. Если вы запускаете несколько процессов, логи дочерних процессов не будут видны, если их не перенаправить.

#### Перенаправление потоков на PID 1

Простой способ — перенаправить потоки дочерних процессов на стандартные потоки процесса с PID 1. В Linux это можно сделать, используя псевдофайловую систему `/proc`.

- `/proc/1/fd/1` — стандартный вывод (STDOUT) процесса PID 1.
- `/proc/1/fd/2` — стандартный вывод ошибок (STDERR) процесса PID 1.

**Пример `entrypoint.sh`:**
```bash
#!/bin/bash

# Запускаем первый процесс в фоне, перенаправляя его потоки
./my-app-1 > /proc/1/fd/1 2>/proc/1/fd/2 &

# Запускаем второй процесс в фоне
./my-app-2 > /proc/1/fd/1 2>/proc/1/fd/2 &

# Ждем завершения всех фоновых процессов
wait -n
```
> **Примечание:** Этот метод прост, но не решает проблему "зомби-процессов" и сложен в управлении.

#### Использование супервизора процессов (рекомендуемый способ)

Более надежное и правильное решение — использовать легковесный менеджер процессов, такой как **`supervisord`**. Он запускается как PID 1, управляет дочерними процессами и корректно собирает их логи.

**Шаги:**
1.  Установите `supervisor` в ваш образ (`apt-get install supervisor` или `pip install supervisor`).
2.  Создайте конфигурационный файл `supervisord.conf`.
3.  Запустите `supervisord` в качестве основной команды (`CMD` или `ENTRYPOINT`).

**Пример `supervisord.conf`:**

```ini
[supervisord]
nodaemon=true ; Запускает supervisord в основном потоке, что необходимо для Docker

[program:app1]
command=/usr/bin/my-app-1
autostart=true
autorestart=true
stdout_logfile=/dev/stdout ; Перенаправить stdout в stdout supervisord
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr ; Перенаправить stderr в stderr supervisord
stderr_logfile_maxbytes=0

[program:app2]
command=/usr/bin/my-app-2
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
```

**Пример Dockerfile:**

```dockerfile
FROM ubuntu:22.04

# ... установка зависимостей и копирование файлов приложения ...
RUN apt-get update && apt-get install -y supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY my-app-1 /usr/bin/my-app-1
COPY my-app-2 /usr/bin/my-app-2

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
```
