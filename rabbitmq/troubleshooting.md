# RabbitMQ: Устранение неполадок (Troubleshooting)

## Операционный контекст

RabbitMQ в production на bare-metal или виртуальных машинах имеет характерные точки отказа: узел Erlang, диск, память, сеть и клиентские приложения. Устранение неполадок строится на знании архитектуры (Connection → Channel → Exchange → Queue → Consumer) и внутренних механизмов (Raft, gossip, flow control). Этот файл является центральным справочником по диагностике и восстановлению. Для специализированных сценариев используйте смежные файлы:

- **[Установка, кластеризация и эксплуатация](./installation_and_clustering.md)** — кластерные проблемы (узел не присоединяется, потеря кворума, медленная репликация, обновление версий).
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — проблемы с метриками, Prometheus, Alertmanager.
- **[Обзор RabbitMQ](./overview.md)** — базовые концепции, гарантии доставки, ограничения.

## Определения

- **Troubleshooting (Устранение неполадок)** — систематический процесс выявления, анализа и устранения причин, препятствующих корректной работе RabbitMQ брокера или клиентских приложений.
- **Memory Pressure (Давление памяти)** — состояние, при котором RabbitMQ блокирует публикации сообщений для предотвращения исчерпания оперативной памяти. Возникает при превышении `vm_memory_high_watermark`.
- **Flow Control** — механизм брокера, замедляющий или блокирующий подключения при критическом уровне потребления ресурсов.
- **Dead Letter Exchange (DLX)** — обменник, в который перенаправляются сообщения, не удавшиеся при обработке (reject, nack с requeue=false, TTL истек, превышен delivery-limit).
- **Poison Message (Ядовитое сообщение)** — сообщение, которое консьюмер не может обработать и возвращает в очередь снова и снова, вызывая бесконечный цикл.
- **Split-Brain** — состояние кластера, при котором группа узлов разделена сетевой разбивкой, и каждая часть считает себя действующей. В RabbitMQ 4.0+ Khepri минимизирует риск потери данных, но требуется ручное вмешательство для восстановления кворума.
- **Consumer Cancellation** — отмена подписки консьюмера брокером (например, при удалении очереди, превышении prefetch или закрытии канала). Клиентское приложение должно обработать `basic_cancel` и корректно завершить работу.
- **Channel Flow Control** — отдельный от глобального Memory Pressure механизм, при котором брокер приостанавливает конкретный канал при переполнении его внутреннего буфера unacked-сообщений.
- **Erlang Process Limit** — максимальное количество Erlang-процессов на узле (по умолчанию ~1 048 576). При исчерпании брокер перестает принимать новые подключения.
- **Disk Free Limit** — порог свободного места на диске (`disk_free_limit`), при котором брокер блокирует публикации и переходит в режим только чтения.
- **Graceful Shutdown** — корректное завершение работы узла с сохранением метаданных и кворума. В отличие от `kill -9`, позволяет избежать необходимости пересоздания кластера.

## Основные концепции

### Типичные категории проблем

| Категория | Симптомы | Частые причины |
|:---|:---|:---|
| **Доступность** | Нет подключения, connection refused | Брокер упал, порт закрыт, firewall, Erlang cookie mismatch |
| **Производительность** | Низкий throughput, высокая латентность | Нехватка RAM/CPU, медленный диск, network, недостаточно консьюмеров |
| **Доставка** | Сообщения теряются, дублируются | Отсутствует confirm_delivery, auto_ack=True, отсутствие идемпотентности |
| **Репликация** | Кворум потерян, данные не реплицируются | Проблемы с сетью, недостаточно узлов, диск заполнен |
| **Ресурсы** | FD exhaustion, OOM, high CPU | Утечки файловых дескрипторов, большие сообщения, неограниченный prefetch |
| **Безопасность** | Неавторизованный доступ, утечка данных | Слабые пароли, открытый Management UI, отсутствие TLS |

### Методология устранения неполадок

Систематический подход сокращает время восстановления (MTTR):

