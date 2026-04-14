# Api Access Forbidden: Диагностика

## Definitions

**Диагностика API access ошибок** — пошаговый процесс определения причины 401/403 и выбора решения. Цель — минимизировать время обнаружения проблемы.

> Краткая диагностика в конкретных сценариях: [common.md](common.md), [authentication_methods.md](authentication_methods.md)

## Basic Concepts

### Диагностическое дерево

```
Получена ошибка API
    ↓
Шаг 1: Какой код? (401 или 403)
    ├── 401 → Шаг 2a: Аутентификация
    └── 403 → Шаг 2b: Авторизация
         ↓
    Шаг 3: Какой субъект? (SA, User, Group)
         ↓
    Шаг 4: Какие RoleBinding/ClusterRoleBinding?
         ↓
    Шаг 5: Решение
```

### Ключевые инструменты

| Инструмент | Назначение | Когда использовать |
|------------|------------|-------------------|
| `kubectl auth can-i` | Проверка прав субъекта | 403 — нет прав |
| `kubectl get rolebinding` | Поиск привязок | 403 — нет binding |
| `kubectl describe sa` | Проверка токенов SA | 401 — проблемы с токеном |
| `kubectl config view` | Проверка kubeconfig | 401 — неверный контекст |
| `-v=8` | HTTP-трейс запросов | Определение 401 vs 403 |

## Practical Scenarios

### Шаг 1: Определение типа ошибки

```bash
# Запуск с HTTP-трейсом
kubectl get pods -v=8 2>&1 | grep "HTTP/"

# Результаты:
# HTTP/1.1 401 Unauthorized → аутентификация
# HTTP/1.1 403 Forbidden → авторизация
```

> Подробнее о различиях 401/403: [definitions.md](definitions.md)

### Шаг 2a: Диагностика 401 (аутентификация)

```bash
# Текущий контекст
kubectl config current-context

# Пользователь контекста
kubectl config view --minify -o jsonpath='{.users[0].name}'

# Проверка токена (для ServiceAccount, K8s <1.24)
kubectl get secret $(kubectl get serviceaccount default \
  -o jsonpath='{.secrets[0].name}') \
  -o jsonpath='{.data.token}' | base64 -d
```

**Частые причины 401:**

- Истёкший токен ServiceAccount
- Истёкший клиентский сертификат
- Неверный kubeconfig (смена кластера/контекста)

> Полная диагностика 401: [authentication_methods.md](authentication_methods.md)

### Шаг 2b: Диагностика 403 (авторизация)

```bash
# Проверка прав текущего пользователя
kubectl auth can-i get pods -n default
kubectl auth can-i list secrets -n kube-system

# Проверка прав от имени ServiceAccount
kubectl auth can-i get pods \
  --as=system:serviceaccount:my-ns:my-sa \
  -n my-ns

# Список всех прав субъекта
kubectl auth can-i --list --as=system:serviceaccount:my-ns:my-sa
```

> Подробнее: [common.md](common.md), [advanced.md](advanced.md)

### Шаг 3: Определение ServiceAccount пода

```bash
# SA пода
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Детали SA
kubectl get serviceaccount <sa-name> -n <namespace> -o yaml

# Secrets SA (токены)
kubectl get serviceaccount <sa-name> -n <namespace> \
  -o jsonpath='{.secrets}'

# Автомонтирование токена
kubectl get serviceaccount <sa-name> -n <namespace> \
  -o jsonpath='{.automountServiceAccountToken}'
```

### Шаг 4: Проверка RoleBinding и ClusterRoleBinding

```bash
# RoleBinding в namespace
kubectl get rolebinding -n <namespace> -o wide

# ClusterRoleBinding
kubectl get clusterrolebinding -o wide

# Поиск binding для конкретного SA
kubectl get rolebinding -n <namespace> -o yaml | \
  grep -B 5 -A 5 "name: <sa-name>"

# ClusterRoleBinding для SA
kubectl get clusterrolebinding -o yaml | \
  grep -B 10 "system:serviceaccount:<namespace>:<sa-name>"
```

### Шаг 5: Расширенная диагностика

```bash
# Подробный вывод RoleBinding
kubectl get rolebinding <binding-name> -n <namespace> -o yaml

# Проверка правил ClusterRole
kubectl get clusterrole <role-name> -o yaml

# Dry-run — проверка без реальных изменений
kubectl auth reconcile -f rbac.yaml --dry-run=client

# API audit logs (если включены)
kubectl logs -n kube-system kube-apiserver-<node> | \
  grep "Forbidden"
```

## Additional Information

### Автоматизация проверки прав

```bash
#!/bin/bash
# Проверка всех прав ServiceAccount

SA=${1:?ServiceAccount name required}
NS=${2:-default}

echo "=== Права для $SA в namespace $NS ==="

# RoleBinding
echo -e "\n--- RoleBinding ---"
kubectl get rolebinding -n "$NS" -o yaml | \
  grep -B 10 "name: $SA"

# ClusterRoleBinding
echo -e "\n--- ClusterRoleBinding ---"
kubectl get clusterrolebinding -o yaml | \
  grep -B 15 "system:serviceaccount:$NS:$SA"

# Проверка прав
echo -e "\n--- can-i --list ---"
kubectl auth can-i --list --as=system:serviceaccount:"$NS":"$SA"
```

### Связанные ресурсы

- Определения 401/403: [definitions.md](definitions.md)
- Методы аутентификации: [authentication_methods.md](authentication_methods.md)
- Распространённые 403: [common.md](common.md)
- Расширенные 403: [advanced.md](advanced.md)
- RBAC объекты: [rbac_objects.md](rbac_objects.md)
- Лучшие практики: [best_practices.md](best_practices.md)
