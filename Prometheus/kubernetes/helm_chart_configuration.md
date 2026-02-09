# Конфигурация Helm-чарта kube-prometheus-stack

## Определения

**`kube-prometheus-stack`** — это Helm-чарт, предназначенный для развертывания и управления полным стеком мониторинга в среде Kubernetes. Он включает в себя [Prometheus](../overview.md), [Alertmanager](../alertmanager.md), [Grafana](../../Grafana/grafana_overview.md), а также ключевые экспортеры и конфигурационные ресурсы.

**`values.yaml`** — основной конфигурационный файл Helm-чарта, который позволяет кастомизировать развертываемые компоненты и их параметры.

## Базовые концепции

В данном разделе рассматриваются ключевые параметры файла `values.yaml`, используемого для конфигурации стека мониторинга.

### Глобальные параметры и RBAC

*   `rbac.create`: `true`
    *   **Описание:** Создает все необходимые роли и привязки (Roles, RoleBindings) для работы компонентов стека в кластере.
    *   **Рекомендация:** Оставить `true`.

*   `serviceAccount.create`: `true`
    *   **Описание:** Создает ServiceAccount для каждого компонента.
    *   **Рекомендация:** Оставить `true`.

### Конфигурация Alertmanager

> ℹ️ Для детального изучения Alertmanager обратитесь к основной заметке: [alertmanager](../alertmanager.md).

*   `alertmanager.enabled`: `true`
    *   **Рекомендация:** Оставить включенным для управления алертами.

*   `alertmanager.ingress.enabled`: `false`
    *   **Описание:** Создает Ingress-ресурс для доступа к веб-интерфейсу Alertmanager.
    *   **Рекомендация:** Можно оставить выключенным, так как основной интерфейс для работы — это Grafana.

*   `alertmanager.persistentVolume.enabled`: `true`
    *   **Описание:** Включает использование PersistentVolume для сохранения состояния Alertmanager (например, созданных "подавлений" - silences).
    *   **Рекомендация (Production):** Обязательно `true`, чтобы сделать его stateful.
    *   `storageClass`: Необходимо указать имя существующего в кластере `StorageClass`.
    *   `size`: Размер диска подбирается эмпирически, можно начать с `2Gi`.

*   `alertmanager.replicaCount`: `1`
    *   **Рекомендация (Production):** Установить значение `3` для обеспечения высокой доступности и кворума.

*   `alertmanager.resources`:
    *   **Описание:** Запросы (`requests`) и лимиты (`limits`) по CPU и Memory.
    *   **Рекомендация:** Подбираются эмпирически. Можно начать с минимальных значений (`requests: cpu: 100m, memory: 32Mi`) и наблюдать за потреблением.

### Конфигурация Grafana

> ℹ️ Для детального изучения Grafana обратитесь к основной заметке: [grafana_overview](../../Grafana/grafana_overview.md).

*   `grafana.enabled`: `true`
    *   **Рекомендация:** Оставить `true`.

*   `grafana.adminPassword`:
    *   **Описание:** Позволяет задать пароль для пользователя `admin`.
    *   **Рекомендация:** Установить надежный пароль или сослаться на `Secret`. Не оставлять пароль по умолчанию.
        ```yaml
        grafana:
          adminPassword: "MySecurePassword"
        ```

*   `grafana.grafana.ini`:
    *   **Описание:** Позволяет кастомизировать основной конфигурационный файл Grafana `grafana.ini`.
    *   **Пример:** Настройка `root_url` важна, чтобы Grafana генерировала корректные ссылки в уведомлениях.
        ```yaml
        grafana:
          grafana.ini:
            server:
              root_url: "https://grafana.example.com"
        ```

*   `grafana.sidecar`:
    *   **Описание:** Включает механизм автоматического обнаружения и загрузки дашбордов из `ConfigMap`.
    *   **Рекомендация:** Обязательно включить для реализации подхода "Dashboards as Code".
        ```yaml
        grafana:
          sidecar:
            dashboards:
              enabled: true
              label: grafana_dashboard
              # Сайдкар будет искать ConfigMap'ы с этим лейблом
        ```

