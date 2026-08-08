# 389DS в Kubernetes: Развёртывание и администрирование

## Определения

Для понимания архитектуры развёртывания 389 Directory Server (389DS) в кластере Kubernetes используются следующие понятия:

*   **[StatefulSet](../../../Kubernetes/Base/StatefulSet/statefulset_overview.md)** — основной контроллер для управления инстансами 389DS, обеспечивающий стабильные сетевые идентификаторы (hostname) и персистентное хранилище.
*   **[Headless Service](../../../Kubernetes/Networking/Service/service_type_headless.md)** — сервис без ClusterIP, необходимый для прямой DNS-адресации подов (например, `389ds-0.389ds-headless`), что критично для работы Multi-Master репликации.
*   **[StartupProbe](../../../Kubernetes/Base/probes.md)** — механизм проверки начального запуска, предотвращающий перезапуск контейнера во время длительной инициализации базы данных или индексации.
*   **SecurityContext** — настройки безопасности пода/контейнера, обеспечивающие запуск процесса от не привилегированного пользователя (UID 389).
*   **DIT (Directory Information Tree)** — иерархическая структура данных LDAP, которая в Kubernetes-контейнере инициализируется при первом запуске, если том `/data` пуст.

## Базовые концепции

### Архитектура развёртывания

Развёртывание 389DS в Kubernetes (актуально для версии 3.x в 2026 году) строится на следующих принципах:

1.  **Персистентность:** Все данные (конфигурация, БД, логи) хранятся в директории `/data`. Использование `PersistentVolumeClaim` (PVC) в составе `StatefulSet` гарантирует сохранение данных при перезапуске подов.
2.  **Сетевая идентификация:** Каждый под получает стабильное FQDN вида `pod-name.service-name.namespace.svc.cluster.local`, которое используется для настройки соглашений о репликации (Replication Agreements).
3.  **Безопасность Non-root:** Контейнер должен запускаться от пользователя `dirsrv` (UID 389). Это требует настройки `fsGroup` в `podSecurityContext` для корректного доступа к томам.

### Требования к ресурсам

В 2026 году для стабильной работы 389DS в Production рекомендуются следующие параметры:

| Ресурс | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Память (RAM)** | от 4Gi до 8Gi | LMDB требует значительного объема для кэширования (Memory Mapped Files). |
| **Процессор (CPU)** | от 2 до 4 ядер | Высокая параллельность при обработке запросов и работе плагинов. |
| **Диск** | SSD/NVMe (RWO) | Критично для производительности транзакционного лога LMDB. |

**Важно:** Используйте переменную окружения `DS_MEMORY_PERCENTAGE` (например, `50`), чтобы сервер корректно рассчитывал кэш на основе установленных в Kubernetes `limits.memory`.

## Практические сценарии

### Развёртывание StatefulSet (Стандарт 2026)

