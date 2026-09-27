# RabbitMQ: Плагины (Plugins)

## Определения

- **Плагин (Plugin):** Расширение функциональности RabbitMQ, добавляющее новые протоколы, обменники, аутентификацию, мониторинг или другие возможности.
- **Management Plugin:** Официальный плагин, предоставляющий HTTP API (порт 15672) и веб-интерфейс для управления брокером.
- **Prometheus Plugin:** Плагин `rabbitmq_prometheus`, экспортирующий метрики в формате Prometheus (порт 15692).
- **Federation Plugin:** Плагин для передачи сообщений между кластерами через WAN.
- **Shovel Plugin:** Плагин для надежного копирования сообщений между брокерами.
- **Delayed Message Exchange:** Плагин для отложенной доставки сообщений (аналог Kafka延迟队列).
- **Consistent Hash Exchange:** Плагин для маршрутизации по хешу ключа (для балансировки нагрузки).
- **Auth Backend LDAP:** Плагин для аутентификации через LDAP.
- **Auth Mechanism OAuth2:** Плагин для аутентификации через OAuth 2.0 JWT-токены.

## Управление плагинами

### Базовые команды

```bash
# Список всех плагинов
sudo rabbitmq-plugins list

# Список только включенных
sudo rabbitmq-plugins list -e

# Список только отключенных
sudo rabbitmq-plugins list -d

# Включение плагина
sudo rabbitmq-plugins enable rabbitmq_management

# Отключение плагина
sudo rabbitmq-plugins disable rabbitmq_management

# Включение нескольких плагинов
sudo rabbitmq-plugins enable rabbitmq_management rabbitmq_prometheus

# Проверка зависимостей
sudo rabbitmq-plugins list --verbose

# Offline режим (для обновлений)
sudo rabbitmq-plugins disable --offline <plugin>
```

## Основные плагины

### 1. Management Plugin

```bash
# Включение
sudo rabbitmq-plugins enable rabbitmq_management

# Порты
# 15672 — HTTP API и UI
# 15670 — HTTPS (если настроен)

# Доступ
# http://localhost:15672/
# Логин: guest / guest (только localhost)

# Настройка в rabbitmq.conf
management.tcp.port = 15672
management.tcp.ip = 127.0.0.1
management.http.log = true
management.rates_mode = basic
```

### 2. Prometheus Plugin

```bash
# Включение
sudo rabbitmq-plugins enable rabbitmq_prometheus

# Порт
# 15692 — метрики Prometheus

# Доступ
# http://localhost:15692/metrics

# Конфигурация в rabbitmq.conf
prometheus.return_per_object_metrics = false
prometheus.tcp.port = 15692
```

### 3. Federation Plugin

```bash
# Включение
sudo rabbitmq-plugins enable rabbitmq_federation

# Настройка upstream (межкластерная связь)
sudo rabbitmqctl set_parameter federation-upstream my-upstream \
  '{"uri":"amqp://user:pass@downstream:5672","expires":3600000}'

# Применение к обменнику
sudo rabbitmqctl set_policy \
  --apply-to exchanges \
  federate-me "^federated\." \
  '{"federation-upstream-set":"all"}'

# Проверка статуса
sudo rabbitmq-diagnostics federation_status
```

### 4. Shovel Plugin

```bash
# Включение
sudo rabbitmq-plugins enable rabbitmq_shovel

# Создание Shovel (из очереди в очередь)
sudo rabbitmqctl set_parameter shovel my-shovel \
  '{
    "src-uri": "amqp://user:pass@source:5672",
    "src-queue": "my_queue",
    "dest-uri": "amqp://user:pass@dest:5672",
    "dest-queue": "my_queue_backup",
    "ack-mode": "on-confirm",
    "publish-interval": 10000
  }'

# Создание Shovel (из exchange в exchange)
sudo rabbitmqctl set_parameter shovel exchange-shovel \
  '{
    "src-uri": "amqp://source",
    "src-exchange": "source_exchange",
    "dest-uri": "amqp://dest",
    "dest-exchange": "dest_exchange",
    "ack-mode": "on-confirm"
  }'
```

### 5. Delayed Message Exchange

```bash
# Включение
sudo rabbitmq-plugins enable rabbitmq_delayed_message_exchange

# Создание обменника с задержкой
sudo rabbitmqadmin declare exchange name=delayed_exchange \
  type=x-delayed-message \
  arguments='{"x-delayed-type":"direct","x-delayed-message":true}'

# Публикация с задержкой (в миллисекундах)
sudo rabbitmqadmin publish routing_key=delayed_exchange \
  payload='{"task":"process"}' \
  arguments='{"x-delay":30000}'  # 30 секунд задержки
```

