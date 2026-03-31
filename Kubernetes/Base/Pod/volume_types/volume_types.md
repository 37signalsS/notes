# Типы томов в Kubernetes

## Определения

**Volume (том)** — абстракция файлового хранилища Kubernetes, предоставляющая контейнерам доступ к данным вне файловой системы контейнера.

**Эфемерное хранилище** — тома, жизненный цикл которых совпадает с жизненным циклом пода (emptyDir, hostPath, configMap, secret). Данные удаляются при удалении пода.

**Персистентное хранилище** — тома, жизненный цикл которых не зависит от пода (persistentVolumeClaim). Данные сохраняются после удаления пода.

---

## Базовые концепции

### Классификация типов томов

| Тип | Категория | Назначение | Персистентность |
| :--- | :--- | :--- | :--- |
| `emptyDir` | Эфемерное | Временное хранилище, обмен данными между контейнерами | Нет |
| `hostPath` | Эфемерное | Доступ к файловой системе узла | Нет (привязка к ноде) |
| `configMap` | Эфемерное | Конфигурационные файлы | Нет |
| `secret` | Эфемерное | Конфиденциальные данные (пароли, ключи) | Нет |
| `projected` | Эфемерное | Комбинация нескольких источников | Нет |
| `persistentVolumeClaim` | Персистентное | Постоянное хранилище (БД, файлы пользователей) | Да |

### emptyDir

**Описание:** Пустой каталог, создаваемый вместе с подом на узле. Существует, пока под работает на этом узле.

**Жизненный цикл:** Данные сохраняются при перезапуске контейнера, но удаляются при удалении пода.

**Источник:** По умолчанию создаётся на диске узла (`/var/lib/kubelet/pods/...`). Можно использовать оперативную память.

**Сценарии использования:**

| Сценарий | Описание |
| :--- | :--- |
| Временное хранилище (кэш) | Для данных, которые не страшно потерять |
| Обмен данными между контейнерами | Основной способ обмена файлами в multi-container Pod (sidecar-паттерн) |
| Инициализация данных | `initContainer` подготавливает данные для основных контейнеров |

**Параметры:**

| Параметр | Описание | Предостережения |
| :--- | :--- | :--- |
| `medium: Memory` | Создание `emptyDir` в оперативной памяти (tmpfs) | Потребляемая память учитывается в `limits.memory` контейнера. Без лимитов возможно `OOMKill` |
| `sizeLimit` | Ограничение размера тома (например, `1Gi`) | При превышении под будет выселен (`evicted`) с узла |

**Важно:** Не используйте `emptyDir` для персистентных данных (базы данных). Это эфемерное хранилище.

### hostPath

**Описание:** Монтирует файл или директорию с файловой системы узла внутрь пода.

**Ключевое ограничение:** Данные физически находятся на конкретной ноде. При перемещении пода на другую ноду доступ к данным теряется. Непригоден для stateful-приложений в многоузловых кластерах.

**Типы (`type`):**

| Тип | Описание |
| :--- | :--- |
| `Directory` | Путь должен существовать и быть директорией. Если нет — под не запустится |
| `DirectoryOrCreate` | Если директория не существует, `kubelet` создаст её с правами `0755` и владельцем `root` |
| `File`, `FileOrCreate`, `Socket`, `CharDevice`, `BlockDevice` | Другие типы для специфических сценариев |

**Проблема с правами доступа:** При использовании `DirectoryOrCreate` созданная директория принадлежит `root`. Контейнер, запущенный от непривилегированного пользователя (`runAsUser: 1000`), не сможет записывать данные.

**Решение:** Заранее создать директорию на узле и выставить права (`chown`). Для гарантированного попадания пода на подготовленный узел использовать `nodeAffinity`.

**Основное применение:** DaemonSet для агентов мониторинга (node-exporter), сборщиков логов (fluent-bit), плагинов CNI. Том монтируется в режиме `readOnly: true`.

**Пример: Сборщик логов**

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: log-collector
spec:
  template:
    spec:
      containers:
      - name: fluent-bit
        image: fluent/fluent-bit
        volumeMounts:
        - name: varlog
          mountPath: /var/log
          readOnly: true
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
          type: Directory
```

> **ВНИМАНИЕ: УГРОЗА БЕЗОПАСНОСТИ.** Использование `hostPath` нарушает изоляцию контейнера, предоставляет доступ к файловой системе хоста и может привести к компрометации узла. В кластерах с политиками безопасности (PSA, OPA) `hostPath` обычно запрещён для рабочих нагрузок.

### configMap и secret

**Описание:** Позволяют передать данные из [ConfigMap](../../ConfigMap/configmap.md) или [Secret](../../secrets/secrets_basics.md) в под в виде файлов.

**Сценарии использования:**

| Тип | Назначение |
| :--- | :--- |
| `configMap` | Конфигурационные файлы, настройки приложения |
| `secret` | TLS-сертификаты, пароли, ключи API |

### projected

**Описание:** Объединяет несколько источников (`secret`, `configMap`, `downwardAPI`, `serviceAccountToken`) в один том, монтируемый как единая директория.

**Основное преимущество:** Одна точка монтирования вместо нескольких отдельных томов.

Подробнее: [Projected Volumes](./projected_volumes.md).

### persistentVolumeClaim

**Описание:** Способ смонтировать персистентное хранилище, жизненный цикл которого не зависит от пода.

**Сценарии использования:** Хранение данных приложений, требующих сохранения (базы данных, файлы пользователей).

Подробнее: [PV, PVC и StorageClass](../../../Storage/pv_and_pvc.md).

---

## Практические сценарии

### Пример 1: emptyDir для обмена данными между контейнерами

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: shared-volume-pod
spec:
  volumes:
  - name: shared-data
    emptyDir:
      sizeLimit: 500Mi
  containers:
  - name: producer
    image: busybox
    command: ["sh", "-c", "echo 'data' > /shared/data.txt"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
  - name: consumer
    image: busybox
    command: ["sh", "-c", "cat /shared/data.txt"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
```

### Пример 2: emptyDir в оперативной памяти

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: memory-backed-emptydir
spec:
  volumes:
  - name: cache
    emptyDir:
      medium: Memory
      sizeLimit: 1Gi
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: cache
      mountPath: /cache
    resources:
      limits:
        memory: 2Gi  # Обязательно при использовании medium: Memory
```

### Пример 3: hostPath для DaemonSet (сборщик логов)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
spec:
  template:
    spec:
      containers:
      - name: node-exporter
        image: prom/node-exporter
        volumeMounts:
        - name: proc
          mountPath: /host/proc
          readOnly: true
        - name: sys
          mountPath: /host/sys
          readOnly: true
      volumes:
      - name: proc
        hostPath:
          path: /proc
          type: Directory
      - name: sys
        hostPath:
          path: /sys
          type: Directory
```

---

## Дополнительная информация

**Связанные темы:** [Базовые концепции Volume](./volumes_basics.md), [Projected Volumes](./projected_volumes.md), [ConfigMap](../../ConfigMap/configmap.md), [Secret](../../secrets/secrets_basics.md), [PV и PVC](../../../Storage/pv_and_pvc.md).
