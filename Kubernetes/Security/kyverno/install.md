# Установка Kyverno

Установка Kyverno в кластер Kubernetes осуществляется через **Helm Chart**.

При установке разворачиваются **4 компонента**:

* **Admission Controller**: Обрабатывает mutating и validating admission webhook-запросы.
* **Background Controller**: Обрабатывает создание и обновление ресурсов в фоновом режиме.
* **Cleanup Controller**: Удаляет ресурсы, помеченные на очистку.
* **Reports Controller**: Генерирует отчеты о применении политик.