### 6. Consistent Hash Exchange

```bash
# Включение
sudo rabbitmq-plugins enable rabbitmq_consistent_hash_exchange

# Создание обменника
sudo rabbitmqadmin declare exchange name=hash_exchange \
  type=x-consistent-hash

# Биндинг очередей с весами
sudo rabbitmqadmin declare binding source=hash_exchange \
  destination=queue1 routing_key="1"
sudo rabbitmqadmin declare binding source=hash_exchange \
  destination=queue2 routing_key="2"

# Маршрутизация по хешу ключа
sudo rabbitmqadmin publish routing_key=hash_exchange \
  payload='order-123'
```

### 7. Auth Backend LDAP

```bash
# Включение
sudo rabbitmq-plugins enable rabbitmq_auth_backend_ldap

# Конфигурация в rabbitmq.conf
auth_ldap.enabled = true
auth_ldap.servers.1 = ldap://ldap.example.com
auth_ldap.user_dn_pattern = ou=users,dc=example,dc=com
auth_ldap.bind_dn = cn=admin,dc=example,dc=com
auth_ldap.bind_password = password
auth_ldap.use_ssl = true
auth_ldap.port = 636
```

### 8. Auth Mechanism OAuth2

```bash
# Включение
sudo rabbitmq-plugins enable rabbitmq_auth_mechanism_oauth2

# Конфигурация
auth_mechanisms.1 = OAUTHBEARER
auth_oauth2.jwks_url = https://auth.example.com/.well-known/jwks.json
auth_oauth2.issuer = https://auth.example.com
auth_oauth2.audience = rabbitmq
```

### 9. Management Visualizer

```bash
# Включение (визуализация топологии)
sudo rabbitmq-plugins enable rabbitmq_management_visualizer

# Доступ
# http://localhost:15672/#/connections
# Вкладка "Visualizer"
```

### 10. Web STOMP

```bash
# Включение (STOMP через WebSocket)
sudo rabbitmq-plugins enable rabbitmq_web_stomp

# Порт
# 15674 — WebSocket STOMP

# Доступ
# ws://localhost:15674/ws
```

### 11. Web MQTT

```bash
# Включение (MQTT через WebSocket)
sudo rabbitmq-plugins enable rabbitmq_web_mqtt

# Порт
# 15675 — WebSocket MQTT
```

## Мониторинг плагинов

```bash
# Проверка включенных плагинов
sudo rabbitmq-plugins list -e

# Проверка портов плагинов
sudo rabbitmq-diagnostics ports
# → 15672 (management), 15692 (prometheus), 5672 (amqp)

# Проверка через Management API
curl -s -u guest:guest http://localhost:15672/api/overview | \
  jq '.rabbitmq_version, .erlang_version'

# Проверка плагинов через rabbitmqctl
sudo rabbitmqctl status | grep -A 5 "plugins"
```

## Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| Plugin not found | Плагин не установлен | Установите пакет `rabbitmq-<plugin>` |
| Dependency error | Не установлена зависимость | `rabbitmq-plugins list --verbose` проверьте зависимости |
| Port conflict | Порт уже занят | Измените порт в `rabbitmq.conf` |
| Auth failed | Неверные credentials | Проверьте конфигурацию LDAP/OAuth |
| Federation not working | Нет connectivity | Проверьте firewall и DNS |

## Лучшие практики

1. **Включайте только необходимые плагины** — каждый плагин потребляет ресурсы.
2. **Используйте Prometheus для метрик** — стандарт для мониторинга.
3. **Настройте Federation/Shovel** для DR — межкластерная репликация.
4. **Используйте Delayed Message Exchange** для scheduled tasks — проще, чем cron.
5. **Включайте Management UI** только в dev/staging — в production через reverse proxy.
6. **Используйте LDAP/OAuth** для enterprise — централизованное управление доступом.
7. **Регулярно обновляйте плагины** — совместимость с версией RabbitMQ.
8. **Тестируйте плагины в staging** — перед production развертыванием.

## Дополнительная информация

### См. также

- **[Обзор RabbitMQ](./overview.md)** — базовые концепции.
- **[Безопасность](./security.md)** — LDAP, OAuth2 аутентификация.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — Prometheus плагин.
- **[Установка и кластеризация](./installation_and_clustering.md)** — Federation, Shovel.
