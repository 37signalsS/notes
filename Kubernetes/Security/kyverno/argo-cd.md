# Интеграция Kyverno с Argo CD

При совместном использовании Kyverno и Argo CD необходимо учитывать ряд нюансов для корректной работы.

## Конфликт меток (Resource Tracking)

Argo CD и Kyverno используют одинаковый механизм отслеживания ресурсов через метки (`labels`). Для предотвращения конфликта необходимо перевести Argo CD на использование **annotations** вместо labels.

* **Решение**: В `values.yaml` Argo CD указать параметр `resourceTrackingMethod: annotation`.

## Server-side Diff

Argo CD по умолчанию сравнивает манифесты из Git с состоянием в кластере. При использовании Kyverno (который может мутировать манифесты) возникает бесконечный цикл синхронизации.

* **Решение**: Включить `server-side diff` в Argo CD.
  * Глобально: в `values.yaml` параметр `controller.diff.serverSide: true`.
  * Для конкретного приложения: аннотация `argocd.argoproj.io/compare-options: ServerSideDiff=true`.

## Mutation Webhooks

Kyverno может изменять (мутировать) манифесты в процессе admission. Argo CD необходимо учитывать эти изменения при сравнении.

* **Решение**: Добавить аннотацию `argocd.argoproj.io/sync-option: IncludeMutationWebhook=true` к приложению в Argo CD.
* **Примечание**: Работает только при включенном `server-side diff`.

## Aggregated Roles

Kyverno использует Aggregated Cluster Roles, что приводит к динамическому изменению ролей. Argo CD может некорректно обрабатывать эти изменения.

* **Решение**: В `values.yaml` Argo CD указать `resource.compare: ignoreAggregatedRoles: true`.

## Важное примечание по установке

При установке Kyverno через Argo CD **обязательно** использовать параметр `spec.syncPolicy.automated.applyServerSide: true`. Параметр `spec.syncPolicy.automated.replace: true` использовать **нельзя** (на момент съемки видео в документации была ошибка).
