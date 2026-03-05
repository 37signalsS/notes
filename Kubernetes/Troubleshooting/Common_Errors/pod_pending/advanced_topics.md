# Pod в состоянии `Pending`: Дополнительная информация

## Взаимодействие механизмов планирования

```
Планировщик проверяет (в порядке):
1. NodeSelector (простой)
2. NodeAffinity (продвинутый)
3. Taints/Tolerations (фильтр)
4. PodAffinity/PodAntiAffinity (относительно других подов)
5. ResourceRequests (CPU, Memory)
6. TopologySpreadConstraints (распределение)
```

> **Важно:** Все правила должны выполняться одновременно. Слишком сложные комбинации могут привести к вечному `Pending`.

---

## Таблица решений

| Симптом | Первая команда | Вероятное решение |
|---------|----------------|-------------------|
| `Insufficient cpu/memory` | `kubectl top nodes` | Уменьшить requests / добавить узлы |
| `didn't match node affinity` | `kubectl get nodes --show-labels` | Добавить метку / исправить affinity |
| `had taint ... didn't tolerate` | `kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints` | Добавить toleration |
| `unbound PersistentVolumeClaims` | `kubectl describe pvc` | Создать PV / исправить StorageClass |
| `failed quota` | `kubectl describe resourcequota` | Увеличить квоту / уменьшить requests |

---

## Мониторинг Pending подов

```bash
# Все Pending поды
kubectl get pods --field-selector status.phase=Pending

# Pending поды с сортировкой по времени
kubectl get pods --field-selector status.phase=Pending --sort-by='.metadata.creationTimestamp'

# Алерт Prometheus
alert: PendingPodsHigh
expr: count(kube_pod_status_phase{phase="Pending"}) > 5
for: 5m
```

> **См. также:** [`pod_distribution.md`](../../Autoscaling/pod_distribution.md)

---

## Best Practices

| Практика | Описание |
|----------|----------|
| **Всегда указывайте `requests` и `limits`** | Предсказуемое планирование, QoS |
| **Используйте `nodeAffinity` вместо `nodeSelector`** | Больше гибкости |
| **Комбинируйте с `tolerations`** | Для системных подов |
| **Настройте `topologySpreadConstraints`** | Высокая доступность |
| **Мониторьте Pending поды** | Алерты на Pending > 5 минут |

---

## Ссылки

- [Kubernetes Scheduler](https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/)
- [Pod Priority and Preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/)
- [Configure Pod Assignment](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)

---

## Ссылки на связанные файлы

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Практические сценарии](./practical_scenarios.md) — диагностика и решения