1. **Ограничь область:** Определите, работает ли один узел, несколько или весь кластер.
2. **Соберите метрики:** `rabbitmq-diagnostics status`, `rabbitmq-diagnostics memory_breakdown`, `rabbitmqctl list_queues`.
3. **Проверьте логи:** `journalctl -u rabbitmq-server --since "30 minutes ago"` — ищите предупреждения и ошибки.
4. **Проверьте ресурсы:** `df -h`, `free -m`, `ulimit -n`, `ps aux | grep beam`.
5. **Проверьте сеть:** `nc -zv nodeX 5672`, `nc -zv nodeX 25672`, `rabbitmqctl cluster_status`.
6. **Проверьте клиент:** Статус подключений, каналов, консьюмеров (`list_connections`, `list_channels`, `list_consumers`).
7. **Примените изоляцию:** Если проблема в конкретной очереди или обменнике, сосредоточьтесь на ней; если глобальная — проверьте настройки брокера и ресурсы.
8. **Восстановите и верифицируйте:** После исправления подтвердите, что метрики вернулись к норме и алерты сняты.

## Практические сценарии

### Сценарий 1: Консьюмер не получает сообщения

**Симптомы:** `basic_consume` работает, но callback не вызывается.

**Диагностика:**

```bash
# 1. Проверить количество потребителей в очереди
sudo rabbitmqctl list_queues name consumers messages_ready messages_unacknowledged
# → Если consumers=0, консьюмер не подключен или отключился

# 2. Проверить статус подключений
sudo rabbitmqctl list_consumers
# → Должен показать активных потребителей

# 3. Проверить ACL (если используется виртуальный хост)
sudo rabbitmqctl list_permissions -p my_vhost
```

**Решение:**
- Убедитесь, что консьюмер установил `basic_consume` с правильным именем очереди.
- Проверьте, что консьюмер имеет права `read` на очередь и `write` на обменник.
- Проверьте, что очередь не удалена (проверьте политики auto-delete).
- Проверьте, не получил ли консьюмер `basic.cancel` от брокера (например, при переполнении prefetch).

### Сценарий 2: Сообщения накапливаются в очереди (High Watermark)

**Симптомы:** `messages_ready` растет, `messages_unacknowledged` растет.

**Диагностика:**

```bash
# Проверить prefetch count консьюмеров
sudo rabbitmqctl list_consumers -p my_vhost
# → Смотрите на: prefetch_count

# Проверить скорость обработки
watch -n 1 'sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged'
```

**Решение:**
- Увеличьте количество консьюмеров (parallelism).
- Установите `prefetch_count` (QoS) для ограничения буферизации на одном консьюмере:
  ```python
  channel.basic_qos(prefetch_count=10)  # Не более 10 неподтвержденных сообщений
  ```
- Проверьте, не зависли ли консьюмеры (memory leak, deadlock).
- Проверьте скорость публикации: если продюсеры генерируют сообщения быстрее, чем консьюмеры их обрабатывают, очередь будет расти независимо от prefetch.

### Сценарий 3: Publisher Confirms не работают

**Симптомы:** `UnroutableError` не выбрасывается, сообщения теряются при перезагрузке брокера.

**Диагностика:**

```python
# Проверьте, что confirm_delivery включен ДО публикации
channel.confirm_delivery()
try:
    channel.basic_publish(...)
except pika.exceptions.UnroutableError:
    print("Unroutable")
```

**Решение:**
- Убедитесь, что очередь объявлена с `durable=True`.
- Установите `delivery_mode=2` (персистентность) в `BasicProperties`.
- Проверьте, что брокер включил `persistent` режим для очереди (не `transient`).
- Включите Publisher Confirms на уровне соединения или канала до начала публикаций.

### Сценарий 4: Брокер блокирует публикации (Memory/Flow Control)

**Симптомы:** `connection.blocked` от брокера, публикации зависают.

**Диагностика:**

```bash
# Проверить статус аллармов
sudo rabbitmq-diagnostics alarms
# → Может показать: memory, disk

# Проверить использование памяти
sudo rabbitmq-diagnostics memory_breakdown
# → Смотрите на: messaging, indices, metadata, binary, connection_other, connection_channels, connection_procs, connection_other_procs, ets, metrics, quorum_queue_procs, quorum_queue_core_procs, stream_procs, stream_queue_procs, stream_coordinator_procs, stream_leader_procs, stream_http_procs, stream_chunk_procs, other_procs

# Проверить процесс Erlang
ps aux | grep beam.smp
```

