# RabbitMQ: Установка, кластеризация и эксплуатация

## Определения

- **Кластер RabbitMQ (Cluster):** Группа узлов (обычно 3+), объединенных для обеспечения отказоустойчивости и балансировки нагрузки. Каждый узел имеет одинаковые метаданные (пользователи, vhosts, политики) через Khepri/Raft.
- **Узел (Node):** Экземпляр RabbitMQ с уникальным именем. В кластере каждый узел знает о состоянии других через gossip-протокол.
- **Политика (Policy):** Набор правил, применяемых к очередям или обменникам (например, HA-репликация, TTL, Dead Lettering). Применяется по маске имен.
- **Quorum Queue (QW):** Очередь на базе Raft, требующая большинства узлов для записи. Гарантирует консистентность при сбое узла.
- **Stream Queue (SQ):** Высокопроизводительная очередь на базе неизменяемого лога (аналог Kafka). Поддерживает повторное чтение и millions+ сообщений/сек.
- **Split-Brain:** Состояние кластера, при котором группа узлов разделена сетевой разбивкой, и каждая часть считает себя действующей. В RabbitMQ 4.0+ Khepri минимизирует риск потери данных, но требуется ручное вмешательство для восстановления кворума.
- **Network Partition:** Разделение кластера на изолированные группы из-за отказа сети. Управляется параметром `cluster_partition_handling` (`autoheal`, `pause_minority`, `ignore`).
- **Graceful Shutdown:** Корректное завершение работы узла с сохранением метаданных и кворума. В отличие от `kill -9`, позволяет избежать необходимости пересоздания кластера.
- **Rolling Upgrade:** Поэтапное обновление узлов кластера без полной остановки. Каждый узел останавливается, обновляется и возвращается в кластер по очереди.
- **Learner Node:** Узел, который участвует в репликации данных, но не имеет права голоса в Raft-группах. Используется для чтения (read-only replica) или подготовки к вводу в кластер.
- **Federation:** Логическое объединение кластеров через WAN. Позволяет передавать сообщения между обменниками или очередями в разных кластерах без создания единого кластера.
- **Shovel:** Низкоуровневый механизм надежного копирования сообщений из одного брокера в другой. Идеален для миграций, multi-region и DR.

## Основные концепции

### Архитектура кластера

RabbitMQ использует gossip-протокол для распространения метаданных между узлами. Каждый узел периодически рассылает свое состояние (очереди, подключения, память) остальным членам кластера.

**Процесс формирования кластера:**
1. Узел запускается и ищет других членов через epmd (Erlang Port Mapper Daemon, порт 4369).
2. При обнаружении совпадающего Erlang cookie узел формирует gossip-сообщение.
3. При совпадении имен и конфигурации узел добавляется в `running_nodes`.
4. Khepri (в RabbitMQ 4.0+) реплицирует метаданные через Raft, обеспечивая консистентность.

**Варианты топологии:**

| Топология | Описание | Применение |
|:---|:---|:---|
| **Single Node** | Один узел. Нет отказоустойчивости. | Разработка, тестирование. |
| **Cluster (Same DC)** | 3+ узла в одной сети. Кворум для Quorum Queues. | Production в одном дата-центре. |
| **Federation** | Логическое объединение кластеров через WAN. | Geo-распределение, DR. |
| **Shovel** | Копирование сообщений между кластерами. | Миграции, multi-region. |

**Порты межузлового взаимодействия:**
- `4369/tcp` — epmd (Erlang Port Mapper Daemon). Обнаружение узлов.
- `25672/tcp` — inter-node communication (gossip, Raft). Должен быть открыт между всеми узлами кластера.
- `5672/tcp` — AMQP клиенты.
- `15672/tcp` — Management UI/API.
- `15692/tcp` — Prometheus exporter.
- `35672-35682/tcp` — диапазон для динамических портов inter-node (при конфликтах).

### Роль Khepri

Начиная с RabbitMQ 4.0, метаданные (пользователи, vhosts, политики, параметры) хранятся в **Khepri** — Raft-базированном хранилище, обеспечивающем:
- Консистентность при сетевым разбиениях
- Отказоустойчивость metadata (не требует Mnesia)
- Простое восстановление после потери большинства узлов

