# Руководство: Настройка кластера Elasticsearch 8.x

> Эта заметка является частью обзора [ELK стека](../elk_stack_overview.md) и описывает пошаговую настройку мультинодового кластера Elasticsearch 8.x.
>
> Базовые понятия (роли узлов, шарды и реплики, статусы здоровья) — в [Обзоре Elasticsearch](../Elasticsearch/elasticsearch_overview.md).

## Определения

* **Токен регистрации (Enrollment Token)** — механизм автоматической настройки безопасности в Elasticsearch 8.x. Позволяет новому узлу или Kibana безопасно присоединиться к кластеру, автоматически получая сертификаты CA и необходимые настройки TLS от первого узла.
* **Проверки при загрузке (Bootstrap Checks)** — системные проверки, которые выполняет Elasticsearch при переходе в "production mode" (когда `network.host` не является loopback-адресом). Если проверки не пройдены, узел не запустится.

## Основные концепции

### Ключевые параметры конфигурации

| Параметр | Назначение | Особенности |
| :--- | :--- | :--- |
| **`cluster.name`** | Имя кластера | Должно быть идентичным на всех узлах. |
| **`node.name`** | Уникальное имя узла | По умолчанию — имя хоста. |
| **`network.host`** | IP-адрес для прослушивания | Установка значения, отличного от `localhost`, активирует **Bootstrap Checks**. |
| **`discovery.seed_hosts`** | Список узлов для обнаружения | IP-адреса мастер-нод. Используется для поиска кластера при старте. |
| **`cluster.initial_master_nodes`** | Начальные мастер-узлы | Используется **только один раз** при самом первом создании кластера. |

### Системные настройки (Bootstrap Checks)

Перед запуском в промышленной среде необходимо настроить ОС:

1. **Виртуальная память (mmap)**: Elasticsearch использует `mmap` для хранения индексов. Лимит должен быть увеличен:
    * `sysctl -w vm.max_map_count=262144` (или в `/etc/sysctl.conf`).
2. **Лимиты файлов (ulimits)**: Увеличьте количество открытых файлов для пользователя `elasticsearch` до 65536 в `/etc/security/limits.conf`.
3. **Отключение Swap**: Рекомендуется полностью отключить swap для предотвращения задержек GC.

## Практические сценарии

### Сценарий 1: Автоматическая настройка (Enrollment Token)

Рекомендуемый способ для новых кластеров, использующий встроенный CA.

#### Шаг 1: Установка и первый запуск

1. Установите Elasticsearch на все узлы.
2. На **первом узле** запустите сервис без предварительной настройки `elasticsearch.yml`:

    ```bash
    sudo systemctl start elasticsearch
    ```

3. **Важно:** При первом запуске в консоль (или в `/var/log/elasticsearch/`) будут выведены:
    * Пароль суперпользователя `elastic`.
    * Токен регистрации для новых узлов.
    * Токен регистрации для Kibana.

#### Шаг 2: Добавление новых узлов

1. Сгенерируйте новый токен на первом узле, если старый истек (30 мин):

    ```bash
    sudo /usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s node
    ```

2. На новом узле выполните команду настройки, указав токен:

    ```bash
    sudo /usr/share/elasticsearch/bin/elasticsearch-reconfigure-node --enrollment-token <TOKEN>
    ```

3. Отредактируйте `elasticsearch.yml`, задав `node.name` и `network.host`, затем запустите сервис.

---

### Сценарий 2: Ручная настройка (Custom CA)

Используется, если политика безопасности требует использования корпоративного Центра Сертификации.

#### Шаг 1: Генерация сертификатов

1. Создайте сертификаты для транспортного уровня (Transport TLS) и HTTP с помощью утилиты `bin/elasticsearch-certutil`.
2. Скопируйте сертификаты в директорию `/etc/elasticsearch/certs/` на все узлы.

#### Шаг 2: Настройка `elasticsearch.yml`

На всех узлах настройте параметры безопасности вручную:

```yaml
cluster.name: production-cluster
network.host: 10.0.0.1
discovery.seed_hosts: ["10.0.0.1", "10.0.0.2", "10.0.0.3"]

# Security Settings
xpack.security.enabled: true
xpack.security.transport.ssl.enabled: true
xpack.security.transport.ssl.verification_mode: certificate
xpack.security.transport.ssl.keystore.path: certs/transport.p12
xpack.security.transport.ssl.truststore.path: certs/transport.p12

xpack.security.http.ssl.enabled: true
xpack.security.http.ssl.keystore.path: certs/http.p12
```

#### Шаг 3: Инициализация кластера

На первом узле при самом первом запуске добавьте:
`cluster.initial_master_nodes: ["node-1", "node-2", "node-3"]`

> После формирования кластера этот параметр следует удалить или закомментировать.

---

### Проверка состояния

```bash
# Проверка списка узлов и их ролей
curl -k -u elastic:$ELASTIC_PASSWORD "https://localhost:9200/_cat/nodes?v"

# Проверка распределения шардов
curl -k -u elastic:$ELASTIC_PASSWORD "https://localhost:9200/_cat/shards?v"

# Объяснение аллокации (полезно при статусе Yellow/Red)
curl -k -u elastic:$ELASTIC_PASSWORD "https://localhost:9200/_cluster/allocation/explain?pretty"
```

## Дополнительная информация

### Типичные проблемы

* **`mmap` limit reached**: Узел падает сразу после старта. Решение: увеличить `vm.max_map_count`.
* **Certificate Expired**: Узлы теряют связь. Регулярно проверяйте срок действия сертификатов, если используете ручную настройку.
* **Quorum Loss**: Если упало более половины мастер-узлов, кластер перестанет принимать запросы. Потребуется процедура восстановления кворума.

### Рекомендации

* **JVM Heap**: Настраивайте в `/etc/elasticsearch/jvm.options.d/heap.options`. Выделяйте 50% RAM, но не более 31 ГБ. Подробное обоснование — в [Обзоре Elasticsearch](../Elasticsearch/elasticsearch_overview.md#оптимизация-производительности).
* **Dedicated Masters**: В кластерах более 10 узлов выделяйте 3 узла только с ролью `master`.
* **Мониторинг**: Используйте `elasticsearch_exporter` для сбора метрик в Prometheus.

> **См. также:**
> * [Elasticsearch: Жизненный цикл индексов (ILM)](../Elasticsearch/elasticsearch_ilm_and_retention.md)
> * [Сравнение Elasticsearch и OpenSearch](../OpenSearch/opensearch_overview.md)
