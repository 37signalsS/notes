# Service Discovery и Relabeling в Prometheus

> Эта заметка описывает общие принципы Service Discovery и Relabeling. Для специфики работы в Kubernetes, см. **[[./kubernetes/service_discovery.md]]**.

## 1. Определения

**Service Discovery (Обнаружение сервисов)** — это механизм, который [Prometheus](./overview.md) использует для автоматического нахождения целей (targets) для сбора метрик. Вместо ручного перечисления каждого хоста в [конфигурации](./configuration.md), Prometheus может запрашивать информацию у внешних систем (например, у API облачного провайдера, Kubernetes или Consul) для получения актуального списка эндпоинтов. Это ключевая возможность для работы в динамических средах, где инфраструктура постоянно меняется, как описано в концепции [наблюдаемости](../Concepts/Observability_and_Monitoring/observability_overview.md).

**Relabeling (Перемаркировка)** — это процесс модификации меток, связанных с целью, *до* того, как Prometheus выполнит сбор метрик (scraping). Он позволяет фильтровать цели, стандартизировать метки, добавлять или удалять метаданные, полученные в процессе Service Discovery.

## 2. Основные концепции

### Как работает Service Discovery

Общий процесс выглядит следующим образом:
1.  **Обнаружение:** Prometheus обращается к настроенному источнику (например, `file_sd_configs`, `kubernetes_sd_configs`, `consul_sd_config`).
2.  **Получение метаданных:** Источник возвращает список потенциальных целей и набор метаданных для каждой из них. Эти временные метки имеют префикс `__meta_`. Например, `__meta_kubernetes_pod_name` или `__meta_consul_tags`.
3.  **Перемаркировка (`relabel_configs`):** Prometheus применяет к этому набору целей и меток правила из секции `relabel_configs` для фильтрации и преобразования.
4.  **Формирование финальной цели:** После перемаркировки определяется итоговый адрес для сбора метрик (метка `__address__`) и набор финальных меток, которые будут прикреплены ко всем временным рядам, собранным с этой цели.

### Жизненный цикл меток

Модификация меток в Prometheus происходит на двух этапах:

1.  `relabel_configs`: Производит изменения **до** сбора метрик. Этот механизм используется для управления самими целями:
    *   Решает, будет ли Prometheus вообще опрашивать данную цель (`keep`, `drop`).
    *   Устанавливает адрес цели (`__address__`).
    *   Формирует постоянные метки цели на основе метаданных (например, превращает `__meta_kubernetes_namespace` в метку `kubernetes_namespace`).
    Важность правильного управления метками на этом этапе подчеркивается в заметке о [лейблах и кардинальности](./concepts/labels_and_cardinality.md).

2.  `metric_relabel_configs`: Производит изменения **после** сбора метрик, но **до** их сохранения в базу данных. Этот механизм используется для управления уже собранными временными рядами:
    *   Фильтрация и удаление ненужных метрик.
    *   Переименование или удаление меток у самих метрик.
    *   **Важно:** `metric_relabel_configs` не применяются к автоматически генерируемым метрикам, таким как `up`.

## 3. Практические сценарии (Механизмы Service Discovery)

Ниже приведены примеры настройки различных механизмов Service Discovery в `prometheus.yml`. Все они настраиваются в рамках секции `scrape_configs` (см. [Конфигурация Prometheus](./configuration.md)).

### 3.1. Статическая конфигурация (`static_config`)

Это самый простой способ определить цели. Он подходит для небольшого количества хостов с неизменными адресами.

**Пример:** Добавление нескольких `node_exporter` в `prometheus.yml`.

```yaml
# /etc/prometheus/prometheus.yml

scrape_configs:
  - job_name: 'static_config_example'
    # Используется статическое определение таргетов
    static_configs:
    - targets:
        - localhost:9100
        - <адрес сервера server1>:9100
        - <адрес сервера server2>:9100
      labels: 
        # Эта метка будет добавлена ко всем метрикам, собранным в рамках этого job
        env: 'production' 
        sd_method: 'static'
```

После перезагрузки конфигурации Prometheus (`systemctl reload prometheus`), новые таргеты появятся в веб-интерфейсе в разделе **Status -> Targets**.

### 3.2. Обнаружение на основе файлов (`file_sd_configs`)

Этот метод является развитием статической конфигурации. Prometheus периодически перечитывает один или несколько файлов, в которых в формате YAML или JSON определены таргеты. Это позволяет добавлять или удалять хосты без перезагрузки основной конфигурации Prometheus.

**Шаг 1: Создать каталог и файл для SD**

