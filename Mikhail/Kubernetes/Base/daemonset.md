# DaemonSet

**DaemonSet** — это объект Kubernetes, который гарантирует, что на каждом (или на определённом наборе) узле кластера будет запущен ровно один экземпляр пода. Это идеально подходит для развертывания системных сервисов, которые должны работать на всех или некоторых узлах.

### Примеры использования:

*   **Сборщики логов:** Fluentd, Logstash, Promtail.
*   **Агенты мониторинга:** Prometheus Node Exporter, Datadog Agent, New Relic.
*   **Сетевые плагины:** Calico, Flannel, Cilium.
*   **Системы хранения:** Ceph, GlusterFS.

---

### Taints и Tolerations

Часто `DaemonSet` используется в связке с `tolerations`, чтобы иметь возможность запускаться даже на "загрязненных" (tainted) узлах, например, на мастер-узлах.

Команда для установки "загрязнения" на узел:
```bash
# Узел 'my-node' будет принимать только поды, у которых есть соответствующий 'toleration'.
kubectl taint nodes my-node dedicated=special:NoSchedule
```
*   `NoSchedule`: Новые поды не будут планироваться на этот узел, если у них нет `toleration`.
*   `NoExecute`: Новые поды не будут планироваться, а уже запущенные (без `toleration`) будут выселены.

---

### Пример: DaemonSet для Fluentd

Этот `DaemonSet` разворачивает под с Fluentd на каждом узле для сбора логов. Он использует `tolerations`, чтобы работать даже на мастер-узлах, и `volumeMounts` для доступа к логам хост-машины.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluentd-collector
  namespace: kube-system # Системные сервисы принято размещать в kube-system
  labels:
    k8s-app: fluentd-logging
spec:
  # Стратегия обновления: как будут обновляться поды DaemonSet
  updateStrategy:
    rollingUpdate:
      maxUnavailable: 1 # Во время обновления может быть недоступен максимум 1 под
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
            requests:
              cpu: 100m
              memory: 200Mi
          volumeMounts:
            # Монтируем директории с логами и контейнерами с хост-машины внутрь пода
            - name: varlog
              mountPath: /var/log
            - name: dockercontainers
              mountPath: /var/lib/docker/containers
              readOnly: true
      # volumes определяет тома, которые будут использоваться в поде
      volumes:
        # Определяем тома, которые будут использоваться в поде
        - name: varlog
          hostPath: # hostPath монтирует директорию с хост-машины
            path: /var/log
        - name: dockercontainers
          hostPath:
            path: /var/lib/docker/containers # Замонтировать директори с хоста где запущено приложение в mountPath
```