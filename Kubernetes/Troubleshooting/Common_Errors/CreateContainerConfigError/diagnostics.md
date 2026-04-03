# CreateContainerConfigError: Диагностика

## Definitions

**Диагностика CreateContainerConfigError** — процесс определения конкретной отсутствующей или некорректной зависимости (ConfigMap, Secret, PVC, Volume, RBAC), блокирующей создание конфигурации контейнера.

## Basic Concepts

### Workflow диагностики

```
kubectl get pod → статус
    ↓
kubectl describe pod → Events (конкретная ошибка)
    ↓
Идентификация типа зависимости
    ↓
Проверка существования ресурса
    ↓
Проверка namespace / ключей / прав доступа
    ↓
Устранение причины
```

### Ключевые команды

| Команда | Назначение |
|---------|------------|
| `kubectl describe pod <name>` | Основной источник — Events с текстом ошибки |
| `kubectl get <resource> <name>` | Проверка существования ресурса |
| `kubectl get <resource> <name> -o yaml` | Проверка содержимого |
| `kubectl auth can-i get <resource>` | Проверка прав ServiceAccount |
| `kubectl get pod <name> -o jsonpath='{.spec.volumes}'` | Проверка томов пода |

### Типичные сообщения в Events

| Сообщение | Тип зависимости | Файл решения |
|-----------|-----------------|--------------|
| `configmap "x" not found` | ConfigMap | [configmap_issues.md](./configmap_issues.md) |
| `secret "x" not found` | Secret | [secret_issues.md](./secret_issues.md) |
| `persistentvolumeclaim "x" not found` | PVC | [pvc_issues.md](./pvc_issues.md) |
| `projected volume error` | Projected Volume | [volume_issues.md](./volume_issues.md) |

## Practical Scenarios

### Сценарий 1: Полная диагностика пода

```bash
# Шаг 1: Статус пода
kubectl get pod <pod-name> -n <namespace>

# Шаг 2: Детальное описание (раздел Events)
kubectl describe pod <pod-name> -n <namespace>

# Шаг 3: Быстрый поиск ошибки
kubectl describe pod <pod-name> -n <namespace> | grep -i "Error:"
```

### Сценарий 2: Диагностика ConfigMap

```bash
# Проверка существования
kubectl get configmap <configmap-name> -n <namespace>

# Проверка содержимого (все ключи)
kubectl get configmap <configmap-name> -n <namespace> -o jsonpath='{.data}'

# Проверка содержимого (полный YAML)
kubectl get configmap <configmap-name> -n <namespace> -o yaml
```

### Сценарий 3: Диагностика Secret

```bash
# Проверка существования
kubectl get secret <secret-name> -n <namespace>

# Проверка типа
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.type}'

# Проверка ключей (base64)
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data}'
```

### Сценарий 4: Диагностика PVC

```bash
# Статус всех PVC
kubectl get pvc -n <namespace>

# Детальная информация
kubectl describe pvc <pvc-name> -n <namespace>

# Проверка привязки (статус)
kubectl get pvc -n <namespace> -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,VOLUME:.spec.volumeName
```

### Сценарий 5: Диагностика RBAC

Применяется если ресурс существует, но ошибка сохраняется.

```bash
# ServiceAccount пода
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.serviceAccountName}'

# Проверка прав на Secret
kubectl auth can-i get secret/<secret-name> \
  --as=system:serviceaccount:<namespace>:<sa-name> -n <namespace>

# Проверка прав на ConfigMap
kubectl auth can-i get configmap/<configmap-name> \
  --as=system:serviceaccount:<namespace>:<sa-name> -n <namespace>
```

### Сценарий 6: Диагностика томов

```bash
# Тома пода
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.volumes}'

# VolumeMounts контейнера
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[0].volumeMounts}'
```

### Сценарий 7: Автоматизированная диагностика (скрипт)

```bash
#!/bin/bash
# Скрипт диагностики CreateContainerConfigError
# Использование: ./diagnose.sh <pod-name> [namespace]

POD=$1
NS=${2:-default}

echo "=== Описание пода (Events) ==="
kubectl describe pod "$POD" -n "$NS" | grep -A 5 "Events:"

echo -e "\n=== ConfigMap в namespace ==="
kubectl get configmap -n "$NS"

echo -e "\n=== Secrets в namespace ==="
kubectl get secret -n "$NS"

echo -e "\n=== PVC в namespace ==="
kubectl get pvc -n "$NS"

echo -e "\n=== Тома пода ==="
kubectl get pod "$POD" -n "$NS" -o jsonpath='{.spec.volumes}'
echo
```

## Additional Information

### Интеграция с общим workflow

Диагностика CreateContainerConfigError — часть общего процесса troubleshooting Kubernetes. Общие инструменты и методы описаны в:

- Troubleshooting overview: [troubleshooting_overview.md](../../troubleshooting_overview.md)
- Common Errors overview: [overview.md](../overview.md)

### Автоматическое восстановление

После устранения причины Kubernetes автоматически переведёт Pod в `Running` при следующей проверке зависимостей (~10–30 сек). Ручной перезапуск обычно не требуется.

### Связанные ресурсы

- Определения и workflow: [definitions.md](./definitions.md)
- ConfigMap: [configmap_issues.md](./configmap_issues.md)
- Secrets: [secret_issues.md](./secret_issues.md)
- PVC: [pvc_issues.md](./pvc_issues.md)
- Volume: [volume_issues.md](./volume_issues.md)
- RBAC: [rbac_issues.md](./rbac_issues.md)
- Профилактика: [prevention.md](./prevention.md)