**Решение:**
- Увеличьте `vm_memory_high_watermark` в `/etc/rabbitmq/rabbitmq.conf`:
  ```ini
  vm_memory_high_watermark.relative = 0.6  # 60% вместо 40%
  ```
- Добавьте больше узлов в кластер (распределение памяти).
- Проверьте, есть ли утечки сообщений (unacknowledged > 0 на мертвых очередях).
- Перезапустите брокер с `rabbitmqctl reset` только если данные не критичны.
- Настройте `vm_memory_high_watermark.absolute` для стабилизации лимита в гибридных окружениях.

### Сценарий 5: Потеря кворума Quorum Queue

**Симптомы:** Очередь недоступна, `rabbitmq-diagnostics quorum_queues` показывает `no_quorum`.

**Диагностика:**

```bash
# Статус всех quorum очередей
sudo rabbitmq-diagnostics quorum_queues

# Показать, какие узлы членов Raft-группы
sudo rabbitmqctl quorum_status <queue_name>
```

**Решение:**
- Восстановите недоступный узел (если он временно отключен).
- Если узел потерян навсегда, выполните `forget_cluster_node` на живых узлах:
  ```bash
  sudo rabbitmqctl forget_cluster_node rabbit@lost_node --offline
  ```
- **Важно:** Для восстановления кворума требуется большинство узлов Raft-группы. При потере 2 из 3 узлов данные очереди невосстановимы.

> **Примечание:** Кластерные сценарии (объединение узлов, gossip, Erlang cookie, rolling upgrade) подробно описаны в **[Установка, кластеризация и эксплуатация](./installation_and_clustering.md)**.

### Сценарий 6: Poison Message (зацикливание сообщений)

**Симптомы:** Сообщение постоянно возвращается в очередь, консьюмер не может его обработать.

**Диагностика:**

```bash
# Проверить счетчик доставок (delivery_count)
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged --formatter json | jq .
```

**Решение:**
- Настройте `delivery-limit` в политике для Quorum Queues:
  ```bash
  sudo rabbitmqctl set_policy \
    DLX "^errors\." \
    '{"dead-letter-exchange":"dlx","dead-letter-routing-key":"errors","delivery-limit":5}' \
    --apply-to queues
  ```
- Используйте `basic_nack` с `requeue=False` для отправки в DLX после N попыток.
- Реализуйте логику обработки ошибок в консьюмере (logging + DLQ).
- Внедрите идемпотентность на стороне консьюмера (исключайте повторную обработку по уникальному `message_id`).

### Сценарий 7: Высокое потребление диска

**Симптомы:** `df -h` показывает заполнение `/var/lib/rabbitmq`, брокер зависает.

**Диагностика:**

```bash
# Найти большие файлы
sudo du -sh /var/lib/rabbitmq/mnesia/*

# Проверить логи на ошибки записи
sudo journalctl -u rabbitmq-server --since "2 hours ago" | grep -i "disk"

# Проверить, не активировался ли disk alarm
sudo rabbitmq-diagnostics alarms
# → disk
```

**Решение:**
- Очистите старые логи: `sudo rm /var/log/rabbitmq/*.log.*` и перезапустите `logrotate`.
- Настройте `disk_free_limit` в `rabbitmq.conf`:
  ```ini
  disk_free_limit.absolute = 2GB  # Блокировать публикации при <2GB
  ```
- Перенесите `msg_store` на отдельный диск (через `db_dir` и `msg_store_dir`).
- Если брокер уже заблокирован, примонтируйте дополнительный диск или удалите неиспользуемые очереди/сообщения.

### Сценарий 8: Сетевые разбиения (Network Partition)

**Симптомы:** Логи содержат `network partition detected`, кластер разделился на части.

**Диагностика:**

```bash
# Проверить статус кластера
sudo rabbitmqctl cluster_status
# → Смотрите на: partitions, running_nodes
```

