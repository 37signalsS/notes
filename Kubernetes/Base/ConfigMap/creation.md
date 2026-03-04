# Создание ConfigMap

## Определения

**ConfigMap** — объект API Kubernetes для хранения неконфиденциальных конфигурационных данных в виде пар «ключ-значение».

## Основные концепции

### Подходы к созданию

Существует два основных подхода к созданию ConfigMap:

1. **Декларативный** (рекомендуемый) — через YAML-манифест
2. **Императивный** — через команды `kubectl`

## Практические сценарии

### Декларативно: из манифеста (рекомендуемый способ)

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

**Применение:**
```bash
kubectl apply -f app-config.yaml
```

### Императивно: с помощью `kubectl`

Удобно для быстрого создания или для данных, генерируемых скриптами.

```bash
# Из файла (ключ = имя файла, значение = содержимое)
kubectl create configmap my-config-from-file --from-file=path/to/config.json

# Из нескольких файлов
kubectl create configmap my-config-from-files --from-file=path/to/config1.json --from-file=path/to/config2.xml

# Из литералов (явное указание ключ-значение)
kubectl create configmap my-config-from-literals --from-literal=KEY1=VALUE1 --from-literal=KEY2=VALUE2

# Из всей директории
kubectl create configmap my-config-dir --from-file=path/to/config-dir/
```

### Проверка созданного ConfigMap

```bash
# Просмотр списка ConfigMap
kubectl get configmaps

# Детальная информация
kubectl describe configmap app-config

# Просмотр содержимого (YAML)
kubectl get configmap app-config -o yaml

# Просмотр данных (только data)
kubectl get configmap app-config -o jsonpath='{.data}'
```

## Дополнительная информация

### Сравнение подходов

| Подход | Преимущества | Недостатки | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Декларативный** | Версионируемость, воспроизводимость, code review | Требует больше времени | Production, CI/CD, GitOps |
| **Императивный** | Быстро, удобно для скриптов | Не версионируется, сложно отследить изменения | Dev/тестирование, прототипирование |

### Best practices

* Всегда предпочитайте декларативный подход для production
* Используйте `kubectl diff -f <file>` перед применением для просмотра изменений
* Для бинарных данных используйте поле `binaryData` (автоматическое кодирование в base64)
* Избегайте хранения чувствительных данных — для этого используйте [Secret](../secrets/secrets_basics.md)

### Связанные документы

* [Использование ConfigMap в подах](./pod_usage.md)
* [Неизменяемые ConfigMap](./immutable.md)
* [Лучшие практики](./best_practices.md)
