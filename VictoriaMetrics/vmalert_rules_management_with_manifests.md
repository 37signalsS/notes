# Управление правилами vmalert с помощью манифестов Kubernetes

## 1. Проблема: Управление правилами в Helm-чарте

При использовании [vmalert](./vmalert_overview.md) в Kubernetes стандартный подход — установка через Helm-чарт. Однако этот метод имеет существенный недостаток: все правила алертинга (`alerting rules`) должны быть определены внутри одного файла `values.yaml`. По мере роста количества правил, они превращаются в одну длинную, трудноуправляемую "колбасу" кода. Управление десятками и сотнями правил в одном большом файле становится крайне неудобным и затрудняет поддержку.

Более гибкий и масштабируемый подход — отказаться от управления правилами через Helm-чарт и перейти на использование нативных манифестов Kubernetes.

**Основная идея**:
1.  Использовать Helm только для **однократной генерации** первоначального шаблона манифестов (`Deployment`, `Service`, `RBAC` и т.д.).
2.  Вынести правила алертинга в **отдельные, логически сгруппированные `ConfigMap`**.
3.  Модифицировать `Deployment` `vmalert`, чтобы он монтировал эти `ConfigMap` как файлы и загружал из них правила.

Этот подход позволяет управлять каждой группой правил как независимым объектом Kubernetes, что идеально вписывается в методологию GitOps и упрощает автоматизацию, ревью и поддержку.

## 2. Практический сценарий: От Helm-чарта к манифестам

### Шаг 1: Генерация манифестов из Helm-чарта

Сначала необходимо сгенерировать базовые манифесты из чарта.

1.  **Подготовка зависимостей (subcharts)**
    Официальный чарт `vmalert` может иметь зависимости. Чтобы команда `helm template` сработала корректно локально, необходимо сначала загрузить эти зависимости.

    ```bash
    # Создайте временную рабочую директорию
    mkdir -p vmalert-generation/charts
    cd vmalert-generation/charts

    # Загрузите зависимый чарт (имя и репозиторий могут отличаться)
    # Например, для чарта от VictoriaMetrics
    helm pull vm/victoria-metrics-k8s-stack --untar

    # Вернитесь в корневую директорию генерации
    cd ..
    ```
    > **Важно**: ArgoCD обрабатывает зависимости чартов автоматически, поэтому при развертывании через ArgoCD этот шаг не требуется. Он необходим **именно для локальной генерации шаблонов**. После генерации манифестов эту директорию можно удалить, чтобы не хранить лишние файлы в Git.

2.  **Генерация шаблона**
    Используйте `helm template`, указав имя релиза, путь к чарту и ваши `values`. На этом этапе важно, чтобы в `my-values.yaml` была хотя бы одна "заглушка" для правил, иначе чарт может не сгенерировать `ConfigMap` и связанные с ним секции.

    ```bash
    helm template vmalert vm/vmalert \
      -f my-values.yaml \
      > vmalert-manifests.yaml
    ```
    > **Ошибка**: Если вы не загрузили зависимости, Helm выдаст ошибку, что не может найти subchart, например: `Error: found in Chart.yaml, but missing in charts/ directory: victoria-metrics-k8s-stack`.

### Шаг 2: Разделение и очистка манифестов

Сгенерированный `vmalert-manifests.yaml` будет содержать все ресурсы в одном файле. Для удобства разделите их на логические части:
-   `vmalert-deployment.yaml` (содержит только `Deployment` и, возможно, `Ingress`)
-   `vmalert-rbac.yaml` (ServiceAccount, Role, RoleBinding, ClusterRoleBinding)
-   `vmalert-service.yaml` (Service)

Также рекомендуется очистить манифесты от ненужных артефактов, добавленных Helm, например, `namespace: default`. **Однако будьте осторожны**: не удаляйте указание `namespace` из `subjects` в `ClusterRoleBinding`, так как это приведет к ошибке RBAC.

### Шаг 3: Создание ConfigMap для правил

Это ключевой шаг. Вместо одного `ConfigMap`, управляемого Helm, создайте отдельные `ConfigMap` для каждой логической группы правил.

**Пример: `alert-rules-cpu.yaml`**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vmalert-rules-cpu # Уникальное имя для ConfigMap
  namespace: monitoring
