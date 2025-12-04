# Централизованное логирование в Production

В реальных системах логи необходимо собирать в одном месте. Для этого используются другие драйверы, которые настраиваются в файле `/etc/docker/daemon.json` или при запуске контейнера.

Популярные драйверы для production:

- **`journald`**: Интегрируется с `systemd-journald`, позволяя использовать `journalctl` для просмотра логов.

  > **Тюнинг `journald` для Docker**
  > 
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
  **Пример конфигурации `daemon.json` для `journald`:**

  ```json
  {
    "log-driver": "journald",
    "log-opts": {
      "tag": "{{.ImageName}}/{{.Name}}/{{.ID}}"
    }
  }
  ```

- **`syslog`**: Отправляет логи на Syslog-сервер хост-машины или удаленный Syslog-сервер.

  - **Принцип работы:** Использует стандартный протокол Syslog. Требует запущенного Syslog-демона на хосте.
  - **Использование:** `docker run --log-driver=syslog --log-opt syslog-address=udp://1.2.3.4:514 my_image`

- **`gelf`**: Отправляет логи на GELF-совместимый сервер (например, Graylog или Logstash).

  - **Принцип работы:** Использует протокол Graylog Extended Log Format (GELF), который позволяет передавать структурированные логи.
  - **Использование:** `docker run --log-driver=gelf --log-opt gelf-address=udp://1.2.3.4:12201 my_image`

- **`fluentd`**: Отправляет логи на сервер-агрегатор Fluentd.

  - **Принцип работы:** Использует протокол Fluentd. Отличается гибкостью и широкими возможностями по трансформации логов.
  - **Использование:** `docker run --log-driver=fluentd --log-opt fluentd-address=localhost:24224 my_image`

## Fluentd как лог-драйвер

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

### Обработка многострочных логов

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
