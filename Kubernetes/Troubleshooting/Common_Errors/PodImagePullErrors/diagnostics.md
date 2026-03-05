# Pod Image Pull Errors: Диагностика

## Диагностика: пошаговый чек-лист

### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

**Ищите в разделе `Events`:**

```
Type     Reason     Age                From               Message
----     ------     ----               ----               -------
Warning  Failed     2m (x4 over 3m)    kubelet            Failed to pull image "my-app:1.1": rpc error: code = Unknown desc = Error response from daemon: manifest for my-app:1.1 not found
Warning  Failed     2m (x4 over 3m)    kubelet            Error: ErrImagePull
Normal   BackOff    1m (x6 over 2m)    kubelet            Back-off pulling image "my-app:1.1"
Warning  Failed     1m (x6 over 2m)    kubelet            Error: ImagePullBackOff
```

### Шаг 2: Проверка имени образа

```bash
# Извлечение имени образа из пода
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].image}'

# Проверка наличия образа в registry
docker pull <image-name>
# или
crane pull <image-name> <local-file>
```

### Шаг 3: Проверка imagePullSecrets

```bash
# Проверка secrets в поде
kubectl get pod <pod-name> -o jsonpath='{.spec.imagePullSecrets}'

# Проверка существования secret
kubectl get secret <secret-name> -o yaml

# Проверка типа secret
kubectl get secret <secret-name> -o jsonpath='{.type}'
```

### Шаг 4: Проверка сети и DNS

```bash
# Проверка доступности registry с узла
ssh <node-name> "curl -I https://registry.example.com"

# Проверка DNS
ssh <node-name> "nslookup registry.example.com"

# Проверка firewall правил
ssh <node-name> "telnet registry.example.com 443"
```
