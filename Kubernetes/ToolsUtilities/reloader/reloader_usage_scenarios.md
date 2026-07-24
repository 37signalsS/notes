# Reloader — Практические сценарии использования

## Определения

**Сценарии использования Reloader** — типовые конфигурации и примеры применения контроллера Reloader для автоматического обновления рабочих нагрузок (Deployments, StatefulSets, Rollouts) при изменении связанных с ними ресурсов `ConfigMap` и `Secret`.

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Основные концепции

### Механизмы активации

Reloader управляется через аннотации в метаданных объектов. Основные способы отслеживания:

-   **Явное указание:** Аннотации `configmap.reloader.stakater.com/reload` или `secret.reloader.stakater.com/reload`.
-   **Автоматическое обнаружение:** Аннотация `reloader.stakater.com/auto: "true"`.
-   **Стратегия обновления:** В 2026 году рекомендуется использовать `--reload-strategy=annotations` для совместимости с GitOps (ArgoCD/Flux), чтобы избежать состояния OutOfSync.

---

## Практические сценарии

### Сценарий 1: Веб-сервер с динамическим контентом (subPath)

**Задача:** Перезапуск OpenResty при обновлении HTML-файла, смонтированного через `subPath`.
**Особенность:** Без Reloader изменения в `subPath` не синхронизируются внутри контейнера без перезапуска пода (ограничение ядра Linux).

```yaml
# openresty-deployment.yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: web-content
data:
  index.html: "<h1>Version 1.0</h1>"

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openresty
  annotations:
    # Отслеживаем конкретный ConfigMap
    configmap.reloader.stakater.com/reload: "web-content"
spec:
  template:
    spec:
      containers:
        - name: openresty
          image: openresty/openresty:alpine
          volumeMounts:
            - name: html
              mountPath: /usr/local/openresty/nginx/html/index.html
              subPath: index.html
      volumes:
        - name: html
          configMap:
            name: web-content
```

**Проверка срабатывания:**
1.  Обновите ConfigMap: `kubectl patch configmap web-content -p '{"data":{"index.html":"<h1>Version 2.0</h1>"}}'`.
2.  Наблюдайте за перезапуском: `kubectl get pods -w`.
3.  # → result: Старые поды переходят в `Terminating`, новые запускаются.

---

### Сценарий 2: Ротация секретов через Secrets Store CSI Driver

**Задача:** Автоматический перезапуск приложения при обновлении секрета во внешнем хранилище (Vault/AWS/Azure).
**Требование:** Reloader запущен с флагом `--enable-csi-integration=true`.

```yaml
# app-with-csi.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: business-app
  annotations:
    # Reloader следит за SecretProviderClass
    secret.reloader.stakater.com/reload: "vault-db-creds"
spec:
  template:
    spec:
      containers:
        - name: app
          image: my-app:latest
          volumeMounts:
            - name: secrets-store-inline
              mountPath: "/mnt/secrets-store"
              readOnly: true
      volumes:
        - name: secrets-store-inline
          csi:
            driver: secrets-store.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: "vault-db-creds"
```

**Принцип работы:** Когда CSI-драйвер обнаруживает изменение в Vault и обновляет статус `SecretProviderClassPodStatus`, Reloader инициирует Rolling Update.

---

### Сценарий 3: Интеграция с Argo Rollouts (Canary)

**Задача:** При изменении секрета запускать не обычный перезапуск, а Canary-развёртывание через Argo Rollouts.
**Требование:** Reloader запущен с флагом `--is-argo-rollouts=true`.

```yaml
# argo-rollout-example.yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: canary-app
  annotations:
    reloader.stakater.com/auto: "true"
spec:
  replicas: 5
  strategy:
    canary:
      steps:
        - setWeight: 20
        - pause: { duration: 10m }
  template:
    spec:
      containers:
        - name: app
          image: my-app:latest
          envFrom:
            - secretRef:
                name: api-keys
```

**Результат:** При обновлении секрета `api-keys` Reloader обновит `Rollout`, что запустит постепенный перевод трафика (20% на новые поды), вместо мгновенного перезапуска всех реплик.

---

### Сценарий 4: Оптимизация для GitOps (Стратегия аннотаций)

**Задача:** Использование Reloader в кластере под управлением ArgoCD без возникновения конфликтов "OutOfSync".

Если Reloader добавляет переменные окружения (`env-vars`), ArgoCD видит расхождение с Git. Решение — использовать аннотации.

**Настройка контроллера:** `--reload-strategy=annotations`.

**Манифест приложения:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gitops-app
  annotations:
    reloader.stakater.com/auto: "true"
    # Reloader будет записывать хеш сюда:
    # reloader.stakater.com/last-reloaded-from: "..."
spec:
  # ...
```

---

## Дополнительная информация

### Рекомендации по выбору режима

| Режим | Плюсы | Минусы |
| :--- | :--- | :--- |
| **Явный (Explicit)** | Максимальный контроль, отсутствие лишних перезапусков. | Требует ручного перечисления всех ресурсов в аннотациях. |
| **Автоматический (`auto`)** | "Поставил и забыл", работает для всех ENV и Volumes. | Может вызвать каскадный перезапуск при случайном изменении общего ConfigMap. |

### Группировка обновлений (Debounce)

Для предотвращения множественных перезапусков при массовом обновлении секретов используйте аннотацию паузы:
`deployment.reloader.stakater.com/pause-period: "2m"`
# → result: Reloader подождет 2 минуты после первого изменения, соберет все остальные и выполнит один перезапуск.

### См. также
- [Установка и настройка Reloader](./reloader_installation.md)
- [Мониторинг и лучшие практики](./reloader_monitoring_and_best_practices.md)
- [Официальные примеры (GitHub)](https://github.com/stakater/Reloader/tree/master/examples)
