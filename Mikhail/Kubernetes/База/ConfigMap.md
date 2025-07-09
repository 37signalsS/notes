# ConfigMap

**ConfigMap** — это объект API Kubernetes, который позволяет хранить конфигурационные данные в виде пар "ключ-значение". Эти данные могут быть использованы подами для конфигурации приложений, например, через переменные окружения, аргументы командной строки или как файлы в томе.

Основное преимущество — отделение конфигурации от кода приложения, что делает приложения более гибкими и переносимыми.

---

### Способы использования

1.  **Переменные окружения:** Передача значений из ConfigMap напрямую в переменные окружения контейнера.
2.  **Файлы в томе (volume):** Монтирование данных из ConfigMap как файлов в файловую систему контейнера. Это самый распространенный способ.

---

### Пример: Создание и использование ConfigMap

#### 1. Манифест ConfigMap

Этот манифест создаёт ConfigMap с именем `nginx-config`. Он содержит один ключ `default.conf`, значением которого является конфигурационный файл для Nginx.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
data:
  # Имя файла, который будет создан в томе
  default.conf: |
    server {
        listen 80;
        server_name example.com;

        location / {
            root /usr/share/nginx/html;
            index index.html;
        }
    }
```

#### 2. Использование ConfigMap в поде

Здесь ConfigMap `nginx-config` монтируется в качестве тома в директорию `/etc/nginx/conf.d` внутри контейнера. Nginx автоматически подхватит конфигурационный файл `default.conf` из этой директории.

**Важно:** Перед запуском пода, который использует ConfigMap, необходимо сначала создать сам ConfigMap в кластере (`kubectl apply -f configmap.yaml`).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-pod-from-configmap
spec:
  containers:
    - name: nginx
      image: nginx:latest
      ports:
        - containerPort: 80
      volumeMounts:
        # Монтируем том 'config-volume' в директорию /etc/nginx/conf.d
        # Ключ 'default.conf' из ConfigMap станет файлом в этой директории.
        - name: config-volume
          mountPath: /etc/nginx/conf.d
  volumes:
    # Объявляем том с именем 'config-volume'.
    - name: config-volume
      # Указываем, что источником данных для этого тома является ConfigMap 'nginx-config'.
      configMap:
        name: nginx-config
```

**Предупреждение:** Если вы монтируете ConfigMap в существующую директорию (например, `/etc`), то все файлы в этой директории внутри контейнера будут скрыты файлами из ConfigMap. В примере выше, если бы `mountPath` был `/etc`, то контейнер потерял бы доступ ко всему содержимому `/etc`, кроме файла `CONFIG_FILE`.