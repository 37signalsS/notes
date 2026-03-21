# Pod Terminating: Узел недоступен

## 4. Узел недоступен

**Сообщение:**

```
Node <node-name> is unreachable
```

**Причина:** Узел в статусе `NotReady` или `Unknown`, kubelet не отвечает.

**Диагностика:**

```bash
kubectl get nodes
kubectl describe node <node-name>
```

**Решение:**

```bash
# Если узел не вернется — принудительное удаление
kubectl delete pod <pod-name> --force --grace-period=0

# Для StatefulSet — важно удалить PVC отдельно если нужно
kubectl delete pvc <pvc-name>
```
