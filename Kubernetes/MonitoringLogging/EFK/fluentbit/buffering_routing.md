# Буферизация и маршрутизация в Fluent Bit

Буферизация и маршрутизация — ключевые механизмы, определяющие надежность доставки и гибкость отправки логов.

## Буферизация: модели и параметры

**Fluent Bit** буферизует записи в памяти с возможностью выгрузки на диск (Storage Layer).

- Глобально в `[SERVICE]`: `storage.path`, `storage.sync`, `storage.backlog.mem_limit`
- На входе `[INPUT]`: `storage.type filesystem` для долговременного буфера и `Mem_Buf_Limit` для контроля памяти

## Маршрутизация: теги и правила

Каждый `[OUTPUT]` имеет `Match` или `Match_Regex` для выбора логов по тегу.

## Сравнение с Fluentd

| Аспект | Fluentd | Fluent Bit |
| :--- | :--- | :--- |
| **Буфер по умолчанию** | `file`/`memory` на каждый output | `memory` + опциональный `filesystem` |
| **Управление перегрузкой** | `overflow_action`, backpressure | `Mem_Buf_Limit`, `storage.backlog.mem_limit` |
| **Гибкость маршрутизации** | `@label`, `copy`, сложные графы | Простые правила `Match`/`Match_Regex` |
| **Надежность доставки** | Высокая с `file`-буфером | Высокая с `storage.type=filesystem` |

## Пример конфигурации Fluentd (агрегация и маршрутизация)

```bash
<source>
  @type tail
  path /var/log/app.log
  tag app.log
</source>

<match app.**>
  @type copy

  <store>
    @type elasticsearch
    host es
    port 9200
    <buffer tag,time>
      @type file
      path /var/lib/fluentd/buffer/es
      chunk_limit_size 5m
      total_limit_size 1g
      flush_interval 5s
      retry_forever true
    </buffer>
  </store>

  <store>
    @type s3
    s3_bucket logs-archive
    <buffer tag>
      @type file
      path /var/lib/fluentd/buffer/s3
      chunk_limit_size 10m
      flush_interval 60s
    </buffer>
  </store>
</match>
```

В этом примере плагин `@type copy` дублирует входящие логи в два разных хранилища (Elasticsearch и S3) с независимыми настройками буферизации.
