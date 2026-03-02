# Способы создания ConfigMap

## Декларативно: из манифеста (рекомендуемый способ)

Это самый надежный и воспроизводимый подход.

```yaml
# app-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: my-app
data:
  # Простые ключ-значение
  APP_COLOR: "blue"
  APP_MODE: "production"

  # Ключ, значением которого является целый файл
  nginx.conf: |
    server {
        listen 80;
        location / {
            root /app;
            index index.html;
        }
    }
binaryData:
  # Бинарные данные, кодированные в Base64
  logo.png: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
```

## Императивно: с помощью `kubectl`

Удобно для быстрого создания или для данных, генерируемых скриптами.

```bash
# Из файла (ключ = имя файла, значение = содержимое)
kubectl create configmap my-config-from-file --from-file=path/to/config.json

# Из нескольких файлов
kubectl create configmap my-config-from-files --from-file=path/to/config1.json --from-file=path/to/config2.xml

# Из литералов (явное указание ключ-значение)
kubectl create configmap my-config-from-literals --from-literal=KEY1=VALUE1 --from-literal=KEY2=VALUE2
```
