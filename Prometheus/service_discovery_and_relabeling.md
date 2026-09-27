# Service Discovery и Relabeling в Prometheus

> Данный раздел описывает общие концепции. Специфика Kubernetes выделена в отдельное руководство: [Service Discovery в Kubernetes](./kubernetes/service_discovery.md).

> **См. также:** [Лейблы и кардинальность](./concepts/labels_and_cardinality.md) — лучшие практики работы с метками; [Конфигурация Prometheus](./configuration.md) — обзор блока `scrape_configs`.

## Определения

* **Service Discovery (SD)** — механизм автоматического обнаружения целей (targets) для сбора метрик. Prometheus запрашивает актуальный список эндпоинтов у внешних систем (Kubernetes API, [Consul](../Consul/consul_overview.md), конфигурационные файлы, облачные API) вместо их ручного жесткого прописывания в [конфигурационном файле](./configuration.md). В Prometheus 3.0+ механизм SD оптимизирован: он пропускает неизмененные конфигурации, снижая нагрузку на API провайдеров.
* **Relabeling (Релейблинг/Перемаркировка)** — процесс динамической модификации меток (labels) цели или конкретного временного ряда до или после сбора метрик. Позволяет фильтровать цели, стандартизировать имена меток и обогащать метрики метаданными.
    * **UTF-8 Support:** Начиная с версии 3.0, Prometheus поддерживает любые символы UTF-8 в именах метрик и меток (включая эмодзи и спецсимволы), что расширяет возможности классификации.

## Основные концепции

### Жизненный цикл обнаружения и перемаркировки

Процесс сбора метрик проходит через пять ключевых этапов:

1. **Обнаружение (Discovery)** — Prometheus обращается к источнику SD. Современный SD Manager (стандарт с v3.0) эффективно кэширует результаты и минимизирует повторные запросы.
2. **Получение метаданных** — источник возвращает список целей со служебными метками `__meta_*`.
3. **`relabel_configs`** — модификация меток цели **до** начала сбора. Здесь принимается решение о фильтрации (keep/drop) и формируется `__address__`.
    * **Важно (Prometheus 3.0+):** В веб-интерфейсе доступен визуальный отладчик релейблинга (**Relabeling Debugger**), позволяющий отследить трансформацию меток по шагам.
4. **Scrape** — выполнение HTTP-запроса.
    * **Примечание:** В v3.0+ Prometheus не добавляет порты по умолчанию (80/443) автоматически — цель опрашивается ровно так, как она обнаружена или указана.
5. **`metric_relabel_configs`** — модификация меток **после** сбора, но **до** их сохранения в TSDB. Используется для фильтрации конкретных временных рядов и управления [кардинальностью](./concepts/labels_and_cardinality.md).

> **Внимание (Изменение в Regex):** В Prometheus 3.0 символ точки `.` в регулярных выражениях теперь соответствует в том числе символу переноса строки (`\n`). Если требуется старое поведение (исключение переноса), используйте `[^\n]`.

### Различия между `relabel_configs` и `metric_relabel_configs`

| Параметр | `relabel_configs` | `metric_relabel_configs` |
| :--- | :--- | :--- |
| **Когда применяется** | До сбора метрик (pre-scrape) | После сбора, до записи в TSDB (post-scrape) |
| **Объект управления** | Цели (targets) | Метрики (временные ряды) |
| **Типичные задачи** | Фильтрация целей, формирование `__address__`, копирование полезных `__meta_*` в постоянные метки | Удаление ресурсоемких метрик, фильтрация отдельных временных рядов, управление [кардинальностью](./concepts/labels_and_cardinality.md) |
| **Влияние на производительность** | Минимальное | Создает дополнительную вычислительную нагрузку на сервер Prometheus |

### Поведение меток экспортёра (`honor_labels`)

При скрейпинге экспортёр может возвращать метки с теми же именами, что и Prometheus присваивает по умолчанию (`job`, `instance`). Параметр `honor_labels` в `scrape_configs` управляет конфликтом:

*   **`honor_labels: false` (по умолчанию)** — Prometheus перезаписывает метки экспортёра своими значениями. `job` и `instance` остаются корректными.
*   **`honor_labels: true`** — значения от экспортёра имеют приоритет. Используйте для Pushgateway или кастомных экспортёров, где требуется сохранить оригинальные метки.

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true
    static_configs:
      - targets: ['pushgateway:9091']