**Важно:** В RabbitMQ 4.3+ legacy-хранилище Mnesia удалено окончательно. Для доступности кластера всегда требуется большинство узлов.

### Структура каталогов данных

```
/var/lib/rabbitmq/
├── mnesia/          # Mnesia-совместимые таблицы (переходный период)
├── quorum/          # Raft-логи Quorum Queues
├── stream/          # Данные Stream Queues
├── indices/         # Индексы очередей
├── .erlang.cookie   # Cookie для аутентификации узлов
└── schema/          # Схемы Raft (Khepri)
```

### Erlang cookie

Файл `.erlang.cookie` — секретный ключ для аутентификации Erlang-узлов. Длина 20 байт (SHA-1 MD5-сумма). Должен быть идентичен на всех узлах кластера и иметь права `400`, владелец `rabbitmq:rabbitmq`.

## Практические сценарии

### 1. Установка кластера на 3 узла (bare-metal / VM)

**Предварительные требования:**
- ОС: Linux (RHEL 9+, Ubuntu 22.04+, Debian 12+)
- Сеть: Низкая задержка (<1ms) между узлами, открытые порты 4369 (epmd), 25672 (inter-node), 5672 (AMQP), 15672 (management)
- Доменное имя: Рекомендуется настроить DNS или `/etc/hosts` для разрешения `rabbit@node1`, `rabbit@node2`, `rabbit@node3`
- NTP: Синхронизация времени обязательна (Khepri/Raft чувствителен к рассинхронизации >1s)

**Шаг 1: Установка пакетов**

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y rabbitmq-server erlang-base

# RHEL/Fedora
sudo dnf install -y rabbitmq-server erlang
```

**Шаг 2: Настройка Erlang cookie**

Cookie должен быть одинаковым на всех узлах (иначе кластер не образуется):

```bash
# Создать общий cookie (на всех узлах)
sudo rabbitmqctl await_startup
sudo systemctl stop rabbitmq-server

# Скопировать cookie с первого узла
sudo scp node1:/var/lib/rabbitmq/.erlang.cookie /tmp/.erlang.cookie
sudo chown rabbitmq:rabbitmq /tmp/.erlang.cookie
sudo chmod 400 /tmp/.erlang.cookie
sudo mv /tmp/.erlang.cookie /var/lib/rabbitmq/.erlang.cookie

sudo systemctl start rabbitmq-server
sudo rabbitmqctl await_startup
```

**Шаг 3: Объединение узлов в кластер**

На втором и третьем узлах:

```bash
# Присоединить к первому узлу
sudo rabbitmqctl stop_app
sudo rabbitmqctl reset
sudo rabbitmqctl join_cluster rabbit@node1
sudo rabbitmqctl start_app
```

Проверить кластер:

```bash
sudo rabbitmqctl cluster_status
# → Ожидаемый вывод: running_nodes содержит все три узла
```

**Шаг 4: Валидация**

```bash
# Проверить Khepri
sudo rabbitmqctl status | grep khepri

# Проверить сетевое соединение между узлами
sudo rabbitmq-diagnostics check_local_alarms
sudo rabbitmq-diagnostics check_port_listener 25672
```

### 2. Настройка Quorum Queues и политик

Quorum Queues — современный стандарт для HA-очередей в RabbitMQ 4.0+.

**Создание политики автоматического применения QW:**

```bash
# Применить политики ко всем очередям, начинающимся с "orders."
sudo rabbitmqctl set_policy \
  ha-all "^orders\." \
  '{"ha-mode":"exactly","ha-params":3,"ha-sync-mode":"automatic","queue-type":"quorum"}' \
  --priority 1 \
  --apply-to queues
```

**Параметры политики:**
- `ha-mode: exactly` — реплицировать на ровно 3 узла
- `ha-sync-mode: automatic` — синхронизация происходит автоматически при создании очереди
- `queue-type: quorum` — использовать Raft-очереди

### 3. Добавление узла в существующий кластер

```bash
# На новом узле (node4)
sudo rabbitmqctl stop_app
sudo rabbitmqctl reset
sudo rabbitmqctl join_cluster rabbit@node1
sudo rabbitmqctl start_app
```

**Валидация:**
```bash
sudo rabbitmqctl cluster_status
# → running_nodes теперь содержит 4 узла
```

### 4. Удаление узла из кластера

```bash
# На удаляемом узле
sudo rabbitmqctl stop_app
sudo rabbitmqctl reset