**Решение:**
- Восстановите сетевую связность между узлами.
- Настройте `cluster_partition_handling` в `/etc/rabbitmq/rabbitmq.conf`:
  ```ini
  cluster_partition_handling = autoheal  # Или pause_minority для безопасности
  ```
- `pause_minority` рекомендуется для сред, где потеря данных неприемлема: узел, оставшийся без большинства, перестает принимать публикации до восстановления связи.
- После восстановления связи проверьте целостность кворумных очередей: `sudo rabbitmq-diagnostics quorum_queues`.

### Сценарий 9: Исчерпание файловых дескрипторов (File Descriptors)

**Симптомы:** Брокер перестает принимать подключения, логи содержат `too many open files` или `emfile`.

**Диагностика:**

```bash
# Проверить лимит для процесса beam.smp
cat /proc/$(pgrep -f beam.smp)/limits | grep "open files"
# → Max open files            1024                 1048576                 files

# Проверить текущее количество открытых FD
sudo lsof -p $(pgrep -f beam.smp) | wc -l

# Проверить открытые сокеты
sudo rabbitmq-diagnostics sockets
```

**Решение:**
- Увеличьте `LimitNOFILE` в systemd-юните:
  ```ini
  # /etc/systemd/system/rabbitmq-server.service.d/limits.conf
  [Service]
  LimitNOFILE=65536
  ```
  Затем `sudo systemctl daemon-reload && sudo systemctl restart rabbitmq-server`.
- Проверьте, нет ли утечек файловых дескрипторов в клиентских приложениях.
- Мониторьте `rabbitmq_process_open_fds` в Prometheus.

### Сценарий 10: Плагин не загружается (Plugin Load Failure)

**Симптомы:** После `rabbitmq-plugins enable` плагин не появляется в списке, Management UI недоступен.

**Диагностика:**

```bash
# Список плагинов
sudo rabbitmq-plugins list
# → Смотрите на статус [E] (enabled) или [ ] (disabled)

# Проверить, активирован ли плагин
sudo rabbitmq-plugins enable rabbitmq_management
# → Если ошибка: "plugin rabbitmq_management depends on rabbitmq_web_dispatch"

# Проверить версию плагина и брокера
sudo rabbitmqctl status | grep -i "rabbitmq_management"
```

**Решение:**
- Убедитесь, что зависимости плагина удовлетворены (например, `rabbitmq_web_dispatch` для Management).
- Проверьте архитектуру Erlang/OTP: плагин должен быть скомпилирован под версию Erlang, установленную на узле.
- При обновлении RabbitMQ удалите старые версии плагинов: `sudo rabbitmq-plugins disable --offline <plugin>`.

### Сценарий 11: Ошибки авторизации (Permission Denied)

**Симптомы:** Клиент получает `ACCESS_REFUSED - Login was refused using authentication mechanism PLAIN`, или операции с очередями возвращают `access_refused`.

**Диагностика:**

```bash
# Проверить права пользователя
sudo rabbitmqctl list_permissions -p my_vhost
# → app_user  configure  .*  .*  .*

# Проверить существование пользователя
sudo rabbitmqctl list_users
# → app_user  [my_vhost]

# Проверить, существует ли vhost
sudo rabbitmqctl list_vhosts
# → my_vhost
```

**Решение:**
- Убедитесь, что пользователь существует и имеет права на нужный vhost:
  ```bash
  sudo rabbitmqctl set_permissions -p my_vhost app_user ".*" ".*" ".*"
  ```
- Проверьте, что клиент подключается к правильному vhost (`/` по умолчанию).
- Для LDAP/OAuth2 проверьте конфигурацию внешнего аутентификатора в `rabbitmq.conf`.

### Сценарий 12: Ошибки TLS/SSL рукопожатия

**Симптомы:** Подключение падает с `ssl_connect: ssl handshake failure`, `certificate verify failed`, или `tlsv1 alert unknown ca`.

**Диагностика:**

```bash
# Проверить конфигурацию TLS
sudo rabbitmq-diagnostics listeners
# → 5671 (tls) ...

# Проверить сертификат
openssl s_client -connect localhost:5671 -servername rabbitmq.local
# → Проверьте: issuer, subject, validity dates, chain

# Проверить конфигурацию в rabbitmq.conf
grep -E "ssl_options|listeners.ssl" /etc/rabbitmq/rabbitmq.conf
```

