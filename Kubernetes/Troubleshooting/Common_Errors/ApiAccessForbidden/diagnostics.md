# Api Access Forbidden: Диагностика

## Диагностика: пошаговый чек-лист

### Шаг 1: Определение типа ошибки

```bash
# Запуск команды с подробным выводом
kubectl get pods -v=8

# Ищите в выводе:
# HTTP/1.1 401 Unauthorized → Аутентификация
# HTTP/1.1 403 Forbidden → Авторизация
```

### Шаг 2: Проверка аутентификации (401)

```bash
# Проверка текущего контекста
kubectl config current-context

# Проверка пользователя
kubectl config view --minify -o jsonpath='{.users[0].name}'

# Проверка токена ServiceAccount
kubectl get secret $(kubectl get serviceaccount default -o jsonpath='{.secrets[0].name}') -o jsonpath='{.data.token}' | base64 -d
```

### Шаг 3: Проверка авторизации (403)

**Основной инструмент — `kubectl auth can-i`:**

```bash
# Проверка прав текущего пользователя
kubectl auth can-i get pods -n default
kubectl auth can-i list secrets -n kube-system

# Проверка от имени ServiceAccount
kubectl auth can-i get pods \
  --as=system:serviceaccount:my-ns:my-sa \
  -n my-ns

# Проверка всех прав
kubectl auth can-i --list

# Проверка прав для конкретного ресурса
kubectl auth can-i get deployments --all-namespaces
```

### Шаг 4: Определение ServiceAccount пода

```bash
# SA пода
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Детали SA
kubectl get serviceaccount <sa-name> -n <namespace> -o yaml

# Secrets SA
kubectl get serviceaccount <sa-name> -o jsonpath='{.secrets}'
```

### Шаг 5: Проверка RoleBinding

```bash
# RoleBinding в namespace
kubectl get rolebinding -n <namespace>

# ClusterRoleBinding
kubectl get clusterrolebinding

# Поиск binding для конкретного SA
kubectl get rolebinding -n <namespace> -o yaml | grep -B 5 -A 5 "name: <sa-name>"
```

### Автоматизация проверки прав

```bash
#!/bin/bash
# Скрипт проверки прав ServiceAccount

SA=${1:-default}
NS=${2:-default}

echo "=== Проверка прав для $SA в $NS ==="

# Получение всех RoleBinding
echo -e "\n=== RoleBinding ==="
kubectl get rolebinding -n $NS -o yaml | grep -B 5 -A 5 "$SA"

# Получение всех ClusterRoleBinding
echo -e "\n=== ClusterRoleBinding ==="
kubectl get clusterrolebinding -o yaml | grep -B 5 -A 5 "$SA"

# Проверка конкретных прав
echo -e "\n=== Проверка can-i ==="
kubectl auth can-i --list --as=system:serviceaccount:$NS:$SA
```
