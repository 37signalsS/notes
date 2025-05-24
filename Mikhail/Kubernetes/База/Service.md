Распределение нагрузки по подам, при обращении к сервису он выдает айпи адрес из clusterip(не всегда, в основном выдается автоматом)(если нет ingress), также создается dns запись на основании имени сервиса

Выбор подов происходит при помощи selector, по меткам(например, my-app)

``` yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:
    app: example
  type: ClusterIP (работает только внутри контейнера) 
  ports:
    - port: 80 # доступен внутри кластера
      targetPort: 80 # куда будет перенаправляться трафик
      protocol: TCP
      nodePort: 30007 # доступ извне
```