data:
  # Имя файла, который будет смонтирован в под
  alert-rules-cpu.yaml: |
    groups:
      - name: cpu-alerts
        rules:
          - alert: HighCpuUsage
            expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100) > 85
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "High CPU usage on node {{ $labels.instance }}"
              description: "CPU usage is above 85% for more than 5 minutes."
```
Создайте аналогичные файлы для других групп правил (память, диск, специфичные для приложений и т.д.).

### Шаг 4: Модификация Deployment `vmalert`

Теперь нужно обновить `Deployment`, чтобы он использовал созданные `ConfigMap`.

1.  **Добавление томов (`volumes`)**: В спецификации `Deployment` (`spec.template.spec.volumes`) добавьте по одному тому типа `configMap` для каждого `ConfigMap` с правилами.
2.  **Монтирование томов в контейнер (`volumeMounts`)**: В спецификации контейнера `vmalert` (`spec.template.spec.containers[0].volumeMounts`) смонтируйте каждый том. Использование `subPath` позволяет монтировать `ConfigMap` как отдельный файл, а не директорию.
3.  **Обновление команды запуска**: В команде запуска контейнера `vmalert` (`spec.template.spec.containers[0].args`) перечислите **все** файлы правил через флаг `-rule`.

**Пример `vmalert-deployment.yaml` (фрагменты):**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vmalert
  namespace: monitoring
spec:
  template:
    spec:
      containers:
        - name: vmalert
          args:
            - -datasource.url=http://victoria-metrics-single-server.monitoring.svc:8429/
            - -notifier.url=http://alertmanager.monitoring.svc:9093/
            # Ключевое изменение: перечисляем все файлы правил
            - -rule=/config/rules/cpu/alert-rules-cpu.yaml
            - -rule=/config/rules/memory/alert-rules-memory.yaml
            # ... и так далее для каждого нового файла правил
          volumeMounts:
            - name: alert-config-cpu
              mountPath: /config/rules/cpu/alert-rules-cpu.yaml
              subPath: alert-rules-cpu.yaml # Монтируем как файл
            - name: alert-config-memory
              mountPath: /config/rules/memory/alert-rules-memory.yaml
              subPath: alert-rules-memory.yaml # Монтируем как файл
            # ... и так далее
      volumes:
        - name: alert-config-cpu
          configMap:
            name: vmalert-rules-cpu # Имя ConfigMap из шага 3
        - name: alert-config-memory
          configMap:
            name: vmalert-rules-memory # Имя другого ConfigMap
        # ... и так далее
```

### Шаг 5: Развертывание через GitOps (ArgoCD)

После подготовки всех манифестов и их размещения в Git-репозитории, обновите ваше ArgoCD `Application`.

**Было (управление через Helm):**
```yaml
# argocd-app-vmalert.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: vmalert
spec:
  source:
    repoURL: 'https://github.com/VictoriaMetrics/helm-charts.git'
    chart: vmalert
    targetRevision: x.y.z
    helm:
      values: |
        # ... длинный values файл с правилами ...
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: monitoring
```

**Стало (управление через манифесты):**
```yaml
# argocd-app-vmalert.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: vmalert
spec:
  source:
    repoURL: 'https://github.com/my-org/my-k8s-configs.git'
    path: 'monitoring/vmalert' # Путь к директории с вашими манифестами
    targetRevision: main
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: monitoring
```

Теперь добавление новой группы правил сводится к созданию нового `ConfigMap`, добавлению его в `volumes` и `volumeMounts` в `vmalert-deployment.yaml`, и коммиту в Git. ArgoCD автоматически подхватит изменения.

## 3. Устранение неполадок

- **Ошибка `ClusterRoleBinding`**: При синхронизации в ArgoCD может возникнуть ошибка `ClusterRoleBinding is invalid`. Часто это происходит из-за некорректной очистки манифестов. Например, если в `ClusterRoleBinding` из секции `subjects` был удален `namespace`.
  ```yaml
  subjects:
  - kind: ServiceAccount
    name: vmalert
    namespace: monitoring # <-- Убедитесь, что это поле на месте
  ```
- **Правила не применяются**: Убедитесь, что:
    1.  Новый `ConfigMap` с правилами создан в правильном `namespace`.
    2.  `Deployment` обновлен и содержит `volume` и `volumeMount` для нового `ConfigMap`.
    3.  Путь к новому файлу правил добавлен в аргументы запуска (`-rule`) контейнера `vmalert`.
    4.  ArgoCD синхронизировал последнюю версию манифестов.