# На живом узле (при необходимости удалить мертвый узел)
sudo rabbitmqctl forget_cluster_node rabbit@lost_node --offline
```

**Валидация:**
```bash
sudo rabbitmqctl cluster_status
# → lost_node отсутствует в running_nodes
```

### 5. Мониторинг и диагностика

**Встроенные команды диагностики:**

```bash
# Проверка здоровья кластера
sudo rabbitmq-diagnostics status

# Проверка состояния кворума для конкретной очереди
sudo rabbitmq-diagnostics quorum_queues

# Проверка потребления памяти
sudo rabbitmq-diagnostics memory_breakdown

# Проверка портов и слушателей
sudo rabbitmq-diagnostics ports

# Проверка состояния репликации
sudo rabbitmq-diagnostics federation_status

# Проверка alarms
sudo rabbitmq-diagnostics alarms
```

**Метрики Prometheus:**

RabbitMQ экспортирует метрики через плагин `rabbitmq_prometheus` (порт 15692):

```bash
# Включить плагин
sudo rabbitmq-plugins enable rabbitmq_prometheus
```

**Ключевые метрики для Grafana:**
- `rabbitmq_queue_messages_ready` — сообщения, ожидающие обработки
- `rabbitmq_queue_messages_unacknowledged` — неподтвержденные сообщения
- `rabbitmq_process_open_fds` — открытые файловые дескрипторы (предотвращение утечек)
- `rabbitmq_resident_memory_limit_bytes` — лимит RAM
- `rabbitmq_erlang_processes` — количество Erlang-процессов

### 6. Backup и восстановление

RabbitMQ не имеет встроенного механизма бэкапа всех данных "в одно действие". Необходимо комбинировать несколько методов:

**Метод 1: Экспорт метаданных (пользователи, vhosts, политики)**

```bash
# Определений
sudo rabbitmqctl export_definitions /tmp/rabbitmq_definitions.json

# Импорт
sudo rabbitmqctl import_definitions /tmp/rabbitmq_definitions.json
```

**Метод 2: Snapshot очередей (Quorum/Stream)**

```bash
# Для Quorum Queue: копирование файлов на выключенном узле
sudo systemctl stop rabbitmq-server
sudo tar -czf /backup/rabbitmq-$(date +%F).tar.gz /var/lib/rabbitmq/quorum/
sudo systemctl start rabbitmq-server
```

**Метод 3: Federation/Shovel для непрерывной репликации**

Настройте Shovel для копирования сообщений в резервный кластер в реальном времени.

### 7. Управление версиями и обновление

**Rolling Upgrade (минимальный простой):**

```bash
# 1. Остановить один узел
sudo rabbitmqctl stop_app
sudo systemctl stop rabbitmq-server

# 2. Обновить пакет
sudo apt install --only-upgrade rabbitmq-server

# 3. Запустить узел
sudo systemctl start rabbitmq-server
sudo rabbitmqctl await_startup
sudo rabbitmqctl start_app

# 4. Повторить для остальных узлов
```

**Важно:** При обновлении с 3.x на 4.0 проверьте совместимость клиентских библиотек и обновите политики на Quorum Queues (классические mirror queues удалены).

### 8. Настройка Federation (кросс-кластер)

Federation позволяет передавать сообщения между обменниками в разных кластерах через WAN.

```bash
# На upstream-кластере: создать upstream
sudo rabbitmqctl set_parameter federation-upstream my-upstream \
  '{"uri":"amqp://user:pass@downstream:5672","expires":3600000}'

# На downstream-кластере: создать upstream (обратное направление)
sudo rabbitmqctl set_parameter federation-upstream my-upstream-reverse \
  '{"uri":"amqp://user:pass@upstream:5672","expires":3600000}'

# Применить federation к обменнику
sudo rabbitmqctl set_policy \
  --apply-to exchanges \
  federate-me "^federated\." \
  '{" federation-upstream-set":"all"}'
