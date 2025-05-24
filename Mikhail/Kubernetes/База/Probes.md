Пробы в кубере бывают: 

liveness - контролирует состояние приложения в течение всего времени его работы. Если проверка не проходит, контейнер будет перезапущен.

readiness - постоянно проверяет готово ли приложение принимать трафик. Если проверка не проходит, Pod удаляется из списка Endpoints Service'а (трафик больше не направляется на этот Pod).

startup - определяет успешный старт, выполняется один раз до момента, пока приложение не будет считаться запущенным.

``` yaml
apiVersion: v1
kind: Pod
metadata:
  name: example-pod
  labels:
    app: example-app
spec:
  containers:
    - name: example-container
      image: nginx:latest
      ports:
        - containerPort: 80
      startupProbe:
        httpGet:
          path: /startup
          port: 80
        initialDelaySeconds: 10
        periodSeconds: 5
        failureThreshold: 30
      livenessProbe:
        httpGet:
          path: /health
          port: 80
        initialDelaySeconds: 5
        periodSeconds: 10
        failureThreshold: 3
      readinessProbe:
        httpGet:
          path: /ready
          port: 80
        initialDelaySeconds: 5
        periodSeconds: 5
        failureThreshold: 3
        successThreshold: 1

#livenessProbe:
#  tcpSocket:
#    port: 8080      # Порт, который нужно проверить
#  initialDelaySeconds: 5  
#  periodSeconds: 10       
#  timeoutSeconds: 1       
#  failureThreshold: 3     

# Выполняет команду внутри контейнера и проверяет её код возврата. Если код # возврата ≠ 0, контейнер будет перезапущен.
#livenessProbe:
#  exec:
#    command:
#      - cat
#      - /tmp/healthy  # Файл, который должен существовать
#  initialDelaySeconds: 5  
#  periodSeconds: 10       
#  failureThreshold: 3     
```

failureThreshold - сколько попыток дано до принудительного рестарта(проба считается неуспешной)

periodSeconds - периодичность между пробами

successThreshold - если выполниться указанной число тестов то проба проходит и пробы обнуляются

initialDelaySeconds - задержка перед первой проверкой после запуска контейнера.

timeoutSeconds - таймаут для выполнения проверки