**Решение:**
- Убедитесь, что цепочка сертификатов (CA → intermediate → server) полная и не содержит самоподписанных корневей, если клиент их не доверяет.
- Проверьте соответствие `sni` имени (`ssl_cert_login_from`) имени, указанному в сертификате (`subjectAltName`).
- Для самоподписанных сертификатов добавьте CA в доверенные на стороне клиента.
- Убедитесь, что версии TLS совместимы (например, `tlsv1.2` на брокере и `tlsv1.3` на клиенте).

### Сценарий 13: Неожиданное закрытие канала (Channel Closed)

**Симптомы:** Консьюмер или продюсер получает `Channel.Close` с кодом 541 (INTERNAL_ERROR) или 406 (PRECONDITION_FAILED).

**Диагностика:**

```bash
# Список активных каналов
sudo rabbitmqctl list_channels pid user state consumer_count
# → Смотрите на: state (flow, running)

# Проверить, не приостановлен ли канал flow control
sudo rabbitmq-diagnostics channels
# → Смотрите на: consumer_count, messages_unacknowledged
```

**Решение:**
- **541 INTERNAL_ERROR:** Часто вызван нехваткой ресурсов (память, FD). Проверьте аллармы и лимиты.
- **406 PRECONDITION_FAILED:** Попытка повторно объявить очередь с отличающимися аргументами (например, без `durable` или с другим `x-queue-type`). Убедитесь, что конфигурация очереди единообразна.
- Обработайте `on_channel_close` в клиентском коде для логирования и переподключения.
- Для долгоживущих приложений реализуйте автоматическое восстановление канала (automatic recovery) или переподключение (reconnect).

### Сценарий 14: Достигнут лимит Erlang-процессов

**Симптомы:** Брокер перестает принимать новые подключения, логи содержат `process limit reached` или `too many processes`.

**Диагностика:**

```bash
# Текущее количество Erlang-процессов
sudo rabbitmq-diagnostics status | grep "erlang_processes"
# → {erlang_processes, 850000}

# Лимит процессов
sudo rabbitmqctl environment | grep "+P"
# → [{erlang_processes, ...}, {process_limit, ...}]
```

**Решение:**
- Увеличьте лимит процессов в `rabbitmq.conf`:
  ```ini
  process_limit = 2000000  # 2M вместо дефолтных ~1M
  ```
- Перезапустите брокер.
- Найдите источник утечки: `rabbitmqctl list_connections`, `rabbitmqctl list_channels` — проверяйте, не создают ли клиентские приложения тысячи каналов на одно соединение.
- Рассмотрите архитектурные изменения: один канал на очередь вместо множества, или ограничение количества каналов на приложение.

### Сценарий 15: Высокое потребление CPU

**Симптомы:** `top` показывает `beam.smp` с CPU >90%, латентность публикации растет.

**Диагностика:**

```bash
# Топ Erlang-процессов по CPU
sudo rabbitmqctl eval 'erlang:process_info(erlang:whereis(rabbit_channel_sup), message_queue_len).'

# Проверить количество каналов и подключений
sudo rabbitmqctl list_connections name
sudo rabbitmqctl list_channels name connection pid

# Проверить, нет ли циклов в Vhost
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged --formatter json | jq .
```

**Решение:**
- Проверьте, не создают ли клиентские приложения "шторм" каналов (thundering herd).
- Ограничьте количество одновременно открытых каналов на приложение.
- Если высокая нагрузка вызвана массовыми переподключениями (reconnect storm), добавьте экспоненциальный backoff в клиентский код.
- Проверьте, нет ли проблем с сетевыми задержками, вызывающих частые таймауты и повторные попытки.
- Для Streams проверьте, не перегружен ли лидер партиции: `rabbitmqctl stream_list_consumers <stream_name>`.

### Сценарий 16: Management UI/API не отвечает

**Симптомы:** `curl http://localhost:15672/api/overview` зависает или возвращает 502, веб-интерфейс не загружается.

**Диагностика:**

