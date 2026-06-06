# Типы томов в Kubernetes

## Определения

**Volume (том)** — абстракция хранилища в Kubernetes, позволяющая Pod (подам) сохранять данные за пределами жизненного цикла отдельных container (контейнеров) и обмениваться файлами между ними.

**Эфемерное хранилище** — тома, жизненный цикл которых неразрывно связан с жизненным циклом Pod (например, `emptyDir`, `hostPath`, `ConfigMap`, `Secret`). Данные в таких томах уничтожаются при удалении объекта Pod из кластера.

**Персистентное хранилище** — тома, данные в которых сохраняются независимо от состояния Pod (например, `PersistentVolumeClaim`). Позволяют приложениям сохранять состояние (state) при пересоздании или миграции Pod на другой Node (узел).

---

## Базовые концепции

### Классификация типов томов

| Тип | Категория | Основное назначение | Персистентность |
| :--- | :--- | :--- | :--- |
| `emptyDir` | Эфемерное | Временные данные, кэш, обмен между container | Нет |
| `hostPath` | Эфемерное | Доступ к файлам Node (для системных утилит) | Нет (привязка к Node) |
| `ConfigMap` | Эфемерное | Инъекция файлов конфигурации | Нет |
| `Secret` | Эфемерное | Передача конфиденциальных данных (пароли, ключи) | Нет |
| `Projected` | Эфемерное | Агрегация нескольких источников в один путь | Нет |
| `PersistentVolumeClaim` | Персистентное | Постоянное хранение данных (БД, медиа-файлы) | Да |

### emptyDir

**Описание:** пустой каталог, создаваемый на Node в момент запуска Pod.
**Жизненный цикл:** данные сохраняются при перезапуске container внутри Pod, но безвозвратно удаляются при удалении самого Pod.

**Параметры и особенности:**
- **medium: Memory**: создание тома в оперативной памяти (tmpfs). Скорость выше, но данные потребляют RAM (Random Access Memory) и учитываются в лимитах памяти container. Без установленных лимитов возможен `OOM (Out Of Memory)` на узле.
- **sizeLimit**: ограничение максимального объема. При превышении Pod будет принудительно завершен (evicted).

### hostPath

**Описание:** монтирование файла или директории напрямую с файловой системы Node в container.

**Критические ограничения:**
- **Отсутствие мобильности**: Pod жестко привязан к конкретной Node. Если Pod будет пересоздан на другом узле, он не увидит данных предыдущего.
- **Безопасность**: предоставляет container доступ к ресурсам хоста. Неправильная настройка может привести к компрометации всего кластера.

**Применение:** системные компоненты кластера, агенты мониторинга или CNI (Container Network Interface) плагины, которым требуется доступ к `/var/log`, `/proc` или `/sys`.

### ConfigMap и Secret

Позволяют монтировать данные, хранящиеся в одноименных объектах Kubernetes, как файлы.
- [Использование ConfigMap в Pod](../../ConfigMap/configmap.md)
- [Использование Secret в Pod](../../secrets/secrets_basics.md)

### Projected Volume

Объединяет несколько источников (Secret, ConfigMap, Downward API, ServiceAccountToken) в одну точку монтирования. Это упрощает структуру манифеста и организацию файлов в container.
Подробнее: [Projected Volumes в Kubernetes](./projected_volumes.md).

### PersistentVolumeClaim (PVC)

Механизм запроса ресурсов хранения. Через PVC приложение абстрагируется от конкретных технологий (NFS, облачные диски, Ceph) и работает с абстрактным томом, который Kubernetes подключает к Pod через CSI (Container Storage Interface).
Подробнее: [PV, PVC и StorageClass](../../../Storage/pv_and_pvc.md).

---

## Практические сценарии

### Сценарий 1: emptyDir для совместной работы container

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

Монтирование логов хоста в режиме "только чтение" для безопасности.

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

---

## Дополнительная информация

**Связанные темы:**
- [Базовые концепции Volume](./volumes_basics.md)
- [Projected Volumes](./projected_volumes.md)
- [Downward API в Kubernetes](../downward_api.md)
- [PV (PersistentVolume) и PVC](../../../Storage/pv_and_pvc.md)

### Сравнение с Docker Volumes

Хотя концепции похожи, Kubernetes предоставляет более высокий уровень абстракции:

| Характеристика | Kubernetes Volume | Docker Volume |
| :--- | :--- | :--- |
| **Управление** | Декларативное (YAML) | Императивное (CLI) |
| **Масштабируемость** | Работает в рамках всего кластера | Ограничено одним хостом |
| **Драйверы** | CSI (облачные диски, распределенные ФС) | Volume Drivers (в основном локальные) |
| **Персистентность** | Гибкая настройка через PVC | Всегда персистентно |

**Ключевое отличие:** в Kubernetes тома являются частью жизненного цикла Pod (за исключением PVC), что обеспечивает предсказуемую очистку ресурсов и безопасность в динамических средах.

> **См. также:** [Тома в Docker (Docker Volumes)](../../../../Docker/Docker_fs/docker_volumes.md)
