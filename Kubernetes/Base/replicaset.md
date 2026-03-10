# ReplicaSet

## Определения

**ReplicaSet** — это объект Kubernetes, основная задача которого — гарантировать, что указанное количество идентичных подов (реплик) всегда будет запущено. `ReplicaSet` постоянно отслеживает количество подов, соответствующих его селектору (`selector`):

- Если подов меньше, чем `replicas`, он создает новые из шаблона (`template`).
- Если подов больше, он удаляет лишние.
- Если под, управляемый `ReplicaSet`, выходит из строя, контроллер автоматически создает замену.

`ReplicaSet` является преемником `ReplicationController`. Хотя его можно использовать и самостоятельно, сегодня `ReplicaSet` в основном используется как механизм для оркестровки подов в составе объекта [Deployment](./Deployment/index.md). `Deployment` управляет `ReplicaSet`-ами, которые, в свою очередь, управляют подами, что позволяет реализовать более сложные сценарии, такие как декларативные обновления и откаты.

## Основные концепции

### Анатомия манифеста

- **`replicas`**: Указывает желаемое количество реплик (подов), которое `ReplicaSet` должен постоянно поддерживать.
- **`selector`**: Определяет, как `ReplicaSet` находит поды, которыми он должен управлять. **Важно:** Метки (`labels`) в `spec.selector.matchLabels` должны в точности совпадать с метками в `spec.template.metadata.labels`.
- **`template`**: Это шаблон (blueprint), по которому будут создаваться поды. Он содержит свою `metadata` и `spec` с описанием контейнеров, полностью аналогично описанию простого [пода](./Pod/pod_overview.md).

## Практические сценарии

### Пример манифеста

Манифест ниже создает `ReplicaSet`, который будет поддерживать 2 работающих экземпляра пода с образом `nginx:1.28.0`.

```yaml
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: nginx-rs
  labels:
    run: nginx
spec:
  # 1. Желаемое количество реплик
  replicas: 2

  # 2. Селектор для связи с подами
  selector:
    matchLabels:
      run: nginx # Должен совпадать с меткой в шаблоне пода

  # 3. Шаблон для создания подов
  template:
    metadata:
      labels:
        run: nginx # Метка пода
    spec:
      containers:
      - name: nginx
        image: nginx:1.28.0
        ports:
        - containerPort: 80
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
          limits:
            memory: "128Mi"
            cpu: "250m"
```

### Создание и проверка

```bash
# Создание ReplicaSet из файла
kubectl apply -f nginx-replicaset.yaml

# Просмотр всех объектов в неймспейсе
# Мы увидим ReplicaSet и два созданных им пода
kubectl get all
# NAME             DESIRED   CURRENT   READY   AGE
# replicaset.apps/nginx-rs   2         2         2       7s
#
# NAME                 READY   STATUS    RESTARTS   AGE
# pod/nginx-rs-a9z7d   1/1     Running   0          7s
# pod/nginx-rs-b8x6k   1/1     Running   0          7s

# Просмотр с расширенной информацией (IP, нода)
kubectl get all -o wide
```

### Демонстрация самовосстановления

Если удалить один из подов, управляемых `ReplicaSet`, контроллер немедленно обнаружит это и создаст новый под для поддержания заданного количества реплик.

```bash
# Удаляем один из подов
kubectl delete pod nginx-rs-a9z7d
# pod "nginx-rs-a9z7d" deleted

# Сразу проверяем состояние
kubectl get pods
# NAME                 READY   STATUS              RESTARTS   AGE
# pod/nginx-rs-b8x6k   1/1     Running             0          90s
# pod/nginx-rs-c1v5f   0/1     ContainerCreating   0          1s
```

Новый под `nginx-rs-c1v5f` был автоматически запущен взамен удаленного.

## Ограничения ReplicaSet

Основной недостаток `ReplicaSet` — **отсутствие механизма декларативных обновлений**. Если вам нужно обновить версию приложения (например, изменить тег образа с `nginx:1.28.0` на `nginx:1.29.0`), вам придется вручную:

1. Удалить старый `ReplicaSet`.
2. Создать новый `ReplicaSet` с обновленным шаблоном пода.

Это приводит к простою приложения. Именно для решения этой проблемы был создан [Deployment](./Deployment/index.md), который автоматизирует процесс создания и управления `ReplicaSet`-ами, обеспечивая плавные обновления (`Rolling Update`).

## Связанные темы

- [Deployment](./Deployment/index.md) — декларативное управление ReplicaSet-ами и подами.
- [Pod](./Pod/pod_overview.md) — базовый объект развертывания.
