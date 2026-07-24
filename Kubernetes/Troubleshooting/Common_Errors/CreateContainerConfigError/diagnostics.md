# CreateContainerConfigError: Диагностика

## Определения

**Диагностика CreateContainerConfigError** — структурированный процесс выявления конкретной отсутствующей или некорректно настроенной внешней зависимости (ConfigMap, Secret, PersistentVolumeClaim, Volume, RBAC), которая препятствует формированию спецификации контейнера на стороне `kubelet`.

Общее описание ошибки: [definitions.md](./definitions.md).

## Основные концепции

### Алгоритм диагностики (Workflow)

Процесс отладки всегда начинается с API Kubernetes, так как при этой ошибке контейнер еще не создан, и логи приложения отсутствуют.

1.  **Сбор первичных данных:** Проверка статуса пода и последних событий (Events).
2.  **Идентификация ресурса:** Определение типа и имени ресурса (например, ConfigMap "api-config"), на который ссылается ошибка.
3.  **Валидация существования:** Проверка наличия ресурса в том же Namespace, что и Pod.
4.  **Проверка контента:** Убедиться, что требуемые ключи (keys) присутствуют в `data` ресурса.
5.  **Анализ прав доступа:** Проверка прав ServiceAccount пода на чтение указанного ресурса.

### Ключевые команды

| Команда | Назначение |
| :--- | :--- |
| `kubectl describe pod <name>` | Основной инструмент: содержит детальные сообщения об ошибках в секции Events. |
| `kubectl get <resource> <name>` | Проверка наличия ресурса. |
| `kubectl get pod <name> -o yaml` | Проверка `env` и `volumeMounts` на наличие опечаток в именах ресурсов. |
| `kubectl auth can-i get <resource>` | Имитация прав (impersonation) для проверки RBAC. |
| `kubectl get events --field-selector involvedObject.name=<pod-name>` | Получение только релевантных событий для конкретного пода. |

### Типичные сообщения в секции Events

| Текст сообщения | Тип проблемы | Ссылка на решение |
| :--- | :--- | :--- |
| `configmap "x" not found` | Отсутствует ConfigMap | [Проблемы с ConfigMap](./configmap_issues.md) |
| `secret "x" not found` | Отсутствует Secret | [Проблемы с Secret](./secret_issues.md) |
| `persistentvolumeclaim "x" not found` | Ошибка PVC | [Проблемы с PVC](./pvc_issues.md) |
| `Error: Secret "x" is not a valid secret type` | Неверный тип секрета | [Проблемы с Secret](./secret_issues.md) |

## Практические сценарии

### Сценарий 1: Быстрый поиск причины через Events

```bash
# Получение только ошибок из событий пода
kubectl describe pod <pod-name> | grep -iE "reason|message" | grep -A 1 "CreateContainerConfigError"
# → reason: CreateContainerConfigError
# → message: configmap "app-env" not found
```

### Сценарий 2: Глубокая проверка ConfigMap и Secret

Если в сообщении указано, что ресурс не найден, проверьте его наличие в текущем Namespace:

```bash
# Проверка наличия и метаданных
kubectl get configmap <name> -o wide
# → NAME      DATA   AGE
# → app-env   5      12h

# Проверка наличия конкретного ключа, на который ссылается Pod
kubectl get configmap <name> -o jsonpath='{.data.DATABASE_URL}'
# → postgres://user:pass@host:5432/db
```

### Сценарий 3: Диагностика проблем с PersistentVolumeClaim (PVC)

При использовании PVC ошибка может возникать, если том не может быть привязан или монтирован.

```bash
# Проверка статуса PVC
kubectl get pvc <pvc-name>
# → NAME       STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → data-pvc   Pending                                      standard       5m

# Просмотр причин задержки
kubectl describe pvc <pvc-name> | tail -n 10
# → Events: ... Failed to provision volume with StorageClass "standard": ...
```

Подробнее: [Проблемы с PVC](./pvc_issues.md).

### Сценарий 4: Проверка RBAC через ServiceAccount

Если ресурс существует, но под его "не видит", возможно, у ServiceAccount нет прав на `get` или `list`.

```bash
# 1. Узнаем SA пода
SA_NAME=$(kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}')

# 2. Проверяем права (результат должен быть yes)
kubectl auth can-i get configmap/<cm-name> --as=system:serviceaccount:<namespace>:$SA_NAME
# → yes (или no при отсутствии прав)
```

### Сценарий 5: Скрипт для комплексной диагностики

Этот скрипт собирает всю информацию о зависимостях пода в один отчет.

```bash
#!/bin/bash
# usage: ./check-pod-deps.sh <pod-name> <namespace>

POD=$1
NS=${2:-default}

echo "=== Диагностика пода: $POD (Namespace: $NS) ==="

# 1. События
echo -e "\n[Events]"
kubectl get events -n "$NS" --field-selector involvedObject.name="$POD" --sort-by='.lastTimestamp'

# 2. Переменные окружения из ConfigMap/Secret
echo -e "\n[EnvFrom Dependencies]"
kubectl get pod "$POD" -n "$NS" -o jsonpath='{range .spec.containers[*].envFrom[*]}{.configMapRef.name}{.secretRef.name}{"\n"}{end}' | while read ref; do
    if [ ! -z "$ref" ]; then
        kubectl get cm,secret "$ref" -n "$NS" > /dev/null 2>&1 || echo "!!! РЕСУРС НЕ НАЙДЕН: $ref"
    fi
done

# 3. Тома (Volumes)
echo -e "\n[Volume Dependencies]"
kubectl get pod "$POD" -n "$NS" -o jsonpath='{range .spec.volumes[*]}{.configMap.name}{.secret.secretName}{.persistentVolumeClaim.claimName}{"\n"}{end}' | while read vol; do
    if [ ! -z "$vol" ]; then
        kubectl get cm,secret,pvc "$vol" -n "$NS" > /dev/null 2>&1 || echo "!!! ТОМ НЕ НАЙДЕН: $vol"
    fi
done
```

## Дополнительная информация

### Место в процессе Troubleshooting

Диагностика `CreateContainerConfigError` — это "внешняя" отладка. Она предшествует проверке логов контейнера, так как на этом этапе контейнер еще не существует. Если вы видите эту ошибку, не пытайтесь использовать `kubectl logs` или `kubectl exec`.

*   [Обзор процесса Troubleshooting](../../troubleshooting_overview.md)
*   [Профилактика ошибок конфигурации](./prevention.md)

### Связанные ресурсы

*   [Проблемы с ConfigMap](./configmap_issues.md)
*   [Проблемы с Secret](./secret_issues.md)
*   [Проблемы с PVC](./pvc_issues.md)
*   [Проблемы с RBAC](./rbac_issues.md)
*   [Проблемы с томами](./volume_issues.md)
