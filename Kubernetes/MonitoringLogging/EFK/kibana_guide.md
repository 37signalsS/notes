# Kibana: Практическое руководство в Kubernetes

> **Примечание:** Данный файл описывает практическое использование Kibana в Kubernetes. Общий обзор Kibana и его концепций — в [Kibana: Обзор](../../../ELK_Stack/Kibana/kibana_overview.md).

## Определения

- **Discover**: Основной инструмент в Kibana для интерактивного исследования, поиска и фильтрации логов — [Kibana: Обзор](../../../ELK_Stack/Kibana/kibana_overview.md).
- **Index Pattern (Data View)**: Шаблон, который сообщает Kibana, какие индексы Elasticsearch необходимо запрашивать. Обычно включает wildcard (например, `my-cluster-*`).
- **KQL (Kibana Query Language)**: Простой и интуитивный язык запросов для фильтрации данных в строке поиска Kibana.

## Базовые концепции

Базовые концепции (KQL, Data Views) подробно описаны в [Kibana: Обзор](../../../ELK_Stack/Kibana/kibana_overview.md).

## Практические сценарии

### Создание индекс-паттерна для Kubernetes

Для логов, собираемых Fluent Bit в Kubernetes:

1. Следуйте [стандартной инструкции по созданию Data View (Index Pattern)](../../../ELK_Stack/Kibana/kibana_overview.md#создание-data-view-index-pattern).
2. В качестве шаблона индексов используйте префикс, заданный в Fluent Bit (например, `my-cluster-*` при использовании `Logstash_Prefix`).

### Поиск и фильтрация логов

Перейдите в **Discover** и выберите созданный индекс-паттерн.

**Примеры запросов KQL:**

- **Найти все логи конкретного пода:**

    ```kql
    kubernetes.pod_name: "my-app-pod-xyz123"
    ```

- **Найти все логи подов приложения (по лейблу):**

    ```kql
    kubernetes.labels.app: "my-app"
    ```

- **Показать все ошибки из неймспейса `production`:**

    ```kql
    kubernetes.namespace_name: "production" and log.level: (error or warn)
    ```

- **Показать все HTTP-запросы с ошибками (статус не 2xx):**

    ```kql
    not http.status_code: [200 to 299]
    ```

- **Найти логи с определенной фразой:**

    ```kql
    message: "payment failed"
    ```

### Кастомизация отображения полей

В Discover записи по умолчанию отображаются как JSON-документы. Для табличного представления:

1. В списке `Available fields` найдите нужные поля (например, `log`, `kubernetes.container_name`, `kubernetes.namespace_name`).
2. Нажмите `+` для добавления поля в `Selected fields`.
3. Kibana автоматически построит таблицу с выбранными колонками.

### Устранение проблем: неразобранные JSON-логи

**Симптом:** Логи отображаются как единая строка в поле `log`, а не как структурированные поля (`level`, `message`).

**Причина:** Fluent Bit не смог разобрать JSON-структуру из-за смешанных форматов или сложных вложенных JSON.

**Решение:** Настройте парсинг в Fluent Bit:

1. Включите `Merge_Log On` в фильтре `kubernetes`.
2. Для сложных случаев создайте кастомный парсер через аннотацию пода (`fluentbit.io/parser: "my-app-json"`) или глобально.
3. Подробные инструкции — [Парсинг логов в Fluent Bit](./fluentbit/parsing.md).

## Дополнительная информация

Инструкции по установке Kibana в Kubernetes — [руководство по настройке стека EFK](./efk_stack_setup_guide.md). Устранение неполадок при запуске Kibana — [руководство по устранению неполадок](./efk_stack_troubleshooting.md). Для глубокого понимания возможностей Kibana изучите [обзорный документ](../../../ELK_Stack/Kibana/kibana_overview.md).
