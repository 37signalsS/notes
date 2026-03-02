# Дополнительная информация Kyverno

## Aggregated Cluster Roles

По умолчанию Kyverno не имеет прав на создание некоторых ресурсов (например, `Secret`). Для расширения прав используются **Aggregated Cluster Roles**.

* **Mechanism**: Создание `ClusterRole` с лейблом `kyverno.io/aggregate-to-<controller>-controller: "true"`, где `<controller>` — один из: `admission`, `background`, `reports`, `cleanup`.
* **Controllers**:
  * `admission-controller`: Обрабатывает запросы admission webhooks.
  * `background-controller`: Обрабатывает создание и обновление ресурсов.
  * `reports-controller`: Обрабатывает Policy Reports.
  * `cleanup-controller`: Обрабатывает удаление ресурсов.
* **Пример**: Для генерации `Secret` необходимы права `create` на ресурсы `Secret` с лейблом `kyverno.io/aggregate-to-background-controller: "true"`.

## Историческая справка

В Kubernetes 1.25 были удалены **Pod Security Policies (PSP)**. Kyverno рассматривался как одна из альтернатив для замены PSP, наряду с другими решениями, такими как OPA Gatekeeper.
