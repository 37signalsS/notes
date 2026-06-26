# Тома в Kubernetes

## Определения

**Volume (том)** — абстракция хранилища данных, которая предоставляет Pod (подам) доступ к файловой системе вне жизненного цикла отдельных container (контейнеров).

**Эфемерное хранилище** — тома, жизненный цикл которых неразрывно связан с жизненным циклом Pod (например, `emptyDir`, `hostPath`, `ConfigMap`, `Secret`). Данные в таких томах уничтожаются при удалении объекта Pod из кластера.

**Персистентное хранилище** — тома, данные в которых сохраняются независимо от состояния Pod (например, `PersistentVolumeClaim`). Позволяют приложениям сохранять состояние (state) при пересоздании или миграции Pod на другой Node (узел).

---

## Базовые концепции

### Назначение томов

| Проблема | Решение через Volume |
| :--- | :--- |
| Эфемерность ФС | Сохранение состояния при аварийном перезапуске container. |
| Совместное использование | Доступ к одним и тем же файлам для нескольких container внутри одного Pod. |
| Изоляция технологий | Единый интерфейс доступа независимо от типа СХД (NFS, облачные диски). |

### Механизм подключения

Работа с хранилищем в манифесте Pod описывается двумя секциями:

1. **Определение тома (`spec.volumes`)**: задается на уровне Pod. Описывает источник данных и присваивает ему имя.
2. **Монтирование тома (`spec.containers[*].volumeMounts`)**: задается внутри container. Указывает путь (`mountPath`), по которому том будет доступен.

**Важно:** имя тома в `volumeMounts` должно точно совпадать с именем, объявленным в `volumes`.

### Классификация типов томов

| Тип | Категория | Основное назначение | Персистентность |
| :--- | :--- | :--- | :--- |
| `emptyDir` | Эфемерное | Временные данные, кэш, обмен между container | Нет |
| `hostPath` | Эфемерное | Доступ к файлам Node (для системных утилит) | Нет (привязка к Node) |
| `ConfigMap` | Эфемерное | Инъекция файлов конфигурации | Нет |
| `Secret` | Эфемерное | Передача конфиденциальных данных | Нет |
| `Projected` | Эфемерное | Агрегация нескольких источников в один путь | Нет |
| `PersistentVolumeClaim` | Персистентное | Постоянное хранение данных (БД, медиа) | Да |

### Основные типы томов

#### emptyDir

**Описание:** пустой каталог, создаваемый на Node в момент запуска Pod.
**Особенности:**
- **medium: Memory**: создание тома в RAM (tmpfs). Выше скорость, но данные потребляют лимиты памяти container.
- **sizeLimit**: ограничение объема. При превышении Pod будет выселен (evicted).

#### hostPath

**Описание:** монтирование файла или директории напрямую с файловой системы Node.
**Ограничения:**
- **Отсутствие мобильности**: Pod жестко привязан к конкретной Node.
- **Безопасность**: предоставляет доступ к ресурсам хоста (требует осторожности).

#### ConfigMap и Secret

Позволяют монтировать данные из одноименных объектов Kubernetes как файлы.
- [Использование ConfigMap в Pod](../../ConfigMap/pod_usage.md)
- [Использование Secret в Pod](../../secrets/using_secrets.md)

#### Projected Volume

Объединяет несколько источников (Secret, ConfigMap, Downward API, ServiceAccountToken) в одну точку монтирования.
Подробнее: [Projected Volumes в Kubernetes](./projected_volumes.md).

#### PersistentVolumeClaim (PVC)

Механизм запроса ресурсов хранения. Абстрагирует приложение от конкретных технологий (NFS, Ceph) через CSI (Container Storage Interface).
Подробнее: [PV, PVC и StorageClass](../../../Storage/pv_and_pvc.md).

---

## Практические сценарии

### Сценарий 1: Обмен данными через emptyDir (sidecar)

Использование общего тома для передачи данных от `initContainer` к основному приложению.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: sidecar-storage-demo
spec:
  volumes:
  - name: shared-data
    emptyDir: {}
  containers:
  - name: app
    image: nginx:1.25
    volumeMounts:
    - name: shared-data
      mountPath: /usr/share/nginx/html
  initContainers:
  - name: fetcher
    image: busybox
    command: ["sh", "-c", "echo 'Hello from Init' > /data/index.html"]
    volumeMounts:
    - name: shared-data
      mountPath: /data
```

### Сценарий 2: hostPath для агента сбора логов

Монтирование логов хоста в режиме "только чтение".

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: log-agent
spec:
  containers:
  - name: agent
    image: fluent/fluent-bit
    volumeMounts:
    - name: host-logs
      mountPath: /var/log/host
      readOnly: true
  volumes:
  - name: host-logs
    hostPath:
      path: /var/log
      type: Directory
```

### Сценарий 3: Множественное монтирование

Один источник данных монтируется в разные директории с разными правами.

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

### Сравнение с Docker Volumes

| Характеристика | Kubernetes Volume | Docker Volume |
| :--- | :--- | :--- |
| **Управление** | Декларативное (YAML) | Императивное (CLI) |
| **Масштабируемость** | В рамках всего кластера | Ограничено одним хостом |
| **Драйверы** | CSI (облачные диски, NFS) | Volume Drivers |

**Связанные темы:**
- [Projected Volumes](./projected_volumes.md)
- [PV, PVC и StorageClass](../../../Storage/pv_and_pvc.md)
- [Тома в Docker](../../../../Docker/Docker_fs/docker_volumes.md)