```

**Валидация:**
```bash
sudo rabbitmq-diagnostics federation_status
# → upstreams и downstreams показывают активные связи
```

### 9. Настройка Shovel для DR/Migration

Shovel — низкоуровневый механизм копирования сообщений.

```bash
# Создать shovel для копирования сообщений из очереди
sudo rabbitmqctl set_parameter shovel my-shovel \
  '{
    "src-uri": "amqp://user:pass@source:5672",
    "src-queue": "my_queue",
    "dest-uri": "amqp://user:pass@dest:5672",
    "dest-queue": "my_queue_backup",
    "ack-mode": "on-confirm",
    "publish-properties": {},
    "publish-interval": 10000
  }'
```

### 10. TLS для межузлового и клиентского подключения

```ini
# /etc/rabbitmq/rabbitmq.conf

# Слушатели AMQP с TLS
listeners.ssl.default = 5671
ssl_options.cacertfile = /etc/rabbitmq/tls/ca_certificate.pem
ssl_options.certfile = /etc/rabbitmq/tls/server_certificate.pem
ssl_options.keyfile = /etc/rabbitmq/tls/server_key.pem
ssl_options.verify = verify_peer
ssl_options.fail_if_no_peer_cert = true

# Inter-node TLS
ssl_options.inter_node_tls = true
```

### 11. Capacity Planning и sizing

**Правила планирования:**

| Ресурс | Правило | Мониторинг |
|:---|:---|:---|
| **RAM** | 1 ГБ на 10,000 queued messages (зависит от размера) | `rabbitmqctl status` → `mem_used` |
| **Disk** | Включить `disk_free_limit` (по умолчанию 1 ГБ) | `rabbitmqctl status` → `disk_free` |
| **Connections** | Каждое соединение = ~1 МБ | `rabbitmqctl list_connections` |
| **Queues** | Не более 1000 queues на ноду (зависит от RAM) | `rabbitmqctl list_queues name messages` |

**Рекомендации:**
- Для high-load: используйте SSD/NVMe для `/var/lib/rabbitmq`
- Отдельный диск для логов (`/var/log/rabbitmq`)
- `vm_memory_high_watermark.relative = 0.4` (40% RAM) для production
- `disk_free_limit.absolute = 2GB` минимум

### 12. Структура каталогов и дисковая подсистема

```bash
# Директории по умолчанию
/var/lib/rabbitmq/   # Данные (mnesia, quorum, stream, indices)
/var/log/rabbitmq/   # Логи
/etc/rabbitmq/       # Конфигурация (rabbitmq.conf, advanced.config)
/run/rabbitmq/       # PID и runtime файлы
```

**Для production рекомендуется:**
- Отдельный раздел/диск для `/var/lib/rabbitmq`
- Отдельный раздел/диск для `/var/log/rabbitmq`
- `noatime` и `nodiratime` в fstab для дисковой подсистемы
- XFS или ext4 с `inode64` для больших файлов

### 13. Disaster Recovery

**Сценарий: потеря всего кластера**

1. **Создайте новый кластер** из 3+ узлов.
2. **Восстановите метаданные** из бэкапа:
   ```bash
   sudo rabbitmqctl import_definitions /backup/rabbitmq_definitions.json
   ```
3. **Восстановите очереди** (если был snapshot):
   ```bash
   sudo systemctl stop rabbitmq-server
   sudo tar -xzf /backup/rabbitmq-backup.tar.gz -C /var/lib/rabbitmq/
   sudo systemctl start rabbitmq-server
   ```
4. **Перенастройте клиентов** на новый кластер.
5. **Восстановите Shovel/Federation** для репликации из primary.

**Для минимизации потерь:**
- Регулярный экспорт `definitions` (ежедневно через cron).
- Непрерывная репликация через Shovel/Federation.
- Хранение snapshot'ов Quorum Queues на выключенных узлах.

## Устранение неполадок (Troubleshooting)

### Проблема 1: Узел не присоединяется к кластеру

**Симптомы:** `rabbitmqctl cluster_status` показывает узел в статусе `down` или `running_nodes` содержит только текущий узел.

**Диагностика:**
```bash
# Проверить Erlang cookie
sudo diff /var/lib/rabbitmq/.erlang.cookie /var/lib/rabbitmq/.erlang.cookie

# Проверить сетевую связность
nc -zv node2 4369
nc -zv node2 25672

