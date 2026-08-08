# Elasticsearch: Жизненный цикл индексов (ILM) и политики хранения

## Определения

* **ILM (Index Lifecycle Management)** — подсистема Elasticsearch для полной автоматизации управления индексами через набор фаз и действий.
* **DLM (Data Stream Lifecycle)** — упрощенный механизм управления жизненным циклом, ориентированный специально на потоки данных (Data Streams). Позволяет настраивать хранение (`retention`) и перенос в `frozen` без создания сложных политик ILM.
* **Ротация (Rollover)** — процесс закрытия текущего индекса для записи и создания нового при достижении определенных условий (размер, возраст, количество документов).
* **Data Tier (Уровень данных)** — логическая роль узла в хранении данных (`hot`, `warm`, `cold`, `frozen`), определяющая тип оборудования и стоимость хранения.
* **Downsampling** — технология уменьшения объема данных временных рядов (TSDS) путем агрегации старых метрик в более крупные временные интервалы (бакеты), сохраняя статистическую значимость (`min`, `max`, `sum`, `count`).
* **Searchable Snapshot (Поисковый снимок)** — технология, позволяющая выполнять поисковые запросы напрямую по данным, хранящимся в объектном хранилище (S3/GCS), без необходимости их полного восстановления на локальный диск.

## Основные концепции

### Фазы жизненного цикла

В современной архитектуре (8.x+) жизненный цикл делится на пять фаз. Переход между фазами определяется параметром `min_age` (время с момента ротации).

| Фаза | Характеристики | Ключевые действия |
| :--- | :--- | :--- |
| **Hot** | Активная запись и поиск. | **Rollover**: создание нового индекса. **Downsample**: агрегация метрик (8.15+). |
| **Warm** | Запись закрыта, поиск частый. | **Shrink**: уменьшение числа шард. **Force Merge**: оптимизация сегментов. **Migrate**: перенос на `warm` узлы. |
| **Cold** | Поиск редкий, данные статичны. | **Searchable Snapshot**: (Fully Mounted) — снимок становится основной копией данных. |
| **Frozen** | Архивный поиск. | **Searchable Snapshot**: (Partially Mounted) — данные в облаке, на диске только кэш. |
| **Delete** | Данные не нужны. | **Delete**: окончательное удаление. |

### Рекомендации по размеру шард

Для стабильности кластера и производительности ILM следует придерживаться правила: **целевой размер основного шарда — 50 ГБ**.
*   Используйте `max_primary_shard_size: "50gb"` в качестве основного триггера ротации.
*   Избегайте "раздувания шардов" (shard bloat) — ситуации с тысячами мелких индексов по несколько мегабайт, что перегружает Master-узел.

### Data Stream Lifecycle (DLM) vs ILM

Начиная с версий 8.12+, для стандартных логов рекомендуется использовать **DLM** из-за простоты:
*   **ILM**: Максимальная гибкость (shrink, force merge, сложные условия). Требует политики и шаблона.
*   **DLM**: Настраивается одной командой API. Автоматически управляет ротацией и удалением. Идеально для большинства observability-задач.

## Практические сценарии

### 1. Настройка политики ILM для логов (Hot-Warm-Delete)

Сценарий: ротация при 50 ГБ, оптимизация в Warm (1 шард, 1 сегмент), удаление через 30 дней.

```bash
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_ilm/policy/logs-policy" -H 'Content-Type: application/json' -d'
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": { "max_primary_shard_size": "50gb", "max_age": "30d" }
        }
      },
      "warm": {
        "min_age": "0ms",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 }
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": { "delete": {} }
      }
    }
  }
}'
```

### 2. Настройка Downsampling для метрик

Позволяет хранить детальные метрики 7 дней, а затем сжимать их, экономя до 90% места.

```json
"phases": {
  "warm": {
    "min_age": "7d",
    "actions": {
      "downsample": {
        "fixed_interval": "1h"
      }
    }
  }
}
```
*Данные после Downsampling полностью query-compatible с оригинальными индексами.*

### 3. Привязка политики к Data Stream

Используйте компонентные шаблоны для модульности:

```bash
# Создание настроек
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_component_template/logs-lifecycle" -H 'Content-Type: application/json' -d'
{
  "template": {
    "settings": { "index.lifecycle.name": "logs-policy" }
  }
}'

# Создание итогового шаблона
curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_index_template/app-logs" -H 'Content-Type: application/json' -d'
{
  "index_patterns": ["logs-app-*"],
  "data_stream": {},
  "composed_of": ["logs-lifecycle", "logs-mappings"],
  "priority": 500
}'
```

### 4. Диагностика и решение проблем

Если индексы не удаляются или не перемещаются:

```bash
# Выяснить причину остановки ILM для конкретного индекса
curl -u elastic:$PASS -k -X GET "https://localhost:9200/my-index/_ilm/explain"
```

**Типичные ошибки:**
*   **"index.lifecycle.rollover_alias does not point to index"**: Вы используете старый подход с алиасами. Рекомендуется перейти на **Data Streams**.
*   **Insufficient disk space**: ILM не выполнит `shrink` или `migrate`, если на узлах превышен порог `high watermark` (обычно 90%).
*   **ILM Status is STOPPED**: Проверьте статус через `GET /_ilm/status`. Запустите при необходимости: `POST /_ilm/start`.

## Дополнительная информация

### Searchable Snapshots и уровни хранения

*   **Cold Tier**: Данные хранятся в S3, но индекс "смонтирован" полностью. Реплики не нужны, так как S3 гарантирует сохранность. Экономия 50% ресурсов.
*   **Frozen Tier**: Локально хранится только кэш самых частых запросов. Подходит для хранения данных годами.
*   *Лицензия*: Searchable Snapshots требуют уровня Platinum или Enterprise. Downsampling доступен в Basic (Free).

### Смотрите также

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера и уровни данных (Data Tiers).
*   **[Elasticsearch: Индексирование и маппинг](./elasticsearch_mapping_and_indexing.md)** — детально о структуре Data Streams.
*   **[Официальная документация: ILM Actions](https://www.elastic.co/guide/en/elasticsearch/reference/current/ilm-actions.html)**.
