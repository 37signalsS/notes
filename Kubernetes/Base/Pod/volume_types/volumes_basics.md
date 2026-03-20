# Базовые концепции Volume в Kubernetes

## Определения

**Volume** — это абстракция файлового хранилища, которая решает следующие ключевые проблемы:

* Файловая система контейнера существует только до его удаления. `Volume` позволяет сохранять данные даже после перезапуска контейнера.
* Некоторым контейнерам в одном поде требуется общее пространство для обмена файлами.
* Абстрагирование приложения от конкретных технологий хранения данных на узле.

Жизненный цикл `Volume` совпадает с жизненным циклом **пода**, а не отдельного контейнера. Это означает, что данные в томе сохраняются при перезапуске контейнеров и теряются только тогда, когда удаляется сам под.

## Механизм работы

Механизм состоит из двух частей в манифесте пода:

1. `spec.volumes`: На уровне пода определяется список томов, которые будут доступны в этом поде. Здесь указывается имя тома и его тип (источник данных).
2. `spec.containers[*].volumeMounts`: На уровне каждого контейнера определяется, куда (`mountPath`) в его файловой системе будет смонтирован том, определенный в `spec.volumes`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pd
spec:
  containers:
  - image: registry.k8s.io/test-webserver
    name: test-container
    # Монтируем том 'test-volume' в директорию /test внутри контейнера
    volumeMounts:
    - mountPath: /test
      name: test-volume
  # На уровне пода определяем, что такое 'test-volume'
  volumes:
  - name: test-volume
    # В данном примере используется временный том emptyDir
    emptyDir: {}
```

## Практический пример: обмен данными между контейнерами через emptyDir

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
  # Контейнер-производитель: пишет данные
  - name: producer
    image: busybox
    command: ["sh", "-c", "while true; do echo $(date) >> /shared/data.txt; sleep 5; done"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
  # Контейнер-потребитель: читает данные
  - name: consumer
    image: busybox
    command: ["sh", "-c", "tail -f /shared/data.txt"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
```

## Дополнительные ссылки

- [Типы томов](./volume_types.md) — подробное описание всех типов томов
- [Projected Volumes](./projected_volumes.md) — расширенные возможности projected volumes
- [Downward API](../downward_api/) — получение метаданных пода
