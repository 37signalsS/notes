# Local Path Provisioner

## Определения

**Local Path Provisioner** — Kubernetes-провижинер от Rancher, позволяющий использовать локальное хранилище на узлах кластера через стандартный механизм PVC/PV. Он динамически создаёт `PersistentVolume` из пути на файловой системе хоста, являясь легковесной альтернативой сложным СХД и прямому использованию `HostPath`.

Является стандартным (default) решением для хранения данных в дистрибутиве **K3s**.

## Базовые концепции

### Принцип работы

Provisioner работает как `Deployment`, отслеживающий создание PVC с указанным `StorageClass`.

**Алгоритм при создании PVC:**

1. Под с PVC планируется планировщиком на конкретный узел.
2. Provisioner запускает временный "helper" под на этом же узле.
3. Helper под выполняет `mkdir -p` для создания директории в сконфигурированном пути (например, `/opt/local-path-provisioner/<pvc-name>`).
4. Создаётся `PersistentVolume`, указывающий на эту директорию.
5. PVC связывается с PV (статус `Bound`).

**При удалении PVC:**

- Helper под выполняет `rm -rf` для очистки директории (если Reclaim Policy — `Delete`).
- PV удаляется.

**Преимущество:** Абстракция от прямого использования `HostPath`, повышенная безопасность и упрощённое управление жизненным циклом томов.

### Сравнение с альтернативами

| Решение | Плюсы | Минусы | Когда использовать |
|---------|-------|--------|------------------|
| **Local Path Provisioner** | Простота, высокая производительность, стандартные PVC/PV | Данные привязаны к узлу, нет репликации, нет контроля ёмкости по умолчанию | Dev/Test, кэширование, временные данные, Edge/IoT |
| **HostPath** | Максимальная производительность | Небезопасно, требует ручного создания PV, сложно управлять в динамическом кластере | **Не рекомендуется** для общего использования |
| **NFS/Сетевые ФС** | Доступ со всех узлов, `ReadWriteMany` | Производительность ограничена сетью, требуется отдельный сервер | Общие данные, RWX-требования |
| **Longhorn/Ceph** | Репликация, миграция, снимки, отказоустойчивость | Высокая сложность, накладные расходы на CPU/Сеть | Production, важные данные ([Longhorn](./longhorn.md)) |

### Ограничения

| Ограничение | Описание | Обход / Решение |
|-------------|----------|-------|
| **Привязка к узлу** | Том физически на одном узле. При перемещении пода на другой узел доступ к данным теряется | Использовать `affinity` для жёсткой привязки подов к узлам |
| **Нет контроля ёмкости** | Размер PVC игнорируется. Приложение может занять всё пространство диска хоста | Отдельные диски/разделы, квоты на уровне LVM, мониторинг диска |
| **Только RWO** | Режим `ReadWriteMany` не поддерживается | Использовать NFS/CephFS для сценариев RWX |
| **Node failure** | При выходе узла из строя данные становятся недоступны до восстановления узла | Регулярные бэкапы или использование реплицируемых систем (Longhorn) |

### Безопасность (CVE-2025-62878)

**Критическое обновление:** В версиях до **v0.0.34** существовала критическая уязвимость (CVSS 10.0), позволявшая выполнять атаку "path traversal" через шаблоны путей в StorageClass, давая доступ к произвольным файлам хоста.
- **Действие:** Обязательное обновление до версии **v0.0.34+** (рекомендуется **v0.0.36**).
- **Hardening:** Ограничьте доступ к редактированию ConfigMap `local-path-config`, так как содержащиеся в нем скрипты запускаются от имени root на хостах.

### volumeBindingMode: WaitForFirstConsumer

**Критически важный параметр** для локальных хранилищ.

| Режим | Описание |
|-------|----------|
| `Immediate` | PV создаётся сразу при создании PVC. Риск: PV может быть создан на узле A, а планировщик позже решит запустить под на узле B |
| `WaitForFirstConsumer` | PV создаётся только ПОСЛЕ того, как под будет назначен на узел. Гарантирует совпадение места хранения и места запуска |

**Рекомендация:** Для Local Path Provisioner всегда используйте `WaitForFirstConsumer`.

## Практические сценарии

### Установка

Актуальная версия (март 2026): **v0.0.36**.

