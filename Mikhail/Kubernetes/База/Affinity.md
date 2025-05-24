Указывает каким образом(с какими labels) и на каких нодах будут запускаться поды

Типы Affinity:

1. **Node Affinity** — определяет, на каких нодах должны запускаться поды.
2. **Pod Affinity/Anti-Affinity** — определяет, с какими другими подами должны или не должны запускаться поды.

``` yaml
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
        # Node Affinity
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution: # если метка измениться когда поды работают, с подами ничего не произойдет, reuired - жесткое ограничение выполнения affinity
            nodeSelectorTerms:
              - matchExpressions:
                  - key: disktype
                    operator: In
                    values:
                      - ssd
          preferredDuringSchedulingIgnoredDuringExecution: # если метка измениться когда поды работают, с подами ничего не произойдет, preferred - мягкое ограничение выполнения affinity, елси под условия ничего не подходит то будет выбрана любая нода
            - weight: 1 # вес - приоритет от 1 до 100
              preference:
                matchExpressions:
                  - key: zone
                    operator: In
                    values:
                      - east
#                   operator: Exists # если key на ноде присутствует, то запускаем на ней
        # Pod Affinity
        podAffinity: # запускать поды с определенными метками на одной ноде
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app
                    operator: In
                    values:
                      - database

              topologyKey: kubernetes.io/hostname
        # Pod Anti-Affinity
        podAntiAffinity: # поды с определенной меткой нельзя запускать на одной ноде
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
