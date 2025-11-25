# Трюк: Автоматический Rollout при изменении ConfigMap в Kubernetes

По умолчанию Kubernetes **НЕ** перезапускает поды Deployment'а автоматически при изменении связанного ConfigMap. Это может привести к тому, что приложение продолжит работать со старой конфигурацией, пока Deployment не будет перезапущен вручную.

## Проблема

ConfigMap'ы — отличный способ управлять конфигурацией приложений. Однако, если вы обновляете ConfigMap, используемый Deployment'ом, поды Deployment'а не узнают об изменении и не перезапустятся, чтобы загрузить новую конфигурацию. Это требует ручного вмешательства (например, `kubectl rollout restart deployment/<name>`).

## Решение: ConfigMap Rollout Trick

Чтобы Deployment автоматически перезапускался при каждом обновлении ConfigMap, можно использовать следующую хитрость: добавьте хеш содержимого ConfigMap в аннотацию Pod Template.

### Принцип работы

При каждом изменении ConfigMap его хеш изменится. Поскольку этот хеш включён в аннотацию шаблона пода (`spec.template.metadata.annotations`), Kubernetes воспримет это как изменение спецификации пода. В результате Kubernetes автоматически инициирует `rollout` (обновление) Deployment'а, что приведёт к перезапуску подов и загрузке ими новой конфигурации.

Этот способ устраняет необходимость ручных перезапусков, снижает вероятность ошибок конфигураций и экономит время.

### Пример реализации

В YAML-файле вашего Deployment'а добавьте аннотацию `config-hash` в `spec.template.metadata.annotations`, используя хеш содержимого ConfigMap (например, с помощью функции `sha256sum` из вашего CI/CD инструмента или шаблонизатора, такого как Helm).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        # Эта аннотация заставит Deployment перезапуститься при изменении my-config
        # В реальной системе {{ sha256sum .Values.myConfig }} будет заменено на фактический хеш ConfigMap
        config-hash: "{{ sha256sum .Values.myConfig }}"
    spec:
      containers:
      - name: app
        image: myimage:latest
        volumeMounts:
        - name: cfg
          mountPath: /app/config # Путь монтирования ConfigMap
      volumes:
      - name: cfg
        configMap:
          name: my-config # Имя ConfigMap, который будет отслеживаться
```

**Примечание:** В реальных системах, таких как Helm, `.Values.myConfig` будет представлять содержимое или имя вашего ConfigMap, от которого будет вычисляться хеш.