# Проверить логи
sudo journalctl -u rabbitmq-server -n 50 --no-pager
```

**Решение:**
- Убедитесь, что cookie идентичен на всех узлах (MD5-сумма).
- Откройте порты 4369 (epmd) и 25672 (inter-node) в файрволе.
- Проверьте, что hostname разрешается в IP на всех узлах.

### Проблема 2: Нет лидера кворума (no quorum)

**Симптомы:** Очереди недоступны, `rabbitmq-diagnostics quorum_queues` показывает `no_quorum` для некоторых очередей.

**Диагностика:**
```bash
sudo rabbitmq-diagnostics quorum_queues
# → Ожидаемый вывод: status = "no_quorum" или "running"
```

**Решение:**
- Восстановите недостающий узел (перезагрузка, исправление сети).
- Если узел потерян навсегда, используйте `rabbitmqctl forget_cluster_node` на живых узлах для удаления мертвого узла из Raft-группы.

### Проблема 3: Высокое потребление памяти (Memory Pressure)

**Симптомы:** Брокер блокирует публикации, логи содержат `memory limit exceeded`.

**Диагностика:**
```bash
sudo rabbitmq-diagnostics memory_breakdown
# → Смотрите на: messaging, indices, metadata, binary
```

**Решение:**
- Увеличьте `vm_memory_high_watermark` в `/etc/rabbitmq/rabbitmq.conf` (по умолчанию 0.4 = 40% RAM).
- Добавьте больше узлов или увеличьте RAM на существующих.
- Проверьте, есть ли утечки сообщений (неподтвержденные сообщения в очереди).

### Проблема 4: Медленная репликация Quorum Queues

**Симптомы:** Очереди на разных узлах отстают друг от друга.

**Диагностика:**
```bash
sudo rabbitmq-diagnostics quorum_queues
# → Смотрите на: online, offline, syncing
```

**Решение:**
- Увеличьте `ha-sync-batch-size` в политике (по умолчанию 10 000 сообщений за батч).
- Проверьте сетевую пропускную способность между узлами.
- Используйте SSD для `/var/lib/rabbitmq` — синхронизация интенсивно пишет на диск.

### Проблема 5: Split-Brain / Network Partition

**Симптомы:** Логи содержат `network partition detected`, кластер разделился на части.

**Диагностика:**
```bash
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

### Проблема 6: Утечка файловых дескрипторов

**Симптомы:** Брокер перестает принимать подключения, логи содержат `too many open files` или `emfile`.

**Диагностика:**
```bash
# Проверить лимит для процесса beam.smp
cat /proc/$(pgrep -f beam.smp)/limits | grep "open files"

# Проверить текущее количество открытых FD
sudo lsof -p $(pgrep -f beam.smp) | wc -l
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

## Масштабирование RabbitMQ

### Стратегии масштабирования

**1. Горизонтальное масштабирование:**
- Добавление узлов в кластер
- Использование Quorum Queues для автоматической репликации
- Federation/Shovel для межкластерной связи

**2. Вертикальное масштабирование:**
- Увеличение RAM на существующих узлах
- Использование SSD/NVMe для дисковой подсистемы
- Оптимизация Erlang-процессов

**3. Масштабирование через Streams:**
- Высокий throughput для append-only данных
- Pull-модель для масштабирования consumer'ов
- Повторное чтение (replay) для аналитики

### Рекомендации по масштабированию

- **Кворумные очереди** для HA и отказоустойчивости
- **Federation** для disaster recovery и geo-распределения
- **Streams** для аналитики и high-throughput сценариев
- **HAProxy** для балансировки клиентских подключений

## Стратегии обновления RabbitMQ

### Rolling Update (поэтапное обновление)

```bash
# 1. Остановить один узел
rabbitmqctl stop_app
systemctl stop rabbitmq-server

# 2. Обновить пакет
apt install --only-upgrade rabbitmq-server

# 3. Запустить узел
systemctl start rabbitmq-server
rabbitmqctl await_startup
rabbitmqctl start_app

# 4. Проверить кластер
rabbitmqctl cluster_status

