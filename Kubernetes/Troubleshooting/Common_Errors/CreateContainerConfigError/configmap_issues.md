# CreateContainerConfigError: Проблемы с ConfigMap

## 1. Отсутствует ConfigMap

**Сообщение:**
```
Error: configmap "app-config" not found
```

**Причина:** Pod ссылается на ConfigMap, который не существует в данном namespace.

**Решение:**
```bash
# Создание недостающего ConfigMap
kubectl create configmap app-config \
  --from-literal=key1=value1 \
  --from-literal=key2=value2 \
  -n <namespace>

# Или из файла
kubectl create configmap app-config \
  --from-file=config.yaml=/path/to/config.yaml \
  -n <namespace>
```

**Пример манифеста:**
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

**Использование в Pod:**
```yaml
# Как переменные окружения
envFrom:
- configMapRef:
    name: app-config

# Как отдельные переменные
env:
- name: DATABASE_URL
  valueFrom:
    configMapKeyRef:
      name: app-config
      key: DATABASE_URL

# Как volume (файлы)
volumes:
- name: config
  configMap:
    name: app-config
```

> **См. также:** [`../../../Base/configmap.md`](../../../Base/configmap.md)

## 2. Ключ ConfigMap не существует

**Сообщение:**
```
configmaps "app-config" not found: key "DATABASE_PASSWORD" not found
```

**Причина:** ConfigMap существует, но указанный ключ отсутствует.

**Диагностика:**
```bash
# Проверка ключей ConfigMap
kubectl get configmap app-config -o jsonpath='{.data}'
```

**Решение:**
```bash
# Добавление ключа в ConfigMap
kubectl patch configmap app-config \
  -p '{"data":{"DATABASE_PASSWORD":"newpassword"}}'
```