```bash
# Создаем каталог для файлов Service Discovery
mkdir /etc/prometheus/sd
chown prometheus:prometheus /etc/prometheus/sd

# Создаем файл со списком хостов
cat <<EOF > /etc/prometheus/sd/node_exporter_hosts.yml
- targets:
  - localhost:9100
  - <адрес сервера server1>:9100
  - <адрес сервера server2>:9100
  labels:
    env: 'production'
    sd_method: 'file'
EOF
```

**Шаг 2: Настроить Prometheus**

```yaml
# /etc/prometheus/prometheus.yml

scrape_configs:
  - job_name: 'file_sd_example'
    file_sd_configs:
      - files:
        - /etc/prometheus/sd/*.yml # Prometheus будет читать все .yml файлы из этого каталога
        # Как часто перечитывать файлы.
        refresh_interval: 1m 
```

### 3.3. Обнаружение через API (Пример с OpenStack)

Prometheus может интегрироваться с API множества облачных провайдеров и систем оркестрации для автоматического обнаружения ресурсов.

**Пример:** Настройка `openstack_sd_configs` для обнаружения виртуальных машин в OpenStack.

```yaml
# /etc/prometheus/prometheus.yml

scrape_configs:
  - job_name: 'openstack_vms'
    openstack_sd_configs:
      - identity_endpoint: https://api.selvpc.ru/identity/v3
        # Порт, по которому будет производиться scraping (например, порт node_exporter)
        port: 9100 
        domain_name: '82113'
        username: '<user_name>'
        project_name: '<project_name>'
        password: '<password>'
        role: 'instance' # Указываем, что мы ищем виртуальные машины
        region: '<region>'
        # Как часто опрашивать API OpenStack
        refresh_interval: 30s
```

## 4. Продвинутые детали (Действия `relabel_configs`)

`relabel_configs` — это мощный механизм, который позволяет модифицировать метки таргетов *до* сбора метрик. Он используется для фильтрации, переименования и создания новых меток на основе метаданных (`__meta_` меток), полученных от Service Discovery.

### Действие: `keep` / `drop` (Фильтрация)

*   `keep`: Оставить только те таргеты, которые соответствуют регулярному выражению.
*   `drop`: Отбросить таргеты, которые соответствуют регулярному выра-жению.

**Пример:** Собирать метрики только с ВМ, у которых есть тег `monitoring=enabled`.

```yaml
relabel_configs:
  # source_labels - из какой мета-метки брать значение
  - source_labels: [__meta_openstack_tag_monitoring] 
    # regex - какое регулярное выражение применить
    regex: 'enabled'
    # action - что сделать при совпадении
    action: keep
```

### Действие: `replace` (Переименование/Замена)

Позволяет заменить значение одной метки на другое.

**Пример:** Привести значения метки `team` к единому виду (убрать окончание `ing`).

```yaml
relabel_configs:
  - source_labels: [team]
    regex: '(.*)ing' # Найти "ing" в конце
    replacement: '$1' # Заменить на первую группу захвата (все, что было до "ing")
    target_label: team # Применить к метке 'team'
    action: replace
```
`developing` -> `develop`

### Действие: `labelmap` (Копирование меток)

Позволяет скопировать значение из одной метки в другую, используя имя исходной метки как шаблон для имени новой.

**Пример:** Скопировать все мета-теги OpenStack в обычные метки, убрав префикс.

```yaml
relabel_configs:
  # Найти все метки, начинающиеся с __meta_openstack_tag_
  - regex: __meta_openstack_tag_(.+)
    # Создать новую метку, имя которой - это часть после префикса, 
    # а значение - значение исходной мета-метки.
    replacement: '$1'
    action: labelmap
```
`__meta_openstack_tag_project: billing` -> `project: billing`

### Действие: Извлечение из списка меток

Некоторые механизмы Service Discovery (например, [Consul](../Consul/consul_overview.md)) могут предоставлять метаданные в виде списков. С помощью регулярных выражений можно извлечь нужные значения.

**Пример:** Если в списке тэгов Consul присутствует тэг с именем `prod`, `staging` или `dev`, сохранить имя этого тэга как значение лейбла `env`.

```yaml
relabel_configs:
  - source_labels: [__meta_consul_tag]
    regex: '.*,(prod|staging|dev),.*'
    target_label: env
    action: replace
```

### Действие: `labeldrop` / `labelkeep` (Удаление меток)

*   `labeldrop`: Удалить все метки, имена которых соответствуют регулярному выражению.
*   `labelkeep`: Сохранить только те метки, имена которых соответствуют регулярному выражению.

**Пример:** Удалить все метки, содержащие `temp`.

```yaml
relabel_configs:
  - regex: '.*temp.*'
    action: labeldrop
```
> **Внимание!** Используйте `labelkeep` с осторожностью, так как можно случайно удалить служебные метки, такие как `__address__`, что сделает сбор метрик невозможным.