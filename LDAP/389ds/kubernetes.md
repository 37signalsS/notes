# Развёртывание 389DS в Kubernetes

## Определения

**StatefulSet** — контроллер Kubernetes для stateful-приложений с уникальными идентификаторами подов и персистентным хранилищем.

**Headless Service** — сервис без ClusterIP для прямого DNS-discovery подов StatefulSet.

## Базовые концепции

### Архитектура развёртывания

389DS в Kubernetes использует:
* **StatefulSet** — для сохранения состояния и стабильных идентификаторов
* **PersistentVolumeClaim** — для персистентных данных (режим RWO)
* **ConfigMap/Secret** — для конфигурации и чувствительных данных
* **Headless Service** — для discovery подов репликации

> **Рекомендуемая последовательность:**
> 1. Запустить 389DS в Docker на отдельных машинах
> 2. Настроить кластер и репликацию
> 3. Протестировать failover
> 4. Перенести работающую конфигурацию в Kubernetes
> 5. Создать Helm chart для повторяемости

### Требования к кластеру

| Требование | Описание |
| :--- | :--- |
| **Nodes** | Минимум 2 worker nodes для HA |
| **Storage** | StorageClass с поддержкой RWO |
| **Network** | Ingress/LoadBalancer (MetalLB) для внешнего доступа |
| **Certificates** | cert-manager для TLS-сертификатов (см. [Приватный CA](../../Kubernetes/ToolsUtilities/cert_manager/02_private_ca.md)) |

## Практические сценарии

### StatefulSet конфигурация

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
      # Anti-affinity для распределения по узлам
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: 389ds
              topologyKey: kubernetes.io/hostname
      # Ограничение количества реплик
      initContainers:
        - name: check-replicas
          image: busybox:1.36
          command: ["/bin/sh", "-c"]
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          args:
            - |
              POD_NUM=${POD_NAME##*-}
              if [ "$POD_NUM" -gt 1 ]; then
                echo "Maximum 2 replicas allowed, found: $POD_NUM"
                exit 1
              fi
      containers:
        - name: 389ds
          image: quay.io/389ds/ds-container:latest
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: SUFFIX
              value: "dc=example,dc=com"
            - name: DM_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-admin-secret
                  key: password
          ports:
            - containerPort: 3389
              name: ldap
            - containerPort: 3636
              name: ldaps
          volumeMounts:
            - name: data
              mountPath: /data
            - name: tls
              mountPath: /data/tls
              readOnly: true
          # Probes для проверки работоспособности
          livenessProbe:
            exec:
              command: ["/bin/sh", "-c", "ldapsearch -x -H ldap://localhost:3389 -b '' -s base '(objectClass=*)'"]
            initialDelaySeconds: 60
            periodSeconds: 10
            timeoutSeconds: 5
          readinessProbe:
            exec:
              command: ["/bin/sh", "-c", "ldapsearch -x -H ldap://localhost:3389 -b '' -s base '(objectClass=*)'"]
            initialDelaySeconds: 30
            periodSeconds: 5
            timeoutSeconds: 3
          resources:
            requests:
              memory: "2Gi"
              cpu: "1"
            limits:
              memory: "4Gi"
              cpu: "2"
      volumes:
        - name: tls
          secret:
            secretName: 389ds-tls
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: "standard"
        resources:
          requests:
            storage: 10Gi
```

### Сервисы

```yaml
# Headless service для discovery подов
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
    - port: 3636
      name: ldaps

---
# LoadBalancer для внешнего доступа
apiVersion: v1
kind: Service
metadata:
  name: 389ds
  namespace: ldap
  annotations:
    metallb.universe.tf/loadBalancerIPs: 192.168.1.100
spec:
  type: LoadBalancer
  selector:
    app: 389ds
  ports:
    - port: 389
      targetPort: 3389
      name: ldap
    - port: 636
      targetPort: 3636
      name: ldaps
```

### Инициализация через Job

Для автоматической инициализации (backend, репликация, плагины) используется Job.

#### RBAC для Job

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: 389ds-init
  namespace: ldap
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: 389ds-init
  namespace: ldap
rules:
  - apiGroups: ["apps"]
    resources: ["statefulsets"]
    verbs: ["get", "list", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: 389ds-init
  namespace: ldap
subjects:
  - kind: ServiceAccount
    name: 389ds-init
    namespace: ldap
roleRef:
  kind: Role
  name: 389ds-init
  apiGroup: rbac.authorization.k8s.io
```

#### Пример Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: 389ds-init
  namespace: ldap
spec:
  template:
    spec:
      serviceAccountName: 389ds-init
      restartPolicy: OnFailure
      containers:
        - name: init
          image: quay.io/389ds/ds-container:latest
          command: ["/bin/bash", "/init/init.sh"]
          env:
            - name: SUFFIX
              value: "dc=example,dc=com"
            - name: DM_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-admin-secret
                  key: password
            - name: REPLICATION_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-admin-secret
                  key: repl-password
            - name: NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          volumeMounts:
            - name: init-script
              mountPath: /init
      volumes:
        - name: init-script
          configMap:
            name: 389ds-init-script
```

#### Задачи init-скрипта

1. **Проверка количества реплик** — максимум 2 для простоты
2. **Инициализация backend** — `dsconf backend create`
3. **Включение репликации** — `dsconf replica enable`
4. **Создание replication agreement** — между подами
5. **Заполнение DIT** — базовые OU (people, groups, services)
6. **Включение плагинов** — RetroChangelog, MemberOf
7. **Перезапуск подов** — через `kubectl patch statefulset`

### Настройка TLS (cert-manager)

**Подробно:** См. [Интеграция с Ingress](../../Kubernetes/ToolsUtilities/cert_manager/05_ingress.md) или [Приватный CA](../../Kubernetes/ToolsUtilities/cert_manager/02_private_ca.md).

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: 389ds-tls
  namespace: ldap
spec:
  secretName: 389ds-tls
  dnsNames:
    - 389ds-headless.ldap.svc.cluster.local
    - 389ds-0.389ds-headless.ldap.svc.cluster.local
    - 389ds-1.389ds-headless.ldap.svc.cluster.local
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
```

## Дополнительная информация

### Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| Pod не запускается | Проверить логи: `kubectl logs 389ds-0 -n ldap` |
| PVC не создаётся | Проверить StorageClass: `kubectl get sc` |
| Репликация не работает | Проверить сеть между подами, DNS |

### Мониторинг

```bash
# Статус подов
kubectl get pods -l app=389ds -n ldap

# Проверка репликации
kubectl exec 389ds-0 -n ldap -- \
  dsconf replication status --suffix "dc=example,dc=com" me-to-389ds-1

# Логи
kubectl logs -f 389ds-0 -n ldap
```

### Best Practices

1. **Anti-affinity** — распределять поды по разным узлам
2. **Resource limits** — ограничивать CPU/RAM для предсказуемости
3. **Backup** — использовать `dsctl backup` перед обновлениями
4. **Update strategy** — обновлять по одному поду (RollingUpdate)
5. **Monitoring** — отслеживать статус репликации и свободное место

### Связанные темы

* [Docker развёртывание](./docker.md)
* [Настройка репликации](./replication.md)
* [Плагины](./plugins.md)
* [OpenLDAP в Kubernetes](../openldap_kubernetes.md)
