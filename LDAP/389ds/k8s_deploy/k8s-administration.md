# 389DS в Kubernetes: Развёртывание и администрирование

## Определения

Для понимания архитектуры развёртывания 389 Directory Server (389DS) в кластере Kubernetes используются следующие понятия:

*   **[StatefulSet](../../../Kubernetes/Base/StatefulSet/statefulset_overview.md)** — основной контроллер для управления инстансами 389DS, обеспечивающий стабильные идентификаторы и персистентное хранилище.
*   **[Headless Service](../../../Kubernetes/Networking/Service/service_type_headless.md)** — сервис без ClusterIP, необходимый для прямой DNS-адресации подов (например, для настройки репликации между узлами).
*   **DIT (Directory Information Tree)** — иерархическая структура данных внутри LDAP, которая в K8s часто инициализируется автоматически при первом запуске пода.
*   **Suffix (Суффикс)** — корневой DN каталога (например, `dc=example,dc=com`), определяющий область данных.
*   **Backend (Бэкенд)** — дисковое хранилище конкретного суффикса (в 389DS 3.x используется высокопроизводительный движок LMDB).

## Базовые концепции

### Архитектура развёртывания

Развёртывание 389DS в Kubernetes строится на принципах высокой доступности (HA) и персистентности:

1.  **Хранение данных:** Каждый под StatefulSet получает собственный `PersistentVolume` (PV) через `volumeClaimTemplates`. Рекомендуется использовать `reclaimPolicy: Retain` на уровне StorageClass для предотвращения потери данных при удалении ресурсов.
2.  **Сетевая идентификация:** Использование **Headless Service** позволяет подам обращаться друг к другу по именам вида `389ds-0.389ds-headless.ldap.svc.cluster.local`, что критично для стабильной Multi-Master репликации.
3.  **Конфигурация:** Настройки передаются через переменные окружения и монтируемые `ConfigMap` (для скриптов инициализации и кастомных `.inf` файлов).

### Требования к ресурсам

| Ресурс | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Память (RAM)** | от 2Gi до 4Gi | LMDB активно использует memory-mapping для кэширования БД. |
| **Процессор (CPU)** | от 1 до 2 ядер | Зависит от интенсивности операций записи и количества плагинов. |
| **Диск** | SSD (RWO) | 389DS чувствителен к задержкам дисковой подсистемы. |

## Практические сценарии

### Развёртывание StatefulSet

Ниже представлен актуальный манифест для развёртывания 389DS версии 3.x с использованием официального образа.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: 389ds
  namespace: ldap
spec:
  serviceName: 389ds-headless
  replicas: 2
  selector:
    matchLabels:
      app: 389ds
  template:
    metadata:
      labels:
        app: 389ds
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: 389ds
              topologyKey: kubernetes.io/hostname
      containers:
        - name: 389ds
          image: quay.io/389ds/ds-container:latest
          env:
            - name: DS_DM_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-secrets
                  key: dm-password
            - name: DS_SUFFIX_NAME
              value: "dc=example,dc=com"
          ports:
            - containerPort: 3389
              name: ldap
            - containerPort: 3636
              name: ldaps
          volumeMounts:
            - name: data
              mountPath: /data
          livenessProbe:
            tcpSocket:
              port: ldap
            initialDelaySeconds: 60
            periodSeconds: 10
          readinessProbe:
            exec:
              command: ["/usr/bin/dsctl", "instance", "status", "localhost"]
            initialDelaySeconds: 30
            periodSeconds: 10
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

### Сетевой доступ

Для внутреннего взаимодействия и внешнего доступа используются два типа сервисов:

```yaml
# Headless Service для репликации
apiVersion: v1
kind: Service
metadata:
  name: 389ds-headless
  namespace: ldap
spec:
  clusterIP: None
  selector:
    app: 389ds
  ports:
    - port: 3389
      name: ldap

---
# LoadBalancer для клиентов (например, через MetalLB)
apiVersion: v1
kind: Service
metadata:
  name: 389ds-external
  namespace: ldap
spec:
  type: LoadBalancer
  selector:
    app: 389ds
  ports:
    - port: 389
      targetPort: 3389
      name: ldap
```

### Инициализация и автоматизация

В современных версиях контейнера рекомендуется использовать автоматическую инициализацию через переменные окружения `DS_*` или подкладывание `.inf` файлов в `/data/config`.

**Основные задачи автоматизации:**
1.  **Создание инстанса:** Происходит автоматически при первом запуске, если `/data` пуст.
2.  **Настройка репликации:** Выполняется через `dsconf` после запуска всех подов.
3.  **Плагины:** Включение `MemberOf` и `Retro Changelog` является стандартом для интеграций.

## Дополнительная информация

### Мониторинг и диагностика

Основные команды для проверки состояния 389DS внутри пода:

*   **Статус инстанса:** `dsctl instance list`
*   **Статус репликации:** `dsconf -ls ldap://localhost:3389 replication status --suffix "dc=example,dc=com"`
*   **Логи доступа:** `kubectl logs -f 389ds-0 -c 389ds` (основные логи зеркалируются в stdout контейнера).

### Устранение неполадок (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в CrashLoopBackOff** | Ошибка прав на `/data` или неверный пароль DM | Проверить `chown 389:389` на томе (если используется не стандартный образ) и Secret. |
| **Репликация не сходится** | Проблемы DNS или несовпадение сертификатов TLS | Проверить резолвинг имен через `nslookup 389ds-0.389ds-headless`. |
| **Низкая производительность** | Недостаточно RAM для кэша LMDB | Увеличить memory limits и проверить параметры `nsslapd-cachememsize`. |

---

## См. также
*   [Обзор 389 Directory Server](../overview.md) — общие принципы и архитектура.
*   [Репликация в 389DS](../replication.md) — детальное описание механизмов Multi-Master.
*   [389DS в Docker](../docker.md) — альтернативный вариант развёртывания.
