# StatefulSet: Лучшие практики

* **Используйте PodDisruptionBudget** для защиты от плановых выселений при обслуживании нод. См. [Высокая доступность](../high_availability.md).
* **Настройте readinessProbe** для корректного определения готовности пода к приему трафика.
* **Используйте `volumeBindingMode: WaitForFirstConsumer`** в StorageClass для корректного размещения томов.
* **Регулярно делайте бэкапы** PVC, даже несмотря на их постоянство.
* **Применяйте podAntiAffinity** для распределения подов по разным зонам доступности. См. [Affinity и Anti-Affinity](../../Scheduling/affinity.md).