```

### Механизмы Service Discovery

Prometheus поддерживает множество встроенных механизмов интеграции с популярными инфраструктурными решениями.

#### `static_configs`

Статическое перечисление целей непосредственно в конфигурации. Подходит для небольшой или неизменной инфраструктуры.

```yaml
scrape_configs:
  - job_name: 'node_exporter'
    static_configs:
      - targets: ['192.168.1.10:9100', '192.168.1.11:9100']
        labels:
          env: 'production'
```

#### `file_sd_configs`

Prometheus периодически читает указанные YAML/JSON-файлы со списками целей. При изменении файлов конфигурация применяется автоматически без перезагрузки процесса Prometheus.

```yaml
scrape_configs:
  - job_name: 'file_sd'
    file_sd_configs:
      - files: ['/etc/prometheus/sd/*.yml']
        refresh_interval: 2m
```

**Пример файла целей (`/etc/prometheus/sd/hosts.yml`):**

```yaml
- targets:
  - 'server1.example.com:9100'
  - 'server2.example.com:9100'
  labels:
    service: 'backend'
```

**Best practices для `file_sd_configs`:**
*   Используйте `refresh_interval` не меньше `1m` для снижения нагрузки на диск.
*   Храните файлы в отдельном каталоге с правами `0640` и владельцем `prometheus:prometheus`.
*   Для автоматической доставки файлов от Ansible/Terraform используйте `rsync` или `scp` с послеоперационным `systemctl reload prometheus` для гарантированного применения.
*   Формат YAML предпочтительнее JSON для ручного редактирования — он читаемее и поддерживает комментарии.
*   Группируйте цели по типу: `nodes.yml`, `databases.yml`, `web_servers.yml` — для удобства управления и поиска.
*   Всегда добавляйте `labels` для идентификации окружения, дата-центра и роли сервера.
*   Для on-premise сред с数百 серверами详见 [Bare-metal развёртывание](./installation/bare_metal_setup.md).

> **Примечание:** Для автоматической генерации `file_sd` файлов из Ansible Inventory или CMDB используйте шаблоны Jinja2 и `notify: reload prometheus` — это устраняет необходимость ручного обновления и обеспечивает актуальность списка целей.

#### `docker_sd_configs`

Обнаружение контейнеров через Docker Engine API. Для работы требуется доступ к Docker socket.

```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        port: 2375
    relabel_configs:
      - source_labels: [__meta_docker_container_label_prometheus_enable]
        regex: 'true'
        action: keep
      - source_labels: [__meta_docker_container_name]
        target_label: container
        replacement: '${1}'
```

> **Внимание:** При использовании TCP-сокета (`tcp://host:2375`) без TLS трафик между Prometheus и Docker Engine передается в открытом виде. В production используйте TLS или Unix socket с правильными правами (`chmod 660 /var/run/docker.sock`, группа `docker`).

#### `consul_sd_configs`

Обнаружение сервисов через API реестра Consul.

```yaml
scrape_configs:
  - job_name: 'consul_services'
    consul_sd_configs:
      - server: 'localhost:8500'
        services: ['node-exporter', 'app-metrics']
        tags: ['production']
```

#### Другие механизмы

| Механизм | Описание |
| :--- | :--- |
| `kubernetes_sd_configs` | Обнаружение через Kubernetes API (pod, service, endpoint, node, ingress). В современных кластерах рекомендуется роль `endpointslice` для снижения нагрузки на API. См. [SD в Kubernetes](./kubernetes/service_discovery.md). |
| `docker_sd_configs` | Обнаружение контейнеров на локальном или удаленном хосте Docker через Docker Engine API. |
| `dockerswarm_sd_configs` | Интеграция с кластером Docker Swarm (обнаружение сервисов, задач и узлов). |
| `nomad_sd_configs` | Обнаружение задач (tasks) в кластере HashiCorp Nomad. |
| `http_sd_configs` | Опрос внешнего HTTP-эндпоинта, возвращающего список целей в JSON-формате. Идеально для интеграции с кастомными CMDB. |
| `dns_sd_configs` | Обнаружение на основе DNS-записей (SRV, A). Часто используется для интеграции с CoreDNS вне Kubernetes. |
| `ec2_sd_configs` / `azure_sd_configs` / `gce_sd_configs` | Интеграция с API публичных облаков (AWS/Azure/GCP) для поиска виртуальных машин по тегам. |

