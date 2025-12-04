# Глубокое погружение в конфигурацию Fluent Bit

В этом документе подробно рассматриваются основные секции конфигурационного файла Fluent Bit (`fluent-bit.conf` или `values.yaml` при использовании Helm-чарта) и их параметры для эффективного сбора логов в Kubernetes.

При возникновении проблем с компонентами стека EFK обратитесь к руководству по [устранению неполадок](./efk_stack_troubleshooting.md).

## Обзор структуры конфигурации

Конфигурация Fluent Bit разделена на несколько ключевых секций:

-   `[SERVICE]` — общие настройки сервиса.
-   `[INPUT]` — определяет источники логов.
-   `[FILTER]` — позволяет модифицировать и обогащать логи.
-   `[OUTPUT]` — определяет, куда отправлять обработанные логи.
-   `[PARSER]` — определяет пользовательские парсеры для структурирования логов.

## Секция `[SERVICE]`

Здесь содержатся глобальные настройки для демона Fluent Bit.

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
```

-   `Flush`: Интервал в секундах, с которым Fluent Bit отправляет собранные логи в `OUTPUT`. `Flush 1` означает отправку раз в секунду. На нагруженных системах это значение можно увеличить, чтобы снизить количество запросов, например, к [Elasticsearch](../../../ELK_Stack/Elasticsearch/elasticsearch_sharding_replication_cluster.md), но это добавит задержку в доставке логов.
-   `Daemon`: `Off` указывает, что Fluent Bit не должен уходить в фоновый режим. Это стандартная практика при запуске в контейнере.
-   `Log_Level`: Уровень логирования самого Fluent Bit.
-   `Parsers_File`: Путь к файлу с определениями парсеров.
-   `HTTP_Server`: `On` включает встроенный HTTP-сервер, который используется для предоставления метрик (например, для Prometheus) и общей статистики работы Fluent Bit.

## Секция `[INPUT]`

Эта секция определяет, откуда Fluent Bit будет собирать логи. В Kubernetes обычно используется несколько `INPUT`'ов.

```yaml
# Пример секции Input в values.yaml
config:
  inputs: |
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        Parser            docker
        Mem_Buf_Limit     5MB
        Skip_Long_Lines   On

    [INPUT]
        Name              systemd
        Tag               host.*
        Systemd_Filter    _SYSTEMD_UNIT=kubelet.service
        Systemd_Filter    _SYSTEMD_UNIT=docker.service
        Read_From_Tail    On