*   `grafana.additionalGrafanaPlugins`:
    *   **Описание:** Позволяет устанавливать дополнительные плагины для Grafana.
    *   **Пример:** Установка плагина `worldmap-panel`.
        ```yaml
        grafana:
          additionalGrafanaPlugins:
            - "grafana-worldmap-panel"
        ```

*   `grafana.persistence`:
    *   **Описание:** Настройка постоянного хранилища для Grafana.
    *   **Рекомендация (Production):** Обязательно включить, чтобы сохранять дашборды, созданные через UI, и другие настройки.
        ```yaml
        persistence:
          enabled: true
          type: pvc
          storageClassName: "your-storage-class"
          accessModes:
            - ReadWriteOnce
          size: 10Gi
        ```

### Конфигурация `kube-state-metrics`

*   `kube-state-metrics.enabled`: `true`
    *   **Описание:** Включает развертывание `kube-state-metrics`, который генерирует метрики о состоянии объектов Kubernetes (Deployments, Pods, Nodes и т.д.).
    *   **Рекомендация:** Оставить `true`. Это один из ключевых источников метрик о состоянии кластера.

### Конфигурация ConfigMapReload

ConfigMapReload — это вспомогательный компонент, который автоматически перезагружает конфигурацию Prometheus и Alertmanager при изменении соответствующих ConfigMap.

*   `configmapReload.enabled`: `true`
    *   **Описание:** Включает развертывание `configmap-reload` контейнера.
    *   **Рекомендация:** Оставить `true` для автоматической перезагрузки конфигураций без ручного вмешательства.

### Конфигурация Node Exporter

> ℹ️ Общую информацию об экспортерах метрик можно найти в заметке: [exporters](../exporters.md).

*   `nodeExporter.enabled`: `true`
    *   **Рекомендация:** Оставить `true` для сбора метрик с нод.

*   `nodeExporter.hostNetwork`: `true`
    *   **Описание:** Позволяет подам Node Exporter использовать сетевой namespace хоста (`hostNetwork: true`) и PID namespace хоста (`hostPID: true`).
    *   **Рекомендация:** Оставить `true` для корректного сбора сетевых метрик и метрик процессов с хоста.

*   `nodeExporter.resources`:
    *   **Рекомендация:** Как и для других компонентов, задать минимальные значения и наблюдать.

### Конфигурация Prometheus Server

Это основной компонент системы мониторинга. Общие рекомендации и лучшие практики по работе с Prometheus описаны в документе [PromTool и лучшие практики Prometheus](../promtool_and_best_practices.md). Концептуальное описание конфигурации сервера, включая Service Discovery и `relabel_configs`, можно найти в [Обзоре конфигурации сервера Prometheus](../service_discovery_and_relabeling.md).

*   `prometheus.enabled`: `true`
    *   **Рекомендация:** Оставить `true`.

*   `prometheus.prometheusSpec.scrapeInterval`, `scrapeTimeout`, `evaluationInterval`:
    *   `scrapeInterval`: Частота сбора метрик с таргетов. Подбирается эмпирически. Если метрик собирается большой объем, то есть смысл собирать их реже (например, `30s` или `1m`). Если метрик немного, то можно собирать их чаще.
    *   `scrapeTimeout`: Время, по истечении которого Prometheus будет считать, что сбор метрик с таргета не удался.
    *   `evaluationInterval`: Как часто Prometheus должен вычислять правила алертинга. Это значение также подбирается эмпирически. Например, если настроено правило на проверку количества ETCD-узлов (не менее трех), то при уменьшении их числа до двух, сигнал будет передан в AlertManager через указанный `evaluationInterval`.

