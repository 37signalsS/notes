Автоматический запуск на каждой ноде кластера по одному поду

``` sh
kubectl taint nodes my-node dedicated=special:NoSchedule
```
Поды не будут назначаться на my-node, если у них нет toleration = dedicated=special([[Pod]]).

``` yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluentd
  namespace: kube-system  # Обычно DaemonSet для логирования размещают в kube-system
  labels:
    k8s-app: fluentd-logging
spec:
  updateStrategy:
    rollingUpdate:
      maxUnavailable: 1
  selector:
    matchLabels:
      name: fluentd
  template:
    metadata:
      labels:
        name: fluentd
    spec:
      hostNetwork: true  # Использует сетевой namespace хоста
      hostPID: true  # Позволяет видеть процессы namespace хоста
      nodeSelector:
        kubernetes.io/os: linux  # Запускается только на узлах с ОС Linux
        log-node: "true"  # Разворачивается только на узлах с label log-node=true
      securityContext:  
        runAsNonRoot: true  
        runAsUser: 1000  # UID пользователя, под которым запустятся контейнеры
      tolerations:
        - key: node-role.kubernetes.io/master # master меняем на нужную роль
         #operator: Exists # позволяет игнорировать любые taints, независимо от их ключа, значения или эффекта, чтобы DaemonSet работал на всех нодах
          effect: NoSchedule  # запрещает назначать поды на ноду, если у них нет соответствующей toleration 
      containers:
        - name: fluentd
          image: fluent/fluentd:v1.15.3-debian-1
          env:
            - name: FLUENT_ELASTICSEARCH_HOST
              value: "elasticsearch.logging.svc.cluster.local"
            - name: FLUENT_ELASTICSEARCH_PORT
              value: "9200"
          resources:
            limits:
              memory: 200Mi
              cpu: 100m
          volumeMounts:
            - name: varlog
              mountPath: /var/log
            - name: dockercontainers
              mountPath: /var/lib/docker/containers
              readOnly: true
      volumes:
        - name: varlog
          hostPath:
            path: /var/log
        - name: dockercontainers
          hostPath:
            path: /var/lib/docker/containers # Замонтировать директори с хоста где запущено приложение в mountPath

```