# DaemonSet: Гарантированный запуск подов на каждом узле

**DaemonSet** — это контроллер Kubernetes, который обеспечивает запуск ровно одного экземпляра пода на каждом (или на определённом наборе) узле кластера. Если в кластер добавляется новый узел, DaemonSet автоматически развернет на нем под. При удалении узла — под будет корректно удален.

Это идеальный инструмент для развертывания системных сервисов, которые должны работать на всех или некоторых узлах для обеспечения мониторинга, сбора логов или сетевой функциональности.

### Ключевые сценарии использования:

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

## Пример: Развертывание Node Exporter для Prometheus


```yaml
# node-exporter-daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring # Системные агенты лучше размещать в отдельном неймспейсе
  labels:
    app: node-exporter
spec:
  # 1. Селектор для связи DaemonSet с его подами
  selector:
    matchLabels:
      app: node-exporter

  # 2. Стратегия обновления (по умолчанию RollingUpdate)
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      # Во время обновления может быть недоступен максимум 1 под
      maxUnavailable: 1

  # 3. Шаблон пода, который будет создаваться на каждом узле
  template:
    metadata:
      labels:
        app: node-exporter
    spec:
      # 4. Позволяет поду запускаться на master-узлах
      tolerations:
        - effect: NoSchedule
          operator: Exists

      # 5. Ограничиваем запуск только на узлах с ОС Linux
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
              memory: 128Mi
            requests:
              cpu: 100m
              memory: 128Mi
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

---

## Стратегии обновления DaemonSet

DaemonSet поддерживает две стратегии обновления, которые указываются в поле `spec.updateStrategy.type`:

1.  **`RollingUpdate` (по умолчанию):** Поды на узлах обновляются поочередно. Старый под удаляется, а новый создается. Это обеспечивает плавное обновление без простоя сервиса на всех узлах одновременно. Параметр `maxUnavailable` контролирует, сколько подов может быть недоступно в один момент времени.

2.  **`OnDelete`:** Kubernetes не будет автоматически обновлять поды при изменении шаблона DaemonSet. Чтобы применить изменения, вам нужно **вручную удалить** старые поды. После этого DaemonSet создаст новые, уже с обновленной конфигурацией. Эта стратегия полезна для критически важных агентов, обновление которых нужно контролировать полностью вручную.