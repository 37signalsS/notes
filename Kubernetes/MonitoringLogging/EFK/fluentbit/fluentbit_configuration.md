# Глубокое погружение в конфигурацию Fluent Bit

Конфигурация Fluent Bit разделена на несколько ключевых секций, которые определяют полный жизненный цикл лога от сбора до отправки.

## Секция `[SERVICE]`: Глобальные настройки

```yaml
# Пример секции Service в values.yaml
config:
  service: |
    [SERVICE]
        Flush         1
        Daemon        Off
        Log_Level     info
        Parsers_File  parsers.conf
        HTTP_Server   On
        HTTP_Listen   0.0.0.0
        HTTP_Port     2020
        storage.path        /var/lib/fluent-bit/storage
        storage.sync        normal
        storage.backlog.mem_limit 128M
```

- `Flush`: Интервал в секундах для отправки собранных логов в `OUTPUT`
- `Daemon`: `Off` указывает, что Fluent Bit не должен уходить в фоновый режим
- `Log_Level`: Уровень логирования самого Fluent Bit
- `Parsers_File`: Путь к файлу с определениями парсеров
- `HTTP_Server`: Включает встроенный HTTP-сервер для метрик Prometheus
- `storage.*`: Параметры для настройки дисковой буферизации

## Секция `[INPUT]`: Сбор логов

```yaml
config:
  inputs: |
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        Parser            docker
        Mem_Buf_Limit     10MB
        Skip_Long_Lines   On
        storage.type      filesystem

    [INPUT]
        Name              systemd
        Tag               host.*
        Systemd_Filter    _SYSTEMD_UNIT=kubelet.service
        Read_From_Tail    On
```

- **Плагин `tail`**: Читает логи из файлов, подобно `tail -f`
- **Плагин `systemd`**: Сбор логов напрямую из `journald`

## Секция `[FILTER]`: Модификация и обогащение логов

```yaml
config:
  filters: |
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Merge_Log           On
        Keep_Log            Off
        K8S-Logging.Parser  On
        K8S-Logging.Exclude On
```

- `Name kubernetes`: Обогащение логов метаданными из Kubernetes API
- `Merge_Log On`: Если поле `log` содержит JSON, его поля "поднимаются" на верхний уровень
- `K8S-Logging.Parser On`: Позволяет переопределить парсер через аннотацию

## Секция `[OUTPUT]`: Отправка логов

```yaml
config:
  outputs: |
    [OUTPUT]
        Name               es
        Match              kube.*
        Host               elasticsearch-master.logging.svc.cluster.local
        Port               9200
        Logstash_Format    On
        Logstash_Prefix    kube
        Replace_Dots       On
        Retry_Limit        False
```

- `Name es`: Плагин для вывода в Elasticsearch
- `Replace_Dots On`: Заменяет точки в именах полей на `_`
- `Retry_Limit False`: Бесконечные попытки повторной отправки
