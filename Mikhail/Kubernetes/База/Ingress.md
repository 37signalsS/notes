Ingress управляет внешним доступом к сервисам в кластере. Он НЕ отправляет трафик напрямую к Pod'ам, а всегда работает через объекты типа Service.

Нуждается в Ingress контролере, который следит за изменениями объектом тип Ingress, и на основании полученных данных генерирует конфиг для балансировщика, например, nginx  

``` yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: example-ingress
  annotations:
    # Если используется ingress-контроллер, например, nginx-ingress, могут понадобиться дополнительные аннотации
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
    - host: nnstd.ru 
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: example-service
                port:
                  number: 80
```