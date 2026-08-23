# Upgrades и миграция Elastic Stack

> Руководство по обновлению версий и миграции данных в Elastic Stack. Рассматриваются rolling upgrades, Blue-Green деплой и version compatibility.
>
> Связанные темы: установка кластера — [Cluster Setup](../Tutorials/cluster_setup.md); бэкапы — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md).

## Определения

* **Rolling Upgrade** — последовательное обновление узлов кластера без downtime.
* **Full Cluster Restart** — обновление с downtime (все узлы останавливаются).
* **Blue-Green Deployment** — создание параллельного кластера новой версии.
* **Version Compatibility** — правила совместимости между версиями компонентов.
* **Migration Assistant** — инструмент Kibana для проверки готовности к обновлению.
* **Deprecated Features** — функции, которые будут удалены в следующей major version.

## Version Compatibility Rules

### Elasticsearch и Kibana

| Версия | Совместимость |
|--------|---------------|
| Major | Должна совпадать (8.x ↔ 8.x) |
| Minor | Kibana ≥ Elasticsearch |
| Patch | Любая |

### Beats и Logstash

| Компонент | Совместимость с ES |
|-----------|-------------------|
| Beats | Beats major ≤ ES major |
| Logstash | Logstash major ≤ ES major |

### Примеры

```
✅ ES 8.15 + Kibana 8.15 (OK)
✅ ES 8.15 + Kibana 8.16 (OK, Kibana newer)
❌ ES 8.15 + Kibana 9.15 (FAIL, different major)
✅ ES 8.15 + Beats 8.15 (OK)
✅ ES 8.15 + Beats 8.14 (OK, Beats older)
❌ ES 8.15 + Beats 9.0 (FAIL)
```

## Rolling Upgrade Elasticsearch

### Предварительные проверки

```bash
# Проверка готовности
GET /_migration/system_features

# Проверка deprecated features
GET /_migration/deprecations

# Статус кластера (должен быть green)
GET /_cluster/health
```

### Шаги Rolling Upgrade

```
1. Отключить shard allocation
2. Остановить не-essential индексацию
3. Обновить один узел
4. Запустить узел, дождаться присоединения
5. Включить shard allocation
6. Дождаться recovery
7. Повторить для следующего узла
```

### Детальный процесс

```bash
# 1. Отключить shard allocation
PUT /_cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.enable": "primaries"
  }
}

# 2. Синхронизированный flush (опционально)
POST /_flush/synced

# 3. Остановить узел
sudo systemctl stop elasticsearch

# 4. Обновить пакет
sudo apt update && sudo apt install elasticsearch

# 5. Обновить конфигурацию (если нужны изменения)
sudo vim /etc/elasticsearch/elasticsearch.yml

# 6. Запустить узел
sudo systemctl start elasticsearch

# 7. Проверить присоединение
GET /_cat/nodes?v

# 8. Включить shard allocation
PUT /_cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.enable": null
  }
}

# 9. Дождаться green
GET /_cluster/health?wait_for_status=green&timeout=300s

# 10. Повторить для следующего узла
```

### Важные моменты

1. **Master-eligible узлы обновляйте последними** — или по одному с интервалом
2. **Data nodes** можно обновлять параллельно (если replicas ≥ 1)
3. **Не обновляйте быстрее 1 узла в минуту** — дождитесь recovery
4. **Следите за shard allocation** — если unassigned > 0, приостановитесь

## Blue-Green Deployment

### Когда использовать

- Major version upgrade (8.x → 9.x)
- Большие изменения в конфигурации
- Нельзя допустить downtime
- Требуется rollback

### Архитектура

```
Blue Cluster (current)          Green Cluster (new)
├── ES 8.x                      ├── ES 9.x
├── Active                      ├── Standby
├── Receives traffic            ├── Receiving replicated data
└── Old Kibana                  └── New Kibana
```

### Процесс

```
1. Deploy Green Cluster (new version)
2. Setup CCR с Blue на Green (опционально)
3. Reindex из Blue в Green
4. Verify data integrity
5. Switch traffic to Green
6. Keep Blue for rollback (24-48h)
7. Decommission Blue
```

### Reindex при миграции

```bash
# Reindex в новый кластер
POST _reindex?wait_for_completion=false
{
  "source": {
    "remote": {
      "host": "https://blue-cluster:9200",
      "username": "reindex",
      "password": "${REINDEX_PASSWORD}"
    },
    "index": "logs-*"
  },
  "dest": {
    "index": "logs-new",
    "op_type": "create"
  }
}
```

