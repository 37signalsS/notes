# ConfigMap: Управление конфигурацией

**ConfigMap** — это объект API Kubernetes для хранения неконфиденциальных конфигурационных данных в виде пар "ключ-значение". Он позволяет отделить конфигурацию от кода приложения, что делает приложения более гибкими и переносимыми.

**Основное правило:** Используйте ConfigMap для настроек, которые вы хотите менять без пересборки контейнерного образа.

**Важно:** ConfigMap не предназначен для хранения секретов. Для этого используйте объект `Secret`.

---

## Способы создания ConfigMap

#### 1. Декларативно (из манифеста)

Самый надежный и воспроизводимый способ. Конфигурация хранится в системе контроля версий вместе с кодом.

```yaml
# nginx-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  # Ключ-значение
  APP_COLOR: "blue"
  # Ключ со значением в виде файла
  nginx.conf: |
    server {
        listen 80;
        location / {
            root /app;
            index index.html;
        }
    }
```

#### 2. Императивно (из файлов или литералов)

Удобно для быстрого создания или для данных, генерируемых скриптами.

```bash
# Из файла (ключ = имя файла, значение = содержимое)
kubectl create configmap my-config-from-file --from-file=path/to/config.json

# Из литералов (ключ-значение)
kubectl create configmap my-config-from-literals --from-literal=KEY1=VALUE1 --from-literal=KEY2=VALUE2
```

---

## Способы использования ConfigMap в подах

#### 1. Как файлы в томе (Volume)

Это самый распространенный и гибкий способ. ConfigMap монтируется как директория в файловую систему контейнера.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
        - name: nginx
          image: nginx:latest
          ports:
            - containerPort: 80
          volumeMounts:
            # Монтируем том 'config-volume' в директорию /etc/nginx/conf.d
            # Ключ 'nginx.conf' из ConfigMap станет файлом в этой директории.
            - name: config-volume
              mountPath: /etc/nginx/conf.d
      volumes:
        - name: config-volume
          configMap:
            name: app-config # Имя нашего ConfigMap
```

**Проблема:** Монтирование ConfigMap в существующую директорию (например, `/etc/nginx`) **скроет/затрет** все её оригинальное содержимое.

**Решение:** Используйте `subPath`, чтобы смонтировать только конкретный файл или директорию из ConfigMap, не затрагивая остальное содержимое `mountPath`.

```yaml
# ...
volumeMounts:
  - name: config-volume
    mountPath: /etc/nginx/nginx.conf # Указываем полный путь к файлу
    subPath: nginx.conf # Имя ключа в ConfigMap, который нужно смонтировать
# ...
```

#### 2. Как переменные окружения

Подходит для передачи простых строковых значений.

```yaml
# ...
spec:
  containers:
    - name: my-app
      image: my-app:latest
      env:
        # 1. Передать значение одного ключа
        - name: APP_BACKGROUND_COLOR
          valueFrom:
            configMapKeyRef:
              name: app-config # Имя ConfigMap
              key: APP_COLOR    # Ключ, значение которого нужно взять

      # 2. Передать все ключи из ConfigMap как переменные окружения
      envFrom:
        - configMapRef:
            name: app-config
```

---

## Обновление ConfigMap

Поведение при обновлении ConfigMap зависит от способа его использования:

*   **Монтирование как том (`volume`):** Данные в смонтированных файлах **обновляются автоматически** через некоторое время (обычно около минуты). Приложение должно уметь само перечитывать конфигурационные файлы, чтобы подхватить изменения.
*   **Переменные окружения (`env`, `envFrom`):** Переменные окружения **не обновляются** после запуска пода. Чтобы изменения вступили в силу, **необходимо перезапустить под** (например, выполнив `kubectl rollout restart deployment/my-deployment`).