```bash
# Проверить, слушает ли плагин Management
sudo rabbitmq-diagnostics ports
# → Должен показать 15672

# Проверить статус плагина
sudo rabbitmq-plugins list | grep management
# → [E] rabbitmq_management

# Проверить процесс cowboy (веб-сервер плагина)
ps aux | grep -E "cowboy|ranch"
```

**Решение:**
- Убедитесь, что `management.tcp.ip` настроен на доступный интерфейс (не только `127.0.0.1`, если нужно удаленное управление).
- Проверьте, не утекла ли память у веб-серверного процесса (Cowboy Ranch) при очень большом количестве очередей (>10 000).
- Если API возвращает 503, проверьте, не активирован ли `disk alarm` — при нехватке диска Management переходит в режим только чтение.
- Перезапустите плагин: `sudo rabbitmq-plugins disable rabbitmq_management && sudo rabbitmq-plugins enable rabbitmq_management`.

### Сценарий 17: Нарушение порядка сообщений (Ordering Violation)

**Симптомы:** Консьюмер обрабатывает сообщения не в порядке публикации.

**Диагностика:**

```bash
# Проверить количество консьюмеров в очереди
sudo rabbitmqctl list_queues name consumers
# → Если consumers > 1, порядок не гарантируется по определению

# Проверить, есть ли requeue
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged --formatter json | jq .
# → messages_unacknowledged > 0 при requeue возвращает сообщение в конец
```

**Решение:**
- Гарантируйте один консьюмер на очередь, если порядок критичен.
- Используйте `Single Active Consumer` (расширение RabbitMQ) для автоматического переключения на резервный консьюмер при падении основного.
- Отключите requeue для необработанных сообщений — используйте DLX вместо `basic_nack(requeue=True)`.
- Для параллезма с сохранением порядка используйте ключевое поле (`correlation_id`, `partition_key`) и Hash Exchange (плагин) для маршрутизации по ключу.

### Сценарий 18: Высокая задержка диска (Disk I/O Latency)

**Симптомы:** Публикации подтверждаются медленно, `messages_persistent` растет, `iostat` показывает высокий `await`.

**Диагностика:**

```bash
# Проверить задержку диска
iostat -x -d 1 5
# → Смотрите на: await, %util

# Проверить, куда пишет RabbitMQ
sudo rabbitmq-diagnostics memory_breakdown
# → Смотрите на: msg_store, indices

# Проверить тип хранилища
mount | grep /var/lib/rabbitmq
# → /dev/nvme0n1p3 on /var/lib/rabbitmq type ext4
```

**Решение:**
- Переместите `db_dir` и `msg_store` на SSD или NVMe.
- Отделите диск для сообщений от диска для ОС и логов.
- Увеличьте `queue_index_embed_msgs_below` для маленьких сообщений (они хранятся в индексе очереди, а не в отдельном файле):
  ```ini
  queue_index_embed_msgs_below = 4096  # 4KB
  ```
- Проверьте, не работает ли диск в режиме `ro` (read-only) после ошибки.

## Оптимизация производительности RabbitMQ

### Дисковая подсистема

- **Используйте SSD/NVMe** для `/var/lib/rabbitmq` — основной фактор производительности
- **Отдельный диск** для логов (`/var/log/rabbitmq`)
- **Монтирование с `noatime,nodiratime`** — снижение overhead на запись
- **XFS или ext4** с `inode64` для больших файлов

### Память и ресурсы

```ini
# /etc/rabbitmq/rabbitmq.conf

# Высокий порог памяти (40% RAM по умолчанию)
vm_memory_high_watermark.relative = 0.4

# Минимальное свободное место на диске
disk_free_limit.absolute = 2GB

# Лимит Erlang-процессов
process_limit = 2000000
```

### Prefetch и consumer'ы

```python
# Настройка prefetch для балансировки нагрузки
channel.basic_qos(prefetch_count=10)  # Для средних задач

# Мониторинг consumer lag
# promql: sum(rabbitmq_queue_messages_ready) by (vhost, name) / sum(rabbitmq_queue_consumers) by (vhost, name)
```

### Connection pooling

