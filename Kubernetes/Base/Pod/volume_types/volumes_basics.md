# Базовые концепции Volume в Kubernetes

## Определения

**Volume (том)** — абстракция хранилища данных в Kubernetes, которая предоставляет Pod (подам) доступ к файловой системе вне жизненного цикла отдельных container (контейнеров).

**Жизненный цикл Volume** — неразрывно связан с жизненным циклом самого Pod. Данные внутри Volume сохраняются при перезапуске container внутри Pod и уничтожаются только при полном удалении объекта Pod из кластера (за исключением персистентных томов).

---

## Базовые концепции

### Задачи, решаемые механизмом Volume

| Проблема | Решение через Volume |
| :--- | :--- |
| Эфемерность файловой системы | Сохранение состояния приложения при аварийном перезапуске процесса или container. |
| Совместное использование данных | Обеспечение доступа к одним и тем же файлам для нескольких container внутри одного Pod. |
| Изоляция технологий хранения | Предоставление единого интерфейса доступа независимо от типа хранилища (локальный диск, NFS, облачный провайдер). |

### Механика подключения

Работа с хранилищем в манифесте Pod описывается двумя связанными секциями:

1.  **Определение тома (`spec.volumes`)**: задается на уровне Pod. Описывает источник данных (например, `emptyDir`, `ConfigMap`) и присваивает ему логическое имя.
2.  **Монтирование тома (`spec.containers[*].volumeMounts`)**: задается внутри спецификации конкретного container. Указывает, под каким именем и по какому пути (`mountPath`) ранее определенный том будет доступен внутри файловой системы container.

**Важно**: имя тома в `volumeMounts` должно точно совпадать с именем, объявленным в `volumes`.

### Пример базовой конфигурации

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: storage-example
spec:
  containers:
  - name: web-server
    image: nginx:1.25
    volumeMounts:
    - name: shared-content
      mountPath: /usr/share/nginx/html
  volumes:
  - name: shared-content
    emptyDir: {}
```

---

## Практические сценарии

### Сценарий 1: Обмен данными через emptyDir

Использование общего тома для взаимодействия основного приложения и вспомогательного (sidecar) container:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: log-collector-demo
spec:
  volumes:
  - name: log-storage
    emptyDir: {}
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: log-storage
      mountPath: /var/log/app
  - name: sidecar-logger
    image: busybox
    command: ["sh", "-c", "tail -f /logs/app.log"]
    volumeMounts:
    - name: log-storage
      mountPath: /logs
```

В данном примере `app` пишет логи в `/var/log/app`, а `sidecar-logger` читает их из `/logs` в реальном времени.

### Сценарий 2: Множественное монтирование

Один и тот же источник данных может быть смонтирован в разные директории или с разными правами доступа:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-mount-config
spec:
  volumes:
  - name: settings
    configMap:
      name: app-settings
  containers:
  - name: backend
    image: my-backend:1.0
    volumeMounts:
    - name: settings
      mountPath: /etc/config
      readOnly: true
    - name: settings
      mountPath: /app/runtime/config
      readOnly: false
```

---

## Дополнительная информация

**Связанные темы:**
- [Типы томов в Kubernetes](./volume_types.md)
- [Projected Volumes (проектируемые тома)](./projected_volumes.md)
- [Downward API в Kubernetes](../downward_api.md)
- [Использование ConfigMap](../../configmap.md)
- [Основы работы с Secret](../../secrets/secrets_basics.md)

**Аббревиатуры:**
- **NFS** — Network File System (сетевая файловая система).
- **IP** — Internet Protocol (межсетевой протокол).