```

### Input `tail` (Логи контейнеров)

-   `Name tail`: Использует плагин `tail` для чтения логов из файлов, подобно команде `tail -f`.
-   `Path /var/log/containers/*.log`: Указывает Fluent Bit собирать все файлы, заканчивающиеся на `.log`, из директории `/var/log/containers/`. Kubernetes создает в этой директории символические ссылки на логи всех контейнеров, запущенных на ноде.
-   `Tag kube.*`: Назначает всем логам из этого `INPUT`'а тег, начинающийся с `kube.`. Теги используются для маршрутизации логов в секциях `FILTER` и `OUTPUT`.
-   `Parser docker`: Применяет парсер `docker` для обработки строк лога.
-   `Mem_Buf_Limit`: Ограничивает количество памяти, которое Fluent Bit может использовать для буферизации логов из одного файла. Это защищает от чрезмерного потребления памяти.
-   `Skip_Long_Lines On`: Если строка лога превышает `Mem_Buf_Limit`, эта опция предписывает пропустить эту строку и продолжить чтение файла. По умолчанию (`Off`) Fluent Bit перестал бы обрабатывать такой файл целиком.

### Input `systemd` (Логи хостовой системы)

-   `Name systemd`: Использует плагин `systemd` для сбора логов напрямую из `journald` на хосте.
-   `Tag host.*`: Назначает тег `host.` логам системных компонентов.
-   `Systemd_Filter`: Позволяет указать, логи каких `systemd-unit`'ов нужно собирать. В примере собираются логи `kubelet` и `docker`.
-   `Read_From_Tail On`: Указывает Fluent Bit читать логи не с самого начала, а только те, что появляются после его запуска.

## Секция `[FILTER]`

Фильтры позволяют изменять проходящие через них логи. Самый важный фильтр в контексте Kubernetes — `kubernetes`.

```yaml
# Пример секции Filter в values.yaml
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

-   `Name kubernetes`: Название встроенного фильтра.
-   `Match kube.*`: Применяет этот фильтр ко всем логам, тег которых соответствует паттерну `kube.*` (т.е. ко всем логам контейнеров из нашего `INPUT`'а).
-   `Kube_URL`: Адрес API-сервера Kubernetes.
-   **Обогащение логов**: Фильтр обращается к API-серверу и обогащает логи метаданными из Kubernetes:
    -   Имя пода (`pod_name`)
    -   Namespace (`namespace_name`)
    -   ID контейнера (`container_id`)
    -   Лейблы пода (`kubernetes_labels`)
    -   Аннотации пода (`kubernetes_annotations`)
-   `Merge_Log On`: Если поле `log` содержит валидный JSON, его поля будут "подняты" на верхний уровень лог-записи. Это крайне полезно, если ваши приложения пишут логи в JSON-формате.
-   `Keep_Log Off`: После успешного `Merge_Log` исходное поле `log` будет удалено, чтобы избежать дублирования.
-   `K8S-Logging.Parser On`: Позволяет переопределить парсер для логов конкретного пода с помощью аннотации `fluentbit.io/parser: <имя_парсера>`.
-   `K8S-Logging.Exclude On`: Позволяет полностью исключить логи пода из сбора с помощью аннотации `fluentbit.io/exclude: "true"`. Это удобно для отключения логов отладочных или слишком "шумных" приложений.

## Секция `[OUTPUT]`

Эта секция определяет, куда Fluent Bit будет отправлять обработанные логи.

```yaml
# Пример секции Output в values.yaml
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

    [OUTPUT]
        Name               es
        Match              host.*
        Host               elasticsearch-master.logging.svc.cluster.local
        Port               9200
        Logstash_Format    On
        Logstash_Prefix    node
        Retry_Limit        False
```

-   `Name es`: Использует плагин для вывода в Elasticsearch.
-   `Match`: Указывает, какие логи (по тегу) отправлять в этот `OUTPUT`. `kube.*` — для логов контейнеров, `host.*` — для логов хоста.
-   `Host`, `Port`: Адрес и порт сервиса Elasticsearch.
-   `Logstash_Format On`: Заставляет Fluent Bit отправлять данные в формате, совместимом с Logstash. Это влияет на то, как создаются имена индексов.
-   `Logstash_Prefix`: Префикс, используемый для имени индекса в Elasticsearch. В сочетании с `Logstash_Format` индексы будут иметь вид `<Logstash_Prefix>-YYYY.MM.DD`. Например, `kube-2025.11.11`. Это позволяет разделить логи приложений (`kube`) и логи хостов (`node`).
-   `Replace_Dots On`: **Важный параметр для избежания конфликтов маппинга в Elasticsearch.** Kubernetes использует точки в именах лейблов и аннотаций (например, `app.kubernetes.io/name`). Elasticsearch интерпретирует точки как вложенные поля, что может привести к конфликту типов (например, `app` в одном случае строка, а в другом — объект). Эта опция заменяет точки на нижние подчеркивания (`_`), решая проблему.
-   `Retry_Limit False`: Указывает Fluent Bit бесконечно пытаться повторно отправить логи в случае недоступности Elasticsearch.

## Секция `[PARSERS]`

Здесь объявляются кастомные парсеры, которые можно использовать в `INPUT`'ах или через аннотации.

```yaml
# Пример секции Parsers в values.yaml
config:
  parsers: |
    [PARSER]
        Name        docker
        Format      json
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L
```

-   `Name docker`: Имя парсера.
-   `Format json`: Указывает, что парсер работает с JSON-форматом.
-   `Time_Key`: Поле в JSON, которое содержит временную метку.
-   `Time_Format`: Формат временной метки.

## Применение изменений

После внесения изменений в `values.yaml` для Helm-чарта Fluent Bit, необходимо применить их с помощью команды:

```bash
helm upgrade --install fluent-bit fluent/fluent-bit \
  --namespace logging \
  -f /home/q/notes/Kubernetes/fluent_values.yaml
```