### Действия (Actions) в `relabel_configs`

Для управления метками в блоке `relabel_configs` применяются следующие действия:

| Действие | Описание |
| :--- | :--- |
| `keep` | Оставить (сохранить) цель, если значение `source_labels` соответствует регулярному выражению `regex` |
| `drop` | Отбросить (исключить) цель, если значение `source_labels` соответствует `regex` |
| `replace` | Заменить значение или создать новую метку (`target_label`), используя данные из `source_labels` |
| `lowercase` | Перевести значение меток из `source_labels` в нижний регистр и сохранить в `target_label` |
| `uppercase` | Перевести значение меток из `source_labels` в верхний регистр и сохранить в `target_label` |
| `labelmap` | Массово скопировать метки, имена которых соответствуют `regex` (часто используется для трансформации `__meta_*` в рабочие метки) |
| `labeldrop` | Удалить все метки, имена которых соответствуют `regex` |
| `labelkeep` | Сохранить только те метки, имена которых соответствуют `regex` (остальные удаляются) |
| `hashmod` | Вычислить хэш от меток с делением по модулю — используется для горизонтального шардирования серверов Prometheus |

### Особенности Prometheus 3.x в Service Discovery

В мажорной версии 3.x (актуальной на 2026 год) произошел ряд качественных изменений:

*   **Переменные окружения:** Внешние лейблы и параметры теперь поддерживают интерполяцию переменных окружения (`${VAR}`) прямо в `prometheus.yml`, что упрощает настройку в Docker/Kubernetes.
*   **Отсутствие портов по умолчанию:** Prometheus больше не пытается угадать порт на основе схемы (80 для http, 443 для https). Если порт не передан через SD или не указан явно в `__address__`, скрейпинг может завершиться ошибкой.
*   **Нативная поддержка UTF-8:** Метки теперь могут содержать любые символы Юникода. Это позволяет использовать человекочитаемые теги из облачных панелей без транслитерации.
*   **Улучшенный SD Manager:** Механизм стал полностью событийным (event-driven). Если в Kubernetes или Consul не произошло изменений, Prometheus не пересчитывает цели, что экономит до 30-40% ресурсов CPU на больших инсталляциях.

## Практические сценарии

### Интеграция с CMDB через `http_sd_configs`

Сценарий: Получение списка целей из внутренней инвентарной системы компании.

```yaml
scrape_configs:
  - job_name: 'internal-cmdb'
    http_sd_configs:
      - url: 'http://inventory.example.com/api/v1/targets'
        refresh_interval: 5m
    relabel_configs:
      - source_labels: [__meta_http_sd_target_tag_env]
        target_label: environment
        action: replace
```

*JSON-ответ от API:*
```json
[
  {
    "targets": ["10.0.1.5:9100", "10.0.1.6:9100"],
    "labels": {
      "__meta_http_sd_target_tag_env": "production",
      "team": "devops"
    }
  }
]
```

### Фильтрация целей (действия keep и drop)

Сценарий: собирать метрики только с хостов, у которых установлен тег `production` в реестре Consul.

```yaml
relabel_configs:
  - source_labels: [__meta_consul_tag]
    regex: '.*production.*'
    action: keep
```

### Создание метки из метаданных (действие replace)

Сценарий: извлечь имя пода из системной мета-метки и сохранить его в понятную метку `pod_name` для дальнейших запросов.

```yaml
relabel_configs:
  - source_labels: [__meta_kubernetes_pod_name]
    target_label: pod_name
    action: replace
```

### Массовое копирование меток (действие labelmap)

Сценарий: перенести все пользовательские лейблы пода из Kubernetes, отбросив системный префикс `__meta_kubernetes_pod_label_`.

```yaml
relabel_configs:
  - regex: __meta_kubernetes_pod_label_(.+)
    replacement: '$1'
    action: labelmap
```

*Результат:* Метка `__meta_kubernetes_pod_label_app` превратится в `app`, а `__meta_kubernetes_pod_label_version` — в `version`.

### Удаление служебных метаданных (действие labeldrop)

Сценарий: после того как все нужные данные извлечены, удалить оставшиеся громоздкие мета-метки Kubernetes для экономии памяти.

```yaml
relabel_configs:
  - regex: __meta_kubernetes_.+
    action: labeldrop
```

