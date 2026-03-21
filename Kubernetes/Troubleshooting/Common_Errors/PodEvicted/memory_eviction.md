# Pod Evicted: Нехватка памяти

## 1. Eviction из-за нехватки памяти (`MemoryPressure`)

**Сообщение:**

```
The node was low on resource: memory.
```

**Причина:** Суммарное потребление памяти подами превышает доступную память узла.

**Диагностика:**

```bash
# Проверка доступной памяти
free -h

# Потребление подами
kubectl top pod --all-namespaces --sort-by=memory

# OOM события в ядре
dmesg -T | grep -i "oom"
```

**Решение:**

| Вариант | Описание |
|---------|----------|
| **Увеличить `limits.memory`** | Для подов с низким приоритетом |
| **Добавить узлы** | Горизонтальное масштабирование |
| **Уменьшить потребление** | Оптимизация приложений |
| **Настроить QoS** | Использовать `Guaranteed` для критичных подов |

**Prevention:**

```yaml
# Настройка eviction thresholds в kubelet
# /var/lib/kubelet/config.yaml
evictionHard:
  memory.available: "200Mi"
  nodefs.available: "10%"
evictionSoft:
  memory.available: "500Mi"
evictionSoftGracePeriod:
  memory.available: 2m
```

> **См. также:** [`oomkilled_pods.md`](../oomkilled_pods.md)
