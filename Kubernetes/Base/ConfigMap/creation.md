# Создание ConfigMap

## Определения

**ConfigMap** — объект API (Application Programming Interface) Kubernetes для хранения неконфиденциальных конфигурационных данных в виде пар «ключ-значение». Он позволяет отделить конфигурацию от кода приложения, обеспечивая переносимость образов между окружениями.

## Основные концепции

### Подходы к созданию

Существует два основных подхода к созданию ресурсов ConfigMap:

1. **Декларативный** (рекомендуемый) — через манифесты в формате YAML (YAML Ain't Markup Language). Обеспечивает возможность версионирования в Git и использование в процессах CI/CD (Continuous Integration / Continuous Deployment).
2. **Императивный** — через команды `kubectl`. Подходит для быстрой отладки, создания простых объектов «на лету» или использования в автоматизационных скриптах.

## Практические сценарии

### Декларативно: из YAML-манифеста

Это основной способ для Production-сред и подходов GitOps. Позволяет точно описать структуру данных и хранить её вместе с кодом.

```yaml
# app-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: my-app
data:
  # Простые пары ключ-значение
  APP_COLOR: "blue"
  APP_MODE: "production"

  # Ключ, значением которого является содержимое целого файла
  nginx.conf: |
    server {
        listen 80;
        location / {
            root /app;
            index index.html;
        }
    }
binaryData:
  # Бинарные данные (например, логотип), закодированные в Base64
  logo.png: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
```

**Применение манифеста:**

```bash
kubectl apply -f app-config.yaml
# → configmap/app-config created
```

### Императивно: с помощью kubectl

Используется для быстрого создания объектов из существующих файлов или строковых литералов.

**Из литералов (явное указание ключ-значение):**

```bash
kubectl create configmap my-config-from-literals --from-literal=KEY1=VALUE1 --from-literal=KEY2=VALUE2
# → configmap/my-config-from-literals created
```

**Из одного или нескольких файлов:**

```bash
# Ключ = имя файла, значение = содержимое файла
kubectl create configmap my-config-from-file --from-file=path/to/config.json
# → configmap/my-config-from-file created

# Можно указывать несколько файлов одновременно
kubectl create configmap my-config-from-files --from-file=config1.json --from-file=config2.xml
```

**Из директории:**

```bash
# Создает ключи для всех файлов, находящихся в указанной директории
kubectl create configmap my-config-dir --from-file=path/to/config-dir/
# → configmap/my-config-dir created
```

**Из env-файла:**

```bash
# Считывает переменные из файла формата .env и создает соответствующие ключи в ConfigMap
kubectl create configmap my-config-from-env --from-env-file=.env
# → configmap/my-config-from-env created
```

### Проверка созданного ConfigMap

```bash
# Просмотр списка всех ConfigMap в текущем пространстве имен
kubectl get configmaps
# → NAME         DATA   AGE
#   app-config   3      10m

# Просмотр структуры и данных в формате YAML
kubectl get configmap app-config -o yaml

# Получение детальной информации (включая метаданные и события)
kubectl describe configmap app-config

# Извлечение конкретного значения через jsonpath
kubectl get configmap app-config -o jsonpath='{.data.APP_COLOR}'
# → blue
```

## Дополнительная информация

### Сравнение подходов

| Подход | Преимущества | Недостатки | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Декларативный** | Версионируемость, аудит (Code Review), воспроизводимость | Требует предварительного описания манифеста | Production, GitOps, CI/CD |
| **Императивный** | Скорость создания, не требует подготовки файлов | Сложно отследить изменения, не подходит для автоматизации развертываний | Разработка, отладка, разовые задачи |

### Рекомендации по созданию

* **Предпочитайте декларативный подход** для всех постоянных конфигураций.
* **Проверяйте изменения** перед их применением в кластере с помощью команды `kubectl diff -f <file>`.
* **Для бинарных данных** (изображения, скомпилированные конфиги) используйте поле `binaryData` для корректной обработки.
* **Не храните конфиденциальные данные** (пароли, ключи) в ConfigMap — для этих целей используйте [Secret](../secrets/creating_secrets.md).
* **Учитывайте лимит размера**: максимальный размер объекта ConfigMap в etcd составляет 1 MiB (Мегабайт).

**См. также:**

* [Лучшие практики ConfigMap](./best_practices.md)
* [Использование ConfigMap в подах](./pod_usage.md)
* [Неизменяемые ConfigMap](./immutable.md)