## Обновление Kibana

### Rolling Update (для кластера Kibana)

```bash
# Обновить один инстанс
sudo apt update && sudo apt install kibana

# Перезапустить
sudo systemctl restart kibana
```

### Standalone Kibana

```bash
# Остановить
sudo systemctl stop kibana

# Обновить
sudo apt update && sudo apt install kibana

# Перезапустить
sudo systemctl start kibana
```

**Важно:** Kibana не может быть новее Elasticsearch на major version.

## Обновление Beats

```bash
# Остановить Beat
sudo systemctl stop metricbeat

# Обновить
sudo apt update && sudo apt install metricbeat

# Загрузить новые dashboards (если нужно)
metricbeat setup -e

# Перезапустить
sudo systemctl start metricbeat
```

## Обновление Logstash

### Rolling Update (для кластера)

```bash
# Остановить один узел
sudo systemctl stop logstash

# Обновить
sudo apt update && sudo apt install logstash

# Перезапустить
sudo systemctl start logstash
```

### С PQ (Persistent Queue)

PQ сохраняет данные на диск, поэтому обновление безопасно — данные не теряются.

### Без PQ

1. Остановить input (Filebeat, Kafka)
2. Дождаться опустошения pipeline
3. Остановить Logstash
4. Обновить
5. Запустить
6. Включить input

## Migration Assistant

### Использование в Kibana

1. **Stack Management > Upgrade Assistant**
2. Проверить readiness
3. Просмотреть deprecated features
4. Получить upgrade recommendations

### Проверка готовности

```bash
GET /_migration/system_features
```

Ответ:
```json
{
  "available_features": [
    {
      "name": "security",
      "enabled": true
    }
  ],
  "compatible": true
}
```

### Deprecated Features

```bash
GET /_migration/deprecations
```

Ответ:
```json
{
  "cluster_settings": [...],
  "index_settings": [...],
  "machine_learning_settings": [...]
}
```

## Pre-Upgrade Checklist

### Перед Upgrade

- [ ] Проверить version compatibility
- [ ] Проверить deprecated features (`/_migration/deprecations`)
- [ ] Создать snapshot
- [ ] Проверить cluster health (green)
- [ ] Проверить плагины на совместимость
- [ ] Проверить кастомные скрипты (Painless)
- [ ] Протестировать на staging
- [ ] Подготовить rollback plan
- [ ] Уведомить stakeholders

### После Upgrade

- [ ] Проверить cluster health
- [ ] Проверить shard allocation
- [ ] Проверить индексацию (indexing rate)
- [ ] Проверить поиск (search latency)
- [ ] Проверить dashboards и alerts
- [ ] Мониторить 24-48 часов

## Rollback

### Rolling Upgrade Rollback

```
1. Отключить shard allocation
2. Остановить upgraded узлы
3. Откатить пакеты на предыдущую версию
4. Запустить узлы
5. Включить shard allocation
```

**Важно:** Rollback возможен только в пределах одной major version (8.15 → 8.14).

### Blue-Green Rollback

```
1. Switch traffic back to Blue
2. Удалить Green
3. Расследовать причину неудачи
```

## Common Issues

### Shard Allocation Failed после upgrade

```
Причина: Несовместимость формата shard data
Решение: Не откатывать на major version назад
```

### Kibana не подключается к ES после upgrade

```
Причина: Версии несовместимы
Решение: Обновить Kibana до совместимой версии
```

### Slow queries после upgrade

```
Причина: Изменения в query engine
Решение: Перестроить индексы, проверить fielddata
```

### Plugins не работают

```
Причина: Плагин не совместим с новой версией
Решение: Обновить плагин или удалить
```

## Best Practices

1. **Всегда тестируйте на staging** — перед production upgrade
2. **Создавайте snapshot** — перед каждым upgrade
3. **Rolling upgrade для minor/patch** — без downtime
4. **Blue-Green для major** — безопасный rollback
5. **Обновляйте по одному компоненту** — ES → Kibana → Beats → Logstash
6. **Мониторьте после upgrade** — 24-48 часов
7. **Документируйте изменения** — конфигурации, плагины
8. **Следите за EOL** — не откладывайте upgrade

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура и роли узлов.
* **[ECK: Elastic Cloud on Kubernetes](../elastic_cloud_on_k8s.md)** — upgrade в Kubernetes.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — snapshots для backup.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — мониторинг после upgrade.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты и протоколы.
* **[OpenSearch: Обзор](../OpenSearch/opensearch_overview.md)** — миграция на OpenSearch.
