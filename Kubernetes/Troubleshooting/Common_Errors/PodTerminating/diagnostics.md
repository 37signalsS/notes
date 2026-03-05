# Pod Terminating: Диагностика

## Диагностика: пошаговый чек-лист

### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в выводе:**

```
Name:         my-pod
Namespace:    default
Status:       Terminating
Deletion Timestamp:  2026-03-05T10:00:00Z
Finalizers:    [kubernetes.io/pod-protection external-attacher/csi-driver]
```

### Шаг 2: Проверка finalizers

```bash
# Проверка finalizers
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'

# Полная информация в JSON
kubectl get pod <pod-name> -o json
```

### Шаг 3: Проверка volumes

```bash
# Volumes пода
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes}'

# Mounts на узле (требуется SSH)
findmnt | grep <pod-uid>
```

### Шаг 4: Проверка узла

```bash
# Статус узла
kubectl get node <node-name>

# Events узла
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name>
```

### Шаг 5: Получение UID пода

```bash
kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}'
```

### Автоматизация диагностики

```bash
#!/bin/bash
# Скрипт диагностики Terminating pod

POD=$1
NS=${2:-default}

echo "=== Статус пода ==="
kubectl get pod $POD -n $NS -o wide

echo -e "\n=== Finalizers ==="
kubectl get pod $POD -n $NS -o jsonpath='{.metadata.finalizers}'
echo

echo -e "\n=== Volumes ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.volumes}'
echo

echo -e "\n=== Описание ==="
kubectl describe pod $POD -n $NS | grep -A 10 "Status:\|Finalizers:\|Conditions:"

echo -e "\n=== События ==="
kubectl get events -n $NS --field-selector involvedObject.name=$POD --sort-by='.lastTimestamp'
```
