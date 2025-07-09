# Affinity и Anti-Affinity

**Affinity** в Kubernetes — это механизм, который позволяет влиять на решения планировщика (Scheduler) о том, на каких узлах (nodes) будут размещены поды (pods). Это более гибкая и мощная альтернатива `nodeSelector`.

## Типы Affinity

1.  **Node Affinity** — привязка пода к узлам с определёнными метками. Позволяет указать "предпочтительные" или "обязательные" узлы для запуска.
2.  **Pod Affinity/Anti-Affinity** — размещение подов относительно других подов.
    *   **Pod Affinity:** Старается разместить поды на одном узле (или в одной зоне доступности), если на нём уже работают поды с определёнными метками.
    *   **Pod Anti-Affinity:** Старается *не* размещать поды на одном узле, если там уже есть поды с определёнными метками.

---

## Пример использования

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: affinity-demo
spec:
  replicas: 3
  selector:
    matchLabels:
      app: affinity-demo
  template:
    metadata:
      labels:
        app: affinity-demo
    spec:
      affinity:
        # 1. Node Affinity: привязка к узлам
        nodeAffinity:
          # Жесткое правило: под будет запущен ТОЛЬКО на узле с меткой disktype=ssd.
          # IgnoredDuringExecution означает, что если метка на узле изменится, уже запущенный под не будет перемещён.
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: disktype
                    operator: In
                    values:
                      - ssd
          # Мягкое правило: планировщик будет стараться запустить под на узле с меткой zone=east.
          # Если таких узлов нет, под будет запущен на любом другом доступном узле.
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 1 # Приоритет правила (от 1 до 100).
              preference:
                matchExpressions:
                  - key: zone
                    operator: In
                    values:
                      - east
                  # - key: another-label
                  #   operator: Exists # Оператор Exists означает, что под будет запущен на узле, если у него есть метка 'another-label' (значение не важно).

        # 2. Pod Affinity: привязка к другим подам
        podAffinity:
          # Жесткое правило: запускать этот под на том же узле, где уже есть под с меткой app=database.
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app
                    operator: In
                    values:
                      - database
              # topologyKey определяет "область" применения правила.
              # kubernetes.io/hostname означает, что поды должны быть на одном и том же узле.
              topologyKey: kubernetes.io/hostname

        # 3. Pod Anti-Affinity: избегание других подов
        podAntiAffinity:
          # Мягкое правило: стараться не запускать поды этого Deployment'а на одном и том же узле.
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values:
                        - affinity-demo
                topologyKey: kubernetes.io/hostname
      containers:
        - name: nginx
          image: nginx:latest
          ports:
            - containerPort: 80
```