# 5. Повторить для остальных узлов
```

**Важно:** При обновлении с 3.x на 4.0 проверьте совместимость клиентских библиотек и обновите политики на Quorum Queues (зеркалирование классических очередей удалено).

### Blue-Green Upgrade (сине-зеленое обновление)

1. Разверните новый кластер с обновленной версией
2. Настройте Federation/Shovel для репликации данных
3. Переключите клиентов на новый кластер
4. Остановите старый кластер

### Подготовка к обновлению

```bash
# Экспорт определений перед обновлением
rabbitmqctl export_definitions /backup/rabbitmq_$(date +%F).json

# Проверка совместимости
rabbitmqctl status | grep rabbitmq_version

# Проверка feature flags
rabbitmq-upgrade list-features
```

## Disaster Recovery (восстановление после сбоев)

### План DR

1. **Бэкапы:** Ежедневный экспорт `definitions` через cron
2. **Репликация:** Federation/Shovel для межкластерной связи
3. **Snapshots:** Резервное копирование Quorum Queues
4. **Тестирование:** Регулярная проверка восстановления

### Команды для DR

```bash
# Экспорт определений (пользователи, vhosts, политики)
rabbitmqctl export_definitions /backup/rabbitmq_definitions.json

# Импорт определений
rabbitmqctl import_definitions /backup/rabbitmq_definitions.json

# Бэкап Quorum Queues (на остановленном узле)
systemctl stop rabbitmq-server
tar -czf /backup/rabbitmq_quorum_$(date +%F).tar.gz /var/lib/rabbitmq/quorum/
systemctl start rabbitmq-server
```

### Восстановление после потери кластера

1. Создайте новый кластер из 3+ узлов
2. Восстановите метаданные из бэкапа
3. Восстановите очереди (если был snapshot)
4. Перенастройте клиентов на новый кластер
5. Восстановите Federation/Shovel для репликации

## Дополнительная информация

### См. также

- **[Обзор RabbitMQ](./overview.md)** — базовые концепции, гарантии доставки.
- **[Сравнение RabbitMQ и Kafka](../Kafka/rabbitmq_vs_kafka.md)** — когда выбирать RabbitMQ, а когда Kafka.
- **[Гарантии доставки](../Kafka/delivery_guarantees.md)** — семантики At-least-once, Exactly-once.
- **[Принципы работы очередей](../Kafka/message_queues_principles.md)** — общие концепции.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — метрики, Prometheus, Grafana, алерты.
- **[Устранение неполадок](./troubleshooting.md)** — подробные сценарии диагностики.
- **[Планирование мощности](../Concepts/capacity-planning.md)** — расчет ресурсов.
- **[Безопасность](./security.md)** — ACL, SASL, LDAP, OAuth, TLS.
- **[CLI-команды](./cli_reference.md)** — справочник всех CLI-инструментов.
- **[Балансировка нагрузки](./load_balancing.md)** — HAProxy, DNS round-robin.
- **[Конфигурация](./configuration_reference.md)** — справочник параметров.


### Лучшие практики

1. **Всегда используйте Quorum Queues** (не классические mirror queues) в production.
2. **Настраивайте префетч (prefetch count)** для консьюмеров, чтобы избежать неравномерного распределения нагрузки.
3. **Используйте Publisher Confirms** для гарантии приема сообщения брокером.
4. **Мониторите память:** RabbitMQ блокирует публикации при превышении `vm_memory_high_watermark`.
5. **Разделяйте vhosts** по средам (dev/staging/prod) или командам.
6. **Храните сообщения ≤1 MiB** — большие сообщения снижают пропускную способность в 10-100 раз.
7. **Настраивайте `cluster_partition_handling`** при развертывании в WAN — `pause_minority` предотвращает Split-Brain.
8. **Используйте отдельный диск** для `/var/lib/rabbitmq` и `/var/log/rabbitmq` — предотвращает взаимоблокировки при заполнении диска.
9. **Настраивайте NTP** на всех узлах — Khepri/Raft чувствителен к рассинхронизации времени.
10. **Экспортируйте definitions регулярно** — автоматический cron для `rabbitmqctl export_definitions`.
11. **Тестируйте Rolling Upgrade** в staging перед production — проверяйте совместимость клиентских библиотек.
12. **Ограничьте количество очередей на узел** — не более 1000 queues на ноду для стабильной работы.
