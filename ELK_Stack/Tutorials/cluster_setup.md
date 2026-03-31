# Руководство: Настройка кластера Elasticsearch 8

> Эта заметка является частью обзора [ELK стека](../elk_stack_overview.md) и описывает пошаговую настройку мультинодового кластера Elasticsearch 8.x.
>
> **Базовые понятия** ([кластер](../Elasticsearch/elasticsearch_overview.md#определения), [роли узлов](../Elasticsearch/elasticsearch_overview.md#основные-концепции), [шарды и реплики](../Elasticsearch/elasticsearch_overview.md#индексы-шарды-и-реплики), [статусы здоровья](../Elasticsearch/elasticsearch_overview.md#статусы-здоровья-кластера)) — в [Обзоре Elasticsearch](../Elasticsearch/elasticsearch_overview.md).

## Определения

* **Токен регистрации (Enrollment Token)**: Временный токен в Elasticsearch 8 для безопасного присоединения новых узлов к кластеру. Автоматически настраивает TLS и параметры безопасности.

## Основные концепции

### Критически важные параметры конфигурации

| Параметр | Назначение | Примечание |
| :--- | :--- | :--- |
| **`cluster.name`** | Имя кластера | Должно быть **идентичным** на всех узлах |
| **`node.name`** | Имя узла | Уникальное для каждого узла |
| **`network.host`** | IP для прослушивания | В production указывать конкретный IP |
| **`discovery.seed_hosts`** | Список узлов для обнаружения | IP-адреса всех мастер-нод |
| **`cluster.initial_master_nodes`** | Мастер-ноды для первого запуска | **Используется один раз** при инициализации кластера |

### Безопасность в Elasticsearch 8

* **TLS по умолчанию**: Весь трафик (между узлами и клиентами) шифруется.
* **Встроенные пользователи**: Предопределенные пользователи (`elastic` — суперпользователь) с генерируемыми паролями.
* **Токен регистрации**: Рекомендуемый способ добавления узлов — автоматическая настройка TLS без ручного копирования сертификатов.

## Практические сценарии

### Шаг 1: Подготовка и установка

1. **Установите Java** (рекомендуется OpenJDK) на все узлы.
2. **Установите Elasticsearch** на каждый узел (Ubuntu/Debian):

    ```bash
    sudo apt update
    sudo apt install elasticsearch
    ```

### Шаг 2: Настройка первого узла (Bootstrap)

1. **Отредактируйте `/etc/elasticsearch/elasticsearch.yml`:**

    ```yaml
    cluster.name: my-es-cluster
    node.name: node-1
    network.host: 0.0.0.0
    http.port: 9200
    transport.port: 9300
    discovery.seed_hosts: ["192.168.101.63", "192.168.101.64", "192.168.101.65"]
    cluster.initial_master_nodes: ["node-1", "node-2", "node-3"]
    ```

    > **Важно:** `cluster.initial_master_nodes` используется только при первом запуске. После формирования кластера параметр можно удалить.

### Шаг 3: Запуск и установка пароля

1. **Запустите сервис:**

    ```bash
    sudo systemctl start elasticsearch
    sudo systemctl enable elasticsearch
    ```

2. **Установите пароль для `elastic`:**

    ```bash
    sudo /usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic -i
    ```

### Шаг 4: Добавление новых узлов

1. **Сгенерируйте токен на первом узле:**

    ```bash
    sudo /usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s node
    ```

2. **На новом узле:**
    * Остановите Elasticsearch: `sudo systemctl stop elasticsearch`
    * **Очистите данные** (если узел ранее запускался):

        ```bash
        sudo rm -rf /var/lib/elasticsearch/*
        ```

    * Настройте `elasticsearch.yml` (аналогично первому узлу, но с уникальным `node.name`).
    * **Выполните присоединение:**

        ```bash
        sudo /usr/share/elasticsearch/bin/elasticsearch-reconfigure-node --enrollment-token <ВАШ_ТОКЕН>
        ```

    * Запустите Elasticsearch:

        ```bash
        sudo systemctl start elasticsearch
        sudo systemctl enable elasticsearch
        ```

3. **Повторите для всех остальных узлов.**

### Шаг 5: Проверка состояния кластера

```bash
# Список узлов
curl -k -u elastic:<пароль> "https://localhost:9200/_cat/nodes?v"

# Здоровье кластера
curl -k -u elastic:<пароль> "https://localhost:9200/_cluster/health?pretty"
```

> Флаг `-k` игнорирует проверку самоподписанного сертификата. В production используйте доверенные сертификаты.

### Шаг 6: Управление индексами

#### Создание индекса

```bash
curl -k -u elastic:<пароль> -X PUT "https://localhost:9200/my_test_index?pretty" -H 'Content-Type: application/json' -d'
{
  "settings": {
    "index.number_of_shards": 3,
    "index.number_of_replicas": 1
  }
}
'
```

#### Изменение количества реплик

```bash
curl -k -u elastic:<пароль> -X PUT "https://localhost:9200/my_test_index/_settings?pretty" -H 'Content-Type: application/json' -d'
{
  "index.number_of_replicas": 2
}
'
```

#### Просмотр шардов

```bash
curl -k -u elastic:<пароль> -X GET "https://localhost:9200/_cat/shards/my_test_index?v"
```

## Дополнительная информация

### Типичные проблемы и отладка

* **Узел не присоединяется:** Проверьте логи (`sudo journalctl -u elasticsearch -f`), совпадение `cluster.name`, сетевую связность (порты `9200`, `9300`), правильность `discovery.seed_hosts`.
* **Статус Yellow:** Не все реплики распределены. Нормально, если узлов меньше чем `1 + N (replicas)`.
* **Статус Red:** Потерян первичный шард. Серьезная проблема с потерей данных.
* **Проблемы с TLS:** Используйте токен регистрации для автоматической настройки.

### Рекомендации

* **Конкретные версии:** Избегайте тега `latest`. Указывайте проверенную версию (например, `8.11.1`).
* **Логи:** Главный источник информации для диагностики.
* **Клиенты:** Приложения должны быть спроектированы с учетом кластерной природы Elasticsearch (работа с несколькими узлами, обработка отказов).