> **Внимание:** Используйте действие `labelkeep` с большой осторожностью. Существует риск случайного удаления внутренних служебных меток Prometheus (например, `__address__` или `__scheme__`), что полностью сломает процесс сбора метрик с этих целей.

### Подмена адреса (Паттерн Blackbox Exporter)

Сценарий: Blackbox Exporter не может быть опрошен стандартным способом, так как ему необходимо передать URL проверяемой цели в качестве параметра. Relabeling используется для подмены адресов "на лету".

```yaml
scrape_configs:
  - job_name: 'blackbox-http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets: ['https://example.com', 'https://api.example.com']
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: 'blackbox-exporter:9115'
      - source_labels: [__param_target]
        target_label: instance
```

**Логика работы:**

1. Оригинальный `__address__` (например, `https://example.com`) копируется в параметр URL `__param_target`.
2. Фактический адрес скрейпинга `__address__` принудительно заменяется на адрес самого сервера Blackbox Exporter.
3. Оригинальный проверяемый URL сохраняется в метке `instance`, чтобы в дашбордах было видно, какой именно ресурс проверялся.

### Горизонтальное шардирование (действие hashmod)

Сценарий: распределение большого количества целей между несколькими экземплярами Prometheus для балансировки нагрузки.

```yaml
relabel_configs:
  - source_labels: [__address__]
    modulus: 4
    target_label: __tmp_hash
    action: hashmod
  - source_labels: [__tmp_hash]
    regex: '0'
    action: keep
```

*Как это работает:* Каждой цели вычисляется хэш, который затем делится по модулю на количество серверов (в данном случае 4). Каждый экземпляр Prometheus получает конфигурацию с собственным значением `regex` (0, 1, 2 или 3) и забирает только свою "долю" целей.

### Управление кардинальностью и фильтрация метрик (`metric_relabel_configs`)

В отличие от `relabel_configs`, блок `metric_relabel_configs` работает с уже собранными временными рядами и позволяет удалять дорогие метрики до попадания в TSDB.

#### Удаление высококардинальных метрик

Сценарий: экспортёр добавляет уникальный `device` лейбл к каждой mounted filesystem, что взрывает кардинальность.

```yaml
metric_relabel_configs:
  - source_labels: [__name__, device]
    regex: 'node_filesystem_size_bytes.+'
    action: drop
```

#### Оставление только нужных метрик

Сценарий: с экспортёра поставляются десятки метрик, нужны только `up`, `node_cpu_seconds_total` и `node_memory_*`.

```yaml
metric_relabel_configs:
  - source_labels: [__name__]
    regex: 'up|node_cpu_seconds_total|node_memory_.*'
    action: keep
```

#### Удаление debug-метрик из приложения

Сценарий: приложение экспонирует метрики с префиксом `debug_*`, которые не нужны в production.

```yaml
metric_relabel_configs:
  - source_labels: [__name__]
    regex: 'debug_.*'
    action: labeldrop
```

#### Фильтрация перед Remote Write

Для отправки данных в долгосрочное хранилище используется `write_relabel_configs` в блоке `remote_write`:

```yaml
remote_write:
  - url: 'http://victoriametrics:8428/api/v1/write'
    write_relabel_configs:
      - source_labels: [__name__]
        regex: 'go_.*|prometheus_.*'
        action: drop
      - source_labels: [job]
        regex: 'temp-job'
        action: drop
```

### Автоматизация мониторинга большого количества ВМ (100+ в день)

При массовом и динамичном создании виртуальных машин ручное обновление `static_configs` становится невозможным. Применяются следующие подходы к автоматизации:

#### 1. Использование `file_sd_configs` и систем управления конфигурацией

Самый распространенный и гибкий способ для инфраструктуры без Kubernetes.

* **Процесс:** Система управления конфигурацией (Ansible) или Provisioning-инструмент (Terraform) генерирует конфигурационный JSON/YAML файл в целевой директории на сервере Prometheus.
* **Преимущества:** Prometheus подхватывает изменения мгновенно без перезагрузки процесса; архитектурно просто в реализации.
* **Недостатки:** Требуется настроить надежный механизм доставки файлов от Terraform/Ansible до сервера мониторинга.

```yaml
# Пример фрагмента prometheus.yml
scrape_configs:
  - job_name: 'automated_vms'
    file_sd_configs:
      - files: ['/etc/prometheus/targets/*.json']
```

