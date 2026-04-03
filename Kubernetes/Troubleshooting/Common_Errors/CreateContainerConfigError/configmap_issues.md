# CreateContainerConfigError: Проблемы с ConfigMap

## Definitions

**ConfigMap-related CreateContainerConfigError** — ошибка, возникающая когда `kubelet` не может создать конфигурацию контейнера из-за проблем с ConfigMap: отсутствие ресурса, недостающие ключи, неправильные ссылки или ошибки монтирования.

## Basic Concepts

### Способы использования ConfigMap в Pod

| Способ | Синтаксис | Поведение |
|--------|-----------|-----------|
| **Все ключи как env** | `envFrom.configMapRef` | Каждый ключ → переменная окружения |
| **Отдельный ключ как env** | `env.valueFrom.configMapKeyRef` | Один ключ → одна переменная |
| **Как volume (файлы)** | `volumes.configMap` | Каждый ключ → файл с содержимым |

### Типичные причины ошибок

- **ConfigMap не существует** в указанном namespace
- **Ключ отсутствует** в существующем ConfigMap
- **Namespace mismatch** — Pod и ConfigMap в разных namespace
- **Опечатка в имени** — `name: app-config` vs `name: app-conf`
- **ConfigMap создан после Pod** — требуется рестарт Pod

### Манифест ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: default
data:
  DATABASE_URL: "postgres://db:5432/mydb"
  LOG_LEVEL: "info"
  config.yaml: |
    server:
      port: 8080
    logging:
      level: info
```

### Создание ConfigMap

```bash
# Из литералов
kubectl create configmap app-config \
  --from-literal=key1=value1 \
  --from-literal=key2=value2 \
  -n <namespace>

# Из файла
kubectl create configmap app-config \
  --from-file=config.yaml=/path/to/config.yaml \
  -n <namespace>

# Из директории
kubectl create configmap app-config \
  --from-file=/path/to/config-dir/ \
  -n <namespace>
```

## Practical Scenarios

### Сценарий 1: ConfigMap не существует

**Сообщение об ошибке:**

```
Error: configmap "app-config" not found
```

**Диагностика:**

```bash
kubectl get configmap app-config -n <namespace>
```

**Решение:** Создать недостающий ConfigMap (см. раздел Basic Concepts).

### Сценарий 2: Ключ ConfigMap отсутствует

**Сообщение об ошибке:**

```
configmaps "app-config" not found: key "DATABASE_PASSWORD" not found
```

**Диагностика:**

```bash
kubectl get configmap app-config -o jsonpath='{.data}'
```

**Решение:**

```bash
# Добавление ключа в существующий ConfigMap
kubectl patch configmap app-config \
  -p '{"data":{"DATABASE_PASSWORD":"newpassword"}}'
```

### Сценарий 3: Namespace mismatch

**Симптом:** ConfigMap существует, но Pod не может его найти.

**Диагностика:**

```bash
# Проверка namespace ConfigMap
kubectl get configmap app-config -n <namespace-a>

# Проверка namespace Pod
kubectl get pod <pod-name> -n <namespace-b>
```

**Решение:** Создать ConfigMap в том же namespace, где находится Pod, или исправить namespace в манифесте Pod.

### Сценарий 4: ConfigMap обновлён, но Pod не подхватил изменения

**Особенность:** При монтировании как volume обновление происходит автоматически (с задержкой ~1 мин). При использовании как env — требуется рестарт Pod.

**Решение:**

```bash
# Рестарт Pod через rollout (для Deployment)
kubectl rollout restart deployment/<deployment-name> -n <namespace>

# Удаление Pod (для прямого управления Pod)
kubectl delete pod <pod-name> -n <namespace>
```

## Additional Information

### Примеры использования в Pod

```yaml
# Все ключи как переменные окружения
envFrom:
- configMapRef:
    name: app-config

# Отдельный ключ как переменная
env:
- name: DATABASE_URL
  valueFrom:
    configMapKeyRef:
      name: app-config
      key: DATABASE_URL

# Монтирование как volume
volumes:
- name: config
  configMap:
    name: app-config
volumeMounts:
- name: config
  mountPath: /etc/config
  readOnly: true
```

### Связанные ресурсы

- Общая диагностика: [diagnostics.md](./diagnostics.md)
- Профилактика: [prevention.md](./prevention.md)
- Проблемы с Secret: [secret_issues.md](./secret_issues.md)
