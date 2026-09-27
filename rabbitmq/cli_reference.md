# RabbitMQ: Справочник CLI-команд

## Определения

- **rabbitmqctl:** Основной инструмент администрирования RabbitMQ. Управление пользователями, vhosts, политиками, очередями и кластером.
- **rabbitmq-diagnostics:** Инструмент диагностики здоровья брокера. Проверка портов, памяти, кворума, alarms.
- **rabbitmqadmin:** CLI-клиент для HTTP Management API. Создание/удаление ресурсов, публикация сообщений, просмотр статистики.
- **rabbitmq-plugins:** Управление плагинами (включение, отключение, список).
- **rabbitmq-queues:** Управление очередями (в特别是 для Quorum и Stream очередей).
- **rabbitmq-streams:** Управление Stream queues (создание, управление consumer'ами).
- **rabbitmq-upgrade:** Инструменты для обновления RabbitMQ (blue-green upgrade, feature flags).

## Основные команды

### rabbitmqctl — администрирование

```bash
# === Статус и кластер ===

# Общий статус кластера
sudo rabbitmqctl status

# Статус кластера (узлы, партиции, кворум)
sudo rabbitmqctl cluster_status

# Ожидание запуска узла
sudo rabbitmqctl await_startup

# Остановка приложения (без остановки Erlang VM)
sudo rabbitmqctl stop_app

# Запуск приложения
sudo rabbitmqctl start_app

# Сброс узла (удаление данных)
sudo rabbitmqctl reset

# Присоединение к кластеру
sudo rabbitmqctl join_cluster rabbit@node1

# Забыть узел (удаление мертвого узла из кластера)
sudo rabbitmqctl forget_cluster_node rabbit@lost_node --offline

# === Пользователи и vhosts ===

# Создание пользователя
sudo rabbitmqctl add_user <username> <password>

# Удаление пользователя
sudo rabbitmqctl delete_user <username>

# Изменение пароля
sudo rabbitmqctl change_password <username> <new_password>

# Список пользователей
sudo rabbitmqctl list_users

# Установка тегов пользователя
sudo rabbitmqctl set_user_tags <username> <tag1> <tag2>

# Создание vhost
sudo rabbitmqctl add_vhost <vhost_name>

# Удаление vhost
sudo rabbitmqctl delete_vhost <vhost_name>

# Список vhosts
sudo rabbitmqctl list_vhosts

# === Права доступа (ACL) ===

# Установка прав на vhost
sudo rabbitmqctl set_permissions -p <vhost> <user> <configure> <write> <read>

# Просмотр прав на vhost
sudo rabbitmqctl list_permissions -p <vhost>

# Просмотр прав пользователя
sudo rabbitmqctl list_user_permissions <username>

# Установка прав только для одного типа (configure/write/read)
sudo rabbitmqctl set_topic_permissions -p <vhost> <user> <exchange> <write> <read>

# === Очереди ===

# Список очередей
sudo rabbitmqctl list_queues name messages consumers

# Список очередей с деталями
sudo rabbitmqctl list_queues name messages messages_ready messages_unacknowledged consumers memory

# Очистка очереди
sudo rabbitmqctl purge_queue <queue_name>

# Удаление очереди
sudo rabbitmqctl delete_queue <queue_name>

# === Обменники ===

# Список обменников
sudo rabbitmqctl list_exchanges name type durable auto_delete

# Удаление обменника
sudo rabbitmqctl delete_exchange <exchange_name>

# === Биндинги ===

# Список биндингов
sudo rabbitmqctl list_bindings source_name destination_name destination_type routing_key

# === Политики ===

# Список политик
sudo rabbitmqctl list_policies

# Установка политики
sudo rabbitmqctl set_policy \
  --priority <priority> \
  --apply-to <queues|exchanges> \
  <name> <pattern> '<definition>'

# Удаление политики
sudo rabbitmqctl clear_policy <name>

# === Параметры ===

# Список параметров
sudo rabbitmqctl list_parameters

# Установка параметра
sudo rabbitmqctl set_parameter <component> <name> '<value>'

# Удаление параметра
sudo rabbitmqctl clear_parameter <component> <name>

# === Environment ===

# Просмотр конфигурации
sudo rabbitmqctl environment

# Просмотр определений (бэкап)
sudo rabbitmqctl export_definitions <file_path>

# Импорт определений
sudo rabbitmqctl import_definitions <file_path>

# === Оценка Erlang-выражений ===

# Выполнение Erlang-выражения
sudo rabbitmqctl eval 'application:get_env(rabbit, vm_memory_high_watermark).'
```

### rabbitmq-diagnostics — диагностика

```bash
# === Здоровье ===

# Общая проверка здоровья
sudo rabbitmq-diagnostics health_check

# Проверка запущенного состояния
sudo rabbitmq-diagnostics check_running

# Проверка alarms
sudo rabbitmq-diagnostics check_local_alarms

# Проверка портов и слушателей
sudo rabbitmq-diagnostics check_port_listener <port>

# Проверка TCP-соединения
sudo rabbitmq-diagnostics check_tcp_connectivity <host> <port>

# === Ресурсы ===

# Использование памяти
sudo rabbitmq-diagnostics memory_breakdown

# Открытые файловые дескрипторы
sudo rabbitmq-diagnostics open_file_handles

# Сокеты
sudo rabbitmq-diagnostics sockets

# Erlang-процессы
sudo rabbitmq-diagnostics status | grep erlang_processes

# === Порты ===

# Список слушателей
sudo rabbitmq-diagnostics ports

# Проверка конкретного порта
sudo rabbitmq-diagnostics check_port_listener 5672

# === Кластер ===

# Статус кластера
sudo rabbitmq-diagnostics cluster_status

# Проверка кворума
sudo rabbitmq-diagnostics quorum_queues

# Проверка federation
sudo rabbitmq-diagnostics federation_status

# Проверка connections
sudo rabbitmq-diagnostics connections

# Проверка channels
sudo rabbitmq-diagnostics channels

# === Алерты ===

# Текущие alarms
sudo rabbitmq-diagnostics alarms

# Проверка alarms на кластере
sudo rabbitmq-diagnostics check_cluster_name
```

### rabbitmqadmin — HTTP API клиент

```bash
# === Настройка ===

# Конфигурация подключения
export RABBITMQ_HOST=localhost
export RABBITMQ_PORT=15672
export RABBITMQ_USER=guest
export RABBITMQ_PASSWORD=guest

# Или флаги
rabbitmqadmin -H localhost -P 15672 -u guest -p guest <command>

# === Очереди ===

# Список очередей
rabbitmqadmin list queues name messages consumers

# Создание очереди
rabbitmqadmin declare queue name=tasks durable=true \
  arguments='{"x-max-priority":10}'

# Удаление очереди
rabbitmqadmin delete queue name=tasks

# Очистка очереди
rabbitmqadmin purge queue name=tasks

# === Обменники ===

# Список обменников
rabbitmqadmin list exchanges name type durable

# Создание обменника
rabbitmqadmin declare exchange name=logs type=fanout durable=true

# Удаление обменника
rabbitmqadmin delete exchange name=logs

# === Биндинги ===

# Создание биндинга
rabbitmqadmin declare binding source=logs destination=logs_queue

# Список биндингов
rabbitmqadmin list bindings

# === Публикация сообщений ===

# Публикация сообщения
rabbitmqadmin publish routing_key=tasks payload="Hello World"

# Публикация с properties
rabbitmqadmin publish routing_key=tasks \
  payload='{"task":"process"}' \
  properties='{"content_type":"application/json","delivery_mode":2}'

# === Статистика ===

# Обзор кластера
rabbitmqadmin list overview

# Список подключений
rabbitmqadmin list connections name state channels

# Список каналов
rabbitmqadmin list channels name connection consumer_count

# Список потребителей
rabbitmqadmin list consumers queue_name channel consumer_tag

# === Импорт/экспорт ===

# Экспорт конфигурации
rabbitmqadmin export /tmp/rabbitmq_config.json

# Импорт конфигурации
rabbitmqadmin import /tmp/rabbitmq_config.json
```

### rabbitmq-plugins — управление плагинами

```bash
# Список плагинов
sudo rabbitmq-plugins list

# Включение плагина
sudo rabbitmq-plugins enable rabbitmq_management

# Отключение плагина
sudo rabbitmq-plugins disable rabbitmq_management

# Включение нескольких плагинов
sudo rabbitmq-plugins enable rabbitmq_management rabbitmq_prometheus

# Проверка зависимостей
sudo rabbitmq-plugins list -e  # Только enabled
sudo rabbitmq-plugins list -d  # Только disabled

# Режим offline (для обновления)
sudo rabbitmq-plugins disable --offline <plugin>
```

### rabbitmq-queues — управление очередями

```bash
# Список Quorum очередей
sudo rabbitmq-queues list_quorum_queues

# Добавить узел в кворумную очередь
sudo rabbitmq-queues add_member <queue_name> rabbit@node2

# Удалить узел из кворумной очереди
sudo rabbitmq-queues delete_member <queue_name> rabbit@node2

# Статус кворумной очереди
sudo rabbitmq-queues quorum_status <queue_name>

# Force quorum re-election
sudo rabbitmq-queues force_elect_leader <queue_name>
```

### rabbitmq-streams — управление Streams

```bash
# Список Streams
sudo rabbitmq-streams list_streams

# Информация о Stream
sudo rabbitmq-streams stream_status <stream_name>

# Добавить consumer
sudo rabbitmq-streams add_consumer <stream_name> \
  --offset 0 \
  --consumer \
  --app-id my-app

# Удалить consumer
sudo rabbitmq-streams delete_consumer <stream_name> \
  --consumer my-consumer

# Purge Stream
sudo rabbitmq-streams purge_stream <stream_name>
```

### rabbitmq-upgrade — обновление

```bash
# Проверка готовности к обновлению
sudo rabbitmq-upgrade check

# Blue-green upgrade
sudo rabbitmq-upgrade blue-green

# Включение feature flags
sudo rabbitmq-upgrade enable-features <feature1> <feature2>

# Список доступных feature flags
sudo rabbitmq-upgrade list-features
```

## Шпаргалка: типичные операции

### Ежедневные проверки

```bash
# Статус кластера
sudo rabbitmqctl cluster_status

# Здоровье
sudo rabbitmq-diagnostics health_check

# Alarms
sudo rabbitmq-diagnostics alarms

# Глубина очередей
sudo rabbitmqctl list_queues name messages messages_ready messages_unacknowledged

# Потребители
sudo rabbitmqctl list_queues name consumers

# Подключения
sudo rabbitmqctl list_connections user client_host state
```

### Диагностика проблем

```bash
# Memory breakdown
sudo rabbitmq-diagnostics memory_breakdown

# File descriptors
sudo rabbitmq-diagnostics open_file_handles

# Erlang processes
sudo rabbitmq-diagnostics status | grep erlang_processes

# Quorum status
sudo rabbitmq-diagnostics quorum_queues

# Порты
sudo rabbitmq-diagnostics ports
```

### Управление пользователями

```bash
# Создание пользователя с правами
sudo rabbitmqctl add_user app_user 'password'
sudo rabbitmqctl set_user_tags app_user monitoring
sudo rabbitmqctl set_permissions -p production app_user ".*" ".*" ".*"

# Удаление пользователя
sudo rabbitmqctl delete_user old_user
```

### Backup и восстановление

```bash
# Экспорт определений
sudo rabbitmqctl export_definitions /backup/rabbitmq_$(date +%F).json

# Импорт определений
sudo rabbitmqctl import_definitions /backup/rabbitmq_2026-09-21.json
```

## Типичные ошибки CLI

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `nodedown` | Узел недоступен | Проверьте статус сервиса: `systemctl status rabbitmq-server` |
| `access_refused` | Нет прав | Используйте `sudo` или проверьте credentials |
| `timeout` | Долгая операция | Увеличьте `--timeout` или проверьте нагрузку |
| `epmd error` | epmd не запущен | Запустите: `sudo systemctl start epmd` |
| `cluster_error` | Проблемы с кластером | Проверьте `cluster_status` и network connectivity |

## Лучшие практики

1. **Используйте `sudo`** — все команды управления требуют root-привилегий.
2. **Проверяйте `cluster_status`** перед изменениями — убедитесь, что кластер здоров.
3. **Экспортируйте определения** перед обновлениями — `export_definitions`.
4. **Используйте `rabbitmq-diagnostics`** для диагностики — не `rabbitmqctl`.
5. **Для очередей используйте `rabbitmq-queues`** — специализированный инструмент.
6. **Для Streams используйте `rabbitmq-streams`** — специализированный инструмент.
7. **Возвращайте вывод в скриптах** — проверяйте exit code: `rabbitmqctl status || echo "FAILED"`.
8. **Избегайте `reset` в production** — это удаляет все данные.

## Дополнительная информация

### См. также

- **[Обзор RabbitMQ](./overview.md)** — базовые концепции.
- **[Установка и кластеризация](./installation_and_clustering.md)** — кластерные команды.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — метрики и алерты.
- **[Устранение неполадок](./troubleshooting.md)** — диагностика проблем.