#### 2. Интеграция `http_sd_configs` и Inventory API (CMDB)

Подходит, если в компании внедрен централизованный реестр ИТ-активов.

* **Процесс:** Prometheus периодически опрашивает специальный HTTP-эндпоинт внутреннего сервиса, который возвращает актуальный список всех виртуальных машин в требуемом формате JSON.
* **Преимущества:** Единый центр управления целями; отпадает необходимость в доставке конфигурационных файлов.
* **Недостатки:** Требует разработки и поддержки собственного HTTP-адаптера или API.

#### 3. Использование облачных Service Discovery

Оптимально для инфраструктуры, полностью развернутой в публичных облаках (AWS, Azure, GCP).

* **Процесс:** Prometheus напрямую взаимодействует с API облачного провайдера через механизмы вроде `ec2_sd_configs`.
* **Преимущества:** Полная автоматизация «из коробки»; возможность мощной фильтрации на стороне облака (например, собирать метрики только с ВМ, имеющих тег `monitor: true`).

#### 4. Интеграция с реестрами сервисов (например, Consul)

* **Процесс:** Каждая виртуальная машина при запуске ОС автоматически регистрирует себя в кластере Consul. Prometheus периодически запрашивает у Consul список живых инстансов.
* **Преимущества:** Наличие встроенного механизма Health Checks — Prometheus не будет пытаться собирать метрики с серверов, которые Consul пометил как недоступные.

#### 5. Native Docker Swarm Discovery

* **Процесс:** Prometheus подключается к API менеджера Swarm и автоматически находит все задачи (`tasks`) запущенных сервисов.
* **Сценарий:** Сбор метрик только с тех сервисов, у которых в `deploy.labels` указано `prometheus.enable=true`.

```yaml
scrape_configs:
  - job_name: 'swarm-services'
    dockerswarm_sd_configs:
      - host: unix:///var/run/docker.sock
        role: tasks
    relabel_configs:
      - source_labels: [__meta_dockerswarm_service_label_prometheus_enable]
        regex: 'true'
        action: keep
```

## Дополнительная информация

### Валидация и отладка Service Discovery

После изменения конфигурации SD или relabeling выполните проверки:

```bash
# 1. Валидация синтаксиса YAML
promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS

# 2. Проверка правил (если есть)
promtool check rules /etc/prometheus/rules/*.yml
# → SUCCESS

# 3. Проверка доступности API
curl -s http://localhost:9090/-/healthy
# → healthy

# 4. Проверка целей и меток через API
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health}'
# → все health: "up"

# 5. Отладочный вывод Service Discovery в UI
# Откройте http://<prometheus>:9090/targets и найдите job.
# В столбце "Labels" видны метки ДО (Discovered Labels) и ПОСЛЕ (Labels) relabeling.
```

**Отладка конкретного правила relabeling через UI (Prometheus 3.x):**
1. Перейдите в `Status` → `Service Discovery`.
2. Найдите нужный pool и раскройте его.
3. Для каждой цели отображаются `Discovered Labels` (с префиксом `__meta_*`) и итоговые `Labels` после применения `relabel_configs`.
4. Сравните их, чтобы понять, почему цель была отброшена (`drop`) или почему метка получила неожиданное значение.

**Анализ кардинальности:**
```bash
promtool tsdb analyze /var/lib/prometheus/
# → Memory usage: ...
# → Series: ...
# → Top metrics by series: ...
```

### Производительность и масштабирование

*   **Количество целей:** Prometheus комфортно опрашивает до нескольких тысяч целей на одном инстансе. При превышении 10 000 targets рекомендуется горизонтальное шардирование через `hashmod` или развертывание нескольких экземпляров Prometheus.
*   **Частота опроса SD:** Уменьшение `refresh_interval` до значений меньше `30s` увеличивает нагрузку на API-серверы (Kubernetes, Consul). Используйте `1m` или `2m` как стартовое значение.
*   **Режим прокси/сокета:** `docker_sd_configs` с TCP-сокетом добавляет задержку при большом количестве контейнеров. Для высоконагруженных хостов используйте Unix socket.
*   **Relabeling и CPU:** Сложные регулярные выражения в `relabel_configs` обрабатываются для каждой цели на каждом refresh. Избегайте вложенных regex и используйте префиксы (`__meta_.*`) для быстрого отсечения.
*   **Кардинальность:** `metric_relabel_configs` выполняется на CPU для каждого собранного временного ряда. При百万ском количестве series убедитесь, что правило `drop` находится в начале конфигурации, чтобы отсечь метрики как можно раньше.

