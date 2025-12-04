# DaemonSet

**DaemonSet** — это контроллер Kubernetes, который обеспечивает запуск ровно одного экземпляра пода на каждом (или на определённом наборе) узле кластера. Если в кластер добавляется новый узел, DaemonSet автоматически развернет на нем под. При удалении узла — под будет корректно удален.

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

### Сценарий: Гарантированный запуск перед другими подами

`Taints` и `Tolerations` также являются ключевым механизмом для обеспечения того, чтобы `DaemonSet` (например, сетевой плагин CNI или агент мониторинга) был полностью запущен и готов на узле *до* того, как на него начнут размещаться обычные поды приложений.

Паттерн выглядит следующим образом:
1. На узел при добавлении в кластер вешается `taint` с эффектом `NoSchedule`.
2. В манифест `DaemonSet` добавляется соответствующий `toleration`, что позволяет ему запуститься на этом узле.
3. После успешного запуска пода `DaemonSet`, внешний контроллер (или логика самого демона) убирает `taint` с узла.
4. Планировщик начинает размещать на узле обычные поды.

> Подробное описание этого сценария можно найти в документе **[Taints and Tolerations](../Scheduling/taints_and_tolerations.md#практический-сценарий-отложенный-запуск-подов-до-готовности-daemonset)**.


---

## Пример: Развертывание Fluentd для сбора логов

```yaml
# fluentd-daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluentd-daemonset
  namespace: monitoring # Системные агенты лучше размещать в отдельном неймспейсе
  labels:
    app: fluentd
spec:
  selector:
    matchLabels:
      app: fluentd
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      # Во время обновления может быть недоступен максимум 1 под
      maxUnavailable: 1
  template:
    metadata:
      labels:
        app: fluentd
    spec:
      # Ограничиваем запуск только на узлах с ОС Linux и специальной меткой
      nodeSelector:
        kubernetes.io/os: linux
        log-node: "true"
      # Позволяет поду запускаться на master-узлах, которые часто имеют taint NoSchedule
      tolerations:
      - key: "node-role.kubernetes.io/master"
        operator: "Exists"
        effect: "NoSchedule"
      securityContext:  
        runAsNonRoot: true  
        runAsUser: 1000  # UID пользователя, под которым запустятся контейнеры
      containers:
      - name: fluentd
        image: fluent/fluentd:v1.19.0-debian-1.0
        env:
        - name: FLUENT_ELASTICSEARCH_HOST # Подробнее о настройке кластера Elasticsearch: [Elasticsearch](../../ELK_Stack/Elasticsearch/elasticsearch_sharding_replication_cluster.md)
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
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
      terminationGracePeriodSeconds: 30
      # volumes определяет тома, которые будут использоваться в поде
      volumes:
      - name: varlog
        hostPath: # hostPath монтирует директорию с хост-машины
          path: /var/log
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
```

---

## Стратегии обновления DaemonSet

DaemonSet поддерживает две стратегии обновления, которые указываются в поле `spec.updateStrategy.type`:

1.  **`RollingUpdate` (по умолчанию):** Поды на узлах обновляются поочередно. Старый под удаляется, а новый создается. Это обеспечивает плавное обновление без простоя сервиса на всех узлах одновременно. Параметр `maxUnavailable` контролирует, сколько подов может быть недоступно в один момент времени.
2.  **`OnDelete`:** Kubernetes не будет автоматически обновлять поды при изменении шаблона DaemonSet. Чтобы применить изменения, вам нужно **вручную удалить** старые поды. После этого DaemonSet создаст новые, уже с обновленной конфигурацией. Эта стратегия полезна для критически важных агентов, обновление которых нужно контролировать полностью вручную.