```python
# Переиспользование TCP-соединений
connection = pika.BlockingConnection(
    pika.ConnectionParameters(
        host='localhost',
        heartbeat=600,
        blocked_connection_timeout=300
    )
)
```

### Мониторинг производительности

```promql
# Memory pressure
rabbitmq_resident_memory_limit_bytes / rabbitmq_resident_memory_bytes > 0.8

# Queue depth
rabbitmq_queue_messages_ready > 10000

# Consumer lag
rabbitmq:queue_consumer_lag:rate1h > 50000

# Flow control
rabbitmq_channel_flow_blocked > 0
```

### Рекомендации

1. **Используйте Quorum Queues** для HA и отказоустойчивости
2. **Настраивайте prefetch** для контроля нагрузки
3. **Мониторьте память** и disk space
4. **Используйте Publisher Confirms** для критичных данных
5. **Разделяйте vhosts** по средам

## Дополнительная информация

### Диагностические команды (шпаргалка)

```bash
# Общий статус кластера
sudo rabbitmq-diagnostics status

# Список всех очередей с метриками
sudo rabbitmqctl list_queues name durable auto_delete messages_ready messages_unacknowledged consumers

# Список подключений
sudo rabbitmqctl list_connections user client_host state

# Проверка здоровья конкретного узла
sudo rabbitmq-diagnostics health_check

# Проверка gossip-сообщений
sudo rabbitmq-diagnostics cluster_status

# Проверка открытых файловых дескрипторов
sudo rabbitmq-diagnostics open_file_handles

# Проверка состояния каналов
sudo rabbitmqctl list_channels name connection pid state

# Проверка слушателей (порты)
sudo rabbitmq-diagnostics ports
```

### Метрики для диагностики через Management API

```bash
# Обзор кластера (JSON)
curl -s -u guest:guest http://localhost:15672/api/overview | jq .

# Глубина конкретных очередей
curl -s -u guest:guest "http://localhost:15672/api/queues/%2F?columns=name,messages_ready,messages_unacknowledged" | jq .

# Проверка аллармов через API
curl -s -u guest:guest http://localhost:15672/api/alarms | jq .
```

### См. также

- **[Обзор RabbitMQ](./overview.md)** — базовые концепции, гарантии доставки, ограничения.
- **[Установка и кластеризация](./installation_and_clustering.md)** — развертывание кластеров, кворум, backup.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — метрики, Prometheus, Grafana, алерты.
- **[Сравнение RabbitMQ и Kafka](../Kafka/rabbitmq_vs_kafka.md)** — архитектурные различия.
- **[CLI-команды](./cli_reference.md)** — справочник диагностических команд.
- **[Безопасность](./security.md)** — диагностика ошибок авторизации и TLS.
- **[Клиентские библиотеки](./client_libraries.md)** — типичные ошибки клиентов.


### Лучшие практики

1. **Настройте алерты на `memory alarm` и `disk alarm`** — это первые признаки, что брокер приближается к нерабочему состоянию.
2. **Используйте Quorum Queues** для всех критичных данных в RabbitMQ 4.0+ — они автоматически ограничивают `delivery-limit` и минимизируют риск потери данных.
3. **Настраивайте префетч (prefetch count)** для консьюмеров, чтобы избежать неравномерного распределения нагрузки и памяти.
4. **Мониторьте file descriptors** — RabbitMQ может открывать тысячи файлов при высокой нагрузке.
5. **Всегда используйте Publisher Confirms** для гарантии приема сообщения брокером.
6. **Реализуйте graceful shutdown** в клиентских приложениях: `basic_cancel` → обработка оставшихся unacked → закрытие канала → закрытие соединения.
7. **Ведите логи клиентских ошибок** (`channel.close`, `connection.close`) — часто корень проблемы в приложении, а не в брокере.
8. **Регулярно проверяйте кворум** через `rabbitmq-diagnostics quorum_queues` — проактивная проверка предотвращает внезапные отказы.
9. **Храните сообщения ≤1 MiB** — большие сообщения снижают пропускную способность и увеличивают потребление RAM/диска.
10. **Разделяйте vhosts** по средам (dev/staging/prod) — упрощает диагностику и ограничивает последствия проблем в одной среде.