### Устранение неисправностей

| Симптом | Возможная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Цель имеет статус `DOWN` | Неверный `__address__` после relabeling | UI → Targets → раскройте цель, проверьте `Discovered Labels` и `Labels`. |
| Цель отсутствует в списке | Ошибка regex в `keep`/`drop` или SD недоступен | Проверьте `promtool check config`, доступность API SD (Consul/K8s). |
| `sample limit exceeded` | `metric_relabel_configs` не удаляет лишние метрики | Добавьте `drop` правило для high-cardinality меток или увеличьте `sample_limit`. |
| Дублирующиеся series | `honor_labels: true` и экспортёр возвращает конфликтующие `job`/`instance` | Установите `honor_labels: false` или нормализуйте метки через `relabel_configs`. |
| Реликвийные метки `__meta_*` в TSDB | Забытое `labeldrop` в `relabel_configs` | Добавьте `labeldrop` для `__meta_.*` после извлечения нужных данных. |
| Высокий CPU на SD Manager | Слишком частый `refresh_interval` или большое количество источников | Увеличьте `refresh_interval`, добавьте фильтры на стороне SD (Consul tags, K8s selectors). |
| `relabel_configs` не применяется | Ошибка в порядке действий или опечатка в `source_labels` | Проверьте `promtool check config`; убедитесь, что `source_labels` существует. |
| SD Manager не обнаруживает изменения | Проблема кэширования или событийного механизма | Перезагрузите Prometheus (`SIGHUP` или `/-/reload`); проверьте логи на предмет ошибок SD. |
| Docker socket permission denied | Пользователь Prometheus не в группе `docker` | `sudo usermod -aG docker prometheus` и перелогин. |
| DNS SD возвращает устаревшие записи | TTL кэша DNS превышает время жизни записи | Уменьшите `refresh_interval` или проверьте `dns_sd_configs` параметры. |

### Резервное копирование и управление конфигурацией

*   **Версионирование:** Храните `prometheus.yml` и файлы SD в Git-репозитории. Это обеспечивает аудит изменений и возможность быстрого отката.
*   **Экспорт конфигурации SD:** Регулярно экспортируйте состояние SD для audit:
    ```bash
    curl -s http://localhost:9090/api/v1/targets > /backups/prometheus-targets-$(date +%Y%m%d).json
    ```
*   **Валидация перед применением:** После изменения `prometheus.yml` проверяйте синтаксис и перезапускайте Prometheus:
    ```bash
    promtool check config /etc/prometheus/prometheus.yml
    sudo systemctl reload prometheus
    ```

### Миграция с конфигурации на Prometheus 2.x на 3.x

*   **Regex точка `.`:** В 3.x `.` совпадает с `\n`. Проверьте все regex в `relabel_configs` и `metric_relabel_configs`, которые работают с мультистрочными значениями.
*   **Отсутствие портов по умолчанию:** Убедитесь, что все `__address__` содержат явный порт. Добавьте `:9100` к целям, если SD не возвращает порт.
*   **UTF-8 в метках:** Если старые экспортёры используют escape-последовательности для Unicode, проверьте корректность отображения в Grafana после миграции.
*   **`honor_labels`:** Поведение по умолчанию не изменилось, но в 3.x стоит явно указывать `honor_labels: false` для совместимости.

## Связанные темы

* [SD в Kubernetes](./kubernetes/service_discovery.md) — специфика обнаружения через `kubernetes_sd_configs` и использование абстракций ServiceMonitor/PodMonitor.
* [Blackbox Exporter](./Exporters/blackbox/blackbox_exporter_overview.md) — детальный разбор relabeling для probe-мониторинга.
* [promtool](./promtool_and_best_practices.md) — использование утилит для статической валидации сложной конфигурации relabeling.
* [Remote Read/Write](./scaling/remote_read_write.md) — использование параметров `write_relabel_configs` для фильтрации метрик перед их отправкой в долгосрочное хранилище (LTS).
* [Лейблы и кардинальность](./concepts/labels_and_cardinality.md) — влияние релейблинга на производительность TSDB.
