# ConfigMap

**ConfigMap** — это объект API, который позволяет хранить неконфиденциальные конфигурационные данные в виде пар "ключ-значение". Его главная задача — **отделить конфигурацию от кода приложения**, что делает приложения переносимыми и легко настраиваемыми для разных окружений (dev, staging, prod) без пересборки Docker-образа.

Ключевое правило: Используйте ConfigMap для настроек, которые могут меняться, а [Secret](./secret.md) — для конфиденциальных данных (пароли, токены, ключи API).

---

## Способы создания ConfigMap

#### Декларативно: из манифеста (рекомендуемый способ)

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
```

#### Императивно: с помощью `kubectl`

Удобно для быстрого создания или для данных, генерируемых скриптами.

```bash
# Из файла (ключ = имя файла, значение = содержимое)
kubectl create configmap my-config-from-file --from-file=path/to/config.json

# Из нескольких файлов
kubectl create configmap my-config-from-files --from-file=path/to/config1.json --from-file=path/to/config2.xml

# Из литералов (явное указание ключ-значение)
kubectl create configmap my-config-from-literals --from-literal=KEY1=VALUE1 --from-literal=KEY2=VALUE2
```

---

## Способы использования ConfigMap в [подах](./pod.md)

#### Как файлы в томе (Volume)

Это самый распространенный и мощный способ. ConfigMap монтируется как директория в файловую систему контейнера, где каждый ключ становится файлом.

```yaml
apiVersion: v1
kind: Pod
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
          image: nginx:1.28.0
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

**Важный нюанс: `subPath`**

Если смонтировать ConfigMap в существующую системную директорию (например, `/etc/nginx`), он **полностью скроет** ее оригинальное содержимое. Чтобы этого избежать и смонтировать только один файл, используйте `subPath`.

```yaml
# ...
volumeMounts:
  - name: config-volume
    mountPath: /etc/nginx/nginx.conf # Указываем полный путь к файлу
    subPath: nginx.conf # Имя ключа в ConfigMap, который нужно смонтировать
# ...
```

**Внимание:** Использование `subPath` имеет побочный эффект — **смонтированный файл перестает обновляться автоматически** при изменении ConfigMap.

#### Как переменные окружения

Подходит для передачи простых строковых значений в приложение.

```yaml
# ...
spec:
  containers:
    - name: my-app
      image: my-app:1.0.0
      env:
        # 1. Передать значение одного конкретного ключа
        - name: APP_COLOR_SETTING
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

## Обновление ConfigMap и его влияние на поды

| Способ использования | Поведение при обновлении ConfigMap | Что нужно делать? |
| :--- | :--- | :--- |
| **Том (`volume`)** | Файлы в смонтированной директории **обновляются автоматически** (с задержкой до минуты). | Приложение должно уметь само перечитывать файлы конфигурации. |
| **Том с `subPath`** | Файл **НЕ обновляется** автоматически. | Требуется **перезапуск пода**. |
| **Переменные окружения** | Переменные окружения **НЕ обновляются** никогда. | Требуется **перезапуск пода**. |

Для перезапуска подов в [Deployment](./deployment_and_rolling_update.md) или [StatefulSet](./statefulset.md) используйте команду:
`kubectl rollout restart deployment/my-deployment`

## Рекомендации и лучшие практики

*   **Предпочитайте монтирование через том:** Это позволяет обновлять конфигурацию на лету, без перезапуска приложения, если оно поддерживает перечитывание конфигов.
*   **Именуйте и версионируйте ConfigMap:** Чтобы избежать хаоса, давайте осмысленные имена (например, `nginx-config-v2`). При развертывании новой версии приложения можно создать новый ConfigMap и обновить ссылку на него в манифесте `Deployment`.
*   **Не используйте `latest`:** Явно указывайте версию ConfigMap в манифестах, чтобы развертывания были предсказуемыми.
*   **Проверяйте перед применением:** Используйте `kubectl diff -f my-manifest.yaml` для просмотра изменений перед их применением в кластере.

---

## Автоматический перезапуск подов при изменении ConfigMap

По умолчанию, при изменении данных в `ConfigMap`, поды, использующие его через переменные окружения или `subPath`, **не обновляются автоматически**. Это требует ручного перезапуска, например, с помощью команды `kubectl rollout restart deployment/my-deployment`.

Чтобы автоматизировать этот процесс, можно использовать "трюк" с аннотацией в шаблоне пода.

### Принцип работы

Идея состоит в том, чтобы добавить в аннотации шаблона пода (`spec.template.metadata.annotations`) хеш-сумму от данных `ConfigMap`.

1.  Вычисляется хеш от содержимого `ConfigMap` (например, `sha256sum`).
2.  Этот хеш добавляется как значение аннотации в `Deployment`.
3.  При любом изменении в `ConfigMap` его хеш также меняется.
4.  Изменение аннотации в шаблоне пода расценивается Kubernetes как изменение спецификации `Deployment`.
5.  Kubernetes автоматически запускает `Rolling Update`, создавая новые поды, которые подхватывают обновленный `ConfigMap`.

Этот подход полностью автоматизирует процесс обновления конфигурации и является лучшей практикой при работе с GitOps и CI/CD.

### Пример реализации (с Helm)

В шаблонизаторах, таких как Helm, это реализуется очень просто.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        # При каждом изменении ConfigMap 'my-config' будет меняться хеш,
        # что вызовет автоматический rollout для Deployment'а.
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
      - name: app
        image: myimage:latest
        envFrom:
        - configMapRef:
            name: my-config
```
В данном примере Helm вычисляет `sha256sum` от отрендеренного шаблона `configmap.yaml` и вставляет его в аннотацию.

### Пример с `volumeMounts` и `sha256sum`

Этот более общий пример подходит для любого Deployment, где ConfigMap монтируется как том. Здесь хеш также вычисляется с помощью шаблонизатора, но демонстрируется использование с `volumeMounts`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        config-hash: "{{ sha256sum .Values.myConfig }}"
    spec:
      containers:
      - name: app
        image: myimage:latest
        volumeMounts:
        - name: cfg
          mountPath: /app/config
      volumes:
      - name: cfg
        configMap:
          name: my-config
```