Ниже представлен актуальный манифест с использованием современного образа `dirsrv` и настроенными проверками здоровья.

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
      securityContext:
        fsGroup: 389
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: 389ds
              topologyKey: kubernetes.io/hostname
      containers:
        - name: 389ds
          image: quay.io/389ds/dirsrv:latest
          env:
            - name: DS_DM_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-secrets
                  key: dm-password
            - name: DS_SUFFIX_NAME
              value: "dc=example,dc=com"
            - name: DS_MEMORY_PERCENTAGE
              value: "50"
          ports:
            - containerPort: 3389
              name: ldap
            - containerPort: 3636
              name: ldaps
            - containerPort: 9100
              name: metrics
          resources:
            requests:
              cpu: "1"
              memory: "2Gi"
            limits:
              cpu: "2"
              memory: "4Gi"
          volumeMounts:
            - name: data
              mountPath: /data
          startupProbe:
            exec:
              command: ["/usr/sbin/dsctl", "localhost", "status"]
            initialDelaySeconds: 15
            failureThreshold: 30
            periodSeconds: 10
          livenessProbe:
            tcpSocket:
              port: ldap
            initialDelaySeconds: 60
            periodSeconds: 20
          readinessProbe:
            exec:
              command: ["/usr/sbin/dsctl", "localhost", "status"]
            initialDelaySeconds: 10
            periodSeconds: 10
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 20Gi
```

### Настройка безопасности и TLS

В 2026 году для управления сертификатами рекомендуется использовать `cert-manager`. Сертификаты монтируются как секреты, а 389DS настраивается на их использование через `.inf` файл или `dsconf`.

**Рекомендуемый подход:**
1.  Выпуск сертификата через `cert-manager` для каждого пода (используя DNS-имя Headless-сервиса).
2.  Монтирование секрета в `/data/tls`.
3.  Настройка LDAPS:
```bash
# Внутри контейнера
dsconf -D "cn=Directory Manager" ldap://localhost:3389 security tls set \
    --certificate-file /data/tls/tls.crt \
    --key-file /data/tls/tls.key \
    --ca-certificate-file /data/tls/ca.crt
```

### Резервное копирование (Backup)

Для бэкапа LDAP в Kubernetes используется `CronJob`, который выполняет экспорт данных в LDIF-формат.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: 389ds-backup
spec:
  schedule: "0 2 * * *" # Ежедневно в 02:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: quay.io/389ds/dirsrv:latest
            command:
            - /usr/sbin/dsconf
            - -D
            - "cn=Directory Manager"
            - ldap://389ds-0.389ds-headless.ldap.svc:3389
            - backend
            - export
            - userRoot
            - --output-file
            - /data/backups/backup-$(date +%F).ldif
            env:
            - name: LDAP_PW
              valueFrom:
                secretKeyRef:
                  name: 389ds-secrets
                  key: dm-password
            volumeMounts:
            - name: data
              mountPath: /data
          restartPolicy: OnFailure
          volumes:
          - name: data
            persistentVolumeClaim:
              claimName: data-389ds-0
```

## Дополнительная информация

### Мониторинг

389DS 3.x включает встроенный экспортер метрик в формате Prometheus (обычно на порту 9100 или через LDAP-интерфейс).

*   **ServiceMonitor:** Используйте для интеграции с Prometheus Operator.
*   **Ключевые метрики:**
    *   `ds_connection_current_total` — текущие соединения.
    *   `ds_operation_search_total` — количество поисковых операций.
    *   `ds_backend_entry_cache_hit_ratio` — эффективность кэша (должна быть >90%).

### Сетевая политика (NetworkPolicy)

Для защиты LDAP-сервера ограничьте доступ только доверенными клиентами.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: 389ds-allow-ldap
  namespace: ldap
spec:
  podSelector:
    matchLabels:
      app: 389ds
  ingress:
    - from:
        - podSelector:
            matchLabels:
              allow-ldap: "true"
      ports:
        - protocol: TCP
          port: 3389
        - protocol: TCP
          port: 3636
```

### Устранение неполадок (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **StartupProbe failure** | Долгая проверка БД после падения | Увеличить `failureThreshold` или `periodSeconds` в `startupProbe`. |
| **Permission denied на /data** | Неверный `fsGroup` | Убедитесь, что в `securityContext` указан `fsGroup: 389`. |
| **Replication lags** | Проблемы с DNS Headless-сервиса | Проверить резолвинг: `nslookup 389ds-1.389ds-headless`. |
| **OOMKill** | Некорректный `DS_MEMORY_PERCENTAGE` | Снизить значение переменной или увеличить `limits.memory`. |

---

## См. также
*   [Обзор 389 Directory Server](../overview.md) — общие принципы и архитектура.
*   [Репликация в 389DS](../replication.md) — детальное описание механизмов Multi-Master.
*   [389DS в Docker](../docker.md) — альтернативный вариант развёртывания.
