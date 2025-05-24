Создание уникальных dns-записей-имена для StatefulSet. Не имеет ClusterIP, резолвиться будет в IP подов за ним. Создаются DNS-записи с именами всех подов

``` yaml
apiVersion: v1
kind: Service
metadata:
  name: my-headless-service
  labels:
	app: rabbitmq
spec:
  clusterIP: None # Указываем "None", чтобы сделать сервис headless
  ports:
    - protocol: TCP
      port: 80 # Порт сервиса
      targetPort: 8080 # Порт, на котором работают ваши поды
  selector:
    app: my-app # Укажите метку, которая соответствует вашим подам
```

 Проверить работоспособность: nslookup имя сервиса (my-headless-service), должно выдать IP адреса подов за ним. Можно также проверить каждый под: nslookup порядковое_имя_пода_созданного_StatefulSet и узнать его IP