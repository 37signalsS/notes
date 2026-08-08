# Reloader — Практические сценарии использования

## Определения

**Сценарии использования Reloader** — типовые конфигурации и примеры применения контроллера Reloader для автоматического обновления рабочих нагрузок (Deployments, StatefulSets, Rollouts) при изменении связанных с ними ресурсов `ConfigMap` и `Secret`.

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Основные концепции

### Механизмы активации

Reloader управляется через аннотации в метаданных объектов. Основные способы отслеживания:

-   **Явное указание (Explicit):** Аннотации `configmap.reloader.stakater.com/reload: "name"` или `secret.reloader.stakater.com/reload: "name"`. Позволяет точечно управлять перезапусками.
-   **Автоматическое обнаружение (Auto):** Аннотация `reloader.stakater.com/auto: "true"`. Рекомендуется для большинства stateless-приложений.
-   **Стратегия обновления:** В 2026 году стандартом является использование `--reload-strategy=annotations` для совместимости с GitOps (ArgoCD/Flux), чтобы избежать конфликтов состояния (OutOfSync).
-   **Глобальное переопределение (v1.4.19):** Флаг `--ignore-annotation` на уровне контроллера позволяет игнорировать аннотации запрета на уровне отдельных приложений, что полезно для соблюдения политик безопасности платформы.

---

## Практические сценарии

### Сценарий 1: Веб-сервер с динамическим контентом (subPath)

**Задача:** Перезапуск Nginx/OpenResty при обновлении HTML-файла или конфигурации, смонтированной через `subPath`.
**Проблема:** Механизмы Kubernetes не обновляют файлы, смонтированные через `subPath`, без перезапуска пода.

```yaml
# nginx-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-web
  annotations:
    configmap.reloader.stakater.com/reload: "web-config"
spec:
  template:
    spec:
      containers:
        - name: nginx
          image: nginx:alpine
          volumeMounts:
            - name: config
              mountPath: /etc/nginx/nginx.conf
              subPath: nginx.conf
      volumes:
        - name: config
          configMap:
            name: web-config
```

**Проверка:**
1.  Измените данные в ConfigMap `web-config`.
2.  Reloader обнаружит изменение и обновит Deployment.
3.  # → result: Выполнится Rolling Update, новые поды подхватят обновлённый файл.

---

### Сценарий 2: Ротация секретов через Secrets Store CSI Driver

**Задача:** Автоматический перезапуск приложения при обновлении секрета во внешнем хранилище (HashiCorp Vault, AWS Secrets Manager).
**Требование:** Reloader запущен с флагом `--enable-csi-integration=true`.

```yaml
# app-with-csi.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: security-app
  annotations:
    secret.reloader.stakater.com/reload: "app-db-creds"
spec:
  template:
    spec:
      containers:
        - name: app
          image: internal-app:v2
          volumeMounts:
            - name: secrets-store-inline
              mountPath: "/mnt/secrets"
              readOnly: true
      volumes:
        - name: secrets-store-inline
          csi:
            driver: secrets-store.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: "vault-db-creds"
```

**Принцип работы:** Когда CSI-драйвер обновляет локальный Kubernetes Secret (синхронизированный из Vault), Reloader реагирует на изменение этого секрета и инициирует перезапуск.

---

### Сценарий 3: Интеграция с Argo Rollouts (Canary)

**Задача:** Использование Canary-стратегии развёртывания при обновлении конфигурации.
**Требование:** Флаг `--is-argo-rollouts=true`.

```yaml
# argo-rollout-canary.yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: canary-deployment
  annotations:
    reloader.stakater.com/auto: "true"
spec:
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: { duration: 5m }
        - setWeight: 50
        - pause: { duration: 10m }
  template:
    spec:
      containers:
        - name: app
          image: business-logic:latest
          envFrom:
            - configMapRef:
                name: app-params
```

**Результат:** При изменении `app-params` Reloader инициирует не мгновенный Rolling Update, а запуск Canary-процесса, определённого в Rollout.

---

### Сценарий 4: Оптимизация для GitOps (ArgoCD)

**Задача:** Предотвращение состояния OutOfSync в ArgoCD при работе Reloader.

**Решение:**
1.  Установить `--reload-strategy=annotations`.
2.  Настроить ArgoCD на игнорирование аннотации хеша.

```yaml
# ArgoCD Application
apiVersion: argoproj.io/v1alpha1
kind: Application
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

---

### Сценарий 5: Глобальное принудительное обновление (Platform Policy)

**Задача:** Игнорирование аннотации `reloader.stakater.com/ignore: "true"` для обеспечения безопасности (например, принудительная ротация TLS-сертификатов).

**Контекст:** Разработчик пометил приложение аннотацией `ignore`, но администратор платформы запустил Reloader с флагом `--ignore-annotation=true`.

**Манифест приложения:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: legacy-app
  annotations:
    reloader.stakater.com/ignore: "true" # Будет проигнорировано контроллером
    reloader.stakater.com/auto: "true"
spec:
  # ...
```

**Результат:** Несмотря на наличие аннотации `ignore`, Reloader выполнит перезапуск при обновлении связанных ресурсов.

---

## Дополнительная информация

### Рекомендации по выбору режима отслеживания

| Режим | Когда применять | Особенности |
| :--- | :--- | :--- |
| **Явный (Explicit)** | Критические системы, БД, StatefulSets | Исключает случайные перезапуски при изменении соседних ресурсов. |
| **Автоматический (`auto`)** | Stateless микросервисы, Dev/Stage среды | Максимальное удобство, автоматический охват всех ENV и Volumes. |

### Группировка обновлений (Debounce)

Для предотвращения "шторма" перезапусков при массовом обновлении нескольких ConfigMap/Secret используйте задержку:

```yaml
metadata:
  annotations:
    deployment.reloader.stakater.com/pause-period: "1m"
```
# → result: Reloader подождет 1 минуту после первого события, соберет все изменения и выполнит ровно один Rolling Update.

### См. также
- [Установка и настройка Reloader](./reloader_installation.md)
- [Мониторинг и лучшие практики](./reloader_monitoring_and_best_practices.md)
- [Официальный GitHub Stakater/Reloader](https://github.com/stakater/Reloader)