#### Способ 1: Манифест (YAML)

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.36/deploy/local-path-storage.yaml
```

#### Способ 2: Helm

```bash
helm repo add rancher https://charts.rancher.io
helm repo update
helm install local-path rancher/local-path-provisioner \
  --namespace local-path-storage \
  --create-namespace
```

### Конфигурация

Настройка выполняется через `ConfigMap` `local-path-config` в пространстве имен установки.

#### Базовая конфигурация (один путь)

```json
{
  "nodePathMap": [
    {
      "node": "DEFAULT_PATH_FOR_NON_LISTED_NODES",
      "paths": ["/opt/local-path-provisioner"]
    }
  ]
}
```

#### Несколько StorageClass для разных типов дисков

**Шаг 1:** Обновите `ConfigMap`, перечислив доступные пути:

```json
{
  "nodePathMap": [
    {
      "node": "DEFAULT_PATH_FOR_NON_LISTED_NODES",
      "paths": ["/mnt/fast-ssd", "/mnt/slow-hdd"]
    }
  ]
}
```

**Шаг 2:** Создайте специфичные `StorageClass`:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path-ssd
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
parameters:
  hostDir: /mnt/fast-ssd
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path-hdd
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
parameters:
  hostDir: /mnt/slow-hdd
```

### Использование со StatefulSet

StatefulSet требует стабильных идентификаторов и привязки данных.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-sts-headless
spec:
  clusterIP: None
  selector:
    app: my-sts-app
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: my-sts
spec:
  serviceName: "my-sts-headless"
  replicas: 2
  selector:
    matchLabels:
      app: my-sts-app
  template:
    metadata:
      labels:
        app: my-sts-app
    spec:
      affinity:
        # Привязка к узлам с меткой worker=true
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: "node-role.kubernetes.io/worker"
                operator: In
                values: ["true"]
        # Распределение подов по разным узлам
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values: ["my-sts-app"]
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: nginx
        image: nginx:latest
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "local-path-ssd"
      resources:
        requests:
          storage: 1Gi
```

**Объяснение параметров affinity:**

| Параметр | Назначение |
|----------|------------|
| `nodeAffinity` | Гарантирует, что поды будут запускаться только на специализированных рабочих узлах |
| `podAntiAffinity` | Запрещает планировщику размещать два пода одного StatefulSet на одном физическом узле, предотвращая потерю всех реплик при сбое узла |

### Мониторинг и диагностика

- **Health Probes:** Начиная с v0.0.33, провижинер поддерживает пробу `/health` на порту `8080`.
- **Логирование:** Для отладки процесса создания томов:
  ```bash
  kubectl logs -n local-path-storage -l app=local-path-provisioner
  ```
- **События PVC:** При ошибке `ProvisioningFailed` проверьте:
  ```bash
  kubectl describe pvc <pvc-name>
  ```

### Устранение неисправностей (Troubleshooting)

#### PVC завис в Pending
- **Причина:** Под не назначен на узел. Так как используется `WaitForFirstConsumer`, провижинер ждет решения планировщика.
- **Решение:** Проверьте `kubectl describe pod <pod-name>` на предмет проблем с ресурсами или `nodeSelector`.

#### Ошибка запуска Helper Pod (Pod Security Admission)
- **Сценарий:** В кластере включен режим `restricted` PSA. Helper под пытается примонтировать `hostPath` и блокируется.
- **Решение:** Добавьте исключение для namespace `local-path-storage`:
  ```bash
  kubectl label ns local-path-storage pod-security.kubernetes.io/enforce=privileged
  ```

#### Проблемы с правами (Permission Denied)
- **Сценарий:** Контейнер запускается от не-root пользователя и не может писать в смонтированную директорию.
- **Решение:** Настройте `fsGroup` в `securityContext` пода или используйте скрипт `setup` в ConfigMap для смены владельца директории.

## Дополнительная информация

- Базовые концепции хранения: [PersistentVolume и PVC](./pv_and_pvc.md).
- Контроллер для stateful-приложений: [StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md).
- Альтернатива для RWX: [NFS Provisioner](./nfs-subdir-external-provisioner.md).
- Официальный репозиторий: [github.com/rancher/local-path-provisioner](https://github.com/rancher/local-path-provisioner).
