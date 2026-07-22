# Elasticsearch: Жизненный цикл индексов (ILM) и политики хранения

## Определения

* **ILM (Index Lifecycle Management)** — подсистема Elasticsearch для автоматизации управления индексами. Она позволяет минимизировать ручное вмешательство в процесс ротации, оптимизации и удаления данных.
* **Политика ILM (ILM Policy)** — конечный автомат (state machine), описывающий переходы индекса между фазами и действия, выполняемые в каждой фазе.
* **Ротация (Rollover)** — точка перехода, когда текущий индекс закрывается для записи и создается новый. В современных версиях это базовая операция для **Data Streams**.
* **Data Tier (Уровень данных)** — логическая группировка узлов кластера по их роли в хранении данных (`hot`, `warm`, `cold`, `frozen`). Настройка уровня данных в ILM автоматически управляет перемещением шардов (Shard Allocation) между узлами.

## Базовые концепции

### Фазы жизненного цикла

Elasticsearch 8.x выделяет пять фаз. Переход между фазами контролируется параметром `min_age` (время с момента ротации индекса, а не его создания).

| Фаза | Характеристики | Ключевые действия |
| :--- | :--- | :--- |
| **Hot** | Активная запись, интенсивный поиск. | **Rollover**: обязателен для Data Streams. **Downsample**: (для метрик) агрегация данных в большие интервалы. |
| **Warm** | Запись закрыта, поиск регулярный. | **Shrink**: уменьшение количества первичных шард. **Force Merge**: объединение сегментов Lucene. **Migrate**: перемещение на `data_warm` узлы. |
| **Cold** | Поиск редкий, данные статичны. | **Searchable Snapshot**: перевод индекса в формат снимка для экономии локального диска. **Migrate**: перемещение на `data_cold` узлы. |
| **Frozen** | Поиск через Searchable Snapshots. | **Mount**: работа напрямую с объектным хранилищем (S3, GCS) с локальным кэшированием. Требует `data_frozen`. |
| **Delete** | Данные не нужны. | **Delete**: окончательное удаление индекса. |

### Связь с уровнями данных (Data Tiers)

В Elasticsearch 8.x политики ILM используют встроенную систему миграции данных. Вам больше не нужно вручную настраивать `index.routing.allocation.require.data`; вместо этого ILM использует действие `migrate`, которое автоматически перемещает данные на узлы с соответствующими ролями (`data_hot`, `data_warm`, `data_cold`).

* **Hot nodes**: Максимальная производительность (SSD/NVMe).
* **Warm nodes**: Баланс между ценой и производительностью.
* **Cold nodes**: Оптимизация под плотность хранения (HDD).
* **Frozen nodes**: Кэширующие узлы для поиска по снимкам в облаке.

## Практические сценарии

### Настройка комплексной политики ILM

Пример политики для логов: ротация каждые 50 ГБ или 7 дней, переход в Warm сразу после ротации, удаление через 90 дней.

```bash
# Переменная $ELASTIC_PASSWORD должна содержать пароль пользователя elastic
curl -u elastic:$ELASTIC_PASSWORD -k -X PUT "https://localhost:9200/_ilm/policy/prod-logs-policy" \
-H 'Content-Type: application/json' -d'
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "50gb",
            "max_age": "7d"
          }
        }
      },
      "warm": {
        "min_age": "0ms",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 },
          "migrate": { "enabled": true }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}' # → {"acknowledged": true}
```

### Привязка политики через Data Streams

Современный способ назначения политики — использование компонентных шаблонов:

```bash
# 1. Создаем компонентный шаблон с настройками ILM
curl -u elastic:$ELASTIC_PASSWORD -k -X PUT "https://localhost:9200/_component_template/logs-settings" \
-H 'Content-Type: application/json' -d'
{
  "template": {
    "settings": {
      "index.lifecycle.name": "prod-logs-policy"
    }
  }
}'

# 2. Создаем индексный шаблон для потока данных
curl -u elastic:$ELASTIC_PASSWORD -k -X PUT "https://localhost:9200/_index_template/logs-template" \
-H 'Content-Type: application/json' -d'
{
  "index_patterns": ["logs-*"],
  "data_stream": {},
  "composed_of": ["logs-settings"],
  "priority": 500
}'
```

### Диагностика и отладка

Если индекс "застрял" в одной из фаз, используйте API `explain` для выяснения причины:

```bash
curl -u elastic:$ELASTIC_PASSWORD -k -X GET "https://localhost:9200/logs-my_app-default/_ilm/explain?filter_path=indices.*.policy,indices.*.step_info"
```

**Типичные проблемы:**
* **`step_info` содержит ошибку о нехватке места**: ILM не может выполнить `shrink` или `migrate`, если на целевых узлах недостаточно места (см. `watermark` в [Обзоре Elasticsearch](./elasticsearch_overview.md#ключевые-настройки-elasticsearchyml)).
* **Индекс не переходит в следующую фазу**: Проверьте `min_age`. Помните, что отсчет идет от момента **ротации** индекса.
* **Ошибка "index.lifecycle.rollover_alias does not point to index"**: Возникает при использовании обычных индексов (не Data Streams) без правильно настроенного алиаса. С Data Streams этой проблемы не существует.

### Проверка общего статуса

```bash
# Проверка, запущен ли процесс ILM в кластере
curl -u elastic:$ELASTIC_PASSWORD -k -X GET "https://localhost:9200/_ilm/status" # → {"operation_mode": "RUNNING"}
```

## Дополнительная информация

### Особенности Rollover

* Если используется **Data Stream**, ротация происходит автоматически без необходимости настройки `rollover_alias`.
* Ротация — это единственный способ изменить количество первичных шард (`number_of_shards`) для потока данных "на лету" (через обновление шаблона перед ротацией).

### Удаление данных (Retention)

Удаление в ILM происходит только по достижении `min_age` относительно момента **ротации**, а не момента создания документа. Это важно учитывать при планировании дискового пространства.

### Смотрите также

* **[Data Streams и шаблоны индексов](./elasticsearch_mapping_and_indexing.md#современный-подход-data-streams-ilm-и-шаблоны)** — подробнее о том, как работают потоки данных.
* **[Маппинг данных](./elasticsearch_mapping_and_indexing.md)** — описание структуры документов.
