# Pod Terminating: Graceful Shutdown

## Graceful shutdown

```yaml
# Настройка graceful shutdown
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  terminationGracePeriodSeconds: 60  # Увеличенное время
  containers:
  - name: app
    image: my-app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 10; kill -TERM 1"]
```

## Сравнение методов удаления

| Метод | Описание | Когда использовать |
|-------|----------|-------------------|
| `kubectl delete pod` | Стандартное удаление | Нормальный случай |
| `--grace-period=N` | Задать время ожидания | Приложение требует больше времени |
| `--force --grace-period=0` | Принудительное | Pod застрял в Terminating |
| `kubectl patch finalizers` | Удаление finalizers | Крайняя мера, когда ничего не помогает |

> **Warning:** Принудительное удаление не решает проблему на узле. Volume может остаться в состоянии "attached", данные могут быть потеряны.

## Best Practices

| Практика | Описание |
|----------|----------|
| **Настройте preStop hook** | Graceful shutdown приложений |
| **Используйте PDB** | Защита от массового удаления |
| **Мониторьте finalizers** | Алерты на долгие Terminating |
| **Избегайте force delete** | Только когда другие методы не работают |
| **Проверяйте volumes** | Перед удалением finalizers |

## Ссылки

- [Pod Termination](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination)
- [Finalizers](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/)
- [Graceful Shutdown](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination)
