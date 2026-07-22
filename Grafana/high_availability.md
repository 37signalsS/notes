# Grafana: Высокая доступность

## Определения

**Высокая доступность (High Availability, HA)** в контексте Grafana — архитектурный подход, обеспечивающий бесперебойную работу системы мониторинга при отказе одного или нескольких узлов. Реализуется через развертывание нескольких stateless-экземпляров приложения за балансировщиком нагрузки с использованием внешних хранилищ состояния (БД, Redis).

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Провиженинг](./grafana_provisioning.md) — автоматизация конфигурации в HA
- [Обзор High Availability](../Concepts/High_Availability/ha_overview.md) — общие принципы отказоустойчивости

## Базовые концепции

### Архитектура HA в Grafana 13.x

Современная архитектура HA Grafana опирается на три столпа: общая база данных, внешнее хранилище сессий и межсерверная коммуникация для алертинга.

1. **Внешняя БД (Configuration Storage):** PostgreSQL или MySQL для хранения дашбордов, пользователей и настроек. SQLite в HA не поддерживается.
2. **Remote Cache / Session Storage:** Использование Redis для хранения сессий пользователей и временных данных. Это позволяет избежать зависимости от «липких сессий» (Sticky Sessions) на балансировщике.
3. **Alerting HA (Gossip Protocol):** Узлы обмениваются состоянием алертов через Memberlist (порт 9094) для предотвращения дублирования уведомлений.

### Ключевые компоненты

| Компонент | Назначение | Рекомендация |
| :--- | :--- | :--- |
| **Load Balancer** | L7-балансировка (HTTP/HTTPS) | Nginx, HAProxy, AWS ALB |
| **Grafana Nodes** | 2 или более идентичных узла | Минимум 3 для кворума в алертинге |
| **Shared Database** | Основное хранилище настроек | PostgreSQL 16+ (Patroni) |
| **Redis** | Хранение сессий и кэширование | Redis Cluster или Sentinel |

## Практические сценарии

### Конфигурация HA (grafana.ini)

Для корректной работы кластера необходимо синхронизировать настройки безопасности и подключить внешние хранилища.

```ini
[database]
type = postgres
host = postgres-ha-proxy:5432
name = grafana
user = grafana_user
password = grafana_password
# Включает распределенные блокировки для фоновых задач
high_availability = true

[remote_cache]
# Рекомендуется для HA вместо базы данных
type = redis
connstr = addr=redis-ha-proxy:6379,pool_size=100,db=0

[session]
# Использование Redis для сессий позволяет балансировщику работать в режиме Round Robin
provider = redis
provider_config = addr=redis-ha-proxy:6379,pool_size=100,prefix=grafana_sess

[security]
# КЛЮЧЕВОЙ ПАРАМЕТР: должен быть идентичен на всех узлах
secret_key = <your_random_long_string>
```

### Настройка Unified Alerting HA

В версии 13.x Grafana использует Gossip-протокол для дедупликации уведомлений.

**Настройка через Memberlist:**
Каждый узел должен знать о соседях. В Kubernetes это обычно решается через headless service.
```ini
[unified_alerting]
enabled = true
# Список IP или DNS-имен других узлов кластера
ha_peers = grafana-node-1:9094, grafana-node-2:9094
ha_listen_address = 0.0.0.0:9094

# Новинка v13: Single-node Evaluation
# Снижает нагрузку на Prometheus, вычисляя алерты только на одном (primary) узле
ha_evaluation_mode = single-node
```

**Примечание по сети:** Убедитесь, что порт **9094 (TCP и UDP)** открыт между всеми узлами Grafana.

### Развертывание в Docker Compose (HA-стек)

```yaml
services:
  grafana-1: &grafana_base
    image: grafana/grafana:13.1.1
    environment:
      - GF_DATABASE_TYPE=postgres
      - GF_DATABASE_HOST=postgres:5432
      - GF_REMOTE_CACHE_TYPE=redis
      - GF_REMOTE_CACHE_CONNSTR=addr=redis:6379
      - GF_SECURITY_SECRET_KEY=secret_123
      - GF_UNIFIED_ALERTING_HA_PEERS=grafana-2:9094
    ports: [ "3001:3000", "9094:9094" ]

  grafana-2:
    <<: *grafana_base
    environment:
      - GF_DATABASE_TYPE=postgres
      - GF_DATABASE_HOST=postgres:5432
      - GF_REMOTE_CACHE_TYPE=redis
      - GF_REMOTE_CACHE_CONNSTR=addr=redis:6379
      - GF_SECURITY_SECRET_KEY=secret_123
      - GF_UNIFIED_ALERTING_HA_PEERS=grafana-1:9094
    ports: [ "3002:3000", "9095:9094" ]

  postgres:
    image: postgres:16
    environment:
      - POSTGRES_DB=grafana
      - POSTGRES_USER=grafana_user
      - POSTGRES_PASSWORD=grafana_password

  redis:
    image: redis:7-alpine
```

## Дополнительная информация

### Рекомендации по эксплуатации

- **Синхронизация времени:** Используйте NTP. Разница во времени между узлами > 500мс приведет к дублированию алертов.
- **Sticky Sessions:** При использовании Redis для сессий липкие сессии **не обязательны**, но рекомендуются для оптимизации работы Grafana Live (WebSockets).
- **База данных:** PostgreSQL является критической точкой отказа. Используйте **Patroni** для обеспечения HA на уровне СУБД.
- **Изоляция:** Если Grafana используется для критических алертов, не перегружайте ее тяжелыми ad-hoc запросами.

### Контрольный список (HA Checklist)

- [ ] Идентичный `secret_key` на всех узлах.
- [ ] Внешняя БД в отказоустойчивом режиме.
- [ ] Redis подключен для сессий и кэша.
- [ ] Порт 9094 открыт (TCP/UDP) для Alerting HA.
- [ ] Настроены Health Checks (`/api/health`) на балансировщике.
- [ ] Все узлы синхронизированы по времени (NTP).

**Ссылки:**
- [Официальная документация Grafana HA](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/high-availability/)
- [Настройка Unified Alerting HA](https://grafana.com/docs/grafana/latest/alerting/set-up/high-availability/)
- [Репозиторий Patroni (PostgreSQL HA)](https://github.com/zalando/patroni)
