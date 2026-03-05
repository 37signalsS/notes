# CreateContainerConfigError: Диагностика

## Диагностика: пошаговый чек-лист

### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в разделе `Events`:**

```
Type     Reason     Age                From               Message
----     ------     ----               ----               -------
Warning  Failed     56s (x6 over 1m)   kubelet            Error: configmap "missing-config" not found
Warning  Failed     56s (x6 over 1m)   kubelet            Error: secret "missing-secret" not found
Warning  Failed     40s (x6 over 1m)   kubelet            Error: persistentvolumeclaim "data-pvc" not found
```

### Шаг 2: Проверка ConfigMap

```bash
# Проверка существования
kubectl get configmap <configmap-name> -n <namespace>

# Проверка содержимого
kubectl get configmap <configmap-name> -o yaml

# Поиск всех ConfigMap в namespace
kubectl get configmap -n <namespace>
```

### Шаг 3: Проверка Secret

```bash
# Проверка существования
kubectl get secret <secret-name> -n <namespace>

# Проверка типа
kubectl get secret <secret-name> -o jsonpath='{.type}'

# Проверка ключей
kubectl get secret <secret-name> -o jsonpath='{.data}'
```

### Шаг 4: Проверка PVC

```bash
# Статус PVC
kubectl get pvc -n <namespace>

# Описание PVC
kubectl describe pvc <pvc-name> -n <namespace>

# Проверка привязки
kubectl get pvc -n <namespace> -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,VOLUME:.spec.volumeName
```

### Скрипт автоматической диагностики

```bash
#!/bin/bash
# Скрипт диагностики CreateContainerConfigError

POD=$1
NS=${2:-default}

echo "=== Описание пода ==="
kubectl describe pod $POD -n $NS | grep -A 5 "Events:"

echo -e "\n=== Проверка ConfigMap ==="
kubectl get configmap -n $NS

echo -e "\n=== Проверка Secret ==="
kubectl get secret -n $NS

echo -e "\n=== Проверка PVC ==="
kubectl get pvc -n $NS

echo -e "\n=== Проверка VolumeMounts ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.volumes}'
```
