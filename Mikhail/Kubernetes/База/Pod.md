В кубере в рамках одного пода создается один namespace где приложения могут локально взаимодействовать, например, постучать на порт. 

Один под - один namespace даже если несколько контейнеров которым нужен общий namespace

Под в кубере- это два контейнера. 

При запуске контейнер создается контейнер по имени пода  с уникальным хэшем и еще один контейнер POD_именяпода который создает сетевой namespace и больше он ничем не занимается.

Для создания пода создается файл pod.yaml(в данном случае вызывается объект pod из апи версии 1)

``` yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
  labels:
    app: my-app
spec:
#  tolerations: # Для taints, DaemonSet
#  - key: "dedicated" # Любой ключ
#    value: "special" # Любое значение
#    effect: "NoSchedule" # Если есть 100% совпадение параметров выше то на ноду будут назначаться поды
#    effect: "NoExecute" # если под уже работает на этом узле, он будет удалён, если не имеет соответствующей toleration.
#    effect: "PreferNoSchedule" # Kubernetes попытается не назначать под на узел с таким taint, но в случае нехватки ресурсов может всё равно назначить его.
  containers:
  - name: my-container
    image: nginx:latest
    ports:
    - containerPort: 80
#  nodeName: worker-node-1  # Указываем конкретную ноду 

```

[[ConfigMap]]

[[Probes]]

[[QOS, limit and requests]]

[[Secret]]

Запуск из файла kubectl create -f pod.yaml(-f нужен для указания файла)

Получить информация  любом объекте в кубере kubectl get