# Конфигурация Alertmanager в kube-prometheus-stack

> ℹ️ Для детального изучения Alertmanager обратитесь к основной заметке: [alertmanager](../alertmanager.md).

*   `alertmanager.enabled`: `true`
    *   **Рекомендация:** Оставить включенным для управления алертами.

*   `alertmanager.ingress.enabled`: `false`
    *   **Описание:** Создает Ingress-ресурс для доступа к веб-интерфейсу Alertmanager.
    *   **Рекомендация:** Можно оставить выключенным, так как основной интерфейс для работы — это Grafana.

*   `alertmanager.persistentVolume.enabled`: `true`
    *   **Описание:** Включает использование PersistentVolume для сохранения состояния Alertmanager (например, созданных "подавлений" - silences).
    *   **Рекомендация (Production):** Обязательно `true`, чтобы сделать его stateful.
    *   `storageClass`: Необходимо указать имя существующего в кластере `StorageClass`.
    *   `size`: Размер диска подбирается эмпирически, можно начать с `2Gi`.

*   `alertmanager.replicaCount`: `1`
    *   **Рекомендация (Production):** Установить значение `3` для обеспечения высокой доступности и кворума.

*   `alertmanager.resources`:
    *   **Описание:** Запросы (`requests`) и лимиты (`limits`) по CPU и Memory.
    *   **Рекомендация:** Подбираются эмпирически. Можно начать с минимальных значений (`requests: cpu: 100m, memory: 32Mi`) и наблюдать за потреблением.
