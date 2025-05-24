Секреты в кубере по умолчанию закодированы в base64, и могут быть легко раскодированны в исходный вид при помощи команды base 64 -d

generic - пароли/токены приложений(произвольные данные)

docker-registry - данные авторизации в docker registry

tls - tls сертификаты для ingress

Создание секрета - kubectl create secret generic test --from-literal=test1=asdf (будет создан ключ типа generic с названием test а значения ключа test1 and asdf)

``` yaml
apiVersion: v1
kind: Pod
metadata:
  name: example-pod
spec:
  containers:
    - name: example-container
      image: nginx:latest
      env:
#       - name: HARDCODED_ENV
#         value: "значение_захардкоженное"
        - name: SECRET_ENV
          valueFrom:
            secretKeyRef:
              name: my-secret    # имя секрета
              key: secret_key    # ключ, по которому извлекается значение из секрета
```