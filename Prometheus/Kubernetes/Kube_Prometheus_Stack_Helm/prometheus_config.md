# Конфигурация Prometheus Server в kube-prometheus-stack

Это основной компонент системы мониторинга. Общие рекомендации и лучшие практики по работе с Prometheus описаны в документе [PromTool и лучшие практики Prometheus](../promtool_and_best_practices.md). Концептуальное описание конфигурации сервера, включая Service Discovery и `relabel_configs`, можно найти в [Обзоре конфигурации сервера Prometheus](../service_discovery_and_relabeling.md).

*   `prometheus.enabled`: `true`
    *   **Рекомендация:** Оставить `true`.

*   `prometheus.prometheusSpec.scrapeInterval`, `scrapeTimeout`, `evaluationInterval`:
    *   `scrapeInterval`: Частота сбора метрик с таргетов. Подбирается эмпирически. Если метрик собирается большой объем, то есть смысл собирать их реже (например, `30s` или `1m`). Если метрик немного, то можно собирать их чаще.
    *   `scrapeTimeout`: Время, по истечении которого Prometheus будет считать, что сбор метрик с таргета не удался.
    *   `evaluationInterval`: Как часто Prometheus должен вычислять правила алертинга. Это значение также подбирается эмпирически. Например, если настроено правило на проверку количества ETCD-узлов (не менее трех), то при уменьшении их числа до двух, сигнал будет передан в AlertManager через указанный `evaluationInterval`.

*   `prometheus.prometheusSpec.remoteWrite`, `remoteRead`:
    *   **Описание:** Настройки для интеграции с внешними долгосрочными хранилищами (например, [VictoriaMetrics](../../VictoriaMetrics/victoria_metrics_overview.md), Thanos, M3DB).
    *   **Рекомендация:** Использовать в production для долгосрочного хранения метрик, так как хранение больших объемов данных в самом Prometheus неэффективно и может привести к деградации производительности.

*   `prometheus.prometheusSpec.storage`:
    *   **Описание:** Определяет конфигурацию хранилища для `StatefulSet`'а Prometheus. Использование `volumeClaimTemplate` является стандартным подходом.
    *   **Рекомендация (Production):** Обязательно настроить для сохранения данных при перезапусках.
    *   `storageClassName`: Необходимо указать имя существующего в кластере `StorageClass`.
    *   `storage`: Размер диска подбирается в зависимости от количества метрик и срока хранения (`retention`).
        ```yaml
        prometheus:
          prometheusSpec:
            storage:
              volumeClaimTemplate:
                spec:
                  storageClassName: "your-storage-class"
                  accessModes: ["ReadWriteOnce"]
                  resources:
                    requests:
                      storage: 50Gi
        ```

*   `prometheus.replicaCount`: `1`
    *   **Рекомендация (Production):** Установить значение больше `1` для высокой доступности.

*   `prometheus.prometheusSpec.retention`: `15d`
    *   **Описание:** Срок хранения метрик в локальном хранилище Prometheus. Метрики старше этого срока будут удалены.
    *   **Рекомендация:** Настраивается эмпирически в зависимости от доступного дискового пространства, требований к хранению и влияния на нагрузку сервера. Если объем метрик слишком велик, и кластер не справляется, следует уменьшить срок хранения. Для долгосрочного хранения используется `remoteWrite`.

*   `prometheus.prometheusSpec.retentionSize`: `""`
    *   **Описание:** (Альфа-версия) Позволяет ограничивать хранилище по размеру (например, `50GB`), а не только по времени.
    *   **Рекомендация:** Использовать с осторожностью, так как это экспериментальная функция.