*   `prometheus.prometheusSpec.remoteWrite`, `remoteRead`:
    *   **Описание:** Настройки для интеграции с внешними долгосрочными хранилищами (например, [VictoriaMetrics](../../VictoriaMetrics/victoria_metrics_overview.md), Thanos, M3DB).
    *   **Рекомендация:** Использовать в production для долгосрочного хранения метрик, так как хранение больших объемов данных в самом Prometheus неэффективно и может привести к деградации производительности.

*   `prometheus.prometheusSpec.storage`:
    *   **Описание:** Определяет конфигурацию хранилища для `StatefulSet`'а Prometheus. Использование `volumeClaimTemplate` является стандартным подходом.
    *   **Рекомендация (Production):** Обязательно настроить для сохранения данных при перезапусках.
    *   `storageClassName`: Необходимо указать имя существующего в кластере `StorageClass`.
    *   `storage`: Размер диска подбирается в зависимости от количества метрик и срока хранения (`retention`).
        ```yaml
        prometheus:
          prometheusSpec:
            storage:
              volumeClaimTemplate:
                spec:
                  storageClassName: "your-storage-class"
                  accessModes: ["ReadWriteOnce"]
                  resources:
                    requests:
                      storage: 50Gi
        ```

*   `prometheus.replicaCount`: `1`
    *   **Рекомендация (Production):** Установить значение больше `1` для высокой доступности.

*   `prometheus.prometheusSpec.retention`: `15d`
    *   **Описание:** Срок хранения метрик в локальном хранилище Prometheus. Метрики старше этого срока будут удалены.
    *   **Рекомендация:** Настраивается эмпирически в зависимости от доступного дискового пространства, требований к хранению и влияния на нагрузку сервера. Если объем метрик слишком велик, и кластер не справляется, следует уменьшить срок хранения. Для долгосрочного хранения используется `remoteWrite`.

*   `prometheus.prometheusSpec.retentionSize`: `""`
    *   **Описание:** (Альфа-версия) Позволяет ограничивать хранилище по размеру (например, `50GB`), а не только по времени.
    *   **Рекомендация:** Использовать с осторожностью, так как это экспериментальная функция.

### Конфигурация Push Gateway

> ℹ️ Для детального изучения Push Gateway обратитесь к основной заметке: [pushgateway](../pushgateway.md).

Push Gateway используется для сбора метрик от кратковременных или периодически запускаемых задач, которые не могут быть "собраны" (scraped) Prometheus напрямую.

*   `pushgateway.enabled`: `true`
    *   **Описание:** Включает развертывание Push Gateway.
    *   **Рекомендация:** Оставить `true` по умолчанию, если нет необходимости его отключать. В данном контексте он не используется, но может быть полезен в других сценариях.

## Практические сценарии

### Процесс установки

1.  **Скачать чарт локально:**
    ```bash
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update
    helm pull prometheus-community/prometheus --untar
    ```
    **Рекомендация:** Всегда работайте с локальной копией чарта. Это позволяет версионировать конфигурацию (`values.yaml`) вместе с кодом вашего приложения и интегрировать развертывание в CI/CD. Установка через CI/CD помогает избежать несоответствий версий и конфигураций, которые могут привести к болезненным проблемам при обновлении.

2.  **Создать PV (при необходимости):**
    ```bash
    kubectl apply -f pv-manifests/
    ```

3.  **Установить чарт:**
    ```bash
    helm install prometheus ./prometheus \
      --namespace monitoring \
      --create-namespace \
      -f values.yaml
    ```
    **Примечание:** Если при установке возникают ошибки, например, из-за пустых списков в `values.yaml` (как в строке 493 в примере), убедитесь, что все списки корректно заполнены или закомментированы. После успешной установки проверьте статус подов (`kubectl get pods -n monitoring`), PV/PVC (`kubectl get pv,pvc -n monitoring`) и Ingress (`kubectl get ingress -n monitoring`).

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

## Дополнительная информация

Для общего обзора технологий рекомендуется ознакомиться с основными заметками:
- [Helm](../../Kubernetes/ToolsUtilities/helm_overview.md)
- [Kubernetes](../../Kubernetes/kubernetes_overview.md)
- [Prometheus](../overview.md)