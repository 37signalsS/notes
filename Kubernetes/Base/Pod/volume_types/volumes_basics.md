# Базовые концепции Volume в Kubernetes

## Определения

**Volume (том)** — абстракция файлового хранилища Kubernetes, предоставляющая контейнерам доступ к данным вне файловой системы контейнера.

**Жизненный цикл Volume:** Совпадает с жизненным циклом **пода**, а не отдельного контейнера. Данные сохраняются при перезапуске контейнеров и теряются только при удалении пода.

---

## Базовые концепции

### Проблемы, решаемые Volume

| Проблема | Решение |
| :--- | :--- |
| Файловая система контейнера эфемерна | Volume позволяет сохранять данные после перезапуска контейнера |
| Обмен данными между контейнерами в поде | Общий том предоставляет общее пространство для записи/чтения |
| Абстракция от технологий хранения | Kubernetes скрывает детали реализации хранилища (локальный диск, NFS, облачное хранилище) |

### Механизм работы

Манифест пода состоит из двух частей для работы с томами:

| Часть | Поле | Описание |
| :--- | :--- | :--- |
| **Определение тома** | `spec.volumes` | На уровне пода: список томов с именем и типом (источник данных) |
| **Монтирование тома** | `spec.containers[*].volumeMounts` | На уровне контейнера: точка монтирования (`mountPath`) в файловой системе |

**Важно:** Имя тома в `volumeMounts` должно соответствовать имени в `volumes`.

### Базовый пример манифеста

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pd
spec:
  containers:
  - name: test-container
    image: registry.k8s.io/test-webserver
    volumeMounts:
    - name: test-volume  # Ссылка на том из spec.volumes
      mountPath: /test   # Путь внутри контейнера
  volumes:
  - name: test-volume
    emptyDir: {}  # Тип тома
```

### Типы томов

Kubernetes поддерживает множество типов томов для различных сценариев:

| Тип | Категория | Краткое описание |
| :--- | :--- | :--- |
| `emptyDir` | Эфемерное | Временное хранилище, обмен данными между контейнерами |
| `hostPath` | Эфемерное | Доступ к файловой системе узла |
| `configMap` | Эфемерное | Конфигурационные файлы из ConfigMap |
| `secret` | Эфемерное | Конфиденциальные данные из Secret |
| `projected` | Эфемерное | Комбинация нескольких источников в одном томе |
| `persistentVolumeClaim` | Персистентное | Постоянное хранилище (БД, файлы пользователей) |

Подробнее о типах томов: [Типы томов](./volume_types.md).

---

## Практические сценарии

### Пример 1: Обмен данными между контейнерами через emptyDir

Два контейнера в одном поде используют общий том для обмена данными:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: producer-consumer
spec:
  volumes:
  - name: shared-data
    emptyDir: {}
  containers:
  - name: producer
    image: busybox
    command: ["sh", "-c", "while true; do echo $(date) >> /shared/data.txt; sleep 5; done"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
  - name: consumer
    image: busybox
    command: ["sh", "-c", "tail -f /shared/data.txt"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
```

**Как это работает:**
1. Контейнер `producer` записывает данные в `/shared/data.txt`
2. Контейнер `consumer` читает данные из того же файла
3. Оба контейнера видят одни и те же данные благодаря общему тому `emptyDir`

### Пример 2: Монтирование одного тома в разные пути

Один том может быть смонтирован в разные пути внутри одного или нескольких контейнеров:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-mount-pod
spec:
  volumes:
  - name: config-volume
    configMap:
      name: app-config
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: config-volume
      mountPath: /etc/app/config  # Конфигурация приложения
      readOnly: true
    - name: config-volume
      mountPath: /usr/share/app/templates  # Шаблоны
      readOnly: true
```

---

## Дополнительная информация

**Связанные темы:** [Типы томов](./volume_types.md), [Projected Volumes](./projected_volumes.md), [Downward API](../downward_api.md), [ConfigMap](../../ConfigMap/configmap.md), [Secret](../../secrets/secrets_basics.md).
