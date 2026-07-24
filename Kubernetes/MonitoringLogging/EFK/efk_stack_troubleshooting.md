# Устранение неполадок стека EFK в Kubernetes

<!--
Reliability: 10 (SSoT + Web: Практики диагностики ES 8.x и K8s 1.30+)
Freshness: 10 (Июль 2026)
-->

> **Примечание:** Данный файл является специализированным руководством по диагностике в среде Kubernetes. Общие концепции и базовое решение проблем поиска описаны в документе [Elasticsearch: Обзор](../../../ELK_Stack/Elasticsearch/elasticsearch_overview.md).

## Определения

**[CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md)** — статус циклической перезагрузки контейнера. Частая причина для Fluent Bit — ошибки конфигурации или недоступность Elasticsearch.

**`mapper_parsing_exception`** — ошибка в Elasticsearch, возникающая при несоответствии типа данных поля (например, число вместо строки) в новом документе ранее определенному маппингу индекса или Data Stream.

**`security_exception`** — (характерно для 8.x) ошибка аутентификации. Возникает при использовании неверных учетных данных или отсутствии прав у пользователя `elastic`/`fluent-bit`.

**Статусы здоровья кластера (Cluster Health)**:
*   **Green**: все шарды (основные и реплики) распределены и доступны.
*   **Yellow**: все основные шарды доступны, но некоторые реплики не распределены (кластер уязвим к сбоям узлов).
*   **Red**: часть основных шардов недоступна (потеря данных или частичная неработоспособность).

## Основные концепции диагностики

Процесс поиска неисправностей в Kubernetes должен быть последовательным:

1.  **Инспекция ресурсов**: проверка статуса подов и событий.
    ```bash
    kubectl get pods -n logging
    kubectl describe pod <pod-name> -n logging
    ```

2.  **Анализ логов**: изучение вывода компонентов.
    ```bash
    # Для Fluent Bit (поиск ошибок OUTPUT)
    kubectl logs -l app.kubernetes.io/name=fluent-bit -n logging --tail=100
    # Для Elasticsearch (поиск причин Red status)
    kubectl logs elasticsearch-master-0 -n logging | grep -i "error"
    ```

3.  **Сетевая связность и TLS**: проверка доступности API и сертификатов.
    ```bash
    # Проверка доступности с игнорированием проверки сертификата (для 8.x)
    kubectl exec <fluent-bit-pod> -n logging -- curl -k -u elastic:$PASS https://elasticsearch-master:9200
    ```

4.  **Инструментальная отладка**: использование эфемерных контейнеров (для K8s 1.25+).
    ```bash
    kubectl debug <pod-name> -it --image=nicolaka/netshoot -n logging
    ```

## Практические сценарии

### Сценарий 1: Проблемы безопасности и TLS (Elasticsearch 8.x)

**Симптом: Fluent Bit выдает ошибки "SSL handshake failed" или "401 Unauthorized".**

*   **SSL Certificate Unknown**: Если используется self-signed сертификат (по умолчанию в ECK/Helm), Fluent Bit должен либо доверять CA, либо иметь настройку `TLS.Verify Off` (не рекомендуется для prod).
    *   *Решение*: Смонтируйте секрет `elasticsearch-master-certs` в под Fluent Bit и укажите `TLS.CA_File`.
*   **Authentication Error**: Пароль пользователя `elastic` был изменен или неверно передан в секрет.
    *   *Решение*: Проверьте значение в секрете `kubectl get secret elasticsearch-master-credentials -o jsonpath='{.data.password}' | base64 -d`.

### Сценарий 2: Проблемы сбора логов (Fluent Bit)

**Симптом: логи не появляются в Kibana, ошибок в Elasticsearch нет.**

*   **Неверные пути (Input)**: Агент ищет логи там, где их нет (например, `/var/lib/docker/containers` в кластерах с `containerd`).
    *   *Решение*: Проверьте `Path` в `[INPUT]`. Для современных кластеров это обычно `/var/log/containers/*.log`.
*   **Backpressure (Mem_Buf_Limit)**: Fluent Bit потребляет слишком много памяти и убивается OOM Killer.
    *   *Решение*: Установите `Mem_Buf_Limit 50MB` в секции `[INPUT]`. Если буфер полон, агент приостановит чтение до освобождения места.

### Сценарий 3: Деградация кластера Elasticsearch (Red/Yellow)

**Симптом: медленный поиск, ошибки записи, статус Red.**

*   **Low Disk Watermark**: Диск заполнен на 85-90%. ES переводит индексы в `read-only`.
    *   *Решение*: Расширьте PVC или удалите старые индексы. Сбросьте блокировку:
        ```bash
        curl -XPUT -u elastic:$PASS "https://es:9200/_all/_settings" -H 'Content-Type: application/json' -d'{"index.blocks.read_only_allow_delete": null}'
        ```
*   **Unassigned Shards**: Шарды не могут быть размещены (например, из-за нехватки узлов для реплик).
    *   *Решение*: Проверьте причину через API:
        ```bash
        curl -u elastic:$PASS "https://es:9200/_cluster/allocation/explain?pretty"
        ```

### Сценарий 4: Конфликты маппинга (Mapping Conflicts)

**Симптом: Ошибка `mapper_parsing_exception` в логах Fluent Bit.**

*   **Причина**: В одном индексе поле `request_time` — это `float`, а в новом логе пришла строка `"0.05"`.
*   **Решение**:
    1.  Используйте `Replace_Dots On` во Fluent Bit, чтобы избежать конфликтов с вложенными объектами.
    2.  Настройте Ingest Pipeline в Elasticsearch для принудительного приведения типов.
    3.  При использовании **Data Streams** — обновите Index Template и дождитесь ротации (`rollover`).

## Дополнительная информация

*   [Настройка стека EFK](./efk_stack_setup_guide.md) — развертывание и базовые параметры.
*   [Практическое руководство по Kibana](./kibana_guide.md) — поиск логов и создание дашбордов.
*   [Управление индексами (ILM)](../../../ELK_Stack/Elasticsearch/elasticsearch_ilm_and_retention.md) — настройка автоматической очистки данных.
*   [Elasticsearch: Обзор](../../../ELK_Stack/Elasticsearch/elasticsearch_overview.md) — статусы кластера и общая архитектура.
