# kube-prometheus-stack: Практические сценарии

### Настройка доступа к веб-интерфейсам

*   **Grafana:**
    ```yaml
    grafana:
      ingress:
        enabled: true
        hosts:
          - grafana.example.com
    ```

*   **Prometheus:**
    ```yaml
    prometheus:
      ingress:
        enabled: true
        hosts:
          - prometheus.S4999.edu.example.com # Пример DNS-имени, используемого в стендах пользователя
        annotations: # Можно использовать для автоматического получения TLS-сертификатов
          cert-manager.io/cluster-issuer: "letsencrypt-prod"
    ```

### Настройка мониторинга внешних ресурсов (static_configs)

Позволяет добавлять кастомные `scrape_configs` напрямую в конфигурацию Prometheus. Это основной способ настроить мониторинг целей, которые находятся **вне Kubernetes** (виртуальные машины, физические серверы).

*   **Пример:** Мониторинг внешнего хоста с `node-exporter`.
    ```yaml
    prometheus:
      prometheusSpec:
        additionalScrapeConfigs:
          - job_name: 'external-nodes'
            static_configs:
              - targets: ['192.168.1.100:9100', '192.168.1.101:9100']
                labels:
                  env: 'production'
    ```

### Обогащение метрик `node-exporter`
Позволяет определить специфичные для `node-exporter` правила `relabeling` для обогащения метрик.

*   **Пример:** Добавление читаемого имени узла в метрики.
    ```yaml
    prometheus:
      prometheusSpec:
        scrapeClasses:
          - name: node-exporter
            relabelingConfigs:
              - sourceLabels: [__meta_kubernetes_pod_node_name]
                targetLabel: node
                action: replace
    ```

### Сбор метрик с master-нод

Позволяет подам Node Exporter размещаться на master-нодах, которые по умолчанию имеют `taint` (например, `NoSchedule`).

*   **Рекомендация:** Добавить `toleration`, чтобы собирать метрики со всех узлов кластера.
    ```yaml
    nodeExporter:
      tolerations:
        - operator: "Exists"
          effect: "NoSchedule"
    ```

### Настройка Persistent Volumes (PV) вручную

Если ваш `StorageClass` не поддерживает динамическое создание томов (dynamic provisioning), вам потребуется создать PersistentVolume вручную. Это актуально, например, при использовании `local-storage`.

*   **Пример манифеста PV:**
    ```yaml
    apiVersion: v1
    kind: PersistentVolume
    metadata:
      name: pv-prometheus-1
    spec:
      capacity:
        storage: 5Gi
      accessModes:
        - ReadWriteOnce
      storageClassName: local-storage
      local:
        path: /mnt/local-pv-1 # Путь на хостовой машине, который должен существовать
      nodeAffinity:
        required:
          nodeSelectorTerms:
            - matchExpressions:
                - key: kubernetes.io/hostname
                  operator: In
                  values:
                    - node-1 # Имя ноды, на которой будет использоваться PV
    ```
    **Важно:** Перед применением манифеста необходимо убедиться, что директория, указанная в `local.path`, существует на соответствующей ноде. **Не забудьте создать эти директории на целевых узлах кластера перед применением PV-манифестов.**

### Авторизация в веб-интерфейсе

1.  **Через Ingress:** Исторически доступ к интерфейсу Prometheus защищался через Basic Auth на уровне Ingress. Это позволяет настроить окно ввода логина и пароля при доступе к Prometheus через Ingress.
2.  **Закрытый контур:** Не выставлять Prometheus наружу, держать его в закрытых контурах с подключением через VPN. Это наиболее безопасный вариант, но не всегда возможный.
3.  **Нативная авторизация Prometheus:** В новых версиях Prometheus появилась **нативная поддержка Basic Auth**, которую можно настроить непосредственно в конфигурации самого Prometheus. Это более современный и безопасный способ. Также появилась возможность авторизации по TLS-сертификатам. Подробности можно можно найти в `release notes` соответствующей версии Prometheus.
