# Примеры Service Discovery и Relabeling

Этот документ содержит практические примеры настройки обнаружения сервисов (Service Discovery) и модификации меток (Relabeling) в Prometheus.

## 1. Статическая конфигурация (`static_config`)

Это самый простой способ определить цели для сбора метрик. Он подходит для небольшого количества хостов с неизменными адресами.

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

После добавления этой секции и перезагрузки конфигурации Prometheus (`systemctl reload prometheus`), новые таргеты появятся в веб-интерфейсе в разделе **Status -> Targets**.

## 2. Обнаружение на основе файлов (`file_sd_configs`)

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

Добавьте в `prometheus.yml` новую `job` с типом `file_sd_configs`.

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

После перезагрузки конфигурации Prometheus начнет мониторить цели, указанные в `node_exporter_hosts.yml`.

## 3. Обнаружение через API (Пример с OpenStack)

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

Prometheus будет автоматически находить все ВМ в указанном проекте и регионе и добавлять их в качестве таргетов для сбора метрик с порта `9100`.

## 4. Модификация меток (`relabel_configs`)

Для модификации меток в Prometheus существуют два основных механизма: `relabel_configs` и `metric_relabel_configs`.
*   `relabel_configs` производят все модификации **до** сбора метрик (до scraping). Они влияют на то, какие таргеты будут опрашиваться и какие метки будут иметь эти таргеты.
*   `metric_relabel_configs` производят изменения **после** сбора метрик, но **перед** их сохранением в базу данных. Они обычно используются для удаления или переименования меток уже собранных метрик. Важно отметить, что `metric_relabel_configs` не применяются к автоматически генерируемым метрикам, таким как `up`.

`relabel_configs` — это мощный механизм, который позволяет модифицировать метки таргетов *до* сбора метрик. Он используется для фильтрации, переименования и создания новых меток на основе метаданных, полученных от Service Discovery.

Все метки, предоставляемые механизмом SD, имеют префикс `__meta_`. Например, `__meta_openstack_tag_...`. Эти временные метки отбрасываются после этапа релейблинга.

### Действие: `keep` / `drop` (Фильтрация)

*   `keep`: Оставить только те таргеты, которые соответствуют регулярному выражению.
*   `drop`: Отбросить таргеты, которые соответствуют регулярному выражению.

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

**Пример:** Создать новую метку `instance_name` из мета-метки `__meta_openstack_name`.

```yaml
relabel_configs:
  - source_labels: [__meta_openstack_name]
    # Создаем новую метку с именем 'instance_name' и значением из __meta_openstack_name
    target_label: instance_name 
    action: replace
```

Более сложный пример с `labelmap`: скопировать все мета-теги OpenStack в обычные метки, убрав префикс.

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

### Действие: `Labels list` (Извлечение из списка)

Некоторые механизмы Service Discovery могут предоставлять метаданные в виде списков (например, тэги Consul). С помощью регулярных выражений можно извлечь нужные значения из такого списка.

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

---
**Связанные темы:**
*   [[./overview.md]]
*   [[./prometheus_configuration.md]]
*   [[./kubernetes/service_discovery.md]]
*   [[./concepts/labels_and_cardinality.md]]
