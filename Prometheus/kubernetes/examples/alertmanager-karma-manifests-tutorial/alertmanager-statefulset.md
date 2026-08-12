# Alertmanager StatefulSet: Манифест и конфигурация

## Определения

**Alertmanager StatefulSet** — основной ресурс Kubernetes для развёртывания Alertmanager. Использование StatefulSet вместо Deployment обеспечивает стабильные сетевые идентификаторы (например, `alertmanager-0`), что критически важно для работы Gossip-протокола кластеризации, и гарантирует привязку PersistentVolume для сохранения состояния (silences, журнал уведомлений).

**Расширение переменных окружения (External Variable Expansion)** — функция Alertmanager (v0.27+), позволяющая динамически подставлять значения из ENV напрямую в `alertmanager.yml` через синтаксис `${VAR_NAME}`, что исключает хранение секретов в ConfigMap.

> **См. также:** [Развёртывание Alertmanager в Kubernetes](../../../alertmanager.md#развёртывание-в-kubernetes-через-манифесты).

---

## Основные концепции

### Структура пода и безопасность

В современных инсталляциях (2025–2026) акцент делается на безопасности и нативной интеграции с секретами Kubernetes.

| Компонент | Назначение |
| :--- | :--- |
| **Alertmanager** | Образ `prom/alertmanager:v0.27.0`. Флаг `--config.expand-external-variables` активирует подстановку ENV. |
| **SecurityContext** | Запуск от non-root пользователя (`uid: 65534`) для минимизации привилегий контейнера. |
| **Кластеризация** | Использование флага `--cluster.peer` для связи реплик через Headless Service. |
| **Пробы (Probes)** | Проверки `/health` для управления трафиком и автоматического перезапуска при сбоях. |

### Схема томов (Volumes)

| Том | Источник | Точка монтирования | Описание |
| :--- | :--- | :--- | :--- |
| `config` | ConfigMap | `/etc/alertmanager` | Содержит основной файл конфигурации с плейсхолдерами. |
| `templates` | ConfigMap | `/etc/alertmanager/templates` | Кастомные Go-шаблоны оформления уведомлений. |
| `data` | PVC | `/alertmanager` | Персистентное хранилище (1Gi, ReadWriteOnce). |

---

## Практические сценарии

### Манифест StatefulSet (Production-ready)

Пример конфигурации с пробами, ресурсами и безопасным контекстом.

**`alertmanager-statefulset.yaml`**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: alertmanager
  namespace: monitoring
spec:
  serviceName: alertmanager-mesh
  replicas: 3
  selector:
    matchLabels:
      app: alertmanager
  template:
    metadata:
      labels:
        app: alertmanager
    spec:
      securityContext:
        runAsUser: 65534
        runAsGroup: 65534
        fsGroup: 65534
      containers:
        - name: alertmanager
          image: prom/alertmanager:v0.27.0
          args:
            - "--config.file=/etc/alertmanager/alertmanager.yml"
            - "--storage.path=/alertmanager"
            - "--config.expand-external-variables"
            - "--cluster.listen-address=0.0.0.0:9094"
            - "--cluster.peer=alertmanager-mesh.monitoring.svc.cluster.local:9094"
          ports:
            - name: web
              containerPort: 9093
            - name: mesh
              containerPort: 9094
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits: { cpu: 200m, memory: 256Mi }
          livenessProbe:
            httpGet: { path: /-/healthy, port: web }
            initialDelaySeconds: 30
            timeoutSeconds: 5
          readinessProbe:
            httpGet: { path: /-/ready, port: web }
            initialDelaySeconds: 15
            timeoutSeconds: 5
          env:
            - name: SMTP_PASSWORD
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: smtp.password } }
            - name: TELEGRAM_TOKEN
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: telegram.token } }
            - name: TELEGRAM_CHAT_ID
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: telegram.chat_id } }
          volumeMounts:
            - name: config
              mountPath: /etc/alertmanager
            - name: templates
              mountPath: /etc/alertmanager/templates
              readOnly: true
            - name: alertmanager-data
              mountPath: /alertmanager
      volumes:
        - name: config
          configMap: { name: alertmanager-config }
        - name: templates
          configMap: { name: alertmanager-templates }
  volumeClaimTemplates:
    - metadata:
        name: alertmanager-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources: { requests: { storage: 1Gi } }
```

---

## Дополнительная информация

- **[Сетевой доступ: Сервисы и Ingress](./services.md)** — описание Headless Service для кластеризации.
- **[Конфигурация (ConfigMap)](./alertmanager-config.md)** — синтаксис маршрутов и `${}` в конфиге.
- **[Шаблоны сообщений](./alertmanager-templates.md)** — подключение и использование Go Templates.
- **[Секреты Kubernetes](./secrets.md)** — подготовка ключей в Secret для ENV-подстановки.
