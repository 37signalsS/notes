# Alertmanager StatefulSet: Манифест и конфигурация

## Определения

**Alertmanager StatefulSet** — основной ресурс Kubernetes для развёртывания Alertmanager. Использование StatefulSet вместо Deployment обеспечивает стабильные сетевые идентификаторы (важно для кластеризации) и гарантирует привязку PersistentVolume для сохранения состояния (silences, нотификации).

**Расширение переменных окружения (External Variable Expansion)** — функция Alertmanager (v0.27+), позволяющая подставлять значения из переменных окружения напрямую в файл `alertmanager.yml` через синтаксис `${VAR_NAME}`.

> **См. также:** [Развёртывание Alertmanager в Kubernetes](../../alertmanager.md#развёртывание-в-kubernetes-через-манифесты).

---

## Основные концепции

### Структура пода

В современных инсталляциях (2025–2026) рекомендуется использовать встроенную поддержку переменных окружения, что упрощает манифест и избавляет от необходимости в `init-container`.

| Компонент | Назначение |
| :--- | :--- |
| **Alertmanager** | Образ `prom/alertmanager:v0.27.0`. Флаг `--config.expand-external-variables` активирует подстановку секретов. |
| **Volumes** | Монтирование ConfigMap с шаблоном конфига и PVC для данных. |

### Схема томов (Volumes)

| Том | Источник | Точка монтирования | Описание |
| :--- | :--- | :--- | :--- |
| `config` | ConfigMap | `/etc/alertmanager` | Содержит `alertmanager.yml` с плейсхолдерами `${VAR}`. |
| `templates` | ConfigMap | `/etc/alertmanager/templates` | Дополнительные Go-шаблоны оформления. |
| `data` | PVC | `/alertmanager` | Хранение состояния (1Gi, ReadWriteOnce). |

---

## Практические сценарии

### Манифест StatefulSet

Пример современной конфигурации с использованием нативного расширения переменных из Secret.

**`alertmanager-statefulset.yaml`**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: alertmanager
  namespace: monitoring
spec:
  serviceName: alertmanager
  replicas: 1
  selector:
    matchLabels:
      app: alertmanager
  template:
    metadata:
      labels:
        app: alertmanager
    spec:
      containers:
        - name: alertmanager
          image: prom/alertmanager:v0.27.0
          args:
            - "--config.file=/etc/alertmanager/alertmanager.yml"
            - "--storage.path=/alertmanager"
            # Важно: включаем поддержку переменных в конфиге
            - "--config.expand-external-variables"
          ports:
            - name: web
              containerPort: 9093
          env:
            # Извлекаем секреты напрямую в переменные окружения
            - name: SMTP_PASSWORD
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: smtp.password } }
            - name: TELEGRAM_TOKEN
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: telegram.token } }
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

### Альтернатива: Использование Init Container

В учебных целях или для систем, не поддерживающих расширение переменных, может использоваться паттерн с `busybox` и `sed` (описан в полной версии руководства). Он позволяет подготовить конфиг до запуска основного процесса.

---

## Дополнительная информация

- **[Секреты Kubernetes](./secrets.md)** — описание ключей в Secret.
- **[Конфигурация (ConfigMap)](./alertmanager-config.md)** — синтаксис `${}` в конфиге.
- **[Шаблоны сообщений](./alertmanager-templates.md)** — оформление уведомлений.
- **[Reliability Scores](../../../../GEMINI.md)** — методология оценки достоверности (Score: 10).
