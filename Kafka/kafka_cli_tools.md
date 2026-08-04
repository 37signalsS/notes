# CLI-инструменты для работы с Apache Kafka

Для взаимодействия с Apache Kafka из командной строки используются стандартные утилиты, входящие в дистрибутив, а также сторонние решения, такие как `kcat` и `kafkactl`. Они позволяют управлять топиками, читать и отправлять сообщения, а также диагностировать состояние кластера.

## Определения

- **Kafka CLI (Standard)**: Набор shell-скриптов (оберток над Java-приложениями), поставляемых с Kafka. Требуют наличия JVM.
- **kcat (ранее kafkacat)**: Легковесный не-Java инструмент (на базе `librdkafka`) для потоковой передачи данных в Kafka.
- **kafkactl**: Современный CLI-инструмент с интерфейсом в стиле `kubectl`, ориентированный на удобное управление несколькими кластерами через конфигурационные файлы и контексты.
- **Контекст (Context)**: Именованный набор параметров подключения (брокеры, аутентификация, сертификаты) в `kafkactl`.

## Базовые концепции

### Сравнение инструментов

| Критерий | Стандартные утилиты | kcat | kafkactl |
| :--- | :--- | :--- | :--- |
| **Зависимости** | JVM (Java) | `librdkafka` | Статический бинарный файл |
| **Синтаксис** | Разные утилиты под задачи | Флаги (`-C`, `-P`, `-L`) | Действие + Объект (`get topics`) |
| **Конфигурация** | Параметры в каждой команде | Параметры в командной строке | YAML-конфиг с контекстами |
| **Удобство** | Низкое (длинные команды) | Высокое для пайплайнов | Высокое для регулярной работы |
| **Consumer Groups** | Полная поддержка | Ограниченно | Полная поддержка + визуализация |

### Архитектура подключения kafkactl

`kafkactl` использует конфигурационный файл `config.yml` (обычно в `~/.config/kafkactl/`), что избавляет от необходимости передавать параметры подключения при каждом вызове.

**Иерархия конфигурации:**
1. **Локальный конфиг**: `kafkactl.yml` в корне проекта (рядом с `.git`).
2. **Глобальный конфиг**: Пользовательские настройки в домашней директории.
3. **Переменные окружения**: Переопределение через `${VAR_NAME}` для безопасности (пароли).

## Практические сценарии

### Сценарий 1: Управление топиками

**Стандартные утилиты:**
```bash
# Список топиков
kafka-topics.sh --bootstrap-server localhost:9092 --list

# Описание топика
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic orders

# Увеличение партиций (партиции можно только добавлять)
kafka-topics.sh --bootstrap-server localhost:9092 --alter --topic orders --partitions 24
```

**kafkactl:**
```bash
# Список топиков
kafkactl get topics

# Детальная информация
kafkactl describe topic orders
```

### Сценарий 2: Отправка и чтение сообщений

**kcat:**
```bash
# Чтение из топика orders
kcat -b localhost:9092 -t orders -C

# Отправка сообщения
echo "message" | kcat -b localhost:9092 -t orders -P
```

**kafkactl:**
```bash
# Чтение с начала
kafkactl consume orders --from-beginning

# Чтение последних N сообщений
kafkactl consume orders --tail 10

# Отправка JSON-сообщения
echo '{"order_id":1001,"status":"created"}' | kafkactl produce orders
```

### Сценарий 3: Работа с Consumer Groups (kafkactl)

Группы потребителей позволяют отслеживать прогресс обработки и распределять нагрузку.

```bash
# Создание группы при чтении
kafkactl consume orders --group orders-service

# Просмотр списка групп
kafkactl get consumer-groups

# Анализ состояния группы (LAG)
kafkactl describe consumer-group orders-service
# → Вывод содержит:
# TOPIC 	PARTITION  NEWEST_OFFSET  CONSUMER_OFFSET  LAG
# orders	0	   1005           1005             0
```
**LAG** — ключевая метрика, показывающая отставание консьюмера от конца топика (разница между `NEWEST_OFFSET` и `CONSUMER_OFFSET`).

### Сценарий 4: Использование в shell-сценариях

`kafkactl` отлично подходит для автоматизации благодаря поддержке стандартного ввода (stdin) и пайплайнов.

```bash
# Отправка содержимого JSON-файла
cat orders.json | kafkactl produce orders

# Генерация тестовой последовательности сообщений
seq 1 5 | while read n; do
  echo "{\"order_id\":$n}" | kafkactl produce orders
done

# Мониторинг новых сообщений в реальном времени (tailing)
kafkactl consume orders --tail 1
```

### Сценарий 5: Настройка kafkactl с TLS/SSL и SASL

Пример `config.yml` для защищенного подключения:

```yaml
contexts:
  prod-cluster:
    brokers:
      - broker-1.example.com:9093
    sasl:
      enabled: true
      mechanism: scram-sha512
      username: my-user
      password: ${KAFKA_PASSWORD}
    tls:
      enabled: true
      ca: /path/to/root.crt
```

**Переключение контекста:**
```bash
# Выбор контекста для команды
kafkactl get topics --context prod-cluster

# Установка текущего контекста (в current-context.yml)
# current-context: prod-cluster
```

## Дополнительная информация

### Выбор инструмента

- **kafkactl**: Идеален для регулярного администрирования, работы с несколькими кластерами и мониторинга групп потребителей.
- **kcat**: Лучший выбор для интеграции в shell-пайплайны (`grep`, `jq`, `awk`) и быстрой диагностики потоков данных.
- **Стандартные утилиты**: Необходимы для специфических административных задач (например, `kafka-reassign-partitions.sh` для перераспределения данных).

**Связанные документы:**
- [Обзор Apache Kafka](./kafka_overview.md)
- [Партиционирование и балансировка](./partitioning_and_balancing.md) — детали работы с разделами.
- [Управление секретами в GitOps](../GitOps/secrets_encryption.md) — для настройки SOPS в конфигурациях.
