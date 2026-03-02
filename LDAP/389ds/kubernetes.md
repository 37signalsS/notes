# Развертывание 389DS в Kubernetes

После освоения запуска в контейнерах, 389DS переносится в Kubernetes с использованием:
* **StatefulSet** — для сохранения состояния
* **PersistentVolumeClaim** — для персистентных данных
* **ConfigMap/Secret** — для конфигурации
* **Helm chart** — для автоматизации развертывания

> **Рекомендуемая последовательность:**
> 1. Запустить 389DS в Docker на отдельных машинах
> 2. Настроить кластер и репликацию
> 3. Перенести работающую конфигурацию в Kubernetes
> 4. Создать Helm chart для повторяемости

## Требования к кластеру Kubernetes

* Минимум 2 worker nodes (для отказоустойчивости)
* Ingress/LoadBalancer для доступа к сервису (MetalLB)
* Cert-manager для TLS-сертификатов

## StatefulSet конфигурация

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: 389ds
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
      initContainers:
        - name: check-replicas
          image: busybox
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
          image: 389ds/ds-container:latest
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
            - name: tls-ca
              mountPath: /data/tls/ca
              readOnly: true
          livenessProbe:
            exec:
              command: ["/bin/sh", "-c", "nslookup localhost"]
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            exec:
              command: ["/bin/sh", "-c", "nslookup localhost"]
            initialDelaySeconds: 30
            periodSeconds: 10
          resources:
            requests:
              memory: "2Gi"
              cpu: "1"
            limits:
              memory: "2Gi"
              cpu: "2"
      volumes:
        - name: tls
          secret:
            secretName: 389ds-tls
        - name: tls-ca
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

## Сервисы

```yaml
# Headless service для discovery подов
apiVersion: v1
kind: Service
metadata:
  name: 389ds-headless
spec:
  clusterIP: None
  selector:
    app: 389ds
  ports:
    - port: 3389
      name: ldap

---
# LoadBalancer для доступа к LDAP
apiVersion: v1
kind: Service
metadata:
  name: 389ds
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

## Инициализация и репликация через Job

Для автоматической инициализации 389DS (создание backend, настройка репликации) используется Job. Job выполняет shell-скрипт внутри контейнера 389DS.

### RBAC для Job

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: 389ds-init
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: 389ds-init
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
subjects:
  - kind: ServiceAccount
    name: 389ds-init
roleRef:
  kind: Role
  name: 389ds-init
  apiGroup: rbac.authorization.k8s.io
```

### Пример Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: 389ds-init
spec:
  template:
    spec:
      serviceAccountName: 389ds-init
      restartPolicy: OnFailure
      containers:
        - name: init
          image: 389ds/ds-container:latest
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
            - name: config
              mountPath: /config
      volumes:
        - name: init-script
          configMap:
            name: 389ds-init-script
        - name: config
          configMap:
            name: 389ds-config
```

### Основные задачи init-скрипта

1. **Проверка количества реплик** — не более 2 для простоты
2. **Настройка логирования** — JSON формат для логов
3. **Инициализация backend** — `dsconf backend create`
4. **Включение репликации** — `dsconf replica enable`
5. **Создание replication agreement** — между подами
6. **Заполнение LDAP-дерева** — базовые OU (people, groups, service)
7. **Включение плагинов** — RetroChangelog, MemberOf
8. **Перезапуск подов** — через `kubectl patch statefulset`

## Настройка TLS (cert-manager)

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: 389ds-tls
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
